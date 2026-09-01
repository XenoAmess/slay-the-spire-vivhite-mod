# hybrid_v3_final：五页隔离总装候选

这是当前 Hybrid V3 的隔离总装源。总装器以 `hybrid_cast_set` 为结构基线，只合并四类
已审阅差量：`hybrid_neutral_v3` 的三循环 slot reset、`hybrid_hurt_neutral` 的 hurt
骨骼、`hybrid_death_v3` 的 die bone 子树，以及 cast-restart 时清理外部 EyeFire 的
VFX bridge。它生成五张 combat atlas 页和八动画，但候选目录仍被 PCK 排除；正式
runtime 只能由发布器从已验收源镜像。

## 构建与静态/runtime 门禁

```powershell
# 总装五页（art 项目）
& $godot --headless --path .\tools\art `
  --script res://candidates/hybrid_v3_final/build_hybrid_v3_final_candidate.gd -- assemble-hybrid-v3-final

# 完整 no-deploy Source/Godot/Vulkan/merchant 验收（不导出 PCK）
& .\tools\art\candidates\hybrid_v3_final\Invoke-HybridV3FinalValidation.ps1

# 完整隔离 C# build + PCK 结构门禁（CopyModOnBuild=false）
& .\tools\art\candidates\hybrid_v3_final\Invoke-HybridV3FinalPckValidation.ps1
```

两个 wrapper 都支持路径/画布参数，并从 `Vivhite/local.props` 解析 Godot、游戏目录和
PCK；输出必须在 `.work/`。前者应报告 8 动画 exact 共 84 帧、连续 interruption、
merchant random seek 和 VFX；后者在完整隔离项目中构建并再次验证 PCK，绝不部署到游戏。

## authored 基线与 donor 关系

`Vivhite/tools/candidates/hybrid_v3_final/` 的 authored 基线严格是：

```text
vivhite_combat.png                 # neutral + arc/sigil
vivhite_combat_death.png           # grounded side pose
vivhite_combat_attack.png          # ordinary attack
vivhite_combat_attack_heavy.png    # heavy attack
vivhite_combat_cast.png             # cast
vivhite_combat.spjson
vivhite_combat.spatlas
vivhite_combat_skeleton_data.tres
```

`.import`/`.uid` 是缓存，不计入八个 authored 文件。validator 会逐页校验尺寸、哈希、
Spine 4.2.43、35 bones、六 runtime slots、四 events、动作窗口、原子切换、neutral reset、
hurt/die/VFX 清理；任一 donor 漂移都 fail-closed。

## 精确与连续渲染

`render_hybrid_v3_final_exact.gd` 每次采一个动画（`--animation` 必须是八个受支持名称，
可用 `--times` 做聚焦采样）；`render_hybrid_v3_final_transitions.gd` 保持同一
SpineAnimationState 连续推进，覆盖动作中断、VFX 清理和 recovery；
`render_hybrid_v3_final_merchant.gd` 实例化正式 merchant 场景并验证 `relaxed_loop` 随机相位。
这些脚本保存原始 Vulkan 帧与 JSON，不改源 Alpha。

## 发布边界

本目录通过所有隔离门禁仍不能跳过 [`publish_ironclad_skin.py`](../../publish_ironclad_skin.py)、
正式三件套构建、真机场景验收和 Workshop 物料同步。不要手动复制候选文件、修改报告、
删掉失败现场或把 `tools/candidates` 路径写进正式 runtime。

