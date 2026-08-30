using MegaCrit.Sts2.Core.CardSelection;
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
public sealed class ConservedRecurrence : VivhiteLifeCalculationCard
{
    public ConservedRecurrence()
        : base(2, CardType.Skill, CardRarity.Rare, TargetType.Self)
    {
    }

    protected override int LifeCalculationCost => 5;

    protected override IEnumerable<CardKeyword> AdditionalVivhiteKeywords =>
        [CardKeyword.Exhaust];

    protected override IEnumerable<DynamicVar> CanonicalVars =>
        [ModCardVars.Int("LifeCost", 5)];

    protected override async Task OnPlayAfterLifePayment(
        PlayerChoiceContext choiceContext,
        CardPlay cardPlay,
        LifePaymentResult payment)
    {
        var preferences = new CardSelectorPrefs(SelectionScreenPrompt, 1);
        var selection = await CardSelectCmd.FromCombatPile(
            choiceContext,
            Owner.PlayerCombatState!.ExhaustPile,
            Owner,
            preferences,
            card => card.Type != CardType.Power);
        var selected = selection.SingleOrDefault();
        if (selected is null)
        {
            return;
        }

        var copy = selected.CreateClone();
        copy.SetToFreeThisTurn();
        if (IsUpgraded)
        {
            selected.SetToFreeThisTurn();
        }

        await CardPileCmd.Add(
            selected,
            PileType.Hand,
            CardPilePosition.Bottom,
            this,
            false);
        await CardPileCmd.AddGeneratedCardToCombat(
            copy,
            PileType.Hand,
            Owner,
            CardPilePosition.Bottom);
    }

    protected override void OnUpgrade()
    {
        // The upgrade changes the returned original card, not this card's cost or Life Calculation.
    }
}
