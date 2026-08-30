"""Session-scoped manual takeover control and Windows global hotkeys.

The runner owns the hotkey message loop so pausing the Brain does not remove the
only component capable of resuming it.  The Brain child reads the tiny atomic
state file before every gameplay POST; read-only state polling remains available
while a human owns the game.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Callable

from lifecycle import RUNTIME_DIR, SESSION_ID


CONTROL_SCHEMA = "sts2.ascend-brain-control/v1"
PAUSE_HOTKEY = "Ctrl+Alt+F9"
RESUME_HOTKEY = "Ctrl+Alt+F10"

_PAUSE_HOTKEY_ID = 0xB901
_RESUME_HOTKEY_ID = 0xB902
_REPLACE_RETRIES = 20


class BrainControlPaused(RuntimeError):
    """Raised immediately before a gameplay POST while manual control is active."""


@dataclass(frozen=True)
class ControlSnapshot:
    enabled: bool
    pause_generation: int = 0
    changed_at: str = ""
    source: str = "default"
    hotkeys_registered: bool | None = None
    error: str = ""

    @property
    def paused(self) -> bool:
        return not self.enabled


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def control_path(runtime_dir: Path | None = None,
                 session_id: str | None = None) -> Path:
    root = Path(runtime_dir) if runtime_dir is not None else RUNTIME_DIR
    sid = str(session_id or SESSION_ID or "legacy").strip().lower() or "legacy"
    safe_sid = "".join(ch for ch in sid if ch.isalnum() or ch in "-_") or "legacy"
    return root / f"brain-control.{safe_sid}.json"


def read_control_state(runtime_dir: Path | None = None,
                       session_id: str | None = None) -> ControlSnapshot:
    """Read the current control mode.

    A missing file is the backwards-compatible autonomous default.  A present but
    malformed file fails closed because an unreadable explicit stop must never be
    interpreted as permission to click the game.
    """
    path = control_path(runtime_dir, session_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ControlSnapshot(enabled=True)
    except OSError as exc:
        return ControlSnapshot(enabled=False, source="read-error", error=str(exc))
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or type(data.get("enabled")) is not bool:
            raise ValueError("control payload must contain boolean enabled")
        generation = data.get("pause_generation", 0)
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ValueError("pause_generation must be a non-negative integer")
        registered = data.get("hotkeys_registered")
        if registered is not None and type(registered) is not bool:
            raise ValueError("hotkeys_registered must be boolean or null")
        return ControlSnapshot(
            enabled=data["enabled"],
            pause_generation=generation,
            changed_at=str(data.get("changed_at") or ""),
            source=str(data.get("source") or "unknown"),
            hotkeys_registered=registered,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return ControlSnapshot(enabled=False, source="invalid-state", error=str(exc))


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False,
                dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as handle:
            temporary = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(temporary, path)
                temporary = None
                return
            except PermissionError:
                if attempt + 1 == _REPLACE_RETRIES:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except OSError:
                pass


def _publish(enabled: bool, *, source: str,
             runtime_dir: Path | None = None,
             session_id: str | None = None,
             hotkeys_registered: bool | None = None,
             reset_generation: bool = False) -> ControlSnapshot:
    path = control_path(runtime_dir, session_id)
    previous = read_control_state(runtime_dir, session_id)
    generation = 0 if reset_generation else previous.pause_generation
    if not enabled and previous.enabled:
        generation += 1
    registered = (previous.hotkeys_registered if hotkeys_registered is None
                  else bool(hotkeys_registered))
    payload = {
        "schema": CONTROL_SCHEMA,
        "session_id": str(session_id or SESSION_ID or "legacy"),
        "enabled": bool(enabled),
        "pause_generation": generation,
        "changed_at": _now(),
        "source": str(source),
        "hotkeys_registered": registered,
        "pause_hotkey": PAUSE_HOTKEY,
        "resume_hotkey": RESUME_HOTKEY,
    }
    _atomic_write(path, payload)
    return ControlSnapshot(
        enabled=bool(enabled), pause_generation=generation,
        changed_at=payload["changed_at"], source=str(source),
        hotkeys_registered=registered)


def initialize_control_state(runtime_dir: Path | None = None,
                             session_id: str | None = None) -> ControlSnapshot:
    """Start a fresh stack session in autonomous mode."""
    return _publish(
        True, source="runner-start", runtime_dir=runtime_dir,
        session_id=session_id, hotkeys_registered=False, reset_generation=True)


def set_brain_enabled(enabled: bool, *, source: str,
                      runtime_dir: Path | None = None,
                      session_id: str | None = None) -> ControlSnapshot:
    return _publish(
        bool(enabled), source=source, runtime_dir=runtime_dir,
        session_id=session_id)


def set_hotkey_registration(registered: bool, *, source: str,
                            runtime_dir: Path | None = None,
                            session_id: str | None = None) -> ControlSnapshot:
    current = read_control_state(runtime_dir, session_id)
    return _publish(
        current.enabled, source=source, runtime_dir=runtime_dir,
        session_id=session_id, hotkeys_registered=registered)


def ensure_action_allowed() -> None:
    """Final action-send gate shared by every ``Sts2Client.act`` call."""
    snapshot = read_control_state()
    if snapshot.paused:
        detail = f": {snapshot.error}" if snapshot.error else ""
        raise BrainControlPaused(
            f"Brain is paused by manual control ({RESUME_HOTKEY} resumes){detail}")


class GlobalHotkeyController:
    """Own the Windows RegisterHotKey message loop inside the persistent runner."""

    def __init__(self, log: Callable[[str], None] | None = None,
                 *, runtime_dir: Path | None = None,
                 session_id: str | None = None) -> None:
        self.log = log or (lambda _message: None)
        self.runtime_dir = runtime_dir
        self.session_id = session_id
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._thread_id = 0
        self.registered = False

    def start(self, timeout: float = 3.0) -> bool:
        initialize_control_state(self.runtime_dir, self.session_id)
        if os.name != "nt":
            self.log("全局 Brain 快捷键仅支持 Windows；自主模式照常运行")
            return False
        self._thread = threading.Thread(
            target=self._message_loop, name="brain-global-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(max(0.0, timeout))
        return self.registered

    def close(self, timeout: float = 2.0) -> None:
        thread = self._thread
        if thread is None:
            return
        if thread.is_alive() and self._thread_id:
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
        thread.join(max(0.0, timeout))

    def _set_mode(self, enabled: bool) -> None:
        previous = read_control_state(self.runtime_dir, self.session_id)
        snapshot = set_brain_enabled(
            enabled, source=("hotkey-resume" if enabled else "hotkey-pause"),
            runtime_dir=self.runtime_dir, session_id=self.session_id)
        if previous.enabled == snapshot.enabled:
            return
        if enabled:
            self.log(f"人工接管结束：Brain 已启动（{PAUSE_HOTKEY} 可再次停止）")
        else:
            self.log(f"人工接管生效：Brain 已停止发送操作（{RESUME_HOTKEY} 恢复）")
        try:
            import winsound
            tones = ((520, 70), (880, 110)) if enabled else ((880, 70), (440, 130))
            for frequency, duration in tones:
                winsound.Beep(frequency, duration)
        except Exception:
            pass

    def handle_hotkey_id(self, hotkey_id: int) -> bool:
        """Pure dispatch seam used by the Win32 loop and focused tests."""
        if hotkey_id == _PAUSE_HOTKEY_ID:
            self._set_mode(False)
            return True
        if hotkey_id == _RESUME_HOTKEY_ID:
            self._set_mode(True)
            return True
        return False

    def _message_loop(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        mods = 0x0001 | 0x0002 | 0x4000  # ALT | CONTROL | MOD_NOREPEAT
        registrations = (
            (_PAUSE_HOTKEY_ID, 0x78),   # VK_F9
            (_RESUME_HOTKEY_ID, 0x79),  # VK_F10
        )
        successful: list[int] = []
        self._thread_id = int(kernel32.GetCurrentThreadId())
        try:
            for hotkey_id, virtual_key in registrations:
                if not user32.RegisterHotKey(None, hotkey_id, mods, virtual_key):
                    error = int(kernel32.GetLastError())
                    self.log(
                        f"Brain 全局快捷键注册失败（Win32 {error}）；"
                        "可继续使用 Stop-Agent.ps1 -KeepGame")
                    return
                successful.append(hotkey_id)
            self.registered = True
            set_hotkey_registration(
                True, source="hotkeys-ready", runtime_dir=self.runtime_dir,
                session_id=self.session_id)
            self.log(
                f"Brain 全局快捷键就绪：{PAUSE_HOTKEY} 停止，"
                f"{RESUME_HOTKEY} 启动")
            self._ready.set()
            message = wintypes.MSG()
            while True:
                result = int(user32.GetMessageW(ctypes.byref(message), None, 0, 0))
                if result <= 0:
                    break
                if message.message == 0x0312:  # WM_HOTKEY
                    self.handle_hotkey_id(int(message.wParam))
        except Exception as exc:
            self.log(f"Brain 全局快捷键监听异常：{exc}")
        finally:
            for hotkey_id in successful:
                try:
                    user32.UnregisterHotKey(None, hotkey_id)
                except Exception:
                    pass
            if self.registered:
                try:
                    set_hotkey_registration(
                        False, source="hotkeys-stopped", runtime_dir=self.runtime_dir,
                        session_id=self.session_id)
                except OSError:
                    pass
            self.registered = False
            self._ready.set()

