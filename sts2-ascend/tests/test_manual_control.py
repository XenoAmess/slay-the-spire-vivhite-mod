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
from character_profiles import ProfileStore  # noqa: E402
from knowledge import Knowledge  # noqa: E402


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
    @staticmethod
    def _disk_stats(root: Path) -> dict:
        return json.loads((root / "stats.json").read_text(encoding="utf-8"))

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

    def test_track_captures_profile_baseline_before_first_run_observation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-manual-run-start-") as root_raw:
            root = Path(root_raw)
            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", root):
                instance = agent_module.Agent({"api_ports": [], "seed": 7})
            vivhite = instance._profile_knowledge["vivhite"]
            baseline = json.loads(json.dumps(vivhite.stats))
            state = {
                "screen": "MAP", "run_id": "fresh-vivhite-run",
                "run": {
                    "run_id": "fresh-vivhite-run",
                    "character_id": VIVHITE_ID,
                    "ascension": 0, "floor": 1,
                    "current_hp": 78, "max_hp": 78, "gold": 99,
                    "deck": [], "relics": [], "potions": [],
                },
            }

            instance._track(state)

            self.assertIs(instance.know, vivhite)
            journal = json.loads(
                (vivhite.root / ".active_run_learning.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(journal["run_id"], "fresh-vivhite-run")
            self.assertFalse(journal["excluded_from_learning"])
            self.assertEqual(journal["stats"], baseline)

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

    def test_f9_rolls_back_midrun_save_and_f10_cannot_resume_learning(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-manual-learning-") as root_raw:
            root = Path(root_raw)
            know = Knowledge(root, repair_phantoms=False)
            baseline = json.loads(json.dumps(know.stats))
            know.begin_run_learning("mixed-run")
            know.commit_card_play("CARD_BEFORE_F9")
            know.commit_event_option(
                "EVENT_BEFORE_F9", "OPTION", -8, 0, False)
            know.commit_enemy_fight(
                "ENEMY_BEFORE_F9", 12, won=True, died=False)
            know.commit_room_damage("Monster", 12)
            know.save()  # the pollution is genuinely durable before F9
            self.assertNotEqual(self._disk_stats(root), baseline)

            instance = object.__new__(agent_module.Agent)
            instance.ctx = agent_module.RunContext()
            instance.ctx.reset_for("mixed-run", 0, 1)
            instance.ctx.decisions = [{"floor": 7}]
            instance.know = know
            instance._manual_pause_active = False
            instance._manual_run_ids = set()
            instance._seen_pause_generation = 0
            instance._save_run_progress = mock.Mock()
            instance._dashboard_connection = mock.Mock()
            state = {
                "screen": "COMBAT", "run_id": "mixed-run",
                "run": {"run_id": "mixed-run", "floor": 7,
                        "ascension": 0, "character_id": VIVHITE_ID},
            }
            paused = manual_control.ControlSnapshot(
                enabled=False, pause_generation=1, source="test-hotkey")
            with mock.patch.object(
                    agent_module, "read_control_state", return_value=paused):
                self.assertTrue(instance._manual_control_blocks(state))

            self.assertEqual(know.stats, baseline)
            self.assertEqual(self._disk_stats(root), baseline)
            self.assertTrue(know.run_learning_is_excluded("mixed-run"))

            resumed = manual_control.ControlSnapshot(
                enabled=True, pause_generation=1, source="test-resume")
            with mock.patch.object(
                    agent_module, "read_control_state", return_value=resumed):
                self.assertFalse(instance._manual_control_blocks(state))

            # F10 restores actions, never learning eligibility for the same run.
            know.commit_card_play("CARD_AFTER_F10")
            know.commit_event_option(
                "EVENT_AFTER_F10", "OPTION", -20, 0, True)
            know.commit_enemy_fight(
                "ENEMY_AFTER_F10", 40, won=False, died=True)
            know.commit_room_damage("Boss", 40, died=True)
            know.save()
            self.assertEqual(know.stats, baseline)
            self.assertEqual(self._disk_stats(root), baseline)

    def test_exclusion_survives_exit_and_reconnect_until_same_run_closes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-manual-reconnect-") as root_raw:
            root = Path(root_raw)
            first = Knowledge(root, repair_phantoms=False)
            baseline = json.loads(json.dumps(first.stats))
            first.begin_run_learning("mixed-run")
            first.commit_card_play("SAVED_BEFORE_F9")
            first.save()
            first.exclude_run_learning("mixed-run")

            # A direct legacy mutation followed by the main() exit save must also
            # be discarded, not merely guarded commit_* calls.
            first.stats.setdefault("cards", {})["DIRECT_AFTER_F9"] = {
                "seen": 1, "offered": 1, "picked": 0, "plays": 9,
                "outcome_sum": 0.0, "bias": 0.0,
            }
            first.save()
            self.assertEqual(self._disk_stats(root), baseline)

            reconnected = Knowledge(root, repair_phantoms=False)
            # Construction itself restores and arms the exclusion.  No screen or
            # begin_run_learning callback is required before write guards engage.
            self.assertTrue(reconnected.run_learning_is_excluded("mixed-run"))
            reconnected.commit_card_play("RECONNECTED_AFTER_F10")
            reconnected.save()
            self.assertEqual(reconnected.stats, baseline)
            self.assertEqual(self._disk_stats(root), baseline)

            reconnected.finish_run_learning("mixed-run")
            self.assertFalse((root / ".active_run_learning.json").exists())

    def test_constructor_recovers_exclusion_flag_restore_crash_on_restart_screens(self) -> None:
        for screen in ("MAIN_MENU", "GAME_OVER"):
            with self.subTest(screen=screen), tempfile.TemporaryDirectory(
                    prefix=f"sts2-manual-{screen.lower()}-") as root_raw:
                base = Path(root_raw)
                profiles = ProfileStore(base)
                first = Knowledge(profiles.vivhite, repair_phantoms=False)
                baseline = json.loads(json.dumps(first.stats))
                first.begin_run_learning("crashed-mixed-run")
                first.commit_card_play("DURABLE_BEFORE_F9")
                first.save()
                self.assertNotEqual(self._disk_stats(first.root), baseline)

                # exclude_run_learning journals the fail-closed bit first.  Crash
                # before the following stats restore leaves exactly this window.
                with mock.patch.object(
                        first, "_restore_run_learning_baseline",
                        side_effect=OSError("crash after exclusion marker")):
                    with self.assertRaisesRegex(
                            OSError, "crash after exclusion marker"):
                        first.exclude_run_learning("crashed-mixed-run")
                journal = json.loads(
                    (first.root / ".active_run_learning.json").read_text(
                        encoding="utf-8"))
                self.assertTrue(journal["excluded_from_learning"])
                self.assertNotEqual(self._disk_stats(first.root), baseline)

                # A fresh Agent constructs every profile Knowledge before it can
                # observe either startup screen.  The exact Vivhite baseline must
                # already be durable and every learning entry must already no-op.
                with mock.patch.object(agent_module, "KNOWLEDGE_DIR", base):
                    restarted = agent_module.Agent(
                        {"api_ports": [], "seed": 17})
                recovered = restarted._profile_knowledge["vivhite"]
                self.assertTrue(recovered.run_learning_is_excluded(
                    "crashed-mixed-run"))
                self.assertEqual(self._disk_stats(recovered.root), baseline)
                recovered.commit_card_play(f"WRITE_BEFORE_{screen}")
                recovered.save()
                self.assertEqual(self._disk_stats(recovered.root), baseline)

                state = {"screen": screen, "run": {}}
                if screen == "GAME_OVER":
                    state.update({
                        "run_id": "crashed-mixed-run",
                        "run": {
                            "run_id": "crashed-mixed-run",
                            "character_id": VIVHITE_ID,
                            "floor": 17, "current_hp": 0, "gold": 99,
                        },
                        "game_over": {"floor": 17, "is_victory": False},
                    })
                restarted._track(state)
                self.assertEqual(self._disk_stats(recovered.root), baseline)

    def test_terminal_exclusion_closes_only_its_profile_learning_scope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-manual-profiles-") as root_raw:
            base = Path(root_raw)
            profiles = ProfileStore(base)
            mixed_root = profiles.vivhite.root
            other_root = profiles.ironclad.root
            mixed = Knowledge(profiles.vivhite, repair_phantoms=False)
            other = Knowledge(profiles.ironclad, repair_phantoms=False)
            mixed_baseline = json.loads(json.dumps(mixed.stats))
            other_baseline = json.loads(json.dumps(other.stats))

            mixed.begin_run_learning("mixed-run")
            mixed.commit_card_play("MIXED_CARD")
            mixed.save()

            instance = object.__new__(agent_module.Agent)
            instance.ctx = agent_module.RunContext()
            instance.ctx.reset_for("mixed-run", 0, 1)
            instance.ctx.profile_id = profiles.vivhite.profile_id
            instance.ctx.character_id = VIVHITE_ID
            instance.ctx.human_assisted = True
            instance.ctx.decisions = [{"floor": 9}]
            # Deliberately point the active aliases at the other profile.  The
            # terminal rollback must resolve the run context's profile id instead.
            instance.profile_store = profiles
            instance._profile_knowledge = {
                profiles.vivhite.profile_id: mixed,
                profiles.ironclad.profile_id: other,
            }
            instance.know = other
            instance.rotation = None
            instance._manual_run_ids = {"mixed-run"}
            with mock.patch.object(agent_module, "finalize_run") as finalize, \
                    mock.patch.object(agent_module, "log"):
                instance._finalize(victory=False, floor=9)

            finalize.assert_not_called()
            self.assertEqual(mixed.stats, mixed_baseline)
            self.assertEqual(self._disk_stats(mixed_root), mixed_baseline)
            self.assertFalse(
                (mixed_root / ".active_run_learning.json").exists())
            mixed_log = mixed.load_run_log("mixed-run")
            self.assertIsNotNone(mixed_log)
            self.assertEqual(mixed_log["profile_id"], profiles.vivhite.profile_id)
            self.assertTrue(mixed_log["human_assisted"])
            self.assertTrue(mixed_log["excluded_from_learning"])
            self.assertIsNone(other.load_run_log("mixed-run"))

            other.begin_run_learning("other-run")
            other.commit_card_play("OTHER_PROFILE_CARD")
            other.save()
            self.assertNotEqual(other.stats, other_baseline)
            self.assertEqual(
                other.stats["cards"]["OTHER_PROFILE_CARD"]["plays"], 1)

    def test_incomplete_terminal_cleans_exact_profile_journal_before_finalized(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-manual-incomplete-") as root_raw:
            base = Path(root_raw)
            profiles = ProfileStore(base)
            mixed = Knowledge(profiles.vivhite, repair_phantoms=False)
            other = Knowledge(profiles.ironclad, repair_phantoms=False)
            baseline = json.loads(json.dumps(mixed.stats))
            mixed.begin_run_learning("partial-run")
            mixed.commit_card_play("PARTIAL_BEFORE_F9")
            mixed.save()
            mixed.exclude_run_learning("partial-run")

            instance = object.__new__(agent_module.Agent)
            instance.ctx = agent_module.RunContext()
            instance.ctx.reset_for("partial-run", 0, 1)
            instance.ctx.profile_id = profiles.vivhite.profile_id
            instance.ctx.character_id = VIVHITE_ID
            instance.ctx.decisions = [{"floor": 17} for _ in range(4)]
            instance.profile_store = profiles
            instance._profile_knowledge = {
                profiles.vivhite.profile_id: mixed,
                profiles.ironclad.profile_id: other,
            }
            # Deliberately leave the active alias on the other character.
            instance.know = other
            instance.rotation = None

            real_finish = mixed.finish_run_learning
            with mock.patch.object(
                    mixed, "finish_run_learning",
                    side_effect=OSError("cleanup interrupted")), \
                    mock.patch.object(agent_module, "finalize_run") as finalize, \
                    mock.patch.object(agent_module, "log"):
                instance._finalize(victory=False, floor=17)
            finalize.assert_not_called()
            self.assertFalse(instance.ctx.run_finalized)
            self.assertTrue(instance.ctx.finalize_requested)
            self.assertTrue(
                (mixed.root / ".active_run_learning.json").exists())

            # Retry succeeds, restores excluded stats before unlinking, and only
            # then publishes run_finalized.  A duplicate terminal is a no-op.
            with mock.patch.object(
                    mixed, "finish_run_learning", wraps=real_finish) as finish, \
                    mock.patch.object(agent_module, "finalize_run") as finalize, \
                    mock.patch.object(agent_module, "log"):
                instance._finalize(victory=False, floor=17)
                instance._finalize(victory=False, floor=17)
            finalize.assert_not_called()
            finish.assert_called_once_with("partial-run")
            self.assertTrue(instance.ctx.run_finalized)
            self.assertFalse(instance.ctx.finalize_requested)
            self.assertFalse(
                (mixed.root / ".active_run_learning.json").exists())
            self.assertEqual(mixed.stats, baseline)
            self.assertEqual(self._disk_stats(mixed.root), baseline)
            self.assertIsNone(other.load_run_log("partial-run"))


if __name__ == "__main__":
    unittest.main()

