"""Recent packets and exact archived batches retain evidence without full scans."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))
import compact_knowledge as compact
import llm_review


class ReviewHistoryLoadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-review-history-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "runs").mkdir()
        self.enterContext(llm_review._review_profile_scope(
            profile_id="ironclad", profile_root=self.root))

    def write_run(self, number, **overrides):
        path = self.root / "runs" / f"run-{number:04}.json"
        payload = {
            "run_id": f"ID-{number}", "run_number": number,
            "floor": number, "victory": False, "ascension": 0,
            "decisions": [{"screen": "COMBAT", "floor": number}],
            **overrides,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_recent_packet_reads_only_newest_eligible_files_in_original_order(self):
        for number in range(100):
            self.write_run(number)
        self.write_run(100, in_progress=True)
        self.write_run(101, human_assisted=True)
        self.write_run(102).write_text("[]", encoding="utf-8")
        self.write_run(103).write_bytes(b"\xff")
        opened = []
        original = Path.read_text

        def read(path, *args, **kwargs):
            if path.parent == self.root / "runs":
                opened.append(path.name)
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", read):
            rows = llm_review._review_run_records(3)
        self.assertEqual([row[1]["run_number"] for row in rows], [97, 98, 99])
        self.assertEqual(len(opened), 7)
        self.assertEqual({row[2] for row in rows}, {"recent"})

    def test_zero_recent_limit_does_not_read_history(self):
        self.write_run(1)
        with mock.patch.object(Path, "read_text", side_effect=AssertionError):
            self.assertEqual(llm_review._review_run_records(0), [])

    def test_exact_batch_still_finds_older_active_runs_and_labels_missing_fallback(self):
        for number in range(8):
            self.write_run(number)
        rows = llm_review._review_run_records(3, [1, 6, 999])
        self.assertEqual([(row[1]["run_number"], row[2]) for row in rows], [
            (1, "exact_batch"), (6, "exact_batch"), (7, "recent_fallback_unmapped")])

    def test_exact_archived_batch_works_without_active_directory_or_manifest_rescan(self):
        self.write_run(1)
        self.write_run(2)
        compact.apply_compaction(self.root, compact.CompactionOptions(
            keep_recent=0, deep_floor=999, keep_longest=0, keep_largest=0,
            keep_floor_representatives=False))
        # Keep the newest representative elsewhere to exercise archive-only
        # retrieval, including installations without an active runs directory.
        (self.root / "runs" / "run-0002.json").rename(self.root / "representative.json")
        (self.root / "runs").rmdir()
        with mock.patch.object(compact, "_load_manifest", side_effect=AssertionError):
            rows = llm_review._review_run_records(10, [1])
        self.assertEqual([(row[1]["run_id"], row[2]) for row in rows],
                         [("ID-1", "exact_batch")])
        chain = llm_review._primary_failure_decision_chain(10, [1], records=rows)
        location = chain["full_failure_run"]["full_chain_available_in"]
        self.assertIn("archive/run_catalog.jsonl", location)
        self.assertIn("run-0001.json", location)

    def test_active_content_overrides_archived_catalog_entry(self):
        self.write_run(1)
        self.write_run(2)
        compact.apply_compaction(self.root, compact.CompactionOptions(
            keep_recent=0, deep_floor=999, keep_longest=0, keep_largest=0,
            keep_floor_representatives=False))
        self.write_run(1, floor=12)
        rows = llm_review._requested_archived_runs({1}, set())
        self.assertEqual(rows[0][1]["floor"], 12)


if __name__ == "__main__":
    unittest.main()
