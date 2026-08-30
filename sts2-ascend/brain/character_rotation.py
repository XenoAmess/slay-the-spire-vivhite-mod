"""Durable, strict Vivhite/Ironclad run rotation.

The main agent can integrate the state machine at three narrow boundaries::

    rotation = CharacterRotation.from_knowledge_root(knowledge_root)
    choice = rotation.resolve_selection(state["character_select"]["characters"])
    rotation.observe_active_run(state["run_id"], state["run"]["character_id"])
    rotation.record_terminal(run_id, terminal_persisted=True)

``record_terminal`` must be called only after the terminal run record has been
successfully persisted.  Passing ``terminal_persisted=False`` is an explicit
no-op.  The rotation state itself is published with an atomic sibling-file
replacement, so a failed write cannot expose or cache a half-advanced rotation.
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
STATE_FILENAME = "character_rotation.json"
STATE_VERSION = 1

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


def _default_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "next_character": VIVHITE,
        "active_run": None,
        "finalized_runs": {},
    }


def _validated_state(data: object, path: Path) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise CharacterRotationError(f"rotation state is not an object: {path}")
    if data.get("version") != STATE_VERSION:
        raise CharacterRotationError(
            f"unsupported rotation state version in {path}: {data.get('version')!r}")

    next_character = data.get("next_character")
    if next_character not in ROTATION:
        raise CharacterRotationError(
            f"invalid next_character in {path}: {next_character!r}")

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
    active: dict[str, str] | None
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
        active = {
            "run_id": run_id,
            "character": character,
            "character_id": normalized_id,
        }
    else:
        raise CharacterRotationError(f"active_run is not an object or null: {path}")

    return {
        "version": STATE_VERSION,
        "next_character": next_character,
        "active_run": active,
        "finalized_runs": finalized,
    }


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


def _snapshot(state: Mapping[str, Any]) -> RotationSnapshot:
    active = state.get("active_run")
    return RotationSnapshot(
        next_character=state["next_character"],
        active_run_id=active["run_id"] if active else None,
        active_character=active["character"] if active else None,
        active_character_id=active["character_id"] if active else None,
        finalized_run_ids=tuple(state["finalized_runs"]),
    )


class CharacterRotation:
    """Strict two-character rotation backed by one atomic JSON state file."""

    def __init__(self, state_path: str | os.PathLike[str]) -> None:
        self.state_path = Path(state_path)
        self._lock = _path_lock(self.state_path)

    @classmethod
    def from_knowledge_root(
            cls, knowledge_root: str | os.PathLike[str]) -> "CharacterRotation":
        return cls(Path(knowledge_root) / STATE_FILENAME)

    def _load_unlocked(self) -> dict[str, Any]:
        try:
            raw = self.state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _default_state()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CharacterRotationError(
                f"malformed rotation state {self.state_path}: {exc}") from exc
        return _validated_state(parsed, self.state_path)

    def _save_unlocked(self, state: Mapping[str, Any]) -> None:
        validated = _validated_state(state, self.state_path)
        _atomic_write_json(self.state_path, validated)

    def snapshot(self) -> RotationSnapshot:
        with self._lock:
            return _snapshot(self._load_unlocked())

    @property
    def target_character(self) -> str:
        return self.snapshot().target_character

    def resolve_selection(
            self, characters: Iterable[Mapping[str, Any]]) -> SelectionResult:
        """Resolve only the required target; never choose a fallback character."""
        with self._lock:
            state = self._load_unlocked()
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
            state = self._load_unlocked()
            finalized_character = state["finalized_runs"].get(normalized_run_id)
            if finalized_character is not None:
                if finalized_character != character:
                    raise CharacterRotationError(
                        f"finalized run {normalized_run_id!r} changed character from "
                        f"{finalized_character} to {character}")
                return _snapshot(state)

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
                return _snapshot(state)

            updated = dict(state)
            updated["active_run"] = {
                "run_id": normalized_run_id,
                "character": character,
                "character_id": normalized_character_id,
            }
            self._save_unlocked(updated)
            return _snapshot(updated)

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
            state = self._load_unlocked()
            finalized_character = state["finalized_runs"].get(normalized_run_id)
            if finalized_character is not None:
                if (explicit_character is not None
                        and explicit_character != finalized_character):
                    raise CharacterRotationError(
                        f"finalized run {normalized_run_id!r} changed character from "
                        f"{finalized_character} to {explicit_character}")
                return TerminalResult(
                    run_id=normalized_run_id,
                    character=finalized_character,
                    terminal_persisted=terminal_persisted,
                    advanced=False,
                    next_character=state["next_character"],
                )

            active = state["active_run"]
            active_for_run = active if (
                active is not None and active["run_id"] == normalized_run_id) else None
            observed_character = (
                active_for_run["character"] if active_for_run else explicit_character)

            if not terminal_persisted:
                return TerminalResult(
                    run_id=normalized_run_id,
                    character=observed_character,
                    terminal_persisted=False,
                    advanced=False,
                    next_character=state["next_character"],
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

            updated = dict(state)
            updated_finalized = dict(state["finalized_runs"])
            updated_finalized[normalized_run_id] = observed_character
            updated["finalized_runs"] = updated_finalized
            updated["active_run"] = None
            updated["next_character"] = _other(observed_character)
            self._save_unlocked(updated)
            return TerminalResult(
                run_id=normalized_run_id,
                character=observed_character,
                terminal_persisted=True,
                advanced=True,
                next_character=updated["next_character"],
            )


CharacterRotationStateMachine = CharacterRotation

__all__ = [
    "BLOCKED",
    "CharacterRotation",
    "CharacterRotationError",
    "CharacterRotationStateMachine",
    "IRONCLAD",
    "READY",
    "RotationSnapshot",
    "SelectionResult",
    "STATE_FILENAME",
    "TerminalResult",
    "VIVHITE",
    "canonical_character_id",
]
