using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Powers;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.ValueProps;
using STS2RitsuLib.Interop.AutoRegistration;
using STS2RitsuLib.Scaffolding.Content;
using Vivhite.Cards.Common;
using Vivhite.Core;
using Vivhite.Powers;

namespace Vivhite.Cards.Conservation;

/// <summary>
/// Each point of Margin actually consumed by a Life Calculation card grants Amount block.
/// Negative Margin changes from unrelated effects are deliberately excluded.
/// </summary>
[RegisterPower]
public sealed class LawOfConservationPower : VivhitePowerTemplate
{
    public override PowerType Type => PowerType.Buff;
    public override PowerStackType StackType => PowerStackType.Counter;

    public override async Task AfterPowerAmountChanged(
        PlayerChoiceContext choiceContext,
        PowerModel power,
        decimal delta,
        Creature? applier,
        CardModel? cardSource)
    {
        if (delta >= 0 ||
            power is not InfiniteMarginPower ||
            !ReferenceEquals(power.Owner, Owner) ||
            cardSource is not VivhiteLifeCalculationCard)
        {
            return;
        }

        var preventedLifeLoss = decimal.Negate(delta);
        if (preventedLifeLoss <= 0 || Amount <= 0)
        {
            return;
        }

        Flash();
        await CreatureCmd.GainBlock(
            Owner,
            preventedLifeLoss * Amount,
            ValueProp.Move,
            null!);
    }
}

[RegisterPower]
public sealed class LifeManifoldPower : VivhitePowerTemplate
{
    public override PowerType Type => PowerType.Buff;
    public override PowerStackType StackType => PowerStackType.Counter;

    public override async Task AfterPlayerTurnStart(
        PlayerChoiceContext choiceContext,
        Player player)
    {
        if (!ReferenceEquals(player.Creature, Owner) || Amount <= 0)
        {
            return;
        }

        Flash();
        await InfiniteMargin.GainAsync(
            choiceContext,
            Owner,
            Amount,
            Owner);
    }
}

internal sealed class ClosedManifoldHpLedger
{
    public bool IsInitialized { get; set; }
    public int PreviousHp { get; set; }

    public void Capture(Creature owner)
    {
        PreviousHp = owner.CurrentHp;
        IsInitialized = true;
    }
}

/// <summary>
/// CreatureCmd.Heal reports its requested amount to AfterCurrentHpChanged. Comparing that value
/// with the owner's real HP movement captures native overheal from every source. GainMaxHp is not
/// misclassified: its requested heal and simultaneous current-HP gain are equal.
/// </summary>
[RegisterPower]
public sealed class ClosedManifoldPower : VivhitePowerTemplate
{
    public override PowerType Type => PowerType.Buff;
    public override PowerStackType StackType => PowerStackType.Single;

    protected override object InitInternalData()
    {
        return new ClosedManifoldHpLedger();
    }

    public override Task AfterApplied(Creature? applier, CardModel? cardSource)
    {
        GetInternalData<ClosedManifoldHpLedger>().Capture(Owner);
        return Task.CompletedTask;
    }

    public override async Task AfterCurrentHpChanged(Creature creature, decimal delta)
    {
        if (!ReferenceEquals(creature, Owner))
        {
            return;
        }

        var ledger = GetInternalData<ClosedManifoldHpLedger>();
        if (!ledger.IsInitialized)
        {
            ledger.Capture(Owner);
            return;
        }

        var previousHp = ledger.PreviousHp;
        var currentHp = Owner.CurrentHp;
        ledger.PreviousHp = currentHp;

        if (delta <= 0)
        {
            return;
        }

        var actualHealing = Math.Max(0, currentHp - previousHp);
        var excess = delta - actualHealing;
        if (excess < 1)
        {
            return;
        }

        var margin = decimal.ToInt32(decimal.Floor(excess));
        if (margin <= 0)
        {
            return;
        }

        Flash();
        await InfiniteMargin.GainAsync(
            new BlockingPlayerChoiceContext(),
            Owner,
            margin,
            Owner);
    }
}
