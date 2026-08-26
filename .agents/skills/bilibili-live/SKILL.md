---
name: bilibili-live
description: Control this workspace's Bilibili broadcast through the local Bilibili Livehime app. Use when the user explicitly asks to start or stop the Bilibili stream; starting also launches the complete sts2-ascend stack and makes Slay the Spire 2 TOPMOST, while stopping affects only Bilibili streaming.
---

# Bilibili Live

Use the repository scripts as the only operational entrypoints. They trigger two fixed, protected scheduled tasks that interact with the elevated Livehime GUI; they never use a browser/private web API or OBS as the streaming transport.

## One-time prerequisite

The protected bridge must already be installed. Installation requires one explicit UAC approval while the user is at the PC:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Install-BilibiliLiveBridge.ps1
```

The installer copies only the Livehime module and fixed Start/Stop worker into `C:\Program Files\VivhiteBilibiliLiveBridge`, verifies SHA-256 equality, and registers `\Vivhite\BilibiliLive-Start` plus `\Vivhite\BilibiliLive-Stop` for the current user with `Interactive` logon and `Highest` run level. Never silently replace this prerequisite with a UAC bypass, web API, or third-party encoder.

## Start

For an explicit request such as "B站开播" or "开始直播", run from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-BilibiliLive.ps1
```

This command must finish the following sequence: call `Start-Agent.ps1 -SkipDeploy`, trigger the protected Livehime GUI task idempotently, then set the exact `SlayTheSpire2.exe` window to foreground and `TOPMOST`. If `ASCEND-VISION` is already running, the entrypoint also reorders it above the game with a non-activating Win32 call; the viewer itself continues this z-order repair every 500ms without taking focus. If Bilibili start fails, report the error and leave the already-started stack running; do not roll it back.

## Stop

For an explicit request such as "B站下播" or "结束直播", run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-BilibiliLive.ps1
```

Stopping is deliberately narrow. Never substitute `Stop-Agent.ps1`, close the game, stop a process, kill a port, or modify `sts2-ascend/.runtime`. Leave every service running and leave the game `TOPMOST`; if `ASCEND-VISION` is present, restore it above the game without activating it.

## Reporting

Treat an already-streaming start and an already-idle stop as successful idempotent outcomes. Report script failures exactly enough to distinguish a missing protected task, an unrecognized Livehime state/layout, and a missing game window. Use `-WhatIf` only when the user asks for a dry run.
