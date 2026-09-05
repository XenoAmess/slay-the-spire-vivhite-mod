# Capture-time evidence helper (T16/T18)

`promo_capture_evidence_helper.ps1` is a small, capture-time hand-off tool for
new Vivhite takes. It is deliberately evidence-only. It does not start or stop
the game, OBS, the recorder, Brain, a console, or an HTTP action endpoint, and
it never emits `vivhite-promo-action-evidence` or any other strict receipt.

The helper must be dot-sourced by the same PowerShell process that performs the
real `GameTest` pointer calls. A mark is meaningful only when the operator has
just completed the corresponding native game-UI input. A screenshot is a visual
observation, not a runtime state snapshot. The final archive step must still
obtain a genuine `state.before` / `action.receipt` / `state.after` chain from
the current game run and manually bind source frames.

## What is captured

Each fresh attempt directory contains:

* `capture-evidence.partial.json`: atomically checkpointed hand-off manifest;
* `events/000001-*.json`: immutable operator and recording-boundary marks;
* `screenshots/*.png`: atomically moved `Save-Screenshot` images, each labelled
  `state.before`, `state.after`, `phase0`, `phase1`, or observation-only;
* `logs/game-log-window.txt`: bytes appended to `godot.log` after the baseline,
  with a prefix hash check. The log is corroborative order-only evidence; it
  has no trustworthy per-line timestamp in this tool;
* `events.ndjson` and `capture-evidence.json` after finalization.

The manifest records game and OBS PID, executable path, start time, and a
portable process identity in the strict-v2-compatible form
`<exe>-<pid>-<start-utc-with-colons-replaced>`. It also records a capture
identity (`session_id`, `game_run_id`, `run_id`, `take_id`, `attempt_id`, and
provisional `source_video_artifact_id`). The manifest also records
Stopwatch timestamps and a candidate `round(seconds * 60)` source frame for
each event. Candidate frames are explicitly non-authoritative. Only
`Set-PromoCaptureRawFrameAnchor` after human inspection of the immutable raw
source can fill `verified_source_frame`; this still does not create a strict
receipt.

## Start a new attempt

Use a new empty directory for every attempt. Do not point the helper at an old
take, an old video, or a directory containing a previous partial/final
manifest. The source video id is a lineage label, not permission to retrofit
that video.

```powershell
Import-Module .\tools\test\GameTest.psm1
. .\tools\promo\v2\promo_capture_evidence_helper.ps1

$evidence = New-PromoCaptureEvidenceSession `
  -OutputDirectory .\tools\promo\runs\<new-run>\capture\takes\T16\a01\evidence `
  -SessionId <32-char-session-id> `
  -RunId run-<new-run> `
  -GameRunId <native-game-run-id> `
  -TakeId T16 `
  -AttemptId a01 `
  -SourceVideoArtifactId raw-<new-video-id> `
  -RawArtifactPath .\tools\promo\runs\<new-run>\raw\T16-a01.mkv `
  -GameLogPath "$env:APPDATA\SlayTheSpire2\logs\godot.log" `
  -GameProcessName SlayTheSpire2 `
  -ObsProcessName obs64
```

If more than one matching process exists, pass `-GameProcessId` and
`-ObsProcessId`. The helper fails closed when it cannot read a visible window,
executable path, or start time. A failed constructor must not be worked around
by inventing an identity.

Before and after each real boundary, call the helper in the same process:

```powershell
# OBS/recorder controls are outside this helper. Mark immediately around them.
Set-PromoCaptureRecordingBoundary -Session $evidence -Boundary start_request
# operator observes that the raw file is actually being written:
Set-PromoCaptureRecordingBoundary -Session $evidence -Boundary started_observed

# Capture full HUD before the first real card input.
$before = Save-PromoCaptureEvidenceScreenshot -Session $evidence `
  -Role state.before -Label T16-before

# Hover and perform the actual native game pointer operation.  Mark each
# edge immediately after the native call; the helper itself never clicks.
Move-Mouse -X 1430 -Y 955
Start-Sleep -Milliseconds 1500
[GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
Add-PromoCaptureEvidenceMark -Session $evidence -Label T16-ritual-click `
  -Kind pointer_down -X 1430 -Y 955 -TargetKind card `
  -TargetId VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL `
  -ActionId T16-ritual-01
[GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
Add-PromoCaptureEvidenceMark -Session $evidence -Label T16-ritual-up `
  -Kind pointer_up -X 1430 -Y 955 -TargetKind card `
  -TargetId VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL `
  -ActionId T16-ritual-01

# Leave the complete 1x resolution visible, then observe the result.
Start-Sleep -Seconds 3
$phase0 = Save-PromoCaptureEvidenceScreenshot -Session $evidence `
  -Role phase0 -Label T16-phase0
```

The example’s coordinates are only placeholders. Recalculate the current
window/card hitbox before the take. The helper never sends the click; the
operator’s `Invoke-MouseClick` (or equivalent native call) remains the input
provenance.

## Recommended T16 sequence

For `T16` (绯彩积分 / Crimson Transformation Ritual), keep setup outside the
formal take and mark it as `staged_setup` in the run record. Inside one
continuous source recording, use this order:

1. `start_request`, `started_observed`, then a full-HUD `state.before` image.
2. Real ritual hover, pointer down/up marks, and the complete phase-0 result;
   save `phase0` only after the result settles.
3. Real end-turn hover and pointer marks; save `phase1` after the next hand and
   power state are stable.
4. Save a second full-HUD observation immediately before the attack, without
   changing the state. This image may later be reused as the strict
   `state.after`/next `state.before` artifact only after a human verifies the
   exact frame and state payload.
5. Real `Luminous Projection` card and target pointer marks, preserving the
   uninterrupted 1x resolution and 3–4 second result tail. Save `state.after`
   as a visual observation.
6. Mark `stop_request` and then `file_closed_observed` only after the raw file
   is closed. Call `Finalize-PromoCaptureEvidenceSession`.

If phase 0, phase 1, or the target hand is not visibly present, stop and create
a new attempt. Do not insert a console card, splice an old video, or fill the
missing receipt from `godot.log`.

## Recommended T18 sequence

For `T18` (Unified Field Theory), use a separate fresh attempt directory:

1. Mark recording start and capture the full-HUD `state.before` while UFT,
   Margin, missing HP, energy, both cards, and a live target are visible.
2. Perform the real Closed Domain Mapping pointer operation; mark down/up and
   capture `state.after-cough` only after Margin payment, Drain increase, and
   the resulting HUD settle.
3. Hover and play Trichromatic Waltz, mark both the card click and target
   selection, and preserve all three native hits at 1x. Capture `state.after`
   after the single aggregated healing and Margin return are visible.
4. Mark recording stop/file close and finalize the bundle.

If a target dies too early, the player is full health, or the three hits cannot
be seen as one uninterrupted action, preserve the partial bundle and retry with
a new `attempt_id`. Do not claim the intended mechanism from a visually similar
old take.

## Manual frame binding and hand-off

After the raw MKV is closed, a reviewer may inspect it with a frame-accurate
tool and bind an event to a screenshot that is actually visible in that source:

```powershell
Set-PromoCaptureRawFrameAnchor -Session $evidence `
  -EventLabel T16-ritual-click `
  -SourceZeroBasedFrame 1234 `
  -EvidencePath $before.artifact.path `
  -VerificationNote 'Reviewed immutable CFR source; frame shows the marked HUD and pointer result.'
```

The frame number must come from the closed source, not from the helper’s
Stopwatch candidate. The manifest remains `production_eligible=false`,
`strict_sidecar_emitted=false`, and `manual_review_required=true` by design.
The reviewer then creates the normal strict v2 sidecars using the native state
and action receipt, with the same capture identity and verified frame order.

If PowerShell or OBS dies, leave `capture-evidence.partial.json` and the
immutable event files in place. Send the whole attempt directory and its raw
artifact path to the next operator. Never reuse that directory or overwrite a
partial manifest; continue with a new attempt and link the prior attempt in the
progress document. A missing/rotated log is recorded as unavailable and does
not become a fabricated state or action receipt.

## Recording frame bounds helper

After `file_closed_observed`, complete CFR bounds can be recorded without
editing the manifest by hand:

```powershell
Set-PromoCaptureRecordingFrameBounds -Session $evidence `
  -StartZeroBasedFrame 300 -EndExclusiveFrame 1500 `
  -VerificationNote 'Reviewed the closed CFR-60 source; first/last frames are clean HUD boundaries.' `
  -StartEvidencePath $before.artifact.path -EndEvidencePath $phase0.artifact.path
```

The function requires an existing closed raw artifact and remains
human-verified/non-authoritative until the normal production binder validates
the full native triad.

## Self-test (does not start game or OBS)

The helper was syntax-checked under Windows PowerShell 5.1 and exercised with a
temporary fake session for atomic JSON, append-only log copying, pointer marks,
non-colliding screenshots, manual frame anchors, and finalization. The fake
`Save-Screenshot` writes bytes only; it is not a game capture. Run the same
checks after modifying the helper, and keep all temporary output outside the
repository’s production runs.
