using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using STS2RitsuLib.Scaffolding.Content;

namespace Vivhite.Core;

/// <summary>
/// Reusable card base that makes payment-before-effect an invariant.
/// </summary>
public abstract class LifeCalculationCard : ModCardTemplate
{
    protected LifeCalculationCard(
        int baseEnergyCost,
        CardType cardType,
        CardRarity rarity,
        TargetType targetType,
        bool shouldShowInCardLibrary = true)
        : base(baseEnergyCost, cardType, rarity, targetType, shouldShowInCardLibrary)
    {
    }

    protected abstract int LifeCalculationCost { get; }

    protected virtual bool AdditionalLifeCalculationPlayability => true;

    protected sealed override bool IsPlayable =>
        base.IsPlayable &&
        AdditionalLifeCalculationPlayability &&
        LifeCalculation.CanPay(this, LifeCalculationCost);

    protected sealed override async Task OnPlay(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay)
    {
        var payment = await LifeCalculation.TryPayAsync(
            choiceContext,
            this,
            cardPlay,
            LifeCalculationCost);
        if (!payment.Succeeded)
        {
            await OnLifePaymentFailed(choiceContext, cardPlay, payment);
            return;
        }

        await OnPlayAfterLifePayment(choiceContext, cardPlay, payment);
    }

    protected virtual Task OnLifePaymentFailed(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        return Task.CompletedTask;
    }

    protected abstract Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment);
}
