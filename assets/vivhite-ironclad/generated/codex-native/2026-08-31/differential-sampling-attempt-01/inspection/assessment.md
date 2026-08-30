# Differential Sampling attempt 01 static assessment

## Consumer and format

- The source is one complete opaque `1536×1024` RGB8 scene, not an atlas, sprite sheet, transparent cutout, or UI composition.
- `VivhiteCard.CustomPortraitPath` loads this card as `res://Vivhite/images/cards/DifferentialSampling.png`; there is no region, slot, pivot, animation, or Alpha-layer consumer.
- The deterministic centered `25:19` crop is `x=105, y=8, 1325×1007`, resized with Lanczos to exactly `1000×760` RGB8.
- The runtime portrait, full-size grayscale inspection, and `250×190` / `100×76` color and grayscale thumbnails were generated without content-aware cropping, compositing, repainting, or Alpha processing.

## Identity and hard bans

- Exactly one Vivhite is present with short silver hair, violet eyes, round gold glasses, a blue butterfly, and the established white/deep-indigo/violet/gold magical-girl costume.
- Both hands are visible, empty, and drive separate outgoing pulses. No weapon, held prop, second character, creature, text, equation, logo, signature, watermark, or card UI appears.
- Her mouth is naturally closed and unobstructed. No red or crimson line, strand, ribbon, liquid, blood, wound, coughing visualization, or mouth-emitted magic appears on or near the mouth, cheeks, nose, glasses, or face.

## Card semantics

- Two separate white-blue/violet tangential pulse paths leave the upper and lower hands along strong open screen-right diagonals.
- The same single faceted training monolith receives two large, spatially separated terminal impact flares. Their separation remains obvious and reads as two consecutive hits rather than one broad beam.
- A secondary cyan geometric trajectory returns from the lower impact area along the floor to the low hand. It stays below the shoulders, does not cross the face, and does not enclose Vivhite like a defensive shell.
- The environment has a polished geometric foreground floor, a clear character-and-spell middle ground, and deep observatory arches and astronomical instruments in the background.

## Small-size and grayscale review

- At `250×190`, Vivhite, the two outgoing tracks, the two distinct impact flares, the single target, and the lower cyan return path remain separately readable.
- At `100×76`, the two bright right-side impact points and their two left-to-right connecting trajectories remain the dominant silhouette. The result still reads immediately as a fast double attack.
- In grayscale, the two open attack lines and two terminal explosions remain distinct; the lower return loop remains subordinate and does not become a shield boundary.

## Status

Static source, deterministic crop, RGB8 format, mouth hard-ban, original-color, grayscale, and thumbnail checks pass. The component stops after attempt `1/8`. Real Vulkan card-frame, hand-size, and enlarged-view validation remain pending and are not claimed here.
