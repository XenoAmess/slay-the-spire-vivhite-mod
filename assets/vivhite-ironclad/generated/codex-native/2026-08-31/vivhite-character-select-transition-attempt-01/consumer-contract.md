# Vivhite character-select transition consumer contract

Status before generation: frozen input contract for `attempt 1/8`.

## Asset classification

- Semantic asset: White Qi / Vivhite character-specific run-start transition.
- Source type: one complete, full-frame, opaque raster image.
- Runtime role: scalar wipe mask; it is not a character-select portrait, animation frame,
  spritesheet, atlas page, atlas region, Spine attachment, VFX overlay, or directly visible
  color scene.
- Final runtime texture contract: `2560x1200`, RGB/RGBA accepted by Godot but every pixel must
  be fully opaque; no transparent or translucent pixels.
- Generation route: Codex built-in `image_gen` only. EvoLink is forbidden for this opaque asset.

## Verified runtime consumer

- Game assembly: `G:/SteamLibrary/steamapps/common/Slay the Spire 2/data_sts2_windows_x86_64/sts2.dll`
  (`0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9`).
- Game PCK: `G:/SteamLibrary/steamapps/common/Slay the Spire 2/SlayTheSpire2.pck`
  (`c60f672ee7804e6aefa1e19a582fa1c80b126a7b0eef4d084d3abf110df2eab7`).
- Base getter: `MegaCrit.Sts2.Core.Models.CharacterModel.CharacterSelectTransitionPath`.
- Preload membership: both `AssetPathsCharacterSelect` and full-run `AssetPaths` include the
  transition material path.
- Call sites: character-select, daily/custom run, multiplayer load, and continue-run paths pass
  the selected character's material to `NGame.Instance.Transition.FadeOut(0.8f, path)`, then call
  `FadeIn()` after the destination loads.
- Actual consumer class: `MegaCrit.Sts2.Core.Nodes.NTransition : ColorRect`.
- Actual scene: `res://scenes/game.tscn`, UID `uid://cywpu6lxdjhuu`.
- Actual node: `%GameTransitionRect`, black `ColorRect`, full viewport anchors with offsets
  `left=-320`, `top=-60`, `right=+320`, `bottom=+60`, pivot `(1280,600)`. At the game's
  `1920x1080` design canvas this is exactly `2560x1200` and deliberately overscans every edge.
- Texture UV therefore consumes the entire image. There is no independent pivot, crop region,
  draw order, bone, slot, or attachment.

## Shader contract

The original material uses the following logic:

```glsl
float falloff = 1.0 - texture(transitionTex, UV).r;
float remap = mix(-0.1, 1.1, threshold);
falloff = step(falloff, remap);
COLOR.a = falloff;
```

- Only the texture's red channel affects runtime output; source hue is never displayed.
- As `threshold` rises from `0` to `1`, high-red / bright mask regions become black first and
  low-red / dark regions become black last. Fade-in reverses this process.
- The shader applies a hard step per pixel, so broad value ramps and multiple tonal bands create
  the motion. A binary black/white image would pop instead of wipe.
- The candidate must distribute high, middle, and low values across all four screen quadrants,
  avoid a single isolated reveal seed, and remain full bleed after overscan.

## Vanilla reference facts

- Ironclad, Silent, and Necrobinder transition textures are all `2560x1200`, fully opaque,
  grayscale thematic masks.
- They use broad overlapping shapes, not literal UI, readable text, or transparent artwork.
- Original Ironclad mask source:
  `inspection/source/original-ironclad-transition-decoded.png`, SHA-256
  `766ab00b2df8423b9469f25371ee7addda34a73dbf8b295baaf6ce9cb823ef62`.
- Original Ironclad red-channel range is `18..255`, mean `65.043`; quantiles are
  `p01=18, p05=36, p10=36, p25=55, p50=55, p75=73, p90=109, p95=128, p99=164`.
  This is a dark-dominant mask with sparse early highlights. Exact histogram matching is not a
  requirement, but the Vivhite candidate must avoid a near-binary or mostly-white distribution.

## Creative and safety contract

- White Qi identity: silver bob hair, purple eyes, round gold glasses, blue butterfly,
  black/white/blue-violet magical-girl dress, cool and restrained demeanor.
- The transition should read as mathematical magic through concentric constructions, topology,
  tessellation, orbital curves, butterfly-wing symmetry, and broad calculation-like geometry.
- Exactly one White Qi figure may appear; if present, her face and closed mouth remain clear and
  unobstructed, and both hands are empty.
- No sword, staff, wand, book, shield, handheld orb, computer, brush, tool, or other prop.
- No red or crimson element. No blood, liquid, droplet, strand, filament, ribbon, or line near the
  mouth or face. No magic may originate from, cross, touch, point toward, or appear to leave the
  mouth, nose, lips, or face edge. In particular, no “thin crimson magic threads” and no red bar
  by the mouth.
- No readable text, letters, numbers, equations, logo, signature, watermark, UI frame, panel grid,
  second person, duplicate pose, weapon silhouette, or scenery crop border.

## Composition and deterministic adaptation

- Requested composition is ultra-wide `32:15` / `2560x1200`.
- Built-in image generation does not expose a destination-size control. Preserve its returned
  original unchanged. If it returns a taller landscape canvas, a deterministic centered crop to
  `32:15` followed by a single high-quality resize to `2560x1200` is permitted after visual
  acceptance; this changes no semantic content and creates no Alpha.
- Essential figure/emblem geometry must stay within the middle `68%` of source height so that a
  potential `3:2 -> 32:15` center crop cannot cut the face, butterfly, hands, or primary rings.
- Broad background geometry must continue through all source edges so the final mask remains
  full bleed with no blank border.

## Evidence paths

- Decompiled consumers: `inspection/decompiled-consumers/`.
- Source/material/shader inspection: `inspection/source/`.
- Static source scan: `inspection/source-consumer-report.json`.
- Mask metrics: `inspection/source/original-mask-metrics.json`.
- Vanilla comparisons: `inspection/source/vanilla-transition-references/`.

