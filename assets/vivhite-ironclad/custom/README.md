# Custom 制作源

`custom/` 保存已经选定为制作输入、但仍需按消费者契约构建或复验的 PNG 源图。它不是 `approved/` 的替代品，也不是“目录里有文件就可以发布”的清单；构建器必须显式列出每个源图及其 hash。

| 子目录 | 内容 | 约束 |
| --- | --- | --- |
| [`character_select/`](character_select/README.md) | 选人英雄与魔法印记源图 | 私有 Spine rig/转场门禁 |
| [`combat/`](combat/README.md) | 战斗母源、动作峰值、VFX 和部件 | 不得套用原版战士骨骼 |
| [`rest_site/`](rest_site/README.md) | 休息点坐姿母源 | 三动画、翻转和火焰层序门禁 |
| [`ui/`](ui/README.md) | UI 与多人手势源图 | 多人手势仅限用户封闭例外 |

所有透明源图的生成血缘必须能回到 [`../generated/`](../generated/README.md)；若发现棋盘格、绿幕、程序抠图或不明来源，立即移入历史隔离区并保持 fail-closed。
