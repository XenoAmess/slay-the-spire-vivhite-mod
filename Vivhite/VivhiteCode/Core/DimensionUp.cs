using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;

namespace Vivhite.Core;

public readonly record struct DimensionUpResult(
    int Requested,
    int InfiniteExtensionStacks,
    int InfiniteExtensionBonus,
    int RequestedTotal,
    int MaxHpGained,
    int MaxHpBefore,
    int MaxHpAfter,
    int CurrentHpBefore,
    int CurrentHpAfter,
    int CombatGrowthBefore,
    int CombatGrowthAfter);

/// <summary>
/// Permanent, uncapped max-HP growth used by Dimension Up. Native GainMaxHp immediately heals by
/// the actual max-HP increase. Every Infinite Extension stack contributes once to the outer call;
/// it never invokes DimensionUp recursively. InfiniteDimensionalityPower is the
/// combat-local growth marker and naturally disappears with other combat powers.
/// </summary>
public static class DimensionUp
{
    /// <summary>
    /// Pure, uncapped expansion calculation for previews and contract tests.
    /// </summary>
    public static (int InfiniteExtensionBonus, int RequestedTotal) Calculate(
        int amount,
        int infiniteExtensionStacks)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(amount);
        ArgumentOutOfRangeException.ThrowIfNegative(infiniteExtensionStacks);

        var bonus = amount > 0 ? infiniteExtensionStacks : 0;
        return (bonus, checked(amount + bonus));
    }

    public static Task<DimensionUpResult> ApplyAsync(
        PlayerChoiceContext choiceContext,
        Creature creature,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silentMarker = false)
    {
        return GainMaxHpAsync(
            choiceContext,
            creature,
            amount,
            applier,
            cardSource,
            silentMarker);
    }

    public static async Task<DimensionUpResult> GainMaxHpAsync(
        PlayerChoiceContext choiceContext,
        Creature creature,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silentMarker = false)
    {
        ArgumentNullException.ThrowIfNull(choiceContext);
        ArgumentNullException.ThrowIfNull(creature);
        ArgumentOutOfRangeException.ThrowIfNegative(amount);

        var maxHpBefore = creature.MaxHp;
        var currentHpBefore = creature.CurrentHp;
        var growthBefore = InfiniteDimensionality.GetAmount(creature);
        var extensionStacks = InfiniteExtension.GetAmount(creature);
        var (extensionBonus, requestedTotal) = Calculate(amount, extensionStacks);

        if (requestedTotal > 0)
        {
            await CreatureCmd.GainMaxHp(creature, requestedTotal);
        }

        var maxHpAfter = creature.MaxHp;
        var actualGain = Math.Max(0, maxHpAfter - maxHpBefore);
        if (actualGain > 0)
        {
            await InfiniteDimensionality.GainAsync(
                choiceContext,
                creature,
                actualGain,
                applier ?? creature,
                cardSource,
                silentMarker);
        }

        return new DimensionUpResult(
            amount,
            extensionStacks,
            extensionBonus,
            requestedTotal,
            actualGain,
            maxHpBefore,
            maxHpAfter,
            currentHpBefore,
            creature.CurrentHp,
            growthBefore,
            InfiniteDimensionality.GetAmount(creature));
    }
}
