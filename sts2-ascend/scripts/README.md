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

`Stack ready` 只表示 Brain 存活且某个 8080–8084 `/health` 就绪；开播/恢复还需要真实对局、有效 run/state_version、驾驶舱心跳，以及同一局内两个不同 `decision_id` 且时间递增的近期 `applied` 回执。`state_version` 是合法快照标记，不要求逐动作递增；动作间的过渡状态不计作进展，但不会抹掉首个有效回执。开播前遇到 `MAIN_MENU`、`run_unknown`、等待/终局仍失败关闭；已经开播后，正常 `GAME_OVER` → 菜单 → 选角跨局采用两阶段门禁：最多 120 秒取得新局第一条 `applied`，随后独立 30 秒取得同一新局第二条连续回执。期间短暂空、`UNKNOWN`、`WAITING` screen 继承原阶段而不单帧下播，也不能重置计时；任一阶段超时才下播。

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
| `Start-BilibiliLive.ps1`、`Stop-BilibiliLive.ps1` | 直播姬开播/下播控制。开播前验证唯一 IndexTTS owner 已启用 3328 MiB CUDA 上限和 `staged_cuda` BigVGAN，直播期间继续提供克隆音色；不会停止游戏、Brain 或 runner。 |
| `Invoke-BilibiliLiveDailyStart.ps1` | 北京时间 `[23:00, 23:20)` 每分钟检查一次的有限权限协调器；只调用统一开播入口，真实游玩或显存门禁失败时由窗口内下一次检查重试。 |
| `Invoke-BilibiliLiveDailyStopWatch.ps1` | 北京时间 `[11:00, 11:20)` 每分钟检查一次的有限权限协调器；只有精确 `Streaming` 才调用统一下播入口，且不停止训练栈或 Quipper。 |
| `Invoke-BilibiliLiveHealthWatch.ps1` | 直播期间并行检查两条互不替代的证据链：显示器捕获错误/预览运动，以及当前 session 的 API、驾驶舱与 `applied` 动作回执。错误爆发与静帧相互印证时快速安全下播，单独低运动仅在连续五分钟后失败关闭；正常跨局按 120 秒首回执 + 30 秒第二回执的两阶段门禁观察，跨局外的 API/驾驶舱短暂不可读等暂态最多宽限 90 秒。同一 run 中只有新的 `decision_id` 且终局回执时间递增才重置语义时钟，预览动画、heartbeat 和 `state_version` 都不能替动作进展续命；watcher 无固定 12/24 小时运行上限，只随 `Streaming` 生命周期退出，下播后恢复 IndexTTS。 |

驾驶舱 `history` 行只保存终局回执的 `decision_id/status/at`，自身不携带 `run_id`。监测器因此只把它绑定到同一采样中 API 与驾驶舱共同确认的当前 run，首次仅建立基线；基线本身不算进展，后续必须在 run 未变化时看到不同 `decision_id` 和更晚的回执时间才会清零 90 秒语义卡死计时。

## 无人值守与 UAC 边界

脚本不执行需要人工确认的 UAC、原生模组同意弹窗或 Steam Workshop 法律协议。SteamMode `off` 若本地 profile 尚未完成原生同意，脚本必须保持 fail-closed，不能自动点击或把 API 缺失归咎于 Brain。Workshop 发布只复用已登录 Steam 客户端，详见 [`../../tools/workshop/README.md`](../../tools/workshop/README.md)。

直播桥安装器不得在直播中触发 UAC：请求 `RunAs` 前以及提权子进程开始后都必须重新读取直播姬状态，只有明确 `Idle`/`NotRunning` 才能继续。显示器捕获可能把 UAC 安全桌面或冻结画面播满屏，进而触发平台挂机/消极直播处罚；任何其他状态或读取失败均须在 UAC 前失败关闭。

生命周期状态位于 `sts2-ascend/.runtime/`（由 `lifecycle.STACK_ROOT` 解析）；不要手改或删除 `session.json`、PID、lock、stop sentinel、boot marker。停止流程会保留必要 sentinel 防止旧进程复活。

## 直播脚本的安全顺序

只有用户明确授权开播时，才按“启动/确认真实游玩 → 验证 Quipper 有界显存共存 → `Start-BilibiliLive.ps1` → 持续巡检”执行；下播只调用 `Stop-BilibiliLive.ps1`，不停止训练栈。直播中断恢复预算仅适用于已证明真实游玩的会话；证据丢失时立即下播，不为守两分钟红线空播或自动复播。

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
