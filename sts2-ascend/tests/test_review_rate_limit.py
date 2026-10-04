"""Regression coverage for provider HTTP 429 review-queue recovery."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402


class ProviderRateLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-review-rate-limit-")
        self.queue = Path(self.temp.name) / "review_queue.json"
        self.old_queue = llm_review.QUEUE_FILE
        llm_review.QUEUE_FILE = self.queue

    def tearDown(self) -> None:
        llm_review.QUEUE_FILE = self.old_queue
        self.temp.cleanup()

    def test_provider_rate_limit_info_reads_structured_429(self) -> None:
        sandbox = llm_review.SandboxReviewResult(
            rc=1,
            error="provider exited with an error",
            provider_metrics={
                "rate_limit": {
                    "status_code": 429,
                    "retry_after_seconds": 42.5,
                    "message": "  Too many requests  ",
                    "source": "codex",
                },
            },
        )

        info = llm_review._provider_rate_limit_info(sandbox, {})

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["status_code"], 429)
        self.assertEqual(info["retry_after_seconds"], 42.5)
        self.assertEqual(info["retry_after_raw"], 42.5)
        self.assertEqual(info["message"], "Too many requests")
        self.assertEqual(info["source"], "codex")
        self.assertEqual(info["failure_code"], "provider_http_429")
        self.assertEqual(info["deferred_kind"], "provider_rate_limit")

    def test_provider_rate_limit_info_rejects_non_429_and_clean_success(self) -> None:
        non_429 = llm_review.SandboxReviewResult(
            rc=1,
            error="provider failed",
            provider_metrics={
                "rate_limit_detected": True,
                "rate_limit_status": 503,
                "retry_after_seconds": 10,
            },
        )
        self.assertIsNone(llm_review._provider_rate_limit_info(non_429, {}))

        successful_patch = llm_review.SandboxReviewResult(
            rc=0,
            paths=("brain/config.json",),
            patch=b"valid patch",
            provider_metrics={
                "rate_limit_detected": True,
                "rate_limit_status": 429,
                "retry_after_seconds": 10,
            },
        )
        self.assertIsNone(
            llm_review._provider_rate_limit_info(successful_patch, {}))

    def test_provider_unavailable_info_accepts_only_structured_credit_failure(self) -> None:
        sandbox = llm_review.SandboxReviewResult(
            rc=1,
            error="provider failed",
            provider_metrics={
                "provider_unavailable": {
                    "status_code": 401,
                    "reason": "insufficient_credits",
                    "message": "Insufficient balance",
                    "source": "error.status_code",
                },
            },
        )

        info = llm_review._provider_unavailable_info(sandbox)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info["status_code"], 401)
        self.assertEqual(info["failure_code"], "provider_account_unavailable")
        self.assertEqual(info["deferred_kind"], "provider_unavailable")
        self.assertEqual(info["reason"], "insufficient_credits")

        ordinary_auth = llm_review.SandboxReviewResult(
            rc=1,
            provider_metrics={
                "provider_unavailable_detected": True,
                "provider_unavailable_status": 401,
                "provider_unavailable_reason": "invalid_token",
            },
        )
        self.assertIsNone(llm_review._provider_unavailable_info(ordinary_auth))

    def test_server_retry_delay_is_not_shortened_by_host_backoff_cap(self) -> None:
        self.assertEqual(llm_review._bounded_provider_retry_delay(
            10_000, {"provider_rate_limit_max_retry_seconds": 30}), 10_000.0)
        self.assertEqual(llm_review._bounded_provider_retry_delay(None, {}), 60.0)
        self.assertEqual(llm_review._bounded_provider_retry_delay(
            None, {"provider_rate_limit_max_retry_seconds": 30}), 30.0)

    def test_missing_header_is_distinct_and_uses_bounded_exponential_jitter(self):
        info = llm_review._provider_rate_limit_info(llm_review.SandboxReviewResult(
            rc=1, provider_metrics={"rate_limit_detected": True}), {})
        self.assertEqual(info["retry_after_source"], "fallback")
        with mock.patch.object(llm_review.random, "uniform", return_value=1.1):
            waits = [llm_review._provider_retry_backoff(i, {}) for i in (1, 2, 3, 20)]
        self.assertEqual(waits, [66.0, 132.0, 264.0, 900.0])

    def test_recovered_manifest_preserves_server_absolute_deadline(self):
        fields = llm_review._manifest_review_queue_fields({
            "model": "audit", "provider_retry_at": 4600.0,
            "provider_rate_limit": {"status_code": 429, "retry_after_seconds": 3600.0,
                                    "retry_after_source": "server"},
        }, {})
        self.assertEqual(fields["retry_after"], 4600.0)
        self.assertEqual(fields["deferred_retry_after_seconds"], 3600.0)
        self.assertEqual(fields["deferred_retry_after_source"], "server")

    def test_missing_header_finalization_increments_backoff_and_keeps_one_item(self):
        item = {"run": 1, "queue_id": "retry-one", "runner": "codex", "model": "audit",
                "retry_same_model": True, "deferred_kind": "provider_rate_limit",
                "deferred_retry_after_source": "fallback"}
        waits = []
        with (mock.patch.object(llm_review.time, "time", return_value=1000.0),
              mock.patch.object(llm_review.random, "uniform", return_value=1.0),
              mock.patch.object(llm_review, "load_llm_config", return_value={})):
            for _ in range(4):
                self.queue.write_text(json.dumps({
                    "pending": [], "reviewing": {"runs": [1], "items": [item]},
                }), encoding="utf-8")
                waits.append(llm_review._finalize_review_batch(
                    [item], "deferred", log=lambda _: None))
                q = llm_review._load_queue_unlocked()
                self.assertEqual(len(q["pending"]), 1)
                item = q["pending"][0]
        self.assertEqual(waits, [60.0, 120.0, 240.0, 480.0])
        self.assertEqual(item["deferred_count"], 4)
        self.assertEqual(item["retry_after"], 1480.0)
        self.assertTrue(item["retry_same_model"])
        self.assertEqual(item["queue_id"], "retry-one")

    def test_finalize_provider_rate_limit_uses_explicit_delay_and_keeps_affinity(self) -> None:
        batch = [{
            "run": 42,
            "queue_id": "rate-limit-42",
            "runner": "codex",
            "model": "gpt-5.6-luna",
            "source": "preferred",
            "retry_same_model": True,
            "deferred_kind": "provider_rate_limit",
            "deferred_reason": "HTTP 429",
            "deferred_retry_after_seconds": 12.0,
            # Finalization increments this to the normal hold threshold.  A
            # provider 429 must remain reusable and never enter that hold.
            "deferred_count": llm_review._REVIEW_DEFERRED_HOLD_AFTER - 1,
            "deferred_hold_until": 0,
            "retry_after": 0,
        }]
        self.queue.parent.mkdir(parents=True, exist_ok=True)
        self.queue.write_text(
            json.dumps({
                "pending": [],
                "reviewing": {
                    "runs": [42],
                    "items": [dict(batch[0])],
                },
            }),
            encoding="utf-8",
        )

        with mock.patch.object(llm_review.time, "time", return_value=1000.0):
            delay = llm_review._finalize_review_batch(
                batch, "deferred", log=lambda _message: None)

        saved = llm_review._load_queue_unlocked()
        self.assertEqual(delay, 12.0)
        self.assertIsNone(saved["reviewing"])
        self.assertEqual(len(saved["pending"]), 1)
        deferred = saved["pending"][0]
        self.assertEqual(deferred["retry_after"], 1012.0)
        self.assertEqual(deferred["deferred_retry_after_seconds"], 12.0)
        self.assertEqual(deferred["deferred_count"],
                         llm_review._REVIEW_DEFERRED_HOLD_AFTER)
        self.assertTrue(deferred["retry_same_model"])
        self.assertEqual(deferred["runner"], "codex")
        self.assertEqual(deferred["model"], "gpt-5.6-luna")
        self.assertEqual(deferred["deferred_kind"], "provider_rate_limit")
        self.assertEqual(deferred["deferred_hold_until"], 0)


if __name__ == "__main__":
    unittest.main()
