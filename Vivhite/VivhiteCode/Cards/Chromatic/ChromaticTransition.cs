using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using STS2RitsuLib.Cards.DynamicVars;
using STS2RitsuLib.Interop.AutoRegistration;
using Vivhite.Cards.Common;
using Vivhite.Characters;
using Vivhite.Core;

namespace Vivhite.Cards.Chromatic;

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class ChromaticTransition : ChromaticCard
{
    public ChromaticTransition()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self, 4)
    {
    }

    protected override IEnumerable<CardKeyword> ChromaticKeywords =>
        [VivhiteKeywords.Drain, CardKeyword.Exhaust];

    protected override IEnumerable<DynamicVar> ChromaticVars =>
        [ModCardVars.Int("Drain", 8)];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await InfiniteDrain.GainGlobalPercentAsync(
            choiceContext,
            Owner.Creature,
            IntVar("Drain"),
            Owner.Creature,
            this);
        await CardPileCmd.Draw(choiceContext, 2, Owner, false);
    }

    protected override void OnUpgrade()
    {
        DynamicVars["Drain"].UpgradeValueBy(4);
    }
}
