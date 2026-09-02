"""Derive and render short Vivhite previews from one full-master batch.

This is a project-side producer.  It consumes the *same* hash-bound raw
capture, capture contract, and already-produced Xiaoxiao narration batch as a
full-master run, then writes explicit EDLs and fresh sibling attempt
directories for the 60/30/15 second cuts.  It never starts OBS/the game/OCR or
TTS, and it never treats a rendered byte as semantic proof or signoff.

The renderer used here is :mod:`render_full_master`: its one-pass FFmpeg
command retains the raw/contract/probe/partial/process-log provenance.  A
batch is deliberately a new sibling of the source run; existing directories
are rejected before any output is written.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import traceback
from typing import Any, Iterable, Mapping


PROMO_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_RUN = PROMO_ROOT / "runs" / "run-20260902T-full-master-delivery-a2"
DEFAULT_SOURCE_EDL = DEFAULT_SOURCE_RUN / "notes" / "full-master-edl-staged.json"
DEFAULT_RAW = DEFAULT_SOURCE_RUN / "raw" / "capture.mkv"
DEFAULT_CAPTURE_CONTRACT = DEFAULT_SOURCE_RUN / "capture" / "contract.json"
DEFAULT_NARRATION_ROOT = PROMO_ROOT / "runs" / "run-20260902T-full-master-tts-a4" / "narration"
DEFAULT_FFMPEG = Path(r"C:\ffmpeg\bin\ffmpeg.exe")
DEFAULT_FFPROBE = Path(r"C:\ffmpeg\bin\ffprobe.exe")

# Small, static project inputs are snapshotted into every preview batch.  The
# large raw capture and narration MP3s remain external immutable inputs and
# are bound by bytes/SHA-256 in the lineage records below.
PROJECT_SNAPSHOT_PATHS: tuple[Path, ...] = (
    Path("project.json"),
    Path("preset.json"),
    Path("storyboard.json"),
    Path("capture-settings.json"),
    Path("full-master-script.json"),
    Path("variants") / "hero-60.json",
    Path("variants") / "cut-30.json",
    Path("variants") / "cut-15.json",
)

# Each tuple is (source shot, source cue, output segment duration).  The cue
# files are copied by reference, never regenerated.  A short final segment may
# intentionally have no cue: clipping a spoken file at an arbitrary boundary
# is less auditable than carrying the final visual with game audio only.
VARIANT_SPECS: "OrderedDict[str, tuple[tuple[str, str | None, float], ...]]" = OrderedDict(
    (
        (
            "hero-60",
            (
                ("S01-identity", "S01-01", 10.0),
                ("S03-cough", "S03-01", 12.0),
                ("S05-drain", "S05-01", 12.0),
                ("S09-unified-field", "S09-01", 14.0),
                ("S10-finale", "S10-01", 12.0),
            ),
        ),
        (
            "cut-30",
            (
                ("S01-identity", "S01-01", 9.0),
                ("S03-cough", "S03-01", 10.0),
                ("S10-finale", "S10-01", 11.0),
            ),
        ),
        (
            "cut-15",
            (
                # Keep the 15-second bumper's spoken line intact (8.496 s)
                # and use a silent finale tag for the remaining six seconds.
                ("S01-identity", "S01-01", 9.0),
                ("S10-finale", None, 6.0),
            ),
        ),
    )
)


class PreviewVariantError(ValueError):
    """The source batch or derived preview EDL is not safely consumable."""


def _renderer_module() -> Any:
    """Import the sibling full-master producer without package side effects."""

    if str(PROMO_ROOT) not in sys.path:
        sys.path.insert(0, str(PROMO_ROOT))
    try:
        import render_full_master as renderer  # type: ignore
    except ImportError as exc:  # pragma: no cover - installation failure
        raise PreviewVariantError(f"full-master renderer is unavailable: {exc}") from exc
    return renderer


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreviewVariantError(f"could not read {label} {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise PreviewVariantError(f"{label} root must be an object")
    return value


def _write_json_new(path: Path, payload: Mapping[str, Any]) -> None:
    """Write one newly-created sidecar; never replace an existing byte."""

    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    # Use exclusive creation as well as the preflight existence check.  The
    # latter gives a friendly error for the common case; ``xb`` closes the
    # small race where another attempt creates the sidecar between checks.
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to overwrite existing preview artifact: {path}") from exc


def _record(renderer: Any, path: Path) -> dict[str, Any]:
    """Use the renderer's content-addressing helper for small sidecars."""

    return dict(renderer.file_record(path))


def _snapshot_project_config(renderer: Any, batch_root: Path) -> tuple[dict[str, Any], ...]:
    """Copy small project configuration bytes into a fresh batch.

    A snapshot makes a later review independent of mutable working-tree
    config.  It intentionally excludes raw media, credentials, and runtime
    caches; those stay content-addressed external inputs.
    """

    destination_root = batch_root / "notes" / "project-config"
    records: list[dict[str, Any]] = []
    for relative in PROJECT_SNAPSHOT_PATHS:
        source = (PROMO_ROOT / relative).resolve()
        if not source.is_file():
            raise PreviewVariantError(f"project config snapshot source is missing: {source}")
        destination = destination_root / relative
        if destination.exists():
            raise FileExistsError(f"refusing to overwrite project config snapshot: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        records.append(
            {
                "relative_path": relative.as_posix(),
                "source": _record(renderer, source),
                "snapshot": _record(renderer, destination),
            }
        )
    return tuple(records)


def _narration_records(
    renderer: Any,
    narration_root: Path,
    edl_payloads: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Content-address every selected MP3 in the pinned TTS batch."""

    names: set[str] = set()
    for payload in edl_payloads.values():
        for cue in payload.get("cues", []):
            if isinstance(cue, Mapping):
                name = cue.get("file")
                if isinstance(name, str) and name:
                    names.add(name)
    records: list[dict[str, Any]] = []
    for name in sorted(names):
        candidate = (narration_root / Path(name)).resolve()
        try:
            candidate.relative_to(narration_root.resolve())
        except ValueError as exc:
            raise PreviewVariantError(f"narration path escapes root: {name}") from exc
        if not candidate.is_file():
            raise PreviewVariantError(f"selected narration file is missing: {candidate}")
        records.append({"file": name, "artifact": _record(renderer, candidate)})
    return tuple(records)


def _narration_batch_record(renderer: Any, narration_root: Path) -> dict[str, Any]:
    """Require the pinned TTS manifest to be Xiaoxiao/no-BGM."""

    manifest_path = narration_root.parent / "logs" / "full-master-narration-manifest.json"
    if not manifest_path.is_file():
        raise PreviewVariantError(f"narration batch manifest is missing: {manifest_path}")
    payload = _read_json(manifest_path, "narration batch manifest")
    policy = payload.get("policy")
    if not isinstance(policy, Mapping):
        raise PreviewVariantError("narration batch manifest has no policy object")
    if policy.get("voice") != "zh-CN-XiaoxiaoNeural":
        raise PreviewVariantError(
            "preview requires zh-CN-XiaoxiaoNeural narration; "
            f"manifest declares {policy.get('voice')!r}"
        )
    if policy.get("include_bgm") is not False:
        raise PreviewVariantError("preview narration batch must declare include_bgm=false")
    run_id = payload.get("run_id")
    expected_run_id = narration_root.parent.name
    if not isinstance(run_id, str) or not run_id:
        raise PreviewVariantError("narration batch manifest has no run_id")
    if run_id != expected_run_id:
        raise PreviewVariantError(
            "narration batch manifest run_id does not match narration root: "
            f"manifest={run_id!r}, root={expected_run_id!r}"
        )
    summary = payload.get("summary")
    if isinstance(summary, Mapping) and summary.get("failed", 0) not in {0, None}:
        raise PreviewVariantError("preview narration batch contains failed cue generations")
    return {
        "run_id": run_id,
        "manifest": _record(renderer, manifest_path),
        "policy": {
            "voice": policy.get("voice"),
            "include_bgm": policy.get("include_bgm"),
            "provider": policy.get("provider"),
        },
    }


def _raw_record_from_binding(raw: Path, binding: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the already-verified contract binding without rehashing raw."""

    row = dict(binding)
    row["path"] = raw.resolve().as_posix()
    # ``load_capture_binding`` has verified these exact values before this
    # function is called.  Keep both the contract-relative and absolute path.
    row["relative_contract_path"] = str(binding.get("path", "raw/capture.mkv"))
    return row


def _source_maps(source_payload: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    segments = source_payload.get("segments")
    cues = source_payload.get("cues")
    if not isinstance(segments, list) or not segments:
        raise PreviewVariantError("source EDL has no segments")
    if not isinstance(cues, list):
        raise PreviewVariantError("source EDL cues must be an array")
    by_shot: dict[str, Mapping[str, Any]] = {}
    by_cue: dict[str, Mapping[str, Any]] = {}
    for row in segments:
        if not isinstance(row, Mapping):
            raise PreviewVariantError("source EDL contains a malformed segment")
        shot = str(row.get("shot_id", ""))
        if not shot or shot in by_shot:
            raise PreviewVariantError(f"source EDL has duplicate/empty shot {shot!r}")
        by_shot[shot] = row
    for row in cues:
        if not isinstance(row, Mapping):
            raise PreviewVariantError("source EDL contains a malformed cue")
        cue_id = str(row.get("cue_id", ""))
        if not cue_id or cue_id in by_cue:
            raise PreviewVariantError(f"source EDL has duplicate/empty cue {cue_id!r}")
        by_cue[cue_id] = row
    return by_shot, by_cue


def _validate_relative_file_name(value: str, label: str) -> str:
    """Apply the same portable relative-path rule as the EDL loader."""

    if not value or "\\" in value or "\x00" in value:
        raise PreviewVariantError(f"{label} must be a normalized relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(":" in part for part in path.parts)
        or path.as_posix() != value
    ):
        raise PreviewVariantError(f"{label} must be a normalized relative path")
    return value


def derive_variant_edl(
    source_payload: Mapping[str, Any],
    *,
    variant_id: str,
    narration_root_label: str,
    source_edl_record: Mapping[str, Any] | None = None,
    source_batch_label: str | None = None,
) -> dict[str, Any]:
    """Derive one explicit short EDL from the canonical full-master EDL.

    Source timestamps, span IDs, provenance and bilingual text are copied from
    the source EDL.  Only the editorial window and timeline IDs change.  This
    makes accidental drift to an unrelated capture or narration batch easy to
    detect in review.
    """

    if variant_id not in VARIANT_SPECS:
        raise PreviewVariantError(f"unknown preview variant {variant_id!r}")
    if source_payload.get("kind") != "vivhite_promo_full_master_edl":
        raise PreviewVariantError("source EDL kind must be vivhite_promo_full_master_edl")
    if source_payload.get("schema_version") != 1:
        raise PreviewVariantError("source EDL schema_version must be 1")
    source_by_shot, source_by_cue = _source_maps(source_payload)
    rows: list[dict[str, Any]] = []
    cues: list[dict[str, Any]] = []
    segment_bindings: list[dict[str, Any]] = []
    cursor = 0.0
    used_cues: set[str] = set()
    for index, (shot_id, cue_id, duration) in enumerate(VARIANT_SPECS[variant_id], 1):
        if not math.isfinite(duration) or duration <= 0:
            raise PreviewVariantError(f"{variant_id} has invalid segment duration")
        source = source_by_shot.get(shot_id)
        if source is None:
            raise PreviewVariantError(f"source EDL lacks shot {shot_id!r}")
        try:
            source_start = float(source["source_start_seconds"])
            source_duration = float(source["duration_seconds"])
        except (TypeError, ValueError, KeyError) as exc:
            raise PreviewVariantError(f"source segment {shot_id!r} has invalid geometry") from exc
        if (
            not math.isfinite(source_start)
            or source_start < 0
            or not math.isfinite(source_duration)
            or source_duration <= 0
        ):
            raise PreviewVariantError(f"source segment {shot_id!r} has non-finite geometry")
        if duration > source_duration + 1e-6:
            raise PreviewVariantError(
                f"{variant_id} segment {shot_id!r} ({duration:g}s) exceeds source window ({source_duration:g}s)"
            )
        span_id = source.get("span_id")
        provenance = str(source.get("provenance", ""))
        if not isinstance(span_id, str) or not span_id:
            raise PreviewVariantError(f"source segment {shot_id!r} lacks an explicit span_id")
        if provenance not in {"natural", "staged"}:
            raise PreviewVariantError(f"source segment {shot_id!r} has invalid provenance")
        segment_id = f"{variant_id.replace('-', '_')}-seg-{index:02d}"
        rows.append(
            {
                "segment_id": segment_id,
                "shot_id": shot_id,
                "source_start_seconds": round(source_start, 6),
                "duration_seconds": round(float(duration), 6),
                "provenance": provenance,
                "span_id": span_id,
            }
        )
        segment_bindings.append(
            {
                "segment_id": segment_id,
                "source_segment_id": source.get("segment_id"),
                "shot_id": shot_id,
                "source_start_seconds": source_start,
                "source_duration_seconds": source_duration,
                "span_id": span_id,
                "provenance": provenance,
            }
        )
        if cue_id is not None:
            if cue_id in used_cues:
                raise PreviewVariantError(f"duplicate selected cue {cue_id!r}")
            source_cue = source_by_cue.get(cue_id)
            if source_cue is None:
                raise PreviewVariantError(f"source EDL lacks cue {cue_id!r}")
            if str(source_cue.get("segment_id")) != str(source.get("segment_id")):
                raise PreviewVariantError(
                    f"cue {cue_id!r} is not bound to source shot {shot_id!r}"
                )
            file_name = source_cue.get("file")
            zh = source_cue.get("subtitle_zh")
            en = source_cue.get("subtitle_en")
            if not all(isinstance(value, str) and value.strip() for value in (file_name, zh, en)):
                raise PreviewVariantError(f"cue {cue_id!r} has incomplete bilingual metadata")
            file_name = _validate_relative_file_name(file_name, f"cue {cue_id!r}.file")
            source_window = source_cue.get("subtitle_duration_seconds")
            try:
                subtitle_window = float(source_window) if source_window is not None else float(duration)
            except (TypeError, ValueError) as exc:
                raise PreviewVariantError(f"cue {cue_id!r} has invalid subtitle duration") from exc
            # The renderer clips the actual spoken stream after ffprobe.  Cap
            # the authored subtitle window too, so the EDL itself never asks a
            # short segment to display text outside its boundary.
            subtitle_window = min(max(0.1, subtitle_window), float(duration))
            cues.append(
                {
                    "cue_id": f"{variant_id.replace('-', '_')}-{cue_id}",
                    "segment_id": segment_id,
                    "offset_seconds": 0.0,
                    "file": file_name.replace("\\", "/"),
                    "subtitle_zh": zh,
                    "subtitle_en": en,
                    "subtitle_duration_seconds": round(subtitle_window, 6),
                }
            )
            used_cues.add(cue_id)
        cursor += float(duration)
    target = round(cursor, 6)
    expected = {"hero-60": 60.0, "cut-30": 30.0, "cut-15": 15.0}[variant_id]
    if not math.isclose(target, expected, rel_tol=0.0, abs_tol=1e-6):
        raise PreviewVariantError(f"{variant_id} duration is {target:g}s, expected {expected:g}s")
    authoring: dict[str, Any] = {
        "mode": "derived-from-full-master-edl",
        "source_label": source_batch_label or str(source_payload.get("source_label", "full-master")),
        "narration_root": narration_root_label.replace("\\", "/"),
        "narration_voice": "zh-CN-XiaoxiaoNeural",
        "include_bgm": False,
        "source_segment_bindings": segment_bindings,
        "selected_source_cues": sorted(used_cues),
        "semantic_audit": "pending",
        "signoff": False,
    }
    if source_edl_record is not None:
        authoring["source_edl"] = dict(source_edl_record)
    return {
        "schema_version": 1,
        "kind": "vivhite_promo_full_master_edl",
        "source_label": f"{source_batch_label or source_payload.get('source_label', 'full-master')}-derived-{variant_id}; semantic audit pending",
        "target_duration_seconds": expected,
        "segments": rows,
        "cues": cues,
        "authoring": authoring,
    }


def _fresh_batch_root(raw: Path, requested: Path | None) -> Path:
    renderer = _renderer_module()
    source_run = renderer._source_run_root(raw)
    if requested is not None:
        selected = requested.expanduser().resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = source_run.parent / f"run-{stamp}-preview-full-master-a1"
        selected = base
        suffix = 1
        while selected.exists():
            suffix += 1
            selected = source_run.parent / f"run-{stamp}-preview-full-master-a{suffix}"
    if selected.parent != source_run.parent:
        raise PreviewVariantError(
            "preview batch must be a fresh sibling of the source run: "
            f"expected parent {source_run.parent}, got {selected.parent}"
        )
    renderer.validate_output_root(raw, selected)
    return selected


def _ensure_failure_dirs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name in ("logs", "review", "renders", "subtitles"):
        (root / name).mkdir(parents=True, exist_ok=True)


def _write_failure(root: Path, variant_id: str, exc: BaseException) -> None:
    _ensure_failure_dirs(root)
    payload = {
        "schema_version": 1,
        "kind": "vivhite_promo_preview_failure",
        "status": "incomplete",
        "variant_id": variant_id,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": traceback.format_exc(),
        "preservation": {
            "partial_and_process_logs_retained": True,
            "retry_policy": "new batch/run; never overwrite this attempt",
        },
        "audits": {"technical": "pending", "semantic": "pending", "human_review": "pending", "signoff": False},
    }
    _write_json_new(root / "review" / "preview-failure.json", payload)
    _write_json_new(root / "logs" / "preview-failure.json", payload)


def _normalise_renderer_manifest(renderer: Any, child: Path, variant_id: str, edl_record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Preserve and correct the renderer's preliminary manifest wording."""

    path = child / "review" / "render-manifest.json"
    if not path.is_file():
        return None
    original = child / "review" / "renderer-render-manifest.json"
    if not original.exists():
        shutil.copyfile(path, original)
    payload = _read_json(path, "renderer manifest")
    mutable = dict(payload)
    audits = dict(mutable.get("audits", {})) if isinstance(mutable.get("audits"), Mapping) else {}
    audits["human_review"] = "pending"
    audits["semantic"] = "pending"
    audits["signoff"] = False
    audits["export_approval"] = False
    mutable["audits"] = audits
    # Keep the preview contract explicit even if a future renderer adds or
    # changes audio-policy fields.  The source renderer's manifest is retained
    # byte-for-byte beside this normalized copy, but only this copy is used as
    # the preview batch's downstream metadata.
    narration = dict(mutable.get("narration", {})) if isinstance(mutable.get("narration"), Mapping) else {}
    narration["voice"] = "zh-CN-XiaoxiaoNeural"
    narration["external_bgm"] = False
    mutable["narration"] = narration
    audio_policy = dict(mutable.get("audio_policy", {})) if isinstance(mutable.get("audio_policy"), Mapping) else {}
    audio_policy["include_bgm"] = False
    mutable["audio_policy"] = audio_policy
    mutable["status"] = "preliminary"
    mutable["run_role"] = "preview-variant-draft"
    mutable["variant_id"] = variant_id
    mutable["variant_edl"] = dict(edl_record)
    mutable["warning"] = (
        "Preview draft only: technical rendering does not certify semantic claims, "
        "human review, signoff, or publishing approval."
    )
    path.write_text(json.dumps(mutable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": renderer.sha256_file(path),
        "renderer_original": _record(renderer, original),
    }


def _copy_alias(renderer: Any, child: Path, variant_id: str) -> dict[str, Any] | None:
    source = child / "renders" / "full-master.mp4"
    if not source.is_file():
        return None
    alias = child / "renders" / f"vivhite-player-{variant_id}.mp4"
    if alias.exists():
        raise FileExistsError(f"refusing to overwrite preview alias: {alias}")
    shutil.copyfile(source, alias)
    subtitle = child / "subtitles" / "full-master.bilingual.ass"
    if subtitle.is_file():
        subtitle_alias = child / "subtitles" / f"vivhite-player-{variant_id}.bilingual.ass"
        if not subtitle_alias.exists():
            shutil.copyfile(subtitle, subtitle_alias)
    return _record(renderer, alias)


def _preserve_partial(renderer: Any, child: Path) -> dict[str, Any] | None:
    """Keep a byte-identical partial sidecar after successful promotion.

    ``render_full_master`` promotes its process partial with ``os.replace``
    after a successful encode.  A preview attempt still needs a durable
    partial/provenance slot for audit tooling, so copy (never move or
    overwrite) the promoted bytes back to the conventional partial name.
    Failed encodes already leave the real partial in place and are returned
    unchanged.
    """

    final = child / "renders" / "full-master.mp4"
    partial = child / "renders" / "full-master.partial.mp4"
    if partial.is_file():
        return _record(renderer, partial)
    if not final.is_file():
        return None
    if partial.exists():
        raise FileExistsError(f"refusing to overwrite existing partial artifact: {partial}")
    shutil.copyfile(final, partial)
    return _record(renderer, partial)


def render_batch(
    *,
    raw: Path,
    capture_contract_path: Path,
    source_edl_path: Path,
    narration_root: Path,
    output_root: Path,
    ffmpeg: Path,
    ffprobe: Path,
    xar_source: Path | None = None,
    variant_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Create one fresh batch and render selected variants."""

    renderer = _renderer_module()
    raw = raw.expanduser().resolve()
    capture_contract_path = capture_contract_path.expanduser().resolve()
    source_edl_path = source_edl_path.expanduser().resolve()
    narration_root = narration_root.expanduser().resolve()
    ffmpeg = ffmpeg.expanduser().resolve()
    ffprobe = ffprobe.expanduser().resolve()
    for path, label in (
        (raw, "raw capture"),
        (capture_contract_path, "capture contract"),
        (source_edl_path, "source EDL"),
        (narration_root, "narration root"),
        (ffmpeg, "ffmpeg"),
        (ffprobe, "ffprobe"),
    ):
        if not path.exists() or (path.is_dir() and label not in {"narration root"}) or (label == "narration root" and not path.is_dir()):
            raise PreviewVariantError(f"{label} is missing: {path}")
    source_payload = _read_json(source_edl_path, "source EDL")
    # Validate canonical source EDL before deriving any bytes.  This catches a
    # stale/foreign full-master file without touching the output root.
    renderer.load_edl(source_edl_path)
    narration_batch = _narration_batch_record(renderer, narration_root)
    narration_batch_id = str(narration_batch.get("run_id") or narration_root.parent.name)
    selected = tuple(variant_ids) if variant_ids is not None else tuple(VARIANT_SPECS)
    if not selected:
        raise PreviewVariantError("at least one preview variant is required")
    unknown = [item for item in selected if item not in VARIANT_SPECS]
    if unknown:
        raise PreviewVariantError(f"unknown preview variants: {unknown}")
    if len(set(selected)) != len(selected):
        raise PreviewVariantError("preview variants must be unique")

    # Hash-bound load is deliberately done once before creating the new run.
    # It verifies the 3.6 GB raw bytes and project identity; the renderer then
    # rechecks the same object at every render boundary.
    capture_contract, capture_provenance = renderer._load_capture_binding(raw, capture_contract_path)
    if xar_source is not None:
        os.environ["XAR_PROMO_TOOLCHAIN_SOURCE"] = str(xar_source.expanduser().resolve())
    xar_provenance = renderer._xar_provenance()
    source_edl_record = _record(renderer, source_edl_path)
    contract_record = _record(renderer, capture_contract_path)
    raw_binding = _raw_record_from_binding(raw, capture_provenance.get("raw_binding", {}))
    batch_root = output_root.expanduser().resolve()
    # Re-run sibling/non-existence checks immediately before mkdir to close the
    # operator race between preflight and actual writes.
    renderer.validate_output_root(raw, batch_root)
    batch_root.mkdir(parents=True, exist_ok=False)
    (batch_root / "notes").mkdir()
    project_config_snapshot = _snapshot_project_config(renderer, batch_root)
    lineage = {
        "schema_version": 1,
        "kind": "vivhite_promo_preview_batch_lineage",
        "status": "preliminary",
        "batch_root": batch_root.as_posix(),
        "source_full_master_run": renderer._source_run_root(raw).as_posix(),
        "source_edl": source_edl_record,
        "raw_capture": raw_binding,
        "capture_contract": contract_record,
        "capture_provenance": dict(capture_provenance),
        "narration_root": narration_root.as_posix(),
        "narration_batch": narration_batch_id,
        "narration_batch_manifest": narration_batch,
        "voice": "zh-CN-XiaoxiaoNeural",
        "include_bgm": False,
        "copy_policy": "raw/contract/narration remain immutable external inputs; outputs are fresh sibling attempts",
        "project_config_snapshot": list(project_config_snapshot),
        "xar": xar_provenance,
        "audits": {"technical": "pending", "semantic": "pending", "human_review": "pending", "signoff": False, "export_approval": False},
    }
    plan: dict[str, Any] = {
        "schema_version": 1,
        "kind": "vivhite_promo_preview_batch_plan",
        "status": "preliminary",
        "source_full_master_run": renderer._source_run_root(raw).as_posix(),
        "source_edl": source_edl_record,
        "raw_capture": raw_binding,
        "capture_contract": contract_record,
        "voice": "zh-CN-XiaoxiaoNeural",
        "include_bgm": False,
        "project_config_snapshot": list(project_config_snapshot),
        "narration_batch_manifest": narration_batch,
        "variants": [],
        "xar": xar_provenance,
    }
    # Derive and persist all EDLs before launching any encoder.  A later
    # failure therefore leaves the exact editorial intent in the attempt.
    edl_paths: dict[str, Path] = {}
    edl_payloads: dict[str, Mapping[str, Any]] = {}
    for variant_id in selected:
        payload = derive_variant_edl(
            source_payload,
            variant_id=variant_id,
            narration_root_label=narration_root.as_posix(),
            source_edl_record=source_edl_record,
            source_batch_label=renderer._source_run_root(raw).name,
        )
        path = batch_root / "notes" / f"{variant_id}.edl.json"
        _write_json_new(path, payload)
        edl_paths[variant_id] = path
        edl_payloads[variant_id] = payload
        plan["variants"].append(
            {
                "variant_id": variant_id,
                "target_duration_seconds": payload["target_duration_seconds"],
                "edl": _record(renderer, path),
                "output_root": (batch_root / variant_id).as_posix(),
            }
        )
    narration_inputs = _narration_records(renderer, narration_root, edl_payloads)
    lineage["narration_inputs"] = list(narration_inputs)
    lineage["edls"] = [item for item in plan["variants"]]
    _write_json_new(batch_root / "notes" / "narration-inputs.json", {"schema_version": 1, "kind": "vivhite_promo_preview_narration_inputs", "voice": "zh-CN-XiaoxiaoNeural", "include_bgm": False, "inputs": list(narration_inputs)})
    _write_json_new(batch_root / "notes" / "source-lineage.json", lineage)
    plan["narration_inputs"] = list(narration_inputs)
    _write_json_new(batch_root / "notes" / "batch-plan.json", plan)

    results: list[dict[str, Any]] = []
    for variant_id in selected:
        child = batch_root / variant_id
        row: dict[str, Any] = {
            "variant_id": variant_id,
            "target_duration_seconds": edl_payloads[variant_id]["target_duration_seconds"],
            "edl": _record(renderer, edl_paths[variant_id]),
            "status": "failed",
        }
        try:
            edl = renderer.load_edl(edl_paths[variant_id])
            render_result = renderer.render_full_master(
                raw=raw,
                output_root=child,
                edl=edl,
                narration_root=narration_root,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
                capture_contract_path=capture_contract_path,
                capture_contract=capture_contract,
                capture_provenance=capture_provenance,
                edl_path=edl_paths[variant_id],
            )
            row["renderer_result"] = render_result
            partial = _preserve_partial(renderer, child)
            if partial is not None:
                expected_bytes = render_result.get("bytes") if isinstance(render_result, Mapping) else None
                expected_sha = str(render_result.get("sha256", "")).upper() if isinstance(render_result, Mapping) else ""
                if expected_bytes is not None and (
                    partial.get("bytes") != expected_bytes
                    or str(partial.get("sha256", "")).upper() != expected_sha
                ):
                    raise PreviewVariantError(
                        f"{variant_id} partial bytes/hash differ from renderer result"
                    )
                row["partial_artifact"] = partial
            alias = _copy_alias(renderer, child, variant_id)
            if alias is not None:
                expected_bytes = render_result.get("bytes") if isinstance(render_result, Mapping) else None
                expected_sha = str(render_result.get("sha256", "")).upper() if isinstance(render_result, Mapping) else ""
                if expected_bytes is not None and (
                    alias.get("bytes") != expected_bytes
                    or str(alias.get("sha256", "")).upper() != expected_sha
                ):
                    raise PreviewVariantError(
                        f"{variant_id} alias bytes/hash differ from renderer result"
                    )
                row["deliverable_alias"] = alias
            normalized = _normalise_renderer_manifest(renderer, child, variant_id, row["edl"])
            if normalized is None:
                raise PreviewVariantError(
                    f"{variant_id} renderer did not produce a render manifest"
                )
            row["variant_manifest"] = normalized
            row["status"] = "preliminary-rendered"
        except Exception as exc:  # noqa: BLE001 - preserve every failed attempt
            row["error_type"] = type(exc).__name__
            row["error"] = str(exc)
            try:
                _write_failure(child, variant_id, exc)
            except Exception as report_exc:  # pragma: no cover - disk failure
                row["failure_report_error"] = f"{type(report_exc).__name__}: {report_exc}"
            # Continue to the next independent variant while retaining this
            # child run; batch status below remains incomplete.
        results.append(row)

    # Verify all immutable inputs after the last encoder.  If this fails, the
    # batch remains preliminary/incomplete and no signoff/export field flips.
    post_error: str | None = None
    try:
        capture_contract.verify_unchanged()
        _record(renderer, capture_contract_path)
    except Exception as exc:  # noqa: BLE001
        post_error = f"{type(exc).__name__}: {exc}"
    all_rendered = post_error is None and all(item["status"] == "preliminary-rendered" for item in results)
    batch_manifest = {
        "schema_version": 1,
        "kind": "vivhite_promo_preview_batch",
        "status": "preliminary" if all_rendered else "incomplete",
        "source_full_master_run": renderer._source_run_root(raw).as_posix(),
        "raw_capture": raw_binding,
        "capture_contract": contract_record,
        "source_edl": source_edl_record,
        "narration": {
            "root": narration_root.as_posix(),
            "batch": narration_batch_id,
            "voice": "zh-CN-XiaoxiaoNeural",
            "include_bgm": False,
            "batch_manifest": narration_batch,
            "inputs": list(narration_inputs),
        },
        "project_config_snapshot": list(project_config_snapshot),
        "xar": xar_provenance,
        "variants": results,
        "post_render_input_check": "passed" if post_error is None else "failed: " + post_error,
        "audits": {
            "technical": "pending",
            "semantic": "pending",
            "human_review": "pending",
            "signoff": False,
            "export_approval": False,
        },
        "warning": "Preview drafts only; no semantic claims, human review, signoff, or publishing approval is asserted.",
        "preservation": {
            "new_run_required": True,
            "existing_runs_overwrite": False,
            "failed_partial_logs_retained": True,
        },
    }
    _write_json_new(batch_root / "batch-manifest.json", batch_manifest)
    run_manifest = {
        "schema_version": 1,
        "kind": "vivhite_promo_preview_run_manifest",
        "status": "preliminary" if all_rendered else "incomplete",
        "run_id": batch_root.name,
        "attempt": 1,
        "stage": "preview-draft",
        "state": "preview-draft-preserved" if all_rendered else "preview-draft-incomplete",
        "batch_root": batch_root.as_posix(),
        "source_full_master_run": renderer._source_run_root(raw).as_posix(),
        "raw_capture": raw_binding,
        "capture_contract": contract_record,
        "source_edl": source_edl_record,
        "project_config_snapshot": list(project_config_snapshot),
        "narration": {
            "batch": narration_batch_id,
            "batch_manifest": narration_batch,
            "voice": "zh-CN-XiaoxiaoNeural",
            "include_bgm": False,
            "inputs": list(narration_inputs),
        },
        "variants": results,
        "xar": xar_provenance,
        "gates": {
            "capture_contract": "passed",
            "technical_audit": "pending",
            "semantic_audit": "pending",
            "human_review": "pending",
            "signoff": False,
            "export": False,
        },
        "preservation": {
            "retry_policy": "new batch/run/attempt; never overwrite this directory",
            "failed_and_partial_artifacts_retained": True,
        },
        "warning": "Preview draft only; no semantic claim or publishing approval is asserted.",
    }
    _write_json_new(batch_root / "run-manifest.json", run_manifest)
    return {"output_root": batch_root.as_posix(), "status": batch_manifest["status"], "variants": results}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--capture-contract", type=Path, default=DEFAULT_CAPTURE_CONTRACT)
    parser.add_argument("--source-edl", type=Path, default=DEFAULT_SOURCE_EDL)
    parser.add_argument("--narration-root", type=Path, default=DEFAULT_NARRATION_ROOT)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--ffmpeg", type=Path, default=DEFAULT_FFMPEG)
    parser.add_argument("--ffprobe", type=Path, default=DEFAULT_FFPROBE)
    parser.add_argument("--xar-source", type=Path, default=None)
    parser.add_argument("--variant", dest="variants", action="append", choices=tuple(VARIANT_SPECS), help="render only this variant (repeatable)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw = args.raw.expanduser().resolve()
    output = _fresh_batch_root(raw, args.output_root)
    result = render_batch(
        raw=raw,
        capture_contract_path=args.capture_contract,
        source_edl_path=args.source_edl,
        narration_root=args.narration_root,
        output_root=output,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        xar_source=args.xar_source,
        variant_ids=args.variants,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "preliminary" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"preview variant batch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise


__all__ = [
    "DEFAULT_CAPTURE_CONTRACT",
    "DEFAULT_FFMPEG",
    "DEFAULT_FFPROBE",
    "DEFAULT_NARRATION_ROOT",
    "DEFAULT_RAW",
    "DEFAULT_SOURCE_EDL",
    "DEFAULT_SOURCE_RUN",
    "PreviewVariantError",
    "VARIANT_SPECS",
    "derive_variant_edl",
    "render_batch",
]
