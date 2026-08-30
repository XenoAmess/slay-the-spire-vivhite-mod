using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using Vivhite.Core;

namespace Vivhite.Powers;

/// <summary>
/// Base for powers that trigger once whenever any opponent dies. The native AfterDeath hook is
/// authoritative; the tracker only suppresses duplicate delivery and is re-armed on revival.
/// </summary>
public abstract class AnyEnemyDeathPower : VivhiteCounterPower
{
    protected override object InitInternalData()
    {
        return new EnemyDeathTracker();
    }

    public sealed override Task AfterDeath(
        PlayerChoiceContext choiceContext,
        Creature creature,
        bool wasRemovalPrevented,
        float deathAnimLength)
    {
        var tracker = GetInternalData<EnemyDeathTracker>();
        if (!tracker.TryCreate(
                Owner,
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
        GetInternalData<EnemyDeathTracker>().ObserveAlive(creature);
        return Task.CompletedTask;
    }

    protected abstract Task OnAnyEnemyDeath(
        PlayerChoiceContext choiceContext,
        EnemyDeathEvent deathEvent);
}
