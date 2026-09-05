# T10 clean capture recipe — Act 2/3 campfire

This is an append-only operational supplement for run `run-20260903T0012-director-v2-a1`.
It exists because T10/a01 and T10/a02 are preserved reference failures: both begin at an
Act 1 `REST_SITE`, and neither contains the required map entry plus return-to-map feedback.
Do not edit or re-use those attempts as production footage.

## Goal and acceptance chain

The single independent source must show, in this order, with game UI input at 1×:

`clean Act 2/3 MAP → hover a reachable RestSite → click RestSite → complete campfire animation → click REST/休息 → actual HP increase and extinguished fire → click Proceed/前进 → clean MAP`

Keep approximately 2 s clean preroll before the first formal input and 3–4 s after the
map return. The player must be visibly injured before REST (`current_hp < max_hp`). The
map, campfire, rest result, and return must all be from the same raw MKV and the same game
process. A map-to-rest transition may contain the native loading fade; never cut or hide it
inside the formal action span. If the transition is black, record its exact frame interval
and bind the owner span around it rather than silently treating black as a HUD result.

## Setup (before the recording mark only)

1. Preserve the current clean capture process and profile. Verify the game is the direct
   `SlayTheSpire2.exe` process with `VIVHITE_PROMO_CAPTURE=1`, Vulkan, and no overlay/debug
   surface. Configure OBS to a new attempt directory, never an existing raw path.
2. In a normal in-game state, open the development console only for staging. The shortest
   known route is:

   ```text
   act 2                 # use act 3 instead if Act 2 map is unsuitable
   travel                # wait until the selected act map is fully rendered
   damage 30 0           # only if the player is not visibly injured; adjust conservatively
   ```

   `act`/`travel`/`damage` are setup operations, not formal footage. Do not use `kill`.
   If the command leaves the player in a room rather than on a map, return to a fully
   rendered map before marking; do not record a direct `room REST_SITE` jump.
3. Close the console and every setup surface. Wait for the map to settle and confirm the
   HUD, Act/floor context, player HP, and reachable-node rings are visible. Capture a clean
   checkpoint screenshot. The screenshot is a recovery aid, not a substitute for the raw
   take or action receipt.

## Dynamic map-node identification (never hard-code an old coordinate)

Map coordinates vary by act, seed, scroll, and camera position. Identify the target at the
last clean frame immediately before the click:

1. Use the legend on the right side to identify the red campfire glyph (`RestSite`). Only
   consider a glyph connected to the current node by a visible dotted route and surrounded
   by the game's reachable/highlight ring.
2. Move the in-game hover over the candidate. Keep the hover long enough for the native
   tooltip or node highlight to appear; reject a node if the tooltip says it is not
   reachable or if the route is not connected.
3. Record the exact client-pixel point and observed hitbox in the live receipt. Also record
   the visible act/floor and, after the click, the runtime log line
   `Player vote changed ... coord: (row,col)` when available. The current T07 log's
   `(4,15)` is an Act 1 coordinate and must not be copied as an Act 2/3 identifier.
4. Use a descriptive portable target ID such as
   `act2-map-coord-<row>-<col>` only after the screenshot and log agree. If the runtime
   exposes no stable semantic node ID, retain the literal coordinate, screenshot hash,
   client point, act, floor, and a note that the ID is coordinate-scoped; do not invent a
   global canonical ID.
5. Before clicking, move away and back once if needed to re-check the same glyph/bbox. The
   receipt pointer must lie inside the observed hitbox. Do not use a system cursor in the
   captured surface; the pointer is evidence metadata only.

This procedure is intentionally visual/runtime-bound. A coordinate from an earlier map
shot (for example `(1100,535)` or `(4,15)`) is only a starting hint, never a production
target.

## Formal recording sequence

After the mark and 2 s preroll:

1. Hover the identified RestSite for about 1.5–2 s and retain the full map HUD.
2. Click the RestSite once. Hold the source continuously until the room is stable. In the
   current build the Act 2 campfire animation is expected to use `hive_loop` (about 3.6 s);
   Act 3 commonly uses `glory_loop` (about 4.4 s). These are timing hints, not reasons to
   cut or accelerate the take.
3. Leave a complete readable campfire/character animation, then hover REST/休息 for
   1.5–2 s and click it. Wait until the native healing number and HUD settle; verify
   `after_hp > before_hp` and the fire state changes.
4. Click Proceed/前进 once, wait through the native return transition, and hold the clean
   map for 3–4 s. Stop OBS only after this hold.

Immediately after stopping, preserve the raw file, OBS log, source probe, decoded-frame
count, blackdetect output, clean screenshots, and the live receipt. Generate a CFR
derivative only as a new file; never overwrite the raw MKV.

## Evidence checklist

At minimum create separate immutable artifacts for:

* `T10-frame-begin` and `T10-frame-end`;
* `T10-state-before` (Act 2/3 MAP, injured HP, reachable RestSite);
* campfire-entry receipt (pointer, target coordinate, act/floor, runtime coordinate/log);
* rest receipt (real REST click and settled HP delta);
* `T10-state-after` (rest result, actual healing, fire state, map-return status);
* return-map receipt and event sequence;
* source/CFR probes, media lineage, process identities, and raw SHA-256.

For each UI action sidecar keep the ordering
`state.before.frame < pointer.down < pointer.up <= settled.frame < state.after.frame`.
Use the exact observed HUD values from this attempt; do not copy the Act 1 values from
T10/a02 (`52/82 → 76/82`).

## Rejection and interruption rules

Reject and preserve the attempt if it starts on `REST_SITE`, uses a direct room jump,
shows Act 1, has no reachable-map click, has no actual HP increase, ends before the map
returns, or contains a forbidden overlay/debug surface. If recording or the game stops,
leave the raw attempt untouched, append the failure reason to the progress document, and
resume by reading the latest checkpoint, process identities, and OBS output path. Start a
new attempt ID for every retry; never splice setup or a second run into this source.
