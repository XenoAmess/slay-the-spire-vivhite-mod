from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))
import llm_review  # noqa: E402


class ReviewPrivateIndexSeedTests(unittest.TestCase):
    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        self.root = Path(self.resources.enter_context(
            tempfile.TemporaryDirectory(prefix="sts2-private-index-seed-test-")))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.managed = self.root / "managed"
        self.resources.enter_context(mock.patch.object(
            llm_review, "_review_work_root", return_value=self.managed))
        self.resources.enter_context(mock.patch.object(
            llm_review, "_review_stop_requested", return_value=False))
        self.paths = [f"sts2-ascend/brain/{name}.py" for name in ("alpha", "beta", "gamma")]
        for path in self.paths:
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"VALUE = 1\n")
        (self.repo / ".gitignore").write_bytes(b"ignored.py\n")
        self.git("init", "-q")
        self.git("config", "user.name", "Seed Test")
        self.git("config", "user.email", "seed@example.invalid")
        self.git("add", "--all")
        self.git("commit", "-qm", "baseline")
        self.pre_head = self.git("rev-parse", "HEAD").stdout.strip()
        self.source_index = self.repo / ".git" / "index"

    def git(self, *args, env=None, check=True):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], env=env, check=check,
            capture_output=True, text=True, encoding="utf-8", errors="replace")

    def private(self):
        prefix = "sts2-review-capture-index-"
        root, env = llm_review._new_private_sandbox_git(self.repo, prefix)
        self.addCleanup(llm_review._discard_private_sandbox_git, root, prefix, lambda _: None)
        return root, env

    def stage(self, env):
        reset = llm_review._reset_private_sandbox_index(self.repo, self.pre_head, env)
        self.assertEqual(reset.returncode, 0, reset.stderr)
        staged = llm_review._sandbox_git(
            self.repo, ["add", "--all", "--force", "--", "."], env=env)
        self.assertEqual(staged.returncode, 0, staged.stderr)
        return set(self.git("diff", "--cached", "--name-only", self.pre_head, env=env).stdout.splitlines())

    def raw_state(self):
        return {
            "index": self.source_index.read_bytes() if self.source_index.exists() else None,
            "index_mtime": self.source_index.stat().st_mtime_ns if self.source_index.exists() else None,
            "head": self.git("rev-parse", "HEAD").stdout,
            "config": (self.repo / ".git" / "config").read_bytes(),
            "objects": tuple(sorted(str(p.relative_to(self.repo / ".git"))
                                    for p in (self.repo / ".git" / "objects").rglob("*") if p.is_file())),
            "shared_indexes": {p.name: p.read_bytes() for p in (self.repo / ".git").glob("sharedindex.*")},
        }

    def test_seed_copies_index_timestamp_without_hardlinks_or_raw_writes(self):
        before = self.raw_state()
        root, env = self.private()
        copied = root / "index"
        self.assertEqual(copied.read_bytes(), before["index"])
        self.assertEqual(copied.stat().st_mtime_ns, before["index_mtime"])
        self.assertFalse(os.path.samefile(copied, self.source_index))
        self.assertEqual(self.stage(env), set())
        self.assertEqual(self.raw_state(), before)
        self.assertEqual(self.git("remote").stdout, "")

    def test_warm_capture_does_not_reread_unchanged_payloads(self):
        reads = self.root / "filter-reads.log"
        script = self.root / "filter.py"
        script.write_text(
            'import sys\nfrom pathlib import Path\n'
            'data=sys.stdin.buffer.read()\n'
            'with Path(sys.argv[1]).open("ab") as out: out.write(str(len(data)).encode()+b"\\n")\n'
            'sys.stdout.buffer.write(data)\n', encoding="utf-8")
        self.git("config", "filter.counter.clean", f'"{sys.executable}" -B "{script}" "{reads}"')
        (self.repo / ".gitattributes").write_bytes(b"payloads/*.dat filter=counter\n")
        (self.repo / "payloads").mkdir()
        stamp = time.time_ns() - 2_000_000_000
        for index in range(6):
            path = self.repo / "payloads" / f"{index}.dat"
            path.write_bytes(os.urandom(128 * 1024))
            os.utime(path, ns=(stamp, stamp))
        self.git("add", "--all")
        self.git("commit", "-qm", "payload baseline")
        self.pre_head = self.git("rev-parse", "HEAD").stdout.strip()
        before = self.raw_state()
        _, cold_env = self.private()
        Path(cold_env["GIT_INDEX_FILE"]).unlink()
        self.git("read-tree", self.pre_head, env=cold_env)
        reads.write_bytes(b"")
        self.git("add", "--all", "--force", "--", ".", env=cold_env)
        cold_reads = reads.read_text().splitlines()
        cold_tree = self.git("write-tree", env=cold_env).stdout
        _, warm_env = self.private()
        reset = llm_review._reset_private_sandbox_index(self.repo, self.pre_head, warm_env)
        self.assertEqual(reset.returncode, 0, reset.stderr)
        reads.write_bytes(b"")
        self.git("add", "--all", "--force", "--", ".", env=warm_env)
        self.assertEqual(len(cold_reads), 6)
        self.assertEqual(reads.read_bytes(), b"")
        self.assertEqual(self.git("write-tree", env=warm_env).stdout, cold_tree)
        self.assertEqual(self.raw_state(), before)

    def test_assume_skip_and_fsmonitor_flags_cannot_hide_changes(self):
        self.git("update-index", "--assume-unchanged", self.paths[0])
        self.git("update-index", "--skip-worktree", self.paths[1])
        self.git("update-index", "--fsmonitor-valid", self.paths[2])
        self.git("config", "core.ignorestat", "true")
        self.git("config", "core.sparseCheckout", "true")
        for path in self.paths:
            (self.repo / path).write_bytes(b"VALUE = 2\n")
        ignored = "sts2-ascend/brain/ignored.py"
        (self.repo / ignored).write_bytes(b"IGNORED = 3\n")
        before = self.raw_state()
        _, env = self.private()
        self.assertEqual(self.stage(env), {*self.paths, ignored})
        self.assertEqual(self.raw_state(), before)

    def test_model_commits_staging_and_deletions_still_use_frozen_baseline(self):
        (self.repo / self.paths[0]).write_bytes(b"VALUE = 2\n")
        self.git("add", self.paths[0])
        self.git("commit", "-qm", "model local commit")
        self.git("rm", "--", self.paths[1])
        (self.repo / self.paths[2]).write_bytes(b"VALUE = 3\n")
        before = self.raw_state()
        _, env = self.private()
        self.assertEqual(self.stage(env), set(self.paths))
        self.assertEqual(self.raw_state(), before)
        self.assertNotEqual(before["head"].strip(), self.pre_head)

    def test_missing_and_corrupt_seed_fall_back_to_complete_capture(self):
        original_index = self.source_index.read_bytes()
        (self.repo / self.paths[0]).write_bytes(b"VALUE = 2\n")
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                if corrupt:
                    self.source_index.write_bytes(b"invalid model index")
                else:
                    self.source_index.unlink(missing_ok=True)
                before = self.raw_state()
                _, env = self.private()
                self.assertEqual(self.stage(env), {self.paths[0]})
                self.assertEqual(self.raw_state(), before)
        self.source_index.write_bytes(original_index)

    def test_racy_timestamp_and_same_size_change_is_captured(self):
        self.git("config", "core.trustctime", "false")
        target = self.repo / self.paths[0]
        stamp = target.stat().st_mtime_ns
        os.utime(self.source_index, ns=(stamp, stamp))
        target.write_bytes(b"VALUE = 2\n")
        os.utime(target, ns=(stamp, stamp))
        before = self.raw_state()
        _, env = self.private()
        self.assertEqual(self.stage(env), {self.paths[0]})
        self.assertEqual(self.raw_state(), before)

    def test_split_index_is_expanded_only_in_private_copy(self):
        self.git("update-index", "--split-index")
        self.assertTrue(self.git("rev-parse", "--shared-index-path").stdout.strip())
        (self.repo / self.paths[0]).write_bytes(b"VALUE = 2\n")
        before = self.raw_state()
        _, env = self.private()
        self.assertEqual(self.stage(env), {self.paths[0]})
        self.assertEqual(self.git("rev-parse", "--shared-index-path", env=env).stdout.strip(), "")
        self.assertEqual(self.raw_state(), before)

    def test_wip_capture_retains_ignored_and_outside_evidence(self):
        (self.repo / self.paths[0]).write_bytes(b"VALUE = 2\n")
        self.git("update-index", "--assume-unchanged", self.paths[0])
        ignored = "sts2-ascend/brain/ignored.py"
        (self.repo / ignored).write_bytes(b"NEW_STATIC = 3\n")
        (self.repo / "outside.txt").write_bytes(b"OUTSIDE_EVIDENCE\n")
        before = self.raw_state()
        knowledge = self.repo / "sts2-ascend/knowledge"
        paths = llm_review._ReviewProfilePaths(
            profile_id="ironclad", root=knowledge,
            prompt=knowledge / "review_prompt_latest.md",
            runs=knowledge / "runs", lessons=knowledge / "lessons.md",
            policy=knowledge / "policy.json", report=knowledge / "meta_review.md",
            conclusion=knowledge / "review_conclusion.txt",
            queue=knowledge / "review_queue.jsonl")
        result = llm_review.SandboxReviewResult()
        with mock.patch.object(llm_review, "REPO_DIR", self.repo), \
                mock.patch.object(llm_review, "_current_profile_paths", return_value=paths):
            llm_review._capture_sandbox_wip(self.repo, self.pre_head, result, log=lambda _: None)
        self.assertTrue(result.snapshot_complete)
        self.assertEqual(set(result.wip_paths), {self.paths[0], ignored, "outside.txt"})
        self.assertIn(ignored, result.allowed_paths)
        self.assertIn("outside.txt", result.unexpected_paths)
        self.assertIn(b"NEW_STATIC", result.wip_patch)
        self.assertIn(b"OUTSIDE_EVIDENCE", result.wip_patch)
        self.assertEqual(self.raw_state(), before)


if __name__ == "__main__":
    unittest.main()
