using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Powers;
using MegaCrit.Sts2.Core.ValueProps;

namespace Vivhite.Core;

public sealed record DrainRecoveryContext(
    PlayerChoiceContext ChoiceContext,
    Creature Recipient,
    int Amount,
    Creature Applier,
    CardModel? CardSource = null,
    CardPlay? CardPlay = null,
    bool PlayHealAnimation = true);

public sealed record DrainRecoveryOutcome(
    int Requested,
    int Healed = 0,
    int UnconvertedExcess = 0,
    int BlockGained = 0,
    int StrengthGained = 0,
    int MarginGained = 0,
    int MaxHpGained = 0)
{
    public int Converted => BlockGained + StrengthGained + MarginGained + MaxHpGained;
}

public delegate Task<DrainRecoveryOutcome> DrainRecoveryHandler(DrainRecoveryContext context);

/// <summary>
/// Built-in 1:1 destinations for drain recovery. HealThen composes overheal with any destination,
/// e.g. DrainRecovery.HealThen(DrainRecovery.MarginAsync).
/// </summary>
public static class DrainRecovery
{
    public static async Task<DrainRecoveryOutcome> HealAsync(DrainRecoveryContext context)
    {
        Validate(context);
        var healing = await Overheal.HealAsync(
            context.Recipient,
            context.Amount,
            context.PlayHealAnimation);
        return new DrainRecoveryOutcome(
            context.Amount,
            Healed: healing.Healed,
            UnconvertedExcess: healing.Excess);
    }

    public static async Task<DrainRecoveryOutcome> BlockAsync(DrainRecoveryContext context)
    {
        Validate(context);
        var gained = await CreatureCmd.GainBlock(
            context.Recipient,
            context.Amount,
            ValueProp.Move,
            context.CardPlay);
        return new DrainRecoveryOutcome(
            context.Amount,
            BlockGained: Math.Max(0, decimal.ToInt32(decimal.Truncate(gained))));
    }

    public static async Task<DrainRecoveryOutcome> StrengthAsync(DrainRecoveryContext context)
    {
        Validate(context);
        var before = context.Recipient.GetPowerAmount<StrengthPower>();
        await PowerCmd.Apply<StrengthPower>(
            context.ChoiceContext,
            context.Recipient,
            context.Amount,
            context.Applier,
            context.CardSource);
        var after = context.Recipient.GetPowerAmount<StrengthPower>();
        return new DrainRecoveryOutcome(
            context.Amount,
            StrengthGained: Math.Max(0, after - before));
    }

    public static async Task<DrainRecoveryOutcome> MarginAsync(DrainRecoveryContext context)
    {
        Validate(context);
        var before = InfiniteMargin.GetAmount(context.Recipient);
        await InfiniteMargin.GainAsync(
            context.ChoiceContext,
            context.Recipient,
            context.Amount,
            context.Applier,
            context.CardSource);
        var after = InfiniteMargin.GetAmount(context.Recipient);
        return new DrainRecoveryOutcome(
            context.Amount,
            MarginGained: Math.Max(0, after - before));
    }

    public static async Task<DrainRecoveryOutcome> GrowthAsync(DrainRecoveryContext context)
    {
        Validate(context);
        var growth = await DimensionUp.GainMaxHpAsync(
            context.ChoiceContext,
            context.Recipient,
            context.Amount,
            context.Applier,
            context.CardSource);
        return new DrainRecoveryOutcome(
            context.Amount,
            MaxHpGained: growth.MaxHpGained);
    }

    public static DrainRecoveryHandler HealThen(DrainRecoveryHandler excessHandler)
    {
        ArgumentNullException.ThrowIfNull(excessHandler);
        return async context =>
        {
            var healing = await HealAsync(context);
            if (healing.UnconvertedExcess == 0)
            {
                return healing;
            }

            var converted = await excessHandler(
                context with { Amount = healing.UnconvertedExcess });
            return new DrainRecoveryOutcome(
                context.Amount,
                healing.Healed + converted.Healed,
                converted.UnconvertedExcess,
                converted.BlockGained,
                converted.StrengthGained,
                converted.MarginGained,
                converted.MaxHpGained);
        };
    }

    private static void Validate(DrainRecoveryContext context)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(context.ChoiceContext);
        ArgumentNullException.ThrowIfNull(context.Recipient);
        ArgumentNullException.ThrowIfNull(context.Applier);
        ArgumentOutOfRangeException.ThrowIfNegative(context.Amount);
    }
}
