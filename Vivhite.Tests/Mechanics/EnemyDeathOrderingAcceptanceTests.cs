using System.Reflection;
using MegaCrit.Sts2.Core.Commands.Builders;
using Vivhite.Core;
using Vivhite.Powers;
using Vivhite.Relics;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class EnemyDeathOrderingAcceptanceTests
{
    public static async Task WrappedAttackRecoversBeforeDeathListenersAndUnwrappedDeathIsImmediate(
        RepositorySnapshot _)
    {
        var executeAttack = typeof(InfiniteDrain).GetMethod(
            nameof(InfiniteDrain.ExecuteAttackAsync),
            BindingFlags.Static | BindingFlags.Public)
            ?? throw new AcceptanceFailureException("InfiniteDrain.ExecuteAttackAsync is missing.");
        var attackCalls = IlInspection.CalledMethods(executeAttack).ToArray();
        var enterIndex = FindCall(attackCalls, typeof(EnemyDeathTriggerScope), nameof(EnemyDeathTriggerScope.Enter));
        var executeIndex = FindCall(attackCalls, typeof(AttackCommand), "Execute");
        var recoveryIndex = FindCall(attackCalls, typeof(InfiniteDrainAggregate), nameof(InfiniteDrainAggregate.ResolveAsync));
        var flushIndex = FindCall(attackCalls, typeof(EnemyDeathTriggerScope), nameof(EnemyDeathTriggerScope.FlushAsync));
        AcceptanceAssert.True(
            enterIndex >= 0 && executeIndex > enterIndex && recoveryIndex > executeIndex && flushIndex > recoveryIndex,
            "A wrapped Attack must enter the death scope, complete native damage, finish Drain healing/conversion, " +
            "and only then flush Vivhite death listeners." +
            $" Calls: {string.Join(" -> ", attackCalls.Select(FormatCall))}");

        AssertListenerUsesScopedDeferralWithImmediateFallback(typeof(AnyEnemyDeathPower));
        AssertListenerUsesScopedDeferralWithImmediateFallback(typeof(AnyEnemyDeathRelic));

        var events = new List<string>();
        await DeliverDeathAsync(() =>
        {
            events.Add("unwrapped-death");
            return Task.CompletedTask;
        });
        AcceptanceAssert.True(
            events.SequenceEqual(["unwrapped-death"]),
            "A death outside a wrapped Attack must execute immediately.");

        using (var scope = EnemyDeathTriggerScope.Enter())
        {
            await DeliverDeathAsync(() =>
            {
                events.Add("power-death");
                return Task.CompletedTask;
            });
            await DeliverDeathAsync(() =>
            {
                events.Add("relic-death");
                return Task.CompletedTask;
            });
            AcceptanceAssert.True(
                events.SequenceEqual(["unwrapped-death"]),
                "Wrapped Vivhite power/relic death listeners must remain deferred during native Attack damage.");

            events.Add("drain-heal-and-convert");
            await scope.FlushAsync();
            AcceptanceAssert.True(
                events.SequenceEqual([
                    "unwrapped-death",
                    "drain-heal-and-convert",
                    "power-death",
                    "relic-death"
                ]),
                "Drain actual healing/conversion must settle before queued power/relic death callbacks, in FIFO order.");

            await DeliverDeathAsync(() =>
            {
                events.Add("late-death");
                return Task.CompletedTask;
            });
            AcceptanceAssert.Equal(
                "late-death",
                events[^1],
                "A closed scope must reject late work so the caller executes that death immediately.");
        }
    }

    public static async Task DeferredListenerFailuresArePreservedWithoutLossOrReplay(RepositorySnapshot _)
    {
        var firstCalls = 0;
        var secondCalls = 0;
        var expected = new InvalidOperationException("listener failure sentinel");

        using var scope = EnemyDeathTriggerScope.Enter();
        AcceptanceAssert.True(
            EnemyDeathTriggerScope.TryEnqueue(async () =>
            {
                firstCalls++;
                await Task.Yield();
                throw expected;
            }),
            "The first death listener must be accepted by an active scope.");
        AcceptanceAssert.True(
            EnemyDeathTriggerScope.TryEnqueue(() =>
            {
                secondCalls++;
                return Task.CompletedTask;
            }),
            "The second death listener must be accepted by an active scope.");

        Exception? observed = null;
        try
        {
            await scope.FlushAsync();
        }
        catch (Exception exception)
        {
            observed = exception;
        }

        AcceptanceAssert.True(
            ReferenceEquals(expected, observed),
            "A deferred listener exception must be rethrown without being replaced or lost.");
        AcceptanceAssert.Equal(1, firstCalls, "A failing deferred listener must run exactly once.");
        AcceptanceAssert.Equal(1, secondCalls, "A later deferred listener must still run exactly once after an earlier failure.");
        AcceptanceAssert.True(
            !EnemyDeathTriggerScope.TryEnqueue(() => Task.CompletedTask),
            "A flushed scope must reject new listeners instead of silently losing them.");

        var secondFlushRejected = false;
        try
        {
            await scope.FlushAsync();
        }
        catch (InvalidOperationException)
        {
            secondFlushRejected = true;
        }

        AcceptanceAssert.True(secondFlushRejected, "A scope must reject a second flush instead of replaying callbacks.");
        AcceptanceAssert.Equal(1, firstCalls, "A second flush attempt must not replay the failing listener.");
        AcceptanceAssert.Equal(1, secondCalls, "A second flush attempt must not replay later listeners.");
    }

    private static async Task DeliverDeathAsync(Func<Task> listener)
    {
        if (!EnemyDeathTriggerScope.TryEnqueue(listener))
        {
            await listener();
        }
    }

    private static void AssertListenerUsesScopedDeferralWithImmediateFallback(Type listenerType)
    {
        var afterDeath = listenerType.GetMethod(
            "AfterDeath",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
            ?? throw new AcceptanceFailureException($"{listenerType.FullName}.AfterDeath is missing.");
        var calls = IlInspection.CalledMethods(afterDeath).ToArray();
        var enqueueIndex = FindCall(calls, typeof(EnemyDeathTriggerScope), nameof(EnemyDeathTriggerScope.TryEnqueue));
        var immediateIndex = Array.FindIndex(calls, method => method.Name == "InvokeEnemyDeathAsync");
        AcceptanceAssert.True(
            enqueueIndex >= 0 && immediateIndex > enqueueIndex,
            $"{listenerType.Name}.AfterDeath must try scoped deferral and retain an immediate fallback outside/after a scope.");
    }

    private static int FindCall(IReadOnlyList<MethodBase> calls, Type declaringType, string methodName) =>
        calls.ToList().FindIndex(method => method.DeclaringType == declaringType && method.Name == methodName);

    private static string FormatCall(MethodBase method) =>
        $"{method.DeclaringType?.FullName}.{method.Name}";
}
