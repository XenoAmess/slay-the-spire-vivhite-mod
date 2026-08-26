"""Shared lifecycle primitives for the sts2-ascend process stack.

The PowerShell entrypoints and every long-lived Python component coordinate via
``sts2-ascend/.runtime``.  Keeping the protocol file-based makes shutdown work
for detached/no-window children without relying on a shared Windows console.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent.parent


def resolve_stack_root(source_root: Path | None = None,
                       environ: dict[str, str] | None = None) -> Path:
    """Resolve the authoritative stack root shared by detached copies.

    Review sandboxes contain a full copy of ``sts2-ascend``.  Deriving runtime
    ownership from ``__file__`` lets such a copy create a second viewer lock.
    Started stack processes already inherit the canonical ``.runtime`` path,
    so its parent is the stable identity even when the executing script lives
    in a review clone.
    """
    env = os.environ if environ is None else environ
    explicit_root = str(env.get("STS2_ASCEND_ROOT", "")).strip()
    if explicit_root:
        return Path(explicit_root).resolve()
    explicit_runtime = str(env.get("STS2_ASCEND_RUNTIME_DIR", "")).strip()
    if explicit_runtime:
        return Path(explicit_runtime).resolve().parent
    return Path(source_root or BASE_DIR).resolve()


STACK_ROOT = resolve_stack_root()
RUNTIME_DIR = Path(os.environ.get("STS2_ASCEND_RUNTIME_DIR") or (STACK_ROOT / ".runtime"))
_RAW_SESSION_ID = os.environ.get("STS2_ASCEND_SESSION_ID", "legacy").strip()
SESSION_ID = (_RAW_SESSION_ID.lower() if re.fullmatch(r"[0-9a-fA-F]{32}", _RAW_SESSION_ID)
              else "legacy")
_ENV_STOP_FILE = os.environ.get("STS2_ASCEND_STOP_FILE", "").strip()
STOP_REQUEST = (Path(_ENV_STOP_FILE) if _ENV_STOP_FILE else
                RUNTIME_DIR / (f"stop.{SESSION_ID}.request" if SESSION_ID != "legacy"
                               else "stop.request"))
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def viewer_launch_disabled(environ: dict[str, str] | None = None) -> bool:
    """Return whether this process tree is forbidden from opening a viewer."""
    env = os.environ if environ is None else environ
    value = str(env.get("STS2_ASCEND_DISABLE_VIEWER", "")).strip().casefold()
    return value in {"1", "true", "yes", "on"}


def _process_creation_times(pid: int | None = None) -> tuple[int, float] | None:
    """Return exact Windows FILETIME ticks plus Unix seconds for a process."""
    try:
        import ctypes

        class FileTime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

        k32 = ctypes.windll.kernel32
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(FileTime)] * 4
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k32.OpenProcess(0x1000, False, int(pid or os.getpid()))
        if not handle:
            return None
        try:
            created, exited, kernel, user = FileTime(), FileTime(), FileTime(), FileTime()
            if not k32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                       ctypes.byref(kernel), ctypes.byref(user)):
                return None
            ticks = (int(created.high) << 32) | int(created.low)
            return ticks, ticks / 10_000_000 - 11_644_473_600
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return None


def _runtime_path(name: str, runtime_dir: Path | None = None) -> Path:
    root = Path(runtime_dir) if runtime_dir is not None else RUNTIME_DIR
    return root / name


def stop_path(runtime_dir: Path | None = None, session_id: str | None = None) -> Path:
    """Return the session-scoped stop file (legacy callers use ``stop.request``)."""
    if runtime_dir is None and session_id is None:
        return STOP_REQUEST
    root = Path(runtime_dir) if runtime_dir is not None else RUNTIME_DIR
    sid = SESSION_ID if session_id is None else (session_id.strip() or "legacy")
    return root / (f"stop.{sid}.request" if sid != "legacy" else "stop.request")


def stop_requested(runtime_dir: Path | None = None) -> bool:
    """Return whether the unified stop script has requested stack shutdown."""
    return stop_path(runtime_dir).exists()


def request_stop(source: str = "python", runtime_dir: Path | None = None) -> Path:
    """Atomically publish a stop request and return its path."""
    root = Path(runtime_dir) if runtime_dir is not None else RUNTIME_DIR
    root.mkdir(parents=True, exist_ok=True)
    path = STOP_REQUEST if runtime_dir is None else stop_path(root)
    temp = root / f"stop.{os.getpid()}.tmp"
    payload = {
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": source,
        "pid": os.getpid(),
    }
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    return path


def clear_stop_request(runtime_dir: Path | None = None) -> None:
    """Clear the previous stop request immediately before a new stack start."""
    try:
        stop_path(runtime_dir).unlink(missing_ok=True)
    except OSError:
        pass


def wait_for_stop(seconds: float, poll_seconds: float = 0.2,
                  runtime_dir: Path | None = None) -> bool:
    """Sleep interruptibly; return True as soon as shutdown is requested."""
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        if stop_requested(runtime_dir):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(max(0.02, poll_seconds), remaining))


def pid_path(role: str, runtime_dir: Path | None = None) -> Path:
    """Return the PID file for a validated stack role."""
    if not _ROLE_RE.fullmatch(role):
        raise ValueError(f"invalid lifecycle role: {role!r}")
    suffix = f".{SESSION_ID}" if SESSION_ID != "legacy" else ""
    return _runtime_path(f"{role}{suffix}.pid", runtime_dir)


@contextmanager
def pid_file(role: str, runtime_dir: Path | None = None) -> Iterator[Path]:
    """Publish this process PID for *role* and remove only our own record."""
    path = pid_path(role, runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    own_pid = os.getpid()
    creation = _process_creation_times(own_pid)
    payload = {
        "pid": own_pid,
        "role": role,
        "session_id": SESSION_ID,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "created_unix": creation[1] if creation else time.time(),
        "creation_filetime": creation[0] if creation else 0,
        "executable": sys.executable,
        "argv": list(sys.argv),
    }
    temp = path.parent / f"{path.name}.{own_pid}.tmp"
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    try:
        yield path
    finally:
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if (int(current.get("pid", 0)) == own_pid and
                    current.get("session_id") == SESSION_ID):
                path.unlink(missing_ok=True)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
