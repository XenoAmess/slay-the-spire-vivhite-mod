# 候选资产

`candidates/` 是离线研究、灰盒和运动学对照区。候选可以包含临时 UV、Spine 骨架、接触表和诊断脚本，但**绝不能直接复制到** `Vivhite/Vivhite/skins/ironclad/`。

## 目前的候选集合

- [`split_mesh/`](split_mesh/README.md)：拆件、层级骨链和死亡整图切换的 Hybrid 候选；其 `candidate.json` 明确标记 `preview_only_not_publishable`。

语义部件的独立研究报告位于 [`../evaluation/`](../evaluation/README.md)。候选目录中的 PNG 可能仍带有整体光晕、压平关节或临时灰盒；它们不是可发布素材。

## 候选晋级

晋级必须同时满足：素材布局与源码消费者已核对、原生 Alpha/相邻 SourceOver 验收通过、真实 Godot/Spine Vulkan 动画和层序采样通过、运行时 manifest/PCK 合同通过。任一证据缺失就保持 `fail-closed`，不通过改名、复制或手工修改 `knowledge/` 绕过。
