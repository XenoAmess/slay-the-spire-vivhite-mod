"""Regressions for long reviews, 100-run batches, and failed-review salvage."""
from __future__ import annotations

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
        self.assertEqual(cfg["preferred_models"], ["opencode-go/glm-5.3-flash@max"])
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

    def test_stream_clean_eof_wins_over_stall_after_slow_final_translation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-stream-eof-") as root:
            stream = Path(root) / "review.stream"
            command = [sys.executable, "-c", "print('done', flush=True)"]

            def slow_translate(raw: str) -> list[str]:
                import time
                time.sleep(0.3)
                return [raw]

            with (mock.patch.object(llm_review, "LIVE_STREAM", stream),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                rc, tail, timed_out, stopped, stalled = llm_review._stream_run(
                    command, 5, translate=slow_translate,
                    stall_warn_sec=0.05, stall_timeout_sec=0.1)
        self.assertEqual(rc, 0)
        self.assertFalse(timed_out)
        self.assertFalse(stopped)
        self.assertFalse(stalled)
        self.assertIn("done", tail)

    def test_stream_backlog_is_not_misclassified_as_raw_output_stall(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-stream-backlog-") as root:
            stream = Path(root) / "review.stream"
            command = [
                sys.executable, "-c",
                "import sys,time\n"
                "for value in ('first','two','three','four','five','done'):\n"
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
                    time.sleep(0.15)
                return [raw]

            with (mock.patch.object(llm_review.queue, "Queue", ObservedQueue),
                  mock.patch.object(llm_review, "LIVE_STREAM", stream),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                rc, _tail, timed_out, stopped, stalled = llm_review._stream_run(
                    command, 5, translate=slow_first_translation,
                    stall_warn_sec=0.05, stall_timeout_sec=0.1)
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
                "model": "opencode-go/glm-5.3-flash@max", "stopped": False,
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

    def test_stopped_review_publishes_partial_salvage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-salvage-stop-") as root:
            salvage_root = Path(root) / "salvage"
            result = llm_review.SandboxReviewResult(
                stopped=True, wip_patch=b"partial patch",
                wip_paths=("sts2-ascend/brain/policy.py",),
                allowed_paths=("sts2-ascend/brain/policy.py",))
            with mock.patch.object(llm_review, "SALVAGE_ROOT", salvage_root):
                saved = llm_review._save_review_salvage(
                    "a" * 40, "整套停止", result, log=lambda _msg: None)
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual((saved / "wip.patch").read_bytes(), b"partial patch")
            manifest = json.loads((saved / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["stopped"])
            self.assertEqual(manifest["failure_kind"], "lifecycle_stop")
            self.assertEqual(manifest["reason"], "统一停机中断并全量保全")
            self.assertFalse(manifest["auto_apply"])

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


if __name__ == "__main__":
    unittest.main()
