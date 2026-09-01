# V3 独立死亡动作验收

> **状态：** 离线帧/切换契约通过，仍需完整 VFX、相邻动作中断和真机复测。返回总索引：[`evaluation/README.md`](../README.md)。

本目录保留 `hybrid_death_v3` 的可复核离线证据，不是正式 runtime 资源。

- 美术源：`assets/vivhite-ironclad/custom/combat/sources/vivhite-combat-death-side-collapse-v2.png`
- 美术源 SHA-256：`9B391E6DAE9AC1E85D05D77B3B0E7E286BF2F0B613E164C714A99054EC12A17B`
- 候选骨架 SHA-256：`121EAD61910B2D5AA2CC745D136C1A4F36DA5718720F45A41BDFF402E3D09E56`
- 消费契约：`hurt` 预滚 `0.5s`，`die` 在 `1.05s` 原子切换到唯一侧卧 attachment，人物层不做交叉淡化。
- 渲染环境：Godot 4.5.1、Windows display、Vulkan、真实游戏 Spine GDExtension、场景缩放 `.28`。
- 结果：16/16 精确采样帧通过；人物层始终恰好一个 attachment；无空帧、双影、触边或残留 VFX。
- 连续性：实体左边界跳变从旧方案的 `61px` 降至 `16px`，实体底边跳变 `1px`；落地序列为 `684, 686, 680, 684, 684px`。

`die-exact-character-only.png` 与 `die-exact-composite.png` 当前逐像素相同，因为该专项验收会清空刀光、眼火和法阵，专门证明人物切换本身。完整动作集整合后仍须复测场景 VFX、相邻动作中断和用户真机观感。

源图可在 [`custom/combat/sources/vivhite-combat-death-side-collapse-v2.png`](../../custom/combat/sources/vivhite-combat-death-side-collapse-v2.png) 复核；候选与帧摘要仅保存在本目录，不能直接替换正式运行时 atlas。
