# whole_mesh：整身加权基线候选

`whole_mesh` 是最早的完整白绮 combat rig 基线：一张连续加权身体网格由层级骨链驱动，
并在 `die` 中切换到独立的侧倒 attachment。它用于和 `split_mesh` / Hybrid V3 做
同条件比较，**不是当前正式生产方案**；大角度动作会把服装和关节像橡皮布一样拉伸，
死亡切换前仍有整身网格的形变上限。

## 输入与输出

- 输入：已验真的白绮 combat body、magic arc、magic sigil，以及冻结的
  `vivhite-combat-death-side-collapse-v2.png`。
- 输出：`Vivhite/tools/candidates/whole_mesh/` 下的
  `vivhite_combat.spjson`、`.spatlas`、`vivhite_combat.png`、
  `vivhite_combat_death.png`、`vivhite_combat_skeleton_data.tres`（候选五件套）。
- 运行时边界：输出目录位于正式 Mod 的 `tools/**` 排除范围；构建器不会写
  `Vivhite/Vivhite/skins/ironclad/`，也不会部署或启动游戏。

## 构建、校验与精确死亡采样

```powershell
$propsText = Get-Content .\Vivhite\local.props -Raw
$props = [xml]$propsText
$godot = [string]$props.Project.PropertyGroup.GodotExe

# 构建（art 项目把 res:// 解析到 tools/art）
& $godot --headless --path .\tools\art `
  --script res://candidates/whole_mesh/build_whole_mesh_candidate.gd -- build-combat

# 校验（Vivhite 项目提供游戏 Spine GDExtension）
& $godot --headless --path .\Vivhite `
  --script (Resolve-Path .\tools\art\candidates\whole_mesh\validate_whole_mesh_candidate.gd)

# 仅采样 die 的原子切换/接地/回弹时刻；需要 Windows Vulkan 与基础 PCK
& $godot --path .\Vivhite --display-driver windows --rendering-driver vulkan `
  --script (Resolve-Path .\tools\art\candidates\whole_mesh\render_atomic_death_exact.gd)
```

构建器支持 `--body-source`、`--arc-source`、`--sigil-source`、`--death-source` 和
`--output-root`；输出根必须保持在候选/调查目录，不得指向正式 skins。validator 会
检查 Spine 4.2.43、八个动画、VFX slots/events、骨骼/Bezier 契约和死亡 swap 时间线。

## 对照解释

比较器的默认 scene scale 是 `.28`、制作比例 `.70`；推荐把本候选与
`hybrid_v3_final` 或历史 `split_mesh` 一起交给
[`compare/preview`](../../compare/preview/README.md)。`die` 精确采样点包括
`1.0499s`（切换前仅站立网格）、`1.05s`（原子切换后仅侧倒图）、`1.1666667s`
（接地）、`1.30s`（回弹）和 `1.80/1.90s`（静止复核）。这些是研究证据，不是
“整身方案已适合生产”的证明。

保存 `.work/` 中的 `summary.json` 与原始帧；禁止把候选 PNG、`.tres` 或诊断接触表
复制进 runtime。新透明来源仍须经过 EvoLink 原生 Alpha 与追加式 Prompt/请求归档。
