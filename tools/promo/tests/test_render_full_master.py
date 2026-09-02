"""Offline contract checks for the full-master project producer."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROMO_ROOT = Path(__file__).resolve().parents[1]
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

import render_full_master as master  # noqa: E402


class FullMasterEdlTests(unittest.TestCase):
    def test_deliverable_probe_enforces_master_encoding_contract(self) -> None:
        probe = {
            "result": {
                "format": {"duration": "600.0"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                        "r_frame_rate": "60/1",
                        "pix_fmt": "yuv420p",
                    },
                    {
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "48000",
                        "channels": 2,
                        "channel_layout": "stereo",
                    },
                ],
            }
        }
        master._validate_deliverable_probe(
            probe, target_duration_seconds=600.0
        )
        probe["result"]["streams"][0]["pix_fmt"] = "yuv444p"
        with self.assertRaisesRegex(master.FullMasterError, "pixel format"):
            master._validate_deliverable_probe(
                probe, target_duration_seconds=600.0
            )

    def test_generated_edl_matches_canonical_ten_shot_duration(self) -> None:
        edl = master.load_edl(None, source_start_seconds=100.0)
        self.assertEqual(master.TARGET_DURATION_SECONDS, edl.target_duration_seconds)
        self.assertEqual(
            [shot_id for shot_id, _duration in master.SHOT_DURATIONS],
            [segment.shot_id for segment in edl.segments],
        )
        self.assertAlmostEqual(600.0, sum(item.duration_seconds for item in edl.segments))
        self.assertEqual(30, len(edl.cues))
        self.assertEqual("S01-01.mp3", edl.cues[0].file_name)
        self.assertEqual("S10-03.mp3", edl.cues[-1].file_name)

    def test_explicit_edl_rejects_duration_mismatch_and_path_escape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-full-edl-") as raw:
            path = Path(raw) / "bad.json"
            base = {
                "schema_version": 1,
                "kind": "vivhite_promo_full_master_edl",
                "target_duration_seconds": 10,
                "segments": [
                    {
                        "segment_id": "seg-01",
                        "shot_id": "S01-identity",
                        "source_start_seconds": 0,
                        "duration_seconds": 10,
                    }
                ],
                "cues": [
                    {
                        "cue_id": "cue-01",
                        "segment_id": "seg-01",
                        "file": "../voice.mp3",
                        "subtitle_zh": "中文",
                        "subtitle_en": "English",
                    }
                ],
            }
            path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(master.FullMasterError, "normalized relative path"):
                master.load_edl(path)
            base["cues"][0]["file"] = "voice.mp3"
            path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
            # The segment is valid now; this assertion also verifies the
            # parser accepts a deliberately short (non-600s) test EDL.
            self.assertEqual(10.0, master.load_edl(path).target_duration_seconds)

    def test_subtitle_window_is_clipped_at_segment_boundary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-full-edl-clip-") as raw:
            path = Path(raw) / "clip.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "vivhite_promo_full_master_edl",
                        "target_duration_seconds": 2,
                        "segments": [
                            {
                                "segment_id": "seg-01",
                                "shot_id": "S01-identity",
                                "source_start_seconds": 0,
                                "duration_seconds": 2,
                            }
                        ],
                        "cues": [
                            {
                                "cue_id": "cue-01",
                                "segment_id": "seg-01",
                                "offset_seconds": 1.5,
                                "file": "voice.mp3",
                                "subtitle_zh": "中文",
                                "subtitle_en": "English",
                                "subtitle_duration_seconds": 4,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            edl = master.load_edl(path)
            events = master.write_ass(
                Path(raw) / "clip.ass", edl, narration_durations={"voice.mp3": 4.0}
            )
            # The parser intentionally accepts the editorial window; the
            # writer clips it once the audio duration is known.
            self.assertAlmostEqual(2.0, events[0]["end_seconds"])

    def test_filtergraph_is_single_pass_concat_without_padding(self) -> None:
        edl = master.FullMasterEdl(
            target_duration_seconds=4.0,
            segments=(
                master.EditSegment("a", "S01-identity", 0.0, 2.0),
                master.EditSegment("b", "S02-loadout", 2.0, 2.0),
            ),
            cues=(
                master.NarrationCue(
                    "cue", "a", 0.1, "voice.mp3", "中文", "English"
                ),
            ),
        )
        graph = master.build_filtergraph(
            edl,
            ass_path=Path(r"C:\promo\subtitles\master.ass"),
            narration_durations={"voice.mp3": 0.8},
        )
        self.assertIn("concat=n=2:v=1:a=1", graph)
        self.assertIn("[vcat]ass=filename='C\\:/promo/subtitles/master.ass'", graph)
        self.assertIn("adelay=100|100", graph)
        # A full master may shorten a source span, but it must not invent
        # frames by cloning/looping a short clip.
        self.assertNotIn("tpad=", graph)

    def test_capture_span_provenance_must_match_edit(self) -> None:
        from types import SimpleNamespace

        contract = SimpleNamespace(
            clean_spans=(
                SimpleNamespace(
                    span_id="span",
                    begin_seconds=0.0,
                    end_seconds=2.0,
                    provenance="natural",
                ),
            )
        )
        with self.assertRaisesRegex(master.FullMasterError, "provenance"):
            master._find_span(
                contract,
                master.EditSegment("seg", "S01-identity", 0.0, 1.0, "staged", "span"),
            )

    def test_ass_uses_global_segment_timeline_and_utf8(self) -> None:
        edl = master.FullMasterEdl(
            target_duration_seconds=4.0,
            segments=(
                master.EditSegment("a", "S01-identity", 0.0, 2.0),
                master.EditSegment("b", "S02-loadout", 2.0, 2.0),
            ),
            cues=(
                master.NarrationCue(
                    "cue", "b", 0.25, "voice.mp3", "白绮：测试", "Vivhite: test"
                ),
            ),
        )
        with tempfile.TemporaryDirectory(prefix="vivhite-full-ass-") as raw:
            path = Path(raw) / "master.ass"
            events = master.write_ass(
                path, edl, narration_durations={"voice.mp3": 0.75}
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("白绮：测试", text)
            self.assertIn("Vivhite: test", text)
            self.assertEqual(1, len(events))
            self.assertAlmostEqual(2.25, events[0]["start_seconds"])
            self.assertAlmostEqual(3.0, events[0]["end_seconds"])


if __name__ == "__main__":
    unittest.main()
