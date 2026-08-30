using Vivhite.Tests.Acceptance;
using Vivhite.Tests.Mechanics;

namespace Vivhite.Tests;

internal static class Program
{
    private static async Task<int> Main()
    {
        RepositorySnapshot repository;
        try
        {
            repository = RepositorySnapshot.Load();
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"[FATAL] Could not load the compiled Vivhite acceptance snapshot: {exception.Message}");
            return 2;
        }

        AcceptanceTest[] tests =
        [
            new("production source compiles and reflects", CardCatalogAcceptanceTests.ProductionSourceCompilesAndReflects),
            new("exact 60 registered card IDs", CardCatalogAcceptanceTests.HasApprovedStableIds),
            new("rarity distribution 3/18/24/15", CardCatalogAcceptanceTests.HasApprovedRarityDistribution),
            new("starter deck 4/4/1 and legacy classes removed", CardCatalogAcceptanceTests.HasApprovedStarterDeckAndNoLegacyCardTypes),
            new("exact bilingual 60-card localization", LocalizationAcceptanceTests.CoversExactApprovedCardSet),
            new("five bilingual keywords use approved mechanics", LocalizationAcceptanceTests.KeywordsDescribeApprovedMechanics),
            new("Margin pays before HP and payment leaves 1 HP", LifeCalculationAcceptanceTests.MarginIsConsumedBeforeHpAndPaymentLeavesOneHp),
            new("compiled card flow gates and pays before effects", LifeCalculationAcceptanceTests.CompiledCardBaseGatesPlayAndPaysBeforeEffects),
            new("no artificial cap constants or static fields", UnboundedGrowthAcceptanceTests.HasNoArtificialCapConstantsOrStaticFields),
            new("Dimension Up is uncapped, stackable, and grows max/current HP", UnboundedGrowthAcceptanceTests.DimensionUpUsesUncappedStackableMaxAndCurrentHpGrowth),
            new("overheal preserves uncapped excess", UnboundedGrowthAcceptanceTests.OverhealPreservesUncappedExcess),
            new("Drain uses actual enemy HP loss and rounds once", DrainAcceptanceTests.UsesActualEnemyHpLossAndAggregatesBeforeOneRounding),
            new("Drain supports rates and healing above 100%", DrainAcceptanceTests.SupportsRatesAndHealingFarAboveOneHundredPercent),
            new("generated and recovered copies retain Dimension Up eligibility", GeneratedCardGrowthAcceptanceTests.GeneratedAndRecoveredCopiesRetainNormalDimensionUpEligibility),
            new("death deduplication is per entity event", DeathDeduplicationAcceptanceTests.DeduplicatesOnlyTheSameEntityDeathEvent),
            new("Vivhite and Ironclad share the V3 five-page skin", SharedAssetsAcceptanceTests.VivhiteAndIroncladUseTheSameV3Skin),
            new("card portraits resolve to real type-appropriate placeholders", SharedAssetsAcceptanceTests.CardPortraitsResolveToRealTypeAppropriatePlaceholders)
        ];

        var failures = 0;
        Console.WriteLine($"Vivhite compiled acceptance tests ({repository.RootDirectory})");
        foreach (var test in tests)
        {
            try
            {
                await test.Body(repository);
                Console.WriteLine($"[PASS] {test.Name}");
            }
            catch (Exception exception)
            {
                failures++;
                Console.WriteLine($"[FAIL] {test.Name}");
                Console.WriteLine(Indent(exception.GetBaseException().Message));
            }
        }

        Console.WriteLine($"Result: {tests.Length - failures} passed, {failures} failed, {tests.Length} total.");
        return failures == 0 ? 0 : 1;
    }

    private static string Indent(string message) =>
        string.Join(Environment.NewLine, message.Split('\n').Select(line => $"       {line.TrimEnd('\r')}"));

    private sealed record AcceptanceTest(string Name, Func<RepositorySnapshot, Task> Body)
    {
        public AcceptanceTest(string name, Action<RepositorySnapshot> body)
            : this(name, repository =>
            {
                body(repository);
                return Task.CompletedTask;
            })
        {
        }
    }
}
