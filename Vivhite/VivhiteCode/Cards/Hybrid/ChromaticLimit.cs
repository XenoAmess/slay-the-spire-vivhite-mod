using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.ValueProps;
using STS2RitsuLib.Cards.DynamicVars;
using STS2RitsuLib.Interop.AutoRegistration;
using Vivhite.Cards.Common;
using Vivhite.Characters;
using Vivhite.Core;

namespace Vivhite.Cards.Hybrid;

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class ChromaticLimit : VivhiteLifeCalculationCard
{
    public ChromaticLimit()
        : base(0, CardType.Attack, CardRarity.Rare, TargetType.AnyEnemy)
    {
    }

    protected override bool HasEnergyCostX => true;

    protected override int LifeCalculationCost => 4;

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Drain, VivhiteKeywords.Margin];

    protected override IEnumerable<DynamicVar> CanonicalVars =>
    [
        ModCardVars.Int("LifeCost", 4),
        ModCardVars.Damage(9, ValueProp.Move),
        ModCardVars.Int("DrainPerX", 15),
        ModCardVars.Int("HealingPerMargin", 10)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);

        var x = ResolveEnergyXValue();
        var attack = DamageCmd.Attack(DynamicVars.Damage.BaseValue)
            .WithHitCount(x)
            .FromCard(this, cardPlay)
            .Targeting(cardPlay.Target);
        var drain = await VivhiteCardRules.ExecuteDrainAttackAsync(
            choiceContext,
            attack,
            this,
            cardPlay,
            x * IntVar("DrainPerX"));

        var margin = drain.ActualHealing / IntVar("HealingPerMargin");
        if (margin > 0)
        {
            await InfiniteMargin.GainAsync(
                choiceContext,
                Owner.Creature,
                margin,
                Owner.Creature,
                this);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(3);
        DynamicVars["DrainPerX"].UpgradeValueBy(5);
    }
}
