#!/usr/bin/env python3
"""Dump compact values from the MOSS-TTS Nano ONNX metadata JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


STS2_ASCEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_PATH = (
    STS2_ASCEND_ROOT
    / "third_party"
    / "MOSS-TTS-Nano"
    / "models"
    / "MOSS-TTS-Nano-100M-ONNX"
    / "tts_browser_onnx_meta.json"
)


def dump_metadata(value: Any, prefix: str = "") -> None:
    """Print short scalar values and list lengths using dotted JSON paths."""
    if isinstance(value, dict):
        for key, child in value.items():
            dump_metadata(child, f"{prefix}.{key}")
        return

    if isinstance(value, list):
        print(prefix, "= list", len(value))
        return

    rendered = str(value)
    if len(rendered) < 80:
        print(prefix, "=", rendered)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dump compact values from MOSS-TTS Nano ONNX metadata."
    )
    parser.add_argument(
        "metadata",
        nargs="?",
        type=Path,
        default=DEFAULT_METADATA_PATH,
        help=(
            "metadata JSON to inspect; defaults to the local MOSS-TTS Nano "
            "ONNX metadata file"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    metadata_path = args.metadata.expanduser()

    try:
        with metadata_path.open("r", encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
    except FileNotFoundError:
        print(f"Metadata file not found: {metadata_path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"Invalid metadata JSON in {metadata_path}: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Unable to read metadata file {metadata_path}: {exc}", file=sys.stderr)
        return 2

    dump_metadata(metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
