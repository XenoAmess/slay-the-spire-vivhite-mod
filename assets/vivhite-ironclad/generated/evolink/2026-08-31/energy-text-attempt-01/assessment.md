# Attempt 0190 assessment

Status: **accepted for the static runtime asset**. No second paid attempt was
needed.

## Generation record

- Route: repository `tools/art/evolink_transparent_image.py` only.
- Endpoint/model: EvoLink `gpt-image-2`.
- Request transparency: `background=transparent`, `n=1`.
- Returned source: `1024x1024` native RGBA8 PNG.
- Raw SHA-256: `f2a5f701bf775ede7a132bee3c9b511a22606e6834634dd15f821065fc6ea2a2`.
- Exact prompt, sanitized request, and resumable task id are stored beside the
  untouched `output.png`.

## Raw Alpha finding

The untouched result has corner Alpha `[0, 0, 1, 0]`. The only source-edge
Alpha has maximum value `1`; no pixel with Alpha `>=16` touches an edge. The
`A>=16` bbox is `[57, 66, 909, 862]`, while the substantially opaque core is
well inside the image. This is an isolated sub-visible trim warning, not a
visible canvas-shaped field. It was not thresholded, masked, erased, or used as
a reason to spend another request.

## Permitted deterministic adaptation

The accepted source was uniformly resized in RGBA with Godot Lanczos from its
complete `1024x1024` canvas to `22x22`, then centered on a new transparent
`24x24` canvas with one pixel of safety padding. The same check was repeated at
`16x16` and `12x12`, also with one pixel of padding.

The archived `inspection-padded-1/inspect_energy_text.gd` performs only that
operation and SourceOver rendering. It contains no crop, threshold, mask,
flood fill, color key, Alpha cleanup, erosion, expansion, recolor, or creative
edit.

Final `24x24` metrics:

- format: native RGBA8;
- corner Alpha: `[0, 0, 0, 0]`;
- all four edge maximum Alpha: `0`;
- `A>0` bbox: `[1, 1, 22, 22]`;
- `A>=16` bbox: `[2, 2, 20, 19]`;
- `A>=127` bbox: `[3, 3, 18, 17]`;
- SHA-256: `10d26ff0e87026fa17a98ba25632e1ce879b84e93fa150e9acdb4d18c74fde0d`.

## Visual acceptance

Real SourceOver images on black, white, and game-indigo `#182139` were inspected
at `24`, `16`, and `12` pixels. The platinum rim, violet-blue disk, and bright
four-point center remain distinct at 24 and 16 pixels; the 12-pixel version
retains a clean luminous energy-dot silhouette. No rectangular haze, visible
edge pollution, text, person, weapon, blood/liquid, mouth element, or detached
particle is present.

The result reads as the compact textual sibling of the five-layer energy orb
and is materially distinct from the retired red Ironclad placeholder.

Runtime output:
`Vivhite/Vivhite/images/characters/energy_text.png`.

This assessment covers the standalone static sprite. It does not claim a
separate full-game/Vulkan integration run.
