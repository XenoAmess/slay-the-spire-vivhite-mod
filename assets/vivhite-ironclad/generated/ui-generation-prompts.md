# 白绮战士换皮：UI ImageGen 生成记录

生成日期：2026-08-27
生成方式：Codex 内置 ImageGen；每个独立创意资产单独调用一次。
最终角色约束：白绮是银发、紫瞳、金框眼镜的华丽冷淡可爱魔法少女；绝无武器、剑、法杖、魔杖、法书、手持法球、白绫、绷带、头盔或重甲。

## 输入参考

- `../references/character-design.png`：官方服装和配饰设定。
- `../references/face-reference.jpg`：脸、淡银蓝短发、紫瞳和金框眼镜。
- `anchor/vivhite-master-front-final.png`：最终人物身份、比例、服装结构、蝴蝶和水晶锚点。

## 公共人物提示

> Preserve this same adult magical-girl character identity. She is elegant, cool, cute and self-possessed. Preserve the exact outfit, proportions, hairstyle, cyan-blue butterfly ornament, magenta ribbons and violet crystal jewelry from the finalized anchor. Absolutely no weapon, no sword, no staff, no wand, no spellbook, no handheld orb, no white silk ribbons, no bandages, no helmet, no heavy armor, no text, no logo, no watermark.

透明资产的生成底统一为：

> A perfectly flat, uniform, saturated technical chroma-key green (#00FF00) filling every background pixel, with no gradient, texture, floor, shadow, glow, halo or vignette.

## 独立调用

### `ui_raw/icon-source.png`

> Isolated source art for an 85x85 fantasy game top-panel icon. Paint a compact near-front three-quarter head-and-high-collar portrait of Vivhite. Preserve violet-pink eyes, thin round gold glasses, short silver-blue bob, black/navy angular gold-trimmed hair ornaments, cyan-blue butterfly on viewer-right, and one hint of the violet throat crystal. Polished hand-painted dark-fantasy card-game UI portrait, crisp oval silhouette, chunky readable shapes and strong value separation at tiny size. Head and upper collar only; all hair and butterfly inside the frame. No particles or decorative frame.

### `ui_raw/select-source.png`

> Isolated source art for a 132x195 fantasy game character-select portrait. Paint a vertical head-and-shoulders portrait from above the butterfly through the upper chest. Preserve violet-pink eyes, round gold glasses, silver-blue bob, black/navy gold-edged hair ornaments, cyan butterfly, magenta ribbons, high navy collar, asymmetric shoulders and centered violet crystal pendant. Near-front three-quarter view, calm cool-cute expression, gaze toward viewer; head in upper two-thirds, shoulders and pendant in lower third. No hands, particles or decorative border.

### `ui_raw/map-marker-source.png`

> Tiny 49x64 fantasy game map marker. Create one simple bold downward-pointing magical crest derived only from Vivhite: symmetric cyan-to-cobalt butterfly upper wings surrounding a single faceted violet crystal, with a compact magenta-violet V-shaped lower point and thick near-black/indigo outer contour. It must read as butterfly plus crystal at extremely small size, not as a weapon or shield. Emblem only, vector-like silhouette, chunky facets, no face, body, letters, particles or circle frame.

### 四张手势的公共提示

> Exactly one disembodied pale right hand and long slender forearm belonging to Vivhite, rising vertically from below. The arm wears the same white segmented magical gauntlet/bracer from the final anchor: pearl-white angular plates, dark navy diamond-shaped cuff and inset, thin restrained gold edging, one small faceted violet crystal accent. Pale bare fingers begin above the wrist. Perfect green technical background. Polished hand-painted fantasy card-game UI art, crisp anatomical silhouette. Extremely tall centered arm; fingertips near top; forearm exits at bottom. Exactly five fingers total and one arm only. No body, face, second arm, particles, weapon, staff, wand, book, handheld orb, white silk, bandage, orange armor, green skin or bulky robe.

### `ui_raw/point-source.png`

> POINT: raise exactly the index finger straight upward. Curl middle, ring and little fingers naturally into the palm; thumb rests across them. Unmistakable one-finger pointing silhouette.

### `ui_raw/rock-source.png`

> ROCK: compact fully closed fist with all four fingers curled and thumb resting naturally across them. Knuckles mostly face viewer. No finger raised; fist is lower in the tall frame than other gestures.

### `ui_raw/paper-source.png`

> PAPER: open palm facing viewer with exactly five fingers naturally spread; four fingers upward and thumb toward viewer-left. Clear gaps, no bent or duplicated fingers.

### `ui_raw/scissors-source.png`

> SCISSORS: raise exactly index and middle fingers in a clean V. Curl ring and little fingers into palm and hold them with thumb. Exactly two raised fingers and clear negative space inside V.

## 后处理

- `tools/art/remove_chroma.gd`：纯绿技术底转换成 straight-alpha RGBA。
- `tools/art/process_vivhite_ui.gd`：裁切、缩放、落位、手臂底部渐隐、绿边清理。
- `icon_outline.png` 从最终 `icon.png` alpha 膨胀派生；没有额外生成。
- `select_locked.png` 从最终选人图与同一人物 mask 灰阶压黑派生；没有额外生成。
