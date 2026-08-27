from __future__ import annotations

import json
from contextlib import contextmanager
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BRAIN_DIR = ROOT / "sts2-ascend" / "brain"
sys.path.insert(0, str(BRAIN_DIR))

import autogit  # noqa: E402
import llm_review  # noqa: E402
import runner  # noqa: E402


class AutoGitSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self._old_repo = autogit.REPO_DIR
        self._old_base = autogit.BASE_DIR
        self._old_flag = autogit.REVIEW_ACTIVE_FILE
        self._old_tombstones = runner.ROLLBACK_TOMBSTONES
        autogit.REPO_DIR = self.repo
        autogit.BASE_DIR = self.repo / "sts2-ascend"
        autogit.REVIEW_ACTIVE_FILE = autogit.BASE_DIR / "knowledge" / "review_active.flag"
        runner.ROLLBACK_TOMBSTONES = self.repo / "review_rollback_tombstones.json"
        runner._ROLLED_BACK_COMMITS.clear()

        self._git("init", "-q")
        self._git("config", "user.name", "Safety Test")
        self._git("config", "user.email", "safety@example.invalid")
        self._write("outside.txt", "outside-v1\n")
        self._write("sts2-ascend/knowledge/stats.json", '{"runs": 1}\n')
        self._write("sts2-ascend/knowledge/progression.json", '{"ascension": 0}\n')
        self._write("sts2-ascend/brain/policy.py", "VALUE = 1\n")
        self._write("sts2-ascend/brain/agent.py", "AGENT = 1\n")
        self._git("add", "--all")
        self._git("commit", "-qm", "initial")

    def tearDown(self) -> None:
        autogit.REPO_DIR = self._old_repo
        autogit.BASE_DIR = self._old_base
        autogit.REVIEW_ACTIVE_FILE = self._old_flag
        runner.ROLLBACK_TOMBSTONES = self._old_tombstones
        runner._ROLLED_BACK_COMMITS.clear()
        self.tmp.cleanup()

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], check=check,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

    def _write(self, relative: str, text: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _read(self, relative: str) -> str:
        return (self.repo / relative).read_text(encoding="utf-8")

    def _provisional_commit(self, relative: str, contents: str) -> tuple[str, str]:
        parent = self._git("rev-parse", "HEAD").stdout.strip()
        self._write(relative, contents)
        self._git("add", relative)
        self._git("commit", "-qm", "provisional review")
        commit = self._git("rev-parse", "HEAD").stdout.strip()
        self._git("update-ref", "refs/heads/master", parent, commit)
        self._git("restore", "--staged", f"--source={parent}", "--", relative)
        self._git("restore", f"--source={parent}", "--", relative)
        return parent, commit

    def test_private_index_excludes_and_preserves_pre_staged_user_file(self) -> None:
        self._write("outside.txt", "user-staged\n")
        self._git("add", "outside.txt")
        self._write("sts2-ascend/knowledge/stats.json", '{"runs": 2}\n')

        result = autogit.commit_progress_result(
            "automatic progress", paths=["sts2-ascend/knowledge/stats.json"], push=False)

        self.assertTrue(result.created, result.reason)
        self.assertEqual(
            self._git("show", "HEAD:outside.txt").stdout, "outside-v1\n",
            "调用前 staged 的仓外文件不得进入自动 commit",
        )
        self.assertEqual(
            self._git("show", "HEAD:sts2-ascend/knowledge/stats.json").stdout,
            '{"runs": 2}\n',
        )
        self.assertEqual(self._git("diff", "--cached", "--name-only").stdout.strip(), "outside.txt")
        status = self._git("status", "--porcelain").stdout.splitlines()
        self.assertEqual(status, ["M  outside.txt"])

    def test_staged_target_causes_transaction_refusal_without_mutation(self) -> None:
        before = self._git("rev-parse", "HEAD").stdout.strip()
        self._write("sts2-ascend/knowledge/stats.json", '{"runs": 9}\n')
        self._git("add", "sts2-ascend/knowledge/stats.json")
        cached_before = self._git("diff", "--cached").stdout

        result = autogit.commit_progress_result(
            "must refuse", paths=["sts2-ascend/knowledge/stats.json"], push=False)

        self.assertFalse(result.created)
        self.assertIn("staged", result.reason)
        self.assertEqual(self._git("rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(self._git("diff", "--cached").stdout, cached_before)

    def test_default_progress_scope_does_not_sweep_unrelated_knowledge_files(self) -> None:
        self._write("sts2-ascend/knowledge/stats.json", '{"runs": 2}\n')
        self._write("sts2-ascend/knowledge/manual-export.json", '{"large": true}\n')

        result = autogit.commit_progress_result("runtime only", push=False)

        self.assertTrue(result.created, result.reason)
        names = self._git("show", "--format=", "--name-only", "HEAD").stdout.splitlines()
        self.assertIn("sts2-ascend/knowledge/stats.json", names)
        self.assertNotIn("sts2-ascend/knowledge/manual-export.json", names)
        self.assertTrue((self.repo / "sts2-ascend/knowledge/manual-export.json").exists())

    def test_review_active_checkpoint_uses_default_scope_and_pushes_immediately(self) -> None:
        self._write("sts2-ascend/knowledge/policy.json", '{"weight": 1}\n')
        self._git("add", "sts2-ascend/knowledge/policy.json")
        self._git("commit", "-qm", "add policy")
        self._write("sts2-ascend/knowledge/stats.json", '{"runs": 2}\n')
        self._write("sts2-ascend/knowledge/policy.json", '{"weight": 99}\n')
        autogit.set_review_active(True)
        try:
            with mock.patch.object(
                    autogit, "_push_with_retry_unlocked", return_value=True) as push:
                result = autogit.commit_progress_result("online while review", push=True)
        finally:
            autogit.set_review_active(False)

        self.assertTrue(result.created, result.reason)
        self.assertTrue(result.pushed)
        push.assert_called_once_with(log=print)
        self.assertEqual(
            self._git("show", "HEAD:sts2-ascend/knowledge/policy.json").stdout,
            '{"weight": 99}\n',
        )
        self.assertEqual(
            self._git("show", "HEAD:sts2-ascend/knowledge/stats.json").stdout,
            '{"runs": 2}\n',
        )

    def test_push_pending_runs_during_review_and_only_when_ahead(self) -> None:
        messages: list[str] = []
        def git_result(args, **_kwargs):
            if args[0] == "rev-parse":
                return subprocess.CompletedProcess(args, 0, "origin/master\n", "")
            if args[0] == "rev-list":
                return subprocess.CompletedProcess(args, 0, "2\n", "")
            raise AssertionError(args)

        autogit.set_review_active(True)
        try:
            with (mock.patch.object(autogit, "_run_git", side_effect=git_result),
                  mock.patch.object(autogit, "_push_with_retry_unlocked",
                                    return_value=True) as push):
                self.assertTrue(autogit.push_pending(log=messages.append, attempts=1))
        finally:
            autogit.set_review_active(False)
        push.assert_called_once_with(log=messages.append, attempts=1)
        self.assertTrue(any("已补推" in message for message in messages))

        def no_ahead(args, **_kwargs):
            value = "origin/master\n" if args[0] == "rev-parse" else "0\n"
            return subprocess.CompletedProcess(args, 0, value, "")

        with (mock.patch.object(autogit, "_run_git", side_effect=no_ahead),
              mock.patch.object(autogit, "_push_with_retry_unlocked") as push):
            self.assertTrue(autogit.push_pending(log=messages.append))
        push.assert_not_called()

    def test_compare_and_swap_failure_never_moves_head_or_real_index(self) -> None:
        before = self._git("rev-parse", "HEAD").stdout.strip()
        self._write("outside.txt", "user-staged\n")
        self._git("add", "outside.txt")
        self._write("sts2-ascend/knowledge/stats.json", '{"runs": 3}\n')
        original_run = autogit._run_git

        def fail_update_ref(args, **kwargs):
            if args and args[0] == "update-ref":
                return subprocess.CompletedProcess(args, 1, "", "fault injected")
            return original_run(args, **kwargs)

        with mock.patch.object(autogit, "_run_git", side_effect=fail_update_ref):
            result = autogit.commit_progress_result(
                "CAS failure", paths=["sts2-ascend/knowledge/stats.json"], push=False)

        self.assertFalse(result.created)
        self.assertEqual(self._git("rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(self._git("diff", "--cached", "--name-only").stdout.strip(), "outside.txt")
        self.assertEqual(self._read("sts2-ascend/knowledge/stats.json"), '{"runs": 3}\n')

    def test_shared_worktree_restore_fails_closed_and_preserves_every_hunk(self) -> None:
        base = self._git("rev-parse", "HEAD").stdout.strip()
        self._write("sts2-ascend/brain/policy.py", "BROKEN = True\n")
        self._write("sts2-ascend/knowledge/stats.json", '{"runs": 2}\n')

        self.assertFalse(autogit.restore_paths(base, ["sts2-ascend/brain/policy.py"]))
        self.assertEqual(self._read("sts2-ascend/brain/policy.py"), "BROKEN = True\n")
        self.assertEqual(self._read("sts2-ascend/knowledge/stats.json"), '{"runs": 2}\n')

    def test_runner_style_reverse_patch_is_forward_history_and_preserves_concurrent_data(self) -> None:
        self._write("sts2-ascend/brain/policy.py", "VALUE = 2\n")
        review = autogit.commit_progress_result(
            "review", paths=["sts2-ascend/brain/policy.py"], push=False)
        self.assertTrue(review.created, review.reason)
        self._write("sts2-ascend/knowledge/stats.json", '{"runs": 88}\n')
        self._write("outside.txt", "concurrent-user-work\n")

        with mock.patch.object(autogit, "_push_with_retry_unlocked", return_value=True):
            ok = autogit.rollback_review_commit(
                review.before_head, review.commit,
                marker_paths=["sts2-ascend/brain/policy.py"],
            )

        self.assertTrue(ok)
        new_head = self._git("rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(new_head, review.before_head)
        self.assertNotEqual(new_head, review.commit)
        self.assertEqual(self._read("sts2-ascend/brain/policy.py"), "VALUE = 1\n")
        self.assertEqual(self._read("sts2-ascend/knowledge/stats.json"), '{"runs": 88}\n')
        self.assertEqual(self._read("outside.txt"), "concurrent-user-work\n")
        self.assertEqual(self._git("merge-base", "--is-ancestor", review.commit, "HEAD").returncode, 0)

    def test_reverse_patch_commit_excludes_disjoint_user_hunk_in_same_file(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        self._write(path, "REVIEW = 1\nUSER = 1\n")
        self._git("add", path)
        self._git("commit", "-qm", "two-line baseline")
        self._write(path, "REVIEW = 2\nUSER = 1\n")
        review = autogit.commit_progress_result("review line", paths=[path], push=False)
        self.assertTrue(review.created, review.reason)
        self._write(path, "REVIEW = 2\nUSER = 9\n")

        with mock.patch.object(autogit, "_push_with_retry_unlocked", return_value=True):
            self.assertTrue(autogit.rollback_review_commit(
                review.before_head, review.commit, marker_paths=[path]))

        # 回滚 commit 的树只含精确反向 patch，不得夹带 USER=9。
        self.assertEqual(self._git("show", f"HEAD:{path}").stdout, "REVIEW = 1\nUSER = 1\n")
        # 用户 hunk 仍留在工作树，且相对新 HEAD 是普通 unstaged 修改。
        self.assertEqual(self._read(path), "REVIEW = 1\nUSER = 9\n")
        self.assertEqual(self._git("diff", "--name-only", "--", path).stdout.strip(), path)

    def test_exact_patch_prepares_marker_before_worktree_ref_and_push(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        before = self._git("rev-parse", "HEAD").stdout.strip()
        self._write(path, "VALUE = 7\n")
        patch = subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--binary", "--", path],
            check=True, capture_output=True,
        ).stdout
        self._git("restore", path)
        observed: list[str] = []

        def prepare(provisional: autogit.CommitResult) -> bool:
            observed.append("prepare")
            self.assertEqual(self._git("rev-parse", "HEAD").stdout.strip(), before)
            self.assertEqual(self._read(path), "VALUE = 1\n")
            self.assertTrue(provisional.commit)
            return True

        result = autogit.commit_patch_result(
            patch, "exact review patch", [path], push=False, prepare=prepare)
        self.assertTrue(result.created, result.reason)
        self.assertEqual(observed, ["prepare"])
        self.assertEqual(self._read(path), "VALUE = 7\n")
        self.assertEqual(self._git("show", f"HEAD:{path}").stdout, "VALUE = 7\n")

        # prepare 失败时既不改 HEAD，也不改工作树。
        second_before = self._git("rev-parse", "HEAD").stdout.strip()
        self._write(path, "VALUE = 8\n")
        second_patch = subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--binary", "--", path],
            check=True, capture_output=True,
        ).stdout
        self._git("restore", path)
        rejected = autogit.commit_patch_result(
            second_patch, "must reject", [path], push=False, prepare=lambda _result: False)
        self.assertFalse(rejected.created)
        self.assertEqual(self._git("rev-parse", "HEAD").stdout.strip(), second_before)
        self.assertEqual(self._read(path), "VALUE = 7\n")

    def test_patch_cas_failure_undoes_worktree_and_prepared_marker(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        before = self._git("rev-parse", "HEAD").stdout.strip()
        self._write(path, "VALUE = 7\n")
        patch = subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--binary", "--", path],
            check=True, capture_output=True,
        ).stdout
        self._git("restore", path)
        marker = self.repo / "pending.marker"
        events: list[str] = []
        original_run = autogit._run_git

        def fail_update_ref(args, **kwargs):
            if args and args[0] == "update-ref":
                return subprocess.CompletedProcess(args, 1, "", "fault injected CAS")
            return original_run(args, **kwargs)

        def prepare(provisional: autogit.CommitResult) -> bool:
            events.append("prepare")
            self.assertEqual(self._git("rev-parse", "HEAD").stdout.strip(), before)
            self.assertEqual(self._read(path), "VALUE = 1\n")
            marker.write_text(provisional.commit, encoding="utf-8")
            return True

        def abort(provisional: autogit.CommitResult) -> None:
            events.append("abort")
            self.assertEqual(marker.read_text(encoding="utf-8"), provisional.commit)
            marker.unlink()

        with mock.patch.object(autogit, "_run_git", side_effect=fail_update_ref):
            result = autogit.commit_patch_result(
                patch, "CAS must fail", [path], push=False,
                prepare=prepare, abort_prepare=abort,
            )

        self.assertFalse(result.created)
        self.assertEqual(events, ["prepare", "abort"] * 3)
        self.assertEqual(self._git("rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(self._read(path), "VALUE = 1\n")
        self.assertFalse(marker.exists())

    def test_patch_finalizes_marker_only_after_ref_and_worktree_publish(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        before = self._git("rev-parse", "HEAD").stdout.strip()
        self._write(path, "VALUE = 7\n")
        patch = subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--binary", "--", path],
            check=True, capture_output=True,
        ).stdout
        self._git("restore", path)
        events: list[str] = []

        def prepare(provisional: autogit.CommitResult) -> bool:
            events.append("prepared")
            self.assertEqual(self._git("rev-parse", "HEAD").stdout.strip(), before)
            self.assertEqual(self._read(path), "VALUE = 1\n")
            return True

        def finalize(provisional: autogit.CommitResult) -> None:
            events.append("committed")
            self.assertEqual(
                self._git("rev-parse", "HEAD").stdout.strip(), provisional.commit)
            self.assertEqual(self._read(path), "VALUE = 7\n")

        result = autogit.commit_patch_result(
            patch, "two phase marker", [path], push=False,
            prepare=prepare, finalize_prepare=finalize,
        )

        self.assertTrue(result.created, result.reason)
        self.assertEqual(events, ["prepared", "committed"])

    def test_patch_cas_retries_restore_superseded_review_marker(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        before = self._git("rev-parse", "HEAD").stdout.strip()
        self._write(path, "VALUE = 7\n")
        patch = subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--binary", "--", path],
            check=True, capture_output=True,
        ).stdout
        self._git("restore", path)
        marker = self.repo / "pending_restart.json"
        previous = {
            "review_parent": "1" * 40,
            "review_commit": "2" * 40,
            "healthy_runs": 1,
        }
        marker.write_text(json.dumps(previous), encoding="utf-8")
        old_marker = llm_review.MARKER_FILE
        original_run = autogit._run_git

        def fail_update_ref(args, **kwargs):
            if args and args[0] == "update-ref":
                return subprocess.CompletedProcess(args, 1, "", "fault injected CAS")
            return original_run(args, **kwargs)

        def prepare(provisional: autogit.CommitResult) -> bool:
            return llm_review._write_restart_marker({
                "review_parent": provisional.before_head,
                "review_commit": provisional.commit,
                "paths": [path],
            }, log=lambda _message: None)

        llm_review.MARKER_FILE = marker
        try:
            with mock.patch.object(autogit, "_run_git", side_effect=fail_update_ref):
                result = autogit.commit_patch_result(
                    patch, "CAS must restore A", [path], push=False,
                    prepare=prepare,
                    abort_prepare=lambda provisional: llm_review._remove_restart_marker(
                        provisional.commit, log=lambda _message: None),
                )
        finally:
            llm_review.MARKER_FILE = old_marker

        self.assertFalse(result.created)
        self.assertEqual(self._git("rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(self._read(path), "VALUE = 1\n")
        self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), previous)
        self.assertFalse(list(marker.parent.glob(".pending_restart.*.tmp")))

    def test_patch_refuses_symbolic_head_switch_during_prepare(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        original_ref = self._git("symbolic-ref", "HEAD").stdout.strip()
        before = self._git("rev-parse", "HEAD").stdout.strip()
        self._write(path, "VALUE = 7\n")
        patch = subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--binary", "--", path],
            check=True, capture_output=True,
        ).stdout
        self._git("restore", path)
        aborted: list[str] = []

        def switch_branch(_provisional: autogit.CommitResult) -> bool:
            self._git("switch", "-qc", "concurrent-branch")
            return True

        result = autogit.commit_patch_result(
            patch, "must not follow switched HEAD", [path], push=False,
            prepare=switch_branch,
            abort_prepare=lambda provisional: aborted.append(provisional.commit),
        )

        self.assertFalse(result.created)
        self.assertTrue(aborted)
        self.assertEqual(self._read(path), "VALUE = 1\n")
        self.assertEqual(self._git("rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(self._git("rev-parse", original_ref).stdout.strip(), before)

    def test_push_timeout_keeps_successful_local_commit_result(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        self._write(path, "VALUE = 7\n")
        patch = subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--binary", "--", path],
            check=True, capture_output=True,
        ).stdout
        self._git("restore", path)
        original_run = autogit._run_git

        def timeout_push(args, **kwargs):
            if args and args[0] == "push":
                raise subprocess.TimeoutExpired(cmd="git push", timeout=120)
            return original_run(args, **kwargs)

        with (mock.patch.object(autogit, "_run_git", side_effect=timeout_push),
              mock.patch.object(autogit.time, "sleep")):
            result = autogit.commit_patch_result(patch, "local commit", [path], push=True)

        self.assertTrue(result.created, result.reason)
        self.assertFalse(result.pushed)
        self.assertEqual(self._read(path), "VALUE = 7\n")
        self.assertEqual(self._git("show", f"HEAD:{path}").stdout, "VALUE = 7\n")

        # ref 更新后的任意 push helper 异常也不能把已建立的提交误报为失败。
        self._write(path, "VALUE = 8\n")
        second_patch = subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--binary", "--", path],
            check=True, capture_output=True,
        ).stdout
        self._git("restore", path)
        with mock.patch.object(
                autogit, "_push_with_retry_unlocked", side_effect=OSError("push exploded")):
            second = autogit.commit_patch_result(
                second_patch, "local commit after push error", [path], push=True)
        self.assertTrue(second.created, second.reason)
        self.assertFalse(second.pushed)
        self.assertEqual(self._git("show", f"HEAD:{path}").stdout, "VALUE = 8\n")

    def test_reverse_patch_conflict_and_allowlist_violation_preserve_files(self) -> None:
        self._write("sts2-ascend/brain/policy.py", "VALUE = 2\n")
        review = autogit.commit_progress_result(
            "review", paths=["sts2-ascend/brain/policy.py"], push=False)
        self._write("sts2-ascend/brain/policy.py", "USER = 99\n")
        before = self._git("rev-parse", "HEAD").stdout.strip()
        self.assertFalse(autogit.rollback_review_commit(review.before_head, review.commit))
        self.assertEqual(self._git("rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(self._read("sts2-ascend/brain/policy.py"), "USER = 99\n")

        # 构造一个真实但越界的单父 commit；安全回滚层必须先拒绝路径。
        self._git("restore", "sts2-ascend/brain/policy.py")
        parent = self._git("rev-parse", "HEAD").stdout.strip()
        self._write("sts2-ascend/tts/unsafe.py", "unsafe = True\n")
        self._git("add", "sts2-ascend/tts/unsafe.py")
        self._git("commit", "-qm", "out of allowlist")
        commit = self._git("rev-parse", "HEAD").stdout.strip()
        self.assertFalse(autogit.rollback_review_commit(parent, commit))
        self.assertEqual(self._read("sts2-ascend/tts/unsafe.py"), "unsafe = True\n")

    def test_review_rollback_is_local_and_uses_shared_total_budget(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        parent = "1" * 40
        commit = "2" * 40
        patch_result = autogit.CommitResult(True, commit="3" * 40)
        patch_bytes = subprocess.CompletedProcess(
            ["git", "diff"], 0, b"non-empty-patch", b"")
        with mock.patch.object(
                autogit, "_validated_commit_pair_unlocked", return_value=(path,)), \
                mock.patch.object(autogit, "_run_git_bytes", return_value=patch_bytes), \
                mock.patch.object(
                    autogit, "commit_patch_result", return_value=patch_result) as commit_patch:
            self.assertTrue(autogit.rollback_review_commit(
                parent, commit, marker_paths=[path], lock_timeout=1.0,
                transaction_timeout=4.0, log=lambda _message: None))

        kwargs = commit_patch.call_args.kwargs
        self.assertFalse(kwargs["push"], "恢复 Brain 前禁止同步 push 消耗直播预算")
        self.assertLessEqual(kwargs["transaction_timeout"], 4.0)

    def test_cross_process_lock_blocks_other_process(self) -> None:
        marker = self.repo / "child-locked"
        code = (
            "import sys,time; from pathlib import Path; "
            f"sys.path.insert(0, {str(BRAIN_DIR)!r}); import autogit; "
            "autogit.REPO_DIR=Path(sys.argv[1]); "
            "ctx=autogit.repository_lock(); ctx.__enter__(); "
            "Path(sys.argv[2]).write_text('locked'); time.sleep(0.7); ctx.__exit__(None,None,None)"
        )
        child = subprocess.Popen([sys.executable, "-c", code, str(self.repo), str(marker)])
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists(), "child 未取得文件锁")
            started = time.monotonic()
            with autogit.repository_lock():
                elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 0.45)
        finally:
            child.wait(timeout=5)

    def test_in_process_lock_honors_short_timeout(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def holder() -> None:
            with autogit.repository_lock():
                entered.set()
                release.wait(2.0)

        thread = threading.Thread(target=holder, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(1.0))
        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                with autogit.repository_lock(timeout=0.05):
                    self.fail("busy in-process lock must not be entered")
            self.assertLess(time.monotonic() - started, 0.4)
        finally:
            release.set()
            thread.join(1.0)

    def test_pid_probe_never_terminates_target_process(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        try:
            autogit.REVIEW_ACTIVE_FILE.write_text(str(child.pid), encoding="utf-8")
            self.assertTrue(autogit.is_review_active())
            self.assertIsNone(child.poll(), "探活不得终止目标进程（Windows os.kill(pid, 0) 会杀进程）")
        finally:
            autogit.REVIEW_ACTIVE_FILE.unlink(missing_ok=True)
            child.terminate()
            child.wait(timeout=5)

    def test_repo_wide_scan_observes_changes_outside_sts2_ascend(self) -> None:
        base = self._git("rev-parse", "HEAD").stdout.strip()
        self._write("outside.txt", "changed outside\n")
        self._write("root-new.txt", "new outside\n")
        changed = autogit.repo_changed_paths_since(base)
        self.assertIn("outside.txt", changed)
        self.assertIn("root-new.txt", changed)

    def test_review_sandbox_contains_forbidden_and_ignored_model_writes(self) -> None:
        self._write(".gitignore", ".runtime/\n")
        self._git("add", ".gitignore")
        self._git("commit", "-qm", "ignore runtime")
        pre_head = self._git("rev-parse", "HEAD").stdout.strip()
        old_repo = llm_review.REPO_DIR
        old_knowledge = llm_review.KNOWLEDGE_DIR
        old_prompt = llm_review.PROMPT_FILE
        llm_review.REPO_DIR = self.repo
        llm_review.KNOWLEDGE_DIR = self.repo / "sts2-ascend" / "knowledge"
        llm_review.PROMPT_FILE = llm_review.KNOWLEDGE_DIR / "review_prompt_latest.md"
        sandbox_paths: list[Path] = []
        messages: list[str] = []
        try:
            def write_forbidden(cmd, timeout, translate=None):
                sandbox = Path(cmd[cmd.index("--dir") + 1])
                sandbox_paths.append(sandbox)
                (sandbox / "outside.txt").write_text("model outside\n", encoding="utf-8")
                policy = sandbox / "sts2-ascend" / "brain" / "policy.py"
                policy.write_text("VALUE = 9\n", encoding="utf-8")
                return 0, "done", False, False

            with mock.patch.object(llm_review, "_stream_run", side_effect=write_forbidden):
                denied = llm_review._run_review_sandbox(
                    ["fake", "--dir", str(self.repo)], "prompt", pre_head, 10,
                    mock.Mock(feed=lambda _line: None), log=messages.append)
            self.assertIn("越过 allowlist", denied.error)
            self.assertIn("outside.txt", denied.wip_paths)
            self.assertIn("outside.txt", denied.unexpected_paths)
            self.assertIn(b"model outside", denied.wip_patch)
            self.assertEqual(self._read("outside.txt"), "outside-v1\n")
            self.assertEqual(self._read("sts2-ascend/brain/policy.py"), "VALUE = 1\n")
            self.assertTrue(sandbox_paths[-1].exists(), messages)
            llm_review._discard_sandbox_snapshot(denied, log=lambda _msg: None)
            llm_review._discard_retained_sandbox(denied, log=lambda _msg: None)

            def write_ignored(cmd, timeout, translate=None):
                sandbox = Path(cmd[cmd.index("--dir") + 1])
                sandbox_paths.append(sandbox)
                ignored = sandbox / ".runtime" / "evil.exe"
                ignored.parent.mkdir(parents=True, exist_ok=True)
                ignored.write_bytes(b"contained")
                return 0, "done", False, False

            with mock.patch.object(llm_review, "_stream_run", side_effect=write_ignored):
                ignored = llm_review._run_review_sandbox(
                    ["fake", "--dir", str(self.repo)], "prompt", pre_head, 10,
                    mock.Mock(feed=lambda _line: None), log=messages.append)
            self.assertIn("越过 allowlist", ignored.error)
            self.assertFalse(ignored.paths)
            self.assertIn(".runtime/evil.exe", ignored.wip_paths)
            self.assertIn(b"contained", ignored.wip_patch)
            self.assertFalse((self.repo / ".runtime" / "evil.exe").exists())
            self.assertTrue(sandbox_paths[-1].exists(), messages)
            llm_review._discard_sandbox_snapshot(ignored, log=lambda _msg: None)
            llm_review._discard_retained_sandbox(ignored, log=lambda _msg: None)
        finally:
            llm_review.REPO_DIR = old_repo
            llm_review.KNOWLEDGE_DIR = old_knowledge
            llm_review.PROMPT_FILE = old_prompt

    def test_review_sandbox_captures_pyc_without_rejecting_source_patch(self) -> None:
        self._write(".gitignore", "**/__pycache__/\n*.py[cod]\n")
        self._git("add", ".gitignore")
        self._git("commit", "-qm", "ignore python caches")
        pre_head = self._git("rev-parse", "HEAD").stdout.strip()
        old_repo = llm_review.REPO_DIR
        old_knowledge = llm_review.KNOWLEDGE_DIR
        old_prompt = llm_review.PROMPT_FILE
        llm_review.REPO_DIR = self.repo
        llm_review.KNOWLEDGE_DIR = self.repo / "sts2-ascend" / "knowledge"
        llm_review.PROMPT_FILE = llm_review.KNOWLEDGE_DIR / "review_prompt_latest.md"
        try:
            def write_source_and_cache(cmd, timeout, translate=None):
                sandbox = Path(cmd[cmd.index("--dir") + 1])
                policy = sandbox / "sts2-ascend" / "brain" / "policy.py"
                policy.write_text("VALUE = 2\n", encoding="utf-8")
                cache = policy.parent / "__pycache__" / "policy.cpython-314.pyc"
                cache.parent.mkdir()
                cache.write_bytes(b"REPRODUCIBLE_BYTECODE")
                generic_cache = sandbox / "tool-CACHE" / "result.bin"
                generic_cache.parent.mkdir()
                generic_cache.write_bytes(b"GENERIC_CACHE")
                return 0, "done", False, False

            with (mock.patch.object(
                    llm_review, "_stream_run", side_effect=write_source_and_cache),
                  mock.patch.object(llm_review, "_run_selfcheck", return_value=True)):
                result = llm_review._run_review_sandbox(
                    ["fake", "--dir", str(self.repo)], "prompt", pre_head, 10,
                    mock.Mock(feed=lambda _line: None), log=lambda _msg: None)
            self.assertEqual(result.error, "")
            self.assertEqual(result.paths, ("sts2-ascend/brain/policy.py",))
            self.assertIn(b"VALUE = 2", result.patch)
            self.assertNotIn(b"REPRODUCIBLE_BYTECODE", result.patch)
            self.assertNotIn(b"GENERIC_CACHE", result.patch)
            self.assertIn(
                "sts2-ascend/brain/__pycache__/policy.cpython-314.pyc",
                result.wip_paths)
            self.assertIn("tool-CACHE/result.bin", result.wip_paths)
            self.assertEqual(set(result.artifact_paths), {
                "sts2-ascend/brain/__pycache__/policy.cpython-314.pyc",
                "tool-CACHE/result.bin",
            })
            self.assertEqual(result.unexpected_paths, ())
            llm_review._discard_sandbox_snapshot(result, log=lambda _msg: None)
        finally:
            llm_review.REPO_DIR = old_repo
            llm_review.KNOWLEDGE_DIR = old_knowledge
            llm_review.PROMPT_FILE = old_prompt

    def test_runner_counts_slow_post_review_crashes(self) -> None:
        old_marker = runner.MARKER
        marker = self.repo / "sts2-ascend" / "knowledge" / "pending_restart.json"
        marker.write_text("{}", encoding="utf-8")
        runner.MARKER = marker
        crashes = [(1, runner.FAST_CRASH_SECONDS + 1)] * runner.MAX_FAST_CRASHES + [(0, 1)]
        try:
            with (mock.patch.object(runner, "_run_brain", side_effect=crashes),
                  mock.patch.object(runner, "stop_requested", return_value=False),
                  mock.patch.object(runner, "_has_active_review_marker", return_value=True),
                  mock.patch.object(runner, "wait_for_stop", return_value=False),
                  mock.patch.object(runner, "rollback_from_marker", return_value=True) as rollback,
                  mock.patch.object(runner, "log")):
                self.assertEqual(runner.main(), 0)
            rollback.assert_called_once_with()
        finally:
            runner.MARKER = old_marker

    def test_runner_rolls_back_consecutive_review_restart_loop(self) -> None:
        old_marker = runner.MARKER
        marker = self.repo / "pending_restart.json"
        marker.write_text("{}", encoding="utf-8")
        runner.MARKER = marker
        restarts = [(runner.RESTART_CODE, 1)] * runner.MAX_REVIEW_RESTARTS + [(0, 1)]
        try:
            with (mock.patch.object(runner, "_run_brain", side_effect=restarts),
                  mock.patch.object(runner, "stop_requested", return_value=False),
                  mock.patch.object(runner, "_has_active_review_marker", return_value=True),
                  mock.patch.object(runner, "rollback_from_marker", return_value=True) as rollback,
                  mock.patch.object(runner, "log")):
                self.assertEqual(runner.main(), 0)
                rollback.assert_called_once_with()
        finally:
            runner.MARKER = old_marker

    def test_runner_stops_when_review_restart_loop_cannot_roll_back(self) -> None:
        old_marker = runner.MARKER
        marker = self.repo / "pending_restart.json"
        marker.write_text("{}", encoding="utf-8")
        runner.MARKER = marker
        try:
            with (mock.patch.object(
                    runner, "_run_brain",
                    side_effect=[(runner.RESTART_CODE, 1)] * runner.MAX_REVIEW_RESTARTS),
                  mock.patch.object(runner, "stop_requested", return_value=False),
                  mock.patch.object(runner, "_has_active_review_marker", return_value=True),
                  mock.patch.object(runner, "rollback_from_marker", return_value=False),
                  mock.patch.object(runner, "log")):
                self.assertEqual(runner.main(), 1)
        finally:
            runner.MARKER = old_marker

    def test_runner_stops_when_post_review_crashes_cannot_roll_back(self) -> None:
        old_marker = runner.MARKER
        marker = self.repo / "pending_restart.json"
        marker.write_text("{}", encoding="utf-8")
        runner.MARKER = marker
        crashes = [(1, runner.FAST_CRASH_SECONDS + 1)] * runner.MAX_FAST_CRASHES
        try:
            with (mock.patch.object(runner, "_run_brain", side_effect=crashes),
                  mock.patch.object(runner, "stop_requested", return_value=False),
                  mock.patch.object(runner, "_has_active_review_marker", return_value=True),
                  mock.patch.object(runner, "wait_for_stop", return_value=False),
                  mock.patch.object(runner, "rollback_from_marker", return_value=False) as rollback,
                  mock.patch.object(runner, "log")):
                self.assertEqual(runner.main(), 1)
                rollback.assert_called_once_with()
            self.assertTrue(marker.exists(), "失败回滚必须保留 marker 供人工诊断")
        finally:
            runner.MARKER = old_marker

    def test_runner_passes_frozen_boot_head_to_brain(self) -> None:
        frozen = "a" * 40
        process = mock.Mock()
        process.wait.return_value = 0
        process.poll.return_value = None
        process.pid = 4242
        loaded_review = "b" * 40
        with mock.patch.object(runner, "read_git_head", return_value=frozen), \
                mock.patch.object(
                    runner, "_active_review_commit", return_value=loaded_review), \
                mock.patch.object(runner, "_reconcile_prepared_marker", return_value=True), \
                mock.patch.object(runner, "_brain_pid_has_stage", return_value=True), \
                mock.patch.object(runner, "_brain_pid_is_ready", return_value=True), \
                mock.patch.object(runner.subprocess, "Popen", return_value=process) as popen:
            result = runner._run_brain()

        self.assertEqual(result[0], 0)
        child_env = popen.call_args.kwargs["env"]
        self.assertEqual(child_env["STS2_ASCEND_BOOT_HEAD"], frozen)
        self.assertEqual(child_env["STS2_ASCEND_BOOT_REVIEW_COMMIT"], loaded_review)

    def test_runner_exposes_only_committed_or_legacy_marker_epochs(self) -> None:
        old_marker = runner.MARKER
        marker = self.repo / "pending_restart.json"
        commit = "e" * 40
        runner.MARKER = marker
        try:
            marker.write_text(json.dumps({
                "review_commit": commit, "state": "prepared"}), encoding="utf-8")
            self.assertEqual(runner._active_review_commit(), "")
            marker.write_text(json.dumps({
                "review_commit": commit, "state": "committed"}), encoding="utf-8")
            self.assertEqual(runner._active_review_commit(), commit)
            marker.write_text(json.dumps({"review_commit": commit}), encoding="utf-8")
            self.assertEqual(runner._active_review_commit(), commit)
            runner._record_rollback_tombstone(commit)
            runner._ROLLED_BACK_COMMITS.clear()  # simulate a fresh runner process
            self.assertEqual(runner._active_review_commit(), "")
        finally:
            runner.MARKER = old_marker

    def test_runner_reconciles_prepared_marker_before_and_after_worktree_apply(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        parent, commit = self._provisional_commit(path, "VALUE = 2\n")
        old_marker = runner.MARKER
        marker = self.repo / "pending_restart.json"
        runner.MARKER = marker
        prepared = {
            "review_parent": parent,
            "review_commit": commit,
            "paths": [path],
            "state": "prepared",
        }
        try:
            # Crash before worktree apply: forward patch is still applicable, so
            # reconciliation only retires the unpublished marker.
            marker.write_text(json.dumps(prepared), encoding="utf-8")
            self.assertTrue(runner._reconcile_prepared_marker())
            self.assertFalse(marker.exists())
            self.assertEqual(self._read(path), "VALUE = 1\n")

            # Crash after atomic worktree apply but before update-ref: reverse the
            # exact provisional patch, then retire/restore the wrapper.
            self._write(path, "VALUE = 2\n")
            marker.write_text(json.dumps(prepared), encoding="utf-8")
            self.assertTrue(runner._reconcile_prepared_marker())
            self.assertFalse(marker.exists())
            self.assertEqual(self._read(path), "VALUE = 1\n")

            # An overlapping external edit is neither proven state; preserve it
            # and refuse to start a mixed Brain.
            self._write(path, "VALUE = 99\n")
            marker.write_text(json.dumps(prepared), encoding="utf-8")
            self.assertFalse(runner._reconcile_prepared_marker())
            self.assertTrue(marker.exists())
            self.assertEqual(self._read(path), "VALUE = 99\n")
        finally:
            runner.MARKER = old_marker

    def test_blocked_prepared_recovery_preserves_all_files_before_known_tree_restore(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        parent, commit = self._provisional_commit(path, "VALUE = 2\n")
        self._write(path, "VALUE = 99\n")
        old_marker = runner.MARKER
        old_knowledge = runner.KNOWLEDGE_DIR
        knowledge = self.repo / "sts2-ascend" / "knowledge"
        marker = knowledge / "pending_restart.json"
        marker.write_text(json.dumps({
            "review_parent": parent,
            "review_commit": commit,
            "paths": [path],
            "state": "prepared",
        }), encoding="utf-8")
        runner.MARKER = marker
        runner.KNOWLEDGE_DIR = knowledge
        try:
            self.assertTrue(runner._recover_blocked_prepared_marker("fault injected"))
            self.assertEqual(self._read(path), "VALUE = 1\n")
            self.assertFalse(marker.exists())
            packages = list((knowledge / "code_backups" / "review_salvage").iterdir())
            self.assertEqual(len(packages), 1)
            package = packages[0]
            self.assertEqual(
                (package / "files" / path).read_text(encoding="utf-8"),
                "VALUE = 99\n")
            self.assertTrue((package / "wip.patch").is_file())
            self.assertTrue((package / "provisional.patch").is_file())
            self.assertEqual(
                json.loads((package / "manifest.json").read_text(encoding="utf-8"))[
                    "failure_kind"],
                "prepared_recovery")
        finally:
            runner.MARKER = old_marker
            runner.KNOWLEDGE_DIR = old_knowledge

    def test_blocked_prepared_recovery_is_never_an_infinite_retry(self) -> None:
        failures = [(runner.RECONCILE_BLOCKED_CODE, 1.0)] * 3
        with mock.patch.object(runner, "_run_brain", side_effect=failures) as launch, \
                mock.patch.object(runner, "stop_requested", return_value=False), \
                mock.patch.object(
                    runner, "_recover_blocked_prepared_marker", return_value=False), \
                mock.patch.object(runner, "wait_for_stop", return_value=False), \
                mock.patch.object(runner, "log"):
            self.assertEqual(runner.main(), 1)
        self.assertEqual(launch.call_count, 3)

    def test_runner_promotes_prepared_marker_when_head_is_commit(self) -> None:
        path = "sts2-ascend/brain/policy.py"
        parent, commit = self._provisional_commit(path, "VALUE = 2\n")
        self._git("update-ref", "refs/heads/master", commit, parent)
        self._git("restore", "--staged", f"--source={commit}", "--", path)
        self._git("restore", f"--source={commit}", "--", path)
        old_marker = runner.MARKER
        marker = self.repo / "pending_restart.json"
        marker.write_text(json.dumps({
            "review_parent": parent,
            "review_commit": commit,
            "paths": [path],
            "state": "prepared",
        }), encoding="utf-8")
        runner.MARKER = marker
        try:
            self.assertTrue(runner._reconcile_prepared_marker())
            promoted = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(promoted["state"], "committed")
            self.assertTrue(promoted["reconciled_at_startup"])
        finally:
            runner.MARKER = old_marker

    def test_brain_ready_handshake_rejects_stale_boot_token(self) -> None:
        record_path = self.repo / "brain.pid"
        record_path.write_text(json.dumps({
            "pid": 42,
            "session_id": runner.SESSION_ID,
            "stage": "ready",
            "boot_id": "fresh",
            "boot_head": "a" * 40,
            "boot_review_commit": "b" * 40,
        }), encoding="utf-8")
        with mock.patch.object(runner, "pid_path", return_value=record_path):
            self.assertFalse(runner._brain_pid_is_ready(
                42, "stale", "a" * 40, "b" * 40))
            self.assertTrue(runner._brain_pid_is_ready(
                42, "fresh", "a" * 40, "b" * 40))

    def test_runner_kills_child_that_never_completes_ready_handshake(self) -> None:
        process = mock.Mock(pid=4242)
        process.poll.return_value = None
        with mock.patch.object(runner, "STARTUP_READY_SECONDS", 0), \
                mock.patch.object(runner, "read_git_head", return_value="a" * 40), \
                mock.patch.object(runner, "_active_review_commit", return_value=""), \
                mock.patch.object(runner, "_reconcile_prepared_marker", return_value=True), \
                mock.patch.object(runner.subprocess, "Popen", return_value=process), \
                mock.patch.object(runner, "_terminate_startup_child") as terminate:
            rc, _alive = runner._run_brain()
        self.assertEqual(rc, runner.STARTUP_TIMEOUT_CODE)
        terminate.assert_called_once_with(process)

    def test_runner_releases_repository_lock_after_imported_before_ready(self) -> None:
        events: list[str] = []

        @contextmanager
        def observed_lock(**_kwargs):
            events.append("lock-enter")
            try:
                yield
            finally:
                events.append("lock-exit")

        process = mock.Mock(pid=4242)
        process.poll.return_value = None
        process.wait.return_value = 0

        def imported(*_args) -> bool:
            self.assertNotIn("lock-exit", events)
            events.append("child-imported")
            return True

        def ready(*_args) -> bool:
            self.assertIn("lock-exit", events)
            events.append("child-ready")
            return True

        with mock.patch.object(autogit, "repository_lock", observed_lock), \
                mock.patch.object(runner, "read_git_head", return_value="a" * 40), \
                mock.patch.object(runner, "_active_review_commit", return_value=""), \
                mock.patch.object(runner, "_reconcile_prepared_marker", return_value=True), \
                mock.patch.object(runner, "_brain_pid_has_stage", side_effect=imported), \
                mock.patch.object(runner, "_brain_pid_is_ready", side_effect=ready), \
                mock.patch.object(runner.subprocess, "Popen", return_value=process):
            rc, _alive = runner._run_brain()

        self.assertEqual(rc, 0)
        self.assertEqual(events[:4], [
            "lock-enter", "child-imported", "lock-exit", "child-ready"])

    def test_review_startup_failures_roll_back_within_short_retry_budget(self) -> None:
        failures = [(runner.STARTUP_TIMEOUT_CODE, 10.0)] \
            * runner.MAX_REVIEW_STARTUP_FAILURES + [(0, 1.0)]
        with mock.patch.object(runner, "_run_brain", side_effect=failures), \
                mock.patch.object(runner, "stop_requested", return_value=False), \
                mock.patch.object(runner, "_has_active_review_marker", return_value=True), \
                mock.patch.object(runner, "wait_for_stop", return_value=False) as wait, \
                mock.patch.object(runner, "rollback_from_marker", return_value=True) as rollback, \
                mock.patch.object(runner, "log"):
            self.assertEqual(runner.main(), 0)
        rollback.assert_called_once_with()
        self.assertEqual(wait.call_count, runner.MAX_REVIEW_STARTUP_FAILURES - 1,
                         "回滚成功后必须立即拉起旧代码，不再额外等待10秒")

    def test_runner_rollback_restores_superseded_marker(self) -> None:
        old_marker = runner.MARKER
        marker = self.repo / "pending_restart.json"
        previous = {
            "review_parent": "1" * 40,
            "review_commit": "2" * 40,
            "healthy_runs": 1,
        }
        current = {
            "review_parent": "3" * 40,
            "review_commit": "4" * 40,
            "paths": ["sts2-ascend/brain/policy.py"],
            "_superseded_marker": previous,
        }
        marker.write_text(json.dumps(current), encoding="utf-8")
        runner.MARKER = marker
        try:
            with mock.patch.object(
                    autogit, "rollback_review_commit", return_value=True) as rollback:
                self.assertTrue(runner.rollback_from_marker())
            rollback.assert_called_once_with(
                current["review_parent"], current["review_commit"],
                marker_paths=current["paths"], log=runner.log,
                lock_timeout=5.0, transaction_timeout=30.0)
            self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), previous)
            tombstones = json.loads(
                runner.ROLLBACK_TOMBSTONES.read_text(encoding="utf-8"))["commits"]
            self.assertIn(current["review_commit"], tombstones)
        finally:
            runner.MARKER = old_marker

    def test_successful_code_rollback_survives_marker_restore_failure(self) -> None:
        old_marker = runner.MARKER
        marker = self.repo / "pending_restart.json"
        current = {
            "review_parent": "6" * 40,
            "review_commit": "7" * 40,
            "paths": ["sts2-ascend/brain/policy.py"],
            "_superseded_marker": {"review_commit": "8" * 40},
        }
        marker.write_text(json.dumps(current), encoding="utf-8")
        runner.MARKER = marker
        try:
            with mock.patch.object(
                    autogit, "rollback_review_commit", return_value=True), \
                    mock.patch.object(
                        runner, "_restore_superseded_marker",
                        side_effect=PermissionError("fault injected")), \
                    mock.patch.object(runner, "log"):
                self.assertTrue(runner.rollback_from_marker())
            self.assertTrue(marker.exists(), "诊断 marker 应保留供后续恢复")
            runner._ROLLED_BACK_COMMITS.clear()  # persisted identity survives restart
            self.assertEqual(runner._active_review_commit(), "8" * 40)
        finally:
            runner.MARKER = old_marker

    def test_llm_allowlist_matches_git_boundary_and_partitions_online_data(self) -> None:
        self.assertEqual(tuple(llm_review.REVIEW_MUTABLE_PATHS), autogit.REVIEW_PATCH_ALLOWLIST)
        review, online, unexpected = llm_review._partition_review_changes([
            "sts2-ascend/brain/policy.py",
            "sts2-ascend/knowledge/stats.json",
            "sts2-ascend/brain/autogit.py",
            "outside.txt",
        ])
        self.assertEqual(review, ["sts2-ascend/brain/policy.py"])
        self.assertEqual(online, ["sts2-ascend/knowledge/stats.json"])
        self.assertEqual(unexpected, ["sts2-ascend/brain/autogit.py", "outside.txt"])
        with self.assertRaises(ValueError):
            autogit.validate_review_paths(["sts2-ascend/brain/autogit.py"])
        self.assertEqual(
            autogit.validate_review_paths(["sts2-ascend/brain/selfcheck.py"]),
            ("sts2-ascend/brain/selfcheck.py",),
        )
        with self.assertRaises(ValueError):
            autogit.validate_review_paths([
                "sts2-ascend/brain/config.json/evil.py"])
        review, concurrent, unexpected = llm_review._partition_review_changes([
            "sts2-ascend/brain/config.json/evil.py",
            "sts2-ascend/knowledge/runs/new.json",
        ])
        self.assertEqual(review, [])
        self.assertEqual(concurrent, ["sts2-ascend/knowledge/runs/new.json"])
        self.assertEqual(unexpected, ["sts2-ascend/brain/config.json/evil.py"])
        with self.assertRaises(ValueError):
            autogit.normalize_paths(["../outside.txt"])
        with self.assertRaises(ValueError):
            autogit.normalize_paths(["sts2-ascend/*"])
        empty = autogit.commit_progress_result("empty must not widen", paths=[], push=False)
        self.assertFalse(empty.created)
        self.assertIn("不能为空", empty.reason)

    def test_safety_modules_contain_no_hard_reset_invocation(self) -> None:
        for name in ("autogit.py", "runner.py", "llm_review.py"):
            source = (BRAIN_DIR / name).read_text(encoding="utf-8")
            self.assertNotIn('"--hard"', source, name)
            self.assertNotIn("'--hard'", source, name)

    def test_restart_marker_supersedes_atomically_and_abort_restores_old_marker(self) -> None:
        old_knowledge = llm_review.KNOWLEDGE_DIR
        old_marker = llm_review.MARKER_FILE
        knowledge = self.repo / "sts2-ascend" / "knowledge"
        marker = knowledge / "pending_restart.json"
        previous = {
            "review_parent": "1" * 40,
            "review_commit": "2" * 40,
            "healthy_runs": 1,
        }
        marker.write_text(json.dumps(previous) + "\n", encoding="utf-8")
        llm_review.KNOWLEDGE_DIR = knowledge
        llm_review.MARKER_FILE = marker
        try:
            next_marker = {
                "review_parent": "3" * 40,
                "review_commit": "4" * 40,
            }
            # Windows 发布故障必须让 A 原样留存，且不能遗留临时文件。
            before = marker.read_text(encoding="utf-8")
            with mock.patch.object(
                    llm_review, "_replace_with_retry",
                    side_effect=PermissionError("fault injected")):
                self.assertFalse(llm_review._write_restart_marker(next_marker))
            self.assertEqual(marker.read_text(encoding="utf-8"), before)
            self.assertFalse(list(knowledge.glob(".pending_restart.*.tmp")))

            # B 接管 A；若 B 的 Git CAS 随后失败，abort 精确恢复 A 的语义和健康数。
            self.assertTrue(llm_review._write_restart_marker(next_marker))
            active = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(active["review_commit"], next_marker["review_commit"])
            self.assertEqual(active["state"], "prepared")
            self.assertEqual(active["_superseded_marker"], previous)
            self.assertTrue(llm_review._commit_restart_marker(
                next_marker["review_commit"]))
            self.assertEqual(
                json.loads(marker.read_text(encoding="utf-8"))["state"],
                "committed")
            llm_review._remove_restart_marker(next_marker["review_commit"])
            self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), previous)

            # 外部 C 已接管时，迟到的 B abort 不得覆盖 C。
            current_c = {"review_commit": "5" * 40}
            marker.write_text(json.dumps(current_c), encoding="utf-8")
            llm_review._remove_restart_marker(next_marker["review_commit"])
            self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), current_c)

            # 无前任时，abort 只删除本次 B。
            marker.unlink()
            self.assertTrue(llm_review._write_restart_marker(next_marker))
            llm_review._remove_restart_marker(next_marker["review_commit"])
            self.assertFalse(marker.exists())
        finally:
            llm_review.KNOWLEDGE_DIR = old_knowledge
            llm_review.MARKER_FILE = old_marker


if __name__ == "__main__":
    unittest.main()
