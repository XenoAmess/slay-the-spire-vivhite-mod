# V3 `hurt` neutral whole-mesh component report

## Decision

`hurt` remains on the neutral weighted whole-body mesh. The final offline result reads as a short protective contraction, leftward knockback and damped rebound at the actual combat scene scale. It does not need a dedicated `hurt_peak` image.

This component adds:

- **0** hurt PNGs;
- **0** atlas pages;
- **0** Spine attachments.

The existing `vivhite_body` attachment remains the only visible character layer. `vivhite_action_pose` is explicitly null at `t=0`; the death, slash, eye and magic-sigil slots remain empty throughout `hurt`.

## Consumer and performance contract

The game's character animation state maps `hurt` to the `Hit` trigger. Positive damage triggers it unless the damage result requests `SkipHurtAnim`. The animation therefore has to be readable immediately, must tolerate re-entry, and cannot depend on a weapon or a new gameplay event.

The authored one-second performance is:

| Time | Performance |
| ---: | --- |
| `0.00` | Neutral setup pose. |
| `0.10` | Guard contraction and peak leftward knockback, root `x=-118`. |
| `0.16` | Brief retained recoil, root `x=-110`. |
| `0.28` | Recovery begins, root `x=-55`. |
| `0.46` | Small opposite-direction rebound, root `x=+24`. |
| `0.70` | Damped settle, root `x=+7`. |
| `1.00` | Exact return to setup pose. |

The sole event remains `clear_vfx` at `0.72s`.

## Hidden Vulkan acceptance

The saved report comes from an independent hidden Windows/Vulkan render using the actual game-compatible Spine GDExtension:

- canvas `1280×900`;
- scene scale `0.28`;
- authored character scale `0.70`;
- 11 uniform samples per animation, including the exact `0.10s` impact;
- all eight animations non-empty and clear of canvas edges.

For `hurt`, the first and last frames are identical, giving 10 unique hashes from 11 samples. At impact, the Alpha bbox changes from `210×352` to `193×349`: visible width contracts by `8.1%`. Maximum centroid displacement from the first frame is `18.478px`; maximum pairwise displacement is `19.621px`; maximum changed-pixel ratio is `0.023417`.

The contact sheets are byte-identical by design. `hurt` has no attached VFX or alternate character layer, so rendering every Spine slot (composite) produces the same pixels as the character-only body render. They are stored under separate names to freeze both consumer views without pretending that a VFX layer exists.

## Bypass regression evidence

The candidate changes only `animations.hurt` plus the isolated skeleton hash. For the seven bypass animations below, all 11 Vulkan sample hashes match `hybrid_action_set_upstream` frame-for-frame—77 identical frame comparisons in total:

- `idle_loop`
- `low_health_loop`
- `relaxed_loop`
- `attack`
- `attack_heavy`
- `cast`
- `die`

The candidate reuses the four upstream atlas PNGs byte-for-byte. No page, region or attachment was added for `hurt`.

## Transition mixes and remaining risk

Static resource checks and real Spine `TrackEntry` probes both confirm:

| From | To | Mix |
| --- | --- | ---: |
| `idle_loop` | `hurt` | `0.03s` |
| `hurt` | `hurt` | `0.00s` |
| `hurt` | `idle_loop` | `0.10s` |
| `hurt` | `die` | `0.00s` |

The remaining risk is the inherited `hurt → hurt` zero mix. Repeated positive-damage `Hit` triggers can restart the performance at frame zero without blending, so extremely rapid consecutive hits may show an instantaneous re-trigger. This candidate did not introduce or change that behavior; it should remain an explicit gameplay observation item when the integrated runtime is tested.

## Evidence files

- `hurt-character-only-contact-sheet.png`: final body-only contact sheet.
- `hurt-composite-contact-sheet.png`: final all-slot contact sheet; byte-identical because non-body slots are empty.
- `summary.json`: complete two-candidate Vulkan report, including upstream comparison and per-frame hashes.
- `metrics.json`: frozen component decision, measurements and transition results.

This evaluation did not deploy the mod, launch the game, operate a stream, or invoke a paid image service.
