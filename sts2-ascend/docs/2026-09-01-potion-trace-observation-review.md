# 2026-09-01｜药水动作 trace 观测复盘

本批从第1231局 F17-T1 的完整决策链定位到一个可复现的观测缺口：`use_potion`
动作虽然进入持久 trace，但候选仍由 COMBAT 手牌生成，无法在驾驶舱或复盘中直接
看到被消费的药水。批次1220~1231还出现11次“描述无法分类”药水动作，原生
v0.111.0 药水快照则提供稳定 ID，足以支持后续结果对账。

最小修复是在 `policy.py` 的三条药水返回分支写入已有 trace 候选，包含药水名称/ID、
槽位和已计算分类；未知分支保留 `POTION_UNKNOWN_FALLBACK` 标记。它只复制当前
决策已经算出的值，不改变动作、评分、去重或资源消费。`selfcheck.py` 增加未知药水
候选被选中的回归断言，验证 trace 的槽位、动作和 `chosen` 状态。

关键注意事项：持久候选必须使用 `use_potion` 的 `option_index` 与原状态槽位一致，
否则 `DecisionTraceBuilder.finish` 无法标记真实选择；观测应先验证3~10局，不能把
未知药水 trace 缺口直接升级为消费策略改变。

验证：`py -3 -B sts2-ascend/brain/selfcheck.py` 输出 `SELFCHECK OK`；回滚三处
`_trace_candidate` 调用和测试断言即可，生产决策不受影响。
