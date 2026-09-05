"""Append-only archive/probe utility for an independent T10 capture.

The T10 recorder is intentionally an operator-side recorder.  This utility
preserves the closed OBS source and every sidecar in the capture directory,
creates a stream-copy review file, runs deterministic media probes/diagnostics,
and writes a handoff package.  It never derives a game state, action receipt,
or frame boundary from pixels, OCR, wall-clock marks, or pointer coordinates.
Consequently a normal operator-only T10 capture is recorded as a preserved
visual reference and is *not* promoted to the production manifest.

The command is safe to rerun.  Existing artifacts are accepted only when their
bytes are identical; a differing file is never overwritten.  A completed
``archive-summary.json`` is an immutable idempotency sentinel.

Example::

    py -3 -B tools/promo/archive_t10_attempt.py \
      --external-dir "G:/OBS_VIDEOS/vivhite-director-v2/run-20260903-0012/T10/a04" \
      --run-id run-20260903T0012-director-v2-a1 --attempt-id a04

The external directory must contain exactly one closed ``*.mkv``.  The source
MKV is copied byte-for-byte to ``raw/takes/T10/<attempt>.mkv``; JSON/NDJSON,
images, and other sidecars are copied below the attempt's
``capture/source-artifacts`` directory without being interpreted as native
evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_RUN_ID = "run-20260903T0012-director-v2-a1"
TAKE_ID = "T10"
DEFAULT_REQUIRED_OWNER_SECONDS = 18.2
FFMPEG_CANDIDATES = (
    pathlib.Path(r"C:\ffmpeg\promo-9.0.1\bin\ffmpeg.exe"),
    pathlib.Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
)
FFPROBE_CANDIDATES = (
    pathlib.Path(r"C:\ffmpeg\promo-9.0.1\bin\ffprobe.exe"),
    pathlib.Path(r"C:\ffmpeg\bin\ffprobe.exe"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def path_label(path: pathlib.Path, root: pathlib.Path | None = None) -> str:
    if root is not None:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def descriptor(path: pathlib.Path, root: pathlib.Path | None = None) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": path_label(path, root),
        "bytes": stat.st_size,
        "sha256": sha256(path),
        "last_write_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def write_bytes_append_only(path: pathlib.Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_bytes()
        if existing != body:
            raise RuntimeError(f"refusing to overwrite differing archival file: {path}")
        return
    path.write_bytes(body)


def write_json(path: pathlib.Path, payload: Any) -> None:
    write_bytes_append_only(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def preserve_copy(source: pathlib.Path, destination: pathlib.Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"required source is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_file() and destination.stat().st_size == source.stat().st_size and sha256(destination) == sha256(source):
            return
        raise RuntimeError(f"refusing to overwrite differing preserved artifact: {destination}")
    shutil.copy2(source, destination)


def choose_tool(candidates: tuple[pathlib.Path, ...], name: str) -> pathlib.Path:
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"pinned {name} is missing (checked: {', '.join(map(str, candidates))})")


def run_capture(command: list[str], *, include_full_output: bool = False) -> dict[str, Any]:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    payload: dict[str, Any] = {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-8000:],
    }
    if include_full_output:
        # Full output is used for the per-check log, but deliberately kept out
        # of archive-commands.json so a noisy filter cannot make that index
        # unbounded.
        payload["_stdout_full"] = result.stdout
        payload["_stderr_full"] = result.stderr
    return payload


def ffprobe_json(path: pathlib.Path, ffprobe: pathlib.Path) -> dict[str, Any]:
    command = [
        str(ffprobe), "-v", "error", "-show_entries",
        "format=format_name,start_time,duration,size,bit_rate,nb_streams,probe_score:"
        "stream=index,codec_name,profile,codec_type,width,height,pix_fmt,field_order,"
        "r_frame_rate,avg_frame_rate,time_base,start_time,sample_rate,channels,channel_layout",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return json.loads(result.stdout)


def decoded_frames(path: pathlib.Path, ffprobe: pathlib.Path) -> int:
    command = [str(ffprobe), "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=nb_read_frames", "-of", "json", str(path)]
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    streams = json.loads(result.stdout).get("streams", [])
    return int(streams[0].get("nb_read_frames") or 0) if streams else 0


def stream_summary(path: pathlib.Path, ffprobe: pathlib.Path, frames: int, observed_at: str) -> dict[str, Any]:
    raw = ffprobe_json(path, ffprobe)
    streams = raw.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    fmt = raw.get("format", {})
    fps = video.get("avg_frame_rate")
    return {
        "format": {
            "name": fmt.get("format_name"),
            "duration_seconds": float(fmt.get("duration") or 0.0),
            "start_time_seconds": float(fmt.get("start_time") or 0.0),
            "streams": int(fmt.get("nb_streams") or len(streams)),
            "size": int(fmt.get("size") or path.stat().st_size),
            "bit_rate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
            "probe_score": int(fmt["probe_score"]) if fmt.get("probe_score") else None,
        },
        "video": {
            "codec": video.get("codec_name"),
            "profile": video.get("profile"),
            "width": video.get("width"),
            "height": video.get("height"),
            "pixel_format": video.get("pix_fmt"),
            "field_order": video.get("field_order"),
            "r_frame_rate": video.get("r_frame_rate"),
            "avg_frame_rate": fps,
            "time_base": video.get("time_base"),
            "decoded_frame_count": frames,
            "frame_exact_duration_seconds": frames / 60.0 if frames else None,
            "nominal_cfr": fps == "60/1",
        },
        "audio": {
            "codec": audio.get("codec_name"),
            "profile": audio.get("profile"),
            "sample_rate_hz": int(audio["sample_rate"]) if audio.get("sample_rate") else None,
            "channels": int(audio["channels"]) if audio.get("channels") else None,
            "channel_layout": audio.get("channel_layout"),
            "time_base": audio.get("time_base"),
        },
        "probe_command": "ffprobe -v error -show_entries format,stream -of json",
        "observed_at_utc": observed_at,
    }


def normalize(raw: pathlib.Path, cfr: pathlib.Path, ffmpeg: pathlib.Path, commands: list[dict[str, Any]]) -> None:
    if cfr.exists():
        if not cfr.is_file() or cfr.stat().st_size == 0:
            raise RuntimeError(f"existing normalized artifact is empty: {cfr}")
        return
    command = [
        str(ffmpeg), "-hide_banner", "-y", "-i", str(raw),
        "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-copyts",
        "-avoid_negative_ts", "disabled", str(cfr),
    ]
    result = run_capture(command)
    commands.append(result)
    if result["returncode"] != 0 or not cfr.is_file() or cfr.stat().st_size == 0:
        raise RuntimeError(f"stream-copy normalization failed: {result['stderr_tail']}")


def diagnostics(path: pathlib.Path, ffmpeg: pathlib.Path, diag_dir: pathlib.Path, commands: list[dict[str, Any]], run: pathlib.Path) -> dict[str, Any]:
    diag_dir.mkdir(parents=True, exist_ok=True)
    checks = {
        "decode": [str(ffmpeg), "-hide_banner", "-i", str(path), "-map", "0:v:0", "-f", "null", "NUL"],
        "blackdetect": [str(ffmpeg), "-hide_banner", "-i", str(path), "-vf", "blackdetect=d=0.25:pix_th=0.10", "-an", "-f", "null", "NUL"],
        "freezedetect": [str(ffmpeg), "-hide_banner", "-i", str(path), "-vf", "freezedetect=n=0.003:d=1.0", "-an", "-f", "null", "NUL"],
    }
    result: dict[str, Any] = {}
    for name, command in checks.items():
        item = run_capture(command, include_full_output=True)
        commands.append({key: value for key, value in item.items() if not key.startswith("_")})
        stdout_full = str(item.get("_stdout_full", ""))
        stderr_full = str(item.get("_stderr_full", ""))
        log_body = (stdout_full + ("\n" if stdout_full and stderr_full else "") + stderr_full).encode("utf-8", errors="replace")
        log_path = diag_dir / f"{name}.log"
        write_bytes_append_only(log_path, log_body)
        result[name] = {
            "returncode": item["returncode"],
            "log": path_label(log_path, run),
            "blackdetect_intervals": [line for line in item["stderr_tail"].splitlines() if "black_start" in line or "black_end" in line],
            "freezedetect_events": [line for line in item["stderr_tail"].splitlines() if "freeze_" in line],
        }
    return result


def extract_anchors(cfr: pathlib.Path, evidence_dir: pathlib.Path, ffmpeg: pathlib.Path, duration: float, run: pathlib.Path, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors_dir = evidence_dir / "anchors"
    anchors_dir.mkdir(parents=True, exist_ok=True)
    offsets = sorted({0.0, round(max(0.0, duration * 0.25), 3), round(max(0.0, duration * 0.5), 3), round(max(0.0, duration * 0.75), 3), round(max(0.0, duration - 0.25), 3)})
    records: list[dict[str, Any]] = []
    for index, offset in enumerate(offsets):
        target = anchors_dir / f"anchor-{index:02d}-{offset:07.3f}s.png"
        if not target.exists():
            command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{offset:.3f}", "-i", str(cfr), "-frames:v", "1", str(target)]
            result = run_capture(command)
            commands.append(result)
            if result["returncode"] != 0 or not target.is_file() or target.stat().st_size == 0:
                raise RuntimeError(f"failed to extract visual anchor at {offset:.3f}s")
        records.append({
            "frame": round(offset * 60),
            "time_seconds": offset,
            "path": path_label(target, run),
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
            "media_type": "image/png",
            "status": "visual_only",
        })
    return records


def load_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def load_ndjson(path: pathlib.Path) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line {line_number}: invalid JSON")
            continue
        if isinstance(value, dict):
            events.append(value)
        else:
            errors.append(f"line {line_number}: JSON value is not an object")
    return events, errors


def find_named(source_files: list[pathlib.Path], name: str) -> pathlib.Path | None:
    matches = [p for p in source_files if p.name.lower() == name.lower()]
    return sorted(matches)[0] if matches else None


def source_artifact_copy(external_dir: pathlib.Path, files: list[pathlib.Path], destination: pathlib.Path, run: pathlib.Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in sorted(files):
        relative = source.relative_to(external_dir)
        target = destination / "source-artifacts" / relative
        preserve_copy(source, target)
        records.append({"external": descriptor(source), "preserved": descriptor(target, run), "relative_name": relative.as_posix()})
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-dir", required=True, type=pathlib.Path, help="Closed OBS output directory for exactly one attempt")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--attempt-id", required=True, help="Attempt identifier such as a04")
    parser.add_argument("--required-owner-seconds", type=float, default=DEFAULT_REQUIRED_OWNER_SECONDS)
    args = parser.parse_args()

    if not args.attempt_id.startswith("a") or not args.attempt_id[1:].isdigit():
        raise RuntimeError(f"attempt id must look like a04, got {args.attempt_id!r}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", args.run_id):
        raise RuntimeError("run-id must be a simple directory name (letters, digits, '.', '_' or '-')")
    if not math.isfinite(args.required_owner_seconds) or args.required_owner_seconds <= 0:
        raise RuntimeError("required-owner-seconds must be a finite positive number")
    external_dir = args.external_dir.resolve()
    if not external_dir.is_dir():
        raise RuntimeError(f"external capture directory is missing: {external_dir}")

    runs_root = (REPO / "tools" / "promo" / "runs").resolve()
    run = (runs_root / args.run_id).resolve()
    try:
        run.relative_to(runs_root)
    except ValueError as exc:  # defensive even after the basename check
        raise RuntimeError(f"run-id escapes the promo runs root: {args.run_id!r}") from exc
    # Never let an external OBS directory point into the archive tree (or the
    # reverse); this prevents recursive self-copying and accidental source
    # mutation when a caller mistypes a path.
    try:
        external_dir.relative_to(run)
        raise RuntimeError(f"external directory is inside the archive run: {external_dir}")
    except ValueError:
        pass
    try:
        run.relative_to(external_dir)
        raise RuntimeError(f"archive run is inside the external directory: {run}")
    except ValueError:
        pass
    capture = run / "capture" / "takes" / TAKE_ID / args.attempt_id
    raw = run / "raw" / "takes" / TAKE_ID / f"{args.attempt_id}.mkv"
    cfr = run / "raw" / "takes" / TAKE_ID / f"{args.attempt_id}.cfr-normalized.mkv"
    evidence = run / "evidence" / "takes" / TAKE_ID / args.attempt_id
    contracts = run / "contracts" / "takes" / TAKE_ID / args.attempt_id
    probe_dir = run / "probe" / "takes" / TAKE_ID / args.attempt_id
    summary_path = capture / "archive-summary.json"

    if summary_path.is_file():
        existing_summary = load_json(summary_path)
        if not isinstance(existing_summary, dict) or any(existing_summary.get(key) != value for key, value in (("run_id", args.run_id), ("take_id", TAKE_ID), ("attempt_id", args.attempt_id))):
            raise RuntimeError(f"archive summary exists but does not match this invocation: {summary_path}")
        if existing_summary.get("status") not in {"rejected_preserved", "technical_failed_preserved"}:
            raise RuntimeError(f"archive summary has an unknown/incomplete status: {summary_path}")
        print(summary_path.read_text(encoding="utf-8"), end="")
        return 0

    media = sorted(p for p in external_dir.rglob("*.mkv") if p.is_file())
    if len(media) != 1:
        raise RuntimeError(f"expected exactly one closed MKV in {external_dir}, found {len(media)}: {[p.name for p in media]}")
    external_raw = media[0]
    external_files = [p for p in external_dir.rglob("*") if p.is_file() and p != external_raw]
    # A second descriptor/hash pass is a cheap closed-file guard.  The raw
    # source is never edited, renamed, or deleted by this script.
    ext_before = descriptor(external_raw)
    ext_after = descriptor(external_raw)
    if ext_before != ext_after:
        raise RuntimeError("external MKV changed while being inspected; wait for OBS closure and retry")
    sidecars_before = [descriptor(path) for path in external_files]
    sidecars_after = [descriptor(path) for path in external_files]
    if sidecars_before != sidecars_after:
        raise RuntimeError("one or more external sidecars changed while being inspected; wait for capture closure and retry")

    context_path = capture / "archive-context.json"
    context = load_json(context_path) if context_path.is_file() else None
    if isinstance(context, dict):
        expected_context = {"run_id": args.run_id, "take_id": TAKE_ID, "attempt_id": args.attempt_id, "external_directory": external_dir.as_posix()}
        mismatches = [key for key, expected in expected_context.items() if context.get(key) != expected]
        if mismatches:
            raise RuntimeError(f"archive context provenance mismatch for {', '.join(mismatches)}: {context_path}")
    observed_at = str(context.get("observed_at_utc")) if isinstance(context, dict) and context.get("observed_at_utc") else utc_now()
    if context is None:
        write_json(context_path, {
            "schema_version": 1,
            "kind": "vivhite_promo_archive_context_v1",
            "run_id": args.run_id,
            "take_id": TAKE_ID,
            "attempt_id": args.attempt_id,
            "observed_at_utc": observed_at,
            "external_directory": external_dir.as_posix(),
            "external_raw_initial": ext_after,
            "append_only": True,
        })

    preserve_copy(external_raw, raw)
    preserved_raw_check = descriptor(raw)
    if preserved_raw_check["bytes"] != ext_after["bytes"] or preserved_raw_check["sha256"] != ext_after["sha256"]:
        raise RuntimeError("preserved raw does not match the closed external OBS source")
    copied_artifacts = source_artifact_copy(external_dir, external_files, capture, run)
    marks_source = find_named(external_files, "operator-marks.json")
    partial_source = find_named(external_files, "operator-marks.partial.json")
    events_source = find_named(external_files, "operator-events.ndjson")
    preflight_source = find_named(external_files, "preflight-receipt.json")
    canonical_sources: dict[str, pathlib.Path | None] = {
        "operator-marks.source.json": marks_source,
        "operator-marks.partial.source.json": partial_source,
        "operator-events.source.ndjson": events_source,
        "preflight-receipt.source.json": preflight_source,
    }
    canonical: dict[str, dict[str, Any] | None] = {}
    for name, source in canonical_sources.items():
        if source is None:
            canonical[name] = None
            continue
        target = capture / name
        preserve_copy(source, target)
        canonical[name] = descriptor(target, run)

    ffmpeg = choose_tool(FFMPEG_CANDIDATES, "ffmpeg.exe")
    ffprobe = choose_tool(FFPROBE_CANDIDATES, "ffprobe.exe")
    commands: list[dict[str, Any]] = []
    normalize(raw, cfr, ffmpeg, commands)
    raw_frames = decoded_frames(raw, ffprobe)
    cfr_frames = decoded_frames(cfr, ffprobe)
    raw_probe = stream_summary(raw, ffprobe, raw_frames, observed_at)
    cfr_probe = stream_summary(cfr, ffprobe, cfr_frames, observed_at)
    raw_duration = raw_probe["format"]["duration_seconds"]
    cfr_duration = cfr_probe["format"]["duration_seconds"]
    video = cfr_probe["video"]
    audio = cfr_probe["audio"]
    stream_technical_pass = bool(
        raw_frames > 0 and cfr_frames > 0 and
        raw_frames == cfr_frames and
        video.get("width") == 1920 and video.get("height") == 1080 and
        video.get("codec") == "h264" and video.get("field_order") == "progressive" and
        video.get("nominal_cfr") and video.get("pixel_format") == "yuv420p" and
        audio.get("codec") == "aac" and
        audio.get("sample_rate_hz") == 48000 and audio.get("channels") == 2
    )

    raw_desc = descriptor(raw, run)
    cfr_desc = descriptor(cfr, run)
    source_desc = {"external": ext_after, "raw": raw_desc, "normalized": cfr_desc}
    write_json(probe_dir / "source-probe.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_media_probe_v2",
        "status": "passed_technical_only" if stream_technical_pass else "failed_technical",
        "observed_at_utc": observed_at,
        "probe_scope": "immutable_obs_source",
        "source": source_desc,
        **raw_probe,
        "lineage_check": {
            "external_matches_preserved_raw_bytes": ext_after["bytes"] == raw_desc["bytes"],
            "external_matches_preserved_raw_sha256": ext_after["sha256"] == raw_desc["sha256"],
            "source_closed_and_hash_stable_at_review": True,
        },
        "production_gate": "not_promoted_without_native_action_state_triads",
    })
    write_json(probe_dir / "normalized-probe.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_media_probe_v2",
        "status": "passed_technical_only" if stream_technical_pass else "failed_technical",
        "observed_at_utc": observed_at,
        "probe_scope": "stream_copy_remux_review_reference",
        "source": cfr_desc,
        **cfr_probe,
        "normalization": {
            "method": "ffmpeg stream-copy remux (-map 0:v:0 -map 0:a:0? -c copy -copyts -avoid_negative_ts disabled)",
            "reencode": False,
            "raw_preserved": True,
            "purpose": "deterministic visual review reference",
        },
        "production_gate": "not_promoted_without_native_action_state_triads",
    })

    # Decode both immutable raw and normalized review streams.  Keeping the
    # logs in separate directories makes it impossible to mistake a derivative
    # pass for validation of the original OBS bytes.
    diagnostic_result = {
        "raw": diagnostics(raw, ffmpeg, evidence / "diagnostics" / "raw", commands, run),
        "normalized": diagnostics(cfr, ffmpeg, evidence / "diagnostics" / "normalized", commands, run),
    }
    diagnostics_pass = all(check.get("returncode") == 0 for stream in diagnostic_result.values() for check in stream.values())
    technical_pass = stream_technical_pass and diagnostics_pass
    anchors = extract_anchors(cfr, evidence, ffmpeg, cfr_duration, run, commands)
    write_json(evidence / "frame-index.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_exact_frame_index_v2",
        "status": "verified_decoded_cfr_anchor_index_visual_only",
        "run_id": args.run_id,
        "take_id": TAKE_ID,
        "attempt_id": args.attempt_id,
        "source": {**cfr_desc, "fps": 60, "decoded_frames": cfr_frames, "container_duration_seconds": cfr_duration},
        "index_basis": "timestamp-seeked CFR review anchor; nominal frame=round(time*60) is a presentation label, not a native frame mark",
        "frame_index_exact": False,
        "seek_method": "ffmpeg -ss timestamp before input decode; no pixel edits",
        "key_frames": anchors,
        "contact_sheets": [],
        "semantic_status": "visual-only; no native action/state binding",
    })
    write_json(evidence / "media-decode-check.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_media_decode_check_v2",
        "status": "passed" if diagnostics_pass else "failed",
        "checked_at_utc": observed_at,
        "sources": [{"path": raw_desc["path"], "decoded_video_frames": raw_frames}, {"path": cfr_desc["path"], "decoded_video_frames": cfr_frames}],
        "frame_exact_duration_seconds": cfr_frames / 60.0 if cfr_frames else None,
        "container_duration_seconds": {"raw": raw_duration, "normalized": cfr_duration},
        "diagnostics": diagnostic_result,
    })
    write_json(probe_dir / "archive-commands.json", {"schema_version": 1, "observed_at_utc": observed_at, "commands": commands})

    marks_obj = load_json(capture / "operator-marks.source.json") if marks_source is not None else None
    events: list[dict[str, Any]] = []
    event_errors: list[str] = []
    if events_source is not None:
        events, event_errors = load_ndjson(capture / "operator-events.source.ndjson")
    candidate_names = [item["relative_name"] for item in copied_artifacts if any(token in item["relative_name"].lower() for token in ("action", "receipt", "state", "evidence"))]
    mark_failures = [
        "T10 recorder exports operator-side marks, not native vivhite-promo-action-evidence v2",
        "wall-clock and pointer coordinates are not promoted to state/action/frame evidence",
        "native state.before/state.after snapshots and action.receipt delivery/outcome/settled binding were not verified by this archive step",
        "formal owner span remains unbound until native evidence is independently validated",
    ]
    write_json(evidence / "operator-marks-review.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_operator_marks_review_v2",
        "status": "preserved_incomplete_observation_only_not_native_evidence",
        "run_id": args.run_id,
        "take_id": TAKE_ID,
        "attempt_id": args.attempt_id,
        "reviewed_at_utc": observed_at,
        "source": canonical,
        "parsed_marks": marks_obj,
        "event_count": len(events),
        "event_parse_errors": event_errors,
        "native_sidecar_candidates": candidate_names,
        "strict_action_evidence_loadable": False,
        "failed_requirements": mark_failures,
        "decision": "retain all operator artifacts; never synthesize receipts or state snapshots from video/logs",
    })
    write_json(evidence / "clean-surface-review.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_clean_surface_review_v2",
        "status": "pending_manual_visual_review",
        "run_id": args.run_id,
        "take_id": TAKE_ID,
        "attempt_id": args.attempt_id,
        "sample_basis": "CFR anchor PNGs only; automated forbidden-surface assertions are intentionally not made",
        "forbidden_surfaces": {"console": "not_assessed", "obs": "not_assessed", "taskbar": "not_assessed", "system_cursor": "not_assessed", "debug_or_modded_label": "not_assessed", "loading_screen": "not_assessed"},
        "anchors": [item["path"] for item in anchors],
    })
    write_json(evidence / "technical-visual-review.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_technical_visual_review_v2",
        "status": "technical_pass_native_contract_reject" if technical_pass else "technical_fail_native_contract_reject",
        "run_id": args.run_id,
        "take_id": TAKE_ID,
        "attempt_id": args.attempt_id,
        "reviewed_at_utc": observed_at,
        "source": {"raw": raw_desc, "normalized": cfr_desc, "operator_artifacts": canonical},
        "technical": {"resolution": f"{video.get('width')}x{video.get('height')}", "fps": video.get("avg_frame_rate"), "decoded_frames": cfr_frames, "frame_exact_duration_seconds": cfr_frames / 60.0 if cfr_frames else None, "pixel_format": video.get("pixel_format"), "video_codec": video.get("codec"), "audio_codec": audio.get("codec"), "audio_sample_rate_hz": audio.get("sample_rate_hz"), "audio_channels": audio.get("channels"), "diagnostics": diagnostic_result},
        "visual_sampling": {"exact_frame_index": path_label(evidence / "frame-index.json", run), "clean_surface": "pending_manual_visual_review", "formal_receipt_bound": False},
        "strict_evidence": {"required_triads_present": False, "native_frame_marks_present": False, "action_receipts_present": False, "state_snapshots_present": False, "candidate_artifacts_not_promoted": candidate_names},
        "failed_gates": mark_failures,
        "disposition": {"production_eligible": False, "preserve": True, "allowed_use": "visual reference and retake guide only"},
    })

    evidence_refs = [
        {"ref_id": "T10-frame-begin", "role": "frame.begin", "status": "missing_native", "path": None},
        {"ref_id": "T10-state-before", "role": "state.before", "status": "missing_native", "path": None},
        {"ref_id": "T10-campfire-entry-receipt", "role": "action.receipt", "status": "missing_native", "path": None},
        {"ref_id": "T10-rest-receipt", "role": "action.receipt", "status": "missing_native", "path": None},
        {"ref_id": "T10-state-after", "role": "state.after", "status": "missing_native", "path": None},
        {"ref_id": "T10-return-map-receipt", "role": "action.receipt", "status": "missing_native", "path": None},
        {"ref_id": "T10-frame-end", "role": "frame.end", "status": "missing_native", "path": None},
    ]
    source = {"external": ext_after, "raw": raw_desc, "normalized": cfr_desc, "operator_artifacts": canonical, "copied_artifacts": copied_artifacts, "probe": path_label(probe_dir / "source-probe.json", run), "normalized_probe": path_label(probe_dir / "normalized-probe.json", run)}
    rejection_code = "rejected_missing_native_action_state_triads"
    write_json(contracts / "strict-action-sidecar.rejected.json", {
        "schema_version": 2,
        "kind": "vivhite-promo-action-evidence",
        "status": "rejected_missing_native_triads_non_loadable",
        "input_origin": "operator_marks_and_video_only",
        "run_id": args.run_id,
        "take_id": TAKE_ID,
        "attempt_id": args.attempt_id,
        "operator_artifacts": canonical,
        "candidate_artifacts_not_promoted": candidate_names,
        "missing_required_refs": [item["ref_id"] for item in evidence_refs],
        "loadable": False,
        "reason": "Archive step refuses to manufacture native state/action/frame evidence from an OBS file or operator log.",
    })
    write_json(capture / "recording-marks.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_recording_marks_review_v2",
        "status": "operator_marks_not_native_frame_bounds",
        "run_id": args.run_id,
        "take_id": TAKE_ID,
        "attempt_id": args.attempt_id,
        "source": canonical.get("operator-marks.source.json") or canonical.get("operator-marks.partial.source.json"),
        "recording_start_frame": None,
        "recording_end_frame_exclusive": None,
        "started_monotonic_seconds": None,
        "stopped_monotonic_seconds": None,
        "strict_loadable": False,
        "note": "Recorder-side elapsed ticks remain in copied source artifacts but are not encoded-frame boundaries.",
    })
    write_json(capture / "attempt-manifest.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_take_attempt_v2",
        "run_id": args.run_id,
        "take_id": TAKE_ID,
        "attempt_id": args.attempt_id,
        "status": rejection_code if technical_pass else "failed_technical_probe",
        "production_eligible": False,
        "visual_status": "pending_manual_visual_review",
        "technical_status": "raw_preserved_cfr_review_copy" if technical_pass else "technical_probe_failed",
        "evidence_status": "operator_marks_only_missing_native_triads",
        "director_contract": {"storyboard": "tools/promo/v2/storyboard.json", "capture_runbook": "tools/promo/v2/capture-runbook.json", "subshot_id": "S06-05-campfire-rest", "required_owner_span_seconds": args.required_owner_seconds, "single_continuous_source": True, "playback_speed": 1, "max_no_visible_change_seconds": 4},
        "source": source,
        "recording_bounds": {"start_frame": None, "end_frame_exclusive": None, "status": "not_binder_ready"},
        "observed_operator_events": [{"event": item.get("event"), "elapsed_s": item.get("elapsed_s"), "status": "operator_observation_only"} for item in events],
        "continuity_assessment": {"single_mkv": True, "formal_action_chain": "unverified_missing_native_triads", "formal_owner_span": None},
        "formal_action_evidence": {"status": "not_created", "rejected_sidecar_record": path_label(contracts / "strict-action-sidecar.rejected.json", run)},
        "editorial_binding": {"formal_owner_span": None, "candidate_visual_span": {"in_seconds": 0.0, "out_seconds": cfr_duration}, "owner_span_status": "rejected_missing_native_triads"},
        "evidence_refs": evidence_refs,
        "rejection": {"code": rejection_code, "failed_conditions": mark_failures},
        "disposition": {"preserve": True, "allowed_use": "visual reference and retake guide only", "must_not_enter_production_manifest": True, "must_not_create_formal_edl_span": True},
    })
    write_json(capture / "take-row.rejected.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_take_row_v2",
        "status": rejection_code,
        "production_eligible": False,
        "run_id": args.run_id,
        "attempt_id": args.attempt_id,
        "take": {"take_id": TAKE_ID, "attempt_id": args.attempt_id, "independent": True, "requirement": "required", "asset_type": "ui_gameplay", "source": source, "evidence_refs": evidence_refs, "action_evidence": [], "spans": []},
        "editorial_boundary": {"formal_owner_span": None, "visual_candidate_spans": [{"label": "uncut_source_for_manual_review", "in_seconds": 0.0, "out_seconds": cfr_duration}], "required_owner_span_seconds": args.required_owner_seconds, "required_action_chain_complete": False, "formal_continuity_verified": False},
        "rejection": {"code": rejection_code, "failed_conditions": ["No native action/state/state triads were verified.", "Operator marks are retained as provenance only."]},
        "disposition": {"preserve": True, "allowed_use": "visual reference and retake guide only", "must_not_enter_production_manifest": True, "must_not_create_formal_edl_span": True},
    })
    write_json(capture / "binder-validation.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_binder_validation_v2",
        "status": "rejected_before_binding",
        "validated_at_utc": observed_at,
        "take_id": TAKE_ID,
        "attempt_id": args.attempt_id,
        "inputs": {"attempt_manifest": path_label(capture / "attempt-manifest.json", run), "rejected_row": path_label(capture / "take-row.rejected.json", run), "source": cfr_desc, "strict_sidecar": path_label(contracts / "strict-action-sidecar.rejected.json", run)},
        "technical_validation": {"status": "passed" if technical_pass else "failed", "decoded_video_frames": cfr_frames, "resolution": f"{video.get('width')}x{video.get('height')}", "nominal_60fps": video.get("nominal_cfr", False), "audio": {"codec": audio.get("codec"), "sample_rate_hz": audio.get("sample_rate_hz"), "channels": audio.get("channels")}},
        "forbidden_visual_validation": {"status": "pending_manual_visual_review", "evidence": path_label(evidence / "clean-surface-review.json", run)},
        "strict_action_evidence_validation": {"status": "failed_missing_native_triads", "sidecar": path_label(contracts / "strict-action-sidecar.rejected.json", run)},
        "span_assertions": {"status": "not_binder_ready", "required_owner_span_seconds": args.required_owner_seconds, "formal_owner_span": None, "source_duration_seconds": cfr_duration},
        "production_row": {"path": None, "created": False},
        "formal_edl": {"path": None, "created": False},
        "disposition": "preserved_failed_reference_only",
    })

    handoff = f"""# T10/{args.attempt_id} archive handoff\n\n- Decision: **rejected_preserved**; `production_eligible=false`; no production row or formal EDL.\n- External OBS source: `{external_raw.as_posix()}`\n- Preserved raw: `{raw_desc['path']}` — {raw_desc['bytes']} bytes — SHA-256 `{raw_desc['sha256']}`\n- CFR review copy: `{cfr_desc['path']}` — {cfr_desc['bytes']} bytes — SHA-256 `{cfr_desc['sha256']}`\n- Media: {video.get('width')}×{video.get('height')}, {video.get('codec')} / {video.get('pixel_format')}, {video.get('avg_frame_rate')}; {cfr_frames} decoded frames; raw {raw_duration:.3f}s, CFR {cfr_duration:.3f}s.\n- Audio: {audio.get('codec')}, {audio.get('sample_rate_hz')} Hz, {audio.get('channels')} channels.\n\n## Archive result\n\nThe closed source and all external sidecars are preserved below `capture/takes/T10/{args.attempt_id}/source-artifacts/`. CFR, ffprobe, full decode, blackdetect/freezedetect logs, and visual anchor PNGs are retained for manual review. No source bytes were edited or overwritten.\n\n## Strict disposition\n\nThis archive step does not infer `state.before`, `action.receipt`, `state.after`, or encoded frame bounds from the MKV, screenshots, OCR, pointer marks, or wall-clock notes. Operator artifacts are therefore recorded as provenance only; no native triads were promoted and no formal owner span or EDL was created. A fresh take with independently exported native evidence can be archived using the same command.\n\nAuthoritative records: `capture/takes/T10/{args.attempt_id}/attempt-manifest.json`, `capture/takes/T10/{args.attempt_id}/take-row.rejected.json`, `capture/takes/T10/{args.attempt_id}/binder-validation.json`, `evidence/takes/T10/{args.attempt_id}/operator-marks-review.json`, and `contracts/takes/T10/{args.attempt_id}/strict-action-sidecar.rejected.json`.\n"""
    write_bytes_append_only(capture / "HANDOFF.md", handoff.encode("utf-8"))
    write_json(capture / "handoff-index.json", {
        "schema_version": 2,
        "kind": "vivhite_promo_take_handoff_index_v2",
        "status": "rejected_preserved_ready_for_retake",
        "run_id": args.run_id,
        "take_id": TAKE_ID,
        "attempt_id": args.attempt_id,
        "handoff": path_label(capture / "HANDOFF.md", run),
        "authoritative_records": [path_label(capture / "attempt-manifest.json", run), path_label(capture / "take-row.rejected.json", run), path_label(capture / "binder-validation.json", run), path_label(evidence / "operator-marks-review.json", run), path_label(contracts / "strict-action-sidecar.rejected.json", run)],
        "production_row": None,
        "native_sidecars_present": False,
    })
    summary = {
        "schema_version": 1,
        "kind": "vivhite_promo_t10_archive_summary_v1",
        "status": "rejected_preserved" if technical_pass else "technical_failed_preserved",
        "run_id": args.run_id,
        "take_id": TAKE_ID,
        "attempt_id": args.attempt_id,
        "external": ext_after,
        "raw": raw_desc,
        "cfr": cfr_desc,
        "raw_duration_seconds": raw_duration,
        "cfr_duration_seconds": cfr_duration,
        "decoded_frames": cfr_frames,
        "technical_pass": technical_pass,
        "native_triads_verified": False,
        "production_eligible": False,
        "production_row_created": False,
        "handoff": path_label(capture / "HANDOFF.md", run),
        "observed_at_utc": observed_at,
    }
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"archive_t10_attempt: ERROR: {exc}", file=sys.stderr)
        raise
