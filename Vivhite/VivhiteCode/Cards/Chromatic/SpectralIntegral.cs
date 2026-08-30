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
public sealed class SpectralIntegral : ChromaticCard
{
    public SpectralIntegral()
        : base(1, CardType.Power, CardRarity.Uncommon, TargetType.Self, 6)
    {
    }

    protected override IEnumerable<CardKeyword> ChromaticKeywords =>
        [VivhiteKeywords.Drain];

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
    }

    protected override void OnUpgrade()
    {
        DynamicVars["Drain"].UpgradeValueBy(4);
    }
}
