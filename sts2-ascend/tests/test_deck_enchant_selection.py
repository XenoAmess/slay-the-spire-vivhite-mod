"""Offline replay of the F38 empty-confirm enchant stall from 2026-10-03."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402
from policy import Policy  # noqa: E402


def _f38_enchant_state() -> dict:
    # Relevant fields copied from GET /state for TCT5KXLV3Y9R, state_version=16.
    # The live API is never queried by these tests. Scores are fixed in setUp so
    # the replay verifies UI progression independently of learned card values.
    cards = (
        ("STRIKE_IRONCLAD", "打击", False),
        ("STRIKE_IRONCLAD", "打击", False),
        ("STRIKE_IRONCLAD", "打击", False),
        ("STRIKE_IRONCLAD", "打击+", True),
        ("BASH", "痛击", False),
        ("BLUDGEON", "重锤", False),
        ("UNRELENTING", "无情猛攻", False),
        ("SWORD_BOOMERANG", "飞剑回旋镖", False),
        ("RAMPAGE", "暴走", False),
        ("SWORD_BOOMERANG", "飞剑回旋镖+", True),
        ("UPPERCUT", "上勾拳+", True),
        ("SWORD_BOOMERANG", "飞剑回旋镖", False),
        ("RAMPAGE", "暴走", False),
        ("THUNDERCLAP", "闪电霹雳+", True),
        ("DISMANTLE", "拆卸", False),
        ("FEED", "狂宴", False),
        ("HEADBUTT", "头槌", False),
        ("THUNDERCLAP", "闪电霹雳+", True),
        ("SETUP_STRIKE", "预备打击+", True),
        ("MANGLE", "凌虐+", True),
        ("FISTICUFFS", "拳斗+", True),
    )
    return {
        "screen": "CARD_SELECTION",
        "native_profile_id": 1,
        "run_id": "TCT5KXLV3Y9R",
        "state_version": 16,
        "run": {"run_id": "TCT5KXLV3Y9R", "floor": 38,
                "current_hp": 35, "max_hp": 83},
        "available_actions": ["save_and_quit", "select_deck_card",
                              "confirm_selection", "discard_potion"],
        "selection": {
            "kind": "deck_enchant_select",
            "prompt": "[center]选择[blue]3[/blue]张牌来[purple]附魔[/purple]。[/center]",
            "min_select": 0,
            "max_select": 3,
            "selected_count": 0,
            "can_confirm": True,
            "requires_confirmation": True,
            "cards": [
                {"index": index, "card_id": card_id, "name": name,
                 "upgraded": upgraded, "card_type": "Attack", "selected": False}
                for index, (card_id, name, upgraded) in enumerate(cards)
            ],
        },
    }


class DeckEnchantSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        knowledge = SimpleNamespace(profile=None, policy={}, stats={})
        self.policy = Policy(knowledge)
        self.ctx = SimpleNamespace(credit_tags=[])
        self.state = _f38_enchant_state()
        self.agent = agent_module.Agent.__new__(agent_module.Agent)
        # Keep strategy scoring outside this UI-contract regression. Only candidate
        # order is controlled; selection memory, confirmation and reconciliation
        # run through the production implementations.
        self.enterContext(mock.patch.object(
            self.policy, "eval_reward_card",
            side_effect=lambda card, *args, **kwargs: 100.0 - card["index"]))
        self.enterContext(mock.patch.object(
            self.policy, "_pick_threshold", return_value=0.0))
        self.enterContext(mock.patch.object(
            self.policy, "_thin_deck_must_pick", return_value=False))
        self.enterContext(mock.patch.object(
            self.policy, "_knowledge_demon_curse_offset", return_value=0.0))
        for method in ("_card_pick_burst_audit", "_vivhite_margin_pick_note",
                       "_vivhite_life_cost_pick_note"):
            self.enterContext(mock.patch.object(self.policy, method, return_value=""))

    def _choose(self):
        return self.policy._card_selection(self.state, self.ctx)

    def _accept(self, decision) -> None:
        before = deepcopy(self.state)
        self.ctx.credit_tags.extend(decision.tags)
        self.state["selection"]["cards"][decision.params["option_index"]]["selected"] = True
        self.state["selection"]["selected_count"] += 1
        self.assertEqual(self.agent._ambiguous_action_outcome(
            before, self.state, decision), "applied")

    def test_raw_empty_grid_selects_a_card_instead_of_confirming_nothing(self) -> None:
        decision = self._choose()
        self.assertEqual(decision.action, "select_deck_card")
        self.assertEqual(self.state["selection"]["selected_count"], 0)
        self.assertFalse(self.ctx.credit_tags)

    def test_three_distinct_accepted_clicks_fill_capacity_then_confirm(self) -> None:
        indices = []
        for expected_count in range(3):
            with self.subTest(selected_count=expected_count):
                decision = self._choose()
                self.assertEqual(decision.action, "select_deck_card")
                indices.append(decision.params["option_index"])
                self._accept(decision)
        self.assertEqual(len(set(indices)), 3)
        self.assertEqual(self._choose().action, "confirm_selection")

    def test_accepted_click_waits_for_count_refresh_before_next_candidate(self) -> None:
        decision = self._choose()
        self.ctx.credit_tags.extend(decision.tags)
        for _ in range(2):
            stale = self._choose()
            self.assertIsNone(stale.action)
            self.assertIn("等待结果刷新", stale.reason)
        self.state["selection"]["selected_count"] = 1
        next_decision = self._choose()
        self.assertEqual(next_decision.action, "select_deck_card")
        self.assertNotEqual(next_decision.params, decision.params)

    def test_click_without_receipt_remains_retryable_without_phantom_credit(self) -> None:
        first = self._choose()
        retry = self._choose()
        self.assertEqual(retry.action, "select_deck_card")
        self.assertEqual(retry.params, first.params)
        self.assertFalse(self.ctx.credit_tags)
        self.assertEqual(self.agent._ambiguous_action_outcome(
            self.state, self.state, first), "unproven")

    def test_restarted_brain_does_not_deselect_native_selected_cards(self) -> None:
        self.state["selection"]["cards"][0]["selected"] = True
        self.state["selection"]["selected_count"] = 1
        decision = self._choose()
        self.assertEqual(decision.action, "select_deck_card")
        self.assertNotEqual(decision.params["option_index"], 0)

    def test_new_selection_instance_does_not_inherit_previous_clicks(self) -> None:
        first = self._choose()
        self._accept(first)
        self._choose()  # Consume the accepted click into the old screen ledger.
        self.state = _f38_enchant_state()
        self.state["run"]["floor"] = 39
        fresh = self._choose()
        self.assertEqual(fresh.action, "select_deck_card")
        self.assertEqual(fresh.params, first.params)
        first_token = next(tag[1] for tag in first.tags if tag[0] == "selection_click")
        fresh_token = next(tag[1] for tag in fresh.tags if tag[0] == "selection_click")
        self.assertNotEqual(first_token, fresh_token)

    def test_corrected_api_minimum_one_still_uses_all_three_enchants(self) -> None:
        self.state["selection"]["min_select"] = 1
        for _ in range(3):
            decision = self._choose()
            self.assertEqual(decision.action, "select_deck_card")
            self._accept(decision)
        self.assertEqual(self._choose().action, "confirm_selection")

    def test_fewer_eligible_cards_than_capacity_confirms_after_available_cards(self) -> None:
        self.state["selection"]["cards"] = self.state["selection"]["cards"][:2]
        for _ in range(2):
            decision = self._choose()
            self.assertEqual(decision.action, "select_deck_card")
            self._accept(decision)
        self.assertEqual(self._choose().action, "confirm_selection")

    def test_other_optional_zero_choice_grids_can_still_confirm_empty(self) -> None:
        for kind in ("deck_card_select", "deck_transform_select", "combat_hand_select"):
            with self.subTest(kind=kind):
                self.state["selection"]["kind"] = kind
                self.assertEqual(self._choose().action, "confirm_selection")


if __name__ == "__main__":
    unittest.main()
