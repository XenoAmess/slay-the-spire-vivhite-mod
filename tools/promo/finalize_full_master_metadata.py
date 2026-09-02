"""CLI wrapper for :mod:`vivhite_promo.run_metadata`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vivhite_promo.run_metadata import RunMetadataError, finalize_run_metadata


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Content-address one existing Vivhite full-master run without signoff/export."
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--run-root", type=Path)
    args = parser.parse_args()
    try:
        result = finalize_run_metadata(args.spec, run_root=args.run_root)
    except RunMetadataError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
