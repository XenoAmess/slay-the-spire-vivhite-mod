# 蓝蝶语义部件离线验收

本目录只保存 `0030-split-butterfly-attachment-attempt-01` 的最终隔离验收证据，不是正式 runtime 资源，也未启动或操作游戏。验收没有新增 EvoLink 付费调用，也没有修改原图 Alpha。

> **状态：** `isolated_graybox_not_runtime`。总索引：[`evaluation/README.md`](../README.md)。

## 固化证据

| 文件 | 内容 | SHA-256 |
| --- | --- | --- |
| `vulkan-contact-sheet.png` | Godot 4.5.1、Vulkan、场景缩放 `.28` 的最终 16 帧接触表 | `F30AABA594577BCD83D7B70F4B0E007C1ACBC81C27E1FC9F5B1D246BAAE920C4` |
| `vulkan-summary.json` | 每帧动画、时间、slot attachment、Alpha bbox、裁切状态与帧哈希 | `BAA53AC20573A27407930BB66705B214CFAF23AF8A0295064F51BB0BC568A184` |
| `component-analysis.json` | 原生 Alpha、pivot、消费者、层序和剩余生产门禁 | `2C0CD2925D02E7365D51C86FC8B8F5AD70A549612F54994A5472877C65C89590` |

`vulkan-summary.json` 中保留了 16 张逐帧输出的相对名称、SHA-256 和测量值；本目录不重复保存这些逐帧 PNG，接触表用于视觉复核，渲染工具可确定性重新生成逐帧文件。

原始蓝蝶输入：[`0030-split-butterfly-attachment-attempt-01/`](../../generated/evolink-paid/2026-08-28/0030-split-butterfly-attachment-attempt-01/)。候选制作副本：[`custom/combat/parts/normal/vivhite-butterfly-v1.png`](../../custom/combat/parts/normal/vivhite-butterfly-v1.png)。这些链接用于追溯，不因本报告通过而自动打包。

## 结果

- Vulkan 验收通过 `16/16`，错误数为 `0`，所有采样均有可见像素且没有接触画布边缘。
- 覆盖 setup 层序 A/B、正负最大旋转、八个战斗消费者、死亡解绑，以及商店 `relaxed_loop` 的随机 seek。
- 使用真实相邻部件 `0031` 后发、`0044` 头脸和 `0033` 前发。蓝蝶放在最前层会露出过长的深蓝金边连接片；生产层序应把蓝蝶置于前发之后。
- 死亡动画在 `1.05s` 前保持唯一蓝蝶，在 `1.05s` 与身体切换同步解绑；商店随机 seek 的 `1.37 / 5.4 / 9.9 / 12.000001s` 均保持唯一、正确层序。

## 原生 Alpha 与挂点

- 源图和候选页 SHA-256 均为 `A8FEDB56C6D4A4388FA60CDB3CB66435F3CC6720A47754F53CC9F1F9A449458C`。
- 图片为 `1024×1024 RGBA8`，四角 Alpha 均为 `0`，外边缘非零 Alpha 像素数为 `0`。
- `Alpha >= 16` 时只有一个连通对象；bbox 为 `[169, 36, 693, 862]`。
- 推荐源图 pivot 为 `(176, 650)`，该像素 Alpha 为 `253`；隔离骨架头部挂点为 `(100, 110)`。

## 生产判断

`0030` 原图可直接作为一个不拆分的刚性 Spine region，不需要重生、传统抠图或 Alpha 修补。它仍不是可直接部署的 runtime 文件：必须在统一生产头骨架中创建唯一蓝蝶 slot，将其放在前发 slot 之前，并保留 `die@1.05s` 解绑；合并完整身体后还需做战斗与商店的全身协调验收。

Godot 自动生成的 `.import`、`.uid` 和 `.godot` 缓存不属于本验收证据，禁止加入 Git。

## 晋级门禁

总装必须采用“后发 → 头脸 → 蓝蝶 → 前发 → 前景右臂”的层序，保留 `die@1.05s` 的唯一蓝蝶解绑，并在真实 combat 场景重新验证 EyeFire、最大旋转和商店 seek。完成前，本目录中的接触表只作为研究证据。
