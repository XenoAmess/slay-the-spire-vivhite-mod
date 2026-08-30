from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import dashboard_launcher  # noqa: E402
import lifecycle  # noqa: E402
import review_viewer  # noqa: E402


class DashboardSourceTests(unittest.TestCase):
    def test_accepts_v1_and_preserves_last_good_on_corruption(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-dashboard-") as root:
            path = Path(root) / "live.json"
            payload = {
                "schema": review_viewer.DASHBOARD_SCHEMA,
                "seq": 1,
                "revision": 1,
                "run": {"floor": 9},
                "decision": {"decision_id": "d1"},
                "history": [],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            source = review_viewer.DashboardSource(path)
            snapshot, changed = source.poll(time.time(), force=True)
            self.assertTrue(changed)
            self.assertEqual(snapshot["run"]["floor"], 9)

            path.write_text("{broken", encoding="utf-8")
            snapshot, changed = source.poll(time.time(), force=True)
            self.assertFalse(changed)
            self.assertEqual(snapshot["decision"]["decision_id"], "d1")
            self.assertTrue(snapshot["_error"])

    def test_rejects_unknown_schema_without_inventing_values(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-dashboard-") as root:
            path = Path(root) / "live.json"
            path.write_text(json.dumps({"schema": "future/v9", "run": {},
                                        "decision": {}}), encoding="utf-8")
            source = review_viewer.DashboardSource(path)
            snapshot, changed = source.poll(time.time(), force=True)
            self.assertFalse(changed)
            self.assertNotIn("run", snapshot)
            self.assertIn("schema", snapshot["_error"])

    def test_snapshot_becomes_stale_without_discarding_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-dashboard-") as root:
            path = Path(root) / "live.json"
            payload = {"schema": review_viewer.DASHBOARD_SCHEMA, "seq": 1,
                       "run": {}, "decision": {}}
            path.write_text(json.dumps(payload), encoding="utf-8")
            source = review_viewer.DashboardSource(path)
            source.poll(time.time(), force=True)
            stale = source.snapshot(path.stat().st_mtime + review_viewer.DASHBOARD_STALE_SEC + 1)
            self.assertTrue(stale["_stale"])
            self.assertEqual(stale["schema"], review_viewer.DASHBOARD_SCHEMA)

    def test_metric_never_turns_missing_into_zero(self) -> None:
        self.assertEqual(review_viewer.Viewer._metric(None), "—")
        self.assertEqual(review_viewer.Viewer._metric(float("nan")), "—")
        self.assertEqual(review_viewer.Viewer._metric(17.625), "17.6")

    def test_review_text_is_not_a_decision_telemetry_fallback(self) -> None:
        """Only the v1 snapshot can populate the mechanical decision display."""
        with tempfile.TemporaryDirectory(prefix="ascend-dashboard-") as root:
            missing = Path(root) / "live_dashboard.session.json"
            (Path(root) / "review_live.stream").write_text(
                "模型猜测：应该打出某张牌\n", encoding="utf-8"
            )
            snapshot, _changed = review_viewer.DashboardSource(missing).poll(
                time.time(), force=True
            )
            self.assertNotIn("decision", snapshot)
            self.assertEqual(snapshot["_error"], "waiting")

    def test_dashboard_render_accepts_the_production_snapshot_shape(self) -> None:
        viewer = object.__new__(review_viewer.Viewer)
        viewer.canvas = mock.MagicMock()
        viewer.font_tiny = viewer.font_dim = viewer.font_card = viewer.font_bold = object()
        viewer.dashboard = review_viewer.Viewer._demo_dashboard()
        viewer.dashboard["run"].update({
            "profile_id": "vivhite", "profile_label": "Vivhite",
            "character_id": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
        })
        viewer.floor_stats = {
            "stale": False,
            "active_profile": "vivhite",
            "lifetime": {"runs": 5, "wins": 1, "win_rate": 0.2,
                         "mean_floor": 18.2, "best_floor": 41},
            "recent": {"count": 5, "mean_floor": 18.2, "best_floor": 41},
            "previous": {"count": 0, "mean_floor": None, "best_floor": None},
            "delta_mean": None,
            "trend": [
                {"run_number": 1, "floor": 10, "rolling_mean": 10.0},
                {"run_number": 2, "floor": 20, "rolling_mean": 15.0},
            ],
            "current": viewer.dashboard["run"],
            "profile_comparison": {"rolling_mean_ratio": 1.5},
        }
        viewer.lines = []
        viewer.model_name = "fixture-model"
        viewer.reveal = 0.0
        viewer.ended = False
        viewer._dash_dirty = True
        viewer._review_dirty = True
        viewer._decision_anim_at = time.time()
        viewer._last_dashboard_render = 0.0
        review_viewer.Viewer._render_dashboard(viewer, time.time())
        self.assertGreater(viewer.canvas.create_text.call_count, 10)
        self.assertEqual(viewer.auto_mode, "LIVE")
        texts = [call.kwargs.get("text", "")
                 for call in viewer.canvas.create_text.call_args_list]
        self.assertIn("白绮 · 历史平均", texts)
        self.assertIn("白绮/战士 ×1.50", texts)

    def test_trend_chart_marks_active_profile_and_comparison_ratio(self) -> None:
        viewer = object.__new__(review_viewer.Viewer)
        viewer.canvas = mock.MagicMock()
        viewer.font_tiny = viewer.font_dim = object()
        stats = {
            "active_profile": "vivhite",
            "lifetime": {"mean_floor": 12.0, "best_floor": 20},
            "trend": [
                {"run_number": 1, "floor": 10, "rolling_mean": 10.0},
                {"run_number": 2, "floor": 14, "rolling_mean": 12.0},
            ],
            "current": {"floor": 4, "profile_id": "vivhite"},
            "profile_comparison": {"rolling_mean_ratio": 1.375},
        }

        review_viewer.Viewer._draw_trend(viewer, stats)

        texts = [call.kwargs.get("text", "")
                 for call in viewer.canvas.create_text.call_args_list]
        self.assertIn("白绮 · FLOOR TREND · 最近 2 局", texts)
        self.assertIn("白绮/战士 ×1.38", texts)

    def test_hud_marks_active_profile(self) -> None:
        viewer = object.__new__(review_viewer.Viewer)
        viewer.canvas = mock.MagicMock()
        viewer.font_hud = viewer.font = viewer.font_tiny = viewer.font_dim = object()
        viewer.mode = "live"
        viewer.dashboard = {
            "run": {
                "run_number": 1, "floor": 4, "screen": "COMBAT",
                "profile_id": "vivhite",
                "character_id": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
            },
            "decision": {"status": "applied"},
            "connection": {"status": "connected", "message": "API 8080"},
            "_stale": False,
        }
        viewer.floor_stats = {"active_profile": "vivhite"}
        viewer.run_no = None
        viewer._manual_page = None
        viewer._view_page = "LIVE"
        viewer.interactive = False
        viewer.win_h = 760
        viewer.ended = False
        viewer.flash_until = 0.0
        viewer._volume_label = mock.Mock(return_value="")

        review_viewer.Viewer._render_hud(viewer, 100.0)

        texts = [call.kwargs.get("text", "")
                 for call in viewer.canvas.create_text.call_args_list]
        self.assertIn("AUTO/LIVE · 白绮 · #1 · F4 · COMBAT", texts)
        self.assertIn("Ctrl+Alt+F9 停止 Brain · Ctrl+Alt+F10 启动", texts)

        viewer.canvas.reset_mock()
        viewer.dashboard["connection"] = {
            "status": "paused", "message": "人工接管中"}
        review_viewer.Viewer._render_hud(viewer, 101.0)
        paused_texts = [call.kwargs.get("text", "")
                        for call in viewer.canvas.create_text.call_args_list]
        self.assertIn("HUMAN/LIVE · 白绮 · #1 · F4 · COMBAT", paused_texts)
        self.assertIn("人工接管中 · Ctrl+Alt+F10 启动 Brain", paused_texts)
        self.assertEqual(
            review_viewer.Viewer._status_color("paused"), review_viewer.GOLD)

    def test_auto_page_is_state_driven_and_never_rotates(self) -> None:
        viewer = object.__new__(review_viewer.Viewer)
        viewer.interactive = False
        viewer._manual_page = None
        viewer.dashboard = review_viewer.Viewer._demo_dashboard()
        viewer._decision_seen_at = 100.0
        self.assertEqual(viewer._select_view_mode(100.0), "LIVE")
        self.assertEqual(viewer._select_view_mode(110.0), "LIVE")

        viewer.dashboard["run"]["screen"] = "GAME_OVER"
        self.assertEqual(viewer._select_view_mode(110.0), "TREND")
        self.assertEqual(viewer._select_view_mode(500.0), "TREND")

        viewer.dashboard["run"]["screen"] = "MAIN_MENU"
        self.assertEqual(viewer._select_view_mode(110.0), "REVIEW")
        self.assertEqual(viewer._select_view_mode(500.0), "REVIEW")

        viewer.dashboard["run"]["screen"] = "COMBAT"
        self.assertEqual(viewer._select_view_mode(121.0), "REVIEW")
        self.assertEqual(viewer._select_view_mode(500.0), "REVIEW")

    def test_interactive_page_selection_overrides_auto_state(self) -> None:
        viewer = object.__new__(review_viewer.Viewer)
        viewer.interactive = True
        viewer.mode = "live"
        viewer.dashboard = review_viewer.Viewer._demo_dashboard()
        viewer._decision_seen_at = time.time()
        for page in review_viewer.VIEW_PAGES:
            viewer._manual_page = page
            self.assertEqual(viewer._select_view_mode(), page)

    def test_demo_stays_on_combined_live_until_manually_changed(self) -> None:
        viewer = object.__new__(review_viewer.Viewer)
        viewer.mode = "demo"
        viewer.interactive = True
        viewer._manual_page = None
        viewer.dashboard = review_viewer.Viewer._demo_dashboard()
        viewer._decision_seen_at = 0.0
        self.assertEqual(viewer._select_view_mode(10_000.0), "LIVE")

    def test_live_review_panel_keeps_multiple_styled_lines(self) -> None:
        viewer = object.__new__(review_viewer.Viewer)
        viewer.canvas = mock.MagicMock()
        viewer.font_tiny = viewer.font_dim = viewer.font_bold = viewer.font = object()
        viewer.model_name = "review-model"
        viewer.lines = [(f"review-line-{index}", "tool" if index == 3 else "body")
                        for index in range(8)]
        viewer.reveal = 10_000.0
        viewer._review_dirty = True
        viewer._render_review_panel(time.time(), 517, 714,
                                    title="LIVE REVIEW · 连续复盘流")
        calls = viewer.canvas.create_text.call_args_list
        texts = [call.kwargs.get("text", "") for call in calls]
        self.assertGreaterEqual(sum(text.startswith("review-line-") for text in texts), 8)
        tool_calls = [call for call in calls
                      if call.kwargs.get("text") == "review-line-3"
                      and call.kwargs.get("fill") == review_viewer.MAGENTA]
        self.assertTrue(tool_calls)


class StatsSourceProfileTests(unittest.TestCase):
    @staticmethod
    def _source_without_worker() -> review_viewer.StatsSource:
        with mock.patch.object(review_viewer, "FloorStatsProvider", None):
            return review_viewer.StatsSource()

    def test_profile_switch_replaces_old_headline_with_safe_empty_snapshot(self) -> None:
        source = self._source_without_worker()
        source._snapshot = {
            "active_profile": "ironclad",
            "lifetime": {"runs": 1228, "mean_floor": 18.3, "best_floor": 48},
            "recent": {"count": 20, "mean_floor": 20.0, "best_floor": 33},
        }

        source.set_current({
            "run_id": "LIVE-V", "screen": "COMBAT", "profile_id": "vivhite",
            "character_id": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
        })
        snapshot, changed = source.poll()

        self.assertTrue(changed)
        self.assertEqual(snapshot["active_profile"], "vivhite")
        self.assertEqual(snapshot["lifetime"]["runs"], 0)
        self.assertIsNone(snapshot["lifetime"]["mean_floor"])
        self.assertIsNone(snapshot["lifetime"]["best_floor"])
        self.assertEqual(snapshot["recent"]["count"], 0)
        self.assertIsNone(snapshot["recent"]["mean_floor"])
        self.assertIsNone(snapshot["recent"]["best_floor"])

    def test_game_over_and_review_retain_finished_profile_until_real_switch(self) -> None:
        source = self._source_without_worker()
        source.set_current({
            "run_id": "FINISHED-V", "screen": "GAME_OVER",
            "profile_id": "vivhite",
            "character_id": "VIVHITE_CHARACTER_VIVHITE_CHARACTER",
        })
        self.assertEqual(source._current["profile_id"], "vivhite")

        source.set_current({"screen": "MAIN_MENU"})
        self.assertEqual(source._current["profile_id"], "vivhite")

        source.set_current({
            "run_id": "LIVE-I", "screen": "COMBAT",
            "profile_id": "ironclad", "character_id": "IRONCLAD",
        })
        self.assertEqual(source._current["profile_id"], "ironclad")
        snapshot, _changed = source.poll()
        self.assertEqual(snapshot["active_profile"], "ironclad")


class ViewerSingletonTests(unittest.TestCase):
    @staticmethod
    def _kernel(*, handle: int = 4242, last_error: int = 0):
        kernel = mock.Mock()
        kernel.CreateMutexW.return_value = handle
        kernel.GetLastError.return_value = last_error
        return kernel

    def setUp(self) -> None:
        review_viewer._viewer_mutex_handle = None

    def tearDown(self) -> None:
        # Every successful-owner test releases explicitly.  Resetting here also
        # keeps a failed assertion from leaking fake state into later cases.
        review_viewer._viewer_mutex_handle = None

    def test_named_mutex_rejects_viewer_from_another_repository_copy(self) -> None:
        kernel = self._kernel(last_error=review_viewer._ERROR_ALREADY_EXISTS)
        with mock.patch.object(review_viewer.os, "name", "nt"), \
                mock.patch.object(review_viewer.ctypes, "windll", create=True) as windll:
            windll.kernel32 = kernel
            self.assertFalse(review_viewer._acquire_viewer_mutex())
        kernel.SetLastError.assert_called_once_with(0)
        kernel.CreateMutexW.assert_called_once_with(
            None, False, review_viewer._VIEWER_MUTEX_NAME)
        kernel.CloseHandle.assert_called_once_with(4242)
        self.assertIsNone(review_viewer._viewer_mutex_handle)

    def test_named_mutex_handle_lives_until_viewer_lock_release(self) -> None:
        kernel = self._kernel(handle=7331)
        with mock.patch.object(review_viewer.os, "name", "nt"), \
                mock.patch.object(review_viewer.ctypes, "windll", create=True) as windll:
            windll.kernel32 = kernel
            self.assertTrue(review_viewer._acquire_viewer_mutex())
            self.assertEqual(review_viewer._viewer_mutex_handle, 7331)
            review_viewer._release_viewer_mutex()
        self.assertIsNone(review_viewer._viewer_mutex_handle)
        closed = kernel.CloseHandle.call_args.args[0]
        self.assertEqual(closed.value, 7331)

    def test_fresh_local_heartbeat_releases_newly_claimed_mutex(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-viewer-lock-") as root:
            lock = Path(root) / "viewer.lock"
            lock.write_text("123", encoding="utf-8")
            with mock.patch.object(review_viewer, "LOCK_FILE", lock), \
                    mock.patch.object(review_viewer, "_acquire_viewer_mutex",
                                      return_value=True), \
                    mock.patch.object(review_viewer, "_release_viewer_mutex") as release:
                self.assertFalse(review_viewer.acquire_lock())
        release.assert_called_once_with()

    def test_win32_mutex_error_falls_back_to_local_file_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-viewer-fallback-") as root:
            lock = Path(root) / "viewer.lock"
            kernel = self._kernel()
            kernel.CreateMutexW.side_effect = review_viewer.ctypes.ArgumentError(
                "bad CreateMutexW fixture")
            with mock.patch.object(review_viewer, "LOCK_FILE", lock), \
                    mock.patch.object(review_viewer.os, "name", "nt"), \
                    mock.patch.object(review_viewer.ctypes, "windll", create=True) as windll:
                windll.kernel32 = kernel
                self.assertTrue(review_viewer.acquire_lock())
                self.assertEqual(lock.read_text(encoding="utf-8"), str(os.getpid()))
                review_viewer.release_lock()
        self.assertFalse(lock.exists())

    def test_non_windows_keeps_file_lock_fallback(self) -> None:
        with mock.patch.object(review_viewer.os, "name", "posix"), \
                mock.patch.object(review_viewer.ctypes, "windll", create=True) as windll:
            self.assertTrue(review_viewer._acquire_viewer_mutex())
        self.assertFalse(windll.kernel32.called)


class DashboardLauncherTests(unittest.TestCase):
    def test_runtime_dir_canonicalizes_copied_stack_root(self) -> None:
        copied = Path("D:/backup/repo/sts2-ascend")
        runtime = Path("D:/workspace/live/sts2-ascend/.runtime")
        resolved = lifecycle.resolve_stack_root(
            copied, {"STS2_ASCEND_RUNTIME_DIR": str(runtime)})
        self.assertEqual(resolved, runtime.resolve().parent)

    def test_review_process_tree_cannot_spawn_viewer(self) -> None:
        with mock.patch.dict(os.environ, {"STS2_ASCEND_DISABLE_VIEWER": "1"}), \
                mock.patch.object(dashboard_launcher.subprocess, "Popen") as popen:
            self.assertFalse(
                dashboard_launcher.ensure_dashboard_viewer({}, lambda _msg: None))
        popen.assert_not_called()

    def test_top_level_enabled_overrides_legacy_llm_switch(self) -> None:
        cfg = {"viewer": {"enabled": False}, "llm": {"viewer_enabled": True}}
        self.assertFalse(dashboard_launcher.resolve_viewer_config(cfg)["enabled"])
        self.assertTrue(dashboard_launcher.resolve_viewer_config(
            {"llm": {"viewer_enabled": True}})["enabled"])
        self.assertFalse(dashboard_launcher.resolve_viewer_config(
            {"viewer_enabled": False})["enabled"])

    def test_existing_viewer_is_not_spawned_again(self) -> None:
        with mock.patch.object(dashboard_launcher, "viewer_is_running", return_value=True), \
                mock.patch.object(dashboard_launcher, "stop_requested", return_value=False), \
                mock.patch.object(dashboard_launcher.subprocess, "Popen") as popen:
            self.assertTrue(dashboard_launcher.ensure_dashboard_viewer({}, lambda _msg: None))
        popen.assert_not_called()

    def test_missing_viewer_is_spawned_detached(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-launcher-") as root:
            temp = Path(root)
            viewer = temp / "review_viewer.py"
            viewer.write_text("# fixture", encoding="utf-8")
            with mock.patch.object(dashboard_launcher, "VIEWER_PATH", viewer), \
                    mock.patch.object(dashboard_launcher, "KNOWLEDGE_DIR", temp), \
                    mock.patch.object(dashboard_launcher, "viewer_is_running", return_value=False), \
                    mock.patch.object(dashboard_launcher, "stop_requested", return_value=False), \
                    mock.patch.object(dashboard_launcher.subprocess, "Popen") as popen:
                self.assertTrue(dashboard_launcher.ensure_dashboard_viewer({}, lambda _msg: None))
            args = popen.call_args.args[0]
            self.assertEqual(Path(args[-1]), viewer)
            self.assertIn("-u", args)


if __name__ == "__main__":
    unittest.main()
