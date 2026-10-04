from __future__ import annotations

import json
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


if __name__ == "__main__":
    unittest.main()
