#!/usr/bin/env python3
"""Build and validate a versioned STS2 base-game knowledge snapshot."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from game_knowledge.extract import DEFAULT_LOCALES, ExtractionError, extract_game_resources
from game_knowledge.mechanics import MechanicsImportError, import_mechanics
from game_knowledge.pck import PckError
from game_knowledge.runtime import (
    DEFAULT_COLLECTIONS,
    RuntimeCaptureError,
    capture_runtime,
    import_runtime_response_dir,
)
from game_knowledge.validate import ValidationError, validate_snapshot


TOOL_DIR = Path(__file__).resolve().parent
ASCEND_DIR = TOOL_DIR.parents[1]
DEFAULT_OUTPUT_ROOT = ASCEND_DIR / "knowledge" / "game"


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _game_dir(value: str | None) -> Path:
    configured = value or os.environ.get("STS2_GAME_DIR")
    if not configured:
        raise ExtractionError("Pass --game-dir or set STS2_GAME_DIR")
    return Path(configured)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _add_runtime_options(parser: argparse.ArgumentParser, *, include_auto: bool) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--runtime-response-dir",
        help="Import offline <collection>.response.json files captured from /data",
    )
    group.add_argument(
        "--runtime-url",
        help="Read /data from this running STS2AIAgent base URL (for example http://127.0.0.1:8080)",
    )
    if include_auto:
        group.add_argument(
            "--discover-runtime",
            action="store_true",
            help="Probe localhost ports 8080-8084 and capture the first healthy instance",
        )
    parser.add_argument(
        "--runtime-collections",
        type=_csv,
        default=DEFAULT_COLLECTIONS,
        metavar="CSV",
        help="Runtime collections to request/import (default: core plus expanded ModelDb collections)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract immutable STS2 resources and runtime ModelDb data into a versioned knowledge corpus."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract", help="Extract PCK inventory and bilingual localization")
    extract.add_argument("--game-dir", help="Slay the Spire 2 installation directory")
    extract.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help=f"Parent of the version directory (default: {DEFAULT_OUTPUT_ROOT})",
    )
    extract.add_argument(
        "--locales",
        type=_csv,
        default=DEFAULT_LOCALES,
        metavar="CSV",
        help="PCK localization locales to copy (default: eng,zhs)",
    )
    extract.add_argument(
        "--full-pck-sha256",
        action="store_true",
        help="Also hash the full ~2 GB PCK; directory SHA256 is always recorded",
    )
    extract.add_argument("--skip-validation", action="store_true")
    extract.add_argument(
        "--mechanics-dir",
        help="Import GameKnowledge.Tool mechanics-manifest.json and category JSONL files",
    )
    _add_runtime_options(extract, include_auto=True)

    runtime = subparsers.add_parser("runtime", help="Add a runtime ModelDb snapshot to an extracted version")
    runtime.add_argument("--output-dir", required=True, help="Existing knowledge/game/vX.Y.Z directory")
    _add_runtime_options(runtime, include_auto=False)

    mechanics = subparsers.add_parser(
        "mechanics", help="Import and ID-join static assembly behavior facts"
    )
    mechanics.add_argument("--output-dir", required=True, help="Existing knowledge/game/vX.Y.Z directory")
    mechanics.add_argument(
        "--mechanics-dir",
        required=True,
        help="Directory produced by GameKnowledge.Tool extract",
    )

    validate = subparsers.add_parser("validate", help="Validate hashes, schema, IDs, and references")
    validate.add_argument("--output-dir", required=True, help="Existing knowledge/game/vX.Y.Z directory")
    validate.add_argument("--game-dir", help="Optionally recheck the installed game's source hashes")
    validate.add_argument("--no-write-report", action="store_true")
    return parser


def _run_extract(args: argparse.Namespace) -> int:
    game_dir = _game_dir(args.game_dir)
    output_dir, manifest = extract_game_resources(
        game_dir=game_dir,
        output_root=args.output_root,
        locales=args.locales,
        full_pck_sha256=args.full_pck_sha256,
    )
    runtime_result = None
    if args.runtime_response_dir:
        runtime_result = import_runtime_response_dir(
            output_dir=output_dir,
            response_dir=args.runtime_response_dir,
            collections=args.runtime_collections,
        )
    elif args.runtime_url or args.discover_runtime:
        runtime_result = capture_runtime(
            output_dir=output_dir,
            base_url=args.runtime_url,
            collections=args.runtime_collections,
        )

    mechanics_result = None
    if args.mechanics_dir:
        mechanics_result = import_mechanics(
            output_dir=output_dir,
            mechanics_dir=args.mechanics_dir,
        )

    report = None
    if not args.skip_validation:
        report = validate_snapshot(output_dir=output_dir, game_dir=game_dir)
    _print(
        {
            "output_dir": str(output_dir),
            "game": manifest["game"],
            "localization_files": len(manifest["localization"]["files"]),
            "runtime": runtime_result,
            "mechanics": mechanics_result,
            "validation": report and {"overall": report["overall"], "counts": report["counts"]},
        }
    )
    return 1 if report and report["overall"] == "fail" else 0


def _run_runtime(args: argparse.Namespace) -> int:
    if args.runtime_response_dir:
        result = import_runtime_response_dir(
            output_dir=args.output_dir,
            response_dir=args.runtime_response_dir,
            collections=args.runtime_collections,
        )
    else:
        result = capture_runtime(
            output_dir=args.output_dir,
            base_url=args.runtime_url,
            collections=args.runtime_collections,
        )
    report = validate_snapshot(output_dir=args.output_dir)
    _print({"runtime": result, "validation": {"overall": report["overall"], "counts": report["counts"]}})
    return 1 if report["overall"] == "fail" else 0


def _run_validate(args: argparse.Namespace) -> int:
    report = validate_snapshot(
        output_dir=args.output_dir,
        game_dir=args.game_dir,
        write_report=not args.no_write_report,
    )
    _print(report)
    return 1 if report["overall"] == "fail" else 0


def _run_mechanics(args: argparse.Namespace) -> int:
    result = import_mechanics(output_dir=args.output_dir, mechanics_dir=args.mechanics_dir)
    report = validate_snapshot(output_dir=args.output_dir)
    _print(
        {
            "mechanics": result,
            "validation": {"overall": report["overall"], "counts": report["counts"]},
        }
    )
    return 1 if report["overall"] == "fail" else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            return _run_extract(args)
        if args.command == "runtime":
            return _run_runtime(args)
        if args.command == "mechanics":
            return _run_mechanics(args)
        if args.command == "validate":
            return _run_validate(args)
        raise AssertionError(f"Unhandled command: {args.command}")
    except (
        ExtractionError,
        MechanicsImportError,
        PckError,
        RuntimeCaptureError,
        ValidationError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
