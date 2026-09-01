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
