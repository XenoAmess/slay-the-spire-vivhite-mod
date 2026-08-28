# 白绮屏幕左侧／远侧腿：语义拆件研究结论

## 结论

这组证据只通过了**研究门禁**，没有通过生产门禁，也不是可发布的 atlas 或 spritesheet。最终拓扑固定为：

- 两个 attachment：`far_thigh`、`far_lower_leg_with_boot`；
- 保留膝关节与 `far_knee` 骨骼；
- 取消独立脚踝／靴子 attachment，不再保留可见踝部接缝；
- 组内 draw order 从后到前为 `far_lower_leg_with_boot -> far_thigh`，让大腿遮住小腿上端的隐藏搭接；放入整身时再依次位于 `near_leg`、`skirt` 后方。

现有 `0078`、`0088`、`0063` 三张图全部只允许作为研究证据。它们不得进入正式 atlas，也不得被描述成已经完成的两件制生产美术。

## 为什么保膝、去踝

源码中的远侧腿骨链是 `thigh -> knee -> ankle -> foot`，当前 slot 固定按 `thigh(1) -> lower(3) -> foot(5)` 从后到前绘制，并且没有 draw-order 动画。历史动画的相对旋转极值为：大腿 `-8°..+58°`、膝 `-88°..0°`、踝 `0°..+21°`。

`-88°` 的膝弯是死亡等动作的实质运动需求，不能删除。相比之下，独立脚踝只贡献最多 `+21°`，却引入了白袜／靴筒接缝、靴口 pivot 与旧 foot-slot 原点不一致、三件比例漂移等风险。接触表也直接显示：当前固定顺序会让 `0088` 的小腿顶盖暴露，而 `0063` 独立旋转时靴口更容易断接。合并小腿与靴子能用一个隐藏膝搭接解决这些问题。

## 图片类型与读法

- `contact-sheet-sourceover-bluegray.png` 是五个研究姿势在蓝灰底上的 SourceOver 接触表。
- `contact-sheet-pivots-overlay.png` 是同五个姿势的骨点／pivot 叠加图；黄、粉、绿、紫依次为髋、膝、真实踝 pivot、旧 foot-slot 原点。
- 五格依次为旧 UV setup、物理靴口 setup、最大膝弯、最大踝弯、死亡链组合极值。

这两张图是多个验证视图拼接成的研究接触表，不是供游戏逐 region 消费的贴图页。

## 源码消费复核

- `tools/art/build_vivhite_combat_split_mesh_candidate.gd` 定义了当前三段 UV 灰盒、骨链、固定 slot 顺序、骨点和动作极值。
- `tools/art/candidates/semantic_split_v3/build_semantic_split_v3_candidate.gd` 已按 fail-closed 方式处理远侧腿：`0078` 仅标记为静态研究美术，`far_lower_leg_with_boot` 仍是待生成灰盒，独立 foot slot 为空，生产 ready 列表为空。
- `Vivhite/tools/candidates/semantic_left_leg/candidate.json` 固化了来源、Alpha/PCA、pivot、五姿势与拓扑决策；`validation.json` 必须继续保持 `production_gate_passed=false`。

## 2026-08-28 离线复验

使用 Godot 4.5.1 Mono 在隐藏 Windows Vulkan 进程中重建，随后 headless 校验：builder 和 validator 均为退出码 `0`；5 个 RGBA 姿势、三种 SourceOver 底色、两张接触表全部存在且哈希一致。校验器明确报告 `research_gate_passed=true`、`production_gate_passed=false`。

从仓库根目录复现时，`--path tools/art` 已将 `res://` 根设为 `tools/art`，所以脚本参数必须使用下面的 `res://candidates/...` 路径，不能再次写入 `tools/art/` 前缀：

```powershell
Godot_v4.5.1-stable_mono_win64_console.exe --path tools/art --display-driver windows `
  --rendering-driver vulkan --resolution 64x64 --position -32000,-32000 `
  --script res://candidates/semantic_left_leg/build_semantic_left_leg_candidate.gd

Godot_v4.5.1-stable_mono_win64_console.exe --headless --path tools/art `
  --script res://candidates/semantic_left_leg/validate_semantic_left_leg_candidate.gd
```

下一道生产门禁是：取得经批准的协调两件制美术，完成真 Alpha 与相邻部件 SourceOver 验收，将 lower-leg-with-boot 绑定到膝链并置于大腿后方，再以真实 Spine/Godot Vulkan 对全部战斗动画和整身 draw order 采样。未完成前不得接入 runtime。
