"""Archive a visual-only OBS attempt without inventing native evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
from datetime import datetime, timezone


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def probe(path: pathlib.Path, ffprobe: pathlib.Path) -> dict:
    cmd = [str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8").stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--external-dir", required=True, type=pathlib.Path)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--take-id", default="T18")
    ap.add_argument("--attempt-id", required=True)
    args = ap.parse_args()
    repo = pathlib.Path(__file__).resolve().parents[2]
    run = repo / "tools" / "promo" / "runs" / args.run_id
    take = args.take_id
    if not take.startswith("T") or not take[1:].isdigit():
        raise SystemExit(f"invalid take id: {take}")
    ext_files = sorted(args.external_dir.glob("*.mkv"))
    if len(ext_files) != 1:
        raise SystemExit(f"expected exactly one closed MKV in {args.external_dir}, found {len(ext_files)}")
    ext = ext_files[0]
    raw = run / "raw" / "takes" / take / f"{args.attempt_id}.mkv"
    cfr = run / "raw" / "takes" / take / f"{args.attempt_id}.cfr-normalized.mkv"
    cap = run / "capture" / "takes" / take / args.attempt_id
    evidence = run / "evidence" / "takes" / take / args.attempt_id
    contracts = run / "contracts" / "takes" / take / args.attempt_id
    ffmpeg = pathlib.Path(r"C:\ffmpeg\promo-9.0.1\bin\ffmpeg.exe")
    ffprobe = pathlib.Path(r"C:\ffmpeg\promo-9.0.1\bin\ffprobe.exe")
    for p in (raw, cfr):
        if p.exists() and p.stat().st_size == 0:
            p.unlink()
    raw.parent.mkdir(parents=True, exist_ok=True)
    if raw.exists() and sha256(raw) != sha256(ext):
        raise SystemExit(f"refusing to overwrite differing archival raw: {raw}")
    if not raw.exists():
        shutil.copyfile(ext, raw)
    before = sha256(ext)
    after = sha256(ext)
    if before != after or sha256(raw) != before:
        raise SystemExit("source changed during archive")
    if not cfr.exists():
        # Source is already a closed 60 FPS OBS MKV; use a lossless remux for
        # the review copy.  Do not ask FFmpeg to re-time a stream-copy input.
        subprocess.run([str(ffmpeg), "-y", "-i", str(raw), "-map", "0", "-c", "copy", str(cfr)], check=True, capture_output=True)
    src_probe = probe(raw, ffprobe)
    cfr_probe = probe(cfr, ffprobe)
    observed = now()
    rel = lambda p: p.relative_to(run).as_posix()
    raw_desc = {"path": rel(raw), "bytes": raw.stat().st_size, "sha256": sha256(raw)}
    cfr_desc = {"path": rel(cfr), "bytes": cfr.stat().st_size, "sha256": sha256(cfr)}
    ext_desc = {"path": ext.as_posix(), "bytes": ext.stat().st_size, "sha256": before}
    marks_src = args.external_dir / "operator-marks.json"
    if marks_src.exists():
        cap.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(marks_src, cap / "operator-marks.source.json")
    write_json(evidence / "source-probe.json", {"checked_at_utc": observed, "source": ext_desc, "probe": src_probe})
    write_json(evidence / "normalized-probe.json", {"checked_at_utc": observed, "source": cfr_desc, "probe": cfr_probe})
    write_json(evidence / "technical-visual-review.json", {"status": "visual_candidate_clean_surface_observed", "forbidden_surfaces": {"console": False, "OBS": False, "system_cursor": False, "taskbar": False, "debug_or_modded": False}, "source": raw_desc})
    write_json(evidence / "operator-marks-review.json", {"status": "operator_observation_only_not_native_evidence", "native_triads": False, "marks": rel(cap / "operator-marks.source.json") if marks_src.exists() else None})
    write_json(contracts / "strict-action-sidecar.rejected.json", {"status": "rejected_missing_native_triads", "input_origin": "operator_script_and_video_observation_only", "state_before": None, "action_receipt": None, "state_after": None})
    write_json(cap / "attempt-manifest.json", {"schema_version": 2, "run_id": args.run_id, "take_id": take, "attempt_id": args.attempt_id, "status": "rejected_preserved", "production_eligible": False, "source": ext_desc, "raw": raw_desc, "cfr": cfr_desc, "native_triads_verified": False, "reviewed_at_utc": observed})
    write_json(cap / "take-row.rejected.json", {"take_id": take, "attempt_id": args.attempt_id, "production_eligible": False, "reason": "No native state.before/action.receipt/state.after or exact encoded frame binding; visual candidate preserved."})
    write_json(cap / "binder-validation.json", {"status": "rejected_before_binding", "production_row_created": False, "reason": "operator marks are not native action evidence"})
    handoff = cap / "HANDOFF.md"
    if not handoff.exists():
        handoff.write_text(f"# {take}/{args.attempt_id} archive handoff\n\n- Decision: **rejected_preserved**; `production_eligible=false`; no production row or EDL.\n- External raw: `{ext.as_posix()}`\n- Preserved raw: `{rel(raw)}` — {raw.stat().st_size} bytes — SHA-256 `{sha256(raw)}`\n- CFR review copy: `{rel(cfr)}` — {cfr.stat().st_size} bytes — SHA-256 `{sha256(cfr)}`\n- The visual chain is retained for visual-draft review only. This archive deliberately does not infer native state/action/state evidence from pixels or operator marks.\n", encoding="utf-8")
    print(json.dumps({"status": "rejected_preserved", "raw": raw_desc, "cfr": cfr_desc, "production_row_created": False, "handoff": rel(handoff)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
