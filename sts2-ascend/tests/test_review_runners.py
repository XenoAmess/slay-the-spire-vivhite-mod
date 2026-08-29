"""Runner-adapter regressions for the GLM -> Luna -> Kimi review chain."""
from __future__ import annotations

import json
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
from review_runners import (  # noqa: E402
    CodexJsonTranslator,
    ReviewPlan,
    bind_review_workdir,
    build_review_command,
    review_plans_from_config,
)


class ReviewPlanTests(unittest.TestCase):
    def test_production_luna_uses_explicit_non_auto_approval(self) -> None:
        cfg = json.loads((BRAIN / "config.json").read_text(encoding="utf-8"))

        luna = next(
            plan for plan in review_plans_from_config(cfg["llm"])
            if plan.key == "luna-max")

        self.assertFalse(luna.approve_for_me)
        self.assertEqual(luna.sandbox, "workspace-write")

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



    def test_codex_command_is_noninteractive_ephemeral_and_bound_to_clone(self) -> None:
        plan = ReviewPlan(
            key="luna", priority=2, runner="codex", model="gpt-5.6-luna",
            reasoning_effort="max", approve_for_me=True,
            sandbox="workspace-write", every_runs=1, source="preferred")

        command = build_review_command(
            plan, "codex.CMD", Path("C:/review/repo"), "read prompt", title="ignored")

        self.assertEqual(command[:4], ["codex.CMD", "exec", "--model", "gpt-5.6-luna"])
        self.assertIn('model_reasoning_effort="max"', command)
        for option in ("--approve-for-me", "--json", "--ephemeral"):
            self.assertIn(option, command)
        self.assertNotIn("--sandbox", command)
        self.assertEqual(command[command.index("-C") + 1], "C:\\review\\repo")
        self.assertEqual(command[-1], "read prompt")

        rebound = bind_review_workdir(command, "codex", Path("D:/isolated/repo"))
        self.assertEqual(rebound[rebound.index("-C") + 1], "D:\\isolated\\repo")

    def test_codex_command_uses_explicit_sandbox_without_auto_review(self) -> None:
        plan = ReviewPlan(
            key="luna", priority=2, runner="codex", model="gpt-5.6-luna",
            sandbox="workspace-write", approve_for_me=False,
            every_runs=1, source="preferred")

        command = build_review_command(
            plan, "codex.CMD", Path("C:/review/repo"), "read prompt", title="ignored")

        self.assertEqual(command[:4], ["codex.CMD", "-a", "never", "exec"])
        self.assertNotIn("--approve-for-me", command)
        self.assertEqual(
            command[command.index("--sandbox") + 1], "workspace-write")


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
    def test_jsonl_translation_records_work_usage_and_tool_metrics(self) -> None:
        translator = CodexJsonTranslator()
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


class OpencodeTranslatorTests(unittest.TestCase):
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


class ReviewResolverTests(unittest.TestCase):
    def test_glm_cooldown_selects_luna_before_kimi(self) -> None:
        cfg = {
            "review_model_chain": [
                {"key": "glm", "priority": 1, "runner": "opencode",
                 "model": "glm", "variant": "max"},
                {"key": "luna", "priority": 2, "runner": "codex",
                 "model": "gpt-5.6-luna", "reasoning_effort": "max"},
                {"key": "kimi", "priority": 3, "runner": "opencode",
                 "model": "kimi", "every_runs": 5},
            ],
        }

        with (mock.patch.object(
                  llm_review, "_preferred_cooldown_remaining",
                  side_effect=lambda key: 60.0 if key == "glm" else 0.0),
              mock.patch.object(llm_review, "runner_binary",
                                side_effect=lambda _cfg, runner: runner + ".exe"),
              mock.patch.object(llm_review, "_query_codex_models",
                                return_value={"gpt-5.6-luna": {"max"}}),
              mock.patch.object(llm_review, "_query_available_models",
                                return_value={"glm", "kimi"})):
            selected = llm_review.resolve_review_plan(cfg, log=lambda _message: None)

        self.assertEqual((selected.key, selected.runner), ("luna", "codex"))

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
