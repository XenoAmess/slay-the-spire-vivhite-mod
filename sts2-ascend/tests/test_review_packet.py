"""Review context stays bounded without changing persisted evidence semantics."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))
from review_packet import enforce_packet_budget


def serialized_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def packet_fixture():
    decisions = [
        {"decision_id": f"decision-{i}", "action": "play_card", "floor": i // 3,
         "reason": f"证据 {i}: " + "结算\n\"" * 900,
         "outcome": {"status": "applied", "at": i}}
        for i in range(48)
    ]
    return {
        "profile_id": "vivhite",
        "run_evidence_scope": {
            "requested": [10, 11], "queue_identity_runs": [10, 11],
            "exact": [10], "missing": [11], "evidence_only": False,
            "fallback_is_not_batch_evidence": True,
        },
        "review_closure": {"action_required": True, "last_outcome": "report_only"},
        "runs_summary": [{
            "run_id": "stable-run-10", "run_number": 10,
            "evidence_match": "exact_batch", "decisions": 48,
            "combat_notes_total": 6, "key_reasons_total": 5,
            "combat_notes": [f"note-{i}: " + "a" * 4000 for i in range(6)],
            "key_reasons": [f"reason-{i}: " + "b" * 2000 for i in range(5)],
        }],
        "decision_chain_evidence": {
            "selection_policy": "newest_exact_failed_run_full",
            "full_failure_run": {
                "run_id": "stable-run-10", "run_number": 10,
                "evidence_file": "run-10.json", "decision_count": 48,
                "kept_decisions": 48, "omitted_decisions": 0,
                "serialized_chars": serialized_size(decisions),
                "complete_persisted_chain": True, "full_chain_available_in": None,
                "decision_aggregates": [], "decisions": decisions,
            },
        },
        "stats_digest": {
            "stats_version": 3,
            "cards": [{"id": str(i), "name": "card" * 500, "plays": 100 - i}
                      for i in range(50)],
            "events": {str(i): {"option": "e" * 1500} for i in range(50)},
        },
        "recent_review_context": "old-" * 12000 + "LATEST REVIEW",
        "historical_zero_code_debt": "old debt\n" * 3000 + "RECENT DEBT",
        "failed_review_replay": {
            "requested_packages": ["target"], "attempt_packages": ["attempt-1"],
            "complete_evidence": {"index": "retry_evidence/index.json", "required": True},
            "packages": [{
                "package": "target", "role": "target", "available": True,
                "candidate_source": "retry_candidate.patch", "auto_apply": False,
                "candidate_patch": "+ change\n" * 15000,
                "candidate_patch_bytes": 135000, "candidate_patch_truncated": False,
                "manifest": "{\"model\":\"retained-in-source\"}",
            }, {"package": "attempt-1", "role": "attempt_evidence", "available": False,
                "error": "failure package is missing; keep pending"}],
        },
        "native_game_knowledge": {
            "snapshot": {"available": True}, "corpus_paths": {"cards": "game/cards.jsonl"},
            "cards": ["native fact" * 1000] * 20,
        },
    }


class PacketBudgetTests(unittest.TestCase):
    def test_default_budget_includes_note_and_preserves_source(self):
        packet = packet_fixture()
        original = copy.deepcopy(packet)
        result = enforce_packet_budget(packet)
        self.assertLessEqual(serialized_size(result), 200_000)
        note = result["packet_budget_note"]
        self.assertEqual(note["serialized_chars"], serialized_size(result))
        self.assertEqual(note["original_chars"], serialized_size(original))
        self.assertEqual(packet, original)
        self.assertEqual(enforce_packet_budget(packet), result)

    def test_small_budget_keeps_identity_missing_evidence_and_recovery_paths(self):
        original = packet_fixture()
        result = enforce_packet_budget(original, budget=8_000)
        self.assertLessEqual(serialized_size(result), 8_000)
        for key in ("profile_id", "run_evidence_scope", "review_closure"):
            self.assertEqual(result[key], original[key])
        summary = result["runs_summary"][0]
        self.assertEqual(summary["run_id"], "stable-run-10")
        self.assertEqual(summary["combat_notes_total"], 6)
        replay = result["failed_review_replay"]
        for key in ("requested_packages", "attempt_packages", "complete_evidence"):
            self.assertEqual(replay[key], original["failed_review_replay"][key])
        self.assertEqual(replay["packages"][1], original["failed_review_replay"]["packages"][1])
        self.assertTrue(replay["packages"][0]["candidate_patch_truncated"])
        self.assertEqual(result["native_game_knowledge"]["corpus_paths"], {"cards": "game/cards.jsonl"})
        self.assertEqual(result["packet_budget_note"]["budget_chars"], 8_000)

    def test_removed_decisions_update_all_accounting_and_keep_whole_recent_rows(self):
        packet = packet_fixture()
        result = enforce_packet_budget(packet, 90_000)
        source = packet["decision_chain_evidence"]["full_failure_run"]
        full = result["decision_chain_evidence"]["full_failure_run"]
        kept = len(full["decisions"])
        self.assertGreater(kept, 0)
        self.assertLess(kept, 48)
        self.assertEqual(full["decisions"], source["decisions"][-kept:])
        self.assertEqual(full["kept_decisions"], kept)
        self.assertEqual(full["omitted_decisions"], 48 - kept)
        self.assertEqual(full["packet_budget_omitted_decisions"], 48 - kept)
        self.assertEqual(full["serialized_chars"], serialized_size(full["decisions"]))
        self.assertFalse(full["complete_persisted_chain"])
        self.assertEqual(full["full_chain_available_in"], "runs/run-10.json")

    def test_existing_omissions_and_recovery_reference_are_not_overwritten(self):
        packet = packet_fixture()
        full = packet["decision_chain_evidence"]["full_failure_run"]
        full.update(decision_count=100, omitted_decisions=52,
                    complete_persisted_chain=False,
                    full_chain_available_in="archive/exact-run-10.json.gz")
        result = enforce_packet_budget(packet, 90_000)
        actual = result["decision_chain_evidence"]["full_failure_run"]
        self.assertEqual(actual["omitted_decisions"], 100 - actual["kept_decisions"])
        self.assertEqual(actual["full_chain_available_in"], "archive/exact-run-10.json.gz")
        self.assertEqual(actual["decision_aggregates_scope"], "before packet budget trimming")

    def test_huge_unusual_section_reduces_without_unbounded_fallback(self):
        packet = {"profile_id": "test", "future_diagnostic_context": {"payload": "x" * 500_000}}
        result = enforce_packet_budget(packet, 2_000)
        self.assertLessEqual(serialized_size(result), 2_000)
        self.assertIn("future_diagnostic_context", result["packet_budget_note"]["sections"])

    def test_recent_text_retains_tail_and_noop_returns_independent_copy(self):
        result = enforce_packet_budget({"recent_review_context": "x" * 9000 + "最新结论"}, 2_000)
        self.assertTrue(result["recent_review_context"].endswith("最新结论"))
        packet = {"nested": [1, {"value": "source"}]}
        result = enforce_packet_budget(packet)
        result["nested"][1]["value"] = "changed"
        self.assertEqual(packet["nested"][1]["value"], "source")

    def test_budget_too_small_for_identity_has_clear_error(self):
        with self.assertRaisesRegex(ValueError, "identity"):
            enforce_packet_budget({"profile_id": "vivhite", "run_evidence_scope": {"missing": [11]}}, 10)
        with self.assertRaises(ValueError):
            enforce_packet_budget({}, 1)


if __name__ == "__main__":
    unittest.main()
