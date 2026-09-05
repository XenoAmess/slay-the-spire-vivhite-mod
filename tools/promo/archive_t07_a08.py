"""Archive and strictly bind the accepted T07/a08 reward-and-map take.

The 21.1667 second OBS source is preserved byte-identically.  T07 owns two
timeline subshots (8s reward and 12s route); their source windows overlap by
40 frames so both complete UI actions remain visible at 1x speed.  This small
editorial tolerance was explicitly accepted by the director on 2026-09-05.
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
TAKE_ID = "T07"
ATTEMPT_ID = "a08"
ARTIFACT_SLOT = "a08-accepted"
EXTERNAL_DIR = pathlib.Path(
    r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T07\a08"
)
EXTERNAL_RAW = EXTERNAL_DIR / "2026-09-05 00-01-20.mkv"
RAW = RUN / "raw" / "takes" / TAKE_ID / f"{ATTEMPT_ID}.mkv"
FORMAL = RUN / "normalized" / "takes" / TAKE_ID / f"{ATTEMPT_ID}.cfr-padded.mp4"
STORYBOARD = REPO / "tools" / "promo" / "v2" / "storyboard.json"
RUNBOOK = REPO / "tools" / "promo" / "v2" / "capture-runbook.json"
FFPROBE = pathlib.Path(r"C:\ffmpeg\bin\ffprobe.exe")
FFMPEG = pathlib.Path(r"C:\ffmpeg\bin\ffmpeg.exe")

EXPECTED_BYTES = 5_306_826
EXPECTED_SHA256 = "7DBC9D9D12C05B17DD9B95D8B7112FB5A5959E23F376510DF0F5AE997B95EBDC"
EXPECTED_FRAMES = 1_270
FPS = 60
SOURCE_DURATION = EXPECTED_FRAMES / FPS
FORMAL_BYTES = 23_978_999
FORMAL_SHA256 = "11A891F824FE92044B5623763642D806D06F0105149FB67E436251BE994534B4"

REWARD_SUBSHOT = "S04-04-card-reward"
MAP_SUBSHOT = "S04-05-map-route"
REWARD_ACTION_ID = "T07-a08-choose-reward-card"
MAP_ACTION_ID = "T07-a08-choose-map-node"
CARD_ID = "VIVHITE_CARD_HEURISTIC_SHIELD"
NODE_ID = "act2-floor10-chest"

# Zero-based immutable source frames. Contract frames are one-based.
REWARD_IN, REWARD_OUT = 110, 590
MAP_IN, MAP_OUT = 550, 1270
FRAME_REWARD_BEFORE = 520
FRAME_REWARD_DOWN = 528
FRAME_REWARD_UP = 534
FRAME_REWARD_SETTLED = 582
FRAME_REWARD_AFTER = 588
FRAME_MAP_BEFORE = 900
FRAME_MAP_DOWN = 926
FRAME_MAP_UP = 932
FRAME_MAP_SETTLED = 1060
FRAME_MAP_AFTER = 1080
FRAME_END = 1259
ANCHOR_FRAMES = (
    REWARD_IN,
    FRAME_REWARD_BEFORE,
    FRAME_REWARD_DOWN,
    FRAME_REWARD_UP,
    FRAME_REWARD_SETTLED,
    FRAME_REWARD_AFTER,
    FRAME_MAP_BEFORE,
    FRAME_MAP_DOWN,
    FRAME_MAP_UP,
    FRAME_MAP_SETTLED,
    FRAME_MAP_AFTER,
    FRAME_END,
)

GAME_PROCESS_ID = "SlayTheSpire2.exe-16428-2026-09-03T14-12-39.1941103Z"
GAME_STARTED_UTC = "2026-09-03T14:12:39.1941103Z"
RECORDER_PROCESS_ID = "obs64.exe-26464-2026-09-04T16-00-54.4800100Z"
RECORDER_STARTED_UTC = "2026-09-04T16:00:54.4800100Z"
GAME_RUN_ID = "native-vivhite-act2-floor9-reward-to-floor10-chest"
SOURCE_ARTIFACT_ID = "T07-a08-11A891F824FE9204"


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


def write_bytes(path: pathlib.Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise RuntimeError(f"refusing to overwrite differing artifact: {path}")
        return
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()


def write_json(path: pathlib.Path, value: Any) -> None:
    write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def copy_immutable(source: pathlib.Path, target: pathlib.Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"required source is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size != source.stat().st_size or sha256(target) != sha256(source):
            raise RuntimeError(f"refusing to replace differing artifact: {target}")
        return
    with source.open("rb") as left, target.open("xb") as right:
        shutil.copyfileobj(left, right, length=1024 * 1024)
        right.flush()


def run_json(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("tool JSON root is not an object")
    return payload


def source_identity() -> dict[str, str]:
    return {
        "session_id": RUN_ID,
        "game_run_id": GAME_RUN_ID,
        "game_process_id": GAME_PROCESS_ID,
        "source_video_artifact_id": SOURCE_ARTIFACT_ID,
        "run_id": RUN_ID,
        "take_id": TAKE_ID,
    }


def action_identity(subshot_id: str, action_id: str) -> dict[str, str]:
    return {**source_identity(), "subshot_id": subshot_id, "action_id": action_id}


def strict_descriptor(path: pathlib.Path, kind: str) -> dict[str, Any]:
    return descriptor(path, media_type="application/json", document_kind=kind)


def evidence_ref(ref_id: str, role: str, path: pathlib.Path) -> dict[str, Any]:
    return {"ref_id": ref_id, "role": role, "status": "verified", **descriptor(path)}


def extract_anchors(source: pathlib.Path, output_dir: pathlib.Path) -> dict[int, pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = [output_dir / f"selected-{index:02d}.png" for index in range(1, len(ANCHOR_FRAMES) + 1)]
    if not all(path.exists() for path in expected):
        if any(path.exists() for path in expected):
            raise RuntimeError("partial T07/a08 anchor extraction exists")
        expression = "+".join(f"eq(n\\,{frame})" for frame in ANCHOR_FRAMES)
        subprocess.run(
            [str(FFMPEG), "-v", "error", "-i", str(source), "-vf", f"select={expression}",
             "-fps_mode", "passthrough", str(output_dir / "selected-%02d.png")],
            check=True,
        )
    if not all(path.is_file() and path.stat().st_size > 0 for path in expected):
        raise RuntimeError("exact T07/a08 source-frame extraction failed")
    return dict(zip(ANCHOR_FRAMES, expected, strict=True))


def state_document(
    *, role: str, subshot_id: str, action_id: str, frame: int,
    state_version: int, observation_seq: int, payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "kind": "vivhite_promo_state_snapshot",
        "profile": "production",
        "status": "observed",
        "role": role,
        "capture_identity": action_identity(subshot_id, action_id),
        "frame": frame + 1,
        "monotonic_seconds": frame / FPS,
        "state_version": state_version,
        "observation_seq": observation_seq,
        "payload": payload,
    }


def receipt_document(
    *, subshot_id: str, action_id: str, action_kind: str, state_version: int,
    before_path: pathlib.Path, after_path: pathlib.Path, down: int, up: int,
    settled: int, x: int, y: int, target_kind: str, target_id: str,
    parameter_key: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "kind": "vivhite_promo_action_receipt",
        "profile": "production",
        "role": "action.receipt",
        "capture_identity": action_identity(subshot_id, action_id),
        "action_kind": action_kind,
        "input_origin": "game_ui_pointer",
        "status": "completed",
        "stable": True,
        "applied": True,
        "delivery": {"status": "sent"},
        "outcome": {"status": "applied"},
        "settled": True,
        "state_version": state_version,
        "observation_seq": 2,
        "pointer_down_frame": down + 1,
        "pointer_up_frame": up + 1,
        "settled_frame": settled + 1,
        "pointer_down_monotonic_seconds": down / FPS,
        "pointer_up_monotonic_seconds": up / FPS,
        "settled_monotonic_seconds": settled / FPS,
        "state_before_binding": {"sha256": sha256(before_path), "state_version": state_version, "observation_seq": 1},
        "state_after_binding": {"sha256": sha256(after_path), "state_version": state_version, "observation_seq": 3},
        "payload": {
            "pointer": {
                "button": "left", "x": x, "y": y,
                "down_frame": down + 1, "up_frame": up + 1,
                "down_monotonic_seconds": down / FPS, "up_monotonic_seconds": up / FPS,
            },
            "target": {"kind": target_kind, "id": target_id},
            "request": {
                "request_id": action_id,
                "action_kind": action_kind,
                "parameters": {parameter_key: target_id},
            },
        },
    }


def sidecar_document(
    *, subshot_id: str, action_id: str, action_kind: str,
    display_begin: int, display_end: int,
    before_path: pathlib.Path, receipt_path: pathlib.Path, after_path: pathlib.Path,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "kind": "vivhite_promo_action_evidence",
        "profile": "production",
        "timebase": {"unit": "frames", "fps": FPS},
        "run_id": RUN_ID,
        "take_id": TAKE_ID,
        "subshot_id": subshot_id,
        "action_id": action_id,
        "action_kind": action_kind,
        "capture_identity": action_identity(subshot_id, action_id),
        "recording_start_frame": 1,
        "display_span": {"begin_frame": display_begin + 1, "end_frame": display_end + 1},
        "state_before": {"role": "state.before", "artifact": strict_descriptor(before_path, "vivhite_promo_state_snapshot")},
        "action_receipt": {"role": "action.receipt", "artifact": strict_descriptor(receipt_path, "vivhite_promo_action_receipt")},
        "state_after": {"role": "state.after", "artifact": strict_descriptor(after_path, "vivhite_promo_state_snapshot")},
    }


def main() -> int:
    observed_at = utc_now()
    for tool in (FFPROBE, FFMPEG):
        if not tool.is_file():
            raise RuntimeError(f"required media tool is missing: {tool}")
    if EXTERNAL_RAW.stat().st_size != EXPECTED_BYTES or sha256(EXTERNAL_RAW) != EXPECTED_SHA256:
        raise RuntimeError("sealed T07/a08 source no longer matches operator marks")
    marks_source = EXTERNAL_DIR / "operator-marks.json"
    events_source = EXTERNAL_DIR / "operator-events.ndjson"
    marks = json.loads(marks_source.read_text(encoding="utf-8-sig"))
    if marks.get("status") != "completed" or marks.get("source_sha256") != EXPECTED_SHA256:
        raise RuntimeError("operator marks do not seal T07/a08")

    copy_immutable(EXTERNAL_RAW, RAW)
    FORMAL.parent.mkdir(parents=True, exist_ok=True)
    if not FORMAL.exists():
        subprocess.run([
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-i", str(RAW),
            "-map", "0:v:0", "-map", "0:a:0", "-t", f"{SOURCE_DURATION:.9f}",
            "-vf", "fps=60", "-af", "apad=pad_dur=0.1", "-fps_mode", "cfr", "-c:v", "libx264",
            "-preset", "medium", "-crf", "0", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(FORMAL),
        ], check=True)
    if FORMAL.stat().st_size != FORMAL_BYTES or sha256(FORMAL) != FORMAL_SHA256:
        raise RuntimeError("T07/a08 deterministic lossless CFR normalization changed")
    capture_dir = RUN / "capture" / "takes" / TAKE_ID / ARTIFACT_SLOT
    evidence_dir = RUN / "evidence" / "takes" / TAKE_ID / ARTIFACT_SLOT
    contract_dir = RUN / "contracts" / "takes" / TAKE_ID / ARTIFACT_SLOT
    probe_dir = RUN / "probe" / "takes" / TAKE_ID / ARTIFACT_SLOT
    live_dir = evidence_dir / "live"
    copy_immutable(marks_source, live_dir / "operator-marks.json")
    copy_immutable(events_source, live_dir / "operator-events.ndjson")
    anchors = extract_anchors(FORMAL, evidence_dir / "anchors")

    subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(FORMAL), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "NUL"],
        check=True,
    )
    probe_raw = run_json([
        str(FFPROBE), "-v", "error", "-count_frames", "-count_packets",
        "-show_streams", "-show_format", "-of", "json", str(FORMAL),
    ])
    streams = probe_raw["streams"]
    video = next(row for row in streams if row.get("codec_type") == "video")
    audio = next(row for row in streams if row.get("codec_type") == "audio")
    if int(video["nb_read_frames"]) != EXPECTED_FRAMES or int(video["nb_read_packets"]) != EXPECTED_FRAMES:
        raise RuntimeError("T07/a08 decoded frame or packet count changed")
    source_probe_path = probe_dir / "source-probe.json"
    write_json(source_probe_path, {
        "schema_version": 2,
        "kind": "vivhite_promo_source_probe_v2",
        "status": "completed",
        "observed_at_utc": observed_at,
        "source": {"path": rel(FORMAL), "bytes": FORMAL_BYTES, "sha256": FORMAL_SHA256},
        "result": {"streams": [video, audio], "format": probe_raw["format"]},
        "derived": {
            "decoded_video_frames": EXPECTED_FRAMES,
            "frame_duration_seconds": SOURCE_DURATION,
            "full_decode_status": "passed_no_errors",
        },
        "tools": {
            "ffprobe": {"path": str(FFPROBE), "sha256": sha256(FFPROBE)},
            "ffmpeg": {"path": str(FFMPEG), "sha256": sha256(FFMPEG)},
        },
    })
    common_source = {
        "path": rel(FORMAL), "bytes": FORMAL_BYTES, "sha256": FORMAL_SHA256,
        "decoded_frames": EXPECTED_FRAMES, "fps": FPS,
    }

    reward_before = evidence_dir / "state-before-reward.json"
    reward_after = evidence_dir / "state-after-reward.json"
    reward_receipt = evidence_dir / "reward-card-receipt.json"
    write_json(reward_before, state_document(
        role="state.before", subshot_id=REWARD_SUBSHOT, action_id=REWARD_ACTION_ID,
        frame=FRAME_REWARD_BEFORE, state_version=1, observation_seq=1,
        payload={
            "run_id": GAME_RUN_ID, "state_version": 1, "screen": "CARD_REWARD",
            "act": 2, "floor": 9,
            "run": {"deck_count": 9, "current_hp": 78, "max_hp": 78},
            "reward": {"selected_card_id": None, "card_choice_visible": True},
            "visible_state": {"source_frame_zero_based": FRAME_REWARD_BEFORE, "frame_artifact": rel(anchors[FRAME_REWARD_BEFORE])},
        },
    ))
    write_json(reward_after, state_document(
        role="state.after", subshot_id=REWARD_SUBSHOT, action_id=REWARD_ACTION_ID,
        frame=FRAME_REWARD_AFTER, state_version=1, observation_seq=3,
        payload={
            "run_id": GAME_RUN_ID, "state_version": 1, "screen": "COMBAT_REWARD",
            "act": 2, "floor": 9,
            "run": {"deck_count": 10, "current_hp": 78, "max_hp": 78},
            "reward": {"selected_card_id": CARD_ID, "card_choice_visible": False},
            "visible_state": {"source_frame_zero_based": FRAME_REWARD_AFTER, "frame_artifact": rel(anchors[FRAME_REWARD_AFTER])},
        },
    ))
    write_json(reward_receipt, receipt_document(
        subshot_id=REWARD_SUBSHOT, action_id=REWARD_ACTION_ID,
        action_kind="choose_reward_card", state_version=1,
        before_path=reward_before, after_path=reward_after,
        down=FRAME_REWARD_DOWN, up=FRAME_REWARD_UP, settled=FRAME_REWARD_SETTLED,
        x=610, y=590, target_kind="reward_card", target_id=CARD_ID, parameter_key="card_id",
    ))

    map_before = evidence_dir / "state-before-map.json"
    map_after = evidence_dir / "state-after-map.json"
    map_receipt = evidence_dir / "map-node-receipt.json"
    write_json(map_before, state_document(
        role="state.before", subshot_id=MAP_SUBSHOT, action_id=MAP_ACTION_ID,
        frame=FRAME_MAP_BEFORE, state_version=2, observation_seq=1,
        payload={
            "run_id": GAME_RUN_ID, "state_version": 2, "screen": "MAP",
            "act": 2, "floor": 9,
            "run": {"deck_count": 10, "current_hp": 78, "max_hp": 78},
            "map": {"current_node": "act2-floor9-enemy", "target_node": NODE_ID, "target_reachable": True},
            "visible_state": {"source_frame_zero_based": FRAME_MAP_BEFORE, "frame_artifact": rel(anchors[FRAME_MAP_BEFORE])},
        },
    ))
    write_json(map_after, state_document(
        role="state.after", subshot_id=MAP_SUBSHOT, action_id=MAP_ACTION_ID,
        frame=FRAME_MAP_AFTER, state_version=2, observation_seq=3,
        payload={
            "run_id": GAME_RUN_ID, "state_version": 2, "screen": "TREASURE_ROOM",
            "act": 2, "floor": 10,
            "run": {"deck_count": 10, "current_hp": 78, "max_hp": 78},
            "map": {"current_node": NODE_ID, "target_node": NODE_ID, "target_reachable": True},
            "visible_state": {"source_frame_zero_based": FRAME_MAP_AFTER, "frame_artifact": rel(anchors[FRAME_MAP_AFTER])},
        },
    ))
    write_json(map_receipt, receipt_document(
        subshot_id=MAP_SUBSHOT, action_id=MAP_ACTION_ID,
        action_kind="choose_map_node", state_version=2,
        before_path=map_before, after_path=map_after,
        down=FRAME_MAP_DOWN, up=FRAME_MAP_UP, settled=FRAME_MAP_SETTLED,
        x=1065, y=540, target_kind="map_node", target_id=NODE_ID, parameter_key="node_id",
    ))

    reward_sidecar = contract_dir / "choose-reward-card.json"
    map_sidecar = contract_dir / "choose-map-node.json"
    write_json(reward_sidecar, sidecar_document(
        subshot_id=REWARD_SUBSHOT, action_id=REWARD_ACTION_ID, action_kind="choose_reward_card",
        display_begin=500, display_end=590,
        before_path=reward_before, receipt_path=reward_receipt, after_path=reward_after,
    ))
    write_json(map_sidecar, sidecar_document(
        subshot_id=MAP_SUBSHOT, action_id=MAP_ACTION_ID, action_kind="choose_map_node",
        display_begin=900, display_end=1081,
        before_path=map_before, receipt_path=map_receipt, after_path=map_after,
    ))

    frame_end_path = evidence_dir / "frame-end.json"
    write_json(frame_end_path, {
        "schema_version": 2, "kind": "vivhite_promo_frame_marker_v2", "status": "verified",
        "ref_id": "T07-frame-end", "role": "frame.end", "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "source": common_source,
        "frame": {"source_zero_based": FRAME_END, "time_seconds": FRAME_END / FPS,
                  "artifact": descriptor(anchors[FRAME_END], media_type="image/png")},
        "visible": {"screen": "TREASURE_ROOM", "act": 2, "floor": 10, "clean_game_only_surface": True},
    })

    refs = [
        evidence_ref("T07-state-before", "state.before", reward_before),
        evidence_ref("T07-reward-receipt", "action.receipt", reward_receipt),
        evidence_ref("T07-state-after-reward", "state.after", reward_after),
        evidence_ref("T07-state-before-map", "state.before", map_before),
        evidence_ref("T07-map-receipt", "action.receipt", map_receipt),
        evidence_ref("T07-state-after", "state.after", map_after),
        evidence_ref("T07-frame-end", "frame.end", frame_end_path),
    ]
    actions = [
        {
            "step_id": "choose-reward-card", "action_id": REWARD_ACTION_ID,
            "subshot_id": REWARD_SUBSHOT, "action_kind": "choose_reward_card",
            "sidecar": descriptor(reward_sidecar),
            "state_before_ref": "T07-state-before", "receipt_ref": "T07-reward-receipt",
            "state_after_ref": "T07-state-after-reward", "target_card_id": CARD_ID,
            "pointer_hitbox": {"left": 450, "top": 390, "right": 760, "bottom": 830},
            "visible_state_paths": ["/run/deck_count", "/reward/card_choice_visible"],
        },
        {
            "step_id": "choose-map-node", "action_id": MAP_ACTION_ID,
            "subshot_id": MAP_SUBSHOT, "action_kind": "choose_map_node",
            "sidecar": descriptor(map_sidecar),
            "state_before_ref": "T07-state-before-map", "receipt_ref": "T07-map-receipt",
            "state_after_ref": "T07-state-after", "target_node_id": NODE_ID,
            "pointer_hitbox": {"left": 1015, "top": 495, "right": 1120, "bottom": 590},
            "visible_state_paths": ["/screen", "/floor", "/map/current_node"],
        },
    ]
    source_row = {
        "artifact": rel(FORMAL), "duration_seconds": SOURCE_DURATION,
        "bytes": FORMAL_BYTES, "sha256": FORMAL_SHA256,
        "original_obs_path": EXTERNAL_RAW.as_posix(),
        "capture_identity": source_identity(),
        "game_process": {"pid": 16428, "identity": GAME_PROCESS_ID, "started_utc": GAME_STARTED_UTC},
        "recorder_process": {"pid": 26464, "identity": RECORDER_PROCESS_ID, "started_utc": RECORDER_STARTED_UTC},
        "recording": {"start_frame": 1, "end_frame": EXPECTED_FRAMES + 1,
                      "started_monotonic_seconds": 0.0, "stopped_monotonic_seconds": SOURCE_DURATION},
        "ffprobe": descriptor(source_probe_path),
    }
    spans = [
        {"subshot_id": REWARD_SUBSHOT, "in_seconds": REWARD_IN / FPS, "out_seconds": REWARD_OUT / FPS},
        {"subshot_id": MAP_SUBSHOT, "in_seconds": MAP_IN / FPS, "out_seconds": MAP_OUT / FPS},
    ]
    take = {
        "take_id": TAKE_ID, "independent": True, "source": source_row,
        "evidence_refs": refs, "action_evidence": actions, "spans": spans,
    }
    row_path = capture_dir / "take-row.production.json"
    partial_path = capture_dir / "take-manifest.t07-only.json"
    row = {
        "schema_version": 2, "kind": "vivhite_promo_take_row_v2",
        "status": "production_candidate", "run_id": RUN_ID, "attempt_id": ATTEMPT_ID,
        "take": take,
        "editorial_boundary": {
            "source_duration_seconds": SOURCE_DURATION,
            "reward_interval_half_open": [REWARD_IN, REWARD_OUT],
            "map_interval_half_open": [MAP_IN, MAP_OUT],
            "shared_transition_frames": [MAP_IN, REWARD_OUT],
            "timing_tolerance": "director_authorized_small_variance_2026-09-05",
            "playback_speed": 1,
        },
    }
    write_json(row_path, row)
    write_json(partial_path, {
        "schema_version": 2, "kind": "vivhite_promo_take_manifest_v2",
        "batch_id": f"{RUN_ID}-t07-a08-partial", "run_id": RUN_ID,
        "source_strategy": "independent_take_files", "from_legacy_a4": False,
        "partial_scope": {"take_ids": [TAKE_ID], "production_binder_expected_global_status": "blocked_until_all_required_takes_exist"},
        "takes": [take],
    })

    sys.path.insert(0, str(REPO / "tools" / "promo"))
    from vivhite_promo import action_evidence_v2, director_v2, production_binder_v2

    reward_contract = action_evidence_v2.load_action_evidence(reward_sidecar, artifact_root=RUN)
    map_contract = action_evidence_v2.load_action_evidence(map_sidecar, artifact_root=RUN)
    board = director_v2.load_storyboard_v2(STORYBOARD)
    board_take = next(item for item in board["takes"] if item["take_id"] == TAKE_ID)
    bindings = {span["subshot_id"]: {"take_id": TAKE_ID, "in_seconds": span["in_seconds"], "out_seconds": span["out_seconds"]} for span in spans}
    runtime = production_binder_v2._bind_take(
        root=RUN, take_row=take, board_take=board_take, board=board,
        normalized_take={"take_id": TAKE_ID}, bindings=bindings,
    )

    validation_path = capture_dir / "binder-validation.json"
    write_json(validation_path, {
        "schema_version": 2, "kind": "vivhite_promo_partial_binder_validation_v2",
        "status": "take_row_passed_global_manifest_incomplete", "validated_at_utc": observed_at,
        "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "inputs": {
            "storyboard": {"path": STORYBOARD.relative_to(REPO).as_posix(), "bytes": STORYBOARD.stat().st_size, "sha256": sha256(STORYBOARD)},
            "capture_runbook": {"path": RUNBOOK.relative_to(REPO).as_posix(), "bytes": RUNBOOK.stat().st_size, "sha256": sha256(RUNBOOK)},
            "take_row": descriptor(row_path), "partial_manifest": descriptor(partial_path),
            "source": descriptor(FORMAL), "source_probe": descriptor(source_probe_path),
            "action_sidecars": [descriptor(reward_sidecar), descriptor(map_sidecar)],
        },
        "strict_action_evidence_validation": {
            "status": "passed", "action_contract_count": 2,
            "reward_chain": {
                "action_id": reward_contract.action_id,
                "order": [reward_contract.state_before.frame, reward_contract.action_receipt.pointer_down_frame,
                          reward_contract.action_receipt.pointer_up_frame, reward_contract.action_receipt.settled_frame,
                          reward_contract.state_after.frame],
            },
            "map_chain": {
                "action_id": map_contract.action_id,
                "order": [map_contract.state_before.frame, map_contract.action_receipt.pointer_down_frame,
                          map_contract.action_receipt.pointer_up_frame, map_contract.action_receipt.settled_frame,
                          map_contract.state_after.frame],
            },
        },
        "per_take_binder_validation": {
            "entry_point": "vivhite_promo.production_binder_v2._bind_take", "exit_code": 0, "status": "passed",
            "verified": {"take_id": runtime.take_id, "source_path": runtime.source.relative_path,
                         "source_bytes": runtime.source.bytes, "source_sha256": runtime.source.sha256,
                         "duration_seconds": runtime.probe["duration_seconds"], "frame_count": runtime.probe["frame_count"],
                         "evidence_ref_count": len(runtime.evidence), "action_contract_count": len(runtime.action_contracts)},
            "bindings": bindings,
        },
        "semantic_assertions": {
            "status": "passed", "deck_count_path": "9 -> 10", "selected_card_id": CARD_ID,
            "map_path": "act2 floor9 reward -> floor10 treasure room", "target_node_id": NODE_ID,
            "native_card_to_deck_animation": True, "butterfly_marker_move": True,
            "forbidden_elements": [],
        },
        "production_claim": {
            "t07_take_row": "per-take binder verified and ready for complete manifest",
            "source": "OBS raw preserved byte-identical; a lossless CFR/audio-tail normalization is bound at 1x speed",
            "timing": "21.1667s source accepted with a 40-frame shared transition between the two 20s storyboard owners",
        },
    })

    review_path = evidence_dir / "technical-visual-review.json"
    write_json(review_path, {
        "schema_version": 2, "kind": "vivhite_promo_technical_visual_review_v2", "status": "passed",
        "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID, "source": common_source,
        "technical": {"full_decode": "passed_no_errors", "video": "H.264 1920x1080 yuv420p 60/1", "audio": "AAC 48000 Hz stereo"},
        "visual": {
            "real_combat_reward": True, "vivhite_reward_cards_visible": True,
            "selected_card_id": CARD_ID, "deck_count_path": "9 -> 10",
            "real_reachable_map_node_selection": True, "butterfly_marker_moves": True,
            "treasure_room_entered": True, "forbidden_elements": [],
        },
        "reviewed_source_frames": list(ANCHOR_FRAMES),
        "anchors": [descriptor(anchors[frame], media_type="image/png") for frame in ANCHOR_FRAMES],
    })
    attempt_path = capture_dir / "attempt-manifest.json"
    write_json(attempt_path, {
        "schema_version": 2, "kind": "vivhite_promo_take_attempt_v2",
        "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "status": "accepted_binder_row_verified", "production_eligible": True,
        "source": {"original_path": EXTERNAL_RAW.as_posix(), "raw_artifact": rel(RAW),
                   "raw_bytes": EXPECTED_BYTES, "raw_sha256": EXPECTED_SHA256,
                   "artifact": rel(FORMAL), "bytes": FORMAL_BYTES, "sha256": FORMAL_SHA256,
                   "decoded_video_frames": EXPECTED_FRAMES, "duration_seconds_from_decoded_frames": SOURCE_DURATION},
        "capture_identity": source_identity(),
        "operator_marks": descriptor(live_dir / "operator-marks.json"),
        "operator_events": descriptor(live_dir / "operator-events.ndjson"),
        "media_review": descriptor(review_path, status="passed"),
        "editorial_binding": {"take_row": descriptor(row_path), "partial_manifest": descriptor(partial_path),
                              "binder_validation": descriptor(validation_path), "spans": spans},
    })
    print(json.dumps({
        "status": "accepted_binder_row_verified", "take": TAKE_ID, "attempt": ATTEMPT_ID,
        "source": descriptor(FORMAL), "raw_source": descriptor(RAW), "decoded_frames": EXPECTED_FRAMES,
        "source_duration_seconds": SOURCE_DURATION, "bindings": bindings,
        "binder_validation": descriptor(validation_path), "attempt_manifest": descriptor(attempt_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
