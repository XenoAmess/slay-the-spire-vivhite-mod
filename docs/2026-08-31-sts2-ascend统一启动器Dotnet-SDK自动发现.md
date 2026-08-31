# sts2-ascend 统一启动器 .NET SDK 自动发现

## 问题

从根仓直接执行 `sts2-ascend/scripts/Start-Agent.ps1` 时，本地 fork 部署会进入
`Deploy-Mod.ps1 -> third_party/STS2-Agent/scripts/build-mod.ps1`。外层 PowerShell
若只在 `PATH` 中解析到 runtime-only 的 `dotnet.exe`，构建会报
`It was not possible to find any installed .NET Core SDKs`。本机实际 SDK 安装在
`%LOCALAPPDATA%\Microsoft\dotnet`，但统一入口此前不会发现或继承它。

关键点是“能找到 `dotnet.exe`”不等于“该 host 能看到 SDK”；只检查文件存在或
`Get-Command dotnet` 都不足以证明构建环境可用。

### 首版修复的实机漏项

首版修复 `c5f68d86` 能用明确路径验证用户目录 SDK，却只在候选 root **完全不在**
`PATH` 时才 prepend。真实冷启动环境的顺序是：

1. `C:\Program Files\dotnet\dotnet.exe`：runtime-only，`--list-sdks` 无输出、退出码 0；
2. `%LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe`：能列出 SDK `9.0.317`。

用户 SDK root 已位于 `PATH` 后方，因此旧判断得到 `pathContainsRoot=true`，没有改变
顺序。随后 `build-mod.ps1` 调用裸 `dotnet build`，仍然命中第一项的坏宿主并再次报
`It was not possible to find any installed .NET Core SDKs`。首版测试只检查“包含候选”
和源码写入顺序，没有构造“坏宿主在前、已验证候选已在后”的优先级场景，也没有验证
后续裸 `dotnet` 的实际命令解析；这是本次实机失败未被测试拦住的直接原因。

## 解决方案

`Start-Agent.ps1` 在且仅在本次部署会构建本地 fork 时初始化 SDK 环境：

1. 优先探测当前 `PATH` 解析到的 `dotnet.exe`，并以 `dotnet --list-sdks` 非空且
   退出码为零作为可用条件。可用时立即返回，不改写调用方的 `DOTNET_ROOT` 或 `PATH`。
2. 当前 `PATH` 不可用时，依次检查既有 `DOTNET_ROOT\dotnet.exe` 与
   `%LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe`。候选同样必须通过 `--list-sdks`
   探测，不能因文件存在就采用。
3. 采用 fallback 后，仅为当前启动进程设置 `DOTNET_ROOT`；无论候选 root 此前是否
   已在 `PATH` 中，都先移除它的全部重复项，再把规范化 root 固定放到第一项，确保
   后续子脚本的裸 `dotnet` 解析到刚验证的 executable。路径全部来自环境变量，不硬编码用户名。
4. 所有候选都没有 SDK 时，在进入 fork 构建前以原有关键语义
   `It was not possible to find any installed .NET SDKs` 清晰失败。

`-SkipDeploy` 和官方 release 部署不增加 SDK 前置条件，游戏、runner、brain 与播报的
统一入口顺序和生命周期语义均未改变。

## 测试与注意事项

`sts2-ascend/tests/test_start_agent_dotnet_discovery.py` 保留源码契约测试，并新增隔离
PowerShell harness。harness 只加载 SDK 初始化函数，以临时空 `dotnet.exe` 文件模拟
前方坏宿主和后方候选，并用 mock SDK probe 避免执行任一 fake executable；它不加载
`Start-Agent.ps1` 主体、不部署，也不启动游戏或 Brain。覆盖：

- `PATH` 不可用时，LOCALAPPDATA fallback 必须先验 SDK 再设置环境；
- 当前 `PATH` 的 dotnet 有 SDK 时，必须在任何环境写入前返回；
- 坏 dotnet 位于第一项、候选 root 已在后方且重复出现时，修复后候选必须成为唯一的
  第一项，并且 `Get-Command dotnet.exe`（即后续裸命令的解析）必须命中候选 executable；
- 候选无 SDK 时跳过候选并保留清晰的 SDK 缺失错误；
- SDK 修复只包围本地 fork 部署，并发生在 `Deploy-Mod.ps1` 调用前。

验证还应单独使用 PowerShell AST 解析器检查 `Start-Agent.ps1` 语法，并运行
`git diff --check`。本轮闭环按任务约束没有执行统一启动入口、Start/Stop、部署，也没有
启动或停止游戏；最终冷启动验证留给主线程使用默认统一入口完成。

后续若增加新的 SDK 安装约定，应追加环境变量派生候选并继续执行真实
`--list-sdks` 探测；不要退化为用户名硬编码或仅检查可执行文件是否存在。
