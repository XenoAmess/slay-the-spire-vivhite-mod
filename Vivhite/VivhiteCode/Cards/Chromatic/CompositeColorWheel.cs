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
public sealed class CompositeColorWheel : ChromaticCard
{
    public CompositeColorWheel()
        : base(2, CardType.Attack, CardRarity.Common, TargetType.AllEnemies, 3)
    {
    }

    protected override IEnumerable<CardKeyword> ChromaticKeywords =>
        [VivhiteKeywords.Drain];

    protected override IEnumerable<DynamicVar> ChromaticVars =>
    [
        ModCardVars.Damage(10, ValueProp.Move),
        ModCardVars.Int("Drain", 25)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await DrainAllAsync(choiceContext, cardPlay, IntVar("Drain"));
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(3);
        DynamicVars["Drain"].UpgradeValueBy(5);
    }
}
