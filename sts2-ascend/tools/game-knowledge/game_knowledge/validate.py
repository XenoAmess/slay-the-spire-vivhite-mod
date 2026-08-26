"""Completeness and provenance checks for a generated knowledge snapshot."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable

from .extract import LOCALIZATION_RECORD_SCHEMA, MANIFEST_SCHEMA, atomic_write_json
from .ids import model_entry_id
from .mechanics import MECHANICS_INPUT_SCHEMA_VERSION, MECHANICS_RECORD_SCHEMA
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

MECHANICS_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "mechanics-record.schema.json"
)
VALIDATION_SCHEMA = "sts2.game-knowledge-validation/v2"
VALIDATOR_VERSION = "game_knowledge.validate/v3"


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Cannot parse JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path} is not a JSON object")
    return value


def _artifact_set_sha256(output_dir: Path, manifest: dict[str, Any]) -> str:
    """Hash actual artifact contents plus their normalized paths and sizes."""
    digest = hashlib.sha256()
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValidationError("manifest.artifacts is not an array")
    rows: list[tuple[str, Path]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise ValidationError("Artifact entry is not an object")
        relative = item.get("path")
        path = _safe_artifact_path(output_dir, relative)
        if not path.is_file():
            raise ValidationError(f"Missing artifact: {relative}")
        rows.append((str(relative), path))
    for relative, path in sorted(rows):
        row = json.dumps({
            "path": relative,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest.update(row.encode("utf-8") + b"\n")
    return digest.hexdigest()


def _schema_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }.get(expected, True)


def _schema_errors(
    value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$",
) -> list[str]:
    """Validate the JSON-Schema subset used by our checked-in record schemas.

    Keeping this small validator in the standard-library tool avoids making a
    generated knowledge snapshot depend on an optional third-party package while
    still enforcing the actual schema file (including refs/allOf/nested objects).
    Unknown schema keywords fail closed so a future schema expansion cannot be
    silently accepted without validator support.
    """
    errors: list[str] = []
    supported = {
        "$schema", "$id", "$defs", "title", "description", "$ref", "allOf",
        "type", "const", "enum", "pattern", "minLength", "required",
        "properties", "additionalProperties", "items",
    }
    unknown = sorted(set(schema) - supported)
    if unknown:
        return [f"{path}: unsupported schema keywords {unknown}"]
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return [f"{path}: unsupported schema ref {ref!r}"]
        target: Any = root
        try:
            for part in ref[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            return [f"{path}: unresolved schema ref {ref!r}"]
        if not isinstance(target, dict):
            return [f"{path}: schema ref is not an object {ref!r}"]
        errors.extend(_schema_errors(value, target, root, path))
    for child in schema.get("allOf", []):
        if not isinstance(child, dict):
            errors.append(f"{path}: allOf entry is not an object")
        else:
            errors.extend(_schema_errors(value, child, root, path))
    expected_types = schema.get("type")
    if isinstance(expected_types, str):
        expected_types = [expected_types]
    if isinstance(expected_types, list) and not any(
            isinstance(item, str) and _schema_type_matches(value, item)
            for item in expected_types):
        errors.append(f"{path}: expected type {expected_types}, got {type(value).__name__}")
        return errors
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is outside enum")
    if isinstance(value, str):
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            errors.append(f"{path}: string is shorter than {schema['minLength']}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{path}: string does not match {pattern!r}")
    if isinstance(value, dict):
        required = schema.get("required", [])
        for name in required if isinstance(required, list) else []:
            if name not in value:
                errors.append(f"{path}: missing required property {name!r}")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for name, child in properties.items():
                if name in value and isinstance(child, dict):
                    errors.extend(_schema_errors(value[name], child, root, f"{path}.{name}"))
            if schema.get("additionalProperties") is False:
                for name in sorted(set(value) - set(properties)):
                    errors.append(f"{path}: unexpected property {name!r}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        child = schema["items"]
        for index, item in enumerate(value):
            errors.extend(_schema_errors(item, child, root, f"{path}[{index}]"))
    return errors


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


def _check_localization(output_dir: Path, manifest: dict[str, Any]) -> list[Check]:
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

    bilingual_artifact = localization.get("bilingual_artifact")
    if not isinstance(bilingual_artifact, str):
        checks.append(
            Check("localization.bilingual_catalog", "fail", "Bilingual localization catalog is missing")
        )
        return checks
    try:
        bilingual_records = _load_jsonl(_safe_artifact_path(output_dir, bilingual_artifact))
    except ValidationError as exc:
        checks.append(Check("localization.bilingual_catalog", "fail", str(exc)))
        return checks
    seen_keys: set[tuple[str, str]] = set()
    actual_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    status_counts: Counter[str] = Counter()
    malformed = 0
    for record in bilingual_records:
        filename = record.get("file")
        key = record.get("key")
        status = record.get("status")
        fallback_locale = record.get("fallback_locale")
        key_parts = key.split(".", 1) if isinstance(key, str) else []
        expected_model_id = key_parts[0] if key_parts else None
        expected_field = key_parts[1] if len(key_parts) == 2 else None
        expected_fallback = (
            record.get("zhs") if fallback_locale == "zhs" else record.get("eng")
        )
        if (
            record.get("schema") != LOCALIZATION_RECORD_SCHEMA
            or not isinstance(filename, str)
            or "/" in filename
            or "\\" in filename
            or not isinstance(key, str)
            or record.get("model_id") != expected_model_id
            or record.get("field") != expected_field
            or status not in {"bilingual", "missing_eng", "missing_zhs"}
            or fallback_locale not in {"eng", "zhs"}
            or (status == "missing_eng" and fallback_locale != "zhs")
            or (status == "missing_zhs" and fallback_locale != "eng")
            or (status == "bilingual" and fallback_locale != "zhs")
            or (status == "missing_eng" and record.get("eng") is not None)
            or (status == "missing_zhs" and record.get("zhs") is not None)
            or record.get("zhs_or_eng") != expected_fallback
        ):
            malformed += 1
            continue
        identity = (filename, key)
        if identity in seen_keys:
            malformed += 1
            continue
        seen_keys.add(identity)
        actual_by_key[identity] = record
        status_counts[status] += 1

    # Rebuild the catalog from the hashed official source files.  Comparing only
    # catalog counts to manifest counts is circular: a generator bug could omit a
    # whole key and update both numbers together.  This is the independent source
    # closure that proves every eng/zhs key and value is represented exactly once.
    expected_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    source_errors: list[str] = []
    for filename in sorted(eng_files | zhs_files):
        try:
            eng_values = _load_json_object(_safe_artifact_path(
                output_dir, f"localization/eng/{filename}")) \
                if filename in eng_files else {}
            zhs_values = _load_json_object(_safe_artifact_path(
                output_dir, f"localization/zhs/{filename}")) \
                if filename in zhs_files else {}
        except ValidationError as exc:
            source_errors.append(str(exc))
            continue
        for key in sorted(set(eng_values) | set(zhs_values)):
            has_eng = key in eng_values
            has_zhs = key in zhs_values
            status = "bilingual" if has_eng and has_zhs else "missing_zhs" if has_eng else "missing_eng"
            fallback_locale = "zhs" if has_zhs else "eng"
            key_parts = key.split(".", 1)
            expected_by_key[(filename, key)] = {
                "schema": LOCALIZATION_RECORD_SCHEMA,
                "file": filename,
                "key": key,
                "model_id": key_parts[0],
                "field": key_parts[1] if len(key_parts) == 2 else None,
                "eng": eng_values.get(key),
                "zhs": zhs_values.get(key),
                "status": status,
                "zhs_or_eng": zhs_values[key] if has_zhs else eng_values[key],
                "fallback_locale": fallback_locale,
            }
    missing_source_keys = sorted(set(expected_by_key) - set(actual_by_key))
    extra_catalog_keys = sorted(set(actual_by_key) - set(expected_by_key))
    value_mismatches = sorted(
        identity for identity in set(expected_by_key) & set(actual_by_key)
        if actual_by_key[identity] != expected_by_key[identity]
    )
    expected_count = localization.get("bilingual_records")
    expected_status_counts = localization.get("bilingual_status_counts")
    if (
        malformed
        or source_errors
        or missing_source_keys
        or extra_catalog_keys
        or value_mismatches
        or len(bilingual_records) != expected_count
        or dict(sorted(status_counts.items())) != expected_status_counts
    ):
        checks.append(
            Check(
                "localization.bilingual_catalog",
                "fail",
                "Bilingual localization catalog metadata is inconsistent",
                {
                    "malformed": malformed,
                    "actual_records": len(bilingual_records),
                    "expected_records": expected_count,
                    "actual_status_counts": dict(status_counts),
                    "expected_status_counts": expected_status_counts,
                    "source_errors": source_errors[:8],
                    "missing_source_keys": missing_source_keys[:20],
                    "extra_catalog_keys": extra_catalog_keys[:20],
                    "value_mismatches": value_mismatches[:20],
                },
            )
        )
    else:
        checks.append(
            Check(
                "localization.bilingual_catalog",
                "pass",
                f"Validated {len(bilingual_records)} bilingual localization records",
                {"status_counts": dict(status_counts)},
            )
        )
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
        mechanics = manifest.get("mechanics", {})
        if not isinstance(mechanics, dict) or not str(mechanics.get("status", "")).startswith("imported"):
            checks.append(
                Check(
                    "runtime.monsters.moves",
                    "warning",
                    f"{len(empty_moves)}/{len(monsters)} monsters have no runtime move metadata; "
                    "substantive static move facts are required",
                    {"ids": empty_moves},
                )
            )
    return checks


def _has_substantive_monster_moves(
    record: dict[str, Any], records_by_type: dict[str, dict[str, Any]], seen: set[str] | None = None,
) -> bool:
    """Require an actual move-state behavior fact, allowing inherited state machines."""
    data = record.get("data", {})
    type_name = str(record.get("type_name") or "")
    visited = set() if seen is None else seen
    if not type_name or type_name in visited or not isinstance(data, dict):
        return False
    visited.add(type_name)
    for method in data.get("methods", []):
        if not isinstance(method, dict) or method.get("name") != "GenerateMoveStateMachine":
            continue
        facts = " ".join(
            str(item)
            for field_name in (
                "calls", "creates", "assignments", "conditions", "switches", "returns",
                "loops", "throws", "yields", "awaits", "mutations",
            )
            for item in (method.get(field_name) or [])
        )
        if re.search(r"(?:MonsterMoveStateMachine|\bMoveState\b|GenerateMoveStateMachine)", facts):
            return True
    return any(
        _has_substantive_monster_moves(parent, records_by_type, visited)
        for base_type in data.get("base_types", [])
        if isinstance(base_type, str)
        for parent in [records_by_type.get(base_type)]
        if parent is not None
    )


def _walk_control_flow(nodes: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        yield node
        yield from _walk_control_flow(node.get("children"))


def _control_flow_mapping_errors(fact: Any, path: str) -> list[str]:
    """Cross-check flattened branch indexes against the nested statement facts."""
    if not isinstance(fact, dict):
        return [f"{path}: member fact is not an object"]
    flow = fact.get("control_flow")
    if not isinstance(flow, list):
        return [f"{path}.control_flow: expected array"]
    nodes = list(_walk_control_flow(flow))
    normalize = lambda value: " ".join(str(value or "").split())
    expected_conditions = {normalize(value) for value in fact.get("conditions") or []}
    expected_switches = {normalize(value) for value in fact.get("switches") or []}
    actual_conditions = {
        normalize(node.get("expression")) for node in nodes if node.get("kind") == "if"
    }
    actual_switches = {
        normalize(node.get("expression")) for node in nodes if node.get("kind") == "switch"
    }
    errors = [
        f"{path}.control_flow: missing if mapping for {condition!r}"
        for condition in sorted(expected_conditions - actual_conditions)
    ]
    errors.extend(
        f"{path}.control_flow: missing switch mapping for {selection!r}"
        for selection in sorted(expected_switches - actual_switches)
    )
    for node in nodes:
        kind = node.get("kind")
        children = node.get("children")
        if not isinstance(children, list):
            continue
        if kind == "if":
            branch_kinds = [
                child.get("kind") for child in children if isinstance(child, dict)
            ]
            if (branch_kinds.count("then") != 1
                    or branch_kinds.count("else") > 1
                    or branch_kinds.count("condition") > 1
                    or any(branch not in {"condition", "then", "else"}
                           for branch in branch_kinds)):
                errors.append(f"{path}.control_flow: if node has invalid branch roles")
        elif kind == "switch" and any(
                not isinstance(child, dict) or child.get("kind") not in {"case", "default"}
                for child in children):
            errors.append(f"{path}.control_flow: switch node has non-case child")
    return errors


def _check_mechanics(output_dir: Path, manifest: dict[str, Any]) -> list[Check]:
    mechanics = manifest.get("mechanics")
    if not isinstance(mechanics, dict) or mechanics.get("status") == "not_imported":
        return [Check("mechanics.import", "warning", "Static mechanics facts have not been imported")]
    checks: list[Check] = []
    try:
        schema = _load_json_object(MECHANICS_SCHEMA_PATH)
    except ValidationError as exc:
        return [Check("mechanics.schema_definition", "fail", str(exc))]
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
    source_files_raw = mechanics.get("source", {}).get("files", [])
    source_files = source_files_raw if isinstance(source_files_raw, list) else []
    source_by_name = {
        item.get("filename"): item
        for item in source_files
        if isinstance(item, dict) and isinstance(item.get("filename"), str)
    }
    artifact_by_name = {
        Path(str(item.get("path"))).name: item for item in artifacts
    }
    manifest_errors: list[str] = []
    if mechanics.get("schema") != MECHANICS_RECORD_SCHEMA:
        manifest_errors.append(
            f"mechanics.schema={mechanics.get('schema')!r}, expected {MECHANICS_RECORD_SCHEMA!r}")
    if (not isinstance(source_files_raw, list) or len(source_by_name) != len(source_files)
            or set(source_by_name) != set(artifact_by_name)):
        manifest_errors.append("mechanics.source.files does not exactly cover mechanics artifacts")
    for filename in set(source_by_name) & set(artifact_by_name):
        if source_by_name[filename].get("records") != artifact_by_name[filename].get("records"):
            manifest_errors.append(f"record count differs for {filename}")
    if manifest_errors:
        checks.append(Check(
            "mechanics.manifest", "fail", "Mechanics manifest/schema migration is inconsistent",
            {"errors": manifest_errors[:20]},
        ))
    else:
        checks.append(Check(
            "mechanics.manifest", "pass",
            f"Mechanics manifest and {len(artifacts)} artifact declarations are self-consistent",
        ))
    type_names: set[str] = set()
    ids: dict[str, set[str]] = {}
    records_by_type: dict[str, dict[str, Any]] = {}
    records_by_id: dict[str, dict[str, dict[str, Any]]] = {}
    record_count = 0
    malformed = 0
    schema_error_examples: list[str] = []
    control_flow_members = 0
    control_flow_branches = 0
    control_flow_error_examples: list[str] = []
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
            deep_errors = _schema_errors(record, schema, schema)
            provenance = record.get("provenance")
            if isinstance(data, dict) and any(
                data.get(field_name) != record.get(field_name)
                for field_name in ("type_name", "name", "category", "entry_id")
            ):
                deep_errors.append("$: data identity fields do not mirror envelope")
            if not isinstance(provenance, dict) or (
                provenance.get("assembly_sha256") != assembly_hash
                or provenance.get("extractor_schema_version") != MECHANICS_INPUT_SCHEMA_VERSION
            ):
                deep_errors.append("$: record provenance does not match snapshot assembly/schema")
            if isinstance(data, dict):
                member_facts = (
                    list(data.get("constructors") or [])
                    + list(data.get("methods") or [])
                    + [
                        accessor
                        for property_fact in (data.get("properties") or [])
                        if isinstance(property_fact, dict)
                        for accessor in (property_fact.get("accessors") or [])
                    ]
                )
                for member_index, fact in enumerate(member_facts):
                    member_path = f"$.data.members[{member_index}]"
                    mapping_errors = _control_flow_mapping_errors(fact, member_path)
                    deep_errors.extend(mapping_errors)
                    control_flow_error_examples.extend(mapping_errors)
                    if isinstance(fact, dict) and isinstance(fact.get("control_flow"), list):
                        control_flow_members += 1
                        control_flow_branches += sum(
                            1 for node in _walk_control_flow(fact["control_flow"])
                            if node.get("kind") in {"if", "switch", "for", "foreach", "while",
                                                    "do_while", "try_catch"}
                        )
            if (
                record.get("schema") != MECHANICS_RECORD_SCHEMA
                or record.get("category") != category
                or not isinstance(type_name, str)
                or not isinstance(name, str)
                or not isinstance(data, dict)
                or deep_errors
            ):
                malformed += 1
                schema_error_examples.extend(
                    f"{path.name}:{record_count}: {error}" for error in deep_errors[:4]
                )
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
                        "calls", "creates", "assignments", "conditions", "switches", "returns",
                        "loops", "throws", "yields", "awaits", "mutations",
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
            records_by_type[type_name] = record
            if entry_id is not None:
                folded = str(entry_id).casefold()
                category_ids = ids.setdefault(category, set())
                if folded in category_ids:
                    checks.append(
                        Check("mechanics.entry_id", "fail", f"Duplicate {category} ID: {entry_id}")
                    )
                category_ids.add(folded)
                records_by_id.setdefault(category, {})[str(entry_id)] = record
    if malformed:
        checks.append(
            Check(
                "mechanics.schema", "fail", f"{malformed} malformed mechanics records",
                {"examples": schema_error_examples[:20]},
            )
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
    if control_flow_error_examples:
        checks.append(Check(
            "mechanics.control_flow", "fail",
            f"Found {len(control_flow_error_examples)} flattened/nested control-flow mismatches",
            {"examples": control_flow_error_examples[:20]},
        ))
    else:
        checks.append(Check(
            "mechanics.control_flow", "pass",
            f"Validated nested control flow for {control_flow_members} members "
            f"({control_flow_branches} branch/loop nodes)",
        ))

    try:
        model_source_rows = _load_jsonl(
            _safe_artifact_path(output_dir, "catalog/model-source-types.jsonl"))
        pck_model_types = {
            str(item.get("type_name")) for item in model_source_rows
            if isinstance(item.get("type_name"), str)
        }
        mechanics_model_types = {
            type_name for type_name, record in records_by_type.items()
            if type_name.startswith("MegaCrit.Sts2.Core.Models.")
            and not bool((record.get("data") or {}).get("is_nested"))
        }
        missing_model_types = sorted(pck_model_types - mechanics_model_types)
        extra_model_types = sorted(mechanics_model_types - pck_model_types)
        if missing_model_types:
            checks.append(Check(
                "mechanics.model_source_closure", "fail",
                f"{len(missing_model_types)} PCK model source types lack top-level mechanics facts",
                {"missing": missing_model_types[:100], "extra_assembly_types": extra_model_types[:100]},
            ))
        else:
            checks.append(Check(
                "mechanics.model_source_closure", "pass",
                f"All {len(pck_model_types)} PCK model source types have top-level mechanics facts",
                {"extra_assembly_types": extra_model_types},
            ))
    except ValidationError as exc:
        checks.append(Check("mechanics.model_source_closure", "fail", str(exc)))

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

    runtime_collections = manifest.get("runtime", {}).get("collections", {})
    monster_meta = runtime_collections.get("monsters", {}) if isinstance(runtime_collections, dict) else {}
    runtime_monsters: list[dict[str, Any]] = []
    if isinstance(monster_meta, dict) and monster_meta.get("status") == "captured":
        try:
            runtime_monsters = _load_jsonl(
                _safe_artifact_path(output_dir, monster_meta.get("artifact")))
        except ValidationError as exc:
            checks.append(Check("runtime.monsters.moves", "fail", str(exc)))
    if runtime_monsters:
        missing_move_facts = []
        monster_records = records_by_id.get("monsters", {})
        for runtime_record in runtime_monsters:
            monster_id = runtime_record.get("id")
            mechanics_record = monster_records.get(str(monster_id))
            if mechanics_record is None or not _has_substantive_monster_moves(
                    mechanics_record, records_by_type):
                missing_move_facts.append(monster_id)
        if missing_move_facts:
            checks.append(Check(
                "runtime.monsters.moves", "fail",
                f"{len(missing_move_facts)}/{len(runtime_monsters)} runtime monsters lack "
                "a substantive static move-state fact (including inherited facts)",
                {"ids": missing_move_facts},
            ))
        else:
            checks.append(Check(
                "runtime.monsters.moves", "pass",
                f"All {len(runtime_monsters)} runtime monsters have substantive static "
                "move-state facts (direct or inherited)",
            ))
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
    checks.extend(_check_localization(output_dir, manifest))
    checks.extend(_check_runtime(output_dir, manifest))
    checks.extend(_check_mechanics(output_dir, manifest))
    checks.extend(_check_sources(manifest, Path(game_dir).resolve() if game_dir else None))

    counts = Counter(check.status for check in checks)
    overall = "fail" if counts["fail"] else "warning" if counts["warning"] else "pass"
    try:
        artifact_set_hash = _artifact_set_sha256(output_dir, manifest)
    except ValidationError:
        artifact_set_hash = None
    report = {
        "schema": VALIDATION_SCHEMA,
        "validated_snapshot": {
            "binding_version": 1,
            "manifest_sha256": sha256_file(manifest_path),
            "artifact_set_sha256": artifact_set_hash,
            "validator": VALIDATOR_VERSION,
        },
        "overall": overall,
        "counts": {status: counts[status] for status in ("pass", "warning", "fail")},
        "checks": [asdict(check) for check in checks],
    }
    if write_report:
        atomic_write_json(output_dir / "validation.json", report)
    return report
