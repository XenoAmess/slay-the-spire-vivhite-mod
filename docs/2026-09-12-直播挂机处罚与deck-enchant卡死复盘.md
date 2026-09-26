# 2026-09-12 直播挂机处罚与 deck-enchant 卡死复盘

## 结论

14:42 的下播不是本地静帧守护误停，也没有证据表明平台识别了“非真人直播”。这次直播在 14:27:15 起已经真实失去游戏进展：Brain 在扭曲锤子的 `deck_enchant_select` 界面持续空确认，动作每轮超时后又被重新评估为同一个空确认。平台于 14:42:46 下发 `cut_off_v2_danmaku, scene:1` 并关闭直播，时间上对应约十五分钟无有效游戏动作。

## 时间线与证据

- 14:26:41，`knowledge/brain.log` 记录购买遗物“扭曲锤子”。
- 14:27:15，Agent 状态进入 `CARD_SELECTION/F27`：`kind=deck_enchant_select`、`min_select=0`、`max_select=3`、`selected_count=0`、`can_confirm=true`。Brain 选择 `confirm_selection`。
- 随后每轮都出现 11 次“丢失回执、尚无动作特定效果”，达到重试上限后只释放短冷却，再次选择同一个 `confirm_selection`；屏幕、选择数和楼层均未推进。
- 14:42:00，本地 `capture-health-watch.log` 只有 `stale_preview_without_capture_errors`，连续低运动计数为 4/46；到 14:42:46 也只有 11/46，且没有新的 `887A0001` 捕获错误爆发。
- 14:42:46，直播姬日志先收到平台 `cut_off_v2_danmaku,scene:1`；14:42:47 才出现 RTMP 断开及 `live room is closed, cmd=PREPARING`。本地守护随后只观察到 `Idle` 并恢复 TTS，没有写入 `watch=safety_stop`。

因此，平台切断发生在本地守护的任何停止条件之前；直播画面虽仍有少量动画像素变化，游戏语义已经卡死。

## 根因

直接根因在 Brain 策略层，不在 MCP：事发进程的 `/health` 明确报告 `mcp_enabled=false`。Brain 把 API 的 `min_select=0` 当作“可以立即空确认”，且确认分支位于选卡分支之前。

Agent/HTTP API 层同时暴露了一个次要契约缺口：`can_confirm` 由选择数量和偏好值推导，因此零选时为真；但该阶段没有实际可生效的确认控件。`confirm_selection` 最终只会等待约十秒并返回 pending。这个不一致放大了 Brain 的错误，但不是 MCP 调用造成的。

## 修复

1. Brain 对 `deck_enchant_select` 使用独立语义：确认目标为 `min(max_select, 有效候选数)`，本次即三张；未达到目标前继续选择，达到后才确认。其他真正允许零选的界面保持原行为。
2. 恢复已有部分选择时排除 `selected=true` 的卡，避免 Brain 重启后反点取消。
3. 附魔选择使用 `card_enchant` 审计标签，不写入 `card_pick` 学习归因。
4. `BilibiliLive-HealthWatch` 在像素/捕获检查之外增加独立的真实游玩语义时钟。只有同一 `run_id` 中新的 `applied` 决策回执（不同 `decision_id` 且 `outcome.at` 递增）才能重置；dashboard 心跳、预览动画和 `state_version` 本身都不能重置。初版把主菜单与终局单次判为硬失败，导致 20:53:55 在 Brain 正常 `GAME_OVER` 自动换局时误停；第一轮修订虽加入跨局窗口，但 23:40:07 又证明游戏会在 `GAME_OVER` 与新菜单之间短暂报告 `UNKNOWN`，旧硬失败分支仍于窗口开始 20 秒后误停。最终修订把空、`UNKNOWN`、`WAITING` screen 作为有界不可验证样本：已有跨局窗口时继承其原始起点与截止时间，跨局外则最多宽限 90 秒，均不算动作进展。已经开播时的 `GAME_OVER`、胜利/结算、主菜单和选角进入独立 90 秒跨局窗口；新局第一条 `applied` 只建立基线，第二条连续回执才证明恢复，超时以 `cross_run_transition_timeout` 下播。开播前硬闸不变，短暂 API/dashboard 不可读仍只使用有界宽限；普通对局持续无新动作时以 `semantic_gameplay_stall` 下播。

原有捕获门禁不变：`887A0001` 与预览不新鲜共同出现时走三次快速路径；只有低运动、没有捕获错误时仍需完整五分钟观察窗。

## 验证

- `brain/selfcheck.py` 新增零选、部分已选、选满确认及普通零选界面的回归，完整自检通过。
- 16:45:54 只重启 Brain/runner、保留游戏和原生对局后，新策略依次附魔两张“尺度变换+”和一张“绯色面积+”；16:46:01 已返回商店，16:46:03 进入地图，随后进入 F28 战斗。
- 新 session `a725a7ab47f54fc58a31dfa0d457c2eb` 的 dashboard 连续记录了不同 `decision_id` 的 `applied` 回执；直播姬在整个修复与验收期间保持 `Idle`。

## 直播跨局追踪

- 23:39:47，受保护 watcher 首次进入新规则的 `cross_run_transition`；23:40:07 游戏短暂报告 `UNKNOWN`，当时已安装版本仍将其判为 `passive_or_unknown_screen` 硬失败并于 23:40:09 下播。巡检确认新局 `DTB8Y84PAV3N` 的真实动作后，于 23:40:52 恢复 `Streaming`。
- 23:53:57 至 23:54:44，下一次跨局没有采到 `UNKNOWN`：旧局 `KYH2DF13FCTX` 经 `GAME_OVER`、`CHARACTER_SELECT`，在新局 `ATYAH1GXFRXQ` 先建立首条 `applied` 基线，再由第二条回执恢复 `Progressed`；全程 47 秒且直播未中断，证明跨局状态机的主路径正确。
- 00:00:31，`ATYAH1GXFRXQ` 再次进入 `GAME_OVER`；00:00:51 再次采到 `UNKNOWN` 并复现相同误停，排除平台切断或新 Brain 卡死。巡检在新局 `PBDNR4FWTDKU` 取得真实动作后，于 00:01:53 重启 watcher、00:01:55 完成受控复播。
- 空/`UNKNOWN`/`WAITING` 的源码修复已通过 59 项 Bilibili 脚本测试。受保护副本更新需要直播精确 `Idle` 时的一次 UAC；本次部署提示被用户取消，因此不得自动再次提示，当前继续由旧版 watcher 失败关闭和附着式两小时巡检作受控恢复，直到获得新的明确安装请求。

## 两小时驻守结果

- 驻守窗口为 2026-09-12 23:24:50 至 2026-09-13 01:24:50（北京时间）；附着式巡检于 01:24:56 正常结束，当时直播为 `Streaming`、健康任务为 `Running`，累计确认 455 次新的 `applied` 进展采样。
- 窗口内 watcher 记录 11 次跨局开始、8 次新局基线建立、0 次 `cross_run_transition_timeout`。其中 8 次跨局完整取得新局第二条回执而保持直播；另外 3 次分别在 23:40:07、00:00:51、00:31:38 被旧安装副本对单次 `UNKNOWN` 的硬失败分支提前中断。三次停止的 `capture_signal` 均为 `Healthy`，且在确认新局真实动作后分别受控恢复。
- 捕获侧没有任何新 `887A0001`，没有 `prolonged_low_motion`，仅有 6 条孤立 `degraded` 低运动样本，均未形成停止条件。因此这三次下播不是显示器捕获冻结，也没有本地证据支持“平台识别非真人直播”。
- 23:44:54 另有一次为部署前按规则主动下播；UAC 被取消后，23:47:46 才恢复直播。这是一次人工维护中断，不计入 watcher 的三次安全停止，且超过了两分钟恢复预算，必须保留为流程事故。
- 驻守结束后 watcher 继续独立运行。01:27:31 Brain 仍有新 `applied` 回执；01:27:38 API 短暂报告 `UNKNOWN`，旧安装副本立即写入 `passive_or_unknown_screen`，01:27:40 安全下播。由于附着式两小时巡检已经到期，这次没有自动复播。01:42 复核时直播姬精确为 `Idle`，但 Brain 已在新局 `Y5W9ZQ19Y5FB` 的 F12 战斗中，于 01:42:24、01:42:25、01:42:27 连续执行两次出牌和结束回合，排除 Brain 卡死。
- 仓库源码已经把跨局内的空/`UNKNOWN`/`WAITING` 绑定到原 90 秒截止时间，并给跨局外的同类瞬态最多 90 秒宽限；2026-09-13 再次运行完整 Bilibili 脚本测试为 59/59 通过。但 `C:\Program Files\VivhiteBilibiliLiveBridge\BilibiliLive.psm1` 与仓库源码哈希仍不同，说明 UAC 取消后修复从未部署到实际 watcher。当前直接根因是受保护拦截器的部署缺口，不是 MCP 或 Brain。

## 受保护副本最终部署

- 02:03 用户重新明确请求 UAC 安装。安装前重新完成 59/59 脚本测试，确认直播姬精确为 `Idle`，并验证 2026-09-13 16:00 停播和 23:00 开播的北京时间、本地时间、UTC 与只读计划触发器完全一致。
- 本次 UAC 获得批准，提权安装成功。安装后五份受保护文件 SHA-256 全部与仓库源码一致，其中 `BilibiliLive.psm1` 为 `E12D2F3B545E9A5657D6CB5A93DCB776A563A70104FED55B2DF638722FCCF7B3`；五项任务的运行级别正确，16:00/23:00 两项完整日期边界及 `NextRunTime` 均通过复核。
- 随后按用户要求调用统一 `Start-BilibiliLive.ps1`。开播前取得新局 `2FPX7RX6TZW4` 的两条独立 `applied` 证据，并通过 Quipper 单 owner、3328 MiB allocator 上限和 `staged_cuda` 门禁。02:06 独立复核为直播姬 `Streaming`、HealthWatch `Running`；02:06:26、02:06:27、02:06:29 又连续记录出牌、出牌、结束回合，证明开播后仍在真实游玩。

## 16:00 定时下播退役

- 15:45 用户明确取消按时钟自动下播规则并授权 UAC。源码删除 `Get-BilibiliDailyStopWindow`、`Get-BilibiliDailyStopSchedule`、`Test-BilibiliDailyStopRequired` 和专用 `Invoke-BilibiliLiveDailyStopWatch.ps1`；安装器改为升级时精确注销旧任务并删除旧受保护 worker，只保留 23:00 每日开播。现行 50 项 Bilibili 脚本测试全部通过，23:00 的北京时间、本地时间、UTC 与只读触发器一致。
- 第一次维护于 15:45:31 确认 `Idle`，但 UAC 长时间未返回；达到两分钟恢复优先级后中止父流程并恢复直播，15:48:55 才重新达到 `Streaming`。该次约 3 分 24 秒的实际中断超过预算，保留为人工授权等待事故，不宣称安装成功。
- 用户随后于 15:49 再次明确要求发起 UAC。15:49:32 确认 `Idle`，提权安装成功；安装后四份现行文件哈希全部一致，旧 `BilibiliLive-DailyStopWatch` 任务和旧受保护 worker 均不存在，23:00 每日开播的完整 `StartBoundary` 与 `NextRunTime` 正确。
- 15:50:46 恢复 `Streaming`，本次从 `Idle` 到复播约 75 秒，符合两分钟预算。独立复核显示 HealthWatch `Running`，新局 `6ZSYF39WNPKK` 于 15:51:08、15:51:09、15:51:10 连续执行出牌、出牌、结束回合；当前不再存在任何按时钟自动下播入口。

## 2026-09-15 跨局边界竞态与监控寿命修正

- 06:37:41，HealthWatch 从旧局 `GAME_OVER` 开启跨局计时。Brain 随后正常执行终局收尾、复盘和 Git 事务，并于 06:38:50 开始下一局选择、06:38:58 至 06:39:00 完成一次受控热重启。06:39:05 已出现新 `run_id`，但 screen 仍为 `UNKNOWN`；06:39:12 新局进入 `MAP` 并取得第一条权威 `applied` 回执，此时旧单窗口已运行约 91.6 秒。
- 旧状态机把“等待新局出现”和“取得新局第二条连续回执”共用同一个 90 秒截止时间。它虽然先识别了 06:39:12 的新局基线，却在同一次判断中继续套用原截止时间，以 `cross_run_transition_timeout` 调用本地 GUI 下播。直播姬 06:39:14 明确记录 `User stopped the stream`，捕获侧为 `Healthy`、lag 仅 0.4%，且没有 `cut_off_v2`；因此这是本地 watcher 的边界误停，不是平台切断，也不是 Brain 卡死。新局从 06:39:09 起已有事件、选牌、地图和战斗动作，之后持续推进。
- 当前源码把跨局门禁拆成两阶段：第一阶段从首次过渡起最多 120 秒，只等待新 `run_id` 的第一条权威 `applied`；第一条到达后立即开启独立 30 秒证明阶段，只等待同一新局中不同 `decision_id` 且更晚 `outcome.at` 的第二条回执。空、`UNKNOWN`、`WAITING`、heartbeat、预览运动、`state_version` 和重复的第一条回执均不能重置任何阶段；120 秒无首条或首条后 30 秒无第二条仍以 `cross_run_transition_timeout` 失败关闭。普通活动对局的 90 秒语义卡死门禁保持不变。
- 同时移除 watcher 脚本的 24 小时自退参数/截止时间，并把计划任务的 12 小时 `ExecutionTimeLimit` 改为无限；任务仍使用 `MultipleInstances IgnoreNew` 保持单实例，watcher 在 Livehime 不再为 `Streaming` 时自行退出。这样直播跨越半天或整天时不会静默失去本地守护。
- 新增回归用例精确复现“84.9 秒仍未知、91.6 秒首条新局回执、随后第二条回执”的时序，并覆盖首条回执重复 30 秒后的失败关闭及两个阶段的迟到回执不能越过硬截止线；完整 Bilibili 脚本测试为 53/53 通过。
- 本轮遵照用户“先不 UAC、本人不在”的要求，只修改仓库源码、测试和事实源，没有启动安装器、没有写入 `C:\Program Files`、没有变更计划任务，也没有触碰直播状态。受保护安装副本仍需用户在场并明确授权 UAC 后才会获得本修复；在此之前不得把源码通过误报为生产 watcher 已更新。

## 2026-09-16 每日直播窗口重新启用

- 用户将现行计划明确改为北京时间 `[23:00, 23:20)` 检测开播、`[11:00, 11:20)` 监测下播。两者均为半开区间，由 Task Scheduler 从窗口起点开始每分钟触发一次，重复时长 19 分钟，共覆盖 20 个分钟槽；窗口结束点本身不允许操作。
- 每日开播任务仍是有限权限协调器，只能调用统一 `Start-BilibiliLive.ps1`。完整真实游玩、连续 `applied`、驾驶舱和 Quipper 显存门禁不变；统一入口确认 `Streaming` 后记录当天窗口 ID，后续检查只有在标记匹配、仍为 `Streaming` 且受保护 HealthWatch 仍为 `Running` 时直接通过。若窗口内重新掉到 `Idle`/`NotRunning`，或 HealthWatch 缺失/未运行，下一分钟必须重新执行完整开播门禁，不能凭旧标记复播。
- 每日下播任务恢复为有限权限协调器，而不是旧版直接操作 GUI 的高权限 worker。它只在精确 `Streaming` 时调用统一 `Stop-BilibiliLive.ps1`；`Idle`/`NotRunning` 视为已完成，`Starting`/`Stopping`/`Unknown`、读取失败或窗口过期均不触碰 GUI，等待下一分钟。统一下播只停止直播姬，并恢复 IndexTTS 与窗口层级，不停止游戏、Brain、runner、驾驶舱或 Quipper。
- 安装器现需部署并核验五份文件，注册三个高权限固定任务和两个有限权限窗口协调器，并验证两项完整日期 `StartBoundary`、`PT1M` 间隔、`PT19M` 重复时长与 `NextRunTime`。完整 Bilibili 脚本测试为 56/56 通过，只读触发器验收也确认 23:00/11:00 北京时间分别映射到正确 UTC。遵照用户此前“人不在、先不 UAC”的限制，本轮仍只完成仓库源码与测试，未写入 `Program Files`、未改计划任务、未触碰当前直播状态；生产计划在用户在场明确批准一次 UAC 前仍保持旧配置。
