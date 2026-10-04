"""Crash windows between manual hotkeys, durable exclusion and audit archival."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))
import agent as agent_module
import manual_control


def live(run_id="mixed-run"):
    return {"screen": "MAP", "run_id": run_id,
            "run": {"run_id": run_id, "character_id": "IRONCLAD", "floor": 5,
                    "ascension": 0, "current_hp": 70, "max_hp": 80,
                    "gold": 99, "deck": [], "relics": [], "potions": []}}


class AgentTakeoverRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sts2-takeover-recovery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.session = "1" * 32
        for module, name, value in (
                (agent_module, "KNOWLEDGE_DIR", self.root / "knowledge"),
                (manual_control, "RUNTIME_DIR", self.root / "runtime"),
                (manual_control, "SESSION_ID", self.session)):
            replacement = patch.object(module, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        logger = patch.object(agent_module, "log")
        logger.start()
        self.addCleanup(logger.stop)
        manual_control.initialize_control_state()

    def create(self):
        return agent_module.Agent({"api_ports": [], "seed": 123})

    def active(self):
        instance = self.create()
        instance._track(live())
        instance.ctx.decisions = [{"floor": 5, "action": "choose_map_node"}]
        return instance

    def test_f9_f10_without_poll_then_restart_excludes_and_acknowledges(self):
        first = self.active()
        baseline = copy.deepcopy(first.know.stats)
        first.know.commit_card_play("BEFORE_UNOBSERVED_F9")
        first.know.save()
        first._save_run_progress(live()["run"], force=True)
        manual_control.set_brain_enabled(False, source="hotkey-pause")
        manual_control.set_brain_enabled(True, source="hotkey-resume")

        restarted = self.create()
        self.assertEqual(restarted._seen_pause_generation, 0)
        self.assertFalse(restarted._manual_control_blocks(live()))
        self.assertTrue(restarted.ctx.human_assisted)
        self.assertEqual(restarted.know.stats, baseline)
        self.assertTrue(restarted.know.run_learning_is_excluded("mixed-run"))
        self.assertEqual(manual_control.read_control_state().acknowledged_pause_generation, 1)
        restarted.know.commit_card_play("AFTER_F10")
        self.assertEqual(restarted.know.stats, baseline)

        restarted._exclude_human_assisted_run(victory=False, floor=5)
        self.assertTrue(restarted.ctx.run_finalized)
        subsequent = self.create()
        self.assertEqual(subsequent._seen_pause_generation, 1)
        self.assertFalse(subsequent._manual_control_blocks(live("clean-new-run")))
        subsequent._track(live("clean-new-run"))
        self.assertFalse(subsequent.ctx.human_assisted)

    def test_unseen_epoch_on_empty_menu_also_excludes_old_active_identity(self):
        first = self.active()
        baseline = copy.deepcopy(first.know.stats)
        first.know.commit_card_play("BEFORE_F9")
        first.know.save()
        manual_control.set_brain_enabled(False, source="hotkey-pause")
        manual_control.set_brain_enabled(True, source="hotkey-resume")
        restarted = self.create()
        self.assertFalse(restarted._manual_control_blocks({"screen": "MAIN_MENU", "run": None}))
        self.assertTrue(restarted.ctx.human_assisted)
        self.assertTrue(restarted.ctx.run_finalized)
        self.assertEqual(restarted.know.stats, baseline)
        evidence = restarted.know.load_run_log("mixed-run")
        self.assertTrue(evidence["human_assisted"])
        self.assertTrue(evidence["in_progress"])
        self.assertFalse(restarted.rotation.snapshot().has_active_run)

    def test_failed_acknowledgement_retries_before_actions_resume(self):
        instance = self.active()
        manual_control.set_brain_enabled(False, source="hotkey-pause")
        manual_control.set_brain_enabled(True, source="hotkey-resume")
        with patch.object(agent_module, "acknowledge_pause_generation",
                          side_effect=OSError("ack temporarily locked")):
            self.assertTrue(instance._manual_control_blocks(live()))
        self.assertEqual(instance._seen_pause_generation, 0)
        self.assertFalse(instance._manual_control_blocks(live()))
        self.assertEqual(instance._seen_pause_generation, 1)

    def test_failed_audit_save_preserves_journal_and_active_slot_until_retry(self):
        for failure in (False, OSError("audit locked")):
            with self.subTest(failure=failure):
                instance = self.active()
                journal = instance.know.root / ".active_run_learning.json"
                options = ({"side_effect": failure} if isinstance(failure, Exception)
                           else {"return_value": failure})
                with patch.object(instance, "_save_run_progress", **options):
                    instance._exclude_human_assisted_run(victory=False, floor=5)
                self.assertFalse(instance.ctx.run_finalized)
                self.assertTrue(instance.ctx.finalize_requested)
                self.assertTrue(journal.exists())
                self.assertTrue(json.loads(journal.read_text(encoding="utf-8"))["excluded_from_learning"])
                self.assertEqual(instance.rotation.snapshot().active_run_id, "mixed-run")
                instance._exclude_human_assisted_run(victory=False, floor=5)
                self.assertTrue(instance.ctx.run_finalized)
                self.assertFalse(journal.exists())
                self.assertFalse(instance.rotation.snapshot().has_active_run)

    def test_unreadable_frame_keeps_epoch_pending_until_touched_run_is_identified(self):
        instance = self.create()
        manual_control.set_brain_enabled(False, source="hotkey-pause")
        manual_control.set_brain_enabled(True, source="hotkey-resume")
        self.assertTrue(instance._manual_control_blocks({"screen": "UNKNOWN", "run": None}))
        self.assertEqual(instance._seen_pause_generation, 0)
        self.assertEqual(manual_control.read_control_state().acknowledged_pause_generation, 0)
        self.assertFalse(instance._manual_control_blocks(live("first-human-run")))
        self.assertTrue(instance.ctx.human_assisted)
        self.assertTrue(instance.know.run_learning_is_excluded("first-human-run"))
        self.assertEqual(instance._seen_pause_generation, 1)

    def test_same_live_mixed_run_reappearing_cancels_failed_close_wait(self):
        instance = self.active()
        with patch.object(instance, "_save_run_progress", return_value=False):
            instance._exclude_human_assisted_run(victory=False, floor=5)
        self.assertTrue(instance.ctx.finalize_requested)
        instance._track(live())
        self.assertFalse(instance.ctx.finalize_requested)
        self.assertFalse(instance.ctx.run_finalized)
        self.assertTrue(instance.ctx.human_assisted)
        self.assertTrue(instance.know.run_learning_is_excluded("mixed-run"))
        self.assertEqual(instance.rotation.snapshot().active_run_id, "mixed-run")

    def test_acknowledgement_is_scoped_and_runner_mode_writes_preserve_it(self):
        manual_control.set_brain_enabled(False, source="hotkey-pause")
        manual_control.acknowledge_pause_generation(1)
        manual_control.set_brain_enabled(True, source="hotkey-resume")
        snapshot = manual_control.read_control_state()
        self.assertTrue(snapshot.enabled)
        self.assertEqual(snapshot.acknowledged_pause_generation, 1)
        self.assertEqual(manual_control.read_control_state(
            session_id="2" * 32).acknowledged_pause_generation, 0)
        manual_control.set_brain_enabled(False, source="next-pause")
        self.assertEqual(manual_control.read_control_state().pause_generation, 2)
        self.assertEqual(manual_control.read_control_state().acknowledged_pause_generation, 1)


if __name__ == "__main__":
    unittest.main()
