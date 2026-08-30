using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.ValueProps;
using STS2RitsuLib.Cards.DynamicVars;
using STS2RitsuLib.Interop.AutoRegistration;
using Vivhite.Characters;
using Vivhite.Core;

namespace Vivhite.Cards.Recursion;

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class ProofOfTermination : RecursionCard
{
    public ProofOfTermination()
        : base(2, CardType.Attack, CardRarity.Rare, TargetType.AllEnemies, 10)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [CardKeyword.Exhaust];

    protected override IEnumerable<DynamicVar> RecursionVars =>
        [ModCardVars.Damage(20, ValueProp.Move)];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var attack = await AttackAllAsync(choiceContext, cardPlay);
        for (var kill = 0; kill < attack.Damage.EnemyKills; kill++)
        {
            await DrawAsync(choiceContext, 4);
            await PlayerCmd.GainEnergy(1, Owner);
        }
    }

    protected override void OnUpgrade()
    {
        DynamicVars.Damage.UpgradeValueBy(7);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class DynamicProgramming : RecursionCard
{
    public DynamicProgramming()
        : base(2, CardType.Power, CardRarity.Rare, TargetType.Self, 10)
    {
    }

    protected override IEnumerable<DynamicVar> RecursionVars =>
        [ModCardVars.Int("Calculation", 2)];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await PowerCmd.Apply<DynamicProgrammingPower>(
            choiceContext,
            Owner.Creature,
            IntVar("Calculation"),
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        DynamicVars["Calculation"].UpgradeValueBy(1);
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class InfiniteStarSequence : RecursionCard
{
    public InfiniteStarSequence()
        : base(1, CardType.Skill, CardRarity.Rare, TargetType.Self, 8)
    {
    }

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [CardKeyword.Exhaust, Vivhite.Cards.Common.VivhiteKeywords.Margin];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        // The current card has not reached CardPlayFinished yet, so this is exactly the number
        // of this player's cards completed before Infinite Star Sequence this turn.
        var priorCardsPlayed = CombatManager.Instance.History.CardPlaysFinished.Count(entry =>
            entry.HappenedThisTurn(CombatState) &&
            ReferenceEquals(entry.CardPlay.Player, Owner));
        var requestedDraw = 2 * (priorCardsPlayed + (IsUpgraded ? 1 : 0));
        var actuallyDrawn = (await DrawAsync(choiceContext, requestedDraw)).Count();
        if (actuallyDrawn > 0)
        {
            await InfiniteMargin.GainAsync(
                choiceContext,
                Owner.Creature,
                actuallyDrawn,
                Owner.Creature,
                this);
        }
    }

    protected override void OnUpgrade()
    {
        // The upgrade adds two draws after the pre-play history count is captured.
    }
}

[RegisterCard(typeof(VivhiteCardPool))]
public sealed class OptimalAlgorithm : RecursionCard
{
    public OptimalAlgorithm()
        : base(3, CardType.Power, CardRarity.Rare, TargetType.Self, 14)
    {
    }

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        await PowerCmd.Apply<OptimalAlgorithmPower>(
            choiceContext,
            Owner.Creature,
            1,
            Owner.Creature,
            this);
    }

    protected override void OnUpgrade()
    {
        EnergyCost.UpgradeBy(-1);
    }
}
