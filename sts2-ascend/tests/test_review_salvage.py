"""Regressions for long reviews, 100-run batches, and failed-review salvage."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402


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

    def test_translator_part_memory_is_bounded(self) -> None:
        translator = llm_review.OpencodeJsonTranslator()
        for index in range(5000):
            translator.feed(json.dumps({
                "part": {"id": f"part-{index}-" + ("x" * 2000),
                         "type": "text", "text": "ok"},
            }))
        self.assertLessEqual(len(translator._seen), 4096)
        self.assertTrue(all(len(key) == 32 for key in translator._seen))


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
            self.assertFalse(manifest["auto_apply"])

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
                  mock.patch.object(llm_review, "load_llm_config", return_value={}),
                  mock.patch.object(llm_review, "_run_batch_review", side_effect=complete)):
                llm_review._worker_loop(agent, log=lambda _message: None)
                saved = llm_review._load_queue_unlocked()

            self.assertEqual(batches, [list(range(1, 101))])
            self.assertIsNone(saved["reviewing"])
            self.assertEqual([item["run"] for item in saved["pending"]], list(range(101, 106)))


if __name__ == "__main__":
    unittest.main()
