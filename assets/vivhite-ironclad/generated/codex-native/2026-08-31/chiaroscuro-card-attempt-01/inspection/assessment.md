# Chiaroscuro attempt 01 static assessment

## Consumer and format

- The source is one complete opaque `1536×1024` RGB8 scene, not an atlas, sprite sheet, transparent cutout, Spine attachment, or UI composition.
- Runtime loading was verified in `Chiaroscuro.cs` and `VivhiteCard.cs`: the card resolves `images/cards/Chiaroscuro.png` by compiled type name.
- The deterministic centered `25:19` crop is `x=105, y=8, 1325×1007`, resized with Lanczos to exactly `1000×760` RGB8.
- The runtime portrait, full-size grayscale inspection, and `250×190` / `100×76` color and grayscale thumbnails were generated without content-aware cropping, compositing, repainting, or Alpha processing.

## Identity and hard bans

- Exactly one Vivhite is present with short silver hair, cool violet eyes, round gold glasses, a blue butterfly ornament, and the white/deep-indigo/violet/gold magical-girl costume.
- Both hands are empty, visible, and held inward. No weapon, held prop, enemy, second character, text, logo, signature, watermark, card frame, or UI appears.
- Her mouth and face are unobstructed. No red or crimson bar, line, strand, ribbon, liquid, blood, coughing visualization, or mouth-emitted magic appears anywhere in the scene.

## Card semantics

- A single continuous faceted geometric domain fully surrounds and visibly protects Vivhite. Its stable centered enclosure and inward hand posture make defense the dominant reading.
- The domain and the full-depth observatory share one crisp hard split between near-black/deep-indigo shadow and silver-white illumination, preserving the chiaroscuro concept through foreground, middle ground, and distant architecture.
- A compact cyan-blue closed storage circuit sits low at Vivhite's side, safely away from her face. Its small star-like angular symbol remains sealed inside a circular capacitor cradle and has no target, impact, trail, or outward motion.
- The future-attack motif remains subordinate to the enclosing domain. Nothing pierces the shell; no beam, projectile, enemy, collision, or outward blast turns the composition into an attack card.

## Small-size and grayscale review

- At `250×190`, the enclosing shell, hard light/shadow split, centered protected figure, and lower cyan storage circuit remain distinct.
- At `100×76`, the closed domain remains the strongest silhouette in both color and grayscale. The split reads as a dark half and bright half around one protected center.
- The small stored symbol remains visibly contained rather than released. With card name and type hidden, the image still reads as a defensive skill with a prepared future-attack rider, not as a current attack.

## Status

Static source, deterministic crop, RGB8 format, mouth hard-ban, original-color, grayscale, and thumbnail checks pass. The component stops after attempt `1/8`. Real Vulkan card-frame, hand-size, and enlarged-view validation remain pending and are not claimed here.
