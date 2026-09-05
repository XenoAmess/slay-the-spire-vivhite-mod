"""Archive and bind the accepted T17/a02 crimson-route card-library capture.

The operation is append-only.  It preserves the sealed OBS source byte for
byte, extracts exact frame anchors, snapshots the active runtime's 61-card
dump, and validates the resulting row through the production binder.  T17 has
no formal action chain, so the scroll/hover operator marks are audit context
only and action_evidence remains empty.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


REPO = pathlib.Path(__file__).resolve().parents[2]
RUN_ID = "run-20260903T0012-director-v2-a1"
RUN = REPO / "tools" / "promo" / "runs" / RUN_ID
TAKE_ID = "T17"
ATTEMPT_ID = "a02"
EXTERNAL_RAW = pathlib.Path(
    r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T17\a02\2026-09-04 21-13-24.mkv"
)
RAW = RUN / "raw" / "takes" / TAKE_ID / f"{ATTEMPT_ID}.mkv"
STORYBOARD = REPO / "tools" / "promo" / "v2" / "storyboard.json"
RUNBOOK = REPO / "tools" / "promo" / "v2" / "capture-runbook.json"
FFPROBE = pathlib.Path(r"C:\ffmpeg\bin\ffprobe.exe")
FFMPEG = pathlib.Path(r"C:\ffmpeg\bin\ffmpeg.exe")
GAME_LOG = pathlib.Path.home() / "AppData" / "Roaming" / "SlayTheSpire2" / "logs" / "godot.log"
DEPLOYED = pathlib.Path(r"G:\SteamLibrary\steamapps\common\Slay the Spire 2\mods\Vivhite")
LOCALIZATION = REPO / "Vivhite" / "Vivhite" / "localization" / "zhs" / "cards.json"
TARGET_SOURCE = REPO / "Vivhite" / "VivhiteCode" / "Cards" / "Chromatic" / "TrichromaticWaltz.cs"

EXPECTED_BYTES = 18_667_603
EXPECTED_SHA256 = "B59FEA6448108578FBB068053D6480A7874CE4B3A7130931C835633BDE12CD1C"
EXPECTED_FRAMES = 728
FPS = 60
SOURCE_DURATION = EXPECTED_FRAMES / FPS
OWNER_BEGIN = 0
OWNER_END = 720
OWNER_IN = OWNER_BEGIN / FPS
OWNER_OUT = OWNER_END / FPS
GAME_PROCESS_ID = "SlayTheSpire2.exe-16428-2026-09-03T14-12-39.1941103Z"
GAME_STARTED_UTC = "2026-09-03T14:12:39.1941103Z"
RECORDER_PROCESS_ID = "obs64.exe-17432-2026-09-04T13-12-31.1174768Z"
RECORDER_STARTED_UTC = "2026-09-04T13:12:31.1174768Z"
GAME_RUN_ID = "native-vivhite-card-library"
SOURCE_ARTIFACT_ID = "T17-a02-B59FEA6448108578"
ANCHOR_FRAMES = (0, 150, 300, 400, 540, 719)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def rel(path: pathlib.Path) -> str:
    return path.relative_to(RUN).as_posix()


def descriptor(path: pathlib.Path, **extra: Any) -> dict[str, Any]:
    return {"path": rel(path), "bytes": path.stat().st_size, "sha256": sha256(path), **extra}


def write_bytes(path: pathlib.Path, data: bytes) -> None:
    """Create an immutable artifact; allow only a byte-identical rerun."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f"refusing to overwrite differing artifact: {path}")
        return
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()


def write_json(path: pathlib.Path, payload: Any) -> None:
    write_bytes(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def copy_immutable(source: pathlib.Path, target: pathlib.Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"required source is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size != source.stat().st_size or sha256(target) != sha256(source):
            raise RuntimeError(f"refusing to replace differing preserved artifact: {target}")
        return
    with source.open("rb") as source_stream, target.open("xb") as target_stream:
        shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
        target_stream.flush()


def run_json(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("tool JSON root is not an object")
    return value


def exact_probe(path: pathlib.Path) -> dict[str, Any]:
    return run_json(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-count_frames",
            "-count_packets",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )


def extract_anchors(source: pathlib.Path, output_dir: pathlib.Path) -> dict[int, pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = [output_dir / f"selected-{index:02d}.png" for index in range(1, len(ANCHOR_FRAMES) + 1)]
    if not all(path.exists() for path in expected):
        if any(path.exists() for path in expected):
            raise RuntimeError("partial T17 anchor extraction exists; refusing ambiguous rerun")
        expression = "+".join(f"eq(n\\,{frame})" for frame in ANCHOR_FRAMES)
        subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-i",
                str(source),
                "-vf",
                f"select={expression}",
                "-fps_mode",
                "passthrough",
                str(output_dir / "selected-%02d.png"),
            ],
            check=True,
        )
    if not all(path.is_file() and path.stat().st_size > 0 for path in expected):
        raise RuntimeError("exact source-frame extraction did not emit every T17 anchor")
    return dict(zip(ANCHOR_FRAMES, expected, strict=True))


def capture_identity() -> dict[str, str]:
    return {
        "session_id": RUN_ID,
        "game_run_id": GAME_RUN_ID,
        "game_process_id": GAME_PROCESS_ID,
        "source_video_artifact_id": SOURCE_ARTIFACT_ID,
        "run_id": RUN_ID,
        "take_id": TAKE_ID,
    }


def evidence_ref(ref_id: str, role: str, path: pathlib.Path) -> dict[str, Any]:
    return {"ref_id": ref_id, "role": role, "status": "verified", **descriptor(path)}


def parse_runtime_cards(log_bytes: bytes) -> list[dict[str, Any]]:
    text = log_bytes.decode("utf-8-sig", errors="strict")
    matches = [
        {"runtime_index": int(index), "content_id": content_id}
        for index, content_id in re.findall(r"(?m)^(\d+): (VIVHITE_CARD_[A-Z0-9_]+)\r?$", text)
        if content_id != "VIVHITE_CARD_POOL"
    ]
    if len(matches) != 61:
        raise RuntimeError(f"current runtime log must contain exactly 61 Vivhite card IDs, found {len(matches)}")
    if [row["runtime_index"] for row in matches] != list(range(613, 674)):
        raise RuntimeError("current runtime card dump is not the expected contiguous 613..673 block")
    ids = [str(row["content_id"]) for row in matches]
    if len(set(ids)) != 61:
        raise RuntimeError("current runtime card dump contains duplicate Vivhite card IDs")
    forbidden = {
        "VIVHITE_CARD_VIVHITE_STRIKE",
        "VIVHITE_CARD_VIVHITE_DEFENSE",
        "VIVHITE_CARD_WHITE_SILK_KNOT",
    }
    present = sorted(forbidden.intersection(ids))
    if present:
        raise RuntimeError(f"deprecated placeholder cards are present: {present}")
    required = {"VIVHITE_CARD_TRICHROMATIC_WALTZ", "VIVHITE_CARD_COMPOSITE_COLOR_WHEEL"}
    missing = sorted(required.difference(ids))
    if missing:
        raise RuntimeError(f"current runtime dump is missing route cards: {missing}")
    return matches


def main() -> int:
    source_probe_path = RUN / "probe" / "takes" / TAKE_ID / ATTEMPT_ID / "source-probe.json"
    observed_at = (
        str(json.loads(source_probe_path.read_text(encoding="utf-8-sig"))["observed_at_utc"])
        if source_probe_path.exists()
        else utc_now()
    )
    for tool in (FFPROBE, FFMPEG):
        if not tool.is_file():
            raise RuntimeError(f"required media tool is missing: {tool}")
    if EXTERNAL_RAW.stat().st_size != EXPECTED_BYTES or sha256(EXTERNAL_RAW) != EXPECTED_SHA256:
        raise RuntimeError("sealed T17/a02 OBS source no longer matches its capture receipt")

    copy_immutable(EXTERNAL_RAW, RAW)
    if RAW.stat().st_size != EXPECTED_BYTES or sha256(RAW) != EXPECTED_SHA256:
        raise RuntimeError("preserved T17/a02 raw is not byte-identical to the sealed OBS source")

    capture_dir = RUN / "capture" / "takes" / TAKE_ID / ATTEMPT_ID
    evidence_dir = RUN / "evidence" / "takes" / TAKE_ID / ATTEMPT_ID
    probe_dir = RUN / "probe" / "takes" / TAKE_ID / ATTEMPT_ID
    live_dir = evidence_dir / "live"
    for name in (
        "operator-marks.json",
        "checkpoint-before-mark.png",
        "operator-frame-begin.png",
        "operator-frame-end.png",
    ):
        copy_immutable(capture_dir / name, live_dir / name)

    anchors = extract_anchors(RAW, evidence_dir / "anchors")
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(RAW), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "NUL"],
        check=True,
    )
    probe_raw = exact_probe(RAW)
    streams = probe_raw.get("streams", [])
    video = next(item for item in streams if item.get("codec_type") == "video")
    audio = next(item for item in streams if item.get("codec_type") == "audio")
    fmt = probe_raw["format"]
    frame_count = int(video["nb_read_frames"])
    if frame_count != EXPECTED_FRAMES:
        raise RuntimeError(f"T17/a02 decoded frame count changed: {frame_count}")
    if int(video["nb_read_packets"]) != EXPECTED_FRAMES:
        raise RuntimeError("T17/a02 video packet count does not match decoded frame count")

    source_probe = {
        "schema_version": 2,
        "kind": "vivhite_promo_source_probe_v2",
        "status": "completed",
        "observed_at_utc": observed_at,
        "source": {"path": rel(RAW), "bytes": EXPECTED_BYTES, "sha256": EXPECTED_SHA256},
        "result": {
            "streams": [video, audio],
            "format": {
                "format_name": fmt["format_name"],
                "start_time": fmt["start_time"],
                "duration": fmt["duration"],
                "size": fmt["size"],
                "bit_rate": fmt.get("bit_rate"),
            },
        },
        "derived": {
            "decoded_video_frames": frame_count,
            "frame_duration_seconds": SOURCE_DURATION,
            "ffprobe_reported_duration_seconds": float(fmt["duration"]),
            "container_minus_video_frame_duration_seconds": float(fmt["duration"]) - SOURCE_DURATION,
            "video_packets": int(video["nb_read_packets"]),
            "audio_packets": int(audio["nb_read_packets"]),
            "audio_frames": int(audio["nb_read_frames"]),
            "full_decode_status": "passed_no_errors",
            "blackdetect_status": "not_claimed; sampled visual review recorded separately",
            "freezedetect_status": "not_claimed; static tooltip holds are intentional",
        },
        "tools": {
            "ffprobe": {"path": str(FFPROBE), "sha256": sha256(FFPROBE)},
            "ffmpeg": {"path": str(FFMPEG), "sha256": sha256(FFMPEG)},
        },
    }
    write_json(source_probe_path, source_probe)

    log_snapshot = evidence_dir / "runtime-godot-log.snapshot.txt"
    if log_snapshot.exists():
        log_bytes = log_snapshot.read_bytes()
    else:
        log_bytes = GAME_LOG.read_bytes()
        write_bytes(log_snapshot, log_bytes)
    cards = parse_runtime_cards(log_bytes)
    card_ids = {str(row["content_id"]) for row in cards}
    localization = json.loads(LOCALIZATION.read_text(encoding="utf-8-sig"))
    route_cards = [
        {
            "content_id": "VIVHITE_CARD_TRICHROMATIC_WALTZ",
            "localized_title": localization["VIVHITE_CARD_TRICHROMATIC_WALTZ.title"],
            "visible_role": "hovered_core_card",
        },
        {
            "content_id": "VIVHITE_CARD_COMPOSITE_COLOR_WHEEL",
            "localized_title": localization["VIVHITE_CARD_COMPOSITE_COLOR_WHEEL.title"],
            "visible_role": "adjacent_route_card",
        },
    ]
    if [row["localized_title"] for row in route_cards] != ["三色轮舞", "综合色轮"]:
        raise RuntimeError("current Chinese localization changed for the two visually bound route cards")
    if any(row["content_id"] not in card_ids for row in route_cards):
        raise RuntimeError("visually bound route card is absent from the current runtime dump")
    deployed_files = []
    for name in ("Vivhite.dll", "Vivhite.json", "Vivhite.pck"):
        path = DEPLOYED / name
        deployed_files.append(
            {"name": name, "path": path.as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
        )

    runtime_manifest_path = evidence_dir / "runtime-manifest.json"
    runtime_manifest = {
        "schema_version": 2,
        "kind": "vivhite_promo_runtime_manifest_v2",
        "status": "verified_current_process_runtime_dump_and_route_cards",
        "ref_id": "T17-runtime-manifest",
        "role": "runtime.manifest",
        "capture_identity": capture_identity(),
        "observed_at_utc": observed_at,
        "game_process": {"pid": 16428, "identity": GAME_PROCESS_ID, "started_utc": GAME_STARTED_UTC},
        "runtime_dump": {
            "artifact": descriptor(log_snapshot, media_type="text/plain"),
            "numeric_range_inclusive": [613, 673],
            "card_count": len(cards),
            "cards": cards,
            "unique_content_ids": len(card_ids),
            "deprecated_placeholders_present": [],
        },
        "route_cards": route_cards,
        "implementation_evidence": {
            "target_source": {
                "path": TARGET_SOURCE.relative_to(REPO).as_posix(),
                "bytes": TARGET_SOURCE.stat().st_size,
                "sha256": sha256(TARGET_SOURCE),
                "registered_pool": "VivhiteCardPool",
            },
            "localization": {
                "path": LOCALIZATION.relative_to(REPO).as_posix(),
                "bytes": LOCALIZATION.stat().st_size,
                "sha256": sha256(LOCALIZATION),
            },
        },
        "deployed_artifacts": deployed_files,
        "conclusion": "The active process exposes 61 unique current Vivhite cards; 三色轮舞 and 综合色轮 are present and deprecated placeholders are absent.",
    }
    write_json(runtime_manifest_path, runtime_manifest)

    common_source = {
        "path": rel(RAW),
        "bytes": EXPECTED_BYTES,
        "sha256": EXPECTED_SHA256,
        "decoded_frames": EXPECTED_FRAMES,
        "fps": FPS,
    }
    frame_begin_path = evidence_dir / "frame-begin.json"
    frame_end_path = evidence_dir / "frame-end.json"
    write_json(
        frame_begin_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_frame_marker_v2",
            "status": "verified",
            "ref_id": "T17-frame-begin",
            "role": "frame.begin",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "source": common_source,
            "frame": {
                "source_zero_based": OWNER_BEGIN,
                "time_seconds": OWNER_IN,
                "owner_interval_half_open": [OWNER_BEGIN, OWNER_END],
                "artifact": descriptor(anchors[OWNER_BEGIN], media_type="image/png"),
            },
            "visible": {
                "screen": "CARD_LIBRARY",
                "route_cards_readable": ["三色轮舞", "综合色轮"],
                "clean_game_only_surface": True,
            },
        },
    )
    write_json(
        frame_end_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_frame_marker_v2",
            "status": "verified",
            "ref_id": "T17-frame-end",
            "role": "frame.end",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "source": common_source,
            "frame": {
                "source_zero_based": OWNER_END - 1,
                "time_seconds": (OWNER_END - 1) / FPS,
                "owner_interval_half_open": [OWNER_BEGIN, OWNER_END],
                "artifact": descriptor(anchors[OWNER_END - 1], media_type="image/png"),
            },
            "visible": {
                "screen": "CARD_LIBRARY",
                "hovered_card": "三色轮舞",
                "clean_game_only_surface": True,
            },
        },
    )

    operator_marks = json.loads((live_dir / "operator-marks.json").read_text(encoding="utf-8-sig"))
    start_mark = operator_marks["recording"]["start_request"]
    stop_mark = operator_marks["recording"]["stop_request"]
    operator_control_seconds = (
        int(stop_mark["monotonic_tick"]) - int(start_mark["monotonic_tick"])
    ) / int(start_mark["stopwatch_frequency"])
    boundary_path = evidence_dir / "recording-boundary.json"
    write_json(
        boundary_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_recording_boundary_v2",
            "status": "passed_source_local_with_operator_control_disclosure",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "operator_receipt": descriptor(live_dir / "operator-marks.json"),
            "decoded_source_bounds": {
                "start_frame": 1,
                "end_frame_exclusive": EXPECTED_FRAMES + 1,
                "decoded_frame_count": EXPECTED_FRAMES,
                "exact_decoded_duration_seconds": SOURCE_DURATION,
                "container_duration_seconds": float(fmt["duration"]),
                "recording_started_monotonic_seconds": 0.0,
                "recording_stopped_monotonic_seconds": SOURCE_DURATION,
                "coordinate_system": "source-local decoded media time",
                "formal_owner_interval_zero_based": [OWNER_BEGIN, OWNER_END],
            },
            "operator_control": {
                "start_request": start_mark,
                "stop_request": stop_mark,
                "request_interval_seconds": operator_control_seconds,
                "request_minus_decoded_seconds": operator_control_seconds - SOURCE_DURATION,
                "interpretation": "UI Automation request marks are preserved but are not decoded media PTS boundaries.",
            },
        },
    )

    lineage_path = evidence_dir / "lineage.json"
    write_json(
        lineage_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_montage_lineage_v2",
            "status": "verified_same_new_raw_take",
            "ref_id": "T17-lineage",
            "role": "runtime.manifest",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "source": common_source,
            "formal_owner": {
                "subshot_id": "S10-04-crimson-route",
                "interval_half_open_frames": [OWNER_BEGIN, OWNER_END],
                "in_seconds": OWNER_IN,
                "out_seconds": OWNER_OUT,
                "duration_frames": OWNER_END - OWNER_BEGIN,
                "duration_seconds": OWNER_OUT - OWNER_IN,
                "playback_speed": 1,
            },
            "operator_marks": descriptor(live_dir / "operator-marks.json"),
            "observed_sequence": [
                {"kind": "clean_route_card_hold", "review_frame": 0, "readable_cards": ["三色轮舞", "综合色轮"]},
                {"kind": "game_ui_scroll", "review_frames": [150, 300]},
                {"kind": "game_ui_hover", "review_frames": [400, 540, 719], "card_id": "VIVHITE_CARD_TRICHROMATIC_WALTZ", "title": "三色轮舞", "tooltip_keywords": ["謦欬", "汲取"]},
            ],
            "claim_boundary": {
                "formal_action_chain": None,
                "action_evidence": [],
                "balance_or_infinite_growth_claim": False,
                "purpose": "third build-route montage only",
            },
        },
    )

    review_path = evidence_dir / "technical-visual-review.json"
    write_json(
        review_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_technical_visual_review_v2",
            "status": "passed",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "source": common_source,
            "technical": {
                "full_decode": "passed_no_errors",
                "video": "H.264 High 1920x1080 yuv420p progressive CFR 60/1",
                "audio": "AAC-LC 48000 Hz stereo",
                "duration_seconds": SOURCE_DURATION,
            },
            "visual": {
                "card_library_full_screen": True,
                "two_or_more_route_elements_readable": True,
                "game_ui_scroll_visible": True,
                "trichromatic_waltz_hover_and_tooltip_visible": True,
                "forbidden_elements": [],
                "forbidden_surface_review": {
                    "deprecated_cards": False,
                    "old_ironclad_replacement": False,
                    "balance_or_infinite_growth_promise": False,
                    "console": False,
                    "pause_menu": False,
                    "obs_or_taskbar": False,
                    "system_cursor": False,
                    "brain_ai_or_ascend_vision": False,
                    "debug_or_modded_label": False,
                    "loading_screen": False,
                },
            },
            "reviewed_source_frames": list(ANCHOR_FRAMES),
            "anchors": [descriptor(anchors[frame], media_type="image/png") for frame in ANCHOR_FRAMES],
        },
    )

    media_lineage_path = evidence_dir / "media-normalization.json"
    write_json(
        media_lineage_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_media_normalization_v2",
            "status": "passed_no_normalization",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "source": common_source,
            "normalization": {
                "required": False,
                "operation": "byte_identical_source",
                "raw_source_preserved": True,
                "formal_bound_frames": [OWNER_BEGIN, OWNER_END],
                "unbound_tail_frames": [OWNER_END, EXPECTED_FRAMES],
            },
        },
    )

    refs = [
        evidence_ref("T17-frame-begin", "frame.begin", frame_begin_path),
        evidence_ref("T17-runtime-manifest", "runtime.manifest", runtime_manifest_path),
        evidence_ref("T17-lineage", "runtime.manifest", lineage_path),
        evidence_ref("T17-frame-end", "frame.end", frame_end_path),
    ]
    source_row = {
        "artifact": rel(RAW),
        "duration_seconds": SOURCE_DURATION,
        "bytes": EXPECTED_BYTES,
        "sha256": EXPECTED_SHA256,
        "original_obs_path": EXTERNAL_RAW.as_posix(),
        "capture_identity": capture_identity(),
        "game_process": {"pid": 16428, "identity": GAME_PROCESS_ID, "started_utc": GAME_STARTED_UTC},
        "recorder_process": {"pid": 17432, "identity": RECORDER_PROCESS_ID, "started_utc": RECORDER_STARTED_UTC},
        "recording": {
            "start_frame": 1,
            "end_frame": EXPECTED_FRAMES + 1,
            "started_monotonic_seconds": 0.0,
            "stopped_monotonic_seconds": SOURCE_DURATION,
        },
        "ffprobe": descriptor(source_probe_path),
        "media_lineage": descriptor(media_lineage_path, normalization_required=False, raw_source_preserved=True),
    }
    span = {"subshot_id": "S10-04-crimson-route", "in_seconds": OWNER_IN, "out_seconds": OWNER_OUT}
    take = {
        "take_id": TAKE_ID,
        "independent": True,
        "source": source_row,
        "evidence_refs": refs,
        "action_evidence": [],
        "spans": [span],
    }
    row = {
        "schema_version": 2,
        "kind": "vivhite_promo_take_row_v2",
        "status": "production_candidate",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "take": take,
        "editorial_boundary": {
            "formal_owner_span": {
                "begin_zero_based_frame_inclusive": OWNER_BEGIN,
                "end_zero_based_frame_exclusive": OWNER_END,
                "duration_frames": OWNER_END - OWNER_BEGIN,
                "duration_seconds": OWNER_OUT - OWNER_IN,
            },
            "unbound_tail": {
                "begin_zero_based_frame_inclusive": OWNER_END,
                "end_zero_based_frame_exclusive": EXPECTED_FRAMES,
                "duration_frames": EXPECTED_FRAMES - OWNER_END,
            },
            "normalization_note": "The immutable OBS source is used byte-identically at 1x speed.",
        },
    }
    row_path = capture_dir / "take-row.production.json"
    partial_path = capture_dir / "take-manifest.t17-only.json"
    write_json(row_path, row)
    write_json(
        partial_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_take_manifest_v2",
            "batch_id": f"{RUN_ID}-t17-a02-partial",
            "run_id": RUN_ID,
            "source_strategy": "independent_take_files",
            "from_legacy_a4": False,
            "partial_scope": {
                "take_ids": [TAKE_ID],
                "production_binder_expected_global_status": "blocked_until_all_required_takes_exist",
            },
            "takes": [take],
        },
    )

    sys.path.insert(0, str(REPO / "tools" / "promo"))
    from vivhite_promo import director_v2, production_binder_v2  # noqa: PLC0415

    board = director_v2.load_storyboard_v2(STORYBOARD)
    board_take = next(item for item in board["takes"] if item["take_id"] == TAKE_ID)
    bindings = {"S10-04-crimson-route": {"take_id": TAKE_ID, "in_seconds": OWNER_IN, "out_seconds": OWNER_OUT}}
    runtime = production_binder_v2._bind_take(
        root=RUN,
        take_row=take,
        board_take=board_take,
        board=board,
        normalized_take={"take_id": TAKE_ID},
        bindings=bindings,
    )
    try:
        production_binder_v2.build_production_edl_v2(STORYBOARD, partial_path, artifact_root=RUN)
    except production_binder_v2.ProductionBinderV2Error as exc:
        public_error = f"{type(exc).__name__}: {exc}"
        if "take manifest must bind 19 or 20 independent takes" not in str(exc):
            raise
    else:
        raise RuntimeError("partial T17-only manifest unexpectedly passed the full production binder")

    validation_path = capture_dir / "binder-validation.json"
    write_json(
        validation_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_partial_binder_validation_v2",
            "status": "take_row_passed_global_manifest_incomplete",
            "validated_at_utc": observed_at,
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "inputs": {
                "storyboard": {"path": STORYBOARD.relative_to(REPO).as_posix(), "bytes": STORYBOARD.stat().st_size, "sha256": sha256(STORYBOARD)},
                "capture_runbook": {"path": RUNBOOK.relative_to(REPO).as_posix(), "bytes": RUNBOOK.stat().st_size, "sha256": sha256(RUNBOOK)},
                "take_row": descriptor(row_path),
                "partial_manifest": descriptor(partial_path),
                "source": descriptor(RAW),
                "source_probe": descriptor(source_probe_path),
            },
            "per_take_binder_validation": {
                "entry_point": "vivhite_promo.production_binder_v2._bind_take",
                "exit_code": 0,
                "status": "passed",
                "verified": {
                    "take_id": runtime.take_id,
                    "source_path": runtime.source.relative_path,
                    "source_bytes": runtime.source.bytes,
                    "source_sha256": runtime.source.sha256,
                    "duration_seconds": runtime.probe["duration_seconds"],
                    "frame_count": runtime.probe["frame_count"],
                    "video": "H.264 yuv420p 1920x1080 60 FPS",
                    "audio": "AAC 48000 Hz stereo",
                    "recording_start_frame": runtime.recording["start_frame"],
                    "recording_end_frame": runtime.recording["end_frame"],
                    "evidence_ref_count": len(runtime.evidence),
                    "action_contract_count": len(runtime.action_contracts),
                },
                "span_assertions": {
                    "status": "passed",
                    "binding": bindings["S10-04-crimson-route"],
                    "duration_frames": OWNER_END - OWNER_BEGIN,
                    "duration_seconds": OWNER_OUT - OWNER_IN,
                    "continuous": True,
                    "playback_speed": 1,
                },
            },
            "semantic_assertions": {
                "status": "passed",
                "runtime_card_count": 61,
                "deprecated_placeholder_cards_present": [],
                "route_cards": route_cards,
                "scroll_and_hover_visible": True,
                "balance_or_infinite_growth_claim": False,
            },
            "public_full_manifest_binder_invocation": {
                "entry_point": "vivhite_promo.production_binder_v2.build_production_edl_v2",
                "take_manifest": rel(partial_path),
                "output_created": False,
                "exit_code": 1,
                "status": "expected_global_failure",
                "exact_error": public_error,
            },
            "production_claim": {
                "t17_take_row": "per-take binder verified and ready to merge into the complete independent take manifest",
                "master_540_edl": "not generated; correctly pending all required independent takes",
                "raw_capture": "preserved byte-identical; only frames 0-719 are bound",
            },
        },
    )

    attempt_path = capture_dir / "attempt-manifest.json"
    write_json(
        attempt_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_take_attempt_v2",
            "run_id": RUN_ID,
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "status": "accepted_binder_row_verified",
            "production_eligible": True,
            "source": {
                "original_path": EXTERNAL_RAW.as_posix(),
                "artifact": rel(RAW),
                "bytes": EXPECTED_BYTES,
                "sha256": EXPECTED_SHA256,
                "decoded_video_frames": EXPECTED_FRAMES,
                "duration_seconds_from_decoded_frames": SOURCE_DURATION,
                "ffprobe": descriptor(source_probe_path),
            },
            "director_contract": {
                "storyboard": {"path": STORYBOARD.relative_to(REPO).as_posix(), "bytes": STORYBOARD.stat().st_size, "sha256": sha256(STORYBOARD)},
                "capture_runbook": {"path": RUNBOOK.relative_to(REPO).as_posix(), "bytes": RUNBOOK.stat().st_size, "sha256": sha256(RUNBOOK)},
                "subshot_id": "S10-04-crimson-route",
                "timeline_duration_seconds": 12,
                "formal_action_chain": None,
                "action_evidence": [],
            },
            "capture_identity": capture_identity(),
            "recording_bounds": descriptor(boundary_path, status="passed_source_local_with_operator_control_disclosure"),
            "runtime_manifest": descriptor(runtime_manifest_path, status="verified_61_cards_and_route_cards"),
            "lineage": descriptor(lineage_path, status="verified_same_new_raw_take"),
            "media_review": descriptor(review_path, status="passed"),
            "editorial_binding": {
                "take_row": descriptor(row_path),
                "partial_manifest": descriptor(partial_path),
                "binder_validation": descriptor(validation_path),
                "span": {
                    "subshot_id": "S10-04-crimson-route",
                    "frame_interval_half_open": [OWNER_BEGIN, OWNER_END],
                    "in_seconds": OWNER_IN,
                    "out_seconds": OWNER_OUT,
                    "duration_frames": OWNER_END - OWNER_BEGIN,
                    "duration_seconds": OWNER_OUT - OWNER_IN,
                    "playback_speed": 1,
                    "continuous": True,
                },
            },
        },
    )
    print(
        json.dumps(
            {
                "status": "accepted_binder_row_verified",
                "take": TAKE_ID,
                "attempt": ATTEMPT_ID,
                "source": descriptor(RAW),
                "decoded_frames": EXPECTED_FRAMES,
                "source_duration_seconds": SOURCE_DURATION,
                "owner_interval": [OWNER_BEGIN, OWNER_END],
                "owner_duration_seconds": OWNER_OUT - OWNER_IN,
                "runtime_cards": len(cards),
                "route_cards": route_cards,
                "binder_validation": descriptor(validation_path),
                "attempt_manifest": descriptor(attempt_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
