"""Offline contract checks for the long-form narration authoring files."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROMO_ROOT = Path(__file__).resolve().parents[1]
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

import generate_full_master_narration as producer  # noqa: E402
import build_full_master_edl as edl_builder  # noqa: E402


class FullMasterNarrationTests(unittest.TestCase):
    def test_script_is_pinned_and_has_monotonic_ten_chapter_timeline(self) -> None:
        script, rows = producer._load_script(PROMO_ROOT / "full-master-script.json")
        self.assertEqual("zh-CN-XiaoxiaoNeural", script["audio_policy"]["voice"])
        self.assertFalse(script["audio_policy"]["include_bgm"])
        self.assertEqual(10, len(script["chapters"]))
        self.assertEqual(30, len(rows))
        anchors = [float(row["anchor_seconds"]) for row in rows]
        self.assertEqual(sorted(anchors), anchors)
        self.assertEqual("S01-01", rows[0]["cue_id"])
        self.assertEqual("S10-03", rows[-1]["cue_id"])
        self.assertLess(anchors[-1], float(script["target_duration_seconds"]))
        windows = [
            (
                float(chapter["window"]["start_seconds"]),
                float(chapter["window"]["end_seconds"]),
            )
            for chapter in script["chapters"]
        ]
        self.assertEqual(
            [
                (0.0, 45.0),
                (45.0, 95.0),
                (95.0, 155.0),
                (155.0, 210.0),
                (210.0, 275.0),
                (275.0, 335.0),
                (335.0, 395.0),
                (395.0, 455.0),
                (455.0, 530.0),
                (530.0, 600.0),
            ],
            windows,
        )

    def test_every_cue_has_bilingual_text_and_evidence_mode(self) -> None:
        _script, rows = producer._load_script(PROMO_ROOT / "full-master-script.json")
        for row in rows:
            self.assertTrue(row["narration_zh"].strip())
            self.assertTrue(row["subtitle_zh"].strip())
            self.assertTrue(row["subtitle_en"].strip())
            self.assertIn(row["evidence"].get("mode"), {
                "source_verified",
                "runtime_observed_if_bound",
                "editorial",
            })

    def test_subtitle_materializer_emits_four_hashable_files(self) -> None:
        _script, rows = producer._load_script(PROMO_ROOT / "full-master-script.json")
        for row in rows:
            row["duration_seconds"] = 1.0
        import tempfile

        with tempfile.TemporaryDirectory(prefix="vivhite-full-master-subtitles-") as raw:
            report = producer._write_subtitles(Path(raw), rows)
            self.assertEqual(4, len(report["files"]))
            for item in report["files"].values():
                path = Path(raw) / str(item["path"])
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_size, item["bytes"])
                self.assertEqual(len(str(item["sha256"])), 64)
            ass = (Path(raw) / "subtitles" / "full-master.bilingual.ass").read_text(encoding="utf-8")
            self.assertIn("白绮", ass)
            self.assertIn("Vivhite", ass)

    def test_edl_builder_maps_all_cues_without_guessing_capture_start(self) -> None:
        result = edl_builder.build(edl_builder.DEFAULT_SCRIPT, 1015.25)
        self.assertEqual("vivhite_promo_full_master_edl", result["kind"])
        self.assertEqual(600, result["target_duration_seconds"])
        self.assertEqual(10, len(result["segments"]))
        self.assertEqual(30, len(result["cues"]))
        self.assertEqual(1015.25, result["segments"][0]["source_start_seconds"])
        self.assertEqual(0.0, result["cues"][0]["offset_seconds"])
        self.assertEqual("S10-03.mp3", result["cues"][-1]["file"])
        self.assertEqual(
                "run-20260902T-full-master-tts-a4/narration",
            result["authoring"]["narration_root"],
        )


if __name__ == "__main__":
    unittest.main()
