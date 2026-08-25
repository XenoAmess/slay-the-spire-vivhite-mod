"""Extraction pipeline for immutable game resources and localization."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Iterable, Iterator, Sequence

from . import __version__
from .pck import PckEntry, PckReader, jsonl_inventory, sha256_file


MANIFEST_SCHEMA = "sts2.game-knowledge-manifest/v1"
LOCALIZATION_RECORD_SCHEMA = "sts2.game-knowledge-localization-record/v1"
DEFAULT_LOCALES = ("eng", "zhs")


class ExtractionError(RuntimeError):
    """Raised when source resources cannot form a trustworthy snapshot."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_bytes(value: Any, *, pretty: bool = True) -> bytes:
    if pretty:
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    return text.encode("utf-8")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace one generated file atomically without touching sibling files."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, _json_bytes(value))


def atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    count = 0
    try:
        with os.fdopen(descriptor, "wb") as stream:
            for row in rows:
                stream.write(_json_bytes(row, pretty=False))
                count += 1
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise
    return count


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExtractionError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json_object(data: bytes, *, source: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ExtractionError) as exc:
        raise ExtractionError(f"Invalid JSON object in {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExtractionError(f"Expected a JSON object in {source}, got {type(value).__name__}")
    return value


def normalized_version(value: Any) -> str:
    version = str(value or "").strip()
    if not version:
        raise ExtractionError("release_info.json has no version")
    return version if version.startswith("v") else f"v{version}"


def _artifact(output_dir: Path, path: Path, *, records: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": path.relative_to(output_dir).as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if records is not None:
        result["records"] = records
    return result


def _localization_entries(reader: PckReader, locales: Sequence[str]) -> dict[str, list[PckEntry]]:
    requested = {locale.strip() for locale in locales if locale.strip()}
    if not requested:
        raise ExtractionError("At least one localization locale is required")
    result: dict[str, list[PckEntry]] = {locale: [] for locale in sorted(requested)}
    for entry in reader.entries:
        parts = PurePosixPath(entry.path).parts
        if len(parts) != 3 or parts[0] != "localization" or parts[1] not in requested:
            continue
        if not parts[2].endswith(".json"):
            continue
        result[parts[1]].append(entry)
    for locale, entries in result.items():
        entries.sort(key=lambda entry: entry.path)
        if not entries:
            raise ExtractionError(f"PCK contains no localization JSON for locale {locale!r}")
    return result


def _model_type_rows(entries: Iterable[PckEntry]) -> Iterator[dict[str, Any]]:
    prefix = PurePosixPath("src/Core/Models")
    for entry in sorted(entries, key=lambda item: item.path):
        pure = PurePosixPath(entry.path)
        if pure.suffix != ".cs":
            continue
        try:
            relative = pure.relative_to(prefix)
        except ValueError:
            continue
        without_suffix = relative.with_suffix("")
        parts = without_suffix.parts
        if not parts:
            continue
        category = parts[0] if len(parts) > 1 else "_base"
        yield {
            "type_name": "MegaCrit.Sts2.Core.Models." + ".".join(parts),
            "category": category,
            "source_path": entry.path,
            "pck_size": entry.size,
            "source_is_export_stub": entry.size <= 1,
        }


def extract_game_resources(
    *,
    game_dir: str | Path,
    output_root: str | Path,
    locales: Sequence[str] = DEFAULT_LOCALES,
    full_pck_sha256: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """Extract versioned immutable knowledge from an installed game.

    The game directory is opened read-only.  All writes are confined to
    ``output_root/<version>``.
    """

    game_dir = Path(game_dir).resolve()
    output_root = Path(output_root).resolve()
    release_path = game_dir / "release_info.json"
    pck_path = game_dir / "SlayTheSpire2.pck"
    assembly_path = game_dir / "data_sts2_windows_x86_64" / "sts2.dll"
    for source in (release_path, pck_path, assembly_path):
        if not source.is_file():
            raise ExtractionError(f"Required game file is missing: {source}")

    release_bytes = release_path.read_bytes()
    release = parse_json_object(release_bytes, source=str(release_path))
    version = normalized_version(release.get("version"))
    output_dir = output_root / version
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[dict[str, Any]] = []
    localization_manifest: list[dict[str, Any]] = []
    with PckReader(pck_path) as reader:
        assert reader.header is not None
        localization = _localization_entries(reader, locales)
        localization_key_sets: dict[tuple[str, str], set[str]] = {}
        localization_values: dict[tuple[str, str], dict[str, Any]] = {}
        for locale, entries in localization.items():
            for entry in entries:
                data = reader.read_bytes(entry)
                value = parse_json_object(data, source=entry.path)
                name = PurePosixPath(entry.path).name
                destination = output_dir / "localization" / locale / name
                atomic_write_bytes(destination, data)
                localization_key_sets[(locale, name)] = set(value)
                localization_values[(locale, name)] = value
                item = {
                    "locale": locale,
                    "name": name,
                    "source_path": entry.path,
                    "output_path": destination.relative_to(output_dir).as_posix(),
                    "size": len(data),
                    "pck_md5": entry.md5,
                    "sha256": sha256_file(destination),
                    "key_count": len(value),
                }
                localization_manifest.append(item)
                artifacts.append(_artifact(output_dir, destination, records=len(value)))

        inventory_path = output_dir / "catalog" / "pck-index.jsonl"
        inventory_count = atomic_write_jsonl(inventory_path, jsonl_inventory(reader.entries))
        artifacts.append(_artifact(output_dir, inventory_path, records=inventory_count))

        model_types = list(_model_type_rows(reader.entries))
        model_types_path = output_dir / "catalog" / "model-source-types.jsonl"
        model_type_count = atomic_write_jsonl(model_types_path, model_types)
        artifacts.append(_artifact(output_dir, model_types_path, records=model_type_count))
        model_category_counts = dict(
            sorted(Counter(row["category"] for row in model_types).items(), key=lambda item: item[0])
        )
        csharp_entries = [entry for entry in reader.entries if entry.path.endswith(".cs")]

        locale_files = {
            locale: sorted(item["name"] for item in localization_manifest if item["locale"] == locale)
            for locale in sorted(localization)
        }
        locale_key_coverage: list[dict[str, Any]] = []
        if "eng" in localization and "zhs" in localization:
            for name in sorted(set(locale_files["eng"]) | set(locale_files["zhs"])):
                eng = localization_key_sets.get(("eng", name), set())
                zhs = localization_key_sets.get(("zhs", name), set())
                locale_key_coverage.append(
                    {
                        "name": name,
                        "eng_keys": len(eng),
                        "zhs_keys": len(zhs),
                        "missing_in_zhs": sorted(eng - zhs),
                        "extra_in_zhs": sorted(zhs - eng),
                    }
                )

        bilingual_rows: list[dict[str, Any]] = []
        bilingual_status_counts: Counter[str] = Counter()
        if "eng" in localization and "zhs" in localization:
            for name in sorted(set(locale_files["eng"]) | set(locale_files["zhs"])):
                eng_values = localization_values.get(("eng", name), {})
                zhs_values = localization_values.get(("zhs", name), {})
                for key in sorted(set(eng_values) | set(zhs_values)):
                    has_eng = key in eng_values
                    has_zhs = key in zhs_values
                    status = (
                        "bilingual" if has_eng and has_zhs else "missing_zhs" if has_eng else "missing_eng"
                    )
                    fallback_locale = "zhs" if has_zhs else "eng"
                    bilingual_status_counts[status] += 1
                    key_parts = key.split(".", 1)
                    bilingual_rows.append(
                        {
                            "schema": LOCALIZATION_RECORD_SCHEMA,
                            "file": name,
                            "key": key,
                            "model_id": key_parts[0],
                            "field": key_parts[1] if len(key_parts) == 2 else None,
                            "eng": eng_values.get(key),
                            "zhs": zhs_values.get(key),
                            "status": status,
                            "zhs_or_eng": zhs_values[key] if has_zhs else eng_values[key],
                            "fallback_locale": fallback_locale,
                        }
                    )
            bilingual_path = output_dir / "catalog" / "localization-bilingual.jsonl"
            bilingual_count = atomic_write_jsonl(bilingual_path, bilingual_rows)
            artifacts.append(_artifact(output_dir, bilingual_path, records=bilingual_count))
        else:
            bilingual_path = None
            bilingual_count = 0

        pck_source: dict[str, Any] = {
            "path": pck_path.name,
            "size": pck_path.stat().st_size,
            "directory_sha256": reader.directory_sha256(),
            "full_sha256": sha256_file(pck_path) if full_pck_sha256 else None,
            "header": {
                "format_version": reader.header.format_version,
                "engine_version": reader.header.engine_version,
                "flags": reader.header.flags,
                "file_base": reader.header.file_base,
                "directory_offset": reader.header.directory_offset,
                "entry_count": len(reader.entries),
            },
            "extension_counts": reader.extension_counts(),
            "csharp_path_count": len(csharp_entries),
            "csharp_non_stub_count": sum(entry.size > 1 for entry in csharp_entries),
            "model_type_path_count": len(model_types),
            "model_category_counts": model_category_counts,
        }

    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "generator": {
            "name": "sts2-ascend-game-knowledge",
            "version": __version__,
            "generated_at_utc": _utc_now(),
        },
        "game": {
            "version": version,
            "commit": release.get("commit"),
            "branch": release.get("branch"),
            "release_date": release.get("date"),
            "main_assembly_hash": release.get("main_assembly_hash"),
        },
        "sources": {
            "release_info": {
                "path": release_path.name,
                "size": len(release_bytes),
                "sha256": sha256_file(release_path),
                "content": release,
            },
            "assembly": {
                "path": "data_sts2_windows_x86_64/sts2.dll",
                "size": assembly_path.stat().st_size,
                "sha256": sha256_file(assembly_path),
            },
            "pck": pck_source,
        },
        "localization": {
            "locales": sorted(localization),
            "files": sorted(localization_manifest, key=lambda item: (item["locale"], item["name"])),
            "file_sets": locale_files,
            "eng_zhs_key_coverage": locale_key_coverage,
            "bilingual_artifact": (
                bilingual_path.relative_to(output_dir).as_posix() if bilingual_path else None
            ),
            "bilingual_records": bilingual_count,
            "bilingual_status_counts": dict(sorted(bilingual_status_counts.items())),
        },
        "runtime": {
            "status": "not_captured",
            "base_game_filter": "unavailable",
            "collections": {},
        },
        "mechanics": {
            "status": "not_imported",
            "note": "Static behavior facts are produced by GameKnowledge.Tool and merged separately.",
        },
        "artifacts": sorted(artifacts, key=lambda item: item["path"]),
    }
    manifest_path = output_dir / "manifest.json"
    atomic_write_json(manifest_path, manifest)
    return output_dir, manifest
