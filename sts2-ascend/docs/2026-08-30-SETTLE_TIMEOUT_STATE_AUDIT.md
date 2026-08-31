# 2026-08-30｜SETTLE_TIMEOUT_CONCEDE_OBS 状态观测

## HYPOTHESIS

结算超时收口时，`latent` 非空并不等于能够安全等待：接口可能仍未开放出牌，
而玩家已经会吃到当前意图。若记录收口瞬间的生命、格挡和 incoming damage，
就能用下一条决策链中的实际掉血量检验「接口锁定导致零格挡收口」这一解释。

## EVIDENCE

- 第 1199 局 `3HDJ9UH4AZ5K` 的 F33 决策 386 记录 `hp=62`、`block=0`、
  当前意图 28，`latent=重振精神+(1)`；下一条决策的 HP 为 34。
- 原生 v0.111.0 知识确认 `SecondWind` 是 1 费技能，获得 5 格挡并消耗
  手牌中的非攻击牌；同一手牌中的 `Normality` 为不可用诅咒。
- 这是现有结算超时标记的新独立样本，尚不足以直接改变等待预算或出牌策略。

## IMPLEMENTATION

保留原有 `SETTLE_TIMEOUT_CONCEDE_OBS` 闸门和行为，仅在标记后追加
`hp`、`block`、`incoming` 三个收口状态字段，并在 selfcheck 夹具中锁定字段存在。
没有新增预算、强制出牌或改变 `end_turn` 判定。

## EXPECTED_SIGNAL

后续 3–10 局收集标记次数、收口状态及下一决策的 HP 变化，检查
`incoming - block` 是否与实际掉血一致，并区分接口锁定和真实无牌可出。若样本
持续无法对账或没有同型暴露，保持观测或关闭 `end_turn_settle_concede_obs`；
只有达到至少 3 个独立样本后才重新评估预算行为化。

## VALIDATION / ROLLBACK

- `py -3 -B sts2-ascend/brain/selfcheck.py` 必须输出 `SELFCHECK OK`。
- 回滚只需将 `end_turn_settle_concede_obs` 设为 `False`（或移除新增字段）；
  既有等待预算和收口判定不受本次改动影响。
