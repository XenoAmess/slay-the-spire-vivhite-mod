"""Loaded review epochs, rather than a later marker, own restart attribution."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))
import runner  # noqa: E402


class RunnerEpochTests(unittest.TestCase):
    def supervise(self, generations: list[tuple[str, str, int]]) -> mock.Mock:
        remaining = iter(generations)
        current = [""]

        def child(_deadline):
            loaded, current[0], code = next(remaining)
            return runner.BrainRunResult(
                code, 300.0, boot_id=f"boot-{loaded}",
                boot_head="f" * 40, boot_review_commit=loaded)

        with mock.patch.object(runner, "_run_brain", side_effect=child), \
                mock.patch.object(runner, "_active_review_commit", side_effect=lambda: current[0]), \
                mock.patch.object(runner, "stop_requested", return_value=False), \
                mock.patch.object(runner, "wait_for_stop", return_value=False), \
                mock.patch.object(runner, "rollback_from_marker", return_value=True) as rollback, \
                mock.patch.object(runner, "log"):
            self.assertEqual(runner.main(), 0)
        return rollback

    def test_different_normal_review_handoffs_never_accumulate_a_restart_loop(self):
        commits = [letter * 40 for letter in "abcdef"]
        generations = [(commits[i], commits[i + 1], runner.RESTART_CODE)
                       for i in range(5)]
        generations.append((commits[-1], commits[-1], 0))
        self.supervise(generations).assert_not_called()

    def test_repeated_restart_from_same_loaded_epoch_still_rolls_back(self):
        commit = "a" * 40
        generations = [(commit, commit, runner.RESTART_CODE)] * runner.MAX_REVIEW_RESTARTS
        generations.append((commit, commit, 0))
        self.supervise(generations).assert_called_once_with(
            None, expected_review_commit=commit)

    def test_crashes_from_different_epochs_do_not_accumulate(self):
        commits = [letter * 40 for letter in "abcde"]
        generations = [(commit, commit, 1) for commit in commits]
        generations.append((commits[-1], commits[-1], 0))
        self.supervise(generations).assert_not_called()

    def test_old_loaded_crash_cannot_be_assigned_to_new_marker(self):
        old, new = "a" * 40, "b" * 40
        generations = [(old, new, 1)] * runner.MAX_FAST_CRASHES
        generations.append((new, new, 0))
        self.supervise(generations).assert_not_called()

    def test_startup_failures_from_different_epochs_do_not_accumulate(self):
        old, new = "a" * 40, "b" * 40
        self.supervise([(old, old, runner.STARTUP_TIMEOUT_CODE),
                        (new, new, runner.STARTUP_TIMEOUT_CODE),
                        (new, new, 0)]).assert_not_called()

    def test_rollback_rechecks_exact_epoch_under_repository_lock(self):
        with tempfile.TemporaryDirectory(prefix="runner-rollback-epoch-") as raw:
            marker = Path(raw) / "pending_restart.json"
            payload = {"review_parent": "c" * 40, "review_commit": "b" * 40,
                       "state": "committed"}
            marker.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(runner, "MARKER", marker), \
                    mock.patch.object(runner.autogit, "repository_lock") as lock, \
                    mock.patch.object(runner, "_trusted_marker_paths") as paths, \
                    mock.patch.object(runner.autogit, "rollback_review_commit") as rollback, \
                    mock.patch.object(runner, "log"):
                self.assertFalse(runner.rollback_from_marker(
                    expected_review_commit="a" * 40))
            lock.assert_called_once()
            paths.assert_not_called()
            rollback.assert_not_called()
            self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), payload)

    def test_marker_replacement_during_rollback_check_retries_new_target(self):
        with mock.patch.object(runner, "rollback_from_marker", return_value=False), \
                mock.patch.object(runner, "_active_review_commit", return_value="b" * 40), \
                mock.patch.object(runner, "log"):
            self.assertTrue(runner._rollback_loaded_epoch("a" * 40))


if __name__ == "__main__":
    unittest.main()
