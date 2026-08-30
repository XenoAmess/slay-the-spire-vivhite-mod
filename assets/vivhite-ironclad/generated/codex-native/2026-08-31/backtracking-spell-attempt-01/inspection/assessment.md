# Backtracking Spell attempt 01 — static acceptance

Status: static_accepted_pending_game_validation

## Consumer and file contract

- The target is one complete opaque card illustration, not an atlas, sprite sheet, Spine attachment, or alpha overlay.
- Runtime consumption is derived from the class name `BacktrackingSpell` through `VivhiteCard.CustomPortraitPath`.
- The Codex-native source is 1536×1024, PNG color type 2 (RGB8), with no alpha channel.
- The deterministic centered 25:19 crop is `x=105, y=8, 1325×1007`.
- The runtime output is exactly 1000×760, PNG color type 2 (RGB8), with SHA-256 `54314C7764458EBB0C84B1D09ABE398FAD63EC9AB488BD848CA47BF7B4ECDD18`.
- The runtime file is byte-identical to the accepted inspection crop.
- EvoLink was not used.

## Visual acceptance

- Exactly one Vivhite is present with short silver hair, violet eyes, round gold glasses, one blue butterfly ornament, the approved magical-girl costume, and two visible empty hands.
- The astral-computation archive has dark discarded pages in the foreground, Vivhite and the reversed trajectory in the middle ground, and deep shelves, stairs, celestial mechanisms, and observatory architecture in the distance.
- One primary pale card page with a sharp abstract attack-star emblem rises from the lower-right discard repository and returns toward Vivhite's waiting hand.
- A broad, continuous purple-gold arc and ordered page afterimages make the direction read as temporal backtracking and retrieval rather than a projectile fired at an enemy.
- The primary page carries a dim hollow circular cost medallion without a numeral, conveying that the retrieved attack becomes free for the current turn.
- The dominant reading is selection from discard, recursion, time reversal, and return to hand. There is no enemy, impact, attack beam, enclosing shield, defensive dome, or self-transformation axis.
- There is no card frame, readable text, number, equation, pseudo-glyph, UI, logo, weapon, held prop, second character, duplicate limb, signature, or watermark.
- There is no blood, red liquid, crimson strand, mouth-adjacent line, mouth-emitted magic, or object emerging from the mouth.

## Small-size and grayscale review

- At 250×190, the lower-right discard repository, rising attack-emblem page, reverse arc, and receiving hand remain distinct.
- At 100×76, the bright returning page and curved path remain legible against the dark archive and still read as retrieval rather than impact.
- In grayscale, the page, reverse path, dark origin slot, and waiting hand remain separated by value and direction rather than card border or hue.

## Remaining gate

The static source, deterministic crop, file format, and thumbnail checks pass. Real Vulkan card-frame, hand-size, and enlarged-view validation remain pending and are not claimed by this component.
