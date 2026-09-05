# T16 / T18 录制动作交接单

本文件是 `run-20260903T0012-director-v2-a1` 的录制前操作单。它只描述录制前
的受控布置和录制标记后的真实游戏输入；控制台布置必须在 recording mark 之前
完成并关闭。正式片段不能出现控制台、系统鼠标、暂停界面、OBS 或任何 debug/AI
覆盖层。

## 通用输入约定

- 使用 `tools/test/GameTest.psm1`：

  ```powershell
  Import-Module .\tools\test\GameTest.psm1
  ```

- 游戏坐标为 1920x1080 内容坐标；新会话先用截图确认窗口矩形和卡牌槽位。手牌
  纵坐标通常约 `950–980`，但不能把旧 take 的横坐标当成固定值。
- 每张正式牌在点击前悬停 1.5–2 秒；点击到游戏结算完毕保持 1x、不中断；结算
  后至少保留 3 秒（建议 3–4 秒）。
- 参考坐标（仅作命中区域起点，录制前必须动态复核）：结束回合按钮中心
  `(1720,900)`，敌方目标常在 `(1200,620)`；攻击牌应记录从牌面到目标的完整
  拖拽，而不是只记录一个抽象 click。
- 开关控制台：``Send-Key -VkCode 0xC0``。带空格的命令使用剪贴板粘贴；每次
  布置完成后关闭控制台并截一张 clean HUD，再建立 recording mark。

## 控制台粘贴助手

```powershell
function Send-ConsoleLine([string]$line) {
    Set-Clipboard $line
    [GameInputNative]::keybd_event([byte]0x11,0,[uint32]0,0) # Ctrl down
    Send-Key -VkCode 0x56                                     # V
    [GameInputNative]::keybd_event([byte]0x11,0,[uint32]2,0) # Ctrl up
    Send-Key -VkCode 0x0D                                     # Enter
    Start-Sleep -Milliseconds 300
}
```

`fight`、`heal`、`damage <amount> <index>`、`energy`、`power <ID> <amount> 0` 和
`card <ID>` 已在当前游戏日志中验证。`damage`、`power`、`card` 都只能写入
`staged_setup`；正式片段不得使用 `kill` 或其他控制台命令。

## T16：猩红转化仪式 phase 0 → phase 1 → 攻击

### 录制前布置

在普通战斗中执行并记录为 `staged_setup`（以下敌人索引只作示例，先看 HUD 确认）：

```text
fight NIBBITS_NORMAL
heal 100
energy 3
card VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL
card VIVHITE_CARD_LUMINOUS_PROJECTION
card VIVHITE_CARD_LUMINOUS_PROJECTION
```

选择一个能活过两回合、能承受 phase 1 `LUMINOUS_PROJECTION` 的敌人。必要时只在
控制台阶段用 `damage <n> <enemy-index>` 调整敌人血量，不能杀死目标。不要预先
施加猩红仪式 power；仪式卡必须在正式镜头中真实打出并显示 phase 0。若结束回合
后手牌没有 Luminous Projection，停止本次尝试、重新布置并建立新的 attempt，不能
在正式链中补牌。

### 正式连续链

1. 建立 recording mark，先留完整 HUD 的 2 秒 clean preroll（phase 0 尚未存在）。
2. 在当前手牌中动态定位猩红仪式，悬停 1.5–2 秒，真实点击；保留支付/结算，
   直至 `T16-state-phase0`。
3. 点击结束回合按钮（参考中心 `(1720,900)`），不中断录制；等待下一回合、
   phase 1 power 和新手牌稳定。
4. 在新手牌中动态定位 Luminous Projection，悬停 1.5–2 秒，真实拖拽/点击到
   仍存活的敌人（参考目标 `(1200,620)`，以当帧目标框为准），完整保留额外謦欬、
   每击伤害和最终 HUD，再留 3–4 秒结果尾。

不得在第 2–4 步之间暂停、重启录制、切换窗口、重新布置或插入 setup。建议源文件
预留约 2 秒 preroll、约 30.5 秒 owner span（最终以实际动作和 EDL 为准）。

### T16 证据交付

必须在同一 source MKV、同一 game run/process 上写入以下引用：

```text
T16-frame-begin
T16-state-before
T16-ritual-receipt
T16-state-phase0
T16-end-turn-receipt
T16-state-phase1
T16-state-before-attack
T16-phase1-attack-receipt
T16-state-final
T16-event-sequence
T16-frame-end
```

证据 owner 是 `S08-02-crimson-phase-zero`（begin、before、仪式 receipt、phase0、
end-turn receipt、phase1、sequence）和 `S08-03-crimson-phase-one`（before-attack、
phase1 attack receipt、final、sequence、end）。

每个 action sidecar 使用 `vivhite-promo-action-evidence` v2：
`input_origin=game_ui_pointer`、`status=completed`、`stable=true`、`applied=true`、
`delivery.status=sent`、`outcome.status=applied`、`settled=true`；填入 source/session/
run/process/take/subshot/action 身份、`recording_start_frame`、`display_span`、鼠标
按下/抬起帧和 monotonic 时间、真实 pointer hitbox，以及 target card/button ID。
`T16-state-phase1` 与 `T16-state-before-attack` 必须是完全相同的快照（包括 frame、
monotonic_seconds、state_version、observation_seq 和 payload）；最稳妥做法是让两
个 evidence ref 指向同一份 immutable JSON，再分别作为前一步 after、后一步 before
绑定。

生成 sidecar 时严格满足帧/时间顺序：
`display.begin <= before.frame < pointer_down < pointer_up <= settled < after.frame
< display.end`；`recording_start_frame <= display.begin`，而 `staged_setup.setup_end_frame`
必须同时早于 recording start 和 display begin。三份正式 artifact（state.before、
action.receipt、state.after）使用不同路径和不同 SHA；它们共享同一个 protocol
`state_version`，但 `observation_seq` 必须满足 `before < receipt <= after`。

action receipt 的 target/request 要严格使用 schema 的枚举值：

```json
{"target":{"kind":"card","id":"VIVHITE_CARD_LUMINOUS_PROJECTION"},
 "request":{"request_id":"<action_id>","action_kind":"play_card",
             "parameters":{"card_id":"VIVHITE_CARD_LUMINOUS_PROJECTION"}}}
```

结束回合不是普通 button：

```json
{"target":{"kind":"end_turn_button","id":"end_turn"},
 "request":{"request_id":"<action_id>","action_kind":"end_turn",
             "parameters":{"control":"end_turn"}}}
```

事件序列至少覆盖：
`ritual_click → phase0_power_active → end_turn_click → phase1_handoff →
Luminous_click/target → extra Cough/payment → increased_damage → final_state`。
状态路径使用实时 `/state` 实际返回的路径（至少 current HP、energy、margin、手牌、
仪式 phase/power、目标 HP），不要把导演目标数值硬编码成运行时事实。

## T18：统一场论完整资源闭环

### 录制前布置

先在普通战斗中完成下列受控布置，并截取包含 power、余裕、缺血和两张牌的 clean HUD：

```text
fight NIBBITS_NORMAL
heal 100
damage 40 0                         # 仅在确认 index 0 是玩家后执行
energy 3
power VIVHITE_POWER_UNIFIED_FIELD_THEORY_POWER 1 0
power VIVHITE_POWER_INFINITE_MARGIN_POWER 2 0
card VIVHITE_CARD_CLOSED_DOMAIN_MAPPING
card VIVHITE_CARD_TRICHROMATIC_WALTZ
```

若当前 `damage` 后玩家不满足缺血条件，重新用小额 `damage` 调整，保证缺失 HP 至少
等于 tooltip 的 `HealingDivisor`；若目标有格挡或血量不足以承受三击，换目标/战斗
并重新建立 attempt。统一场论 power 必须在 recording mark 前已经生效，正式镜头
不要打出统一场论本身。以当次 tooltip 绑定 divisor（未升级通常 3，升级通常 2），
所有数值以 HUD/tooltip/receipt 为准。

### 正式连续链

1. recording mark 后留 2 秒完整 HUD，确认 UFT、Margin>0、缺血、energy≥2、两张
   牌和存活目标均可读。
2. 动态定位 Closed Domain Mapping，悬停 1.5–2 秒后真实点击；完整保留謦欬被
   Margin 抵扣、Margin 降低和 Drain 增长，直到 `T18-state-after-cough`。
3. 不插入 setup，悬停并真实点击 Trichromatic Waltz（旧 take 常见牌面中心
   `(1430,955)`，仅作参考）；在目标选择阶段点击实际目标（常见 `(1200,620)`），
   保留三次原生命中、一次聚合实际回血和 Margin 回流，结果尾 3–4 秒。

预期未升级基线仅用于排练：Margin `2→0`，每点抵扣增加 4 个百分点 Drain，三击
实际伤害约 12，实际回血应至少达到 runtime divisor，最终 Margin 必须高于
`state-after-cough`。不符合时判该 attempt 失败并保留原片，不用旁白或后期伪造。

### T18 证据交付

```text
T18-frame-begin
T18-state-before
T18-cough-card-receipt
T18-state-after-cough
T18-drain-attack-receipt
T18-state-after
T18-event-sequence
T18-frame-end
```

证据 owner 是 `S09-02-unified-field-chain`（begin、before、Cough receipt、after-cough、
Drain receipt、sequence、after）和 `S09-03-unified-field-result`（sequence、after、end）。

`state.before` 必须绑定 UFT active、runtime divisor、缺血、Margin、energy、两张牌、
目标 HP/no-block。观察字段至少记录：`actual_healing`、`healing_divisor`、
`margin_before`、`margin_after_cough`、`margin_final`、`drain_percent_before/after`、
`target_damage_total`、三击完成和单次聚合回血。事件顺序必须可回放为：
`Margin offsets Cough → Drain increases → real drain damage → actual healing resolves
→ Margin returns`。

## 中断恢复清单

1. 先读取本文件、`capture-runbook.json`、`storyboard.json` 和进度 doc 的最新时间戳。
2. 只在 `tools/promo/runs/<new-run>/capture/takes/T16/<new-attempt>` 或 T18 对应
   新 attempt 写入；不要覆盖旧 raw/receipt。
3. 确认游戏/OBS 当前窗口和 process identity，再做 setup；没有 clean HUD、目标存活
   或动态卡槽确认就不建立 recording mark。
4. 录制结束立即保存 raw、live receipt、before/receipt/after/event-sequence、frame
   begin/end、staged-setup 和 SHA-256，并把下一步写回进度 doc。
