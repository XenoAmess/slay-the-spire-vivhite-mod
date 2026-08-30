using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Models.Powers;
using STS2RitsuLib.Cards.DynamicVars;
using STS2RitsuLib.Interop.AutoRegistration;
using Vivhite.Cards.Common;
using Vivhite.Characters;
using Vivhite.Core;

namespace Vivhite.Cards.Chromatic;

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class CompositeColorField : ChromaticCard
{
    public CompositeColorField()
        : base(2, CardType.Skill, CardRarity.Uncommon, TargetType.AllEnemies, 8)
    {
    }

    protected override IEnumerable<CardKeyword> ChromaticKeywords =>
        [VivhiteKeywords.Drain, CardKeyword.Exhaust];

    protected override IEnumerable<DynamicVar> ChromaticVars =>
    [
        new PowerVar<VulnerablePower>("VulnerablePower", 2),
        ModCardVars.Int("Drain", 8)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var combatState = CombatState ??
            throw new InvalidOperationException("Composite Color Field requires an active combat.");
        await PowerCmd.Apply<VulnerablePower>(
            choiceContext,
            combatState.GetOpponentsOf(Owner.Creature),
            DynamicVars["VulnerablePower"].BaseValue,
            Owner.Creature,
            this);
        await InfiniteDrain.GainGlobalPercentAsync(
            choiceContext,
            Owner.Creature,
            IntVar("Drain"),
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        DynamicVars["VulnerablePower"].UpgradeValueBy(1);
        DynamicVars["Drain"].UpgradeValueBy(4);
    }
}
