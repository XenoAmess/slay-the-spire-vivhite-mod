using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Commands.Builders;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Powers;
using MegaCrit.Sts2.Core.ValueProps;
using Vivhite.Cards.Common;
using Vivhite.Core;

namespace Vivhite.Cards.Chromatic;

/// <summary>
/// C-suit composition around Common.ExecuteDrainAttackAsync. The Common wrapper remains the only
/// attack entry point, preserving Unified Field Theory's Drain-to-Margin callback.
/// </summary>
public static class ChromaticDrainMechanics
{
    public static async Task<InfiniteDrainResult> ExecuteDrainAttackAsync(
        PlayerChoiceContext choiceContext,
        AttackCommand attackCommand,
        CardModel card,
        CardPlay cardPlay,
        decimal cardPercent)
    {
        ArgumentNullException.ThrowIfNull(choiceContext);
        ArgumentNullException.ThrowIfNull(attackCommand);
        ArgumentNullException.ThrowIfNull(card);
        ArgumentNullException.ThrowIfNull(cardPlay);
        ArgumentOutOfRangeException.ThrowIfNegative(cardPercent);

        return await VivhiteCardRules.ExecuteDrainAttackAsync(
            choiceContext,
            attackCommand,
            card,
            cardPlay,
            cardPercent,
            RecoverAndConvertAsync);
    }

    /// <summary>
    /// Heal first, then use only the actual HP increase for all three C-suit conversions. Each
    /// call is one complete card-level Drain resolution, so no hit can trigger Canvas twice.
    /// </summary>
    public static async Task<DrainRecoveryOutcome> RecoverAndConvertAsync(
        DrainRecoveryContext context)
    {
        var healing = await DrainRecovery.HealAsync(context);
        var actualHealing = healing.Healed;
        if (actualHealing <= 0)
        {
            return healing;
        }

        ChromaticTurnHealing.ObserveCurrentHp(context.Recipient);

        var blockGained = await GainConservationBlockAsync(context, actualHealing);
        var strengthGained = await GainConservationStrengthAsync(context, actualHealing);
        await GrowCanvasDrainAsync(context, actualHealing);

        return healing with
        {
            BlockGained = blockGained,
            StrengthGained = strengthGained
        };
    }

    private static async Task<int> GainConservationBlockAsync(
        DrainRecoveryContext context,
        int actualHealing)
    {
        var power = context.Recipient.GetPower<ColorConservationPower>();
        var stacks = Math.Max(0, power?.Amount ?? 0);
        if (stacks == 0)
        {
            return 0;
        }

        power!.Flash();
        var requested = checked(actualHealing * stacks);
        var gained = await CreatureCmd.GainBlock(
            context.Recipient,
            requested,
            ValueProp.Move,
            context.CardPlay);
        return Math.Max(0, decimal.ToInt32(decimal.Truncate(gained)));
    }

    private static async Task<int> GainConservationStrengthAsync(
        DrainRecoveryContext context,
        int actualHealing)
    {
        var normalPower = context.Recipient.GetPower<CrimsonConservationLawPower>();
        var upgradedPower = context.Recipient.GetPower<CrimsonConservationLawUpgradedPower>();
        var normalStacks = Math.Max(0, normalPower?.Amount ?? 0);
        var upgradedStacks = Math.Max(0, upgradedPower?.Amount ?? 0);
        var strength = checked(
            (normalStacks * (actualHealing / 5)) +
            (upgradedStacks * (actualHealing / 4)));
        if (strength == 0)
        {
            return 0;
        }

        normalPower?.Flash();
        upgradedPower?.Flash();
        var before = context.Recipient.GetPowerAmount<StrengthPower>();
        await PowerCmd.Apply<StrengthPower>(
            context.ChoiceContext,
            context.Recipient,
            strength,
            context.Applier,
            context.CardSource);
        var after = context.Recipient.GetPowerAmount<StrengthPower>();
        return Math.Max(0, after - before);
    }

    private static async Task GrowCanvasDrainAsync(
        DrainRecoveryContext context,
        int actualHealing)
    {
        if (actualHealing <= 0)
        {
            return;
        }

        var normalPower = context.Recipient.GetPower<InfiniteCanvasPower>();
        var upgradedPower = context.Recipient.GetPower<InfiniteCanvasUpgradedPower>();
        var normalStacks = Math.Max(0, normalPower?.Amount ?? 0);
        var upgradedStacks = Math.Max(0, upgradedPower?.Amount ?? 0);
        var growth = checked((normalStacks * 2) + (upgradedStacks * 3));
        if (growth == 0)
        {
            return;
        }

        normalPower?.Flash();
        upgradedPower?.Flash();
        await InfiniteDrain.GainGlobalPercentAsync(
            context.ChoiceContext,
            context.Recipient,
            growth,
            context.Recipient,
            context.CardSource);
    }
}
