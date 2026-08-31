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
from character_rotation import CharacterRotation


class ResetProfileStatisticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="profile-reset-")
        self.root = Path(self.temp.name) / "sts2-ascend"
        self.profile = self.root / "knowledge" / "profiles" / "vivhite"
        (self.profile / "runs" / "nested").mkdir(parents=True)
        (self.root / ".runtime").mkdir(parents=True)
        self.progression_state = {
            "character": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
            "current_ascension": 7,
            "max_ascension_goal": 10,
            "wins_by_ascension": {"0": 2},
            "runs_by_ascension": {"0": 5},
            "best_floor_by_ascension": {"0": 48},
            "last_llm_review_run": 5,
            "last_successful_review_run": 4,
            "last_fallback_review_run": 3,
            "review_report_only_streak": 2,
            "review_closure_last_outcome": "implemented",
            "review_closure_last_runs": [4, 5],
            "custom_strategy": {"preserve": True},
        }
        self.progression_original = (
            json.dumps(self.progression_state, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        self.original = {
            "stats.json": b'{"global":{"runs":4,"floor_sum_raw":115}}',
            ".active_run_learning.json": b'{"run_id":"old-4"}',
            "review_queue.json": b'{"pending":[{"run":1},{"run":4}],"reviewing":{"run":2}}',
            "progression.json": self.progression_original,
            "runs/one.json": b'{"run":1,"floor":20}',
            "runs/nested/four.json": b'{"run":4,"floor":48}',
        }
        for relative, payload in self.original.items():
            path = self.profile / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self.preserved = {
            "policy.json": b'{"vivhite":"policy"}', "lessons.md": "历史课题".encode(),
            "review_prompt_latest.md": "旧 prompt".encode(), "meta_review.md": "旧报告".encode(),
        }
        for relative, payload in self.preserved.items():
            (self.profile / relative).write_bytes(payload)
        knowledge = self.root / "knowledge"
        (knowledge / "runs").mkdir()
        (knowledge / "stats.json").write_bytes(b'{"global":{"runs":1231}}')
        (knowledge / "runs" / "ironclad.json").write_bytes(b'{"run":1231}')
        self.rotation_path = knowledge / "character_rotation.json"
        self.rotation_state = {
            "version": 2,
            "next_character": "VIVHITE",
            "schedule_mode": "catchup_4_to_1",
            "catchup_index": 1,
            "catchup_completed": False,
            "last_completed_character": "VIVHITE",
            "active_run": None,
            "finalized_runs": {"old-vivhite": "VIVHITE"},
        }
        self.rotation_path.write_text(
            json.dumps(self.rotation_state, ensure_ascii=False), encoding="utf-8")
        self.rotation_original = self.rotation_path.read_bytes()
        self.protected = {path: path.read_bytes() for path in (
            knowledge / "stats.json", knowledge / "runs" / "ironclad.json")}
        self.now = datetime(2026, 8, 31, 8, 9, 10, 123456, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _assert_untouched(self) -> None:
        for relative, payload in self.preserved.items():
            self.assertEqual((self.profile / relative).read_bytes(), payload)
        for path, payload in self.protected.items():
            self.assertEqual(path.read_bytes(), payload)

    def _assert_rotation_original(self) -> None:
        self.assertEqual(self.rotation_path.read_bytes(), self.rotation_original)

    def _profile_snapshot(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.profile).as_posix(): path.read_bytes()
            for path in sorted(self.profile.rglob("*")) if path.is_file()
        }

    def test_archives_and_creates_clean_vivhite_baseline(self) -> None:
        result = reset.reset_profile_statistics(
            self.root, "vivhite", reset.CONFIRMATION, now=self.now)
        self.assertEqual(json.loads((self.profile / "stats.json").read_text("utf-8")),
                         copy.deepcopy(reset.DEFAULT_STATS))
        self.assertEqual(list((self.profile / "runs").iterdir()), [])
        self.assertFalse((self.profile / ".active_run_learning.json").exists())
        self.assertEqual(json.loads((self.profile / "review_queue.json").read_text("utf-8")),
                         reset.EMPTY_REVIEW_QUEUE)
        progression = json.loads(
            (self.profile / "progression.json").read_text("utf-8"))
        self.assertEqual(progression["wins_by_ascension"], {})
        self.assertEqual(progression["runs_by_ascension"], {})
        self.assertEqual(progression["best_floor_by_ascension"], {})
        self.assertEqual(progression["last_llm_review_run"], 0)
        self.assertEqual(progression["last_successful_review_run"], 0)
        self.assertEqual(progression["last_fallback_review_run"], 0)
        self.assertEqual(progression["review_closure_last_runs"], [])
        self.assertEqual(progression["current_ascension"], 7)
        self.assertEqual(progression["max_ascension_goal"], 10)
        self.assertEqual(progression["review_report_only_streak"], 2)
        self.assertEqual(
            progression["review_closure_last_outcome"], "implemented")
        self.assertEqual(progression["custom_strategy"], {"preserve": True})
        rotation = json.loads(self.rotation_path.read_text("utf-8"))
        self.assertEqual(rotation["catchup_index"], 0)
        self.assertEqual(rotation["next_character"], "VIVHITE")
        self.assertFalse(rotation["catchup_completed"])
        self.assertEqual(rotation["finalized_runs"], {"old-vivhite": "VIVHITE"})
        self._assert_untouched()
        for relative, payload in self.original.items():
            self.assertEqual((result.archive_dir / relative).read_bytes(), payload)
        self.assertEqual(
            (result.archive_dir / reset.ROTATION_FILENAME).read_bytes(),
            self.rotation_original)
        manifest = json.loads((result.archive_dir / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["schema"], "sts2-ascend-profile-reset/v3")
        self.assertEqual(manifest["status"], "completed")
        checksums = (result.archive_dir / "SHA256SUMS").read_text("utf-8")
        for relative, payload in self.original.items():
            self.assertIn(f"{hashlib.sha256(payload).hexdigest()}  {relative}", checksums)
        self.assertIn(
            f"{hashlib.sha256(self.rotation_original).hexdigest()}  "
            f"{reset.ROTATION_FILENAME}", checksums)

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
        self._assert_rotation_original()

    def test_missing_progression_creates_vivhite_defaults(self) -> None:
        (self.profile / "progression.json").unlink()
        result = reset.reset_profile_statistics(
            self.root, "vivhite", reset.CONFIRMATION, now=self.now)
        progression = json.loads(
            (self.profile / "progression.json").read_text("utf-8"))
        self.assertEqual(
            progression["character"], "VIVHITE_CHARACTER_VIVHITE_CHARACTER")
        self.assertEqual(progression["current_ascension"], 0)
        self.assertEqual(progression["wins_by_ascension"], {})
        self.assertEqual(progression["runs_by_ascension"], {})
        self.assertEqual(progression["best_floor_by_ascension"], {})
        manifest = json.loads(
            (result.archive_dir / "manifest.json").read_text("utf-8"))
        self.assertFalse(manifest["artifacts"]["progression.json"]["present"])
        self.assertFalse((result.archive_dir / "progression.json").exists())

    def test_malformed_progression_is_rejected_before_any_archive_or_mutation(self) -> None:
        (self.profile / "progression.json").write_text("[]\n", encoding="utf-8")
        profile_before = self._profile_snapshot()
        rotation_before = self.rotation_path.read_bytes()
        with self.assertRaises(reset.ResetError):
            reset.reset_profile_statistics(
                self.root, "vivhite", reset.CONFIRMATION, now=self.now)
        self.assertEqual(self._profile_snapshot(), profile_before)
        self.assertEqual(self.rotation_path.read_bytes(), rotation_before)
        self.assertFalse(
            (self.root / "knowledge" / "profile_reset_archives").exists())

    def test_active_vivhite_becomes_slot_zero_of_the_new_cycle(self) -> None:
        self.rotation_state["active_run"] = {
            "run_id": "new-vivhite-run",
            "character": "VIVHITE",
            "character_id": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
            "scheduled_character": None,
        }
        self.rotation_path.write_text(
            json.dumps(self.rotation_state, ensure_ascii=False), encoding="utf-8")
        active_original = self.rotation_path.read_bytes()

        result = reset.reset_profile_statistics(
            self.root, "vivhite", reset.CONFIRMATION, now=self.now)
        rotation = json.loads(self.rotation_path.read_text("utf-8"))
        self.assertEqual(rotation["catchup_index"], 0)
        self.assertEqual(rotation["next_character"], "VIVHITE")
        self.assertEqual(
            rotation["active_run"]["scheduled_character"], "VIVHITE")
        self.assertEqual(
            (result.archive_dir / reset.ROTATION_FILENAME).read_bytes(),
            active_original)

        stats = copy.deepcopy(reset.DEFAULT_STATS)
        stats["global"]["runs"] = 1
        reset._atomic_write_json(self.profile / "stats.json", stats)
        terminal = CharacterRotation(self.rotation_path).record_terminal(
            "new-vivhite-run", terminal_persisted=True)
        self.assertTrue(terminal.quota_consumed)
        self.assertEqual(
            CharacterRotation(self.rotation_path).snapshot().catchup_index, 1)

    def test_refuses_balanced_mode_or_active_ironclad_without_mutation(self) -> None:
        invalid_states = []
        balanced = copy.deepcopy(self.rotation_state)
        balanced.update({
            "schedule_mode": "balanced_1_to_1",
            "catchup_index": 0,
            "catchup_completed": True,
            "next_character": "IRONCLAD",
        })
        invalid_states.append(("balanced", balanced))
        active_ironclad = copy.deepcopy(self.rotation_state)
        active_ironclad["active_run"] = {
            "run_id": "active-ironclad",
            "character": "IRONCLAD",
            "character_id": "IRONCLAD_CHARACTER_IRONCLAD",
            "scheduled_character": None,
        }
        invalid_states.append(("active_ironclad", active_ironclad))

        for label, state in invalid_states:
            with self.subTest(label=label):
                self.rotation_path.write_text(
                    json.dumps(state, ensure_ascii=False), encoding="utf-8")
                before = self.rotation_path.read_bytes()
                with self.assertRaises(reset.ResetError):
                    reset.reset_profile_statistics(
                        self.root, "vivhite", reset.CONFIRMATION, now=self.now)
                self.assertEqual(self.rotation_path.read_bytes(), before)
                for relative, payload in self.original.items():
                    self.assertEqual((self.profile / relative).read_bytes(), payload)
                self.assertFalse(
                    (self.root / "knowledge" / "profile_reset_archives").exists())

    def test_rotation_only_preserves_new_statistics_and_archives_rotation(self) -> None:
        (self.profile / "stats.json").write_bytes(
            b'{"global":{"runs":0,"floor_sum_raw":0},"baseline":"new"}')
        (self.profile / "runs" / "new-in-progress.json").write_bytes(
            b'{"run_id":"new-vivhite-run","in_progress":true}')
        (self.profile / "review_queue.json").write_bytes(
            b'{"pending":[],"reviewing":null,"new_baseline":true}')
        profile_before = self._profile_snapshot()
        self.rotation_state["active_run"] = {
            "run_id": "new-vivhite-run",
            "character": "VIVHITE",
            "character_id": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
            "scheduled_character": None,
        }
        self.rotation_path.write_text(
            json.dumps(self.rotation_state, ensure_ascii=False), encoding="utf-8")
        rotation_before = self.rotation_path.read_bytes()

        result = reset.reset_rotation_cycle(
            self.root, "vivhite", reset.CONFIRMATION, now=self.now)

        self.assertEqual(self._profile_snapshot(), profile_before)
        self.assertFalse(
            (self.root / "knowledge" / "profile_reset_archives").exists())
        self.assertEqual(
            (result.archive_dir / reset.ROTATION_FILENAME).read_bytes(),
            rotation_before)
        self.assertFalse((result.archive_dir / "stats.json").exists())
        self.assertFalse((result.archive_dir / "runs").exists())
        self.assertFalse((result.archive_dir / "review_queue.json").exists())
        manifest = json.loads((result.archive_dir / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["schema"], "sts2-ascend-rotation-reset/v1")
        self.assertEqual(manifest["status"], "completed")
        rotation = json.loads(self.rotation_path.read_text("utf-8"))
        self.assertEqual(rotation["catchup_index"], 0)
        self.assertEqual(rotation["next_character"], "VIVHITE")
        self.assertFalse(rotation["catchup_completed"])
        self.assertEqual(
            rotation["active_run"]["scheduled_character"], "VIVHITE")

    def test_rotation_only_failure_restores_rotation_and_preserves_statistics(self) -> None:
        profile_before = self._profile_snapshot()
        rotation_before = self.rotation_path.read_bytes()
        real_write = reset._atomic_write_json

        def fail_rotation(path: Path, value: object) -> None:
            if path == self.rotation_path:
                raise OSError("injected rotation-only failure")
            real_write(path, value)

        with mock.patch.object(reset, "_atomic_write_json", side_effect=fail_rotation):
            with self.assertRaises(reset.ResetError):
                reset.reset_rotation_cycle(
                    self.root, "vivhite", reset.CONFIRMATION, now=self.now)

        self.assertEqual(self._profile_snapshot(), profile_before)
        self.assertEqual(self.rotation_path.read_bytes(), rotation_before)
        manifest_path = next((self.root / "knowledge" / "rotation_reset_archives" /
                              "vivhite").glob("*/manifest.json"))
        self.assertEqual(json.loads(manifest_path.read_text("utf-8"))["status"],
                         "rolled_back")

    def test_rotation_only_requires_confirmation_and_stopped_stack(self) -> None:
        profile_before = self._profile_snapshot()
        rotation_before = self.rotation_path.read_bytes()
        with self.assertRaises(reset.ResetError):
            reset.reset_rotation_cycle(self.root, "vivhite", "yes", now=self.now)
        (self.root / ".runtime" / "session.json").write_text(
            '{"state":"running"}', encoding="utf-8")
        with self.assertRaises(reset.ResetError):
            reset.reset_rotation_cycle(
                self.root, "vivhite", reset.CONFIRMATION, now=self.now)
        self.assertEqual(self._profile_snapshot(), profile_before)
        self.assertEqual(self.rotation_path.read_bytes(), rotation_before)
        self.assertFalse(
            (self.root / "knowledge" / "rotation_reset_archives").exists())

    def test_cli_rotation_only_routes_without_calling_full_reset(self) -> None:
        expected = reset.ResetResult(
            profile="vivhite", archive_dir=self.root / "rotation-archive")
        with (
            mock.patch.object(
                reset, "reset_rotation_cycle", return_value=expected
            ) as rotation_only,
            mock.patch.object(reset, "reset_profile_statistics") as full_reset,
            mock.patch("builtins.print"),
        ):
            status = reset.main([
                "--profile", "vivhite",
                "--confirm", reset.CONFIRMATION,
                "--rotation-only",
                "--stack-root", str(self.root),
            ])
        self.assertEqual(status, 0)
        rotation_only.assert_called_once_with(
            self.root, "vivhite", reset.CONFIRMATION)
        full_reset.assert_not_called()

    def test_failure_rolls_back_all_profile_artifacts_and_rotation(self) -> None:
        real_write = reset._atomic_write_json
        def fail_rotation(path: Path, value: object) -> None:
            if path == self.rotation_path:
                raise OSError("injected rotation failure")
            real_write(path, value)
        with mock.patch.object(reset, "_atomic_write_json", side_effect=fail_rotation):
            with self.assertRaises(reset.ResetError):
                reset.reset_profile_statistics(
                    self.root, "vivhite", reset.CONFIRMATION, now=self.now)
        for relative, payload in self.original.items():
            self.assertEqual((self.profile / relative).read_bytes(), payload)
        self._assert_untouched()
        self._assert_rotation_original()
        manifest_path = next((self.root / "knowledge" / "profile_reset_archives" /
                              "vivhite").glob("*/manifest.json"))
        self.assertEqual(json.loads(manifest_path.read_text("utf-8"))["status"],
                         "rolled_back")


if __name__ == "__main__":
    unittest.main()
