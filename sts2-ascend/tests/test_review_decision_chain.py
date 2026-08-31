"""Decision evidence must reach reviews without exploding every run log."""
from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402
import llm_review  # noqa: E402
from character_strategy import VIVHITE_STRATEGY  # noqa: E402
from policy import (  # noqa: E402
    Decision,
    idle_energy_rescue_pick,
    idle_leak_audit_note,
)


class IdleLeakAuditTests(unittest.TestCase):
    @staticmethod
    def _block(name="坚毅", cost=1, block=8, **extra):
        return {
            "name": name, "playable": True, "energy_cost": cost,
            "dynamic_values": [{"name": "Block", "current_value": block}],
            **extra,
        }

    @staticmethod
    def _attack(name="打击", cost=1, damage=6, hits=1, **extra):
        values = [{"name": "Damage", "current_value": damage}]
        if hits != 1:
            values.append({"name": "Hits", "current_value": hits})
        return {
            "name": name, "playable": True, "energy_cost": cost,
            "dynamic_values": values, **extra,
        }

    def test_idle_leak_marks_affordable_block_and_race_attack(self) -> None:
        hand = [self._block(block=8), self._attack("双重打击", damage=5, hits=2)]
        note = idle_leak_audit_note(
            hand, energy=2, incoming=11, my_block=5, race_mode=True)
        self.assertIn("IDLE_LEAK_BLK", note)
        self.assertIn("可抵6", note)
        self.assertIn("IDLE_LEAK_RACE", note)
        self.assertIn("预估10", note)

    def test_idle_leak_suppresses_non_candidates_and_dirty_payloads(self) -> None:
        block = self._block()
        self.assertEqual(idle_leak_audit_note([block], 0, 11, 5), "")
        self.assertEqual(idle_leak_audit_note([block], 2, 5, 5), "")
        self.assertEqual(
            idle_leak_audit_note([block], 2, 11, 5, is_unavailable=lambda _c: True), "")
        self.assertEqual(
            idle_leak_audit_note([self._block(cost=2, costs_x=True)], 2, 11, 5), "")
        self.assertEqual(idle_leak_audit_note([object()], "dirty", None, {}), "")


class VivhiteIdleEnergyRescueTests(unittest.TestCase):
    @staticmethod
    def _closed_domain_mapping(*, card_id="VIVHITE_CARD_CLOSED_DOMAIN_MAPPING"):
        return {
            "index": 0,
            "card_id": card_id,
            "name": "闭域映射",
            "card_type": "Skill",
            "playable": True,
            "energy_cost": 1,
            "dynamic_values": [
                {"name": "LifeCost", "base_value": 2, "current_value": 2},
                {"name": "Block", "base_value": 9, "current_value": 9},
            ],
        }

    def _pick(self, card, *, gap, powers=None):
        return idle_energy_rescue_pick(
            [card],
            energy=1,
            incoming=gap,
            my_block=0,
            character_strategy=VIVHITE_STRATEGY,
            player_powers=powers or [],
        )

    def test_f14_gap_two_cough_two_does_not_force_block(self) -> None:
        card, kind = self._pick(self._closed_domain_mapping(), gap=2)

        self.assertIsNone(card)
        self.assertEqual(kind, "")
        note = idle_leak_audit_note(
            [self._closed_domain_mapping()],
            energy=1,
            incoming=2,
            my_block=0,
            character_strategy=VIVHITE_STRATEGY,
            player_powers=[],
        )
        self.assertNotIn("IDLE_LEAK_BLK", note)

    def test_f17_gap_four_cough_two_still_forces_block(self) -> None:
        card, kind = self._pick(self._closed_domain_mapping(), gap=4)

        self.assertEqual(card["card_id"], "VIVHITE_CARD_CLOSED_DOMAIN_MAPPING")
        self.assertEqual(kind, "block")

    def test_independent_draw_benefit_can_force_nonpositive_block_trade(self) -> None:
        card = self._closed_domain_mapping(
            card_id="VIVHITE_CARD_HEURISTIC_SHIELD")
        card["name"] = "启发式护盾"
        card["dynamic_values"][1].update(base_value=8, current_value=8)

        picked, kind = self._pick(card, gap=2)

        self.assertEqual(picked["card_id"], "VIVHITE_CARD_HEURISTIC_SHIELD")
        self.assertEqual(kind, "block")

    def test_consumed_margin_is_not_treated_as_free_block(self) -> None:
        margin = [{
            "power_id": "VIVHITE_POWER_INFINITE_MARGIN_POWER",
            "amount": 2,
        }]

        card, kind = self._pick(
            self._closed_domain_mapping(), gap=2, powers=margin)

        self.assertIsNone(card)
        self.assertEqual(kind, "")


class PersistedDecisionEvidenceTests(unittest.TestCase):
    def test_end_turn_keeps_energy_hand_intent_and_bounded_trace(self) -> None:
        state = {
            "screen": "COMBAT",
            "turn": 4,
            "available_actions": ["play_card", "end_turn"],
            "run": {"floor": 17, "current_hp": 19, "gold": 88},
            "combat": {
                "player": {"current_hp": 19, "max_hp": 80,
                           "block": 3, "energy": 2},
                "hand": [
                    {"index": 0, "card_id": "STRIKE_IRONCLAD", "name": "打击",
                     "card_type": "Attack", "energy_cost": 1, "playable": True,
                     "requires_target": True, "valid_target_indices": [0],
                     "rules_text": "this deliberately large field is not persisted"},
                    {"index": 1, "card_id": "DEFEND_IRONCLAD", "name": "防御",
                     "card_type": "Skill", "energy_cost": 1, "playable": True,
                     "requires_target": False},
                ],
                "enemies": [{"is_alive": True,
                              "intents": [{"total_damage": 11}]}],
            },
        }
        decision = Decision("end_turn", {}, "仍有能量但评估后结束回合")

        row = agent_module._decision_log_entry(
            state, decision, timestamp="12:34:56")

        self.assertEqual(row["turn"], 4)
        self.assertEqual(row["energy"], 2)
        self.assertEqual(row["turn_end_state"]["incoming_damage"], 11)
        self.assertEqual(len(row["turn_end_state"]["hand"]), 2)
        self.assertTrue(row["turn_end_state"]["hand"][0]["playable"])
        self.assertNotIn("rules_text", row["turn_end_state"]["hand"][0])
        self.assertEqual(row["trace"]["selected"]["action"], "end_turn")

    def test_end_turn_persists_native_can_play_and_action_readiness_diagnostics(self) -> None:
        state = {
            "screen": "COMBAT",
            "turn": 6,
            "available_actions": ["end_turn"],
            "run": {"floor": 17, "current_hp": 41, "gold": 99},
            "combat": {
                "action_readiness": {
                    "can_use_combat_actions": False,
                    "reason": "game_action_running",
                    "actions_settled": False,
                    "running_action_type": "QueuedCardAction",
                    "ready_action_type": None,
                    "modal_open": False,
                    "player_actions_disabled": False,
                    "snapshot_stable": False,
                },
                "player": {
                    "current_hp": 41, "max_hp": 78,
                    "block": 0, "energy": 1,
                },
                "hand": [{
                    "index": 0,
                    "card_id": "VIVHITE_CARD_ASTRAL_SEARCH",
                    "name": "星图检索",
                    "card_type": "Skill",
                    "energy_cost": 0,
                    "playable": False,
                    "requires_target": False,
                    "unplayable_reason": "blocked_by_hook",
                    "unplayable_reason_raw": "BlockedByHook",
                    "unplayable_preventer_id": "RINGING_POWER",
                    "unplayable_preventer_type": "RingingPower",
                }],
                "enemies": [{"is_alive": True, "intents": []}],
            },
        }

        row = agent_module._decision_log_entry(
            state, Decision("end_turn", {}, "原生规则阻止出牌"),
            timestamp="16:33:17")

        end_state = row["turn_end_state"]
        self.assertEqual(
            end_state["action_readiness"]["reason"], "game_action_running")
        self.assertFalse(end_state["action_readiness"]["actions_settled"])
        self.assertEqual(
            end_state["hand"][0]["unplayable_reason"], "blocked_by_hook")
        self.assertEqual(
            end_state["hand"][0]["unplayable_reason_raw"], "BlockedByHook")
        self.assertEqual(
            end_state["hand"][0]["unplayable_preventer_id"], "RINGING_POWER")
        self.assertEqual(
            end_state["hand"][0]["unplayable_preventer_type"], "RingingPower")
        self.assertEqual(row["trace"]["candidates"][0]["why"], "blocked_by_hook")

    def test_routine_card_action_stays_compact_but_keeps_turn_and_energy(self) -> None:
        state = {
            "screen": "COMBAT", "turn": 2,
            "run": {"floor": 3, "current_hp": 70, "gold": 12},
            "combat": {"player": {"energy": 1}, "hand": []},
        }
        row = agent_module._decision_log_entry(
            state, Decision("play_card", {"card_index": 0}, "打出打击"),
            timestamp="01:02:03")
        self.assertEqual(row["turn"], 2)
        self.assertEqual(row["energy"], 1)
        self.assertNotIn("trace", row)
        self.assertNotIn("turn_end_state", row)


class ReviewDecisionChainTests(unittest.TestCase):
    @staticmethod
    def _write_run(root: Path, number: int, victory: bool, reasons: list[str]) -> None:
        decisions = [{
            "t": f"00:00:{index:02d}", "screen": "COMBAT", "floor": number,
            "hp": 20 - index, "gold": 0, "action": "play_card",
            "params": {"card_index": index}, "reason": reason,
        } for index, reason in enumerate(reasons)]
        (root / "runs" / f"run-{number:03d}.json").write_text(
            json.dumps({
                "run_id": f"run-{number}", "run_number": number,
                "ascension": 0, "victory": victory, "floor": number,
                "decisions": decisions, "combat_notes": [],
            }, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _knowledge() -> SimpleNamespace:
        return SimpleNamespace(
            stats={
                "version": 1,
                "global": {"runs": 11},
                "cards": {}, "enemies": {}, "events": {},
                "rooms": {}, "rooms_act": {}, "rooms_band": {},
                "respawn_adds": {}, "act_entries": [], "relics": {},
            },
            progression={}, policy={}, game_knowledge=None,
        )

    def test_prompt_inlines_every_row_of_newest_failed_run_without_clipping(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-chain-") as temp:
            knowledge = Path(temp)
            (knowledge / "runs").mkdir()
            old_long_reason = "旧死亡链" * 500
            newest_reasons = ["开局", "中段", "致命决定" * 700]
            self._write_run(knowledge, 9, False, [old_long_reason])
            self._write_run(knowledge, 10, True, ["胜利动作"])
            self._write_run(knowledge, 11, False, newest_reasons)

            with mock.patch.object(llm_review, "KNOWLEDGE_DIR", knowledge):
                prompt = llm_review.build_prompt(
                    self._knowledge(), {"max_runs_in_packet": 100},
                    batch_runs=[9, 10, 11])

        packet_text = re.search(r"```json\n(.*?)\n```", prompt, re.S).group(1)
        packet = json.loads(packet_text)
        full = packet["decision_chain_evidence"]["full_failure_run"]
        self.assertEqual(full["run_number"], 11)
        self.assertEqual(full["decision_count"], len(newest_reasons))
        self.assertEqual([row["reason"] for row in full["decisions"]], newest_reasons)
        self.assertTrue(full["complete_persisted_chain"])
        self.assertNotIn(old_long_reason, packet_text)
        self.assertIn("必须先逐条阅读", prompt)


if __name__ == "__main__":
    unittest.main()
