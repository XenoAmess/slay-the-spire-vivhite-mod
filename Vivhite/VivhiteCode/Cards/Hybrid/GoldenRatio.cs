using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using STS2RitsuLib.Cards.DynamicVars;
using STS2RitsuLib.Interop.AutoRegistration;
using Vivhite.Cards.Common;
using Vivhite.Characters;
using Vivhite.Core;

namespace Vivhite.Cards.Hybrid;

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class GoldenRatio : VivhiteLifeCalculationCard
{
    public GoldenRatio()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self)
    {
    }

    protected override int LifeCalculationCost => IntVar("LifeCost");

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin, VivhiteKeywords.Drain];

    protected override IEnumerable<DynamicVar> CanonicalVars =>
    [
        ModCardVars.Int("LifeCost", 4),
        ModCardVars.Int("Margin", 3),
        ModCardVars.Int("Drain", 12),
        ModCardVars.Cards(2)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await InfiniteMargin.GainAsync(
            choiceContext,
            Owner.Creature,
            IntVar("Margin"),
            Owner.Creature,
            this);
        await InfiniteDrain.GainThisTurnPercentAsync(
            choiceContext,
            Owner.Creature,
            IntVar("Drain"),
            Owner.Creature,
            this);
        await CardPileCmd.Draw(
            choiceContext,
            DynamicVars.Cards.BaseValue,
            Owner,
            false);
    }

    protected override void OnUpgrade()
    {
        DynamicVars["Margin"].UpgradeValueBy(1);
        DynamicVars["Drain"].UpgradeValueBy(4);
    }
}
