# hybrid_action_set：普攻 + 重击动作集

本候选在 `hybrid_attack_peak` 的 neutral/attack/death 基础上，向同一个
`vivhite_action_pose` slot 增加刚性 `vivhite_combat_attack_heavy_peak`。它验证动作
集合可以共享一个原子人物切换槽，而不会把普攻、重击或 VFX 变成两层叠影。

## 关键事实

- 重击可见窗口 `[0.12, 0.32)`，`heavy_slash_start` 在 `0.12s`，idle mix 约 `.02s`；
  heavy arc 与普通 arc 使用同一已验收消费者锚点。
- authored 页为 neutral、attack、heavy、death 四页；其余 skeleton/slot/event
  结构必须与上游 donor 一致，validator 会比较 baseline JSON 并拒绝额外 cross-fade。
- 这是隔离候选，不是正式 runtime；只有 `hybrid_v3_final` 总装并通过完整发布门禁后，
  才能由发布器镜像到 skins。

## 一键精确验收

```powershell
& .\tools\art\candidates\hybrid_action_set\Invoke-HybridAttackHeavyPreview.ps1
```

包装器默认使用 `Vivhite/local.props`，支持 `-GodotExe -Sts2Dir -ProjectDir -OutputDir`
以及画布/场景参数。它先读取候选 `.tres`，再在隐藏 off-screen Vulkan 中采样 14 个
heavy transition 时刻；输出目录必须在 `.work/` 且为空。详细分步命令：

```powershell
& $godot --headless --path .\tools\art `
  --script res://candidates/hybrid_action_set/build_hybrid_action_set_candidate.gd -- build-combat
& $godot --headless --path .\Vivhite `
  --script (Resolve-Path .\tools\art\candidates\hybrid_action_set\validate_hybrid_action_set_candidate.gd)
```

`14/14` 只证明重击窗口和隔离契约；不能替代 final 的 84 帧、连续中断、merchant、
VFX bridge、PCK 和真机验收。保留 `summary.json`/日志，不要手改 JSON 或复用旧 `.import`。

