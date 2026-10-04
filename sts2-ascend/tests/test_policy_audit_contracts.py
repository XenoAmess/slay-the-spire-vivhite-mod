"""Offline behavioral counterexamples from the 2026-10-04 Brain audit.

These are ordinary regression contracts, deliberately failing on the audited
baseline. They do not submit game actions, load learned production memory, or
invoke providers. Native per-hit limits come from the versioned v0.111.0
mechanics snapshot. Hardened Shell display_amount is the optional native
remaining HP-loss allowance agreed with the Agent API implementation. A missing
or unreadable value is unknown; it is not the original total Amount.
"""
from __future__ import annotations

import copy
from pathlib import Path
import random
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import character_profiles  # noqa: E402
import knowledge  # noqa: E402
import policy  # noqa: E402


def card(index: int, card_id: str, *, damage: int = 0, block: int = 0,
         hits: int = 1, cost: int = 1, kind: str = "Attack",
         targets: list[int] | None = None) -> dict:
    values = []
    if damage:
        values.append({"name": "Damage", "current_value": damage})
    if block:
        values.append({"name": "Block", "current_value": block})
    if hits != 1:
        values.append({"name": "Hits", "current_value": hits})
    return {
        "index": index, "card_id": card_id, "name": card_id,
        "card_type": kind, "energy_cost": cost, "playable": True,
        "upgraded": False, "dynamic_values": values,
        "requires_target": targets is not None,
        "valid_target_indices": list(targets or []),
    }


def enemy(index: int = 0, *, hp: int = 100, block: int = 0,
          incoming: int = 0, powers: list[dict] | None = None) -> dict:
    return {
        "index": index, "enemy_id": f"AUDIT_ENEMY_{index}",
        "name": f"Enemy {index}", "current_hp": hp, "max_hp": 100,
        "block": block, "is_alive": True, "is_hittable": True,
        "powers": copy.deepcopy(powers or []),
        "intents": [{"total_damage": incoming}],
    }


class CombatAuditContracts(unittest.TestCase):
    def make_policy(self) -> policy.Policy:
        memory = SimpleNamespace(
            policy=copy.deepcopy(knowledge.DEFAULT_POLICY), stats={},
            is_known_respawn_add=lambda _key: False)
        return policy.Policy(memory, random.Random(13))

    def score(self, p: policy.Policy, c: dict, enemies: list[dict]) -> tuple:
        return p._score_play(
            c, enemies, incoming=sum(e["intents"][0]["total_damage"]
                                     for e in enemies),
            my_block=0, round_no=1, pol=p.know.policy,
            my_hp=80, my_max_hp=80, cur_energy=3,
            player_powers=[], observed_hand_count=2)

    def test_scoring_an_unselected_candidate_preserves_focus_memory(self) -> None:
        p = self.make_policy()
        p._focus_index = 0
        enemies = [enemy(0, incoming=10), enemy(1, incoming=12)]
        self.score(p, card(1, "STRIKE", damage=6, targets=[1]), enemies)
        self.assertEqual(
            p._focus_index, 0,
            "Scoring a candidate must not commit its target as the actual focus")

    def test_other_candidate_evaluation_does_not_change_a_cards_score_or_target(self) -> None:
        p = self.make_policy()
        enemies = [enemy(0, incoming=10), enemy(1, incoming=12)]
        selected = card(0, "STRIKE", damage=6, targets=[0, 1])
        p._focus_index = 0
        baseline = self.score(p, selected, enemies)
        p._focus_index = 0
        self.score(p, card(1, "STRIKE", damage=6, targets=[1]), enemies)
        repeated = self.score(p, selected, enemies)
        self.assertEqual(
            repeated[:2], baseline[:2],
            "Candidate traversal must share one pre-decision focus snapshot")

    def test_hardened_shell_exhausted_within_multihit_never_resumes_hp_damage(self) -> None:
        p = self.make_policy()
        target = enemy(hp=25, powers=[
            {"id": "HARDENED_SHELL_POWER", "amount": 20, "display_amount": 20}])
        c = card(0, "MULTIHIT_AUDIT", damage=10, hits=3, targets=[0])
        score, target_index, why = self.score(p, c, [target])
        self.assertEqual(target_index, 0)
        self.assertFalse(
            why.startswith("可击杀"),
            "Native per-turn HP-loss cap 20 cannot kill an enemy at 25 HP")
        self.assertLessEqual(score, 20.0)

    def test_hardened_shell_prices_the_native_remaining_allowance(self) -> None:
        p = self.make_policy()
        target = enemy(hp=8, powers=[
            {"id": "HARDENED_SHELL_POWER", "amount": 20, "display_amount": 5}])
        score, _, why = self.score(
            p, card(0, "STRIKE", damage=10, targets=[0]), [target])
        self.assertFalse(
            why.startswith("可击杀"),
            "Amount 20 is a total cap; native remaining allowance 5 cannot kill HP 8")
        self.assertAlmostEqual(score, 5.0)

    def test_hardened_shell_zero_native_remaining_allowance_stays_zero(self) -> None:
        p = self.make_policy()
        target = enemy(hp=8, powers=[
            {"id": "HARDENED_SHELL_POWER", "amount": 20, "display_amount": 0}])
        score, _, why = self.score(
            p, card(0, "STRIKE", damage=10, targets=[0]), [target])
        self.assertFalse(why.startswith("可击杀"))
        self.assertAlmostEqual(
            score, 0.0, msg="A known exhausted cap permits zero further HP removal")

    def assert_unknown_hardened_shell_does_not_claim_certain_kill(self,
                                                              power: dict) -> None:
        p = self.make_policy()
        _, _, why = self.score(
            p, card(0, "STRIKE", damage=12, targets=[0]),
            [enemy(hp=10, powers=[power])])
        self.assertFalse(
            why.startswith("可击杀"),
            "Unknown native remaining allowance must not certify a lethal attack")

    def test_missing_native_remaining_allowance_is_not_the_total_cap(self) -> None:
        self.assert_unknown_hardened_shell_does_not_claim_certain_kill(
            {"id": "HARDENED_SHELL_POWER", "amount": 20})

    def test_null_native_remaining_allowance_is_not_the_total_cap(self) -> None:
        self.assert_unknown_hardened_shell_does_not_claim_certain_kill(
            {"id": "HARDENED_SHELL_POWER", "amount": 20, "display_amount": None})

    def test_intangible_remains_active_after_last_slippery_layer_breaks(self) -> None:
        p = self.make_policy()
        target = enemy(hp=10, powers=[
            {"id": "SLIPPERY_POWER", "amount": 1},
            {"id": "INTANGIBLE_POWER", "amount": 1}])
        c = card(0, "MULTIHIT_AUDIT", damage=6, hits=3, targets=[0])
        score, target_index, why = self.score(p, c, [target])
        self.assertEqual(target_index, 0)
        self.assertFalse(
            why.startswith("可击杀"),
            "Intangible caps every hit even when Slippery expires mid-card")
        self.assertAlmostEqual(score, 3.0)

    def test_ordinary_target_retains_full_multihit_damage(self) -> None:
        p = self.make_policy()
        score, _, why = self.score(
            p, card(0, "MULTIHIT_AUDIT", damage=10, hits=3, targets=[0]),
            [enemy(hp=25)])
        self.assertTrue(why.startswith("可击杀"))
        self.assertGreater(score, 25.0)

    def potion_state(self, *, hp: int, block: int, damage: int) -> dict:
        return {
            "turn": 1,
            "run": {"current_hp": 80, "max_hp": 80, "floor": 1,
                    "potions": [{
                        "index": 0, "potion_id": "FIRE_POTION",
                        "name": "Fire Potion", "occupied": True,
                        "can_use": True, "usage": "Combat",
                        "requires_target": True, "valid_target_indices": [0],
                        "description": f"Deal {damage} damage."}]},
            "combat": {"player": {
                "current_hp": 80, "max_hp": 80, "block": 0},
                "enemies": [enemy(hp=hp, block=block, powers=[
                    {"id": "ASLEEP_POWER", "amount": 3}])]},
        }

    def potion_decision(self, p: policy.Policy, state: dict):
        ctx = SimpleNamespace(combat={"node_type": "Boss"})
        return p._maybe_potion(state, ctx, hard=True, premium=True)

    def test_sleeping_enemy_survives_potion_after_block_and_must_not_be_woken(self) -> None:
        p = self.make_policy()
        decision = self.potion_decision(
            p, self.potion_state(hp=15, block=10, damage=20))
        self.assertIsNone(
            decision,
            "20 damage into 10 block leaves 15-10=5 HP and wakes the sleeper")

    def test_potion_that_really_kills_through_block_is_allowed(self) -> None:
        decision = self.potion_decision(
            self.make_policy(), self.potion_state(hp=15, block=10, damage=25))
        self.assertIsNotNone(decision)
        self.assertEqual(decision.action, "use_potion")
        self.assertEqual(decision.params, {"option_index": 0, "target_index": 0})

    def test_potion_fully_absorbed_by_block_does_not_wake_sleeper(self) -> None:
        decision = self.potion_decision(
            self.make_policy(), self.potion_state(hp=15, block=20, damage=20))
        self.assertIsNotNone(decision)
        self.assertEqual(decision.action, "use_potion")


class DraftAndRemovalAuditContracts(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="ascend-policy-audit-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def make_policy(self, profile_id: str = "ironclad") -> policy.Policy:
        profiles = character_profiles.ProfileStore(self.root)
        profile = profiles.resolve(profile_id)
        return policy.Policy(
            knowledge.Knowledge(profile, repair_phantoms=False),
            random.Random(13))

    def test_reward_selection_uses_current_hp_for_the_same_offer_value(self) -> None:
        p = self.make_policy("vivhite")
        p.know.policy.update(
            card_exploration_enabled=0, vivhite_life_cost_overcap_skip=0)
        deck = [card(i, "VIVHITE_CARD_LUMINOUS_PROJECTION", damage=10)
                for i in range(4)]
        deck += [card(i + 4, "VIVHITE_CARD_CLOSED_DOMAIN_MAPPING", kind="Skill")
                 for i in range(4)]
        offer = [card(0, "VIVHITE_CARD_CLOSED_PROJECTION", damage=14),
                 card(1, "VIVHITE_CARD_DIFFERENTIAL_SAMPLING", damage=3, cost=0)]
        state = {
            "screen": "CARD_SELECTION",
            "run": {"deck": deck, "current_hp": 10, "max_hp": 78, "floor": 5},
            "selection": {"kind": "reward_card_select", "prompt": "Choose a card",
                          "cards": offer},
            "reward": {"pending_card_choice": True, "card_options": offer},
            "available_actions": ["select_deck_card", "skip_reward_cards"],
        }
        values = [p.eval_reward_card(
            c, deck, current_hp=10, max_hp=78, act=1) for c in offer]
        # Establish the fixture's actual low-HP preference rather than hardcoding
        # arbitrary weights: both entrypoints must agree on the same context.
        self.assertGreater(values[1], values[0])
        with patch.object(p, "_record_card_offer"):
            decision = p._card_selection(state, SimpleNamespace(credit_tags=[]))
        self.assertEqual(decision.action, "select_deck_card")
        self.assertEqual(
            decision.params["option_index"], 1,
            "Draft routing must preserve the low-HP preference of its evaluator")

    def test_shop_removal_selection_preserves_minimum_block_card_count(self) -> None:
        p = self.make_policy()
        p.know.policy["min_block_cards"] = 5
        deck = [card(i, "DEFEND", block=5, kind="Skill") for i in range(5)]
        deck += [card(i + 5, "DUPLICATE_ATTACK", damage=12) for i in range(22)]
        run = {"deck": deck, "current_hp": 80, "max_hp": 80,
               "gold": 200, "floor": 9}
        shop_state = {
            "screen": "SHOP", "run": run,
            "shop": {"is_open": True, "card_removal": {
                "available": True, "used": False, "enough_gold": True,
                "price": 75}, "cards": [], "relics": [], "potions": []},
            "available_actions": ["remove_card_at_shop", "close_shop_inventory"],
        }
        ctx = SimpleNamespace(credit_tags=[])
        opening = p._shop(shop_state, ctx)
        self.assertEqual(opening.action, "remove_card_at_shop")
        # The action was accepted; exercise the existing successful-action
        # handshake rather than directly replacing its pending token.
        ctx.credit_tags = opening.tags
        p._sync_action_handshakes(ctx)
        selection = {
            "screen": "CARD_SELECTION", "run": run,
            "selection": {"kind": "remove", "prompt": "Remove a card",
                          "cards": deck},
            "available_actions": ["select_deck_card"],
        }
        decision = p._card_selection(selection, ctx)
        self.assertEqual(decision.action, "select_deck_card")
        removed = decision.params["option_index"]
        remaining_block_cards = sum(
            policy.card_numbers(c)[1] > 0 for c in deck if c["index"] != removed)
        self.assertGreaterEqual(
            remaining_block_cards, 5,
            "A paid removal with redundant attacks available must retain block floor")
        self.assertEqual(deck[removed]["card_id"], "DUPLICATE_ATTACK")


class FixedSupplyAuditContracts(unittest.TestCase):
    def make_policy(self) -> policy.Policy:
        return policy.Policy(SimpleNamespace(
            policy=copy.deepcopy(knowledge.DEFAULT_POLICY), stats={}),
            random.Random(13))

    def test_adding_an_optional_attack_cannot_reduce_fixed_available_burst(self) -> None:
        p = self.make_policy()
        original = [card(0, "THREE_ENERGY_ATTACK", damage=30, cost=3)]
        expanded = original + [card(1, "TWO_ENERGY_ATTACK", damage=22, cost=2)]
        self.assertGreaterEqual(
            p.deck_burst(expanded, energy=3), p.deck_burst(original, energy=3),
            "A fixed-supply estimate may ignore an optional card; 30 must not become 22")

    def test_zero_cost_attacks_do_not_consume_fixed_supply_energy(self) -> None:
        p = self.make_policy()
        deck = [card(i, "FREE_ATTACK", damage=6, cost=0) for i in range(3)]
        deck.append(card(3, "THREE_ENERGY_ATTACK", damage=30, cost=3))
        self.assertAlmostEqual(p.deck_burst(deck, energy=3), 48.0)

    def test_zero_energy_still_allows_available_zero_cost_attacks(self) -> None:
        p = self.make_policy()
        deck = [card(i, "FREE_ATTACK", damage=6, cost=0) for i in range(3)]
        self.assertAlmostEqual(p.deck_burst(deck, energy=0), 18.0)

    def test_adding_optional_block_cannot_reduce_fixed_available_supply(self) -> None:
        p = self.make_policy()
        original = [card(0, "THREE_ENERGY_BLOCK", block=30, cost=3, kind="Skill")]
        expanded = original + [card(1, "TWO_ENERGY_BLOCK", block=22, cost=2,
                                    kind="Skill")]
        self.assertGreaterEqual(
            p.deck_block_burst(expanded, energy=3),
            p.deck_block_burst(original, energy=3))

    def test_zero_cost_block_does_not_consume_fixed_supply_energy(self) -> None:
        p = self.make_policy()
        deck = [card(i, "FREE_BLOCK", block=6, cost=0, kind="Skill")
                for i in range(3)]
        deck.append(card(3, "THREE_ENERGY_BLOCK", block=30, cost=3, kind="Skill"))
        self.assertAlmostEqual(p.deck_block_burst(deck, energy=3), 48.0)


if __name__ == "__main__":
    unittest.main()
