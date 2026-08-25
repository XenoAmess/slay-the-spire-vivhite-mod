"""Capture canonical model data from the running STS2AIAgent endpoint."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .extract import atomic_write_json, atomic_write_jsonl
from .ids import model_entry_id
from .pck import sha256_file


RUNTIME_RECORD_SCHEMA = "sts2.game-knowledge-runtime-record/v1"
REQUIRED_COLLECTIONS = (
    "cards",
    "relics",
    "monsters",
    "potions",
    "events",
    "powers",
    "characters",
)
EXPANDED_COLLECTIONS = (
    "encounters",
    "acts",
    "ancients",
    "orbs",
    "afflictions",
    "enchantments",
    "modifiers",
    "card_pools",
    "relic_pools",
    "potion_pools",
)
DEFAULT_COLLECTIONS = REQUIRED_COLLECTIONS + EXPANDED_COLLECTIONS

LOCALIZATION_ID_FILES = {
    "cards": "cards.json",
    "relics": "relics.json",
    "monsters": "monsters.json",
    "potions": "potions.json",
    "events": "events.json",
    "powers": "powers.json",
    "characters": "characters.json",
    "encounters": "encounters.json",
    "acts": "acts.json",
    "ancients": "ancients.json",
    "orbs": "orbs.json",
    "afflictions": "afflictions.json",
    "enchantments": "enchantments.json",
    "modifiers": "modifiers.json",
}

_SAFE_COLLECTION = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_RESPONSE_BYTES = 256 * 1024 * 1024


class RuntimeCaptureError(RuntimeError):
    """Raised when the local game-data API cannot produce a valid snapshot."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _request_json(url: str, *, timeout: float) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "sts2-ascend-game-knowledge/1"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - localhost/explicit user URL.
            data = response.read(_MAX_RESPONSE_BYTES + 1)
    except HTTPError:
        raise
    except (OSError, URLError) as exc:
        raise RuntimeCaptureError(f"Cannot read {url}: {exc}") from exc
    if len(data) > _MAX_RESPONSE_BYTES:
        raise RuntimeCaptureError(f"Response from {url} exceeds {_MAX_RESPONSE_BYTES} bytes")
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeCaptureError(f"Invalid JSON from {url}: {exc}") from exc


def discover_runtime_url(
    *,
    host: str = "127.0.0.1",
    ports: Iterable[int] = range(8080, 8085),
    timeout: float = 1.5,
) -> tuple[str, dict[str, Any]]:
    """Find the first healthy local game instance without serial timeout cost."""

    candidates = [f"http://{host}:{int(port)}" for port in ports]

    def probe(base_url: str) -> tuple[str, Any]:
        return base_url, _request_json(f"{base_url}/health", timeout=timeout)

    successful: list[tuple[str, dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(candidates))) as executor:
        futures = {executor.submit(probe, candidate): candidate for candidate in candidates}
        for future in as_completed(futures):
            try:
                base_url, payload = future.result()
            except Exception:
                continue
            if isinstance(payload, dict) and payload.get("ok") is not False:
                successful.append((base_url, payload))
    if not successful:
        raise RuntimeCaptureError(
            f"No healthy STS2AIAgent endpoint found on {host}:"
            f"{min(ports, default=8080)}-{max(ports, default=8084)}"
        )
    return sorted(successful, key=lambda item: int(item[0].rsplit(":", 1)[1]))[0]


def _collection_items(value: Any, *, collection: str) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("items"), list):
            value = value["items"]
        elif isinstance(value.get(collection), list):
            value = value[collection]
        elif isinstance(value.get("data"), list):
            value = value["data"]
    if not isinstance(value, list):
        raise RuntimeCaptureError(
            f"Runtime collection {collection!r} must be an array (or an object containing one)"
        )
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise RuntimeCaptureError(
                f"Runtime collection {collection!r} item {index} is {type(item).__name__}, not object"
            )
        items.append(item)
    return items


def _base_assembly_status(value: Any) -> str:
    if value is None or not str(value).strip():
        return "unavailable"
    simple_name = str(value).split(",", 1)[0].strip().lower()
    return "base" if simple_name == "sts2" else "mod"


def _localization_allowed_ids(output_dir: Path, collection: str) -> set[str] | None:
    filename = LOCALIZATION_ID_FILES.get(collection)
    if filename is None:
        return None
    path = output_dir / "localization" / "eng" / filename
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    # Localization keys are MODEL_ID.property (and sometimes continue with
    # page/move segments).  The base PCK contains no mod localization, making
    # this a strong fallback filter when the endpoint omits source_assembly.
    return {str(key).split(".", 1)[0].casefold() for key in value if "." in str(key)}


def _snake_category(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _pck_model_allowed_ids(output_dir: Path, collection: str) -> set[str] | None:
    """Get base IDs from source-type paths embedded in the unmodified PCK.

    Unlike localization, the type inventory also contains native models that
    deliberately have no player-facing text (monster segments, temporary
    powers, and test/debug models).  It is therefore the preferred fallback
    when older HTTP endpoints omit ``source_assembly``.
    """

    path = output_dir / "catalog" / "model-source-types.jsonl"
    if not path.is_file():
        return None
    allowed: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    return None
                category = value.get("category")
                type_name = value.get("type_name")
                if (
                    isinstance(category, str)
                    and _snake_category(category) == collection
                    and isinstance(type_name, str)
                ):
                    allowed.add(model_entry_id(type_name.rsplit(".", 1)[-1]).casefold())
    except (OSError, json.JSONDecodeError):
        return None
    return allowed or None


def _base_allowed_ids(output_dir: Path, collection: str) -> tuple[set[str] | None, str | None]:
    model_ids = _pck_model_allowed_ids(output_dir, collection)
    if model_ids is not None:
        return model_ids, "pck_model_types:catalog/model-source-types.jsonl"
    localization_ids = _localization_allowed_ids(output_dir, collection)
    if localization_ids is not None:
        return (
            localization_ids,
            f"pck_localization:localization/eng/{LOCALIZATION_ID_FILES[collection]}",
        )
    return None, None


def _normalized_records(
    items: Sequence[dict[str, Any]],
    *,
    collection: str,
    allowed_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    filtered_mod_ids: list[str] = []
    filtered_not_in_pck_ids: list[str] = []
    unknown_filter_ids: list[str] = []
    for index, item in enumerate(items):
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise RuntimeCaptureError(
                f"Runtime collection {collection!r} item {index} has no non-empty string id"
            )
        item_id = item_id.strip()
        folded = item_id.casefold()
        if folded in seen:
            raise RuntimeCaptureError(f"Duplicate id in runtime {collection}: {item_id}")
        seen.add(folded)

        assembly_status = _base_assembly_status(item.get("source_assembly"))
        if assembly_status == "mod":
            filtered_mod_ids.append(item_id)
            continue
        if assembly_status == "unavailable" and allowed_ids is not None:
            if folded not in allowed_ids:
                filtered_not_in_pck_ids.append(item_id)
                continue
            assembly_status = "pck_base_membership"
        elif assembly_status == "unavailable":
            unknown_filter_ids.append(item_id)
        records.append(
            {
                "schema": RUNTIME_RECORD_SCHEMA,
                "category": collection,
                "id": item_id,
                "type_name": item.get("type_name"),
                "source_assembly": item.get("source_assembly"),
                "provenance": {
                    "source": "STS2AIAgent /data endpoint",
                    "base_game_filter": assembly_status,
                },
                "data": item,
            }
        )
    records.sort(key=lambda row: row["id"])
    metadata = {
        "raw_count": len(items),
        "record_count": len(records),
        "filtered_mod_count": len(filtered_mod_ids),
        "filtered_mod_ids": sorted(filtered_mod_ids),
        "filtered_not_in_pck_count": len(filtered_not_in_pck_ids),
        "filtered_not_in_pck_ids": sorted(filtered_not_in_pck_ids),
        "unknown_base_filter_count": len(unknown_filter_ids),
        "unknown_base_filter_ids": sorted(unknown_filter_ids),
    }
    return records, metadata


def _read_manifest(output_dir: Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeCaptureError(f"Run resource extraction first; manifest missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeCaptureError(f"Cannot read manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeCaptureError(f"Manifest must be a JSON object: {manifest_path}")
    return manifest_path, manifest


def _validate_collection_names(collections: Sequence[str]) -> tuple[str, ...]:
    requested = tuple(dict.fromkeys(collection.strip() for collection in collections if collection.strip()))
    invalid = [collection for collection in requested if not _SAFE_COLLECTION.fullmatch(collection)]
    if invalid:
        raise RuntimeCaptureError(f"Unsafe runtime collection names: {invalid}")
    if not requested:
        raise RuntimeCaptureError("At least one runtime collection is required")
    return requested


def _write_runtime_snapshot(
    *,
    output_dir: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    payloads: dict[str, Any],
    requested: Sequence[str],
    source: dict[str, Any],
) -> dict[str, Any]:
    collection_meta: dict[str, Any] = {}
    new_artifacts: list[dict[str, Any]] = []
    warnings: list[str] = []
    filter_states: set[str] = set()
    for collection in requested:
        if collection not in payloads:
            collection_meta[collection] = {
                "status": "unavailable",
                "required": collection in REQUIRED_COLLECTIONS,
            }
            warnings.append(f"Runtime collection {collection} is unavailable")
            continue
        items = _collection_items(payloads[collection], collection=collection)
        allowed_ids, allowed_ids_source = _base_allowed_ids(output_dir, collection)
        records, metadata = _normalized_records(
            items,
            collection=collection,
            allowed_ids=allowed_ids,
        )
        destination = output_dir / "runtime" / f"{collection}.jsonl"
        written = atomic_write_jsonl(destination, records)
        if written != metadata["record_count"]:
            raise RuntimeCaptureError(f"Short write for runtime collection {collection}")
        artifact = {
            "path": destination.relative_to(output_dir).as_posix(),
            "size": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "records": written,
        }
        new_artifacts.append(artifact)
        base_filter_source = (
            allowed_ids_source
            if allowed_ids is not None and metadata["unknown_base_filter_count"] == 0
            else "source_assembly"
        )
        collection_meta[collection] = {
            "status": "captured",
            "required": collection in REQUIRED_COLLECTIONS,
            "artifact": artifact["path"],
            "base_filter_source": base_filter_source,
            **metadata,
        }
        if metadata["unknown_base_filter_count"]:
            filter_states.add("unavailable")
            warnings.append(
                f"Runtime collection {collection} lacks source_assembly/PCK membership for "
                f"{metadata['unknown_base_filter_count']} records; mod contamination cannot be excluded"
            )
        else:
            filter_states.add("available")

    required_unavailable = [
        name for name in REQUIRED_COLLECTIONS if collection_meta.get(name, {}).get("status") != "captured"
    ]
    if required_unavailable:
        warnings.append(f"Required runtime collections unavailable: {required_unavailable}")

    if filter_states == {"available"}:
        base_filter = "available"
    elif filter_states == {"unavailable"}:
        base_filter = "unavailable"
    else:
        base_filter = "partially_available"

    previous_artifacts = [
        item
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict) and not str(item.get("path", "")).startswith("runtime/")
    ]
    manifest["artifacts"] = sorted(previous_artifacts + new_artifacts, key=lambda item: item["path"])
    manifest["runtime"] = {
        "status": "captured" if not warnings else "captured_with_warnings",
        "captured_at_utc": _utc_now(),
        "source": source,
        "base_game_filter": base_filter,
        "collections": collection_meta,
        "warnings": warnings,
    }
    atomic_write_json(manifest_path, manifest)
    return manifest["runtime"]


def capture_runtime(
    *,
    output_dir: str | Path,
    base_url: str | None = None,
    collections: Sequence[str] = DEFAULT_COLLECTIONS,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Capture runtime collections and merge their provenance into manifest."""

    output_dir = Path(output_dir).resolve()
    manifest_path, manifest = _read_manifest(output_dir)
    requested = _validate_collection_names(collections)

    if base_url is None:
        base_url, health = discover_runtime_url(timeout=min(timeout, 2.0))
    else:
        base_url = base_url.rstrip("/")
        health_value = _request_json(f"{base_url}/health", timeout=min(timeout, 5.0))
        health = health_value if isinstance(health_value, dict) else {"response": health_value}

    payloads: dict[str, Any] = {}
    unavailable: dict[str, dict[str, Any]] = {}
    for collection in requested:
        url = f"{base_url}/data/{collection}"
        try:
            payload = _request_json(url, timeout=timeout)
            payloads[collection] = payload
        except HTTPError as exc:
            if exc.code == 404:
                unavailable[collection] = {"http_status": 404}
                continue
            raise RuntimeCaptureError(f"HTTP {exc.code} from {url}: {exc.reason}") from exc
    result = _write_runtime_snapshot(
        output_dir=output_dir,
        manifest_path=manifest_path,
        manifest=manifest,
        payloads=payloads,
        requested=requested,
        source={"kind": "http", "url": base_url, "health": health},
    )
    for collection, detail in unavailable.items():
        if collection in result["collections"]:
            result["collections"][collection].update(detail)
    if unavailable:
        atomic_write_json(manifest_path, manifest)
    return result


def import_runtime_response_dir(
    *,
    output_dir: str | Path,
    response_dir: str | Path,
    collections: Sequence[str] = DEFAULT_COLLECTIONS,
) -> dict[str, Any]:
    """Import ``<collection>.response.json`` files captured from /data."""

    output_dir = Path(output_dir).resolve()
    response_dir = Path(response_dir).resolve()
    if not response_dir.is_dir():
        raise RuntimeCaptureError(f"Runtime response directory does not exist: {response_dir}")
    manifest_path, manifest = _read_manifest(output_dir)
    requested = _validate_collection_names(collections)
    payloads: dict[str, Any] = {}
    response_sources: dict[str, Any] = {}
    for collection in requested:
        path = response_dir / f"{collection}.response.json"
        if not path.is_file():
            continue
        try:
            payloads[collection] = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeCaptureError(f"Invalid runtime response {path}: {exc}") from exc
        response_sources[collection] = {
            "filename": path.name,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    if not payloads:
        raise RuntimeCaptureError(f"No *.response.json files found in {response_dir}")
    result = _write_runtime_snapshot(
        output_dir=output_dir,
        manifest_path=manifest_path,
        manifest=manifest,
        payloads=payloads,
        requested=requested,
        source={
            "kind": "response_directory",
            "directory_name": response_dir.name,
            "responses": response_sources,
        },
    )
    return result
