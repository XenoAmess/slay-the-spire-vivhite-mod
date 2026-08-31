using System.Collections;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Powers;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.TestSupport;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Vivhite.Cards.Conservation;
using Vivhite.Cards.Hybrid;
using Vivhite.Cards.Recursion;
using Vivhite.Core;
using Vivhite.Powers;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class GeneratedCardGrowthAcceptanceTests
{
    public static async Task GeneratedAndRecoveredCopiesRetainNormalDimensionUpEligibility(
        RepositorySnapshot repository)
    {
        string[] copyCardTypes =
        [
            "Vivhite.Cards.Recursion.EventLoop",
            "Vivhite.Cards.Hybrid.ConservedRecurrence"
        ];
        var copyFailures = new List<string>();
        foreach (var fullName in copyCardTypes)
        {
            var cardType = repository.CompiledAssembly.GetType(fullName, throwOnError: false);
            if (cardType is null)
            {
                copyFailures.Add($"{fullName}: missing compiled card type");
                continue;
            }
            var effect = DeclaredEffect(cardType);
            var calls = IlInspection.CalledMethods(effect);
            if (!calls.Any(method => method.Name == "CreateClone"))
            {
                copyFailures.Add($"{fullName}: does not clone the selected normal card instance");
            }
            if (!calls.Any(method =>
                    method.DeclaringType?.FullName == "MegaCrit.Sts2.Core.Commands.CardPileCmd" &&
                    method.Name == "AddGeneratedCardToCombat"))
            {
                copyFailures.Add($"{fullName}: does not add the clone through the normal generated-card pipeline");
            }
        }
        AcceptanceAssert.Empty(
            copyFailures,
            "Event Loop and Conserved Recurrence must generate ordinary runtime clones, not downgraded special card types:");

        string[] dimensionCardTypes =
        [
            "Vivhite.Cards.Conservation.ScaleTransformation",
            "Vivhite.Cards.Conservation.TopologicalGrowth",
            "Vivhite.Cards.Conservation.AxiomOfLife"
        ];
        var growthFailures = new List<string>();
        foreach (var fullName in dimensionCardTypes)
        {
            var cardType = repository.CompiledAssembly.GetType(fullName, throwOnError: false);
            if (cardType is null)
            {
                growthFailures.Add($"{fullName}: missing compiled card type");
                continue;
            }
            var calls = IlInspection.CalledMethods(DeclaredEffect(cardType));
            if (!calls.Any(method =>
                    method.DeclaringType == typeof(DimensionUp) &&
                    method.Name == nameof(DimensionUp.ApplyAsync)))
            {
                growthFailures.Add($"{fullName}: card effect bypasses the shared DimensionUp.ApplyAsync entry point");
            }
        }
        AcceptanceAssert.Empty(
            growthFailures,
            "Every approved Dimension Up card must call the same core entry point, so its runtime clones stay eligible:");

        var coreSource = repository.RequireSourceType("Vivhite.Core.DimensionUp").Declaration;
        var sourceOriginFilters = coreSource.DescendantNodes()
            .OfType<IfStatementSyntax>()
            .Where(statement => statement.Condition.ToString().Contains("cardSource", StringComparison.Ordinal))
            .Select(statement => statement.Condition.ToString())
            .Concat(coreSource.DescendantNodes()
                .OfType<MemberAccessExpressionSyntax>()
                .Where(access => access.Expression.ToString().Contains("cardSource", StringComparison.Ordinal))
                .Select(access => access.ToString()))
            .Distinct(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Empty(
            sourceOriginFilters,
            "DimensionUp may carry CardModel provenance but must not inspect it to exclude generated, copied, temporary, repeated, or recovered cards:");

        await AssertProductionGenerationRecoveryAndGrowthChains(repository);
    }

    private static async Task AssertProductionGenerationRecoveryAndGrowthChains(
        RepositorySnapshot repository)
    {
        var manager = CombatManager.Instance;
        var turnStateField = typeof(CombatManager).GetField(
            "_turnState",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("CombatManager._turnState is missing from the engine contract.");
        var previousTurnState = turnStateField.GetValue(manager);
        var previousTestMode = TestMode.IsOn;
        var previousLocalNetId = LocalContext.NetId;
        var injectedTypes = new List<Type>();
        IDisposable? selectorScope = null;
        IDisposable? localizationScope = null;
        IDisposable? loggingScope = null;
        ActionQueueSet? actionQueues = null;
        var trackedObjects = new List<object>();

        try
        {
            TestMode.IsOn = true;
            LocalContext.NetId = 1UL;
            loggingScope = SuppressHeadlessLogging();
            foreach (var type in new[]
                     {
                         typeof(InfiniteDimensionalityPower),
                         typeof(InfiniteMarginPower),
                         typeof(TopologicalGrowth),
                         typeof(EventLoop),
                         typeof(ConservedRecurrence)
                     })
            {
                if (ModelDb.Contains(type))
                {
                    continue;
                }

                ModelDb.Inject(type);
                injectedTypes.Add(type);
            }
            localizationScope = InstallProductionCardLocalization(repository);

            var encounterType = typeof(EncounterModel).Assembly.GetTypes()
                .Where(type => typeof(EncounterModel).IsAssignableFrom(type) && !type.IsAbstract)
                .OrderBy(type => type.FullName, StringComparer.Ordinal)
                .First();
            var encounter = MakeMutableForEngineContract(
                (EncounterModel)RuntimeHelpers.GetUninitializedObject(encounterType));
            var combatState = new CombatState(encounter, NullRunState.Instance, [], [], null!);
            var owner = CreateCreatureWithPowerStorage(currentHp: 2048, maxHp: 2048, enemy: false);
            var enemy = CreateCreatureWithPowerStorage(currentHp: 40, maxHp: 40, enemy: true);
            var monster = CreateHeadlessMonster(enemy);
            var player = CreateHeadlessPlayer(owner);

            combatState.AddPlayer(player);
            EngineTestObjects.SetAutoProperty(enemy, nameof(Creature.CombatState), combatState);
            combatState.AddCreature(enemy);
            var playerCombatState = new PlayerCombatState(player);
            EngineTestObjects.SetAutoProperty(player, nameof(Player.PlayerCombatState), playerCombatState);
            EngineTestObjects.SetAutoProperty(playerCombatState, nameof(PlayerCombatState.Energy), 256);

            var turnState = new CombatTurnState(combatState);
            EngineTestObjects.SetAutoProperty(turnState, nameof(CombatTurnState.IsInProgress), true);
            turnStateField.SetValue(manager, turnState);
            manager.History.Clear();
            AcceptanceAssert.True(manager.IsInProgress, "The real CombatTurnState must be in progress for generated-card production commands.");
            NetCombatCardDb.Instance.ClearCardsForTesting();

            trackedObjects.Add(playerCombatState);
            trackedObjects.AddRange(playerCombatState.AllPiles);
            trackedObjects.Add(owner);
            trackedObjects.Add(enemy);
            trackedObjects.Add(monster);

            var selector = new TestCardSelector();
            selectorScope = CardSelectCmd.UseSelector(selector, false);
            actionQueues = new ActionQueueSet([player]);
            actionQueues.SetUpForCombat();
            actionQueues.CombatStarted();

            var sourceProbe = MakeMutableForEngineContract(new DimensionUpCardSourceProbe());
            sourceProbe.Owner = owner;
            GetPowerStorage(owner).Add(sourceProbe);
            trackedObjects.Add(sourceProbe);
            var playedDimensionUpSources = new List<CardModel>();

            var eventLoopSource = await AddProductionCardToHandAsync<TopologicalGrowth>(
                combatState,
                player,
                trackedObjects);
            await PlayCardThroughProductionActionAsync(
                eventLoopSource,
                actionQueues,
                expectedEnergySpent: 1,
                expectedLifeLost: 8,
                expectedDimensionUp: 1);
            playedDimensionUpSources.Add(eventLoopSource);
            AcceptanceAssert.True(
                playerCombatState.ExhaustPile.Cards.Contains(eventLoopSource),
                "The Topological Growth source must reach the real Exhaust pile after its first production play.");

            var eventLoop = await AddProductionCardToHandAsync<EventLoop>(
                combatState,
                player,
                trackedObjects);
            selector.PrepareToSelect([eventLoopSource]);
            await PlayCardThroughProductionActionAsync(
                eventLoop,
                actionQueues,
                expectedEnergySpent: 1,
                expectedLifeLost: 3,
                expectedDimensionUp: 0);

            var eventLoopClones = playerCombatState.Hand.Cards
                .Where(card => card.IsClone && ReferenceEquals(card.CloneOf, eventLoopSource))
                .ToArray();
            AcceptanceAssert.Equal(
                1,
                eventLoopClones.Length,
                "Event Loop must create exactly one temporary clone through its production effect. Hand: " +
                string.Join(", ", playerCombatState.Hand.Cards.Select(DescribeCard)));
            var eventLoopClone = eventLoopClones[0];
            AcceptanceAssert.True(
                combatState.ContainsCard(eventLoopClone),
                "Event Loop must register its temporary clone in the real CombatState.");
            AcceptanceAssert.True(
                playerCombatState.Hand.Cards.Contains(eventLoopClone),
                "Event Loop must add its temporary clone through AddGeneratedCardToCombat into the real hand.");
            AcceptanceAssert.True(
                ReferenceEquals(eventLoopClone.Owner, player),
                "Event Loop's temporary clone must retain the selected card's owner.");
            AcceptanceAssert.Equal(
                0,
                eventLoopClone.EnergyCost.GetAmountToSpend(),
                "Event Loop's temporary clone must really cost 0 before it is played.");
            trackedObjects.Add(eventLoopClone);
            await PlayCardThroughProductionActionAsync(
                eventLoopClone,
                actionQueues,
                expectedEnergySpent: 0,
                expectedLifeLost: 8,
                expectedDimensionUp: 1);
            playedDimensionUpSources.Add(eventLoopClone);
            AcceptanceAssert.True(
                playerCombatState.ExhaustPile.Cards.Contains(eventLoopClone),
                "Event Loop's temporary clone must enter the real Exhaust pile after its production play.");

            var conservedRecurrence = await AddProductionCardToHandAsync<ConservedRecurrence>(
                combatState,
                player,
                trackedObjects);
            selector.PrepareToSelect([eventLoopSource]);
            await PlayCardThroughProductionActionAsync(
                conservedRecurrence,
                actionQueues,
                expectedEnergySpent: 2,
                expectedLifeLost: 7,
                expectedDimensionUp: 0);

            var conservedRecurrenceClones = playerCombatState.Hand.Cards
                .Where(card => card.IsClone && ReferenceEquals(card.CloneOf, eventLoopSource))
                .ToArray();
            AcceptanceAssert.Equal(
                1,
                conservedRecurrenceClones.Length,
                "Conserved Recurrence must create exactly one clone of the recovered original. " +
                "Hand: " + string.Join(", ", playerCombatState.Hand.Cards.Select(DescribeCard)) +
                "; Exhaust: " + string.Join(", ", playerCombatState.ExhaustPile.Cards.Select(DescribeCard)));
            var conservedRecurrenceClone = conservedRecurrenceClones[0];
            AcceptanceAssert.True(
                !playerCombatState.ExhaustPile.Cards.Contains(eventLoopSource),
                "Conserved Recurrence must remove the selected original from the real Exhaust pile.");
            AcceptanceAssert.True(
                playerCombatState.Hand.Cards.Contains(eventLoopSource),
                "Conserved Recurrence must recover the exact exhausted original into the real hand.");
            AcceptanceAssert.True(
                !eventLoopSource.IsClone,
                "Conserved Recurrence's recovered card must remain the original card instance.");
            AcceptanceAssert.True(
                combatState.ContainsCard(conservedRecurrenceClone) &&
                playerCombatState.Hand.Cards.Contains(conservedRecurrenceClone),
                "Conserved Recurrence must register and add its generated clone through the real production pipeline.");
            AcceptanceAssert.Equal(
                1,
                eventLoopSource.EnergyCost.GetAmountToSpend(),
                "The non-upgraded recovered original must retain its normal production energy cost.");
            AcceptanceAssert.Equal(
                0,
                conservedRecurrenceClone.EnergyCost.GetAmountToSpend(),
                "Conserved Recurrence's temporary clone must really cost 0 before it is played.");
            trackedObjects.Add(conservedRecurrenceClone);

            await PlayCardThroughProductionActionAsync(
                eventLoopSource,
                actionQueues,
                expectedEnergySpent: 1,
                expectedLifeLost: 8,
                expectedDimensionUp: 1);
            playedDimensionUpSources.Add(eventLoopSource);
            await PlayCardThroughProductionActionAsync(
                conservedRecurrenceClone,
                actionQueues,
                expectedEnergySpent: 0,
                expectedLifeLost: 5,
                expectedDimensionUp: 1);
            playedDimensionUpSources.Add(conservedRecurrenceClone);

            const int settlements = 105;
            for (var growth = playedDimensionUpSources.Count + 1; growth <= settlements; growth++)
            {
                var source = await AddProductionCardToHandAsync<TopologicalGrowth>(
                    combatState,
                    player,
                    trackedObjects);
                await PlayCardThroughProductionActionAsync(
                    source,
                    actionQueues,
                    expectedEnergySpent: 1,
                    expectedLifeLost: 5,
                    expectedDimensionUp: 1);
                playedDimensionUpSources.Add(source);

                if (growth == 30)
                {
                    AssertGrowthCheckpoint(owner, expectedGrowth: 30, expectedMaxHp: 2078, expectedCurrentHp: 1909);
                }
                else if (growth == 100)
                {
                    AssertGrowthCheckpoint(owner, expectedGrowth: 100, expectedMaxHp: 2148, expectedCurrentHp: 1629);
                }
            }

            AssertGrowthCheckpoint(owner, expectedGrowth: 105, expectedMaxHp: 2153, expectedCurrentHp: 1609);
            AcceptanceAssert.Equal(
                150,
                playerCombatState.Energy,
                "All 105 growth settlements must come from real plays with normal and temporary energy costs.");
            AcceptanceAssert.Equal(
                settlements,
                sourceProbe.CardSources.Count,
                "Every production Infinite Dimensionality amount change must expose exactly one originating cardSource hook.");
            for (var index = 0; index < settlements; index++)
            {
                AcceptanceAssert.True(
                    ReferenceEquals(playedDimensionUpSources[index], sourceProbe.CardSources[index]),
                    $"Real play {index + 1} must forward its exact generated, recovered, or production card instance through DimensionUp and PowerCmd.");
            }
        }
        finally
        {
            selectorScope?.Dispose();
            CardSelectCmd.Reset();
            actionQueues?.CombatEnded();
            loggingScope?.Dispose();
            localizationScope?.Dispose();
            manager.History.Clear();
            NetCombatCardDb.Instance.ClearCardsForTesting();
            turnStateField.SetValue(manager, previousTurnState);
            TestMode.IsOn = previousTestMode;
            LocalContext.NetId = previousLocalNetId;

            foreach (var trackedObject in trackedObjects.AsEnumerable().Reverse())
            {
                TryUnsubscribe(manager.StateTracker, trackedObject);
            }

            foreach (var type in injectedTypes.AsEnumerable().Reverse())
            {
                ModelDb.Remove(type);
            }
        }
    }

    private static Player CreateHeadlessPlayer(Creature creature)
    {
        var player = (Player)RuntimeHelpers.GetUninitializedObject(typeof(Player));
        EngineTestObjects.SetAutoProperty(player, nameof(Player.NetId), 1UL);
        SetField(player, "_runState", NullRunState.Instance);
        EngineTestObjects.SetAutoProperty(
            player,
            nameof(Player.Character),
            MakeMutableForEngineContract(new Vivhite.Characters.VivhiteCharacter()));
        EngineTestObjects.SetAutoProperty(player, nameof(Player.BaseOrbSlotCount), 0);
        EngineTestObjects.SetAutoProperty(player, nameof(Player.MaxEnergy), 256);
        EngineTestObjects.SetAutoProperty(player, nameof(Player.IsActiveForHooks), true);
        EngineTestObjects.SetAutoProperty(player, nameof(Player.Creature), creature);
        EngineTestObjects.SetAutoProperty(creature, nameof(Creature.Player), player);
        SetCollectionField(player, "_runPiles", new CardPile(PileType.Deck));
        SetCollectionField(player, "_relics");
        SetCollectionField(player, "_potionSlots");
        return player;
    }

    private static Creature CreateCreatureWithPowerStorage(int currentHp, int maxHp, bool enemy)
    {
        var creature = EngineTestObjects.CreateCreature(currentHp, maxHp, enemy);
        var powers = typeof(Creature).GetField(
            "_powers",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("Creature._powers is missing from the engine contract.");
        powers.SetValue(creature, new List<PowerModel>());
        return creature;
    }

    private static MonsterModel CreateHeadlessMonster(Creature creature)
    {
        var monsterType = typeof(MonsterModel).Assembly.GetTypes()
            .Where(type => typeof(MonsterModel).IsAssignableFrom(type) && !type.IsAbstract)
            .OrderBy(type => type.FullName, StringComparer.Ordinal)
            .First();
        var monster = Activator.CreateInstance(monsterType, nonPublic: true) as MonsterModel
            ?? throw new AcceptanceFailureException(
                $"Could not construct {monsterType.FullName} through its production parameterless constructor.");
        MakeMutableForEngineContract(monster);
        EngineTestObjects.SetAutoProperty(monster, nameof(MonsterModel.Creature), creature);
        EngineTestObjects.SetAutoProperty(creature, nameof(Creature.Monster), monster);
        return monster;
    }

    private static List<PowerModel> GetPowerStorage(Creature creature)
    {
        var powers = typeof(Creature).GetField(
            "_powers",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?.GetValue(creature) as List<PowerModel>;
        return powers ?? throw new AcceptanceFailureException("Creature._powers is not initialized as a production power list.");
    }

    private static void SetCollectionField(object target, string fieldName, params object[] items)
    {
        var field = target.GetType().GetField(
            fieldName,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException($"{target.GetType().FullName}.{fieldName} is missing from the engine contract.");
        if (field.FieldType.IsArray)
        {
            var elementType = field.FieldType.GetElementType()
                ?? throw new AcceptanceFailureException($"{field.FieldType.FullName} has no array element type.");
            var array = Array.CreateInstance(elementType, items.Length);
            for (var index = 0; index < items.Length; index++)
            {
                array.SetValue(items[index], index);
            }
            field.SetValue(target, array);
            return;
        }

        var collection = Activator.CreateInstance(field.FieldType)
            ?? throw new AcceptanceFailureException($"Could not create {field.FieldType.FullName} for {fieldName}.");
        if (collection is not IList list)
        {
            throw new AcceptanceFailureException($"{field.FieldType.FullName} is not an IList-backed production collection.");
        }

        foreach (var item in items)
        {
            list.Add(item);
        }
        field.SetValue(target, collection);
    }

    private static async Task<CardModel> AddProductionCardToHandAsync<TCard>(
        CombatState combatState,
        Player player,
        ICollection<object> trackedObjects)
        where TCard : CardModel
    {
        var playerCombatState = player.PlayerCombatState
            ?? throw new AcceptanceFailureException("The headless player has no PlayerCombatState.");
        var card = combatState.CreateCard(ModelDb.Card<TCard>(), player);
        await CardPileCmd.AddGeneratedCardToCombat(
            card,
            PileType.Hand,
            player,
            CardPilePosition.Bottom);
        trackedObjects.Add(card);
        AcceptanceAssert.True(
            combatState.ContainsCard(card) && playerCombatState.Hand.Cards.Contains(card),
            $"{card.GetType().Name} must be a real combat card in the real Hand before PlayCardAction.");
        return card;
    }

    private static async Task PlayCardThroughProductionActionAsync(
        CardModel card,
        ActionQueueSet actionQueues,
        int expectedEnergySpent,
        int expectedLifeLost,
        int expectedDimensionUp)
    {
        var player = card.Owner;
        var playerCombatState = player.PlayerCombatState
            ?? throw new AcceptanceFailureException($"{card.GetType().Name} has no real PlayerCombatState.");
        var combatState = card.CombatState
            ?? throw new AcceptanceFailureException($"{card.GetType().Name} has no real CombatState.");
        AcceptanceAssert.True(
            playerCombatState.Hand.Cards.Contains(card),
            $"{DescribeCard(card)} must be in the real Hand before PlayCardAction executes.");
        AcceptanceAssert.True(
            card.CanPlay(out var unplayableReason, out var preventer),
            $"{DescribeCard(card)} must be legally playable before PlayCardAction; " +
            $"reason={unplayableReason}, preventer={preventer?.GetType().FullName ?? "none"}.");

        var energyBefore = playerCombatState.Energy;
        var energyToSpend = card.EnergyCost.GetAmountToSpend();
        var currentHpBefore = player.Creature.CurrentHp;
        var maxHpBefore = player.Creature.MaxHp;
        var growthBefore = InfiniteDimensionality.GetAmount(player.Creature);
        var priorFinishedPlays = CombatManager.Instance.History.CardPlaysFinished.Count(entry =>
            ReferenceEquals(entry.CardPlay.Card, card));
        AcceptanceAssert.Equal(
            expectedEnergySpent,
            energyToSpend,
            $"{DescribeCard(card)} must expose the expected real energy cost before play.");
        if (!NetCombatCardDb.Instance.TryGetCardId(card, out _))
        {
            NetCombatCardDb.Instance.IdCardForTesting(card);
        }
        AcceptanceAssert.True(
            NetCombatCardDb.Instance.TryGetCardId(card, out _),
            $"{DescribeCard(card)} must have a legal headless network identity before PlayCardAction.");

        PlayCardAction action;
        try
        {
            action = new PlayCardAction(card, null);
            actionQueues.EnqueueWithoutSynchronizing(action);
            AcceptanceAssert.True(
                ReferenceEquals(actionQueues.GetReadyAction(), action),
                $"{DescribeCard(card)} must become the real ready action after production queueing.");
            await action.Execute();
            AcceptanceAssert.True(
                actionQueues.GetReadyAction() is null,
                $"{DescribeCard(card)} must be removed by the production queue after execution.");
        }
        catch (Exception exception)
        {
            throw new AcceptanceFailureException(
                $"PlayCardAction failed while really playing {DescribeCard(card)}: {exception}");
        }

        if (action.Exception is not null)
        {
            throw new AcceptanceFailureException(
                $"PlayCardAction recorded an exception while really playing {DescribeCard(card)}: {action.Exception}");
        }
        AcceptanceAssert.Equal(
            energyBefore - expectedEnergySpent,
            playerCombatState.Energy,
            $"{DescribeCard(card)} must spend energy through CardModel.SpendResources.");
        AcceptanceAssert.Equal(
            maxHpBefore + expectedDimensionUp,
            player.Creature.MaxHp,
            $"{DescribeCard(card)} must apply Dimension Up only through its real OnPlay effect.");
        AcceptanceAssert.Equal(
            currentHpBefore - expectedLifeLost + expectedDimensionUp,
            player.Creature.CurrentHp,
            $"{DescribeCard(card)} must pay real Cough HP before resolving its real OnPlay effect.");
        AcceptanceAssert.Equal(
            growthBefore + expectedDimensionUp,
            InfiniteDimensionality.GetAmount(player.Creature),
            $"{DescribeCard(card)} must update the production combat-growth marker through real play.");
        AcceptanceAssert.Equal(
            priorFinishedPlays + 1,
            CombatManager.Instance.History.CardPlaysFinished.Count(entry =>
                ReferenceEquals(entry.CardPlay.Card, card) &&
                ReferenceEquals(entry.CardPlay.Player, player) &&
                entry.HappenedThisTurn(combatState)),
            $"{DescribeCard(card)} must produce exactly one real CardPlayFinished history entry.");
        AcceptanceAssert.True(
            !playerCombatState.Hand.Cards.Contains(card) &&
            playerCombatState.ExhaustPile.Cards.Contains(card),
            $"{DescribeCard(card)} must move from the real Hand through Play and into the real Exhaust pile.");
    }

    private static IDisposable InstallProductionCardLocalization(
        RepositorySnapshot repository)
    {
        var productionPath = Path.Combine(repository.LocalizationDirectory, "eng", "cards.json");
        var productionTranslations = JsonSerializer.Deserialize<Dictionary<string, string>>(
            File.ReadAllText(productionPath))
            ?? throw new AcceptanceFailureException($"Production localization is not a JSON object: {productionPath}");
        var productionCards = new Dictionary<string, CardModel>(StringComparer.Ordinal)
        {
            [repository.CardId(typeof(TopologicalGrowth))] = ModelDb.Card<TopologicalGrowth>(),
            [repository.CardId(typeof(EventLoop))] = ModelDb.Card<EventLoop>(),
            [repository.CardId(typeof(ConservedRecurrence))] = ModelDb.Card<ConservedRecurrence>()
        };
        var translations = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (fullProductionId, canonicalCard) in productionCards)
        {
            AcceptanceAssert.Equal(
                fullProductionId,
                $"VIVHITE_CARD_{canonicalCard.Id.Entry}",
                $"{canonicalCard.GetType().Name} must retain its registered production ID.");
            var sourcePrefix = $"{fullProductionId}.";
            var sourceEntries = productionTranslations
                .Where(pair => pair.Key.StartsWith(sourcePrefix, StringComparison.Ordinal))
                .ToArray();
            AcceptanceAssert.True(
                sourceEntries.Length > 0,
                $"Production localization must contain entries for {fullProductionId}.");
            foreach (var (sourceKey, value) in sourceEntries)
            {
                var suffix = sourceKey[fullProductionId.Length..];
                translations[$"{canonicalCard.Id.Entry}{suffix}"] = value;
            }
        }

        foreach (var card in new CardModel[]
                 {
                     ModelDb.Card<EventLoop>(),
                     ModelDb.Card<ConservedRecurrence>()
                 })
        {
            var fullPromptKey = $"VIVHITE_CARD_{card.Id.Entry}.selectionScreenPrompt";
            AcceptanceAssert.True(
                productionTranslations.ContainsKey(fullPromptKey),
                $"The real production localization file must define {fullPromptKey}.");
            AcceptanceAssert.True(
                translations.TryGetValue($"{card.Id.Entry}.selectionScreenPrompt", out var routedPrompt) &&
                string.Equals(routedPrompt, productionTranslations[fullPromptKey], StringComparison.Ordinal),
                $"The cards LocTable must route {fullPromptKey} to the exact canonical ModelId.Entry consumer.");
        }

        var assembly = typeof(CardModel).Assembly;
        var locManagerType = assembly.GetType(
            "MegaCrit.Sts2.Core.Localization.LocManager",
            throwOnError: true)!;
        var locTableType = assembly.GetType(
            "MegaCrit.Sts2.Core.Localization.LocTable",
            throwOnError: true)!;
        var instanceField = locManagerType.GetField(
            "<Instance>k__BackingField",
            BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("LocManager.Instance backing field is missing from the engine contract.");
        var previousInstance = instanceField.GetValue(null);
        var manager = RuntimeHelpers.GetUninitializedObject(locManagerType);
        var table = RuntimeHelpers.GetUninitializedObject(locTableType);
        SetField(table, "_name", "cards");
        SetField(table, "_translations", translations);
        var tablesField = locManagerType.GetField(
            "_tables",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("LocManager._tables is missing from the engine contract.");
        var tables = tablesField.GetValue(manager) as IDictionary;
        if (tables is null)
        {
            tables = Activator.CreateInstance(tablesField.FieldType) as IDictionary
                ?? throw new AcceptanceFailureException("Could not initialize LocManager._tables.");
            tablesField.SetValue(manager, tables);
        }
        tables["cards"] = table;
        instanceField.SetValue(null, manager);
        return new CallbackDisposable(() => instanceField.SetValue(null, previousInstance));
    }

    private static IDisposable SuppressHeadlessLogging()
    {
        var harmony = new Harmony($"vivhite.tests.generated-card-growth.{Guid.NewGuid():N}");
        var loggerType = typeof(CardModel).Assembly.GetType(
            "MegaCrit.Sts2.Core.Logging.Logger",
            throwOnError: true)!;
        var editorProbe = loggerType.GetMethod(
            "GetIsRunningFromGodotEditor",
            BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException(
                "Logger.GetIsRunningFromGodotEditor is missing from the headless engine contract.");
        var editorProbePrefix = typeof(GeneratedCardGrowthAcceptanceTests).GetMethod(
            nameof(SkipGodotEditorProbe),
            BindingFlags.Static | BindingFlags.NonPublic)!;
        harmony.Patch(editorProbe, prefix: new HarmonyMethod(editorProbePrefix));

        var consolePrinterType = typeof(CardModel).Assembly.GetType(
            "MegaCrit.Sts2.Core.Logging.ConsoleLogPrinter",
            throwOnError: true)!;
        var consolePrint = consolePrinterType.GetMethods(
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            .Single(method => method.Name == "Print");
        var consolePrintPrefix = typeof(GeneratedCardGrowthAcceptanceTests).GetMethod(
            nameof(SkipHeadlessConsoleLog),
            BindingFlags.Static | BindingFlags.NonPublic)!;
        harmony.Patch(consolePrint, prefix: new HarmonyMethod(consolePrintPrefix));

        var onPlayWrapper = typeof(CardModel).GetMethods(
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            .Single(method => method.Name == "OnPlayWrapper");
        var stateMachineType = onPlayWrapper.GetCustomAttribute<AsyncStateMachineAttribute>()?.StateMachineType
            ?? throw new AcceptanceFailureException(
                "CardModel.OnPlayWrapper must retain its production async state machine.");
        var moveNext = stateMachineType.GetMethod(
            "MoveNext",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException(
                "CardModel.OnPlayWrapper async state machine has no MoveNext method.");
        var clockTranspiler = typeof(GeneratedCardGrowthAcceptanceTests).GetMethod(
            nameof(UseManagedClockInHeadlessCardPlay),
            BindingFlags.Static | BindingFlags.NonPublic)!;
        harmony.Patch(moveNext, transpiler: new HarmonyMethod(clockTranspiler));

        var logChoice = typeof(CardSelectCmd).GetMethod(
            "LogChoice",
            BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("CardSelectCmd.LogChoice is missing from the engine contract.");
        var prefix = typeof(GeneratedCardGrowthAcceptanceTests).GetMethod(
            nameof(SkipHeadlessCardSelectionLog),
            BindingFlags.Static | BindingFlags.NonPublic)!;
        harmony.Patch(logChoice, prefix: new HarmonyMethod(prefix));
        return new CallbackDisposable(() => harmony.UnpatchAll(harmony.Id));
    }

    private static bool SkipHeadlessConsoleLog() => false;

    private static IEnumerable<CodeInstruction> UseManagedClockInHeadlessCardPlay(
        IEnumerable<CodeInstruction> instructions)
    {
        var godotTicks = typeof(Godot.Time).GetMethod(
            nameof(Godot.Time.GetTicksMsec),
            BindingFlags.Static | BindingFlags.Public)
            ?? throw new AcceptanceFailureException("Godot.Time.GetTicksMsec is missing.");
        var managedTicks = typeof(GeneratedCardGrowthAcceptanceTests).GetMethod(
            nameof(GetManagedTicksMsec),
            BindingFlags.Static | BindingFlags.NonPublic)!;
        foreach (var instruction in instructions)
        {
            if (instruction.opcode == OpCodes.Call && Equals(instruction.operand, godotTicks))
            {
                instruction.operand = managedTicks;
            }
            yield return instruction;
        }
    }

    private static ulong GetManagedTicksMsec() => checked((ulong)Environment.TickCount64);

    private static bool SkipGodotEditorProbe(ref bool __result)
    {
        __result = false;
        return false;
    }

    private static bool SkipHeadlessCardSelectionLog() => false;

    private static void SetField(object target, string fieldName, object value)
    {
        var field = target.GetType().GetField(
            fieldName,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException($"{target.GetType().FullName}.{fieldName} is missing from the engine contract.");
        field.SetValue(target, value);
    }

    private static void AssertGrowthCheckpoint(
        Creature owner,
        int expectedGrowth,
        int expectedMaxHp,
        int expectedCurrentHp)
    {
        AcceptanceAssert.Equal(expectedGrowth, InfiniteDimensionality.GetAmount(owner), $"Growth must remain uncapped at {expectedGrowth} applications.");
        AcceptanceAssert.Equal(expectedMaxHp, owner.MaxHp, $"Max HP must remain uncapped at {expectedGrowth} applications.");
        AcceptanceAssert.Equal(expectedCurrentHp, owner.CurrentHp, $"Current HP must grow equally at {expectedGrowth} applications.");
    }

    private static T MakeMutableForEngineContract<T>(T model)
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

    private static void TryUnsubscribe(object stateTracker, object trackedObject)
    {
        var unsubscribe = stateTracker.GetType()
            .GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            .Where(method => method.Name == "Unsubscribe" && method.GetParameters().Length == 1)
            .FirstOrDefault(method => method.GetParameters()[0].ParameterType.IsInstanceOfType(trackedObject));
        unsubscribe?.Invoke(stateTracker, [trackedObject]);
    }

    private static string DescribeCard(CardModel card) =>
        $"{card.GetType().Name}[clone={card.IsClone}, cloneOf={card.CloneOf?.GetType().Name ?? "null"}]";

    private static MethodInfo DeclaredEffect(Type cardType) =>
        cardType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
            .Single(method => method.Name == "OnPlayAfterLifePayment");

    private sealed class DimensionUpCardSourceProbe : PowerModel
    {
        public override PowerType Type => PowerType.Buff;
        public override PowerStackType StackType => PowerStackType.Single;

        public List<CardModel?> CardSources { get; } = [];

        public override Task AfterPowerAmountChanged(
            PlayerChoiceContext choiceContext,
            PowerModel power,
            decimal delta,
            Creature? applier,
            CardModel? cardSource)
        {
            if (power is InfiniteDimensionalityPower &&
                delta > 0 &&
                ReferenceEquals(power.Owner, Owner))
            {
                CardSources.Add(cardSource);
            }

            return Task.CompletedTask;
        }
    }

    private sealed class CallbackDisposable(Action callback) : IDisposable
    {
        private Action? _callback = callback;

        public void Dispose()
        {
            Interlocked.Exchange(ref _callback, null)?.Invoke();
        }
    }
}
