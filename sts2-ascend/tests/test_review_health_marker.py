"""Review rollback markers require completed runs, not arbitrary API ticks."""
from __future__ import annotations

from contextlib import contextmanager
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


def _verified_state(run_id: str, floor: int) -> dict:
    return {
        "screen": "GAME_OVER",
        "run_id": run_id,
        "run": {"run_id": run_id, "floor": floor},
        "game_over": {
            "phase": "summary_ready",
            "save_status": "verified",
            "save_verified": True,
            "save_error": None,
        },
    }


@contextmanager
def _lock(**_kwargs):
    yield


class ReviewHealthMarkerTests(unittest.TestCase):
    @staticmethod
    def _restart_probe(*, request_restart: bool = False,
                       loaded_review: str = "") -> agent_module.Agent:
        instance = object.__new__(agent_module.Agent)
        instance.ctx = SimpleNamespace(run_finalized=True, run_id="run_unknown")
        instance.request_restart = request_restart
        instance._boot_review_commit = loaded_review
        return instance

    def test_in_memory_restart_is_rechecked_only_at_safe_boundary(self) -> None:
        instance = self._restart_probe(request_restart=True)

        self.assertEqual(
            instance._pending_review_restart_at_safe_boundary({"screen": "COMBAT"}),
            "")
        self.assertTrue(instance._pending_review_restart_at_safe_boundary(
            {"screen": "MAIN_MENU"}))
        self.assertTrue(instance._pending_review_restart_at_safe_boundary(
            {"screen": "CHARACTER_SELECT"}))

        # A terminal frame is not a cross-process boundary: a new Brain can still
        # observe it and would otherwise finalize a victory twice.
        instance.ctx.run_finalized = False
        self.assertEqual(instance._pending_review_restart_at_safe_boundary(
            {"screen": "GAME_OVER"}), "")
        instance.ctx.run_finalized = True
        self.assertEqual(instance._pending_review_restart_at_safe_boundary(
            {"screen": "GAME_OVER"}), "")

        # A menu-like screen must not discard an unarchived run context.  It stays
        # blocked until the old run's native GAME_OVER save proof is observed.
        instance.ctx.run_id = "unfinished-run"
        instance.ctx.run_finalized = False
        self.assertEqual(instance._pending_review_restart_at_safe_boundary(
            {"screen": "MAIN_MENU", "run": {}}), "")
        instance.ctx.run_finalized = True
        self.assertTrue(instance._pending_review_restart_at_safe_boundary(
            {"screen": "MAIN_MENU", "run": {}}))
        self.assertEqual(instance._pending_review_restart_at_safe_boundary(
            {"screen": "CHARACTER_SELECT", "run": {"floor": 1}}), "")

    def test_committed_marker_restarts_only_an_older_brain_epoch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-restart-") as root:
            knowledge = Path(root)
            marker = knowledge / "pending_restart.json"
            review_commit = "b" * 40
            marker.write_text(json.dumps({
                "review_commit": review_commit,
                "state": "committed",
            }), encoding="utf-8")

            stale = self._restart_probe()
            loaded = self._restart_probe(loaded_review=review_commit)
            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", knowledge):
                self.assertTrue(stale._pending_review_restart_at_safe_boundary(
                    {"screen": "MAIN_MENU"}))
                self.assertEqual(loaded._pending_review_restart_at_safe_boundary(
                    {"screen": "MAIN_MENU"}), "")
                self.assertEqual(stale._pending_review_restart_at_safe_boundary(
                    {"screen": "COMBAT"}), "")
                stale.ctx.run_finalized = True
                self.assertEqual(stale._pending_review_restart_at_safe_boundary(
                    {"screen": "GAME_OVER", "game_over": {"is_victory": True}}),
                    "")

                marker.write_text(json.dumps({
                    "review_commit": "c" * 40,
                    "state": "prepared",
                }), encoding="utf-8")
                self.assertEqual(stale._pending_review_restart_at_safe_boundary(
                    {"screen": "MAIN_MENU"}), "")

    def test_finalize_defers_restart_until_empty_menu(self) -> None:
        instance = object.__new__(agent_module.Agent)
        instance.ctx = SimpleNamespace(
            run_finalized=False,
            decisions=[{"floor": 1}],
            combat_notes=[],
            attribution_tags=[],
            run_id="finished-run",
            run_number=0,
            ascension=0,
            started_at="now",
        )
        instance.runs_played = 0
        instance.request_restart = True
        instance._flush_combat_agg = mock.Mock()
        instance._mark_review_run_healthy = mock.Mock()
        instance.know = SimpleNamespace(
            stats={"global": {"runs": 1, "wins": 0}},
            save_run_log=mock.Mock(return_value=Path("finished-run.json")),
            save=mock.Mock(),
        )

        with mock.patch.object(agent_module, "finalize_run", return_value="lesson"), \
                mock.patch.object(agent_module, "llm_review", None), \
                mock.patch.object(agent_module, "autogit", None), \
                mock.patch.object(agent_module, "log") as logged:
            # Regression: this used to raise SystemExit(42) directly on GAME_OVER.
            instance._finalize(
                victory=False, floor=1,
                native_save_state=_verified_state("finished-run", 1))

        self.assertTrue(instance.ctx.run_finalized)
        self.assertTrue(logged.called)

    def test_disappeared_run_blocks_new_run_and_restart_without_finalizing(self) -> None:
        instance = object.__new__(agent_module.Agent)
        instance.ctx = agent_module.RunContext()
        instance.ctx.reset_for("old-run", 0, 7)
        instance.ctx.decisions.append({"floor": 5})
        instance.request_restart = True
        instance._boot_review_commit = ""
        instance._review_health_ready_for_new_run = False
        instance.know = SimpleNamespace(
            stats={"global": {"runs": 7}}, load_run_log=lambda _run_id: None)
        instance._save_run_progress = mock.Mock(return_value=True)
        instance._finalize = mock.Mock()
        fresh = {
            "screen": "EVENT",
            "run_id": "new-run",
            "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                    "ascension": 0, "floor": 0},
        }
        with mock.patch.object(agent_module, "log"):
            instance._track(fresh)

        instance._finalize.assert_not_called()
        self.assertEqual(instance.ctx.run_id, "old-run")
        self.assertTrue(instance.ctx.finalize_requested)
        self.assertTrue(instance._native_save_transition_blocked)
        self.assertEqual(
            instance.ctx.native_save_wait["replacement_run_id"], "new-run")
        instance._save_run_progress.assert_called_once_with(
            {"floor": 5}, force=True)

    def test_track_requires_empty_main_menu_before_complete_run_eligibility(self) -> None:
        instance = object.__new__(agent_module.Agent)
        instance.ctx = agent_module.RunContext()
        instance._review_health_ready_for_new_run = False
        instance.know = SimpleNamespace(
            stats={"global": {"runs": 0}}, load_run_log=lambda _run_id: None)
        instance._finalize = mock.Mock()

        # TIMELINE can be exposed while a run payload is still active. It must not
        # turn a reconnect tail into a complete boot-validation run.
        active = {
            "screen": "TIMELINE",
            "run_id": "active-run",
            "run": {"current_hp": 50, "max_hp": 80, "gold": 0,
                    "ascension": 0, "floor": 3},
        }
        instance._track(active)
        self.assertFalse(instance.ctx.review_health_eligible)

        # A genuinely empty main menu arms exactly the next new run.
        instance.ctx.run_finalized = True
        instance._track({"screen": "MAIN_MENU", "run": {}})
        fresh = {
            "screen": "EVENT",
            "run_id": "fresh-run",
            "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                    "ascension": 0, "floor": 0},
        }
        instance._track(fresh)
        self.assertTrue(instance.ctx.review_health_eligible)

    def test_marker_survives_first_run_and_retires_after_threshold(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-health-") as root:
            knowledge = Path(root)
            marker = knowledge / "pending_restart.json"
            marker.write_text(json.dumps({
                "review_parent": "a" * 40,
                "review_commit": "b" * 40,
                "paths": ["sts2-ascend/brain/policy.py"],
            }), encoding="utf-8")
            instance = object.__new__(agent_module.Agent)
            # HEAD 诊断即使不可读，Runner 冻结的 marker epoch 仍能可靠计数。
            instance._boot_head = ""
            instance._boot_review_commit = "b" * 40
            instance.ctx = SimpleNamespace(
                review_health_eligible=True, run_id="complete-run")
            fake_autogit = SimpleNamespace(repository_lock=_lock)

            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", knowledge), \
                    mock.patch.object(agent_module, "autogit", fake_autogit):
                instance._mark_review_run_healthy()
                first = json.loads(marker.read_text(encoding="utf-8"))
                self.assertEqual(first["healthy_runs"], 1)
                instance._mark_review_run_healthy()

            self.assertFalse(marker.exists())

    def test_unloaded_review_commit_never_advances_health(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-health-") as root:
            knowledge = Path(root)
            marker = knowledge / "pending_restart.json"
            original = {"review_commit": "b" * 40}
            marker.write_text(json.dumps(original), encoding="utf-8")
            instance = object.__new__(agent_module.Agent)
            instance._boot_head = "c" * 40
            instance._boot_review_commit = "d" * 40
            instance.ctx = SimpleNamespace(
                review_health_eligible=True, run_id="complete-run")
            fake_autogit = SimpleNamespace(repository_lock=_lock)

            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", knowledge), \
                    mock.patch.object(agent_module, "autogit", fake_autogit):
                instance._mark_review_run_healthy()

            self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), original)

    def test_mid_run_reconnect_never_advances_health(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-health-") as root:
            knowledge = Path(root)
            marker = knowledge / "pending_restart.json"
            original = {
                "review_commit": "b" * 40,
                "state": "committed",
                "healthy_runs": 1,
            }
            marker.write_text(json.dumps(original), encoding="utf-8")
            instance = object.__new__(agent_module.Agent)
            instance._boot_review_commit = "b" * 40
            instance.ctx = SimpleNamespace(
                review_health_eligible=False, run_id="resumed-run")
            fake_autogit = SimpleNamespace(repository_lock=_lock)

            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", knowledge), \
                    mock.patch.object(agent_module, "autogit", fake_autogit):
                instance._mark_review_run_healthy()

            self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), original)

    def test_prepared_marker_never_advances_health(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-health-") as root:
            knowledge = Path(root)
            marker = knowledge / "pending_restart.json"
            original = {
                "review_commit": "b" * 40,
                "state": "prepared",
            }
            marker.write_text(json.dumps(original), encoding="utf-8")
            instance = object.__new__(agent_module.Agent)
            instance._boot_review_commit = "b" * 40
            instance.ctx = SimpleNamespace(
                review_health_eligible=True, run_id="complete-run")
            fake_autogit = SimpleNamespace(repository_lock=_lock)

            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", knowledge), \
                    mock.patch.object(agent_module, "autogit", fake_autogit):
                instance._mark_review_run_healthy()

            self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), original)


if __name__ == "__main__":
    unittest.main()
