"""Read-only floor statistics for the ASCEND-VISION live dashboard.

The learning score deliberately awards +50 for a victory.  This module never
uses that score as a displayed floor: lifetime totals come from the raw-floor
aggregate (with a legacy migration fallback), while recent/trend data comes
from completed run evidence.  Ironclad and Vivhite profile views stay separate;
historical logs without both ``profile_id`` and ``character_id`` remain
Ironclad data regardless of their storage directory.
Active run files override compact archive catalog entries with the same run id.

Only the Python standard library is used so the overlay can import this module
without bringing up the agent, Godot API client, or review stack.
"""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import threading
import time
from typing import Any, Mapping
import zipfile

try:
    from character_strategy import (
        CONSERVATION_GEOMETRY,
        CRIMSON_INTEGRAL,
        HYBRID,
        RECURSIVE_ASTRAL,
        VIVHITE_CARD_CATALOG,
    )
except ImportError:  # pragma: no cover - package import fallback
    from .character_strategy import (
        CONSERVATION_GEOMETRY,
        CRIMSON_INTEGRAL,
        HYBRID,
        RECURSIVE_ASTRAL,
        VIVHITE_CARD_CATALOG,
    )


_UNSET = object()
_LIVE_DASHBOARD_SCHEMA = "sts2.ascend-live/v1"
_LIVE_DASHBOARD_FRESH_SEC = 5.0
PROFILE_IDS = ("ironclad", "vivhite")
PROFILE_LABELS = {"ironclad": "Ironclad", "vivhite": "Vivhite"}
PROFILE_CHARACTER_IDS = {
    "ironclad": "IRONCLAD",
    "vivhite": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
}
MIXED_BUILD = "mixed"
BRIDGE_ONLY_BUILD = "bridge_only"
FOREIGN_BUILD = "foreign"
UNCLASSIFIED_BUILD = "unclassified"
BRIDGE_SYSTEM = "bridge"
NEUTRAL_SYSTEM = "neutral"
FOREIGN_SYSTEM = "foreign"
_VIVHITE_PRIMARY_SYSTEMS = (
    CONSERVATION_GEOMETRY,
    RECURSIVE_ASTRAL,
    CRIMSON_INTEGRAL,
)
VIVHITE_BUILD_ORDER = (
    *_VIVHITE_PRIMARY_SYSTEMS,
    MIXED_BUILD,
    BRIDGE_ONLY_BUILD,
    FOREIGN_BUILD,
    UNCLASSIFIED_BUILD,
)
VIVHITE_BUILD_LABELS = {
    CONSERVATION_GEOMETRY: "守恒几何",
    RECURSIVE_ASTRAL: "递归星算",
    CRIMSON_INTEGRAL: "绯彩积分",
    MIXED_BUILD: "混合构筑",
    BRIDGE_ONLY_BUILD: "仅跨体系",
    FOREIGN_BUILD: "外来牌构筑",
    UNCLASSIFIED_BUILD: "未分类",
}
VIVHITE_SELECTION_SYSTEM_ORDER = (
    *_VIVHITE_PRIMARY_SYSTEMS,
    BRIDGE_SYSTEM,
    NEUTRAL_SYSTEM,
    FOREIGN_SYSTEM,
)
VIVHITE_SELECTION_SYSTEM_LABELS = {
    CONSERVATION_GEOMETRY: VIVHITE_BUILD_LABELS[CONSERVATION_GEOMETRY],
    RECURSIVE_ASTRAL: VIVHITE_BUILD_LABELS[RECURSIVE_ASTRAL],
    CRIMSON_INTEGRAL: VIVHITE_BUILD_LABELS[CRIMSON_INTEGRAL],
    BRIDGE_SYSTEM: "桥接",
    NEUTRAL_SYSTEM: "中性",
    FOREIGN_SYSTEM: "外来",
}
_VIVHITE_CARDS = {entry.card_id: entry for entry in VIVHITE_CARD_CATALOG}


def _vivhite_system(card_id: str) -> str:
    entry = _VIVHITE_CARDS.get(str(card_id or "").strip().upper())
    if entry is None:
        return FOREIGN_SYSTEM
    if entry.rarity == "basic":
        return NEUTRAL_SYSTEM
    tag = entry.build_tags[0]
    return BRIDGE_SYSTEM if tag == HYBRID else tag


VIVHITE_CATALOG_SYSTEM_COUNTS = dict(Counter(
    _vivhite_system(entry.card_id) for entry in VIVHITE_CARD_CATALOG))
_EXPECTED_VIVHITE_SYSTEM_COUNTS = {
    CONSERVATION_GEOMETRY: 17,
    RECURSIVE_ASTRAL: 17,
    CRIMSON_INTEGRAL: 17,
    BRIDGE_SYSTEM: 7,
    NEUTRAL_SYSTEM: 3,
}
if VIVHITE_CATALOG_SYSTEM_COUNTS != _EXPECTED_VIVHITE_SYSTEM_COUNTS:
    raise RuntimeError(
        "Vivhite statistics taxonomy must remain 17A/17B/17C/7bridge/3neutral")


def _profile_id(value: Any) -> str | None:
    """Canonicalize API/content ids without discarding an unknown future id."""
    if value in (None, ""):
        return None
    text = str(value).strip().casefold()
    if not text:
        return None
    if "vivhite" in text:
        return "vivhite"
    if "ironclad" in text:
        return "ironclad"
    return text


def _explicit_historical_profile_id(value: Mapping[str, Any]) -> str | None:
    """Resolve only the two durable identity fields persisted on run logs."""
    return (_profile_id(value.get("profile_id"))
            or _profile_id(value.get("character_id")))


def _historical_profile_id(value: Mapping[str, Any]) -> str:
    return _explicit_historical_profile_id(value) or "ironclad"


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


def _card_picks(data: Mapping[str, Any]) -> tuple[str, ...]:
    """Return durable card additions in persisted order, including duplicates."""
    raw = data.get("attribution_tags")
    if not isinstance(raw, list):
        raw = data.get("attribution")
    if not isinstance(raw, list):
        return ()
    result: list[str] = []
    for tag in raw:
        if not isinstance(tag, (list, tuple)) or len(tag) < 2:
            continue
        if str(tag[0]).strip().casefold() != "card_pick":
            continue
        card_id = str(tag[1] or "").strip().upper()
        if card_id:
            result.append(card_id)
    return tuple(result)


def _has_card_pick_evidence(data: Mapping[str, Any]) -> bool:
    return (isinstance(data.get("attribution_tags"), list)
            or isinstance(data.get("attribution"), list))


@dataclass(frozen=True)
class _DeckCard:
    card_id: str
    name: str | None = None
    upgraded: bool = False


def _final_deck(data: Mapping[str, Any]) -> tuple[_DeckCard, ...]:
    raw = data.get("final_deck")
    if not isinstance(raw, list):
        return ()
    result: list[_DeckCard] = []
    for item in raw:
        if isinstance(item, str):
            card_id = item.strip().upper()
            if card_id:
                result.append(_DeckCard(card_id=card_id))
            continue
        if not isinstance(item, Mapping):
            continue
        card_id = str(item.get("card_id") or "").strip().upper()
        if not card_id:
            continue
        name = item.get("name")
        result.append(_DeckCard(
            card_id=card_id,
            name=str(name) if name not in (None, "") else None,
            upgraded=bool(item.get("upgraded")),
        ))
    return tuple(result)


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
    human_assisted: bool
    excluded_from_learning: bool
    floor: int | None
    decisions: int
    game_over: bool
    phantom: bool
    storage_kind: str | None = None
    card_picks: tuple[str, ...] = ()
    card_evidence: bool = False
    final_deck: tuple[_DeckCard, ...] = ()
    final_deck_evidence: bool = False

    @property
    def identity(self) -> str:
        return f"run:{self.run_id}" if self.run_id else f"file:{self.file}"

    @property
    def complete(self) -> bool:
        # ``in_progress`` is the durable commit boundary.  A GAME_OVER row (or
        # even a victory bit) can be written before the terminal payload and
        # profile aggregates are committed, so neither may promote a half-written
        # run into completed statistics.
        return not self.in_progress

    @property
    def excluded_from_statistics(self) -> bool:
        """Whether durable run metadata excludes this run from all aggregates."""
        return self.human_assisted or self.excluded_from_learning

    @property
    def statistical_completion(self) -> bool:
        """A terminal run that is eligible for autonomous floor statistics."""
        return (not self.in_progress and self.complete
                and not self.excluded_from_statistics)

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
                 trend_window: int = 40, rolling_window: int = 5,
                 profile_id: str = "ironclad", _discover_profiles: bool = True):
        self.root = Path(knowledge_dir)
        self.profile_id = _profile_id(profile_id)
        if self.profile_id not in PROFILE_IDS:
            raise ValueError(f"unsupported floor statistics profile: {profile_id!r}")
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
        self._card_evidence_errors: list[str] = []
        self._active: dict[Path, tuple[tuple[int, int], _RunRecord]] = {}
        self._invalid_active: set[Path] = set()
        self._live_run_id: object | str | None = _UNSET
        self._base: dict[str, Any] | None = None
        self._last_errors: tuple[str, ...] = ()
        self._profile_providers: dict[str, FloorStatsProvider] = {}
        if _discover_profiles and self.profile_id == "ironclad":
            self._profile_providers["vivhite"] = FloorStatsProvider(
                self.root / "profiles" / "vivhite",
                refresh_interval=self.refresh_interval,
                recent_window=self.recent_window,
                comparison_window=self.comparison_window,
                trend_window=self.trend_window,
                rolling_window=self.rolling_window,
                profile_id="vivhite",
                _discover_profiles=False,
            )

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

    def _runtime_dir(self) -> Path | None:
        """Resolve the stack runtime adjacent to this profile's knowledge root."""
        for candidate in (self.root, *self.root.parents):
            if candidate.name.casefold() == "knowledge":
                return candidate.parent / ".runtime"
        return None

    def _read_fresh_live_run_id(self) -> str | None:
        """Return the authoritative run id from this stack's fresh live session.

        A durable ``in_progress`` log may legitimately outlive the process that
        wrote it and later be resumed after a crash.  Therefore age alone never
        retires it.  We only have contrary evidence when the currently running
        session's own, still-fresh dashboard explicitly reports another run.
        """
        runtime_dir = self._runtime_dir()
        if runtime_dir is None:
            return None
        try:
            session = self._load_object(runtime_dir / "session.json")
            if str(session.get("state") or "").strip().casefold() != "running":
                return None
            session_id = str(session.get("session_id") or "").strip()
            if not session_id:
                return None
            live_path = runtime_dir / f"live_dashboard.{session_id}.json"
            live_stat = live_path.stat()
            if max(0.0, time.time() - live_stat.st_mtime) > _LIVE_DASHBOARD_FRESH_SEC:
                return None
            live = self._load_object(live_path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return None
        if (live.get("schema") != _LIVE_DASHBOARD_SCHEMA
                or str(live.get("session_id") or "").strip() != session_id):
            return None
        run = live.get("run")
        if not isinstance(run, Mapping):
            return None
        run_id = str(run.get("run_id") or "").strip()
        return run_id or None

    def _refresh_live_run_id(self) -> bool:
        run_id = self._read_fresh_live_run_id()
        if run_id == self._live_run_id:
            return False
        self._live_run_id = run_id
        return True

    def _catalog_row_with_recovered_identity(
            self, row: dict[str, Any]) -> dict[str, Any]:
        """Hydrate identity from legacy ZIP evidence before Ironclad fallback."""
        if _explicit_historical_profile_id(row) is not None:
            return row
        storage = row.get("storage") if isinstance(row.get("storage"), dict) else {}
        if storage.get("kind") != "zip":
            return row
        try:
            try:
                from compact_knowledge import read_catalog_storage_evidence
            except ImportError:  # pragma: no cover - package import fallback
                from .compact_knowledge import read_catalog_storage_evidence
            raw = read_catalog_storage_evidence(self.root, row)
            archived = json.loads(raw.decode("utf-8"))
        except (ImportError, OSError, UnicodeError, json.JSONDecodeError,
                RuntimeError, ValueError) as exc:
            raise ValueError(
                f"cannot recover archived profile identity for {row.get('file')}: {exc}"
            ) from exc
        if not isinstance(archived, dict):
            raise ValueError("archived run root is not an object")
        recovered = dict(row)
        for key in ("profile_id", "character_id"):
            if _profile_id(archived.get(key)) is not None:
                recovered[key] = archived[key]
        return recovered

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
        return _RunRecord(
            file=path.name,
            source="active",
            run_id=str(run_id) if run_id not in (None, "") else None,
            run_number=_integer(data.get("run_number")),
            started_at=(str(data.get("started_at"))
                        if data.get("started_at") not in (None, "") else None),
            profile_id=_historical_profile_id(data),
            ascension=_integer(data.get("ascension")),
            victory=victory,
            in_progress=bool(data.get("in_progress")),
            human_assisted=bool(data.get("human_assisted")),
            excluded_from_learning=bool(data.get("excluded_from_learning")),
            floor=max(valid_floors) if valid_floors else None,
            decisions=len(decisions),
            game_over=bool(game_over_rows),
            phantom=not decisions and not victory,
            storage_kind="active",
            card_picks=_card_picks(data),
            card_evidence=_has_card_pick_evidence(data),
            final_deck=_final_deck(data),
            final_deck_evidence=isinstance(data.get("final_deck"), list),
        )

    @staticmethod
    def _catalog_record(
            row: dict[str, Any], *, card_picks: tuple[str, ...] = (),
            card_evidence: bool = False,
            final_deck: tuple[_DeckCard, ...] = (),
            final_deck_evidence: bool = False) -> _RunRecord | None:
        filename = row.get("file")
        if not isinstance(filename, str) or not filename:
            return None  # schema/description header
        run_id = row.get("run_id")
        decisions = max(0, _integer(row.get("decisions")) or 0)
        victory = bool(row.get("victory"))
        storage = row.get("storage") if isinstance(row.get("storage"), dict) else {}
        return _RunRecord(
            file=filename,
            source="catalog",
            run_id=str(run_id) if run_id not in (None, "") else None,
            run_number=_integer(row.get("run_number")),
            started_at=(str(row.get("started_at"))
                        if row.get("started_at") not in (None, "") else None),
            profile_id=_historical_profile_id(row),
            ascension=_integer(row.get("ascension")),
            victory=victory,
            in_progress=bool(row.get("in_progress")),
            human_assisted=bool(row.get("human_assisted")),
            excluded_from_learning=bool(row.get("excluded_from_learning")),
            floor=_floor(row.get("floor")),
            decisions=decisions,
            game_over=str(row.get("last_screen") or "") == "GAME_OVER",
            phantom=bool(row.get("phantom_candidate")) or (not decisions and not victory),
            storage_kind=(str(storage.get("kind")) if storage.get("kind") else None),
            card_picks=card_picks,
            card_evidence=card_evidence,
            final_deck=final_deck,
            final_deck_evidence=final_deck_evidence,
        )

    def _catalog_run_evidence(
            self, row: dict[str, Any], archives: dict[Path, zipfile.ZipFile]
    ) -> tuple[tuple[str, ...], bool, tuple[_DeckCard, ...], bool]:
        """Hydrate optional choices/final deck from exact archived evidence.

        Empty explicit arrays are evidence. Missing fields remain missing even
        after compaction; they are never synthesized from another field.
        """
        picks: tuple[str, ...] = ()
        has_card_evidence = False
        if "card_picks" in row:
            raw_picks = row.get("card_picks")
            if not isinstance(raw_picks, list):
                raise ValueError("catalog card_picks must be a list")
            picks = _card_picks({
                "attribution_tags": [["card_pick", value] for value in raw_picks]
            })
            has_card_evidence = True

        deck: tuple[_DeckCard, ...] = ()
        has_final_deck_evidence = False
        if "final_deck" in row:
            if not isinstance(row.get("final_deck"), list):
                raise ValueError("catalog final_deck must be a list")
            deck = _final_deck(row)
            has_final_deck_evidence = True

        storage = row.get("storage") if isinstance(row.get("storage"), dict) else {}
        if storage.get("kind") != "zip":
            return picks, has_card_evidence, deck, has_final_deck_evidence
        archive_rel = PurePosixPath(str(storage.get("archive") or ""))
        member = PurePosixPath(str(storage.get("member") or ""))
        if (not archive_rel.parts or archive_rel.is_absolute()
                or ".." in archive_rel.parts or not member.parts
                or member.is_absolute() or ".." in member.parts):
            raise ValueError("invalid archived run-evidence path")
        root = self.root.resolve()
        archive_path = root.joinpath(*archive_rel.parts).resolve()
        try:
            archive_path.relative_to(root)
        except ValueError as exc:
            raise ValueError("archived run evidence escapes profile root") from exc
        archive = archives.get(archive_path)
        if archive is None:
            archive = zipfile.ZipFile(archive_path, "r")
            archives[archive_path] = archive
        raw = archive.read(member.as_posix())
        expected_size = _integer(row.get("bytes"))
        if expected_size is not None and len(raw) != expected_size:
            raise ValueError("archived run evidence size mismatch")
        expected_hash = str(row.get("sha256") or "").strip().casefold()
        if expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ValueError("archived run evidence SHA256 mismatch")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("archived run root is not an object")
        if not has_card_evidence and _has_card_pick_evidence(data):
            picks = _card_picks(data)
            has_card_evidence = True
        if (not has_final_deck_evidence
                and isinstance(data.get("final_deck"), list)):
            deck = _final_deck(data)
            has_final_deck_evidence = True
        return picks, has_card_evidence, deck, has_final_deck_evidence

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
        archives: dict[Path, zipfile.ZipFile] = {}
        evidence_errors: list[str] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            saw_header = False
            for line_number, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"line {line_number} is not an object")
                if saw_header:
                    row = self._catalog_row_with_recovered_identity(row)
                if not saw_header:
                    if row.get("schema_version") != 1:
                        raise ValueError("missing or unsupported catalog header")
                    saw_header = True
                    continue
                try:
                    picks, has_card_evidence, deck, has_deck_evidence = (
                        self._catalog_run_evidence(row, archives))
                except (OSError, UnicodeError, zipfile.BadZipFile, KeyError,
                        json.JSONDecodeError, ValueError) as exc:
                    evidence_errors.append(
                        f"{row.get('file') or f'catalog line {line_number}'}: "
                        f"run evidence: {exc}")
                    picks, has_card_evidence = (), False
                    deck, has_deck_evidence = (), False
                record = self._catalog_record(
                    row, card_picks=picks, card_evidence=has_card_evidence,
                    final_deck=deck,
                    final_deck_evidence=has_deck_evidence)
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
        finally:
            for archive in archives.values():
                archive.close()
        self._catalog_sig = signature
        self._catalog = records
        self._catalog_invalid = invalid
        self._card_evidence_errors = evidence_errors[:8]
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
        preferred = left if left_key >= right_key else right
        return FloorStatsProvider._preserve_exclusion(preferred, left, right)

    @staticmethod
    def _preserve_exclusion(
            preferred: _RunRecord, *evidence: _RunRecord) -> _RunRecord:
        """Make exclusions sticky and retain independent evidence channels."""
        human_assisted = preferred.human_assisted or any(
            record.human_assisted for record in evidence)
        excluded_from_learning = preferred.excluded_from_learning or any(
            record.excluded_from_learning for record in evidence)
        card_source = preferred
        if not preferred.card_evidence:
            # Never transplant evidence from a half-written duplicate onto a
            # completed preferred record: that would reintroduce its card picks
            # through duplicate merging even though its floor was filtered out.
            candidates = [
                record for record in evidence
                if record.card_evidence and not record.in_progress
            ]
            if candidates:
                card_source = max(candidates, key=lambda record: (
                    record.sort_key, record.decisions, len(record.card_picks)))
        deck_source = preferred
        if not preferred.final_deck_evidence:
            candidates = [record for record in evidence
                          if (record.final_deck_evidence
                              and not record.in_progress)]
            if candidates:
                deck_source = max(candidates, key=lambda record: (
                    record.sort_key, record.decisions, len(record.final_deck)))
        if (human_assisted == preferred.human_assisted
                and excluded_from_learning == preferred.excluded_from_learning
                and card_source is preferred and deck_source is preferred):
            return preferred
        return replace(
            preferred,
            human_assisted=human_assisted,
            excluded_from_learning=excluded_from_learning,
            card_picks=card_source.card_picks,
            card_evidence=card_source.card_evidence,
            final_deck=deck_source.final_deck,
            final_deck_evidence=deck_source.final_deck_evidence,
        )

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
                    catalog[identity] = self._preserve_exclusion(
                        previous, previous, record)
                    continue
                if (record.floor is None and previous.floor is not None
                        and not previous.phantom):
                    # Valid JSON can still contain an entirely unusable floor.
                    # Active precedence must not erase cleaner persisted evidence.
                    catalog[identity] = self._preserve_exclusion(
                        previous, previous, record)
                    continue
                record = self._preserve_exclusion(record, previous, record)
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
            if raw_sum is None and self.profile_id == "ironclad":
                outcome_sum = _number(global_stats.get("floors_total"))
                if outcome_sum is not None:
                    raw_sum = max(0.0, outcome_sum - 50.0 * wins)
                    source = "aggregate_legacy"
            if raw_sum is not None and raw_sum >= 0:
                raw_best = _floor(global_stats.get("best_floor_raw"))
                if raw_best is None and self.profile_id == "ironclad":
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
                if raw_best is not None:
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

    @staticmethod
    def _card_choice_view(completed: list[_RunRecord]) -> dict[str, Any]:
        """Aggregate filtered per-run choices without cross-profile backfill."""
        evidence = [record for record in completed if record.card_evidence]
        rows: dict[str, dict[str, Any]] = {}
        total_picks = 0
        runs_with_picks = 0
        for record in evidence:
            counts = Counter(record.card_picks)
            if counts:
                runs_with_picks += 1
            total_picks += sum(counts.values())
            for card_id, count in counts.items():
                row = rows.setdefault(card_id, {
                    "card_id": card_id,
                    "name": (_VIVHITE_CARDS[card_id].name_zh
                             if card_id in _VIVHITE_CARDS else card_id),
                    "picked": 0,
                    "run_count": 0,
                    "wins": 0,
                    "floor_sum": 0.0,
                    "floor_count": 0,
                    "best_floor": None,
                })
                row["picked"] += count
                row["run_count"] += 1
                row["wins"] += 1 if record.victory else 0
                if record.floor is not None:
                    row["floor_sum"] += record.floor
                    row["floor_count"] += 1
                    row["best_floor"] = max(
                        record.floor, row["best_floor"] or record.floor)

        cards: dict[str, dict[str, Any]] = {}
        for card_id, raw in rows.items():
            run_count = int(raw["run_count"])
            floor_count = int(raw["floor_count"])
            cards[card_id] = {
                "card_id": card_id,
                "name": raw["name"],
                "picked": int(raw["picked"]),
                "run_count": run_count,
                "run_rate": (run_count / len(evidence)) if evidence else None,
                "pick_share": (int(raw["picked"]) / total_picks) if total_picks else None,
                "wins": int(raw["wins"]),
                "win_rate": (int(raw["wins"]) / run_count) if run_count else None,
                "mean_floor": (float(raw["floor_sum"]) / floor_count
                               if floor_count else None),
                "best_floor": raw["best_floor"],
            }
        ordered = sorted(
            cards.values(),
            key=lambda row: (-row["picked"], -row["run_count"], row["card_id"]),
        )
        return {
            "source": "filtered_run_attribution_tags",
            "eligible_runs": len(completed),
            "evidence_runs": len(evidence),
            "missing_evidence_runs": len(completed) - len(evidence),
            "runs_with_picks": runs_with_picks,
            "total_picks": total_picks,
            "unique_cards": len(cards),
            "top_cards": ordered[:5],
            "cards": {row["card_id"]: row for row in ordered},
        }

    @staticmethod
    def _vivhite_build_pattern(card_ids) -> str:
        """Classify a real terminal deck by system presence, never by shares."""
        systems = {_vivhite_system(card_id) for card_id in card_ids}
        primary = systems.intersection(_VIVHITE_PRIMARY_SYSTEMS)
        if len(primary) == 1:
            return next(iter(primary))
        if len(primary) > 1:
            return MIXED_BUILD
        # bridge_only really means there is no primary or foreign card.
        # Starter/basic cards are neutral and do not prevent that classification.
        if FOREIGN_SYSTEM in systems:
            return FOREIGN_BUILD
        if BRIDGE_SYSTEM in systems:
            return BRIDGE_ONLY_BUILD
        return UNCLASSIFIED_BUILD

    @classmethod
    def _selection_system_distribution(
            cls, profile: str, completed: list[_RunRecord]) -> dict[str, Any]:
        """Describe card-pick systems only; this is never a final-build proxy."""
        if profile != "vivhite":
            return {
                "supported": False,
                "source": "no_approved_ironclad_selection_system_catalog",
                "eligible_runs": len(completed),
                "evidence_runs": sum(record.card_evidence for record in completed),
                "missing_evidence_runs": sum(
                    not record.card_evidence for record in completed),
                "total_card_picks": sum(
                    len(record.card_picks) for record in completed
                    if record.card_evidence),
                "categories": {},
            }
        evidence = [record for record in completed if record.card_evidence]
        raw_categories = {
            system: {"card_picks": 0, "run_count": 0}
            for system in VIVHITE_SELECTION_SYSTEM_ORDER
        }
        for record in evidence:
            counts = Counter(_vivhite_system(card_id)
                             for card_id in record.card_picks)
            for system, count in counts.items():
                raw_categories[system]["card_picks"] += count
                raw_categories[system]["run_count"] += 1
        total_picks = sum(
            int(row["card_picks"]) for row in raw_categories.values())
        categories = {
            system: {
                "system_id": system,
                "label": VIVHITE_SELECTION_SYSTEM_LABELS[system],
                "catalog_cards": int(VIVHITE_CATALOG_SYSTEM_COUNTS.get(system, 0)),
                "card_picks": int(raw_categories[system]["card_picks"]),
                "share": (int(raw_categories[system]["card_picks"]) / total_picks
                          if total_picks else None),
                "run_count": int(raw_categories[system]["run_count"]),
            }
            for system in VIVHITE_SELECTION_SYSTEM_ORDER
        }
        return {
            "supported": True,
            "source": "filtered_run_attribution_tags",
            "classification": "card_pick_counts_only",
            "eligible_runs": len(completed),
            "evidence_runs": len(evidence),
            "missing_evidence_runs": len(completed) - len(evidence),
            "total_card_picks": total_picks,
            "catalog_card_counts": dict(VIVHITE_CATALOG_SYSTEM_COUNTS),
            "category_order": list(VIVHITE_SELECTION_SYSTEM_ORDER),
            "categories": categories,
        }

    @staticmethod
    def _final_deck_view(completed: list[_RunRecord]) -> dict[str, Any]:
        """Summarize explicit terminal deck evidence without archetype inference."""
        evidence = [record for record in completed if record.final_deck_evidence]
        rows: dict[str, dict[str, Any]] = {}
        total_copies = 0
        upgraded_copies = 0
        for record in evidence:
            counts = Counter(card.card_id for card in record.final_deck)
            upgrades = Counter(card.card_id for card in record.final_deck
                               if card.upgraded)
            names = {card.card_id: card.name for card in record.final_deck
                     if card.name}
            total_copies += len(record.final_deck)
            upgraded_copies += sum(upgrades.values())
            for card_id, count in counts.items():
                row = rows.setdefault(card_id, {
                    "card_id": card_id,
                    "name": (_VIVHITE_CARDS[card_id].name_zh
                             if card_id in _VIVHITE_CARDS
                             else names.get(card_id) or card_id),
                    "copies": 0,
                    "deck_count": 0,
                    "upgraded_copies": 0,
                })
                row["copies"] += count
                row["deck_count"] += 1
                row["upgraded_copies"] += upgrades[card_id]
        ordered = sorted(rows.values(), key=lambda row: (
            -row["copies"], -row["deck_count"], row["card_id"]))
        return {
            "source": "filtered_terminal_final_deck",
            "eligible_runs": len(completed),
            "evidence_runs": len(evidence),
            "missing_evidence_runs": len(completed) - len(evidence),
            "total_card_copies": total_copies,
            "upgraded_copies": upgraded_copies,
            "unique_cards": len(rows),
            "top_cards": ordered[:5],
            "cards": {row["card_id"]: row for row in ordered},
        }

    @classmethod
    def _build_distribution(
            cls, profile: str, completed: list[_RunRecord]) -> dict[str, Any]:
        evidence = [record for record in completed if record.final_deck_evidence]
        if profile != "vivhite":
            return {
                "supported": False,
                "source": "no_approved_ironclad_archetype_catalog",
                "eligible_runs": len(completed),
                "evidence_runs": len(evidence),
                "missing_evidence_runs": len(completed) - len(evidence),
                "classified_runs": 0,
                "unclassified_runs": None,
                "categories": {},
            }
        raw_categories = {
            build: {"runs": 0, "wins": 0, "floors": [], "card_copies": 0}
            for build in VIVHITE_BUILD_ORDER
        }
        raw_composition = {
            system: {"card_copies": 0, "run_count": 0}
            for system in VIVHITE_SELECTION_SYSTEM_ORDER
        }
        unclassified_with_evidence = 0
        for record in completed:
            if record.final_deck_evidence:
                system_counts = Counter(
                    _vivhite_system(card.card_id) for card in record.final_deck)
                for system, count in system_counts.items():
                    raw_composition[system]["card_copies"] += count
                    raw_composition[system]["run_count"] += 1
                build = cls._vivhite_build_pattern(
                    card.card_id for card in record.final_deck)
                if build == UNCLASSIFIED_BUILD:
                    unclassified_with_evidence += 1
            else:
                # Missing final_deck is deliberately not backfilled from card_pick.
                build = UNCLASSIFIED_BUILD
            row = raw_categories[build]
            row["runs"] += 1
            row["wins"] += 1 if record.victory else 0
            if record.final_deck_evidence:
                row["card_copies"] += len(record.final_deck)
            if record.floor is not None:
                row["floors"].append(record.floor)
        eligible = len(completed)
        unclassified = int(raw_categories[UNCLASSIFIED_BUILD]["runs"])
        classified = eligible - unclassified
        categories: dict[str, dict[str, Any]] = {}
        for build in VIVHITE_BUILD_ORDER:
            raw = raw_categories[build]
            runs = int(raw["runs"])
            floors = list(raw["floors"])
            categories[build] = {
                "build_id": build,
                "label": VIVHITE_BUILD_LABELS[build],
                "runs": runs,
                "share": (runs / eligible) if eligible else None,
                "classified_share": (
                    runs / classified
                    if classified and build != UNCLASSIFIED_BUILD else None),
                "wins": int(raw["wins"]),
                "win_rate": (int(raw["wins"]) / runs) if runs else None,
                "mean_floor": (sum(floors) / len(floors)) if floors else None,
                "best_floor": max(floors, default=None),
                "card_copies": int(raw["card_copies"]),
            }
        composition = {
            system: {
                "system_id": system,
                "label": VIVHITE_SELECTION_SYSTEM_LABELS[system],
                "catalog_cards": int(VIVHITE_CATALOG_SYSTEM_COUNTS.get(system, 0)),
                "card_copies": int(raw_composition[system]["card_copies"]),
                "run_count": int(raw_composition[system]["run_count"]),
            }
            for system in VIVHITE_SELECTION_SYSTEM_ORDER
        }
        return {
            "supported": True,
            "source": "filtered_terminal_final_deck",
            "classification": "primary_presence_no_share_threshold",
            "eligible_runs": eligible,
            "evidence_runs": len(evidence),
            "missing_evidence_runs": eligible - len(evidence),
            "classified_runs": classified,
            "unclassified_runs": unclassified,
            "unclassified_with_evidence_runs": unclassified_with_evidence,
            "catalog_card_counts": dict(VIVHITE_CATALOG_SYSTEM_COUNTS),
            "category_order": list(VIVHITE_BUILD_ORDER),
            "categories": categories,
            "composition_order": list(VIVHITE_SELECTION_SYSTEM_ORDER),
            "composition": composition,
            "foreign_card_runs": int(
                raw_composition[FOREIGN_SYSTEM]["run_count"]),
        }

    def _profile_view(
            self, profile: str, completed: list[_RunRecord],
            excluded_from_statistics: int = 0) -> dict[str, Any]:
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
        if profile == self.profile_id:
            lifetime, source = self._lifetime(completed)
        else:
            lifetime, source = self._records_lifetime(completed)
        # The completed population is already strict at the durable
        # ``in_progress`` boundary.  Reuse exactly that population for card and
        # build views so every profile surface has the same eligibility rules.
        card_completed = completed
        card_choices = self._card_choice_view(card_completed)
        card_choices["errors"] = (
            list(self._card_evidence_errors) if profile == self.profile_id else [])
        selection_systems = self._selection_system_distribution(
            profile, card_completed)
        final_deck_evidence = self._final_deck_view(card_completed)
        final_deck_evidence["errors"] = (
            list(self._card_evidence_errors) if profile == self.profile_id else [])
        return {
            "profile_id": profile,
            "character_id": PROFILE_CHARACTER_IDS[profile],
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
            "card_choices": card_choices,
            "selection_system_distribution": selection_systems,
            "final_deck_evidence": final_deck_evidence,
            "build_distribution": self._build_distribution(
                profile, card_completed),
            "quality": {
                "source": source,
                "completed_records": len(completed),
                "excluded_from_statistics": excluded_from_statistics,
            },
        }

    def _build(self, errors: list[str]) -> dict[str, Any]:
        records, duplicates = self._merged_records()
        completed = sorted(
            (record for record in records
             if (record.statistical_completion and not record.phantom
                 and record.floor is not None)),
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
             if (record.in_progress and not record.phantom
                  and not record.excluded_from_statistics
                  and (not isinstance(self._live_run_id, str)
                       or record.run_id == self._live_run_id))),
            key=lambda record: record.sort_key,
        )
        current = self._current_from_record(auto_current[-1]) if auto_current else None
        lifetime, source = self._lifetime(completed)
        profile_records = {profile: [] for profile in PROFILE_IDS}
        profile_excluded = {profile: 0 for profile in PROFILE_IDS}
        for record in records:
            profile = record.profile_id or "ironclad"
            if (profile in profile_excluded and record.excluded_from_statistics
                    and not record.phantom):
                profile_excluded[profile] += 1
        for record in completed:
            # Untagged history is Ironclad even inside a Vivhite profile store.
            profile = record.profile_id or "ironclad"
            if profile in profile_records:
                profile_records[profile].append(record)
        profiles = {
            profile: self._profile_view(
                profile, profile_records[profile], profile_excluded[profile])
            for profile in PROFILE_IDS
        }
        for profile, provider in self._profile_providers.items():
            child_snapshot = provider.snapshot()
            child_profile = (child_snapshot.get("profiles") or {}).get(profile)
            if not isinstance(child_profile, dict):
                continue
            child_profile = copy.deepcopy(child_profile)
            child_lifetime = (child_profile.get("lifetime")
                              if isinstance(child_profile.get("lifetime"), dict) else {})
            child_quality = (child_profile.get("quality")
                             if isinstance(child_profile.get("quality"), dict) else {})
            child_errors = list(
                (child_snapshot.get("quality") or {}).get("errors") or [])
            child_stale = bool(child_snapshot.get("stale"))
            child_profile.setdefault("quality", {})["stale"] = child_stale
            child_profile["quality"]["errors"] = child_errors
            # A clean, brand-new profile store is known to contain zero runs.
            # Missing averages/maxima remain None so the viewer renders N/A.
            # A stale or malformed store remains unavailable instead of
            # inventing a zero that could hide evidence loss.
            if (child_lifetime.get("runs") is None
                    and not child_quality.get("completed_records")
                    and not child_stale and not child_errors):
                child_lifetime["runs"] = 0
                child_lifetime["wins"] = 0
                child_lifetime["win_rate"] = None
            child_profile["lifetime"] = child_lifetime
            # The nested profile is authoritative even when it is empty.  Root
            # logs are legacy Ironclad data and must never backfill Vivhite.
            profiles[profile] = child_profile
            child_current = child_snapshot.get("current")
            if (current is None and isinstance(child_current, dict)
                    and child_current.get("profile_id") == profile):
                current = copy.deepcopy(child_current)
        rolling_means = {
            profile: profiles[profile]["rolling_mean"] for profile in PROFILE_IDS
        }
        ironclad_mean = rolling_means["ironclad"]
        vivhite_mean = rolling_means["vivhite"]
        rolling_samples_complete = all(
            _integer((profiles[profile].get("recent") or {}).get("count"))
            == self.rolling_window
            for profile in PROFILE_IDS
        )
        rolling_ratio = (
            vivhite_mean / ironclad_mean
            if (rolling_samples_complete
                and vivhite_mean is not None and ironclad_mean is not None
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
            "active_profile": ((current.get("profile_id") or self.profile_id)
                               if current is not None else None),
            "profiles": profiles,
            "profile_comparison": {
                "rolling_window": self.rolling_window,
                "rolling_means": rolling_means,
                "rolling_mean_ratio": rolling_ratio,
                "vivhite_to_ironclad_ratio": rolling_ratio,
                "ratio_numerator": "vivhite",
                "ratio_denominator": "ironclad",
            },
            "quality": {
                "source": source,
                "catalog_records": len(self._catalog),
                "active_records": len(self._active),
                "completed_records": len(completed),
                "excluded_in_progress": sum(
                    1 for record in records
                    if (record.in_progress and not record.phantom
                        and not record.excluded_from_statistics)),
                "excluded_from_statistics": sum(
                    1 for record in records
                    if record.excluded_from_statistics and not record.phantom),
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
        profile = _profile_id(
            current.get("character_profile", current.get("profile_id", character)))
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
            changed |= self._refresh_live_run_id()
            changed |= self._refresh_json(
                self.root / "stats.json", "_stats_sig", "_stats", errors)
            changed |= self._refresh_json(
                self.root / "progression.json", "_progression_sig", "_progression", errors)
            changed |= self._refresh_catalog(errors)
            changed |= self._refresh_active(errors)
            for provider in self._profile_providers.values():
                changed |= provider.refresh(force=force)
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
                    result["current"].get("profile_id") or self.profile_id)
            active_profile = result.get("active_profile") or self.profile_id
            profile_view = (result.get("profiles") or {}).get(active_profile)
            if isinstance(profile_view, dict):
                # Top-level keys are the compatibility contract consumed by the
                # existing viewer.  They must describe the active profile, not
                # whichever provider happens to own the legacy knowledge root.
                for key in ("lifetime", "recent", "previous", "delta_mean", "trend",
                            "card_choices", "selection_system_distribution",
                            "final_deck_evidence", "build_distribution"):
                    if key in profile_view:
                        result[key] = copy.deepcopy(profile_view[key])
                result["active_profile"] = active_profile
                profile_quality = profile_view.get("quality")
                if isinstance(profile_quality, dict) and "stale" in profile_quality:
                    result["stale"] = bool(profile_quality.get("stale"))
            return result


__all__ = [
    "FloorStatsProvider",
    "PROFILE_IDS",
    "VIVHITE_BUILD_LABELS",
    "VIVHITE_BUILD_ORDER",
    "VIVHITE_CATALOG_SYSTEM_COUNTS",
    "VIVHITE_SELECTION_SYSTEM_LABELS",
    "VIVHITE_SELECTION_SYSTEM_ORDER",
]
