using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Combat;
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
public sealed class BacktrackingSpell : RecursionCard
{
    public BacktrackingSpell()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self, 6)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [CardKeyword.Exhaust];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var discardPile = CardPile.Get(PileType.Discard, Owner);
        if (discardPile is null ||
            !discardPile.Cards.Any(static card => card.Type == CardType.Attack))
        {
            return;
        }

        var selectedCards = await CardSelectCmd.FromCombatPile(
            choiceContext,
            discardPile,
            Owner,
            new CardSelectorPrefs(SelectionScreenPrompt, 1),
            static card => card.Type == CardType.Attack);
        var selected = selectedCards.SingleOrDefault();
        if (selected is null)
        {
            return;
        }

        await CardPileCmd.Add(
            selected,
            PileType.Hand,
            CardPilePosition.Top,
            this,
            false);
        selected.SetToFreeThisTurn();
    }

    protected override void OnUpgrade()
    {
        DynamicVars["LifeCost"].UpgradeValueBy(-4);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class ConvergenceVerdict : RecursionCard
{
    public ConvergenceVerdict()
        : base(2, CardType.Attack, CardRarity.Uncommon, TargetType.AnyEnemy, 8)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [VivhiteKeywords.Lethal];

    protected override IEnumerable<DynamicVar> RecursionVars =>
    [
        ModCardVars.Damage(27, ValueProp.Move),
        ModCardVars.Cards(6)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);
        var attack = await AttackTargetAsync(choiceContext, cardPlay);
        if (attack.Damage.EnemyKills == 0)
        {
            return;
        }

        await DrawAsync(choiceContext, DynamicVars.Cards.BaseValue);
        await PlayerCmd.GainEnergy(1, Owner);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(8);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class DivideAndConquerCircle : RecursionCard
{
    public DivideAndConquerCircle()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self, 4)
    {
    }

    protected override IEnumerable<DynamicVar> RecursionVars =>
    [
        ModCardVars.Cards(4),
        ModCardVars.Int("SpellDamage", 4)
    ];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var drawnAttacks = (await DrawAsync(choiceContext, DynamicVars.Cards.BaseValue))
            .Where(static card => card.Type == CardType.Attack)
            .ToArray();
        var combatState = CombatState!;
        var runState = RunState!;

        foreach (var _ in drawnAttacks)
        {
            var opponents = combatState
                .GetOpponentsOf(Owner.Creature)
                .Where(static creature => creature.IsAlive && creature.IsHittable)
                .ToArray();
            if (opponents.Length == 0)
            {
                break;
            }

            var target = runState.Rng.CombatTargets.NextItem(opponents);
            if (target is null)
            {
                break;
            }

            await CreatureCmd.Damage(
                choiceContext,
                target,
                IntVar("SpellDamage"),
                ValueProp.Unpowered | ValueProp.Move,
                Owner.Creature,
                this,
                cardPlay);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Cards.UpgradeValueBy(2);
        DynamicVars["SpellDamage"].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class AstralPursuit : RecursionCard
{
    public AstralPursuit()
        : base(0, CardType.Power, CardRarity.Uncommon, TargetType.Self, 4)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        IsUpgraded ? [VivhiteKeywords.Margin] : [];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await PowerCmd.Apply<AstralPursuitPower>(
            choiceContext,
            Owner.Creature,
            1,
            Owner.Creature,
            this);
        if (IsUpgraded)
        {
            await PowerCmd.Apply<AstralPursuitMarginPower>(
                choiceContext,
                Owner.Creature,
                1,
                Owner.Creature,
                this);
        }
    }

    protected override void OnUpgrade()
    {
        // The upgrade adds the independent Margin-on-death observer.
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class PrefetchFuture : RecursionCard
{
    public PrefetchFuture()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self, 4)
    {
    }

    protected override IEnumerable<DynamicVar> RecursionVars =>
        [ModCardVars.Cards(6)];

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

        var selection = await CardSelectCmd.FromHand(
            choiceContext,
            Owner,
            new CardSelectorPrefs(SelectionScreenPrompt, 1),
            static _ => true,
            this);
        var selected = selection.SingleOrDefault();
        if (selected is null)
        {
            return;
        }

        await CardPileCmd.Add(
            selected,
            PileType.Draw,
            CardPilePosition.Top,
            this,
            false);
    }

    protected override void OnUpgrade()
    {
        EnergyCost.UpgradeBy(-1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class InductiveCircle : RecursionCard
{
    public InductiveCircle()
        : base(1, CardType.Power, CardRarity.Uncommon, TargetType.Self, 8)
    {
    }

    protected override IEnumerable<DynamicVar> RecursionVars =>
        [ModCardVars.Heal(50)];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await PowerCmd.Apply<InductiveCirclePower>(
            choiceContext,
            Owner.Creature,
            DynamicVars.Heal.BaseValue,
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Heal.UpgradeValueBy(25);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class EventLoop : RecursionCard
{
    public EventLoop()
        : base(1, CardType.Skill, CardRarity.Uncommon, TargetType.Self, 6)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [CardKeyword.Exhaust];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var candidates = CombatManager.Instance.History.CardPlaysFinished
            .Where(entry =>
                entry.HappenedThisTurn(CombatState) &&
                ReferenceEquals(entry.CardPlay.Player, Owner) &&
                entry.CardPlay.Card.Type != CardType.Power)
            .Select(static entry => entry.CardPlay.Card)
            .Distinct((IEqualityComparer<MegaCrit.Sts2.Core.Models.CardModel>)ReferenceEqualityComparer.Instance)
            .ToArray();
        if (candidates.Length == 0)
        {
            return;
        }

        var selection = await CardSelectCmd.FromSimpleGrid(
            choiceContext,
            candidates,
            Owner,
            new CardSelectorPrefs(SelectionScreenPrompt, 1));
        var selected = selection.SingleOrDefault();
        if (selected is null)
        {
            return;
        }

        var copy = selected.CreateClone();
        // The copy is combat-scoped because it enters through AddGeneratedCardToCombat, but
        // Event Loop's contract also makes it a one-shot card.  Use the durable native keyword
        // rather than ExhaustOnNextPlay: CreateClone resets that transient flag and the engine
        // clears it at turn end, which would let an unplayed copy survive without exhausting.
        copy.AddKeyword(CardKeyword.Exhaust);
        copy.SetToFreeThisTurn();
        await CardPileCmd.AddGeneratedCardToCombat(
            copy,
            PileType.Hand,
            Owner,
            CardPilePosition.Bottom);
    }

    protected override void OnUpgrade()
    {
        EnergyCost.UpgradeBy(-1);
    }
}
