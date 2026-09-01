using System.Reflection;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.ValueProps;
using Vivhite.Core;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

/// <summary>
/// Regression coverage for native HP-loss modifiers.  The game reports the amount that was
/// actually lost in DamageResult; that amount is allowed to be lower than the command request.
/// </summary>
internal static class TungstenRodCompatibilityAcceptanceTests
{
    public static void ReducedHpLossStillCompletesPayment(RepositorySnapshot _)
    {
        var onePointPayer = EngineTestObjects.CreateCreature(currentHp: 20, maxHp: 20, enemy: false);
        var onePointResult = new DamageResult(onePointPayer, LifeCalculation.PaymentProps)
        {
            // Tungsten Rod applies max(0, requested - 1), so a one-point request reports zero.
            // This is also the result shape produced by Buffer's native prevention hook.
            UnblockedDamage = 0
        };
        AcceptanceAssert.True(
            LifeCalculation.WasHpPaymentApplied(onePointPayer, [onePointResult]),
            "A live payer result must complete a one-point Life Calculation payment even when Tungsten Rod (or Buffer) reduces actual HP loss to zero.");

        var multiPointPayer = EngineTestObjects.CreateCreature(currentHp: 20, maxHp: 20, enemy: false);
        const int requested = 4;
        var reducedResult = new DamageResult(multiPointPayer, LifeCalculation.PaymentProps)
        {
            // The same native hook reports three actual HP lost for a four-point request.
            UnblockedDamage = requested - 1
        };
        AcceptanceAssert.True(
            reducedResult.UnblockedDamage < requested,
            "The regression fixture must represent a native one-point HP-loss reduction.");
        AcceptanceAssert.True(
            LifeCalculation.WasHpPaymentApplied(multiPointPayer, [reducedResult]),
            "A live payer result must complete a multi-point Life Calculation payment when a native reducer lowers actual HP loss.");

        var unrelated = EngineTestObjects.CreateCreature(currentHp: 20, maxHp: 20, enemy: true);
        var unrelatedResult = new DamageResult(unrelated, LifeCalculation.PaymentProps)
        {
            UnblockedDamage = requested
        };
        AcceptanceAssert.True(
            !LifeCalculation.WasHpPaymentApplied(multiPointPayer, [unrelatedResult]),
            "A result for another creature must not satisfy the payer's HP payment.");
        AcceptanceAssert.True(
            !LifeCalculation.WasHpPaymentApplied(multiPointPayer, []),
            "An empty native result set must remain a prevented payment.");

        var deadPayer = EngineTestObjects.CreateCreature(currentHp: 0, maxHp: 20, enemy: false);
        var deadResult = new DamageResult(deadPayer, LifeCalculation.PaymentProps)
        {
            UnblockedDamage = requested
        };
        AcceptanceAssert.True(
            !LifeCalculation.WasHpPaymentApplied(deadPayer, [deadResult]),
            "A payer that died during the command must not resolve card effects.");
    }

    public static void PaymentFlowUsesReducerAwareCompletion(RepositorySnapshot _)
    {
        var creaturePayment = typeof(LifeCalculation).GetMethods(
                BindingFlags.Static | BindingFlags.Public)
            .Single(method =>
                method.Name == nameof(LifeCalculation.TryPayAsync) &&
                method.GetParameters().Length >= 3 &&
                method.GetParameters()[1].ParameterType.Name == nameof(Creature));
        var calls = IlInspection.CalledMethods(creaturePayment);
        AcceptanceAssert.True(
            calls.Any(method =>
                method.DeclaringType == typeof(LifeCalculation) &&
                method.Name == nameof(LifeCalculation.WasHpPaymentApplied)),
            "TryPayAsync must use the reducer-aware completion predicate after CreatureCmd.Damage.");
        AcceptanceAssert.True(
            LifeCalculation.PaymentProps ==
            (ValueProp.Unblockable | ValueProp.Unpowered | ValueProp.Move),
            "The Tungsten Rod fix must preserve the native self-HP-loss props and ordinary damage semantics.");
    }
}
