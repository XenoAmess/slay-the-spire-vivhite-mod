"""Read-only access to versioned base-game facts under ``knowledge/game``.

The extractor deliberately keeps immutable game facts separate from learned
statistics.  This module is the small query boundary between those layers: it
selects a validated snapshot, lazily indexes runtime/static JSONL records, can
fill fields omitted by combat payloads, and builds a bounded evidence packet
for the asynchronous reviewer.

No generated file is modified here.  A missing or invalid corpus degrades to an
explicit unavailable status instead of preventing the autonomous runner from
starting.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


MANIFEST_SCHEMA = "sts2.game-knowledge-manifest/v1"
RUNTIME_SCHEMA = "sts2.game-knowledge-runtime-record/v1"
MECHANICS_SCHEMA = "sts2.game-knowledge-mechanics-record/v4"
VALIDATION_SCHEMA = "sts2.game-knowledge-validation/v2"
VALIDATOR_VERSION = "game_knowledge.validate/v3"
SUPPORTED_MECHANICS_SCHEMAS = {
    "sts2.game-knowledge-mechanics-record/v1",
    "sts2.game-knowledge-mechanics-record/v2",
    "sts2.game-knowledge-mechanics-record/v3",
    MECHANICS_SCHEMA,
}
CORE_CATEGORIES = ("cards", "monsters", "relics", "potions", "events")


def _version_key(path: Path) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", path.name)
    return tuple(int(value) for value in numbers) or (0,)


def _entity_id(value: Any) -> str:
    return str(value or "").strip().upper().rstrip("+")


def _clip(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _bounded_behavior_values(field: str, values: Any, limit: int = 3) -> list[str]:
    """Keep a bounded behavior sample without wasting slots on call-chain prefixes."""
    normalized = list(dict.fromkeys(
        " ".join(str(value or "").split())
        for value in (values or [])
        if str(value or "").strip()
    ))
    if field == "calls":
        normalized = [
            value for value in normalized
            if not any(value != other and len(value) < len(other) and value in other
                       for other in normalized)
        ]
    return [_clip(value) for value in normalized[:limit]]


_CONTROL_FLOW_KINDS = {
    "if", "then", "else", "switch", "case", "default", "for", "foreach",
    "await_foreach", "while", "do_while", "try_catch", "try", "catch", "finally",
}


def _control_flow_has_structure(nodes: Any) -> bool:
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if node.get("kind") in _CONTROL_FLOW_KINDS:
            return True
        if _control_flow_has_structure(node.get("children")):
            return True
    return False


def _bounded_control_flow(
    nodes: Any, *, max_nodes: int = 32, max_depth: int = 6, max_siblings: int = 16,
) -> list[dict[str, Any]]:
    """Bound a normalized statement tree while retaining structural branches."""
    budget = [max_nodes]

    def select_children(children: list[Any]) -> list[Any]:
        if len(children) <= max_siblings:
            return children
        structural = [
            (index, child) for index, child in enumerate(children)
            if isinstance(child, dict) and child.get("kind") in _CONTROL_FLOW_KINDS
        ]
        selected = structural[:max_siblings]
        selected_indexes = {index for index, _child in selected}
        for index, child in enumerate(children):
            if len(selected) >= max_siblings:
                break
            if index not in selected_indexes:
                selected.append((index, child))
        return [child for _index, child in sorted(selected)]

    def visit(node: Any, depth: int) -> dict[str, Any] | None:
        if budget[0] <= 0 or not isinstance(node, dict):
            return None
        budget[0] -= 1
        children = node.get("children") if isinstance(node.get("children"), list) else []
        result: dict[str, Any] = {
            "kind": str(node.get("kind") or "unknown"),
            "expression": None if node.get("expression") is None else _clip(node["expression"], 120),
            "children": [],
        }
        if depth >= max_depth:
            if children:
                result["truncated_children"] = len(children)
            return result
        chosen = select_children(children)
        for child in chosen:
            rendered = visit(child, depth + 1)
            if rendered is not None:
                result["children"].append(rendered)
        omitted = len(children) - len(chosen)
        if omitted > 0:
            result["truncated_children"] = omitted
        return result

    rendered = []
    for node in select_children(list(nodes or [])):
        value = visit(node, 0)
        if value is not None:
            rendered.append(value)
    return rendered


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_set_sha256(snapshot: Path, manifest: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("manifest.artifacts is not an array")
    rows: list[tuple[str, Path]] = []
    for item in artifacts:
        relative = item.get("path") if isinstance(item, dict) else None
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise ValueError(f"invalid artifact path: {relative!r}")
        pure = Path(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"unsafe artifact path: {relative!r}")
        path = (snapshot / pure).resolve()
        path.relative_to(snapshot.resolve())
        if not path.is_file():
            raise ValueError(f"missing artifact: {relative}")
        rows.append((relative, path))
    for relative, path in sorted(rows):
        row = json.dumps({
            "path": relative, "size": path.stat().st_size,
            "sha256": _sha256_file(path),
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest.update(row.encode("utf-8") + b"\n")
    return digest.hexdigest()


class NativeGameKnowledge:
    """Lazy index for one validated base-game snapshot."""

    def __init__(self, game_root: Path):
        self.game_root = Path(game_root)
        self.snapshot_dir: Path | None = None
        self.manifest: dict[str, Any] = {}
        self.validation: dict[str, Any] = {}
        self.error: str | None = None
        self._runtime: dict[str, dict[str, dict[str, Any]]] = {}
        self._mechanics: dict[str, dict[str, dict[str, Any]]] = {}
        self._name_index: dict[str, list[tuple[str, str]]] | None = None
        self._open_latest()

    @classmethod
    def from_knowledge_root(cls, knowledge_root: str | Path) -> "NativeGameKnowledge":
        return cls(Path(knowledge_root) / "game")

    @property
    def available(self) -> bool:
        return self.snapshot_dir is not None and self.error is None

    @property
    def version(self) -> str | None:
        game = self.manifest.get("game") if isinstance(self.manifest, dict) else None
        return str(game.get("version")) if isinstance(game, dict) and game.get("version") else None

    def _open_latest(self) -> None:
        if not self.game_root.is_dir():
            self.error = f"native knowledge directory is missing: {self.game_root}"
            return
        candidates = sorted(
            (path for path in self.game_root.iterdir()
             if path.is_dir() and (path / "manifest.json").is_file()),
            key=lambda path: (_version_key(path), path.name),
            reverse=True,
        )
        if not candidates:
            self.error = f"no versioned native snapshot under {self.game_root}"
            return
        selected = candidates[0]
        try:
            manifest_path = selected / "manifest.json"
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            validation_path = selected / "validation.json"
            validation = (json.loads(validation_path.read_text(encoding="utf-8"))
                          if validation_path.is_file() else {})
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.error = f"cannot read native snapshot {selected}: {exc}"
            return
        if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
            self.error = f"unsupported native manifest schema in {selected}"
            return
        if isinstance(validation, dict) and int((validation.get("counts") or {}).get("fail", 0)):
            self.error = f"native snapshot validation has failures: {selected}"
            return
        binding = validation.get("validated_snapshot") if isinstance(validation, dict) else None
        if (not isinstance(validation, dict) or validation.get("schema") != VALIDATION_SCHEMA
                or not isinstance(binding, dict)
                or binding.get("validator") != VALIDATOR_VERSION):
            self.error = f"native snapshot validation is missing a trusted binding: {selected}"
            return
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if binding.get("manifest_sha256") != manifest_hash:
            self.error = f"native snapshot validation is stale for manifest: {selected}"
            return
        try:
            artifact_hash = _artifact_set_sha256(selected, manifest)
        except (OSError, ValueError) as exc:
            self.error = f"cannot verify native snapshot artifacts {selected}: {exc}"
            return
        if binding.get("artifact_set_sha256") != artifact_hash:
            self.error = f"native snapshot validation is stale for artifacts: {selected}"
            return
        if selected.name != str((manifest.get("game") or {}).get("version") or ""):
            self.error = f"native snapshot version/directory mismatch: {selected}"
            return
        self.snapshot_dir = selected
        self.manifest = manifest
        self.validation = validation if isinstance(validation, dict) else {}
        self.error = None

    def status_digest(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "error": self.error}
        game = self.manifest.get("game") or {}
        runtime = self.manifest.get("runtime") or {}
        mechanics = self.manifest.get("mechanics") or {}
        collections = runtime.get("collections") or {}
        return {
            "available": True,
            "version": game.get("version"),
            "commit": game.get("commit"),
            "assembly_sha256": (self.manifest.get("sources", {}).get("assembly", {})
                                .get("sha256")),
            "runtime_counts": {
                name: detail.get("record_count")
                for name, detail in sorted(collections.items())
                if isinstance(detail, dict) and detail.get("status") == "captured"
            },
            "mechanics_records": mechanics.get("record_count"),
            "extractor_failures": len(mechanics.get("extractor_failures") or []),
            "validation": (self.validation.get("counts") or {}),
        }

    def _load_jsonl(self, relative: Path, schema: str | set[str],
                    category: str) -> dict[str, dict[str, Any]]:
        if self.snapshot_dir is None:
            return {}
        path = self.snapshot_dir / relative
        rows: dict[str, dict[str, Any]] = {}
        try:
            with path.open("r", encoding="utf-8-sig") as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    accepted = {schema} if isinstance(schema, str) else schema
                    if not isinstance(value, dict) or value.get("schema") not in accepted:
                        raise ValueError(f"invalid schema at {path}:{line_number}")
                    if value.get("category") != category:
                        raise ValueError(f"category mismatch at {path}:{line_number}")
                    runtime_file = accepted == {RUNTIME_SCHEMA}
                    record_id = value.get("id") if runtime_file else value.get("entry_id")
                    if not record_id and not runtime_file and value.get("type_name"):
                        # v2 includes nested types as independent facts.  They have
                        # no ModelDb ID but remain addressable by their unique CLR
                        # type and are attached to their declaring model in digests.
                        record_id = "@TYPE:" + str(value["type_name"])
                    if record_id:
                        key = _entity_id(record_id)
                        if key in rows:
                            raise ValueError(f"duplicate id {key} in {path}")
                        rows[key] = value
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self.error = f"native index read failed: {exc}"
            return {}
        return rows

    def runtime_records(self, category: str) -> dict[str, dict[str, Any]]:
        category = str(category).lower()
        if category not in self._runtime:
            self._runtime[category] = self._load_jsonl(
                Path("runtime") / f"{category}.jsonl", RUNTIME_SCHEMA, category)
        return self._runtime[category]

    def mechanics_records(self, category: str) -> dict[str, dict[str, Any]]:
        category = str(category).lower()
        if category not in self._mechanics:
            self._mechanics[category] = self._load_jsonl(
                Path("mechanics") / f"{category}.jsonl", SUPPORTED_MECHANICS_SCHEMAS,
                category)
        return self._mechanics[category]

    def lookup(self, category: str, record_id: Any) -> dict[str, Any] | None:
        """Return runtime and static facts joined by the game's canonical ID."""
        key = _entity_id(record_id)
        if not key or not self.available:
            return None
        runtime = self.runtime_records(category).get(key)
        mechanics = self.mechanics_records(category).get(key)
        if runtime is None and mechanics is None:
            return None
        return {
            "id": key,
            "runtime": runtime.get("data") if runtime else None,
            "mechanics": mechanics.get("data") if mechanics else None,
            "type_name": ((mechanics or {}).get("type_name")
                          or (runtime or {}).get("type_name")),
        }

    def enrich_card(self, card: dict[str, Any]) -> dict[str, Any]:
        """Fill fields omitted by live combat/reward payloads without overriding state."""
        fact = self.lookup("cards", card.get("card_id") or card.get("id"))
        runtime = (fact or {}).get("runtime") or {}
        if not runtime:
            return card
        enriched = dict(card)
        aliases = {
            "name": "name",
            "card_type": "type",
            "rarity": "rarity",
            "rules_text": "description",
            "resolved_rules_text": "description",
            "energy_cost": "cost",
            "costs_x": "is_x_cost",
            "dynamic_values": "vars",
        }
        for destination, source in aliases.items():
            if enriched.get(destination) is None or enriched.get(destination) == "":
                if runtime.get(source) is not None:
                    enriched[destination] = runtime[source]
        return enriched

    def _build_name_index(self) -> dict[str, list[tuple[str, str]]]:
        if self._name_index is not None:
            return self._name_index
        index: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for category in CORE_CATEGORIES:
            for record_id, envelope in self.runtime_records(category).items():
                data = envelope.get("data") or {}
                for candidate in (record_id, data.get("name")):
                    token = str(candidate or "").strip().casefold()
                    if len(token) >= 2:
                        index[token].append((category, record_id))
        self._name_index = dict(index)
        return self._name_index

    def ids_mentioned(self, texts: Iterable[Any]) -> dict[str, set[str]]:
        """Resolve localized names/IDs mentioned in bounded run summaries."""
        haystack = "\n".join(str(text or "") for text in texts).casefold()
        found: dict[str, set[str]] = defaultdict(set)
        if not haystack:
            return found
        for token, rows in self._build_name_index().items():
            if token in haystack:
                for category, record_id in rows:
                    found[category].add(record_id)
        return found

    @staticmethod
    def _runtime_highlights(category: str, data: dict[str, Any]) -> dict[str, Any]:
        common = ("name", "description", "type", "rarity")
        fields = {
            "cards": common + ("target", "cost", "is_x_cost", "color", "damage", "block",
                                "keywords", "tags", "vars", "upgrade"),
            "monsters": common + ("min_hp", "max_hp", "moves"),
            "relics": common + ("pool", "counter_type"),
            "potions": common + ("pool", "usage", "target_type"),
            "events": common + ("options",),
        }.get(category, common)
        return {name: data.get(name) for name in fields if name in data}

    @staticmethod
    def _mechanics_highlights(category: str, data: dict[str, Any]) -> dict[str, Any]:
        behavior_fields = (
            "calls", "creates", "assignments", "conditions", "switches", "returns",
            "loops", "throws", "yields", "awaits", "mutations",
        )
        properties = []
        for prop in data.get("properties") or []:
            if not isinstance(prop, dict) or not (prop.get("expressions") or prop.get("accessors")):
                continue
            compact_property = {
                "name": prop.get("name"),
                "expressions": [_clip(value) for value in prop.get("expressions", [])[:3]],
            }
            accessors = []
            for accessor in (prop.get("accessors") or [])[:2]:
                compact_accessor = {"kind": accessor.get("kind")}
                for field in behavior_fields:
                    values = _bounded_behavior_values(field, accessor.get(field))
                    if values:
                        compact_accessor[field] = values
                if _control_flow_has_structure(accessor.get("control_flow")):
                    compact_accessor["control_flow"] = _bounded_control_flow(
                        accessor.get("control_flow"))
                accessors.append(compact_accessor)
            if accessors:
                compact_property["accessors"] = accessors
            properties.append(compact_property)
        constants = [
            {"name": row.get("name"), "value": _clip(row.get("value"))}
            for row in (data.get("fields") or [])
            if isinstance(row, dict) and row.get("is_const") and row.get("value") is not None
        ]
        method_pattern = {
            "cards": r"canonical|play|upgrade|draw|discard|exhaust|energy|damage|block|power|can",
            "monsters": r"move|state|damage|turn|stun|die|spawn|power|intent",
            "relics": r"play|combat|turn|card|damage|block|reward|gold|potion|power|can|should",
            "potions": r"use|can|damage|block|heal|card|power|energy|target",
            "events": r"option|choose|enter|room|reward|card|relic|gold|damage|heal|combat",
        }.get(category, r"play|use|apply|reward|damage|power")
        method_candidates = []
        for ordinal, method in enumerate(data.get("methods") or []):
            if not isinstance(method, dict):
                continue
            joined = " ".join(
                [str(method.get("name") or "")]
                + [str(value) for key in behavior_fields
                   for value in (method.get(key) or [])]
            )
            if not re.search(method_pattern, joined, re.I):
                continue
            name = str(method.get("name") or "")
            if category == "monsters":
                if name.casefold() == "generatemovestatemachine":
                    priority = (0, 0, ordinal)
                elif re.search(r"move(?:async)?$", name, re.I):
                    # Growth/phase moves carry state mutations and are more
                    # informative than branched moves, which in turn are more
                    # informative than otherwise equivalent attack moves.
                    detail_rank = (
                        0 if method.get("mutations")
                        else 1 if _control_flow_has_structure(method.get("control_flow"))
                        else 2
                    )
                    priority = (1, detail_rank, ordinal)
                else:
                    priority = (2, 0, ordinal)
            else:
                priority = (0, 0, ordinal)
            method_candidates.append((priority, method))

        methods = []
        for _priority, method in sorted(method_candidates, key=lambda item: item[0]):
            compact = {"name": method.get("name")}
            for field in behavior_fields:
                values = _bounded_behavior_values(field, method.get(field))
                if values:
                    compact[field] = values
            if _control_flow_has_structure(method.get("control_flow")):
                compact["control_flow"] = _bounded_control_flow(method.get("control_flow"))
            methods.append(compact)
            if len(methods) >= 3:
                break
        constructors = []
        for constructor in (data.get("constructors") or [])[:3]:
            compact_constructor = {
                "kind": constructor.get("kind"),
                "initializer": _clip(constructor.get("initializer")),
            }
            for field in behavior_fields:
                values = _bounded_behavior_values(field, constructor.get(field))
                if values:
                    compact_constructor[field] = values
            if _control_flow_has_structure(constructor.get("control_flow")):
                compact_constructor["control_flow"] = _bounded_control_flow(
                    constructor.get("control_flow"))
            constructors.append(compact_constructor)
        return {
            "properties": properties[:10],
            "constants": constants[:6],
            "constructors": constructors,
            "methods": methods,
        }

    def entity_digest(self, category: str, record_id: Any) -> dict[str, Any] | None:
        fact = self.lookup(category, record_id)
        if not fact:
            return None
        result: dict[str, Any] = {"id": fact["id"], "type_name": fact.get("type_name")}
        if fact.get("runtime"):
            result["runtime"] = self._runtime_highlights(category, fact["runtime"])
        if fact.get("mechanics"):
            result["mechanics"] = self._mechanics_highlights(category, fact["mechanics"])
            declaring = fact.get("type_name")
            nested = []
            if declaring:
                for envelope in self.mechanics_records(category).values():
                    data = envelope.get("data") or {}
                    if data.get("declaring_type_name") != declaring:
                        continue
                    nested.append({
                        "type_name": envelope.get("type_name"),
                        "facts": self._mechanics_highlights(category, data),
                    })
                    if len(nested) >= 2:
                        break
            if nested:
                result["nested_types"] = nested
        return result

    def review_digest(
        self,
        stats: dict[str, Any],
        texts: Iterable[Any] = (),
        *,
        limits: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Build a deterministic, bounded set of native facts relevant to a review."""
        limits = {"cards": 4, "monsters": 3, "relics": 2, "potions": 2, "events": 1,
                  **(limits or {})}
        selected = self.ids_mentioned(texts)

        card_rows = []
        for card_id, row in (stats.get("cards") or {}).items():
            if not isinstance(row, dict):
                continue
            card_rows.append((
                1 if int(row.get("picked", 0) or 0) > 0 and int(row.get("plays", 0) or 0) == 0 else 0,
                int(row.get("picked", 0) or 0),
                abs(float(row.get("bias", 0.0) or 0.0)),
                _entity_id(card_id),
            ))
        for _zero_play, _picked, _bias, card_id in sorted(card_rows, reverse=True):
            if card_id in self.runtime_records("cards"):
                selected["cards"].add(card_id)
            if len(selected["cards"]) >= limits["cards"]:
                break

        enemy_rows = sorted(
            ((int((row or {}).get("deaths", 0) or 0),
              float((row or {}).get("hp_lost_sum", 0.0) or 0.0), str(comp))
             for comp, row in (stats.get("enemies") or {}).items() if isinstance(row, dict)),
            reverse=True,
        )
        monster_ids = self.runtime_records("monsters")
        for _deaths, _loss, comp in enemy_rows:
            comp_upper = comp.upper()
            for monster_id in monster_ids:
                if monster_id in comp_upper:
                    selected["monsters"].add(monster_id)
            if len(selected["monsters"]) >= limits["monsters"]:
                break

        for event_id, rows in (stats.get("events") or {}).items():
            if rows and _entity_id(event_id) in self.runtime_records("events"):
                selected["events"].add(_entity_id(event_id))

        for relic_id, row in sorted((stats.get("relics") or {}).items(),
                                    key=lambda item: int((item[1] or {}).get("picked", 0) or 0)
                                    if isinstance(item[1], dict) else 0, reverse=True):
            if _entity_id(relic_id) in self.runtime_records("relics"):
                selected["relics"].add(_entity_id(relic_id))

        entities: dict[str, list[dict[str, Any]]] = {}
        for category in CORE_CATEGORIES:
            rows = []
            for record_id in sorted(selected.get(category, set()))[:limits[category]]:
                digest = self.entity_digest(category, record_id)
                if digest:
                    rows.append(digest)
            entities[category] = rows

        snapshot = self.snapshot_dir
        return {
            "snapshot": self.status_digest(),
            "entities": entities,
            "corpus_paths": ({
                "manifest": str((snapshot / "manifest.json").as_posix()),
                "runtime": str((snapshot / "runtime" / "<category>.jsonl").as_posix()),
                "mechanics": str((snapshot / "mechanics" / "<category>.jsonl").as_posix()),
                "joins": str((snapshot / "catalog" / "runtime-mechanics-joins.jsonl").as_posix()),
                "localization": str((snapshot / "localization" / "{eng,zhs}" / "<file>.json").as_posix()),
            } if snapshot else {}),
        }
