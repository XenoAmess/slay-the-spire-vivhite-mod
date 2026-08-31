#!/usr/bin/env python3
"""Archive and reset one character's statistical baseline while the stack is stopped."""
from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STACK_ROOT = SCRIPT_DIR.parent
BRAIN_DIR = DEFAULT_STACK_ROOT / "brain"
if str(BRAIN_DIR) not in sys.path:
    sys.path.insert(0, str(BRAIN_DIR))

from character_profiles import ProfileStore  # noqa: E402
from character_rotation import (  # noqa: E402
    CATCHUP_MODE,
    VIVHITE,
    CharacterRotationError,
    _validated_v2_state,
)
from knowledge import DEFAULT_PROGRESSION, DEFAULT_STATS  # noqa: E402

CONFIRMATION = "RESET-VIVHITE-STATISTICS"
EMPTY_REVIEW_QUEUE = {"pending": [], "reviewing": None}
SUPPORTED_PROFILES = ("vivhite",)
ROTATION_FILENAME = "character_rotation.json"
PROGRESSION_FILENAME = "progression.json"
PROGRESSION_GAMEPLAY_AGGREGATES = (
    "wins_by_ascension",
    "runs_by_ascension",
    "best_floor_by_ascension",
)
PROGRESSION_RUN_CURSORS = (
    "last_llm_review_run",
    "last_successful_review_run",
    "last_fallback_review_run",
)
TARGETS = (
    ("stats.json", "file"),
    ("runs", "directory"),
    (".active_run_learning.json", "file"),
    ("review_queue.json", "file"),
    (PROGRESSION_FILENAME, "file"),
)
ARCHIVE_TARGETS = TARGETS + ((ROTATION_FILENAME, "file"),)


class ResetError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResetResult:
    profile: str
    archive_dir: Path


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=1) + "\n"
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False,
                dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextmanager
def _lifecycle_lock(runtime_dir: Path):
    """Exclude Start-Agent/Stop-Agent while the reset transaction runs."""
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / "lifecycle.lock"
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = (
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel32.CreateFileW(str(path), 0xC0000000, 0, None, 4, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ResetError("Start-Agent/Stop-Agent is currently running")
        try:
            yield
        finally:
            kernel32.CloseHandle(handle)
        return
    handle = path.open("a+b")
    try:
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ResetError("Start-Agent/Stop-Agent is currently running") from exc
        yield
    finally:
        handle.close()


def _assert_stack_stopped(stack_root: Path) -> None:
    runtime = stack_root / ".runtime"
    if (runtime / "session.json").exists():
        raise ResetError(
            "sts2-ascend is not cleanly stopped; run scripts/Stop-Agent.ps1 first")
    for pid_path in sorted(runtime.glob("*.pid")):
        try:
            raw = pid_path.read_text(encoding="utf-8").strip()
            value = json.loads(raw)
            pid = int(value.get("pid", 0)) if isinstance(value, dict) else int(value)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ResetError(f"cannot verify stale PID record: {pid_path}") from exc
        if _pid_alive(pid):
            raise ResetError(f"sts2-ascend process is still alive (pid {pid})")


def _archive_inventory(archive_dir: Path, present: dict[str, bool]) -> tuple[dict, str]:
    artifacts: dict[str, object] = {}
    checksum_lines: list[str] = []
    for name, kind in ARCHIVE_TARGETS:
        target = archive_dir / name
        item: dict[str, object] = {"kind": kind, "present": present[name]}
        if present[name] and kind == "file":
            item.update({"bytes": target.stat().st_size, "sha256": _sha256(target)})
            checksum_lines.append(f"{item['sha256']}  {name}\n")
        elif present[name]:
            files = []
            for child in sorted(p for p in target.rglob("*") if p.is_file()):
                relative = child.relative_to(archive_dir).as_posix()
                row = {"path": relative, "bytes": child.stat().st_size,
                       "sha256": _sha256(child)}
                files.append(row)
                checksum_lines.append(f"{row['sha256']}  {relative}\n")
            item.update({"file_count": len(files), "files": files})
        artifacts[name] = item
    checksum_text = "".join(sorted(checksum_lines))
    (archive_dir / "SHA256SUMS").write_text(checksum_text, encoding="utf-8", newline="\n")
    return artifacts, hashlib.sha256(checksum_text.encode("utf-8")).hexdigest()


def _prepare_rotation_reset(rotation_path: Path) -> dict:
    """Validate and prepare a fresh catch-up cycle without mutating the file."""
    if not rotation_path.is_file():
        raise ResetError(f"rotation state is missing or not a file: {rotation_path}")
    try:
        raw = json.loads(rotation_path.read_text(encoding="utf-8-sig"))
        validated = _validated_v2_state(raw, rotation_path)
    except (OSError, UnicodeError, json.JSONDecodeError,
            CharacterRotationError) as exc:
        raise ResetError(f"cannot validate rotation state: {exc}") from exc

    if validated["schedule_mode"] != CATCHUP_MODE:
        raise ResetError(
            "rotation cycle can only be reset while schedule_mode is "
            f"{CATCHUP_MODE}")
    active = validated["active_run"]
    if active is not None and active["character"] != VIVHITE:
        raise ResetError(
            "rotation cycle cannot be reset while the active run is not Vivhite")

    updated = copy.deepcopy(raw)
    updated["catchup_index"] = 0
    updated["next_character"] = VIVHITE
    updated["catchup_completed"] = False
    if active is not None:
        # The already-running Vivhite game is slot zero of the new 4:1 cycle.
        updated_active = copy.deepcopy(updated["active_run"])
        updated_active["scheduled_character"] = VIVHITE
        updated["active_run"] = updated_active
    try:
        _validated_v2_state(updated, rotation_path)
    except CharacterRotationError as exc:
        raise ResetError(f"prepared rotation state is invalid: {exc}") from exc
    return updated


def _prepare_progression_reset(
        progression_path: Path, *, character_id: str) -> dict:
    """Clear run/floor aggregates while preserving strategy and review state."""
    if progression_path.exists() and not progression_path.is_file():
        raise ResetError(
            f"progression state is not a file: {progression_path}")
    if progression_path.is_file():
        try:
            raw = json.loads(progression_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResetError(f"cannot read progression state: {exc}") from exc
        if not isinstance(raw, dict):
            raise ResetError("progression state must be a JSON object")
        updated = copy.deepcopy(raw)
    else:
        updated = copy.deepcopy(DEFAULT_PROGRESSION)
        updated["character"] = character_id

    # Preserve all known and future non-gameplay keys.  Only aggregates whose
    # writers are run finalization, plus run-number review cursors invalidated by
    # the new zero-based stats/review queue, are rebased.
    for key, value in DEFAULT_PROGRESSION.items():
        default_value = character_id if key == "character" else value
        updated.setdefault(key, copy.deepcopy(default_value))
    for key in PROGRESSION_GAMEPLAY_AGGREGATES:
        updated[key] = {}
    updated["last_llm_review_run"] = 0
    updated["last_successful_review_run"] = 0
    for key in PROGRESSION_RUN_CURSORS:
        if key in updated:
            updated[key] = 0
    if "review_closure_last_runs" in updated:
        updated["review_closure_last_runs"] = []

    character = updated.get("character")
    current_ascension = updated.get("current_ascension")
    max_goal = updated.get("max_ascension_goal")
    if not isinstance(character, str) or not character.strip():
        raise ResetError("progression.character must be a non-empty string")
    for label, value in (
            ("current_ascension", current_ascension),
            ("max_ascension_goal", max_goal)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ResetError(f"progression.{label} must be a non-negative integer")
    return updated


def reset_rotation_cycle(
        stack_root: Path, profile: str, confirmation: str,
        *, now: datetime | None = None) -> ResetResult:
    """Archive and reset only the durable 4:1 cycle, never profile statistics."""
    stack_root = Path(stack_root).resolve()
    if profile not in SUPPORTED_PROFILES:
        raise ResetError("only --profile vivhite is supported")
    if confirmation != CONFIRMATION:
        raise ResetError(f"confirmation must be exactly {CONFIRMATION}")

    knowledge_root = stack_root / "knowledge"
    with _lifecycle_lock(stack_root / ".runtime"):
        _assert_stack_stopped(stack_root)
        rotation_path = knowledge_root / ROTATION_FILENAME
        updated_rotation = _prepare_rotation_reset(rotation_path)

        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        stamp = instant.strftime("%Y%m%dT%H%M%S.%fZ")
        archive_dir = knowledge_root / "rotation_reset_archives" / profile / stamp
        suffix = 0
        while archive_dir.exists():
            suffix += 1
            archive_dir = archive_dir.with_name(f"{stamp}-{suffix:02d}")
        archive_dir.mkdir(parents=True)
        manifest = {
            "schema": "sts2-ascend-rotation-reset/v1",
            "status": "prepared",
            "profile": profile,
            "created_at_utc": instant.isoformat().replace("+00:00", "Z"),
            "rotation_path": ROTATION_FILENAME,
        }
        _atomic_write_json(archive_dir / "manifest.json", manifest)

        archived_rotation = archive_dir / ROTATION_FILENAME
        original_moved = False
        try:
            rotation_path.rename(archived_rotation)
            original_moved = True
            original_sha256 = _sha256(archived_rotation)
            checksum_text = f"{original_sha256}  {ROTATION_FILENAME}\n"
            (archive_dir / "SHA256SUMS").write_text(
                checksum_text, encoding="utf-8", newline="\n")
            manifest.update({
                "status": "archived",
                "artifact": {
                    "path": ROTATION_FILENAME,
                    "bytes": archived_rotation.stat().st_size,
                    "sha256": original_sha256,
                },
                "checksums": {
                    "file": "SHA256SUMS",
                    "sha256": hashlib.sha256(
                        checksum_text.encode("utf-8")).hexdigest(),
                },
            })
            _atomic_write_json(archive_dir / "manifest.json", manifest)

            _atomic_write_json(rotation_path, updated_rotation)
            manifest.update({
                "status": "completed",
                "new_rotation_sha256": _sha256(rotation_path),
            })
            _atomic_write_json(archive_dir / "manifest.json", manifest)
            return ResetResult(profile=profile, archive_dir=archive_dir)
        except Exception as exc:
            rollback_errors: list[str] = []
            if original_moved:
                try:
                    _remove(rotation_path)
                except OSError as rollback_exc:
                    rollback_errors.append(
                        f"remove replacement {ROTATION_FILENAME}: {rollback_exc}")
                try:
                    if rotation_path.exists():
                        raise OSError("restore destination already exists")
                    archived_rotation.rename(rotation_path)
                except OSError as rollback_exc:
                    rollback_errors.append(
                        f"restore {ROTATION_FILENAME}: {rollback_exc}")
            manifest.update({
                "status": "rolled_back" if not rollback_errors
                          else "rollback_incomplete",
                "error": f"{type(exc).__name__}: {exc}",
                "rollback_errors": rollback_errors,
            })
            try:
                _atomic_write_json(archive_dir / "manifest.json", manifest)
            except OSError:
                pass
            detail = "; ".join(rollback_errors) if rollback_errors else "rollback completed"
            raise ResetError(f"rotation reset failed ({detail}): {exc}") from exc


def reset_profile_statistics(
        stack_root: Path, profile: str, confirmation: str,
        *, now: datetime | None = None) -> ResetResult:
    stack_root = Path(stack_root).resolve()
    if profile not in SUPPORTED_PROFILES:
        raise ResetError("only --profile vivhite is supported")
    if confirmation != CONFIRMATION:
        raise ResetError(f"confirmation must be exactly {CONFIRMATION}")

    knowledge_root = stack_root / "knowledge"
    profile_binding = ProfileStore(knowledge_root).resolve(profile)
    profile_root = profile_binding.root
    with _lifecycle_lock(stack_root / ".runtime"):
        _assert_stack_stopped(stack_root)
        rotation_path = knowledge_root / ROTATION_FILENAME
        updated_rotation = _prepare_rotation_reset(rotation_path)
        progression_path = profile_root / PROGRESSION_FILENAME
        updated_progression = _prepare_progression_reset(
            progression_path, character_id=profile_binding.character_id)
        profile_root.mkdir(parents=True, exist_ok=True)
        present: dict[str, bool] = {}
        for name, kind in TARGETS:
            source = profile_root / name
            present[name] = source.exists()
            if source.exists() and ((kind == "file" and not source.is_file()) or
                                    (kind == "directory" and not source.is_dir())):
                raise ResetError(f"unexpected artifact type: {source}")
        present[ROTATION_FILENAME] = True

        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        stamp = instant.strftime("%Y%m%dT%H%M%S.%fZ")
        archive_dir = knowledge_root / "profile_reset_archives" / profile / stamp
        suffix = 0
        while archive_dir.exists():
            suffix += 1
            archive_dir = archive_dir.with_name(f"{stamp}-{suffix:02d}")
        archive_dir.mkdir(parents=True)
        manifest = {
            "schema": "sts2-ascend-profile-reset/v3", "status": "prepared",
            "profile": profile,
            "created_at_utc": instant.isoformat().replace("+00:00", "Z"),
            "profile_root": f"profiles/{profile}",
            "rotation_path": ROTATION_FILENAME,
            "moved": [],
        }
        _atomic_write_json(archive_dir / "manifest.json", manifest)
        moved: list[str] = []
        baseline_started = False
        try:
            for name, _kind in TARGETS:
                if not present[name]:
                    continue
                (profile_root / name).rename(archive_dir / name)
                moved.append(name)
                manifest["moved"] = list(moved)
                _atomic_write_json(archive_dir / "manifest.json", manifest)
            rotation_path.rename(archive_dir / ROTATION_FILENAME)
            moved.append(ROTATION_FILENAME)
            manifest["moved"] = list(moved)
            _atomic_write_json(archive_dir / "manifest.json", manifest)

            artifacts, checksum_hash = _archive_inventory(archive_dir, present)
            manifest.update({"status": "archived", "artifacts": artifacts,
                             "checksums": {"file": "SHA256SUMS",
                                           "sha256": checksum_hash}})
            _atomic_write_json(archive_dir / "manifest.json", manifest)

            baseline_started = True
            _atomic_write_json(profile_root / "stats.json", copy.deepcopy(DEFAULT_STATS))
            (profile_root / "runs").mkdir()
            _atomic_write_json(profile_root / "review_queue.json", EMPTY_REVIEW_QUEUE)
            _atomic_write_json(progression_path, updated_progression)
            _atomic_write_json(rotation_path, updated_rotation)
            manifest.update({
                "status": "completed",
                "new_baseline": {
                    "stats_sha256": _sha256(profile_root / "stats.json"),
                    "review_queue_sha256": _sha256(profile_root / "review_queue.json"),
                    "progression_sha256": _sha256(progression_path),
                    "runs_file_count": 0,
                    "rotation_sha256": _sha256(rotation_path),
                },
            })
            _atomic_write_json(archive_dir / "manifest.json", manifest)
            return ResetResult(profile=profile, archive_dir=archive_dir)
        except Exception as exc:
            rollback_errors: list[str] = []
            if baseline_started:
                for name in (
                        "stats.json", "runs", "review_queue.json",
                        PROGRESSION_FILENAME):
                    try:
                        _remove(profile_root / name)
                    except OSError as rollback_exc:
                        rollback_errors.append(f"remove {name}: {rollback_exc}")
                try:
                    _remove(rotation_path)
                except OSError as rollback_exc:
                    rollback_errors.append(
                        f"remove {ROTATION_FILENAME}: {rollback_exc}")
            for name in reversed(moved):
                try:
                    source = (rotation_path if name == ROTATION_FILENAME
                              else profile_root / name)
                    if source.exists():
                        raise OSError("restore destination already exists")
                    (archive_dir / name).rename(source)
                except OSError as rollback_exc:
                    rollback_errors.append(f"restore {name}: {rollback_exc}")
            manifest.update({
                "status": "rolled_back" if not rollback_errors else "rollback_incomplete",
                "error": f"{type(exc).__name__}: {exc}",
                "rollback_errors": rollback_errors,
            })
            try:
                _atomic_write_json(archive_dir / "manifest.json", manifest)
            except OSError:
                pass
            detail = "; ".join(rollback_errors) if rollback_errors else "rollback completed"
            raise ResetError(f"reset failed ({detail}): {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=SUPPORTED_PROFILES)
    parser.add_argument("--confirm", required=True, help=f"must be exactly {CONFIRMATION}")
    parser.add_argument(
        "--rotation-only", action="store_true",
        help="archive and reset only character_rotation.json; preserve all statistics")
    parser.add_argument("--stack-root", type=Path, default=DEFAULT_STACK_ROOT,
                        help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        operation = reset_rotation_cycle if args.rotation_only else reset_profile_statistics
        result = operation(args.stack_root, args.profile, args.confirm)
    except ResetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    label = "Rotation reset" if args.rotation_only else "Reset"
    print(f"{label} complete for {result.profile}; archive: {result.archive_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
