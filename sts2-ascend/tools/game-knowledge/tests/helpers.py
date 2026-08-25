from __future__ import annotations

import hashlib
from pathlib import Path
import struct


def build_pck(
    path: Path,
    files: dict[str, bytes],
    *,
    relative_offsets: bool = True,
    corrupt_path: str | None = None,
) -> None:
    """Build the small subset of Godot PCK v3 used by unit tests."""

    header_size = 112
    file_base = header_size
    flags = 2 if relative_offsets else 0
    payload = bytearray()
    entries: list[tuple[str, int, int, bytes, int]] = []
    for name, data in files.items():
        absolute_offset = file_base + len(payload)
        stored_offset = len(payload) if relative_offsets else absolute_offset
        entries.append((name, stored_offset, len(data), hashlib.md5(data).digest(), 0))
        payload.extend(data)

    directory_offset = file_base + len(payload)
    directory = bytearray(struct.pack("<I", len(entries)))
    for name, offset, size, digest, entry_flags in entries:
        raw_path = name.encode("utf-8") + b"\0"
        raw_path += b"\0" * ((-len(raw_path)) % 4)
        directory.extend(struct.pack("<I", len(raw_path)))
        directory.extend(raw_path)
        directory.extend(struct.pack("<QQ", offset, size))
        directory.extend(digest)
        directory.extend(struct.pack("<I", entry_flags))

    header = struct.pack("<4sIIIIIQQ", b"GDPC", 3, 4, 5, 1, flags, file_base, directory_offset)
    header += bytes(header_size - len(header))
    path.write_bytes(header + payload + directory)
    if corrupt_path is not None:
        names_before = list(files)
        index = names_before.index(corrupt_path)
        payload_offset = file_base + sum(len(files[name]) for name in names_before[:index])
        with path.open("r+b") as stream:
            stream.seek(payload_offset)
            original = stream.read(1)
            stream.seek(payload_offset)
            stream.write(bytes([original[0] ^ 0xFF]))
