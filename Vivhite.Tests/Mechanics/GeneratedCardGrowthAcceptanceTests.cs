using System.Reflection;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Vivhite.Core;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class GeneratedCardGrowthAcceptanceTests
{
    public static void GeneratedAndRecoveredCopiesRetainNormalDimensionUpEligibility(RepositorySnapshot repository)
    {
        string[] copyCardTypes =
        [
            "Vivhite.Cards.Recursion.EventLoop",
            "Vivhite.Cards.Hybrid.ConservedRecurrence"
        ];
        var copyFailures = new List<string>();
        foreach (var fullName in copyCardTypes)
        {
            var cardType = repository.CompiledAssembly.GetType(fullName, throwOnError: false);
            if (cardType is null)
            {
                copyFailures.Add($"{fullName}: missing compiled card type");
                continue;
            }
            var effect = DeclaredEffect(cardType);
            var calls = IlInspection.CalledMethods(effect);
            if (!calls.Any(method => method.Name == "CreateClone"))
            {
                copyFailures.Add($"{fullName}: does not clone the selected normal card instance");
            }
            if (!calls.Any(method =>
                    method.DeclaringType?.FullName == "MegaCrit.Sts2.Core.Commands.CardPileCmd" &&
                    method.Name == "AddGeneratedCardToCombat"))
            {
                copyFailures.Add($"{fullName}: does not add the clone through the normal generated-card pipeline");
            }
        }
        AcceptanceAssert.Empty(
            copyFailures,
            "Event Loop and Conserved Recurrence must generate ordinary runtime clones, not downgraded special card types:");

        string[] dimensionCardTypes =
        [
            "Vivhite.Cards.Conservation.ScaleTransformation",
            "Vivhite.Cards.Conservation.TopologicalGrowth",
            "Vivhite.Cards.Conservation.AxiomOfLife"
        ];
        var growthFailures = new List<string>();
        foreach (var fullName in dimensionCardTypes)
        {
            var cardType = repository.CompiledAssembly.GetType(fullName, throwOnError: false);
            if (cardType is null)
            {
                growthFailures.Add($"{fullName}: missing compiled card type");
                continue;
            }
            var calls = IlInspection.CalledMethods(DeclaredEffect(cardType));
            if (!calls.Any(method =>
                    method.DeclaringType == typeof(DimensionUp) &&
                    method.Name == nameof(DimensionUp.ApplyAsync)))
            {
                growthFailures.Add($"{fullName}: card effect bypasses the shared DimensionUp.ApplyAsync entry point");
            }
        }
        AcceptanceAssert.Empty(
            growthFailures,
            "Every approved Dimension Up card must call the same core entry point, so its runtime clones stay eligible:");

        var coreSource = repository.RequireSourceType("Vivhite.Core.DimensionUp").Declaration;
        var sourceOriginFilters = coreSource.DescendantNodes()
            .OfType<IfStatementSyntax>()
            .Where(statement => statement.Condition.ToString().Contains("cardSource", StringComparison.Ordinal))
            .Select(statement => statement.Condition.ToString())
            .Concat(coreSource.DescendantNodes()
                .OfType<MemberAccessExpressionSyntax>()
                .Where(access => access.Expression.ToString().Contains("cardSource", StringComparison.Ordinal))
                .Select(access => access.ToString()))
            .Distinct(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Empty(
            sourceOriginFilters,
            "DimensionUp may carry CardModel provenance but must not inspect it to exclude generated, copied, temporary, repeated, or recovered cards:");
    }

    private static MethodInfo DeclaredEffect(Type cardType) =>
        cardType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
            .Single(method => method.Name == "OnPlayAfterLifePayment");
}
