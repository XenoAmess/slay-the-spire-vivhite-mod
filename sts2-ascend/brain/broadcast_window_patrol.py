"""Token-free Bilibili broadcast window-layer patrol.

The active state comes from the local Livehime process and debug log.  During
an actual stream, the existing ASCEND-VISION process periodically restores the
exact game window to the TOPMOST band and then restores itself above the game.
No LLM, network request, browser API, or input-focus mutation is involved.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import time
from typing import Callable

from lifecycle import RUNTIME_DIR
from window_layers import (find_window_for_executable, is_topmost,
                           process_name_running,
                           reassert_viewer_topmost, set_topmost_no_activate)


BROADCAST_WINDOW_PATROL_INTERVAL_SEC = 60.0
_LOG_TAIL_BYTES = 4 * 1024 * 1024
_STATUS_RE = re.compile(
    rb"set_streaming_status:\s+last_status:\d+\s+set_status:(\d+)"
)
_STATUS_NAMES = {
    0: "Idle",
    2: "Starting",
    3: "Starting",
    5: "Streaming",
    6: "Stopping",
    7: "Stopping",
}


def _default_livehime_executable() -> Path:
    program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
    return Path(program_files) / "bililive" / "livehime" / "livehime.exe"


def _default_livehime_log() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA") or ""
    return Path(local_app_data) / "Bililive" / "User Data" / "bililive_debug.log"


def _read_tail(path: Path, limit: int = _LOG_TAIL_BYTES) -> bytes:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max(1, int(limit))), os.SEEK_SET)
        return stream.read()


def _livehime_process_running(executable_path: Path | str) -> bool:
    """Handle Livehime's elevated process path being hidden by Windows UIPI."""
    return process_name_running(Path(executable_path).name)


def get_livehime_streaming_state(
    log_path: Path | str | None = None,
    livehime_executable: Path | str | None = None,
    process_checker: Callable[[Path | str], bool] = _livehime_process_running,
) -> str:
    """Mirror the protected bridge's local status mapping, fail-closed."""
    executable = (Path(livehime_executable) if livehime_executable is not None
                  else _default_livehime_executable())
    if not process_checker(executable):
        return "NotRunning"
    path = Path(log_path) if log_path is not None else _default_livehime_log()
    try:
        latest = None
        for match in _STATUS_RE.finditer(_read_tail(path)):
            latest = int(match.group(1))
    except (OSError, TypeError, ValueError):
        return "Unknown"
    return _STATUS_NAMES.get(latest, "Unknown")


def current_session_game_executable(
    session_path: Path | str | None = None,
) -> Path | None:
    """Read the exact game executable selected by the current stack session."""
    path = (Path(session_path) if session_path is not None
            else RUNTIME_DIR / "session.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("state") != "running":
        return None
    raw = payload.get("game_exe")
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw.strip())
    return candidate if candidate.is_absolute() else None


@dataclass(frozen=True)
class PatrolResult:
    state: str
    game_hwnd: int | None = None
    game_was_topmost: bool | None = None
    game_topmost: bool = False
    viewer_topmost: bool = False
    error: str = ""

    @property
    def repaired(self) -> bool:
        return bool(self.game_was_topmost is False and self.game_topmost)


class BroadcastWindowPatrol:
    """Run one bounded window-order check at most once per minute."""

    def __init__(
        self,
        interval_sec: float = BROADCAST_WINDOW_PATROL_INTERVAL_SEC,
        *,
        state_reader: Callable[[], str] = get_livehime_streaming_state,
        game_executable_reader: Callable[[], Path | None] = current_session_game_executable,
        game_window_finder: Callable[[Path | str], int | None] = find_window_for_executable,
        topmost_reader: Callable[[int], bool] = is_topmost,
        topmost_setter: Callable[[int], bool] = set_topmost_no_activate,
        viewer_reassert: Callable[..., bool] = reassert_viewer_topmost,
    ) -> None:
        self.interval_sec = max(1.0, float(interval_sec))
        self._next_check_at = 0.0
        self._state_reader = state_reader
        self._game_executable_reader = game_executable_reader
        self._game_window_finder = game_window_finder
        self._topmost_reader = topmost_reader
        self._topmost_setter = topmost_setter
        self._viewer_reassert = viewer_reassert

    def poll(
        self,
        *,
        viewer_hwnd: int | None = None,
        now: float | None = None,
        force: bool = False,
    ) -> PatrolResult | None:
        moment = time.monotonic() if now is None else float(now)
        if not force and moment < self._next_check_at:
            return None
        self._next_check_at = moment + self.interval_sec

        try:
            state = str(self._state_reader())
        except Exception as exc:
            return PatrolResult("Unknown", error=f"state: {exc}")
        if state != "Streaming":
            return PatrolResult(state)

        try:
            game_executable = self._game_executable_reader()
            if game_executable is None:
                return PatrolResult(state, error="current session has no exact game executable")
            game_hwnd = self._game_window_finder(game_executable)
            if not game_hwnd:
                return PatrolResult(state, error="exact game window not found")
            was_topmost = bool(self._topmost_reader(game_hwnd))
        except Exception as exc:
            return PatrolResult(state, error=f"game lookup: {exc}")

        game_topmost = False
        viewer_topmost = False
        errors: list[str] = []
        try:
            # Reassert even when WS_EX_TOPMOST is already set: the style bit
            # alone does not prove that the game leads the TOPMOST z-order band.
            game_topmost = bool(
                self._topmost_setter(game_hwnd)
                and self._topmost_reader(game_hwnd)
            )
            if not game_topmost:
                errors.append("game TOPMOST reassert failed")
        except Exception as exc:
            errors.append(f"game TOPMOST: {exc}")
        try:
            # Always run second so ASCEND-VISION ends above the game, without
            # taking input focus from it.
            viewer_topmost = bool(self._viewer_reassert(hwnd=viewer_hwnd))
            if not viewer_topmost:
                errors.append("viewer TOPMOST reassert failed")
        except Exception as exc:
            errors.append(f"viewer TOPMOST: {exc}")
        return PatrolResult(
            state=state,
            game_hwnd=int(game_hwnd),
            game_was_topmost=was_topmost,
            game_topmost=game_topmost,
            viewer_topmost=viewer_topmost,
            error="; ".join(errors),
        )
