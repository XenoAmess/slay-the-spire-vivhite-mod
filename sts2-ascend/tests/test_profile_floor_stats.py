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
import compact_knowledge  # noqa: E402
from live_dashboard import LiveDashboardPublisher  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _run(run_id: str, number: int, floor: int, character_id: str | None, *,
         in_progress: bool = False, game_over: bool = False,
         human_assisted: bool | None = None,
         excluded_from_learning: bool | None = None) -> dict:
    decisions = [{"screen": "COMBAT", "floor": floor,
                  "action": "end_turn"}]
    if game_over:
        decisions.append({"screen": "GAME_OVER", "floor": floor,
                          "reason": "defeat"})
    value = {
        "run_id": run_id,
        "run_number": number,
        "started_at": f"2026-08-30 10:{number:02d}:00",
        "ascension": 0,
        "victory": False,
        "in_progress": in_progress,
        "floor": floor,
        "decisions": decisions,
    }
    if character_id is not None:
        value["character_id"] = character_id
    if human_assisted is not None:
        value["human_assisted"] = human_assisted
    if excluded_from_learning is not None:
        value["excluded_from_learning"] = excluded_from_learning
    return value


class ProfileFloorStatsTests(unittest.TestCase):
    @staticmethod
    def _write_stats(root: Path, floors: list[int]) -> None:
        _write_json(root / "stats.json", {
            "global": {
                "runs": len(floors),
                "wins": 0,
                "floors_total": float(sum(floors)),
                "best_floor": max(floors, default=0),
                "floor_sum_raw": float(sum(floors)),
                "best_floor_raw": max(floors, default=0),
            },
        })

    def test_human_assisted_runs_never_enter_available_profile_statistics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-profile-assisted-stats-") as temp:
            root = Path(temp)
            vivhite_root = root / "profiles" / "vivhite"
            self._write_stats(root, [10, 14])
            self._write_stats(vivhite_root, [20, 28])

            runs = (
                (root, _run("I-LEGACY", 1, 10, None)),
                (root, _run("I-AUTO", 2, 14, "IRONCLAD")),
                (root, _run(
                    "I-HUMAN-GAME-OVER", 3, 99, "IRONCLAD",
                    in_progress=True, game_over=True, human_assisted=True,
                )),
                (root, _run(
                    "I-EXCLUDED", 4, 98, "IRONCLAD",
                    game_over=True, excluded_from_learning=True,
                )),
                (vivhite_root, _run(
                    "V-LEGACY", 1, 20, "VIVHITE_CHARACTER_VIVHITE_CHARACTER")),
                (vivhite_root, _run(
                    "V-AUTO", 2, 28, "VIVHITE_CHARACTER_VIVHITE_CHARACTER")),
                (vivhite_root, _run(
                    "V-HUMAN-GAME-OVER", 3, 97,
                    "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
                    in_progress=True, game_over=True, human_assisted=True,
                )),
                (vivhite_root, _run(
                    "V-EXCLUDED", 4, 96,
                    "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
                    game_over=True, excluded_from_learning=True,
                )),
            )
            for run_root, data in runs:
                _write_json(run_root / "runs" / f"{data['run_id']}.json", data)

            snapshot = FloorStatsProvider(
                root, refresh_interval=0, rolling_window=2).snapshot()
            ironclad = snapshot["profiles"]["ironclad"]
            vivhite = snapshot["profiles"]["vivhite"]

            self.assertEqual(ironclad["lifetime"]["runs"], 2)
            self.assertEqual(ironclad["lifetime"]["mean_floor"], 12.0)
            self.assertEqual(ironclad["recent"]["count"], 2)
            self.assertEqual(
                [row["run_id"] for row in ironclad["trend"]],
                ["I-LEGACY", "I-AUTO"],
            )
            self.assertEqual(vivhite["lifetime"]["runs"], 2)
            self.assertEqual(vivhite["lifetime"]["mean_floor"], 24.0)
            self.assertEqual(vivhite["recent"]["count"], 2)
            self.assertEqual(
                [row["run_id"] for row in vivhite["trend"]],
                ["V-LEGACY", "V-AUTO"],
            )
            self.assertEqual(
                snapshot["profile_comparison"]["rolling_mean_ratio"], 2.0)
            self.assertEqual(snapshot["quality"]["excluded_from_statistics"], 2)
            self.assertEqual(
                snapshot["profiles"]["vivhite"]["quality"]
                ["excluded_from_statistics"], 2)
            for run_root, data in runs:
                self.assertTrue(
                    (run_root / "runs" / f"{data['run_id']}.json").is_file())

    def test_human_assisted_runs_never_enter_record_fallback_statistics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-profile-assisted-fallback-") as temp:
            root = Path(temp)
            vivhite_root = root / "profiles" / "vivhite"
            runs = (
                (root, _run("I-LEGACY", 1, 11, None)),
                (root, _run(
                    "I-HUMAN-GAME-OVER", 2, 91, "IRONCLAD",
                    in_progress=True, game_over=True, human_assisted=True,
                )),
                (vivhite_root, _run(
                    "V-LEGACY", 1, 22, "VIVHITE_CHARACTER_VIVHITE_CHARACTER")),
                (vivhite_root, _run(
                    "V-EXCLUDED-GAME-OVER", 2, 92,
                    "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
                    in_progress=True, game_over=True,
                    excluded_from_learning=True,
                )),
            )
            for run_root, data in runs:
                _write_json(run_root / "runs" / f"{data['run_id']}.json", data)

            snapshot = FloorStatsProvider(
                root, refresh_interval=0, rolling_window=2).snapshot()
            ironclad = snapshot["profiles"]["ironclad"]
            vivhite = snapshot["profiles"]["vivhite"]

            self.assertEqual(ironclad["quality"]["source"], "records")
            self.assertEqual(ironclad["lifetime"], {
                "runs": 1, "wins": 0, "win_rate": 0.0,
                "mean_floor": 11.0, "best_floor": 11,
            })
            self.assertEqual([row["run_id"] for row in ironclad["trend"]],
                             ["I-LEGACY"])
            self.assertEqual(vivhite["quality"]["source"], "records")
            self.assertEqual(vivhite["lifetime"], {
                "runs": 1, "wins": 0, "win_rate": 0.0,
                "mean_floor": 22.0, "best_floor": 22,
            })
            self.assertEqual([row["run_id"] for row in vivhite["trend"]],
                             ["V-LEGACY"])
            comparison = snapshot["profile_comparison"]
            self.assertEqual(comparison["rolling_mean_ratio"], 2.0)
            self.assertEqual(comparison["vivhite_to_ironclad_ratio"], 2.0)

    def test_real_compaction_catalog_keeps_exclusions_after_takeover(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-profile-compact-exclusion-") as temp:
            root = Path(temp)
            vivhite_root = root / "profiles" / "vivhite"
            _write_json(vivhite_root / "policy.json", {})

            ironclad_auto = _run("I-AUTO", 1, 10, None)
            ironclad_assisted = _run(
                "I-HUMAN", 2, 9, "IRONCLAD",
                game_over=True, human_assisted=True,
            )
            vivhite_auto = _run(
                "V-AUTO", 1, 20, "VIVHITE_CHARACTER_VIVHITE_CHARACTER")
            vivhite_excluded = _run(
                "V-EXCLUDED", 2, 19,
                "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
                game_over=True, excluded_from_learning=True,
            )
            fixtures = (
                (root, "i-auto.json", ironclad_auto),
                (root, "i-human.json", ironclad_assisted),
                (vivhite_root, "v-auto.json", vivhite_auto),
                (vivhite_root, "v-excluded.json", vivhite_excluded),
            )
            archived_raw: dict[tuple[Path, str], bytes] = {}
            for run_root, filename, data in fixtures:
                path = run_root / "runs" / filename
                _write_json(path, data)
                if data.get("human_assisted") or data.get("excluded_from_learning"):
                    archived_raw[(run_root, filename)] = path.read_bytes()

            options = compact_knowledge.CompactionOptions(
                keep_recent=0,
                deep_floor=999,
                keep_longest=0,
                keep_largest=0,
                keep_floor_representatives=False,
                keep_lessons=0,
                keep_meta_reviews=0,
            )
            result = compact_knowledge.apply_compaction(root, options)

            self.assertEqual(result["archived_runs"], 2)
            for (run_root, filename), raw in archived_raw.items():
                self.assertFalse((run_root / "runs" / filename).exists())
                self.assertEqual(
                    compact_knowledge.read_run_evidence(run_root, filename), raw)

            def catalog_by_run(run_root: Path) -> dict[str, dict]:
                rows = [
                    json.loads(line)
                    for line in (run_root / compact_knowledge.CATALOG_REL)
                    .read_text(encoding="utf-8").splitlines()[1:]
                ]
                return {str(row.get("run_id")): row for row in rows}

            ironclad_catalog = catalog_by_run(root)
            vivhite_catalog = catalog_by_run(vivhite_root)
            self.assertTrue(ironclad_catalog["I-HUMAN"]["human_assisted"])
            self.assertTrue(
                vivhite_catalog["V-EXCLUDED"]["excluded_from_learning"])
            self.assertNotIn("human_assisted", ironclad_catalog["I-AUTO"])
            self.assertNotIn(
                "excluded_from_learning", vivhite_catalog["V-AUTO"])
            self.assertEqual(
                ironclad_catalog["I-HUMAN"]["storage"]["kind"], "zip")
            self.assertEqual(
                vivhite_catalog["V-EXCLUDED"]["storage"]["kind"], "zip")

            snapshot = FloorStatsProvider(
                root, refresh_interval=0, rolling_window=2).snapshot()
            ironclad = snapshot["profiles"]["ironclad"]
            vivhite = snapshot["profiles"]["vivhite"]

            self.assertEqual(ironclad["quality"]["source"], "records")
            self.assertEqual(ironclad["lifetime"], {
                "runs": 1, "wins": 0, "win_rate": 0.0,
                "mean_floor": 10.0, "best_floor": 10,
            })
            self.assertEqual(ironclad["recent"]["count"], 1)
            self.assertEqual(ironclad["recent"]["mean_floor"], 10.0)
            self.assertEqual(ironclad["recent"]["best_floor"], 10)
            self.assertEqual(
                [row["run_id"] for row in ironclad["trend"]], ["I-AUTO"])
            self.assertEqual(ironclad["rolling_mean"], 10.0)
            self.assertEqual(
                ironclad["quality"]["excluded_from_statistics"], 1)

            self.assertEqual(vivhite["quality"]["source"], "records")
            self.assertEqual(vivhite["lifetime"], {
                "runs": 1, "wins": 0, "win_rate": 0.0,
                "mean_floor": 20.0, "best_floor": 20,
            })
            self.assertEqual(vivhite["recent"]["count"], 1)
            self.assertEqual(vivhite["recent"]["mean_floor"], 20.0)
            self.assertEqual(vivhite["recent"]["best_floor"], 20)
            self.assertEqual(
                [row["run_id"] for row in vivhite["trend"]], ["V-AUTO"])
            self.assertEqual(vivhite["rolling_mean"], 20.0)
            self.assertEqual(
                vivhite["quality"]["excluded_from_statistics"], 1)

            comparison = snapshot["profile_comparison"]
            self.assertEqual(comparison["rolling_means"], {
                "ironclad": 10.0,
                "vivhite": 20.0,
            })
            self.assertEqual(comparison["rolling_mean_ratio"], 2.0)
            self.assertEqual(comparison["vivhite_to_ironclad_ratio"], 2.0)
            self.assertEqual(snapshot["lifetime"], ironclad["lifetime"])
            self.assertEqual(snapshot["recent"], ironclad["recent"])
            self.assertEqual(snapshot["trend"], ironclad["trend"])

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
                _run("V-OLD", 3, 15, "VIVHITE_CHARACTER_VIVHITE_CHARACTER"),
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
            data = _run(
                "V-EVIDENCE", 1, 12, "VIVHITE_CHARACTER_VIVHITE_CHARACTER")
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
