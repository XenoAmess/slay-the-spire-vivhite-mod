using MegaCrit.Sts2.Core.Entities.Powers;
using STS2RitsuLib.Scaffolding.Content;

namespace Vivhite.Powers;

/// <summary>
/// Shared presentation contract for every Vivhite power. Until dedicated power art exists,
/// use one known-good in-pack texture instead of falling through to the engine's red NOPE icon.
/// </summary>
public abstract class VivhitePowerTemplate : ModPowerTemplate
{
    private static readonly PowerAssetProfile PlaceholderAssetProfile = new(
        IconPath: $"{Entry.ResPath}/images/relics/VivhiteRelic.png",
        BigIconPath: $"{Entry.ResPath}/images/relics/VivhiteRelic.png");

    public override PowerAssetProfile AssetProfile => PlaceholderAssetProfile;
}

/// <summary>
/// Common non-negative, visible counter contract for Vivhite's infinite resources.
/// </summary>
public abstract class VivhiteCounterPower : VivhitePowerTemplate
{
    public override PowerType Type => PowerType.Buff;
    public override PowerStackType StackType => PowerStackType.Counter;
}
