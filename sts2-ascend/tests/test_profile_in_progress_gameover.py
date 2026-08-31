"""Regression coverage for half-written profile runs with GAME_OVER residue."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from floor_stats import FloorStatsProvider  # noqa: E402


VIVHITE = "VIVHITE_CHARACTER_VIVHITE_CHARACTER"
A_CARD = "VIVHITE_CARD_AXIOM_RING"
B_CARD = "VIVHITE_CARD_RECURRENT_STARLIGHT"
BASE_CARD = "VIVHITE_CARD_LUMINOUS_PROJECTION"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _run(
        run_id: str, number: int, floor: int, *, profile_id: str,
        in_progress: bool, game_over: bool = True,
        picks: list[str] | None = None,
        final_deck: list[dict] | None = None) -> dict:
    character_id = VIVHITE if profile_id == "vivhite" else "IRONCLAD"
    decisions = [{"screen": "COMBAT", "floor": floor,
                  "action": "end_turn"}]
    if game_over:
        decisions.append({"screen": "GAME_OVER", "floor": floor,
                          "reason": "defeat"})
    value = {
        "run_id": run_id,
        "run_number": number,
        "started_at": f"2026-08-31 18:{number:02d}:00",
        "profile_id": profile_id,
        "character_id": character_id,
        "ascension": 0,
        "victory": False,
        "in_progress": in_progress,
        "floor": floor,
        "decisions": decisions,
    }
    if picks is not None:
        value["attribution_tags"] = [["card_pick", card] for card in picks]
    if final_deck is not None:
        value["final_deck"] = final_deck
    return value


def _deck(*card_ids: str) -> list[dict]:
    return [{"card_id": card_id, "upgraded": False}
            for card_id in card_ids]


def _profile_root(root: Path, profile_id: str) -> Path:
    return (root / "profiles" / "vivhite"
            if profile_id == "vivhite" else root)


def _write_zip_catalog(profile_root: Path, runs: list[dict]) -> None:
    archive_path = profile_root / "archive" / "profile-runs.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"schema_version": 1, "description": "test profile archive"}]
    with zipfile.ZipFile(
            archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for data in runs:
            filename = f"{data['run_id']}.json"
            member = f"runs/{filename}"
            raw = json.dumps(
                data, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            archive.writestr(member, raw)
            decisions = [row for row in data["decisions"]
                         if isinstance(row, dict)]
            rows.append({
                "file": filename,
                "run_id": data["run_id"],
                "run_number": data["run_number"],
                "started_at": data["started_at"],
                "profile_id": data["profile_id"],
                "character_id": data["character_id"],
                "ascension": data["ascension"],
                "victory": data["victory"],
                "in_progress": data["in_progress"],
                "floor": data["floor"],
                "decisions": len(decisions),
                "last_screen": decisions[-1]["screen"],
                "phantom_candidate": False,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "storage": {
                    "kind": "zip",
                    "archive": "archive/profile-runs.zip",
                    "member": member,
                },
            })
    catalog = profile_root / "archive" / "run_catalog.jsonl"
    catalog.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _assert_only_terminal(
        case: unittest.TestCase, profile: dict, *, floor: int,
        accepted_card: str, rejected_card: str) -> None:
    case.assertEqual(profile["lifetime"]["runs"], 1)
    case.assertEqual(profile["lifetime"]["mean_floor"], float(floor))
    case.assertEqual(profile["lifetime"]["best_floor"], floor)
    case.assertEqual(profile["recent"]["count"], 1)
    case.assertEqual(profile["recent"]["mean_floor"], float(floor))
    case.assertEqual(profile["recent"]["best_floor"], floor)
    case.assertEqual([row["floor"] for row in profile["trend"]], [floor])
    case.assertIn(accepted_card, profile["card_choices"]["cards"])
    case.assertNotIn(rejected_card, profile["card_choices"]["cards"])
    case.assertIn(accepted_card, profile["final_deck_evidence"]["cards"])
    case.assertNotIn(rejected_card, profile["final_deck_evidence"]["cards"])


class ProfileInProgressGameOverTests(unittest.TestCase):
    def test_active_game_over_residue_stays_current_but_never_counts(self) -> None:
        for profile_id, terminal_card, residue_card in (
                ("ironclad", "BASH", "IRONCLAD_RESIDUE"),
                ("vivhite", A_CARD, B_CARD)):
            with self.subTest(profile_id=profile_id), tempfile.TemporaryDirectory(
                    prefix=f"ascend-active-{profile_id}-") as temp:
                root = Path(temp) / "knowledge"
                profile_root = _profile_root(root, profile_id)
                terminal = _run(
                    f"{profile_id}-terminal", 1, 10,
                    profile_id=profile_id, in_progress=False,
                    game_over=False, picks=[terminal_card],
                    final_deck=_deck(terminal_card),
                )
                residue = _run(
                    f"{profile_id}-residue", 2, 900,
                    profile_id=profile_id, in_progress=True,
                    game_over=True, picks=[residue_card],
                    final_deck=_deck(residue_card),
                )
                _write_json(
                    profile_root / "runs" / "terminal.json", terminal)
                _write_json(
                    profile_root / "runs" / "residue.json", residue)

                snapshot = FloorStatsProvider(
                    profile_root, refresh_interval=0, profile_id=profile_id,
                    _discover_profiles=False,
                ).snapshot()
                selected = snapshot["profiles"][profile_id]
                _assert_only_terminal(
                    self, selected, floor=10,
                    accepted_card=terminal_card, rejected_card=residue_card,
                )
                self.assertEqual(snapshot["current"]["run_id"], residue["run_id"])
                self.assertEqual(snapshot["current"]["floor"], 900)
                self.assertEqual(snapshot["quality"]["completed_records"], 1)
                self.assertEqual(snapshot["quality"]["excluded_in_progress"], 1)

    def test_zip_catalog_residue_is_filtered_for_both_profiles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-catalog-profile-") as temp:
            root = Path(temp) / "knowledge"
            for profile_id, terminal_card, residue_card, floor in (
                    ("ironclad", "BASH", "IRONCLAD_ZIP_RESIDUE", 12),
                    ("vivhite", A_CARD, B_CARD, 22)):
                profile_root = _profile_root(root, profile_id)
                _write_zip_catalog(profile_root, [
                    _run(
                        f"{profile_id}-zip-terminal", 1, floor,
                        profile_id=profile_id, in_progress=False,
                        picks=[terminal_card], final_deck=_deck(terminal_card),
                    ),
                    _run(
                        f"{profile_id}-zip-residue", 2, 800,
                        profile_id=profile_id, in_progress=True,
                        picks=[residue_card], final_deck=_deck(residue_card),
                    ),
                ])

            snapshot = FloorStatsProvider(root, refresh_interval=0).snapshot()
            _assert_only_terminal(
                self, snapshot["profiles"]["ironclad"], floor=12,
                accepted_card="BASH", rejected_card="IRONCLAD_ZIP_RESIDUE",
            )
            _assert_only_terminal(
                self, snapshot["profiles"]["vivhite"], floor=22,
                accepted_card=A_CARD, rejected_card=B_CARD,
            )
            self.assertNotIn(800, [row["floor"] for row in snapshot["trend"]])
            self.assertNotIn(
                800, [row["floor"]
                      for row in snapshot["profiles"]["vivhite"]["trend"]])

    def test_active_duplicate_priority_cannot_reintroduce_residue(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-duplicate-profile-") as temp:
            root = Path(temp) / "knowledge"

            # Ironclad: the live half-written trace is authoritative over an
            # older terminal catalog duplicate, so this run remains current and
            # contributes nothing to any completed view.
            _write_zip_catalog(root, [
                _run(
                    "I-DUP", 1, 60, profile_id="ironclad",
                    in_progress=False, picks=["CATALOG_BASH"],
                    final_deck=_deck("CATALOG_BASH"),
                ),
                _run(
                    "I-NORMAL", 2, 10, profile_id="ironclad",
                    in_progress=False, picks=["BASH"],
                    final_deck=_deck("BASH"),
                ),
            ])
            _write_json(
                root / "runs" / "i-dup-live.json",
                _run(
                    "I-DUP", 3, 900, profile_id="ironclad",
                    in_progress=True, picks=["LIVE_RESIDUE"],
                    final_deck=_deck("LIVE_RESIDUE"),
                ),
            )

            # Vivhite: a completed active trace is authoritative over an old
            # in-progress catalog duplicate.  The run counts, but card/deck
            # evidence may not be borrowed from the rejected ZIP row.
            vivhite_root = root / "profiles" / "vivhite"
            _write_zip_catalog(vivhite_root, [
                _run(
                    "V-DUP", 1, 700, profile_id="vivhite",
                    in_progress=True, picks=[B_CARD],
                    final_deck=_deck(BASE_CARD, B_CARD),
                ),
                _run(
                    "V-NORMAL", 2, 20, profile_id="vivhite",
                    in_progress=False, picks=[A_CARD],
                    final_deck=_deck(BASE_CARD, A_CARD),
                ),
            ])
            _write_json(
                vivhite_root / "runs" / "v-dup-terminal.json",
                _run(
                    "V-DUP", 3, 30, profile_id="vivhite",
                    in_progress=False, game_over=True,
                    picks=None, final_deck=None,
                ),
            )

            snapshot = FloorStatsProvider(root, refresh_interval=0).snapshot()
            ironclad = snapshot["profiles"]["ironclad"]
            self.assertEqual(ironclad["lifetime"]["runs"], 1)
            self.assertEqual(ironclad["lifetime"]["mean_floor"], 10.0)
            self.assertEqual(ironclad["recent"]["count"], 1)
            self.assertNotIn("CATALOG_BASH", ironclad["card_choices"]["cards"])
            self.assertNotIn("LIVE_RESIDUE", ironclad["card_choices"]["cards"])
            self.assertEqual(snapshot["current"]["run_id"], "I-DUP")

            vivhite = snapshot["profiles"]["vivhite"]
            self.assertEqual(vivhite["lifetime"]["runs"], 2)
            self.assertEqual(vivhite["lifetime"]["mean_floor"], 25.0)
            self.assertEqual(vivhite["lifetime"]["best_floor"], 30)
            self.assertEqual(vivhite["recent"]["count"], 2)
            self.assertEqual(
                [row["run_id"] for row in vivhite["trend"]],
                ["V-NORMAL", "V-DUP"],
            )
            self.assertIn(A_CARD, vivhite["card_choices"]["cards"])
            self.assertNotIn(B_CARD, vivhite["card_choices"]["cards"])
            self.assertIn(A_CARD, vivhite["final_deck_evidence"]["cards"])
            self.assertNotIn(B_CARD, vivhite["final_deck_evidence"]["cards"])
            builds = vivhite["build_distribution"]
            self.assertEqual(builds["eligible_runs"], 2)
            self.assertEqual(builds["evidence_runs"], 1)
            self.assertEqual(builds["categories"]["conservation_geometry"]["runs"], 1)
            self.assertEqual(builds["categories"]["recursive_astral"]["runs"], 0)
            self.assertEqual(builds["categories"]["unclassified"]["runs"], 1)


if __name__ == "__main__":
    unittest.main()
