"""Production renderer adapter for the Vivhite director-v2 multi-take edit.

This is a project-side adapter around xAR 0.2.1 and FFmpeg.  It accepts only
the byte/probe/evidence verified EDL emitted by ``production_binder_v2``;
planning storyboards and declaration-only EDLs are intentionally rejected.

The module keeps three boundaries explicit:

* every gameplay segment reads its own independent take and source window;
* every generated card is materialized through the existing xAR
  :class:`~xar_promo.visuals.TitleCardSpec` public API;
* every spoken cue has one hash-bound narration asset on an absolute edit
  timeline, so a J-cut may begin before its associated visual segment.

No BGM input exists in the accepted schemas or generated FFmpeg plan.  A
dry-run returns the complete immutable command plan without creating media or
starting an encoder.  Execution uses a fresh output directory and retains a
partial file and xAR process audit if FFmpeg fails.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = 2
EDL_KIND = "vivhite_promo_multi_take_edl_v2"
VARIANT_RECIPE_KIND = "vivhite_promo_variant_recipe_v2"
NARRATION_MANIFEST_KIND = "vivhite_promo_narration_manifest_v2"
TITLE_RESOURCE_MANIFEST_KIND = "vivhite_promo_title_resources_v2"
TITLE_ASSET_MANIFEST_SCHEMA = "vivhite-promo-title-card-assets-v2"
RENDER_PLAN_KIND = "vivhite_promo_render_plan_v2"

WIDTH = 1920
HEIGHT = 1080
FPS = 60
SAMPLE_RATE = 48_000
CHANNELS = 2
VOICE = "zh-CN-XiaoxiaoNeural"
VIDEO_CODEC = "libx264"
PIXEL_FORMAT = "yuv420p"
AUDIO_CODEC = "aac"
TARGET_DURATIONS = frozenset({540.0, 60.0, 30.0, 15.0})
SHORT_VARIANTS = {"hero-60": 60.0, "cut-30": 30.0, "cut-15": 15.0}
TITLE_TYPES = frozenset({"title_card", "tower_title_card", "end_card"})
CAPTURE_TYPES = frozenset({"mechanism_action", "gameplay", "ui_gameplay", "montage"})

_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_EPSILON = 1e-6
_ONE_FRAME = 1.0 / FPS
_FORBIDDEN_SOURCE_TOKENS = (
    "signed-master",
    "master-540.mp4",
    "delivery-a4",
    "full-master-tts-a4",
)


class RenderV2Error(ValueError):
    """A director-v2 render input or plan is unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class BoundFile:
    path: Path
    bytes: int
    sha256: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "path": self.path.as_posix(),
            "bytes": self.bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class NarrationAsset:
    cue_id: str
    file: BoundFile
    duration_seconds: float

    def to_mapping(self) -> dict[str, object]:
        return {
            "cue_id": self.cue_id,
            "file": self.file.to_mapping(),
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True, slots=True)
class RenderPlanV2:
    payload: Mapping[str, Any]

    @property
    def argv(self) -> tuple[str, ...]:
        return tuple(str(value) for value in self.payload["argv"])

    @property
    def output_root(self) -> Path:
        return Path(str(self.payload["output_root"]))

    @property
    def final_path(self) -> Path:
        return Path(str(self.payload["final_path"]))

    @property
    def partial_path(self) -> Path:
        return Path(str(self.payload["partial_path"]))

    def to_mapping(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self.payload))


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RenderV2Error(f"{context} must be an object")
    return value


def _rows(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise RenderV2Error(f"{context} must be an array")
    return value


def _text(value: Any, context: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value or value != value.strip():
        raise RenderV2Error(f"{context} must be trimmed NUL-free text")
    if not empty and not value:
        raise RenderV2Error(f"{context} must be non-empty text")
    return value


def _identifier(value: Any, context: str) -> str:
    result = _text(value, context)
    if _ID.fullmatch(result) is None:
        raise RenderV2Error(f"{context} must be a portable identifier")
    return result


def _number(value: Any, context: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RenderV2Error(f"{context} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        raise RenderV2Error(f"{context} must be finite and {'positive' if positive else 'non-negative'}")
    return result


def _integer(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RenderV2Error(f"{context} must be an integer >= {minimum}")
    return value


def _read_json(source: Mapping[str, Any] | str | Path, context: str) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return copy.deepcopy(dict(source))
    path = Path(source).expanduser().resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RenderV2Error(f"could not read {context} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RenderV2Error(f"{context} root must be an object")
    return value


def _relative_path(value: Any, context: str) -> str:
    raw = _text(value, context)
    if "\\" in raw or any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw):
        raise RenderV2Error(f"{context} must use portable '/' separators")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or _DRIVE.match(raw)
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw
    ):
        raise RenderV2Error(f"{context} must be a normalized relative path")
    folded = raw.casefold()
    if any(token in folded for token in _FORBIDDEN_SOURCE_TOKENS):
        raise RenderV2Error(f"{context} references a signed or legacy master")
    return raw


def _resolve_inside(root: Path, relative: str, context: str) -> Path:
    candidate = (root / PurePosixPath(relative)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RenderV2Error(f"{context} escapes artifact_root") from exc
    return candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _bound_file(
    value: Mapping[str, Any],
    *,
    artifact_root: Path,
    context: str,
    verify_bytes: bool = True,
) -> BoundFile:
    relative = _relative_path(value.get("path"), f"{context}.path")
    expected_bytes = _integer(value.get("bytes"), f"{context}.bytes", minimum=1)
    expected_sha = _text(value.get("sha256"), f"{context}.sha256").upper()
    if _SHA256.fullmatch(expected_sha) is None:
        raise RenderV2Error(f"{context}.sha256 must be a SHA-256 digest")
    path = _resolve_inside(artifact_root, relative, context)
    if verify_bytes:
        if not path.is_file() or path.is_symlink():
            raise RenderV2Error(f"{context} is missing or linked: {path}")
        stat = path.stat()
        if stat.st_size != expected_bytes:
            raise RenderV2Error(f"{context} byte count changed: {path}")
        if _sha256_file(path) != expected_sha:
            raise RenderV2Error(f"{context} SHA-256 changed: {path}")
    return BoundFile(path, expected_bytes, expected_sha)


def _timeline(value: Any, context: str) -> tuple[float, float, float]:
    row = _mapping(value, context)
    start = _number(row.get("start_seconds"), f"{context}.start_seconds")
    end = _number(row.get("end_seconds"), f"{context}.end_seconds")
    duration = _number(row.get("duration_seconds"), f"{context}.duration_seconds", positive=True)
    if end <= start or not math.isclose(end - start, duration, abs_tol=_EPSILON, rel_tol=0.0):
        raise RenderV2Error(f"{context} bounds and duration disagree")
    for label, seconds in (("start", start), ("end", end), ("duration", duration)):
        if not math.isclose(seconds * FPS, round(seconds * FPS), abs_tol=_EPSILON, rel_tol=0.0):
            raise RenderV2Error(f"{context}.{label} must land on a 60 FPS frame")
    return start, end, duration


def _validate_probe(value: Any, *, source_end: float, context: str) -> dict[str, Any]:
    probe = _mapping(value, f"{context}.probe")
    duration = _number(probe.get("duration_seconds"), f"{context}.probe.duration_seconds", positive=True)
    width = _integer(probe.get("width"), f"{context}.probe.width", minimum=1)
    height = _integer(probe.get("height"), f"{context}.probe.height", minimum=1)
    fps = _number(probe.get("fps"), f"{context}.probe.fps", positive=True)
    frame_count = _integer(probe.get("frame_count"), f"{context}.probe.frame_count", minimum=1)
    if probe.get("has_audio") is not True:
        raise RenderV2Error(f"{context}.probe.has_audio must be true")
    sample_rate = _integer(
        probe.get("audio_sample_rate_hz"),
        f"{context}.probe.audio_sample_rate_hz",
        minimum=1,
    )
    channels = _integer(probe.get("audio_channels"), f"{context}.probe.audio_channels", minimum=1)
    if source_end > duration + _ONE_FRAME:
        raise RenderV2Error(f"{context} source window exceeds probed take duration")
    if abs(frame_count / fps - duration) > max(_ONE_FRAME, 2.0 / fps):
        raise RenderV2Error(f"{context}.probe frame_count/fps disagrees with duration")
    return {
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "frame_count": frame_count,
        "has_audio": True,
        "audio_sample_rate_hz": sample_rate,
        "audio_channels": channels,
    }


def validate_production_edl_v2(
    source: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Validate a binder-produced master or independent short-form EDL."""

    edl = _read_json(source, "production EDL")
    if edl.get("schema_version") != SCHEMA_VERSION or edl.get("kind") != EDL_KIND:
        raise RenderV2Error(f"EDL must declare {EDL_KIND} schema_version 2")
    _identifier(edl.get("edit_id"), "edl.edit_id")
    _identifier(edl.get("take_batch_id"), "edl.take_batch_id")
    if edl.get("from_signed_master") is not False:
        raise RenderV2Error("EDL must declare from_signed_master=false")
    target = _number(edl.get("target_duration_seconds"), "edl.target_duration_seconds", positive=True)
    if not any(math.isclose(target, item, abs_tol=_EPSILON, rel_tol=0.0) for item in TARGET_DURATIONS):
        raise RenderV2Error("EDL duration must be exactly 540, 60, 30, or 15 seconds")
    canvas = _mapping(edl.get("canvas"), "edl.canvas")
    if canvas.get("width") != WIDTH or canvas.get("height") != HEIGHT or canvas.get("fps") != FPS:
        raise RenderV2Error("EDL canvas must be 1920x1080 at 60 FPS")
    audio = _mapping(edl.get("audio"), "edl.audio")
    if (
        audio.get("bgm") is not False
        or audio.get("narration_voice") != VOICE
        or audio.get("sample_rate_hz") != SAMPLE_RATE
        or audio.get("channels") != CHANNELS
    ):
        raise RenderV2Error("EDL audio must be no-BGM, Xiaoxiao, 48 kHz stereo")
    authoring = _mapping(edl.get("authoring"), "edl.authoring")
    expected_authoring = {
        "status": "production_verified",
        "offline_only": False,
        "source_verification": "bytes_sha256_ffprobe_verified",
        "action_evidence_verification": "path_loaded_and_hash_bound",
        "production_file_verification_required": False,
    }
    for key, expected in expected_authoring.items():
        if authoring.get(key) != expected:
            raise RenderV2Error(f"edl.authoring.{key} must be {expected!r}")

    segments = _rows(edl.get("segments"), "edl.segments")
    if not segments:
        raise RenderV2Error("EDL must contain segments")
    cursor = 0.0
    segment_ids: set[str] = set()
    subshot_ids: set[str] = set()
    for index, item in enumerate(segments):
        context = f"edl.segments[{index}]"
        row = _mapping(item, context)
        segment_id = _identifier(row.get("segment_id"), f"{context}.segment_id")
        subshot_id = _identifier(row.get("subshot_id"), f"{context}.subshot_id")
        if segment_id in segment_ids or subshot_id in subshot_ids:
            raise RenderV2Error("EDL segment_id and subshot_id values must be unique")
        segment_ids.add(segment_id)
        subshot_ids.add(subshot_id)
        start, end, duration = _timeline(row.get("timeline"), f"{context}.timeline")
        if not math.isclose(start, cursor, abs_tol=_EPSILON, rel_tol=0.0):
            raise RenderV2Error(f"EDL segment timeline has a gap or overlap before {segment_id}")
        cursor = end
        if not math.isclose(_number(row.get("duration_seconds"), f"{context}.duration_seconds", positive=True), duration, abs_tol=_EPSILON, rel_tol=0.0):
            raise RenderV2Error(f"{context}.duration_seconds must match timeline")
        asset_type = _text(row.get("asset_type"), f"{context}.asset_type")
        source_row = _mapping(row.get("source"), f"{context}.source")
        if asset_type in CAPTURE_TYPES:
            if source_row.get("kind") != "video_take" or source_row.get("verification") != "production_verified":
                raise RenderV2Error(f"{context} must use a production_verified video_take")
            _identifier(source_row.get("take_id"), f"{context}.source.take_id")
            _relative_path(source_row.get("path"), f"{context}.source.path")
            _integer(source_row.get("bytes"), f"{context}.source.bytes", minimum=1)
            digest = _text(source_row.get("sha256"), f"{context}.source.sha256")
            if _SHA256.fullmatch(digest) is None:
                raise RenderV2Error(f"{context}.source.sha256 is invalid")
            source_in = _number(source_row.get("in_seconds"), f"{context}.source.in_seconds")
            source_out = _number(source_row.get("out_seconds"), f"{context}.source.out_seconds")
            if source_out <= source_in or not math.isclose(source_out - source_in, duration, abs_tol=_EPSILON, rel_tol=0.0):
                raise RenderV2Error(f"{context} must retain a 1x source window")
            _validate_probe(source_row.get("probe"), source_end=source_out, context=context)
        elif asset_type in TITLE_TYPES:
            if source_row.get("kind") != "generated_title_card" or source_row.get("generator") != "xar.TitleCardSpec":
                raise RenderV2Error(f"{context} must use generated xAR TitleCardSpec")
            spec = _mapping(source_row.get("spec"), f"{context}.source.spec")
            if spec.get("factory") != "vivhite_promo.title_cards_v2.create_title_card_spec_v2":
                raise RenderV2Error(f"{context} title-card factory is invalid")
            _text(spec.get("chinese_title"), f"{context}.source.spec.chinese_title")
            _text(spec.get("english_subtitle"), f"{context}.source.spec.english_subtitle")
            if not math.isclose(_number(spec.get("duration_seconds"), f"{context}.source.spec.duration_seconds", positive=True), duration, abs_tol=_EPSILON, rel_tol=0.0):
                raise RenderV2Error(f"{context} title-card duration must match timeline")
        else:
            raise RenderV2Error(f"{context}.asset_type is unsupported")
    if not math.isclose(cursor, target, abs_tol=_EPSILON, rel_tol=0.0):
        raise RenderV2Error(f"EDL timeline must end at {target:g}s")

    cues = _rows(edl.get("cues"), "edl.cues")
    cue_ids: set[str] = set()
    previous_spoken_end = 0.0
    segment_by_id = {str(row["segment_id"]): row for row in segments}
    for index, item in enumerate(cues):
        context = f"edl.cues[{index}]"
        cue = _mapping(item, context)
        cue_id = _identifier(cue.get("cue_id"), f"{context}.cue_id")
        if cue_id in cue_ids:
            raise RenderV2Error(f"duplicate cue_id {cue_id!r}")
        cue_ids.add(cue_id)
        segment_id = _identifier(cue.get("segment_id"), f"{context}.segment_id")
        if segment_id not in segment_by_id:
            raise RenderV2Error(f"{context} references an unknown segment")
        narration = _text(cue.get("narration_zh"), f"{context}.narration_zh", empty=True)
        _text(cue.get("subtitle_zh"), f"{context}.subtitle_zh", empty=True)
        _text(cue.get("subtitle_en"), f"{context}.subtitle_en", empty=True)
        start = _number(cue.get("timeline_start_seconds"), f"{context}.timeline_start_seconds")
        if start > target + _EPSILON:
            raise RenderV2Error(f"{context} begins outside the edit")
        audio_timeline = cue.get("audio_timeline")
        jcut_value = cue.get("j_cut")
        if audio_timeline is not None:
            audio_start, audio_end, _ = _timeline(audio_timeline, f"{context}.audio_timeline")
            if audio_end > target + _EPSILON:
                raise RenderV2Error(f"{context} audio timeline exceeds the edit")
        else:
            audio_start = start
            audio_end = start
        if jcut_value is not None:
            if audio_timeline is None or not narration:
                raise RenderV2Error(f"{context} J-cut requires narrated audio_timeline")
            jcut = _mapping(jcut_value, f"{context}.j_cut")
            cut = _number(jcut.get("visual_cut_seconds"), f"{context}.j_cut.visual_cut_seconds")
            if (
                jcut.get("audio_starts_before_visual") is not True
                or jcut.get("audio_crosses_visual_cut") is not True
                or not audio_start < cut < audio_end
            ):
                raise RenderV2Error(f"{context} does not encode a real J-cut")
        if narration and audio_timeline is not None:
            if audio_start < previous_spoken_end - _EPSILON:
                raise RenderV2Error("narration audio timelines overlap")
            previous_spoken_end = audio_end
    return edl


def _source_time_mapper(
    intervals: Sequence[tuple[float, float, float]],
    value: float,
    *,
    boundary: str,
) -> float:
    candidates: list[float] = []
    for old_start, old_end, new_start in intervals:
        inside = old_start - _EPSILON <= value <= old_end + _EPSILON
        if inside:
            candidates.append(new_start + (value - old_start))
    if not candidates:
        raise RenderV2Error(f"variant cue {boundary} is outside selected source clips")
    first = candidates[0]
    if any(not math.isclose(item, first, abs_tol=_EPSILON, rel_tol=0.0) for item in candidates[1:]):
        raise RenderV2Error(f"variant cue {boundary} maps ambiguously")
    return first


def build_variant_edl_v2(
    production_master_edl: Mapping[str, Any] | str | Path,
    recipe: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Build a 60/30/15-second EDL directly from the verified take batch.

    This copies video-take bindings and generated-card specs, never media from
    the signed 540-second master.  Cue and J-cut positions are remapped from
    the selected original source-time intervals.
    """

    master = validate_production_edl_v2(production_master_edl)
    if not math.isclose(float(master["target_duration_seconds"]), 540.0, abs_tol=_EPSILON, rel_tol=0.0):
        raise RenderV2Error("variant source EDL must be the 540-second production edit")
    row = _read_json(recipe, "variant recipe")
    if row.get("schema_version") != SCHEMA_VERSION or row.get("kind") != VARIANT_RECIPE_KIND:
        raise RenderV2Error(f"variant recipe must declare {VARIANT_RECIPE_KIND} schema_version 2")
    variant_id = _identifier(row.get("variant_id"), "variant.variant_id")
    if variant_id not in SHORT_VARIANTS:
        raise RenderV2Error("variant_id must be hero-60, cut-30, or cut-15")
    target = _number(row.get("target_duration_seconds"), "variant.target_duration_seconds", positive=True)
    if not math.isclose(target, SHORT_VARIANTS[variant_id], abs_tol=_EPSILON, rel_tol=0.0):
        raise RenderV2Error(f"{variant_id} must be exactly {SHORT_VARIANTS[variant_id]:g} seconds")
    if row.get("source") != "same_v2_take_batch" or row.get("from_signed_master") is not False:
        raise RenderV2Error("variant must directly use the same v2 take batch")
    source_segments = {str(item["subshot_id"]): item for item in master["segments"]}
    source_cues = {str(item["cue_id"]): item for item in master["cues"]}
    output_segments: list[dict[str, Any]] = []
    intervals: list[tuple[float, float, float]] = []
    clip_segment_by_source: dict[str, str] = {}
    cursor = 0.0
    seen_subshots: set[str] = set()
    for index, item in enumerate(_rows(row.get("clips"), "variant.clips")):
        context = f"variant.clips[{index}]"
        clip = _mapping(item, context)
        clip_id = _identifier(clip.get("clip_id"), f"{context}.clip_id")
        source_subshot_id = _identifier(clip.get("source_subshot_id"), f"{context}.source_subshot_id")
        if source_subshot_id not in source_segments:
            raise RenderV2Error(f"{context} references unknown source subshot")
        if source_subshot_id in seen_subshots:
            raise RenderV2Error("a variant recipe cannot reuse a source subshot")
        seen_subshots.add(source_subshot_id)
        source_segment = source_segments[source_subshot_id]
        offset = _number(clip.get("in_offset_seconds", 0), f"{context}.in_offset_seconds")
        duration = _number(clip.get("duration_seconds"), f"{context}.duration_seconds", positive=True)
        source_start, _source_end, source_duration = _timeline(source_segment["timeline"], f"source {source_subshot_id}.timeline")
        if offset + duration > source_duration + _EPSILON:
            raise RenderV2Error(f"{context} exceeds source subshot duration")
        out = copy.deepcopy(source_segment)
        out["segment_id"] = f"variant-{variant_id}-{clip_id}"
        out["subshot_id"] = f"{variant_id}-{clip_id}"
        out["source_subshot_id"] = source_subshot_id
        out["timeline"] = {
            "start_seconds": cursor,
            "end_seconds": cursor + duration,
            "duration_seconds": duration,
        }
        out["duration_seconds"] = duration
        source_binding = out["source"]
        if source_binding["kind"] == "video_take":
            original_in = float(source_binding["in_seconds"])
            source_binding["in_seconds"] = original_in + offset
            source_binding["out_seconds"] = original_in + offset + duration
        else:
            source_binding["spec"]["duration_seconds"] = duration
        out["cue_id"] = None
        output_segments.append(out)
        old_clip_start = source_start + offset
        intervals.append((old_clip_start, old_clip_start + duration, cursor))
        clip_segment_by_source[source_subshot_id] = out["segment_id"]
        cursor += duration
    if not math.isclose(cursor, target, abs_tol=_EPSILON, rel_tol=0.0):
        raise RenderV2Error(f"variant clip duration is {cursor:g}s, expected {target:g}s")

    requested_cues = _rows(row.get("cue_ids", []), "variant.cue_ids")
    output_cues: list[dict[str, Any]] = []
    for index, value in enumerate(requested_cues):
        cue_id = _identifier(value, f"variant.cue_ids[{index}]")
        if cue_id not in source_cues:
            raise RenderV2Error(f"variant references unknown cue {cue_id!r}")
        cue = copy.deepcopy(source_cues[cue_id])
        source_segment = next(
            segment for segment in master["segments"] if segment["segment_id"] == cue["segment_id"]
        )
        source_subshot_id = str(source_segment["subshot_id"])
        if source_subshot_id not in clip_segment_by_source:
            raise RenderV2Error(f"variant cue {cue_id} belongs to an unselected clip")
        cue["segment_id"] = clip_segment_by_source[source_subshot_id]
        cue["timeline_start_seconds"] = _source_time_mapper(
            intervals,
            float(cue["timeline_start_seconds"]),
            boundary=f"{cue_id}.timeline_start_seconds",
        )
        if "audio_timeline" in cue:
            audio = cue["audio_timeline"]
            new_start = _source_time_mapper(intervals, float(audio["start_seconds"]), boundary=f"{cue_id}.audio_start")
            new_end = _source_time_mapper(intervals, float(audio["end_seconds"]), boundary=f"{cue_id}.audio_end")
            audio.update(
                start_seconds=new_start,
                end_seconds=new_end,
                duration_seconds=new_end - new_start,
            )
        if "j_cut" in cue:
            cue["j_cut"]["visual_cut_seconds"] = _source_time_mapper(
                intervals,
                float(cue["j_cut"]["visual_cut_seconds"]),
                boundary=f"{cue_id}.visual_cut",
            )
        output_cues.append(cue)
        for segment in output_segments:
            if segment["segment_id"] == cue["segment_id"]:
                segment["cue_id"] = cue_id
                break

    result = copy.deepcopy(master)
    result["edit_id"] = variant_id
    result["target_duration_seconds"] = target
    result["segments"] = output_segments
    result["cues"] = output_cues
    result["from_signed_master"] = False
    result["source_strategy"] = "independent_take_manifest"
    result["authoring"]["variant_id"] = variant_id
    result["authoring"]["variant_recipe"] = copy.deepcopy(row)
    result["authoring"]["same_take_batch_as_master"] = True
    validate_production_edl_v2(result)
    return result


def _validate_narration_manifest(
    source: Mapping[str, Any] | str | Path,
    *,
    artifact_root: Path,
    edl: Mapping[str, Any],
    verify_bytes: bool,
) -> dict[str, NarrationAsset]:
    manifest = _read_json(source, "narration manifest")
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("kind") != NARRATION_MANIFEST_KIND
    ):
        raise RenderV2Error(
            f"narration manifest must declare {NARRATION_MANIFEST_KIND} schema_version 2"
        )
    if manifest.get("status") != "production_verified":
        raise RenderV2Error("narration manifest is not production_verified")
    if manifest.get("voice") != VOICE or manifest.get("bgm") is not False:
        raise RenderV2Error("narration manifest must be Xiaoxiao and bgm=false")
    if manifest.get("path_base") not in {None, "run_root"}:
        raise RenderV2Error("narration manifest path_base must be run_root")
    # Narration is generated as its own immutable production run before the
    # capture batch exists.  It may therefore carry its own run id here; the
    # renderer binds it to this edit by revision plus exact cue text/hashes.
    # If a producer claims direct capture-batch identity, that identity must
    # still be exact.
    narration_batch = manifest.get("take_batch_id")
    if narration_batch != edl.get("take_batch_id"):
        if not (
            manifest.get("revision_id") == "director-v2"
            and narration_batch == manifest.get("run_id")
            and isinstance(narration_batch, str)
            and narration_batch
        ):
            raise RenderV2Error(
                "narration manifest must match the EDL batch or be an immutable director-v2 narration run"
            )

    assets: dict[str, NarrationAsset] = {}
    manifest_rows = _rows(manifest.get("cues"), "narration.cues")
    for index, item in enumerate(manifest_rows):
        context = f"narration.cues[{index}]"
        cue = _mapping(item, context)
        cue_id = _identifier(cue.get("cue_id"), f"{context}.cue_id")
        if cue_id in assets:
            raise RenderV2Error(f"narration manifest repeats cue {cue_id!r}")
        if cue.get("status") != "production_verified" or cue.get("voice") != VOICE:
            raise RenderV2Error(f"{context} is not a verified Xiaoxiao cue")
        audio_row = _mapping(cue.get("audio"), f"{context}.audio")
        binding = _bound_file(
            audio_row,
            artifact_root=artifact_root,
            context=f"{context}.audio",
            verify_bytes=verify_bytes,
        )
        duration = _number(
            audio_row.get("duration_seconds"),
            f"{context}.audio.duration_seconds",
            positive=True,
        )
        assets[cue_id] = NarrationAsset(cue_id, binding, duration)

    expected_rows = {
        str(cue["cue_id"]): cue
        for cue in edl["cues"]
        if str(cue.get("narration_zh", ""))
    }
    missing = sorted(set(expected_rows) - set(assets))
    if missing:
        raise RenderV2Error("narration manifest lacks spoken cues: " + ", ".join(missing))
    manifest_by_id = {
        str(item["cue_id"]): item
        for item in manifest_rows
        if isinstance(item, Mapping) and isinstance(item.get("cue_id"), str)
    }
    allowed_deferred_fields = {
        "initial_hp",
        "initial_gold",
        "signature_card_count",
        "runtime_version",
        "workshop_status",
    }
    for cue_id, cue in expected_rows.items():
        manifest_cue = manifest_by_id[cue_id]
        runtime_binding_value = manifest_cue.get("runtime_binding")
        if runtime_binding_value is None:
            runtime_binding = None
        else:
            runtime_binding = _mapping(
                runtime_binding_value, f"narration cue {cue_id}.runtime_binding"
            )
            deferred = {
                _identifier(value, f"narration cue {cue_id}.deferred_fields")
                for value in _rows(
                    runtime_binding.get("deferred_fields"),
                    f"narration cue {cue_id}.runtime_binding.deferred_fields",
                )
            }
            if (
                not deferred
                or not deferred.issubset(allowed_deferred_fields)
                or runtime_binding.get("status") != "pending"
                or runtime_binding.get("must_not_bake_into_tts_or_subtitle") is not True
            ):
                raise RenderV2Error(
                    f"narration cue {cue_id} runtime_binding is not a safe deferred-value contract"
                )
        for field in ("narration_zh", "subtitle_zh", "subtitle_en"):
            if manifest_cue.get(field) != cue.get(field):
                if runtime_binding is None:
                    raise RenderV2Error(
                        f"narration cue {cue_id} {field} does not match the production EDL"
                    )
                replacement = _text(
                    manifest_cue.get(field),
                    f"narration cue {cue_id}.{field}",
                    empty=field != "narration_zh",
                )
                if any(char.isdigit() for char in replacement):
                    raise RenderV2Error(
                        f"narration cue {cue_id} deferred runtime copy still bakes a numeric value"
                    )
                cue[field] = replacement
        if runtime_binding is not None:
            cue["runtime_binding"] = copy.deepcopy(dict(runtime_binding))
    return {cue_id: assets[cue_id] for cue_id in expected_rows}


def _validate_title_resources(
    source: Mapping[str, Any] | str | Path,
    *,
    artifact_root: Path,
    edl: Mapping[str, Any],
    verify_bytes: bool,
) -> dict[str, Any]:
    manifest = _read_json(source, "title resource manifest")
    if manifest.get("schema") == TITLE_ASSET_MANIFEST_SCHEMA:
        if manifest.get("status") not in {
            "rendered_pending_editorial_review",
            "production_verified",
        }:
            raise RenderV2Error("pre-rendered title-card manifest is not usable")
        renderer = _mapping(manifest.get("renderer"), "title_assets.renderer")
        canvas = _mapping(renderer.get("canvas"), "title_assets.renderer.canvas")
        if (
            renderer.get("public_api") != "xar_promo.visuals.render_title_card"
            or renderer.get("xar_version") != "0.2.1"
            or canvas.get("width") != WIDTH
            or canvas.get("height") != HEIGHT
            or canvas.get("fps") != FPS
        ):
            raise RenderV2Error("pre-rendered title cards do not prove the xAR 0.2.1 1080p60 contract")
        required = {
            str(segment.get("source_subshot_id", segment["subshot_id"])): segment
            for segment in edl["segments"]
            if segment["asset_type"] in TITLE_TYPES
        }
        cards: dict[str, Any] = {}
        for index, item in enumerate(_rows(manifest.get("title_cards"), "title_assets.title_cards")):
            context = f"title_assets.title_cards[{index}]"
            card = _mapping(item, context)
            subshot_id = _identifier(card.get("subshot_id"), f"{context}.subshot_id")
            if subshot_id in cards:
                raise RenderV2Error(f"pre-rendered title manifest repeats {subshot_id}")
            if subshot_id not in required:
                continue
            segment = required[subshot_id]
            spec = segment["source"]["spec"]
            if (
                card.get("chinese_title") != spec.get("chinese_title")
                or card.get("english_subtitle") != spec.get("english_subtitle")
            ):
                raise RenderV2Error(f"pre-rendered title copy disagrees for {subshot_id}")
            source_duration = _number(card.get("duration_seconds"), f"{context}.duration_seconds", positive=True)
            if source_duration + _EPSILON < float(segment["duration_seconds"]):
                raise RenderV2Error(f"pre-rendered title {subshot_id} is shorter than its edit segment")
            inspection = _mapping(card.get("inspection"), f"{context}.inspection")
            if (
                inspection.get("width") != WIDTH
                or inspection.get("height") != HEIGHT
                or inspection.get("mode") != "RGBA"
            ):
                raise RenderV2Error(f"pre-rendered title {subshot_id} is not 1920x1080 RGBA")
            file = _bound_file(
                _mapping(card.get("artifact"), f"{context}.artifact"),
                artifact_root=artifact_root,
                context=f"{context}.artifact",
                verify_bytes=verify_bytes,
            )
            if verify_bytes:
                width, height, color_type = _png_geometry(file.path)
                if (width, height, color_type) != (WIDTH, HEIGHT, 6):
                    raise RenderV2Error(f"pre-rendered title {subshot_id} PNG bytes are not 1920x1080 RGBA")
            cards[subshot_id] = {
                "file": file.to_mapping(),
                "duration_seconds": source_duration,
                "manifest_status": manifest["status"],
            }
        missing = sorted(set(required) - set(cards))
        if missing:
            raise RenderV2Error("pre-rendered title manifest lacks: " + ", ".join(missing))
        manifest_file = _snapshot_document_file(source, artifact_root, "title-card manifest")
        return {
            "mode": "pre_rendered_xar_title_cards",
            "manifest_status": manifest["status"],
            "manifest": None if manifest_file is None else manifest_file.to_mapping(),
            "cards": cards,
        }
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("kind") != TITLE_RESOURCE_MANIFEST_KIND
    ):
        raise RenderV2Error(
            f"title resources must declare {TITLE_RESOURCE_MANIFEST_KIND} schema_version 2"
        )
    if manifest.get("status") != "production_verified":
        raise RenderV2Error("title resources are not production_verified")
    if manifest.get("path_base") not in {None, "run_root"}:
        raise RenderV2Error("title resource path_base must be run_root")
    fonts = _mapping(manifest.get("fonts"), "title_resources.fonts")
    assets = _mapping(manifest.get("assets"), "title_resources.assets")
    required_fonts = ("vivhite_title_zh_v2", "vivhite_subtitle_en_v2")
    required_assets = ("vivhite_blue_butterfly_v2",)
    result_fonts: dict[str, Any] = {}
    result_assets: dict[str, Any] = {}
    for key in required_fonts:
        row = _mapping(fonts.get(key), f"title_resources.fonts.{key}")
        file = _bound_file(
            row,
            artifact_root=artifact_root,
            context=f"title_resources.fonts.{key}",
            verify_bytes=verify_bytes,
        )
        size_px = _integer(row.get("size_px"), f"title_resources.fonts.{key}.size_px", minimum=1)
        result_fonts[key] = {"file": file.to_mapping(), "size_px": size_px}
    for key in required_assets:
        row = _mapping(assets.get(key), f"title_resources.assets.{key}")
        file = _bound_file(
            row,
            artifact_root=artifact_root,
            context=f"title_resources.assets.{key}",
            verify_bytes=verify_bytes,
        )
        result_assets[key] = {"file": file.to_mapping()}
    manifest_file = _snapshot_document_file(source, artifact_root, "title resource manifest")
    return {
        "mode": "xar_materialize",
        "manifest": None if manifest_file is None else manifest_file.to_mapping(),
        "fonts": result_fonts,
        "assets": result_assets,
    }


def _snapshot_document_file(
    source: Mapping[str, Any] | str | Path,
    artifact_root: Path,
    context: str,
) -> BoundFile | None:
    if isinstance(source, Mapping):
        return None
    path = Path(source).expanduser().resolve()
    try:
        path.relative_to(artifact_root)
    except ValueError as exc:
        raise RenderV2Error(f"{context} must be inside its declared run root") from exc
    if not path.is_file() or path.is_symlink():
        raise RenderV2Error(f"{context} is missing or linked: {path}")
    return BoundFile(path, path.stat().st_size, _sha256_file(path))


def _png_geometry(path: Path) -> tuple[int, int, int]:
    try:
        with path.open("rb") as handle:
            header = handle.read(33)
    except OSError as exc:
        raise RenderV2Error(f"could not read title-card PNG: {path}") from exc
    if len(header) < 33 or not header.startswith(b"\x89PNG\r\n\x1a\n") or header[12:16] != b"IHDR":
        raise RenderV2Error(f"title-card artifact is not a PNG: {path}")
    width, height = struct.unpack(">II", header[16:24])
    color_type = header[25]
    return width, height, color_type


def _artifact_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise RenderV2Error(f"artifact_root is missing or linked: {root}")
    return root


def _output_root(value: str | Path) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    result = raw.resolve()
    if result.exists():
        raise RenderV2Error(f"output_root already exists; attempts are append-only: {result}")
    if not result.parent.is_dir():
        raise RenderV2Error(f"output_root parent is missing: {result.parent}")
    return result


def _format_seconds(value: float) -> str:
    return f"{value:.6f}"


def _filter_escape(value: str | os.PathLike[str]) -> str:
    raw = os.fspath(value).replace("\\", "/")
    if any(char in raw for char in ("\x00", "\n", "\r")):
        raise RenderV2Error("filter path contains a control character")
    return "".join(("\\" + char) if char in "\\':,;[]" else char for char in raw)


def _ass_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100.0)))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, hundredths = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{hundredths:02d}"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ChineseUpper,Microsoft YaHei,44,&H00FFFFFF,&H00FFFFFF,&H80000000,&H90000000,0,0,0,0,100,100,0,0,1,3,1,8,120,120,54,1
Style: EnglishUpper,Arial,31,&H00D8E8FF,&H00D8E8FF,&H80000000,&H90000000,0,0,0,0,100,100,0,0,1,2,1,8,120,120,112,1
Style: MainTitle,Microsoft YaHei,82,&H00F8F1E0,&H00F8F1E0,&H900F0A2E,&H900F0A2E,1,0,0,0,100,100,1,0,1,3,1,5,180,180,100,1
Style: MainSubtitle,Microsoft YaHei,52,&H00EBBE9A,&H00EBBE9A,&H900F0A2E,&H900F0A2E,0,0,0,0,100,100,1,0,1,2,1,5,180,180,250,1
Style: Template,Microsoft YaHei,38,&H00FFFFFF,&H00FFFFFF,&H90000000,&H90000000,0,0,0,0,100,100,0,0,1,2,1,5,140,140,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _cue_audio_window(
    cue: Mapping[str, Any],
    narration: NarrationAsset,
    *,
    target: float,
) -> tuple[float, float]:
    timeline = cue.get("audio_timeline")
    if timeline is None:
        start = float(cue["timeline_start_seconds"])
        planned_end = target
    else:
        start, planned_end, _duration = _timeline(timeline, f"cue {cue['cue_id']}.audio_timeline")
    actual_end = start + narration.duration_seconds
    if actual_end > planned_end + _ONE_FRAME:
        raise RenderV2Error(
            f"narration cue {cue['cue_id']} is longer than its available audio window"
        )
    if actual_end > target + _ONE_FRAME:
        raise RenderV2Error(f"narration cue {cue['cue_id']} exceeds the edit")
    if "j_cut" in cue:
        cut = float(cue["j_cut"]["visual_cut_seconds"])
        if not start < cut < actual_end:
            raise RenderV2Error(
                f"narration cue {cue['cue_id']} no longer crosses its J-cut after probing"
            )
    return start, min(actual_end, target)


def _subtitle_and_overlay_events(
    edl: Mapping[str, Any],
    narration_assets: Mapping[str, NarrationAsset],
) -> tuple[list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    cues = {str(row["cue_id"]): row for row in edl["cues"]}
    target = float(edl["target_duration_seconds"])
    for cue_id, narration in narration_assets.items():
        cue = cues[cue_id]
        start, end = _cue_audio_window(cue, narration, target=target)
        # These visual types already contain the same title copy.
        if cue.get("kind") in {"title_card", "end_card", "main_title"}:
            continue
        for style, field in (("ChineseUpper", "subtitle_zh"), ("EnglishUpper", "subtitle_en")):
            text = str(cue.get(field, ""))
            if text:
                events.append(
                    {
                        "layer": 10 if style == "ChineseUpper" else 11,
                        "start_seconds": start,
                        "end_seconds": end,
                        "style": style,
                        "cue_id": cue_id,
                        "text": text,
                    }
                )

    for segment in edl["segments"]:
        start, end, _ = _timeline(segment["timeline"], f"segment {segment['segment_id']}.timeline")
        visual = segment.get("visual_requirements")
        if visual is not None:
            visual = _mapping(visual, f"segment {segment['segment_id']}.visual_requirements")
            title_lines = visual.get("title_lines")
            if title_lines is not None:
                lines = _rows(title_lines, f"segment {segment['segment_id']}.visual_requirements.title_lines")
                if len(lines) != 2:
                    raise RenderV2Error("main title visual_requirements.title_lines must contain two lines")
                for index, value in enumerate(lines):
                    fade = r"\fad(400,300)" if visual.get("short_fade_allowed") is True else ""
                    position = r"\pos(960,450)" if index == 0 else r"\pos(960,570)"
                    events.append(
                        {
                            "layer": 20 + index,
                            "start_seconds": start,
                            "end_seconds": end,
                            "style": "MainTitle" if index == 0 else "MainSubtitle",
                            "cue_id": str(segment.get("cue_id") or segment["segment_id"]),
                            "text": _text(value, "main title line"),
                            "effect_prefix": "{" + position + fade + "}",
                        }
                    )

    for cue in edl["cues"]:
        fields_value = cue.get("template_fields")
        if fields_value is None:
            continue
        fields = [_identifier(value, "cue.template_fields entry") for value in _rows(fields_value, "cue.template_fields")]
        values = _mapping(cue.get("template_values"), f"cue {cue['cue_id']}.template_values")
        if set(values) != set(fields):
            raise RenderV2Error(f"cue {cue['cue_id']} template_values must resolve every template field")
        labels = {
            "runtime_version": "当前本地版本",
            "workshop_status": "Workshop 状态",
            "signature_card_count": "专属卡牌",
            "initial_hp": "初始生命",
            "initial_gold": "初始金币",
        }
        pieces = [
            f"{labels.get(field, field.replace('_', ' '))}: "
            f"{_text(values[field], f'template value {field}')}"
            for field in fields
        ]
        segment = next(row for row in edl["segments"] if row["segment_id"] == cue["segment_id"])
        start, end, _ = _timeline(segment["timeline"], f"segment {segment['segment_id']}.timeline")
        events.append(
            {
                "layer": 18,
                "start_seconds": start,
                "end_seconds": end,
                "style": "Template",
                "cue_id": str(cue["cue_id"]),
                "text": " | ".join(pieces),
                "effect_prefix": r"{\an5\pos(960,720)}",
            }
        )

    events.sort(key=lambda item: (float(item["start_seconds"]), int(item["layer"]), str(item["cue_id"])))
    lines = [ASS_HEADER]
    for event in events:
        rendered_text = str(event.get("effect_prefix", "")) + _ass_escape(str(event["text"]))
        lines.append(
            "Dialogue: "
            f"{event['layer']},{_ass_time(float(event['start_seconds']))},"
            f"{_ass_time(float(event['end_seconds']))},{event['style']},"
            f"{event['cue_id']},0,0,0,,{rendered_text}\n"
        )
    return events, "".join(lines)


def _build_filtergraph(
    *,
    segments: Sequence[Mapping[str, Any]],
    narration_windows: Sequence[Mapping[str, Any]],
    ass_path: Path,
    target: float,
) -> str:
    graph: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []
    for index, segment in enumerate(segments):
        duration = float(segment["duration_seconds"])
        video = f"v{index:03d}"
        audio = f"a{index:03d}"
        video_labels.append(f"[{video}]")
        audio_labels.append(f"[{audio}]")
        graph.append(
            f"[{index}:v:0]fps={FPS},"
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
            f"trim=duration={_format_seconds(duration)},setpts=PTS-STARTPTS[{video}]"
        )
        if segment["source_kind"] == "video_take":
            graph.append(
                f"[{index}:a:0]aresample={SAMPLE_RATE}:async=0,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"atrim=duration={_format_seconds(duration)},asetpts=PTS-STARTPTS[{audio}]"
            )
        else:
            graph.append(
                f"anullsrc=r={SAMPLE_RATE}:cl=stereo,"
                f"atrim=duration={_format_seconds(duration)},asetpts=PTS-STARTPTS[{audio}]"
            )
    graph.append("".join(video_labels) + f"concat=n={len(segments)}:v=1:a=0[vcat]")
    graph.append("".join(audio_labels) + f"concat=n={len(segments)}:v=0:a=1[game0]")
    game_label = "game0"
    for index, window in enumerate(narration_windows):
        next_label = f"game{index + 1}"
        start = _format_seconds(float(window["start_seconds"]))
        end = _format_seconds(float(window["end_seconds"]))
        graph.append(
            f"[{game_label}]volume=0.50:enable='between(t,{start},{end})'[{next_label}]"
        )
        game_label = next_label
    graph.append(
        f"[{game_label}]apad,atrim=duration={_format_seconds(target)},"
        "asetpts=N/SR/TB[game]"
    )
    narration_labels: list[str] = []
    base_index = len(segments)
    for index, window in enumerate(narration_windows):
        label = f"nar{index:03d}"
        narration_labels.append(f"[{label}]")
        delay_ms = round(float(window["start_seconds"]) * 1000)
        duration = float(window["duration_seconds"])
        graph.append(
            f"[{base_index + index}:a:0]atrim=duration={_format_seconds(duration)},"
            f"asetpts=PTS-STARTPTS,aresample={SAMPLE_RATE}:async=0,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"adelay=delays={delay_ms}:all=1,apad,"
            f"atrim=duration={_format_seconds(target)}[{label}]"
        )
    if narration_labels:
        graph.append(
            "[game]" + "".join(narration_labels)
            + f"amix=inputs={len(narration_labels) + 1}:duration=first:"
            "dropout_transition=0:normalize=0,"
            f"aresample={SAMPLE_RATE}:async=0,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad,atrim=duration={_format_seconds(target)},asetpts=N/SR/TB[aout]"
        )
    else:
        graph.append("[game]anull[aout]")
    graph.append(
        f"[vcat]ass=filename='{_filter_escape(ass_path)}',format={PIXEL_FORMAT}[vout]"
    )
    return ";".join(graph)


def _validate_ffmpeg_tools(
    ffmpeg: Path,
    ffprobe: Path,
    lock_path: Path,
    *,
    verify_bytes: bool,
) -> dict[str, Any]:
    lock = _read_json(lock_path, "FFmpeg lock")
    if lock.get("kind") != "vivhite_promo_ffmpeg_lock":
        raise RenderV2Error("FFmpeg lock kind is invalid")
    install = _mapping(lock.get("windows_install"), "ffmpeg_lock.windows_install")
    expected_rows = {
        "ffmpeg": _mapping(install.get("ffmpeg"), "ffmpeg_lock.ffmpeg"),
        "ffprobe": _mapping(install.get("ffprobe"), "ffmpeg_lock.ffprobe"),
    }
    result: dict[str, Any] = {}
    for key, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        expected = expected_rows[key]
        digest = _text(expected.get("sha256"), f"ffmpeg_lock.{key}.sha256").upper()
        if _SHA256.fullmatch(digest) is None:
            raise RenderV2Error(f"ffmpeg_lock.{key}.sha256 is invalid")
        if verify_bytes:
            if not path.is_file() or path.is_symlink():
                raise RenderV2Error(f"{key} is missing or linked: {path}")
            if _sha256_file(path) != digest:
                raise RenderV2Error(f"{key} does not match the pinned FFmpeg lock")
        result[key] = {
            "path": path.as_posix(),
            "sha256": digest,
            "bytes": path.stat().st_size if verify_bytes else None,
        }
    return result


def build_render_plan_v2(
    production_edl: Mapping[str, Any] | str | Path,
    narration_manifest: Mapping[str, Any] | str | Path,
    title_resource_manifest: Mapping[str, Any] | str | Path | None,
    *,
    artifact_root: str | Path,
    narration_root: str | Path | None = None,
    title_resource_root: str | Path | None = None,
    output_root: str | Path,
    ffmpeg: str | Path = Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
    ffprobe: str | Path = Path(r"C:\ffmpeg\bin\ffprobe.exe"),
    ffmpeg_lock: str | Path | None = None,
    verify_files: bool = True,
    verify_tools: bool = True,
) -> RenderPlanV2:
    """Build an executable, shell-free FFmpeg plan without creating output.

    ``verify_files=False`` exists solely for hermetic unit tests that exercise
    schema planning.  The CLI and :func:`execute_render_plan_v2` never disable
    byte verification.
    """

    edl = validate_production_edl_v2(production_edl)
    root = _artifact_root(artifact_root)
    voice_root = root if narration_root is None else _artifact_root(narration_root)
    title_root = root if title_resource_root is None else _artifact_root(title_resource_root)
    attempt_root = _output_root(output_root)
    ffmpeg_path = Path(ffmpeg).expanduser().resolve()
    ffprobe_path = Path(ffprobe).expanduser().resolve()
    lock_path = (
        Path(ffmpeg_lock).expanduser().resolve()
        if ffmpeg_lock is not None
        else Path(__file__).resolve().parents[1] / "ffmpeg-lock.json"
    )
    tools = _validate_ffmpeg_tools(
        ffmpeg_path,
        ffprobe_path,
        lock_path,
        verify_bytes=verify_tools,
    )
    production_edl_file = _snapshot_document_file(
        production_edl,
        root,
        "production EDL",
    )
    narration_assets = _validate_narration_manifest(
        narration_manifest,
        artifact_root=voice_root,
        edl=edl,
        verify_bytes=verify_files,
    )
    narration_manifest_file = _snapshot_document_file(
        narration_manifest,
        voice_root,
        "narration manifest",
    )

    needs_titles = any(segment["asset_type"] in TITLE_TYPES for segment in edl["segments"])
    if needs_titles and title_resource_manifest is None:
        raise RenderV2Error("generated title cards require a title resource manifest")
    title_resources = (
        None
        if not needs_titles
        else _validate_title_resources(
            title_resource_manifest,  # type: ignore[arg-type]
            artifact_root=title_root,
            edl=edl,
            verify_bytes=verify_files,
        )
    )

    plan_segments: list[dict[str, Any]] = []
    title_tasks: list[dict[str, Any]] = []
    immutable: dict[str, dict[str, Any]] = {}
    if production_edl_file is not None:
        immutable[production_edl_file.path.as_posix()] = production_edl_file.to_mapping()
    if narration_manifest_file is not None:
        immutable[narration_manifest_file.path.as_posix()] = (
            narration_manifest_file.to_mapping()
        )
    for index, segment in enumerate(edl["segments"]):
        source = segment["source"]
        duration = float(segment["duration_seconds"])
        if source["kind"] == "video_take":
            file = _bound_file(
                source,
                artifact_root=root,
                context=f"segment {segment['segment_id']}.source",
                verify_bytes=verify_files,
            )
            immutable.setdefault(file.path.as_posix(), file.to_mapping())
            plan_segments.append(
                {
                    "input_index": index,
                    "segment_id": segment["segment_id"],
                    "subshot_id": segment["subshot_id"],
                    "asset_type": segment["asset_type"],
                    "source_kind": "video_take",
                    "take_id": source["take_id"],
                    "path": file.path.as_posix(),
                    "in_seconds": float(source["in_seconds"]),
                    "out_seconds": float(source["out_seconds"]),
                    "duration_seconds": duration,
                    "probe": copy.deepcopy(source["probe"]),
                }
            )
        else:
            original_subshot_id = str(segment.get("source_subshot_id", segment["subshot_id"]))
            pre_rendered = (
                title_resources is not None
                and title_resources.get("mode") == "pre_rendered_xar_title_cards"
            )
            if pre_rendered:
                title_file = title_resources["cards"][original_subshot_id]["file"]
                title_path = Path(str(title_file["path"]))
                immutable.setdefault(title_path.as_posix(), copy.deepcopy(title_file))
            else:
                title_path = attempt_root / "work" / "title-cards" / f"{segment['segment_id']}.png"
            plan_segments.append(
                {
                    "input_index": index,
                    "segment_id": segment["segment_id"],
                    "subshot_id": segment["subshot_id"],
                    "asset_type": segment["asset_type"],
                    "source_kind": (
                        "pre_rendered_title_card" if pre_rendered else "generated_title_card"
                    ),
                    "path": title_path.as_posix(),
                    "in_seconds": 0.0,
                    "out_seconds": duration,
                    "duration_seconds": duration,
                }
            )
            if not pre_rendered:
                title_tasks.append(
                    {
                        "segment_id": segment["segment_id"],
                        "output_path": title_path.as_posix(),
                        "generator": "xar.TitleCardSpec",
                        "factory": source["spec"]["factory"],
                        "spec": copy.deepcopy(source["spec"]),
                    }
                )

    cue_by_id = {str(cue["cue_id"]): cue for cue in edl["cues"]}
    narration_windows: list[dict[str, Any]] = []
    previous_end = 0.0
    for cue in edl["cues"]:
        cue_id = str(cue["cue_id"])
        if cue_id not in narration_assets:
            continue
        asset = narration_assets[cue_id]
        start, end = _cue_audio_window(
            cue,
            asset,
            target=float(edl["target_duration_seconds"]),
        )
        if start < previous_end - _EPSILON:
            raise RenderV2Error(f"spoken cue {cue_id} overlaps the previous narration cue")
        previous_end = end
        immutable.setdefault(asset.file.path.as_posix(), asset.file.to_mapping())
        narration_windows.append(
            {
                "input_index": len(plan_segments) + len(narration_windows),
                "cue_id": cue_id,
                "path": asset.file.path.as_posix(),
                "duration_seconds": asset.duration_seconds,
                "start_seconds": start,
                "end_seconds": end,
                "j_cut": copy.deepcopy(cue.get("j_cut")),
            }
        )

    if title_resources is not None:
        manifest_file = title_resources.get("manifest")
        if manifest_file is not None:
            immutable.setdefault(str(manifest_file["path"]), copy.deepcopy(manifest_file))
        if title_resources.get("mode") == "xar_materialize":
            for group in ("fonts", "assets"):
                for value in title_resources[group].values():
                    file = value["file"]
                    immutable.setdefault(str(file["path"]), copy.deepcopy(file))

    events, ass_content = _subtitle_and_overlay_events(edl, narration_assets)
    ass_path = attempt_root / "work" / "subtitles" / f"{edl['edit_id']}.bilingual.ass"
    target = float(edl["target_duration_seconds"])
    graph = _build_filtergraph(
        segments=plan_segments,
        narration_windows=narration_windows,
        ass_path=ass_path,
        target=target,
    )
    partial = attempt_root / "renders" / f"{edl['edit_id']}.partial.mp4"
    final = attempt_root / "deliverables" / f"{edl['edit_id']}.mp4"
    argv: list[str] = [
        ffmpeg_path.as_posix(),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
    ]
    for segment in plan_segments:
        if segment["source_kind"] == "video_take":
            argv.extend(
                [
                    "-ss",
                    _format_seconds(float(segment["in_seconds"])),
                    "-t",
                    _format_seconds(float(segment["duration_seconds"])),
                    "-i",
                    str(segment["path"]),
                ]
            )
        else:
            argv.extend(
                [
                    "-loop",
                    "1",
                    "-framerate",
                    str(FPS),
                    "-t",
                    _format_seconds(float(segment["duration_seconds"])),
                    "-i",
                    str(segment["path"]),
                ]
            )
    for window in narration_windows:
        argv.extend(["-i", str(window["path"])])
    argv.extend(
        [
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-t",
            _format_seconds(target),
            "-frames:v",
            str(round(target * FPS)),
            "-c:v",
            VIDEO_CODEC,
            "-preset",
            "slow",
            "-crf",
            "16",
            "-pix_fmt",
            PIXEL_FORMAT,
            "-r",
            str(FPS),
            "-fps_mode",
            "cfr",
            "-c:a",
            AUDIO_CODEC,
            "-b:a",
            "192k",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            partial.as_posix(),
        ]
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": RENDER_PLAN_KIND,
        "status": "ready_not_executed",
        "edit_id": edl["edit_id"],
        "take_batch_id": edl["take_batch_id"],
        "target_duration_seconds": target,
        "target_frames": round(target * FPS),
        "source_strategy": "independent_take_files",
        "from_signed_master": False,
        "bgm": False,
        "output_root": attempt_root.as_posix(),
        "partial_path": partial.as_posix(),
        "final_path": final.as_posix(),
        "ass_path": ass_path.as_posix(),
        "ass_content": ass_content,
        "subtitle_and_overlay_events": events,
        "segments": plan_segments,
        "narration": narration_windows,
        "title_card_tasks": title_tasks,
        "title_resources": title_resources,
        "immutable_inputs": list(immutable.values()),
        "tools": tools,
        "filtergraph": graph,
        "argv": argv,
        "production_edl": copy.deepcopy(edl),
        "execution": {
            "shell": False,
            "executor": "xar_promo.process.run_command",
            "xar_version": "0.2.1",
            "dry_run_has_started_process": False,
        },
    }
    # Retain this lookup check near plan emission: an accidentally duplicated
    # cue would otherwise reorder audio inputs without an obvious argv change.
    if len(cue_by_id) != len(edl["cues"]):
        raise RenderV2Error("EDL cue IDs are not unique")
    return RenderPlanV2(payload)


def _verify_plan_inputs(plan: Mapping[str, Any]) -> None:
    for index, item in enumerate(_rows(plan.get("immutable_inputs"), "plan.immutable_inputs")):
        row = _mapping(item, f"plan.immutable_inputs[{index}]")
        path = Path(_text(row.get("path"), f"plan.immutable_inputs[{index}].path"))
        if not path.is_file() or path.is_symlink():
            raise RenderV2Error(f"render input is missing or linked: {path}")
        if path.stat().st_size != _integer(row.get("bytes"), "render input bytes", minimum=1):
            raise RenderV2Error(f"render input byte count changed: {path}")
        if _sha256_file(path) != _text(row.get("sha256"), "render input sha256").upper():
            raise RenderV2Error(f"render input SHA-256 changed: {path}")


def _load_xar_runtime() -> tuple[Any, Any, Any, Path]:
    source_root = Path(
        os.environ.get(
            "XAR_PROMO_TOOLCHAIN_SOURCE",
            r"G:\workspace\xar_promo_toolchain-v0.2.1-tag",
        )
    ).expanduser().resolve()
    source = source_root / "src"
    if not source.is_dir():
        raise RenderV2Error(f"pinned xAR source is missing: {source}")
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    try:
        import xar_promo  # type: ignore
        from xar_promo.process import CommandSpec, run_command  # type: ignore
        from xar_promo.visuals import render_title_card  # type: ignore
    except (ImportError, ModuleNotFoundError) as exc:
        raise RenderV2Error("xAR 0.2.1 runtime is unavailable") from exc
    if getattr(xar_promo, "__version__", None) != "0.2.1":
        raise RenderV2Error("renderer requires xAR 0.2.1")
    package_file = Path(str(xar_promo.__file__)).resolve()
    try:
        package_file.relative_to(source)
    except ValueError as exc:
        raise RenderV2Error(
            f"loaded xAR does not come from the selected source tree: {package_file}"
        ) from exc
    return CommandSpec, run_command, render_title_card, source_root


def _materialize_title_cards(
    plan: Mapping[str, Any],
    *,
    render_title_card: Callable[..., bytes],
) -> list[dict[str, Any]]:
    tasks = _rows(plan.get("title_card_tasks"), "plan.title_card_tasks")
    if not tasks:
        return []
    resources = _mapping(plan.get("title_resources"), "plan.title_resources")
    fonts_spec = _mapping(resources.get("fonts"), "plan.title_resources.fonts")
    assets_spec = _mapping(resources.get("assets"), "plan.title_resources.assets")
    try:
        from PIL import Image, ImageFont
    except ImportError as exc:
        raise RenderV2Error("Pillow==12.3.0 is required to render title cards") from exc
    try:
        import PIL
        if getattr(PIL, "__version__", None) != "12.3.0":
            raise RenderV2Error("title-card rendering requires Pillow==12.3.0")
        fonts = {
            key: ImageFont.truetype(
                str(value["file"]["path"]),
                size=int(value["size_px"]),
            )
            for key, value in fonts_spec.items()
        }
        images = {
            key: Image.open(str(value["file"]["path"])).convert("RGBA")
            for key, value in assets_spec.items()
        }
    except (OSError, ValueError) as exc:
        raise RenderV2Error(f"could not load title-card resources: {exc}") from exc
    try:
        from vivhite_promo.title_cards_v2 import create_title_card_spec_v2
    except (ImportError, ModuleNotFoundError) as exc:
        raise RenderV2Error("Vivhite title-card factory is unavailable") from exc

    outputs: list[dict[str, Any]] = []
    for index, item in enumerate(tasks):
        task = _mapping(item, f"plan.title_card_tasks[{index}]")
        spec_row = _mapping(task.get("spec"), f"plan.title_card_tasks[{index}].spec")
        spec = create_title_card_spec_v2(
            str(spec_row["chinese_title"]),
            str(spec_row["english_subtitle"]),
        )
        payload = render_title_card(spec, fonts=fonts, assets=images)
        if not isinstance(payload, bytes) or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RenderV2Error("xAR title-card renderer did not return PNG bytes")
        output = Path(str(task["output_path"]))
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise RenderV2Error(f"refusing to overwrite title card: {output}") from exc
        outputs.append(
            {
                "segment_id": task["segment_id"],
                "path": output.as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest().upper(),
            }
        )
    return outputs


def _probe_json(path: Path, ffprobe: Path) -> dict[str, Any]:
    argv = [
        ffprobe.as_posix(),
        "-v",
        "error",
        "-count_frames",
        "-show_entries",
        "format=duration,size,start_time:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,pix_fmt,sample_rate,channels,channel_layout,duration,start_time,nb_frames,nb_read_frames",
        "-of",
        "json",
        path.as_posix(),
    ]
    completed = subprocess.run(
        argv,
        shell=False,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RenderV2Error(f"ffprobe failed for {path}: {completed.stderr[-1000:]}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RenderV2Error(f"ffprobe returned invalid JSON for {path}") from exc
    if not isinstance(result, dict):
        raise RenderV2Error(f"ffprobe result for {path} is not an object")
    # Some builds expose exact decoded count as nb_read_frames only.  Promote
    # it for the strict master gate without changing the captured raw result.
    normalized = copy.deepcopy(result)
    for stream in normalized.get("streams", []):
        if isinstance(stream, dict) and stream.get("codec_type") == "video":
            if stream.get("nb_frames") in {None, "N/A"} and stream.get("nb_read_frames") not in {None, "N/A"}:
                stream["nb_frames"] = stream["nb_read_frames"]
    return {"argv": argv, "result": normalized, "raw_result": result}


def _validate_short_output_probe(probe: Mapping[str, Any], *, target: float) -> dict[str, Any]:
    result = _mapping(probe.get("result"), "ffprobe.result")
    streams = _rows(result.get("streams"), "ffprobe.result.streams")
    videos = [row for row in streams if isinstance(row, Mapping) and row.get("codec_type") == "video"]
    audios = [row for row in streams if isinstance(row, Mapping) and row.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise RenderV2Error("short deliverable must contain one video and one audio stream")
    video, audio = videos[0], audios[0]
    expected_frames = round(target * FPS)
    frame_value = video.get("nb_frames", video.get("nb_read_frames"))
    try:
        observed = {
            "width": int(video.get("width")),
            "height": int(video.get("height")),
            "frames": int(frame_value),
            "sample_rate": int(audio.get("sample_rate")),
            "channels": int(audio.get("channels")),
            "duration": float(_mapping(result.get("format"), "ffprobe.result.format").get("duration")),
        }
    except (TypeError, ValueError) as exc:
        raise RenderV2Error("short deliverable probe has invalid numeric fields") from exc
    if (
        (observed["width"], observed["height"]) != (WIDTH, HEIGHT)
        or video.get("codec_name") != "h264"
        or video.get("pix_fmt") != PIXEL_FORMAT
        or str(video.get("r_frame_rate")) != "60/1"
        or str(video.get("avg_frame_rate")) != "60/1"
        or observed["frames"] != expected_frames
        or audio.get("codec_name") != AUDIO_CODEC
        or observed["sample_rate"] != SAMPLE_RATE
        or observed["channels"] != CHANNELS
        or str(audio.get("channel_layout")) != "stereo"
        or abs(observed["duration"] - target) > _ONE_FRAME + 1e-9
    ):
        raise RenderV2Error("short deliverable does not meet the 1080p60 H.264/AAC ABI")
    return observed


def execute_render_plan_v2(plan: RenderPlanV2) -> dict[str, Any]:
    """Materialize cards/subtitles, run FFmpeg once, and validate output."""

    if not isinstance(plan, RenderPlanV2):
        raise RenderV2Error("execute_render_plan_v2 requires a RenderPlanV2")
    payload = plan.to_mapping()
    if payload.get("status") != "ready_not_executed" or payload.get("bgm") is not False:
        raise RenderV2Error("render plan is not an unexecuted no-BGM plan")
    root = plan.output_root
    if root.exists():
        raise RenderV2Error(f"output_root already exists: {root}")
    _verify_plan_inputs(payload)
    CommandSpec, run_command, render_title_card, xar_root = _load_xar_runtime()
    root.mkdir(parents=False)
    (root / "work" / "subtitles").mkdir(parents=True)
    (root / "renders").mkdir()
    (root / "deliverables").mkdir()
    (root / "logs").mkdir()
    (root / "review").mkdir()
    title_outputs = _materialize_title_cards(payload, render_title_card=render_title_card)
    ass_path = Path(str(payload["ass_path"]))
    try:
        with ass_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(str(payload["ass_content"]))
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RenderV2Error(f"refusing to overwrite subtitle file: {ass_path}") from exc
    plan_record = copy.deepcopy(payload)
    plan_record["status"] = "executing"
    plan_record["execution"]["xar_source_root"] = xar_root.as_posix()
    plan_path = root / "logs" / "render-plan.json"
    with plan_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(plan_record, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    partial = plan.partial_path
    spec = CommandSpec.create(
        payload["argv"],
        label=f"render Vivhite director-v2 {payload['edit_id']}",
        partial_artifacts=(partial,),
    )
    run_command(spec, audit_directory=root / "logs" / "ffmpeg")
    if not partial.is_file() or partial.stat().st_size < 1:
        raise RenderV2Error("FFmpeg succeeded without a non-empty partial deliverable")
    final = plan.final_path
    if final.exists():
        raise RenderV2Error(f"refusing to overwrite deliverable: {final}")
    os.replace(partial, final)
    ffprobe_path = Path(str(payload["tools"]["ffprobe"]["path"]))
    output_probe = _probe_json(final, ffprobe_path)
    target = float(payload["target_duration_seconds"])
    if math.isclose(target, 540.0, abs_tol=_EPSILON, rel_tol=0.0):
        try:
            from vivhite_promo.media_gate_v2 import validate_media_gate_v2
            technical = validate_media_gate_v2(output_probe["result"]).to_mapping()
        except Exception as exc:
            raise RenderV2Error(f"540-second media gate failed: {exc}") from exc
    else:
        technical = _validate_short_output_probe(output_probe, target=target)
    _verify_plan_inputs(payload)
    deliverable = {
        "path": final.as_posix(),
        "bytes": final.stat().st_size,
        "sha256": _sha256_file(final),
    }
    review = {
        "schema_version": SCHEMA_VERSION,
        "kind": "vivhite_promo_render_receipt_v2",
        "status": "technically_verified",
        "edit_id": payload["edit_id"],
        "take_batch_id": payload["take_batch_id"],
        "from_signed_master": False,
        "bgm": False,
        "deliverable": deliverable,
        "technical_gate": technical,
        "ffprobe": output_probe,
        "title_cards": title_outputs,
        "subtitle_events": payload["subtitle_and_overlay_events"],
        "narration": payload["narration"],
        "render_plan": {
            "path": plan_path.as_posix(),
            "bytes": plan_path.stat().st_size,
            "sha256": _sha256_file(plan_path),
        },
        "semantic_review": "pending",
        "signoff": False,
    }
    review_path = root / "review" / "render-receipt.json"
    with review_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(review, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return review


__all__ = [
    "SCHEMA_VERSION",
    "EDL_KIND",
    "VARIANT_RECIPE_KIND",
    "NARRATION_MANIFEST_KIND",
    "TITLE_RESOURCE_MANIFEST_KIND",
    "RENDER_PLAN_KIND",
    "WIDTH",
    "HEIGHT",
    "FPS",
    "SAMPLE_RATE",
    "CHANNELS",
    "VOICE",
    "SHORT_VARIANTS",
    "RenderV2Error",
    "BoundFile",
    "NarrationAsset",
    "RenderPlanV2",
    "validate_production_edl_v2",
    "build_variant_edl_v2",
    "build_render_plan_v2",
    "execute_render_plan_v2",
]
