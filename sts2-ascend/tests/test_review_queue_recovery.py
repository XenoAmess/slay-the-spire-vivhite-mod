"""Durable review handoffs and profile-local scheduler recovery, without providers."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))
import llm_review


class ProfileQueueFairnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-review-fairness-")
        root = Path(self.temp.name)
        self.bindings = tuple(
            llm_review._ReviewProfileBinding(
                llm_review._paths_for_profile(profile, root / profile), None)
            for profile in ("ironclad", "vivhite"))
        for binding in self.bindings:
            binding.paths.root.mkdir(parents=True)
            binding.paths.queue.write_text(json.dumps({
                "pending": [{"run": 2, "profile_id": binding.paths.profile_id}],
                "reviewing": None,
            }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _run_worker(self, claim_failure=False):
        stopped = False
        runs = []
        claim = llm_review._claim_profile_review_batch
        finalize = llm_review._finalize_review_batch

        def claim_one(binding, *args, **kwargs):
            if claim_failure and binding.paths.profile_id == "ironclad":
                raise llm_review.ReviewQueueError("temporary queue lock")
            return claim(binding, *args, **kwargs)

        def execute(_agent, batch, _log):
            runs.append(llm_review._batch_profile_id(batch))
            return "documented"

        def finish(*args, **kwargs):
            nonlocal stopped
            delay = finalize(*args, **kwargs)
            stopped = True
            return delay

        with ExitStack() as stack:
            for name in (
                "_kill_orphan_review_processes", "_cleanup_stale_private_git_temps",
                "_cleanup_stale_pre_provider_sandboxes", "_recover_deferred_salvages",
                "_recover_unpointed_review_sandboxes", "_recover_review_holds",
                "_recover_committed_retry_resolutions", "_recover_salvage_replay_queue",
                "_backfill_rejection_ledger", "_resume_host_salvage_closures",
            ):
                stack.enter_context(mock.patch.object(llm_review, name))
            stack.enter_context(mock.patch.object(
                llm_review, "_agent_review_profile_bindings", return_value=self.bindings))
            stack.enter_context(mock.patch.object(
                llm_review, "_review_stop_requested", side_effect=lambda: stopped))
            stack.enter_context(mock.patch.object(
                llm_review, "_wait_review_stop", side_effect=lambda _: stopped))
            stack.enter_context(mock.patch.object(
                llm_review, "load_llm_config", return_value={"enabled": True}))
            stack.enter_context(mock.patch.object(
                llm_review, "_claim_profile_review_batch", side_effect=claim_one))
            stack.enter_context(mock.patch.object(
                llm_review, "_run_batch_review", side_effect=execute))
            stack.enter_context(mock.patch.object(
                llm_review, "_finalize_review_batch", side_effect=finish))
            llm_review._worker_loop_body(
                SimpleNamespace(request_restart=False), log=lambda _: None)
        self.assertEqual(runs, ["vivhite"])
        return runs

    def test_startup_bad_profile_does_not_block_healthy_reviewing_recovery(self):
        bad = self.bindings[0].paths.queue
        bad.write_bytes(b"invalid queue JSON")
        healthy = self.bindings[1].paths.queue
        healthy.write_text(json.dumps({
            "pending": [], "reviewing": {
                "runs": [2], "profile_id": "vivhite",
                "items": [{"run": 2, "profile_id": "vivhite"}],
            },
        }), encoding="utf-8")
        self._run_worker()
        self.assertEqual(bad.read_bytes(), b"invalid queue JSON")
        self.assertIsNone(json.loads(healthy.read_text(encoding="utf-8"))["reviewing"])

    def test_claim_read_error_does_not_skip_other_profiles(self):
        original = self.bindings[0].paths.queue.read_bytes()
        self._run_worker(claim_failure=True)
        self.assertEqual(self.bindings[0].paths.queue.read_bytes(), original)

    def test_failed_profile_restores_exact_reviewing_after_unlock(self):
        binding = self.bindings[0]
        binding.paths.queue.write_bytes(b"temporarily invalid")
        self.assertFalse(llm_review._restore_profile_review_queue(binding, log=lambda _: None))
        items = [{"run": 1, "queue_id": "original", "profile_id": "ironclad"}]
        binding.paths.queue.write_text(json.dumps({
            "pending": [{"run": 2, "profile_id": "ironclad"}],
            "reviewing": {"runs": [1], "items": items, "profile_id": "ironclad"},
        }), encoding="utf-8")
        self.assertTrue(llm_review._restore_profile_review_queue(binding, log=lambda _: None))
        saved = json.loads(binding.paths.queue.read_text(encoding="utf-8"))
        self.assertIsNone(saved["reviewing"])
        self.assertEqual(saved["pending"][0], items[0])


class AccumulationConfigTests(unittest.TestCase):
    @staticmethod
    def _item():
        return {
            "run": 1, "profile_id": "ironclad", "runner": "opencode",
            "model": "kimi-old", "backend_key": "old", "every": 5,
            "retry_same_model": False, "deferred_kind": "batch_accumulation",
        }

    def test_changed_config_releases_one_run_from_old_five_run_cadence(self):
        cfg = {"review_model_chain": [{
            "key": "new", "runner": "codex", "model": "new-model", "every_runs": 1,
        }]}
        item = self._item()
        self.assertEqual(llm_review._select_review_batch([item], 100, 1000, cfg), ([0], 0.0))
        self.assertTrue(llm_review._refresh_accumulation_plans([item], cfg))
        self.assertEqual((item["backend_key"], item["every"]), ("new", 1))
        self.assertFalse(item["retry_same_model"])

    def test_unchanged_plan_keeps_minimum_and_attempted_binding_unchanged(self):
        cfg = {"review_model_chain": [{
            "key": "old", "runner": "opencode", "model": "kimi-old", "every_runs": 5,
        }]}
        item = self._item()
        self.assertEqual(llm_review._select_review_batch([item], 100, 1000, cfg), ([], 5.0))
        item["retry_same_model"] = True
        original = dict(item)
        self.assertFalse(llm_review._refresh_accumulation_plans([item], cfg))
        self.assertEqual(item, original)

    def test_explicit_disabled_chain_resolves_unavailable_without_probes(self):
        cfg = {"review_model_chain": [{
            "key": "off", "model": "provider/off", "enabled": False,
        }]}
        # The runner normalizer's explicit-disable change is merged separately.
        with (mock.patch.object(llm_review, "review_plans_from_config", return_value=[]),
              mock.patch.object(llm_review, "runner_binary") as binary,
              mock.patch.object(llm_review, "_query_available_models") as query):
            plan = llm_review.resolve_review_plan(cfg, log=lambda _: None)
        self.assertFalse(plan.available)
        binary.assert_not_called()
        query.assert_not_called()


class TerminalReviewHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-review-handoff-")
        self.root = Path(self.temp.name)
        (self.root / "runs").mkdir()
        self.cfg = {"enabled": True, "review_model_chain": [{
            "key": "audit", "runner": "opencode", "model": "audit", "every_runs": 1,
        }]}
        self.know = SimpleNamespace(
            root=self.root, profile_id="ironclad", stats={"global": {"runs": 10}},
            progression={"last_llm_review_run": 9, "review_epoch": "epoch-a"},
            save=mock.Mock(),
            _run_log_path=lambda run_id: self.root / "runs" / (run_id + ".json"))
        self.agent = SimpleNamespace(
            know=self.know, profile_id="ironclad", ctx=SimpleNamespace(run_id="run-10"))
        self.binding = llm_review._ReviewProfileBinding(
            llm_review._paths_for_profile("ironclad", self.root, self.know), self.know)
        self.patches = ExitStack()
        self.patches.enter_context(mock.patch.object(llm_review, "load_llm_config", return_value=self.cfg))
        self.patches.enter_context(mock.patch.object(llm_review, "_latest_profile_reset_info", return_value=None))
        self.patches.enter_context(mock.patch.object(llm_review, "_ensure_worker"))
        self.patches.enter_context(mock.patch.object(llm_review, "_review_stop_requested", return_value=False))

    def tearDown(self):
        self.patches.close()
        self.temp.cleanup()

    def _archive(self, run_id="run-10", run_number=10, **extra):
        self.agent.ctx.run_id = run_id
        payload = {"run_id": run_id, "run_number": run_number, "profile_id": "ironclad",
                   "floor": 5, "decisions": [{"screen": "GAME_OVER"}], **extra}
        handoff = llm_review.terminal_review_handoff(self.agent, payload)
        if handoff is not None:
            payload["review_handoff"] = handoff
        path = self.root / "runs" / (run_id + ".json")
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path, payload

    def _queue(self):
        with llm_review._review_profile_paths_scope(self.binding.paths):
            return llm_review._load_queue_unlocked()

    def test_failed_enqueue_is_recovered_with_next_run_and_after_restart(self):
        first, _ = self._archive()
        with mock.patch.object(llm_review, "_save_queue_unlocked", side_effect=llm_review.ReviewQueueError("locked")):
            llm_review.enqueue_review(self.agent, log=lambda _: None)
        self.assertEqual(self.know.progression["last_llm_review_run"], 9)
        self.assertEqual(json.loads(first.read_text())["review_handoff"]["state"], "pending")
        self.know.stats["global"]["runs"] = 11
        second, _ = self._archive("run-11", 11)
        llm_review.enqueue_review(self.agent, log=lambda _: None)
        llm_review._terminal_handoff_scan_cache.clear()  # fresh Brain process
        self.assertEqual(llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None), 1)
        self.assertEqual(sorted(item["run"] for item in self._queue()["pending"]), [10, 11])
        self.assertEqual(llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None), 0)
        self.assertTrue(all(json.loads(p.read_text())["review_handoff"]["state"] == "queued"
                            for p in (first, second)))

    def test_startup_empty_queue_starts_worker_for_terminal_outbox(self):
        self._archive()
        llm_review._terminal_handoff_scan_cache.clear()
        with (mock.patch.object(llm_review, "_salvage_recovery_needed", return_value=False),
              mock.patch.object(llm_review, "_ensure_worker") as ensure):
            llm_review.resume_review_queue(self.agent, log=lambda _: None)
        ensure.assert_called_once()
        self.assertTrue(llm_review._restore_profile_review_queue(self.binding, log=lambda _: None))
        self.assertEqual(len(self._queue()["pending"]), 1)

    def test_archive_ack_failure_and_consumed_queue_do_not_reenqueue(self):
        path, data = self._archive()
        with (llm_review._review_profile_paths_scope(self.binding.paths),
              mock.patch.object(llm_review, "_ack_terminal_review_handoff", side_effect=OSError("archive locked"))):
            with self.assertRaises(OSError):
                llm_review._queue_terminal_review_handoff(self.binding, path, data, self.cfg, log=lambda _: None)
        q = self._queue()
        self.assertEqual(len(q["pending"]), 1)
        self.assertEqual(len(q["terminal_handoff_receipts"]), 1)
        with llm_review._review_profile_paths_scope(self.binding.paths):
            batch, _ = llm_review._claim_profile_review_batch(self.binding, self.cfg, log=lambda _: None)
            llm_review._finalize_review_batch(batch, "documented", log=lambda _: None)
        llm_review._terminal_handoff_scan_cache.clear()
        llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None)
        self.assertEqual(self._queue()["pending"], [])
        self.assertEqual(self._queue()["terminal_handoff_receipts"], {})
        self.assertEqual(json.loads(path.read_text())["review_handoff"]["state"], "queued")

    def test_cleanup_receipt_write_failure_is_retried_after_archive_ack(self):
        path, data = self._archive()
        original = llm_review._save_queue_unlocked
        calls = 0
        def save(q):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise llm_review.ReviewQueueError("receipt cleanup locked")
            return original(q)
        with (llm_review._review_profile_paths_scope(self.binding.paths),
              mock.patch.object(llm_review, "_save_queue_unlocked", side_effect=save)):
            with self.assertRaises(llm_review.ReviewQueueError):
                llm_review._queue_terminal_review_handoff(self.binding, path, data, self.cfg, log=lambda _: None)
        self.assertEqual(json.loads(path.read_text())["review_handoff"]["state"], "queued")
        llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None)
        self.assertEqual(len(self._queue()["pending"]), 1)
        self.assertEqual(self._queue()["terminal_handoff_receipts"], {})

    def test_pending_terminal_waits_for_learning_cleanup_and_excluded_runs_stay_out(self):
        self._archive()
        journal = self.root / ".active_run_learning.json"
        journal.write_text(json.dumps({"run_id": "run-10"}), encoding="utf-8")
        self.assertEqual(llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None), 0)
        llm_review.enqueue_review(self.agent, log=lambda _: None)
        self.assertEqual(self.know.progression["last_llm_review_run"], 9)
        self.assertEqual(self._queue()["pending"], [])
        journal.unlink()
        self.assertEqual(llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None), 1)
        _, excluded = self._archive("human", 11, human_assisted=True, excluded_from_learning=True)
        self.assertNotIn("review_handoff", excluded)
        self.assertEqual(llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None), 0)
        self.assertEqual(len(self._queue()["pending"]), 1)

    def test_same_numeric_run_from_distinct_epoch_and_native_identity_is_not_deduped(self):
        self._archive("old-native", 10)
        llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None)
        self.know.progression["review_epoch"] = "epoch-b"
        self._archive("new-native", 10)
        llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None)
        pending = self._queue()["pending"]
        self.assertEqual(len(pending), 2)
        self.assertEqual({item["run_id"] for item in pending}, {"old-native", "new-native"})
        self.assertEqual(len({item["queue_id"] for item in pending}), 2)

    def test_acknowledged_terminal_does_not_reenqueue_if_review_already_consumed(self):
        self._archive()
        llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None)
        with llm_review._review_profile_paths_scope(self.binding.paths):
            batch, _ = llm_review._claim_profile_review_batch(self.binding, self.cfg, log=lambda _: None)
            llm_review._finalize_review_batch(batch, "documented", log=lambda _: None)
        llm_review.enqueue_review(self.agent, log=lambda _: None)
        self.assertEqual(self._queue()["pending"], [])
        self.assertEqual(self.know.progression["last_llm_review_run"], 10)

    def test_unrelated_corrupt_archive_does_not_block_explicit_handoff(self):
        (self.root / "runs" / "bad-old.json").write_bytes(b"invalid historical file")
        self._archive()
        self.assertEqual(llm_review._recover_terminal_review_handoffs(self.binding, log=lambda _: None), 1)
        self.assertEqual(len(self._queue()["pending"]), 1)

    def test_pending_handoff_is_kept_by_offline_and_online_archive_selectors(self):
        import compact_knowledge
        scripts = str(Path(__file__).resolve().parents[1] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import compact_run_history
        path, data = self._archive()
        data["started_at"] = "2026-01-01 00:00:00"
        path.write_text(json.dumps(data), encoding="utf-8")
        options = compact_knowledge.CompactionOptions(
            keep_recent=0, keep_longest=0, keep_largest=0, keep_floor_representatives=False,
            deep_floor=100, archive_before="2026-02-01")
        records = compact_knowledge._scan_runs(self.root)
        keep = compact_knowledge._select_working_set(records, options)
        self.assertIn("review_handoff_pending", keep[path.name])
        online = compact_run_history.plan_run_archive(self.root, archive_before="2026-02-01", keep_recent=0)
        self.assertIn("review_handoff_pending", online.keep_reasons[path.name])
        self.assertEqual(online.archive_new, [])


if __name__ == "__main__":
    unittest.main()
