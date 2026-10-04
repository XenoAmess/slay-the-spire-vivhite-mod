"""Bounded, reversible prompt views of persisted review evidence.

This module never changes the source packet or persisted knowledge, and does
not decide whether a review may run.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from typing import Any


PACKET_CHAR_BUDGET = 200_000


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


@dataclass
class _Reduction:
    path: tuple[str | int, ...]
    value: Any
    saved: int
    tail: bool = False

    @property
    def priority(self) -> tuple[int, int]:
        # The primary failed run is the most useful causal evidence. Spend
        # discretionary history/statistics space before cutting its recent tail.
        # A multiplier cannot express that order: one large decision cut can
        # still outweigh all the individually small historical summaries.
        if self.path[0] == "decision_chain_evidence":
            return (0, self.saved)
        if self.path[0] == "failed_review_replay":
            return (1, self.saved)
        return (2, self.saved)


def _half(path: tuple, value: Any, *, tail: bool = False) -> _Reduction | None:
    if isinstance(value, (str, list)) and value:
        count = len(value) // 2
        reduced = value[-count:] if tail and count else value[:count]
    elif isinstance(value, dict) and value:
        reduced = dict(list(value.items())[:len(value) // 2])
    else:
        return None
    saved = _size(value) - _size(reduced)
    return _Reduction(path, reduced, saved, tail=tail) if saved > 0 else None


_SUMMARY_IDENTITY = frozenset({
    "profile_id", "run_id", "run_number", "evidence_match", "evidence_file",
    "victory", "floor", "ascension", "decisions", "combat_notes_total",
    "key_reasons_total", "human_assisted", "excluded_from_learning",
})
_REPLAY_TEXT_FIELDS = ("manifest", "inventory", "report", "candidate_patch")
_PROTECTED_ROOTS = frozenset({
    "profile_id", "run_evidence_scope", "review_closure", "packet_budget_note",
})
_SOURCES = {
    "runs_summary": "this profile's runs/*.json (or archive/run_catalog.jsonl)",
    "decision_chain_evidence": "full_failure_run.full_chain_available_in",
    "stats_digest": "this profile's stats.json, policy.json and progression.json",
    "recent_review_context": "this profile's meta_review.md",
    "historical_zero_code_debt": "this profile's meta_review.md",
    "failed_review_replay": "failed_review_replay.complete_evidence.index",
    "native_game_knowledge": "native_game_knowledge.corpus_paths",
}


def _identity_key(key: str) -> bool:
    return (key.endswith(("_id", "_ids")) or "receipt" in key
            or "missing" in key or key in ("batch_runs", "run_number"))


def _summary_reduction(value: list) -> _Reduction | None:
    """Shrink batch excerpts together while retaining every run's identity."""
    rows = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            rows.append(row)
            continue
        reduced = dict(row)
        for key, item in row.items():
            if key not in _SUMMARY_IDENTITY and not _identity_key(key):
                reduction = _half(("runs_summary", index, key), item, tail=True)
                if reduction is not None:
                    reduced[key] = reduction.value
        rows.append(reduced)
    saved = _size(value) - _size(rows)
    return _Reduction(("runs_summary",), rows, saved) if saved > 0 else None


def _reductions(packet: dict):
    """Yield only payload reductions; identity and recovery metadata stay exact."""
    for root, value in packet.items():
        if root in _PROTECTED_ROOTS or _identity_key(root):
            continue
        if root == "runs_summary" and isinstance(value, list):
            # A 100-run batch can have hundreds of small excerpts. Group their
            # reductions so protecting the failure chain does not require
            # hundreds of complete packet measurements. Never drop a run.
            yield _summary_reduction(value)
        elif root == "decision_chain_evidence" and isinstance(value, dict):
            full = value.get("full_failure_run")
            if isinstance(full, dict):
                yield _half((root, "full_failure_run", "decisions"),
                            full.get("decisions"), tail=True)
                yield _half((root, "full_failure_run", "decision_aggregates"),
                            full.get("decision_aggregates"))
        elif root == "failed_review_replay" and isinstance(value, dict):
            for index, row in enumerate(value.get("packages") or []):
                if isinstance(row, dict):
                    for key in _REPLAY_TEXT_FIELDS:
                        yield _half((root, "packages", index, key),
                                    row.get(key), tail=True)
        elif root in ("stats_digest", "native_game_knowledge") and isinstance(value, dict):
            for key, item in value.items():
                if (key not in ("snapshot", "corpus_paths", "long_tail_available_in")
                        and not _identity_key(key)):
                    yield _half((root, key), item)
        else:
            yield _half((root,), value, tail=True)


def _get(packet: dict, path: tuple):
    for key in path:
        packet = packet[key]
    return packet


def _set(packet: dict, path: tuple, value: Any) -> None:
    parent = _get(packet, path[:-1])
    parent[path[-1]] = value
    if path[0] == "failed_review_replay":
        parent[path[-1] + "_truncated"] = True


def _update_failure_chain(packet: dict, original: dict) -> None:
    chain = packet.get("decision_chain_evidence")
    original_chain = original.get("decision_chain_evidence")
    if not isinstance(chain, dict) or not isinstance(original_chain, dict):
        return
    full = chain.get("full_failure_run")
    source = original_chain.get("full_failure_run")
    if not isinstance(full, dict) or not isinstance(source, dict):
        return
    rows = full.get("decisions")
    source_rows = source.get("decisions")
    if not isinstance(rows, list) or not isinstance(source_rows, list):
        return
    removed = len(source_rows) - len(rows)
    if removed:
        original_omitted = int(source.get("omitted_decisions") or 0)
        total = max(int(source.get("decision_count") or 0),
                    len(source_rows) + original_omitted)
        full.update({
            "decision_count": total,
            "kept_decisions": len(rows),
            "omitted_decisions": total - len(rows),
            "serialized_chars": _size(rows),
            "complete_persisted_chain": False,
            "packet_budget_omitted_decisions": removed,
            "decision_aggregates_scope": "before packet budget trimming",
        })
        if not full.get("full_chain_available_in"):
            filename = source.get("evidence_file")
            full["full_chain_available_in"] = (
                f"runs/{filename}" if filename else
                "this profile's runs/*.json or archive/run_catalog.jsonl; match run_id")
    aggregates = full.get("decision_aggregates")
    source_aggregates = source.get("decision_aggregates")
    if isinstance(aggregates, list) and isinstance(source_aggregates, list):
        if len(aggregates) != len(source_aggregates):
            full["packet_budget_omitted_aggregates"] = len(source_aggregates) - len(aggregates)


def _budget_note(packet: dict, original: dict, budget: int,
                 original_chars: int, roots: set[str]) -> int:
    note = {
        "version": 1,
        "budget_chars": budget,
        "original_chars": original_chars,
        "serialized_chars": 0,
        "truncated": True,
        "rule": "Inline excerpts are incomplete; inspect referenced evidence on demand. "
                "Trim history/statistics, then replay excerpts, then the primary failure chain. "
                "Recent narrative/decision tails are retained; statistics retain their ranked head.",
        "sections": {
            root: {
                "before_chars": _size(original[root]),
                "after_chars": _size(packet[root]),
                "available_in": _SOURCES.get(root, "original review evidence for this profile/batch"),
            }
            for root in sorted(roots)
        },
    }
    packet["packet_budget_note"] = note
    # The digits in the measurement itself are part of the serialized budget.
    while True:
        measured = _size(packet)
        if measured == note["serialized_chars"]:
            return measured
        note["serialized_chars"] = measured


def enforce_packet_budget(packet: dict, budget: int = PACKET_CHAR_BUDGET) -> dict:
    """Return an independent packet whose compact JSON is at most ``budget`` chars.

    Progressively halve bulky payloads, favoring failed-run evidence over old
    narrative and statistics. Retain whole recent
    decision rows and never dropping batch/run identity, missing-evidence state,
    failure-package inventory, or recovery references. All changes are measured
    in ``packet_budget_note``; it counts toward the limit. A tiny budget unable
    to contain even the identity/reference envelope raises ``ValueError``.
    """
    if budget < 2:
        raise ValueError("budget cannot contain a JSON object")
    result = copy.deepcopy(packet)
    original_chars = _size(result)
    if original_chars <= budget:
        return result
    changed: set[str] = set()
    choices = [item for item in _reductions(result) if item is not None]
    while True:
        if not choices:
            raise ValueError("budget cannot contain review identity and evidence references")
        # Stable iteration order breaks equal-size ties deterministically.
        choice_index = max(range(len(choices)), key=lambda index: choices[index].priority)
        reduction = choices[choice_index]
        _set(result, reduction.path, reduction.value)
        changed.add(reduction.path[0])
        _update_failure_chain(result, packet)
        if _budget_note(result, packet, budget, original_chars, changed) <= budget:
            return result
        # Reduction paths are disjoint payloads; accounting updates touch only
        # their metadata. Recompute the changed payload instead of serializing
        # every other summary again on each small historical cut.
        value = _get(result, reduction.path)
        next_reduction = (
            _summary_reduction(value) if reduction.path == ("runs_summary",)
            else _half(reduction.path, value, tail=reduction.tail))
        if next_reduction is None:
            choices.pop(choice_index)
        else:
            choices[choice_index] = next_reduction
