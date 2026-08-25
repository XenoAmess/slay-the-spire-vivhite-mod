"""Minimal, read-only reader for Godot 4 PCK archives.

The game currently ships a version-3 PCK.  We intentionally implement only
the small part of the format needed for deterministic inventory and byte
extraction; no Godot installation is required and the archive is never
modified.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path, PurePosixPath
import struct
from typing import BinaryIO, Iterable, Iterator


PCK_MAGIC = b"GDPC"
SUPPORTED_FORMATS = frozenset({2, 3})

PACK_DIR_ENCRYPTED = 1 << 0
PACK_REL_FILEBASE = 1 << 1
PACK_FILE_ENCRYPTED = 1 << 0
PACK_FILE_REMOVAL = 1 << 1

_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_HEADER_PREFIX = struct.Struct("<4sIIIIIQQ")


class PckError(RuntimeError):
    """Raised when a PCK is malformed or uses an unsupported feature."""


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

    @property
    def is_encrypted(self) -> bool:
        return bool(self.flags & PACK_FILE_ENCRYPTED)

    @property
    def is_removal(self) -> bool:
        return bool(self.flags & PACK_FILE_REMOVAL)


def _read_exact(stream: BinaryIO, size: int, *, context: str) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise PckError(
            f"Unexpected end of PCK while reading {context}: "
            f"wanted {size} bytes, got {len(data)}"
        )
    return data


def _read_u32(stream: BinaryIO, *, context: str) -> int:
    return _U32.unpack(_read_exact(stream, _U32.size, context=context))[0]


def _read_u64(stream: BinaryIO, *, context: str) -> int:
    return _U64.unpack(_read_exact(stream, _U64.size, context=context))[0]


def _decode_path(raw: bytes, *, index: int) -> str:
    try:
        path = raw.rstrip(b"\0").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PckError(f"PCK entry {index} has a non-UTF-8 path") from exc

    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or ".." in pure.parts or "\\" in path:
        raise PckError(f"PCK entry {index} has an unsafe path: {path!r}")
    return path


class PckReader:
    """Read a Godot PCK directory and selected file payloads.

    ``PckReader`` keeps one file descriptor open, so callers should use it as
    a context manager.  Entry payload hashes are checked on every read by
    default.  The hash stored by Godot is MD5; it is used here only as the
    archive's integrity checksum, never for trust or authentication.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._stream: BinaryIO | None = None
        self.header: PckHeader | None = None
        self._entries: tuple[PckEntry, ...] = ()
        self._by_path: dict[str, PckEntry] = {}

    def __enter__(self) -> "PckReader":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def open(self) -> None:
        if self._stream is not None:
            return
        try:
            stream = self.path.open("rb")
        except OSError as exc:
            raise PckError(f"Cannot open PCK {self.path}: {exc}") from exc
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

    @property
    def entries(self) -> tuple[PckEntry, ...]:
        self._require_open()
        return self._entries

    def get(self, path: str) -> PckEntry:
        self._require_open()
        normalized = path.removeprefix("res://")
        try:
            return self._by_path[normalized]
        except KeyError as exc:
            raise KeyError(f"PCK entry not found: {normalized}") from exc

    def iter_prefix(self, prefix: str) -> Iterator[PckEntry]:
        self._require_open()
        normalized = prefix.removeprefix("res://")
        return (entry for entry in self._entries if entry.path.startswith(normalized))

    def read_bytes(self, entry_or_path: PckEntry | str, *, verify: bool = True) -> bytes:
        stream = self._require_open()
        entry = self.get(entry_or_path) if isinstance(entry_or_path, str) else entry_or_path
        if entry.is_encrypted:
            raise PckError(f"Encrypted PCK entries are unsupported: {entry.path}")
        if entry.is_removal:
            raise PckError(f"Removal entries have no readable payload: {entry.path}")
        stream.seek(entry.absolute_offset)
        data = _read_exact(stream, entry.size, context=f"payload for {entry.path}")
        if verify:
            digest = hashlib.md5(data).hexdigest()  # noqa: S324 - Godot's format uses MD5.
            if digest != entry.md5:
                raise PckError(
                    f"PCK checksum mismatch for {entry.path}: "
                    f"directory={entry.md5}, payload={digest}"
                )
        return data

    def directory_sha256(self, *, chunk_size: int = 1024 * 1024) -> str:
        """Hash the raw directory table through EOF.

        Every entry record contains the payload's MD5, so this gives a fast,
        stable fingerprint of the complete archive inventory without reading
        the roughly 2 GB game payload a second time.
        """

        stream = self._require_open()
        assert self.header is not None
        stream.seek(self.header.directory_offset)
        digest = hashlib.sha256()
        remaining = self.header.archive_size - self.header.directory_offset
        while remaining:
            block = stream.read(min(chunk_size, remaining))
            if not block:
                raise PckError("Unexpected end of PCK while hashing directory")
            digest.update(block)
            remaining -= len(block)
        return digest.hexdigest()

    def extension_counts(self) -> dict[str, int]:
        counts = Counter(PurePosixPath(entry.path).suffix.lower() for entry in self.entries)
        return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))

    def _require_open(self) -> BinaryIO:
        if self._stream is None:
            raise PckError("PckReader is not open; use it as a context manager")
        return self._stream

    def _parse(self, stream: BinaryIO) -> None:
        archive_size = stream.seek(0, io.SEEK_END)
        stream.seek(0)
        prefix = _read_exact(stream, _HEADER_PREFIX.size, context="PCK header")
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
            raise PckError(f"Not a Godot PCK: expected {PCK_MAGIC!r}, got {magic!r}")
        if format_version not in SUPPORTED_FORMATS:
            raise PckError(
                f"Unsupported PCK format {format_version}; "
                f"supported formats: {sorted(SUPPORTED_FORMATS)}"
            )
        if flags & PACK_DIR_ENCRYPTED:
            raise PckError("Encrypted PCK directories are unsupported")
        if not 0 <= directory_offset <= archive_size - _U32.size:
            raise PckError(
                f"PCK directory offset {directory_offset} is outside a "
                f"{archive_size}-byte archive"
            )

        header = PckHeader(
            format_version=format_version,
            engine_major=engine_major,
            engine_minor=engine_minor,
            engine_patch=engine_patch,
            flags=flags,
            file_base=file_base,
            directory_offset=directory_offset,
            archive_size=archive_size,
        )
        stream.seek(directory_offset)
        file_count = _read_u32(stream, context="PCK file count")
        # Each entry needs at least path length + offset + size + MD5 + flags.
        minimum_entry_size = 4 + 8 + 8 + 16 + 4
        if file_count > (archive_size - stream.tell()) // minimum_entry_size:
            raise PckError(f"Implausible PCK file count: {file_count}")

        entries: list[PckEntry] = []
        by_path: dict[str, PckEntry] = {}
        for index in range(file_count):
            path_length = _read_u32(stream, context=f"path length for entry {index}")
            if path_length == 0 or path_length > 1024 * 1024:
                raise PckError(
                    f"PCK entry {index} has an implausible path length: {path_length}"
                )
            raw_path = _read_exact(stream, path_length, context=f"path for entry {index}")
            path = _decode_path(raw_path, index=index)
            offset = _read_u64(stream, context=f"offset for {path}")
            size = _read_u64(stream, context=f"size for {path}")
            md5 = _read_exact(stream, 16, context=f"MD5 for {path}").hex()
            entry_flags = _read_u32(stream, context=f"flags for {path}")
            absolute_offset = file_base + offset if flags & PACK_REL_FILEBASE else offset

            if not entry_flags & PACK_FILE_REMOVAL:
                end = absolute_offset + size
                if absolute_offset < 0 or end > archive_size:
                    raise PckError(
                        f"PCK payload for {path} is outside the archive: "
                        f"offset={absolute_offset}, size={size}, archive={archive_size}"
                    )
            entry = PckEntry(
                path=path,
                offset=offset,
                absolute_offset=absolute_offset,
                size=size,
                md5=md5,
                flags=entry_flags,
            )
            if path in by_path:
                raise PckError(f"Duplicate PCK path: {path}")
            entries.append(entry)
            by_path[path] = entry

        self.header = header
        self._entries = tuple(entries)
        self._by_path = by_path


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def jsonl_inventory(entries: Iterable[PckEntry]) -> Iterator[dict[str, object]]:
    for entry in entries:
        yield {
            "path": entry.path,
            "size": entry.size,
            "md5": entry.md5,
            "flags": entry.flags,
        }
