"""Profile floor statistics and dashboard identity contract."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from floor_stats import FloorStatsProvider  # noqa: E402
from live_dashboard import LiveDashboardPublisher  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _run(run_id: str, number: int, floor: int, character_id: str | None) -> dict:
    value = {
        "run_id": run_id,
        "run_number": number,
        "started_at": f"2026-08-30 10:{number:02d}:00",
        "ascension": 0,
        "victory": False,
        "in_progress": False,
        "floor": floor,
        "decisions": [{"screen": "COMBAT", "floor": floor,
                       "action": "end_turn"}],
    }
    if character_id is not None:
        value["character_id"] = character_id
    return value


class ProfileFloorStatsTests(unittest.TestCase):
    def test_legacy_root_is_ironclad_and_uses_raw_floor_counters(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-profile-legacy-") as temp:
            root = Path(temp)
            _write_json(root / "stats.json", {
                "global": {
                    "runs": 2,
                    "wins": 1,
                    # Deliberately incompatible learning scores: neither may be
                    # rendered as a real floor.
                    "floors_total": 1030.0,
                    "best_floor": 999,
                    "floor_sum_raw": 30.0,
                    "best_floor_raw": 20,
                },
            })

            snapshot = FloorStatsProvider(root, refresh_interval=0).snapshot()

            ironclad = snapshot["profiles"]["ironclad"]
            vivhite = snapshot["profiles"]["vivhite"]
            self.assertEqual(ironclad["profile_id"], "ironclad")
            self.assertEqual(ironclad["character_id"], "IRONCLAD")
            self.assertEqual(vivhite["profile_id"], "vivhite")
            self.assertEqual(
                vivhite["character_id"], "VIVHITE_CHARACTER_VIVHITE_CHARACTER")
            self.assertEqual(ironclad["lifetime"]["mean_floor"], 15.0)
            self.assertEqual(ironclad["lifetime"]["best_floor"], 20)
            self.assertEqual(ironclad["quality"]["source"], "aggregate_raw")
            self.assertEqual(vivhite["lifetime"]["runs"], 0)
            self.assertIsNone(snapshot["profile_comparison"]["rolling_mean_ratio"])

    def test_profile_roots_are_independent_and_publish_rolling_ratio(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-profile-split-") as temp:
            root = Path(temp)
            _write_json(root / "stats.json", {
                "global": {
                    "runs": 2, "wins": 0,
                    "floors_total": 900.0, "best_floor": 900,
                    "floor_sum_raw": 30.0, "best_floor_raw": 20,
                },
            })
            vivhite_root = root / "profiles" / "vivhite"
            _write_json(vivhite_root / "stats.json", {
                "global": {
                    "runs": 2, "wins": 1,
                    "floors_total": 950.0, "best_floor": 950,
                    "floor_sum_raw": 45.0, "best_floor_raw": 30,
                },
            })
            for data in (_run("I-OLD", 1, 10, None),
                         _run("I-NEW", 2, 20, "IRONCLAD")):
                _write_json(root / "runs" / f"{data['run_id']}.json", data)
            for data in (
                _run("V-OLD", 3, 15, None),
                _run("V-NEW", 4, 30, "VIVHITE_CHARACTER_VIVHITE_CHARACTER"),
            ):
                _write_json(vivhite_root / "runs" / f"{data['run_id']}.json", data)

            snapshot = FloorStatsProvider(
                root, refresh_interval=0, rolling_window=2).snapshot({
                    "run_id": "LIVE-V", "run_number": 5, "floor": 4,
                    "character_id": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
                })

            ironclad = snapshot["profiles"]["ironclad"]
            vivhite = snapshot["profiles"]["vivhite"]
            self.assertEqual(ironclad["lifetime"]["mean_floor"], 15.0)
            self.assertEqual(ironclad["lifetime"]["best_floor"], 20)
            self.assertEqual(vivhite["lifetime"]["mean_floor"], 22.5)
            self.assertEqual(vivhite["lifetime"]["best_floor"], 30)
            self.assertEqual(ironclad["quality"]["source"], "aggregate_raw")
            self.assertEqual(vivhite["quality"]["source"], "aggregate_raw")
            self.assertEqual(ironclad["rolling_mean"], 15.0)
            self.assertEqual(vivhite["rolling_mean"], 22.5)
            comparison = snapshot["profile_comparison"]
            self.assertEqual(comparison["rolling_mean_ratio"], 1.5)
            self.assertEqual(comparison["vivhite_to_ironclad_ratio"], 1.5)
            self.assertEqual(snapshot["active_profile"], "vivhite")
            self.assertEqual(snapshot["current"]["profile_id"], "vivhite")
            self.assertEqual(snapshot["lifetime"], vivhite["lifetime"])
            self.assertEqual(snapshot["recent"], vivhite["recent"])
            self.assertEqual(snapshot["previous"], vivhite["previous"])
            self.assertEqual(snapshot["delta_mean"], vivhite["delta_mean"])
            self.assertEqual(snapshot["trend"], vivhite["trend"])

            ironclad_snapshot = FloorStatsProvider(
                root, refresh_interval=0, rolling_window=2).snapshot({
                    "run_id": "LIVE-I", "run_number": 6, "floor": 5,
                    "profile_id": "ironclad", "character_id": "IRONCLAD",
                })
            self.assertEqual(ironclad_snapshot["active_profile"], "ironclad")
            self.assertEqual(
                ironclad_snapshot["lifetime"],
                ironclad_snapshot["profiles"]["ironclad"]["lifetime"],
            )
            self.assertEqual(
                ironclad_snapshot["recent"],
                ironclad_snapshot["profiles"]["ironclad"]["recent"],
            )

    def test_vivhite_headline_never_falls_back_to_1228_ironclad_runs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-profile-1228-regression-") as temp:
            root = Path(temp)
            ironclad_floors = list(range(14, 34))
            _write_json(root / "stats.json", {
                "global": {
                    "runs": 1228, "wins": 0,
                    "floors_total": 22472.4, "best_floor": 48,
                    "floor_sum_raw": 22472.4, "best_floor_raw": 48,
                },
            })
            for number, floor in enumerate(ironclad_floors, 1):
                data = _run(f"I-{number}", number, floor, "IRONCLAD")
                _write_json(root / "runs" / f"i-{number}.json", data)

            # Even a misplaced tagged row in the legacy root must not become
            # Vivhite history.  Vivhite owns only profiles/vivhite.
            misplaced = _run(
                "ROOT-VIVHITE-MUST-NOT-LEAK", 100, 99,
                "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
            )
            _write_json(root / "runs" / "root-vivhite.json", misplaced)

            provider = FloorStatsProvider(root, refresh_interval=0)
            vivhite_current = {
                "run_id": "LIVE-V", "run_number": 1, "floor": 3,
                "profile_id": "vivhite",
                "character_id": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
            }
            empty = provider.snapshot(vivhite_current)

            self.assertEqual(empty["active_profile"], "vivhite")
            self.assertEqual(empty["lifetime"]["runs"], 0)
            self.assertIsNone(empty["lifetime"]["mean_floor"])
            self.assertIsNone(empty["lifetime"]["best_floor"])
            self.assertEqual(empty["recent"]["count"], 0)
            self.assertIsNone(empty["recent"]["mean_floor"])
            self.assertIsNone(empty["recent"]["best_floor"])
            self.assertEqual(empty["profiles"]["ironclad"]["lifetime"]["runs"], 1228)
            self.assertEqual(empty["profiles"]["vivhite"]["lifetime"]["runs"], 0)

            vivhite_root = root / "profiles" / "vivhite"
            _write_json(vivhite_root / "stats.json", {
                "global": {
                    "runs": 1, "wins": 0,
                    "floors_total": 7.0, "best_floor": 7,
                    "floor_sum_raw": 7.0, "best_floor_raw": 7,
                },
            })
            _write_json(
                vivhite_root / "runs" / "v-1.json",
                _run("V-1", 1, 7, "VIVHITE_CHARACTER_VIVHITE_CHARACTER"),
            )
            one_vivhite = provider.snapshot(vivhite_current, force=True)
            self.assertEqual(one_vivhite["lifetime"]["runs"], 1)
            self.assertEqual(one_vivhite["lifetime"]["mean_floor"], 7.0)
            self.assertEqual(one_vivhite["lifetime"]["best_floor"], 7)
            self.assertEqual(one_vivhite["recent"]["count"], 1)
            self.assertEqual(one_vivhite["recent"]["mean_floor"], 7.0)
            self.assertEqual(one_vivhite["recent"]["best_floor"], 7)

            ironclad = provider.snapshot({
                "run_id": "LIVE-I", "run_number": 1229, "floor": 4,
                "profile_id": "ironclad", "character_id": "IRONCLAD",
            })
            self.assertEqual(ironclad["active_profile"], "ironclad")
            self.assertEqual(ironclad["lifetime"]["runs"], 1228)
            self.assertEqual(ironclad["lifetime"]["mean_floor"], 18.3)
            self.assertEqual(ironclad["lifetime"]["best_floor"], 48)
            self.assertEqual(ironclad["recent"]["count"], 20)
            self.assertEqual(ironclad["recent"]["mean_floor"], 23.5)
            self.assertEqual(ironclad["recent"]["best_floor"], 33)

    def test_vivhite_never_falls_back_to_learning_score_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-profile-raw-only-") as temp:
            root = Path(temp)
            vivhite_root = root / "profiles" / "vivhite"
            _write_json(vivhite_root / "stats.json", {
                "global": {
                    "runs": 1, "wins": 1,
                    "floors_total": 999.0, "best_floor": 999,
                },
            })
            data = _run("V-EVIDENCE", 1, 12, None)
            _write_json(vivhite_root / "runs" / "v-evidence.json", data)

            snapshot = FloorStatsProvider(root, refresh_interval=0).snapshot()
            vivhite = snapshot["profiles"]["vivhite"]

            self.assertEqual(vivhite["lifetime"]["mean_floor"], 12.0)
            self.assertEqual(vivhite["lifetime"]["best_floor"], 12)
            self.assertEqual(vivhite["quality"]["source"], "records")

    def test_live_dashboard_exports_raw_character_and_canonical_profile(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-profile-dashboard-") as temp:
            publisher = LiveDashboardPublisher(Path(temp), "profile-session")
            publisher.observe({
                "screen": "COMBAT",
                "run_id": "live-vivhite",
                "run": {
                    "character_id": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
                    "floor": 7,
                    "ascension": 1,
                },
            }, run_number=9)
            publisher.close(timeout=2.0)

            payload = json.loads(publisher.path.read_text(encoding="utf-8"))
            run = payload["run"]
            self.assertEqual(
                run["character_id"], "VIVHITE_CHARACTER_VIVHITE_CHARACTER")
            self.assertEqual(run["profile_id"], "vivhite")
            self.assertEqual(run["profile_label"], "Vivhite")


if __name__ == "__main__":
    unittest.main()
