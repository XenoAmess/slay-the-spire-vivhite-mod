# semantic_right_leg：屏幕右 / 近侧腿研究候选

本目录审计角色朝屏幕右时的屏幕右（近侧）腿：`0083` 大腿、`0100` 小腿、被方向
阻断的 `0064` 靴子，并对比三段冻结顺序与“小腿+靴一体”的二段拓扑。它只做
SourceOver 诊断，不修改运行时皮肤、不调用付费生图。

## 事实与结论

- `candidate.json` 记录 12 个来源哈希、固定 7/9/11 层关系、setup/`+82°` 膝极限和
  `-18°` 踝极限。三件路线被明确阻断；二件路线只是下一轮新透明生成的建议。
- 输出的五张 contact sheet（black/white/game、轴向冲突和 0064–0071 对照）是诊断
  图，不是 spritesheet/atlas，也不能把 `0100 + 0064` flatten 后放进 runtime。
- 状态必须保持 `research_only_not_publishable`；validator 通过不等于拓扑已有生产资格。

## 命令

```powershell
& $godot --headless --path .\tools\art `
  --script res://candidates/semantic_right_leg/build_semantic_right_leg_candidate.gd -- `
  build-semantic-right-leg-candidate
& $godot --headless --path .\tools\art `
  --script res://candidates/semantic_right_leg/validate_semantic_right_leg_candidate.gd -- `
  validate-semantic-right-leg-candidate
```

builder 和 validator 都支持 `--output-root PATH`，默认根为
`Vivhite/tools/candidates/semantic_right_leg/`。两者会核对已验收来源、split consumer
和层序；所有输出留在候选/`.work`，失败时保留 JSON 与接触表。要继续生成，必须先
通过结构性二段方案门禁，并重新走 EvoLink 原生透明、相邻膝/踝极限和 Alpha 验收。
