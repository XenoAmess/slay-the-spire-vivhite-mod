"""Pure offline tests for the exact Vivhite v2 final-media gate."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


PROMO_ROOT = Path(__file__).resolve().parents[1]
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

from vivhite_promo.media_gate_v2 import (  # noqa: E402
    MediaGateV2Error,
    validate_media_gate_v2,
)


def valid_probe() -> dict[str, object]:
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p",
                "r_frame_rate": "60/1",
                "avg_frame_rate": "60/1",
                # ffprobe emits this field as a string for ordinary files.
                "nb_frames": "32400",
                "duration": "540.000000",
                "start_time": "0.000000",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "channel_layout": "stereo",
                "duration": "540.000000",
                "start_time": "0.000000",
            },
        ],
        "format": {"duration": "540.000000"},
    }


class MediaGateV2Tests(unittest.TestCase):
    def test_accepts_exact_probe_and_string_nb_frames(self) -> None:
        report = validate_media_gate_v2(valid_probe())
        self.assertTrue(report.passed)
        self.assertEqual(32_400, report.total_frames)
        self.assertEqual(540.0, report.format_duration_seconds)
        self.assertEqual(540.0, report.audio_duration_seconds)
        self.assertEqual(0.0, report.video_start_time_seconds)
        self.assertEqual(0.0, report.audio_start_time_seconds)
        self.assertEqual("stereo", report.channel_layout)

    def test_accepts_project_result_envelope_and_json_text(self) -> None:
        payload = json.dumps({"result": valid_probe()})
        report = validate_media_gate_v2(payload)
        self.assertEqual("60/1", report.r_frame_rate)
        self.assertEqual("60/1", report.avg_frame_rate)

    def test_rejects_extra_audio_or_video_stream(self) -> None:
        for stream_kind in ("audio", "video"):
            with self.subTest(stream_kind=stream_kind):
                probe = valid_probe()
                stream = deepcopy(probe["streams"][0 if stream_kind == "video" else 1])
                probe["streams"].append(stream)
                with self.assertRaisesRegex(MediaGateV2Error, "exactly one"):
                    validate_media_gate_v2(probe)

    def test_non_av_stream_does_not_change_exact_av_counts(self) -> None:
        probe = valid_probe()
        probe["streams"].append(
            {"index": 2, "codec_type": "subtitle", "codec_name": "ass"}
        )
        self.assertTrue(validate_media_gate_v2(probe).passed)

    def test_rejects_wrong_video_encoding_or_geometry(self) -> None:
        cases = (
            ("width", 1280),
            ("height", 720),
            ("codec_name", "hevc"),
            ("pix_fmt", "yuv444p"),
            ("r_frame_rate", "60000/1001"),
            ("avg_frame_rate", "60000/1001"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                probe = valid_probe()
                probe["streams"][0][field] = value
                with self.assertRaises(MediaGateV2Error):
                    validate_media_gate_v2(probe)

    def test_rejects_one_frame_count_drift_in_either_direction(self) -> None:
        for frames in (32_399, 32_401):
            with self.subTest(frames=frames):
                probe = valid_probe()
                probe["streams"][0]["nb_frames"] = str(frames)
                with self.assertRaisesRegex(MediaGateV2Error, "nb_frames"):
                    validate_media_gate_v2(probe)

    def test_both_format_and_video_duration_are_independently_gated(self) -> None:
        for owner, duration in (
            ("format", "540.016666"),
            ("video", "539.983334"),
        ):
            with self.subTest(owner=owner):
                probe = valid_probe()
                if owner == "format":
                    probe["format"]["duration"] = duration
                else:
                    probe["streams"][0]["duration"] = duration
                self.assertTrue(validate_media_gate_v2(probe).passed)

        for owner, duration in (
            ("format", "540.016668"),
            ("video", "539.983332"),
        ):
            with self.subTest(owner=owner, outside=True):
                probe = valid_probe()
                if owner == "format":
                    probe["format"]["duration"] = duration
                else:
                    probe["streams"][0]["duration"] = duration
                with self.assertRaisesRegex(MediaGateV2Error, owner):
                    validate_media_gate_v2(probe)

    def test_float_duration_at_one_frame_boundary_is_accepted(self) -> None:
        probe = valid_probe()
        probe["format"]["duration"] = 540.0 + (1.0 / 60.0)
        probe["streams"][0]["duration"] = 540.0 - (1.0 / 60.0)
        self.assertTrue(validate_media_gate_v2(probe).passed)

    def test_audio_duration_is_required_and_independently_gated(self) -> None:
        for value in (None, "N/A", "NaN", "1.000000", "540.016668", "539.983332"):
            with self.subTest(value=value):
                probe = valid_probe()
                if value is None:
                    del probe["streams"][1]["duration"]
                else:
                    probe["streams"][1]["duration"] = value
                with self.assertRaisesRegex(MediaGateV2Error, "audio.duration|audio duration"):
                    validate_media_gate_v2(probe)

        for duration in ("540.016666", "539.983334"):
            with self.subTest(duration=duration, boundary=True):
                probe = valid_probe()
                probe["streams"][1]["duration"] = duration
                self.assertTrue(validate_media_gate_v2(probe).passed)

    def test_audio_duration_must_align_with_format_and_video(self) -> None:
        for owner in ("format", "video"):
            with self.subTest(owner=owner):
                probe = valid_probe()
                probe["streams"][1]["duration"] = "540.016666"
                if owner == "format":
                    probe["format"]["duration"] = "539.983334"
                else:
                    probe["streams"][0]["duration"] = "539.983334"
                with self.assertRaisesRegex(MediaGateV2Error, f"from {owner} duration"):
                    validate_media_gate_v2(probe)

    def test_video_and_audio_require_explicit_zero_start_times(self) -> None:
        for stream_index, stream_name in ((0, "video"), (1, "audio")):
            for value in (None, "N/A", "NaN", "-0.000001", "0.000001", "1.000000"):
                with self.subTest(stream=stream_name, value=value):
                    probe = valid_probe()
                    if value is None:
                        del probe["streams"][stream_index]["start_time"]
                    else:
                        probe["streams"][stream_index]["start_time"] = value
                    with self.assertRaisesRegex(
                        MediaGateV2Error, f"{stream_name}.start_time"
                    ):
                        validate_media_gate_v2(probe)

    def test_audio_contract_requires_explicit_stereo(self) -> None:
        cases = (
            ("codec_name", "mp3"),
            ("sample_rate", "44100"),
            ("channels", 1),
            ("channel_layout", "2 channels"),
            ("channel_layout", ""),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                probe = valid_probe()
                probe["streams"][1][field] = value
                with self.assertRaises(MediaGateV2Error):
                    validate_media_gate_v2(probe)

        probe = valid_probe()
        del probe["streams"][1]["channel_layout"]
        with self.assertRaisesRegex(MediaGateV2Error, "channel_layout.*required"):
            validate_media_gate_v2(probe)

    def test_every_required_media_field_fails_closed_when_missing(self) -> None:
        video_fields = (
            "codec_type",
            "codec_name",
            "width",
            "height",
            "pix_fmt",
            "r_frame_rate",
            "avg_frame_rate",
            "nb_frames",
            "duration",
            "start_time",
        )
        for field in video_fields:
            with self.subTest(section="video", field=field):
                probe = valid_probe()
                del probe["streams"][0][field]
                with self.assertRaises(MediaGateV2Error):
                    validate_media_gate_v2(probe)

        for field in (
            "codec_type",
            "codec_name",
            "sample_rate",
            "channels",
            "channel_layout",
            "duration",
            "start_time",
        ):
            with self.subTest(section="audio", field=field):
                probe = valid_probe()
                del probe["streams"][1][field]
                with self.assertRaises(MediaGateV2Error):
                    validate_media_gate_v2(probe)

        probe = valid_probe()
        del probe["format"]["duration"]
        with self.assertRaisesRegex(MediaGateV2Error, "format.duration.*required"):
            validate_media_gate_v2(probe)

    def test_malformed_or_ambiguous_probe_shape_is_rejected(self) -> None:
        bad_values = (
            None,
            [],
            {"result": None},
            {"streams": {}, "format": {"duration": "540"}},
            {"result": valid_probe(), **valid_probe()},
        )
        for value in bad_values:
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(MediaGateV2Error):
                    validate_media_gate_v2(value)


if __name__ == "__main__":
    unittest.main()
