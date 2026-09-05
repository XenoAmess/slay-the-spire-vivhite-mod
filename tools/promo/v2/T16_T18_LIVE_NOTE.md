# T16/T18 live capture handoff note (2026-09-03)

This note is an append-only diagnostic handoff. It does not promote any media to
production and does not replace the capture runbook.

## T16/a01 disposition

- Raw: `G:/OBS_VIDEOS/vivhite-director-v2/run-20260903-0012/T16/a01/2026-09-03 17-21-33.mkv`
- OBS start/stop: `17:21:34.088` / `17:29:19.270`
- ffprobe duration: `464.874000` seconds
- Format: 1920x1080, H.264, 60 FPS, AAC 48 kHz stereo
- Bytes: `204637583`
- SHA-256: `39FB635E29E21A3A5FF31A9AFE2518F825C1E008F2B683EEB4A2A7856268EBE2`
- Read-only 30-second contact-sheet review: every sampled frame is identical;
  Ritual tooltip remains hovered, HP is 82/82, energy is 6/3, four Slimes remain,
  and no card click, end-turn transition, or resolved state change appears.

Disposition: `rejected_static_no_action`. Keep raw, OBS log, and contact-sheet
diagnostic. Do not reference this attempt from a production row or EDL. Start T16
from a fresh attempt directory (`a02` or later), with the dynamic card/target
coordinates verified immediately before the recording mark.

The active OBS profile was still pointing at the `T16/a01` directory after this
take. Before a new attempt, close OBS before applying any profile-path change, set
the output path to the new exact attempt directory, reopen OBS, and verify the
path in the active profile/log. Never let a new take append to or overwrite this
failed raw.

## Next T16 execution checklist

1. Close any open tooltip and move the cursor to an empty area.
2. Ensure setup is complete before the recording mark; preserve a live target and
   enough player HP/energy.
3. Mark the clean take only after the 2-second preroll is visible.
4. Hover Ritual 1.5-2 seconds, click it, and wait for phase-0 power to settle.
5. Click the end-turn control (`target.kind=end_turn_button`, `id=end_turn`) and
   retain the complete transition to phase 1.
6. Hover and click Luminous Projection, then select a high-HP live Slime. Keep the
   entire action-to-settlement chain and 3-4 seconds of result HUD.
7. Stop promptly; record raw path, bytes, SHA-256, frame count, span, and all
   before/receipt/after/event-sequence refs in the progress document.

## Next T18 execution checklist

Use the T18 recipe in `T16_T18_CAPTURE_RECIPE.md`. Before the mark, verify UFT is
active, Margin is positive, player HP is below max by at least the runtime healing
divisor, energy is sufficient, the target has no blocking effect, and both required
cards are visible. The formal chain must remain contiguous:

`Closed Domain Mapping -> Margin/Cough settlement -> Trichromatic Waltz -> three
hits -> actual healing -> Margin return`.

Numeric claims must come from the current tooltip/HUD and receipts, not this note.
