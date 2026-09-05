#!/usr/bin/env python3
"""Read-only probe for production native action evidence.

This utility inventories a promo run without starting the game/OBS or calling
the STS2 action API.  It discovers strict v2 sidecars and validates them with
``vivhite_promo.action_evidence_v2``.  Operator marks, screenshots, game-log
windows, and rejected absence records are reported as non-native observations;
none can be promoted by this probe.

The command is intentionally diagnostic.  It never writes a sidecar, alters a
take row, or derives state/receipts from video pixels or logs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable


DEFAULT_TAKES = ("T07", "T10", "T16", "T18", "T19", "T20")
STRICT_KIND = "vivhite_promo_action_evidence"
STATE_KIND = "vivhite_promo_state_snapshot"
RECEIPT_KIND = "vivhite_promo_action_receipt"


def _module_import() -> Any:
    # ``v2`` and ``vivhite_promo`` are sibling directories under tools/promo.
    promo_root = Path(__file__).resolve().parents[1]
    if str(promo_root) not in sys.path:
        sys.path.insert(0, str(promo_root))
    from vivhite_promo import action_evidence_v2  # type: ignore

    return action_evidence_v2


def _json_object(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _iter_json_files(directory: Path) -> Iterable[Path]:
    if not directory.is_dir() or directory.is_symlink():
        return ()
    # Do not follow linked directories.  A linked artifact is invalid for the
    # strict validator and should not make a diagnostic scan leave the run.
    paths: list[Path] = []
    for candidate in directory.rglob("*.json"):
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
        except OSError:
            continue
        paths.append(candidate)
    return sorted(paths, key=lambda item: item.as_posix().lower())


def _attempt_dirs(run_root: Path, take_id: str) -> list[tuple[str, Path]]:
    found: dict[str, Path] = {}
    for area in ("contracts/takes", "capture/takes", "evidence/takes"):
        take_dir = run_root / area / take_id
        if not take_dir.is_dir() or take_dir.is_symlink():
            continue
        for attempt in take_dir.iterdir():
            if attempt.is_dir() and not attempt.is_symlink():
                found.setdefault(attempt.name, attempt)
    return sorted(found.items(), key=lambda item: item[0].lower())


def _status_for(
    *,
    strict_valid: list[dict[str, Any]],
    strict_invalid: list[dict[str, Any]],
    native_roles: set[str],
    operator_files: list[str],
    rejected_files: list[str],
) -> str:
    if strict_valid:
        return "native_valid"
    if strict_invalid:
        return "native_candidate_invalid"
    if native_roles:
        return "native_documents_without_sidecar"
    if operator_files:
        return "operator_only"
    if rejected_files:
        return "rejected_absence_record_only"
    return "missing"


def _scan_attempt(
    run_root: Path,
    take_id: str,
    attempt_id: str,
    attempt_dirs: list[Path],
    validator: Any,
) -> dict[str, Any]:
    strict_candidates: dict[str, Path] = {}
    native_roles: set[str] = set()
    operator_files: set[str] = set()
    rejected_files: set[str] = set()
    parse_errors: list[str] = []

    for directory in attempt_dirs:
        for path in _iter_json_files(directory):
            document = _json_object(path)
            if document is None:
                # Keep malformed files visible only when they look like a
                # contract/evidence record; random media probes are noise.
                if any(token in path.name.lower() for token in ("sidecar", "action", "state")):
                    parse_errors.append(path.relative_to(run_root).as_posix())
                continue
            kind = str(document.get("kind", ""))
            lower_name = path.name.lower()
            rejected_named = "rejected" in lower_name or "absence" in lower_name
            rejected_status = "rejected" in str(document.get("status", "")).lower()
            if (
                kind == STRICT_KIND
                and document.get("profile") == "production"
                and not rejected_named
                and not rejected_status
            ):
                strict_candidates[path.relative_to(run_root).as_posix()] = path
            elif kind == STRICT_KIND and (rejected_named or rejected_status):
                rejected_files.add(path.relative_to(run_root).as_posix())
            elif kind == STATE_KIND:
                role = str(document.get("role", ""))
                if role in ("state.before", "state.after"):
                    native_roles.add(role)
            elif kind == RECEIPT_KIND:
                if str(document.get("role", "action.receipt")) == "action.receipt":
                    native_roles.add("action.receipt")

            if any(token in lower_name for token in ("operator", "recording-marks", "live-receipt", "capture-evidence")):
                operator_files.add(path.relative_to(run_root).as_posix())
            if "rejected" in lower_name or "absence" in lower_name:
                rejected_files.add(path.relative_to(run_root).as_posix())

    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for relative, sidecar in strict_candidates.items():
        try:
            contract = validator.load_action_evidence(sidecar, artifact_root=run_root)
            identity = contract.capture_identity.to_mapping()
            valid.append(
                {
                    "path": relative,
                    "action_kind": contract.action_kind,
                    "subshot_id": contract.subshot_id,
                    "action_id": contract.action_id,
                    "capture_identity": identity,
                    "state_before_frame": contract.state_before.frame,
                    "pointer_down_frame": contract.action_receipt.pointer_down_frame,
                    "settled_frame": contract.action_receipt.settled_frame,
                    "state_after_frame": contract.state_after.frame,
                }
            )
        except Exception as exc:  # validator exposes one fail-closed error type
            invalid.append({"path": relative, "error": str(exc)})

    status = _status_for(
        strict_valid=valid,
        strict_invalid=invalid,
        native_roles=native_roles,
        operator_files=sorted(operator_files),
        rejected_files=sorted(rejected_files),
    )
    reasons: list[str] = []
    if status == "operator_only":
        reasons.append("operator marks/screenshots are not native state or pointer receipts")
    elif status == "native_documents_without_sidecar":
        missing = (set(("state.before", "action.receipt", "state.after")) - native_roles)
        if missing:
            reasons.append("native documents are incomplete; missing " + ", ".join(sorted(missing)))
        else:
            reasons.append("all native roles are present but no strict v2 sidecar binds them")
    elif status == "rejected_absence_record_only":
        reasons.append("absence/rejection record explicitly forbids loading as action evidence")
    elif status == "missing":
        reasons.append("no native triad or capture-time operator bundle found")
    if invalid:
        reasons.append("strict sidecar candidate(s) failed action_evidence_v2 validation")
    if parse_errors:
        reasons.append("some evidence-like JSON files could not be parsed")

    return {
        "take_id": take_id,
        "attempt_id": attempt_id,
        "status": status,
        "attempt_roots": [path.relative_to(run_root).as_posix() for path in attempt_dirs],
        "native_roles_observed": sorted(native_roles),
        "strict_sidecars": {"valid": valid, "invalid": invalid},
        "operator_files": sorted(operator_files),
        "rejected_or_absence_files": sorted(rejected_files),
        "parse_error_files": parse_errors,
        "reasons": reasons,
    }


def probe(run_root: Path, takes: Iterable[str]) -> dict[str, Any]:
    if not run_root.exists() or not run_root.is_dir() or run_root.is_symlink():
        raise ValueError(f"run_root must be an existing, non-linked directory: {run_root}")
    run_root = run_root.resolve(strict=True)
    validator = _module_import()
    result: list[dict[str, Any]] = []
    for take_id in takes:
        attempts = _attempt_dirs(run_root, take_id)
        if not attempts:
            result.append(
                {
                    "take_id": take_id,
                    "attempt_id": None,
                    "status": "missing",
                    "attempt_roots": [],
                    "native_roles_observed": [],
                    "strict_sidecars": {"valid": [], "invalid": []},
                    "operator_files": [],
                    "rejected_or_absence_files": [],
                    "parse_error_files": [],
                    "reasons": ["take directory is absent from contracts/capture/evidence"],
                }
            )
            continue
        for attempt_id, directory in attempts:
            # Scan matching attempt directories from all three areas.  A
            # sidecar in contracts may point at artifacts in evidence.
            roots = [
                run_root / "contracts/takes" / take_id / attempt_id,
                run_root / "capture/takes" / take_id / attempt_id,
                run_root / "evidence/takes" / take_id / attempt_id,
            ]
            roots = [path for path in roots if path.is_dir() and not path.is_symlink()]
            result.append(_scan_attempt(run_root, take_id, attempt_id, roots, validator))
    return {
        "tool": "native_evidence_probe",
        "schema_version": 1,
        "read_only": True,
        "strict_validator": "vivhite_promo.action_evidence_v2.load_action_evidence",
        "run_root": run_root.as_posix(),
        "takes": list(takes),
        "attempts": result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path, help="promo run root (for example tools/promo/runs/run-...)")
    parser.add_argument("--takes", nargs="+", default=list(DEFAULT_TAKES), help="take IDs to inspect")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--strict", action="store_true", help="return exit code 2 if any attempt is not native_valid")
    args = parser.parse_args(argv)
    try:
        report = probe(args.run_root, args.takes)
    except (OSError, ValueError, ImportError) as exc:
        parser.error(str(exc))
        return 2
    if args.format == "text":
        for item in report["attempts"]:
            print(f"{item['take_id']}/{item['attempt_id'] or '-'}: {item['status']}")
            for reason in item["reasons"]:
                print(f"  - {reason}")
        return 2 if args.strict and any(item["status"] != "native_valid" for item in report["attempts"]) else 0
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if args.strict and any(item["status"] != "native_valid" for item in report["attempts"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
