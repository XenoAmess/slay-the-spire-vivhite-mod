"""Windows review-sandbox ACL bootstrap regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402
import autogit  # noqa: E402


class _Translator:
    model_work_started = False

    @staticmethod
    def feed(_text):
        return []

    @staticmethod
    def metrics():
        return {}


class ReviewSandboxAclTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-review-acl-test-")
        self.addCleanup(self.temp.cleanup)
        self.host = Path(self.temp.name) / "host"
        self.work = (
            self.host / "sts2-ascend" / "knowledge" / "code_backups"
            / "review_work"
        )
        self.work.mkdir(parents=True)

    def test_windows_normalization_resets_only_exact_root_to_parent_inheritance(self) -> None:
        sandbox = self.work / "sts2-review-sandbox-unit"
        sandbox.mkdir()
        completed = [
            subprocess.CompletedProcess([], 0, "reset ok", ""),
            subprocess.CompletedProcess(
                [], 0, f"{sandbox} TEST-SID:(I)(OI)(CI)(M)\n", ""),
        ]
        with (
            mock.patch.object(llm_review, "REPO_DIR", self.host),
            mock.patch.object(llm_review, "_WINDOWS_REVIEW_ACL_REQUIRED", True),
            mock.patch.object(
                llm_review, "_run_captured_stop_aware", side_effect=completed,
            ) as run,
        ):
            llm_review._normalize_windows_review_sandbox_acl(sandbox)

        target = str(sandbox.resolve())
        self.assertEqual(
            run.call_args_list,
            [
                mock.call(["icacls.exe", target, "/reset"], timeout=30),
                mock.call(["icacls.exe", target], timeout=30),
            ],
        )
        flattened = " ".join(
            str(part)
            for call in run.call_args_list
            for part in call.args[0]
        ).lower()
        self.assertNotIn("/t", flattened)
        self.assertNotIn("/grant", flattened)
        self.assertNotIn("everyone", flattened)

    def test_non_windows_normalization_is_noop(self) -> None:
        with (
            mock.patch.object(llm_review, "_WINDOWS_REVIEW_ACL_REQUIRED", False),
            mock.patch.object(llm_review, "_run_captured_stop_aware") as run,
        ):
            llm_review._normalize_windows_review_sandbox_acl(
                Path("not-created-on-unix"))
        run.assert_not_called()

    def _new_fake_repo(self, name: str) -> Path:
        repo = Path(self.temp.name) / name
        (repo / "sts2-ascend" / "brain").mkdir(parents=True)
        return repo

    def _prepare_selfcheck_runtime(
        self, repo: Path,
    ) -> llm_review._CodexWindowsSelfcheckRuntime:
        with mock.patch.object(
            llm_review, "_WINDOWS_REVIEW_ACL_REQUIRED", True,
        ):
            runtime = llm_review._prepare_codex_windows_selfcheck_runtime(
                repo, "codex")
        self.assertIsNotNone(runtime)
        return runtime

    @staticmethod
    def _selfcheck_env(
        runtime: llm_review._CodexWindowsSelfcheckRuntime,
    ) -> dict[str, str]:
        env = dict(os.environ)
        pool = str(runtime.pool_dir)
        env.update({
            "TEMP": pool,
            "TMP": pool,
            "TMPDIR": pool,
            llm_review._CODEX_SELFCHECK_POOL_ENV: pool,
            "PYTHONPATH": str(runtime.startup_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        return env

    def _run_fake_selfcheck(
        self, repo: Path, runtime: llm_review._CodexWindowsSelfcheckRuntime,
        source: str, *, absolute: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        script = repo / "sts2-ascend" / "brain" / "selfcheck.py"
        script.write_text(source, encoding="utf-8")
        target = str(script if absolute else Path("sts2-ascend/brain/selfcheck.py"))
        return subprocess.run(
            [sys.executable, "-B", target], cwd=repo,
            env=self._selfcheck_env(runtime), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )

    def test_codex_selfcheck_runtime_is_windows_codex_only(self) -> None:
        repo = self._new_fake_repo("runtime-guards")
        with mock.patch.object(
            llm_review, "_WINDOWS_REVIEW_ACL_REQUIRED", True,
        ):
            self.assertIsNone(
                llm_review._prepare_codex_windows_selfcheck_runtime(
                    repo, "opencode"))
        with mock.patch.object(
            llm_review, "_WINDOWS_REVIEW_ACL_REQUIRED", False,
        ):
            self.assertIsNone(
                llm_review._prepare_codex_windows_selfcheck_runtime(
                    repo, "codex"))
        self.assertFalse((repo / ".review-cache").exists())

    def test_sitecustomize_guard_and_stream_environment_are_narrow(self) -> None:
        repo = self._new_fake_repo("runtime-env")
        runtime = self._prepare_selfcheck_runtime(repo)
        slots = sorted(runtime.pool_dir.glob("slot-*"))
        self.assertEqual(len(slots), 256)

        guarded = self._run_fake_selfcheck(
            repo, runtime,
            "import tempfile\n"
            "print(bool(getattr(tempfile.mkdtemp, "
            "'_sts2_ascend_selfcheck_pool', False)))\n",
            absolute=True,
        )
        self.assertEqual(guarded.returncode, 0, guarded.stderr)
        self.assertEqual(guarded.stdout.strip(), "True")

        other = repo / "other.py"
        other.write_text(
            "import tempfile\n"
            "print(bool(getattr(tempfile.mkdtemp, "
            "'_sts2_ascend_selfcheck_pool', False)))\n",
            encoding="utf-8",
        )
        unguarded = subprocess.run(
            [sys.executable, "-B", str(other)], cwd=repo,
            env=self._selfcheck_env(runtime), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(unguarded.returncode, 0, unguarded.stderr)
        self.assertEqual(unguarded.stdout.strip(), "False")

        live = Path(self.temp.name) / "review-live.stream"
        probe = (
            "import json,os; keys=('TEMP','TMP','TMPDIR','PYTHONPATH','"
            + llm_review._CODEX_SELFCHECK_POOL_ENV
            + "'); print(json.dumps({key: os.environ.get(key) for key in keys}))"
        )
        with (
            mock.patch.object(llm_review, "LIVE_STREAM", live),
            mock.patch.object(
                llm_review, "_review_stop_requested", return_value=False),
        ):
            rc, tail, timed_out, stopped, stalled = llm_review._stream_run(
                [sys.executable, "-B", "-c", probe], 15, cwd=repo,
                codex_windows_selfcheck_runtime=runtime,
            )
        self.assertEqual((rc, timed_out, stopped, stalled), (0, False, False, False))
        values = json.loads(tail.strip().splitlines()[-1])
        pool = str(runtime.pool_dir)
        self.assertEqual(values["TEMP"], pool)
        self.assertEqual(values["TMP"], pool)
        self.assertEqual(values["TMPDIR"], pool)
        self.assertEqual(values[llm_review._CODEX_SELFCHECK_POOL_ENV], pool)
        self.assertEqual(values["PYTHONPATH"].split(os.pathsep)[0], str(runtime.startup_dir))

    def test_managed_temporary_directory_keeps_parent_slot_for_next_process(self) -> None:
        repo = self._new_fake_repo("slot-reuse")
        runtime = self._prepare_selfcheck_runtime(repo)
        source = (
            "import json,tempfile\n"
            "from pathlib import Path\n"
            "with tempfile.TemporaryDirectory(prefix='managed-') as value:\n"
            "    child=Path(value); parent=child.parent\n"
            "    (child/'marker').write_text('x')\n"
            "print(json.dumps({'child':str(child),'parent':str(parent),"
            "'child_exists':child.exists(),'parent_exists':parent.exists()}))\n"
        )
        first = self._run_fake_selfcheck(repo, runtime, source)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_result = json.loads(first.stdout.strip())
        self.assertFalse(first_result["child_exists"])
        self.assertTrue(first_result["parent_exists"])
        self.assertEqual(Path(first_result["parent"]).name, "slot-000")

        second = self._run_fake_selfcheck(repo, runtime, source)
        self.assertEqual(second.returncode, 0, second.stderr)
        second_result = json.loads(second.stdout.strip())
        self.assertEqual(second_result["parent"], first_result["parent"])
        self.assertTrue(second_result["parent_exists"])

    def test_managed_slots_are_unique_and_exhaust_fail_closed(self) -> None:
        repo = self._new_fake_repo("slot-exhaustion")
        runtime = self._prepare_selfcheck_runtime(repo)
        unique = self._run_fake_selfcheck(
            repo, runtime,
            "import json,tempfile\n"
            "from pathlib import Path\n"
            "values=[tempfile.mkdtemp(prefix='managed-') for _ in range(256)]\n"
            "print(json.dumps([Path(value).parent.name for value in values]))\n",
        )
        self.assertEqual(unique.returncode, 0, unique.stderr)
        parents = json.loads(unique.stdout.strip())
        self.assertEqual(len(set(parents)), 256)
        self.assertEqual(parents[0], "slot-000")
        self.assertEqual(parents[-1], "slot-255")

        exhausted = self._run_fake_selfcheck(
            repo, runtime,
            "import tempfile\n"
            "for _ in range(257): tempfile.mkdtemp(prefix='managed-')\n",
        )
        self.assertEqual(exhausted.returncode, 86)
        self.assertIn("REVIEW_SELFCHECK_BOOTSTRAP_FAILED", exhausted.stderr)
        self.assertIn("exhausted after 256 allocations", exhausted.stderr)

    def test_review_cache_pool_is_transient_but_old_root_temp_remains_unsafe(self) -> None:
        self.assertEqual(
            autogit.classify_review_path(
                ".review-cache/selfcheck-pool/slot-000/managed-x"),
            autogit.REVIEW_PATH_CACHE,
        )
        self.assertEqual(
            autogit.classify_review_path(".selfcheck-tmp/managed-x"),
            autogit.REVIEW_PATH_OUTSIDE_UNSAFE,
        )

    def test_missing_inherited_acl_fails_closed(self) -> None:
        sandbox = self.work / "sts2-review-sandbox-no-inherit"
        sandbox.mkdir()
        completed = [
            subprocess.CompletedProcess([], 0, "reset ok", ""),
            subprocess.CompletedProcess([], 0, "OWNER RIGHTS:(OI)(CI)(F)\n", ""),
        ]
        with (
            mock.patch.object(llm_review, "REPO_DIR", self.host),
            mock.patch.object(llm_review, "_WINDOWS_REVIEW_ACL_REQUIRED", True),
            mock.patch.object(
                llm_review, "_run_captured_stop_aware", side_effect=completed,
            ),
            self.assertRaisesRegex(
                llm_review._ReviewSandboxAclError, "did not inherit",
            ),
        ):
            llm_review._normalize_windows_review_sandbox_acl(sandbox)

    def test_acl_normalization_precedes_no_hardlink_clone_and_provider(self) -> None:
        events: list[str] = []

        def normalize(_root: Path) -> None:
            events.append("acl")

        def fail_clone(args: list[str], **_kwargs):
            events.append("clone")
            self.assertEqual(args[:4], [
                "git", "clone", "--quiet", "--no-hardlinks",
            ])
            return subprocess.CompletedProcess(args, 1, "", "clone stopped")

        with (
            mock.patch.object(llm_review, "REPO_DIR", self.host),
            mock.patch.object(
                llm_review, "_review_stop_requested", return_value=False,
            ),
            mock.patch.object(
                llm_review, "_normalize_windows_review_sandbox_acl",
                side_effect=normalize,
            ),
            mock.patch.object(
                llm_review, "_codex_windows_filesystem_preflight",
                return_value="",
            ),
            mock.patch.object(
                llm_review, "_run_captured_stop_aware", side_effect=fail_clone,
            ),
            mock.patch.object(llm_review, "_stream_run") as provider,
        ):
            result = llm_review._run_review_sandbox(
                ["provider"], "prompt", "a" * 40, 30, _Translator(),
                runner="codex", log=lambda _message: None,
            )

        self.assertEqual(events, ["acl", "clone"])
        provider.assert_not_called()
        self.assertIn("创建隔离 clone 失败", result.error)
        self.assertTrue(Path(result.retained_sandbox_dir).is_dir())

    def test_acl_failure_never_clones_or_starts_provider_and_retains_root(self) -> None:
        with (
            mock.patch.object(llm_review, "REPO_DIR", self.host),
            mock.patch.object(
                llm_review, "_review_stop_requested", return_value=False,
            ),
            mock.patch.object(
                llm_review, "_normalize_windows_review_sandbox_acl",
                side_effect=llm_review._ReviewSandboxAclError("access denied"),
            ),
            mock.patch.object(llm_review, "_run_captured_stop_aware") as spawn,
            mock.patch.object(llm_review, "_stream_run") as provider,
        ):
            result = llm_review._run_review_sandbox(
                ["provider"], "prompt", "a" * 40, 30, _Translator(),
                runner="codex", log=lambda _message: None,
            )

        spawn.assert_not_called()
        provider.assert_not_called()
        self.assertEqual(
            result.failure_code, "review_sandbox_acl_preflight")
        self.assertFalse(result.provider_work_started)
        self.assertIn("ACL 预检失败", result.error)
        retained = Path(result.retained_sandbox_dir)
        self.assertEqual(retained.parent, self.work)
        self.assertTrue(retained.is_dir())
        self.assertEqual(
            list(retained.iterdir()), [],
            "preflight root must be preserved before clone/provider writes",
        )

    def test_selfcheck_pool_prepare_failure_is_acl_preflight_before_evidence(self) -> None:
        prompt = self.host / "sts2-ascend" / "knowledge" / "review_prompt_latest.md"

        def fake_clone(args: list[str], **_kwargs):
            clone_repo = Path(args[-1])
            (clone_repo / "sts2-ascend" / "knowledge").mkdir(parents=True)
            (clone_repo / ".review-cache").mkdir()
            return subprocess.CompletedProcess(args, 0, "", "")

        completed = subprocess.CompletedProcess([], 0, "", "")
        with (
            mock.patch.object(llm_review, "REPO_DIR", self.host),
            mock.patch.object(llm_review, "PROMPT_FILE", prompt),
            mock.patch.object(llm_review, "_WINDOWS_REVIEW_ACL_REQUIRED", True),
            mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
            mock.patch.object(llm_review, "_normalize_windows_review_sandbox_acl"),
            mock.patch.object(
                llm_review, "_codex_windows_filesystem_preflight", return_value=""),
            mock.patch.object(
                llm_review, "_run_captured_stop_aware", side_effect=fake_clone),
            mock.patch.object(llm_review, "_sandbox_git", return_value=completed),
            mock.patch.object(llm_review, "_capture_sandbox_wip"),
            mock.patch.object(llm_review, "_mount_failed_review_evidence") as evidence,
            mock.patch.object(llm_review, "_stream_run") as provider,
        ):
            result = llm_review._run_review_sandbox(
                ["codex"], "pool prompt", "a" * 40, 30, _Translator(),
                runner="codex", replay_packages=["pending-lineage"],
                log=lambda _message: None,
            )

        evidence.assert_not_called()
        provider.assert_not_called()
        self.assertEqual(result.failure_code, "review_sandbox_acl_preflight")
        self.assertFalse(result.provider_work_started)
        retained_repo = Path(result.retained_sandbox_dir) / "repo"
        self.assertEqual(
            (retained_repo / prompt.relative_to(self.host)).read_text(encoding="utf-8"),
            "pool prompt",
        )

    def test_acl_preflight_is_deferred_without_model_cooldown(self) -> None:
        prompt = (
            self.host / "sts2-ascend" / "knowledge" / "review_prompt_latest.md"
        )
        prompt.parent.mkdir(parents=True, exist_ok=True)
        sandbox = llm_review.SandboxReviewResult(
            error="隔离复盘 Windows ACL 预检失败：access denied",
            failure_code="review_sandbox_acl_preflight",
            provider_work_started=False,
            snapshot_complete=True,
            review_sandbox_name="sts2-review-sandbox-acl-failed",
            replay_evidence_requested=True,
            replay_evidence_complete=False,
            replay_evidence_error="evidence was not mounted",
            replay_evidence_model_started=False,
        )
        cfg = {
            "enabled": True,
            "model": "gpt-5.6-luna",
            "preferred_timeout_min": 480,
            "stall_warn_min": 15,
            "stall_timeout_min": 30,
            "pre_work_timeout_min": 5,
        }
        know = SimpleNamespace(
            stats={"global": {"runs": 12}},
            progression={"review_report_only_streak": 0},
        )
        closure = {
            "action_required": False,
            "consecutive_report_only": 0,
            "report_only_limit": 2,
            "state_source": "test",
        }
        status: dict = {}
        saved = self.host / "saved-acl-failure"
        with (
            mock.patch.object(llm_review, "REPO_DIR", self.host),
            mock.patch.object(llm_review, "PROMPT_FILE", prompt),
            mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
            mock.patch.object(llm_review, "runner_binary", return_value="codex.CMD"),
            mock.patch.object(llm_review, "build_prompt", return_value="prompt"),
            mock.patch.object(
                llm_review, "_review_closure_state", return_value=closure,
            ),
            mock.patch.object(
                llm_review, "build_review_command", return_value=["codex.CMD", "exec"],
            ),
            mock.patch.object(
                llm_review, "_run_review_sandbox", return_value=sandbox,
            ) as run_sandbox,
            mock.patch.object(
                llm_review, "_save_review_salvage", return_value=saved,
            ) as preserve,
            mock.patch.object(
                llm_review, "_review_stop_requested", return_value=False,
            ),
            mock.patch.object(llm_review, "_stream_begin"),
            mock.patch.object(llm_review, "_stream_end") as stream_end,
            mock.patch.object(llm_review, "_launch_viewer"),
            mock.patch.object(llm_review, "_launch_speaker"),
            mock.patch.object(llm_review, "_mark_preferred_failure") as cooldown,
            mock.patch.object(autogit, "commit_progress_result"),
            mock.patch.object(autogit, "head", return_value="a" * 40),
            mock.patch.object(autogit, "set_review_active"),
            mock.patch.object(autogit, "push_pending", return_value=True),
        ):
            changed = llm_review.run_review(
                know, model="gpt-5.6-luna", runner="codex",
                backend_key="luna-max", reasoning_effort="max",
                approve_for_me=True, sandbox_mode="workspace-write",
                source="preferred", batch_runs=[12], async_mode=True,
                _status=status, log=lambda _message: None,
            )

        self.assertFalse(changed)
        run_sandbox.assert_called_once()
        preserve.assert_called_once()
        cooldown.assert_not_called()
        self.assertEqual(status["outcome"], "deferred")
        self.assertEqual(
            status["deferred_kind"], "review_sandbox_acl_preflight")
        self.assertEqual(
            status["failure_code"], "review_sandbox_acl_preflight")
        self.assertFalse(status["startup_unavailable"])
        self.assertFalse(status["provider_launch_attempted"])
        live_end = stream_end.call_args.args[0]
        self.assertEqual(live_end["outcome"], "deferred")
        self.assertEqual(
            live_end["failure_code"], "review_sandbox_acl_preflight")
        self.assertFalse(live_end["provider_work_started"])

    @unittest.skipUnless(os.name == "nt", "Windows ACL integration only")
    def test_real_icacls_reset_produces_inherited_writable_descendants(self) -> None:
        # S-1-5-11 (Authenticated Users) models the non-owner restricted helper
        # identity required by native Apply Patch. Keep this grant inside the
        # disposable test parent; production permissions are never touched.
        grant = subprocess.run(
            [
                "icacls.exe", str(self.work), "/grant:r",
                "*S-1-5-11:(OI)(CI)M",
            ],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
        self.assertEqual(grant.returncode, 0, grant.stderr)
        sandbox = Path(tempfile.mkdtemp(
            prefix="sts2-review-sandbox-integration-", dir=str(self.work)))
        with mock.patch.object(llm_review, "REPO_DIR", self.host):
            llm_review._normalize_windows_review_sandbox_acl(sandbox)

        inspected = subprocess.run(
            ["icacls.exe", str(sandbox)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        inherited = [
            line for line in inspected.stdout.splitlines() if "(I)" in line
        ]
        self.assertTrue(inherited, inspected.stdout)
        self.assertTrue(
            any("(M)" in line or "(F)" in line for line in inherited),
            inspected.stdout,
        )
        restricted_sid = subprocess.run(
            ["icacls.exe", str(sandbox), "/findsid", "*S-1-5-11"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
        self.assertEqual(restricted_sid.returncode, 0, restricted_sid.stderr)
        self.assertIn("SID Found:", restricted_sid.stdout)
        policy = sandbox / "repo" / "sts2-ascend" / "brain" / "policy.py"
        policy.parent.mkdir(parents=True)
        policy.write_text("VALUE = 1\n", encoding="utf-8")
        self.assertEqual(policy.read_text(encoding="utf-8"), "VALUE = 1\n")


if __name__ == "__main__":
    unittest.main()
