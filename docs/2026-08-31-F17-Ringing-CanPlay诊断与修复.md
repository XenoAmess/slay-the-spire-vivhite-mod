# F17 Ringing / CanPlay 误判诊断与修复

## 现场与结论

- 对局：`6D0T5BPUDMG6`，F17，2026-08-31 16:32:50 至 16:33:17。
- Brain 打出 `VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL` 后，连续 39 次报告“账面仍有可负担目标牌”，第 40 拍以 1 能量结束回合。
- 当时手牌包括 0 费星图检索和多张 1 费牌；原始状态却把全部手牌标为 `playable=false`，`available_actions` 只有 `end_turn` 与 `save_and_quit`。
- Godot 日志显示出牌 POST 已在约 470 ms 内成功返回，随后 `/state` 一直正常响应，最终 `end_turn` 也在约 348 ms 内成功。故障不是 HTTP、动作请求或游戏动作队列卡死。
- 礼仪野兽此前使用 `BEAST_CRY_MOVE`，游戏随后加载 `ringing_power.png`。原生 `RingingPower.ShouldPlay` 限制本回合只能打出一张牌；第一张牌开始结算后，其余卡牌的 `CardModel.CanPlay` 返回 `BlockedByHook`，阻止者为 `RingingPower`。
- 根因是 Brain 的结算等待闸门只按费用和目标重算“账面可出”，没有读取 API 已提供的 `unplayable_reason=blocked_by_hook`，把永久到回合结束的规则锁误当成短暂接口锁。

## 最小行为修复

- `Policy._native_card_unplayable_reason` 识别原生 `CanPlay` 的明确拒因。
- 结算等待候选排除具有明确原生拒因的牌；Ringing、资源不足、关键词、牌自身逻辑和自定义 hook 均不会再等待 40 拍。
- 缺失拒因的旧 payload 或未知接口状态仍保留原有有界等待，避免把真正的动画、动作队列或模态窗口提前收口。
- 等待文案加入 `unknown_can_play` 及 `combat.action_readiness.reason`；终局逐牌审计加入规范化原生拒因。
- 白绮謦欬生命不足仍由既有专用检测优先处理，保持两拍确认语义。

## API 诊断契约

STS2-Agent 状态协议升级为 `state_version=14`、`agent_view.version=9`。

每张手牌新增或透传：

- `can_play_result`
- `unplayable_reason`：规范化原因，如 `blocked_by_hook`
- `unplayable_reason_raw`：原生枚举文本，如 `BlockedByHook`
- `unplayable_preventer_id`
- `unplayable_preventer_type`

`combat.action_readiness` 新增只读诊断：

- 总结：`can_use_combat_actions`、`reason`
- 动作队列：`actions_settled`、`running_action_type`、`ready_action_type`
- 模态窗口：`modal_open`、`modal_type`
- 战斗/UI：`player_actions_disabled`、战斗进行/结束状态、房间模式、手牌播放/选择/模式
- 回合与稳定性：`local_turn_ready`、`snapshot_stable`、`player_action_phase`

主要 `reason` 包括 `modal_open`、`game_action_running`、`game_action_queued`、`snapshot_stabilizing`、`hand_in_card_play`、`hand_in_card_selection`、`player_actions_disabled` 与 `ready`。

Brain 的 `end_turn` 持久决策证据保存上述动作就绪状态和逐牌拒因；watchdog 状态签名也纳入这些字段。下次即使出现不同类型的接口关闭，也可直接区分动作队列、模态窗口、稳定延迟、生命费用锁与未知拒因。

## 验证

- Python 定向回归 5 项通过，包括 F17 Ringing 原形、未知拒因动作队列状态、謦欬锁和终局诊断落盘。
- `test_character_strategy` 与 `test_review_decision_chain` 共 66 项通过。
- Brain 完整 `selfcheck.py` 通过；既有结算等待预算与回滚夹具保持兼容。
- STS2-Agent 轻量测试全通过，新增 `CombatDiagnostics.CanPlay` 与 `CombatDiagnostics.Readiness`。
- STS2-Agent 主项目纯编译通过：0 警告、0 错误。
- 本任务未执行生命周期入口、未部署、未启动或停止游戏、未提交、未推送。

## 共享工作树兼容性

- `policy.py` 中 Singer 的 residual-block 净生命收益修复保留不变。本任务只在同一 `_combat` 方法的“无 `play_card` 时结算等待”分支增加原生拒因过滤，并新增独立 helper；没有改动 Singer 的 residual-block 计算或竞速/续航账。
- `agent.py` 同时存在中文编码修复代理的稳定遗物 ID 改动。本任务只修改 `_decision_log_entry` 与 `_signature`；没有修改其 `relic_stats_key`、遗物标签解析或动作事务逻辑。
- `knowledge.py` 仅包含中文编码修复代理的改动，本任务未修改该文件。
