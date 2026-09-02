"""Fail-closed metadata finalization for one Vivhite full-master run.

This module does not record, render, probe, review, sign off, or publish.  It
only turns a project-owned metadata specification into content-addressed run
sidecars.  Every referenced artifact must already exist under the selected
run directory; byte counts and SHA-256 digests are computed here rather than
accepted from an operator-supplied JSON document.

The distinction between workflow authorization and an observed 1.0x review
is intentional.  A user may explicitly delegate or waive a separate review
pause, but that instruction is not rewritten as evidence that somebody
watched the exact deliverable bytes from beginning to end.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


SPEC_VERSION = 1
SPEC_KIND = "vivhite_promo_full_master_metadata_spec"
RUN_MANIFEST_KIND = "vivhite_promo_full_master_run_manifest"
ARTIFACT_INDEX_KIND = "vivhite_promo_full_master_artifact_index"
COVERAGE_KIND = "vivhite_promo_full_master_evidence_coverage"
VOICE = "zh-CN-XiaoxiaoNeural"
SHOT_IDS = (
    "S01-identity",
    "S02-loadout",
    "S03-cough",
    "S04-margin",
    "S05-drain",
    "S06-conservation-geometry",
    "S07-recursive-star-calculus",
    "S08-crimson-integral",
    "S09-unified-field",
    "S10-finale",
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_STAGES = {"capture", "master-draft"}
_SHOT_STATUSES = {"missing", "visual-only", "hash-bound-observation"}
_SEMANTIC_STATUSES = {"pending", "blocked", "passed"}
_REVIEW_MODES = {
    "pending",
    "user-delegated-assumed-pass",
    "independent-1x-review",
}


class RunMetadataError(ValueError):
    """A full-master metadata specification cannot be safely finalized."""


def _object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RunMetadataError(f"{context} must be an object")
    return value


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise RunMetadataError(f"{context} must be non-empty NUL-free text")
    return value.strip()


def _id(value: Any, context: str) -> str:
    result = _text(value, context)
    if _ID.fullmatch(result) is None:
        raise RunMetadataError(f"{context} must be a portable identifier")
    return result


def _relative(value: Any, context: str) -> str:
    raw = _text(value, context)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
        raise RunMetadataError(f"{context} must not contain control characters")
    if "\\" in raw:
        raise RunMetadataError(f"{context} must use portable '/' separators")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or _DRIVE.match(raw)
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw
    ):
        raise RunMetadataError(f"{context} must be a normalized relative path")
    return raw


def _resolve_under(root: Path, relative_path: str, context: str) -> Path:
    candidate = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RunMetadataError(f"{context} escapes the run directory") from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise RunMetadataError(f"could not read artifact {path}: {exc}") from exc
    return digest.hexdigest().upper()


def _file_record(path: Path, *, relative_path: str | None = None) -> dict[str, object]:
    if not path.is_file():
        raise RunMetadataError(f"artifact is missing: {path}")
    result: dict[str, object] = {
        "path": relative_path if relative_path is not None else path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }
    return result


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _bytes_record(relative_path: str, payload: bytes) -> dict[str, object]:
    return {
        "path": relative_path,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest().upper(),
        "media_type": "application/json",
    }


def _read_json(path: Path, context: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise RunMetadataError(f"could not read {context} {path}: {exc}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RunMetadataError(f"invalid JSON in {context} {path}: {exc}") from exc
    return _object(value, context)


def _report_passed(path: Path, context: str) -> bool:
    report = _read_json(path, context)
    status = str(report.get("status", "")).strip().casefold()
    passed = report.get("passed")
    accepted_status = status in {"pass", "passed", "green"}
    if passed is not None and not isinstance(passed, bool):
        raise RunMetadataError(f"{context} passed field must be boolean when present")
    # Do not let contradictory fields silently certify an audit.  A report
    # with an explicit boolean must agree with its status; a status-only
    # report is accepted only for the small, established pass vocabulary.
    if passed is not None:
        return passed is True and (not status or accepted_status)
    return accepted_status


def _validate_capture_contract(
    path: Path,
    *,
    run_root: Path,
    run_id: str,
    raw_record: Mapping[str, object],
) -> None:
    """Validate a declared project capture contract before recording a pass.

    The metadata finalizer does not construct a contract.  When a caller
    declares one, however, it must be the real v1 contract and must bind the
    same raw bytes that are indexed in this run.
    """

    try:
        from .capture_contract import load_capture_contract
    except (ImportError, ModuleNotFoundError) as exc:
        raise RunMetadataError(
            "capture contract was declared but the project contract module is unavailable"
        ) from exc
    try:
        contract = load_capture_contract(
            path,
            artifact_root=run_root,
            verify_files=True,
        )
        contract.verify_unchanged()
    except Exception as exc:  # contract errors are normalized at this boundary
        if isinstance(exc, RunMetadataError):
            raise
        raise RunMetadataError(f"capture contract did not validate: {exc}") from exc
    if contract.run_id != run_id:
        raise RunMetadataError(
            f"capture contract run_id {contract.run_id!r} does not match {run_id!r}"
        )
    bound = contract.raw_capture
    if (
        str(raw_record["path"]) != bound.relative_path
        or
        int(raw_record["bytes"]) != bound.bytes
        or str(raw_record["sha256"]).upper() != bound.sha256
    ):
        raise RunMetadataError("capture contract is bound to a different raw artifact")


def _xar_record(value: Any) -> dict[str, object] | None:
    if value is None:
        return None
    row = _object(value, "xar")
    source_root = Path(_text(row.get("source_root"), "xar.source_root")).expanduser().resolve()
    expected = _text(row.get("expected_git_commit"), "xar.expected_git_commit").lower()
    if not source_root.is_dir():
        raise RunMetadataError(f"xar.source_root is missing: {source_root}")
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RunMetadataError(f"could not inspect xAR checkout: {exc}") from exc
    actual = completed.stdout.strip().lower()
    if completed.returncode != 0 or not actual:
        raise RunMetadataError("could not resolve the xAR checkout commit")
    if actual != expected:
        raise RunMetadataError(
            f"xAR checkout changed: expected {expected}, got {actual}"
        )
    return {
        "source_root": source_root.as_posix(),
        "git_commit": actual,
        "package_version": _text(row.get("package_version"), "xar.package_version"),
    }


def _tool_records(value: Any) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RunMetadataError("tools must be an array")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        row = _object(item, f"tools[{index}]")
        tool_id = _id(row.get("tool_id"), f"tools[{index}].tool_id")
        if tool_id in seen:
            raise RunMetadataError(f"tools repeats {tool_id!r}")
        path = Path(_text(row.get("path"), f"tools[{index}].path")).expanduser().resolve()
        record = _file_record(path)
        record["tool_id"] = tool_id
        if row.get("version") is not None:
            record["version"] = _text(row.get("version"), f"tools[{index}].version")
        result.append(record)
        seen.add(tool_id)
    return result


def _artifact_records(
    run_root: Path, value: Any
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    if not isinstance(value, list) or not value:
        raise RunMetadataError("artifacts must be a non-empty array")
    records: list[dict[str, object]] = []
    by_id: dict[str, dict[str, object]] = {}
    seen_paths: set[str] = set()
    for index, item in enumerate(value):
        row = _object(item, f"artifacts[{index}]")
        artifact_id = _id(row.get("artifact_id"), f"artifacts[{index}].artifact_id")
        relative_path = _relative(row.get("path"), f"artifacts[{index}].path")
        if artifact_id in by_id:
            raise RunMetadataError(f"artifacts repeats ID {artifact_id!r}")
        if relative_path in seen_paths:
            raise RunMetadataError(f"artifacts repeats path {relative_path!r}")
        path = _resolve_under(run_root, relative_path, f"artifacts[{index}].path")
        record = _file_record(path, relative_path=relative_path)
        record.update(
            {
                "artifact_id": artifact_id,
                "media_type": _text(
                    row.get("media_type"), f"artifacts[{index}].media_type"
                ),
                "category": _id(
                    row.get("category"), f"artifacts[{index}].category"
                ),
            }
        )
        records.append(record)
        by_id[artifact_id] = record
        seen_paths.add(relative_path)
    return records, by_id


def _shots(value: Any, artifacts: Mapping[str, Mapping[str, object]]) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise RunMetadataError("shots must be an array")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        row = _object(item, f"shots[{index}]")
        shot_id = _id(row.get("shot_id"), f"shots[{index}].shot_id")
        if shot_id not in SHOT_IDS:
            raise RunMetadataError(f"shots[{index}] has non-canonical shot ID {shot_id!r}")
        if shot_id in seen:
            raise RunMetadataError(f"shots repeats {shot_id!r}")
        status = _text(row.get("capture_status"), f"shots[{index}].capture_status")
        semantic = _text(row.get("semantic_status"), f"shots[{index}].semantic_status")
        if status not in _SHOT_STATUSES:
            raise RunMetadataError(f"shots[{index}].capture_status is unsupported")
        if semantic not in _SEMANTIC_STATUSES:
            raise RunMetadataError(f"shots[{index}].semantic_status is unsupported")
        evidence = row.get("evidence_artifact_ids", [])
        if not isinstance(evidence, list):
            raise RunMetadataError(f"shots[{index}].evidence_artifact_ids must be an array")
        evidence_ids: list[str] = []
        for item_index, artifact_id_value in enumerate(evidence):
            artifact_id = _id(
                artifact_id_value,
                f"shots[{index}].evidence_artifact_ids[{item_index}]",
            )
            if artifact_id not in artifacts:
                raise RunMetadataError(
                    f"shot {shot_id!r} references undeclared artifact {artifact_id!r}"
                )
            evidence_ids.append(artifact_id)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise RunMetadataError(f"shot {shot_id!r} repeats an evidence artifact")
        if status != "missing" and not evidence_ids:
            raise RunMetadataError(f"shot {shot_id!r} needs at least one evidence artifact")
        if semantic == "passed":
            # Per-shot semantic truth requires a run-level validator report;
            # that binding is checked after all report references are parsed.
            pass
        result.append(
            {
                "shot_id": shot_id,
                "capture_status": status,
                "semantic_status": semantic,
                "evidence_artifact_ids": evidence_ids,
                "observation": _text(row.get("observation"), f"shots[{index}].observation"),
            }
        )
        seen.add(shot_id)
    missing = set(SHOT_IDS) - seen
    if missing:
        raise RunMetadataError("shots is missing canonical IDs: " + ", ".join(sorted(missing)))
    return sorted(result, key=lambda item: SHOT_IDS.index(str(item["shot_id"])))


def _review_record(value: Any) -> dict[str, object]:
    row = _object(value, "human_review")
    mode = _text(row.get("mode"), "human_review.mode")
    if mode not in _REVIEW_MODES:
        raise RunMetadataError("human_review.mode is unsupported")
    result: dict[str, object] = {"mode": mode}
    if mode == "pending":
        result.update(
            {
                "workflow_authorization": "pending",
                "independent_1x_observation": False,
            }
        )
        return result
    instruction = _text(row.get("instruction"), "human_review.instruction")
    result["instruction"] = instruction
    if mode == "user-delegated-assumed-pass":
        if row.get("independent_1x_observation", False) is not False:
            raise RunMetadataError(
                "delegated assumed-pass must not claim an independent 1.0x observation"
            )
        result.update(
            {
                "workflow_authorization": "passed-by-explicit-user-instruction",
                "independent_1x_observation": False,
                "content_review_claim": "not-independently-recorded",
            }
        )
    else:
        if row.get("independent_1x_observation") is not True:
            raise RunMetadataError(
                "independent-1x-review requires independent_1x_observation=true"
            )
        result.update(
            {
                "workflow_authorization": "passed",
                "independent_1x_observation": True,
                "content_review_claim": "recorded-by-operator",
            }
        )
    return result


def _write_new(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise RunMetadataError(f"refusing to overwrite existing metadata: {path}") from exc
    except OSError as exc:
        raise RunMetadataError(f"could not write metadata {path}: {exc}") from exc


def finalize_run_metadata(
    spec_path: str | Path,
    *,
    run_root: str | Path | None = None,
) -> Mapping[str, Any]:
    """Finalize three immutable sidecars for one existing run.

    The function refuses to overwrite any prior output.  Callers must use a
    new run/attempt if a finalized artifact or editorial decision changes.
    """

    source = Path(spec_path).expanduser().resolve()
    if run_root is not None:
        root = Path(run_root).expanduser().resolve()
    else:
        # The documented location is ``<run>/notes/spec.json``; accepting a
        # spec directly at ``<run>/`` is useful for small attempts while still
        # keeping the root inference deterministic.
        root = (
            source.parent.parent
            if source.parent.name.casefold() == "notes"
            else source.parent
        ).resolve()
    if not root.is_dir():
        raise RunMetadataError(f"run directory is missing: {root}")
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise RunMetadataError("metadata spec must live inside the selected run") from exc
    document = _read_json(source, "full-master metadata spec")
    if document.get("schema_version") != SPEC_VERSION or document.get("kind") != SPEC_KIND:
        raise RunMetadataError(
            f"metadata spec must declare {SPEC_KIND} schema_version {SPEC_VERSION}"
        )
    run_id = _id(document.get("run_id"), "run_id")
    if root.name.startswith("run-") and root.name != run_id:
        raise RunMetadataError(
            f"run_id {run_id!r} does not match run directory {root.name!r}"
        )
    attempt = document.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise RunMetadataError("attempt must be an integer >= 1")
    stage = _text(document.get("stage"), "stage")
    if stage not in _STAGES:
        raise RunMetadataError("stage must be capture or master-draft")

    editorial = _object(document.get("editorial"), "editorial")
    width = editorial.get("width")
    height = editorial.get("height")
    fps = editorial.get("fps")
    target_duration = editorial.get("target_duration_seconds")
    if (width, height, fps) != (1920, 1080, 60):
        raise RunMetadataError("editorial output must be 1920x1080 at 60 fps")
    if (
        isinstance(target_duration, bool)
        or not isinstance(target_duration, (int, float))
        or not math.isfinite(float(target_duration))
        or float(target_duration) <= 0
    ):
        raise RunMetadataError("editorial.target_duration_seconds must be positive")
    if editorial.get("voice") != VOICE:
        raise RunMetadataError(f"editorial.voice must be {VOICE}")
    if editorial.get("external_bgm") is not False:
        raise RunMetadataError("editorial.external_bgm must be false")

    records, by_id = _artifact_records(root, document.get("artifacts"))
    raw_id = _id(document.get("raw_capture_artifact_id"), "raw_capture_artifact_id")
    if raw_id not in by_id:
        raise RunMetadataError("raw_capture_artifact_id is not declared in artifacts")
    if by_id[raw_id].get("category") != "raw-media":
        raise RunMetadataError("raw_capture_artifact_id must refer to category raw-media")
    deliverable_value = document.get("deliverable_artifact_id")
    deliverable_id: str | None = None
    if deliverable_value is not None:
        deliverable_id = _id(deliverable_value, "deliverable_artifact_id")
        if deliverable_id not in by_id:
            raise RunMetadataError("deliverable_artifact_id is not declared in artifacts")
        if by_id[deliverable_id].get("category") != "deliverable":
            raise RunMetadataError(
                "deliverable_artifact_id must refer to category deliverable"
            )
    if stage == "master-draft" and deliverable_id is None:
        raise RunMetadataError("master-draft stage requires deliverable_artifact_id")
    probe_id_value = document.get("deliverable_probe_artifact_id")
    probe_id: str | None = None
    if stage == "master-draft" and probe_id_value is None:
        raise RunMetadataError("master-draft stage requires deliverable_probe_artifact_id")
    if probe_id_value is not None:
        probe_id = _id(probe_id_value, "deliverable_probe_artifact_id")
        if probe_id not in by_id:
            raise RunMetadataError(
                "deliverable_probe_artifact_id is not declared in artifacts"
            )
        if by_id[probe_id].get("category") != "technical-probe":
            raise RunMetadataError(
                "deliverable_probe_artifact_id must refer to category technical-probe"
            )

    reports = _object(document.get("reports", {}), "reports")
    report_ids: dict[str, str] = {}
    report_passes: dict[str, bool] = {}
    for report_name in ("capture_contract", "technical_audit", "semantic_audit"):
        value = reports.get(report_name)
        if value is None:
            continue
        artifact_id = _id(value, f"reports.{report_name}")
        if artifact_id not in by_id:
            raise RunMetadataError(
                f"reports.{report_name} references undeclared artifact {artifact_id!r}"
            )
        report_ids[report_name] = artifact_id
        report_path = _resolve_under(
            root, str(by_id[artifact_id]["path"]), f"reports.{report_name}"
        )
        if report_name == "capture_contract":
            _validate_capture_contract(
                report_path,
                run_root=root,
                run_id=run_id,
                raw_record=by_id[raw_id],
            )
        else:
            report_passes[report_name] = _report_passed(report_path, report_name)

    shots = _shots(document.get("shots"), by_id)
    semantic_pass_requested = any(item["semantic_status"] == "passed" for item in shots)
    if semantic_pass_requested and not report_passes.get("semantic_audit", False):
        raise RunMetadataError(
            "a shot cannot be semantic_status=passed without a passing semantic audit artifact"
        )

    review = _review_record(document.get("human_review"))
    if document.get("signoff", False) is not False or document.get("export", False) is not False:
        raise RunMetadataError("metadata finalizer never performs signoff or export")

    tools = _tool_records(document.get("tools"))
    xar = _xar_record(document.get("xar"))
    spec_relative = source.relative_to(root).as_posix()
    spec_record = _file_record(source, relative_path=spec_relative)
    spec_record["media_type"] = "application/json"

    artifact_index: dict[str, Any] = {
        "schema_version": 1,
        "kind": ARTIFACT_INDEX_KIND,
        "run_id": run_id,
        "artifacts": records,
        "policy": {
            "records_are_computed_from_existing_bytes": True,
            "paths_are_relative_to_run_root": True,
            "placeholder_hashes_accepted": False,
        },
    }
    coverage: dict[str, Any] = {
        "schema_version": 1,
        "kind": COVERAGE_KIND,
        "run_id": run_id,
        "shots": shots,
        "semantic_policy": {
            "visual_observation_is_not_an_api_action_receipt": True,
            "missing_runtime_evidence_remains_pending_or_blocked": True,
            "source_or_test_evidence_must_not_be_relabelled_as_runtime_evidence": True,
        },
    }
    artifact_bytes = _json_bytes(artifact_index)
    coverage_bytes = _json_bytes(coverage)
    artifact_index_relative = "review/full-master-artifact-index.json"
    coverage_relative = "review/full-master-evidence-coverage.json"
    artifact_index_record = _bytes_record(artifact_index_relative, artifact_bytes)
    coverage_record = _bytes_record(coverage_relative, coverage_bytes)

    semantic_gate = "pending"
    if "semantic_audit" in report_ids:
        semantic_gate = "passed" if report_passes.get("semantic_audit") else "blocked"
    technical_gate = "pending"
    if "technical_audit" in report_ids:
        technical_gate = "passed" if report_passes.get("technical_audit") else "blocked"
    capture_gate = "passed" if "capture_contract" in report_ids else "pending"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": RUN_MANIFEST_KIND,
        "run_id": run_id,
        "attempt": attempt,
        "stage": stage,
        "state": "master-draft-preserved" if deliverable_id else "capture-preserved",
        "metadata_spec": {**spec_record, "path": spec_relative},
        "sidecars": {
            "artifact_index": artifact_index_record,
            "evidence_coverage": coverage_record,
        },
        "raw_capture": by_id[raw_id],
        "deliverable": by_id.get(deliverable_id) if deliverable_id else None,
        "deliverable_probe": by_id.get(probe_id) if probe_id else None,
        "reports": report_ids,
        "editorial": {
            "width": 1920,
            "height": 1080,
            "fps": 60,
            "target_duration_seconds": float(target_duration),
            "voice": VOICE,
            "external_bgm": False,
        },
        "tools": tools,
        "xar": xar,
        "gates": {
            "capture_contract": capture_gate,
            "technical_audit": technical_gate,
            "semantic_audit": semantic_gate,
            "human_review": review,
            "signoff": False,
            "export": False,
        },
        "preservation": {
            "retry_policy": "new run/attempt; never overwrite this directory",
            "failed_and_partial_artifacts_retained": True,
        },
    }
    manifest_bytes = _json_bytes(manifest)
    manifest_relative = "run-manifest.json"

    review_root = root / "review"
    review_root.mkdir(parents=True, exist_ok=True)
    destinations = (
        review_root / "full-master-artifact-index.json",
        review_root / "full-master-evidence-coverage.json",
        root / manifest_relative,
    )
    existing = [str(path) for path in destinations if path.exists()]
    if existing:
        raise RunMetadataError(
            "refusing to overwrite finalized metadata: " + ", ".join(existing)
        )
    _write_new(destinations[0], artifact_bytes)
    _write_new(destinations[1], coverage_bytes)
    _write_new(destinations[2], manifest_bytes)
    return manifest


__all__ = [
    "SPEC_VERSION",
    "SPEC_KIND",
    "RUN_MANIFEST_KIND",
    "ARTIFACT_INDEX_KIND",
    "COVERAGE_KIND",
    "VOICE",
    "SHOT_IDS",
    "RunMetadataError",
    "finalize_run_metadata",
]
