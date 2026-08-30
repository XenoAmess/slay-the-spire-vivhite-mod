using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Vivhite.Relics;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Relics;

internal static class SolitaryCrownRelicAcceptanceTests
{
    public static void UsesFivePercentMaxHpCeilingWithoutTriggerCaps(RepositorySnapshot repository)
    {
        (int MaxHp, int ExpectedHealing)[] cases =
        [
            (0, 0),
            (1, 1),
            (19, 1),
            (20, 1),
            (21, 2),
            (78, 4),
            (100, 5),
            (101, 6),
            (1_000_000, 50_000),
            (int.MaxValue, 107_374_183)
        ];

        foreach (var (maxHp, expectedHealing) in cases)
        {
            AcceptanceAssert.Equal(
                expectedHealing,
                OriginStarChart.CalculateHealingForMaxHp(maxHp),
                $"Solitary Crown must heal ceil(5% of {maxHp} Max HP). ");
        }

        var rejectedNegativeMaxHp = false;
        try
        {
            OriginStarChart.CalculateHealingForMaxHp(-1);
        }
        catch (ArgumentOutOfRangeException)
        {
            rejectedNegativeMaxHp = true;
        }

        AcceptanceAssert.True(
            rejectedNegativeMaxHp,
            "A negative Max HP input must be rejected instead of producing invalid healing.");
        AcceptanceAssert.Equal(
            typeof(AnyEnemyDeathRelic),
            typeof(OriginStarChart).BaseType!,
            "Solitary Crown must retain the shared per-entity enemy-death deduplication listener. ");
        AcceptanceAssert.Empty(
            typeof(OriginStarChart).GetFields(
                    BindingFlags.Instance |
                    BindingFlags.Public |
                    BindingFlags.NonPublic |
                    BindingFlags.DeclaredOnly),
            "Solitary Crown must not add a per-turn, per-combat, trigger-count, or healing cap field:");

        VerifyLocalization(repository, "eng", "Solitary Crown", "rounded up");
        VerifyLocalization(repository, "zhs", "孤高冠冕", "向上取整");
    }

    private static void VerifyLocalization(
        RepositorySnapshot repository,
        string locale,
        string expectedTitle,
        string roundingText)
    {
        var path = Path.Combine(repository.LocalizationDirectory, locale, "relics.json");
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var root = document.RootElement;
        var title = root.GetProperty("VIVHITE_RELIC_ORIGIN_STAR_CHART.title").GetString() ?? string.Empty;
        var description = root.GetProperty("VIVHITE_RELIC_ORIGIN_STAR_CHART.description").GetString() ?? string.Empty;

        AcceptanceAssert.Equal(expectedTitle, title, $"{locale} relic title must match the approved player-facing name. ");
        AcceptanceAssert.True(
            description.Contains("{Heal}%", StringComparison.Ordinal),
            $"{locale} relic description must present the five-point Heal variable as a percentage.");
        AcceptanceAssert.True(
            description.Contains(roundingText, StringComparison.Ordinal),
            $"{locale} relic description must explicitly state ceiling rounding.");
    }

#if VIVHITE_RELIC_ACCEPTANCE
    [ModuleInitializer]
    internal static void RunStandalone()
    {
        UsesFivePercentMaxHpCeilingWithoutTriggerCaps(RepositorySnapshot.Load());
        Console.WriteLine("[PASS] Solitary Crown heals ceil(5% Max HP) per deduplicated enemy death without custom caps");
    }
#endif
}
