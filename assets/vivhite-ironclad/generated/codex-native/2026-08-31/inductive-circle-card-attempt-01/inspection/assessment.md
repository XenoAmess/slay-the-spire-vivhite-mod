# Inductive Circle card attempt 01 — static acceptance

Status: static_accepted_pending_game_validation

## Consumer and file contract

- The class name is `InductiveCircle`; `VivhiteCard.CustomPortraitPath` resolves it to `res://Vivhite/images/cards/InductiveCircle.png`.
- The target is one complete opaque card illustration, not an atlas, sprite sheet, Spine attachment, or alpha overlay.
- The Codex-native source is 1536×1024, PNG color type 2 (RGB8), with no alpha channel.
- The deterministic centered 25:19 crop is x=105, y=8, 1325×1007.
- The runtime output is exactly 1000×760, PNG color type 2 (RGB8).
- The runtime file and archived centered RGB8 inspection output are byte-identical with SHA-256 `63E75015B007533F158A056CA548F34EA7A6856AEF2FC29F5E494EE163EA5DD1`.
- EvoLink was not used.

## Visual acceptance

- Exactly one Vivhite is present with short silver hair, violet eyes, round gold glasses, a blue butterfly ornament, the white/deep-indigo/violet/gold magical-girl costume, and two complete empty hands.
- Vivhite remains calm and centered while a stable open induction circle continuously operates around her body.
- Three cyan-blue life-crystal stages are visibly ordered from the small abdominal core through the medium upper core to the large crown core. Their increasing scale conveys proportional growth rather than a flat fixed heal.
- Multiple dark enemy-star markers occupy the distant upper galleries. The upper-left inner marker is visibly breaking and extinguishing, while white-gold connectors carry the event into the ascending crystal sequence.
- Foreground observatory rails and reflections, the character and induction apparatus in the middle ground, and deep vaulted galleries and star maps in the distance create a continuous full scene to all four edges.
- The dominant structure is a vertical self-power axis with open concentric orbits. It does not close into a defensive sphere and nothing fires toward an enemy.
- There is no enemy body, corpse, gore, card frame, text, number, equation, pseudo-glyph, UI, logo, weapon, held prop, shield, second character, duplicate limb, split panel, or watermark.
- There is no red or crimson accent, mouth-adjacent strand, liquid, blood, mouth-emitted magic, or other facial obstruction.

## Small-size and grayscale review

- At 250×190, the three crystal stages, open orbits, central empty-hand maintenance pose, and distant dark star markers remain individually distinguishable.
- At 100×76, the small-to-medium-to-large crystal progression and vertical concentric system remain the dominant read; the composition still presents a persistent self-power rather than an attack or shield.
- In grayscale at both sizes, crystal scale and orbit hierarchy preserve the induction/proportional-growth semantics without relying on card type color or text.

## Remaining gate

The static source, deterministic crop, file format, original-color, grayscale, and thumbnail checks pass. Real Vulkan card-frame, hand-size, and enlarged-view validation remain pending and are not claimed by this component.
