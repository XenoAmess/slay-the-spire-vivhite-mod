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
public sealed class ChromaticSequence : VivhiteLifeCalculationCard
{
    public ChromaticSequence()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self)
    {
    }

    protected override int LifeCalculationCost => 4;

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Margin, VivhiteKeywords.Drain];

    protected override IEnumerable<DynamicVar> CanonicalVars =>
    [
        ModCardVars.Int("LifeCost", 4),
        ModCardVars.Cards(2),
        ModCardVars.Int("MarginPerAttack", 1),
        ModCardVars.Int("DrainPerSkill", 1)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var drawn = (await CardPileCmd.Draw(
                choiceContext,
                DynamicVars.Cards.BaseValue,
                Owner,
                false))
            .ToArray();

        var attacks = drawn.Count(card => card.Type == CardType.Attack);
        var skills = drawn.Count(card => card.Type == CardType.Skill);
        var powers = drawn.Count(card => card.Type == CardType.Power);
        var margin = (attacks + powers) * IntVar("MarginPerAttack");
        var drain = (skills + powers) * IntVar("DrainPerSkill");

        if (margin > 0)
        {
            await InfiniteMargin.GainAsync(
                choiceContext,
                Owner.Creature,
                margin,
                Owner.Creature,
                this);
        }

        if (drain > 0)
        {
            await InfiniteDrain.GainThisTurnPercentAsync(
                choiceContext,
                Owner.Creature,
                drain,
                Owner.Creature,
                this);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Cards.UpgradeValueBy(1);
    }
}
