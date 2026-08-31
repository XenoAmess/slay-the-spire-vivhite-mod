"""GAME_OVER, summary, and UNLOCK ordering contracts for the shared Brain."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
ASCEND = BRAIN.parent
MCP_ROOT = ASCEND / "third_party" / "STS2-Agent" / "mcp_server"
sys.path.insert(0, str(BRAIN))

from policy import Decision, Policy  # noqa: E402


class GameOverUnlockFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = Policy(SimpleNamespace(policy={}))
        self.ctx = SimpleNamespace(
            run_id="run-game-over-1",
            decisions=[{"floor": 17}],
            run_finalized=False,
            finalize_requested=False,
        )

    @staticmethod
    def _game_over(*, actions: list[str], can_continue: bool,
                   can_return: bool, showing_summary: bool) -> dict:
        return {
            "screen": "GAME_OVER",
            "run_id": "run-game-over-1",
            "available_actions": actions,
            "game_over": {
                "is_victory": False,
                "floor": 17,
                "can_continue": can_continue,
                "can_return_to_main_menu": can_return,
                "showing_summary": showing_summary,
            },
        }

    def test_first_game_over_ui_action_is_dedicated_continue(self) -> None:
        state = self._game_over(
            actions=["continue_game_over", "continue_run", "proceed"],
            can_continue=True,
            can_return=False,
            showing_summary=False,
        )
        decision = self.policy._game_over(state, self.ctx)
        self.assertEqual(decision.action, "continue_game_over")
        self.assertNotIn(decision.action, {"continue_run", "proceed"})
        self.assertFalse(self.ctx.finalize_requested)

    def test_summary_waits_until_native_return_button_is_really_available(self) -> None:
        hidden = self.policy._game_over(
            self._game_over(
                actions=[],
                can_continue=False,
                can_return=False,
                showing_summary=True,
            ),
            self.ctx,
        )
        disabled = self.policy._game_over(
            self._game_over(
                actions=[],
                can_continue=False,
                can_return=False,
                showing_summary=True,
            ),
            self.ctx,
        )
        ready_before_persistence = self.policy._game_over(
            self._game_over(
                actions=["return_to_main_menu"],
                can_continue=False,
                can_return=True,
                showing_summary=True,
            ),
            self.ctx,
        )

        self.assertIsNone(hidden.action)
        self.assertIsNone(disabled.action)
        self.assertIsNone(ready_before_persistence.action)
        self.assertTrue(self.ctx.finalize_requested)

        self.ctx.run_finalized = True
        ready_after_persistence = self.policy._game_over(
            self._game_over(
                actions=["return_to_main_menu"],
                can_continue=False,
                can_return=True,
                showing_summary=True,
            ),
            self.ctx,
        )
        self.assertEqual(ready_after_persistence.action, "return_to_main_menu")

    def test_unlock_screens_are_confirmed_one_by_one_before_next_run(self) -> None:
        pending_unlock = {
            "screen": "UNLOCK",
            "available_actions": ["open_character_select"],
            "unlock": {
                "unlock_type": "NUnlockRelicsScreen",
                "items": ["Relic A"],
                "can_confirm": False,
            },
        }
        first_unlock = {
            "screen": "UNLOCK",
            "available_actions": ["confirm_unlock"],
            "unlock": {
                "unlock_type": "NUnlockRelicsScreen",
                "items": ["Relic A"],
                "can_confirm": True,
            },
        }
        second_unlock = {
            "screen": "UNLOCK",
            "available_actions": ["confirm_unlock"],
            "unlock": {
                "unlock_type": "NUnlockCardsScreen",
                "items": ["Card B"],
                "can_confirm": True,
            },
        }

        pending = self.policy._unlock_screen(pending_unlock, self.ctx)
        first = self.policy._unlock_screen(first_unlock, self.ctx)
        second = self.policy._unlock_screen(second_unlock, self.ctx)
        self.assertIsNone(pending.action)
        self.assertEqual(first.action, "confirm_unlock")
        self.assertEqual(second.action, "confirm_unlock")

        waiting_summary = self.policy._game_over(
            self._game_over(
                actions=[],
                can_continue=False,
                can_return=False,
                showing_summary=True,
            ),
            self.ctx,
        )
        self.assertIsNone(waiting_summary.action)

    def test_misreported_card_selection_unlock_prefers_confirm_unlock(self) -> None:
        selection_calls: list[dict] = []
        self.policy._card_selection = lambda state, _ctx: (
            selection_calls.append(state)
            or Decision("select_deck_card", {"option_index": 0}, "wrong route")
        )
        state = {
            "screen": "CARD_SELECTION",
            "available_actions": ["confirm_unlock", "select_deck_card"],
            "unlock": {
                "unlock_type": "NUnlockCardsScreen",
                "items": [],
                "can_confirm": True,
            },
        }

        decision = self.policy.decide(state, self.ctx)

        self.assertEqual(decision.action, "confirm_unlock")
        self.assertNotEqual(decision.action, "select_deck_card")
        self.assertEqual(selection_calls, [])

    def test_unlock_wait_never_uses_mouse_fallback_and_recovers_via_api(self) -> None:
        stuck_unlock = {
            "screen": "UNLOCK",
            "available_actions": [],
            "unlock": {
                "unlock_type": "NUnlockRelicsScreen",
                "items": ["Relic A"],
                "can_confirm": False,
            },
        }
        clicks: list[tuple[float, float]] = []
        self.policy._click_game_point = (
            lambda x, y: clicks.append((x, y)) or True)

        waits = [
            self.policy._unlock_screen(stuck_unlock, self.ctx)
            for _ in range(24)
        ]

        self.assertTrue(all(decision.action is None for decision in waits))
        self.assertEqual(clicks, [])
        self.assertTrue(all(
            "等待 confirm_unlock 就绪" in decision.reason
            for decision in waits
        ))

        ready_unlock = {
            **stuck_unlock,
            "available_actions": ["confirm_unlock"],
            "unlock": {
                **stuck_unlock["unlock"],
                "can_confirm": True,
            },
        }
        recovered = self.policy._unlock_screen(ready_unlock, self.ctx)

        self.assertEqual(recovered.action, "confirm_unlock")
        self.assertEqual(self.policy._unlock_stall, 0)
        self.assertEqual(clicks, [])

    def test_legacy_game_over_actions_never_bypass_native_settlement(self) -> None:
        state = self._game_over(
            actions=["continue_run", "proceed", "return_to_main_menu"],
            can_continue=True,
            can_return=False,
            showing_summary=False,
        )
        decision = self.policy._game_over(state, self.ctx)
        self.assertIsNone(decision.action)

    def test_broken_action_fallback_never_substitutes_generic_proceed(self) -> None:
        self.policy._broken_actions.add("continue_game_over")
        state = self._game_over(
            actions=["continue_game_over", "proceed"],
            can_continue=True,
            can_return=False,
            showing_summary=False,
        )

        decision = self.policy.decide(state, self.ctx)

        self.assertIsNone(decision.action)
        self.assertNotIn(decision.action, {"continue_run", "proceed"})

    def test_policy_exception_fallback_never_bypasses_terminal_protocol(self) -> None:
        self.policy._decide_errors = 9

        def fail_terminal_handler(_state: dict, _ctx) -> object:
            raise RuntimeError("synthetic terminal policy failure")

        self.policy._game_over = fail_terminal_handler
        state = self._game_over(
            actions=["continue_game_over", "proceed"],
            can_continue=True,
            can_return=False,
            showing_summary=False,
        )

        decision = self.policy.decide(state, self.ctx)

        self.assertIsNone(decision.action)
        self.assertNotIn(decision.action, {"continue_run", "proceed"})

    def test_terminal_sequence_continues_before_requesting_finalize(self) -> None:
        intro = self._game_over(
            actions=["continue_game_over"],
            can_continue=True,
            can_return=False,
            showing_summary=False,
        )
        first = self.policy._game_over(intro, self.ctx)
        self.assertEqual(first.action, "continue_game_over")
        self.assertFalse(self.ctx.finalize_requested)

        animating = self._game_over(
            actions=[],
            can_continue=False,
            can_return=False,
            showing_summary=True,
        )
        waiting = self.policy._game_over(animating, self.ctx)
        self.assertIsNone(waiting.action)
        self.assertFalse(self.ctx.finalize_requested)

        summary_ready = self._game_over(
            actions=["return_to_main_menu"],
            can_continue=False,
            can_return=True,
            showing_summary=True,
        )
        persistence_barrier = self.policy._game_over(summary_ready, self.ctx)
        repeated_poll = self.policy._game_over(summary_ready, self.ctx)
        self.assertIsNone(persistence_barrier.action)
        self.assertIsNone(repeated_poll.action)
        self.assertTrue(self.ctx.finalize_requested)

        self.ctx.run_finalized = True
        leave = self.policy._game_over(summary_ready, self.ctx)
        self.assertEqual(leave.action, "return_to_main_menu")

    def test_reconnected_old_terminal_echo_exits_without_requesting_stats(self) -> None:
        reconnect_ctx = SimpleNamespace(
            run_id="run_unknown",
            decisions=[],
            run_finalized=False,
            finalize_requested=False,
        )
        summary_ready = self._game_over(
            actions=["return_to_main_menu"],
            can_continue=False,
            can_return=True,
            showing_summary=True,
        )

        decision = self.policy._game_over(summary_ready, reconnect_ctx)

        self.assertEqual(decision.action, "return_to_main_menu")
        self.assertFalse(reconnect_ctx.finalize_requested)


class McpGameOverActionContractTests(unittest.TestCase):
    def test_mcp_full_profile_exposes_continue_game_over(self) -> None:
        server_source = (MCP_ROOT / "src" / "sts2_mcp" / "server.py").read_text(
            encoding="utf-8")
        client_source = (MCP_ROOT / "src" / "sts2_mcp" / "client.py").read_text(
            encoding="utf-8")

        self.assertIn('ActionToolSpec("continue_game_over"', server_source)
        client_tree = ast.parse(client_source)
        methods = [
            node for node in ast.walk(client_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "continue_game_over"
        ]
        self.assertEqual(len(methods), 1)
        method_source = ast.get_source_segment(client_source, methods[0]) or ""
        self.assertIn("self.execute_action(", method_source)
        self.assertIn('"continue_game_over"', method_source)


if __name__ == "__main__":
    unittest.main()
