"""Generate the full-master Vivhite narration and bilingual subtitles.

This is a project-side producer for ``full-master-script.json``.  It keeps the
long-form script separate from the canonical ten-shot storyboard used by the
short-candidate producer, while retaining the same pinned xAR Edge TTS
contract.  Every invocation requires a new run directory and records the
request, returned bytes, ffprobe result, and subtitle timeline.  It never
touches OBS, the game, or an existing run.

Typical invocation (from the repository root)::

    uv run --no-project --with edge-tts --with imageio-ffmpeg python \
      tools/promo/generate_full_master_narration.py \
      --run tools/promo/runs/run-<utc>-full-master-tts-a1

The voice and BGM policy are intentionally not command-line options: the
script is bound to ``zh-CN-XiaoxiaoNeural`` and no external BGM stem.
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


PROMO_ROOT = Path(__file__).resolve().parent
DEFAULT_SCRIPT = PROMO_ROOT / "full-master-script.json"
DEFAULT_FFPROBE = Path(r"C:\ffmpeg\bin\ffprobe.exe")
VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "+0%"
PITCH = "+0Hz"
VOLUME = "+0%"
AUDIO_FORMAT = "mp3"
# ``build_narration_request`` in the project preset owns the cache namespace;
# keep this constant aligned for documentation/fallback records.
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
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(partial, path)


def _load_script(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("kind") != "vivhite_promo_full_master_script":
        raise ValueError("script must declare vivhite_promo_full_master_script")
    if payload.get("project_id") != "vivhite-player-promo":
        raise ValueError("script project_id does not match the Vivhite promo")
    duration = payload.get("target_duration_seconds")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError("script target_duration_seconds must be positive")
    policy = payload.get("audio_policy")
    if not isinstance(policy, dict):
        raise ValueError("script audio_policy is missing")
    if policy.get("voice") != VOICE or policy.get("include_bgm") is not False:
        raise ValueError("script must remain pinned to Xiaoxiao/no-BGM")
    chapters = payload.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("script chapters must be a non-empty array")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous_anchor = -1.0
    for chapter in chapters:
        if not isinstance(chapter, dict):
            raise ValueError("chapter must be an object")
        chapter_id = chapter.get("chapter_id")
        shot_id = chapter.get("shot_id")
        window = chapter.get("window")
        cues = chapter.get("cues")
        if not isinstance(chapter_id, str) or not isinstance(shot_id, str):
            raise ValueError("chapter_id and shot_id are required")
        if not isinstance(window, dict):
            raise ValueError(f"chapter {chapter_id!r} has no window")
        chapter_start = float(window.get("start_seconds", -1))
        chapter_end = float(window.get("end_seconds", -1))
        if chapter_start < 0 or chapter_end <= chapter_start:
            raise ValueError(f"chapter {chapter_id!r} has an invalid window")
        if not isinstance(cues, list) or not cues:
            raise ValueError(f"chapter {chapter_id!r} has no cues")
        for cue in cues:
            if not isinstance(cue, dict):
                raise ValueError("cue must be an object")
            cue_id = cue.get("cue_id")
            text = cue.get("narration_zh")
            zh = cue.get("subtitle_zh")
            en = cue.get("subtitle_en")
            anchor = cue.get("anchor_seconds")
            window_seconds = cue.get("subtitle_window_seconds")
            if not isinstance(cue_id, str) or cue_id in seen:
                raise ValueError(f"duplicate or malformed cue id: {cue_id!r}")
            if not all(isinstance(value, str) and value.strip() for value in (text, zh, en)):
                raise ValueError(f"cue {cue_id!r} needs non-empty narration and subtitles")
            if not isinstance(anchor, (int, float)) or not isinstance(window_seconds, (int, float)):
                raise ValueError(f"cue {cue_id!r} needs numeric anchor/window")
            absolute_anchor = float(anchor)
            if absolute_anchor < chapter_start or absolute_anchor >= chapter_end:
                raise ValueError(f"cue {cue_id!r} lies outside chapter window")
            if absolute_anchor < previous_anchor:
                raise ValueError("cue anchors must be monotonic")
            if float(window_seconds) <= 0:
                raise ValueError(f"cue {cue_id!r} has a non-positive subtitle window")
            if absolute_anchor + float(window_seconds) > chapter_end + 1e-6:
                raise ValueError(f"cue {cue_id!r} subtitle window exceeds chapter window")
            if absolute_anchor + float(window_seconds) > float(duration) + 1e-6:
                raise ValueError(f"cue {cue_id!r} subtitle window exceeds target duration")
            seen.add(cue_id)
            previous_anchor = absolute_anchor
            rows.append(
                {
                    "cue_id": cue_id,
                    "chapter_id": chapter_id,
                    "shot_id": shot_id,
                    "anchor_seconds": absolute_anchor,
                    "subtitle_window_seconds": float(window_seconds),
                    "narration_zh": text.strip(),
                    "subtitle_zh": zh.strip(),
                    "subtitle_en": en.strip(),
                    "evidence": cue.get("evidence", {}),
                    "chapter_window": {
                        "start_seconds": chapter_start,
                        "end_seconds": chapter_end,
                    },
                }
            )
    if not rows:
        raise ValueError("script contains no cues")
    if rows[-1]["anchor_seconds"] >= float(duration):
        raise ValueError("last cue anchor must fit inside target duration")
    return payload, rows


def _load_xar() -> tuple[Any, Any, Any, Any]:
    xar_source = os.environ.get("XAR_PROMO_TOOLCHAIN_SOURCE")
    if xar_source:
        source_root = Path(xar_source).expanduser().resolve() / "src"
        if source_root.is_dir() and str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
    try:
        from xar_promo.tts import EdgeTtsProvider, TtsCache  # type: ignore
        from vivhite_promo.preset import build_narration_request  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "xAR TTS dependencies are unavailable; run with uv --with edge-tts "
            "and set XAR_PROMO_TOOLCHAIN_SOURCE"
        ) from exc
    provider = EdgeTtsProvider()
    if provider.identity.provider_id != "edge-tts":
        raise RuntimeError(f"unexpected TTS provider: {provider.identity.provider_id}")
    return provider, TtsCache, build_narration_request, xar_source


def _ffprobe_audio(path: Path, ffprobe: Path) -> dict[str, Any]:
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
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe rc={result.returncode}: {result.stderr[-500:]}")
    parsed = json.loads(result.stdout)
    if not isinstance(parsed, dict):
        raise ValueError("ffprobe output is not an object")
    return {"argv": command, "result": parsed}


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(float(seconds) * 100.0)))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, hundredths = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{hundredths:02d}"


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds) * 1000.0)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _ass_escape(value: str) -> str:
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


def _write_subtitles(root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    bilingual = [ASS_HEADER]
    chinese = [ASS_HEADER]
    english = [ASS_HEADER]
    srt: list[str] = []
    warnings: list[str] = []
    for index, row in enumerate(rows, 1):
        start = float(row["anchor_seconds"])
        # The authored window keeps short subtitles readable even if a TTS
        # encoder reports a small trailing frame.  If the actual audio is
        # longer, extend the event so it remains bound to the whole cue.
        end = max(
            start + float(row["subtitle_window_seconds"]),
            start + float(row.get("duration_seconds") or 0.0),
        )
        next_start = row.get("next_anchor_seconds")
        if isinstance(next_start, (int, float)) and end > float(next_start):
            warnings.append(
                f"{row['cue_id']} subtitle/audio window overlaps next cue by "
                f"{end - float(next_start):.3f}s"
            )
        row["timeline_start_seconds"] = round(start, 3)
        row["timeline_end_seconds"] = round(end, 3)
        zh = _ass_escape(str(row["subtitle_zh"]))
        en = _ass_escape(str(row["subtitle_en"]))
        bilingual.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Chinese,,0,0,78,,"
            f"{zh}\\N{{\\i1}}{en}{{\\i0}}\n"
        )
        chinese.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Chinese,,0,0,78,,{zh}\n"
        )
        english.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},English,,0,0,30,,{en}\n"
        )
        srt.append(
            f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n"
            f"{row['subtitle_zh']}\n{row['subtitle_en']}\n"
        )

    subtitle_dir = root / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "bilingual_ass": subtitle_dir / "full-master.bilingual.ass",
        "zh_cn_ass": subtitle_dir / "full-master.zh-CN.ass",
        "en_ass": subtitle_dir / "full-master.en.ass",
        "bilingual_srt": subtitle_dir / "full-master.bilingual.srt",
    }
    contents = {
        files["bilingual_ass"]: "".join(bilingual),
        files["zh_cn_ass"]: "".join(chinese),
        files["en_ass"]: "".join(english),
        files["bilingual_srt"]: "\n".join(srt) + "\n",
    }
    for path, content in contents.items():
        path.write_text(content, encoding="utf-8", newline="\n")
    return {
        "total_timeline_seconds": round(max(row["timeline_end_seconds"] for row in rows), 3),
        "warnings": warnings,
        "files": {
            key: {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for key, path in files.items()
        },
    }


def generate(script_path: Path, run_root: Path, ffprobe: Path) -> int:
    script_path = script_path.expanduser().resolve()
    run_root = run_root.expanduser().resolve()
    ffprobe = ffprobe.expanduser().resolve()
    if run_root.exists() and any(run_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty run: {run_root}")
    if not ffprobe.is_file():
        raise FileNotFoundError(f"ffprobe is missing: {ffprobe}")
    script, rows = _load_script(script_path)
    provider, cache_type, build_request, xar_source = _load_xar()

    run_root.mkdir(parents=True, exist_ok=False)
    narration_dir = run_root / "narration"
    narration_dir.mkdir()
    (run_root / "logs").mkdir()
    (run_root / "tts-cache").mkdir()
    cache = cache_type(run_root / "tts-cache")
    identity = provider.identity

    requests: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        cue_id = row["cue_id"]
        text_path = narration_dir / f"{cue_id}.zh-CN.txt"
        destination = narration_dir / f"{cue_id}.mp3"
        text_path.write_text(row["narration_zh"] + "\n", encoding="utf-8", newline="\n")
        request = build_request(row["narration_zh"])
        # The project preset's request has the authoritative cache salt.  The
        # explicit check prevents a future provider change from silently
        # mixing this long-form run with another voice or project.
        request_voice = getattr(request, "voice", VOICE)
        if request_voice != VOICE:
            raise ValueError(f"cue {cue_id} request voice is {request_voice!r}, not {VOICE!r}")
        record: dict[str, Any] = {
            "index": index,
            "cue_id": cue_id,
            "chapter_id": row["chapter_id"],
            "shot_id": row["shot_id"],
            "anchor_seconds": row["anchor_seconds"],
            "text": row["narration_zh"],
            "voice": request_voice,
            "rate": getattr(request, "rate", RATE),
            "pitch": getattr(request, "pitch", PITCH),
            "volume": getattr(request, "volume", VOLUME),
            "audio_format": getattr(request, "audio_format", AUDIO_FORMAT),
            "cache_salt": getattr(request, "cache_salt", CACHE_SALT),
            "destination": destination.relative_to(run_root).as_posix(),
            "script_artifact": file_record(text_path, run_root),
            "status": "pending",
        }
        try:
            entry = cache.get_or_create(
                request,
                provider,
                max_attempts=MAX_ATTEMPTS,
                retry_backoff_seconds=1.0,
            )
            shutil.copyfile(entry.media_path, destination)
            if sha256_file(entry.media_path) != sha256_file(destination):
                raise RuntimeError("named narration copy changed bytes")
            probe = _ffprobe_audio(destination, ffprobe)
            format_info = probe["result"].get("format", {})
            duration = float(format_info.get("duration") or 0.0)
            if duration <= 0:
                raise ValueError(f"cue {cue_id} has no positive ffprobe duration")
            record.update(
                {
                    "status": "cache-hit" if entry.cache_hit else "generated",
                    "cache_hit": bool(entry.cache_hit),
                    "fingerprint": entry.fingerprint,
                    "cache_entry": entry.media_path.relative_to(run_root).as_posix(),
                    "artifact": file_record(destination, run_root),
                    "duration_seconds": round(duration, 3),
                    "ffprobe": probe,
                }
            )
            sidecar = narration_dir / f"{cue_id}.edge-tts.json"
            write_json(
                sidecar,
                {
                    "format_version": 1,
                    "kind": "vivhite_promo_full_master_edge_tts_cue",
                    "generated_utc": utc_now(),
                    "cue_id": cue_id,
                    "chapter_id": row["chapter_id"],
                    "shot_id": row["shot_id"],
                    "provider": {"id": identity.provider_id, "tool_version": identity.tool_version},
                    "request": {
                        "text": record["text"],
                        "voice": record["voice"],
                        "rate": record["rate"],
                        "pitch": record["pitch"],
                        "volume": record["volume"],
                        "audio_format": record["audio_format"],
                        "cache_salt": record["cache_salt"],
                    },
                    "timeline": {
                        "anchor_seconds": row["anchor_seconds"],
                        "subtitle_window_seconds": row["subtitle_window_seconds"],
                    },
                    "fingerprint": entry.fingerprint,
                    "audio": record["artifact"],
                    "cache_entry": record["cache_entry"],
                    "ffprobe": probe,
                    "status": record["status"],
                },
            )
            record["metadata_artifact"] = file_record(sidecar, run_root)
            row.update(
                {
                    "duration_seconds": duration,
                    "audio": record["artifact"],
                    "metadata": record["metadata_artifact"],
                }
            )
        except Exception as error:  # preserve request and failure, continue cues
            record.update(
                {
                    "status": "failed",
                    "error": {"type": type(error).__name__, "message": str(error)},
                }
            )
            sidecar = narration_dir / f"{cue_id}.edge-tts.json"
            write_json(
                sidecar,
                {
                    "format_version": 1,
                    "kind": "vivhite_promo_full_master_edge_tts_cue",
                    "generated_utc": utc_now(),
                    "cue_id": cue_id,
                    "chapter_id": row["chapter_id"],
                    "shot_id": row["shot_id"],
                    "provider": {"id": identity.provider_id, "tool_version": identity.tool_version},
                    "request": {
                        "text": record["text"],
                        "voice": record["voice"],
                        "rate": record["rate"],
                        "pitch": record["pitch"],
                        "volume": record["volume"],
                        "audio_format": record["audio_format"],
                        "cache_salt": record["cache_salt"],
                    },
                    "status": "failed",
                    "error": record["error"],
                },
            )
            record["metadata_artifact"] = file_record(sidecar, run_root)
            failures.append(record)
        requests.append(record)

    # Subtitle events are still emitted for successful cues only.  A failed
    # cue remains in the manifest and cannot be mistaken for a silent success.
    successful_rows = [row for row in rows if row.get("duration_seconds")]
    for index, row in enumerate(successful_rows):
        row["next_anchor_seconds"] = (
            successful_rows[index + 1]["anchor_seconds"]
            if index + 1 < len(successful_rows)
            else None
        )
    if successful_rows:
        subtitle_manifest = _write_subtitles(run_root, successful_rows)
    else:
        subtitle_manifest = {"total_timeline_seconds": 0.0, "warnings": [], "files": {}}

    write_json(
        run_root / "full-master-timeline.json",
        {
            "schema": "vivhite-promo-full-master-timeline-v1",
            "target_duration_seconds": script["target_duration_seconds"],
            "cues": [
                {
                    "cue_id": row["cue_id"],
                    "chapter_id": row["chapter_id"],
                    "shot_id": row["shot_id"],
                    "anchor_seconds": row["anchor_seconds"],
                    "duration_seconds": row.get("duration_seconds"),
                    "audio": row.get("audio"),
                    "status": "generated" if row.get("duration_seconds") else "failed",
                }
                for row in rows
            ],
            "subtitle_manifest": subtitle_manifest,
        },
    )

    script_root = script_path.parent
    manifest = {
        "schema": "vivhite-promo-full-master-narration-run-v1",
        "created_at": utc_now(),
        "run_id": run_root.name,
        "script": file_record(script_path, script_root),
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
            "ffprobe": str(ffprobe),
            "ffprobe_sha256": sha256_file(ffprobe),
        },
        "requests": requests,
        "subtitle_manifest": subtitle_manifest,
        "summary": {
            "requested": len(requests),
            "generated": sum(1 for item in requests if item["status"] in {"generated", "cache-hit"}),
            "failed": len(failures),
            "total_audio_seconds": round(sum(float(row.get("duration_seconds") or 0.0) for row in rows), 3),
            "target_timeline_seconds": script["target_duration_seconds"],
            "bgm": "disabled",
        },
    }
    write_json(run_root / "logs" / "full-master-narration-manifest.json", manifest)
    write_json(
        run_root / "logs" / "full-master-narration-failures.json",
        {"schema": "vivhite-promo-full-master-tts-failures-v1", "failures": failures},
    )
    (run_root / "audio-policy.json").write_text(
        json.dumps(
            {
                "include_bgm": False,
                "narration_voice": VOICE,
                "game_audio": "provided by capture run",
                "sfx": "provided by capture run",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {"run": str(run_root), "manifest": str(run_root / "logs" / "full-master-narration-manifest.json"), **manifest["summary"]},
            ensure_ascii=False,
        )
    )
    return 0 if not failures else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--run", type=Path, required=True, help="new, empty run directory")
    parser.add_argument("--ffprobe", type=Path, default=DEFAULT_FFPROBE)
    args = parser.parse_args()
    try:
        return generate(args.script, args.run, args.ffprobe)
    except Exception as error:
        print(f"full-master narration generation failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
