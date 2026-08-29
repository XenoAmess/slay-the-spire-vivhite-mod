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

    def _closed_quarantine(self, target: str, attempts: list[str],
                           queue_ids: list[str]) -> tuple[Path, dict]:
        quarantine = self.salvage / f"{llm_review._CLOSED_SALVAGE_PREFIX}{target}"
        quarantine.mkdir(parents=True)
        manifest = {
            "time": "2026-08-29 11:41:20",
            "batch_runs": [808, 809, 810, 811, 812],
            "pre_head": "a" * 40,
            "model": "opencode-go/glm-5.3-flash@max",
            "failure_kind": "stall",
            "replay_enqueue_pending": True,
            "replay_target": target,
            "replay_role": "target",
            "replay_attempt_packages": attempts,
            "replay_queue_ids": queue_ids,
            "retry_resolution": "no_valid_change",
            "retry_resolution_target": target,
            "retry_resolution_lineage": [target, *attempts],
            "retry_resolution_commit": "c" * 40,
            "retry_resolution_state": "quarantined_pending_ledger",
            "retry_resolution_evidence_complete": True,
            "retry_resolution_evidence_schema": (
                llm_review._RETRY_SANDBOX_EVIDENCE_SCHEMA),
        }
        (quarantine / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return quarantine, manifest

    def _pending_replay_queue(self, target: str, queue_ids: list[str]) -> None:
        payload = {
            "pending": [{
                "run": run,
                "time": "2026-08-29 11:47:00",
                "queue_id": queue_id,
                "retry_group": target,
                "replay_target": target,
                "salvage_packages": [target],
            } for run, queue_id in zip(
                [808, 809, 810, 811, 812], queue_ids)],
            "reviewing": None,
        }
        self.queue.parent.mkdir(parents=True, exist_ok=True)
        self.queue.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

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

    def test_nested_rmdir_failure_then_startup_does_not_revive_closed_hold(self) -> None:
        target = "pkg-target"
        attempts = ["pkg-attempt-1", "pkg-attempt-2"]
        queue_ids = [f"closed-{run}" for run in range(808, 813)]
        self._package(target, target=target, role="target", attempts=attempts)
        for name in attempts:
            self._package(name, target=target, role="attempt_evidence")
        quarantine, manifest = self._closed_quarantine(target, attempts, queue_ids)
        skins = quarantine / "raw_sandbox" / "repo" / "Vivhite" / "skins"
        skins.mkdir(parents=True)
        (skins / "atlas.png").write_bytes(b"evidence")
        self._pending_replay_queue(target, queue_ids)
        original_rmdir = Path.rmdir
        failed_once = False

        def fail_nested_once(path: Path):
            nonlocal failed_once
            if path == skins and not failed_once:
                failed_once = True
                raise OSError(145, "The directory is not empty")
            return original_rmdir(path)

        with (mock.patch.object(llm_review, "_review_stop_requested",
                                return_value=False),
              mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_exact_status",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_contains",
                                return_value=True),
              mock.patch.object(llm_review, "_update_rejection_ledger",
                                return_value=True),
              mock.patch.object(Path, "rmdir", fail_nested_once)):
            self.assertFalse(llm_review._finish_quarantined_salvage(
                quarantine, target, manifest, log=lambda _message: None))

        receipt = llm_review._read_review_hold_closure(target)
        self.assertEqual(receipt["commit"], "c" * 40)
        self.assertEqual(receipt["evidence_schema"],
                         llm_review._RETRY_SANDBOX_EVIDENCE_SCHEMA)
        self.assertTrue(quarantine.is_dir())

        with (mock.patch.object(llm_review, "_review_stop_requested",
                                return_value=False),
              mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_exact_status",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_contains",
                                return_value=True),
              mock.patch.object(llm_review, "_update_rejection_ledger",
                                return_value=True)):
            recovered = llm_review._recover_review_holds(
                log=lambda _message: None)
            llm_review._recover_salvage_replay_queue(
                log=lambda _message: None)
            llm_review._resume_host_salvage_closures(
                log=lambda _message: None)

        self.assertEqual(recovered, [])
        self.assertFalse((self.salvage / target).exists())
        self.assertFalse(quarantine.exists())
        queue = json.loads(self.queue.read_text(encoding="utf-8"))
        self.assertEqual(queue["pending"], [])
        self.assertTrue((self.hold / target / "manifest.json").is_file())

    def test_empty_quarantine_tail_does_not_revive_closed_hold(self) -> None:
        target = "pkg-target"
        queue_ids = [f"empty-{run}" for run in range(808, 813)]
        self._package(target, target=target, role="target", attempts=[])
        quarantine, manifest = self._closed_quarantine(target, [], queue_ids)
        self._pending_replay_queue(target, queue_ids)
        original_rmdir = Path.rmdir
        failed_once = False

        def fail_root_once(path: Path):
            nonlocal failed_once
            if path == quarantine and not failed_once:
                failed_once = True
                raise OSError(145, "The directory is not empty")
            return original_rmdir(path)

        with (mock.patch.object(llm_review, "_review_stop_requested",
                                return_value=False),
              mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_exact_status",
                                return_value=True),
              mock.patch.object(llm_review, "_update_rejection_ledger",
                                return_value=True),
              mock.patch.object(Path, "rmdir", fail_root_once)):
            self.assertFalse(llm_review._finish_quarantined_salvage(
                quarantine, target, manifest, log=lambda _message: None))

        self.assertTrue(quarantine.is_dir())
        self.assertEqual(list(quarantine.iterdir()), [])
        with (mock.patch.object(llm_review, "_review_stop_requested",
                                return_value=False),
              mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_exact_status",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_contains",
                                return_value=True)):
            recovered = llm_review._recover_review_holds(
                log=lambda _message: None)
            llm_review._recover_salvage_replay_queue(
                log=lambda _message: None)
            llm_review._resume_host_salvage_closures(
                log=lambda _message: None)

        self.assertEqual(recovered, [])
        self.assertFalse((self.salvage / target).exists())
        self.assertFalse(quarantine.exists())
        queue = json.loads(self.queue.read_text(encoding="utf-8"))
        self.assertEqual(queue["pending"], [])

    def test_confirmed_receipt_consumes_stale_active_target_without_requeue(self) -> None:
        target = "pkg-target"
        queue_ids = ["stale-active"]
        active = self._package(target, target=target, role="target", attempts=[])
        manifest = json.loads((active / "manifest.json").read_text(
            encoding="utf-8"))
        manifest["replay_queue_ids"] = queue_ids
        (active / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        restored = llm_review._restore_review_hold_package(
            active, log=lambda _message: None)
        self.assertEqual(restored, self.salvage / target)
        receipt_path = llm_review._review_hold_closure_path(target)
        assert receipt_path is not None
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_text(json.dumps({
            "schema": llm_review._REVIEW_HOLD_CLOSURE_SCHEMA,
            "target": target,
            "lineage": [target],
            "resolution": "no_valid_change",
            "commit": "c" * 40,
            "evidence_complete": True,
            "evidence_schema": llm_review._RETRY_SANDBOX_EVIDENCE_SCHEMA,
            "ledger_status": "GLM 复审确认无有效成果并闭环 `cccccccc`",
            "queue_ids": queue_ids,
        }), encoding="utf-8")
        self._pending_replay_queue(target, queue_ids)

        with (mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_exact_status",
                                return_value=True)):
            llm_review._recover_review_holds(log=lambda _message: None)
            llm_review._recover_salvage_replay_queue(
                log=lambda _message: None)

        queue = json.loads(self.queue.read_text(encoding="utf-8"))
        self.assertEqual(queue["pending"], [])

    def test_old_receipt_does_not_consume_active_new_attempt(self) -> None:
        target = "pkg-target"
        queue_ids = ["active-new-attempt"]
        held = self._package(target, target=target, role="target", attempts=[])
        restored = llm_review._restore_review_hold_package(
            held, log=lambda _message: None)
        self.assertEqual(restored, self.salvage / target)
        new_attempt = "pkg-active-new-attempt"
        attempt = self.salvage / new_attempt
        attempt.mkdir()
        (attempt / "manifest.json").write_text(json.dumps({
            "replay_enqueue_pending": True,
            "replay_target": target,
            "replay_role": "attempt_evidence",
        }), encoding="utf-8")
        receipt_path = llm_review._review_hold_closure_path(target)
        assert receipt_path is not None
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_text(json.dumps({
            "schema": llm_review._REVIEW_HOLD_CLOSURE_SCHEMA,
            "target": target,
            "lineage": [target],
            "resolution": "no_valid_change",
            "commit": "c" * 40,
            "evidence_complete": True,
            "evidence_schema": llm_review._RETRY_SANDBOX_EVIDENCE_SCHEMA,
            "ledger_status": "GLM 复审确认无有效成果并闭环 `cccccccc`",
            "queue_ids": queue_ids,
        }), encoding="utf-8")
        self._pending_replay_queue(target, queue_ids)

        with (mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_exact_status",
                                return_value=True)):
            self.assertTrue((self.salvage / new_attempt).is_dir())
            llm_review._recover_review_holds(log=lambda _message: None)
            llm_review._recover_salvage_replay_queue(
                log=lambda _message: None)

        queue = json.loads(self.queue.read_text(encoding="utf-8"))
        self.assertEqual(len(queue["pending"]), 1)
        self.assertTrue(all(
            item["salvage_attempts"] == [new_attempt]
            for item in queue["pending"]))

    def test_old_receipt_does_not_consume_queue_with_new_attempt_reference(self) -> None:
        target = "pkg-target"
        queue_ids = ["queue-new-attempt"]
        held = self._package(target, target=target, role="target", attempts=[])
        llm_review._restore_review_hold_package(held, log=lambda _message: None)
        receipt_path = llm_review._review_hold_closure_path(target)
        assert receipt_path is not None
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_text(json.dumps({
            "schema": llm_review._REVIEW_HOLD_CLOSURE_SCHEMA,
            "target": target,
            "lineage": [target],
            "resolution": "no_valid_change",
            "commit": "c" * 40,
            "evidence_complete": True,
            "evidence_schema": llm_review._RETRY_SANDBOX_EVIDENCE_SCHEMA,
            "ledger_status": "GLM 复审确认无有效成果并闭环 `cccccccc`",
            "queue_ids": queue_ids,
        }), encoding="utf-8")
        self._pending_replay_queue(target, queue_ids)
        queue = json.loads(self.queue.read_text(encoding="utf-8"))
        for item in queue["pending"]:
            item["salvage_attempts"] = ["pkg-queue-new-attempt"]
        self.queue.write_text(
            json.dumps(queue, ensure_ascii=False), encoding="utf-8")

        with (mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_exact_status",
                                return_value=True)):
            llm_review._recover_salvage_replay_queue(
                log=lambda _message: None)

        queue = json.loads(self.queue.read_text(encoding="utf-8"))
        self.assertEqual(len(queue["pending"]), 1)
        self.assertTrue(all(
            item["salvage_attempts"] == ["pkg-queue-new-attempt"]
            for item in queue["pending"]))

    def test_empty_attempt_quarantine_uses_target_lineage_receipt(self) -> None:
        target = "pkg-target"
        attempt = "pkg-attempt"
        self._package(target, target=target, role="target", attempts=[attempt])
        self._package(attempt, target=target, role="attempt_evidence")
        receipt_path = llm_review._review_hold_closure_path(target)
        assert receipt_path is not None
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_text(json.dumps({
            "schema": llm_review._REVIEW_HOLD_CLOSURE_SCHEMA,
            "target": target,
            "lineage": [target, attempt],
            "resolution": "no_valid_change",
            "commit": "c" * 40,
            "evidence_complete": True,
            "evidence_schema": llm_review._RETRY_SANDBOX_EVIDENCE_SCHEMA,
            "ledger_status": "GLM 复审确认无有效成果并闭环 `cccccccc`",
        }), encoding="utf-8")
        quarantine = self.salvage / f"{llm_review._CLOSED_SALVAGE_PREFIX}{attempt}"
        quarantine.mkdir(parents=True)

        with (mock.patch.object(llm_review, "_review_stop_requested",
                                return_value=False),
              mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_exact_status",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_terminal_closure",
                                return_value=False)):
            llm_review._resume_host_salvage_closures(
                log=lambda _message: None)

        self.assertFalse(quarantine.exists())

    def test_old_receipt_does_not_hide_new_attempt_in_same_hold_lineage(self) -> None:
        target = "pkg-target"
        self._package(target, target=target, role="target", attempts=[])
        receipt_path = llm_review._review_hold_closure_path(target)
        assert receipt_path is not None
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_text(json.dumps({
            "schema": llm_review._REVIEW_HOLD_CLOSURE_SCHEMA,
            "target": target,
            "lineage": [target],
            "resolution": "no_valid_change",
            "commit": "c" * 40,
            "evidence_complete": True,
            "evidence_schema": llm_review._RETRY_SANDBOX_EVIDENCE_SCHEMA,
            "ledger_status": "GLM 复审确认无有效成果并闭环 `cccccccc`",
        }), encoding="utf-8")
        new_attempt = "pkg-new-attempt"
        self._package(new_attempt, target=target, role="attempt_evidence")

        with (mock.patch.object(llm_review, "_review_stop_requested",
                                return_value=False),
              mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_exact_status",
                                return_value=True)):
            recovered = llm_review._recover_review_holds(
                log=lambda _message: None)

        self.assertEqual(set(recovered), {target, new_attempt})
        self.assertTrue((self.salvage / target).is_dir())
        self.assertTrue((self.salvage / new_attempt).is_dir())

    def test_closure_receipt_without_full_evidence_schema_does_not_hide_old_hold(self) -> None:
        target = "pkg-target"
        self._package(target, target=target, role="target", attempts=[])
        receipt_path = llm_review._review_hold_closure_path(target)
        assert receipt_path is not None
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_text(json.dumps({
            "schema": llm_review._REVIEW_HOLD_CLOSURE_SCHEMA,
            "target": target,
            "lineage": [target],
            "resolution": "no_valid_change",
            "commit": "c" * 40,
            "evidence_complete": True,
            "evidence_schema": 0,
            "ledger_status": "GLM 复审确认无有效成果并闭环 `cccccccc`",
        }), encoding="utf-8")

        with (mock.patch.object(llm_review, "_review_stop_requested",
                                return_value=False),
              mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_upstream_ledger_has_exact_status",
                                return_value=True)):
            recovered = llm_review._recover_review_holds(
                log=lambda _message: None)

        self.assertEqual(recovered, [target])
        active = json.loads((self.salvage / target / "manifest.json").read_text(
            encoding="utf-8"))
        self.assertTrue(active["replay_enqueue_pending"])
        self.assertNotIn("retry_resolution", active)

    def test_blocked_committed_receipt_does_not_log_false_recovery(self) -> None:
        target = "pkg-target"
        self._package(target, target=target, role="target", attempts=[])
        with mock.patch.object(llm_review, "_review_stop_requested", return_value=False):
            llm_review._recover_review_holds(log=lambda _message: None)
        messages: list[str] = []
        with (mock.patch.object(llm_review, "_review_stop_requested",
                                return_value=False),
              mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_committed_retry_resolutions",
                                return_value={
                                    target: ("no_valid_change", "c" * 40),
                                })):
            recovered = llm_review._recover_committed_retry_resolutions(
                log=messages.append)

        self.assertEqual(recovered, [])
        self.assertTrue(any("缺少完整证据 schema" in message
                            for message in messages))
        self.assertFalse(any("已从上游提交" in message for message in messages))

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
