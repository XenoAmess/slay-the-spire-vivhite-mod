"""Render the director-v2 title cards through xAR's public visual API.

The command is deliberately append-only: every invocation requires a fresh
``run-...`` directory and refuses to replace an existing path.  Fonts and the
butterfly are explicit inputs, so xAR never performs an implicit resource
fallback.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
PROMO_ROOT = REPO_ROOT / "tools" / "promo"
DEFAULT_STORYBOARD = PROMO_ROOT / "v2" / "storyboard.json"
DEFAULT_RUNS_ROOT = PROMO_ROOT / "runs"
DEFAULT_BUTTERFLY = (
    REPO_ROOT
    / "assets"
    / "vivhite-ironclad"
    / "generated"
    / "evolink-paid"
    / "2026-08-28"
    / "0030-split-butterfly-attachment-attempt-01"
    / "output.png"
)
DEFAULT_ZH_FONT = Path(r"C:\Windows\Fonts\msyhbd.ttc")
DEFAULT_EN_FONT = Path(r"C:\Windows\Fonts\seguisb.ttf")
EXPECTED_TITLE_CARD_COUNT = 10
FPS = 60
RUN_ID_RE = re.compile(r"^run-[A-Za-z0-9][A-Za-z0-9._-]*$")


class TitleCardRenderError(RuntimeError):
    """The requested append-only title-card render is not valid."""


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--storyboard", type=Path, default=DEFAULT_STORYBOARD)
    parser.add_argument("--butterfly", type=Path, default=DEFAULT_BUTTERFLY)
    parser.add_argument("--zh-font", type=Path, default=DEFAULT_ZH_FONT)
    parser.add_argument("--en-font", type=Path, default=DEFAULT_EN_FONT)
    parser.add_argument("--zh-font-size", type=int, default=76)
    parser.add_argument("--en-font-size", type=int, default=36)
    parser.add_argument("--xar-source", type=Path)
    return parser.parse_args(argv)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _binding(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    label: str
    if root is not None:
        try:
            label = resolved.relative_to(root.resolve(strict=True)).as_posix()
        except ValueError:
            label = resolved.as_posix()
    else:
        label = resolved.as_posix()
    return {
        "path": label,
        "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TitleCardRenderError(f"could not read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TitleCardRenderError(f"JSON root must be an object: {path}")
    return payload


def _find_xar_source(explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    configured = os.environ.get("XAR_PROMO_TOOLCHAIN_SOURCE")
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        (
            Path(r"G:\workspace\xar_promo_toolchain-v0.2.1-tag"),
            Path(r"G:\workspace\xar_promo_toolchain"),
        )
    )
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        source = resolved / "src"
        if (source / "xar_promo" / "visuals.py").is_file():
            return resolved
    raise TitleCardRenderError(
        "xAR source not found; pass --xar-source or set XAR_PROMO_TOOLCHAIN_SOURCE"
    )


def _title_card_rows(storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    if storyboard.get("kind") != "vivhite_promo_storyboard_v2":
        raise TitleCardRenderError("storyboard kind is not vivhite_promo_storyboard_v2")
    rows: list[dict[str, Any]] = []
    for shot in storyboard.get("shots", []):
        if not isinstance(shot, dict):
            raise TitleCardRenderError("storyboard shots must be objects")
        for subshot in shot.get("subshots", []):
            if not isinstance(subshot, dict) or "title_card" not in subshot:
                continue
            title_card = subshot["title_card"]
            cue = subshot.get("cue")
            take = subshot.get("take")
            if not all(isinstance(value, dict) for value in (title_card, cue, take)):
                raise TitleCardRenderError("title-card subshot has malformed metadata")
            if take.get("generator") != "xar.TitleCardSpec":
                raise TitleCardRenderError(
                    f"{subshot.get('subshot_id')} does not declare xar.TitleCardSpec"
                )
            if title_card.get("factory") != (
                "vivhite_promo.title_cards_v2.create_title_card_spec_v2"
            ):
                raise TitleCardRenderError(
                    f"{subshot.get('subshot_id')} has an unexpected title-card factory"
                )
            duration = title_card.get("duration_seconds")
            if isinstance(duration, bool) or not isinstance(duration, (int, float)):
                raise TitleCardRenderError("title-card duration must be numeric")
            rows.append(
                {
                    "shot_id": shot.get("shot_id"),
                    "subshot_id": subshot.get("subshot_id"),
                    "cue_id": cue.get("cue_id"),
                    "chinese_title": title_card.get("chinese_title"),
                    "english_subtitle": title_card.get("english_subtitle"),
                    "duration_seconds": float(duration),
                }
            )
    if len(rows) != EXPECTED_TITLE_CARD_COUNT:
        raise TitleCardRenderError(
            f"expected {EXPECTED_TITLE_CARD_COUNT} title cards, found {len(rows)}"
        )
    for row in rows:
        for field in ("shot_id", "subshot_id", "cue_id", "chinese_title", "english_subtitle"):
            value = row[field]
            if not isinstance(value, str) or not value.strip():
                raise TitleCardRenderError(f"title-card {field} must be non-empty")
        if not 0 < row["duration_seconds"] <= 7:
            raise TitleCardRenderError("title-card duration must be in (0, 7] seconds")
    return rows


def _exclusive_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)


def _exclusive_write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _exclusive_write_bytes(path, encoded)


def render_run(args: argparse.Namespace) -> Path:
    if not RUN_ID_RE.fullmatch(args.run_id):
        raise TitleCardRenderError("--run-id must start with 'run-' and use safe characters")
    if args.zh_font_size <= 0 or args.en_font_size <= 0:
        raise TitleCardRenderError("font sizes must be positive integers")

    runs_root = args.runs_root.expanduser().resolve()
    run_root = runs_root / args.run_id
    if run_root.exists():
        raise TitleCardRenderError(f"append-only run already exists: {run_root}")

    storyboard_path = args.storyboard.expanduser().resolve(strict=True)
    butterfly_path = args.butterfly.expanduser().resolve(strict=True)
    zh_font_path = args.zh_font.expanduser().resolve(strict=True)
    en_font_path = args.en_font.expanduser().resolve(strict=True)
    xar_root = _find_xar_source(args.xar_source)

    sys.path.insert(0, str(PROMO_ROOT))
    sys.path.insert(0, str(xar_root / "src"))
    try:
        from PIL import Image, ImageFont
        import PIL
        import xar_promo
        from xar_promo.layout import FontSpec
        from xar_promo.visuals import PillowFont, render_title_card
        from vivhite_promo.title_cards_v2 import (
            CHINESE_TITLE_FONT_KEY,
            DEFAULT_BUTTERFLY_ASSET_KEY,
            ENGLISH_SUBTITLE_FONT_KEY,
            create_title_card_spec_v2,
        )
    except ImportError as exc:
        raise TitleCardRenderError(f"render dependency unavailable: {exc}") from exc
    if xar_promo.__version__ != "0.2.1":
        raise TitleCardRenderError(
            f"expected xAR 0.2.1, found {xar_promo.__version__!r}"
        )

    storyboard = _load_json(storyboard_path)
    rows = _title_card_rows(storyboard)

    zh_handle = ImageFont.truetype(str(zh_font_path), args.zh_font_size)
    en_handle = ImageFont.truetype(str(en_font_path), args.en_font_size)
    zh_name = zh_handle.getname()
    en_name = en_handle.getname()
    fonts = {
        CHINESE_TITLE_FONT_KEY: PillowFont(
            FontSpec(
                key=CHINESE_TITLE_FONT_KEY,
                family=str(zh_name[0]),
                size_px=float(args.zh_font_size),
                weight=700,
            ),
            zh_handle,
        ),
        ENGLISH_SUBTITLE_FONT_KEY: PillowFont(
            FontSpec(
                key=ENGLISH_SUBTITLE_FONT_KEY,
                family=str(en_name[0]),
                size_px=float(args.en_font_size),
                weight=600,
            ),
            en_handle,
        ),
    }
    with Image.open(butterfly_path) as opened:
        butterfly = opened.convert("RGBA")
    butterfly.load()
    alpha = butterfly.getchannel("A")
    asset_inspection = {
        "classification": "single_2d_spine_attachment_rgba_not_atlas_or_spritesheet",
        "title_card_consumption": "decoded_whole_image_contain_fit_no_slicing",
        "source_binding": _binding(butterfly_path, root=REPO_ROOT),
        "generation_request": (
            butterfly_path.parent.relative_to(REPO_ROOT).as_posix()
            + "/output.request.json"
        ),
        "existing_acceptance_evidence": (
            "assets/vivhite-ironclad/evaluation/semantic-butterfly/"
            "component-analysis.json"
        ),
        "game_runtime_deployment_claimed": False,
        "width": butterfly.width,
        "height": butterfly.height,
        "mode": butterfly.mode,
        "corner_alpha": [
            alpha.getpixel((0, 0)),
            alpha.getpixel((butterfly.width - 1, 0)),
            alpha.getpixel((0, butterfly.height - 1)),
            alpha.getpixel((butterfly.width - 1, butterfly.height - 1)),
        ],
        "alpha_bbox": list(alpha.getbbox() or ()),
        "alpha_extrema": list(alpha.getextrema()),
    }
    if (
        butterfly.size != (1024, 1024)
        or butterfly.mode != "RGBA"
        or asset_inspection["corner_alpha"] != [0, 0, 0, 0]
    ):
        raise TitleCardRenderError("butterfly does not match its accepted RGBA contract")

    run_root.mkdir(parents=True)
    rendered: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        spec = create_title_card_spec_v2(
            row["chinese_title"],
            row["english_subtitle"],
            butterfly_asset_key=DEFAULT_BUTTERFLY_ASSET_KEY,
        )
        png = render_title_card(
            spec,
            fonts=fonts,
            assets={DEFAULT_BUTTERFLY_ASSET_KEY: butterfly},
        )
        filename = f"{index:02d}-{row['subshot_id']}.png"
        output_path = run_root / "title-cards" / filename
        _exclusive_write_bytes(output_path, png)
        with Image.open(output_path) as rendered_image:
            rendered_image.load()
            rendered_rgba = rendered_image.convert("RGBA")
            output_alpha = rendered_rgba.getchannel("A")
            inspection = {
                "width": rendered_image.width,
                "height": rendered_image.height,
                "mode": rendered_image.mode,
                "alpha_extrema": list(output_alpha.getextrema()),
                "corner_alpha": [
                    output_alpha.getpixel((0, 0)),
                    output_alpha.getpixel((rendered_image.width - 1, 0)),
                    output_alpha.getpixel((0, rendered_image.height - 1)),
                    output_alpha.getpixel(
                        (rendered_image.width - 1, rendered_image.height - 1)
                    ),
                ],
            }
        if (
            inspection["width"] != 1920
            or inspection["height"] != 1080
            or inspection["mode"] != "RGBA"
            or inspection["alpha_extrema"][0] <= 0
            or inspection["alpha_extrema"][1] != 255
            or inspection["corner_alpha"] != [255, 255, 255, 255]
        ):
            raise TitleCardRenderError(
                f"unexpected rendered image contract for {output_path}: {inspection}"
            )
        rendered.append(
            {
                **row,
                "duration_frames": round(row["duration_seconds"] * FPS),
                "artifact": _binding(output_path, root=run_root),
                "inspection": inspection,
            }
        )

    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    title_manifest = {
        "schema": "vivhite-promo-title-card-assets-v2",
        "run_id": args.run_id,
        "created_at_utc": created_at,
        "status": "rendered_pending_editorial_review",
        "storyboard": _binding(storyboard_path, root=REPO_ROOT),
        "renderer": {
            "public_api": "xar_promo.visuals.render_title_card",
            "xar_version": xar_promo.__version__,
            "xar_visuals_source": _binding(
                xar_root / "src" / "xar_promo" / "visuals.py"
            ),
            "pillow_version": PIL.__version__,
            "canvas": {"width": 1920, "height": 1080, "fps": FPS},
        },
        "resources": {
            "fonts": {
                CHINESE_TITLE_FONT_KEY: {
                    **_binding(zh_font_path),
                    "family": str(zh_name[0]),
                    "style": str(zh_name[1]),
                    "size_px": args.zh_font_size,
                },
                ENGLISH_SUBTITLE_FONT_KEY: {
                    **_binding(en_font_path),
                    "family": str(en_name[0]),
                    "style": str(en_name[1]),
                    "size_px": args.en_font_size,
                },
            },
            "images": {DEFAULT_BUTTERFLY_ASSET_KEY: asset_inspection},
        },
        "title_cards": rendered,
    }
    title_manifest_path = run_root / "title-cards" / "manifest.json"
    _exclusive_write_json(title_manifest_path, title_manifest)

    run_manifest = {
        "schema": "vivhite-promo-title-card-render-run-v2",
        "run_id": args.run_id,
        "created_at_utc": created_at,
        "status": "complete_pending_editorial_review",
        "purpose": "director-v2-title-card-render",
        "legacy_media_used": False,
        "game_started": False,
        "obs_started": False,
        "paid_generation_calls": 0,
        "artifact_count": len(rendered),
        "title_card_manifest": _binding(title_manifest_path, root=run_root),
        "artifacts": [item["artifact"] for item in rendered],
    }
    _exclusive_write_json(run_root / "run-manifest.json", run_manifest)
    return run_root


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        run_root = render_run(args)
    except (TitleCardRenderError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
