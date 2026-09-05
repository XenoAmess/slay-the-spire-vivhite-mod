"""Runner-adapter regressions for the GLM -> DeepSeek -> Kimi -> Luna chain."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
ASCEND = BRAIN.parent
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402
import review_runners  # noqa: E402
import autogit  # noqa: E402
from review_runners import (  # noqa: E402
    CodexJsonTranslator,
    ProviderRateLimit,
    ReviewPlan,
    RunnerToolPathEscape,
    bind_review_workdir,
    build_review_command,
    detect_provider_rate_limit,
    parse_retry_after,
    review_plans_from_config,
)


class ReviewPlanTests(unittest.TestCase):
    def test_amd_provider_uses_environment_secret_and_exact_endpoint(self) -> None:
        provider = json.loads(
            (ASCEND.parent / "opencode.json").read_text(encoding="utf-8")
        )["provider"]["amd-radeon"]

        self.assertEqual(provider["options"]["baseURL"],
                         "https://developer.amd.com.cn/radeon/api/v1")
        self.assertEqual(provider["options"]["apiKey"],
                         "{env:AMD_RADEON_API_KEY}")
        self.assertEqual(list(provider["models"]), ["DeepSeek-V4-Flash"])
        self.assertNotIn("rc-", json.dumps(provider))

    def test_production_chain_places_luna_last(self) -> None:
        cfg = json.loads((BRAIN / "config.json").read_text(encoding="utf-8"))["llm"]

        plans = review_plans_from_config(cfg)

        self.assertEqual(
            [(plan.priority, plan.key, plan.runner, plan.model) for plan in plans],
            [
                (1, "glm-flash", "opencode", "opencode-go/glm-5.3-flash"),
                (2, "deepseek-v4-flash", "opencode", "amd-radeon/DeepSeek-V4-Flash"),
                (3, "kimi-k3", "opencode", "kimi-for-coding/k3"),
                (4, "luna-max", "codex", "gpt-5.6-luna"),
            ],
        )
        self.assertEqual(
            [(plan.key, plan.source) for plan in plans],
            [
                ("glm-flash", "preferred"),
                ("deepseek-v4-flash", "preferred"),
                ("kimi-k3", "preferred"),
                ("luna-max", "fallback"),
            ],
        )

    def test_production_luna_denies_approval_with_workspace_sandbox(self) -> None:
        cfg = json.loads((BRAIN / "config.json").read_text(encoding="utf-8"))

        luna = next(
            plan for plan in review_plans_from_config(cfg["llm"])
            if plan.key == "luna-max")

        self.assertFalse(luna.approve_for_me)
        self.assertEqual(luna.sandbox, "workspace-write")

    def test_production_codex_resolves_the_pinned_user_cache_binary(self) -> None:
        cfg = json.loads((BRAIN / "config.json").read_text(encoding="utf-8"))["llm"]

        binary = review_runners.runner_binary(cfg, "codex")

        self.assertEqual(cfg["codex_compat_version"], "0.148.0")
        self.assertEqual(
            cfg["codex_compat_sha256"],
            "2AD2CF8A732DA68B8F141634F92DB1A03016C5FAF533A7225FBC0FB740130410")
        self.assertEqual(
            os.path.normcase(str(binary)),
            os.path.normcase(os.path.expandvars(cfg["runner_bins"]["codex"])))

    def test_explicit_three_level_chain_preserves_runner_specific_options(self) -> None:
        cfg = {
            "review_model_chain": [
                {"key": "kimi", "priority": 3, "runner": "opencode",
                 "model": "kimi-for-coding/k3", "every_runs": 5},
                {"key": "glm", "priority": 1, "runner": "opencode",
                 "model": "opencode-go/glm-5.3-flash", "variant": "max"},
                {"key": "luna", "priority": 2, "runner": "codex",
                 "model": "gpt-5.6-luna", "reasoning_effort": "max",
                 "approve_for_me": True, "sandbox": "workspace-write"},
            ],
        }

        plans = review_plans_from_config(cfg)

        self.assertEqual([plan.key for plan in plans], ["glm", "luna", "kimi"])
        self.assertEqual(plans[0].display_model, "opencode-go/glm-5.3-flash@max")
        self.assertEqual(
            (plans[1].runner, plans[1].display_model, plans[1].approve_for_me),
            ("codex", "gpt-5.6-luna@max", True),
        )
        self.assertEqual((plans[2].every_runs, plans[2].source), (5, "fallback"))

    def test_legacy_two_level_config_is_still_supported(self) -> None:
        plans = review_plans_from_config({
            "preferred_models": ["opencode-go/glm-5.3-flash@max"],
            "preferred_every_runs": 1,
            "model": "kimi-for-coding/k3",
            "review_every_runs": 5,
        })

        self.assertEqual(len(plans), 2)
        self.assertEqual(
            (plans[0].runner, plans[0].model, plans[0].variant, plans[0].source),
            ("opencode", "opencode-go/glm-5.3-flash", "max", "preferred"),
        )
        self.assertEqual(
            (plans[1].runner, plans[1].model, plans[1].every_runs, plans[1].source),
            ("opencode", "kimi-for-coding/k3", 5, "fallback"),
        )
    def test_empty_explicit_chain_falls_back_to_legacy_config(self) -> None:
        plans = review_plans_from_config({
            "review_model_chain": [{"runner": "codex", "model": ""}],
            "preferred_models": ["opencode-go/glm-5.3-flash@max"],
            "model": "kimi-for-coding/k3",
            "review_every_runs": 5,
        })

        self.assertEqual([plan.model for plan in plans],
                         ["opencode-go/glm-5.3-flash", "kimi-for-coding/k3"])



    def test_codex_command_hardens_legacy_auto_review_plan(self) -> None:
        plan = ReviewPlan(
            key="luna", priority=2, runner="codex", model="gpt-5.6-luna",
            reasoning_effort="max", approve_for_me=True,
            sandbox="workspace-write", every_runs=1, source="preferred")

        command = build_review_command(
            plan, "codex.CMD", Path("C:/review/repo"), "read prompt", title="ignored")

        self.assertEqual(
            command[:6],
            ["codex.CMD", "-a", "never", "exec", "--model", "gpt-5.6-luna"])
        reasoning_config = 'model_reasoning_effort="max"'
        windows_config = 'windows.sandbox="unelevated"'
        permission_config = (
            'permissions.luna_commit={extends=":workspace",'
            'filesystem={":workspace_roots"={".git"="write"}},'
            'network={enabled=false}}')
        default_config = 'default_permissions="luna_commit"'
        self.assertIn(reasoning_config, command)
        self.assertEqual(
            [value for value in command if value.startswith("windows.sandbox=")],
            [windows_config])
        self.assertIn(permission_config, command)
        self.assertIn(default_config, command)
        windows_index = command.index(windows_config)
        self.assertEqual(command[windows_index - 1], "-c")
        self.assertLess(command.index(reasoning_config), windows_index)
        self.assertLess(windows_index, command.index(permission_config))
        self.assertLess(command.index(permission_config), command.index(default_config))
        self.assertLess(command.index(default_config), command.index("--json"))
        for option in ("--json", "--ephemeral", "--ignore-user-config"):
            self.assertIn(option, command)
        self.assertNotIn("--approve-for-me", command)
        self.assertEqual(sum(option in {"-C", "--cd"} for option in command), 1)
        for forbidden in (
            "--sandbox", "--add-dir", "--yolo",
            "--dangerously-bypass-approvals-and-sandbox", "danger-full-access",
        ):
            self.assertNotIn(forbidden, command)
        self.assertLess(command.index("-a"), command.index("exec"))
        self.assertGreater(command.index("--ignore-user-config"), command.index("exec"))
        self.assertEqual(command[command.index("-C") + 1], "C:\\review\\repo")
        self.assertEqual(command[-1], "read prompt")

        rebound = bind_review_workdir(command, "codex", Path("D:/isolated/repo"))
        self.assertEqual(rebound[rebound.index("-C") + 1], "D:\\isolated\\repo")

    def test_codex_command_uses_custom_profile_without_auto_review(self) -> None:
        plan = ReviewPlan(
            key="luna", priority=2, runner="codex", model="gpt-5.6-luna",
            sandbox="workspace-write", approve_for_me=False,
            every_runs=1, source="preferred")

        command = build_review_command(
            plan, "codex.CMD", Path("C:/review/repo"), "read prompt", title="ignored")

        self.assertEqual(
            command[:6],
            ["codex.CMD", "-a", "never", "exec", "--model", "gpt-5.6-luna"])
        self.assertNotIn("--approve-for-me", command)
        self.assertNotIn("--sandbox", command)
        self.assertEqual(command.count('windows.sandbox="unelevated"'), 1)
        self.assertIn('default_permissions="luna_commit"', command)

    def test_codex_rejects_a_non_workspace_sandbox(self) -> None:
        plan = ReviewPlan(
            key="luna", priority=2, runner="codex", model="gpt-5.6-luna",
            sandbox="read-only", approve_for_me=True,
            every_runs=1, source="preferred")

        with self.assertRaisesRegex(
                ValueError, "requires workspace-write configuration semantics"):
            build_review_command(
                plan, "codex.CMD", Path("C:/review/repo"), "read prompt",
                title="ignored")


    def test_opencode_command_keeps_variant_and_json_stream(self) -> None:
        plan = ReviewPlan(
            key="glm", priority=1, runner="opencode",
            model="opencode-go/glm-5.3-flash", variant="max",
            every_runs=1, source="preferred")

        command = build_review_command(
            plan, "opencode.exe", "C:/review/repo", "read prompt", title="batch")

        self.assertEqual(command[:4], ["opencode.exe", "run", "--model",
                                      "opencode-go/glm-5.3-flash"])
        self.assertEqual(command[command.index("--variant") + 1], "max")
        self.assertEqual(command[command.index("--format") + 1], "json")
        self.assertEqual(command[command.index("--dir") + 1], "C:/review/repo")


class CodexTranslatorTests(unittest.TestCase):
    def test_structured_http_429_records_retry_after_without_model_work(self) -> None:
        translator = CodexJsonTranslator()
        rendered = translator.feed(json.dumps({
            "type": "turn.failed",
            "error": {
                "message": "Too Many Requests",
                "response": {
                    "status_code": 429,
                    "headers": {"Retry-After": "75"},
                },
            },
        }))

        metrics = translator.metrics()

        self.assertTrue(rendered)
        self.assertTrue(metrics["rate_limit_detected"])
        self.assertTrue(metrics["rate_limited"])
        self.assertEqual(metrics["rate_limit_status"], 429)
        self.assertEqual(metrics["retry_after_seconds"], 75.0)
        self.assertEqual(metrics["rate_limit"]["status_code"], 429)
        self.assertFalse(metrics["model_work_started"])

    def test_rate_limit_uses_largest_retry_after_across_reconnect_events(self) -> None:
        translator = CodexJsonTranslator()
        translator.feed(json.dumps({
            "type": "error",
            "error": {"status": 429},
            "headers": {"retry-after": 15},
        }))
        translator.feed(json.dumps({
            "type": "error",
            "message": "HTTP 429: Too Many Requests; Retry-After: 90",
        }))

        metrics = translator.metrics()

        self.assertEqual(metrics["retry_after_seconds"], 90.0)
        self.assertEqual(metrics["rate_limit_retry_after_seconds"], 90.0)

    def test_ordinary_errors_and_model_shell_output_do_not_become_rate_limits(self) -> None:
        translator = CodexJsonTranslator()
        translator.feed(json.dumps({
            "type": "error",
            "error": {
                "status_code": 500,
                "message": "upstream mentioned HTTP 429 while reporting a 500",
            },
        }))
        translator.feed(json.dumps({
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "status": "failed",
                "aggregated_output": "fixture expects HTTP 429 but assertion failed",
            },
        }))
        translator.feed("ordinary task 429 failed")

        metrics = translator.metrics()

        self.assertFalse(metrics["rate_limit_detected"])
        self.assertIsNone(metrics["retry_after_seconds"])

    def test_jsonl_translation_records_work_usage_and_tool_metrics(self) -> None:
        translator = CodexJsonTranslator(ASCEND)
        events = [
            {"type": "thread.started", "thread_id": "thread-123"},
            {"type": "item.started", "item": {
                "type": "command_execution", "command": "git status"}},
            {"type": "item.completed", "item": {
                "type": "file_change", "changes": [{"path": "brain/policy.py"}]}},
            {"type": "item.completed", "item": {
                "type": "mcp_tool_call", "name": "tool", "arguments": {"x": 1}}},
            {"type": "item.completed", "item": {
                "type": "agent_message", "text": "done"}},
            {"type": "turn.completed", "usage": {
                "input_tokens": 100, "cached_input_tokens": 25,
                "output_tokens": 20}},
        ]

        rendered = [line for event in events
                    for line in translator.feed(json.dumps(event))]
        metrics = translator.metrics()

        self.assertTrue(metrics["model_work_started"])
        self.assertEqual(metrics["thread_id"], "thread-123")
        self.assertEqual(metrics["command_count"], 1)
        self.assertEqual(metrics["file_change_count"], 1)
        self.assertEqual(metrics["tool_count"], 1)
        self.assertEqual(metrics["usage"]["output_tokens"], 20)
        self.assertIn("done", rendered)

    def test_file_change_paths_inside_bound_clone_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-codex-path-inside-") as root:
            clone = Path(root) / "repo"
            clone.mkdir()
            translator = CodexJsonTranslator(clone)
            event = {
                "type": "item.completed",
                "item": {
                    "type": "file_change",
                    "status": "completed",
                    "changes": [
                        {"path": "sts2-ascend/brain/policy.py"},
                        {"path": str(clone / "sts2-ascend" / "brain" / "selfcheck.py")},
                        {"path": "docs/review.md"},
                    ],
                },
            }

            rendered = translator.feed(json.dumps(event))

        self.assertTrue(rendered)
        metrics = translator.metrics()
        self.assertEqual(metrics["file_change_count"], 1)
        self.assertEqual(metrics["tool_path_escape_count"], 0)
        self.assertEqual(metrics["tool_access_failure_code"], "")

    def test_mixed_file_change_paths_fail_closed_on_escape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-codex-path-escape-") as root:
            clone = Path(root) / "repo"
            clone.mkdir()
            outside = Path(root) / "live-repo" / "sts2-ascend" / "brain" / "policy.py"
            translator = CodexJsonTranslator(clone)
            event = {
                "type": "item.started",
                "item": {
                    "type": "file_change",
                    "status": "in_progress",
                    "changes": [
                        {"path": "sts2-ascend/brain/policy.py"},
                        {"path": str(clone / "docs" / "review.md")},
                        {"path": str(outside)},
                    ],
                },
            }

            with self.assertRaisesRegex(
                    RunnerToolPathEscape, "escaped expected clone root"):
                translator.feed(json.dumps(event))

        metrics = translator.metrics()
        self.assertEqual(metrics["tool_path_escape_count"], 1)
        self.assertEqual(metrics["tool_access_failure_code"],
                         "runner_tool_path_escape")
        self.assertEqual(metrics["file_change_count"], 0)

    def test_malformed_file_change_paths_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-codex-path-malformed-") as root:
            clone = Path(root) / "repo"
            clone.mkdir()
            for changes in (
                None, [], [{"kind": "update"}], [{"path": "   "}], ["policy.py"],
            ):
                with self.subTest(changes=changes):
                    translator = CodexJsonTranslator(clone)
                    event = {
                        "type": "item.started",
                        "item": {"type": "file_change", "changes": changes},
                    }
                    with self.assertRaises(RunnerToolPathEscape):
                        translator.feed(json.dumps(event))
                    self.assertEqual(
                        translator.metrics()["tool_access_failure_code"],
                        "runner_tool_path_escape")

    def test_reset_clock_separates_first_event_from_first_model_work(self) -> None:
        with mock.patch.object(
                review_runners.time, "monotonic",
                side_effect=[10.0, 20.0, 20.25, 20.8]):
            translator = CodexJsonTranslator()
            translator.reset_clock()
            translator.feed(json.dumps({
                "type": "thread.started", "thread_id": "thread-123"}))
            translator.feed(json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "done"},
            }))

        metrics = translator.metrics()
        self.assertAlmostEqual(metrics["first_event_after_sec"], 0.25)
        self.assertAlmostEqual(metrics["first_model_work_after_sec"], 0.8)
        self.assertTrue(metrics["model_work_started"])

    def test_non_object_event_item_and_error_payloads_never_raise(self) -> None:
        translator = CodexJsonTranslator()

        self.assertEqual(translator.feed(json.dumps(["unexpected"])),
                         ['["unexpected"]'])
        self.assertTrue(translator.feed(json.dumps({
            "type": "item.completed", "item": "unexpected"})))
        rendered = translator.feed(json.dumps({
            "type": "error", "error": "transport failed"}))

        self.assertIn("transport failed", rendered[0])
        self.assertEqual(translator.metrics()["error_count"], 1)

    def test_transport_error_events_are_counted_without_inventing_model_work(self) -> None:
        translator = CodexJsonTranslator()
        for index in range(5):
            translator.feed(json.dumps({"type": "error", "message": f"retry {index}"}))

        metrics = translator.metrics()
        self.assertEqual(metrics["error_count"], 5)
        self.assertFalse(metrics["model_work_started"])

    def test_non_json_tool_policy_failure_is_counted_and_preserved(self) -> None:
        translator = CodexJsonTranslator()
        raw = (
            "ERROR codex_core::tools::router: exec_command failed: "
            "CreateProcess rejected: blocked by policy " + ("x" * 800)
        )

        self.assertEqual(translator.feed(raw), [raw])
        metrics = translator.metrics()

        self.assertEqual(metrics["non_json_lines"], 1)
        self.assertEqual(metrics["error_count"], 1)
        self.assertEqual(metrics["blocked_tool_count"], 1)
        self.assertLessEqual(len(metrics["tool_access_error"]), 500)
        self.assertIn("blocked by policy", metrics["tool_access_error"])

    def test_failed_command_output_mentioning_policy_block_is_not_host_denial(self) -> None:
        translator = CodexJsonTranslator()
        translator.feed(json.dumps({
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "status": "failed",
                "aggregated_output": (
                    '{"fixture":"blocked by policy","result":"assertion failed"}'
                ),
            },
        }))

        metrics = translator.metrics()
        self.assertEqual(metrics["blocked_tool_count"], 0)
        self.assertEqual(metrics["tool_access_failure_code"], "")
        self.assertEqual(metrics["tool_access_error"], "")

    def test_explicit_policy_block_contract_is_host_denial(self) -> None:
        translator = CodexJsonTranslator()
        translator.feed(json.dumps({
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": (
                    "BLOCKED_TOOL_CAPABILITY\n"
                    "Original error: exec_command blocked by policy"
                ),
            },
        }))

        metrics = translator.metrics()
        self.assertEqual(metrics["blocked_tool_count"], 1)
        self.assertEqual(
            metrics["tool_access_failure_code"], "runner_tool_access_denied")

    def test_codex_tool_access_denials_are_counted_once_per_event(self) -> None:
        translator = CodexJsonTranslator()
        translator.feed(json.dumps({
            "type": "error",
            "message": "apply_patch failed: Access is denied (os error 5)",
        }))
        translator.feed(json.dumps({
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "status": "failed",
                "aggregated_output": "Access denied",
            },
        }))
        translator.feed("ordinary diagnostic: access denied")

        metrics = translator.metrics()
        self.assertEqual(metrics["blocked_tool_count"], 2)
        self.assertEqual(metrics["error_count"], 2)
        self.assertEqual(metrics["non_json_lines"], 1)
        self.assertEqual(metrics["tool_access_error"], "Access denied")

    def test_reparse_apply_patch_failure_is_host_tool_capability(self) -> None:
        translator = CodexJsonTranslator()
        original = (
            "Failed to read file to update D:\\review\\repo\\brain\\policy.py: "
            "path contains a reparse point")
        translator.feed(
            "ERROR codex_core::tools::router: error=Exit code: 1 Output: " + original)
        translator.feed(json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": (
                "BLOCKED_TOOL_CAPABILITY\n\n原始错误：`" + original + "`")},
        }))

        metrics = translator.metrics()
        self.assertTrue(metrics["model_work_started"])
        self.assertGreaterEqual(metrics["blocked_tool_count"], 1)
        self.assertEqual(
            metrics["tool_access_failure_code"], "runner_tool_path_capability")
        self.assertIn("BLOCKED_TOOL_CAPABILITY", metrics["tool_access_error"])

    def test_reparse_words_without_tool_context_or_final_contract_are_ignored(self) -> None:
        translator = CodexJsonTranslator()
        translator.feed("ordinary traceback: path contains a reparse point")
        translator.feed(json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": (
                "analysis only: path contains a reparse point")},
        }))

        metrics = translator.metrics()
        self.assertEqual(metrics["blocked_tool_count"], 0)
        self.assertEqual(metrics["tool_access_failure_code"], "")

    def test_reparse_traceback_with_apply_patch_filename_is_not_host_tool_failure(self) -> None:
        translator = CodexJsonTranslator()
        traceback = (
            "Traceback: C:/app/apply_patch_worker.py line 8; "
            "OSError: path contains a reparse point")
        translator.feed(traceback)
        translator.feed(json.dumps({
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "status": "failed",
                "aggregated_output": traceback,
            },
        }))

        metrics = translator.metrics()
        self.assertEqual(metrics["blocked_tool_count"], 0)
        self.assertEqual(metrics["tool_access_failure_code"], "")


class OpencodeTranslatorTests(unittest.TestCase):
    def test_opencode_error_code_and_retry_after_are_structured(self) -> None:
        translator = llm_review.OpencodeJsonTranslator()

        translator.feed(json.dumps({
            "type": "error",
            "error": {
                "code": "rate_limit_exceeded",
                "message": "request rejected",
                "headers": {"retry_after": 42},
            },
        }))

        metrics = translator.metrics()
        self.assertTrue(metrics["rate_limit_detected"])
        self.assertEqual(metrics["rate_limit_status"], 429)
        self.assertEqual(metrics["retry_after_seconds"], 42.0)
        self.assertFalse(metrics["model_work_started"])

    def test_non_object_event_part_and_tokens_payloads_never_raise(self) -> None:
        translator = llm_review.OpencodeJsonTranslator()

        self.assertEqual(translator.feed(json.dumps(["unexpected"])),
                         ['["unexpected"]'])
        malformed_part = json.dumps({
            "type": "text", "part": "unexpected"})
        self.assertEqual(translator.feed(malformed_part), [malformed_part])
        self.assertEqual(translator.feed(json.dumps({
            "part": {"type": "step-finish", "tokens": "unexpected"}})), [])

        metrics = translator.metrics()
        self.assertEqual(metrics["non_json_lines"], 2)
        self.assertFalse(metrics["model_work_started"])


class ProviderRateLimitParsingTests(unittest.TestCase):
    def test_retry_after_accepts_delta_and_http_date(self) -> None:
        self.assertEqual(parse_retry_after("12.5"), 12.5)
        self.assertEqual(
            parse_retry_after(
                "Wed, 21 Oct 2015 07:28:00 GMT", now=1445412420.0),
            60.0,
        )
        for malformed in (True, -1, "-1", "NaN", "wait 12 seconds"):
            with self.subTest(value=malformed):
                self.assertIsNone(parse_retry_after(malformed))

    def test_explicit_status_is_returned_as_a_serializable_signal(self) -> None:
        signal = detect_provider_rate_limit({
            "error": {
                "http_status": "429",
                "message": "capacity unavailable",
            },
            "headers": {"RETRY-AFTER": "30"},
        })

        self.assertIsInstance(signal, ProviderRateLimit)
        assert signal is not None
        self.assertEqual(signal.status_code, 429)
        self.assertEqual(signal.retry_after_seconds, 30.0)
        self.assertEqual(signal.as_dict()["status_code"], 429)

    def test_incidental_number_or_non_429_status_is_not_rate_limit(self) -> None:
        fixtures = (
            "ordinary request 429 failed",
            {"type": "error", "message": "socket reset"},
            {"status_code": 503, "message": "HTTP 429 appeared in a log excerpt"},
            {"code": 500, "error": "rate_limit_exceeded fixture text"},
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.assertIsNone(detect_provider_rate_limit(fixture))


class ReviewResolverTests(unittest.TestCase):
    def test_path_escape_status_is_durable_and_does_not_cool_luna(self) -> None:
        know = SimpleNamespace(
            stats={"global": {"runs": 7}},
            progression={"review_report_only_streak": 0},
            save=mock.Mock(),
        )
        cfg = {
            "enabled": True,
            "runner": "codex",
            "model": "gpt-5.6-luna",
            "review_every_runs": 1,
            "preferred_timeout_min": 480,
            "stall_warn_min": 15,
            "stall_timeout_min": 30,
            "pre_work_timeout_min": 5,
        }
        sandbox = llm_review.SandboxReviewResult(
            rc=-1,
            error="Codex file_change 越出隔离 clone；整批拒合并保全",
            failure_code="runner_tool_path_escape",
            snapshot_complete=True,
            provider_work_started=True,
            provider_metrics={
                "model_work_started": True,
                "tool_access_failure_code": "runner_tool_path_escape",
                "tool_path_escape_count": 1,
            },
            replay_evidence_requested=True,
            replay_evidence_complete=False,
            replay_evidence_error="reported-path熔断后未完成退出校验",
            replay_evidence_model_started=True,
        )
        status: dict = {}
        closure_state = {
            "action_required": False,
            "consecutive_report_only": 0,
            "report_only_limit": 3,
            "state_source": "test",
        }
        with tempfile.TemporaryDirectory(prefix="sts2-path-status-") as root:
            repo_dir = Path(root)
            prompt_file = (
                repo_dir / "sts2-ascend" / "knowledge" / "review_prompt_latest.md")
            prompt_file.parent.mkdir(parents=True)
            with (mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
                  mock.patch.object(llm_review, "runner_binary", return_value="codex.CMD"),
                  mock.patch.object(llm_review, "REPO_DIR", repo_dir),
                  mock.patch.object(llm_review, "PROMPT_FILE", prompt_file),
                  mock.patch.object(llm_review, "_review_closure_state",
                                    return_value=closure_state),
                  mock.patch.object(llm_review, "build_prompt", return_value="prompt"),
                  mock.patch.object(llm_review, "build_review_command",
                                    return_value=["codex.CMD", "exec"]),
                  mock.patch.object(llm_review, "_run_review_sandbox",
                                    return_value=sandbox),
                  mock.patch.object(llm_review, "_save_review_salvage",
                                    return_value=None),
                  mock.patch.object(llm_review, "_review_stop_requested",
                                    return_value=False),
                  mock.patch.object(llm_review, "_stream_begin"),
                  mock.patch.object(llm_review, "_stream_end"),
                  mock.patch.object(llm_review, "_launch_viewer"),
                  mock.patch.object(llm_review, "_launch_speaker"),
                  mock.patch.object(llm_review, "_mark_preferred_failure") as mark,
                  mock.patch.object(autogit, "commit_progress_result"),
                  mock.patch.object(autogit, "head", return_value="a" * 40),
                  mock.patch.object(autogit, "set_review_active"),
                  mock.patch.object(autogit, "push_pending", return_value=True)):
                restart = llm_review.run_review(
                    know, log=lambda _message: None, runner="codex",
                    model="gpt-5.6-luna", backend_key="luna-max",
                    reasoning_effort="max", approve_for_me=False,
                    sandbox_mode="workspace-write", every=1,
                    source="preferred", batch_runs=[7], async_mode=True,
                    salvage_packages=["pkg-path-escape"],
                    _status=status)

        self.assertFalse(restart)
        self.assertEqual(status["failure_code"], "runner_tool_path_escape")
        self.assertEqual(status["retry_resolutions"], {})
        mark.assert_not_called()

    def test_production_chain_selects_kimi_before_probing_luna(self) -> None:
        cfg = json.loads((BRAIN / "config.json").read_text(
            encoding="utf-8"))["llm"]

        with (mock.patch.object(
                  llm_review, "_preferred_cooldown_remaining",
                  side_effect=lambda key: (
                      60.0 if key in {"glm-flash", "deepseek-v4-flash"}
                      else 0.0)),
              mock.patch.object(llm_review, "runner_binary",
                                side_effect=lambda _cfg, runner: runner + ".exe"),
              mock.patch.object(llm_review, "_query_codex_models") as codex_probe,
              mock.patch.object(llm_review, "_query_available_models",
                                return_value={
                                    "opencode-go/glm-5.3-flash",
                                    "amd-radeon/DeepSeek-V4-Flash",
                                    "kimi-for-coding/k3",
                                })):
            selected = llm_review.resolve_review_plan(cfg, log=lambda _message: None)

        self.assertEqual((selected.key, selected.runner), ("kimi-k3", "opencode"))
        codex_probe.assert_not_called()

    def test_production_chain_uses_luna_only_after_three_unavailable_entries(
            self) -> None:
        cfg = json.loads((BRAIN / "config.json").read_text(
            encoding="utf-8"))["llm"]

        with (mock.patch.object(llm_review, "_preferred_cooldown_remaining",
                                return_value=0.0),
              mock.patch.object(llm_review, "runner_binary",
                                side_effect=lambda _cfg, runner: runner + ".exe"),
              mock.patch.object(llm_review, "_query_available_models",
                                return_value=set()),
              mock.patch.object(llm_review, "_query_codex_models",
                                return_value={"gpt-5.6-luna": {"max"}})):
            selected = llm_review.resolve_review_plan(
                cfg, log=lambda _message: None)

        self.assertEqual(
            (selected.key, selected.runner, selected.source, selected.priority),
            ("luna-max", "codex", "fallback", 4),
        )

    def test_codex_probe_propagates_lifecycle_stop(self) -> None:
        llm_review._review_probe_cache.clear()
        with mock.patch.object(
                llm_review, "_run_captured_stop_aware",
                side_effect=llm_review._ReviewStopped()):
            with self.assertRaises(llm_review._ReviewStopped):
                llm_review._query_codex_models(
                    "codex.CMD", {"models_probe_cache_sec": 0},
                    log=lambda _message: None)

    def test_cooldown_survives_antivirus_write_failure_in_process(self) -> None:
        messages: list[str] = []
        with tempfile.TemporaryDirectory(prefix="sts2-cooldown-test-") as root:
            state = Path(root) / "preferred_model_state.json"
            with (mock.patch.object(llm_review, "PREFERRED_STATE_FILE", state),
                  mock.patch.object(llm_review, "_replace_with_retry",
                                    side_effect=PermissionError("scanner lock"))):
                llm_review._mark_preferred_failure(
                    {"preferred_failure_cooldown_min": 5}, messages.append,
                    "glm-flash", "startup failed")
                remaining = llm_review._preferred_cooldown_remaining("glm-flash")

        self.assertGreater(remaining, 250)
        self.assertTrue(any("本进程内冷却仍已生效" in message for message in messages))

    def test_malformed_cooldown_entries_are_repaired_on_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-cooldown-test-") as root:
            state = Path(root) / "preferred_model_state.json"
            state.write_text('{"entries": "corrupt"}\n', encoding="utf-8")
            with mock.patch.object(llm_review, "PREFERRED_STATE_FILE", state):
                self.assertEqual(llm_review._entry_state("glm-flash"), {})
                self.assertTrue(llm_review._write_entry_state(
                    "glm-flash", {"unavailable_until": 123}))

            repaired = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(
                repaired["entries"]["glm-flash"]["unavailable_until"], 123)

    def test_all_unavailable_keeps_queue_deferred_instead_of_dropping_work(self) -> None:
        cfg = {"review_model_chain": [
            {"key": "glm", "priority": 1, "runner": "opencode", "model": "glm"},
            {"key": "luna", "priority": 2, "runner": "codex", "model": "luna"},
            {"key": "kimi", "priority": 3, "runner": "opencode", "model": "kimi"},
        ]}
        with (mock.patch.object(llm_review, "_preferred_cooldown_remaining",
                                return_value=0.0),
              mock.patch.object(llm_review, "runner_binary", return_value=None)):
            selected = llm_review.resolve_review_plan(cfg, log=lambda _message: None)

        self.assertFalse(selected.available)
        self.assertEqual(selected.key, "kimi")

    def test_kimi_fallback_waits_for_its_configured_five_run_batch(self) -> None:
        plan = ReviewPlan(
            key="kimi", priority=3, runner="opencode", model="kimi",
            every_runs=5, source="fallback")
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)
        short_batch = [{"run": run} for run in range(1, 5)]
        full_batch = [{"run": run} for run in range(1, 6)]

        def complete(*_args, **kwargs):
            kwargs["_status"].update({"outcome": "completed", "reason": "ok"})
            return False

        with (mock.patch.object(llm_review, "load_llm_config",
                                return_value={"opencode_bin": "opencode"}),
              mock.patch.object(llm_review.shutil, "which", return_value="opencode"),
              mock.patch.object(llm_review, "resolve_review_plan", return_value=plan),
              mock.patch.object(llm_review, "runner_binary", return_value="opencode"),
              mock.patch.object(llm_review, "_persist_reviewing_batch_metadata"),
              mock.patch.object(llm_review, "run_review", side_effect=complete) as run):
            self.assertEqual(
                llm_review._run_batch_review(
                    agent, short_batch, log=lambda _message: None),
                "deferred",
            )
            run.assert_not_called()
            self.assertEqual(
                llm_review._run_batch_review(
                    agent, full_batch, log=lambda _message: None),
                "completed",
            )
            run.assert_called_once()

    def test_kimi_fallback_receives_all_twelve_backlogged_runs(self) -> None:
        plan = ReviewPlan(
            key="kimi", priority=3, runner="opencode", model="kimi",
            every_runs=5, source="fallback")
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)
        batch = [{"run": run} for run in range(1, 13)]

        def complete(*_args, **kwargs):
            kwargs["_status"].update({"outcome": "completed", "reason": "ok"})
            return False

        with (mock.patch.object(llm_review, "load_llm_config",
                                return_value={"opencode_bin": "opencode"}),
              mock.patch.object(llm_review, "resolve_review_plan", return_value=plan),
              mock.patch.object(llm_review, "runner_binary", return_value="opencode"),
              mock.patch.object(llm_review, "_persist_reviewing_batch_metadata"),
              mock.patch.object(llm_review, "run_review", side_effect=complete) as run):
            outcome = llm_review._run_batch_review(
                agent, batch, log=lambda _message: None)

        self.assertEqual(outcome, "completed")
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["every"], 5)
        self.assertEqual(run.call_args.kwargs["batch_runs"], list(range(1, 13)))

    def test_scheduler_selects_all_one_hundred_runs_at_packet_cap(self) -> None:
        pending = [{"run": run} for run in range(1, 101)]

        selected, wait = llm_review._select_review_batch(
            pending, cap=100, now=time.time())

        self.assertEqual(wait, 0.0)
        self.assertEqual(selected, list(range(100)))

    def test_kimi_can_retry_one_forensic_target_without_waiting_for_new_runs(self) -> None:
        plan = ReviewPlan(
            key="kimi", priority=3, runner="opencode", model="kimi",
            every_runs=5, source="fallback")
        batch = [{
            "run": 7, "replay_target": "pkg-one",
            "salvage_packages": ["pkg-one"], "queue_id": "retry-one",
        }]
        agent = SimpleNamespace(know=SimpleNamespace(), request_restart=False)

        def complete(*_args, **kwargs):
            kwargs["_status"].update({
                "outcome": "completed", "reason": "ok", "commit": "a" * 40,
                "retry_resolutions": {"pkg-one": "no_valid_change"},
                "unresolved_salvage_packages": [],
            })
            return False

        with (mock.patch.object(llm_review, "load_llm_config", return_value={}),
              mock.patch.object(llm_review, "resolve_review_plan", return_value=plan),
              mock.patch.object(llm_review, "runner_binary", return_value="opencode"),
              mock.patch.object(llm_review, "_persist_reviewing_batch_metadata"),
              mock.patch.object(llm_review, "run_review", side_effect=complete) as run):
            outcome = llm_review._run_batch_review(
                agent, batch, log=lambda _message: None)

        self.assertEqual(outcome, "completed")
        run.assert_called_once()


class StreamAndProbeSafetyTests(unittest.TestCase):
    def _stream_path(self, root: str) -> Path:
        return Path(root) / "review_live.stream"

    def test_translator_exception_terminates_provider_process_tree(self) -> None:
        command = [
            sys.executable, "-u", "-c",
            "import time; print('{}', flush=True); time.sleep(60)",
        ]
        terminate = llm_review._terminate_process_tree
        with tempfile.TemporaryDirectory(prefix="sts2-stream-test-") as root:
            with (mock.patch.object(llm_review, "LIVE_STREAM", self._stream_path(root)),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
                  mock.patch.object(llm_review, "_terminate_process_tree",
                                    wraps=terminate) as kill):
                with self.assertRaisesRegex(ValueError, "malformed event"):
                    llm_review._stream_run(
                        command, 10,
                        translate=lambda _line: (_ for _ in ()).throw(
                            ValueError("malformed event")))

        self.assertTrue(kill.called)
        process = kill.call_args_list[0].args[0]
        self.assertIsNotNone(process.poll())

    def test_stream_binds_clone_root_and_terminates_on_file_change_escape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-stream-path-escape-") as root:
            clone = Path(root) / "repo"
            clone.mkdir()
            outside_policy = Path(root) / "live-repo" / "policy.py"
            outside_selfcheck = Path(root) / "live-repo" / "selfcheck.py"
            event = json.dumps({
                "type": "item.started",
                "item": {
                    "type": "file_change",
                    "status": "in_progress",
                    "changes": [
                        {"path": str(outside_policy)},
                        {"path": str(clone / "knowledge" / "review_conclusion.txt")},
                        {"path": str(outside_selfcheck)},
                    ],
                },
            })
            false_success = json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "SELFCHECK OK"},
            })
            command = [
                sys.executable, "-u", "-c",
                (f"import time; print({event!r}, flush=True); "
                 f"print({false_success!r}, flush=True); time.sleep(60)"),
            ]
            translator = CodexJsonTranslator()
            terminate = llm_review._terminate_process_tree
            with (mock.patch.object(llm_review, "LIVE_STREAM", self._stream_path(root)),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
                  mock.patch.object(llm_review, "_terminate_process_tree",
                                    wraps=terminate) as kill,
                  self.assertRaisesRegex(
                      RunnerToolPathEscape, "escaped expected clone root")):
                llm_review._stream_run(
                    command, 10, translate=translator.feed, cwd=clone,
                    expected_clone_root=clone)

        self.assertTrue(kill.called)
        self.assertIsNotNone(kill.call_args_list[0].args[0].poll())
        self.assertEqual(
            translator.metrics()["tool_access_failure_code"],
            "runner_tool_path_escape")
        self.assertEqual(translator.final_message, "")

    def test_sandbox_path_escape_is_rejected_before_host_selfcheck(self) -> None:
        pre_head = subprocess.run(
            ["git", "-C", str(ASCEND.parent), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True).stdout.strip()
        translator = CodexJsonTranslator()

        def emit_escape(_cmd, _timeout, translate=None, **kwargs):
            clone = Path(kwargs["expected_clone_root"])
            translator.bind_expected_clone_root(clone)
            event = {
                "type": "item.started",
                "item": {
                    "type": "file_change",
                    "status": "in_progress",
                    "changes": [
                        {"path": str(ASCEND / "brain" / "policy.py")},
                        {"path": str(clone / "knowledge" / "review_conclusion.txt")},
                        {"path": str(ASCEND / "brain" / "selfcheck.py")},
                    ],
                },
            }
            translate(json.dumps(event))
            self.fail("path escape must terminate before the stream returns")

        command = [
            "codex.CMD", "-a", "never", "exec",
            "-c", (
                'permissions.luna_commit={extends=":workspace",'
                'filesystem={":workspace_roots"={".git"="write"}},'
                'network={enabled=false}}'),
            "-c", 'default_permissions="luna_commit"',
            "--ignore-user-config", "-C", str(ASCEND.parent), "prompt",
        ]
        with (mock.patch.object(
                  llm_review, "_normalize_windows_review_sandbox_acl"),
              mock.patch.object(
                  llm_review, "_codex_windows_filesystem_preflight",
                  return_value=""),
              mock.patch.object(
                  llm_review, "_mount_failed_review_evidence",
                  return_value={"packages": ["pkg-path-escape"]}) as mount,
              mock.patch.object(
                  llm_review, "_verify_failed_review_evidence") as verify,
              mock.patch.object(
                  llm_review, "_remove_failed_review_evidence") as remove,
              mock.patch.object(llm_review, "_stream_run", side_effect=emit_escape),
              mock.patch.object(llm_review, "_run_selfcheck") as selfcheck):
            result = llm_review._run_review_sandbox(
                command, "prompt", pre_head, 60, translator, runner="codex",
                replay_packages=["pkg-path-escape"],
                log=lambda _message: None)

        try:
            selfcheck.assert_not_called()
            self.assertEqual(result.failure_code, "runner_tool_path_escape")
            self.assertIn("整批拒合并保全", result.error)
            self.assertTrue(result.provider_work_started)
            self.assertEqual(
                result.provider_metrics["tool_access_failure_code"],
                "runner_tool_path_escape")
            self.assertTrue(result.replay_evidence_requested)
            self.assertFalse(result.replay_evidence_complete)
            self.assertEqual(
                result.replay_evidence_error,
                "reported-path熔断后未完成退出校验")
            mount.assert_called_once()
            verify.assert_not_called()
            remove.assert_not_called()
            self.assertTrue(result.retained_sandbox_dir)
        finally:
            llm_review._discard_sandbox_snapshot(result, log=lambda _message: None)
            llm_review._discard_retained_sandbox(result, log=lambda _message: None)

    def test_live_stream_open_failure_terminates_provider_process_tree(self) -> None:
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        terminate = llm_review._terminate_process_tree
        with tempfile.TemporaryDirectory(prefix="sts2-stream-test-") as root:
            # Opening a directory as an append-only file is guaranteed to fail.
            with (mock.patch.object(llm_review, "LIVE_STREAM", Path(root)),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
                  mock.patch.object(llm_review, "_terminate_process_tree",
                                    wraps=terminate) as kill,
                  self.assertRaises(OSError)):
                llm_review._stream_run(command, 10)

        self.assertTrue(kill.called)
        self.assertIsNotNone(kill.call_args_list[0].args[0].poll())

    def test_final_raw_silence_is_included_in_gap_metric(self) -> None:
        command = [
            sys.executable, "-u", "-c",
            "import time; print('event', flush=True); time.sleep(0.08)",
        ]
        metrics: dict = {}
        with tempfile.TemporaryDirectory(prefix="sts2-stream-test-") as root:
            with (mock.patch.object(llm_review, "LIVE_STREAM", self._stream_path(root)),
                  mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
                rc, *_rest = llm_review._stream_run(
                    command, 10, metrics_sink=metrics)

        self.assertEqual(rc, 0)
        self.assertGreaterEqual(metrics["raw_chunk_count"], 1)
        self.assertGreaterEqual(metrics["max_raw_output_gap_sec"], 0.04)

    def test_provider_process_uses_explicit_isolated_working_directory(self) -> None:
        command = [
            sys.executable, "-u", "-c",
            "import os; print(os.getcwd(), flush=True)",
        ]
        with tempfile.TemporaryDirectory(prefix="sts2-provider-cwd-test-") as root:
            provider_cwd = Path(root) / "isolated-repo"
            provider_cwd.mkdir()
            with mock.patch.object(
                    llm_review, "LIVE_STREAM", self._stream_path(root)):
                rc, tail, timed_out, stopped, stalled = llm_review._stream_run(
                    command, 10, cwd=provider_cwd)

        self.assertEqual(rc, 0)
        self.assertFalse(timed_out or stopped or stalled)
        self.assertIn(str(provider_cwd.resolve()), tail)

    def test_probe_timeout_terminates_spawned_process_tree(self) -> None:
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        terminate = llm_review._terminate_process_tree
        with (mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
              mock.patch.object(llm_review, "_terminate_process_tree",
                                wraps=terminate) as kill,
              self.assertRaises(subprocess.TimeoutExpired)):
            llm_review._run_captured_stop_aware(command, timeout=0.1)

        self.assertTrue(kill.called)
        self.assertIsNotNone(kill.call_args_list[0].args[0].poll())


class LifecycleScriptTests(unittest.TestCase):
    def test_cold_start_prepares_pinned_codex_before_deploy_or_runner(self) -> None:
        text = (ASCEND / "scripts" / "Start-Agent.ps1").read_text(encoding="utf-8")

        install = text.index('Join-Path $PSScriptRoot "Install-CodexCompat.ps1"')
        deploy = text.index('Join-Path $PSScriptRoot "Deploy-Mod.ps1"')
        runner = text.index("Start-Process -FilePath $pythonExe")
        self.assertLess(install, deploy)
        self.assertLess(install, runner)
        self.assertIn("Luna will remain unavailable", text)
        self.assertIn("without starting a provider", text)

    def test_start_and_stop_match_only_production_codex_review_shape(self) -> None:
        for name in ("Start-Agent.ps1", "Stop-Agent.ps1"):
            text = (ASCEND / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("Test-IsCodexReviewProcess", text)
            self.assertIn("sts2-review-sandbox-", text)
            self.assertIn("--ephemeral", text)
            self.assertIn("(?:-C|--cd)", text)
            self.assertNotIn("gpt-5\\.6-luna", text)

    def test_brain_orphan_cleanup_regex_matches_windows_sandbox_repo(self) -> None:
        with mock.patch.object(llm_review, "_run_captured_stop_aware") as run:
            llm_review._kill_orphan_review_processes(log=lambda _message: None)

        command = run.call_args.args[0][3]
        self.assertIn("(?:-C|--cd)", command)
        self.assertIn("taskkill.exe", command)
        self.assertIn("/T /F", command)
        match = re.search(
            r"\[regex\]::Escape\(\$reviewRoot\)\+\'([^']+)\'", command)
        self.assertIsNotNone(match)
        assert match is not None
        suffix = match.group(1)
        self.assertIn(r"[\\/]", suffix)
        review_root = r"D:\workspace\sts2-ascend\knowledge\code_backups\review_work"
        pattern = (r'(?i)(?:^|\s)(?:-C|--cd)\s+"?' +
                   re.escape(review_root) + suffix)
        managed = (
            'codex exec --json --ephemeral -C "' + review_root +
            r'\sts2-review-sandbox-abc123\repo" prompt')
        unrelated = (
            'codex exec --json --ephemeral prompt "' + review_root +
            r'\sts2-review-sandbox-abc123\repo"')
        self.assertIsNotNone(re.search(pattern, managed))
        self.assertIsNone(re.search(pattern, unrelated))


    def test_opencode_matcher_accepts_only_managed_review_clone(self) -> None:
        for name in ("Start-Agent.ps1", "Stop-Agent.ps1"):
            text = (ASCEND / "scripts" / name).read_text(encoding="utf-8")
            match = re.search(
                r"(?ms)^function Test-IsOpenCodeReviewProcess \{.*?^\}", text)
            self.assertIsNotNone(match, name)
            assert match is not None
            script = match.group(0) + r'''
$root = 'C:\work\sts2-ascend'
$managed = [pscustomobject]@{
    Name = 'opencode.exe'
    CommandLine = 'opencode run --model glm --format json --dir "C:\work\sts2-ascend\knowledge\code_backups\review_work\sts2-review-sandbox-abc\repo" --auto prompt'
}
$realRepo = [pscustomobject]@{
    Name = 'opencode.exe'
    CommandLine = 'opencode run --format json --dir "C:\work\sts2-ascend" --auto prompt'
}
$pathOnlyInPrompt = [pscustomobject]@{
    Name = 'opencode.exe'
    CommandLine = 'opencode run --format json --dir "C:\work\other" --auto C:\work\sts2-ascend\knowledge\code_backups\review_work\sts2-review-sandbox-abc\repo'
}
if (-not (Test-IsOpenCodeReviewProcess $managed $root)) { exit 11 }
if (Test-IsOpenCodeReviewProcess $realRepo $root) { exit 12 }
if (Test-IsOpenCodeReviewProcess $pathOnlyInPrompt $root) { exit 13 }
'''
            with tempfile.TemporaryDirectory(prefix="sts2-opencode-matcher-") as root:
                check = Path(root) / "check.ps1"
                check.write_text(script, encoding="utf-8-sig")
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-File", str(check)],
                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)



if __name__ == "__main__":
    unittest.main()
