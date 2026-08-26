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
        viewer.floor_stats = {
            "stale": False,
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


class DashboardLauncherTests(unittest.TestCase):
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
