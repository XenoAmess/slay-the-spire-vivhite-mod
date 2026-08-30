using System.Runtime.CompilerServices;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using STS2RitsuLib.Scaffolding.Content;
using Vivhite.Core;

namespace Vivhite.Relics;

/// <summary>
/// Per-relic enemy-death listener. ConditionalWeakTable guarantees that cloned relic instances
/// never share a death ledger, so every listener triggers once for the same enemy entity.
/// </summary>
public abstract class AnyEnemyDeathRelic : ModRelicTemplate
{
    private static readonly ConditionalWeakTable<AnyEnemyDeathRelic, EnemyDeathTracker> Trackers = new();

    public sealed override Task AfterDeath(
        PlayerChoiceContext choiceContext,
        Creature creature,
        bool wasRemovalPrevented,
        float deathAnimLength)
    {
        var tracker = Trackers.GetOrCreateValue(this);
        if (!tracker.TryCreate(
                Owner.Creature,
                creature,
                wasRemovalPrevented,
                deathAnimLength,
                out var deathEvent))
        {
            return Task.CompletedTask;
        }

        Flash();
        return OnAnyEnemyDeath(choiceContext, deathEvent);
    }

    public sealed override Task AfterCurrentHpChanged(Creature creature, decimal delta)
    {
        Trackers.GetOrCreateValue(this).ObserveAlive(creature);
        return Task.CompletedTask;
    }

    protected abstract Task OnAnyEnemyDeath(
        PlayerChoiceContext choiceContext,
        EnemyDeathEvent deathEvent);
}
