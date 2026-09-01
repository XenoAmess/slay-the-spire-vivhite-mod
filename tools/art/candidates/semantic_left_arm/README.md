# semantic_left_arm：屏幕左 / 远侧手臂灰盒

历史 `*_left` 名称按屏幕坐标命名；在白绮朝屏幕右的战斗姿势中，本目录实际表示
**角色解剖右臂、屏幕左、远侧**，应绘制在躯干后方。它是纯几何 consumer graybox，
不含角色美术，付费生图次数固定为 0，永远不可发布。

## 固定拓扑

- 两个活动件：`far_upper_arm` 与 `far_forearm_hand`；肩部遮挡由
  `torso_shoulder_cover` 负责，腕只作为测量锚，不拆成独立生产 attachment。
- Spine 4.2.43、`default` skin、八个 combat 动画和四个兼容事件仍需存在，以便同一
  比较 harness 能加载；固定绘制顺序为 `far_upper_arm → far_forearm_hand → torso_cover`。
- `contract.json` 明确 `diagnostic_graybox_only_not_publishable`、无可用独立美术、
  肩/肘隐藏重叠下限和 upper/forearm 旋转包络（`-35..+71°`、`-48..+55°`）。

## 命令

```powershell
& $godot --headless --path .\tools\art `
  --script res://candidates/semantic_left_arm/build_semantic_left_arm_candidate.gd -- `
  build-semantic-left-arm-candidate
& $godot --headless --path .\tools\art `
  --script res://candidates/semantic_left_arm/validate_semantic_left_arm_candidate.gd -- `
  validate-semantic-left-arm-candidate
```

builder 支持 `--output-root PATH`，validator 使用 `--root PATH`；默认输出为
`Vivhite/tools/candidates/semantic_left_arm/`，含灰盒 page、wrapper、`.spjson/.tres`
和契约 JSON。builder 会在生成输出中写一份机器说明 README，validator 也会检查该
输出文件；源目录 README（本文件）是人类使用说明，两者不要混淆。

这里的“通过”只表示拓扑、pivot、层序和事件契约可复现。获得生产美术前不得调用
发布器；任何新透明手臂都必须另走 EvoLink 原生透明链并完成 Alpha/相邻关节验收。
