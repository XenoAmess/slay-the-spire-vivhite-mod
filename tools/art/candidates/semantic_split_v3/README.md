# `semantic_split_v3`：跨组件总装灰盒

本目录是白绮 combat 拆件研究的离线 A/B 总装。它把「旧 `split_mesh` 消费者」与「语义拆件候选」放进同一套 Spine 4.2.43、同一场景比例和同一批 Vulkan 采样中，用来暴露层序、关节和动画事件问题。它不是运行时皮肤，也不是可发布素材；`production_runtime_ready_slots` 必须保持为空。

## 当前证据和阻断项

- B 行接入已有证据的真实附件：0031 后发、0045 头脸、0033 前刘海、0030 蓝蝶，以及 0078 远侧大腿、0083 近侧大腿。总装层序为：后发 → 躯干 → 头脸 → 蓝蝶 → 前刘海 → 前景手臂；蓝蝶不会退回到旧 head-face 子候选的前置位置。
- 躯干、四片裙、远肩饰前/后片、远/近上臂袖、远/近前臂手、远/近「小腿+靴一体」共 13 个生产附件仍要求新的 EvoLink 语义生成。黄色裙块和交叉纹区域只是诊断代理，不得冒充真实 slot。
- 独立手腕和脚踝 attachment 已从目标拓扑移除；腕锚只用于测量，膝关节保留。缺件、哈希漂移、旧扁平 body attachment 泄漏、slot/事件缺失都会 fail-closed。
- `candidate.json` 同时记录组件状态、生产 slot 合约和 `deployable=false`。任何候选通过都不能绕过完整角色总装、PCK、真实场景和人工视觉复核。

## 一键 A/B 验收

从仓库根目录执行。脚本会先重建候选并执行静态门禁，再调用游戏 PCK 中的真实 Spine GDExtension，在 Windows/Vulkan 隐藏窗口按每个动画 21 个稠密样本渲染 A/B，最后组装关键帧接触表：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\tools\art\candidates\semantic_split_v3\Invoke-SemanticSplitV3Preview.ps1
```

`Vivhite/local.props` 会提供 Godot 和游戏目录；无法解析时再显式传 `-GodotExe`、`-Sts2Dir`。输出固定留在 `.work/combat-rig-compare-preview/semantic-split-v3-ab/`，候选 authored 文件写入 `Vivhite/tools/candidates/semantic_split_v3/`。输出目录不得指向正式 `skins/`，也不要复用含旧报告的目录。

结果中应看到：

```text
<output>/summary.json                 # 21 点稠密 Vulkan 采样及 pairwise 结果
<output>/<candidate>/frames/          # 每动画原始 RGBA 帧
<output>/<candidate>/contact-sheets/  # 对照接触表
Vivhite/tools/candidates/semantic_split_v3/
  validation.json
  ab-contact-index.json
  semantic-split-v3-ab-overview.png
  contact-sheets/ab-<animation>.png
```

`ab-contact-index.json` 必须同时保留请求时间、实际最近采样时间和量化误差；近似采样不能被当成事件精确帧。若要确认 `attack_slash_start`、`heavy_slash_start`、`cast_eyes_start`、`clear_vfx`，仍需运行对应的 event-exact 验收，不得只凭接触表发布。

## 分步调试

需要定位哪一阶段失败时，可在 `tools/art` 项目中分别运行：

```powershell
$propsText = Get-Content .\Vivhite\local.props -Raw
$props = [xml]$propsText
$godot = [string]$props.Project.PropertyGroup.GodotExe

& $godot --headless --path .\tools\art `
  --script (Resolve-Path .\tools\art\candidates\semantic_split_v3\build_semantic_split_v3_candidate.gd) -- `
  build-semantic-split-v3

& $godot --headless --path .\tools\art `
  --script (Resolve-Path .\tools\art\candidates\semantic_split_v3\validate_semantic_split_v3_candidate.gd) -- `
  validate-semantic-split-v3
```

分步命令只用于诊断；不要手工编辑 `Vivhite/tools/candidates/semantic_split_v3/` 的 JSON/atlas 来“修绿”报告。失败时保留 `.work` 中的 stdout、stderr、`summary.json`、manifest 和图片证据，交给复盘/失败包流程。

## 生成和发布边界

本候选不调用 EvoLink，也不改变任何源 PNG 的 Alpha；新透明素材若获批准，必须先完成 atlas/源码消费审计，再按仓库 `AGENTS.md` 的 EvoLink 原生透明契约追加保存原图、逐字 Prompt 和去秘密请求参数（同一语义最多八次）。候选目录永远不能直接复制到 `Vivhite/Vivhite/skins/ironclad/`，也不会启动游戏、Brain 或直播。只有新的语义附件通过完整总装、PCK 和发布前门禁后，发布器才可从已验收源重新生成正式 runtime 镜像。
