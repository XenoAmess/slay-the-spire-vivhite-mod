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
| 启动方式 | `%command% --rendering-driver vulkan`（**必须 vulkan**；根目录 `launch_vulkan.bat` 已封装） |
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
