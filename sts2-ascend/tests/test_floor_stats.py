"""Focused tests for raw-floor accounting and dashboard statistics."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from floor_stats import FloorStatsProvider  # noqa: E402
import knowledge  # noqa: E402


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _run(run_id: str, number: int | None, floor: object, *,
         in_progress: bool = False, victory: bool = False,
         game_over: bool = False, decisions: int = 1,
         started_at: str | None = None) -> dict:
    rows = [
        {"screen": "COMBAT", "floor": floor, "action": "end_turn"}
        for _ in range(decisions)
    ]
    if game_over:
        rows.append({"screen": "GAME_OVER", "floor": floor,
                     "reason": "胜利" if victory else "失败"})
    return {
        "run_id": run_id,
        "run_number": number,
        "started_at": started_at or f"2026-01-01 00:{(number or 0) % 60:02d}:00",
        "ascension": 0,
        "victory": victory,
        "in_progress": in_progress,
        "floor": floor,
        "decisions": rows,
    }


def _catalog_row(data: dict, filename: str) -> dict:
    rows = [row for row in data.get("decisions", []) if isinstance(row, dict)]
    floors = []
    for value in [data.get("floor"), *(row.get("floor") for row in rows)]:
        try:
            floors.append(int(float(value)))
        except (TypeError, ValueError):
            pass
    row = {
        "file": filename,
        "run_id": data.get("run_id"),
        "run_number": data.get("run_number"),
        "started_at": data.get("started_at"),
        # Synthetic ZIP rows in these floor tests are known Ironclad evidence;
        # explicit identity keeps unrelated tests from requiring a fake archive.
        "profile_id": "ironclad",
        "ascension": data.get("ascension"),
        "victory": bool(data.get("victory")),
        "in_progress": bool(data.get("in_progress")),
        "floor": max(floors) if floors else data.get("floor"),
        "decisions": len(rows),
        "last_screen": rows[-1].get("screen") if rows else None,
        "phantom_candidate": not rows and not bool(data.get("victory")),
        "storage": {"kind": "zip", "archive": "archive/test.zip",
                    "member": f"runs/{filename}"},
    }
    for key in ("human_assisted", "excluded_from_learning"):
        if key in data:
            row[key] = data[key]
    return row


class RawFloorAccountingTests(unittest.TestCase):
    def test_legacy_migration_and_new_commit_keep_learning_score_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-floor-migrate-") as temp:
            root = Path(temp)
            stats = copy.deepcopy(knowledge.DEFAULT_STATS)
            stats["global"].update({
                "runs": 3, "wins": 1, "floors_total": 95.0, "best_floor": 60,
            })
            stats["global"].pop("floor_sum_raw")
            stats["global"].pop("best_floor_raw")
            progression = copy.deepcopy(knowledge.DEFAULT_PROGRESSION)
            progression["best_floor_by_ascension"] = {"0": 40}
            _write_json(root / "stats.json", stats)
            _write_json(root / "progression.json", progression)

            know = knowledge.Knowledge(root, repair_phantoms=False)
            global_stats = know.stats["global"]
            self.assertEqual(global_stats["floor_sum_raw"], 45.0)
            # best_floor=60 may be a floor-10 victory score; progression proves F40.
            self.assertEqual(global_stats["best_floor_raw"], 40)

            know.commit_run_end(67.0, True, [], [], [], None, None, raw_floor=17)
            self.assertEqual(global_stats["runs"], 4)
            self.assertEqual(global_stats["wins"], 2)
            self.assertEqual(global_stats["floors_total"], 162.0)
            self.assertEqual(global_stats["best_floor"], 67)
            self.assertEqual(global_stats["floor_sum_raw"], 62.0)
            self.assertEqual(global_stats["best_floor_raw"], 40)

            # The optional argument preserves compatibility for old callers.
            know.commit_run_end(58.0, True, [], [], [], None, None)
            self.assertEqual(global_stats["floor_sum_raw"], 70.0)


class FloorStatsProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-floor-stats-")
        self.root = Path(self.temp.name)
        (self.root / "runs").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_stats(self, floors: list[int], wins: int = 0) -> None:
        _write_json(self.root / "stats.json", {
            "global": {
                "runs": len(floors), "wins": wins,
                "floors_total": float(sum(floors) + 50 * wins),
                "best_floor": max(floors, default=0) + (50 if wins else 0),
                "floor_sum_raw": float(sum(floors)),
                "best_floor_raw": max(floors, default=0),
            },
        })

    def _write_catalog(self, rows: list[dict]) -> None:
        path = self.root / "archive" / "run_catalog.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        header = {"schema_version": 1, "description": "test"}
        path.write_text("\n".join(json.dumps(row, ensure_ascii=False)
                                    for row in [header, *rows]) + "\n", encoding="utf-8")

    def test_initially_absent_sources_are_unavailable_without_stale(self) -> None:
        snapshot = FloorStatsProvider(self.root, refresh_interval=0).snapshot()
        self.assertFalse(snapshot["stale"])
        self.assertEqual(snapshot["quality"]["source"], "unavailable")
        self.assertIsNone(snapshot["lifetime"]["runs"])
        self.assertEqual(snapshot["recent"]["count"], 0)

        # A schema-valid empty catalog is also legitimate before any runs exist.
        self._write_catalog([])
        empty_catalog = FloorStatsProvider(self.root, refresh_interval=0).snapshot()
        self.assertFalse(empty_catalog["stale"])
        self.assertEqual(empty_catalog["quality"]["catalog_records"], 0)

    def test_exclusion_is_sticky_across_catalog_and_active_duplicates(self) -> None:
        legacy = _run("LEGACY", 1, 7)
        assisted = _run(
            "ASSISTED", 2, 99, in_progress=True, game_over=True)
        assisted["human_assisted"] = True
        self._write_catalog([_catalog_row(assisted, "assisted.json")])
        _write_json(self.root / "runs" / "legacy.json", legacy)

        # The active trace is authoritative for gameplay evidence, but an older
        # duplicate's durable exclusion flag must never be erased by omission.
        active_duplicate = copy.deepcopy(assisted)
        active_duplicate.pop("human_assisted")
        _write_json(self.root / "runs" / "assisted.json", active_duplicate)
        self._write_stats([7])

        snapshot = FloorStatsProvider(self.root, refresh_interval=0).snapshot()

        self.assertEqual(snapshot["recent"]["count"], 1)
        self.assertEqual(snapshot["recent"]["mean_floor"], 7.0)
        self.assertEqual([row["run_id"] for row in snapshot["trend"]], ["LEGACY"])
        self.assertEqual(snapshot["quality"]["completed_records"], 1)
        self.assertEqual(snapshot["quality"]["excluded_from_statistics"], 1)
        self.assertTrue((self.root / "runs" / "assisted.json").is_file())

    def test_sources_that_disappear_preserve_last_good_and_mark_stale(self) -> None:
        archived = _run("ARCHIVED", 1, 5)
        active = _run("ACTIVE_ONLY", 2, 12)
        self._write_catalog([_catalog_row(archived, "archived.json")])
        active_path = self.root / "runs" / "active.json"
        _write_json(active_path, active)
        self._write_stats([5, 12])
        _write_json(self.root / "progression.json", {
            "best_floor_by_ascension": {"0": 12},
        })
        provider = FloorStatsProvider(self.root, refresh_interval=0)
        good = provider.snapshot()

        (self.root / "stats.json").unlink()
        (self.root / "progression.json").unlink()
        (self.root / "archive" / "run_catalog.jsonl").unlink()
        active_path.unlink()
        stale = provider.snapshot(force=True)

        self.assertTrue(stale["stale"])
        self.assertEqual(stale["lifetime"], good["lifetime"])
        self.assertEqual(stale["recent"], good["recent"])
        errors = "\n".join(stale["quality"]["errors"])
        self.assertIn("stats.json: disappeared", errors)
        self.assertIn("progression.json: disappeared", errors)
        self.assertIn("run_catalog.jsonl: disappeared", errors)
        self.assertIn("active.json: disappeared before a valid catalog takeover", errors)

    def test_missing_active_retires_only_after_zip_catalog_takeover(self) -> None:
        data = _run("TAKEOVER", 1, 7)
        active_path = self.root / "runs" / "takeover.json"
        _write_json(active_path, data)
        self._write_stats([7])
        provider = FloorStatsProvider(self.root, refresh_interval=0)
        good = provider.snapshot()
        active_path.unlink()

        missing = provider.snapshot(force=True)
        self.assertTrue(missing["stale"])
        self.assertEqual(missing["recent"], good["recent"])

        not_archived = _catalog_row(data, active_path.name)
        not_archived["storage"] = {"kind": "active", "path": "runs/takeover.json"}
        self._write_catalog([not_archived])
        still_missing = provider.snapshot(force=True)
        self.assertTrue(still_missing["stale"])
        self.assertEqual(still_missing["recent"], good["recent"])

        archived = dict(not_archived)
        archived["storage"] = {
            "kind": "zip", "archive": "archive/test.zip",
            "member": "runs/takeover.json",
        }
        self._write_catalog([archived])
        taken_over = provider.snapshot(force=True)
        self.assertFalse(taken_over["stale"])
        self.assertEqual(taken_over["recent"], good["recent"])
        self.assertEqual(taken_over["quality"]["active_records"], 0)

    def test_valid_json_with_bad_schema_cannot_clear_last_good(self) -> None:
        archived = _run("SCHEMA", 1, 11)
        self._write_catalog([_catalog_row(archived, "schema.json")])
        self._write_stats([11])
        _write_json(self.root / "progression.json", {
            "best_floor_by_ascension": {"0": 11},
        })
        provider = FloorStatsProvider(self.root, refresh_interval=0)
        good = provider.snapshot()

        _write_json(self.root / "stats.json", {})
        _write_json(self.root / "progression.json", {})
        self._write_catalog([])
        stale = provider.snapshot(force=True)

        self.assertTrue(stale["stale"])
        self.assertEqual(stale["lifetime"], good["lifetime"])
        self.assertEqual(stale["recent"], good["recent"])
        errors = "\n".join(stale["quality"]["errors"])
        self.assertIn("stats.global must be an object", errors)
        self.assertIn("progression.best_floor_by_ascension", errors)
        self.assertIn("catalog unexpectedly lost all run records", errors)

    def test_unrecoverable_active_floor_cannot_erase_clean_catalog(self) -> None:
        clean = _run("DIRTY_OVERRIDE", 1, 9)
        self._write_catalog([_catalog_row(clean, "clean.json")])
        dirty = _run("DIRTY_OVERRIDE", 2, "broken")
        _write_json(self.root / "runs" / "dirty.json", dirty)
        self._write_stats([9])

        snapshot = FloorStatsProvider(self.root, refresh_interval=0).snapshot()
        self.assertTrue(snapshot["stale"])
        self.assertEqual(snapshot["recent"]["count"], 1)
        self.assertEqual(snapshot["recent"]["mean_floor"], 9.0)
        self.assertEqual(snapshot["recent"]["best_floor"], 9)
        self.assertEqual(snapshot["quality"]["invalid_records"], 1)
        self.assertIn("no usable floor evidence",
                      "\n".join(snapshot["quality"]["errors"]))

    def test_merge_completion_phantom_dirty_floor_and_active_override(self) -> None:
        archived_a = _run("ARCHIVE_A", None, 1, started_at="2026-01-01 00:01:00")
        archived_dup = _run("DUP", 2, 4, started_at="2026-01-01 00:02:00")
        game_over = _run("OLD_GAME_OVER", 3, 12, in_progress=True, game_over=True)
        phantom = _run("PHANTOM", 4, 30, decisions=0)
        self._write_catalog([
            _catalog_row(archived_a, "archive-a.json"),
            _catalog_row(archived_dup, "archive-dup.json"),
            _catalog_row(game_over, "game-over.json"),
            _catalog_row(phantom, "phantom.json"),
        ])

        active_dup = _run("DUP", 5, 10, started_at="2026-01-01 00:05:00")
        active_dup_phantom = _run(
            "DUP", 6, 99, decisions=0, started_at="2026-01-01 00:06:00")
        dirty = _run("DIRTY", 7, "not-a-floor", started_at="2026-01-01 00:07:00")
        dirty["decisions"][0]["floor"] = "7"
        current = _run("CURRENT", 8, 14, in_progress=True,
                       started_at="2026-01-01 00:08:00")
        for name, data in [
            ("active-dup.json", active_dup),
            ("active-dup-phantom.json", active_dup_phantom),
            ("dirty.json", dirty),
            ("current.json", current),
        ]:
            _write_json(self.root / "runs" / name, data)
        # Durable aggregate counters contain only committed terminal runs.  The
        # half-written OLD_GAME_OVER trace must not be reintroduced by records.
        self._write_stats([1, 10, 7])

        snapshot = FloorStatsProvider(self.root, refresh_interval=0).snapshot()
        self.assertFalse(snapshot["stale"])
        self.assertEqual(snapshot["lifetime"]["mean_floor"], 6.0)
        self.assertEqual(snapshot["lifetime"]["best_floor"], 10)
        self.assertEqual(snapshot["recent"]["count"], 3)
        self.assertEqual(snapshot["recent"]["best_floor"], 10)
        self.assertNotIn(
            "OLD_GAME_OVER", [row["run_id"] for row in snapshot["trend"]])
        self.assertEqual(snapshot["previous"]["count"], 0)
        self.assertIsNone(snapshot["previous"]["mean_floor"])
        self.assertIsNone(snapshot["previous"]["best_floor"])
        self.assertIsNone(snapshot["delta_mean"])
        self.assertEqual(snapshot["current"]["run_id"], "CURRENT")
        self.assertEqual(snapshot["quality"]["completed_records"], 3)
        self.assertEqual(snapshot["quality"]["excluded_in_progress"], 2)
        self.assertEqual(snapshot["quality"]["excluded_phantom"], 1)
        self.assertGreaterEqual(snapshot["quality"]["duplicates"], 2)
        self.assertEqual(snapshot["quality"]["invalid_records"], 0)

        override = FloorStatsProvider(self.root, refresh_interval=0).snapshot({
            "run_id": "LIVE", "run_number": "9", "ascension": "2",
            "floor": "15", "turn": "3",
        })
        self.assertEqual(override["current"], {
            "run_id": "LIVE", "run_number": 9, "ascension": 2,
            "floor": 15, "turn": 3,
        })

    def test_windows_trend_and_compaction_catalog_are_equivalent(self) -> None:
        active: list[tuple[Path, dict]] = []
        for number in range(1, 46):
            data = _run(f"RUN_{number}", number, number,
                        started_at=f"2026-01-{number:02d} 00:00:00")
            path = self.root / "runs" / f"run-{number:02d}.json"
            _write_json(path, data)
            active.append((path, data))
        self._write_stats(list(range(1, 46)))

        provider = FloorStatsProvider(self.root, refresh_interval=0)
        before = provider.snapshot()
        self.assertEqual(before["recent"]["mean_floor"], 35.5)
        self.assertEqual(before["previous"]["mean_floor"], 15.5)
        self.assertEqual(before["delta_mean"], 20.0)
        self.assertEqual(len(before["trend"]), 40)
        self.assertEqual(before["trend"][0]["floor"], 6)
        self.assertEqual(before["trend"][4]["rolling_mean"], 8.0)

        # Simulate compaction: the first 30 raw files move behind catalog summaries.
        archived_rows = []
        for path, data in active[:30]:
            archived_rows.append(_catalog_row(data, path.name))
            path.unlink()
        self._write_catalog(archived_rows)
        after = provider.snapshot(force=True)
        for key in ("lifetime", "recent", "previous", "delta_mean", "trend"):
            self.assertEqual(after[key], before[key])

    def test_malformed_replacement_keeps_last_good_record_and_recovers(self) -> None:
        path = self.root / "runs" / "stable.json"
        _write_json(path, _run("STABLE", 1, 5))
        self._write_stats([5])
        provider = FloorStatsProvider(self.root, refresh_interval=0)
        good = provider.snapshot()

        path.write_text("{broken", encoding="utf-8")
        stale = provider.snapshot(force=True)
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["recent"], good["recent"])
        self.assertEqual(stale["quality"]["invalid_records"], 1)
        self.assertTrue(stale["quality"]["errors"])

        _write_json(path, _run("STABLE", 1, 8))
        recovered = provider.snapshot(force=True)
        self.assertFalse(recovered["stale"])
        self.assertEqual(recovered["recent"]["best_floor"], 8)
        self.assertEqual(recovered["quality"]["invalid_records"], 0)

    def test_in_progress_rewrite_does_not_publish_timestamp_only_change(self) -> None:
        path = self.root / "runs" / "current.json"
        current = _run("CURRENT", 1, 7, in_progress=True)
        _write_json(path, current)
        self._write_stats([])
        provider = FloorStatsProvider(self.root, refresh_interval=0)
        first = provider.snapshot()

        current["decisions"].append(
            {"screen": "COMBAT", "floor": 7, "action": "end_turn"})
        _write_json(path, current)

        self.assertFalse(provider.refresh(force=True))
        second = provider.snapshot()
        self.assertEqual(second["updated_at"], first["updated_at"])
        self.assertEqual(second["recent"], first["recent"])


if __name__ == "__main__":
    unittest.main()
