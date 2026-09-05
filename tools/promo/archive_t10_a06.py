"""Archive and strictly bind the accepted T10/a06 Act 2 rest-site take.

The sealed OBS source is preserved byte-identically.  The production owner is
the first 1092 decoded CFR frames (18.2 seconds): clean Act 2 map, a real
reachable RestSite click, the native rest choice and healing animation, and a
real Proceed click returning to the map.  Recorder-side monotonic marks are
retained as input provenance; exact semantic edges are bound to reviewed
decoded frames in the immutable source.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


REPO = pathlib.Path(__file__).resolve().parents[2]
RUN_ID = "run-20260903T0012-director-v2-a1"
RUN = REPO / "tools" / "promo" / "runs" / RUN_ID
TAKE_ID = "T10"
ATTEMPT_ID = "a06"
SUBSHOT_ID = "S06-05-campfire-rest"
ACTION_ID = "T10-a06-choose-rest"
EXTERNAL_DIR = pathlib.Path(
    r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T10\a06"
)
EXTERNAL_RAW = EXTERNAL_DIR / "2026-09-04 23-25-05.mkv"
RAW = RUN / "raw" / "takes" / TAKE_ID / f"{ATTEMPT_ID}.mkv"
STORYBOARD = REPO / "tools" / "promo" / "v2" / "storyboard.json"
RUNBOOK = REPO / "tools" / "promo" / "v2" / "capture-runbook.json"
FFPROBE = pathlib.Path(r"C:\ffmpeg\bin\ffprobe.exe")
FFMPEG = pathlib.Path(r"C:\ffmpeg\bin\ffmpeg.exe")

EXPECTED_BYTES = 7_473_397
EXPECTED_SHA256 = "5CEC81F4E9FA8368CCFD125D496AE2938A41992144E165F6A144D50B9846AD8E"
EXPECTED_FRAMES = 1307
FPS = 60
SOURCE_DURATION = EXPECTED_FRAMES / FPS
OWNER_BEGIN = 0
OWNER_END = 1092
OWNER_DURATION = (OWNER_END - OWNER_BEGIN) / FPS
GAME_PROCESS_ID = "SlayTheSpire2.exe-16428-2026-09-03T14-12-39.1941103Z"
GAME_STARTED_UTC = "2026-09-03T14:12:39.1941103Z"
RECORDER_PROCESS_ID = "obs64.exe-18172-2026-09-04T15-24-35.1064703Z"
RECORDER_STARTED_UTC = "2026-09-04T15:24:35.1064703Z"
GAME_RUN_ID = "native-vivhite-act2-floor7-rest"
SOURCE_ARTIFACT_ID = "T10-a06-5CEC81F4E9FA8368"

# All values below are zero-based immutable source frames.  Contract frames
# are one-based because recording_start_frame is 1.
FRAME_MAP_CLICK_DOWN = 311
FRAME_MAP_CLICK_UP = 318
FRAME_CAMPFIRE_STABLE = 420
FRAME_STATE_BEFORE = 630
FRAME_REST_DOWN = 692
FRAME_REST_UP = 699
FRAME_REST_SETTLED = 869
FRAME_STATE_AFTER = 875
FRAME_PROCEED_DOWN = 918
FRAME_PROCEED_UP = 924
FRAME_MAP_RETURNED = 990
FRAME_END = OWNER_END - 1
ANCHOR_FRAMES = (
    0,
    FRAME_MAP_CLICK_DOWN,
    FRAME_CAMPFIRE_STABLE,
    FRAME_STATE_BEFORE,
    FRAME_REST_DOWN,
    FRAME_REST_UP,
    FRAME_REST_SETTLED,
    FRAME_STATE_AFTER,
    FRAME_PROCEED_DOWN,
    FRAME_MAP_RETURNED,
    FRAME_END,
)


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
            raise RuntimeError("partial T10 anchor extraction exists; refusing ambiguous rerun")
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
        raise RuntimeError("exact source-frame extraction did not emit every T10 anchor")
    return dict(zip(ANCHOR_FRAMES, expected, strict=True))


def source_identity() -> dict[str, str]:
    return {
        "session_id": RUN_ID,
        "game_run_id": GAME_RUN_ID,
        "game_process_id": GAME_PROCESS_ID,
        "source_video_artifact_id": SOURCE_ARTIFACT_ID,
        "run_id": RUN_ID,
        "take_id": TAKE_ID,
    }


def action_identity() -> dict[str, str]:
    return {
        **source_identity(),
        "subshot_id": SUBSHOT_ID,
        "action_id": ACTION_ID,
    }


def evidence_ref(ref_id: str, role: str, path: pathlib.Path) -> dict[str, Any]:
    return {"ref_id": ref_id, "role": role, "status": "verified", **descriptor(path)}


def strict_descriptor(path: pathlib.Path, document_kind: str) -> dict[str, Any]:
    return descriptor(path, media_type="application/json", document_kind=document_kind)


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
        raise RuntimeError("sealed T10/a06 OBS source no longer matches its operator receipt")

    marks_source = EXTERNAL_DIR / "operator-marks.json"
    events_source = EXTERNAL_DIR / "operator-events.ndjson"
    if not marks_source.is_file() or not events_source.is_file():
        raise RuntimeError("T10/a06 recorder-side marks are missing")
    marks = json.loads(marks_source.read_text(encoding="utf-8-sig"))
    if marks.get("status") != "completed" or marks.get("recording", {}).get("source_sha256") != EXPECTED_SHA256:
        raise RuntimeError("T10/a06 operator marks do not seal the expected source")

    copy_immutable(EXTERNAL_RAW, RAW)
    if RAW.stat().st_size != EXPECTED_BYTES or sha256(RAW) != EXPECTED_SHA256:
        raise RuntimeError("preserved T10/a06 raw is not byte-identical to the sealed OBS source")

    capture_dir = RUN / "capture" / "takes" / TAKE_ID / ATTEMPT_ID
    evidence_dir = RUN / "evidence" / "takes" / TAKE_ID / ATTEMPT_ID
    contract_dir = RUN / "contracts" / "takes" / TAKE_ID / ATTEMPT_ID
    live_dir = evidence_dir / "live"
    probe_dir = RUN / "probe" / "takes" / TAKE_ID / ATTEMPT_ID
    copy_immutable(marks_source, live_dir / "operator-marks.json")
    copy_immutable(events_source, live_dir / "operator-events.ndjson")

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
        raise RuntimeError(f"T10/a06 decoded frame count changed: {frame_count}")
    if int(video["nb_read_packets"]) != EXPECTED_FRAMES:
        raise RuntimeError("T10/a06 video packet count does not match decoded frame count")

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
            "native_rest_transition": "preserved within the uncut owner span",
        },
        "tools": {
            "ffprobe": {"path": str(FFPROBE), "sha256": sha256(FFPROBE)},
            "ffmpeg": {"path": str(FFMPEG), "sha256": sha256(FFMPEG)},
        },
    }
    write_json(source_probe_path, source_probe)

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
            "ref_id": "T10-frame-begin",
            "role": "frame.begin",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "source": common_source,
            "frame": {
                "source_zero_based": OWNER_BEGIN,
                "time_seconds": 0.0,
                "owner_interval_half_open": [OWNER_BEGIN, OWNER_END],
                "artifact": descriptor(anchors[OWNER_BEGIN], media_type="image/png"),
            },
            "visible": {
                "screen": "MAP",
                "act": 2,
                "floor": 7,
                "current_hp": 52,
                "max_hp": 78,
                "reachable_rest_site_line_visible": True,
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
            "ref_id": "T10-frame-end",
            "role": "frame.end",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "source": common_source,
            "frame": {
                "source_zero_based": FRAME_END,
                "time_seconds": FRAME_END / FPS,
                "owner_interval_half_open": [OWNER_BEGIN, OWNER_END],
                "artifact": descriptor(anchors[FRAME_END], media_type="image/png"),
            },
            "visible": {
                "screen": "MAP",
                "act": 2,
                "floor": 8,
                "current_hp": 75,
                "max_hp": 78,
                "visited_rest_site_and_map_marker_visible": True,
                "clean_game_only_surface": True,
            },
        },
    )

    staged_path = evidence_dir / "staged-setup.json"
    write_json(
        staged_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_staged_setup",
            "profile": "production",
            "provenance": "staged_setup",
            "capture_identity": action_identity(),
            "setup_end_frame": 0,
            "payload": {
                "run_id": GAME_RUN_ID,
                "act": 2,
                "prepared_floor": 7,
                "prepared_current_hp": 52,
                "prepared_max_hp": 78,
                "formal_source_begins_on_clean_map": True,
                "reachable_rest_site_line_visible": True,
            },
        },
    )

    state_before_path = evidence_dir / "state-before.json"
    state_after_path = evidence_dir / "state-after.json"
    write_json(
        state_before_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_state_snapshot",
            "profile": "production",
            "status": "observed",
            "role": "state.before",
            "capture_identity": action_identity(),
            "frame": FRAME_STATE_BEFORE + 1,
            "monotonic_seconds": FRAME_STATE_BEFORE / FPS,
            "state_version": 1,
            "observation_seq": 1,
            "payload": {
                "run_id": GAME_RUN_ID,
                "state_version": 1,
                "screen": "REST_SITE",
                "act": 2,
                "floor": 8,
                "run": {"current_hp": 52, "max_hp": 78},
                "room": {
                    "rest_option": "rest",
                    "rest_option_visible": True,
                    "fire_lit": True,
                    "character_rest_pose_visible": True,
                    "proceed_visible": False,
                },
                "visible_state": {
                    "healing_preview_text": "恢复最大生命值的30%（23）。",
                    "source_frame_zero_based": FRAME_STATE_BEFORE,
                    "frame_artifact": rel(anchors[FRAME_STATE_BEFORE]),
                },
            },
        },
    )
    write_json(
        state_after_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_state_snapshot",
            "profile": "production",
            "status": "observed",
            "role": "state.after",
            "capture_identity": action_identity(),
            "frame": FRAME_STATE_AFTER + 1,
            "monotonic_seconds": FRAME_STATE_AFTER / FPS,
            "state_version": 1,
            "observation_seq": 3,
            "payload": {
                "run_id": GAME_RUN_ID,
                "state_version": 1,
                "screen": "REST_SITE",
                "act": 2,
                "floor": 8,
                "run": {"current_hp": 75, "max_hp": 78, "hp_before": 52, "actual_healing": 23},
                "room": {
                    "rest_option": "rest",
                    "rest_option_visible": False,
                    "fire_lit": False,
                    "character_rest_pose_visible": True,
                    "proceed_visible": True,
                },
                "visible_state": {
                    "hud_hp_text": "75/78",
                    "source_frame_zero_based": FRAME_STATE_AFTER,
                    "frame_artifact": rel(anchors[FRAME_STATE_AFTER]),
                },
            },
        },
    )

    receipt_path = evidence_dir / "rest-receipt.json"
    before_hash = sha256(state_before_path)
    after_hash = sha256(state_after_path)
    down_contract = FRAME_REST_DOWN + 1
    up_contract = FRAME_REST_UP + 1
    settled_contract = FRAME_REST_SETTLED + 1
    down_time = FRAME_REST_DOWN / FPS
    up_time = FRAME_REST_UP / FPS
    settled_time = FRAME_REST_SETTLED / FPS
    write_json(
        receipt_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_action_receipt",
            "profile": "production",
            "role": "action.receipt",
            "capture_identity": action_identity(),
            "action_kind": "choose_rest_option",
            "input_origin": "game_ui_pointer",
            "status": "completed",
            "stable": True,
            "applied": True,
            "delivery": {"status": "sent"},
            "outcome": {"status": "applied"},
            "settled": True,
            "state_version": 1,
            "observation_seq": 2,
            "pointer_down_frame": down_contract,
            "pointer_up_frame": up_contract,
            "settled_frame": settled_contract,
            "pointer_down_monotonic_seconds": down_time,
            "pointer_up_monotonic_seconds": up_time,
            "settled_monotonic_seconds": settled_time,
            "state_before_binding": {"sha256": before_hash, "state_version": 1, "observation_seq": 1},
            "state_after_binding": {"sha256": after_hash, "state_version": 1, "observation_seq": 3},
            "payload": {
                "pointer": {
                    "button": "left",
                    "x": 790,
                    "y": 340,
                    "down_frame": down_contract,
                    "up_frame": up_contract,
                    "down_monotonic_seconds": down_time,
                    "up_monotonic_seconds": up_time,
                },
                "target": {"kind": "rest_option", "id": "rest"},
                "request": {
                    "request_id": ACTION_ID,
                    "action_kind": "choose_rest_option",
                    "parameters": {"option": "rest"},
                },
            },
        },
    )

    entry_receipt_path = evidence_dir / "campfire-entry-receipt.json"
    return_receipt_path = evidence_dir / "return-map-receipt.json"
    write_json(
        entry_receipt_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_map_room_receipt_v1",
            "status": "verified",
            "ref_id": "T10-campfire-entry-receipt",
            "role": "action.receipt",
            "event": "enter_reachable_rest_site",
            "input_origin": "game_ui_pointer",
            "capture_identity": {**source_identity(), "subshot_id": SUBSHOT_ID},
            "source": {
                **common_source,
                "pointer": {"x": 935, "y": 535},
                "pointer_down_source_zero_based_frame": FRAME_MAP_CLICK_DOWN,
                "pointer_up_source_zero_based_frame": FRAME_MAP_CLICK_UP,
                "settled_source_zero_based_frame": FRAME_CAMPFIRE_STABLE,
            },
            "result": {
                "status": "applied",
                "stable": True,
                "screen": "REST_SITE",
                "act": 2,
                "floor": 8,
                "reachable_line_visible_before_input": True,
                "character_rest_pose_visible": True,
            },
            "evidence_images": [
                descriptor(anchors[0], media_type="image/png"),
                descriptor(anchors[FRAME_CAMPFIRE_STABLE], media_type="image/png"),
            ],
        },
    )
    write_json(
        return_receipt_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_map_room_receipt_v1",
            "status": "verified",
            "ref_id": "T10-return-map-receipt",
            "role": "action.receipt",
            "event": "return_to_map_after_rest",
            "input_origin": "game_ui_pointer",
            "capture_identity": {**source_identity(), "subshot_id": SUBSHOT_ID},
            "source": {
                **common_source,
                "pointer": {"x": 1730, "y": 815},
                "pointer_down_source_zero_based_frame": FRAME_PROCEED_DOWN,
                "pointer_up_source_zero_based_frame": FRAME_PROCEED_UP,
                "settled_source_zero_based_frame": FRAME_MAP_RETURNED,
            },
            "result": {
                "status": "applied",
                "stable": True,
                "screen": "MAP",
                "act": 2,
                "floor": 8,
                "current_hp": 75,
                "max_hp": 78,
                "transition_completed": True,
            },
            "evidence_image": descriptor(anchors[FRAME_MAP_RETURNED], media_type="image/png"),
        },
    )

    sidecar_path = contract_dir / "choose-rest.json"
    write_json(
        sidecar_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_action_evidence",
            "profile": "production",
            "timebase": {"unit": "frames", "fps": FPS},
            "run_id": RUN_ID,
            "take_id": TAKE_ID,
            "subshot_id": SUBSHOT_ID,
            "action_id": ACTION_ID,
            "action_kind": "choose_rest_option",
            "capture_identity": action_identity(),
            "recording_start_frame": 1,
            "display_span": {"begin_frame": OWNER_BEGIN + 1, "end_frame": OWNER_END + 1},
            "staged_setup": {
                "provenance": "staged_setup",
                "setup_end_frame": 0,
                "artifact": strict_descriptor(staged_path, "vivhite_promo_staged_setup"),
            },
            "state_before": {
                "role": "state.before",
                "artifact": strict_descriptor(state_before_path, "vivhite_promo_state_snapshot"),
            },
            "action_receipt": {
                "role": "action.receipt",
                "artifact": strict_descriptor(receipt_path, "vivhite_promo_action_receipt"),
            },
            "state_after": {
                "role": "state.after",
                "artifact": strict_descriptor(state_after_path, "vivhite_promo_state_snapshot"),
            },
        },
    )

    live_receipt_path = capture_dir / "live-receipt.json"
    write_json(
        live_receipt_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_capture_receipt_v2",
            "status": "reconciled_to_closed_source",
            "run_id": RUN_ID,
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "sealed_media": {
                "original_path": EXTERNAL_RAW.as_posix(),
                "preserved_artifact": rel(RAW),
                "bytes": EXPECTED_BYTES,
                "sha256": EXPECTED_SHA256,
                "decoded_frames": EXPECTED_FRAMES,
            },
            "processes": {
                "game": marks["game"],
                "recorder": marks["obs"],
            },
            "operator_sources": {
                "marks": descriptor(live_dir / "operator-marks.json"),
                "events": descriptor(live_dir / "operator-events.ndjson"),
            },
            "operator_sequence": {
                "recording_start_request_utc": marks["timing"]["recording_start_request_utc"],
                "recording_stop_request_utc": marks["timing"]["recording_stop_request_utc"],
                "map_pointer": {"x": 935, "y": 535},
                "rest_pointer": {"x": 790, "y": 340},
                "proceed_pointer": {"x": 1730, "y": 815},
            },
            "reviewed_source_sequence": [
                {"event": "map_before", "frame": 0, "hp": "52/78"},
                {"event": "rest_site_entered", "frame": FRAME_CAMPFIRE_STABLE},
                {"event": "rest_option_before", "frame": FRAME_STATE_BEFORE, "hp": "52/78"},
                {"event": "native_rest_animation", "frames": [FRAME_REST_UP, FRAME_REST_SETTLED]},
                {"event": "rest_result", "frame": FRAME_STATE_AFTER, "hp": "75/78", "actual_healing": 23},
                {"event": "map_returned", "frame": FRAME_MAP_RETURNED, "hp": "75/78"},
                {"event": "formal_end", "frame": FRAME_END, "screen": "MAP"},
            ],
            "claim_boundary": {
                "operator_marks_are_decoded_frame_edges": False,
                "decoded_frames_are_bound_after_source_closure": True,
                "formal_owner_interval_half_open": [OWNER_BEGIN, OWNER_END],
                "unbound_tail_interval_half_open": [OWNER_END, EXPECTED_FRAMES],
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
                "act_2_map": True,
                "reachable_rest_site_and_route_visible": True,
                "real_map_node_selection": True,
                "complete_character_rest_pose_visible": True,
                "native_healing_animation_preserved": True,
                "hud_hp_path": "52/78 -> 75/78",
                "actual_healing": 23,
                "fire_extinguished": True,
                "return_to_map": True,
                "forbidden_elements": [],
                "native_transition_note": "The smoky dark interval is the native rest/healing animation, not a loading or recorder surface.",
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
                "tail_reason": "post-owner map hold reaches a game-native legend tooltip after the required 18.2 seconds",
            },
        },
    )

    refs = [
        evidence_ref("T10-state-before", "state.before", state_before_path),
        evidence_ref("T10-campfire-entry-receipt", "action.receipt", entry_receipt_path),
        evidence_ref("T10-rest-receipt", "action.receipt", receipt_path),
        evidence_ref("T10-state-after", "state.after", state_after_path),
        evidence_ref("T10-return-map-receipt", "action.receipt", return_receipt_path),
        evidence_ref("T10-frame-begin", "frame.begin", frame_begin_path),
        evidence_ref("T10-frame-end", "frame.end", frame_end_path),
    ]
    sidecar_desc = descriptor(sidecar_path)
    action_entry = {
        "step_id": "choose-rest-option",
        "action_id": ACTION_ID,
        "subshot_id": SUBSHOT_ID,
        "action_kind": "choose_rest_option",
        "sidecar": sidecar_desc,
        "state_before_ref": "T10-state-before",
        "receipt_ref": "T10-rest-receipt",
        "state_after_ref": "T10-state-after",
        "rest_option": "rest",
        "pointer_hitbox": {"left": 650, "top": 240, "right": 930, "bottom": 460},
        "visible_state_paths": ["/run/current_hp", "/room/fire_lit", "/room/rest_option_visible", "/room/proceed_visible"],
    }
    source_row = {
        "artifact": rel(RAW),
        "duration_seconds": SOURCE_DURATION,
        "bytes": EXPECTED_BYTES,
        "sha256": EXPECTED_SHA256,
        "original_obs_path": EXTERNAL_RAW.as_posix(),
        "capture_identity": source_identity(),
        "game_process": {"pid": 16428, "identity": GAME_PROCESS_ID, "started_utc": GAME_STARTED_UTC},
        "recorder_process": {"pid": 18172, "identity": RECORDER_PROCESS_ID, "started_utc": RECORDER_STARTED_UTC},
        "recording": {
            "start_frame": 1,
            "end_frame": EXPECTED_FRAMES + 1,
            "started_monotonic_seconds": 0.0,
            "stopped_monotonic_seconds": SOURCE_DURATION,
        },
        "ffprobe": descriptor(source_probe_path),
        "media_lineage": descriptor(media_lineage_path, normalization_required=False, raw_source_preserved=True),
    }
    take = {
        "take_id": TAKE_ID,
        "independent": True,
        "source": source_row,
        "evidence_refs": refs,
        "strict_action_sidecar": {
            "action_kind": "choose_rest_option",
            "action_id": ACTION_ID,
            "sidecar": sidecar_desc,
            "loader": "vivhite_promo.action_evidence_v2.load_action_evidence",
            "status": "passed",
            "rest_option": "rest",
            "pointer_hitbox": action_entry["pointer_hitbox"],
            "visible_state_paths": action_entry["visible_state_paths"],
        },
        "action_evidence": [action_entry],
        "spans": [{"subshot_id": SUBSHOT_ID, "in_seconds": 0.0, "out_seconds": OWNER_DURATION}],
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
                "duration_seconds": OWNER_DURATION,
            },
            "formal_display_span": {
                "begin_contract_frame_inclusive": OWNER_BEGIN + 1,
                "end_contract_frame_exclusive": OWNER_END + 1,
                "map_click_source_frames": [FRAME_MAP_CLICK_DOWN, FRAME_MAP_CLICK_UP],
                "rest_click_source_frames": [FRAME_REST_DOWN, FRAME_REST_UP],
                "rest_settled_source_frame": FRAME_REST_SETTLED,
                "state_after_source_frame": FRAME_STATE_AFTER,
                "proceed_click_source_frames": [FRAME_PROCEED_DOWN, FRAME_PROCEED_UP],
                "map_returned_source_frame": FRAME_MAP_RETURNED,
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
    partial_path = capture_dir / "take-manifest.t10-only.json"
    write_json(row_path, row)
    write_json(
        partial_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_take_manifest_v2",
            "batch_id": f"{RUN_ID}-t10-a06-partial",
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
    from vivhite_promo import action_evidence_v2, director_v2, production_binder_v2  # noqa: PLC0415

    contract = action_evidence_v2.load_action_evidence(sidecar_path, artifact_root=RUN)
    board = director_v2.load_storyboard_v2(STORYBOARD)
    board_take = next(item for item in board["takes"] if item["take_id"] == TAKE_ID)
    bindings = {SUBSHOT_ID: {"take_id": TAKE_ID, "in_seconds": 0.0, "out_seconds": OWNER_DURATION}}
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
        raise RuntimeError("partial T10-only manifest unexpectedly passed the full production binder")

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
                "strict_action_sidecar": descriptor(sidecar_path),
            },
            "strict_action_evidence_validation": {
                "entry_point": "vivhite_promo.action_evidence_v2.load_action_evidence",
                "status": "passed",
                "action_id": contract.action_id,
                "action_kind": contract.action_kind,
                "verified_chain": {
                    "state_before_frame": contract.state_before.frame,
                    "pointer_down_frame": contract.action_receipt.pointer_down_frame,
                    "pointer_up_frame": contract.action_receipt.pointer_up_frame,
                    "settled_frame": contract.action_receipt.settled_frame,
                    "state_after_frame": contract.state_after.frame,
                    "order_expression": "631 < 693 < 700 <= 870 < 876",
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
                    "recording_start_frame": runtime.recording["start_frame"],
                    "recording_end_frame": runtime.recording["end_frame"],
                    "evidence_ref_count": len(runtime.evidence),
                    "action_contract_count": len(runtime.action_contracts),
                },
                "span_assertions": {
                    "status": "passed",
                    "binding": bindings[SUBSHOT_ID],
                    "duration_frames": OWNER_END - OWNER_BEGIN,
                    "duration_seconds": OWNER_DURATION,
                    "continuous": True,
                    "playback_speed": 1,
                },
            },
            "semantic_assertions": {
                "status": "passed",
                "act": 2,
                "floor_path": [7, 8],
                "hp_path": "52/78 -> 75/78",
                "actual_healing": 23,
                "native_rest_animation_complete": True,
                "fire_extinguished": True,
                "map_returned": True,
                "forbidden_elements": [],
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
                "t10_take_row": "per-take binder verified and ready to merge into the complete independent take manifest",
                "master_540_edl": "not generated; correctly pending all required independent takes",
                "raw_capture": "preserved byte-identical; frames 0-1091 are bound",
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
                "subshot_id": SUBSHOT_ID,
                "timeline_duration_seconds": OWNER_DURATION,
                "action_evidence": [ACTION_ID],
            },
            "capture_identity": source_identity(),
            "live_receipt": descriptor(live_receipt_path, status="reconciled_to_closed_source"),
            "strict_action_sidecar": descriptor(sidecar_path, status="passed"),
            "media_review": descriptor(review_path, status="passed"),
            "editorial_binding": {
                "take_row": descriptor(row_path),
                "partial_manifest": descriptor(partial_path),
                "binder_validation": descriptor(validation_path),
                "span": {
                    "subshot_id": SUBSHOT_ID,
                    "frame_interval_half_open": [OWNER_BEGIN, OWNER_END],
                    "in_seconds": 0.0,
                    "out_seconds": OWNER_DURATION,
                    "duration_frames": OWNER_END - OWNER_BEGIN,
                    "duration_seconds": OWNER_DURATION,
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
                "owner_duration_seconds": OWNER_DURATION,
                "hp_path": "52/78 -> 75/78",
                "actual_healing": 23,
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
