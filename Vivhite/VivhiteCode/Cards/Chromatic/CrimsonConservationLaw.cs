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
public sealed class CrimsonConservationLaw : ChromaticCard
{
    public CrimsonConservationLaw()
        : base(2, CardType.Power, CardRarity.Rare, TargetType.Self, 5)
    {
    }

    protected override IEnumerable<CardKeyword> ChromaticKeywords =>
        [VivhiteKeywords.Drain];

    protected override IEnumerable<DynamicVar> ChromaticVars =>
        [ModCardVars.Int("HealingStep", 5)];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        if (IsUpgraded)
        {
            await PowerCmd.Apply<CrimsonConservationLawUpgradedPower>(
                choiceContext,
                Owner.Creature,
                1,
                Owner.Creature,
                this);
            return;
        }

        await PowerCmd.Apply<CrimsonConservationLawPower>(
            choiceContext,
            Owner.Creature,
            1,
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        DynamicVars["HealingStep"].UpgradeValueBy(-1);
    }
}
