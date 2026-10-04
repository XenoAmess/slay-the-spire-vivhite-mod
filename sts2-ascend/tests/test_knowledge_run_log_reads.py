"""Unavailable persisted run history must never look like a new run."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))
import knowledge


class KnowledgeRunLogReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascend-run-log-read-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = knowledge.Knowledge(self.root, repair_phantoms=False)
        self.payload = {
            "run_id": "active", "human_assisted": True,
            "excluded_from_learning": True,
            "decisions": [{"screen": "COMBAT", "floor": 7}],
            "attribution_tags": [["card_pick", "BASH"]],
        }
        self.path = self.store.save_run_log("active", self.payload)

    def test_transient_permission_error_retries_and_recovers_exact_history(self):
        read = Path.read_text
        attempts = 0

        def flaky(path, *args, **kwargs):
            nonlocal attempts
            if path == self.path:
                attempts += 1
                if attempts == 1:
                    raise PermissionError("temporary busy file")
            return read(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", flaky), \
                mock.patch.object(knowledge.time, "sleep"):
            self.assertEqual(self.store.load_run_log("active"), self.payload)
        self.assertEqual(attempts, 2)

    def test_persistent_read_error_is_bounded_and_preserves_original(self):
        original = self.path.read_bytes()
        read = Path.read_text
        attempts = 0

        def denied(path, *args, **kwargs):
            nonlocal attempts
            if path == self.path:
                attempts += 1
                raise PermissionError("busy file")
            return read(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", denied), \
                mock.patch.object(knowledge.time, "sleep"):
            with self.assertRaises(PermissionError):
                self.store.load_run_log("active")
        self.assertEqual(attempts, knowledge._READ_RETRIES)
        self.assertEqual(self.path.read_bytes(), original)

    def test_bad_json_and_non_object_are_not_missing_history(self):
        for raw in (b"{broken", b"[]"):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.store.load_run_log("active")
                self.assertEqual(self.path.read_bytes(), raw)

    def test_directory_read_error_is_not_missing_history(self):
        scan = Path.iterdir

        def denied(path):
            if path == self.root / "runs":
                raise PermissionError("directory busy")
            return scan(path)

        with mock.patch.object(Path, "iterdir", denied):
            with self.assertRaises(PermissionError):
                self.store.load_run_log("active")

    def test_genuinely_missing_run_and_store_still_return_none(self):
        self.assertIsNone(self.store.load_run_log("different"))
        self.path.unlink()
        (self.root / "runs").rmdir()
        self.assertIsNone(self.store.load_run_log("active"))


if __name__ == "__main__":
    unittest.main()
