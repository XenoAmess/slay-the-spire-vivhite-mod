"""Production-only semantic evidence for one recorded Vivhite promo action.

xAR binds generic evidence files but intentionally does not interpret STS2
state or input semantics. This module closes that project-specific gap. It
only reads an already-recorded sidecar and JSON artifacts; it never launches
the game, injects input, records video, or invokes a media tool.

The contract is deliberately fail-closed. Every artifact is a non-linked,
regular UTF-8 JSON file with a mandatory byte count and SHA-256 binding. A
formal receipt must prove a game-window pointer action and a reconciled
applied outcome. Direct API, Brain, console, debug, pending, fixture, and
synthetic records cannot satisfy this gate. Controlled setup has its own
``staged_setup`` record and must finish before recording and display begin.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_VERSION = 2
ACTION_EVIDENCE_SCHEMA_VERSION = SCHEMA_VERSION
ACTION_EVIDENCE_KIND = "vivhite_promo_action_evidence"
CONTRACT_KIND = ACTION_EVIDENCE_KIND
PROFILE = "production"
FPS = 60
FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080

STATE_SNAPSHOT_KIND = "vivhite_promo_state_snapshot"
ACTION_RECEIPT_DOCUMENT_KIND = "vivhite_promo_action_receipt"
STAGED_SETUP_DOCUMENT_KIND = "vivhite_promo_staged_setup"
STATE_BEFORE_ROLE = "state.before"
ACTION_RECEIPT_ROLE = "action.receipt"
STATE_AFTER_ROLE = "state.after"
STAGED_SETUP_PROVENANCE = "staged_setup"

# STS2 action names needed by the director-v2 mechanism and tower-life takes.
# Console/debug/API setup actions are intentionally not members of this enum.
ACTION_KINDS = frozenset(
    {
        "play_card",
        "end_turn",
        "choose_reward_card",
        "choose_map_node",
        "choose_rest_option",
        "buy_card",
        "buy_relic",
        "buy_potion",
    }
)
FORMAL_ACTION_KINDS = ACTION_KINDS

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9A-F]{64}$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_MAX_JSON_BYTES = 16 * 1024 * 1024

# Payloads are producer-controlled JSON, so an outer production-looking
# envelope is insufficient.  These explicit markers are rejected at every
# nesting depth before any action-specific fields are trusted.
_PROHIBITED_PAYLOAD_MARKERS = frozenset(
    {
        "direct_api",
        "brain",
        "console",
        "debug",
        "fixture",
        "synthetic",
        "pending",
        "failed",
    }
)
_PROHIBITED_PAYLOAD_FLAG_KEYS = frozenset(
    {
        "direct_api",
        "is_direct_api",
        "brain",
        "is_brain",
        "console",
        "is_console",
        "debug",
        "is_debug",
        "fixture",
        "is_fixture",
        "synthetic",
        "is_synthetic",
        "pending",
        "is_pending",
        "failed",
        "is_failed",
    }
)
_PROHIBITED_PAYLOAD_COMPACT_MARKERS = frozenset(
    {
        "directapi",
        "isdirectapi",
        "isbrain",
        "isconsole",
        "isdebug",
        "isfixture",
        "issynthetic",
        "ispending",
        "isfailed",
    }
)

# target.kind, request parameter key, optional required parameter value, and
# optional shop item kind.  The target id must match the named parameter.
_ACTION_PAYLOAD_SPECS: Mapping[str, tuple[str, str, str | None, str | None]] = {
    "play_card": ("card", "card_id", None, None),
    "end_turn": ("end_turn_button", "control", "end_turn", None),
    "choose_reward_card": ("reward_card", "card_id", None, None),
    "choose_map_node": ("map_node", "node_id", None, None),
    "choose_rest_option": ("rest_option", "option", "rest", None),
    "buy_card": ("shop_item", "item_id", None, "card"),
    "buy_relic": ("shop_item", "item_id", None, "relic"),
    "buy_potion": ("shop_item", "item_id", None, "potion"),
}

_ROOT_KEYS = {
    "schema_version",
    "kind",
    "profile",
    "timebase",
    "run_id",
    "take_id",
    "subshot_id",
    "action_id",
    "action_kind",
    "capture_identity",
    "recording_start_frame",
    "display_span",
    "staged_setup",
    "state_before",
    "action_receipt",
    "state_after",
}
_CAPTURE_IDENTITY_KEYS = {
    "session_id",
    "game_run_id",
    "game_process_id",
    "source_video_artifact_id",
    "run_id",
    "take_id",
    "subshot_id",
    "action_id",
}
_ARTIFACT_KEYS = {"path", "bytes", "sha256", "media_type", "document_kind"}
_EVIDENCE_REF_KEYS = {"role", "artifact"}
_SETUP_REF_KEYS = {"provenance", "setup_end_frame", "artifact"}
_STATE_DOCUMENT_KEYS = {
    "schema_version",
    "kind",
    "profile",
    "status",
    "role",
    "capture_identity",
    "frame",
    "monotonic_seconds",
    "state_version",
    "observation_seq",
    "payload",
}
_RECEIPT_DOCUMENT_KEYS = {
    "schema_version",
    "kind",
    "profile",
    "role",
    "capture_identity",
    "action_kind",
    "input_origin",
    "status",
    "stable",
    "applied",
    "delivery",
    "outcome",
    "settled",
    "state_version",
    "observation_seq",
    "pointer_down_frame",
    "pointer_up_frame",
    "settled_frame",
    "pointer_down_monotonic_seconds",
    "pointer_up_monotonic_seconds",
    "settled_monotonic_seconds",
    "state_before_binding",
    "state_after_binding",
    "payload",
}
_SETUP_DOCUMENT_KEYS = {
    "schema_version",
    "kind",
    "profile",
    "provenance",
    "capture_identity",
    "setup_end_frame",
    "payload",
}


class ActionEvidenceError(ValueError):
    """A sidecar cannot certify one production formal action."""


def _object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ActionEvidenceError(f"{context} must be an object")
    return value


def _only_keys(
    value: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
    context: str,
) -> None:
    extras = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if extras:
        raise ActionEvidenceError(
            f"{context} has unsupported fields: {', '.join(extras)}"
        )
    if missing:
        raise ActionEvidenceError(
            f"{context} is missing fields: {', '.join(missing)}"
        )


def _text(value: Any, context: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise ActionEvidenceError(
            f"{context} must be non-empty NUL-free text without outer whitespace"
        )
    return value


def _id(value: Any, context: str) -> str:
    result = _text(value, context)
    if _ID.fullmatch(result) is None:
        raise ActionEvidenceError(f"{context} must be a portable identifier")
    return result


def _integer(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ActionEvidenceError(f"{context} must be an integer >= {minimum}")
    return value


def _seconds(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ActionEvidenceError(f"{context} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ActionEvidenceError(f"{context} must be a finite non-negative number")
    return result


def _sha256(value: Any, context: str) -> str:
    result = _text(value, context)
    if _SHA256.fullmatch(result) is None:
        raise ActionEvidenceError(f"{context} must be an uppercase SHA-256 digest")
    return result


def _relative_json_path(value: Any, context: str) -> str:
    raw = _text(value, context)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
        raise ActionEvidenceError(f"{context} must not contain control characters")
    if "\\" in raw:
        raise ActionEvidenceError(f"{context} must use portable '/' separators")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or _DRIVE.match(raw)
        or ":" in raw
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(part.endswith((" ", ".")) for part in path.parts)
        or any(_WINDOWS_RESERVED.fullmatch(part) for part in path.parts)
        or path.as_posix() != raw
        or path.suffix != ".json"
    ):
        raise ActionEvidenceError(
            f"{context} must be a normalized safe relative path to a .json artifact"
        )
    return raw


def _reject_link_or_reparse(path: Path, context: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ActionEvidenceError(f"could not inspect {context} {path}: {exc}") from exc
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    if stat.S_ISLNK(metadata.st_mode) or attributes & _REPARSE_ATTRIBUTE:
        raise ActionEvidenceError(f"{context} must not be a symlink or reparse point")
    return metadata


def _local_absolute_path(value: str | Path, context: str) -> Path:
    """Return a lexical absolute local path without resolving link components."""

    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise ActionEvidenceError(f"{context} must be a filesystem path") from exc
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ActionEvidenceError(f"{context} must be a non-empty NUL-free path")
    # Covers UNC shares and Windows device namespaces (\\?\ and \\.\).  The
    # latter can bypass ordinary local path and reparse inspection as well.
    if raw.startswith(("\\\\", "//")):
        raise ActionEvidenceError(f"{context} must be a local path, not UNC/device")
    try:
        absolute = Path(os.path.abspath(Path(raw).expanduser()))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ActionEvidenceError(f"{context} is not a usable local path") from exc
    absolute_text = os.fspath(absolute)
    if absolute_text.startswith(("\\\\", "//")):
        raise ActionEvidenceError(f"{context} must resolve to a local path, not UNC")
    return absolute


def _inspect_existing_path_chain(path: Path, context: str) -> None:
    """Reject links/reparse points in every existing component, including leaf."""

    if not path.is_absolute():
        raise ActionEvidenceError(f"{context} must be absolute after normalization")
    parts = path.parts
    cursor = Path(parts[0])
    _reject_link_or_reparse(cursor, context)
    for part in parts[1:]:
        cursor = cursor / part
        _reject_link_or_reparse(cursor, context)


def _read_absolute_regular_unlinked_file(path: Path, context: str) -> bytes:
    _inspect_existing_path_chain(path, context)
    target_metadata = _reject_link_or_reparse(path, context)
    if not stat.S_ISREG(target_metadata.st_mode):
        raise ActionEvidenceError(f"{context} must be a regular file")
    if getattr(target_metadata, "st_nlink", 1) != 1:
        raise ActionEvidenceError(f"{context} must not be a hard-linked file")
    if target_metadata.st_size > _MAX_JSON_BYTES:
        raise ActionEvidenceError(f"{context} exceeds the {_MAX_JSON_BYTES}-byte limit")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            data = handle.read(_MAX_JSON_BYTES + 1)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise ActionEvidenceError(f"could not read {context} {path}: {exc}") from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size)
    identity_after = (after.st_dev, after.st_ino, after.st_size)
    path_identity = (
        target_metadata.st_dev,
        target_metadata.st_ino,
        target_metadata.st_size,
    )
    if identity_before != identity_after or identity_before != path_identity:
        raise ActionEvidenceError(f"{context} changed while it was being read")
    if not stat.S_ISREG(before.st_mode) or getattr(before, "st_nlink", 1) != 1:
        raise ActionEvidenceError(f"{context} must be a non-linked regular file")
    if len(data) > _MAX_JSON_BYTES:
        raise ActionEvidenceError(f"{context} exceeds the {_MAX_JSON_BYTES}-byte limit")
    return data


def _read_regular_unlinked_file(root: Path, relative: str, context: str) -> bytes:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ActionEvidenceError(f"{context} escapes artifact_root") from exc
    return _read_absolute_regular_unlinked_file(candidate, context)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _json_object_from_bytes(data: bytes, context: str) -> Mapping[str, Any]:
    if data.startswith(b"\xef\xbb\xbf"):
        raise ActionEvidenceError(f"{context} must be UTF-8 without a BOM")

    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ActionEvidenceError(
                    f"{context} contains duplicate JSON key {key!r}"
                )
            result[key] = value
        return result

    def no_nonfinite(value: str) -> None:
        raise ActionEvidenceError(f"{context} contains non-finite number {value}")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=no_duplicate_keys,
            parse_constant=no_nonfinite,
        )
    except ActionEvidenceError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ActionEvidenceError(f"{context} must be valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ActionEvidenceError(f"{context} JSON root must be an object")
    return _freeze_json(value)


@dataclass(frozen=True, slots=True)
class CaptureIdentity:
    session_id: str
    game_run_id: str
    game_process_id: str
    source_video_artifact_id: str
    run_id: str
    take_id: str
    subshot_id: str
    action_id: str

    def to_mapping(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "game_run_id": self.game_run_id,
            "game_process_id": self.game_process_id,
            "source_video_artifact_id": self.source_video_artifact_id,
            "run_id": self.run_id,
            "take_id": self.take_id,
            "subshot_id": self.subshot_id,
            "action_id": self.action_id,
        }


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    relative_path: str
    path: Path
    artifact_root: Path
    bytes: int
    sha256: str
    media_type: str
    document_kind: str
    document: Mapping[str, Any]

    def to_mapping(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "document_kind": self.document_kind,
        }

    def verify_unchanged(self) -> None:
        data = _read_regular_unlinked_file(
            self.artifact_root, self.relative_path, f"artifact {self.relative_path}"
        )
        digest = hashlib.sha256(data).hexdigest().upper()
        if len(data) != self.bytes or digest != self.sha256:
            raise ActionEvidenceError(
                f"action evidence artifact changed: {self.relative_path}"
            )
        document = _json_object_from_bytes(data, f"artifact {self.relative_path}")
        if document != self.document:
            raise ActionEvidenceError(
                f"action evidence document changed: {self.relative_path}"
            )


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    role: str
    capture_identity: CaptureIdentity
    frame: int
    monotonic_seconds: float
    state_version: int
    observation_seq: int
    payload: Mapping[str, Any]
    artifact: ArtifactBinding


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    capture_identity: CaptureIdentity
    action_kind: str
    state_version: int
    observation_seq: int
    pointer_down_frame: int
    pointer_up_frame: int
    settled_frame: int
    pointer_down_monotonic_seconds: float
    pointer_up_monotonic_seconds: float
    settled_monotonic_seconds: float
    payload: Mapping[str, Any]
    artifact: ArtifactBinding


@dataclass(frozen=True, slots=True)
class StagedSetup:
    capture_identity: CaptureIdentity
    setup_end_frame: int
    payload: Mapping[str, Any]
    artifact: ArtifactBinding


@dataclass(frozen=True, slots=True)
class DisplaySpan:
    begin_frame: int
    end_frame: int

    def to_mapping(self) -> dict[str, int]:
        return {"begin_frame": self.begin_frame, "end_frame": self.end_frame}


@dataclass(frozen=True, slots=True)
class ActionEvidenceContract:
    capture_identity: CaptureIdentity
    action_kind: str
    recording_start_frame: int
    display_span: DisplaySpan
    state_before: StateSnapshot
    action_receipt: ActionReceipt
    state_after: StateSnapshot
    artifact_root: Path
    staged_setup: StagedSetup | None = None

    @property
    def run_id(self) -> str:
        return self.capture_identity.run_id

    @property
    def take_id(self) -> str:
        return self.capture_identity.take_id

    @property
    def subshot_id(self) -> str:
        return self.capture_identity.subshot_id

    @property
    def action_id(self) -> str:
        return self.capture_identity.action_id

    def artifacts(self) -> tuple[ArtifactBinding, ...]:
        setup = () if self.staged_setup is None else (self.staged_setup.artifact,)
        return (
            self.state_before.artifact,
            self.action_receipt.artifact,
            self.state_after.artifact,
            *setup,
        )

    def verify_unchanged(self) -> None:
        for artifact in self.artifacts():
            artifact.verify_unchanged()

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "kind": ACTION_EVIDENCE_KIND,
            "profile": PROFILE,
            "timebase": {"unit": "frames", "fps": FPS},
            "run_id": self.run_id,
            "take_id": self.take_id,
            "subshot_id": self.subshot_id,
            "action_id": self.action_id,
            "action_kind": self.action_kind,
            "capture_identity": self.capture_identity.to_mapping(),
            "recording_start_frame": self.recording_start_frame,
            "display_span": self.display_span.to_mapping(),
            "state_before": {
                "role": STATE_BEFORE_ROLE,
                "artifact": self.state_before.artifact.to_mapping(),
            },
            "action_receipt": {
                "role": ACTION_RECEIPT_ROLE,
                "artifact": self.action_receipt.artifact.to_mapping(),
            },
            "state_after": {
                "role": STATE_AFTER_ROLE,
                "artifact": self.state_after.artifact.to_mapping(),
            },
        }
        if self.staged_setup is not None:
            result["staged_setup"] = {
                "provenance": STAGED_SETUP_PROVENANCE,
                "setup_end_frame": self.staged_setup.setup_end_frame,
                "artifact": self.staged_setup.artifact.to_mapping(),
            }
        return result


ActionEvidence = ActionEvidenceContract


def _capture_identity(value: Any, context: str) -> CaptureIdentity:
    row = _object(value, context)
    _only_keys(
        row,
        allowed=_CAPTURE_IDENTITY_KEYS,
        required=_CAPTURE_IDENTITY_KEYS,
        context=context,
    )
    values = {
        name: _id(row.get(name), f"{context}.{name}")
        for name in _CAPTURE_IDENTITY_KEYS
    }
    return CaptureIdentity(**values)


def _artifact(
    value: Any,
    *,
    root: Path,
    context: str,
    expected_kind: str,
) -> ArtifactBinding:
    row = _object(value, context)
    _only_keys(
        row,
        allowed=_ARTIFACT_KEYS,
        required=_ARTIFACT_KEYS,
        context=context,
    )
    relative = _relative_json_path(row.get("path"), f"{context}.path")
    declared_bytes = _integer(row.get("bytes"), f"{context}.bytes", minimum=1)
    declared_sha = _sha256(row.get("sha256"), f"{context}.sha256")
    if row.get("media_type") != "application/json":
        raise ActionEvidenceError(f"{context}.media_type must be 'application/json'")
    if row.get("document_kind") != expected_kind:
        raise ActionEvidenceError(f"{context}.document_kind must be {expected_kind!r}")
    data = _read_regular_unlinked_file(root, relative, context)
    actual_sha = hashlib.sha256(data).hexdigest().upper()
    if len(data) != declared_bytes:
        raise ActionEvidenceError(f"{context}.bytes does not match {relative}")
    if actual_sha != declared_sha:
        raise ActionEvidenceError(f"{context}.sha256 does not match {relative}")
    document = _json_object_from_bytes(data, f"artifact {relative}")
    if document.get("kind") != expected_kind:
        raise ActionEvidenceError(
            f"artifact {relative} kind does not match its document_kind"
        )
    return ArtifactBinding(
        relative_path=relative,
        path=root.joinpath(*PurePosixPath(relative).parts),
        artifact_root=root,
        bytes=declared_bytes,
        sha256=declared_sha,
        media_type="application/json",
        document_kind=expected_kind,
        document=document,
    )


def _nonempty_payload(value: Any, context: str) -> Mapping[str, Any]:
    payload = _object(value, context)
    if not payload:
        raise ActionEvidenceError(f"{context} must be a non-empty object")
    return payload


def _normalized_payload_marker(value: str) -> str:
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return re.sub(r"[^a-z0-9]+", "_", camel_split.casefold()).strip("_")


def _contains_prohibited_payload_marker(value: str) -> bool:
    normalized = _normalized_payload_marker(value)
    if (
        normalized in _PROHIBITED_PAYLOAD_MARKERS
        or normalized in _PROHIBITED_PAYLOAD_COMPACT_MARKERS
    ):
        return True
    parts = normalized.split("_")
    if any(
        marker != "direct_api"
        and any(part.startswith(marker) for part in parts)
        for marker in _PROHIBITED_PAYLOAD_MARKERS
    ):
        return True
    if "directapi" in parts:
        return True
    return any(
        parts[index : index + 2] == ["direct", "api"]
        for index in range(max(0, len(parts) - 1))
    )


def _reject_prohibited_payload_markers(value: Any, context: str) -> None:
    """Recursively reject self-declared non-production provenance or state."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ActionEvidenceError(f"{context} contains a non-text JSON key")
            marker = _normalized_payload_marker(key)
            if (
                marker in _PROHIBITED_PAYLOAD_FLAG_KEYS
                or _contains_prohibited_payload_marker(key)
            ):
                raise ActionEvidenceError(
                    f"{context} contains prohibited production flag {key!r}"
                )
            _reject_prohibited_payload_markers(item, f"{context}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_prohibited_payload_markers(item, f"{context}[{index}]")
        return
    if isinstance(value, str):
        if _contains_prohibited_payload_marker(value):
            raise ActionEvidenceError(
                f"{context} contains prohibited production marker {value!r}"
            )


def _receipt_payload(
    value: Any,
    *,
    action_kind: str,
    down_frame: int,
    up_frame: int,
    down_time: float,
    up_time: float,
    action_id: str,
) -> Mapping[str, Any]:
    """Validate the game-client pointer and its exact semantic request.

    Pointer x/y live only in this payload and are game-client pixel
    coordinates.  Frame/time duplicates are mandatory and bound to the
    receipt envelope so an unrelated click cannot be relabelled afterward.
    """

    context = "action_receipt document.payload"
    payload = _nonempty_payload(value, context)
    _reject_prohibited_payload_markers(payload, context)
    _only_keys(
        payload,
        allowed={"pointer", "target", "request"},
        required={"pointer", "target", "request"},
        context=context,
    )

    pointer = _object(payload.get("pointer"), f"{context}.pointer")
    pointer_keys = {
        "button",
        "x",
        "y",
        "down_frame",
        "up_frame",
        "down_monotonic_seconds",
        "up_monotonic_seconds",
    }
    _only_keys(
        pointer,
        allowed=pointer_keys,
        required=pointer_keys,
        context=f"{context}.pointer",
    )
    if pointer.get("button") != "left":
        raise ActionEvidenceError(f"{context}.pointer.button must be 'left'")
    x = _integer(pointer.get("x"), f"{context}.pointer.x")
    y = _integer(pointer.get("y"), f"{context}.pointer.y")
    if x >= FRAME_WIDTH or y >= FRAME_HEIGHT:
        raise ActionEvidenceError(
            "action_receipt payload pointer x/y must be inside the 1920x1080 game client"
        )
    payload_down_frame = _integer(
        pointer.get("down_frame"), f"{context}.pointer.down_frame"
    )
    payload_up_frame = _integer(
        pointer.get("up_frame"), f"{context}.pointer.up_frame"
    )
    payload_down_time = _seconds(
        pointer.get("down_monotonic_seconds"),
        f"{context}.pointer.down_monotonic_seconds",
    )
    payload_up_time = _seconds(
        pointer.get("up_monotonic_seconds"),
        f"{context}.pointer.up_monotonic_seconds",
    )
    if (payload_down_frame, payload_up_frame) != (down_frame, up_frame):
        raise ActionEvidenceError(
            "action_receipt payload pointer frames must match the receipt envelope"
        )
    if (payload_down_time, payload_up_time) != (down_time, up_time):
        raise ActionEvidenceError(
            "action_receipt payload pointer times must match the receipt envelope"
        )

    target = _object(payload.get("target"), f"{context}.target")
    _only_keys(
        target,
        allowed={"kind", "id"},
        required={"kind", "id"},
        context=f"{context}.target",
    )
    target_kind = _text(target.get("kind"), f"{context}.target.kind")
    target_id = _id(target.get("id"), f"{context}.target.id")

    request = _object(payload.get("request"), f"{context}.request")
    _only_keys(
        request,
        allowed={"request_id", "action_kind", "parameters"},
        required={"request_id", "action_kind", "parameters"},
        context=f"{context}.request",
    )
    request_id = _id(request.get("request_id"), f"{context}.request.request_id")
    if request_id != action_id:
        raise ActionEvidenceError(
            "action_receipt payload request.request_id must match capture_identity.action_id"
        )
    if request.get("action_kind") != action_kind:
        raise ActionEvidenceError(
            "action_receipt payload request.action_kind must match action_kind"
        )
    parameters = _object(
        request.get("parameters"), f"{context}.request.parameters"
    )

    expected_target, parameter_key, required_value, shop_item_kind = (
        _ACTION_PAYLOAD_SPECS[action_kind]
    )
    parameter_keys = {parameter_key}
    if shop_item_kind is not None:
        parameter_keys.add("item_kind")
    _only_keys(
        parameters,
        allowed=parameter_keys,
        required=parameter_keys,
        context=f"{context}.request.parameters",
    )
    parameter_value = _id(
        parameters.get(parameter_key),
        f"{context}.request.parameters.{parameter_key}",
    )
    if required_value is not None and parameter_value != required_value:
        raise ActionEvidenceError(
            f"{context}.request.parameters.{parameter_key} must be {required_value!r}"
        )
    if shop_item_kind is not None and parameters.get("item_kind") != shop_item_kind:
        raise ActionEvidenceError(
            f"{context}.request.parameters.item_kind must be {shop_item_kind!r}"
        )
    if target_kind != expected_target:
        raise ActionEvidenceError(
            f"{context}.target.kind must be {expected_target!r} for {action_kind}"
        )
    if target_id != parameter_value:
        raise ActionEvidenceError(
            f"{context}.target.id must match request.parameters.{parameter_key}"
        )
    return payload


def _state_snapshot(
    reference: Any,
    *,
    role: str,
    root: Path,
    context: str,
) -> StateSnapshot:
    row = _object(reference, context)
    _only_keys(
        row,
        allowed=_EVIDENCE_REF_KEYS,
        required=_EVIDENCE_REF_KEYS,
        context=context,
    )
    if row.get("role") != role:
        raise ActionEvidenceError(f"{context}.role must be {role!r}")
    artifact = _artifact(
        row.get("artifact"),
        root=root,
        context=f"{context}.artifact",
        expected_kind=STATE_SNAPSHOT_KIND,
    )
    document = artifact.document
    _only_keys(
        document,
        allowed=_STATE_DOCUMENT_KEYS,
        required=_STATE_DOCUMENT_KEYS,
        context=f"{context} document",
    )
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ActionEvidenceError(f"{context} document schema_version must be 2")
    if document.get("profile") != PROFILE:
        raise ActionEvidenceError(f"{context} document profile must be 'production'")
    if document.get("status") != "observed":
        raise ActionEvidenceError(f"{context} document status must be 'observed'")
    if document.get("role") != role:
        raise ActionEvidenceError(f"{context} document role must be {role!r}")
    identity = _capture_identity(
        document.get("capture_identity"), f"{context} document.capture_identity"
    )
    frame = _integer(document.get("frame"), f"{context} document.frame")
    timestamp = _seconds(
        document.get("monotonic_seconds"),
        f"{context} document.monotonic_seconds",
    )
    version = _integer(
        document.get("state_version"), f"{context} document.state_version", minimum=1
    )
    observation_seq = _integer(
        document.get("observation_seq"),
        f"{context} document.observation_seq",
    )
    payload = _nonempty_payload(document.get("payload"), f"{context} document.payload")
    _reject_prohibited_payload_markers(payload, f"{context} document.payload")
    if payload.get("run_id") != identity.game_run_id:
        raise ActionEvidenceError(
            f"{context} document payload.run_id must match capture_identity.game_run_id"
        )
    if payload.get("state_version") != version:
        raise ActionEvidenceError(
            f"{context} document payload.state_version must match state_version"
        )
    return StateSnapshot(
        role,
        identity,
        frame,
        timestamp,
        version,
        observation_seq,
        payload,
        artifact,
    )


def _status_object(value: Any, context: str, expected: str) -> None:
    row = _object(value, context)
    _only_keys(row, allowed={"status"}, required={"status"}, context=context)
    if row.get("status") != expected:
        raise ActionEvidenceError(f"{context}.status must be {expected!r}")


def _state_binding(value: Any, context: str) -> tuple[str, int, int]:
    row = _object(value, context)
    required = {"sha256", "state_version", "observation_seq"}
    _only_keys(row, allowed=required, required=required, context=context)
    return (
        _sha256(row.get("sha256"), f"{context}.sha256"),
        _integer(row.get("state_version"), f"{context}.state_version", minimum=1),
        _integer(row.get("observation_seq"), f"{context}.observation_seq"),
    )


def _action_receipt(reference: Any, *, root: Path) -> ActionReceipt:
    context = "action_receipt"
    row = _object(reference, context)
    _only_keys(
        row,
        allowed=_EVIDENCE_REF_KEYS,
        required=_EVIDENCE_REF_KEYS,
        context=context,
    )
    if row.get("role") != ACTION_RECEIPT_ROLE:
        raise ActionEvidenceError(
            f"{context}.role must be {ACTION_RECEIPT_ROLE!r}"
        )
    artifact = _artifact(
        row.get("artifact"),
        root=root,
        context=f"{context}.artifact",
        expected_kind=ACTION_RECEIPT_DOCUMENT_KIND,
    )
    document = artifact.document
    _only_keys(
        document,
        allowed=_RECEIPT_DOCUMENT_KEYS,
        required=_RECEIPT_DOCUMENT_KEYS,
        context=f"{context} document",
    )
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ActionEvidenceError("action_receipt document schema_version must be 2")
    if document.get("profile") != PROFILE:
        raise ActionEvidenceError("action_receipt document profile must be 'production'")
    if document.get("role") != ACTION_RECEIPT_ROLE:
        raise ActionEvidenceError("action_receipt document role is invalid")
    identity = _capture_identity(
        document.get("capture_identity"), "action_receipt document.capture_identity"
    )
    action_kind = _text(
        document.get("action_kind"), "action_receipt document.action_kind"
    )
    if action_kind not in ACTION_KINDS:
        raise ActionEvidenceError(
            "action_receipt document.action_kind is not an allowed formal action"
        )
    if document.get("input_origin") != "game_ui_pointer":
        raise ActionEvidenceError(
            "action_receipt document.input_origin must be 'game_ui_pointer'"
        )
    if document.get("status") != "completed":
        raise ActionEvidenceError("action_receipt document.status must be 'completed'")
    if document.get("stable") is not True:
        raise ActionEvidenceError("action_receipt document.stable must be true")
    if document.get("applied") is not True:
        raise ActionEvidenceError("action_receipt document.applied must be true")
    _status_object(document.get("delivery"), "action_receipt document.delivery", "sent")
    _status_object(document.get("outcome"), "action_receipt document.outcome", "applied")
    if document.get("settled") is not True:
        raise ActionEvidenceError("action_receipt document.settled must be true")
    state_version = _integer(
        document.get("state_version"),
        "action_receipt document.state_version",
        minimum=1,
    )
    observation_seq = _integer(
        document.get("observation_seq"),
        "action_receipt document.observation_seq",
    )
    down_frame = _integer(
        document.get("pointer_down_frame"),
        "action_receipt document.pointer_down_frame",
    )
    up_frame = _integer(
        document.get("pointer_up_frame"), "action_receipt document.pointer_up_frame"
    )
    settled_frame = _integer(
        document.get("settled_frame"), "action_receipt document.settled_frame"
    )
    down_time = _seconds(
        document.get("pointer_down_monotonic_seconds"),
        "action_receipt document.pointer_down_monotonic_seconds",
    )
    up_time = _seconds(
        document.get("pointer_up_monotonic_seconds"),
        "action_receipt document.pointer_up_monotonic_seconds",
    )
    settled_time = _seconds(
        document.get("settled_monotonic_seconds"),
        "action_receipt document.settled_monotonic_seconds",
    )
    if not (down_frame < up_frame <= settled_frame):
        raise ActionEvidenceError(
            "receipt frames must satisfy pointer_down < pointer_up <= settled"
        )
    if not (down_time < up_time <= settled_time):
        raise ActionEvidenceError(
            "receipt times must satisfy pointer_down < pointer_up <= settled"
        )
    payload = _receipt_payload(
        document.get("payload"),
        action_kind=action_kind,
        down_frame=down_frame,
        up_frame=up_frame,
        down_time=down_time,
        up_time=up_time,
        action_id=identity.action_id,
    )
    return ActionReceipt(
        capture_identity=identity,
        action_kind=action_kind,
        state_version=state_version,
        observation_seq=observation_seq,
        pointer_down_frame=down_frame,
        pointer_up_frame=up_frame,
        settled_frame=settled_frame,
        pointer_down_monotonic_seconds=down_time,
        pointer_up_monotonic_seconds=up_time,
        settled_monotonic_seconds=settled_time,
        payload=payload,
        artifact=artifact,
    )


def _staged_setup(reference: Any, *, root: Path) -> StagedSetup:
    context = "staged_setup"
    row = _object(reference, context)
    _only_keys(
        row,
        allowed=_SETUP_REF_KEYS,
        required=_SETUP_REF_KEYS,
        context=context,
    )
    if row.get("provenance") != STAGED_SETUP_PROVENANCE:
        raise ActionEvidenceError("staged_setup.provenance must be 'staged_setup'")
    declared_end = _integer(row.get("setup_end_frame"), "staged_setup.setup_end_frame")
    artifact = _artifact(
        row.get("artifact"),
        root=root,
        context="staged_setup.artifact",
        expected_kind=STAGED_SETUP_DOCUMENT_KIND,
    )
    document = artifact.document
    _only_keys(
        document,
        allowed=_SETUP_DOCUMENT_KEYS,
        required=_SETUP_DOCUMENT_KEYS,
        context="staged_setup document",
    )
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ActionEvidenceError("staged_setup document schema_version must be 2")
    if document.get("profile") != PROFILE:
        raise ActionEvidenceError("staged_setup document profile must be 'production'")
    if document.get("provenance") != STAGED_SETUP_PROVENANCE:
        raise ActionEvidenceError("staged_setup document provenance is invalid")
    identity = _capture_identity(
        document.get("capture_identity"), "staged_setup document.capture_identity"
    )
    document_end = _integer(
        document.get("setup_end_frame"), "staged_setup document.setup_end_frame"
    )
    if document_end != declared_end:
        raise ActionEvidenceError(
            "staged_setup setup_end_frame does not match its artifact"
        )
    payload = _nonempty_payload(document.get("payload"), "staged_setup document.payload")
    _reject_prohibited_payload_markers(payload, "staged_setup document.payload")
    return StagedSetup(identity, declared_end, payload, artifact)


def _artifact_root(value: str | Path, context: str) -> Path:
    root = _local_absolute_path(value, context)
    _inspect_existing_path_chain(root, context)
    metadata = _reject_link_or_reparse(root, context)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ActionEvidenceError(f"{context} is not a directory: {root}")
    try:
        resolved = root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ActionEvidenceError(f"could not resolve {context}: {root}") from exc
    if os.fspath(resolved).startswith(("\\\\", "//")):
        raise ActionEvidenceError(f"{context} must resolve to a local path, not UNC")
    return resolved


def _read_contract(path: Path) -> Mapping[str, Any]:
    if path.suffix != ".json":
        raise ActionEvidenceError("action evidence sidecar must use a .json filename")
    data = _read_absolute_regular_unlinked_file(path, "action evidence sidecar")
    return _json_object_from_bytes(data, f"action evidence {path}")


def validate_action_evidence(
    payload: Mapping[str, Any] | str | Path,
    artifact_root: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
) -> ActionEvidenceContract:
    """Validate a production sidecar and all mandatory SHA-bound artifacts."""

    explicit_artifact_root = (
        None if artifact_root is None else _artifact_root(artifact_root, "artifact_root")
    )
    explicit_project_root = (
        None if project_root is None else _artifact_root(project_root, "project_root")
    )
    if explicit_artifact_root is not None and explicit_project_root is not None:
        if explicit_artifact_root != explicit_project_root:
            raise ActionEvidenceError("artifact_root and project_root disagree")
    selected_root = (
        explicit_artifact_root
        if explicit_artifact_root is not None
        else explicit_project_root
    )
    if isinstance(payload, (str, Path)):
        contract_path = _local_absolute_path(payload, "action evidence sidecar")
        if selected_root is not None:
            try:
                contract_path.relative_to(selected_root)
            except ValueError as exc:
                raise ActionEvidenceError(
                    "action evidence sidecar must be inside artifact_root"
                ) from exc
        document = _read_contract(contract_path)
        if selected_root is None:
            selected_root = _artifact_root(
                contract_path.parent, "action evidence sidecar parent"
            )
    else:
        document = _object(payload, "action evidence")
    if selected_root is None:
        raise ActionEvidenceError(
            "artifact_root/project_root is required for in-memory action evidence"
        )
    root = selected_root

    _only_keys(
        document,
        allowed=_ROOT_KEYS,
        required=_ROOT_KEYS - {"staged_setup"},
        context="action evidence",
    )
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ActionEvidenceError("action evidence schema_version must be 2")
    if document.get("kind") != ACTION_EVIDENCE_KIND:
        raise ActionEvidenceError(
            f"action evidence kind must be {ACTION_EVIDENCE_KIND!r}"
        )
    if document.get("profile") != PROFILE:
        raise ActionEvidenceError("action evidence profile must be 'production'")
    timebase = _object(document.get("timebase"), "timebase")
    _only_keys(
        timebase,
        allowed={"unit", "fps"},
        required={"unit", "fps"},
        context="timebase",
    )
    if timebase.get("unit") != "frames" or timebase.get("fps") != FPS:
        raise ActionEvidenceError("timebase must be integer frames at 60 fps")

    root_ids = {
        name: _id(document.get(name), f"action evidence.{name}")
        for name in ("run_id", "take_id", "subshot_id", "action_id")
    }
    identity = _capture_identity(document.get("capture_identity"), "capture_identity")
    for name, expected in root_ids.items():
        if getattr(identity, name) != expected:
            raise ActionEvidenceError(
                f"capture_identity.{name} must match the root {name}"
            )
    action_kind = _text(document.get("action_kind"), "action evidence.action_kind")
    if action_kind not in ACTION_KINDS:
        raise ActionEvidenceError("action evidence.action_kind is not allowed")

    recording_start = _integer(
        document.get("recording_start_frame"), "recording_start_frame"
    )
    span_row = _object(document.get("display_span"), "display_span")
    _only_keys(
        span_row,
        allowed={"begin_frame", "end_frame"},
        required={"begin_frame", "end_frame"},
        context="display_span",
    )
    begin_frame = _integer(span_row.get("begin_frame"), "display_span.begin_frame")
    end_frame = _integer(span_row.get("end_frame"), "display_span.end_frame")
    if end_frame <= begin_frame:
        raise ActionEvidenceError("display_span.end_frame must exceed begin_frame")
    if recording_start > begin_frame:
        raise ActionEvidenceError(
            "recording_start_frame must be <= display_span.begin_frame"
        )
    display_span = DisplaySpan(begin_frame, end_frame)

    before = _state_snapshot(
        document.get("state_before"),
        role=STATE_BEFORE_ROLE,
        root=root,
        context="state_before",
    )
    receipt = _action_receipt(document.get("action_receipt"), root=root)
    after = _state_snapshot(
        document.get("state_after"),
        role=STATE_AFTER_ROLE,
        root=root,
        context="state_after",
    )
    setup = (
        None
        if "staged_setup" not in document
        else _staged_setup(document.get("staged_setup"), root=root)
    )

    for context, candidate in (
        ("state_before", before.capture_identity),
        ("action_receipt", receipt.capture_identity),
        ("state_after", after.capture_identity),
        ("staged_setup", None if setup is None else setup.capture_identity),
    ):
        if candidate is not None and candidate != identity:
            raise ActionEvidenceError(
                f"{context} capture identity must match the root capture_identity"
            )
    if receipt.action_kind != action_kind:
        raise ActionEvidenceError(
            "action_receipt action_kind must match the root action_kind"
        )

    # STS2's state_version is a protocol/schema version, not a changing state
    # counter. Keep it identical and use observation_seq plus frame/time for
    # freshness and ordering.
    if not (
        before.state_version == receipt.state_version == after.state_version
    ):
        raise ActionEvidenceError(
            "state_version must be the same protocol version across the action"
        )
    if not (
        before.observation_seq < receipt.observation_seq <= after.observation_seq
    ):
        raise ActionEvidenceError(
            "observation_seq must satisfy before < receipt <= after"
        )
    if not (
        begin_frame
        <= before.frame
        < receipt.pointer_down_frame
        < receipt.pointer_up_frame
        <= receipt.settled_frame
        < after.frame
        < end_frame
    ):
        raise ActionEvidenceError(
            "frames must satisfy display begin <= before < pointer_down < "
            "pointer_up <= settled < after < display end"
        )
    if not (
        before.monotonic_seconds
        < receipt.pointer_down_monotonic_seconds
        < receipt.pointer_up_monotonic_seconds
        <= receipt.settled_monotonic_seconds
        < after.monotonic_seconds
    ):
        raise ActionEvidenceError(
            "times must satisfy before < pointer_down < pointer_up <= settled < after"
        )

    receipt_document = receipt.artifact.document
    before_binding = _state_binding(
        receipt_document.get("state_before_binding"),
        "action_receipt document.state_before_binding",
    )
    after_binding = _state_binding(
        receipt_document.get("state_after_binding"),
        "action_receipt document.state_after_binding",
    )
    if before_binding != (
        before.artifact.sha256,
        before.state_version,
        before.observation_seq,
    ):
        raise ActionEvidenceError(
            "action_receipt state_before_binding does not bind state_before"
        )
    if after_binding != (
        after.artifact.sha256,
        after.state_version,
        after.observation_seq,
    ):
        raise ActionEvidenceError(
            "action_receipt state_after_binding does not bind state_after"
        )

    artifacts = [before.artifact, receipt.artifact, after.artifact]
    if setup is not None:
        if not (
            setup.setup_end_frame < recording_start
            and setup.setup_end_frame < begin_frame
        ):
            raise ActionEvidenceError(
                "staged_setup.setup_end_frame must be before recording_start_frame "
                "and display_span.begin_frame"
            )
        artifacts.append(setup.artifact)
    path_keys = [os.path.normcase(str(item.path.resolve())) for item in artifacts]
    if len(path_keys) != len(set(path_keys)):
        raise ActionEvidenceError("every evidence role must use a distinct artifact path")
    formal_hashes = [item.sha256 for item in artifacts[:3]]
    if len(formal_hashes) != len(set(formal_hashes)):
        raise ActionEvidenceError(
            "state.before, action.receipt and state.after must have distinct hashes"
        )

    return ActionEvidenceContract(
        capture_identity=identity,
        action_kind=action_kind,
        recording_start_frame=recording_start,
        display_span=display_span,
        state_before=before,
        action_receipt=receipt,
        state_after=after,
        artifact_root=root,
        staged_setup=setup,
    )


def load_action_evidence(
    path: str | Path,
    *,
    artifact_root: str | Path | None = None,
    project_root: str | Path | None = None,
) -> ActionEvidenceContract:
    if not isinstance(path, (str, Path)):
        raise ActionEvidenceError("load_action_evidence requires a sidecar path")
    return validate_action_evidence(
        path, artifact_root=artifact_root, project_root=project_root
    )


validate_action_evidence_contract = validate_action_evidence
load_action_evidence_contract = load_action_evidence
validate_action_evidence_bundle = validate_action_evidence
load_action_evidence_bundle = load_action_evidence
parse_action_evidence = validate_action_evidence


__all__ = [
    "SCHEMA_VERSION",
    "ACTION_EVIDENCE_SCHEMA_VERSION",
    "ACTION_EVIDENCE_KIND",
    "CONTRACT_KIND",
    "PROFILE",
    "FPS",
    "STATE_SNAPSHOT_KIND",
    "ACTION_RECEIPT_DOCUMENT_KIND",
    "STAGED_SETUP_DOCUMENT_KIND",
    "ACTION_KINDS",
    "FORMAL_ACTION_KINDS",
    "STATE_BEFORE_ROLE",
    "ACTION_RECEIPT_ROLE",
    "STATE_AFTER_ROLE",
    "STAGED_SETUP_PROVENANCE",
    "ActionEvidenceError",
    "CaptureIdentity",
    "ArtifactBinding",
    "StateSnapshot",
    "ActionReceipt",
    "StagedSetup",
    "DisplaySpan",
    "ActionEvidenceContract",
    "ActionEvidence",
    "validate_action_evidence",
    "load_action_evidence",
    "validate_action_evidence_contract",
    "load_action_evidence_contract",
    "validate_action_evidence_bundle",
    "load_action_evidence_bundle",
    "parse_action_evidence",
]
