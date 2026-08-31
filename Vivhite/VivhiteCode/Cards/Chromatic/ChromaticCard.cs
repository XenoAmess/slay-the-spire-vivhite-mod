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
    private readonly int _baseLifeCalculationCost;

    protected ChromaticCard(
        int energyCost,
        CardType type,
        CardRarity rarity,
        TargetType targetType,
        int lifeCalculationCost)
        : base(energyCost, type, rarity, targetType)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(lifeCalculationCost);
        _baseLifeCalculationCost = lifeCalculationCost;
    }

    protected sealed override int LifeCalculationCost => IntVar("LifeCost");

    protected virtual IEnumerable<DynamicVar> ChromaticVars => [];

    protected sealed override IEnumerable<DynamicVar> CanonicalVars =>
        [new HpLossVar("LifeCost", _baseLifeCalculationCost), .. ChromaticVars];

    protected virtual IEnumerable<CardKeyword> ChromaticKeywords => [];

    protected sealed override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        ChromaticKeywords;

    protected bool CurrentHpIncreasedThisTurn =>
        ChromaticTurnHealing.HasIncreased(Owner.Creature);

    public override Task AfterCurrentHpChanged(Creature creature, decimal delta)
    {
        if (ReferenceEquals(creature, Owner.Creature))
        {
            ChromaticTurnHealing.ObserveCurrentHp(creature);
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
            var playerCombatState = Owner.PlayerCombatState;
            if (playerCombatState is not null)
            {
                ChromaticTurnHealing.BeginTurn(
                    combatState,
                    Owner.Creature,
                    playerCombatState.TurnNumber);
            }
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
/// Tracks the owner's real HP movement for Complementary Afterimage. CreatureCmd.Heal sends its
/// requested amount to AfterCurrentHpChanged even when no HP was restored, so the hook delta is
/// deliberately ignored. CombatState is the outer weak key, preventing a player's persistent
/// Creature from carrying this turn's fact into the next combat.
/// </summary>
public static class ChromaticTurnHealing
{
    private sealed class CreatureState
    {
        public bool IsInitialized;
        public int PreviousHp;
        public bool Increased;
        public int? TurnNumber;
    }

    private sealed class CombatHealingState
    {
        public ConditionalWeakTable<Creature, CreatureState> Creatures { get; } = new();
    }

    private static readonly ConditionalWeakTable<ICombatState, CombatHealingState> CombatStates =
        new();

    public static bool HasIncreased(Creature creature)
    {
        ArgumentNullException.ThrowIfNull(creature);
        var combatState = creature.CombatState;
        if (combatState is null)
        {
            return false;
        }

        var state = GetState(combatState, creature);
        ObserveCurrentHp(state, creature.CurrentHp);
        return state.Increased;
    }

    public static void ObserveCurrentHp(Creature creature)
    {
        ArgumentNullException.ThrowIfNull(creature);
        var combatState = creature.CombatState;
        if (combatState is null)
        {
            return;
        }

        ObserveCurrentHp(GetState(combatState, creature), creature.CurrentHp);
    }

    public static void BeginTurn(
        ICombatState combatState,
        Creature creature,
        int turnNumber)
    {
        ArgumentNullException.ThrowIfNull(combatState);
        ArgumentNullException.ThrowIfNull(creature);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(turnNumber);

        var state = GetState(combatState, creature);
        if (state.TurnNumber == turnNumber)
        {
            return;
        }

        state.IsInitialized = true;
        state.PreviousHp = creature.CurrentHp;
        state.Increased = false;
        state.TurnNumber = turnNumber;
    }

    private static CreatureState GetState(
        ICombatState combatState,
        Creature creature)
    {
        return CombatStates
            .GetOrCreateValue(combatState)
            .Creatures
            .GetOrCreateValue(creature);
    }

    private static void ObserveCurrentHp(CreatureState state, int currentHp)
    {
        if (!state.IsInitialized)
        {
            state.IsInitialized = true;
            state.PreviousHp = currentHp;
            return;
        }

        if (currentHp > state.PreviousHp)
        {
            state.Increased = true;
        }

        state.PreviousHp = currentHp;
    }
}
