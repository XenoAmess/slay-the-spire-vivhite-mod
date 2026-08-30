using MegaCrit.Sts2.Core.Entities.Powers;
using STS2RitsuLib.Scaffolding.Content;

namespace Vivhite.Powers;

/// <summary>
/// Common non-negative, visible counter contract for Vivhite's infinite resources.
/// </summary>
public abstract class VivhiteCounterPower : ModPowerTemplate
{
    public override PowerType Type => PowerType.Buff;
    public override PowerStackType StackType => PowerStackType.Counter;
}
