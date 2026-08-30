using MegaCrit.Sts2.Core.Commands.Builders;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using Vivhite.Cards.Hybrid;
using Vivhite.Core;

namespace Vivhite.Cards.Common;

/// <summary>
/// Card-facing entry points around the shared Core rules. Keeping these wrappers here lets all
/// three suits participate in cross-suit powers without copying payment or drain arithmetic.
/// </summary>
public static class VivhiteCardRules
{
    public static async Task<LifePaymentResult> PayThenAsync(
        PlayerChoiceContext choiceContext,
        CardModel card,
        CardPlay cardPlay,
        int amount,
        Func<LifePaymentResult, Task> effect)
    {
        ArgumentNullException.ThrowIfNull(effect);

        return await LifeCalculation.PayThenAsync(
            choiceContext,
            card,
            cardPlay,
            amount,
            async payment =>
            {
                await UnifiedFieldTheoryMechanics.AfterMarginPreventedAsync(
                    choiceContext,
                    card.Owner.Creature,
                    payment.MarginConsumed,
                    card,
                    cardPlay);
                await effect(payment);
            });
    }

    public static async Task<InfiniteDrainResult> ExecuteDrainAttackAsync(
        PlayerChoiceContext choiceContext,
        AttackCommand attackCommand,
        CardModel card,
        CardPlay cardPlay,
        decimal cardPercent,
        DrainRecoveryHandler? recoveryHandler = null)
    {
        ArgumentNullException.ThrowIfNull(attackCommand);
        ArgumentNullException.ThrowIfNull(card);
        ArgumentNullException.ThrowIfNull(cardPlay);

        var result = await InfiniteDrain.ExecuteAttackAsync(
            choiceContext,
            attackCommand,
            card.Owner.Creature,
            cardPercent,
            recoveryHandler,
            card,
            cardPlay);

        await UnifiedFieldTheoryMechanics.AfterDrainRecoveryAsync(
            choiceContext,
            card.Owner.Creature,
            result.ActualHealing,
            card);
        return result;
    }
}
