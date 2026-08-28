# split_mesh 战斗候选

这是“拆件 + 层级骨链”的**离线对照候选**，不是可发布素材，也不会被复制到
`Vivhite/Vivhite/skins/ironclad/`。

## 当前能验证什么

- 15 个可见部件分别挂在 33 根层级骨骼上；手臂是
  `upper_arm -> forearm -> hand`，腿是 `thigh -> knee -> ankle -> foot`。
- 保留战斗消费方要求的 8 个动画、`slash_mesh` / `eye_attach_slot`，以及
  `attack_slash_start`、`heavy_slash_start`、`cast_eyes_start`、`clear_vfx`。
- 普通攻击、重击、受伤在场景 `.28` 下的根位移分别是 29.12、45.92、
  33.6 像素；肢体链会把末端手掌位移继续放大。
- `die` 在 0 秒清理 VFX，然后按髋、膝、踝、躯干、头和双臂错峰坍塌。
  根骨最大只旋转 7 度，不再把整张站姿卡片直接旋倒。
- 每个普通部件都有独立的 `death_*` slot 和 `vivhite_death_*` attachment
  名称，最终死亡专用图可以原位替换。

## 为什么不能发布

当前 1680×2512 母图是单帧完整人物，而不是 spritesheet 或已拆分部件图。
它虽然是 EvoLink 原生 RGBA，四角透明，但整个人物外侧有半透明光晕，且所有
肩、肘、腕、髋、膝、踝都已压平为一张图。候选只为比较运动学，使用同一张
未改 Alpha 的 atlas region，通过 15 个 mesh 的 UV 子域和关节重叠来显示。
一旦大幅旋转，就会暴露接缝、重复光晕和缺少遮挡后像素的问题。

`candidate.json` 完整列出每个临时 UV 裁片、已核对的消费契约、风险，以及最终
必须通过 EvoLink `gpt-image-2` 原生透明模式独立重绘的输入集合。只有这些独立
部件与死亡套件到位并重新绑定后，才允许进入运行时 atlas。

## 重新生成

```powershell
& '<Godot 4.5.1 mono exe>' --headless --path tools/art `
  --script res://build_vivhite_combat_split_mesh_candidate.gd -- `
  build-split-mesh-candidate
```

脚本拒绝把输出目录指向 `Vivhite/Vivhite/skins/ironclad`，不会部署、重启或操作
游戏，也不会发起任何 EvoLink 调用。
