# Golden Composition attempt 01 static assessment

## Consumer and format

- The source is one complete opaque `1536×1024` RGB8 scene, not an atlas, sprite sheet, transparent cutout, Spine layer, or UI composition.
- `GoldenComposition` inherits the sealed `VivhiteCard.CustomPortraitPath` contract and therefore consumes `images/cards/GoldenComposition.png` as one independent portrait.
- The deterministic centered `25:19` crop is `x=105, y=8, 1325×1007`, resized with Lanczos to exactly `1000×760` RGB8.
- The runtime portrait and archived centered candidate are byte-identical (`SHA-256 AC0A51538DDA3BD30C52C16E3CDC4DFD3832A1D74F6857111B5B7AF3373C1082`). No content-aware crop, compositing, repainting, masking, or Alpha processing was used.

## Identity and hard bans

- Exactly one Vivhite is present with short silver hair, violet eyes, round gold glasses, a blue butterfly ornament, and a white/deep-indigo/violet/gold magical-girl costume.
- Both hands are empty and visible. No weapon, held prop, second character, duplicate limb, text, equation, pseudo-glyph, logo, signature, watermark, card frame, or UI appears.
- Her mouth and face are natural and unobstructed. No red or crimson bar, line, strand, ribbon, liquid, blood, coughing visualization, or mouth-emitted magic appears near the mouth or face.

## Card semantics

- Three hard-edged gold-violet star cores are separated along the outbound path and progress from small to medium to large. They remain individually countable after the centered crop.
- The dominant golden spiral is open and strongly directional from Vivhite on the left toward one distant architectural target on the right; it does not wrap her in a defensive shell.
- Three separate target-side flashes form a readable first contact, second impact, and decisive final burst on the same structure.
- A separate broad cyan polygonal circuit runs through the lower foreground from the target back to Vivhite's lowered hand. It remains spatially distinct from the outbound gold-violet attack and does not touch her mouth or resemble blood, liquid, a ribbon, or an organic vein.
- Foreground crystal rails, the middle-ground bridge, and the distant celestial city provide a full scene and reinforce the left-to-right attack depth.

## Small-size and grayscale review

- At `250×190`, the three outbound star-core masses, three target-side impact stages, single right-side target, and lower cyan return circuit remain separately legible.
- At `100×76`, the image still reads as an open multi-hit attack: three bright nodes advance along one large spiral into a stacked impact cluster, while the cyan circuit remains a distinct lower return route.
- In grayscale, node spacing, scale progression, target impacts, and the lower geometric circuit remain visible without relying on gold, violet, or cyan color labels.

## Status

Static source, deterministic crop, RGB8 format, mouth hard-ban, original-color, grayscale, `250×190`, and `100×76` checks pass. The component stops after attempt `1/8`. Real Vulkan card-frame, hand-size, and enlarged-view validation remain pending and are not claimed here.
