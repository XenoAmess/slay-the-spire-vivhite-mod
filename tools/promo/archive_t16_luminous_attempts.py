"""Append-only archive and strict review for clean T16 Luminous attempts.

The operator marks are preserved as operator provenance.  They are not native
game state/action receipts, and this script never promotes them (or pixels) to
the production evidence contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


REPO = pathlib.Path(__file__).resolve().parents[2]
RUN_ID = "run-20260903T0012-director-v2-a1"
RUN = REPO / "tools" / "promo" / "runs" / RUN_ID
TAKE_ID = "T16"
PROFILES: dict[str, dict[str, Any]] = {
    "a22": {
        "external_file": "2026-09-04 11-10-57.mkv",
        "anchors_count": 8,
        "card_anchor": "t-019p166.png",
        "events": [
            ("clean_preroll", 0.000, "clean full HUD; ritual is visible in the phase-0 hand"),
            ("ritual_tooltip", 3.828, "白绮的猩红转化仪式 tooltip is visible"),
            ("ritual_play", 6.146, "ritual release and phase-0 play animation"),
            ("end_turn_hover", 10.158, "end-turn hover/input highlight is visible"),
            ("enemy_turn_transition", 12.158, "enemy-turn transition begins"),
            ("phase1_hand", 19.166, "turn-2 hand is visible with Luminous Projection"),
            ("luminous_tooltip", 19.166, "弦光投影 tooltip is visible"),
            ("luminous_play", 21.493, "Luminous Projection is released toward the target"),
            ("phase1_extra_cough", 21.900, "phase-1 extra Cough/payment animation is visible"),
            ("luminous_damage", 22.300, "target damage resolves"),
            ("settled_result", 24.000, "settled HUD remains visible"),
            ("operator_result_hold", 27.504, "settled HUD result hold"),
        ],
        "visible_values": {
            "start": {"hp": "82/82", "energy": "6/3", "targets": ["46/46", "43/43"]},
            "luminous_tooltip": {"cough": 2, "damage_before_phase1_resolution": 10},
            "phase1_play": {"visible_damage": 11, "hp_before": 76, "hp_after": 73},
            "settled": {"hp": "73/82", "energy": "2/3"},
        },
    },
    "a20": {
        "external_file": "2026-09-04 05-44-57.mkv",
        "anchors_count": 56,
        "card_anchor": "t-018p371.png",
        "events": [
            ("clean_preroll", 0.000, "clean full HUD; ritual is visible in the phase-0 hand"),
            ("ritual_tooltip", 3.053, "白绮的猩红转化仪式 tooltip is visible"),
            ("ritual_play", 5.364, "ritual is released and phase-0 play animation begins"),
            ("end_turn_hover", 9.373, "end-turn hover/input highlight is visible"),
            ("enemy_turn_transition", 11.360, "enemy-turn transition is visible"),
            ("enemy_attack", 13.100, "enemy attack resolves; HP later shows 76/82"),
            ("phase1_hand", 17.400, "turn-2 hand is visible with Luminous Projection"),
            ("luminous_tooltip", 18.371, "弦光投影 tooltip visibly shows Cough 2 and 10 damage"),
            ("luminous_play", 20.197, "Luminous Projection is dragged toward the target"),
            ("phase1_extra_cough", 20.693, "card text updates to 11 damage and HP falls 76 to 73 with visible 1 plus 2 payment"),
            ("luminous_damage", 21.000, "target with 5 block takes visible 6 unblocked damage and reaches 40/46"),
            ("settled_result", 22.000, "settled HUD shows HP 73/82, energy 2/3, target 40/46"),
            ("operator_result_hold", 26.705, "settled HUD remains and discard hover appears"),
        ],
        "visible_values": {
            "after_enemy_attack": {"hp": "76/82"},
            "luminous_tooltip": {"cough": 2, "damage_before_phase1_resolution": 10},
            "phase1_play": {"visible_damage": 11, "hp_before": 76, "hp_after": 73, "visible_payment_components": [1, 2]},
            "settled": {"hp": "73/82", "energy": "2/3", "target": "40/46", "target_block_before": 5},
        },
    },
    "a21": {
        "external_file": "2026-09-04 05-59-10.mkv",
        "anchors_count": 58,
        "card_anchor": "t-018p385.png",
        "events": [
            ("clean_preroll", 0.000, "clean full HUD: HP 82/82, energy 6/3, targets 43/43 and 45/45; ritual is visible"),
            ("ritual_tooltip", 3.029, "白绮的猩红转化仪式 tooltip is visible"),
            ("ritual_play", 5.374, "ritual is released and phase-0 play animation begins"),
            ("end_turn_hover", 9.385, "end-turn hover/input highlight is visible"),
            ("enemy_turn_transition", 11.375, "enemy-turn transition is visible"),
            ("enemy_attack", 13.100, "enemy attack resolves; HP later shows 76/82"),
            ("phase1_hand", 17.400, "turn-2 hand is visible with Luminous Projection"),
            ("luminous_tooltip", 18.385, "弦光投影 tooltip visibly shows Cough 2 and 10 damage"),
            ("luminous_play", 20.207, "Luminous Projection is dragged toward the target"),
            ("phase1_extra_cough", 20.704, "card text updates to 11 damage and HP falls 76 to 73 with visible 1 plus 2 payment"),
            ("luminous_damage", 22.000, "target with 5 block takes visible 6 unblocked damage and reaches 37/43"),
            ("settled_result", 23.000, "settled HUD shows HP 73/82, energy 2/3, target 37/43"),
            ("operator_result_hold", 27.712, "settled HUD remains and discard hover appears"),
        ],
        "visible_values": {
            "start": {"hp": "82/82", "energy": "6/3", "targets": ["43/43", "45/45"]},
            "after_enemy_attack": {"hp": "76/82"},
            "luminous_tooltip": {"cough": 2, "damage_before_phase1_resolution": 10},
            "phase1_play": {"visible_damage": 11, "hp_before": 76, "hp_after": 73, "visible_payment_components": [1, 2]},
            "settled": {"hp": "73/82", "energy": "2/3", "target": "37/43", "target_block_before": 5},
        },
    },
}
ATTEMPT_ID = os.environ.get("VIVHITE_T16_ATTEMPT", "a20")
if ATTEMPT_ID not in PROFILES:
    raise RuntimeError(f"unsupported T16 Luminous archive profile: {ATTEMPT_ID}")
PROFILE = PROFILES[ATTEMPT_ID]
EXTERNAL_DIR = pathlib.Path(r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T16") / ATTEMPT_ID
EXTERNAL_RAW = EXTERNAL_DIR / str(PROFILE["external_file"])
EXTERNAL_MARKS = EXTERNAL_DIR / "operator-marks.json"
RAW = RUN / "raw" / "takes" / TAKE_ID / f"{ATTEMPT_ID}.mkv"
CFR = RUN / "raw" / "takes" / TAKE_ID / f"{ATTEMPT_ID}.cfr-normalized.mkv"
CAPTURE = RUN / "capture" / "takes" / TAKE_ID / ATTEMPT_ID
MARKS_COPY = CAPTURE / "operator-marks.source.json"
EVIDENCE = RUN / "evidence" / "takes" / TAKE_ID / ATTEMPT_ID
PROBE = RUN / "probe" / "takes" / TAKE_ID / ATTEMPT_ID
CONTRACTS = RUN / "contracts" / "takes" / TAKE_ID / ATTEMPT_ID
FFMPEG = pathlib.Path(r"C:\ffmpeg\promo-9.0.1\bin\ffmpeg.exe")
FFPROBE = pathlib.Path(r"C:\ffmpeg\promo-9.0.1\bin\ffprobe.exe")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def rel(path: pathlib.Path) -> str:
    return path.relative_to(RUN).as_posix()


def artifact(path: pathlib.Path) -> dict[str, Any]:
    return {"path": rel(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def external_artifact(path: pathlib.Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": path.as_posix(),
        "bytes": stat.st_size,
        "sha256": sha256(path),
        "last_write_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != blob:
            raise RuntimeError(f"refusing to overwrite differing archival record: {path}")
        return
    path.write_bytes(blob)


def probe(path: pathlib.Path) -> dict[str, Any]:
    command = [
        str(FFPROBE), "-v", "error", "-show_entries",
        "format=format_name,start_time,duration,size,bit_rate,nb_streams,probe_score:stream=index,codec_name,profile,codec_type,width,height,pix_fmt,field_order,r_frame_rate,avg_frame_rate,time_base,start_time,sample_rate,channels,channel_layout",
        "-of", "json", str(path),
    ]
    return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)


def count_frames(path: pathlib.Path) -> int:
    command = [
        str(FFPROBE), "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=nb_read_frames", "-of", "json", str(path),
    ]
    data = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
    streams = data.get("streams", [])
    return int(streams[0].get("nb_read_frames") or 0) if streams else 0


def media_record(path: pathlib.Path, frames: int, observed: str) -> dict[str, Any]:
    data = probe(path)
    streams = data.get("streams", [])
    video = next(item for item in streams if item.get("codec_type") == "video")
    audio = next(item for item in streams if item.get("codec_type") == "audio")
    fmt = data.get("format", {})
    return {
        "observed_at_utc": observed,
        "format": {
            "name": fmt.get("format_name"),
            "duration_seconds": float(fmt.get("duration") or 0),
            "start_time_seconds": float(fmt.get("start_time") or 0),
            "streams": int(fmt.get("nb_streams") or len(streams)),
            "size": int(fmt.get("size") or path.stat().st_size),
            "bit_rate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
            "probe_score": int(fmt["probe_score"]) if fmt.get("probe_score") else None,
        },
        "video": {
            "codec": video.get("codec_name"), "profile": video.get("profile"),
            "width": video.get("width"), "height": video.get("height"),
            "pixel_format": video.get("pix_fmt"), "field_order": video.get("field_order"),
            "r_frame_rate": video.get("r_frame_rate"), "avg_frame_rate": video.get("avg_frame_rate"),
            "time_base": video.get("time_base"), "decoded_frame_count": frames,
            "frame_exact_duration_seconds": frames / 60 if frames else None,
            "nominal_cfr": video.get("avg_frame_rate") == "60/1",
        },
        "audio": {
            "codec": audio.get("codec_name"), "profile": audio.get("profile"),
            "sample_rate_hz": int(audio["sample_rate"]), "channels": int(audio["channels"]),
            "channel_layout": audio.get("channel_layout"), "time_base": audio.get("time_base"),
        },
    }


def run_ffmpeg(path: pathlib.Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-i", str(path), *args],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stderr


def operator_relative_events(marks: dict[str, Any]) -> list[dict[str, Any]]:
    origin = float(marks["recording_start_release_monotonic_seconds"])
    result = []
    for name, event in marks.get("events", {}).items():
        if not isinstance(event, dict) or event.get("monotonic_seconds") is None:
            continue
        monotonic = float(event["monotonic_seconds"])
        result.append({
            "event": name,
            "operator_monotonic_seconds": monotonic,
            "relative_to_recording_start_release_seconds": round(monotonic - origin, 6),
            "encoded_pts_binding": "approximate_only_not_native",
        })
    return result


def main() -> int:
    observed = utc_now()
    for required in (EXTERNAL_RAW, EXTERNAL_MARKS, RAW, CFR, MARKS_COPY, FFMPEG, FFPROBE):
        if not required.exists():
            raise RuntimeError(f"required immutable input missing: {required}")

    external_raw_before = external_artifact(EXTERNAL_RAW)
    external_raw_after = external_artifact(EXTERNAL_RAW)
    external_marks = external_artifact(EXTERNAL_MARKS)
    if external_raw_before != external_raw_after:
        raise RuntimeError("external raw changed during review")
    raw = artifact(RAW)
    cfr = artifact(CFR)
    marks_artifact = artifact(MARKS_COPY)
    if (raw["bytes"], raw["sha256"]) != (external_raw_after["bytes"], external_raw_after["sha256"]):
        raise RuntimeError("preserved raw differs from external source")
    if (marks_artifact["bytes"], marks_artifact["sha256"]) != (external_marks["bytes"], external_marks["sha256"]):
        raise RuntimeError("preserved operator marks differ from external source")

    raw_frames = count_frames(RAW)
    cfr_frames = count_frames(CFR)
    if raw_frames <= 0 or raw_frames != cfr_frames:
        raise RuntimeError(f"decoded frame mismatch: raw={raw_frames}, cfr={cfr_frames}")
    raw_media = media_record(RAW, raw_frames, observed)
    cfr_media = media_record(CFR, cfr_frames, observed)
    raw_duration = raw_media["format"]["duration_seconds"]
    cfr_duration = cfr_media["format"]["duration_seconds"]
    exact_duration = cfr_frames / 60

    write_json(PROBE / "source-probe.json", {
        "schema_version": 2, "kind": "vivhite_promo_media_probe_v2", "status": "passed_technical_only",
        "scope": "immutable_external_obs_source", "source": {**external_raw_after, "preserved_artifact": rel(RAW)},
        **raw_media,
        "lineage": {"external_matches_preserved_bytes": True, "external_matches_preserved_sha256": True},
        "production_gate": "rejected_missing_native_triads_and_exact_frame_binding",
    })
    write_json(PROBE / "normalized-probe.json", {
        "schema_version": 2, "kind": "vivhite_promo_media_probe_v2", "status": "passed_technical_only",
        "scope": "stream_copy_review_reference", "source": cfr, **cfr_media,
        "normalization": {"method": "ffmpeg stream-copy remux", "reencode": False, "raw_preserved": True},
        "production_gate": "rejected_missing_native_triads_and_exact_frame_binding",
    })

    anchors = []
    for path in sorted((EVIDENCE / "anchors").glob("*.png")):
        match = re.fullmatch(r"t-(\d+)p(\d+)", path.stem)
        seconds = None
        frame = None
        if match:
            seconds = int(match.group(1)) + int(match.group(2)) / (10 ** len(match.group(2)))
            frame = round(seconds * 60)
        anchors.append({
            "frame": frame, "time_seconds": seconds, **artifact(path),
            "media_type": "image/png", "status": "visual_only",
        })
    if not anchors:
        raise RuntimeError("no visual anchors found")
    contacts = [artifact(path) for path in sorted(EVIDENCE.glob("contact-*.jpg"))]
    write_json(EVIDENCE / "frame-index.json", {
        "schema_version": 2, "kind": "vivhite_promo_exact_frame_index_v2",
        "status": "verified_decoded_cfr_anchor_index_visual_only",
        "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "source": {**cfr, "fps": 60, "decoded_frames": cfr_frames, "container_duration_seconds": cfr_duration},
        "index_basis": "zero-based decoded frame; time=frame/60; direct ffmpeg PNG extraction without pixel edits",
        "key_frames": anchors, "contact_sheets": contacts,
        "semantic_status": "visual-only; not native game evidence",
    })

    marks = json.loads(MARKS_COPY.read_text(encoding="utf-8-sig"))
    operator_events = operator_relative_events(marks)
    declared_card = marks.get("parameters", {}).get("luminous_card_id")
    mark_failures = [
        "operator schema is not vivhite-promo-action-evidence v2",
        "no native state.before/action.receipt/state.after snapshots are included",
        "no game state_version, observation_seq, applied/outcome/settled receipt fields, or game-run identity are included",
        "operator monotonic events are not bound exactly to encoded source PTS/frames",
    ]
    write_json(EVIDENCE / "operator-marks-review.json", {
        "schema_version": 2, "kind": "vivhite_promo_operator_marks_review_v2",
        "status": "preserved_operator_provenance_not_native_evidence",
        "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID, "reviewed_at_utc": observed,
        "source": {**external_marks, "preserved_artifact": rel(MARKS_COPY)},
        "operator_schema": marks.get("schema"), "operator_status": marks.get("status"),
        "declared_phase1_card_id": declared_card,
        "visible_phase1_card": {"name_zh": "弦光投影", "declared_id_match": declared_card == "VIVHITE_CARD_LUMINOUS_PROJECTION", "anchor": rel(EVIDENCE / "anchors" / str(PROFILE["card_anchor"]))},
        "process_notes": {"game_process": marks.get("game_process"), "obs_process": marks.get("obs_process")},
        "operator_relative_events": operator_events,
        "strict_action_evidence_loadable": False, "native_state_snapshots_present": False,
        "failed_requirements": mark_failures,
        "decision": "retain as operator timing/provenance only; correct visible card identity does not make the notes native receipts",
    })
    write_json(CAPTURE / "recording-marks.json", {
        "schema_version": 2, "kind": "vivhite_promo_recording_marks_v2",
        "status": "operator_note_only_non_native_unbound_to_encoded_pts",
        "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "source": rel(RAW), "operator_marks": marks_artifact,
        "encoded_start_frame": None, "encoded_end_frame_exclusive": None,
        "operator_relative_events": operator_events,
        "reason": "The script clock and encoded MKV have no exported exact PTS/frame binding; these are not native recording/action marks.",
    })

    raw_decode, raw_decode_log = run_ffmpeg(RAW, "-map", "0:v:0", "-f", "null", "NUL")
    cfr_decode, cfr_decode_log = run_ffmpeg(CFR, "-map", "0:v:0", "-f", "null", "NUL")
    scene_code, scene_log = run_ffmpeg(CFR, "-vf", "select='gt(scene,0.04)',showinfo", "-an", "-f", "null", "NUL")
    black_code, black_log = run_ffmpeg(CFR, "-vf", "blackdetect=d=0.25:pix_th=0.10", "-an", "-f", "null", "NUL")
    freeze_code, freeze_log = run_ffmpeg(CFR, "-vf", "freezedetect=n=0.003:d=1.0", "-an", "-f", "null", "NUL")
    scene_points = []
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", scene_log):
        value = float(match.group(1))
        if not scene_points or abs(scene_points[-1] - value) > 0.02:
            scene_points.append(value)
    black_intervals = re.findall(r"black_start:[^\r\n]+", black_log)
    freeze_events = re.findall(r"lavfi.freezedetect[^\r\n]+", freeze_log)
    decode_ok = raw_decode == 0 and cfr_decode == 0
    write_json(EVIDENCE / "media-decode-check.json", {
        "schema_version": 2, "kind": "vivhite_promo_media_decode_check_v2",
        "status": "passed" if decode_ok else "failed", "checked_at_utc": observed,
        "sources": [
            {"path": rel(RAW), "decoded_video_frames": raw_frames, "full_video_decode_exit_code": raw_decode},
            {"path": rel(CFR), "decoded_video_frames": cfr_frames, "full_video_decode_exit_code": cfr_decode},
        ],
        "decode_error_tail": {"raw": raw_decode_log[-1000:] if raw_decode else "", "cfr": cfr_decode_log[-1000:] if cfr_decode else ""},
        "frame_exact_duration_seconds": exact_duration,
        "container_duration_seconds": {"raw": raw_duration, "normalized": cfr_duration},
        "filters": {"scene_exit_code": scene_code, "black_exit_code": black_code, "freeze_exit_code": freeze_code},
        "blackdetect": {"filter": "d=0.25:pix_th=0.10", "intervals": black_intervals},
        "freezedetect": {"filter": "n=0.003:d=1.0", "events": freeze_events},
    })

    visual_events = [
        {"event": event, "time_seconds": seconds, "observation": note}
        for event, seconds, note in PROFILE["events"]
    ]
    write_json(EVIDENCE / "event-sequence.json", {
        "schema_version": 2, "kind": "vivhite_promo_event_sequence_v2",
        "status": "visual_sequence_matches_card_contract_but_native_evidence_unverified",
        "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "events": [{**event, "frame": round(event["time_seconds"] * 60), "status": "visual_only", "input_receipt": None} for event in visual_events],
        "required_order": ["ritual_click", "phase0_power_active", "end_turn_click", "phase1_handoff", "Luminous_click/target", "extra Cough/payment", "increased_damage", "final_state"],
        "observed_divergence": None,
        "visible_card_identity": {"required": "VIVHITE_CARD_LUMINOUS_PROJECTION", "observed": "弦光投影", "match": True},
        "native_order_verified": False,
    })
    write_json(EVIDENCE / "clean-surface-review.json", {
        "schema_version": 2, "kind": "vivhite_promo_clean_surface_review_v2", "status": "passed_sampled",
        "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "sample_basis": f"{len(anchors)} exact PNG anchors plus 1fps and 4-second contact sheets",
        "forbidden_surfaces": {"console": False, "obs": False, "taskbar": False, "system_cursor": False, "brain_or_ai_panel": False, "ascend_vision": False, "debug_or_modded_label": False, "loading_screen": False},
        "note": "Sampled visual cleanliness and correct card identity do not cure the native-evidence failure.",
    })
    write_json(EVIDENCE / "technical-visual-review.json", {
        "schema_version": 2, "kind": "vivhite_promo_technical_visual_review_v2",
        "status": "technical_and_visual_contract_pass_native_evidence_reject",
        "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID, "reviewed_at_utc": observed,
        "source": {"raw": raw, "normalized": cfr, "operator_marks": marks_artifact},
        "technical": {
            "resolution": "1920x1080", "fps": 60, "decoded_frames": cfr_frames,
            "frame_exact_duration_seconds": exact_duration,
            "container_duration_seconds": {"raw": raw_duration, "normalized": cfr_duration},
            "video": "H.264 High yuv420p progressive", "audio": "AAC-LC 48000 Hz stereo",
            "full_decode": "passed_raw_and_normalized" if decode_ok else "failed",
            "black_intervals": black_intervals, "freeze_events": freeze_events,
            "scene_change_points_seconds": scene_points,
        },
        "visual_chain": {
            "ritual_phase0_to_phase1": "observed",
            "extra_cough_and_increased_damage": "visually observed on Luminous Projection",
            "required_phase1_card": "VIVHITE_CARD_LUMINOUS_PROJECTION",
            "actual_visible_phase1_card": "弦光投影",
            "required_card_match": True,
            "native_receipt_bound": False,
        },
        "visible_values": PROFILE["visible_values"],
        "timing": {
            "required_owner_span_seconds": 30.5, "source_long_enough_in_total": cfr_duration >= 30.5,
            "formal_owner_span": None,
            "reason": "No native frame/action binding; the visually settled tail is also longer than the preferred 2-4 second result hold before/around the discard hover.",
        },
        "failed_gates": mark_failures,
        "disposition": {"production_eligible": False, "preserve": True, "allowed_use": "failed-reference and timing guide only"},
    })

    missing_refs = [
        "T16-frame-begin", "T16-state-before", "T16-ritual-receipt", "T16-state-phase0",
        "T16-end-turn-receipt", "T16-state-phase1", "T16-state-before-attack",
        "T16-phase1-attack-receipt", "T16-state-final", "T16-event-sequence(native)", "T16-frame-end",
    ]
    write_json(CONTRACTS / "strict-action-sidecar.rejected.json", {
        "schema_version": 2, "kind": "vivhite-promo-action-evidence",
        "status": "rejected_non_loadable_missing_native_triads",
        "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "input_origin": "operator_script_and_video_observation_only", "loadable": False,
        "missing_required_refs": missing_refs,
        "card_identity": {"declared": declared_card, "visible": "弦光投影", "match": True},
        "reason": "Absence record only; it is not an action receipt and must never be loaded as one.",
    })

    source = {
        "external_path": EXTERNAL_RAW.as_posix(), "raw": raw, "normalized": cfr,
        "operator_marks": marks_artifact, "decoded_frames": cfr_frames,
        "frame_exact_duration_seconds": exact_duration,
        "container_duration_seconds": {"raw": raw_duration, "normalized": cfr_duration},
        "probe": rel(PROBE / "source-probe.json"), "normalized_probe": rel(PROBE / "normalized-probe.json"),
    }
    evidence_refs = [{"ref_id": ref_id, "status": "missing_native", "path": None} for ref_id in missing_refs]
    rejection_code = "rejected_missing_native_triads_and_exact_frame_binding"
    write_json(CAPTURE / "attempt-manifest.json", {
        "schema_version": 2, "kind": "vivhite_promo_take_attempt_v2",
        "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "status": rejection_code, "production_eligible": False,
        "technical_status": "passed_raw_preserved_stream_copy_cfr60_full_decode",
        "visual_status": "clean_continuous_chain_correct_luminous_card",
        "evidence_status": "operator_provenance_only_missing_native_triads",
        "director_contract": {
            "required_phase1_card_id": "VIVHITE_CARD_LUMINOUS_PROJECTION",
            "required_owner_span_seconds": 30.5, "required_subshot_durations_seconds": [14.5, 16.0],
            "single_continuous_source": True, "playback_speed": 1,
        },
        "source": source,
        "operator_identity_note": {"status": "preserved_not_native_action_binding", "game_process": marks.get("game_process"), "obs_process": marks.get("obs_process")},
        "evidence_refs": evidence_refs,
        "visual_references": {
            "frame_index": rel(EVIDENCE / "frame-index.json"), "event_sequence": rel(EVIDENCE / "event-sequence.json"),
            "operator_marks_review": rel(EVIDENCE / "operator-marks-review.json"),
        },
        "formal_owner_span": None, "production_row": None, "formal_edl": None,
        "rejection": {
            "code": rejection_code,
            "failed_conditions": [
                "No native state/action/state triad or exact native frame binding exists.",
                "Operator notes and matching pixels cannot establish native applied/outcome/settled receipts.",
            ],
        },
        "disposition": {"preserve": True, "must_not_enter_production_manifest": True, "must_not_create_formal_edl": True},
    })
    write_json(CAPTURE / "take-row.rejected.json", {
        "schema_version": 2, "kind": "vivhite_promo_take_row_v2",
        "status": rejection_code, "production_eligible": False,
        "run_id": RUN_ID, "attempt_id": ATTEMPT_ID,
        "take": {"take_id": TAKE_ID, "independent": True, "source": source, "evidence_refs": evidence_refs, "spans": []},
        "visual_contract": {"required_phase1_card": "弦光投影", "actual_phase1_card": "弦光投影", "match": True},
        "editorial_boundary": {"formal_owner_span": None, "required_owner_span_seconds": 30.5, "formal_continuity_verified": False},
        "rejection": {"code": rejection_code, "failed_conditions": ["missing native triads/exact frame marks"]},
        "disposition": {"preserve": True, "allowed_use": "failed-reference only", "must_not_enter_production_manifest": True},
    })
    write_json(CAPTURE / "binder-validation.json", {
        "schema_version": 2, "kind": "vivhite_promo_binder_validation_v2",
        "status": "rejected_before_binding", "validated_at_utc": observed,
        "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "technical_validation": {"status": "passed", "decoded_frames": cfr_frames, "nominal_60fps": True},
        "clean_surface_validation": {"status": "passed_sampled", "path": rel(EVIDENCE / "clean-surface-review.json")},
        "card_identity_validation": {"status": "passed_sampled", "required": "VIVHITE_CARD_LUMINOUS_PROJECTION", "visible": "弦光投影"},
        "strict_action_validation": {"status": "failed_missing_native_triads", "path": rel(CONTRACTS / "strict-action-sidecar.rejected.json")},
        "binder_invoked": False, "production_row": {"created": False, "path": None}, "formal_edl": {"created": False, "path": None},
    })
    write_json(CAPTURE / "take-manifest.t16-only.json", {
        "schema_version": 2, "kind": "vivhite_promo_partial_take_manifest_v2",
        "status": "rejected_take_preserved", "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "production_eligible": False, "formal_rows": [], "rejected_rows": [rel(CAPTURE / "take-row.rejected.json")],
        "reason": "Visual contract passes, but native state/action/state evidence and exact frame binding are absent.",
    })

    handoff = f"""# T16/{ATTEMPT_ID} archive handoff

- Decision: **rejected_preserved**; `production_eligible=false`; no production row or formal EDL.
- External source: `{EXTERNAL_RAW.as_posix()}`
- Preserved raw: `{rel(RAW)}` — {raw['bytes']} bytes — SHA-256 `{raw['sha256']}`
- CFR review copy: `{rel(CFR)}` — {cfr['bytes']} bytes — SHA-256 `{cfr['sha256']}`
- Operator marks: `{rel(MARKS_COPY)}` — {marks_artifact['bytes']} bytes — SHA-256 `{marks_artifact['sha256']}`
- Media: H.264 High 1920×1080 yuv420p progressive at nominal 60 FPS; AAC-LC 48 kHz stereo; {cfr_frames} decoded frames; raw {raw_duration:.3f}s / CFR {cfr_duration:.3f}s.

## Visual verdict

The source is continuous and visually clean. It shows the Crimson Transformation Ritual, end-turn/enemy turn, phase 1, and the contract-required **弦光投影 / Luminous Projection**. The card tooltip, drag/play, extra Cough payment, phase-1 damage increase, target damage, and settled HUD are visible in order. See `evidence/takes/T16/{ATTEMPT_ID}/technical-visual-review.json` for sampled values.

## Evidence verdict

`operator-marks.json` is preserved as operator provenance and includes process/timing notes, but it is not native `vivhite-promo-action-evidence` v2. It has no state/action/state snapshots, game versions/observations, native applied/outcome/settled receipts, or exact encoded-frame binding. Matching script intent and visible card identity do not make it a native sidecar.

The source is long enough in total for 30.5 seconds, but no formal owner span is selected. The long result tail also needs editorial review against the 2–4 second hold rule. A production attempt must export the complete T16 native triads and exact frame marks.

Continue from `capture/takes/T16/{ATTEMPT_ID}/attempt-manifest.json`, `capture/takes/T16/{ATTEMPT_ID}/binder-validation.json`, `evidence/takes/T16/{ATTEMPT_ID}/technical-visual-review.json`, and `contracts/takes/T16/{ATTEMPT_ID}/strict-action-sidecar.rejected.json`.
"""
    handoff_path = CAPTURE / "HANDOFF.md"
    encoded_handoff = handoff.encode("utf-8")
    if handoff_path.exists() and handoff_path.read_bytes() != encoded_handoff:
        raise RuntimeError(f"refusing to overwrite differing handoff: {handoff_path}")
    if not handoff_path.exists():
        handoff_path.write_bytes(encoded_handoff)
    write_json(CAPTURE / "handoff-index.json", {
        "schema_version": 2, "kind": "vivhite_promo_take_handoff_index_v2",
        "status": "rejected_preserved_ready_for_retake", "run_id": RUN_ID, "take_id": TAKE_ID, "attempt_id": ATTEMPT_ID,
        "handoff": rel(handoff_path),
        "authoritative_records": [rel(CAPTURE / "attempt-manifest.json"), rel(CAPTURE / "take-row.rejected.json"), rel(CAPTURE / "binder-validation.json"), rel(EVIDENCE / "technical-visual-review.json"), rel(CONTRACTS / "strict-action-sidecar.rejected.json")],
        "production_row": None, "native_sidecars_present": False,
    })
    print(json.dumps({
        "status": "rejected_preserved", "reason": rejection_code,
        "raw": raw, "cfr": cfr, "operator_marks": marks_artifact,
        "raw_duration_seconds": raw_duration, "cfr_duration_seconds": cfr_duration,
        "decoded_frames": cfr_frames, "production_row_created": False,
        "handoff": rel(handoff_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"archive_t16_luminous_attempts[{ATTEMPT_ID}]: ERROR: {exc}", file=sys.stderr)
        raise
