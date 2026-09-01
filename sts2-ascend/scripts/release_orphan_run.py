#!/usr/bin/env python3
"""One-shot, fail-closed release of an unrecoverable active run.

This is an operator boundary for the *explicit* orphan transaction exposed by
``brain.agent.release_orphan_run_once``.  It is intentionally not part of the
normal runner lifecycle:

* ``--capture`` is a live-stack, read-only phase bound to one GUID session;
* preview/apply run only after ``Stop-Agent.ps1`` has completed;
* default mode is a read-only validation/preview;
* ``--apply`` is required before any Knowledge/rotation transaction is invoked;
* automatic evidence collection uses only localhost ``GET`` requests and
  read-only native-file probes; no ``POST /action`` or process/UAC operation is
  ever performed.

Callers may instead provide a previously captured JSON evidence file with
``--evidence-file``.  Active-run apply requires the capture's exact session
stop sentinel, so an arbitrary old JSON file cannot be replayed across boots.
The evidence is still validated by the same strict contract in
``character_rotation`` before an apply can proceed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import ctypes
import glob
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import stat as stat_module
import sys
import time
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
ASCEND_ROOT = SCRIPT_DIR.parent
REPO_ROOT = ASCEND_ROOT.parent
BRAIN_DIR = ASCEND_ROOT / "brain"
if str(BRAIN_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_DIR))

from agent import release_orphan_run_once  # noqa: E402
from character_rotation import (  # noqa: E402
    ORPHAN_EVIDENCE_VERSION,
    ORPHAN_RELEASE_REASON,
    CharacterRotation,
    CharacterRotationError,
    _validate_orphan_evidence,
    canonical_character_id,
)
from client import ApiError, ConnectionDown, Sts2Client  # noqa: E402


RESULT_SCHEMA = "sts2.ascend.orphan-release-result/v1"
CAPTURE_SCHEMA = "sts2.ascend.orphan-capture/v1"
MAX_EVIDENCE_BYTES = 1024 * 1024
MAX_NATIVE_FILE_BYTES = 8 * 1024 * 1024
MAX_HISTORY_FILES = 4096
MAX_HISTORY_BYTES = 64 * 1024 * 1024
DEFAULT_SAMPLE_DELAY = 1.0
DEFAULT_PORTS = (8080, 8081, 8082, 8083, 8084)
SESSION_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class OrphanCliError(RuntimeError):
    """An operator input or read-only probe failed closed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z")


def _evidence_digest(evidence: Mapping[str, Any]) -> str:
    """Hash the immutable evidence body (excluding its capture envelope)."""
    body = {key: value for key, value in evidence.items() if key != "capture"}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_stack_root() -> Path:
    """Resolve the canonical stack root without deriving a second runtime tree."""
    explicit = os.environ.get("STS2_ASCEND_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    runtime = os.environ.get("STS2_ASCEND_RUNTIME_DIR", "").strip()
    if runtime:
        return Path(runtime).expanduser().resolve().parent
    return ASCEND_ROOT.resolve()


def _pid_alive(pid: int) -> bool:
    """Read-only liveness check; never opens a process with write rights."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # PROCESS_QUERY_LIMITED_INFORMATION; no terminate/suspend rights.
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            # An inability to prove that a PID is dead is itself a block.  The
            # caller treats the conservative ``True`` as a live owner.
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def assert_stack_stopped(runtime_dir: str | os.PathLike[str]) -> None:
    """Require a clean lifecycle boundary before touching durable stores.

    ``Stop-Agent.ps1`` removes ``session.json`` after its scoped shutdown.  A
    live PID record is also a hard block, including a stale record whose PID
    cannot be proven dead.  We deliberately do not kill, clean, or rewrite any
    runtime marker here.
    """
    runtime = Path(runtime_dir).expanduser().resolve()
    session = runtime / "session.json"
    if session.exists():
        raise OrphanCliError(
            f"sts2-ascend session is still present; run Stop-Agent.ps1 first: {session}")

    live: list[str] = []
    for pid_path in sorted(runtime.glob("*.pid")):
        try:
            raw = json.loads(pid_path.read_text(encoding="utf-8"))
            pid = int(raw.get("pid", 0)) if isinstance(raw, Mapping) else int(raw)
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise OrphanCliError(
                f"cannot validate lifecycle PID record {pid_path}: {exc}") from exc
        if _pid_alive(pid):
            live.append(f"{pid_path.name}(pid={pid})")
    if live:
        raise OrphanCliError(
            "sts2-ascend process records are still alive; stop the stack first: "
            + ", ".join(live))


@contextmanager
def lifecycle_lock(runtime_dir: str | os.PathLike[str]):
    """Hold the same lifecycle lock as Start/Stop without creating markers.

    Opening an existing lock with exclusive sharing prevents a concurrent
    Start-Agent/Stop-Agent transaction from racing the stopped-state check.  A
    missing lock is an error instead of an invitation to create or mutate a
    runtime file; the normal lifecycle scripts create it during installation.
    """
    runtime = Path(runtime_dir).expanduser().resolve()
    path = runtime / "lifecycle.lock"
    if not path.is_file():
        raise OrphanCliError(f"lifecycle lock is missing; run Stop-Agent.ps1 first: {path}")
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = (
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        )
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        # GENERIC_READ|GENERIC_WRITE, no sharing, OPEN_EXISTING.
        handle = kernel32.CreateFileW(
            str(path), 0xC0000000, 0, None, 3, 0x80, None)
        invalid = ctypes.c_void_p(-1).value
        handle_value = getattr(handle, "value", handle)
        if not handle_value or handle_value == invalid:
            raise OrphanCliError(
                f"lifecycle lock is held by another operation: {path}")
        try:
            yield
        finally:
            kernel32.CloseHandle(handle)
        return

    try:
        handle = path.open("r+b")
    except OSError as exc:
        raise OrphanCliError(f"cannot open lifecycle lock {path}: {exc}") from exc
    try:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            raise OrphanCliError(
                f"lifecycle lock is held by another operation: {path}") from exc
        yield
    finally:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        handle.close()


def _read_json_file(path: Path, *, label: str) -> Any:
    try:
        if not path.is_file():
            raise OrphanCliError(f"{label} is not a regular file: {path}")
        size = path.stat().st_size
        if size > MAX_EVIDENCE_BYTES:
            raise OrphanCliError(
                f"{label} exceeds the {MAX_EVIDENCE_BYTES}-byte limit: {path}")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OrphanCliError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OrphanCliError(f"cannot read {label} {path}: {exc}") from exc


def _read_evidence_argument(value: Path) -> Any:
    """Read a caller-supplied evidence file, or ``-`` for stdin.

    Stdin is opt-in and bounded in memory just like a file.  The stream is
    never written back to disk, and a missing/invalid object is a hard error.
    """
    if str(value) != "-":
        raw = _read_json_file(value, label="evidence file")
    else:
        try:
            text = sys.stdin.read(MAX_EVIDENCE_BYTES + 1)
        except (OSError, UnicodeError) as exc:
            raise OrphanCliError(f"cannot read evidence stdin: {exc}") from exc
        if len(text.encode("utf-8", errors="replace")) > MAX_EVIDENCE_BYTES:
            raise OrphanCliError(
                f"evidence stdin exceeds the {MAX_EVIDENCE_BYTES}-byte limit")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OrphanCliError(f"evidence stdin is not valid JSON: {exc}") from exc

    # ``--capture`` prints the normal result envelope so that every invocation
    # has one stable JSON schema.  Accept that envelope on the subsequent
    # apply command, but never unwrap arbitrary objects merely because they
    # happen to contain an ``evidence`` key.
    if (isinstance(raw, Mapping) and raw.get("schema") == RESULT_SCHEMA
            and raw.get("operation") == "release_orphan_run_once"
            and isinstance(raw.get("evidence"), Mapping)):
        return raw["evidence"]
    return raw


def _rotation_identity(knowledge_root: Path) -> dict[str, Any]:
    """Read the durable identity without inventing a run or character.

    This lightweight read keeps preview mode from causing a migration write via
    ``CharacterRotation.snapshot``.  ``--apply`` still delegates all writes to
    the normal transaction API.
    """
    path = knowledge_root / "character_rotation.json"
    raw = _read_json_file(path, label="rotation state")
    if not isinstance(raw, Mapping):
        raise OrphanCliError("rotation state must be a JSON object")
    active = raw.get("active_run")
    active_run_id = ""
    active_character_id = ""
    if active is not None:
        if not isinstance(active, Mapping):
            raise OrphanCliError("rotation active_run must be an object or null")
        active_run_id = str(active.get("run_id") or "").strip()
        active_character_id = str(active.get("character_id") or "").strip()
        if not active_run_id or not active_character_id:
            raise OrphanCliError("rotation active_run lacks exact run/character identity")
        if canonical_character_id(active_character_id) is None:
            raise OrphanCliError(
                f"rotation active_run has unsupported character_id: {active_character_id!r}")

    orphaned = raw.get("orphaned_runs") or {}
    if not isinstance(orphaned, Mapping):
        raise OrphanCliError("rotation orphaned_runs must be an object")
    orphaned_ids = tuple(str(key).strip() for key in orphaned if str(key).strip())
    return {
        "path": str(path),
        "active_run_id": active_run_id or None,
        "active_character_id": active_character_id or None,
        "orphaned_run_ids": orphaned_ids,
    }


def _parse_iso_timestamp(value: Any, *, label: str) -> tuple[str, float]:
    """Parse one bounded ISO-8601 timestamp for local capture binding."""
    if not isinstance(value, str) or not value.strip():
        raise OrphanCliError(f"{label} must be a non-empty ISO-8601 string")
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise OrphanCliError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        # Lifecycle files are emitted by PowerShell with an offset, but treat a
        # legacy no-offset value as UTC rather than guessing local wall time.
        parsed = parsed.replace(tzinfo=timezone.utc)
    instant = parsed.astimezone(timezone.utc).timestamp()
    if not math.isfinite(instant):
        raise OrphanCliError(f"{label} is not a finite timestamp")
    return text, instant


def _canonical_session_path(path: Path, runtime_dir: Path) -> Path:
    """Resolve a session-owned path and require it to stay in ``runtime_dir``."""
    try:
        resolved = path.expanduser().resolve()
        runtime = runtime_dir.expanduser().resolve()
        if resolved.parent != runtime:
            raise OrphanCliError(
                f"session stop marker escapes the lifecycle directory: {resolved}")
        return resolved
    except OrphanCliError:
        raise
    except OSError as exc:
        raise OrphanCliError(f"cannot resolve session path {path}: {exc}") from exc


def _capture_session_binding(runtime_dir: Path, stack_root: Path) -> dict[str, Any]:
    """Read a live session identity for a read-only capture.

    The binding is deliberately local and explicit.  A capture made without a
    GUID session cannot later be tied to the stop sentinel, so legacy/malformed
    sessions are rejected instead of being treated as interchangeable.
    """
    session_path = runtime_dir / "session.json"
    raw = _read_json_file(session_path, label="live session")
    if not isinstance(raw, Mapping):
        raise OrphanCliError("live session must be a JSON object")
    raw_sid = raw.get("session_id")
    if not isinstance(raw_sid, str) or not SESSION_ID_RE.fullmatch(raw_sid.strip()):
        raise OrphanCliError(
            "live session must carry a 32-hex session_id for capture binding")
    session_id = raw_sid.strip().lower()
    state = raw.get("state")
    if state not in {"running", "foreground"}:
        raise OrphanCliError(
            f"live session is not in a capturable state: {state!r}")
    root_value = raw.get("root")
    if not isinstance(root_value, str) or not root_value.strip():
        raise OrphanCliError("live session.root is required for capture binding")
    try:
        if Path(root_value).expanduser().resolve() != stack_root.resolve():
            raise OrphanCliError("live session root does not match --stack-root")
    except OSError as exc:
        raise OrphanCliError(f"cannot resolve live session root: {exc}") from exc
    started_at, started_unix = _parse_iso_timestamp(
        raw.get("started_at"), label="live session.started_at")
    try:
        session_mtime = session_path.stat().st_mtime
    except OSError as exc:
        raise OrphanCliError(f"cannot stat live session: {exc}") from exc
    expected_stop = runtime_dir / f"stop.{session_id}.request"
    stop_value = raw.get("stop_file")
    if not isinstance(stop_value, str) or not stop_value.strip():
        raise OrphanCliError("live session.stop_file is required for capture binding")
    stop_path = _canonical_session_path(Path(stop_value), runtime_dir)
    if stop_path.name.casefold() != expected_stop.name.casefold():
        raise OrphanCliError("live session.stop_file is not session-scoped")
    if started_unix > time.time() + 30.0:
        raise OrphanCliError("live session.started_at is in the future")
    # A pre-existing sentinel means Stop-Agent has already begun shutting this
    # session down; do not capture a race at that boundary.
    if stop_path.exists():
        raise OrphanCliError(
            f"live session already has a stop request; capture aborted: {stop_path}")
    return {
        "session_id": session_id,
        "session_state": state,
        "session_started_at": started_at,
        "session_started_unix": started_unix,
        "session_file_mtime_unix": session_mtime,
        "session_file": str(session_path.resolve()),
        "stop_file": str(stop_path),
    }


def _capture_metadata(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate the local capture envelope before an active-run apply."""
    raw = evidence.get("capture")
    if not isinstance(raw, Mapping):
        raise OrphanCliError(
            "active-run --apply requires a session-bound --capture evidence file")
    if raw.get("schema") != CAPTURE_SCHEMA:
        raise OrphanCliError("evidence capture schema is unsupported")
    if raw.get("mode") != "api-native-readonly":
        raise OrphanCliError("evidence capture mode is not read-only API/native")
    if raw.get("stack_stopped") is not False:
        raise OrphanCliError("capture must be taken before the stack stop boundary")
    sid = raw.get("session_id")
    if not isinstance(sid, str) or not SESSION_ID_RE.fullmatch(sid.strip()):
        raise OrphanCliError("capture lacks a valid 32-hex session_id")
    digest = raw.get("evidence_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest.strip()):
        raise OrphanCliError("capture lacks an evidence_sha256 integrity binding")
    captured = raw.get("captured_unix")
    if isinstance(captured, bool) or not isinstance(captured, (int, float)):
        raise OrphanCliError("capture.captured_unix must be numeric")
    if not math.isfinite(float(captured)) or float(captured) <= 0:
        raise OrphanCliError("capture.captured_unix must be finite and positive")
    now = time.time()
    if float(captured) > now + 30.0:
        raise OrphanCliError("capture timestamp is in the future")
    _captured_text, captured_at_unix = _parse_iso_timestamp(
        raw.get("captured_at"), label="capture.captured_at")
    if abs(captured_at_unix - float(captured)) > 10.0:
        raise OrphanCliError(
            "capture.captured_at and captured_unix disagree")
    if not isinstance(raw.get("stop_file"), str) or not str(raw.get("stop_file")).strip():
        raise OrphanCliError("capture.stop_file is required for session binding")
    for field in ("session_started_at", "session_file_mtime_unix", "session_file"):
        if field not in raw:
            raise OrphanCliError(f"capture.{field} is required for session binding")
    _parse_iso_timestamp(raw.get("session_started_at"),
                         label="capture.session_started_at")
    mtime = raw.get("session_file_mtime_unix")
    if (isinstance(mtime, bool) or not isinstance(mtime, (int, float))
            or not math.isfinite(float(mtime)) or float(mtime) <= 0):
        raise OrphanCliError("capture.session_file_mtime_unix is invalid")
    if not isinstance(raw.get("session_file"), str) or not str(raw.get("session_file")).strip():
        raise OrphanCliError("capture.session_file is invalid")
    return raw


def _assert_capture_stopped(capture: Mapping[str, Any], runtime_dir: Path) -> None:
    """Prove a live capture crossed the matching local Stop-Agent boundary."""
    sid = str(capture.get("session_id") or "").strip().lower()
    expected = runtime_dir / f"stop.{sid}.request"
    stop_value = capture.get("stop_file")
    if not isinstance(stop_value, str) or not stop_value.strip():
        raise OrphanCliError("capture.stop_file is required for session binding")
    stop_path = _canonical_session_path(Path(stop_value), runtime_dir)
    if stop_path.name.casefold() != expected.name.casefold():
        raise OrphanCliError("capture.stop_file is not the matching session sentinel")
    if not stop_path.is_file():
        raise OrphanCliError(
            "capture has no matching Stop-Agent sentinel; reject stale evidence")
    try:
        stat = stop_path.stat()
    except OSError as exc:
        raise OrphanCliError(f"cannot stat capture stop sentinel: {exc}") from exc
    captured_unix = float(capture["captured_unix"])
    # NTFS timestamps have finite granularity; allow a small tolerance while
    # still requiring the sentinel to be newer than the read-only capture.
    if stat.st_mtime + 2.0 < captured_unix:
        raise OrphanCliError(
            "capture predates the session stop sentinel; evidence is stale")
    marker = _read_json_file(stop_path, label="capture stop sentinel")
    if not isinstance(marker, Mapping):
        raise OrphanCliError("capture stop sentinel must be a JSON object")
    marker_sid = marker.get("session_id")
    if not isinstance(marker_sid, str) or marker_sid.strip().lower() != sid:
        raise OrphanCliError("capture stop sentinel session_id does not match capture")
    _marker_at, marker_unix = _parse_iso_timestamp(
        marker.get("requested_at"), label="capture stop sentinel.requested_at")
    if marker_unix + 2.0 < captured_unix:
        raise OrphanCliError(
            "capture stop request timestamp predates capture; evidence is stale")


def _action_names(state: Mapping[str, Any]) -> set[str]:
    raw_actions = state.get("available_actions") or []
    names: set[str] = set()
    if not isinstance(raw_actions, (list, tuple)):
        return names
    for item in raw_actions:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, Mapping):
            value = item.get("action", item.get("id", item.get("name")))
            if isinstance(value, str):
                names.add(value)
    return names


def _endpoint_action_names(actions: Any) -> set[str]:
    """Normalize ``GET /actions/available`` while rejecting malformed rows."""
    if not isinstance(actions, (list, tuple)):
        raise OrphanCliError("/actions/available.actions must be an array")
    names: set[str] = set()
    for index, item in enumerate(actions):
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, Mapping):
            value = item.get("name", item.get("action", item.get("id")))
            name = value.strip() if isinstance(value, str) else ""
        else:
            name = ""
        if not name:
            raise OrphanCliError(
                f"/actions/available.actions[{index}] is not a named action")
        names.add(name)
    return names


def _strict_available_actions(client: Any) -> set[str]:
    """Read ``/actions/available`` without the client's empty-list fallback."""
    request = getattr(client, "_request", None)
    if callable(request):
        payload = request("GET", "/actions/available")
        if not isinstance(payload, Mapping) or "actions" not in payload:
            raise OrphanCliError(
                "/actions/available omitted its required actions field")
        return _endpoint_action_names(payload.get("actions"))
    # Small test doubles and third-party wrappers may expose only the public
    # method.  Their method has already performed the HTTP decode; malformed
    # values are still rejected by _endpoint_action_names.
    return _endpoint_action_names(client.available_actions())


def _state_sample(state: Mapping[str, Any], sequence: int) -> dict[str, Any]:
    required = ("screen", "run_id", "run", "available_actions", "state_version")
    missing = [key for key in required if key not in state]
    if missing:
        raise OrphanCliError(
            "/state omitted required field(s): " + ", ".join(missing))
    screen = state.get("screen")
    run_id = state.get("run_id")
    run = state.get("run")
    actions = state.get("available_actions")
    version = state.get("state_version")
    if not isinstance(screen, str) or not screen.strip():
        raise OrphanCliError("/state.screen must be a non-empty string")
    if not isinstance(run_id, str) or not run_id.strip():
        raise OrphanCliError("/state.run_id must be a non-empty string")
    # The orphan proof is a negative assertion.  An empty object is not
    # equivalent to an explicit JSON null: a truncated/older DTO could expose
    # ``{}`` while omitting the actual run payload.  Require the native API's
    # unambiguous null marker and let the transaction validator perform the
    # final MAIN_MENU/run_unknown checks.
    if run is not None:
        raise OrphanCliError(
            "/state.run must be explicit null for an orphan negative probe")
    if not isinstance(actions, (list, tuple)):
        raise OrphanCliError("/state.available_actions must be an array")
    # Reject malformed action entries instead of treating them as an empty list.
    for index, item in enumerate(actions):
        if isinstance(item, str) and item.strip():
            continue
        if isinstance(item, Mapping):
            name = item.get("name", item.get("action", item.get("id")))
            if isinstance(name, str) and name.strip():
                continue
        raise OrphanCliError(
            f"/state.available_actions[{index}] is not a named action")
    if isinstance(version, bool) or not isinstance(version, (int, float, str)):
        raise OrphanCliError("/state.state_version must be a scalar")
    if isinstance(version, str) and not version.strip():
        raise OrphanCliError("/state.state_version must be non-empty")
    if isinstance(version, (int, float)):
        if not math.isfinite(float(version)) or version < 0:
            raise OrphanCliError(
                "/state.state_version must be finite and non-negative")
    sample: dict[str, Any] = {
        "sequence": sequence,
        "observed_at": _utc_now(),
        "screen": screen.strip(),
        "run_id": run_id.strip(),
        "run": None,
        "run_empty": run is None,
        "continue_run": "continue_run" in _action_names(state),
        "state_version": version,
    }
    return sample


def _path_values(value: Any) -> tuple[Path, ...]:
    """Normalize one or many CLI path values without accepting empty entries."""
    if value is None:
        return ()
    if isinstance(value, (str, os.PathLike)):
        values = (value,)
    elif isinstance(value, Sequence):
        values = tuple(value)
    else:
        raise OrphanCliError(f"native path argument has unsupported type: {type(value).__name__}")
    paths: list[Path] = []
    for item in values:
        text = str(item).strip()
        if text:
            paths.append(Path(text).expanduser())
    return tuple(paths)


def _expand_probe_paths(paths: Sequence[Path]) -> tuple[Path, ...]:
    """Expand explicit wildcard probes; an unmatched pattern remains absent."""
    expanded: list[Path] = []
    for path in paths:
        text = str(path)
        if any(mark in text for mark in ("*", "?", "[")):
            matches = [Path(item) for item in sorted(glob.glob(text))]
            expanded.extend(matches or (path,))
        else:
            expanded.append(path)
    return tuple(expanded)


def _read_marker(path: Path, run_id: str) -> tuple[str, int, bool, list[str]]:
    """Classify one native artifact using a bounded, read-only read.

    Non-text files are deliberately ``unreadable`` rather than being treated as
    proof of absence.  The strict evidence validator rejects that state, so a
    binary/opaque save can never be released by guesswork.
    """
    errors: list[str] = []
    try:
        info = path.stat()
    except FileNotFoundError:
        return "absent", 0, False, errors
    except OSError as exc:
        return "unreadable", 0, False, [f"stat_failed:{path}:{type(exc).__name__}"]
    try:
        if stat_module.S_ISDIR(info.st_mode):
            return "unreadable", 0, False, [f"not_a_file:{path}"]
        if not stat_module.S_ISREG(info.st_mode):
            return "unreadable", 0, False, [f"not_a_regular_file:{path}"]
        size = info.st_size
        if size == 0:
            return "zero_byte", 0, False, errors
        if size > MAX_NATIVE_FILE_BYTES:
            return "unreadable", size, False, [f"file_too_large:{path}"]
        data = path.read_bytes()
    except OSError as exc:
        return "unreadable", 0, False, [f"read_failed:{path}:{type(exc).__name__}"]

    decoded = None
    # Do not let arbitrary binary bytes happen to decode as UTF-16.  A UTF-16
    # save must carry a BOM (or the caller should provide a hand-verified
    # evidence file); otherwise a successful decode is not proof that the file
    # is an inspectable text serializer.
    encodings = ["utf-8-sig"]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    for encoding in encodings:
        try:
            candidate = data.decode(encoding)
            if any(ord(char) < 32 and char not in "\t\r\n"
                       for char in candidate):
                continue
            decoded = candidate
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        return "unreadable", size, False, [f"non_text_artifact:{path}"]
    if not decoded.strip():
        return "empty", size, False, errors
    if run_id in decoded:
        return "matching_run", size, True, errors
    return "no_matching_run", size, False, errors


def _checked_row(kind: str, path: Path, status: str, size: int,
                 *, files: int | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "kind": kind,
        "status": status,
        "path": str(path.resolve()),
        "bytes": max(0, int(size)),
    }
    if files is not None:
        row["files"] = max(0, int(files))
    return row


def _probe_native_path(path: Path, run_id: str, *, kind: str,
                       directory: bool = False) -> tuple[dict[str, Any], dict[str, Any],
                                                         list[str]]:
    """Return ``(summary, checked_row, errors)`` for a save/history path."""
    errors: list[str] = []
    try:
        path_info = path.stat()
    except FileNotFoundError:
        return ({"status": "absent", "bytes": 0, "files": 0},
                _checked_row(kind, path, "absent", 0, files=0), errors)
    except OSError as exc:
        return ({"status": "unreadable"},
                _checked_row(kind, path, "unreadable", 0),
                [f"stat_failed:{path}:{type(exc).__name__}"])

    is_directory = stat_module.S_ISDIR(path_info.st_mode)
    if directory or is_directory:
        if not is_directory:
            return ({"status": "unreadable", "bytes": 0, "files": 0},
                    _checked_row(kind, path, "unreadable", 0, files=0),
                    [f"not_a_directory:{path}"])
        files_seen = 0
        total_bytes = 0
        matched = False
        unreadable = False
        candidates: list[tuple[Path, int]] = []
        try:
            descendants = list(path.rglob("*"))
        except OSError as exc:
            descendants = []
            unreadable = True
            errors.append(f"directory_scan_failed:{path}:{type(exc).__name__}")
        for child in descendants:
            try:
                child_info = child.stat()
            except FileNotFoundError:
                unreadable = True
                errors.append(f"stat_failed:{child}:FileNotFoundError")
                continue
            except OSError as exc:
                unreadable = True
                errors.append(f"stat_failed:{child}:{type(exc).__name__}")
                continue
            if stat_module.S_ISREG(child_info.st_mode):
                candidates.append((child, max(0, int(child_info.st_size))))
            elif not stat_module.S_ISDIR(child_info.st_mode):
                unreadable = True
                errors.append(f"not_a_regular_file:{child}")
        candidates.sort(key=lambda item: str(item[0]).casefold())
        if len(candidates) > MAX_HISTORY_FILES:
            errors.append(f"too_many_history_files:{path}")
            candidates = candidates[:MAX_HISTORY_FILES]
            unreadable = True
        for child, child_size in candidates:
            files_seen += 1
            total_bytes += child_size
            if total_bytes > MAX_HISTORY_BYTES:
                unreadable = True
                errors.append(f"history_bytes_limit:{path}")
                break
            status, _size, child_match, child_errors = _read_marker(child, run_id)
            matched = matched or child_match
            if status == "unreadable":
                unreadable = True
            errors.extend(child_errors)
            if len(errors) >= 32:
                errors = errors[:32]
                unreadable = True
                break
        if matched:
            status = "matching_run"
        elif unreadable or errors:
            status = "unreadable"
        elif not files_seen:
            status = "empty"
        else:
            status = "no_matching_run"
        summary = {"status": status, "bytes": total_bytes, "files": files_seen}
        return summary, _checked_row(kind, path, status, total_bytes, files=files_seen), errors

    status, size, _matched, errors = _read_marker(path, run_id)
    return {"status": status, "bytes": size}, _checked_row(kind, path, status, size), errors


def _aggregate_summaries(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Combine a complete set of explicitly probed candidate paths."""
    statuses = [str(row.get("status") or "unreadable") for row in summaries]
    if any(status == "matching_run" for status in statuses):
        status = "matching_run"
    elif any(status == "unreadable" for status in statuses):
        status = "unreadable"
    elif statuses and all(status == "absent" for status in statuses):
        status = "absent"
    elif statuses and all(status == "zero_byte" for status in statuses):
        status = "zero_byte"
    elif statuses and all(status == "empty" for status in statuses):
        status = "empty"
    else:
        # A mixture such as absent + non-empty text with no matching ID is a
        # successful no-match scan, which is stronger than simply ``absent``.
        status = "no_matching_run"
    return {
        "status": status,
        "bytes": sum(max(0, int(row.get("bytes", 0) or 0)) for row in summaries),
        "files": sum(max(0, int(row.get("files", 0) or 0)) for row in summaries),
    }


def _probe_many(paths: Sequence[Path], run_id: str, *, kind: str,
                directory: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    # A typo in a save/history wildcard must not silently become an ``absent``
    # negative witness.  ``*.stmp`` is the one intentional exception: no temp
    # files is a meaningful result when the containing history directory was
    # explicitly named.
    pre_errors: list[str] = []
    pre_rows: list[dict[str, Any]] = []
    pre_summaries: list[dict[str, Any]] = []
    filtered: list[Path] = []
    for path in paths:
        text = str(path)
        wildcard = any(mark in text for mark in ("*", "?", "["))
        if wildcard:
            matches = glob.glob(text)
            if not matches and kind != "stmp":
                pre_errors.append(f"unmatched_probe_pattern:{path}")
                pre_rows.append(_checked_row(kind, path, "unreadable", 0))
                continue
            if not matches and kind == "stmp":
                # Do not pass a literal wildcard to Path.stat() (Windows
                # reports it as a generic OSError rather than ENOENT).  An
                # explicitly named, readable history directory plus no
                # matching temp files is a valid ``absent`` result.
                pre_summaries.append({"status": "absent", "bytes": 0, "files": 0})
                pre_rows.append(_checked_row(kind, path, "absent", 0))
                continue
        filtered.append(path)
    expanded = _expand_probe_paths(filtered)
    summaries: list[dict[str, Any]] = list(pre_summaries)
    rows: list[dict[str, Any]] = list(pre_rows)
    errors: list[str] = list(pre_errors)
    for path in expanded:
        summary, row, path_errors = _probe_native_path(
            path, run_id, kind=kind,
            directory=directory or path.is_dir())
        summaries.append(summary)
        rows.append(row)
        errors.extend(path_errors)
    if not summaries:
        # Missing candidate classes are intentionally represented as an
        # incomplete probe.  The transaction validator will reject them.
        return ({"status": "unreadable", "bytes": 0, "files": 0}, rows,
                [f"missing_explicit_native_path:{kind}"])
    return _aggregate_summaries(summaries), rows, errors


def collect_native_evidence(
        run_id: str, *,
        save_path: Path | Sequence[Path] | None = None,
        history_path: Path | Sequence[Path] | None = None,
        stmp_path: Path | Sequence[Path] | None = None,
        save_backup_path: Path | Sequence[Path] | None = None,
        save_paths: Sequence[Path] | None = None,
        history_paths: Sequence[Path] | None = None,
        stmp_paths: Sequence[Path] | None = None,
        save_backup_paths: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Probe every explicitly supplied native candidate path, read-only.

    ``save_path``/``history_path``/``stmp_path`` remain accepted as singular
    compatibility aliases.  Automatic CLI capture uses the plural forms and
    requires separate primary ``current_run.save`` and backup candidates so a
    lone ``progress.save`` file cannot accidentally stand in for the full
    native-save check.
    """
    primary = _path_values(save_paths if save_paths is not None else save_path)
    backups = _path_values(
        save_backup_paths if save_backup_paths is not None else save_backup_path)
    histories = _path_values(history_paths if history_paths is not None else history_path)
    stmp_candidates = _path_values(stmp_paths if stmp_paths is not None else stmp_path)

    # Keep the path kinds semantically explicit.  In particular, a caller must
    # not be able to pass a career-wide ``progress.save`` as the sole witness
    # for the per-run ``current_run.save`` slot.
    save, save_rows, errors = _probe_many(
        primary, run_id, kind="current_run.save")
    backup, backup_rows, backup_errors = _probe_many(
        backups, run_id, kind="current_run.save.backup")
    history, history_rows, history_errors = _probe_many(
        histories, run_id, kind="history", directory=True)
    stmp, stmp_rows, stmp_errors = _probe_many(
        stmp_candidates, run_id, kind="stmp", directory=False)
    errors.extend(backup_errors)
    errors.extend(history_errors)
    errors.extend(stmp_errors)
    checked = save_rows + backup_rows + history_rows + stmp_rows
    probe_observed_at = _utc_now()
    return {
        "probe_complete": not errors,
        "save": {"status": save["status"]},
        "save_backup": {"status": backup["status"]},
        "history": {"status": history["status"]},
        "stmp": {"status": stmp["status"]},
        "save_match": save["status"] == "matching_run"
        or backup["status"] == "matching_run",
        "history_match": history["status"] == "matching_run",
        "read_errors": errors[:32],
        "checked_paths": checked,
        "probe_observed_at": probe_observed_at,
    }


def collect_api_evidence(
        run_id: str, character_id: str, *, ports: Sequence[int], delay: float,
        save_paths: Sequence[Path] | None = None,
        history_paths: Sequence[Path] | None = None,
        stmp_paths: Sequence[Path] | None = None,
        save_backup_paths: Sequence[Path] | None = None,
        # Singular names are retained for callers of the first draft of this
        # wrapper.  They are aliases only; the automatic CLI still requires
        # all four explicit native path classes.
        save_path: Path | Sequence[Path] | None = None,
        history_path: Path | Sequence[Path] | None = None,
        stmp_path: Path | Sequence[Path] | None = None,
        save_backup_path: Path | Sequence[Path] | None = None,
        session_binding: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """Collect two consecutive read-only API frames plus native probe facts."""
    if delay < 0.1 or delay > 30.0:
        raise OrphanCliError("--sample-delay must be between 0.1 and 30 seconds")
    try:
        normalized_ports = tuple(int(port) for port in ports)
    except (TypeError, ValueError) as exc:
        raise OrphanCliError("API ports must be integers") from exc
    if not normalized_ports or any(not 1 <= port <= 65535
                                  for port in normalized_ports):
        raise OrphanCliError("API ports must be between 1 and 65535")
    normalized_save_paths = _path_values(
        save_paths if save_paths is not None else save_path)
    normalized_backup_paths = _path_values(
        save_backup_paths if save_backup_paths is not None else save_backup_path)
    normalized_history_paths = _path_values(
        history_paths if history_paths is not None else history_path)
    normalized_stmp_paths = _path_values(
        stmp_paths if stmp_paths is not None else stmp_path)
    client = Sts2Client(ports=normalized_ports, read_timeout=10.0, action_timeout=10.0)
    try:
        base_url = client.discover()
        if not base_url:
            raise OrphanCliError("STS2-Agent /health is not reachable on the requested ports")
        samples: list[dict[str, Any]] = []
        for sequence in (1, 2):
            state = client.state()  # GET only; no call to client.act is reachable here.
            if not isinstance(state, Mapping):
                raise OrphanCliError("/state returned a non-object payload")
            sample = _state_sample(state, sequence)
            # The state DTO and the dedicated endpoint must agree.  In
            # particular, a truncated /state response may not silently turn a
            # missing continue action into a negative orphan proof.
            endpoint_actions = _strict_available_actions(client)
            state_actions = _action_names(state)
            if endpoint_actions != state_actions:
                raise OrphanCliError(
                    "/state.available_actions disagrees with /actions/available")
            samples.append(sample)
            if sequence == 1:
                time.sleep(delay)
    except (ApiError, ConnectionDown, OSError, ValueError, AttributeError) as exc:
        raise OrphanCliError(f"read-only API probe failed: {exc}") from exc

    native = collect_native_evidence(
        run_id, save_paths=normalized_save_paths,
        save_backup_paths=normalized_backup_paths,
        history_paths=normalized_history_paths, stmp_paths=normalized_stmp_paths)
    # Bind the native read to the newest API frame.  The rotation validator
    # rejects a probe that predates that frame; retaining this metadata also
    # makes the JSON capture auditable without copying arbitrary API payloads.
    native["api_state_version"] = samples[-1]["state_version"]
    native["probe_observed_at"] = _utc_now()
    capture = {
        "schema": CAPTURE_SCHEMA,
        "mode": "api-native-readonly",
        "captured_at": _utc_now(),
        "captured_unix": time.time(),
        "stack_stopped": False,
    }
    if session_binding:
        capture.update(dict(session_binding))
    evidence: dict[str, Any] = {
        "version": ORPHAN_EVIDENCE_VERSION,
        "reason": ORPHAN_RELEASE_REASON,
        "run_id": run_id,
        "character_id": character_id,
        "observed_at": _utc_now(),
        "api": {
            "consecutive": True,
            "samples": samples,
            "latest_state_version": samples[-1]["state_version"],
        },
        "native": native,
        "capture": capture,
    }
    capture["evidence_sha256"] = _evidence_digest(evidence)
    return evidence, base_url


def _normalise_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "__dataclass_fields__"):
        return {
            name: getattr(result, name)
            for name in result.__dataclass_fields__
        }
    if isinstance(result, Mapping):
        return dict(result)
    return {"value": str(result)}


def _native_cli_paths(args: argparse.Namespace) -> dict[str, tuple[Path, ...]]:
    """Normalize and semantically check the four automatic-probe path sets."""
    paths = {
        "save_paths": _path_values(getattr(args, "native_save_path", None)),
        "save_backup_paths": _path_values(
            getattr(args, "native_save_backup_path", None)),
        "history_paths": _path_values(
            getattr(args, "native_history_path", None)),
        "stmp_paths": _path_values(getattr(args, "native_stmp_path", None)),
    }
    missing = [name for name, values in paths.items() if not values]
    if missing:
        raise OrphanCliError(
            "automatic probe requires explicit current_run.save, "
            "current_run.save.backup, history, and .stmp paths; missing "
            + ", ".join(missing))

    def require_basename(name: str, expected: str) -> None:
        for path in paths[name]:
            # A wildcard is allowed in parent/profile components, but the
            # semantic leaf must remain the exact native artifact name.  This
            # blocks accidentally passing the career-wide progress.save file.
            leaf = str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            if leaf.casefold() != expected.casefold():
                raise OrphanCliError(
                    f"{name} must name {expected}; got {path}")

    require_basename("save_paths", "current_run.save")
    require_basename("save_backup_paths", "current_run.save.backup")
    save_set = {str(path.expanduser().resolve()).casefold()
                for path in paths["save_paths"]}
    backup_set = {str(path.expanduser().resolve()).casefold()
                  for path in paths["save_backup_paths"]}
    if save_set & backup_set:
        raise OrphanCliError(
            "current_run.save and current_run.save.backup probes must be distinct")

    def profile_saves_root(path: Path, name: str, *, class_name: str) -> tuple[Path, Path]:
        """Derive and validate the canonical ``profile1/saves`` ancestor."""
        try:
            resolved = path.expanduser().resolve()
        except OSError as exc:
            raise OrphanCliError(f"cannot resolve {name} path {path}: {exc}") from exc
        parts = list(resolved.parts)
        folded = [part.casefold() for part in parts]
        save_indexes = [index for index, part in enumerate(folded)
                        if part == "saves"]
        if not save_indexes:
            raise OrphanCliError(
                f"{name} must be under a profile1/saves directory: {path}")
        save_index = save_indexes[-1]
        if save_index == 0 or folded[save_index - 1] != "profile1":
            raise OrphanCliError(
                f"{name} must be under profile1/saves (not an arbitrary path): {path}")
        tail = folded[save_index + 1:]
        if class_name in {"save", "backup"} and tail and tail[0] == "history":
            raise OrphanCliError(
                f"{name} must be the direct current_run artifact under saves: {path}")
        if class_name == "history":
            if not tail or tail[0] != "history":
                raise OrphanCliError(
                    f"native history must be under profile1/saves/history: {path}")
        if class_name == "stmp":
            leaf = folded[-1]
            if not (tail and tail[0] == "history") and not leaf.endswith(".stmp"):
                raise OrphanCliError(
                    f"native .stmp probe must be a .stmp file/glob under saves/history: {path}")
        root = Path(*parts[:save_index + 1])
        # Negative evidence is meaningful only when the containing saves tree
        # itself exists.  The artifact may be absent, but a misspelled profile
        # or arbitrary empty directory must not masquerade as a clean probe.
        if not root.is_dir():
            raise OrphanCliError(
                f"native probe parent does not exist or is not a directory: {root}")
        if class_name in {"save", "backup"}:
            parent = resolved.parent
            if parent != root:
                raise OrphanCliError(
                    f"{name} must be directly under profile1/saves: {path}")
            if not parent.is_dir():
                raise OrphanCliError(
                    f"{name} parent is not readable: {parent}")
        elif class_name == "history":
            history_dir = root / "history"
            # If the directory is absent, its parent still proves the profile
            # is real; the probe will record an explicit absent status.  If it
            # exists, it must be a directory.
            if history_dir.exists() and not history_dir.is_dir():
                raise OrphanCliError(
                    f"native history path is not a directory: {history_dir}")
            if resolved != history_dir and not resolved.parent.is_dir():
                raise OrphanCliError(
                    f"native history parent is not readable: {resolved.parent}")
        else:
            # For a wildcard/file, require its static parent.  A directory
            # probe is allowed as long as it is the history directory itself.
            parent = resolved if resolved.is_dir() else resolved.parent
            if not parent.is_dir():
                raise OrphanCliError(
                    f"native .stmp parent is not readable: {parent}")
        return root, resolved

    roots: list[Path] = []
    for path in paths["save_paths"]:
        roots.append(profile_saves_root(
            path, "current_run.save", class_name="save")[0])
    for path in paths["save_backup_paths"]:
        roots.append(profile_saves_root(
            path, "current_run.save.backup", class_name="backup")[0])
    for path in paths["history_paths"]:
        roots.append(profile_saves_root(
            path, "native history", class_name="history")[0])
    for path in paths["stmp_paths"]:
        roots.append(profile_saves_root(
            path, "native .stmp", class_name="stmp")[0])
    canonical_root = str(roots[0]).casefold()
    if any(str(root).casefold() != canonical_root for root in roots[1:]):
        raise OrphanCliError(
            "all native probes must share one canonical profile1/saves root")
    return paths


def _ports_from_args(args: argparse.Namespace) -> tuple[int, ...]:
    value = getattr(args, "api_port", None)
    if value is None:
        return DEFAULT_PORTS
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise OrphanCliError("--api-port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise OrphanCliError("--api-port must be between 1 and 65535")
    return (port,)


def _validate_probe_shape(evidence: Mapping[str, Any], *, require_capture: bool) -> None:
    """Apply the CLI's complete raw-probe contract before rotation normalization.

    ``character_rotation`` intentionally accepts a few historical evidence
    aliases for replay compatibility.  A new live capture/active-run apply is
    stricter: every API freshness field and every native artifact class must be
    present, so an edited/truncated JSON object cannot inherit old defaults.
    """
    api = evidence.get("api")
    if not isinstance(api, Mapping):
        raise OrphanCliError("evidence.api must be an object")
    samples = api.get("samples")
    if not isinstance(samples, list) or len(samples) < 2:
        raise OrphanCliError("evidence.api.samples must contain two frames")
    required_sample = {
        "screen", "run_id", "run", "run_empty", "continue_run",
        "sequence", "observed_at", "state_version",
    }
    for index, sample in enumerate(samples[:8]):
        if not isinstance(sample, Mapping):
            raise OrphanCliError(f"evidence.api.samples[{index}] is not an object")
        missing = sorted(required_sample - set(sample))
        if missing:
            raise OrphanCliError(
                f"evidence.api.samples[{index}] omitted: {', '.join(missing)}")
        if sample.get("run") is not None or sample.get("run_empty") is not True:
            raise OrphanCliError(
                f"evidence.api.samples[{index}] lacks explicit null run proof")
        if sample.get("continue_run") is not False:
            raise OrphanCliError(
                f"evidence.api.samples[{index}] continue_run is not false")
        sequence = sample.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise OrphanCliError(
                f"evidence.api.samples[{index}].sequence is invalid")
        _parse_iso_timestamp(sample.get("observed_at"),
                             label=f"evidence.api.samples[{index}].observed_at")
        version = sample.get("state_version")
        if (isinstance(version, bool) or not isinstance(version, (int, float))
                or not math.isfinite(float(version)) or version < 0):
            raise OrphanCliError(
                f"evidence.api.samples[{index}].state_version must be finite numeric")
    latest = api.get("latest_state_version")
    latest_sample = samples[-1].get("state_version")
    if (isinstance(latest, bool) or not isinstance(latest, (int, float))
            or not math.isfinite(float(latest)) or latest != latest_sample):
        raise OrphanCliError(
            "evidence.api.latest_state_version is missing or stale")

    native = evidence.get("native")
    if not isinstance(native, Mapping):
        raise OrphanCliError("evidence.native must be an object")
    for field in ("save", "save_backup", "history", "stmp"):
        value = native.get(field)
        if not isinstance(value, Mapping) or not isinstance(value.get("status"), str):
            raise OrphanCliError(f"evidence.native.{field} is missing or malformed")
    if native.get("probe_complete") is not True or native.get("read_errors") != []:
        raise OrphanCliError("evidence.native probe is incomplete")
    if native.get("save_match") is not False or native.get("history_match") is not False:
        raise OrphanCliError("evidence native match flags must be explicitly false")
    probe_at = native.get("probe_observed_at")
    _probe_text, probe_unix = _parse_iso_timestamp(
        probe_at, label="evidence.native.probe_observed_at")
    latest_sample_at = _parse_iso_timestamp(
        samples[-1].get("observed_at"),
        label="evidence.api.samples[-1].observed_at")[1]
    if probe_unix < latest_sample_at:
        raise OrphanCliError("evidence.native probe predates the latest API frame")
    probe_version = native.get("api_state_version")
    if (isinstance(probe_version, bool) or not isinstance(probe_version, (int, float))
            or not math.isfinite(float(probe_version))
            or probe_version != latest_sample):
        raise OrphanCliError(
            "evidence.native.api_state_version is missing or stale")
    checked = native.get("checked_paths")
    if not isinstance(checked, list) or not checked or len(checked) > 32:
        raise OrphanCliError("evidence.native.checked_paths is missing or oversized")
    required_kinds = {
        "current_run.save", "current_run.save.backup", "history", "stmp",
    }
    rows_by_kind: dict[str, list[Mapping[str, Any]]] = {kind: []
                                                         for kind in required_kinds}
    allowed_statuses = {"absent", "empty", "zero_byte", "no_matching_run", "missing"}
    roots: list[str] = []

    def path_semantics(raw_path: Any, kind: str, index: int) -> str:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise OrphanCliError(
                f"evidence.native.checked_paths[{index}].path is missing")
        text = raw_path.strip().replace("\\", "/")
        parsed = Path(raw_path.strip())
        if not parsed.is_absolute():
            raise OrphanCliError(
                f"evidence.native.checked_paths[{index}].path must be absolute")
        parts = [part.casefold() for part in text.split("/") if part]
        try:
            profile_index = parts.index("profile1")
            if profile_index + 1 >= len(parts) or parts[profile_index + 1] != "saves":
                raise ValueError
            root_parts = parts[:profile_index + 2]
            tail = parts[profile_index + 2:]
        except ValueError as exc:
            raise OrphanCliError(
                f"checked path {index} is not under profile1/saves: {raw_path}") from exc
        if kind in {"current_run.save", "current_run.save.backup"}:
            expected = kind
            if tail != [expected]:
                raise OrphanCliError(
                    f"checked path {index} is not the exact {expected} artifact")
        elif kind == "history":
            if not tail or tail[0] != "history":
                raise OrphanCliError(
                    f"checked history path {index} is outside profile1/saves/history")
        else:
            if not tail or tail[0] != "history":
                raise OrphanCliError(
                    f"checked .stmp path {index} is outside profile1/saves/history")
            leaf = tail[-1]
            if len(tail) > 1 and not (
                    leaf.endswith(".stmp") or any(mark in leaf for mark in ("*", "?", "["))):
                raise OrphanCliError(
                    f"checked .stmp path {index} has an unexpected leaf")
        return "/".join(root_parts)

    for index, row in enumerate(checked):
        if not isinstance(row, Mapping):
            raise OrphanCliError(f"evidence.native.checked_paths[{index}] is malformed")
        kind_raw = row.get("kind")
        if not isinstance(kind_raw, str) or kind_raw.casefold() not in required_kinds:
            raise OrphanCliError(
                f"evidence.native.checked_paths[{index}] must use one exact native kind")
        kind = kind_raw.casefold()
        status = row.get("status")
        if not isinstance(status, str) or status.casefold() not in allowed_statuses:
            raise OrphanCliError(
                f"evidence.native.checked_paths[{index}] has an unsupported status")
        roots.append(path_semantics(row.get("path"), kind, index))
        rows_by_kind[kind].append(row)
    if set(kind for kind, rows in rows_by_kind.items() if rows) != required_kinds:
        missing = sorted(kind for kind, rows in rows_by_kind.items() if not rows)
        raise OrphanCliError(
            "evidence.native.checked_paths is missing exact class(es): "
            + ", ".join(missing))
    if len(set(roots)) != 1:
        raise OrphanCliError(
            "all checked native paths must share one profile1/saves root")

    # Summary fields must agree with the rows, rather than being trusted flags
    # that an edited JSON file can set independently.
    for field, kind in (("save", "current_run.save"),
                        ("save_backup", "current_run.save.backup"),
                        ("history", "history"), ("stmp", "stmp")):
        expected_status = _aggregate_summaries(rows_by_kind[kind])["status"]
        actual_status = str(native[field]["status"]).casefold()
        if actual_status not in allowed_statuses or actual_status != expected_status:
            raise OrphanCliError(
                f"evidence.native.{field}.status disagrees with checked paths")
    if require_capture:
        _capture_metadata(evidence)


def run_once(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """Execute one capture/preview/apply operation and return JSON data."""
    capture_mode = bool(getattr(args, "capture", False))
    apply_requested = bool(getattr(args, "apply", False))
    evidence_arg = getattr(args, "evidence_file", None)
    if capture_mode and (apply_requested or evidence_arg is not None):
        # Capture is intentionally a separate, read-only phase.  Requiring a
        # second invocation for apply prevents an operator from accidentally
        # releasing a run while the game is still alive.
        stack_root_hint = _resolve_stack_root()
    else:
        stack_root_hint = None
    stack_root_value = getattr(args, "stack_root", None)
    stack_root = (Path(stack_root_value).expanduser().resolve()
                  if stack_root_value else (stack_root_hint or _resolve_stack_root()))
    runtime_value = getattr(args, "runtime_dir", None)
    runtime_dir = (Path(runtime_value).expanduser().resolve()
                   if runtime_value else stack_root / ".runtime")
    knowledge_value = getattr(args, "knowledge_root", None)
    knowledge_root = (Path(knowledge_value).expanduser().resolve()
                      if knowledge_value else stack_root / "knowledge")
    base: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "operation": "release_orphan_run_once",
        "ok": False,
        "applied": False,
        "dry_run": not apply_requested,
        "mode": "capture" if capture_mode else ("apply" if apply_requested else "preview"),
        "stack_stopped": False,
        "stack_root": str(stack_root),
        "runtime_dir": str(runtime_dir),
        "knowledge_root": str(knowledge_root),
        "evidence_source": None,
    }
    guard = None
    locked = False
    try:
        if capture_mode and (apply_requested or evidence_arg is not None):
            raise OrphanCliError(
                "--capture is read-only and cannot be combined with --apply or --evidence-file")
        guard = lifecycle_lock(runtime_dir)
        guard.__enter__()
        locked = True
        if capture_mode:
            # Hold the lifecycle lock across the session read, both API frames,
            # and all native probes.  Stop-Agent cannot publish a stop boundary
            # until this capture is complete, eliminating a TOCTOU window.
            binding = _capture_session_binding(runtime_dir, stack_root)
            identity = _rotation_identity(knowledge_root)
            base["rotation"] = identity
            active_run_id = str(identity.get("active_run_id") or "").strip()
            active_character_id = str(identity.get("active_character_id") or "").strip()
            if not active_run_id or not active_character_id:
                raise OrphanCliError(
                    "capture requires an exact active run in rotation state")
            expected_character = canonical_character_id(active_character_id)
            if expected_character is None:
                raise OrphanCliError("active rotation character identity is unsupported")
            native_paths = _native_cli_paths(args)
            evidence, base_url = collect_api_evidence(
                active_run_id, active_character_id,
                ports=_ports_from_args(args), delay=float(
                    getattr(args, "sample_delay", DEFAULT_SAMPLE_DELAY)),
                session_binding=binding, **native_paths)
            # Do not emit a capture that the durable transaction would reject.
            _validate_probe_shape(evidence, require_capture=True)
            normalized = _validate_orphan_evidence(
                evidence, active_run_id, expected_character, active_character_id)
            base.update({
                "ok": True,
                "captured": True,
                "evidence_source": "api-native-readonly",
                "api_base_url": base_url,
                "capture": evidence.get("capture"),
                "evidence": evidence,
                "validated_evidence": normalized,
            })
            return 0, base

        # Every non-capture path is a stopped-stack operation.  The lock is
        # acquired first, so the stopped check and subsequent validation/apply
        # are one lifecycle-critical section.
        assert_stack_stopped(runtime_dir)
        base["stack_stopped"] = True
        identity = _rotation_identity(knowledge_root)
        base["rotation"] = identity

        if evidence_arg is not None:
            evidence_file = Path(evidence_arg).expanduser()
            if str(evidence_file) != "-":
                evidence_file = evidence_file.resolve()
        else:
            evidence_file = None
        auto_options = any(
            getattr(args, name, None) is not None
            for name in (
                "api_port", "native_save_path", "native_save_backup_path",
                "native_history_path", "native_stmp_path"))
        if evidence_file is not None:
            if auto_options:
                raise OrphanCliError(
                    "--evidence-file cannot be combined with API/native probe options")
            evidence = _read_evidence_argument(evidence_file)
            base["evidence_source"] = "stdin" if str(evidence_file) == "-" else "file"
        else:
            active_run_id = str(identity.get("active_run_id") or "").strip()
            active_character_id = str(identity.get("active_character_id") or "").strip()
            if not active_run_id or not active_character_id:
                raise OrphanCliError(
                    "automatic probe requires an exact active run in rotation state")
            native_paths = _native_cli_paths(args)
            evidence, base_url = collect_api_evidence(
                active_run_id, active_character_id,
                ports=_ports_from_args(args),
                delay=float(getattr(args, "sample_delay", DEFAULT_SAMPLE_DELAY)),
                **native_paths,
            )
            base["evidence_source"] = "api-native-readonly"
            base["api_base_url"] = base_url

        if not isinstance(evidence, Mapping):
            raise OrphanCliError("evidence must be a JSON object")
        run_id = str(evidence.get("run_id") or "").strip()
        character_id = str(evidence.get("character_id") or "").strip()
        requested_run_id = getattr(args, "run_id", None)
        if requested_run_id and str(requested_run_id).strip() != run_id:
            raise OrphanCliError("--run-id does not match evidence.run_id")
        if not run_id or not character_id:
            raise OrphanCliError("evidence must carry exact run_id and character_id")
        base["run_id"] = run_id
        base["character_id"] = character_id

        active_run_id = identity.get("active_run_id")
        active_character_id = identity.get("active_character_id")
        if active_run_id:
            if run_id != active_run_id or character_id != active_character_id:
                raise OrphanCliError(
                    "evidence identity does not match the exact active rotation slot")
            # A file/stdin supplied for an active run must come from the
            # read-only capture phase of this exact GUID session and must have
            # crossed its matching Stop-Agent sentinel.  This rejects stale
            # JSON copied from an earlier session, while automatic probing in
            # this invocation remains inherently fresh.
            if apply_requested and evidence_file is not None:
                capture = _capture_metadata(evidence)
                expected_digest = str(capture["evidence_sha256"]).strip().lower()
                if not hmac.compare_digest(_evidence_digest(evidence), expected_digest):
                    raise OrphanCliError(
                        "capture evidence_sha256 does not match the evidence body")
                _assert_capture_stopped(capture, runtime_dir)
                base["capture"] = dict(capture)
            expected_character = canonical_character_id(active_character_id)
            if expected_character is None:
                raise OrphanCliError("active rotation character identity is unsupported")
            normalized = _validate_orphan_evidence(
                evidence, active_run_id, expected_character, active_character_id)
            if apply_requested:
                _validate_probe_shape(evidence, require_capture=False)
        else:
            if run_id not in identity["orphaned_run_ids"]:
                raise OrphanCliError(
                    "no exact active run; idempotent replay is allowed only for a known orphan ledger row")
            expected_character = canonical_character_id(character_id)
            if expected_character is None:
                raise OrphanCliError("evidence character identity is unsupported")
            normalized = _validate_orphan_evidence(
                evidence, run_id, expected_character, character_id)
            base["idempotent_replay"] = True
        base["validated_evidence"] = normalized

        if not apply_requested:
            base.update({"ok": True, "would_apply": bool(active_run_id), "applied": False})
            return 0, base

        # The helper owns all Knowledge/rotation writes and its own idempotence
        # rules.  No JSON file is edited by this CLI.
        result = release_orphan_run_once(knowledge_root, normalized)
        base.update({"ok": True, "applied": True, "result": _normalise_result(result)})
        return 0, base
    except (OrphanCliError, CharacterRotationError, OSError, ValueError, TypeError) as exc:
        base["error"] = {"type": type(exc).__name__, "message": str(exc)}
        return 2, base
    finally:
        if locked and guard is not None:
            guard.__exit__(None, None, None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture, preview, or explicitly apply one evidence-backed orphan-run "
            "release. Capture runs while the stack is live; preview/apply run "
            "only after Stop-Agent.ps1. This command never sends game actions."),
    )
    parser.add_argument("--stack-root", type=Path,
                        help="canonical sts2-ascend root (default: script parent)")
    parser.add_argument("--runtime-dir", type=Path,
                        help="lifecycle runtime directory (default: <stack-root>/.runtime)")
    parser.add_argument("--knowledge-root", type=Path,
                        help="Knowledge root (default: <stack-root>/knowledge)")
    parser.add_argument("--evidence-file", type=Path,
                        help="read-only JSON evidence file (use - for stdin)")
    parser.add_argument(
        "--capture", action="store_true",
        help=("capture two GET /state + /actions/available frames and native "
              "artifacts while the current GUID session is running; emit JSON "
              "for a later stopped-stack --apply"))
    parser.add_argument("--run-id", help="optional exact run-id assertion")
    parser.add_argument("--api-port", type=int,
                        help="single localhost API port for automatic read-only probing")
    parser.add_argument("--sample-delay", type=float, default=DEFAULT_SAMPLE_DELAY,
                        help="seconds between the two GET /state samples (0.1..30)")
    parser.add_argument(
        "--native-save-path", action="append", type=Path, metavar="PATH",
        help=("explicit current_run.save candidate; repeat for every primary "
              "native save path"))
    parser.add_argument(
        "--native-save-backup-path", action="append", type=Path, metavar="PATH",
        help=("explicit current_run.save.backup candidate; repeat for every "
              "backup path"))
    parser.add_argument(
        "--native-history-path", action="append", type=Path, metavar="PATH",
        help=("explicit native run-history file/directory; repeat for every "
              "profile/slot"))
    parser.add_argument(
        "--native-stmp-path", action="append", type=Path, metavar="PATH",
        help=("explicit .stmp file/directory/glob; repeat for every candidate"))
    parser.add_argument("--apply", action="store_true",
                        help="apply the validated transaction; default is read-only preview")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    code, payload = run_once(args)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
