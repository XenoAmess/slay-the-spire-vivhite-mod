"""Boundary matrix for isolated-review path classification."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import autogit  # noqa: E402


class ReviewPathClassifierTests(unittest.TestCase):
    def assert_paths(self, expected: str, paths: list[str]) -> None:
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(autogit.classify_review_path(path), expected)

    def test_accepts_project_source_config_tests_docs_and_curated_knowledge(self) -> None:
        self.assert_paths(autogit.REVIEW_PATH_ACCEPTED, [
            "sts2-ascend/brain/autogit.py",
            "sts2-ascend/brain/config.json",
            "sts2-ascend/tests/test_review_path_classifier.py",
            "sts2-ascend/docs/review-design.md",
            "sts2-ascend/scripts/Start-Agent.ps1",
            "sts2-ascend/README.md",
            "sts2-ascend/.gitignore",
            "sts2-ascend/knowledge/meta_review.md",
            "sts2-ascend/knowledge/review_conclusion.txt",
            "sts2-ascend/knowledge/game/v0.111.0/mechanics/cards.jsonl",
            "sts2-ascend/knowledge/game/v0.111.0/localization/zhs/cards.json",
            # Log-like names are runtime only at the knowledge root. Curated
            # nested knowledge stays reviewable.
            "sts2-ascend/knowledge/game/research.log",
            "sts2-ascend/knowledge/curated/analysis.LOCK",
            # Similar names must not turn a precise runtime boundary into a prefix gate.
            "sts2-ascend/.runtime-notes/readme.md",
            "sts2-ascend/knowledge/runs-notes.md",
            "sts2-ascend/knowledge/stats_notes.md",
            "sts2-ascend/knowledge/review_prompting.md",
            "sts2-ascend/REVIEW_REJECTIONS.md.bak",
        ])
        self.assertEqual(
            autogit.classify_review_path(r"sts2-ascend\brain\policy.py"),
            autogit.REVIEW_PATH_ACCEPTED,
        )

    def test_partitions_all_online_runtime_scopes(self) -> None:
        self.assert_paths(autogit.REVIEW_PATH_ONLINE_RUNTIME, [
            "sts2-ascend/.runtime/session.json",
            "sts2-ascend/knowledge/runs/run-1.json",
            "sts2-ascend/knowledge/archive/run-1.json",
            "sts2-ascend/knowledge/code_backups/review_work/prompt.md",
            "sts2-ascend/knowledge/stats.json",
            "sts2-ascend/knowledge/progression.json",
            "sts2-ascend/knowledge/policy.json",
            "sts2-ascend/knowledge/lessons.md",
            "sts2-ascend/knowledge/review_queue.json",
            "sts2-ascend/knowledge/preferred_model_state.json",
            "sts2-ascend/knowledge/pending_restart.json",
            "sts2-ascend/knowledge/.pending_restart.123.tmp",
            "sts2-ascend/KNOWLEDGE/.STATS.snapshot.tmp",
            "sts2-ascend/Knowledge/REVIEW_QUEUE.JSON.tmp",
            "sts2-ascend/knowledge/review_rollback_tombstones.json",
            "sts2-ascend/knowledge/stale_code_restart.json",
            "sts2-ascend/knowledge/voice_volume.json",
            "sts2-ascend/knowledge/brain.log",
            "sts2-ascend/knowledge/VOICE_SPEAKER.LOCK",
            "sts2-ascend/knowledge/review_live.stream",
            "sts2-ascend/knowledge/review_active.flag",
            "sts2-ascend/knowledge/screenshot-now.png",
            "sts2-ascend/knowledge/review_prompt_latest.md",
            "sts2-ascend/REVIEW_REJECTIONS.md",
        ])

    def test_cache_is_case_insensitive_and_wins_over_online_runtime(self) -> None:
        self.assert_paths(autogit.REVIEW_PATH_CACHE, [
            "sts2-ascend/brain/__pycache__/policy.cpython-314.pyc",
            "sts2-ascend/brain/tool-CACHE/result.bin",
            "sts2-ascend/brain/cache_policy.py",
            "sts2-ascend/brain/model.PYC",
            "sts2-ascend/brain/model.pyo",
            "sts2-ascend/knowledge/runs/__PYCACHE__/run.bin",
            "sts2-ascend/.runtime/model.pyc",
            # A safe clone-relative tool cache outside sts2-ascend is still a
            # transient artifact: it is excluded from the patch but retained
            # in the full forensic snapshot.
            "tool-CACHE/result.bin",
        ])

    def test_git_metadata_wins_over_cache_and_online_runtime(self) -> None:
        self.assert_paths(autogit.REVIEW_PATH_GIT_METADATA, [
            "sts2-ascend/.git/config",
            "sts2-ascend/brain/.GIT/index",
            "sts2-ascend/.gitmodules",
            "sts2-ascend/knowledge/code_backups/review_work/repo/.git/HEAD",
            "sts2-ascend/.git/cache/index.bin",
        ])

    def test_unsafe_input_is_classified_without_weakening_normalization(self) -> None:
        unsafe = [
            "",
            "outside.txt",
            "../outside.txt",
            "sts2-ascend/../outside.txt",
            "sts2-ascend/*",
            "sts2-ascend/file?.py",
            "sts2-ascend/file[0].py",
            "sts2-ascend/bad\0name.py",
            "/tmp/sts2-ascend/brain/policy.py",
            r"C:\temp\sts2-ascend\brain\policy.py",
            # Windows drive-absolute and drive-relative syntax must never be
            # hidden by the cache exception.
            "C:/tmp/cache/result.bin",
            "C:cache/result.bin",
        ]
        self.assert_paths(autogit.REVIEW_PATH_OUTSIDE_UNSAFE, unsafe)
        for path in unsafe:
            with self.subTest(normalize=path):
                with self.assertRaises((TypeError, ValueError)):
                    autogit.normalize_paths([path])

        # The project root is a valid general Git pathspec but is never an exact
        # file target for a model-produced review patch.
        self.assertEqual(
            autogit.normalize_paths(["sts2-ascend"]), ("sts2-ascend",))
        self.assertEqual(
            autogit.classify_review_path("sts2-ascend"),
            autogit.REVIEW_PATH_OUTSIDE_UNSAFE,
        )

    def test_default_validation_is_deny_only_with_optional_exact_compatibility(self) -> None:
        self.assertEqual(
            autogit.validate_review_paths([
                "sts2-ascend/brain/autogit.py",
                "sts2-ascend/scripts/Start-Agent.ps1",
                "sts2-ascend/docs/review-design.md",
            ]),
            (
                "sts2-ascend/brain/autogit.py",
                "sts2-ascend/scripts/Start-Agent.ps1",
                "sts2-ascend/docs/review-design.md",
            ),
        )
        for path in (
            "sts2-ascend/knowledge/stats.json",
            "sts2-ascend/brain/__pycache__/policy.pyc",
            "sts2-ascend/.git/config",
            "outside.txt",
            "C:/tmp/cache/result.bin",
        ):
            with self.subTest(default_denied=path), self.assertRaises(ValueError):
                autogit.validate_review_paths([path])

        # Legacy callers can still request exact-file semantics. In particular,
        # a formerly allowed filename can never turn into a directory prefix.
        exact = autogit.REVIEW_PATCH_ALLOWLIST
        self.assertEqual(
            autogit.validate_review_paths(
                ["sts2-ascend/brain/selfcheck.py"], allowlist=exact),
            ("sts2-ascend/brain/selfcheck.py",),
        )
        with self.assertRaises(ValueError):
            autogit.validate_review_paths(
                ["sts2-ascend/brain/autogit.py"], allowlist=exact)
        with self.assertRaises(ValueError):
            autogit.validate_review_paths(
                ["sts2-ascend/brain/config.json/evil.py"], allowlist=exact)


if __name__ == "__main__":
    unittest.main()
