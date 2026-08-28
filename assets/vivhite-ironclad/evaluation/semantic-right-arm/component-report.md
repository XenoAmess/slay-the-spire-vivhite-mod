# 白绮近侧手臂语义组件离线验收

> 组件 ID：`near_screen_right_anatomical_left_arm`
>
> 验收日期：2026-08-28
>
> 状态：**消费契约与无美术灰盒通过；生产美术尚缺，禁止部署。**

## 结论

战斗画面中位于屏幕右侧、靠近镜头的一条手臂，是白绮解剖学上的**左臂**。历史 split
builder 的 `*_right` 只表示屏幕侧，不能继续当作解剖学命名使用。

该语义组冻结为两个生产 attachment：

1. `upper_arm`：肩部为 pivot，位于躯干提供的肩袖／袖窿遮挡层之后；
2. `forearm_hand`：肘部为 pivot，前臂与手掌保持一个连续轮廓，位于上臂和躯干之前。

手腕不建立贴图接缝。`near_palm_deform` 只是 `forearm_hand` 内部的加权形变与 VFX 锚点骨，
不是第三张手掌 attachment。这样保留肘部的大幅相对旋转，同时避开当前最高风险的腕部断缝。

本轮复跑了 9 个既有动作极值：setup、低血、普攻前摇／峰值、重击峰值、施法前摇／峰值、
受伤峰值和死亡终态。所有姿势保持刚性上臂长度 `130.7027` world units、连续前臂手长度
`207.4290` world units，旋转均位于冻结包络内，肩根、肘部搭接和层序门禁均通过。

这只是消费架构灰盒，不是生产美术或真实 Spine 贴图验收。接触表由 Godot 4.5.1 的隐藏
Windows Vulkan 进程绘制几何诊断图；候选本身没有 raster、atlas 或可发布 attachment，因而
不能据此声称白绮身份、Alpha、真实关节接缝、atlas 或运行时动画已经通过。

## 原版素材与源码消费证据

- 原版 `ironclad.atlas` 是多 region atlas，不是一幅可整体重绘的插画。手臂至少拆有
  `bottom/top upper arm`、`bottom/top lower arm`、hand/fingers，并另有 attack 变体；原版
  做法说明肘部相对运动和前后层序确实重要，但其持剑战士骨骼、网格、姿势和 region 不会被
  白绮生产方案复用。
- 原版 `combat/scene.tscn` 与当前白绮私有 `combat.tscn` 都保留场景 `scale=(0.28,0.28)`、
  `SlashVfxSlot.slot_name="slash_mesh"`、`show_behind_parent=true` 以及原 Bounds／CenterPos／
  IntentPos 锚点。
- v0.111.0 反编译 `NIroncladVfx` 监听 `attack_slash_start`、`heavy_slash_start`、
  `cast_eyes_start` 和 `clear_vfx`。普通／重击事件控制 slash shader 的 `step` tween；它不从
  手臂图片推断掌心，也不应要求手臂美术烘入魔法弧。
- 当前 split builder 的实际 pivot 权威是 `0018`，不是只用于新视觉方向比较的 `0022`。
  已冻结的源像素点为肩 `(810,545)`、肘 `(1040,650)`、掌内形变点 `(1430,555)`、魔法弧
  锚点 `(1500,530)`；转换使用完整 `1680×2512` 画布、`868×1302` authored world 与
  场景 `.28`，不能按部件 Alpha bbox 各自重新归一化。

## 层序、搭接和 VFX 所属

灰盒 attachment / consumer 的枚举顺序为：

```text
near_upper_arm_back
< torso-owned near_shoulder_occluder_reference
< near_forearm_hand_front
< external slash_mesh consumer record
```

末项表示魔法弧必须是手臂之外的独立消费者记录，不代表把弧烘入前臂，也不单独裁定最终
视觉前后层；真实场景的 `SlashVfxSlot` 仍明确设置 `show_behind_parent=true`。

- 上臂肩根隐藏搭接 `48 px`，肘端延伸 `32 px`，关节端帽半径 `44 px`。
- 前臂手在肘部的隐藏搭接 `64 px`，关节端帽半径 `44 px`。
- 躯干语义组必须提供以肩 pivot 为中心、最小覆盖半径 `96 px` 的肩袖／袖窿前景遮挡。
  若躯干终稿无法提供，增加单独的 shoulder-front attachment；禁止把上臂整体提到躯干前面
  来掩盖缺口。
- 魔法弧归 `slash_mesh` 与 `NIroncladVfx` 消费链所有，不归 `upper_arm` 或
  `forearm_hand` 美术。setup 下它相对掌内形变点位于源图右上 `(+70,-25 px)`，即 Spine world
  约 `(+36.17,+12.96)`；未来统一骨架应让独立 arc anchor 跟随 `near_palm_deform`。普攻／重击
  的姿势特定偏移仍由动作消费者校准。手臂两张生产图都必须保持空手、无武器、无法球、
  无烘入辉光。

## 生产美术缺口与下一道门禁

仓库当前没有可用于生产的原生透明 `upper_arm` 或 `forearm_hand`：

- `0018/0022` 都是压平的完整人物，肩、肘遮挡后的隐藏像素不存在，只能提供 pivot／轮廓证据；
- `0054` 是相邻躯干／袖口候选，不是手臂源，而且仍需由躯干语义组决定最终肩袖遮挡；
- 本候选目录刻意含 0 张 PNG、0 个 atlas page、0 个可发布 region，且未调用 EvoLink。

进入付费生成前，必须由总集成候选先冻结最终 neutral setup pose、躯干肩袖遮挡和上臂／
前臂手的真实轴线。随后分别生成一张 `upper_arm` 与一张连续 `forearm_hand` 原生透明单幅素材，
按真实相邻层在 setup 与上述 9 个最大旋转姿势做 SourceOver、关节搭接和 Windows Vulkan
验收；通过前继续保持 fail-closed，不进入正式 atlas。

## 本轮复验

执行命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/art/candidates/semantic_right_arm/Invoke-SemanticRightArmGraybox.ps1
```

结果：

- Godot `4.5.1.stable.mono`；
- Vulkan `1.4.312`，NVIDIA GeForce GTX 1060；
- `9/9` 姿势，`2` 个目标 attachment，`0` 个 raster asset；
- `validation-summary.json`：`passed=true`、`error_count=0`；
- 未启动游戏、未修改正式 runtime、未部署、未调用付费生成。

## 固化证据文件与 SHA-256

| 路径 | 字节 | SHA-256 |
| --- | ---: | --- |
| `assets/vivhite-ironclad/evaluation/semantic-right-arm/extreme-poses.png` | 102192 | `ccf1e73bfe54579b98909894a8dbdbc5d08707961d665a1ad9072438ac9d0b18` |
| `assets/vivhite-ironclad/evaluation/semantic-right-arm/validation-summary.json` | 4092 | `f2ae2e2f40c7384960399b180fa6fd3a1b54edd6c89e27bb807739d553ec4c64` |

## 候选实现文件与 SHA-256

| 路径 | SHA-256 |
| --- | --- |
| `tools/art/candidates/semantic_right_arm/build_semantic_right_arm_graybox.gd` | `9f9abc4bc0054aa11e4e5e9c69d1a028baec83ab040bb8632dcf3c2118fe83a6` |
| `tools/art/candidates/semantic_right_arm/validate_semantic_right_arm_graybox.gd` | `36216317dab5bdcb0418bb3b40992ddf5f6b75ea947dbc44a991e35b3e864453` |
| `tools/art/candidates/semantic_right_arm/render_semantic_right_arm_extremes.gd` | `540260607a74501b260feffbff5ce8ac19de0a095fb34c7aebcf5e3f52830f9e` |
| `tools/art/candidates/semantic_right_arm/Invoke-SemanticRightArmGraybox.ps1` | `628c82155cc21c6a9b55320049f2a748adac64b19f08077de31cc82039d965b5` |
| `Vivhite/tools/candidates/semantic_right_arm/README.md` | `380428bcbbd152855b9f1d27b12f7d250888a5e913811390a3ea746f52b0508d` |
| `Vivhite/tools/candidates/semantic_right_arm/consumer-contract.json` | `a639f1f42a882f6bf91a1fcbbb4a892cfe47f0746d67903c37536621ccc592db` |
| `Vivhite/tools/candidates/semantic_right_arm/vivhite_semantic_right_arm_graybox.spjson` | `6bb94cde0539e36d30eec5528821edc6689a81dba11799d7baa0728cdca56c5d` |

## 关键输入与消费者 SHA-256

| 证据 | SHA-256 |
| --- | --- |
| `0018 .../output.png` / `custom/combat/sources/vivhite-combat-body-master-v1.png` | `86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1` |
| `0022 .../output.png` | `488e74758164dab0702ec6f943e02d23d9561caef29320275f698cb0000e232e` |
| `0054 .../output.png` | `70a293dd908af44aee0d9921cd5e4ac4d542105ba6717d8233705ec1a4a7cc35` |
| `tools/art/build_vivhite_combat_split_mesh_candidate.gd` | `db7deebd7f81a0e5a35479ed66718317cafd091ddcef8369c2336ad4f8238895` |
| `.work/ironclad-v0.111.0/combat/scene.tscn` | `37c634e979a689f22e95e130ff27dbbe0a494291b82d4786b4839840c311d93e` |
| `.work/ironclad-v0.111.0/combat/ironclad.atlas` | `80c02b8edd1cb9b6d7316ff08eeb020250302123544dc71c6457d54254bd3c54` |
| `.work/ironclad-v0.111.0/combat/ironclad.skel` | `74b3923522927e2056ab624df79e83e861697b1057ba5fd39582f033f903facf` |
| `.work/sts2-decompiled-v0.111.0/.../NIroncladVfx.cs` | `e383ffc51c13921273c17c7ab37dbff24372fe2ae9458d95dabe3b3c28bf3eba` |
| `Vivhite/Vivhite/skins/ironclad/scenes/combat.tscn` | `138109ea30e904cc1dd6be3e390cbc56b0b6936f80767f27f55cd901ca52ad4b` |
