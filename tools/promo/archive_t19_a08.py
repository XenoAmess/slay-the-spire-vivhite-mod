"""Archive and bind the accepted T19/a08 card-library capture.

The writer is append-only.  It copies the sealed OBS source byte-for-byte,
extracts exact source-frame anchors, snapshots the current runtime card dump,
and runs the production binder's per-take gate.  It never fabricates formal
action evidence: T19 has no formal_action_chain and therefore binds an empty
action_evidence list.
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
TAKE_ID = "T19"
ATTEMPT_ID = "a08"
EXTERNAL_DIR = pathlib.Path(
    r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T19\a08"
)
EXTERNAL_RAW = EXTERNAL_DIR / "2026-09-04 19-28-44.mkv"
RAW = RUN / "raw" / "takes" / TAKE_ID / f"{ATTEMPT_ID}.mkv"
STORYBOARD = REPO / "tools" / "promo" / "v2" / "storyboard.json"
RUNBOOK = REPO / "tools" / "promo" / "v2" / "capture-runbook.json"
FFPROBE = pathlib.Path(r"C:\ffmpeg\bin\ffprobe.exe")
FFMPEG = pathlib.Path(r"C:\ffmpeg\bin\ffmpeg.exe")
GAME_LOG = pathlib.Path.home() / "AppData" / "Roaming" / "SlayTheSpire2" / "logs" / "godot.log"
DEPLOYED = pathlib.Path(r"G:\SteamLibrary\steamapps\common\Slay the Spire 2\mods\Vivhite")

EXPECTED_BYTES = 36_123_295
EXPECTED_SHA256 = "A3C1B530AC33DE0BC4F7B3FC1F5D37528991CBB41966B873E08AF4FA59C1B9F4"
EXPECTED_FRAMES = 6_603
FPS = 60
SOURCE_DURATION = EXPECTED_FRAMES / FPS
OWNER_BEGIN = 5_667
OWNER_END = 6_507
OWNER_IN = OWNER_BEGIN / FPS
OWNER_OUT = OWNER_END / FPS
GAME_PROCESS_ID = "SlayTheSpire2.exe-16428-2026-09-03T14-12-39.1941103Z"
GAME_STARTED_UTC = "2026-09-03T14:12:39.1941103Z"
RECORDER_PROCESS_ID = "obs64.exe-19256-2026-09-04T11-27-55.0005611Z"
RECORDER_STARTED_UTC = "2026-09-04T11:27:55.0005611Z"
GAME_RUN_ID = "native-vivhite-card-library"
SOURCE_ARTIFACT_ID = "T19-a08-A3C1B530AC33DE0B"


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
    """Create an immutable artifact; an identical rerun is harmless."""

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
    frames = [OWNER_BEGIN, 5_730, 5_880, 6_090, 6_240, 6_360, OWNER_END - 1]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = output_dir / "selected-%02d.png"
    expected = [output_dir / f"selected-{index:02d}.png" for index in range(1, len(frames) + 1)]
    if not all(path.exists() for path in expected):
        if any(path.exists() for path in expected):
            raise RuntimeError("partial T19 anchor extraction exists; refusing ambiguous rerun")
        expression = "+".join(f"eq(n\\,{frame})" for frame in frames)
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
                str(output_pattern),
            ],
            check=True,
        )
    if not all(path.is_file() and path.stat().st_size > 0 for path in expected):
        raise RuntimeError("exact source-frame extraction did not emit every T19 anchor")
    return dict(zip(frames, expected, strict=True))


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
    # The current process may dump IDs only once, but reject duplicates rather than
    # silently turning multiple dumps into one invented manifest.
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
    return matches


def main() -> int:
    source_probe_path = RUN / "probe" / "takes" / TAKE_ID / ATTEMPT_ID / "source-probe.json"
    if source_probe_path.exists():
        observed_at = str(json.loads(source_probe_path.read_text(encoding="utf-8-sig"))["observed_at_utc"])
    else:
        observed_at = utc_now()
    for tool in (FFPROBE, FFMPEG):
        if not tool.is_file():
            raise RuntimeError(f"required media tool is missing: {tool}")
    if EXTERNAL_RAW.stat().st_size != EXPECTED_BYTES or sha256(EXTERNAL_RAW) != EXPECTED_SHA256:
        raise RuntimeError("sealed T19/a08 OBS source no longer matches its capture receipt")

    copy_immutable(EXTERNAL_RAW, RAW)
    if RAW.stat().st_size != EXPECTED_BYTES or sha256(RAW) != EXPECTED_SHA256:
        raise RuntimeError("preserved T19/a08 raw is not byte-identical to the sealed OBS source")

    evidence_dir = RUN / "evidence" / "takes" / TAKE_ID / ATTEMPT_ID
    capture_dir = RUN / "capture" / "takes" / TAKE_ID / ATTEMPT_ID
    probe_dir = RUN / "probe" / "takes" / TAKE_ID / ATTEMPT_ID
    live_dir = evidence_dir / "live"
    for name in (
        "operator-marks.json",
        "explicit-start.json",
        "operator-frame-begin.png",
        "operator-frame-end.png",
        "count-label-checkpoint.png",
        "tooltip-1-VIVHITE_CARD_LAW_OF_CONSERVATION.png",
        "tooltip-2-VIVHITE_CARD_ASTRAL_PURSUIT.png",
        "tooltip-3-VIVHITE_CARD_TRICHROMATIC_WALTZ.png",
        "obs-before-start.png",
        "obs-after-start.png",
        "obs-before-stop.png",
        "obs-after-stop.png",
    ):
        copy_immutable(EXTERNAL_DIR / name, live_dir / name)

    anchors = extract_anchors(RAW, evidence_dir / "anchors")

    # Full decode validates both streams; ffprobe supplies the exact packet/frame counts.
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
        raise RuntimeError(f"T19/a08 decoded frame count changed: {frame_count}")
    if int(video["nb_read_packets"]) != EXPECTED_FRAMES:
        raise RuntimeError("T19/a08 video packet count does not match decoded frame count")

    source_probe_path = probe_dir / "source-probe.json"
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
            "freezedetect_status": "not_claimed; static UI holds are intentional",
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
    deployed_files = []
    for name in ("Vivhite.dll", "Vivhite.json", "Vivhite.pck"):
        path = DEPLOYED / name
        deployed_files.append({"name": name, "path": path.as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})

    runtime_manifest_path = evidence_dir / "runtime-manifest.json"
    runtime_manifest = {
        "schema_version": 2,
        "kind": "vivhite_promo_runtime_manifest_v2",
        "status": "verified_current_process_runtime_dump",
        "ref_id": "T19-runtime-manifest",
        "role": "runtime.manifest",
        "capture_identity": capture_identity(),
        "observed_at_utc": observed_at,
        "game_process": {"pid": 16428, "identity": GAME_PROCESS_ID, "started_utc": GAME_STARTED_UTC},
        "runtime_dump": {
            "artifact": descriptor(log_snapshot, media_type="text/plain"),
            "numeric_range_inclusive": [613, 673],
            "card_count": len(cards),
            "cards": cards,
            "unique_content_ids": len({row["content_id"] for row in cards}),
            "deprecated_placeholders_present": [],
        },
        "deployed_artifacts": deployed_files,
        "conclusion": "The active game process dumped exactly 61 unique current Vivhite card IDs and no deprecated placeholder card IDs.",
    }
    write_json(runtime_manifest_path, runtime_manifest)

    route_specs = [
        ("conservation_geometry", "VIVHITE_CARD_LAW_OF_CONSERVATION", "守恒定律", 5_730, "tooltip-1-VIVHITE_CARD_LAW_OF_CONSERVATION.png"),
        ("recursive_astromancy", "VIVHITE_CARD_ASTRAL_PURSUIT", "星算追猎", 5_880, "tooltip-2-VIVHITE_CARD_ASTRAL_PURSUIT.png"),
        ("chromatic_integral", "VIVHITE_CARD_TRICHROMATIC_WALTZ", "三色轮舞", 6_240, "tooltip-3-VIVHITE_CARD_TRICHROMATIC_WALTZ.png"),
    ]
    tooltip_path = evidence_dir / "tooltip-ocr.json"
    tooltip_doc = {
        "schema_version": 2,
        "kind": "vivhite_promo_tooltip_review_v2",
        "status": "verified_manual_visual_review_ocr_unavailable",
        "ref_id": "T19-tooltip-ocr",
        "role": "tooltip.ocr",
        "capture_identity": capture_identity(),
        "review_method": {
            "machine_ocr": "unavailable",
            "machine_ocr_error": "Windows.Globalization.Language initialization failed in the local WinRT OCR path",
            "fallback": "manual visual transcription cross-checked against exact raw-video frame anchors and operator screenshots",
            "claim_boundary": "No machine-OCR result is claimed.",
        },
        "representatives": [
            {
                "route": route,
                "card_id": card_id,
                "runtime_title_transcribed": title,
                "source_frame_zero_based": frame,
                "source_time_seconds": frame / FPS,
                "raw_frame": descriptor(anchors[frame], media_type="image/png"),
                "operator_checkpoint": descriptor(live_dir / screenshot, media_type="image/png"),
                "manual_visual_status": "passed_title_and_current_card_art_readable",
            }
            for route, card_id, title, frame, screenshot in route_specs
        ],
    }
    write_json(tooltip_path, tooltip_doc)

    frame_begin_path = evidence_dir / "frame-begin.json"
    frame_end_path = evidence_dir / "frame-end.json"
    common_source = {
        "path": rel(RAW),
        "bytes": EXPECTED_BYTES,
        "sha256": EXPECTED_SHA256,
        "decoded_frames": EXPECTED_FRAMES,
        "fps": FPS,
    }
    write_json(
        frame_begin_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_frame_marker_v2",
            "status": "verified",
            "ref_id": "T19-frame-begin",
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
            "visible": {"screen": "CARD_LIBRARY", "vivhite_card_count": 61, "clean_game_only_surface": True},
        },
    )
    write_json(
        frame_end_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_frame_marker_v2",
            "status": "verified",
            "ref_id": "T19-frame-end",
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
            "visible": {"screen": "CARD_LIBRARY", "route_tail": "chromatic_integral", "clean_game_only_surface": True},
        },
    )

    boundary_path = evidence_dir / "recording-boundary.json"
    started_mono = 243344.9252929
    stopped_mono = 243455.1153032
    write_json(
        boundary_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_recording_boundary_v2",
            "status": "passed_source_anchored",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "operator_receipt": descriptor(live_dir / "operator-marks.json"),
            "decoded_source_bounds": {
                "start_frame": 1,
                "end_frame_exclusive": EXPECTED_FRAMES + 1,
                "decoded_frame_count": EXPECTED_FRAMES,
                "exact_decoded_duration_seconds": SOURCE_DURATION,
                "container_duration_seconds": float(fmt["duration"]),
                "recording_started_monotonic_seconds": started_mono,
                "recording_stopped_monotonic_seconds": stopped_mono,
                "control_duration_seconds": stopped_mono - started_mono,
                "formal_owner_interval_zero_based": [OWNER_BEGIN, OWNER_END],
                "formal_owner_duration_frames": OWNER_END - OWNER_BEGIN,
                "formal_owner_duration_seconds": OWNER_OUT - OWNER_IN,
            },
            "reconciliation": {
                "raw_receipt_preserved": True,
                "control_to_decoded_duration_difference_seconds": (stopped_mono - started_mono) - SOURCE_DURATION,
                "formal_sequence_continuous": True,
                "playback_speed": 1,
            },
        },
    )

    review_path = evidence_dir / "technical-visual-review.json"
    reviewed_frames = [OWNER_BEGIN, 5_730, 5_880, 6_090, 6_240, 6_360, OWNER_END - 1]
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
                "native_card_count_61_visible": True,
                "three_route_representatives_readable": True,
                "game_ui_scroll_visible": True,
                "forbidden_elements": [],
                "forbidden_surface_review": {
                    "console": False,
                    "pause_menu": False,
                    "obs_or_taskbar": False,
                    "system_cursor": False,
                    "brain_ai_or_ascend_vision": False,
                    "debug_or_modded_label": False,
                    "loading_screen": False,
                    "old_ironclad_replacement": False,
                },
            },
            "reviewed_source_frames": reviewed_frames,
            "anchors": [descriptor(anchors[frame], media_type="image/png") for frame in reviewed_frames],
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
                "reason": "The OBS source already satisfies the production media contract.",
            },
        },
    )

    refs = [
        evidence_ref("T19-frame-begin", "frame.begin", frame_begin_path),
        evidence_ref("T19-runtime-manifest", "runtime.manifest", runtime_manifest_path),
        evidence_ref("T19-tooltip-ocr", "tooltip.ocr", tooltip_path),
        evidence_ref("T19-frame-end", "frame.end", frame_end_path),
    ]
    source_row = {
        "artifact": rel(RAW),
        "duration_seconds": SOURCE_DURATION,
        "bytes": EXPECTED_BYTES,
        "sha256": EXPECTED_SHA256,
        "original_obs_path": EXTERNAL_RAW.as_posix(),
        "capture_identity": capture_identity(),
        "game_process": {"pid": 16428, "identity": GAME_PROCESS_ID, "started_utc": GAME_STARTED_UTC},
        "recorder_process": {"pid": 19256, "identity": RECORDER_PROCESS_ID, "started_utc": RECORDER_STARTED_UTC},
        "recording": {
            "start_frame": 1,
            "end_frame": EXPECTED_FRAMES + 1,
            "started_monotonic_seconds": started_mono,
            "stopped_monotonic_seconds": stopped_mono,
        },
        "ffprobe": descriptor(source_probe_path),
        "media_lineage": descriptor(media_lineage_path, normalization_required=False, raw_source_preserved=True),
    }
    take = {
        "take_id": TAKE_ID,
        "independent": True,
        "source": source_row,
        "evidence_refs": refs,
        "action_evidence": [],
        "spans": [{"subshot_id": "S10-01-card-library", "in_seconds": OWNER_IN, "out_seconds": OWNER_OUT}],
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
            "formal_events": {
                "conservation_hover_frame": 5_730,
                "recursive_hover_frame": 5_880,
                "library_scroll_review_frame": 6_090,
                "chromatic_hover_frame": 6_240,
                "chromatic_result_hold_frame": 6_360,
            },
            "normalization_note": "The immutable OBS source is used byte-identically at 1x speed.",
        },
    }
    row_path = capture_dir / "take-row.production.json"
    partial_path = capture_dir / "take-manifest.t19-only.json"
    write_json(row_path, row)
    write_json(
        partial_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_take_manifest_v2",
            "batch_id": f"{RUN_ID}-t19-a08-partial",
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
    bindings = {
        "S10-01-card-library": {
            "take_id": TAKE_ID,
            "in_seconds": OWNER_IN,
            "out_seconds": OWNER_OUT,
        }
    }
    runtime = production_binder_v2._bind_take(
        root=RUN,
        take_row=take,
        board_take=board_take,
        board=board,
        normalized_take={"take_id": TAKE_ID},
        bindings=bindings,
    )
    try:
        production_binder_v2.build_production_edl_v2(
            STORYBOARD,
            partial_path,
            artifact_root=RUN,
        )
    except production_binder_v2.ProductionBinderV2Error as exc:
        public_error = f"{type(exc).__name__}: {exc}"
        if "take manifest must bind 19 or 20 independent takes" not in str(exc):
            raise
    else:
        raise RuntimeError("partial T19-only manifest unexpectedly passed the full production binder")

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
                "binder_implementation": {
                    "path": "tools/promo/vivhite_promo/production_binder_v2.py",
                    "bytes": (REPO / "tools/promo/vivhite_promo/production_binder_v2.py").stat().st_size,
                    "sha256": sha256(REPO / "tools/promo/vivhite_promo/production_binder_v2.py"),
                },
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
                    "source_in_seconds": OWNER_IN,
                    "source_out_seconds": OWNER_OUT,
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
                "representative_routes": [row["route"] for row in tooltip_doc["representatives"]],
                "manual_tooltip_review": "passed; machine OCR explicitly unavailable and not claimed",
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
                "t19_take_row": "per-take binder verified and ready to merge into the complete independent take manifest",
                "master_540_edl": "not generated; correctly pending all required independent takes",
                "raw_capture": "preserved byte-identical for audit and production source",
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
                "subshot_id": "S10-01-card-library",
                "timeline_duration_seconds": 14,
                "formal_action_chain": None,
                "action_evidence": [],
            },
            "capture_identity": capture_identity(),
            "recording_bounds": descriptor(boundary_path, status="passed"),
            "runtime_manifest": descriptor(runtime_manifest_path, status="verified_61_cards"),
            "tooltip_review": descriptor(tooltip_path, status="verified_manual_visual_ocr_unavailable"),
            "media_review": descriptor(review_path, status="passed"),
            "editorial_binding": {
                "take_row": descriptor(row_path),
                "partial_manifest": descriptor(partial_path),
                "binder_validation": descriptor(validation_path),
                "span": {
                    "subshot_id": "S10-01-card-library",
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
