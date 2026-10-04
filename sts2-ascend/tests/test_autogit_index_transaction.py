from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

BRAIN_DIR = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN_DIR))
import autogit  # noqa: E402


class AutoGitIndexTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        self.repo = Path(self.resources.enter_context(
            tempfile.TemporaryDirectory(prefix="sts2-autogit-index-test-")))
        self.resources.enter_context(mock.patch.object(autogit, "REPO_DIR", self.repo))
        self.resources.enter_context(mock.patch.object(
            autogit, "BASE_DIR", self.repo / "sts2-ascend"))
        self.path = "sts2-ascend/brain/policy.py"
        self.target = self.repo / self.path
        self.target.parent.mkdir(parents=True)
        self.target.write_text("VALUE = 1\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.name", "Index Transaction Test")
        self.git("config", "user.email", "index@example.invalid")
        self.git("add", "--all")
        self.git("commit", "-qm", "initial")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True,
            capture_output=True, text=True, encoding="utf-8", errors="replace")

    def patch(self, text: str) -> bytes:
        self.target.write_text(text, encoding="utf-8")
        patch = subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--binary", "HEAD", "--", self.path],
            check=True, capture_output=True).stdout
        self.git("restore", "--worktree", "--source=HEAD", "--", self.path)
        return patch

    def pending_commit(self) -> autogit.CommitResult:
        with mock.patch.object(autogit, "_sync_progress_index_unlocked", return_value=False):
            result = autogit.commit_patch_result(
                self.patch("VALUE = 2\n"), "pending review", [self.path],
                push=False, log=lambda _: None)
        self.assertTrue(result.created, result.reason)
        self.assertTrue(autogit._progress_index_pending_path().exists())
        return result

    def assert_verification_failure_preserves_journal(self, command: str, *, timeout=False):
        self.pending_commit()
        journal = autogit._progress_index_pending_path()
        journal_before = journal.read_bytes()
        index_before = (autogit._git_dir() / "index").read_bytes()
        original = autogit._run_git
        failures = []

        def fail_verify(args, **kwargs):
            matches = (args[:2] == ["rev-list", "--parents"] if command == "rev-list"
                       else args[:2] == ["merge-base", "--is-ancestor"]
                       if command == "merge-base" else args[:2] == ["diff", "--quiet"])
            if matches:
                failures.append(args)
                if timeout:
                    raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 10))
                return subprocess.CompletedProcess(args, 128, "", "temporary read failure")
            return original(args, **kwargs)

        messages = []
        with autogit.repository_lock(), mock.patch.object(
                autogit, "_run_git", side_effect=fail_verify):
            autogit._recover_pending_progress_indexes_unlocked(log=messages.append)
        self.assertTrue(failures)
        self.assertEqual(journal.read_bytes(), journal_before)
        self.assertEqual((autogit._git_dir() / "index").read_bytes(), index_before)
        self.assertTrue(any("read failed" in message for message in messages))
        with autogit.repository_lock():
            autogit._recover_pending_progress_indexes_unlocked(log=lambda _: None)
        self.assertFalse(journal.exists())
        self.assertEqual(self.git("show", ":" + self.path).stdout, "VALUE = 2\n")

    def test_rev_list_read_error_preserves_pending_transaction(self):
        self.assert_verification_failure_preserves_journal("rev-list")

    def test_ancestor_read_error_preserves_pending_transaction(self):
        self.assert_verification_failure_preserves_journal("merge-base")

    def test_target_diff_read_error_preserves_pending_transaction(self):
        self.assert_verification_failure_preserves_journal("diff")

    def test_verify_timeout_preserves_pending_transaction(self):
        self.assert_verification_failure_preserves_journal("rev-list", timeout=True)

    def test_proven_unpublished_transaction_is_discarded(self):
        parent = self.git("rev-parse", "HEAD").stdout.strip()
        tree = self.git("rev-parse", "HEAD^{tree}").stdout.strip()
        commit = self.git("commit-tree", tree, "-p", parent, "-m", "unpublished").stdout.strip()
        with autogit.repository_lock():
            autogit._add_progress_index_pending_unlocked(
                parent, commit, [self.path], "unpublished",
                expected_index=autogit._index_entries_unlocked([self.path]))
            autogit._recover_pending_progress_indexes_unlocked(log=lambda _: None)
        self.assertFalse(autogit._progress_index_pending_path().exists())
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), parent)


    def test_concurrent_git_add_is_blocked_until_index_publish_finishes(self):
        outside = self.repo / "outside.txt"
        outside.write_text("unrelated staging\n", encoding="utf-8")
        self.git("add", "outside.txt")
        outside_entries = autogit._index_entries_unlocked(["outside.txt"])
        original = autogit._run_git
        add_results = []

        def add_during_restore(args, **kwargs):
            if args[:2] == ["restore", "--staged"]:
                self.target.write_text("USER = 99\n", encoding="utf-8")
                add_results.append(subprocess.run(
                    ["git", "-C", str(self.repo), "add", self.path],
                    capture_output=True, text=True, encoding="utf-8"))
            return original(args, **kwargs)

        with mock.patch.object(autogit, "_run_git", side_effect=add_during_restore):
            result = autogit.commit_patch_result(
                self.patch("VALUE = 2\n"), "concurrent staging", [self.path],
                push=False, log=lambda _: None)
        self.assertTrue(result.created, result.reason)
        self.assertEqual(len(add_results), 1)
        self.assertNotEqual(add_results[0].returncode, 0)
        self.assertIn("index.lock", add_results[0].stderr)
        self.assertEqual(autogit._index_entries_unlocked(["outside.txt"]), outside_entries)
        self.assertEqual(self.git("show", ":" + self.path).stdout, "VALUE = 2\n")
        self.git("add", self.path)
        self.assertEqual(self.git("show", ":" + self.path).stdout, "USER = 99\n")
        self.assertFalse((autogit._git_dir() / "index.lock").exists())

    def test_staging_just_before_native_lock_is_preserved(self):
        original = autogit._index_path_unlocked
        staged = []

        def stage_before_lock(*args, **kwargs):
            self.target.write_text("USER = 99\n", encoding="utf-8")
            self.git("add", self.path)
            staged.append(True)
            return original(*args, **kwargs)

        with mock.patch.object(autogit, "_index_path_unlocked", side_effect=stage_before_lock):
            result = autogit.commit_patch_result(
                self.patch("VALUE = 2\n"), "stage before lock", [self.path],
                push=False, log=lambda _: None)
        self.assertTrue(result.created, result.reason)
        self.assertEqual(len(staged), 1)
        self.assertEqual(self.git("show", ":" + self.path).stdout, "USER = 99\n")
        self.assertTrue(autogit._progress_index_pending_path().exists())
        self.assertFalse((autogit._git_dir() / "index.lock").exists())

    def test_preexisting_native_index_lock_is_never_removed(self):
        patch = self.patch("VALUE = 2\n")
        lock = autogit._git_dir() / "index.lock"
        lock.write_bytes(b"another Git transaction")
        with mock.patch.object(autogit.time, "sleep"):
            result = autogit.commit_patch_result(
                patch, "existing lock", [self.path],
                push=False, log=lambda _: None)
        self.assertTrue(result.created, result.reason)
        self.assertEqual(lock.read_bytes(), b"another Git transaction")
        self.assertEqual(self.git("show", ":" + self.path).stdout, "VALUE = 1\n")
        self.assertTrue(autogit._progress_index_pending_path().exists())

    def test_publish_failure_keeps_index_and_releases_only_owned_lock(self):
        original = autogit.os.replace

        def fail_index_publish(source, destination):
            if Path(destination) == autogit._git_dir() / "index":
                raise PermissionError("temporary index rename failure")
            return original(source, destination)

        with mock.patch.object(autogit.os, "replace", side_effect=fail_index_publish):
            result = autogit.commit_patch_result(
                self.patch("VALUE = 2\n"), "publish failure", [self.path],
                push=False, log=lambda _: None)
        self.assertTrue(result.created, result.reason)
        self.assertEqual(self.git("show", ":" + self.path).stdout, "VALUE = 1\n")
        self.assertFalse((autogit._git_dir() / "index.lock").exists())
        self.assertFalse(list(autogit._git_dir().glob(".sts2-autogit-index-*")))
        self.assertTrue(autogit._progress_index_pending_path().exists())
        with autogit.repository_lock():
            autogit._recover_pending_progress_indexes_unlocked(log=lambda _: None)
        self.assertEqual(self.git("show", ":" + self.path).stdout, "VALUE = 2\n")

    def test_effective_index_respects_git_index_file(self):
        actual_index = autogit._git_dir() / "index"
        original_bytes = actual_index.read_bytes()
        alternate = self.repo / "alternate-index"
        shutil.copyfile(actual_index, alternate)
        with mock.patch.dict(os.environ, {"GIT_INDEX_FILE": str(alternate)}):
            self.assertEqual(autogit._index_path_unlocked(), alternate)
            result = autogit.commit_patch_result(
                self.patch("VALUE = 2\n"), "alternate index", [self.path],
                push=False, log=lambda _: None)
            self.assertTrue(result.created, result.reason)
            self.assertEqual(self.git("show", ":" + self.path).stdout, "VALUE = 2\n")
        self.assertEqual(actual_index.read_bytes(), original_bytes)
        self.assertFalse(Path(str(alternate) + ".lock").exists())

    def test_linked_worktree_uses_its_own_index(self):
        original_repo = self.repo
        original_index = (original_repo / ".git" / "index").read_bytes()
        linked = original_repo / "linked"
        self.git("worktree", "add", "--detach", "--quiet", str(linked), "HEAD")
        self.repo = linked
        self.target = linked / self.path
        with mock.patch.object(autogit, "REPO_DIR", linked), mock.patch.object(
                autogit, "BASE_DIR", linked / "sts2-ascend"):
            index = autogit._index_path_unlocked()
            self.assertEqual(index, autogit._git_dir() / "index")
            result = autogit.commit_patch_result(
                self.patch("VALUE = 2\n"), "linked index", [self.path],
                push=False, log=lambda _: None)
            self.assertTrue(result.created, result.reason)
            self.assertEqual(self.git("show", ":" + self.path).stdout, "VALUE = 2\n")
            self.assertFalse(index.with_name(index.name + ".lock").exists())
        self.assertEqual((original_repo / ".git" / "index").read_bytes(), original_index)


    def test_prepared_index_repair_blocks_concurrent_git_add(self):
        pending = self.pending_commit()
        original = autogit._run_git
        blocked = []

        def add_during_restore(args, **kwargs):
            if args[:2] == ["restore", "--staged"]:
                self.target.write_text("USER = 99\n", encoding="utf-8")
                blocked.append(subprocess.run(
                    ["git", "-C", str(self.repo), "add", self.path],
                    capture_output=True, text=True, encoding="utf-8"))
            return original(args, **kwargs)

        with mock.patch.object(autogit, "_run_git", side_effect=add_during_restore):
            self.assertTrue(autogit.sync_prepared_index(
                pending.before_head, pending.commit, [self.path], log=lambda _: None))
        self.assertEqual(len(blocked), 1)
        self.assertNotEqual(blocked[0].returncode, 0)
        self.git("add", self.path)
        self.assertEqual(self.git("show", ":" + self.path).stdout, "USER = 99\n")


    def test_patch_recovery_charges_each_read_to_one_deadline(self):
        pending = self.pending_commit()
        next_patch = self.patch("VALUE = 3\n")
        journal = autogit._progress_index_pending_path()
        journal_before = journal.read_bytes()
        index_before = (autogit._git_dir() / "index").read_bytes()
        clock = [100.0]
        calls = []

        def slow_read(args, **kwargs):
            allowed = kwargs["timeout"]
            calls.append((args[0], allowed))
            duration = 0.04
            clock[0] += min(duration, allowed)
            if allowed < duration:
                raise subprocess.TimeoutExpired(args, allowed)
            if args[:2] == ["rev-list", "--parents"]:
                return subprocess.CompletedProcess(
                    args, 0, f"{pending.commit} {pending.before_head}\n", "")
            if args[:2] == ["merge-base", "--is-ancestor"]:
                return subprocess.CompletedProcess(args, 0, "", "")
            self.fail(f"Unexpected read after recovery deadline: {args}")

        with mock.patch.object(autogit.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(autogit, "_run_git", side_effect=slow_read):
            result = autogit.commit_patch_result(
                next_patch, "bounded recovery", [self.path], push=False,
                transaction_timeout=0.06, log=lambda _: None)
        self.assertFalse(result.created)
        self.assertIn("deadline", result.reason)
        self.assertEqual([name for name, _ in calls], ["rev-list", "merge-base"])
        self.assertAlmostEqual(calls[0][1], 0.06)
        self.assertAlmostEqual(calls[1][1], 0.02)
        self.assertEqual(journal.read_bytes(), journal_before)
        self.assertEqual((autogit._git_dir() / "index").read_bytes(), index_before)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "VALUE = 2\n")

    def test_index_lock_retry_sleep_cannot_extend_deadline(self):
        clock = [100.0]
        sleeps = []
        restore_calls = []

        def busy(*args, **kwargs):
            restore_calls.append(kwargs["timeout"])
            clock[0] += 0.04
            return subprocess.CompletedProcess([], 128, "", "Could not lock index")

        def sleep(duration):
            sleeps.append(duration)
            clock[0] += duration

        with mock.patch.object(autogit.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(autogit.time, "sleep", side_effect=sleep), \
                mock.patch.object(autogit, "_validated_progress_pair_unlocked", return_value=True), \
                mock.patch.object(autogit, "_index_entries_unlocked", return_value=b"snapshot"), \
                mock.patch.object(autogit, "_restore_index_snapshot_unlocked", side_effect=busy):
            with self.assertRaises(TimeoutError):
                autogit._sync_progress_index_unlocked(
                    "1" * 40, "2" * 40, [self.path], b"snapshot",
                    deadline=100.06, log=lambda _: None)
        self.assertEqual(len(restore_calls), 1)
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.02)
        self.assertAlmostEqual(clock[0], 100.06)

    def test_deadline_expiring_before_publish_preserves_real_index(self):
        pending = self.pending_commit()
        expected = autogit._index_entries_unlocked([self.path])
        index_path = autogit._git_dir() / "index"
        original_bytes = index_path.read_bytes()
        clock = [100.0]
        original = autogit._index_matches_commit_unlocked

        def expire_after_verify(*args, **kwargs):
            verified = original(*args, **kwargs)
            self.assertTrue(verified)
            clock[0] = 105.0
            return verified

        with mock.patch.object(autogit.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(autogit, "_index_matches_commit_unlocked", side_effect=expire_after_verify):
            with self.assertRaises(TimeoutError):
                autogit._restore_index_snapshot_unlocked(
                    pending.commit, [self.path], expected, deadline=105.0)
        self.assertEqual(index_path.read_bytes(), original_bytes)
        self.assertFalse(index_path.with_name(index_path.name + ".lock").exists())
        self.assertFalse(list(index_path.parent.glob(".sts2-autogit-index-*")))
        self.assertTrue(autogit._progress_index_pending_path().exists())

    def test_rollback_relationship_reads_share_total_deadline(self):
        pending = self.pending_commit()
        clock = [100.0]
        calls = []

        def slow_read(args, **kwargs):
            allowed = kwargs["timeout"]
            calls.append((args[0], allowed))
            clock[0] += min(0.04, allowed)
            if allowed < 0.04:
                raise subprocess.TimeoutExpired(args, allowed)
            self.assertEqual(args[:2], ["rev-list", "--parents"])
            return subprocess.CompletedProcess(
                args, 0, f"{pending.commit} {pending.before_head}\n", "")

        with mock.patch.object(autogit.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(autogit, "_run_git", side_effect=slow_read):
            self.assertFalse(autogit.rollback_review_commit(
                pending.before_head, pending.commit, [self.path],
                transaction_timeout=0.06, log=lambda _: None))
        self.assertEqual([name for name, _ in calls], ["rev-list", "merge-base"])
        self.assertAlmostEqual(calls[0][1], 0.06)
        self.assertAlmostEqual(calls[1][1], 0.02)
        self.assertEqual(self.git("show", ":" + self.path).stdout, "VALUE = 1\n")
        self.assertEqual(self.git("show", "HEAD:" + self.path).stdout, "VALUE = 2\n")


    def test_expired_post_commit_budget_skips_push_and_keeps_success(self):
        clock = [100.0]

        def expire_after_commit(_provisional):
            clock[0] = 105.0

        with mock.patch.object(autogit.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(autogit, "_push_with_retry_unlocked") as push:
            result = autogit.commit_patch_result(
                self.patch("VALUE = 2\n"), "post commit budget", [self.path],
                transaction_timeout=5.0, prepare=lambda _: True,
                finalize_prepare=expire_after_commit, log=lambda _: None)
        self.assertTrue(result.created, result.reason)
        self.assertFalse(result.pushed)
        push.assert_not_called()
        self.assertTrue(autogit._progress_index_pending_path().exists())
        self.assertEqual(self.git("show", "HEAD:" + self.path).stdout, "VALUE = 2\n")


if __name__ == "__main__":
    unittest.main()
