"""Runtime integration regressions for character profiles and strict rotation."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402
from character_profiles import VIVHITE_CHARACTER_ID  # noqa: E402
from character_rotation import CharacterRotation, IRONCLAD, VIVHITE  # noqa: E402
from policy import Policy  # noqa: E402


def _characters(*, include_vivhite: bool = True,
                vivhite_locked: bool = False) -> list[dict]:
    result = [{
        "index": 0,
        "character_id": "IRONCLAD",
        "name": "Ironclad",
        "is_locked": False,
        "is_random": False,
    }]
    if include_vivhite:
        result.append({
            "index": 4,
            "character_id": VIVHITE_CHARACTER_ID,
            "name": "Vivhite",
            "is_locked": vivhite_locked,
            "is_random": False,
        })
    return result


def _character_select_state(characters: list[dict]) -> dict:
    return {
        "screen": "CHARACTER_SELECT",
        "available_actions": ["select_character", "embark"],
        "character_select": {
            "characters": characters,
            "ascension": 0,
            "max_ascension": 20,
            "can_embark": True,
        },
    }


class _FinalKnowledge:
    def __init__(self, events: list[str], *, fail_save: bool = False) -> None:
        self.events = events
        self.fail_save = fail_save
        self.stats = {"global": {"runs": 7, "wins": 0}}
        self.progression = {"character": VIVHITE_CHARACTER_ID}
        self.saved_log: dict | None = None

    def save_run_log(self, _run_id: str, payload: dict) -> Path:
        self.events.append("terminal_log")
        self.saved_log = payload
        return Path("run-v.json")

    def save(self) -> None:
        self.events.append("character_stats")
        if self.fail_save:
            raise OSError("injected stats failure")


def _finalizing_agent(rotation, know: _FinalKnowledge) -> agent_module.Agent:
    instance = object.__new__(agent_module.Agent)
    instance.ctx = agent_module.RunContext()
    instance.ctx.reset_for("run-v", 3, 7)
    instance.ctx.profile_id = "vivhite"
    instance.ctx.character_id = VIVHITE_CHARACTER_ID
    instance.ctx.profile_run_number = 7
    instance.ctx.decisions = [{"floor": 12}] * 10
    instance.active_profile = SimpleNamespace(
        profile_id="vivhite", character_id=VIVHITE_CHARACTER_ID)
    instance.know = know
    instance.rotation = rotation
    instance.runs_played = 0
    instance.request_restart = False
    instance._flush_combat_agg = mock.Mock()
    instance._mark_review_run_healthy = mock.Mock()
    return instance


class AgentProfileRotationIntegrationTests(unittest.TestCase):
    def test_policy_first_selects_vivhite_and_never_falls_back(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-agent-rotation-") as root:
            rotation = CharacterRotation.from_knowledge_root(root)
            know = SimpleNamespace(
                progression={"character": "IRONCLAD"}, policy={})
            policy = Policy(know, character_rotation=rotation)

            first = policy._character_select(
                _character_select_state(_characters()), SimpleNamespace())
            self.assertEqual(first.action, "select_character")
            self.assertEqual(first.params, {"option_index": 4})
            self.assertIn(VIVHITE, first.reason)

            missing = policy._character_select(
                _character_select_state(_characters(include_vivhite=False)),
                SimpleNamespace())
            self.assertIsNone(missing.action)
            self.assertIn("target_missing", missing.reason)
            self.assertNotEqual(missing.params, {"option_index": 0})

            locked = policy._character_select(
                _character_select_state(_characters(vivhite_locked=True)),
                SimpleNamespace())
            self.assertIsNone(locked.action)
            self.assertIn("target_unavailable", locked.reason)
            self.assertEqual(rotation.target_character, VIVHITE)

    def test_agent_owns_isolated_runtimes_and_api_actual_character_wins(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-agent-profiles-") as root:
            knowledge_root = Path(root)
            cfg = {"api_ports": [], "seed": 11}
            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", knowledge_root):
                instance = agent_module.Agent(cfg)

            self.assertEqual(
                instance._profile_knowledge["ironclad"].root,
                knowledge_root)
            self.assertEqual(
                instance._profile_knowledge["vivhite"].root,
                knowledge_root / "profiles" / "vivhite")
            self.assertIsNot(
                instance._profile_policies["ironclad"],
                instance._profile_policies["vivhite"])

            # The empty rotation expects Vivhite, so selection activates Vivhite's
            # progression/policy runtime.
            instance._bind_profile_for_state(
                _character_select_state(_characters()))
            self.assertEqual(instance.active_profile.profile_id, "vivhite")

            # A pre-existing API run is authoritative even when it disagrees with
            # that expected selection target.
            actual = {
                "screen": "MAP",
                "run_id": "existing-ironclad",
                "run": {
                    "run_id": "existing-ironclad",
                    "character_id": "IRONCLAD",
                    "current_hp": 70,
                    "max_hp": 80,
                    "gold": 99,
                    "ascension": 0,
                    "floor": 3,
                },
            }
            instance._track(actual)
            self.assertEqual(instance.active_profile.profile_id, "ironclad")
            self.assertIs(instance.know, instance._profile_knowledge["ironclad"])
            self.assertIs(instance.policy, instance._profile_policies["ironclad"])
            self.assertEqual(instance.ctx.character_id, "IRONCLAD")
            snapshot = instance.rotation.snapshot()
            self.assertEqual(snapshot.active_run_id, "existing-ironclad")
            self.assertEqual(snapshot.active_character, IRONCLAD)
            self.assertEqual(snapshot.next_character, VIVHITE)

    def test_terminal_metadata_persists_before_flip_and_duplicate_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-agent-finalize-") as root:
            events: list[str] = []
            real_rotation = CharacterRotation.from_knowledge_root(root)
            real_rotation.observe_active_run("run-v", VIVHITE_CHARACTER_ID)
            rotation = mock.Mock(wraps=real_rotation)
            rotation.snapshot.side_effect = real_rotation.snapshot

            def record_terminal(*args, **kwargs):
                events.append("rotation")
                return real_rotation.record_terminal(*args, **kwargs)

            rotation.record_terminal.side_effect = record_terminal
            know = _FinalKnowledge(events)
            instance = _finalizing_agent(rotation, know)

            with mock.patch.object(
                    agent_module, "finalize_run", return_value="lesson") as reflected, \
                    mock.patch.object(agent_module, "llm_review", None), \
                    mock.patch.object(agent_module, "autogit", None), \
                    mock.patch.object(agent_module, "log"):
                instance._finalize(victory=False, floor=12)

                self.assertEqual(
                    events, ["terminal_log", "character_stats", "rotation"])
                self.assertEqual(know.saved_log["profile_id"], "vivhite")
                self.assertEqual(
                    know.saved_log["character_id"], VIVHITE_CHARACTER_ID)
                self.assertEqual(know.saved_log["profile_run_number"], 7)
                self.assertEqual(know.saved_log["run_number"], 7)
                self.assertEqual(real_rotation.target_character, IRONCLAD)

                # Simulate a repeated terminal callback after a process-local latch
                # was lost. The durable run-id ledger prevents duplicate learning.
                instance.ctx.run_finalized = False
                instance._finalize(victory=False, floor=12)

            reflected.assert_called_once()
            self.assertEqual(
                events, ["terminal_log", "character_stats", "rotation"])
            rotation.record_terminal.assert_called_once()

    def test_reconnected_terminal_echo_cannot_repeat_stats_or_rotation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-agent-reconnect-") as root:
            events: list[str] = []
            real_rotation = CharacterRotation.from_knowledge_root(root)
            real_rotation.observe_active_run("run-v", VIVHITE_CHARACTER_ID)
            rotation = mock.Mock(wraps=real_rotation)
            rotation.snapshot.side_effect = real_rotation.snapshot

            def record_terminal(*args, **kwargs):
                events.append("rotation")
                return real_rotation.record_terminal(*args, **kwargs)

            rotation.record_terminal.side_effect = record_terminal
            know = _FinalKnowledge(events)
            first_process = _finalizing_agent(rotation, know)
            reconnected_process = _finalizing_agent(rotation, know)

            with mock.patch.object(
                    agent_module, "finalize_run", return_value="lesson") as reflected, \
                    mock.patch.object(agent_module, "llm_review", None), \
                    mock.patch.object(agent_module, "autogit", None), \
                    mock.patch.object(agent_module, "log"):
                first_process._finalize(victory=False, floor=12)
                reconnected_process._finalize(victory=False, floor=12)

            self.assertEqual(
                events, ["terminal_log", "character_stats", "rotation"])
            reflected.assert_called_once()
            rotation.record_terminal.assert_called_once()
            self.assertTrue(reconnected_process.ctx.run_finalized)
            self.assertEqual(real_rotation.target_character, IRONCLAD)

    def test_failed_character_stats_save_does_not_flip_rotation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-agent-finalize-fail-") as root:
            events: list[str] = []
            real_rotation = CharacterRotation.from_knowledge_root(root)
            real_rotation.observe_active_run("run-v", VIVHITE_CHARACTER_ID)
            rotation = mock.Mock(wraps=real_rotation)
            rotation.snapshot.side_effect = real_rotation.snapshot
            know = _FinalKnowledge(events, fail_save=True)
            instance = _finalizing_agent(rotation, know)

            with mock.patch.object(
                    agent_module, "finalize_run", return_value="lesson"), \
                    mock.patch.object(agent_module, "llm_review", None), \
                    mock.patch.object(agent_module, "autogit", None), \
                    mock.patch.object(agent_module, "log"), \
                    self.assertRaises(OSError):
                instance._finalize(victory=False, floor=12)

            self.assertEqual(events, ["terminal_log", "character_stats"])
            rotation.record_terminal.assert_not_called()
            snapshot = real_rotation.snapshot()
            self.assertEqual(snapshot.active_run_id, "run-v")
            self.assertEqual(snapshot.target_character, VIVHITE)


if __name__ == "__main__":
    unittest.main()
