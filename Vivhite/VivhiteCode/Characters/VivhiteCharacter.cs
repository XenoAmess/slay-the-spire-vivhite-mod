using Godot;
using MegaCrit.Sts2.Core.Entities.Characters;
using MegaCrit.Sts2.Core.Nodes.Combat;
using STS2RitsuLib.Interop.AutoRegistration;
using STS2RitsuLib.Scaffolding.Characters;
using STS2RitsuLib.Scaffolding.Godot;

namespace Vivhite.Characters;

[RegisterCharacter]
public sealed class VivhiteCharacter : ModCharacterTemplate<VivhiteCardPool, VivhiteRelicPool, VivhitePotionPool>
{
    // 白绮主题色：素白微蓝。
    public static readonly Color ThemeColor = new(0.93f, 0.94f, 0.98f);

    private const string EnergyCounterScenePath =
        $"{Entry.ResPath}/scenes/characters/Vivhite_energy_counter.tscn";

    private const string CardTrailScenePath =
        $"{Entry.ResPath}/scenes/vfx/card_trail_vivhite.tscn";

    private static CharacterAssetProfile? _assetProfile;

    // 角色名称颜色。
    public override Color NameColor => ThemeColor;
    // 能量图标轮廓颜色。
    public override Color EnergyLabelOutlineColor => new(0.30f, 0.31f, 0.38f);
    // 地图绘制颜色。
    public override Color MapDrawingColor => ThemeColor;

    // 人物性别（男女中立）。
    public override CharacterGender Gender => CharacterGender.Feminine;

    // 初始血量和金币。
    public override int StartingHp => 78;
    public override int MaxEnergy => 3;
    public override int StartingGold => 99;

    // 独立白绮角色独占当前已验证的 V3 五页资源 profile；物理目录沿用历史
    // skins/ironclad 路径，但不再向原版 IRONCLAD 注册任何资源替换。
    public override CharacterAssetProfile AssetProfile => _assetProfile ??= CreateVivhiteAssetProfile();

    // 某个字段没写时，RitsuLib 会从占位角色配置里补齐。
    public override string? PlaceholderCharacterId => "ironclad";
    // 如果你的人物不需要时间线小故事，加上这句。
    public override bool RequiresEpochAndTimeline => false;
    // 攻击和施法动画延迟，以对齐动画。静态占位资源不需要延迟。
    public override float AttackAnimDelay => 0f;
    public override float CastAnimDelay => 0f;

    // 让 RitsuLib 把普通 Godot 场景转换成游戏需要的 NCreatureVisuals。
    // 自动转换人物场景，让你不需要手动挂脚本。复制即可。
    protected override NCreatureVisuals? TryCreateCreatureVisuals()
    {
        var visualsPath = AssetProfile.Scenes?.VisualsPath;
        if (string.IsNullOrWhiteSpace(visualsPath))
        {
            throw new InvalidOperationException(
                "The validated Vivhite V3 profile has no combat visuals path.");
        }

        return RitsuGodotNodeFactories.CreateFromScenePath<NCreatureVisuals>(
            visualsPath);
    }

    private static CharacterAssetProfile CreateVivhiteAssetProfile()
    {
        var baseProfile = VivhiteCharacterAssets.GetValidatedV3Profile();
        var scenes = baseProfile.Scenes
            ?? throw new InvalidOperationException(
                "The validated Vivhite V3 profile has no scene asset set.");
        scenes = scenes with { EnergyCounterPath = EnergyCounterScenePath };

        var vivhiteProfile = CharacterAssetProfiles.WithScenes(baseProfile, scenes);
        return CharacterAssetProfiles.WithVfx(
            vivhiteProfile,
            new CharacterVfxAssetSet(
                TrailPath: CardTrailScenePath,
                TrailStyle: null));
    }

    // 攻击建筑师的攻击特效列表。
    public override List<string> GetArchitectAttackVfx()
    {
        // The Architect shuffles this fresh list in place and plays every entry as one hit.
        // Preserve its five-hit cadence with spell effects that do not imply weapons or gore.
        return
        [
            "vfx/vfx_attack_lightning",
            "vfx/vfx_starry_impact",
            "vfx/vfx_attack_lightning",
            "vfx/vfx_starry_impact",
            "vfx/vfx_attack_lightning"
        ];
    }
}
