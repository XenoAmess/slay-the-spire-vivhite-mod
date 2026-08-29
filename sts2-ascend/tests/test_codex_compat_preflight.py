"""No-model Codex compatibility preflight regressions."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402
from review_runners import CodexJsonTranslator  # noqa: E402


class _FakeExecServer:
    def __init__(self, responses: list[dict]) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(
            json.dumps(response, separators=(",", ":")) + "\n"
            for response in responses))
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


class CodexCompatPreflightTests(unittest.TestCase):
    def _run(self, read_response: dict) -> str:
        payload = b"ordinary windows drive file\n"
        fake = _FakeExecServer([
            {"id": 1, "result": {"sessionId": "test"}},
            read_response,
        ])
        version = subprocess.CompletedProcess(
            ["codex", "--version"], 0, "codex-cli 0.148.0\n", "")
        with tempfile.TemporaryDirectory(prefix="sts2-codex-preflight-test-") as root:
            probe = Path(root) / "probe.txt"
            probe.write_bytes(payload)
            with (mock.patch.object(
                      llm_review, "_run_captured_stop_aware", return_value=version),
                  mock.patch.object(llm_review.subprocess, "Popen", return_value=fake)):
                return llm_review._codex_windows_filesystem_preflight(
                    "codex.exe", probe, payload, expected_version="0.148.0")

    def test_compatible_cli_reads_exact_bytes_without_model_work(self) -> None:
        error = self._run({
            "id": 2,
            "result": {"dataBase64": base64.b64encode(
                b"ordinary windows drive file\n").decode("ascii")},
        })

        self.assertEqual(error, "")

    def test_codex_0149_drive_root_false_positive_fails_closed(self) -> None:
        error = self._run({
            "id": 2,
            "error": {"code": -32600, "message": "path contains a reparse point"},
        })

        self.assertIn("Windows filesystem capability failed", error)
        self.assertIn("path contains a reparse point", error)

    def test_hash_mismatch_stops_before_exec_server(self) -> None:
        payload = b"ordinary windows drive file\n"
        version = subprocess.CompletedProcess(
            ["codex", "--version"], 0, "codex-cli 0.148.0\n", "")
        with tempfile.TemporaryDirectory(prefix="sts2-codex-hash-test-") as root:
            binary = Path(root) / "codex.exe"
            binary.write_bytes(b"different pinned build")
            probe = Path(root) / "probe.txt"
            probe.write_bytes(payload)
            with (mock.patch.object(
                      llm_review, "_run_captured_stop_aware", return_value=version),
                  mock.patch.object(llm_review.subprocess, "Popen") as popen):
                error = llm_review._codex_windows_filesystem_preflight(
                    str(binary), probe, payload, expected_version="0.148.0",
                    expected_sha256="0" * 64)

        self.assertIn("SHA256 mismatch", error)
        popen.assert_not_called()

    def test_sandbox_preflight_failure_happens_before_clone_or_provider(self) -> None:
        translator = CodexJsonTranslator()
        with tempfile.TemporaryDirectory(prefix="sts2-codex-sandbox-test-") as root:
            sandbox_root = Path(root) / "sts2-review-sandbox-test"
            sandbox_root.mkdir()
            with (mock.patch.object(
                      llm_review, "_new_review_temp", return_value=sandbox_root),
                  mock.patch.object(
                      llm_review, "_normalize_windows_review_sandbox_acl"),
                  mock.patch.object(
                      llm_review, "_codex_windows_filesystem_preflight",
                      return_value=("Codex Windows filesystem capability failed: "
                                    "path contains a reparse point")),
                  mock.patch.object(
                      llm_review, "_run_captured_stop_aware") as run_process):
                result = llm_review._run_review_sandbox(
                    ["codex.exe", "exec", "-C", str(Path(root) / "repo")],
                    "prompt", "a" * 40, 60, translator, runner="codex",
                    codex_expected_version="0.148.0",
                    codex_expected_sha256="1" * 64,
                    log=lambda _message: None)

        self.assertEqual(result.failure_code, "runner_codex_filesystem_preflight")
        self.assertFalse(result.provider_work_started)
        self.assertEqual(result.provider_metrics.get("event_count"), 0)
        run_process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
