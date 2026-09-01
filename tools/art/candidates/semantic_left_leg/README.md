# semantic_left_leg：屏幕左 / 远侧腿研究候选

本候选研究角色朝屏幕右时的屏幕左（远侧）腿：`0078` 大腿、`0088` 小腿/袜筒、
`0063` 靴子三段输入。构建器只读取已归档 native-transparent PNG，在 setup 与消费者
极限上做刚性变换和 SourceOver 合成；不裁切、不阈值、不抠 Alpha、不镜像、不写 runtime。

## 结论与输出

- 当前三件路线会暴露膝/踝 seam 与遮挡问题；建议保留膝关节、把小腿+靴合成一个新
  语义附件，并移除独立踝 attachment。该建议不是已生成的生产素材。
- 默认输出 `Vivhite/tools/candidates/semantic_left_leg/`：`candidate.json`、
  `poses/*_rgba.png`、`poses/*_overlay.png`、三底色 `composites/`、蓝灰接触表及
  overlay 接触表。PNG 是诊断证据，不能作为 atlas 输入。
- manifest 会记录 0018/0022 身体母图、输入 SHA-256、层序和每个姿势的关节坐标；状态
  必须包含 `not runtime` / `not deployable`。

## 命令

```powershell
& $godot --headless --path .\tools\art `
  --script res://candidates/semantic_left_leg/build_semantic_left_leg_candidate.gd
& $godot --headless --path .\tools\art `
  --script res://candidates/semantic_left_leg/validate_semantic_left_leg_candidate.gd
```

这两个脚本没有位置参数；它们从仓库根解析固定来源和输出目录。validator 会复核
12 个不可变来源哈希、RGBA/四角、五个姿势与消费契约，并明确打印生产 gate 为 false。
若需要更高保真，先使用真实游戏消费者的 comparator；不要把 `0.70` 检查预览误报成
正式 scene scale。

