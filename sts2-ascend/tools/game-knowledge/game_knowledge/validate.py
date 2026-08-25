"""Completeness and provenance checks for a generated knowledge snapshot."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .extract import MANIFEST_SCHEMA, atomic_write_json
from .ids import model_entry_id
from .mechanics import MECHANICS_RECORD_SCHEMA
from .pck import PckReader, sha256_file
from .runtime import REQUIRED_COLLECTIONS, RUNTIME_RECORD_SCHEMA


@dataclass(slots=True)
class Check:
    name: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class ValidationError(RuntimeError):
    """Raised when a snapshot cannot even be parsed for validation."""


REQUIRED_DATA_FIELDS: dict[str, tuple[str, ...]] = {
    "cards": ("id", "name", "description", "type", "rarity", "target", "cost", "upgrade"),
    "relics": ("id", "name", "description", "rarity", "pool"),
    "monsters": ("id", "name", "type", "min_hp", "max_hp", "moves"),
    "potions": ("id", "name", "description", "rarity", "pool", "usage", "target_type"),
    "events": ("id", "name", "description", "type", "options"),
    "powers": ("id", "name", "description", "type", "stack_type"),
    "characters": (
        "id",
        "name",
        "starting_hp",
        "starting_gold",
        "max_energy",
        "starting_deck",
        "starting_relics",
        "starting_potions",
    ),
}


def _safe_artifact_path(output_dir: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValidationError(f"Invalid artifact path: {relative!r}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise ValidationError(f"Unsafe artifact path: {relative!r}")
    path = (output_dir / Path(*pure.parts)).resolve()
    try:
        path.relative_to(output_dir)
    except ValueError as exc:
        raise ValidationError(f"Artifact escapes output directory: {relative!r}") from exc
    return path


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValidationError(f"{path}:{line_number} is not a JSON object")
                records.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot parse JSONL {path}: {exc}") from exc
    return records


def _check_artifacts(output_dir: Path, manifest: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return [Check("artifacts.manifest", "fail", "manifest.artifacts is not an array")]
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            checks.append(Check("artifacts.entry", "fail", "Artifact entry is not an object"))
            continue
        relative = item.get("path")
        try:
            path = _safe_artifact_path(output_dir, relative)
        except ValidationError as exc:
            checks.append(Check("artifacts.path", "fail", str(exc)))
            continue
        if str(relative) in seen:
            checks.append(Check("artifacts.duplicate", "fail", f"Duplicate artifact: {relative}"))
            continue
        seen.add(str(relative))
        if not path.is_file():
            checks.append(Check("artifacts.exists", "fail", f"Missing artifact: {relative}"))
            continue
        actual_size = path.stat().st_size
        actual_hash = sha256_file(path)
        expected_size = item.get("size")
        expected_hash = item.get("sha256")
        if actual_size != expected_size or actual_hash != expected_hash:
            checks.append(
                Check(
                    "artifacts.integrity",
                    "fail",
                    f"Artifact integrity mismatch: {relative}",
                    {
                        "expected_size": expected_size,
                        "actual_size": actual_size,
                        "expected_sha256": expected_hash,
                        "actual_sha256": actual_hash,
                    },
                )
            )
            continue
        if "records" in item and path.suffix == ".jsonl":
            try:
                count = len(_load_jsonl(path))
            except ValidationError as exc:
                checks.append(Check("artifacts.jsonl", "fail", str(exc)))
                continue
            if count != item["records"]:
                checks.append(
                    Check(
                        "artifacts.records",
                        "fail",
                        f"JSONL record count mismatch: {relative}",
                        {"expected": item["records"], "actual": count},
                    )
                )
    if not any(check.status == "fail" for check in checks):
        checks.append(Check("artifacts.integrity", "pass", f"Verified {len(artifacts)} artifacts"))
    return checks


def _check_localization(manifest: dict[str, Any]) -> list[Check]:
    localization = manifest.get("localization")
    if not isinstance(localization, dict):
        return [Check("localization.manifest", "fail", "manifest.localization is missing")]
    locales = localization.get("locales")
    checks: list[Check] = []
    if not isinstance(locales, list) or not {"eng", "zhs"}.issubset(locales):
        checks.append(Check("localization.locales", "fail", "Both eng and zhs localization are required"))
    else:
        checks.append(Check("localization.locales", "pass", "English and Simplified Chinese are present"))
    file_sets = localization.get("file_sets", {})
    eng_files = set(file_sets.get("eng", [])) if isinstance(file_sets, dict) else set()
    zhs_files = set(file_sets.get("zhs", [])) if isinstance(file_sets, dict) else set()
    if eng_files != zhs_files:
        checks.append(
            Check(
                "localization.file_symmetry",
                "warning",
                "English and Chinese localization file sets differ",
                {"only_eng": sorted(eng_files - zhs_files), "only_zhs": sorted(zhs_files - eng_files)},
            )
        )
    else:
        checks.append(
            Check("localization.file_symmetry", "pass", f"Matched {len(eng_files)} bilingual files")
        )
    coverage = localization.get("eng_zhs_key_coverage", [])
    mismatches = [
        item
        for item in coverage
        if isinstance(item, dict) and (item.get("missing_in_zhs") or item.get("extra_in_zhs"))
    ]
    if mismatches:
        checks.append(
            Check(
                "localization.key_symmetry",
                "warning",
                f"{len(mismatches)} localization files have asymmetric key sets",
                {"files": [item.get("name") for item in mismatches]},
            )
        )
    else:
        checks.append(Check("localization.key_symmetry", "pass", "Bilingual key sets match"))
    return checks


def _runtime_records(output_dir: Path, runtime: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[Check]]:
    checks: list[Check] = []
    result: dict[str, list[dict[str, Any]]] = {}
    collections = runtime.get("collections", {})
    if not isinstance(collections, dict):
        return result, [Check("runtime.collections", "fail", "runtime.collections is not an object")]
    for collection, metadata in collections.items():
        if not isinstance(metadata, dict) or metadata.get("status") != "captured":
            continue
        try:
            path = _safe_artifact_path(output_dir, metadata.get("artifact"))
            records = _load_jsonl(path)
        except ValidationError as exc:
            checks.append(Check(f"runtime.{collection}.parse", "fail", str(exc)))
            continue
        ids: set[str] = set()
        missing_fields: Counter[str] = Counter()
        bad_envelopes = 0
        leaked_mods: list[str] = []
        for record in records:
            record_id = record.get("id")
            data = record.get("data")
            provenance = record.get("provenance", {})
            if (
                record.get("schema") != RUNTIME_RECORD_SCHEMA
                or record.get("category") != collection
                or not isinstance(record_id, str)
                or not isinstance(data, dict)
                or data.get("id") != record_id
            ):
                bad_envelopes += 1
                continue
            folded = record_id.casefold()
            if folded in ids:
                checks.append(
                    Check(f"runtime.{collection}.ids", "fail", f"Duplicate runtime id: {record_id}")
                )
            ids.add(folded)
            if isinstance(provenance, dict) and provenance.get("base_game_filter") == "mod":
                leaked_mods.append(record_id)
            for field_name in REQUIRED_DATA_FIELDS.get(collection, ()):
                if field_name not in data:
                    missing_fields[field_name] += 1
        if bad_envelopes:
            checks.append(
                Check(
                    f"runtime.{collection}.schema",
                    "fail",
                    f"{bad_envelopes} malformed runtime envelopes",
                )
            )
        elif missing_fields:
            checks.append(
                Check(
                    f"runtime.{collection}.fields",
                    "fail",
                    f"Runtime {collection} records are missing required fields",
                    {"missing_counts": dict(missing_fields)},
                )
            )
        elif leaked_mods:
            checks.append(
                Check(
                    f"runtime.{collection}.base_filter",
                    "fail",
                    f"Explicit mod records leaked into base snapshot: {leaked_mods}",
                )
            )
        else:
            checks.append(
                Check(f"runtime.{collection}.schema", "pass", f"Validated {len(records)} records")
            )
        result[collection] = records
    return result, checks


def _data_by_id(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(record["id"]).casefold(): record["data"]
        for record in records
        if isinstance(record.get("id"), str) and isinstance(record.get("data"), dict)
    }


def _check_references(records: dict[str, list[dict[str, Any]]]) -> list[Check]:
    if not all(name in records for name in ("characters", "cards", "relics", "potions")):
        return [Check("runtime.references", "warning", "Core collections unavailable for reference checks")]
    cards = _data_by_id(records["cards"])
    relics = _data_by_id(records["relics"])
    potions = _data_by_id(records["potions"])
    missing: list[dict[str, str]] = []
    for character_record in records["characters"]:
        character = character_record["data"]
        character_id = character_record["id"]
        for field_name, target in (
            ("starting_deck", cards),
            ("starting_relics", relics),
            ("starting_potions", potions),
        ):
            for target_id in character.get(field_name) or []:
                if str(target_id).casefold() not in target:
                    missing.append(
                        {"character": character_id, "field": field_name, "missing_id": str(target_id)}
                    )
    if missing:
        return [
            Check(
                "runtime.references.characters",
                "fail",
                f"{len(missing)} character starting-content references are unresolved",
                {"missing": missing},
            )
        ]
    return [Check("runtime.references.characters", "pass", "Character starting content is closed")]


def _check_runtime(output_dir: Path, manifest: dict[str, Any]) -> list[Check]:
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("status") == "not_captured":
        return [Check("runtime.capture", "warning", "Runtime ModelDb snapshot has not been captured")]
    checks: list[Check] = []
    collections = runtime.get("collections", {})
    missing_required = [
        name
        for name in REQUIRED_COLLECTIONS
        if not isinstance(collections, dict)
        or not isinstance(collections.get(name), dict)
        or collections[name].get("status") != "captured"
    ]
    if missing_required:
        checks.append(
            Check(
                "runtime.required_collections",
                "fail",
                f"Required runtime collections missing: {missing_required}",
            )
        )
    else:
        checks.append(Check("runtime.required_collections", "pass", "All core collections captured"))
    if runtime.get("base_game_filter") != "available":
        checks.append(
            Check(
                "runtime.base_game_filter",
                "warning",
                f"Base-game filtering is {runtime.get('base_game_filter')}",
            )
        )
    else:
        checks.append(Check("runtime.base_game_filter", "pass", "Base-game filtering is available"))
    records, record_checks = _runtime_records(output_dir, runtime)
    checks.extend(record_checks)
    checks.extend(_check_references(records))

    monsters = records.get("monsters", [])
    empty_moves = [record["id"] for record in monsters if not (record.get("data", {}).get("moves") or [])]
    if monsters and empty_moves:
        checks.append(
            Check(
                "runtime.monsters.moves",
                "warning",
                f"{len(empty_moves)}/{len(monsters)} monsters have no runtime move metadata; static mechanics are required",
                {"ids": empty_moves},
            )
        )
    return checks


def _check_mechanics(output_dir: Path, manifest: dict[str, Any]) -> list[Check]:
    mechanics = manifest.get("mechanics")
    if not isinstance(mechanics, dict) or mechanics.get("status") == "not_imported":
        return [Check("mechanics.import", "warning", "Static mechanics facts have not been imported")]
    checks: list[Check] = []
    assembly_hash = manifest.get("sources", {}).get("assembly", {}).get("sha256")
    mechanics_hash = mechanics.get("source", {}).get("assembly_sha256")
    if mechanics_hash != assembly_hash:
        checks.append(
            Check(
                "mechanics.source",
                "fail",
                "Mechanics and runtime resources came from different assemblies",
                {"snapshot": assembly_hash, "mechanics": mechanics_hash},
            )
        )
    else:
        checks.append(Check("mechanics.source", "pass", "Mechanics assembly hash matches"))

    artifacts = [
        item
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict) and str(item.get("path", "")).startswith("mechanics/")
    ]
    type_names: set[str] = set()
    ids: dict[str, set[str]] = {}
    record_count = 0
    malformed = 0
    for artifact in artifacts:
        try:
            path = _safe_artifact_path(output_dir, artifact.get("path"))
            records = _load_jsonl(path)
        except ValidationError as exc:
            checks.append(Check("mechanics.parse", "fail", str(exc)))
            continue
        category = path.stem
        for record in records:
            record_count += 1
            type_name = record.get("type_name")
            name = record.get("name")
            entry_id = record.get("entry_id")
            data = record.get("data")
            if (
                record.get("schema") != MECHANICS_RECORD_SCHEMA
                or record.get("category") != category
                or not isinstance(type_name, str)
                or not isinstance(name, str)
                or not isinstance(data, dict)
            ):
                malformed += 1
                continue
            is_nested = data.get("is_nested")
            declaring_type_name = data.get("declaring_type_name")
            expected_entry_id = (
                model_entry_id(name)
                if not is_nested
                and category != "model_bases"
                and type_name.startswith("MegaCrit.Sts2.Core.Models.")
                else None
            )
            arrays_are_valid = all(
                isinstance(data.get(field_name), list)
                for field_name in ("base_types", "fields", "properties", "constructors", "methods")
            )
            properties_are_valid = isinstance(data.get("properties"), list) and all(
                isinstance(property_fact, dict)
                and isinstance(property_fact.get("expressions"), list)
                and isinstance(property_fact.get("accessors"), list)
                for property_fact in data.get("properties", [])
            )
            behavior_arrays_are_valid = all(
                isinstance(fact, dict)
                and all(
                    isinstance(fact.get(field_name), list)
                    for field_name in (
                        "calls", "creates", "assignments", "conditions", "switches", "returns"
                    )
                )
                for fact in (
                    list(data.get("constructors", []))
                    + list(data.get("methods", []))
                    + [
                        accessor
                        for property_fact in data.get("properties", [])
                        for accessor in property_fact.get("accessors", [])
                    ]
                )
            ) if arrays_are_valid and properties_are_valid else False
            if (
                not isinstance(is_nested, bool)
                or (is_nested and not isinstance(declaring_type_name, str))
                or (not is_nested and declaring_type_name is not None)
                or entry_id != expected_entry_id
                or not arrays_are_valid
                or not properties_are_valid
                or not behavior_arrays_are_valid
            ):
                malformed += 1
                continue
            if type_name in type_names:
                checks.append(Check("mechanics.type_names", "fail", f"Duplicate type: {type_name}"))
            type_names.add(type_name)
            if entry_id is not None:
                folded = str(entry_id).casefold()
                category_ids = ids.setdefault(category, set())
                if folded in category_ids:
                    checks.append(
                        Check("mechanics.entry_id", "fail", f"Duplicate {category} ID: {entry_id}")
                    )
                category_ids.add(folded)
    if malformed:
        checks.append(
            Check("mechanics.schema", "fail", f"{malformed} malformed mechanics envelopes")
        )
    elif record_count != mechanics.get("record_count"):
        checks.append(
            Check(
                "mechanics.count",
                "fail",
                f"Mechanics record count is {record_count}, manifest says {mechanics.get('record_count')}",
            )
        )
    else:
        checks.append(Check("mechanics.schema", "pass", f"Validated {record_count} mechanics records"))

    extractor_failures = mechanics.get("extractor_failures", [])
    if extractor_failures:
        checks.append(
            Check(
                "mechanics.extractor_failures",
                "warning",
                f"Static extractor failed for {len(extractor_failures)} types",
            )
        )
    joins = mechanics.get("joins", {})
    partial = [
        category
        for category, detail in joins.items()
        if isinstance(detail, dict) and detail.get("status") == "partial"
    ] if isinstance(joins, dict) else []
    if partial:
        checks.append(
            Check(
                "mechanics.runtime_join",
                "warning",
                f"Runtime/mechanics ID join is partial for: {partial}",
            )
        )
    elif isinstance(joins, dict):
        checks.append(Check("mechanics.runtime_join", "pass", "All available runtime joins are complete"))
    return checks


def _check_sources(manifest: dict[str, Any], game_dir: Path | None) -> list[Check]:
    if game_dir is None:
        return [Check("sources.live", "pass", "Live source recheck skipped (no --game-dir)")]
    sources = manifest.get("sources", {})
    release_path = game_dir / "release_info.json"
    assembly_path = game_dir / "data_sts2_windows_x86_64" / "sts2.dll"
    pck_path = game_dir / "SlayTheSpire2.pck"
    missing = [str(path) for path in (release_path, assembly_path, pck_path) if not path.is_file()]
    if missing:
        return [Check("sources.live", "fail", "Installed source files are missing", {"paths": missing})]
    mismatches: dict[str, Any] = {}
    if sha256_file(release_path) != sources.get("release_info", {}).get("sha256"):
        mismatches["release_info"] = "sha256"
    if sha256_file(assembly_path) != sources.get("assembly", {}).get("sha256"):
        mismatches["assembly"] = "sha256"
    with PckReader(pck_path) as reader:
        if reader.directory_sha256() != sources.get("pck", {}).get("directory_sha256"):
            mismatches["pck"] = "directory_sha256"
        expected_full = sources.get("pck", {}).get("full_sha256")
        if expected_full and sha256_file(pck_path) != expected_full:
            mismatches["pck_full"] = "sha256"
    if mismatches:
        return [
            Check(
                "sources.live",
                "fail",
                "Installed game no longer matches the snapshot sources",
                mismatches,
            )
        ]
    return [Check("sources.live", "pass", "Installed source hashes match")]


def validate_snapshot(
    *, output_dir: str | Path, game_dir: str | Path | None = None, write_report: bool = True
) -> dict[str, Any]:
    output_dir = Path(output_dir).resolve()
    manifest_path = output_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot read snapshot manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValidationError("Snapshot manifest is not a JSON object")

    checks: list[Check] = []
    if manifest.get("schema") == MANIFEST_SCHEMA:
        checks.append(Check("manifest.schema", "pass", MANIFEST_SCHEMA))
    else:
        checks.append(
            Check(
                "manifest.schema",
                "fail",
                f"Expected {MANIFEST_SCHEMA}, got {manifest.get('schema')!r}",
            )
        )
    expected_dir_name = manifest.get("game", {}).get("version")
    if output_dir.name == expected_dir_name:
        checks.append(Check("manifest.version_directory", "pass", str(expected_dir_name)))
    else:
        checks.append(
            Check(
                "manifest.version_directory",
                "fail",
                f"Directory {output_dir.name!r} does not match game version {expected_dir_name!r}",
            )
        )
    checks.extend(_check_artifacts(output_dir, manifest))
    checks.extend(_check_localization(manifest))
    checks.extend(_check_runtime(output_dir, manifest))
    checks.extend(_check_mechanics(output_dir, manifest))
    checks.extend(_check_sources(manifest, Path(game_dir).resolve() if game_dir else None))

    counts = Counter(check.status for check in checks)
    overall = "fail" if counts["fail"] else "warning" if counts["warning"] else "pass"
    report = {
        "schema": "sts2.game-knowledge-validation/v1",
        "overall": overall,
        "counts": {status: counts[status] for status in ("pass", "warning", "fail")},
        "checks": [asdict(check) for check in checks],
    }
    if write_report:
        atomic_write_json(output_dir / "validation.json", report)
    return report
