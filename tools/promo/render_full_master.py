"""Render the ten-minute Vivhite master from a hash-bound capture and EDL.

This module is a project-side producer.  It deliberately does not start OBS,
the game, OCR, TTS, or a publishing client.  The recorder writes an immutable
capture receipt first; this helper then consumes that receipt, an editorial
EDL, and already-produced narration files and emits one deterministic
1920x1080/60 H.264/AAC draft.

The short-cut producer in :mod:`render_capture_candidate` is intentionally
left unchanged.  A full master has a different input contract: it may contain
several windows from one capture, and its output timeline is assembled by the
FFmpeg ``concat`` filter in one auditable command.  No source window is padded
or looped to manufacture duration.  Every edit must fit a clean span in the
capture contract.

Example (all paths are examples; use a fresh sibling run directory)::

    python tools/promo/render_full_master.py \
      --raw runs/run-.../raw/capture.mkv \
      --capture-contract runs/run-.../capture/contract.json \
      --edl runs/run-.../notes/full-master-edl.json \
      --output-root runs/run-...-full-master-a2 \
      --narration-root runs/run-20260902T-full-master-tts-a4/narration

When ``--edl`` is omitted, ``--source-start`` creates the canonical ten-shot
600-second EDL from contiguous source windows.  This is useful for a quick
draft, but it still checks every generated window against the capture receipt.
The output is always marked ``preliminary``; semantic validators, review and
signoff remain project gates outside this renderer.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence


PROMO_ROOT = Path(__file__).resolve().parent
VOICE = "zh-CN-XiaoxiaoNeural"
FFMPEG_DEFAULT = Path(r"C:\ffmpeg\bin\ffmpeg.exe")
FFPROBE_DEFAULT = Path(r"C:\ffmpeg\bin\ffprobe.exe")
# The checked-in long-form script is paired with the a4 Xiaoxiao run.  Keep
# the default in lockstep with ``build_full_master_edl.py`` so an operator who
# omits ``--narration-root`` cannot silently pick the obsolete short-run
# assets.  Callers may still pass an explicit root for a new, hash-bound TTS
# attempt.
NARRATION_DEFAULT = PROMO_ROOT / "runs" / "run-20260902T-full-master-tts-a4" / "narration"
STORYBOARD_DEFAULT = PROMO_ROOT / "storyboard.json"
FULL_MASTER_SCRIPT_DEFAULT = PROMO_ROOT / "full-master-script.json"
TARGET_DURATION_SECONDS = 600.0
WIDTH = 1920
HEIGHT = 1080
FPS = 60
SAMPLE_RATE = 48_000
CHANNELS = 2
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"
PIXEL_FORMAT = "yuv420p"
ENCODER_PRESET = "medium"
CRF = 20

SHOT_DURATIONS: tuple[tuple[str, float], ...] = (
    ("S01-identity", 45.0),
    ("S02-loadout", 50.0),
    ("S03-cough", 60.0),
    ("S04-margin", 55.0),
    ("S05-drain", 65.0),
    ("S06-conservation-geometry", 60.0),
    ("S07-recursive-star-calculus", 60.0),
    ("S08-crimson-integral", 60.0),
    ("S09-unified-field", 75.0),
    ("S10-finale", 70.0),
)
CANONICAL_SHOT_IDS = frozenset(shot_id for shot_id, _duration in SHOT_DURATIONS)

# These are the text paired with the already-produced Xiaoxiao MP3 files.  An
# EDL may override any line (for example after a semantic audit narrows a
# claim); keeping the default here makes a first full draft reproducible and
# avoids reading the project's historical, sometimes mojibake, config text.
DEFAULT_CUE_TEXT: dict[str, tuple[str, str, str]] = {
    "S01-identity": (
        "S01-identity",
        "白绮：把数学写成魔法",
        "Vivhite: mathematics as magic",
    ),
    "S02-loadout": (
        "S02-loadout",
        "起始牌组与孤高冠冕",
        "Starter deck and Solitary Crown",
    ),
    "S03-cough": (
        "S03-cough",
        "謦欬：生命是施法成本",
        "Cough: life is the casting cost",
    ),
    "S04-margin": (
        "S04-margin",
        "余裕按一比一抵扣謦欬",
        "Margin offsets Cough one for one",
    ),
    "S05-drain": (
        "S05-drain",
        "汲取：按实际伤害统一回收",
        "Drain: recover actual damage once",
    ),
    "S06-conservation-geometry": (
        "S06-conservation-geometry",
        "守恒几何：资源可以互相证明",
        "Conservation Geometry: resources prove each other",
    ),
    "S07-recursive-star-calculus": (
        "S07-recursive-star-calculus",
        "递归星算：增长也是输入",
        "Recursive Star Calculus: growth is input",
    ),
    "S08-crimson-integral": (
        "S08-crimson-integral",
        "绯彩积分：把伤害变成循环",
        "Crimson Integral: turn damage into a loop",
    ),
    "S09-unified-field": (
        "S09-unified-field",
        "统一场论：跨体系闭环",
        "Unified Field Theory: a cross-system loop",
    ),
    "S10-finale": (
        "S10-finale",
        "白绮：61 张卡，3 套构筑",
        "Vivhite: 61 cards, 3 archetypes",
    ),
}

class FullMasterError(ValueError):
    """The EDL or its immutable inputs cannot be consumed safely."""


@dataclass(frozen=True, slots=True)
class EditSegment:
    segment_id: str
    shot_id: str
    source_start_seconds: float
    duration_seconds: float
    provenance: str = "natural"
    span_id: str | None = None

    @property
    def source_end_seconds(self) -> float:
        return self.source_start_seconds + self.duration_seconds

    def to_mapping(self, timeline_start_seconds: float) -> dict[str, Any]:
        result: dict[str, Any] = {
            "segment_id": self.segment_id,
            "shot_id": self.shot_id,
            "timeline_start_seconds": round(timeline_start_seconds, 6),
            "timeline_end_seconds": round(
                timeline_start_seconds + self.duration_seconds, 6
            ),
            "source_start_seconds": self.source_start_seconds,
            "source_end_seconds": self.source_end_seconds,
            "duration_seconds": self.duration_seconds,
            "provenance": self.provenance,
        }
        if self.span_id is not None:
            result["span_id"] = self.span_id
        return result


@dataclass(frozen=True, slots=True)
class NarrationCue:
    cue_id: str
    segment_id: str
    offset_seconds: float
    file_name: str
    zh: str
    en: str
    subtitle_duration_seconds: float | None = None

    def to_mapping(self, timeline_start_seconds: float) -> dict[str, Any]:
        result: dict[str, Any] = {
            "cue_id": self.cue_id,
            "segment_id": self.segment_id,
            "timeline_start_seconds": round(
                timeline_start_seconds + self.offset_seconds, 6
            ),
            "offset_seconds": self.offset_seconds,
            "file": self.file_name,
            "subtitle_zh": self.zh,
            "subtitle_en": self.en,
        }
        if self.subtitle_duration_seconds is not None:
            result["subtitle_duration_seconds"] = self.subtitle_duration_seconds
        return result


@dataclass(frozen=True, slots=True)
class FullMasterEdl:
    target_duration_seconds: float
    segments: tuple[EditSegment, ...]
    cues: tuple[NarrationCue, ...]
    source_label: str = "capture"

    def timeline_rows(self) -> tuple[tuple[EditSegment, float], ...]:
        cursor = 0.0
        rows: list[tuple[EditSegment, float]] = []
        for segment in self.segments:
            rows.append((segment, cursor))
            cursor += segment.duration_seconds
        return tuple(rows)

    def segment_timeline_start(self, segment_id: str) -> float:
        for segment, start in self.timeline_rows():
            if segment.segment_id == segment_id:
                return start
        raise FullMasterError(f"cue references unknown segment {segment_id!r}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise FullMasterError(f"could not hash {path}: {exc}") from exc
    return digest.hexdigest().upper()


def file_record(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise FullMasterError(f"required file is missing or unreadable: {resolved}") from exc
    result: dict[str, Any] = {
        "path": resolved.as_posix(),
        "bytes": size,
        "sha256": sha256_file(resolved),
    }
    if root is not None:
        try:
            result["relative_path"] = resolved.relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return result


def _finite(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FullMasterError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise FullMasterError(f"{label} must be finite and {qualifier}")
    return result


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise FullMasterError(f"{label} must be non-empty NUL-free text")
    return value.strip()


def _portable_id(value: Any, label: str) -> str:
    text = _text(value, label)
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for character in text):
        raise FullMasterError(f"{label} must be a portable identifier")
    return text


def _relative_file_name(value: Any, label: str) -> str:
    raw = _text(value, label)
    if "\\" in raw:
        raise FullMasterError(f"{label} must use portable '/' separators")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(":" in part for part in path.parts)
        or path.as_posix() != raw
    ):
        raise FullMasterError(f"{label} must be a normalized relative path")
    return raw


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullMasterError(f"could not read {label} {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise FullMasterError(f"{label} root must be an object")
    return value


def _default_segments(source_start_seconds: float) -> tuple[EditSegment, ...]:
    cursor = _finite(source_start_seconds, "source_start_seconds")
    result: list[EditSegment] = []
    for index, (shot_id, duration) in enumerate(SHOT_DURATIONS, 1):
        result.append(
            EditSegment(
                segment_id=f"seg-{index:02d}",
                shot_id=shot_id,
                source_start_seconds=cursor,
                duration_seconds=duration,
                provenance="natural" if shot_id not in {"S01-identity", "S10-finale"} else "staged",
            )
        )
        cursor += duration
    return tuple(result)


def _default_cues(segments: Sequence[EditSegment]) -> tuple[NarrationCue, ...]:
    result: list[NarrationCue] = []
    for segment in segments:
        text = DEFAULT_CUE_TEXT.get(segment.shot_id)
        if text is None:
            continue
        cue_id, zh, en = text
        result.append(
            NarrationCue(
                cue_id=cue_id,
                segment_id=segment.segment_id,
                offset_seconds=0.0,
                file_name=f"{segment.shot_id}.mp3",
                zh=zh,
                en=en,
            )
        )
    return tuple(result)


def load_edl(
    path: Path,
    *,
    source_start_seconds: float | None = None,
) -> FullMasterEdl:
    """Load and validate a full-master EDL without touching media."""

    if path is None:
        # Keep the command-line shortcut aligned with the checked-in
        # long-form script and its final a4 narration batch.  The historical
        # one-cue-per-shot fallback expected files such as
        # ``S01-identity.mp3`` that the long-form producer never emits, so it
        # could pass structural tests and then fail only after probing media.
        # Building the exact same in-memory payload as the standalone EDL
        # helper removes that split-brain path without creating a temporary
        # file or guessing capture timestamps.
        try:
            from build_full_master_edl import build as build_full_master_edl
        except ImportError as exc:  # pragma: no cover - installation error
            raise FullMasterError(
                "build_full_master_edl.py is required when --edl is omitted"
            ) from exc
        try:
            payload = build_full_master_edl(
                FULL_MASTER_SCRIPT_DEFAULT,
                source_start_seconds or 0.0,
                narration_root="run-20260902T-full-master-tts-a4/narration",
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FullMasterError(f"could not build canonical full-master EDL: {exc}") from exc
    else:
        payload = _read_json(path, "full-master EDL")
    if payload.get("kind") != "vivhite_promo_full_master_edl":
        raise FullMasterError("EDL kind must be vivhite_promo_full_master_edl")
    if payload.get("schema_version") != 1:
        raise FullMasterError("EDL schema_version must be 1")
    target = _finite(payload.get("target_duration_seconds"), "target_duration_seconds", positive=True)
    if target > 1200:
        raise FullMasterError("target_duration_seconds must be <= 1200")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise FullMasterError("EDL segments must be a non-empty array")
    segments: list[EditSegment] = []
    ids: set[str] = set()
    for index, row in enumerate(raw_segments):
        if not isinstance(row, Mapping):
            raise FullMasterError(f"segments[{index}] must be an object")
        segment_id = _portable_id(row.get("segment_id"), f"segments[{index}].segment_id")
        if segment_id in ids:
            raise FullMasterError(f"duplicate segment_id {segment_id!r}")
        ids.add(segment_id)
        shot_id = _text(row.get("shot_id"), f"segments[{index}].shot_id")
        if shot_id not in CANONICAL_SHOT_IDS:
            raise FullMasterError(
                f"segments[{index}].shot_id is not one of the canonical Vivhite shots"
            )
        source_start = _finite(row.get("source_start_seconds"), f"segments[{index}].source_start_seconds")
        duration = _finite(row.get("duration_seconds"), f"segments[{index}].duration_seconds", positive=True)
        provenance = _text(row.get("provenance", "natural"), f"segments[{index}].provenance")
        if provenance not in {"natural", "staged"}:
            raise FullMasterError(f"segments[{index}].provenance must be natural or staged")
        span_id_value = row.get("span_id")
        span_id = None if span_id_value is None else _portable_id(span_id_value, f"segments[{index}].span_id")
        segments.append(EditSegment(segment_id, shot_id, source_start, duration, provenance, span_id))
    total = sum(segment.duration_seconds for segment in segments)
    if not math.isclose(total, target, rel_tol=0.0, abs_tol=1e-6):
        raise FullMasterError(
            f"EDL segment durations sum to {total:g}s, not target {target:g}s"
        )
    raw_cues = payload.get("cues", [])
    if raw_cues is None:
        raw_cues = []
    if not isinstance(raw_cues, list):
        raise FullMasterError("EDL cues must be an array")
    cues: list[NarrationCue] = []
    cue_ids: set[str] = set()
    for index, row in enumerate(raw_cues):
        if not isinstance(row, Mapping):
            raise FullMasterError(f"cues[{index}] must be an object")
        cue_id = _portable_id(row.get("cue_id"), f"cues[{index}].cue_id")
        if cue_id in cue_ids:
            raise FullMasterError(f"duplicate cue_id {cue_id!r}")
        cue_ids.add(cue_id)
        segment_id = _portable_id(row.get("segment_id"), f"cues[{index}].segment_id")
        if segment_id not in ids:
            raise FullMasterError(f"cues[{index}] references unknown segment {segment_id!r}")
        offset = _finite(row.get("offset_seconds", 0.0), f"cues[{index}].offset_seconds")
        file_name = _relative_file_name(row.get("file"), f"cues[{index}].file")
        zh = _text(row.get("subtitle_zh"), f"cues[{index}].subtitle_zh")
        en = _text(row.get("subtitle_en"), f"cues[{index}].subtitle_en")
        subtitle_duration_value = row.get("subtitle_duration_seconds")
        subtitle_duration = (
            None
            if subtitle_duration_value is None
            else _finite(
                subtitle_duration_value,
                f"cues[{index}].subtitle_duration_seconds",
                positive=True,
            )
        )
        cues.append(NarrationCue(cue_id, segment_id, offset, file_name, zh, en, subtitle_duration))
    # A cue cannot begin outside its segment.  The exact audio duration is
    # checked later, after ffprobe; this structural check catches bad EDLs
    # before any external process is started.
    by_id = {segment.segment_id: segment for segment in segments}
    for cue in cues:
        segment = by_id[cue.segment_id]
        if cue.offset_seconds >= segment.duration_seconds:
            raise FullMasterError(
                f"cue {cue.cue_id!r} starts outside segment {cue.segment_id!r}"
            )
        # A subtitle window is editorial display time, not source-media time.
        # It may reach the segment boundary when a chapter was shortened; the
        # ASS writer clips it to the available interval.  The spoken audio is
        # independently clipped after ffprobe, so this remains fail-closed
        # without rejecting otherwise usable long-form cue sheets.
    return FullMasterEdl(
        target_duration_seconds=target,
        segments=tuple(segments),
        cues=tuple(cues),
        source_label=_text(payload.get("source_label", "edl"), "source_label"),
    )


def _source_run_root(raw: Path) -> Path:
    resolved = raw.resolve()
    return resolved.parent.parent if resolved.parent.name.casefold() == "raw" else resolved.parent


def validate_output_root(raw: Path, output_root: Path) -> None:
    selected = output_root.expanduser().resolve()
    source_run = _source_run_root(raw)
    try:
        selected.relative_to(source_run)
    except ValueError:
        pass
    else:
        raise FullMasterError(
            "full-master output must be a fresh sibling run, not the source run: "
            + str(selected)
        )
    if selected.exists():
        raise FileExistsError(f"refusing to reuse existing output root: {selected}")


def _infer_contract(raw: Path) -> Path:
    run_root = _source_run_root(raw)
    candidates = (
        run_root / "capture" / "contract.json",
        run_root / "contract.json",
        run_root / "partial-candidate-contract.json",
    )
    existing = tuple(path for path in candidates if path.is_file())
    if len(existing) != 1:
        if not existing:
            raise FileNotFoundError("no hash-bound capture contract found for raw media")
        raise FullMasterError(
            "multiple capture contracts found; pass --capture-contract explicitly"
        )
    return existing[0].resolve()


def _load_capture_binding(raw: Path, contract_path: Path) -> tuple[Any, dict[str, Any]]:
    """Reuse the project's strict adapter gate without importing it at module load."""

    try:
        from render_capture_candidate import load_capture_binding  # type: ignore
    except ModuleNotFoundError as exc:
        raise FullMasterError("render_capture_candidate helper is unavailable") from exc
    try:
        contract, provenance = load_capture_binding(raw, contract_path)
    except Exception as exc:
        raise FullMasterError(f"capture contract is not consumable: {exc}") from exc
    return contract, provenance


def _find_span(contract: Any, segment: EditSegment) -> Any:
    spans = tuple(getattr(contract, "clean_spans", ()))
    candidates = []
    for span in spans:
        if segment.span_id is not None and str(getattr(span, "span_id", "")) != segment.span_id:
            continue
        begin = float(getattr(span, "begin_seconds"))
        end = float(getattr(span, "end_seconds"))
        if begin <= segment.source_start_seconds + 1e-9 and segment.source_end_seconds <= end + 1e-9:
            candidates.append(span)
    if not candidates:
        wanted = f" span {segment.span_id!r}" if segment.span_id else ""
        raise FullMasterError(
            f"segment {segment.segment_id!r} source window "
            f"{segment.source_start_seconds:g}..{segment.source_end_seconds:g}s "
            f"is not contained in a clean capture span{wanted}"
        )
    selected = min(
        candidates,
        key=lambda item: (
            float(getattr(item, "end_seconds")) - float(getattr(item, "begin_seconds")),
            float(getattr(item, "begin_seconds")),
            str(getattr(item, "span_id", "")),
        ),
    )
    observed_provenance = str(getattr(selected, "provenance", ""))
    if observed_provenance != segment.provenance:
        raise FullMasterError(
            f"segment {segment.segment_id!r} provenance {segment.provenance!r} "
            f"does not match capture span {getattr(selected, 'span_id', '')!r} "
            f"({observed_provenance!r})"
        )
    return selected


def _probe_json(path: Path, ffprobe: Path) -> dict[str, Any]:
    argv = [
        str(ffprobe),
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels,channel_layout",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise FullMasterError(f"ffprobe failed for {path}: {completed.stderr[-1000:]}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise FullMasterError(f"ffprobe returned invalid JSON for {path}") from exc
    if not isinstance(result, Mapping):
        raise FullMasterError(f"ffprobe result for {path} is not an object")
    return {"argv": argv, "result": result}


def _format_seconds(value: float) -> str:
    return f"{value:.6f}"


def _filter_escape(value: str | os.PathLike[str]) -> str:
    raw = os.fspath(value).replace("\\", "/")
    if any(character in raw for character in ("\x00", "\n", "\r")):
        raise FullMasterError("filter path contains a control character")
    return "".join(
        ("\\" + character) if character in "\\':,;[]" else character
        for character in raw
    )


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100.0)))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, hundredths = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{hundredths:02d}"


def _ass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chinese,Microsoft YaHei,46,&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,80,80,78,1
Style: English,Arial,34,&H00D8E8FF,&H00D8E8FF,&H80000000,&H80000000,0,1,0,0,100,100,0,0,1,2,1,2,80,80,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _duration_from_probe(probe: Mapping[str, Any]) -> float:
    result = probe.get("result")
    if not isinstance(result, Mapping):
        return 0.0
    value = result.get("format", {})
    if isinstance(value, Mapping):
        try:
            duration = float(value.get("duration", 0.0))
            return duration if math.isfinite(duration) and duration > 0 else 0.0
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _stream_types(probe: Mapping[str, Any]) -> set[str]:
    result = probe.get("result")
    if not isinstance(result, Mapping):
        return set()
    streams = result.get("streams")
    if not isinstance(streams, list):
        return set()
    return {
        str(row.get("codec_type"))
        for row in streams
        if isinstance(row, Mapping) and row.get("codec_type")
    }


def _validate_deliverable_probe(
    probe: Mapping[str, Any], *, target_duration_seconds: float
) -> None:
    """Fail closed unless the encoded file meets the advertised master ABI.

    FFmpeg's command line requests these properties, but the post-render
    probe is the authoritative byte-level check.  Keeping this validation in
    the project producer means a changed local FFmpeg build cannot silently
    produce a differently encoded deliverable that later gets labelled as a
    1080p/60 master.
    """

    result = probe.get("result")
    if not isinstance(result, Mapping):
        raise FullMasterError("deliverable ffprobe result is not an object")
    streams = result.get("streams")
    if not isinstance(streams, list):
        raise FullMasterError("deliverable ffprobe did not report streams")
    video = next(
        (row for row in streams if isinstance(row, Mapping) and row.get("codec_type") == "video"),
        None,
    )
    audio = next(
        (row for row in streams if isinstance(row, Mapping) and row.get("codec_type") == "audio"),
        None,
    )
    if video is None or audio is None:
        raise FullMasterError("deliverable must contain one video and one audio stream")
    try:
        width = int(video.get("width"))
        height = int(video.get("height"))
        channels = int(audio.get("channels"))
        sample_rate = int(float(audio.get("sample_rate")))
    except (TypeError, ValueError) as exc:
        raise FullMasterError("deliverable stream geometry/audio fields are invalid") from exc
    if (width, height) != (WIDTH, HEIGHT):
        raise FullMasterError(
            f"deliverable dimensions are {width}x{height}, expected {WIDTH}x{HEIGHT}"
        )
    frame_rate = str(video.get("r_frame_rate", ""))
    if frame_rate not in {"60/1", "60/1.0", "60"}:
        raise FullMasterError(
            f"deliverable frame rate is {frame_rate!r}, expected 60/1"
        )
    if str(video.get("codec_name", "")).casefold() not in {"h264", "avc1"}:
        raise FullMasterError("deliverable video codec is not H.264")
    if str(video.get("pix_fmt", "")).casefold() != PIXEL_FORMAT:
        raise FullMasterError(
            f"deliverable pixel format is {video.get('pix_fmt')!r}, expected {PIXEL_FORMAT}"
        )
    if str(audio.get("codec_name", "")).casefold() != AUDIO_CODEC:
        raise FullMasterError("deliverable audio codec is not AAC")
    if sample_rate != SAMPLE_RATE or channels != CHANNELS:
        raise FullMasterError(
            f"deliverable audio is {sample_rate} Hz/{channels} channels, "
            f"expected {SAMPLE_RATE} Hz/{CHANNELS} channels"
        )
    layout = str(audio.get("channel_layout", "")).casefold()
    if layout and layout != "stereo":
        raise FullMasterError(f"deliverable channel layout is {layout!r}, expected stereo")
    duration = _duration_from_probe(probe)
    if abs(duration - target_duration_seconds) > 0.25:
        raise FullMasterError(
            f"rendered full master duration {duration:.3f}s is outside target "
            f"{target_duration_seconds:.3f}s tolerance"
        )


def write_ass(
    path: Path,
    edl: FullMasterEdl,
    *,
    narration_durations: Mapping[str, float],
) -> tuple[dict[str, Any], ...]:
    rows = {segment.segment_id: start for segment, start in edl.timeline_rows()}
    segments = {segment.segment_id: segment for segment in edl.segments}
    events: list[dict[str, Any]] = []
    for cue in edl.cues:
        segment = segments[cue.segment_id]
        timeline_start = rows[cue.segment_id] + cue.offset_seconds
        available = segment.duration_seconds - cue.offset_seconds
        # A missing probe is only possible for callers building a pure plan
        # (the render path always probes every file).  Keep that fallback
        # short so a plan preview does not accidentally duck an entire shot.
        audio_duration = narration_durations.get(cue.file_name, 0.0)
        requested = cue.subtitle_duration_seconds
        visible_duration = requested if requested is not None else (audio_duration or 5.0)
        visible_duration = min(max(0.1, visible_duration), available)
        timeline_end = timeline_start + visible_duration
        events.append(
            {
                "cue": cue,
                "start": timeline_start,
                "end": timeline_end,
            }
        )
    events.sort(key=lambda item: (float(item["start"]), item["cue"].cue_id))
    lines = [ASS_HEADER]
    for event in events:
        cue = event["cue"]
        lines.append(
            f"Dialogue: 0,{_ass_time(event['start'])},{_ass_time(event['end'])},Chinese,,0,0,78,,"
            f"{_ass_escape(cue.zh)}\\N{{\\i1}}{_ass_escape(cue.en)}{{\\i0}}\n"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8", newline="\n")
    return tuple(
        {
            "cue_id": event["cue"].cue_id,
            "start_seconds": event["start"],
            "end_seconds": event["end"],
            "file": event["cue"].file_name,
        }
        for event in events
    )


def _duck_expression(windows: Sequence[tuple[float, float]]) -> str:
    if not windows:
        return ""
    parts = [f"between(t,{_format_seconds(start)},{_format_seconds(end)})" for start, end in windows]
    return "+".join(parts)


def build_filtergraph(
    edl: FullMasterEdl,
    *,
    ass_path: Path,
    narration_durations: Mapping[str, float],
) -> str:
    """Build the single-pass visual concat + game/narration mix graph."""

    rows = {segment.segment_id: start for segment, start in edl.timeline_rows()}
    video_rows: list[str] = []
    audio_rows: list[str] = []
    for index, segment in enumerate(edl.segments):
        duration = _format_seconds(segment.duration_seconds)
        video_rows.append(
            f"[{index}:v]trim=duration={duration},setpts=PTS-STARTPTS,"
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS},"
            f"format={PIXEL_FORMAT}[v{index}]"
        )
        audio_rows.append(
            f"[{index}:a]aresample={SAMPLE_RATE}:async=0,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad,atrim=duration={duration},asetpts=N/SR/TB[a{index}]"
        )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(edl.segments)))
    graph: list[str] = [*video_rows, *audio_rows]
    graph.append(
        f"{concat_inputs}concat=n={len(edl.segments)}:v=1:a=1[vcat][gamecat]"
    )

    cue_rows: list[str] = []
    duck_windows: list[tuple[float, float]] = []
    for cue_index, cue in enumerate(edl.cues):
        segment = next(segment for segment in edl.segments if segment.segment_id == cue.segment_id)
        timeline_start = rows[cue.segment_id] + cue.offset_seconds
        available = segment.duration_seconds - cue.offset_seconds
        # Real renders always provide a positive ffprobe duration.  The
        # bounded fallback keeps this pure graph builder useful in offline
        # tests and avoids treating a missing probe as a full-shot voice-over.
        audio_duration = narration_durations.get(cue.file_name, 0.0) or min(8.0, available)
        clip_duration = min(max(0.1, audio_duration), available)
        timeline_end = timeline_start + clip_duration
        duck_windows.append((timeline_start, timeline_end))
        input_index = len(edl.segments) + cue_index
        delay_ms = int(round(timeline_start * 1000.0))
        delay = f",adelay={delay_ms}|{delay_ms}" if delay_ms > 0 else ""
        cue_rows.append(
            f"[{input_index}:a]aresample={SAMPLE_RATE}:async=0,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=duration={_format_seconds(clip_duration)},asetpts=PTS-STARTPTS"
            f"{delay},afade=t=in:st=0:d=0.03,"
            f"afade=t=out:st={_format_seconds(max(0.0, timeline_end - timeline_start - 0.05))}:d=0.05[n{cue_index}]"
        )
    graph.extend(cue_rows)
    game_chain = "[gamecat]volume=6.000000dB"
    expression = _duck_expression(duck_windows)
    if expression:
        # xAR's audio planner uses this same deterministic volume/enable
        # primitive.  The expression is quoted for libavfilter, not a shell.
        game_chain += f",volume=enable='{expression}':volume=-6.000000dB"
    game_chain += ",aresample=48000:async=0,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=duration=" + _format_seconds(edl.target_duration_seconds) + ",asetpts=N/SR/TB[game]"
    graph.append(game_chain)
    mix_inputs = "[game]" + "".join(f"[n{i}]" for i in range(len(edl.cues)))
    if edl.cues:
        graph.append(
            f"{mix_inputs}amix=inputs={len(edl.cues)+1}:duration=first:dropout_transition=0:normalize=0,"
            f"aresample={SAMPLE_RATE}:async=0,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad,atrim=duration={_format_seconds(edl.target_duration_seconds)},asetpts=N/SR/TB[aout]"
        )
    else:
        graph.append(
            f"[game]aresample={SAMPLE_RATE}:async=0,aformat=sample_fmts=fltp:channel_layouts=stereo[ aout]".replace("[ aout]", "[aout]")
        )
    graph.append(
        f"[vcat]ass=filename='{_filter_escape(ass_path)}',format={PIXEL_FORMAT}[vout]"
    )
    return ";".join(graph)


def _load_xar_process() -> tuple[Any, Any]:
    source = os.environ.get("XAR_PROMO_TOOLCHAIN_SOURCE")
    if source:
        src = Path(source).expanduser().resolve() / "src"
    else:
        src = Path(r"G:\workspace\xar_promo_toolchain") / "src"
    if not src.is_dir():
        raise FullMasterError(f"xAR source directory is missing: {src}")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from xar_promo.process import CommandSpec, run_command  # type: ignore
    except ModuleNotFoundError as exc:
        raise FullMasterError("xAR process module is unavailable") from exc
    return CommandSpec, run_command


def _xar_provenance() -> dict[str, Any]:
    """Return the source checkout and package version used by the executor."""

    source_root = Path(
        os.environ.get("XAR_PROMO_TOOLCHAIN_SOURCE", r"G:\workspace\xar_promo_toolchain")
    ).expanduser().resolve()
    source_src = source_root / "src"
    if source_src.is_dir() and str(source_src) not in sys.path:
        sys.path.insert(0, str(source_src))
    commit: str | None = None
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            commit = completed.stdout.strip()
    except OSError:
        pass
    version: str | None = None
    try:
        import xar_promo  # type: ignore

        version = getattr(xar_promo, "__version__", None)
    except Exception:
        pass
    return {
        "source_root": source_root.as_posix(),
        "git_commit": commit,
        "package_version": version,
    }


def _verify_record(path: Path, expected: Mapping[str, Any], label: str) -> None:
    actual = file_record(path)
    if actual["bytes"] != expected.get("bytes") or actual["sha256"] != str(expected.get("sha256", "")).upper():
        raise FullMasterError(f"{label} changed during full-master render: {path}")


def render_full_master(
    *,
    raw: Path,
    output_root: Path,
    edl: FullMasterEdl,
    narration_root: Path,
    ffmpeg: Path,
    ffprobe: Path,
    capture_contract_path: Path,
    capture_contract: Any,
    capture_provenance: Mapping[str, Any],
    edl_path: Path | None,
) -> dict[str, Any]:
    """Validate inputs, run one auditable FFmpeg command, and write a manifest."""

    raw = raw.resolve()
    output_root = output_root.resolve()
    narration_root = narration_root.resolve()
    ffmpeg = ffmpeg.resolve()
    ffprobe = ffprobe.resolve()
    validate_output_root(raw, output_root)
    if not raw.is_file() or not ffmpeg.is_file() or not ffprobe.is_file():
        raise FullMasterError("raw, ffmpeg and ffprobe must all be files")
    if not narration_root.is_dir():
        raise FullMasterError(f"narration root is missing: {narration_root}")

    xar_provenance = _xar_provenance()

    # Resolve and bind all narration files before creating an output directory.
    narration_paths: dict[str, Path] = {}
    for cue in edl.cues:
        candidate = (narration_root / Path(cue.file_name)).resolve()
        try:
            candidate.relative_to(narration_root)
        except ValueError as exc:
            raise FullMasterError(f"narration path escapes root: {cue.file_name}") from exc
        if not candidate.is_file():
            raise FullMasterError(f"narration file is missing: {candidate}")
        narration_paths[cue.file_name] = candidate

    # Capture span and source-duration checks happen before any output write.
    span_rows: list[dict[str, Any]] = []
    for segment in edl.segments:
        span = _find_span(capture_contract, segment)
        span_rows.append(
            {
                "segment_id": segment.segment_id,
                "shot_id": segment.shot_id,
                "span_id": str(getattr(span, "span_id")),
                "begin_seconds": float(getattr(span, "begin_seconds")),
                "end_seconds": float(getattr(span, "end_seconds")),
                "provenance": str(getattr(span, "provenance")),
            }
        )

    source_probe = _probe_json(raw, ffprobe)
    source_duration = _duration_from_probe(source_probe)
    if source_duration <= 0:
        raise FullMasterError("ffprobe did not report a positive source duration")
    source_types = _stream_types(source_probe)
    if not {"video", "audio"}.issubset(source_types):
        raise FullMasterError(
            "raw capture must contain both video and audio streams; "
            f"ffprobe reported {sorted(source_types)}"
        )
    if any(segment.source_end_seconds > source_duration + 0.25 for segment in edl.segments):
        raise FullMasterError(
            f"EDL references media past source duration {source_duration:.3f}s"
        )
    narration_probes: dict[str, dict[str, Any]] = {}
    narration_durations: dict[str, float] = {}
    for name, path in narration_paths.items():
        probe = _probe_json(path, ffprobe)
        narration_probes[name] = probe
        narration_durations[name] = _duration_from_probe(probe)
        if "audio" not in _stream_types(probe):
            raise FullMasterError(f"narration file has no audio stream: {path}")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=False, exist_ok=False)
    (output_root / "logs").mkdir()
    (output_root / "review").mkdir()
    (output_root / "renders").mkdir()
    (output_root / "subtitles").mkdir()
    ass_path = output_root / "subtitles" / "full-master.bilingual.ass"
    subtitle_events = write_ass(
        ass_path,
        edl,
        narration_durations=narration_durations,
    )
    # Materialize the exact normalized EDL before launching FFmpeg.  It is a
    # first-class immutable input (and therefore gets a hash record), even
    # when the caller used generated-contiguous mode without an input file.
    normalized_edl_payload = {
        "schema_version": 1,
        "kind": "vivhite_promo_full_master_edl",
        "source_label": edl.source_label,
        "target_duration_seconds": edl.target_duration_seconds,
        "segments": [
            segment.to_mapping(start) for segment, start in edl.timeline_rows()
        ],
        "cues": [
            cue.to_mapping(edl.segment_timeline_start(cue.segment_id))
            for cue in edl.cues
        ],
    }
    normalized_edl_path = output_root / "full-master-edl.json"
    normalized_edl_path.write_text(
        json.dumps(normalized_edl_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    final = output_root / "renders" / "full-master.mp4"
    partial = output_root / "renders" / "full-master.partial.mp4"
    graph = build_filtergraph(
        edl,
        ass_path=ass_path,
        narration_durations=narration_durations,
    )

    # One input per edit window gives FFmpeg accurate seeking while retaining
    # one-pass concat/mix determinism.  The narration inputs follow in EDL
    # order; their indices are part of the recorded command ABI.
    argv: list[str | os.PathLike[str]] = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
    ]
    for segment in edl.segments:
        argv.extend(
            (
                "-ss",
                _format_seconds(segment.source_start_seconds),
                "-t",
                _format_seconds(segment.duration_seconds),
                "-i",
                raw,
            )
        )
    for cue in edl.cues:
        argv.extend(("-i", narration_paths[cue.file_name]))
    argv.extend(
        (
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-t",
            _format_seconds(edl.target_duration_seconds),
            "-c:v",
            VIDEO_CODEC,
            "-preset",
            ENCODER_PRESET,
            "-crf",
            str(CRF),
            "-pix_fmt",
            PIXEL_FORMAT,
            "-c:a",
            AUDIO_CODEC,
            "-b:a",
            AUDIO_BITRATE,
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            partial,
        )
    )
    command_payload = [str(item).replace("\\", "/") for item in argv]
    (output_root / "logs" / "render-plan.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "vivhite_promo_full_master_render_plan",
                "target_duration_seconds": edl.target_duration_seconds,
                "filtergraph": graph,
                "argv": command_payload,
                "source_probe": source_probe,
                "narration_probes": narration_probes,
                "xar_executor": "xar_promo.process.run_command",
                "xar": xar_provenance,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    input_records: dict[str, dict[str, Any]] = {
        "raw": file_record(raw),
        "capture_contract": file_record(capture_contract_path),
        "ffmpeg": file_record(ffmpeg),
        "ffprobe": file_record(ffprobe),
        "ass": file_record(ass_path),
        "normalized_edl": file_record(normalized_edl_path),
    }
    for name, path in narration_paths.items():
        input_records[f"narration:{name}"] = file_record(path)
    if edl_path is not None:
        input_records["edl"] = file_record(edl_path)

    CommandSpec, run_command = _load_xar_process()
    spec = CommandSpec.create(
        argv,
        label="render Vivhite full master",
        partial_artifacts=(partial,),
    )
    try:
        result = run_command(spec, audit_directory=output_root / "logs" / "render")
    except Exception:
        # xAR intentionally retains partial output and process logs.  Do not
        # clean this directory or turn a failed attempt into a success.
        raise
    if not final.exists():
        # Promote only after the process succeeded and the partial is present;
        # os.replace is deterministic and cannot overwrite a pre-existing file.
        if not partial.is_file():
            raise FullMasterError("FFmpeg succeeded without producing the partial output")
        os.replace(partial, final)

    final_probe = _probe_json(final, ffprobe)
    _validate_deliverable_probe(
        final_probe, target_duration_seconds=edl.target_duration_seconds
    )
    # Keep the exact post-render ffprobe response as a first-class artifact.
    # Downstream run metadata can bind this file as ``technical-probe``
    # without having to rerun ffprobe (or trust an operator-supplied hash).
    # It is written only after the deliverable has passed the duration gate;
    # failed attempts retain the xAR process partial/logs but never receive a
    # misleading successful probe sidecar.
    final_probe_path = output_root / "review" / "full-master-deliverable-probe.json"
    final_probe_payload = {
        "schema_version": 1,
        "kind": "vivhite_promo_full_master_deliverable_probe",
        "deliverable": file_record(final),
        "expected": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "audio_sample_rate": SAMPLE_RATE,
            "audio_channels": CHANNELS,
            "video_codec": VIDEO_CODEC,
            "audio_codec": AUDIO_CODEC,
            "pixel_format": PIXEL_FORMAT,
            "target_duration_seconds": edl.target_duration_seconds,
        },
        "ffprobe": final_probe,
    }
    final_probe_path.write_text(
        json.dumps(final_probe_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    final_probe_record = file_record(final_probe_path)
    # Last boundary: every immutable input must still match the preflight
    # records.  A mutation invalidates this attempt, while preserving its
    # output and audit files for diagnosis.
    for key, record in input_records.items():
        if key == "ass":
            continue  # generated locally and intentionally immutable already
        path = Path(str(record["path"]))
        _verify_record(path, record, key)
    try:
        capture_contract.verify_unchanged()
    except Exception as exc:
        raise FullMasterError(
            f"capture evidence changed during full-master render: {exc}"
        ) from exc

    timeline = []
    for segment, start in edl.timeline_rows():
        row = segment.to_mapping(start)
        row["capture_span"] = next(item for item in span_rows if item["segment_id"] == segment.segment_id)
        timeline.append(row)
    manifest = {
        "schema_version": 1,
        "kind": "vivhite_promo_full_master_render",
        "status": "preliminary",
        "run_role": "full-master-draft",
        "target_duration_seconds": edl.target_duration_seconds,
        "deliverable": file_record(final),
        "source": {
            "raw_capture": input_records["raw"],
            "capture_contract": input_records["capture_contract"],
            "capture_provenance": dict(capture_provenance),
            "source_probe": source_probe,
            "edl": input_records["normalized_edl"],
            "edl_source": input_records.get("edl"),
            "timeline": timeline,
        },
        "narration": {
            "voice": VOICE,
            "external_bgm": False,
            "stems": [
                {
                    "cue_id": cue.cue_id,
                    "segment_id": cue.segment_id,
                    "file": input_records[f"narration:{cue.file_name}"],
                    "duration_seconds": narration_durations.get(cue.file_name),
                    "offset_seconds": cue.offset_seconds,
                }
                for cue in edl.cues
            ],
        },
        "subtitles": {
            "burned_in": True,
            "file": input_records["ass"],
            "events": list(subtitle_events),
        },
        "technical_probe": final_probe_record,
        "technical_probe_payload": final_probe_payload,
        "audio_policy": {
            "include_bgm": False,
            "game_audio": True,
            "game_gain_db": 6.0,
            "narration_duck_db": -6.0,
            "sample_rate": SAMPLE_RATE,
            "channels": CHANNELS,
        },
        "tools": {
            "ffmpeg": input_records["ffmpeg"],
            "ffprobe": input_records["ffprobe"],
            "xar": xar_provenance,
        },
        "audits": {
            "technical": "pending",
            "semantic": "pending",
            "human_review": "user-authorized-assumed-pass; no separate review step",
            "signoff": False,
            "export_approval": False,
        },
        "warning": "Draft only: this renderer does not certify semantic claims or publishing approval.",
    }
    (output_root / "review" / "render-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "output_root": str(output_root),
        "deliverable": str(final),
        "bytes": final.stat().st_size,
        "sha256": sha256_file(final),
        "duration_seconds": _duration_from_probe(final_probe),
        "technical_probe": str(final_probe_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--edl", type=Path, default=None)
    parser.add_argument(
        "--source-start",
        type=float,
        default=None,
        help="explicit source timestamp for the generated EDL (required when --edl is omitted)",
    )
    parser.add_argument("--narration-root", type=Path, default=NARRATION_DEFAULT)
    parser.add_argument("--capture-contract", type=Path, default=None)
    parser.add_argument("--ffmpeg", type=Path, default=FFMPEG_DEFAULT)
    parser.add_argument("--ffprobe", type=Path, default=FFPROBE_DEFAULT)
    args = parser.parse_args(argv)
    raw = args.raw.expanduser().resolve()
    if not raw.is_file():
        raise SystemExit(f"raw capture is missing: {raw}")
    ffmpeg = args.ffmpeg.expanduser().resolve()
    ffprobe = args.ffprobe.expanduser().resolve()
    contract_path = (
        args.capture_contract.expanduser().resolve()
        if args.capture_contract is not None
        else _infer_contract(raw)
    )
    edl_path = args.edl.expanduser().resolve() if args.edl is not None else None
    # Both the project capture adapter and the standalone EDL builder live
    # beside this script.  Add that directory before resolving either input so
    # the same entry point works when invoked as ``python render_full_master.py``
    # and when imported/embedded by a project runner.
    if str(PROMO_ROOT) not in sys.path:
        sys.path.insert(0, str(PROMO_ROOT))
    if edl_path is None and args.source_start is None:
        raise SystemExit(
            "--source-start is required when --edl is omitted; refusing to guess a capture window"
        )
    edl = load_edl(
        edl_path,
        source_start_seconds=args.source_start,
    )
    capture_contract, capture_provenance = _load_capture_binding(raw, contract_path)
    result = render_full_master(
        raw=raw,
        output_root=args.output_root.expanduser(),
        edl=edl,
        narration_root=args.narration_root.expanduser(),
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        capture_contract_path=contract_path,
        capture_contract=capture_contract,
        capture_provenance=capture_provenance,
        edl_path=edl_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"full-master render failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise


__all__ = [
    "DEFAULT_CUE_TEXT",
    "EditSegment",
    "FullMasterEdl",
    "FullMasterError",
    "NarrationCue",
    "SHOT_DURATIONS",
    "TARGET_DURATION_SECONDS",
    "build_filtergraph",
    "load_edl",
    "_validate_deliverable_probe",
    "write_ass",
]
