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
public sealed class UnifiedFieldTheory : VivhiteLifeCalculationCard
{
    public UnifiedFieldTheory()
        : base(3, CardType.Power, CardRarity.Rare, TargetType.Self)
    {
    }

    protected override int LifeCalculationCost => IntVar("LifeCost");

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin, VivhiteKeywords.Drain];

    protected override IEnumerable<DynamicVar> CanonicalVars =>
    [
        ModCardVars.Int("LifeCost", 14),
        ModCardVars.Int("DrainPerMargin", 4),
        ModCardVars.Int("HealingDivisor", 3)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        if (IsUpgraded)
        {
            await PowerCmd.Apply<UnifiedFieldTheoryUpgradedPower>(
                choiceContext,
                Owner.Creature,
                1,
                Owner.Creature,
                this);
            return;
        }

        await PowerCmd.Apply<UnifiedFieldTheoryPower>(
            choiceContext,
            Owner.Creature,
            1,
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        DynamicVars["HealingDivisor"].UpgradeValueBy(-1);
    }
}
