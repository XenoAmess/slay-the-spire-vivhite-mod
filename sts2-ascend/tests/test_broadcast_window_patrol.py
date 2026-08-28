"""Behavioral coverage for the token-free broadcast window patrol."""
from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import broadcast_window_patrol as patrol  # noqa: E402


class BroadcastWindowPatrolTests(unittest.TestCase):
    def test_elevated_livehime_uses_process_name_fallback(self) -> None:
        with mock.patch.object(
                patrol, "process_name_running", return_value=True) as basename:
            self.assertTrue(
                patrol._livehime_process_running(
                    Path(r"C:\Program Files\bililive\livehime\livehime.exe")))
        basename.assert_called_once_with("livehime.exe")

    def test_livehime_state_uses_latest_local_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix="livehime-state-") as root:
            log = Path(root) / "bililive_debug.log"
            log.write_bytes(
                b"set_streaming_status: last_status:5 set_status:0\n"
                b"set_streaming_status: last_status:0 set_status:5\n"
            )
            self.assertEqual(
                patrol.get_livehime_streaming_state(
                    log_path=log,
                    livehime_executable=Path(root) / "livehime.exe",
                    process_checker=lambda _path: True,
                ),
                "Streaming",
            )

    def test_livehime_must_be_running_even_with_stale_streaming_log(self) -> None:
        with tempfile.TemporaryDirectory(prefix="livehime-stale-") as root:
            log = Path(root) / "bililive_debug.log"
            log.write_bytes(b"set_streaming_status: last_status:0 set_status:5\n")
            self.assertEqual(
                patrol.get_livehime_streaming_state(
                    log_path=log,
                    process_checker=lambda _path: False,
                ),
                "NotRunning",
            )

    def test_current_session_requires_running_and_absolute_game_exe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="broadcast-session-") as root:
            session = Path(root) / "session.json"
            game = Path(root).resolve() / "SlayTheSpire2.exe"
            session.write_text(
                json.dumps({"state": "running", "game_exe": str(game)}),
                encoding="utf-8",
            )
            self.assertEqual(patrol.current_session_game_executable(session), game)
            session.write_text(
                json.dumps({"state": "stopped", "game_exe": str(game)}),
                encoding="utf-8",
            )
            self.assertIsNone(patrol.current_session_game_executable(session))

    def test_idle_state_never_touches_game_or_viewer(self) -> None:
        touched: list[str] = []
        window_patrol = patrol.BroadcastWindowPatrol(
            state_reader=lambda: "Idle",
            game_executable_reader=lambda: touched.append("game-path"),
            game_window_finder=lambda _path: touched.append("game-window"),
            topmost_reader=lambda _hwnd: touched.append("topmost-read"),
            topmost_setter=lambda _hwnd: touched.append("topmost-set"),
            viewer_reassert=lambda **_kwargs: touched.append("viewer"),
        )
        result = window_patrol.poll(viewer_hwnd=44, now=10.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.state, "Idle")
        self.assertEqual(touched, [])

    def test_streaming_repairs_game_then_places_viewer_above_it(self) -> None:
        calls: list[str] = []
        reads = iter((False, True))

        def topmost_reader(_hwnd: int) -> bool:
            calls.append("read")
            return next(reads)

        window_patrol = patrol.BroadcastWindowPatrol(
            state_reader=lambda: "Streaming",
            game_executable_reader=lambda: Path(r"G:\Game\SlayTheSpire2.exe"),
            game_window_finder=lambda _path: 101,
            topmost_reader=topmost_reader,
            topmost_setter=lambda _hwnd: calls.append("game") or True,
            viewer_reassert=lambda **_kwargs: calls.append("viewer") or True,
        )
        result = window_patrol.poll(viewer_hwnd=202, now=10.0)
        self.assertIsNotNone(result)
        self.assertTrue(result.repaired)
        self.assertTrue(result.game_topmost)
        self.assertTrue(result.viewer_topmost)
        self.assertEqual(calls, ["read", "game", "read", "viewer"])

    def test_already_topmost_game_is_reordered_once_per_minute(self) -> None:
        calls: list[str] = []
        window_patrol = patrol.BroadcastWindowPatrol(
            state_reader=lambda: "Streaming",
            game_executable_reader=lambda: Path(r"G:\Game\SlayTheSpire2.exe"),
            game_window_finder=lambda _path: 101,
            topmost_reader=lambda _hwnd: True,
            topmost_setter=lambda _hwnd: calls.append("game") or True,
            viewer_reassert=lambda **_kwargs: calls.append("viewer") or True,
        )
        first = window_patrol.poll(viewer_hwnd=202, now=10.0)
        throttled = window_patrol.poll(viewer_hwnd=202, now=69.9)
        second = window_patrol.poll(viewer_hwnd=202, now=70.0)
        self.assertIsNotNone(first)
        self.assertIsNone(throttled)
        self.assertIsNotNone(second)
        self.assertEqual(calls, ["game", "viewer", "game", "viewer"])

    def test_probe_errors_are_fail_closed_and_do_not_raise(self) -> None:
        window_patrol = patrol.BroadcastWindowPatrol(
            state_reader=lambda: (_ for _ in ()).throw(OSError("unreadable")),
        )
        result = window_patrol.poll(now=10.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.state, "Unknown")
        self.assertIn("unreadable", result.error)


if __name__ == "__main__":
    unittest.main()
