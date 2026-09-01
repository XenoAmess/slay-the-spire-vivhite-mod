# `Vivhite/tools/candidates` — 角色皮肤候选输出

本目录是 Vivhite Godot/Spine 皮肤候选的工作副本和静态输出集合。它用于离线比较、消费者验证和构建前审计；**不是**运行时资源目录，也不代表其中每个候选都已批准发布。

## 候选集合

| 目录 | 侧重点 | 当前边界 |
| --- | --- | --- |
| `hybrid_action_set/` | 普通/攻击动作组合 | 候选，需按实际动画和姿势证据复核 |
| `hybrid_attack_peak/` | 攻击峰值帧 | 候选，不直接覆盖正式资源 |
| `hybrid_cast_set/` | 施法动作组合 | 候选，VFX 与身体层要分离验收 |
| `hybrid_death_v3/` | V3 死亡页 | 候选，须满足私有 Spine 合同 |
| `hybrid_hurt_neutral/` | 受击/中性组合 | 候选，需实机最大旋转复核 |
| `hybrid_neutral_v3/` | V3 中性页 | 候选，不能把单帧展示图当 atlas |
| `hybrid_v3_final/` | V3 五页整合候选 | 仅为离线候选；正式发布仍以 `assets/.../approved`、PCK 门禁和实机证据为准 |
| `semantic_back_hair/` | 后发语义拆件 | 候选；有独立 region/Alpha 接触记录 |
| `semantic_butterfly/` | 蓝蝶语义拆件 | 候选；需检查层序和邻接附件 |
| `semantic_head_face/` | 头脸语义拆件 | 候选；眼镜/瞳孔不得丢失 |
| `semantic_left_arm/`、`semantic_right_arm/` | 手臂语义拆件 | 候选；方向按解剖侧与消费者契约解释 |
| `semantic_left_leg/`、`semantic_right_leg/` | 腿部语义拆件 | 候选；关节切口和最大旋转须实测 |
| `semantic_split_v3/` | V3 拆件组合 | 候选；不等于正式多网格方案 |
| `semantic_torso_skirt/` | 躯干/裙摆语义拆件 | 候选；肩饰归属需保持唯一 |
| `whole_mesh/` | 整身网格候选 | 候选；当前正式路线是否采用由验收报告决定 |

其中部分语义候选目录有就近 README，记录各自 region、锚点和消费者证据；其余目录由本索引与 [`tools/art/candidates/README.md`](../../../tools/art/candidates/README.md) 的统一候选规则覆盖。不要为了补齐叶目录而复制一份会漂移的通用说明。

## 输入、输出与晋级

1. 先查 [`tools/art/README.md`](../../../tools/art/README.md) 和根 `AGENTS.md`，确认原版 atlas/Spine/场景布局及实际消费者；PNG 可能是 atlas/spritesheet，不可凭肉眼当成整幅插画。
2. 候选可以包含 `.spjson`、`.spatlas`、`.tres`、`.png` 和诊断 sidecar，但必须保留 provenance；候选文件不自动进入 `Vivhite/` 运行时或 Workshop。
3. 透明素材只能经 EvoLink `gpt-image-2` 的原生 `background: "transparent"` 路径产生；禁止传统抠图、色键、代码修 Alpha、污染历史素材回流或整体重绘 packed atlas。
4. 通过逐项 Alpha/SourceOver、邻接姿势、Spine/atlas 合同、PCK 和 Vulkan 真机门禁后，才可复制到明确的 `approved/` 或 `custom/` 源；晋级动作应在报告中记录，而不是仅改目录名。

## 常用只读检查

```powershell
# 查看候选目录与就近说明
Get-ChildItem .\Vivhite\tools\candidates -Directory
rg --files .\Vivhite\tools\candidates -g 'README.md' -g '*.spjson' -g '*.spatlas'

# 运行统一的美术合同测试（从仓库根执行）
py -3 -B -m unittest discover -s .\tools\art\tests -p "test_*.py" -v
```

不要把本目录作为游戏加载路径；正式运行时只消费经过 `Vivhite/tools/Validate-IroncladSkin.ps1`、PCK 门禁和真实游戏验收的私有资源。
