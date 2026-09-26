"""Reward UI handshake regressions for the 2026-09-18/26 claim/skip loop."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from knowledge import Knowledge  # noqa: E402
from policy import Policy  # noqa: E402


def reward(index=0, kind="Card", description="Card reward", claimable=True):
    return {"index": index, "reward_type": kind, "description": description,
            "claimable": claimable}


class RewardCycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sts2-reward-cycle-")
        self.addCleanup(temporary.cleanup)
        self.policy = Policy(Knowledge(Path(temporary.name)))
        self.ctx = SimpleNamespace(run_id="REWARD_CYCLE", credit_tags=[])
        # Exercise only UI lifecycle: card valuation and pick policy are unchanged.
        for name, value in (("eval_reward_card", -1.0),
                            ("_pick_threshold", 8.0),
                            ("_thin_deck_must_pick", False)):
            mocked = patch.object(self.policy, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def root(self, rewards=None, **kwargs):
        state = {
            "screen": "REWARD", "run_id": self.ctx.run_id,
            "available_actions": ["claim_reward", "proceed"],
            "run": {"floor": 14, "current_hp": 46, "max_hp": 84,
                    "deck": [], "potions": []},
            "reward": {"pending_card_choice": False, "can_proceed": True,
                       "rewards": [reward()] if rewards is None else rewards,
                       "card_options": []},
        }
        state.update(kwargs)
        return state

    def offer(self, root):
        state = deepcopy(root)
        state["available_actions"] = ["choose_reward_card", "skip_reward_cards"]
        # Exact shape of live F14 /state: the child card screen hides ALL root
        # rewards, including siblings; it does not mean those rewards disappeared.
        state["reward"] = {
            "pending_card_choice": True, "can_proceed": False, "rewards": [],
            "card_options": [
                {"index": 0, "card_id": "VIVHITE_CARD_ASTRAL_PURSUIT",
                 "name": "星算追猎", "upgraded": False},
                {"index": 1, "card_id": "VIVHITE_CARD_COMPOSITE_COLOR_WHEEL",
                 "name": "综合色轮+", "upgraded": True},
                {"index": 2, "card_id": "VIVHITE_CARD_LIFE_MANIFOLD",
                 "name": "生命流形", "upgraded": False},
            ],
        }
        return state

    def accepted(self, state, action):
        decision = self.policy.decide(state, self.ctx)
        self.assertEqual(decision.action, action, decision.reason)
        self.ctx.credit_tags.extend(decision.tags)
        return decision

    def test_accepted_open_skip_then_proceed_without_reopening(self):
        root = self.root()
        self.accepted(root, "claim_reward")
        self.accepted(self.offer(root), "skip_reward_cards")
        self.assertEqual(self.policy.decide(root, self.ctx).action, "proceed")

    def test_unknown_transition_does_not_forget_opened_reward(self):
        root = self.root()
        self.accepted(root, "claim_reward")
        self.policy.decide(dict(root, screen="UNKNOWN", available_actions=[]), self.ctx)
        self.accepted(self.offer(root), "skip_reward_cards")
        self.assertEqual(self.policy.decide(root, self.ctx).action, "proceed")

    def test_no_receipt_keeps_claim_retryable(self):
        root = self.root()
        first = self.policy.decide(root, self.ctx)
        retry = self.policy.decide(root, self.ctx)
        self.assertEqual((first.action, first.params), (retry.action, retry.params))
        self.assertEqual(retry.action, "claim_reward")
        self.assertEqual(self.policy._reward_tried, set())

    def test_explicit_rejection_retains_existing_suppression(self):
        root = self.root()
        first = self.policy.decide(root, self.ctx)
        self.policy.note_action_failed(first.action, first.tags)
        self.assertEqual(self.policy.decide(root, self.ctx).action, "proceed")

    def test_two_identical_rewards_are_each_opened_once(self):
        root = self.root([reward(0), reward(1)])
        first = self.accepted(root, "claim_reward")
        self.assertEqual(first.params, {"option_index": 0})
        self.accepted(self.offer(root), "skip_reward_cards")
        second = self.accepted(root, "claim_reward")
        self.assertEqual(second.params, {"option_index": 1})
        self.accepted(self.offer(root), "skip_reward_cards")
        self.assertEqual(self.policy.decide(root, self.ctx).action, "proceed")

    def test_taken_identical_reward_can_reuse_index_after_reindex(self):
        root = self.root([reward(0), reward(1)])
        self.accepted(root, "claim_reward")
        with patch.object(self.policy, "eval_reward_card", return_value=10.0):
            self.accepted(self.offer(root), "choose_reward_card")
        # A native take removes one reward and reindexes the identical sibling.
        remaining = self.root([reward(0)])
        self.assertEqual(self.policy.decide(remaining, self.ctx).action, "claim_reward")

    def test_same_floor_new_reward_screen_can_repeat_identical_payload(self):
        root = self.root()
        self.accepted(root, "claim_reward")
        self.accepted(self.offer(root), "skip_reward_cards")
        self.assertEqual(self.policy.decide(root, self.ctx).action, "proceed")
        self.policy.decide(dict(root, screen="MAP", available_actions=[],
                                reward=None, map={}), self.ctx)
        self.assertEqual(self.policy.decide(root, self.ctx).action, "claim_reward")

    def test_new_floor_can_repeat_identical_reward(self):
        root = self.root()
        self.accepted(root, "claim_reward")
        self.accepted(self.offer(root), "skip_reward_cards")
        root["run"]["floor"] += 1
        self.assertEqual(self.policy.decide(root, self.ctx).action, "claim_reward")

    def test_new_run_can_repeat_identical_reward_without_old_receipts(self):
        root = self.root()
        self.accepted(root, "claim_reward")
        self.accepted(self.offer(root), "skip_reward_cards")
        self.ctx = SimpleNamespace(run_id="REWARD_CYCLE_NEW", credit_tags=[])
        self.assertEqual(self.policy.decide(self.root(), self.ctx).action, "claim_reward")

    def test_starting_inside_offer_recovers_after_one_parent_observation(self):
        # A restarted process has no parent identity yet.  It may reopen once to
        # bind that identity, but must then proceed rather than enter a cycle.
        root = self.root()
        self.accepted(self.offer(root), "skip_reward_cards")
        self.accepted(root, "claim_reward")
        self.accepted(self.offer(root), "skip_reward_cards")
        self.assertEqual(self.policy.decide(root, self.ctx).action, "proceed")

    def test_skipping_cards_does_not_suppress_other_reward_types(self):
        root = self.root([reward(0), reward(1, "Relic", "Anchor")])
        self.accepted(root, "claim_reward")
        self.accepted(self.offer(root), "skip_reward_cards")
        sibling = self.accepted(root, "claim_reward")
        self.assertEqual(sibling.params, {"option_index": 1})

    def test_offer_failure_cooldown_is_not_inherited_by_another_offer(self):
        root = self.root([reward(0), reward(1)])
        self.accepted(root, "claim_reward")
        offer = self.offer(root)
        self.accepted(offer, "skip_reward_cards")
        key = (0, "VIVHITE_CARD_ASTRAL_PURSUIT")
        self.policy._reward_card_cooldowns[key] = 5
        self.policy.decide(offer, self.ctx)
        self.assertGreater(self.policy._reward_card_cooldowns.get(key, 0), 0)
        self.accepted(root, "claim_reward")
        self.accepted(offer, "skip_reward_cards")
        self.assertEqual(self.policy._reward_card_cooldowns, {})


if __name__ == "__main__":
    unittest.main()
