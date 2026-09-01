# assets — 美术与游戏基线资产

`assets/` 保存两类互相隔离的资料：从本机《杀戮尖塔 2》提取的只读原版基线，以及白绮/Ironclad 视觉替换的制作、评估和发布源。资产目录不是自动安装目录；运行时只消费经过源码消费契约、Alpha 检查、PCK 门禁和真机验收的明确文件。

## 子目录

| 路径 | 用途 | 运行时可直接消费？ |
| --- | --- | --- |
| [`ironclad-v0.111.0/`](ironclad-v0.111.0/README.md) | v0.111.0 + Godot 4.5.1 的原版 Ironclad 提取快照、atlas/Spine/场景布局和 provenance | 否，作为只读模板 |
| [`vivhite-ironclad/`](vivhite-ironclad/README.md) | 白绮角色的参考图、EvoLink 原图、候选、已验收源和历史污染留档 | 仅 `custom/`/`approved/` 中经门禁的明确产物 |

`vivhite-ironclad/` 内的集合级 README 说明 references → generated → candidates/evaluation → custom/approved 的生命周期；不要为方便打包而跨集合复制或改名素材。`legacy-contaminated/` 可以留作审计证据，但永远不得作为新生成参考、atlas 输入或运行时资源（四张多人手势的封闭恢复例外除外，详见子目录说明）。

## 图像判定与版权边界

在分析任何 PNG 前，先确认它是单幅成品、单帧、atlas/spritesheet 还是多个区域拼接，并同时读取相邻 `.atlas`/`.spatlas`/Spine JSON/场景元数据和实际 C#/GDScript 消费方。透明素材必须来自仓库规定的 EvoLink `gpt-image-2` 原生透明路径；禁止程序抠图、色键、蒙版或把图集整页交给模型重绘。原版游戏资源只用于本地研究和 Mod 构建，不在仓库外重新分发。

详细生产流程见 [`../tools/art/README.md`](../tools/art/README.md) 和 [`vivhite-ironclad/README.md`](vivhite-ironclad/README.md)。
