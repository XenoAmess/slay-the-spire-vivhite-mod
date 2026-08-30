using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Powers;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using STS2RitsuLib.Interop.AutoRegistration;
using STS2RitsuLib.Scaffolding.Content;
using Vivhite.Core;
using Vivhite.Powers;

namespace Vivhite.Cards.Chromatic;

public abstract class ChromaticCounterPower : VivhitePowerTemplate
{
    public override PowerType Type => PowerType.Buff;
    public override PowerStackType StackType => PowerStackType.Counter;
}

/// <summary>
/// Tracks the exact share of this-turn Drain injected by Chiaroscuro. The share is removed only
/// after the next Attack finishes, so every Common drain wrapper sees it during damage recovery.
/// </summary>
[RegisterPower]
public sealed class ChiaroscuroPower : ChromaticCounterPower
{
    public override async Task AfterCardPlayed(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay)
    {
        if (cardPlay.Card.Type != CardType.Attack ||
            !ReferenceEquals(cardPlay.Card.Owner.Creature, Owner))
        {
            return;
        }

        var injected = Math.Max(0, Amount);
        var turnDrain = Owner.GetPower<InfiniteDrainThisTurnPower>();
        if (injected > 0 && turnDrain is not null)
        {
            await PowerCmd.ModifyAmount(
                choiceContext,
                turnDrain,
                -Math.Min(injected, Math.Max(0, turnDrain.Amount)),
                Owner,
                cardPlay.Card);
        }

        await PowerCmd.Remove(this);
    }

    public override Task AfterSideTurnEnd(
        PlayerChoiceContext choiceContext,
        CombatSide side,
        IEnumerable<Creature> participants)
    {
        return participants.Any(creature => ReferenceEquals(creature, Owner))
            ? PowerCmd.Remove(this)
            : Task.CompletedTask;
    }
}

/// <summary>Each stack converts actual Drain healing to an equal amount of Block.</summary>
[RegisterPower]
public sealed class ColorConservationPower : ChromaticCounterPower;

/// <summary>Each stack grants one Strength per five HP healed by one Drain resolution.</summary>
[RegisterPower]
public sealed class CrimsonConservationLawPower : ChromaticCounterPower;

/// <summary>Upgraded copies remain separate so mixed 5/4 thresholds resolve exactly.</summary>
[RegisterPower]
public sealed class CrimsonConservationLawUpgradedPower : ChromaticCounterPower;

/// <summary>Each stack grows global Drain by two points after a healing Attack.</summary>
[RegisterPower]
public sealed class InfiniteCanvasPower : ChromaticCounterPower;

/// <summary>Upgraded copies remain separate and grow global Drain by three points.</summary>
[RegisterPower]
public sealed class InfiniteCanvasUpgradedPower : ChromaticCounterPower;

public static class ChromaticPowerMechanics
{
    public static async Task GainNextAttackDrainAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int percentagePoints,
        CardModel cardSource)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(percentagePoints);
        if (percentagePoints == 0)
        {
            return;
        }

        await InfiniteDrain.GainThisTurnPercentAsync(
            choiceContext,
            owner,
            percentagePoints,
            owner,
            cardSource);
        await PowerCmd.Apply<ChiaroscuroPower>(
            choiceContext,
            owner,
            percentagePoints,
            owner,
            cardSource);
    }
}
