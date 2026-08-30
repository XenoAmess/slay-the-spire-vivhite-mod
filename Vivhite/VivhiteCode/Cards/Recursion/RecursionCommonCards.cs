using MegaCrit.Sts2.Core.CardSelection;
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

namespace Vivhite.Cards.Recursion;

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class RecurrentStarlight : RecursionCard
{
    public RecurrentStarlight()
        : base(1, CardType.Attack, CardRarity.Common, TargetType.AnyEnemy, 4)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Lethal];

    protected override IEnumerable<DynamicVar> RecursionVars =>
    [
        ModCardVars.Damage(13, ValueProp.Move),
        ModCardVars.Cards(2)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);
        var attack = await AttackTargetAsync(choiceContext, cardPlay);
        if (attack.Damage.EnemyKills > 0)
        {
            await DrawAsync(choiceContext, DynamicVars.Cards.BaseValue);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(4);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class TerminationCondition : RecursionCard
{
    public TerminationCondition()
        : base(1, CardType.Attack, CardRarity.Common, TargetType.AnyEnemy, 4)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Lethal];

    protected override IEnumerable<DynamicVar> RecursionVars =>
    [
        ModCardVars.Damage(12, ValueProp.Move),
        ModCardVars.Heal(5)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);
        var attack = await AttackTargetAsync(choiceContext, cardPlay);
        if (attack.Damage.EnemyKills > 0)
        {
            await Overheal.HealAsync(Owner.Creature, DynamicVars.Heal.IntValue);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(4);
        DynamicVars.Heal.UpgradeValueBy(3);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class ParallelStarfall : RecursionCard
{
    public ParallelStarfall()
        : base(1, CardType.Attack, CardRarity.Common, TargetType.AllEnemies, 6)
    {
    }

    protected override IEnumerable<DynamicVar> RecursionVars =>
    [
        ModCardVars.Damage(6, ValueProp.Move),
        ModCardVars.Repeat(2)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await AttackAllAsync(choiceContext, cardPlay, DynamicVars.Repeat.IntValue);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(2);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class AstralSearch : RecursionCard
{
    public AstralSearch()
        : base(0, CardType.Skill, CardRarity.Common, TargetType.Self, 2)
    {
    }

    protected override IEnumerable<DynamicVar> RecursionVars =>
        [ModCardVars.Cards(2)];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await DrawAsync(choiceContext, DynamicVars.Cards.BaseValue);

        var hand = Owner.PlayerCombatState?.Hand;
        if (hand is null || hand.IsEmpty)
        {
            return;
        }

        var selected = await CardSelectCmd.FromHandForDiscard(
            choiceContext,
            Owner,
            new CardSelectorPrefs(CardSelectorPrefs.DiscardSelectionPrompt, 1),
            static _ => true,
            this);
        await CardCmd.Discard(choiceContext, selected);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Cards.UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class HeuristicShield : RecursionCard
{
    public HeuristicShield()
        : base(1, CardType.Skill, CardRarity.Common, TargetType.Self, 2)
    {
    }

    public override bool GainsBlock => true;

    protected override IEnumerable<DynamicVar> RecursionVars =>
        [ModCardVars.Block(8, ValueProp.Move)];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await CreatureCmd.GainBlock(Owner.Creature, DynamicVars.Block, cardPlay);
        await DrawAsync(choiceContext, 1);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Block.UpgradeValueBy(3);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class SuccessorFormula : RecursionCard
{
    public SuccessorFormula()
        : base(0, CardType.Attack, CardRarity.Common, TargetType.AnyEnemy, 4)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Lethal];

    protected override IEnumerable<DynamicVar> RecursionVars =>
        [ModCardVars.Damage(7, ValueProp.Move)];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);
        var attack = await AttackTargetAsync(choiceContext, cardPlay);
        if (attack.Damage.EnemyKills > 0)
        {
            await PlayerCmd.GainEnergy(1, Owner);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(3);
    }
}
