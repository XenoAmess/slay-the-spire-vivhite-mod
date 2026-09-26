"""Losslessly archive one explicitly selected, historical human-assisted run.

Unlike routine completed-run compaction, this narrow offline operation retains
in_progress=true and all other JSON bytes.  It requires both exclusion flags,
a stopped stack, and a live /state proving a different current run.  Dry-run is
the default.  --apply publishes verified ZIP/manifest/catalog before removing
the exact source; learning state, rotation ledgers and review queues are untouched.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


BRAIN = Path(__file__).resolve().parents[1] / "brain"
if str(BRAIN) not in sys.path:
    sys.path.insert(0, str(BRAIN))

import compact_knowledge as compact  # noqa: E402
from client import Sts2Client  # noqa: E402
from release_orphan_run import lifecycle_lock  # noqa: E402


OPERATION = "explicit_excluded_run_archive"


def _runtime_dir(root: Path) -> Path:
    return compact._knowledge_tree_root(root).parent / ".runtime"


def _offline_reasons(root: Path, stopped_session_id: str | None) -> list[str]:
    """Only waive a persisted review queue after a proved unified stack stop."""
    reasons = compact._active_reasons(root)
    runtime = _runtime_dir(root)
    if (runtime / "session.json").exists():
        reasons.append("runtime/session.json still exists")
    # The generic compactor ignores malformed PID markers.  An explicit stop
    # exemption needs stronger negative evidence and therefore rejects them.
    for path in runtime.glob("*.pid"):
        try:
            row = json.loads(path.read_text("utf-8-sig"))
            pid = row.get("pid")
            if type(pid) is not int or pid <= 0:
                raise ValueError("invalid PID")
            if compact._pid_alive(pid):
                reasons.append(f"live lifecycle pid {pid} ({path.name})")
        except (OSError, UnicodeError, ValueError, AttributeError):
            reasons.append(f"unreadable lifecycle pid marker: {path.name}")
    queue_reasons = [reason for reason in reasons
                     if reason.endswith("review_queue.json has an active reviewing batch")]
    if not queue_reasons or not stopped_session_id:
        return reasons
    if not re.fullmatch(r"[0-9a-f]{32}", stopped_session_id):
        return reasons + ["invalid stopped-session-id"]
    sentinel = runtime / f"stop.{stopped_session_id}.request"
    try:
        stop = json.loads(sentinel.read_text("utf-8-sig"))
        valid_stop = (isinstance(stop, dict) and stop.get("source") == "Stop-Agent.ps1"
                      and stop.get("session_id") == stopped_session_id
                      and bool(stop.get("requested_at")))
    except (OSError, UnicodeError, ValueError):
        valid_stop = False
    other_reasons = [reason for reason in reasons if reason not in queue_reasons]
    if valid_stop and not other_reasons:
        return []
    return reasons + ([] if valid_stop else ["matching unified stop sentinel is missing or invalid"])


def _observe_current_run(api_url: str, run_id: str, current_run_id: str) -> dict:
    parsed = urllib.parse.urlsplit(api_url)
    if (parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("api-url must be a local Agent HTTP origin")
    if not current_run_id or current_run_id == "run_unknown" or current_run_id == run_id:
        raise ValueError("current-run-id must identify a different real run")
    with urllib.request.urlopen(api_url.rstrip("/") + "/state", timeout=5) as response:
        state = Sts2Client._decode(response.read())
    if not isinstance(state, dict) or not isinstance(state.get("run"), dict):
        raise RuntimeError("current API state has no real run")
    identity = state.get("run_id") or state["run"].get("run_id")
    nested_identity = state["run"].get("run_id")
    if (identity != current_run_id or (nested_identity and nested_identity != identity)
            or type(state.get("state_version")) not in (int, float)
            or not math.isfinite(state["state_version"]) or state["state_version"] < 0):
        raise RuntimeError("current API run identity or state_version does not match")
    return {"run_id": identity, "state_version": state["state_version"],
            "native_profile_id": state.get("native_profile_id"),
            "screen": state.get("screen")}


def _read_selected(root: Path, filename: str, run_id: str) -> compact.RunRecord:
    if (Path(filename).name != filename or "/" in filename or "\\" in filename
            or not filename.endswith(".json")):
        raise ValueError("filename must be one JSON basename")
    source = root / "runs" / filename
    source.resolve().relative_to(root)
    raw = compact.read_run_evidence(root, filename)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("run_id") != run_id:
        raise RuntimeError("selected raw run_id does not match --run-id")
    if not all(data.get(key) is True for key in ("human_assisted", "excluded_from_learning")):
        raise RuntimeError("selected run must be human_assisted and excluded_from_learning")
    digest = compact._sha256(raw)
    summary = compact._run_summary(data, filename, len(raw), digest)
    summary["catalog_projection_version"] = 1
    return compact.RunRecord(source, filename, raw, digest, len(raw), True, summary)


def _build_archive(root: Path, record: compact.RunRecord, current_run_id: str) -> tuple[Path, dict]:
    member = compact._safe_zip_member(f"runs/{record.name}")
    selection = {"schema_version": 1, "operation": OPERATION,
                 "run_id": record.summary["run_id"], "current_run_id": current_run_id,
                 "preserves_in_progress": True, "preserves_learning_exclusion": True,
                 "source_sha256": record.sha256, "source_bytes": record.size}
    members = {member: record.raw, "metadata/selection.json": compact._json_bytes(selection)}
    batch_id = compact._sha256(members["metadata/selection.json"])[:20]
    archive = root / "archive" / f"excluded-{batch_id}.zip"
    archive.parent.resolve().relative_to(root)
    archive.parent.mkdir(parents=True, exist_ok=True)
    expected = {name: (compact._sha256(raw), len(raw)) for name, raw in members.items()}
    if not archive.exists():
        temp = archive.with_name(f".{archive.name}.tmp-{os.getpid()}-{time.time_ns()}")
        try:
            with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=9, allowZip64=True) as output:
                for name, raw in sorted(members.items()):
                    compact._zip_entry(output, name, raw)
            with temp.open("rb+") as handle:
                os.fsync(handle.fileno())
            compact._verify_zip(temp, expected)
            os.replace(temp, archive)
        finally:
            temp.unlink(missing_ok=True)
    compact._verify_zip(archive, expected)
    return archive, {
        "id": batch_id, "operation": OPERATION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "archive": archive.relative_to(root).as_posix(),
        "archive_sha256": compact._sha256(archive.read_bytes()),
        "archive_bytes": archive.stat().st_size,
        "selection_rules": selection,
        "runs": [dict(record.summary, member=member)],
        "kept": [], "markdown": [], "snapshots": [],
    }


def _catalog(root: Path, manifest: dict) -> bytes:
    # Preserve existing summaries for unrelated active runs.  The selected run
    # must point to its ZIP before its source can disappear.
    entries = {}
    path = root / compact.CATALOG_REL
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RuntimeError("invalid existing run catalog row")
            if row.get("file"):
                entries[row["file"]] = row
    for name, row in compact._archived_run_map(manifest).items():
        entries[name] = {key: value for key, value in row.items() if key != "archive"}
        entries[name]["storage"] = {"kind": "zip", "archive": row["archive"],
                                    "member": row["member"]}
    header = {"schema_version": compact.SCHEMA_VERSION,
              "description": "Searchable summaries; raw archived runs remain exact in ZIP."}
    return b"".join(compact._json_bytes(row, indent=None)
                    for row in [header, *(entries[name] for name in sorted(entries))])


def archive_excluded_run(root: Path, *, filename: str, run_id: str,
                         current_run_id: str, api_url: str = "http://127.0.0.1:8080",
                         apply: bool = False, stopped_session_id: str | None = None) -> dict:
    root = Path(root).resolve()
    evidence = _observe_current_run(api_url, run_id, current_run_id)
    record = _read_selected(root, filename, run_id)
    report = {"operation": OPERATION, "mode": "apply" if apply else "dry-run",
              "knowledge_dir": str(root), "file": filename, "run_id": run_id,
              "source_bytes": record.size, "source_sha256": record.sha256,
              "in_progress": record.summary["in_progress"], "current_run": evidence,
              "changed": False}
    if not apply:
        report["stack_blockers"] = _offline_reasons(root, stopped_session_id)
        return report
    import autogit

    active = _offline_reasons(root, stopped_session_id)
    if active:
        raise RuntimeError("refusing to archive with an active stack: " + "; ".join(active))
    with lifecycle_lock(_runtime_dir(root)), compact._compaction_lock(root):
        active = _offline_reasons(root, stopped_session_id)
        if active:
            raise RuntimeError("stack became active: " + "; ".join(active))
        record = _read_selected(root, filename, run_id)
        report.update(source_bytes=record.size, source_sha256=record.sha256,
                      in_progress=record.summary["in_progress"])
        manifest = compact._load_manifest(root)
        prior = compact._archived_run_map(manifest).get(filename)
        if prior and prior.get("sha256") != record.sha256:
            raise RuntimeError("archive already contains a different version of this filename")
        if prior:
            compact.read_archived_run(root, run_id)
            archive = root / prior["archive"]
        else:
            archive, batch = _build_archive(root, record, current_run_id)
        with autogit.repository_lock(timeout=10.0):
            if compact._load_manifest(root) != manifest:
                raise RuntimeError("manifest changed during archiving")
            active = _offline_reasons(root, stopped_session_id)
            if active:
                raise RuntimeError("stack became active: " + "; ".join(active))
            evidence = _observe_current_run(api_url, run_id, current_run_id)
            if record.path.exists() and compact._sha256(record.path.read_bytes()) != record.sha256:
                raise RuntimeError("selected run changed during archiving")
            updated = copy.deepcopy(manifest)
            if not prior:
                batch["current_run_evidence"] = evidence
                if stopped_session_id:
                    batch["stopped_session_id"] = stopped_session_id
                updated["batches"].append(batch)
                compact._atomic_write(root / compact.MANIFEST_REL, compact._json_bytes(updated))
            catalog_changed = compact._write_if_changed(root / compact.CATALOG_REL, _catalog(root, updated))
            # Verify the exact manifest-addressed member before the removal.
            stored = compact._archived_run_map(updated)[filename]
            compact.read_catalog_storage_evidence(root, dict(stored, storage={
                "kind": "zip", "archive": stored["archive"], "member": stored["member"]}))
            removed = record.path.exists()
            if removed:
                _observe_current_run(api_url, run_id, current_run_id)
                if compact._sha256(record.path.read_bytes()) != record.sha256:
                    raise RuntimeError("selected run changed before removal")
                record.path.unlink()
        report.update(changed=bool(not prior or catalog_changed or removed),
                      archive=str(archive), archive_bytes=archive.stat().st_size,
                      source_removed=removed, current_run=evidence)
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-dir", type=Path, required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--current-run-id", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8080")
    parser.add_argument("--stopped-session-id",
                        help="exact Stop-Agent GUID; permits only its dormant reviewing queue")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(archive_excluded_run(
        args.knowledge_dir, filename=args.filename, run_id=args.run_id,
        current_run_id=args.current_run_id, api_url=args.api_url, apply=args.apply,
        stopped_session_id=args.stopped_session_id),
        ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
