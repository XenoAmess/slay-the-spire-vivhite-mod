"""Render preliminary short cuts from one hash-bound OBS capture.

This is intentionally a Vivhite-project producer, not an xAR command.  It
selects an edit window from a real capture, supplies project-owned narration
stems/subtitles, and delegates the deterministic audio/video render to xAR.
The output is always marked ``preliminary``: this helper never performs a
semantic claim audit, human review, signoff, or publish operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping


VOICE = "zh-CN-XiaoxiaoNeural"
FFMPEG_DEFAULT = Path(r"C:\ffmpeg\bin\ffmpeg.exe")
FFPROBE_DEFAULT = Path(r"C:\ffmpeg\bin\ffprobe.exe")
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_NARRATION_ROOT = PROJECT_ROOT / "runs" / "run-20260901T205757Z-tts4" / "narration"


# The edit window is deliberately a continuous, observed combat interval.  A
# later human edit may replace it with a multi-window EDL, but this first pass
# must not invent frames or pad a short take into a fake long master.
VARIANTS: dict[str, dict[str, Any]] = {
    "hero-60": {
        "duration": 60.0,
        "source_start": 1015.0,
        "cues": [
            (0.0, "S01-identity", "白绮，以魔法书写几何与星算。", "Vivhite, a mage who writes geometry and star calculus as magic."),
            (12.0, "S03-cough", "謦欬在牌面效果前支付生命；实际费用不会让她低于1点生命。", "Cough pays life before the card effect; the payment never takes her below 1 HP."),
            (24.0, "S05-drain", "攻击结算后，汲取按敌人的实际损失统一回收。", "After the attack resolves, Drain recovers the enemy's actual loss at once."),
            (36.0, "S09-unified-field", "不同体系在同一场战斗里寻找闭环。", "Different systems search for a closed loop in one fight."),
            (48.0, "S10-finale", "61张专属卡、三套构筑，白绮的魔法仍在生长。", "Sixty-one signature cards, three archetypes, and a mage that keeps growing."),
        ],
    },
    "cut-30": {
        "duration": 30.0,
        "source_start": 1015.0,
        "cues": [
            (0.0, "S01-identity", "白绮，以魔法书写几何与星算。", "Vivhite, a mage who writes geometry and star calculus as magic."),
            (10.0, "S03-cough", "謦欬在牌面效果前支付生命；实际费用不会让她低于1点生命。", "Cough pays life before the card effect; the payment never takes her below 1 HP."),
            (20.0, "S05-drain", "攻击结算后，汲取按敌人的实际损失统一回收。", "After the attack resolves, Drain recovers the enemy's actual loss at once."),
        ],
    },
    "cut-15": {
        "duration": 15.0,
        "source_start": 1018.0,
        "cues": [
            (0.0, "S03-cough", "謦欬先支付生命，再让牌面效果发生。", "Cough pays life first, then lets the card effect happen."),
            (7.5, "S05-drain", "汲取只回收敌人的实际损失。", "Drain recovers only the enemy's actual loss."),
        ],
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def file_record(path: Path, root: Path | None = None) -> dict[str, Any]:
    path = path.resolve()
    result: dict[str, Any] = {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if root is not None:
        try:
            result["relative_path"] = path.relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return result


def _source_run_root(raw: Path) -> Path:
    """Return the immutable source run directory containing ``raw``."""

    resolved = raw.expanduser().resolve()
    return (
        resolved.parent.parent
        if resolved.parent.name.casefold() == "raw"
        else resolved.parent
    )


def _is_within(path: Path, root: Path) -> bool:
    """Return whether ``path`` is ``root`` or one of its descendants."""

    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def validate_output_root(raw: Path, output_root: Path) -> None:
    """Reject output locations that could mutate or mix an old capture run."""

    source_run = _source_run_root(raw)
    selected = output_root.expanduser().resolve()
    if _is_within(selected, source_run):
        raise RuntimeError(
            "candidate output must be a new sibling run, not the source capture "
            f"run or one of its descendants: {selected}"
        )
    if selected.exists():
        raise FileExistsError(
            "refusing to reuse an existing candidate run directory; choose a new "
            f"attempt path: "
            f"{selected}"
        )


def infer_capture_contract_path(raw: Path) -> Path:
    """Find the one contract belonging to a raw file's run directory.

    A candidate render must be rooted in a hash-bound capture receipt.  The
    normal layout is ``<run>/raw/<media>`` plus ``<run>/capture/contract.json``;
    the other names cover the checked-in fixture and the first producer pass.
    Ambiguous or missing receipts are errors rather than reasons to render an
    unbound media file.
    """

    resolved = raw.expanduser().resolve()
    run_root = _source_run_root(resolved)
    candidates = (
        run_root / "capture" / "contract.json",
        run_root / "contract.json",
        run_root / "partial-candidate-contract.json",
    )
    existing = tuple(path for path in candidates if path.is_file())
    if not existing:
        expected = ", ".join(str(path) for path in candidates)
        raise FileNotFoundError(
            "no hash-bound capture contract found for raw media; checked: " + expected
        )
    if len(existing) > 1:
        raise RuntimeError(
            "multiple capture contracts found for raw media; pass --capture-contract explicitly: "
            + ", ".join(str(path) for path in existing)
        )
    return existing[0].resolve()


def load_capture_binding(raw: Path, contract_path: Path) -> tuple[Any, dict[str, Any]]:
    """Load and verify one project capture contract against ``raw`` bytes."""

    try:
        from vivhite_promo.capture_contract import load_capture_contract
        from vivhite_promo.adapter import VivhiteAdapter, VivhiteAdapterError
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Vivhite capture-contract module is unavailable; run from tools/promo"
        ) from exc

    raw = raw.expanduser().resolve()
    contract_path = contract_path.expanduser().resolve()
    if not contract_path.is_file():
        raise FileNotFoundError(f"capture contract is missing: {contract_path}")
    contract_root = (
        contract_path.parent.parent
        if contract_path.parent.name.casefold() == "capture"
        else contract_path.parent
    )
    contract = load_capture_contract(
        contract_path,
        artifact_root=contract_root,
        verify_files=True,
    )
    bound_raw = Path(contract.raw_capture.path).expanduser().resolve()
    if bound_raw != raw:
        raise RuntimeError(
            "capture contract raw path does not match --raw: "
            f"contract={bound_raw}, raw={raw}"
        )
    # Recheck every referenced byte immediately before planning.  This closes
    # the race between the loader's hash check and the first FFmpeg input.
    contract.verify_unchanged()
    try:
        # Keep the project-side identity gate ahead of FFmpeg. This checks
        # renderer/version/overlay policy without running semantic validators
        # or interpreting any claim text.
        VivhiteAdapter().validate_identity(contract.project_context)
    except VivhiteAdapterError as exc:
        raise RuntimeError(f"capture project identity is not consumable: {exc}") from exc
    run_root = _source_run_root(raw)
    if run_root.name.startswith("run-") and contract.run_id != run_root.name:
        raise RuntimeError(
            "capture contract run_id does not match raw run directory: "
            f"contract={contract.run_id!r}, directory={run_root.name!r}"
        )
    metadata = {
        "contract": file_record(contract_path, contract_root),
        "run_id": contract.run_id,
        "producer_id": contract.producer_id,
        "producer_version": contract.capture_receipt.producer_version,
        "artifact_root": contract_root.as_posix(),
        "raw_binding": contract.raw_capture.to_mapping(),
        "verification": "hash-bound-and-unchanged-before-render",
    }
    _verify_file_record(contract_path, metadata["contract"], "capture contract")
    return contract, metadata


def _verify_file_record(path: Path, expected: Mapping[str, Any], label: str) -> None:
    """Rehash a sidecar/input record and fail closed on mutation."""

    try:
        actual = file_record(path)
    except OSError as exc:
        raise RuntimeError(f"{label} is missing or unreadable: {path}") from exc
    expected_bytes = expected.get("bytes")
    expected_sha = str(expected.get("sha256", "")).upper()
    if actual["bytes"] != expected_bytes or actual["sha256"] != expected_sha:
        raise RuntimeError(
            f"{label} changed during candidate render: "
            f"expected {expected_bytes} bytes/{expected_sha}, got "
            f"{actual['bytes']} bytes/{actual['sha256']}"
        )


def verify_render_inputs(
    *,
    capture_contract: Any,
    contract_path: Path,
    capture_provenance: Mapping[str, Any],
    narration_inputs: Iterable[Mapping[str, Any]],
    tool_inputs: Mapping[str, Mapping[str, Any]],
) -> None:
    """Verify every immutable input at each render boundary."""

    capture_contract.verify_unchanged()
    _verify_file_record(contract_path, capture_provenance["contract"], "capture contract")
    for record in narration_inputs:
        _verify_file_record(Path(str(record["path"])), record, "narration input")
    for tool_id, record in tool_inputs.items():
        _verify_file_record(Path(str(record["path"])), record, f"{tool_id} executable")


def narration_input_paths(narration_root: Path) -> dict[str, Path]:
    """Resolve every narration input once for the whole candidate batch."""

    paths: dict[str, Path] = {}
    for spec in VARIANTS.values():
        for _delay, shot_id, _zh, _en in spec["cues"]:
            path = (narration_root / f"{shot_id}.mp3").resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            paths[shot_id] = path
    return paths


def narration_input_records(narration_root: Path) -> tuple[dict[str, Any], ...]:
    """Snapshot every narration input used by the selected variants."""

    paths = narration_input_paths(narration_root)
    return tuple(file_record(path) for path in paths.values())


def containing_capture_span(contract: Any, start_seconds: float, duration_seconds: float) -> Any:
    """Return the narrowest clean span containing a requested edit window."""

    start = float(start_seconds)
    duration = float(duration_seconds)
    end = start + duration
    if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
        raise ValueError("capture edit window must have a finite non-negative start and positive duration")
    spans = tuple(
        span
        for span in contract.clean_spans
        if span.begin_seconds <= start + 1e-9 and end <= span.end_seconds + 1e-9
    )
    if not spans:
        raise RuntimeError(
            f"edit window {start:g}..{end:g}s is not contained in a hash-bound clean span"
        )
    return min(
        spans,
        key=lambda span: (span.end_seconds - span.begin_seconds, span.begin_seconds, span.span_id),
    )


def ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100.0)))
    hours, rem = divmod(centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, hundredths = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{hundredths:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chinese,Microsoft YaHei,46,&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,140,140,122,1
Style: English,Arial,34,&H00D8E8FF,&H00D8E8FF,&H80000000,&H80000000,0,1,0,0,100,100,0,0,1,2,1,2,140,140,76,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(path: Path, cues: Iterable[tuple[float, str, str, str]], duration: float) -> None:
    rows = list(cues)
    lines = [ASS_HEADER]
    for index, (start, _shot, zh, en) in enumerate(rows):
        end = rows[index + 1][0] if index + 1 < len(rows) else duration
        # Leave a five-frame guard at the end of each subtitle segment.  The
        # guard keeps the final rendered frame of one cue clear before the
        # next cue begins, even when a source clip ends on a frame boundary.
        safe_end = max(start + 0.1, end - (5.0 / 60.0))
        lines.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(safe_end)},Chinese,,0,0,122,,"
            f"{ass_escape(zh)}\\N{{\\i1}}{ass_escape(en)}{{\\i0}}\n"
        )
    path.write_text("".join(lines), encoding="utf-8", newline="\n")


def load_xar(source: Path | None) -> dict[str, Any]:
    selected = source
    if selected is None:
        env = os.environ.get("XAR_PROMO_TOOLCHAIN_SOURCE")
        selected = Path(env) if env else Path(r"G:\workspace\xar_promo_toolchain")
    src = selected.expanduser().resolve() / "src"
    if not src.is_dir():
        raise RuntimeError(f"xAR source directory is missing: {src}")
    # This helper is normally a fresh CLI process, but fail closed when an
    # embedding process already imported xAR from another checkout.  A stale
    # parent or submodule would make the recorded commit differ from the code
    # actually used by the planner.
    for module_name, module in tuple(sys.modules.items()):
        if module_name != "xar_promo" and not module_name.startswith("xar_promo."):
            continue
        module_file = getattr(module, "__file__", None)
        if module_file and not _is_within(Path(module_file), src):
            raise RuntimeError(
                "xAR modules are already loaded from another source; start a "
                "fresh candidate-render process"
            )
    sys.path.insert(0, str(src))
    commit: str | None = None
    try:
        completed = subprocess.run(
            ["git", "-C", str(src.parent), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode == 0:
            candidate = completed.stdout.strip()
            if candidate:
                commit = candidate
    except OSError:
        pass
    try:
        import xar_promo

        version = getattr(xar_promo, "__version__", None)
    except Exception:
        version = None
    return {
        "source_root": src.parent.as_posix(),
        "git_commit": commit,
        "package_version": version,
    }


def probe(path: Path, ffprobe: Path) -> dict[str, Any]:
    argv = [
        str(ffprobe),
        "-v", "error",
        "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,pix_fmt,sample_rate,channels,channel_layout",
        "-of", "json",
        str(path),
    ]
    completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed ({completed.returncode}): {completed.stderr[-1000:]}")
    return {"argv": argv, "result": json.loads(completed.stdout)}


def run_variant(
    *,
    variant_id: str,
    spec: dict[str, Any],
    raw: Path,
    narration_root: Path,
    output_root: Path,
    ffmpeg: Path,
    ffprobe: Path,
    capture_contract: Any,
    capture_provenance: Mapping[str, Any],
    narration_paths: Mapping[str, Path],
    xar_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    from xar_promo.audio import AudioMixSpec, AudioStem, DuckWindow
    from xar_promo.render import RenderOptions, execute_render_plan, plan_render

    duration = float(spec["duration"])
    source_start = float(spec["source_start"])
    capture_span = containing_capture_span(capture_contract, source_start, duration)
    capture_span_provenance = {
        "span_id": capture_span.span_id,
        "begin_seconds": capture_span.begin_seconds,
        "end_seconds": capture_span.end_seconds,
        "provenance": capture_span.provenance,
    }
    variant_root = output_root / variant_id
    if variant_root.exists() and any(variant_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty variant directory: {variant_root}")
    variant_root.mkdir(parents=True, exist_ok=True)
    (variant_root / "logs").mkdir()
    (variant_root / "review").mkdir()
    (variant_root / "renders").mkdir()
    ass_path = variant_root / "subtitles" / f"{variant_id}.bilingual.ass"
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    write_ass(ass_path, spec["cues"], duration)

    narration_stems: list[AudioStem] = []
    narration_records: list[dict[str, Any]] = []
    duck_windows: list[DuckWindow] = []
    cues = list(spec["cues"])
    for index, (delay, shot_id, _zh, _en) in enumerate(cues):
        try:
            cue_path = narration_paths[shot_id]
        except KeyError as exc:
            raise FileNotFoundError(narration_root / f"{shot_id}.mp3") from exc
        if not cue_path.is_file():
            raise FileNotFoundError(cue_path)
        next_start = cues[index + 1][0] if index + 1 < len(cues) else duration
        cue_window = max(0.1, next_start - delay)
        narration_stems.append(
            AudioStem(
                stem_id=f"narration-{index + 1}",
                path=cue_path,
                delay_seconds=float(delay),
                trim_duration_seconds=cue_window,
                fade_in_seconds=0.03,
                fade_out_seconds=0.05,
            )
        )
        narration_records.append({"shot_id": shot_id, "delay_seconds": delay, "artifact": file_record(cue_path)})
        duck_windows.append(DuckWindow(float(delay), min(duration, float(next_start)), -6.0))

    game_stem = AudioStem(
        stem_id="game",
        path=raw.resolve(),
        trim_start_seconds=source_start,
        trim_duration_seconds=duration,
        gain_db=6.0,
        duck_windows=tuple(duck_windows),
    )
    mix = AudioMixSpec(
        stems=(game_stem, *narration_stems),
        duration_seconds=duration,
        sample_rate=48_000,
        channels=2,
        # Six simultaneous inputs otherwise trigger FFmpeg's default
        # ``amix=normalize=1`` attenuation.  The project supplies explicit
        # gain/duck values and records the choice; xAR still keeps ``True`` as
        # its backwards-compatible default for other callers.
        normalize=False,
        metadata={
            "external_bgm": False,
            "embedded_game_audio": True,
            "narration_voice": VOICE,
            "game_gain_db": 6.0,
            "narration_duck_db": -6.0,
        },
    )
    options = RenderOptions(
        width=1920,
        height=1080,
        fps=60,
        duration_seconds=duration,
        video_codec="libx264",
        audio_codec="aac",
        pixel_format="yuv420p",
        preset="medium",
        crf=20,
        audio_bitrate="192k",
        audio_sample_rate=48_000,
        audio_channels=2,
    )
    partial = variant_root / "renders" / f"{variant_id}.partial.mp4"
    final = variant_root / "renders" / f"{variant_id}.mp4"
    plan = plan_render(
        ffmpeg=ffmpeg,
        video_input=raw.resolve(),
        partial_output=partial,
        final_output=final,
        audit_directory=variant_root / "logs",
        options=options,
        ass_path=ass_path,
        start_seconds=source_start,
        audio_mix=mix,
    )
    plan_payload = {
        "variant_id": variant_id,
        "source_start_seconds": source_start,
        "duration_seconds": duration,
        "capture_contract": dict(capture_provenance),
        "capture_span": capture_span_provenance,
        "audio_mix": mix.to_mapping(),
        "ass": file_record(ass_path),
        "commands": [list(map(str, command.spec.argv)) for command in plan.commands],
        "filtergraph": plan.commands[0].spec.argv[plan.commands[0].spec.argv.index("-filter_complex") + 1],
        "planner": "xar_promo.render.plan_render",
        "executor": "xar_promo.render.execute_render_plan",
        "xar": dict(xar_provenance),
    }
    (variant_root / "logs" / "render-plan.json").write_text(
        json.dumps(plan_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    results = execute_render_plan(plan)
    (variant_root / "logs" / "render-results.json").write_text(
        json.dumps(
            [
                {
                    "status": result.status,
                    "returncode": result.returncode,
                    "audit_directory": str(result.audit_directory),
                    "argv": list(result.spec.argv),
                }
                for result in results
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8", newline="\n",
    )
    bound_probe = probe(final, ffprobe)
    (variant_root / "review" / "bound-probe.json").write_text(
        json.dumps(bound_probe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    manifest = {
        "schema_version": 1,
        "kind": "vivhite_promo_candidate_render",
        "status": "preliminary",
        "variant_id": variant_id,
        "source": {
            "raw_capture": file_record(raw),
            "start_seconds": source_start,
            "duration_seconds": duration,
            "capture_contract": dict(capture_provenance),
            "capture_span": capture_span_provenance,
        },
        "deliverable": file_record(final),
        "audio": {
            "external_bgm": False,
            "embedded_game_audio": True,
            "narration_voice": VOICE,
            "stems": narration_records,
            "mix_metadata": dict(mix.metadata),
        },
        "subtitles": {"burned_in": True, "file": file_record(ass_path)},
        "technical_probe": bound_probe,
        "xar": dict(xar_provenance),
        "audits": {"technical": "pending_write", "semantic": "pending", "human_review": "pending", "signoff": False},
        "warning": "Candidate only; no semantic claim has been certified and no human signoff/export approval has been performed.",
    }
    manifest_path = variant_root / "review" / "render-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"variant_id": variant_id, "path": str(final), "bytes": final.stat().st_size, "sha256": sha256_file(final), "duration_seconds": duration}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--narration-root", type=Path, default=DEFAULT_NARRATION_ROOT)
    parser.add_argument("--ffmpeg", type=Path, default=FFMPEG_DEFAULT)
    parser.add_argument("--ffprobe", type=Path, default=FFPROBE_DEFAULT)
    parser.add_argument("--xar-source", type=Path, default=None)
    parser.add_argument(
        "--capture-contract",
        type=Path,
        default=None,
        help=(
            "hash-bound capture contract; when omitted, infer one from the raw "
            "file's run directory"
        ),
    )
    args = parser.parse_args()
    raw = args.raw.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    ffmpeg = args.ffmpeg.expanduser().resolve()
    ffprobe = args.ffprobe.expanduser().resolve()
    narration_root = args.narration_root.expanduser().resolve()
    for path in (raw, ffmpeg, ffprobe):
        if not path.is_file():
            raise SystemExit(f"missing required file: {path}")
    contract_path = (
        args.capture_contract.expanduser().resolve()
        if args.capture_contract is not None
        else infer_capture_contract_path(raw)
    )
    validate_output_root(raw, output_root)
    capture_contract, capture_provenance = load_capture_binding(raw, contract_path)
    narration_paths = narration_input_paths(narration_root)
    narration_inputs = tuple(file_record(path) for path in narration_paths.values())
    tool_inputs: dict[str, dict[str, Any]] = {
        "ffmpeg": file_record(ffmpeg),
        "ffprobe": file_record(ffprobe),
    }
    xar_provenance = load_xar(args.xar_source)
    verify_render_inputs(
        capture_contract=capture_contract,
        contract_path=contract_path,
        capture_provenance=capture_provenance,
        narration_inputs=narration_inputs,
        tool_inputs=tool_inputs,
    )
    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir()
    results = []
    for variant_id, spec in VARIANTS.items():
        verify_render_inputs(
            capture_contract=capture_contract,
            contract_path=contract_path,
            capture_provenance=capture_provenance,
            narration_inputs=narration_inputs,
            tool_inputs=tool_inputs,
        )
        results.append(
            run_variant(
                variant_id=variant_id,
                spec=spec,
                raw=raw,
                narration_root=narration_root,
                output_root=output_root,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
                capture_contract=capture_contract,
                capture_provenance=capture_provenance,
                narration_paths=narration_paths,
                xar_provenance=xar_provenance,
            )
        )
        verify_render_inputs(
            capture_contract=capture_contract,
            contract_path=contract_path,
            capture_provenance=capture_provenance,
            narration_inputs=narration_inputs,
            tool_inputs=tool_inputs,
        )
    # FFmpeg has now consumed every variant.  A raw/evidence mutation during
    # rendering invalidates the entire candidate batch; retain any produced
    # files as an incomplete attempt and refuse to publish a batch manifest.
    verify_render_inputs(
        capture_contract=capture_contract,
        contract_path=contract_path,
        capture_provenance=capture_provenance,
        narration_inputs=narration_inputs,
        tool_inputs=tool_inputs,
    )
    capture_provenance["verification"] = "hash-bound-and-unchanged-before-and-after-render"
    parent_manifest = {
        "schema_version": 1,
        "kind": "vivhite_promo_candidate_render_batch",
        "status": "preliminary",
        "source_raw": file_record(raw),
        "capture_contract": dict(capture_provenance),
        "ffmpeg": dict(tool_inputs["ffmpeg"]),
        "ffprobe": dict(tool_inputs["ffprobe"]),
        "voice": VOICE,
        "xar": dict(xar_provenance),
        "narration_inputs": list(narration_inputs),
        "external_bgm": False,
        "variants": results,
        "semantic_audit": "pending",
        "human_review": "pending",
        "signoff": False,
        "export_approval": False,
    }
    (output_root / "batch-manifest.json").write_text(
        json.dumps(parent_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({"output_root": str(output_root), "variants": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"candidate render failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
