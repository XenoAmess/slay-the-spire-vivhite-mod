# 2026-08-30：Decimillipede 接续观测复盘

## 证据

- 本批 requested/exact runs 为 1162、1163、1164；最新完整失败链为 `E4UUZ5UQC7QN`，F25 Elite 战在 T7 阵亡。
- F25 决策链已经记录“重生体计入血池（全场无本体）”和“全场均为已证实重生体”，但没有记录某个段离场后是否仍在接续窗口内。
- v0.111.0 原生资料确认 `DECIMILLIPEDE_ELITE` 由 `DECIMILLIPEDE_SEGMENT_FRONT/MIDDLE/BACK` 三段组成；`REATTACH_POWER` 的描述为其他段存活时 2 回合后以 25 点生命复活。对应资料位于 `knowledge/game/v0.111.0/runtime/powers.jsonl`、`mechanics/encounters.jsonl` 和 `mechanics/monsters.jsonl`。

## 一个可证伪假设

Decimillipede 的通用重生体竞速账只看当前可见生命值，无法从决策链辨认离场段的原生 2 回合/25 生命接续窗口；这会使后续复盘无法判断竞速投影是否低估了未来血池。假设的可证伪信号是：以后出现该精英且至少一个段被载荷标为不存活或从三段集合中缺失时，决策理由应出现可解析的 `DECIMILLIPEDE_REATTACH_AUDIT`，并能与随后实际回归的段及生命值对账。

## 最小生产改动

- `brain/policy.py` 从原始战斗载荷识别三段 ID；仅在 `inactive > 0` 或 `absent > 0` 时追加 `DECIMILLIPEDE_REATTACH_AUDIT alive=a/3 inactive=i absent=m native=REATTACH_POWER(2t,25hp)`。
- `brain/knowledge.py` 新增 `decimillipede_reattach_audit=True`；设为 `False` 即移除观测。
- 观测不改变评分、竞速血池、出牌顺序或学习统计，也不把三段写入通用 learned respawn roster。
- `brain/selfcheck.py` 覆盖死段载荷、生产理由传播和开关回退。

## 验证与下一道门禁

`py -3 -B sts2-ascend/brain/selfcheck.py` 输出 `SELFCHECK OK`，`git diff --check` 通过。下一次遇到该精英时核对 `inactive/absent` 与实际 `REATTACH_POWER` 回归；在至少 3 个相关战斗完成对账前，不扩大为竞速血池或评分行为改动。若观测与实际回归不一致，先关闭 `decimillipede_reattach_audit` 并回看载荷契约。
