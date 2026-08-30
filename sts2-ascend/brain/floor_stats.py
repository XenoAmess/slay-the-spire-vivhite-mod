"""Read-only floor statistics for the ASCEND-VISION live dashboard.

The learning score deliberately awards +50 for a victory.  This module never
uses that score as a displayed floor: lifetime totals come from the raw-floor
aggregate (with a legacy migration fallback), while recent/trend data comes
from completed run evidence.  Ironclad and Vivhite profile views stay separate;
old root aggregates and run logs without a character id remain Ironclad data.
Active run files override compact archive catalog entries with the same run id.

Only the Python standard library is used so the overlay can import this module
without bringing up the agent, Godot API client, or review stack.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import time
from typing import Any, Mapping


_UNSET = object()
PROFILE_IDS = ("IRONCLAD", "VIVHITE")
PROFILE_LABELS = {"IRONCLAD": "Ironclad", "VIVHITE": "Vivhite"}


def _profile_id(value: Any) -> str | None:
    """Canonicalize API/content ids without discarding an unknown future id."""
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if "VIVHITE" in text:
        return "VIVHITE"
    if "IRONCLAD" in text:
        return "IRONCLAD"
    return text


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _floor(value: Any) -> int | None:
    number = _number(value)
    if number is None or number < 0 or number > 999:
        return None
    return int(number)


def _mean(records: list["_RunRecord"]) -> float | None:
    floors = [record.floor for record in records if record.floor is not None]
    return (sum(floors) / len(floors)) if floors else None


@dataclass(frozen=True)
class _RunRecord:
    file: str
    source: str
    run_id: str | None
    run_number: int | None
    started_at: str | None
    profile_id: str | None
    ascension: int | None
    victory: bool
    in_progress: bool
    floor: int | None
    decisions: int
    game_over: bool
    phantom: bool
    storage_kind: str | None = None

    @property
    def identity(self) -> str:
        return f"run:{self.run_id}" if self.run_id else f"file:{self.file}"

    @property
    def complete(self) -> bool:
        # Older logs sometimes retained in_progress=true after a GAME_OVER row.
        return self.victory or self.game_over or not self.in_progress

    @property
    def sort_key(self) -> tuple[str, int, str]:
        # The timestamp/file prefix remains useful when old logs have no run_number.
        return (self.started_at or self.file[:15], self.run_number or -1, self.file)


class FloorStatsProvider:
    """Incrementally merge aggregate, compacted, and active floor evidence.

    ``snapshot`` is safe to call from a viewer worker once per frame: filesystem
    checks are throttled by ``refresh_interval`` and unchanged run files are not
    reparsed.  A failed replacement retains the last successfully parsed copy of
    that component and marks the result stale instead of publishing fake zeros.
    """

    def __init__(self, knowledge_dir: Path, *, refresh_interval: float = 1.0,
                 recent_window: int = 20, comparison_window: int = 20,
                 trend_window: int = 40, rolling_window: int = 5):
        self.root = Path(knowledge_dir)
        self.refresh_interval = max(0.0, float(refresh_interval))
        self.recent_window = max(1, int(recent_window))
        self.comparison_window = max(1, int(comparison_window))
        self.trend_window = max(1, int(trend_window))
        self.rolling_window = max(1, int(rolling_window))

        self._lock = threading.RLock()
        self._last_check = 0.0
        self._stats_sig: object | tuple[int, int] | None = _UNSET
        self._progression_sig: object | tuple[int, int] | None = _UNSET
        self._catalog_sig: object | tuple[int, int] | None = _UNSET
        self._stats: dict[str, Any] = {}
        self._progression: dict[str, Any] = {}
        self._catalog: list[_RunRecord] = []
        self._catalog_invalid = 0
        self._active: dict[Path, tuple[tuple[int, int], _RunRecord]] = {}
        self._invalid_active: set[Path] = set()
        self._base: dict[str, Any] | None = None
        self._last_errors: tuple[str, ...] = ()

    @staticmethod
    def _signature(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    @staticmethod
    def _load_object(path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("root JSON value is not an object")
        return data

    @staticmethod
    def _active_record(path: Path, data: dict[str, Any]) -> _RunRecord:
        raw_decisions = data.get("decisions")
        decisions = ([row for row in raw_decisions if isinstance(row, dict)]
                     if isinstance(raw_decisions, list) else [])
        floors = [_floor(data.get("floor"))]
        floors.extend(_floor(row.get("floor")) for row in decisions)
        valid_floors = [value for value in floors if value is not None]
        game_over_rows = [row for row in decisions if row.get("screen") == "GAME_OVER"]
        victory = bool(data.get("victory")) or any(
            marker in str(row.get("reason") or "").casefold()
            for row in game_over_rows for marker in ("胜利", "victory"))
        run_id = data.get("run_id")
        profile = data.get("profile_id", data.get("character_id", data.get("character")))
        return _RunRecord(
            file=path.name,
            source="active",
            run_id=str(run_id) if run_id not in (None, "") else None,
            run_number=_integer(data.get("run_number")),
            started_at=(str(data.get("started_at"))
                        if data.get("started_at") not in (None, "") else None),
            profile_id=_profile_id(profile),
            ascension=_integer(data.get("ascension")),
            victory=victory,
            in_progress=bool(data.get("in_progress")),
            floor=max(valid_floors) if valid_floors else None,
            decisions=len(decisions),
            game_over=bool(game_over_rows),
            phantom=not decisions and not victory,
            storage_kind="active",
        )

    @staticmethod
    def _catalog_record(row: dict[str, Any]) -> _RunRecord | None:
        filename = row.get("file")
        if not isinstance(filename, str) or not filename:
            return None  # schema/description header
        run_id = row.get("run_id")
        decisions = max(0, _integer(row.get("decisions")) or 0)
        victory = bool(row.get("victory"))
        storage = row.get("storage") if isinstance(row.get("storage"), dict) else {}
        profile = row.get("profile_id", row.get("character_id", row.get("character")))
        return _RunRecord(
            file=filename,
            source="catalog",
            run_id=str(run_id) if run_id not in (None, "") else None,
            run_number=_integer(row.get("run_number")),
            started_at=(str(row.get("started_at"))
                        if row.get("started_at") not in (None, "") else None),
            profile_id=_profile_id(profile),
            ascension=_integer(row.get("ascension")),
            victory=victory,
            in_progress=bool(row.get("in_progress")),
            floor=_floor(row.get("floor")),
            decisions=decisions,
            game_over=str(row.get("last_screen") or "") == "GAME_OVER",
            phantom=bool(row.get("phantom_candidate")) or (not decisions and not victory),
            storage_kind=(str(storage.get("kind")) if storage.get("kind") else None),
        )

    @staticmethod
    def _validate_json_source(path: Path, value: dict[str, Any]) -> None:
        """Reject valid JSON whose minimum persisted schema is unusable.

        A syntactically valid ``{}`` must not silently replace trusted lifetime
        statistics.  Legacy stats without raw-floor keys remain valid because the
        provider can derive their sum from the learning outcome.
        """
        if path.name == "stats.json":
            global_stats = value.get("global")
            if not isinstance(global_stats, dict):
                raise ValueError("stats.global must be an object")
            runs = _integer(global_stats.get("runs"))
            wins = _integer(global_stats.get("wins"))
            if runs is None or runs < 0 or wins is None or wins < 0 or wins > runs:
                raise ValueError("stats.global runs/wins are invalid")
            raw_sum = _number(global_stats.get("floor_sum_raw"))
            outcome_sum = _number(global_stats.get("floors_total"))
            if raw_sum is None and outcome_sum is None:
                raise ValueError("stats.global has no usable floor total")
        elif path.name == "progression.json":
            if not isinstance(value.get("best_floor_by_ascension"), dict):
                raise ValueError("progression.best_floor_by_ascension must be an object")

    def _refresh_json(self, path: Path, signature_attr: str, value_attr: str,
                      errors: list[str]) -> bool:
        try:
            signature = self._signature(path)
        except OSError as exc:
            errors.append(f"{path.name}: {exc}")
            return False
        if signature == getattr(self, signature_attr):
            return False
        if signature is None:
            if getattr(self, signature_attr) is _UNSET:
                # A genuinely absent optional source on first startup is not an
                # error.  Once a complete version has been observed, disappearance
                # means evidence loss and must retain the last-good object.
                setattr(self, signature_attr, None)
                setattr(self, value_attr, {})
                return True
            errors.append(f"{path.name}: disappeared after a successful read")
            return False
        try:
            value = self._load_object(path)
            self._validate_json_source(path, value)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
            return False
        setattr(self, signature_attr, signature)
        setattr(self, value_attr, value)
        return True

    def _refresh_catalog(self, errors: list[str]) -> bool:
        path = self.root / "archive" / "run_catalog.jsonl"
        try:
            signature = self._signature(path)
        except OSError as exc:
            errors.append(f"run_catalog.jsonl: {exc}")
            return False
        if signature == self._catalog_sig:
            return False
        if signature is None:
            if self._catalog_sig is _UNSET:
                self._catalog_sig = None
                self._catalog = []
                self._catalog_invalid = 0
                return True
            errors.append("run_catalog.jsonl: disappeared after a successful read")
            return False
        records: list[_RunRecord] = []
        invalid = 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            saw_header = False
            for line_number, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"line {line_number} is not an object")
                if not saw_header:
                    if row.get("schema_version") != 1:
                        raise ValueError("missing or unsupported catalog header")
                    saw_header = True
                    continue
                record = self._catalog_record(row)
                if record is None:
                    raise ValueError(f"line {line_number} has no run file")
                records.append(record)
            if not saw_header:
                raise ValueError("empty catalog has no schema header")
            if self._catalog and not records:
                raise ValueError("catalog unexpectedly lost all run records")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"run_catalog.jsonl: {exc}")
            return False
        self._catalog_sig = signature
        self._catalog = records
        self._catalog_invalid = invalid
        return True

    def _refresh_active(self, errors: list[str]) -> bool:
        run_dir = self.root / "runs"
        try:
            paths = sorted(run_dir.glob("*.json")) if run_dir.exists() else []
        except OSError as exc:
            errors.append(f"runs: {exc}")
            return False
        changed = False
        present = set(paths)
        for old_path in list(self._active):
            if old_path not in present:
                old_record = self._active[old_path][1]
                takeover = any(
                    (record.identity == old_record.identity or record.file == old_record.file)
                    and record.storage_kind == "zip"
                    and record.complete and not record.phantom and record.floor is not None
                    for record in self._catalog
                )
                if takeover:
                    del self._active[old_path]
                    changed = True
                else:
                    errors.append(
                        f"{old_path.name}: disappeared before a valid catalog takeover")
        self._invalid_active.intersection_update(present)
        for path in paths:
            try:
                signature = self._signature(path)
            except OSError as exc:
                self._invalid_active.add(path)
                errors.append(f"{path.name}: {exc}")
                continue
            cached = self._active.get(path)
            if signature is not None and cached and cached[0] == signature:
                continue
            try:
                data = self._load_object(path)
                record = self._active_record(path, data)
                if not record.phantom and record.floor is None:
                    raise ValueError("run has decisions but no usable floor evidence")
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                self._invalid_active.add(path)
                errors.append(f"{path.name}: {exc}")
                continue
            if signature is None:
                continue
            self._active[path] = (signature, record)
            self._invalid_active.discard(path)
            changed = True
        return changed

    @staticmethod
    def _prefer(left: _RunRecord, right: _RunRecord) -> _RunRecord:
        # A later real trace wins; a zero-decision duplicate can never erase it.
        left_key = (not left.phantom, left.sort_key, left.decisions,
                    left.floor if left.floor is not None else -1)
        right_key = (not right.phantom, right.sort_key, right.decisions,
                     right.floor if right.floor is not None else -1)
        return left if left_key >= right_key else right

    def _merged_records(self) -> tuple[list[_RunRecord], int]:
        catalog: dict[str, _RunRecord] = {}
        active: dict[str, _RunRecord] = {}
        duplicates = 0
        for record in self._catalog:
            previous = catalog.get(record.identity)
            if previous is not None:
                duplicates += 1
                record = self._prefer(record, previous)
            catalog[record.identity] = record
        for _, record in self._active.values():
            previous = active.get(record.identity)
            if previous is not None:
                duplicates += 1
                record = self._prefer(record, previous)
            active[record.identity] = record
        for identity, record in active.items():
            previous = catalog.get(identity)
            if previous is not None:
                duplicates += 1
                # An active real trace is authoritative, including a continuation
                # that is currently in progress.  A phantom duplicate is ignored.
                if record.phantom and not previous.phantom:
                    continue
                if (record.floor is None and previous.floor is not None
                        and not previous.phantom):
                    # Valid JSON can still contain an entirely unusable floor.
                    # Active precedence must not erase cleaner persisted evidence.
                    continue
            catalog[identity] = record
        return list(catalog.values()), duplicates

    def _lifetime(self, completed: list[_RunRecord]) -> tuple[dict[str, Any], str]:
        global_stats = (self._stats.get("global")
                        if isinstance(self._stats.get("global"), dict) else {})
        runs = _integer(global_stats.get("runs"))
        wins = _integer(global_stats.get("wins"))
        if runs is not None and runs >= 0 and wins is not None and 0 <= wins <= runs:
            raw_sum = _number(global_stats.get("floor_sum_raw"))
            source = "aggregate_raw"
            if raw_sum is None:
                outcome_sum = _number(global_stats.get("floors_total"))
                if outcome_sum is not None:
                    raw_sum = max(0.0, outcome_sum - 50.0 * wins)
                    source = "aggregate_legacy"
            if raw_sum is not None and raw_sum >= 0:
                raw_best = _floor(global_stats.get("best_floor_raw"))
                if raw_best is None:
                    progression_best = max(
                        (_floor(value) or 0 for value in
                         (self._progression.get("best_floor_by_ascension") or {}).values()),
                        default=0,
                    ) if isinstance(self._progression.get("best_floor_by_ascension"), dict) else 0
                    evidence_best = max(
                        (record.floor or 0 for record in completed), default=0)
                    score_best = _floor(global_stats.get("best_floor")) or 0
                    score_guess = max(0, score_best - 50) if wins else score_best
                    raw_best = max(progression_best, evidence_best, score_guess)
                return ({
                    "runs": runs,
                    "wins": wins,
                    "win_rate": (wins / runs) if runs else None,
                    "mean_floor": (raw_sum / runs) if runs else None,
                    "best_floor": raw_best if runs else None,
                }, source)

        floors = [record.floor for record in completed if record.floor is not None]
        if floors:
            evidence_wins = sum(1 for record in completed if record.victory)
            return ({
                "runs": len(floors),
                "wins": evidence_wins,
                "win_rate": evidence_wins / len(floors),
                "mean_floor": sum(floors) / len(floors),
                "best_floor": max(floors),
            }, "records")
        return ({"runs": None, "wins": None, "win_rate": None,
                 "mean_floor": None, "best_floor": None}, "unavailable")

    @staticmethod
    def _records_lifetime(completed: list[_RunRecord]) -> tuple[dict[str, Any], str]:
        floors = [record.floor for record in completed if record.floor is not None]
        if not floors:
            return ({"runs": None, "wins": None, "win_rate": None,
                     "mean_floor": None, "best_floor": None}, "unavailable")
        wins = sum(1 for record in completed if record.victory)
        return ({
            "runs": len(floors),
            "wins": wins,
            "win_rate": wins / len(floors),
            "mean_floor": sum(floors) / len(floors),
            "best_floor": max(floors),
        }, "records")

    def _profile_aggregates(self) -> dict[str, dict[str, Any]]:
        """Return explicit per-profile raw aggregates, if the ledger has them.

        ``stats.profiles`` is the profile-aware contract.  Accepting the same
        object below ``stats.global`` makes the reader tolerant of an early
        nested prototype without changing the published dashboard shape.
        A row may be either the aggregate itself or ``{"global": aggregate}``.
        """
        global_stats = (self._stats.get("global")
                        if isinstance(self._stats.get("global"), dict) else {})
        containers = (self._stats.get("profiles"), global_stats.get("profiles"))
        result: dict[str, dict[str, Any]] = {}
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key, value in container.items():
                if not isinstance(value, dict):
                    continue
                aggregate = (value.get("global")
                             if isinstance(value.get("global"), dict) else value)
                profile = _profile_id(
                    aggregate.get("profile_id", aggregate.get("character_id", key)))
                if profile in PROFILE_IDS and profile not in result:
                    result[profile] = aggregate
        return result

    @staticmethod
    def _raw_profile_lifetime(aggregate: Mapping[str, Any]) -> dict[str, Any] | None:
        """Build display metrics only from raw-floor profile counters.

        Profile rows never fall back to the learning-score fields.  Legacy score
        migration is deliberately confined to the old root aggregate in
        ``_lifetime`` where wins/progression evidence can disambiguate it.
        """
        runs = _integer(aggregate.get("runs"))
        raw_sum = _number(aggregate.get("floor_sum_raw"))
        raw_best = _floor(aggregate.get("best_floor_raw"))
        if runs is None or runs < 0 or raw_sum is None or raw_sum < 0 or raw_best is None:
            return None
        wins = _integer(aggregate.get("wins"))
        if wins is None or wins < 0 or wins > runs:
            wins = None
        return {
            "runs": runs,
            "wins": wins,
            "win_rate": (wins / runs) if runs and wins is not None else None,
            "mean_floor": (raw_sum / runs) if runs else None,
            "best_floor": raw_best if runs else None,
        }

    def _profile_lifetime(
            self, profile: str, completed: list[_RunRecord],
            aggregates: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any], str]:
        aggregate = aggregates.get(profile)
        if aggregate is not None:
            lifetime = self._raw_profile_lifetime(aggregate)
            if lifetime is not None:
                return lifetime, "profile_raw"
        if not aggregates and profile == "IRONCLAD":
            # Before profile ledgers existed, the root was exclusively Ironclad.
            # Keep its migration fallback while never copying it into Vivhite.
            return self._lifetime(completed)
        return self._records_lifetime(completed)

    def _profile_view(
            self, profile: str, completed: list[_RunRecord],
            aggregates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        recent = completed[-self.recent_window:]
        previous_end = max(0, len(completed) - self.recent_window)
        previous_start = max(0, previous_end - self.comparison_window)
        previous = completed[previous_start:previous_end]
        recent_mean = _mean(recent)
        previous_mean = _mean(previous)
        trend_records = completed[-self.trend_window:]
        trend: list[dict[str, Any]] = []
        for index, record in enumerate(trend_records):
            rolling = trend_records[max(0, index + 1 - self.rolling_window):index + 1]
            trend.append({
                "run_id": record.run_id,
                "run_number": record.run_number,
                "started_at": record.started_at,
                "floor": record.floor,
                "victory": record.victory,
                "rolling_mean": _mean(rolling),
            })
        lifetime, source = self._profile_lifetime(profile, completed, aggregates)
        return {
            "profile_id": profile,
            "label": PROFILE_LABELS[profile],
            "lifetime": lifetime,
            "recent": {
                "window": self.recent_window,
                "count": len(recent),
                "mean_floor": recent_mean,
                "best_floor": max((record.floor for record in recent
                                   if record.floor is not None), default=None),
            },
            "previous": {
                "window": self.comparison_window,
                "count": len(previous),
                "mean_floor": previous_mean,
                "best_floor": max((record.floor for record in previous
                                   if record.floor is not None), default=None),
            },
            "delta_mean": ((recent_mean - previous_mean)
                           if recent_mean is not None and previous_mean is not None else None),
            "rolling_window": self.rolling_window,
            "rolling_mean": trend[-1]["rolling_mean"] if trend else None,
            "trend": trend,
            "quality": {"source": source, "completed_records": len(completed)},
        }

    def _build(self, errors: list[str]) -> dict[str, Any]:
        records, duplicates = self._merged_records()
        completed = sorted(
            (record for record in records
             if record.complete and not record.phantom and record.floor is not None),
            key=lambda record: record.sort_key,
        )
        recent = completed[-self.recent_window:]
        previous_end = max(0, len(completed) - self.recent_window)
        previous_start = max(0, previous_end - self.comparison_window)
        previous = completed[previous_start:previous_end]
        recent_mean = _mean(recent)
        previous_mean = _mean(previous)

        trend_records = completed[-self.trend_window:]
        trend: list[dict[str, Any]] = []
        for index, record in enumerate(trend_records):
            rolling = trend_records[max(0, index + 1 - self.rolling_window):index + 1]
            trend.append({
                "run_id": record.run_id,
                "run_number": record.run_number,
                "started_at": record.started_at,
                "floor": record.floor,
                "victory": record.victory,
                "rolling_mean": _mean(rolling),
            })

        auto_current = sorted(
            (record for record in records
             if record.in_progress and not record.complete and not record.phantom),
            key=lambda record: record.sort_key,
        )
        current = self._current_from_record(auto_current[-1]) if auto_current else None
        lifetime, source = self._lifetime(completed)
        profile_aggregates = self._profile_aggregates()
        profile_records = {profile: [] for profile in PROFILE_IDS}
        for record in completed:
            # Character ids were not persisted before profile-aware telemetry;
            # those old root records are the existing Ironclad history.
            profile = record.profile_id or "IRONCLAD"
            if profile in profile_records:
                profile_records[profile].append(record)
        profiles = {
            profile: self._profile_view(
                profile, profile_records[profile], profile_aggregates)
            for profile in PROFILE_IDS
        }
        rolling_means = {
            profile: profiles[profile]["rolling_mean"] for profile in PROFILE_IDS
        }
        ironclad_mean = rolling_means["IRONCLAD"]
        vivhite_mean = rolling_means["VIVHITE"]
        rolling_ratio = (
            vivhite_mean / ironclad_mean
            if (vivhite_mean is not None and ironclad_mean is not None
                and ironclad_mean != 0) else None
        )
        invalid_floor = sum(1 for record in records if record.floor is None and not record.phantom)
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stale": bool(errors),
            "lifetime": lifetime,
            "recent": {
                "window": self.recent_window,
                "count": len(recent),
                "mean_floor": recent_mean,
                "best_floor": max((record.floor for record in recent
                                   if record.floor is not None), default=None),
            },
            "previous": {
                "window": self.comparison_window,
                "count": len(previous),
                "mean_floor": previous_mean,
                "best_floor": max((record.floor for record in previous
                                   if record.floor is not None), default=None),
            },
            "delta_mean": ((recent_mean - previous_mean)
                           if recent_mean is not None and previous_mean is not None else None),
            "trend": trend,
            "current": current,
            "active_profile": ((current.get("profile_id") or "IRONCLAD")
                               if current is not None else None),
            "profiles": profiles,
            "profile_comparison": {
                "rolling_window": self.rolling_window,
                "rolling_means": rolling_means,
                "rolling_mean_ratio": rolling_ratio,
                "vivhite_to_ironclad_ratio": rolling_ratio,
                "ratio_numerator": "VIVHITE",
                "ratio_denominator": "IRONCLAD",
            },
            "quality": {
                "source": source,
                "catalog_records": len(self._catalog),
                "active_records": len(self._active),
                "completed_records": len(completed),
                "excluded_in_progress": sum(
                    1 for record in records if not record.complete and not record.phantom),
                "excluded_phantom": sum(1 for record in records if record.phantom),
                "invalid_records": (self._catalog_invalid + len(self._invalid_active)
                                    + invalid_floor),
                "duplicates": duplicates,
                "errors": errors[:8],
            },
        }

    @staticmethod
    def _current_from_record(record: _RunRecord) -> dict[str, Any]:
        result = {
            "run_id": record.run_id,
            "run_number": record.run_number,
            "ascension": record.ascension,
            "floor": record.floor,
            "turn": None,
        }
        if record.profile_id is not None:
            result["profile_id"] = record.profile_id
        return result

    @staticmethod
    def _normalize_current(current: Mapping[str, Any]) -> dict[str, Any]:
        run_id = current.get("run_id")
        result = {
            "run_id": str(run_id) if run_id not in (None, "") else None,
            "run_number": _integer(current.get("run_number")),
            "ascension": _integer(current.get("ascension")),
            "floor": _floor(current.get("floor")),
            "turn": _integer(current.get("turn")),
        }
        character = current.get("character_id")
        profile = _profile_id(current.get("profile_id", character))
        if character not in (None, ""):
            result["character_id"] = str(character)
        if profile is not None:
            result["profile_id"] = profile
        return result

    def refresh(self, *, force: bool = False) -> bool:
        """Refresh changed inputs and return whether the published base changed."""
        with self._lock:
            now = time.monotonic()
            if (not force and self._base is not None
                    and now - self._last_check < self.refresh_interval):
                return False
            self._last_check = now
            errors: list[str] = []
            changed = False
            changed |= self._refresh_json(
                self.root / "stats.json", "_stats_sig", "_stats", errors)
            changed |= self._refresh_json(
                self.root / "progression.json", "_progression_sig", "_progression", errors)
            changed |= self._refresh_catalog(errors)
            changed |= self._refresh_active(errors)
            error_tuple = tuple(errors)
            if self._base is None or changed or error_tuple != self._last_errors:
                candidate = self._build(errors)
                self._last_errors = error_tuple
                if self._base is not None:
                    previous_semantic = {
                        key: value for key, value in self._base.items()
                        if key != "updated_at"
                    }
                    candidate_semantic = {
                        key: value for key, value in candidate.items()
                        if key != "updated_at"
                    }
                    if candidate_semantic == previous_semantic:
                        # An in-progress run is rewritten after every decision.
                        # Its mtime is not a statistics change, and publishing a
                        # fresh timestamp would make the viewer redraw stable
                        # cards once per second.
                        return False
                self._base = candidate
                return True
            return False

    def snapshot(self, current: Mapping[str, Any] | None = None, *,
                 force: bool = False) -> dict[str, Any]:
        """Return a detached dashboard snapshot, optionally overriding live run data."""
        with self._lock:
            self.refresh(force=force)
            assert self._base is not None
            result = copy.deepcopy(self._base)
            if current is not None:
                result["current"] = self._normalize_current(current)
                result["active_profile"] = (
                    result["current"].get("profile_id") or "IRONCLAD")
            return result


__all__ = ["FloorStatsProvider", "PROFILE_IDS"]
