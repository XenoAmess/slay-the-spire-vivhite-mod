# 白绮后发（0031）离线验收结论

状态：**离线 Vulkan 研究候选通过，可继续进入完整语义头部与躯干组合；尚未接入正式运行时。** 当前证据不支持为后发继续付费生图。

## 素材与血缘

- 消费对象是一个独立的 Spine 后发 attachment，不是 atlas、spritesheet 或多图拼接页。
- 唯一图像源为 `0031-split-back-hair-attachment-attempt-01/output.png`；归档原图、提升后的 `custom/combat/parts/normal/vivhite-back-hair-v1.png` 和候选 atlas page 三者逐字节相同。
- 三者 SHA-256：`9fd66b599eb4128ba9c3b4c2bd815aadb0613e064aca2f697307997048c01782`。
- 原图保持完整 `1024×1024` RGBA8 画布；四角和四边 Alpha 均为 0。`A>=1 / 16 / 128` bbox 分别为 `[113,3,827,965] / [127,50,761,798] / [127,51,761,796]`。没有裁切、阈值、蒙版或 Alpha 后处理。

## 网格、权重与叠层契约

- 后发使用一个 `7×7` weighted mesh：49 个顶点、72 个三角形。
- 冠顶顶点 100% 绑定 `vivhite_hair_back`；下半部由 `vivhite_hair_left / center / right` 提供受控惯性。末梢三骨骼总权重不超过 `0.72`，因此根骨权重始终不低于 `0.28`。
- 本候选实际渲染顺序为：后发 `<` torso/neck `<` head-face `<` front-hair `<` butterfly；它足以
  验证后发冠顶、权重和接缝，但不再是总装层序真值。蓝蝶专项 A/B 的 16/16 Vulkan 证据随后
  证明前置蓝蝶会露出连接片，总装必须改为 head-face `<` butterfly `<` front-hair。
- `attack_heavy` 后发末梢压力峰值约 `+20°`，`hurt` 约 `-19°`；循环动作只使用低幅惯性。

## Windows Vulkan 逐帧证据

- 引擎/驱动：Godot 4.5.1 Mono、游戏实际 Spine GDExtension、Windows Vulkan。
- 显示契约：场景缩放 `.28`，制作比例 `.70`。
- 每个候选采样 8 个动画 × 21 帧；本后发候选共 168 帧，基线与候选合计 336 帧。
- 8 个动画为 `idle_loop`、`low_health_loop`、`relaxed_loop`、`attack`、`attack_heavy`、`cast`、`hurt`、`die`。全部动画通过契约检查，168 帧均非空、未触碰画布边缘且没有加载/Spine 错误；8 个动画都有实际帧变化。
- `relaxed_loop` 有 11 个唯一帧，首末帧哈希相同，最大质心位移约 `4.191 px`。它覆盖商店随机 seek 的任意相位。
- 实际显示尺寸人工检查未见冠顶脱离、双头、颈部穿透、明显三角折线或前后发接缝爆开。

## 商店消费契约

- 商店通过独立 `merchant_skeleton_data.tres` 复用 combat `.spjson + .spatlas`，场景仍使用 `.28`。
- 商店消费者播放 `relaxed_loop` 后随机设置 track time；所以任意相位都必须完整显示正确头部叠层。
- 候选在 `0` 与 `12.000001` 两端显式重申后发、头脸、前发和蝴蝶 attachment；循环首尾闭合。

## 边界与下一道门禁

- `die` 在 `t=0` 隐藏正常头部组并切换既有死亡预览层，因此本证据不声称已经验证倒地阶段的后发网格。
- 邻接的头脸、前发、蝴蝶和躯干目前仅用于隔离组合验证。正式采用前仍需通过完整语义头部 + torso 的跨组件 Vulkan 验收，再做游戏内实际画面审美验收。
- 2026-08-28 已重新执行离线构建器和静态验证器，均以退出码 0 通过；未部署、未启动或重启游戏，也未修改正式运行时资源。
