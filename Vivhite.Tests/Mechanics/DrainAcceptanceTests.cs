using System.Reflection;
using MegaCrit.Sts2.Core.Commands.Builders;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.ValueProps;
using Vivhite.Core;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class DrainAcceptanceTests
{
    public static void UsesActualEnemyHpLossAndAggregatesBeforeOneRounding(RepositorySnapshot _)
    {
        var attacker = EngineTestObjects.CreateCreature(currentHp: 30, maxHp: 30, enemy: false);
        var enemyOne = EngineTestObjects.CreateCreature(currentHp: 0, maxHp: 30, enemy: true);
        var enemyTwo = EngineTestObjects.CreateCreature(currentHp: 0, maxHp: 30, enemy: true);
        var enemyThree = EngineTestObjects.CreateCreature(currentHp: 0, maxHp: 30, enemy: true);
        var ally = EngineTestObjects.CreateCreature(currentHp: 30, maxHp: 30, enemy: false);

        var first = Damage(enemyOne, actualHpLoss: 3, blocked: 7, overkill: 20);
        var second = Damage(enemyOne, actualHpLoss: 2);
        var friendlyFire = Damage(ally, actualHpLoss: 100);
        var third = Damage(enemyTwo, actualHpLoss: 4, killed: true);
        var fourth = Damage(enemyThree, actualHpLoss: 1, killed: true);

        var multiHit = Command(attacker, [first, friendlyFire], [second, first]);
        var areaHit = Command(attacker, [third, fourth]);
        var aggregate = InfiniteDrain.CreateAggregate()
            .AddAttackCommand(multiHit)
            .AddAttackCommand(multiHit)
            .AddAttackCommand(areaHit);
        var snapshot = aggregate.Snapshot();

        AcceptanceAssert.Equal(2, snapshot.AttackCommandCount, "The same completed attack command must not be counted twice.");
        AcceptanceAssert.Equal(5, snapshot.DamageResultCount, "The same DamageResult delivered twice must be identity-deduplicated.");
        AcceptanceAssert.Equal(4, snapshot.TargetCount, "Diagnostics must retain all distinct targets, including friendly damage.");
        AcceptanceAssert.Equal(3, snapshot.EnemyTargetCount, "Only opposing creatures are Drain-eligible targets.");
        AcceptanceAssert.Equal(10, snapshot.ActualEnemyHpLoss, "Drain base must sum only actual enemy HP loss across hits and targets.");
        AcceptanceAssert.Equal(7, snapshot.EnemyBlockedDamage, "Blocked damage is diagnostic only and must not enter the Drain base.");
        AcceptanceAssert.Equal(20, snapshot.EnemyOverkillDamage, "Overkill is diagnostic only and must not enter the Drain base.");
        AcceptanceAssert.Equal(2, snapshot.EnemyKills, "Different killed enemies must remain distinct in an area attack.");

        var fifteenPercent = new DrainRate(CardPercent: 15m, GlobalPercent: 0m, ThisTurnPercent: 0m);
        AcceptanceAssert.Equal(
            2,
            fifteenPercent.CalculateHealing(snapshot.ActualEnemyHpLoss),
            "10 aggregate damage at 15% must ceiling once to 2 after all hits and targets are aggregated.");
        AcceptanceAssert.Equal(
            1,
            new DrainRate(CardPercent: 1m, GlobalPercent: 0m, ThisTurnPercent: 0m)
                .CalculateHealing(actualEnemyHpLoss: 1),
            "Any positive fractional Drain result must round upward to one.");
        AcceptanceAssert.Equal(
            0,
            fifteenPercent.CalculateHealing(actualEnemyHpLoss: 0),
            "Zero actual enemy HP loss must remain zero after ceiling rounding.");

        var publicDamageResultInputs = typeof(InfiniteDrainAggregate)
            .GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly)
            .Where(method => method.GetParameters().Any(parameter => ContainsDamageResult(parameter.ParameterType)))
            .Select(method => method.ToString() ?? method.Name)
            .ToArray();
        AcceptanceAssert.Empty(
            publicDamageResultInputs,
            "Drain aggregation must only accept completed AttackCommand objects; arbitrary/non-attack DamageResult injection is forbidden:");
    }

    public static void SupportsRatesAndHealingFarAboveOneHundredPercent(RepositorySnapshot _)
    {
        var oneHundredTwentyFive = new DrainRate(CardPercent: 80m, GlobalPercent: 45m, ThisTurnPercent: 0m);
        AcceptanceAssert.Equal(125m, oneHundredTwentyFive.TotalPercent, "Card and global Drain percentages add as percentage points.");
        AcceptanceAssert.Equal(
            100,
            oneHundredTwentyFive.CalculateHealing(actualEnemyHpLoss: 80),
            "125% Drain on 80 actual HP loss must heal 100; it must not clamp to 80.");

        var thousandScale = new DrainRate(CardPercent: 800m, GlobalPercent: 250m, ThisTurnPercent: 200m);
        AcceptanceAssert.Equal(1_250m, thousandScale.TotalPercent, "Drain totals above 1,000% must remain additive.");
        AcceptanceAssert.Equal(
            12_500,
            thousandScale.CalculateHealing(actualEnemyHpLoss: 1_000),
            "A 1,000-point actual-damage input at 1,250% must scale linearly to 12,500 healing.");
    }

    private static DamageResult Damage(
        Creature receiver,
        int actualHpLoss,
        int blocked = 0,
        int overkill = 0,
        bool killed = false) =>
        new(receiver, ValueProp.Move)
        {
            UnblockedDamage = actualHpLoss,
            BlockedDamage = blocked,
            OverkillDamage = overkill,
            WasTargetKilled = killed
        };

    private static AttackCommand Command(Creature attacker, params DamageResult[][] hits)
    {
        var command = new AttackCommand(1m);
        EngineTestObjects.SetAutoProperty(command, "Attacker", attacker);
        var addResults = typeof(AttackCommand).GetMethod(
            "AddResultsInternal",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("AttackCommand.AddResultsInternal is unavailable in game v0.111.0.");
        foreach (var hit in hits)
        {
            addResults.Invoke(command, [hit]);
        }
        return command;
    }

    private static bool ContainsDamageResult(Type type)
    {
        if (type == typeof(DamageResult))
        {
            return true;
        }
        return type.IsGenericType && type.GetGenericArguments().Any(ContainsDamageResult);
    }
}
