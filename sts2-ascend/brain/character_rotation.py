"""Durable Vivhite catch-up and balanced Ironclad run rotation.

The main agent can integrate the state machine at three narrow boundaries::

    rotation = CharacterRotation.from_knowledge_root(knowledge_root)
    choice = rotation.resolve_selection(state["character_select"]["characters"])
    rotation.observe_active_run(state["run_id"], state["run"]["character_id"])
    rotation.record_terminal(run_id, terminal_persisted=True)

While Vivhite's persisted completed-run total trails Ironclad's legacy-root
total, selectable runs follow ``V,V,V,V,I``.  Reaching parity permanently
switches the durable scheduler to ``V,I`` alternation.  ``record_terminal``
must be called only after both the terminal run record and character statistics
have been successfully persisted.  Passing ``terminal_persisted=False`` is an
explicit no-op.  The rotation state itself is published with an atomic
sibling-file replacement, so a failed write cannot expose or cache a
half-advanced rotation.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any


VIVHITE = "VIVHITE"
IRONCLAD = "IRONCLAD"
ROTATION = (VIVHITE, IRONCLAD)
CATCHUP_ROTATION = (VIVHITE, VIVHITE, VIVHITE, VIVHITE, IRONCLAD)
BALANCED_MODE = "balanced_1_to_1"
CATCHUP_MODE = "catchup_4_to_1"
STATE_FILENAME = "character_rotation.json"
STATE_VERSION = 2
LEGACY_STATE_VERSION = 1
ORPHAN_EVIDENCE_VERSION = 1
ORPHAN_RELEASE_REASON = "no_native_save_no_continue"
# A prepared orphan transaction may be retried a small, persisted number of
# times after a process/CAS failure.  Keeping the cap here (next to the proof
# schema) makes an accidental hot-loop impossible; an operator can inspect the
# retained marker and supply a new explicit transaction after rollback.
ORPHAN_RELEASE_MAX_ATTEMPTS = 3

# A missing native save is only actionable when the read-only probe can say so
# explicitly.  These values are deliberately narrower than a generic
# ``missing``/``false`` flag: callers must distinguish an absent/empty artifact
# from a probe that failed to read the game profile.
_ORPHAN_ARTIFACT_STATES = frozenset({
    "absent", "missing", "empty", "zero_byte", "no_matching_run",
})

READY = "ready"
BLOCKED = "blocked"

_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}
_REPLACE_RETRIES = 8


class CharacterRotationError(RuntimeError):
    """The durable rotation state or an observed transition is inconsistent."""


@dataclass(frozen=True)
class RotationSnapshot:
    """A read-only view suitable for diagnostics and agent decisions."""

    next_character: str
    active_run_id: str | None
    active_character: str | None
    active_character_id: str | None
    finalized_run_ids: tuple[str, ...]
    schedule_mode: str
    catchup_index: int
    catchup_completed: bool
    vivhite_runs: int
    ironclad_runs: int
    # Run IDs explicitly released as unrecoverable orphans.  They are kept out
    # of ``finalized_run_ids`` on purpose: an orphan is not a terminal game
    # result and must never be counted as a played loss or consume a slot.
    orphaned_run_ids: tuple[str, ...] = ()

    @property
    def target_character(self) -> str:
        """Actual active character when resuming, otherwise the next selection."""
        return self.active_character or self.next_character

    @property
    def has_active_run(self) -> bool:
        return self.active_run_id is not None


@dataclass(frozen=True)
class SelectionResult:
    """Exact target resolution for a CHARACTER_SELECT payload."""

    status: str
    target_character: str
    character_id: str | None = None
    option_index: Any | None = None
    reason: str = ""

    @property
    def ready(self) -> bool:
        return self.status == READY

    @property
    def blocked(self) -> bool:
        return self.status == BLOCKED


@dataclass(frozen=True)
class TerminalResult:
    """Outcome of one idempotent terminal-persistence acknowledgement."""

    run_id: str
    character: str | None
    terminal_persisted: bool
    advanced: bool
    next_character: str
    quota_consumed: bool
    schedule_mode: str


@dataclass(frozen=True)
class OrphanReleaseResult:
    """Outcome of an explicit, evidence-backed orphan release.

    ``released`` is false for an idempotent replay of the same evidence.  No
    field in this result represents a terminal outcome; in particular
    ``quota_consumed`` is permanently false.
    """

    run_id: str
    character: str
    released: bool
    next_character: str
    quota_consumed: bool
    schedule_mode: str
    reason: str = ORPHAN_RELEASE_REASON


@dataclass(frozen=True)
class PersistedRunCounts:
    """Successfully persisted completed-run totals for both profile roots."""

    vivhite: int
    ironclad: int

    @property
    def vivhite_caught_up(self) -> bool:
        return self.vivhite >= self.ironclad


def canonical_character_id(character_id: object) -> str | None:
    """Map game character IDs to one of the two rotation identities.

    Game/mod IDs contain the stable ``VIVHITE`` or ``IRONCLAD`` token (for
    example ``VIVHITE_CHARACTER_VIVHITE_CHARACTER``).  Unknown and ambiguous
    IDs are deliberately not guessed.
    """
    if not isinstance(character_id, str):
        return None
    normalized = character_id.strip().upper()
    if not normalized:
        return None
    matches = tuple(character for character in ROTATION if character in normalized)
    return matches[0] if len(matches) == 1 else None


def _other(character: str) -> str:
    if character == VIVHITE:
        return IRONCLAD
    if character == IRONCLAD:
        return VIVHITE
    raise CharacterRotationError(f"unsupported rotation character: {character!r}")


def _normalize_run_id(run_id: object) -> str:
    if not isinstance(run_id, str) or not run_id.strip():
        raise CharacterRotationError("run_id must be a non-empty string")
    return run_id.strip()


def _normalize_character(character_id: object) -> tuple[str, str]:
    character = canonical_character_id(character_id)
    if character is None:
        raise CharacterRotationError(
            f"character_id is not Vivhite or Ironclad: {character_id!r}")
    return character, str(character_id).strip()


def _orphan_text(value: object, field: str, *, max_len: int = 240) -> str:
    """Validate a bounded audit string without accepting implicit coercion."""
    if not isinstance(value, str) or not value.strip():
        raise CharacterRotationError(
            f"orphan evidence {field} must be a non-empty string")
    text = value.strip()
    if len(text) > max_len:
        raise CharacterRotationError(
            f"orphan evidence {field} is too long")
    return text


def _orphan_artifact_state(value: object, field: str) -> str:
    state = _orphan_text(value, field, max_len=64).casefold()
    if state not in _ORPHAN_ARTIFACT_STATES:
        raise CharacterRotationError(
            f"orphan evidence {field} has unsupported state: {value!r}")
    return state


def _orphan_state_version(value: object, field: str) -> int | float | str:
    """Validate one bounded API state marker without guessing its semantics."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise CharacterRotationError(
            f"orphan evidence {field} state_version is invalid")
    if isinstance(value, float) and not math.isfinite(value):
        raise CharacterRotationError(
            f"orphan evidence {field} state_version is non-finite")
    if isinstance(value, str):
        value = _orphan_text(value, field, max_len=80)
    elif value < 0:
        raise CharacterRotationError(
            f"orphan evidence {field} state_version is negative")
    return value


def _orphan_timestamp(value: object, field: str) -> tuple[str, datetime]:
    """Validate an ISO-8601 audit timestamp and return a comparable instant."""
    text = _orphan_text(value, field, max_len=80)
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise CharacterRotationError(
            f"orphan evidence {field} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return text, parsed.astimezone(timezone.utc)


def _validate_orphan_evidence(
        evidence: object, expected_run_id: str,
        expected_character: str, expected_character_id: str | None = None,
) -> dict[str, Any]:
    """Validate and normalize a read-only orphan probe result.

    This is intentionally a *negative* proof contract.  A caller cannot pass a
    bare ``orphaned=True`` flag: it must provide two consecutive API snapshots
    and a completed native-file probe with no matching run and no read errors.
    Only bounded, non-secret fields are copied into the rotation ledger.
    """
    if not isinstance(evidence, Mapping):
        raise CharacterRotationError("orphan evidence must be an object")
    if evidence.get("version") != ORPHAN_EVIDENCE_VERSION:
        raise CharacterRotationError(
            "unsupported orphan evidence version: "
            f"{evidence.get('version')!r}")
    run_id = _normalize_run_id(evidence.get("run_id"))
    if run_id != expected_run_id:
        raise CharacterRotationError(
            f"orphan evidence run_id {run_id!r} does not match "
            f"active run {expected_run_id!r}")
    reason = _orphan_text(evidence.get("reason"), "reason", max_len=96)
    if reason != ORPHAN_RELEASE_REASON:
        raise CharacterRotationError(
            f"unsupported orphan release reason: {reason!r}")
    evidence_character, normalized_id = _normalize_character(
        evidence.get("character_id"))
    if evidence_character != expected_character:
        raise CharacterRotationError(
            f"orphan evidence character disagrees with active run: "
            f"{evidence_character!r} != {expected_character!r}")
    if expected_character_id is not None:
        expected_character_norm = _normalize_character(expected_character_id)[1]
        if normalized_id != expected_character_norm:
            raise CharacterRotationError(
                "orphan evidence character_id does not match active identity")

    observed_at, observed_instant = _orphan_timestamp(
        evidence.get("observed_at"), "observed_at")
    api = evidence.get("api")
    if not isinstance(api, Mapping):
        raise CharacterRotationError("orphan evidence api must be an object")
    raw_samples = api.get("samples")
    if not isinstance(raw_samples, list) or len(raw_samples) < 2:
        raise CharacterRotationError(
            "orphan evidence requires at least two API snapshots")
    if api.get("consecutive") is not True:
        raise CharacterRotationError(
            "orphan evidence API snapshots are not marked consecutive")
    samples: list[dict[str, Any]] = []
    for index, raw_sample in enumerate(raw_samples[:8]):
        if not isinstance(raw_sample, Mapping):
            raise CharacterRotationError(
                f"orphan evidence api sample {index} is not an object")
        screen = _orphan_text(raw_sample.get("screen"),
                              f"api.samples[{index}].screen", max_len=64)
        sample_run_id = _orphan_text(
            raw_sample.get("run_id"),
            f"api.samples[{index}].run_id", max_len=96)
        if screen != "MAIN_MENU" or sample_run_id != "run_unknown":
            raise CharacterRotationError(
                "orphan evidence API samples must be MAIN_MENU/run_unknown")
        if raw_sample.get("run_empty") is not True:
            raise CharacterRotationError(
                f"orphan evidence api sample {index} has a run payload")
        if raw_sample.get("continue_run") is not False:
            raise CharacterRotationError(
                f"orphan evidence api sample {index} does not prove "
                "continue_run is absent")
        sequence = raw_sample.get("sequence")
        observed_sample_at = raw_sample.get("observed_at")
        sample_version = raw_sample.get("state_version")
        if sample_version is None:
            raise CharacterRotationError(
                f"orphan evidence api sample {index} lacks state_version marker")
        if sequence is None and observed_sample_at is None:
            raise CharacterRotationError(
                f"orphan evidence api sample {index} lacks ordering metadata")
        if sequence is not None and (
                isinstance(sequence, bool) or not isinstance(sequence, int)
                or sequence < 0):
            raise CharacterRotationError(
                f"orphan evidence api sample {index} sequence is invalid")
        sample_instant = None
        if observed_sample_at is not None:
            observed_sample_at, sample_instant = _orphan_timestamp(
                observed_sample_at,
                f"api.samples[{index}].observed_at")
        if sample_version is not None:
            sample_version = _orphan_state_version(
                sample_version, f"api.samples[{index}]")
        # Keep only stable, bounded facts; arbitrary API payloads do not belong
        # in the rotation ledger and could contain secrets or huge data.
        normalized_sample = {
            "screen": screen,
            "run_id": sample_run_id,
            "run_empty": True,
            "continue_run": False,
        }
        if sequence is not None:
            normalized_sample["sequence"] = sequence
        if observed_sample_at is not None:
            normalized_sample["observed_at"] = observed_sample_at
        if sample_version is not None:
            normalized_sample["state_version"] = sample_version
        samples.append(normalized_sample)

    # At least one monotonic marker must distinguish the two observations.  A
    # caller cannot satisfy this by duplicating the same stale frame twice.
    ordered = False
    sequences = [row.get("sequence") for row in samples]
    if all(value is not None for value in sequences):
        ordered = all(a < b for a, b in zip(sequences, sequences[1:]))
    if not ordered:
        times = [row.get("observed_at") for row in samples]
        if all(value is not None for value in times):
            try:
                instants = [
                    _orphan_timestamp(value, "api.sample.observed_at")[1]
                    for value in times
                ]
                ordered = all(a < b for a, b in zip(instants, instants[1:]))
            except CharacterRotationError:
                ordered = False
    if not ordered:
        versions = [row.get("state_version") for row in samples]
        if all(value is not None for value in versions):
            # A state_version is a freshness marker, not necessarily a counter;
            # only use it as an ordering fallback when its native values are
            # directly comparable.  Equal versions remain valid when sequence
            # or timestamps establish the two distinct observations.
            try:
                ordered = all(a < b for a, b in zip(versions, versions[1:]))
            except TypeError:
                ordered = False
    if not ordered:
        raise CharacterRotationError(
            "orphan evidence API snapshots are not distinct and ordered")

    native = evidence.get("native")
    if not isinstance(native, Mapping):
        raise CharacterRotationError("orphan evidence native must be an object")
    if native.get("probe_complete") is not True:
        raise CharacterRotationError(
            "orphan evidence native probe is incomplete")
    read_errors = native.get("read_errors")
    if not isinstance(read_errors, list) or read_errors:
        raise CharacterRotationError(
            "orphan evidence native probe has read errors")

    def artifact_status(key: str, aliases: tuple[str, ...] = ()) -> str:
        raw = native.get(key)
        if isinstance(raw, Mapping):
            raw = raw.get("status")
        if raw is None:
            for alias in aliases:
                raw = native.get(alias)
                if isinstance(raw, Mapping):
                    raw = raw.get("status")
                if raw is not None:
                    break
        return _orphan_artifact_state(raw, f"native.{key}")

    save_status = artifact_status(
        "save", ("save_status", "save_backup", "current_run_save",
                  "current_run.save", "current_run.save.backup"))
    history_status = artifact_status(
        "history", ("history_status", "run_history", "history_dir"))
    stmp_raw = native.get("stmp")
    if isinstance(stmp_raw, Mapping):
        stmp_raw = stmp_raw.get("status")
    if stmp_raw is None:
        stmp_raw = native.get("stmp_status", "absent")
    stmp_status = _orphan_artifact_state(stmp_raw, "native.stmp")
    if native.get("save_match") is not False:
        raise CharacterRotationError(
            "orphan evidence native save match is not explicitly false")
    if native.get("history_match") is not False:
        raise CharacterRotationError(
            "orphan evidence native history match is not explicitly false")
    api_latest_version = api.get("latest_state_version")
    if api_latest_version is not None:
        api_latest_version = _orphan_state_version(
            api_latest_version, "api.latest_state_version")
        latest_sample_version = samples[-1].get("state_version")
        if (latest_sample_version is None
                or api_latest_version != latest_sample_version):
            raise CharacterRotationError(
                "orphan evidence latest state_version does not match sample")
    probe_observed_at = native.get("probe_observed_at")
    if probe_observed_at is None:
        probe_observed_at = native.get("observed_at")
    if probe_observed_at is not None:
        probe_observed_at, probe_instant = _orphan_timestamp(
            probe_observed_at, "native.probe_observed_at")
        latest_sample_time = samples[-1].get("observed_at")
        if latest_sample_time is not None:
            latest_instant = _orphan_timestamp(
                latest_sample_time, "api.samples[-1].observed_at")[1]
            if probe_instant < latest_instant:
                raise CharacterRotationError(
                    "orphan native probe predates the latest API snapshot")
        if observed_instant < probe_instant:
            raise CharacterRotationError(
                "orphan evidence observed_at predates native probe")
    probe_state_version = native.get("api_state_version")
    if probe_state_version is not None:
        probe_state_version = _orphan_state_version(
            probe_state_version, "native.api_state_version")
        latest_sample_version = samples[-1].get("state_version")
        if (latest_sample_version is None
                or probe_state_version != latest_sample_version):
            raise CharacterRotationError(
                "orphan native probe is not bound to latest API state_version")
    checked_paths = native.get("checked_paths")
    if not isinstance(checked_paths, list) or not checked_paths:
        raise CharacterRotationError(
            "orphan evidence must list checked native paths")
    normalized_paths: list[dict[str, Any]] = []
    for index, raw_path in enumerate(checked_paths[:32]):
        if not isinstance(raw_path, Mapping):
            raise CharacterRotationError(
                f"orphan evidence checked path {index} is not an object")
        kind = _orphan_text(raw_path.get("kind"),
                            f"native.checked_paths[{index}].kind", max_len=40)
        status = _orphan_artifact_state(
            raw_path.get("status"),
            f"native.checked_paths[{index}].status")
        # Absolute paths are useful for an audit but are not needed to replay
        # the decision.  Retain a bounded display path only.
        path_text = _orphan_text(raw_path.get("path"),
                                 f"native.checked_paths[{index}].path", max_len=260)
        row: dict[str, Any] = {"kind": kind, "status": status, "path": path_text}
        if "bytes" in raw_path:
            bytes_value = raw_path.get("bytes")
            if (isinstance(bytes_value, bool) or not isinstance(bytes_value, int)
                    or bytes_value < 0 or bytes_value > 2**63 - 1):
                raise CharacterRotationError(
                    f"orphan evidence checked path {index} bytes is invalid")
            row["bytes"] = bytes_value
        digest = raw_path.get("sha256")
        if digest is not None:
            digest = _orphan_text(digest,
                                  f"native.checked_paths[{index}].sha256", max_len=128)
            row["sha256"] = digest
        normalized_paths.append(row)

    path_kinds = {str(row["kind"]).casefold() for row in normalized_paths}
    if not any(kind in path_kinds for kind in (
            "save", "save_backup", "progress", "progress.save",
            "current_run_save", "current_run.save")):
        raise CharacterRotationError(
            "orphan evidence must check the native save path")
    if not any(kind in path_kinds for kind in (
            "history", "run_history", "history_dir", "history_file")):
        raise CharacterRotationError(
            "orphan evidence must check the native history path")

    normalized_api = {
        "consecutive": True,
        "samples": samples,
    }
    if api_latest_version is not None:
        normalized_api["latest_state_version"] = api_latest_version
    normalized_native = {
        "probe_complete": True,
        "save": {"status": save_status},
        "history": {"status": history_status},
        "stmp": {"status": stmp_status},
        "save_match": False,
        "history_match": False,
        "read_errors": [],
        "checked_paths": normalized_paths,
    }
    if probe_observed_at is not None:
        normalized_native["probe_observed_at"] = probe_observed_at
    if probe_state_version is not None:
        normalized_native["api_state_version"] = probe_state_version

    return {
        "version": ORPHAN_EVIDENCE_VERSION,
        "reason": reason,
        "run_id": run_id,
        "character_id": normalized_id,
        "observed_at": observed_at,
        "api": normalized_api,
        "native": normalized_native,
    }


def _default_state(counts: PersistedRunCounts) -> dict[str, Any]:
    catchup_completed = counts.vivhite_caught_up
    return {
        "version": STATE_VERSION,
        "next_character": VIVHITE,
        "schedule_mode": (
            BALANCED_MODE if catchup_completed else CATCHUP_MODE),
        "catchup_index": 0,
        "catchup_completed": catchup_completed,
        "last_completed_character": None,
        "active_run": None,
        "finalized_runs": {},
        "orphaned_runs": {},
    }


def _validated_run_ledger(
        data: Mapping[str, Any], path: Path, *, legacy: bool
) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Validate the active/idempotence ledger shared by v1 and v2 states."""
    raw_finalized = data.get("finalized_runs")
    if not isinstance(raw_finalized, Mapping):
        raise CharacterRotationError(f"finalized_runs is not an object: {path}")
    finalized: dict[str, str] = {}
    for raw_run_id, raw_character in raw_finalized.items():
        run_id = _normalize_run_id(raw_run_id)
        if raw_character not in ROTATION:
            raise CharacterRotationError(
                f"invalid finalized character for {run_id!r}: {raw_character!r}")
        finalized[run_id] = raw_character

    raw_active = data.get("active_run")
    active: dict[str, Any] | None
    if raw_active is None:
        active = None
    elif isinstance(raw_active, Mapping):
        run_id = _normalize_run_id(raw_active.get("run_id"))
        character = raw_active.get("character")
        character_id = raw_active.get("character_id")
        actual, normalized_id = _normalize_character(character_id)
        if character not in ROTATION or actual != character:
            raise CharacterRotationError(
                f"active character fields disagree for {run_id!r}: "
                f"{character!r} / {character_id!r}")
        if run_id in finalized:
            raise CharacterRotationError(
                f"run_id {run_id!r} is both active and finalized in {path}")
        scheduled = None if legacy else raw_active.get("scheduled_character")
        if scheduled is not None and scheduled not in ROTATION:
            raise CharacterRotationError(
                f"invalid scheduled character for {run_id!r}: {scheduled!r}")
        if scheduled is not None and scheduled != character:
            raise CharacterRotationError(
                f"active run {run_id!r} cannot consume {scheduled!r} as "
                f"{character!r}")
        active = {
            "run_id": run_id,
            "character": character,
            "character_id": normalized_id,
            "scheduled_character": scheduled,
        }
    else:
        raise CharacterRotationError(f"active_run is not an object or null: {path}")
    return finalized, active


def _validated_orphan_ledger(
        data: Mapping[str, Any], path: Path,
        finalized: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Validate the non-terminal orphan audit ledger.

    Older rotation files have no ``orphaned_runs`` key and are treated as an
    empty ledger.  Orphan IDs may never overlap finalized IDs; keeping the two
    sets disjoint is what prevents a recovery record from being mistaken for a
    completed loss by downstream readers.
    """
    raw_orphans = data.get("orphaned_runs", {})
    if raw_orphans is None:
        raw_orphans = {}
    if not isinstance(raw_orphans, Mapping):
        raise CharacterRotationError(f"orphaned_runs is not an object: {path}")
    orphaned: dict[str, dict[str, Any]] = {}
    for raw_run_id, raw_entry in raw_orphans.items():
        run_id = _normalize_run_id(raw_run_id)
        if run_id in finalized:
            raise CharacterRotationError(
                f"run_id {run_id!r} is both orphaned and finalized in {path}")
        if not isinstance(raw_entry, Mapping):
            raise CharacterRotationError(
                f"orphaned entry for {run_id!r} is not an object")
        entry_run_id = _normalize_run_id(raw_entry.get("run_id"))
        if entry_run_id != run_id:
            raise CharacterRotationError(
                f"orphaned entry run_id disagrees for {run_id!r}")
        character = raw_entry.get("character")
        character_id = raw_entry.get("character_id")
        actual, normalized_character_id = _normalize_character(character_id)
        if character not in ROTATION or actual != character:
            raise CharacterRotationError(
                f"orphaned character fields disagree for {run_id!r}")
        reason = _orphan_text(raw_entry.get("reason"), "orphaned.reason", max_len=96)
        if reason != ORPHAN_RELEASE_REASON:
            raise CharacterRotationError(
                f"invalid orphaned reason for {run_id!r}: {reason!r}")
        released_at = _orphan_text(
            raw_entry.get("released_at"), "orphaned.released_at", max_len=80)
        evidence = _validate_orphan_evidence(
            raw_entry.get("evidence"), run_id, actual, normalized_character_id)
        orphaned[run_id] = {
            "run_id": run_id,
            "character": character,
            "character_id": normalized_character_id,
            "reason": reason,
            "released_at": released_at,
            "evidence": evidence,
        }
    return orphaned


def _validated_v2_state(data: object, path: Path) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise CharacterRotationError(f"rotation state is not an object: {path}")
    if data.get("version") != STATE_VERSION:
        raise CharacterRotationError(
            f"unsupported rotation state version in {path}: {data.get('version')!r}")

    next_character = data.get("next_character")
    if next_character not in ROTATION:
        raise CharacterRotationError(
            f"invalid next_character in {path}: {next_character!r}")

    schedule_mode = data.get("schedule_mode")
    if schedule_mode not in (CATCHUP_MODE, BALANCED_MODE):
        raise CharacterRotationError(
            f"invalid schedule_mode in {path}: {schedule_mode!r}")
    catchup_index = data.get("catchup_index")
    if (isinstance(catchup_index, bool)
            or not isinstance(catchup_index, int)
            or not 0 <= catchup_index < len(CATCHUP_ROTATION)):
        raise CharacterRotationError(
            f"invalid catchup_index in {path}: {catchup_index!r}")
    catchup_completed = data.get("catchup_completed")
    if not isinstance(catchup_completed, bool):
        raise CharacterRotationError(
            f"invalid catchup_completed in {path}: {catchup_completed!r}")
    if schedule_mode == CATCHUP_MODE:
        if catchup_completed:
            raise CharacterRotationError(
                f"catch-up mode is already completed in {path}")
        expected = CATCHUP_ROTATION[catchup_index]
        if next_character != expected:
            raise CharacterRotationError(
                f"catch-up phase {catchup_index} requires {expected}, got "
                f"{next_character} in {path}")
    elif not catchup_completed:
        raise CharacterRotationError(
            f"balanced mode must latch catchup_completed in {path}")

    last_completed = data.get("last_completed_character")
    if last_completed is not None and last_completed not in ROTATION:
        raise CharacterRotationError(
            f"invalid last_completed_character in {path}: {last_completed!r}")
    finalized, active = _validated_run_ledger(data, path, legacy=False)
    orphaned = _validated_orphan_ledger(data, path, finalized)
    if active is not None and active["run_id"] in orphaned:
        raise CharacterRotationError(
            f"run_id {active['run_id']!r} is both active and orphaned in {path}")
    if (active is not None
            and active.get("scheduled_character") is not None
            and active["scheduled_character"] != next_character):
        raise CharacterRotationError(
            f"active scheduled character disagrees with next_character in {path}")

    return {
        "version": STATE_VERSION,
        "next_character": next_character,
        "schedule_mode": schedule_mode,
        "catchup_index": catchup_index,
        "catchup_completed": catchup_completed,
        "last_completed_character": last_completed,
        "active_run": active,
        "finalized_runs": finalized,
        "orphaned_runs": orphaned,
    }


def _load_or_migrate_state(
        data: object, path: Path, counts: PersistedRunCounts
) -> tuple[dict[str, Any], bool]:
    """Load v2 or migrate the old strict-alternation state without guessing.

    A v1 active Vivhite run is catch-up slot zero: counting it produces exactly
    four Vivhite completions before the first scheduled Ironclad.  A v1 active
    Ironclad remains authoritative but is outside the new quota, so the first
    selectable run after it ends still starts at catch-up slot zero.
    """
    if not isinstance(data, Mapping):
        raise CharacterRotationError(f"rotation state is not an object: {path}")
    version = data.get("version")
    if version == STATE_VERSION:
        return _validated_v2_state(data, path), False
    if version != LEGACY_STATE_VERSION:
        raise CharacterRotationError(
            f"unsupported rotation state version in {path}: {version!r}")

    next_character = data.get("next_character")
    if next_character not in ROTATION:
        raise CharacterRotationError(
            f"invalid next_character in {path}: {next_character!r}")
    finalized, active = _validated_run_ledger(data, path, legacy=True)
    caught_up = counts.vivhite_caught_up
    if caught_up:
        schedule_mode = BALANCED_MODE
        migrated_next = next_character
        if active is not None and active["character"] == migrated_next:
            active["scheduled_character"] = active["character"]
    else:
        schedule_mode = CATCHUP_MODE
        migrated_next = VIVHITE
        if active is not None:
            active["scheduled_character"] = (
                VIVHITE
                if active["character"] == VIVHITE
                else None)

    migrated = {
        "version": STATE_VERSION,
        "next_character": migrated_next,
        "schedule_mode": schedule_mode,
        "catchup_index": 0,
        "catchup_completed": caught_up,
        "last_completed_character": None,
        "active_run": active,
        "finalized_runs": finalized,
        "orphaned_runs": {},
    }
    return _validated_v2_state(migrated, path), True


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve()).casefold()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Publish one complete JSON state without ever truncating the destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False,
                dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(temporary, path)
                temporary = None
                break
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


def _persisted_run_total(path: Path, profile_label: str) -> int:
    """Read one profile's successfully saved stats.global.runs total."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 0
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise CharacterRotationError(
            f"malformed {profile_label} stats {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CharacterRotationError(
            f"{profile_label} stats is not an object: {path}")
    global_stats = payload.get("global")
    if global_stats is None:
        return 0
    if not isinstance(global_stats, Mapping):
        raise CharacterRotationError(
            f"{profile_label} stats.global is not an object: {path}")
    raw_runs = global_stats.get("runs", 0)
    if isinstance(raw_runs, bool):
        raise CharacterRotationError(
            f"{profile_label} stats.global.runs is invalid: {raw_runs!r}")
    try:
        runs = int(raw_runs)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CharacterRotationError(
            f"{profile_label} stats.global.runs is invalid: {raw_runs!r}") from exc
    if isinstance(raw_runs, float) and raw_runs != runs:
        raise CharacterRotationError(
            f"{profile_label} stats.global.runs is not integral: {raw_runs!r}")
    if runs < 0:
        raise CharacterRotationError(
            f"{profile_label} stats.global.runs is negative: {runs}")
    return runs


def _snapshot(
        state: Mapping[str, Any], counts: PersistedRunCounts
) -> RotationSnapshot:
    active = state.get("active_run")
    return RotationSnapshot(
        next_character=state["next_character"],
        active_run_id=active["run_id"] if active else None,
        active_character=active["character"] if active else None,
        active_character_id=active["character_id"] if active else None,
        finalized_run_ids=tuple(state["finalized_runs"]),
        schedule_mode=state["schedule_mode"],
        catchup_index=state["catchup_index"],
        catchup_completed=state["catchup_completed"],
        vivhite_runs=counts.vivhite,
        ironclad_runs=counts.ironclad,
        orphaned_run_ids=tuple(state.get("orphaned_runs", {})),
    )


class CharacterRotation:
    """Durable 4:1 catch-up scheduler that latches to strict 1:1."""

    def __init__(self, state_path: str | os.PathLike[str]) -> None:
        self.state_path = Path(state_path)
        self.knowledge_root = self.state_path.parent
        self._lock = _path_lock(self.state_path)

    @classmethod
    def from_knowledge_root(
            cls, knowledge_root: str | os.PathLike[str]) -> "CharacterRotation":
        return cls(Path(knowledge_root) / STATE_FILENAME)

    def _persisted_counts_unlocked(self) -> PersistedRunCounts:
        return PersistedRunCounts(
            vivhite=_persisted_run_total(
                self.knowledge_root / "profiles" / "vivhite" / "stats.json",
                "Vivhite"),
            ironclad=_persisted_run_total(
                self.knowledge_root / "stats.json", "Ironclad legacy root"),
        )

    @staticmethod
    def _reconcile_idle_schedule(
            state: Mapping[str, Any], counts: PersistedRunCounts
    ) -> tuple[dict[str, Any], bool]:
        """Latch catch-up completion observed outside terminal acknowledgement."""
        if (state.get("active_run") is not None
                or state["schedule_mode"] != CATCHUP_MODE
                or not counts.vivhite_caught_up):
            return dict(state), False
        updated = dict(state)
        updated["schedule_mode"] = BALANCED_MODE
        updated["catchup_completed"] = True
        last_completed = updated.get("last_completed_character")
        if last_completed in ROTATION:
            updated["next_character"] = _other(last_completed)
        return updated, True

    def _load_unlocked(
            self, *, reconcile_idle: bool = True
    ) -> tuple[dict[str, Any], PersistedRunCounts, bool]:
        counts = self._persisted_counts_unlocked()
        try:
            raw = self.state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _default_state(counts), counts, False
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CharacterRotationError(
                f"malformed rotation state {self.state_path}: {exc}") from exc
        state, dirty = _load_or_migrate_state(parsed, self.state_path, counts)
        if reconcile_idle:
            state, reconciled = self._reconcile_idle_schedule(state, counts)
            dirty = dirty or reconciled
        return _validated_v2_state(state, self.state_path), counts, dirty

    def _save_unlocked(self, state: Mapping[str, Any]) -> None:
        validated = _validated_v2_state(state, self.state_path)
        _atomic_write_json(self.state_path, validated)

    def snapshot(self) -> RotationSnapshot:
        with self._lock:
            state, counts, dirty = self._load_unlocked()
            if dirty:
                self._save_unlocked(state)
            return _snapshot(state, counts)

    def orphan_record(self, run_id: object) -> dict[str, Any] | None:
        """Return one immutable orphan audit row, if the CAS already landed.

        Startup recovery uses this read-only accessor to distinguish a crash
        after the rotation CAS from a crash before it.  It deliberately returns
        a deep copy and never creates, removes, or promotes a ledger entry.
        """
        normalized_run_id = _normalize_run_id(run_id)
        with self._lock:
            state, _counts, dirty = self._load_unlocked(reconcile_idle=False)
            if dirty:
                self._save_unlocked(state)
            row = state.get("orphaned_runs", {}).get(normalized_run_id)
            return copy.deepcopy(row) if isinstance(row, Mapping) else None

    @property
    def target_character(self) -> str:
        return self.snapshot().target_character

    def resolve_selection(
            self, characters: Iterable[Mapping[str, Any]]) -> SelectionResult:
        """Resolve only the required target; never choose a fallback character."""
        with self._lock:
            state, _counts, dirty = self._load_unlocked()
            if dirty:
                self._save_unlocked(state)
            active = state["active_run"]
            if active is not None:
                return SelectionResult(
                    status=BLOCKED,
                    target_character=active["character"],
                    reason=f"active_run_pending_terminal:{active['run_id']}",
                )

            target = state["next_character"]
            target_seen = False
            missing_index = False
            for candidate in characters:
                if not isinstance(candidate, Mapping):
                    continue
                character_id = candidate.get("character_id")
                if canonical_character_id(character_id) != target:
                    continue
                target_seen = True
                if candidate.get("is_locked") or candidate.get("is_random"):
                    continue
                option_index = candidate.get("index")
                if option_index is None:
                    missing_index = True
                    continue
                return SelectionResult(
                    status=READY,
                    target_character=target,
                    character_id=str(character_id),
                    option_index=option_index,
                    reason="target_ready",
                )

            if missing_index:
                reason = "target_missing_index"
            elif target_seen:
                reason = "target_unavailable"
            else:
                reason = "target_missing"
            return SelectionResult(
                status=BLOCKED,
                target_character=target,
                reason=reason,
            )

    def observe_active_run(
            self, run_id: object, character_id: object) -> RotationSnapshot:
        """Persist the game's actual active character for restart recovery.

        The actual character is authoritative for an already-active run, including
        a run that predates this state file.  A different unresolved run is never
        overwritten: its terminal outcome must be durably acknowledged first.
        """
        normalized_run_id = _normalize_run_id(run_id)
        character, normalized_character_id = _normalize_character(character_id)
        with self._lock:
            state, counts, dirty = self._load_unlocked()
            finalized_character = state["finalized_runs"].get(normalized_run_id)
            if finalized_character is not None:
                if finalized_character != character:
                    raise CharacterRotationError(
                        f"finalized run {normalized_run_id!r} changed character from "
                        f"{finalized_character} to {character}")
                if dirty:
                    self._save_unlocked(state)
                return _snapshot(state, counts)
            if normalized_run_id in state.get("orphaned_runs", {}):
                # An explicitly released orphan can never silently come back as
                # a fresh run with the same ID.  Requiring a new authoritative
                # native identity prevents stale API echoes from reoccupying the
                # scheduler slot after recovery.
                raise CharacterRotationError(
                    f"orphaned run {normalized_run_id!r} cannot be reactivated")

            active = state["active_run"]
            if active is not None:
                if active["run_id"] != normalized_run_id:
                    raise CharacterRotationError(
                        f"cannot replace unresolved active run {active['run_id']!r} "
                        f"with {normalized_run_id!r}")
                if active["character"] != character:
                    raise CharacterRotationError(
                        f"active run {normalized_run_id!r} changed character from "
                        f"{active['character']} to {character}")
                if dirty:
                    self._save_unlocked(state)
                return _snapshot(state, counts)

            updated = dict(state)
            updated["active_run"] = {
                "run_id": normalized_run_id,
                "character": character,
                "character_id": normalized_character_id,
                "scheduled_character": (
                    character if character == state["next_character"] else None),
            }
            self._save_unlocked(updated)
            return _snapshot(updated, counts)

    def reconcile_native_continue(
            self, expected_run_id: object, actual_run_id: object,
            character_id: object) -> RotationSnapshot:
        """Replace a stale active identity proven by the native Continue path.

        The game can preserve one playable native save while the HTTP run id
        previously recorded by Brain no longer exists.  This transition is not
        a terminal result: it must preserve the scheduled character slot, quota
        phase, counters and finalized ledger.  Callers must supply the exact old
        identity they observed before selecting the game's native Continue action.
        """
        normalized_expected = _normalize_run_id(expected_run_id)
        normalized_actual = _normalize_run_id(actual_run_id)
        if normalized_actual == normalized_expected:
            raise CharacterRotationError(
                "native continue reconciliation requires a different run_id")
        character, normalized_character_id = _normalize_character(character_id)

        with self._lock:
            state, counts, _dirty = self._load_unlocked(reconcile_idle=False)
            active = state["active_run"]
            if active is None:
                raise CharacterRotationError(
                    f"cannot reconcile {normalized_expected!r}; no active run exists")
            if active["run_id"] != normalized_expected:
                raise CharacterRotationError(
                    f"cannot reconcile {normalized_expected!r}; unresolved active "
                    f"run is {active['run_id']!r}")
            if active["character"] != character:
                raise CharacterRotationError(
                    f"native continue changed character from {active['character']} "
                    f"to {character}")
            finalized_character = state["finalized_runs"].get(normalized_actual)
            if finalized_character is not None:
                raise CharacterRotationError(
                    f"native continue run {normalized_actual!r} is already finalized "
                    f"as {finalized_character}")
            if normalized_actual in state.get("orphaned_runs", {}):
                raise CharacterRotationError(
                    f"native continue run {normalized_actual!r} was already "
                    "released as an orphan")

            updated = dict(state)
            updated["active_run"] = {
                "run_id": normalized_actual,
                "character": character,
                "character_id": normalized_character_id,
                "scheduled_character": active.get("scheduled_character"),
            }
            self._save_unlocked(updated)
            return _snapshot(updated, counts)

    def release_orphan_run(
            self, run_id: object, *, evidence: object,
            character_id: object | None = None,
    ) -> OrphanReleaseResult:
        """Release one exact active run after a complete negative proof.

        This is intentionally separate from :meth:`record_terminal` and
        :meth:`release_human_controlled_run`.  It records an audit entry in the
        durable rotation state but never adds the ID to ``finalized_runs``,
        changes ``next_character``/catch-up counters, or consumes a quota slot.
        The evidence validator is fail-closed and accepts only two consecutive
        ``MAIN_MENU/run_unknown`` snapshots plus a successful native-file probe
        showing no matching save/history.
        """
        normalized_run_id = _normalize_run_id(run_id)
        explicit_character = None
        explicit_character_id = None
        if character_id is not None:
            explicit_character, explicit_character_id = _normalize_character(
                character_id)

        with self._lock:
            state, counts, _dirty = self._load_unlocked(reconcile_idle=False)
            existing = state.get("orphaned_runs", {}).get(normalized_run_id)
            if existing is not None:
                # A retry is safe only when it carries byte-for-byte equivalent
                # normalized evidence and, if supplied, the same character.
                normalized_evidence = _validate_orphan_evidence(
                    evidence, normalized_run_id, existing["character"],
                    existing["character_id"])
                if explicit_character is not None \
                        and explicit_character != existing["character"]:
                    raise CharacterRotationError(
                        f"orphan run {normalized_run_id!r} character mismatch")
                if normalized_evidence != existing["evidence"]:
                    raise CharacterRotationError(
                        f"orphan run {normalized_run_id!r} evidence changed")
                return OrphanReleaseResult(
                    run_id=normalized_run_id,
                    character=existing["character"],
                    released=False,
                    next_character=state["next_character"],
                    quota_consumed=False,
                    schedule_mode=state["schedule_mode"],
                )

            if normalized_run_id in state["finalized_runs"]:
                raise CharacterRotationError(
                    f"cannot release finalized run {normalized_run_id!r} as orphan")
            active = state.get("active_run")
            if active is None or active["run_id"] != normalized_run_id:
                active_id = active["run_id"] if active else None
                raise CharacterRotationError(
                    f"cannot release orphan {normalized_run_id!r}; unresolved "
                    f"active run is {active_id!r}")
            if (explicit_character is not None
                    and explicit_character != active["character"]):
                raise CharacterRotationError(
                    f"orphan character for {normalized_run_id!r} disagrees with "
                    f"active character {active['character']}")
            normalized_evidence = _validate_orphan_evidence(
                evidence, normalized_run_id, active["character"],
                active["character_id"])

            orphaned = dict(state.get("orphaned_runs", {}))
            orphaned[normalized_run_id] = {
                "run_id": normalized_run_id,
                "character": active["character"],
                "character_id": active["character_id"],
                "reason": ORPHAN_RELEASE_REASON,
                "released_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "evidence": normalized_evidence,
            }
            updated = dict(state)
            updated["active_run"] = None
            updated["orphaned_runs"] = orphaned
            # Do not touch any schedule/terminal fields.  _save_unlocked also
            # revalidates the disjoint finalized/orphaned ledgers atomically.
            self._save_unlocked(updated)
            return OrphanReleaseResult(
                run_id=normalized_run_id,
                character=active["character"],
                released=True,
                next_character=updated["next_character"],
                quota_consumed=False,
                schedule_mode=updated["schedule_mode"],
            )

    # Descriptive alias used by recovery callers; keeping one implementation
    # avoids a second, less strict path that could accidentally consume quota.
    release_unrecoverable_orphan = release_orphan_run

    def release_human_controlled_run(self, run_id: object) -> RotationSnapshot:
        """Forget one human-controlled active run without consuming a quota slot.

        Manual takeover runs are deliberately excluded from autonomous balance
        statistics.  They therefore cannot satisfy ``record_terminal``'s contract
        that character stats were durably committed first.  Releasing only the
        exact matching active identity keeps the scheduler on the same character
        slot and prevents a later character-select screen from remaining blocked.
        """
        normalized_run_id = _normalize_run_id(run_id)
        with self._lock:
            state, counts, dirty = self._load_unlocked(reconcile_idle=False)
            active = state["active_run"]
            if active is None:
                if dirty:
                    self._save_unlocked(state)
                return _snapshot(state, counts)
            if active["run_id"] != normalized_run_id:
                raise CharacterRotationError(
                    f"cannot release human-controlled run {normalized_run_id!r}; "
                    f"unresolved active run is {active['run_id']!r}")
            updated = dict(state)
            updated["active_run"] = None
            self._save_unlocked(updated)
            return _snapshot(updated, counts)

    def record_terminal(
            self, run_id: object, *, terminal_persisted: bool,
            character_id: object | None = None) -> TerminalResult:
        """Advance exactly once after the caller has durably saved a terminal run.

        ``run_id`` is retained in the durable ledger, making retries idempotent
        across process restarts and even after later runs have completed.
        """
        if not isinstance(terminal_persisted, bool):
            raise CharacterRotationError("terminal_persisted must be a bool")
        normalized_run_id = _normalize_run_id(run_id)
        explicit_character = None
        if character_id is not None:
            explicit_character, _ = _normalize_character(character_id)

        with self._lock:
            # The caller saves character stats immediately before this method.
            # Delay parity reconciliation until this terminal has consumed (or
            # deliberately not consumed) its scheduled slot.
            state, counts, dirty = self._load_unlocked(reconcile_idle=False)
            if normalized_run_id in state.get("orphaned_runs", {}):
                # Orphan releases are audit-only records, never terminal
                # outcomes.  A later stale GAME_OVER echo must not promote one
                # back into the completed ledger or consume a schedule slot.
                raise CharacterRotationError(
                    f"orphaned run {normalized_run_id!r} cannot be finalized")
            finalized_character = state["finalized_runs"].get(normalized_run_id)
            if finalized_character is not None:
                if (explicit_character is not None
                        and explicit_character != finalized_character):
                    raise CharacterRotationError(
                        f"finalized run {normalized_run_id!r} changed character from "
                        f"{finalized_character} to {explicit_character}")
                state, reconciled = self._reconcile_idle_schedule(state, counts)
                if dirty or reconciled:
                    self._save_unlocked(state)
                return TerminalResult(
                    run_id=normalized_run_id,
                    character=finalized_character,
                    terminal_persisted=terminal_persisted,
                    advanced=False,
                    next_character=state["next_character"],
                    quota_consumed=False,
                    schedule_mode=state["schedule_mode"],
                )

            active = state["active_run"]
            active_for_run = active if (
                active is not None and active["run_id"] == normalized_run_id) else None
            observed_character = (
                active_for_run["character"] if active_for_run else explicit_character)

            if not terminal_persisted:
                # Explicit no-op: even a pending v1 migration is not written and
                # the durable quota phase cannot move.
                return TerminalResult(
                    run_id=normalized_run_id,
                    character=observed_character,
                    terminal_persisted=False,
                    advanced=False,
                    next_character=state["next_character"],
                    quota_consumed=False,
                    schedule_mode=state["schedule_mode"],
                )

            if active is not None and active_for_run is None:
                raise CharacterRotationError(
                    f"terminal run {normalized_run_id!r} does not match unresolved "
                    f"active run {active['run_id']!r}")
            if (active_for_run is not None and explicit_character is not None
                    and explicit_character != active_for_run["character"]):
                raise CharacterRotationError(
                    f"terminal character for {normalized_run_id!r} disagrees with "
                    f"active character {active_for_run['character']}")
            if observed_character is None:
                raise CharacterRotationError(
                    f"cannot advance terminal run {normalized_run_id!r} without its "
                    "actual character")

            scheduled_character = (
                active_for_run.get("scheduled_character")
                if active_for_run is not None
                else (observed_character
                      if observed_character == state["next_character"] else None))
            quota_consumed = scheduled_character == observed_character

            updated = dict(state)
            updated_finalized = dict(state["finalized_runs"])
            updated_finalized[normalized_run_id] = observed_character
            updated["finalized_runs"] = updated_finalized
            updated["active_run"] = None
            updated["last_completed_character"] = observed_character

            if updated["schedule_mode"] == CATCHUP_MODE:
                if quota_consumed:
                    next_index = (
                        int(updated["catchup_index"]) + 1
                    ) % len(CATCHUP_ROTATION)
                    updated["catchup_index"] = next_index
                    updated["next_character"] = CATCHUP_ROTATION[next_index]
                if counts.vivhite_caught_up:
                    updated["schedule_mode"] = BALANCED_MODE
                    updated["catchup_completed"] = True
                    updated["next_character"] = _other(observed_character)
            elif quota_consumed:
                updated["next_character"] = _other(observed_character)

            self._save_unlocked(updated)
            return TerminalResult(
                run_id=normalized_run_id,
                character=observed_character,
                terminal_persisted=True,
                advanced=True,
                next_character=updated["next_character"],
                quota_consumed=quota_consumed,
                schedule_mode=updated["schedule_mode"],
            )


CharacterRotationStateMachine = CharacterRotation

__all__ = [
    "BALANCED_MODE",
    "BLOCKED",
    "CATCHUP_MODE",
    "CATCHUP_ROTATION",
    "CharacterRotation",
    "CharacterRotationError",
    "CharacterRotationStateMachine",
    "IRONCLAD",
    "ORPHAN_EVIDENCE_VERSION",
    "ORPHAN_RELEASE_MAX_ATTEMPTS",
    "ORPHAN_RELEASE_REASON",
    "OrphanReleaseResult",
    "PersistedRunCounts",
    "READY",
    "RotationSnapshot",
    "SelectionResult",
    "STATE_FILENAME",
    "STATE_VERSION",
    "TerminalResult",
    "VIVHITE",
    "canonical_character_id",
    "_validate_orphan_evidence",
]
