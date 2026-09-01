# hybrid_hurt_neutral：受伤保护收缩候选

这是一个只改时间线的隔离实验：从 `hybrid_action_set` 快照全部 authored 文件，再把
`hurt` 替换为 neutral whole-mesh 的保护性收缩、后撤与回弹。它不新增 PNG、不改变
atlas 页，也不写正式 runtime；目标是验证非致死伤害不会留下动作或 VFX 脏状态。

## 快照与门禁

- `upstream_snapshot.json` 记录上游七个 authored 文件的 SHA-256；构建器在复制前后
  复核，检测并发写入，避免产生撕裂候选。
- validator 要求恰好 8 个动画、只允许 skeleton hash 与 `hurt` bone performance
  改变，并检查 `idle→hurt=.03s`、`hurt→hurt=0`、`hurt→idle=.10s`、`hurt→die=0`。
- hurt 采样时间为 `0.0, .10, .16, .28, .46, .70, 1.0s`；所有输入必须沿用上游
  已验收 Alpha，禁止把灰盒/后处理图混入快照。

## 命令

```powershell
# 构建（会读取并一致性快照 hybrid_action_set）
& $godot --headless --path .\tools\art `
  --script res://candidates/hybrid_hurt_neutral/build_hybrid_hurt_neutral_candidate.gd -- build-hurt-neutral

# validator（Vivhite 项目；只读静态 + Spine runtime gate）
& $godot --headless --path .\Vivhite `
  --script (Resolve-Path .\tools\art\candidates\hybrid_hurt_neutral\validate_hybrid_hurt_neutral_candidate.gd)
```

该候选没有自己的渲染包装器；需要画面时，把 `Vivhite/tools/candidates/hybrid_hurt_neutral/`
作为候选交给 [`compare/preview`](../../compare/preview/README.md)，或在 final 连续中断
验收中采样。通过这里不等于受伤视觉已在正式游戏通过，最终结论由 `hybrid_v3_final` donor
与真机非致死伤害回归给出。

