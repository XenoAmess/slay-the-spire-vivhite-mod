#!/usr/bin/env python3
"""Mix the verified Xiaoxiao cue batch into the non-signoff visual draft.

This is an editorial preview path.  It never changes production rows or the
signed master EDL.  Video comes from the visual-draft render, while every
spoken cue is loaded from the hash-bound director-v2 narration manifest and
delayed to its manifest anchor.  The existing bilingual ASS is burned into a
new preview file so the result can be reviewed without a separate subtitle
player.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VIDEO = ROOT / "tools/promo/runs/run-20260903T0012-director-v2-a1/edl/visual-draft-540-v3.mp4"
DEFAULT_MANIFEST = ROOT / "tools/promo/runs/run-20260903T0040-director-v2-narration-a5/logs/director-v2-narration-manifest.json"
DEFAULT_ASS = ROOT / "tools/promo/runs/run-20260903T0040-director-v2-narration-a5/subtitles/full-master.bilingual.ass"
UPPER_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ChineseUpper,Microsoft YaHei,44,&H00FFFFFF,&H00FFFFFF,&H80000000,&H90000000,0,0,0,0,100,100,0,0,1,3,1,8,120,120,54,1
Style: EnglishUpper,Arial,31,&H00D8E8FF,&H00D8E8FF,&H80000000,&H90000000,0,1,0,0,100,100,0,0,1,2,1,8,120,120,112,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def esc(path: Path) -> str:
    # FFmpeg filter filename escaping for Windows paths.
    return str(path.resolve()).replace("\\", "/").replace("'", r"\'").replace(":", r"\:")


def ass_time(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    hours, rem = divmod(cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    whole, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{whole:02d}.{centis:02d}"


def ass_text(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def write_upper_ass(manifest_path: Path, output: Path, duration: float) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    lines = [UPPER_ASS_HEADER]
    for cue in manifest["cues"]:
        audio = cue.get("audio")
        if not audio or cue.get("provider_status") != "generated":
            continue
        start = float(cue["anchor_seconds"])
        end = min(duration, start + float(audio["duration_seconds"]))
        if end <= start:
            continue
        for layer, style, field in ((10, "ChineseUpper", "subtitle_zh"), (11, "EnglishUpper", "subtitle_en")):
            value = str(cue.get(field) or "").strip()
            if value:
                lines.append(f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},{cue['cue_id']},0,0,0,,{ass_text(value)}\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(lines), encoding="utf-8")
    return output


def command(video: Path, manifest_path: Path, ass_path: Path, output: Path, ffmpeg: Path, duration: float) -> list[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    cues = [c for c in manifest["cues"] if c.get("provider_status") == "generated" and c.get("audio")]
    run_root = manifest_path.parent.parent
    args = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video.resolve())]
    for cue in cues:
        audio_path = (run_root / cue["audio"]["path"]).resolve()
        if not audio_path.is_file():
            raise FileNotFoundError(audio_path)
        args += ["-i", str(audio_path)]
    graph: list[str] = []
    current = "g0"
    graph.append(f"[0:a]aresample=48000:async=0,aformat=sample_fmts=fltp:channel_layouts=stereo[{current}]")
    narration_labels: list[str] = []
    for index, cue in enumerate(cues):
        start = float(cue["anchor_seconds"])
        cue_dur = float(cue["audio"]["duration_seconds"])
        end = min(duration, start + cue_dur)
        next_label = f"g{index + 1}"
        graph.append(f"[{current}]volume=0.50:enable='between(t,{start:.6f},{end:.6f})'[{next_label}]")
        current = next_label
        label = f"n{index:03d}"
        narration_labels.append(f"[{label}]")
        delay = max(0, round(start * 1000))
        graph.append(
            f"[{index + 1}:a]atrim=duration={cue_dur:.6f},asetpts=PTS-STARTPTS,"
            f"aresample=48000:async=0,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"adelay=delays={delay}:all=1,apad,atrim=duration={duration:.6f}[{label}]"
        )
    graph.append(f"[{current}]apad,atrim=duration={duration:.6f},asetpts=N/SR/TB[game]")
    graph.append(
        "[game]" + "".join(narration_labels)
        + f"amix=inputs={len(narration_labels) + 1}:duration=first:dropout_transition=0:normalize=0,"
        f"aresample=48000:async=0,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad,atrim=duration={duration:.6f},asetpts=N/SR/TB[aout]"
    )
    graph_text = ";".join(graph)
    vf = f"subtitles=filename='{esc(ass_path)}'"
    args += [
        "-filter_complex", graph_text,
        "-map", "0:v:0", "-map", "[aout]",
        "-vf", vf,
        "-t", f"{duration:.6f}", "-r", "60",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(output.resolve()),
    ]
    return args


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--ass", type=Path, default=None, help="Optional prebuilt ASS. By default a top-safe bilingual ASS is generated beside the output.")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--ffmpeg", type=Path, required=True)
    ap.add_argument("--duration", type=float, default=540.0)
    ap.add_argument("--plan-only", action="store_true")
    args = ap.parse_args()
    if args.duration <= 0 or args.duration > 540:
        raise SystemExit("duration must be in (0, 540]")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ass_path = args.ass if args.ass is not None else args.output.with_suffix(args.output.suffix + ".upper.ass")
    if args.ass is None:
        write_upper_ass(args.manifest, ass_path, args.duration)
    cmd = command(args.video, args.manifest, ass_path, args.output, args.ffmpeg, args.duration)
    plan = args.output.with_suffix(args.output.suffix + ".plan.json")
    plan.write_text(json.dumps({"kind": "vivhite_visual_draft_narration_mix_plan_v1", "duration_seconds": args.duration, "subtitle_ass": str(ass_path.resolve()), "subtitle_placement": "upper_safe_area", "command": cmd, "strict_signoff": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "plan": str(plan.resolve()), "duration": args.duration, "strict_signoff": False}, ensure_ascii=False))
    if not args.plan_only:
        subprocess.run(cmd, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
