# Crimson Area attempt 01 static assessment

## Consumer and format

- The source is one complete opaque `1536×1024` RGB8 scene, not an atlas, sprite sheet, transparent cutout, or UI composition.
- The deterministic centered `25:19` crop is `x=105, y=8, 1325×1007`, resized with Lanczos to exactly `1000×760` RGB8.
- The runtime portrait, full-size grayscale inspection, and `250×190` / `100×76` color and grayscale thumbnails were generated without content-aware cropping, compositing, repainting, or Alpha processing.

## Identity and hard bans

- Exactly one Vivhite is present with short silver hair, cool violet eyes, round gold glasses, the blue butterfly, and the established white/deep-indigo/violet/gold magical-girl costume.
- Both hands are empty, visible, and readable. No weapon, held prop, second character, text, logo, signature, watermark, or card UI appears.
- Her mouth is naturally closed and unobstructed. No red or crimson bar, line, strand, ribbon, liquid, blood, wound, coughing visualization, or mouth-emitted magic appears on or near the mouth, cheeks, nose, glasses, or face.
- Crimson is confined to the hard-edged geometric attack plane between her hands and the remote impact point.

## Card semantics

- The large asymmetric crimson-violet area compresses from a broad faceted plane into one sharp screen-right cutting surface and terminates in a distinct distant impact. The faceless black-violet target and surrounding architecture visibly split along the same axis.
- The cyan drain system is spatially separate from the attack: broad polygonal segments leave the lower impact, arc through the lower third, and reconnect to the chest crystal from below. It does not cross the face or resemble liquid, blood, or a thin filament.
- The composition is open, directional, and strongly asymmetric. It does not form a closed defensive shell or a centered self-buff arrangement.

## Small-size and grayscale review

- At `250×190`, the broad geometric attack face, the right-side impact, and the lower cyan return circuit remain separately readable.
- At `100×76`, the dominant grayscale silhouette still reads as a left-to-right attack because the hard-edged wedge and bright terminal impact remain the strongest connected axis.
- In grayscale, the lower return circuit remains a second, lower-value geometric route back toward Vivhite rather than merging into a shield boundary.

## Status

Static source, deterministic crop, RGB8 format, mouth hard-ban, original-color, grayscale, and thumbnail checks pass. The component stops after attempt `1/8`. Real Vulkan card-frame, hand-size, and enlarged-view validation remain pending and are not claimed here.
