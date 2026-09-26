"""Keep selfchecked insertions anchored across concurrent source commits."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))
import autogit
import llm_review


class ReviewPatchContextTests(unittest.TestCase):
    path = "sts2-ascend/brain/sample.py"
    baseline = (
        "# shared source\n"
        "\n"
        "def decide(handler):\n"
        "    try:\n"
        "        result = handler()\n"
        "        return result\n"
        "    except Exception as exc:\n"
        "        failures = 1\n"
        "        return type(exc).__name__\n"
    )
    checked = baseline.replace(
        "        failures = 1\n",
        "        observation = type(exc).__name__\n        failures = 1\n",
    ).replace("        return type(exc).__name__\n", "        return observation\n")
    prefix = "# concurrent maintenance one\n# concurrent maintenance two\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sts2-patch-context-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.file = self.repo / self.path
        self.file.parent.mkdir(parents=True)
        for name, value in (
            ("REPO_DIR", self.repo),
            ("BASE_DIR", self.repo / "sts2-ascend"),
            ("REVIEW_ACTIVE_FILE", self.repo / "review-active.flag"),
        ):
            patcher = mock.patch.object(autogit, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.git("init", "-q")
        self.git("config", "user.name", "Context Test")
        self.git("config", "user.email", "context@example.invalid")
        self.file.write_text(self.baseline, encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.base = self.git("rev-parse", "HEAD").stdout.strip().decode()

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            capture_output=True, check=True,
        )

    def export(self, *, legacy=False):
        self.file.write_text(self.checked, encoding="utf-8")
        self.git("add", self.path)
        if legacy:
            patch = self.git("diff", "--cached", "--binary", "--unified=0", self.base).stdout
        else:
            result = llm_review._export_review_patch(
                self.repo, self.base, [self.path], env=dict(os.environ))
            self.assertEqual(result.returncode, 0, result.stderr)
            patch = result.stdout
        self.git("restore", "--staged", "--worktree", f"--source={self.base}", "--", self.path)
        return patch

    def concurrent_commit(self, text):
        self.file.write_text(text, encoding="utf-8")
        self.git("add", self.path)
        self.git("commit", "-qm", "concurrent maintenance")

    @staticmethod
    def exercise(source):
        namespace = {}
        exec(compile(source, "sample.py", "exec"), namespace)

        def broken_handler():
            raise RuntimeError("original failure")

        return namespace["decide"](broken_handler)

    def test_zero_context_reproduces_misplaced_checked_insertion(self):
        self.assertEqual(self.exercise(self.checked), "RuntimeError")
        patch = self.export(legacy=True)
        self.concurrent_commit(self.prefix + self.baseline)
        result = autogit.commit_patch_result(
            patch, "legacy misplaced insertion", [self.path], push=False)
        self.assertTrue(result.created, result.reason)
        with self.assertRaises(UnboundLocalError):
            self.exercise(self.file.read_text(encoding="utf-8"))

    def test_context_relocates_insertion_and_keeps_concurrent_commit(self):
        patch = self.export()
        self.concurrent_commit(self.prefix + self.baseline)
        result = autogit.commit_patch_result(
            patch, "anchored insertion", [self.path], push=False)
        self.assertTrue(result.created, result.reason)
        actual = self.file.read_text(encoding="utf-8")
        self.assertEqual(actual, self.prefix + self.checked)
        self.assertEqual(self.exercise(actual), "RuntimeError")

    def test_conflicting_context_keeps_head_index_and_worktree_unchanged(self):
        patch = self.export()
        conflict = self.baseline.replace("        failures = 1\n", "        failures = 9\n")
        self.concurrent_commit(conflict)
        before = self.git("rev-parse", "HEAD").stdout
        before_index = self.git("ls-files", "--stage").stdout
        result = autogit.commit_patch_result(
            patch, "conflicting insertion", [self.path], push=False)
        self.assertFalse(result.created)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)
        self.assertEqual(self.git("ls-files", "--stage").stdout, before_index)
        self.assertEqual(self.file.read_text(encoding="utf-8"), conflict)


if __name__ == "__main__":
    unittest.main()
