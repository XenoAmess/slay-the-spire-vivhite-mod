"""Generate the project-owned Vivhite narration and subtitle artifacts.

This is deliberately a project-side producer.  It reads the checked-in
storyboard/config, asks the pinned xAR TTS contract for the
``zh-CN-XiaoxiaoNeural`` request, and stores immutable, hash-bound copies in a
new promo run.  It does not touch the game, OBS, the Brain, or any existing
run.  A destination that already contains a generated artifact is rejected;
retrying therefore requires a new ``runs/run-...`` directory.

The actual Edge request is made by xAR's optional ``EdgeTtsProvider``.  The
run-local ``tts-cache`` retains xAR's content-addressed metadata while the
named files in ``narration/`` are the paths consumed by the Vivhite composer.
The provider request, tool versions, ffprobe output, and every failure are
recorded in ``logs/narration-manifest.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Mapping


VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "+0%"
PITCH = "+0Hz"
VOLUME = "+0%"
AUDIO_FORMAT = "mp3"
CACHE_SALT = "vivhite-player-promo:v1"
MAX_ATTEMPTS = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def file_record(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(root.resolve()).as_posix(),
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def load_project(project_path: Path) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    project = json.loads(project_path.read_text(encoding="utf-8-sig"))
    if not isinstance(project, dict):
        raise ValueError("project.json root must be an object")
    if project.get("locales", {}).get("narration") != "zh-CN":
        raise ValueError("project narration locale must remain zh-CN")
    chapters = project.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("project must contain chapters")
    by_id: dict[str, Mapping[str, Any]] = {}
    for chapter in chapters:
        if not isinstance(chapter, dict):
            raise ValueError("chapter must be an object")
        chapter_id = chapter.get("id")
        cues = chapter.get("cues")
        if not isinstance(chapter_id, str) or not isinstance(cues, list) or len(cues) != 1:
            raise ValueError(f"chapter {chapter_id!r} must have exactly one cue")
        cue = cues[0]
        if not isinstance(cue, dict) or not isinstance(cue.get("id"), str):
            raise ValueError(f"chapter {chapter_id!r} cue is malformed")
        narration = cue.get("narration")
        subtitles = cue.get("subtitles")
        if not isinstance(narration, dict) or not isinstance(subtitles, dict):
            raise ValueError(f"cue {cue.get('id')!r} lacks localized text")
        zh = narration.get("zh-CN")
        en = subtitles.get("en", narration.get("en"))
        zh_sub = subtitles.get("zh-CN", zh)
        if not all(isinstance(value, str) and value.strip() for value in (zh, zh_sub, en)):
            raise ValueError(f"cue {cue.get('id')!r} needs non-empty zh-CN/en text")
        by_id[str(chapter_id)] = {
            "chapter_id": str(chapter_id),
            "cue_id": str(cue["id"]),
            "zh": str(zh).strip(),
            "zh_subtitle": str(zh_sub).strip(),
            "en_subtitle": str(en).strip(),
        }
    return project, by_id


def load_storyboard(storyboard_path: Path, chapters: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8-sig"))
    shots = storyboard.get("shots") if isinstance(storyboard, dict) else None
    if not isinstance(shots, list) or not shots:
        raise ValueError("storyboard must contain shots")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for shot in shots:
        if not isinstance(shot, dict):
            raise ValueError("storyboard shot must be an object")
        shot_id = shot.get("shot_id")
        chapter_id = shot.get("chapter_id")
        if not isinstance(shot_id, str) or shot_id in seen:
            raise ValueError(f"duplicate or malformed shot id: {shot_id!r}")
        if not isinstance(chapter_id, str) or chapter_id not in chapters:
            raise ValueError(f"shot {shot_id!r} references unknown chapter")
        cue = chapters[chapter_id]
        if shot.get("cue_id") != cue["cue_id"]:
            raise ValueError(f"shot {shot_id!r} cue mapping disagrees with project")
        seen.add(shot_id)
        result.append({**shot, **cue, "shot_id": shot_id})
    return result


def ffprobe_audio(path: Path, ffprobe: Path) -> dict[str, Any]:
    command = [
        str(ffprobe),
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name:stream=index,codec_name,codec_type,sample_rate,channels,duration",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe rc={completed.returncode}: {completed.stderr[-500:]}")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("ffprobe output is not an object")
    return {"argv": command, "result": value}


def ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(float(seconds) * 100.0)))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, hundredths = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{hundredths:02d}"


def srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds) * 1000.0)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def ass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chinese,Microsoft YaHei,46,&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,80,80,78,1
Style: English,Arial,34,&H00D8E8FF,&H00D8E8FF,&H80000000,&H80000000,0,1,0,0,100,100,0,0,1,2,1,2,80,80,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_subtitles(root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    cursor = 0.0
    events: list[dict[str, Any]] = []
    for row in rows:
        duration = max(0.5, float(row.get("duration_seconds") or 0.5))
        start = cursor
        end = cursor + duration
        row["timeline_start_seconds"] = round(start, 3)
        row["timeline_end_seconds"] = round(end, 3)
        events.append({"start": start, "end": end, **row})
        cursor = end

    bilingual = [ASS_HEADER]
    chinese = [ASS_HEADER]
    english = [ASS_HEADER]
    srt = []
    for index, row in enumerate(events, 1):
        start = ass_time(row["start"])
        end = ass_time(row["end"])
        zh = ass_escape(row["zh_subtitle"])
        en = ass_escape(row["en_subtitle"])
        bilingual.append(f"Dialogue: 0,{start},{end},Chinese,,0,0,78,,{zh}\\N{{\\i1}}{en}{{\\i0}}\n")
        chinese.append(f"Dialogue: 0,{start},{end},Chinese,,0,0,78,,{zh}\n")
        english.append(f"Dialogue: 0,{start},{end},English,,0,0,30,,{en}\n")
        srt.append(f"{index}\n{srt_time(row['start'])} --> {srt_time(row['end'])}\n{row['zh_subtitle']}\n{row['en_subtitle']}\n")

    subtitle_dir = root / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "bilingual_ass": subtitle_dir / "vivhite-narration-bilingual.ass",
        "zh_cn_ass": subtitle_dir / "vivhite-narration.zh-CN.ass",
        "en_ass": subtitle_dir / "vivhite-narration.en.ass",
        "bilingual_srt": subtitle_dir / "vivhite-narration-bilingual.srt",
    }
    for path, content in (
        (files["bilingual_ass"], "".join(bilingual)),
        (files["zh_cn_ass"], "".join(chinese)),
        (files["en_ass"], "".join(english)),
        (files["bilingual_srt"], "\n".join(srt) + "\n"),
    ):
        path.write_text(content, encoding="utf-8", newline="\n")
    return {
        "total_duration_seconds": round(cursor, 3),
        "files": {
            key: {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for key, path in files.items()
        },
        "events": events,
    }


def git_head(path: Path) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, encoding="ascii", timeout=10)
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def generate(project_path: Path, run_root: Path, ffprobe: Path) -> int:
    project_path = project_path.resolve()
    run_root = run_root.resolve()
    if run_root.exists() and any(run_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty run: {run_root}")
    run_root.mkdir(parents=True, exist_ok=False)
    narration_dir = run_root / "narration"
    narration_dir.mkdir()
    (run_root / "logs").mkdir()
    (run_root / "tts-cache").mkdir()

    project, chapters = load_project(project_path)
    storyboard = load_storyboard(project_path.parent / "storyboard.json", chapters)
    preset = json.loads((project_path.parent / "preset.json").read_text(encoding="utf-8-sig"))
    if preset.get("voice") != VOICE or preset.get("include_bgm") is not False:
        raise ValueError("preset voice/BGM policy is not the pinned Xiaoxiao/no-BGM policy")

    # Import xAR lazily so validate-only project checks remain dependency-free.
    xar_source = os.environ.get("XAR_PROMO_TOOLCHAIN_SOURCE")
    if xar_source:
        src = Path(xar_source).expanduser().resolve() / "src"
        if src.is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
    from xar_promo.tts import EdgeTtsProvider, TtsCache  # type: ignore
    from vivhite_promo.preset import build_narration_request  # type: ignore

    provider = EdgeTtsProvider()
    identity = provider.identity
    if identity.provider_id != "edge-tts":
        raise ValueError(f"unexpected TTS provider: {identity.provider_id}")
    cache = TtsCache(run_root / "tts-cache")
    rows: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for shot in storyboard:
        shot_id = shot["shot_id"]
        text = shot["zh"]
        request = build_narration_request(text)
        destination = narration_dir / f"{shot_id}.mp3"
        text_path = narration_dir / f"{shot_id}.zh-CN.txt"
        # Keep the exact authoring text beside the returned bytes.  This is a
        # provenance artifact, not a regenerated/normalized copy of the cue.
        text_path.write_text(text + "\n", encoding="utf-8", newline="\n")
        request_record: dict[str, Any] = {
            "shot_id": shot_id,
            "chapter_id": shot["chapter_id"],
            "cue_id": shot["cue_id"],
            "text": text,
            "voice": getattr(request, "voice", VOICE),
            "rate": getattr(request, "rate", RATE),
            "pitch": getattr(request, "pitch", PITCH),
            "volume": getattr(request, "volume", VOLUME),
            "audio_format": getattr(request, "audio_format", AUDIO_FORMAT),
            "cache_salt": getattr(request, "cache_salt", CACHE_SALT),
            "destination": destination.relative_to(run_root).as_posix(),
            "script_artifact": file_record(text_path, run_root),
            "status": "pending",
            "attempts": [],
        }
        try:
            entry = cache.get_or_create(request, provider, max_attempts=MAX_ATTEMPTS, retry_backoff_seconds=1.0)
            shutil.copyfile(entry.media_path, destination)
            if sha256_file(entry.media_path) != sha256_file(destination):
                raise RuntimeError("named narration copy changed bytes")
            probe = ffprobe_audio(destination, ffprobe)
            request_record.update({
                "status": "generated" if not entry.cache_hit else "cache-hit",
                "fingerprint": entry.fingerprint,
                "cache_hit": bool(entry.cache_hit),
                "cache_entry": entry.media_path.relative_to(run_root).as_posix(),
                "artifact": file_record(destination, run_root),
                "ffprobe": probe,
            })
            sidecar = narration_dir / f"{shot_id}.edge-tts.json"
            write_json(
                sidecar,
                {
                    "format_version": 1,
                    "kind": "vivhite_promo_edge_tts_cue",
                    "generated_utc": utc_now(),
                    "shot_id": shot_id,
                    "chapter_id": shot["chapter_id"],
                    "cue_id": shot["cue_id"],
                    "provider": {"id": identity.provider_id, "tool_version": identity.tool_version},
                    "request": {key: request_record[key] for key in ("text", "voice", "rate", "pitch", "volume", "audio_format", "cache_salt")},
                    "fingerprint": entry.fingerprint,
                    "audio": request_record["artifact"],
                    "cache_entry": request_record["cache_entry"],
                    "ffprobe": probe,
                    "status": request_record["status"],
                },
            )
            request_record["metadata_artifact"] = file_record(sidecar, run_root)
            format_info = probe["result"].get("format", {})
            duration = float(format_info.get("duration") or 0.5)
            rows.append({
                "shot_id": shot_id,
                "chapter_id": shot["chapter_id"],
                "cue_id": shot["cue_id"],
                "zh": text,
                "zh_subtitle": shot["zh_subtitle"],
                "en_subtitle": shot["en_subtitle"],
                "audio": request_record["artifact"],
                "duration_seconds": duration,
            })
        except Exception as error:  # preserve the request and exact failure
            request_record.update({
                "status": "failed",
                "error": {"type": type(error).__name__, "message": str(error)},
            })
            sidecar = narration_dir / f"{shot_id}.edge-tts.json"
            write_json(
                sidecar,
                {
                    "format_version": 1,
                    "kind": "vivhite_promo_edge_tts_cue",
                    "generated_utc": utc_now(),
                    "shot_id": shot_id,
                    "chapter_id": shot["chapter_id"],
                    "cue_id": shot["cue_id"],
                    "provider": {"id": identity.provider_id, "tool_version": identity.tool_version},
                    "request": {key: request_record[key] for key in ("text", "voice", "rate", "pitch", "volume", "audio_format", "cache_salt")},
                    "status": "failed",
                    "error": request_record["error"],
                },
            )
            request_record["metadata_artifact"] = file_record(sidecar, run_root)
            failures.append(request_record)
        requests.append(request_record)

    subtitle_manifest = write_subtitles(run_root, rows) if rows else {"total_duration_seconds": 0.0, "files": {}, "events": []}
    manifest = {
        "schema": "vivhite-promo-narration-run-v1",
        "created_at": utc_now(),
        "run_id": run_root.name,
        "project": {
            "id": project.get("project", {}).get("id"),
            "config": file_record(project_path, project_path.parent),
            "preset": file_record(project_path.parent / "preset.json", project_path.parent),
            "storyboard": file_record(project_path.parent / "storyboard.json", project_path.parent),
        },
        "policy": {
            "voice": VOICE,
            "rate": RATE,
            "pitch": PITCH,
            "volume": VOLUME,
            "audio_format": AUDIO_FORMAT,
            "include_bgm": False,
            "provider": {"id": identity.provider_id, "tool_version": identity.tool_version},
            "max_attempts_per_cue": MAX_ATTEMPTS,
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "xar_source": xar_source,
            "xar_git_head": git_head(Path(xar_source).resolve()) if xar_source else None,
            "project_git_head": git_head(project_path.parent.parent.parent),
            "ffprobe": str(ffprobe),
            "ffprobe_sha256": sha256_file(ffprobe) if ffprobe.is_file() else None,
        },
        "requests": requests,
        "subtitle_manifest": subtitle_manifest,
        "summary": {
            "requested": len(requests),
            "generated": sum(1 for item in requests if item["status"] in {"generated", "cache-hit"}),
            "failed": len(failures),
            "total_audio_seconds": round(sum(float(row.get("duration_seconds") or 0.0) for row in rows), 3),
            "bgm": "disabled",
        },
    }
    manifest_path = run_root / "logs" / "narration-manifest.json"
    write_json(manifest_path, manifest)
    write_json(run_root / "logs" / "narration-requests.json", {"schema": "vivhite-promo-tts-requests-v1", "requests": requests})
    write_json(run_root / "logs" / "narration-failures.json", {"schema": "vivhite-promo-tts-failures-v1", "failures": failures})
    (run_root / "audio-policy.json").write_text(
        json.dumps({"include_bgm": False, "narration_voice": VOICE, "game_audio": "provided by capture run", "sfx": "provided by capture run"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"run": str(run_root), "manifest": str(manifest_path), **manifest["summary"]}, ensure_ascii=False))
    return 0 if not failures else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).with_name("project.json"))
    parser.add_argument("--run", type=Path, required=True, help="new, empty run directory")
    parser.add_argument("--ffprobe", type=Path, default=Path(r"C:\ffmpeg\bin\ffprobe.exe"))
    args = parser.parse_args()
    try:
        return generate(args.project, args.run, args.ffprobe.resolve())
    except Exception as error:
        print(f"narration generation failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
