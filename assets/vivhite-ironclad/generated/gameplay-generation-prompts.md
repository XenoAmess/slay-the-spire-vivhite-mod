# 白绮战士换皮：Gameplay ImageGen 生成记录

生成日期：2026-08-27
生成方式：Codex 内置 ImageGen；最终 atlas 不是直接采用模型坐标，而是通过
`build_vivhite_gameplay_regions.gd` 按 region 语义裁切、保留原几何/Alpha，随后
由 `atlas_region_tool.gd` 精确回包。

## 统一身份约束

- 银白/淡蓝短 bob、紫粉瞳、细圆金框眼镜；
- 黑/藏青金边角翼发饰、蓝青蝴蝶、紫水晶；
- 白/淡紫/藏青魔法少女礼裙、细金边、白色分节护臂、白长袜、藏青短靴；
- 冷淡、可爱、华丽，偏手绘暗色幻想卡牌游戏材质；
- 空手施法；禁止剑、法杖、魔杖、法书、盾、手持法球、刀鞘及一切武器；
- 禁止白绫和长条飘带；法术只使用紫蓝晶光、魔法弧、星屑与蓝蝶。

## 输入参考

- `../references/character-design.png`：服装、蝴蝶、配色和全身比例；
- `../references/face-reference.jpg`：脸、银蓝发质、紫瞳、金镜与冷淡神态；
- `anchor/vivhite-master-front-final.png`：批准后的统一人物锚点；
- `../../ironclad-v0.111.0/**`：只作为 atlas 岛屿布局/动作几何模板。

## 身份锚点

输出：`anchor/vivhite-master-front-chroma.png`，再由
`tools/art/remove_chroma.gd` 生成 `anchor/vivhite-master-front-final.png`。

核心提示：

> Create Bai Qi as an ornate magical girl and unarmed spellcaster. Exact front
> full-body A-pose, short silver-blue bob, violet eyes, thin round gold glasses,
> cyan butterfly, navy/gold hair ornaments, white-lavender/navy dress, violet
> crystal and empty hands. Later combat language is hand gestures, violet-blue
> magic circles, crystalline light, stars and butterfly particles. Never add a
> sword, staff, wand, book, shield, held orb, white silk, long fabric, text or
> watermark. Flat technical chroma green background.

内置生成器第一次透明请求返回了不透明棋盘格，因此保留绿底版本并用 Godot
确定性抠图；最终图是 straight-alpha RGBA，角落 alpha 为 0。

## 战斗/商店母贴图

### `gameplay/merchant-page1-registration-ai.png`

参考：原版 merchant page 1、人物锚点、第一次 page 1 风格稿。

> Exact-layout game texture-atlas revision. Keep every source island as an
> absolute registration template and repaint it in Bai Qi's silver-blue,
> white-lavender, navy, gold and violet-crystal materials. Source slash/VFX
> become violet-cyan butterfly and crystalline spell arcs. Bai Qi is an
> unarmed mage: sword/blade/handle footprints may only be detached translucent
> magic and must never read as a held object. Pure black technical background;
> no checkerboard, labels, ribbons or weapons.

### `gameplay/merchant-page2-ai.png`

参考：原版 attack atlas、人物锚点、设定图、page 1 风格稿。

> Repaint all attack-pose pieces as matching Bai Qi parts: pale empty hands,
> white segmented bracers, short white sleeves, navy/lavender bodice, white
> pleated skirt panels, white thigh-highs and navy boots. Preserve attack island
> semantics and use the same painterly palette. Absolutely no sword, staff,
> wand, book, shield, held orb, white silk or long fabric. Black technical
> background.

### `gameplay/merchant-page3-ai.png`

参考：原版 death atlas、人物锚点、设定图、page 1 风格稿。

> Repaint the hurt/death components into the same unarmed magical girl, with a
> strained/closed-eye silver-haired face, gold glasses, cool subdued lighting,
> white/navy costume pieces, violet crystal, pale hands and navy boots. Empty
> hands only; no weapon or weapon handle. Black technical background.

`merchant-page1-ai.png` 是第一次构图探索稿，也保留在仓库中作为材质/效果参考；
生产脚本采用 registration 版本。page 4 的 placeholder 不单独生图，由确定性法术
效果配方生成。

## 篝火

输出：`gameplay/rest-site-ai.png`。

> Repaint the rest-site component language into a seated Bai Qi: silver-blue
> bob, purple eyes, round gold glasses, cyan butterfly, white/navy magical dress,
> segmented bracers, white stockings and navy boots under cool violet campfire
> rim light. Keep shadow/highlight concepts isolated. She is unarmed with empty
> hands; no sword, staff, wand, book, shield, held orb, white silk or long
> fabric. Black technical background.

篝火 sheet 的头部构图不够稳定，生产脚本对头/发改用批准后的透明人物锚点；其余
身体、手臂与腿仍取自本次篝火生成图，阴影与法术光来自统一效果源。

## 选人动态背景

输出：`gameplay/character-select-ai.png`。

> Repaint the character-select atlas into a cold indigo-violet arcane tableau.
> Large background regions contain faceted violet light and cyan butterfly
> motes. Character regions show Bai Qi with silver-blue bob, violet eyes, gold
> glasses, cyan butterfly, white/navy dress, violet crystal and empty pale
> hands. Transform fire/eye-shine into crystalline spell glow. Any original
> sword-shaped area must become detached light or empty space and never a held
> object. No weapon, staff, wand, book, shield, held orb, white silk, text or
> watermark. Pure black outside atlas islands.

生产脚本把右下独立空手护臂裁片写入复合 `top arm` region，不沿用原剑 Alpha。
最终 `characterselect_ironclad.png` 已人工查看：右下只有裸手与白色护臂，没有剑
或其他持有物。

## 确定性迁移与审计

```powershell
$godot = 'C:\path\to\Godot_v4.5.1-stable_mono_win64_console.exe'

& $godot --headless --path .\tools\art `
  --script res://build_vivhite_gameplay_regions.gd -- build

foreach ($domain in 'combat','merchant','rest_site','character_select') {
  & $godot --headless --path .\tools\art `
    --script res://atlas_region_tool.gd -- pack `
    --workspace "assets/vivhite-ironclad/custom/$domain" `
    --weapon-policy clear
}

& $godot --headless --path .\tools\art `
  --script res://build_vivhite_gameplay_regions.gd -- audit
```

当前报告：

- `../custom/gameplay-region-build-report.json`：输入 SHA-256、190 个 region 的
  配方、输出 hash 与 Alpha 是否保留；
- `../custom/gameplay-static-audit.json`：`passed=true`，190/190 region 和 10/10
  atlas 页均不同于模板；combat/merchant 的 blade/handle 母片及 packed rect
  alpha 全为 0；select `top arm` 来源固定为 `select-empty-hand-arm`。
