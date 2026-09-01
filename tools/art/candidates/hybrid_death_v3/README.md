# hybrid_death_v3：死亡连续性候选

本候选专门修复从受伤/站立网格到 `0029` 侧倒图的死亡交接：低幅收缩 → 一次原子
attachment swap → 实体接地 → 小幅阻尼回弹。它仍是离线候选，不能单独发布。

## 不可变输入与时间线

- `vivhite-combat-death-side-collapse-v2.png` 必须与脚本冻结 SHA-256 一致；脚本会
  fail-closed，不能换成未经审计的相似图。
- swap 前 `1.0499s`、swap `1.05s`、接触 `1.1666667s`、回弹 `1.30s`、稳定 `1.80s`；
  validator 同时检查八动画、`die` 的 `clear_vfx@0`、slot visibility 和无运行时路径泄漏。
- 侧倒图是完整独立 attachment；它不声称可继续独立摆动四肢，也不复用原战士骨骼。

## 命令

```powershell
# 一键隐藏 Vulkan 验收（默认 1280x900、scene scale .28）
& .\tools\art\candidates\hybrid_death_v3\Invoke-HybridDeathV3Preview.ps1

# 仅构建候选
& $godot --headless --path .\tools\art `
  --script res://candidates/hybrid_death_v3/build_hybrid_death_v3_candidate.gd -- build-combat
```

包装器支持 `-GodotExe -Sts2Dir -ProjectDir -OutputDir -Width -Height -SceneScale
-OriginX/-OriginY -SceneOffsetX/-SceneOffsetY`，并把报告限制在新的 `.work/` 目录。
渲染器对每个时刻保存 composite 与 character-only 帧；`summary.json` 必须完整通过，
再由 `hybrid_v3_final` 总装器接收其 `die` bone 子树。

不要把死姿态接触表当作 atlas 输入，也不要删除失败帧。Alpha、原图归档和 EvoLink
八次额度规则仍适用。

