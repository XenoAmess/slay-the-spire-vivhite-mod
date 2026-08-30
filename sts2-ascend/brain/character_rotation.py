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
from dataclasses import dataclass
import json
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
    "PersistedRunCounts",
    "READY",
    "RotationSnapshot",
    "SelectionResult",
    "STATE_FILENAME",
    "STATE_VERSION",
    "TerminalResult",
    "VIVHITE",
    "canonical_character_id",
]
