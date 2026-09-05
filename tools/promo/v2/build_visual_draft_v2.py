#!/usr/bin/env python3
"""Build and optionally render the director-approved Vivhite editorial master.

This path is deliberately separate from ``production_binder_v2``.  Seventeen
takes come from verified production rows; T16 and T18 use the director-approved
editorial rows without relabelling operator telemetry as native receipts.  The
result contains no placeholder frames, but remains distinct from strict signoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any


FPS = 60
WIDTH = 1920
HEIGHT = 1080
SAMPLE_RATE = 48000
TARGET = 540.0
REPO = Path(__file__).resolve().parents[3]
RUN = REPO / "tools/promo/runs/run-20260903T0012-director-v2-a1"
TITLE_ROOT = REPO / "tools/promo/runs/run-20260902T162155Z-director-v2-title-cards-a2"
NARRATION_MANIFEST = REPO / "tools/promo/runs/run-20260903T0040-director-v2-narration-a5/logs/director-v2-narration-manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def binding(path: Path, *, artifact_root: Path = REPO) -> dict[str, Any]:
    rel = path.resolve().relative_to(artifact_root.resolve()).as_posix()
    return {"path": rel, "bytes": path.stat().st_size, "sha256": sha256(path)}


def video(path: str, take_id: str, start: float, end: float, *, status: str = "production_row") -> dict[str, Any]:
    p = (REPO / path).resolve()
    return {
        "kind": "video_take",
        "take_id": take_id,
        **binding(p),
        "in_seconds": start,
        "out_seconds": end,
        "provenance_status": status,
        "strict_production_row": status == "production_row",
        "formal_action_evidence": False,
        "native_triads_loaded": False,
    }


def title(path: str, title_id: str) -> dict[str, Any]:
    p = (REPO / path).resolve()
    return {
        "kind": "title_card",
        "title_id": title_id,
        **binding(p),
        "provenance_status": "rendered_title_card_pending_editorial_review",
    }


def placeholder(reason: str) -> dict[str, Any]:
    return {
        "kind": "placeholder_color",
        "color": "#120B29",
        "provenance_status": "explicit_placeholder",
        "reason": reason,
    }


def segment(segment_id: str, shot_id: str, subshot_id: str, start: float, duration: float,
            source: dict[str, Any], asset_type: str, *, note: str = "") -> dict[str, Any]:
    return {
        "segment_id": segment_id,
        "shot_id": shot_id,
        "subshot_id": subshot_id,
        "asset_type": asset_type,
        "timeline": {"start_seconds": start, "end_seconds": start + duration, "duration_seconds": duration},
        "duration_seconds": duration,
        "source": source,
        "editorial_status": "director_approved_editorial_master_candidate",
        "strict_production_eligible": False,
        "note": note,
    }


def build_segments() -> list[dict[str, Any]]:
    # Source spans use 17 verified production rows plus the director-approved
    # T16/T18 editorial rows.  No rejected source or placeholder is used.
    t01 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T01/a05.mkv"
    t02 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T02/a02.mkv"
    t03 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T03/a02.mkv"
    t04 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T04/a01.mkv"
    t05 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T05/a03.mkv"
    t06 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T06/a01.cfr-normalized.mkv"
    t08 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T08/a01.mkv"
    t09 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T09/a01.mkv"
    t11 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T11/a02.cfr-normalized.mkv"
    t12 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T12/a03.mkv"
    t13 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T13/a01.mkv"
    t14 = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T14/a02.cfr-normalized.mkv"
    t07v = "tools/promo/runs/run-20260903T0012-director-v2-a1/normalized/takes/T07/a08.cfr-padded.mp4"
    t10v = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T10/a06.mkv"
    t16v = "tools/promo/runs/run-20260903T0012-director-v2-a1/normalized/takes/T16/a22.cfr-lossless-pad.mp4"
    t17v = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T17/a02.mkv"
    t18v = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T18/a08.mkv"
    t19v = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T19/a08.mkv"
    t20v = "tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T20/a07.mkv"
    titles = "tools/promo/runs/run-20260902T162155Z-director-v2-title-cards-a2/title-cards/"
    s: list[dict[str, Any]] = []
    n = 0

    def add(shot: str, sub: str, start: float, dur: float, src: dict[str, Any], typ: str, note: str = "") -> None:
        nonlocal n
        n += 1
        s.append(segment(f"vd-{n:03d}", shot, sub, start, dur, src, typ, note=note))

    # Cold open + selection.
    add("S01-identity", "S01-01-cough-highlight", 0, 2.4, video(t03, "T03", 55.25, 57.65), "montage")
    add("S01-identity", "S01-02-margin-highlight", 2.4, 2.4, video(t05, "T05", 71.767, 74.167), "montage")
    add("S01-identity", "S01-03-drain-highlight", 4.8, 2.4, video(t11, "T11", 5.5, 7.9), "montage")
    add("S01-identity", "S01-04-kill-chain-highlight", 7.2, 2.4, video(t14, "T14", 8.5, 10.9), "montage")
    add("S01-identity", "S01-05-map-highlight", 9.6, 2.4, video(t07v, "T07", 16.0, 18.4), "montage")
    add("S01-identity", "S01-06-question-bridge", 12, 6, video(t20v, "T20", 5, 11), "montage")
    add("S01-identity", "S01-07-main-title", 18, 5, video(t20v, "T20", 11, 16), "montage")
    add("S01-identity", "S01-08-main-title-continuation", 23, 5, video(t20v, "T20", 16, 21), "montage")
    add("S01-identity", "S01-09-character-selection-j-cut", 28, 10, video(t20v, "T20", 21, 31, status="editorial_extension_clean_source"), "ui_gameplay", "Continuous T20/a07 white-character selection; frames after the formal 24s union are the preserved same-screen stop-delay tail.")
    add("S01-identity", "S01-10-character-selection", 38, 12, video(t20v, "T20", 31, 43, status="editorial_extension_clean_source"), "ui_gameplay", "Continuous T20/a07 white-character selection; no Ironclad or main-menu frames.")
    add("S01-identity", "S01-10-character-selection-continuation", 50, 8, video(t20v, "T20", 43, 51, status="editorial_extension_clean_source"), "ui_gameplay", "Continuous T20/a07 white-character selection; no Ironclad or main-menu frames.")

    add("S02-loadout", "S02-01-starting-status", 58, 8, video(t02, "T02", 1, 9), "ui_gameplay")
    add("S02-loadout", "S02-02-starter-deck", 66, 12, video(t02, "T02", 9, 21), "ui_gameplay")

    add("S03-cough", "S03-01-title", 78, 2.5, title(titles + "01-S03-01-title.png", "S03-01-title"), "title_card")
    add("S03-cough", "S03-02-basic-payment", 80.5, 18.5, video(t03, "T03", 43.1, 61.6), "mechanism_action")
    add("S03-cough", "S03-03-transformation-payment", 99, 21, video(t04, "T04", 38, 59), "mechanism_action")

    add("S04-margin", "S04-01-title", 120, 2.5, title(titles + "02-S04-01-title.png", "S04-01-title"), "title_card")
    add("S04-margin", "S04-02-axiom-closed-chain", 122.5, 28.5, video(t05, "T05", 57.5, 86), "mechanism_action")
    add("S04-margin", "S04-03-second-conservation-chain", 151, 17, video(t06, "T06", 30, 47), "mechanism_action")
    add("S04-margin", "S04-04-card-reward", 168, 8, video(t07v, "T07", 1.8333333333, 9.8333333333), "ui_gameplay")
    add("S04-margin", "S04-05-map-route", 176, 12, video(t07v, "T07", 9.1666666667, 21.1666666667), "ui_gameplay", "Director-approved 40-frame native transition overlap with the reward span.")

    add("S06-conservation-geometry", "S06-01-title", 188, 2.5, title(titles + "03-S06-01-title.png", "S06-01-title"), "title_card")
    add("S06-conservation-geometry", "S06-02-topology-growth", 190.5, 21.5, video(t08, "T08", 55, 76.5), "mechanism_action")
    add("S06-conservation-geometry", "S06-03-fatal-growth", 212, 20, video(t09, "T09", 73, 93), "mechanism_action")
    add("S06-conservation-geometry", "S06-04-campfire-title", 232, 1.8, title(titles + "04-S06-04-campfire-title.png", "S06-04-campfire-title"), "tower_title_card")
    add("S06-conservation-geometry", "S06-05-campfire-rest", 233.8, 18.2, video(t10v, "T10", 0, 18.2), "ui_gameplay")

    add("S05-drain", "S05-01-title", 252, 2.5, title(titles + "05-S05-01-title.png", "S05-01-title"), "title_card")
    add("S05-drain", "S05-02-multihit-drain", 254.5, 28, video(t11, "T11", 0, 28), "mechanism_action")
    add("S05-drain", "S05-03-heal-to-block", 282.5, 23.5, video(t12, "T12", 29, 52.5), "mechanism_action")
    add("S05-drain", "S05-04-shop-title", 306, 1.8, title(titles + "06-S05-04-shop-title.png", "S05-04-shop-title"), "tower_title_card")
    add("S05-drain", "S05-05-shop-purchase", 307.8, 22.2, video(t13, "T13", 67.983, 90.183), "ui_gameplay")

    add("S07-recursive-star-calculus", "S07-01-title", 330, 2.5, title(titles + "07-S07-01-title.png", "S07-01-title"), "title_card")
    add("S07-recursive-star-calculus", "S07-02-termination-chain-a", 332.5, 24.5, video(t14, "T14", 0, 24.5), "mechanism_action")
    add("S07-recursive-star-calculus", "S07-03-result-hold", 357, 3.5, video(t14, "T14", 24.5, 28.0), "gameplay", "T14 result/event continuation; no second formal input is claimed.")
    add("S07-recursive-star-calculus", "S07-03-library-recap", 360.5, 14, video(t19v, "T19", 94.45, 108.45), "montage", "Editorial card-library recap replacing optional T15; no second action claim.")
    add("S07-recursive-star-calculus", "S07-03-route-recap", 374.5, 7.5, video(t17v, "T17", 0, 7.5), "montage", "Editorial route recap replacing optional T15; no second action claim.")

    add("S08-crimson-integral", "S08-01-title", 382, 2.5, title(titles + "08-S08-01-title.png", "S08-01-title"), "title_card")
    add("S08-crimson-integral", "S08-02-crimson-phase-zero", 384.5, 18, video(t16v, "T16", 0, 18, status="editorial_accepted_non_native"), "mechanism_action", "Director-approved T16/a22 editorial row; native triad remains unavailable.")
    add("S08-crimson-integral", "S08-03-crimson-phase-one", 402.5, 12.5, video(t16v, "T16", 18, 30.5, status="editorial_accepted_non_native"), "mechanism_action", "Director-approved T16/a22 editorial row; native triad remains unavailable.")

    add("S09-unified-field", "S09-01-title", 415, 2.5, title(titles + "09-S09-01-title.png", "S09-01-title"), "title_card")
    add("S09-unified-field", "S09-02-unified-field-chain", 417.5, 26.5, video(t18v, "T18", 0.5, 27, status="editorial_accepted_non_native"), "mechanism_action", "Director-approved T18/a08 editorial row; native triad remains unavailable.")
    add("S09-unified-field", "S09-03-unified-field-result", 444, 4, video(t18v, "T18", 27, 31, status="editorial_accepted_non_native"), "gameplay", "Director-approved T18/a08 result hold; native triad remains unavailable.")

    add("S10-finale", "S10-01-card-library", 448, 12, video(t19v, "T19", 94.45, 106.45), "ui_gameplay")
    add("S10-finale", "S10-01-card-library-tail", 460, 2, video(t19v, "T19", 106.45, 108.45), "ui_gameplay")
    add("S10-finale", "S10-02-conservation-route", 462, 11, video(t05, "T05", 64.75, 75.75), "montage")
    add("S10-finale", "S10-03-recursive-route", 473, 11, video(t14, "T14", 9, 20), "montage")
    add("S10-finale", "S10-04-crimson-route", 484, 12, video(t17v, "T17", 0, 12), "montage")
    add("S10-finale", "S10-05-finale-cough", 496, 3.5, video(t03, "T03", 54.8, 58.3), "montage")
    add("S10-finale", "S10-06-finale-margin", 499.5, 3.5, video(t05, "T05", 71.75, 75.25), "montage")
    add("S10-finale", "S10-07-finale-drain", 503, 3.5, video(t11, "T11", 10, 13.5), "montage")
    add("S10-finale", "S10-08-finale-kill-chain", 506.5, 3.5, video(t14, "T14", 8.5, 12), "montage")
    add("S10-finale", "S10-09-finale-map", 510, 4, video(t07v, "T07", 16, 20), "montage")
    add("S10-finale", "S10-10-idle-cta", 514, 12, video(t20v, "T20", 5, 17), "gameplay")
    add("S10-finale", "S10-11-version-and-workshop-status", 526, 7, video(t20v, "T20", 17, 24), "montage")
    add("S10-finale", "S10-12-clean-end-card", 533, 7, title(titles + "10-S10-12-clean-end-card.png", "S10-12-clean-end-card"), "end_card")
    return s


def build_edl() -> dict[str, Any]:
    segments = build_segments()
    cursor = 0.0
    for item in segments:
        start = float(item["timeline"]["start_seconds"])
        end = float(item["timeline"]["end_seconds"])
        if abs(start - cursor) > 1e-6:
            raise ValueError(f"timeline gap/overlap before {item['segment_id']}: {cursor} -> {start}")
        if end <= start:
            raise ValueError(f"non-positive segment {item['segment_id']}")
        source = item["source"]
        if source["kind"] in {"video_take", "title_card"} and not (REPO / source["path"]).is_file():
            raise FileNotFoundError(source["path"])
        cursor = end
    if abs(cursor - TARGET) > 1e-6:
        raise ValueError(f"timeline ends at {cursor}, expected {TARGET}")
    counts: dict[str, int] = {}
    for item in segments:
        k = item["source"]["kind"]
        counts[k] = counts.get(k, 0) + 1
    if counts.get("placeholder_color", 0) != 0:
        raise ValueError("director-approved editorial master must not contain placeholders")
    return {
        "schema_version": 1,
        "kind": "vivhite_promo_editorial_master_edl_v1",
        "edit_id": "editorial-master-540-v2",
        "status": "director_approved_editorial_not_strict_signoff",
        "source_strategy": "seventeen_production_rows_plus_two_director_approved_editorial_rows_and_clean_t20_stop_tail_no_placeholders",
        "take_batch_id": "run-20260903T0012-director-v2-a1",
        "target_duration_seconds": TARGET,
        "canvas": {"width": WIDTH, "height": HEIGHT, "fps": FPS},
        "audio": {"game_audio": "from_video_takes", "bgm": False, "sample_rate_hz": SAMPLE_RATE, "channels": 2,
                  "narration_manifest": NARRATION_MANIFEST.relative_to(REPO).as_posix(),
                  "narration_mix": "optional_in_preview_renderer"},
        "segments": segments,
        "provenance_summary": {
            "production_row_source_segments": sum(1 for x in segments if x["source"]["provenance_status"] == "production_row"),
            "editorial_accepted_non_native_segments": sum(1 for x in segments if x["source"]["provenance_status"] == "editorial_accepted_non_native"),
            "editorial_clean_extension_segments": sum(1 for x in segments if x["source"]["provenance_status"] == "editorial_extension_clean_source"),
            "title_card_segments": counts.get("title_card", 0),
            "explicit_placeholder_segments": counts.get("placeholder_color", 0),
            "strict_production_rows_used": 17,
            "director_approved_editorial_rows_used": 2,
            "native_action_evidence_loaded": False,
        },
        "strict_boundary": {
            "production_binder_input": False,
            "does_not_modify_or_replace": "master-540.production.json",
            "operator_marks_as_native_evidence": False,
            "rejected_candidates_in_formal_manifest": False,
            "strict_signoff_gap": ["T16 native state/action/state triads", "T18 native state/action/state triads"],
        },
        "narration": {"manifest": NARRATION_MANIFEST.relative_to(REPO).as_posix(), "status": "ready_for_final_editorial_mix", "voice": "zh-CN-XiaoxiaoNeural"},
    }


def _fmt(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".")


def build_command(edl: dict[str, Any], output: Path, *, preview_duration: float | None = None) -> list[str]:
    limit = TARGET if preview_duration is None else min(float(preview_duration), TARGET)
    selected: list[tuple[dict[str, Any], float, float]] = []
    for item in edl["segments"]:
        st = float(item["timeline"]["start_seconds"])
        en = float(item["timeline"]["end_seconds"])
        if st >= limit:
            break
        d = min(en, limit) - st
        source = item["source"]
        if d > 0:
            selected.append((item, d, st))
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    input_pairs: list[tuple[int, int]] = []
    input_index = 0
    for item, duration, timeline_start in selected:
        src = item["source"]
        if src["kind"] == "video_take":
            args += ["-ss", _fmt(float(src["in_seconds"]) + (timeline_start - float(item["timeline"]["start_seconds"]))),
                     "-t", _fmt(duration), "-i", str((REPO / src["path"]).resolve())]
            input_pairs.append((input_index, input_index))
            input_index += 1
        elif src["kind"] == "title_card":
            args += ["-loop", "1", "-t", _fmt(duration), "-i", str((REPO / src["path"]).resolve()),
                     "-f", "lavfi", "-t", _fmt(duration), "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo"]
            input_pairs.append((input_index, input_index + 1))
            input_index += 2
        else:
            args += ["-f", "lavfi", "-t", _fmt(duration), "-i", f"color=c=0x120B29:s={WIDTH}x{HEIGHT}:r={FPS}",
                     "-f", "lavfi", "-t", _fmt(duration), "-i", f"anullsrc=r={SAMPLE_RATE}:cl=stereo"]
            input_pairs.append((input_index, input_index + 1))
            input_index += 2
    graph: list[str] = []
    vs: list[str] = []
    aus: list[str] = []
    for i, ((item, duration, _), (vi, ai)) in enumerate(zip(selected, input_pairs)):
        v = f"v{i}"; a = f"a{i}"
        graph.append(f"[{vi}:v:0]fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,trim=duration={_fmt(duration)},setpts=PTS-STARTPTS[{v}]")
        graph.append(f"[{ai}:a:0]aresample={SAMPLE_RATE}:async=0,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=duration={_fmt(duration)},asetpts=PTS-STARTPTS[{a}]")
        vs.append(f"[{v}]"); aus.append(f"[{a}]")
    graph.append("".join(vs) + f"concat=n={len(vs)}:v=1:a=0[vcat]")
    graph.append("".join(aus) + f"concat=n={len(aus)}:v=0:a=1[acat]")
    graph.append(f"[vcat]format=yuv420p[vout];[acat]apad,atrim=duration={_fmt(limit)},asetpts=N/SR/TB[aout]")
    args += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]", "-r", str(FPS),
             "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", str(SAMPLE_RATE), "-ac", "2", "-movflags", "+faststart", str(output)]
    return args


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-edl", type=Path, default=RUN / "edl/visual-draft-540.json")
    ap.add_argument("--plan-output", type=Path, default=RUN / "edl/visual-draft-540.render-plan.json")
    ap.add_argument("--render-output", type=Path)
    ap.add_argument("--preview-duration", type=float, default=30.0)
    ap.add_argument("--ffmpeg", type=Path, default=Path(r"C:/ffmpeg/promo-9.0.1/bin/ffmpeg.exe"))
    ap.add_argument("--plan-only", action="store_true")
    args = ap.parse_args()
    edl = build_edl()
    args.output_edl.parent.mkdir(parents=True, exist_ok=True)
    args.output_edl.write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preview_out = args.render_output or (RUN / "edl/visual-draft-preview-30s.mp4")
    cmd = build_command(edl, preview_out, preview_duration=args.preview_duration)
    pinned_cmd = [str(args.ffmpeg.resolve()), *cmd[1:]]
    plan = {
        "kind": "vivhite_promo_visual_draft_render_plan_v1",
        "status": "executable_non_signoff_preview",
        "edl": args.output_edl.resolve().relative_to(REPO.resolve()).as_posix(),
        "target_duration_seconds": TARGET,
        "preview_duration_seconds": min(float(args.preview_duration), TARGET),
        "output": preview_out.resolve().relative_to(REPO.resolve()).as_posix(),
        "ffmpeg": str(args.ffmpeg.resolve()),
        "command_argv": pinned_cmd,
        "shell_command_preview": " ".join(shlex.quote(x) for x in pinned_cmd),
        "narration_mix": "not included in this minimal preview; narration manifest is recorded in EDL for the editorial renderer",
        "strict_signoff": False,
    }
    args.plan_output.parent.mkdir(parents=True, exist_ok=True)
    args.plan_output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"edl": str(args.output_edl), "plan": str(args.plan_output), "preview": str(preview_out), "preview_duration": plan["preview_duration_seconds"]}, ensure_ascii=False))
    if not args.plan_only:
        args.ffmpeg.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(args.ffmpeg), *cmd[1:]], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
