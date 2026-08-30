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

namespace Vivhite.Cards.Hybrid;

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class AstralMeasure : VivhiteCard
{
    public AstralMeasure()
        : base(1, CardType.Attack, CardRarity.Uncommon, TargetType.AnyEnemy)
    {
    }

    protected override IEnumerable<CardKeyword> VivhiteCanonicalKeywords =>
        [VivhiteKeywords.Margin, VivhiteKeywords.Drain];

    protected override IEnumerable<DynamicVar> CanonicalVars =>
    [
        ModCardVars.Damage(10, ValueProp.Move),
        ModCardVars.Int("DrainPerMargin", 4)
    ];

    protected override async Task OnPlay(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);

        // M is intentionally captured before any payment or effect. This card itself has no
        // Life Calculation cost, so the snapshot is never reduced by playing Astral Measure.
        var margin = InfiniteMargin.GetAmount(Owner.Creature);
        var attack = DamageCmd.Attack(DynamicVars.Damage.BaseValue + margin)
            .FromCard(this, cardPlay)
            .Targeting(cardPlay.Target);

        await VivhiteCardRules.ExecuteDrainAttackAsync(
            choiceContext,
            attack,
            this,
            cardPlay,
            margin * IntVar("DrainPerMargin"));
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(3);
        DynamicVars["DrainPerMargin"].UpgradeValueBy(4);
    }
}
