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
    BALANCED_MODE,
    CATCHUP_MODE,
    CATCHUP_ROTATION,
    CharacterRotation,
    CharacterRotationError,
    IRONCLAD,
    STATE_VERSION,
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

    def _set_persisted_runs(self, *, vivhite: int, ironclad: int) -> None:
        """Persist the same profile totals read by the production scheduler."""
        root = self.state_path.parent
        vivhite_stats = root / "profiles" / "vivhite" / "stats.json"
        vivhite_stats.parent.mkdir(parents=True, exist_ok=True)
        (root / "stats.json").write_text(
            json.dumps({"global": {"runs": ironclad}}),
            encoding="utf-8",
        )
        vivhite_stats.write_text(
            json.dumps({"global": {"runs": vivhite}}),
            encoding="utf-8",
        )

    def _complete(
            self, rotation: CharacterRotation, run_id: str, character: str,
            *, vivhite: int, ironclad: int):
        character_id = VIVHITE_ID if character == VIVHITE else IRONCLAD_ID
        self.assertEqual(rotation.target_character, character)
        rotation.observe_active_run(run_id, character_id)
        self._set_persisted_runs(vivhite=vivhite, ironclad=ironclad)
        return rotation.record_terminal(
            run_id, terminal_persisted=True, character_id=character_id)

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

    def test_0_to_1229_runs_strict_four_vivhite_one_ironclad(self) -> None:
        self._set_persisted_runs(vivhite=0, ironclad=1229)
        vivhite_runs = 0
        ironclad_runs = 1229
        observed: list[str] = []

        for index, expected in enumerate(CATCHUP_ROTATION * 2):
            choice = self.rotation.resolve_selection(_characters())
            self.assertTrue(choice.ready)
            self.assertEqual(choice.target_character, expected)
            if expected == VIVHITE:
                vivhite_runs += 1
            else:
                ironclad_runs += 1
            terminal = self._complete(
                self.rotation, f"catchup-{index}", expected,
                vivhite=vivhite_runs, ironclad=ironclad_runs)
            self.assertTrue(terminal.advanced)
            self.assertTrue(terminal.quota_consumed)
            self.assertEqual(terminal.schedule_mode, CATCHUP_MODE)
            observed.append(expected)

        self.assertEqual(observed, list(CATCHUP_ROTATION * 2))
        snapshot = self.rotation.snapshot()
        self.assertEqual(snapshot.schedule_mode, CATCHUP_MODE)
        self.assertFalse(snapshot.catchup_completed)
        self.assertEqual(snapshot.catchup_index, 0)
        self.assertEqual(snapshot.next_character, VIVHITE)
        self.assertEqual(snapshot.vivhite_runs, 8)
        self.assertEqual(snapshot.ironclad_runs, 1231)

    def test_catchup_phase_survives_process_restart(self) -> None:
        self._set_persisted_runs(vivhite=0, ironclad=1229)
        self._complete(
            self.rotation, "restart-v1", VIVHITE,
            vivhite=1, ironclad=1229)
        self._complete(
            self.rotation, "restart-v2", VIVHITE,
            vivhite=2, ironclad=1229)

        reloaded = CharacterRotation(self.state_path)
        snapshot = reloaded.snapshot()
        self.assertEqual(snapshot.schedule_mode, CATCHUP_MODE)
        self.assertEqual(snapshot.catchup_index, 2)
        self.assertEqual(snapshot.next_character, VIVHITE)
        third = self._complete(
            reloaded, "restart-v3", VIVHITE,
            vivhite=3, ironclad=1229)
        self.assertTrue(third.quota_consumed)
        self.assertEqual(reloaded.snapshot().catchup_index, 3)

    def test_catchup_quota_moves_only_after_persisted_unique_terminal(self) -> None:
        self._set_persisted_runs(vivhite=0, ironclad=1229)
        self.rotation.observe_active_run("quota-v1", VIVHITE_ID)
        before = self.state_path.read_bytes()

        rejected = self.rotation.record_terminal(
            "quota-v1", terminal_persisted=False)
        self.assertFalse(rejected.advanced)
        self.assertFalse(rejected.quota_consumed)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(self.rotation.snapshot().catchup_index, 0)

        self._set_persisted_runs(vivhite=1, ironclad=1229)
        accepted = self.rotation.record_terminal(
            "quota-v1", terminal_persisted=True)
        self.assertTrue(accepted.advanced)
        self.assertTrue(accepted.quota_consumed)
        self.assertEqual(self.rotation.snapshot().catchup_index, 1)

        duplicate = self.rotation.record_terminal(
            "quota-v1", terminal_persisted=True)
        self.assertFalse(duplicate.advanced)
        self.assertFalse(duplicate.quota_consumed)
        self.assertEqual(self.rotation.snapshot().catchup_index, 1)

        reloaded = CharacterRotation(self.state_path)
        duplicate_after_restart = reloaded.record_terminal(
            "quota-v1", terminal_persisted=True)
        self.assertFalse(duplicate_after_restart.advanced)
        self.assertFalse(duplicate_after_restart.quota_consumed)
        self.assertEqual(reloaded.snapshot().catchup_index, 1)

    def test_parity_latches_balanced_alternation_without_reentering_catchup(
            self) -> None:
        self._set_persisted_runs(vivhite=1228, ironclad=1229)
        parity = self._complete(
            self.rotation, "parity-v", VIVHITE,
            vivhite=1229, ironclad=1229)
        self.assertEqual(parity.schedule_mode, BALANCED_MODE)
        self.assertEqual(parity.next_character, IRONCLAD)

        after_parity = self.rotation.snapshot()
        self.assertTrue(after_parity.catchup_completed)
        self.assertEqual(after_parity.schedule_mode, BALANCED_MODE)

        # A balanced Ironclad run makes Vivhite temporarily trail by one again.
        # The completion latch prevents an accidental return to the 4:1 schedule.
        ironclad = self._complete(
            self.rotation, "balanced-i", IRONCLAD,
            vivhite=1229, ironclad=1230)
        self.assertEqual(ironclad.schedule_mode, BALANCED_MODE)
        self.assertEqual(ironclad.next_character, VIVHITE)

        reloaded = CharacterRotation(self.state_path)
        behind_again = reloaded.snapshot()
        self.assertEqual(behind_again.vivhite_runs, 1229)
        self.assertEqual(behind_again.ironclad_runs, 1230)
        self.assertEqual(behind_again.schedule_mode, BALANCED_MODE)
        self.assertEqual(behind_again.next_character, VIVHITE)

        vivhite = self._complete(
            reloaded, "balanced-v", VIVHITE,
            vivhite=1230, ironclad=1230)
        self.assertEqual(vivhite.schedule_mode, BALANCED_MODE)
        self.assertEqual(vivhite.next_character, IRONCLAD)

    def test_api_actual_mismatch_resumes_but_does_not_consume_target_slot(
            self) -> None:
        self._set_persisted_runs(vivhite=0, ironclad=1229)
        self.assertEqual(self.rotation.target_character, VIVHITE)

        observed = self.rotation.observe_active_run(
            "preexisting-ironclad", IRONCLAD_ID)
        self.assertEqual(observed.target_character, IRONCLAD)
        self.assertEqual(observed.next_character, VIVHITE)
        self.assertEqual(observed.catchup_index, 0)

        reloaded = CharacterRotation(self.state_path)
        restored = reloaded.snapshot()
        self.assertEqual(restored.active_run_id, "preexisting-ironclad")
        self.assertEqual(restored.target_character, IRONCLAD)

        self._set_persisted_runs(vivhite=0, ironclad=1230)
        terminal = reloaded.record_terminal(
            "preexisting-ironclad", terminal_persisted=True,
            character_id=IRONCLAD_ID)
        self.assertTrue(terminal.advanced)
        self.assertFalse(terminal.quota_consumed)
        self.assertEqual(terminal.next_character, VIVHITE)
        self.assertEqual(reloaded.snapshot().catchup_index, 0)

        first_scheduled = self._complete(
            reloaded, "scheduled-v1", VIVHITE,
            vivhite=1, ironclad=1230)
        self.assertTrue(first_scheduled.quota_consumed)
        self.assertEqual(reloaded.snapshot().catchup_index, 1)

    def test_v1_active_vivhite_consumes_catchup_slot_zero(self) -> None:
        self._set_persisted_runs(vivhite=3, ironclad=1231)
        self.state_path.write_text(json.dumps({
            "version": 1,
            "next_character": IRONCLAD,
            "active_run": {
                "run_id": "PNQXCZ7X1UZ9",
                "character": VIVHITE,
                "character_id": VIVHITE_ID,
            },
            "finalized_runs": {},
        }), encoding="utf-8")

        migrated = CharacterRotation(self.state_path)
        active = migrated.snapshot()
        self.assertEqual(active.schedule_mode, CATCHUP_MODE)
        self.assertEqual(active.catchup_index, 0)
        self.assertEqual(active.target_character, VIVHITE)
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["active_run"]["scheduled_character"], VIVHITE)

        self._set_persisted_runs(vivhite=4, ironclad=1231)
        terminal = migrated.record_terminal(
            "PNQXCZ7X1UZ9", terminal_persisted=True,
            character_id=VIVHITE_ID)
        self.assertTrue(terminal.quota_consumed)
        self.assertEqual(migrated.snapshot().catchup_index, 1)

        vivhite_runs = 4
        ironclad_runs = 1231
        remaining_cycle = CATCHUP_ROTATION[1:]
        self.assertEqual(
            remaining_cycle, (VIVHITE, VIVHITE, VIVHITE, IRONCLAD))
        for index, expected in enumerate(remaining_cycle, start=1):
            if expected == VIVHITE:
                vivhite_runs += 1
            else:
                ironclad_runs += 1
            result = self._complete(
                migrated, f"after-active-v-{index}", expected,
                vivhite=vivhite_runs, ironclad=ironclad_runs)
            self.assertTrue(result.quota_consumed)

        completed_cycle = migrated.snapshot()
        self.assertEqual(completed_cycle.catchup_index, 0)
        self.assertEqual(completed_cycle.next_character, VIVHITE)

    def test_v1_active_ironclad_does_not_consume_catchup_slot_zero(self) -> None:
        self._set_persisted_runs(vivhite=3, ironclad=1231)
        self.state_path.write_text(json.dumps({
            "version": 1,
            "next_character": IRONCLAD,
            "active_run": {
                "run_id": "legacy-active-ironclad",
                "character": IRONCLAD,
                "character_id": IRONCLAD_ID,
            },
            "finalized_runs": {},
        }), encoding="utf-8")

        migrated = CharacterRotation(self.state_path)
        active = migrated.snapshot()
        self.assertEqual(active.target_character, IRONCLAD)
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertIsNone(
            persisted["active_run"]["scheduled_character"])

        self._set_persisted_runs(vivhite=3, ironclad=1232)
        terminal = migrated.record_terminal(
            "legacy-active-ironclad", terminal_persisted=True,
            character_id=IRONCLAD_ID)
        self.assertFalse(terminal.quota_consumed)
        after_active = migrated.snapshot()
        self.assertEqual(after_active.catchup_index, 0)
        self.assertEqual(after_active.next_character, VIVHITE)

        vivhite_runs = 3
        ironclad_runs = 1232
        for index, expected in enumerate(CATCHUP_ROTATION):
            if expected == VIVHITE:
                vivhite_runs += 1
            else:
                ironclad_runs += 1
            result = self._complete(
                migrated, f"after-active-i-{index}", expected,
                vivhite=vivhite_runs, ironclad=ironclad_runs)
            self.assertTrue(result.quota_consumed)
        self.assertEqual(migrated.snapshot().catchup_index, 0)

    def test_v1_state_migrates_to_fresh_catchup_cycle_when_behind(self) -> None:
        self._set_persisted_runs(vivhite=0, ironclad=1229)
        self.state_path.write_text(json.dumps({
            "version": 1,
            "next_character": IRONCLAD,
            "active_run": None,
            "finalized_runs": {"legacy-v": VIVHITE},
        }), encoding="utf-8")

        snapshot = CharacterRotation(self.state_path).snapshot()
        self.assertEqual(snapshot.schedule_mode, CATCHUP_MODE)
        self.assertEqual(snapshot.catchup_index, 0)
        self.assertEqual(snapshot.next_character, VIVHITE)
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["version"], STATE_VERSION)
        self.assertFalse(persisted["catchup_completed"])

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

    def test_native_continue_replaces_only_identity_without_consuming_slot(
            self) -> None:
        self.rotation.observe_active_run("stale-v", VIVHITE_ID)
        before = self.rotation.snapshot()

        after = self.rotation.reconcile_native_continue(
            "stale-v", "native-v", VIVHITE_ID)

        self.assertEqual(after.active_run_id, "native-v")
        self.assertEqual(after.active_character, VIVHITE)
        self.assertEqual(after.next_character, before.next_character)
        self.assertEqual(after.catchup_index, before.catchup_index)
        self.assertEqual(after.schedule_mode, before.schedule_mode)
        self.assertEqual(after.finalized_run_ids, before.finalized_run_ids)
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["active_run"]["scheduled_character"],
            VIVHITE,
        )

    def test_native_continue_requires_exact_old_identity(self) -> None:
        self.rotation.observe_active_run("stale-v", VIVHITE_ID)

        with self.assertRaises(CharacterRotationError):
            self.rotation.reconcile_native_continue(
                "different-old", "native-v", VIVHITE_ID)

        self.assertEqual(
            self.rotation.snapshot().active_run_id, "stale-v")

    def test_native_continue_cannot_change_character(self) -> None:
        self.rotation.observe_active_run("stale-v", VIVHITE_ID)

        with self.assertRaises(CharacterRotationError):
            self.rotation.reconcile_native_continue(
                "stale-v", "native-i", IRONCLAD_ID)

        self.assertEqual(
            self.rotation.snapshot().active_run_id, "stale-v")

    def test_unknown_terminal_character_cannot_guess_and_advance(self) -> None:
        with self.assertRaises(CharacterRotationError):
            self.rotation.record_terminal(
                "unobserved", terminal_persisted=True)
        self.assertEqual(self.rotation.target_character, VIVHITE)
        self.assertFalse(self.state_path.exists())

    def test_corrupt_active_slot_cannot_skip_the_durable_next_character(
            self) -> None:
        self.rotation.observe_active_run("active-v", VIVHITE_ID)
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        persisted["next_character"] = IRONCLAD
        self.state_path.write_text(json.dumps(persisted), encoding="utf-8")

        with self.assertRaises(CharacterRotationError):
            CharacterRotation(self.state_path).snapshot()

    def test_persisted_schema_contains_active_and_idempotence_facts(self) -> None:
        self.rotation.observe_active_run("run-v", VIVHITE_ID)
        self.rotation.record_terminal("run-v", terminal_persisted=True)
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))

        self.assertEqual(persisted["version"], STATE_VERSION)
        self.assertEqual(persisted["next_character"], IRONCLAD)
        self.assertEqual(persisted["schedule_mode"], BALANCED_MODE)
        self.assertTrue(persisted["catchup_completed"])
        self.assertEqual(persisted["catchup_index"], 0)
        self.assertEqual(persisted["last_completed_character"], VIVHITE)
        self.assertIsNone(persisted["active_run"])
        self.assertEqual(persisted["finalized_runs"], {"run-v": VIVHITE})


if __name__ == "__main__":
    unittest.main()
