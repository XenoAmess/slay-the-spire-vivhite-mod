# 2026-08-30：Boss Slippery 联合复核闸门

本批第 1169~1172 局均在 F17 Boss 失败。1172 的 T1 决策同时出现“防守线复核：格挡3+输出13/回合”和墨影幻灵滑溜 8 层下打击约 1 伤害，说明静态 `_race_joint_feasible` 把敌方 power 机制漏算了。

本次只在 Boss 战斗端的 `race_lost` 分支加最小闸门：实时 Slippery 大于 0 且静态联合复核返回可行时，保留竞速判负并记录 `SLIPPERY_RACE_GUARD`。配置 `boss_race_slippery_joint_guard=False` 可回滚；非 Boss、无 Slippery 和原本不可行的路径不变。

验证：`py -3 -B sts2-ascend/brain/selfcheck.py` 输出 **SELFCHECK OK**，`git diff --check` 通过。后续 3~10 场观察闸门触发数、触发决策中的防守线复核残留、Boss race audit 与实际战损；若闸门触发却稳定可胜，或 3 场以上未改善后段战损，先关闭配置再复盘。
