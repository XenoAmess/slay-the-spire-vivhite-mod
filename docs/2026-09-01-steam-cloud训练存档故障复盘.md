# Steam Cloud 训练存档故障复盘与隔离方案

## 结论

本次训练中，`TTT6HQGV7NAS` 并非 Brain 正常结束的终局，而是退出时本地 `current_run.save` 未能写入 Steam RemoteStorage，随后下一次冷启动的原生云同步按“远端不存在”删除了本地存档。现有证据无法恢复该局，因此它已通过一次性孤儿局入口标记为 `orphaned`、`excluded_from_learning`，没有计入胜负、统计或轮换配额。不能把零字节暂存文件或 `MAIN_MENU/run_unknown` 当作恢复证据。

## 证据链（2026-09-01，Asia/Shanghai）

1. 停栈前 runner 日志仍有 `TTT6HQGV7NAS` 在 F7/F8 的真实动作；停止哨兵时间为 17:56:56。Steam 远端的 `current_run.save.stmp` 在 17:56:44 变成 0 字节，不能证明有有效 payload。
2. 游戏日志在 18:15 左右记录 `Syncing cloud save files to the local save directory`，紧接着记录 `Deleting modded/profile1/saves/current_run.save because it does not exist on remote`。这解释了为什么 API 随后回到 `MAIN_MENU/run_unknown`。
3. 同一会话多次记录 `Wrote ... current_run.save` 后的 `Cloud write failed ... k_EResultIOFailure`。Steam `cloud_log.txt` 还记录 `login=false`/`offlineMode=true`、`Upload failed due to conflicts in build list` 与 `YldWriteCacheDirectoryToFile failed`；采样到的 D: 可用空间在约 0–1.8 MB 间（其中游戏日志曾报告 0.0 B）。这是直接的写入风险证据，但不能把单一容量读数当作全部根因。
4. 复核时远端没有 `current_run.save` 或 `.backup`；`remotecache.vdf` 只保留 `size/localtime/remotetime=0/syncstate=3/persiststate=2` 等本地未上传元数据，没有存档 payload。该条目的 `localtime` 约为 17:00:03，早于最后一次本地写入约 60,967 B（17:56:43.5），所以不是最后版本的备份。C: 本地 save、backup、stmp 及 history 中也没有该 run。早期读取到的 0 字节 `remotecache.vdf` 是并发重写期间的瞬时快照，不能作为最终文件状态。
5. 两次有序 API 采样均为 `MAIN_MENU`、`run=null`、无 `continue_run`，四类原生探针无读错且没有匹配 run；故按窄例外流程释放孤儿账本，而不是伪造终局或强行开新局。

## 修复与边界

- 统一启动入口新增显式 `-SteamMode auto|on|off`。只有冷启动且用户明确指定 `-SteamMode off` 时，才向 `launch_vulkan.bat` 传 `--force-steam off`，让本次显式诊断/隔离会话使用本地存档而跳过 Steam 初始化；`session.json` 记录请求模式、实际参数和是否应用。该选项不改 Steam 客户端、云文件或游戏目录，不需要 UAC，也不宣称修复 Steam Cloud 本身。
- 生产无人训练默认使用 `-SteamMode auto`（或显式 `on`），保留已验证 Steam profile 的原生初始化与模组同意；已有游戏进程不会被参数追溯修改。需要切换模式时必须先用统一 `Stop-Agent.ps1`，再冷启动。
- `-SteamMode off` 仅限已完成独立 `user://default/1` profile 原生模组同意、且明确接受独立存档命名空间的显式诊断/隔离实验；它不是生产训练 fallback，也不是 Steam Cloud 修复。无论模式如何，都必须执行原生 Continue、API 状态、动作回执和连续进展门禁。云同步失败、存档证据缺失时保持 Brain/直播 fail-closed；绝不复制、改名或手改 `.stmp`/`knowledge`。
- 直播姬本次及后续训练均保持 `Idle`；没有调用开播入口，也没有请求人工 UAC。Steam Cloud 恢复仍需用户在 Steam 客户端/磁盘空间恢复后另行处理，本流程不代替该人工步骤。

## 回归

- `sts2-ascend/tests/test_start_agent_steam_mode.py` 覆盖参数映射、冷启动分支和文档审计；另有已有孤儿恢复/空播门禁回归。
- 真实运行验证必须按模式记录：生产基线为 `SteamMode=auto`（或显式 `on`）并确认 Steam profile/模组已加载；仅诊断 off 验证才要求启动日志出现 `SteamMode=off`、游戏日志显示跳过 Steam 初始化且使用独立本地 profile。两者随后都必须满足 `/state` 非菜单真实 run、驾驶舱 `connected`、`applied` 回执和楼层进展。

## 二次复现与处置（session `6b3a1ff9d80845ed97742a0f2d50324f`）

2026-09-01 19:37:57 以 Steam-on 冷启动后，Brain 握手在 0.699 秒内完成；API 与驾驶舱均连接，白绮 run `4MALNYXSZ5CV` 从 F3 推进到 F17，最后连续决策 `-282`（出牌）、`-283`（出牌）、`-285`（结束回合）均收到服务端 `completed` 回执。故障不是挂机或 API 假就绪。

19:45 起 D: 可用空间耗尽，游戏仍能写本地文件但 Steam RemoteStorage 暂存写入失败。当前日志中的关键成对记录为：

- `godot.log:1814-1815`：写入 71,753 bytes 后 `Cloud write failed ... k_EResultIOFailure`；
- `godot.log:1854-1855`：写入 72,656 bytes 后同一错误；
- `godot.log:1903-1904`：写入 75,565 bytes 后同一错误；
- `godot.log:1922-1923`：写入 76,381 bytes 后同一错误；`progress.save` 同时失败。

停止前后的只读快照（均未手工改动）如下：

| 位置 | 大小 | SHA-256 | 结论 |
|---|---:|---|---|
| 本地 `current_run.save` | 76,381 | `5A93B23CA7B96CF003BD6CDF25212532EE6A178B204C20E0A6F7C3AE43358F2A` | 保留最新本地局面 |
| 本地 `.backup` | 75,565 | `D277AC07B85A54ADBB79D8A146FEAF33A6D4F633C50423E5ACC494E454CEE7D6` | 可作本地回退证据 |
| Steam remote `current_run.save` | 70,759 | `EA2AA271F70DB260611E15D408F5408A0C8ABEFB5FFE78D740A6C42E04EBD6D1` | 落后且不一致 |
| Steam remote `.stmp` | 0 | `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` | 无有效上传载荷 |

`Stop-Agent.ps1` 于 19:46:07 发布 session sentinel，Brain 以 `rc=0` 退出，游戏随后有序关闭；没有开播、键鼠操作或 UAC。由于 D: 仍为 0 bytes，当前训练标记为“动作稳定、存档不稳定”，不得再次冷启动或开播，直到用户释放磁盘并验证本地/远端存档重新一致。该次运行的完整审计日志仍保留在 `knowledge/profiles/vivhite/runs/20260901-193925_4MALNYXSZ5CV.json`；该运行不应被当作已安全终局。
