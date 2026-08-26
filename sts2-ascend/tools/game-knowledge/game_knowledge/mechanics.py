"""Import normalized gameplay facts extracted from the managed game assembly."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .extract import atomic_write_json, atomic_write_jsonl
from .ids import model_entry_id
from .pck import sha256_file
from .runtime import RUNTIME_RECORD_SCHEMA


MECHANICS_RECORD_SCHEMA = "sts2.game-knowledge-mechanics-record/v4"
MECHANICS_INPUT_SCHEMA_VERSION = 4


class MechanicsImportError(RuntimeError):
    """Raised when static facts cannot be trusted or deterministically joined."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MechanicsImportError(f"Cannot parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MechanicsImportError(f"Expected a JSON object in {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise MechanicsImportError(f"{path}:{line_number} is not a JSON object")
                records.append(value)
    except json.JSONDecodeError as exc:
        raise MechanicsImportError(f"Cannot parse JSONL {path}:{exc.lineno}: {exc.msg}") from exc
    except OSError as exc:
        raise MechanicsImportError(f"Cannot read {path}: {exc}") from exc
    return records


def _safe_input_file(mechanics_dir: Path, filename: Any) -> Path:
    if not isinstance(filename, str) or not filename:
        raise MechanicsImportError(f"Invalid mechanics filename: {filename!r}")
    pure = PurePosixPath(filename)
    if pure.is_absolute() or len(pure.parts) != 1 or "\\" in filename:
        raise MechanicsImportError(f"Unsafe mechanics filename: {filename!r}")
    path = (mechanics_dir / filename).resolve()
    try:
        path.relative_to(mechanics_dir)
    except ValueError as exc:
        raise MechanicsImportError(f"Mechanics file escapes input directory: {filename!r}") from exc
    return path


def _artifact(output_dir: Path, path: Path, records: int) -> dict[str, Any]:
    return {
        "path": path.relative_to(output_dir).as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "records": records,
    }


def _runtime_ids(output_dir: Path, manifest: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    collections = manifest.get("runtime", {}).get("collections", {})
    if not isinstance(collections, dict):
        return result
    for category, metadata in collections.items():
        if not isinstance(metadata, dict) or metadata.get("status") != "captured":
            continue
        relative = metadata.get("artifact")
        if not isinstance(relative, str):
            continue
        path = output_dir / Path(*PurePosixPath(relative).parts)
        ids: set[str] = set()
        for record in _read_jsonl(path):
            if record.get("schema") != RUNTIME_RECORD_SCHEMA:
                raise MechanicsImportError(f"Unexpected runtime record schema in {path}")
            record_id = record.get("id")
            if isinstance(record_id, str):
                ids.add(record_id.casefold())
        result[str(category)] = ids
    return result


def _validate_fact_record(
    value: dict[str, Any], *, expected_category: str, source: str
) -> tuple[str, str, str | None]:
    type_name = value.get("type_name")
    name = value.get("name")
    category = value.get("category")
    if not isinstance(type_name, str) or not type_name:
        raise MechanicsImportError(f"{source} has no non-empty type_name")
    if not isinstance(name, str) or not name:
        raise MechanicsImportError(f"{source} has no non-empty name")
    if category != expected_category:
        raise MechanicsImportError(
            f"{source} category {category!r} does not match file category {expected_category!r}"
        )
    is_nested = value.get("is_nested")
    declaring_type_name = value.get("declaring_type_name")
    if not isinstance(is_nested, bool):
        raise MechanicsImportError(f"{source} field 'is_nested' is not boolean")
    if is_nested and (not isinstance(declaring_type_name, str) or not declaring_type_name):
        raise MechanicsImportError(f"{source} nested type has no declaring_type_name")
    if not is_nested and declaring_type_name is not None:
        raise MechanicsImportError(f"{source} top-level type has declaring_type_name")
    for field_name in ("base_types", "fields", "properties", "constructors", "methods"):
        if not isinstance(value.get(field_name), list):
            raise MechanicsImportError(f"{source} field {field_name!r} is not an array")
    for index, property_fact in enumerate(value["properties"]):
        if (
            not isinstance(property_fact, dict)
            or not isinstance(property_fact.get("expressions"), list)
            or not isinstance(property_fact.get("accessors"), list)
        ):
            raise MechanicsImportError(f"{source} property {index} has invalid v4 facts")
        for accessor_index, accessor in enumerate(property_fact["accessors"]):
            _validate_behavior_fact(
                accessor,
                source=f"{source} property {index} accessor {accessor_index}",
            )
    for field_name in ("constructors", "methods"):
        for index, behavior in enumerate(value[field_name]):
            _validate_behavior_fact(behavior, source=f"{source} {field_name} {index}")

    supplied_entry_id = value.get("entry_id")
    is_model = (
        not is_nested
        and type_name.startswith("MegaCrit.Sts2.Core.Models.")
        and category != "model_bases"
    )
    computed_entry_id = model_entry_id(name) if is_model else None
    if supplied_entry_id != computed_entry_id:
        raise MechanicsImportError(
            f"{source} entry_id mismatch: supplied={supplied_entry_id!r}, "
            f"computed={computed_entry_id!r}"
        )
    return type_name, name, computed_entry_id


def _validate_control_flow(value: Any, *, source: str) -> None:
    if not isinstance(value, list):
        raise MechanicsImportError(f"{source} is not an array")
    for index, node in enumerate(value):
        node_source = f"{source}[{index}]"
        if not isinstance(node, dict):
            raise MechanicsImportError(f"{node_source} is not an object")
        kind = node.get("kind")
        expression = node.get("expression")
        if not isinstance(kind, str) or not kind:
            raise MechanicsImportError(f"{node_source} has no non-empty kind")
        if expression is not None and not isinstance(expression, str):
            raise MechanicsImportError(f"{node_source} expression is not string/null")
        _validate_control_flow(node.get("children"), source=f"{node_source}.children")


def _validate_behavior_fact(value: Any, *, source: str) -> None:
    if not isinstance(value, dict):
        raise MechanicsImportError(f"{source} is not an object")
    for field_name in (
        "calls", "creates", "assignments", "conditions", "switches", "returns",
        "loops", "throws", "yields", "awaits", "mutations",
    ):
        items = value.get(field_name)
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise MechanicsImportError(f"{source} field {field_name!r} is not a string array")
    _validate_control_flow(value.get("control_flow"), source=f"{source}.control_flow")


def _join_summary(
    runtime: dict[str, set[str]], mechanics_ids: dict[str, dict[str, str]]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    summary: dict[str, Any] = {}
    joins: list[dict[str, str]] = []
    for category in sorted(set(runtime) | set(mechanics_ids)):
        runtime_ids = runtime.get(category)
        by_id = mechanics_ids.get(category, {})
        if runtime_ids is None:
            summary[category] = {
                "status": "runtime_unavailable",
                "mechanics_id_count": len(by_id),
            }
            continue
        matched = sorted(set(by_id) & runtime_ids)
        missing_mechanics = sorted(runtime_ids - set(by_id))
        missing_runtime = sorted(set(by_id) - runtime_ids)
        if missing_mechanics:
            status = "partial"
        elif missing_runtime:
            status = "complete_with_static_only"
        else:
            status = "complete"
        summary[category] = {
            "status": status,
            "runtime_id_count": len(runtime_ids),
            "mechanics_id_count": len(by_id),
            "matched_count": len(matched),
            "runtime_without_mechanics": missing_mechanics,
            "mechanics_without_runtime": missing_runtime,
        }
        joins.extend(
            {
                "category": category,
                "id": entry_id.upper(),
                "type_name": by_id[entry_id],
            }
            for entry_id in matched
        )
    joins.sort(key=lambda item: (item["category"], item["id"], item["type_name"]))
    return summary, joins


def import_mechanics(*, output_dir: str | Path, mechanics_dir: str | Path) -> dict[str, Any]:
    """Import assembly facts and join model types to runtime records by exact ID."""

    output_dir = Path(output_dir).resolve()
    mechanics_dir = Path(mechanics_dir).resolve()
    manifest_path = output_dir / "manifest.json"
    manifest = _read_json_object(manifest_path)
    input_manifest_path = mechanics_dir / "mechanics-manifest.json"
    input_manifest = _read_json_object(input_manifest_path)
    if input_manifest.get("schema_version") != MECHANICS_INPUT_SCHEMA_VERSION:
        raise MechanicsImportError(
            f"Unsupported mechanics schema_version: {input_manifest.get('schema_version')!r}"
        )

    expected_assembly_hash = manifest.get("sources", {}).get("assembly", {}).get("sha256")
    input_assembly_hash = input_manifest.get("source", {}).get("assembly_sha256")
    if not isinstance(expected_assembly_hash, str) or input_assembly_hash != expected_assembly_hash:
        raise MechanicsImportError(
            "Mechanics assembly SHA256 does not match the resource snapshot: "
            f"mechanics={input_assembly_hash!r}, snapshot={expected_assembly_hash!r}"
        )

    advertised_hashes = input_manifest.get("output_sha256")
    if not isinstance(advertised_hashes, dict) or not advertised_hashes:
        raise MechanicsImportError("mechanics-manifest.json has no output_sha256 mapping")

    rows_by_category: dict[str, list[dict[str, Any]]] = {}
    type_names: set[str] = set()
    mechanics_ids: dict[str, dict[str, str]] = {}
    source_files: list[dict[str, Any]] = []
    for filename in sorted(advertised_hashes):
        path = _safe_input_file(mechanics_dir, filename)
        expected_hash = advertised_hashes[filename]
        if not path.is_file():
            raise MechanicsImportError(f"Advertised mechanics file is missing: {filename}")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise MechanicsImportError(
                f"Mechanics hash mismatch for {filename}: expected={expected_hash}, actual={actual_hash}"
            )
        if path.suffix != ".jsonl":
            raise MechanicsImportError(f"Mechanics output is not JSONL: {filename}")
        category = path.stem
        rows = _read_jsonl(path)
        normalized: list[dict[str, Any]] = []
        by_id = mechanics_ids.setdefault(category, {})
        for index, value in enumerate(rows, 1):
            source = f"{filename}:{index}"
            type_name, name, entry_id = _validate_fact_record(
                value, expected_category=category, source=source
            )
            if type_name in type_names:
                raise MechanicsImportError(f"Duplicate mechanics type_name: {type_name}")
            type_names.add(type_name)
            if entry_id is not None:
                folded = entry_id.casefold()
                if folded in by_id:
                    raise MechanicsImportError(
                        f"Duplicate computed model ID in {category}: {entry_id} "
                        f"({by_id[folded]}, {type_name})"
                    )
                by_id[folded] = type_name
            normalized.append(
                {
                    "schema": MECHANICS_RECORD_SCHEMA,
                    "category": category,
                    "type_name": type_name,
                    "name": name,
                    "entry_id": entry_id,
                    "provenance": {
                        "source": "locally installed sts2.dll",
                        "assembly_sha256": input_assembly_hash,
                        "extractor_schema_version": MECHANICS_INPUT_SCHEMA_VERSION,
                    },
                    "data": value,
                }
            )
        normalized.sort(key=lambda item: item["type_name"])
        rows_by_category[category] = normalized
        source_files.append(
            {
                "filename": filename,
                "size": path.stat().st_size,
                "sha256": actual_hash,
                "records": len(rows),
            }
        )

    runtime = _runtime_ids(output_dir, manifest)
    join_summary, joins = _join_summary(runtime, mechanics_ids)
    new_artifacts: list[dict[str, Any]] = []
    for category, rows in sorted(rows_by_category.items()):
        path = output_dir / "mechanics" / f"{category}.jsonl"
        written = atomic_write_jsonl(path, rows)
        new_artifacts.append(_artifact(output_dir, path, written))
    join_path = output_dir / "catalog" / "runtime-mechanics-joins.jsonl"
    join_count = atomic_write_jsonl(join_path, joins)
    new_artifacts.append(_artifact(output_dir, join_path, join_count))

    failures = input_manifest.get("failures")
    if not isinstance(failures, list):
        raise MechanicsImportError("mechanics-manifest.json failures field is not an array")
    warnings: list[str] = []
    if failures:
        warnings.append(f"Static extractor reported {len(failures)} failed types")
    partial_categories = [
        category for category, detail in join_summary.items() if detail.get("status") == "partial"
    ]
    if partial_categories:
        warnings.append(f"Runtime/mechanics joins are partial for: {partial_categories}")

    previous_artifacts = [
        item
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict)
        and not str(item.get("path", "")).startswith("mechanics/")
        and item.get("path") != "catalog/runtime-mechanics-joins.jsonl"
    ]
    manifest["artifacts"] = sorted(previous_artifacts + new_artifacts, key=lambda item: item["path"])
    manifest["mechanics"] = {
        "status": "imported_with_warnings" if warnings else "imported",
        "imported_at_utc": _utc_now(),
        "schema": MECHANICS_RECORD_SCHEMA,
        "source": {
            "assembly": input_manifest.get("source", {}).get("assembly"),
            "assembly_sha256": input_assembly_hash,
            "extraction": input_manifest.get("extraction"),
            "generated_at_utc": input_manifest.get("generated_at_utc"),
            "files": source_files,
        },
        "counts": dict(sorted(Counter(row["category"] for rows in rows_by_category.values() for row in rows).items())),
        "record_count": sum(len(rows) for rows in rows_by_category.values()),
        "extractor_failures": failures,
        "joins": join_summary,
        "join_artifact": join_path.relative_to(output_dir).as_posix(),
        "warnings": warnings,
    }
    atomic_write_json(manifest_path, manifest)
    return manifest["mechanics"]
