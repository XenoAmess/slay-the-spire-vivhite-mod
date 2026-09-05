using System.Reflection;
using System.Text.Json;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Vivhite.Cards.Chromatic;
using Vivhite.Cards.Hybrid;
using Vivhite.Cards.Recursion;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class FinalBalanceAcceptanceTests
{
    private static readonly string[] ImmediateCoughDrawOrDiscardCardIds =
    [
        "VIVHITE_CARD_RECURRENT_STARLIGHT",
        "VIVHITE_CARD_ASTRAL_SEARCH",
        "VIVHITE_CARD_HEURISTIC_SHIELD",
        "VIVHITE_CARD_CONVERGENCE_VERDICT",
        "VIVHITE_CARD_DIVIDE_AND_CONQUER_CIRCLE",
        "VIVHITE_CARD_PREFETCH_FUTURE",
        "VIVHITE_CARD_PROOF_OF_TERMINATION",
        "VIVHITE_CARD_INFINITE_STAR_SEQUENCE",
        "VIVHITE_CARD_CHROMATIC_TRANSITION",
        "VIVHITE_CARD_GOLDEN_RATIO",
        "VIVHITE_CARD_CHROMATIC_SEQUENCE"
    ];

    private static readonly string[] TriggeredPowerDrawCardIds =
    [
        "VIVHITE_CARD_ASTRAL_PURSUIT",
        "VIVHITE_CARD_OPTIMAL_ALGORITHM"
    ];

    private static readonly DrawVarExpectation[] DynamicDrawCards =
    [
        new(
            typeof(RecurrentStarlight),
            "VIVHITE_CARD_RECURRENT_STARLIGHT",
            4,
            4,
            "DrawAsync(choiceContext,DynamicVars.Cards.BaseValue)"),
        new(
            typeof(AstralSearch),
            "VIVHITE_CARD_ASTRAL_SEARCH",
            4,
            6,
            "DrawAsync(choiceContext,DynamicVars.Cards.BaseValue)"),
        new(
            typeof(ConvergenceVerdict),
            "VIVHITE_CARD_CONVERGENCE_VERDICT",
            6,
            6,
            "DrawAsync(choiceContext,DynamicVars.Cards.BaseValue)"),
        new(
            typeof(DivideAndConquerCircle),
            "VIVHITE_CARD_DIVIDE_AND_CONQUER_CIRCLE",
            4,
            6,
            "DrawAsync(choiceContext,DynamicVars.Cards.BaseValue)"),
        new(
            typeof(PrefetchFuture),
            "VIVHITE_CARD_PREFETCH_FUTURE",
            6,
            6,
            "DrawAsync(choiceContext,DynamicVars.Cards.BaseValue)"),
        new(
            typeof(GoldenRatio),
            "VIVHITE_CARD_GOLDEN_RATIO",
            2,
            2,
            "CardPileCmd.Draw(choiceContext,DynamicVars.Cards.BaseValue,Owner,false)"),
        new(
            typeof(ChromaticSequence),
            "VIVHITE_CARD_CHROMATIC_SEQUENCE",
            4,
            6,
            "CardPileCmd.Draw(choiceContext,DynamicVars.Cards.BaseValue,Owner,false)")
    ];

    public static void EveryCoughDrawAndDiscardEffectUsesTheFinalDoubledAmount(
        RepositorySnapshot repository)
    {
        AcceptanceAssert.Equal(
            61,
            repository.VivhitePoolCards.Count,
            "The Cough draw/discard audit must enumerate the complete 61-card Vivhite pool.");

        var cards = repository.VivhitePoolCards.ToDictionary(
            repository.CardId,
            type => MakeMutableForUpgrade((CardModel)(Activator.CreateInstance(type)
                ?? throw new AcceptanceFailureException($"Could not construct {type.FullName}."))),
            StringComparer.Ordinal);

        var actualImmediateCards = cards
            .Where(entry => HasFixedOrStagedCough(entry.Value))
            .Where(entry => HasImmediateCardPlayDrawOrDiscardCall(repository, entry.Value.GetType()))
            .Select(entry => entry.Key)
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.SetEqual(
            ImmediateCoughDrawOrDiscardCardIds,
            actualImmediateCards,
            "Exactly the approved Cough cards may draw or discard during their own card-play resolution. " +
            "A newly registered card with fixed/staged Cough plus an immediate Draw/Discard call must be reviewed here.");

        var triggeredCardsMisclassifiedAsImmediate = TriggeredPowerDrawCardIds
            .Intersect(actualImmediateCards, StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Empty(
            triggeredCardsMisclassifiedAsImmediate,
            "Power-triggered draw cards must not be mistaken for card-face immediate draw/discard effects:");

        foreach (var expectation in DynamicDrawCards)
        {
            AcceptanceAssert.Equal(
                expectation.CardId,
                repository.CardId(expectation.CardType),
                $"{expectation.CardType.FullName} must retain its approved stable card ID.");
            var card = cards[expectation.CardId];
            AcceptanceAssert.Equal(
                expectation.BaseCards,
                card.DynamicVars["Cards"].IntValue,
                $"{expectation.CardId}.Cards must use the final doubled base draw amount.");
            InvokeOnUpgrade(expectation.CardId, card);
            AcceptanceAssert.Equal(
                expectation.UpgradedCards,
                card.DynamicVars["Cards"].IntValue,
                $"{expectation.CardId}.Cards must use the final doubled upgraded draw amount.");
            AssertSourceContains(
                repository,
                expectation.CardType,
                expectation.DrawInvocation,
                $"{expectation.CardId} must pass its doubled Cards DynamicVar to the immediate draw call.");
        }

        AssertSourceContains(
            repository,
            typeof(HeuristicShield),
            "DrawAsync(choiceContext,2)",
            "Heuristic Shield must draw two cards.");
        AssertSourceContains(
            repository,
            typeof(AstralPursuit),
            "PowerCmd.Apply<AstralPursuitPower>",
            "Astral Pursuit must delegate its delayed draw to AstralPursuitPower rather than drawing on card play.");
        AssertSourceContains(
            repository,
            typeof(AstralPursuitPower),
            "CardPileCmd.Draw(choiceContext,Amount*2,player,false)",
            "Astral Pursuit must draw two cards per stack on every enemy death.");
        AssertSourceContains(
            repository,
            typeof(ProofOfTermination),
            "DrawAsync(choiceContext,4)",
            "Proof of Termination must draw four cards per kill.");
        AssertSourceContains(
            repository,
            typeof(InfiniteStarSequence),
            "requestedDraw=2*(priorCardsPlayed+(IsUpgraded?1:0))",
            "Infinite Star Sequence must double both its per-card draw and upgraded bonus.");
        AssertSourceContains(
            repository,
            typeof(OptimalAlgorithm),
            "PowerCmd.Apply<OptimalAlgorithmPower>",
            "Optimal Algorithm must delegate its delayed draw to OptimalAlgorithmPower rather than drawing on card play.");
        AssertSourceContains(
            repository,
            typeof(OptimalAlgorithmPower),
            "CardPileCmd.Draw(choiceContext,4,player,false)",
            "Optimal Algorithm must draw four cards per stack on every enemy death.");
        AssertSourceContains(
            repository,
            typeof(ChromaticTransition),
            "CardPileCmd.Draw(choiceContext,2,Owner,false)",
            "Chromatic Transition must draw two cards.");
        AssertSourceContains(
            repository,
            typeof(AstralSearch),
            "CardSelectorPrefs(CardSelectorPrefs.DiscardSelectionPrompt,2)",
            "Astral Search must discard two cards after its doubled draw.");
        AssertSourceContains(
            repository,
            typeof(AstralSearch),
            "CardCmd.Discard(choiceContext,selected)",
            "Astral Search must execute the selected doubled discard instead of only opening a selector.");
    }

    public static void InductiveCircleUsesUncappedPercentageHealingAndFinalEnergy(
        RepositorySnapshot repository)
    {
        var card = new InductiveCircle();
        AcceptanceAssert.Equal(1, card.EnergyCost.Canonical, "Inductive Circle must cost one Energy.");
        AcceptanceAssert.Equal(8, card.DynamicVars["LifeCost"].IntValue, "Inductive Circle must retain Cough 8.");
        AcceptanceAssert.Equal(50, card.DynamicVars.Heal.IntValue, "Inductive Circle must add 50% before upgrade.");
        InvokeOnUpgrade("VIVHITE_CARD_INDUCTIVE_CIRCLE", card);
        AcceptanceAssert.Equal(1, card.EnergyCost.Canonical, "Upgrading Inductive Circle must not change its one-Energy cost.");
        AcceptanceAssert.Equal(75, card.DynamicVars.Heal.IntValue, "Upgraded Inductive Circle must add 75%.");

        var calculator = typeof(InductiveCirclePower).GetMethod(
            "CalculateAdditionalHealing",
            BindingFlags.Static | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException(
                "InductiveCirclePower.CalculateAdditionalHealing is missing.");
        (long BaseHealing, int Percentage, int Expected)[] cases =
        [
            (0, 50, 0),
            (16, 50, 8),
            (19, 50, 10),
            (19, 75, 15),
            (19, 125, 24),
            (1_000_000, 10_000, 100_000_000)
        ];
        foreach (var (baseHealing, percentage, expected) in cases)
        {
            var actual = (int)calculator.Invoke(null, [baseHealing, percentage])!;
            AcceptanceAssert.Equal(
                expected,
                actual,
                $"Inductive Circle must heal ceil({baseHealing} * {percentage}%) without a custom cap.");
        }

        var source = Compact(repository.RequireSourceType(typeof(InductiveCirclePower).FullName!).Declaration.ToFullString());
        AcceptanceAssert.True(
            source.Contains("SolitaryCrown.CalculateHealingForMaxHp(owner.MaxHp)", StringComparison.Ordinal) &&
            source.Contains("OptimalAlgorithmPower.HealingPerStack", StringComparison.Ordinal),
            "Inductive Circle's percentage base must include both Solitary Crown and Optimal Algorithm immediate healing.");
    }

    public static void InductiveCircleDeathHealingRuntimeChainIsCompleteAndUncapped(
        RepositorySnapshot repository)
    {
        var cardPlay = RequireSourceMethod(
            repository,
            typeof(InductiveCircle),
            "OnPlayAfterLifePayment");
        var applyPower = RequireSingleInvocation(
            cardPlay,
            "PowerCmd.Apply<InductiveCirclePower>");
        AcceptanceAssert.Equal(
            5,
            applyPower.ArgumentList.Arguments.Count,
            "Inductive Circle must apply its runtime Power with the complete PowerCmd.Apply contract.");
        AcceptanceAssert.Equal(
            "DynamicVars.Heal.BaseValue",
            applyPower.ArgumentList.Arguments[2].Expression.ToString(),
            "Inductive Circle must pass its live Heal dynamic value into InductiveCirclePower.");

        var deathCallback = RequireSourceMethod(
            repository,
            typeof(InductiveCirclePower),
            "OnAnyEnemyDeath");
        var readBaseHealing = RequireSingleInvocation(
            deathCallback,
            "CalculateBaseImmediateDeathHealing");
        AcceptanceAssert.Equal(
            "Owner",
            readBaseHealing.ArgumentList.Arguments.Single().Expression.ToString(),
            "Every enemy death must read the owner's full immediate death-healing base.");

        var calculateAdditional = RequireSingleInvocation(
            deathCallback,
            "CalculateAdditionalHealing");
        AcceptanceAssert.Equal(
            "baseHealing",
            calculateAdditional.ArgumentList.Arguments[0].Expression.ToString(),
            "Inductive Circle must scale the complete immediate death-healing base.");
        AcceptanceAssert.Equal(
            "Amount",
            calculateAdditional.ArgumentList.Arguments[1].Expression.ToString(),
            "Inductive Circle Power Amount must remain the uncapped percentage supplied by the card.");

        var heal = RequireSingleInvocation(deathCallback, "Overheal.HealAsync");
        AcceptanceAssert.True(
            heal.Parent is AwaitExpressionSyntax,
            "Inductive Circle's additional death healing must await the shared Overheal runtime path.");
        AcceptanceAssert.Equal(
            "Owner",
            heal.ArgumentList.Arguments[0].Expression.ToString(),
            "Inductive Circle must heal its owning creature.");
        AcceptanceAssert.Equal(
            "additionalHealing",
            heal.ArgumentList.Arguments[1].Expression.ToString(),
            "Inductive Circle must pass the full rounded-up additional healing to Overheal without clipping it.");
        AcceptanceAssert.True(
            readBaseHealing.SpanStart < calculateAdditional.SpanStart &&
            calculateAdditional.SpanStart < heal.SpanStart,
            "The death callback must read base healing, calculate the percentage bonus, then heal in that order.");

        var baseHealingMethod = RequireSourceMethod(
            repository,
            typeof(InductiveCirclePower),
            "CalculateBaseImmediateDeathHealing");
        var crownHealing = RequireSingleInvocation(
            baseHealingMethod,
            "SolitaryCrown.CalculateHealingForMaxHp");
        AcceptanceAssert.Equal(
            "owner.MaxHp",
            crownHealing.ArgumentList.Arguments.Single().Expression.ToString(),
            "The immediate base must use Solitary Crown's current max-HP healing calculation.");
        var otherImmediateHealing = RequireSingleInvocation(
            baseHealingMethod,
            "owner.GetPower<OptimalAlgorithmPower>");
        AcceptanceAssert.True(
            otherImmediateHealing.Parent?.ToString().Contains(".Amount", StringComparison.Ordinal) == true,
            "The immediate base must read every Optimal Algorithm stack as another death-healing source.");
        var baseReturn = baseHealingMethod.DescendantNodes()
            .OfType<ReturnStatementSyntax>()
            .Single();
        AcceptanceAssert.Equal(
            "checked(crownHealing+optimalAlgorithmHealing)",
            Compact(baseReturn.Expression?.ToString() ?? string.Empty),
            "The immediate base must add Solitary Crown and other immediate death-healing sources without clipping.");

        var powerDeclaration = repository.RequireSourceType(typeof(InductiveCirclePower).FullName!).Declaration;
        AcceptanceAssert.Empty(
            powerDeclaration.Members.OfType<FieldDeclarationSyntax>().ToArray(),
            "Inductive Circle Power must not keep per-trigger, per-turn, or per-combat healing-limit state:");
        var forbiddenLimitCalls = powerDeclaration.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(invocation => invocation.Expression.ToString() is "Math.Min" or "Math.Clamp")
            .Select(invocation => invocation.ToString())
            .ToArray();
        AcceptanceAssert.Empty(
            forbiddenLimitCalls,
            "Inductive Circle's death-healing chain must not Min/Clamp its base, percentage, or result:");
        var amountMutations = deathCallback.DescendantNodes()
            .Where(node =>
                node is AssignmentExpressionSyntax assignment && assignment.Left.ToString() == "Amount" ||
                node is PrefixUnaryExpressionSyntax prefix && prefix.Operand.ToString() == "Amount" ||
                node is PostfixUnaryExpressionSyntax postfix && postfix.Operand.ToString() == "Amount")
            .Select(node => node.ToString())
            .ToArray();
        AcceptanceAssert.Empty(
            amountMutations,
            "Inductive Circle must not consume or reset its percentage after a death, turn, or combat trigger:");
    }

    public static void ColorConservationUpgradeReducesCoughAndKeepsZeroEnergy(RepositorySnapshot _)
    {
        var card = MakeMutableForUpgrade(new ColorConservation());
        AcceptanceAssert.Equal(0, card.EnergyCost.GetWithModifiers(CostModifiers.None), "Color Conservation must cost zero Energy.");
        AcceptanceAssert.Equal(4, card.DynamicVars["LifeCost"].IntValue, "Base Color Conservation must cost 4 Cough.");
        card.UpgradeInternal();
        AcceptanceAssert.Equal(2, card.DynamicVars["LifeCost"].IntValue, "Upgrading Color Conservation must reduce Cough to 2.");
        AcceptanceAssert.Equal(
            0,
            card.EnergyCost.GetWithModifiers(CostModifiers.None),
            "Upgraded Color Conservation must remain a legal zero-Energy card, never a negative-cost sentinel.");
    }

    public static void InfiniteCanvasUpgradeReducesEnergyAndPreservesDrainGrowth(RepositorySnapshot _)
    {
        var card = MakeMutableForUpgrade(new InfiniteCanvas());
        AcceptanceAssert.Equal(3, card.EnergyCost.GetWithModifiers(CostModifiers.None), "Base Infinite Canvas must cost 3 Energy.");
        AcceptanceAssert.Equal(16, card.DynamicVars["LifeCost"].IntValue, "Base Infinite Canvas must cost 16 Cough.");
        AcceptanceAssert.Equal(4, card.DynamicVars["DrainGrowth"].IntValue, "Base Infinite Canvas must grow Drain by 4 percentage points.");
        card.UpgradeInternal();
        AcceptanceAssert.Equal(2, card.EnergyCost.GetWithModifiers(CostModifiers.None), "Upgrading Infinite Canvas must reduce Energy to 2.");
        AcceptanceAssert.True(card.EnergyCost.WasJustUpgraded, "The energy cost upgrade must be highlighted in the native upgrade preview.");
        AcceptanceAssert.Equal(16, card.DynamicVars["LifeCost"].IntValue, "Upgraded Infinite Canvas must still cost 16 Cough.");
        AcceptanceAssert.Equal(4, card.DynamicVars["DrainGrowth"].IntValue, "The cost upgrade must preserve the existing 4-point Drain growth.");
        card.FinalizeUpgradeInternal();
        AcceptanceAssert.Equal(2, card.EnergyCost.GetWithModifiers(CostModifiers.None), "The reduced energy cost must survive upgrade finalization.");
    }

    public static void FinalDrawAndInductiveTextMatchesRuntime(RepositorySnapshot repository)
    {
        var englishCards = ReadLocalization(repository, "eng", "cards.json");
        var chineseCards = ReadLocalization(repository, "zhs", "cards.json");
        var englishPowers = ReadLocalization(repository, "eng", "powers.json");
        var chinesePowers = ReadLocalization(repository, "zhs", "powers.json");

        AssertContainsAll(englishCards["VIVHITE_CARD_ASTRAL_SEARCH.description"], "Astral Search", "{Cards", "discard 2");
        AssertContainsAll(chineseCards["VIVHITE_CARD_ASTRAL_SEARCH.description"], "星图检索", "{Cards", "弃 2");
        AssertContainsAll(englishCards["VIVHITE_CARD_HEURISTIC_SHIELD.description"], "Heuristic Shield", "Draw 2");
        AssertContainsAll(chineseCards["VIVHITE_CARD_HEURISTIC_SHIELD.description"], "启发式护盾", "抽 2");
        AssertContainsAll(englishCards["VIVHITE_CARD_ASTRAL_PURSUIT.description"], "Astral Pursuit", "draw 2");
        AssertContainsAll(chineseCards["VIVHITE_CARD_ASTRAL_PURSUIT.description"], "星算追猎", "抽 2");
        AssertContainsAll(englishCards["VIVHITE_CARD_CHROMATIC_TRANSITION.description"], "Chromatic Transition", "Draw 2");
        AssertContainsAll(chineseCards["VIVHITE_CARD_CHROMATIC_TRANSITION.description"], "色阶过渡", "抽 2");

        AssertContainsAll(
            englishPowers["VIVHITE_POWER_INDUCTIVE_CIRCLE_POWER.smartDescription"],
            "Inductive Circle power",
            "{Amount}", "%", "rounded up");
        AssertContainsAll(
            chinesePowers["VIVHITE_POWER_INDUCTIVE_CIRCLE_POWER.smartDescription"],
            "归纳法阵能力",
            "{Amount}", "%", "向上取整");
    }

    private static void AssertSourceContains(
        RepositorySnapshot repository,
        Type type,
        string expectedCompactSource,
        string message)
    {
        var source = Compact(repository.RequireSourceType(type.FullName!).Declaration.ToFullString());
        AcceptanceAssert.True(source.Contains(expectedCompactSource, StringComparison.Ordinal), message);
    }

    private static bool HasFixedOrStagedCough(CardModel card) =>
        card.DynamicVars.Any(entry =>
            (entry.Key is "LifeCost" or "LifeCostPerPhase") &&
            entry.Value.BaseValue > 0m);

    private static bool HasImmediateCardPlayDrawOrDiscardCall(
        RepositorySnapshot repository,
        Type cardType)
    {
        var playMethods = repository.RequireSourceType(cardType.FullName!)
            .Declaration.Members
            .OfType<MethodDeclarationSyntax>()
            .Where(method => method.Identifier.ValueText == "OnPlayAfterLifePayment")
            .ToArray();
        if (playMethods.Length == 0)
        {
            return false;
        }
        if (playMethods.Length != 1)
        {
            throw new AcceptanceFailureException(
                $"{cardType.FullName} must declare at most one OnPlayAfterLifePayment method; " +
                $"actual {playMethods.Length}.");
        }

        return playMethods[0].DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Any(IsImmediateDrawOrDiscardInvocation);
    }

    private static bool IsImmediateDrawOrDiscardInvocation(InvocationExpressionSyntax invocation)
    {
        var expression = Compact(invocation.Expression.ToString());
        return expression is
            "DrawAsync" or
            "DiscardAsync" or
            "CardPileCmd.Draw" or
            "CardCmd.Discard" or
            "CardSelectCmd.FromHandForDiscard";
    }

    private static MethodDeclarationSyntax RequireSourceMethod(
        RepositorySnapshot repository,
        Type type,
        string methodName)
    {
        var methods = repository.RequireSourceType(type.FullName!)
            .Declaration.Members
            .OfType<MethodDeclarationSyntax>()
            .Where(method => method.Identifier.ValueText == methodName)
            .ToArray();
        if (methods.Length != 1)
        {
            throw new AcceptanceFailureException(
                $"{type.FullName}.{methodName} source must resolve exactly once; actual {methods.Length}.");
        }
        return methods[0];
    }

    private static InvocationExpressionSyntax RequireSingleInvocation(
        MethodDeclarationSyntax method,
        string expression)
    {
        var invocations = method.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(invocation => invocation.Expression.ToString() == expression)
            .ToArray();
        if (invocations.Length != 1)
        {
            throw new AcceptanceFailureException(
                $"{method.Identifier.ValueText} must invoke {expression} exactly once; actual {invocations.Length}.");
        }
        return invocations[0];
    }

    private static string Compact(string source) =>
        new string(source.Where(character => !char.IsWhiteSpace(character)).ToArray());

    private static void InvokeOnUpgrade(string cardId, CardModel card)
    {
        var method = card.GetType().GetMethod(
            "OnUpgrade",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException($"{cardId} has no upgrade hook in its type hierarchy.");
        method.Invoke(card, null);
    }

    private static T MakeMutableForUpgrade<T>(T model)
        where T : AbstractModel
    {
        for (var cursor = model.GetType(); cursor is not null; cursor = cursor.BaseType)
        {
            var mutableField = cursor.GetField(
                "<IsMutable>k__BackingField",
                BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
            if (mutableField is null)
            {
                continue;
            }

            mutableField.SetValue(model, true);
            return model;
        }

        throw new AcceptanceFailureException($"{model.GetType().FullName} has no IsMutable backing field.");
    }

    private static IReadOnlyDictionary<string, string> ReadLocalization(
        RepositorySnapshot repository,
        string locale,
        string fileName)
    {
        var path = Path.Combine(repository.LocalizationDirectory, locale, fileName);
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        return document.RootElement.EnumerateObject().ToDictionary(
            property => property.Name,
            property => property.Value.GetString() ?? string.Empty,
            StringComparer.Ordinal);
    }

    private static void AssertContainsAll(string text, string label, params string[] fragments)
    {
        var missing = fragments
            .Where(fragment => !text.Contains(fragment, StringComparison.OrdinalIgnoreCase))
            .ToArray();
        AcceptanceAssert.Empty(missing, $"{label} localization is missing final mechanics text:");
    }

    private sealed record DrawVarExpectation(
        Type CardType,
        string CardId,
        int BaseCards,
        int UpgradedCards,
        string DrawInvocation);
}
