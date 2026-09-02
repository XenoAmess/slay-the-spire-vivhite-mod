"""Build a valid ten-segment full-master EDL from the long-form cue script.

The script's ``anchor_seconds`` values describe the output timeline.  This
helper converts them into per-segment cue offsets and takes the first source
timestamp as an explicit argument; it never guesses where a capture starts.
The resulting JSON is consumable by ``render_full_master.py``.  If a capture
has discontinuous clean spans, edit only the generated segment
``source_start_seconds`` values after reviewing the capture receipt, retaining
the cue/segment mapping unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


PROMO_ROOT = Path(__file__).resolve().parent
DEFAULT_SCRIPT = PROMO_ROOT / "full-master-script.json"


SHOT_ORDER = (
    ("S01-identity", 45.0),
    ("S02-loadout", 50.0),
    ("S03-cough", 60.0),
    ("S04-margin", 55.0),
    ("S05-drain", 65.0),
    ("S06-conservation-geometry", 60.0),
    ("S07-recursive-star-calculus", 60.0),
    ("S08-crimson-integral", 60.0),
    ("S09-unified-field", 75.0),
    ("S10-finale", 70.0),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def build(
    script_path: Path,
    source_start: float,
    *,
    narration_root: str = "run-20260902T-full-master-tts-a4/narration",
) -> dict[str, Any]:
    if not math.isfinite(float(source_start)) or float(source_start) < 0:
        raise ValueError("source_start must be finite and non-negative")
    payload = json.loads(script_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("kind") != "vivhite_promo_full_master_script":
        raise ValueError("script must be vivhite_promo_full_master_script")
    if payload.get("target_duration_seconds") != 600:
        raise ValueError("the canonical full-master EDL is exactly 600 seconds")
    chapters = payload.get("chapters")
    if not isinstance(chapters, list) or len(chapters) != len(SHOT_ORDER):
        raise ValueError("script must contain the canonical ten chapters")

    chapter_by_shot = {str(item.get("shot_id")): item for item in chapters if isinstance(item, dict)}
    if tuple(chapter_by_shot) != tuple(shot for shot, _duration in SHOT_ORDER):
        raise ValueError("script chapter order does not match canonical shot order")

    segments: list[dict[str, Any]] = []
    cues: list[dict[str, Any]] = []
    source_cursor = float(source_start)
    timeline_cursor = 0.0
    for index, (shot_id, duration) in enumerate(SHOT_ORDER, 1):
        chapter = chapter_by_shot[shot_id]
        segment_id = f"seg-{index:02d}"
        # Keep the canonical first/last provenance policy.  The source receipt
        # remains authoritative for whether a span is actually clean.
        provenance = "staged" if shot_id in {"S01-identity", "S10-finale"} else "natural"
        segments.append(
            {
                "segment_id": segment_id,
                "shot_id": shot_id,
                "source_start_seconds": round(source_cursor, 6),
                "duration_seconds": duration,
                "provenance": provenance,
            }
        )
        window = chapter.get("window")
        if not isinstance(window, dict):
            raise ValueError(f"chapter {shot_id} has no window")
        chapter_start = float(window.get("start_seconds"))
        chapter_end = float(window.get("end_seconds"))
        if abs(chapter_start - timeline_cursor) > 1e-6 or abs(
            (chapter_end - chapter_start) - duration
        ) > 1e-6:
            raise ValueError(
                f"chapter {shot_id} window must match canonical timeline "
                f"{timeline_cursor:g}..{timeline_cursor + duration:g}"
            )
        for cue in chapter.get("cues", []):
            if not isinstance(cue, dict):
                raise ValueError(f"chapter {shot_id} contains malformed cue")
            anchor = float(cue.get("anchor_seconds"))
            offset = anchor - chapter_start
            if offset < 0 or offset >= duration:
                raise ValueError(f"cue {cue.get('cue_id')} falls outside {shot_id}")
            subtitle_window = float(cue["subtitle_window_seconds"])
            if offset + subtitle_window > duration + 1e-6:
                raise ValueError(
                    f"cue {cue.get('cue_id')} subtitle window exceeds {shot_id}"
                )
            cues.append(
                {
                    "cue_id": str(cue["cue_id"]),
                    "segment_id": segment_id,
                    "offset_seconds": round(offset, 6),
                    "file": f"{cue['cue_id']}.mp3",
                    "subtitle_zh": str(cue["subtitle_zh"]),
                    "subtitle_en": str(cue["subtitle_en"]),
                    "subtitle_duration_seconds": subtitle_window,
                }
            )
        source_cursor += duration
        timeline_cursor += duration

    if not isinstance(narration_root, str) or not narration_root.strip():
        raise ValueError("narration_root must be non-empty text")
    return {
        "schema_version": 1,
        "kind": "vivhite_promo_full_master_edl",
        "source_label": "full-master-script-derived; verify source starts against capture receipt",
        "target_duration_seconds": 600,
        "segments": segments,
        "cues": cues,
        "authoring": {
            "script_path": script_path.as_posix(),
            "script_sha256": sha256_file(script_path),
            "narration_root": narration_root.replace("\\", "/"),
            "cue_count": len(cues),
            "source_start_argument_seconds": source_start,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--source-start", type=float, required=True)
    parser.add_argument(
        "--narration-root",
        default="run-20260902T-full-master-tts-a4/narration",
        help="metadata path passed to the renderer's --narration-root",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.source_start) or args.source_start < 0:
        raise SystemExit("--source-start must be finite and non-negative")
    result = build(
        args.script.expanduser().resolve(),
        args.source_start,
        narration_root=args.narration_root,
    )
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing EDL: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(output), "segments": len(result["segments"]), "cues": len(result["cues"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
