"""Global Brain stop/start hotkey and human-takeover regressions."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402
import client as client_module  # noqa: E402
import manual_control  # noqa: E402
from character_rotation import CharacterRotation, VIVHITE  # noqa: E402


VIVHITE_ID = "VIVHITE_CHARACTER_VIVHITE_CHARACTER"


class ManualControlStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-manual-control-")
        self.root = Path(self.temp.name)
        self.session = "a" * 32

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_missing_is_enabled_but_malformed_explicit_state_fails_closed(self) -> None:
        missing = manual_control.read_control_state(self.root, self.session)
        self.assertTrue(missing.enabled)
        path = manual_control.control_path(self.root, self.session)
        path.write_text("{broken", encoding="utf-8")
        malformed = manual_control.read_control_state(self.root, self.session)
        self.assertTrue(malformed.paused)
        self.assertTrue(malformed.error)

    def test_pause_resume_is_atomic_idempotent_and_session_scoped(self) -> None:
        started = manual_control.initialize_control_state(self.root, self.session)
        self.assertTrue(started.enabled)
        self.assertEqual(started.pause_generation, 0)

        paused = manual_control.set_brain_enabled(
            False, source="test-pause", runtime_dir=self.root,
            session_id=self.session)
        self.assertTrue(paused.paused)
        self.assertEqual(paused.pause_generation, 1)
        repeated = manual_control.set_brain_enabled(
            False, source="test-repeat", runtime_dir=self.root,
            session_id=self.session)
        self.assertEqual(repeated.pause_generation, 1)

        resumed = manual_control.set_brain_enabled(
            True, source="test-resume", runtime_dir=self.root,
            session_id=self.session)
        self.assertTrue(resumed.enabled)
        self.assertEqual(resumed.pause_generation, 1)
        self.assertTrue(
            manual_control.read_control_state(self.root, "b" * 32).enabled)

        payload = json.loads(manual_control.control_path(
            self.root, self.session).read_text(encoding="utf-8"))
        self.assertEqual(payload["pause_hotkey"], "Ctrl+Alt+F9")
        self.assertEqual(payload["resume_hotkey"], "Ctrl+Alt+F10")

    def test_hotkey_ids_dispatch_to_distinct_modes(self) -> None:
        controller = manual_control.GlobalHotkeyController(
            runtime_dir=self.root, session_id=self.session)
        controller._set_mode = mock.Mock()  # type: ignore[method-assign]
        self.assertTrue(controller.handle_hotkey_id(
            manual_control._PAUSE_HOTKEY_ID))
        self.assertTrue(controller.handle_hotkey_id(
            manual_control._RESUME_HOTKEY_ID))
        self.assertFalse(controller.handle_hotkey_id(123))
        self.assertEqual(
            controller._set_mode.call_args_list,
            [mock.call(False), mock.call(True)])


class ManualControlIntegrationTests(unittest.TestCase):
    def test_client_gate_runs_before_any_gameplay_post(self) -> None:
        client = client_module.Sts2Client(ports=[])
        client.base_url = "http://127.0.0.1:8080"
        client._request = mock.Mock(return_value={})  # type: ignore[method-assign]
        with mock.patch.object(
                client_module, "ensure_action_allowed",
                side_effect=manual_control.BrainControlPaused("paused")):
            with self.assertRaises(manual_control.BrainControlPaused):
                client.act("end_turn")
        client._request.assert_not_called()

    def test_agent_marks_pause_epoch_and_keeps_run_out_of_learning(self) -> None:
        instance = object.__new__(agent_module.Agent)
        instance.ctx = agent_module.RunContext()
        instance.ctx.reset_for("auto-run", 0, 1)
        instance.ctx.decisions = [{"floor": 7}]
        instance.know = SimpleNamespace(stats={"global": {"runs": 0}})
        instance._manual_pause_active = False
        instance._manual_run_ids = set()
        instance._seen_pause_generation = 0
        instance._save_run_progress = mock.Mock()
        instance._dashboard_connection = mock.Mock()
        state = {
            "screen": "COMBAT", "run_id": "auto-run",
            "run": {"run_id": "auto-run", "floor": 7,
                    "ascension": 0, "character_id": VIVHITE_ID},
        }
        paused = manual_control.ControlSnapshot(
            enabled=False, pause_generation=1, source="test-hotkey")
        with mock.patch.object(agent_module, "read_control_state", return_value=paused):
            self.assertTrue(instance._manual_control_blocks(state))
        self.assertTrue(instance.ctx.human_assisted)
        self.assertIn("auto-run", instance._manual_run_ids)
        instance._save_run_progress.assert_called()

        resumed = manual_control.ControlSnapshot(
            enabled=True, pause_generation=1, source="test-resume")
        with mock.patch.object(agent_module, "read_control_state", return_value=resumed):
            self.assertFalse(instance._manual_control_blocks(state))
        instance._dashboard_connection.assert_called_with(
            "connected", "Brain 已恢复自主操作")

    def test_human_controlled_run_does_not_finalize_stats_or_consume_rotation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-manual-rotation-") as root:
            rotation = CharacterRotation.from_knowledge_root(root)
            rotation.observe_active_run("mixed-run", VIVHITE_ID)
            before = rotation.snapshot()
            self.assertEqual(before.target_character, VIVHITE)

            instance = object.__new__(agent_module.Agent)
            instance.ctx = agent_module.RunContext()
            instance.ctx.reset_for("mixed-run", 0, 1)
            instance.ctx.character_id = VIVHITE_ID
            instance.ctx.human_assisted = True
            instance.ctx.decisions = [{"floor": 9}]
            instance.rotation = rotation
            instance._manual_run_ids = {"mixed-run"}
            instance._save_run_progress = mock.Mock()
            with mock.patch.object(agent_module, "finalize_run") as finalize, \
                    mock.patch.object(agent_module, "log"):
                instance._finalize(victory=False, floor=9)

            finalize.assert_not_called()
            self.assertTrue(instance.ctx.run_finalized)
            after = CharacterRotation.from_knowledge_root(root).snapshot()
            self.assertFalse(after.has_active_run)
            self.assertEqual(after.target_character, before.target_character)
            self.assertEqual(after.catchup_index, before.catchup_index)
            self.assertNotIn("mixed-run", after.finalized_run_ids)


if __name__ == "__main__":
    unittest.main()

