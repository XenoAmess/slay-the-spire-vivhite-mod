using Godot;
using STS2RitsuLib.Scaffolding.Content;

namespace Vivhite.Characters;

public sealed class VivhitePotionPool : TypeListPotionPoolModel
{
    public override string EnergyColorName => "Vivhite";
    public override Color LabOutlineColor => VivhiteCharacter.ThemeColor;

    // 白绮目前未注册专属药水，但保留独立的角色药水池结构。
    // 使用白绮专用、已通过 89 项运行时美术门禁的能量 UI 资源。
    public override string? BigEnergyIconPath => $"{Entry.ResPath}/images/characters/energy_big.png";
    public override string? TextEnergyIconPath => $"{Entry.ResPath}/images/characters/energy_text.png";
}
