#!/usr/bin/env python3
"""Extract Ironclad Spine and character UI sources from the STS2 v0.111.0 PCK.

The game archive is opened read-only.  Godot import payloads are converted as
follows:

* ``.spskel`` -> the original Spine 4.2 binary ``.skel`` bytes;
* ``.spatlas`` -> the JSON object's plain-text ``atlas_data`` value;
* ``.ctex``/``.s3tc.ctex``/``.bptc.ctex`` -> RGBA PNG through Godot 4.5.1.

Only Python's standard library is required.  A matching Godot executable is
required because hand-decoding Godot's VRAM texture formats would be brittle.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import BinaryIO, Iterable


TOOL_VERSION = "1.1.0"
EXPECTED_GAME_VERSION = "0.111.0"
PCK_MAGIC = b"GDPC"
SUPPORTED_PCK_FORMATS = frozenset({2, 3})
PACK_DIR_ENCRYPTED = 1 << 0
PACK_REL_FILEBASE = 1 << 1
PACK_FILE_ENCRYPTED = 1 << 0
PACK_FILE_REMOVAL = 1 << 1

_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_HEADER_PREFIX = struct.Struct("<4sIIIIIQQ")
_REMAP_RE = re.compile(
    r'^path(?:\.[A-Za-z0-9_]+)?="res://([^"\r\n]+)"', re.MULTILINE
)

# These direct-entry checks deliberately bind the default output label to the
# locally researched game build.  --skip-version-check is available for an
# intentional experiment with a later build.
EXPECTED_V0111_ENTRY_MD5 = {
    "scenes/creature_visuals/ironclad.tscn":
        "b5681b373a7551e14bf78b0f252da1c9",
    "animations/characters/ironclad/ironclad_skel_data.tres":
        "f37ff6757884cc67209652582f4914ea",
    "scenes/screens/char_select/char_select_bg_ironclad.tscn":
        "8fce539648fabfc629d5a035629148a3",
    "scenes/merchant/characters/ironclad_merchant.tscn":
        "0bbc6c58357e3adfe7d840dc420e4b73",
    "scenes/rest_site/characters/ironclad_rest_site.tscn":
        "7e6bf1c5bd279bcf34005eda3005afb7",
}


@dataclass(frozen=True, slots=True)
class AssetSpec:
    logical_path: str
    output_path: str
    category: str
    transform: str


SPINE_ASSETS = (
    # Combat.
    AssetSpec(
        "scenes/creature_visuals/ironclad.tscn",
        "combat/scene.tscn",
        "combat",
        "copy",
    ),
    AssetSpec(
        "animations/characters/ironclad/ironclad_skel_data.tres",
        "combat/combat_skeleton_data.tres",
        "combat",
        "copy",
    ),
    AssetSpec(
        "animations/characters/ironclad/ironclad.skel",
        "combat/ironclad.skel",
        "combat",
        "spskel_to_skel",
    ),
    AssetSpec(
        "animations/characters/ironclad/ironclad.atlas",
        "combat/ironclad.atlas",
        "combat",
        "spatlas_to_atlas",
    ),
    *(
        AssetSpec(
            f"animations/characters/ironclad/ironclad{suffix}.png",
            f"combat/ironclad{suffix}.png",
            "combat",
            "ctex_to_png",
        )
        for suffix in ("", "_2", "_3", "_4")
    ),
    # Character select.
    AssetSpec(
        "scenes/screens/char_select/char_select_bg_ironclad.tscn",
        "character_select/scene.tscn",
        "character_select",
        "copy",
    ),
    AssetSpec(
        "animations/character_select/ironclad/characterselect_ironclad_skel_data.tres",
        "character_select/character_select_skeleton_data.tres",
        "character_select",
        "copy",
    ),
    AssetSpec(
        "animations/character_select/ironclad/characterselect_ironclad.skel",
        "character_select/characterselect_ironclad.skel",
        "character_select",
        "spskel_to_skel",
    ),
    AssetSpec(
        "animations/character_select/ironclad/characterselect_ironclad.atlas",
        "character_select/characterselect_ironclad.atlas",
        "character_select",
        "spatlas_to_atlas",
    ),
    AssetSpec(
        "animations/character_select/ironclad/characterselect_ironclad.png",
        "character_select/characterselect_ironclad.png",
        "character_select",
        "ctex_to_png",
    ),
    # Merchant.  Its skeleton_file_res points to the combat ironclad.skel.
    AssetSpec(
        "scenes/merchant/characters/ironclad_merchant.tscn",
        "merchant/scene.tscn",
        "merchant",
        "copy",
    ),
    AssetSpec(
        "animations/merchant/ironclad/ironclad_merchant_skel_data.tres",
        "merchant/merchant_skeleton_data.tres",
        "merchant",
        "copy",
    ),
    AssetSpec(
        "animations/merchant/ironclad/ironclad_shop.atlas",
        "merchant/ironclad_shop.atlas",
        "merchant",
        "spatlas_to_atlas",
    ),
    *(
        AssetSpec(
            f"animations/merchant/ironclad/ironclad_shop{suffix}.png",
            f"merchant/ironclad_shop{suffix}.png",
            "merchant",
            "ctex_to_png",
        )
        for suffix in ("", "_2", "_3", "_4")
    ),
    # Rest site.
    AssetSpec(
        "scenes/rest_site/characters/ironclad_rest_site.tscn",
        "rest_site/scene.tscn",
        "rest_site",
        "copy",
    ),
    AssetSpec(
        "animations/rest_site/ironclad/rest_site_ironclad_skel_data.tres",
        "rest_site/rest_site_skeleton_data.tres",
        "rest_site",
        "copy",
    ),
    AssetSpec(
        "animations/rest_site/ironclad/restsite_ironclad.skel",
        "rest_site/restsite_ironclad.skel",
        "rest_site",
        "spskel_to_skel",
    ),
    AssetSpec(
        "animations/rest_site/ironclad/restsite_ironclad.atlas",
        "rest_site/restsite_ironclad.atlas",
        "rest_site",
        "spatlas_to_atlas",
    ),
    AssetSpec(
        "animations/rest_site/ironclad/restsite_ironclad.png",
        "rest_site/restsite_ironclad.png",
        "rest_site",
        "ctex_to_png",
    ),
)

UI_ASSETS = (
    AssetSpec(
        "images/ui/top_panel/character_icon_ironclad.png",
        "ui/icon.png",
        "ui",
        "ctex_to_png",
    ),
    AssetSpec(
        "images/ui/top_panel/character_icon_ironclad_outline.png",
        "ui/icon_outline.png",
        "ui",
        "ctex_to_png",
    ),
    AssetSpec(
        "images/packed/character_select/char_select_ironclad.png",
        "ui/select.png",
        "ui",
        "ctex_to_png",
    ),
    AssetSpec(
        "images/packed/character_select/char_select_ironclad_locked.png",
        "ui/select_locked.png",
        "ui",
        "ctex_to_png",
    ),
    AssetSpec(
        "images/packed/map/icons/map_marker_ironclad.png",
        "ui/map_marker.png",
        "ui",
        "ctex_to_png",
    ),
    *(
        AssetSpec(
            f"images/ui/hands/multiplayer_hand_ironclad_{gesture}.png",
            f"ui/multiplayer/{gesture}.png",
            "ui/multiplayer",
            "ctex_to_png",
        )
        for gesture in ("point", "rock", "paper", "scissors")
    ),
)

ASSETS = (*SPINE_ASSETS, *UI_ASSETS)

ANIMATION_SETS = {
    "combat": {
        "authoring_skeleton": "combat/ironclad.skel",
        "ready_runtime_skeleton": (
            "res://Vivhite/skins/ironclad/spine/combat/ironclad.spskel"
        ),
        "animations": [
            "attack",
            "attack_heavy",
            "cast",
            "die",
            "hurt",
            "idle_loop",
            "low_health_loop",
            "relaxed_loop",
        ],
        "required_vfx_slots": ["slash_mesh", "eye_attach_slot"],
        "vfx_events": [
            "attack_slash_start",
            "heavy_slash_start",
            "cast_eyes_start",
            "clear_vfx",
        ],
    },
    "character_select": {
        "authoring_skeleton": "character_select/characterselect_ironclad.skel",
        "ready_runtime_skeleton": (
            "res://Vivhite/skins/ironclad/spine/character_select/"
            "characterselect_ironclad.spskel"
        ),
        "animations": ["animation"],
    },
    "merchant": {
        "authoring_skeleton": "combat/ironclad.skel",
        "ready_runtime_skeleton": (
            "res://Vivhite/skins/ironclad/spine/combat/ironclad.spskel"
        ),
        "shared_with": "combat",
        "animations": ["relaxed_loop"],
    },
    "rest_site": {
        "authoring_skeleton": "rest_site/restsite_ironclad.skel",
        "ready_runtime_skeleton": (
            "res://Vivhite/skins/ironclad/spine/rest_site/restsite_ironclad.spskel"
        ),
        "animations": [
            "glory_loop",
            "hive_loop",
            "overgrowth_loop",
            "_tracks/light_off",
            "_tracks/light_on",
        ],
    },
}

class ExtractionError(RuntimeError):
    """A deterministic, user-facing extraction failure."""


@dataclass(frozen=True, slots=True)
class PckHeader:
    format_version: int
    engine_major: int
    engine_minor: int
    engine_patch: int
    flags: int
    file_base: int
    directory_offset: int
    archive_size: int

    @property
    def engine_version(self) -> str:
        return f"{self.engine_major}.{self.engine_minor}.{self.engine_patch}"


@dataclass(frozen=True, slots=True)
class PckEntry:
    path: str
    offset: int
    absolute_offset: int
    size: int
    md5: str
    flags: int


class PckReader:
    """Minimal read-only reader for Godot 4 PCK format 2/3 archives."""

    def __init__(self, path: Path):
        self.path = path
        self._stream: BinaryIO | None = None
        self.header: PckHeader | None = None
        self._entries: dict[str, PckEntry] = {}

    def __enter__(self) -> "PckReader":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def open(self) -> None:
        if self._stream is not None:
            return
        stream = self.path.open("rb")
        try:
            self._parse(stream)
        except Exception:
            stream.close()
            raise
        self._stream = stream

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def get(self, path: str) -> PckEntry:
        normalized = path.removeprefix("res://")
        try:
            return self._entries[normalized]
        except KeyError as exc:
            raise ExtractionError(f"PCK entry not found: res://{normalized}") from exc

    def read_bytes(self, path: str) -> tuple[PckEntry, bytes]:
        if self._stream is None:
            raise ExtractionError("PCK reader is not open")
        entry = self.get(path)
        if entry.flags & PACK_FILE_ENCRYPTED:
            raise ExtractionError(f"Encrypted PCK entry is unsupported: {entry.path}")
        if entry.flags & PACK_FILE_REMOVAL:
            raise ExtractionError(f"PCK removal entry has no payload: {entry.path}")
        self._stream.seek(entry.absolute_offset)
        data = _read_exact(self._stream, entry.size, f"payload for {entry.path}")
        digest = hashlib.md5(data).hexdigest()  # noqa: S324 - PCK stores MD5.
        if digest != entry.md5:
            raise ExtractionError(
                f"PCK checksum mismatch for {entry.path}: "
                f"directory={entry.md5}, actual={digest}"
            )
        return entry, data

    def directory_sha256(self) -> str:
        if self._stream is None or self.header is None:
            raise ExtractionError("PCK reader is not open")
        self._stream.seek(self.header.directory_offset)
        digest = hashlib.sha256()
        remaining = self.header.archive_size - self.header.directory_offset
        while remaining:
            block = self._stream.read(min(1024 * 1024, remaining))
            if not block:
                raise ExtractionError("Unexpected end of PCK directory")
            digest.update(block)
            remaining -= len(block)
        return digest.hexdigest()

    def _parse(self, stream: BinaryIO) -> None:
        archive_size = stream.seek(0, io.SEEK_END)
        stream.seek(0)
        prefix = _read_exact(stream, _HEADER_PREFIX.size, "PCK header")
        (
            magic,
            format_version,
            engine_major,
            engine_minor,
            engine_patch,
            flags,
            file_base,
            directory_offset,
        ) = _HEADER_PREFIX.unpack(prefix)
        if magic != PCK_MAGIC:
            raise ExtractionError(f"Not a Godot PCK: {self.path}")
        if format_version not in SUPPORTED_PCK_FORMATS:
            raise ExtractionError(f"Unsupported PCK format: {format_version}")
        if flags & PACK_DIR_ENCRYPTED:
            raise ExtractionError("Encrypted PCK directories are unsupported")
        if not 0 <= directory_offset <= archive_size - _U32.size:
            raise ExtractionError("PCK directory offset is outside the archive")

        self.header = PckHeader(
            format_version,
            engine_major,
            engine_minor,
            engine_patch,
            flags,
            file_base,
            directory_offset,
            archive_size,
        )
        stream.seek(directory_offset)
        file_count = _read_u32(stream, "PCK file count")
        minimum_entry_size = 4 + 8 + 8 + 16 + 4
        if file_count > (archive_size - stream.tell()) // minimum_entry_size:
            raise ExtractionError(f"Implausible PCK file count: {file_count}")

        for index in range(file_count):
            path_length = _read_u32(stream, f"path length for entry {index}")
            if path_length == 0 or path_length > 1024 * 1024:
                raise ExtractionError(
                    f"PCK entry {index} has invalid path length {path_length}"
                )
            raw_path = _read_exact(stream, path_length, f"path for entry {index}")
            path = _decode_pck_path(raw_path, index)
            offset = _read_u64(stream, f"offset for {path}")
            size = _read_u64(stream, f"size for {path}")
            md5 = _read_exact(stream, 16, f"MD5 for {path}").hex()
            entry_flags = _read_u32(stream, f"flags for {path}")
            absolute_offset = file_base + offset if flags & PACK_REL_FILEBASE else offset
            if not entry_flags & PACK_FILE_REMOVAL:
                if absolute_offset + size > archive_size:
                    raise ExtractionError(f"PCK payload is outside archive: {path}")
            if path in self._entries:
                raise ExtractionError(f"Duplicate PCK path: {path}")
            self._entries[path] = PckEntry(
                path, offset, absolute_offset, size, md5, entry_flags
            )


def _read_exact(stream: BinaryIO, size: int, context: str) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ExtractionError(
            f"Unexpected end of file while reading {context}: "
            f"wanted {size}, got {len(data)}"
        )
    return data


def _read_u32(stream: BinaryIO, context: str) -> int:
    return _U32.unpack(_read_exact(stream, _U32.size, context))[0]


def _read_u64(stream: BinaryIO, context: str) -> int:
    return _U64.unpack(_read_exact(stream, _U64.size, context))[0]


def _decode_pck_path(raw: bytes, index: int) -> str:
    try:
        path = raw.rstrip(b"\0").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError(f"PCK entry {index} path is not UTF-8") from exc
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or ".." in pure.parts or "\\" in path:
        raise ExtractionError(f"PCK entry {index} has unsafe path: {path!r}")
    return path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_local_prop(name: str) -> str | None:
    props = _repo_root() / "Vivhite" / "local.props"
    if not props.is_file():
        return None
    text = props.read_text(encoding="utf-8")
    match = re.search(rf"<{re.escape(name)}>(.*?)</{re.escape(name)}>", text)
    if not match:
        return None
    value = match.group(1).strip()
    return None if "$(" in value else value


def _resolve_game_dir(argument: str | None) -> Path:
    candidates: list[str] = []
    if argument:
        candidates.append(argument)
    env_value = os.environ.get("STS2_DIR")
    if env_value:
        candidates.append(env_value)
    prop_value = _read_local_prop("Sts2Dir")
    if prop_value:
        candidates.append(prop_value)
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if program_files_x86:
        candidates.append(
            str(Path(program_files_x86) / "Steam/steamapps/common/Slay the Spire 2")
        )
    candidates.append(r"G:\SteamLibrary\steamapps\common\Slay the Spire 2")

    for candidate in candidates:
        path = Path(candidate).expanduser().resolve()
        if (path / "SlayTheSpire2.pck").is_file():
            return path
    shown = "\n  - ".join(candidates) if candidates else "(none)"
    raise ExtractionError(
        "Could not locate SlayTheSpire2.pck. Pass --game-dir. Checked:\n  - "
        + shown
    )


def _resolve_godot(argument: str | None) -> Path:
    candidates: list[str] = []
    if argument:
        candidates.append(argument)
    env_value = os.environ.get("GODOT_EXE")
    if env_value:
        candidates.append(env_value)
    prop_value = _read_local_prop("GodotExe")
    if prop_value:
        candidates.append(prop_value)
    for executable in (
        "Godot_v4.5.1-stable_mono_win64.exe",
        "Godot_v4.5.1-stable_win64.exe",
        "godot4",
        "godot",
    ):
        located = shutil.which(executable)
        if located:
            candidates.append(located)

    for candidate in candidates:
        path = Path(candidate).expanduser().resolve()
        if path.is_file():
            return path
    shown = "\n  - ".join(candidates) if candidates else "(none)"
    raise ExtractionError(
        "Could not locate Godot 4.5.1. Pass --godot. Checked:\n  - " + shown
    )


def _resolve_output(argument: str | None) -> Path:
    default = _repo_root() / "assets" / f"ironclad-v{EXPECTED_GAME_VERSION}"
    output = Path(argument).expanduser().resolve() if argument else default.resolve()
    repository = _repo_root().resolve()
    approved_repository_root = default.resolve()
    inside_repository = output == repository or repository in output.parents
    if inside_repository and output != approved_repository_root:
        raise ExtractionError(
            "Inside this repository, extraction is restricted to the approved "
            f"authoring root {approved_repository_root}. Requested: {output}"
        )
    return output


def _clean_output(output: Path) -> None:
    approved_repository_root = (
        _repo_root() / "assets" / f"ironclad-v{EXPECTED_GAME_VERSION}"
    ).resolve()
    resolved = output.resolve()
    if resolved != approved_repository_root:
        raise ExtractionError(
            "--clean-output is restricted to the approved generated authoring "
            f"root {approved_repository_root}. Requested: {resolved}"
        )
    if resolved.exists():
        shutil.rmtree(resolved)


def _safe_output_path(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ExtractionError(f"Unsafe output path: {relative_path!r}")
    output = (root / Path(*relative.parts)).resolve()
    expected_root = root.resolve()
    if output != expected_root and expected_root not in output.parents:
        raise ExtractionError(f"Output escapes extraction root: {output}")
    return output


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_remap(reader: PckReader, logical_path: str) -> tuple[PckEntry, str]:
    import_path = logical_path + ".import"
    import_entry, import_bytes = reader.read_bytes(import_path)
    text = import_bytes.rstrip(b"\0").decode("utf-8")
    matches = _REMAP_RE.findall(text)
    if not matches:
        raise ExtractionError(f"No imported payload path in res://{import_path}")
    # Windows exports in this build contain one unqualified, S3TC, or BPTC
    # path.  Prefer the first .ctex/.spskel/.spatlas payload deterministically.
    return import_entry, matches[0]


def _verify_v0111(reader: PckReader, skip: bool) -> dict[str, object]:
    mismatches = []
    for path, expected_md5 in EXPECTED_V0111_ENTRY_MD5.items():
        actual_md5 = reader.get(path).md5
        if actual_md5 != expected_md5:
            mismatches.append(
                {"path": f"res://{path}", "expected": expected_md5, "actual": actual_md5}
            )
    if mismatches and not skip:
        details = "\n".join(
            f"  {item['path']}: expected {item['expected']}, got {item['actual']}"
            for item in mismatches
        )
        raise ExtractionError(
            f"PCK does not match the researched STS2 v{EXPECTED_GAME_VERSION} "
            f"fingerprint:\n{details}\nUse --skip-version-check only intentionally."
        )
    return {
        "expected_version": EXPECTED_GAME_VERSION,
        "matched": not mismatches,
        "check_skipped": skip,
        "mismatches": mismatches,
    }


def _base_asset_record(
    spec: AssetSpec,
    archive_entry: PckEntry,
    output_path: Path,
    output_root: Path,
    output_bytes: bytes,
    import_entry: PckEntry | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "category": spec.category,
        "logical_source_path": f"res://{spec.logical_path}",
        "archive_payload_path": f"res://{archive_entry.path}",
        "output_path": output_path.relative_to(output_root).as_posix(),
        "transform": spec.transform,
        "source_size": archive_entry.size,
        "source_md5": archive_entry.md5,
        "output_size": len(output_bytes),
        "output_sha256": _sha256_bytes(output_bytes),
    }
    if import_entry is not None:
        record["import_remap_path"] = f"res://{import_entry.path}"
        record["import_remap_md5"] = import_entry.md5
    return record


def _extract_non_texture(
    reader: PckReader,
    spec: AssetSpec,
    output_root: Path,
) -> dict[str, object]:
    output_path = _safe_output_path(output_root, spec.output_path)
    import_entry: PckEntry | None = None
    if spec.transform == "copy":
        archive_entry, output_bytes = reader.read_bytes(spec.logical_path)
    elif spec.transform == "spskel_to_skel":
        import_entry, payload_path = _parse_remap(reader, spec.logical_path)
        archive_entry, output_bytes = reader.read_bytes(payload_path)
        if not payload_path.endswith(".spskel"):
            raise ExtractionError(f"Expected .spskel payload, got res://{payload_path}")
    elif spec.transform == "spatlas_to_atlas":
        import_entry, payload_path = _parse_remap(reader, spec.logical_path)
        archive_entry, wrapper_bytes = reader.read_bytes(payload_path)
        if not payload_path.endswith(".spatlas"):
            raise ExtractionError(f"Expected .spatlas payload, got res://{payload_path}")
        try:
            wrapper = json.loads(wrapper_bytes.rstrip(b"\0").decode("utf-8"))
            atlas_data = wrapper["atlas_data"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ExtractionError(f"Invalid Spine atlas wrapper: {payload_path}") from exc
        if not isinstance(atlas_data, str):
            raise ExtractionError(f"atlas_data is not text: {payload_path}")
        output_bytes = atlas_data.encode("utf-8")
    else:
        raise ExtractionError(f"Unexpected non-texture transform: {spec.transform}")

    _write_bytes(output_path, output_bytes)
    return _base_asset_record(
        spec,
        archive_entry,
        output_path,
        output_root,
        output_bytes,
        import_entry,
    )


def _prepare_texture_jobs(
    reader: PckReader,
    specs: Iterable[AssetSpec],
    temp_root: Path,
) -> tuple[list[dict[str, str]], dict[str, tuple[AssetSpec, PckEntry, PckEntry]]]:
    jobs: list[dict[str, str]] = []
    context: dict[str, tuple[AssetSpec, PckEntry, PckEntry]] = {}
    input_dir = temp_root / "input"
    output_dir = temp_root / "decoded"
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    for index, spec in enumerate(specs):
        import_entry, payload_path = _parse_remap(reader, spec.logical_path)
        archive_entry, payload = reader.read_bytes(payload_path)
        if not payload_path.endswith(".ctex"):
            raise ExtractionError(f"Expected .ctex payload, got res://{payload_path}")
        job_id = f"texture-{index:03d}"
        input_name = f"{job_id}.ctex"
        output_name = f"{job_id}.png"
        _write_bytes(input_dir / input_name, payload)
        jobs.append(
            {
                "id": job_id,
                "input": f"res://input/{input_name}",
                "output": f"res://decoded/{output_name}",
            }
        )
        context[job_id] = (spec, import_entry, archive_entry)
    return jobs, context


def _decode_textures(
    reader: PckReader,
    specs: list[AssetSpec],
    godot: Path,
    output_root: Path,
) -> tuple[list[dict[str, object]], str]:
    helper_dir = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="vivhite-ironclad-ctex-") as temp_name:
        temp_root = Path(temp_name)
        shutil.copy2(helper_dir / "project.godot", temp_root / "project.godot")
        shutil.copy2(helper_dir / "decode_ctex.gd", temp_root / "decode_ctex.gd")
        jobs, context = _prepare_texture_jobs(reader, specs, temp_root)
        (temp_root / "jobs.json").write_text(
            json.dumps(jobs, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        command = [
            str(godot),
            "--headless",
            "--path",
            str(temp_root),
            "--script",
            "res://decode_ctex.gd",
            "--",
            "--jobs",
            "res://jobs.json",
            "--report",
            "res://decode-report.json",
        ]
        process = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        report_path = temp_root / "decode-report.json"
        if not report_path.is_file():
            raise ExtractionError(
                "Godot texture decoder did not produce a report.\n"
                f"exit={process.returncode}\nstdout:\n{process.stdout}\n"
                f"stderr:\n{process.stderr}"
            )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        failed = [item for item in report.get("results", []) if not item.get("ok")]
        if process.returncode != 0 or failed:
            raise ExtractionError(
                "Godot failed to decode one or more textures.\n"
                f"exit={process.returncode}\nfailures={json.dumps(failed, indent=2)}\n"
                f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
            )

        records: list[dict[str, object]] = []
        for item in report["results"]:
            job_id = item["id"]
            spec, import_entry, archive_entry = context[job_id]
            decoded_path = temp_root / "decoded" / f"{job_id}.png"
            output_path = _safe_output_path(output_root, spec.output_path)
            output_bytes = decoded_path.read_bytes()
            _write_bytes(output_path, output_bytes)
            record = _base_asset_record(
                spec,
                archive_entry,
                output_path,
                output_root,
                output_bytes,
                import_entry,
            )
            record["image"] = {
                "width": item["width"],
                "height": item["height"],
                "format": item["format"],
            }
            records.append(record)
        version_line = next(
            (line.strip() for line in process.stdout.splitlines() if "Godot Engine" in line),
            "Godot version not reported",
        )
        return records, version_line


def _write_manifest(
    output_root: Path,
    pck_path: Path,
    reader: PckReader,
    version_check: dict[str, object],
    godot: Path,
    godot_version_line: str,
    records: list[dict[str, object]],
) -> Path:
    assert reader.header is not None
    manifest = {
        "schema_version": 2,
        "tool": {
            "name": "extract_ironclad_assets.py",
            "version": TOOL_VERSION,
        },
        "game": {
            "expected_version": EXPECTED_GAME_VERSION,
            "pck_file": pck_path.name,
            "pck_size": pck_path.stat().st_size,
            "pck_format": reader.header.format_version,
            "pck_engine_version": reader.header.engine_version,
            "pck_directory_sha256": reader.directory_sha256(),
            "version_fingerprint": version_check,
        },
        "decoder": {
            "executable_name": godot.name,
            "reported_version": godot_version_line,
            "method": "Godot ResourceLoader + Texture2D.get_image + Image.save_png",
        },
        "layout": {
            "authoring_domains": [
                "combat/",
                "merchant/",
                "rest_site/",
                "character_select/",
                "ui/",
            ],
            "note": (
                "These are local authoring sources. A separate publish step "
                "must create private .spskel/.spatlas resources and scenes."
            ),
        },
        "animation_sets": ANIMATION_SETS,
        "assets": sorted(records, key=lambda item: str(item["output_path"])),
        "not_included": [
            "Generic game scripts, shaders, and shared scene dependencies",
            "Original .import files and Godot cache UIDs",
            "Card art, relic art, and timeline portraits",
            "Energy orb, transition, victory, and combat-VFX art",
            "Ready-to-publish mod resources (generated by a separate tool)",
        ],
        "notice": (
            "Extracted Mega Crit assets are for local reference/editing. "
            "Do not redistribute original game art without permission."
        ),
    }
    manifest_path = output_root / "manifest.json"
    _write_bytes(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return manifest_path


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--game-dir",
        help="Slay the Spire 2 install directory (or set STS2_DIR)",
    )
    parser.add_argument(
        "--godot",
        help="Godot 4.5.1 executable (or set GODOT_EXE)",
    )
    parser.add_argument(
        "--output",
        help=(
            "Output root; defaults to <repo>/assets/"
            f"ironclad-v{EXPECTED_GAME_VERSION}"
        ),
    )
    parser.add_argument(
        "--skip-version-check",
        action="store_true",
        help="Allow extraction when known v0.111.0 entry hashes do not match",
    )
    parser.add_argument(
        "--clean-output",
        action="store_true",
        help="Delete/recreate the approved assets/ironclad-v0.111.0 source root",
    )
    return parser.parse_args(argv)


def run(argv: list[str]) -> int:
    args = _parse_args(argv)
    game_dir = _resolve_game_dir(args.game_dir)
    godot = _resolve_godot(args.godot)
    output_root = _resolve_output(args.output)
    pck_path = game_dir / "SlayTheSpire2.pck"
    if args.clean_output:
        _clean_output(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    with PckReader(pck_path) as reader:
        version_check = _verify_v0111(reader, args.skip_version_check)
        for spec in ASSETS:
            if spec.transform != "ctex_to_png":
                records.append(_extract_non_texture(reader, spec, output_root))
        texture_specs = [spec for spec in ASSETS if spec.transform == "ctex_to_png"]
        texture_records, godot_version = _decode_textures(
            reader, texture_specs, godot, output_root
        )
        records.extend(texture_records)
        manifest_path = _write_manifest(
            output_root,
            pck_path,
            reader,
            version_check,
            godot,
            godot_version,
            records,
        )

    print(f"Extracted {len(records)} assets to: {output_root}")
    print(f"Manifest: {manifest_path}")
    return 0


def main() -> None:
    try:
        raise SystemExit(run(sys.argv[1:]))
    except (ExtractionError, OSError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
