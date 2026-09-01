# sts2-ascend/scripts — 生命周期与运维入口

本目录的脚本是自动游玩栈的唯一受支持运维入口。它们负责部署 Agent、冷启动/停止游戏与 Brain、检查 Steam 存档卷、维护 Bilibili 桥接和运行只读诊断。脚本从仓库根目录调用，路径和 session/runtime 由脚本解析，不要复制到临时目录运行。

## 训练栈（默认下播）

```powershell
# 幂等后台启动：部署（必要时）→ Vulkan 游戏 → runner → Brain/驾驶舱
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-Agent.ps1

# 完整协作停止
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1

# 保留游戏，只停止 Brain/runner/播报/复盘链
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1 -KeepGame
```

`Start-Agent.ps1` 常用参数：

| 参数 | 作用 |
| --- | --- |
| `-Source auto|fork|release` | 默认优先本地 fork；`release` 只部署官方未补丁包。 |
| `-SteamMode auto|on|off` | `auto/on` 保留 Steam 初始化；仅显式 `off` 才使用独立本地 profile。off 仍要求该 profile 已完成原生模组同意。 |
| `-SteamMinFreeBytes` | Steam-on 冷启动前的 userdata 卷可用空间下限，默认 1 GiB；低于下限直接 fail-closed。 |
| `-SkipDeploy` | 游戏已运行且已部署同批 DLL/JSON/PCK 时复用，避免 DLL 锁；不会跳过就绪/身份检查。 |
| `-Foreground`、`-ReadyTimeoutSeconds` | 调试前台输出或调整有界就绪等待。 |

参数说明：

```powershell
Get-Help .\sts2-ascend\scripts\Start-Agent.ps1 -Full
Get-Help .\sts2-ascend\scripts\Stop-Agent.ps1 -Full
```

`Stack ready` 只表示 Brain 存活且某个 8080–8084 `/health` 就绪；开播/恢复还需要真实对局、有效 run/state_version、驾驶舱心跳、近期 `applied` 回执和连续状态推进。任何 `MAIN_MENU`、`run_unknown`、等待/终局阻塞或动作停滞都保持失败关闭。

## 部署与诊断脚本

| 脚本 | 用途 |
| --- | --- |
| [`Deploy-Mod.ps1`](Deploy-Mod.ps1) | 从 fork 或官方 release 构建/复制 `STS2AIAgent.dll/.pck/mod_id.json`；游戏运行时 DLL 锁定会拒绝部署。 |
| [`release_orphan_run.py`](release_orphan_run.py) | 停栈后一次性处理“无原生存档/Continue”孤儿局负证据；默认只读，缺证据即拒绝。 |
| [`reset_profile_statistics.py`](reset_profile_statistics.py) | 受控、可审计的 Profile 统计重置；先阅读专项文档并保存备份。 |
| [`review_model_eval.py`](review_model_eval.py) | 离线复盘模型评测，不是生产 runner。 |
| [`prepare_reference_voice.py`](prepare_reference_voice.py) | 生成/核验 TTS 参考音频条件缓存，支持 `--dry-run`。 |
| [`Install-CodexCompat.ps1`](Install-CodexCompat.ps1) | 安装并校验固定版本的 Windows Codex CLI 兼容缓存；不写入密钥。 |
| `BilibiliLive.psm1`、`Test-BilibiliLive.ps1` | 直播桥接的状态/连接测试模块。 |
| `Install-BilibiliLiveBridge.ps1`、`Invoke-BilibiliLiveBridge.ps1` | 一次性安装或调用本地直播姬桥接；安装可能需要交互式管理员/UAC 授权，绝不在无人值守任务中执行。 |
| `Start-BilibiliLive.ps1`、`Stop-BilibiliLive.ps1` | 直播姬开播/下播控制。它们不会被训练脚本自动调用；当前用户要求下播时严禁调用开播入口。 |
| `Invoke-BilibiliLiveDailyStopWatch.ps1` | 已授权直播期间的每日停止观察；不是自动复播器。 |

## 无人值守与 UAC 边界

脚本不执行需要人工确认的 UAC、原生模组同意弹窗或 Steam Workshop 法律协议。SteamMode `off` 若本地 profile 尚未完成原生同意，脚本必须保持 fail-closed，不能自动点击或把 API 缺失归咎于 Brain。Workshop 发布只复用已登录 Steam 客户端，详见 [`../../tools/workshop/README.md`](../../tools/workshop/README.md)。

生命周期状态位于 `sts2-ascend/.runtime/`（由 `lifecycle.STACK_ROOT` 解析）；不要手改或删除 `session.json`、PID、lock、stop sentinel、boot marker。停止流程会保留必要 sentinel 防止旧进程复活。

## 直播脚本的安全顺序

只有用户明确授权开播时，才按“启动/确认真实游玩 → `Start-BilibiliLive.ps1` → 持续巡检”执行；下播只调用 `Stop-BilibiliLive.ps1`，不停止训练栈。直播中断恢复预算仅适用于已证明真实游玩的会话；证据丢失时立即下播，不为守两分钟红线空播或自动复播。

## 修改脚本后的检查

```powershell
# PowerShell 语法解析（不启动任何组件）
Get-ChildItem .\sts2-ascend\scripts -Filter *.ps1 | ForEach-Object {
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $_.FullName, [ref]$null, [ref]$null)
}

# 相关 Python 合同测试
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_start_agent_*.py"
```

修改 Start/Stop 协议时还要同步更新根 `AGENTS.md`、[`../README.md`](../README.md) 和本 README，并验证冷启动、重复 Start、启动中 Stop、正常/重复 Stop、`-KeepGame` 及复盘/TTS 活跃场景。
