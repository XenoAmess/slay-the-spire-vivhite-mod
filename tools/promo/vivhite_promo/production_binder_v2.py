"""Fail-closed production binding for the Vivhite director-v2 EDL.

``director_v2`` deliberately authors only a declaration-level draft.  This
module is the boundary that turns that draft into a renderable production EDL:
it reads real files, recomputes their byte counts and SHA-256 digests, consumes
hash-bound ffprobe output, and loads every formal or explicitly declared UI
action through the path-only ``action_evidence_v2.load_action_evidence`` entry
point.  UI actions belong to a separate branch and never create a formal
mechanism action chain.

The binding pass is read-only; the optional CLI writes only one fresh,
non-overwriting EDL.  In particular, a staged setup may be proven by an action
contract, but its artifact and frames are never copied into the EDL.
"""

from __future__ import annotations

import argparse
import copy
import datetime as _datetime
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from . import action_evidence_v2, director_v2


PRODUCTION_STATUS = "production_verified"
SOURCE_PROBE_KIND = "vivhite_promo_source_probe_v2"
ACTION_BINDING_KIND = "vivhite_promo_action_binding_v2"
FPS = 60
WIDTH = 1920
HEIGHT = 1080
# A UI take (for example the ordinary-shop chapter) is not a mechanism take:
# it has no storyboard ``formal_action_chain``.  Its optional action evidence
# is still a real game-UI receipt and is promoted through this separate branch.
# Keep this enum deliberately small and explicit so an arbitrary producer
# cannot turn an opaque ``action_evidence`` array into a formal card chain.
#
# The three tower-life actions below are intentionally kept in this explicit
# set instead of accepting every value from ``action_evidence_v2.ACTION_KINDS``.
# A producer must opt in to a known UI semantic and provide its target in the
# manifest entry; a formal card action can therefore never be smuggled into a
# UI-only take by merely omitting ``formal_action_chain``.
UI_ACTION_KINDS = frozenset(
    {
        "choose_reward_card",
        "choose_map_node",
        "choose_rest_option",
        "buy_card",
        # These two legacy shop controls are retained for ABI compatibility;
        # their custom receipts remain evidence-only until they have a native
        # action-evidence payload kind.
        "close_inventory",
        "leave_shop",
    }
)
UI_ACTION_ASSET_TYPES = frozenset({"ui_gameplay", "gameplay"})
_UI_ACTION_SPECS: Mapping[str, tuple[str, str, str | None, str]] = {
    # receipt target.kind, request parameter, fixed parameter value, entry field
    #
    # ``target_*_id`` names deliberately mirror the sidecar's request
    # parameter while making the manifest declaration unambiguous.  Keeping a
    # separate field for each action kind prevents a map node or rest option
    # from being accidentally interpreted as a shop item.
    "choose_reward_card": ("reward_card", "card_id", None, "target_card_id"),
    "choose_map_node": ("map_node", "node_id", None, "target_node_id"),
    "choose_rest_option": ("rest_option", "option", "rest", "rest_option"),
    "buy_card": ("shop_item", "item_id", None, "target_item_id"),
    "close_inventory": ("shop_control", "control", "close_inventory", "control"),
    "leave_shop": ("shop_control", "control", "leave_shop", "control"),
}
_FRAME_EPSILON = 1.0 / FPS + 1e-9
_AAC_LC_PACKET_SAMPLES = 1024
_CONTAINER_DURATION_SLACK_SECONDS = 0.001
_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_PORTABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class ProductionBinderV2Error(ValueError):
    """A declared source cannot be promoted to a production-verified EDL."""


@dataclass(frozen=True, slots=True)
class _VerifiedFile:
    relative_path: str
    path: Path
    bytes: int
    sha256: str
    stat_signature: tuple[int, int, int, int]

    def descriptor(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }

    def assert_unchanged(self) -> None:
        try:
            current = os.stat(self.path, follow_symlinks=False)
        except OSError as exc:
            raise ProductionBinderV2Error(
                f"verified file disappeared: {self.relative_path}: {exc}"
            ) from exc
        if _stat_signature(current) != self.stat_signature:
            raise ProductionBinderV2Error(
                f"verified file changed while binding: {self.relative_path}"
            )


@dataclass(frozen=True, slots=True)
class _TakeRuntime:
    take_id: str
    source: _VerifiedFile
    probe_file: _VerifiedFile
    probe: Mapping[str, object]
    capture_identity: Mapping[str, str]
    recording: Mapping[str, object]
    game_process: Mapping[str, object]
    recorder_process: Mapping[str, object]
    evidence: Mapping[str, _VerifiedFile]
    template_values: Mapping[str, Mapping[str, str]]
    action_sidecars: Mapping[str, _VerifiedFile]
    action_contracts: Mapping[str, action_evidence_v2.ActionEvidenceContract]
    action_bindings: Mapping[str, Mapping[str, object]]
    # Step IDs in ``action_contracts`` that came from the UI-action branch.
    # Formal mechanism counts and UI counts must remain separately auditable.
    ui_action_step_ids: frozenset[str]


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionBinderV2Error(f"{context} must be an object")
    return value


def _list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProductionBinderV2Error(f"{context} must be an array")
    return value


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ProductionBinderV2Error(f"{context} must be non-empty NUL-free text")
    return value.strip()


def _identifier(value: Any, context: str) -> str:
    result = _text(value, context)
    if _PORTABLE_ID.fullmatch(result) is None:
        raise ProductionBinderV2Error(f"{context} must be a portable identifier")
    return result


def _integer(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProductionBinderV2Error(
            f"{context} must be an integer >= {minimum}"
        )
    return value


def _number(value: Any, context: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProductionBinderV2Error(f"{context} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise ProductionBinderV2Error(f"{context} must be finite and {qualifier}")
    return result


def _sha256(value: Any, context: str) -> str:
    digest = _text(value, context).upper()
    if _SHA256.fullmatch(digest) is None:
        raise ProductionBinderV2Error(f"{context} must be a SHA-256 digest")
    return digest


def _relative_path(value: Any, context: str) -> str:
    raw = _text(value, context)
    if "\\" in raw or any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw):
        raise ProductionBinderV2Error(
            f"{context} must use portable '/' separators without controls"
        )
    pure = PurePosixPath(raw)
    if (
        pure.is_absolute()
        or _DRIVE.match(raw)
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != raw
    ):
        raise ProductionBinderV2Error(f"{context} must be a normalized relative path")
    normalized = raw.casefold()
    if "a4" in {part.casefold() for part in pure.parts} or "full-master-tts-a4" in normalized:
        raise ProductionBinderV2Error(f"{context} must not reference legacy a4 material")
    return raw


def _stat_signature(metadata: os.stat_result) -> tuple[int, int, int, int]:
    # On Windows, a path stat and fstat of the same newly-created NTFS file can
    # report st_ctime_ns a few hundred nanoseconds apart.  File identity,
    # length, and mtime remain stable and are the portable replacement gate.
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
    )


def _reject_link_or_reparse(path: Path, context: str) -> os.stat_result:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ProductionBinderV2Error(f"could not inspect {context} {path}: {exc}") from exc
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    if stat.S_ISLNK(metadata.st_mode) or attributes & _REPARSE_ATTRIBUTE:
        raise ProductionBinderV2Error(f"{context} must not be a link/reparse point: {path}")
    return metadata


def _artifact_root(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise ProductionBinderV2Error("artifact_root must be a local absolute path")
    raw = os.fspath(value)
    if not os.path.isabs(raw) or raw.startswith(("\\\\", "//")):
        raise ProductionBinderV2Error("artifact_root must be a local absolute path")
    path = Path(raw)
    for parent in reversed((path, *path.parents)):
        if parent.exists():
            _reject_link_or_reparse(parent, "artifact_root component")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionBinderV2Error(f"could not resolve artifact_root {path}") from exc
    metadata = _reject_link_or_reparse(resolved, "artifact_root")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ProductionBinderV2Error("artifact_root must be a directory")
    return resolved


def _path_inside(root: Path, relative: str, context: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        _reject_link_or_reparse(current, context)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionBinderV2Error(f"{context} escapes artifact_root: {relative}") from exc
    return resolved


def _verify_file(
    root: Path,
    descriptor: Mapping[str, Any],
    context: str,
    *,
    require_json: bool = False,
) -> _VerifiedFile:
    relative = _relative_path(descriptor.get("path"), f"{context}.path")
    expected_bytes = _integer(descriptor.get("bytes"), f"{context}.bytes", minimum=1)
    expected_sha = _sha256(descriptor.get("sha256"), f"{context}.sha256")
    if require_json and Path(relative).suffix.casefold() != ".json":
        raise ProductionBinderV2Error(f"{context}.path must use a .json filename")
    path = _path_inside(root, relative, context)
    metadata = _reject_link_or_reparse(path, context)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ProductionBinderV2Error(f"{context} must be a regular unlinked file")
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if _stat_signature(opened) != _stat_signature(metadata):
                raise ProductionBinderV2Error(f"{context} changed before it was read")
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                byte_count += len(block)
            closed = os.fstat(stream.fileno())
    except OSError as exc:
        raise ProductionBinderV2Error(f"could not read {context} {relative}: {exc}") from exc
    if _stat_signature(closed) != _stat_signature(metadata):
        raise ProductionBinderV2Error(f"{context} changed while it was read")
    actual_sha = digest.hexdigest().upper()
    if byte_count != expected_bytes or actual_sha != expected_sha:
        raise ProductionBinderV2Error(
            f"{context} bytes/SHA-256 do not match the declared artifact"
        )
    return _VerifiedFile(
        relative,
        path,
        byte_count,
        actual_sha,
        _stat_signature(metadata),
    )


def _read_verified_json(file: _VerifiedFile, context: str) -> Mapping[str, Any]:
    try:
        value = json.loads(file.path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionBinderV2Error(f"{context} must be valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ProductionBinderV2Error(f"{context} JSON root must be an object")
    return value


def _document_file(value: str | Path, context: str) -> tuple[Path, bytes, tuple[int, int, int, int]]:
    if not isinstance(value, (str, Path)):
        raise ProductionBinderV2Error(f"{context} requires a filesystem path")
    raw = os.fspath(value)
    if not os.path.isabs(raw) or raw.startswith(("\\\\", "//")):
        raise ProductionBinderV2Error(f"{context} must be a local absolute path")
    path = Path(raw)
    for parent in reversed((path, *path.parents)):
        if parent.exists():
            _reject_link_or_reparse(parent, f"{context} component")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionBinderV2Error(f"could not resolve {context} {path}") from exc
    metadata = _reject_link_or_reparse(resolved, context)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ProductionBinderV2Error(f"{context} must be a regular unlinked file")
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        raise ProductionBinderV2Error(f"could not read {context} {resolved}: {exc}") from exc
    if _stat_signature(os.stat(resolved, follow_symlinks=False)) != _stat_signature(metadata):
        raise ProductionBinderV2Error(f"{context} changed while it was read")
    return resolved, data, _stat_signature(metadata)


def _read_input_json(value: str | Path, context: str) -> tuple[Mapping[str, Any], Mapping[str, object], Path, tuple[int, int, int, int]]:
    path, data, signature = _document_file(value, context)
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionBinderV2Error(f"{context} must be valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ProductionBinderV2Error(f"{context} root must be an object")
    descriptor = {
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
    }
    return payload, descriptor, path, signature


def _aware_utc(value: Any, context: str) -> _datetime.datetime:
    raw = _text(value, context)
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = _datetime.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProductionBinderV2Error(f"{context} must be RFC 3339 time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProductionBinderV2Error(f"{context} must include a UTC offset")
    return parsed.astimezone(_datetime.timezone.utc)


def _process_identity(value: Any, context: str) -> Mapping[str, object]:
    row = _mapping(value, context)
    pid = _integer(row.get("pid"), f"{context}.pid", minimum=1)
    identity = _identifier(row.get("identity"), f"{context}.identity")
    started = _aware_utc(row.get("started_utc"), f"{context}.started_utc")
    return MappingProxyType(
        {"pid": pid, "identity": identity, "started_utc": started.isoformat().replace("+00:00", "Z")}
    )


def _int_from_probe(value: Any, context: str) -> int:
    if isinstance(value, bool):
        raise ProductionBinderV2Error(f"{context} must be an integer")
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    raise ProductionBinderV2Error(f"{context} must be an integer")


def _probe_duration(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ProductionBinderV2Error(f"{context} must be a finite duration")
    try:
        result = float(value)
    except ValueError as exc:
        raise ProductionBinderV2Error(f"{context} must be a finite duration") from exc
    if not math.isfinite(result) or result < 0:
        raise ProductionBinderV2Error(f"{context} must be a non-negative duration")
    return result


def _validate_source_probe(
    payload: Mapping[str, Any],
    *,
    source: _VerifiedFile,
    declared_duration: float,
    context: str,
) -> Mapping[str, object]:
    if payload.get("schema_version") != 2 or payload.get("kind") != SOURCE_PROBE_KIND:
        raise ProductionBinderV2Error(
            f"{context} must declare {SOURCE_PROBE_KIND} schema_version 2"
        )
    if payload.get("status") != "completed":
        raise ProductionBinderV2Error(f"{context}.status must be completed")
    bound_source = _mapping(payload.get("source"), f"{context}.source")
    if (
        _relative_path(bound_source.get("path"), f"{context}.source.path") != source.relative_path
        or _integer(bound_source.get("bytes"), f"{context}.source.bytes", minimum=1) != source.bytes
        or _sha256(bound_source.get("sha256"), f"{context}.source.sha256") != source.sha256
    ):
        raise ProductionBinderV2Error(f"{context} does not bind the verified source video")
    result = _mapping(payload.get("result"), f"{context}.result")
    streams = _list(result.get("streams"), f"{context}.result.streams")
    videos = [row for row in streams if isinstance(row, Mapping) and row.get("codec_type") == "video"]
    audios = [row for row in streams if isinstance(row, Mapping) and row.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1 or len(videos) + len(audios) != len(streams):
        raise ProductionBinderV2Error(f"{context} must prove exactly one video and one audio stream")
    video = videos[0]
    audio = audios[0]
    width = _int_from_probe(video.get("width"), f"{context}.video.width")
    height = _int_from_probe(video.get("height"), f"{context}.video.height")
    if (width, height) != (WIDTH, HEIGHT):
        raise ProductionBinderV2Error(f"{context} video must be 1920x1080")
    if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        raise ProductionBinderV2Error(f"{context} video must be H.264 yuv420p")
    if video.get("r_frame_rate") != "60/1" or video.get("avg_frame_rate") != "60/1":
        raise ProductionBinderV2Error(f"{context} video must be constant 60/1 FPS")
    frame_value = video.get("nb_read_frames", video.get("nb_frames"))
    frame_count = _int_from_probe(frame_value, f"{context}.video.frame_count")
    if frame_count < 1 or not math.isclose(frame_count / FPS, declared_duration, rel_tol=0.0, abs_tol=_FRAME_EPSILON):
        raise ProductionBinderV2Error(f"{context} frame count does not match declared duration")
    if audio.get("codec_name") != "aac":
        raise ProductionBinderV2Error(f"{context} audio must be AAC")
    sample_rate = _int_from_probe(audio.get("sample_rate"), f"{context}.audio.sample_rate")
    channels = _int_from_probe(audio.get("channels"), f"{context}.audio.channels")
    if sample_rate != 48_000 or channels != 2 or audio.get("channel_layout") != "stereo":
        raise ProductionBinderV2Error(f"{context} audio must be 48 kHz stereo")
    format_row = _mapping(result.get("format"), f"{context}.result.format")
    container_duration = _probe_duration(
        format_row.get("duration"), f"{context}.format.duration"
    )
    decoded_video_duration = frame_count / FPS
    container_duration_tolerance = max(
        1.0 / FPS,
        _AAC_LC_PACKET_SAMPLES / sample_rate,
    ) + _CONTAINER_DURATION_SLACK_SECONDS
    duration_rounding_epsilon = math.ulp(
        max(abs(container_duration), abs(decoded_video_duration), 1.0)
    )
    if (
        abs(container_duration - decoded_video_duration)
        > container_duration_tolerance + duration_rounding_epsilon
    ):
        raise ProductionBinderV2Error(
            f"{context} format duration does not match decoded video duration"
        )
    durations: dict[str, float] = {}
    # Matroska commonly omits per-stream duration even when -count_frames
    # supplies an exact decoded video count.  Treat an omitted/N/A stream
    # duration as absent evidence, while still requiring and checking it when
    # ffprobe provides one.
    for label, row in (("video", video), ("audio", audio)):
        raw_duration = row.get("duration")
        if raw_duration not in {None, "N/A"}:
            durations[label] = _probe_duration(
                raw_duration, f"{context}.{label}.duration"
            )
    for label, duration in durations.items():
        if not math.isclose(duration, declared_duration, rel_tol=0.0, abs_tol=_FRAME_EPSILON):
            raise ProductionBinderV2Error(
                f"{context} {label} duration does not match declared source duration"
            )
    for label, row in (("video", video), ("audio", audio)):
        if _probe_duration(row.get("start_time"), f"{context}.{label}.start_time") != 0:
            raise ProductionBinderV2Error(f"{context} {label} stream must start at zero")
    return MappingProxyType(
        {
            "duration_seconds": declared_duration,
            "width": width,
            "height": height,
            "fps": FPS,
            "frame_count": frame_count,
            "has_audio": True,
            "audio_sample_rate_hz": sample_rate,
            "audio_channels": channels,
        }
    )


def _capture_identity(value: Any, take_id: str, context: str) -> Mapping[str, str]:
    row = _mapping(value, context)
    required = (
        "session_id",
        "game_run_id",
        "game_process_id",
        "source_video_artifact_id",
        "run_id",
        "take_id",
    )
    result = {name: _identifier(row.get(name), f"{context}.{name}") for name in required}
    if result["take_id"] != take_id:
        raise ProductionBinderV2Error(f"{context}.take_id must match {take_id}")
    return MappingProxyType(result)


def _recording(
    value: Any,
    *,
    frame_count: int,
    declared_duration: float,
    context: str,
) -> Mapping[str, object]:
    row = _mapping(value, context)
    start_frame = _integer(row.get("start_frame"), f"{context}.start_frame")
    end_frame = _integer(row.get("end_frame"), f"{context}.end_frame")
    start_time = _number(row.get("started_monotonic_seconds"), f"{context}.started_monotonic_seconds")
    stop_time = _number(row.get("stopped_monotonic_seconds"), f"{context}.stopped_monotonic_seconds", positive=True)
    if end_frame - start_frame != frame_count:
        raise ProductionBinderV2Error(f"{context} frame bounds must match ffprobe frame count")
    if stop_time <= start_time or not math.isclose(
        stop_time - start_time, declared_duration, rel_tol=0.0, abs_tol=0.25
    ):
        raise ProductionBinderV2Error(f"{context} monotonic bounds must match source duration")
    return MappingProxyType(
        {
            "start_frame": start_frame,
            "end_frame": end_frame,
            "started_monotonic_seconds": start_time,
            "stopped_monotonic_seconds": stop_time,
        }
    )


def _evidence_catalog(
    root: Path, value: Any, *, context: str
) -> Mapping[str, tuple[str, _VerifiedFile]]:
    result: dict[str, tuple[str, _VerifiedFile]] = {}
    for index, item in enumerate(_list(value, context)):
        row_context = f"{context}[{index}]"
        row = _mapping(item, row_context)
        ref_id = _identifier(row.get("ref_id"), f"{row_context}.ref_id")
        role = _identifier(row.get("role"), f"{row_context}.role")
        if ref_id in result:
            raise ProductionBinderV2Error(f"{context} has duplicate ref_id {ref_id}")
        if row.get("status") not in {"verified", "bound"}:
            raise ProductionBinderV2Error(f"{row_context}.status must be verified or bound")
        if role == "staged_setup" or row.get("provenance") == "staged_setup":
            raise ProductionBinderV2Error(
                f"{row_context} must not expose staged_setup as display evidence"
            )
        result[ref_id] = (role, _verify_file(root, row, row_context))
    return MappingProxyType(result)


def _json_pointer(document: Any, pointer: Any, context: str) -> Any:
    raw = _text(pointer, context)
    if raw == "/":
        tokens = [""]
    elif raw.startswith("/"):
        tokens = raw[1:].split("/")
    else:
        raise ProductionBinderV2Error(f"{context} must be an absolute JSON pointer")
    current = document
    for raw_token in tokens:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise ProductionBinderV2Error(f"{context} does not resolve: missing {token!r}")
            current = current[token]
        elif isinstance(current, (list, tuple)):
            if not token.isascii() or not token.isdecimal():
                raise ProductionBinderV2Error(f"{context} array token must be an index")
            index = int(token)
            if index >= len(current):
                raise ProductionBinderV2Error(f"{context} array index is out of range")
            current = current[index]
        else:
            raise ProductionBinderV2Error(f"{context} traverses a scalar")
    return current


def _template_values(
    value: Any,
    *,
    evidence: Mapping[str, tuple[str, _VerifiedFile]],
    context: str,
) -> Mapping[str, Mapping[str, str]]:
    rows = [] if value is None else _list(value, context)
    result: dict[str, Mapping[str, str]] = {}
    for index, item in enumerate(rows):
        row_context = f"{context}[{index}]"
        row = _mapping(item, row_context)
        field = _identifier(row.get("field"), f"{row_context}.field")
        ref_id = _identifier(row.get("evidence_ref"), f"{row_context}.evidence_ref")
        if field in result:
            raise ProductionBinderV2Error(f"{context} duplicates field {field}")
        if ref_id not in evidence:
            raise ProductionBinderV2Error(f"{row_context} references absent evidence {ref_id}")
        document = _read_verified_json(evidence[ref_id][1], f"{row_context}.evidence")
        observed = _json_pointer(document, row.get("json_pointer"), f"{row_context}.json_pointer")
        if isinstance(observed, bool) or not isinstance(observed, (str, int, float)):
            raise ProductionBinderV2Error(f"{row_context}.json_pointer must resolve to display text/number")
        display_value = _text(row.get("display_value"), f"{row_context}.display_value")
        if str(observed) != display_value:
            raise ProductionBinderV2Error(f"{row_context}.display_value does not match observed evidence")
        result[field] = MappingProxyType(
            {"value": display_value, "evidence_ref": ref_id}
        )
    return MappingProxyType(result)


def _step_subshot(
    board: Mapping[str, Any], *, take_id: str, receipt_ref: str
) -> str:
    matches: list[str] = []
    for shot in board["shots"]:
        for subshot in shot["subshots"]:
            take = subshot.get("take")
            if not isinstance(take, Mapping) or take.get("take_id") != take_id:
                continue
            if (
                subshot.get("asset_type") == "mechanism_action"
                and receipt_ref in subshot.get("evidence_refs", [])
            ):
                matches.append(str(subshot["subshot_id"]))
    if len(matches) != 1:
        raise ProductionBinderV2Error(
            f"formal receipt {receipt_ref} in {take_id} must belong to exactly one "
            "mechanism_action subshot"
        )
    return matches[0]


def _expected_action(step: Mapping[str, Any], context: str) -> tuple[str, str, str]:
    input_kind = _text(step.get("input"), f"{context}.input")
    if input_kind == "card_click":
        return "play_card", "card", _identifier(step.get("card_id"), f"{context}.card_id")
    if input_kind == "end_turn_click":
        return "end_turn", "end_turn_button", "end_turn"
    raise ProductionBinderV2Error(f"{context}.input is not a supported formal UI action")


def _hitbox(value: Any, context: str) -> Mapping[str, int]:
    row = _mapping(value, context)
    result = {
        name: _integer(row.get(name), f"{context}.{name}")
        for name in ("left", "top", "right", "bottom")
    }
    if not (0 <= result["left"] < result["right"] <= WIDTH):
        raise ProductionBinderV2Error(f"{context} horizontal bounds are outside 1920px")
    if not (0 <= result["top"] < result["bottom"] <= HEIGHT):
        raise ProductionBinderV2Error(f"{context} vertical bounds are outside 1080px")
    return MappingProxyType(result)


def _artifact_summary(binding: action_evidence_v2.ArtifactBinding) -> dict[str, object]:
    return {
        "path": binding.relative_path,
        "bytes": binding.bytes,
        "sha256": binding.sha256,
        "document_kind": binding.document_kind,
    }


def _semantic_state(snapshot: action_evidence_v2.StateSnapshot) -> tuple[object, ...]:
    return (
        snapshot.frame,
        snapshot.monotonic_seconds,
        snapshot.state_version,
        snapshot.observation_seq,
        snapshot.payload,
    )


def _validate_contract_for_step(
    contract: action_evidence_v2.ActionEvidenceContract,
    *,
    take_id: str,
    subshot_id: str,
    step: Mapping[str, Any],
    capture: Mapping[str, str],
    recording: Mapping[str, object],
    hitbox: Mapping[str, int],
    visible_state_paths: Sequence[str],
    source_in: float,
    source_out: float,
    context: str,
) -> None:
    identity = contract.capture_identity
    expected_identity = {
        "session_id": identity.session_id,
        "game_run_id": identity.game_run_id,
        "game_process_id": identity.game_process_id,
        "source_video_artifact_id": identity.source_video_artifact_id,
        "run_id": identity.run_id,
        "take_id": identity.take_id,
    }
    if expected_identity != dict(capture):
        raise ProductionBinderV2Error(f"{context} capture identity does not match its source take")
    if contract.take_id != take_id or contract.subshot_id != subshot_id:
        raise ProductionBinderV2Error(f"{context} take/subshot identity does not match storyboard binding")
    expected_kind, expected_target_kind, expected_target_id = _expected_action(step, context)
    if contract.action_kind != expected_kind:
        raise ProductionBinderV2Error(f"{context} action kind does not match storyboard step")
    payload = contract.action_receipt.payload
    target = _mapping(payload.get("target"), f"{context}.receipt.target")
    if target.get("kind") != expected_target_kind or target.get("id") != expected_target_id:
        raise ProductionBinderV2Error(f"{context} action target does not match storyboard step")
    pointer = _mapping(payload.get("pointer"), f"{context}.receipt.pointer")
    x = _integer(pointer.get("x"), f"{context}.receipt.pointer.x")
    y = _integer(pointer.get("y"), f"{context}.receipt.pointer.y")
    if not (hitbox["left"] <= x < hitbox["right"] and hitbox["top"] <= y < hitbox["bottom"]):
        raise ProductionBinderV2Error(f"{context} pointer is outside its observed target hitbox")
    start_frame = int(recording["start_frame"])
    end_frame = int(recording["end_frame"])
    if contract.recording_start_frame != start_frame:
        raise ProductionBinderV2Error(f"{context} recording_start_frame does not match source recording")
    local_display_begin = start_frame + round(source_in * FPS)
    local_display_end = start_frame + round(source_out * FPS)
    if not (
        local_display_begin <= contract.display_span.begin_frame
        and contract.display_span.end_frame <= local_display_end
        and start_frame <= contract.display_span.begin_frame
        and contract.display_span.end_frame <= end_frame
    ):
        raise ProductionBinderV2Error(f"{context} action display span is not fully inside its EDL source span")
    start_time = float(recording["started_monotonic_seconds"])
    stop_time = float(recording["stopped_monotonic_seconds"])
    if not (
        start_time <= contract.state_before.monotonic_seconds
        < contract.state_after.monotonic_seconds <= stop_time
    ):
        raise ProductionBinderV2Error(f"{context} action timestamps are outside the recording")
    if contract.state_before.payload == contract.state_after.payload:
        raise ProductionBinderV2Error(f"{context} before/after state has no visible semantic change")
    visible_deltas: list[str] = []
    for index, pointer in enumerate(visible_state_paths):
        before_value = _json_pointer(
            contract.state_before.payload,
            pointer,
            f"{context}.visible_state_paths[{index}] before",
        )
        after_value = _json_pointer(
            contract.state_after.payload,
            pointer,
            f"{context}.visible_state_paths[{index}] after",
        )
        if before_value != after_value:
            visible_deltas.append(pointer)
    if not visible_deltas:
        raise ProductionBinderV2Error(
            f"{context} proves no change on its declared visible_state_paths"
        )
    if contract.staged_setup is not None:
        if not contract.staged_setup.setup_end_frame < start_frame:
            raise ProductionBinderV2Error(f"{context} staged_setup reaches the recorded source")


def _ui_action_subshot(
    board: Mapping[str, Any], *, take_id: str, subshot_id: str, context: str
) -> Mapping[str, Any]:
    """Resolve the sole UI gameplay owner of a public UI-action entry.

    Mechanism actions intentionally use :func:`_step_subshot`, which resolves
    an action receipt by role.  UI actions carry an explicit subshot ID because
    a shop/map take can contain several ordinary UI receipts and has no formal
    mechanism chain.  Requiring the declared owner to be a capture subshot
    keeps this branch independent from (and unable to masquerade as) the
    formal card-action ABI.
    """

    matches: list[Mapping[str, Any]] = []
    for shot in board["shots"]:
        for subshot in shot["subshots"]:
            if str(subshot.get("subshot_id")) != subshot_id:
                continue
            take = subshot.get("take")
            if isinstance(take, Mapping) and take.get("take_id") == take_id:
                matches.append(subshot)
    if len(matches) != 1:
        raise ProductionBinderV2Error(
            f"{context}.subshot_id must resolve to exactly one subshot owned by {take_id}"
        )
    asset_type = _text(matches[0].get("asset_type"), f"{context}.subshot.asset_type")
    if asset_type not in UI_ACTION_ASSET_TYPES:
        raise ProductionBinderV2Error(
            f"{context} UI action owner must be a ui_gameplay/gameplay subshot"
        )
    return matches[0]


def _assert_action_artifact_ref(
    evidence_catalog: Mapping[str, tuple[str, _VerifiedFile]],
    ref_id: str,
    binding: action_evidence_v2.ArtifactBinding,
    *,
    expected_role: str,
    context: str,
) -> None:
    """Bind a sidecar role to the take row's named evidence catalog entry."""

    row = evidence_catalog.get(ref_id)
    if row is None:
        raise ProductionBinderV2Error(f"{context} refers to absent evidence {ref_id}")
    role, artifact = row
    if role != expected_role:
        raise ProductionBinderV2Error(
            f"{context} evidence {ref_id} must have role {expected_role!r}"
        )
    if (
        artifact.relative_path != binding.relative_path
        or artifact.bytes != binding.bytes
        or artifact.sha256 != binding.sha256
    ):
        raise ProductionBinderV2Error(
            f"{context} evidence {ref_id} does not match the action sidecar artifact"
        )


def _validate_strict_sidecar_mirror(
    take_row: Mapping[str, Any],
    *,
    sidecar_file: _VerifiedFile,
    action_id: str,
    action_kind: str,
    context: str,
) -> None:
    """Keep the human-facing strict-sidecar descriptor in lockstep.

    T13 rows retain ``strict_action_sidecar`` for the capture audit while the
    public manifest consumes ``action_evidence``.  If both are present, a
    stale descriptor must fail closed instead of silently pointing at a
    different contract.
    """

    mirror_value = take_row.get("strict_action_sidecar")
    if mirror_value is None:
        return
    mirror = _mapping(mirror_value, f"{context}.strict_action_sidecar")
    mirror_action_id = _identifier(
        mirror.get("action_id"), f"{context}.strict_action_sidecar.action_id"
    )
    if mirror_action_id != action_id:
        raise ProductionBinderV2Error(
            f"{context}.strict_action_sidecar.action_id disagrees with action_evidence"
        )
    if mirror.get("action_kind") != action_kind:
        raise ProductionBinderV2Error(
            f"{context}.strict_action_sidecar.action_kind disagrees with action_evidence"
        )
    if mirror.get("status") != "passed":
        raise ProductionBinderV2Error(
            f"{context}.strict_action_sidecar.status must be 'passed'"
        )
    declared = _mapping(
        mirror.get("sidecar"), f"{context}.strict_action_sidecar.sidecar"
    )
    actual = sidecar_file.descriptor()
    if any(declared.get(field) != actual[field] for field in ("path", "bytes", "sha256")):
        raise ProductionBinderV2Error(
            f"{context}.strict_action_sidecar does not mirror action_evidence.sidecar"
        )


def _validate_contract_for_ui_action(
    contract: action_evidence_v2.ActionEvidenceContract,
    *,
    take_id: str,
    subshot_id: str,
    entry: Mapping[str, Any],
    capture: Mapping[str, str],
    recording: Mapping[str, object],
    hitbox: Mapping[str, int],
    visible_state_paths: Sequence[str],
    source_in: float,
    source_out: float,
    context: str,
) -> None:
    """Validate a non-formal, but still fully observed, UI action.

    This is intentionally separate from ``_validate_contract_for_step``.  A
    UI take has no ``formal_action_chain`` and therefore cannot satisfy a
    mechanism step by merely adding a compatible-looking entry.  The same
    capture identity, frame/time, pointer, state-delta, and staged-setup
    gates are retained for the independent UI branch.
    """

    action_kind = _identifier(entry.get("action_kind"), f"{context}.action_kind")
    if action_kind not in UI_ACTION_KINDS:
        raise ProductionBinderV2Error(
            f"{context}.action_kind must be one of {sorted(UI_ACTION_KINDS)!r}"
        )
    spec = _UI_ACTION_SPECS[action_kind]
    entry_field = spec[3]
    entry_value = _identifier(entry.get(entry_field), f"{context}.{entry_field}")
    if action_kind in {"buy_card", "choose_reward_card"} and not entry_value.startswith(
        "VIVHITE_CARD_"
    ):
        raise ProductionBinderV2Error(
            f"{context}.{entry_field} must be a Vivhite card identifier"
        )
    if spec[2] is not None and entry_value != spec[2]:
        raise ProductionBinderV2Error(
            f"{context}.{entry_field} must be {spec[2]!r}"
        )

    identity = contract.capture_identity
    for name, expected in capture.items():
        if getattr(identity, name) != expected:
            raise ProductionBinderV2Error(
                f"{context} capture identity does not match its source take"
            )
    if contract.take_id != take_id or contract.subshot_id != subshot_id:
        raise ProductionBinderV2Error(
            f"{context} take/subshot identity does not match storyboard binding"
        )
    if contract.action_kind != action_kind:
        raise ProductionBinderV2Error(
            f"{context} action kind does not match the UI-action entry"
        )

    payload = contract.action_receipt.payload
    target = _mapping(payload.get("target"), f"{context}.receipt.target")
    expected_target_kind, parameter_key, required_value, _entry_field = spec
    if target.get("kind") != expected_target_kind or target.get("id") != entry_value:
        raise ProductionBinderV2Error(
            f"{context} action target does not match the UI-action entry"
        )
    request = _mapping(payload.get("request"), f"{context}.receipt.request")
    parameters = _mapping(
        request.get("parameters"), f"{context}.receipt.request.parameters"
    )
    if parameters.get(parameter_key) != entry_value:
        raise ProductionBinderV2Error(
            f"{context} request parameter does not match the UI-action entry"
        )
    if required_value is not None and parameters.get(parameter_key) != required_value:
        raise ProductionBinderV2Error(
            f"{context} request parameter must be {required_value!r}"
        )

    pointer = _mapping(payload.get("pointer"), f"{context}.receipt.pointer")
    x = _integer(pointer.get("x"), f"{context}.receipt.pointer.x")
    y = _integer(pointer.get("y"), f"{context}.receipt.pointer.y")
    if not (
        hitbox["left"] <= x < hitbox["right"]
        and hitbox["top"] <= y < hitbox["bottom"]
    ):
        raise ProductionBinderV2Error(
            f"{context} pointer is outside its observed target hitbox"
        )

    start_frame = int(recording["start_frame"])
    end_frame = int(recording["end_frame"])
    if contract.recording_start_frame != start_frame:
        raise ProductionBinderV2Error(
            f"{context} recording_start_frame does not match source recording"
        )
    local_display_begin = start_frame + round(source_in * FPS)
    local_display_end = start_frame + round(source_out * FPS)
    if not (
        local_display_begin <= contract.display_span.begin_frame
        and contract.display_span.end_frame <= local_display_end
        and start_frame <= contract.display_span.begin_frame
        and contract.display_span.end_frame <= end_frame
    ):
        raise ProductionBinderV2Error(
            f"{context} action display span is not fully inside its EDL source span"
        )
    start_time = float(recording["started_monotonic_seconds"])
    stop_time = float(recording["stopped_monotonic_seconds"])
    if not (
        start_time <= contract.state_before.monotonic_seconds
        < contract.state_after.monotonic_seconds
        <= stop_time
    ):
        raise ProductionBinderV2Error(
            f"{context} action timestamps are outside the recording"
        )
    if contract.state_before.payload == contract.state_after.payload:
        raise ProductionBinderV2Error(
            f"{context} before/after state has no visible semantic change"
        )
    visible_deltas: list[str] = []
    for index, pointer_path in enumerate(visible_state_paths):
        before_value = _json_pointer(
            contract.state_before.payload,
            pointer_path,
            f"{context}.visible_state_paths[{index}] before",
        )
        after_value = _json_pointer(
            contract.state_after.payload,
            pointer_path,
            f"{context}.visible_state_paths[{index}] after",
        )
        if before_value != after_value:
            visible_deltas.append(pointer_path)
    if not visible_deltas:
        raise ProductionBinderV2Error(
            f"{context} proves no change on its declared visible_state_paths"
        )
    if contract.staged_setup is not None:
        if not contract.staged_setup.setup_end_frame < start_frame:
            raise ProductionBinderV2Error(
                f"{context} staged_setup reaches the recorded source"
            )


def _take_chain(value: Any, context: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    chain = _mapping(value, context)
    if not _list(chain.get("steps"), f"{context}.steps"):
        raise ProductionBinderV2Error(f"{context}.steps must not be empty")
    return chain


def _validate_chain_order(
    take_id: str,
    chain: Mapping[str, Any],
    contracts: Mapping[str, action_evidence_v2.ActionEvidenceContract],
) -> None:
    steps = _list(chain.get("steps"), f"storyboard take {take_id}.formal_action_chain.steps")
    for left, right in zip(steps, steps[1:]):
        left_id = str(left["step_id"])
        right_id = str(right["step_id"])
        previous = contracts[left_id]
        following = contracts[right_id]
        if not (
            previous.state_after.frame <= following.state_before.frame
            and previous.state_after.monotonic_seconds <= following.state_before.monotonic_seconds
            and previous.state_after.observation_seq <= following.state_before.observation_seq
        ):
            raise ProductionBinderV2Error(
                f"{take_id} formal actions are not a continuous ordered runtime chain"
            )
        if left.get("state_after_ref") == right.get("state_before_ref"):
            if _semantic_state(previous.state_after) != _semantic_state(following.state_before):
                raise ProductionBinderV2Error(
                    f"{take_id} shared state handoff is not the same observed snapshot"
                )
    handoff_value = chain.get("state_handoff")
    if handoff_value is not None:
        handoff = _mapping(handoff_value, f"storyboard take {take_id}.state_handoff")
        if handoff.get("must_be_identical_snapshot") is not True:
            raise ProductionBinderV2Error(f"{take_id} state handoff must require an identical snapshot")
        left_ref = handoff.get("left_ref")
        right_ref = handoff.get("right_ref")
        left_matches = [
            contracts[str(step["step_id"])].state_after
            for step in steps
            if step.get("state_after_ref") == left_ref
        ]
        right_matches = [
            contracts[str(step["step_id"])].state_before
            for step in steps
            if step.get("state_before_ref") == right_ref
        ]
        if len(left_matches) != 1 or len(right_matches) != 1:
            raise ProductionBinderV2Error(f"{take_id} state_handoff refs do not resolve once")
        if _semantic_state(left_matches[0]) != _semantic_state(right_matches[0]):
            raise ProductionBinderV2Error(f"{take_id} state_handoff snapshots are not identical")


def _positive_metric(value: Any, context: str) -> int:
    return _integer(value, context, minimum=1)


def _validate_crown_semantics(
    take_id: str,
    chain: Mapping[str, Any],
    contracts: Mapping[str, action_evidence_v2.ActionEvidenceContract],
) -> None:
    if take_id not in {"T14", "T15"}:
        return
    step = _list(chain["steps"], f"{take_id}.steps")[0]
    contract = contracts[str(step["step_id"])]
    before_payload = _mapping(contract.state_before.payload, f"{take_id}.state_before.payload")
    after_payload = _mapping(contract.state_after.payload, f"{take_id}.state_after.payload")
    run_before = _mapping(before_payload.get("run"), f"{take_id}.state_before.payload.run")
    run_after = _mapping(after_payload.get("run"), f"{take_id}.state_after.payload.run")
    before_hp = _integer(run_before.get("current_hp"), f"{take_id}.before.current_hp")
    max_hp = _integer(run_before.get("max_hp"), f"{take_id}.before.max_hp", minimum=1)
    after_hp = _integer(run_after.get("current_hp"), f"{take_id}.after.current_hp")
    if not before_hp < max_hp or not after_hp > before_hp:
        raise ProductionBinderV2Error(
            f"{take_id} must visibly recover real HP from a missing-HP state"
        )
    relics_value = before_payload.get("relics")
    if not isinstance(relics_value, (list, tuple)):
        raise ProductionBinderV2Error(
            f"{take_id}.state_before.payload.relics must be an array"
        )
    relics = list(relics_value)
    relic_ids = {
        item if isinstance(item, str) else _mapping(item, f"{take_id}.relic").get("id")
        for item in relics
    }
    if "VIVHITE_RELIC_ORIGIN_STAR_CHART" not in relic_ids:
        raise ProductionBinderV2Error(f"{take_id} does not prove Solitary Crown is present")
    observations = _mapping(
        after_payload.get("production_observations"),
        f"{take_id}.state_after.payload.production_observations",
    )
    drain = _positive_metric(observations.get("actual_drain_healing"), f"{take_id}.actual_drain_healing")
    crown = _positive_metric(
        observations.get("solitary_crown_actual_healing"),
        f"{take_id}.solitary_crown_actual_healing",
    )
    _positive_metric(observations.get("actual_draw_delta"), f"{take_id}.actual_draw_delta")
    _positive_metric(observations.get("actual_energy_gain"), f"{take_id}.actual_energy_gain")
    deaths = _integer(observations.get("enemy_deaths"), f"{take_id}.enemy_deaths", minimum=2)
    if deaths > 3:
        raise ProductionBinderV2Error(f"{take_id}.enemy_deaths must be in the director range 2..3")
    if after_hp - before_hp > drain + crown:
        raise ProductionBinderV2Error(
            f"{take_id} HP delta exceeds the proven Drain plus Solitary Crown healing"
        )
    event_order_value = observations.get("event_order")
    if not isinstance(event_order_value, (list, tuple)):
        raise ProductionBinderV2Error(f"{take_id}.event_order must be an array")
    event_order = list(event_order_value)
    required = (
        "drain_healing",
        "solitary_crown_recovery",
        "card_draw",
        "energy_gain",
    )
    try:
        positions = [event_order.index(item) for item in required]
    except ValueError as exc:
        raise ProductionBinderV2Error(f"{take_id} event_order lacks a required real event") from exc
    if not all(positions[0] < position for position in positions[1:]):
        raise ProductionBinderV2Error(f"{take_id} does not prove Drain before Crown/draw/energy")


def _validate_continuity_groups(
    board: Mapping[str, Any], bindings: Mapping[str, Mapping[str, Any]]
) -> None:
    groups: dict[str, list[tuple[float, str, Mapping[str, Any]]]] = {}
    for shot in board["shots"]:
        for subshot in shot["subshots"]:
            group = subshot.get("continuity_group")
            if group is None:
                continue
            subshot_id = str(subshot["subshot_id"])
            groups.setdefault(str(group), []).append(
                (float(subshot["timeline"]["start_seconds"]), subshot_id, bindings[subshot_id])
            )
    for group, rows in groups.items():
        rows.sort()
        take_ids = {str(row[2]["take_id"]) for row in rows}
        if len(rows) < 2 or len(take_ids) != 1:
            raise ProductionBinderV2Error(f"continuity group {group} must use one take across multiple subshots")
        for left, right in zip(rows, rows[1:]):
            if not math.isclose(
                float(left[2]["out_seconds"]),
                float(right[2]["in_seconds"]),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ProductionBinderV2Error(
                    f"continuity group {group} has a gap or overlap between {left[1]} and {right[1]}"
                )


def _bind_take(
    *,
    root: Path,
    take_row: Mapping[str, Any],
    board_take: Mapping[str, Any],
    board: Mapping[str, Any],
    normalized_take: Mapping[str, Any],
    bindings: Mapping[str, Mapping[str, Any]],
) -> _TakeRuntime:
    take_id = str(normalized_take["take_id"])
    context = f"take_manifest take {take_id}"
    source_row = _mapping(take_row.get("source", take_row.get("media")), f"{context}.source")
    source = _verify_file(
        root,
        {
            "path": source_row.get("artifact", source_row.get("path")),
            "bytes": source_row.get("bytes"),
            "sha256": source_row.get("sha256"),
        },
        f"{context}.source",
    )
    declared_duration = _number(source_row.get("duration_seconds"), f"{context}.source.duration_seconds", positive=True)
    probe_descriptor = _mapping(source_row.get("ffprobe"), f"{context}.source.ffprobe")
    probe_file = _verify_file(root, probe_descriptor, f"{context}.source.ffprobe", require_json=True)
    probe = _validate_source_probe(
        _read_verified_json(probe_file, f"{context}.source.ffprobe"),
        source=source,
        declared_duration=declared_duration,
        context=f"{context}.source.ffprobe",
    )
    capture = _capture_identity(source_row.get("capture_identity"), take_id, f"{context}.source.capture_identity")
    game_process = _process_identity(source_row.get("game_process"), f"{context}.source.game_process")
    recorder_process = _process_identity(source_row.get("recorder_process"), f"{context}.source.recorder_process")
    if game_process["identity"] != capture["game_process_id"]:
        raise ProductionBinderV2Error(f"{context} game PID/start identity is not bound to capture_identity")
    recording = _recording(
        source_row.get("recording"),
        frame_count=int(probe["frame_count"]),
        declared_duration=declared_duration,
        context=f"{context}.source.recording",
    )
    evidence_catalog = _evidence_catalog(root, take_row.get("evidence_refs"), context=f"{context}.evidence_refs")
    template_values = _template_values(
        take_row.get("template_values"),
        evidence=evidence_catalog,
        context=f"{context}.template_values",
    )
    chain = _take_chain(board_take.get("formal_action_chain"), f"storyboard take {take_id}.formal_action_chain")
    entries = _list(take_row.get("action_evidence", []), f"{context}.action_evidence")
    contracts: dict[str, action_evidence_v2.ActionEvidenceContract] = {}
    action_sidecars: dict[str, _VerifiedFile] = {}
    action_bindings: dict[str, Mapping[str, object]] = {}
    ui_action_step_ids: set[str] = set()
    if chain is None:
        # A UI gameplay take may opt into independently proven UI actions.  It
        # must never smuggle those entries into the formal mechanism ABI.
        if take_row.get("strict_action_sidecar") is not None and not entries:
            raise ProductionBinderV2Error(
                f"{context} strict_action_sidecar must be mapped into action_evidence"
            )
        if entries:
            board_asset_type = _text(
                board_take.get("asset_type"), f"storyboard take {take_id}.asset_type"
            )
            if board_asset_type not in UI_ACTION_ASSET_TYPES:
                raise ProductionBinderV2Error(
                    f"{context} UI action evidence requires a ui_gameplay/gameplay take"
                )
    else:
        expected_steps = {
            str(step["step_id"]): step
            for step in _list(chain["steps"], f"storyboard take {take_id}.steps")
        }
        if set(expected_steps) != {
            _identifier(
                _mapping(entry, f"{context}.action_evidence entry").get("step_id"),
                f"{context}.action_evidence.step_id",
            )
            for entry in entries
        }:
            raise ProductionBinderV2Error(
                f"{context}.action_evidence must bind every formal step exactly once"
            )
    seen_step_ids: set[str] = set()
    seen_action_ids: set[str] = set()
    seen_sidecar_paths: set[str] = set()
    staged_artifacts: set[tuple[str, str]] = set()
    if chain is None:
        for index, entry_value in enumerate(entries):
            entry_context = f"{context}.action_evidence[{index}]"
            entry = _mapping(entry_value, entry_context)
            step_id = _identifier(entry.get("step_id"), f"{entry_context}.step_id")
            if step_id in seen_step_ids:
                raise ProductionBinderV2Error(
                    f"{context}.action_evidence duplicates {step_id}"
                )
            seen_step_ids.add(step_id)
            action_id = _identifier(entry.get("action_id"), f"{entry_context}.action_id")
            if action_id in seen_action_ids:
                raise ProductionBinderV2Error(
                    f"{context}.action_evidence reuses action_id {action_id}"
                )
            seen_action_ids.add(action_id)
            action_kind = _identifier(entry.get("action_kind"), f"{entry_context}.action_kind")
            if action_kind not in UI_ACTION_KINDS:
                raise ProductionBinderV2Error(
                    f"{entry_context}.action_kind must be one of {sorted(UI_ACTION_KINDS)!r}"
                )
            subshot_id = _identifier(entry.get("subshot_id"), f"{entry_context}.subshot_id")
            owner_subshot = _ui_action_subshot(
                board, take_id=take_id, subshot_id=subshot_id, context=entry_context
            )
            binding = bindings.get(subshot_id)
            if binding is None:
                raise ProductionBinderV2Error(
                    f"{entry_context}.subshot_id is absent from normalized storyboard bindings"
                )
            before_ref = _identifier(
                entry.get("state_before_ref"), f"{entry_context}.state_before_ref"
            )
            receipt_ref = _identifier(
                entry.get("receipt_ref"), f"{entry_context}.receipt_ref"
            )
            after_ref = _identifier(
                entry.get("state_after_ref"), f"{entry_context}.state_after_ref"
            )
            owner_refs = {
                _identifier(ref, f"{entry_context}.owner.evidence_refs")
                for ref in _list(
                    owner_subshot.get("evidence_refs"),
                    f"{entry_context}.owner.evidence_refs",
                )
            }
            missing_owner_refs = sorted(
                {before_ref, receipt_ref, after_ref} - owner_refs
            )
            if missing_owner_refs:
                raise ProductionBinderV2Error(
                    f"{entry_context} action evidence is not declared by its UI owner: "
                    + ", ".join(missing_owner_refs)
                )
            sidecar_file = _verify_file(
                root,
                _mapping(entry.get("sidecar"), f"{entry_context}.sidecar"),
                f"{entry_context}.sidecar",
                require_json=True,
            )
            _validate_strict_sidecar_mirror(
                take_row,
                sidecar_file=sidecar_file,
                action_id=action_id,
                action_kind=action_kind,
                context=entry_context,
            )
            normalized_sidecar = os.path.normcase(str(sidecar_file.path.resolve()))
            if normalized_sidecar in seen_sidecar_paths:
                raise ProductionBinderV2Error(
                    f"{context}.action_evidence reuses one sidecar"
                )
            seen_sidecar_paths.add(normalized_sidecar)
            # This path-only call is intentional.  Never replace it with
            # validate_action_evidence(an_in_memory_mapping, ...).
            try:
                contract = action_evidence_v2.load_action_evidence(
                    sidecar_file.path, artifact_root=root
                )
            except action_evidence_v2.ActionEvidenceError as exc:
                raise ProductionBinderV2Error(
                    f"{entry_context} action contract failed: {exc}"
                ) from exc
            if contract.action_id != action_id:
                raise ProductionBinderV2Error(
                    f"{entry_context}.action_id does not match its sidecar"
                )
            if contract.action_kind != action_kind:
                raise ProductionBinderV2Error(
                    f"{entry_context}.action_kind does not match its sidecar"
                )
            _assert_action_artifact_ref(
                evidence_catalog,
                before_ref,
                contract.state_before.artifact,
                expected_role="state.before",
                context=entry_context,
            )
            _assert_action_artifact_ref(
                evidence_catalog,
                receipt_ref,
                contract.action_receipt.artifact,
                expected_role="action.receipt",
                context=entry_context,
            )
            _assert_action_artifact_ref(
                evidence_catalog,
                after_ref,
                contract.state_after.artifact,
                expected_role="state.after",
                context=entry_context,
            )
            hitbox = _hitbox(
                entry.get("pointer_hitbox"), f"{entry_context}.pointer_hitbox"
            )
            visible_state_paths = [
                _text(
                    pointer,
                    f"{entry_context}.visible_state_paths[{pointer_index}]",
                )
                for pointer_index, pointer in enumerate(
                    _list(
                        entry.get("visible_state_paths"),
                        f"{entry_context}.visible_state_paths",
                    )
                )
            ]
            if not visible_state_paths or len(visible_state_paths) != len(
                set(visible_state_paths)
            ):
                raise ProductionBinderV2Error(
                    f"{entry_context}.visible_state_paths must be non-empty and unique"
                )
            _validate_contract_for_ui_action(
                contract,
                take_id=take_id,
                subshot_id=subshot_id,
                entry=entry,
                capture=capture,
                recording=recording,
                hitbox=hitbox,
                visible_state_paths=visible_state_paths,
                source_in=float(binding["in_seconds"]),
                source_out=float(binding["out_seconds"]),
                context=entry_context,
            )
            contracts[step_id] = contract
            action_sidecars[step_id] = sidecar_file
            ui_action_step_ids.add(step_id)
            action_bindings[step_id] = MappingProxyType(
                {
                    "kind": ACTION_BINDING_KIND,
                    "step_id": step_id,
                    "action_id": action_id,
                    "subshot_id": subshot_id,
                    "action_kind": action_kind,
                    "formal_action": False,
                    "ui_action": True,
                    "sidecar": sidecar_file.descriptor(),
                    "pointer_hitbox": dict(hitbox),
                    "visible_state_paths": visible_state_paths,
                    "state_before_ref": before_ref,
                    "state_before": _artifact_summary(contract.state_before.artifact),
                    "receipt_ref": receipt_ref,
                    "action_receipt": _artifact_summary(contract.action_receipt.artifact),
                    "state_after_ref": after_ref,
                    "state_after": _artifact_summary(contract.state_after.artifact),
                }
            )
            if contract.staged_setup is not None:
                staged_artifacts.add(
                    (
                        str(contract.staged_setup.artifact.path.resolve()),
                        contract.staged_setup.artifact.sha256,
                    )
                )
    else:
        for index, entry_value in enumerate(entries):
            entry_context = f"{context}.action_evidence[{index}]"
            entry = _mapping(entry_value, entry_context)
            step_id = _identifier(entry.get("step_id"), f"{entry_context}.step_id")
            if step_id in seen_step_ids:
                raise ProductionBinderV2Error(f"{context}.action_evidence duplicates {step_id}")
            seen_step_ids.add(step_id)
            action_id = _identifier(entry.get("action_id"), f"{entry_context}.action_id")
            if action_id in seen_action_ids:
                raise ProductionBinderV2Error(f"{context}.action_evidence reuses action_id {action_id}")
            seen_action_ids.add(action_id)
            sidecar_file = _verify_file(
                root,
                _mapping(entry.get("sidecar"), f"{entry_context}.sidecar"),
                f"{entry_context}.sidecar",
                require_json=True,
            )
            normalized_sidecar = os.path.normcase(str(sidecar_file.path.resolve()))
            if normalized_sidecar in seen_sidecar_paths:
                raise ProductionBinderV2Error(f"{context}.action_evidence reuses one sidecar")
            seen_sidecar_paths.add(normalized_sidecar)
            # This path-only call is intentional.  Never replace it with
            # validate_action_evidence(an_in_memory_mapping, ...).
            try:
                contract = action_evidence_v2.load_action_evidence(
                    sidecar_file.path, artifact_root=root
                )
            except action_evidence_v2.ActionEvidenceError as exc:
                raise ProductionBinderV2Error(f"{entry_context} action contract failed: {exc}") from exc
            if contract.action_id != action_id:
                raise ProductionBinderV2Error(f"{entry_context}.action_id does not match its sidecar")
            step = expected_steps[step_id]
            receipt_ref = _identifier(step.get("receipt_ref"), f"{entry_context}.receipt_ref")
            before_ref = _identifier(step.get("state_before_ref"), f"{entry_context}.state_before_ref")
            after_ref = _identifier(step.get("state_after_ref"), f"{entry_context}.state_after_ref")
            for ref in (receipt_ref, before_ref, after_ref):
                if ref not in evidence_catalog:
                    raise ProductionBinderV2Error(f"{entry_context} refers to absent evidence {ref}")
            subshot_id = _step_subshot(board, take_id=take_id, receipt_ref=receipt_ref)
            binding = bindings[subshot_id]
            hitbox = _hitbox(entry.get("pointer_hitbox"), f"{entry_context}.pointer_hitbox")
            visible_state_paths = [
                _text(pointer, f"{entry_context}.visible_state_paths[{pointer_index}]")
                for pointer_index, pointer in enumerate(
                    _list(entry.get("visible_state_paths"), f"{entry_context}.visible_state_paths")
                )
            ]
            if not visible_state_paths or len(visible_state_paths) != len(set(visible_state_paths)):
                raise ProductionBinderV2Error(
                    f"{entry_context}.visible_state_paths must be non-empty and unique"
                )
            _validate_contract_for_step(
                contract,
                take_id=take_id,
                subshot_id=subshot_id,
                step=step,
                capture=capture,
                recording=recording,
                hitbox=hitbox,
                visible_state_paths=visible_state_paths,
                source_in=float(binding["in_seconds"]),
                source_out=float(binding["out_seconds"]),
                context=entry_context,
            )
            contracts[step_id] = contract
            action_sidecars[step_id] = sidecar_file
            action_bindings[step_id] = MappingProxyType(
                {
                    "kind": ACTION_BINDING_KIND,
                    "step_id": step_id,
                    "action_id": action_id,
                    "subshot_id": subshot_id,
                    "sidecar": sidecar_file.descriptor(),
                    "pointer_hitbox": dict(hitbox),
                    "visible_state_paths": visible_state_paths,
                    "state_before_ref": before_ref,
                    "state_before": _artifact_summary(contract.state_before.artifact),
                    "receipt_ref": receipt_ref,
                    "action_receipt": _artifact_summary(contract.action_receipt.artifact),
                    "state_after_ref": after_ref,
                    "state_after": _artifact_summary(contract.state_after.artifact),
                }
            )
            if contract.staged_setup is not None:
                staged_artifacts.add(
                    (str(contract.staged_setup.artifact.path.resolve()), contract.staged_setup.artifact.sha256)
                )
    if chain is not None:
        _validate_chain_order(take_id, chain, contracts)
        _validate_crown_semantics(take_id, chain, contracts)
    for _ref_id, (_role, artifact) in evidence_catalog.items():
        if (str(artifact.path.resolve()), artifact.sha256) in staged_artifacts:
            raise ProductionBinderV2Error(f"{context} exposes a staged_setup artifact as EDL evidence")
    return _TakeRuntime(
        take_id,
        source,
        probe_file,
        probe,
        capture,
        recording,
        game_process,
        recorder_process,
        MappingProxyType({key: item[1] for key, item in evidence_catalog.items()}),
        template_values,
        MappingProxyType(action_sidecars),
        MappingProxyType(contracts),
        MappingProxyType(action_bindings),
        frozenset(ui_action_step_ids),
    )


def build_production_edl_v2(
    storyboard_path: str | Path,
    take_manifest_path: str | Path,
    *,
    artifact_root: str | Path,
    edit_id: str = "master-540",
) -> dict[str, Any]:
    """Build a byte-, probe-, process-, and action-verified v2 production EDL.

    Both top-level inputs must be real JSON paths.  Formal action evidence is
    likewise accepted only by sidecar path and is always loaded with
    :func:`action_evidence_v2.load_action_evidence`.
    """

    root = _artifact_root(artifact_root)
    board, board_descriptor, board_file, board_signature = _read_input_json(
        storyboard_path, "storyboard"
    )
    manifest, manifest_descriptor, manifest_file, manifest_signature = _read_input_json(
        take_manifest_path, "take manifest"
    )
    try:
        normalized = director_v2.validate_take_manifest(board, manifest)
        edl = director_v2.build_multitake_edl(board, manifest, edit_id=edit_id)
    except director_v2.DirectorV2Error as exc:
        raise ProductionBinderV2Error(f"director-v2 declaration failed: {exc}") from exc
    board_takes = {str(row["take_id"]): row for row in board["takes"]}
    manifest_takes = {str(row["take_id"]): row for row in manifest["takes"]}
    production_run_id = _identifier(manifest.get("run_id"), "take_manifest.run_id")
    runtimes: dict[str, _TakeRuntime] = {}
    for take_id, normalized_take in normalized["takes"].items():
        runtimes[take_id] = _bind_take(
            root=root,
            take_row=manifest_takes[take_id],
            board_take=board_takes[take_id],
            board=board,
            normalized_take=normalized_take,
            bindings=normalized["bindings"],
        )
        if runtimes[take_id].capture_identity["run_id"] != production_run_id:
            raise ProductionBinderV2Error(
                f"take {take_id} capture run_id does not match take_manifest.run_id"
            )
    source_artifact_ids = [
        runtime.capture_identity["source_video_artifact_id"]
        for runtime in runtimes.values()
    ]
    if len(source_artifact_ids) != len(set(source_artifact_ids)):
        raise ProductionBinderV2Error(
            "independent takes must use distinct source_video_artifact_id values"
        )
    _validate_continuity_groups(board, normalized["bindings"])

    storyboard_subshots = {
        str(subshot["subshot_id"]): subshot
        for shot in board["shots"]
        for subshot in shot["subshots"]
    }

    subshot_actions: dict[str, list[Mapping[str, object]]] = {}
    staged_paths: set[str] = set()
    for runtime in runtimes.values():
        for binding in runtime.action_bindings.values():
            subshot_actions.setdefault(str(binding["subshot_id"]), []).append(binding)
        for contract in runtime.action_contracts.values():
            if contract.staged_setup is not None:
                staged_paths.add(str(contract.staged_setup.artifact.path.resolve()))

    for segment in edl["segments"]:
        storyboard_subshot = storyboard_subshots[str(segment["subshot_id"])]
        if "visual_requirements" in storyboard_subshot:
            segment["visual_requirements"] = copy.deepcopy(
                storyboard_subshot["visual_requirements"]
            )
        if "montage_lineage" in storyboard_subshot:
            segment["montage_lineage"] = copy.deepcopy(
                storyboard_subshot["montage_lineage"]
            )
        source = segment["source"]
        asset_type = str(segment["asset_type"])
        if source["kind"] != "video_take":
            continue
        take_id = str(source["take_id"])
        runtime = runtimes[take_id]
        source.update(
            {
                "verification": PRODUCTION_STATUS,
                "probe": dict(runtime.probe),
                "probe_artifact": runtime.probe_file.descriptor(),
                "capture_identity": dict(runtime.capture_identity),
                "game_process": dict(runtime.game_process),
                "recorder_process": dict(runtime.recorder_process),
                "recording": dict(runtime.recording),
            }
        )
        selected: list[dict[str, object]] = []
        for ref_id in segment["evidence_refs"]:
            artifact = runtime.evidence[str(ref_id)]
            if str(artifact.path.resolve()) in staged_paths:
                raise ProductionBinderV2Error(
                    f"segment {segment['subshot_id']} would expose staged_setup evidence"
                )
            selected.append({"ref_id": ref_id, **artifact.descriptor()})
        segment["evidence_bindings"] = selected
        action_rows = [dict(row) for row in subshot_actions.get(str(segment["subshot_id"]), [])]
        lineage_value = storyboard_subshot.get("montage_lineage")
        if lineage_value is not None:
            lineage = _mapping(
                lineage_value,
                f"segment {segment['subshot_id']}.montage_lineage",
            )
            owner_id = str(lineage["source_subshot_id"])
            owner_actions = [
                dict(row) for row in subshot_actions.get(owner_id, [])
            ]
            if not owner_actions:
                raise ProductionBinderV2Error(
                    f"montage segment {segment['subshot_id']} lacks a verified formal "
                    f"source action at {owner_id}"
                )
            selected_files = {
                (str(row["path"]), str(row["sha256"]).upper())
                for row in selected
            }
            receipt_files = {
                (
                    str(_mapping(row["action_receipt"], "action_receipt")["path"]),
                    str(_mapping(row["action_receipt"], "action_receipt")["sha256"]).upper(),
                )
                for row in owner_actions
            }
            if selected_files & receipt_files:
                raise ProductionBinderV2Error(
                    f"montage segment {segment['subshot_id']} exposes its source formal "
                    "action receipt instead of visual/event lineage evidence"
                )
        is_formal = asset_type == "mechanism_action" and source.get("resolved_semantics") == "formal_action"
        if is_formal and not action_rows:
            raise ProductionBinderV2Error(
                f"mechanism segment {segment['subshot_id']} lacks path-loaded formal action evidence"
            )
        segment["formal_action_claimed"] = bool(is_formal)
        if action_rows:
            segment["action_bindings"] = action_rows
            if asset_type in UI_ACTION_ASSET_TYPES:
                # ``director_v2`` uses ``resolved_semantics=formal_action``
                # for every non-fallback capture span.  Keep that declaration
                # ABI intact, but expose the binder's independent UI branch
                # explicitly so downstream audit/render code cannot infer a
                # mechanism chain from the source label alone.
                segment["ui_action_claimed"] = True

    cue_to_subshot = {
        str(subshot["cue"]["cue_id"]): subshot
        for subshot in storyboard_subshots.values()
    }
    segment_by_id = {str(segment["segment_id"]): segment for segment in edl["segments"]}
    for cue_row in edl["cues"]:
        source_cue = cue_to_subshot[str(cue_row["cue_id"])]["cue"]
        if "template_fields" not in source_cue:
            continue
        fields = [
            _identifier(value, f"cue {cue_row['cue_id']}.template_fields")
            for value in _list(source_cue["template_fields"], f"cue {cue_row['cue_id']}.template_fields")
        ]
        evidence_map = _mapping(
            source_cue.get("template_evidence"),
            f"cue {cue_row['cue_id']}.template_evidence",
        )
        segment = segment_by_id[str(cue_row["segment_id"])]
        take_id = segment["source"].get("take_id")
        if take_id is None:
            raise ProductionBinderV2Error(f"templated cue {cue_row['cue_id']} must use a verified take")
        runtime = runtimes[str(take_id)]
        values: dict[str, str] = {}
        for field in fields:
            if field not in runtime.template_values:
                raise ProductionBinderV2Error(
                    f"templated cue {cue_row['cue_id']} lacks observed value for {field}"
                )
            binding = runtime.template_values[field]
            if evidence_map.get(field) != binding["evidence_ref"]:
                raise ProductionBinderV2Error(
                    f"templated cue {cue_row['cue_id']} evidence ref disagrees for {field}"
                )
            values[field] = binding["value"]
        cue_row["template_fields"] = fields
        cue_row["template_evidence"] = copy.deepcopy(dict(evidence_map))
        cue_row["template_values"] = values

    # Recheck every file identity after the semantic work.  Large media is
    # hashed once, then protected against in-call replacement by its stable
    # filesystem identity and timestamps.
    checked: dict[str, _VerifiedFile] = {}
    for runtime in runtimes.values():
        for artifact in (
            runtime.source,
            runtime.probe_file,
            *runtime.evidence.values(),
            *runtime.action_sidecars.values(),
        ):
            checked[str(artifact.path)] = artifact
        for contract in runtime.action_contracts.values():
            try:
                contract.verify_unchanged()
            except action_evidence_v2.ActionEvidenceError as exc:
                raise ProductionBinderV2Error(f"action evidence changed while binding: {exc}") from exc
    for artifact in checked.values():
        artifact.assert_unchanged()
    for path, signature, label in (
        (board_file, board_signature, "storyboard"),
        (manifest_file, manifest_signature, "take manifest"),
    ):
        if _stat_signature(os.stat(path, follow_symlinks=False)) != signature:
            raise ProductionBinderV2Error(f"{label} changed while binding")

    edl["authoring"].update(
        {
            "offline_only": False,
            "status": PRODUCTION_STATUS,
            "source_verification": "bytes_sha256_ffprobe_verified",
            "action_evidence_verification": "path_loaded_and_hash_bound",
            "production_file_verification_required": False,
            "verified_source_count": len(runtimes),
            "verified_formal_action_count": sum(
                len(runtime.action_contracts) - len(runtime.ui_action_step_ids)
                for runtime in runtimes.values()
            ),
            "verified_ui_action_count": sum(
                len(runtime.ui_action_step_ids) for runtime in runtimes.values()
            ),
        }
    )
    edl["production_binding"] = {
        "storyboard": board_descriptor,
        "take_manifest": manifest_descriptor,
        "artifact_root": str(root),
        "run_id": production_run_id,
        "staged_setup_in_edl": False,
    }
    return copy.deepcopy(edl)


build_production_edl = build_production_edl_v2


def write_production_edl_v2(
    storyboard_path: str | Path,
    take_manifest_path: str | Path,
    *,
    artifact_root: str | Path,
    output_relative_path: str,
    edit_id: str = "master-540",
) -> Mapping[str, object]:
    """Bind and write one new production EDL without overwriting an attempt."""

    root = _artifact_root(artifact_root)
    relative = _relative_path(output_relative_path, "output_relative_path")
    parent = root.joinpath(*PurePosixPath(relative).parts[:-1])
    try:
        resolved_parent = parent.resolve(strict=True)
        resolved_parent.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProductionBinderV2Error(
            "output parent must already exist inside artifact_root"
        ) from exc
    metadata = _reject_link_or_reparse(resolved_parent, "output parent")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ProductionBinderV2Error("output parent must be a directory")
    output = resolved_parent / PurePosixPath(relative).name
    if output.exists() or output.is_symlink():
        raise ProductionBinderV2Error(f"production EDL output already exists: {relative}")
    edl = build_production_edl_v2(
        storyboard_path,
        take_manifest_path,
        artifact_root=root,
        edit_id=edit_id,
    )
    data = (json.dumps(edl, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        with output.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ProductionBinderV2Error(
            f"production EDL output already exists: {relative}"
        ) from exc
    except OSError as exc:
        raise ProductionBinderV2Error(f"could not write production EDL {relative}: {exc}") from exc
    return {
        "path": relative,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "status": PRODUCTION_STATUS,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--take-manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", required=True, help="new path relative to artifact root")
    parser.add_argument("--edit-id", default="master-540")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    receipt = write_production_edl_v2(
        args.storyboard,
        args.take_manifest,
        artifact_root=args.artifact_root,
        output_relative_path=args.output,
        edit_id=args.edit_id,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = [
    "PRODUCTION_STATUS",
    "SOURCE_PROBE_KIND",
    "ACTION_BINDING_KIND",
    "UI_ACTION_KINDS",
    "UI_ACTION_ASSET_TYPES",
    "ProductionBinderV2Error",
    "build_production_edl_v2",
    "build_production_edl",
    "write_production_edl_v2",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
