"""Project-owned ``PipelineComposer`` for the Vivhite promo.

The composer is intentionally a thin bridge.  It resolves the current
Vivhite capture contract and storyboard, then injects those concrete inputs
into xAR's stable ``PipelineInvocation`` ABI.  Importing this module and
running ``validate_only_project`` never launches a game, recorder, OCR, TTS
provider, or FFmpeg.
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .adapter import VivhiteAdapter, VivhiteAdapterError, VivhiteCaptureCandidate, create_adapter
from .capture_contract import CaptureContractError
from .preset import (
    BGM_STEM_IDS,
    CAPTURE_CONTRACT_RELATIVE_PATH,
    CLAIMS_RELATIVE_PATH,
    POLICY,
    STORYBOARD_RELATIVE_PATH,
    VARIANTS_RELATIVE_PATH,
    SHOT_IDS,
    VivhitePolicy,
    build_narration_request,
    build_render_options,
    load_policy,
    load_project_config,
    load_storyboard,
    load_variants,
    validate_project_config,
)


class VivhitePromoError(ValueError):
    """An xAR invocation cannot be composed from current project evidence."""


def _default_ffmpeg() -> str:
    """Resolve the known local encoder without relying on a mutable PATH.

    The project remains portable: callers can override this with
    ``XAR_PROMO_FFMPEG`` or install ``ffmpeg`` on PATH.  On the capture machine
    the explicitly provisioned, capability- and hash-checked build at the
    user's established ``C:\\ffmpeg\\bin`` location is preferred.
    """

    configured = os.environ.get("XAR_PROMO_FFMPEG")
    if configured and configured.strip():
        return configured
    repo_root = Path(__file__).resolve().parents[3]
    # Keep the provisioned in-place candidate first.  Every known candidate is
    # expected to be the pinned build, while preflight verifies the selected
    # binary's capability, exact location, and hash before a production run.
    candidates = (
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\ffmpeg\promo-9.0.1\bin\ffmpeg.exe"),
        repo_root / ".tools" / "ffmpeg-9.0.1" / "ffmpeg-9.0.1-full_build-shared" / "bin" / "ffmpeg.exe",
    )
    for known in candidates:
        if known.is_file():
            return str(known)
    return "ffmpeg"


def _xar_modules() -> Mapping[str, Any]:
    """Load xAR lazily, optionally from ``XAR_PROMO_TOOLCHAIN_SOURCE``."""

    try:
        from xar_promo import model, pipeline, process, render, sources  # type: ignore
        try:
            from xar_promo import storyboard  # type: ignore
        except (ImportError, ModuleNotFoundError):
            storyboard = None

        return {
            "model": model,
            "pipeline": pipeline,
            "process": process,
            "render": render,
            "sources": sources,
            "storyboard": storyboard,
        }
    except ModuleNotFoundError as first_error:
        source = os.environ.get("XAR_PROMO_TOOLCHAIN_SOURCE")
        if source:
            src = Path(source).expanduser().resolve() / "src"
            if src.is_dir() and str(src) not in os.sys.path:
                os.sys.path.insert(0, str(src))
            try:
                from xar_promo import model, pipeline, process, render, sources  # type: ignore
                try:
                    from xar_promo import storyboard  # type: ignore
                except (ImportError, ModuleNotFoundError):
                    storyboard = None

                return {
                    "model": model,
                    "pipeline": pipeline,
                    "process": process,
                    "render": render,
                    "sources": sources,
                    "storyboard": storyboard,
                }
            except ModuleNotFoundError as error:
                raise VivhitePromoError(
                    "xar-promo-toolchain is unavailable; install the pinned release "
                    "or set XAR_PROMO_TOOLCHAIN_SOURCE to its checkout"
                ) from error
        raise VivhitePromoError(
            "xar-promo-toolchain is unavailable; install the pinned release "
            "or set XAR_PROMO_TOOLCHAIN_SOURCE to its checkout"
        ) from first_error


def _factory_object(factory: Any, *, kind: str) -> Any:
    if not callable(factory):
        raise VivhitePromoError(f"{kind}_factory must be callable")
    try:
        value = factory()
    except TypeError:
        # Third-party registry factories may expose a constructor-style
        # signature.  Keep this fallback narrow and never pass game state.
        try:
            value = factory(kind=kind)
        except TypeError as exc:
            raise VivhitePromoError(f"could not instantiate {kind} factory") from exc
    if value is None:
        raise VivhitePromoError(f"{kind}_factory returned None")
    return value


def _config_chapters(config: Any) -> Mapping[str, Any]:
    rows = getattr(config, "chapters", None)
    if rows is None and isinstance(config, Mapping):
        rows = config.get("chapters")
    result: dict[str, Any] = {}
    for row in rows or ():
        chapter_id = getattr(row, "chapter_id", None)
        if chapter_id is None and isinstance(row, Mapping):
            chapter_id = row.get("id")
        if chapter_id:
            result[str(chapter_id)] = row
    return result


def _cue_for(config: Any, chapter_id: str, cue_id: str) -> tuple[str, str, str]:
    chapters = _config_chapters(config)
    chapter = chapters.get(chapter_id)
    if chapter is None:
        raise VivhitePromoError(f"project config lacks storyboard chapter {chapter_id!r}")
    cues = getattr(chapter, "cues", None)
    if cues is None and isinstance(chapter, Mapping):
        cues = chapter.get("cues", ())
    for cue in cues or ():
        current_id = getattr(cue, "cue_id", None)
        if current_id is None and isinstance(cue, Mapping):
            current_id = cue.get("id")
        if current_id != cue_id:
            continue
        narration = getattr(cue, "narration", None)
        subtitles = getattr(cue, "subtitles", None)
        if narration is None and isinstance(cue, Mapping):
            narration = cue.get("narration", {})
            subtitles = cue.get("subtitles", {})
        if not isinstance(narration, Mapping) or not isinstance(subtitles, Mapping):
            raise VivhitePromoError(f"cue {cue_id!r} has malformed localized text")
        # Never stringify malformed values: ``None`` must not become a
        # seemingly valid subtitle or TTS phrase.
        zh_value = narration.get("zh-CN")
        zh_sub_value = subtitles.get("zh-CN", zh_value)
        en_sub_value = subtitles.get("en")
        if en_sub_value is None:
            en_sub_value = narration.get("en")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (zh_value, zh_sub_value, en_sub_value)
        ):
            raise VivhitePromoError(f"cue {cue_id!r} needs zh-CN and en text")
        zh = zh_value.strip()
        zh_sub = zh_sub_value.strip()
        en_sub = en_sub_value.strip()
        return zh, zh_sub, en_sub
    raise VivhitePromoError(f"chapter {chapter_id!r} lacks cue {cue_id!r}")


def _shot_rows(storyboard: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    rows = storyboard.get("shots")
    if not isinstance(rows, list) or tuple(str(item.get("shot_id")) for item in rows if isinstance(item, Mapping)) != SHOT_IDS:
        raise VivhitePromoError("storyboard must contain the canonical ten Vivhite shots")
    return tuple(item for item in rows if isinstance(item, Mapping))


def _plan_storyboard_timeline(
    config: Any,
    shots: tuple[Mapping[str, Any], ...],
    *,
    xar: Mapping[str, Any],
    validate_only: bool,
) -> Mapping[str, tuple[float, float]]:
    """Ask xAR's pure storyboard planner for cue offsets and durations.

    The project storyboard carries the editorial shot IDs while xAR plans a
    generic chapter/cue timeline.  Keeping this small projection in the
    project composer means all timeline arithmetic still goes through the
    reusable xAR implementation.  A narrow fallback is retained for an older
    xAR checkout that predates ``storyboard.plan_storyboard``; it uses the
    already validated project durations and has no side effects.
    """

    module = xar.get("storyboard")
    planner = getattr(module, "plan_storyboard", None)
    spacing_type = getattr(module, "TimelineSpacing", None)
    if not callable(planner) or not callable(spacing_type):
        # The fallback below is completed with cumulative offsets so it is a
        # valid timeline even when running against the v0.1 xAR package.
        return _cumulative_shot_timeline(shots)

    durations = {
        str(item["cue_id"]): float(item["draft_duration_seconds"])
        for item in shots
    }

    def draft_estimator(_project: Any, _chapter: Any, cue: Any) -> float:
        cue_id = getattr(cue, "cue_id", None)
        if cue_id is None and isinstance(cue, Mapping):
            cue_id = cue.get("id")
        try:
            return durations[str(cue_id)]
        except KeyError as exc:
            raise VivhitePromoError(f"storyboard has no duration for cue {cue_id!r}") from exc

    chapter_artifacts: set[str] = set()
    chapters = getattr(config, "chapters", None)
    if chapters is None and isinstance(config, Mapping):
        chapters = config.get("chapters", ())
    for chapter in chapters or ():
        artifact_ids = getattr(chapter, "artifact_ids", None)
        if artifact_ids is None and isinstance(chapter, Mapping):
            artifact_ids = chapter.get("artifact_ids", ())
        chapter_artifacts.update(str(item) for item in artifact_ids or ())
    try:
        spacing = spacing_type(cue_gap_seconds=0, chapter_gap_seconds=0)
        timeline = planner(
            config,
            narration_duration_resolver=None,
            draft_estimator=draft_estimator,
            spacing=spacing,
            available_artifact_ids=chapter_artifacts,
            validate_only=validate_only,
        )
        rows = getattr(timeline, "cues", ())
        result = {
            str(row.cue_id): (
                float(row.start_seconds),
                float(row.duration_seconds),
            )
            for row in rows
        }
        if set(result) != set(durations):
            raise VivhitePromoError("xAR storyboard planner returned an incomplete cue timeline")
        return result
    except Exception as exc:
        # Do not hide a malformed project or an xAR planning failure.  Only
        # compatibility errors from a pre-storyboard xAR build should use the
        # deterministic local fallback; all current xAR errors are actionable.
        error_name = type(exc).__name__
        if error_name in {"ImportError", "ModuleNotFoundError", "AttributeError", "TypeError"}:
            return _cumulative_shot_timeline(shots)
        raise


def _cumulative_shot_timeline(
    shots: tuple[Mapping[str, Any], ...],
) -> Mapping[str, tuple[float, float]]:
    """Compatibility timeline used only when xAR has no storyboard module."""

    cursor = 0.0
    result: dict[str, tuple[float, float]] = {}
    for item in shots:
        cue_id = str(item["cue_id"])
        duration = float(item["draft_duration_seconds"])
        result[cue_id] = (cursor, duration)
        cursor += duration
    return result


def _find_capture_path(
    adapter: VivhiteAdapter,
    *,
    config_path: Path,
    run_path: Path | None,
    policy: VivhitePolicy,
) -> Path:
    candidates: list[Path] = []
    if run_path is not None:
        run_root = run_path.expanduser().resolve().parent
        candidates.extend((run_root / "capture" / "contract.json", run_root / "contract.json"))
    candidates.append(config_path.parent / policy.capture_contract_path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    # Let adapter produce the canonical actionable path if no candidate exists.
    adapter.project_root = config_path.parent.resolve()
    return adapter.capture_path()


def _load_candidate(
    adapter: VivhiteAdapter,
    *,
    config_path: Path,
    run_path: Path | None,
    policy: VivhitePolicy,
    validate_only: bool,
) -> VivhiteCaptureCandidate | None:
    if validate_only:
        return None
    path = _find_capture_path(adapter, config_path=config_path, run_path=run_path, policy=policy)
    if not path.is_file():
        raise VivhitePromoError(
            f"verified Vivhite capture contract is required for build: {path}"
        )
    artifact_root = path.parent
    if path.parent.name.casefold() == "capture":
        artifact_root = path.parent.parent
    if run_path is not None:
        artifact_root = run_path.expanduser().resolve().parent
    return adapter.load_capture(
        path,
        verify_files=True,
        artifact_root=artifact_root,
    )


def _subtitle_renderer(segment: Any, narration: Any, *, workdir: Path) -> str:
    """Emit a conservative, bilingual ASS document without side effects."""

    subtitles = dict(getattr(segment, "subtitles", {}) or {})
    zh = str(subtitles.get("zh-CN", "")).replace("{", "\\{").replace("}", "\\}")
    en = str(subtitles.get("en", "")).replace("{", "\\{").replace("}", "\\}")
    options = getattr(segment, "render_options", None)
    duration = float(getattr(options, "duration_seconds", 1.0) or 1.0)
    # ASS timestamps use centiseconds.  Keep the event bounded to this segment
    # instead of the old placeholder hour-long window; this matters when the
    # same renderer is reused for 60/30/15-second variants.
    centiseconds = max(1, int(round(duration * 100.0)))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, hundredths = divmod(remainder, 100)
    event_end = f"{hours}:{minutes:02d}:{seconds:02d}.{hundredths:02d}"
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
        "WrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        "Style: Default,Microsoft YaHei,42,&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,80,80,70,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,{event_end},Default,,0,0,70,,{zh}\\N{{\\i1}}{en}{{\\i0}}\n"
    )


def _narration_resolver_factory(
    *,
    config_path: Path,
    run_path: Path | None,
    candidate: VivhiteCaptureCandidate | None,
) -> Any:
    def resolve(segment: Any, *, workdir: Path) -> Any:
        shot_id = str(segment.segment_id)
        roots: list[Path] = []
        if run_path is not None:
            roots.append(run_path.parent.resolve())
        roots.append(config_path.parent.resolve())
        if candidate is not None:
            roots.append(candidate.contract.artifact_root)
        names = (f"{shot_id}.mp3", f"{shot_id}.wav", f"{shot_id}.m4a")
        for root in roots:
            for relative in (
                *(Path("narration") / name for name in names),
                *(Path("audio") / name for name in names),
                *(Path("capture") / "audio" / name for name in names),
            ):
                path = (root / relative).resolve()
                if path.is_file():
                    try:
                        from xar_promo.pipeline import NarrationArtifact  # type: ignore

                        return NarrationArtifact(
                            path=path,
                            media_type={
                                ".mp3": "audio/mpeg",
                                ".m4a": "audio/mp4",
                            }.get(path.suffix.lower(), "audio/wav"),
                            origin="vivhite-prepared-narration",
                            metadata={"shot_id": shot_id},
                        )
                    except ModuleNotFoundError as exc:
                        raise VivhitePromoError("xAR NarrationArtifact is unavailable") from exc
        raise VivhitePromoError(
            f"prepared narration for {shot_id!r} is missing; generate it in the project run first"
        )

    return resolve


def _prepared_narration_path(
    shot_id: str,
    *,
    config_path: Path,
    run_path: Path | None,
    candidate: VivhiteCaptureCandidate | None,
) -> Path | None:
    """Find a project-prepared narration file without invoking a provider."""

    roots: list[Path] = []
    if run_path is not None:
        roots.append(run_path.parent.resolve())
    roots.append(config_path.parent.resolve())
    if candidate is not None:
        roots.append(candidate.contract.artifact_root)
    names = (f"{shot_id}.mp3", f"{shot_id}.wav", f"{shot_id}.m4a")
    seen: set[Path] = set()
    for root in roots:
        for relative in (
            *(Path("narration") / name for name in names),
            *(Path("audio") / name for name in names),
            *(Path("capture") / "audio" / name for name in names),
        ):
            path = (root / relative).resolve()
            if path in seen:
                continue
            seen.add(path)
            if path.is_file():
                return path
    return None


def _audio_mix_for_segment(
    *,
    candidate: VivhiteCaptureCandidate | None,
    shot_id: str,
    start_seconds: float,
    duration_seconds: float,
    config_path: Path,
    run_path: Path | None,
    policy: VivhitePolicy,
) -> Any | None:
    """Build an optional xAR multitrack spec from explicitly prepared stems.

    Mixing is opt-in by evidence: a capture with no declared stems retains the
    legacy single-narration path.  Once a verified capture declares stems,
    every dependency must be present and the typed mix must build successfully;
    silently dropping game/SFX audio would invalidate the capture contract.
    """

    if candidate is None or not candidate.audio_stems:
        return None
    narration_path = _prepared_narration_path(
        shot_id,
        config_path=config_path,
        run_path=run_path,
        candidate=candidate,
    )
    if narration_path is None:
        raise VivhitePromoError(
            f"capture declares audio stems but prepared narration for {shot_id!r} is missing"
        )
    try:
        from xar_promo.audio import AudioMixSpec, AudioStem  # type: ignore
    except (ImportError, ModuleNotFoundError) as exc:
        raise VivhitePromoError(
            "capture declares audio stems but xAR 0.2 multitrack support is unavailable"
        ) from exc
    stems: list[Any] = [AudioStem("narration", narration_path)]
    seen_ids = {"narration"}
    for binding in candidate.audio_stems:
        if not policy.include_bgm and binding.stem_id.casefold() in BGM_STEM_IDS:
            raise VivhitePromoError(
                f"BGM stem {binding.stem_id!r} is forbidden by this preset; "
                "set include_bgm=true only after an explicit project decision"
            )
        if binding.stem_id in seen_ids:
            raise VivhitePromoError(
                f"capture audio stem {binding.stem_id!r} conflicts with narration or another stem"
            )
        seen_ids.add(binding.stem_id)
        stems.append(
            AudioStem(
                binding.stem_id,
                binding.artifact.path,
                trim_start_seconds=start_seconds,
                trim_duration_seconds=duration_seconds,
            )
        )
    try:
        return AudioMixSpec(
            tuple(stems),
            duration_seconds=duration_seconds,
            sample_rate=48_000,
            channels=2,
            metadata={"project": "vivhite-player-promo", "shot_id": shot_id},
        )
    except (TypeError, ValueError) as exc:
        raise VivhitePromoError(
            f"could not construct the hash-bound audio mix for {shot_id!r}: {exc}"
        ) from exc


def _visual_probe_factory(*, policy: VivhitePolicy) -> Any:
    def probe(path: Path) -> Any:
        sidecars = (
            Path(f"{path}.probe.json"),
            path.with_name(f"{path.stem}.probe.json"),
        )
        payload: Mapping[str, Any] | None = None
        for sidecar in sidecars:
            if sidecar.is_file():
                try:
                    raw = json.loads(sidecar.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise VivhitePromoError(f"invalid media probe sidecar: {sidecar}") from exc
                if isinstance(raw, Mapping):
                    payload = raw
                    break
        if payload is None:
            raise VivhitePromoError(
                f"visual {path} lacks a bound ffprobe sidecar; run xAR media probe before build"
            )
        try:
            media_type = str(payload["media_type"])
            width = int(payload["width"])
            height = int(payload["height"])
            from xar_promo.sources import VisualProbeResult  # type: ignore

            return VisualProbeResult(media_type=media_type, width=width, height=height)
        except (KeyError, TypeError, ValueError, ModuleNotFoundError) as exc:
            raise VivhitePromoError(f"media probe sidecar is incomplete: {path}") from exc

    return probe


def _visual_resolver_factory() -> Any:
    """Return the inert resolver required by xAR's validate-only contract."""

    def resolve(source: Any, *, workdir: Path) -> Path:
        path = Path(source.path)
        return (path if path.is_absolute() else Path(workdir) / path).resolve()

    return resolve


def _command_runner_factory() -> Any:
    try:
        from xar_promo.process import run_command  # type: ignore

        return run_command
    except ModuleNotFoundError as exc:
        def unavailable(*args: Any, **kwargs: Any) -> Any:
            raise VivhitePromoError("xAR process runner is unavailable") from exc

        return unavailable


def compose(
    config: Any,
    run: Any,
    *,
    config_path: Path,
    run_path: Path | None,
    workdir: Path,
    adapter_factory: Any,
    preset_factory: Any,
    validate_only: bool,
) -> Any:
    """Compose one xAR ``PipelineInvocation`` using the fixed ABI."""

    config_path = Path(config_path).expanduser().resolve()
    workdir = Path(workdir).expanduser().resolve()
    if not isinstance(validate_only, bool):
        raise VivhitePromoError("validate_only must be boolean")
    adapter = _factory_object(adapter_factory, kind="adapter")
    preset = _factory_object(preset_factory, kind="preset")
    if not isinstance(adapter, VivhiteAdapter):
        # Accept compatible project wrappers while preventing accidental use of
        # another game adapter under the Vivhite preset.
        if not hasattr(adapter, "load_capture") or not hasattr(adapter, "visual_path"):
            raise VivhitePromoError("vivhite adapter factory returned an incompatible object")
    policy = getattr(preset, "policy", POLICY)
    if not isinstance(policy, VivhitePolicy):
        policy = POLICY
    validate_project_config(config, policy=policy)
    storyboard_path = config_path.parent / policy.storyboard_path
    storyboard = load_storyboard(storyboard_path)
    shots = _shot_rows(storyboard)
    if hasattr(adapter, "project_root"):
        adapter.project_root = config_path.parent
    candidate = _load_candidate(
        adapter,
        config_path=config_path,
        run_path=run_path,
        policy=policy,
        validate_only=validate_only,
    )
    xar = _xar_modules()
    model = xar["model"]
    pipeline = xar["pipeline"]
    sources = xar["sources"]
    render = xar["render"]

    # The generic storyboard planner deliberately accepts only xAR's typed
    # ``ProjectConfig``.  Registry/CLI callers already provide that object,
    # while direct project tests sometimes pass the decoded JSON mapping.  Do
    # the conversion before invoking the planner so both entry paths exercise
    # the same deterministic xAR timeline implementation.
    if not isinstance(config, model.ProjectConfig):
        try:
            config = model.ProjectConfig.from_mapping(dict(config))
        except (TypeError, ValueError, KeyError) as exc:
            raise VivhitePromoError(
                "Vivhite composer requires a valid xAR ProjectConfig mapping"
            ) from exc
    cue_timeline = _plan_storyboard_timeline(
        config,
        shots,
        xar=xar,
        validate_only=validate_only,
    )
    segments: list[Any] = []
    for item in shots:
        shot_id = str(item["shot_id"])
        chapter_id = str(item["chapter_id"])
        cue_id = str(item["cue_id"])
        narration, zh_subtitle, en_subtitle = _cue_for(config, chapter_id, cue_id)
        try:
            timeline_start_seconds, planned_duration = cue_timeline[cue_id]
        except KeyError as exc:
            raise VivhitePromoError(
                f"storyboard timeline lacks cue {cue_id!r} for shot {shot_id!r}"
            ) from exc
        visual_path, capture_start_seconds = adapter.visual_path(
            shot_id,
            workdir=workdir,
            candidate=candidate,
            validate_only=validate_only,
        )
        # With a real capture, seek into the producer's raw media at the
        # hash-bound span start.  During validate-only planning no capture is
        # loaded, so expose xAR's cumulative storyboard offset instead of
        # repeating zero for every placeholder source.
        start_seconds = (
            capture_start_seconds if candidate is not None else timeline_start_seconds
        )
        visual = sources.VisualSource(
            source_id=shot_id,
            kind=sources.VIDEO,
            path=visual_path,
            origin="vivhite-capture-contract-v1",
            requires_resolution=validate_only and candidate is None,
            metadata={
                "shot_id": shot_id,
                "chapter_id": chapter_id,
                "provenance": item.get("provenance", "natural"),
            },
        )
        options = render.RenderOptions(
            width=policy.width,
            height=policy.height,
            fps=policy.fps,
            duration_seconds=planned_duration if candidate is None else max(
                0.5,
                min(
                    planned_duration,
                    candidate.shot(shot_id).end_seconds
                    - candidate.shot(shot_id).begin_seconds,
                ),
            ),
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
        audio_mix = _audio_mix_for_segment(
            candidate=candidate,
            shot_id=shot_id,
            start_seconds=start_seconds,
            duration_seconds=options.duration_seconds,
            config_path=config_path,
            run_path=run_path,
            policy=policy,
        )
        segment_kwargs: dict[str, Any] = {
            "segment_id": shot_id,
            "visual_source": visual,
            "render_options": options,
            "subtitles": {"zh-CN": zh_subtitle, "en": en_subtitle},
            "narration_request": build_narration_request(narration, policy=policy),
            "start_seconds": start_seconds,
        }
        # The optional field was added in xAR 0.2.  Do not break a caller that
        # still has a v0.1 installation when no multitrack spec is available.
        if audio_mix is not None and "audio_mix" in inspect.signature(pipeline.SegmentDraft).parameters:
            segment_kwargs["audio_mix"] = audio_mix
        segments.append(pipeline.SegmentDraft(**segment_kwargs))
    draft = pipeline.PipelineDraft(
        config=config,
        segments=tuple(segments),
        deliverable_relative_path=Path("deliverables") / "vivhite-player-10m.mp4",
        deliverable_artifact_id="deliverable.vivhite-player-10m",
        deliverable_media_type="video/mp4",
    )
    dependencies = pipeline.PipelineDependencies(
        ffmpeg=_default_ffmpeg(),
        subtitle_renderer=_subtitle_renderer,
        command_runner=_command_runner_factory(),
        visual_probe=_visual_probe_factory(policy=policy),
        visual_resolver=_visual_resolver_factory(),
        narration_resolver=_narration_resolver_factory(
            config_path=config_path,
            run_path=run_path,
            candidate=candidate,
        ),
        render_planner=render.plan_render,
        concat_planner=render.plan_concat,
        plan_executor=render.execute_render_plan,
    )
    return pipeline.PipelineInvocation(draft=draft, dependencies=dependencies, workdir=workdir)


def validate_only_project(path: str | Path) -> Mapping[str, Any]:
    """Run the project-side offline checks without importing or invoking xAR."""

    config_path = Path(path).expanduser().resolve()
    config = load_project_config(config_path)
    policy_path = config_path.parent / "preset.json"
    policy = load_policy(policy_path if policy_path.is_file() else None)
    validate_project_config(config, policy=policy)
    storyboard = load_storyboard(config_path.parent / policy.storyboard_path)
    variants = load_variants(
        config_path.parent / VARIANTS_RELATIVE_PATH,
        storyboard=storyboard,
    )
    claim_path = config_path.parent / policy.claims_path
    claims_count = 0
    if claim_path.is_file():
        from .claims import load_claims

        claims_count = len(load_claims(claim_path))
    return {
        "status": "validated",
        "project_id": policy.project_id,
        "preset": policy.preset_id,
        "shot_count": len(storyboard["shots"]),
        "variant_count": len(variants),
        "claims_count": claims_count,
        "capture_required_for_build": True,
        "xar_invocation": "deferred",
    }


__all__ = ["VivhitePromoError", "compose", "validate_only_project"]
