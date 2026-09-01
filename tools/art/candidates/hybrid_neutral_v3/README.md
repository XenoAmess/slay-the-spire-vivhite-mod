# hybrid_neutral_v3：neutral 循环边界候选

`hybrid_neutral_v3` 从 action-set 做字节快照，不改 neutral 图页、网格或权重，只为
`idle_loop`、`low_health_loop`、`relaxed_loop` 增加明确的边界 attachment reset。
这样商店随机 seek、战斗被中断后重新进入循环时，人物与 slash/sigil/eye/VFX 不会残留。

## 契约

- 保留上游 35 根骨骼、默认 skin 和完整五页基础；源 body 必须是冻结 `0018` 的
  native-transparent master（脚本验 SHA-256）。
- 三个 loop 的时长为 `2.0s`、`1.4666667s`、`12.000001s`；六个相关 slot 在两端
  都写入 reset，禁止整个人物 cross-fade。
- validator 会通过真实 Spine runtime 在每个循环的 0/中点/终点制造 dirty slot，
  检查恢复后的 attachment；渲染器再做隐藏 Vulkan 的 exact 和游戏绿色接触表。

## 一键命令

```powershell
& .\tools\art\candidates\hybrid_neutral_v3\Invoke-HybridNeutralV3Preview.ps1
```

包装器依次构建、`--import`、validator、Vulkan renderer；默认报告在新建的
`.work/combat-rig-compare-preview/hybrid-neutral-v3-exact-<timestamp>/`，支持
`-GodotExe -Sts2Dir -ProjectDir -OutputDir -Width -Height -SceneScale -OriginX/-OriginY
-SceneOffsetX/-SceneOffsetY`。分步构建器命令是 `build-neutral-v3`，validator 不需要
额外命令参数。

此候选是 final 的 neutral donor，不是可独立部署的皮肤；改动后必须重新运行 action/cast/
death 上游和 final 总装门禁。

