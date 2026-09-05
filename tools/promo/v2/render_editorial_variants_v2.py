#!/usr/bin/env python3
"""Render the director's 60/30/15 second edits from the final take batch."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import subprocess
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[3]
RUN = ROOT / "tools/promo/runs/run-20260903T0012-director-v2-a1"
MASTER_EDL = RUN / "edl/editorial-master-540-v1.json"
STORYBOARD = ROOT / "tools/promo/v2/storyboard.json"
NARRATION_MANIFEST = ROOT / "tools/promo/runs/run-20260903T0040-director-v2-narration-a5/logs/director-v2-narration-manifest.json"
RECIPE_ROOT = ROOT / "tools/promo/v2/edl"
FFMPEG = pathlib.Path(r"C:\ffmpeg\promo-9.0.1\bin\ffmpeg.exe")
VARIANTS = ("hero-60", "cut-30", "cut-15")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def write_json_new(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != body:
            raise FileExistsError(f"refusing to overwrite differing artifact: {path}")
        return
    with path.open("xb") as stream:
        stream.write(body)


def file_record(path: pathlib.Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}


def cue_owners(storyboard: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for shot in storyboard["shots"]:
        for subshot in shot["subshots"]:
            cue = subshot.get("cue") or {}
            cue_id = cue.get("cue_id")
            if cue_id:
                result[str(cue_id)] = str(subshot["subshot_id"])
    return result


def build_variant(
    master: dict[str, Any], recipe: dict[str, Any], narration: dict[str, Any], owners: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    variant_id = str(recipe["variant_id"])
    target = float(recipe["target_duration_seconds"])
    source_segments = {str(item["subshot_id"]): item for item in master["segments"]}
    output_segments: list[dict[str, Any]] = []
    clip_positions: dict[str, tuple[float, float]] = {}
    cursor = 0.0
    for index, clip in enumerate(recipe["clips"], 1):
        source_id = str(clip["source_subshot_id"])
        if source_id not in source_segments:
            raise ValueError(f"{variant_id} references missing source subshot {source_id}")
        source_segment = source_segments[source_id]
        offset = float(clip["in_offset_seconds"])
        duration = float(clip["duration_seconds"])
        available = float(source_segment["duration_seconds"])
        if offset < 0 or duration <= 0 or offset + duration > available + 1e-6:
            raise ValueError(f"{variant_id}/{source_id} clip is outside its source segment")
        row = copy.deepcopy(source_segment)
        row["segment_id"] = f"{variant_id}-{index:02d}-{clip['clip_id']}"
        row["source_subshot_id"] = source_id
        row["subshot_id"] = row["segment_id"]
        row["timeline"] = {"start_seconds": cursor, "end_seconds": cursor + duration, "duration_seconds": duration}
        row["duration_seconds"] = duration
        row["editorial_status"] = "director_approved_short_variant"
        if row["source"]["kind"] == "video_take":
            source_in = float(row["source"]["in_seconds"]) + offset
            row["source"]["in_seconds"] = source_in
            row["source"]["out_seconds"] = source_in + duration
        clip_positions[source_id] = (cursor, offset)
        output_segments.append(row)
        cursor += duration
    if abs(cursor - target) > 1e-6:
        raise ValueError(f"{variant_id} duration {cursor} does not equal {target}")

    narration_by_id = {str(item["cue_id"]): item for item in narration["cues"]}
    selected_cues: list[dict[str, Any]] = []
    for cue_id in recipe["cue_ids"]:
        cue_id = str(cue_id)
        if cue_id not in narration_by_id or cue_id not in owners:
            raise ValueError(f"{variant_id} references unknown narration cue {cue_id}")
        owner = owners[cue_id]
        if owner not in clip_positions:
            raise ValueError(f"{variant_id} narration cue {cue_id} owner {owner} is not selected")
        variant_start, clip_offset = clip_positions[owner]
        master_start = float(source_segments[owner]["timeline"]["start_seconds"])
        source_anchor = float(narration_by_id[cue_id]["anchor_seconds"])
        new_anchor = variant_start + source_anchor - master_start - clip_offset
        cue = copy.deepcopy(narration_by_id[cue_id])
        cue["source_anchor_seconds"] = source_anchor
        cue["anchor_seconds"] = new_anchor
        if new_anchor < -1e-6 or new_anchor >= target:
            raise ValueError(f"{variant_id} narration cue {cue_id} maps outside the variant")
        selected_cues.append(cue)

    variant_edl = {
        "schema_version": 1,
        "kind": "vivhite_promo_editorial_variant_edl_v1",
        "edit_id": variant_id,
        "status": "director_approved_editorial_not_strict_signoff",
        "target_duration_seconds": target,
        "canvas": copy.deepcopy(master["canvas"]),
        "source_master_edl": file_record(MASTER_EDL),
        "source_recipe": copy.deepcopy(recipe),
        "segments": output_segments,
        "strict_boundary": copy.deepcopy(master["strict_boundary"]),
        "narration": {"cue_ids": list(recipe["cue_ids"]), "voice": "zh-CN-XiaoxiaoNeural", "bgm": False},
    }
    variant_manifest = copy.deepcopy(narration)
    variant_manifest["kind"] = "vivhite_promo_editorial_variant_narration_manifest_v1"
    variant_manifest["variant_id"] = variant_id
    variant_manifest["target_duration_seconds"] = target
    variant_manifest["source_manifest"] = file_record(NARRATION_MANIFEST)
    variant_manifest["cues"] = selected_cues
    variant_manifest["cue_count"] = len(selected_cues)
    variant_manifest["include_bgm"] = False
    return variant_edl, variant_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", type=pathlib.Path, default=FFMPEG)
    parser.add_argument("--variant", action="append", choices=VARIANTS)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    selected = tuple(args.variant or VARIANTS)
    if not args.ffmpeg.is_file():
        raise FileNotFoundError(args.ffmpeg)

    sys.path.insert(0, str(ROOT / "tools/promo/v2"))
    import build_visual_draft_v2 as builder

    master = json.loads(MASTER_EDL.read_text(encoding="utf-8-sig"))
    storyboard = json.loads(STORYBOARD.read_text(encoding="utf-8-sig"))
    narration = json.loads(NARRATION_MANIFEST.read_text(encoding="utf-8-sig"))
    owners = cue_owners(storyboard)
    results: list[dict[str, Any]] = []
    for variant_id in selected:
        recipe_path = RECIPE_ROOT / f"{variant_id}.recipe.json"
        recipe = json.loads(recipe_path.read_text(encoding="utf-8-sig"))
        edl, variant_manifest = build_variant(master, recipe, narration, owners)
        edl_path = RUN / "edl" / f"editorial-{variant_id}-v1.json"
        narration_path = NARRATION_MANIFEST.parent / f"editorial-{variant_id}-v1.manifest.json"
        base_output = RUN / "edl" / f"editorial-{variant_id}-v1-base.mp4"
        final_output = RUN / "edl" / f"editorial-{variant_id}-v1-narrated-upper.mp4"
        write_json_new(edl_path, edl)
        write_json_new(narration_path, variant_manifest)
        for output in (base_output, final_output):
            if output.exists() and not args.plan_only:
                raise FileExistsError(f"refusing to overwrite existing render: {output}")
        command = builder.build_command(edl, base_output, preview_duration=float(edl["target_duration_seconds"]))
        command[0] = str(args.ffmpeg.resolve())
        plan_path = RUN / "edl" / f"editorial-{variant_id}-v1.render-plan.json"
        write_json_new(plan_path, {
            "schema_version": 1,
            "kind": "vivhite_promo_editorial_variant_render_plan_v1",
            "variant_id": variant_id,
            "edl": file_record(edl_path),
            "narration_manifest": file_record(narration_path),
            "base_output": base_output.relative_to(ROOT).as_posix(),
            "final_output": final_output.relative_to(ROOT).as_posix(),
            "command": command,
            "strict_signoff": False,
        })
        if not args.plan_only:
            subprocess.run(command, check=True)
            subprocess.run([
                sys.executable, "-B", str(ROOT / "tools/promo/v2/mix_visual_draft_narration.py"),
                "--video", str(base_output), "--manifest", str(narration_path),
                "--output", str(final_output), "--ffmpeg", str(args.ffmpeg),
                "--duration", str(edl["target_duration_seconds"]),
            ], check=True)
        results.append({
            "variant_id": variant_id,
            "duration_seconds": edl["target_duration_seconds"],
            "edl": file_record(edl_path),
            "narration_manifest": file_record(narration_path),
            "base_output": file_record(base_output) if base_output.exists() else None,
            "final_output": file_record(final_output) if final_output.exists() else None,
        })
    print(json.dumps({"status": "rendered" if not args.plan_only else "planned", "variants": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
