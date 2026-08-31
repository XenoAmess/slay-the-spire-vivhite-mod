"""Focused regressions for live Boss race survival projection."""
from __future__ import annotations

from pathlib import Path
import random
import sys
import tempfile
from types import SimpleNamespace
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from character_profiles import ProfileStore  # noqa: E402
from knowledge import Knowledge  # noqa: E402
from policy import Policy  # noqa: E402


class BossRaceSustainProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-boss-race-sustain-")
        self.store = ProfileStore(Path(self.temp.name) / "knowledge")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _policy_and_context(self) -> tuple[Policy, SimpleNamespace]:
        policy = Policy(
            Knowledge(self.store.vivhite, repair_phantoms=False),
            random.Random(11),
        )
        context = SimpleNamespace(
            combat={"comp_id": "RITUAL_BEAST", "node_type": "Boss"},
            current_combat_is_hard=True,
            credit_tags=[],
            stall_analysis_asked=False,
            stall_analysis_needed=False,
            stall_giveup=False,
        )
        return policy, context

    @staticmethod
    def _state(turn: int, hp: int, incoming: int) -> dict:
        attack = {
            "index": 0,
            "card_id": "VIVHITE_CARD_LUMINOUS_PROJECTION",
            "name": "弦光投影",
            "card_type": "Attack",
            "playable": True,
            "energy_cost": 1,
            "requires_target": True,
            "valid_target_indices": [0],
            "dynamic_values": [{"name": "Damage", "current_value": 10}],
        }
        block = {
            "index": 1,
            "card_id": "VIVHITE_CARD_CLOSED_DOMAIN_MAPPING",
            "name": "闭域映射",
            "card_type": "Skill",
            "playable": True,
            "energy_cost": 1,
            "requires_target": False,
            "dynamic_values": [{"name": "Block", "current_value": 9}],
        }
        return {
            "screen": "COMBAT",
            "available_actions": ["play_card", "end_turn"],
            "turn": turn,
            "combat": {
                "player": {
                    "current_hp": hp,
                    "max_hp": 85,
                    "block": 0,
                    "energy": 3,
                    "powers": [],
                },
                "hand": [attack, block],
                "enemies": [{
                    "index": 0,
                    "enemy_id": "RITUAL_BEAST",
                    "name": "仪式兽",
                    "current_hp": 168,
                    "max_hp": 252,
                    "block": 0,
                    "is_alive": True,
                    "is_hittable": True,
                    "intents": [{"total_damage": incoming}],
                }],
            },
            # Keep the joint-defense fallback deliberately weak.  The regression
            # must be decided by observed sustain, not by a generous deck prior.
            "run": {
                "current_hp": hp,
                "max_hp": 85,
                "gold": 0,
                "floor": 17,
                "deck": [{
                    "card_id": "VIVHITE_CARD_LUMINOUS_PROJECTION",
                    "card_type": "Attack",
                    "energy_cost": 1,
                    "dynamic_values": [
                        {"name": "Damage", "current_value": 10}],
                }],
            },
        }

    def _reach_turn_three(self, *, observe_heal: bool) -> tuple[Policy, object]:
        policy, context = self._policy_and_context()

        # F17 evidence shape: Boss opens with a zero-damage action.  During T1,
        # Qingke costs 10 net HP.  T2 starts at 75, then a drain attack resolves
        # to +2 net HP after its Qingke payment.  T3 starts at 70.
        policy.decide(self._state(1, 85, 0), context)
        policy.decide(self._state(1, 75, 0), context)
        policy.decide(self._state(2, 75, 18), context)
        if observe_heal:
            policy.decide(self._state(2, 77, 18), context)

        # Match the already-observed combat output at the T3 latch boundary:
        # 20 damage/turn, then the existing 20% escalation-bucket uplift.
        policy._krace_turns = 2
        policy._krace_dmg = 40.0
        policy._krace_dmg_sustained = 40.0
        decision = policy.decide(self._state(3, 70, 20), context)
        return policy, decision

    def test_observed_qingke_drain_and_zero_turn_use_net_hp_survival(self) -> None:
        policy, decision = self._reach_turn_three(observe_heal=True)

        # Turn-start samples are 85→75 (-10) and 75→70 (-5): EMA 8.5.
        # Intra-turn observations separately prove Qingke/self-cost and drain.
        self.assertAlmostEqual(policy._race_loss_rate, 8.5)
        self.assertEqual(policy._race_same_round_loss, 10.0)
        self.assertEqual(policy._race_same_round_heal, 2.0)
        self.assertEqual(policy._race_zero_intent_rounds, 1)
        self.assertIn("BOSS_SUSTAIN_NET_HP", decision.reason)
        self.assertNotIn("斩杀竞速投影", decision.reason)
        self.assertFalse(policy._krace_latch)

    def test_no_observed_heal_keeps_existing_boss_race_guard(self) -> None:
        policy, decision = self._reach_turn_three(observe_heal=False)

        self.assertEqual(policy._race_same_round_heal, 0.0)
        self.assertNotIn("BOSS_SUSTAIN_NET_HP", decision.reason)
        self.assertIn("斩杀竞速投影", decision.reason)
        self.assertTrue(policy._krace_latch)


if __name__ == "__main__":
    unittest.main()
