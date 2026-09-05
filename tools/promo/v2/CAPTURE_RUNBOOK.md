# 白绮宣传片 v2 逐 take 录制手册

这是 `T01–T20` 的现场操作清单；`T15` 仅在 `T14` 的 UI 事件互相遮挡时启用。它不代表任何 take 已完成，也不能替代 raw、probe、`state.before`、`action.receipt`、`state.after` 和实际画面。

用户已在 2026-09-03 明确解除游戏、OBS、录制与渲染门禁。正式开拍仍须先通过当次 external-tools/overlay 预检，并使用可逆隔离移走会进入画面的训练 overlay；授权本身不等于预检通过。

## 开拍前 30 秒

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Resolve-Path .\tools\promo).Path
py -3 -B -m vivhite_promo.capture_runbook_v2 validate
py -3 -B -m vivhite_promo.capture_runbook_v2 show T06
```

`validate` 必须输出 20 个 take 槽、`T15 conditional` 和
`T06=VIVHITE_CARD_TANGENT_STARLIGHT`。若 T06 校验失败，先停拍该 take：当前 C# 注册、奖励稀有度或中文本地化已经与清单不同，不能继续沿用旧 ID。

每个 attempt 使用新文件：

```text
tools/promo/runs/<new-v2-run-id>/raw/takes/Txx/<attempt-id>.mkv
```

失败 take 只追加新 attempt，不覆盖、不删除旧文件。

## 每个 take 的固定循环

1. 只在录制标记前完成牌组、能力、敌人和 HP 的 `staged_setup`；需要控制台时也只在这里使用。
2. 关闭控制台和所有 setup/overlay 表面，回到 1920×1080 的完整游戏画面；确认无 OBS、任务栏、系统鼠标、Brain/AI、ASCEND-VISION、loading、debug/MODDED 或旧战士素材。
3. 开始独立 MKV，并以第一个干净游戏帧作为录制标记；先保留 2 秒完整 HUD。
4. 机制牌先悬停 1.5–2 秒，再用游戏 UI 真实点击；从点击到最终结算始终 1×、同一 source、不中断。
5. 等 UI 动画全部落定，再保留 3–4 秒结果 HUD。立刻保存证据并回看；失败则启用新 attempt。

正式动作中禁止重新开控制台、注入 direct API、换 raw 文件或用 `kill` 替代卡牌击杀。受控布置必须标记 `staged_setup`，并从所有 EDL 展示段排除。

## 批次顺序

| 批次 | take | 现场目标 |
| --- | --- | --- |
| B01 身份与早期局 | T01、T02、T07 | 白绮选人、初始配置、真实奖励与地图移动 |
| B02 守恒与增维 | T03–T06、T08、T09 | 謦欬、余裕、第二守恒链、增维和真实致命 |
| B03 塔内生活与牌库 | T10、T13、T19 | Act 2/3 篝火、普通商店、61 张牌 |
| B04 汲取与递归 | T11、T12、T14；必要时 T15 | 多段汲取、回血转格挡、死亡连锁 |
| B05 高潮与收束 | T16、T17、T18、T20 | 猩红连续链、绯彩补镜、统一场论、idle |

## 逐 take 一页总表

| take | 标记前准备 | 正式段 | 通过条件 |
| --- | --- | --- | --- |
| T01 | 主菜单、独立白绮实现可用 | 标准模式→移动高亮→立绘 6–8 秒→确认 | 清楚显示白绮、78/78、99、孤高冠冕和描述；出现“铁甲战士”即作废 |
| T02 | 新白绮局初始状态 | 完整 HUD→打开牌组→依次悬停三种起始牌 | 78 HP、99 金币、冠冕和三种当前 tooltip 可读 |
| T03 | 弦光投影、余裕 0、HP 大于 runtime 謦欬、敌人存活 | 点击弦光投影 | 生命支付先于攻击伤害 |
| T04 | 变身式、余裕/力量/敏捷均 0 | 点击变身式 | 支付成功后才出现力量和敏捷 |
| T05 | 未升级公理护环+闭域投影、无数值修正 | 连续点击两张牌 | 当前基线余裕 0→3→0、余下支付 1、伤害、15 格挡；runtime 优先 |
| T06 | 源码校验通过；切线星光、余裕 0、敌人存活 | 点击切线星光 | 当前基线支付 2→伤害 11→余裕 1；runtime 优先，且不重复 T05 |
| T07 | 真实战斗奖励页和可达地图节点 | 选白绮奖励→开地图→选节点 | 奖励、路线和白绮蝴蝶移动均有真实回执 |
| T08 | 拓扑增生、余裕至少 8 | 点击拓扑增生 | 当前生命和最大生命同步正增长 |
| T09 | 尺度变换、一个可击杀目标、另一个存活目标 | 点击尺度变换 | 真实攻击击杀后触发致命增维；禁止控制台 kill |
| T10 | Act 2/3 可达篝火，玩家缺血 | 进篝火→看动画→休息→回地图 | 休息产生实际 HP 正增量并有完整界面反馈 |
| T11 | 三色轮舞、玩家缺血、目标能撑过三击 | 点击三色轮舞 | 三击先完成，随后一次聚合汲取且 actual_healing>0 |
| T12 | 色彩守恒已生效、复合色轮、玩家缺血、全敌存活 | 点击复合色轮 | actual_healing>0，随后格挡正增长 |
| T13 | 普通商店、可支付白绮商品、完整货架 | 悬停→购买→关库存→离店 | 金币真实下降、商品成功购买、离店完成 |
| T14 | 冠冕+星算追猎+正汲取、2 个低血敌人、足够缺血/抽牌空间 | 点击终止证明 | 汲取先结算；冠冕实际回血、抽牌和能量均为正增量 |
| T15 | 仅 T14 UI 遮挡时重建更简洁的独立战斗 | 重新真实点击终止证明 | 同一完整动作链更清楚；不能拿 T14 后半段冒充 |
| T16 | 仪式在手，弦光投影下回合可抽到，敌我均能存活 | 仪式→结束回合→phase 1 弦光投影 | 三步在同一 MKV，之间无 setup、停录或切镜 |
| T17 | 当前绯彩积分牌组/战斗 | 游戏内浏览并悬停核心牌 | 能表达第三条构筑路线，不做完全平衡/无限成长承诺 |
| T18 | 统一场论已生效、余裕/缺血/牌序满足闭环、敌人存活 | 闭域映射→三色轮舞 | 余裕抵扣→汲取增长→实际回血≥divisor→余裕回流，全链同一 MKV |
| T19 | 当前白绮牌库，runtime manifest=61 | 游戏内滚动并悬停三路线代表牌 | 61 张与当前实现一致，无旧占位牌 |
| T20 | 干净白绮选人动画或战斗 idle | 连续保留足够长的干净动画 | 身份明确、负空间足够，供标题/Finale 取不同新窗口 |

## 四个高风险 take

### T06：已绑定的第二守恒牌

绑定不是凭旧文档猜测。`capture_runbook_v2` 会读取：

- `Vivhite/VivhiteCode/Cards/Conservation/ConservationCommonCards.cs`
- `Vivhite/Vivhite/localization/zhs/cards.json`

只有源码仍同时证明 `[RegisterCard(typeof(VivhiteCardPool))]`、继承
`ConservationCard`、`CardRarity.Common` 和中文标题“切线星光”时才放行。

### T14/T15：冠冕必须产生实际回血

不要只确认图标存在。标记前按当次 runtime 值估算：

```text
缺血量 + 终止证明实际生命支付 - 预计汲取实际回血 > 0
```

推荐让左侧结果至少达到 `ceil(MaxHP × 20%)`，这样第一段孤高冠冕回复能完整可见。优先只用 2 个敌人，手牌尽量只留终止证明，抽牌堆至少 8 张；回执必须分别证明汲取实际回血、冠冕实际回血、手牌正增量和能量正增量。

### T16：两个卡牌动作必须连续

正式 source 顺序固定为：

```text
真实点击猩红转化仪式 → 真实点击结束回合 → 等 phase 1 → 真实点击弦光投影
```

三步只允许一个 MKV；结束回合后不得用控制台把攻击牌塞回手牌，所以必须在标记前把牌序准备好。

### T18：统一场论闭环

统一场论必须在录制标记前已经生效。建议使用未升级版本，当前源码基线可用：

```text
初始余裕 2
→ 闭域映射的 2 点謦欬全部由余裕抵扣
→ 统一场论增加 8% 全局汲取
→ 三色轮舞自身 12% + 全局 8% = 20%
→ 三击合计实际掉血 12 时，向上取整实际回血 3
→ floor(3 / HealingDivisor 3) = 1 余裕回流
```

这是排练基线，不是片中硬编码值。开拍时必须从当前 tooltip 重新绑定 `HealingDivisor`，并用 HUD/回执证明最终余裕严格大于闭域映射结算后的余裕。

## 回看与交接

每完成一个 attempt，立即在当次 run 的 `capture/take-index.json` 和进度文档中记录：take/attempt、raw 相对路径、录制标记、干净 span、是否通过、失败原因、对应 evidence 路径。没有真实文件和回执时只能写 `not_started` / `failed`，不得填 bytes、SHA 或 `observed`。

机器清单与全部逐项文字位于 [capture-runbook.json](capture-runbook.json)。单 take 现场提示可用：

```powershell
py -3 -B -m vivhite_promo.capture_runbook_v2 show T14
```
