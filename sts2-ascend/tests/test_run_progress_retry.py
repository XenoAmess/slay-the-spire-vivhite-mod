"""A failed incremental save must remain due on the next observation."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402


class RunProgressRetryTests(unittest.TestCase):
    def test_failed_write_retries_same_snapshot_then_resumes_throttling(self) -> None:
        for previous_mark in (None, (0, 3, 0), (15, 2, 0)):
            with self.subTest(previous_mark=previous_mark):
                instance = object.__new__(agent_module.Agent)
                instance.ctx = agent_module.RunContext(
                    run_id="offline-save-retry", run_number=1,
                    decisions=[{"floor": 3, "action": "play_card"}] * 15)
                storage = mock.Mock()
                storage.save_run_log.side_effect = [
                    OSError("injected transient write failure"), None]
                instance.know = storage
                instance._knowledge_for_run_learning = mock.Mock(
                    return_value=(storage, None))
                instance._run_profile_metadata = mock.Mock(return_value={})
                if previous_mark is not None:
                    instance._rlog_mark = previous_mark

                self.assertFalse(instance._save_run_progress({"floor": 3}))
                self.assertEqual(
                    getattr(instance, "_rlog_mark", None), previous_mark)
                self.assertTrue(instance._save_run_progress({"floor": 3}))
                self.assertEqual(storage.save_run_log.call_count, 2)
                self.assertEqual(instance._rlog_mark, (15, 3, 0))
                self.assertEqual(
                    storage.save_run_log.call_args_list[0],
                    storage.save_run_log.call_args_list[1])

                # A successful retry still suppresses unchanged snapshots.
                self.assertFalse(instance._save_run_progress({"floor": 3}))
                self.assertEqual(storage.save_run_log.call_count, 2)


if __name__ == "__main__":
    unittest.main()
