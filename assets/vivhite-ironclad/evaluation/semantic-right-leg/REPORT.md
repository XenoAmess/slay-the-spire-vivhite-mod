# 屏幕右侧／近侧腿语义组离线审计

> 状态：研究拓扑已收口，美术未齐，不可发布、不可接入正式 runtime。
> 本轮没有付费生成，没有改游戏、直播、正式皮肤或共享文档。

## 素材分类与消费者

这里的五张 PNG 是诊断接触表，不是角色单帧、spritesheet 或 atlas page，更不能作为运行时
素材。它们只把原始 EvoLink RGBA 以真实 SourceOver 合成到黑、白和游戏蓝灰底，并展示
setup、`+82°` 膝极值与 `-18°` 踝极值；生成过程中没有改源像素或 Alpha。

消费契约同时核对了实际注册代码、战斗场景和 split Spine JSON：

- `IroncladReplacementAssets.cs` 仍把战士指向私有 combat skeleton；
- `combat.tscn` 的 `SpineSprite` scale 仍为 `.28`；
- 近侧腿正常 slot index 固定为 `7 / 9 / 11`，即 thigh → lower → foot，八动画都没有
  drawOrder 时间线；
- 历史 builder 的膝、踝点为 `(880,1580)` / `(1190,2070)`，但其小腿轴 `57.681201°`
  与实际 `0018≈68.2°`、已选新 rig 方向 `0022≈74.2°`、`0100 PCA≈61.481798°` 冲突。
  因此旧硬编码骨点只能作历史诊断，不能直接升格为生产真值。

## 复验结果

使用 Godot `4.5.1.stable.mono`、Windows display + Vulkan 在屏幕外重建，随后用独立
validator 复核。12 个不可变源、5 张接触表、7/9/11 层序和零 drawOrder 均通过；新输出与
隔离候选逐字节一致。黑、白、游戏蓝灰三底未见矩形光幕或边缘色块，但清楚复现了几何问题：

- `0083` 大腿与 `0100` 小腿目前都只能作研究参考，不能写成生产素材已通过；
- 固定 7→9 层序使 `0100` 的闭合上端压在 `0083` 前方，setup 已有膝横缝，`+82°`
  屈膝时更明显；
- `0064–0071` 八张靴全部是鞋尖朝屏幕左、鞋跟朝屏幕右，和已选的屏幕右鞋尖目标相反；
- 单独 boot 还会增加踝缝，并要求在 `-18°` 踝旋转时拥有现有图并未证明的隐藏像素。

所以旧三件制 `right_thigh + right_lower + right_boot` 必须 fail-closed。

## 当前推荐

近侧腿采用两件制：

1. `right_thigh`；
2. `right_lower_leg_and_boot_union`。

保留髋和膝自由度，踝固定在连续的“小腿 + 靴”美术内。不得把 `0100 + 0064` 程序合成后
冒充联合生产图；接触表里的组合只是用来说明结构。若该路线继续，先按最终 neutral/new-rig
重新冻结髋、膝、踝与屏幕方向，再生成一张原生透明、鞋尖朝屏幕右的联合附件。之后必须重跑
setup、`+82°` 膝极值的真实邻接 SourceOver，以及统一骨架下的 Windows Vulkan/Spine 动态
门禁。回退仍是 Hybrid 完整人物主线。

## 精确哈希

| 文件 | SHA-256 |
| --- | --- |
| `candidate.json` | `93c167d15b5bec309c41914abdf2487c3a31d608be0a9205339c19475eed1782` |
| `right-leg-contact-black.png` | `4259971ba8f132ff58e7a899e4ea9b3c8f02c10b4d57eda03f2c57320b4ef188` |
| `right-leg-contact-white.png` | `282e49a8043185c020ea6ba81efd49562cdbe43fb7987df3f44f51f608124578` |
| `right-leg-contact-game.png` | `d4ed87ec039ac41097d13025193cf55e7ef4fc1b1786bfa9f555129a0d020fe1` |
| `right-boot-0064-0071-contact-game.png` | `f94b5121db3aa51d4874ce6de9d310e6dfd46b49880a0e3b22d337e14216f154` |
| `right-leg-axis-conflict.png` | `bb884198d3dcb531ea38ac923bf7b5eae3769916a3761d32bdd5d9a12ab4fa6a` |
| `build_semantic_right_leg_candidate.gd` | `78a2bb6a693ec899b916a47a88f37506c1208428404c1b9ceb8f61c5936b35da` |
| `validate_semantic_right_leg_candidate.gd` | `51f7e35d3d1160cac39bebc70ac07f8e456524fa7e759835d92e0b47683e74df` |

12 张源图的精确哈希、轴线数值和完整门禁结果见同目录 `summary.json`。
