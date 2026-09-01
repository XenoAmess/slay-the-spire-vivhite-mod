# `tools/test`

这里是白绮 Vivhite 的 Windows 真机辅助工具和发布前 PCK 内容闸门。工具分成两类：

| 文件 | 用途 | 是否会触碰游戏 |
| --- | --- | --- |
| [`GameTest.psm1`](GameTest.psm1) | 截图、OCR、鼠标和键盘输入的 PowerShell 模块 | 导入模块本身不会；调用输入函数会把真实输入发送到当前桌面 |
| [`Verify-VivhitePck.ps1`](Verify-VivhitePck.ps1) | 对已经生成的 `Vivhite.pck` 做只读四层内容验收 | 不启动游戏，不部署，不修改 PCK；会启动隔离的 Godot 子进程 |
| [`Verify-VivhitePck.Tests.ps1`](Verify-VivhitePck.Tests.ps1) | `Verify-VivhitePck.ps1` 的自包含行为回归套件 | 使用合成 PCK/伪 Godot，不连接 Steam 或真实游戏 |

## 前置条件

- Windows PowerShell 5.1（`powershell.exe`）。OCR 依赖 Windows Runtime，截图和输入依赖
  `System.Windows.Forms`/`System.Drawing`；在无桌面的 CI 中不要调用 `GameTest.psm1` 的交互函数。
- PCK 闸门需要 Godot 4.5.1 Mono。默认从 `Vivhite/local.props` 读取 `Sts2Dir` 和 `GodotExe`；也可以在命令行显式传路径。
- 运行时验收的构建、部署和游戏启动仍由 [`Vivhite/README.md`](../../Vivhite/README.md) 和统一脚本负责。本目录的脚本不会申请 UAC，也不会启动直播。

## 截图、OCR 和显式输入

只在已经确认目标窗口、并且确实需要人工验收时使用。`Invoke-MouseClick`、`Send-Key`、
`Send-Text` 会改变桌面状态，可能把焦点从游戏移走；它们不是无人值守训练接口，也不能用于
处理 UAC/模组同意框。训练栈应使用 `sts2-ascend/scripts/Start-Agent.ps1` 的受控 API 路径。

```powershell
Import-Module .\tools\test\GameTest.psm1 -Force

# 输出目录建议放在 .work/，不要把临时截图混入运行时素材
Save-Screenshot -Path .\.work\screenshots\manual-check.png
Get-OcrText -Path .\.work\screenshots\manual-check.png -Language zh-Hans

# 仅在明确知道坐标和前台窗口时使用
Move-Mouse -X 960 -Y 540
Invoke-MouseClick -X 960 -Y 540
Send-Key -VkCode 0xC0       # ` 键，打开游戏控制台
Send-Text -Text 'dump'
```

含空格的控制台命令不要逐字发送空格；按项目约定使用剪贴板粘贴后回车。截图中的透明
素材判定仍必须按根 [`AGENTS.md`](../../AGENTS.md) 的 Alpha/SourceOver 规则进行，普通
查看器或黑底缩略图不能替代程序化检查。

## 只读 PCK 内容闸门

从仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\test\Verify-VivhitePck.ps1
```

默认从 `Vivhite/local.props` 推导 `mods\Vivhite\Vivhite.pck`。隔离构建产物或其他安装位置
可以显式指定：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\test\Verify-VivhitePck.ps1 `
  -RepoRoot (Get-Location).Path `
  -PckPath 'G:\staging\Vivhite.pck' `
  -GodotExe 'C:\tools\Godot_v4.5.1-stable_mono_win64.exe' `
  -EvidenceRunId 'manual-check-20260901'
```

闸门会在空的临时 Godot 项目中依次检查：

1. 已批准的运行时美术集合是否精确为 92/92；
2. V3 Ironclad skin 的源文件/发布文件契约是否为 30/34；
3. 英文和简体中文各 6 个本地化文件、每种语言 314 个 key 及术语约束；
4. 挂载真实 PCK 后，卡牌、能力、遗物、能量、三类 VFX、纹理导入和 NOPE 兜底是否全部可解析；
5. 校验前后 PCK SHA-256 是否保持不变。

成功时每次运行的临时目录会清理，但 `.tmp/vivhite-pck-gate-events.jsonl` 生命周期日志会保留。
失败时不要删除证据目录；脚本会输出 `.tmp/vivhite-pck-gate-<run-id>/`，其中包含报告、Godot
日志、输入哈希和 `failure.json`。这些证据用于修复和复核，不是运行时知识，不能手改
`sts2-ascend/knowledge/` 或 `.runtime/`。

## 行为回归套件

该套件不使用 Pester，而是自包含的 PowerShell 测试进程。它会构造合成归档、伪 Godot 和
故障场景，验证等待子进程、UTF-8 中文往返、临时目录清理失败时的证据保全等契约：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\test\Verify-VivhitePck.Tests.ps1
```

可以传 `-RepoRoot` 在临时检出中运行。测试失败时保留的证据位于该仓库 `.tmp/` 下；不要
用删除临时目录或放宽断言的方式“修复”测试。

## 与其他验收层的关系

- [`tools/art/`](../art/README.md) 负责素材提取、候选渲染和静态美术契约；本目录只验证最终
  PCK 消费结果。
- [`Vivhite/tools/Validate-IroncladSkin.ps1`](../../Vivhite/tools/Validate-IroncladSkin.ps1)
  是被 PCK 闸门隔离调用的 skin 契约检查器。
- Workshop 发布前必须先通过本闸门，再由 [`workshop/`](../../workshop/README.md) 的统一
  发布流程同步三件套、BBCode 和预览图。

