"""Regression tests for mandatory evidence-to-code review closure."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402


REPORT = "sts2-ascend/knowledge/meta_review.md"
CONCLUSION = "sts2-ascend/knowledge/review_conclusion.txt"
SELFCHECK = "sts2-ascend/brain/selfcheck.py"
POLICY = "sts2-ascend/brain/policy.py"
AGENT = "sts2-ascend/brain/agent.py"
AUTOGIT = "sts2-ascend/brain/autogit.py"
CONFIG = "sts2-ascend/brain/config.json"
SCRIPT = "sts2-ascend/scripts/Start-Agent.ps1"
TTS_OWNER = "sts2-ascend/tts/quipper.py"
TTS_GPU = "sts2-ascend/tts/indextts_gpu.py"
TTS_EPOCH = "sts2-ascend/tts/owner_epoch.py"
TEST = "sts2-ascend/tests/test_policy.py"
DOC = "sts2-ascend/docs/review-design.md"
STATIC_KNOWLEDGE = "sts2-ascend/knowledge/game/v0.111.0/mechanics/cards.jsonl"


class ReviewClosureTests(unittest.TestCase):
    def test_retry_receipts_accept_colon_and_two_or_three_column_tables(self) -> None:
        packages = ["pkg-colon", "pkg-two", "pkg-three", "pkg-note", "pkg-inline"]
        report = """
retry_resolution: pkg-colon integrated
| retry_resolution | **pkg-two no_valid_change** |
| retry_resolution | `pkg-three` | `integrated` |
| retry_resolution | **pkg-note integrated** | current HEAD implementation verified |
retry_resolution: pkg-inline integrated（明细见本节）
| retry_resolution | **pkg-inline integrated**（补合即本批闭环实验本体） |
"""
        self.assertEqual(llm_review._parse_retry_resolutions(report, packages), {
            "pkg-colon": "integrated",
            "pkg-two": "no_valid_change",
            "pkg-three": "integrated",
            "pkg-note": "integrated",
            "pkg-inline": "integrated",
        })

    def test_retry_receipts_reject_prose_substrings_and_ambiguous_tables(self) -> None:
        report = """
Prose mentions retry_resolution: pkg-a integrated but is not a receipt.
retry_resolution: pkg-a integrated because it looks correct
retry_resolution_extra: pkg-a integrated
| notes | retry_resolution | pkg-a integrated |
| retry_resolution | pkg-a integrated extra words |
| retry_resolution | pkg-a | integrated | unexpected fourth cell |
| retry_resolution | pkg-a-prefix integrated |
| retry_resolution | package | status |
"""
        self.assertEqual(
            llm_review._parse_retry_resolutions(report, ["pkg-a"]), {})

    def test_committed_retry_receipts_require_added_lines_and_action_for_integrated(
            self) -> None:
        repo = Path("X:/test-repo")
        report_path = "sts2-ascend/knowledge/meta_review.md"
        action_commit = "a" * 40
        report_only_commit = "b" * 40

        def completed(stdout: str = "", returncode: int = 0):
            return SimpleNamespace(stdout=stdout, returncode=returncode)

        def fake_git(args, **_kwargs):
            operation = args[3]
            if operation == "log":
                return completed(f"{report_only_commit}\n{action_commit}\n")
            commit = next((value for value in args if value in {
                action_commit, report_only_commit}), "")
            if operation == "diff-tree":
                if commit == action_commit:
                    return completed(
                        "sts2-ascend/brain/policy.py\n" + report_path + "\n")
                return completed(report_path + "\n")
            if operation == "show" and args[-1] == report_path:
                if commit == report_only_commit:
                    return completed(
                        "+| retry_resolution | pkg-no-action integrated |\n"
                        "+| retry_resolution | pkg-empty no_valid_change |\n")
                return completed(
                    "+| retry_resolution | **pkg-action integrated** | verified |\n")
            if operation == "show" and commit == action_commit:
                return completed(
                    "diff --git a/sts2-ascend/brain/policy.py "
                    "b/sts2-ascend/brain/policy.py\n"
                    "--- a/sts2-ascend/brain/policy.py\n"
                    "+++ b/sts2-ascend/brain/policy.py\n"
                    "@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n")
            return completed(returncode=1)

        packages = ["pkg-action", "pkg-no-action", "pkg-empty"]
        with (mock.patch.object(llm_review, "REPO_DIR", repo),
              mock.patch.object(llm_review, "REVIEW_LOG", repo / report_path),
              mock.patch.object(llm_review, "_upstream_ref", return_value="origin/main"),
              mock.patch.object(llm_review, "_review_stop_requested",
                                return_value=False),
              mock.patch.object(llm_review.subprocess, "run", side_effect=fake_git)):
            found = llm_review._committed_retry_resolutions(
                packages, log=lambda _message: None)

        self.assertEqual(found, {
            "pkg-action": ("integrated", action_commit),
            "pkg-empty": ("no_valid_change", report_only_commit),
        })

    def test_recovered_batch_description_is_ordered_and_honest(self) -> None:
        self.assertEqual(llm_review._batch_description([730, 698, 699, 729]),
                         "第 698~730 局范围内的 4 局")
        self.assertEqual(llm_review._batch_description([3, 2, 1]), "第 1~3 局")

    def test_default_policy_requires_runtime_action_every_batch(self) -> None:
        cfg = llm_review.load_llm_config()
        self.assertTrue(cfg["review_require_action_every_batch"])
        self.assertEqual(cfg["review_report_only_limit"], 2)
        self.assertEqual(cfg["review_evidence_run_threshold"], 3)
        self.assertEqual(cfg["review_evidence_batch_threshold"], 2)

    def test_model_editable_config_can_adjust_closure_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-config-") as root:
            path = Path(root) / "config.json"
            path.write_text(json.dumps({"llm": {
                "review_require_action_every_batch": False,
                "review_report_only_limit": 11,
                "review_evidence_run_threshold": 12,
                "review_evidence_batch_threshold": 13,
            }}), encoding="utf-8")
            with mock.patch.object(llm_review, "CONFIG_PATH", path):
                cfg = llm_review.load_llm_config()
        self.assertFalse(cfg["review_require_action_every_batch"])
        self.assertEqual(cfg["review_report_only_limit"], 11)
        self.assertEqual(cfg["review_evidence_run_threshold"], 12)
        self.assertEqual(cfg["review_evidence_batch_threshold"], 13)

    def test_host_classification_cannot_be_satisfied_by_reports_or_tests(self) -> None:
        self.assertEqual(llm_review._review_action_paths([REPORT, CONCLUSION]), ())
        self.assertEqual(llm_review._review_action_paths([REPORT, SELFCHECK]), ())
        self.assertEqual(llm_review._review_action_paths(
            [REPORT, TEST, DOC, STATIC_KNOWLEDGE]), ())
        self.assertEqual(llm_review._review_action_paths([REPORT, AGENT]), (AGENT,))
        self.assertEqual(llm_review._review_action_paths([POLICY, SELFCHECK]), (POLICY,))
        self.assertEqual(
            llm_review._review_action_paths([AUTOGIT, CONFIG, SCRIPT]),
            (AUTOGIT, CONFIG, SCRIPT),
        )

    def test_action_and_brain_hot_restart_boundaries_are_distinct(self) -> None:
        self.assertEqual(
            llm_review._review_hot_restart_paths(
                [POLICY, AUTOGIT, CONFIG, SCRIPT, TEST, DOC, SELFCHECK]),
            (POLICY, AUTOGIT, CONFIG),
        )
        self.assertEqual(
            llm_review._review_hot_restart_paths(
                [TTS_OWNER, TTS_GPU, TTS_EPOCH, SCRIPT]),
            (TTS_OWNER, TTS_GPU, TTS_EPOCH),
        )
        script_patch = (
            "diff --git a/sts2-ascend/scripts/Start-Agent.ps1 "
            "b/sts2-ascend/scripts/Start-Agent.ps1\n"
            "--- a/sts2-ascend/scripts/Start-Agent.ps1\n"
            "+++ b/sts2-ascend/scripts/Start-Agent.ps1\n"
            "@@ -1,0 +2 @@\n+$ready = $true\n"
        ).encode()
        brain_patch = (
            "diff --git a/sts2-ascend/brain/autogit.py "
            "b/sts2-ascend/brain/autogit.py\n"
            "--- a/sts2-ascend/brain/autogit.py\n"
            "+++ b/sts2-ascend/brain/autogit.py\n"
            "@@ -1,0 +2 @@\n+READY = True\n"
        ).encode()
        self.assertTrue(llm_review._patch_has_substantive_action(
            script_patch, [SCRIPT]))
        self.assertFalse(llm_review._patch_requires_brain_restart(
            script_patch, [SCRIPT]))
        self.assertTrue(llm_review._patch_requires_brain_restart(
            brain_patch, [AUTOGIT]))

    def test_restart_marker_records_the_whole_mixed_transaction(self) -> None:
        payload = llm_review._restart_marker_payload(
            "a" * 40, "b" * 40, "c" * 40,
            [POLICY, SCRIPT, DOC, POLICY], "2026-08-27 18:00")
        self.assertEqual(payload["paths"], [POLICY, SCRIPT, DOC])
        self.assertEqual(payload["state"], "prepared")
        self.assertEqual(payload["review_commit"], "c" * 40)

    def test_every_batch_gate_rejects_docs_and_accepts_runtime_observability(self) -> None:
        state = {
            "action_required": True,
            "require_action_every_batch": True,
            "consecutive_report_only": 3,
            "report_only_limit": 2,
        }
        denied = llm_review._review_closure_gate_error(state, [REPORT, CONCLUSION])
        self.assertIn("每批落地", denied)
        self.assertIn("仅 selfcheck", denied)
        self.assertEqual(llm_review._review_closure_gate_error(state, [REPORT, AGENT]), "")

        comment_only = (
            "diff --git a/sts2-ascend/brain/agent.py b/sts2-ascend/brain/agent.py\n"
            "--- a/sts2-ascend/brain/agent.py\n"
            "+++ b/sts2-ascend/brain/agent.py\n"
            "@@ -1 +1 @@\n-old = 1\n+# 只写注释冒充观测\n"
        ).encode()
        # The removed executable line makes this a substantive deletion; use a
        # pure added-comment hunk for the actual rejection case.
        pure_comment = (
            "diff --git a/sts2-ascend/brain/agent.py b/sts2-ascend/brain/agent.py\n"
            "--- a/sts2-ascend/brain/agent.py\n"
            "+++ b/sts2-ascend/brain/agent.py\n"
            "@@ -1,0 +2 @@\n+# 只写注释冒充观测\n"
        ).encode()
        code_change = (
            "diff --git a/sts2-ascend/brain/agent.py b/sts2-ascend/brain/agent.py\n"
            "--- a/sts2-ascend/brain/agent.py\n"
            "+++ b/sts2-ascend/brain/agent.py\n"
            "@@ -1,0 +2 @@\n+log('closure metric')\n"
        ).encode()
        self.assertTrue(llm_review._patch_has_substantive_action(comment_only, [AGENT]))
        self.assertFalse(llm_review._patch_has_substantive_action(pure_comment, [AGENT]))
        self.assertIn("注释/空白", llm_review._review_closure_gate_error(
            state, [REPORT, AGENT], pure_comment))
        self.assertEqual(llm_review._review_closure_gate_error(
            state, [REPORT, AGENT], code_change), "")

    def test_bootstrap_counts_report_only_commits_until_last_runtime_action(self) -> None:
        output = """__STS2_REVIEW_COMMIT__new

sts2-ascend/knowledge/meta_review.md
sts2-ascend/knowledge/review_conclusion.txt
__STS2_REVIEW_COMMIT__older

sts2-ascend/knowledge/meta_review.md
__STS2_REVIEW_COMMIT__action

sts2-ascend/brain/policy.py
sts2-ascend/knowledge/meta_review.md
"""
        completed = SimpleNamespace(returncode=0, stdout=output)
        with mock.patch.object(llm_review.subprocess, "run", return_value=completed):
            self.assertEqual(llm_review._infer_recent_report_only_streak(), 2)

    def test_state_is_host_owned_and_hard_required_even_after_implementation(self) -> None:
        know = SimpleNamespace(progression={
            "review_report_only_streak": 0,
            "review_closure_last_outcome": "implemented",
        })
        state = llm_review._review_closure_state(know, {
            "review_require_action_every_batch": True,
            "review_report_only_limit": 2,
            "review_evidence_run_threshold": 3,
            "review_evidence_batch_threshold": 2,
        })
        self.assertEqual(state["state_source"], "progression")
        self.assertTrue(state["action_required"])
        self.assertEqual(state["consecutive_report_only"], 0)

    def test_only_accepted_runtime_action_resets_streak(self) -> None:
        know = SimpleNamespace(progression={})
        base = {"consecutive_report_only": 4, "report_only_limit": 2,
                "require_action_every_batch": True}
        llm_review._record_review_closure(
            know, base, [REPORT, POLICY, SELFCHECK], [721, 722, 723],
            log=lambda _message: None)
        self.assertEqual(know.progression["review_report_only_streak"], 0)
        self.assertEqual(know.progression["review_closure_last_outcome"], "implemented")
        self.assertEqual(know.progression["review_closure_last_runs"], [721, 722, 723])

    def test_historical_zero_code_sections_are_injected_as_debt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-debt-") as root:
            report = Path(root) / "meta_review.md"
            report.write_text(
                "# 2026-08-27｜第 700 局复盘\n零代码纪律，问题 A 待立项。\n\n"
                "# 2026-08-27｜第 701 局复盘\n已修改 policy.py。\n\n"
                "# 2026-08-27｜第 702 局复盘\n未改任何 .py，问题 B 待观察。\n",
                encoding="utf-8")
            with mock.patch.object(llm_review, "REVIEW_LOG", report):
                debt = llm_review._historical_zero_code_context()
        self.assertIn("问题 A", debt)
        self.assertIn("问题 B", debt)
        self.assertNotIn("已修改 policy.py", debt)

    def test_prompt_forbids_zero_code_and_requires_historical_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-prompt-") as root:
            knowledge = Path(root)
            (knowledge / "lessons.md").write_text("lesson", encoding="utf-8")
            report = knowledge / "meta_review.md"
            report.write_text(
                "# 2026-08-27｜第 723 局复盘\n零代码纪律，成长姿态第4例。\n",
                encoding="utf-8")
            know = SimpleNamespace(
                progression={"review_report_only_streak": 3},
                stats={"global": {"runs": 723}}, game_knowledge=None)
            state = {
                "action_required": True,
                "require_action_every_batch": True,
                "consecutive_report_only": 3,
                "report_only_limit": 2,
                "evidence_run_threshold": 3,
                "evidence_batch_threshold": 2,
                "state_source": "test",
            }
            with (mock.patch.object(llm_review, "KNOWLEDGE_DIR", knowledge),
                  mock.patch.object(llm_review, "REVIEW_LOG", report),
                  mock.patch.object(llm_review, "_review_run_records", return_value=[]),
                  mock.patch.object(llm_review, "_stats_digest", return_value={})):
                prompt = llm_review.build_prompt(
                    know, {"max_runs_in_packet": 100}, batch_runs=[723],
                    closure_state=state)
        self.assertIn("每个成功复盘批次", prompt)
        self.assertIn("相对安全", prompt)
        self.assertIn("历史问题", prompt)
        self.assertIn("成长姿态第4例", prompt)
        self.assertIn("纯 `meta_review.md`", prompt)
        self.assertIn("deny-only", prompt)
        self.assertIn("`brain/config.json`", prompt)
        self.assertIn("`scripts/`、`tests/`、`docs/`", prompt)
        self.assertIn("静态原生游戏", prompt)
        self.assertIn("允许当前隔离 clone 内", prompt)
        self.assertIn("禁止 remote、push、reset", prompt)
        self.assertIn("user.name=sts2-review-agent", prompt)
        self.assertNotIn("sts2-review-luna", prompt)
        self.assertLess(prompt.index("3. 落地："), prompt.index("5. 最后才写报告："))
        self.assertIn("BLOCKED_TOOL_CAPABILITY", prompt)
        self.assertIn("初始读取或 shell 本身被", prompt)
        self.assertIn("`Access is denied (os error 5)` 或 `WinError 5`", prompt)
        self.assertIn("sandbox DACL 的稳定权限拒绝", prompt)
        self.assertIn("交宿主修复 ACL", prompt)
        self.assertIn("generic `Failed to write file`", prompt)
        self.assertIn("明确的 `Sharing violation`", prompt)
        self.assertIn("在首次失败之后至少再重试 3 次", prompt)
        self.assertIn(llm_review._APPLY_PATCH_PATH_CONTRACT, prompt)
        self.assertIn("`git rev-parse --show-toplevel`", prompt)
        self.assertIn("`sts2-ascend/brain/knowledge.py`", prompt)
        self.assertIn("绝不能拼入 Apply Patch 路径", prompt)
        self.assertIn("禁止粘贴或重复 clone 根目录", prompt)
        self.assertIn("禁止缩写成 `brain/knowledge.py`", prompt)
        self.assertIn("`writing outside of the project`", prompt)
        self.assertIn("只重试一次原生 Apply Patch", prompt)
        self.assertLess(
            prompt.index("`writing outside of the project`"),
            prompt.index("generic `Failed to write file`"),
        )
        self.assertIn("不得管理或终止进程", prompt)
        self.assertIn("不得改用 shell、脚本、重定向等旁路写法", prompt)
        self.assertIn("全部失败才输出", prompt)
        self.assertNotIn("Windows `Access is denied`，把它视为", prompt)
        self.assertNotIn("任何本地读取、shell 或 Apply Patch 再出现", prompt)
        self.assertNotIn("安全基础设施不可自改", prompt)
        self.assertNotIn("不得修改 `brain/autogit.py`", prompt)

    def test_short_invocation_teaches_bounded_apply_patch_retry(self) -> None:
        prompt = llm_review._review_invocation_prompt(
            "sts2-ascend/knowledge/review_prompt_latest.md")

        self.assertIn("修改 sts2-ascend 静态项目文件", prompt)
        self.assertIn("SELFCHECK OK", prompt)
        self.assertIn("commit SHA", prompt)
        self.assertIn("BLOCKED_TOOL_CAPABILITY", prompt)
        self.assertIn("初始读取或 shell 本身被 blocked/access denied", prompt)
        self.assertIn("Access is denied (os error 5) 或 WinError 5", prompt)
        self.assertIn("稳定 DACL 拒绝", prompt)
        self.assertIn("立即输出 BLOCKED_TOOL_CAPABILITY 并交宿主修复 ACL", prompt)
        self.assertIn("generic Failed to write file", prompt)
        self.assertIn("明确 Sharing violation", prompt)
        self.assertIn("首次失败后至少再重试 3 次", prompt)
        self.assertIn(llm_review._APPLY_PATCH_PATH_CONTRACT, prompt)
        self.assertIn("`git rev-parse --show-toplevel`", prompt)
        self.assertIn("`sts2-ascend/brain/knowledge.py`", prompt)
        self.assertIn("绝不能拼入 Apply Patch 路径", prompt)
        self.assertIn("禁止粘贴或重复 clone 根目录", prompt)
        self.assertIn("禁止缩写成 `brain/knowledge.py`", prompt)
        self.assertIn("`writing outside of the project`", prompt)
        self.assertIn("只重试一次原生 Apply Patch", prompt)
        self.assertLess(
            prompt.index("`writing outside of the project`"),
            prompt.index("generic Failed to write file"),
        )
        self.assertIn("不得管理或终止进程", prompt)
        self.assertIn("不得换用 shell/脚本/重定向等旁路写法", prompt)
        self.assertIn("全部失败才 BLOCKED", prompt)
        self.assertNotIn("Access is denied，须将其视为瞬态共享冲突", prompt)
        self.assertNotIn("Apply Patch 被 blocked/access denied，立即输出", prompt)
        self.assertLess(prompt.index("最小生产行为/观测改动"), prompt.index("最后才写报告"))

    def test_tool_access_failure_outranks_report_only_closure(self) -> None:
        sandbox = llm_review.SandboxReviewResult(
            rc=0,
            provider_metrics={
                "blocked_tool_count": 3,
                "tool_access_error": "CreateProcess rejected: blocked by policy",
            },
        )

        error = llm_review._provider_tool_capability_error("codex", sandbox)

        self.assertIn("runner 工具能力被阻断", error)
        sandbox.failure_code = "runner_tool_access_denied"
        self.assertEqual(
            llm_review._salvage_kind(error, sandbox),
            "runner_tool_access_denied",
        )
        self.assertIsNone(sandbox.selfcheck_ok)

    def test_retry_closure_uses_actual_luna_backend_label(self) -> None:
        manifest = {
            "retry_resolution": "integrated",
            "retry_resolution_commit": "a" * 40,
            "retry_backend_key": "luna-max",
            "retry_runner": "codex",
            "retry_model": "gpt-5.6-luna",
            "retry_reasoning_effort": "max",
        }
        captured = {}

        def update(_name, _manifest, **kwargs):
            captured.update(kwargs)
            return True

        with (mock.patch.object(llm_review, "_review_stop_requested",
                                return_value=False),
              mock.patch.object(llm_review, "_upstream_contains_commit",
                                return_value=True),
              mock.patch.object(llm_review, "_ensure_rejection_ledger_marker",
                                return_value=True),
              mock.patch.object(llm_review, "_update_rejection_ledger",
                                side_effect=update),
              mock.patch.object(llm_review, "_publish_manifest_update"),
              mock.patch.object(llm_review, "_publish_review_hold_closure",
                                return_value=True),
              mock.patch.object(llm_review, "_delete_closed_quarantine",
                                return_value=True)):
            self.assertTrue(llm_review._finish_quarantined_salvage(
                Path("X:/salvage/.glm-closed-pkg"), "pkg", manifest,
                log=lambda _message: None))

        self.assertEqual(
            captured["status"],
            "luna-max (codex/gpt-5.6-luna@max) 已补合并闭环 `aaaaaaaa`")
        self.assertIn("luna-max (codex/gpt-5.6-luna@max) 重审结论",
                      captured["reason"])
        self.assertNotIn("GLM", captured["status"])

    def test_crash_recovery_does_not_guess_resolver_from_failed_model(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-neutral-resolver-") as root:
            salvage = Path(root)
            target = "pkg-target"
            package = salvage / target
            package.mkdir()
            (package / "manifest.json").write_text(json.dumps({
                "model": "kimi-for-coding/k3",
                "runner": "opencode",
                "backend_key": "kimi-k3",
                "replay_target": target,
                "replay_role": "target",
            }), encoding="utf-8")
            with (mock.patch.object(llm_review, "SALVAGE_ROOT", salvage),
                  mock.patch.object(llm_review, "_review_hold_contains_package",
                                    return_value=False),
                  mock.patch.object(llm_review, "_upstream_contains_commit",
                                    return_value=True)):
                result = llm_review._close_replayed_salvages(
                    [target], [], {target: "integrated"},
                    commit="b" * 40, pushed=True, review_backend=None,
                    log=lambda _message: None)

            persisted = json.loads(
                (package / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result["host_pending"], [target])
            self.assertEqual(persisted["retry_backend_label"], "执行后端未记录")
            self.assertEqual(persisted["retry_model"], "")
            self.assertNotIn("kimi", persisted["retry_backend_label"].lower())

    def test_neutral_lifecycle_closure_is_terminal(self) -> None:
        package = "pkg-neutral-closure"
        ledger = (
            f"<!-- rejection:{package} -->\n"
            "| now | run | `aaaaaaaa` | 维护中断/取消（lifecycle_stop） | kimi | "
            "维护中断/取消；复盘已补合并闭环 `abcdef12` | cleanup | reason |\n")
        completed = SimpleNamespace(returncode=0, stdout=ledger)
        with (mock.patch.object(llm_review, "_upstream_ref",
                                return_value="origin/main"),
              mock.patch.object(llm_review.subprocess, "run",
                                return_value=completed)):
            self.assertTrue(
                llm_review._upstream_ledger_has_terminal_closure(package))

    def test_retry_feedback_recovers_legacy_tool_block_and_not_run_selfcheck(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-feedback-") as root:
            salvage_root = Path(root)
            package = salvage_root / "pkg-target"
            package.mkdir()
            (package / "manifest.json").write_text(json.dumps({
                "failure_kind": "review_failure",
                "reason": "闭环闸门拒绝纯报告",
                "return_code": 0,
                "selfcheck_ok": True,
                "patch_bytes": 0,
                "provider_metrics": {"command_count": 0, "file_change_count": 0},
            }), encoding="utf-8")
            (package / "model_output_tail.txt").write_text(
                "CreateProcess rejected: blocked by policy\n", encoding="utf-8")
            with mock.patch.object(llm_review, "SALVAGE_ROOT", salvage_root):
                feedback = llm_review._review_retry_feedback(["pkg-target"])

        row = feedback["previous_attempts"][0]
        self.assertEqual(row["failure_code"], "runner_tool_access_denied")
        self.assertEqual(row["selfcheck_state"], "not_run")
        self.assertIn("blocked by policy", row["tool_access_error"])

    def test_prompt_explains_inline_packet_and_rewrites_native_corpus_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-packet-") as root:
            repo = Path(root) / "repo"
            knowledge = repo / "sts2-ascend" / "knowledge"
            knowledge.mkdir(parents=True)
            (knowledge / "lessons.md").write_text("lesson", encoding="utf-8")
            manifest = (knowledge / "game" / "v0.111.0" / "manifest.json").as_posix()
            mechanics = (knowledge / "game" / "v0.111.0" /
                         "mechanics" / "<category>.jsonl").as_posix()
            digest = {
                "snapshot": {"available": True},
                "corpus_paths": {
                    "manifest": manifest,
                    "groups": [{"mechanics": mechanics}],
                    "external": "Z:/external/native.jsonl",
                },
            }
            native = SimpleNamespace(review_digest=mock.Mock(return_value=digest))
            know = SimpleNamespace(progression={}, stats={}, game_knowledge=native)
            state = {
                "action_required": True,
                "require_action_every_batch": True,
                "consecutive_report_only": 2,
                "report_only_limit": 2,
            }
            with (mock.patch.object(llm_review, "REPO_DIR", repo),
                  mock.patch.object(llm_review, "KNOWLEDGE_DIR", knowledge),
                  mock.patch.object(llm_review, "REVIEW_LOG", knowledge / "meta_review.md"),
                  mock.patch.object(llm_review, "_review_run_records", return_value=[]),
                  mock.patch.object(llm_review, "_stats_digest", return_value={})):
                prompt = llm_review.build_prompt(
                    know, {"max_runs_in_packet": 100}, batch_runs=[724],
                    closure_state=state)

        packet_text = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]
        packet = json.loads(packet_text)
        paths = packet["native_game_knowledge"]["corpus_paths"]
        self.assertEqual(
            paths["manifest"],
            "sts2-ascend/knowledge/game/v0.111.0/manifest.json")
        self.assertEqual(
            paths["groups"][0]["mechanics"],
            "sts2-ascend/knowledge/game/v0.111.0/mechanics/<category>.jsonl")
        self.assertEqual(paths["external"], "Z:/external/native.jsonl")
        self.assertEqual(digest["corpus_paths"]["manifest"], manifest)
        self.assertIn("第一个 `json` 代码块就是完整 packet", prompt)
        self.assertIn("不存在独立的 packet JSON 文件", prompt)
        self.assertIn("`json.loads` 解析", prompt)
        self.assertIn("# review_closure 快速摘要", prompt)
        self.assertIn("action_required=true；require_action_every_batch=true", prompt)


if __name__ == "__main__":
    unittest.main()
