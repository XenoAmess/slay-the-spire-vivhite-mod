using MegaCrit.Sts2.Core.Entities.Powers;
using STS2RitsuLib.Scaffolding.Content;

namespace Vivhite.Powers;

/// <summary>
/// Shared presentation contract for every Vivhite power. Each registered power resolves to its
/// own mod-owned transparent icon, named after the compiled power type. A missing icon is a
/// packaging failure and can no longer be hidden by the old shared relic placeholder.
/// </summary>
public abstract class VivhitePowerTemplate : ModPowerTemplate
{
    public sealed override PowerAssetProfile AssetProfile
    {
        get
        {
            var iconName = GetType().Name.Replace(
                "UpgradedPower",
                "Power",
                StringComparison.Ordinal);
            var path = $"{Entry.ResPath}/images/powers/{iconName}.png";
            return new PowerAssetProfile(IconPath: path, BigIconPath: path);
        }
    }
}

/// <summary>
/// Common non-negative, visible counter contract for Vivhite's infinite resources.
/// </summary>
public abstract class VivhiteCounterPower : VivhitePowerTemplate
{
    public override PowerType Type => PowerType.Buff;
    public override PowerStackType StackType => PowerStackType.Counter;
}
