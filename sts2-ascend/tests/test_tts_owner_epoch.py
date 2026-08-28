from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ASCEND_DIR = Path(__file__).resolve().parent.parent
TTS_DIR = ASCEND_DIR / "tts"
sys.path.insert(0, str(TTS_DIR))

import owner_epoch  # noqa: E402
import quipper  # noqa: E402


class OwnerEpochTests(unittest.TestCase):
    def test_epoch_is_path_local_and_ignores_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index, relative in enumerate(owner_epoch.OWNER_EPOCH_PATHS):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"owner-{index}", encoding="utf-8")
            before = owner_epoch.code_epoch(root)
            (root / "README.md").write_text("ordinary repo change", encoding="utf-8")
            self.assertEqual(owner_epoch.code_epoch(root), before)
            (root / owner_epoch.OWNER_EPOCH_PATHS[1]).write_text(
                "changed owner code", encoding="utf-8")
            self.assertNotEqual(owner_epoch.code_epoch(root), before)

    def test_health_match_requires_exact_session_epoch_and_protocol(self) -> None:
        epoch = "a" * 64
        status = {
            "ready": True,
            "session_id": "session-a",
            "owner_protocol_version": owner_epoch.OWNER_PROTOCOL_VERSION,
            "owner_feature_version": owner_epoch.OWNER_FEATURE_VERSION,
            "owner_code_epoch": epoch,
        }
        self.assertTrue(owner_epoch.status_matches(
            status, session_id="session-a", expected_epoch=epoch))
        self.assertFalse(owner_epoch.status_matches(
            status, session_id="session-b", expected_epoch=epoch))
        self.assertFalse(owner_epoch.status_matches(
            status, session_id="session-a", expected_epoch="b" * 64))


class OwnerLockHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.old_lock = quipper.LOCK_FILE
        self.old_session = quipper.SESSION_ID
        self.old_epoch = quipper.OWNER_CODE_EPOCH
        quipper.LOCK_FILE = Path(self.temp.name) / "voice_quipper.lock"
        quipper.SESSION_ID = "session-test"
        quipper.OWNER_CODE_EPOCH = "b" * 64

    def tearDown(self) -> None:
        quipper.LOCK_FILE = self.old_lock
        quipper.SESSION_ID = self.old_session
        quipper.OWNER_CODE_EPOCH = self.old_epoch
        self.temp.cleanup()

    @staticmethod
    def _record(epoch: str, protocol: int = 2) -> dict:
        return {
            "pid": 4242,
            "session_id": "session-test",
            "created_unix": 1700000000.0,
            "creation_filetime": 133444736000000000,
            "owner_protocol_version": protocol,
            "owner_code_epoch": epoch,
        }

    def _write_lock(self, record: dict) -> None:
        quipper.LOCK_FILE.write_text(json.dumps(record), encoding="utf-8")

    def test_legacy_live_owner_is_kept_for_one_time_full_restart(self) -> None:
        self._write_lock(self._record("", protocol=0))
        with (mock.patch.object(quipper, "stop_requested", return_value=False),
              mock.patch.object(quipper, "_pid_alive", return_value=True),
              mock.patch.object(quipper, "_request_handoff") as handoff):
            self.assertFalse(quipper._acquire_owner_lock(self._record("b" * 64)))
        handoff.assert_not_called()
        self.assertTrue(quipper.LOCK_FILE.exists())

    def test_new_generation_waits_for_old_identity_then_claims(self) -> None:
        self._write_lock(self._record("a" * 64))
        successor = self._record("b" * 64)
        successor["pid"] = 5252
        with (mock.patch.object(quipper, "stop_requested", return_value=False),
              mock.patch.object(quipper, "_pid_alive", side_effect=[True, False]),
              mock.patch.object(quipper, "_request_handoff", return_value=True) as handoff):
            self.assertTrue(quipper._acquire_owner_lock(successor))
        handoff.assert_called_once()
        claimed = json.loads(quipper.LOCK_FILE.read_text(encoding="utf-8"))
        self.assertEqual(claimed["pid"], 5252)
        self.assertEqual(claimed["owner_code_epoch"], "b" * 64)

    def test_atomic_claim_allows_only_one_candidate(self) -> None:
        record = self._record("b" * 64)
        self.assertTrue(quipper._claim_owner_lock(record))
        self.assertFalse(quipper._claim_owner_lock(record))


if __name__ == "__main__":
    unittest.main()
