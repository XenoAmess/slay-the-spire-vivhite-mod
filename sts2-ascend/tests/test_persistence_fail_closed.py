"""Fault-injection regressions for durable knowledge and review-queue I/O."""
from __future__ import annotations

from contextlib import contextmanager
import json
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
        llm_review.QUEUE_FILE = self.queue

    def tearDown(self) -> None:
        llm_review.QUEUE_FILE = self.old_queue
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
               "review_queue_max": 10}

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


if __name__ == "__main__":
    unittest.main()
