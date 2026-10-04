"""Material event attribution survives reconnect without replaying success tags."""
from __future__ import annotations

import copy
from pathlib import Path
import random
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))
import agent as agent_module
from knowledge import Knowledge
from policy import Decision, Policy


def state(screen="EVENT", hp=80, deck_size=10, *, page=0):
    value = {"screen": screen, "run_id": "event-run", "turn": 1,
             "run": {"run_id": "event-run", "character_id": "IRONCLAD",
                     "floor": 5, "ascension": 0, "current_hp": hp,
                     "max_hp": 80, "gold": 0,
                     "deck": [{"card_id": "A"}] * deck_size,
                     "relics": [], "potions": []}}
    if screen == "EVENT":
        value["event"] = {"event_id": "EVENT", "page": page, "options": []}
    if screen == "COMBAT":
        value["combat"] = {"enemies": [{"enemy_id": "ENEMY", "is_alive": True}]}
    return value


def create(root):
    instance = object.__new__(agent_module.Agent)
    instance.ctx = agent_module.RunContext()
    instance.know = Knowledge(root, repair_phantoms=False)
    instance.policy = Policy(instance.know, random.Random(1))
    instance._manual_run_ids = set()
    instance._rotation_unresolved_run_id = ""
    instance._ambiguous_action = None
    return instance


def choose(instance, snapshot, option="REPEAT"):
    instance._track(snapshot)
    instance._commit_successful_action(snapshot, Decision(
        "choose_event_option", {"option_index": 0}, "accepted",
        tags=[("event_choice", "EVENT", option)]))


class AgentEventRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sts2-event-recovery-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        logger = mock.patch.object(agent_module, "log")
        logger.start()
        self.addCleanup(logger.stop)

    def test_selection_reconnect_settles_event_once_without_replaying_tags(self):
        first = create(self.root)
        choose(first, state(), "GAIN_CARD")
        first._track(state("CARD_SELECTION"))
        saved = first.know.load_run_log("event-run")
        self.assertEqual(saved["event_checkpoint"]["schema"], "sts2.pending-event/v1")
        self.assertIsNotNone(saved["event_checkpoint"]["pending_event_own"])
        self.assertEqual(len(saved["decisions"]), 1)

        restarted = create(self.root)
        restarted._track(state("CARD_SELECTION"))
        self.assertEqual(restarted.ctx.pending_event[:2], ("EVENT", "GAIN_CARD"))
        self.assertEqual(restarted.ctx.credit_tags, [])
        restarted._track(state("MAP", deck_size=11))
        restarted._track(state("MAP", deck_size=11))
        outcome = restarted.know.stats["events"]["EVENT"]["GAIN_CARD"]
        self.assertEqual(outcome["n"], 1)
        self.assertEqual(outcome["card_delta_sum"], 1)
        self.assertNotIn("event_checkpoint", restarted.know.load_run_log("event-run"))

    def test_combat_reconnect_preserves_start_hp_and_same_attribution_as_continuous(self):
        def run(root, reconnect):
            instance = create(root)
            choose(instance, state(), "FIGHT")
            instance._track(state("COMBAT", hp=75))
            instance._track(state("COMBAT", hp=65))
            if reconnect:
                instance = create(root)
                instance._track(state("COMBAT", hp=65))
                self.assertEqual(instance.ctx.combat["hp_start"], 75)
            instance._track(state("REWARD", hp=55))
            return instance.know.stats["events"]["EVENT"]["FIGHT"]
        continuous = run(self.root / "continuous", False)
        resumed = run(self.root / "resumed", True)
        self.assertEqual(resumed, continuous)
        self.assertEqual(resumed["n"], 1)
        self.assertEqual(resumed["hp_delta_sum"], -25)

    def test_recovered_event_combat_preserves_historical_danger_classification(self):
        first = create(self.root)
        choose(first, state(), "FIGHT")
        first.know.stats["enemies"]["ENEMY"] = {"encounters": 3, "deaths": 3, "hp_lost_sum": 60}
        first._track(state("COMBAT", hp=75))
        self.assertTrue(first.ctx.current_combat_is_hard)
        restarted = create(self.root)
        restarted._track(state("COMBAT", hp=75))
        self.assertTrue(restarted.ctx.current_combat_is_hard)
        self.assertEqual(restarted.ctx.combat["hp_start"], 75)

    def test_real_repeated_choice_is_two_samples_but_unchanged_retry_is_one(self):
        for material_progress in (False, True):
            with self.subTest(material_progress=material_progress):
                instance = create(self.root / str(material_progress))
                choose(instance, state(hp=80))
                choose(instance, state(hp=70 if material_progress else 80))
                instance._track(state("MAP", hp=60 if material_progress else 80))
                outcome = instance.know.stats["events"]["EVENT"]["REPEAT"]
                self.assertEqual(outcome["n"], 2 if material_progress else 1)
                self.assertEqual(outcome["hp_delta_sum"], -20 if material_progress else 0)
                self.assertEqual(outcome["hp_min"], -10 if material_progress else 0)

    def test_same_key_changed_page_settles_zero_resource_choice(self):
        instance = create(self.root)
        choose(instance, state(page=0))
        choose(instance, state(page=1))
        instance._track(state("MAP"))
        self.assertEqual(instance.know.stats["events"]["EVENT"]["REPEAT"]["n"], 2)

    def test_old_and_foreign_checkpoints_keep_history_without_restoring_event(self):
        for checkpoint in (None, {"schema": "sts2.pending-event/v1",
                                  "run_id": "foreign-run", "pending_event": []}):
            with self.subTest(checkpoint=checkpoint):
                instance = create(self.root)
                instance.ctx.reset_for("event-run", 0, 1)
                prior = {"decisions": [{"floor": 5}], "event_checkpoint": checkpoint}
                instance._restore_event_checkpoint(prior)
                self.assertIsNone(instance.ctx.pending_event)
                self.assertEqual(instance.ctx.credit_tags, [])

    def test_log_read_failure_does_not_reset_or_write_context_and_can_retry(self):
        first = create(self.root)
        choose(first, state(), "GAIN_CARD")
        restarted = create(self.root)
        original = restarted.know.load_run_log
        with mock.patch.object(restarted.know, "load_run_log",
                               side_effect=OSError("log temporarily locked")), \
                mock.patch.object(restarted.know, "save_run_log") as save:
            with self.assertRaisesRegex(OSError, "temporarily locked"):
                restarted._track(state("CARD_SELECTION"))
        save.assert_not_called()
        self.assertEqual(restarted.ctx.run_id, "run_unknown")
        self.assertEqual(restarted.ctx.decisions, [])
        self.assertEqual(len(original("event-run")["decisions"]), 1)
        restarted._track(state("CARD_SELECTION"))
        self.assertEqual(len(restarted.ctx.decisions), 1)
        self.assertEqual(restarted.ctx.pending_event[:2], ("EVENT", "GAIN_CARD"))

    def test_unchanged_combat_selection_polls_do_not_write_timestamp_checkpoints(self):
        instance = create(self.root)
        choose(instance, state(), "FIGHT")
        instance._track(state("COMBAT", hp=75))
        instance._track(state("CARD_SELECTION", hp=75))
        with mock.patch.object(instance, "_save_run_progress") as save:
            instance._track(state("CARD_SELECTION", hp=75))
            instance._track(state("CARD_SELECTION", hp=75))
        save.assert_not_called()

    def test_failed_event_checkpoint_retries_on_unchanged_poll_without_another_action(self):
        instance = create(self.root)
        instance._track(state())
        original = instance.know.save_run_log
        calls = 0
        def interrupted(run_id, payload):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("checkpoint temporarily locked")
            return original(run_id, payload)
        with mock.patch.object(instance.know, "save_run_log", side_effect=interrupted):
            instance._commit_successful_action(state(), Decision(
                "choose_event_option", {"option_index": 0}, "accepted",
                tags=[("event_choice", "EVENT", "GAIN_CARD")]))
            self.assertTrue(instance.ctx.event_checkpoint_dirty)
            instance._track(state())
            self.assertFalse(instance.ctx.event_checkpoint_dirty)
        self.assertEqual(calls, 2)
        self.assertEqual(len(instance.ctx.decisions), 1)
        self.assertEqual(instance.know.load_run_log("event-run")[
            "event_checkpoint"]["pending_event"][:2], ["EVENT", "GAIN_CARD"])

    def test_main_loop_retries_unreadable_history_without_policy_or_post(self):
        instance = create(self.root)
        instance.cfg = {"max_runs": 0, "poll_interval": 0.01}
        instance.runs_played = 0
        instance._last_policy_refresh = time.time()
        instance.client = SimpleNamespace(state=mock.Mock(return_value=state()),
                                          health=mock.Mock(return_value={}), act=mock.Mock())
        for name in ("_start_live_dashboard", "_capture_boot_head", "_launch_quipper",
                     "_dashboard_connection", "_dashboard_observe", "_dashboard_propose"):
            setattr(instance, name, mock.Mock())
        instance.ensure_game = mock.Mock(return_value=True)
        instance._manual_control_blocks = mock.Mock(return_value=False)
        instance._native_profile_guard_decision = mock.Mock(return_value=None)
        instance._bind_profile_for_state = mock.Mock()
        instance._reconcile_ambiguous_action = mock.Mock(return_value=None)
        instance._track = mock.Mock(side_effect=[OSError("unreadable log"), None])
        instance._watchdog = mock.Mock(return_value=None)
        instance.policy.decide = mock.Mock(return_value=Decision(None, {}, "wait"))
        with mock.patch.object(agent_module, "mark_pid_stage", return_value=True), \
                mock.patch.object(agent_module, "stop_requested", return_value=False), \
                mock.patch.object(agent_module, "wait_for_stop", side_effect=[False, True]), \
                mock.patch.object(agent_module, "llm_review", None):
            instance.run()
        self.assertEqual(instance._track.call_count, 2)
        self.assertEqual(instance.policy.decide.call_count, 1)
        instance.client.act.assert_not_called()
        self.assertTrue(any(call.args[0] == "degraded" for call in
                            instance._dashboard_connection.call_args_list))


if __name__ == "__main__":
    unittest.main()
