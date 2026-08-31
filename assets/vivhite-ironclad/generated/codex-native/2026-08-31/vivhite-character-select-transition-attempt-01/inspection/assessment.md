# Vivhite character-select transition visual assessment

Status: **PASS as a static runtime-ready candidate**. It has not been wired, exported,
deployed, or observed in a live game by this isolated asset task.

## File and consumer checks

- The source was correctly classified as one complete full-frame scalar wipe mask, not a
  portrait, atlas, spritesheet, Spine attachment, or transparent VFX layer.
- The untouched native return is preserved as `original.png` (`1831x859`, RGB8,
  SHA-256 `6eb7b9331b505b5356715aa845cb817dfc8e0e3992cec206fedb3224c03bd5ea`).
- The final runtime candidate is `2560x1200`, RGB8, and all `3,072,000` pixels are fully opaque.
  It contains no Alpha channel and therefore cannot introduce a transparent border.
- The deterministic adaptation used a centered `1824x855` crop at `(3,2)` followed by one
  Lanczos resize. The face, butterfly, both hands, dress, and primary rings remain intact.
- The generated RGB had a maximum channel delta of `7/255`. Because the verified shader samples
  only `transitionTex.r`, the final archival/runtime file deterministically replicates R into G
  and B. This preserves every runtime scalar while producing strict grayscale (`0` non-grayscale
  pixels). The pre-normalization derivative remains archived and was not overwritten.
- The final runtime copy and strict-grayscale archive have SHA-256
  `82015b8f5aa1c6dd9fa57b9d757e009f35fca67d8818b269af4ab6f49ff252d2`.
- Godot 4.5.1 imported the texture and loaded the new material as `ShaderMaterial`; its
  `transitionTex` resolved to a `2560x1200` `CompressedTexture2D`, and its shader-code hash
  exactly matches the extracted vanilla transition shader.

## Identity and prohibited-element inspection

- PASS: exactly one White Qi figure; silver bob, round glasses, cool expression, magical-girl
  costume, butterfly and mathematical-magic geometry are immediately legible.
- PASS: both hands are visible and empty.
- PASS: no sword, staff, wand, book, shield, handheld orb, computer, brush, tool, or weapon
  silhouette appears.
- PASS: strict grayscale (`R=G=B` for every pixel); no red or crimson element is present.
- PASS: the mouth and face edge are clear. There is no mouth-originating strip, liquid, blood,
  droplet, ribbon, strand, filament, or fine crimson magic thread.
- PASS: no readable text, equation, number, logo, signature, watermark, UI frame, second person,
  duplicate pose, or crop border appears.
- Note: fine grayscale construction lines occur in the background as mathematical geometry.
  They neither touch nor originate from the face and are not red/crimson.

## Threshold-motion inspection

The exact vanilla shader equation was simulated at thresholds `0.20`, `0.35`, `0.50`, `0.65`,
`0.80`, and `0.90`; see `inspection/candidate/threshold-contact-sheet.png`. The strict-grayscale
normalization keeps the red channel byte-for-byte identical, so these frames are also exact for
the final runtime file.

- Bright seeds begin in several quadrants instead of one isolated point.
- The face/figure, butterfly symmetry, and large concentric construction become readable in
  successive bands.
- Midtones expand continuously through the frame; the mask does not behave like a binary logo.
- Dark background regions close last and reach complete coverage without a persistent border.
- Red-channel range is `12..255`, mean `97.801`; quantiles are `p01=27`, `p05=32`, `p10=38`,
  `p25=55`, `p50=87`, `p75=134`, `p90=176`, `p95=198`, `p99=223`.
- Simulated black coverage is `1.21%` at `0.20`, `27.64%` at `0.50`, `65.08%` at `0.70`,
  `91.99%` at `0.80`, and `100%` at `0.90`.

## Gate conclusion

Attempt `1/8` is accepted; no additional paid/native generation attempt is justified. The next
integration gate is to review and apply `.tmp/vivhite-transition-wiring.patch`, then export and
observe FadeOut/FadeIn in Vulkan. Those actions are deliberately outside this asset-only task.
