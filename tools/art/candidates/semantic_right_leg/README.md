# Semantic right-leg research candidate

This isolated candidate audits the screen-right / near-leg semantic group. It
does not modify the runtime skin and makes no paid image request.

The builder SourceOver-composites the untouched `0083` thigh, `0100` lower
leg, and direction-blocked `0064` boot at setup, the authored `+82°` knee
extreme, and the authored `-18°` ankle extreme. It also compares the frozen
three-piece order with a two-piece topology in which the lower leg and boot
would be one newly generated attachment and the ankle degree of freedom is
removed.

Run from the repository root:

```powershell
$godot = 'C:\Users\xenoa\AppData\Local\Temp\opencode\godot\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_mono_win64.exe'
& $godot --headless --path tools/art --script res://candidates/semantic_right_leg/build_semantic_right_leg_candidate.gd -- build-semantic-right-leg-candidate
& $godot --headless --path tools/art --script res://candidates/semantic_right_leg/validate_semantic_right_leg_candidate.gd -- validate-semantic-right-leg-candidate
```

The PNGs under `Vivhite/tools/candidates/semantic_right_leg/` are opaque
diagnostic contact sheets, not spritesheet or atlas inputs. In particular,
`0100 + 0064` must never be flattened into runtime art; a production two-piece
route requires a new native-transparent lower-leg/boot union after its topology
is approved.
