# `semantic_torso_skirt`：躯干／裙摆语义组灰盒

本目录把 0054 躯干候选接到未修改的 0018 combat master 采样上，复现当前「肩袖烘进躯干」和「躯干先于裙摆」的层序问题。它是可重复的诊断 consumer graybox，不是新美术，也不是可发布的 runtime 资源；manifest 的 `status`、`deployable` 和 `0054_production_eligible` 必须保持拒绝状态。

## 输入、拓扑和结论

- 0054 是 EvoLink 原始 RGBA8 单对象（832×1248），按字节复制为一页；0018 是未修改的 1680×2512 单帧上下文页。构建器只读取原图、Prompt/请求记录和既有 Spine/atlas 证据，不裁切、阈值化、抠图或修补 Alpha。
- graybox 共有 `semantic_torso`、`context_skirt`、两侧上臂和两条大腿上下文 slot；`setup`、`max_twist_clockwise`、`max_twist_counter_clockwise` 三个动画让上下躯干各转 ±23°，形成 46° 相对扭转，裙摆反向摆动 8°。
- 0054 把白色肩帽/袖口、屏幕左蓝金肩饰和下腰裙样层烘在同一对象中，导致独立手臂交接、裙摆遮挡和比例无法通过统一缩放修复。下一代合约要求独立 `torso_core`、四片裙（back/far/front/near）及肩饰前后片；在新素材通过前不要复用 0054。

## 构建与隐藏 Vulkan 预览

先从仓库根目录构建一次候选，再运行包装器。包装器不会自动重建，故不要跳过第一步：

```powershell
$propsText = Get-Content .\Vivhite\local.props -Raw
$props = [xml]$propsText
$godot = [string]$props.Project.PropertyGroup.GodotExe

& $godot --headless --path .\tools\art `
  --script (Resolve-Path .\tools\art\candidates\semantic_torso_skirt\build_semantic_torso_skirt_candidate.gd) -- `
  build-semantic-torso-skirt-candidate

& .\tools\art\candidates\semantic_torso_skirt\Invoke-SemanticTorsoSkirtPreview.ps1
```

包装器从 `Vivhite/local.props` 解析 Godot，先在 `--path Vivhite` 下执行静态/Spine 载入门禁，再以 Windows Vulkan 隐藏窗口渲染三种姿势。可显式传 `-GodotExe`、`-ProjectDir` 或 `-OutputDir`；`OutputDir` 必须位于仓库 `.work/` 下。构建 authored 资源始终写入 `Vivhite/tools/candidates/semantic_torso_skirt/`，不得写入 `Vivhite/Vivhite/skins/ironclad/`。

## 输出与检查重点

默认输出为 `.work/semantic-torso-skirt-preview/`：

```text
summary.json
setup-actual-transparent.png / setup-inspection-transparent.png
max_twist_clockwise-*.png
max_twist_counter_clockwise-*.png
contact-sheet-actual-0.28.png
contact-sheet-inspection-0.70.png
validate.stdout.log / validate.stderr.log
render.stdout.log / render.stderr.log
```

`summary.json` 必须列出三种姿势、真实 Alpha bbox、画布触边标志和 PNG SHA-256；实际 `.28` 场景比例与 `.70` 检查比例都不得触边。validator 还会比较源图字节哈希、Spine 4.2.43、slot 顺序、固定 46° 扭转和 manifest 阻断证据。通过只表示灰盒合同完整，不表示肩袖、腰线或裙摆已经解决。

## 安全边界

这是零付费、零部署、零游戏控制的证据工具。不要把灰盒 PNG、上下文页或 `summary.json` 当作 atlas 输入；不要手改 manifest 让报告变绿。失败时保留整个 `.work` 目录和日志，按复盘失败包流程处理。未来透明素材必须先完成源码/atlas 消费审计，并遵守 `AGENTS.md` 的 EvoLink 原生透明、原图/Prompt/请求归档和八次尝试上限。
