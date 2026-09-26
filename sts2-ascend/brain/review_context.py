"""Small, read-only helpers for bounded review context loading."""
from __future__ import annotations

from pathlib import Path


def read_text_tail(path: Path, max_chars: int) -> tuple[str, bool]:
    """Return the exact UTF-8 suffix without loading an entire historical log.

    Four bytes per requested character cover UTF-8's widest encoding.  A seek
    can split the leading codepoint; it falls outside the returned suffix, so
    replacing that partial codepoint cannot change valid retained text.
    """
    max_chars = max(0, int(max_chars))
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        if not max_chars:
            return "", bool(size)
        start = max(0, size - 4 * max_chars - 3)
        handle.seek(start)
        text = handle.read().decode("utf-8", errors="replace")
    return text[-max_chars:], bool(start or len(text) > max_chars)
