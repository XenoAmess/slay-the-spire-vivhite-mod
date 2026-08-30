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

/// <summary>
/// Starts an independently advancing ritual at phase zero. The power owns all turn-to-turn
/// behavior so attacks drawn or generated after this card resolves participate automatically.
/// </summary>
[RegisterCard(typeof(VivhiteCardPool))]
public sealed class VivhitesCrimsonTransformationRitual : VivhiteLifeCalculationCard
{
    public VivhitesCrimsonTransformationRitual()
        : base(0, CardType.Power, CardRarity.Rare, TargetType.Self)
    {
    }

    protected override int LifeCalculationCost => 0;

    // The card itself pays zero, but it grants an effect that makes every later Attack pay
    // Life Calculation. Keep the keyword hover tip visible so that contract is discoverable.
    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.LifeCalculation];

    protected override IEnumerable<DynamicVar> CanonicalVars =>
    [
        ModCardVars.Int("LifeCostPerPhase", 1),
        ModCardVars.Int("DamagePercentPerPhase", 10)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        if (IsUpgraded)
        {
            await PowerCmd.Apply<VivhitesCrimsonTransformationRitualUpgradedPower>(
                choiceContext,
                Owner.Creature,
                1,
                Owner.Creature,
                this);
            return;
        }

        await PowerCmd.Apply<VivhitesCrimsonTransformationRitualPower>(
            choiceContext,
            Owner.Creature,
            1,
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        DynamicVars["DamagePercentPerPhase"].UpgradeValueBy(5);
    }
}
