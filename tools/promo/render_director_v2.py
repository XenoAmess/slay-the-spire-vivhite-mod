#!/usr/bin/env python3
"""Plan or execute the Vivhite director-v2 multi-take render."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence


PROMO_ROOT = Path(__file__).resolve().parent
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

from vivhite_promo.render_v2 import (  # noqa: E402
    RenderV2Error,
    build_render_plan_v2,
    build_variant_edl_v2,
    execute_render_plan_v2,
)


def _write_new_json(path: Path, payload: Any) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise RenderV2Error(f"refusing to overwrite output: {path}") from exc


def _plan_from_args(args: argparse.Namespace):
    return build_render_plan_v2(
        args.edl,
        args.narration_manifest,
        args.title_resources,
        artifact_root=args.artifact_root,
        narration_root=args.narration_root,
        title_resource_root=args.title_resource_root,
        output_root=args.output_root,
        ffmpeg=args.ffmpeg,
        ffprobe=args.ffprobe,
        ffmpeg_lock=args.ffmpeg_lock,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_render_inputs(target: argparse.ArgumentParser) -> None:
        target.add_argument("--edl", type=Path, required=True)
        target.add_argument("--narration-manifest", type=Path, required=True)
        target.add_argument("--title-resources", type=Path, required=True)
        target.add_argument("--artifact-root", type=Path, required=True)
        target.add_argument(
            "--narration-root",
            type=Path,
            default=None,
            help="run root for narration paths; defaults to --artifact-root",
        )
        target.add_argument(
            "--title-resource-root",
            type=Path,
            default=None,
            help="run root for title resources; defaults to --artifact-root",
        )
        target.add_argument("--output-root", type=Path, required=True)
        target.add_argument("--ffmpeg", type=Path, default=Path(r"C:\ffmpeg\bin\ffmpeg.exe"))
        target.add_argument("--ffprobe", type=Path, default=Path(r"C:\ffmpeg\bin\ffprobe.exe"))
        target.add_argument(
            "--ffmpeg-lock",
            type=Path,
            default=PROMO_ROOT / "ffmpeg-lock.json",
        )

    plan = subparsers.add_parser(
        "plan",
        help="verify all inputs and emit an unexecuted command plan",
    )
    add_render_inputs(plan)
    plan.add_argument("--plan-output", type=Path, default=None)

    render = subparsers.add_parser(
        "render",
        help="verify inputs, materialize xAR cards, and execute FFmpeg",
    )
    add_render_inputs(render)

    variant = subparsers.add_parser(
        "variant",
        help="build one independent 60/30/15 EDL from the verified take batch",
    )
    variant.add_argument("--master-edl", type=Path, required=True)
    variant.add_argument("--recipe", type=Path, required=True)
    variant.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "variant":
            value = build_variant_edl_v2(args.master_edl, args.recipe)
            _write_new_json(args.output, value)
            print(
                json.dumps(
                    {
                        "status": "production_verified",
                        "edit_id": value["edit_id"],
                        "target_duration_seconds": value["target_duration_seconds"],
                        "output": args.output.expanduser().resolve().as_posix(),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        plan = _plan_from_args(args)
        if args.command == "plan":
            value = plan.to_mapping()
            if args.plan_output is not None:
                _write_new_json(args.plan_output, value)
            print(
                json.dumps(
                    {
                        "status": value["status"],
                        "edit_id": value["edit_id"],
                        "target_duration_seconds": value["target_duration_seconds"],
                        "segments": len(value["segments"]),
                        "narration_cues": len(value["narration"]),
                        "title_cards": len(value["title_card_tasks"]),
                        "process_started": False,
                        "plan_output": None
                        if args.plan_output is None
                        else args.plan_output.expanduser().resolve().as_posix(),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        receipt = execute_render_plan_v2(plan)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    except RenderV2Error as exc:
        print(f"director-v2 render refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
