"""Fail-closed recovery for active runs with no native save/Continue evidence."""
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

import agent as agent_module  # noqa: E402
from character_profiles import VIVHITE_CHARACTER_ID  # noqa: E402
from character_rotation import (  # noqa: E402
    ORPHAN_EVIDENCE_VERSION,
    ORPHAN_RELEASE_REASON,
    CharacterRotation,
    CharacterRotationError,
    VIVHITE,
)


def _evidence(run_id: str = "orphan-v") -> dict:
    return {
        "version": ORPHAN_EVIDENCE_VERSION,
        "reason": ORPHAN_RELEASE_REASON,
        "run_id": run_id,
        "character_id": VIVHITE_CHARACTER_ID,
        "observed_at": "2026-09-01T15:50:02Z",
        "api": {
            "consecutive": True,
            "latest_state_version": 13,
            "samples": [
                {
                    "sequence": 1,
                    "observed_at": "2026-09-01T15:49:58Z",
                    "state_version": 13,
                    "screen": "MAIN_MENU",
                    "run_id": "run_unknown",
                    "run_empty": True,
                    "continue_run": False,
                },
                {
                    "sequence": 2,
                    "observed_at": "2026-09-01T15:49:59Z",
                    "state_version": 13,
                    "screen": "MAIN_MENU",
                    "run_id": "run_unknown",
                    "run_empty": True,
                    "continue_run": False,
                },
            ],
        },
        "native": {
            "probe_complete": True,
            "save": {"status": "no_matching_run"},
            "history": {"status": "empty"},
            "stmp": {"status": "zero_byte"},
            "probe_observed_at": "2026-09-01T15:50:01Z",
            "api_state_version": 13,
            "save_match": False,
            "history_match": False,
            "read_errors": [],
            "checked_paths": [
                {"kind": "progress.save", "status": "no_matching_run",
                 "path": "profile1/saves/progress.save", "bytes": 108791},
                {"kind": "history", "status": "empty",
                 "path": "profile1/saves/history", "bytes": 0},
                {"kind": "stmp", "status": "zero_byte",
                 "path": "profile1/saves/.current_run.stmp", "bytes": 0},
            ],
        },
    }


def _menu(*, continue_run: bool = False) -> dict:
    actions = ["open_character_select"]
    if continue_run:
        actions.insert(0, "continue_run")
    return {
        "screen": "MAIN_MENU",
        "state_version": 13,
        "run_id": "run_unknown",
        "run": None,
        "available_actions": actions,
    }


class OrphanRotationTests(unittest.TestCase):
    def test_release_is_audit_only_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-rotation-") as raw:
            rotation = CharacterRotation(Path(raw) / "character_rotation.json")
            rotation.observe_active_run("orphan-v", VIVHITE_CHARACTER_ID)
            before = rotation.snapshot()
            proof = _evidence()

            first = rotation.release_orphan_run(
                "orphan-v", evidence=proof, character_id=VIVHITE_CHARACTER_ID)
            self.assertTrue(first.released)
            after = rotation.snapshot()
            self.assertIsNone(after.active_run_id)
            self.assertEqual(after.orphaned_run_ids, ("orphan-v",))
            self.assertEqual(after.finalized_run_ids, before.finalized_run_ids)
            self.assertEqual(after.next_character, before.next_character)
            self.assertEqual(after.catchup_index, before.catchup_index)
            self.assertFalse(first.quota_consumed)

            replay = rotation.release_orphan_run(
                "orphan-v", evidence=proof, character_id=VIVHITE_CHARACTER_ID)
            self.assertFalse(replay.released)
            with self.assertRaises(CharacterRotationError):
                rotation.record_terminal(
                    "orphan-v", terminal_persisted=True,
                    character_id=VIVHITE_CHARACTER_ID)

            persisted = json.loads(
                (Path(raw) / "character_rotation.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["finalized_runs"], {})
            self.assertEqual(
                persisted["orphaned_runs"]["orphan-v"]["evidence"],
                proof,
            )

    def test_release_rejects_weak_or_mismatched_negative_proof(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-rotation-") as raw:
            rotation = CharacterRotation(Path(raw) / "character_rotation.json")
            rotation.observe_active_run("orphan-v", VIVHITE_CHARACTER_ID)
            weak = copy.deepcopy(_evidence())
            weak["api"]["samples"] = weak["api"]["samples"][:1]
            with self.assertRaises(CharacterRotationError):
                rotation.release_orphan_run("orphan-v", evidence=weak)
            mismatch = copy.deepcopy(_evidence())
            mismatch["run_id"] = "other-run"
            with self.assertRaises(CharacterRotationError):
                rotation.release_orphan_run("orphan-v", evidence=mismatch)
            self.assertEqual(rotation.snapshot().active_run_id, "orphan-v")

    def test_negative_proof_requires_distinct_samples_and_save_history_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-proof-shape-") as raw:
            rotation = CharacterRotation(Path(raw) / "character_rotation.json")
            rotation.observe_active_run("orphan-v", VIVHITE_CHARACTER_ID)
            duplicate = copy.deepcopy(_evidence())
            duplicate["api"]["samples"][1]["sequence"] = 1
            duplicate["api"]["samples"][1]["observed_at"] = (
                duplicate["api"]["samples"][0]["observed_at"])
            with self.assertRaises(CharacterRotationError):
                rotation.release_orphan_run("orphan-v", evidence=duplicate)

            missing_history = copy.deepcopy(_evidence())
            missing_history["native"]["checked_paths"] = [
                missing_history["native"]["checked_paths"][0]]
            with self.assertRaises(CharacterRotationError):
                rotation.release_orphan_run("orphan-v", evidence=missing_history)


class OrphanAgentTests(unittest.TestCase):
    def _agent(self, root: Path) -> agent_module.Agent:
        with mock.patch.object(agent_module, "KNOWLEDGE_DIR", root):
            instance = agent_module.Agent({"api_ports": [], "seed": 999})
        instance.rotation.observe_active_run("orphan-v", VIVHITE_CHARACTER_ID)
        instance._rotation_unresolved_run_id = "orphan-v"
        return instance

    def test_two_menu_snapshots_and_probe_release_without_stats_or_quota(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-agent-") as raw:
            instance = self._agent(Path(raw))
            vivhite = instance._profile_knowledge["vivhite"]
            before_stats = copy.deepcopy(vivhite.stats)
            before_rotation = instance.rotation.snapshot()
            instance._orphan_recovery_evidence_provider = (
                lambda _state, _run_id: _evidence())
            with mock.patch.object(agent_module, "log"):
                instance._track(_menu())
                self.assertTrue(instance._native_save_transition_blocked)
                instance._track(_menu())

            self.assertFalse(instance._native_save_transition_blocked)
            self.assertEqual(instance.ctx.run_id, "run_unknown")
            self.assertEqual(vivhite.stats, before_stats)
            after = instance.rotation.snapshot()
            self.assertIsNone(after.active_run_id)
            self.assertEqual(after.orphaned_run_ids, ("orphan-v",))
            self.assertEqual(after.next_character, before_rotation.next_character)
            self.assertEqual(after.catchup_index, before_rotation.catchup_index)
            audit = vivhite.load_run_log("orphan-v")
            self.assertTrue(audit["orphaned"])
            self.assertTrue(audit["excluded_from_learning"])
            self.assertFalse(audit["in_progress"])
            self.assertIsNone(audit["native_save"])

    def test_action_dto_variants_are_normalized_for_orphan_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-action-dto-") as raw:
            instance = self._agent(Path(raw))
            instance._orphan_recovery_evidence_provider = (
                lambda _state, _run_id: _evidence())
            menu = _menu()
            menu["available_actions"] = [{"name": "OPEN_CHARACTER_SELECT"}]
            with mock.patch.object(agent_module, "log"):
                instance._track(menu)
                instance._track(menu)
            self.assertIsNone(instance.rotation.snapshot().active_run_id)

            # A Continue action represented by any supported object key must
            # remain a recovery prompt, never an orphan-release candidate.
            second = self._agent(Path(raw) / "second")
            second._orphan_recovery_evidence_provider = (
                lambda _state, _run_id: _evidence())
            continue_menu = _menu()
            continue_menu["available_actions"] = [{"action_id": "continue_run"}]
            with mock.patch.object(agent_module, "log"):
                second._track(continue_menu)
                second._track(continue_menu)
            self.assertEqual(
                second.rotation.snapshot().active_run_id, "orphan-v")
            self.assertEqual(
                second._native_continue_recovery_expected, "orphan-v")

    def test_no_probe_or_continue_entry_remains_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-agent-") as raw:
            instance = self._agent(Path(raw))
            instance._track(_menu())
            instance._track(_menu(continue_run=True))
            self.assertEqual(
                instance.rotation.snapshot().active_run_id, "orphan-v")
            self.assertTrue(instance._native_save_transition_blocked is False)
            # The continue entry is merely observed; it is not clicked here.
            self.assertEqual(
                instance._native_continue_recovery_expected, "orphan-v")

    def test_rotation_write_failure_keeps_old_identity_blocked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-agent-") as raw:
            instance = self._agent(Path(raw))
            instance._orphan_recovery_evidence_provider = (
                lambda _state, _run_id: _evidence())
            with mock.patch.object(
                    instance.rotation, "release_orphan_run",
                    side_effect=OSError("injected rotation failure")), \
                    mock.patch.object(agent_module, "log"):
                instance._track(_menu())
                instance._track(_menu())
            self.assertEqual(
                instance.rotation.snapshot().active_run_id, "orphan-v")
            self.assertTrue(instance._native_save_transition_blocked)
            audit = instance._profile_knowledge["vivhite"].load_run_log("orphan-v")
            self.assertTrue(audit["orphan_release"]["state"] == "prepared")

    def test_restart_recovers_prepared_marker_and_explicit_retry(self) -> None:
        """A crash between run-log prepare and rotation CAS is recoverable."""
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-restart-") as raw:
            root = Path(raw)
            original = self._agent(root)
            original._orphan_recovery_evidence_provider = (
                lambda _state, _run_id: _evidence())
            with mock.patch.object(
                    original.rotation, "release_orphan_run",
                    side_effect=OSError("crash before CAS")), \
                    mock.patch.object(agent_module, "log"):
                original._track(_menu())
                original._track(_menu())
            prepared = original._profile_knowledge["vivhite"].load_run_log(
                "orphan-v")
            self.assertEqual(prepared["orphan_release"]["state"], "prepared")
            self.assertEqual(prepared["orphan_release"]["attempts"], 1)

            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", root), \
                    mock.patch.object(agent_module, "log"):
                restarted = agent_module.Agent({"api_ports": [], "seed": 904})
            self.assertEqual(restarted._rotation_unresolved_run_id, "orphan-v")
            self.assertEqual(
                restarted._orphan_release_pending["attempts"], 1)
            self.assertTrue(restarted._native_save_transition_blocked)
            self.assertEqual(
                restarted.rotation.snapshot().active_run_id, "orphan-v")

            result = restarted.retry_pending_orphan_release(state=_menu())
            self.assertTrue(result.released)
            self.assertIsNone(restarted.rotation.snapshot().active_run_id)
            self.assertIsNone(restarted._orphan_release_pending)
            audit = restarted._profile_knowledge["vivhite"].load_run_log(
                "orphan-v")
            self.assertEqual(audit["orphan_release"]["state"], "released")
            self.assertEqual(
                audit["native_save_wait"]["state"], "orphan_released")

    def test_restart_reconciles_cas_that_landed_before_crash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-cas-restart-") as raw:
            root = Path(raw)
            original = self._agent(root)
            original._orphan_recovery_evidence_provider = (
                lambda _state, _run_id: _evidence())
            with mock.patch.object(agent_module, "log"):
                original._track(_menu())
                original._track(_menu())
            proof = _evidence()
            original.rotation.release_orphan_run(
                "orphan-v", evidence=proof,
                character_id=VIVHITE_CHARACTER_ID)
            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", root), \
                    mock.patch.object(agent_module, "log"):
                restarted = agent_module.Agent({"api_ports": [], "seed": 905})
            self.assertIsNone(restarted.rotation.snapshot().active_run_id)
            audit = restarted._profile_knowledge["vivhite"].load_run_log(
                "orphan-v")
            self.assertEqual(audit["orphan_release"]["state"], "released")
            self.assertEqual(
                audit["native_save_wait"]["state"], "orphan_released")

    def test_provider_proof_must_bind_latest_state_version(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-freshness-") as raw:
            instance = self._agent(Path(raw))
            instance._orphan_recovery_evidence_provider = (
                lambda _state, _run_id: _evidence())
            stale = _menu()
            stale["state_version"] = 14
            with mock.patch.object(agent_module, "log"):
                instance._track(stale)
                instance._track(stale)
            self.assertEqual(
                instance.rotation.snapshot().active_run_id, "orphan-v")
            self.assertTrue(instance._native_save_transition_blocked)

    def test_malformed_menu_payload_never_counts_as_two_safe_samples(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-shape-") as raw:
            instance = self._agent(Path(raw))
            provider = mock.Mock(return_value=_evidence())
            instance._orphan_recovery_evidence_provider = provider
            malformed = {"screen": "MAIN_MENU"}
            with mock.patch.object(agent_module, "log"):
                instance._track(malformed)
                instance._track(malformed)
            truncated = _menu()
            truncated["run"] = {}
            with mock.patch.object(agent_module, "log"):
                instance._track(truncated)
                instance._track(truncated)
            provider.assert_not_called()
            self.assertEqual(
                instance.rotation.snapshot().active_run_id, "orphan-v")
            self.assertTrue(instance._native_save_transition_blocked)

    def test_prepared_retry_is_bounded_and_keeps_active_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-retry-cap-") as raw:
            instance = self._agent(Path(raw))
            proof = _evidence()
            for _attempt in range(3):
                with mock.patch.object(
                        instance.rotation, "release_orphan_run",
                        side_effect=OSError("transient CAS failure")):
                    with self.assertRaises(OSError):
                        instance.release_unrecoverable_orphan(proof)
            with self.assertRaises(CharacterRotationError):
                instance.release_unrecoverable_orphan(proof)
            self.assertEqual(
                instance.rotation.snapshot().active_run_id, "orphan-v")
            audit = instance._profile_knowledge["vivhite"].load_run_log(
                "orphan-v")
            self.assertEqual(audit["orphan_release"]["state"], "prepared")
            self.assertEqual(audit["orphan_release"]["attempts"], 3)

    def test_stopped_stack_one_shot_uses_same_transaction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-orphan-once-") as raw:
            root = Path(raw)
            rotation = CharacterRotation(root / "character_rotation.json")
            rotation.observe_active_run("orphan-v", VIVHITE_CHARACTER_ID)
            result = agent_module.release_orphan_run_once(root, _evidence())
            self.assertTrue(result.released)
            self.assertIsNone(rotation.snapshot().active_run_id)
            self.assertEqual(rotation.snapshot().orphaned_run_ids, ("orphan-v",))
            # Replaying the exact one-shot evidence is idempotent and still does
            # not turn the row into a terminal/finalized run.
            replay = agent_module.release_orphan_run_once(root, _evidence())
            self.assertFalse(replay.released)
            self.assertEqual(rotation.snapshot().finalized_run_ids, ())


if __name__ == "__main__":
    unittest.main()
