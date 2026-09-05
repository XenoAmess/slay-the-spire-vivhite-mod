"""Offline storyboard validation and multi-take EDL authoring for promo v2.

This module is deliberately project-local.  It validates the director-owned
v2 storyboard mapping and turns a separately recorded, hash-*declared* take
manifest into an explicit edit decision list.  This layer validates manifest
claims only: a production binder must still read the actual bytes, verify the
declared sizes/hashes, and apply ``action_evidence_v2`` before rendering.  The
module never starts the game, OBS, TTS, or a media encoder.

The ten canonical shot IDs remain the xAR-facing ABI.  The actual edit is
described by ordered subshots, which may reference any of nineteen required
independent capture takes plus the one optional split take (T15), or a
project-owned ``xar.TitleCardSpec`` generated card.
"""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 2
STORYBOARD_KIND = "vivhite_promo_storyboard_v2"
TAKE_MANIFEST_KIND = "vivhite_promo_take_manifest_v2"
EDL_KIND = "vivhite_promo_multi_take_edl_v2"
TARGET_DURATION_SECONDS = 540.0
WIDTH = 1920
HEIGHT = 1080
FPS = 60
VOICE = "zh-CN-XiaoxiaoNeural"
TITLE_CARD_FACTORY = "vivhite_promo.title_cards_v2.create_title_card_spec_v2"
TARGET_FRAMES = 32_400
DIRECTOR_SECTION_BOUNDARIES = (
    0.0,
    18.0,
    28.0,
    58.0,
    78.0,
    120.0,
    168.0,
    188.0,
    232.0,
    252.0,
    306.0,
    330.0,
    382.0,
    448.0,
    496.0,
    540.0,
)
DIRECTOR_SECTION_IDS = (
    "D01-cold-open",
    "D02-main-title",
    "D03-character-select",
    "D04-loadout",
    "D05-cough",
    "D06-margin",
    "D07-reward-map",
    "D08-dimension-fatal",
    "D09-campfire",
    "D10-drain",
    "D11-shop",
    "D12-recursive",
    "D13-crimson-unified",
    "D14-cards-builds",
    "D15-finale",
)

CANONICAL_SHOT_IDS = (
    "S01-identity",
    "S02-loadout",
    "S03-cough",
    "S04-margin",
    "S05-drain",
    "S06-conservation-geometry",
    "S07-recursive-star-calculus",
    "S08-crimson-integral",
    "S09-unified-field",
    "S10-finale",
)

REQUIRED_TAKE_IDS = frozenset(
    f"T{index:02d}" for index in (*range(1, 15), *range(16, 21))
)
CONDITIONAL_TAKE_ID = "T15"
ALL_TAKE_IDS = REQUIRED_TAKE_IDS | {CONDITIONAL_TAKE_ID}

CAPTURE_ASSET_TYPES = frozenset(
    {"mechanism_action", "gameplay", "ui_gameplay", "montage"}
)
TITLE_CARD_LIMITS = {
    "title_card": 3.0,
    "tower_title_card": 1.8,
    "end_card": 7.0,
}
ASSET_TYPES = CAPTURE_ASSET_TYPES | frozenset(TITLE_CARD_LIMITS)
MECHANISM_EVIDENCE_ROLES = frozenset(
    {"state.before", "action.receipt", "state.after"}
)
FALLBACK_CONTINUATION_EVIDENCE_ROLES = frozenset(
    {"action.sequence", "state.after", "frame.end"}
)
FALLBACK_CONTINUATION_FORBIDDEN_ROLES = frozenset(
    {"state.before", "action.receipt"}
)
MONTAGE_LINEAGE_EVIDENCE_ROLES = frozenset(
    {"runtime.manifest", "frame.begin", "frame.end", "action.sequence"}
)
MONTAGE_VISUAL_EVIDENCE_ROLES = frozenset({"frame.begin", "frame.end"})
PROVENANCE_VALUES = frozenset({"runtime_observed", "editorial_derived"})
SHORT_VARIANTS = {"hero-60": 60.0, "cut-30": 30.0, "cut-15": 15.0}

_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_PORTABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_A4_TOKEN = re.compile(r"(?:^|[\\/_.-])a4(?:$|[\\/_.-])", re.IGNORECASE)
_EPSILON = 1e-6


class DirectorV2Error(ValueError):
    """A v2 storyboard, take manifest, or EDL binding is unsafe."""


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DirectorV2Error(f"{context} must be an object")
    return value


def _list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise DirectorV2Error(f"{context} must be an array")
    return value


def _text(value: Any, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise DirectorV2Error(f"{context} must be NUL-free text")
    result = value.strip()
    if not allow_empty and not result:
        raise DirectorV2Error(f"{context} must be non-empty text")
    return result


def _identifier(value: Any, context: str) -> str:
    result = _text(value, context)
    if _PORTABLE_ID.fullmatch(result) is None:
        raise DirectorV2Error(f"{context} must be a portable identifier")
    return result


def _number(
    value: Any,
    context: str,
    *,
    positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DirectorV2Error(f"{context} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise DirectorV2Error(f"{context} must be finite and {qualifier}")
    return result


def _boolean(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise DirectorV2Error(f"{context} must be boolean")
    return value


def _relative_path(value: Any, context: str) -> str:
    raw = _text(value, context)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
        raise DirectorV2Error(f"{context} must not contain control characters")
    if "\\" in raw:
        raise DirectorV2Error(f"{context} must use portable '/' separators")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or _DRIVE.match(raw)
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw
    ):
        raise DirectorV2Error(f"{context} must be a normalized relative path")
    _reject_a4_source(raw, context)
    return raw


def _reject_a4_source(value: str, context: str) -> None:
    normalized = value.replace("\\", "/").casefold()
    if (
        _A4_TOKEN.search(normalized)
        or "full-master-tts-a4" in normalized
        or "delivery-a4" in normalized
    ):
        raise DirectorV2Error(
            f"{context} references legacy a4 material; a4 is reference-only and "
            "cannot be a v2 source"
        )


def _read_document(source: Mapping[str, Any] | str | Path, label: str) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return copy.deepcopy(dict(source))
    path = Path(source).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise DirectorV2Error(f"could not read {label} {path}: {exc}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DirectorV2Error(f"invalid {label} JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DirectorV2Error(f"{label} root must be an object")
    return payload


def _timeline(value: Any, context: str) -> tuple[float, float, float]:
    row = _mapping(value, context)
    start = _number(row.get("start_seconds"), f"{context}.start_seconds")
    end = _number(row.get("end_seconds"), f"{context}.end_seconds")
    duration = _number(
        row.get("duration_seconds"), f"{context}.duration_seconds", positive=True
    )
    if end <= start:
        raise DirectorV2Error(f"{context}.end_seconds must exceed start_seconds")
    if not math.isclose(end - start, duration, rel_tol=0.0, abs_tol=_EPSILON):
        raise DirectorV2Error(
            f"{context}.duration_seconds must equal end_seconds - start_seconds"
        )
    for label, seconds in (("start_seconds", start), ("end_seconds", end), ("duration_seconds", duration)):
        frames = seconds * FPS
        if not math.isclose(frames, round(frames), rel_tol=0.0, abs_tol=_EPSILON):
            raise DirectorV2Error(
                f"{context}.{label} must land on an integer frame at {FPS} FPS"
            )
    return start, end, duration


def _validate_contiguous(
    rows: Iterable[tuple[str, float, float]],
    *,
    context: str,
    target: float,
) -> None:
    ordered = sorted(rows, key=lambda item: (item[1], item[2], item[0]))
    if not ordered:
        raise DirectorV2Error(f"{context} must not be empty")
    cursor = 0.0
    for item_id, start, end in ordered:
        if not math.isclose(start, cursor, rel_tol=0.0, abs_tol=_EPSILON):
            relation = "gap" if start > cursor else "overlap"
            raise DirectorV2Error(
                f"{context} has a {relation} before {item_id}: expected {cursor:g}, "
                f"got {start:g}"
            )
        cursor = end
    if not math.isclose(cursor, target, rel_tol=0.0, abs_tol=_EPSILON):
        raise DirectorV2Error(
            f"{context} must end at {target:g}s, got {cursor:g}s"
        )


def _take_source_is_pending(source: Mapping[str, Any], context: str) -> None:
    # Planning documents intentionally have no recorded artifact yet.  A
    # partially bound source is dangerous, so require the three source values
    # to be either all pending or all usable.
    artifact = source.get("artifact")
    start = source.get("in_seconds")
    end = source.get("out_seconds")
    values = (artifact, start, end)
    if all(value is None for value in values):
        return
    if any(value is None for value in values):
        raise DirectorV2Error(f"{context} must be wholly pending or wholly bound")
    _relative_path(artifact, f"{context}.artifact")
    begin = _number(start, f"{context}.in_seconds")
    finish = _number(end, f"{context}.out_seconds")
    if finish <= begin:
        raise DirectorV2Error(f"{context}.out_seconds must exceed in_seconds")


def _frame_value(row: Mapping[str, Any], field: str, context: str) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DirectorV2Error(f"{context}.{field} must be a non-negative integer")
    return value


def _validate_director_sections(root: Mapping[str, Any]) -> None:
    timebase = _mapping(root.get("timebase"), "storyboard.timebase")
    if timebase.get("frames_per_second") != FPS:
        raise DirectorV2Error("storyboard timebase must be 60 FPS")
    if timebase.get("target_frames") != TARGET_FRAMES:
        raise DirectorV2Error("storyboard timebase.target_frames must be 32400")

    sections = _list(root.get("director_sections"), "storyboard.director_sections")
    if len(sections) != len(DIRECTOR_SECTION_BOUNDARIES) - 1:
        raise DirectorV2Error("storyboard must contain exactly 15 director_sections")
    section_ids: set[str] = set()
    windows: list[tuple[str, float, float]] = []
    for index, value in enumerate(sections):
        context = f"storyboard.director_sections[{index}]"
        section = _mapping(value, context)
        section_id = _identifier(section.get("section_id"), f"{context}.section_id")
        if section_id in section_ids:
            raise DirectorV2Error(f"director_sections has duplicate {section_id!r}")
        section_ids.add(section_id)
        if section_id != DIRECTOR_SECTION_IDS[index]:
            raise DirectorV2Error(
                f"director section {index + 1} must be {DIRECTOR_SECTION_IDS[index]!r}"
            )
        start, end, duration = _timeline(section.get("timeline"), f"{context}.timeline")
        expected_start = DIRECTOR_SECTION_BOUNDARIES[index]
        expected_end = DIRECTOR_SECTION_BOUNDARIES[index + 1]
        if not math.isclose(start, expected_start, rel_tol=0.0, abs_tol=_EPSILON) or not math.isclose(
            end, expected_end, rel_tol=0.0, abs_tol=_EPSILON
        ):
            raise DirectorV2Error(
                f"director section {section_id} must use report boundary "
                f"{expected_start:g}..{expected_end:g}s"
            )
        expected_start_frame = round(start * FPS)
        expected_end_frame = round(end * FPS)
        if not math.isclose(start * FPS, expected_start_frame, rel_tol=0.0, abs_tol=_EPSILON) or not math.isclose(
            end * FPS, expected_end_frame, rel_tol=0.0, abs_tol=_EPSILON
        ):
            raise DirectorV2Error(
                f"director section {section_id} boundaries must land on integer frames"
            )
        timeline = _mapping(section["timeline"], f"{context}.timeline")
        start_frame = _frame_value(timeline, "start_frame", f"{context}.timeline")
        end_frame = _frame_value(timeline, "end_frame", f"{context}.timeline")
        duration_frames = _frame_value(
            timeline, "duration_frames", f"{context}.timeline"
        )
        if (
            start_frame != expected_start_frame
            or end_frame != expected_end_frame
            or duration_frames != expected_end_frame - expected_start_frame
            or not math.isclose(duration * FPS, duration_frames, rel_tol=0.0, abs_tol=_EPSILON)
        ):
            raise DirectorV2Error(
                f"director section {section_id} frame bounds do not match its 60 FPS timeline"
            )
        windows.append((section_id, start, end))
    _validate_contiguous(
        windows,
        context="storyboard director section timeline",
        target=TARGET_DURATION_SECONDS,
    )


def _validate_title_card(
    subshot: Mapping[str, Any],
    *,
    context: str,
    duration: float,
) -> Mapping[str, Any]:
    value = subshot.get("title_card")
    card = _mapping(value, f"{context}.title_card")
    if not card:
        raise DirectorV2Error(f"{context}.title_card must be a non-empty object")
    if card.get("factory") != TITLE_CARD_FACTORY:
        raise DirectorV2Error(
            f"{context}.title_card.factory must be {TITLE_CARD_FACTORY!r}"
        )
    chinese_title = _text(
        card.get("chinese_title"), f"{context}.title_card.chinese_title"
    )
    english_subtitle = _text(
        card.get("english_subtitle"), f"{context}.title_card.english_subtitle"
    )
    card_duration = _number(
        card.get("duration_seconds"),
        f"{context}.title_card.duration_seconds",
        positive=True,
    )
    if not math.isclose(card_duration, duration, rel_tol=0.0, abs_tol=_EPSILON):
        raise DirectorV2Error(
            f"{context}.title_card.duration_seconds must match the subshot timeline"
        )
    # This dependency-free layer validates the exact factory identifier and
    # its inputs.  The factory's xAR value-object compatibility has its own
    # fixed-version offline test; importing it here would make basic JSON
    # validation depend on the caller having xAR installed on ``sys.path``.
    return card


def _evidence_catalog(
    rows: Any,
    context: str,
    *,
    planning: bool,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, value in enumerate(_list(rows, context)):
        item_context = f"{context}[{index}]"
        row = _mapping(value, item_context)
        ref_id = _identifier(row.get("ref_id"), f"{item_context}.ref_id")
        role = _identifier(row.get("role"), f"{item_context}.role")
        if ref_id in result:
            raise DirectorV2Error(f"{context} contains duplicate ref_id {ref_id!r}")
        if "status" not in row:
            raise DirectorV2Error(f"{item_context}.status is required")
        status = _text(row.get("status"), f"{item_context}.status")
        path = row.get("path")
        if planning:
            if path is not None:
                _relative_path(path, f"{item_context}.path")
        else:
            if status not in {"verified", "bound"}:
                raise DirectorV2Error(
                    f"{item_context}.status must be verified or bound"
                )
            _relative_path(path, f"{item_context}.path")
            digest = _text(row.get("sha256"), f"{item_context}.sha256")
            if _SHA256.fullmatch(digest) is None:
                raise DirectorV2Error(f"{item_context}.sha256 must be a SHA-256 digest")
        result[ref_id] = role
    return result


def _variant_rows(value: Any) -> dict[str, Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return {
            str(key): _mapping(row, f"variants.{key}")
            for key, row in value.items()
        }
    rows: dict[str, Mapping[str, Any]] = {}
    for index, row_value in enumerate(_list(value, "variants")):
        row = _mapping(row_value, f"variants[{index}]")
        variant_id = _identifier(row.get("variant_id"), f"variants[{index}].variant_id")
        if variant_id in rows:
            raise DirectorV2Error(f"variants contains duplicate {variant_id!r}")
        rows[variant_id] = row
    return rows


def validate_storyboard_v2(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate one in-memory v2 storyboard and return it unchanged.

    A storyboard is a planning artifact, so null/pending source bindings are
    valid here.  :func:`build_multitake_edl` applies the stricter recorded-take
    gate before producing any EDL.
    """

    root = _mapping(payload, "storyboard")
    if root.get("schema_version") != SCHEMA_VERSION or root.get("kind") != STORYBOARD_KIND:
        raise DirectorV2Error(
            f"storyboard must declare {STORYBOARD_KIND} schema_version {SCHEMA_VERSION}"
        )

    top_duration = _number(
        root.get("target_duration_seconds"),
        "storyboard.target_duration_seconds",
        positive=True,
    )
    if not math.isclose(
        top_duration, TARGET_DURATION_SECONDS, rel_tol=0.0, abs_tol=_EPSILON
    ):
        raise DirectorV2Error("storyboard target duration must be exactly 540 seconds")
    _validate_director_sections(root)

    legacy_policy = _mapping(root.get("legacy_policy"), "storyboard.legacy_policy")
    for key, value in legacy_policy.items():
        folded = str(key).casefold()
        if "a4" in folded and "source" in folded and value is True:
            raise DirectorV2Error(
                f"storyboard.legacy_policy.{key} must not allow a4 as a source"
            )

    master = _mapping(root.get("master"), "storyboard.master")
    duration = _number(
        master.get("duration_seconds"), "storyboard.master.duration_seconds", positive=True
    )
    if not math.isclose(duration, TARGET_DURATION_SECONDS, rel_tol=0.0, abs_tol=_EPSILON):
        raise DirectorV2Error("v2 master duration must be exactly 540 seconds")
    video = _mapping(master.get("video"), "storyboard.master.video")
    if (
        video.get("width") != WIDTH
        or video.get("height") != HEIGHT
        or video.get("fps") != FPS
    ):
        raise DirectorV2Error("v2 master video must be 1920x1080 at 60 FPS")
    if master.get("narration_voice") != VOICE:
        raise DirectorV2Error(f"v2 narration voice must be {VOICE}")
    if master.get("bgm") is not False:
        raise DirectorV2Error("v2 master must declare bgm=false")

    canonical = tuple(_list(root.get("canonical_shot_ids"), "canonical_shot_ids"))
    if canonical != CANONICAL_SHOT_IDS:
        raise DirectorV2Error(
            "canonical_shot_ids must preserve the ten S01-S10 Vivhite ABI IDs"
        )

    take_policy = _mapping(root.get("take_policy"), "storyboard.take_policy")
    if take_policy.get("minimum_independent_takes") != 19:
        raise DirectorV2Error("take_policy.minimum_independent_takes must be 19")
    if take_policy.get("maximum_independent_takes") != 20:
        raise DirectorV2Error("take_policy.maximum_independent_takes must be 20")
    if take_policy.get("conditional_take_id") != CONDITIONAL_TAKE_ID:
        raise DirectorV2Error("T15 must be the sole conditional take")

    takes = _list(root.get("takes"), "storyboard.takes")
    if len(takes) not in {19, 20}:
        raise DirectorV2Error("storyboard must plan 19 or 20 independent capture takes")
    take_rows: dict[str, Mapping[str, Any]] = {}
    take_evidence: dict[str, dict[str, str]] = {}
    for index, value in enumerate(takes):
        context = f"storyboard.takes[{index}]"
        row = _mapping(value, context)
        take_id = _identifier(row.get("take_id"), f"{context}.take_id")
        if take_id in take_rows:
            raise DirectorV2Error(f"storyboard has duplicate take_id {take_id!r}")
        if take_id not in ALL_TAKE_IDS:
            raise DirectorV2Error(f"storyboard has unexpected take_id {take_id!r}")
        if _boolean(row.get("independent"), f"{context}.independent") is not True:
            raise DirectorV2Error(f"{context} must be an independent take")
        requirement = _text(row.get("requirement"), f"{context}.requirement")
        expected_requirement = "conditional" if take_id == CONDITIONAL_TAKE_ID else "required"
        if requirement != expected_requirement:
            raise DirectorV2Error(
                f"{take_id} requirement must be {expected_requirement!r}"
            )
        _text(row.get("asset_type"), f"{context}.asset_type")
        _text(row.get("capture_status"), f"{context}.capture_status")
        _boolean(row.get("staged_setup_allowed"), f"{context}.staged_setup_allowed")
        formal = _mapping(row.get("formal_display"), f"{context}.formal_display")
        for field in ("real_input", "game_resolution", "uncut_action"):
            _boolean(formal.get(field), f"{context}.formal_display.{field}")
        speed = _number(
            formal.get("playback_speed"),
            f"{context}.formal_display.playback_speed",
            positive=True,
        )
        if not math.isclose(speed, 1.0, rel_tol=0.0, abs_tol=_EPSILON):
            raise DirectorV2Error(f"{take_id} formal display must remain at 1x speed")
        source = _mapping(row.get("source"), f"{context}.source")
        _take_source_is_pending(source, f"{context}.source")
        evidence = _evidence_catalog(
            row.get("evidence_refs"), f"{context}.evidence_refs", planning=True
        )
        take_rows[take_id] = row
        take_evidence[take_id] = evidence

    storyboard_take_ids = set(take_rows)
    if not (
        storyboard_take_ids == set(REQUIRED_TAKE_IDS)
        or storyboard_take_ids == set(ALL_TAKE_IDS)
    ):
        raise DirectorV2Error(
            "storyboard take IDs must be T01-T20 with only conditional T15 optional"
        )

    shots = _list(root.get("shots"), "storyboard.shots")
    if len(shots) != len(CANONICAL_SHOT_IDS):
        raise DirectorV2Error("storyboard.shots must contain exactly ten canonical shots")
    shot_ids: set[str] = set()
    shot_windows: list[tuple[str, float, float]] = []
    subshot_windows: list[tuple[str, float, float]] = []
    subshot_ids: set[str] = set()
    cue_ids: set[str] = set()
    subshot_rows: dict[str, tuple[str, Mapping[str, Any]]] = {}
    cue_rows: dict[str, tuple[Mapping[str, Any], float, float]] = {}
    conditional_fallbacks: list[
        tuple[str, str, Mapping[str, Any]]
    ] = []
    montage_lineages: list[tuple[str, str, str]] = []

    for shot_index, value in enumerate(shots):
        shot_context = f"storyboard.shots[{shot_index}]"
        shot = _mapping(value, shot_context)
        shot_id = _identifier(shot.get("shot_id"), f"{shot_context}.shot_id")
        if shot_id in shot_ids:
            raise DirectorV2Error(f"storyboard has duplicate shot_id {shot_id!r}")
        shot_ids.add(shot_id)
        _text(shot.get("chapter_id"), f"{shot_context}.chapter_id")
        _text(shot.get("title"), f"{shot_context}.title")
        shot_start, shot_end, _shot_duration = _timeline(
            shot.get("timeline"), f"{shot_context}.timeline"
        )
        shot_windows.append((shot_id, shot_start, shot_end))

        subshots = _list(shot.get("subshots"), f"{shot_context}.subshots")
        if not subshots:
            raise DirectorV2Error(f"{shot_context}.subshots must not be empty")
        local_windows: list[tuple[str, float, float]] = []
        for sub_index, sub_value in enumerate(subshots):
            context = f"{shot_context}.subshots[{sub_index}]"
            subshot = _mapping(sub_value, context)
            subshot_id = _identifier(subshot.get("subshot_id"), f"{context}.subshot_id")
            if subshot_id in subshot_ids:
                raise DirectorV2Error(f"storyboard has duplicate subshot_id {subshot_id!r}")
            subshot_ids.add(subshot_id)
            subshot_rows[subshot_id] = (shot_id, subshot)
            asset_type = _text(subshot.get("asset_type"), f"{context}.asset_type")
            if asset_type not in ASSET_TYPES:
                raise DirectorV2Error(
                    f"{context}.asset_type must be one of {sorted(ASSET_TYPES)!r}"
                )
            start, end, sub_duration = _timeline(
                subshot.get("timeline"), f"{context}.timeline"
            )
            if start < shot_start - _EPSILON or end > shot_end + _EPSILON:
                raise DirectorV2Error(f"{subshot_id} timeline falls outside {shot_id}")
            local_windows.append((subshot_id, start, end))
            subshot_windows.append((subshot_id, start, end))

            take = _mapping(subshot.get("take"), f"{context}.take")
            take_id = take.get("take_id")
            independent = _boolean(take.get("independent"), f"{context}.take.independent")
            if asset_type in CAPTURE_ASSET_TYPES:
                take_id = _identifier(take_id, f"{context}.take.take_id")
                if take_id not in take_rows:
                    raise DirectorV2Error(f"{subshot_id} references unknown take {take_id!r}")
                if independent is not True:
                    raise DirectorV2Error(f"{subshot_id} must reference an independent take")
                fallback = take.get("fallback_take_id")
                fallback_id: str | None = None
                if fallback is not None:
                    fallback_id = _identifier(fallback, f"{context}.take.fallback_take_id")
                    if take_id != CONDITIONAL_TAKE_ID:
                        raise DirectorV2Error("only T15 may declare a fallback take")
                    if fallback_id not in REQUIRED_TAKE_IDS:
                        raise DirectorV2Error(f"{subshot_id} fallback take is unknown")
                    fallback_semantics = _mapping(
                        subshot.get("conditional_edit"),
                        f"{context}.conditional_edit",
                    )
                    if fallback_semantics.get("fallback_take_id") != fallback_id:
                        raise DirectorV2Error(
                            f"{subshot_id} conditional fallback take must match {fallback_id}"
                        )
                    if fallback_semantics.get("fallback_mode") != "result_event_continuation":
                        raise DirectorV2Error(
                            f"{subshot_id} fallback must be result_event_continuation"
                        )
                    predecessor_id = _identifier(
                        fallback_semantics.get("continuation_of_subshot_id"),
                        f"{context}.conditional_edit.continuation_of_subshot_id",
                    )
                    for flag in (
                        "must_be_source_contiguous",
                        "must_not_overlap_source",
                    ):
                        if fallback_semantics.get(flag) is not True:
                            raise DirectorV2Error(
                                f"{subshot_id} conditional fallback requires {flag}=true"
                            )
                    if fallback_semantics.get("fallback_has_formal_input") is not False:
                        raise DirectorV2Error(
                            f"{subshot_id} continuation fallback must not claim a formal input"
                        )
                    conditional_fallbacks.append(
                        (subshot_id, predecessor_id, fallback_semantics)
                    )
            else:
                if take_id is not None or independent is not False:
                    raise DirectorV2Error(
                        f"{subshot_id} is generated and must use take_id=null, independent=false"
                    )
                if take.get("generator") != "xar.TitleCardSpec":
                    raise DirectorV2Error(
                        f"{subshot_id} must use generator='xar.TitleCardSpec'"
                    )
                _validate_title_card(
                    subshot,
                    context=context,
                    duration=sub_duration,
                )

            source = _mapping(subshot.get("source"), f"{context}.source")
            if "status" not in source:
                raise DirectorV2Error(f"{context}.source.status is required")
            _text(source.get("status"), f"{context}.source.status")
            sub_in = source.get("in_seconds")
            sub_out = source.get("out_seconds")
            if (sub_in is None) != (sub_out is None):
                raise DirectorV2Error(
                    f"{subshot_id} source in/out must both be pending or both be bound"
                )
            if sub_in is not None:
                source_in = _number(sub_in, f"{context}.source.in_seconds")
                source_out = _number(sub_out, f"{context}.source.out_seconds")
                if source_out <= source_in:
                    raise DirectorV2Error(f"{subshot_id} source out must exceed in")
                if asset_type in CAPTURE_ASSET_TYPES and not math.isclose(
                    source_out - source_in,
                    sub_duration,
                    rel_tol=0.0,
                    abs_tol=_EPSILON,
                ):
                    raise DirectorV2Error(
                        f"{subshot_id} source duration must equal its 1x edit duration"
                    )

            cue = _mapping(subshot.get("cue"), f"{context}.cue")
            cue_id = _identifier(cue.get("cue_id"), f"{context}.cue.cue_id")
            if cue_id in cue_ids:
                raise DirectorV2Error(
                    f"cue {cue_id!r} is reused; every v2 cue must be independent"
                )
            cue_ids.add(cue_id)
            cue_rows[cue_id] = (cue, start, end)
            _text(cue.get("kind"), f"{context}.cue.kind")
            for field in ("narration_zh", "subtitle_zh", "subtitle_en"):
                if field not in cue:
                    raise DirectorV2Error(f"{context}.cue.{field} is required")
                _text(cue.get(field), f"{context}.cue.{field}", allow_empty=True)
            voice_asset = cue.get("voice_asset")
            if voice_asset is not None:
                _relative_path(voice_asset, f"{context}.cue.voice_asset")
            audio_timeline_value = cue.get("audio_timeline")
            j_cut_value = cue.get("j_cut")
            if audio_timeline_value is not None:
                audio_start, audio_end, _audio_duration = _timeline(
                    audio_timeline_value, f"{context}.cue.audio_timeline"
                )
                if j_cut_value is not None:
                    j_cut = _mapping(j_cut_value, f"{context}.cue.j_cut")
                    visual_cut = _number(
                        j_cut.get("visual_cut_seconds"),
                        f"{context}.cue.j_cut.visual_cut_seconds",
                    )
                    if not math.isclose(
                        visual_cut, start, rel_tol=0.0, abs_tol=_EPSILON
                    ):
                        raise DirectorV2Error(
                            f"{cue_id} J-cut visual boundary must equal its subshot start"
                        )
                    if not (audio_start < visual_cut < audio_end):
                        raise DirectorV2Error(
                            f"{cue_id} J-cut audio must start before and cross the visual boundary"
                        )
                    if (
                        j_cut.get("audio_starts_before_visual") is not True
                        or j_cut.get("audio_crosses_visual_cut") is not True
                    ):
                        raise DirectorV2Error(
                            f"{cue_id} J-cut declarations must be true"
                        )
            elif j_cut_value is not None:
                raise DirectorV2Error(f"{cue_id} J-cut requires an independent audio_timeline")

            provenance = _text(subshot.get("provenance"), f"{context}.provenance")
            if provenance not in PROVENANCE_VALUES:
                raise DirectorV2Error(f"{subshot_id} has invalid provenance {provenance!r}")
            expected_provenance = (
                "runtime_observed" if asset_type in CAPTURE_ASSET_TYPES else "editorial_derived"
            )
            if provenance != expected_provenance:
                raise DirectorV2Error(
                    f"{subshot_id} provenance must be {expected_provenance!r}"
                )

            evidence_refs = _list(subshot.get("evidence_refs"), f"{context}.evidence_refs")
            if not evidence_refs:
                raise DirectorV2Error(f"{subshot_id} must reference evidence")
            normalized_refs = [
                _identifier(ref, f"{context}.evidence_refs[{ref_index}]")
                for ref_index, ref in enumerate(evidence_refs)
            ]
            if len(normalized_refs) != len(set(normalized_refs)):
                raise DirectorV2Error(f"{subshot_id} has duplicate evidence refs")
            if asset_type in CAPTURE_ASSET_TYPES:
                assert isinstance(take_id, str)
                catalog = take_evidence[take_id]
                missing = sorted(set(normalized_refs) - set(catalog))
                if missing:
                    raise DirectorV2Error(
                        f"{subshot_id} references evidence absent from {take_id}: "
                        + ", ".join(missing)
                    )
                if fallback_id is not None:
                    fallback_values = _list(
                        subshot.get("fallback_evidence_refs"),
                        f"{context}.fallback_evidence_refs",
                    )
                    if not fallback_values:
                        raise DirectorV2Error(
                            f"{subshot_id} must declare fallback_evidence_refs for {fallback_id}"
                        )
                    fallback_refs = [
                        _identifier(
                            ref,
                            f"{context}.fallback_evidence_refs[{ref_index}]",
                        )
                        for ref_index, ref in enumerate(fallback_values)
                    ]
                    if len(fallback_refs) != len(set(fallback_refs)):
                        raise DirectorV2Error(
                            f"{subshot_id} has duplicate fallback evidence refs"
                        )
                    fallback_catalog = take_evidence[fallback_id]
                    missing_fallback = sorted(
                        set(fallback_refs) - set(fallback_catalog)
                    )
                    if missing_fallback:
                        raise DirectorV2Error(
                            f"{subshot_id} references fallback evidence absent from "
                            f"{fallback_id}: " + ", ".join(missing_fallback)
                        )
            if asset_type == "mechanism_action":
                assert isinstance(take_id, str)
                roles = {take_evidence[take_id][ref] for ref in normalized_refs}
                missing_roles = sorted(MECHANISM_EVIDENCE_ROLES - roles)
                if missing_roles:
                    raise DirectorV2Error(
                        f"mechanism action {subshot_id} lacks evidence roles: "
                        + ", ".join(missing_roles)
                    )
                if fallback_id is not None:
                    fallback_refs = list(subshot["fallback_evidence_refs"])
                    fallback_roles = {
                        take_evidence[fallback_id][ref] for ref in fallback_refs
                    }
                    missing_fallback_roles = sorted(
                        FALLBACK_CONTINUATION_EVIDENCE_ROLES - fallback_roles
                    )
                    if missing_fallback_roles:
                        raise DirectorV2Error(
                            f"continuation fallback for {subshot_id} lacks "
                            "evidence roles: " + ", ".join(missing_fallback_roles)
                        )
                    forbidden_fallback_roles = sorted(
                        FALLBACK_CONTINUATION_FORBIDDEN_ROLES & fallback_roles
                    )
                    if forbidden_fallback_roles:
                        raise DirectorV2Error(
                            f"continuation fallback for {subshot_id} must not claim "
                            "a second formal action via roles: "
                            + ", ".join(forbidden_fallback_roles)
                        )
                formal = _mapping(
                    take_rows[take_id].get("formal_display"),
                    f"take {take_id}.formal_display",
                )
                if not all(
                    formal.get(field) is True
                    for field in ("real_input", "game_resolution", "uncut_action")
                ):
                    raise DirectorV2Error(
                        f"mechanism action {subshot_id} must be real input, game-resolved, and uncut"
                    )

            lineage_value = subshot.get("montage_lineage")
            if lineage_value is not None:
                if asset_type != "montage":
                    raise DirectorV2Error(
                        f"{subshot_id}.montage_lineage is valid only for montage subshots"
                    )
                assert isinstance(take_id, str)
                lineage = _mapping(
                    lineage_value, f"{context}.montage_lineage"
                )
                source_subshot_id = _identifier(
                    lineage.get("source_subshot_id"),
                    f"{context}.montage_lineage.source_subshot_id",
                )
                if lineage.get("reuse_kind") != "editorial_excerpt":
                    raise DirectorV2Error(
                        f"{subshot_id}.montage_lineage.reuse_kind must be "
                        "'editorial_excerpt'"
                    )
                if lineage.get("formal_action_claimed") is not False:
                    raise DirectorV2Error(
                        f"{subshot_id} montage lineage must declare "
                        "formal_action_claimed=false"
                    )
                lineage_roles = {
                    take_evidence[take_id][ref] for ref in normalized_refs
                }
                forbidden_roles = sorted(
                    lineage_roles - MONTAGE_LINEAGE_EVIDENCE_ROLES
                )
                if forbidden_roles:
                    raise DirectorV2Error(
                        f"{subshot_id} montage lineage must use only lineage, visual, "
                        "or event evidence; forbidden roles: "
                        + ", ".join(forbidden_roles)
                    )
                if not (lineage_roles & MONTAGE_VISUAL_EVIDENCE_ROLES):
                    raise DirectorV2Error(
                        f"{subshot_id} montage lineage lacks frame visual evidence"
                    )
                if "action.sequence" not in lineage_roles:
                    raise DirectorV2Error(
                        f"{subshot_id} montage lineage lacks action.sequence event evidence"
                    )
                montage_lineages.append(
                    (subshot_id, take_id, source_subshot_id)
                )

            limit = TITLE_CARD_LIMITS.get(asset_type)
            if limit is not None and sub_duration > limit + _EPSILON:
                raise DirectorV2Error(
                    f"{asset_type} {subshot_id} exceeds its {limit:g}s duration limit"
                )

        _validate_contiguous(
            [
                (item_id, start - shot_start, end - shot_start)
                for item_id, start, end in local_windows
            ],
            context=f"subshots in {shot_id}",
            target=shot_end - shot_start,
        )

    for subshot_id, take_id, source_subshot_id in montage_lineages:
        source_entry = subshot_rows.get(source_subshot_id)
        if source_entry is None:
            raise DirectorV2Error(
                f"{subshot_id} montage lineage references unknown source subshot "
                f"{source_subshot_id}"
            )
        _source_shot_id, source_subshot = source_entry
        if source_subshot.get("asset_type") != "mechanism_action":
            raise DirectorV2Error(
                f"{subshot_id} montage lineage source {source_subshot_id} must be a "
                "mechanism_action"
            )
        source_take = _mapping(
            source_subshot.get("take"), f"subshot {source_subshot_id}.take"
        )
        if source_take.get("take_id") != take_id:
            raise DirectorV2Error(
                f"{subshot_id} montage lineage must reuse the same take as "
                f"{source_subshot_id}"
            )
        source_refs = _list(
            source_subshot.get("evidence_refs"),
            f"subshot {source_subshot_id}.evidence_refs",
        )
        source_roles = {take_evidence[take_id][str(ref)] for ref in source_refs}
        if "action.receipt" not in source_roles:
            raise DirectorV2Error(
                f"{subshot_id} montage lineage source {source_subshot_id} is not the "
                "formal action owner"
            )

    for subshot_id, predecessor_id, _semantics in conditional_fallbacks:
        if predecessor_id not in subshot_rows:
            raise DirectorV2Error(
                f"conditional fallback {subshot_id} references unknown predecessor "
                f"{predecessor_id}"
            )
        shot_id, subshot = subshot_rows[subshot_id]
        predecessor_shot_id, predecessor = subshot_rows[predecessor_id]
        if predecessor_shot_id != shot_id:
            raise DirectorV2Error(
                f"conditional fallback {subshot_id} and {predecessor_id} must share a shot"
            )
        predecessor_take = _mapping(
            predecessor.get("take"), f"subshot {predecessor_id}.take"
        )
        fallback_take = _mapping(subshot.get("take"), f"subshot {subshot_id}.take")
        if predecessor_take.get("take_id") != fallback_take.get("fallback_take_id"):
            raise DirectorV2Error(
                f"conditional fallback {subshot_id} must continue its fallback take"
            )
        _pre_start, predecessor_end, _pre_duration = _timeline(
            predecessor.get("timeline"), f"subshot {predecessor_id}.timeline"
        )
        subshot_start, _subshot_end, _subshot_duration = _timeline(
            subshot.get("timeline"), f"subshot {subshot_id}.timeline"
        )
        if not math.isclose(
            predecessor_end, subshot_start, rel_tol=0.0, abs_tol=_EPSILON
        ):
            raise DirectorV2Error(
                f"conditional fallback {subshot_id} must immediately follow {predecessor_id}"
            )

    if root.get("revision_id") == "director-v2":
        fixed_opening_cue_ids = ("C007A", "C007B", "C008A")
        missing_opening_cues = [
            cue_id for cue_id in fixed_opening_cue_ids if cue_id not in cue_rows
        ]
        if missing_opening_cues:
            raise DirectorV2Error(
                "director-v2 requires independent audio timelines for C007A, C007B, and C008A"
            )
        opening_audio_windows: list[tuple[float, float]] = []
        for cue_id in fixed_opening_cue_ids:
            opening_cue, _cue_visual_start, _cue_visual_end = cue_rows[cue_id]
            audio_start, audio_end, _audio_duration = _timeline(
                opening_cue.get("audio_timeline"),
                f"cue {cue_id}.audio_timeline",
            )
            opening_audio_windows.append((audio_start, audio_end))
        for previous_id, current_id, previous_window, current_window in zip(
            fixed_opening_cue_ids,
            fixed_opening_cue_ids[1:],
            opening_audio_windows,
            opening_audio_windows[1:],
        ):
            if previous_window[1] > current_window[0] + _EPSILON:
                raise DirectorV2Error(
                    f"opening narration {previous_id} must end before {current_id} starts"
                )
        cue, visual_start, _visual_end = cue_rows["C008A"]
        audio_start, audio_end = opening_audio_windows[-1]
        if not (audio_start < visual_start < audio_end):
            raise DirectorV2Error(
                "C008A audio must start before and cross the character-select visual cut"
            )

    if shot_ids != set(CANONICAL_SHOT_IDS):
        raise DirectorV2Error("storyboard.shots do not preserve the ten canonical IDs")
    _validate_contiguous(
        shot_windows, context="storyboard shot timeline", target=TARGET_DURATION_SECONDS
    )
    _validate_contiguous(
        subshot_windows,
        context="storyboard subshot timeline",
        target=TARGET_DURATION_SECONDS,
    )

    edit_policy = _mapping(root.get("edit_policy"), "storyboard.edit_policy")
    # The key is intentionally project-owned.  Reject only explicit attempts
    # to make the old signed master the source; variants carry the normative
    # per-deliverable declaration below.
    for key, value in edit_policy.items():
        if "signed_master" in str(key).casefold() and value is True:
            raise DirectorV2Error("v2 edits must not derive from a signed master")

    variants = _variant_rows(root.get("variants"))
    if set(variants) != set(SHORT_VARIANTS):
        raise DirectorV2Error("variants must define independent hero-60, cut-30, and cut-15 EDLs")
    for variant_id, expected_duration in SHORT_VARIANTS.items():
        row = variants[variant_id]
        if row.get("independent_edl") is not True:
            raise DirectorV2Error(f"variant {variant_id} must have independent_edl=true")
        if row.get("source") != "same_v2_take_batch":
            raise DirectorV2Error(f"variant {variant_id} must use the same v2 take batch")
        if row.get("from_signed_master") is not False:
            raise DirectorV2Error(f"variant {variant_id} must not derive from the signed master")
        if "duration_seconds" in row:
            observed = _number(
                row.get("duration_seconds"), f"variant {variant_id}.duration_seconds", positive=True
            )
            if not math.isclose(
                observed, expected_duration, rel_tol=0.0, abs_tol=_EPSILON
            ):
                raise DirectorV2Error(
                    f"variant {variant_id} duration must be {expected_duration:g}s"
                )
    return payload


def load_storyboard_v2(
    source: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Load and validate a storyboard mapping or UTF-8 JSON file."""

    payload = _read_document(source, "v2 storyboard")
    validate_storyboard_v2(payload)
    return payload


def _manifest_source(
    row: Mapping[str, Any], context: str
) -> tuple[str, float, str, int]:
    source_value = row.get("source", row.get("media"))
    source = _mapping(source_value, f"{context}.source")
    path_value = source.get("artifact", source.get("path"))
    path = _relative_path(path_value, f"{context}.source.artifact")
    duration = _number(
        source.get("duration_seconds"), f"{context}.source.duration_seconds", positive=True
    )
    digest = _text(source.get("sha256"), f"{context}.source.sha256").upper()
    if _SHA256.fullmatch(digest) is None:
        raise DirectorV2Error(f"{context}.source.sha256 must be a SHA-256 digest")
    byte_count = source.get("bytes")
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 1:
        raise DirectorV2Error(f"{context}.source.bytes must be an integer >= 1")
    return path, duration, digest, byte_count


def _span_rows(row: Mapping[str, Any], context: str) -> list[Any]:
    for key in ("subshots", "spans", "bindings"):
        if key in row:
            return _list(row[key], f"{context}.{key}")
    raise DirectorV2Error(f"{context} must bind subshots/spans")


def validate_take_manifest(
    storyboard: Mapping[str, Any] | str | Path,
    manifest: Mapping[str, Any] | str | Path,
) -> dict[str, Any]:
    """Validate and normalize an independent-take manifest declaration.

    The returned mapping is a private normalized view consumed by
    :func:`build_multitake_edl`; it is not an on-disk schema and deliberately
    opens no media or evidence files.  Passing this gate does *not* prove that
    those files exist or match the declared sizes/hashes.  A later production
    binder must verify the bytes and the action-evidence v2 documents.
    """

    board = load_storyboard_v2(storyboard)
    payload = _read_document(manifest, "v2 take manifest")
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("kind") != TAKE_MANIFEST_KIND:
        raise DirectorV2Error(
            f"take manifest must declare {TAKE_MANIFEST_KIND} schema_version {SCHEMA_VERSION}"
        )
    batch_id = _identifier(payload.get("batch_id"), "take_manifest.batch_id")
    _reject_a4_source(batch_id, "take_manifest.batch_id")
    if payload.get("source_strategy") != "independent_take_files":
        raise DirectorV2Error(
            "take_manifest.source_strategy must be independent_take_files"
        )
    if payload.get("from_legacy_a4") is not False:
        raise DirectorV2Error("take manifest must declare from_legacy_a4=false")

    rows = _list(payload.get("takes"), "take_manifest.takes")
    if len(rows) not in {19, 20}:
        raise DirectorV2Error("take manifest must bind 19 or 20 independent takes")
    takes: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    source_digests: set[str] = set()
    bindings: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(rows):
        context = f"take_manifest.takes[{index}]"
        row = _mapping(value, context)
        take_id = _identifier(row.get("take_id"), f"{context}.take_id")
        if take_id in takes:
            raise DirectorV2Error(f"take manifest has duplicate take {take_id!r}")
        if take_id not in ALL_TAKE_IDS:
            raise DirectorV2Error(f"take manifest has unexpected take {take_id!r}")
        if row.get("independent") is not True:
            raise DirectorV2Error(f"manifest take {take_id} must be independent")
        path, source_duration, digest, byte_count = _manifest_source(row, context)
        if path in paths:
            raise DirectorV2Error(
                f"independent takes must use distinct media files; duplicate {path!r}"
            )
        paths.add(path)
        if digest in source_digests:
            raise DirectorV2Error(
                "independent takes must declare distinct source SHA-256 digests; "
                f"duplicate {digest}"
            )
        source_digests.add(digest)
        evidence = _evidence_catalog(
            row.get("evidence_refs"), f"{context}.evidence_refs", planning=False
        )
        takes[take_id] = {
            "take_id": take_id,
            "path": path,
            "duration_seconds": source_duration,
            "sha256": digest,
            "bytes": byte_count,
            "evidence": evidence,
        }
        for span_index, span_value in enumerate(_span_rows(row, context)):
            span_context = f"{context}.spans[{span_index}]"
            span = _mapping(span_value, span_context)
            subshot_id = _identifier(
                span.get("subshot_id"), f"{span_context}.subshot_id"
            )
            if subshot_id in bindings:
                raise DirectorV2Error(
                    f"take manifest binds subshot {subshot_id!r} more than once"
                )
            start = _number(span.get("in_seconds"), f"{span_context}.in_seconds")
            end = _number(span.get("out_seconds"), f"{span_context}.out_seconds")
            if end <= start:
                raise DirectorV2Error(f"{span_context}.out_seconds must exceed in_seconds")
            for label, seconds in (("in_seconds", start), ("out_seconds", end)):
                frames = seconds * FPS
                if not math.isclose(
                    frames, round(frames), rel_tol=0.0, abs_tol=_EPSILON
                ):
                    raise DirectorV2Error(
                        f"{span_context}.{label} must land on an integer frame "
                        f"at {FPS} FPS"
                    )
            if end > source_duration + _EPSILON:
                raise DirectorV2Error(
                    f"{subshot_id} source window exceeds take {take_id} duration"
                )
            bindings[subshot_id] = {
                "take_id": take_id,
                "in_seconds": start,
                "out_seconds": end,
            }

    manifest_take_ids = set(takes)
    if not (
        manifest_take_ids == set(REQUIRED_TAKE_IDS)
        or manifest_take_ids == set(ALL_TAKE_IDS)
    ):
        raise DirectorV2Error(
            "manifest take IDs must be all required T01-T20 takes with only T15 optional"
        )

    capture_subshots: dict[str, Mapping[str, Any]] = {}
    for shot in board["shots"]:
        for subshot in shot["subshots"]:
            if subshot["asset_type"] in CAPTURE_ASSET_TYPES:
                capture_subshots[str(subshot["subshot_id"])] = subshot
    unknown_bindings = sorted(set(bindings) - set(capture_subshots))
    if unknown_bindings:
        raise DirectorV2Error(
            "take manifest binds unknown or generated subshots: "
            + ", ".join(unknown_bindings)
        )
    missing_bindings = sorted(set(capture_subshots) - set(bindings))
    if missing_bindings:
        raise DirectorV2Error(
            "take manifest lacks capture subshot bindings: " + ", ".join(missing_bindings)
        )

    for subshot_id, subshot in capture_subshots.items():
        take_spec = _mapping(subshot["take"], f"subshot {subshot_id}.take")
        primary = str(take_spec["take_id"])
        fallback = take_spec.get("fallback_take_id")
        fallback_used = primary not in takes
        allowed = {primary}
        if fallback is not None and fallback_used:
            allowed.add(str(fallback))
        binding = bindings[subshot_id]
        take_id = str(binding["take_id"])
        if take_id not in allowed:
            raise DirectorV2Error(
                f"subshot {subshot_id} is bound to {take_id}, expected {primary}"
                + (f" or fallback {fallback}" if fallback is not None else "")
            )
        if primary == CONDITIONAL_TAKE_ID and primary not in takes and fallback is None:
            raise DirectorV2Error(
                f"conditional subshot {subshot_id} needs a fallback when T15 is omitted"
            )
        if fallback_used:
            evidence_refs_value = subshot.get("fallback_evidence_refs")
            if not isinstance(evidence_refs_value, list) or not evidence_refs_value:
                raise DirectorV2Error(
                    f"conditional subshot {subshot_id} needs fallback_evidence_refs "
                    f"when {primary} is omitted"
                )
            evidence_refs = list(evidence_refs_value)
            fallback_semantics = _mapping(
                subshot.get("conditional_edit"),
                f"conditional subshot {subshot_id}.conditional_edit",
            )
        else:
            evidence_refs = list(subshot["evidence_refs"])
            fallback_semantics = None
        duration = float(subshot["timeline"]["duration_seconds"])
        source_duration = float(binding["out_seconds"]) - float(binding["in_seconds"])
        if not math.isclose(source_duration, duration, rel_tol=0.0, abs_tol=_EPSILON):
            raise DirectorV2Error(
                f"subshot {subshot_id} source window is {source_duration:g}s, "
                f"not its 1x timeline duration {duration:g}s"
            )
        missing_evidence = sorted(set(evidence_refs) - set(takes[take_id]["evidence"]))
        if missing_evidence:
            raise DirectorV2Error(
                f"manifest take {take_id} lacks bound evidence for {subshot_id}: "
                + ", ".join(missing_evidence)
            )
        if subshot["asset_type"] == "mechanism_action":
            roles = {takes[take_id]["evidence"][ref] for ref in evidence_refs}
            if fallback_used:
                missing_roles = sorted(
                    FALLBACK_CONTINUATION_EVIDENCE_ROLES - roles
                )
                forbidden_roles = sorted(
                    FALLBACK_CONTINUATION_FORBIDDEN_ROLES & roles
                )
                if missing_roles or forbidden_roles:
                    details = []
                    if missing_roles:
                        details.append("missing " + ", ".join(missing_roles))
                    if forbidden_roles:
                        details.append(
                            "forbidden formal-action roles "
                            + ", ".join(forbidden_roles)
                        )
                    raise DirectorV2Error(
                        f"manifest continuation fallback for {subshot_id} is invalid: "
                        + "; ".join(details)
                    )
            else:
                missing_roles = sorted(MECHANISM_EVIDENCE_ROLES - roles)
                if missing_roles:
                    raise DirectorV2Error(
                        f"manifest binding for mechanism action {subshot_id} lacks roles: "
                        + ", ".join(missing_roles)
                    )
        binding["evidence_refs"] = evidence_refs
        binding["fallback_used"] = fallback_used
        binding["requested_take_id"] = primary
        binding["resolved_semantics"] = (
            str(fallback_semantics["fallback_mode"])
            if fallback_semantics is not None
            else "formal_action"
        )
        if fallback_semantics is not None:
            binding["continuation_of_subshot_id"] = str(
                fallback_semantics["continuation_of_subshot_id"]
            )

    for subshot_id, binding in bindings.items():
        if binding.get("resolved_semantics") != "result_event_continuation":
            continue
        predecessor_id = str(binding["continuation_of_subshot_id"])
        predecessor = bindings.get(predecessor_id)
        if predecessor is None:
            raise DirectorV2Error(
                f"continuation fallback {subshot_id} lacks bound predecessor "
                f"{predecessor_id}"
            )
        if predecessor["take_id"] != binding["take_id"]:
            raise DirectorV2Error(
                f"continuation fallback {subshot_id} and {predecessor_id} must use "
                "the same fallback take"
            )
        predecessor_out = float(predecessor["out_seconds"])
        continuation_in = float(binding["in_seconds"])
        if not math.isclose(
            predecessor_out, continuation_in, rel_tol=0.0, abs_tol=_EPSILON
        ):
            relation = "overlaps" if continuation_in < predecessor_out else "has a gap after"
            raise DirectorV2Error(
                f"continuation fallback {subshot_id} {relation} {predecessor_id}; "
                "source spans must be contiguous and non-overlapping"
            )

    return {
        "storyboard": board,
        "manifest": payload,
        "batch_id": batch_id,
        "takes": takes,
        "bindings": bindings,
    }


def build_multitake_edl(
    storyboard: Mapping[str, Any] | str | Path,
    take_manifest: Mapping[str, Any] | str | Path,
    *,
    edit_id: str = "master-540",
) -> dict[str, Any]:
    """Build a deterministic draft EDL from validated manifest declarations.

    The result is explicitly marked byte-unverified.  It must not enter a
    production renderer until another gate verifies every declared artifact
    and validates the referenced action-evidence v2 bundles.
    """

    normalized = validate_take_manifest(storyboard, take_manifest)
    board = normalized["storyboard"]
    takes = normalized["takes"]
    bindings = normalized["bindings"]
    selected_edit_id = _identifier(edit_id, "edit_id")

    flattened: list[tuple[float, Mapping[str, Any], Mapping[str, Any]]] = []
    for shot in board["shots"]:
        for subshot in shot["subshots"]:
            flattened.append((float(subshot["timeline"]["start_seconds"]), shot, subshot))
    flattened.sort(key=lambda item: item[0])

    segments: list[dict[str, Any]] = []
    cues: list[dict[str, Any]] = []
    for index, (_start, shot, subshot) in enumerate(flattened, 1):
        subshot_id = str(subshot["subshot_id"])
        asset_type = str(subshot["asset_type"])
        timeline = subshot["timeline"]
        segment_id = f"seg-{index:03d}-{subshot_id}"
        cue = subshot["cue"]
        if asset_type in CAPTURE_ASSET_TYPES:
            binding = bindings[subshot_id]
            take = takes[str(binding["take_id"])]
            source: dict[str, Any] = {
                "kind": "video_take",
                "take_id": take["take_id"],
                "path": take["path"],
                "sha256": take["sha256"],
                "bytes": take["bytes"],
                "in_seconds": binding["in_seconds"],
                "out_seconds": binding["out_seconds"],
                "fallback_used": binding["fallback_used"],
                "resolved_semantics": binding["resolved_semantics"],
                "verification": "manifest_declaration_only",
            }
            if binding["fallback_used"]:
                source["requested_take_id"] = binding["requested_take_id"]
            selected_evidence_refs = list(binding["evidence_refs"])
        else:
            source = {
                "kind": "generated_title_card",
                "generator": "xar.TitleCardSpec",
                "spec": copy.deepcopy(subshot["title_card"]),
            }
            selected_evidence_refs = list(subshot["evidence_refs"])
        segment = {
                "segment_id": segment_id,
                "shot_id": shot["shot_id"],
                "subshot_id": subshot_id,
                "asset_type": asset_type,
                "timeline": copy.deepcopy(timeline),
                "duration_seconds": float(timeline["duration_seconds"]),
                "source": source,
                "provenance": subshot["provenance"],
                "evidence_refs": selected_evidence_refs,
                "cue_id": cue["cue_id"],
            }
        if asset_type in CAPTURE_ASSET_TYPES:
            segment["formal_action_claimed"] = (
                binding["resolved_semantics"] == "formal_action"
            )
            if binding["resolved_semantics"] == "result_event_continuation":
                segment["continuation_of_subshot_id"] = binding[
                    "continuation_of_subshot_id"
                ]
        segments.append(segment)
        cue_row = {
                "cue_id": cue["cue_id"],
                "segment_id": segment_id,
                "kind": cue["kind"],
                "timeline_start_seconds": float(timeline["start_seconds"]),
                "narration_zh": cue["narration_zh"],
                "subtitle_zh": cue["subtitle_zh"],
                "subtitle_en": cue["subtitle_en"],
                "voice_asset": cue["voice_asset"],
            }
        if "audio_timeline" in cue:
            cue_row["audio_timeline"] = copy.deepcopy(cue["audio_timeline"])
        if "j_cut" in cue:
            cue_row["j_cut"] = copy.deepcopy(cue["j_cut"])
        cues.append(cue_row)

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": EDL_KIND,
        "edit_id": selected_edit_id,
        "source_strategy": "independent_take_manifest",
        "take_batch_id": normalized["batch_id"],
        "from_signed_master": False,
        "target_duration_seconds": TARGET_DURATION_SECONDS,
        "canvas": {"width": WIDTH, "height": HEIGHT, "fps": FPS},
        "audio": {
            "bgm": False,
            "narration_voice": VOICE,
            "sample_rate_hz": 48_000,
            "channels": 2,
        },
        "canonical_shot_ids": list(CANONICAL_SHOT_IDS),
        "segments": segments,
        "cues": cues,
        "authoring": {
            "offline_only": True,
            "status": "draft_unverified",
            "source_verification": "manifest_declarations_only",
            "production_file_verification_required": True,
            "action_evidence_v2_required": True,
            "independent_take_count": len(takes),
            "segment_count": len(segments),
            "cue_count": len(cues),
        },
    }


# A concise spelling for callers that use EDL as the primary noun.
build_edl = build_multitake_edl


__all__ = [
    "SCHEMA_VERSION",
    "STORYBOARD_KIND",
    "TAKE_MANIFEST_KIND",
    "EDL_KIND",
    "TARGET_DURATION_SECONDS",
    "CANONICAL_SHOT_IDS",
    "REQUIRED_TAKE_IDS",
    "CONDITIONAL_TAKE_ID",
    "ALL_TAKE_IDS",
    "CAPTURE_ASSET_TYPES",
    "TITLE_CARD_LIMITS",
    "MECHANISM_EVIDENCE_ROLES",
    "MONTAGE_LINEAGE_EVIDENCE_ROLES",
    "MONTAGE_VISUAL_EVIDENCE_ROLES",
    "VOICE",
    "DirectorV2Error",
    "validate_storyboard_v2",
    "load_storyboard_v2",
    "validate_take_manifest",
    "build_multitake_edl",
    "build_edl",
]
