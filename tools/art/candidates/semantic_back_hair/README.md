# 0031 后发语义组：离线动态候选

本目录只研究“后发”这一项，不修改正式 Ironclad 运行时，也不部署、启动游戏或调用付费生图。
构建产物位于 `Vivhite/tools/candidates/semantic_back_hair/`，可作为 Windows Vulkan 对照输入。

## 已核实的消费事实

- `0031-split-back-hair-attachment-attempt-01/output.png` 是一张 `1024×1024`、单一完整后发帽体的
  RGBA 单帧，不是 spritesheet、atlas 或多区域拼图。推广文件
  `custom/combat/parts/normal/vivhite-back-hair-v1.png` 与归档图逐字节相同，SHA-256 为
  `9fd66b599eb4128ba9c3b4c2bd815aadb0613e064aca2f697307997048c01782`。
- 它的四边最大 Alpha 为 0；`A>=1 / 16 / 128` bbox 分别为
  `[113,3,827,965] / [127,50,761,798] / [127,51,761,796]`。`A>=1` 的远端稀疏像素会浪费
  任意非零 Alpha 自动裁切，但 `A>=16` 相对实体核只扩 0–1 px；黑、白、游戏蓝灰 SourceOver
  没有可见矩形光幕。因此不能用程序清 Alpha，也不需要为 Alpha 重生成。
- 原 split 候选已有 `vivhite_hair_back / left / right` 三根骨，但没有独立后发 slot 或 attachment；
  `idle_loop` / `relaxed_loop` 只给 left/right 小角度时间线，故旧骨名不能冒充“后发已经接入”。
- 正式商店场景通过单独的 `merchant_skeleton_data.tres` 复用 combat `.spjson + .spatlas`，
  SpineSprite 固定 `.28`，`NMerchantCharacter._Ready()` 播放循环 `relaxed_loop`，随后把 track time
  随机设为动画长度乘随机数。因此 `relaxed_loop` 的任意相位都必须有正确 setup，且 0 / 12.000001
  两端显式重申后发、头脸、前发和蝶饰的可见 attachment。

## 本候选怎么接

- 0031 保留完整源画布，逐字节复制成独立 atlas page；没有 crop、阈值、蒙版或 Alpha 修补。
- 后发使用 `7×7 = 49` 顶点的 weighted mesh。冠顶顶点 100% 绑定 `vivhite_hair_back`；下半部逐步
  增加左/中/右三股影响，末梢总权重上限 72%，避免整顶假发随末端一起甩动。
- 邻接层只为验证真实组合：0031 后发在 torso/neck 后；本候选当时按 0044 头脸、0033 前刘海、
  0030 蝶饰依次在前渲染。后续蓝蝶专项 A/B 已以更强证据纠正总装顺序为
  `头脸 → 蓝蝶 → 前刘海`；这里的接触表只能证明后发自身，不得把旧邻接顺序复制到生产。
  三张头部图保持同一 360×360 authored-world 像素密度；0033 只做 attachment 上移
  118 源像素，以对齐它与 0031 的实体冠顶，没有裁切或改图。
- 极限灰盒使用真实游戏动画：重击给末梢约 `+20°`，受伤约 `-19°`，循环动作只做 2–4° 惯性。
  `die` 在 t=0 隐藏该正常头部组，继续使用旧候选的独立死亡预览层；本任务不越界修改死亡线。

## Vulkan 结果与当前结论

已用游戏实际 Spine GDExtension、Windows Vulkan、场景 `.28`、制作比例 `.70` 对比基础
`split_mesh` 与本候选：每个候选 8 动画 × 21 帧，共渲染 336 帧；本候选 168 帧均非空、
不触边、无契约错误，8 个动画全部变化。`relaxed_loop` 首末哈希相同、11 个独特帧、最大质心
位移约 `4.191 px`，覆盖了商店任意随机相位；重击 `+20°` 与受伤 `-19°` 后发末梢极值在实际
显示尺寸下未见冠顶脱离、双头、颈部穿透或明显三角折线。

setup bbox 从基础候选的 `[220,336,220,357]` 变为 `[220,326,220,367]`：宽度不变，真实头发
让上边界提高 10 px、总高增加 10 px，不是整身缩放漂移。离线报告位于
`.work/combat-rig-compare-preview/semantic-back-hair-v1/summary.json`。

因此 0031 可作为“一张 weighted 后发帽体”继续集成，不能拆称多张独立发束；当前证据不支持
为后发继续付费生成。它仍是研究候选而非正式生产件，因为 0044 头脸、0033 前刘海和 0030 蝶饰
只是邻接验证层，死亡阶段也仍切换旧 preview 头部。下一道门禁是跨组件的完整语义头部 + torso
组合，再由用户在游戏真实画面审美验收。

此前预定的视觉检查项均已覆盖：

1. `relaxed_loop` 随机相位是否始终只有一套头部且冠顶不漂；
2. 重击和受伤极值时，前刘海固定层是否与变形后发形成裂缝、重复发束或露出头皮；
3. 后发是否穿过 torso/neck，蝶饰是否仍在正确前景；
4. 实际 `.28` 尺寸下，49 顶点是否足够平滑，还是出现可见三角折线。

若 Vulkan 暴露无法靠权重、骨点或 attachment 位移修复的结构问题，下一次生成消费规格应是：

```text
id: semantic_back_hair_v2
runtime consumer: one weighted mesh behind torso/neck, under head-face/front-hair/butterfly
screen orientation: three-quarter view facing screen-right
canvas/pivot: same 1024-square family; crown center aligned to current head bone; full hidden scalp/nape pad
target silhouette: only rear crown + nape + 3–5 lower sway locks; no forehead bangs or screen-front side lock
hidden overlap: solid upper face/head overlap and lower neck overlap, both covered in setup and ±20° tail stress
forbidden adjacent parts: face, eyes, glasses, front bangs, butterfly, neck, torso, clothing, weapon, VFX
actual-size gate: `.28` scene, 360 authored-world canvas, no seam against accepted head/front-hair layers
```

只有发生上述结构性失败才值得使用下一次额度；不能因为 `A=1` trim 浪费或普通查看器黑底外观重抽。

## 构建与验证

```powershell
& '<Godot 4.5.1 mono console exe>' --headless --path tools/art `
  --script res://candidates/semantic_back_hair/build_semantic_back_hair_candidate.gd -- `
  build-semantic-back-hair-candidate

& '<Godot 4.5.1 mono console exe>' --headless --path tools/art `
  --script res://candidates/semantic_back_hair/validate_semantic_back_hair_candidate.gd -- `
  validate-semantic-back-hair-candidate
```

Vulkan 对照继续复用 `tools/art/compare/preview/Invoke-CombatRigComparePreview.ps1`，传入基础
`split_mesh` 与本候选的 `.spjson`；输出只能放 `.work/`。
