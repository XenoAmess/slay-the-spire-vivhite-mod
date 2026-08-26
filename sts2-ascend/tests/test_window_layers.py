"""Unit coverage for the non-activating ASCEND-VISION z-order helpers."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import review_viewer  # noqa: E402
import window_layers  # noqa: E402


class WindowLayerTests(unittest.TestCase):
    def test_missing_or_invalid_viewer_lock_is_safe(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-viewer-lock-") as root:
            lock = Path(root) / "viewer.lock"
            self.assertIsNone(window_layers.find_viewer_hwnd(lock))
            lock.write_text("not-a-pid", encoding="utf-8")
            self.assertIsNone(window_layers.find_viewer_hwnd(lock))

    def test_reassert_resolves_viewer_once_without_activation(self) -> None:
        with mock.patch.object(window_layers, "find_viewer_hwnd", return_value=4242) as find, \
                mock.patch.object(window_layers, "set_topmost_no_activate", return_value=True) as set_pos:
            self.assertTrue(window_layers.reassert_viewer_topmost())
        find.assert_called_once_with(None)
        set_pos.assert_called_once_with(4242)

    def test_reassert_accepts_known_hwnd_without_resolving_lock(self) -> None:
        with mock.patch.object(window_layers, "find_viewer_hwnd") as find, \
                mock.patch.object(window_layers, "set_topmost_no_activate", return_value=True) as set_pos:
            self.assertTrue(window_layers.reassert_viewer_topmost(hwnd=4242))
        find.assert_not_called()
        set_pos.assert_called_once_with(4242)

    def test_viewer_watchdog_is_periodic_and_forceable(self) -> None:
        viewer = object.__new__(review_viewer.Viewer)
        viewer.root = SimpleNamespace(wm_frame=lambda: "0x1234")
        viewer._last_viewer_reassert = 0.0
        viewer._viewer_hwnd = 0
        with mock.patch.object(review_viewer, "reassert_viewer_topmost", return_value=True) as reassert, \
                mock.patch.object(review_viewer.time, "monotonic", side_effect=(10.0, 10.1, 10.7)):
            viewer._reassert_viewer_topmost(force=True)
            viewer._reassert_viewer_topmost()  # throttled within the 500ms interval
            viewer._reassert_viewer_topmost()  # runs again after the interval
        self.assertEqual(viewer._viewer_hwnd, 0x1234)
        self.assertEqual(reassert.call_count, 2)
        reassert.assert_any_call(hwnd=0x1234)


if __name__ == "__main__":
    unittest.main()
