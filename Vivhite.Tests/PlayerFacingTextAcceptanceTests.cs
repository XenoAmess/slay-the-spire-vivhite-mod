using System.Text.Json;
using System.Text.RegularExpressions;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class PlayerFacingTextAcceptanceTests
{
    private static readonly string[] CharacterSuffixes =
    [
        "aromaPrinciple",
        "banter.alive.endTurnPing",
        "banter.dead.endTurnPing",
        "cardsModifierDescription",
        "cardsModifierTitle",
        "defeatMessage",
        "description",
        "eventDeathPrevention",
        "flavor",
        "goldMonologue",
        "possessiveAdjective",
        "pronounObject",
        "pronounPossessive",
        "pronounSubject",
        "selectMessage",
        "title",
        "titleObject",
        "unlockText",
        "victoryMessage"
    ];

    private static readonly string[] EnergyCardIds =
    [
        "VIVHITE_CARD_SUCCESSOR_FORMULA",
        "VIVHITE_CARD_CONVERGENCE_VERDICT",
        "VIVHITE_CARD_PROOF_OF_TERMINATION",
        "VIVHITE_CARD_OPTIMAL_ALGORITHM"
    ];

    private static readonly string[] BaseAncientIds =
    [
        "DARV",
        "NEOW",
        "NONUPEIPE",
        "OROBAS",
        "PAEL",
        "TANX",
        "TEZCATARA",
        "THE_ARCHITECT",
        "VAKUU"
    ];

    public static void RegisteredRuntimeModelsNeverExposeRawLocalizationKeys(RepositorySnapshot repository)
    {
        AcceptanceAssert.Equal(1, repository.RegisteredRelics.Count, "The localization audit expects exactly one registered Vivhite relic.");
        AcceptanceAssert.Equal(1, repository.RegisteredCharacters.Count, "The localization audit expects exactly one registered Vivhite character.");

        foreach (var locale in new[] { "eng", "zhs" })
        {
            var entries = ReadLocale(repository, locale);
            var required = new List<string>();
            required.AddRange(repository.RegisteredCards.SelectMany(type =>
                new[] { "title", "description", "smartDescription" }.Select(suffix => $"{repository.CardId(type)}.{suffix}")));
            required.AddRange(repository.RegisteredPowers.SelectMany(type =>
                new[] { "title", "description", "smartDescription" }.Select(suffix => $"{repository.PowerId(type)}.{suffix}")));
            required.AddRange(repository.RegisteredRelics.SelectMany(type =>
                new[] { "title", "description", "flavor" }.Select(suffix => $"{repository.RelicId(type)}.{suffix}")));
            required.AddRange(repository.RegisteredCharacters.SelectMany(type =>
                CharacterSuffixes.Select(suffix => $"{repository.CharacterId(type)}.{suffix}")));

            var failures = required
                .Distinct(StringComparer.Ordinal)
                .Order(StringComparer.Ordinal)
                .Where(key => !entries.TryGetValue(key, out var value) ||
                    string.IsNullOrWhiteSpace(value) ||
                    string.Equals(key, value, StringComparison.Ordinal) ||
                    LooksLikeRawRuntimeKey(value))
                .ToArray();
            AcceptanceAssert.Empty(
                failures,
                $"Locale '{locale}' must resolve every registered Card/Power/Relic/Character runtime key to player-facing text:");

            var selfEchoes = entries
                .Where(entry => string.Equals(entry.Key, entry.Value, StringComparison.Ordinal))
                .Select(entry => entry.Key)
                .Order(StringComparer.Ordinal)
                .ToArray();
            AcceptanceAssert.Empty(selfEchoes, $"Locale '{locale}' must not store a localization key as its displayed value:");
        }
    }

    public static void ChineseTermsAndEnergyRichTextMatchThePlayerContract(RepositorySnapshot repository)
    {
        var english = ReadLocale(repository, "eng");
        var staleEnglishTerms = english
            .Where(entry => entry.Value.Contains("Life Calculation", StringComparison.OrdinalIgnoreCase))
            .Select(entry => $"{entry.Key}: {entry.Value}")
            .ToArray();
        AcceptanceAssert.Empty(
            staleEnglishTerms,
            "English player-facing text must use Cough instead of the retired term Life Calculation:");
        AcceptanceAssert.Equal(
            "Cough",
            english["VIVHITE_KEYWORD_LIFE_CALCULATION.title"],
            "The English Life Calculation mechanic must be displayed as Cough.");
        AcceptanceAssert.Equal(
            "Margin",
            english["VIVHITE_KEYWORD_MARGIN.title"],
            "The English Margin keyword title must remain Margin.");
        AcceptanceAssert.True(
            english["VIVHITE_KEYWORD_MARGIN.description"].Contains("Cough", StringComparison.Ordinal),
            "The English Margin description must refer to Cough by its current player-facing name.");

        var chinese = ReadLocale(repository, "zhs");
        var staleTerms = chinese
            .Where(entry => entry.Value.Contains("生命演算", StringComparison.Ordinal) ||
                entry.Value.Contains("咳血", StringComparison.Ordinal) ||
                entry.Value.Contains("余量", StringComparison.Ordinal))
            .Select(entry => $"{entry.Key}: {entry.Value}")
            .ToArray();
        AcceptanceAssert.Empty(staleTerms, "Simplified Chinese player-facing text must use 謦欬 and 余裕 exclusively:");
        AcceptanceAssert.Equal("謦欬", chinese["VIVHITE_KEYWORD_LIFE_CALCULATION.title"], "The Chinese Life Calculation keyword title must be 謦欬.");
        AcceptanceAssert.Equal("余裕", chinese["VIVHITE_KEYWORD_MARGIN.title"], "The Chinese Margin keyword title must be 余裕.");

        var englishCards = ReadObject(repository, "eng", "cards.json");
        var chineseCards = ReadObject(repository, "zhs", "cards.json");
        foreach (var entries in new[] { englishCards, chineseCards })
        {
            var leakedPaths = entries
                .Where(entry => entry.Key.StartsWith("VIVHITE_CARD_", StringComparison.Ordinal) &&
                    (entry.Value.Contains("energyIcons(", StringComparison.Ordinal) ||
                     entry.Value.Contains("res://", StringComparison.OrdinalIgnoreCase)))
                .Select(entry => entry.Key)
                .ToArray();
            AcceptanceAssert.Empty(
                leakedPaths,
                "Vivhite card text must not serialize a rich-text energy icon into a resource path for /data or /state:");
        }

        foreach (var cardId in EnergyCardIds)
        {
            foreach (var suffix in new[] { "description", "smartDescription" })
            {
                AssertReadableEnergyRichText(englishCards[$"{cardId}.{suffix}"], "[gold]1 Energy[/gold]", $"eng {cardId}.{suffix}");
                AssertReadableEnergyRichText(chineseCards[$"{cardId}.{suffix}"], "[gold]1 点能量[/gold]", $"zhs {cardId}.{suffix}");
            }
        }
    }

    public static void BaseAncientPagesNeverExposeMissingKeyPlaceholders(RepositorySnapshot repository)
    {
        var expectedKeys = BaseAncientIds
            .SelectMany(id => new[]
            {
                $"{id}.pages.INITIAL.description",
                $"{id}.pages.DONE.description"
            })
            .Order(StringComparer.Ordinal)
            .ToArray();

        foreach (var locale in new[] { "eng", "zhs" })
        {
            var entries = ReadObject(repository, locale, "ancients.json");
            var missing = expectedKeys
                .Where(key => !entries.ContainsKey(key))
                .ToArray();
            AcceptanceAssert.Empty(
                missing,
                $"Locale '{locale}' must explicitly register optional base-Ancient page descriptions so absent text renders blank instead of a raw key:");

            var rawKeyValues = expectedKeys
                .Where(key => string.Equals(entries[key], key, StringComparison.Ordinal) ||
                    LooksLikeRawRuntimeKey(entries[key]))
                .ToArray();
            AcceptanceAssert.Empty(
                rawKeyValues,
                $"Locale '{locale}' base-Ancient page descriptions must never resolve to raw localization keys:");
        }
    }

    public static void NativeCardKeywordsAreNotDuplicatedInLocalizedBodies(RepositorySnapshot repository)
    {
        var standaloneNativeKeyword = new Regex(
            @"(?:^|\n)\[gold\](?:Exhaust|Retain|消耗|保留)\[/gold\][。.]*$",
            RegexOptions.CultureInvariant);
        foreach (var locale in new[] { "eng", "zhs" })
        {
            var entries = ReadObject(repository, locale, "cards.json");
            var duplicated = entries
                .Where(entry => entry.Key.StartsWith("VIVHITE_CARD_", StringComparison.Ordinal) &&
                    (entry.Key.EndsWith(".description", StringComparison.Ordinal) ||
                     entry.Key.EndsWith(".smartDescription", StringComparison.Ordinal)) &&
                    standaloneNativeKeyword.IsMatch(entry.Value))
                .Select(entry => entry.Key)
                .ToArray();
            AcceptanceAssert.Empty(
                duplicated,
                $"Locale '{locale}' card bodies must not repeat Exhaust/Retain; the engine appends canonical native keywords once:");
        }
    }

    private static void AssertReadableEnergyRichText(string text, string expected, string contract)
    {
        AcceptanceAssert.True(text.Contains(expected, StringComparison.Ordinal), $"{contract} must contain readable Energy text: {text}");
        AcceptanceAssert.Equal(
            Regex.Matches(text, Regex.Escape("[gold]"), RegexOptions.CultureInvariant).Count,
            Regex.Matches(text, Regex.Escape("[/gold]"), RegexOptions.CultureInvariant).Count,
            $"{contract} must contain balanced gold rich-text tags.");
    }

    private static bool LooksLikeRawRuntimeKey(string value) =>
        Regex.IsMatch(
            value,
            @"^VIVHITE_(?:CARD|POWER|RELIC|CHARACTER|KEYWORD)_[A-Z0-9_]+\.[A-Za-z][A-Za-z0-9.]*$",
            RegexOptions.CultureInvariant);

    private static IReadOnlyDictionary<string, string> ReadLocale(RepositorySnapshot repository, string locale)
    {
        var directory = Path.Combine(repository.LocalizationDirectory, locale);
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        var duplicates = new List<string>();
        foreach (var path in Directory.GetFiles(directory, "*.json", SearchOption.AllDirectories).Order(StringComparer.Ordinal))
        {
            foreach (var entry in ReadObject(path))
            {
                if (!result.TryAdd(entry.Key, entry.Value))
                {
                    duplicates.Add($"{entry.Key} ({path})");
                }
            }
        }
        AcceptanceAssert.Empty(duplicates, $"Locale '{locale}' contains duplicate localization keys:");
        return result;
    }

    private static IReadOnlyDictionary<string, string> ReadObject(
        RepositorySnapshot repository,
        string locale,
        string fileName) =>
        ReadObject(Path.Combine(repository.LocalizationDirectory, locale, fileName));

    private static IReadOnlyDictionary<string, string> ReadObject(string path)
    {
        AcceptanceAssert.True(File.Exists(path), $"Localization file is missing: {path}");
        using var document = JsonDocument.Parse(
            File.ReadAllText(path),
            new JsonDocumentOptions { AllowTrailingCommas = true, CommentHandling = JsonCommentHandling.Skip });
        AcceptanceAssert.True(document.RootElement.ValueKind == JsonValueKind.Object, $"Localization file must be a JSON object: {path}");
        return document.RootElement.EnumerateObject()
            .Where(property => property.Value.ValueKind == JsonValueKind.String)
            .ToDictionary(
                property => property.Name,
                property => property.Value.GetString() ?? string.Empty,
                StringComparer.Ordinal);
    }
}
