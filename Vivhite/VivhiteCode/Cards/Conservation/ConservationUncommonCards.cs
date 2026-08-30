using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.ValueProps;
using STS2RitsuLib.Interop.AutoRegistration;
using Vivhite.Cards.Common;
using Vivhite.Characters;
using Vivhite.Core;

namespace Vivhite.Cards.Conservation;

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class IsoperimetricWard : ConservationCard
{
    private const string BaseBlockVar = "BaseBlock";
    private const string BlockPerMarginVar = "BlockPerMargin";
    private const string EnglishBlockAliasVar = "Block";
    private const string EnglishMultiplierAliasVar = "Multiplier";

    public IsoperimetricWard()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self, 2)
    {
    }

    public override bool GainsBlock => true;

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new BlockVar(BaseBlockVar, 12, ValueProp.Move),
        new IntVar(BlockPerMarginVar, 2),
        // Compatibility aliases for the current English localization. Gameplay uses the
        // semantic BaseBlock and BlockPerMargin variables above.
        new BlockVar(EnglishBlockAliasVar, 12, ValueProp.Move),
        new IntVar(EnglishMultiplierAliasVar, 2)
    ];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin];

    protected override Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var block = DynamicVars[BaseBlockVar].BaseValue +
                    InfiniteMargin.GetAmount(Owner.Creature) *
                    DynamicVars[BlockPerMarginVar].BaseValue;
        return GainBlockAsync(block, cardPlay);
    }

    protected override void OnUpgrade()
    {
        DynamicVars[BaseBlockVar].UpgradeValueBy(4);
        DynamicVars[BlockPerMarginVar].UpgradeValueBy(1);
        DynamicVars[EnglishBlockAliasVar].UpgradeValueBy(4);
        DynamicVars[EnglishMultiplierAliasVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class TopologicalGrowth : ConservationCard
{
    private const string MaxHpVar = "MaxHp";
    private const string EnglishDimensionUpAliasVar = "DimensionUp";
    private const string MarginVar = "Margin";

    public TopologicalGrowth()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self, 4)
    {
    }

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new IntVar(MaxHpVar, 1),
        new IntVar(EnglishDimensionUpAliasVar, 1),
        new IntVar(MarginVar, 3)
    ];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.DimensionUp, VivhiteKeywords.Margin, CardKeyword.Exhaust];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await DimensionUp.ApplyAsync(
            choiceContext,
            Owner.Creature,
            DynamicVars[MaxHpVar].IntValue,
            Owner.Creature,
            this);
        await GainMarginAsync(choiceContext, DynamicVars[MarginVar].IntValue);
    }

    protected override void OnUpgrade()
    {
        DynamicVars[MaxHpVar].UpgradeValueBy(1);
        DynamicVars[EnglishDimensionUpAliasVar].UpgradeValueBy(1);
        DynamicVars[MarginVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class LawOfConservation : ConservationCard
{
    private const string BlockPerMarginVar = "BlockPerMargin";
    private const string EnglishPowerAliasVar = "Power";

    public LawOfConservation()
        : base(1, CardType.Power, CardRarity.Uncommon, TargetType.Self, 3)
    {
    }

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new IntVar(BlockPerMarginVar, 1),
        new IntVar(EnglishPowerAliasVar, 1)
    ];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await PowerCmd.Apply<LawOfConservationPower>(
            choiceContext,
            Owner.Creature,
            DynamicVars[BlockPerMarginVar].BaseValue,
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        DynamicVars[BlockPerMarginVar].UpgradeValueBy(1);
        DynamicVars[EnglishPowerAliasVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class LifeManifold : ConservationCard
{
    private const string MarginVar = "Margin";

    public LifeManifold()
        : base(2, CardType.Power, CardRarity.Uncommon, TargetType.Self, 4)
    {
    }

    protected override IEnumerable<DynamicVar> ConservationVars =>
        [new IntVar(MarginVar, 2)];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await PowerCmd.Apply<LifeManifoldPower>(
            choiceContext,
            Owner.Creature,
            DynamicVars[MarginVar].BaseValue,
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        DynamicVars[MarginVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class MobiusLoop : ConservationCard
{
    public MobiusLoop()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self, 2)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [CardKeyword.Exhaust];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var discardPile = CardPile.Get(PileType.Discard, Owner);
        if (discardPile is null ||
            !discardPile.Cards.Any(static card => card.Type == CardType.Skill))
        {
            return;
        }

        var selectedCards = await CardSelectCmd.FromCombatPile(
            choiceContext,
            discardPile,
            Owner,
            new CardSelectorPrefs(SelectionScreenPrompt, 1),
            static card => card.Type == CardType.Skill);
        var selected = selectedCards.SingleOrDefault();
        if (selected is null)
        {
            return;
        }

        await CardPileCmd.Add(
            selected,
            PileType.Hand,
            CardPilePosition.Top,
            this);
        selected.SetToFreeThisTurn();
    }

    protected override void OnUpgrade()
    {
        EnergyCost.UpgradeBy(-1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class Invariant : ConservationCard
{
    private const string MarginVar = "Margin";

    public Invariant()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self, 1)
    {
    }

    public override bool GainsBlock => true;

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new BlockVar(10, ValueProp.Move),
        new IntVar(MarginVar, 3)
    ];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await CreatureCmd.GainBlock(Owner.Creature, DynamicVars.Block, cardPlay);
        if (InfiniteDimensionality.GetAmount(Owner.Creature) > 0)
        {
            await GainMarginAsync(choiceContext, DynamicVars[MarginVar].IntValue);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Block.UpgradeValueBy(4);
        DynamicVars[MarginVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class GeodesicVeil : ConservationCard
{
    public GeodesicVeil()
        : base(2, CardType.Skill, CardRarity.Uncommon, TargetType.Self, 3)
    {
    }

    public override bool GainsBlock => true;

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [CardKeyword.Retain];

    protected override IEnumerable<DynamicVar> ConservationVars =>
        [new BlockVar(24, ValueProp.Move)];

    protected override Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        return CreatureCmd.GainBlock(Owner.Creature, DynamicVars.Block, cardPlay);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Block.UpgradeValueBy(6);
    }
}
