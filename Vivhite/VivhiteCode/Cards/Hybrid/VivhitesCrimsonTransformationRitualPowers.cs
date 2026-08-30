using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Powers;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.ValueProps;
using STS2RitsuLib.Interop.AutoRegistration;
using Vivhite.Cards.Common;
using Vivhite.Core;
using Vivhite.Powers;

namespace Vivhite.Cards.Hybrid;

public readonly record struct CrimsonRitualStage(
    int Phase,
    int DamagePercentPerPhase);

public readonly record struct CrimsonRitualTotals(
    int ExtraLifeCost,
    decimal DamagePercent)
{
    public decimal DamageMultiplier => 1m + (DamagePercent / 100m);
}

/// <summary>
/// Pure arithmetic and live aggregation for every independently advancing ritual instance.
/// Percentages add before the one native damage multiplier is returned, so multiple copies do
/// not compound with one another. No gameplay cap is applied to phase, life cost, or percentage.
/// </summary>
public static class VivhitesCrimsonTransformationRitualMechanics
{
    public static CrimsonRitualTotals Calculate(
        IEnumerable<CrimsonRitualStage> stages)
    {
        ArgumentNullException.ThrowIfNull(stages);

        var extraLifeCost = 0;
        var damagePercent = 0m;
        foreach (var stage in stages)
        {
            ArgumentOutOfRangeException.ThrowIfNegative(stage.Phase);
            ArgumentOutOfRangeException.ThrowIfNegative(stage.DamagePercentPerPhase);

            extraLifeCost = checked(extraLifeCost + stage.Phase);
            damagePercent += (decimal)stage.Phase * stage.DamagePercentPerPhase;
        }

        return new CrimsonRitualTotals(extraLifeCost, damagePercent);
    }

    public static CrimsonRitualTotals GetTotals(Creature owner)
    {
        ArgumentNullException.ThrowIfNull(owner);
        return Calculate(owner.Powers
            .OfType<VivhitesCrimsonTransformationRitualPowerBase>()
            .Select(power => new CrimsonRitualStage(
                power.Phase,
                power.DamagePercentPerPhase)));
    }

    public static int AdvancePhase(
        int phase,
        int lastTurnNumber,
        int currentTurnNumber)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(phase);
        ArgumentOutOfRangeException.ThrowIfNegative(lastTurnNumber);
        ArgumentOutOfRangeException.ThrowIfNegative(currentTurnNumber);

        return currentTurnNumber <= lastTurnNumber
            ? phase
            : checked(phase + currentTurnNumber - lastTurnNumber);
    }

    public static int GetPrintedLifeCost(CardModel card)
    {
        ArgumentNullException.ThrowIfNull(card);
        return card.DynamicVars.TryGetValue("LifeCost", out var lifeCost)
            ? Math.Max(0, lifeCost.IntValue)
            : 0;
    }

    public static int GetCombinedLifeCost(
        CardModel card,
        int ritualExtraLifeCost)
    {
        ArgumentNullException.ThrowIfNull(card);
        ArgumentOutOfRangeException.ThrowIfNegative(ritualExtraLifeCost);
        return checked(GetPrintedLifeCost(card) + ritualExtraLifeCost);
    }
}

/// <summary>
/// One mutable power object represents one played copy of the card. InstanceType.Instanced keeps
/// phases independent even when several normal or upgraded copies are played on different turns.
/// Only the first live ritual instance performs aggregate hooks; every instance still advances
/// its own phase, and the leader sums all phases and upgrade rates at the moment of use.
/// </summary>
public abstract class VivhitesCrimsonTransformationRitualPowerBase : VivhitePowerTemplate
{
    private const string PhaseKey = "Phase";
    private const string DamagePercentPerPhaseKey = "DamagePercentPerPhase";
    private const string LastTurnNumberKey = "LastTurnNumber";

    protected abstract int CanonicalDamagePercentPerPhase { get; }

    public int Phase => DynamicVars[PhaseKey].IntValue;

    public int DamagePercentPerPhase =>
        DynamicVars[DamagePercentPerPhaseKey].IntValue;

    public override PowerType Type => PowerType.Buff;

    public override PowerStackType StackType => PowerStackType.Counter;

    public override PowerInstanceType InstanceType => PowerInstanceType.Instanced;

    public override int DisplayAmount => Phase;

    protected override IEnumerable<DynamicVar> CanonicalVars =>
    [
        new DynamicVar(PhaseKey, 0),
        new DynamicVar(DamagePercentPerPhaseKey, CanonicalDamagePercentPerPhase),
        new DynamicVar(LastTurnNumberKey, 0)
    ];

    public override Task AfterApplied(Creature? applier, CardModel? cardSource)
    {
        DynamicVars[LastTurnNumberKey].BaseValue = CurrentTurnNumber();
        return Task.CompletedTask;
    }

    public override Task AfterPlayerTurnStart(
        PlayerChoiceContext choiceContext,
        Player player)
    {
        if (!ReferenceEquals(player.Creature, Owner))
        {
            return Task.CompletedTask;
        }

        var playerCombatState = player.PlayerCombatState;
        if (playerCombatState is null)
        {
            return Task.CompletedTask;
        }

        var currentTurn = playerCombatState.TurnNumber;
        var lastTurn = DynamicVars[LastTurnNumberKey].IntValue;
        if (currentTurn <= lastTurn)
        {
            return Task.CompletedTask;
        }

        DynamicVars[PhaseKey].BaseValue =
            VivhitesCrimsonTransformationRitualMechanics.AdvancePhase(
                Phase,
                lastTurn,
                currentTurn);
        DynamicVars[LastTurnNumberKey].BaseValue = currentTurn;
        InvokeDisplayAmountChanged();
        Flash();
        return Task.CompletedTask;
    }

    public override bool ShouldPlay(CardModel card, AutoPlayType autoPlayType)
    {
        if (!IsAggregateLeader() || !IsOwnerAttack(card))
        {
            return true;
        }

        var totals = VivhitesCrimsonTransformationRitualMechanics.GetTotals(Owner);
        var combinedLifeCost =
            VivhitesCrimsonTransformationRitualMechanics.GetCombinedLifeCost(
                card,
                totals.ExtraLifeCost);
        return LifeCalculation.CanPay(card.Owner.Creature, combinedLifeCost);
    }

    public override async Task BeforeCardPlayed(CardPlay cardPlay)
    {
        if (!IsAggregateLeader() || !IsOwnerAttack(cardPlay.Card))
        {
            return;
        }

        var extraLifeCost =
            VivhitesCrimsonTransformationRitualMechanics.GetTotals(Owner).ExtraLifeCost;
        if (extraLifeCost == 0)
        {
            return;
        }

        Flash();
        await VivhiteCardRules.PayThenAsync(
            new ThrowingPlayerChoiceContext(),
            cardPlay.Card,
            cardPlay,
            extraLifeCost,
            _ => Task.CompletedTask);
    }

    public override decimal ModifyDamageMultiplicative(
        Creature? target,
        decimal amount,
        ValueProp props,
        Creature? dealer,
        CardModel? cardSource,
        CardPlay? cardPlay)
    {
        if (!IsAggregateLeader() ||
            !props.IsPoweredAttack() ||
            target is null ||
            !target.IsEnemy ||
            cardSource is null ||
            cardSource.Type != CardType.Attack ||
            !ReferenceEquals(cardSource.Owner.Creature, Owner) ||
            !ReferenceEquals(dealer, Owner))
        {
            return 1m;
        }

        return VivhitesCrimsonTransformationRitualMechanics
            .GetTotals(Owner)
            .DamageMultiplier;
    }

    public override Task AfterModifyingDamageAmount(CardModel? cardSource)
    {
        if (cardSource is not null && IsOwnerAttack(cardSource))
        {
            Flash();
        }

        return Task.CompletedTask;
    }

    private int CurrentTurnNumber()
    {
        return Owner.Player?.PlayerCombatState?.TurnNumber ?? 0;
    }

    private bool IsAggregateLeader()
    {
        return ReferenceEquals(
            this,
            Owner.Powers
                .OfType<VivhitesCrimsonTransformationRitualPowerBase>()
                .FirstOrDefault());
    }

    private bool IsOwnerAttack(CardModel card)
    {
        return card.Type == CardType.Attack &&
               ReferenceEquals(card.Owner.Creature, Owner);
    }
}

[RegisterPower]
public sealed class VivhitesCrimsonTransformationRitualPower
    : VivhitesCrimsonTransformationRitualPowerBase
{
    protected override int CanonicalDamagePercentPerPhase => 10;
}

[RegisterPower]
public sealed class VivhitesCrimsonTransformationRitualUpgradedPower
    : VivhitesCrimsonTransformationRitualPowerBase
{
    protected override int CanonicalDamagePercentPerPhase => 15;
}
