# `sts2-ascend/docs` — Brain 局内复盘记录

本目录保存 Brain 在对局后产出的局部复盘、观测和策略审计记录。它是 `sts2-ascend/knowledge/` 运行态知识的可读证据镜像，不是新的配置入口，也不替代仓库根 [`docs/README.md`](../../docs/README.md) 中的架构、事故和发布报告。

## 这类文件记录什么

- Boss 结算窗口、致死竞速、回血/能量预留和卡牌选择等局内决策证据；
- 由具体 `run_id`、观测快照或复盘批次触发的假设、修正和后续门禁；
- 仍在验证中的策略观察，而不是对所有版本、角色或敌人的永久保证。

文件名可能混用英文审计标识、中文主题或 `-review` 后缀；不要按文件名推断当前策略是否已生效。阅读时先看文件内的日期、证据、结论和遗留风险，再回到 [`brain/README.md`](../brain/README.md)、当前源码与根 [`AGENTS.md`](../../AGENTS.md) 对账。

## 当前记录索引

截至 2026-09-01，本目录有 18 份局部记录：

| 主题 | 记录 |
| --- | --- |
| Boss/结算/致死窗口 | [`BOSS_SETTLE_TIER3`](2026-08-29-BOSS_SETTLE_TIER3-review.md)、[`BOSS_RACE_AUDIT_HEAL_OVERRIDE`](2026-08-30-BOSS_RACE_AUDIT_HEAL_OVERRIDE-review.md)、[`BOSS_RACE_COMBAT_FLIP_CAP`](2026-08-30-BOSS_RACE_COMBAT_FLIP_CAP-review.md)、[`BOSS_RACE_COMBO_GATE_UNIVERSAL`](2026-08-30-BOSS_RACE_COMBO_GATE_UNIVERSAL-review.md)、[`BOSS_RACE_SLIPPERY_GUARD`](2026-08-30-BOSS_RACE_SLIPPERY_GUARD-review.md)、[`LETHAL_SETTLE_EXTENSION`](2026-08-30-LETHAL_SETTLE_EXTENSION-review.md)、[`lethal-kill-race-allocation`](2026-08-30-lethal-kill-race-allocation.md)、[`lethal-kill-race-attack`](2026-08-30-lethal-kill-race-attack.md)、[`SETTLE_TIMEOUT_STATE_AUDIT`](2026-08-30-SETTLE_TIMEOUT_STATE_AUDIT.md) |
| 卡牌/资源/战斗观察 | [`CARD_BURST_PICK_AUDIT`](2026-08-30-CARD_BURST_PICK_AUDIT-review.md)、[`条件成长能力牌误判`](2026-08-30-条件成长能力牌误判.md)、[`能力牌能量预留复盘`](2026-08-30-能力牌能量预留复盘.md)、[`高血池普通战翻盘复核`](2026-08-30-高血池普通战翻盘复核.md)、[`low-pool-burst-observation`](2026-08-31-low-pool-burst-observation.md)、[`Bygone 唤醒竞速火力修正`](2026-08-30-Bygone唤醒竞速火力修正.md) |
| 运行时边界 | [`native-save-barrier 异常旧局旁路修复`](2026-08-31-native-save-barrier异常旧局旁路修复.md)、[`unittest 生产日志隔离`](2026-08-31-unittest生产日志隔离.md)、[`Steam 评论/Vulkan open beta`](2026-09-01-steam-comments-vulkan-openbeta.md) |

## 与在线知识的关系

`knowledge/` 和 `.runtime/` 由生命周期脚本及 Brain 事务维护，禁止手工编辑、删除、改名或复制来制造“已完成”状态。这里的 Markdown 记录也不能被当作动作授权：`MAIN_MENU`、`run_unknown`、终局或孤儿账本阻塞时，Brain 必须保持 fail-closed，直到产生权威的 `/state`、Continue/存档或一次性恢复证据。

复盘模型可以提出策略修正，但源码、配置和静态文档的变更仍须经过隔离审计、测试和正常 Git 事务。若记录与当前代码或 `AGENTS.md` 冲突，以当前规则和可复核的运行证据为准，并追加新的报告，不覆盖旧记录。

## 维护规则

1. 新记录沿用 `YYYY-MM-DD-主题.md` 或已有复盘标识，写清 `run_id`/角色（若可公开）、证据路径、结论和下一步；不要写入凭据或原始运行态密钥。
2. 新增文件后同步更新本索引和根 `docs/README.md` 的主题/日期入口；历史记录只追加，不改写已发布结论。
3. 本目录是 Brain 复盘证据，不是发布物料。Workshop Changelog、版本和预览图应写入 [`workshop/`](../../workshop/README.md) 的发布闭环。
