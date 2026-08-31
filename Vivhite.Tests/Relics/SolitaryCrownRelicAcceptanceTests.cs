using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Vivhite.Core;
using Vivhite.Relics;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Relics;

internal static class SolitaryCrownRelicAcceptanceTests
{
    public static void UsesTwentyPercentMaxHpCeilingWithoutTriggerCaps(RepositorySnapshot repository)
    {
        AcceptanceAssert.Equal(
            1,
            repository.RegisteredRelics.Count,
            "Solitary Crown must remain Vivhite's only registered relic model.");
        AcceptanceAssert.Equal(
            typeof(SolitaryCrown),
            repository.RegisteredRelics.Single(),
            "SolitaryCrown must be the registered canonical relic type.");
        AcceptanceAssert.Equal(
            "VIVHITE_RELIC_ORIGIN_STAR_CHART",
            repository.RelicId(typeof(SolitaryCrown)),
            "Solitary Crown must preserve the deployed Origin Star Chart content ID for old-run compatibility.");
        var registration = RepositorySnapshot.FindAttribute(
                typeof(SolitaryCrown),
                "RegisterRelicAttribute")
            ?? throw new AcceptanceFailureException("SolitaryCrown must carry RegisterRelicAttribute.");
        var fixedPublicEntry = registration.NamedArguments
            .Single(argument => argument.MemberName == "FullPublicEntry")
            .TypedValue.Value as string;
        AcceptanceAssert.Equal(
            "VIVHITE_RELIC_ORIGIN_STAR_CHART",
            fixedPublicEntry ?? string.Empty,
            "Solitary Crown must explicitly pin the old save key while using its current player-facing type name.");
        AcceptanceAssert.True(
            repository.CompiledProductionTypes.All(type => type.Name != "OriginStarChart"),
            "OriginStarChart must not survive as a second registered relic; compatibility belongs to SolitaryCrown's fixed ID.");

        (int MaxHp, int ExpectedHealing)[] cases =
        [
            (0, 0),
            (1, 1),
            (4, 1),
            (5, 1),
            (6, 2),
            (9, 2),
            (10, 2),
            (11, 3),
            (78, 16),
            (100, 20),
            (101, 21),
            (1_000_000, 200_000),
            (int.MaxValue, 429_496_730)
        ];

        foreach (var (maxHp, expectedHealing) in cases)
        {
            AcceptanceAssert.Equal(
                expectedHealing,
                SolitaryCrown.CalculateHealingForMaxHp(maxHp),
                $"Solitary Crown must heal ceil(20% of {maxHp} Max HP). ");
        }

        var rejectedNegativeMaxHp = false;
        try
        {
            SolitaryCrown.CalculateHealingForMaxHp(-1);
        }
        catch (ArgumentOutOfRangeException)
        {
            rejectedNegativeMaxHp = true;
        }

        AcceptanceAssert.True(
            rejectedNegativeMaxHp,
            "A negative Max HP input must be rejected instead of producing invalid healing.");
        AcceptanceAssert.Equal(
            typeof(AnyEnemyDeathRelic),
            typeof(SolitaryCrown).BaseType!,
            "Solitary Crown must retain the shared per-entity enemy-death deduplication listener. ");
        AcceptanceAssert.Empty(
            typeof(SolitaryCrown).GetFields(
                    BindingFlags.Instance |
                    BindingFlags.Public |
                    BindingFlags.NonPublic |
                    BindingFlags.DeclaredOnly),
            "Solitary Crown must not add a per-turn, per-combat, trigger-count, or healing cap field:");

        VerifyLocalization(repository, "eng", "Solitary Crown", "rounded up");
        VerifyLocalization(repository, "zhs", "孤高冠冕", "向上取整");
    }

    public static void DeathCallbackUsesCurrentOwnerMaxHpAndSharedPerEntityDeduplication(
        RepositorySnapshot repository)
    {
        var crownSource = repository.RequireSourceType(typeof(SolitaryCrown).FullName!).Declaration;
        var callback = crownSource.Members
            .OfType<MethodDeclarationSyntax>()
            .Single(method => method.Identifier.ValueText == "OnAnyEnemyDeath");

        var healCalls = callback.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(invocation => IsMemberChain(invocation.Expression, "Overheal", "HealAsync"))
            .ToArray();
        AcceptanceAssert.Equal(
            1,
            healCalls.Length,
            "Solitary Crown must issue exactly one Overheal.HealAsync request for every accepted enemy-death event. ");

        var healCall = healCalls[0];
        AcceptanceAssert.True(
            healCall.Parent is AwaitExpressionSyntax awaitExpression &&
            ReferenceEquals(awaitExpression.Expression, healCall),
            "Solitary Crown must await its death-triggered healing before the callback completes.");
        AcceptanceAssert.Equal(
            2,
            healCall.ArgumentList.Arguments.Count,
            "Solitary Crown must pass only the owner creature and calculated amount to Overheal.HealAsync. ");
        AcceptanceAssert.True(
            IsMemberChain(healCall.ArgumentList.Arguments[0].Expression, "Owner", "Creature"),
            "Solitary Crown must heal Owner.Creature, not the dead enemy or another recipient.");

        var healingCalculation = healCall.ArgumentList.Arguments[1].Expression as InvocationExpressionSyntax;
        AcceptanceAssert.True(
            healingCalculation is not null &&
            IsMemberChain(healingCalculation.Expression, "CalculateHealingForMaxHp"),
            "Solitary Crown must pass CalculateHealingForMaxHp(...) directly into Overheal.HealAsync.");
        AcceptanceAssert.Equal(
            1,
            healingCalculation!.ArgumentList.Arguments.Count,
            "Solitary Crown's healing calculator must receive exactly one current Max HP value. ");
        AcceptanceAssert.True(
            IsMemberChain(
                healingCalculation.ArgumentList.Arguments[0].Expression,
                "Owner",
                "Creature",
                "MaxHp"),
            "Solitary Crown must calculate each death heal from Owner.Creature.MaxHp at callback time.");

        AcceptanceAssert.Empty(
            callback.DescendantNodes()
                .OfType<InvocationExpressionSyntax>()
                .Where(invocation =>
                    IsMemberChain(invocation.Expression, "Math", "Min") ||
                    IsMemberChain(invocation.Expression, "Math", "Clamp"))
                .Select(invocation => invocation.ToString())
                .ToArray(),
            "Solitary Crown's death callback must not cap or clamp the calculated healing:");
        AcceptanceAssert.Empty(
            crownSource.Members
                .OfType<MethodDeclarationSyntax>()
                .Where(method => method.Identifier.ValueText == "AfterDeath")
                .Select(method => method.Identifier.ValueText)
                .ToArray(),
            "Solitary Crown must not replace the shared enemy-death dispatch/deduplication layer:");
        AcceptanceAssert.True(
            !crownSource.DescendantNodes()
                .OfType<IdentifierNameSyntax>()
                .Any(identifier => identifier.Identifier.ValueText == nameof(EnemyDeathTracker)),
            "Solitary Crown must not maintain a private death tracker; deduplication belongs to AnyEnemyDeathRelic.");

        var sharedDeathSource = repository.RequireSourceType(typeof(AnyEnemyDeathRelic).FullName!).Declaration;
        var sharedAfterDeath = sharedDeathSource.Members
            .OfType<MethodDeclarationSyntax>()
            .Single(method => method.Identifier.ValueText == "AfterDeath");
        AcceptanceAssert.True(
            sharedAfterDeath.DescendantNodes()
                .OfType<InvocationExpressionSyntax>()
                .Any(invocation => IsMemberChain(invocation.Expression, "tracker", "TryCreate")),
            "AnyEnemyDeathRelic.AfterDeath must claim each entity death through the shared EnemyDeathTracker.");
        AcceptanceAssert.True(
            sharedAfterDeath.DescendantNodes()
                .OfType<InvocationExpressionSyntax>()
                .Any(invocation => IsMemberChain(invocation.Expression, "InvokeEnemyDeathAsync")),
            "AnyEnemyDeathRelic.AfterDeath must dispatch every successfully claimed event to the relic callback.");

        var compiledSharedAfterDeath = typeof(AnyEnemyDeathRelic).GetMethod(
            "AfterDeath",
            BindingFlags.Instance | BindingFlags.Public)
            ?? throw new AcceptanceFailureException("AnyEnemyDeathRelic.AfterDeath is missing.");
        AcceptanceAssert.True(
            compiledSharedAfterDeath.IsFinal,
            "The shared enemy-death dispatcher must remain sealed so individual relics cannot bypass its deduplication.");

        var owner = EngineTestObjects.CreateCreature(currentHp: 50, maxHp: 101, enemy: false);
        var firstEnemy = EngineTestObjects.CreateCreature(currentHp: 0, maxHp: 20, enemy: true);
        var secondEnemy = EngineTestObjects.CreateCreature(currentHp: 0, maxHp: 20, enemy: true);
        var tracker = new EnemyDeathTracker();

        AcceptanceAssert.True(
            tracker.TryCreate(owner, firstEnemy, wasRemovalPrevented: false, 0.1f, out var firstDeath),
            "The shared death layer must accept the first death event for an enemy entity.");
        AcceptanceAssert.True(
            !tracker.TryCreate(owner, firstEnemy, wasRemovalPrevented: false, 0.1f, out _),
            "The shared death layer must suppress a duplicate delivery for the same enemy death event.");
        AcceptanceAssert.True(
            tracker.TryCreate(owner, secondEnemy, wasRemovalPrevented: false, 0.2f, out var secondDeath),
            "A different enemy must trigger independently, without a per-turn or per-combat trigger cap.");
        AcceptanceAssert.True(
            ReferenceEquals(firstDeath.ListenerOwner, owner) &&
            ReferenceEquals(firstDeath.Enemy, firstEnemy) &&
            ReferenceEquals(secondDeath.ListenerOwner, owner) &&
            ReferenceEquals(secondDeath.Enemy, secondEnemy),
            "The shared death layer must preserve the owner and each distinct enemy identity when dispatching callbacks.");
    }

    private static void VerifyLocalization(
        RepositorySnapshot repository,
        string locale,
        string expectedTitle,
        string roundingText)
    {
        var path = Path.Combine(repository.LocalizationDirectory, locale, "relics.json");
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var root = document.RootElement;
        const string compatibilityKey = "VIVHITE_RELIC_ORIGIN_STAR_CHART";
        const string incompatibleReplacementKey = "VIVHITE_RELIC_SOLITARY_CROWN";
        var title = root.GetProperty($"{compatibilityKey}.title").GetString() ?? string.Empty;
        var description = root.GetProperty($"{compatibilityKey}.description").GetString() ?? string.Empty;

        AcceptanceAssert.True(
            !root.TryGetProperty($"{incompatibleReplacementKey}.title", out _) &&
            !root.TryGetProperty($"{incompatibleReplacementKey}.description", out _) &&
            !root.TryGetProperty($"{incompatibleReplacementKey}.flavor", out _),
            $"{locale} relic localization must use only the old-save compatibility key, not a breaking replacement ID.");

        AcceptanceAssert.Equal(expectedTitle, title, $"{locale} relic title must match the approved player-facing name. ");
        AcceptanceAssert.True(
            description.Contains("{Heal}%", StringComparison.Ordinal),
            $"{locale} relic description must present the twenty-point Heal variable as a percentage.");
        AcceptanceAssert.True(
            description.Contains(roundingText, StringComparison.Ordinal),
            $"{locale} relic description must explicitly state ceiling rounding.");
    }

    private static bool IsMemberChain(ExpressionSyntax expression, params string[] expectedParts)
    {
        var actualParts = new Stack<string>();
        ExpressionSyntax? current = expression;
        while (current is MemberAccessExpressionSyntax memberAccess)
        {
            actualParts.Push(memberAccess.Name.Identifier.ValueText);
            current = memberAccess.Expression;
        }
        if (current is IdentifierNameSyntax identifier)
        {
            actualParts.Push(identifier.Identifier.ValueText);
        }
        else
        {
            return false;
        }
        return actualParts.SequenceEqual(expectedParts, StringComparer.Ordinal);
    }

#if VIVHITE_RELIC_ACCEPTANCE
    [ModuleInitializer]
    internal static void RunStandalone()
    {
        var repository = RepositorySnapshot.Load();
        UsesTwentyPercentMaxHpCeilingWithoutTriggerCaps(repository);
        DeathCallbackUsesCurrentOwnerMaxHpAndSharedPerEntityDeduplication(repository);
        Console.WriteLine("[PASS] Solitary Crown heals ceil(20% Max HP) per deduplicated enemy death without custom caps");
    }
#endif
}
