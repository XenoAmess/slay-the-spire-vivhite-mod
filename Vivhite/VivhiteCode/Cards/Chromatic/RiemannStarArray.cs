using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.ValueProps;
using STS2RitsuLib.Cards.DynamicVars;
using STS2RitsuLib.Interop.AutoRegistration;
using Vivhite.Cards.Common;
using Vivhite.Characters;
using Vivhite.Core;

namespace Vivhite.Cards.Chromatic;

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class RiemannStarArray : ChromaticCard
{
    public RiemannStarArray()
        : base(1, CardType.Attack, CardRarity.Uncommon, TargetType.AnyEnemy, 6)
    {
    }

    protected override IEnumerable<CardKeyword> ChromaticKeywords =>
        [VivhiteKeywords.Drain];

    protected override IEnumerable<DynamicVar> ChromaticVars =>
    [
        ModCardVars.Damage(4, ValueProp.Move),
        ModCardVars.Int("Drain", 3)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var hand = CardPile.Get(PileType.Hand, Owner) ??
            throw new InvalidOperationException("Riemann Star Array requires an active hand pile.");
        var handCount = hand.Cards.Count;
        await DrainTargetAsync(
            choiceContext,
            cardPlay,
            IntVar("Drain"),
            handCount);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(1);
        DynamicVars["Drain"].UpgradeValueBy(1);
    }
}
