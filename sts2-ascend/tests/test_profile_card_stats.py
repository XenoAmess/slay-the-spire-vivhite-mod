"""Per-profile card choices and Vivhite build-distribution contracts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402
import compact_knowledge  # noqa: E402
from floor_stats import (  # noqa: E402
    FloorStatsProvider,
    VIVHITE_CATALOG_SYSTEM_COUNTS,
)


VIVHITE = "VIVHITE_CHARACTER_VIVHITE_CHARACTER"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _deck(*card_ids: str) -> list[dict]:
    return [{"card_id": card_id, "upgraded": False} for card_id in card_ids]


def _run(run_id: str, number: int, floor: int, picks: list[str] | None, *,
         character_id: str | None = None, victory: bool = False,
         human_assisted: bool = False,
         excluded_from_learning: bool = False,
         in_progress: bool = False,
         game_over: bool = False,
         final_deck: list[dict] | None = None) -> dict:
    value = {
        "run_id": run_id,
        "run_number": number,
        "started_at": f"2026-08-31 12:{number:02d}:00",
        "ascension": 0,
        "victory": victory,
        "in_progress": in_progress,
        "floor": floor,
        "decisions": [{"screen": "COMBAT", "floor": floor,
                       "action": "end_turn"}],
    }
    if picks is not None:
        value["attribution_tags"] = [
            ["card_pick", card_id] for card_id in picks]
    if game_over:
        value["decisions"].append({
            "screen": "GAME_OVER", "floor": floor, "action": None})
    if final_deck is not None:
        value["final_deck"] = final_deck
    if character_id is not None:
        value["character_id"] = character_id
    if human_assisted:
        value["human_assisted"] = True
    if excluded_from_learning:
        value["excluded_from_learning"] = True
    return value


class _FakeKnowledge:
    def __init__(self) -> None:
        self.stats = {"global": {"runs": 0, "wins": 0}}
        self.progression = {"character": VIVHITE}
        self.saved_payloads: list[dict] = []

    def save_run_log(self, _run_id: str, payload: dict) -> Path:
        self.saved_payloads.append(payload)
        return Path("terminal.json")

    def save(self) -> None:
        return None


class TerminalDeckPersistenceTests(unittest.TestCase):
    @staticmethod
    def _agent() -> tuple[agent_module.Agent, _FakeKnowledge]:
        brain = object.__new__(agent_module.Agent)
        brain.ctx = agent_module.RunContext(
            run_id="RUN-DECK", ascension=0,
            started_at="2026-08-31 13:00:00", run_number=1,
            profile_id="vivhite", character_id=VIVHITE,
            profile_run_number=1)
        brain.ctx.decisions = [
            {"screen": "COMBAT", "floor": 5, "action": "end_turn"}]
        know = _FakeKnowledge()
        brain.know = know
        brain.active_profile = None
        brain.rotation = None
        brain.runs_played = 0
        brain.request_restart = False
        brain._flush_combat_agg = mock.Mock()
        brain._mark_review_run_healthy = mock.Mock()
        return brain, know

    @staticmethod
    def _reflect(know: _FakeKnowledge, _ctx, _victory: bool, _floor: int) -> str:
        know.stats["global"]["runs"] += 1
        return "terminal lesson"

    def test_terminal_mcp_deck_is_persisted_and_latest_snapshot_is_not_substituted(self) -> None:
        brain, know = self._agent()
        self.assertFalse(brain._observe_run_deck({
            "floor": 4,
            "deck": [{"card_id": "STALE_CARD", "upgraded": False}],
        }, "MAP"))
        terminal_deck = [
            {"card_id": "VIVHITE_CARD_AXIOM_RING", "upgraded": True,
             "name": "公理护环", "card_type": "Skill", "rarity": "Common"},
            {"card_id": "VIVHITE_CARD_AXIOM_RING", "upgraded": False,
             "name": "公理护环", "card_type": "Skill", "rarity": "Common"},
        ]
        with (mock.patch.object(
                agent_module, "finalize_run", side_effect=self._reflect),
              mock.patch.object(agent_module, "llm_review", None),
              mock.patch.object(agent_module, "autogit", None),
              mock.patch.object(agent_module, "log")):
            brain._finalize(False, 5, final_run={
                "floor": 5, "deck": terminal_deck})

        self.assertEqual(len(know.saved_payloads), 1)
        payload = know.saved_payloads[0]
        self.assertEqual(
            [(card["card_id"], card["upgraded"])
             for card in payload["final_deck"]],
            [
                ("VIVHITE_CARD_AXIOM_RING", True),
                ("VIVHITE_CARD_AXIOM_RING", False),
            ])
        self.assertNotIn("STALE_CARD", {
            card["card_id"] for card in payload["final_deck"]})
        self.assertTrue(brain.ctx.run_finalized)

    def test_non_terminal_closure_does_not_promote_observed_snapshot(self) -> None:
        brain, know = self._agent()
        brain._observe_run_deck({
            "floor": 4,
            "deck": [{"card_id": "OBSERVED_NOT_TERMINAL", "upgraded": False}],
        }, "MAP")
        with (mock.patch.object(
                agent_module, "finalize_run", side_effect=self._reflect),
              mock.patch.object(agent_module, "llm_review", None),
              mock.patch.object(agent_module, "autogit", None),
              mock.patch.object(agent_module, "log")):
            brain._finalize(False, 5, final_run=None)

        self.assertEqual(len(know.saved_payloads), 1)
        self.assertNotIn("final_deck", know.saved_payloads[0])


class ProfileCardStatsTests(unittest.TestCase):
    def test_profiles_are_isolated_and_vivhite_builds_use_approved_suits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-profile-cards-") as temp:
            root = Path(temp)
            vivhite_root = root / "profiles" / "vivhite"
            neutral = "VIVHITE_CARD_LUMINOUS_PROJECTION"
            suit_a = "VIVHITE_CARD_AXIOM_RING"
            suit_b = "VIVHITE_CARD_RECURRENT_STARLIGHT"
            suit_c = "VIVHITE_CARD_CRIMSON_AREA"
            bridge = "VIVHITE_CARD_GOLDEN_RATIO"
            foreign = "COLORLESS_TEST_CARD"

            ironclad_runs = [
                _run("I-LEGACY", 1, 10, ["BASH", "BASH", "INFLAME"],
                     final_deck=_deck("STRIKE", "BASH")),
                _run("I-TAGGED", 2, 20, ["SPITE"], character_id="IRONCLAD",
                     final_deck=_deck("STRIKE", "SPITE")),
                _run("I-HUMAN", 3, 99, ["VIVHITE_CARD_AXIOM_RING"],
                     character_id="IRONCLAD", human_assisted=True,
                     final_deck=_deck("BASH")),
                _run("I-IN-PROGRESS", 4, 98, ["MUST_NOT_COUNT"],
                     character_id="IRONCLAD", in_progress=True, game_over=True,
                     final_deck=_deck("MUST_NOT_COUNT")),
                # A misplaced tagged row in the legacy root is not allowed to
                # backfill the authoritative Vivhite profile store.
                _run("ROOT-VIVHITE", 5, 88, ["VIVHITE_CARD_PERFECT_SYNTHESIS"],
                     character_id=VIVHITE,
                     final_deck=_deck(neutral, "VIVHITE_CARD_PERFECT_SYNTHESIS")),
            ]
            vivhite_runs = [
                # One A card plus twenty bridge cards is still A: no share threshold.
                _run("V-A", 1, 20, [suit_a], character_id=VIVHITE,
                     final_deck=_deck(neutral, suit_a, *([bridge] * 20))),
                _run("V-B", 2, 30, [suit_b], character_id=VIVHITE,
                     final_deck=_deck(neutral, suit_b)),
                _run("V-C", 3, 40, [suit_c], character_id=VIVHITE,
                     victory=True, final_deck=_deck(neutral, suit_c)),
                # Presence of two primary suits is mixed even when one dominates.
                _run("V-MIXED", 4, 10, [suit_a, suit_b],
                     character_id=VIVHITE,
                     final_deck=_deck(neutral, suit_a, *([suit_b] * 12))),
                _run("V-BRIDGE-ONLY", 5, 15, [bridge],
                     character_id=VIVHITE,
                     final_deck=_deck(neutral, bridge)),
                _run("V-FOREIGN", 6, 5, [foreign],
                     character_id=VIVHITE,
                     final_deck=_deck(neutral, foreign)),
                # Old logs with picks but no terminal deck are unclassified.
                _run("V-OLD-NO-DECK", 7, 12,
                     ["VIVHITE_CARD_PERFECT_SYNTHESIS"],
                     character_id=VIVHITE),
                # An explicit empty terminal deck is evidence, but has no build signal.
                _run("V-EMPTY-DECK", 8, 13, [], character_id=VIVHITE,
                     final_deck=[]),
                # Foreign cards are counted separately without erasing a primary suit.
                _run("V-A-FOREIGN", 9, 22, [suit_a, foreign],
                     character_id=VIVHITE,
                     final_deck=_deck(neutral, suit_a, foreign)),
                _run("V-HUMAN", 10, 97, [
                    "VIVHITE_CARD_SPECTRAL_INTEGRAL",
                ], character_id=VIVHITE, human_assisted=True,
                     final_deck=_deck(neutral, suit_c)),
                _run("V-EXCLUDED", 11, 98, [
                    "VIVHITE_CARD_CONSERVATION_FIRMAMENT",
                ], character_id=VIVHITE, excluded_from_learning=True,
                     final_deck=_deck(neutral, suit_a)),
                _run("V-IN-PROGRESS", 12, 99, [
                    "VIVHITE_CARD_OPTIMAL_ALGORITHM",
                ], character_id=VIVHITE, in_progress=True,
                     game_over=True,
                     final_deck=_deck(neutral, suit_b)),
            ]
            for data in ironclad_runs:
                _write_json(root / "runs" / f"{data['run_id']}.json", data)
            for data in vivhite_runs:
                _write_json(vivhite_root / "runs" / f"{data['run_id']}.json", data)

            provider = FloorStatsProvider(root, refresh_interval=0)
            snapshot = provider.snapshot({
                "run_id": "LIVE-V", "run_number": 9, "floor": 1,
                "profile_id": "vivhite", "character_id": VIVHITE,
            })
            ironclad = snapshot["profiles"]["ironclad"]
            vivhite = snapshot["profiles"]["vivhite"]
            iron_cards = ironclad["card_choices"]
            vivhite_cards = vivhite["card_choices"]

            self.assertEqual(iron_cards["eligible_runs"], 2)
            self.assertEqual(iron_cards["evidence_runs"], 2)
            self.assertEqual(iron_cards["total_picks"], 4)
            self.assertEqual(iron_cards["cards"]["BASH"]["picked"], 2)
            self.assertEqual(iron_cards["cards"]["BASH"]["run_count"], 1)
            self.assertEqual(iron_cards["cards"]["BASH"]["mean_floor"], 10.0)
            self.assertNotIn("VIVHITE_CARD_AXIOM_RING", iron_cards["cards"])
            self.assertNotIn("VIVHITE_CARD_PERFECT_SYNTHESIS", iron_cards["cards"])
            self.assertNotIn("MUST_NOT_COUNT", iron_cards["cards"])
            self.assertFalse(
                ironclad["selection_system_distribution"]["supported"])
            self.assertFalse(ironclad["build_distribution"]["supported"])
            self.assertEqual(ironclad["build_distribution"]["categories"], {})

            self.assertEqual(vivhite_cards["eligible_runs"], 9)
            self.assertEqual(vivhite_cards["evidence_runs"], 9)
            self.assertEqual(vivhite_cards["total_picks"], 10)
            self.assertNotIn("BASH", vivhite_cards["cards"])
            self.assertNotIn(
                "VIVHITE_CARD_CONSERVATION_FIRMAMENT", vivhite_cards["cards"])
            self.assertNotIn(
                "VIVHITE_CARD_SPECTRAL_INTEGRAL", vivhite_cards["cards"])
            self.assertNotIn(
                "VIVHITE_CARD_OPTIMAL_ALGORITHM", vivhite_cards["cards"])

            selection = vivhite["selection_system_distribution"]
            self.assertEqual(selection["classification"], "card_pick_counts_only")
            self.assertNotIn("run_patterns", selection)
            self.assertEqual(VIVHITE_CATALOG_SYSTEM_COUNTS, {
                "conservation_geometry": 17,
                "recursive_astral": 17,
                "crimson_integral": 17,
                "bridge": 7,
                "neutral": 3,
            })
            selected = selection["categories"]
            self.assertEqual(selected["conservation_geometry"]["card_picks"], 3)
            self.assertEqual(selected["recursive_astral"]["card_picks"], 2)
            self.assertEqual(selected["crimson_integral"]["card_picks"], 2)
            self.assertEqual(selected["bridge"]["card_picks"], 1)
            self.assertEqual(selected["neutral"]["card_picks"], 0)
            self.assertEqual(selected["foreign"]["card_picks"], 2)

            builds = vivhite["build_distribution"]
            self.assertTrue(builds["supported"])
            self.assertEqual(builds["eligible_runs"], 9)
            self.assertEqual(builds["evidence_runs"], 8)
            self.assertEqual(builds["missing_evidence_runs"], 1)
            self.assertEqual(builds["classified_runs"], 7)
            self.assertEqual(builds["unclassified_runs"], 2)
            self.assertEqual(builds["unclassified_with_evidence_runs"], 1)
            self.assertEqual(builds["foreign_card_runs"], 2)
            categories = builds["categories"]
            self.assertEqual(categories["conservation_geometry"]["runs"], 2)
            self.assertEqual(categories["recursive_astral"]["runs"], 1)
            self.assertEqual(categories["crimson_integral"]["runs"], 1)
            self.assertEqual(categories["mixed"]["runs"], 1)
            self.assertEqual(categories["bridge_only"]["runs"], 1)
            self.assertEqual(categories["foreign"]["runs"], 1)
            self.assertEqual(categories["unclassified"]["runs"], 2)
            self.assertAlmostEqual(
                categories["conservation_geometry"]["share"], 2 / 9)
            self.assertAlmostEqual(
                categories["conservation_geometry"]["classified_share"], 2 / 7)
            self.assertEqual(categories["crimson_integral"]["win_rate"], 1.0)
            self.assertEqual(categories["recursive_astral"]["mean_floor"], 30.0)
            self.assertEqual(
                builds["composition"]["foreign"]["card_copies"], 2)

            final_decks = vivhite["final_deck_evidence"]
            self.assertEqual(final_decks["evidence_runs"], 8)
            self.assertEqual(final_decks["missing_evidence_runs"], 1)
            # The old run selected this card, but picks must not fabricate a deck.
            self.assertNotIn(
                "VIVHITE_CARD_PERFECT_SYNTHESIS", final_decks["cards"])

            # Active-profile compatibility keys must point at Vivhite, while the
            # complete profile map continues to expose both characters.
            self.assertEqual(snapshot["card_choices"], vivhite_cards)
            self.assertEqual(
                snapshot["selection_system_distribution"], selection)
            self.assertEqual(snapshot["build_distribution"], builds)
            self.assertEqual(snapshot["quality"]["excluded_from_statistics"], 1)
            self.assertEqual(
                vivhite["quality"]["excluded_from_statistics"], 2)

    def test_old_zip_catalog_hydrates_choices_and_still_filters_exclusions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-profile-card-archive-") as temp:
            root = Path(temp)
            archive_path = root / "archive" / "legacy.zip"
            archive_path.parent.mkdir(parents=True)
            archived = {
                "archived-auto.json": _run(
                    "ARCHIVED-AUTO", 1, 12, ["ARCHIVE_ONLY"],
                    final_deck=_deck("STRIKE", "ARCHIVE_DECK_ONLY")),
                "archived-human.json": _run(
                    "ARCHIVED-HUMAN", 2, 99, ["MUST_NOT_COUNT"],
                    human_assisted=True,
                    final_deck=_deck("MUST_NOT_COUNT")),
            }
            raw_by_name = {
                name: json.dumps(data, ensure_ascii=False).encode("utf-8")
                for name, data in archived.items()
            }
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, raw in raw_by_name.items():
                    archive.writestr(f"runs/{name}", raw)

            rows = []
            for name, data in archived.items():
                raw = raw_by_name[name]
                row = compact_knowledge._run_summary(
                    data, name, len(raw), hashlib.sha256(raw).hexdigest())
                # Simulate a catalog written before card_picks was summarized.
                row.pop("card_picks", None)
                row.pop("final_deck", None)
                row["storage"] = {
                    "kind": "zip", "archive": "archive/legacy.zip",
                    "member": f"runs/{name}",
                }
                rows.append(row)
            catalog = root / "archive" / "run_catalog.jsonl"
            catalog.write_text(
                "\n".join([
                    json.dumps({"schema_version": 1}),
                    *(json.dumps(row, ensure_ascii=False) for row in rows),
                ]) + "\n",
                encoding="utf-8",
            )
            active = _run(
                "ACTIVE-AUTO", 3, 18, ["ACTIVE_ONLY"],
                final_deck=_deck("STRIKE", "ACTIVE_DECK_ONLY"))
            _write_json(root / "runs" / "active.json", active)

            snapshot = FloorStatsProvider(root, refresh_interval=0).snapshot()
            choices = snapshot["profiles"]["ironclad"]["card_choices"]
            self.assertEqual(choices["eligible_runs"], 2)
            self.assertEqual(choices["evidence_runs"], 2)
            self.assertEqual(choices["missing_evidence_runs"], 0)
            self.assertEqual(set(choices["cards"]), {"ARCHIVE_ONLY", "ACTIVE_ONLY"})
            self.assertNotIn("MUST_NOT_COUNT", choices["cards"])
            self.assertEqual(choices["errors"], [])
            decks = snapshot["profiles"]["ironclad"]["final_deck_evidence"]
            self.assertEqual(decks["evidence_runs"], 2)
            self.assertEqual(
                set(decks["cards"]),
                {"STRIKE", "ARCHIVE_DECK_ONLY", "ACTIVE_DECK_ONLY"})
            self.assertNotIn("MUST_NOT_COUNT", decks["cards"])
            self.assertFalse(snapshot["stale"])

    def test_compaction_summary_preserves_picks_and_true_final_deck(self) -> None:
        data = _run(
            "SUMMARY", 1, 7, ["BASH", "BASH", "INFLAME"],
            final_deck=[
                {"card_id": "STRIKE", "upgraded": False, "name": "Strike"},
                {"card_id": "BASH", "upgraded": True, "name": "Bash+"},
                {"card_id": "BASH", "upgraded": False, "name": "Bash"},
            ])
        raw = json.dumps(data).encode("utf-8")
        summary = compact_knowledge._run_summary(
            data, "summary.json", len(raw), hashlib.sha256(raw).hexdigest())
        self.assertEqual(summary["card_picks"], ["BASH", "BASH", "INFLAME"])
        self.assertEqual(
            [(card["card_id"], card["upgraded"])
             for card in summary["final_deck"]],
            [("STRIKE", False), ("BASH", True), ("BASH", False)])

        old = _run("OLD", 2, 8, None)
        old_raw = json.dumps(old).encode("utf-8")
        old_summary = compact_knowledge._run_summary(
            old, "old.json", len(old_raw),
            hashlib.sha256(old_raw).hexdigest())
        self.assertNotIn("card_picks", old_summary)
        self.assertNotIn("final_deck", old_summary)

        explicit_empty = _run("EMPTY", 3, 9, [], final_deck=[])
        empty_raw = json.dumps(explicit_empty).encode("utf-8")
        empty_summary = compact_knowledge._run_summary(
            explicit_empty, "empty.json", len(empty_raw),
            hashlib.sha256(empty_raw).hexdigest())
        self.assertEqual(empty_summary["card_picks"], [])
        self.assertEqual(empty_summary["final_deck"], [])


if __name__ == "__main__":
    unittest.main()
