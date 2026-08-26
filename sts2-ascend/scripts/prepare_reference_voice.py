from __future__ import annotations

import argparse
import hashlib
import math
import os
import shutil
import sys
import tempfile
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


ASCEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ASCEND_DIR / "tts" / "reference_voice.wav"
DEFAULT_OUTPUT = ASCEND_DIR / "tts" / "reference_voice_15s.wav"
DEFAULT_BACKUP_DIR = ASCEND_DIR / "tts" / "reference_voice_backups"
DEFAULT_CACHE = ASCEND_DIR / "tts" / "reference_voice_15s.indextts25.cache.pt"


@dataclass(frozen=True)
class SilenceSpan:
    start: int
    end: int

    def duration_seconds(self, sample_rate: int) -> float:
        return (self.end - self.start) / sample_rate


@dataclass(frozen=True)
class PreparationResult:
    input_samples: int
    output_samples: int
    sample_rate: int
    silence_spans: tuple[SilenceSpan, ...]
    backup_path: Path | None
    output_sha256: str | None
    changed: bool

    @property
    def input_seconds(self) -> float:
        return self.input_samples / self.sample_rate

    @property
    def output_seconds(self) -> float:
        return self.output_samples / self.sample_rate


def read_pcm16_mono(path: Path) -> tuple[array, int]:
    with wave.open(str(path), "rb") as reader:
        if reader.getnchannels() != 1:
            raise ValueError(f"expected mono WAV, got {reader.getnchannels()} channels: {path}")
        if reader.getsampwidth() != 2:
            raise ValueError(f"expected PCM16 WAV, got {reader.getsampwidth() * 8}-bit: {path}")
        if reader.getcomptype() != "NONE":
            raise ValueError(f"expected uncompressed PCM WAV, got {reader.getcomptype()}: {path}")
        sample_rate = reader.getframerate()
        frames = reader.readframes(reader.getnframes())

    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples, sample_rate


def write_pcm16_mono(path: Path, samples: Sequence[int], sample_rate: int) -> None:
    pcm = array("h", samples)
    if sys.byteorder != "little":
        pcm.byteswap()
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.setcomptype("NONE", "not compressed")
        writer.writeframes(pcm.tobytes())


def detect_silence_spans(
    samples: Sequence[int],
    sample_rate: int,
    *,
    threshold_dbfs: float,
    frame_ms: float,
    hop_ms: float,
    min_silence_ms: float,
) -> tuple[SilenceSpan, ...]:
    if not samples:
        return ()
    frame_samples = max(1, round(sample_rate * frame_ms / 1000.0))
    hop_samples = max(1, round(sample_rate * hop_ms / 1000.0))
    min_silence_samples = max(1, round(sample_rate * min_silence_ms / 1000.0))
    threshold_squared = (32768.0 * 10.0 ** (threshold_dbfs / 20.0)) ** 2

    last_start = max(0, len(samples) - frame_samples)
    frame_starts = list(range(0, last_start + 1, hop_samples))
    if not frame_starts or frame_starts[-1] != last_start:
        frame_starts.append(last_start)

    quiet_starts: list[int] = []
    for start in frame_starts:
        frame = samples[start : min(start + frame_samples, len(samples))]
        mean_square = sum(value * value for value in frame) / len(frame)
        if mean_square <= threshold_squared:
            quiet_starts.append(start)

    spans: list[SilenceSpan] = []
    group_start: int | None = None
    previous_start: int | None = None
    for start in quiet_starts:
        if group_start is None or previous_start is None or start - previous_start > hop_samples:
            if group_start is not None and previous_start is not None:
                end = min(len(samples), previous_start + frame_samples)
                if end - group_start > min_silence_samples:
                    spans.append(SilenceSpan(group_start, end))
            group_start = start
        previous_start = start

    if group_start is not None and previous_start is not None:
        end = min(len(samples), previous_start + frame_samples)
        if end - group_start > min_silence_samples:
            spans.append(SilenceSpan(group_start, end))

    # Leading/trailing silence should be trimmed deliberately, not treated as
    # an internal edit. The current reference has neither in the long-span set.
    return tuple(span for span in spans if span.start > 0 and span.end < len(samples))


def compress_silence_spans(
    samples: Sequence[int],
    spans: Sequence[SilenceSpan],
    sample_rate: int,
    *,
    keep_silence_ms: float,
    crossfade_ms: float,
) -> array:
    keep_samples = max(1, round(sample_rate * keep_silence_ms / 1000.0))
    crossfade_samples = max(0, round(sample_rate * crossfade_ms / 1000.0))
    if crossfade_samples * 2 >= keep_samples:
        raise ValueError("crossfade must be shorter than half the retained silence")

    cuts: list[tuple[int, int]] = []
    previous_end = 0
    for span in spans:
        if span.start < previous_end or span.end > len(samples) or span.start >= span.end:
            raise ValueError(f"invalid or overlapping silence span: {span}")
        span_samples = span.end - span.start
        # Crossfading overlaps the two retained sides. Preserve one additional
        # crossfade window before the splice so the final pause is keep_samples.
        retained_before_crossfade = keep_samples + crossfade_samples
        if span_samples <= retained_before_crossfade:
            previous_end = span.end
            continue
        keep_left = retained_before_crossfade // 2
        keep_right = retained_before_crossfade - keep_left
        cut_start = span.start + keep_left
        cut_end = span.end - keep_right
        if cut_end > cut_start:
            cuts.append((cut_start, cut_end))
        previous_end = span.end

    pieces: list[Sequence[int]] = []
    cursor = 0
    for cut_start, cut_end in cuts:
        pieces.append(samples[cursor:cut_start])
        cursor = cut_end
    pieces.append(samples[cursor:])

    output = array("h")
    for piece in pieces:
        if not piece:
            continue
        fade = min(crossfade_samples, len(output), len(piece))
        if fade:
            blended = array("h")
            for index in range(fade):
                weight = index / (fade - 1) if fade > 1 else 0.5
                value = round(output[-fade + index] * (1.0 - weight) + piece[index] * weight)
                blended.append(max(-32768, min(32767, value)))
            output[-fade:] = blended
            output.extend(piece[fade:])
        else:
            output.extend(piece)
    return output


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _temporary_path(parent: Path, name: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=parent)
    os.close(descriptor)
    return Path(raw_path)


def backup_file(path: Path, backup_dir: Path) -> Path:
    source_sha256 = sha256_file(path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}.backup-{source_sha256[:16]}{path.suffix}"
    if backup_path.exists():
        if sha256_file(backup_path) != source_sha256:
            raise RuntimeError(f"backup path exists with different contents: {backup_path}")
        return backup_path

    temporary = _temporary_path(backup_dir, backup_path.name)
    try:
        shutil.copyfile(path, temporary)
        if sha256_file(temporary) != source_sha256:
            raise RuntimeError(f"backup verification failed: {temporary}")
        os.replace(temporary, backup_path)
    finally:
        temporary.unlink(missing_ok=True)
    return backup_path


def prepare_reference_voice(
    input_path: Path,
    output_path: Path,
    backup_dir: Path,
    *,
    max_seconds: float = 15.0,
    threshold_dbfs: float = -45.0,
    frame_ms: float = 20.0,
    hop_ms: float = 10.0,
    min_silence_ms: float = 400.0,
    keep_silence_ms: float = 200.0,
    crossfade_ms: float = 8.0,
    dry_run: bool = False,
) -> PreparationResult:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("input and output must be different paths")
    if max_seconds <= 0:
        raise ValueError("max_seconds must be positive")
    if min_silence_ms <= keep_silence_ms:
        raise ValueError("min_silence_ms must be greater than keep_silence_ms")

    source_samples, sample_rate = read_pcm16_mono(input_path)
    max_samples = min(len(source_samples), round(sample_rate * max_seconds))
    clipped_samples = source_samples[:max_samples]
    spans = detect_silence_spans(
        clipped_samples,
        sample_rate,
        threshold_dbfs=threshold_dbfs,
        frame_ms=frame_ms,
        hop_ms=hop_ms,
        min_silence_ms=min_silence_ms,
    )
    output_samples = compress_silence_spans(
        clipped_samples,
        spans,
        sample_rate,
        keep_silence_ms=keep_silence_ms,
        crossfade_ms=crossfade_ms,
    )

    if dry_run:
        return PreparationResult(
            input_samples=len(clipped_samples),
            output_samples=len(output_samples),
            sample_rate=sample_rate,
            silence_spans=spans,
            backup_path=None,
            output_sha256=None,
            changed=False,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(output_path.parent, output_path.name)
    backup_path: Path | None = None
    try:
        write_pcm16_mono(temporary, output_samples, sample_rate)
        verified_samples, verified_rate = read_pcm16_mono(temporary)
        if verified_rate != sample_rate or verified_samples != output_samples:
            raise RuntimeError(f"candidate WAV verification failed: {temporary}")
        output_sha256 = sha256_file(temporary)
        if output_path.exists() and sha256_file(output_path) == output_sha256:
            return PreparationResult(
                input_samples=len(clipped_samples),
                output_samples=len(output_samples),
                sample_rate=sample_rate,
                silence_spans=spans,
                backup_path=None,
                output_sha256=output_sha256,
                changed=False,
            )
        if output_path.exists():
            backup_path = backup_file(output_path, backup_dir)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)

    return PreparationResult(
        input_samples=len(clipped_samples),
        output_samples=len(output_samples),
        sample_rate=sample_rate,
        silence_spans=spans,
        backup_path=backup_path,
        output_sha256=sha256_file(output_path),
        changed=True,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the fixed IndexTTS reference by conservatively shortening long pauses.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--threshold-dbfs", type=float, default=-45.0)
    parser.add_argument("--frame-ms", type=float, default=20.0)
    parser.add_argument("--hop-ms", type=float, default=10.0)
    parser.add_argument("--min-silence-ms", type=float, default=400.0)
    parser.add_argument("--keep-silence-ms", type=float, default=200.0)
    parser.add_argument("--crossfade-ms", type=float, default=8.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cache_backup: Path | None = None
    if not args.dry_run and args.cache.is_file():
        cache_backup = backup_file(args.cache, args.backup_dir)
    result = prepare_reference_voice(
        args.input,
        args.output,
        args.backup_dir,
        max_seconds=args.max_seconds,
        threshold_dbfs=args.threshold_dbfs,
        frame_ms=args.frame_ms,
        hop_ms=args.hop_ms,
        min_silence_ms=args.min_silence_ms,
        keep_silence_ms=args.keep_silence_ms,
        crossfade_ms=args.crossfade_ms,
        dry_run=args.dry_run,
    )
    action = "dry-run" if args.dry_run else ("updated" if result.changed else "unchanged")
    print(
        f"reference voice {action}: {result.input_seconds:.3f}s -> "
        f"{result.output_seconds:.3f}s at {result.sample_rate}Hz"
    )
    for index, span in enumerate(result.silence_spans, start=1):
        print(
            f"  pause {index}: {span.start / result.sample_rate:.3f}s -> "
            f"{span.end / result.sample_rate:.3f}s "
            f"({span.duration_seconds(result.sample_rate):.3f}s)"
        )
    if result.backup_path is not None:
        print(f"backup: {result.backup_path}")
        print(f"backup sha256: {sha256_file(result.backup_path)}")
    if cache_backup is not None:
        print(f"cache backup: {cache_backup}")
        print(f"cache backup sha256: {sha256_file(cache_backup)}")
    if result.output_sha256 is not None:
        print(f"output sha256: {result.output_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
