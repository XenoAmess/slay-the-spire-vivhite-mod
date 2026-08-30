using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Commands.Builders;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.ValueProps;
using Vivhite.Cards.Common;
using Vivhite.Core;

namespace Vivhite.Cards.Conservation;

/// <summary>
/// Shared implementation surface for the Conservation Geometry suit. The common Vivhite base
/// supplies shared Life Calculation rules, keywords, and dedicated type-named card art.
/// </summary>
public abstract class ConservationCard : VivhiteLifeCalculationCard
{
    private readonly int _lifeCalculationCost;

    protected ConservationCard(
        int energyCost,
        CardType type,
        CardRarity rarity,
        TargetType targetType,
        int lifeCalculationCost)
        : base(energyCost, type, rarity, targetType)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(lifeCalculationCost);
        _lifeCalculationCost = lifeCalculationCost;
    }

    protected sealed override int LifeCalculationCost => _lifeCalculationCost;

    /// <summary>
    /// Card-specific dynamic values. Life Calculation is injected once here so every card uses
    /// the same payment value in both rules text and execution.
    /// </summary>
    protected virtual IEnumerable<DynamicVar> ConservationVars => [];

    protected sealed override IEnumerable<DynamicVar> CanonicalVars =>
        LifeCalculationCost == 0
            ? ConservationVars
            : [new HpLossVar("LifeCost", LifeCalculationCost), .. ConservationVars];

    protected Task GainMarginAsync(
        PlayerChoiceContext choiceContext,
        int amount,
        bool silent = false)
    {
        return InfiniteMargin.GainAsync(
            choiceContext,
            Owner.Creature,
            amount,
            Owner.Creature,
            this,
            silent);
    }

    protected Task<decimal> GainBlockAsync(
        decimal amount,
        CardPlay cardPlay,
        bool fast = false)
    {
        return CreatureCmd.GainBlock(
            Owner.Creature,
            amount,
            ValueProp.Move,
            cardPlay,
            fast);
    }

    /// <summary>
    /// Executes every A-suit Attack through the shared card-level Drain aggregator. A card Drain
    /// rate of zero still includes all global and this-turn Drain powers exactly once.
    /// </summary>
    protected Task<InfiniteDrainResult> AttackAsync(
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

    /// <summary>
    /// A-suit lethal attacks are single-target, so the aggregate reports one enemy kill exactly
    /// when this card's completed AttackCommand directly killed its target.
    /// </summary>
    protected static bool DirectlyKilled(InfiniteDrainResult result)
    {
        ArgumentNullException.ThrowIfNull(result);
        return result.Damage.EnemyKills > 0;
    }
}
