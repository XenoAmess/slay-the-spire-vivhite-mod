"""Safely compact sts2-ascend's append-only knowledge history.

The online learner consumes ``stats.json``, ``policy.json`` and
``progression.json`` directly.  Old ``runs/*.json`` files are valuable raw
evidence, but keeping every full decision trace in the active working set makes
repository scans and LLM reviews increasingly expensive.  This tool moves old
raw traces into a verified ZIP archive while retaining a deliberately broad
working set of recent and exceptional runs.

Safety properties:

* dry-run is the default; ``--apply`` is explicit;
* apply refuses to run while the brain/reviewer appears active;
* every source is hashed before archiving and every ZIP member is read back and
  hashed before the archive is atomically published;
* the manifest is atomically published before any source is removed;
* source hashes are checked again immediately before removal;
* repeated apply is a no-op until enough new history accumulates;
* ZIP member names are generated and validated as safe relative POSIX paths.

The existing Git history is intentionally untouched.  Compaction reduces the
current checkout and future prompt/search cost; ordinary deletion cannot shrink
objects already present in Git history.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import time
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterator


SCHEMA_VERSION = 1
DEFAULT_KEEP_RECENT = 96
DEFAULT_DEEP_FLOOR = 33
DEFAULT_KEEP_LONGEST = 12
DEFAULT_KEEP_LARGEST = 8
DEFAULT_KEEP_LESSONS = 96
DEFAULT_KEEP_META_REVIEWS = 32

MANIFEST_REL = Path("archive") / "manifest.json"
CATALOG_REL = Path("archive") / "run_catalog.jsonl"
LOCK_NAME = ".compact.lock"
_KNOWLEDGE_STORE_MARKERS = frozenset({
    "stats.json",
    "progression.json",
    "policy.json",
    "lessons.md",
})
_KNOWLEDGE_STORE_SCAN_PRUNE = frozenset({
    ".runtime",
    "archive",
    "code_backups",
    "game",
    "runs",
})


@dataclass(frozen=True)
class CompactionOptions:
    keep_recent: int = DEFAULT_KEEP_RECENT
    deep_floor: int = DEFAULT_DEEP_FLOOR
    keep_longest: int = DEFAULT_KEEP_LONGEST
    keep_largest: int = DEFAULT_KEEP_LARGEST
    keep_floor_representatives: bool = True
    keep_lessons: int = DEFAULT_KEEP_LESSONS
    keep_meta_reviews: int = DEFAULT_KEEP_META_REVIEWS

    def selection_rules(self) -> dict:
        return {
            "recent_files": max(0, int(self.keep_recent)),
            "deep_floor_at_least": max(0, int(self.deep_floor)),
            "keep_all_victories": True,
            "keep_all_in_progress": True,
            "longest_decision_traces": max(0, int(self.keep_longest)),
            "largest_raw_files": max(0, int(self.keep_largest)),
            "one_representative_per_floor": bool(self.keep_floor_representatives),
            "keep_invalid_and_zero_decision_anomalies": True,
            "lessons_recent_sections": max(0, int(self.keep_lessons)),
            "lessons_pin_brain_sections": True,
            "meta_review_recent_sections": max(0, int(self.keep_meta_reviews)),
        }


@dataclass
class RunRecord:
    path: Path
    name: str
    raw: bytes
    sha256: str
    size: int
    valid: bool
    summary: dict
    error: str | None = None


@dataclass
class MarkdownPlan:
    path: Path
    name: str
    original: bytes
    compacted: bytes
    original_sha256: str
    compacted_sha256: str
    sections: int
    kept_sections: int
    removed_headings: list[str]
    rule: dict

    @property
    def changed(self) -> bool:
        return self.original != self.compacted


@dataclass
class CompactionPlan:
    root: Path
    options: CompactionOptions
    runs: list[RunRecord]
    keep_reasons: dict[str, list[str]]
    archive_new: list[RunRecord]
    archive_duplicates: list[RunRecord]
    markdown: list[MarkdownPlan]
    manifest: dict
    archived_by_name: dict[str, dict]
    stats_sha256: str | None
    runtime_logs: list[dict]
    profile_plans: list["CompactionPlan"] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def kept(self) -> list[RunRecord]:
        names = set(self.keep_reasons)
        return [r for r in self.runs if r.name in names]

    @property
    def local_changes_history(self) -> bool:
        return bool(self.archive_new or self.archive_duplicates or
                    any(m.changed for m in self.markdown))

    @property
    def changes_history(self) -> bool:
        return self.local_changes_history or any(
            plan.changes_history for plan in self.profile_plans)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(data, *, indent: int | None = 2) -> bytes:
    if indent is None:
        text = json.dumps(data, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    else:
        text = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=indent)
    return (text + "\n").encode("utf-8")


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _write_if_changed(path: Path, raw: bytes) -> bool:
    try:
        if path.read_bytes() == raw:
            return False
    except OSError:
        pass
    _atomic_write(path, raw)
    return True


def _safe_zip_member(name: str) -> str:
    """Validate and normalize an archive member; reject traversal/drive paths."""
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError(f"unsafe ZIP member: {name!r}")
    posix = PurePosixPath(name)
    if posix.is_absolute() or any(part in ("", ".", "..") for part in posix.parts):
        raise ValueError(f"unsafe ZIP member: {name!r}")
    normalized = posix.as_posix()
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"unsafe ZIP member: {name!r}")
    return normalized


def _decision_list(data: dict) -> list[dict]:
    value = data.get("decisions")
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _run_summary(data: dict, name: str, size: int, sha256: str) -> dict:
    decisions = _decision_list(data)
    trail_floor = max((int(row.get("floor") or 0) for row in decisions), default=0)
    floor = max(int(data.get("floor") or 0), trail_floor)
    game_over = [row for row in decisions if row.get("screen") == "GAME_OVER"]
    victory = bool(data.get("victory")) or any(
        "胜利" in str(row.get("reason") or "") for row in game_over)
    notes = data.get("combat_notes") if isinstance(data.get("combat_notes"), list) else []
    last_reason = ""
    if game_over:
        last_reason = str(game_over[-1].get("reason") or "")
    elif decisions:
        last_reason = str(decisions[-1].get("reason") or "")
    return {
        "file": name,
        "sha256": sha256,
        "bytes": size,
        "run_id": data.get("run_id"),
        "run_number": data.get("run_number"),
        "started_at": data.get("started_at"),
        "ascension": data.get("ascension"),
        "victory": victory,
        "in_progress": bool(data.get("in_progress")),
        "floor": floor,
        "decisions": len(decisions),
        "combat_notes": len(notes),
        "last_screen": decisions[-1].get("screen") if decisions else None,
        "last_reason": last_reason[:320],
        "phantom_candidate": not decisions and not victory,
    }


def _scan_runs(root: Path) -> list[RunRecord]:
    run_dir = root / "runs"
    records: list[RunRecord] = []
    if not run_dir.exists():
        return records
    for path in sorted(run_dir.glob("*.json"), key=lambda item: item.name):
        raw = path.read_bytes()
        digest = _sha256(raw)
        try:
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("top-level JSON value is not an object")
            summary = _run_summary(data, path.name, len(raw), digest)
            records.append(RunRecord(path, path.name, raw, digest, len(raw), True, summary))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            summary = {
                "file": path.name, "sha256": digest, "bytes": len(raw),
                "valid": False, "error": str(exc)[:240],
            }
            records.append(RunRecord(path, path.name, raw, digest, len(raw), False,
                                     summary, str(exc)))
    return records


def _load_manifest(root: Path) -> dict:
    path = root / MANIFEST_REL
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "batches": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read compaction manifest {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"unsupported compaction manifest schema in {path}")
    if not isinstance(data.get("batches"), list):
        raise RuntimeError(f"invalid compaction manifest batches in {path}")
    return data


def _archived_run_map(manifest: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for batch in manifest.get("batches", []):
        archive = str(batch.get("archive") or "")
        _safe_zip_member(archive)
        for entry in batch.get("runs", []):
            if not isinstance(entry, dict):
                raise RuntimeError("invalid run entry in compaction manifest")
            name = str(entry.get("file") or "")
            if Path(name).name != name or not name.endswith(".json"):
                raise RuntimeError(f"invalid archived run filename: {name!r}")
            _safe_zip_member(str(entry.get("member") or ""))
            prior = out.get(name)
            if prior and prior.get("sha256") != entry.get("sha256"):
                raise RuntimeError(f"conflicting archived hashes for {name}")
            merged = dict(entry)
            merged["archive"] = archive
            out[name] = merged
    return out


def _mark(keep: dict[str, list[str]], record: RunRecord, reason: str) -> None:
    reasons = keep.setdefault(record.name, [])
    if reason not in reasons:
        reasons.append(reason)


def _select_working_set(records: list[RunRecord], options: CompactionOptions) -> dict[str, list[str]]:
    keep: dict[str, list[str]] = {}
    valid = [record for record in records if record.valid]
    for record in records:
        if not record.valid:
            _mark(keep, record, "invalid_json_anomaly")
        elif record.summary.get("phantom_candidate"):
            _mark(keep, record, "zero_decision_anomaly")

    recent_n = max(0, int(options.keep_recent))
    for record in valid[-recent_n:] if recent_n else []:
        _mark(keep, record, "recent")

    for record in valid:
        summary = record.summary
        if summary.get("victory"):
            _mark(keep, record, "victory")
        if summary.get("in_progress"):
            _mark(keep, record, "in_progress")
        if int(summary.get("floor") or 0) >= max(0, int(options.deep_floor)):
            _mark(keep, record, f"deep_floor>={max(0, int(options.deep_floor))}")

    longest_n = max(0, int(options.keep_longest))
    if longest_n:
        longest = sorted(valid, key=lambda r: (int(r.summary.get("decisions") or 0),
                                                r.size, r.name), reverse=True)[:longest_n]
        for record in longest:
            _mark(keep, record, f"top_{longest_n}_longest")

    largest_n = max(0, int(options.keep_largest))
    if largest_n:
        largest = sorted(valid, key=lambda r: (r.size, r.name), reverse=True)[:largest_n]
        for record in largest:
            _mark(keep, record, f"top_{largest_n}_largest")

    if options.keep_floor_representatives:
        by_floor: dict[int, RunRecord] = {}
        for record in valid:
            floor = int(record.summary.get("floor") or 0)
            current = by_floor.get(floor)
            if current is None or (int(record.summary.get("decisions") or 0), record.size,
                                   record.name) > (int(current.summary.get("decisions") or 0),
                                                   current.size, current.name):
                by_floor[floor] = record
        for floor, record in by_floor.items():
            _mark(keep, record, f"floor_{floor}_representative")

    # If future progression adds multiple ascensions, retain the deepest raw
    # trace for each difficulty even when it is below the global deep threshold.
    by_ascension: dict[str, RunRecord] = {}
    for record in valid:
        asc = str(record.summary.get("ascension"))
        current = by_ascension.get(asc)
        if current is None or (int(record.summary.get("floor") or 0),
                               int(record.summary.get("decisions") or 0), record.name) > (
                                   int(current.summary.get("floor") or 0),
                                   int(current.summary.get("decisions") or 0), current.name):
            by_ascension[asc] = record
    for asc, record in by_ascension.items():
        _mark(keep, record, f"ascension_{asc}_deepest")
    return keep


@dataclass
class _MarkdownSection:
    heading: str | None
    raw: str


def _split_markdown_sections(text: str) -> list[_MarkdownSection]:
    """Split on level-2 headings outside fenced code blocks, preserving bytes."""
    lines = text.splitlines(keepends=True)
    sections: list[_MarkdownSection] = []
    current: list[str] = []
    heading: str | None = None
    fence: str | None = None
    for line in lines:
        stripped = line.lstrip()
        marker = None
        if stripped.startswith("```"):
            marker = "```"
        elif stripped.startswith("~~~"):
            marker = "~~~"
        if marker:
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
        is_heading = fence is None and bool(re.match(r"^##\s+", line))
        if is_heading and current:
            sections.append(_MarkdownSection(heading, "".join(current)))
            current = []
        if is_heading:
            heading = line.strip()
        current.append(line)
    if current or not sections:
        sections.append(_MarkdownSection(heading, "".join(current)))
    return sections


def _plan_markdown(path: Path, keep_recent: int, pin_brain: bool) -> MarkdownPlan | None:
    if not path.exists():
        return None
    original = path.read_bytes()
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"cannot compact non-UTF-8 markdown {path}: {exc}") from exc
    sections = _split_markdown_sections(text)
    keep: set[int] = {0}
    recent_n = max(0, int(keep_recent))
    if recent_n:
        keep.update(range(max(0, len(sections) - recent_n), len(sections)))
    if pin_brain:
        keep.update(i for i, section in enumerate(sections)
                    if section.heading and "🧠" in section.heading)
    compacted_text = "".join(section.raw for i, section in enumerate(sections) if i in keep)
    compacted = compacted_text.encode("utf-8")
    removed = [section.heading or "<preamble>" for i, section in enumerate(sections)
               if i not in keep]
    return MarkdownPlan(
        path=path,
        name=path.name,
        original=original,
        compacted=compacted,
        original_sha256=_sha256(original),
        compacted_sha256=_sha256(compacted),
        sections=len(sections),
        kept_sections=len(keep),
        removed_headings=removed,
        rule={"recent_sections": recent_n, "pin_brain_sections": pin_brain},
    )


def _runtime_log_report(root: Path) -> list[dict]:
    out = []
    for path in sorted(root.glob("*.log"), key=lambda item: item.name):
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append({"file": path.name, "bytes": stat.st_size,
                    "action": "report_only_not_archived"})
    return out


def _plan_single_compaction(
    root: Path, options: CompactionOptions | None = None,
) -> CompactionPlan:
    root = Path(root).resolve()
    options = options or CompactionOptions()
    manifest = _load_manifest(root)
    archived_by_name = _archived_run_map(manifest)
    records = _scan_runs(root)
    keep = _select_working_set(records, options)
    archive_new: list[RunRecord] = []
    archive_duplicates: list[RunRecord] = []
    warnings: list[str] = []
    for record in records:
        if record.name in keep:
            continue
        prior = archived_by_name.get(record.name)
        if prior:
            if prior.get("sha256") == record.sha256:
                archive_duplicates.append(record)
            else:
                _mark(keep, record, "archive_name_hash_collision")
                warnings.append(f"kept {record.name}: archive contains a different hash")
        else:
            archive_new.append(record)

    markdown: list[MarkdownPlan] = []
    lesson_plan = _plan_markdown(root / "lessons.md", options.keep_lessons, True)
    meta_plan = _plan_markdown(root / "meta_review.md", options.keep_meta_reviews, False)
    if lesson_plan:
        markdown.append(lesson_plan)
    if meta_plan:
        markdown.append(meta_plan)

    stats_path = root / "stats.json"
    stats_sha = _sha256(stats_path.read_bytes()) if stats_path.exists() else None
    return CompactionPlan(
        root=root,
        options=options,
        runs=records,
        keep_reasons=keep,
        archive_new=archive_new,
        archive_duplicates=archive_duplicates,
        markdown=markdown,
        manifest=manifest,
        archived_by_name=archived_by_name,
        stats_sha256=stats_sha,
        runtime_logs=_runtime_log_report(root),
        warnings=warnings,
    )


def discover_character_profile_roots(root: Path) -> tuple[Path, ...]:
    """Find nested Knowledge stores while pruning archives and forensic copies."""
    root = Path(root).resolve()
    if not root.is_dir():
        return ()
    stores: list[Path] = []
    for current, directory_names, file_names in os.walk(root):
        directories = {name.casefold() for name in directory_names}
        files = {name.casefold() for name in file_names}
        directory_names[:] = sorted(
            name for name in directory_names
            if name.casefold() not in _KNOWLEDGE_STORE_SCAN_PRUNE
            and "cache" not in name.casefold()
        )
        current_path = Path(current)
        if current_path == root:
            continue
        if "runs" in directories and files.intersection(_KNOWLEDGE_STORE_MARKERS):
            stores.append(current_path.resolve())
    return tuple(sorted(set(stores), key=lambda path: path.as_posix().casefold()))


def plan_compaction(root: Path, options: CompactionOptions | None = None) -> CompactionPlan:
    """Plan the root store and every nested character-profile store."""
    root = Path(root).resolve()
    options = options or CompactionOptions()
    plan = _plan_single_compaction(root, options)
    plan.profile_plans = [
        _plan_single_compaction(profile_root, options)
        for profile_root in discover_character_profile_roots(root)
    ]
    return plan


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is not a side-effect-free existence probe on
        # Windows: CPython maps unsupported signals to TerminateProcess.  The
        # compactor must fail closed without ever signalling the live stack.
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            handle = kernel32.OpenProcess(
                0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                # Access denied means the process exists but is inaccessible;
                # treating it as alive is the safe compaction decision.
                return ctypes.get_last_error() == 5
            try:
                exit_code = ctypes.c_ulong()
                queried = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                return bool(queried) and exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            # An unavailable probe must not make destructive compaction proceed.
            return True
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        # An inaccessible process still exists; fail closed for compaction.
        return True
    except OSError:
        return False


def _knowledge_tree_root(root: Path) -> Path:
    """Return the outer knowledge/ anchor for a nested profile when available."""
    root = Path(root).resolve()
    for candidate in (root, *root.parents):
        if candidate.name.casefold() == "knowledge":
            return candidate
    return root


def _active_reasons(root: Path) -> list[str]:
    root = Path(root).resolve()
    tree_root = _knowledge_tree_root(root)
    reasons: list[str] = []
    checked_roots = tuple(dict.fromkeys((root, tree_root)))
    for state_root in checked_roots:
        flag_path = state_root / "review_active.flag"
        if flag_path.exists():
            reasons.append(
                "knowledge/review_active.flag exists"
                if state_root == tree_root else f"{flag_path} exists")
        queue_path = state_root / "review_queue.json"
        if queue_path.exists():
            try:
                queue = json.loads(queue_path.read_text(encoding="utf-8"))
                if isinstance(queue, dict) and queue.get("reviewing"):
                    reasons.append(
                        "review_queue.json has an active reviewing batch"
                        if state_root == tree_root else
                        f"{queue_path} has an active reviewing batch")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                reasons.append(
                    "review_queue.json is unreadable"
                    if state_root == tree_root else f"{queue_path} is unreadable")
    runtime = tree_root.parent / ".runtime"
    if runtime.exists():
        for pid_path in sorted(runtime.glob("*.pid")):
            try:
                payload = json.loads(pid_path.read_text(encoding="utf-8"))
                pid = int(payload.get("pid") or 0)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                continue
            if _pid_alive(pid):
                reasons.append(f"live lifecycle pid {pid} ({pid_path.name})")
    return reasons


@contextmanager
def _compaction_lock(root: Path) -> Iterator[None]:
    path = root / LOCK_NAME
    payload = _json_bytes({"pid": os.getpid(), "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"compaction lock already exists: {path}") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _zip_entry(zf: zipfile.ZipFile, member: str, raw: bytes) -> None:
    member = _safe_zip_member(member)
    info = zipfile.ZipInfo(member)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zf.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _verify_zip(path: Path, expected: dict[str, tuple[str, int]]) -> None:
    with zipfile.ZipFile(path, "r") as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC verification failed for {bad}")
        actual_names = set()
        for info in zf.infolist():
            name = _safe_zip_member(info.filename)
            if name in actual_names:
                raise RuntimeError(f"duplicate ZIP member: {name}")
            actual_names.add(name)
        if actual_names != set(expected):
            missing = sorted(set(expected) - actual_names)
            extra = sorted(actual_names - set(expected))
            raise RuntimeError(f"ZIP member mismatch; missing={missing}, extra={extra}")
        for member, (digest, size) in expected.items():
            raw = zf.read(member)
            if len(raw) != size or _sha256(raw) != digest:
                raise RuntimeError(f"ZIP SHA256 verification failed for {member}")


def _batch_material(plan: CompactionPlan) -> tuple[dict[str, bytes], dict]:
    members: dict[str, bytes] = {}
    selection = {
        "schema_version": SCHEMA_VERSION,
        "selection_rules": plan.options.selection_rules(),
        "kept": [{"file": name, "reasons": reasons}
                 for name, reasons in sorted(plan.keep_reasons.items())],
        "archived": [record.summary for record in plan.archive_new],
    }
    for record in plan.archive_new:
        member = _safe_zip_member(f"runs/{record.name}")
        members[member] = record.raw
    for markdown in plan.markdown:
        if markdown.changed:
            member = _safe_zip_member(f"markdown/{markdown.name}.before")
            members[member] = markdown.original
    for name in ("stats.json", "policy.json", "progression.json"):
        path = plan.root / name
        if path.exists():
            members[_safe_zip_member(f"snapshots/{name}")] = path.read_bytes()
    selection_raw = _json_bytes(selection)
    members[_safe_zip_member("metadata/selection.json")] = selection_raw
    return members, selection


def _build_or_reuse_archive(plan: CompactionPlan) -> tuple[Path, str, dict, dict[str, bytes]]:
    members, selection = _batch_material(plan)
    fingerprint = hashlib.sha256()
    for member, raw in sorted(members.items()):
        fingerprint.update(member.encode("utf-8"))
        fingerprint.update(b"\x00")
        fingerprint.update(_sha256(raw).encode("ascii"))
        fingerprint.update(b"\n")
    batch_id = fingerprint.hexdigest()[:20]
    archive_rel = Path("archive") / f"batch-{batch_id}.zip"
    archive_path = plan.root / archive_rel
    expected = {member: (_sha256(raw), len(raw)) for member, raw in members.items()}
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        archive_path.parent.resolve().relative_to(plan.root)
    except ValueError as exc:
        raise RuntimeError(f"archive directory escapes knowledge root: {archive_path.parent}") from exc
    if archive_path.exists():
        _verify_zip(archive_path, expected)
        return archive_path, batch_id, selection, members

    temp = archive_path.parent / f".{archive_path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9, allowZip64=True) as zf:
            for member, raw in sorted(members.items()):
                _zip_entry(zf, member, raw)
        # Windows' _commit (os.fsync) rejects a read-only descriptor.
        with temp.open("rb+") as handle:
            os.fsync(handle.fileno())
        _verify_zip(temp, expected)
        os.replace(temp, archive_path)
        _verify_zip(archive_path, expected)
        return archive_path, batch_id, selection, members
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _manifest_batch(plan: CompactionPlan, archive_path: Path, batch_id: str,
                    selection: dict, members: dict[str, bytes]) -> dict:
    archive_rel = archive_path.relative_to(plan.root).as_posix()
    markdown_entries = []
    for item in plan.markdown:
        if not item.changed:
            continue
        markdown_entries.append({
            "file": item.name,
            "member": _safe_zip_member(f"markdown/{item.name}.before"),
            "original_sha256": item.original_sha256,
            "original_bytes": len(item.original),
            "compacted_sha256": item.compacted_sha256,
            "compacted_bytes": len(item.compacted),
            "sections": item.sections,
            "kept_sections": item.kept_sections,
            "removed_headings": item.removed_headings,
            "rule": item.rule,
        })
    snapshots = []
    for member, raw in sorted(members.items()):
        if member.startswith("snapshots/"):
            snapshots.append({"member": member, "sha256": _sha256(raw), "bytes": len(raw)})
    return {
        "id": batch_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "archive": _safe_zip_member(archive_rel),
        "archive_sha256": _sha256(archive_path.read_bytes()),
        "archive_bytes": archive_path.stat().st_size,
        "selection_rules": plan.options.selection_rules(),
        "kept": selection["kept"],
        "runs": [dict(record.summary, member=_safe_zip_member(f"runs/{record.name}"))
                 for record in plan.archive_new],
        "markdown": markdown_entries,
        "snapshots": snapshots,
        "runtime_logs": {"action": "report_only_not_archived",
                         "files": plan.runtime_logs},
    }


def _catalog_bytes(root: Path, manifest: dict) -> bytes:
    archived = _archived_run_map(manifest)
    entries: dict[str, dict] = {}
    for name, item in archived.items():
        entry = {key: value for key, value in item.items() if key != "archive"}
        entry["storage"] = {"kind": "zip", "archive": item["archive"],
                            "member": item["member"]}
        entries[name] = entry
    for record in _scan_runs(root):
        entry = dict(record.summary)
        entry["storage"] = {"kind": "active", "path": f"runs/{record.name}"}
        entries[record.name] = entry
    lines = [json.dumps({"schema_version": SCHEMA_VERSION,
                         "description": "Searchable summaries; raw archived runs remain exact in ZIP."},
                        ensure_ascii=False, sort_keys=True, separators=(",", ":"))]
    lines.extend(json.dumps(entries[name], ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")) for name in sorted(entries))
    return ("\n".join(lines) + "\n").encode("utf-8")


def read_run_evidence(root: Path, filename: str) -> bytes:
    """Read one active or archived raw run, verifying archived SHA256 first."""
    root = Path(root).resolve()
    if Path(filename).name != filename or not filename.endswith(".json"):
        raise ValueError(f"invalid run filename: {filename!r}")
    active = root / "runs" / filename
    if active.is_file():
        return active.read_bytes()
    manifest = _load_manifest(root)
    entry = _archived_run_map(manifest).get(filename)
    if not entry:
        raise FileNotFoundError(f"run not found in active store or archive: {filename}")
    archive_rel = _safe_zip_member(str(entry["archive"]))
    archive_path = (root / Path(PurePosixPath(archive_rel))).resolve()
    try:
        archive_path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"archive escapes knowledge root: {archive_rel}") from exc
    member = _safe_zip_member(str(entry["member"]))
    with zipfile.ZipFile(archive_path, "r") as zf:
        raw = zf.read(member)
    if len(raw) != int(entry.get("bytes") or -1) or _sha256(raw) != entry.get("sha256"):
        raise RuntimeError(f"archived run verification failed: {filename}")
    return raw


def _verify_sources_unchanged(plan: CompactionPlan) -> None:
    for record in plan.archive_new + plan.archive_duplicates:
        if not record.path.exists() or _sha256(record.path.read_bytes()) != record.sha256:
            raise RuntimeError(f"run changed during compaction: {record.path}")
    for item in plan.markdown:
        if item.changed and (not item.path.exists() or
                             _sha256(item.path.read_bytes()) != item.original_sha256):
            raise RuntimeError(f"markdown changed during compaction: {item.path}")
    stats_path = plan.root / "stats.json"
    if plan.stats_sha256 and _sha256(stats_path.read_bytes()) != plan.stats_sha256:
        raise RuntimeError("stats.json changed during compaction")


def _verify_archived_duplicates(plan: CompactionPlan) -> None:
    """Prove existing manifest-backed copies before removing active duplicates."""
    grouped: dict[str, list[tuple[RunRecord, dict]]] = {}
    for record in plan.archive_duplicates:
        prior = plan.archived_by_name.get(record.name)
        if not prior:
            raise RuntimeError(f"missing manifest entry for duplicate {record.name}")
        grouped.setdefault(str(prior["archive"]), []).append((record, prior))
    for archive_rel, rows in grouped.items():
        _safe_zip_member(archive_rel)
        archive_path = (plan.root / Path(PurePosixPath(archive_rel))).resolve()
        try:
            archive_path.relative_to(plan.root)
        except ValueError as exc:
            raise RuntimeError(f"archive escapes knowledge root: {archive_rel}") from exc
        if not archive_path.is_file():
            raise RuntimeError(f"manifest archive is missing: {archive_path}")
        with zipfile.ZipFile(archive_path, "r") as zf:
            for record, prior in rows:
                member = _safe_zip_member(str(prior["member"]))
                try:
                    raw = zf.read(member)
                except KeyError as exc:
                    raise RuntimeError(f"manifest member is missing: {archive_rel}!{member}") from exc
                if len(raw) != int(prior.get("bytes") or -1) or _sha256(raw) != record.sha256:
                    raise RuntimeError(f"archived duplicate verification failed: {record.name}")


def _apply_single_compaction(root: Path, options: CompactionOptions | None = None) -> dict:
    """Apply one safe compaction pass and return a machine-readable result."""
    root = Path(root).resolve()
    active = _active_reasons(root)
    if active:
        raise RuntimeError("refusing to compact an active knowledge store: " + "; ".join(active))
    with _compaction_lock(root):
        # Re-plan under the lock so a prior dry-run can never authorize stale paths.
        plan = _plan_single_compaction(root, options)
        active = _active_reasons(root)
        if active:
            raise RuntimeError("stack became active while planning compaction: " + "; ".join(active))
        if not plan.changes_history:
            catalog_changed = _write_if_changed(root / CATALOG_REL,
                                                _catalog_bytes(root, plan.manifest))
            return {
                "changed": catalog_changed,
                "archive_created": False,
                "archived_runs": 0,
                "removed_duplicate_runs": 0,
                "markdown_compacted": 0,
                "catalog_changed": catalog_changed,
                "idempotent_noop": not catalog_changed,
            }

        needs_batch = bool(plan.archive_new or any(item.changed for item in plan.markdown))
        manifest = copy.deepcopy(plan.manifest)
        archive_path: Path | None = None
        batch_id: str | None = None
        if needs_batch:
            archive_path, batch_id, selection, members = _build_or_reuse_archive(plan)
            batch = _manifest_batch(plan, archive_path, batch_id, selection, members)
            if not any(existing.get("id") == batch_id for existing in manifest["batches"]):
                manifest["batches"].append(batch)
                _atomic_write(root / MANIFEST_REL, _json_bytes(manifest))
            else:
                # A crash may have published the manifest before deleting sources.
                # The identical batch is reused after validating its archive.
                manifest = _load_manifest(root)

        _verify_sources_unchanged(plan)
        _verify_archived_duplicates(plan)
        for item in plan.markdown:
            if item.changed:
                if _sha256(item.path.read_bytes()) != item.original_sha256:
                    raise RuntimeError(f"markdown changed before replacement: {item.path}")
                _atomic_write(item.path, item.compacted)
        for record in plan.archive_new + plan.archive_duplicates:
            # Exact path, no globs; the second hash check above covered all files
            # before the first destructive operation.
            if _sha256(record.path.read_bytes()) != record.sha256:
                raise RuntimeError(f"run changed before removal: {record.path}")
            record.path.unlink()

        stats_path = root / "stats.json"
        if plan.stats_sha256 and _sha256(stats_path.read_bytes()) != plan.stats_sha256:
            raise RuntimeError("stats.json changed unexpectedly after compaction")
        catalog_changed = _write_if_changed(root / CATALOG_REL,
                                            _catalog_bytes(root, manifest))
        return {
            "changed": True,
            "archive_created": bool(needs_batch),
            "batch_id": batch_id,
            "archive": str(archive_path) if archive_path else None,
            "archived_runs": len(plan.archive_new),
            "removed_duplicate_runs": len(plan.archive_duplicates),
            "markdown_compacted": sum(1 for item in plan.markdown if item.changed),
            "catalog_changed": catalog_changed,
            "idempotent_noop": False,
        }


def apply_compaction(root: Path, options: CompactionOptions | None = None) -> dict:
    """Compact the legacy root store and each discovered character profile."""
    root = Path(root).resolve()
    options = options or CompactionOptions()
    profile_roots = discover_character_profile_roots(root)
    root_result = _apply_single_compaction(root, options)
    if not profile_roots:
        return root_result

    profile_results = [
        {
            "knowledge_dir": str(profile_root),
            **_apply_single_compaction(profile_root, options),
        }
        for profile_root in profile_roots
    ]
    all_results = [root_result, *profile_results]
    result = dict(root_result)
    result.update({
        "changed": any(item["changed"] for item in all_results),
        "archive_created": any(item["archive_created"] for item in all_results),
        "archived_runs": sum(int(item["archived_runs"]) for item in all_results),
        "removed_duplicate_runs": sum(
            int(item["removed_duplicate_runs"]) for item in all_results),
        "markdown_compacted": sum(
            int(item["markdown_compacted"]) for item in all_results),
        "catalog_changed": any(item["catalog_changed"] for item in all_results),
        "idempotent_noop": all(item["idempotent_noop"] for item in all_results),
        "root_store": {"knowledge_dir": str(root), **root_result},
        "character_profiles": profile_results,
    })
    return result


def plan_report(plan: CompactionPlan) -> dict:
    active_bytes = sum(record.size for record in plan.runs)
    archive_bytes = sum(record.size for record in plan.archive_new)
    compressed_estimate = sum(len(zlib.compress(record.raw, level=9))
                              for record in plan.archive_new)
    markdown = []
    for item in plan.markdown:
        markdown.append({
            "file": item.name,
            "sections": item.sections,
            "kept_sections": item.kept_sections,
            "removed_sections": item.sections - item.kept_sections,
            "bytes_before": len(item.original),
            "bytes_after": len(item.compacted),
        })
    report = {
        "mode": "dry-run",
        "knowledge_dir": str(plan.root),
        "selection_rules": plan.options.selection_rules(),
        "runs": {
            "active_files": len(plan.runs),
            "active_bytes": active_bytes,
            "kept_files": len(plan.kept),
            "kept_bytes": sum(record.size for record in plan.kept),
            "new_archive_files": len(plan.archive_new),
            "new_archive_raw_bytes": archive_bytes,
            "new_archive_deflate_estimate_bytes": compressed_estimate,
            "already_archived_duplicate_files": len(plan.archive_duplicates),
        },
        "markdown": markdown,
        "stats": {"action": "unchanged_sufficient_statistics",
                  "sha256": plan.stats_sha256},
        "runtime_logs": {"action": "report_only_not_archived",
                         "files": plan.runtime_logs,
                         "bytes": sum(item["bytes"] for item in plan.runtime_logs)},
        "warnings": plan.warnings,
        "git_history_note": "Current checkout shrinks; existing Git objects do not.",
    }
    if plan.profile_plans:
        report["character_profiles"] = [
            plan_report(profile_plan) for profile_plan in plan.profile_plans
        ]
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "knowledge")
    parser.add_argument("--apply", action="store_true",
                        help="apply the plan (default is read-only dry-run)")
    parser.add_argument("--show-run", metavar="FILENAME",
                        help="print one active/archived raw run after verification")
    parser.add_argument("--keep-recent", type=int, default=DEFAULT_KEEP_RECENT)
    parser.add_argument("--deep-floor", type=int, default=DEFAULT_DEEP_FLOOR)
    parser.add_argument("--keep-longest", type=int, default=DEFAULT_KEEP_LONGEST)
    parser.add_argument("--keep-largest", type=int, default=DEFAULT_KEEP_LARGEST)
    parser.add_argument("--no-floor-representatives", action="store_true")
    parser.add_argument("--keep-lessons", type=int, default=DEFAULT_KEEP_LESSONS)
    parser.add_argument("--keep-meta-reviews", type=int,
                        default=DEFAULT_KEEP_META_REVIEWS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    options = CompactionOptions(
        keep_recent=max(0, args.keep_recent),
        deep_floor=max(0, args.deep_floor),
        keep_longest=max(0, args.keep_longest),
        keep_largest=max(0, args.keep_largest),
        keep_floor_representatives=not args.no_floor_representatives,
        keep_lessons=max(0, args.keep_lessons),
        keep_meta_reviews=max(0, args.keep_meta_reviews),
    )
    if args.show_run:
        if args.apply:
            raise SystemExit("--show-run and --apply are mutually exclusive")
        sys.stdout.buffer.write(read_run_evidence(args.knowledge_dir, args.show_run))
        return 0
    if args.apply:
        result = apply_compaction(args.knowledge_dir, options)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        report = plan_report(plan_compaction(args.knowledge_dir, options))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("\nDRY-RUN ONLY: pass --apply after stopping the sts2-ascend stack.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
