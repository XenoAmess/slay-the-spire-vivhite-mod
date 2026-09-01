from __future__ import annotations

import io
import json
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BRAIN_DIR = ROOT / "sts2-ascend" / "brain"
sys.path.insert(0, str(BRAIN_DIR))

import autogit  # noqa: E402
import runner  # noqa: E402


class RunnerHandshakeTests(unittest.TestCase):
    def test_child_output_capture_keeps_bounded_stdout_and_stderr_tails(self) -> None:
        process = mock.Mock(pid=123)
        process.stdout = io.BytesIO(b"stdout line\n")
        process.stderr = io.BytesIO(b"stderr line\n")
        old_limit = runner._CHILD_OUTPUT_LIMIT
        runner._CHILD_OUTPUT_LIMIT = 8
        try:
            capture = runner._ChildOutputCapture(process)
            capture.finish()
            snapshot = capture.snapshot()
        finally:
            runner._CHILD_OUTPUT_LIMIT = old_limit
        self.assertEqual(snapshot["stdout"], "ut line\n")
        self.assertEqual(snapshot["stderr"], "rr line\n")

    def test_startup_context_records_interpreter_and_marker_without_secret_env(self) -> None:
        with tempfile.TemporaryDirectory(prefix="runner-handshake-context-") as raw:
            marker = Path(raw) / "knowledge" / "pending_restart.json"
            old_marker = runner.MARKER
            runner.MARKER = marker
            try:
                with mock.patch.object(runner.sys, "executable", "X:/Python/python.exe"), \
                        mock.patch.object(runner.sys, "prefix", "X:/Python"), \
                        mock.patch.object(runner.sys, "base_prefix", "X:/Python"):
                    context = runner._startup_context({"PYTHONHOME": "X:/Python"})
            finally:
                runner.MARKER = old_marker
        self.assertEqual(context["exe"], "X:/Python/python.exe")
        self.assertEqual(context["prefix"], "X:/Python")
        self.assertEqual(context["PYTHONHOME"], "X:/Python")
        self.assertEqual(context["marker_path"], str(marker.resolve()))
        self.assertNotIn("EVOLINK", json.dumps(context))

    def test_run_brain_captures_pipes_and_logs_import_elapsed(self) -> None:
        @contextmanager
        def lock(**_kwargs):
            yield

        process = mock.Mock(pid=4242)
        process.poll.return_value = None
        process.wait.return_value = 0
        process.stdout = io.BytesIO(b"child stdout\n")
        process.stderr = io.BytesIO(b"child stderr\n")
        messages: list[str] = []

        with mock.patch.object(autogit, "repository_lock", lock), \
                mock.patch.object(runner, "read_git_head", return_value="a" * 40), \
                mock.patch.object(runner, "_active_review_commit", return_value=""), \
                mock.patch.object(runner, "_reconcile_prepared_marker", return_value=True), \
                mock.patch.object(runner, "_brain_pid_has_stage", return_value=True), \
                mock.patch.object(runner, "_brain_pid_is_ready", return_value=True), \
                mock.patch.object(runner, "stop_requested", return_value=False), \
                mock.patch.object(runner.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.object(runner, "log", side_effect=messages.append):
            rc, _elapsed = runner._run_brain()

        self.assertEqual(rc, 0)
        kwargs = popen.call_args.kwargs
        self.assertIs(kwargs["stdout"], runner.subprocess.PIPE)
        self.assertIs(kwargs["stderr"], runner.subprocess.PIPE)
        events = [
            json.loads(message.split("Brain startup ", 1)[1])
            for message in messages
            if message.startswith("Brain startup {")
        ]
        self.assertGreaterEqual(len(events), 4)
        self.assertEqual([event["event"] for event in events[:3]],
                         ["launch", "imported", "ready"])
        self.assertIn("elapsed_s", events[1])
        self.assertEqual(events[1]["import_timeout_s"], 10)
        self.assertEqual(events[1]["marker_path"], str(runner.MARKER.resolve()))

    def test_import_timeout_reports_both_child_streams_and_terminates(self) -> None:
        @contextmanager
        def lock(**_kwargs):
            yield

        process = mock.Mock(pid=4343)
        process.poll.return_value = None
        process.stdout = io.BytesIO(b"import stdout\n")
        process.stderr = io.BytesIO(b"import stderr\n")
        messages: list[str] = []

        with mock.patch.object(autogit, "repository_lock", lock), \
                mock.patch.object(runner, "read_git_head", return_value="a" * 40), \
                mock.patch.object(runner, "_active_review_commit", return_value=""), \
                mock.patch.object(runner, "_reconcile_prepared_marker", return_value=True), \
                mock.patch.object(runner, "_brain_pid_has_stage", return_value=False), \
                mock.patch.object(runner, "stop_requested", return_value=False), \
                mock.patch.object(runner, "STARTUP_IMPORT_SECONDS", 0), \
                mock.patch.object(runner.subprocess, "Popen", return_value=process), \
                mock.patch.object(runner, "_terminate_startup_child") as terminate, \
                mock.patch.object(runner, "log", side_effect=messages.append):
            rc, _elapsed = runner._run_brain()

        self.assertEqual(rc, runner.STARTUP_TIMEOUT_CODE)
        terminate.assert_called_once_with(process)
        timeout_events = [
            json.loads(message.split("Brain startup ", 1)[1])
            for message in messages
            if message.startswith("Brain startup {")
            and '"event": "import_timeout"' in message
        ]
        self.assertEqual(len(timeout_events), 1)
        self.assertEqual(timeout_events[0]["child_stdout_tail"], "import stdout\n")
        self.assertEqual(timeout_events[0]["child_stderr_tail"], "import stderr\n")
        self.assertEqual(timeout_events[0]["import_timeout_s"], 0)

    def test_import_timeout_and_outage_budget_remain_separate_bounds(self) -> None:
        self.assertEqual(runner.STARTUP_IMPORT_SECONDS, 10)
        self.assertEqual(runner.OUTAGE_BUDGET_SECONDS, 115)
        self.assertLess(runner.STARTUP_IMPORT_SECONDS, runner.OUTAGE_BUDGET_SECONDS)


if __name__ == "__main__":
    unittest.main()
