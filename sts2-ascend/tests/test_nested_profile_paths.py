"""Regression coverage for character-scoped knowledge stores."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import autogit  # noqa: E402
import compact_knowledge  # noqa: E402


def _run_payload(run_id: str, run_number: int) -> dict:
    return {
        "run_id": run_id,
        "run_number": run_number,
        "ascension": 0,
        "victory": False,
        "floor": run_number,
        "decisions": [
            {"screen": "COMBAT", "floor": run_number, "reason": run_id},
        ],
        "combat_notes": [],
    }


def _write_store(root: Path, prefix: str, run_count: int = 3) -> None:
    (root / "runs").mkdir(parents=True, exist_ok=True)
    (root / "stats.json").write_text('{"global":{"runs":0}}\n', encoding="utf-8")
    (root / "policy.json").write_text("{}\n", encoding="utf-8")
    (root / "progression.json").write_text("{}\n", encoding="utf-8")
    (root / "review_queue.json").write_text("{}\n", encoding="utf-8")
    (root / "lessons.md").write_text("# lessons\n", encoding="utf-8")
    for number in range(1, run_count + 1):
        payload = _run_payload(f"{prefix}_{number}", number)
        (root / "runs" / f"{prefix.lower()}-{number}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class NestedProfileClassifierTests(unittest.TestCase):
    def test_nested_profile_runtime_is_partitioned_without_hiding_static_files(self) -> None:
        profile = "sts2-ascend/knowledge/characters/vivhite"
        online = [
            f"{profile}/runs/run-1.json",
            f"{profile}/archive/manifest.json",
            f"{profile}/stats.json",
            f"{profile}/.stats.snapshot.tmp",
            f"{profile}/policy.json",
            f"{profile}/progression.json",
            f"{profile}/lessons.md",
            f"{profile}/review_queue.json",
            f"{profile}/.compact.lock",
        ]
        for path in online:
            with self.subTest(path=path):
                self.assertEqual(
                    autogit.classify_review_path(path),
                    autogit.REVIEW_PATH_ONLINE_RUNTIME,
                )
                with self.assertRaises(ValueError):
                    autogit.validate_review_paths([path])

        for path in (
            f"{profile}/strategy.md",
            "sts2-ascend/knowledge/game/v0.111.0/research.log",
            "sts2-ascend/knowledge/curated/analysis.LOCK",
        ):
            with self.subTest(static=path):
                self.assertEqual(
                    autogit.classify_review_path(path), autogit.REVIEW_PATH_ACCEPTED)

        # The legacy store at knowledge/ remains governed by the same rules.
        self.assertEqual(
            autogit.classify_review_path("sts2-ascend/knowledge/stats.json"),
            autogit.REVIEW_PATH_ONLINE_RUNTIME,
        )


class NestedProfileAutogitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-nested-autogit-")
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.base = self.repo / "sts2-ascend"
        self.root_store = self.base / "knowledge"
        self.profile_store = self.root_store / "characters" / "vivhite"
        _write_store(self.root_store, "ROOT", run_count=1)
        _write_store(self.profile_store, "PROFILE", run_count=1)
        (self.profile_store / "strategy.md").write_text("baseline\n", encoding="utf-8")

        self._git("init")
        self._git("config", "user.email", "nested-paths@example.invalid")
        self._git("config", "user.name", "Nested Paths Test")
        self._git("add", ".")
        self._git("commit", "-m", "baseline")

        self.old_repo = autogit.REPO_DIR
        self.old_base = autogit.BASE_DIR
        self.old_flag = autogit.REVIEW_ACTIVE_FILE
        autogit.REPO_DIR = self.repo
        autogit.BASE_DIR = self.base
        autogit.REVIEW_ACTIVE_FILE = self.root_store / "review_active.flag"

    def tearDown(self) -> None:
        autogit.REPO_DIR = self.old_repo
        autogit.BASE_DIR = self.old_base
        autogit.REVIEW_ACTIVE_FILE = self.old_flag
        self.temp.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True,
            capture_output=True, text=True, encoding="utf-8")

    def test_default_progress_commit_includes_root_and_nested_profile_only(self) -> None:
        (self.root_store / "stats.json").write_text(
            '{"global":{"runs":1}}\n', encoding="utf-8")
        (self.profile_store / "stats.json").write_text(
            '{"global":{"runs":1}}\n', encoding="utf-8")
        (self.profile_store / "runs" / "profile-2.json").write_text(
            json.dumps(_run_payload("PROFILE_2", 2)), encoding="utf-8")
        (self.profile_store / "strategy.md").write_text("user static edit\n", encoding="utf-8")

        result = autogit.commit_progress_result(
            "nested profile checkpoint", push=False)

        self.assertTrue(result.created, result.reason)
        committed = set(self._git(
            "diff-tree", "--no-commit-id", "--name-only", "-r", result.commit,
        ).stdout.splitlines())
        self.assertIn("sts2-ascend/knowledge/stats.json", committed)
        self.assertIn(
            "sts2-ascend/knowledge/characters/vivhite/stats.json", committed)
        self.assertIn(
            "sts2-ascend/knowledge/characters/vivhite/runs/profile-2.json", committed)
        self.assertNotIn(
            "sts2-ascend/knowledge/characters/vivhite/strategy.md", committed)
        self.assertIn("strategy.md", self._git("status", "--short").stdout)


class NestedProfileCompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-nested-compact-")
        self.project = Path(self.temp.name) / "sts2-ascend"
        self.root_store = self.project / "knowledge"
        self.profile_store = self.root_store / "characters" / "vivhite"
        _write_store(self.root_store, "ROOT")
        _write_store(self.profile_store, "PROFILE")
        self.options = compact_knowledge.CompactionOptions(
            keep_recent=0,
            deep_floor=99,
            keep_longest=0,
            keep_largest=0,
            keep_floor_representatives=False,
            keep_lessons=0,
            keep_meta_reviews=0,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_root_pass_plans_and_applies_each_nested_profile_store(self) -> None:
        plan = compact_knowledge.plan_compaction(self.root_store, self.options)

        self.assertEqual(plan.root, self.root_store.resolve())
        self.assertEqual(
            [item.root for item in plan.profile_plans],
            [self.profile_store.resolve()],
        )
        self.assertTrue(plan.archive_new)
        self.assertTrue(plan.profile_plans[0].archive_new)

        result = compact_knowledge.apply_compaction(self.root_store, self.options)

        self.assertTrue(result["changed"])
        self.assertEqual(len(result["character_profiles"]), 1)
        self.assertEqual(
            result["character_profiles"][0]["knowledge_dir"],
            str(self.profile_store.resolve()),
        )
        self.assertTrue((self.root_store / compact_knowledge.MANIFEST_REL).is_file())
        self.assertTrue((self.profile_store / compact_knowledge.MANIFEST_REL).is_file())

        second = compact_knowledge.apply_compaction(self.root_store, self.options)
        self.assertTrue(second["idempotent_noop"])

    def test_nested_profile_honours_root_activity_marker(self) -> None:
        (self.root_store / "review_active.flag").write_text("123\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "active knowledge store"):
            compact_knowledge.apply_compaction(self.profile_store, self.options)


if __name__ == "__main__":
    unittest.main()
