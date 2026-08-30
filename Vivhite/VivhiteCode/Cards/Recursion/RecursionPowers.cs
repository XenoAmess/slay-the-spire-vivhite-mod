using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Powers;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.ValueProps;
using STS2RitsuLib.Interop.AutoRegistration;
using STS2RitsuLib.Scaffolding.Content;
using Vivhite.Core;
using Vivhite.Powers;

namespace Vivhite.Cards.Recursion;

[RegisterPower]
public sealed class AstralPursuitPower : AnyEnemyDeathPower
{
    protected override async Task OnAnyEnemyDeath(
        PlayerChoiceContext choiceContext,
        EnemyDeathEvent deathEvent)
    {
        var player = Owner.Player;
        if (player is null || Amount <= 0)
        {
            return;
        }

        await CardPileCmd.Draw(choiceContext, Amount, player, false);
    }
}

/// <summary>
/// Kept separate from AstralPursuitPower so any mixture of base and upgraded copies stacks
/// exactly: every copy draws, while only upgraded copies grant Margin.
/// </summary>
[RegisterPower]
public sealed class AstralPursuitMarginPower : AnyEnemyDeathPower
{
    protected override async Task OnAnyEnemyDeath(
        PlayerChoiceContext choiceContext,
        EnemyDeathEvent deathEvent)
    {
        if (Amount <= 0)
        {
            return;
        }

        await InfiniteMargin.GainAsync(
            choiceContext,
            Owner,
            Amount,
            Owner);
    }
}

[RegisterPower]
public sealed class InductiveCirclePower : AnyEnemyDeathPower
{
    protected override async Task OnAnyEnemyDeath(
        PlayerChoiceContext choiceContext,
        EnemyDeathEvent deathEvent)
    {
        if (Amount > 0)
        {
            await Overheal.HealAsync(Owner, Amount);
        }
    }
}

[RegisterPower]
public sealed class OptimalAlgorithmPower : AnyEnemyDeathPower
{
    protected override async Task OnAnyEnemyDeath(
        PlayerChoiceContext choiceContext,
        EnemyDeathEvent deathEvent)
    {
        var player = Owner.Player;
        for (var copy = 0; copy < Amount; copy++)
        {
            await Overheal.HealAsync(Owner, 3);
            if (player is null)
            {
                continue;
            }

            await CardPileCmd.Draw(choiceContext, 2, player, false);
            await PlayerCmd.GainEnergy(1, player);
        }
    }
}

internal sealed class DynamicProgrammingState
{
    public int Calculation { get; set; }
    public CardPlay? ArmedPlay { get; set; }
    public int ArmedValue { get; set; }
}

/// <summary>
/// Amount is the uncapped Calculation gained per non-hand draw. The accumulated value is armed
/// for the next Attack card before that card resolves, applies to every damage hit belonging to
/// that exact CardPlay, and is cleared only after the whole card has finished resolving.
/// </summary>
[RegisterPower]
public sealed class DynamicProgrammingPower : VivhitePowerTemplate
{
    public override PowerType Type => PowerType.Buff;
    public override PowerStackType StackType => PowerStackType.Counter;

    public override int DisplayAmount => GetInternalData<DynamicProgrammingState>().Calculation;

    protected override object InitInternalData()
    {
        return new DynamicProgrammingState();
    }

    public override Task AfterCardDrawn(
        PlayerChoiceContext choiceContext,
        CardModel card,
        bool fromHandDraw)
    {
        if (fromHandDraw ||
            Amount <= 0 ||
            !ReferenceEquals(card.Owner.Creature, Owner))
        {
            return Task.CompletedTask;
        }

        var state = GetInternalData<DynamicProgrammingState>();
        state.Calculation += Amount;
        InvokeDisplayAmountChanged();
        Flash();
        return Task.CompletedTask;
    }

    public override Task BeforeCardPlayed(CardPlay cardPlay)
    {
        var state = GetInternalData<DynamicProgrammingState>();
        if (state.ArmedPlay is null &&
            state.Calculation > 0 &&
            ReferenceEquals(cardPlay.Player.Creature, Owner) &&
            cardPlay.Card.Type == CardType.Attack)
        {
            state.ArmedPlay = cardPlay;
            state.ArmedValue = state.Calculation;
        }

        return Task.CompletedTask;
    }

    public override decimal ModifyDamageAdditive(
        Creature? target,
        decimal amount,
        ValueProp props,
        Creature? dealer,
        CardModel? cardSource,
        CardPlay? cardPlay)
    {
        var state = GetInternalData<DynamicProgrammingState>();
        // Life Calculation deliberately carries the same card source, CardPlay, and dealer as
        // the card effect. Match the native Strength/Vigor gate so only powered Attack damage
        // against an enemy receives Calculation; self-payment and other card damage return 0.
        if (state.ArmedValue <= 0 ||
            !props.IsPoweredAttack() ||
            target is null ||
            ReferenceEquals(target, Owner) ||
            !target.IsEnemy ||
            cardSource is null ||
            cardPlay is null ||
            !ReferenceEquals(cardPlay, state.ArmedPlay) ||
            !ReferenceEquals(cardSource, state.ArmedPlay.Card) ||
            cardSource.Type != CardType.Attack ||
            !ReferenceEquals(dealer, Owner))
        {
            return 0;
        }

        return state.ArmedValue;
    }

    public override Task AfterCardPlayed(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay)
    {
        var state = GetInternalData<DynamicProgrammingState>();
        if (!ReferenceEquals(cardPlay, state.ArmedPlay))
        {
            return Task.CompletedTask;
        }

        state.Calculation = 0;
        state.ArmedValue = 0;
        state.ArmedPlay = null;
        InvokeDisplayAmountChanged();
        return Task.CompletedTask;
    }
}
