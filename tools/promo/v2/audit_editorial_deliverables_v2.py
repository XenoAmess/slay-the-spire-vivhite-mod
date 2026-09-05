#!/usr/bin/env python3
"""Full-decode and audit the director-approved editorial deliverables."""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[3]
RUN = ROOT / "tools/promo/runs/run-20260903T0012-director-v2-a1"
EDL_ROOT = RUN / "edl"
FFMPEG = pathlib.Path(r"C:\ffmpeg\bin\ffmpeg.exe")
FFPROBE = pathlib.Path(r"C:\ffmpeg\bin\ffprobe.exe")
DELIVERABLES = (
    ("master-540", EDL_ROOT / "editorial-master-540-v2-narrated-upper.mp4", 540.0, 32_400),
    ("hero-60", EDL_ROOT / "editorial-hero-60-v1-narrated-upper.mp4", 60.0, 3_600),
    ("cut-30", EDL_ROOT / "editorial-cut-30-v1-narrated-upper.mp4", 30.0, 1_800),
    ("cut-15", EDL_ROOT / "editorial-cut-15-v1-narrated-upper.mp4", 15.0, 900),
)


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def probe(path: pathlib.Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def audit_one(label: str, path: pathlib.Path, duration: float, frames: int) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = probe(path)
    videos = [row for row in payload["streams"] if row.get("codec_type") == "video"]
    audios = [row for row in payload["streams"] if row.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise RuntimeError(f"{label}: expected exactly one video and one audio stream")
    video, audio = videos[0], audios[0]
    checks = {
        "video_codec_h264": video.get("codec_name") == "h264",
        "geometry_1920x1080": video.get("width") == 1920 and video.get("height") == 1080,
        "pixel_format_yuv420p": video.get("pix_fmt") == "yuv420p",
        "frame_rates_60": video.get("r_frame_rate") == "60/1" and video.get("avg_frame_rate") == "60/1",
        "frame_count_exact": int(video.get("nb_frames", -1)) == frames,
        "video_duration_exact": abs(float(video.get("duration", -1)) - duration) <= 1 / 60,
        "audio_codec_aac": audio.get("codec_name") == "aac",
        "audio_48k_stereo": audio.get("sample_rate") == "48000" and audio.get("channels") == 2 and audio.get("channel_layout") == "stereo",
        "audio_duration_exact": abs(float(audio.get("duration", -1)) - duration) <= 1 / 60,
        "container_duration_exact": abs(float(payload["format"].get("duration", -1)) - duration) <= 1 / 60,
    }
    if not all(checks.values()):
        raise RuntimeError(f"{label}: media gate failed: {checks}")
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "NUL"],
        check=True,
    )
    ass_path = path.with_suffix(path.suffix + ".upper.ass")
    if not ass_path.is_file():
        raise FileNotFoundError(ass_path)
    ass_text = ass_path.read_text(encoding="utf-8-sig")
    subtitle_checks = {
        "upper_chinese_style": "Style: ChineseUpper" in ass_text and ",8,120,120,54,1" in ass_text,
        "upper_english_style": "Style: EnglishUpper" in ass_text and ",8,120,120,112,1" in ass_text,
        "dialogue_nonempty": ass_text.count("Dialogue:") > 0,
    }
    if not all(subtitle_checks.values()):
        raise RuntimeError(f"{label}: subtitle gate failed: {subtitle_checks}")
    return {
        "label": label,
        "status": "passed",
        "artifact": {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        },
        "expected": {"duration_seconds": duration, "video_frames": frames},
        "observed": {
            "container_duration_seconds": float(payload["format"]["duration"]),
            "video_duration_seconds": float(video["duration"]),
            "audio_duration_seconds": float(audio["duration"]),
            "video_frames": int(video["nb_frames"]),
        },
        "media_checks": checks,
        "full_decode": "passed_no_errors",
        "subtitle": {
            "path": ass_path.relative_to(ROOT).as_posix(),
            "bytes": ass_path.stat().st_size,
            "sha256": sha256(ass_path),
            "checks": subtitle_checks,
            "dialogue_lines": ass_text.count("Dialogue:"),
        },
    }


def main() -> int:
    master_edl_path = EDL_ROOT / "editorial-master-540-v2.json"
    master_edl = json.loads(master_edl_path.read_text(encoding="utf-8-sig"))
    placeholders = [row["segment_id"] for row in master_edl["segments"] if row["source"]["kind"] == "placeholder_color"]
    if placeholders:
        raise RuntimeError(f"editorial master still contains placeholders: {placeholders}")
    results = [audit_one(*row) for row in DELIVERABLES]
    report = {
        "schema_version": 1,
        "kind": "vivhite_promo_editorial_deliverables_technical_audit_v1",
        "status": "passed",
        "audited_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "master_edl": {
            "path": master_edl_path.relative_to(ROOT).as_posix(),
            "bytes": master_edl_path.stat().st_size,
            "sha256": sha256(master_edl_path),
            "segments": len(master_edl["segments"]),
            "placeholder_segments": 0,
            "duration_seconds": master_edl["target_duration_seconds"],
        },
        "deliverables": results,
        "audio_policy": {"game_audio": True, "voice": "zh-CN-XiaoxiaoNeural", "bgm": False},
        "evidence_boundary": {
            "editorial_complete": True,
            "strict_binder_signoff": False,
            "strict_gap": ["T16 native triad", "T18 native triad"],
        },
        "semantic_review": "pending_visual_contact_sheet_review",
        "human_signoff": False,
    }
    output = EDL_ROOT / "qa/editorial-deliverables-v2-technical-audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if output.exists() and output.read_bytes() != body:
        raise FileExistsError(f"refusing to overwrite differing audit: {output}")
    if not output.exists():
        with output.open("xb") as stream:
            stream.write(body)
    print(json.dumps({"status": "passed", "report": output.relative_to(ROOT).as_posix(), "deliverables": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
