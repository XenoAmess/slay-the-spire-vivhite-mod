"""Fault-injection regressions for durable knowledge and review-queue I/O."""
from __future__ import annotations

from contextlib import contextmanager
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import threading
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import autogit  # noqa: E402
import knowledge  # noqa: E402
import llm_review  # noqa: E402


class KnowledgeReadSafetyTests(unittest.TestCase):
    def test_transient_read_error_retries_instead_of_returning_defaults(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-load-json-") as root:
            path = Path(root) / "stats.json"
            path.write_text('{"sentinel": 73}\n', encoding="utf-8")
            original_read = Path.read_text
            attempts = 0

            def flaky_read(value: Path, *args, **kwargs):
                nonlocal attempts
                if value == path:
                    attempts += 1
                    if attempts == 1:
                        raise PermissionError("temporary antivirus lock")
                return original_read(value, *args, **kwargs)

            with (mock.patch.object(Path, "read_text", flaky_read),
                  mock.patch.object(knowledge.time, "sleep")):
                loaded = knowledge._load_json(path, {"sentinel": 0})

            self.assertEqual(loaded, {"sentinel": 73})
            self.assertGreaterEqual(attempts, 2)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["sentinel"], 73)
            self.assertFalse(list(Path(root).glob("stats.json.broken-*")))

    def test_persistent_read_error_raises_and_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-load-json-") as root:
            path = Path(root) / "stats.json"
            original = b'{"sentinel": 91}\n'
            path.write_bytes(original)
            original_read = Path.read_text

            def denied_read(value: Path, *args, **kwargs):
                if value == path:
                    raise PermissionError("still locked")
                return original_read(value, *args, **kwargs)

            with (mock.patch.object(Path, "read_text", denied_read),
                  mock.patch.object(knowledge.time, "sleep"),
                  self.assertRaises(PermissionError)):
                knowledge._load_json(path, {"sentinel": 0})

            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(list(Path(root).glob("stats.json.broken-*")))

    def test_malformed_json_is_not_defaulted_when_quarantine_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-load-json-") as root:
            path = Path(root) / "stats.json"
            original = b'{"sentinel": broken}\n'
            path.write_bytes(original)
            original_replace = Path.replace

            def denied_replace(value: Path, target: Path):
                if value == path:
                    raise PermissionError("cannot preserve malformed source")
                return original_replace(value, target)

            with (mock.patch.object(Path, "replace", denied_replace),
                  self.assertRaises(OSError)):
                knowledge._load_json(path, {"sentinel": 0})

            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(list(Path(root).glob("stats.json.broken-*")))


class PolicyMergeTransactionTests(unittest.TestCase):
    def test_external_policy_write_cannot_land_between_read_and_replace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-policy-txn-") as root:
            repo = Path(root)
            (repo / ".git").mkdir()
            knowledge_root = repo / "sts2-ascend" / "knowledge"
            knowledge_root.mkdir(parents=True)
            policy_path = knowledge_root / "policy.json"
            policy_path.write_text(
                json.dumps({"external": 1, "local": 1}), encoding="utf-8")
            store = knowledge.Knowledge(knowledge_root, repair_phantoms=False)
            store.policy["local"] = 2

            gate = threading.Lock()
            external_holds_lock = threading.Event()
            saver_requested_lock = threading.Event()
            allow_external_write = threading.Event()
            errors: list[BaseException] = []

            @contextmanager
            def fake_repository_lock(*_args, **_kwargs):
                if threading.current_thread().name == "policy-saver":
                    saver_requested_lock.set()
                with gate:
                    yield

            def external_writer() -> None:
                try:
                    with fake_repository_lock():
                        external_holds_lock.set()
                        self.assertTrue(allow_external_write.wait(5))
                        policy_path.write_text(json.dumps({
                            "external": 9, "local": 1, "new_external_key": 44,
                        }), encoding="utf-8")
                except BaseException as exc:  # surfaced in the main test thread
                    errors.append(exc)

            def saver() -> None:
                try:
                    store._save_policy_merged()
                except BaseException as exc:
                    errors.append(exc)

            with (mock.patch.object(autogit, "REPO_DIR", repo),
                  mock.patch.object(autogit, "repository_lock", fake_repository_lock)):
                writer_thread = threading.Thread(target=external_writer)
                writer_thread.start()
                self.assertTrue(external_holds_lock.wait(5))
                save_thread = threading.Thread(target=saver, name="policy-saver")
                save_thread.start()
                self.assertTrue(saver_requested_lock.wait(5))
                self.assertTrue(save_thread.is_alive(),
                                "policy save did not wait for the external transaction")
                allow_external_write.set()
                writer_thread.join(5)
                save_thread.join(5)

            self.assertFalse(writer_thread.is_alive())
            self.assertFalse(save_thread.is_alive())
            self.assertEqual(errors, [])
            saved = json.loads(policy_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["external"], 9)
            self.assertEqual(saved["new_external_key"], 44)
            self.assertEqual(saved["local"], 2)


class ReviewQueueSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-review-queue-")
        self.queue = Path(self.temp.name) / "review_queue.json"
        self.old_queue = llm_review.QUEUE_FILE
        self.old_salvage_root = llm_review.SALVAGE_ROOT
        llm_review.QUEUE_FILE = self.queue
        llm_review.SALVAGE_ROOT = Path(self.temp.name) / "review_salvage"
        llm_review.SALVAGE_ROOT.mkdir()

    def tearDown(self) -> None:
        llm_review.QUEUE_FILE = self.old_queue
        llm_review.SALVAGE_ROOT = self.old_salvage_root
        self.temp.cleanup()

    @staticmethod
    def _payload() -> dict:
        return {
            "pending": [{"run": 10, "time": "old", "model": "m"}],
            "reviewing": {"runs": [8, 9], "started": "earlier"},
        }

    def test_transient_queue_read_retries_without_losing_work(self) -> None:
        payload = self._payload()
        self.queue.write_text(json.dumps(payload), encoding="utf-8")
        original_read = Path.read_text
        attempts = 0

        def flaky_read(value: Path, *args, **kwargs):
            nonlocal attempts
            if value == self.queue:
                attempts += 1
                if attempts == 1:
                    raise PermissionError("temporary queue lock")
            return original_read(value, *args, **kwargs)

        with (mock.patch.object(Path, "read_text", flaky_read),
              mock.patch.object(llm_review.time, "sleep")):
            loaded = llm_review._load_queue_unlocked()

        self.assertEqual(loaded, payload)
        self.assertGreaterEqual(attempts, 2)

    def test_persistent_queue_read_error_raises_and_preserves_work(self) -> None:
        payload = self._payload()
        original = (json.dumps(payload) + "\n").encode("utf-8")
        self.queue.write_bytes(original)
        original_read = Path.read_text

        def denied_read(value: Path, *args, **kwargs):
            if value == self.queue:
                raise PermissionError("queue remains locked")
            return original_read(value, *args, **kwargs)

        with (mock.patch.object(Path, "read_text", denied_read),
              mock.patch.object(llm_review.time, "sleep"),
              self.assertRaises(llm_review.ReviewQueueError)):
            llm_review._load_queue_unlocked()
        self.assertEqual(self.queue.read_bytes(), original)

    def test_invalid_schema_and_failed_replace_leave_original_queue_untouched(self) -> None:
        invalid = b'{"pending":"not-a-list","reviewing":null}\n'
        self.queue.write_bytes(invalid)
        with self.assertRaises(llm_review.ReviewQueueError):
            llm_review._load_queue_unlocked()
        self.assertEqual(self.queue.read_bytes(), invalid)

        payload = self._payload()
        original = (json.dumps(payload) + "\n").encode("utf-8")
        self.queue.write_bytes(original)
        replacement = {"pending": [{"run": 11}], "reviewing": None}
        with (mock.patch.object(llm_review.os, "replace",
                               side_effect=PermissionError("replace locked")),
              mock.patch.object(llm_review.time, "sleep"),
              self.assertRaises(llm_review.ReviewQueueError)):
            llm_review._save_queue_unlocked(replacement)
        self.assertEqual(self.queue.read_bytes(), original)
        self.assertFalse(list(self.queue.parent.glob(".review_queue.json.*.tmp")))

    def test_enqueue_failure_keeps_cadence_markers_and_existing_queue(self) -> None:
        payload = self._payload()
        original = (json.dumps(payload) + "\n").encode("utf-8")
        self.queue.write_bytes(original)
        know = SimpleNamespace(
            stats={"global": {"runs": 20}},
            progression={"last_successful_review_run": 20,
                         "last_llm_review_run": 0},
            save=mock.Mock(),
        )
        agent = SimpleNamespace(know=know)
        messages: list[str] = []
        cfg = {"enabled": True, "preferred_model": "m",
               "model": "fallback", "review_every_runs": 1,
               "review_queue_max": 10}

        with (mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
              mock.patch.object(llm_review, "resolve_review_plan",
                                return_value=("m", 1, "preferred")),
              mock.patch.object(llm_review, "_load_queue_unlocked",
                                side_effect=llm_review.ReviewQueueError("locked")),
              mock.patch.object(llm_review, "_ensure_worker") as ensure):
            llm_review.enqueue_review(agent, log=messages.append)

        self.assertEqual(know.progression["last_llm_review_run"], 0)
        self.assertNotIn("last_review_attempt_source", know.progression)
        know.save.assert_not_called()
        ensure.assert_not_called()
        self.assertEqual(self.queue.read_bytes(), original)
        self.assertTrue(any("保留原队列" in message for message in messages))

    def test_enqueue_preserves_pending_and_reviewing_then_commits_markers(self) -> None:
        payload = self._payload()
        self.queue.write_text(json.dumps(payload), encoding="utf-8")
        know = SimpleNamespace(
            stats={"global": {"runs": 20}},
            progression={"last_successful_review_run": 20,
                         "last_llm_review_run": 0},
            save=mock.Mock(),
        )
        agent = SimpleNamespace(know=know)
        cfg = {"enabled": True, "preferred_model": "m",
               "model": "fallback", "review_every_runs": 1,
               "review_queue_max": 1}

        with (mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
              mock.patch.object(llm_review, "resolve_review_plan",
                                return_value=("m", 1, "preferred")),
              mock.patch.object(llm_review, "_ensure_worker")):
            llm_review.enqueue_review(agent, log=lambda _message: None)

        saved = llm_review._load_queue_unlocked()
        self.assertEqual(saved["reviewing"], payload["reviewing"])
        self.assertEqual([item["run"] for item in saved["pending"]], [10, 20])
        self.assertEqual(know.progression["last_llm_review_run"], 20)
        self.assertEqual(know.progression["last_review_attempt_source"], "preferred")
        know.save.assert_called_once_with()

    def test_starvation_never_overrides_available_glm_preferred_plan(self) -> None:
        self.queue.write_text(json.dumps({"pending": [], "reviewing": None}),
                              encoding="utf-8")
        glm = "opencode-go/glm-5.3-flash@max"
        know = SimpleNamespace(
            stats={"global": {"runs": 20}},
            progression={"last_successful_review_run": 0,
                         "last_llm_review_run": 0,
                         "last_review_attempt_source": "preferred"},
            save=mock.Mock(),
        )
        agent = SimpleNamespace(know=know)
        cfg = {"enabled": True, "preferred_model": glm,
               "model": "kimi-for-coding/k3", "review_every_runs": 5,
               "review_queue_max": 100}

        with (mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
              mock.patch.object(llm_review, "resolve_review_plan",
                                return_value=(glm, 1, "preferred")),
              mock.patch.object(llm_review, "_ensure_worker")):
            llm_review.enqueue_review(agent, log=lambda _message: None)

        item = llm_review._load_queue_unlocked()["pending"][-1]
        self.assertEqual((item["model"], item["source"]), (glm, "preferred"))
        self.assertEqual(know.progression["last_review_attempt_source"], "preferred")

    def test_failed_batch_is_requeued_with_backoff_and_success_clears_it(self) -> None:
        payload = {
            "pending": [{"run": 11, "time": "new", "model": "next"}],
            "reviewing": {"runs": [8, 9], "started": "earlier"},
        }
        self.queue.write_text(json.dumps(payload), encoding="utf-8")
        batch = [
            {"run": 8, "time": "old", "model": "old", "source": "preferred"},
            {"run": 9, "time": "old", "model": "old", "source": "preferred"},
        ]

        with mock.patch.object(llm_review.time, "time", return_value=1000.0):
            delay = llm_review._finalize_review_batch(batch, "failed", log=lambda _msg: None)
        self.assertEqual(delay, 60.0)
        saved = llm_review._load_queue_unlocked()
        self.assertIsNone(saved["reviewing"])
        self.assertEqual([item["run"] for item in saved["pending"]], [11, 8, 9])
        self.assertEqual(saved["pending"][1]["model"], "old")
        self.assertEqual(saved["pending"][1]["source"], "preferred")
        self.assertTrue(saved["pending"][1]["retry_same_model"])
        self.assertEqual(saved["pending"][1]["retry_count"], 1)
        self.assertEqual(saved["pending"][1]["retry_after"], 1060.0)
        self.assertEqual(saved["pending"][2]["retry_count"], 1)
        self.assertNotIn("retry_count", saved)
        self.assertNotIn("retry_after", saved)

        saved["pending"] = [saved["pending"][0]]
        saved["reviewing"] = {"runs": [8, 9], "started": "retry"}
        llm_review._save_queue_unlocked(saved)
        llm_review._finalize_review_batch(batch, "completed", log=lambda _msg: None)
        completed = llm_review._load_queue_unlocked()
        self.assertIsNone(completed["reviewing"])
        self.assertEqual([item["run"] for item in completed["pending"]], [11])

    def test_queue_rejects_invalid_run_and_nonfinite_retry(self) -> None:
        for pending in (
            [{"run": 0}],
            [{"run": True}],
            [{"run": 8, "retry_after": float("inf")}],
            [{"run": 8, "retry_after": float("nan")}],
        ):
            with self.subTest(pending=pending), self.assertRaises(llm_review.ReviewQueueError):
                llm_review._validate_queue({"pending": pending, "reviewing": None})

    def test_requeue_cli_refuses_starting_or_foreground_stack(self) -> None:
        for state in ("starting", "foreground"):
            with self.subTest(state=state), tempfile.TemporaryDirectory(
                    prefix="sts2-review-session-") as root:
                base = Path(root)
                runtime = base / ".runtime"
                runtime.mkdir()
                (runtime / "session.json").write_text(
                    json.dumps({"state": state}), encoding="utf-8")
                with (mock.patch.object(llm_review, "BASE_DIR", base),
                      mock.patch.object(sys, "argv", ["llm_review.py", "--requeue", "8"]),
                      mock.patch.object(llm_review, "requeue_review_runs") as requeue,
                      self.assertRaises(SystemExit) as raised):
                    llm_review.main()
                self.assertEqual(raised.exception.code, 3)
                requeue.assert_not_called()

    def test_recovered_runs_append_without_delaying_or_duplicating_live_work(self) -> None:
        payload = {
            "pending": [{"run": 11, "time": "new"}],
            "reviewing": {"runs": [12], "started": "live"},
        }
        self.queue.write_text(json.dumps(payload), encoding="utf-8")

        added = llm_review.requeue_review_runs(
            [8, 11, 12, 8, -1, 9], log=lambda _message: None)

        self.assertEqual(added, [8, 9])
        saved = llm_review._load_queue_unlocked()
        self.assertEqual(saved["reviewing"], payload["reviewing"])
        self.assertEqual([item["run"] for item in saved["pending"]], [11, 8, 9])

    def test_worker_supervisor_retries_failed_startup_replay_recovery(self) -> None:
        self.queue.write_text(json.dumps({"pending": [], "reviewing": None}),
                              encoding="utf-8")
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)
        attempts = 0

        def flaky_recovery(log):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise llm_review.ReviewQueueError("temporary startup queue lock")
            agent.request_restart = True

        old_started, old_thread = llm_review._worker_started, llm_review._worker_thread
        llm_review._worker_started = True
        llm_review._worker_thread = None
        try:
            with (mock.patch.object(llm_review, "_review_stop_requested",
                                   return_value=False),
                  mock.patch.object(llm_review, "_wait_review_stop", return_value=False),
                  mock.patch.object(llm_review, "_kill_orphan_review_processes"),
                  mock.patch.object(llm_review, "_recover_deferred_salvages"),
                  mock.patch.object(llm_review, "_recover_salvage_replay_queue",
                                   side_effect=flaky_recovery),
                  mock.patch.object(llm_review, "_backfill_rejection_ledger"),
                  mock.patch.object(llm_review, "load_llm_config",
                                   return_value={"enabled": True,
                                                 "review_queue_max": 100,
                                                 "max_runs_in_packet": 100})):
                llm_review._worker_loop(agent, log=lambda _message: None)
            self.assertEqual(attempts, 2)
            self.assertFalse(llm_review._worker_started)
            self.assertIsNone(llm_review._worker_thread)
        finally:
            llm_review._worker_started = old_started
            llm_review._worker_thread = old_thread

    def test_worker_skips_cooled_old_batch_for_fresh_live_evidence(self) -> None:
        payload = {
            "pending": [
                {"run": 8, "time": "old", "retry_count": 2, "retry_after": 2000.0},
                {"run": 11, "time": "live"},
            ],
            "reviewing": None,
        }
        self.queue.write_text(json.dumps(payload), encoding="utf-8")
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)
        batches: list[list[int]] = []

        def complete(_agent, batch, _log):
            batches.append([item["run"] for item in batch])
            agent.request_restart = True
            return "completed"

        with (mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
              mock.patch.object(llm_review, "_wait_review_stop", return_value=False),
              mock.patch.object(llm_review, "_kill_orphan_review_processes"),
              mock.patch.object(llm_review, "load_llm_config",
                                return_value={"review_queue_max": 1}),
              mock.patch.object(llm_review.time, "time", return_value=1000.0),
              mock.patch.object(llm_review, "_run_batch_review", side_effect=complete)):
            llm_review._worker_loop(agent, log=lambda _message: None)

        self.assertEqual(batches, [[11]])
        saved = llm_review._load_queue_unlocked()
        self.assertIsNone(saved["reviewing"])
        self.assertEqual([item["run"] for item in saved["pending"]], [8])

    def test_worker_retries_finalize_in_place_instead_of_deadlocking_reviewing(self) -> None:
        self.queue.write_text(json.dumps({
            "pending": [{"run": 8, "time": "live"}], "reviewing": None,
        }), encoding="utf-8")
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)
        original_finalize = llm_review._finalize_review_batch
        attempts = 0

        def complete(_agent, _batch, _log):
            agent.request_restart = True
            return "completed"

        def flaky_finalize(batch, outcome, log):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise llm_review.ReviewQueueError("temporary replace lock")
            return original_finalize(batch, outcome, log=log)

        with (mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
              mock.patch.object(llm_review, "_wait_review_stop", return_value=False),
              mock.patch.object(llm_review, "_kill_orphan_review_processes"),
              mock.patch.object(llm_review, "load_llm_config",
                                return_value={"review_queue_max": 1}),
              mock.patch.object(llm_review, "_run_batch_review", side_effect=complete),
              mock.patch.object(llm_review, "_finalize_review_batch",
                                side_effect=flaky_finalize)):
            llm_review._worker_loop(agent, log=lambda _message: None)

        self.assertEqual(attempts, 2)
        saved = llm_review._load_queue_unlocked()
        self.assertIsNone(saved["reviewing"])
        self.assertEqual(saved["pending"], [])

    def test_canceled_worker_leaves_reviewing_for_startup_recovery(self) -> None:
        self.queue.write_text(json.dumps({
            "pending": [{"run": 8}, {"run": 9}], "reviewing": None,
        }), encoding="utf-8")
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)

        with (mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
              mock.patch.object(llm_review, "_kill_orphan_review_processes"),
              mock.patch.object(llm_review, "load_llm_config",
                                return_value={"review_queue_max": 1}),
              mock.patch.object(llm_review, "_run_batch_review", return_value="canceled")):
            llm_review._worker_loop(agent, log=lambda _message: None)

        saved = llm_review._load_queue_unlocked()
        self.assertEqual(saved["reviewing"]["runs"], [8])
        self.assertEqual([item["run"] for item in saved["pending"]], [9])

    def test_batch_outcome_distinguishes_failure_report_and_runtime_change(self) -> None:
        batch = [{"run": 8, "model": "m", "every": 1, "source": "preferred"}]
        cfg = {"opencode_bin": "opencode"}

        def result(outcome: str, changed: bool):
            agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)

            def fake_run(*_args, **kwargs):
                kwargs["_status"].update({"outcome": outcome, "reason": outcome})
                return changed
            with (mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
                  mock.patch.object(llm_review.shutil, "which", return_value="opencode"),
                  mock.patch.object(llm_review, "run_review", side_effect=fake_run)):
                answer = llm_review._run_batch_review(agent, batch, log=lambda _msg: None)
            return answer, agent.request_restart

        self.assertEqual(result("failed", False), ("failed", False))
        self.assertEqual(result("completed", False), ("completed", False))
        self.assertEqual(result("documented", False), ("documented", False))
        self.assertEqual(result("changed", True), ("changed", True))

    def test_full_reviewing_items_must_match_runs_and_preserve_group_identity(self) -> None:
        valid = {
            "pending": [],
            "reviewing": {
                "runs": [8],
                "items": [{"run": 8, "retry_group": "pkg-a"}],
            },
        }
        self.assertIs(llm_review._validate_queue(valid), valid)
        invalid = json.loads(json.dumps(valid))
        invalid["reviewing"]["items"][0]["run"] = 9
        with self.assertRaises(llm_review.ReviewQueueError):
            llm_review._validate_queue(invalid)

        batch = [{"run": 8, "retry_group": "pkg-b"}]
        self.queue.write_text(json.dumps(valid), encoding="utf-8")
        with self.assertRaises(llm_review.ReviewQueueError):
            llm_review._finalize_review_batch(batch, "completed", log=lambda _msg: None)
        self.assertIsNotNone(llm_review._load_queue_unlocked()["reviewing"])

    def test_first_failure_can_add_retry_group_without_losing_transaction_identity(self) -> None:
        batch = [{
            "run": 8, "time": "live", "model": "glm", "every": 1,
            "source": "preferred", "queue_id": "txn-8",
        }]
        self.queue.write_text(json.dumps({
            "pending": [],
            "reviewing": {"runs": [8], "items": batch, "started": "now"},
        }), encoding="utf-8")
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)

        def fail(*_args, **kwargs):
            kwargs["_status"].update({
                "outcome": "failed", "reason": "test",
                "salvage_packages": ["pkg-first-failure"],
            })
            return False

        with (mock.patch.object(llm_review, "load_llm_config",
                               return_value={"opencode_bin": "opencode"}),
              mock.patch.object(llm_review.shutil, "which", return_value="opencode"),
              mock.patch.object(llm_review, "run_review", side_effect=fail)):
            outcome = llm_review._run_batch_review(
                agent, batch, log=lambda _message: None)
        self.assertEqual(outcome, "failed")
        llm_review._finalize_review_batch(batch, outcome, log=lambda _message: None)
        saved = llm_review._load_queue_unlocked()
        self.assertIsNone(saved["reviewing"])
        retry = saved["pending"][0]
        self.assertEqual(retry["queue_id"], "txn-8")
        self.assertEqual(retry["retry_group"], "pkg-first-failure")
        self.assertEqual(retry["salvage_packages"], ["pkg-first-failure"])
        self.assertEqual(retry["model"], "glm")

    def test_successful_code_commit_keeps_replay_pending_until_glm_receipt(self) -> None:
        batch = [{
            "run": 8, "model": "glm", "every": 1, "source": "preferred",
            "retry_group": "pkg-a", "salvage_packages": ["pkg-a"],
            "queue_id": "txn-pkg-a",
        }]
        self.queue.write_text(json.dumps({
            "pending": [],
            "reviewing": {"runs": [8], "items": batch, "started": "now"},
        }), encoding="utf-8")
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)

        def changed_without_receipt(*_args, **kwargs):
            kwargs["_status"].update({
                "outcome": "changed", "commit": "a" * 40, "pushed": True,
                "retry_resolutions": {}, "unresolved_salvage_packages": ["pkg-a"],
                "salvage_packages": ["pkg-a"],
            })
            return True

        with (mock.patch.object(llm_review, "load_llm_config",
                               return_value={"opencode_bin": "opencode"}),
              mock.patch.object(llm_review.shutil, "which", return_value="opencode"),
              mock.patch.object(llm_review, "run_review", side_effect=changed_without_receipt)):
            outcome = llm_review._run_batch_review(
                agent, batch, log=lambda _message: None)
        self.assertEqual(outcome, "replay_pending")
        self.assertTrue(agent.request_restart)
        llm_review._finalize_review_batch(batch, outcome, log=lambda _message: None)
        retry = llm_review._load_queue_unlocked()["pending"][0]
        self.assertEqual(retry["retry_group"], "pkg-a")

    def test_replay_groups_are_taken_one_by_one_without_mixing_live_runs(self) -> None:
        self.queue.write_text(json.dumps({
            "pending": [
                {"run": 11}, {"run": 12},
                {"run": 8, "retry_group": "pkg-a"},
                {"run": 9, "retry_group": "pkg-a"},
                {"run": 8, "retry_group": "pkg-b"},
                {"run": 10, "retry_group": "pkg-b"},
            ],
            "reviewing": None,
        }), encoding="utf-8")
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)
        batches: list[tuple[str, list[int]]] = []

        def complete(_agent, batch, _log):
            batches.append((str(batch[0].get("retry_group") or "live"),
                            [item["run"] for item in batch]))
            if len(batches) == 3:
                agent.request_restart = True
            return "completed"

        with (mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
              mock.patch.object(llm_review, "_wait_review_stop", return_value=False),
              mock.patch.object(llm_review, "_kill_orphan_review_processes"),
              mock.patch.object(llm_review, "_recover_deferred_salvages"),
              mock.patch.object(llm_review, "_backfill_rejection_ledger"),
              mock.patch.object(llm_review, "load_llm_config",
                                return_value={"review_queue_max": 100,
                                              "max_runs_in_packet": 100}),
              mock.patch.object(llm_review, "_run_batch_review", side_effect=complete)):
            llm_review._worker_loop(agent, log=lambda _message: None)

        self.assertEqual(batches, [
            ("live", [11, 12]), ("pkg-a", [8, 9]), ("pkg-b", [8, 10]),
        ])

    def test_explicit_salvage_replay_keeps_each_package_as_an_independent_group(self) -> None:
        base = Path(self.temp.name) / "stack"
        (base / ".runtime").mkdir(parents=True)
        (base / ".runtime" / "session.json").write_text(
            json.dumps({"state": "stopped"}), encoding="utf-8")
        manifests = {
            "pkg-a": {"batch_runs": [8, 9], "model": "glm", "source": "preferred"},
            "pkg-b": {"batch_runs": [8, 10], "model": "glm", "source": "preferred"},
        }
        for name, manifest in manifests.items():
            package = llm_review.SALVAGE_ROOT / name
            package.mkdir()
            (package / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
        self.queue.write_text(json.dumps({"pending": [], "reviewing": None}),
                              encoding="utf-8")

        def materialize(package: Path, log=print):
            return manifests[package.name]

        with (mock.patch.object(llm_review, "BASE_DIR", base),
              mock.patch.object(llm_review, "_materialize_retry_evidence",
                                side_effect=materialize) as materialize_mock):
            queued = llm_review.requeue_salvage_packages(
                ["pkg-a", "pkg-b"], log=lambda _message: None)
        materialize_mock.assert_not_called()

        self.assertEqual(queued, {"pkg-a": [8, 9], "pkg-b": [8, 10]})
        pending = llm_review._load_queue_unlocked()["pending"]
        self.assertEqual([(item["retry_group"], item["run"]) for item in pending], [
            ("pkg-a", 8), ("pkg-a", 9), ("pkg-b", 8), ("pkg-b", 10),
        ])

    def test_retry_evidence_uses_private_objects_and_excludes_runtime_cache_from_patch(self) -> None:
        package = llm_review.SALVAGE_ROOT / "pkg-materialize"
        repo = package / "raw_sandbox" / "repo"
        (repo / "sts2-ascend" / "brain").mkdir(parents=True)
        (repo / "sts2-ascend" / "knowledge").mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
                       check=True)
        policy = repo / "sts2-ascend" / "brain" / "policy.py"
        policy.write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "base"], check=True)
        pre_head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip()
        policy.write_text("VALUE = 2\n", encoding="utf-8")
        cache = repo / "sts2-ascend" / "brain" / "__pycache__" / "policy.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"cache-bytes")
        runtime = repo / "sts2-ascend" / ".runtime" / "viewer.pid"
        runtime.parent.mkdir()
        runtime.write_text("123", encoding="utf-8")
        (package / "manifest.json").write_text(json.dumps({
            "pre_head": pre_head, "batch_runs": [8], "model": "glm",
        }), encoding="utf-8")
        objects = repo / ".git" / "objects"

        def object_snapshot() -> dict[str, bytes]:
            return {path.relative_to(objects).as_posix(): path.read_bytes()
                    for path in objects.rglob("*") if path.is_file()}

        before_objects = object_snapshot()
        old_repo, old_prompt = llm_review.REPO_DIR, llm_review.PROMPT_FILE
        try:
            llm_review.REPO_DIR = repo
            llm_review.PROMPT_FILE = (
                repo / "sts2-ascend" / "knowledge" / "review_prompt_latest.md")
            with mock.patch.object(llm_review, "_review_stop_requested", return_value=False):
                manifest = llm_review._materialize_retry_evidence(
                    package, log=lambda _message: None)
        finally:
            llm_review.REPO_DIR, llm_review.PROMPT_FILE = old_repo, old_prompt

        self.assertEqual(object_snapshot(), before_objects)
        self.assertEqual(manifest["retry_evidence_schema"], 3)
        candidate = (package / "retry_candidate.patch").read_text(
            encoding="utf-8", errors="replace")
        inventory = json.loads((package / "retry_candidate_inventory.json").read_text(
            encoding="utf-8"))
        self.assertIn("sts2-ascend/brain/policy.py", candidate)
        self.assertNotIn("__pycache__", candidate)
        self.assertNotIn(".runtime", candidate)
        self.assertIn("sts2-ascend/brain/__pycache__/policy.pyc",
                      inventory["transient_artifact_paths"])
        self.assertIn("sts2-ascend/.runtime/viewer.pid",
                      inventory["online_runtime_paths"])

    def test_retry_evidence_reads_clean_local_ref_and_stash_without_mutating_raw_git(self) -> None:
        package = llm_review.SALVAGE_ROOT / "pkg-ref-stash"
        repo = package / "raw_sandbox" / "repo"
        brain = repo / "sts2-ascend" / "brain"
        brain.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email",
                        "test@example.invalid"], check=True)
        policy = brain / "policy.py"
        strategy = brain / "strategy.py"
        policy.write_text("VALUE = 1\n", encoding="utf-8")
        strategy.write_text("STRATEGY = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "base"],
                       check=True)
        pre_head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "-C", str(repo), "switch", "-c", "model-work", "--quiet"],
                       check=True)
        policy.write_text("VALUE = 2\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", str(policy)], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "model commit"],
                       check=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "--detach", "--quiet", pre_head],
                       check=True)
        strategy.write_text("STRATEGY = 3\n", encoding="utf-8")
        new_strategy = brain / "new_strategy.py"
        new_strategy.write_text("NEW_STRATEGY = 4\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "stash", "push", "-u", "--quiet", "-m",
                        "model stash"], check=True)
        (package / "manifest.json").write_text(json.dumps({
            "pre_head": pre_head, "batch_runs": [8], "model": "glm",
        }), encoding="utf-8")
        git_dir = repo / ".git"

        def git_snapshot() -> dict[str, bytes]:
            return {path.relative_to(git_dir).as_posix(): path.read_bytes()
                    for path in git_dir.rglob("*") if path.is_file()}

        before = git_snapshot()
        with mock.patch.object(llm_review, "_review_stop_requested", return_value=False):
            manifest = llm_review._materialize_retry_evidence(
                package, log=lambda _message: None)
        self.assertEqual(git_snapshot(), before)
        self.assertEqual(manifest["retry_evidence_schema"], 3)
        candidate = (package / "retry_candidate.patch").read_text(
            encoding="utf-8", errors="replace")
        inventory = json.loads((package / "retry_candidate_inventory.json").read_text(
            encoding="utf-8"))
        self.assertIn("VALUE = 2", candidate)
        self.assertIn("STRATEGY = 3", candidate)
        self.assertIn("NEW_STRATEGY = 4", candidate)
        self.assertIn("sts2-ascend/brain/new_strategy.py", inventory["paths"])
        kinds = {item.get("kind") for item in inventory["sources"]}
        self.assertIn("local_ref", kinds)
        self.assertIn("stash", kinds)
        self.assertIn("stash_untracked", kinds)

    def test_retry_evidence_preserves_staged_only_raw_index_content(self) -> None:
        package = llm_review.SALVAGE_ROOT / "pkg-raw-index"
        repo = package / "raw_sandbox" / "repo"
        policy = repo / "sts2-ascend" / "brain" / "policy.py"
        policy.parent.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email",
                        "test@example.invalid"], check=True)
        policy.write_text("VALUE = 'base'\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "base"],
                       check=True)
        pre_head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip()
        policy.write_text("VALUE = 'staged-only'\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "--",
                        "sts2-ascend/brain/policy.py"], check=True)
        policy.write_text("VALUE = 'base'\n", encoding="utf-8")
        (package / "manifest.json").write_text(
            json.dumps({"pre_head": pre_head}), encoding="utf-8")
        index_before = (repo / ".git" / "index").read_bytes()

        with mock.patch.object(llm_review, "_review_stop_requested", return_value=False):
            llm_review._materialize_retry_evidence(package, log=lambda _message: None)

        self.assertEqual((repo / ".git" / "index").read_bytes(), index_before)
        candidate = (package / "retry_candidate.patch").read_text(
            encoding="utf-8", errors="replace")
        inventory = json.loads((package / "retry_candidate_inventory.json").read_text(
            encoding="utf-8"))
        self.assertIn("VALUE = 'staged-only'", candidate)
        index_sources = [item for item in inventory["sources"]
                         if item.get("kind") == "raw_index"]
        self.assertEqual(len(index_sources), 1)
        self.assertIn("sts2-ascend/brain/policy.py",
                      index_sources[0]["accepted_candidate_paths"])

    def test_retry_evidence_does_not_treat_git_notes_ref_as_code_commit(self) -> None:
        package = llm_review.SALVAGE_ROOT / "pkg-notes-ref"
        repo = package / "raw_sandbox" / "repo"
        policy = repo / "sts2-ascend" / "brain" / "policy.py"
        policy.parent.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email",
                        "test@example.invalid"], check=True)
        policy.write_text("VALUE = 'keep'\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "base"],
                       check=True)
        pre_head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "-C", str(repo), "notes", "add", "-m",
                        "review metadata", pre_head], check=True)
        (package / "manifest.json").write_text(
            json.dumps({"pre_head": pre_head}), encoding="utf-8")

        with mock.patch.object(llm_review, "_review_stop_requested", return_value=False):
            llm_review._materialize_retry_evidence(package, log=lambda _message: None)

        candidate = (package / "retry_candidate.patch").read_text(
            encoding="utf-8", errors="replace")
        inventory = json.loads((package / "retry_candidate_inventory.json").read_text(
            encoding="utf-8"))
        self.assertNotIn("sts2-ascend/brain/policy.py", candidate)
        self.assertIn("refs/notes/commits", {item["ref"] for item in inventory["refs"]})
        self.assertNotIn("refs/notes/commits",
                         {item.get("label") for item in inventory["sources"]})

    def test_failed_sandbox_preserves_raw_head_and_index_for_retry_materializer(self) -> None:
        host = Path(self.temp.name) / "host"
        policy = host / "sts2-ascend" / "brain" / "policy.py"
        strategy = host / "sts2-ascend" / "brain" / "strategy.py"
        prompt = host / "sts2-ascend" / "knowledge" / "review_prompt_latest.md"
        policy.parent.mkdir(parents=True)
        prompt.parent.mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet", str(host)], check=True)
        subprocess.run(["git", "-C", str(host), "config", "user.name", "test"], check=True)
        subprocess.run(["git", "-C", str(host), "config", "user.email",
                        "test@example.invalid"], check=True)
        policy.write_text("POLICY = 'base'\n", encoding="utf-8")
        strategy.write_text("STRATEGY = 'base'\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(host), "add", "."], check=True)
        subprocess.run(["git", "-C", str(host), "commit", "--quiet", "-m", "base"],
                       check=True)
        pre_head = subprocess.run(
            ["git", "-C", str(host), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip()
        observed: dict[str, object] = {}

        def fail_after_commit_and_stage(cmd, timeout, translate=None, **_kwargs):
            repo = Path(cmd[cmd.index("--dir") + 1])
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "model"],
                           check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email",
                            "model@example.invalid"], check=True)
            model_policy = repo / "sts2-ascend" / "brain" / "policy.py"
            model_strategy = repo / "sts2-ascend" / "brain" / "strategy.py"
            model_policy.write_text("POLICY = 'committed'\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "--",
                            "sts2-ascend/brain/policy.py"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "--quiet", "-m",
                            "model commit"], check=True)
            model_strategy.write_text("STRATEGY = 'staged-only'\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "--",
                            "sts2-ascend/brain/strategy.py"], check=True)
            model_strategy.write_text("STRATEGY = 'base'\n", encoding="utf-8")
            observed["head"] = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                capture_output=True, text=True).stdout.strip()
            observed["index"] = (repo / ".git" / "index").read_bytes()
            return 1, "model failed", False, False, False

        old_repo, old_knowledge, old_prompt = (
            llm_review.REPO_DIR, llm_review.KNOWLEDGE_DIR, llm_review.PROMPT_FILE)
        llm_review.REPO_DIR = host
        llm_review.KNOWLEDGE_DIR = host / "sts2-ascend" / "knowledge"
        llm_review.PROMPT_FILE = prompt
        try:
            with (mock.patch.object(llm_review, "_stream_run",
                                    side_effect=fail_after_commit_and_stage),
                  mock.patch.object(llm_review, "_review_stop_requested",
                                    return_value=False)):
                result = llm_review._run_review_sandbox(
                    ["fake", "--dir", str(host)], "prompt", pre_head, 10,
                    mock.Mock(feed=lambda _line: None), log=lambda _message: None)
                self.assertTrue(result.error)
                saved = llm_review._save_review_salvage(
                    pre_head, result.error, result, batch_runs=[9], model="glm",
                    source="test", log=lambda _message: None)
                self.assertIsNotNone(saved)
                assert saved is not None
                raw_repo = saved / "raw_sandbox" / "repo"
                self.assertEqual(
                    subprocess.run(["git", "-C", str(raw_repo), "rev-parse", "HEAD"],
                                   check=True, capture_output=True,
                                   text=True).stdout.strip(),
                    observed["head"])
                self.assertEqual((raw_repo / ".git" / "index").read_bytes(),
                                 observed["index"])
                llm_review._materialize_retry_evidence(
                    saved, log=lambda _message: None)
        finally:
            llm_review.REPO_DIR, llm_review.KNOWLEDGE_DIR, llm_review.PROMPT_FILE = (
                old_repo, old_knowledge, old_prompt)

        candidate = (saved / "retry_candidate.patch").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("POLICY = 'committed'", candidate)
        self.assertIn("STRATEGY = 'staged-only'", candidate)

    def test_no_raw_package_promotes_validated_candidate_not_noisy_wip(self) -> None:
        package = llm_review.SALVAGE_ROOT / "pkg-no-raw"
        package.mkdir()
        accepted = b"diff --git a/sts2-ascend/brain/policy.py b/sts2-ascend/brain/policy.py\n+VALUE = 2\n"
        (package / "validated_candidate.patch").write_bytes(accepted)
        (package / "wip.patch").write_bytes(
            accepted + b"diff --git a/sts2-ascend/brain/__pycache__/policy.pyc b/cache\n")
        (package / "manifest.json").write_text(json.dumps({
            "pre_head": "a" * 40,
            "validated_candidate_paths": ["sts2-ascend/brain/policy.py"],
            "transient_artifact_paths": ["sts2-ascend/brain/__pycache__/policy.pyc"],
        }), encoding="utf-8")
        manifest = llm_review._materialize_retry_evidence(
            package, log=lambda _message: None)
        self.assertEqual(manifest["retry_evidence_schema"], 3)
        self.assertEqual((package / "retry_candidate.patch").read_bytes(), accepted)
        inventory = json.loads((package / "retry_candidate_inventory.json").read_text(
            encoding="utf-8"))
        self.assertEqual(inventory["accepted_candidate_paths"],
                         ["sts2-ascend/brain/policy.py"])
        self.assertIn("sts2-ascend/brain/__pycache__/policy.pyc",
                      inventory["transient_artifact_paths"])

    def test_crash_after_package_publish_recovers_one_target_from_queue_id(self) -> None:
        package = llm_review.SALVAGE_ROOT / "pkg-crash-window"
        package.mkdir()
        (package / "manifest.json").write_text(json.dumps({
            "time": "now", "batch_runs": [8], "model": "glm",
            "source": "preferred", "every": 1,
            "replay_enqueue_pending": True,
            "replay_target": "pkg-crash-window", "replay_role": "target",
            "replay_queue_ids": ["txn-8"], "replay_attempt_packages": [],
        }), encoding="utf-8")
        self.queue.write_text(json.dumps({
            "pending": [],
            "reviewing": {"runs": [8], "items": [{"run": 8, "queue_id": "txn-8"}]},
        }), encoding="utf-8")
        llm_review._recover_salvage_replay_queue(log=lambda _message: None)
        saved = llm_review._load_queue_unlocked()
        self.assertEqual(saved["pending"], [])
        item = saved["reviewing"]["items"][0]
        self.assertEqual(item["replay_target"], "pkg-crash-window")
        self.assertEqual(item["retry_group"], "pkg-crash-window")
        self.assertEqual(item["salvage_packages"], ["pkg-crash-window"])
        llm_review._recover_salvage_replay_queue(log=lambda _message: None)
        saved = llm_review._load_queue_unlocked()
        self.assertEqual(len(saved["reviewing"]["items"]), 1)
        self.assertEqual(saved["pending"], [])

    def test_durable_receipt_consumes_stale_pending_and_reviewing_before_cleanup(self) -> None:
        package = llm_review.SALVAGE_ROOT / "pkg-resolved"
        package.mkdir()
        (package / "manifest.json").write_text(json.dumps({
            "replay_enqueue_pending": True,
            "replay_target": "pkg-resolved", "replay_role": "target",
            "replay_queue_ids": ["txn-pending", "txn-reviewing"],
            "retry_resolution": "integrated", "retry_resolution_commit": "a" * 40,
            "retry_resolution_state": "code_upstream_confirmed",
        }), encoding="utf-8")
        self.queue.write_text(json.dumps({
            "pending": [{
                "run": 8, "queue_id": "txn-pending", "retry_group": "pkg-resolved",
            }],
            "reviewing": {
                "runs": [9],
                "items": [{
                    "run": 9, "queue_id": "txn-reviewing",
                    "replay_target": "pkg-resolved",
                }],
            },
        }), encoding="utf-8")
        llm_review._recover_salvage_replay_queue(log=lambda _message: None)
        saved = llm_review._load_queue_unlocked()
        self.assertEqual(saved["pending"], [])
        self.assertIsNone(saved["reviewing"])
        self.assertTrue(package.is_dir())

    def test_failed_replay_keeps_one_target_and_attaches_new_attempt(self) -> None:
        batch = [{
            "run": 8, "model": "glm", "every": 1, "source": "preferred",
            "retry_group": "pkg-target", "replay_target": "pkg-target",
            "salvage_packages": ["pkg-target"], "salvage_attempts": ["pkg-old-attempt"],
            "queue_id": "txn-target",
        }]
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)

        def failed(*_args, **kwargs):
            kwargs["_status"].update({
                "outcome": "failed", "reason": "again",
                "new_salvage_package": "pkg-new-attempt",
            })
            return False

        with (mock.patch.object(llm_review, "load_llm_config",
                               return_value={"opencode_bin": "opencode"}),
              mock.patch.object(llm_review.shutil, "which", return_value="opencode"),
              mock.patch.object(llm_review, "run_review", side_effect=failed),
              mock.patch.object(llm_review, "_link_replay_attempt",
                                return_value=["pkg-old-attempt", "pkg-new-attempt"])):
            outcome = llm_review._run_batch_review(
                agent, batch, log=lambda _message: None)
        self.assertEqual(outcome, "failed")
        self.assertEqual(batch[0]["replay_target"], "pkg-target")
        self.assertEqual(batch[0]["retry_group"], "pkg-target")
        self.assertEqual(batch[0]["salvage_packages"], ["pkg-target"])
        self.assertEqual(batch[0]["salvage_attempts"],
                         ["pkg-old-attempt", "pkg-new-attempt"])

    def test_large_attempt_lineage_cannot_starve_target_candidate_budget(self) -> None:
        names = [f"attempt-{index:03d}" for index in range(100)]
        for name in ["pkg-target", *names]:
            package = llm_review.SALVAGE_ROOT / name
            package.mkdir()
            (package / "manifest.json").write_text(
                json.dumps({"pre_head": "a" * 40}), encoding="utf-8")
            (package / "retry_candidate.patch").write_bytes(b"x" * (160 * 1024))
            (package / "retry_candidate_inventory.json").write_text(
                json.dumps({"paths": ["sts2-ascend/brain/policy.py"]}),
                encoding="utf-8")
            (package / "report.md").write_text("report", encoding="utf-8")
        with mock.patch.object(llm_review, "_materialize_retry_evidence"):
            packet = llm_review._failed_review_replay_context(
                ["pkg-target"], names, log=lambda _message: None)
        packages = {item["package"]: item for item in packet["packages"]}
        self.assertGreaterEqual(
            len(packages["pkg-target"]["candidate_patch"].encode("utf-8")),
            96 * 1024)
        self.assertEqual(packages[names[0]]["candidate_patch"], "")
        self.assertGreater(len(packages[names[-1]]["candidate_patch"]), 0)

    def test_closed_package_is_quarantined_until_final_ledger_is_upstream(self) -> None:
        package = llm_review.SALVAGE_ROOT / "pkg-close"
        package.mkdir()
        manifest = {
            "time": "now", "batch_runs": [8], "pre_head": "b" * 40,
            "model": "glm", "failure_kind": "stall",
            "retry_resolution": "integrated",
            "retry_resolution_commit": "a" * 40,
        }
        (package / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        (package / "all-files-preserved.bin").write_bytes(b"evidence")
        old_base = llm_review.BASE_DIR
        try:
            llm_review.BASE_DIR = llm_review.SALVAGE_ROOT.parent
            with (mock.patch.object(llm_review, "_upstream_contains_commit",
                                   return_value=True),
                  mock.patch.object(llm_review, "_update_rejection_ledger",
                                   return_value=False)):
                self.assertFalse(llm_review._finalize_salvage_resolution(
                    package, manifest, log=lambda _message: None))
            quarantine = (llm_review.SALVAGE_ROOT
                          / f"{llm_review._CLOSED_SALVAGE_PREFIX}pkg-close")
            self.assertFalse(package.exists())
            self.assertEqual((quarantine / "all-files-preserved.bin").read_bytes(),
                             b"evidence")
            recovered_manifest = json.loads(
                (quarantine / "manifest.json").read_text(encoding="utf-8"))
            with (mock.patch.object(llm_review, "_upstream_contains_commit",
                                    return_value=True),
                  mock.patch.object(llm_review, "_update_rejection_ledger",
                                    return_value=True)):
                self.assertTrue(llm_review._finish_quarantined_salvage(
                    quarantine, "pkg-close", recovered_manifest,
                    log=lambda _message: None))
            self.assertFalse(quarantine.exists())
        finally:
            llm_review.BASE_DIR = old_base

    def test_stop_during_quarantine_cleanup_keeps_manifest_for_recovery(self) -> None:
        quarantine = (llm_review.SALVAGE_ROOT
                      / f"{llm_review._CLOSED_SALVAGE_PREFIX}pkg-stop-cleanup")
        quarantine.mkdir()
        manifest = quarantine / "manifest.json"
        payload = quarantine / "large-preserved.bin"
        manifest.write_text(json.dumps({"retry_resolution": "integrated"}),
                            encoding="utf-8")
        payload.write_bytes(b"evidence")
        with mock.patch.object(
                llm_review, "_review_stop_requested", side_effect=[False, True]):
            self.assertFalse(llm_review._delete_closed_quarantine(
                quarantine, log=lambda _message: None))
        self.assertFalse(payload.exists())
        self.assertTrue(manifest.is_file())
        with mock.patch.object(llm_review, "_review_stop_requested", return_value=False):
            self.assertTrue(llm_review._delete_closed_quarantine(
                quarantine, log=lambda _message: None))
        self.assertFalse(quarantine.exists())

    def test_empty_quarantine_tail_recovers_only_with_exact_upstream_ledger(self) -> None:
        quarantine = (llm_review.SALVAGE_ROOT
                      / f"{llm_review._CLOSED_SALVAGE_PREFIX}pkg-tail-retry")
        quarantine.mkdir()
        (quarantine / "manifest.json").write_text(json.dumps({
            "retry_resolution": "integrated",
        }), encoding="utf-8")
        original_rmdir = Path.rmdir
        failed_once = False

        def fail_tail_once(path: Path):
            nonlocal failed_once
            if path == quarantine and not failed_once:
                failed_once = True
                raise PermissionError("temporary antivirus directory handle")
            return original_rmdir(path)

        with (mock.patch.object(llm_review, "_review_stop_requested",
                               return_value=False),
              mock.patch.object(Path, "rmdir", fail_tail_once)):
            self.assertFalse(llm_review._delete_closed_quarantine(
                quarantine, log=lambda _message: None))
        self.assertTrue(quarantine.is_dir())
        self.assertEqual(list(quarantine.iterdir()), [])

        with (mock.patch.object(llm_review, "_review_stop_requested",
                               return_value=False),
              mock.patch.object(llm_review, "_upstream_ledger_contains",
                               return_value=True) as upstream):
            llm_review._resume_host_salvage_closures(log=lambda _message: None)
        upstream.assert_called_with("pkg-tail-retry", "并闭环")
        self.assertFalse(quarantine.exists())

    def test_replay_receipt_is_durable_and_host_only_when_stop_arrives(self) -> None:
        for name, role in (("pkg-target", "target"), ("pkg-attempt", "attempt_evidence")):
            package = llm_review.SALVAGE_ROOT / name
            package.mkdir()
            (package / "manifest.json").write_text(json.dumps({
                "time": "now", "batch_runs": [8], "replay_target": "pkg-target",
                "replay_role": role,
            }), encoding="utf-8")
        with (mock.patch.object(llm_review, "_review_stop_requested", return_value=True),
              mock.patch.object(llm_review, "_finalize_salvage_resolution") as finalize):
            result = llm_review._close_replayed_salvages(
                ["pkg-target"], ["pkg-attempt"],
                {"pkg-target": "integrated"}, commit="a" * 40, pushed=True,
                log=lambda _message: None)
        finalize.assert_not_called()
        self.assertEqual(set(result["host_pending"]), {"pkg-target", "pkg-attempt"})
        for name in ("pkg-target", "pkg-attempt"):
            manifest = json.loads(
                (llm_review.SALVAGE_ROOT / name / "manifest.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(manifest["retry_resolution"], "integrated")
            self.assertEqual(manifest["retry_resolution_state"],
                             "code_upstream_confirmed")

    def test_code_push_failure_becomes_host_state_not_another_glm_review(self) -> None:
        package = llm_review.SALVAGE_ROOT / "pkg-push"
        package.mkdir()
        (package / "manifest.json").write_text(json.dumps({
            "time": "now", "batch_runs": [8], "replay_target": "pkg-push",
            "replay_role": "target",
        }), encoding="utf-8")
        with mock.patch.object(llm_review, "_upstream_contains_commit", return_value=False):
            result = llm_review._close_replayed_salvages(
                ["pkg-push"], [], {"pkg-push": "integrated"},
                commit="a" * 40, pushed=False, log=lambda _message: None)
        self.assertEqual(result["host_pending"], ["pkg-push"])
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["retry_resolution_state"],
                         "claimed_pending_code_push")

        batch = [{
            "run": 8, "model": "glm", "every": 1, "source": "preferred",
            "retry_group": "pkg-push", "replay_target": "pkg-push",
            "salvage_packages": ["pkg-push"], "queue_id": "txn-push",
        }]
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)

        def accepted(*_args, **kwargs):
            kwargs["_status"].update({
                "outcome": "changed", "commit": "a" * 40, "pushed": False,
                "retry_resolutions": {"pkg-push": "integrated"},
                "unresolved_salvage_packages": [],
                "host_pending_salvage_packages": ["pkg-push"],
            })
            return True

        with (mock.patch.object(llm_review, "load_llm_config",
                               return_value={"opencode_bin": "opencode"}),
              mock.patch.object(llm_review.shutil, "which", return_value="opencode"),
              mock.patch.object(llm_review, "run_review", side_effect=accepted)):
            outcome = llm_review._run_batch_review(
                agent, batch, log=lambda _message: None)
        self.assertEqual(outcome, "changed")

    def test_explicit_attempt_replay_wakes_root_without_promoting_second_target(self) -> None:
        base = Path(self.temp.name) / "stopped-lineage"
        (base / ".runtime").mkdir(parents=True)
        (base / ".runtime" / "session.json").write_text(
            json.dumps({"state": "stopped"}), encoding="utf-8")
        target = llm_review.SALVAGE_ROOT / "pkg-root"
        attempt = llm_review.SALVAGE_ROOT / "pkg-attempt"
        target.mkdir()
        attempt.mkdir()
        (target / "manifest.json").write_text(json.dumps({
            "batch_runs": [8], "model": "glm", "source": "preferred",
            "replay_target": "pkg-root", "replay_role": "target",
            "replay_attempt_packages": ["pkg-attempt"],
        }), encoding="utf-8")
        (attempt / "manifest.json").write_text(json.dumps({
            "batch_runs": [8], "model": "glm", "source": "preferred",
            "replay_target": "pkg-root", "replay_role": "attempt_evidence",
        }), encoding="utf-8")
        self.queue.write_text(json.dumps({"pending": [], "reviewing": None}),
                              encoding="utf-8")
        with mock.patch.object(llm_review, "BASE_DIR", base):
            queued = llm_review.requeue_salvage_packages(
                ["pkg-attempt", "pkg-root"], log=lambda _message: None)
        self.assertEqual(queued, {"pkg-root": [8]})
        pending = llm_review._load_queue_unlocked()["pending"]
        self.assertEqual({item["replay_target"] for item in pending}, {"pkg-root"})
        self.assertEqual(pending[0]["salvage_attempts"], ["pkg-attempt"])
        attempt_manifest = json.loads((attempt / "manifest.json").read_text(
            encoding="utf-8"))
        self.assertEqual(attempt_manifest["replay_role"], "attempt_evidence")

    def test_runless_legacy_package_is_queued_as_evidence_only(self) -> None:
        base = Path(self.temp.name) / "stopped-stack"
        (base / ".runtime").mkdir(parents=True)
        (base / ".runtime" / "session.json").write_text(
            json.dumps({"state": "stopped"}), encoding="utf-8")
        package = llm_review.SALVAGE_ROOT / "pkg-runless"
        package.mkdir()
        (package / "manifest.json").write_text(json.dumps({
            "batch_runs": [], "model": "glm", "source": "preferred",
        }), encoding="utf-8")
        self.queue.write_text(json.dumps({"pending": [], "reviewing": None}),
                              encoding="utf-8")
        old_knowledge = llm_review.KNOWLEDGE_DIR
        try:
            llm_review.KNOWLEDGE_DIR = Path(self.temp.name) / "missing-knowledge"
            with mock.patch.object(llm_review, "BASE_DIR", base):
                queued = llm_review.requeue_salvage_packages(
                    ["pkg-runless"], log=lambda _message: None)
        finally:
            llm_review.KNOWLEDGE_DIR = old_knowledge
        self.assertEqual(queued, {"pkg-runless": [1]})
        item = llm_review._load_queue_unlocked()["pending"][0]
        self.assertTrue(item["evidence_only"])
        self.assertEqual(item["replay_target"], "pkg-runless")

    def test_evidence_only_prompt_never_attributes_synthetic_run_evidence(self) -> None:
        knowledge_root = Path(self.temp.name) / "evidence-only-knowledge"
        runs_root = knowledge_root / "runs"
        runs_root.mkdir(parents=True)
        # A current run with the same number as the synthetic queue identity must
        # not be loaded or presented as evidence for the legacy failed package.
        (runs_root / "current-1.json").write_text(json.dumps({
            "run_number": 1, "result": "death",
            "decision_chain": [{"reason": "current"}],
        }), encoding="utf-8")
        old_knowledge = llm_review.KNOWLEDGE_DIR
        try:
            llm_review.KNOWLEDGE_DIR = knowledge_root
            with (mock.patch.object(llm_review, "_review_run_records",
                                   side_effect=AssertionError("synthetic run was loaded")),
                  mock.patch.object(llm_review, "_primary_failure_decision_chain",
                                   side_effect=AssertionError("synthetic chain was loaded")),
                  mock.patch.object(llm_review, "_recent_review_context", return_value=[]),
                  mock.patch.object(llm_review, "_historical_zero_code_context",
                                   return_value={}),
                  mock.patch.object(llm_review, "_failed_review_replay_context",
                                   return_value={"packages": []}),
                  mock.patch.object(llm_review, "_stats_digest", return_value={})):
                prompt = llm_review.build_prompt(
                    SimpleNamespace(stats={}), {"max_runs_in_packet": 100},
                    batch_runs=[1], closure_state={"action_required": False},
                    evidence_only=True, log=lambda _message: None)
        finally:
            llm_review.KNOWLEDGE_DIR = old_knowledge
        packet = json.loads(prompt.split("```json\n", 1)[1].split("\n```", 1)[0])
        scope = packet["run_evidence_scope"]
        self.assertEqual(scope["requested"], [])
        self.assertEqual(scope["queue_identity_runs"], [1])
        self.assertEqual(scope["exact"], [])
        self.assertEqual(packet["runs_summary"], [])
        self.assertIsNone(packet["decision_chain_evidence"]["full_failure_run"])

    def test_missing_rejection_marker_is_restored_as_independent_commit(self) -> None:
        import autogit

        root = Path(self.temp.name) / "ledger-recovery"
        repo = root / "repo"
        base = repo / "sts2-ascend"
        knowledge = base / "knowledge"
        salvage = knowledge / "code_backups" / "review_salvage"
        salvage.mkdir(parents=True)
        ledger = base / "REVIEW_REJECTIONS.md"
        ledger.write_text(llm_review._REJECTION_LEDGER_HEADER, encoding="utf-8")
        old_values = (llm_review.REPO_DIR, llm_review.BASE_DIR,
                      llm_review.KNOWLEDGE_DIR, llm_review.SALVAGE_ROOT,
                      llm_review.REJECTION_LEDGER)
        try:
            llm_review.REPO_DIR = repo
            llm_review.BASE_DIR = base
            llm_review.KNOWLEDGE_DIR = knowledge
            llm_review.SALVAGE_ROOT = salvage
            llm_review.REJECTION_LEDGER = ledger
            with (mock.patch.object(llm_review, "_review_stop_requested",
                                   return_value=False),
                  mock.patch.object(llm_review, "_upstream_ledger_contains",
                                   side_effect=[False, True]),
                  mock.patch.object(autogit, "commit_progress_result",
                                   return_value=SimpleNamespace(
                                       created=True, commit="c" * 40)),
                  mock.patch.object(autogit, "push_pending", return_value=True)):
                self.assertTrue(llm_review._ensure_rejection_ledger_marker(
                    "pkg-missing", {"batch_runs": [8], "pre_head": "a" * 40},
                    "（隔离保留）", log=lambda _message: None))
        finally:
            (llm_review.REPO_DIR, llm_review.BASE_DIR,
             llm_review.KNOWLEDGE_DIR, llm_review.SALVAGE_ROOT,
             llm_review.REJECTION_LEDGER) = old_values
        self.assertIn("<!-- rejection:pkg-missing -->",
                      ledger.read_text(encoding="utf-8"))

    def test_failed_ledger_commit_is_flushed_before_next_marker_commit(self) -> None:
        import autogit

        root = Path(self.temp.name) / "ledger-serial"
        root.mkdir()
        ledger = root / "REVIEW_REJECTIONS.md"
        row_a = "<!-- rejection:pkg-a -->\n| a |\n"
        row_b = "<!-- rejection:pkg-b -->\n| b |\n"
        ledger.write_text(llm_review._REJECTION_LEDGER_HEADER + row_a,
                          encoding="utf-8")
        old_repo, old_ledger = llm_review.REPO_DIR, llm_review.REJECTION_LEDGER
        head = {"text": llm_review._REJECTION_LEDGER_HEADER}
        messages: list[str] = []
        attempts = {"count": 0}

        def commit(message, **_kwargs):
            attempts["count"] += 1
            messages.append(message)
            if attempts["count"] == 1:
                return SimpleNamespace(created=False, commit="", reason="lock")
            head["text"] = ledger.read_text(encoding="utf-8")
            return SimpleNamespace(created=True, commit="c" * 40, reason="")

        try:
            llm_review.REPO_DIR = root
            llm_review.REJECTION_LEDGER = ledger
            with (mock.patch.object(llm_review, "_ledger_text_at_head",
                                   side_effect=lambda: head["text"]),
                  mock.patch.object(autogit, "commit_progress_result",
                                   side_effect=commit)):
                self.assertFalse(llm_review._flush_pending_rejection_ledger(
                    log=lambda _message: None))
                self.assertTrue(llm_review._flush_pending_rejection_ledger(
                    log=lambda _message: None))
                ledger.write_text(head["text"] + row_b, encoding="utf-8")
                self.assertTrue(llm_review._flush_pending_rejection_ledger(
                    log=lambda _message: None))
        finally:
            llm_review.REPO_DIR, llm_review.REJECTION_LEDGER = old_repo, old_ledger
        self.assertIn("pkg-a", messages[1])
        self.assertIn("pkg-b", messages[2])

    def test_empty_queue_still_starts_worker_for_host_salvage_recovery(self) -> None:
        package = llm_review.SALVAGE_ROOT / "pkg-host-only"
        package.mkdir()
        (package / "manifest.json").write_text(json.dumps({
            "replay_enqueue_pending": True,
            "replay_target": "pkg-host-only", "replay_role": "target",
            "retry_resolution": "integrated", "retry_resolution_commit": "a" * 40,
            "retry_resolution_state": "claimed_pending_code_push",
        }), encoding="utf-8")
        self.queue.write_text(json.dumps({"pending": [], "reviewing": None}),
                              encoding="utf-8")
        agent = SimpleNamespace()
        with (mock.patch.object(llm_review, "load_llm_config",
                               return_value={"enabled": False}),
              mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
              mock.patch.object(llm_review, "_ensure_worker") as ensure):
            llm_review.resume_review_queue(agent, log=lambda _message: None)
        ensure.assert_called_once()

        for child in package.iterdir():
            child.unlink()
        package.rmdir()
        quarantine = llm_review.SALVAGE_ROOT / ".glm-closed-pkg-quarantine"
        quarantine.mkdir()
        self.assertTrue(llm_review._salvage_recovery_needed())

    def test_unreadable_queue_still_starts_supervisor_for_host_recovery(self) -> None:
        agent = SimpleNamespace()
        with (mock.patch.object(llm_review, "load_llm_config",
                               return_value={"enabled": False}),
              mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
              mock.patch.object(llm_review, "_salvage_recovery_needed",
                               return_value=True),
              mock.patch.object(llm_review, "_load_queue_unlocked",
                               side_effect=llm_review.ReviewQueueError("locked")),
              mock.patch.object(llm_review, "_ensure_worker") as ensure):
            llm_review.resume_review_queue(agent, log=lambda _message: None)
        ensure.assert_called_once_with(agent, mock.ANY)

    def test_worker_start_failure_releases_latch_for_next_attempt(self) -> None:
        agent = SimpleNamespace()
        broken = mock.Mock()
        broken.start.side_effect = OSError("thread resource unavailable")
        healthy = mock.Mock()
        old_started, old_thread = llm_review._worker_started, llm_review._worker_thread
        llm_review._worker_started = False
        llm_review._worker_thread = None
        try:
            with (mock.patch.object(llm_review, "_review_stop_requested",
                                   return_value=False),
                  mock.patch.object(llm_review.threading, "Thread",
                                   return_value=broken)):
                llm_review._ensure_worker(agent, log=lambda _message: None)
            self.assertFalse(llm_review._worker_started)
            self.assertIsNone(llm_review._worker_thread)

            with (mock.patch.object(llm_review, "_review_stop_requested",
                                   return_value=False),
                  mock.patch.object(llm_review.threading, "Thread",
                                   return_value=healthy)):
                llm_review._ensure_worker(agent, log=lambda _message: None)
            healthy.start.assert_called_once_with()
            self.assertTrue(llm_review._worker_started)
            self.assertIs(llm_review._worker_thread, healthy)
        finally:
            llm_review._worker_started = old_started
            llm_review._worker_thread = old_thread


if __name__ == "__main__":
    unittest.main()
