"""Regression coverage for profile-local LLM review state."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402


def _knowledge(root: Path, profile_id: str, runs: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        root=root,
        profile_id=profile_id,
        stats={
            "version": 1,
            "global": {"runs": runs},
            "cards": {},
            "enemies": {},
            "events": {},
            "rooms": {},
            "rooms_act": {},
            "rooms_band": {},
            "respawn_adds": {},
            "act_entries": [],
            "relics": {},
        },
        progression={
            "last_llm_review_run": 0,
            "last_successful_review_run": 0,
            "review_report_only_streak": 0,
        },
        policy={"profile": profile_id},
        game_knowledge=None,
        save=mock.Mock(),
    )


class LlmProfileIsolationTests(unittest.TestCase):
    def test_review_checkpoint_paths_include_only_active_profile_and_global_rotation(self) -> None:
        with llm_review._review_profile_scope("vivhite"):
            paths = llm_review._review_concurrent_paths()

        profile = "sts2-ascend/knowledge/profiles/vivhite"
        self.assertEqual(set(paths), {
            f"{profile}/runs",
            f"{profile}/stats.json",
            f"{profile}/progression.json",
            f"{profile}/policy.json",
            f"{profile}/lessons.md",
            f"{profile}/review_queue.json",
            "sts2-ascend/knowledge/character_rotation.json",
            "sts2-ascend/knowledge/preferred_model_state.json",
        })

    def test_legacy_queue_items_default_to_ironclad_without_rewrite(self) -> None:
        payload = {
            "pending": [{"run": 1, "time": "legacy"}],
            "reviewing": None,
        }

        validated = llm_review._validate_queue(payload)

        self.assertIs(validated, payload)
        self.assertNotIn("profile_id", payload["pending"][0])
        self.assertEqual(
            llm_review._queue_item_profile_id(payload["pending"][0]),
            "ironclad",
        )

    def test_batch_selection_never_mixes_profiles(self) -> None:
        pending = [
            {"run": 1},  # legacy is ironclad
            {"run": 1, "profile_id": "silent"},
            {"run": 2, "profile_id": "ironclad"},
            {"run": 2, "profile_id": "silent"},
        ]

        indexes, wait = llm_review._select_review_batch(pending, 10, 100.0)

        self.assertEqual(wait, 0.0)
        self.assertEqual(indexes, [0, 2])
        self.assertEqual(
            llm_review._batch_profile_id([pending[index] for index in indexes]),
            "ironclad",
        )
        with self.assertRaisesRegex(
                llm_review.ReviewQueueError, "mixed profile_id"):
            llm_review._batch_profile_id([pending[0], pending[1]])

    def test_queue_files_are_rooted_per_profile(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-profiles-") as temp:
            profiles = Path(temp) / "profiles"
            ironclad = profiles / "ironclad"
            silent = profiles / "silent"
            iron_queue = {
                "pending": [{"run": 3, "profile_id": "ironclad"}],
                "reviewing": None,
            }
            silent_queue = {
                "pending": [{"run": 9, "profile_id": "silent"}],
                "reviewing": None,
            }

            llm_review._save_queue(
                iron_queue, profile_id="ironclad", profile_root=ironclad)
            llm_review._save_queue(
                silent_queue, profile_id="silent", profile_root=silent)

            self.assertEqual(
                llm_review._load_queue(
                    profile_id="ironclad", profile_root=ironclad),
                iron_queue,
            )
            self.assertEqual(
                llm_review._load_queue(
                    profile_id="silent", profile_root=silent),
                silent_queue,
            )
            self.assertTrue((ironclad / "review_queue.json").is_file())
            self.assertTrue((silent / "review_queue.json").is_file())
            with self.assertRaisesRegex(
                    llm_review.ReviewQueueError, "another profile"):
                llm_review._save_queue(
                    {"pending": [{"run": 10}], "reviewing": None},
                    profile_id="silent", profile_root=silent,
                )
            with self.assertRaisesRegex(ValueError, "does not match"):
                llm_review._paths_for_profile(
                    "ironclad", profile_root=silent)

    def test_prompt_reads_only_selected_profile_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-prompt-profile-") as temp:
            profiles = Path(temp) / "profiles"
            ironclad = profiles / "ironclad"
            silent = profiles / "silent"
            for root in (ironclad, silent):
                (root / "runs").mkdir(parents=True)
            (ironclad / "runs" / "run-001.json").write_text(
                json.dumps({
                    "run_id": "IRON_ONLY", "run_number": 1,
                    "victory": False, "floor": 1, "decisions": [],
                    "combat_notes": ["IRON_EVIDENCE"],
                }), encoding="utf-8")
            (ironclad / "lessons.md").write_text(
                "IRON_LESSON\n", encoding="utf-8")
            (ironclad / "meta_review.md").write_text(
                "IRON_REPORT\n", encoding="utf-8")

            (silent / "runs" / "run-007.json").write_text(
                json.dumps({
                    "run_id": "SILENT_ONLY", "run_number": 7,
                    "victory": False, "floor": 7,
                    "decisions": [{
                        "screen": "GAME_OVER", "action": None,
                        "reason": "SILENT_DECISION",
                    }],
                    "combat_notes": ["SILENT_EVIDENCE"],
                }), encoding="utf-8")
            (silent / "lessons.md").write_text(
                "SILENT_LESSON\n", encoding="utf-8")
            (silent / "meta_review.md").write_text(
                "SILENT_REPORT\n", encoding="utf-8")
            know = _knowledge(silent, "silent", runs=7)

            prompt = llm_review.build_prompt(
                know,
                {"max_runs_in_packet": 10, "review_every_runs": 1},
                batch_runs=[7],
                closure_state={"action_required": False},
                profile_id="silent",
                profile_root=silent,
            )

            packet_raw = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]
            packet = json.loads(packet_raw)
            self.assertEqual(packet["profile_id"], "silent")
            self.assertEqual(
                [item["run_id"] for item in packet["runs_summary"]],
                ["SILENT_ONLY"],
            )
            self.assertIn("SILENT_LESSON", prompt)
            self.assertIn("SILENT_REPORT", prompt)
            self.assertNotIn("IRON_EVIDENCE", prompt)
            self.assertNotIn("IRON_LESSON", prompt)
            self.assertNotIn("IRON_REPORT", prompt)
            self.assertIn((silent / "policy.json").as_posix(), prompt)
            self.assertIn((silent / "review_queue.json").as_posix(), prompt)

    def test_manual_game_over_runs_never_enter_vivhite_prompt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-manual-prompt-") as temp:
            root = Path(temp) / "profiles" / "vivhite"
            runs = root / "runs"
            runs.mkdir(parents=True)
            blocked = (
                {
                    "run_id": "HUMAN_GAME_OVER",
                    "run_number": 7,
                    "in_progress": True,
                    "human_assisted": True,
                    "decisions": [{"screen": "GAME_OVER"}],
                    "combat_notes": ["HUMAN_PROMPT_POLLUTION"],
                },
                {
                    "run_id": "EXCLUDED_GAME_OVER",
                    "run_number": 8,
                    "in_progress": False,
                    "excluded_from_learning": True,
                    "decisions": [{"screen": "GAME_OVER"}],
                    "combat_notes": ["EXCLUDED_PROMPT_POLLUTION"],
                },
            )
            for item in blocked:
                (runs / f"run-{item['run_number']:03d}.json").write_text(
                    json.dumps(item), encoding="utf-8")
            know = _knowledge(root, "vivhite", runs=8)

            prompt = llm_review.build_prompt(
                know,
                {"max_runs_in_packet": 10, "review_every_runs": 1},
                batch_runs=[7, 8],
                closure_state={"action_required": False},
                profile_id="vivhite",
                profile_root=root,
            )

            packet_raw = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]
            packet = json.loads(packet_raw)
            self.assertEqual(packet["runs_summary"], [])
            self.assertNotIn("HUMAN_GAME_OVER", prompt)
            self.assertNotIn("EXCLUDED_GAME_OVER", prompt)
            self.assertNotIn("HUMAN_PROMPT_POLLUTION", prompt)
            self.assertNotIn("EXCLUDED_PROMPT_POLLUTION", prompt)

    def test_archived_manual_game_over_runs_never_enter_review_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-manual-archive-") as temp:
            root = Path(temp) / "profiles" / "vivhite"
            archive = root / "archive"
            archive.mkdir(parents=True)
            entries = (
                {"run_number": 9, "file": "human-game-over.json"},
                {"run_number": 10, "file": "excluded-game-over.json"},
            )
            (archive / "run_catalog.jsonl").write_text(
                "\n".join(json.dumps(item) for item in entries) + "\n",
                encoding="utf-8",
            )
            archived = {
                "human-game-over.json": {
                    "run_id": "ARCHIVED_HUMAN_GAME_OVER",
                    "run_number": 9,
                    "in_progress": True,
                    "human_assisted": True,
                    "decisions": [{"screen": "GAME_OVER"}],
                },
                "excluded-game-over.json": {
                    "run_id": "ARCHIVED_EXCLUDED_GAME_OVER",
                    "run_number": 10,
                    "excluded_from_learning": True,
                    "decisions": [{"screen": "GAME_OVER"}],
                },
            }

            def read_evidence(_root, filename):
                return json.dumps(archived[filename]).encode("utf-8")

            with (mock.patch(
                    "compact_knowledge.read_run_evidence",
                    side_effect=read_evidence),
                  llm_review._review_profile_scope(
                      "vivhite", profile_root=root)):
                records = llm_review._requested_archived_runs({9, 10}, set())

            self.assertEqual(records, [])

    def test_manual_game_over_context_never_enters_vivhite_queue(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-manual-queue-") as temp:
            root = Path(temp) / "profiles" / "vivhite"
            know = _knowledge(root, "vivhite", runs=9)
            agent = SimpleNamespace(
                know=know,
                profile_id="vivhite",
                cfg={"profile_id": "vivhite"},
                ctx=SimpleNamespace(
                    profile_id="vivhite",
                    human_assisted=True,
                    excluded_from_learning=True,
                    decisions=[{"screen": "GAME_OVER"}],
                ),
            )
            messages: list[str] = []

            with (mock.patch.object(llm_review, "load_llm_config") as load_cfg,
                  mock.patch.object(llm_review, "_ensure_worker") as ensure_worker):
                llm_review.enqueue_review(agent, log=messages.append)

            load_cfg.assert_not_called()
            ensure_worker.assert_not_called()
            know.save.assert_not_called()
            self.assertFalse((root / "review_queue.json").exists())
            self.assertTrue(any("不进入自动复盘队列" in item for item in messages))

    def test_enqueue_persists_profile_id_in_profile_queue(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-enqueue-profile-") as temp:
            root = Path(temp) / "profiles" / "silent"
            know = _knowledge(root, "silent", runs=4)
            agent = SimpleNamespace(
                know=know, profile_id="silent", cfg={"profile_id": "silent"})
            plan = llm_review.ReviewPlan(
                key="test", priority=1, runner="opencode", model="test/model",
                every_runs=1, source="preferred")
            cfg = {
                "enabled": True,
                "review_every_runs": 1,
                "review_queue_max": 10,
            }

            with (mock.patch.object(llm_review, "load_llm_config", return_value=cfg),
                  mock.patch.object(llm_review, "review_plans_from_config",
                                    return_value=[plan]),
                  mock.patch.object(llm_review, "_ensure_worker")):
                llm_review.enqueue_review(agent, log=lambda _message: None)

            queue = json.loads(
                (root / "review_queue.json").read_text(encoding="utf-8"))
            self.assertEqual(queue["pending"][0]["profile_id"], "silent")
            self.assertEqual(queue["pending"][0]["run"], 4)
            know.save.assert_called_once_with()

    def test_inactive_profile_batch_uses_its_matching_knowledge(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-binding-") as temp:
            root = Path(temp) / "knowledge"
            ironclad = _knowledge(root, "ironclad")
            vivhite = _knowledge(root / "profiles" / "vivhite", "vivhite")
            agent = SimpleNamespace(
                know=ironclad,
                profile_id="ironclad",
                _profile_knowledge={
                    "ironclad": ironclad,
                    "vivhite": vivhite,
                },
            )
            observed: dict[str, object] = {}

            def execute(_agent, _batch, _log, know=None):
                observed["know"] = know
                observed["paths"] = llm_review._current_profile_paths()
                return "completed"

            with mock.patch.object(
                    llm_review, "_run_batch_review_scoped",
                    side_effect=execute):
                outcome = llm_review._run_batch_review(
                    agent,
                    [{"run": 2, "profile_id": "vivhite"}],
                    log=lambda _message: None,
                )

            self.assertEqual(outcome, "completed")
            self.assertIs(observed["know"], vivhite)
            paths = observed["paths"]
            self.assertEqual(paths.profile_id, "vivhite")
            self.assertEqual(paths.root, vivhite.root)

    def test_startup_probes_all_profile_queues_with_one_worker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-resume-") as temp:
            root = Path(temp) / "knowledge"
            ironclad = _knowledge(root, "ironclad")
            vivhite = _knowledge(root / "profiles" / "vivhite", "vivhite")
            llm_review._save_queue(
                {"pending": [], "reviewing": None},
                profile_id="ironclad", profile_root=ironclad.root,
            )
            llm_review._save_queue(
                {
                    "pending": [{"run": 6, "profile_id": "vivhite"}],
                    "reviewing": None,
                },
                profile_id="vivhite", profile_root=vivhite.root,
            )
            agent = SimpleNamespace(
                know=ironclad,
                profile_id="ironclad",
                _profile_knowledge={
                    "ironclad": ironclad,
                    "vivhite": vivhite,
                },
            )

            with (mock.patch.object(
                    llm_review, "load_llm_config",
                    return_value={"enabled": True}),
                  mock.patch.object(
                      llm_review, "_salvage_recovery_needed",
                      return_value=False),
                  mock.patch.object(llm_review, "_ensure_worker") as ensure):
                llm_review.resume_review_queue(
                    agent, log=lambda _message: None)

            ensure.assert_called_once_with(agent, mock.ANY)
            self.assertEqual(
                set(agent._llm_review_profile_bindings),
                {"ironclad", "vivhite"},
            )

    def test_shared_worker_drains_each_profile_queue_separately(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-worker-") as temp:
            root = Path(temp) / "knowledge"
            ironclad = _knowledge(root, "ironclad")
            vivhite = _knowledge(root / "profiles" / "vivhite", "vivhite")
            llm_review._save_queue(
                {
                    "pending": [{"run": 3, "profile_id": "ironclad"}],
                    "reviewing": None,
                },
                profile_id="ironclad", profile_root=ironclad.root,
            )
            llm_review._save_queue(
                {
                    "pending": [{"run": 7, "profile_id": "vivhite"}],
                    "reviewing": None,
                },
                profile_id="vivhite", profile_root=vivhite.root,
            )
            agent = SimpleNamespace(
                know=ironclad,
                profile_id="ironclad",
                request_restart=False,
                _profile_knowledge={
                    "ironclad": ironclad,
                    "vivhite": vivhite,
                },
            )
            profiles: list[str] = []

            def complete(_agent, batch, _log):
                profiles.append(llm_review._batch_profile_id(batch))
                if len(profiles) == 2:
                    agent.request_restart = True
                return "completed"

            maintenance = (
                "_kill_orphan_review_processes",
                "_cleanup_stale_private_git_temps",
                "_recover_deferred_salvages",
                "_recover_unpointed_review_sandboxes",
                "_recover_review_holds",
                "_recover_committed_retry_resolutions",
                "_recover_salvage_replay_queue",
                "_backfill_rejection_ledger",
                "_resume_host_salvage_closures",
            )
            patches = [mock.patch.object(llm_review, name) for name in maintenance]
            for patch in patches:
                patch.start()
            try:
                with (mock.patch.object(
                        llm_review, "_review_stop_requested",
                        return_value=False),
                      mock.patch.object(
                          llm_review, "_wait_review_stop",
                          return_value=False),
                      mock.patch.object(
                          llm_review, "load_llm_config",
                          return_value={
                              "enabled": True,
                              "review_queue_max": 10,
                              "max_runs_in_packet": 10,
                          }),
                      mock.patch.object(
                          llm_review, "_run_batch_review",
                          side_effect=complete)):
                    llm_review._worker_loop(
                        agent, log=lambda _message: None)
            finally:
                for patch in reversed(patches):
                    patch.stop()

            self.assertEqual(profiles, ["ironclad", "vivhite"])
            self.assertEqual(
                llm_review._load_queue(
                    profile_id="ironclad", profile_root=ironclad.root)["pending"],
                [],
            )
            self.assertEqual(
                llm_review._load_queue(
                    profile_id="vivhite", profile_root=vivhite.root)["pending"],
                [],
            )

    def test_nested_profile_runtime_paths_are_not_review_actions(self) -> None:
        policy = "sts2-ascend/knowledge/profiles/vivhite/policy.json"
        report = "sts2-ascend/knowledge/profiles/vivhite/meta_review.md"

        self.assertTrue(llm_review._is_profile_online_review_path(policy))
        self.assertTrue(llm_review._is_profile_online_review_path(report))
        self.assertFalse(llm_review._is_review_action_path(report))
        with llm_review._review_profile_scope("vivhite"):
            self.assertFalse(llm_review._is_profile_online_review_path(report))
            allowed, _cache, online, rejected = (
                llm_review._partition_review_changes([
                    report,
                    "sts2-ascend/knowledge/meta_review.md",
                ]))
        self.assertEqual(allowed, [report])
        self.assertEqual(online, ["sts2-ascend/knowledge/meta_review.md"])
        self.assertEqual(rejected, [])


if __name__ == "__main__":
    unittest.main()
