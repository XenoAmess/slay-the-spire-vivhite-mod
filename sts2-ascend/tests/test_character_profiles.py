"""Character profile layout and legacy-compatibility regressions."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from character_profiles import (  # noqa: E402
    IRONCLAD_CHARACTER_ID,
    VIVHITE_CHARACTER_ID,
    CharacterProfile,
    ProfileStore,
    profile_root,
)
from knowledge import Knowledge  # noqa: E402


class CharacterProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-character-profiles-")
        self.root = Path(self.temp.name) / "knowledge"
        self.store = ProfileStore(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_ironclad_keeps_legacy_root_and_vivhite_is_isolated(self) -> None:
        ironclad = self.store.ironclad
        vivhite = self.store.vivhite

        self.assertTrue(ironclad.legacy_root)
        self.assertEqual(ironclad.root, self.root)
        self.assertEqual(vivhite.root, self.root / "profiles" / "vivhite")
        self.assertEqual(profile_root(self.root, IRONCLAD_CHARACTER_ID), self.root)
        self.assertEqual(profile_root(self.root, VIVHITE_CHARACTER_ID), vivhite.root)

    def test_profile_exposes_all_learned_and_shared_paths(self) -> None:
        profile = self.store.vivhite

        self.assertEqual(profile.stats_path, profile.root / "stats.json")
        self.assertEqual(profile.policy_path, profile.root / "policy.json")
        self.assertEqual(profile.progression_path, profile.root / "progression.json")
        self.assertEqual(profile.lessons_path, profile.root / "lessons.md")
        self.assertEqual(profile.runs_dir, profile.root / "runs")
        self.assertEqual(profile.game_dir, self.root / "game")
        self.assertEqual(profile.path_for("policy"), profile.policy_path)
        self.assertEqual(self.store.path_for("vivhite", "runs"), profile.runs_dir)

    def test_resolves_profile_and_character_ids_case_insensitively(self) -> None:
        self.assertIs(self.store.resolve("IRONCLAD"), self.store.ironclad)
        self.assertIs(self.store.resolve("Vivhite"), self.store.vivhite)
        self.assertIs(
            self.store.for_character(VIVHITE_CHARACTER_ID.lower()),
            self.store.vivhite,
        )
        with self.assertRaises(KeyError):
            self.store.resolve("unknown-character")

    def test_legacy_untagged_run_logs_belong_to_ironclad(self) -> None:
        self.assertIs(self.store.for_run({"run_id": "legacy"}), self.store.ironclad)
        self.assertIs(
            self.store.profile_for_run({"character_id": VIVHITE_CHARACTER_ID}),
            self.store.vivhite,
        )
        self.assertIs(
            self.store.for_run({"character_profile": "vivhite"}),
            self.store.vivhite,
        )

    def test_ensure_only_creates_the_selected_profile_layout(self) -> None:
        profile = self.store.ensure("vivhite")

        self.assertIsInstance(profile, CharacterProfile)
        self.assertTrue(profile.runs_dir.is_dir())
        self.assertFalse((self.root / "runs").exists())
        self.assertFalse(profile.stats_path.exists())

    def test_knowledge_accepts_profile_and_uses_shared_game_facts(self) -> None:
        profile = self.store.vivhite
        knowledge = Knowledge(profile, repair_phantoms=False)

        self.assertIs(knowledge.profile, profile)
        self.assertEqual(knowledge.root, profile.root)
        self.assertEqual(knowledge.progression["character"], VIVHITE_CHARACTER_ID)
        self.assertEqual(knowledge.game_knowledge.game_root, self.root / "game")

        knowledge.save()
        self.assertTrue(profile.stats_path.is_file())
        self.assertTrue(profile.policy_path.is_file())
        self.assertTrue(profile.progression_path.is_file())
        self.assertFalse((self.root / "stats.json").exists())

    def test_legacy_path_constructor_remains_ironclad_compatible(self) -> None:
        knowledge = Knowledge(self.root, repair_phantoms=False)

        self.assertIsNone(knowledge.profile)
        self.assertEqual(knowledge.root, self.root)
        self.assertEqual(knowledge.progression["character"], IRONCLAD_CHARACTER_ID)
        self.assertEqual(knowledge.game_knowledge.game_root, self.root / "game")


if __name__ == "__main__":
    unittest.main()
