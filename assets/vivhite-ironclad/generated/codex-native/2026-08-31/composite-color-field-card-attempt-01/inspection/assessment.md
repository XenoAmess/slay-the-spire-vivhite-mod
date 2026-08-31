# Composite Color Field card attempt 01 — static assessment

Status: `static_accepted_pending_game_validation`

## Consumer and format

- Runtime class: `CompositeColorField`; runtime portrait: `Vivhite/Vivhite/images/cards/CompositeColorField.png`.
- The source is one complete opaque `1536×1024` RGB8 scene, not an atlas, sprite sheet, transparent cutout, icon, or UI composition.
- The deterministic centered `25:19` crop is `x=105, y=8, 1325×1007`, resized with Lanczos to exactly `1000×760 RGB8`.
- The archived prepared image and runtime image are byte-identical, both SHA-256 `57B6619C325451C64090FCB7122712DA45C461D38B0E550662FBD2F17ED6380E`.

## Identity and hard bans

- Exactly one Vivhite is present with short silver hair, cool violet eyes, round gold glasses, a blue butterfly ornament, and the established white/deep-indigo/violet/gold magical-girl costume.
- Her expression is calm and analytical. Both hands are visible, empty, and used only to deploy the field.
- No weapon, held prop, second person, creature, humanoid enemy, card UI, text, number, equation, readable symbol, pseudo-glyph, logo, signature, watermark, duplicate limb, or cropped critical hand appears.
- Her mouth is naturally closed and unobstructed. No red or crimson bar, line, strand, ribbon, filament, liquid, blood, wound, coughing visualization, or mouth-emitted magic appears on or near her mouth, face, glasses, or hair.
- Composite colors are rendered as hard-edged indigo, violet, azure, icy-cyan, silver-white, and restrained pale-gold polygonal planes rather than fluid, smoke, strands, ribbons, or a rainbow band.

## Skill and field semantics

- One broad composite field spans the entire amphitheater as a stable planar environmental state. It has no origin-to-target ray, projectile, arrowhead, explosion, impact flash, hit line, or outgoing attack lane.
- Exactly three mutually separate distant hostile polyhedra remain individually countable. Each shows one crisp pale weakness face where the same field cross-section analytically intersects it.
- One broad cyan and icy-blue perimeter encloses the entire deployed field and visibly returns to Vivhite's casting side. It is integrated into the arena boundary rather than enclosing her body as a shield.
- The full-bleed scene provides crystal foreground framing, a middle-ground caster and arena field, and deep observatory arches and star-lit architecture in the far background.

## Small-size and grayscale review

- At `250×190`, Vivhite, the broad hard-edged field, all three separated polyhedra, all three pale weakness faces, and the closed return perimeter remain independently readable.
- At `100×76`, the three dark target silhouettes and their three bright weakness faces remain countable in both color and grayscale. The broad field reads as an arena-wide deployed state, while the cyan boundary remains a low perimeter rather than a body shield.
- The dominant silhouette remains “caster deploying one field across three exposed targets inside one return loop.” It does not collapse into an attack ray, fired projectile, impact, explosion, defensive dome, or self-transforming power.

## Status

Static source, deterministic crop, RGB8 format, mouth hard-ban, original-color, grayscale, and thumbnail checks pass. The main agent visually reviewed and accepted the runtime crop, explicitly directing that no additional generation be issued. The component stops after attempt `1/8`. Real Vulkan card-frame, hand-size, and enlarged-view validation remain pending and are not claimed here.
