"""Focused API -> Python -> relic-stat encoding integrity tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent  # noqa: E402
from client import ConnectionDown, Sts2Client  # noqa: E402
import knowledge  # noqa: E402


BROKEN_RELIC_NAME = "�Բ������"


def _api_payload(data: dict) -> bytes:
    return json.dumps(
        {"ok": True, "data": data}, ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class RelicStatsEncodingTests(unittest.TestCase):
    def test_strict_api_decode_preserves_chinese_and_rejects_invalid_utf8(self) -> None:
        state = Sts2Client._decode(_api_payload({
            "run": {"relics": [{
                "relic_id": "VIVHITE_RELIC_ORIGIN_STAR_CHART",
                "name": "孤高冠冕",
            }]},
        }))
        self.assertEqual(state["run"]["relics"][0]["name"], "孤高冠冕")

        with self.assertRaises(ConnectionDown):
            Sts2Client._decode(
                b'{"ok":true,"data":{"name":"\x81"}}')

    def test_post_action_inventory_replaces_corrupt_reward_label_with_id(self) -> None:
        before = Sts2Client._decode(_api_payload({
            "run": {"relics": [{
                "relic_id": "VIVHITE_RELIC_ORIGIN_STAR_CHART",
                "name": "孤高冠冕",
            }]},
        }))
        after = Sts2Client._decode(_api_payload({
            "run": {"relics": [
                {
                    "relic_id": "VIVHITE_RELIC_ORIGIN_STAR_CHART",
                    "name": "孤高冠冕",
                },
                {"relic_id": "ANCHOR", "name": "锚"},
            ]},
        }))

        tags = agent._resolved_relic_pick_tags(
            [
                ("relic_pick", BROKEN_RELIC_NAME),
                ("reward_attempt", 0, "Relic", BROKEN_RELIC_NAME),
            ],
            before,
            after,
        )
        self.assertIn(("relic_pick", "ANCHOR"), tags)
        self.assertNotIn(("relic_pick", BROKEN_RELIC_NAME), tags)

    def test_success_transaction_commits_canonical_relic_attribution(self) -> None:
        before = Sts2Client._decode(_api_payload({
            "screen": "REWARD",
            "run": {"floor": 8, "current_hp": 70, "gold": 120,
                    "relics": []},
        }))
        after = Sts2Client._decode(_api_payload({
            "screen": "REWARD",
            "run": {"floor": 8, "current_hp": 70, "gold": 120,
                    "relics": [{"relic_id": "ANCHOR", "name": "锚"}]},
        }))
        brain = object.__new__(agent.Agent)
        brain.ctx = agent.RunContext(
            run_id="RELIC-RUN", last_hp=70, last_gold=120)
        brain.know = SimpleNamespace(commit_card_play=lambda _card_id: None)
        brain._save_run_progress = lambda _run, force=False: True
        decision = agent.Decision(
            "claim_reward", {"option_index": 0}, "领取遗物",
            tags=[
                ("relic_pick", BROKEN_RELIC_NAME),
                ("reward_attempt", 0, "Relic", BROKEN_RELIC_NAME),
            ],
        )

        brain._commit_successful_action(
            before, decision, observed_state=after)

        self.assertIn(("relic_pick", "ANCHOR"), brain.ctx.credit_tags)
        self.assertEqual(brain.ctx.attribution_tags,
                         [("relic_pick", "ANCHOR")])

    def test_api_to_stats_persists_only_stable_relic_id_as_utf8(self) -> None:
        before = Sts2Client._decode(_api_payload({"run": {"relics": []}}))
        after = Sts2Client._decode(_api_payload({
            "run": {"relics": [{"relic_id": "ANCHOR", "name": "锚"}]},
        }))
        tags = agent._resolved_relic_pick_tags(
            [("relic_pick", BROKEN_RELIC_NAME)], before, after)

        with tempfile.TemporaryDirectory(prefix="sts2-relic-encoding-") as temp:
            root = Path(temp)
            know = knowledge.Knowledge(root, repair_phantoms=False)
            know.commit_run_end(
                12.0, False, [],
                [tag[1] for tag in tags if tag[0] == "relic_pick"],
                [], None, None, raw_floor=12,
            )
            know.save()

            raw = (root / "stats.json").read_bytes()
            decoded = raw.decode("utf-8", errors="strict")
            persisted = json.loads(decoded)
            self.assertEqual(list(persisted["relics"]), ["ANCHOR"])
            self.assertNotIn("\ufffd", decoded)

    def test_stats_boundary_drops_new_corrupt_key_without_rewriting_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-relic-history-") as temp:
            root = Path(temp)
            stats = copy.deepcopy(knowledge.DEFAULT_STATS)
            stats["relics"][BROKEN_RELIC_NAME] = {
                "picked": 4,
                "outcome_sum": 80.0,
                "bias": 0.0,
            }
            (root / "stats.json").write_text(
                json.dumps(stats, ensure_ascii=False), encoding="utf-8")

            know = knowledge.Knowledge(root, repair_phantoms=False)
            know.commit_run_end(
                20.0, False, [], [BROKEN_RELIC_NAME, "ANCHOR"],
                [], None, None, raw_floor=20,
            )

            # Historical evidence is not silently rewritten, while the same bad
            # label cannot receive another run's credit or create a fresh row.
            self.assertEqual(know.stats["relics"][BROKEN_RELIC_NAME]["picked"], 4)
            self.assertEqual(know.stats["relics"][BROKEN_RELIC_NAME]["outcome_sum"], 80.0)
            self.assertEqual(know.stats["relics"]["ANCHOR"]["picked"], 1)

    def test_durable_run_attribution_omits_corrupt_relic_label(self) -> None:
        self.assertEqual(
            agent._durable_attribution_tags([
                ("map_node", "Elite"),
                ("relic_pick", BROKEN_RELIC_NAME),
                ("relic_pick", "ANCHOR"),
            ]),
            [("map_node", "Elite"), ("relic_pick", "ANCHOR")],
        )


if __name__ == "__main__":
    unittest.main()
