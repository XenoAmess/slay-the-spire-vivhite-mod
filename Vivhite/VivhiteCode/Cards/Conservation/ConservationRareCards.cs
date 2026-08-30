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
public sealed class ClosedManifold : ConservationCard
{
    public ClosedManifold()
        : base(2, CardType.Power, CardRarity.Rare, TargetType.Self, 5)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await PowerCmd.Apply<ClosedManifoldPower>(
            choiceContext,
            Owner.Creature,
            1,
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        EnergyCost.UpgradeBy(-1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class AxiomOfLife : ConservationCard
{
    private const string MaxHpVar = "MaxHp";
    private const string EnglishDimensionUpAliasVar = "DimensionUp";

    public AxiomOfLife()
        : base(2, CardType.Attack, CardRarity.Rare, TargetType.AnyEnemy, 5)
    {
    }

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new DamageVar(24, ValueProp.Move),
        new IntVar(MaxHpVar, 4),
        new IntVar(EnglishDimensionUpAliasVar, 4)
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
                DynamicVars[MaxHpVar].IntValue,
                Owner.Creature,
                this);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(8);
        DynamicVars[MaxHpVar].UpgradeValueBy(1);
        DynamicVars[EnglishDimensionUpAliasVar].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class InfiniteExtension : ConservationCard
{
    public InfiniteExtension()
        : base(3, CardType.Power, CardRarity.Rare, TargetType.Self, 6)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.DimensionUp];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await Vivhite.Core.InfiniteExtension.ApplyAsync(
            choiceContext,
            Owner.Creature,
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        EnergyCost.UpgradeBy(-1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class ConservationFirmament : ConservationCard
{
    private const string BlockMultiplierVar = "BlockMultiplier";
    private const string EnglishMultiplierAliasVar = "Multiplier";

    public ConservationFirmament()
        : base(2, CardType.Skill, CardRarity.Rare, TargetType.Self, 5)
    {
    }

    public override bool GainsBlock => true;

    protected override IEnumerable<DynamicVar> ConservationVars =>
    [
        new IntVar(BlockMultiplierVar, 2),
        new IntVar(EnglishMultiplierAliasVar, 2)
    ];

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin, CardKeyword.Exhaust];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var marginBeforeDoubling = InfiniteMargin.GetAmount(Owner.Creature);
        if (marginBeforeDoubling > 0)
        {
            await GainMarginAsync(choiceContext, marginBeforeDoubling);
        }

        var doubledMargin = InfiniteMargin.GetAmount(Owner.Creature);
        var block = (decimal)doubledMargin * DynamicVars[BlockMultiplierVar].BaseValue;
        if (block > 0)
        {
            await GainBlockAsync(block, cardPlay);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars[BlockMultiplierVar].UpgradeValueBy(1);
        DynamicVars[EnglishMultiplierAliasVar].UpgradeValueBy(1);
    }
}
