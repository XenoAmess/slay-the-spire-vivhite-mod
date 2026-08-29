"""Windows review-sandbox ACL bootstrap regressions."""
from __future__ import annotations

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
