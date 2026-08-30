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
public sealed class DefiniteCrimsonIntegral : ChromaticCard
{
    public DefiniteCrimsonIntegral()
        : base(2, CardType.Attack, CardRarity.Rare, TargetType.AnyEnemy, 6)
    {
    }

    protected override IEnumerable<CardKeyword> ChromaticKeywords =>
        [VivhiteKeywords.Drain];

    protected override IEnumerable<DynamicVar> ChromaticVars =>
    [
        ModCardVars.Damage(32, ValueProp.Move),
        ModCardVars.Int("Drain", 60)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await DrainTargetAsync(choiceContext, cardPlay, IntVar("Drain"));
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(10);
        DynamicVars["Drain"].UpgradeValueBy(15);
    }
}
