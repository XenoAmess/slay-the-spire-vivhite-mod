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


@contextmanager
def _lock(**_kwargs):
    yield


class ReviewHealthMarkerTests(unittest.TestCase):
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
            instance._boot_head = "c" * 40
            fake_autogit = SimpleNamespace(repository_lock=_lock)
            accepted = SimpleNamespace(returncode=0)

            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", knowledge), \
                    mock.patch.object(agent_module, "autogit", fake_autogit), \
                    mock.patch.object(agent_module.subprocess, "run", return_value=accepted):
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
            fake_autogit = SimpleNamespace(repository_lock=_lock)
            rejected = SimpleNamespace(returncode=1)

            with mock.patch.object(agent_module, "KNOWLEDGE_DIR", knowledge), \
                    mock.patch.object(agent_module, "autogit", fake_autogit), \
                    mock.patch.object(agent_module.subprocess, "run", return_value=rejected):
                instance._mark_review_run_healthy()

            self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), original)


if __name__ == "__main__":
    unittest.main()
