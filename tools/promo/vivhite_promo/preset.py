"""Vivhite promotional-video preset and project policy.

This module contains editorial and game-specific policy by design.  It is the
boundary between the generic xAR pipeline and the current Vivhite release.  No
game process is launched here; all methods are deterministic and safe to call
from xAR's read-only ``plan`` path.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PROJECT_ID = "vivhite-player-promo"
ADAPTER_ID = "vivhite"
PRESET_ID = "vivhite-player-10m"
GAME_VERSION = "0.111.0"
MOD_ID = "Vivhite"
MOD_VERSION = "0.2.1"
PCK_NAME = "Vivhite"
RITSULIB_ID = "STS2-RitsuLib"
RITSULIB_VERSION = "0.5.14"
NARRATION_LOCALE = "zh-CN"
SUBTITLE_LOCALES = ("zh-CN", "en")
VOICE = "zh-CN-XiaoxiaoNeural"
INCLUDE_BGM = False
BGM_STEM_IDS = frozenset({"bgm", "music", "background-music", "background_music"})
TARGET_DURATION_SECONDS = 600
DURATION_LIMIT_SECONDS = 1200
WIDTH = 1920
HEIGHT = 1080
FPS = 60
CAPTURE_CONTRACT_RELATIVE_PATH = "runs/current/capture/contract.json"
STORYBOARD_RELATIVE_PATH = "storyboard.json"
CLAIMS_RELATIVE_PATH = "claims/claims.json"
VARIANTS_RELATIVE_PATH = "variants"

SHOT_IDS = (
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

# Chapter IDs are project-owned semantic labels.  Keeping their canonical
# order here prevents an apparently valid ten-shot config from silently
# pairing narration with the wrong capture span.
CHAPTER_IDS = tuple(item.split("-", 1)[1] for item in SHOT_IDS)
VARIANT_IDS = ("hero-60", "cut-30", "cut-15")


class VivhitePresetError(ValueError):
    """The current project config violates the Vivhite promo policy."""


@dataclass(frozen=True, slots=True)
class VivhitePolicy:
    project_id: str = PROJECT_ID
    adapter_id: str = ADAPTER_ID
    preset_id: str = PRESET_ID
    game_version: str = GAME_VERSION
    mod_id: str = MOD_ID
    mod_version: str = MOD_VERSION
    pck_name: str = PCK_NAME
    pck_version: str = MOD_VERSION
    ritsu_lib_id: str = RITSULIB_ID
    ritsu_lib_version: str = RITSULIB_VERSION
    narration_locale: str = NARRATION_LOCALE
    subtitle_locales: tuple[str, ...] = SUBTITLE_LOCALES
    voice: str = VOICE
    include_bgm: bool = INCLUDE_BGM
    target_duration_seconds: int = TARGET_DURATION_SECONDS
    duration_limit_seconds: int = DURATION_LIMIT_SECONDS
    width: int = WIDTH
    height: int = HEIGHT
    fps: int = FPS
    capture_contract_path: str = CAPTURE_CONTRACT_RELATIVE_PATH
    storyboard_path: str = STORYBOARD_RELATIVE_PATH
    claims_path: str = CLAIMS_RELATIVE_PATH
    require_vulkan: bool = True
    forbid_overlays: bool = True
    forbid_loading: bool = True
    forbid_console: bool = True
    preserve_failed_attempts: bool = True

    def validate(self) -> None:
        # This is a project preset, not a user-selectable generic profile.
        # Keep the identity and release geometry pinned so a stale or copied
        # JSON cannot silently make the adapter certify another runtime.
        canonical = {
            "project_id": PROJECT_ID,
            "adapter_id": ADAPTER_ID,
            "preset_id": PRESET_ID,
            "game_version": GAME_VERSION,
            "mod_id": MOD_ID,
            "mod_version": MOD_VERSION,
            "pck_name": PCK_NAME,
            "pck_version": MOD_VERSION,
            "ritsu_lib_id": RITSULIB_ID,
            "ritsu_lib_version": RITSULIB_VERSION,
            "narration_locale": NARRATION_LOCALE,
            "target_duration_seconds": TARGET_DURATION_SECONDS,
            "duration_limit_seconds": DURATION_LIMIT_SECONDS,
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "capture_contract_path": CAPTURE_CONTRACT_RELATIVE_PATH,
            "storyboard_path": STORYBOARD_RELATIVE_PATH,
            "claims_path": CLAIMS_RELATIVE_PATH,
            "require_vulkan": True,
            "forbid_overlays": True,
            "forbid_loading": True,
            "forbid_console": True,
            "preserve_failed_attempts": True,
        }
        for field_name, expected in canonical.items():
            observed = getattr(self, field_name)
            if observed != expected:
                raise VivhitePresetError(
                    f"{field_name} must remain pinned to {expected!r}; got {observed!r}"
                )
        if tuple(self.subtitle_locales) != SUBTITLE_LOCALES:
            raise VivhitePresetError(
                f"subtitle locales must remain {SUBTITLE_LOCALES!r}"
            )
        if self.voice != VOICE:
            raise VivhitePresetError(
                f"voice must remain pinned to the ZhongGuo phase-one voice {VOICE!r}"
            )
        if not isinstance(self.include_bgm, bool):
            raise VivhitePresetError("include_bgm must be boolean")
        if self.include_bgm is not INCLUDE_BGM:
            raise VivhitePresetError(
                "include_bgm must remain false until the project explicitly adopts "
                "and audits a licensed BGM policy"
            )
        if len(self.subtitle_locales) != len(set(self.subtitle_locales)):
            raise VivhitePresetError("subtitle locales must be unique")


POLICY = VivhitePolicy()


@dataclass(frozen=True, slots=True)
class FallbackTtsRequest:
    """Small dependency-free stand-in used by offline authoring tests."""

    text: str
    voice: str
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    audio_format: str = "mp3"
    cache_salt: str = "vivhite-player-promo-v1"


@dataclass(frozen=True, slots=True)
class FallbackRenderOptions:
    width: int
    height: int
    fps: int
    duration_seconds: float
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    pixel_format: str = "yuv420p"
    preset: str = "medium"
    crf: int = 20
    audio_bitrate: str = "192k"
    audio_sample_rate: int = 48_000
    audio_channels: int = 2
    pad_color: str = "black"


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise VivhitePresetError(f"could not read {label}: {path}: {exc}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VivhitePresetError(f"invalid {label} JSON {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise VivhitePresetError(f"{label} root must be an object")
    return value


def _project_fields(config: Any) -> tuple[
    str,
    str,
    str,
    str,
    str,
    tuple[str, ...],
    int | None,
    tuple[Any, ...],
]:
    """Read the stable xAR ProjectConfig attributes without importing xAR."""

    if isinstance(config, Mapping):
        project = config.get("project")
        pipeline = config.get("pipeline")
        locales = config.get("locales")
        constraints = config.get("constraints")
        chapters = config.get("chapters")
        if not all(isinstance(item, Mapping) for item in (project, pipeline, locales, constraints)):
            raise VivhitePresetError("project config has malformed project/pipeline/locales/constraints")
        return (
            str(project.get("id", "")),
            str(project.get("title", "")),
            str(pipeline.get("adapter", "")),
            str(pipeline.get("preset", "")),
            str(locales.get("narration", "")),
            tuple(str(item) for item in locales.get("subtitles", ())),
            constraints.get("duration_limit_seconds"),
            tuple(chapters or ()) if isinstance(chapters, list) else (),
        )
    try:
        return (
            str(config.project_id),
            str(config.title),
            str(config.adapter),
            str(config.preset),
            str(config.narration_locale),
            tuple(str(item) for item in config.subtitle_locales),
            config.duration_limit_seconds,
            tuple(config.chapters),
        )
    except AttributeError as exc:
        raise VivhitePresetError("config must be an xAR ProjectConfig or mapping") from exc


def validate_project_config(config: Any, *, policy: VivhitePolicy = POLICY) -> Any:
    """Validate the generic config plus the fixed ten-shot Vivhite contract."""

    policy.validate()
    (
        project_id,
        title,
        adapter,
        preset,
        narration_locale,
        subtitles,
        duration_limit,
        chapters,
    ) = _project_fields(config)
    if project_id != policy.project_id:
        raise VivhitePresetError(f"project id must be {policy.project_id!r}")
    if not title.strip():
        raise VivhitePresetError("project title must be non-empty")
    if adapter != policy.adapter_id:
        raise VivhitePresetError(f"pipeline.adapter must be {policy.adapter_id!r}")
    if preset != policy.preset_id:
        raise VivhitePresetError(f"pipeline.preset must be {policy.preset_id!r}")
    if narration_locale != policy.narration_locale:
        raise VivhitePresetError(
            f"narration locale must be {policy.narration_locale!r}"
        )
    if tuple(subtitles) != policy.subtitle_locales:
        raise VivhitePresetError(
            f"subtitle locales must be ordered as {policy.subtitle_locales!r}"
        )
    if duration_limit is not None and (
        isinstance(duration_limit, bool)
        or not isinstance(duration_limit, int)
        or duration_limit < policy.duration_limit_seconds
    ):
        raise VivhitePresetError(
            f"duration limit must be >= {policy.duration_limit_seconds} seconds"
        )
    chapter_ids: list[str] = []
    for index, chapter in enumerate(chapters):
        if isinstance(chapter, Mapping):
            chapter_id = str(chapter.get("id", ""))
            chapter_state = str(chapter.get("state", ""))
            cues = chapter.get("cues", [])
        else:
            chapter_id = str(getattr(chapter, "chapter_id", ""))
            chapter_state = str(getattr(chapter, "state", ""))
            cues = getattr(chapter, "cues", ())
        if not chapter_id or chapter_id in chapter_ids:
            raise VivhitePresetError("project chapters contain duplicate or empty ids")
        if chapter_state not in {"planned", "ready"}:
            raise VivhitePresetError(f"chapter {chapter_id!r} has invalid state")
        if not cues:
            raise VivhitePresetError(f"chapter {chapter_id!r} must contain at least one cue")
        chapter_ids.append(chapter_id)
    # The config uses semantic chapter IDs; the storyboard is the source of
    # truth for shot IDs.  Require the canonical order so that a valid-looking
    # config cannot route a narration cue to the wrong gameplay span.
    if tuple(chapter_ids) != CHAPTER_IDS:
        raise VivhitePresetError(
            "Vivhite promo chapters must use the canonical order: "
            + ", ".join(CHAPTER_IDS)
        )
    return config


def load_project_config(path: str | Path) -> Any:
    """Load a project config through xAR when available, otherwise as JSON."""

    config_path = Path(path).expanduser().resolve()
    try:
        from xar_promo.project import load_document  # type: ignore

        loaded = load_document(config_path, check_files=False)
        if loaded.config is None:
            raise VivhitePresetError("project path did not contain an xAR ProjectConfig")
        return validate_project_config(loaded.config)
    except ModuleNotFoundError:
        payload = _read_json(config_path, "project config")
        validate_project_config(payload)
        return payload


def load_policy(path: str | Path | None = None) -> VivhitePolicy:
    """Load optional project policy JSON, retaining safe defaults."""

    if path is None:
        return POLICY
    payload = _read_json(Path(path), "Vivhite preset policy")
    values = dict(POLICY.__dict__) if hasattr(POLICY, "__dict__") else {
        field_name: getattr(POLICY, field_name)
        for field_name in POLICY.__dataclass_fields__
    }
    for key in values:
        if key in payload:
            values[key] = payload[key]
    if "subtitle_locales" in values:
        values["subtitle_locales"] = tuple(values["subtitle_locales"])
    policy = VivhitePolicy(**values)
    policy.validate()
    return policy


def build_narration_request(text: str, *, policy: VivhitePolicy = POLICY) -> Any:
    """Build an xAR TTS request, or a dependency-free equivalent."""

    policy.validate()
    if not isinstance(text, str) or not text.strip():
        raise VivhitePresetError("narration text must be non-empty")
    try:
        from xar_promo.tts import TtsRequest  # type: ignore

        return TtsRequest(
            text=text,
            voice=policy.voice,
            rate="+0%",
            pitch="+0Hz",
            volume="+0%",
            audio_format="mp3",
            cache_salt=f"{policy.project_id}:v1",
        )
    except ModuleNotFoundError:
        return FallbackTtsRequest(
            text=text,
            voice=policy.voice,
            cache_salt=f"{policy.project_id}:v1",
        )


def build_render_options(duration_seconds: float, *, policy: VivhitePolicy = POLICY) -> Any:
    policy.validate()
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)):
        raise VivhitePresetError("render duration must be numeric")
    duration = float(duration_seconds)
    if not math.isfinite(duration) or duration <= 0:
        raise VivhitePresetError("render duration must be positive and finite")
    try:
        from xar_promo.render import RenderOptions  # type: ignore

        return RenderOptions(
            width=policy.width,
            height=policy.height,
            fps=policy.fps,
            duration_seconds=duration,
            video_codec="libx264",
            audio_codec="aac",
            pixel_format="yuv420p",
            preset="medium",
            crf=20,
            audio_bitrate="192k",
            audio_sample_rate=48_000,
            audio_channels=2,
            pad_color="black",
        )
    except ModuleNotFoundError:
        return FallbackRenderOptions(policy.width, policy.height, policy.fps, duration)


def load_storyboard(path: str | Path) -> Mapping[str, Any]:
    payload = _read_json(Path(path), "Vivhite storyboard")
    if payload.get("kind") != "vivhite_promo_storyboard" or payload.get("schema_version") != 1:
        raise VivhitePresetError("storyboard must declare vivhite_promo_storyboard schema_version 1")
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        raise VivhitePresetError("storyboard.shots must be a non-empty array")
    target_duration = payload.get("target_duration_seconds")
    if (
        isinstance(target_duration, bool)
        or not isinstance(target_duration, (int, float))
        or not math.isfinite(float(target_duration))
        or float(target_duration) <= 0
    ):
        raise VivhitePresetError("storyboard.target_duration_seconds must be positive")
    canvas = payload.get("canvas")
    if not isinstance(canvas, Mapping):
        raise VivhitePresetError("storyboard.canvas must be an object")
    if (
        canvas.get("width") != WIDTH
        or canvas.get("height") != HEIGHT
        or canvas.get("fps") != FPS
        or str(canvas.get("orientation", "")).casefold() != "landscape"
    ):
        raise VivhitePresetError("storyboard canvas must be 1920x1080 landscape at 60 FPS")
    ids: list[str] = []
    total_duration = 0.0
    for index, item in enumerate(shots):
        if not isinstance(item, Mapping):
            raise VivhitePresetError(f"storyboard.shots[{index}] must be an object")
        shot_id = str(item.get("shot_id", ""))
        if not shot_id or shot_id in ids:
            raise VivhitePresetError("storyboard shot IDs must be unique and non-empty")
        duration = item.get("draft_duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(float(duration)) or float(duration) <= 0:
            raise VivhitePresetError(f"storyboard shot {shot_id!r} has invalid draft duration")
        for field_name in ("chapter_id", "cue_id", "span_id", "provenance"):
            if not isinstance(item.get(field_name), str) or not str(item[field_name]).strip():
                raise VivhitePresetError(
                    f"storyboard shot {shot_id!r} needs {field_name}"
                )
        if item.get("provenance") not in {"natural", "staged"}:
            raise VivhitePresetError(f"storyboard shot {shot_id!r} has invalid provenance")
        roles = item.get("required_evidence_roles", [])
        if not isinstance(roles, list) or any(
            not isinstance(role, str) or not role.strip() for role in roles
        ) or len(roles) != len(set(roles)):
            raise VivhitePresetError(
                f"storyboard shot {shot_id!r} has invalid required evidence roles"
            )
        ids.append(shot_id)
        total_duration += float(duration)
    if tuple(ids) != SHOT_IDS:
        raise VivhitePresetError("storyboard shot IDs do not match the canonical Vivhite order")
    if not math.isclose(total_duration, float(target_duration), rel_tol=0.0, abs_tol=1e-6):
        raise VivhitePresetError(
            "storyboard draft durations must sum to target_duration_seconds"
        )
    return payload


def estimate_shot_duration(storyboard: Mapping[str, Any], shot_id: str) -> float:
    for item in storyboard.get("shots", []):
        if isinstance(item, Mapping) and item.get("shot_id") == shot_id:
            return float(item["draft_duration_seconds"])
    raise VivhitePresetError(f"storyboard has no shot {shot_id!r}")


def load_variant(path: str | Path) -> Mapping[str, Any]:
    """Load one short-cut manifest without touching media or external tools."""

    payload = _read_json(Path(path), "Vivhite variant")
    if payload.get("kind") != "vivhite_promo_variant" or payload.get("schema_version") != 1:
        raise VivhitePresetError(
            "variant must declare vivhite_promo_variant schema_version 1"
        )
    variant_id = str(payload.get("variant_id", ""))
    if variant_id not in VARIANT_IDS:
        raise VivhitePresetError(f"unknown Vivhite variant {variant_id!r}")
    if payload.get("project_id") != PROJECT_ID:
        raise VivhitePresetError("variant project_id does not match the Vivhite promo")
    duration = payload.get("duration_seconds")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or float(duration) <= 0
    ):
        raise VivhitePresetError(f"variant {variant_id!r} has invalid duration_seconds")
    source_shots = payload.get("source_shots")
    if not isinstance(source_shots, list) or not source_shots:
        raise VivhitePresetError(f"variant {variant_id!r} needs source_shots")
    if len(source_shots) != len(set(source_shots)) or any(
        str(shot) not in SHOT_IDS for shot in source_shots
    ):
        raise VivhitePresetError(f"variant {variant_id!r} references an unknown or duplicate shot")
    if payload.get("composition") != "new-run-from-capture-spans":
        raise VivhitePresetError(
            f"variant {variant_id!r} must compose from a new capture-span run"
        )
    if payload.get("requires_new_run") is not True:
        raise VivhitePresetError(f"variant {variant_id!r} must require a new run")
    deliverable = payload.get("deliverable")
    if not isinstance(deliverable, str) or not deliverable.strip():
        raise VivhitePresetError(f"variant {variant_id!r} needs a deliverable path")
    normalized = Path(deliverable.replace("\\", "/"))
    if normalized.is_absolute() or any(
        part in {"", ".", ".."} for part in normalized.parts
    ):
        raise VivhitePresetError(f"variant {variant_id!r} deliverable must be relative")
    return payload


def load_variants(
    directory: str | Path,
    *,
    storyboard: Mapping[str, Any] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    """Load all canonical variant manifests in deterministic order.

    When the validated storyboard is supplied, its editorial shot lists are
    the source of truth.  Keeping this check at the project boundary prevents
    a short-cut manifest from silently drifting to a different set of claims
    while retaining the old one-argument loader ABI for callers that only need
    structural variant validation.
    """

    root = Path(directory)
    rows: list[Mapping[str, Any]] = []
    for variant_id in VARIANT_IDS:
        path = root / f"{variant_id}.json"
        if not path.is_file():
            raise VivhitePresetError(f"missing variant manifest: {path}")
        rows.append(load_variant(path))
    if storyboard is not None:
        declared = storyboard.get("variants")
        if not isinstance(declared, Mapping):
            raise VivhitePresetError("storyboard.variants must be an object")
        for row in rows:
            variant_id = str(row["variant_id"])
            storyboard_row = declared.get(variant_id)
            if not isinstance(storyboard_row, Mapping):
                raise VivhitePresetError(
                    f"storyboard.variants lacks canonical variant {variant_id!r}"
                )
            expected = storyboard_row.get("shot_ids")
            actual = row.get("source_shots")
            if not isinstance(expected, list) or actual != expected:
                raise VivhitePresetError(
                    f"variant {variant_id!r} source_shots do not match storyboard.variants"
                )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class VivhitePreset:
    policy: VivhitePolicy = POLICY

    def __post_init__(self) -> None:
        self.policy.validate()

    @property
    def id(self) -> str:
        return self.policy.preset_id

    def validate(self, config: Any) -> Any:
        return validate_project_config(config, policy=self.policy)

    def __call__(self, *args: Any, **kwargs: Any) -> "VivhitePreset":
        return self


def create_preset(*args: Any, **kwargs: Any) -> VivhitePreset:
    """Entry-point factory; arguments are intentionally ignored and inert."""

    return VivhitePreset()


__all__ = [
    "PROJECT_ID",
    "ADAPTER_ID",
    "PRESET_ID",
    "GAME_VERSION",
    "MOD_ID",
    "MOD_VERSION",
    "PCK_NAME",
    "RITSULIB_ID",
    "RITSULIB_VERSION",
    "NARRATION_LOCALE",
    "SUBTITLE_LOCALES",
    "VOICE",
    "INCLUDE_BGM",
    "BGM_STEM_IDS",
    "TARGET_DURATION_SECONDS",
    "DURATION_LIMIT_SECONDS",
    "WIDTH",
    "HEIGHT",
    "FPS",
    "SHOT_IDS",
    "CHAPTER_IDS",
    "VARIANT_IDS",
    "CAPTURE_CONTRACT_RELATIVE_PATH",
    "STORYBOARD_RELATIVE_PATH",
    "CLAIMS_RELATIVE_PATH",
    "VARIANTS_RELATIVE_PATH",
    "VivhitePresetError",
    "VivhitePolicy",
    "POLICY",
    "FallbackTtsRequest",
    "FallbackRenderOptions",
    "VivhitePreset",
    "validate_project_config",
    "load_project_config",
    "load_policy",
    "build_narration_request",
    "build_render_options",
    "load_storyboard",
    "estimate_shot_duration",
    "load_variant",
    "load_variants",
    "create_preset",
]
