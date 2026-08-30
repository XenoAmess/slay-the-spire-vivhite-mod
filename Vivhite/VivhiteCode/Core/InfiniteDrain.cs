using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Commands.Builders;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using System.Runtime.ExceptionServices;
using Vivhite.Powers;

namespace Vivhite.Core;

public readonly record struct DrainRate(
    decimal CardPercent,
    decimal GlobalPercent,
    decimal ThisTurnPercent)
{
    public decimal TotalPercent => CardPercent + GlobalPercent + ThisTurnPercent;

    public int CalculateHealing(int actualEnemyHpLoss)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(actualEnemyHpLoss);
        if (CardPercent < 0 || GlobalPercent < 0 || ThisTurnPercent < 0)
        {
            throw new InvalidOperationException("Drain percentages cannot be negative.");
        }

        // Aggregate the complete Attack first, then round the single card-level result upward.
        // Deliberately no 100% rate cap or healing cap.
        return decimal.ToInt32(decimal.Ceiling(actualEnemyHpLoss * TotalPercent / 100m));
    }

    public static DrainRate FromPowers(Creature owner, decimal cardPercent)
    {
        ArgumentNullException.ThrowIfNull(owner);
        return new DrainRate(
            cardPercent,
            InfiniteDrain.GetGlobalPercent(owner),
            InfiniteDrain.GetThisTurnPercent(owner));
    }
}

public readonly record struct InfiniteDrainSnapshot(
    int AttackCommandCount,
    int DamageResultCount,
    int TargetCount,
    int EnemyTargetCount,
    int ActualEnemyHpLoss,
    int EnemyBlockedDamage,
    int EnemyOverkillDamage,
    int EnemyKills);

public sealed record InfiniteDrainResult(
    InfiniteDrainSnapshot Damage,
    DrainRate Rate,
    int RecoveryRequested,
    DrainRecoveryOutcome Recovery)
{
    public int ActualHealing => Recovery.Healed;
    public int UnconvertedOverheal => Recovery.UnconvertedExcess;
}

/// <summary>
/// Aggregates complete native AttackCommands. It has no API for arbitrary DamageResults, making
/// non-attack damage ineligible by construction. Blocked damage and overkill are recorded for
/// diagnostics but never contribute to ActualEnemyHpLoss.
/// </summary>
public sealed class InfiniteDrainAggregate
{
    private readonly HashSet<AttackCommand> _commands = new(ReferenceEqualityComparer.Instance);
    private readonly HashSet<DamageResult> _results = new(ReferenceEqualityComparer.Instance);
    private readonly HashSet<Creature> _targets = new(ReferenceEqualityComparer.Instance);
    private readonly HashSet<Creature> _enemyTargets = new(ReferenceEqualityComparer.Instance);
    private readonly HashSet<Creature> _enemyKills = new(ReferenceEqualityComparer.Instance);

    private int _actualEnemyHpLoss;
    private int _enemyBlockedDamage;
    private int _enemyOverkillDamage;
    private bool _resolved;

    public bool IsResolved => _resolved;

    public InfiniteDrainAggregate AddAttackCommand(AttackCommand completedCommand)
    {
        ArgumentNullException.ThrowIfNull(completedCommand);
        ObjectDisposedException.ThrowIf(_resolved, this);
        if (!_commands.Add(completedCommand))
        {
            return this;
        }

        var attacker = completedCommand.Attacker;
        foreach (var result in completedCommand.Results.SelectMany(hit => hit))
        {
            if (!_results.Add(result))
            {
                continue;
            }

            var receiver = result.Receiver;
            _targets.Add(receiver);
            if (!AreOpponents(attacker, receiver))
            {
                continue;
            }

            _enemyTargets.Add(receiver);
            _actualEnemyHpLoss += result.UnblockedDamage;
            _enemyBlockedDamage += result.BlockedDamage;
            _enemyOverkillDamage += result.OverkillDamage;
            if (result.WasTargetKilled)
            {
                _enemyKills.Add(receiver);
            }
        }

        return this;
    }

    public InfiniteDrainAggregate AddAttackCommands(IEnumerable<AttackCommand> completedCommands)
    {
        ArgumentNullException.ThrowIfNull(completedCommands);
        foreach (var command in completedCommands)
        {
            AddAttackCommand(command);
        }

        return this;
    }

    public InfiniteDrainSnapshot Snapshot()
    {
        return new InfiniteDrainSnapshot(
            _commands.Count,
            _results.Count,
            _targets.Count,
            _enemyTargets.Count,
            _actualEnemyHpLoss,
            _enemyBlockedDamage,
            _enemyOverkillDamage,
            _enemyKills.Count);
    }

    public async Task<InfiniteDrainResult> ResolveAsync(
        PlayerChoiceContext choiceContext,
        Creature recipient,
        DrainRate rate,
        DrainRecoveryHandler? recoveryHandler = null,
        Creature? applier = null,
        CardModel? cardSource = null,
        CardPlay? cardPlay = null)
    {
        ArgumentNullException.ThrowIfNull(choiceContext);
        ArgumentNullException.ThrowIfNull(recipient);
        ObjectDisposedException.ThrowIf(_resolved, this);
        _resolved = true;

        var snapshot = Snapshot();
        var requested = rate.CalculateHealing(snapshot.ActualEnemyHpLoss);
        var handler = recoveryHandler ?? DrainRecovery.HealAsync;
        var recovery = await handler(new DrainRecoveryContext(
            choiceContext,
            recipient,
            requested,
            applier ?? recipient,
            cardSource,
            cardPlay));

        return new InfiniteDrainResult(snapshot, rate, requested, recovery);
    }

    private static bool AreOpponents(Creature? attacker, Creature receiver)
    {
        return attacker is not null &&
               attacker.Side != CombatSide.None &&
               receiver.Side != CombatSide.None &&
               attacker.Side != receiver.Side;
    }
}

public static class InfiniteDrain
{
    public static InfiniteDrainAggregate CreateAggregate() => new();

    public static int GetGlobalPercent(Creature owner) =>
        PowerStackResource<InfiniteDrainPower>.GetAmount(owner);

    public static int GetThisTurnPercent(Creature owner) =>
        PowerStackResource<InfiniteDrainThisTurnPower>.GetAmount(owner);

    public static Task<InfiniteDrainPower?> GainGlobalPercentAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false) =>
        PowerStackResource<InfiniteDrainPower>.GainAsync(
            choiceContext,
            owner,
            amount,
            applier,
            cardSource,
            silent);

    public static Task<InfiniteDrainThisTurnPower?> GainThisTurnPercentAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false) =>
        PowerStackResource<InfiniteDrainThisTurnPower>.GainAsync(
            choiceContext,
            owner,
            amount,
            applier,
            cardSource,
            silent);

    public static async Task<InfiniteDrainResult> ExecuteAttackAsync(
        PlayerChoiceContext choiceContext,
        AttackCommand attackCommand,
        Creature recipient,
        decimal cardPercent,
        DrainRecoveryHandler? recoveryHandler = null,
        CardModel? cardSource = null,
        CardPlay? cardPlay = null)
    {
        ArgumentNullException.ThrowIfNull(attackCommand);

        using var deathScope = EnemyDeathTriggerScope.Enter();
        InfiniteDrainResult? result = null;
        ExceptionDispatchInfo? attackOrDrainFailure = null;
        try
        {
            var completed = await attackCommand.Execute(choiceContext);
            result = await CreateAggregate()
                .AddAttackCommand(completed)
                .ResolveAsync(
                    choiceContext,
                    recipient,
                    DrainRate.FromPowers(recipient, cardPercent),
                    recoveryHandler,
                    completed.Attacker ?? recipient,
                    cardSource,
                    cardPlay);
        }
        catch (Exception exception)
        {
            attackOrDrainFailure = ExceptionDispatchInfo.Capture(exception);
        }

        ExceptionDispatchInfo? deferredDeathFailure = null;
        try
        {
            // Native damage has already completed (including Kill/AfterDeath), but Vivhite's own
            // listener effects remain queued. Drain and all recovery-handler conversions therefore
            // settle before the queue is flushed and before the card resumes its Fatal branch.
            await deathScope.FlushAsync();
        }
        catch (Exception exception)
        {
            deferredDeathFailure = ExceptionDispatchInfo.Capture(exception);
        }

        if (attackOrDrainFailure is not null)
        {
            if (deferredDeathFailure is not null)
            {
                throw new AggregateException(
                    "The attack or Drain resolution and a deferred enemy-death listener both failed.",
                    attackOrDrainFailure.SourceException,
                    deferredDeathFailure.SourceException);
            }

            attackOrDrainFailure.Throw();
        }

        if (deferredDeathFailure is not null)
        {
            deferredDeathFailure.Throw();
        }

        return result ?? throw new InvalidOperationException(
            "A wrapped attack completed without producing a Drain result.");
    }
}
