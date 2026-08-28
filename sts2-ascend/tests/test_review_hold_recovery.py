"""Regression coverage for operator-preserved failed-review package recovery."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402


class ReviewHoldRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-review-hold-")
        self.root = Path(self.temp.name)
        backups = self.root / "knowledge" / "code_backups"
        self.salvage = backups / "review_salvage"
        self.hold = backups / "review_hold" / "preserved-batch"
        self.queue = self.root / "knowledge" / "review_queue.json"
        self.hold.mkdir(parents=True)
        self.old_salvage = llm_review.SALVAGE_ROOT
        self.old_queue = llm_review.QUEUE_FILE
        llm_review.SALVAGE_ROOT = self.salvage
        llm_review.QUEUE_FILE = self.queue

    def tearDown(self) -> None:
        llm_review.SALVAGE_ROOT = self.old_salvage
        llm_review.QUEUE_FILE = self.old_queue
        self.temp.cleanup()

    def _package(self, name: str, *, target: str, role: str,
                 attempts: list[str] | None = None) -> Path:
        package = self.hold / name
        package.mkdir()
        manifest = {
            "time": "2026-08-28 12:00:00",
            "batch_runs": [808, 809, 810, 811, 812],
            "pre_head": "a" * 40,
            "model": "opencode-go/glm-5.3-flash@max",
            "runner": "opencode",
            "source": "preferred",
            "every": 1,
            "replay_enqueue_pending": True,
            "replay_target": target,
            "replay_role": role,
            "replay_attempt_packages": attempts if role == "target" else None,
            "retry_evidence_ready": True,
            "retry_evidence_schema": llm_review._RETRY_EVIDENCE_SCHEMA,
            "retry_candidate_patch": "retry_candidate.patch",
            "retry_candidate_inventory": "retry_candidate_inventory.json",
            "retry_candidate_bytes": 5,
            # This is the old prompt-only conclusion that hold recovery invalidates.
            "retry_resolution": "no_valid_change",
            "retry_resolution_commit": "b" * 40,
            "retry_resolution_state": "ledger_final_upstream",
        }
        (package / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        (package / "report.md").write_text("full report", encoding="utf-8")
        (package / "retry_candidate.patch").write_bytes(b"patch")
        (package / "retry_candidate_inventory.json").write_text(
            json.dumps({
                "schema": llm_review._RETRY_EVIDENCE_SCHEMA,
                "package": name,
                "pre_head": "a" * 40,
                "paths": [],
            }), encoding="utf-8")
        return package

    def test_restores_whole_lineage_and_requeues_same_model_without_deleting_hold(self) -> None:
        target = "pkg-target"
        attempts = ["pkg-attempt-1", "pkg-attempt-2", "pkg-attempt-3"]
        held = [self._package(target, target=target, role="target", attempts=attempts)]
        held.extend(self._package(name, target=target, role="attempt_evidence")
                    for name in attempts)
        original = {
            path.name: (path / "manifest.json").read_bytes() for path in held
        }

        with mock.patch.object(llm_review, "_review_stop_requested", return_value=False):
            recovered = llm_review._recover_review_holds(log=lambda _message: None)
            llm_review._recover_salvage_replay_queue(log=lambda _message: None)

        self.assertEqual(recovered, [target, *attempts])
        for name in [target, *attempts]:
            active = self.salvage / name
            self.assertTrue((active / "retry_candidate.patch").is_file())
            manifest = json.loads((active / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["replay_enqueue_pending"])
            self.assertNotIn("retry_resolution", manifest)
            self.assertNotIn("retry_resolution_commit", manifest)
            self.assertEqual(manifest["review_hold_requires_evidence_schema"],
                             llm_review._RETRY_SANDBOX_EVIDENCE_SCHEMA)
            self.assertEqual((self.hold / name / "manifest.json").read_bytes(),
                             original[name])

        queue = json.loads(self.queue.read_text(encoding="utf-8"))
        self.assertEqual(len(queue["pending"]), 5)
        for item in queue["pending"]:
            self.assertEqual(item["salvage_packages"], [target])
            self.assertEqual(item["salvage_attempts"], attempts)
            self.assertTrue(item["retry_same_model"])
            self.assertEqual(item["model"], "opencode-go/glm-5.3-flash@max")
        self.assertTrue(all((self.hold / name).is_dir()
                            for name in [target, *attempts]))

    def test_missing_declared_attempt_keeps_entire_hold_group_unpublished(self) -> None:
        target = "pkg-target"
        self._package(
            target, target=target, role="target", attempts=["pkg-attempt-missing"])

        with mock.patch.object(llm_review, "_review_stop_requested", return_value=False):
            recovered = llm_review._recover_review_holds(log=lambda _message: None)

        self.assertEqual(recovered, [])
        self.assertFalse(self.salvage.exists())
        self.assertTrue((self.hold / target / "manifest.json").is_file())

    def test_hold_alone_starts_host_recovery_worker(self) -> None:
        self._package("pkg-target", target="pkg-target", role="target", attempts=[])
        self.assertFalse(self.salvage.exists())
        self.assertTrue(llm_review._salvage_recovery_needed())


if __name__ == "__main__":
    unittest.main()
