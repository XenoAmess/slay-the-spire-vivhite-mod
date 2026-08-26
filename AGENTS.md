# AGENTS.md

## 项目简介

Slay the Spire 2（杀戮尖塔2）角色 Mod「白绮 Vivhite」。

- 新增角色**白绮**：专属卡池/遗物池/药水池、初始卡组（4 白绫打击 + 4 白绫防御）、初始遗物（白绸结）。
- 基于基础库 **RitsuLib**（游戏内依赖 mod id：`STS2-RitsuLib`）。
- Mod id：`Vivhite`。内容 ID 规则：`{MODID}_{类别}_{原名}`（如 `VIVHITE_CARD_VIVHITE_STRIKE`）。

## 技术栈与环境

- 游戏：**Slay the Spire 2 v0.111.0**（Godot 4.5.1 Mono 引擎）。
- 语言/框架：C# / .NET 9（`net9.0`），SDK 为 Godot.NET.Sdk 4.5.1。
- 教程站：<https://tutorials.sts2modding.com/>（RitsuLib 章节为主）。
- RitsuLib 仓库：<https://github.com/BAKAOLC/STS2-RitsuLib>，主分支 0.5.x 兼容游戏 0.111.0。

### 本机路径

| 项 | 路径 |
| --- | --- |
| 游戏目录 | `G:\SteamLibrary\steamapps\common\Slay the Spire 2` |
| 游戏 exe | `G:\SteamLibrary\steamapps\common\Slay the Spire 2\SlayTheSpire2.exe` |
| 启动方式 | `%command% --rendering-driver vulkan`（**必须 vulkan**；游戏根目录 `launch_vulkan.bat` 已封装） |
| mod 部署目录 | `<游戏目录>\mods\<ModId>\`（dll + json + pck 三件套） |
| 游戏日志 | `%APPDATA%\SlayTheSpire2\logs\godot.log`（当前会话） |
| .NET SDK | `C:\Users\xenoa\AppData\Local\Microsoft\dotnet`（9.0.317 + 8.0.30 运行时） |
| Godot 编辑器 | `C:\Users\xenoa\AppData\Local\Temp\opencode\godot\...\Godot_v4.5.1-stable_mono_win64.exe`（临时目录，丢失需重下 4.5.1 mono） |

### 环境注意

- 非 Steam 启动需游戏根目录有 `steam_appid.txt`（内容 `2868840`），已创建。
- Godot 编辑器运行依赖 .NET 8 运行时；需要环境变量 `DOTNET_ROOT=<dotnet目录>` 且 PATH 含 dotnet（已写入用户环境变量）。
- `local.props`（被 .gitignore 忽略）配置 `Sts2Dir` / `GodotExe`，是本机构建的前提。

## 构建与部署

```powershell
cd Vivhite
dotnet build                            # 编译 dll + 导出 pck + 自动复制到游戏 mods 目录
dotnet build /p:RunPckExport=false      # 仅编译 dll（跳过 Godot 打包，改纯 C# 代码时用）
```

- 首次 PCK 导出若 Godot 未导入过项目会较慢；可用 `godot --headless --path <proj> --import` 预热。
- manifest `Vivhite.json` 的 `dependencies[STS2-RitsuLib].version` 由构建自动同步为 NuGet 实际版本。

## 真机测试工具链

`tools/test/GameTest.psm1`（PowerShell 模块）：

- `Save-Screenshot -Path <png>`：截屏（可用 Read 工具直接看图）。
- `Get-OcrText -Path <png> -Language zh-Hans`：WinRT OCR（中英文）。
- `Invoke-MouseClick -X -Y` / `Move-Mouse`：鼠标。
- `Send-Key -VkCode 0x..` / `Send-Text -Text "..."`：键盘（SendInput 扫描码）。
- **控制台输入含空格的指令时用剪贴板粘贴**（逐键发送空格会被吞）：

```powershell
Set-Clipboard "card VIVHITE_CARD_VIVHITE_STRIKE"
# Ctrl+V 粘贴后回车
```

游戏内控制台：按 `` ` ``（0xC0）开启；`card <ID>` 发卡到手牌、`dump` 导出全部 ID、`win/kill/heal` 等详见教程站。

## 子项目：sts2-ascend（自动游玩智能体）

`sts2-ascend/` 是独立的自动游玩子项目：基于上游 mod [CharTyr/STS2-Agent](https://github.com/CharTyr/STS2-Agent)
（游戏内 HTTP API，`mods/` 根目录部署 `STS2AIAgent.dll/.pck/mod_id.json`，端口 8080+），
外挂一个纯 Python 标准库的自主学习大脑（`sts2-ascend/brain/`）。

- 启动：`powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-Agent.ps1`（默认后台运行）
- 大脑记忆在 `sts2-ascend/knowledge/`（stats/policy/progression/lessons/runs，已 gitignore，**不要手工改**）
- 上游 release 包在 `sts2-ascend/third_party/dist/`（gitignore，由 `scripts/Deploy-Mod.ps1` 自动下载）
- 上游修复流程：先在 fork（XenoAmess/STS2-Agent，本地克隆 `sts2-ascend/third_party/STS2-Agent`）main 验证，再拉分支提 PR。已提：#46（AoE药水）、#47（UNLOCK屏）、#48（CRYSTAL_SPHERE 占卜屏完整支持）。`Deploy-Mod.ps1 -Source auto` 在本地 fork clone 存在时优先构建 fork；只有显式 `-Source release` 才部署官方未补丁包。
- 详细见 `sts2-ascend/README.md` 与 `docs/2026-08-22-sts2-ascend自动游玩智能体.md`

### 自动游玩全栈启停（AI 必读）

以下命令都从仓库根目录执行：

```powershell
# 默认：按 Source 部署、Vulkan 启动游戏、后台启动 runner/brain
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-Agent.ps1

# 完整停止：brain/runner、碎碎念、复盘 opencode/viewer/speaker，以及游戏
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1

# 只停止智能体和播报/复盘链，保留游戏
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1 -KeepGame
```

- 用户说“启动/停止整套”“游戏 + brain + 播报员”时，AI **只使用上述统一入口**。不要分别拉起组件，不要泛杀 `python` / `uv` / `opencode`，也不要按 8080–8084 端口杀进程。
- `Start-Agent.ps1` 默认后台运行且幂等。`-SkipDeploy` 复用已部署 DLL；游戏已经运行时必须使用它，否则脚本会拒绝部署以避免 DLL 锁。`-Foreground` 仅用于调试，完整停止仍使用 `Stop-Agent.ps1`。
- `-Source auto`（默认）优先本地 fork、否则使用 release；`-Source fork` 强制 fork 构建；`-Source release` 强制官方包。自定义安装传 `-GameDir`，fork 构建可传 `-GodotExe`。
- “Stack ready”表示当前 session 的 brain 存活且 8080–8084 中某个 `/health` 已就绪。ASCEND-VISION 驾驶舱随 brain 启动，并由进程内监督器按心跳自愈；碎碎念在语音环境可用时由 brain 拉起，复盘 OpenCode 与复盘 speaker 仍按需出现。就绪等待超时只警告，runner 与驾驶舱监督器会继续在后台自愈，此时不要再启动第二套。
- 驾驶舱实时决策遥测是纯本地、确定性的 Python 标准库路径：只复用 Policy 本次已经计算出的观察、闸门、候选分数和结果，不重新评分，不调用 LLM、OpenCode、Minimax、OpenRouter 或任何网络服务，token 消耗为 0。遥测只写当前 session 的 `.runtime/live_dashboard.<SESSION_ID>.json`，采用有界队列和原子替换；异步复盘模型链本身仍可能消耗 token，二者不得混淆。
- ASCEND-VISION 必须在同一窗口使用状态驱动的稳定布局，不得按秒在整页 LIVE/REVIEW 间闪回：对局中显示决策主区和多行实时复盘流；`GAME_OVER` 显示趋势主区和复盘流；主菜单、等待或无新鲜决策时显示完整 REVIEW 视图；`--interactive` 可手动选择 LIVE/TREND/REVIEW。`knowledge/review_live.stream` 负责复盘文字展示，但不参与决策遥测、评分或动作选择。
- 楼层展示必须使用真实楼层口径 `floor_sum_raw` / `best_floor_raw`；历史 `floors_total` / `best_floor` 保留“真实楼层 + 胜利 50 分”的学习评分语义，不得拿来显示平均或最高楼层。
- 直播控制语义不变：开播仍先启动完整 sts2-ascend 栈并将杀戮尖塔2置于顶部，再通过本地哔哩哔哩直播姬开播；下播只操作直播姬，不停止任何服务、智能体或游戏。
- `Stop-Agent.ps1` 默认先发 session 哨兵，等待 40 秒协作保存/退出，再对经过 PID、创建时间、可执行文件、命令行和工作区校验的目标兜底；游戏先请求关窗，20 秒后才精确强停。`-WhatIf` 可无写入预览目标。
- `.runtime/` 由脚本维护。不要手改/删除 `session.json`、PID、lock 或 stop 文件；停止后保留的 GUID sentinel 用于防止旧进程“复活”（ABA），不是垃圾。`knowledge/` 的学习记忆同样不要手工修改。

生命周期维护规则：

- 新增长驻 Python 组件必须继承 `STS2_ASCEND_SESSION_ID`、`STS2_ASCEND_RUNTIME_DIR`、`STS2_ASCEND_STOP_FILE`，用 `brain/lifecycle.py` 的 `stop_requested()` / `wait_for_stop()` 响应停止；核心角色用 `pid_file(role)` 发布带 session 和精确创建身份的 PID 记录。
- 新增 detached 脚本或锁文件时，同步更新 `Start-Agent.ps1` 的残留拒绝清单，以及 `Stop-Agent.ps1` 的 scoped 进程、lock 和 marker 清单。身份校验不得退化为只看进程名、PID 或端口。
- 修改生命周期协议时必须同步更新 Start、Stop、AGENTS、README，并至少验证：冷启动、重复 Start、启动中 Stop、正常 Stop、重复 Stop、`-KeepGame`、复盘/TTS 活跃时 Stop，以及无关 Python/OpenCode 不被命中。

复盘安全与成果保全规则：

- **严禁重新引入“全仓指纹变化”、全仓脏状态或 refs 变化门禁。** 隔离复盘期间，真实仓的正常对局提交、推送、用户文件和运行日志变化均不得导致复盘成果作废。
- 复盘安全边界固定为：无 remote/无 hardlink 隔离 clone、复盘 patch 精确 allowlist、隔离自检、二进制 patch 验收，以及真实仓提交时的私有 index + compare-and-swap。不要用全仓扫描替代这些局部边界。
- 复盘 active 时在线 checkpoint 仍须正常提交并推送；不得因为长复盘（统一超时 8 小时）让直播进度长期只留在本地。
- `review_queue_max` 与 `max_runs_in_packet` 当前统一为 100；它们限制单批规模，不得截断持久队列。
- 超时、进程失败、自检失败、allowlist 拒绝或提交冲突时，必须把隔离仓内**全部工作树改动**（含越界、被忽略和被规则拒绝的文件）保存到 `knowledge/code_backups/review_salvage/` 供人工分析；clone/快照原件必须从创建起位于项目 ignored 的 `knowledge/code_backups/review_work/`，热停只准发布项目内指针并异步补齐；自动合入仍只准使用 allowlist patch，补合包永不自动应用。

## 工作流程规则

### 1. 完成后默认提交并推送

完成任何任务后，**默认执行** `git commit` 然后 `git push`，无需再次征求确认。

- 提交信息应简洁明了，说明本次改动的内容。
- 确保只提交与本次任务相关的文件。

### 2. 完成后将经验总结进 docs

完成任何任务后，**必须将经验总结写入 `docs/` 目录**。

- 若 `docs/` 目录不存在，则先创建它。
- 经验总结包括但不限于：
  - 遇到的问题及解决方案
  - 关键技术点和注意事项
  - 踩过的坑与避免方法
- 文件命名建议：`docs/YYYY-MM-DD-主题.md`，例如 `docs/2026-08-22-初始化项目.md`。
