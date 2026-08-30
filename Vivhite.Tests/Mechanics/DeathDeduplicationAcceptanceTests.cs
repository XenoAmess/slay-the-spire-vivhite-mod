using Vivhite.Core;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class DeathDeduplicationAcceptanceTests
{
    public static void DeduplicatesOnlyTheSameEntityDeathEvent(RepositorySnapshot _)
    {
        var firstEnemy = EngineTestObjects.CreateCreature(currentHp: 0, maxHp: 20, enemy: true);
        var secondEnemy = EngineTestObjects.CreateCreature(currentHp: 0, maxHp: 20, enemy: true);
        var livingEnemy = EngineTestObjects.CreateCreature(currentHp: 5, maxHp: 20, enemy: true);
        var tracker = new EnemyDeathTracker();

        AcceptanceAssert.True(tracker.TryClaimAnyEnemy(firstEnemy), "The first delivery for a dead enemy must trigger.");
        AcceptanceAssert.True(!tracker.TryClaimAnyEnemy(firstEnemy), "A duplicate delivery for the same dead entity must be suppressed.");
        AcceptanceAssert.True(tracker.TryClaimAnyEnemy(secondEnemy), "A different dead enemy in the same turn must trigger independently.");
        AcceptanceAssert.True(!tracker.TryClaimAnyEnemy(livingEnemy), "A living enemy is not a death event.");
        AcceptanceAssert.True(
            !tracker.TryClaimAnyEnemy(EngineTestObjects.CreateCreature(0, 20, enemy: true), wasRemovalPrevented: true),
            "A prevented removal is not a completed death event.");

        EngineTestObjects.SetCurrentHp(firstEnemy, 5);
        tracker.ObserveAlive(firstEnemy);
        EngineTestObjects.SetCurrentHp(firstEnemy, 0);
        AcceptanceAssert.True(
            tracker.TryClaimAnyEnemy(firstEnemy),
            "After revival, the same entity's later genuine death is a new event and must trigger.");
    }
}
