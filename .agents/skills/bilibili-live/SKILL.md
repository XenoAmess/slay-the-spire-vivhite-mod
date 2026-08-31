---
name: bilibili-live
description: Control this workspace's Bilibili broadcast and its protected daily stop watch through the local Bilibili Livehime app. Use when the user asks to start or stop the stream or maintain the 16:20 Beijing-time safety stop; starting also launches the complete sts2-ascend stack, while stopping affects only Bilibili streaming.
---

# Bilibili Live

Use the repository scripts as the only operational entrypoints. They use three fixed, protected scheduled tasks that interact with the elevated Livehime GUI; they never use a browser/private web API or OBS as the streaming transport.

## One-time prerequisite

The protected bridge must already be installed. Installation requires one explicit UAC approval while the user is at the PC:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Install-BilibiliLiveBridge.ps1
```

The installer copies only the Livehime module, fixed Start/Stop worker, and fixed daily stop-watch worker into `C:\Program Files\VivhiteBilibiliLiveBridge`, verifies SHA-256 equality, and registers `\Vivhite\BilibiliLive-Start`, `\Vivhite\BilibiliLive-Stop`, and `\Vivhite\BilibiliLive-DailyStopWatch` for the current user with `Interactive` logon and `Highest` run level. Never silently replace this prerequisite with a UAC bypass, web API, or third-party encoder.

## Start

For an explicit request such as "B站开播" or "开始直播", run from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-BilibiliLive.ps1
```

This command must finish the following sequence: call `Start-Agent.ps1 -SkipDeploy`, trigger the protected Livehime GUI task idempotently, then set the exact `SlayTheSpire2.exe` window to foreground and `TOPMOST`. If `ASCEND-VISION` is already running, the entrypoint also reorders it above the game with a non-activating Win32 call; the viewer itself continues this z-order repair every 500ms without taking focus. If Bilibili start fails, report the error and leave the already-started stack running; do not roll it back.

## Broadcast window patrol

`ASCEND-VISION` always keeps its own overlay TOPMOST with the existing approximately 500ms non-activating watchdog, regardless of broadcast state. Separately, its local broadcast patrol checks once every 60 seconds. That patrol may touch the game only when the exact local Livehime process and debug log both report actual `Streaming`; `Idle`, `Starting`, `Stopping`, `NotRunning`, `Unknown`, or any read error must perform no game-window mutation.

During an active patrol, resolve `game_exe` from the current stack session, match the visible game window by that full executable path, reassert the game with `SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE, ...)`, then reassert `ASCEND-VISION` second so it remains above the game. This patrol is deterministic local Win32/file logic: it must not call an LLM, consume tokens, use a browser/private Bilibili API, or steal foreground input.

## Stop

For an explicit request such as "B站下播" or "结束直播", run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-BilibiliLive.ps1
```

Stopping is deliberately narrow. Never substitute `Stop-Agent.ps1`, close the game, stop a process, kill a port, or modify `sts2-ascend/.runtime`. Leave every service running and leave the game `TOPMOST`; if `ASCEND-VISION` is present, restore it above the game without activating it.

## Daily safety stop

The protected `BilibiliLive-DailyStopWatch` task starts a fresh one-shot worker in each Beijing-time minute slot from 16:20 through 16:39: exactly 20 checks in the half-open interval `[16:20, 16:40)`. Each worker validates the Beijing window at startup, again under the shared GUI mutex, and immediately before the stop flow; the stop function also rejects a click once the window deadline has passed. Separate one-shot launches make the next minute independent if endpoint protection blocks or terminates one PowerShell instance.

Each check reads the local Livehime process and debug-log state. Only exact `Streaming` may call the same `Invoke-LivehimeStop` GUI flow; `Idle`, `Starting`, `Stopping`, `NotRunning`, `Unknown`, or any read error must not click anything. Later scheduled checks continue after a successful stop so a stream restarted inside the window is stopped again. A failed stop is recorded and may retry at the next minute slot. Manual Start/Stop and the daily worker share a named mutex covering both the Livehime action and the subsequent game/viewer z-order restoration; a busy daily check skips its click and lets the next minute retry.

This watch uses the fixed elevated local worker, not an LLM, browser, private Bilibili endpoint, or third-party encoder. The installer passes the exact workspace project root to the protected copy only so it can identify the existing ASCEND-VISION process after either a successful or failed stop attempt. It consumes no tokens and never stops the game, sts2-ascend, TTS, the dashboard, or any other service. Its bounded audit log is `%ProgramData%\VivhiteBilibiliLiveBridge\daily-stop-watch.log`.

## Reporting

Treat an already-streaming start and an already-idle stop as successful idempotent outcomes. Report script failures exactly enough to distinguish a missing protected task, an unrecognized Livehime state/layout, and a missing game window. Use `-WhatIf` only when the user asks for a dry run.
