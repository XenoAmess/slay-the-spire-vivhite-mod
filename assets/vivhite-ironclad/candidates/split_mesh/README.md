# split_mesh 候选集合

本层是拆件候选的索引；具体战斗候选见 [`combat/README.md`](combat/README.md)。它把部件 UV、Spine 层级骨链、动画事件和死亡侧卧整图放在同一份离线对照里，目的是验证运动学与消费者契约，不是产出运行时贴图。

当前唯一子项目：

- [`combat/`](combat/README.md)：15 个临时可见部件、33 根层级骨骼和 1 根侧卧落地骨；`candidate.json` 的状态是 `preview_only_not_publishable`。

任何重建都必须把输出留在候选目录，脚本不得指向 `Vivhite/Vivhite/skins/ironclad/`，也不得触发游戏、EvoLink 或部署。真正的生产部件必须从干净参考重新生成，并重新走 `evaluation/` 的 Alpha、相邻部件和整身 Vulkan 门禁。
