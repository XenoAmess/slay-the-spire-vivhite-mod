# ChromaticLimit attempt 01 — static assessment

- Status: `static_accepted_pending_game_validation`.
- Attempts used: `1/8`; generation stopped after this result passed the static gate.
- Generation path: built-in Codex-native `image_gen`; EvoLink was not used.
- Native output: `1254×1254`, 8-bit PNG color type 2 (`RGB8`), fully opaque, preserved unchanged as `original.png`.
- Required square source: deterministic uniform Lanczos resize to `1024×1024 RGB8`, with no crop, repaint, mask, Alpha edit, or content-aware adjustment.
- Runtime: deterministic centered `25:19` crop `x=12, y=132, w=1000, h=760`, yielding exact `1000×760 RGB8`.
- Runtime SHA-256: `8FB5C446EDFE8328165AF1F4AE2C0488F02BC6ECD82691A8B9EC3821B15F507E`.

## Visual result

The scene communicates the complete X-cost loop without relying on card UI or written symbols:

- the huge segmented concentric dial is an unmistakable variable controller, with both dark empty sockets and a selected set of luminous violet, blue, and gold nodes;
- multiple hard-edged attack lanes remain spatially separated from launch to impact and form a strong open, asymmetric, screen-right Attack silhouette;
- every lane converges on one abstract hostile faceted region rather than a creature or humanoid enemy;
- multiple cyan return arcs leave the impact region separately, sweep below the combat lane, and merge into one lower collector reservoir;
- the large cyan crystalline reservoir and newly condensed crystals clearly read as healing converted into Margin;
- foreground calibration architecture, the middle-ground dial/attack exchange, and distant observatory towers provide a full-bleed opaque scene with strong depth;
- after the required central crop, the dial hub, inactive sockets, active nodes, attack lanes, impact cores, return circuits, and Margin reservoir all remain visible;
- the variable multi-hit fan and lower return loop remain recognizable in the `250×190` and `100×76` color and grayscale checks.

## Hard-ban review

Passed:

- no human figure, face, mouth, creature, or humanoid enemy;
- no sword, staff, wand, bow, firearm, blade, book, held prop, or weapon-shaped apparatus;
- no text, literal X, letter, number, equation, readable formula, pseudo-glyph, logo, signature, watermark, card frame, or UI;
- no blood, gore, wound, red/crimson liquid, bar, line, strand, thread, filament, ribbon, tendril, or magic;
- therefore no mouth-adjacent red element and no mouth-emitted magic are possible;
- no enclosing protective sphere, shield bubble, or static self-buff silhouette. The closed curves belong to a visibly segmented attack instrument and open into the rightward firing lanes.

## Tool-size disclosure

The Prompt requested `1024×1024`, but the built-in tool returned `1254×1254` and exposed no explicit size parameter. The native output remains untouched. `source-1024x1024-rgb8.png` is a documented deterministic square-to-square Lanczos size adaptation so the delivered production source satisfies the requested `1024×1024` contract. The first preliminary runtime conversion from the native `1254×1254` file is retained in `runtime-from-native-1254-preliminary.png`; it was not installed as the final runtime asset.

## Remaining gate

Static generation, opacity, deterministic size adaptation, deterministic crop, grayscale, and `250×190 / 100×76` thumbnail checks passed. Real in-game Vulkan card-frame, hand-size, and enlarged-card validation remain pending and are not claimed here.
