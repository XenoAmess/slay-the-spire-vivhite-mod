"""Stable identity for the single IndexTTS owner generation.

The repository HEAD advances for ordinary run checkpoints, so it is much too
coarse for deciding whether the detached CUDA owner needs replacement. This
module hashes only the three Python files that execute inside that owner. It is
therefore a code-generation identity, not a repository fingerprint.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


OWNER_PROTOCOL_VERSION = 2
OWNER_FEATURE_VERSION = "preload-all-then-play-handoff-v1"
OWNER_EPOCH_PATHS = (
    "tts/owner_epoch.py",
    "tts/indextts_gpu.py",
    "tts/quipper.py",
)
_EPOCH_RE = re.compile(r"^[0-9a-f]{64}$")


def code_epoch(base_dir: Path | None = None) -> str:
    """Return a deterministic hash of only the runtime owner implementation."""
    root = Path(base_dir or Path(__file__).resolve().parent.parent)
    digest = hashlib.sha256()
    for relative in OWNER_EPOCH_PATHS:
        path = root / Path(relative)
        payload = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def valid_code_epoch(value: object) -> bool:
    return bool(_EPOCH_RE.fullmatch(str(value or "").strip().lower()))


def status_matches(
    status: object,
    *,
    session_id: str,
    expected_epoch: str,
    require_ready: bool = True,
) -> bool:
    """Return whether health belongs to this session's exact owner code."""
    if not isinstance(status, dict):
        return False
    try:
        protocol = int(status.get("owner_protocol_version", 0))
    except (TypeError, ValueError):
        return False
    return (
        (not require_ready or status.get("ready") is True)
        and str(status.get("session_id", "legacy")) == str(session_id)
        and protocol >= OWNER_PROTOCOL_VERSION
        and str(status.get("owner_feature_version", "")) == OWNER_FEATURE_VERSION
        and str(status.get("owner_code_epoch", "")).lower() == expected_epoch.lower()
    )
