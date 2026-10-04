"""Legacy repair commits once and uses the autonomous closed-run population."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))
import knowledge


class KnowledgeHistoryRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascend-history-repair-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "runs").mkdir()
        self.stats = copy.deepcopy(knowledge.DEFAULT_STATS)
        self.stats["global"].update(runs=10, floors_total=100, floor_sum_raw=100)
        self.progression = copy.deepcopy(knowledge.DEFAULT_PROGRESSION)
        self.progression["runs_by_ascension"] = {"0": 10, "1": 4}
        self._write_initial()

    def _write_initial(self):
        knowledge._save_json(self.root / "stats.json", self.stats)
        knowledge._save_json(self.root / "progression.json", self.progression)

    def _read(self, filename):
        return json.loads((self.root / filename).read_text(encoding="utf-8"))

    def _run(self, run_id="phantom", **values):
        payload = {"run_id": run_id, "floor": 7, "ascension": 0,
                   "victory": False, "decisions": []}
        payload.update(values)
        knowledge._save_json(self.root / "runs" / f"20260101-000000_{run_id}.json",
                             payload)

    def _assert_repaired(self):
        stats = self._read("stats.json")
        self.assertEqual(stats["global"]["runs"], 9)
        self.assertEqual(stats["global"]["floor_sum_raw"], 93)
        self.assertEqual(stats["global"]["floors_total"], 93)
        self.assertTrue(stats["phantom_repair_v1"])
        self.assertNotIn("phantom_repair_pending_progression_v1", stats)
        self.assertEqual(self._read("progression.json")["runs_by_ascension"],
                         {"0": 9, "1": 4})

    def test_consecutive_cold_loads_apply_correction_once(self):
        self._run()
        knowledge.Knowledge(self.root)
        knowledge.Knowledge(self.root)
        self._assert_repaired()

    def test_failed_progression_write_replays_target_without_double_subtraction(self):
        self._run()
        save = knowledge._save_json

        def fail_progression(path, data):
            if path == self.root / "progression.json":
                raise PermissionError("progression busy")
            return save(path, data)

        with mock.patch.object(knowledge, "_save_json", fail_progression):
            with self.assertRaises(PermissionError):
                knowledge.Knowledge(self.root)
        stats = self._read("stats.json")
        self.assertEqual(stats["global"]["runs"], 9)
        self.assertEqual(stats["phantom_repair_pending_progression_v1"],
                         {"0": 9, "1": 4})
        knowledge.Knowledge(self.root)
        self._assert_repaired()

    def test_failed_cleanup_replays_already_written_progression_idempotently(self):
        self._run()
        save = knowledge._save_json
        stats_writes = 0

        def fail_cleanup(path, data):
            nonlocal stats_writes
            if path == self.root / "stats.json":
                stats_writes += 1
                if stats_writes == 2:
                    raise PermissionError("cleanup busy")
            return save(path, data)

        with mock.patch.object(knowledge, "_save_json", fail_cleanup):
            with self.assertRaises(PermissionError):
                knowledge.Knowledge(self.root)
        self.assertEqual(self._read("progression.json")["runs_by_ascension"]["0"], 9)
        knowledge.Knowledge(self.root)
        self._assert_repaired()

    def test_failed_first_commit_leaves_disk_counts_unchanged(self):
        self._run()
        with mock.patch.object(knowledge, "_save_json", side_effect=PermissionError("busy")):
            with self.assertRaises(PermissionError):
                knowledge.Knowledge(self.root)
        self.assertEqual(self._read("stats.json")["global"]["runs"], 10)
        knowledge.Knowledge(self.root)
        self._assert_repaired()

    def test_existing_legacy_marker_never_recalculates_historical_counts(self):
        self.stats["phantom_repair_v1"] = True
        self._write_initial()
        self._run()
        knowledge.Knowledge(self.root)
        self.assertEqual(self._read("stats.json")["global"]["runs"], 10)
        self.assertEqual(self._read("progression.json")["runs_by_ascension"]["0"], 10)

    def test_active_or_excluded_zero_decision_runs_are_not_legacy_phantoms(self):
        self._run("active", in_progress=True)
        self._run("human", human_assisted=True)
        self._run("excluded", excluded_from_learning=True)
        knowledge.Knowledge(self.root)
        self.assertEqual(self._read("stats.json")["global"]["runs"], 10)
        self.assertEqual(self._read("progression.json")["runs_by_ascension"]["0"], 10)

    def test_excluded_run_recovery_defers_legacy_repair_and_preserves_exact_baseline(self):
        first = knowledge.Knowledge(self.root, repair_phantoms=False)
        first.begin_run_learning("mixed")
        first.exclude_run_learning("mixed")
        baseline = self._read("stats.json")
        self._run()
        recovered = knowledge.Knowledge(self.root)
        self.assertTrue(recovered.run_learning_is_excluded("mixed"))
        self.assertEqual(self._read("stats.json"), baseline)
        self.assertEqual(self._read("progression.json")["runs_by_ascension"]["0"], 10)

    def test_raw_maximum_migration_uses_closed_autonomous_active_and_catalog_evidence(self):
        self.stats["global"].pop("best_floor_raw")
        self.stats["global"]["best_floor"] = 10
        self._write_initial()
        self._run("good", floor=10, decisions=[{"floor": 10, "screen": "GAME_OVER"}])
        self._run("human", floor=99, human_assisted=True,
                  decisions=[{"floor": 99, "screen": "GAME_OVER"}])
        self._run("pending", floor=98, in_progress=True, victory=True,
                  decisions=[{"floor": 98, "screen": "GAME_OVER"}])
        archive = self.root / "archive"
        archive.mkdir()
        rows = [{"schema_version": 1},
                {"file": "excluded.json", "floor": 97, "decisions": 1,
                 "excluded_from_learning": True},
                {"file": "pending.json", "floor": 96, "decisions": 1,
                 "in_progress": True, "last_screen": "GAME_OVER"},
                {"file": "good.json", "floor": 20, "decisions": 1}]
        (archive / "run_catalog.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        store = knowledge.Knowledge(self.root, repair_phantoms=False)
        self.assertEqual(store.stats["global"]["best_floor_raw"], 20)

    def test_phantom_repair_recomputed_maximum_excludes_human_and_pending(self):
        self._run()
        self._run("good", floor=10, decisions=[{"floor": 10, "screen": "GAME_OVER"}])
        self._run("human", floor=99, human_assisted=True,
                  decisions=[{"floor": 99, "screen": "GAME_OVER"}])
        self._run("pending", floor=98, in_progress=True,
                  decisions=[{"floor": 98, "screen": "GAME_OVER"}])
        store = knowledge.Knowledge(self.root)
        self.assertEqual(store.stats["global"]["best_floor_raw"], 10)


if __name__ == "__main__":
    unittest.main()
