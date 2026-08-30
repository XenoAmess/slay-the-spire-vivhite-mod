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
public sealed class ComplementaryAfterimage : ChromaticCard
{
    public ComplementaryAfterimage()
        : base(1, CardType.Attack, CardRarity.Uncommon, TargetType.AnyEnemy, 3)
    {
    }

    protected override IEnumerable<CardKeyword> ChromaticKeywords =>
        [VivhiteKeywords.Drain];

    protected override IEnumerable<DynamicVar> ChromaticVars =>
    [
        ModCardVars.Damage(12, ValueProp.Move),
        ModCardVars.Int("Drain", 20)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var hits = CurrentHpIncreasedThisTurn ? 2 : 1;
        await DrainTargetAsync(choiceContext, cardPlay, IntVar("Drain"), hits);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(3);
        DynamicVars["Drain"].UpgradeValueBy(5);
    }
}
