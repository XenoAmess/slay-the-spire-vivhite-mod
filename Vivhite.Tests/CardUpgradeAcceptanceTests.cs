using System.Reflection;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Vivhite.Cards.Hybrid;
using Vivhite.Cards.Recursion;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class CardUpgradeAcceptanceTests
{
    public static void EveryRegisteredCardHasAnEffectiveUpgrade(RepositorySnapshot repository)
    {
        AcceptanceAssert.Equal(61, repository.VivhitePoolCards.Count, "Upgrade acceptance must enumerate the complete 61-card pool.");
        var failures = new List<string>();
        var behaviorOnlyCards = new List<string>();
        foreach (var cardType in repository.VivhitePoolCards)
        {
            var cardId = repository.CardId(cardType);
            try
            {
                var card = MakeMutable((CardModel)(Activator.CreateInstance(cardType)
                    ?? throw new AcceptanceFailureException($"Could not construct {cardId}.")));
                var originalEnergy = card.EnergyCost.GetWithModifiers(CostModifiers.None);
                var originalVars = card.DynamicVars.Keys.ToDictionary(name => name, name => card.DynamicVars[name].BaseValue);
                card.UpgradeInternal();
                AcceptanceAssert.True(card.IsUpgraded, "The native upgrade path must mark the card upgraded.");
                var upgradedEnergy = card.EnergyCost.GetWithModifiers(CostModifiers.None);
                var upgradedVars = card.DynamicVars.Keys.ToDictionary(name => name, name => card.DynamicVars[name].BaseValue);
                card.FinalizeUpgradeInternal();
                AcceptanceAssert.True(card.IsUpgraded, "The upgrade flag must survive native finalization.");
                AcceptanceAssert.Equal(upgradedEnergy, card.EnergyCost.GetWithModifiers(CostModifiers.None),
                    "The upgraded Energy cost must survive native finalization.");
                foreach (var (name, value) in upgradedVars)
                {
                    AcceptanceAssert.Equal(value, card.DynamicVars[name].BaseValue,
                        $"The upgraded {name} value must survive native finalization.");
                }

                // Observe actual compiled mutations: a nonempty hook, an upgrade flag, and
                // switching to a differently named but identical Power are not sufficient.
                var energyImproved = upgradedEnergy >= 0 && upgradedEnergy < originalEnergy;
                var varsChanged = originalVars.Count != card.DynamicVars.Keys.Count() || originalVars.Any(entry =>
                    !card.DynamicVars.TryGetValue(entry.Key, out var upgraded) || upgraded.BaseValue != entry.Value);
                if (energyImproved || varsChanged)
                {
                    continue;
                }

                AssertApprovedBehaviorOnlyUpgrade(repository, cardType);
                behaviorOnlyCards.Add(cardId);
            }
            catch (Exception exception)
            {
                failures.Add($"{cardId}: {exception.GetBaseException().Message}");
            }
        }

        AcceptanceAssert.Empty(failures, "Every registered card must change an actual cost/value or pass its specific behavior upgrade contract:");
        AcceptanceAssert.SetEqual(
            ["VIVHITE_CARD_ASTRAL_PURSUIT", "VIVHITE_CARD_INFINITE_STAR_SEQUENCE", "VIVHITE_CARD_CONSERVED_RECURRENCE"],
            behaviorOnlyCards,
            "Exactly the three reviewed behavior-only upgrades may leave all card-face numbers unchanged.");
    }

    private static void AssertApprovedBehaviorOnlyUpgrade(RepositorySnapshot repository, Type cardType)
    {
        var method = RequireMethod(cardType, "OnPlayAfterLifePayment");
        var calls = IlInspection.CalledMethods(method);
        AcceptanceAssert.True(
            calls.Any(call => call.Name == "get_IsUpgraded"),
            $"{cardType.Name} must read IsUpgraded in its compiled play callback, not only its text or keywords.");
        var play = RequireSourceMethod(repository, cardType, method.Name);
        if (cardType == typeof(AstralPursuit))
        {
            AssertUpgradeBranchCalls(play, "PowerCmd.Apply<AstralPursuitMarginPower>",
                "choiceContext,Owner.Creature,1,Owner.Creature,this");
            AcceptanceAssert.True(calls.OfType<MethodInfo>().Any(call =>
                    call.IsGenericMethod && call.Name == "Apply" &&
                    call.GetGenericArguments().SequenceEqual([typeof(AstralPursuitMarginPower)])),
                "Astral Pursuit's compiled upgraded branch must install the additional Margin observer.");
            var deathCallback = RequireSourceMethod(repository, typeof(AstralPursuitMarginPower), "OnAnyEnemyDeath");
            AssertInvocation(deathCallback, "InfiniteMargin.GainAsync", "choiceContext,Owner,Amount,Owner");
            AcceptanceAssert.True(
                IlInspection.CalledMethods(RequireMethod(typeof(AstralPursuitMarginPower), "OnAnyEnemyDeath"))
                    .Any(call => call.Name == "GainAsync"),
                "Astral Pursuit's additional death observer must execute Margin recovery.");
        }
        else if (cardType == typeof(InfiniteStarSequence))
        {
            var requestedDraw = play.DescendantNodes().OfType<VariableDeclaratorSyntax>()
                .Single(variable => variable.Identifier.ValueText == "requestedDraw");
            AcceptanceAssert.Equal("2*(priorCardsPlayed+(IsUpgraded?1:0))",
                Compact(requestedDraw.Initializer!.Value.ToString()),
                "Infinite Star Sequence's upgrade must add two requested draws, including with no earlier cards played.");
            AssertInvocation(play, "DrawAsync", "choiceContext,requestedDraw");
            AssertInvocation(play, "InfiniteMargin.GainAsync", "choiceContext,Owner.Creature,actuallyDrawn,Owner.Creature,this");
            AcceptanceAssert.True(calls.Any(call => call.Name == "DrawAsync") && calls.Any(call => call.Name == "GainAsync"),
                "Infinite Star Sequence must consume the changed draw request and grant Margin for actual draws.");
        }
        else if (cardType == typeof(ConservedRecurrence))
        {
            AssertUpgradeBranchCalls(play, "selected.SetToFreeThisTurn", "");
            AssertInvocation(play, "copy.SetToFreeThisTurn", "");
            AssertInvocation(play, "CardPileCmd.Add", "selected,PileType.Hand,CardPilePosition.Bottom,this,false");
            AcceptanceAssert.Equal(2, calls.Count(call => call.Name == "SetToFreeThisTurn"),
                "Conserved Recurrence must make the copy free and additionally make the returned original free when upgraded.");
        }
        else
        {
            throw new AcceptanceFailureException("No numerical upgrade and no reviewed behavioral benefit. An IsUpgraded reference alone is insufficient.");
        }
    }

    private static void AssertUpgradeBranchCalls(MethodDeclarationSyntax play, string invocation, string arguments)
    {
        var upgradedBranch = play.Body!.Statements.OfType<IfStatementSyntax>()
            .Single(branch => branch.Condition is IdentifierNameSyntax { Identifier.ValueText: "IsUpgraded" });
        AcceptanceAssert.True(upgradedBranch.Else is null, "The additional upgrade effect must run only in the upgraded branch.");
        var call = upgradedBranch.Statement.DescendantNodes().OfType<InvocationExpressionSyntax>().Single();
        AcceptanceAssert.Equal(invocation, call.Expression.ToString(), "The upgraded branch must execute the approved extra effect.");
        AcceptanceAssert.Equal(arguments, Compact(string.Join(",", call.ArgumentList.Arguments)), "The upgraded effect must use its approved recipient and amount.");
        AssertInvocation(play, invocation, arguments);
    }

    private static void AssertInvocation(Microsoft.CodeAnalysis.SyntaxNode source, string expression, string arguments)
    {
        var call = source.DescendantNodes().OfType<InvocationExpressionSyntax>()
            .Single(invocation => invocation.Expression.ToString() == expression);
        AcceptanceAssert.Equal(arguments, Compact(string.Join(",", call.ArgumentList.Arguments)),
            $"{expression} must consume the approved upgrade data.");
    }

    private static MethodDeclarationSyntax RequireSourceMethod(RepositorySnapshot repository, Type type, string name) =>
        repository.RequireSourceType(type.FullName!).Declaration.Members.OfType<MethodDeclarationSyntax>()
            .Single(method => method.Identifier.ValueText == name);

    private static MethodInfo RequireMethod(Type type, string name) =>
        type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
        ?? throw new AcceptanceFailureException($"{type.FullName}.{name} is missing.");

    private static T MakeMutable<T>(T model) where T : AbstractModel
    {
        for (var cursor = model.GetType(); cursor is not null; cursor = cursor.BaseType)
        {
            var field = cursor.GetField("<IsMutable>k__BackingField",
                BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
            if (field is null)
            {
                continue;
            }
            field.SetValue(model, true);
            return model;
        }
        throw new AcceptanceFailureException($"{model.GetType().FullName} has no IsMutable backing field.");
    }

    private static string Compact(string value) => new(value.Where(character => !char.IsWhiteSpace(character)).ToArray());
}
