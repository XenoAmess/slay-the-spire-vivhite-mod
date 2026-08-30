using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using Vivhite.Powers;

namespace Vivhite.Core;

public static class InfiniteExtension
{
    public static InfiniteExtensionPower? Find(Creature owner) =>
        PowerStackResource<InfiniteExtensionPower>.Find(owner);

    public static int GetAmount(Creature owner) =>
        PowerStackResource<InfiniteExtensionPower>.GetAmount(owner);

    public static bool IsActive(Creature owner)
    {
        return GetAmount(owner) > 0;
    }

    public static Task<InfiniteExtensionPower?> ApplyAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false)
    {
        return GainAsync(
            choiceContext,
            owner,
            1,
            applier,
            cardSource,
            silent);
    }

    public static Task<InfiniteExtensionPower?> GainAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false) =>
        PowerStackResource<InfiniteExtensionPower>.GainAsync(
            choiceContext,
            owner,
            amount,
            applier,
            cardSource,
            silent);
}
