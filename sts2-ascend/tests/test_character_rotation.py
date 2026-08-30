"""Strict character-rotation state-machine regressions."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import character_rotation  # noqa: E402
from character_rotation import (  # noqa: E402
    CharacterRotation,
    CharacterRotationError,
    IRONCLAD,
    VIVHITE,
)


VIVHITE_ID = "VIVHITE_CHARACTER_VIVHITE_CHARACTER"
IRONCLAD_ID = "IRONCLAD"


def _characters(*, include_vivhite: bool = True,
                vivhite_locked: bool = False) -> list[dict]:
    characters = [
        {
            "index": 0,
            "character_id": IRONCLAD_ID,
            "name": "Ironclad",
            "is_locked": False,
            "is_random": False,
        },
    ]
    if include_vivhite:
        characters.append({
            "index": 4,
            "character_id": VIVHITE_ID,
            "name": "Vivhite",
            "is_locked": vivhite_locked,
            "is_random": False,
        })
    return characters


class CharacterRotationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-character-rotation-")
        self.state_path = Path(self.temp.name) / "character_rotation.json"
        self.rotation = CharacterRotation(self.state_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_first_vivhite_then_strict_vivhite_ironclad_alternation(self) -> None:
        first = self.rotation.resolve_selection(_characters())
        self.assertTrue(first.ready)
        self.assertEqual(first.target_character, VIVHITE)
        self.assertEqual(first.character_id, VIVHITE_ID)
        self.assertEqual(first.option_index, 4)

        self.rotation.observe_active_run("run-v1", VIVHITE_ID)
        v1 = self.rotation.record_terminal(
            "run-v1", terminal_persisted=True)
        self.assertTrue(v1.advanced)
        self.assertEqual(v1.next_character, IRONCLAD)

        second = self.rotation.resolve_selection(_characters())
        self.assertTrue(second.ready)
        self.assertEqual(second.target_character, IRONCLAD)
        self.assertEqual(second.character_id, IRONCLAD_ID)
        self.assertEqual(second.option_index, 0)

        self.rotation.observe_active_run("run-i1", IRONCLAD_ID)
        i1 = self.rotation.record_terminal(
            "run-i1", terminal_persisted=True)
        self.assertTrue(i1.advanced)
        self.assertEqual(i1.next_character, VIVHITE)
        self.assertEqual(self.rotation.target_character, VIVHITE)

    def test_terminal_flips_only_after_persistence_and_run_id_is_durable(self) -> None:
        self.rotation.observe_active_run("same-run", VIVHITE_ID)
        before = self.state_path.read_bytes()

        rejected = self.rotation.record_terminal(
            "same-run", terminal_persisted=False)
        self.assertFalse(rejected.advanced)
        self.assertEqual(rejected.next_character, VIVHITE)
        self.assertEqual(self.state_path.read_bytes(), before)

        accepted = self.rotation.record_terminal(
            "same-run", terminal_persisted=True)
        self.assertTrue(accepted.advanced)
        self.assertEqual(accepted.next_character, IRONCLAD)

        duplicate = self.rotation.record_terminal(
            "same-run", terminal_persisted=True)
        self.assertFalse(duplicate.advanced)
        self.assertEqual(duplicate.next_character, IRONCLAD)

        reloaded = CharacterRotation(self.state_path)
        duplicate_after_restart = reloaded.record_terminal(
            "same-run", terminal_persisted=True)
        self.assertFalse(duplicate_after_restart.advanced)
        self.assertEqual(reloaded.target_character, IRONCLAD)
        self.assertEqual(reloaded.snapshot().finalized_run_ids, ("same-run",))

    def test_active_run_recovers_the_games_actual_character(self) -> None:
        # The state machine may be introduced while a pre-existing run is active.
        # The game is authoritative for that run even though a fresh rotation would
        # otherwise begin with Vivhite.
        observed = self.rotation.observe_active_run("existing-run", IRONCLAD_ID)
        self.assertEqual(observed.next_character, VIVHITE)
        self.assertEqual(observed.target_character, IRONCLAD)

        reloaded = CharacterRotation(self.state_path)
        restored = reloaded.snapshot()
        self.assertEqual(restored.active_run_id, "existing-run")
        self.assertEqual(restored.active_character, IRONCLAD)
        self.assertEqual(restored.active_character_id, IRONCLAD_ID)
        self.assertEqual(reloaded.target_character, IRONCLAD)

        pending = reloaded.resolve_selection(_characters())
        self.assertTrue(pending.blocked)
        self.assertEqual(pending.reason, "active_run_pending_terminal:existing-run")

        finished = reloaded.record_terminal(
            "existing-run", terminal_persisted=True)
        self.assertEqual(finished.next_character, VIVHITE)
        self.assertFalse(reloaded.snapshot().has_active_run)

    def test_missing_or_locked_target_blocks_without_fallback(self) -> None:
        missing = self.rotation.resolve_selection(
            _characters(include_vivhite=False))
        self.assertTrue(missing.blocked)
        self.assertEqual(missing.target_character, VIVHITE)
        self.assertEqual(missing.reason, "target_missing")
        self.assertIsNone(missing.character_id)
        self.assertIsNone(missing.option_index)

        locked = self.rotation.resolve_selection(
            _characters(vivhite_locked=True))
        self.assertTrue(locked.blocked)
        self.assertEqual(locked.reason, "target_unavailable")
        self.assertIsNone(locked.character_id)
        self.assertIsNone(locked.option_index)
        self.assertEqual(self.rotation.target_character, VIVHITE)

    def test_atomic_replace_failure_keeps_previous_rotation_and_cleans_temp(self) -> None:
        self.rotation.observe_active_run("run-v1", VIVHITE_ID)
        previous = self.state_path.read_bytes()

        with (mock.patch.object(
                character_rotation.os, "replace",
                side_effect=OSError("injected replace failure")),
              self.assertRaises(OSError)):
            self.rotation.record_terminal(
                "run-v1", terminal_persisted=True)

        self.assertEqual(self.state_path.read_bytes(), previous)
        restored = CharacterRotation(self.state_path).snapshot()
        self.assertEqual(restored.active_run_id, "run-v1")
        self.assertEqual(restored.target_character, VIVHITE)
        self.assertEqual(list(self.state_path.parent.glob(
            f".{self.state_path.name}.*.tmp")), [])

    def test_old_run_id_remains_idempotent_after_later_runs(self) -> None:
        self.rotation.observe_active_run("run-v", VIVHITE_ID)
        self.rotation.record_terminal("run-v", terminal_persisted=True)
        self.rotation.observe_active_run("run-i", IRONCLAD_ID)
        self.rotation.record_terminal("run-i", terminal_persisted=True)

        replay = self.rotation.record_terminal(
            "run-v", terminal_persisted=True, character_id=VIVHITE_ID)
        self.assertFalse(replay.advanced)
        self.assertEqual(replay.next_character, VIVHITE)
        self.assertEqual(
            self.rotation.snapshot().finalized_run_ids,
            ("run-i", "run-v"),
        )

    def test_unknown_terminal_character_cannot_guess_and_advance(self) -> None:
        with self.assertRaises(CharacterRotationError):
            self.rotation.record_terminal(
                "unobserved", terminal_persisted=True)
        self.assertEqual(self.rotation.target_character, VIVHITE)
        self.assertFalse(self.state_path.exists())

    def test_persisted_schema_contains_active_and_idempotence_facts(self) -> None:
        self.rotation.observe_active_run("run-v", VIVHITE_ID)
        self.rotation.record_terminal("run-v", terminal_persisted=True)
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))

        self.assertEqual(persisted["version"], 1)
        self.assertEqual(persisted["next_character"], IRONCLAD)
        self.assertIsNone(persisted["active_run"])
        self.assertEqual(persisted["finalized_runs"], {"run-v": VIVHITE})


if __name__ == "__main__":
    unittest.main()
