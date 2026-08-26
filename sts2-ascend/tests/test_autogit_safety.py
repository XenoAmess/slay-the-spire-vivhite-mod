from __future__ import annotations

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
        autogit.REPO_DIR = self.repo
        autogit.BASE_DIR = self.repo / "sts2-ascend"
        autogit.REVIEW_ACTIVE_FILE = autogit.BASE_DIR / "knowledge" / "review_active.flag"

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

    def test_runner_counts_slow_post_review_crashes(self) -> None:
        old_marker = runner.MARKER
        marker = self.repo / "sts2-ascend" / "knowledge" / "pending_restart.json"
        marker.write_text("{}", encoding="utf-8")
        runner.MARKER = marker
        crashes = [(1, runner.FAST_CRASH_SECONDS + 1)] * runner.MAX_FAST_CRASHES + [(0, 1)]
        try:
            with (mock.patch.object(runner, "_run_brain", side_effect=crashes),
                  mock.patch.object(runner, "stop_requested", return_value=False),
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
                  mock.patch.object(runner, "wait_for_stop", return_value=False),
                  mock.patch.object(runner, "rollback_from_marker", return_value=False) as rollback,
                  mock.patch.object(runner, "log")):
                self.assertEqual(runner.main(), 1)
                rollback.assert_called_once_with()
            self.assertTrue(marker.exists(), "失败回滚必须保留 marker 供人工诊断")
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

    def test_restart_marker_is_atomic_and_keeps_old_marker_on_replace_failure(self) -> None:
        old_knowledge = llm_review.KNOWLEDGE_DIR
        old_marker = llm_review.MARKER_FILE
        knowledge = self.repo / "sts2-ascend" / "knowledge"
        marker = knowledge / "pending_restart.json"
        marker.write_text('{"old": true}\n', encoding="utf-8")
        llm_review.KNOWLEDGE_DIR = knowledge
        llm_review.MARKER_FILE = marker
        try:
            # 已有待健康验证的 A marker 时，B 不得覆盖它。
            self.assertFalse(llm_review._write_restart_marker({"new": True}))
            self.assertEqual(marker.read_text(encoding="utf-8"), '{"old": true}\n')
            marker.unlink()
            with mock.patch.object(llm_review.os, "link", side_effect=OSError("fault injected")):
                self.assertFalse(llm_review._write_restart_marker({"new": True}))
            self.assertFalse(marker.exists())
            self.assertFalse(list((knowledge / "code_backups").glob(".pending_restart.*.tmp")))
            self.assertTrue(llm_review._write_restart_marker({"new": True}))
            self.assertIn('"new": true', marker.read_text(encoding="utf-8"))
        finally:
            llm_review.KNOWLEDGE_DIR = old_knowledge
            llm_review.MARKER_FILE = old_marker


if __name__ == "__main__":
    unittest.main()
