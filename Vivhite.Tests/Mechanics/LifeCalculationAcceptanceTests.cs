using System.Reflection;
using Vivhite.Cards.Common;
using Vivhite.Core;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class LifeCalculationAcceptanceTests
{
    public static void MarginIsConsumedBeforeHpAndPaymentLeavesOneHp(RepositorySnapshot _)
    {
        var payable = LifeCalculation.Calculate(
            currentHp: 6,
            marginAvailable: 3,
            payerIsAlive: true,
            amount: 8);
        AcceptanceAssert.Equal(3, payable.MarginConsumed, "Margin must offset Life Calculation one-for-one before HP.");
        AcceptanceAssert.Equal(5, payable.HpRequired, "Only the remainder after Margin is an HP payment.");
        AcceptanceAssert.Equal(5, payable.MaximumHpPayable, "A living payer at 6 HP may spend at most 5 HP.");
        AcceptanceAssert.True(payable.CanPay, "Exactly enough HP to remain at 1 must be playable.");

        var lethal = LifeCalculation.Calculate(
            currentHp: 6,
            marginAvailable: 3,
            payerIsAlive: true,
            amount: 9);
        AcceptanceAssert.Equal(3, lethal.MarginConsumed, "The same Margin must still be consumed in the quote.");
        AcceptanceAssert.Equal(6, lethal.HpRequired, "The unaffordable remainder must not be hidden.");
        AcceptanceAssert.True(!lethal.CanPay, "A payment that would reach 0 HP must be rejected before play.");

        var thousandMargin = LifeCalculation.Calculate(
            currentHp: 1,
            marginAvailable: 1_000,
            payerIsAlive: true,
            amount: 1_000);
        AcceptanceAssert.Equal(1_000, thousandMargin.MarginConsumed, "Margin must remain linear at 1,000 with no artificial cap.");
        AcceptanceAssert.Equal(0, thousandMargin.HpRequired, "Sufficient Margin must completely offset the HP payment.");
        AcceptanceAssert.True(thousandMargin.CanPay, "A fully Margin-funded payment is valid while the payer is alive.");

        var dead = LifeCalculation.Calculate(10, 1_000, payerIsAlive: false, amount: 1);
        AcceptanceAssert.True(!dead.CanPay, "A dead payer may not play a Life Calculation card even with Margin.");
    }

    public static void CompiledCardBaseGatesPlayAndPaysBeforeEffects(RepositorySnapshot _)
    {
        const BindingFlags instanceMembers = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
        var playabilityGetter = typeof(VivhiteLifeCalculationCard)
            .GetProperty("IsPlayable", instanceMembers)?.GetMethod;
        AcceptanceAssert.True(playabilityGetter is not null, "VivhiteLifeCalculationCard must seal the card playability gate.");
        var playabilityCalls = IlInspection.CalledMethods(playabilityGetter!);
        AcceptanceAssert.True(
            playabilityCalls.Any(method =>
                method.DeclaringType == typeof(LifeCalculation) && method.Name == nameof(LifeCalculation.CanPay)),
            "Compiled LifeCalculationCard.IsPlayable must call LifeCalculation.CanPay.");

        var onPlay = typeof(VivhiteLifeCalculationCard).GetMethods(instanceMembers)
            .Single(method => method.Name == "OnPlay" && method.DeclaringType == typeof(VivhiteLifeCalculationCard));
        var onPlayCalls = IlInspection.CalledMethods(onPlay).ToArray();
        AcceptanceAssert.True(
            onPlayCalls.Any(method =>
                method.DeclaringType == typeof(VivhiteCardRules) && method.Name == nameof(VivhiteCardRules.PayThenAsync)),
            "Compiled Vivhite card base must route play through the shared PayThenAsync rule.");

        var wrapperPayThen = typeof(VivhiteCardRules).GetMethods(BindingFlags.Static | BindingFlags.Public)
            .Single(method => method.Name == nameof(VivhiteCardRules.PayThenAsync));
        var wrapperCalls = IlInspection.CalledMethods(wrapperPayThen).ToArray();
        AcceptanceAssert.True(
            wrapperCalls.Any(method =>
                method.DeclaringType == typeof(LifeCalculation) && method.Name == nameof(LifeCalculation.PayThenAsync)),
            "Card-facing PayThenAsync must delegate payment/effect ordering to the Core API.");

        var payThen = typeof(LifeCalculation).GetMethods(BindingFlags.Static | BindingFlags.Public)
            .Single(method => method.Name == nameof(LifeCalculation.PayThenAsync));
        var calls = IlInspection.CalledMethods(payThen).ToArray();
        var paymentIndex = Array.FindIndex(calls, method =>
            method.DeclaringType == typeof(LifeCalculation) && method.Name == nameof(LifeCalculation.TryPayAsync));
        var successIndex = Array.FindIndex(calls, method =>
            method.DeclaringType == typeof(LifePaymentResult) && method.Name == "get_Succeeded");
        var effectIndex = Array.FindIndex(calls, method =>
            method.Name == "Invoke" &&
            method.DeclaringType?.FullName?.StartsWith("System.Func`", StringComparison.Ordinal) == true);
        AcceptanceAssert.True(
            paymentIndex >= 0 && successIndex > paymentIndex && effectIndex > successIndex,
            "Compiled shared card flow must pay, verify success, then invoke the card effect in that order." +
            $" Indices: payment={paymentIndex}, success={successIndex}, effect={effectIndex}. Calls: " +
            string.Join(" -> ", calls.Select(method => $"{method.DeclaringType?.FullName}.{method.Name}")));

        var creaturePayment = typeof(LifeCalculation).GetMethods(BindingFlags.Static | BindingFlags.Public)
            .Single(method =>
                method.Name == nameof(LifeCalculation.TryPayAsync) &&
                method.GetParameters().Length >= 3 &&
                method.GetParameters()[1].ParameterType.Name == "Creature");
        var paymentCalls = IlInspection.CalledMethods(creaturePayment).ToArray();
        var marginIndex = Array.FindIndex(paymentCalls, method =>
            method.DeclaringType == typeof(InfiniteMargin) && method.Name == nameof(InfiniteMargin.ConsumeUpToAsync));
        var hpIndex = Array.FindIndex(paymentCalls, method =>
            method.DeclaringType?.FullName == "MegaCrit.Sts2.Core.Commands.CreatureCmd" && method.Name == "Damage");
        AcceptanceAssert.True(
            marginIndex >= 0 && hpIndex > marginIndex,
            "Compiled payment flow must consume Margin before issuing native HP damage.");
    }
}
