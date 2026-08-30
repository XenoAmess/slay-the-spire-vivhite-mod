using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using Vivhite.Powers;

namespace Vivhite.Core;

public static class InfiniteDimensionality
{
    public static InfiniteDimensionalityPower? Find(Creature owner) =>
        PowerStackResource<InfiniteDimensionalityPower>.Find(owner);

    public static int GetAmount(Creature owner) =>
        PowerStackResource<InfiniteDimensionalityPower>.GetAmount(owner);

    public static bool CanSpend(Creature owner, int amount) =>
        PowerStackResource<InfiniteDimensionalityPower>.CanSpend(owner, amount);

    public static Task<InfiniteDimensionalityPower?> GainAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false) =>
        PowerStackResource<InfiniteDimensionalityPower>.GainAsync(
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
        PowerStackResource<InfiniteDimensionalityPower>.TrySpendAsync(
            choiceContext,
            owner,
            amount,
            applier,
            cardSource,
            silent);
}
