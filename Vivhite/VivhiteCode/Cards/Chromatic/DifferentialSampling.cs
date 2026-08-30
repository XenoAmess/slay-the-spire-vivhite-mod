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
public sealed class DifferentialSampling : ChromaticCard
{
    public DifferentialSampling()
        : base(0, CardType.Attack, CardRarity.Common, TargetType.AnyEnemy, 1)
    {
    }

    protected override IEnumerable<CardKeyword> ChromaticKeywords =>
        [VivhiteKeywords.Drain];

    protected override IEnumerable<DynamicVar> ChromaticVars =>
    [
        ModCardVars.Damage(3, ValueProp.Move),
        ModCardVars.Int("Drain", 10)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await DrainTargetAsync(choiceContext, cardPlay, IntVar("Drain"), 2);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(1);
        DynamicVars["Drain"].UpgradeValueBy(5);
    }
}
