using System.Reflection;
using MegaCrit.Sts2.Core.Models;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class CardCatalogAcceptanceTests
{
    private static readonly IReadOnlyDictionary<string, int> ApprovedRarityDistribution =
        new Dictionary<string, int>(StringComparer.Ordinal)
        {
            ["Basic"] = 3,
            ["Common"] = 18,
            ["Uncommon"] = 24,
            ["Rare"] = 16
        };

    public static void ProductionSourceCompilesAndReflects(RepositorySnapshot repository)
    {
        AcceptanceAssert.True(
            repository.CompiledAssembly.Location.StartsWith(
                Path.Combine(repository.RootDirectory, "Vivhite.Tests"),
                StringComparison.OrdinalIgnoreCase),
            $"Production source must be linked into the non-deploying acceptance assembly; actual: {repository.CompiledAssembly.Location}");

        var missingRuntimeTypes = repository.SourceTypes
            .Where(source => repository.CompiledAssembly.GetType(source.FullName, throwOnError: false) is null)
            .Select(source => $"{source.FullName} ({source.RelativePath(repository.RootDirectory)})")
            .ToArray();
        AcceptanceAssert.Empty(
            missingRuntimeTypes,
            "Every top-level production class parsed by the source contracts must exist in the compiled acceptance assembly:");
    }

    public static void HasApprovedStableIds(RepositorySnapshot repository)
    {
        var ids = repository.VivhitePoolCards.Select(repository.CardId).Order(StringComparer.Ordinal).ToArray();
        var expectedIds = ApprovedCardCatalog.RarityById.Keys.Order(StringComparer.Ordinal).ToArray();

        AcceptanceAssert.Equal(61, expectedIds.Length, "The independent approved catalog must enumerate exactly 61 IDs.");
        AcceptanceAssert.Equal(ids.Length, ids.Distinct(StringComparer.Ordinal).Count(), "Reflected registered card IDs must be unique.");
        AcceptanceAssert.SetEqual(
            expectedIds,
            ids,
            "Compiled [RegisterCard(typeof(VivhiteCardPool))] metadata must exactly match the approved 61 IDs.");
    }

    public static void HasApprovedRarityDistribution(RepositorySnapshot repository)
    {
        var actualById = new Dictionary<string, string>(StringComparer.Ordinal);
        var constructionFailures = new List<string>();
        foreach (var cardType in repository.VivhitePoolCards)
        {
            try
            {
                var card = Activator.CreateInstance(cardType) as CardModel;
                if (card is null)
                {
                    constructionFailures.Add($"{cardType.FullName}: did not construct a CardModel");
                    continue;
                }
                actualById.Add(repository.CardId(cardType), card.Rarity.ToString());
            }
            catch (Exception exception)
            {
                constructionFailures.Add($"{cardType.FullName}: {exception.GetBaseException().Message}");
            }
        }
        AcceptanceAssert.Empty(
            constructionFailures,
            "Card rarity acceptance reflects and constructs the compiled production card types:");

        var misplaced = ApprovedCardCatalog.RarityById
            .Where(expected => !actualById.TryGetValue(expected.Key, out var actual) || actual != expected.Value)
            .Select(expected =>
                $"{expected.Key}: expected {expected.Value}, actual " +
                (actualById.GetValueOrDefault(expected.Key) ?? "<missing>"))
            .ToArray();
        AcceptanceAssert.Empty(misplaced, "Every approved ID must retain its exact rarity:");

        var actualDistribution = actualById.Values
            .GroupBy(rarity => rarity, StringComparer.Ordinal)
            .ToDictionary(group => group.Key, group => group.Count(), StringComparer.Ordinal);
        var distributionErrors = ApprovedRarityDistribution
            .Where(expected => actualDistribution.GetValueOrDefault(expected.Key) != expected.Value)
            .Select(expected =>
                $"{expected.Key}: expected {expected.Value}, actual {actualDistribution.GetValueOrDefault(expected.Key)}")
            .ToArray();
        AcceptanceAssert.Empty(distributionErrors, "Rarity totals must be Basic/Common/Uncommon/Rare = 3/18/24/16:");
    }

    public static void HasApprovedStarterDeckAndNoLegacyCardTypes(RepositorySnapshot repository)
    {
        var expected = new Dictionary<string, int>(StringComparer.Ordinal)
        {
            ["VIVHITE_CARD_LUMINOUS_PROJECTION"] = 4,
            ["VIVHITE_CARD_CLOSED_DOMAIN_MAPPING"] = 4,
            ["VIVHITE_CARD_VIVHITE_TRANSFORMATION"] = 1
        };
        var actual = new Dictionary<string, int>(StringComparer.Ordinal);
        var malformed = new List<string>();
        foreach (var cardType in repository.CompiledProductionTypes)
        {
            var starterAttributes = cardType.GetCustomAttributesData()
                .Where(attribute =>
                    attribute.AttributeType.Name == "RegisterCharacterStarterCardAttribute" &&
                    RepositorySnapshot.AttributeContainsType(attribute, "Vivhite.Characters.VivhiteCharacter"))
                .ToArray();
            foreach (var attribute in starterAttributes)
            {
                var counts = attribute.ConstructorArguments
                    .Where(argument => argument.ArgumentType == typeof(int) && argument.Value is int)
                    .Select(argument => (int)argument.Value!)
                    .Concat(attribute.NamedArguments
                        .Where(argument => argument.TypedValue.ArgumentType == typeof(int) && argument.TypedValue.Value is int)
                        .Select(argument => (int)argument.TypedValue.Value!))
                    .ToArray();
                if (counts.Length != 1)
                {
                    malformed.Add($"{cardType.FullName}: starter registration must expose exactly one copy count");
                    continue;
                }
                actual[repository.CardId(cardType)] = actual.GetValueOrDefault(repository.CardId(cardType)) + counts[0];
            }
        }

        AcceptanceAssert.Empty(malformed, "Starter registration metadata is malformed:");
        AcceptanceAssert.SetEqual(expected.Keys.ToArray(), actual.Keys.ToArray(), "Vivhite starter card IDs must be exactly 4 + 4 + 1.");
        var wrongCounts = expected
            .Where(item => actual.GetValueOrDefault(item.Key) != item.Value)
            .Select(item => $"{item.Key}: expected {item.Value}, actual {actual.GetValueOrDefault(item.Key)}")
            .ToArray();
        AcceptanceAssert.Empty(wrongCounts, "Vivhite starter card copy counts must be exactly 4 + 4 + 1:");
        AcceptanceAssert.Equal(9, actual.Values.Sum(), "Vivhite must start with exactly nine cards.");

        var legacyTypes = new[] { "Vivhite.Cards.VivhiteStrike", "Vivhite.Cards.VivhiteDefend" }
            .Where(fullName => repository.CompiledAssembly.GetType(fullName, throwOnError: false) is not null)
            .ToArray();
        AcceptanceAssert.Empty(legacyTypes, "Legacy placeholder card classes must be removed from the compiled assembly:");
    }
}
