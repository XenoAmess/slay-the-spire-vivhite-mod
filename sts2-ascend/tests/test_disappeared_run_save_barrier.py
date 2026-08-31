"""Regression coverage for runs that disappear before native save proof."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402
from character_profiles import VIVHITE_CHARACTER_ID  # noqa: E402
from character_rotation import IRONCLAD, VIVHITE  # noqa: E402


def _live_state(run_id: str, *, screen: str = "MAP", floor: int = 5) -> dict:
    return {
        "screen": screen,
        "run_id": run_id,
        "run": {
            "run_id": run_id,
            "character_id": VIVHITE_CHARACTER_ID,
            "current_hp": 60,
            "max_hp": 78,
            "gold": 99,
            "ascension": 0,
            "floor": floor,
            "deck": [],
        },
        "available_actions": [],
    }


def _game_over_state(run_id: str, *, floor: int = 5,
                     status: str = "verified", verified: bool = True,
                     error: str | None = None) -> dict:
    state = _live_state(run_id, screen="GAME_OVER", floor=floor)
    state["available_actions"] = ["return_to_main_menu"]
    state["game_over"] = {
        "phase": "summary_ready",
        "is_victory": False,
        "floor": floor,
        "can_return_to_main_menu": True,
        "save_status": status,
        "save_verified": verified,
        "save_error": error,
    }
    return state


class DisappearedRunNativeSaveBarrierTests(unittest.TestCase):
    @staticmethod
    def _agent(root: Path, run_id: str = "old-vivhite") -> agent_module.Agent:
        with mock.patch.object(agent_module, "KNOWLEDGE_DIR", root):
            instance = agent_module.Agent({"api_ports": [], "seed": 901})
        instance._review_health_ready_for_new_run = False
        instance._track(_live_state(run_id))
        instance.ctx.decisions = [
            {"screen": "MAP", "floor": 5, "action": "choose_map_node"}
            for _ in range(10)
        ]
        instance._save_run_progress({"floor": 5}, force=True)
        return instance

    @staticmethod
    def _stats_snapshot(instance: agent_module.Agent) -> dict:
        return copy.deepcopy(instance.know.stats)

    def test_replacement_without_proof_persists_wait_and_never_accounts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-disappeared-save-") as raw:
            root = Path(raw)
            instance = self._agent(root)
            before_stats = self._stats_snapshot(instance)
            before_rotation = instance.rotation.snapshot()
            review = mock.Mock()
            replacement = _live_state("replacement-vivhite", floor=0)

            with mock.patch.object(agent_module, "llm_review", review), \
                    mock.patch.object(agent_module, "log"):
                instance._track(replacement)
                instance._track(replacement)
                instance._track({"screen": "MAIN_MENU", "run": {}})
                # Even a direct accidental finalizer call remains fail-closed.
                instance._finalize(
                    victory=False, floor=5,
                    native_save_state=replacement)

            self.assertEqual(instance.ctx.run_id, "old-vivhite")
            self.assertFalse(instance.ctx.run_finalized)
            self.assertTrue(instance.ctx.finalize_requested)
            self.assertTrue(instance._native_save_transition_blocked)
            self.assertEqual(instance.know.stats, before_stats)
            after_rotation = instance.rotation.snapshot()
            self.assertEqual(after_rotation.active_run_id, "old-vivhite")
            self.assertEqual(after_rotation.target_character,
                             before_rotation.target_character)
            self.assertEqual(after_rotation.catchup_index,
                             before_rotation.catchup_index)
            self.assertEqual(after_rotation.next_character, VIVHITE)
            self.assertNotIn("old-vivhite", after_rotation.finalized_run_ids)
            review.enqueue_review.assert_not_called()

            evidence = instance.know.load_run_log("old-vivhite")
            self.assertTrue(evidence["in_progress"])
            self.assertEqual(
                evidence["native_save_wait"]["state"],
                "awaiting_native_save")
            self.assertEqual(
                evidence["native_save_wait"]["replacement_run_id"],
                "replacement-vivhite")

    def test_temporary_replacement_resumes_exact_old_live_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-disappeared-resume-") as raw:
            root = Path(raw)
            instance = self._agent(root)
            before_stats = self._stats_snapshot(instance)
            instance._track(_live_state("replacement-vivhite", floor=0))

            instance._track(_live_state("old-vivhite", floor=5))

            self.assertEqual(instance.ctx.run_id, "old-vivhite")
            self.assertIsNone(instance.ctx.native_save_wait)
            self.assertFalse(instance.ctx.finalize_requested)
            self.assertFalse(instance._native_save_transition_blocked)
            self.assertEqual(instance.know.stats, before_stats)
            persisted = instance.know.load_run_log("old-vivhite")
            self.assertNotIn("native_save_wait", persisted)

    def test_restart_restores_wait_and_blocks_replacement_until_old_run_returns(
            self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-disappeared-restart-") as raw:
            root = Path(raw)
            original = self._agent(root)
            original._track(_live_state("replacement-vivhite", floor=0))

            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", root):
                restarted = agent_module.Agent({"api_ports": [], "seed": 902})
            self.assertEqual(restarted.ctx.run_id, "old-vivhite")
            self.assertTrue(restarted.ctx.finalize_requested)
            self.assertEqual(
                restarted.ctx.native_save_wait["state"],
                "awaiting_native_save")

            restarted._track(_live_state("replacement-vivhite", floor=0))
            self.assertTrue(restarted._native_save_transition_blocked)
            self.assertEqual(
                restarted.rotation.snapshot().active_run_id, "old-vivhite")

            restarted._track(_live_state("old-vivhite", floor=5))
            self.assertFalse(restarted._native_save_transition_blocked)
            self.assertFalse(restarted.ctx.finalize_requested)
            self.assertIsNone(restarted.ctx.native_save_wait)

    def test_restart_without_incremental_log_uses_native_continue_to_recover(
            self) -> None:
        instance = object.__new__(agent_module.Agent)
        instance.ctx = agent_module.RunContext()
        instance._rotation_unresolved_run_id = "old-vivhite"
        instance._native_save_transition_blocked = False

        resumable_menu = {
            "screen": "MAIN_MENU",
            "run_id": "run_unknown",
            "run": {},
            "available_actions": ["continue_run", "abandon_run"],
        }
        with mock.patch.object(agent_module, "log") as logger:
            instance._track(resumable_menu)

        self.assertFalse(instance._native_save_transition_blocked)
        self.assertEqual(instance._rotation_unresolved_run_id, "old-vivhite")
        self.assertEqual(
            instance._native_continue_recovery_expected, "old-vivhite")
        logger.assert_called_once()
        self.assertIn("原生继续入口", logger.call_args.args[0])

        non_resumable_menu = copy.deepcopy(resumable_menu)
        non_resumable_menu["available_actions"] = ["open_character_select"]
        instance._track(non_resumable_menu)
        self.assertTrue(instance._native_save_transition_blocked)
        self.assertEqual(instance._rotation_unresolved_run_id, "old-vivhite")

    def test_native_continue_same_character_replaces_stale_id_without_scoring(
            self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-native-continue-") as raw:
            root = Path(raw)
            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", root):
                original = agent_module.Agent({"api_ports": [], "seed": 903})
                original.rotation.observe_active_run(
                    "old-vivhite", VIVHITE_CHARACTER_ID)
                restarted = agent_module.Agent({"api_ports": [], "seed": 904})

            before_stats = self._stats_snapshot(restarted)
            before_rotation = restarted.rotation.snapshot()
            menu = {
                "screen": "MAIN_MENU",
                "run_id": "run_unknown",
                "run": {},
                "available_actions": ["continue_run", "abandon_run"],
            }
            restarted._track(menu)
            native_state = _live_state(
                "native-vivhite", screen="COMBAT", floor=0)
            # The production loop binds the actual profile before transition
            # tracking.  That early bind must not emit a false rotation error.
            restarted._bind_profile_for_state(native_state)
            self.assertIsNone(getattr(
                restarted, "_rotation_runtime_error", None))
            self.assertEqual(
                restarted.rotation.snapshot().active_run_id, "old-vivhite")
            restarted._track(native_state)

            after = restarted.rotation.snapshot()
            self.assertEqual(after.active_run_id, "native-vivhite")
            self.assertEqual(after.active_character, VIVHITE)
            self.assertEqual(after.next_character, before_rotation.next_character)
            self.assertEqual(after.catchup_index, before_rotation.catchup_index)
            self.assertEqual(
                after.finalized_run_ids, before_rotation.finalized_run_ids)
            self.assertEqual(restarted.ctx.run_id, "native-vivhite")
            self.assertFalse(restarted._native_save_transition_blocked)
            before_global = before_stats.get("global", {})
            after_global = restarted.know.stats.get("global", {})
            for key in (
                    "runs", "wins", "losses", "floors_total",
                    "floor_sum_raw", "best_floor", "best_floor_raw"):
                self.assertEqual(
                    after_global.get(key), before_global.get(key), key)

            old_log = restarted._profile_knowledge["vivhite"].load_run_log(
                "old-vivhite")
            self.assertIsNotNone(old_log)
            self.assertFalse(old_log["in_progress"])
            self.assertTrue(old_log["lost_native_save"])
            self.assertTrue(old_log["excluded_from_learning"])
            self.assertEqual(
                old_log["replacement_run_id"], "native-vivhite")

    def test_save_error_does_not_account_verified_terminal_accounts_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-disappeared-finalize-") as raw:
            root = Path(raw)
            instance = self._agent(root)
            instance._track(_live_state("replacement-vivhite", floor=0))
            before_runs = int(instance.know.stats["global"]["runs"])
            review = mock.Mock()

            failed = _game_over_state(
                "old-vivhite", status="error", verified=False,
                error="profile_save_missing")
            with mock.patch.object(agent_module, "llm_review", review), \
                    mock.patch.object(agent_module, "autogit", None), \
                    mock.patch.object(agent_module, "log"):
                instance._track(failed)
                instance._finalize(
                    victory=False, floor=5, final_run=failed["run"],
                    native_save_state=failed)

            self.assertEqual(
                instance.know.stats["global"]["runs"], before_runs)
            self.assertFalse(instance.ctx.run_finalized)
            self.assertEqual(
                instance.rotation.snapshot().active_run_id, "old-vivhite")
            review.enqueue_review.assert_not_called()

            wrong_run_proof = _game_over_state("different-run")
            with mock.patch.object(agent_module, "llm_review", review), \
                    mock.patch.object(agent_module, "autogit", None), \
                    mock.patch.object(agent_module, "log"):
                instance._finalize(
                    victory=False, floor=5,
                    native_save_state=wrong_run_proof)
            self.assertEqual(
                instance.know.stats["global"]["runs"], before_runs)
            self.assertEqual(
                instance.rotation.snapshot().active_run_id, "old-vivhite")
            review.enqueue_review.assert_not_called()

            verified = _game_over_state("old-vivhite")
            with mock.patch.object(agent_module, "llm_review", review), \
                    mock.patch.object(agent_module, "autogit", None), \
                    mock.patch.object(agent_module, "log"):
                instance._track(verified)
                instance._finalize(
                    victory=False, floor=5, final_run=verified["run"],
                    native_save_state=verified)
                instance._finalize(
                    victory=False, floor=5, final_run=verified["run"],
                    native_save_state=verified)

            self.assertTrue(instance.ctx.run_finalized)
            self.assertEqual(
                instance.know.stats["global"]["runs"], before_runs + 1)
            rotation = instance.rotation.snapshot()
            self.assertIsNone(rotation.active_run_id)
            self.assertEqual(rotation.finalized_run_ids, ("old-vivhite",))
            self.assertEqual(rotation.next_character, IRONCLAD)
            review.enqueue_review.assert_called_once()
            terminal = instance.know.load_run_log("old-vivhite")
            self.assertFalse(terminal.get("in_progress", False))
            self.assertEqual(terminal["native_save"], {
                "run_id": "old-vivhite",
                "phase": "summary_ready",
                "save_status": "verified",
                "save_verified": True,
                "save_error": None,
            })


if __name__ == "__main__":
    unittest.main()
