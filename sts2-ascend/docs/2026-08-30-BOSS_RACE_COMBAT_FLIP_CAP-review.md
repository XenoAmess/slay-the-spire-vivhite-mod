# Boss 战斗端翻盘比复核

1168-F33 的链条显示，T3 已按实测输出判定斩杀竞速失败，T4 却重新出现联合防守
复核。问题不在接口或结算：原生 v0.111.0 的 THE_INSATIABLE 有双段 THRASH、
力量增长的 SALIVATE，以及会生成 Frantic Escape 的 LIQUIFY_GROUND，静态平铺
攻防产能不适合作为无限长 Boss 计划的充分证明。

本次复用已有 `boss_race_joint_flip_max_ttk_ratio`，但把收紧范围限定为 Boss 战斗端；
超限时保留竞速状态并写 `JOINT_FLIP_TTK_CAP`，非 Boss 不变，键为 0 可回滚。自检
同时覆盖开启和回滚两态。经验是：前夜与战斗若共享同一“翻盘证明”，必须共享其否决闸门，
否则持久理由会表现为同一场战斗前后自相矛盾。
