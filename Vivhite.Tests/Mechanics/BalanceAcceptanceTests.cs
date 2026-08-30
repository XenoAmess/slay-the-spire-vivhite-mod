using System.Reflection;
using MegaCrit.Sts2.Core.Models;
using Vivhite.Core;
using Vivhite.Powers;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class BalanceAcceptanceTests
{
    private static readonly IReadOnlyDictionary<string, int> DoubledFixedLifeCosts =
        new Dictionary<string, int>(StringComparer.Ordinal)
        {
            ["VIVHITE_CARD_LUMINOUS_PROJECTION"] = 2,
            ["VIVHITE_CARD_CLOSED_DOMAIN_MAPPING"] = 2,
            ["VIVHITE_CARD_VIVHITE_TRANSFORMATION"] = 4,

            ["VIVHITE_CARD_CLOSED_PROJECTION"] = 4,
            ["VIVHITE_CARD_TANGENT_STARLIGHT"] = 2,
            ["VIVHITE_CARD_OPEN_SET_SHELTER"] = 4,
            ["VIVHITE_CARD_LOCAL_HOMEOMORPHISM"] = 2,
            ["VIVHITE_CARD_SCALE_TRANSFORMATION"] = 6,
            ["VIVHITE_CARD_ISOPERIMETRIC_WARD"] = 4,
            ["VIVHITE_CARD_TOPOLOGICAL_GROWTH"] = 8,
            ["VIVHITE_CARD_LAW_OF_CONSERVATION"] = 6,
            ["VIVHITE_CARD_LIFE_MANIFOLD"] = 8,
            ["VIVHITE_CARD_MOBIUS_LOOP"] = 4,
            ["VIVHITE_CARD_INVARIANT"] = 2,
            ["VIVHITE_CARD_GEODESIC_VEIL"] = 6,
            ["VIVHITE_CARD_CLOSED_MANIFOLD"] = 10,
            ["VIVHITE_CARD_AXIOM_OF_LIFE"] = 10,
            ["VIVHITE_CARD_INFINITE_EXTENSION"] = 12,
            ["VIVHITE_CARD_CONSERVATION_FIRMAMENT"] = 10,

            ["VIVHITE_CARD_RECURRENT_STARLIGHT"] = 4,
            ["VIVHITE_CARD_TERMINATION_CONDITION"] = 4,
            ["VIVHITE_CARD_PARALLEL_STARFALL"] = 6,
            ["VIVHITE_CARD_ASTRAL_SEARCH"] = 2,
            ["VIVHITE_CARD_HEURISTIC_SHIELD"] = 2,
            ["VIVHITE_CARD_SUCCESSOR_FORMULA"] = 4,
            ["VIVHITE_CARD_BACKTRACKING_SPELL"] = 6,
            ["VIVHITE_CARD_CONVERGENCE_VERDICT"] = 8,
            ["VIVHITE_CARD_DIVIDE_AND_CONQUER_CIRCLE"] = 4,
            ["VIVHITE_CARD_ASTRAL_PURSUIT"] = 6,
            ["VIVHITE_CARD_PREFETCH_FUTURE"] = 4,
            ["VIVHITE_CARD_INDUCTIVE_CIRCLE"] = 8,
            ["VIVHITE_CARD_EVENT_LOOP"] = 6,
            ["VIVHITE_CARD_PROOF_OF_TERMINATION"] = 10,
            ["VIVHITE_CARD_DYNAMIC_PROGRAMMING"] = 10,
            ["VIVHITE_CARD_INFINITE_STAR_SEQUENCE"] = 8,
            ["VIVHITE_CARD_OPTIMAL_ALGORITHM"] = 14,

            ["VIVHITE_CARD_CRIMSON_AREA"] = 4,
            ["VIVHITE_CARD_TRICHROMATIC_WALTZ"] = 6,
            ["VIVHITE_CARD_COMPOSITE_COLOR_WHEEL"] = 6,
            ["VIVHITE_CARD_DIFFERENTIAL_SAMPLING"] = 2,
            ["VIVHITE_CARD_CHIAROSCURO"] = 4,
            ["VIVHITE_CARD_NEGATIVE_SPACE"] = 4,
            ["VIVHITE_CARD_SPECTRAL_INTEGRAL"] = 6,
            ["VIVHITE_CARD_GOLDEN_COMPOSITION"] = 8,
            ["VIVHITE_CARD_RIEMANN_STAR_ARRAY"] = 6,
            ["VIVHITE_CARD_CHROMATIC_TRANSITION"] = 4,
            ["VIVHITE_CARD_COLOR_CONSERVATION"] = 8,
            ["VIVHITE_CARD_COMPOSITE_COLOR_FIELD"] = 8,
            ["VIVHITE_CARD_COMPLEMENTARY_AFTERIMAGE"] = 6,
            ["VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL"] = 12,
            ["VIVHITE_CARD_CRIMSON_CONSERVATION_LAW"] = 10,
            ["VIVHITE_CARD_INFINITE_CANVAS"] = 16,
            ["VIVHITE_CARD_PERFECT_SYNTHESIS"] = 16,

            ["VIVHITE_CARD_GOLDEN_RATIO"] = 4,
            ["VIVHITE_CARD_CHROMATIC_SEQUENCE"] = 4,
            ["VIVHITE_CARD_UNIFIED_FIELD_THEORY"] = 14,
            ["VIVHITE_CARD_CONSERVED_RECURRENCE"] = 10,
            ["VIVHITE_CARD_CHROMATIC_LIMIT"] = 8
        };

    private static readonly string[] CardsWithoutFixedLifeCost =
    [
        "VIVHITE_CARD_AXIOM_RING",
        "VIVHITE_CARD_ASTRAL_MEASURE",
        "VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL"
    ];

    private static readonly DrainVarExpectation[] DoubledDrainVars =
    [
        new("VIVHITE_CARD_CRIMSON_AREA", "Drain", 16, 20),
        new("VIVHITE_CARD_TRICHROMATIC_WALTZ", "Drain", 12, 16),
        new("VIVHITE_CARD_COMPOSITE_COLOR_WHEEL", "Drain", 20, 24),
        new("VIVHITE_CARD_DIFFERENTIAL_SAMPLING", "Drain", 8, 12),
        new("VIVHITE_CARD_CHIAROSCURO", "Drain", 20, 28),
        new("VIVHITE_CARD_SPECTRAL_INTEGRAL", "Drain", 8, 12),
        new("VIVHITE_CARD_GOLDEN_COMPOSITION", "Drain", 20, 24),
        new("VIVHITE_CARD_RIEMANN_STAR_ARRAY", "Drain", 12, 16),
        new("VIVHITE_CARD_CHROMATIC_TRANSITION", "Drain", 8, 12),
        new("VIVHITE_CARD_COMPOSITE_COLOR_FIELD", "Drain", 8, 12),
        new("VIVHITE_CARD_COMPLEMENTARY_AFTERIMAGE", "Drain", 16, 20),
        new("VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL", "Drain", 48, 60),
        new("VIVHITE_CARD_INFINITE_CANVAS", "DrainGrowth", 4, 4),
        new("VIVHITE_CARD_PERFECT_SYNTHESIS", "Drain", 32, 40),
        new("VIVHITE_CARD_GOLDEN_RATIO", "Drain", 12, 16),
        new("VIVHITE_CARD_ASTRAL_MEASURE", "DrainPerMargin", 4, 8),
        new("VIVHITE_CARD_CHROMATIC_SEQUENCE", "DrainPerSkill", 4, 4),
        new("VIVHITE_CARD_UNIFIED_FIELD_THEORY", "DrainPerMargin", 4, 4),
        new("VIVHITE_CARD_CHROMATIC_LIMIT", "DrainPerX", 12, 16)
    ];

    public static void AllFixedLifeCostsMatchTheDoubledTable(RepositorySnapshot repository)
    {
        var cards = ConstructAllCards(repository);
        AcceptanceAssert.Equal(58, DoubledFixedLifeCosts.Count, "The independent doubled LifeCost table must contain exactly 58 cards.");

        var actualFixedCards = cards
            .Where(entry =>
                entry.Value.DynamicVars.TryGetValue("LifeCost", out var lifeCost) &&
                lifeCost.BaseValue != 0m)
            .Select(entry => entry.Key)
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.SetEqual(
            DoubledFixedLifeCosts.Keys.ToArray(),
            actualFixedCards,
            "Exactly the approved 58 cards must expose a nonzero fixed LifeCost DynamicVar.");

        var actualWithoutFixedCost = cards.Keys
            .Except(actualFixedCards, StringComparer.Ordinal)
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.SetEqual(
            CardsWithoutFixedLifeCost,
            actualWithoutFixedCost,
            "Only Axiom Ring, Astral Measure, and the Crimson ritual may have zero or no fixed LifeCost.");

        foreach (var (cardId, expectedBase) in DoubledFixedLifeCosts)
        {
            var card = cards[cardId];
            AssertDynamicVar(cardId, card, "LifeCost", expectedBase, "base");

            InvokeOnUpgrade(cardId, card);
            var expectedUpgraded = cardId == "VIVHITE_CARD_BACKTRACKING_SPELL" ? 2 : expectedBase;
            AssertDynamicVar(cardId, card, "LifeCost", expectedUpgraded, "upgraded");
        }

        foreach (var cardId in CardsWithoutFixedLifeCost)
        {
            var card = cards[cardId];
            InvokeOnUpgrade(cardId, card);
            AcceptanceAssert.True(
                !card.DynamicVars.TryGetValue("LifeCost", out var upgradedLifeCost) ||
                upgradedLifeCost.BaseValue == 0m,
                $"{cardId} must still have zero or no fixed LifeCost after upgrade.");
        }
    }

    public static void AllDrainDynamicVarsMatchTheDoubledCurrentTable(RepositorySnapshot repository)
    {
        var cards = ConstructAllCards(repository);
        AcceptanceAssert.Equal(19, DoubledDrainVars.Length, "The independent doubled Drain table must contain exactly 19 DynamicVars.");

        var expectedKeys = DoubledDrainVars
            .Select(expectation => $"{expectation.CardId}.{expectation.VarName}")
            .ToArray();
        var actualKeys = cards
            .SelectMany(entry => entry.Value.DynamicVars.Keys
                .Where(name => name.Contains("Drain", StringComparison.Ordinal))
                .Select(name => $"{entry.Key}.{name}"))
            .ToArray();
        AcceptanceAssert.SetEqual(
            expectedKeys,
            actualKeys,
            "Every card-provided Drain DynamicVar must be represented exactly once in the doubled-current-value table.");

        foreach (var expectation in DoubledDrainVars)
        {
            var card = cards[expectation.CardId];
            AssertDynamicVar(
                expectation.CardId,
                card,
                expectation.VarName,
                expectation.BaseValue,
                "base");
            InvokeOnUpgrade(expectation.CardId, card);
            AssertDynamicVar(
                expectation.CardId,
                card,
                expectation.VarName,
                expectation.UpgradedValue,
                "upgraded");
        }
    }

    public static void AllDrainDynamicVarsRemainIntegralAcrossUpgrade(RepositorySnapshot repository)
    {
        var cards = ConstructAllCards(repository);
        foreach (var expectation in DoubledDrainVars)
        {
            var card = cards[expectation.CardId];
            AssertIntegral(
                card.DynamicVars[expectation.VarName].BaseValue,
                $"{expectation.CardId}.{expectation.VarName} base");
            InvokeOnUpgrade(expectation.CardId, card);
            AssertIntegral(
                card.DynamicVars[expectation.VarName].BaseValue,
                $"{expectation.CardId}.{expectation.VarName} upgraded");
        }
    }

    public static void DelayedDrainPowersUseTheDoubledCardValues(RepositorySnapshot _)
    {
        AcceptanceAssert.Equal(
            4,
            Cards.Chromatic.ChromaticDrainMechanics.InfiniteCanvasDrainGrowthPerStack,
            "Each Infinite Canvas stack must add four percentage points after a Drain-healing Attack.");
        AcceptanceAssert.Equal(
            4,
            Cards.Hybrid.UnifiedFieldTheoryMechanics.DrainPercentPerMarginPerStack,
            "Each Unified Field Theory stack must add four percentage points per Margin spent.");
    }

    public static void GlobalDrainPowersUseNativeIntegerAmount(RepositorySnapshot repository)
    {
        var amountProperty = typeof(PowerModel).GetProperty(
            "Amount",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("PowerModel.Amount is unavailable.");
        AcceptanceAssert.Equal(
            typeof(int),
            amountProperty.PropertyType,
            "The engine-native PowerModel.Amount storage must remain an integer.");

        foreach (var getterName in new[]
                 {
                     nameof(InfiniteDrain.GetGlobalPercent),
                     nameof(InfiniteDrain.GetThisTurnPercent)
                 })
        {
            var getter = typeof(InfiniteDrain).GetMethod(
                getterName,
                BindingFlags.Static | BindingFlags.Public)
                ?? throw new AcceptanceFailureException($"InfiniteDrain.{getterName} is unavailable.");
            AcceptanceAssert.Equal(
                typeof(int),
                getter.ReturnType,
                $"InfiniteDrain.{getterName} must return the native integer Power amount.");
            AcceptanceAssert.True(
                IlInspection.CalledMethods(getter).OfType<MethodInfo>().Any(method =>
                    method.Name == "GetAmount" && method.ReturnType == typeof(int)),
                $"InfiniteDrain.{getterName} must read the integer PowerStackResource amount directly.");
        }

        foreach (var gainName in new[]
                 {
                     nameof(InfiniteDrain.GainGlobalPercentAsync),
                     nameof(InfiniteDrain.GainThisTurnPercentAsync)
                 })
        {
            var gain = typeof(InfiniteDrain).GetMethods(BindingFlags.Static | BindingFlags.Public)
                .Single(method => method.Name == gainName);
            var amountParameter = gain.GetParameters().Single(parameter => parameter.Name == "amount");
            AcceptanceAssert.Equal(
                typeof(int),
                amountParameter.ParameterType,
                $"InfiniteDrain.{gainName} must accept integer percentage points.");
        }

        var drainPowerTypes = new[]
        {
            typeof(InfiniteDrainPower),
            typeof(InfiniteDrainThisTurnPower)
        };
        foreach (var powerType in drainPowerTypes)
        {
            var customInstanceStorage = powerType
                .GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
                .Select(field => $"{powerType.FullName}.{field.Name}: {field.FieldType.FullName}")
                .Concat(powerType
                    .GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
                    .Select(property => $"{powerType.FullName}.{property.Name}: {property.PropertyType.FullName}"))
                .ToArray();
            AcceptanceAssert.Empty(
                customInstanceStorage,
                $"{powerType.Name} must use inherited PowerModel.Amount rather than custom fixed-point storage:");
        }

        var forbiddenMembers = new[]
            {
                typeof(InfiniteDrain),
                typeof(InfiniteDrainPower),
                typeof(InfiniteDrainThisTurnPower)
            }
            .SelectMany(type => type.GetMembers(
                BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public |
                BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
            .Where(member =>
                member.Name.Contains("FixedPoint", StringComparison.OrdinalIgnoreCase) ||
                member.Name.Contains("DrainPercent", StringComparison.OrdinalIgnoreCase))
            .Select(member => $"{member.DeclaringType?.FullName}.{member.Name}")
            .ToArray();
        AcceptanceAssert.Empty(
            forbiddenMembers,
            "Global Drain must not expose fixed-point or parallel DrainPercent storage members:");

        AcceptanceAssert.True(
            repository.RegisteredPowers.Contains(typeof(InfiniteDrainPower)) &&
            repository.RegisteredPowers.Contains(typeof(InfiniteDrainThisTurnPower)),
            "Both integer-backed global Drain powers must remain registered.");
    }

    private static IReadOnlyDictionary<string, CardModel> ConstructAllCards(RepositorySnapshot repository)
    {
        var cards = new Dictionary<string, CardModel>(StringComparer.Ordinal);
        var failures = new List<string>();
        foreach (var cardType in repository.VivhitePoolCards)
        {
            var cardId = repository.CardId(cardType);
            try
            {
                var canonical = Activator.CreateInstance(cardType) as CardModel
                    ?? throw new InvalidOperationException("constructor did not produce a CardModel");
                var card = MakeMutableForUpgrade(canonical);
                cards.Add(cardId, card);
            }
            catch (Exception exception)
            {
                failures.Add($"{cardId}: {exception.GetBaseException().Message}");
            }
        }

        AcceptanceAssert.Empty(failures, "The balance acceptance must construct all registered cards:");
        AcceptanceAssert.Equal(61, cards.Count, "The balance acceptance must construct exactly 61 registered cards.");
        return cards;
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

    private static void AssertDynamicVar(
        string cardId,
        CardModel card,
        string varName,
        int expected,
        string state)
    {
        AcceptanceAssert.True(
            card.DynamicVars.TryGetValue(varName, out _),
            $"{cardId} is missing the required {varName} DynamicVar in its {state} state.");
        var actual = card.DynamicVars[varName].BaseValue;
        AcceptanceAssert.Equal(
            (decimal)expected,
            actual,
            $"{cardId}.{varName} has the wrong {state} value.");
        AssertIntegral(actual, $"{cardId}.{varName} {state}");
    }

    private static void AssertIntegral(decimal value, string contract)
    {
        AcceptanceAssert.Equal(
            decimal.Truncate(value),
            value,
            $"{contract} must remain an integer DynamicVar value.");
    }

    private static void InvokeOnUpgrade(string cardId, CardModel card)
    {
        var onUpgrade = card.GetType().GetMethod(
            "OnUpgrade",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException($"{cardId} has no upgrade hook in its type hierarchy.");
        try
        {
            onUpgrade.Invoke(card, null);
        }
        catch (TargetInvocationException exception)
        {
            throw new AcceptanceFailureException(
                $"{cardId}.OnUpgrade failed: {exception.GetBaseException().Message}");
        }
    }

    private sealed record DrainVarExpectation(
        string CardId,
        string VarName,
        int BaseValue,
        int UpgradedValue);
}
