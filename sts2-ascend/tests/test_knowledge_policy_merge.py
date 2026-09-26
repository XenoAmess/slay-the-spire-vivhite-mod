"""Local policy edits survive repeated refreshes until a successful save."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import knowledge  # noqa: E402


class KnowledgePolicyMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ascend-policy-merge-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _store(self, policy: dict) -> knowledge.Knowledge:
        self._write_policy(policy)
        return knowledge.Knowledge(self.root, repair_phantoms=False)

    def _write_policy(self, policy: dict) -> None:
        (self.root / "policy.json").write_text(
            json.dumps(policy), encoding="utf-8")

    def test_unrelated_disk_update_does_not_acknowledge_unsaved_local_edit(self) -> None:
        store = self._store({"local": 1, "external": 1})
        store.policy["local"] = 2
        self._write_policy({"local": 1, "external": 2})

        self.assertIn("external", store.refresh_policy())
        store.refresh_policy()
        self.assertEqual(store.policy["local"], 2)
        store._save_policy_merged()
        saved = json.loads((self.root / "policy.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["local"], saved["external"]), (2, 2))

        self._write_policy({**saved, "local": 3})
        self.assertIn("local", store.refresh_policy())
        self.assertEqual(store.policy["local"], 3)

    def test_nested_local_edit_is_distinct_from_its_sync_baseline(self) -> None:
        store = self._store({"nested": {"weight": 1}, "external": 1})
        store.policy["nested"]["weight"] = 2
        self._write_policy({"nested": {"weight": 3}, "external": 2})

        store.refresh_policy()
        store.refresh_policy()
        store._save_policy_merged()
        saved = json.loads((self.root / "policy.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["nested"], {"weight": 2})
        self.assertEqual(saved["external"], 2)

        store.policy["nested"]["weight"] = 4
        store.refresh_policy()
        self.assertEqual(store.policy["nested"], {"weight": 4})

    def test_adopted_nested_value_gets_an_independent_sync_baseline(self) -> None:
        store = self._store({"nested": {"weight": 1}})
        self._write_policy({"nested": {"weight": 2}})
        store.refresh_policy()
        store.policy["nested"]["weight"] = 3

        store.refresh_policy()
        self.assertEqual(store.policy["nested"], {"weight": 3})

    def test_default_addition_does_not_acknowledge_unsaved_local_edit(self) -> None:
        store = self._store({"local": 1})
        store.policy["local"] = 2
        del store.policy["block_safety"]

        self.assertIn("block_safety", store.refresh_policy())
        store.refresh_policy()
        self.assertEqual(store.policy["local"], 2)

    def test_new_defaults_are_isolated_between_profiles_and_module(self) -> None:
        defaults = copy.deepcopy(knowledge.DEFAULT_POLICY["room_weights"])
        # Restore the constant even when this regression runs on the old code.
        self.addCleanup(knowledge.DEFAULT_POLICY.__setitem__, "room_weights", defaults)
        first = self._store({})
        second_root = self.root / "second"
        second_root.mkdir()
        (second_root / "policy.json").write_text("{}", encoding="utf-8")
        second = knowledge.Knowledge(second_root, repair_phantoms=False)

        first.policy["room_weights"]["Monster"] = 999
        self.assertEqual(second.policy["room_weights"], defaults)
        self.assertEqual(knowledge.DEFAULT_POLICY["room_weights"], defaults)


if __name__ == "__main__":
    unittest.main()
