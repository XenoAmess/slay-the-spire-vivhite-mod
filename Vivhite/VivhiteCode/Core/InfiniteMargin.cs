using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using Vivhite.Powers;

namespace Vivhite.Core;

public static class InfiniteMargin
{
    public static InfiniteMarginPower? Find(Creature owner) =>
        PowerStackResource<InfiniteMarginPower>.Find(owner);

    public static int GetAmount(Creature owner) =>
        PowerStackResource<InfiniteMarginPower>.GetAmount(owner);

    public static bool CanSpend(Creature owner, int amount) =>
        PowerStackResource<InfiniteMarginPower>.CanSpend(owner, amount);

    public static Task<InfiniteMarginPower?> GainAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false) =>
        PowerStackResource<InfiniteMarginPower>.GainAsync(
            choiceContext,
            owner,
            amount,
            applier,
            cardSource,
            silent);

    public static Task<PowerSpendResult> TrySpendAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false) =>
        PowerStackResource<InfiniteMarginPower>.TrySpendAsync(
            choiceContext,
            owner,
            amount,
            applier,
            cardSource,
            silent);

    public static Task<PowerConsumptionResult> ConsumeUpToAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false) =>
        PowerStackResource<InfiniteMarginPower>.ConsumeUpToAsync(
            choiceContext,
            owner,
            amount,
            applier,
            cardSource,
            silent);
}
