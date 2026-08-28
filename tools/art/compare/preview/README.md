# 白绮战斗骨骼离线对照预览

该工具在不部署 Mod、不操作游戏窗口的前提下，用游戏本体 PCK 和游戏实际的 Spine GDExtension，对多个战斗骨骼候选执行同条件 Vulkan 渲染。

固定验收条件：

- 画布：`1280×900`
- 原版战斗场景 SpineSprite 缩放：`0.28`
- 候选制作比例契约：`70%`
- 场景偏移：`(5, -19)`
- 动画：`idle_loop`、`low_health_loop`、`relaxed_loop`、`attack`、`attack_heavy`、`cast`、`hurt`、`die`
- 每个动画至少均匀采样 5 帧
- 必须具有 `default` skin、`slash_mesh` / `eye_attach_slot` slot，以及四个战士 VFX event

## 使用

在仓库根目录的 PowerShell 中执行：

```powershell
& .\tools\art\compare\preview\Invoke-CombatRigComparePreview.ps1 `
    -Candidate @(
        'whole_mesh=Vivhite\tools\candidates\whole_mesh'
        'split_mesh=assets\vivhite-ironclad\candidates\split_mesh\combat'
    ) `
    -OutputDir '.work\combat-rig-compare-preview\whole-vs-split'
```

`-Candidate` 可重复接受 `Name=Path`。`Path` 可以是：

- 包含 `.tres/.spjson/.spatlas/PNG` 的候选目录；
- `SpineSkeletonDataResource .tres`；
- 单独的 `.spjson` 或 `.spatlas`，其余文件从同目录解析。

工具把每个候选复制到 Git 忽略且 PCK 排除的 `Vivhite/bin/combat_compare_preview/stage/`，重建只用于预览的 `.tres`。由于 Spine 运行时按 `.spatlas.source_path` 解析页图，工具只修正隔离副本的该字段，永不改候选源文件。正常结束后暂存副本会删除；`-KeepStage` 可保留它以便排错。

## 输出

输出始终位于 `.work/`：

- `<candidate>/frames/<animation>/`：原始全分辨率透明 Vulkan 帧；
- `<candidate>/contact-sheets/<animation>.png`：逐动画接触表；
- `<candidate>/contact-sheet.png`：八行动画总表，行顺序与上面的动画列表一致；
- `summary.json`：机器可读的契约与渲染指标；
- `candidate-manifest.json`：候选源路径和输入哈希；
- `index.html`：各方案总表入口。

`summary.json` 包括每帧的全分辨率 Alpha bbox、触边状态、Alpha 加权主体质心、相对首帧变化，以及每个动画的最大质心位移、最大像素变化率。bbox 和触边来自原始帧；质心和帧差在有界缩略副本上计算后映射回原画布，避免 GDScript 全像素循环拖慢 80–120 帧批次。缩略副本只用于指标，保存的帧没有任何后处理。

## 进程隔离

- 导入使用 headless Godot；正式捕获使用独立 Vulkan Godot。
- Vulkan 窗口由 `SW_HIDE` 启动、放到 `(-32000,-32000)`，并设置 `WINDOW_FLAG_NO_FOCUS`；不会聚焦或操纵正在运行的游戏。
- 同一 Godot 项目的导入和渲染由项目级 mutex 串行化，防止多个进程争用 Spine GDExtension 的 `~libspine...dll`。
- 工具不部署文件，也不启动、停止或重启游戏、brain、TTS 或直播。

只测试指标与接触表生成时可执行：

```powershell
& .\tools\art\compare\preview\Invoke-CombatRigComparePreview.ps1 `
    -SelfTest `
    -OutputDir '.work\combat-rig-compare-preview-self-test'
```
