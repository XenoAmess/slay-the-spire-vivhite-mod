using System.Text.Json;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class LocalizationAcceptanceTests
{
    private static readonly string[] RequiredCardSuffixes = ["title", "description", "smartDescription"];

    private static readonly string[] RequiredKeywordIds =
    [
        "VIVHITE_KEYWORD_LIFE_CALCULATION",
        "VIVHITE_KEYWORD_MARGIN",
        "VIVHITE_KEYWORD_DIMENSION_UP",
        "VIVHITE_KEYWORD_DRAIN",
        "VIVHITE_KEYWORD_LETHAL"
    ];

    public static void CoversExactApprovedCardSet(RepositorySnapshot repository)
    {
        var approvedIds = ApprovedCardCatalog.RarityById.Keys.Order(StringComparer.Ordinal).ToArray();
        var byLocale = new Dictionary<string, IReadOnlyDictionary<string, string>>(StringComparer.Ordinal)
        {
            ["eng"] = ReadLocale(repository, "eng"),
            ["zhs"] = ReadLocale(repository, "zhs")
        };

        var expectedRequiredKeys = approvedIds
            .SelectMany(id => RequiredCardSuffixes.Select(suffix => $"{id}.{suffix}"))
            .Order(StringComparer.Ordinal)
            .ToArray();
        foreach (var (locale, entries) in byLocale)
        {
            var missing = expectedRequiredKeys
                .Where(key => !entries.TryGetValue(key, out var value) || string.IsNullOrWhiteSpace(value))
                .ToArray();
            AcceptanceAssert.Empty(
                missing,
                $"Locale '{locale}' must provide non-empty title/description/smartDescription for all 60 approved cards:");

            var localizedIds = entries.Keys
                .Where(key => key.StartsWith("VIVHITE_CARD_", StringComparison.Ordinal))
                .Select(key => key.Split('.', 2)[0])
                .Distinct(StringComparer.Ordinal)
                .Order(StringComparer.Ordinal)
                .ToArray();
            AcceptanceAssert.SetEqual(
                approvedIds,
                localizedIds,
                $"Locale '{locale}' card IDs must exactly match the approved catalog; legacy IDs are not allowed.");
        }

        var englishCardKeys = CardKeys(byLocale["eng"]);
        var chineseCardKeys = CardKeys(byLocale["zhs"]);
        AcceptanceAssert.SetEqual(
            englishCardKeys,
            chineseCardKeys,
            "English and Simplified Chinese card-localization key sets must be identical, including selection prompts.");
    }

    public static void KeywordsDescribeApprovedMechanics(RepositorySnapshot repository)
    {
        var english = ReadKeywordFile(repository, "eng");
        var chinese = ReadKeywordFile(repository, "zhs");
        var expectedKeys = RequiredKeywordIds
            .SelectMany(id => new[] { $"{id}.title", $"{id}.description" })
            .ToArray();
        AcceptanceAssert.SetEqual(expectedKeys, english.Keys.ToArray(), "English keyword IDs must be exactly the five approved mechanics.");
        AcceptanceAssert.SetEqual(expectedKeys, chinese.Keys.ToArray(), "Chinese keyword IDs must be exactly the five approved mechanics.");

        AssertContainsAll(
            english["VIVHITE_KEYWORD_LIFE_CALCULATION.description"],
            "English Life Calculation",
            "margin", "1 hp");
        AssertContainsAny(
            english["VIVHITE_KEYWORD_LIFE_CALCULATION.description"],
            "English Life Calculation must say an unaffordable card cannot be played",
            "cannot be played", "can't be played", "unplayable");
        AssertContainsAll(
            english["VIVHITE_KEYWORD_MARGIN.description"],
            "English Margin",
            "life calculation", "consume", "1");
        AssertContainsAll(
            english["VIVHITE_KEYWORD_DIMENSION_UP.description"],
            "English Dimension Up",
            "permanent", "max hp", "current hp");
        AssertContainsAny(
            english["VIVHITE_KEYWORD_DIMENSION_UP.description"],
            "English Dimension Up must increase current HP by the same amount",
            "same amount", "equal amount", "equally");
        AssertContainsAll(
            english["VIVHITE_KEYWORD_DRAIN.description"],
            "English Drain",
            "actual", "enemi", "once");
        AssertContainsAny(
            english["VIVHITE_KEYWORD_DRAIN.description"],
            "English Drain must state that rates can exceed 100%",
            "over 100%", "above 100%", "exceed 100%", "greater than 100%");
        AssertContainsAny(
            english["VIVHITE_KEYWORD_LETHAL.description"],
            "English Lethal must be tied to this card directly killing its target",
            "directly kills", "directly kill", "directly by this card kills", "reduces its target to 0 hp");

        AssertContainsAll(
            chinese["VIVHITE_KEYWORD_LIFE_CALCULATION.description"],
            "中文生命演算",
            "余量", "1");
        AssertContainsAny(
            chinese["VIVHITE_KEYWORD_LIFE_CALCULATION.description"],
            "中文生命演算必须说明生命不足时不可打出",
            "不可打出", "不能打出");
        AssertContainsAll(
            chinese["VIVHITE_KEYWORD_MARGIN.description"],
            "中文余量",
            "生命演算", "消耗", "1");
        AssertContainsAll(
            chinese["VIVHITE_KEYWORD_DIMENSION_UP.description"],
            "中文增维",
            "永久", "最大生命", "当前生命");
        AssertContainsAny(
            chinese["VIVHITE_KEYWORD_DIMENSION_UP.description"],
            "中文增维必须说明当前生命等量增加",
            "等量", "相同数值", "同等数值");
        AssertContainsAll(
            chinese["VIVHITE_KEYWORD_DRAIN.description"],
            "中文汲取",
            "实际", "敌", "取整一次");
        AssertContainsAny(
            chinese["VIVHITE_KEYWORD_DRAIN.description"],
            "中文汲取必须说明倍率可以超过 100%",
            "超过 100%", "超过100%", "高于 100%", "高于100%");
        AssertContainsAny(
            chinese["VIVHITE_KEYWORD_LETHAL.description"],
            "中文致命必须由此牌直接杀死目标触发",
            "直接令目标死亡", "直接杀死目标", "直接造成的伤害击杀目标", "令目标生命降至 0");
    }

    private static string[] CardKeys(IReadOnlyDictionary<string, string> entries) => entries.Keys
        .Where(key => key.StartsWith("VIVHITE_CARD_", StringComparison.Ordinal))
        .Order(StringComparer.Ordinal)
        .ToArray();

    private static IReadOnlyDictionary<string, string> ReadKeywordFile(RepositorySnapshot repository, string locale)
    {
        var path = Path.Combine(repository.LocalizationDirectory, locale, "card_keywords.json");
        AcceptanceAssert.True(File.Exists(path), $"Keyword localization file is missing: {path}");
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        return document.RootElement.EnumerateObject()
            .Where(property => property.Value.ValueKind == JsonValueKind.String)
            .ToDictionary(property => property.Name, property => property.Value.GetString() ?? string.Empty, StringComparer.Ordinal);
    }

    private static IReadOnlyDictionary<string, string> ReadLocale(RepositorySnapshot repository, string locale)
    {
        var directory = Path.Combine(repository.LocalizationDirectory, locale);
        AcceptanceAssert.True(Directory.Exists(directory), $"Localization directory is missing: {directory}");

        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        var duplicates = new List<string>();
        foreach (var file in Directory.GetFiles(directory, "*.json", SearchOption.AllDirectories).Order(StringComparer.Ordinal))
        {
            using var document = JsonDocument.Parse(
                File.ReadAllText(file),
                new JsonDocumentOptions { AllowTrailingCommas = true, CommentHandling = JsonCommentHandling.Skip });
            AcceptanceAssert.True(document.RootElement.ValueKind == JsonValueKind.Object, $"Localization file must contain a JSON object: {file}");
            foreach (var property in document.RootElement.EnumerateObject())
            {
                if (property.Value.ValueKind == JsonValueKind.String &&
                    !result.TryAdd(property.Name, property.Value.GetString() ?? string.Empty))
                {
                    duplicates.Add($"{property.Name} ({file})");
                }
            }
        }
        AcceptanceAssert.Empty(duplicates, $"Locale '{locale}' contains duplicate localization keys:");
        return result;
    }

    private static void AssertContainsAll(string value, string contract, params string[] fragments)
    {
        var missing = fragments.Where(fragment => !value.Contains(fragment, StringComparison.OrdinalIgnoreCase)).ToArray();
        AcceptanceAssert.Empty(missing, $"{contract} is missing required semantic fragments. Text: {value}");
    }

    private static void AssertContainsAny(string value, string contract, params string[] alternatives)
    {
        AcceptanceAssert.True(
            alternatives.Any(fragment => value.Contains(fragment, StringComparison.OrdinalIgnoreCase)),
            $"{contract}. Expected one of [{string.Join(" | ", alternatives)}]. Text: {value}");
    }
}
