"""Regression coverage for operator-preserved failed-review package recovery."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
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

    def test_recovered_hold_reopens_existing_closed_ledger_rows(self) -> None:
        target = "pkg-target"
        attempt = "pkg-attempt-1"
        held = [
            self._package(target, target=target, role="target", attempts=[attempt]),
            self._package(attempt, target=target, role="attempt_evidence"),
        ]
        ledger = self.root / "REVIEW_REJECTIONS.md"
        ledger_text = llm_review._REJECTION_LEDGER_HEADER
        for package in held:
            manifest = json.loads(
                (package / "manifest.json").read_text(encoding="utf-8"))
            ledger_text += llm_review._rejection_ledger_block(
                package.name, manifest, status="historically closed",
                package_cell="closed cleanup", reason="invalid old closure")
        ledger.write_text(ledger_text, encoding="utf-8")
        commits: list[tuple[str, dict]] = []

        def fake_commit(message, **kwargs):
            commits.append((message, kwargs))
            return SimpleNamespace(
                created=True, pushed=False, commit="c" * 40, reason="")

        fake_autogit = SimpleNamespace(
            commit_progress_result=fake_commit,
            push_pending=lambda **_kwargs: True,
        )
        pending_status = "\u5f85 GLM \u91cd\u5ba1/\u8865\u5408"
        with (mock.patch.object(llm_review, "BASE_DIR", self.root),
              mock.patch.object(llm_review, "REPO_DIR", self.root),
              mock.patch.object(llm_review, "KNOWLEDGE_DIR", self.root / "knowledge"),
              mock.patch.object(llm_review, "REJECTION_LEDGER", ledger),
              mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
              mock.patch.object(llm_review, "_flush_pending_rejection_ledger",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_contains",
                                side_effect=lambda _name, status: status == pending_status),
              mock.patch.dict(sys.modules, {"autogit": fake_autogit})):
            llm_review._recover_review_holds(log=lambda _message: None)
            llm_review._backfill_rejection_ledger(log=lambda _message: None)
            # A later maintenance scan retries push without duplicating either
            # the marker or the ledger update commit.
            llm_review._backfill_rejection_ledger(log=lambda _message: None)

        updated = ledger.read_text(encoding="utf-8")
        updated_lines = updated.splitlines()
        for name in (target, attempt):
            marker = f"<!-- rejection:{name} -->"
            self.assertEqual(updated.count(marker), 1)
            self.assertTrue(
                llm_review._ledger_marker_has_status(updated, name, pending_status))
            row = updated_lines[updated_lines.index(marker) + 1]
            self.assertIn(f"review_salvage/{name}", row)
            self.assertIn("restored from review_hold", row)
            self.assertNotIn("invalid old closure", row)
        self.assertEqual(len(commits), 2)
        self.assertTrue(all(
            message.startswith("chore(sts2-ascend): reopen GLM review batch ")
            for message, _kwargs in commits))
        self.assertTrue(all(
            kwargs["paths"] == ["REVIEW_REJECTIONS.md"]
            for _message, kwargs in commits))

    def test_hold_alone_starts_host_recovery_worker(self) -> None:
        self._package("pkg-target", target="pkg-target", role="target", attempts=[])
        self.assertFalse(self.salvage.exists())
        self.assertTrue(llm_review._salvage_recovery_needed())


if __name__ == "__main__":
    unittest.main()
