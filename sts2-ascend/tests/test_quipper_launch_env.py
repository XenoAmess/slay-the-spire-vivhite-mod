"""Regression coverage for the IndexTTS uv child environment."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import agent as agent_module  # noqa: E402


class QuipperLaunchEnvironmentTests(unittest.TestCase):
    def test_uv_child_drops_parent_python_roots_but_keeps_lifecycle(self) -> None:
        instance = object.__new__(agent_module.Agent)
        popen = mock.Mock()
        thread = mock.Mock()
        thread.start = mock.Mock()
        owner_epoch = SimpleNamespace(
            OWNER_PROTOCOL_VERSION=1,
            code_epoch=lambda _root: "epoch-under-test",
            status_matches=lambda *_args, **_kwargs: False,
        )
        client = SimpleNamespace(health=lambda **_kwargs: None)
        inherited = {
            "PYTHONHOME": r"C:\\Python314",
            "PYTHONPATH": r"C:\\Python314\\Lib",
            "STS2_ASCEND_SESSION_ID": "session-under-test",
            "STS2_ASCEND_RUNTIME_DIR": r"G:\\runtime",
            "STS2_ASCEND_STOP_FILE": r"G:\\runtime\\stop.request",
        }

        with (mock.patch.dict(os.environ, inherited, clear=True),
              mock.patch.dict(sys.modules, {
                  "indextts_client": client,
                  "owner_epoch": owner_epoch,
              }),
              mock.patch("shutil.which", return_value=sys.executable),
              mock.patch.object(agent_module.subprocess, "Popen", popen),
              mock.patch.object(agent_module.threading, "Thread",
                                return_value=thread)):
            instance._launch_quipper()

        child_env = popen.call_args.kwargs["env"]
        self.assertNotIn("PYTHONHOME", child_env)
        self.assertNotIn("PYTHONPATH", child_env)
        self.assertEqual(
            child_env["STS2_ASCEND_SESSION_ID"], "session-under-test")
        self.assertEqual(
            child_env["STS2_ASCEND_RUNTIME_DIR"], r"G:\\runtime")
        self.assertEqual(
            child_env["STS2_ASCEND_STOP_FILE"], r"G:\\runtime\\stop.request")
        thread.start.assert_called_once_with()

    def test_inconclusive_game_probe_never_launches_a_duplicate(self) -> None:
        instance = object.__new__(agent_module.Agent)
        instance.client = SimpleNamespace(discover=mock.Mock(return_value=False))
        instance._game_process_count = mock.Mock(return_value=None)
        instance._wait_for_game_api = mock.Mock(return_value=False)

        with (mock.patch.object(agent_module, "stop_requested", return_value=False),
              mock.patch.object(agent_module.subprocess, "Popen") as popen):
            self.assertFalse(instance.ensure_game())

        instance._wait_for_game_api.assert_called_once_with(
            timeout_s=300.0, poll_s=4.0)
        popen.assert_not_called()

if __name__ == "__main__":
    unittest.main()
