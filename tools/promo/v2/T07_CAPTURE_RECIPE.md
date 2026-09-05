# T07 清洁重录动作交接单

本文件是 T07「战斗奖励、地图选路与白绮标记移动」的录制前操作单。它只规定
准备、正式输入和证据交付；不替代实际 raw、probe、state/receipt sidecar 或
production row。每次尝试使用新的 `attempt_id`，失败素材保留，不覆盖旧 attempt。

## 目标与硬边界

- 一条独立、连续的 MKV 完成：真实奖励选卡 → 打开地图 → 选择当前可达节点 →
  看见白绮蝴蝶标记/节点反馈。
- 录制标记后只允许游戏自身 UI 的鼠标悬停和点击；不能使用控制台、Brain/API、
  任务栏、系统鼠标、OBS/AI/debug/MODDED 覆盖层，也不能暂停、停录、换窗口或
  中途重布置。
- 受控布置只在标记前完成并记录为 `staged_setup`（T07 当前
  `staged_setup_allowed=false`，因此优先采用自然导航）；正式画面不得把布置动作
  当作玩法。
- 视频保持 1920×1080、60 FPS、H.264/yuv420p，AAC 48 kHz 双声道；原始 MKV
  字节不改，后续归一化另存。

## 标记前检查（不进入正式显示段）

1. 自然完成一场战斗并停在真实奖励页。确认至少一张当前运行时白绮牌，读取其
   **真实** `VIVHITE_CARD_*` ID（不能从旧 take 猜测）。
2. 预览地图路线，确认一个此刻 `reachable=true` 的节点及运行时 canonical
   `node_id`；记录节点的行/列/类型和当前白绮蝴蝶标记位置。不要预先点击节点。
3. 关闭控制台、调试面板、系统光标捕获和所有 overlay；确认完整 1920×1080
   游戏 HUD 清洁可见。若只能通过控制台改变卡组/敌人/血量，T07 不应把该布置
   写入正式段，且本 take 应改用自然奖励页。
4. 启动新的 OBS MKV 后，以第一个干净游戏帧建立 recording mark；先保持完整
   HUD 2 秒。建议 raw 至少 25–28 秒，以容纳 20 秒 owner 加 3–4 秒结果尾。

## 最短连续动作链（相对 recording mark）

以下是排练用时间窗，不是可事后臆造的时间戳；正式 sidecar 必须记录现场的帧和
单调时钟。若某一步 UI 较慢，延长该步并新建 attempt/调整 source span，不能
压速或跳剪。

| 相对时间 | 输入/画面 | 必须留下的可见结果 |
| --- | --- | --- |
| 0.00–2.00 s | 奖励页全景，静置 | 完整奖励牌面、当前 HP/金币/HUD，无禁项 |
| 2.00–3.50/4.00 s | 悬停实际白绮奖励牌 1.5–2 s | tooltip、牌名和 `VIVHITE_CARD_*` 目标可读 |
| 约 3.50/4.00 s | 游戏 UI 左键真实 down/up | 奖励牌高亮/选中，等待奖励结算 |
| 5.00–6.50 s | 奖励结果稳定后点击 map_button，打开全图 | 全图、路线和白绮蝴蝶标记清楚可见 |
| 8.00–10.00 s | 地图稳定展示路线 | 目标节点确实可达，节点 hover 区域可读 |
| 10.00–11.50 s | 悬停目标节点约 1.5 s，真实左键 down/up | 节点 tooltip/高亮和点击反馈 |
| 11.50–16.00 s | 等待游戏完成节点选择/标记移动 | `settled=true`，标记移动或节点进入反馈可见 |
| 16.00–20.00 s | 保持最终干净地图/节点结果 3–4 s | 结果 HUD/标记稳定；不得出现黑屏、loading 或调试层 |

导演 storyboard 的 owner 是 `S04-04-card-reward`（8 s）和
`S04-05-map-route`（12 s）。若按 20 s owner 使用，两个 source span 必须首尾
相接、各自严格落在 owner 窗内（例如相对 mark 的 `[0,8)`、`[8,20)`）；实际
奖励结算或地图打开超过该窗时，保留更长 raw 并按真实帧重新绑定，不能把动作
剪进错误 subshot。`S01-05-map-highlight` 与 `S10-09-finale-map` 只可引用同一
take 中已证明的地图结果帧。

### 黑屏/切场处理

节点点击若立即进入战斗并产生黑屏或 loading，黑帧永远不能进入 production
display span、EDL 或视觉证据。只有在黑屏前已经有完整 pointer receipt、settled
状态和白绮标记移动，且仍能留下 3–4 秒清洁结果时才可结束显示段；否则该 attempt
判退并重录一个能在地图上留下稳定反馈的可达节点。不得用黑屏代替“标记移动完成”。

## 两个独立 action-evidence-v2 sidecar

T07 没有 `formal_action_chain`，所以在 take manifest 中声明两个 `ui_action`
条目，而不是伪造机制动作：

```text
T07-<attempt>-choose-reward-card   action_kind=choose_reward_card
T07-<attempt>-choose-map-node      action_kind=choose_map_node
```

每个 sidecar 必须独立拥有以下三份不可变 JSON（独立路径、bytes、SHA-256）：

```text
state.before → action.receipt → state.after
```

建议 evidence ref：

```text
T07-frame-begin
T07-reward-state-before
T07-reward-receipt
T07-reward-state-after
T07-map-state-before
T07-map-receipt
T07-map-state-after
T07-frame-end
T07-recording-boundary
T07-live-receipt
```

`capture_identity` 必须绑定 `session_id`、`game_run_id`、`game_process_id`、
`source_video_artifact_id`、`run_id`、`take_id`、`subshot_id`、`action_id`。每个
receipt 使用 `input_origin=game_ui_pointer`、`status=completed`、`stable=true`、
`applied=true`、`delivery.status=sent`、`outcome.status=applied`、`settled=true`。
帧/时间顺序必须满足：

```text
display.begin ≤ before.frame < pointer_down < pointer_up ≤ settled < after.frame < display.end
recording_start_frame ≤ display.begin
```

契约使用 1-based frame；若用 ffmpeg zero-based source frame，写入 sidecar 前统一
加 1，并在 boundary/live receipt 保存映射、UTC/ticks、stopwatch frequency、OBS/game
PID 与启动身份。

### 奖励动作动态字段

- `action_kind=choose_reward_card`。
- `target.kind=reward_card`，`target.id` 必须是画面实际提供的 `VIVHITE_CARD_*`；
  `request.parameters.card_id` 必须逐字相同。
- `pointer_hitbox` 由本次 1920×1080 卡牌位置动态测量；不要复用 a05 坐标。
- `state.before` 应含奖励页、候选牌列表、待选状态和当前牌组；`state.after` 应
  含选中牌/奖励关闭或牌组变化。`visible_state_paths` 只填运行时确实存在且前后
  至少一项变化的路径，例如 `/screen`、`/reward/card_options`、
  `/reward/pending_card_choice`、`/run/deck`。

### 地图动作动态字段

- `action_kind=choose_map_node`。
- `target.kind=map_node`，`target.id` 使用本次地图 payload 的 canonical portable
  ID；`request.parameters.node_id` 必须逐字相同，不可猜测示例值。
- `pointer_hitbox` 由当前节点轮廓动态测量；`state.before` 必须证明节点
  `reachable=true` 和地图已打开；`state.after` 必须显示 marker/current-node
  变化、节点反馈或已结算的下一状态。
- `visible_state_paths` 仅使用真实返回字段，例如 `/screen`、`/map/current_node`、
  `/map/available_nodes`、`/map/marker_position`、`/run/floor`；若 UI 直接转场，
  至少保留转场前 marker/receipt 和转场后非黑状态快照。

## 交付和验收顺序

1. 原始 MKV 关闭后立即复制/哈希；用 `ffprobe -count_frames`、CFR probe、decode
   check、blackdetect 和 contact sheet 做只读检查，禁止修改 raw。
2. 写入两个 sidecar、三联 state/receipt、boundary/live receipt、frame begin/end
   和 attempt manifest；每个 artifact path/hash 在 take row 的 `evidence_refs`
   中逐项列出。不得从视频事后猜 pointer/monotonic 时间。
3. 先调用 `action_evidence_v2` loader，再调用 `_bind_take`；确认两个 action 的
   state payload 在声明的 `visible_state_paths` 上真实变化、source span 不越界、
   没有禁项。失败只新增 attempt 并写明原因。
4. 通过后才把 T07 row 标为 production candidate；任何视觉-only、缺 receipt、
   不可达节点、黑/loading、目标 ID 不匹配或跨度断裂都保持 rejected。

## 可复用工具

```powershell
py -3 -B -m tools.promo.vivhite_promo.capture_runbook_v2 show T07
$env:PYTHONPATH = (Resolve-Path .\tools\promo).Path
py -3 -B -m vivhite_promo.capture_runbook_v2 show T07
```

契约与 binder：

```text
tools/promo/vivhite_promo/action_evidence_v2.py
tools/promo/vivhite_promo/production_binder_v2.py
tools/promo/v2/production-binder.md
tools/promo/tests/test_action_evidence_v2.py
tools/promo/tests/test_production_binder_v2.py
```

仓库目前没有自动生成 T07 原生 pointer/stopwatch sidecar 的脚本；字段必须由录制
辅助器在真实点击发生时写入 live receipt。视频扫描、OCR 或 contact sheet 只能补充
视觉证据，不能替代 `game_ui_pointer` receipt。

## 中断恢复

恢复人先读取本文件、`capture-runbook.json`、`storyboard.json` 和当前 run 进度文档，
确认最近 attempt 的 raw/hash/status；不要覆盖旧文件。若动作中断、坐标不确定、
节点不可达、黑屏超过清洁结果窗或 sidecar 缺字段，保留失败包，换新的 attempt，
从标记前自然奖励页重新开始。只有 raw、双 action sidecar、三联状态、boundary/live
receipt、probe 和 binder validation 全部齐全时，才可把 T07 交给 EDL/渲染。
