"""Regression coverage for binding Brain to the configured native save profile."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402


class NativeProfileSelectionTests(unittest.TestCase):
    @staticmethod
    def _agent(target: int = 1) -> agent_module.Agent:
        instance = object.__new__(agent_module.Agent)
        instance.cfg = {"native_profile_id": target}
        instance.ctx = agent_module.RunContext()
        return instance

    @staticmethod
    def _menu(profile_id: int, *, actions=None) -> dict:
        return {
            "state_version": 14,
            "native_profile_id": profile_id,
            "screen": "MAIN_MENU",
            "run_id": "run_unknown",
            "run": None,
            "available_actions": actions or [
                "switch_profile", "continue_run", "abandon_run"],
        }

    def test_mismatch_switches_before_continue(self) -> None:
        decision = self._agent()._native_profile_guard_decision(self._menu(2))

        self.assertIsNotNone(decision)
        self.assertEqual(decision.action, "switch_profile")
        self.assertEqual(decision.params, {"option_index": 1})

    def test_matching_profile_leaves_normal_policy_path_untouched(self) -> None:
        self.assertIsNone(
            self._agent()._native_profile_guard_decision(self._menu(1)))

    def test_mismatch_outside_safe_menu_remains_fail_closed(self) -> None:
        state = self._menu(2)
        state.update({
            "screen": "CHEST",
            "run_id": "foreign-run",
            "run": {"run_id": "foreign-run"},
            "available_actions": ["open_chest"],
        })

        decision = self._agent()._native_profile_guard_decision(state)

        self.assertIsNotNone(decision)
        self.assertIsNone(decision.action)
        self.assertIn("profile2", decision.reason)

    def test_response_lost_switch_requires_exact_profile_postcondition(self) -> None:
        instance = self._agent()
        decision = agent_module.Decision(
            "switch_profile", {"option_index": 1}, "test")
        before = self._menu(2)
        after = self._menu(1)

        self.assertEqual(
            instance._ambiguous_action_outcome(before, after, decision),
            "applied")
        self.assertEqual(
            instance._ambiguous_action_outcome(before, before, decision),
            "unproven")


if __name__ == "__main__":
    unittest.main()
