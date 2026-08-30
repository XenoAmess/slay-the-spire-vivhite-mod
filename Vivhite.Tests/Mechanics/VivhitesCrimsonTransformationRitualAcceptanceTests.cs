using System.Reflection;
using System.Runtime.CompilerServices;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Powers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.ValueProps;
using Vivhite.Cards.Basics;
using Vivhite.Cards.Common;
using Vivhite.Cards.Hybrid;
using Vivhite.Core;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class VivhitesCrimsonTransformationRitualAcceptanceTests
{
    public static void CardAndPowerContract(RepositorySnapshot repository)
    {
        var card = new VivhitesCrimsonTransformationRitual();
        AcceptanceAssert.Equal(0, card.EnergyCost.Canonical, "The ritual must cost zero Energy.");
        AcceptanceAssert.Equal(CardType.Power, card.Type, "The ritual must be a Power card.");
        AcceptanceAssert.Equal(CardRarity.Rare, card.Rarity, "The ritual must be Rare.");
        AcceptanceAssert.True(
            card.CanonicalKeywords.Contains(VivhiteKeywords.LifeCalculation),
            "The zero-self-cost ritual must still expose the Life Calculation keyword hover tip granted to Attacks.");
        AcceptanceAssert.Equal(
            "VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL",
            repository.CardId(typeof(VivhitesCrimsonTransformationRitual)),
            "The generated full card ID must remain stable.");

        var normal = new VivhitesCrimsonTransformationRitualPower();
        var upgraded = new VivhitesCrimsonTransformationRitualUpgradedPower();
        AcceptanceAssert.Equal(
            PowerInstanceType.Instanced,
            normal.InstanceType,
            "Every normal ritual copy must keep an independent phase.");
        AcceptanceAssert.Equal(
            PowerInstanceType.Instanced,
            upgraded.InstanceType,
            "Every upgraded ritual copy must keep an independent phase.");
    }

    public static void UnboundedPhasesAddLifeCostAndPercentages()
    {
        var phaseZero = VivhitesCrimsonTransformationRitualMechanics.Calculate(
            [new CrimsonRitualStage(0, 10)]);
        AcceptanceAssert.Equal(0, phaseZero.ExtraLifeCost, "The play turn must remain phase zero.");
        AcceptanceAssert.Equal(0m, phaseZero.DamagePercent, "Phase zero must add zero damage.");
        AcceptanceAssert.Equal(1m, phaseZero.DamageMultiplier, "Phase zero must use a neutral multiplier.");

        var nextTurnPhase = VivhitesCrimsonTransformationRitualMechanics.AdvancePhase(
            phase: 0,
            lastTurnNumber: 7,
            currentTurnNumber: 8);
        AcceptanceAssert.Equal(1, nextTurnPhase, "The first turn start after play must advance phase zero to one.");
        var nextTurn = VivhitesCrimsonTransformationRitualMechanics.Calculate(
            [new CrimsonRitualStage(nextTurnPhase, 10)]);
        AcceptanceAssert.Equal(1, nextTurn.ExtraLifeCost, "Phase one must add exactly one Life Calculation.");
        AcceptanceAssert.Equal(10m, nextTurn.DamagePercent, "A normal phase one must add exactly ten percent damage.");

        var upgradedNextTurn = VivhitesCrimsonTransformationRitualMechanics.Calculate(
            [new CrimsonRitualStage(nextTurnPhase, 15)]);
        AcceptanceAssert.Equal(1, upgradedNextTurn.ExtraLifeCost, "Upgrade must not change phase-one Life Calculation.");
        AcceptanceAssert.Equal(15m, upgradedNextTurn.DamagePercent, "An upgraded phase one must add fifteen percent damage.");

        var stacked = VivhitesCrimsonTransformationRitualMechanics.Calculate(
        [
            new CrimsonRitualStage(3, 10),
            new CrimsonRitualStage(2, 15)
        ]);
        AcceptanceAssert.Equal(5, stacked.ExtraLifeCost, "Independent phases must add their extra life costs.");
        AcceptanceAssert.Equal(60m, stacked.DamagePercent, "Normal and upgraded percentages must add as points.");
        AcceptanceAssert.Equal(1.6m, stacked.DamageMultiplier, "Stacked rituals must not compound with one another.");

        var thousand = VivhitesCrimsonTransformationRitualMechanics.Calculate(
        [
            new CrimsonRitualStage(1_000, 10),
            new CrimsonRitualStage(1_000, 15)
        ]);
        AcceptanceAssert.Equal(2_000, thousand.ExtraLifeCost, "Phase growth must continue at 1,000-scale input.");
        AcceptanceAssert.Equal(25_000m, thousand.DamagePercent, "Damage growth must continue without a custom cap.");
        AcceptanceAssert.Equal(251m, thousand.DamageMultiplier, "Unbounded percentage points must remain fully effective.");
    }

    public static void CombinedGateIncludesPrintedAndRitualLifeCost()
    {
        var attack = new LuminousProjection();
        var ritual = VivhitesCrimsonTransformationRitualMechanics.Calculate(
            [new CrimsonRitualStage(3, 10)]);
        var combined = VivhitesCrimsonTransformationRitualMechanics.GetCombinedLifeCost(
            attack,
            ritual.ExtraLifeCost);
        AcceptanceAssert.Equal(4, combined, "Printed Life Calculation 1 and ritual phase 3 must gate as a total of 4.");

        var blocked = LifeCalculation.Calculate(
            currentHp: 4,
            marginAvailable: 0,
            payerIsAlive: true,
            amount: combined);
        AcceptanceAssert.True(!blocked.CanPay, "The combined gate must reject a payment that would reduce HP below one.");

        var payable = LifeCalculation.Calculate(
            currentHp: 5,
            marginAvailable: 0,
            payerIsAlive: true,
            amount: combined);
        AcceptanceAssert.True(payable.CanPay, "The combined gate must allow the same total while exactly one HP remains.");
    }

    public static void GlobalPowerHookCoversAttacksCreatedAfterApplication()
    {
        var player = (Player)RuntimeHelpers.GetUninitializedObject(typeof(Player));
        var owner = CreateCreatureWithPowerStorage(currentHp: 50, maxHp: 50, enemy: false);
        EngineTestObjects.SetAutoProperty(owner, "Player", player);
        EngineTestObjects.SetAutoProperty(player, "Creature", owner);

        var normal = (VivhitesCrimsonTransformationRitualPower)
            new VivhitesCrimsonTransformationRitualPower().ToMutable();
        normal.ApplyInternal(owner, 1);
        normal.DynamicVars["Phase"].BaseValue = 1;

        // Both cards are cloned for the owner only after the global Power already exists. This
        // models a later draw and a later generated copy without registering either card in a
        // hand snapshot owned by the ritual.
        var laterDrawnAttack = MakeMutableForEngineContract(new LuminousProjection());
        laterDrawnAttack.GiveToAnotherPlayer(player);
        var laterGeneratedAttack = MakeMutableForEngineContract(new LuminousProjection());
        laterGeneratedAttack.GiveToAnotherPlayer(player);
        var target = CreateCreatureWithPowerStorage(currentHp: 20, maxHp: 20, enemy: true);

        var drawnMultiplier = normal.ModifyDamageMultiplicative(
            target,
            10,
            ValueProp.Move,
            owner,
            laterDrawnAttack,
            cardPlay: null);
        var generatedMultiplier = normal.ModifyDamageMultiplicative(
            target,
            10,
            ValueProp.Move,
            owner,
            laterGeneratedAttack,
            cardPlay: null);
        AcceptanceAssert.Equal(1.1m, drawnMultiplier, "An Attack drawn after application must use the live global hook.");
        AcceptanceAssert.Equal(1.1m, generatedMultiplier, "An Attack generated after application must use the live global hook.");

        var upgraded = (VivhitesCrimsonTransformationRitualUpgradedPower)
            new VivhitesCrimsonTransformationRitualUpgradedPower().ToMutable();
        upgraded.ApplyInternal(owner, 1);
        upgraded.DynamicVars["Phase"].BaseValue = 2;
        AcceptanceAssert.Equal(
            1.4m,
            normal.ModifyDamageMultiplicative(
                target,
                10,
                ValueProp.Move,
                owner,
                laterGeneratedAttack,
                cardPlay: null),
            "The leader hook must add normal phase 1 (10%) and upgraded phase 2 (30%) once.");
        AcceptanceAssert.Equal(
            1m,
            upgraded.ModifyDamageMultiplicative(
                target,
                10,
                ValueProp.Move,
                owner,
                laterGeneratedAttack,
                cardPlay: null),
            "A non-leader ritual instance must not apply a second multiplier.");
    }

    public static void RuntimeUsesTheSharedPaymentGateAndEveryPrintedBaseCost(
        RepositorySnapshot repository)
    {
        var powerType = typeof(VivhitesCrimsonTransformationRitualPowerBase);
        var shouldPlay = RequireDeclaredMethod(powerType, nameof(CardModel.ShouldPlay));
        var beforePlayed = RequireDeclaredMethod(powerType, nameof(CardModel.BeforeCardPlayed));
        var damageModifier = RequireDeclaredMethod(powerType, nameof(CardModel.ModifyDamageMultiplicative));

        AcceptanceAssert.True(
            IlInspection.CalledMethods(shouldPlay).Any(method =>
                method.DeclaringType == typeof(LifeCalculation) &&
                method.Name == nameof(LifeCalculation.CanPay)),
            "The aggregate ritual gate must quote the combined printed and ritual life cost through LifeCalculation.CanPay.");
        AcceptanceAssert.True(
            IlInspection.CalledMethods(beforePlayed).Any(method =>
                method.DeclaringType == typeof(VivhiteCardRules) &&
                method.Name == nameof(VivhiteCardRules.PayThenAsync)),
            "The pre-effect ritual payment must use VivhiteCardRules.PayThenAsync so Margin and cross-suit observers stay unified.");
        AcceptanceAssert.True(
            IlInspection.CalledMethods(damageModifier).Any(method =>
                method.DeclaringType == typeof(VivhitesCrimsonTransformationRitualMechanics) &&
                method.Name == nameof(VivhitesCrimsonTransformationRitualMechanics.GetTotals)),
            "The one damage hook must aggregate all live ritual instances before returning its multiplier.");

        var mismatches = new List<string>();
        foreach (var cardType in repository.VivhitePoolCards.Where(type =>
                     type.IsAssignableTo(typeof(VivhiteLifeCalculationCard))))
        {
            if (Activator.CreateInstance(cardType) is not CardModel card ||
                card.Type != CardType.Attack)
            {
                continue;
            }

            var costProperty = FindLifeCostProperty(cardType);
            var runtimeCost = (int)costProperty.GetValue(card)!;
            var printedCost =
                VivhitesCrimsonTransformationRitualMechanics.GetPrintedLifeCost(card);
            if (runtimeCost != printedCost)
            {
                mismatches.Add($"{repository.CardId(cardType)}: runtime {runtimeCost}, printed {printedCost}");
            }
        }

        AcceptanceAssert.Empty(
            mismatches,
            "Every Vivhite Attack's printed LifeCost must match its runtime base payment so the ritual can gate their exact combined cost:");
    }

    private static MethodInfo RequireDeclaredMethod(Type type, string name)
    {
        return type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
            .Single(method => method.Name == name);
    }

    private static PropertyInfo FindLifeCostProperty(Type type)
    {
        for (var cursor = type; cursor is not null; cursor = cursor.BaseType)
        {
            var property = cursor.GetProperty(
                "LifeCalculationCost",
                BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
            if (property is not null)
            {
                return property;
            }
        }

        throw new AcceptanceFailureException($"{type.FullName} has no LifeCalculationCost property.");
    }

    private static Creature CreateCreatureWithPowerStorage(
        int currentHp,
        int maxHp,
        bool enemy)
    {
        var creature = EngineTestObjects.CreateCreature(currentHp, maxHp, enemy);
        var powers = typeof(Creature).GetField(
            "_powers",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("Creature._powers was not found.");
        powers.SetValue(creature, new List<PowerModel>());
        return creature;
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

#if RITUAL_COMPONENT_TEST
    public static int Main()
    {
        try
        {
            var repository = RepositorySnapshot.Load();
            CardAndPowerContract(repository);
            UnboundedPhasesAddLifeCostAndPercentages();
            CombinedGateIncludesPrintedAndRitualLifeCost();
            GlobalPowerHookCoversAttacksCreatedAfterApplication();
            RuntimeUsesTheSharedPaymentGateAndEveryPrintedBaseCost(repository);
            Console.WriteLine("[PASS] ritual card and independent Power contract");
            Console.WriteLine("[PASS] ritual phases add uncapped life cost and percentage points");
            Console.WriteLine("[PASS] ritual gate combines printed and global life costs");
            Console.WriteLine("[PASS] global ritual hook covers later drawn and generated Attacks");
            Console.WriteLine("[PASS] ritual runtime uses shared payment and exact printed base costs");
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"[FAIL] {exception.GetBaseException()}");
            return 1;
        }
    }
#endif
}
