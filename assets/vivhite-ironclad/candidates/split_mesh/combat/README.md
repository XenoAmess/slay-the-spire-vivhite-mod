# split_mesh 战斗候选

这是“拆件 + 层级骨链 + 整图落地”的 **Hybrid 离线对照候选**，不是可发布素材，也不会被复制到
`Vivhite/Vivhite/skins/ironclad/`。

> **状态：** `preview_only_not_publishable`（以 [`candidate.json`](candidate.json) 为准）

返回上级索引：[`candidates/README.md`](../../README.md) · [`candidates/split_mesh/README.md`](../README.md)。证据型语义拆件报告：[`evaluation/README.md`](../../../evaluation/README.md)。

## 当前能验证什么

- 15 个可见部件分别挂在 33 根层级骨骼上，另有 1 根完全隔离的侧卧落地骨；手臂是
  `upper_arm -> forearm -> hand`，腿是 `thigh -> knee -> ankle -> foot`。
- 保留战斗消费方要求的 8 个动画、`slash_mesh` / `eye_attach_slot`，以及
  `attack_slash_start`、`heavy_slash_start`、`cast_eyes_start`、`clear_vfx`。
- 普通攻击、重击、受伤在场景 `.28` 下的根位移分别是 29.12、45.92、
  33.6 像素；肢体链会把末端手掌位移继续放大。
- `die` 在 0 秒清理 VFX，先用 `death_*` 预览拆件按髋、膝、踝、躯干、头和
  双臂错峰失衡下坠；根骨最大只旋转 7 度，不再把整张站姿卡片直接旋倒。
- `1.05 s` 原子卸载全部 15 个拆件预览，并在同一帧挂上独立
  `vivhite_death_body/vivhite_combat_death_side` 侧卧整图，避免两个不相似轮廓
  交叉淡化时产生双影。整图继续下落至 `1.17 s` 接触地面，`1.31 s` 轻微回弹，
  `1.80 s` 后保持静止直到 `2.3333335 s`。
- 最终源 `vivhite-combat-death-side-collapse-v2.png` 单独打入第二张
  `2048×1536` atlas 页，不改变站姿拆件、魔法弧或法阵的 UV。

## 动画衔接与绑定修订

- `_skeleton_data.tres` 逐条恢复原版战士提取资源的 10 条 transition mix：
  `idle_loop -> attack` 0.1、`idle_loop -> hurt` 0.03、
  `hurt -> idle_loop` 0.1、`idle_loop -> attack_heavy` 0.02；attack、heavy、
  hurt 的自切换和交叉切换，以及 `hurt -> die` 均为 0。未列出的切换仍使用
  `default_mix = 0.05`。
- 左右肩节点已从上臂节点向锁骨内侧分离，`shoulder -> upper_arm` 不再是零长度
  bind；setup pose 和上臂 attachment 的世界坐标保持不变。
- 所有骨骼 rotate/translate 关键帧段都写入 Spine 4.2 的绝对坐标 Bezier。
  循环动作使用平滑往返曲线，攻击、重击、受伤、施法和死亡使用更快进入的动作
  曲线；关键姿势、事件时刻、动画总时长和根位移不变。

## 为什么不能发布

当前 1680×2512 母图是单帧完整人物，而不是 spritesheet 或已拆分部件图。
它虽然是 EvoLink 原生 RGBA，四角透明，但整个人物外侧有半透明光晕，且所有
肩、肘、腕、髋、膝、踝都已压平为一张图。候选只为比较运动学，使用同一张
未改 Alpha 的 atlas region，通过 15 个 mesh 的 UV 子域和关节重叠来显示。
一旦大幅旋转，就会暴露接缝、重复光晕和缺少遮挡后像素的问题。

`candidate.json` 完整列出每个临时 UV 裁片、已核对的消费契约、Hybrid 死亡
切换窗口、风险，以及最终必须通过 EvoLink `gpt-image-2` 原生透明模式独立重绘
的站姿输入集合。死亡侧卧整图已接入候选；仍需补齐的是无光晕、带隐藏关节像素的
独立站姿部件。

## 离线验收结果

- 游戏实际 Spine 4.2.43 GDExtension + Vulkan 的 8 动画 × 5 帧检查通过，错误、
  空帧和触边均为 0。
- `die@1.04` 仍为拆件，`die@1.05` 已原子切换为侧卧整图；专项采样没有空帧或
  两套轮廓同时显示。
- 原子切换解决的只是空帧和双影，不等于姿势自然。精确 Vulkan 帧中，`1.04 s`
  的近竖直蜷缩轮廓 bbox 为 `237,445,242,250`，`1.05 s` 的横躺轮廓为
  `176,464,332,174`：左边界单帧向左跳 `61 px`、宽度增加 `90 px`、高度减少
  `76 px`。这是明确的 **preview candidate defect**；不得将它当作最终动画自然度，
  不可发布，也不可接入运行时。
- 站姿 setup bbox 为 `220×357`，死亡末帧为 `356×208`，侧卧宽度与站姿高度
  等量；末帧没有裁切。
- `die@1.80` 与 `die@2.3333335` 的渲染哈希相同，证明回弹结束后完全静止。

## 重新生成

```powershell
& '<Godot 4.5.1 mono exe>' --headless --path tools/art `
  --script res://build_vivhite_combat_split_mesh_candidate.gd -- `
  build-split-mesh-candidate `
  --death-source assets/vivhite-ironclad/custom/combat/sources/vivhite-combat-death-side-collapse-v2.png
```

脚本拒绝把输出目录指向 `Vivhite/Vivhite/skins/ironclad`，不会部署、重启或操作
游戏，也不会发起任何 EvoLink 调用。

## 证据原件

- 候选描述、消费契约、风险和 `deployable=false`：[`candidate.json`](candidate.json)；
- 战斗母源：[`custom/combat/sources/`](../../../custom/combat/sources/)；
- 侧卧死亡源：[`vivhite-combat-death-side-collapse-v2.png`](../../../custom/combat/sources/vivhite-combat-death-side-collapse-v2.png)。

上述链接仅用于复核，不改变候选的发布状态。任何将候选提升为生产资产的动作都必须先获得新部件、完成相邻 SourceOver 与整身 Vulkan 门禁，并更新对应验收报告。
