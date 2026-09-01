# hybrid_cast_set：施法动作集

这是 Hybrid V3 的 cast milestone：继承 `hybrid_action_set` 的 neutral、普攻、重击、
死亡结构，再增加 `vivhite_combat_cast_peak` 刚性人物 attachment。施法同时验证
magic sigil、`eye_attach_slot` 与游戏 `NIroncladVfx` 的事件生命周期。

## 冻结契约

- cast 人物窗口 `[0.25, 0.60)`，`cast_eyes_start` 在 `0.25s`；施法环/人物切换是
  原子 null/show/null 序列，不允许整身 cross-fade。
- EyeFire 清理事件 `clear_vfx` 在 `1.222000026s`；渲染器会分别生成 composite、
  character-only、eye-only 与 eye-alignment 接触表，避免把外部 EyeFire 误当身体。
- authored 页为 neutral、attack、heavy、cast、death 五页；输入 Alpha 必须来自已
  验证的 EvoLink 原生透明 PNG，不能由灰盒或程序抠图替代。

## 一键验收

```powershell
& .\tools\art\candidates\hybrid_cast_set\Invoke-HybridCastPreview.ps1
```

脚本会从 `Vivhite/local.props` 解析路径、校验 PCK/Spine DLL、取得 mutex，在隐藏
Vulkan 中运行静态/runtime gate 和 14 个精确 cast 时刻。支持 `-GodotExe -Sts2Dir
-ProjectDir -OutputDir -Width -Height -SceneScale -OriginX/-OriginY -SceneOffsetX/-SceneOffsetY`。

分步时构建器挂 `--path tools/art`，validator 挂 `--path Vivhite`；候选资源位于
`Vivhite/tools/candidates/hybrid_cast_set/`，报告只写 `.work/`。通过后仍必须进入
`hybrid_v3_final` 总装，跑真实 VFX bridge、PCK 和真机 `RAGE`/施法回归。

