using System.Reflection;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Vivhite.Core;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static partial class UnboundedGrowthAcceptanceTests
{
    public static void HasNoArtificialCapConstantsOrStaticFields(RepositorySnapshot repository)
    {
        var violations = repository.CompiledProductionTypes
            .SelectMany(type => type
                .GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly)
                .Where(field => field.IsLiteral || field.IsStatic)
                .Where(field => ArtificialCapName().IsMatch(field.Name))
                .Select(field => $"{type.FullName}.{field.Name}"))
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Empty(
            violations,
            "Compiled production code must not define artificial cap/quota fields for Margin, Dimension Up, healing, Drain, or death triggers:");
    }

    public static void DimensionUpUsesUncappedStackableMaxAndCurrentHpGrowth(RepositorySnapshot repository)
    {
        var hundred = DimensionUp.Calculate(amount: 100, infiniteExtensionStacks: 100);
        AcceptanceAssert.Equal(100, hundred.InfiniteExtensionBonus, "Every Infinite Extension stack must contribute once.");
        AcceptanceAssert.Equal(200, hundred.RequestedTotal, "100 growth with 100 Extension stacks must produce 200, without a cap.");

        var thousand = DimensionUp.Calculate(amount: 1_000, infiniteExtensionStacks: 1_000);
        AcceptanceAssert.Equal(1_000, thousand.InfiniteExtensionBonus, "Infinite Extension must remain stackable at 1,000 stacks.");
        AcceptanceAssert.Equal(2_000, thousand.RequestedTotal, "Dimension Up must remain linear at 1,000-scale input.");

        var zero = DimensionUp.Calculate(amount: 0, infiniteExtensionStacks: 1_000);
        AcceptanceAssert.Equal(0, zero.InfiniteExtensionBonus, "A zero growth event must not manufacture Extension growth.");
        AcceptanceAssert.Equal(0, zero.RequestedTotal, "A zero growth event must remain zero.");

        var sourceType = repository.RequireSourceType("Vivhite.Core.DimensionUp");
        var method = sourceType.Declaration.Members
            .OfType<MethodDeclarationSyntax>()
            .Single(member => member.Identifier.ValueText == "GainMaxHpAsync");

        var calculateCalls = method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(invocation => invocation.Expression.ToString() == "Calculate")
            .ToArray();
        AcceptanceAssert.Equal(1, calculateCalls.Length, "Runtime Dimension Up must use the tested pure Calculate(amount, stacks) contract.");
        AcceptanceAssert.True(
            calculateCalls[0].ArgumentList.Arguments.Select(argument => argument.Expression.ToString())
                .SequenceEqual(["amount", "extensionStacks"], StringComparer.Ordinal),
            "Runtime Dimension Up must pass the requested amount and all Infinite Extension stacks to Calculate.");

        var nativeGrowthCalls = method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(invocation =>
                invocation.Expression is MemberAccessExpressionSyntax access &&
                access.Expression.ToString() == "CreatureCmd" &&
                access.Name.Identifier.ValueText == "GainMaxHp")
            .ToArray();
        AcceptanceAssert.Equal(1, nativeGrowthCalls.Length, "DimensionUp must use exactly one native GainMaxHp call.");
        AcceptanceAssert.True(
            nativeGrowthCalls[0].ArgumentList.Arguments.Count == 2 &&
            nativeGrowthCalls[0].ArgumentList.Arguments[1].Expression.ToString() == "requestedTotal",
            "DimensionUp must forward the full uncapped requested total to CreatureCmd.GainMaxHp.");

        var capCalls = method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(invocation => invocation.Expression is MemberAccessExpressionSyntax access &&
                access.Expression.ToString() == "Math" &&
                access.Name.Identifier.ValueText is "Min" or "Clamp")
            .Select(invocation => invocation.ToString())
            .ToArray();
        AcceptanceAssert.Empty(capCalls, "DimensionUp must not Min/Clamp its requested growth:");

        var extensionType = repository.RequireSourceType("Vivhite.Core.InfiniteExtension");
        var gainMethod = extensionType.Declaration.Members
            .OfType<MethodDeclarationSyntax>()
            .Single(member => member.Identifier.ValueText == "GainAsync");
        AcceptanceAssert.True(
            gainMethod.ParameterList.Parameters.Any(parameter =>
                parameter.Identifier.ValueText == "amount" && parameter.Type?.ToString() == "int"),
            "InfiniteExtension must expose an integer GainAsync amount instead of a one-time boolean activation.");

        var resultProperties = typeof(DimensionUpResult).GetProperties()
            .Select(property => property.Name)
            .ToArray();
        string[] requiredResultProperties =
        [
            "RequestedTotal",
            "MaxHpBefore",
            "MaxHpAfter",
            "CurrentHpBefore",
            "CurrentHpAfter"
        ];
        AcceptanceAssert.SetEqual(
            requiredResultProperties,
            resultProperties.Where(requiredResultProperties.Contains).ToArray(),
            "Compiled DimensionUpResult must expose both max-HP and equal-current-HP before/after evidence.");

        var currentHpReads = method.DescendantNodes()
            .OfType<MemberAccessExpressionSyntax>()
            .Count(access => access.Expression.ToString() == "creature" && access.Name.Identifier.ValueText == "CurrentHp");
        AcceptanceAssert.True(
            currentHpReads >= 2,
            "Runtime Dimension Up must capture current HP before native GainMaxHp and report current HP afterward.");
    }

    public static void OverhealPreservesUncappedExcess(RepositorySnapshot _)
    {
        var fullHealth = EngineTestObjects.CreateCreature(currentHp: 100, maxHp: 100, enemy: false);
        var fullQuote = Overheal.Calculate(fullHealth, 1_000);
        AcceptanceAssert.Equal(0, fullQuote.ExpectedHealing, "Normal healing remains naturally bounded by missing HP.");
        AcceptanceAssert.Equal(1_000, fullQuote.ExpectedExcess, "All 1,000 excess healing must remain available for conversion, without an artificial cap.");

        var damaged = EngineTestObjects.CreateCreature(currentHp: 10, maxHp: 100, enemy: false);
        var damagedQuote = Overheal.Calculate(damaged, 1_000);
        AcceptanceAssert.Equal(90, damagedQuote.ExpectedHealing, "Healing must first fill the exact natural missing-HP amount.");
        AcceptanceAssert.Equal(910, damagedQuote.ExpectedExcess, "The full remainder must be reported as excess at 1,000-scale input.");
    }

    [GeneratedRegex(
        "(?ix)(?:(?:max(?:imum)?|cap|limit|ceiling|quota|budget).*(?:dimension|growth|margin|drain|leech|heal|death)|(?:dimension|growth|margin|drain|leech|heal|death).*(?:max(?:imum)?|cap|limit|ceiling|quota|budget))",
        RegexOptions.CultureInvariant)]
    private static partial Regex ArtificialCapName();
}
