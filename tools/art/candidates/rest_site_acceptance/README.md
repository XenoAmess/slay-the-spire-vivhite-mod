# `rest_site_acceptance`：休息地点离线验收

本目录验证白绮休息地点的私有 Spine 场景是否仍满足原版消费者合同：三个营地动作、翻转显示、火光开/关轨道、选中框/碰撞框和实际布局。它只在离线 Godot Windows/Vulkan 窗口中挂载游戏 PCK 并读取正式资源，不启动游戏、不部署 Mod、不改 PNG/Alpha，也不触碰 Brain 或直播。

## 固定合同

- Spine 版本必须是 4.2.43；场景位置 `(-2, 42)`、缩放约 `0.760006`，画布 1920×1080。
- 三个循环及持续时间：`overgrowth_loop` 5.0 s、`hive_loop` 3.6 s、`glory_loop` 4.4 s。每个循环都要在正向和水平翻转下产生闭合且有变化的帧序列。
- `_tracks/light_on` / `_tracks/light_off` 各 0.5 s，渲染结果必须可区分；三种 SourceOver 底色（营地、纯黑、纯白）用于检查透明边缘。
- 证据计数固定为 73 个实际渲染帧、219 个 SourceOver 合成、11 张接触表。缺一项即失败，不得用旧报告补齐。

## 运行

从仓库根目录执行：

```powershell
& .\tools\art\candidates\rest_site_acceptance\Invoke-RestSiteAcceptance.ps1
```

包装器从 `Vivhite/local.props` 读取 Godot 与 `Sts2Dir`，也可显式传参：

```powershell
& .\tools\art\candidates\rest_site_acceptance\Invoke-RestSiteAcceptance.ps1 `
  -GodotExe 'C:\path\Godot_v4.5.1-stable_mono_win64.exe' `
  -Sts2Dir 'G:\SteamLibrary\steamapps\common\Slay the Spire 2' `
  -OutputDir '.work/rest-site-acceptance/current'
```

`OutputDir` 必须位于仓库 `.work/` 下。为避免陈旧证据被误用，包装器会在运行前删除并重建它；只填写明确的 `.work` 子目录，不要把任何其他目录传给 `-OutputDir`。渲染器使用 `--rendering-driver vulkan`，并自动改用同目录的 `_console.exe`（若存在）。

## 输出和验收

通过后输出结构类似：

```text
.work/rest-site-acceptance/current/
  report.json
  contact-sheets/
    01-overgrowth-loop-camp.png ... 11-vivhite-vs-vanilla-actual-scale.png
  frames/<animation>/frame-*.png
  frames-flipped/<animation>/frame-*.png
```

`report.json` 必须显示 `success=true`、`display_server=Windows`、`rendering_driver=vulkan`，并记录正式 scene/Spine/atlas 路径、帧哈希、Alpha bbox、循环闭合性、翻转结果和 light-on/off 差异。人工复核接触表时，检查主体四角透明、白服/发丝边缘无矩形光晕、选中框与碰撞框未漂移；“脚本通过”只证明离线资源合同，不等于完整游戏流程或发布资格。

失败时保留整个输出目录（包括 stdout/stderr、报告和所有帧）交给复盘流程；不要改写 `report.json`、删除单帧或把 contact sheet 当作新的 atlas 输入。任何新透明素材仍须遵守仓库 `AGENTS.md` 的 EvoLink 原生透明、源码消费审计和八次尝试规则。
