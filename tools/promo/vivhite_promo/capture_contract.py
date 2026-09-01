"""Offline validation for the Vivhite promotional capture contract.

The recorder is deliberately outside this package.  A recorder (normally OBS
or another Windows capture producer) writes a JSON receipt and immutable media
files; this module only checks the receipt, paths, hashes, timeline geometry,
and the project-side capture context.  It never starts a game, invokes OCR, or
repairs a failed take.

The public object can be projected to the generic ``xar_promo.capture`` model
when that optional package is installed.  Keeping the parser dependency-free
is important for ``validate-only`` checks in a clean Vivhite checkout.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
CONTRACT_KIND = "vivhite_promo_capture"
CONTRACT_ID = "vivhite-promo-capture-v1"
GENERIC_RECEIPT_KIND = "xar-promo-capture-receipt"
MODE = "vivhite-promo"
DEFAULT_OVERLAP_POLICY = "forbid"
HUD_START_MARK = "recording_started_after_gameplay_hud"
STOP_MARK = "recording_stop_requested"

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_DRIVE = re.compile(r"^[A-Za-z]:")


class CaptureContractError(ValueError):
    """A capture receipt cannot be safely consumed by the promo pipeline."""


def _object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CaptureContractError(f"{context} must be an object")
    return value


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CaptureContractError(f"{context} must be non-empty NUL-free text")
    return value.strip()


def _id(value: Any, context: str) -> str:
    result = _text(value, context)
    if _ID.fullmatch(result) is None:
        raise CaptureContractError(
            f"{context} must be a portable identifier (letters, digits, '.', '_' or '-')"
        )
    return result


def _number(value: Any, context: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CaptureContractError(f"{context} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (not allow_zero and result == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise CaptureContractError(f"{context} must be finite and {qualifier}")
    return result


def _integer(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CaptureContractError(f"{context} must be an integer >= {minimum}")
    return value


def _sha(value: Any, context: str) -> str:
    result = _text(value, context).upper()
    if _SHA256.fullmatch(result) is None:
        raise CaptureContractError(f"{context} must be a SHA-256 digest")
    return result


def _relative(value: Any, context: str) -> str:
    raw = _text(value, context)
    if "\\" in raw:
        raise CaptureContractError(f"{context} must use portable '/' separators")
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or _DRIVE.match(raw)
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw
    ):
        raise CaptureContractError(f"{context} must be a normalized relative path")
    return path.as_posix()


def _digest_file(path: Path) -> tuple[int, str]:
    try:
        size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise CaptureContractError(f"could not read capture file {path}: {exc}") from exc
    return size, digest.hexdigest().upper()


@dataclass(frozen=True, slots=True)
class CaptureFile:
    """One relative, content-addressed file in a capture run."""

    relative_path: str
    path: Path
    bytes: int
    sha256: str
    media_type: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path).resolve())
        object.__setattr__(self, "relative_path", _relative(self.relative_path, "file.path"))
        object.__setattr__(self, "sha256", _sha(self.sha256, "file.sha256"))
        if isinstance(self.bytes, bool) or not isinstance(self.bytes, int) or self.bytes < 0:
            raise CaptureContractError("file.bytes must be an integer >= 0")
        if self.media_type is not None:
            _text(self.media_type, "file.media_type")

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "path": self.relative_path,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }
        if self.media_type is not None:
            result["media_type"] = self.media_type
        return result

    def verify(self) -> None:
        if not self.path.is_file():
            raise CaptureContractError(f"capture file is missing: {self.relative_path}")
        actual_bytes, actual_sha = _digest_file(self.path)
        if actual_bytes != self.bytes or actual_sha != self.sha256:
            raise CaptureContractError(
                f"capture file changed: {self.relative_path}; expected "
                f"{self.bytes} bytes/{self.sha256}, got {actual_bytes} bytes/{actual_sha}"
            )


@dataclass(frozen=True, slots=True)
class CaptureMark:
    label: str
    seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _id(self.label, "capture mark.label"))
        object.__setattr__(self, "seconds", _number(self.seconds, "capture mark.seconds"))

    def to_mapping(self) -> dict[str, object]:
        return {"label": self.label, "seconds": self.seconds}


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    role: str
    artifact: CaptureFile

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _id(self.role, "evidence.role"))
        if not isinstance(self.artifact, CaptureFile):
            raise CaptureContractError("evidence.artifact must be a CaptureFile")

    def to_mapping(self) -> dict[str, object]:
        return {"role": self.role, "artifact": self.artifact.to_mapping()}


@dataclass(frozen=True, slots=True)
class AudioStemBinding:
    """A project-owned audio stem bound to immutable capture bytes.

    The generic xAR layer does not assign meaning to a stem ID.  The Vivhite
    adapter may use IDs such as ``game``, ``bgm`` or ``sfx`` when it constructs
    an optional :class:`xar_promo.audio.AudioMixSpec`.
    """

    stem_id: str
    artifact: CaptureFile

    def __post_init__(self) -> None:
        object.__setattr__(self, "stem_id", _id(self.stem_id, "audio_stem.stem_id"))
        if not isinstance(self.artifact, CaptureFile):
            raise CaptureContractError("audio_stem.artifact must be a CaptureFile")

    def to_mapping(self) -> dict[str, object]:
        return {"stem_id": self.stem_id, "artifact": self.artifact.to_mapping()}


@dataclass(frozen=True, slots=True)
class CleanSpan:
    span_id: str
    begin_mark: str
    end_mark: str
    begin_seconds: float
    end_seconds: float
    provenance: str
    evidence: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "span_id", _id(self.span_id, "clean span.id"))
        object.__setattr__(self, "begin_mark", _id(self.begin_mark, "clean span.begin_mark"))
        object.__setattr__(self, "end_mark", _id(self.end_mark, "clean span.end_mark"))
        begin = _number(self.begin_seconds, "clean span.begin_seconds")
        end = _number(self.end_seconds, "clean span.end_seconds")
        if end <= begin:
            raise CaptureContractError("clean span end_seconds must exceed begin_seconds")
        object.__setattr__(self, "begin_seconds", begin)
        object.__setattr__(self, "end_seconds", end)
        provenance = _text(self.provenance, "clean span.provenance")
        if provenance not in {"natural", "staged"}:
            raise CaptureContractError("clean span provenance must be natural or staged")
        object.__setattr__(self, "provenance", provenance)
        try:
            evidence = tuple(self.evidence)
        except TypeError as exc:
            raise CaptureContractError("clean span evidence must be a sequence") from exc
        if any(not isinstance(item, EvidenceRef) for item in evidence):
            raise CaptureContractError("clean span evidence must contain EvidenceRef values")
        roles = [item.role for item in evidence]
        if len(roles) != len(set(roles)):
            raise CaptureContractError("clean span evidence roles must be unique")
        paths = [item.artifact.relative_path for item in evidence]
        if len(paths) != len(set(paths)):
            raise CaptureContractError("clean span evidence paths must be unique")
        object.__setattr__(self, "evidence", evidence)

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.begin_seconds

    def to_mapping(self) -> dict[str, object]:
        return {
            "id": self.span_id,
            "begin_mark": self.begin_mark,
            "end_mark": self.end_mark,
            "begin_seconds": self.begin_seconds,
            "end_seconds": self.end_seconds,
            "provenance": self.provenance,
            "evidence": [item.to_mapping() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class CaptureReceipt:
    """The generic portion of a Vivhite receipt."""

    producer_id: str
    producer_version: str
    raw_capture: CaptureFile
    duration_seconds: float
    timebase_unit: str
    fps: int
    marks: tuple[CaptureMark, ...]
    clean_spans: tuple[CleanSpan, ...]
    overlap_policy: str = DEFAULT_OVERLAP_POLICY

    def __post_init__(self) -> None:
        object.__setattr__(self, "producer_id", _id(self.producer_id, "producer.id"))
        object.__setattr__(self, "producer_version", _text(self.producer_version, "producer.version"))
        if not isinstance(self.raw_capture, CaptureFile):
            raise CaptureContractError("raw_capture must be a CaptureFile")
        duration = _number(self.duration_seconds, "capture duration", allow_zero=False)
        object.__setattr__(self, "duration_seconds", duration)
        if self.timebase_unit != "seconds":
            raise CaptureContractError("capture timebase.unit must be 'seconds'")
        object.__setattr__(self, "timebase_unit", _text(self.timebase_unit, "capture timebase.unit"))
        object.__setattr__(self, "fps", _integer(self.fps, "capture timebase.fps", minimum=1))
        if self.overlap_policy not in {"forbid", "allow"}:
            raise CaptureContractError("overlap_policy must be 'forbid' or 'allow'")
        try:
            marks = tuple(self.marks)
            spans = tuple(self.clean_spans)
        except TypeError as exc:
            raise CaptureContractError("capture marks and clean_spans must be sequences") from exc
        if not marks or any(not isinstance(item, CaptureMark) for item in marks):
            raise CaptureContractError("capture marks must contain CaptureMark values")
        if not spans or any(not isinstance(item, CleanSpan) for item in spans):
            raise CaptureContractError("capture clean_spans must contain CleanSpan values")
        object.__setattr__(self, "marks", marks)
        object.__setattr__(self, "clean_spans", spans)
        mark_map: dict[str, float] = {}
        previous = -1.0
        for mark in marks:
            if mark.label in mark_map or mark.seconds < previous or mark.seconds > duration:
                raise CaptureContractError("capture marks must be unique, ordered and within duration")
            mark_map[mark.label] = mark.seconds
            previous = mark.seconds
        if marks[0].label != HUD_START_MARK:
            raise CaptureContractError(f"first capture mark must be {HUD_START_MARK!r}")
        if STOP_MARK not in mark_map or mark_map[STOP_MARK] <= mark_map[HUD_START_MARK]:
            raise CaptureContractError(f"capture marks must contain a positive {STOP_MARK!r} boundary")
        span_ids: set[str] = set()
        previous_begin = -1.0
        previous_end = -1.0
        for span in spans:
            if span.span_id in span_ids:
                raise CaptureContractError(f"capture clean spans repeat {span.span_id!r}")
            if span.begin_mark not in mark_map or span.end_mark not in mark_map:
                raise CaptureContractError(f"clean span {span.span_id!r} references a missing mark")
            if not math.isclose(span.begin_seconds, mark_map[span.begin_mark], rel_tol=0.0, abs_tol=1e-9) or not math.isclose(span.end_seconds, mark_map[span.end_mark], rel_tol=0.0, abs_tol=1e-9):
                raise CaptureContractError(f"clean span {span.span_id!r} seconds do not bind its marks")
            if span.begin_seconds < previous_begin or span.end_seconds > duration:
                raise CaptureContractError("capture clean spans must be ordered and within duration")
            if self.overlap_policy == "forbid" and span.begin_seconds < previous_end:
                raise CaptureContractError(f"clean span {span.span_id!r} overlaps the preceding span")
            span_ids.add(span.span_id)
            previous_begin = span.begin_seconds
            previous_end = max(previous_end, span.end_seconds)

    def mark(self, label: str) -> CaptureMark:
        for mark in self.marks:
            if mark.label == label:
                return mark
        raise KeyError(label)

    def clean_span(self, span_id: str) -> CleanSpan:
        for span in self.clean_spans:
            if span.span_id == span_id:
                return span
        raise KeyError(span_id)

    def to_mapping(self) -> dict[str, object]:
        return {
            "format_version": 1,
            "kind": GENERIC_RECEIPT_KIND,
            "producer": {
                "id": self.producer_id,
                "version": self.producer_version,
            },
            "raw_capture": self.raw_capture.to_mapping(),
            "duration_seconds": self.duration_seconds,
            "timebase": {"unit": self.timebase_unit, "fps": self.fps},
            "marks": [item.to_mapping() for item in self.marks],
            "clean_spans": [item.to_mapping() for item in self.clean_spans],
            "overlap_policy": self.overlap_policy,
        }


@dataclass(frozen=True, slots=True)
class VivhiteCaptureContract:
    """Validated project receipt plus opaque, hash-bound project metadata."""

    contract_version: int
    mode: str
    producer_id: str
    run_id: str
    artifact_root: Path
    capture_receipt: CaptureReceipt
    project_context: Mapping[str, object]
    shot_bindings: Mapping[str, str]
    extra: Mapping[str, object] = field(default_factory=dict)
    audio_stems: tuple[AudioStemBinding, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_root", Path(self.artifact_root).resolve())
        if not isinstance(self.project_context, Mapping):
            raise CaptureContractError("project_context must be a mapping")
        if not isinstance(self.shot_bindings, Mapping):
            raise CaptureContractError("shot_bindings must be a mapping")
        if not isinstance(self.extra, Mapping):
            raise CaptureContractError("extra must be a mapping")
        object.__setattr__(self, "project_context", MappingProxyType(dict(self.project_context)))
        object.__setattr__(self, "shot_bindings", MappingProxyType(dict(self.shot_bindings)))
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))
        object.__setattr__(self, "audio_stems", tuple(self.audio_stems))
        if isinstance(self.contract_version, bool) or not isinstance(self.contract_version, int):
            raise CaptureContractError("contract_version must be an integer")
        if self.contract_version != SCHEMA_VERSION:
            raise CaptureContractError("unsupported Vivhite capture contract version")
        if self.mode != MODE:
            raise CaptureContractError(f"capture mode must be {MODE!r}")
        object.__setattr__(self, "producer_id", _id(self.producer_id, "producer_id"))
        object.__setattr__(self, "run_id", _id(self.run_id, "run_id"))
        if not isinstance(self.capture_receipt, CaptureReceipt):
            raise CaptureContractError("capture_receipt must be a CaptureReceipt")
        if self.capture_receipt.producer_id != self.producer_id:
            raise CaptureContractError("producer_id does not match capture receipt producer")
        if any(not isinstance(item, AudioStemBinding) for item in self.audio_stems):
            raise CaptureContractError("audio_stems must contain AudioStemBinding values")
        stem_ids = [item.stem_id for item in self.audio_stems]
        if len(stem_ids) != len(set(stem_ids)):
            raise CaptureContractError("audio_stems must have unique stem IDs")
        # Keep the in-memory constructor subject to the same root boundary as
        # the JSON loader.  This prevents a caller from bypassing path-escape
        # checks simply by constructing a contract object directly.
        records: list[CaptureFile] = [self.capture_receipt.raw_capture]
        records.extend(
            evidence.artifact
            for span in self.capture_receipt.clean_spans
            for evidence in span.evidence
        )
        records.extend(item.artifact for item in self.audio_stems)
        for record in records:
            expected = (self.artifact_root / Path(*PurePosixPath(record.relative_path).parts)).resolve()
            if expected != record.path:
                raise CaptureContractError(
                    f"capture file {record.relative_path!r} is outside artifact_root"
                )
        for shot_id, span_id in self.shot_bindings.items():
            _id(shot_id, "shot_bindings.shot_id")
            _id(span_id, "shot_bindings.span_id")

    @property
    def raw_capture(self) -> CaptureFile:
        return self.capture_receipt.raw_capture

    @property
    def marks(self) -> tuple[CaptureMark, ...]:
        return self.capture_receipt.marks

    @property
    def clean_spans(self) -> tuple[CleanSpan, ...]:
        return self.capture_receipt.clean_spans

    @property
    def duration_seconds(self) -> float:
        return self.capture_receipt.duration_seconds

    def span_for_shot(self, shot_id: str) -> CleanSpan:
        try:
            span_id = self.shot_bindings[shot_id]
        except KeyError as exc:
            raise CaptureContractError(f"capture has no span binding for shot {shot_id!r}") from exc
        try:
            return self.capture_receipt.clean_span(span_id)
        except KeyError as exc:
            raise CaptureContractError(
                f"shot {shot_id!r} references missing clean span {span_id!r}"
            ) from exc

    def verify_unchanged(self) -> None:
        """Recheck all bytes that can affect a projected shot."""

        records: list[CaptureFile] = [self.raw_capture]
        records.extend(
            evidence.artifact
            for span in self.clean_spans
            for evidence in span.evidence
        )
        records.extend(stem.artifact for stem in self.audio_stems)
        seen: set[Path] = set()
        for record in records:
            if record.path in seen:
                continue
            seen.add(record.path)
            record.verify()

    def to_xar_mapping(self) -> dict[str, object]:
        """Return the generic receipt projection consumed by xAR 0.2+.

        The project sidecar intentionally uses a friendlier ``producer`` and
        ``timebase`` shape.  xAR's canonical wire contract uses an explicit
        adapter/tool identity, a string timebase, and direct file records in
        ``clean_spans.evidence``.  Keeping this conversion explicit prevents
        project vocabulary from leaking into the generic loader.
        """

        receipt = self.capture_receipt
        all_evidence: dict[str, CaptureFile] = {}
        for span in receipt.clean_spans:
            for evidence in span.evidence:
                all_evidence.setdefault(evidence.artifact.relative_path, evidence.artifact)
        for stem in self.audio_stems:
            all_evidence.setdefault(stem.artifact.relative_path, stem.artifact)
        return {
            "format_version": 1,
            "kind": GENERIC_RECEIPT_KIND,
            "producer": {
                "adapter_id": "vivhite",
                "tool": receipt.producer_id,
                "tool_version": receipt.producer_version,
                "operation": "capture",
                "execution": "external",
            },
            "raw_capture": receipt.raw_capture.to_mapping(),
            "duration_seconds": receipt.duration_seconds,
            "timebase": f"1/{receipt.fps}",
            "marks": [item.to_mapping() for item in receipt.marks],
            "clean_spans": [
                {
                    "id": item.span_id,
                    "begin_mark": item.begin_mark,
                    "end_mark": item.end_mark,
                    "begin_seconds": item.begin_seconds,
                    "end_seconds": item.end_seconds,
                    "evidence": [
                        {
                            **evidence.artifact.to_mapping(),
                            "role": evidence.role,
                        }
                        for evidence in item.evidence
                    ],
                }
                for item in receipt.clean_spans
            ],
            "overlap_policy": receipt.overlap_policy,
            "evidence": [
                {**item.to_mapping(), "role": "capture-evidence"}
                for item in all_evidence.values()
            ],
            "metadata": {
                "vivhite_contract": CONTRACT_ID,
                "mode": self.mode,
                "run_id": self.run_id,
                "audio_stems": [stem.stem_id for stem in self.audio_stems],
            },
        }

    def to_mapping(self) -> dict[str, object]:
        return {
            "format_version": 1,
            "kind": CONTRACT_KIND,
            "contract_version": self.contract_version,
            "mode": self.mode,
            "producer_id": self.producer_id,
            "run_id": self.run_id,
            "capture_receipt": self.capture_receipt.to_mapping(),
            "project_context": dict(self.project_context),
            "shot_bindings": [
                {"shot_id": shot_id, "span_id": span_id}
                for shot_id, span_id in self.shot_bindings.items()
            ],
            "audio_stems": [item.to_mapping() for item in self.audio_stems],
        }


def _file_binding(
    value: Any,
    *,
    root: Path,
    context: str,
    verify_files: bool,
) -> CaptureFile:
    row = _object(value, context)
    # The generic xAR projection uses direct fields.  Accept ``binding`` and
    # ``artifact`` wrappers so evidence v2 and this project contract can share
    # the same sidecar vocabulary.
    if isinstance(row.get("binding"), Mapping):
        row = _object(row["binding"], f"{context}.binding")
    elif isinstance(row.get("artifact"), Mapping):
        row = _object(row["artifact"], f"{context}.artifact")
    relative = _relative(row.get("path"), f"{context}.path")
    path = (root / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CaptureContractError(f"{context}.path escapes artifact root") from exc
    record = CaptureFile(
        relative_path=relative,
        path=path,
        bytes=_integer(row.get("bytes"), f"{context}.bytes"),
        sha256=_sha(row.get("sha256"), f"{context}.sha256"),
        media_type=None if row.get("media_type") is None else _text(row.get("media_type"), f"{context}.media_type"),
    )
    if verify_files:
        record.verify()
    return record


def _producer(receipt: Mapping[str, Any], root: Mapping[str, Any]) -> tuple[str, str]:
    value = receipt.get("producer", root.get("producer"))
    if isinstance(value, Mapping):
        return _id(value.get("id", value.get("producer_id")), "producer.id"), _text(
            value.get("version", "1"), "producer.version"
        )
    producer_id = receipt.get("producer_id", root.get("producer_id", value))
    return _id(producer_id, "producer_id"), _text(receipt.get("producer_version", "1"), "producer_version")


def _parse_receipt(
    value: Any,
    *,
    root: Mapping[str, Any],
    artifact_root: Path,
    verify_files: bool,
) -> CaptureReceipt:
    receipt = _object(value, "capture_receipt")
    producer_id, producer_version = _producer(receipt, root)
    raw_value = receipt.get("raw_capture", receipt.get("raw"))
    raw = _file_binding(
        raw_value,
        root=artifact_root,
        context="capture_receipt.raw_capture",
        verify_files=verify_files,
    )
    duration = _number(receipt.get("duration_seconds"), "capture_receipt.duration_seconds", allow_zero=False)
    timebase = _object(receipt.get("timebase"), "capture_receipt.timebase")
    unit = _text(timebase.get("unit"), "capture_receipt.timebase.unit")
    fps = _integer(timebase.get("fps"), "capture_receipt.timebase.fps", minimum=1)

    raw_marks = receipt.get("marks")
    if not isinstance(raw_marks, list) or not raw_marks:
        raise CaptureContractError("capture_receipt.marks must be a non-empty array")
    marks: list[CaptureMark] = []
    seen_marks: set[str] = set()
    prior = -1.0
    for index, item in enumerate(raw_marks):
        row = _object(item, f"capture_receipt.marks[{index}]")
        label = _id(row.get("label"), f"capture_receipt.marks[{index}].label")
        seconds = _number(row.get("seconds"), f"capture_receipt.marks[{index}].seconds")
        if label in seen_marks:
            raise CaptureContractError(f"capture marks repeat {label!r}")
        if seconds < prior or seconds > duration:
            raise CaptureContractError("capture marks must be ordered and within duration")
        seen_marks.add(label)
        marks.append(CaptureMark(label, seconds))
        prior = seconds
    mark_map = {item.label: item.seconds for item in marks}
    if marks[0].label != HUD_START_MARK:
        raise CaptureContractError(f"first capture mark must be {HUD_START_MARK!r}")
    if STOP_MARK not in mark_map or mark_map[STOP_MARK] <= mark_map[HUD_START_MARK]:
        raise CaptureContractError(f"capture marks must contain a positive {STOP_MARK!r} boundary")

    raw_spans = receipt.get("clean_spans")
    if not isinstance(raw_spans, list) or not raw_spans:
        raise CaptureContractError("capture_receipt.clean_spans must be a non-empty array")
    overlap_policy = _text(receipt.get("overlap_policy", DEFAULT_OVERLAP_POLICY), "capture_receipt.overlap_policy")
    if overlap_policy not in {"forbid", "allow"}:
        raise CaptureContractError("capture_receipt.overlap_policy must be 'forbid' or 'allow'")
    spans: list[CleanSpan] = []
    seen_spans: set[str] = set()
    previous_begin = -1.0
    previous_end = -1.0
    for index, item in enumerate(raw_spans):
        row = _object(item, f"capture_receipt.clean_spans[{index}]")
        span_id = _id(row.get("id", row.get("span_id")), f"capture_receipt.clean_spans[{index}].id")
        if span_id in seen_spans:
            raise CaptureContractError(f"capture clean spans repeat {span_id!r}")
        begin_mark = _id(row.get("begin_mark"), f"clean span {span_id}.begin_mark")
        end_mark = _id(row.get("end_mark"), f"clean span {span_id}.end_mark")
        if begin_mark not in mark_map or end_mark not in mark_map:
            raise CaptureContractError(f"clean span {span_id!r} references missing marks")
        begin = mark_map[begin_mark]
        end = mark_map[end_mark]
        if "begin_seconds" in row and _number(row["begin_seconds"], f"clean span {span_id}.begin_seconds") != begin:
            raise CaptureContractError(f"clean span {span_id!r} begin_seconds does not bind its mark")
        if "end_seconds" in row and _number(row["end_seconds"], f"clean span {span_id}.end_seconds") != end:
            raise CaptureContractError(f"clean span {span_id!r} end_seconds does not bind its mark")
        if end <= begin or begin < mark_map[HUD_START_MARK] or end > mark_map[STOP_MARK]:
            raise CaptureContractError(f"clean span {span_id!r} is outside the recorded gameplay window")
        provenance = _text(row.get("provenance", "natural"), f"clean span {span_id}.provenance")
        if provenance not in {"natural", "staged"}:
            raise CaptureContractError(f"clean span {span_id!r}.provenance must be natural or staged")
        raw_evidence = row.get("evidence", [])
        if not isinstance(raw_evidence, list):
            raise CaptureContractError(f"clean span {span_id!r}.evidence must be an array")
        evidence: list[EvidenceRef] = []
        seen_roles: set[str] = set()
        seen_paths: set[str] = set()
        for evidence_index, evidence_item in enumerate(raw_evidence):
            evidence_row = _object(evidence_item, f"clean span {span_id}.evidence[{evidence_index}]")
            role = _id(evidence_row.get("role"), f"clean span {span_id}.evidence[{evidence_index}].role")
            if role in seen_roles:
                raise CaptureContractError(f"clean span {span_id!r} repeats evidence role {role!r}")
            artifact = _file_binding(
                evidence_row,
                root=artifact_root,
                context=f"clean span {span_id}.evidence[{evidence_index}].artifact",
                verify_files=verify_files,
            )
            if artifact.relative_path in seen_paths:
                raise CaptureContractError(
                    f"clean span {span_id!r} repeats evidence path {artifact.relative_path!r}"
                )
            seen_roles.add(role)
            seen_paths.add(artifact.relative_path)
            evidence.append(EvidenceRef(role, artifact))
        # Keep the serialized order canonical.  The generic xAR receipt uses
        # the same order for deterministic projection; sorting here would
        # silently hide a producer bug and could route a shot to the wrong
        # timeline interval.
        if begin < previous_begin:
            raise CaptureContractError(
                "capture clean spans must be ordered by begin_seconds"
            )
        if overlap_policy == "forbid" and begin < previous_end:
            raise CaptureContractError(
                f"clean span {span_id!r} overlaps the preceding span while "
                "overlap_policy=forbid"
            )
        previous_begin = begin
        previous_end = max(previous_end, end)
        seen_spans.add(span_id)
        spans.append(CleanSpan(span_id, begin_mark, end_mark, begin, end, provenance, tuple(evidence)))
    return CaptureReceipt(
        producer_id=producer_id,
        producer_version=producer_version,
        raw_capture=raw,
        duration_seconds=duration,
        timebase_unit=unit,
        fps=fps,
        marks=tuple(marks),
        clean_spans=tuple(spans),
        overlap_policy=overlap_policy,
    )


def _project_context(value: Any) -> Mapping[str, object]:
    row = dict(_object(value, "project_context"))
    required = {
        "game_version",
        "mod_id",
        "mod_version",
        "pck_name",
        "pck_version",
        "ritsu_lib_id",
        "ritsu_lib_version",
        "renderer",
        "resolution",
        "fps",
        "overlays_absent",
        "loading_absent",
        "console_absent",
    }
    missing = sorted(required - set(row))
    if missing:
        raise CaptureContractError("project_context is missing: " + ", ".join(missing))
    for key in (
        "game_version",
        "mod_id",
        "mod_version",
        "pck_name",
        "pck_version",
        "ritsu_lib_id",
        "ritsu_lib_version",
        "renderer",
    ):
        _text(row[key], f"project_context.{key}")
    if row["renderer"].casefold() != "vulkan":
        raise CaptureContractError("project_context.renderer must be Vulkan for the capture baseline")
    resolution = row["resolution"]
    if (
        not isinstance(resolution, (list, tuple))
        or len(resolution) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in resolution)
    ):
        raise CaptureContractError("project_context.resolution must be [width, height]")
    _integer(row["fps"], "project_context.fps", minimum=1)
    for key in ("overlays_absent", "loading_absent", "console_absent"):
        if row[key] is not True:
            raise CaptureContractError(f"project_context.{key} must be true")
    return row


def _shot_bindings(value: Any, spans: Iterable[CleanSpan]) -> Mapping[str, str]:
    rows = value if value is not None else []
    if not isinstance(rows, list):
        raise CaptureContractError("shot_bindings must be an array")
    span_ids = {item.span_id for item in spans}
    result: dict[str, str] = {}
    for index, item in enumerate(rows):
        row = _object(item, f"shot_bindings[{index}]")
        shot_id = _id(row.get("shot_id"), f"shot_bindings[{index}].shot_id")
        span_id = _id(row.get("span_id"), f"shot_bindings[{index}].span_id")
        if shot_id in result:
            raise CaptureContractError(f"shot_bindings repeats {shot_id!r}")
        if span_id not in span_ids:
            raise CaptureContractError(f"shot {shot_id!r} references missing span {span_id!r}")
        result[shot_id] = span_id
    return result


def _audio_stems(
    value: Any,
    *,
    root: Path,
    verify_files: bool,
) -> tuple[AudioStemBinding, ...]:
    """Parse optional project-side stem bindings without interpreting audio."""

    if value is None:
        return ()
    if not isinstance(value, list):
        raise CaptureContractError("audio_stems must be an array")
    result: list[AudioStemBinding] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        row = _object(item, f"audio_stems[{index}]")
        stem_id = _id(row.get("stem_id", row.get("id")), f"audio_stems[{index}].stem_id")
        if stem_id in seen:
            raise CaptureContractError(f"audio_stems repeat {stem_id!r}")
        # Accept both {stem_id, artifact:{...}} and a direct file record with
        # stem_id.  The latter is convenient for producer-generated receipts.
        artifact_value: Any = row.get("artifact", row)
        artifact = _file_binding(
            artifact_value,
            root=root,
            context=f"audio_stems[{index}].artifact",
            verify_files=verify_files,
        )
        seen.add(stem_id)
        result.append(AudioStemBinding(stem_id, artifact))
    return tuple(result)


def validate_capture_contract(
    payload: Mapping[str, Any] | str | Path,
    artifact_root: str | Path | None = None,
    *,
    verify_files: bool = True,
    project_root: str | Path | None = None,
) -> VivhiteCaptureContract:
    """Validate an in-memory or JSON receipt without changing any files.

    ``artifact_root`` is the historical name used by the project adapter.
    ``project_root`` is accepted as a descriptive alias so callers can use the
    same vocabulary as xAR's generic loader.  A path payload defaults its root
    to the containing directory; an in-memory payload must provide one of the
    two root arguments.
    """

    if artifact_root is not None and project_root is not None:
        if Path(artifact_root).expanduser().resolve() != Path(project_root).expanduser().resolve():
            raise CaptureContractError("artifact_root and project_root disagree")
    selected_root = artifact_root if artifact_root is not None else project_root
    if isinstance(payload, (str, Path)):
        contract_path = Path(payload).expanduser().resolve()
        try:
            payload = json.loads(contract_path.read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise CaptureContractError(
                f"could not read capture contract {contract_path}: {exc}"
            ) from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CaptureContractError(
                f"invalid capture contract JSON {contract_path}: {exc}"
            ) from exc
        if selected_root is None:
            selected_root = contract_path.parent
    if selected_root is None:
        raise CaptureContractError(
            "artifact_root/project_root is required for an in-memory capture contract"
        )

    root = Path(selected_root).expanduser().resolve()
    document = _object(payload, "capture contract")
    if document.get("format_version") != 1:
        raise CaptureContractError("capture contract format_version must be 1")
    if document.get("kind") not in {CONTRACT_KIND, GENERIC_RECEIPT_KIND}:
        raise CaptureContractError(f"capture contract kind must be {CONTRACT_KIND!r}")
    contract_version = _integer(document.get("contract_version", 1), "contract_version", minimum=1)
    mode = _text(document.get("mode", MODE), "mode")
    producer_id = _id(document.get("producer_id", "vivhite-offline-producer-v1"), "producer_id")
    run_id = _id(document.get("run_id", "capture-run"), "run_id")
    receipt_value = document.get("capture_receipt", document)
    receipt = _parse_receipt(
        receipt_value,
        root=document,
        artifact_root=root,
        verify_files=verify_files,
    )
    if producer_id != receipt.producer_id:
        raise CaptureContractError("root producer_id does not match capture_receipt producer")
    context = _project_context(document.get("project_context"))
    bindings = _shot_bindings(document.get("shot_bindings"), receipt.clean_spans)
    audio_stems = _audio_stems(
        document.get("audio_stems"), root=root, verify_files=verify_files
    )
    # A producer may reference one file from several roles, but all such
    # references must agree on its immutable binding.  Rejecting conflicting
    # declarations here prevents a later projection from hiding a stale hash
    # behind the first occurrence.
    records: list[CaptureFile] = [receipt.raw_capture]
    records.extend(
        evidence.artifact
        for span in receipt.clean_spans
        for evidence in span.evidence
    )
    records.extend(stem.artifact for stem in audio_stems)
    seen_records: dict[str, tuple[int, str, Path]] = {}
    for record in records:
        binding = (record.bytes, record.sha256, record.path)
        prior = seen_records.get(record.relative_path)
        if prior is not None and prior != binding:
            raise CaptureContractError(
                f"conflicting file bindings for {record.relative_path!r}"
            )
        seen_records[record.relative_path] = binding
    return VivhiteCaptureContract(
        contract_version=contract_version,
        mode=mode,
        producer_id=producer_id,
        run_id=run_id,
        artifact_root=root,
        capture_receipt=receipt,
        project_context=context,
        shot_bindings=bindings,
        audio_stems=audio_stems,
    )


def load_capture_contract(
    path: str | Path,
    *,
    artifact_root: str | Path | None = None,
    verify_files: bool = True,
    project_root: str | Path | None = None,
) -> VivhiteCaptureContract:
    """Read and validate one immutable ``contract.json`` file."""

    contract_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise CaptureContractError(f"could not read capture contract {contract_path}: {exc}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CaptureContractError(f"invalid capture contract JSON {contract_path}: {exc}") from exc
    root = contract_path.parent if artifact_root is None and project_root is None else artifact_root
    return validate_capture_contract(
        payload,
        artifact_root=root,
        project_root=project_root,
        verify_files=verify_files,
    )


__all__ = [
    "SCHEMA_VERSION",
    "CONTRACT_KIND",
    "CONTRACT_ID",
    "GENERIC_RECEIPT_KIND",
    "MODE",
    "HUD_START_MARK",
    "STOP_MARK",
    "CaptureContractError",
    "CaptureFile",
    "CaptureMark",
    "EvidenceRef",
    "AudioStemBinding",
    "CleanSpan",
    "CaptureReceipt",
    "VivhiteCaptureContract",
    "validate_capture_contract",
    "load_capture_contract",
]
