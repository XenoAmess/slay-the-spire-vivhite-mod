"""Seal the director-approved T16/a22 and T18/a08 editorial takes.

This archive deliberately does not manufacture the native state/action/state
triads required by the strict production binder.  It records immutable media,
operator telemetry, exact reviewed frames, and the director's relaxed timing
decision so the footage can move into the edit while the evidence distinction
remains explicit.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any


REPO = pathlib.Path(__file__).resolve().parents[2]
RUN_ID = "run-20260903T0012-director-v2-a1"
RUN = REPO / "tools" / "promo" / "runs" / RUN_ID
FFMPEG = pathlib.Path(r"C:\ffmpeg\bin\ffmpeg.exe")
FFPROBE = pathlib.Path(r"C:\ffmpeg\bin\ffprobe.exe")


TAKES = (
    {
        "take_id": "T16",
        "attempt_id": "a22",
        "slot": "a22-editorial-accepted",
        "source": REPO / ".work" / "promo-review" / "t16-a22-cfr-lossless-pad.mp4",
        "target": RUN / "normalized" / "takes" / "T16" / "a22.cfr-lossless-pad.mp4",
        "source_bytes": 162_430_591,
        "source_sha256": "2734CF706A57E3F08DC1D5C5FB74A472E20AE86A555B57EF2F9C658A3719DDD4",
        "decoded_frames": 1_869,
        "operator_marks": pathlib.Path(
            r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T16\a22\operator-marks.json"
        ),
        "operator_events": None,
        "original_obs": pathlib.Path(
            r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T16\a22\2026-09-04 11-10-57.mkv"
        ),
        "original_bytes": 28_949_211,
        "original_sha256": "DE288BC563265659D77A15C370353FC4177B206505D15D79E6898548B5F9B933",
        "review_frames": (0, 230, 339, 369, 480, 609, 724, 729, 1030, 1070, 1090, 1150, 1259, 1290, 1338, 1440, 1650, 1829),
        "spans": (
            {"subshot_id": "S08-02-crimson-phase-zero", "in_seconds": 0.0, "out_seconds": 18.0},
            {"subshot_id": "S08-03-crimson-phase-one", "in_seconds": 18.0, "out_seconds": 30.5},
        ),
        "semantics": {
            "sequence": ["猩红转化仪式", "结束回合", "phase 1", "弦光投影"],
            "required_phase1_card_id": "VIVHITE_CARD_LUMINOUS_PROJECTION",
            "visible_phase1_card_name": "弦光投影",
            "visible_cough_cost": 2,
            "visible_attack_damage": 10,
            "player_hp_path": "82 -> 76 -> 73",
            "target_hp_path": "46 -> 43",
            "energy_path": "6 -> 2",
        },
        "notes": "31.15s continuous take supplies the exact 30.5s owner span at 1x speed; 0.65s tail is unused.",
    },
    {
        "take_id": "T18",
        "attempt_id": "a08",
        "slot": "a08-editorial-accepted",
        "source": pathlib.Path(
            r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T18\a08\2026-09-05 00-59-40.mkv"
        ),
        "target": RUN / "raw" / "takes" / "T18" / "a08.mkv",
        "source_bytes": 25_820_035,
        "source_sha256": "D472193DD79761F1DCF822ACE9329B87B037175B3F4D9E4AA70888C22C506DDB",
        "decoded_frames": 1_877,
        "operator_marks": pathlib.Path(
            r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T18\a08\operator-marks.json"
        ),
        "operator_events": pathlib.Path(
            r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T18\a08\operator-events.ndjson"
        ),
        "original_obs": pathlib.Path(
            r"G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T18\a08\2026-09-05 00-59-40.mkv"
        ),
        "original_bytes": 25_820_035,
        "original_sha256": "D472193DD79761F1DCF822ACE9329B87B037175B3F4D9E4AA70888C22C506DDB",
        "review_frames": (30, 360, 420, 454, 484, 540, 600, 660, 840, 900, 935, 964, 1020, 1080, 1140, 1200, 1260, 1320, 1500, 1620, 1800, 1859),
        "spans": (
            {"subshot_id": "S09-02-unified-field-chain", "in_seconds": 0.5, "out_seconds": 27.0},
            {"subshot_id": "S09-03-unified-field-result", "in_seconds": 27.0, "out_seconds": 31.0},
        ),
        "semantics": {
            "sequence": ["闭域映射", "余裕消耗", "汲取增长", "三色华尔兹", "实际回复", "余裕回流"],
            "cough_card_id": "VIVHITE_CARD_CLOSED_DOMAIN_MAPPING",
            "drain_attack_card_id": "VIVHITE_CARD_TRICHROMATIC_WALTZ",
            "initial_margin": 2,
            "margin_after_cough": 0,
            "drain_after_cough_percent": 8,
            "visible_attack_damage": "4 x 3",
            "actual_healing_visible": 3,
            "unupgraded_runtime_divisor": 3,
            "final_margin": 1,
            "player_hp_path": "38 -> 32 -> 35",
            "target_hp_path": "44 -> 32",
        },
        "notes": "31.2833s source supplies 30.5s at 1x speed with 0.5s head trim and a small unused tail.",
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def relative(path: pathlib.Path) -> str:
    return path.relative_to(RUN).as_posix()


def descriptor(path: pathlib.Path, **extra: Any) -> dict[str, Any]:
    return {"path": relative(path), "bytes": path.stat().st_size, "sha256": sha256(path), **extra}


def write_json(path: pathlib.Path, value: Any) -> None:
    body = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise RuntimeError(f"refusing to overwrite differing artifact: {path}")
        return
    with path.open("xb") as stream:
        stream.write(body)


def copy_immutable(source: pathlib.Path, target: pathlib.Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size != source.stat().st_size or sha256(target) != sha256(source):
            raise RuntimeError(f"refusing to overwrite differing artifact: {target}")
        return
    with source.open("rb") as left, target.open("xb") as right:
        shutil.copyfileobj(left, right, length=1024 * 1024)


def extract_frames(source: pathlib.Path, frames: tuple[int, ...], output: pathlib.Path) -> list[pathlib.Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / f"selected-{index:02d}.png" for index in range(1, len(frames) + 1)]
    if not all(path.exists() for path in paths):
        if any(path.exists() for path in paths):
            raise RuntimeError(f"partial frame extraction exists: {output}")
        expression = "+".join(f"eq(n\\,{frame})" for frame in frames)
        subprocess.run(
            [str(FFMPEG), "-v", "error", "-i", str(source), "-vf", f"select={expression}",
             "-fps_mode", "passthrough", str(output / "selected-%02d.png")],
            check=True,
        )
    if not all(path.is_file() and path.stat().st_size > 0 for path in paths):
        raise RuntimeError(f"frame extraction failed: {output}")
    return paths


def probe(source: pathlib.Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-count_frames", "-count_packets", "-show_streams", "-show_format", "-of", "json", str(source)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def archive_take(spec: dict[str, Any]) -> dict[str, Any]:
    take_id = spec["take_id"]
    attempt_id = spec["attempt_id"]
    source = spec["source"]
    target = spec["target"]
    if source.stat().st_size != spec["source_bytes"] or sha256(source) != spec["source_sha256"]:
        raise RuntimeError(f"sealed source changed: {take_id}/{attempt_id}")
    if spec["original_obs"].stat().st_size != spec["original_bytes"] or sha256(spec["original_obs"]) != spec["original_sha256"]:
        raise RuntimeError(f"original OBS source changed: {take_id}/{attempt_id}")
    copy_immutable(source, target)

    capture_dir = RUN / "capture" / "takes" / take_id / spec["slot"]
    evidence_dir = RUN / "evidence" / "takes" / take_id / spec["slot"]
    probe_dir = RUN / "probe" / "takes" / take_id / spec["slot"]
    live_dir = evidence_dir / "live"
    copy_immutable(spec["operator_marks"], live_dir / "operator-marks.json")
    if spec["operator_events"] is not None:
        copy_immutable(spec["operator_events"], live_dir / "operator-events.ndjson")

    subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(target), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "NUL"],
        check=True,
    )
    raw_probe = probe(target)
    video = next(row for row in raw_probe["streams"] if row.get("codec_type") == "video")
    audio = next(row for row in raw_probe["streams"] if row.get("codec_type") == "audio")
    frame_count = int(video["nb_read_frames"])
    if frame_count != spec["decoded_frames"] or int(video["nb_read_packets"]) != frame_count:
        raise RuntimeError(f"decoded frame count changed: {take_id}/{attempt_id}")
    probe_path = probe_dir / "source-probe.json"
    write_json(probe_path, {
        "schema_version": 2,
        "kind": "vivhite_promo_source_probe_v2",
        "status": "completed",
        "observed_at_utc": utc_now(),
        "source": descriptor(target),
        "result": {"streams": [video, audio], "format": raw_probe["format"]},
        "derived": {
            "decoded_video_frames": frame_count,
            "frame_duration_seconds": frame_count / 60,
            "full_decode_status": "passed_no_errors",
        },
    })

    frame_paths = extract_frames(target, spec["review_frames"], evidence_dir / "anchors")
    review_path = evidence_dir / "technical-visual-review.json"
    write_json(review_path, {
        "schema_version": 2,
        "kind": "vivhite_promo_editorial_visual_review_v2",
        "status": "passed_editorially",
        "take_id": take_id,
        "attempt_id": attempt_id,
        "review_basis": ["immutable_source_frames", "operator_pointer_telemetry", "gameplay_source_mechanics"],
        "source": descriptor(target, decoded_frames=frame_count, fps=60),
        "full_decode": "passed_no_errors",
        "semantics": spec["semantics"],
        "reviewed_frames_zero_based": list(spec["review_frames"]),
        "anchors": [descriptor(path, media_type="image/png") for path in frame_paths],
        "forbidden_elements": [],
        "strict_native_receipt_status": "not_available_not_claimed",
    })

    row_path = capture_dir / "take-row.editorial.json"
    write_json(row_path, {
        "schema_version": 2,
        "kind": "vivhite_promo_editorial_take_row_v2",
        "status": "accepted_for_edit",
        "production_binder_eligible": False,
        "run_id": RUN_ID,
        "take_id": take_id,
        "attempt_id": attempt_id,
        "source": descriptor(target, duration_seconds=frame_count / 60, decoded_frames=frame_count, fps=60),
        "original_obs": {
            "path": spec["original_obs"].as_posix(),
            "bytes": spec["original_bytes"],
            "sha256": spec["original_sha256"],
        },
        "spans": list(spec["spans"]),
        "playback_speed": 1,
        "technical_visual_review": descriptor(review_path),
        "evidence_boundary": {
            "operator_marks": descriptor(live_dir / "operator-marks.json"),
            "operator_events": descriptor(live_dir / "operator-events.ndjson") if spec["operator_events"] is not None else None,
            "native_state_action_state_triads": "missing",
            "claim": "editorial and visual acceptance only; no native receipt claim",
        },
        "director_timing_decision": {
            "authorized_at_local_date": "2026-09-05",
            "decision": "small duration variance is acceptable; stop retrying usable takes",
            "note": spec["notes"],
        },
    })

    attempt_path = capture_dir / "attempt-manifest.json"
    write_json(attempt_path, {
        "schema_version": 2,
        "kind": "vivhite_promo_take_attempt_v2",
        "run_id": RUN_ID,
        "take_id": take_id,
        "attempt_id": attempt_id,
        "status": "accepted_for_edit_not_strict_binder",
        "production_eligible": False,
        "shooting_complete": True,
        "source": descriptor(target, decoded_frames=frame_count, duration_seconds=frame_count / 60),
        "source_probe": descriptor(probe_path),
        "technical_visual_review": descriptor(review_path),
        "editorial_take_row": descriptor(row_path),
        "strict_evidence_gap": "native state/action/state triads were not captured; operator telemetry is not relabeled as native evidence",
        "disposition": "use in edit under director timing tolerance; preserve all earlier attempts",
    })
    return {
        "take_id": take_id,
        "attempt_id": attempt_id,
        "status": "accepted_for_edit_not_strict_binder",
        "source": descriptor(target),
        "frames": frame_count,
        "duration_seconds": frame_count / 60,
        "row": descriptor(row_path),
        "attempt_manifest": descriptor(attempt_path),
    }


def main() -> int:
    if not FFMPEG.is_file() or not FFPROBE.is_file():
        raise RuntimeError("FFmpeg tools are missing")
    archived = [archive_take(spec) for spec in TAKES]
    print(json.dumps({"status": "shooting_complete_19_of_19_editorially", "takes": archived}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
