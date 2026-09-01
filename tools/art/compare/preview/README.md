# 战斗 Spine 候选对照预览

`Invoke-CombatRigComparePreview.ps1` 是离线、多候选、固定布局的比较器。它把候选
复制到临时 stage，使用游戏本体 `SlayTheSpire2.pck` 和与游戏匹配的 Spine 4.2.43
GDExtension，在隐藏的 Windows/Vulkan 窗口中渲染；源候选、正式 runtime、游戏进程、
Brain 和直播都不会被修改或控制。

## 固定消费者契约

| 项目 | 默认值 / 要求 |
| --- | --- |
| 画布 | `1280×900`（`-Width` / `-Height` 可放大，最小 64） |
| 游戏场景 SpineSprite | `scene_scale=0.28`，偏移 `(5,-19)`，origin `(320,700)` |
| 候选制作比例 | `authored-character-scale=0.70`，脚本拒绝其他值 |
| 动画 | `idle_loop`、`low_health_loop`、`relaxed_loop`、`attack`、`attack_heavy`、`cast`、`hurt`、`die` |
| 采样 | 每动画至少 5 个均匀分数（`-Samples 5..21`） |
| 必需接口 | `default` skin、`slash_mesh` / `eye_attach_slot` slot、`attack_slash_start`、`heavy_slash_start`、`cast_eyes_start`、`clear_vfx` event |
| Alpha | 原始 RGBA 帧记录 bbox/触边；另以黑、白和游戏蓝灰底色复核观感 |

候选必须至少两个；候选路径可以是含 `.tres/.spjson/.spatlas/PNG` 的目录，或一个
明确的 `SpineSkeletonDataResource .tres`、`.spjson`、`.spatlas`。若目录里有多个同类
文件，工具会拒绝歧义，而不是猜一个。

## 推荐用法

从仓库根目录执行，最好让脚本从 `Vivhite/local.props` 读取 `GodotExe` 与 `Sts2Dir`：

```powershell
& .\tools\art\compare\preview\Invoke-CombatRigComparePreview.ps1 `
  -Candidate @(
    'whole_mesh=Vivhite/tools/candidates/whole_mesh',
    'hybrid_v3_final=Vivhite/tools/candidates/hybrid_v3_final'
  ) `
  -Samples 5 `
  -OutputDir '.work/combat-rig-compare-preview/whole-vs-final'
```

`Name=Path` 的 `Path` 是仓库相对路径，或 `res://...`（相对于 `-ProjectDir`）；不要
再使用早期文档里的 `Vivhite\tools\candidates\split_mesh` 旧目录名。候选输出实际
位于 `Vivhite/tools/candidates/`，而脚本源码位于 `tools/art/candidates/`。

只检查参数解析和隔离逻辑、不启动渲染时：

```powershell
& .\tools\art\compare\preview\Invoke-CombatRigComparePreview.ps1 `
  -SelfTest `
  -OutputDir '.work/combat-rig-compare-preview/self-test'
```

`-SelfTest` 与 `-Candidate` 是互斥参数集。真实渲染必须有 `SlayTheSpire2.pck`；
若 `local.props` 不可用，显式传 `-GodotExe`、`-Sts2Dir`、`-ProjectDir`。

## 隔离与输入处理

1. 包装器先校验基础 PCK、游戏/编辑器 Spine DLL 的 SHA-256，并取得项目级 mutex；
   同一 `Vivhite` 项目的导入与渲染不会并发争用 `libspine`。
2. 候选会复制到 `Vivhite/bin/combat_compare_preview/stage/<run-id>/`，这是 PCK 排除的
   临时目录。只改隔离副本的 `.spatlas.source_path`，不改源候选；正常结束后 stage
   删除，`-KeepStage` 仅用于排错。
3. Godot 先以 headless 模式导入，再以 Windows Vulkan、`SW_HIDE`、屏幕外坐标
   `(-32000,-32000)`、`WINDOW_FLAG_NO_FOCUS` 捕获。不要将 `--headless` 当作真实
   Alpha/Spine 渲染证据。
4. 输出路径必须在仓库 `.work/` 下，且已存在目录必须为空，防止旧报告与新候选混淆。

## 输出与判读

```text
.work/combat-rig-compare-preview/<run>/
  candidate-manifest.json       # 输入路径、候选哈希、PCK/DLL 信息
  summary.json                  # 机器可读契约、逐帧指标、pairwise 结果
  index.html                    # 候选总览
  <candidate>/frames/<anim>/*.png
  <candidate>/contact-sheets/<anim>.png
  <candidate>/contact-sheet.png
  import.*.log / render.*.log
```

`summary.json` 中的 bbox 与触边来自未处理原始帧；质心和帧差只在有界缩略副本上计算，
保存的 PNG 不会被缩放、抠图或改 Alpha。`success=true` 只代表结构、加载和自动指标通过，
不代表艺术上已发布；仍需真实游戏场景、UI、VFX、边缘污染和相邻附件的人工复看。

## 与单候选精确工具的关系

`hybrid_*` 目录中的 `Invoke-*-Preview.ps1` 会调用各自精确采样器，适合验证动作窗口、
原子 attachment 切换、EyeFire/VFX 生命周期等局部契约；本比较器适合统一八动画横向
比较。先跑候选自己的 validator，再跑 comparator；不要用比较器绕过候选的 lineage、
Alpha 或 `deployable=false` 闸门。

## 失败处理

失败时保留该次 `.work/<run>` 的完整日志、manifest 和 summary，交给复盘/失败包流程。
不要删除失败目录、复制旧 `.import`、把诊断灰盒当真材质，或手改报告为绿色。新透明
素材仍必须遵循仓库根 `AGENTS.md`：先完成 atlas/源码消费审计，使用 EvoLink 原生
透明 `gpt-image-2`，追加保存原图/Prompt/请求参数，同一语义最多八次付费尝试。
