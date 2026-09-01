# Hybrid V3 runtime VFX bridge acceptance

`vfx_bridge/` 是一个最小、隔离的 C# + Godot harness，用来复核 `NIroncladVfx` 在
cast 重启、中断和 `EyeFire` 清理时的真实事件顺序。它不是游戏 Mod，也不部署 DLL/PCK；
所有编译、导入、运行日志和 `summary.json` 都必须落在 `.work/`。

## 运行

从仓库根目录执行：

```powershell
& .\tools\art\candidates\hybrid_v3_final\vfx_bridge\Invoke-RuntimeVfxAcceptance.ps1 `
  -GameDir 'G:\SteamLibrary\steamapps\common\Slay the Spire 2'
```

实际使用时可省略路径参数，让脚本从 `Vivhite/local.props` 读取；若 props 不可用，
请显式传完整 Godot 可执行文件路径（不要把 `Get-Content` 的 MatchInfo 对象直接作为参数）：

```powershell
[xml]$props = Get-Content .\Vivhite\local.props -Raw
$godot = [string]$props.Project.PropertyGroup.GodotExe
& .\tools\art\candidates\hybrid_v3_final\vfx_bridge\Invoke-RuntimeVfxAcceptance.ps1 `
  -GodotExe $godot `
  -GameDir 'G:\SteamLibrary\steamapps\common\Slay the Spire 2'
```

脚本会创建带 run-id 的输出子目录，
复制最小项目文件，运行 `dotnet build`、Godot import，再以 Windows Vulkan 执行
`run_runtime_vfx_interruptions.gd`。`RuntimeVfxHarness.cs` 只提供本地测试桥接。

## 验收含义

成功报告应证明 cast 在 active window 重启时先清理 stale external EyeFire，再按事件
显示/隐藏；中断后 slash/sigil/eye 不得残留。它只验证 VFX 生命周期，不替代 final 的
Spine/动画/merchant/PCK 门禁或真实游戏出牌回归。失败时保留 `build.*.log`、`import.*.log`、
`run.*.log` 和 summary，不手改结果，也不启动正式游戏。
