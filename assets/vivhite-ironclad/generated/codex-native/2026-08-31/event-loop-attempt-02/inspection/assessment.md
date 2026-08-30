# Event Loop attempt 02 — static acceptance

Status: `static_accepted_pending_game_validation`

## Consumer and file contract

- The target is one complete opaque card illustration, not an atlas, sprite sheet, Spine attachment, or alpha overlay.
- Runtime consumption is derived from the class name `EventLoop` through `VivhiteCard.CustomPortraitPath`.
- The Codex-native source is 1537×1023, PNG color type 2 (RGB8), with no alpha channel.
- The deterministic centered 25:19 crop is `x=106, y=8, 1325×1007`.
- The runtime output is exactly 1000×760, PNG color type 2 (RGB8), with SHA-256 `A3BDFFDABB5901F258F4EDE1436137E26C582129F57DAC50D4CA48E271F63E91`.
- The runtime file is byte-identical to the accepted inspection crop.
- EvoLink was not used.

## Visual acceptance

- Exactly one Vivhite is present with short silver hair, violet eyes, round gold glasses, a blue butterfly ornament, the established white/deep-indigo/violet/gold magical-girl costume, and two visible empty hands.
- The opaque scene has dark crystal consoles and rails in the foreground, Vivhite and the two pages in the middle ground, and a deep mathematical-computation corridor with an empty timing gate in the distance.
- Exactly two card-shaped pages appear across the whole frame. The warm ivory page reads as the already-played original; the cool white-blue page reads as its single temporary mirror copy.
- The copied page has a conspicuous empty dark circular cost socket without a numeral, communicating zero energy this turn without using text.
- A broad purple-gold event track returns from the empty background gate and makes one clear fork into the two pages at Vivhite's receiving hand. The empty gate prevents a third-page reading.
- The dominant reading is event replay, recursion, and one-time duplication. There is no enemy, impact, attack beam, enclosing shield, defensive dome, or vertical self-transformation axis.
- There is no card frame, readable text, number, equation, pseudo-glyph, UI, logo, weapon, held prop, second character, duplicate limb, signature, or watermark.
- There is no blood, red liquid, crimson strand, mouth-adjacent line, mouth-emitted magic, or object emerging from the mouth.

## Small-size and grayscale review

- At 250×190, the empty timing gate, broad loop, two-page endpoint, open receiving hand, and warm/cool page distinction remain clear.
- At 100×76, the composition still shows one loop leading to a pair of pages rather than a deck or attack projectile.
- In grayscale, the original and copied page remain separate by border value, the copy's dark empty cost socket remains visible, and the bright loop remains distinct from the corridor.

## Remaining gate

The static source, deterministic crop, file format, and thumbnail checks pass. Real Vulkan card-frame, hand-size, and enlarged-view validation remain pending and are not claimed by this component.
