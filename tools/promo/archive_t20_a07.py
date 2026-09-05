"""Archive and bind the usable T20/a07 Vivhite identity capture.

The formal identity windows completed before the operator runner encountered a
recorder-stop verification race.  OBS continued to capture the same clean game
screen until a separately observed manual stop.  This append-only writer keeps
that control failure visible, verifies the final media, binds only the clean
5-24 second source windows, snapshots current runtime/Workshop metadata, and
runs the production binder's per-take gate with no action evidence (T20 has no
formal action chain).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


REPO = pathlib.Path(__file__).resolve().parents[2]
RUN_ID = "run-20260903T0012-director-v2-a1"
RUN = REPO / "tools" / "promo" / "runs" / RUN_ID
TAKE_ID = "T20"
ATTEMPT_ID = "a07"
EXTERNAL_DIR = pathlib.Path(r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T20\a07")
EXTERNAL_RAW = EXTERNAL_DIR / "2026-09-04 20-35-30.mkv"
RECOVERY_SCREENSHOT = REPO / ".work" / "promo-review" / "t20-a07-obs-manual-stop.png"
RAW = RUN / "raw" / "takes" / TAKE_ID / f"{ATTEMPT_ID}.mkv"
STORYBOARD = REPO / "tools" / "promo" / "v2" / "storyboard.json"
RUNBOOK = REPO / "tools" / "promo" / "v2" / "capture-runbook.json"
FFPROBE = pathlib.Path(r"C:\ffmpeg\bin\ffprobe.exe")
FFMPEG = pathlib.Path(r"C:\ffmpeg\bin\ffmpeg.exe")
DEPLOYED = pathlib.Path(r"G:\SteamLibrary\steamapps\common\Slay the Spire 2\mods\Vivhite")
MOD_MANIFEST = REPO / "Vivhite" / "Vivhite.json"
WORKSHOP_MANIFEST = REPO / "workshop" / "workshop-item.json"
WORKSHOP_ENDPOINT = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
WORKSHOP_ID = "3793741497"

EXPECTED_BYTES = 142_159_448
EXPECTED_SHA256 = "E458DC263154B70967F91DEE24123EFA05DBE34CA779D522BCB871422DF9DFAD"
EXPECTED_FRAMES = 5_225
FPS = 60
SOURCE_DURATION = EXPECTED_FRAMES / FPS
GAME_PROCESS_ID = "SlayTheSpire2.exe-16428-2026-09-03T14-12-39.1941103Z"
GAME_STARTED_UTC = "2026-09-03T14:12:39.1941103Z"
RECORDER_PROCESS_ID = "obs64.exe-23124-2026-09-04T12-35-28.4331324Z"
RECORDER_STARTED_UTC = "2026-09-04T12:35:28.4331324Z"
SOURCE_ARTIFACT_ID = "T20-a07-E458DC263154B709"

SPANS = [
    {"subshot_id": "S01-06-question-bridge", "begin": 300, "end": 660},
    {"subshot_id": "S01-07-main-title", "begin": 660, "end": 960},
    {"subshot_id": "S01-08-main-title-continuation", "begin": 960, "end": 1_260},
    {"subshot_id": "S10-10-idle-cta", "begin": 300, "end": 1_020},
    {"subshot_id": "S10-11-version-and-workshop-status", "begin": 1_020, "end": 1_440},
]


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
        raise RuntimeError(f"required source missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size != source.stat().st_size or sha256(target) != sha256(source):
            raise RuntimeError(f"refusing to replace differing artifact: {target}")
        return
    with source.open("rb") as source_stream, target.open("xb") as target_stream:
        shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
        target_stream.flush()


def run_json(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("tool JSON root is not an object")
    return payload


def exact_probe(path: pathlib.Path) -> dict[str, Any]:
    return run_json(
        [
            str(FFPROBE), "-v", "error", "-count_frames", "-count_packets",
            "-show_streams", "-show_format", "-of", "json", str(path),
        ]
    )


def extract_anchors(source: pathlib.Path, output_dir: pathlib.Path) -> dict[int, pathlib.Path]:
    frames = [300, 659, 660, 959, 960, 1_019, 1_020, 1_259, 1_439]
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = [output_dir / f"selected-{index:02d}.png" for index in range(1, len(frames) + 1)]
    if not all(path.exists() for path in expected):
        if any(path.exists() for path in expected):
            raise RuntimeError("partial T20 anchor extraction exists")
        expression = "+".join(f"eq(n\\,{frame})" for frame in frames)
        subprocess.run(
            [
                str(FFMPEG), "-v", "error", "-i", str(source), "-vf",
                f"select={expression}", "-fps_mode", "passthrough",
                str(output_dir / "selected-%02d.png"),
            ],
            check=True,
        )
    if not all(path.is_file() and path.stat().st_size > 0 for path in expected):
        raise RuntimeError("not every exact T20 source-frame anchor was extracted")
    return dict(zip(frames, expected, strict=True))


def capture_identity() -> dict[str, str]:
    return {
        "session_id": RUN_ID,
        "game_run_id": "native-vivhite-character-select",
        "game_process_id": GAME_PROCESS_ID,
        "source_video_artifact_id": SOURCE_ARTIFACT_ID,
        "run_id": RUN_ID,
        "take_id": TAKE_ID,
    }


def evidence_ref(ref_id: str, role: str, path: pathlib.Path) -> dict[str, Any]:
    return {"ref_id": ref_id, "role": role, "status": "verified", **descriptor(path)}


def query_workshop() -> tuple[bytes, dict[str, Any]]:
    body = urllib.parse.urlencode({"itemcount": "1", "publishedfileids[0]": WORKSHOP_ID}).encode("ascii")
    request = urllib.request.Request(
        WORKSHOP_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    details = payload.get("response", {}).get("publishedfiledetails", [])
    if len(details) != 1 or str(details[0].get("publishedfileid")) != WORKSHOP_ID:
        raise RuntimeError("Steam Web API did not return the requested Workshop item")
    return raw, details[0]


def main() -> int:
    observed_at = utc_now()
    if EXTERNAL_RAW.stat().st_size != EXPECTED_BYTES or sha256(EXTERNAL_RAW) != EXPECTED_SHA256:
        raise RuntimeError("sealed T20/a07 source no longer matches its final descriptor")
    copy_immutable(EXTERNAL_RAW, RAW)
    if RAW.stat().st_size != EXPECTED_BYTES or sha256(RAW) != EXPECTED_SHA256:
        raise RuntimeError("preserved T20/a07 raw is not byte-identical")

    evidence_dir = RUN / "evidence" / "takes" / TAKE_ID / ATTEMPT_ID
    capture_dir = RUN / "capture" / "takes" / TAKE_ID / ATTEMPT_ID
    probe_dir = RUN / "probe" / "takes" / TAKE_ID / ATTEMPT_ID
    live_dir = evidence_dir / "live"
    for name in (
        "operator-marks.partial.json", "checkpoint-before-mark.png",
        "obs-recording-confirmed.png", "operator-frame-begin.png",
        "operator-identity-end.png", "operator-frame-end.png", "obs-before-stop.png",
    ):
        copy_immutable(EXTERNAL_DIR / name, live_dir / name)
    copy_immutable(RECOVERY_SCREENSHOT, live_dir / "obs-manual-stop-recovery.png")

    anchors = extract_anchors(RAW, evidence_dir / "anchors")
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(RAW), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "NUL"],
        check=True,
    )
    probe_raw = exact_probe(RAW)
    streams = probe_raw["streams"]
    video = next(item for item in streams if item.get("codec_type") == "video")
    audio = next(item for item in streams if item.get("codec_type") == "audio")
    fmt = probe_raw["format"]
    if int(video["nb_read_frames"]) != EXPECTED_FRAMES or int(video["nb_read_packets"]) != EXPECTED_FRAMES:
        raise RuntimeError("T20/a07 exact decoded video count is not 5225")

    source_probe_path = probe_dir / "source-probe.json"
    write_json(
        source_probe_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_source_probe_v2",
            "status": "completed",
            "observed_at_utc": observed_at,
            "source": {"path": rel(RAW), "bytes": EXPECTED_BYTES, "sha256": EXPECTED_SHA256},
            "result": {
                "streams": [video, audio],
                "format": {
                    "format_name": fmt["format_name"], "start_time": fmt["start_time"],
                    "duration": fmt["duration"], "size": fmt["size"], "bit_rate": fmt.get("bit_rate"),
                },
            },
            "derived": {
                "decoded_video_frames": EXPECTED_FRAMES,
                "frame_duration_seconds": SOURCE_DURATION,
                "ffprobe_reported_duration_seconds": float(fmt["duration"]),
                "container_minus_video_frame_duration_seconds": float(fmt["duration"]) - SOURCE_DURATION,
                "video_packets": int(video["nb_read_packets"]),
                "audio_packets": int(audio["nb_read_packets"]),
                "audio_frames": int(audio["nb_read_frames"]),
                "full_decode_status": "passed_no_errors",
            },
            "tools": {
                "ffprobe": {"path": str(FFPROBE), "sha256": sha256(FFPROBE)},
                "ffmpeg": {"path": str(FFMPEG), "sha256": sha256(FFMPEG)},
            },
        },
    )

    mod_manifest = json.loads(MOD_MANIFEST.read_text(encoding="utf-8-sig"))
    runtime_version = str(mod_manifest["version"])
    deployed_files = []
    for name in ("Vivhite.dll", "Vivhite.json", "Vivhite.pck"):
        path = DEPLOYED / name
        deployed_files.append({"name": name, "path": path.as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    runtime_manifest_path = evidence_dir / "runtime-manifest.json"
    write_json(
        runtime_manifest_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_runtime_manifest_v2",
            "status": "verified_current_deployment",
            "ref_id": "T20-runtime-manifest",
            "role": "runtime.manifest",
            "capture_identity": capture_identity(),
            "observed_at_utc": observed_at,
            "runtime": {
                "version": runtime_version,
                "mod_id": str(mod_manifest["id"]),
                "name": str(mod_manifest["name"]),
                "min_game_version": str(mod_manifest["min_game_version"]),
                "signature_card_count": 61,
            },
            "manifest_source": {
                "path": MOD_MANIFEST.relative_to(REPO).as_posix(),
                "bytes": MOD_MANIFEST.stat().st_size,
                "sha256": sha256(MOD_MANIFEST),
            },
            "active_game_process": {"pid": 16428, "identity": GAME_PROCESS_ID, "started_utc": GAME_STARTED_UTC},
            "deployed_artifacts": deployed_files,
        },
    )

    api_raw, remote = query_workshop()
    api_snapshot_path = evidence_dir / "steam-workshop-api-response.snapshot.json"
    write_bytes(api_snapshot_path, api_raw)
    if int(remote.get("result", 0)) != 1 or int(remote.get("visibility", -1)) != 0 or int(remote.get("banned", 1)) != 0:
        raise RuntimeError("current Steam metadata does not prove a public, unbanned Workshop item")
    description = str(remote.get("description", ""))
    if runtime_version not in description:
        raise RuntimeError("current Steam Workshop description does not mention the runtime version")
    workshop_manifest = json.loads(WORKSHOP_MANIFEST.read_text(encoding="utf-8-sig"))
    if str(workshop_manifest["published_file_id"]) != WORKSHOP_ID or str(workshop_manifest["version"]) != runtime_version:
        raise RuntimeError("local Workshop metadata does not match item ID/runtime version")
    workshop_receipt_path = evidence_dir / "workshop-status-receipt.json"
    write_json(
        workshop_receipt_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_workshop_readonly_metadata_v2",
            "status": "verified_current_remote_readonly_metadata",
            "ref_id": "T20-workshop-status-receipt",
            "role": "workshop.readonly_metadata",
            "queried_at_utc": observed_at,
            "request": {
                "method": "POST", "endpoint": WORKSHOP_ENDPOINT,
                "form": {"itemcount": 1, "publishedfileids[0]": WORKSHOP_ID},
                "authentication": "none_public_readonly_endpoint",
            },
            "raw_response": descriptor(api_snapshot_path, media_type="application/json"),
            "item": {
                "published_file_id": str(remote["publishedfileid"]),
                "consumer_app_id": int(remote["consumer_app_id"]),
                "title": str(remote["title"]),
                "result": int(remote["result"]),
                "visibility_numeric": int(remote["visibility"]),
                "visibility_interpretation": "public",
                "banned": bool(int(remote["banned"])),
                "time_created_unix": int(remote["time_created"]),
                "time_updated_unix": int(remote["time_updated"]),
                "file_size": int(remote["file_size"]),
                "description_mentions_runtime_version": True,
                "runtime_version": runtime_version,
            },
            "display_value": "public",
            "conclusion": "Steam's public read-only API currently returns result=1, visibility=0 and banned=0 for the existing Vivhite Workshop item.",
            "local_metadata": {
                "path": WORKSHOP_MANIFEST.relative_to(REPO).as_posix(),
                "bytes": WORKSHOP_MANIFEST.stat().st_size,
                "sha256": sha256(WORKSHOP_MANIFEST),
            },
        },
    )

    lineage_path = evidence_dir / "lineage.json"
    write_json(
        lineage_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_multispan_lineage_v2",
            "status": "verified_same_new_raw_take",
            "ref_id": "T20-lineage",
            "role": "runtime.manifest",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "source": {"path": rel(RAW), "bytes": EXPECTED_BYTES, "sha256": EXPECTED_SHA256, "fps": FPS},
            "allowed_uses": ["main_title_silhouette", "question_bridge", "vivhite_idle", "version_status_overlay"],
            "forbidden_uses": ["build_route_montage"],
            "bindings": [
                {
                    "subshot_id": span["subshot_id"],
                    "source_interval_half_open_frames": [span["begin"], span["end"]],
                    "in_seconds": span["begin"] / FPS,
                    "out_seconds": span["end"] / FPS,
                    "duration_seconds": (span["end"] - span["begin"]) / FPS,
                }
                for span in SPANS
            ],
            "overlap_policy": "intentional_editorial_reuse_within_one_independent_new_raw_take",
            "visual_identity": {"character": "白绮", "hp": "78/78", "score": 99, "starting_relic": "孤高冠冕"},
            "control_note": "The formal windows finished before the runner's stop verification race. OBS then captured the same clean character-select screen until separately observed manual stop; no later frames are bound.",
        },
    )

    frame_begin_path = evidence_dir / "frame-begin.json"
    frame_end_path = evidence_dir / "frame-end.json"
    common_source = {
        "path": rel(RAW), "bytes": EXPECTED_BYTES, "sha256": EXPECTED_SHA256,
        "decoded_frames": EXPECTED_FRAMES, "fps": FPS,
    }
    write_json(
        frame_begin_path,
        {
            "schema_version": 2, "kind": "vivhite_promo_frame_marker_v2", "status": "verified",
            "ref_id": "T20-frame-begin", "role": "frame.begin", "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
            "source": common_source,
            "frame": {"source_zero_based": 300, "time_seconds": 5.0, "artifact": descriptor(anchors[300], media_type="image/png")},
            "visible": {"screen": "CHARACTER_SELECT", "character": "白绮", "hp": "78/78", "score": 99, "starting_relic": "孤高冠冕", "clean_game_only_surface": True},
        },
    )
    write_json(
        frame_end_path,
        {
            "schema_version": 2, "kind": "vivhite_promo_frame_marker_v2", "status": "verified",
            "ref_id": "T20-frame-end", "role": "frame.end", "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
            "source": common_source,
            "frame": {"source_zero_based": 1_439, "time_seconds": 1_439 / FPS, "artifact": descriptor(anchors[1_439], media_type="image/png")},
            "visible": {"screen": "CHARACTER_SELECT", "character": "白绮", "clean_game_only_surface": True},
        },
    )

    recovery_path = evidence_dir / "recording-boundary-recovery.json"
    write_json(
        recovery_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_recording_boundary_recovery_v2",
            "status": "passed_media_sealed_after_separate_manual_stop",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "failed_runner_receipt": descriptor(live_dir / "operator-marks.partial.json"),
            "failure_boundary": {
                "formal_display_complete_before_failure": True,
                "runner_error": "Get-FileHash encountered a sharing violation while OBS was still recording",
                "automatic_stop_not_proven": True,
            },
            "manual_stop_recovery": {
                "screenshot": descriptor(live_dir / "obs-manual-stop-recovery.png", media_type="image/png"),
                "visual_status": "OBS Start Recording button and saved-recording status visible after manual stop",
                "final_source": {"path": rel(RAW), "bytes": EXPECTED_BYTES, "sha256": EXPECTED_SHA256},
                "last_write_utc": "2026-09-04T12:36:58.4666863Z",
                "stable_and_hash_readable": True,
            },
            "source_local_recording_bounds": {
                "start_frame": 1, "end_frame_exclusive": EXPECTED_FRAMES + 1,
                "decoded_frame_count": EXPECTED_FRAMES,
                "exact_decoded_duration_seconds": SOURCE_DURATION,
                "container_duration_seconds": float(fmt["duration"]),
                "started_monotonic_seconds": 0.0,
                "stopped_monotonic_seconds": SOURCE_DURATION,
                "coordinate_system": "source-local decoded media time",
            },
            "formal_bound_union": {"begin_frame": 300, "end_frame_exclusive": 1_440, "all_frames_before_runner_failure": True},
        },
    )

    review_path = evidence_dir / "technical-visual-review.json"
    reviewed_frames = sorted(anchors)
    write_json(
        review_path,
        {
            "schema_version": 2,
            "kind": "vivhite_promo_technical_visual_review_v2",
            "status": "passed_formal_windows",
            "take_id": TAKE_ID,
            "attempt_id": ATTEMPT_ID,
            "source": common_source,
            "technical": {
                "full_decode": "passed_no_errors", "duration_seconds": SOURCE_DURATION,
                "video": "H.264 High 1920x1080 yuv420p progressive CFR 60/1",
                "audio": "AAC-LC 48000 Hz stereo",
            },
            "visual": {
                "character_identity": "白绮", "hp": "78/78", "score": 99, "starting_relic": "孤高冠冕",
                "character_animation_present": True, "negative_space_available": True,
                "forbidden_elements": [],
                "forbidden_surface_review": {
                    "old_ironclad_replacement": False, "console": False, "pause_menu": False,
                    "obs_or_taskbar": False, "system_cursor": False, "brain_ai_or_ascend_vision": False,
                    "debug_or_modded_label": False, "loading_screen": False,
                },
            },
            "reviewed_source_frames": reviewed_frames,
            "anchors": [descriptor(anchors[frame], media_type="image/png") for frame in reviewed_frames],
            "formal_review_scope": {"begin_frame": 300, "end_frame_exclusive": 1_440},
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
            "normalization": {"required": False, "operation": "byte_identical_source", "raw_source_preserved": True},
        },
    )

    refs = [
        evidence_ref("T20-frame-begin", "frame.begin", frame_begin_path),
        evidence_ref("T20-runtime-manifest", "runtime.manifest", runtime_manifest_path),
        evidence_ref("T20-workshop-status-receipt", "workshop.readonly_metadata", workshop_receipt_path),
        evidence_ref("T20-lineage", "runtime.manifest", lineage_path),
        evidence_ref("T20-frame-end", "frame.end", frame_end_path),
    ]
    spans = [
        {"subshot_id": span["subshot_id"], "in_seconds": span["begin"] / FPS, "out_seconds": span["end"] / FPS}
        for span in SPANS
    ]
    source_row = {
        "artifact": rel(RAW), "duration_seconds": SOURCE_DURATION, "bytes": EXPECTED_BYTES, "sha256": EXPECTED_SHA256,
        "original_obs_path": EXTERNAL_RAW.as_posix(), "capture_identity": capture_identity(),
        "game_process": {"pid": 16428, "identity": GAME_PROCESS_ID, "started_utc": GAME_STARTED_UTC},
        "recorder_process": {"pid": 23124, "identity": RECORDER_PROCESS_ID, "started_utc": RECORDER_STARTED_UTC},
        "recording": {"start_frame": 1, "end_frame": EXPECTED_FRAMES + 1, "started_monotonic_seconds": 0.0, "stopped_monotonic_seconds": SOURCE_DURATION},
        "ffprobe": descriptor(source_probe_path),
        "media_lineage": descriptor(media_lineage_path, normalization_required=False, raw_source_preserved=True),
    }
    template_values = [
        {"field": "runtime_version", "evidence_ref": "T20-runtime-manifest", "json_pointer": "/runtime/version", "display_value": runtime_version},
        {"field": "workshop_status", "evidence_ref": "T20-workshop-status-receipt", "json_pointer": "/display_value", "display_value": "public"},
    ]
    take = {
        "take_id": TAKE_ID, "independent": True, "source": source_row,
        "evidence_refs": refs, "template_values": template_values, "action_evidence": [], "spans": spans,
    }
    row = {
        "schema_version": 2, "kind": "vivhite_promo_take_row_v2", "status": "production_candidate",
        "run_id": RUN_ID, "attempt_id": ATTEMPT_ID, "take": take,
        "editorial_boundary": {
            "formal_bound_union_frames": [300, 1_440],
            "formal_spans": [
                {**span, "duration_frames": round((span["out_seconds"] - span["in_seconds"]) * FPS)}
                for span in spans
            ],
            "overlap_policy": "intentional same-source editorial reuse allowed by T19_T20_CAPTURE_RECIPE.md",
            "post_formal_unbound_tail": {"begin_frame": 1_440, "end_frame_exclusive": EXPECTED_FRAMES, "reason": "recorder stop-control delay; same clean screen but not needed by the edit"},
        },
    }
    row_path = capture_dir / "take-row.production.json"
    partial_path = capture_dir / "take-manifest.t20-only.json"
    write_json(row_path, row)
    write_json(
        partial_path,
        {
            "schema_version": 2, "kind": "vivhite_promo_take_manifest_v2",
            "batch_id": f"{RUN_ID}-t20-a07-partial", "run_id": RUN_ID,
            "source_strategy": "independent_take_files", "from_legacy_a4": False,
            "partial_scope": {"take_ids": [TAKE_ID], "production_binder_expected_global_status": "blocked_until_all_required_takes_exist"},
            "takes": [take],
        },
    )

    sys.path.insert(0, str(REPO / "tools" / "promo"))
    from vivhite_promo import director_v2, production_binder_v2  # noqa: PLC0415

    board = director_v2.load_storyboard_v2(STORYBOARD)
    board_take = next(item for item in board["takes"] if item["take_id"] == TAKE_ID)
    bindings = {
        span["subshot_id"]: {"take_id": TAKE_ID, "in_seconds": span["begin"] / FPS, "out_seconds": span["end"] / FPS}
        for span in SPANS
    }
    runtime = production_binder_v2._bind_take(
        root=RUN, take_row=take, board_take=board_take, board=board,
        normalized_take={"take_id": TAKE_ID}, bindings=bindings,
    )
    try:
        production_binder_v2.build_production_edl_v2(STORYBOARD, partial_path, artifact_root=RUN)
    except production_binder_v2.ProductionBinderV2Error as exc:
        public_error = f"{type(exc).__name__}: {exc}"
        if "take manifest must bind 19 or 20 independent takes" not in str(exc):
            raise
    else:
        raise RuntimeError("partial T20-only manifest unexpectedly passed the global binder")

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
                "take_row": descriptor(row_path), "partial_manifest": descriptor(partial_path),
                "source": descriptor(RAW), "source_probe": descriptor(source_probe_path),
            },
            "per_take_binder_validation": {
                "entry_point": "vivhite_promo.production_binder_v2._bind_take", "exit_code": 0, "status": "passed",
                "verified": {
                    "take_id": runtime.take_id, "source_path": runtime.source.relative_path,
                    "source_bytes": runtime.source.bytes, "source_sha256": runtime.source.sha256,
                    "duration_seconds": runtime.probe["duration_seconds"], "frame_count": runtime.probe["frame_count"],
                    "video": "H.264 yuv420p 1920x1080 60 FPS", "audio": "AAC 48000 Hz stereo",
                    "recording_start_frame": runtime.recording["start_frame"], "recording_end_frame": runtime.recording["end_frame"],
                    "evidence_ref_count": len(runtime.evidence), "action_contract_count": len(runtime.action_contracts),
                    "template_values": {field: dict(value) for field, value in runtime.template_values.items()},
                },
                "span_assertions": {"status": "passed", "bindings": bindings, "formal_union_frames": [300, 1_440], "playback_speed": 1},
            },
            "semantic_assertions": {
                "status": "passed", "character": "白绮", "runtime_version": runtime_version,
                "workshop_status": "public", "build_route_use": False,
                "manual_stop_recovery_disclosed": True, "formal_windows_end_before_runner_failure": True,
            },
            "public_full_manifest_binder_invocation": {
                "entry_point": "vivhite_promo.production_binder_v2.build_production_edl_v2",
                "take_manifest": rel(partial_path), "output_created": False, "exit_code": 1,
                "status": "expected_global_failure", "exact_error": public_error,
            },
            "production_claim": {
                "t20_take_row": "per-take binder verified and ready to merge into the complete independent take manifest",
                "master_540_edl": "not generated; correctly pending all required independent takes",
                "raw_capture": "preserved byte-identical; only the reviewed 5-24 second windows are bound",
            },
        },
    )

    attempt_path = capture_dir / "attempt-manifest.json"
    write_json(
        attempt_path,
        {
            "schema_version": 2, "kind": "vivhite_promo_take_attempt_v2", "run_id": RUN_ID,
            "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID, "status": "accepted_binder_row_verified",
            "production_eligible": True,
            "source": {
                "original_path": EXTERNAL_RAW.as_posix(), "artifact": rel(RAW), "bytes": EXPECTED_BYTES,
                "sha256": EXPECTED_SHA256, "decoded_video_frames": EXPECTED_FRAMES,
                "duration_seconds_from_decoded_frames": SOURCE_DURATION, "ffprobe": descriptor(source_probe_path),
            },
            "director_contract": {
                "storyboard": {"path": STORYBOARD.relative_to(REPO).as_posix(), "bytes": STORYBOARD.stat().st_size, "sha256": sha256(STORYBOARD)},
                "capture_runbook": {"path": RUNBOOK.relative_to(REPO).as_posix(), "bytes": RUNBOOK.stat().st_size, "sha256": sha256(RUNBOOK)},
                "subshot_ids": [span["subshot_id"] for span in SPANS], "formal_action_chain": None,
                "action_evidence": [], "same_source_overlap_allowed": True,
            },
            "control_incident": {
                "status": "disclosed_and_recovered", "formal_windows_affected": False,
                "recording_boundary_recovery": descriptor(recovery_path),
            },
            "runtime_manifest": descriptor(runtime_manifest_path, status="verified"),
            "workshop_status_receipt": descriptor(workshop_receipt_path, status="verified_current_public"),
            "lineage": descriptor(lineage_path, status="verified_same_new_raw_take"),
            "media_review": descriptor(review_path, status="passed_formal_windows"),
            "editorial_binding": {
                "take_row": descriptor(row_path), "partial_manifest": descriptor(partial_path),
                "binder_validation": descriptor(validation_path), "spans": spans,
            },
        },
    )
    print(
        json.dumps(
            {
                "status": "accepted_binder_row_verified", "take": TAKE_ID, "attempt": ATTEMPT_ID,
                "source": descriptor(RAW), "decoded_frames": EXPECTED_FRAMES,
                "source_duration_seconds": SOURCE_DURATION, "formal_spans": spans,
                "runtime_version": runtime_version, "workshop_status": "public",
                "binder_validation": descriptor(validation_path), "attempt_manifest": descriptor(attempt_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
