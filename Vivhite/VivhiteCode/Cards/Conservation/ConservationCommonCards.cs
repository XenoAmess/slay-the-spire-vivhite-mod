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
public sealed class AxiomRing : ConservationCard
{
    private const string MarginVar = "Margin";

    public AxiomRing()
        : base(0, CardType.Skill, CardRarity.Common, TargetType.Self, 0)
    {
    }

    protected override IEnumerable<DynamicVar> ConservationVars =>
        [new IntVar(MarginVar, 2)];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin];

    protected override Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        return GainMarginAsync(choiceContext, DynamicVars[MarginVar].IntValue);
    }

    protected override void OnUpgrade()
    {
        DynamicVars[MarginVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class ClosedProjection : ConservationCard
{
    private const string BlockPerMarginVar = "BlockPerMargin";

    public ClosedProjection()
        : base(1, CardType.Attack, CardRarity.Common, TargetType.AnyEnemy, 2)
    {
    }

    public override bool GainsBlock => true;

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new DamageVar(14, ValueProp.Move),
        new BlockVar(BlockPerMarginVar, 5, ValueProp.Move)
    ];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await AttackAsync(choiceContext, cardPlay);

        var block = payment.MarginConsumed * DynamicVars[BlockPerMarginVar].BaseValue;
        if (block > 0)
        {
            await GainBlockAsync(block, cardPlay);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(4);
        DynamicVars[BlockPerMarginVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class TangentStarlight : ConservationCard
{
    private const string MarginVar = "Margin";

    public TangentStarlight()
        : base(1, CardType.Attack, CardRarity.Common, TargetType.AnyEnemy, 1)
    {
    }

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new DamageVar(11, ValueProp.Move),
        new IntVar(MarginVar, 1)
    ];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await AttackAsync(choiceContext, cardPlay);
        await GainMarginAsync(choiceContext, DynamicVars[MarginVar].IntValue);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(4);
        DynamicVars[MarginVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class OpenSetShelter : ConservationCard
{
    private const string MarginVar = "Margin";

    public OpenSetShelter()
        : base(1, CardType.Skill, CardRarity.Common, TargetType.Self, 2)
    {
    }

    public override bool GainsBlock => true;

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new BlockVar(14, ValueProp.Move),
        new IntVar(MarginVar, 1)
    ];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await CreatureCmd.GainBlock(Owner.Creature, DynamicVars.Block, cardPlay);
        await GainMarginAsync(choiceContext, DynamicVars[MarginVar].IntValue);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Block.UpgradeValueBy(4);
        DynamicVars[MarginVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class LocalHomeomorphism : ConservationCard
{
    private const string MarginVar = "Margin";

    public LocalHomeomorphism()
        : base(1, CardType.Skill, CardRarity.Common, TargetType.Self, 1)
    {
    }

    public override bool GainsBlock => true;

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new BlockVar(8, ValueProp.Move),
        new IntVar(MarginVar, 2)
    ];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await CreatureCmd.GainBlock(Owner.Creature, DynamicVars.Block, cardPlay);
        await GainMarginAsync(choiceContext, DynamicVars[MarginVar].IntValue);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Block.UpgradeValueBy(3);
        DynamicVars[MarginVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class ScaleTransformation : ConservationCard
{
    private const string DimensionUpVar = "DimensionUp";

    public ScaleTransformation()
        : base(2, CardType.Attack, CardRarity.Common, TargetType.AnyEnemy, 3)
    {
    }

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new DamageVar(20, ValueProp.Move),
        new IntVar(DimensionUpVar, 1)
    ];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Lethal, VivhiteKeywords.DimensionUp, CardKeyword.Exhaust];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);
        var attack = await AttackAsync(choiceContext, cardPlay);
        if (DirectlyKilled(attack))
        {
            await DimensionUp.ApplyAsync(
                choiceContext,
                Owner.Creature,
                DynamicVars[DimensionUpVar].IntValue,
                Owner.Creature,
                this);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(6);
        DynamicVars[DimensionUpVar].UpgradeValueBy(1);
    }
}
