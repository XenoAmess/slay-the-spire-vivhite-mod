"""Host catalog matching uses transport IDs while preserving review identity."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))
import llm_review
from review_runners import ReviewPlan


class OpencodeCatalogResolverTests(unittest.TestCase):
    @staticmethod
    def _plan(model="kimi-for-coding/k3"):
        return ReviewPlan(
            key="kimi-k3", priority=1, runner="opencode", model=model,
            every_runs=5, source="preferred")

    def _resolve(self, plan, catalog):
        with (mock.patch.object(llm_review, "review_plans_from_config",
                                return_value=[plan]),
              mock.patch.object(llm_review, "_preferred_cooldown_remaining",
                                return_value=0.0),
              mock.patch.object(llm_review, "runner_binary", return_value="opencode.exe"),
              mock.patch.object(llm_review, "_query_available_models",
                                return_value=catalog) as query,
              mock.patch.object(llm_review, "_query_codex_models") as codex):
            selected = llm_review.resolve_review_plan({}, log=lambda _: None)
        query.assert_called_once()
        codex.assert_not_called()
        return selected

    def test_native_k3_catalog_preserves_logical_model_and_affinity(self):
        plan = self._plan()
        selected = self._resolve(plan, {"kimi-code-plan-cn/k3"})
        self.assertIs(selected, plan)
        self.assertEqual(selected.model, "kimi-for-coding/k3")
        self.assertEqual(selected.state_key, plan.state_key)
        self.assertEqual((selected.key, selected.every_runs), ("kimi-k3", 5))

    def test_missing_catalog_keeps_logical_plan_unavailable(self):
        plan = self._plan()
        for catalog in (None, set()):
            with self.subTest(catalog=catalog):
                selected = self._resolve(plan, catalog)
                self.assertFalse(selected.available)
                self.assertEqual(selected.model, plan.model)
                self.assertEqual(selected.key, plan.key)
                self.assertEqual(selected.state_key, plan.state_key)
                self.assertIn("model-unavailable", selected.unavailable_reason)

    def test_unrelated_model_ids_are_not_aliased(self):
        for model, catalog, available in (
            ("kimi-for-coding/k3", {"kimi-code-plan-cn/k3-preview"}, False),
            ("kimi-for-coding/k2.5", {"kimi-code-plan-cn/k3"}, False),
            ("other/k3", {"kimi-code-plan-cn/k3"}, False),
            ("kimi-for-coding/k2.5", {"kimi-for-coding/k2.5"}, True),
            ("opencode-go/glm-5.3-flash", {"opencode-go/glm-5.3-flash"}, True),
        ):
            with self.subTest(model=model, catalog=catalog):
                plan = self._plan(model)
                selected = self._resolve(plan, catalog)
                self.assertEqual(selected.available, available)
                self.assertEqual(selected.model, model)
                if available:
                    self.assertIs(selected, plan)


if __name__ == "__main__":
    unittest.main()
