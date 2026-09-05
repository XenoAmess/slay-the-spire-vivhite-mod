"""Strict, offline media gate for the 540-second Vivhite v2 master.

The gate consumes an already decoded ffprobe JSON object (or the JSON text
itself).  It deliberately does not locate media, invoke ffprobe, or trust
render settings: only fields present in the supplied probe can satisfy the
contract.  Both ordinary ffprobe output and the project recorder's
``{"result": <ffprobe output>}`` envelope are accepted.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


EXPECTED_WIDTH = 1920
EXPECTED_HEIGHT = 1080
EXPECTED_VIDEO_CODEC = "h264"
EXPECTED_PIXEL_FORMAT = "yuv420p"
EXPECTED_FRAME_RATE = "60/1"
EXPECTED_TOTAL_FRAMES = 32_400
EXPECTED_DURATION_SECONDS = Decimal("540")
EXPECTED_AUDIO_CODEC = "aac"
EXPECTED_SAMPLE_RATE = 48_000
EXPECTED_CHANNELS = 2
EXPECTED_CHANNEL_LAYOUT = "stereo"

_ONE_FRAME_SECONDS = Decimal(1) / Decimal(60)
_INTEGER_TEXT = re.compile(r"(?:0|[1-9][0-9]*)\Z")


class MediaGateV2Error(ValueError):
    """Raised when an ffprobe payload does not prove the v2 master ABI."""


@dataclass(frozen=True, slots=True)
class MediaGateV2Report:
    """Canonical values proven by :func:`validate_media_gate_v2`."""

    video_stream_count: int
    audio_stream_count: int
    width: int
    height: int
    video_codec: str
    pixel_format: str
    r_frame_rate: str
    avg_frame_rate: str
    total_frames: int
    format_duration_seconds: float
    video_duration_seconds: float
    audio_duration_seconds: float
    video_start_time_seconds: float
    audio_start_time_seconds: float
    audio_codec: str
    sample_rate: int
    channels: int
    channel_layout: str

    @property
    def passed(self) -> bool:
        return True

    def to_mapping(self) -> dict[str, object]:
        return {
            "kind": "vivhite-promo-media-gate-v2",
            "passed": True,
            "video_stream_count": self.video_stream_count,
            "audio_stream_count": self.audio_stream_count,
            "width": self.width,
            "height": self.height,
            "video_codec": self.video_codec,
            "pixel_format": self.pixel_format,
            "r_frame_rate": self.r_frame_rate,
            "avg_frame_rate": self.avg_frame_rate,
            "total_frames": self.total_frames,
            "format_duration_seconds": self.format_duration_seconds,
            "video_duration_seconds": self.video_duration_seconds,
            "audio_duration_seconds": self.audio_duration_seconds,
            "video_start_time_seconds": self.video_start_time_seconds,
            "audio_start_time_seconds": self.audio_start_time_seconds,
            "audio_codec": self.audio_codec,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "channel_layout": self.channel_layout,
        }


def _decode_probe(value: Mapping[str, Any] | str | bytes | bytearray) -> Mapping[str, Any]:
    if isinstance(value, (str, bytes, bytearray)):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MediaGateV2Error("ffprobe input is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise MediaGateV2Error("ffprobe JSON root must be an object")

    # Project-side probe records preserve the actual ffprobe response under
    # ``result``.  Reject a mixed shape rather than guessing which copy wins.
    if "result" in value:
        if "streams" in value or "format" in value:
            raise MediaGateV2Error(
                "ffprobe JSON ambiguously contains both result and root probe fields"
            )
        result = value["result"]
        if not isinstance(result, Mapping):
            raise MediaGateV2Error("ffprobe result must be an object")
        return result
    return value


def _required(mapping: Mapping[str, Any], field: str, context: str) -> Any:
    if field not in mapping or mapping[field] is None:
        raise MediaGateV2Error(f"{context}.{field} is required")
    return mapping[field]


def _text(mapping: Mapping[str, Any], field: str, context: str) -> str:
    value = _required(mapping, field, context)
    if not isinstance(value, str) or not value:
        raise MediaGateV2Error(f"{context}.{field} must be non-empty text")
    return value


def _integer(mapping: Mapping[str, Any], field: str, context: str) -> int:
    value = _required(mapping, field, context)
    if isinstance(value, bool):
        raise MediaGateV2Error(f"{context}.{field} must be an integer")
    if isinstance(value, int):
        return value
    # ffprobe emits nb_frames and sample_rate as decimal strings.  Supporting
    # that real wire shape must not make floats, signs, or whitespace valid.
    if isinstance(value, str) and _INTEGER_TEXT.fullmatch(value):
        return int(value)
    raise MediaGateV2Error(f"{context}.{field} must be an integer")


def _duration(mapping: Mapping[str, Any], field: str, context: str) -> Decimal:
    value = _required(mapping, field, context)
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise MediaGateV2Error(f"{context}.{field} must be a finite number")
    try:
        duration = Decimal(str(value))
    except InvalidOperation as exc:
        raise MediaGateV2Error(f"{context}.{field} must be a finite number") from exc
    if not duration.is_finite() or duration <= 0:
        raise MediaGateV2Error(f"{context}.{field} must be a positive finite number")
    return duration


def _start_time(mapping: Mapping[str, Any], field: str, context: str) -> Decimal:
    value = _required(mapping, field, context)
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise MediaGateV2Error(f"{context}.{field} must be a finite number")
    try:
        start_time = Decimal(str(value))
    except InvalidOperation as exc:
        raise MediaGateV2Error(f"{context}.{field} must be a finite number") from exc
    if not start_time.is_finite():
        raise MediaGateV2Error(f"{context}.{field} must be a finite number")
    if start_time < 0:
        raise MediaGateV2Error(f"{context}.{field} must not be negative")
    if start_time != 0:
        raise MediaGateV2Error(
            f"{context}.{field} is {start_time}s; v2 streams must start at 0s"
        )
    return start_time


def _require_duration(duration: Decimal, context: str) -> None:
    delta = abs(duration - EXPECTED_DURATION_SECONDS)
    # Decimal input keeps the comparison deterministic.  A minuscule epsilon
    # only absorbs the representation error from callers that decoded a JSON
    # number as binary float; it is far below one encoded frame.
    epsilon = Decimal(str(math.ulp(540.0)))
    if delta > _ONE_FRAME_SECONDS + epsilon:
        raise MediaGateV2Error(
            f"{context} duration {duration}s is more than one 60 FPS frame "
            f"from {EXPECTED_DURATION_SECONDS}s"
        )


def _require_duration_alignment(
    duration: Decimal,
    reference: Decimal,
    context: str,
    reference_context: str,
) -> None:
    epsilon = Decimal(str(math.ulp(540.0)))
    if abs(duration - reference) > _ONE_FRAME_SECONDS + epsilon:
        raise MediaGateV2Error(
            f"{context} duration {duration}s is more than one 60 FPS frame "
            f"from {reference_context} duration {reference}s"
        )


def validate_media_gate_v2(
    probe: Mapping[str, Any] | str | bytes | bytearray,
) -> MediaGateV2Report:
    """Validate one ffprobe payload and return its canonical proof record.

    Failure is fail-closed: missing fields, malformed stream rows, and values
    ffprobe reports as ``N/A`` all raise :class:`MediaGateV2Error`.
    Non-audio/video streams may coexist with the required pair; a second
    audio or video stream is always rejected.
    """

    root = _decode_probe(probe)
    streams = _required(root, "streams", "ffprobe")
    if not isinstance(streams, list):
        raise MediaGateV2Error("ffprobe.streams must be an array")

    videos: list[Mapping[str, Any]] = []
    audios: list[Mapping[str, Any]] = []
    for index, stream in enumerate(streams):
        context = f"ffprobe.streams[{index}]"
        if not isinstance(stream, Mapping):
            raise MediaGateV2Error(f"{context} must be an object")
        codec_type = _text(stream, "codec_type", context)
        if codec_type == "video":
            videos.append(stream)
        elif codec_type == "audio":
            audios.append(stream)

    if len(videos) != 1 or len(audios) != 1:
        raise MediaGateV2Error(
            "master must contain exactly one video stream and one audio stream; "
            f"found {len(videos)} video and {len(audios)} audio"
        )

    format_row = _required(root, "format", "ffprobe")
    if not isinstance(format_row, Mapping):
        raise MediaGateV2Error("ffprobe.format must be an object")

    video = videos[0]
    audio = audios[0]
    width = _integer(video, "width", "video")
    height = _integer(video, "height", "video")
    if (width, height) != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
        raise MediaGateV2Error(
            f"video dimensions are {width}x{height}; "
            f"expected {EXPECTED_WIDTH}x{EXPECTED_HEIGHT}"
        )

    video_codec = _text(video, "codec_name", "video")
    if video_codec != EXPECTED_VIDEO_CODEC:
        raise MediaGateV2Error(
            f"video.codec_name is {video_codec!r}; expected {EXPECTED_VIDEO_CODEC!r}"
        )
    pixel_format = _text(video, "pix_fmt", "video")
    if pixel_format != EXPECTED_PIXEL_FORMAT:
        raise MediaGateV2Error(
            f"video.pix_fmt is {pixel_format!r}; expected {EXPECTED_PIXEL_FORMAT!r}"
        )

    r_frame_rate = _text(video, "r_frame_rate", "video")
    avg_frame_rate = _text(video, "avg_frame_rate", "video")
    if r_frame_rate != EXPECTED_FRAME_RATE:
        raise MediaGateV2Error(
            f"video.r_frame_rate is {r_frame_rate!r}; expected {EXPECTED_FRAME_RATE!r}"
        )
    if avg_frame_rate != EXPECTED_FRAME_RATE:
        raise MediaGateV2Error(
            f"video.avg_frame_rate is {avg_frame_rate!r}; expected {EXPECTED_FRAME_RATE!r}"
        )

    total_frames = _integer(video, "nb_frames", "video")
    if total_frames != EXPECTED_TOTAL_FRAMES:
        raise MediaGateV2Error(
            f"video.nb_frames is {total_frames}; expected {EXPECTED_TOTAL_FRAMES}"
        )

    format_duration = _duration(format_row, "duration", "format")
    video_duration = _duration(video, "duration", "video")
    audio_duration = _duration(audio, "duration", "audio")
    video_start_time = _start_time(video, "start_time", "video")
    audio_start_time = _start_time(audio, "start_time", "audio")
    _require_duration(format_duration, "format")
    _require_duration(video_duration, "video")
    _require_duration(audio_duration, "audio")
    _require_duration_alignment(audio_duration, format_duration, "audio", "format")
    _require_duration_alignment(audio_duration, video_duration, "audio", "video")

    audio_codec = _text(audio, "codec_name", "audio")
    if audio_codec != EXPECTED_AUDIO_CODEC:
        raise MediaGateV2Error(
            f"audio.codec_name is {audio_codec!r}; expected {EXPECTED_AUDIO_CODEC!r}"
        )
    sample_rate = _integer(audio, "sample_rate", "audio")
    channels = _integer(audio, "channels", "audio")
    channel_layout = _text(audio, "channel_layout", "audio")
    if sample_rate != EXPECTED_SAMPLE_RATE:
        raise MediaGateV2Error(
            f"audio.sample_rate is {sample_rate}; expected {EXPECTED_SAMPLE_RATE}"
        )
    if channels != EXPECTED_CHANNELS:
        raise MediaGateV2Error(
            f"audio.channels is {channels}; expected {EXPECTED_CHANNELS}"
        )
    if channel_layout != EXPECTED_CHANNEL_LAYOUT:
        raise MediaGateV2Error(
            f"audio.channel_layout is {channel_layout!r}; "
            f"expected {EXPECTED_CHANNEL_LAYOUT!r}"
        )

    return MediaGateV2Report(
        video_stream_count=1,
        audio_stream_count=1,
        width=width,
        height=height,
        video_codec=video_codec,
        pixel_format=pixel_format,
        r_frame_rate=r_frame_rate,
        avg_frame_rate=avg_frame_rate,
        total_frames=total_frames,
        format_duration_seconds=float(format_duration),
        video_duration_seconds=float(video_duration),
        audio_duration_seconds=float(audio_duration),
        video_start_time_seconds=float(video_start_time),
        audio_start_time_seconds=float(audio_start_time),
        audio_codec=audio_codec,
        sample_rate=sample_rate,
        channels=channels,
        channel_layout=channel_layout,
    )


# Explicit aliases keep the call site readable whether it thinks in terms of
# the ffprobe document or the release gate.  All names are equally pure.
validate_ffprobe_json = validate_media_gate_v2
validate_probe = validate_media_gate_v2
enforce_media_gate_v2 = validate_media_gate_v2


__all__ = [
    "EXPECTED_WIDTH",
    "EXPECTED_HEIGHT",
    "EXPECTED_VIDEO_CODEC",
    "EXPECTED_PIXEL_FORMAT",
    "EXPECTED_FRAME_RATE",
    "EXPECTED_TOTAL_FRAMES",
    "EXPECTED_DURATION_SECONDS",
    "EXPECTED_AUDIO_CODEC",
    "EXPECTED_SAMPLE_RATE",
    "EXPECTED_CHANNELS",
    "EXPECTED_CHANNEL_LAYOUT",
    "MediaGateV2Error",
    "MediaGateV2Report",
    "validate_media_gate_v2",
    "validate_ffprobe_json",
    "validate_probe",
    "enforce_media_gate_v2",
]
