---
name: bilibili-live
description: Control this workspace's Bilibili broadcast and its daily 23:00-23:20 start and 11:00-11:20 stop windows through the local Bilibili Livehime app. Use when the user asks to start or stop the stream or maintain either daily window; starting also launches the complete sts2-ascend stack, while stopping affects only Bilibili streaming.
---

# Bilibili Live

Use the repository scripts as the only operational entrypoints. They use three fixed protected tasks for the elevated Livehime GUI plus limited daily start and stop coordinators; they never use a browser/private web API or OBS as the streaming transport.

## One-time prerequisite

The protected bridge must already be installed. Installation requires one explicit UAC approval while the user is at the PC:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Install-BilibiliLiveBridge.ps1
```

The installer copies only the Livehime module, fixed Start/Stop worker, fixed capture health watcher, daily start coordinator, and daily stop coordinator into `C:\Program Files\VivhiteBilibiliLiveBridge`, verifies all five SHA-256 hashes, and registers `\Vivhite\BilibiliLive-Start`, `\Vivhite\BilibiliLive-Stop`, and `\Vivhite\BilibiliLive-HealthWatch` for the current user with `Interactive` logon and `Highest` run level. It also registers `\Vivhite\BilibiliLive-DailyStart` and `\Vivhite\BilibiliLive-DailyStopWatch` with `Interactive` logon and `Limited` run level. Those coordinators may call only the public start and stop entrypoints, which delegate any GUI operation to the fixed protected tasks. Never silently replace this prerequisite with a UAC bypass, web API, direct scheduled GUI clicks, or third-party encoder.

Before causing the UAC prompt, finish all non-elevated validation: run the Bilibili script tests and generate read-only `New-ScheduledTaskTrigger` objects from the current daily-start and daily-stop schedules. For each trigger, the computed Beijing date, local date, UTC instant, one-minute repetition, 19-minute repetition duration, and generated trigger must identify the same upcoming boundary: 23:00 for start and 11:00 for stop. The installer must also read the local Livehime state before `Start-Process -Verb RunAs` and again in the elevated child: only exact `Idle` or `NotRunning` may proceed. `Streaming`, `Starting`, `Stopping`, `Unknown`, or any read failure must abort before UAC because display capture can broadcast the secure desktop or a frozen full-screen frame and trigger platform enforcement. Never install or repair the protected bridge during a broadcast.

After the elevated installer returns, verify all five installed hashes plus both daily triggers' full `StartBoundary` dates, one-minute/19-minute repetition contracts, and `Get-ScheduledTaskInfo.NextRunTime`; checking only the `23:00` or `11:00` clock portion is insufficient. One requested install attempt means one UAC prompt. If the user cancels it, do not automatically prompt again; report what remains unapplied and wait for a new explicit request.

## Start

For an explicit request such as "B站开播" or "开始直播", run from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-BilibiliLive.ps1
```

This command must finish the following sequence: call `Start-Agent.ps1 -SkipDeploy`, prove real gameplay, exactly identify the single IndexTTS/Quipper owner and require its bounded broadcast-coexistence status (3328 MiB CUDA allocator cap with staged CUDA BigVGAN), trigger the protected Livehime GUI task idempotently, then set the exact `SlayTheSpire2.exe` window to foreground and `TOPMOST`. Quipper cloned-voice narration remains online throughout the broadcast; normal start must never invoke the maintenance-only `/suspend` path. If `ASCEND-VISION` is already running, the entrypoint also reorders it above the game with a non-activating Win32 call; the viewer itself continues this z-order repair every 500ms without taking focus.

Livehime may retain a modal "stream ended"/violation result after a platform-enforced stop. The protected start path must dismiss only a positively identified known modal before validating the calibrated Start button. Test the complete four-arm X glyph by pixel contrast before OCR, and bound every WinRT OCR operation so a broken broker cannot hang Start. If the same modal reappears after the calibrated Start click while state stays `Idle`, or a calibrated click produces no Livehime state/log transition at all, treat it as a rejected or blocked start, perform at most one normal idle cold restart, and retry once; never spin or report success. OCR is optional because WinRT OCR is unavailable on some hosts, and the local glyph check must reject blank or one-diagonal images. A covered Start button that produces no streaming transition is a failed first attempt, not evidence that the platform accepted the broadcast.

The production Livehime scene intentionally uses display/monitor capture so the `ASCEND-VISION` overlay is included in the broadcast. Never replace it with game/window capture as an automated repair. The protected interactive worker must restore the game to foreground and `TOPMOST` after touching Livehime, then place `ASCEND-VISION` above the game without activating the viewer; the public entrypoint waits for that protected restoration to finish before reporting success.

The protected start path also forces synchronized recording off, conservatively removes only an exact duplicate of the Bilibili browser plugin while retaining one copy, cold-restarts an idle Livehime after stale display-capture evidence, and starts `BilibiliLive-HealthWatch`. The watcher keeps capture and gameplay evidence independent. For capture, it samples preview motion and new desktop-duplication failures: low preview motion alone is weak evidence because map, reward, and rest screens can be legitimately static during action reconciliation, so the three-sample fast-stop path still requires a concurrent desktop-duplication error burst; continuously uncorroborated low motion fails closed only after five minutes, and any fresh preview resets only these capture counters.

For gameplay, the watcher reads only the current local `.runtime/session.json`, matching dashboard snapshot, and localhost `/state`. Starting or resuming a broadcast still requires an already active, proven run. During an existing broadcast, however, `GAME_OVER`, `VICTORY`, `RUN_COMPLETE`, `MAIN_MENU`, and `CHARACTER_SELECT` are a normal automatic cross-run transition and start a two-phase proof gate instead of stopping immediately. Phase one allows up to 120 seconds from the first transition observation to obtain the first authoritative `applied` receipt from a new `run_id`. The game can briefly expose an empty, `UNKNOWN`, or `WAITING` screen while tearing down `GAME_OVER` and constructing the next menu/run; those observations are not progress and cannot reset either phase. The first new-run receipt replaces the baseline and starts a separate 30-second proof phase; only a second, different `decision_id` with a later terminal outcome timestamp in that same new run proves continuous play and returns the watcher to normal. Failure to obtain the first receipt within 120 seconds, or the second within 30 seconds after the first, stops with `cross_run_transition_timeout`. Repeated copies of the first receipt remain in the proof phase and never fall back to the normal stall clock. A non-running session, an active screen with `run_unknown`/no valid run, or `TITLE`/profile/history/credits screens outside the automatic transition remains an immediate hard failure. Outside a transition, empty/`UNKNOWN`/`WAITING` screens, transient API/dashboard read failures, temporary identity mismatch, or a moment with no executable action receive at most a 90-second grace period. A dashboard heartbeat, preview animation, or `state_version` is never action progress. Dashboard history rows do not themselves carry `run_id`; they are bound only to the API/dashboard-confirmed current run as a baseline and never count as progress on their own. All gameplay classifications and the final stop reason are written to the bounded capture-health audit log. The protected HealthWatch task and watcher process have no fixed 12-hour or 24-hour execution cap: singleton task semantics prevent duplicates, and the watcher exits when Livehime is no longer `Streaming`.

## Broadcast window patrol

`ASCEND-VISION` always keeps its own overlay TOPMOST with the existing approximately 500ms non-activating watchdog, regardless of broadcast state. Separately, its local broadcast patrol checks once every 60 seconds. That patrol may touch the game only when the exact local Livehime process and debug log both report actual `Streaming`; `Idle`, `Starting`, `Stopping`, `NotRunning`, `Unknown`, or any read error must perform no game-window mutation.

During an active patrol, resolve `game_exe` from the current stack session, match the visible game window by that full executable path, reassert the game with `SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE, ...)`, then reassert `ASCEND-VISION` second so it remains above the game. This patrol is deterministic local Win32/file logic: it must not call an LLM, consume tokens, use a browser/private Bilibili API, or steal foreground input.

## Stop

For an explicit request such as "B站下播" or "结束直播", run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-BilibiliLive.ps1
```

Stopping is deliberately narrow. Never substitute `Stop-Agent.ps1`, close the game, kill a port, or modify `sts2-ascend/.runtime`. Leave the training stack running and restore the single IndexTTS owner for the exact current session after Livehime is confirmed `Idle`; do not launch a second model while an owner is still present. Leave the game `TOPMOST`; if `ASCEND-VISION` is present, restore it above the game without activating it.

## Daily narrow stop

The limited `BilibiliLive-DailyStopWatch` task checks once per minute during the half-open Beijing-time window `[11:00, 11:20)`. Exact `Idle` or `NotRunning` is already successful. Only exact `Streaming` may invoke the public `Stop-BilibiliLive.ps1`; `Starting`, `Stopping`, `Unknown`, read errors, and an expired window perform no GUI action and may be retried by the next scheduled check. The coordinator must never call the protected worker or `Invoke-LivehimeStop` directly, and it must never stop the game, Brain, runner, dashboard, or Quipper. The public stop entrypoint remains responsible for the protected GUI task, `Idle` confirmation, IndexTTS restoration, and game/viewer z-order restoration. Its bounded audit log is `%LOCALAPPDATA%\VivhiteBilibiliLiveBridge\daily-stop-watch.log`.

## Daily fail-closed start

The limited `BilibiliLive-DailyStart` task checks once per minute during the half-open Beijing-time window `[23:00, 23:20)`. Each invocation validates the window and reads the local Livehime state before invoking only `Start-BilibiliLive.ps1`. A successful unified start writes the current window ID to a bounded local success marker; later checks may accept exact `Streaming` only when that marker matches the current window and the protected HealthWatch task is still `Running`. If the stream returns to `Idle`/`NotRunning` within the window, or HealthWatch is absent/not running, the next check must run the full unified preflight again. The coordinator must never call the protected worker directly, click Livehime itself, launch only part of the stack, use a private web API, or manufacture a success marker before `Streaming` is independently confirmed.

The public entrypoint remains the authority for daily starts: it starts or reuses the complete sts2-ascend stack, proves a real active run with two ordered applied actions and fresh dashboard/API evidence, validates the single Quipper owner and GPU limits, and only then asks the protected GUI task to start Livehime. Existing `Streaming` state is passed through the same validation so an empty or stalled stream is stopped rather than blessed. Any missing gameplay proof, unsafe transitional/unknown Livehime state, installation error, or window expiry fails closed. Its bounded audit log is `%LOCALAPPDATA%\VivhiteBilibiliLiveBridge\daily-start.log`.

## Reporting

Treat an already-streaming start and an already-idle stop as successful idempotent outcomes. Report script failures exactly enough to distinguish a missing protected task, an unrecognized Livehime state/layout, and a missing game window. Use `-WhatIf` only when the user asks for a dry run.
