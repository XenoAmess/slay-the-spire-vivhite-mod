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


if __name__ == "__main__":
    unittest.main()
