"""Fail-closed native GAME_OVER save barrier contracts."""
from __future__ import annotations

import copy
from pathlib import Path
import re
from types import SimpleNamespace
import sys
import time
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
ASCEND = BRAIN.parent
GAME_STATE_SERVICE = (
    ASCEND / "third_party" / "STS2-Agent" / "STS2AIAgent" / "Game"
    / "GameStateService.cs")
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402
from policy import Decision  # noqa: E402


def _summary_state(run_id: str = "native-save-run") -> dict:
    return {
        "native_profile_id": 1,
        "screen": "GAME_OVER",
        "run_id": run_id,
        "run": {"run_id": run_id, "floor": 17},
        "available_actions": ["return_to_main_menu"],
        "game_over": {
            "phase": "summary_ready",
            "is_victory": False,
            "floor": 17,
            "can_return_to_main_menu": True,
            "save_status": "verified",
            "save_verified": True,
            "save_error": None,
        },
    }


def _pre_summary_state(phase: str,
                       run_id: str = "native-save-run") -> dict:
    state = _summary_state(run_id)
    state["available_actions"] = (
        ["continue_game_over"] if phase == "intro" else [])
    state["game_over"].update({
        "phase": phase,
        "can_continue": phase == "intro",
        "can_return_to_main_menu": False,
        "showing_summary": False,
        "save_status": "pending",
        "save_verified": False,
        "save_error": None,
    })
    return state


def _bare_agent(*, human_assisted: bool = False) -> agent_module.Agent:
    instance = object.__new__(agent_module.Agent)
    instance.ctx = SimpleNamespace(
        run_id="native-save-run",
        human_assisted=human_assisted,
        finalize_requested=True,
        run_finalized=False,
        decisions=[{"floor": 17}],
    )
    instance._dashboard_connection = mock.Mock()
    return instance


class NativeGameOverSaveVerdictTests(unittest.TestCase):
    def test_only_exact_verified_pair_is_proof(self) -> None:
        instance = _bare_agent()
        with mock.patch.object(agent_module, "log") as logger:
            first = instance._native_game_over_save_barrier(_summary_state())
            second = instance._native_game_over_save_barrier(_summary_state())

        self.assertEqual(first, ("verified", "native_progress_save_verified"))
        self.assertEqual(second, first)
        logger.assert_not_called()
        instance._dashboard_connection.assert_not_called()

    def test_coherent_pending_only_waits_without_reporting_an_error(self) -> None:
        instance = _bare_agent()
        state = _summary_state()
        state["game_over"].update({
            "save_status": "pending",
            "save_verified": False,
            "save_error": None,
        })
        with mock.patch.object(agent_module, "log") as logger:
            verdict = instance._native_game_over_save_barrier(state)

        self.assertEqual(verdict, ("pending", "native_progress_save_pending"))
        logger.assert_not_called()
        instance._dashboard_connection.assert_not_called()

    def test_csharp_v13_emits_exact_game_over_phase_set(self) -> None:
        source = GAME_STATE_SERVICE.read_text(encoding="utf-8")
        phase_assignment = re.search(
            r'var phase = canReturnToMainMenu\s*'
            r'\?\s*"([^"]+)"\s*'
            r':\s*canContinue\s*'
            r'\?\s*"([^"]+)"\s*'
            r':\s*"([^"]+)"\s*;',
            source,
        )
        self.assertIsNotNone(phase_assignment)
        self.assertEqual(
            phase_assignment.groups(),
            ("summary_ready", "intro", "summary_animating"))

    def test_real_pre_summary_phases_wait_and_unknown_phases_fail_closed(
            self) -> None:
        for phase in ("intro", "summary_animating"):
            with self.subTest(phase=phase):
                state = _pre_summary_state(phase)
                self.assertEqual(
                    agent_module.Agent._native_game_over_save_verdict(state),
                    ("pending", f"phase={phase}"))

        for phase in ("continue_available", "future_unknown_phase"):
            with self.subTest(phase=phase):
                state = _pre_summary_state(phase)
                verdict, reason = (
                    agent_module.Agent._native_game_over_save_verdict(state))
                self.assertEqual(verdict, "blocked")
                self.assertEqual(reason, f"unexpected_phase={phase}")

    def test_errors_missing_fields_wrong_types_and_contradictions_fail_closed(
            self) -> None:
        cases: list[tuple[str, dict]] = []

        error = _summary_state()
        error["game_over"].update({
            "save_status": "error", "save_verified": False,
            "save_error": "progress_mismatch"})
        cases.append(("native-error", error))

        for key in ("phase", "save_status", "save_verified", "save_error"):
            state = _summary_state()
            state["game_over"].pop(key)
            cases.append((f"missing-{key}", state))

        mutations = (
            ("verified-false", {"save_status": "verified", "save_verified": False}),
            ("pending-true", {"save_status": "pending", "save_verified": True}),
            ("error-true", {
                "save_status": "error", "save_verified": True,
                "save_error": "progress_mismatch"}),
            ("verified-with-error", {
                "save_status": "verified", "save_verified": True,
                "save_error": "stale_error"}),
            ("status-not-string", {"save_status": 1}),
            ("verified-not-bool", {"save_verified": 1}),
            ("error-not-string", {"save_error": {"code": "bad"}}),
        )
        for label, update in mutations:
            state = _summary_state()
            state["game_over"].update(update)
            cases.append((label, state))

        for label, state in cases:
            with self.subTest(label=label):
                instance = _bare_agent()
                with mock.patch.object(agent_module, "log") as logger:
                    verdict, _reason = instance._native_game_over_save_barrier(state)
                self.assertEqual(verdict, "blocked")
                logger.assert_called_once()
                instance._dashboard_connection.assert_called_once()

    def test_repeated_error_poll_for_same_run_is_observable_but_deduplicated(
            self) -> None:
        instance = _bare_agent()
        state = _summary_state()
        state["game_over"].update({
            "save_status": "error", "save_verified": False,
            "save_error": "progress_mismatch"})
        with mock.patch.object(agent_module, "log") as logger:
            for _ in range(4):
                self.assertEqual(
                    instance._native_game_over_save_barrier(state)[0], "blocked")
            next_run = copy.deepcopy(state)
            next_run["run_id"] = "native-save-run-2"
            instance._native_game_over_save_barrier(next_run)

        self.assertEqual(logger.call_count, 2)
        self.assertEqual(instance._dashboard_connection.call_count, 2)

    def test_return_to_main_menu_is_blocked_until_verified(self) -> None:
        for label, update in (
                ("pending", {
                    "save_status": "pending", "save_verified": False,
                    "save_error": None}),
                ("error", {
                    "save_status": "error", "save_verified": False,
                    "save_error": "write_failed"}),
                ("missing", {"save_status": None}),
                ("contradictory", {
                    "save_status": "verified", "save_verified": False})):
            with self.subTest(label=label):
                instance = _bare_agent()
                state = _summary_state()
                state["game_over"].update(update)
                decision = Decision("return_to_main_menu", {}, "leave")
                with mock.patch.object(agent_module, "log"):
                    gated = instance._apply_native_game_over_return_barrier(
                        state, decision)
                self.assertIsNone(gated.action)

        instance = _bare_agent()
        decision = Decision("return_to_main_menu", {}, "leave")
        self.assertIs(
            instance._apply_native_game_over_return_barrier(
                _summary_state(), decision),
            decision)

    def test_human_assisted_run_cannot_bypass_native_save_barrier(self) -> None:
        instance = _bare_agent(human_assisted=True)
        state = _summary_state()
        state["game_over"].update({
            "save_status": "error", "save_verified": False,
            "save_error": "progress_missing"})
        decision = Decision("return_to_main_menu", {}, "human audit close")
        with mock.patch.object(agent_module, "log"):
            self.assertEqual(
                instance._native_game_over_save_barrier(state)[0], "blocked")
            self.assertIsNone(
                instance._apply_native_game_over_return_barrier(
                    state, decision).action)


class NativeGameOverSaveRunLoopTests(unittest.TestCase):
    @staticmethod
    def _run_one_terminal_poll(state: dict, *, human_assisted: bool = False
                               ) -> agent_module.Agent:
        instance = _bare_agent(human_assisted=human_assisted)
        instance.cfg = {
            "max_runs": 0,
            "native_profile_id": 1,
            "poll_interval": 0.01,
            "action_settle": 0.01,
        }
        instance.runs_played = 0
        instance.client = SimpleNamespace(
            health=mock.Mock(return_value={
                "mod_version": "test", "game_version": "test"}),
            state=mock.Mock(return_value=state),
            act=mock.Mock(),
        )
        instance.know = SimpleNamespace(
            stats={"global": {"wins": 0, "runs": 0}},
            progression={"current_ascension": 0},
            refresh_policy=mock.Mock(return_value=[]),
        )
        instance.rotation = SimpleNamespace(record_terminal=mock.Mock())
        instance.policy = SimpleNamespace(decide=mock.Mock())
        instance._last_policy_refresh = time.time()
        for name in (
                "_start_live_dashboard", "_capture_boot_head",
                "_launch_quipper", "_dashboard_connection",
                "_bind_profile_for_state", "_dashboard_observe", "_track"):
            setattr(instance, name, mock.Mock())
        instance.ensure_game = mock.Mock(return_value=True)
        instance._manual_control_blocks = mock.Mock(return_value=False)
        instance._reconcile_ambiguous_action = mock.Mock(return_value=None)
        instance._finalize = mock.Mock()

        with (mock.patch.object(agent_module, "stop_requested",
                                side_effect=[False, True]),
              mock.patch.object(agent_module, "wait_for_stop", return_value=False),
              mock.patch.object(agent_module, "mark_pid_stage", return_value=True),
              mock.patch.object(agent_module, "llm_review", None),
              mock.patch.object(agent_module, "log")):
            instance.run()
        return instance

    def test_pending_error_missing_and_contradictory_never_reach_finalizer(self) -> None:
        cases = (
            ("pending", {
                "save_status": "pending", "save_verified": False,
                "save_error": None}),
            ("error", {
                "save_status": "error", "save_verified": False,
                "save_error": "disk_mismatch"}),
            ("missing", {"save_status": None}),
            ("contradictory", {
                "save_status": "verified", "save_verified": False}),
        )
        for label, update in cases:
            with self.subTest(label=label):
                state = _summary_state()
                state["game_over"].update(update)
                instance = self._run_one_terminal_poll(state)
                instance._finalize.assert_not_called()
                instance.rotation.record_terminal.assert_not_called()
                instance.client.act.assert_not_called()
                self.assertEqual(instance.know.stats["global"]["runs"], 0)

    def test_verified_reaches_existing_idempotent_finalizer_once(self) -> None:
        state = _summary_state()
        instance = self._run_one_terminal_poll(state)
        instance._finalize.assert_called_once()
        call = instance._finalize.call_args
        self.assertEqual(call.args[:2], (False, 17))
        # The concurrent profile-card-stats change supplies the terminal RunState
        # as ``final_run``; the HEAD baseline has the original two-argument API.
        if "final_run" in call.kwargs:
            self.assertIs(call.kwargs["final_run"], state["run"])
        self.assertIs(call.kwargs["native_save_state"], state)
        instance.client.act.assert_not_called()

    def test_human_assisted_terminal_is_still_blocked_before_exclusion_finalize(
            self) -> None:
        state = _summary_state()
        state["game_over"].update({
            "save_status": "error", "save_verified": False,
            "save_error": "profile_save_missing"})
        instance = self._run_one_terminal_poll(
            state, human_assisted=True)
        instance._finalize.assert_not_called()
        instance.rotation.record_terminal.assert_not_called()
        instance.client.act.assert_not_called()


if __name__ == "__main__":
    unittest.main()
