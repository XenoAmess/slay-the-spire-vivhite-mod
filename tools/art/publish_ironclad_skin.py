#!/usr/bin/env python3
"""Publish White Qi art into Vivhite's private Ironclad resource tree.

The versioned extraction under ``assets/ironclad-v0.111.0`` is a read-only
template source for the manifest, scenes, and skeleton-data wrappers. Finished
atlases, pages, and UI textures come from ``assets/vivhite-ironclad/custom``.
The runtime skin deliberately reuses the matching vanilla ``.skel`` resources
already mounted by the game and publishes only private ``.spatlas`` wrappers,
edited PNGs, scenes, and UI textures. This keeps the original animation
binaries out of the Mod PCK and preserves both template and finished art in the
repository.

Unmodified game art is rejected when publishing to the real mod directory.
``--allow-unchanged`` exists only for a preview destination below ``.work``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
from typing import Iterable
import zlib


EXPECTED_GAME_VERSION = "0.111.0"
RUNTIME_RESOURCE_ROOT = "res://Vivhite/skins/ironclad"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_MAX_DIMENSION = 16_384
PNG_MAX_DECODED_BYTES = 512 * 1024 * 1024
UID_ATTRIBUTE_RE = re.compile(r'\s+uid="uid://[^"]+"')
UID_METADATA_LINE_RE = re.compile(
    r'^metadata/_custom_type_script\s*=\s*"uid://[^"]+"\r?\n?', re.MULTILINE
)


class PublishError(RuntimeError):
    """A deterministic, user-facing publishing failure."""


@dataclass(frozen=True, slots=True)
class DecodedRgba8Png:
    width: int
    height: int
    filtered_scanlines: bytes


@dataclass(frozen=True, slots=True)
class SpineSet:
    name: str
    vanilla_skeleton_resource: str
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
        vanilla_skeleton_resource="res://animations/characters/ironclad/ironclad.skel",
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
        ),
    ),
    SpineSet(
        name="merchant",
        vanilla_skeleton_resource="res://animations/characters/ironclad/ironclad.skel",
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
        ),
    ),
    SpineSet(
        name="rest_site",
        vanilla_skeleton_resource="res://animations/rest_site/ironclad/restsite_ironclad.skel",
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
        ),
    ),
    SpineSet(
        name="character_select",
        vanilla_skeleton_resource=(
            "res://animations/character_select/ironclad/characterselect_ironclad.skel"
        ),
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

CHARACTER_SELECT_SCENE_REPLACEMENTS = (
    (
        "colors = PackedColorArray(0, 0, 0, 1, 0.0421156, 0.0144603, "
        "0.0104837, 1, 0.913725, 0.313726, 0.227451, 1)",
        "colors = PackedColorArray(0, 0, 0, 1, 0.018, 0.012, 0.08, 1, "
        "0.388235, 0.211765, 0.913725, 1)",
    ),
    (
        "colors = PackedColorArray(0.913725, 0.313726, 0.227451, 0, "
        "0.913725, 0.313726, 0.227451, 1, 0.827451, 0.411765, "
        "0.258824, 1, 0, 0, 0, 1)",
        "colors = PackedColorArray(0.388235, 0.211765, 0.913725, 0, "
        "0.388235, 0.211765, 0.913725, 1, 0.227451, 0.678431, "
        "0.913725, 1, 0, 0, 0, 1)",
    ),
    (
        "colors = PackedColorArray(0.913725, 0.313726, 0.227451, 0, "
        "0, 0, 0, 1, 0, 0, 0, 1)",
        "colors = PackedColorArray(0.388235, 0.211765, 0.913725, 0, "
        "0.015686, 0.007843, 0.062745, 1, 0, 0, 0, 1)",
    ),
    (
        '[node name="ash2" type="CPUParticles2D" parent="."]\n'
        "position = Vector2(-14, 1163)",
        '[node name="ash2" type="CPUParticles2D" parent="."]\n'
        "visible = false\n"
        "position = Vector2(-14, 1163)",
    ),
    (
        '[node name="ash3" type="CPUParticles2D" parent="."]\n'
        "position = Vector2(145, 1163)",
        '[node name="ash3" type="CPUParticles2D" parent="."]\n'
        "visible = false\n"
        "position = Vector2(145, 1163)",
    ),
    (
        "color = Color(0.764706, 0.262745, 0.219608, 0.552941)",
        "color = Color(0.388235, 0.211765, 0.913725, 0.552941)",
    ),
    (
        "color = Color(0.764706, 0.470588, 0.219608, 0.552941)",
        "color = Color(0.227451, 0.678431, 0.913725, 0.552941)",
    ),
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


def _paeth_predictor(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    distance_left = abs(estimate - left)
    distance_above = abs(estimate - above)
    distance_upper_left = abs(estimate - upper_left)
    if distance_left <= distance_above and distance_left <= distance_upper_left:
        return left
    if distance_above <= distance_upper_left:
        return above
    return upper_left


def _decode_rgba8_png(data: bytes, label: str) -> DecodedRgba8Png:
    """Decode the exact PNG subset used by the checked-in art without Pillow.

    The publisher deliberately accepts only 8-bit, non-interlaced RGBA PNGs.
    CRCs, chunk ordering, the zlib stream, scanline sizes, and all PNG filters
    are validated so a malformed file cannot pass by merely having a signature.
    """

    if not data.startswith(PNG_SIGNATURE):
        raise PublishError(f"Expected a real PNG file: {label}")

    offset = len(PNG_SIGNATURE)
    width = height = 0
    saw_ihdr = False
    saw_idat = False
    ended_idat = False
    saw_iend = False
    compressed_parts: list[bytes] = []

    while offset < len(data):
        if len(data) - offset < 12:
            raise PublishError(f"Truncated PNG chunk header: {label}")
        length = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        chunk_type = data[offset : offset + 4]
        offset += 4
        if len(chunk_type) != 4 or any(
            byte < ord("A") or byte > ord("z") or ord("Z") < byte < ord("a")
            for byte in chunk_type
        ):
            raise PublishError(f"Invalid PNG chunk type in: {label}")
        if length > len(data) - offset - 4:
            raise PublishError(f"Truncated PNG chunk payload: {label}")
        payload = data[offset : offset + length]
        offset += length
        expected_crc = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(payload, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise PublishError(
                f"PNG chunk CRC mismatch ({chunk_type.decode('ascii')}): {label}"
            )

        if not saw_ihdr and chunk_type != b"IHDR":
            raise PublishError(f"PNG IHDR must be the first chunk: {label}")
        if chunk_type == b"IHDR":
            if saw_ihdr or length != 13:
                raise PublishError(f"Invalid or duplicate PNG IHDR: {label}")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", payload)
            if width < 1 or height < 1:
                raise PublishError(f"PNG dimensions must be positive: {label}")
            if width > PNG_MAX_DIMENSION or height > PNG_MAX_DIMENSION:
                raise PublishError(
                    f"PNG dimensions exceed {PNG_MAX_DIMENSION}: {label} ({width}x{height})"
                )
            if (bit_depth, color_type, compression, filter_method, interlace) != (
                8,
                6,
                0,
                0,
                0,
            ):
                raise PublishError(
                    f"PNG must be RGBA8 and non-interlaced: {label} "
                    f"(depth={bit_depth}, color={color_type}, interlace={interlace})"
                )
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            if ended_idat:
                raise PublishError(f"PNG IDAT chunks must be consecutive: {label}")
            saw_idat = True
            compressed_parts.append(payload)
        elif chunk_type == b"IEND":
            if length != 0 or not saw_idat:
                raise PublishError(f"Invalid PNG IEND or missing IDAT: {label}")
            saw_iend = True
            if offset != len(data):
                raise PublishError(f"Trailing bytes after PNG IEND: {label}")
            break
        elif saw_idat:
            ended_idat = True

        # Unknown critical chunks are unsafe for the deliberately narrow
        # decoder. Ancillary chunks remain acceptable once their CRC passes.
        if (
            chunk_type not in (b"IHDR", b"IDAT", b"IEND")
            and chunk_type[0] & 0x20 == 0
        ):
            raise PublishError(
                f"Unsupported critical PNG chunk {chunk_type.decode('ascii')}: {label}"
            )

    if not saw_ihdr or not saw_idat or not saw_iend:
        raise PublishError(f"Incomplete PNG structure: {label}")

    stride = width * 4
    expected_raw_size = height * (stride + 1)
    expected_pixel_size = height * stride
    if expected_pixel_size > PNG_MAX_DECODED_BYTES:
        raise PublishError(f"Decoded PNG is too large: {label}")
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(
            b"".join(compressed_parts), expected_raw_size + 1
        )
        if decompressor.unconsumed_tail or len(raw) > expected_raw_size:
            raise PublishError(
                f"PNG expands beyond its declared dimensions: {label}"
            )
        raw += decompressor.flush()
    except zlib.error as exc:
        raise PublishError(f"Invalid PNG zlib stream: {label}") from exc
    if (
        not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
        or len(raw) != expected_raw_size
    ):
        raise PublishError(
            f"PNG decompressed scanline length mismatch: {label} "
            f"(expected {expected_raw_size}, got {len(raw)})"
        )

    for row_index in range(height):
        filter_type = raw[row_index * (stride + 1)]
        if filter_type > 4:
            raise PublishError(f"Unsupported PNG filter {filter_type}: {label}")

    return DecodedRgba8Png(width, height, raw)


def _reconstruct_rgba8_row(
    filtered: bytes,
    previous: bytes,
    filter_type: int,
) -> bytes:
    if filter_type == 0:
        return filtered

    reconstructed = bytearray(len(filtered))
    bytes_per_pixel = 4
    if filter_type == 1:
        for index, value in enumerate(filtered):
            left = reconstructed[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            reconstructed[index] = (value + left) & 0xFF
    elif filter_type == 2:
        for index, value in enumerate(filtered):
            reconstructed[index] = (value + previous[index]) & 0xFF
    elif filter_type == 3:
        for index, value in enumerate(filtered):
            left = reconstructed[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            reconstructed[index] = (value + ((left + previous[index]) // 2)) & 0xFF
    else:
        for index, value in enumerate(filtered):
            left = reconstructed[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            above = previous[index]
            upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            reconstructed[index] = (
                value + _paeth_predictor(left, above, upper_left)
            ) & 0xFF
    return bytes(reconstructed)


def _rgba8_png_pixels_equal(first: DecodedRgba8Png, second: DecodedRgba8Png) -> bool:
    if (first.width, first.height) != (second.width, second.height):
        return False
    stride = first.width * 4
    first_previous = bytes(stride)
    second_previous = bytes(stride)
    for row_index in range(first.height):
        row_offset = row_index * (stride + 1)
        first_row = _reconstruct_rgba8_row(
            first.filtered_scanlines[row_offset + 1 : row_offset + 1 + stride],
            first_previous,
            first.filtered_scanlines[row_offset],
        )
        second_row = _reconstruct_rgba8_row(
            second.filtered_scanlines[row_offset + 1 : row_offset + 1 + stride],
            second_previous,
            second.filtered_scanlines[row_offset],
        )
        if first_row != second_row:
            return False
        first_previous = first_row
        second_previous = second_row
    return True


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


def _replace_exact_once(
    text: str,
    replacements: Iterable[tuple[str, str]],
    label: str,
) -> str:
    result = text
    for old, new in replacements:
        occurrence_count = result.count(old)
        if occurrence_count != 1:
            raise PublishError(
                f"{label} expected exactly one occurrence of a protected scene value, "
                f"found {occurrence_count}: {old}"
            )
        result = result.replace(old, new, 1)
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
        for relative in spine_set.pages:
            if relative not in seen:
                seen.add(relative)
                paths.append(relative)
    for source, _ in UI_COPIES:
        if source not in seen:
            seen.add(source)
            paths.append(source)
    return tuple(paths)


def _check_original_art_guard(
    template_root: Path,
    art_root: Path,
    original_hashes: dict[str, str],
    allow_unchanged: bool,
) -> None:
    unchanged: list[str] = []
    for relative in _protected_art_inputs():
        template_data = _read_required(template_root, relative)
        art_data = _read_required(art_root, relative)
        expected = original_hashes.get(relative)
        if expected is None:
            raise PublishError(f"Extraction manifest has no checksum for: {relative}")
        actual_template_hash = _sha256(template_data).lower()
        if actual_template_hash != expected:
            raise PublishError(
                f"Extracted template checksum mismatch for {relative}: "
                f"manifest={expected}, actual={actual_template_hash}"
            )

        template_png = _decode_rgba8_png(
            template_data, f"template/{relative}"
        )
        art_png = _decode_rgba8_png(
            art_data, f"custom/{relative}"
        )
        if (art_png.width, art_png.height) != (
            template_png.width,
            template_png.height,
        ):
            raise PublishError(
                f"Custom PNG dimensions must match the extracted template for {relative}: "
                f"expected {template_png.width}x{template_png.height}, got "
                f"{art_png.width}x{art_png.height}"
            )
        if _rgba8_png_pixels_equal(template_png, art_png):
            unchanged.append(relative)

    if unchanged and not allow_unchanged:
        formatted = "\n  - ".join(unchanged)
        raise PublishError(
            "Refusing to install unmodified extracted game art. Replace/re-export every "
            "listed image before publishing:\n  - "
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


def _build_outputs(template_root: Path, art_root: Path) -> dict[str, bytes]:
    outputs: dict[str, bytes] = {}

    for spine_set in SPINE_SETS:
        template_atlas_data = _read_required(template_root, spine_set.atlas_source)
        art_atlas_data = _read_required(art_root, spine_set.atlas_source)
        if art_atlas_data != template_atlas_data:
            raise PublishError(
                f"Custom atlas layout must be byte-for-byte identical to the "
                f"v{EXPECTED_GAME_VERSION} template: {spine_set.atlas_source}"
            )
        atlas_text = _read_text(art_root, spine_set.atlas_source)
        _validate_atlas_pages(atlas_text, spine_set.pages, spine_set.name)
        outputs[spine_set.atlas_output] = _spatlas(
            atlas_text, spine_set.atlas_logical_source
        )

        skeleton_data = _read_text(template_root, spine_set.skeleton_data_source)
        if spine_set.vanilla_skeleton_resource not in skeleton_data:
            raise PublishError(
                f"{spine_set.skeleton_data_source} must reference the exact vanilla "
                f"skeleton resource: {spine_set.vanilla_skeleton_resource}"
            )
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
            data = _read_required(art_root, page_source)
            if not data.startswith(PNG_SIGNATURE):
                raise PublishError(f"Expected a real PNG file: {page_source}")
            outputs[(output_page_dir / Path(page_source).name).as_posix()] = data

    for source, output, original_ref, private_ref in SCENES:
        scene = _read_text(template_root, source)
        scene = _replace_required(scene, ((original_ref, private_ref),), source)
        if source == "character_select/scene.tscn":
            scene = _replace_exact_once(
                scene,
                CHARACTER_SELECT_SCENE_REPLACEMENTS,
                source,
            )
        outputs[output] = (_without_uids(scene).rstrip() + "\n").encode("utf-8")

    for source, output in UI_COPIES:
        data = _read_required(art_root, source)
        if not data.startswith(PNG_SIGNATURE):
            raise PublishError(f"Expected a real PNG file: {source}")
        outputs[output] = data

    return outputs


def _expected_output_paths() -> set[str]:
    expected: set[str] = set()
    for spine_set in SPINE_SETS:
        expected.add(spine_set.atlas_output)
        expected.add(spine_set.skeleton_data_output)
        output_page_dir = Path(spine_set.atlas_output).parent
        expected.update(
            (output_page_dir / Path(page).name).as_posix()
            for page in spine_set.pages
        )
    expected.update(output for _, output, _, _ in SCENES)
    expected.update(output for _, output in UI_COPIES)
    if len(expected) != 30:
        raise PublishError(
            f"Publisher invariant failed: expected a 30-file allowlist, got {len(expected)}."
        )
    return expected


def _validate_destination(destination: Path, repo: Path) -> None:
    runtime_root = (repo / "Vivhite" / "Vivhite" / "skins" / "ironclad").resolve()
    work_root = (repo / ".work").resolve()
    if destination == runtime_root:
        return
    try:
        relative_to_work = destination.relative_to(work_root)
    except ValueError as exc:
        raise PublishError(
            "Publishing is restricted to the tracked Ironclad runtime root or a "
            "preview subdirectory below .work."
        ) from exc
    if not relative_to_work.parts:
        raise PublishError("Refusing to use .work itself as the publishing destination.")


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _remove_link_like(path: Path) -> None:
    try:
        path.unlink()
    except (IsADirectoryError, PermissionError):
        path.rmdir()


def _mirror_clean_destination(destination: Path, expected: set[str]) -> None:
    """Remove every non-allowlisted file without following links or junctions."""

    destination.mkdir(parents=True, exist_ok=True)
    for current, directory_names, file_names in os.walk(
        destination, topdown=True, followlinks=False
    ):
        current_path = Path(current)
        for directory_name in list(directory_names):
            directory = current_path / directory_name
            if _is_link_like(directory):
                directory_names.remove(directory_name)
                _remove_link_like(directory)
        for file_name in file_names:
            file_path = current_path / file_name
            relative = file_path.relative_to(destination).as_posix()
            if _is_link_like(file_path) or relative not in expected:
                file_path.unlink()

    expected_directories: set[str] = set()
    for relative in expected:
        parent = Path(relative).parent
        while parent != Path("."):
            expected_directories.add(parent.as_posix())
            parent = parent.parent

    for current, directory_names, _ in os.walk(
        destination, topdown=False, followlinks=False
    ):
        current_path = Path(current)
        for directory_name in directory_names:
            directory = current_path / directory_name
            if not directory.exists() or _is_link_like(directory):
                continue
            relative = directory.relative_to(destination).as_posix()
            if relative not in expected_directories:
                try:
                    directory.rmdir()
                except OSError:
                    # A non-empty directory means a filesystem entry appeared
                    # concurrently. Do not broaden deletion beyond the files
                    # inspected above; the post-write allowlist check will fail.
                    pass


def _write_outputs(destination: Path, outputs: dict[str, bytes], repo: Path) -> None:
    _validate_destination(destination, repo)
    expected = _expected_output_paths()
    actual = set(outputs)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise PublishError(
            "Publisher output set does not match the 30-file allowlist. "
            f"Missing={missing}; unexpected={unexpected}"
        )

    _mirror_clean_destination(destination, expected)
    destination.mkdir(parents=True, exist_ok=True)
    for relative in sorted(outputs):
        target = _safe_relative(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(outputs[relative])

    published = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if published != expected:
        raise PublishError(
            "Destination is not an exact mirror of the 30-file allowlist after publish. "
            f"Missing={sorted(expected - published)}; "
            f"unexpected={sorted(published - expected)}"
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    repo = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template-root",
        "--authoring-root",
        dest="template_root",
        default=str(repo / "assets" / f"ironclad-v{EXPECTED_GAME_VERSION}"),
        help=(
            "Read-only extraction template containing manifest/scenes/tres "
            "(defaults to assets/ironclad-v0.111.0)"
        ),
    )
    parser.add_argument(
        "--art-root",
        default=str(repo / "assets" / "vivhite-ironclad" / "custom"),
        help=(
            "Finished White Qi atlases/PNGs/UI "
            "(defaults to assets/vivhite-ironclad/custom)"
        ),
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
    template_root = Path(args.template_root).resolve()
    art_root = Path(args.art_root).resolve()
    destination = Path(args.destination).resolve()

    _validate_destination(destination, repo)
    if args.allow_unchanged:
        try:
            relative_to_work = destination.relative_to(work_root)
        except ValueError as exc:
            raise PublishError(
                "--allow-unchanged is restricted to a preview destination below .work."
            ) from exc
        if not relative_to_work.parts:
            raise PublishError(
                "--allow-unchanged requires a preview subdirectory below .work."
            )

    _, original_hashes = _load_manifest(template_root)
    _check_original_art_guard(
        template_root,
        art_root,
        original_hashes,
        args.allow_unchanged,
    )
    outputs = _build_outputs(template_root, art_root)
    _write_outputs(destination, outputs, repo)

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
