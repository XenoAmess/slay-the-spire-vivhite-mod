"""Regression tests for mandatory evidence-to-code review closure."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402


REPORT = "sts2-ascend/knowledge/meta_review.md"
CONCLUSION = "sts2-ascend/knowledge/review_conclusion.txt"
SELFCHECK = "sts2-ascend/brain/selfcheck.py"
POLICY = "sts2-ascend/brain/policy.py"
AGENT = "sts2-ascend/brain/agent.py"


class ReviewClosureTests(unittest.TestCase):
    def test_recovered_batch_description_is_ordered_and_honest(self) -> None:
        self.assertEqual(llm_review._batch_description([730, 698, 699, 729]),
                         "第 698~730 局范围内的 4 局")
        self.assertEqual(llm_review._batch_description([3, 2, 1]), "第 1~3 局")

    def test_default_policy_requires_runtime_action_every_batch(self) -> None:
        cfg = llm_review.load_llm_config()
        self.assertTrue(cfg["review_require_action_every_batch"])
        self.assertEqual(cfg["review_report_only_limit"], 2)
        self.assertEqual(cfg["review_evidence_run_threshold"], 3)
        self.assertEqual(cfg["review_evidence_batch_threshold"], 2)

    def test_model_editable_config_can_adjust_closure_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-config-") as root:
            path = Path(root) / "config.json"
            path.write_text(json.dumps({"llm": {
                "review_require_action_every_batch": False,
                "review_report_only_limit": 11,
                "review_evidence_run_threshold": 12,
                "review_evidence_batch_threshold": 13,
            }}), encoding="utf-8")
            with mock.patch.object(llm_review, "CONFIG_PATH", path):
                cfg = llm_review.load_llm_config()
        self.assertFalse(cfg["review_require_action_every_batch"])
        self.assertEqual(cfg["review_report_only_limit"], 11)
        self.assertEqual(cfg["review_evidence_run_threshold"], 12)
        self.assertEqual(cfg["review_evidence_batch_threshold"], 13)

    def test_host_classification_cannot_be_satisfied_by_reports_or_tests(self) -> None:
        self.assertEqual(llm_review._review_action_paths([REPORT, CONCLUSION]), ())
        self.assertEqual(llm_review._review_action_paths([REPORT, SELFCHECK]), ())
        self.assertEqual(llm_review._review_action_paths([REPORT, AGENT]), (AGENT,))
        self.assertEqual(llm_review._review_action_paths([POLICY, SELFCHECK]), (POLICY,))

    def test_every_batch_gate_rejects_docs_and_accepts_runtime_observability(self) -> None:
        state = {
            "action_required": True,
            "require_action_every_batch": True,
            "consecutive_report_only": 3,
            "report_only_limit": 2,
        }
        denied = llm_review._review_closure_gate_error(state, [REPORT, CONCLUSION])
        self.assertIn("每批落地", denied)
        self.assertIn("仅 selfcheck", denied)
        self.assertEqual(llm_review._review_closure_gate_error(state, [REPORT, AGENT]), "")

        comment_only = (
            "diff --git a/sts2-ascend/brain/agent.py b/sts2-ascend/brain/agent.py\n"
            "--- a/sts2-ascend/brain/agent.py\n"
            "+++ b/sts2-ascend/brain/agent.py\n"
            "@@ -1 +1 @@\n-old = 1\n+# 只写注释冒充观测\n"
        ).encode()
        # The removed executable line makes this a substantive deletion; use a
        # pure added-comment hunk for the actual rejection case.
        pure_comment = (
            "diff --git a/sts2-ascend/brain/agent.py b/sts2-ascend/brain/agent.py\n"
            "--- a/sts2-ascend/brain/agent.py\n"
            "+++ b/sts2-ascend/brain/agent.py\n"
            "@@ -1,0 +2 @@\n+# 只写注释冒充观测\n"
        ).encode()
        code_change = (
            "diff --git a/sts2-ascend/brain/agent.py b/sts2-ascend/brain/agent.py\n"
            "--- a/sts2-ascend/brain/agent.py\n"
            "+++ b/sts2-ascend/brain/agent.py\n"
            "@@ -1,0 +2 @@\n+log('closure metric')\n"
        ).encode()
        self.assertTrue(llm_review._patch_has_substantive_action(comment_only, [AGENT]))
        self.assertFalse(llm_review._patch_has_substantive_action(pure_comment, [AGENT]))
        self.assertIn("注释/空白", llm_review._review_closure_gate_error(
            state, [REPORT, AGENT], pure_comment))
        self.assertEqual(llm_review._review_closure_gate_error(
            state, [REPORT, AGENT], code_change), "")

    def test_bootstrap_counts_report_only_commits_until_last_runtime_action(self) -> None:
        output = """__STS2_REVIEW_COMMIT__new

sts2-ascend/knowledge/meta_review.md
sts2-ascend/knowledge/review_conclusion.txt
__STS2_REVIEW_COMMIT__older

sts2-ascend/knowledge/meta_review.md
__STS2_REVIEW_COMMIT__action

sts2-ascend/brain/policy.py
sts2-ascend/knowledge/meta_review.md
"""
        completed = SimpleNamespace(returncode=0, stdout=output)
        with mock.patch.object(llm_review.subprocess, "run", return_value=completed):
            self.assertEqual(llm_review._infer_recent_report_only_streak(), 2)

    def test_state_is_host_owned_and_hard_required_even_after_implementation(self) -> None:
        know = SimpleNamespace(progression={
            "review_report_only_streak": 0,
            "review_closure_last_outcome": "implemented",
        })
        state = llm_review._review_closure_state(know, {
            "review_require_action_every_batch": True,
            "review_report_only_limit": 2,
            "review_evidence_run_threshold": 3,
            "review_evidence_batch_threshold": 2,
        })
        self.assertEqual(state["state_source"], "progression")
        self.assertTrue(state["action_required"])
        self.assertEqual(state["consecutive_report_only"], 0)

    def test_only_accepted_runtime_action_resets_streak(self) -> None:
        know = SimpleNamespace(progression={})
        base = {"consecutive_report_only": 4, "report_only_limit": 2,
                "require_action_every_batch": True}
        llm_review._record_review_closure(
            know, base, [REPORT, POLICY, SELFCHECK], [721, 722, 723],
            log=lambda _message: None)
        self.assertEqual(know.progression["review_report_only_streak"], 0)
        self.assertEqual(know.progression["review_closure_last_outcome"], "implemented")
        self.assertEqual(know.progression["review_closure_last_runs"], [721, 722, 723])

    def test_historical_zero_code_sections_are_injected_as_debt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-debt-") as root:
            report = Path(root) / "meta_review.md"
            report.write_text(
                "# 2026-08-27｜第 700 局复盘\n零代码纪律，问题 A 待立项。\n\n"
                "# 2026-08-27｜第 701 局复盘\n已修改 policy.py。\n\n"
                "# 2026-08-27｜第 702 局复盘\n未改任何 .py，问题 B 待观察。\n",
                encoding="utf-8")
            with mock.patch.object(llm_review, "REVIEW_LOG", report):
                debt = llm_review._historical_zero_code_context()
        self.assertIn("问题 A", debt)
        self.assertIn("问题 B", debt)
        self.assertNotIn("已修改 policy.py", debt)

    def test_prompt_forbids_zero_code_and_requires_historical_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-review-prompt-") as root:
            knowledge = Path(root)
            (knowledge / "lessons.md").write_text("lesson", encoding="utf-8")
            report = knowledge / "meta_review.md"
            report.write_text(
                "# 2026-08-27｜第 723 局复盘\n零代码纪律，成长姿态第4例。\n",
                encoding="utf-8")
            know = SimpleNamespace(
                progression={"review_report_only_streak": 3},
                stats={"global": {"runs": 723}}, game_knowledge=None)
            state = {
                "action_required": True,
                "require_action_every_batch": True,
                "consecutive_report_only": 3,
                "report_only_limit": 2,
                "evidence_run_threshold": 3,
                "evidence_batch_threshold": 2,
                "state_source": "test",
            }
            with (mock.patch.object(llm_review, "KNOWLEDGE_DIR", knowledge),
                  mock.patch.object(llm_review, "REVIEW_LOG", report),
                  mock.patch.object(llm_review, "_review_run_records", return_value=[]),
                  mock.patch.object(llm_review, "_stats_digest", return_value={})):
                prompt = llm_review.build_prompt(
                    know, {"max_runs_in_packet": 100}, batch_runs=[723],
                    closure_state=state)
        self.assertIn("每个成功复盘批次", prompt)
        self.assertIn("相对安全", prompt)
        self.assertIn("历史问题", prompt)
        self.assertIn("成长姿态第4例", prompt)
        self.assertIn("纯 `meta_review.md`", prompt)


if __name__ == "__main__":
    unittest.main()
