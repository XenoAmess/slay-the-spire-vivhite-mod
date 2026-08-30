using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Creatures;

namespace Vivhite.Core;

public readonly record struct OverhealQuote(
    int Requested,
    int MissingHp,
    int ExpectedHealing,
    int ExpectedExcess);

public readonly record struct OverhealResult(
    OverhealQuote Quote,
    int HpBefore,
    int HpAfter,
    int Healed,
    int Excess)
{
    public bool HasExcess => Excess > 0;
}

/// <summary>
/// Splits healing into native healing and excess healing without bypassing CreatureCmd.
/// </summary>
public static class Overheal
{
    public static bool ShouldInvokeNativeHeal(bool creatureIsAlive, int amount)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(amount);
        return creatureIsAlive && amount > 0;
    }

    public static OverhealQuote Calculate(Creature creature, int amount)
    {
        ArgumentNullException.ThrowIfNull(creature);
        return Calculate(creature.CurrentHp, creature.MaxHp, creature.IsAlive, amount);
    }

    /// <summary>
    /// Pure overload for previews and contract tests.
    /// </summary>
    public static OverhealQuote Calculate(
        int currentHp,
        int maxHp,
        bool creatureIsAlive,
        int amount)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(currentHp);
        ArgumentOutOfRangeException.ThrowIfNegative(maxHp);
        ArgumentOutOfRangeException.ThrowIfNegative(amount);

        var missingHp = creatureIsAlive
            ? Math.Max(0, maxHp - currentHp)
            : 0;
        var expectedHealing = Math.Min(amount, missingHp);

        return new OverhealQuote(
            amount,
            missingHp,
            expectedHealing,
            amount - expectedHealing);
    }

    public static async Task<OverhealResult> HealAsync(
        Creature creature,
        int amount,
        bool playAnim = true)
    {
        var quote = Calculate(creature, amount);
        var hpBefore = creature.CurrentHp;

        if (ShouldInvokeNativeHeal(creature.IsAlive, amount))
        {
            // Deliver the full request even at full HP so native HP-change observers can convert
            // all excess healing. Suppress only the animation when no HP can actually be restored.
            await CreatureCmd.Heal(creature, amount, playAnim && quote.ExpectedHealing > 0);
        }

        var hpAfter = creature.CurrentHp;
        var healed = Math.Max(0, hpAfter - hpBefore);
        return new OverhealResult(
            quote,
            hpBefore,
            hpAfter,
            healed,
            Math.Max(0, amount - healed));
    }
}
