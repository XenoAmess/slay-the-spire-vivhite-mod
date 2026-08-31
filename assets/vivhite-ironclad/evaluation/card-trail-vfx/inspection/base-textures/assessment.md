# 原版卡牌轨迹纹理审计结论

## 结论

本目录保存的是 5 张《杀戮尖塔 2》原版共享卡牌轨迹纹理的**历史技术诊断**。它们均通过了
当时的技术 Alpha 检查，但随后被白绮专属卡牌轨迹的视觉契约否决。它们不是白绮运行时
候选，不得加入白绮资源清单或 PCK 发布合同；未来若用于原版对照，也必须保持“历史诊断”标记，
不能冒充已接受的白绮视觉参考。

这里的“技术通过”只表示原版 PCK 中的资源可以解析为 `RGBA8`、四角 Alpha 全为 0，并已在
纯黑、纯白和游戏靛蓝底上生成真实 SourceOver 诊断图。`audit_base_textures.gd` 的
`accepted` 字段只以四角透明为自动判据，不代表白绮身份、玩法语义或运行时视觉采用。

## 技术 Alpha 证据

事实源为同目录的 `base-texture-report.json` 与 15 张 SourceOver 预览：

| ID | 原版资源路径 | 尺寸 | 四角 Alpha | 边缘非零 / 最大 Alpha | 技术结果 |
| --- | --- | ---: | --- | ---: | --- |
| `outer_ribbon` | `res://images/packed/vfx/trail.png` | `32×32` | `0/0/0/0` | `56 / 238` | 通过 |
| `inner_ribbon` | `res://images/packed/vfx/trail2.png` | `64×64` | `0/0/0/0` | `116 / 255` | 通过 |
| `big_spark` | `res://images/vfx/brush_particle_2.png` | `16×32` | `0/0/0/0` | `0 / 0` | 通过 |
| `card_silhouette` | `res://images/packed/vfx/small_card_silhouette.png` | `64×64` | `0/0/0/0` | `0 / 0` | 通过 |
| `little_spark` | `res://images/vfx/vfx_ghostly_power_up/sparkle.png` | `512×512` | `0/0/0/0` | `0 / 0` | 通过 |

`outer_ribbon` 与 `inner_ribbon` 的非零 Alpha 到达左右边缘，是其原版连续线带消费方式的一部分；
这项事实已经记录，不能把“四角通过”误写成“四边全透明”。其余三张四边均为零。黑、白和
游戏靛蓝三底预览用于证明实际混合结果，而不是修改任何 Alpha。

## 白绮视觉契约否决

技术可渲染不等于视觉可采用。这 5 张纹理属于原版通用视觉语言：两张是无身份的水平白色
线带，`big_spark` 是通用笔刷火花，`card_silhouette` 是空白卡牌轮廓，`little_spark` 是带
扩散辉光的通用多角星。单独或组合使用都不能稳定表达白绮的数学魔法、蓝紫金配色和闭合轨道
构造，也无法在重复、旋转并缩至 `16–48 px` 后形成白绮专属辨识度。因此它们在技术 Alpha
通过后仍被创意与消费者契约否决。

正式白绮契约由 `0194-card-trail-mathematical-star-attempt-02` 收口：冷白核心、淡青、
电紫、少量淡金，以及明确的数学星体与闭合轨道。当前
`Vivhite/Vivhite/scenes/vfx/card_trail_vivhite.tscn` 只引用
`res://Vivhite/images/vfx/vivhite_card_trail_mathematical_star_0194.png`；两组粒子和两个
Sprite 均消费该纹理，两条轨迹则由无纹理的 `Line2D` 曲线与渐变生成。当前场景没有引用上述
5 个原版路径。

## 保留规则

- 保留 `base-texture-report.json`、三底 SourceOver 预览和审计脚本，作为“先验原版资源可否
  技术复用”的诊断证据。
- 不把这些预览或原版路径登记为白绮运行时素材，也不把技术 `accepted` 解释为视觉候选。
- 不删除或覆盖这批证据；若未来重新审计原版消费者，应新增记录，而不是改写本次结论。
- 白绮运行时状态只以正式 `0194` 纹理、Vivhite-only profile 接线、92 项资源合同和后续
  PCK／实机验证为准。
