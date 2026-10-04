"""Audit 08: every focus state used by scoring advances on applied receipts.

_score_play consumes _focus_played_index and _focus_drift_flips for the
multi-scaler focus lock as well as _focus_index for sticky targeting. A failed
or response-lost action must not advance any of these three states. The existing
Agent receipt path appends Decision.tags to ctx.credit_tags only for an applied
action; Policy imports accepted tags through _sync_action_handshakes. Tests
simulate that path without making a game/API request.
"""
from __future__ import annotations

from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest

import test_policy_audit_contracts as audit


class FocusReceiptContracts(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="ascend-focus-receipt-")
        self.addCleanup(temp.cleanup)
        self.p = audit.policy.Policy(
            audit.knowledge.Knowledge(Path(temp.name), repair_phantoms=False),
            random.Random(13))
        self.ctx = SimpleNamespace(
            current_combat_is_hard=False, run_finalized=True,
            finalize_requested=False, credit_tags=[], combat=None,
            combat_notes=[], pending_event=None, died_in_combat=None,
            died_to_event=None, rests_healed_at_full=0,
            death_hp_pct_at_entry=None, death_was_elite=False, run_id=None)
        self.state = {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": 2, "combat": {
                "player": {"current_hp": 80, "max_hp": 80, "block": 0, "energy": 3},
                "hand": [audit.card(0, "STRIKE", damage=6, targets=[0, 1])],
                "enemies": [audit.enemy(0, incoming=5), audit.enemy(1, incoming=30)]},
            "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                    "floor": 9, "deck": []},
        }
        self.p._focus_index = 0
        self.p._focus_played_index = 0
        self.p._focus_drift_flips = 0

    def focus(self) -> tuple:
        return (self.p._focus_index, self.p._focus_played_index,
                self.p._focus_drift_flips)

    def test_all_focus_state_preserved_until_play_receipt_is_applied(self) -> None:
        decision = self.p.decide(self.state, self.ctx)
        self.assertEqual((decision.action, decision.params.get("target_index")),
                         ("play_card", 1))
        self.assertEqual(self.ctx.credit_tags, [])
        self.assertEqual(
            self.focus(), (0, 0, 0),
            "A proposed play must not advance played-target memory or drift-lock count")
        # A lost/failed request never adds tags. A retry must preserve the same
        # confirmed focus tuple, rather than letting failed targets gain locks.
        self.p.decide(self.state, self.ctx)
        self.assertEqual(self.focus(), (0, 0, 0))

    def test_applied_receipt_commits_all_focus_state_once(self) -> None:
        decision = self.p.decide(self.state, self.ctx)
        self.assertEqual((decision.action, decision.params.get("target_index")),
                         ("play_card", 1))
        self.ctx.credit_tags.extend(decision.tags or [])
        self.p.decide(self.state, self.ctx)
        self.assertEqual(self.focus(), (1, 1, 1))
        # Re-reading the same applied receipt is not another focus switch.
        self.p.decide(self.state, self.ctx)
        self.assertEqual(self.focus(), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
