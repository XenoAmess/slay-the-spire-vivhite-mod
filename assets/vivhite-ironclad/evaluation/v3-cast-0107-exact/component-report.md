# V3 `cast_peak` 0107 精确渲染验收

## 结论

`0107-combat-cast-peak-attempt-01` 已作为 V3 `cast_peak` 候选通过离线验收。它是单幅、单帧、完整人物 RGBA，不是 atlas 或 spritesheet；人物空手，独立魔法阵由既有 `vivhite_magic_sigil` 附件承担，人物层未烘入独立武器或额外魔法光效。

本组件只消费了 `1/8` 次付费尝试。第一次结果达到人物身份、姿势、透明度和固定画布门禁后即停止，未生成 `0108`，仍保留 7 次未消费额度。

本结论当前仍是**候选通过**：尚未写入正式 runtime、未部署 Mod、未启动游戏，也未操作直播。

## 消费契约

| 项目 | 最终值 |
| --- | --- |
| Atlas 页 | `vivhite_combat_cast.png`，`2048×2304` |
| Region | `vivhite_combat_cast_peak` |
| Region bounds | `(16,16,1536,2272)` |
| World size | `868×1302` |
| 人物 slot / bone | `vivhite_action_pose` / `vivhite_action_pose_root` |
| 人物窗口 | `[0.25,0.60)`，pre-exit `0.5999` |
| 魔法阵窗口 | `[0.10,1.222000026)` |
| 事件 | `cast_eyes_start=0.25`，`clear_vfx=1.222000026` |
| 混合 | `idle_loop → cast = 0.05s` |
| `cast` t=0 | `slash_mesh=null` |

人物切换是刚性 region 的原子切换，不做两张完整人物的 RGBA 交叉淡化。`.25` 前与 `.60` 后只显示中立 `vivhite_body`，`[.25,.60)` 内只显示 `vivhite_combat_cast_peak`。

## 初始 `(40,40)` 锚点为何失败

0107 眼睛中心按固定画布公式映射后，最初得到相对中立眼骨的 `(40,40)` 偏移。静态坐标本身合理，但真实消费者不是一个点标记，而是原版 EyeFire 的 TextureRect、生产 shader、材质参数和纹理组合。

首次隐藏 Vulkan 实测在 `t=.25` 得到：

- EyeFire 可见 bbox：`(295,257,7,22)`；
- 可见底边：`y=278`；
- 可见质心约：`(297,270.46)`；
- 白绮实际眼部接触点约：`(342,371)`。

也就是说，火焰可见像素约向左偏 `45px`，并在眼部上方留下 `93px` 的明显空隙。这个失败只推翻了**初始运行时锚点**，没有推翻 0107 原图；禁止据此重新消费付费生成额度。

## 最终双锚点

真实 EyeFire Vulkan 视觉校正得到两段锚点：

- 施法人物 `[.25,.60)`：`(194,-292)`，在 `.25` 与 `.5999` 保持；
- 中立人物 `[.60,1.222000026)`：`(72,-282)`，在 `.60` 与 `1.2219` 保持；
- `clear_vfx=1.222000026` 时归零。

第二段是必须的：人物在 `.60` 已切回中立图，但眼火事件仍持续到 `1.222000026`；若直接回到未校正的零偏移，眼火会再次悬浮到中立人物头顶。

最终关键帧证据：

| 时间 | 人物 | EyeFire bbox | 可见底边 |
| ---: | --- | --- | ---: |
| `.25` | `vivhite_combat_cast_peak` | `(337,352,9,20)` | `371` |
| `.5999` | `vivhite_combat_cast_peak` | `(340,343,7,26)` | `368` |
| `.60` | `vivhite_combat_body` | `(306,347,6,19)` | `365` |
| `1.2219` | `vivhite_combat_body` | `(303,353,8,22)` | `374` |
| `1.222` | `vivhite_combat_body` | 已清除 | — |

`cast-exact-eye-alignment.png` 放大显示了所有七个眼火活跃采样；两种人物姿势下火焰都与眼部连续，不再悬空。

## 静态与 Spine 门禁

独立只读校验通过：

- 8 个 authored 文件、8 个动画；
- Spine `4.2.43`；
- 34 个真实 Spine runtime 样本；
- 38 个可见性样本；
- attack、heavy、death 及中立页继续与已冻结上游一致；
- `relaxed_loop` 两端都恢复唯一中立人物，并清空 action、death、slash 与 sigil。

## 隐藏 Vulkan 验收

使用 Windows display、Vulkan、游戏匹配 Spine GDExtension 与生产 EyeFire 资源，在 `1280×900` 画布、场景缩放 `.28` 下采样：

`0, .0999, .10, .2499, .25, .2667, .48, .5999, .60, .6001, 1.2219, 1.222, 1.2221, 1.5666667`。

结果：

- 14/14 帧成功，每帧恰好一个人物；
- composite 与 character-only 均非空、无画布边缘接触；
- `.2499→.25` 与 `.5999→.60` 的人物附件原子切换通过；
- 魔法阵在 `.10` 出现、`1.222` 清除；
- EyeFire 有 7 个活跃采样，双姿势眼位通过人工放大接触表检查；
- character-only 真正清除 `slash_mesh`、`eye_attach_slot`、`vivhite_magic_sigil` 以及外部 EyeFire CanvasItem；
- 14 个 TrackEntry 均观察到 `0.0500000007450581s`，满足 `.05s` 混合契约；
- 报告 `errors=[]`。

## 固化证据

- `cast-exact-composite.png`：人物、魔法阵和生产 EyeFire 的最终逐帧接触表；
- `cast-exact-character-only.png`：同一时刻清除全部 VFX 后的人物唯一性证据；
- `cast-exact-eye-alignment.png`：七个眼火活跃样本的脸部放大表；
- `summary.json`：完整逐帧 bbox、哈希、附件、隔离和边界结果；
- `metrics.json`：消费契约、锚点复盘、关键指标及证据 SHA-256。

该目录只固化离线候选证据，不表示正式 runtime 或游戏内集成已经完成。
