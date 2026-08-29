# CARD_BURST_PICK_AUDIT

本次复盘把输出饥饿问题收敛为一个可证伪的观测假设：奖励选牌是否真正增加
`deck_effective_burst`，此前没有在最终选牌理由中留下 before/after/delta，因此无法
把供给补强与静态价值上升区分开。

`brain/policy.py` 现在在 REWARD 的最终 `choose_reward_card` 路径追加
`CARD_BURST_PICK_AUDIT`，复用已有 `deck_effective_burst` 和 `_starve_line`。审计发生在
受控探索之后，记录最终实际要点击的卡；`brain/knowledge.py` 的
`card_pick_burst_audit` 默认开启且可关闭。该改动只写理由，不改变评分、排序、门槛、
探索配额或动作。

验证夹具覆盖 marker、before、after、delta 字段，完整 selfcheck 结果为 **SELFCHECK OK**。
后续 3~10 局统计 delta；若饥饿态选牌不产生有效增量，则该假设被证伪，停止沿此方向
增加策略门控。
