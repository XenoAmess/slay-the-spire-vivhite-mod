from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import reset_profile_statistics as reset


class ResetProfileStatisticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="profile-reset-")
        self.root = Path(self.temp.name) / "sts2-ascend"
        self.profile = self.root / "knowledge" / "profiles" / "vivhite"
        (self.profile / "runs" / "nested").mkdir(parents=True)
        (self.root / ".runtime").mkdir(parents=True)
        self.original = {
            "stats.json": b'{"global":{"runs":4,"floor_sum_raw":115}}',
            ".active_run_learning.json": b'{"run_id":"old-4"}',
            "review_queue.json": b'{"pending":[{"run":1},{"run":4}],"reviewing":{"run":2}}',
            "runs/one.json": b'{"run":1,"floor":20}',
            "runs/nested/four.json": b'{"run":4,"floor":48}',
        }
        for relative, payload in self.original.items():
            path = self.profile / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self.preserved = {
            "policy.json": b'{"vivhite":"policy"}', "lessons.md": "历史课题".encode(),
            "progression.json": b'{"ascension":7}',
            "review_prompt_latest.md": "旧 prompt".encode(), "meta_review.md": "旧报告".encode(),
        }
        for relative, payload in self.preserved.items():
            (self.profile / relative).write_bytes(payload)
        knowledge = self.root / "knowledge"
        (knowledge / "runs").mkdir()
        (knowledge / "stats.json").write_bytes(b'{"global":{"runs":1231}}')
        (knowledge / "runs" / "ironclad.json").write_bytes(b'{"run":1231}')
        (knowledge / "character_rotation.json").write_bytes(b'{"next":"vivhite"}')
        self.protected = {path: path.read_bytes() for path in (
            knowledge / "stats.json", knowledge / "runs" / "ironclad.json",
            knowledge / "character_rotation.json")}
        self.now = datetime(2026, 8, 31, 8, 9, 10, 123456, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _assert_untouched(self) -> None:
        for relative, payload in self.preserved.items():
            self.assertEqual((self.profile / relative).read_bytes(), payload)
        for path, payload in self.protected.items():
            self.assertEqual(path.read_bytes(), payload)

    def test_archives_and_creates_clean_vivhite_baseline(self) -> None:
        result = reset.reset_profile_statistics(
            self.root, "vivhite", reset.CONFIRMATION, now=self.now)
        self.assertEqual(json.loads((self.profile / "stats.json").read_text("utf-8")),
                         copy.deepcopy(reset.DEFAULT_STATS))
        self.assertEqual(list((self.profile / "runs").iterdir()), [])
        self.assertFalse((self.profile / ".active_run_learning.json").exists())
        self.assertEqual(json.loads((self.profile / "review_queue.json").read_text("utf-8")),
                         reset.EMPTY_REVIEW_QUEUE)
        self._assert_untouched()
        for relative, payload in self.original.items():
            self.assertEqual((result.archive_dir / relative).read_bytes(), payload)
        manifest = json.loads((result.archive_dir / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["status"], "completed")
        checksums = (result.archive_dir / "SHA256SUMS").read_text("utf-8")
        for relative, payload in self.original.items():
            self.assertIn(f"{hashlib.sha256(payload).hexdigest()}  {relative}", checksums)

    def test_refuses_running_stack_ironclad_and_wrong_confirmation(self) -> None:
        before = (self.profile / "stats.json").read_bytes()
        (self.root / ".runtime" / "session.json").write_text('{"state":"running"}')
        with self.assertRaises(reset.ResetError):
            reset.reset_profile_statistics(self.root, "vivhite", reset.CONFIRMATION)
        (self.root / ".runtime" / "session.json").unlink()
        with self.assertRaises(reset.ResetError):
            reset.reset_profile_statistics(self.root, "ironclad", reset.CONFIRMATION)
        with self.assertRaises(reset.ResetError):
            reset.reset_profile_statistics(self.root, "vivhite", "yes")
        self.assertEqual((self.profile / "stats.json").read_bytes(), before)
        self.assertFalse((self.root / "knowledge" / "profile_reset_archives").exists())
        self._assert_untouched()

    def test_failure_rolls_back_all_four_artifacts(self) -> None:
        real_write = reset._atomic_write_json
        def fail_queue(path: Path, value: object) -> None:
            if path.name == "review_queue.json":
                raise OSError("injected queue failure")
            real_write(path, value)
        with mock.patch.object(reset, "_atomic_write_json", side_effect=fail_queue):
            with self.assertRaises(reset.ResetError):
                reset.reset_profile_statistics(
                    self.root, "vivhite", reset.CONFIRMATION, now=self.now)
        for relative, payload in self.original.items():
            self.assertEqual((self.profile / relative).read_bytes(), payload)
        self._assert_untouched()
        manifest_path = next((self.root / "knowledge" / "profile_reset_archives" /
                              "vivhite").glob("*/manifest.json"))
        self.assertEqual(json.loads(manifest_path.read_text("utf-8"))["status"],
                         "rolled_back")


if __name__ == "__main__":
    unittest.main()
