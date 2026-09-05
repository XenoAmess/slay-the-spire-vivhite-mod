# 白绮 Boss 竞速同回合掉血观测复盘

日期：2026-09-01

## HYPOTHESIS

第 4 局 `9D3T8FHYXKJM` 的 F17 竞速判死理由遗漏了已经由 `_race_same_round_loss` 记录的同回合掉血，因此后续复盘无法区分卡牌自损/费用与敌方意图伤害。

该假设可证伪：若竞速判死时没有同回合掉血，或现有理由已经完整披露该账，则新观测标记应为零信号。

## EVIDENCE

- 完整失败证据索引 `sts2-ascend/.review_evidence/failed_review/index.json` 已核对 473/473 个文件的字节数与 SHA-256；目标包和 3 个重试包的 manifest、report、inventory、候选 patch 均已读取。候选 patch 仅作证据，未自动套用。
- Run 4 `9D3T8FHYXKJM` 的完整 211 条 decision 已逐条检查。F17 决策 192–209 中 HP 从 66 降至 9，多个理由含 `hp-cost`、`VIVHITE_LIVE_ESTIMATE` 和竞速判断；决策 210 以 HP 0 进入 `GAME_OVER`。
- 原生 v0.111.0 knowledge 将 `SOUL_FYSH` 定义为 Boss；其 mechanics 记录 `BECKON`、`DE_GAS`、`GAZE`、`FADE`、`SCREAM` 及 16/7/13 伤害口径。生产 `policy.py` 已逐 tick 累加 `_race_same_round_loss`，但原先只在回血和零伤害意图同时成立的 `BOSS_SUSTAIN_NET_HP` 路径展示相关账。

## PRODUCTION_CHANGE

- `sts2-ascend/brain/knowledge.py` 增加默认开启的 `race_same_round_hp_loss_obs` 开关。
- `sts2-ascend/brain/policy.py` 仅在白绮、Boss、`race_lost` 且同回合观测损失大于 0 时，在既有竞速理由后追加 `RACE_SAME_ROUND_HP_LOSS_OBS` 与损失量。
- `sts2-ascend/tests/test_boss_race_sustain.py` 锁定无回血竞速路径的标记；该分支只改理由文本，不改 action、评分、TTK、可存活回合或能量分配。

## EXPECTED_SIGNAL

未来 3–10 局只统计相关白绮 Boss 竞速判死样本：标记出现次数、损失量、同决策 `hp-cost`/敌方 intent 对账，以及标记后的胜负。至少一个样本应能把损失量与自损/费用或敌方伤害账本对应；非白绮、非 Boss、未 `race_lost`、无损失或开关关闭时标记应为零。若第 10 局仍无样本，补充费用/事件证据而不改竞速阈值；若标记越界或改变动作/评分，立即关闭开关并回退分支。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：`SELFCHECK OK`。
- 独立 `test_boss_race_sustain.py` 已尝试，但 Python 3.14 受管临时目录触发 WinError 5 ACL 错误；未将环境失败伪报为测试通过。
- 目标 diff `git diff --check` 通过，无冲突；工作树中宿主挂载的 `.review_evidence/` 与其他无关变更未纳入本批。

## REPLAY

retry_resolution: 20260831-200515-1788177915907021900-8589e247 integrated

# 第 7~20 局批复盘：謦欬实付占致命战掉血过半，生命支付权重改按实测自损加码

日期：2026-09-05

## HYPOTHESIS

白绮 0/45 生涯的致命 Boss/终盘战掉血主要由謦欬（生命支付）自损构成，但 reflect 的生命支付权重适应只按「本局拿牌张数 ≥2」每局 -0.05 收紧，拿不到实战支付强度；对实测自损占掉血 ≥50% 的致命战再加一档收紧，权重将更快到达能抑制自损卡组的水平。

该假设可证伪：若未来 3~10 局致命战「自损N」段占掉血比例不下降（仍 ≥50%）、或收紧后拿牌/出牌形态与死亡形态均无变化，则假设不成立，删除加码分支与观测字段即整体回滚。

## EVIDENCE

- 近 16 局 runs 文件逐场实测（脚本统计 boss 层 play_card 理由内 hp-cost 累加 vs 战斗记录掉血）：15 场致命 Boss 战自损占掉血 59%~143%，13/15 ≥50%——run42 F33 自损83/掉血85、run43 F33 119/97、run39 F48 142/99、run33 F17 72/84、run35 F17 75/84。
- 批内最新死亡局 run 20（REV1WJECKYDZ，F17 SOUL_FYSH）完整决策链已读：续航账「净损EMA13.4/回合、同回合回血11、自损/费用85、零伤害回合3」，终盘「败局竞速全攻」仍以 hp-cost=4 打出【绯色面积】后 4 血 0 甲对 24 意图结束回合。
- 失败证据索引 sts2-ascend/.review_evidence/failed_review/index.json 已核对：target 包 retry_candidate.patch 与 wip.patch 均 0 字节（git checkout 超时，模型未产出），两个 attempt 包为生命周期停机全量保全、无候选改动——lineage 无可重实现内容。
- 生产 policy.py 已有 _race_same_round_loss 同回合净扣血逐 tick 实测账本（自损/费用口径），但此前只在续航账注展示，死亡归因与战斗记录均不消费。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：新增 combat_self_hp_loss() 访问器，口径与 BOSS_SUSTAIN 账注「自损/费用」字段严格一致。
- sts2-ascend/brain/agent.py：战斗聚合账累计 self_hp_loss_sum（多阶段分段累加）；died_in_combat 新增 self_hp_loss；战斗记录在自损>0 时追加「自损N」段（竞速审计段与（阵亡）后缀位置不变）。
- sts2-ascend/brain/reflect.py：白绮謦欬卡组阵亡的 -0.05 拿牌口径之上，致命战实测自损占比 ≥50% 时再加 -0.05（同一 BOUNDS (-3.0,-0.5) 钳制）；缺 self_hp_loss 字段的旧记录退回纯拿牌口径，行为与旧版一致。
- sts2-ascend/brain/selfcheck.py：3pra 夹具锁定三分支——自损 98% 双档收紧至 -1.35、24% 单档 -1.30、缺字段单档 -1.30，且加码证据入 lesson。

## EXPECTED_SIGNAL

未来 3~10 局：lessons 出现「謦欬实付加码收紧」且 ivhite_param_life_cost_weight 下探速度快于旧纯拿牌口径；战斗记录「自损N」段使每批可直接复核自损/掉血占比。有效信号：致命战自损占比降至 <50%、Boss 战回合数延长或出现首胜。证伪/回滚条件：10 局内自损占比不降、或权重触底 -3.0 后死亡形态不变——删除加码分支与观测字段即可整体撤回。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK。
- git diff --check 通过；完整 diff 已回读，仅 4 个生产/测试文件，无在线状态、无无关文件。

## REPLAY

retry_resolution: 20260905-121621-1788581781070312400-70149919 no_valid_change
