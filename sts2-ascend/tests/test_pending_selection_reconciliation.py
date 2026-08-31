"""Regression coverage for accepted multi-card deck selections."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402
from policy import Decision  # noqa: E402


def _neow_remove_state(selected_count: int) -> dict:
    return {
        "screen": "CARD_SELECTION",
        "run_id": "NEOW_MULTI_REMOVE",
        "run": {"run_id": "NEOW_MULTI_REMOVE", "floor": 1},
        "selection": {
            "kind": "deck_card_select",
            "prompt": "Remove 2 cards.",
            "min_select": 2,
            "max_select": 2,
            "selected_count": selected_count,
            "cards": [
                {
                    "index": 0,
                    "card_id": "VIVHITE_CARD_VIVHITE_TRANSFORMATION",
                    "upgraded": False,
                },
                {
                    "index": 1,
                    "card_id": "VIVHITE_CARD_CLOSED_DOMAIN_MAPPING",
                    "upgraded": False,
                },
            ],
        },
    }


class PendingSelectionReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = agent_module.Agent.__new__(agent_module.Agent)
        self.decision = Decision(
            "select_deck_card",
            {"option_index": 0},
            "NEOW first required removal",
        )

    def test_same_screen_selected_count_increment_proves_first_pick(self) -> None:
        before = _neow_remove_state(0)
        after = _neow_remove_state(1)

        self.assertEqual(
            self.agent._ambiguous_action_outcome(before, after, self.decision),
            "applied",
        )

    def test_same_screen_without_selection_progress_remains_unproven(self) -> None:
        state = _neow_remove_state(0)

        self.assertEqual(
            self.agent._ambiguous_action_outcome(state, state, self.decision),
            "unproven",
        )


if __name__ == "__main__":
    unittest.main()
