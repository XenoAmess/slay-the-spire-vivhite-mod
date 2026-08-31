# Complementary Afterimage card attempt 01 — static assessment

Status: `static_accepted_pending_game_validation`

## Consumer and format

- Runtime class: `ComplementaryAfterimage`; runtime portrait: `Vivhite/Vivhite/images/cards/ComplementaryAfterimage.png`.
- `VivhiteCard.CustomPortraitPath` loads the portrait as one independent PNG. It is not an atlas, region, sprite sheet, transparent cutout, icon, Spine attachment, or UI composition.
- The source is one complete opaque `1536×1024 RGB8` scene. It has no Alpha channel.
- The deterministic centered `25:19` crop is `x=105, y=8, 1325×1007`, resized with Lanczos to exactly `1000×760 RGB8`.
- The archived prepared image and runtime image are byte-identical, both SHA-256 `7F643DC614D76F197044317DEB7877F8DB455C9AE61E23E9E1EA637B03A60944`. No content-aware crop, compositing, repainting, masking, or Alpha processing was used.

## Identity and hard bans

- Exactly one Vivhite appears with short silver hair, violet eyes, round gold glasses, a blue butterfly ornament, and the established white/deep-indigo/violet/gold magical-girl costume.
- Her pose is an asymmetric three-quarter attack cast. Both hands are visible, anatomically coherent, and empty.
- No weapon, held prop, second character, human afterimage, ghost, duplicate limb, card UI, text, equation, pseudo-glyph, logo, signature, or watermark appears.
- Her mouth is naturally closed and unobstructed. No red or crimson bar, line, strand, ribbon, filament, liquid, blood, wound, coughing visualization, or mouth-emitted magic appears on or near her mouth, face, glasses, or hair.

## Conditional two-hit attack semantics

- The upper attack lane contains one large violet-and-gold hard-edged star core and leads to one bright upper impact on the right-side abstract crystalline structure.
- A compact cyan faceted life-light crystal is visibly lit inside a broad closed return node low beside Vivhite. Its low geometric circuit remains far from her face and reads as magical recovery rather than liquid, blood, ribbon, strand, or an organic vein.
- The lit node feeds a distinct cyan-and-gold afterimage star core along a lower, clearly offset parallel trajectory. This core leads to a separate lower impact on another facet of the same right-side structure.
- The two star cores, two attack lanes, and two impact bursts are spatially separated and individually countable. The afterimage is entirely geometric and cannot be mistaken for a second Vivhite.
- The dominant silhouette is an open left-to-right attack. It neither surrounds Vivhite with a defensive shell nor reads as a static persistent ability.
- Foreground rails and prisms, the middle-ground caster and return node, and the distant observatory city provide a complete full-bleed scene with depth beyond both attack endpoints.

## Small-size and grayscale review

- At `250×190`, Vivhite, the low return node, the upper violet-gold first strike, the lower cyan-gold afterimage, and both right-side impacts remain separately readable.
- At `100×76`, two bright parallel attack diagonals remain visible from the left casting side toward two separated impact clusters. The low circular return node is still identifiable beneath the attack lanes.
- In grayscale at both sizes, spacing, lane separation, star-core silhouettes, and the two impact positions preserve the conditional two-hit sequence without relying on violet, cyan, gold, card title, or type-border color.

## Status

Static source, deterministic crop, RGB8 format, original-color, grayscale, `250×190`, `100×76`, identity, attack topology, and mouth hard-ban checks pass. The main agent visually accepted attempt `1/8` and explicitly requested no further generation. Real Vulkan card-frame, hand-size, and enlarged-view validation remain pending and are not claimed here.
