"""Regressions for long reviews, 100-run batches, and failed-review salvage."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402
import autogit  # noqa: E402


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True, encoding="utf-8", errors="replace")


class ReviewConfigurationTests(unittest.TestCase):
    def test_long_review_and_large_batch_defaults_are_consistent(self) -> None:
        cfg = llm_review.load_llm_config()
        self.assertEqual(cfg["timeout_min"], 480)
        self.assertEqual(cfg["preferred_timeout_min"], 480)
        self.assertEqual(cfg["max_runs_in_packet"], 100)
        self.assertEqual(cfg["review_queue_max"], 100)
        self.assertEqual(cfg["stall_warn_min"], 15)
        self.assertEqual(cfg["stall_timeout_min"], 30)
        self.assertEqual(cfg["pre_work_timeout_min"], 5)
        self.assertEqual(
            cfg["preferred_models"],
            ["opencode-go/glm-5.3-flash@max", "amd-radeon/DeepSeek-V4-Flash"],
        )
        self.assertEqual(int(cfg["timeout_min"] * 60), 28800)

    def test_stream_keeps_full_file_but_only_bounded_memory_tail(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-stream-tail-") as root:
            stream = Path(root) / "review.stream"
            command = [sys.executable, "-c", "import sys;sys.stdout.write('x'*400000)"]
            with (mock.patch.object(llm_review, "LIVE_STREAM", stream),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                rc, tail, timed_out, stopped, stalled = llm_review._stream_run(command, 30)
            stream_size = stream.stat().st_size
        self.assertEqual(rc, 0)
        self.assertFalse(timed_out)
        self.assertFalse(stopped)
        self.assertFalse(stalled)
        self.assertLessEqual(len(tail), 256 * 1024)
        self.assertGreater(stream_size, len(tail))

    def test_stream_small_flushed_bytes_reset_stall_without_newline_or_8k_fill(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-stream-buffer-") as root:
            stream = Path(root) / "review.stream"
            command = [
                sys.executable, "-c",
                "import sys,time\n"
                "for _ in range(6):\n"
                " sys.stdout.write('x');sys.stdout.flush();time.sleep(0.25)\n"
                "sys.stdout.write('\\n');sys.stdout.flush()",
            ]
            with (mock.patch.object(llm_review, "LIVE_STREAM", stream),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                rc, tail, timed_out, stopped, stalled = llm_review._stream_run(
                    command, 5, stall_warn_sec=0.6, stall_timeout_sec=1.0)
        self.assertEqual(rc, 0)
        self.assertFalse(timed_out)
        self.assertFalse(stopped)
        self.assertFalse(stalled)
        self.assertIn("xxxxxx", tail)

    def _legacy_stream_clean_eof_os_process_probe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-stream-eof-") as root:
            stream = Path(root) / "review.stream"
            command = [os.environ.get("COMSPEC", "cmd.exe"),
                       "/d", "/s", "/c", "echo done"]

            def slow_translate(raw: str) -> list[str]:
                import time
                time.sleep(0.75)
                return [raw]

            with (mock.patch.object(llm_review, "LIVE_STREAM", stream),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                rc, tail, timed_out, stopped, stalled = llm_review._stream_run(
                    command, 5, translate=slow_translate,
                    stall_warn_sec=0.25, stall_timeout_sec=0.5)
        self.assertEqual(rc, 0)
        self.assertFalse(timed_out)
        self.assertFalse(stopped)
        self.assertFalse(stalled)
        self.assertIn("done", tail)

    def test_stream_clean_eof_wins_over_stall_after_slow_final_translation(self) -> None:
        import threading
        with tempfile.TemporaryDirectory(prefix="sts2-stream-eof-") as root:
            stream = Path(root) / "review.stream"
            translation_started = threading.Event()
            eof_seen = threading.Event()

            class FakeStdout:
                def __init__(self, owner) -> None:
                    self.owner = owner
                    self.buffer = self
                    self.reads = 0

                def read1(self, _size):
                    self.reads += 1
                    if self.reads == 1:
                        return b"done\n"
                    if not translation_started.wait(timeout=2):
                        raise AssertionError("translator never consumed final line")
                    self.owner.returncode = 0
                    eof_seen.set()
                    return b""


                def read(self, size):
                    return self.read1(size)
                def close(self) -> None:
                    pass

            class FakeProc:
                def __init__(self) -> None:
                    self.returncode = None
                    self.killed = False
                    self.stdout = FakeStdout(self)

                def poll(self):
                    return self.returncode

                def wait(self, timeout=None):
                    if not eof_seen.wait(timeout=timeout or 2):
                        raise subprocess.TimeoutExpired("fake", timeout)
                    return self.returncode

                def kill(self) -> None:
                    self.killed = True
                    self.returncode = -9

            fake = FakeProc()

            def slow_translate(raw: str) -> list[str]:
                translation_started.set()
                if not eof_seen.wait(timeout=2):
                    raise AssertionError("reader did not observe EOF during translation")
                time.sleep(0.75)
                return [raw]

            with (mock.patch.object(llm_review.subprocess, "Popen", return_value=fake),
                  mock.patch.object(llm_review, "LIVE_STREAM", stream),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                result = llm_review._stream_run(
                    ["fake-provider"], 5, translate=slow_translate,
                    stall_warn_sec=0.25, stall_timeout_sec=0.5)
        self.assertTrue(eof_seen.is_set())
        self.assertFalse(fake.killed)
        self.assertEqual(result, (0, "done\n", False, False, False))



    def test_stream_backlog_is_not_misclassified_as_raw_output_stall(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-stream-backlog-") as root:
            stream = Path(root) / "review.stream"
            command = [
                sys.executable, "-c",
                "import sys,time\n"
                "for value in range(30):\n"
                " print(value,flush=True);time.sleep(0.05)",
            ]
            import threading
            import time
            real_queue = llm_review.queue.Queue
            backlog_ready = threading.Event()

            class ObservedQueue(real_queue):
                def put(self, item, *args, **kwargs):
                    result = super().put(item, *args, **kwargs)
                    if self.qsize() >= 2:
                        backlog_ready.set()
                    return result

            first_line = True

            def slow_first_translation(raw: str) -> list[str]:
                nonlocal first_line
                if first_line:
                    first_line = False
                    if not backlog_ready.wait(timeout=5):
                        raise AssertionError("reader did not establish a test backlog")
                    # Longer than the watchdog, while the child continues to
                    # produce raw chunks behind this host-side translation.
                    time.sleep(0.75)
                return [raw]

            with (mock.patch.object(llm_review.queue, "Queue", ObservedQueue),
                  mock.patch.object(llm_review, "LIVE_STREAM", stream),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                rc, _tail, timed_out, stopped, stalled = llm_review._stream_run(
                    command, 5, translate=slow_first_translation,
                    stall_warn_sec=0.25, stall_timeout_sec=0.5)
            text = stream.read_text(encoding="utf-8")
        self.assertEqual(rc, 0)
        self.assertFalse(timed_out)
        self.assertFalse(stopped)
        self.assertFalse(stalled)
        diagnostics = [line for line in text.splitlines() if "qsize=" in line]
        self.assertTrue(all("qsize=0" in line for line in diagnostics))

    def test_stream_true_stall_records_pipe_state_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-stream-stall-") as root:
            stream = Path(root) / "review.stream"
            command = [
                sys.executable, "-c",
                "import sys,time;print('started',flush=True);time.sleep(5)",
            ]
            with (mock.patch.object(llm_review, "LIVE_STREAM", stream),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                _rc, _tail, timed_out, stopped, stalled = llm_review._stream_run(
                    command, 10, stall_warn_sec=0.05, stall_timeout_sec=0.1)
            text = stream.read_text(encoding="utf-8")
        self.assertFalse(timed_out)
        self.assertFalse(stopped)
        self.assertTrue(stalled)
        self.assertIn("qsize=0", text)
        self.assertIn("reader_done=False", text)
        self.assertIn("proc_poll=None", text)
        self.assertIn("last_raw_idle=", text)

    def test_codex_error_heartbeats_cannot_extend_prework_forever(self) -> None:
        import threading

        with tempfile.TemporaryDirectory(prefix="sts2-stream-prework-") as root:
            stream = Path(root) / "review.stream"
            payload = "".join(
                json.dumps({"type": "error", "message": f"reconnect {index}"})
                + "\n"
                for index in range(10)
            ).encode("utf-8")

            class HeartbeatStdout:
                def __init__(self, owner) -> None:
                    self.owner = owner
                    self.sent = False

                def read1(self, _size):
                    if not self.sent:
                        self.sent = True
                        return payload
                    self.owner.terminated.wait(timeout=2)
                    return b""

                def read(self, size):
                    return self.read1(size)

                def close(self) -> None:
                    self.owner.terminated.set()

            class HeartbeatProc:
                def __init__(self) -> None:
                    self.pid = None
                    self.returncode = None
                    self.killed = False
                    self.terminated = threading.Event()
                    self.stdout = HeartbeatStdout(self)

                def poll(self):
                    return self.returncode

                def wait(self, timeout=None):
                    if not self.terminated.wait(timeout=timeout or 2):
                        raise subprocess.TimeoutExpired("fake-codex", timeout)
                    return self.returncode

                def kill(self) -> None:
                    self.killed = True
                    self.returncode = -9
                    self.terminated.set()

            fake = HeartbeatProc()
            translator = llm_review.CodexJsonTranslator()
            real_monotonic = time.monotonic

            # The old test raced two real watchdogs (0.5s raw stall versus
            # 0.7s pre-work) against Windows process startup.  Advance the
            # provider clock only after diagnostics prove that error events
            # are flowing, then cross the pre-work deadline deterministically.
            def controlled_monotonic() -> float:
                return 1.0 if translator.error_count >= 3 else 0.0

            started = real_monotonic()
            with (mock.patch.object(llm_review.subprocess, "Popen", return_value=fake),
                  mock.patch.object(llm_review.time, "monotonic",
                                    side_effect=controlled_monotonic),
                  mock.patch.object(llm_review, "LIVE_STREAM", stream),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                _rc, _tail, timed_out, stopped, stalled = llm_review._stream_run(
                    ["fake-codex"], 5, translate=translator.feed,
                    stall_timeout_sec=0.5, pre_work_timeout_sec=0.7)
            elapsed = real_monotonic() - started

        metrics = translator.metrics()
        self.assertFalse(timed_out)
        self.assertFalse(stopped)
        self.assertTrue(stalled)
        self.assertTrue(fake.killed)
        self.assertLess(elapsed, 2.0)
        self.assertGreaterEqual(metrics["error_count"], 3)
        self.assertFalse(metrics["model_work_started"])

    def test_model_work_switches_back_to_raw_output_stall_semantics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-stream-postwork-") as root:
            stream = Path(root) / "review.stream"
            command = [
                sys.executable, "-u", "-c",
                "import json,time;"
                "print(json.dumps({'type':'item.started','item':"
                "{'type':'reasoning','text':'thinking'}}),flush=True);"
                "time.sleep(3)",
            ]
            translator = llm_review.CodexJsonTranslator()
            started = time.monotonic()
            with (mock.patch.object(llm_review, "LIVE_STREAM", stream),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                _rc, _tail, timed_out, stopped, stalled = llm_review._stream_run(
                    command, 5, translate=translator.feed,
                    # This test exercises the *post-work* raw-output watchdog.
                    # Leave enough headroom for a contended Windows test runner
                    # to spawn the helper and dispatch its first JSON event, so
                    # the startup watchdog cannot win the race by accident.
                    stall_timeout_sec=0.8, pre_work_timeout_sec=2.0)
            elapsed = time.monotonic() - started

        self.assertFalse(timed_out)
        self.assertFalse(stopped)
        self.assertTrue(stalled)
        self.assertTrue(translator.metrics()["model_work_started"])
        self.assertGreaterEqual(elapsed, 0.65)

    def test_translator_part_memory_is_bounded(self) -> None:
        translator = llm_review.OpencodeJsonTranslator()
        for index in range(5000):
            translator.feed(json.dumps({
                "part": {"id": f"part-{index}-" + ("x" * 2000),
                         "type": "text", "text": "ok"},
            }))
        self.assertLessEqual(len(translator._seen), 4096)
        self.assertTrue(all(len(key) == 32 for key in translator._seen))

    def test_private_git_temp_cleanup_removes_readonly_loose_objects(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-private-git-cleanup-") as root:
            repo = Path(root) / "repo"
            temp_root = (repo / "sts2-ascend" / "knowledge" / "code_backups"
                         / "review_work" / "sts2-review-capture-index-old")
            loose = temp_root / "objects" / "ab" / "object"
            loose.parent.mkdir(parents=True)
            loose.write_bytes(b"git-object")
            loose.chmod(stat.S_IREAD)
            with mock.patch.object(llm_review, "REPO_DIR", repo):
                removed = llm_review._discard_owned_review_temp(
                    temp_root, "sts2-review-capture-index-",
                    log=lambda _message: None)
        self.assertTrue(removed)
        self.assertFalse(temp_root.exists())

    def test_private_git_temp_cleanup_retries_transient_lock_and_retains_persistent_lock(
            self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-private-git-retry-") as root:
            repo = Path(root) / "repo"
            work = (repo / "sts2-ascend" / "knowledge" / "code_backups"
                    / "review_work")
            transient = work / "sts2-review-validation-index-transient"
            transient.mkdir(parents=True)
            (transient / "object").write_text("x", encoding="utf-8")
            real_rmtree = llm_review.shutil.rmtree
            attempts = 0

            def flaky_rmtree(path, *args, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("scanner still holds the object")
                return real_rmtree(path, *args, **kwargs)

            with (mock.patch.object(llm_review, "REPO_DIR", repo),
                  mock.patch.object(llm_review.shutil, "rmtree",
                                    side_effect=flaky_rmtree)):
                removed = llm_review._discard_owned_review_temp(
                    transient, "sts2-review-validation-index-",
                    log=lambda _message: None)
            self.assertTrue(removed)
            self.assertEqual(attempts, 3)

            retained = work / "sts2-review-retry-index-retained"
            retained.mkdir(parents=True)
            messages: list[str] = []
            with (mock.patch.object(llm_review, "REPO_DIR", repo),
                  mock.patch.object(llm_review.shutil, "rmtree",
                                    side_effect=PermissionError("still locked"))):
                removed = llm_review._discard_owned_review_temp(
                    retained, "sts2-review-retry-index-", log=messages.append)
            self.assertFalse(removed)
            self.assertTrue(retained.is_dir())
            self.assertIn("still locked", messages[-1])

    def test_startup_temp_reaper_only_removes_stale_private_indexes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-private-git-reaper-") as root:
            repo = Path(root) / "repo"
            work = (repo / "sts2-ascend" / "knowledge" / "code_backups"
                    / "review_work")
            stale = [work / f"{prefix}old" for prefix in
                     llm_review._PRIVATE_GIT_TEMP_PREFIXES]
            recent = work / "sts2-review-capture-index-recent"
            evidence = work / "sts2-review-sandbox-evidence"
            for path in [*stale, recent, evidence]:
                path.mkdir(parents=True)
                (path / "keep").write_text("x", encoding="utf-8")
            old = time.time() - 600
            for path in stale:
                os.utime(path, (old, old))
            with mock.patch.object(llm_review, "REPO_DIR", repo):
                llm_review._cleanup_stale_private_git_temps(
                    log=lambda _message: None, min_age_sec=300)
            self.assertTrue(all(not path.exists() for path in stale))
            self.assertTrue(recent.is_dir())
            self.assertTrue(evidence.is_dir())


class ReviewSalvageTests(unittest.TestCase):
    def test_rejection_ledger_is_idempotent_and_requests_one_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-rejection-ledger-") as root:
            repo = Path(root) / "repo"
            base = repo / "sts2-ascend"
            salvage_root = base / "knowledge" / "code_backups" / "review_salvage"
            package = salvage_root / "20260827-130000-123456789-deadbeef"
            package.mkdir(parents=True)
            ledger = base / "REVIEW_REJECTIONS.md"
            commits = []

            def fake_commit(message, **kwargs):
                commits.append((message, kwargs))
                return SimpleNamespace(created=True, pushed=True, commit="a" * 40, reason="")

            fake_autogit = SimpleNamespace(
                commit_progress_result=fake_commit,
                push_pending=lambda **_kwargs: True,
            )
            manifest = {
                "time": "2026-08-27 13:00:00", "batch_runs": [731, 732],
                "pre_head": "deadbeef" * 5, "failure_kind": "path_boundary",
                "backend_key": "kimi-k3", "runner": "opencode",
                "model": "kimi-for-coding/k3", "stopped": False,
                "reason": "复盘 patch 越过 allowlist：tool-CACHE/result.bin",
            }
            with (mock.patch.object(llm_review, "BASE_DIR", base),
                  mock.patch.object(llm_review, "REPO_DIR", repo),
                  mock.patch.object(llm_review, "KNOWLEDGE_DIR", base / "knowledge"),
                  mock.patch.object(llm_review, "SALVAGE_ROOT", salvage_root),
                  mock.patch.object(llm_review, "REJECTION_LEDGER", ledger),
                  mock.patch.dict(sys.modules, {"autogit": fake_autogit}),
                  mock.patch.object(llm_review, "_flush_pending_rejection_ledger",
                                    return_value=True),
                  mock.patch.object(llm_review, "_upstream_ledger_contains",
                                    return_value=True),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                llm_review._record_review_rejection(package, manifest, log=lambda _msg: None)
                llm_review._record_review_rejection(package, manifest, log=lambda _msg: None)

            text = ledger.read_text(encoding="utf-8")
            self.assertEqual(text.count(f"<!-- rejection:{package.name} -->"), 1)
            self.assertIn("第 731~732 局", text)
            self.assertIn("tool-CACHE/result.bin", text)
            self.assertIn("kimi-k3 (opencode/kimi-for-coding/k3)", text)
            self.assertIn("待 kimi-k3 (opencode/kimi-for-coding/k3) 重审/补合", text)
            self.assertNotIn("待 GLM", text)
            self.assertEqual(len(commits), 1)
            self.assertEqual(commits[0][1]["paths"], ["sts2-ascend/REVIEW_REJECTIONS.md"])

    def test_salvage_is_atomic_idempotent_and_preserves_every_changed_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-salvage-") as root:
            base = Path(root)
            repo = base / "repo"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "test@example.invalid")
            _git(repo, "config", "user.name", "Test")
            policy = repo / "sts2-ascend" / "brain" / "policy.py"
            policy.parent.mkdir(parents=True)
            policy.write_text("VALUE = 1\n", encoding="utf-8")
            outside = repo / "outside.txt"
            outside.write_text("safe baseline\n", encoding="utf-8")
            (repo / ".gitignore").write_text(
                ".runtime/\n__pycache__/\n", encoding="utf-8")
            _git(repo, "add", "--all")
            _git(repo, "commit", "-qm", "baseline")
            pre_head = _git(repo, "rev-parse", "HEAD").stdout.strip()

            policy.write_text("VALUE = 2\n", encoding="utf-8")
            outside.write_text("SECRET_UNEXPECTED_CONTENT\n", encoding="utf-8")
            ignored = repo / ".runtime" / "rejected.bin"
            ignored.parent.mkdir()
            ignored.write_bytes(b"IGNORED_REJECTED_CONTENT")
            model_pyc = repo / "sts2-ascend" / "brain" / "__pycache__" / "model.pyc"
            model_pyc.parent.mkdir()
            model_pyc.write_bytes(b"MODEL_WRITTEN_PYC")
            result = llm_review.SandboxReviewResult(
                rc=0, out="model tail", error="复盘 patch 越过 allowlist")
            salvage_root = base / "salvage"
            prompt = repo / "sts2-ascend" / "knowledge" / "review_prompt_latest.md"
            with (mock.patch.object(llm_review, "REPO_DIR", repo),
                  mock.patch.object(llm_review, "PROMPT_FILE", prompt),
                  mock.patch.object(llm_review, "SALVAGE_ROOT", salvage_root)):
                llm_review._capture_sandbox_wip(repo, pre_head, result, log=lambda _msg: None)
                saved = llm_review._save_review_salvage(
                    pre_head, result.error, result, batch_runs=[601, 602],
                    model="opencode-go/glm-5.3-flash@max", source="preferred",
                    prompt_text="full task\n", invocation_prompt="short contract",
                    log=lambda _msg: None)
                saved_again = llm_review._save_review_salvage(
                    pre_head, "duplicate", result, log=lambda _msg: None)

            self.assertEqual(saved, saved_again)
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual([path.name for path in salvage_root.iterdir()], [saved.name])
            self.assertTrue((saved / "wip.patch").is_file())
            self.assertTrue((saved / "manifest.json").is_file())
            self.assertTrue((saved / "report.md").is_file())
            self.assertEqual(
                (saved / "review_prompt.md").read_text(encoding="utf-8"),
                "full task\n")
            self.assertEqual(
                (saved / "invocation_prompt.txt").read_text(encoding="utf-8"),
                "short contract")
            self.assertTrue((saved / "file_states.json").is_file())
            patch = (saved / "wip.patch").read_bytes()
            self.assertIn(b"sts2-ascend/brain/policy.py", patch)
            self.assertIn(b"outside.txt", patch)
            self.assertIn(b"SECRET_UNEXPECTED_CONTENT", patch)
            self.assertIn(b".runtime/rejected.bin", patch)
            self.assertEqual(
                (saved / "files" / "outside.txt").read_text(encoding="utf-8"),
                "SECRET_UNEXPECTED_CONTENT\n")
            self.assertEqual(
                (saved / "files" / ".runtime" / "rejected.bin").read_bytes(),
                b"IGNORED_REJECTED_CONTENT")
            self.assertEqual(
                (saved / "files" / "sts2-ascend" / "brain" / "__pycache__"
                 / "model.pyc").read_bytes(),
                b"MODEL_WRITTEN_PYC")
            manifest = json.loads((saved / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["failure_kind"], "path_boundary")
            self.assertEqual(manifest["allowed_paths"], ["sts2-ascend/brain/policy.py"])
            self.assertEqual(
                set(manifest["rejected_or_unexpected_paths"]),
                {".runtime/rejected.bin", "outside.txt"})
            self.assertEqual(
                manifest["transient_artifact_paths"],
                ["sts2-ascend/brain/__pycache__/model.pyc"])
            self.assertEqual(manifest["online_runtime_paths"], [])
            self.assertEqual(
                set(manifest["all_paths"]),
                {".runtime/rejected.bin", "outside.txt", "sts2-ascend/brain/policy.py",
                 "sts2-ascend/brain/__pycache__/model.pyc"})
            self.assertFalse(manifest["auto_apply"])
            self.assertEqual(manifest["selfcheck_state"], "not_run")
            self.assertIsNone(manifest["selfcheck_ok"])
            self.assertEqual(manifest["prompt_snapshot"], "review_prompt.md")
            self.assertEqual(manifest["prompt_bytes"], len("full task\n".encode("utf-8")))
            self.assertEqual(
                manifest["prompt_sha256"],
                hashlib.sha256(b"full task\n").hexdigest())

    def test_stopped_review_publishes_partial_salvage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-salvage-stop-") as root:
            salvage_root = Path(root) / "salvage"
            result = llm_review.SandboxReviewResult(
                stopped=True, wip_patch=b"partial patch",
                wip_paths=("sts2-ascend/brain/policy.py",),
                allowed_paths=("sts2-ascend/brain/policy.py",))
            with mock.patch.object(llm_review, "SALVAGE_ROOT", salvage_root):
                saved = llm_review._save_review_salvage(
                    "a" * 40, "整套停止", result,
                    runner="opencode", model="kimi-for-coding/k3",
                    backend_key="kimi-k3", log=lambda _msg: None)
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual((saved / "wip.patch").read_bytes(), b"partial patch")
            manifest = json.loads((saved / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["stopped"])
            self.assertEqual(manifest["failure_kind"], "lifecycle_stop")
            self.assertEqual(
                manifest["backend_label"],
                "kimi-k3 (opencode/kimi-for-coding/k3)")
            self.assertIn("维护停机取消 kimi-k3", manifest["reason"])
            self.assertIn("非模型提交失败", manifest["reason"])
            self.assertIn("kimi-k3 (opencode/kimi-for-coding/k3)",
                          manifest["inspection_hint"])
            self.assertFalse(manifest["auto_apply"])

    def test_old_model_spliced_kimi_lifecycle_row_is_neutralized_once(
            self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-ledger-label-migration-") as root:
            repo = Path(root) / "repo"
            ledger = repo / "sts2-ascend" / "REVIEW_REJECTIONS.md"
            ledger.parent.mkdir(parents=True)
            package = "20260829-230230-123456789-65abad11"
            ledger.write_text(
                llm_review._REJECTION_LEDGER_HEADER.replace(
                    "# 复盘拒合与维护中断批次清单",
                    "# GLM 复盘拒合批次清单").replace(
                        llm_review._REJECTION_LEDGER_SCHEMA_MARKER + "\n", "")
                + f"<!-- rejection:{package} -->\n"
                + "| 2026-08-29 23:14:22 | 第 1081~1085 局 | `65abad11` | "
                  "lifecycle_stop | kimi-for-coding/k3 | "
                  "维护中断/取消；kimi-for-coding/k3 已补合并闭环 `ac26841f` | "
                  "（闭环清理） | "
                  "GLM 重审结论与提交 ac26841f 已推送 |\n",
                encoding="utf-8")
            commits = []

            def fake_commit(message, **kwargs):
                commits.append((message, kwargs))
                return SimpleNamespace(
                    created=True, pushed=False, commit="b" * 40, reason="")

            fake_autogit = SimpleNamespace(
                commit_progress_result=fake_commit,
                push_pending=lambda **_kwargs: True,
            )
            with (mock.patch.object(llm_review, "REPO_DIR", repo),
                  mock.patch.object(llm_review, "REJECTION_LEDGER", ledger),
                  mock.patch.object(llm_review, "_review_stop_requested",
                                    return_value=False),
                  mock.patch.object(llm_review, "_flush_pending_rejection_ledger",
                                    return_value=True),
                  mock.patch.dict(sys.modules, {"autogit": fake_autogit})):
                self.assertTrue(llm_review._migrate_rejection_ledger_labels(
                    log=lambda _message: None))
                future_status = (
                    "luna-max (codex/gpt-5.6-luna@max) 已补合并闭环 `deadbeef`")
                with ledger.open("a", encoding="utf-8") as handle:
                    handle.write(llm_review._rejection_ledger_block(
                        "future-precise", {
                            "time": "2026-08-30 01:00:00", "batch_runs": [1090],
                            "pre_head": "d" * 40, "failure_kind": "process_exit",
                            "backend_key": "kimi-k3", "runner": "opencode",
                            "model": "kimi-for-coding/k3",
                        }, status=future_status, package_cell="closed", reason="done"))
                self.assertTrue(llm_review._migrate_rejection_ledger_labels(
                    log=lambda _message: None))

            text = ledger.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# 复盘拒合与维护中断批次清单\n"))
            self.assertEqual(text.count(llm_review._REJECTION_LEDGER_SCHEMA_MARKER), 1)
            self.assertIn("维护中断/取消（lifecycle_stop）", text)
            self.assertIn(
                "维护中断/取消；复盘已补合并闭环 `ac26841f`",
                text)
            self.assertNotIn("kimi-for-coding/k3 已补合", text)
            self.assertIn("复盘重审结论与提交 ac26841f 已推送", text)
            self.assertIn("非模型提交失败", text)
            self.assertNotIn("GLM 已补合", text)
            self.assertIn(future_status, text)
            self.assertEqual(len(commits), 1)
            self.assertEqual(
                commits[0][1]["paths"],
                ["sts2-ascend/REVIEW_REJECTIONS.md"])

    def test_rejection_label_migration_reports_failed_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-ledger-migration-commit-") as root:
            repo = Path(root) / "repo"
            ledger = repo / "sts2-ascend" / "REVIEW_REJECTIONS.md"
            ledger.parent.mkdir(parents=True)
            old_text = "# GLM 复盘拒合批次清单\n"
            ledger.write_text(old_text, encoding="utf-8")
            fake_autogit = SimpleNamespace(
                commit_progress_result=lambda *_args, **_kwargs: SimpleNamespace(
                    created=False, pushed=False, commit="", reason="commit failed"),
                push_pending=lambda **_kwargs: False,
            )
            with (mock.patch.object(llm_review, "REPO_DIR", repo),
                  mock.patch.object(llm_review, "REJECTION_LEDGER", ledger),
                  mock.patch.object(llm_review, "_review_stop_requested",
                                    return_value=False),
                  mock.patch.object(llm_review, "_flush_pending_rejection_ledger",
                                    return_value=True),
                  mock.patch.object(llm_review, "_ledger_text_at_head",
                                    return_value=old_text),
                  mock.patch.dict(sys.modules, {"autogit": fake_autogit})):
                migrated = llm_review._migrate_rejection_ledger_labels(
                    log=lambda _message: None)

            self.assertFalse(migrated)
            migrated_text = ledger.read_text(encoding="utf-8")
            self.assertTrue(migrated_text.startswith(
                "# 复盘拒合与维护中断批次清单\n"))
            self.assertIn(llm_review._REJECTION_LEDGER_SCHEMA_MARKER,
                          migrated_text)

    def test_lifecycle_stop_outranks_exit_timeout_and_stall(self) -> None:
        result = llm_review.SandboxReviewResult(
            rc=1, stopped=True, timed_out=True, stalled=True,
            error="复盘进程未成功完成")
        self.assertEqual(
            llm_review._salvage_kind(result.error, result),
            "lifecycle_stop",
        )

    def test_lifecycle_stop_is_salvaged_without_model_cooldown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-stop-kind-") as root:
            repo = Path(root) / "repo"
            prompt = repo / "sts2-ascend" / "knowledge" / "review_prompt_latest.md"
            prompt.parent.mkdir(parents=True)
            status: dict = {}
            know = SimpleNamespace(
                stats={"global": {"runs": 8}}, progression={}, save=mock.Mock())
            sandbox = llm_review.SandboxReviewResult(
                rc=1, stopped=True, error="复盘进程未成功完成")
            cfg = {
                "enabled": True, "runner": "opencode", "opencode_bin": "opencode",
                "model": "fallback", "preferred_timeout_min": 480,
                "stall_warn_min": 15, "stall_timeout_min": 30,
            }
            with (mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
                  mock.patch.object(llm_review.shutil, "which", return_value="opencode"),
                  mock.patch.object(llm_review, "REPO_DIR", repo),
                  mock.patch.object(llm_review, "PROMPT_FILE", prompt),
                  mock.patch.object(llm_review, "build_prompt", return_value="prompt"),
                  mock.patch.object(llm_review, "_run_review_sandbox",
                                    return_value=sandbox),
                  mock.patch.object(llm_review, "_save_review_salvage",
                                    return_value=Path(root) / "pkg") as save,
                  mock.patch.object(llm_review, "_review_stop_requested",
                                    return_value=False),
                  mock.patch.object(llm_review, "_stream_begin"),
                  mock.patch.object(llm_review, "_stream_end"),
                  mock.patch.object(llm_review, "_launch_viewer"),
                  mock.patch.object(llm_review, "_launch_speaker"),
                  mock.patch.object(llm_review, "_mark_preferred_failure") as mark,
                  mock.patch.object(autogit, "commit_progress_result"),
                  mock.patch.object(autogit, "head", return_value="a" * 40),
                  mock.patch.object(autogit, "set_review_active"),
                  mock.patch.object(autogit, "push_pending", return_value=True)):
                changed = llm_review.run_review(
                    know, log=lambda _message: None,
                    model="glm@max", every=1, source="preferred",
                    batch_runs=[8], async_mode=True, _status=status,
                )

            self.assertFalse(changed)
            self.assertEqual(status["outcome"], "canceled")
            self.assertTrue(status["canceled"])
            mark.assert_not_called()
            self.assertEqual(save.call_args.args[1], "统一停机中断并全量保全")

    def test_replay_evidence_preflight_is_deferred_without_model_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-preflight-") as root:
            repo = Path(root) / "repo"
            prompt = repo / "sts2-ascend" / "knowledge" / "review_prompt_latest.md"
            prompt.parent.mkdir(parents=True)
            status: dict = {}
            know = SimpleNamespace(
                stats={"global": {"runs": 1085}}, progression={}, save=mock.Mock())
            evidence_error = "retry evidence schema 3 candidate is unavailable"
            sandbox = llm_review.SandboxReviewResult(
                rc=-1,
                error="failed-package evidence unavailable: " + evidence_error,
                replay_evidence_requested=True,
                replay_evidence_complete=False,
                replay_evidence_error=evidence_error,
                replay_evidence_model_started=False,
                provider_work_started=False,
            )
            cfg = {
                "enabled": True, "runner": "codex", "codex_bin": "codex.CMD",
                "model": "gpt-5.6-luna", "preferred_timeout_min": 480,
                "stall_warn_min": 15, "stall_timeout_min": 30,
                "pre_work_timeout_min": 5,
            }
            with (mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
                  mock.patch.object(llm_review, "runner_binary",
                                    return_value="codex.CMD"),
                  mock.patch.object(llm_review, "REPO_DIR", repo),
                  mock.patch.object(llm_review, "PROMPT_FILE", prompt),
                  mock.patch.object(llm_review, "build_prompt", return_value="prompt"),
                  mock.patch.object(llm_review, "build_review_command",
                                    return_value=["codex.CMD", "exec"]),
                  mock.patch.object(llm_review, "_run_review_sandbox",
                                    return_value=sandbox),
                  mock.patch.object(llm_review, "_save_review_salvage") as save,
                  mock.patch.object(llm_review, "_review_stop_requested",
                                    return_value=False),
                  mock.patch.object(llm_review, "_stream_begin"),
                  mock.patch.object(llm_review, "_stream_end"),
                  mock.patch.object(llm_review, "_launch_viewer"),
                  mock.patch.object(llm_review, "_launch_speaker"),
                  mock.patch.object(llm_review, "_mark_preferred_failure") as mark,
                  mock.patch.object(autogit, "commit_progress_result"),
                  mock.patch.object(autogit, "head", return_value="a" * 40),
                  mock.patch.object(autogit, "set_review_active"),
                  mock.patch.object(autogit, "push_pending", return_value=True)):
                changed = llm_review.run_review(
                    know, log=lambda _message: None,
                    runner="codex", model="gpt-5.6-luna",
                    backend_key="luna-max", reasoning_effort="max",
                    approve_for_me=True, every=1, source="preferred",
                    batch_runs=[1085], async_mode=True, _status=status,
                    salvage_packages=["pkg-target"])

            self.assertFalse(changed)
            self.assertEqual(status["outcome"], "deferred")
            self.assertEqual(
                status["deferred_kind"], "replay_evidence_preflight")
            self.assertEqual(status["reason"], evidence_error)
            self.assertFalse(status["startup_unavailable"])
            self.assertFalse(status["provider_launch_attempted"])
            self.assertFalse(status["provider_work_started"])
            save.assert_not_called()
            mark.assert_not_called()

    def test_started_provider_rc_failure_remains_a_model_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-provider-failure-") as root:
            repo = Path(root) / "repo"
            prompt = repo / "sts2-ascend" / "knowledge" / "review_prompt_latest.md"
            prompt.parent.mkdir(parents=True)
            status: dict = {}
            know = SimpleNamespace(
                stats={"global": {"runs": 1085}}, progression={}, save=mock.Mock())
            sandbox = llm_review.SandboxReviewResult(
                rc=17,
                error="provider process failed",
                replay_evidence_requested=True,
                replay_evidence_complete=False,
                replay_evidence_model_started=True,
                provider_work_started=True,
            )
            cfg = {
                "enabled": True, "runner": "codex", "codex_bin": "codex.CMD",
                "model": "gpt-5.6-luna", "preferred_timeout_min": 480,
                "stall_warn_min": 15, "stall_timeout_min": 30,
                "pre_work_timeout_min": 5,
            }
            saved_package = Path(root) / "pkg-new-attempt"
            with (mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
                  mock.patch.object(llm_review, "runner_binary",
                                    return_value="codex.CMD"),
                  mock.patch.object(llm_review, "REPO_DIR", repo),
                  mock.patch.object(llm_review, "PROMPT_FILE", prompt),
                  mock.patch.object(llm_review, "build_prompt", return_value="prompt"),
                  mock.patch.object(llm_review, "build_review_command",
                                    return_value=["codex.CMD", "exec"]),
                  mock.patch.object(llm_review, "_run_review_sandbox",
                                    return_value=sandbox),
                  mock.patch.object(llm_review, "_save_review_salvage",
                                    return_value=saved_package) as save,
                  mock.patch.object(llm_review, "_review_stop_requested",
                                    return_value=False),
                  mock.patch.object(llm_review, "_stream_begin"),
                  mock.patch.object(llm_review, "_stream_end"),
                  mock.patch.object(llm_review, "_launch_viewer"),
                  mock.patch.object(llm_review, "_launch_speaker"),
                  mock.patch.object(llm_review, "_mark_preferred_failure") as mark,
                  mock.patch.object(autogit, "commit_progress_result"),
                  mock.patch.object(autogit, "head", return_value="a" * 40),
                  mock.patch.object(autogit, "set_review_active"),
                  mock.patch.object(autogit, "push_pending", return_value=True)):
                changed = llm_review.run_review(
                    know, log=lambda _message: None,
                    runner="codex", model="gpt-5.6-luna",
                    backend_key="luna-max", reasoning_effort="max",
                    approve_for_me=True, every=1, source="preferred",
                    batch_runs=[1085], async_mode=True, _status=status,
                    salvage_packages=["pkg-target"])

            self.assertFalse(changed)
            self.assertEqual(status["outcome"], "failed")
            self.assertNotIn("deferred_kind", status)
            self.assertFalse(status["startup_unavailable"])
            self.assertTrue(status["provider_work_started"])
            save.assert_called_once()
            mark.assert_called_once()

    def test_stopped_raw_clone_is_deferred_then_recovered_by_new_worker(self) -> None:
        raw = Path(tempfile.mkdtemp(prefix="sts2-review-sandbox-"))
        snapshot = Path(tempfile.mkdtemp(prefix="sts2-review-snapshot-"))
        try:
            source_file = raw / "repo" / ".ignored" / "rejected.bin"
            source_file.parent.mkdir(parents=True)
            source_file.write_bytes(b"complete stopped evidence")
            (raw / "escaped-sibling.txt").write_text(
                "outside repo but inside sandbox root\n", encoding="utf-8")
            (snapshot / "files").mkdir()
            (snapshot / "files" / "partial.bin").write_bytes(b"partial snapshot evidence")
            (snapshot / "wip.patch").write_bytes(b"partial patch")
            (snapshot / "file_states.json").write_text("[]\n", encoding="utf-8")
            with tempfile.TemporaryDirectory(prefix="sts2-salvage-deferred-") as root:
                salvage_root = Path(root) / "salvage"
                result = llm_review.SandboxReviewResult(
                    stopped=True, error="复盘进程未成功完成",
                    retained_sandbox_dir=str(raw), snapshot_dir=str(snapshot))
                with mock.patch.object(llm_review, "SALVAGE_ROOT", salvage_root):
                    saved = llm_review._save_review_salvage(
                        "b" * 40, result.error, result, log=lambda _msg: None)
                    self.assertIsNotNone(saved)
                    assert saved is not None
                    self.assertTrue((saved / "raw_sandbox_pointer.txt").is_file())
                    self.assertTrue((saved / "snapshot_pointer.txt").is_file())
                    self.assertTrue(raw.exists())
                    self.assertTrue(snapshot.exists())
                    self.assertFalse((saved / "raw_sandbox").exists())

                    llm_review._recover_deferred_salvages(log=lambda _msg: None)

                    self.assertFalse((saved / "raw_sandbox_pointer.txt").exists())
                    self.assertFalse((saved / "snapshot_pointer.txt").exists())
                    self.assertFalse(raw.exists())
                    self.assertFalse(snapshot.exists())
                    self.assertEqual(
                        (saved / "raw_sandbox" / "repo" / ".ignored"
                         / "rejected.bin").read_bytes(),
                        b"complete stopped evidence")
                    self.assertEqual(
                        (saved / "raw_sandbox" / "escaped-sibling.txt").read_text(
                            encoding="utf-8"),
                        "outside repo but inside sandbox root\n")
                    self.assertEqual(
                        (saved / "captured_snapshot" / "files" / "partial.bin").read_bytes(),
                        b"partial snapshot evidence")
                    manifest = json.loads(
                        (saved / "manifest.json").read_text(encoding="utf-8"))
                    self.assertTrue(manifest["raw_sandbox_included"])
                    self.assertFalse(manifest["raw_sandbox_deferred"])
        finally:
            if raw.exists():
                shutil.rmtree(raw, ignore_errors=True)
            if snapshot.exists():
                shutil.rmtree(snapshot, ignore_errors=True)

    def test_deferred_recovery_completes_existing_partial_targets(self) -> None:
        raw = Path(tempfile.mkdtemp(prefix="sts2-review-sandbox-"))
        snapshot = Path(tempfile.mkdtemp(prefix="sts2-review-snapshot-"))
        try:
            (raw / "repo").mkdir()
            (raw / "repo" / "complete.txt").write_text("raw complete\n", encoding="utf-8")
            (snapshot / "files").mkdir()
            (snapshot / "files" / "complete.txt").write_text(
                "snapshot complete\n", encoding="utf-8")
            with tempfile.TemporaryDirectory(prefix="sts2-salvage-partial-") as root:
                salvage_root = Path(root) / "salvage"
                package = salvage_root / "package"
                (package / "raw_sandbox" / "repo").mkdir(parents=True)
                (package / "captured_snapshot" / "files").mkdir(parents=True)
                (package / "raw_sandbox" / "repo" / "partial.txt").write_text(
                    "keep raw partial\n", encoding="utf-8")
                (package / "captured_snapshot" / "files" / "partial.txt").write_text(
                    "keep snapshot partial\n", encoding="utf-8")
                (package / "raw_sandbox_pointer.txt").write_text(
                    str(raw) + "\n", encoding="utf-8")
                (package / "snapshot_pointer.txt").write_text(
                    str(snapshot) + "\n", encoding="utf-8")
                (package / "manifest.json").write_text(json.dumps({
                    "raw_sandbox_included": False,
                    "raw_sandbox_deferred": True,
                    "snapshot_included": False,
                    "snapshot_deferred": True,
                }), encoding="utf-8")
                with mock.patch.object(llm_review, "SALVAGE_ROOT", salvage_root):
                    llm_review._recover_deferred_salvages(log=lambda _msg: None)

                self.assertEqual(
                    (package / "raw_sandbox" / "repo" / "complete.txt").read_text(
                        encoding="utf-8"), "raw complete\n")
                self.assertEqual(
                    (package / "captured_snapshot" / "files" / "complete.txt").read_text(
                        encoding="utf-8"), "snapshot complete\n")
                self.assertTrue(
                    (package / "raw_sandbox" / "repo" / "partial.txt").is_file())
                self.assertTrue(
                    (package / "captured_snapshot" / "files" / "partial.txt").is_file())
                manifest = json.loads(
                    (package / "manifest.json").read_text(encoding="utf-8"))
                self.assertTrue(manifest["raw_sandbox_included"])
                self.assertTrue(manifest["snapshot_included"])
                self.assertFalse((package / "raw_sandbox_pointer.txt").exists())
                self.assertFalse((package / "snapshot_pointer.txt").exists())
        finally:
            if raw.exists():
                shutil.rmtree(raw, ignore_errors=True)
            if snapshot.exists():
                shutil.rmtree(snapshot, ignore_errors=True)

    def test_stop_arriving_during_snapshot_copy_publishes_full_source_pointer(self) -> None:
        snapshot = Path(tempfile.mkdtemp(prefix="sts2-review-snapshot-"))
        try:
            (snapshot / "files").mkdir()
            payload = b"z" * (2 * 1024 * 1024)
            (snapshot / "files" / "large.bin").write_bytes(payload)
            (snapshot / "wip.patch").write_bytes(b"patch")
            (snapshot / "file_states.json").write_text("[]\n", encoding="utf-8")
            with tempfile.TemporaryDirectory(prefix="sts2-salvage-mid-stop-") as root:
                salvage_root = Path(root) / "salvage"
                result = llm_review.SandboxReviewResult(
                    error="复盘自检失败", snapshot_dir=str(snapshot),
                    snapshot_complete=True, selfcheck_ok=False)
                stop_checks = 0

                def stop_during_copy() -> bool:
                    nonlocal stop_checks
                    stop_checks += 1
                    return stop_checks >= 2

                with (mock.patch.object(llm_review, "SALVAGE_ROOT", salvage_root),
                      mock.patch.object(
                          llm_review, "_review_stop_requested",
                          side_effect=stop_during_copy)):
                    saved = llm_review._save_review_salvage(
                        "c" * 40, result.error, result, log=lambda _msg: None)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertTrue((saved / "snapshot_pointer.txt").is_file())
                self.assertTrue(snapshot.exists())

                with (mock.patch.object(llm_review, "SALVAGE_ROOT", salvage_root),
                      mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                    llm_review._recover_deferred_salvages(log=lambda _msg: None)
                self.assertFalse((saved / "snapshot_pointer.txt").exists())
                self.assertFalse(snapshot.exists())
                self.assertEqual(
                    (saved / "captured_snapshot" / "files" / "large.bin").read_bytes(),
                    payload)
        finally:
            if snapshot.exists():
                shutil.rmtree(snapshot, ignore_errors=True)


class ReviewQueueBatchTests(unittest.TestCase):
    def test_default_worker_batch_takes_100_and_preserves_the_rest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-queue-100-") as root:
            queue_path = Path(root) / "review_queue.json"
            queue_path.write_text(json.dumps({
                "pending": [{"run": run} for run in range(1, 106)],
                "reviewing": None,
            }), encoding="utf-8")
            agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)
            batches: list[list[int]] = []

            def complete(_agent, batch, _log):
                batches.append([item["run"] for item in batch])
                agent.request_restart = True
                return "completed"

            with (mock.patch.object(llm_review, "QUEUE_FILE", queue_path),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
                  mock.patch.object(llm_review, "_wait_review_stop", return_value=False),
                  mock.patch.object(llm_review, "_kill_orphan_review_processes"),
                  mock.patch.object(llm_review, "_cleanup_stale_private_git_temps"),
                  mock.patch.object(llm_review, "_recover_deferred_salvages"),
                  mock.patch.object(llm_review, "_recover_unpointed_review_sandboxes"),
                  mock.patch.object(llm_review, "_recover_committed_retry_resolutions"),
                  mock.patch.object(llm_review, "_recover_salvage_replay_queue"),
                  mock.patch.object(llm_review, "_backfill_rejection_ledger"),
                  mock.patch.object(llm_review, "_resume_host_salvage_closures"),
                  mock.patch.object(llm_review, "load_llm_config", return_value={}),
                  mock.patch.object(llm_review, "_run_batch_review", side_effect=complete)):
                llm_review._worker_loop(agent, log=lambda _message: None)
                saved = llm_review._load_queue_unlocked()

            self.assertEqual(batches, [list(range(1, 101))])
            self.assertIsNone(saved["reviewing"])
            self.assertEqual([item["run"] for item in saved["pending"]], list(range(101, 106)))


    def test_prework_stall_falls_through_but_postwork_stall_stays_sticky(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-stall-kind-") as root:
            repo = Path(root) / "repo"
            prompt = repo / "sts2-ascend" / "knowledge" / "review_prompt_latest.md"
            prompt.parent.mkdir(parents=True)
            know = SimpleNamespace(
                stats={"global": {"runs": 8}}, progression={}, save=mock.Mock())
            cfg = {
                "enabled": True, "runner": "opencode", "opencode_bin": "opencode",
                "model": "fallback", "preferred_timeout_min": 480,
                "stall_warn_min": 15, "stall_timeout_min": 30,
                "pre_work_timeout_min": 2.5,
            }

            def execute(model_work_started: bool) -> tuple[dict, int]:
                status: dict = {}
                sandbox = llm_review.SandboxReviewResult(
                    rc=1, stalled=True, error="stalled",
                    provider_work_started=model_work_started,
                    review_attempt_id="receipt-8",
                    review_sandbox_name="sts2-review-sandbox-receipt8",
                    review_attempt_receipt_schema=1)
                with (mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
                      mock.patch.object(llm_review.shutil, "which", return_value="opencode"),
                      mock.patch.object(llm_review, "REPO_DIR", repo),
                      mock.patch.object(llm_review, "PROMPT_FILE", prompt),
                      mock.patch.object(llm_review, "build_prompt", return_value="prompt"),
                      mock.patch.object(llm_review, "_run_review_sandbox",
                                        return_value=sandbox) as run_sandbox,
                      mock.patch.object(llm_review, "_save_review_salvage",
                                        return_value=Path(root) / "pkg") as save_salvage,
                      mock.patch.object(llm_review, "_review_stop_requested",
                                        return_value=False),
                      mock.patch.object(llm_review, "_stream_begin"),
                      mock.patch.object(llm_review, "_stream_end"),
                      mock.patch.object(llm_review, "_launch_viewer"),
                      mock.patch.object(llm_review, "_launch_speaker"),
                      mock.patch.object(llm_review, "_mark_preferred_failure") as mark,
                      mock.patch.object(autogit, "commit_progress_result"),
                      mock.patch.object(autogit, "head", return_value="a" * 40),
                      mock.patch.object(autogit, "set_review_active"),
                      mock.patch.object(autogit, "push_pending", return_value=True)):
                    changed = llm_review.run_review(
                        know, log=lambda _message: None,
                        model="glm", every=1, source="preferred",
                        batch_runs=[8], async_mode=True, _status=status)
                self.assertFalse(changed)
                self.assertEqual(
                    run_sandbox.call_args.kwargs["pre_work_timeout_seconds"], 150)
                self.assertEqual(
                    save_salvage.call_args.kwargs["review_attempt_id"], "receipt-8")
                self.assertEqual(
                    save_salvage.call_args.kwargs["review_sandbox_name"],
                    "sts2-review-sandbox-receipt8")
                self.assertEqual(
                    save_salvage.call_args.kwargs["review_attempt_receipt_schema"], 1)
                return status, mark.call_count

            prework, prework_cooldowns = execute(False)
            postwork, postwork_cooldowns = execute(True)

        self.assertTrue(prework["startup_unavailable"])
        self.assertEqual(prework_cooldowns, 1)
        self.assertFalse(postwork["startup_unavailable"])
        self.assertEqual(postwork_cooldowns, 0)


if __name__ == "__main__":
    unittest.main()
