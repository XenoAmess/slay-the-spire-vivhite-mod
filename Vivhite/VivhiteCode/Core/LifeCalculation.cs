using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.ValueProps;

namespace Vivhite.Core;

public enum LifePaymentFailure
{
    None,
    PayerIsDead,
    InsufficientLife,
    LifeChangedDuringPayment,
    /// <summary>
    /// The native HP-loss command did not return a result for the payer.  A result with zero
    /// <see cref="DamageResult.UnblockedDamage"/> is still an applied command (for example,
    /// when Buffer prevents the loss).
    /// </summary>
    PaymentWasPrevented
}

/// <summary>
/// Side-effect-free quote for Life Calculation. The effective request is never below zero;
/// Margin offsets it 1:1 before the remaining HP requirement is checked, and HP payment always
/// leaves at least one HP.
/// </summary>
public readonly record struct LifePaymentQuote(
    int Requested,
    int CurrentHp,
    int MarginAvailable,
    int MarginConsumed,
    int HpRequired,
    int MaximumHpPayable,
    bool CanPay);

/// <summary>
/// Observed payment result. Card effects may use MarginConsumed for "margin spent by this card"
/// clauses and must only resolve when Succeeded is true.
/// </summary>
public sealed record LifePaymentResult(
    LifePaymentQuote Quote,
    LifePaymentFailure Failure,
    int Requested,
    int MarginConsumed,
    int HpPaid,
    int HpBefore,
    int HpAfter,
    IReadOnlyList<DamageResult> DamageResults)
{
    public bool Succeeded => Failure == LifePaymentFailure.None;
    public int TotalPaid => MarginConsumed + HpPaid;
}

/// <summary>
/// Shared HP-cost contract for Vivhite cards.
/// </summary>
public static class LifeCalculation
{
    /// <summary>
    /// Matches native self-HP-loss cards while preserving normal damage and HP-change hooks.
    /// </summary>
    public const ValueProp PaymentProps =
        ValueProp.Unblockable | ValueProp.Unpowered | ValueProp.Move;

    public static LifePaymentQuote Calculate(Creature payer, int amount)
    {
        ArgumentNullException.ThrowIfNull(payer);
        return Calculate(payer.CurrentHp, InfiniteMargin.GetAmount(payer), payer.IsAlive, amount);
    }

    /// <summary>
    /// Pure overload for previews and contract tests.
    /// </summary>
    public static LifePaymentQuote Calculate(
        int currentHp,
        int marginAvailable,
        bool payerIsAlive,
        int amount)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(currentHp);
        ArgumentOutOfRangeException.ThrowIfNegative(marginAvailable);

        var requested = Math.Max(0, amount);
        var marginConsumed = Math.Min(requested, marginAvailable);
        var hpRequired = requested - marginConsumed;
        var maximumHpPayable = payerIsAlive ? Math.Max(0, currentHp - 1) : 0;

        return new LifePaymentQuote(
            requested,
            currentHp,
            marginAvailable,
            marginConsumed,
            hpRequired,
            maximumHpPayable,
            payerIsAlive && hpRequired <= maximumHpPayable);
    }

    public static bool CanPay(Creature payer, int amount)
    {
        return Calculate(payer, amount).CanPay;
    }

    public static bool CanPay(CardModel card, int amount)
    {
        ArgumentNullException.ThrowIfNull(card);
        return CanPay(card.Owner.Creature, amount);
    }

    /// <summary>
    /// Checks whether the native HP-loss command reached the payer and completed while the payer
    /// remained alive.  A <see cref="DamageResult"/> reports the HP that was actually lost, not
    /// the amount requested by the command.  Native modifiers such as Tungsten Rod (and Buffer)
    /// are therefore allowed to reduce that value without turning an otherwise completed
    /// self-HP-loss command into a failed card payment.  A zero-loss result is intentionally still
    /// accepted: the engine emits it for native prevention effects such as Buffer, and native
    /// self-HP-loss cards continue their effects after that command.
    /// </summary>
    internal static bool WasHpPaymentApplied(
        Creature payer,
        IReadOnlyCollection<DamageResult> damageResults)
    {
        ArgumentNullException.ThrowIfNull(payer);
        ArgumentNullException.ThrowIfNull(damageResults);

        return payer.IsAlive &&
               damageResults.Any(result => ReferenceEquals(result.Receiver, payer));
    }

    public static Task<LifePaymentResult> TryPayAsync(
        PlayerChoiceContext choiceContext,
        CardModel card,
        CardPlay cardPlay,
        int amount)
    {
        ArgumentNullException.ThrowIfNull(card);
        ArgumentNullException.ThrowIfNull(cardPlay);

        return TryPayAsync(
            choiceContext,
            card.Owner.Creature,
            amount,
            card,
            cardPlay);
    }

    public static async Task<LifePaymentResult> TryPayAsync(
        PlayerChoiceContext choiceContext,
        Creature payer,
        int amount,
        CardModel? cardSource = null,
        CardPlay? cardPlay = null)
    {
        ArgumentNullException.ThrowIfNull(choiceContext);
        ArgumentNullException.ThrowIfNull(payer);

        var quote = Calculate(payer, amount);
        var requested = quote.Requested;
        var hpBefore = payer.CurrentHp;
        if (!quote.CanPay)
        {
            return Failed(
                quote,
                payer.IsAlive
                    ? LifePaymentFailure.InsufficientLife
                    : LifePaymentFailure.PayerIsDead,
                hpBefore,
                payer.CurrentHp);
        }

        var marginPayment = await InfiniteMargin.ConsumeUpToAsync(
            choiceContext,
            payer,
            requested,
            payer,
            cardSource);
        var marginConsumed = marginPayment.Consumed;
        var hpRequired = requested - marginConsumed;

        // A power-change hook may have changed HP while margin was being consumed. Recheck at the
        // command boundary; never issue a payment that can reduce the payer to zero.
        if (!payer.IsAlive || hpRequired > payer.CurrentHp - 1)
        {
            return new LifePaymentResult(
                quote,
                payer.IsAlive
                    ? LifePaymentFailure.LifeChangedDuringPayment
                    : LifePaymentFailure.PayerIsDead,
                requested,
                marginConsumed,
                0,
                hpBefore,
                payer.CurrentHp,
                Array.Empty<DamageResult>());
        }

        if (hpRequired == 0)
        {
            return new LifePaymentResult(
                quote,
                LifePaymentFailure.None,
                requested,
                marginConsumed,
                0,
                hpBefore,
                payer.CurrentHp,
                Array.Empty<DamageResult>());
        }

        var damageResults = (await CreatureCmd.Damage(
                choiceContext,
                payer,
                hpRequired,
                PaymentProps,
                cardSource,
                cardPlay))
            .ToArray();
        var hpPaid = damageResults
            .Where(result => ReferenceEquals(result.Receiver, payer))
            .Sum(result => result.UnblockedDamage);
        var succeeded = WasHpPaymentApplied(payer, damageResults);

        return new LifePaymentResult(
            quote,
            succeeded
                ? LifePaymentFailure.None
                : LifePaymentFailure.PaymentWasPrevented,
            requested,
            marginConsumed,
            hpPaid,
            hpBefore,
            payer.CurrentHp,
            damageResults);
    }

    /// <summary>
    /// Executes effect only after a complete payment. This is the helper form for cards that
    /// cannot derive from LifeCalculationCard.
    /// </summary>
    public static async Task<LifePaymentResult> PayThenAsync(
        PlayerChoiceContext choiceContext,
        CardModel card,
        CardPlay cardPlay,
        int amount,
        Func<LifePaymentResult, Task> effect)
    {
        ArgumentNullException.ThrowIfNull(effect);
        var payment = await TryPayAsync(choiceContext, card, cardPlay, amount);
        if (payment.Succeeded)
        {
            await effect(payment);
        }

        return payment;
    }

    private static LifePaymentResult Failed(
        LifePaymentQuote quote,
        LifePaymentFailure failure,
        int hpBefore,
        int hpAfter)
    {
        return new LifePaymentResult(
            quote,
            failure,
            quote.Requested,
            0,
            0,
            hpBefore,
            hpAfter,
            Array.Empty<DamageResult>());
    }
}
