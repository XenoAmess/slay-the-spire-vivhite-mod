# sts2-ascend 统一启动器 .NET SDK 自动发现

## 问题

从根仓直接执行 `sts2-ascend/scripts/Start-Agent.ps1` 时，本地 fork 部署会进入
`Deploy-Mod.ps1 -> third_party/STS2-Agent/scripts/build-mod.ps1`。外层 PowerShell
若只在 `PATH` 中解析到 runtime-only 的 `dotnet.exe`，构建会报
`It was not possible to find any installed .NET Core SDKs`。本机实际 SDK 安装在
`%LOCALAPPDATA%\Microsoft\dotnet`，但统一入口此前不会发现或继承它。

关键点是“能找到 `dotnet.exe`”不等于“该 host 能看到 SDK”；只检查文件存在或
`Get-Command dotnet` 都不足以证明构建环境可用。

## 解决方案

`Start-Agent.ps1` 在且仅在本次部署会构建本地 fork 时初始化 SDK 环境：

1. 优先探测当前 `PATH` 解析到的 `dotnet.exe`，并以 `dotnet --list-sdks` 非空且
   退出码为零作为可用条件。可用时立即返回，不改写调用方的 `DOTNET_ROOT` 或 `PATH`。
2. 当前 `PATH` 不可用时，依次检查既有 `DOTNET_ROOT\dotnet.exe` 与
   `%LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe`。候选同样必须通过 `--list-sdks`
   探测，不能因文件存在就采用。
3. 采用 fallback 后，仅为当前启动进程设置 `DOTNET_ROOT`，并在尚未包含该目录时
   将其置于 `PATH` 首位；路径全部来自环境变量，不硬编码用户名。
4. 所有候选都没有 SDK 时，在进入 fork 构建前以原有关键语义
   `It was not possible to find any installed .NET SDKs` 清晰失败。

`-SkipDeploy` 和官方 release 部署不增加 SDK 前置条件，游戏、runner、brain 与播报的
统一入口顺序和生命周期语义均未改变。

## 测试与注意事项

新增 `sts2-ascend/tests/test_start_agent_dotnet_discovery.py`。它是纯源码契约测试，
不调用 PowerShell、dotnet、游戏或其他外部进程，覆盖：

- `PATH` 不可用时，LOCALAPPDATA fallback 必须先验 SDK 再设置环境；
- 当前 `PATH` 的 dotnet 有 SDK 时，必须在任何环境写入前返回；
- 候选无 SDK 时跳过候选并保留清晰的 SDK 缺失错误；
- SDK 修复只包围本地 fork 部署，并发生在 `Deploy-Mod.ps1` 调用前。

验证还应单独使用 PowerShell AST 解析器检查 `Start-Agent.ps1` 语法，并运行
`git diff --check`。本次按任务约束没有执行统一启动入口，也没有启动或停止游戏。

后续若增加新的 SDK 安装约定，应追加环境变量派生候选并继续执行真实
`--list-sdks` 探测；不要退化为用户名硬编码或仅检查可执行文件是否存在。
