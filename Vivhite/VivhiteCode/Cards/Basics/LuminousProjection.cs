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

namespace Vivhite.Cards.Basics;

[RegisterCard(typeof(VivhiteCardPool))]
[RegisterCharacterStarterCard(typeof(VivhiteCharacter), 4)]
public sealed class LuminousProjection : VivhiteLifeCalculationCard
{
    public override string CustomPortraitPath =>
        $"{Entry.ResPath}/images/cards/LuminousProjection.png";

    public LuminousProjection()
        : base(1, CardType.Attack, CardRarity.Basic, TargetType.AnyEnemy)
    {
    }

    protected override int LifeCalculationCost => 2;

    protected override IEnumerable<DynamicVar> CanonicalVars =>
    [
        ModCardVars.Int("LifeCost", 2),
        ModCardVars.Damage(10, ValueProp.Move)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);

        var attack = DamageCmd.Attack(DynamicVars.Damage.BaseValue)
            .FromCard(this, cardPlay)
            .Targeting(cardPlay.Target);
        await VivhiteCardRules.ExecuteAttackWithGlobalDrainAsync(
            choiceContext,
            attack,
            this,
            cardPlay);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(4);
    }
}
