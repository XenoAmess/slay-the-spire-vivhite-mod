# hybrid_attack_peak：普攻峰值里程碑

这是 Hybrid V3 的第一个动作候选：neutral 继续使用已验证的加权白绮身体，只有普通
攻击可见窗口切换到一张独立、刚性的 `vivhite_combat_attack_peak` attachment。
魔法弧仍由 `slash_mesh` 消费者负责；候选隔离在 `Vivhite/tools/candidates/`，不能
直接部署。

## 冻结契约

- Spine 4.2.43，八个游戏动画和四个兼容事件保持不变。
- attack attachment 的显示窗口为 `[0.08, 0.20)`，`idle_loop -> attack` mix 为
  `0.10s`；切换前后均要求恰好一个人物 attachment，禁止整身 cross-fade。
- 普通攻击动作事件 `attack_slash_start` 在 `0.08s`；`slash_mesh` 在动作后清理。
- neutral、death、arc/sigil 页来自冻结 donor；新攻击图必须是已验真的原生透明源。

## 运行

```powershell
# 一键构建 + validator + 14 个精确 Vulkan 时刻
& .\tools\art\candidates\hybrid_attack_peak\Invoke-HybridAttackPeakPreview.ps1

# 可选参数：-GodotExe -Sts2Dir -ProjectDir -OutputDir -Width -Height
#            -SceneScale -OriginX/-OriginY -SceneOffsetX/-SceneOffsetY
```

如果需要分步调查：先用 `tools/art` 项目的 `build...gd -- build-combat`，再以
`Vivhite` 项目运行 `validate_hybrid_attack_peak_candidate.gd`。包装器会校验游戏 PCK
和编辑器/游戏 Spine DLL 哈希，使用项目 mutex，并把所有报告限制在新的 `.work/` 子目录。

## 输出与判读

候选 authored 文件为 neutral、death、attack 三张页 + `.spjson/.spatlas/.tres`；
预览报告至少包含 `summary.json`、composite/character-only 接触表和日志。`14/14`
通过说明精确时刻、边界、角色-only 与 VFX 隔离满足自动契约；仍需完整 Hybrid 总装、
正式 PCK 和真机出牌验收。失败现场不得删除或把灰盒输入当成正式美术。

