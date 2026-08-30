using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;

namespace Vivhite.Core;

public enum PowerSpendFailure
{
    None,
    InvalidAmount,
    InsufficientAmount
}

public readonly record struct PowerSpendResult(
    int Requested,
    int AmountBefore,
    int AmountAfter,
    PowerSpendFailure Failure)
{
    public bool Succeeded => Failure == PowerSpendFailure.None;
}

public readonly record struct PowerConsumptionResult(
    int Requested,
    int AmountBefore,
    int Consumed,
    int AmountAfter);

internal static class PowerStackResource<TPower>
    where TPower : PowerModel
{
    public static TPower? Find(Creature owner)
    {
        ArgumentNullException.ThrowIfNull(owner);
        return owner.GetPower<TPower>();
    }

    public static int GetAmount(Creature owner)
    {
        return Math.Max(0, Find(owner)?.Amount ?? 0);
    }

    public static bool CanSpend(Creature owner, int amount)
    {
        return amount >= 0 && GetAmount(owner) >= amount;
    }

    public static async Task<TPower?> GainAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false)
    {
        ArgumentNullException.ThrowIfNull(choiceContext);
        ArgumentNullException.ThrowIfNull(owner);
        ArgumentOutOfRangeException.ThrowIfNegative(amount);

        if (amount == 0)
        {
            return Find(owner);
        }

        return await PowerCmd.Apply<TPower>(
            choiceContext,
            owner,
            amount,
            applier ?? owner,
            cardSource,
            silent);
    }

    public static async Task<PowerSpendResult> TrySpendAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false)
    {
        ArgumentNullException.ThrowIfNull(choiceContext);
        ArgumentNullException.ThrowIfNull(owner);

        var before = GetAmount(owner);
        if (amount < 0)
        {
            return new PowerSpendResult(
                amount,
                before,
                before,
                PowerSpendFailure.InvalidAmount);
        }

        if (amount == 0)
        {
            return new PowerSpendResult(amount, before, before, PowerSpendFailure.None);
        }

        var power = Find(owner);
        if (power is null || before < amount)
        {
            return new PowerSpendResult(
                amount,
                before,
                before,
                PowerSpendFailure.InsufficientAmount);
        }

        var after = await PowerCmd.ModifyAmount(
            choiceContext,
            power,
            -amount,
            applier ?? owner,
            cardSource,
            silent);

        return new PowerSpendResult(amount, before, Math.Max(0, after), PowerSpendFailure.None);
    }

    public static async Task<PowerConsumptionResult> ConsumeUpToAsync(
        PlayerChoiceContext choiceContext,
        Creature owner,
        int amount,
        Creature? applier = null,
        CardModel? cardSource = null,
        bool silent = false)
    {
        ArgumentNullException.ThrowIfNull(choiceContext);
        ArgumentNullException.ThrowIfNull(owner);
        ArgumentOutOfRangeException.ThrowIfNegative(amount);

        var before = GetAmount(owner);
        var requestedConsumption = Math.Min(before, amount);
        var power = Find(owner);
        if (requestedConsumption == 0 || power is null)
        {
            return new PowerConsumptionResult(amount, before, 0, before);
        }

        var commandAmountAfter = await PowerCmd.ModifyAmount(
            choiceContext,
            power,
            -requestedConsumption,
            applier ?? owner,
            cardSource,
            silent);
        var after = Math.Max(0, commandAmountAfter);
        var consumed = Math.Min(requestedConsumption, Math.Max(0, before - after));

        return new PowerConsumptionResult(amount, before, consumed, after);
    }
}
