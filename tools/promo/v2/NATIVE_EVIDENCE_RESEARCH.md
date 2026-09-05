# Native evidence interface review (T07/T10/T16/T18)

**Review date:** 2026-09-04

**Scope:** static repository/game metadata inspection only. No game, OBS,
Brain, `/action`, console, or recording process was started by this review.

## Finding

The current checkout has no **game-runtime HTTP/native exporter** that emits a
complete `game_ui_pointer` + `state.before` + `action.receipt` + `state.after`
chain. A recorder-side route is still possible: an operator runner can
persist a `live-receipt` while it performs real game-window pointer calls and
captures truthful before/after observations, then a reviewer can bind those
records to the closed CFR source. T11/a02 is the existing accepted precedent
(`capture/takes/T11/a02/live-receipt.json`). The capture helper in this
directory intentionally stops short of that promotion step: it records
operator marks, screenshots, process identity, raw-file metadata, and an
append-only log window, but never emits a strict action receipt.

## Existing runtime interfaces

| Source | What exists | Why it is insufficient for strict v2 |
| --- | --- | --- |
| `sts2-ascend/third_party/STS2-Agent/STS2AIAgent/Server/Router.cs:57-83` | `GET /state` and `GET /actions/available` | State payload has no native pointer edge, encoded-frame anchor, or action receipt. A recorder may still save a read-only `/state` response as a truthful observation. |
| `Router.cs:117-141` | `/events/stream` and `POST /action` | Stream is coarse state transitions; `POST /action` is a programmatic API path, not `game_ui_pointer`. |
| `Game/GameStateService.cs:61-115,6083-6097` | State payload (`state_version=13`) | No pointer coordinates, monotonic input times, settled action ID, or observation sequence. |
| `Game/GameActionService.cs:260-350,5014-5046` | API `play_card` calls `TryManualPlay`; response has `action/status/stable/message/state` | This is direct/API execution and cannot be relabelled as a mouse action; no pointer down/up or native settlement receipt. |
| `Server/GameEventService.cs:9-11,148-170,310-319` | 120 ms state polling, timestamped event envelopes | Events omit pointer/action identity, can miss intermediate transitions, and use a bounded drop-oldest queue. |
| `godot.log` | Lines such as `Player 1 playing card ...` | No per-line timestamp or pointer origin; current log also mixes `DevConsole` staged setup. It is order-only corroboration. |
| `Vivhite/VivhiteCode/PromoCaptureSurface.cs` | Capture-only hiding of native debug labels | No instrumentation or evidence export. |

The game XML documents possible future patch points—
`NClickableControl.HandleMousePress/HandleMouseRelease/_GuiInput`
(`sts2.xml:17705-17755`) and
`NCardPlayQueue.OnLocalCardPlayed(PlayCardAction, NCardHolder, CardModel)`
(`sts2.xml:3746-3753`)—but does not provide an existing exporter. Adding such
instrumentation would require a new mod patch, rebuild, and real-runtime
validation; it is not evidence for an existing take.

## Strict v2 implications

`tools/promo/vivhite_promo/action_evidence_v2.py` requires, among other fields:

* `input_origin = "game_ui_pointer"`;
* completed/stable/applied delivery and `settled = true`;
* exact pointer down/up/settled frames and monotonic times;
* a numeric `observation_seq` with `before < receipt <= after`;
* hashes binding the three distinct state/receipt artifacts.

Therefore a screenshot, stopwatch estimate, API `/action` response, or log line
cannot be promoted to a native receipt. Existing T07/T10/T16/T18 video-only
attempts must remain failed-reference material; no old-video retrofit is valid.

## Shortest honest protocol for a new take

1. Create a fresh attempt and preserve one continuous CFR-60 raw recording.
2. Before recording, complete all controlled setup and label it
   `staged_setup`; do not include setup commands in the display span.
3. In the same PowerShell process, capture game/OBS PID, executable, and start
   time. Mark recording start and file-close boundaries.
4. Capture a full-HUD visual observation before the action. Perform the real
   game-window mouse down/up (or card drag and target release), then mark each
   edge immediately after the native call. Do not call `/action`, Brain, or the
   console for the formal action.
5. Keep the game at 1x until native settlement is visible; capture the after
   observation only after the final HUD/result state is stable.
6. Copy the append-only `godot.log` window for corroboration, never as a
   pointer/receipt source. After OBS closes, inspect the immutable CFR source
   frame-by-frame and bind zero-based frames to the marks.
7. Persist a recorder-side `live-receipt` containing those real pointer marks,
   process identity, and truthful before/after observations. If using
   read-only `/state`, save the raw responses and document the local
   observation sequence; do not invent a game-provided sequence or receipt.
   Only after the raw source is closed should a reviewer create and validate
   the strict v2 sidecar. If any triad member is missing, close the bundle as
   evidence-only and preserve it for hand-off.

`promo_capture_evidence_helper.ps1` implements the safe capture-time portion
of steps 1, 3–6. Its manifest always leaves
`production_eligible=false`, `strict_sidecar_emitted=false`, and
`manual_review_required=true`.

## Explicit blocker / future route

If recorder-side marks/state are not sufficient for a particular action, a
future capture-only native instrumentation layer could:

1. records real `NClickableControl` pointer edges and target/card identity;
2. observes the corresponding `PlayCardAction`/end-turn action lifecycle and
   emits a settled receipt only after the native queue completes;
3. snapshots the same game state on a monotonic observation sequence; and
4. persists an immutable, session/process-bound event stream that can be
   joined to the CFR recording.

Until that layer is built and validated on a fresh run, the only honest claim
for a new recording is visual/evidence-only, not strict production eligibility.
