"""Crash recovery regressions for unpointed managed review sandboxes."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True, encoding="utf-8", errors="replace")


class ReviewOrphanRecoveryTests(unittest.TestCase):
    changed_paths = (
        "sts2-ascend/brain/knowledge.py",
        "sts2-ascend/brain/policy.py",
        "sts2-ascend/brain/selfcheck.py",
        "sts2-ascend/knowledge/meta_review.md",
        "sts2-ascend/knowledge/review_conclusion.txt",
    )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-orphan-review-")
        self.addCleanup(self.temp.cleanup)
        self.host = Path(self.temp.name) / "host"
        self.host.mkdir()
        _git(self.host, "init", "--quiet")
        _git(self.host, "config", "user.email", "tests@example.invalid")
        _git(self.host, "config", "user.name", "Review Tests")
        (self.host / ".gitignore").write_text(
            "sts2-ascend/knowledge/code_backups/\n", encoding="utf-8")
        for index, relative in enumerate(self.changed_paths):
            path = self.host / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"baseline-{index}\n", encoding="utf-8")
        _git(self.host, "add", ".")
        _git(self.host, "commit", "--quiet", "-m", "baseline")
        self.head = _git(self.host, "rev-parse", "HEAD").stdout.strip()

        self.knowledge = self.host / "sts2-ascend" / "knowledge"
        self.salvage = self.knowledge / "code_backups" / "review_salvage"
        self.queue = self.knowledge / "review_queue.json"
        self.prompt = self.knowledge / "review_prompt_latest.md"
        self.work = self.knowledge / "code_backups" / "review_work"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(llm_review, "REPO_DIR", self.host))
        self.stack.enter_context(mock.patch.object(llm_review, "SALVAGE_ROOT", self.salvage))
        self.stack.enter_context(mock.patch.object(llm_review, "QUEUE_FILE", self.queue))
        self.stack.enter_context(mock.patch.object(llm_review, "PROMPT_FILE", self.prompt))
        self.stack.enter_context(mock.patch.object(
            llm_review, "_review_stop_requested", return_value=False))
        self.stack.enter_context(mock.patch.object(
            llm_review, "_record_review_rejection", return_value=True))

    @staticmethod
    def plan() -> dict:
        # Deliberately not a configured/known provider. Recovery must be generic.
        return {
            "backend_key": "future-tier-7",
            "priority": 7,
            "runner": "future-runner",
            "model": "vendor/future-model-v9",
            "variant": "deliberate",
            "reasoning_effort": "ultra",
            "approve_for_me": True,
            "sandbox": "workspace-write",
            "every": 26,
            "source": "preferred",
        }

    def items(self) -> list[dict]:
        plan = self.plan()
        return [{
            "run": run,
            "time": "2026-08-29 20:44:42",
            "queue_id": f"old-host-{offset}",
            **plan,
            "retry_same_model": True,
            "salvage_packages": [],
            "salvage_attempts": [],
            "evidence_only": False,
        } for offset, run in enumerate(range(988, 1014))]

    def save_reviewing(self, items: list[dict], started: str = "2026-08-29 20:44:42") -> None:
        self.queue.parent.mkdir(parents=True, exist_ok=True)
        llm_review._save_queue_unlocked({
            "pending": [],
            "reviewing": {
                "runs": [item["run"] for item in items],
                "items": [dict(item) for item in items],
                "retry_group": "",
                "started": started,
            },
        })

    def clone(self, name: str) -> tuple[Path, Path]:
        root = self.work / name
        repo = root / "repo"
        root.mkdir(parents=True)
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout",
             str(self.host), str(repo)], check=True)
        _git(repo, "checkout", "--quiet", "--detach", self.head)
        _git(repo, "remote", "remove", "origin")
        return root, repo

    def modify_candidate(self, repo: Path) -> dict[str, str]:
        expected: dict[str, str] = {}
        for index, relative in enumerate(self.changed_paths):
            payload = f"candidate-{index}-preserve-exactly\n".encode()
            (repo / relative).write_bytes(payload)
            expected[relative] = hashlib.sha256(payload).hexdigest()
        transcript = repo / ".git" / "sts2-review-provider-events.jsonl"
        transcript.write_text('{"type":"tool","work":true}\n', encoding="utf-8")
        return expected

    def write_receipt(
        self, root: Path, items: list[dict], attempt_id: str = "future-attempt-1",
    ) -> dict:
        receipt, _raw = llm_review._publish_review_attempt_receipt(root, {
            "attempt_id": attempt_id,
            "pre_head": self.head,
            "batch_runs": [item["run"] for item in items],
            "queue_items": [dict(item) for item in items],
            "replay_queue_ids": [item["queue_id"] for item in items],
            "replay_target": "",
            "replay_packages": [],
            "replay_attempts": [],
            "plan": self.plan(),
            "provider_launch_affinity_committed": True,
        })
        return receipt

    def packages(self) -> list[Path]:
        if not self.salvage.is_dir():
            return []
        return sorted(
            path for path in self.salvage.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file())

    def test_receipt_exists_before_provider_spawn_boundary(self) -> None:
        items = self.items()
        payload = {
            "attempt_id": "spawn-boundary",
            "pre_head": self.head,
            "batch_runs": [item["run"] for item in items],
            "queue_items": items,
            "replay_queue_ids": [item["queue_id"] for item in items],
            "replay_target": "",
            "replay_packages": [],
            "replay_attempts": [],
            "plan": self.plan(),
            "provider_launch_affinity_committed": True,
        }

        class Translator:
            model_work_started = False

            @staticmethod
            def feed(_text):
                return []

            @staticmethod
            def metrics():
                return {}

        translator = Translator()

        def fail_provider(_cmd, _timeout, **_kwargs):
            roots = list(self.work.glob("sts2-review-sandbox-*"))
            self.assertEqual(len(roots), 1)
            receipt = json.loads((
                roots[0] / llm_review._REVIEW_ATTEMPT_RECEIPT_NAME
            ).read_text(encoding="utf-8"))
            self.assertEqual(receipt["attempt_id"], "spawn-boundary")
            self.assertEqual(receipt["queue_items"], items)
            translator.model_work_started = True
            return 1, "provider failed", False, False, False

        with (mock.patch.object(llm_review, "bind_review_workdir", return_value=["fake"]),
              mock.patch.object(llm_review, "_stream_run", side_effect=fail_provider)):
            result = llm_review._run_review_sandbox(
                ["fake"], "prompt", self.head, 30, translator,
                runner="future-runner", attempt_receipt=payload,
                log=lambda _message: None)
        self.assertTrue(result.provider_work_started)
        self.assertTrue(Path(result.retained_sandbox_dir).is_dir())
        llm_review._discard_sandbox_snapshot(result, log=lambda _message: None)
        llm_review._discard_retained_sandbox(result, log=lambda _message: None)

    def test_receipt_bound_clone_becomes_full_salvage_with_exact_affinity(self) -> None:
        items = self.items()
        self.save_reviewing(items)
        root, repo = self.clone("sts2-review-sandbox-receipt")
        expected = self.modify_candidate(repo)
        receipt = self.write_receipt(root, items)

        recovered = llm_review._recover_unpointed_review_sandboxes(
            log=lambda _message: None)

        self.assertEqual(len(recovered), 1)
        self.assertFalse(root.exists())
        packages = self.packages()
        self.assertEqual(len(packages), 1)
        package = packages[0]
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        plan = self.plan()
        for key in (
            "backend_key", "priority", "runner", "model", "variant",
            "reasoning_effort", "approve_for_me", "sandbox", "every", "source",
        ):
            self.assertEqual(manifest[key], plan[key])
        self.assertTrue(manifest["retry_same_model"])
        self.assertEqual(manifest["batch_runs"], [item["run"] for item in items])
        self.assertEqual(manifest["replay_queue_ids"], [
            item["queue_id"] for item in items])
        self.assertTrue(manifest["startup_orphan_recovery"])
        self.assertEqual(manifest["review_attempt_id"], receipt["attempt_id"])
        self.assertEqual(manifest["review_sandbox_name"], root.name)
        self.assertEqual(manifest["review_attempt_receipt_schema"], 1)
        raw = package / "raw_sandbox"
        self.assertTrue((raw / "repo" / ".git").is_dir())
        self.assertTrue((
            raw / "repo" / ".git" / "sts2-review-provider-events.jsonl").is_file())
        self.assertEqual(json.loads((
            raw / llm_review._REVIEW_ATTEMPT_RECEIPT_NAME
        ).read_text(encoding="utf-8"))["attempt_id"], receipt["attempt_id"])
        for relative, digest in expected.items():
            self.assertEqual(
                hashlib.sha256((raw / "repo" / relative).read_bytes()).hexdigest(),
                digest)
        queue = llm_review._load_queue_unlocked()
        self.assertEqual(
            [item["queue_id"] for item in llm_review._reviewing_items(queue["reviewing"])],
            [item["queue_id"] for item in items])
        llm_review._recover_salvage_replay_queue(log=lambda _message: None)
        queue = llm_review._load_queue_unlocked()
        reviewing = llm_review._reviewing_items(queue["reviewing"])
        self.assertEqual([item["queue_id"] for item in reviewing], [
            item["queue_id"] for item in items])
        for item in reviewing:
            self.assertEqual(item["retry_group"], package.name)
            self.assertEqual(item["replay_target"], package.name)
            self.assertEqual(item["salvage_packages"], [package.name])
            self.assertEqual(item["runner"], plan["runner"])
            self.assertEqual(item["model"], plan["model"])
            self.assertEqual(item["variant"], plan["variant"])
            self.assertEqual(item["reasoning_effort"], plan["reasoning_effort"])
            self.assertEqual(item["sandbox"], plan["sandbox"])
        restored = llm_review._restore_interrupted_reviewing(queue)
        self.assertEqual([item["queue_id"] for item in restored], [
            item["queue_id"] for item in items])
        with mock.patch.object(
                llm_review, "_preferred_cooldown_remaining", return_value=0):
            indexes, wait = llm_review._select_review_batch(
                queue["pending"], 100, time.time())
        self.assertEqual(indexes, list(range(26)))
        self.assertEqual(wait, 0.0)

    def test_legacy_unique_match_recovers_but_older_clone_is_retained(self) -> None:
        items = self.items()
        started_epoch = time.time() - 30
        started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_epoch))
        self.save_reviewing(items, started=started)
        old_root, _old_repo = self.clone("sts2-review-sandbox-old")
        current_root, current_repo = self.clone("sts2-review-sandbox-current")
        self.modify_candidate(current_repo)

        def created(path: Path) -> float:
            return (started_epoch - 3600 if path.name.endswith("-old")
                    else started_epoch + 5)

        with mock.patch.object(
                llm_review, "_sandbox_created_epoch", side_effect=created):
            recovered = llm_review._recover_unpointed_review_sandboxes(
                log=lambda _message: None)

        self.assertEqual(len(recovered), 1)
        self.assertTrue(old_root.is_dir())
        self.assertFalse(current_root.exists())
        manifest = json.loads((
            self.packages()[0] / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["review_attempt_receipt_schema"], 0)
        self.assertEqual(manifest["runner"], self.plan()["runner"])
        self.assertEqual(manifest["model"], self.plan()["model"])

    def test_legacy_ambiguity_and_unmanaged_roots_are_never_consumed(self) -> None:
        items = self.items()
        started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 30))
        self.save_reviewing(items, started=started)
        first, first_repo = self.clone("sts2-review-sandbox-first")
        second, second_repo = self.clone("sts2-review-sandbox-second")
        for repo in (first_repo, second_repo):
            (repo / ".git" / "sts2-review-provider-events.jsonl").write_text(
                "{}\n", encoding="utf-8")
        unmanaged = self.work / "not-a-review-sandbox" / "repo"
        unmanaged.mkdir(parents=True)
        (unmanaged / ".git").mkdir()

        with mock.patch.object(
                llm_review, "_sandbox_created_epoch", return_value=time.time()):
            recovered = llm_review._recover_unpointed_review_sandboxes(
                log=lambda _message: None)

        self.assertEqual(recovered, [])
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())
        self.assertTrue(unmanaged.is_dir())
        self.assertEqual(self.packages(), [])

    def test_overlapping_receipt_queue_claims_retain_every_clone(self) -> None:
        items = self.items()
        self.save_reviewing(items)
        first, first_repo = self.clone("sts2-review-sandbox-overlap-a")
        second, second_repo = self.clone("sts2-review-sandbox-overlap-b")
        self.modify_candidate(first_repo)
        self.modify_candidate(second_repo)
        self.write_receipt(first, items[:2], attempt_id="overlap-a")
        self.write_receipt(second, items[1:3], attempt_id="overlap-b")

        recovered = llm_review._recover_unpointed_review_sandboxes(
            log=lambda _message: None)

        self.assertEqual(recovered, [])
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())
        self.assertEqual(self.packages(), [])

    def test_broken_receipt_link_never_falls_back_to_legacy(self) -> None:
        root = self.work / "sts2-review-sandbox-broken-receipt"
        root.mkdir(parents=True)
        receipt_path = root / llm_review._REVIEW_ATTEMPT_RECEIPT_NAME

        original_is_symlink = Path.is_symlink

        def fake_is_symlink(path: Path) -> bool:
            if path == receipt_path:
                return True
            return original_is_symlink(path)

        with mock.patch.object(Path, "is_symlink", fake_is_symlink):
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                llm_review._read_review_attempt_receipt(root)

    def test_copy_failure_retains_source_and_full_package_is_idempotent(self) -> None:
        items = self.items()
        self.save_reviewing(items)
        root, repo = self.clone("sts2-review-sandbox-copy")
        self.modify_candidate(repo)
        self.write_receipt(root, items, attempt_id="copy-transaction")
        original_copytree = shutil.copytree
        original_replace = llm_review.os.replace

        def force_checked_copy(source, destination, *args, **kwargs):
            if (Path(source) == root
                    and Path(destination).name == "raw_sandbox"):
                raise OSError("simulated cross-volume move")
            return original_replace(source, destination, *args, **kwargs)

        def fail_raw_copy(source, destination, *args, **kwargs):
            if Path(destination).name == "raw_sandbox":
                raise OSError("simulated raw copy failure")
            return original_copytree(source, destination, *args, **kwargs)

        with (mock.patch.object(
                llm_review.os, "replace", side_effect=force_checked_copy),
              mock.patch.object(
                  llm_review.shutil, "copytree", side_effect=fail_raw_copy)):
            recovered = llm_review._recover_unpointed_review_sandboxes(
                log=lambda _message: None)
        self.assertEqual(len(recovered), 1)
        self.assertTrue(root.is_dir())
        self.assertEqual(len(self.packages()), 1)
        package = self.packages()[0]
        self.assertTrue((package / "raw_sandbox_pointer.txt").is_file())

        llm_review._recover_deferred_salvages(log=lambda _message: None)
        self.assertFalse(root.exists())
        self.assertFalse((package / "raw_sandbox_pointer.txt").exists())
        self.assertTrue((package / "raw_sandbox" / "repo" / ".git").is_dir())
        original_copytree(package / "raw_sandbox", root)
        before = [path.name for path in self.packages()]

        recovered_again = llm_review._recover_unpointed_review_sandboxes(
            log=lambda _message: None)
        self.assertEqual(recovered_again, before)
        self.assertFalse(root.exists())
        self.assertEqual([path.name for path in self.packages()], before)


if __name__ == "__main__":
    unittest.main()
