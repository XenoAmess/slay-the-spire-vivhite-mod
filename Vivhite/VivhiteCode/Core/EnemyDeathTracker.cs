using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Combat;

namespace Vivhite.Core;

public readonly record struct EnemyDeathEvent(
    Creature ListenerOwner,
    Creature Enemy,
    float DeathAnimationLength);

/// <summary>
/// Per-listener death ledger. One tracker must be owned by each card, relic, or power that needs
/// a once-per-death trigger; sharing one tracker between listeners would incorrectly suppress them.
/// </summary>
public sealed class EnemyDeathTracker
{
    private readonly HashSet<Creature> _claimed = new(ReferenceEqualityComparer.Instance);

    public static bool IsAnyEnemyDeath(Creature creature, bool wasRemovalPrevented = false)
    {
        ArgumentNullException.ThrowIfNull(creature);
        return !wasRemovalPrevented && creature.IsEnemy && creature.IsDead;
    }

    public static bool IsEnemyDeath(
        Creature observer,
        Creature creature,
        bool wasRemovalPrevented = false)
    {
        ArgumentNullException.ThrowIfNull(observer);
        ArgumentNullException.ThrowIfNull(creature);

        if (wasRemovalPrevented || creature.IsAlive || ReferenceEquals(observer, creature))
        {
            return false;
        }

        // Use combat sides rather than the current enemy list: summons can already have been
        // detached when AfterDeath runs. The source of the kill is intentionally irrelevant, so
        // teammate and environmental kills are observed as well.
        return observer.Side != CombatSide.None &&
               creature.Side != CombatSide.None &&
               observer.Side != creature.Side;
    }

    public bool TryClaimAnyEnemy(Creature creature, bool wasRemovalPrevented = false)
    {
        return IsAnyEnemyDeath(creature, wasRemovalPrevented) && _claimed.Add(creature);
    }

    public bool TryClaim(
        Creature observer,
        Creature creature,
        bool wasRemovalPrevented = false)
    {
        return IsEnemyDeath(observer, creature, wasRemovalPrevented) && _claimed.Add(creature);
    }

    public bool TryCreate(
        Creature observer,
        Creature creature,
        bool wasRemovalPrevented,
        float deathAnimationLength,
        out EnemyDeathEvent deathEvent)
    {
        if (TryClaim(observer, creature, wasRemovalPrevented))
        {
            deathEvent = new EnemyDeathEvent(observer, creature, deathAnimationLength);
            return true;
        }

        deathEvent = default;
        return false;
    }

    /// <summary>
    /// Re-arms a creature after revival so a later, genuine second death may trigger again.
    /// Safe to call from every AfterCurrentHpChanged hook.
    /// </summary>
    public void ObserveAlive(Creature creature)
    {
        ArgumentNullException.ThrowIfNull(creature);
        if (creature.IsAlive)
        {
            _claimed.Remove(creature);
        }
    }

    public void Clear()
    {
        _claimed.Clear();
    }
}
