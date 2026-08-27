"""Idempotent launcher/supervisor for the ASCEND-VISION dashboard.

The dashboard is intentionally detached from the brain process: an LLM review
or a brain hot restart must not make the broadcast overlay disappear.  A tiny
daemon thread in each brain generation checks the existing heartbeat lock and
restarts the viewer when necessary.  The viewer itself remains the authority
for single-instance locking and stack shutdown.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from lifecycle import STACK_ROOT, stop_requested, viewer_launch_disabled, wait_for_stop

BASE_DIR = STACK_ROOT
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
CONFIG_PATH = BASE_DIR / "brain" / "config.json"
VIEWER_PATH = BASE_DIR / "brain" / "review_viewer.py"
LOCK_FILE = KNOWLEDGE_DIR / "viewer.lock"
LOCK_FRESH_SEC = 15.0

_SUPERVISOR_LOCK = threading.Lock()
_SUPERVISOR: "DashboardSupervisor | None" = None


def resolve_viewer_config(config: dict | None = None) -> dict:
    """Resolve top-level ``viewer`` settings with the legacy LLM fallback.

    ``llm_review`` historically passes only its own subsection, so a mapping
    containing ``viewer_enabled`` is accepted as well as the complete config.
    """
    raw = config
    if raw is None:
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    viewer = raw.get("viewer")
    llm = raw.get("llm")
    if not isinstance(viewer, dict):
        viewer = {}
    if not isinstance(llm, dict):
        llm = raw if "viewer_enabled" in raw else {}
    enabled = viewer.get("enabled")
    if enabled is None:
        enabled = llm.get("viewer_enabled", True)
    return {
        "enabled": bool(enabled),
        "supervise_interval_sec": max(
            0.5, float(viewer.get("supervise_interval_sec", 2.0) or 2.0)
        ),
    }


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            kernel = ctypes.windll.kernel32
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                image = ctypes.create_unicode_buffer(512)
                size = ctypes.c_ulong(len(image))
                kernel.QueryFullProcessImageNameW.argtypes = [
                    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p,
                    ctypes.POINTER(ctypes.c_ulong),
                ]
                if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
                    return False
                return "python" in Path(image.value).name.lower()
            finally:
                kernel.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, TypeError):
        return False
    except Exception:
        return False


def viewer_is_running(now: float | None = None) -> bool:
    """Check the viewer heartbeat lock without mutating it."""
    try:
        if (now or time.time()) - LOCK_FILE.stat().st_mtime >= LOCK_FRESH_SEC:
            return False
        pid = int(LOCK_FILE.read_text(encoding="utf-8").strip() or "0")
        return _pid_alive(pid)
    except (OSError, ValueError):
        return False


def ensure_dashboard_viewer(
    config: dict | None = None,
    log: Callable[[str], None] = print,
) -> bool:
    """Ensure one detached viewer exists; never raise into the game loop."""
    cfg = resolve_viewer_config(config)
    if (not cfg["enabled"] or viewer_launch_disabled()
            or stop_requested() or not VIEWER_PATH.exists()):
        return False
    if viewer_is_running():
        return True
    try:
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        with (KNOWLEDGE_DIR / "viewer_out.log").open("ab") as out_f, \
                (KNOWLEDGE_DIR / "viewer_err.log").open("ab") as err_f:
            subprocess.Popen(
                [sys.executable, "-u", str(VIEWER_PATH)],
                cwd=str(BASE_DIR),
                stdin=subprocess.DEVNULL,
                stdout=out_f,
                stderr=err_f,
                creationflags=creationflags,
                # A viewer launched from an OpenCode/selfcheck process must not
                # inherit that tool's capture pipe.  The old False value let the
                # detached viewer keep the pipe alive after selfcheck exited, so
                # OpenCode waited forever for EOF with its tool stuck "running".
                close_fds=True,
            )
        log("[viewer] ASCEND-VISION 已拉起")
        return True
    except Exception as exc:
        try:
            log(f"[viewer] 拉起失败（不影响游玩）：{exc}")
        except Exception:
            pass
        return False


class DashboardSupervisor:
    """Process-local, idempotent self-heal loop for the detached viewer."""

    def __init__(self, config: dict | None, log: Callable[[str], None]) -> None:
        self.config = config
        self.log = log
        self.interval = resolve_viewer_config(config)["supervise_interval_sec"]
        self.thread = threading.Thread(
            target=self._run, name="ascend-dashboard-supervisor", daemon=True
        )
        self.thread.start()

    def _run(self) -> None:
        while not stop_requested():
            ensure_dashboard_viewer(self.config, self.log)
            if wait_for_stop(self.interval):
                break


def start_dashboard_supervisor(
    config: dict | None = None,
    log: Callable[[str], None] = print,
) -> DashboardSupervisor | None:
    """Start the process-wide dashboard supervisor once.

    Call this after the brain config is loaded.  Returning immediately keeps
    viewer startup completely off the decision-loop critical path.
    """
    global _SUPERVISOR
    if not resolve_viewer_config(config)["enabled"]:
        return None
    with _SUPERVISOR_LOCK:
        if _SUPERVISOR is None or not _SUPERVISOR.thread.is_alive():
            _SUPERVISOR = DashboardSupervisor(config, log)
        return _SUPERVISOR
