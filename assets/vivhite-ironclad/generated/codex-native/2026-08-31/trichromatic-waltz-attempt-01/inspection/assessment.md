# Trichromatic Waltz attempt 01 static assessment

## Consumer and format

- The source is one complete opaque `1536×1024` RGB8 scene, not an atlas, sprite sheet, transparent cutout, or UI composition.
- The deterministic centered `25:19` crop is `x=105, y=8, 1325×1007`, resized with Lanczos to exactly `1000×760` RGB8.
- The runtime portrait, full-size grayscale inspection, and `250×190` / `100×76` color and grayscale thumbnails were generated without content-aware cropping, compositing, repainting, or Alpha processing.

## Identity and hard bans

- Exactly one Vivhite is present with short silver hair, violet eyes, round gold glasses, a blue butterfly ornament, and a white/deep-indigo/violet/gold magical-girl costume.
- Both hands are empty and clearly visible. No weapon, held prop, second character, duplicate limb, text, logo, signature, watermark, or card UI appears.
- Her mouth and face are natural and unobstructed. No red or crimson bar, line, strand, ribbon, liquid, blood, coughing visualization, or mouth-emitted magic appears near the mouth or face.
- Crimson is confined to one dry, opaque, hard-edged crystalline wheel and its solid outgoing facet.

## Card semantics

- Three large geometric wheels are separated in both position and trajectory: cyan-blue above, violet in the middle, and crimson below. Their outgoing vectors converge on one distant celestial target rather than forming a shield around Vivhite.
- Three separate terminal flashes curve around the same target, preserving the intended three-hit waltz rhythm rather than reading as one undifferentiated blast.
- The cyan drain route is spatially separate: a polygonal circuit leaves the target on the far right, curves through the lower foreground, and reconnects at Vivhite's forward hand. It does not touch her mouth or resemble blood, liquid, ribbon, or a thin organic filament.
- Foreground crystals, the middle-ground terrace, and the distant observatory architecture provide a complete scene and reinforce left-to-right attack depth.

## Small-size and grayscale review

- At `250×190`, all three wheel masses, the remote target, and the lower cyan return circuit remain separately legible.
- At `100×76`, the image still reads as an open, asymmetric multi-hit attack because three bright radial masses step toward one right-side target.
- In grayscale, the separated wheel silhouettes and three terminal flashes remain visible; the lower return circuit stays a secondary route rather than becoming a defensive boundary.

## Status

Static source, deterministic crop, RGB8 format, mouth hard-ban, original-color, grayscale, and thumbnail checks pass. The component stops after attempt `1/8`. Real Vulkan card-frame, hand-size, and enlarged-view validation remain pending and are not claimed here.
