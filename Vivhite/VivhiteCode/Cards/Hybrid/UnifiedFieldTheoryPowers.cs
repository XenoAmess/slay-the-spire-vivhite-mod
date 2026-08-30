using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using STS2RitsuLib.Interop.AutoRegistration;
using Vivhite.Core;
using Vivhite.Powers;

namespace Vivhite.Cards.Hybrid;

/// <summary>
/// Each stack is one unupgraded copy of Unified Field Theory.
/// </summary>
[RegisterPower]
public sealed class UnifiedFieldTheoryPower : VivhiteCounterPower;

/// <summary>
/// Kept separate so upgraded and unupgraded copies preserve their distinct recovery divisors.
/// </summary>
[RegisterPower]
public sealed class UnifiedFieldTheoryUpgradedPower : VivhiteCounterPower;

public static class UnifiedFieldTheoryMechanics
{
    internal const int DrainPercentPerMarginPerStack = 4;

    public static async Task AfterMarginPreventedAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int marginPrevented,
        CardModel cardSource,
        CardPlay cardPlay)
    {
        ArgumentNullException.ThrowIfNull(choiceContext);
        ArgumentNullException.ThrowIfNull(owner);
        ArgumentNullException.ThrowIfNull(cardSource);
        ArgumentNullException.ThrowIfNull(cardPlay);
        ArgumentOutOfRangeException.ThrowIfNegative(marginPrevented);

        if (marginPrevented == 0)
        {
            return;
        }

        var normal = owner.GetPowerAmount<UnifiedFieldTheoryPower>();
        var upgraded = owner.GetPowerAmount<UnifiedFieldTheoryUpgradedPower>();
        var percentPerMargin = checked(
            (normal + upgraded) * DrainPercentPerMarginPerStack);
        var percent = checked(marginPrevented * percentPerMargin);
        if (percent == 0)
        {
            return;
        }

        owner.GetPower<UnifiedFieldTheoryPower>()?.Flash();
        owner.GetPower<UnifiedFieldTheoryUpgradedPower>()?.Flash();
        await InfiniteDrain.GainGlobalPercentAsync(
            choiceContext,
            owner,
            percent,
            owner,
            cardSource);
    }

    public static async Task AfterDrainRecoveryAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int actualHealing,
        CardModel cardSource)
    {
        ArgumentNullException.ThrowIfNull(choiceContext);
        ArgumentNullException.ThrowIfNull(owner);
        ArgumentNullException.ThrowIfNull(cardSource);
        ArgumentOutOfRangeException.ThrowIfNegative(actualHealing);

        if (actualHealing == 0)
        {
            return;
        }

        var normal = owner.GetPowerAmount<UnifiedFieldTheoryPower>();
        var upgraded = owner.GetPowerAmount<UnifiedFieldTheoryUpgradedPower>();
        var margin = (normal * (actualHealing / 3)) +
                     (upgraded * (actualHealing / 2));
        if (margin == 0)
        {
            return;
        }

        owner.GetPower<UnifiedFieldTheoryPower>()?.Flash();
        owner.GetPower<UnifiedFieldTheoryUpgradedPower>()?.Flash();
        await InfiniteMargin.GainAsync(
            choiceContext,
            owner,
            margin,
            owner,
            cardSource);
    }
}
