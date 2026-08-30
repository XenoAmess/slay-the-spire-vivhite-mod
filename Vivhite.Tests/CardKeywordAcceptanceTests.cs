using MegaCrit.Sts2.Core.Entities.Cards;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Vivhite.Cards.Common;
using Vivhite.Cards.Conservation;
using Vivhite.Cards.Recursion;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class CardKeywordAcceptanceTests
{
    public static void ConditionalKeywordsMatchTheApprovedCardStates(RepositorySnapshot repository)
    {
        var axiomRing = new AxiomRing();
        var axiomKeywords = axiomRing.CanonicalKeywords.ToArray();
        AcceptanceAssert.True(
            !axiomKeywords.Contains(VivhiteKeywords.LifeCalculation),
            "Axiom Ring has no Life Calculation cost and must not declare the Life Calculation keyword.");
        AcceptanceAssert.True(
            axiomKeywords.Contains(VivhiteKeywords.Margin),
            "Axiom Ring must still declare its Margin keyword.");

        var canonicalAstralPursuit = new AstralPursuit();
        AssertAstralPursuitKeywords(canonicalAstralPursuit, expectsMargin: false, "base");

        var keywordProperty = repository.RequireSourceType(typeof(AstralPursuit).FullName!)
            .Declaration.Members
            .OfType<PropertyDeclarationSyntax>()
            .Single(property => property.Identifier.ValueText == "AdditionalVivhiteKeywords");
        var conditional = keywordProperty.ExpressionBody?.Expression as ConditionalExpressionSyntax;
        AcceptanceAssert.True(
            conditional?.Condition is IdentifierNameSyntax condition &&
            condition.Identifier.ValueText == "IsUpgraded",
            "Astral Pursuit's compiled source must condition its additional keywords directly on IsUpgraded.");
        var upgradedKeywords = conditional!.WhenTrue.DescendantNodesAndSelf()
            .OfType<MemberAccessExpressionSyntax>()
            .Select(access => access.Name.Identifier.ValueText)
            .ToArray();
        AcceptanceAssert.True(
            upgradedKeywords.SequenceEqual(["Margin"]),
            "Astral Pursuit's upgraded branch must declare exactly the Margin keyword.");
        AcceptanceAssert.True(
            conditional.WhenFalse is CollectionExpressionSyntax { Elements.Count: 0 },
            "Astral Pursuit's base branch must declare no additional keyword.");
    }

    private static void AssertAstralPursuitKeywords(
        AstralPursuit card,
        bool expectsMargin,
        string state)
    {
        CardKeyword[] keywords = card.CanonicalKeywords.ToArray();
        AcceptanceAssert.True(
            keywords.Contains(VivhiteKeywords.LifeCalculation),
            $"Astral Pursuit must declare Life Calculation in its {state} state.");
        AcceptanceAssert.Equal(
            expectsMargin,
            keywords.Contains(VivhiteKeywords.Margin),
            $"Astral Pursuit must declare Margin only in its upgraded state (checked {state}).");
    }
}
