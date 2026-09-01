using Vivhite.Tests.Acceptance;
using Vivhite.Tests.Mechanics;
using Vivhite.Tests.Relics;

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
            new("exact 61 registered card IDs", CardCatalogAcceptanceTests.HasApprovedStableIds),
            new("rarity distribution 3/18/24/16", CardCatalogAcceptanceTests.HasApprovedRarityDistribution),
            new("starter deck 4/4/1 and legacy classes removed", CardCatalogAcceptanceTests.HasApprovedStarterDeckAndNoLegacyCardTypes),
            new("all 58 fixed LifeCost values match the approved table", BalanceAcceptanceTests.AllFixedLifeCostsMatchTheApprovedTable),
            new("priority weak-card and Dimension Up buffs match approved values", BalanceAcceptanceTests.PriorityWeakCardAndDimensionBuffsMatchApprovedValues),
            new("all 19 Drain DynamicVars are doubled from the current table", BalanceAcceptanceTests.AllDrainDynamicVarsMatchTheDoubledCurrentTable),
            new("all Drain DynamicVars remain integral across upgrade", BalanceAcceptanceTests.AllDrainDynamicVarsRemainIntegralAcrossUpgrade),
            new("delayed Drain powers use doubled card values", BalanceAcceptanceTests.DelayedDrainPowersUseTheDoubledCardValues),
            new("global Drain powers use native integer Amount", BalanceAcceptanceTests.GlobalDrainPowersUseNativeIntegerAmount),
            new("exact bilingual 61-card localization", LocalizationAcceptanceTests.CoversExactApprovedCardSet),
            new("all card DynamicVars match eng/zhs placeholders", LocalizationAcceptanceTests.CardDynamicVarsMatchEveryBilingualPlaceholder),
            new("five bilingual keywords use approved mechanics", LocalizationAcceptanceTests.KeywordsDescribeApprovedMechanics),
            new("all 23 powers have complete bilingual localization", PowerPresentationAcceptanceTests.AllRegisteredPowersHaveCompleteBilingualLocalization),
            new("all 23 powers use dedicated existing non-NOPE icons", PowerPresentationAcceptanceTests.AllRegisteredPowersUseDedicatedExistingIcons),
            new("registered runtime models never expose raw localization keys", PlayerFacingTextAcceptanceTests.RegisteredRuntimeModelsNeverExposeRawLocalizationKeys),
            new("Chinese terms and Energy rich text match the player contract", PlayerFacingTextAcceptanceTests.ChineseTermsAndEnergyRichTextMatchThePlayerContract),
            new("base Ancient pages never expose missing-key placeholders", PlayerFacingTextAcceptanceTests.BaseAncientPagesNeverExposeMissingKeyPlaceholders),
            new("native Exhaust and Retain text is not duplicated", PlayerFacingTextAcceptanceTests.NativeCardKeywordsAreNotDuplicatedInLocalizedBodies),
            new("Margin pays before HP and payment leaves 1 HP", LifeCalculationAcceptanceTests.MarginIsConsumedBeforeHpAndPaymentLeavesOneHp),
            new("negative Life Calculation normalizes to a free payable request", LifeCalculationAcceptanceTests.NegativeAmountsNormalizeToZeroWithoutPayment),
            new("AutoPlay rejects unaffordable Life Calculation payments", LifeCalculationAcceptanceTests.AutoPlayShouldPlayHonorsLifePaymentLegality),
            new("compiled card flow gates and pays before effects", LifeCalculationAcceptanceTests.CompiledCardBaseGatesPlayAndPaysBeforeEffects),
            new("謦欬 attacks pay before card-triggered recovery", LifeCalculationAcceptanceTests.LifeCostAttacksPayBeforeAnyCardTriggeredRecovery),
            new("Tungsten Rod reduced HP loss still completes payment", TungstenRodCompatibilityAcceptanceTests.ReducedHpLossStillCompletesPayment),
            new("Life payment uses reducer-aware completion", TungstenRodCompatibilityAcceptanceTests.PaymentFlowUsesReducerAwareCompletion),
            new("no artificial cap constants or static fields", UnboundedGrowthAcceptanceTests.HasNoArtificialCapConstantsOrStaticFields),
            new("Dimension Up is uncapped, stackable, and grows max/current HP", UnboundedGrowthAcceptanceTests.DimensionUpUsesUncappedStackableMaxAndCurrentHpGrowth),
            new("overheal preserves uncapped excess", UnboundedGrowthAcceptanceTests.OverhealPreservesUncappedExcess),
            new("Drain uses actual enemy HP loss and rounds up once", DrainAcceptanceTests.UsesActualEnemyHpLossAndAggregatesBeforeOneRounding),
            new("Drain supports rates and healing above 100%", DrainAcceptanceTests.SupportsRatesAndHealingFarAboveOneHundredPercent),
            new("Drain ResolveAsync passes one aggregate uncapped ceiling request", DrainAcceptanceTests.ResolveAsyncPassesTheAggregateUncappedCeilingRequest),
            new("all Cough draw and discard effects use final doubled amounts", FinalBalanceAcceptanceTests.EveryCoughDrawAndDiscardEffectUsesTheFinalDoubledAmount),
            new("Inductive Circle uses uncapped 50/75% healing at one Energy", FinalBalanceAcceptanceTests.InductiveCircleUsesUncappedPercentageHealingAndFinalEnergy),
            new("Inductive Circle death healing runtime chain is complete and uncapped", FinalBalanceAcceptanceTests.InductiveCircleDeathHealingRuntimeChainIsCompleteAndUncapped),
            new("Color Conservation remains zero Energy after upgrade", FinalBalanceAcceptanceTests.ColorConservationCostsZeroBeforeAndAfterUpgrade),
            new("final draw and Inductive Circle text matches runtime", FinalBalanceAcceptanceTests.FinalDrawAndInductiveTextMatchesRuntime),
            new("Basic/A/B attacks use Common global Drain at cardPercent 0", CrossSuitDrainAcceptanceTests.BasicAndABAttacksUseZeroPercentCommonDrain),
            new("Common Drain defaults to all Chromatic recovery conversions", CrossSuitDrainAcceptanceTests.CommonDrainDefaultsToChromaticRecoveryConversions),
            new("C/Hybrid printed Drain resolves exactly once", CrossSuitDrainAcceptanceTests.ChromaticAndHybridPrintedDrainIsNotDuplicated),
            new("every printed Drain Attack passes its approved DynamicVar expression", CrossSuitDrainAcceptanceTests.EveryPrintedDrainAttackPassesApprovedDynamicVarExpression),
            new("Dynamic Programming only buffs powered opponent Attack damage", CrossSuitDrainAcceptanceTests.DynamicProgrammingOnlyBuffsPoweredOpponentAttackDamage),
            new("Chromatic healing tracks actual HP gain and resets each turn", ChromaticTurnHealingAcceptanceTests.TracksOnlyActualHpIncreaseAndResetsEachTurn),
            new("Drain recovery precedes wrapped enemy-death listeners", EnemyDeathOrderingAcceptanceTests.WrappedAttackRecoversBeforeDeathListenersAndUnwrappedDeathIsImmediate),
            new("deferred enemy-death failures are neither lost nor replayed", EnemyDeathOrderingAcceptanceTests.DeferredListenerFailuresArePreservedWithoutLossOrReplay),
            new("generated and recovered copies retain Dimension Up eligibility", GeneratedCardGrowthAcceptanceTests.GeneratedAndRecoveredCopiesRetainNormalDimensionUpEligibility),
            new("Crimson ritual keeps LifeCostPerPhase at 1", VivhitesCrimsonTransformationRitualAcceptanceTests.CardAndPowerContract),
            new("Crimson ritual phases scale without caps", _ => VivhitesCrimsonTransformationRitualAcceptanceTests.UnboundedPhasesAddLifeCostAndPercentages()),
            new("Crimson ritual combines printed 2 plus phase 3 as cost 5", _ => VivhitesCrimsonTransformationRitualAcceptanceTests.CombinedGateIncludesPrintedAndRitualLifeCost()),
            new("Crimson ritual global Power hook covers attacks created after application", _ => VivhitesCrimsonTransformationRitualAcceptanceTests.GlobalPowerHookCoversAttacksCreatedAfterApplication()),
            new("Crimson ritual uses shared payment and printed costs", VivhitesCrimsonTransformationRitualAcceptanceTests.RuntimeUsesTheSharedPaymentGateAndEveryPrintedBaseCost),
            new("death deduplication is per entity event", DeathDeduplicationAcceptanceTests.DeduplicatesOnlyTheSameEntityDeathEvent),
            new("Solitary Crown heals ceil(20% Max HP) without caps", SolitaryCrownRelicAcceptanceTests.UsesTwentyPercentMaxHpCeilingWithoutTriggerCaps),
            new("Solitary Crown callback uses current Max HP and shared death deduplication", SolitaryCrownRelicAcceptanceTests.DeathCallbackUsesCurrentOwnerMaxHpAndSharedPerEntityDeduplication),
            new("conditional card keywords match approved states", CardKeywordAcceptanceTests.ConditionalKeywordsMatchTheApprovedCardStates),
            new("Vivhite exclusively owns the V3 skin and Ironclad has no replacement", SharedAssetsAcceptanceTests.VivhiteOwnsV3SkinAndIroncladHasNoReplacement),
            new("Vivhite combat scene uses eye-lens magic", SharedAssetsAcceptanceTests.VivhiteCombatSceneUsesEyeLensMagic),
            new("Vivhite card trail is character-owned", VivhiteCardTrailAcceptanceTests.IsOwnedOnlyByVivhiteCharacter),
            new("Vivhite profile uses verified native magic audio", SharedAssetsAcceptanceTests.VivhiteProfileUsesVerifiedNativeMagicAudio),
            new("V3 skin rejects legacy and missing-page layouts", SharedAssetsAcceptanceTests.V3SkinRequiresExactFivePageLayout),
            new("all 61 cards use dedicated opaque portrait art", SharedAssetsAcceptanceTests.EveryVivhiteCardUsesDedicatedOpaquePortraitArt),
            new("Solitary Crown uses dedicated relic art", SharedAssetsAcceptanceTests.SolitaryCrownUsesDedicatedRelicArt),
            new("exact 92-file runtime art inventory", RuntimeArtInventoryAcceptanceTests.CoversExactNinetyTwoRuntimeAssets),
            new("no retired runtime placeholders or PNG orphans", RuntimeArtInventoryAcceptanceTests.HasNoRetiredRuntimePlaceholdersOrPngOrphans),
            new("eye-lens glint keeps A=254 and A=255 distinct", RuntimeArtInventoryAcceptanceTests.EyeLensGlintKeepsTransparentAlphaClassesDistinct),
            new("PCK deployment contract rejects split builds and preserves full triplet flow", BuildDeploymentContractAcceptanceTests.RejectsSplitDeploymentAndPreservesSafeBuilds)
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
