# Crimson Conservation Law card attempt 01 — static assessment

Status: `rejected_static_crop_failure`

## What passed

- The source is one complete opaque `1536×1024` RGB8 card scene, not an atlas, sprite sheet, transparent cutout, icon, or UI composition.
- Vivhite is centered and calm with short silver hair, violet eyes, round gold glasses, a blue butterfly, two visible empty hands, and the intended white/deep-indigo/violet/gold costume.
- The image reads as a stable persistent Power: a closed cyan input circuit enters a central conservation hub and produces one fixed golden strength star, with a smaller repeated five-to-one module above.
- Exactly five lower life crystals and five upper life crystals exist in the source. There is no enemy, hit, attack, projectile, explosion, shield, weapon, text, second character, liquid, blood, red strand, or mouth-adjacent red element.
- The preparation tool accepted every source pixel as fully opaque. Its deterministic crop is `x=105, y=8, 1325×1007`, resized with Lanczos to `1000×760 RGB8`.

## Why it failed

- The dominant lower return loop was placed too far to screen-left in the source.
- The mandatory fixed centered crop cuts several of its five input crystals at the left image edge.
- At `100×76`, five separate highlights can still be inferred, but the crystals are no longer complete or visually equal-sized. This fails the user's explicit requirement that the five inputs remain clearly and individually countable at thumbnail size.

## Next attempt

Attempt 02 may change only the framing of the main apparatus: move and compact the entire lower five-crystal loop inward so every crystal and its closed cyan track remain fully inside the centered `25:19` crop. Preserve the successful identity, stable ability topology, upper repeat, golden output, background, and all hard bans.
