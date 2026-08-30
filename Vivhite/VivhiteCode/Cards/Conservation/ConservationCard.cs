using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Commands.Builders;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.ValueProps;
using Vivhite.Cards.Common;
using Vivhite.Core;

namespace Vivhite.Cards.Conservation;

/// <summary>
/// Shared implementation surface for the Conservation Geometry suit. The common Vivhite base
/// supplies shared Life Calculation rules, keywords, and placeholder card art.
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

    protected async Task<AttackCommand> AttackAsync(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay)
    {
        ArgumentNullException.ThrowIfNull(cardPlay.Target);
        return await DamageCmd.Attack(DynamicVars.Damage.BaseValue)
            .FromCard(this, cardPlay)
            .Targeting(cardPlay.Target)
            .Execute(choiceContext);
    }

    /// <summary>
    /// A lethal clause belongs only to the completed attack command produced by this card.
    /// Deaths from other commands or previously dead targets do not qualify.
    /// </summary>
    protected static bool DirectlyKilled(AttackCommand attack, Creature target)
    {
        ArgumentNullException.ThrowIfNull(attack);
        ArgumentNullException.ThrowIfNull(target);

        return attack.Results
            .SelectMany(static hit => hit)
            .Any(result =>
                ReferenceEquals(result.Receiver, target) &&
                result.WasTargetKilled);
    }
}
