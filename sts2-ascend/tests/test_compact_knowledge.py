"""Focused regression tests for knowledge compaction and prompt working sets."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import compact_knowledge  # noqa: E402
import knowledge  # noqa: E402
import llm_review  # noqa: E402


class CompactKnowledgeTests(unittest.TestCase):
    def test_windows_pid_probe_never_calls_os_kill(self) -> None:
        with (mock.patch.object(compact_knowledge.os, "name", "nt"),
              mock.patch.object(compact_knowledge.os, "kill",
                                side_effect=AssertionError("must not signal")),
              mock.patch("ctypes.WinDLL", side_effect=OSError("probe unavailable"))):
            # Probe failure is fail-closed: compaction treats the PID as live.
            self.assertTrue(compact_knowledge._pid_alive(1234))

    def test_catalog_summary_preserves_real_card_evidence_without_fake_empty_fields(
            self) -> None:
        old = {
            "run_id": "OLD", "run_number": 1, "floor": 7,
            "decisions": [{"screen": "COMBAT", "floor": 7}],
        }
        old_summary = compact_knowledge._run_summary(
            old, "old.json", 100, "a" * 64)
        self.assertNotIn("card_picks", old_summary)
        self.assertNotIn("final_deck", old_summary)

        explicit_empty = {
            **old,
            "run_id": "EMPTY",
            "attribution_tags": [],
            "final_deck": [],
        }
        empty_summary = compact_knowledge._run_summary(
            explicit_empty, "empty.json", 101, "b" * 64)
        self.assertEqual(empty_summary["card_picks"], [])
        self.assertEqual(empty_summary["final_deck"], [])

        real = {
            **old,
            "run_id": "REAL",
            "attribution_tags": [
                ["map_node", "MONSTER"],
                ["card_pick", "bash"],
                ["card_pick", "bash"],
            ],
            "final_deck": [
                {"card_id": "strike", "upgraded": False, "name": "Strike"},
                {"card_id": "bash", "upgraded": True, "name": "Bash+"},
                {"card_id": "bash", "upgraded": False, "name": "Bash"},
            ],
        }
        real_summary = compact_knowledge._run_summary(
            real, "real.json", 102, "c" * 64)
        self.assertEqual(real_summary["card_picks"], ["BASH", "BASH"])
        self.assertEqual(
            [(row["card_id"], row["upgraded"])
             for row in real_summary["final_deck"]],
            [("STRIKE", False), ("BASH", True), ("BASH", False)])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-compact-test-")
        self.root = Path(self.temp.name)
        self.know = knowledge.Knowledge(self.root, repair_phantoms=False)
        self.know.save()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        for i in range(1, 13):
            decision_n = 30 if i == 2 else i + 2
            floor = 33 if i == 3 else i
            decisions = [
                {"screen": "COMBAT", "action": "play_card", "floor": floor,
                 "reason": ("long-trace-" * 30 if i == 2 else f"run-{i}-step-{j}")}
                for j in range(decision_n)
            ]
            payload = {
                "run_id": f"COMPACT_{i:02d}", "run_number": i, "ascension": 0,
                "started_at": f"2026-01-01 00:{i:02d}:00",
                "victory": i == 4, "in_progress": i == 5, "floor": floor,
                "decisions": decisions, "combat_notes": [f"F{floor} test"],
            }
            path = self.root / "runs" / f"20260101-00{i:02d}00_COMPACT_{i:02d}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        (self.root / "runs" / "invalid.json").write_text("{broken", encoding="utf-8")
        (self.root / "lessons.md").write_text(
            "# lessons\n"
            "## 第 1 局复盘\nold-1\n"
            "## 🧠 关键长期经验\npinned\n"
            "## 第 3 局复盘\nold-3\n"
            "## 第 4 局复盘\nold-4\n"
            "## 第 5 局复盘\nrecent-5\n"
            "## 第 6 局复盘\nrecent-6\n", encoding="utf-8")
        (self.root / "meta_review.md").write_text(
            "# meta\n" + "".join(f"## review {i}\nbody-{i}\n" for i in range(1, 6)),
            encoding="utf-8")

    def test_verified_archive_and_second_apply_is_noop(self) -> None:
        self._write_fixture()
        options = compact_knowledge.CompactionOptions(
            keep_recent=2, deep_floor=33, keep_longest=1, keep_largest=0,
            keep_floor_representatives=False, keep_lessons=2, keep_meta_reviews=2)
        stats_sha = compact_knowledge._sha256((self.root / "stats.json").read_bytes())
        plan = compact_knowledge.plan_compaction(self.root, options)

        self.assertTrue(plan.archive_new)
        self.assertIn("invalid.json", plan.keep_reasons)
        all_reasons = {reason for reasons in plan.keep_reasons.values() for reason in reasons}
        self.assertIn("recent", all_reasons)
        self.assertIn("deep_floor>=33", all_reasons)
        self.assertIn("victory", all_reasons)
        self.assertIn("in_progress", all_reasons)
        archived_hashes = {record.name: record.sha256 for record in plan.archive_new}

        first = compact_knowledge.apply_compaction(self.root, options)
        self.assertTrue(first["archive_created"])
        self.assertEqual(first["archived_runs"], len(archived_hashes))
        self.assertEqual(compact_knowledge._sha256((self.root / "stats.json").read_bytes()),
                         stats_sha)
        self.assertFalse(any((self.root / "runs" / name).exists()
                             for name in archived_hashes))

        manifest_path = self.root / compact_knowledge.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["batches"]), 1)
        batch = manifest["batches"][0]
        self.assertEqual(batch["selection_rules"]["recent_files"], 2)
        self.assertEqual(batch["selection_rules"]["deep_floor_at_least"], 33)
        archive_path = self.root / Path(batch["archive"])

        expected = {entry["member"]: (entry["sha256"], entry["bytes"])
                    for entry in batch["runs"]}
        with compact_knowledge.zipfile.ZipFile(archive_path, "r") as archive:
            for snapshot in batch["snapshots"]:
                expected[snapshot["member"]] = (snapshot["sha256"], snapshot["bytes"])
            for markdown in batch["markdown"]:
                expected[markdown["member"]] = (
                    markdown["original_sha256"], markdown["original_bytes"])
            selection = archive.read("metadata/selection.json")
            expected["metadata/selection.json"] = (
                compact_knowledge._sha256(selection), len(selection))
        compact_knowledge._verify_zip(archive_path, expected)

        probe = sorted(archived_hashes)[0]
        self.assertEqual(compact_knowledge._sha256(
            compact_knowledge.read_run_evidence(self.root, probe)), archived_hashes[probe])
        old_dir = llm_review.KNOWLEDGE_DIR
        try:
            llm_review.KNOWLEDGE_DIR = self.root
            exact = llm_review._recent_run_summaries(10, batch_runs=[1, 12])
            self.assertEqual({item["run_number"] for item in exact}, {1, 12})
            self.assertTrue(all(item["evidence_match"] == "exact_batch" for item in exact))
        finally:
            llm_review.KNOWLEDGE_DIR = old_dir
        lessons = (self.root / "lessons.md").read_text(encoding="utf-8")
        self.assertIn("🧠 关键长期经验", lessons)
        self.assertIn("recent-5", lessons)
        self.assertIn("recent-6", lessons)
        self.assertNotIn("old-1", lessons)

        catalog_before = (self.root / compact_knowledge.CATALOG_REL).read_bytes()
        second = compact_knowledge.apply_compaction(self.root, options)
        self.assertTrue(second["idempotent_noop"])
        self.assertFalse(second["changed"])
        self.assertEqual(len(json.loads(manifest_path.read_text(encoding="utf-8"))["batches"]), 1)
        self.assertEqual((self.root / compact_knowledge.CATALOG_REL).read_bytes(), catalog_before)

    def test_zip_traversal_and_active_store_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            compact_knowledge._safe_zip_member("../escape.json")
        (self.root / "review_active.flag").write_text("123", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "active knowledge store"):
            compact_knowledge.apply_compaction(self.root)

    def test_archive_before_releases_old_quality_pins_but_keeps_recent_and_active(self) -> None:
        self._write_fixture()
        options = compact_knowledge.CompactionOptions(
            archive_before="2026-01-02", keep_recent=2,
            keep_longest=12, keep_largest=12)
        plan = compact_knowledge.plan_compaction(self.root, options)
        self.assertEqual(
            {record.summary["run_number"] for record in plan.archive_new},
            {1, 2, 3, 4, 6, 7, 8, 9, 10})
        self.assertEqual(plan.keep_reasons["20260101-000500_COMPACT_05.json"],
                         ["in_progress"])
        self.assertIn("invalid.json", plan.keep_reasons)
        self.assertEqual(options.selection_rules()["archive_before"], "2026-01-02")

    def test_archive_before_uses_payload_date_and_keeps_unknown_dates_and_anomalies(self) -> None:
        rows = {
            "old.json": {"started_at": "2026-08-01 12:00:00"},
            "20260801-misleading.json": {"started_at": "2026-09-01T00:00:00+08:00"},
            "missing.json": {},
            "invalid-date.json": {"started_at": "2026-08-35 12:00:00"},
            "invalid-time.json": {"started_at": "2026-08-01 29:99:00"},
            "human.json": {"started_at": "2026-08-01", "human_assisted": True},
            "excluded.json": {"started_at": "2026-08-01", "excluded_from_learning": True},
            "orphaned.json": {"started_at": "2026-08-01", "orphaned": True},
            "empty-victory.json": {"started_at": "2026-08-01", "decisions": []},
        }
        for name, extra in rows.items():
            payload = {"run_id": name, "floor": 50, "victory": True,
                       "decisions": [{"screen": "GAME_OVER", "floor": 50}], **extra}
            (self.root / "runs" / name).write_text(json.dumps(payload), encoding="utf-8")
        options = compact_knowledge.CompactionOptions(
            archive_before="2026-09-01", keep_recent=0)
        plan = compact_knowledge.plan_compaction(self.root, options)
        self.assertEqual([record.name for record in plan.archive_new], ["old.json"])
        for name in ("missing.json", "invalid-date.json", "invalid-time.json"):
            self.assertIn("unknown_run_date", plan.keep_reasons[name])
        self.assertIn("victory", plan.keep_reasons["20260801-misleading.json"])
        for name in ("human.json", "excluded.json", "orphaned.json"):
            self.assertIn("excluded_run_anomaly", plan.keep_reasons[name])
        self.assertIn("zero_decision_anomaly", plan.keep_reasons["empty-victory.json"])

    def test_archive_before_validates_calendar_date_in_cli_and_options(self) -> None:
        args = compact_knowledge._parser().parse_args(["--archive-before", "2026-09-01"])
        self.assertEqual(args.archive_before, "2026-09-01")
        for value in ("2026-02-30", "20260901", "2026-W36-1", "yesterday"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    compact_knowledge.CompactionOptions(archive_before=value)
                with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                    compact_knowledge._parser().parse_args(["--archive-before", value])

    def test_archive_before_round_trip_preserves_identity_and_only_recorded_versions(self) -> None:
        payload = {"run_id": "VERSIONED", "run_number": 12,
                   "profile_id": "vivhite", "profile_run_number": 8,
                   "character_id": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
                   "native_profile_id": 1, "boot_head": "a" * 40,
                   "boot_review_commit": "b" * 40, "game_version": "0.111.0",
                   "started_at": "2026-08-01 12:00:00", "floor": 50,
                   "victory": True, "decisions": [{"screen": "GAME_OVER", "floor": 50}]}
        path = self.root / "runs" / "versioned.json"
        raw = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
        path.write_bytes(raw)
        options = compact_knowledge.CompactionOptions(
            archive_before="2026-09-01", keep_recent=0)
        result = compact_knowledge.apply_compaction(self.root, options)
        self.assertEqual(result["archived_runs"], 1)
        self.assertEqual(compact_knowledge.read_run_evidence(self.root, path.name), raw)
        catalog = (self.root / compact_knowledge.CATALOG_REL).read_text(encoding="utf-8")
        row = json.loads(catalog.splitlines()[1])
        self.assertEqual(row["catalog_projection_version"], 1)
        self.assertNotIn("card_picks", row)
        self.assertNotIn("final_deck", row)
        for key in ("run_id", "run_number", "profile_id", "profile_run_number",
                    "character_id", "native_profile_id", "boot_head",
                    "boot_review_commit", "game_version"):
            self.assertEqual(row[key], payload[key])
        self.assertNotIn("brain_version", row)
        self.assertTrue(compact_knowledge.apply_compaction(self.root, options)["idempotent_noop"])

    def test_profile_discovery_excludes_real_reset_backup_layout(self) -> None:
        live = self.root / "profiles" / "vivhite"
        backup = self.root / "profile_reset_archives" / "vivhite" / "20260831T081050.489211Z"
        for store in (live, backup):
            (store / "runs").mkdir(parents=True)
            (store / "policy.json").write_text("{}", encoding="utf-8")
            (store / "runs" / "old.json").write_text(json.dumps({
                "run_id": "OLD", "started_at": "2026-08-01", "floor": 50,
                "victory": True, "decisions": [{"screen": "GAME_OVER", "floor": 50}],
            }), encoding="utf-8")
        original = (backup / "runs" / "old.json").read_bytes()
        self.assertEqual(compact_knowledge.discover_character_profile_roots(self.root),
                         (live.resolve(),))
        result = compact_knowledge.apply_compaction(
            self.root, compact_knowledge.CompactionOptions(
                archive_before="2026-09-01", keep_recent=0))
        self.assertEqual(result["archived_runs"], 1)
        self.assertEqual((backup / "runs" / "old.json").read_bytes(), original)
        self.assertFalse((backup / "archive").exists())

    def test_prompt_bounds_keep_complete_stats_digest(self) -> None:
        self.know.save_run_log("RUN_PACKET_BOUND", {
            "run_id": "RUN_PACKET_BOUND", "victory": False, "floor": 16,
            "combat_notes": [f"combat-{i}-" + "战" * 260 for i in range(12)],
            "decisions": [
                {"screen": "MAP", "action": "choose_map_node", "floor": i,
                 "reason": f"route-{i}-" + "路" * 260}
                for i in range(10)
            ] + [{"screen": "GAME_OVER", "action": None, "floor": 16,
                  "reason": "对局结束：失败"}],
        })
        old_dir = llm_review.KNOWLEDGE_DIR
        try:
            llm_review.KNOWLEDGE_DIR = self.root
            summaries = llm_review._recent_run_summaries(10)
            bounded = next(item for item in summaries
                           if item["run_id"] == "RUN_PACKET_BOUND")
            self.assertEqual(bounded["combat_notes_total"], 12)
            self.assertEqual(len(bounded["combat_notes"]),
                             llm_review.RUN_SUMMARY_COMBAT_NOTES)
            self.assertEqual(bounded["key_reasons_total"], 10)
            self.assertEqual(len(bounded["key_reasons"]),
                             llm_review.RUN_SUMMARY_KEY_REASONS)
            self.assertTrue(all(len(text) <= llm_review.RUN_SUMMARY_TEXT_CHARS
                                for text in bounded["combat_notes"] + bounded["key_reasons"]))

            prompt = llm_review.build_prompt(
                self.know, {"max_runs_in_packet": 10, "review_every_runs": 5})
            packet_raw = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]
            packet = json.loads(packet_raw)
            self.assertEqual(packet["stats_digest"], llm_review._stats_digest(self.know))
        finally:
            llm_review.KNOWLEDGE_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
