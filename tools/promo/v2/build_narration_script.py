"""Materialize the director-v2 per-cue narration script from storyboard.json.

The storyboard remains the authoring source of truth.  This adapter selects
only cues with non-empty ``narration_zh``; title cards, end cards and
``game_audio_only`` cues intentionally remain silent.  Every selected cue is
kept as its own TTS request and its own bilingual subtitle event.

The output deliberately uses the mature ``vivhite_promo_full_master_script``
producer contract so the existing hash-bound Edge TTS pipeline can be reused
without copying its network/provider implementation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_STORYBOARD = ROOT / "storyboard.json"
DEFAULT_OUTPUT = ROOT / "narration-script.json"
VOICE = "zh-CN-XiaoxiaoNeural"

# These facts must be proven by the capture/runtime binder before they may be
# printed.  Keep the pre-generated voice/subtitle batch useful without baking
# pending numbers into audio or text.
RUNTIME_PENDING_COPY: dict[str, dict[str, Any]] = {
    "C008B": {
        "subtitle_zh": "独立角色白绮｜生命与金币以当前 HUD 为准｜孤高冠冕",
        "subtitle_en": "Vivhite | current HP and gold in the HUD | Solitary Crown",
        "deferred_fields": ["initial_hp", "initial_gold"],
    },
    "C038": {
        "narration_zh": "一整套专属卡牌，不是一条固定答案，而是一组可以被重新组合的语言。",
        "subtitle_zh": "专属卡牌构成完整牌库",
        "subtitle_en": "A complete library of signature cards",
        "deferred_fields": ["signature_card_count"],
    },
    "C048": {
        "subtitle_zh": "专属卡牌｜三条核心路线｜当前版本与 Workshop 状态",
        "subtitle_en": "Signature cards | three core routes | current version and Workshop status",
        "deferred_fields": [
            "signature_card_count",
            "runtime_version",
            "workshop_status",
        ],
    },
}


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _timeline(value: object, label: str) -> tuple[float, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    start = _number(value.get("start_seconds"), f"{label}.start_seconds")
    end = _number(value.get("end_seconds"), f"{label}.end_seconds")
    if start < 0 or end <= start:
        raise ValueError(f"{label} must have a positive ordered span")
    return start, end


def build(storyboard_path: Path) -> dict[str, Any]:
    storyboard_path = storyboard_path.expanduser().resolve()
    payload = json.loads(storyboard_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("storyboard root must be an object")
    if payload.get("kind") != "vivhite_promo_storyboard_v2":
        raise ValueError("storyboard must declare vivhite_promo_storyboard_v2")
    if payload.get("revision_id") != "director-v2":
        raise ValueError("storyboard revision must be director-v2")
    if payload.get("project_id") != "vivhite-player-promo":
        raise ValueError("storyboard project_id is not the Vivhite promo")
    target = _number(payload.get("target_duration_seconds"), "target duration")
    if target != 540:
        raise ValueError("director-v2 narration timeline must remain 540 seconds")
    master = payload.get("master")
    if not isinstance(master, dict):
        raise ValueError("storyboard.master is missing")
    if master.get("narration_voice") != VOICE or master.get("bgm") is not False:
        raise ValueError("director-v2 must remain pinned to Xiaoxiao and no BGM")
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("storyboard.shots must be a non-empty array")

    chapters: list[dict[str, Any]] = []
    selected_ids: list[str] = []
    intentionally_silent_ids: list[str] = []
    previous_anchor = -1.0
    for shot in shots:
        if not isinstance(shot, dict):
            raise ValueError("storyboard shot must be an object")
        shot_id = shot.get("shot_id")
        chapter_id = shot.get("chapter_id")
        if not isinstance(shot_id, str) or not isinstance(chapter_id, str):
            raise ValueError("shot_id and chapter_id must be strings")
        shot_start, shot_end = _timeline(shot.get("timeline"), f"shot {shot_id}")
        subshots = shot.get("subshots")
        if not isinstance(subshots, list) or not subshots:
            raise ValueError(f"shot {shot_id} has no subshots")

        authored: list[dict[str, Any]] = []
        for index, subshot in enumerate(subshots):
            if not isinstance(subshot, dict):
                raise ValueError(f"shot {shot_id} has a malformed subshot")
            subshot_id = subshot.get("subshot_id")
            cue = subshot.get("cue")
            if not isinstance(subshot_id, str) or not isinstance(cue, dict):
                raise ValueError(f"shot {shot_id} has a malformed cue")
            cue_id = cue.get("cue_id")
            kind = cue.get("kind")
            if not isinstance(cue_id, str) or not isinstance(kind, str):
                raise ValueError(f"subshot {subshot_id} needs cue_id and kind")
            narration = cue.get("narration_zh")
            if not isinstance(narration, str):
                raise ValueError(f"cue {cue_id} narration_zh must be a string")
            narration = narration.strip()
            if not narration:
                intentionally_silent_ids.append(cue_id)
                continue
            zh = cue.get("subtitle_zh")
            en = cue.get("subtitle_en")
            if not isinstance(zh, str) or not zh.strip():
                raise ValueError(f"cue {cue_id} needs a Chinese subtitle")
            if not isinstance(en, str) or not en.strip():
                raise ValueError(f"cue {cue_id} needs an English subtitle")
            pending_copy = RUNTIME_PENDING_COPY.get(cue_id, {})
            narration = str(pending_copy.get("narration_zh", narration)).strip()
            zh = str(pending_copy.get("subtitle_zh", zh)).strip()
            en = str(pending_copy.get("subtitle_en", en)).strip()
            visual_start, visual_end = _timeline(
                subshot.get("timeline"), f"subshot {subshot_id}"
            )

            audio_timeline = cue.get("audio_timeline")
            if audio_timeline is not None:
                anchor, audio_end = _timeline(
                    audio_timeline, f"cue {cue_id}.audio_timeline"
                )
                subtitle_window = audio_end - anchor
            else:
                anchor = visual_start
                subtitle_end = visual_end
                # A blank narration_continuation immediately following a cue
                # is editorial room reserved for the preceding spoken line.
                if index + 1 < len(subshots):
                    following = subshots[index + 1]
                    following_cue = following.get("cue") if isinstance(following, dict) else None
                    if (
                        isinstance(following_cue, dict)
                        and following_cue.get("kind") == "narration_continuation"
                        and not str(following_cue.get("narration_zh") or "").strip()
                    ):
                        _, subtitle_end = _timeline(
                            following.get("timeline"),
                            f"subshot {following.get('subshot_id')}",
                        )
                subtitle_window = subtitle_end - anchor

            if anchor < shot_start or anchor >= shot_end:
                raise ValueError(f"cue {cue_id} anchor lies outside shot {shot_id}")
            if subtitle_window <= 0 or anchor + subtitle_window > shot_end + 1e-6:
                raise ValueError(f"cue {cue_id} has an invalid subtitle window")
            if anchor < previous_anchor:
                raise ValueError("narration cue anchors must be monotonic")
            previous_anchor = anchor
            selected_ids.append(cue_id)
            authored.append(
                {
                    "cue_id": cue_id,
                    "subshot_id": subshot_id,
                    "anchor_seconds": anchor,
                    "subtitle_window_seconds": subtitle_window,
                    "narration_zh": narration,
                    "subtitle_zh": zh.strip(),
                    "subtitle_en": en.strip(),
                    # The first fixed monologue line is longer than its
                    # authored 4.8-second slot at the provider default rate.
                    # A modest per-cue rate keeps the exact wording and avoids
                    # speech collision with C007B.
                    **({"tts_rate": "+15%"} if cue_id == "C007A" else {}),
                    **(
                        {
                            "runtime_binding": {
                                "status": "pending",
                                "deferred_fields": pending_copy["deferred_fields"],
                                "must_not_bake_into_tts_or_subtitle": True,
                            }
                        }
                        if pending_copy
                        else {}
                    ),
                    "evidence": {
                        "mode": "runtime_observed_if_bound"
                        if subshot.get("provenance") == "runtime_observed"
                        else "editorial",
                        "provenance": subshot.get("provenance"),
                        "refs": list(subshot.get("evidence_refs") or []),
                    },
                }
            )
        if authored:
            chapters.append(
                {
                    "chapter_id": chapter_id,
                    "shot_id": shot_id,
                    "window": {
                        "start_seconds": shot_start,
                        "end_seconds": shot_end,
                    },
                    "cues": authored,
                }
            )

    if not selected_ids:
        raise ValueError("storyboard has no narrated cues")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("narrated cue IDs must be unique")
    all_ids = selected_ids + intentionally_silent_ids
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("all storyboard cue IDs must be unique")

    return {
        "schema_version": 1,
        "kind": "vivhite_promo_full_master_script",
        "project_id": "vivhite-player-promo",
        "revision_id": "director-v2",
        "title": "白绮：把生命写成魔法",
        "target_duration_seconds": target,
        "source_storyboard": storyboard_path.name,
        "audio_policy": {
            "voice": VOICE,
            "include_bgm": False,
            "game_audio": "duck ambience under narration; keep key SFX foregrounded",
        },
        "cue_policy": {
            "one_tts_request_per_narrated_cue": True,
            "one_bilingual_subtitle_event_per_narrated_cue": True,
            "runtime_numbers_must_not_be_hardcoded": True,
        },
        "selection": {
            "narrated_cue_count": len(selected_ids),
            "narrated_cue_ids": selected_ids,
            "intentionally_silent_cue_count": len(intentionally_silent_ids),
            "intentionally_silent_cue_ids": intentionally_silent_ids,
        },
        "chapters": chapters,
    }


def write_new(path: Path, value: dict[str, Any], *, replace: bool = False) -> None:
    path = path.expanduser().resolve()
    if path.exists() and not replace:
        raise FileExistsError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(partial, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", type=Path, default=DEFAULT_STORYBOARD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    try:
        result = build(args.storyboard)
        write_new(args.output, result, replace=args.replace)
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "narrated": result["selection"]["narrated_cue_count"],
                    "intentionally_silent": result["selection"]["intentionally_silent_cue_count"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as error:
        print(f"director-v2 narration script failed: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
