#!/usr/bin/env python3
"""Publish edited Ironclad authoring assets into Vivhite's private resource tree.

The extractor writes versioned editable ``.skel/.atlas/PNG`` files below the
repository's ``assets`` directory. Godot's bundled Spine runtime consumes
``.spskel/.spatlas`` instead, so this tool converts the edited sources,
rewrites the three presentation scenes and Spine data resources, and copies
the nine UI textures to their runtime names.

Unmodified game art is rejected when publishing to the real mod directory.
``--allow-unchanged`` exists only for a preview destination below ``.work``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable


EXPECTED_GAME_VERSION = "0.111.0"
RUNTIME_RESOURCE_ROOT = "res://Vivhite/skins/ironclad"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
UID_ATTRIBUTE_RE = re.compile(r'\s+uid="uid://[^"]+"')
UID_METADATA_LINE_RE = re.compile(
    r'^metadata/_custom_type_script\s*=\s*"uid://[^"]+"\r?\n?', re.MULTILINE
)


class PublishError(RuntimeError):
    """A deterministic, user-facing publishing failure."""


@dataclass(frozen=True, slots=True)
class SpineSet:
    name: str
    skeleton_source: str
    skeleton_output: str | None
    atlas_source: str
    atlas_output: str
    atlas_logical_source: str
    pages: tuple[str, ...]
    skeleton_data_source: str
    skeleton_data_output: str
    path_replacements: tuple[tuple[str, str], ...]


SPINE_SETS = (
    SpineSet(
        name="combat",
        skeleton_source="combat/ironclad.skel",
        skeleton_output="spine/combat/ironclad.spskel",
        atlas_source="combat/ironclad.atlas",
        atlas_output="spine/combat/ironclad.spatlas",
        atlas_logical_source=f"{RUNTIME_RESOURCE_ROOT}/spine/combat/ironclad.atlas",
        pages=(
            "combat/ironclad.png",
            "combat/ironclad_2.png",
            "combat/ironclad_3.png",
            "combat/ironclad_4.png",
        ),
        skeleton_data_source="combat/combat_skeleton_data.tres",
        skeleton_data_output="spine/combat/combat_skeleton_data.tres",
        path_replacements=(
            (
                "res://animations/characters/ironclad/ironclad.atlas",
                f"{RUNTIME_RESOURCE_ROOT}/spine/combat/ironclad.spatlas",
            ),
            (
                "res://animations/characters/ironclad/ironclad.skel",
                f"{RUNTIME_RESOURCE_ROOT}/spine/combat/ironclad.spskel",
            ),
        ),
    ),
    SpineSet(
        name="merchant",
        skeleton_source="combat/ironclad.skel",
        skeleton_output=None,
        atlas_source="merchant/ironclad_shop.atlas",
        atlas_output="spine/merchant/ironclad_shop.spatlas",
        atlas_logical_source=f"{RUNTIME_RESOURCE_ROOT}/spine/merchant/ironclad_shop.atlas",
        pages=(
            "merchant/ironclad_shop.png",
            "merchant/ironclad_shop_2.png",
            "merchant/ironclad_shop_3.png",
            "merchant/ironclad_shop_4.png",
        ),
        skeleton_data_source="merchant/merchant_skeleton_data.tres",
        skeleton_data_output="spine/merchant/merchant_skeleton_data.tres",
        path_replacements=(
            (
                "res://animations/merchant/ironclad/ironclad_shop.atlas",
                f"{RUNTIME_RESOURCE_ROOT}/spine/merchant/ironclad_shop.spatlas",
            ),
            (
                "res://animations/characters/ironclad/ironclad.skel",
                f"{RUNTIME_RESOURCE_ROOT}/spine/combat/ironclad.spskel",
            ),
        ),
    ),
    SpineSet(
        name="rest_site",
        skeleton_source="rest_site/restsite_ironclad.skel",
        skeleton_output="spine/rest_site/restsite_ironclad.spskel",
        atlas_source="rest_site/restsite_ironclad.atlas",
        atlas_output="spine/rest_site/restsite_ironclad.spatlas",
        atlas_logical_source=f"{RUNTIME_RESOURCE_ROOT}/spine/rest_site/restsite_ironclad.atlas",
        pages=("rest_site/restsite_ironclad.png",),
        skeleton_data_source="rest_site/rest_site_skeleton_data.tres",
        skeleton_data_output="spine/rest_site/rest_site_skeleton_data.tres",
        path_replacements=(
            (
                "res://animations/rest_site/ironclad/restsite_ironclad.atlas",
                f"{RUNTIME_RESOURCE_ROOT}/spine/rest_site/restsite_ironclad.spatlas",
            ),
            (
                "res://animations/rest_site/ironclad/restsite_ironclad.skel",
                f"{RUNTIME_RESOURCE_ROOT}/spine/rest_site/restsite_ironclad.spskel",
            ),
        ),
    ),
    SpineSet(
        name="character_select",
        skeleton_source="character_select/characterselect_ironclad.skel",
        skeleton_output="spine/character_select/characterselect_ironclad.spskel",
        atlas_source="character_select/characterselect_ironclad.atlas",
        atlas_output="spine/character_select/characterselect_ironclad.spatlas",
        atlas_logical_source=(
            f"{RUNTIME_RESOURCE_ROOT}/spine/character_select/"
            "characterselect_ironclad.atlas"
        ),
        pages=("character_select/characterselect_ironclad.png",),
        skeleton_data_source="character_select/character_select_skeleton_data.tres",
        skeleton_data_output="spine/character_select/character_select_skeleton_data.tres",
        path_replacements=(
            (
                "res://animations/character_select/ironclad/"
                "characterselect_ironclad.atlas",
                f"{RUNTIME_RESOURCE_ROOT}/spine/character_select/"
                "characterselect_ironclad.spatlas",
            ),
            (
                "res://animations/character_select/ironclad/"
                "characterselect_ironclad.skel",
                f"{RUNTIME_RESOURCE_ROOT}/spine/character_select/"
                "characterselect_ironclad.spskel",
            ),
        ),
    ),
)

SCENES = (
    (
        "merchant/scene.tscn",
        "scenes/merchant.tscn",
        "res://animations/merchant/ironclad/ironclad_merchant_skel_data.tres",
        f"{RUNTIME_RESOURCE_ROOT}/spine/merchant/merchant_skeleton_data.tres",
    ),
    (
        "rest_site/scene.tscn",
        "scenes/rest_site.tscn",
        "res://animations/rest_site/ironclad/rest_site_ironclad_skel_data.tres",
        f"{RUNTIME_RESOURCE_ROOT}/spine/rest_site/rest_site_skeleton_data.tres",
    ),
    (
        "character_select/scene.tscn",
        "scenes/character_select.tscn",
        "res://animations/character_select/ironclad/"
        "characterselect_ironclad_skel_data.tres",
        f"{RUNTIME_RESOURCE_ROOT}/spine/character_select/"
        "character_select_skeleton_data.tres",
    ),
)

UI_COPIES = (
    ("ui/icon.png", "ui/icon.png"),
    ("ui/icon_outline.png", "ui/icon_outline.png"),
    ("ui/select.png", "ui/select.png"),
    ("ui/select_locked.png", "ui/select_locked.png"),
    ("ui/map_marker.png", "ui/map_marker.png"),
    ("ui/multiplayer/point.png", "multiplayer/point.png"),
    ("ui/multiplayer/rock.png", "multiplayer/rock.png"),
    ("ui/multiplayer/paper.png", "multiplayer/paper.png"),
    ("ui/multiplayer/scissors.png", "multiplayer/scissors.png"),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_relative(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise PublishError(f"Expected a non-empty relative path, got {relative!r}")
    root_resolved = root.resolve()
    result = (root_resolved / relative).resolve()
    try:
        result.relative_to(root_resolved)
    except ValueError as exc:
        raise PublishError(f"Path escapes {root_resolved}: {relative}") from exc
    return result


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_required(root: Path, relative: str) -> bytes:
    path = _safe_relative(root, relative)
    if not path.is_file():
        raise PublishError(f"Missing authoring file: {path}")
    data = path.read_bytes()
    if not data:
        raise PublishError(f"Authoring file is empty: {path}")
    return data


def _read_text(root: Path, relative: str) -> str:
    data = _read_required(root, relative)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PublishError(f"Expected UTF-8 text: {_safe_relative(root, relative)}") from exc


def _without_uids(text: str) -> str:
    return UID_METADATA_LINE_RE.sub("", UID_ATTRIBUTE_RE.sub("", text))


def _replace_required(text: str, replacements: Iterable[tuple[str, str]], label: str) -> str:
    result = text
    for old, new in replacements:
        if old not in result:
            raise PublishError(f"{label} does not contain expected resource path: {old}")
        result = result.replace(old, new)
    return result


def _spatlas(atlas_text: str, logical_source_path: str) -> bytes:
    payload = {
        "atlas_data": atlas_text,
        "normal_texture_prefix": "n",
        "source_path": logical_source_path,
        "specular_texture_prefix": "s",
    }
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _load_manifest(authoring_root: Path) -> tuple[dict[str, object], dict[str, str]]:
    manifest_path = authoring_root / "manifest.json"
    if not manifest_path.is_file():
        raise PublishError(
            f"Missing extraction manifest: {manifest_path}. Run extract_ironclad_assets.py first."
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishError(f"Invalid extraction manifest: {manifest_path}") from exc

    game = manifest.get("game")
    if not isinstance(game, dict) or game.get("expected_version") != EXPECTED_GAME_VERSION:
        raise PublishError(
            f"Expected an Ironclad {EXPECTED_GAME_VERSION} extraction manifest: {manifest_path}"
        )
    fingerprint = game.get("version_fingerprint")
    if not isinstance(fingerprint, dict) or fingerprint.get("matched") is not True:
        raise PublishError("The extraction manifest did not pass the v0.111.0 fingerprint check.")

    hashes: dict[str, str] = {}
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise PublishError("Extraction manifest has no asset records.")
    for item in assets:
        if not isinstance(item, dict):
            continue
        relative = item.get("output_path")
        digest = item.get("output_sha256")
        if isinstance(relative, str) and isinstance(digest, str):
            hashes[relative.replace("\\", "/")] = digest.lower()
    return manifest, hashes


def _protected_art_inputs() -> tuple[str, ...]:
    paths: list[str] = []
    seen: set[str] = set()
    for spine_set in SPINE_SETS:
        for relative in (spine_set.skeleton_source, *spine_set.pages):
            if relative not in seen:
                seen.add(relative)
                paths.append(relative)
    for source, _ in UI_COPIES:
        if source not in seen:
            seen.add(source)
            paths.append(source)
    return tuple(paths)


def _check_original_art_guard(
    authoring_root: Path,
    original_hashes: dict[str, str],
    allow_unchanged: bool,
) -> None:
    unchanged: list[str] = []
    for relative in _protected_art_inputs():
        data = _read_required(authoring_root, relative)
        expected = original_hashes.get(relative)
        if expected is None:
            raise PublishError(f"Extraction manifest has no checksum for: {relative}")
        if _sha256(data).lower() == expected:
            unchanged.append(relative)

    if unchanged and not allow_unchanged:
        formatted = "\n  - ".join(unchanged)
        raise PublishError(
            "Refusing to install unmodified extracted game art. Replace/re-export every "
            "listed skeleton or image before publishing:\n  - "
            f"{formatted}\nFor a local pipeline preview only, use --allow-unchanged with a "
            "destination below .work."
        )


def _validate_atlas_pages(atlas_text: str, page_sources: tuple[str, ...], set_name: str) -> None:
    declared = {line.strip() for line in atlas_text.splitlines() if line.strip()}
    missing = [Path(page).name for page in page_sources if Path(page).name not in declared]
    if missing:
        raise PublishError(
            f"{set_name} atlas does not declare required page(s): {', '.join(missing)}"
        )


def _build_outputs(authoring_root: Path) -> dict[str, bytes]:
    outputs: dict[str, bytes] = {}

    for spine_set in SPINE_SETS:
        atlas_text = _read_text(authoring_root, spine_set.atlas_source)
        _validate_atlas_pages(atlas_text, spine_set.pages, spine_set.name)
        outputs[spine_set.atlas_output] = _spatlas(
            atlas_text, spine_set.atlas_logical_source
        )

        if spine_set.skeleton_output is not None:
            outputs[spine_set.skeleton_output] = _read_required(
                authoring_root, spine_set.skeleton_source
            )

        skeleton_data = _read_text(authoring_root, spine_set.skeleton_data_source)
        skeleton_data = _replace_required(
            skeleton_data,
            spine_set.path_replacements,
            spine_set.skeleton_data_source,
        )
        outputs[spine_set.skeleton_data_output] = (
            _without_uids(skeleton_data).rstrip() + "\n"
        ).encode("utf-8")

        output_page_dir = Path(spine_set.atlas_output).parent
        for page_source in spine_set.pages:
            data = _read_required(authoring_root, page_source)
            if not data.startswith(PNG_SIGNATURE):
                raise PublishError(f"Expected a real PNG file: {page_source}")
            outputs[(output_page_dir / Path(page_source).name).as_posix()] = data

    for source, output, original_ref, private_ref in SCENES:
        scene = _read_text(authoring_root, source)
        scene = _replace_required(scene, ((original_ref, private_ref),), source)
        outputs[output] = (_without_uids(scene).rstrip() + "\n").encode("utf-8")

    for source, output in UI_COPIES:
        data = _read_required(authoring_root, source)
        if not data.startswith(PNG_SIGNATURE):
            raise PublishError(f"Expected a real PNG file: {source}")
        outputs[output] = data

    return outputs


def _write_outputs(destination: Path, outputs: dict[str, bytes]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for relative in sorted(outputs):
        target = _safe_relative(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(outputs[relative])


def _parse_args(argv: list[str]) -> argparse.Namespace:
    repo = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--authoring-root",
        default=str(repo / "assets" / f"ironclad-v{EXPECTED_GAME_VERSION}"),
        help="Edited extraction root (defaults to assets/ironclad-v0.111.0)",
    )
    parser.add_argument(
        "--destination",
        default=str(repo / "Vivhite" / "Vivhite" / "skins" / "ironclad"),
        help="Runtime skin root (defaults to the Vivhite project resource tree)",
    )
    parser.add_argument(
        "--allow-unchanged",
        action="store_true",
        help="Allow unchanged originals only for a local preview below .work",
    )
    return parser.parse_args(argv)


def run(argv: list[str]) -> int:
    args = _parse_args(argv)
    repo = _repo_root().resolve()
    work_root = (repo / ".work").resolve()
    authoring_root = Path(args.authoring_root).resolve()
    destination = Path(args.destination).resolve()

    if args.allow_unchanged:
        try:
            destination.relative_to(work_root)
        except ValueError as exc:
            raise PublishError(
                "--allow-unchanged is restricted to a preview destination below .work."
            ) from exc

    _, original_hashes = _load_manifest(authoring_root)
    _check_original_art_guard(authoring_root, original_hashes, args.allow_unchanged)
    outputs = _build_outputs(authoring_root)
    _write_outputs(destination, outputs)

    print(f"Published {len(outputs)} private Ironclad skin resources to: {destination}")
    if destination == (repo / "Vivhite" / "Vivhite" / "skins" / "ironclad").resolve():
        print("Next: cd Vivhite; dotnet build")
    else:
        print("Preview only: no tracked mod resources were changed.")
    return 0


def main() -> None:
    try:
        raise SystemExit(run(sys.argv[1:]))
    except (OSError, PublishError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
