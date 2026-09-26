"""Regression coverage for the 2026-09-17 F35 empty-hand deadlock."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from knowledge import Knowledge  # noqa: E402
from policy import Policy  # noqa: E402


class EmptyHandEndTurnRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = Policy(Knowledge(Path(tempfile.mkdtemp(
            prefix="sts2-empty-hand-recovery-"))))
        self.player = {
            "current_hp": 85,
            "max_hp": 102,
            "block": 27,
            "energy": 0,
            "cards_played_this_turn": 0,
        }
        self.readiness = {
            "reason": "local_turn_not_ready",
            "actions_settled": True,
            "player_action_phase": True,
            "combat_in_progress": True,
            "combat_over_or_ending": False,
            "modal_open": False,
            "player_actions_disabled": False,
            "hand_in_card_play": False,
            "hand_in_card_selection": False,
            "hand_mode": "Play",
            "all_players_ready_to_end_turn": True,
        }

    def decide(self, readiness: dict | None = None):
        combat = {"action_readiness": readiness or self.readiness}
        return self.policy._combat_readiness_wait(
            {}, SimpleNamespace(), combat, self.player, [], 0, 1, {},
            False, 85, 27, 21)

    def test_waits_for_bounded_confirmation_then_forces_end_turn(self) -> None:
        waits = [self.decide() for _ in range(14)]
        self.assertTrue(all(
            decision.action is None and "接口隐藏结束回合" in decision.reason
            for decision in waits))

        recovered = self.decide()
        self.assertEqual(recovered.action, "end_turn")
        self.assertIn("EMPTY_HAND_END_TURN_RECOVERY", recovered.reason)
        self.assertEqual(self.policy._empty_hand_end_turn_stall, 0)

    def test_does_not_bypass_without_all_players_ready(self) -> None:
        unsafe = dict(self.readiness, all_players_ready_to_end_turn=False)
        for _ in range(20):
            decision = self.decide(unsafe)
        self.assertIsNone(decision.action)
        self.assertNotIn("EMPTY_HAND_END_TURN_RECOVERY", decision.reason)
        self.assertEqual(self.policy._empty_hand_end_turn_stall, 0)

    def test_does_not_bypass_opening_draw_or_active_transition(self) -> None:
        for field, value in (
                ("actions_settled", False),
                ("player_action_phase", False),
                ("modal_open", True),
                ("hand_in_card_play", True)):
            with self.subTest(field=field):
                decision = self.decide(dict(self.readiness, **{field: value}))
                self.assertIsNone(decision.action)
                self.assertEqual(self.policy._empty_hand_end_turn_stall, 0)


if __name__ == "__main__":
    unittest.main()
