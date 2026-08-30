using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using Vivhite.Core;

namespace Vivhite.Cards.Common;

/// <summary>
/// Enforces the shared ordering: legal-payment check, Margin consumption, HP payment, then the
/// card effect. Cross-suit observers run after a successful payment and before the card effect.
/// </summary>
public abstract class VivhiteLifeCalculationCard : VivhiteCard
{
    protected VivhiteLifeCalculationCard(
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

    protected virtual IEnumerable<CardKeyword> AdditionalVivhiteKeywords => [];

    protected sealed override IEnumerable<CardKeyword> VivhiteCanonicalKeywords =>
        [VivhiteKeywords.LifeCalculation, .. AdditionalVivhiteKeywords];

    protected sealed override bool IsPlayable =>
        base.IsPlayable &&
        AdditionalLifeCalculationPlayability &&
        LifeCalculation.CanPay(this, LifeCalculationCost);

    protected sealed override async Task OnPlay(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay)
    {
        var payment = await VivhiteCardRules.PayThenAsync(
            choiceContext,
            this,
            cardPlay,
            LifeCalculationCost,
            result => OnPlayAfterLifePayment(choiceContext, cardPlay, result));

        if (!payment.Succeeded)
        {
            await OnLifePaymentFailed(choiceContext, cardPlay, payment);
        }
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
