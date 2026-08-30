using System.Reflection;
using System.Text.Json;
using MegaCrit.Sts2.Core.Models;
using Vivhite.Cards.Chromatic;
using Vivhite.Cards.Recursion;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class FinalBalanceAcceptanceTests
{
    private static readonly DrawVarExpectation[] DynamicDrawCards =
    [
        new("VIVHITE_CARD_RECURRENT_STARLIGHT", 4, 4),
        new("VIVHITE_CARD_ASTRAL_SEARCH", 4, 6),
        new("VIVHITE_CARD_CONVERGENCE_VERDICT", 6, 6),
        new("VIVHITE_CARD_DIVIDE_AND_CONQUER_CIRCLE", 4, 6),
        new("VIVHITE_CARD_PREFETCH_FUTURE", 6, 6),
        new("VIVHITE_CARD_GOLDEN_RATIO", 2, 2),
        new("VIVHITE_CARD_CHROMATIC_SEQUENCE", 4, 6)
    ];

    public static void EveryCoughDrawAndDiscardEffectUsesTheFinalDoubledAmount(
        RepositorySnapshot repository)
    {
        var cards = repository.VivhitePoolCards.ToDictionary(
            repository.CardId,
            type => MakeMutableForUpgrade((CardModel)(Activator.CreateInstance(type)
                ?? throw new AcceptanceFailureException($"Could not construct {type.FullName}."))),
            StringComparer.Ordinal);

        foreach (var expectation in DynamicDrawCards)
        {
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
        }

        AssertSourceContains(
            repository,
            typeof(HeuristicShield),
            "DrawAsync(choiceContext,2)",
            "Heuristic Shield must draw two cards.");
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
            source.Contains("OriginStarChart.CalculateHealingForMaxHp(owner.MaxHp)", StringComparison.Ordinal) &&
            source.Contains("OptimalAlgorithmPower.HealingPerStack", StringComparison.Ordinal),
            "Inductive Circle's percentage base must include both Solitary Crown and Optimal Algorithm immediate healing.");
    }

    public static void ColorConservationCostsZeroBeforeAndAfterUpgrade(RepositorySnapshot _)
    {
        var card = new ColorConservation();
        AcceptanceAssert.Equal(0, card.EnergyCost.Canonical, "Color Conservation must cost zero Energy.");
        InvokeOnUpgrade("VIVHITE_CARD_COLOR_CONSERVATION", card);
        AcceptanceAssert.Equal(
            0,
            card.EnergyCost.Canonical,
            "Upgraded Color Conservation must remain a legal zero-Energy card, never a negative-cost sentinel.");
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
        string CardId,
        int BaseCards,
        int UpgradedCards);
}
