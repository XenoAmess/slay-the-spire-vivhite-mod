using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Commands.Builders;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.ValueProps;
using STS2RitsuLib.Cards.DynamicVars;
using Vivhite.Cards.Common;
using Vivhite.Core;

namespace Vivhite.Cards.Recursion;

/// <summary>
/// Shared declaration and execution surface for the Recursion Astral Calculus suit.
/// Every card in this suit reads its payment from the localization-compatible LifeCost
/// dynamic variable and resolves through the cross-suit Vivhite payment pipeline.
/// </summary>
public abstract class RecursionCard : VivhiteLifeCalculationCard
{
    private readonly int _baseLifeCost;

    protected RecursionCard(
        int energyCost,
        CardType type,
        CardRarity rarity,
        TargetType targetType,
        int lifeCost)
        : base(energyCost, type, rarity, targetType)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(lifeCost);
        _baseLifeCost = lifeCost;
    }

    protected sealed override int LifeCalculationCost => IntVar("LifeCost");

    protected virtual IEnumerable<DynamicVar> RecursionVars => [];

    protected sealed override IEnumerable<DynamicVar> CanonicalVars =>
        [ModCardVars.Int("LifeCost", _baseLifeCost), .. RecursionVars];

    protected Task<InfiniteDrainResult> AttackTargetAsync(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);
        var attack = DamageCmd.Attack(DynamicVars.Damage.BaseValue)
            .FromCard(this, cardPlay)
            .Targeting(cardPlay.Target);
        return VivhiteCardRules.ExecuteDrainAttackAsync(
            choiceContext,
            attack,
            this,
            cardPlay,
            cardPercent: 0);
    }

    protected Task<InfiniteDrainResult> AttackAllAsync(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        int hitCount = 1)
    {
        var attack = DamageCmd.Attack(DynamicVars.Damage.BaseValue)
            .FromCard(this, cardPlay)
            .TargetingAllOpponents(CombatState!);
        if (hitCount != 1)
        {
            attack.WithHitCount(hitCount);
        }

        return VivhiteCardRules.ExecuteDrainAttackAsync(
            choiceContext,
            attack,
            this,
            cardPlay,
            cardPercent: 0);
    }

    protected Task<IEnumerable<MegaCrit.Sts2.Core.Models.CardModel>> DrawAsync(
        PlayerChoiceContext choiceContext,
        decimal amount)
    {
        return CardPileCmd.Draw(choiceContext, amount, Owner, false);
    }
}
