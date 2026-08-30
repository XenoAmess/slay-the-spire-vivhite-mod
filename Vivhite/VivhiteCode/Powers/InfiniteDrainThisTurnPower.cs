using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using STS2RitsuLib.Interop.AutoRegistration;

namespace Vivhite.Powers;

[RegisterPower]
public sealed class InfiniteDrainThisTurnPower : VivhiteCounterPower
{
    public override Task AfterSideTurnEnd(
        PlayerChoiceContext choiceContext,
        CombatSide side,
        IEnumerable<Creature> participants)
    {
        return participants.Any(creature => ReferenceEquals(creature, Owner))
            ? PowerCmd.Remove(this)
            : Task.CompletedTask;
    }
}
