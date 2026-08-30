using System.Runtime.CompilerServices;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Commands.Builders;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using Vivhite.Cards.Common;
using Vivhite.Core;

namespace Vivhite.Cards.Chromatic;

/// <summary>
/// Shared C-suit base. Life payment remains sealed in Common.VivhiteLifeCalculationCard,
/// while this class only contributes the exact LifeCost dynamic variable and local helpers.
/// </summary>
public abstract class ChromaticCard : VivhiteLifeCalculationCard
{
    private readonly int _lifeCalculationCost;

    protected ChromaticCard(
        int energyCost,
        CardType type,
        CardRarity rarity,
        TargetType targetType,
        int lifeCalculationCost)
        : base(energyCost, type, rarity, targetType)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(lifeCalculationCost);
        _lifeCalculationCost = lifeCalculationCost;
    }

    protected sealed override int LifeCalculationCost => _lifeCalculationCost;

    protected virtual IEnumerable<DynamicVar> ChromaticVars => [];

    protected sealed override IEnumerable<DynamicVar> CanonicalVars =>
        [new HpLossVar("LifeCost", LifeCalculationCost), .. ChromaticVars];

    protected virtual IEnumerable<CardKeyword> ChromaticKeywords => [];

    protected sealed override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        ChromaticKeywords;

    protected bool CurrentHpIncreasedThisTurn =>
        ChromaticTurnHealing.HasIncreased(Owner.Creature);

    public override Task AfterCurrentHpChanged(Creature creature, decimal delta)
    {
        if (delta > 0m && ReferenceEquals(creature, Owner.Creature))
        {
            ChromaticTurnHealing.Mark(creature);
        }

        return Task.CompletedTask;
    }

    public override Task BeforeSideTurnStart(
        PlayerChoiceContext choiceContext,
        CombatSide side,
        IReadOnlyList<Creature> participants,
        ICombatState combatState)
    {
        if (participants.Any(creature => ReferenceEquals(creature, Owner.Creature)))
        {
            ChromaticTurnHealing.Reset(Owner.Creature);
        }

        return Task.CompletedTask;
    }

    protected Task<InfiniteDrainResult> DrainTargetAsync(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        decimal cardPercent,
        int hitCount = 1)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);

        var attack = DamageCmd.Attack(DynamicVars.Damage.BaseValue)
            .WithHitCount(hitCount)
            .FromCard(this, cardPlay)
            .Targeting(cardPlay.Target);
        return ChromaticDrainMechanics.ExecuteDrainAttackAsync(
            choiceContext,
            attack,
            this,
            cardPlay,
            cardPercent);
    }

    protected Task<InfiniteDrainResult> DrainAllAsync(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        decimal cardPercent,
        int hitCount = 1)
    {
        var combatState = CombatState ??
            throw new InvalidOperationException("Chromatic AoE attacks require an active combat.");
        var attack = DamageCmd.Attack(DynamicVars.Damage.BaseValue)
            .WithHitCount(hitCount)
            .FromCard(this, cardPlay)
            .TargetingAllOpponents(combatState);
        return ChromaticDrainMechanics.ExecuteDrainAttackAsync(
            choiceContext,
            attack,
            this,
            cardPlay,
            cardPercent);
    }
}

/// <summary>
/// A weak-keyed turn fact used by Complementary Afterimage. Every C-suit card listens for the
/// owner's native HP-change hook, so ordinary healing, kill healing, and Drain all count.
/// </summary>
public static class ChromaticTurnHealing
{
    private sealed class State
    {
        public bool Increased;
    }

    private static readonly ConditionalWeakTable<Creature, State> States = new();

    public static bool HasIncreased(Creature creature)
    {
        ArgumentNullException.ThrowIfNull(creature);
        return States.TryGetValue(creature, out var state) && state.Increased;
    }

    public static void Mark(Creature creature)
    {
        ArgumentNullException.ThrowIfNull(creature);
        States.GetOrCreateValue(creature).Increased = true;
    }

    public static void Reset(Creature creature)
    {
        ArgumentNullException.ThrowIfNull(creature);
        States.GetOrCreateValue(creature).Increased = false;
    }
}
