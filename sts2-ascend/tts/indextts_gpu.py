"""Low-VRAM IndexTTS-2.5 CUDA engine and its serialized local speech queue."""
from __future__ import annotations

import gc
import hashlib
import itertools
import json
import os
import queue
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).resolve().parent.parent
TTS_DIR = BASE_DIR / "tts"
INDEXTTS_DIR = BASE_DIR / "third_party" / "index-tts"
CONFIG_PATH = BASE_DIR / "brain" / "config.json"
REFERENCE_WAV = TTS_DIR / "reference_voice_15s.wav"
REFERENCE_CACHE = TTS_DIR / "reference_voice_15s.indextts25.cache.pt"
CACHE_FORMAT = 1
MAX_TEXT_CHARS = 1200
SOURCE_PRIORITY = {"conclusion": 0, "review": 20, "manual": 30, "quip": 50}
CONCLUSION_TARGET_CHARS = 10
CONCLUSION_MAX_CHARS = 20
SHORT_TEXT_MAX_MEL_TOKENS = 320
_CONCLUSION_BREAKS = frozenset("。！？!?；;，,、：:.…—")
_CONCLUSION_CLOSERS = frozenset("”’」』】）》）)]}\"'")


def _normalize_speech_text(text: str) -> str:
    return " ".join(str(text or "").split())


def _balanced_chunks(text: str, target_chars: int) -> list[str]:
    """Hard-split one punctuation-free clause without leaving a tiny tail."""
    count = max(1, (len(text) + target_chars - 1) // target_chars)
    base, wider = divmod(len(text), count)
    chunks = []
    offset = 0
    for index in range(count):
        width = base + (1 if index < wider else 0)
        chunk = text[offset:offset + width].strip()
        offset += width
        if chunk:
            chunks.append(chunk)
    return chunks


def split_conclusion_text(
    text: str,
    *,
    target_chars: int = CONCLUSION_TARGET_CHARS,
    max_chars: int = CONCLUSION_MAX_CHARS,
) -> list[str]:
    """Split a conclusion into natural clauses with a strict model-input cap.

    Punctuation is kept for prosody. Naturally terminated clauses up to the
    hard limit stay intact; unterminated clauses above the preferred target
    and every clause above the hard limit are balanced around that target.
    Tiny adjacent clauses are packed when doing so remains safe.
    """
    if target_chars < 1 or max_chars < target_chars:
        raise ValueError("结论分句要求 1 <= target_chars <= max_chars")
    normalized = _normalize_speech_text(text)
    if not normalized:
        return []

    clauses: list[tuple[str, bool]] = []
    start = 0
    index = 0
    while index < len(normalized):
        char = normalized[index]
        # Keep decimal/version dots inside an ASCII token (for example 54.5
        # or IndexTTS2.5); a sentence-ending dot remains a natural break.
        decimal_dot = (
            char == "."
            and index > 0
            and index + 1 < len(normalized)
            and normalized[index - 1].isascii()
            and normalized[index - 1].isalnum()
            and normalized[index + 1].isascii()
            and normalized[index + 1].isalnum()
        )
        if char in _CONCLUSION_BREAKS and not decimal_dot:
            end = index + 1
            # Keep repeated terminators and closing quotes/brackets with the
            # phrase they close instead of creating punctuation-only jobs.
            while (end < len(normalized)
                   and (normalized[end] in _CONCLUSION_BREAKS
                        or normalized[end] in _CONCLUSION_CLOSERS)):
                end += 1
            clause = normalized[start:end].strip()
            if clause:
                clauses.append((clause, True))
            start = end
            index = end
            continue
        index += 1
    tail = normalized[start:].strip()
    if tail:
        clauses.append((tail, False))

    chunks: list[str] = []
    pending = ""

    def append_piece(piece: str) -> None:
        nonlocal pending
        if not piece:
            return
        if pending and len(pending) + len(piece) <= target_chars:
            pending += piece
            return
        if pending:
            chunks.append(pending)
        pending = piece

    for clause, has_natural_end in clauses:
        pieces = ([clause] if (len(clause) <= max_chars
                               and (has_natural_end or len(clause) <= target_chars))
                  else _balanced_chunks(clause, target_chars))
        for piece in pieces:
            append_piece(piece)
    if pending:
        chunks.append(pending)

    # Do not synthesize a one-to-four-character orphan merely because a
    # natural boundary happened to land exactly near the target. Merge it
    # when possible; otherwise borrow a few trailing characters from the
    # previous chunk while preserving order and the hard limit.
    min_tail = max(2, target_chars // 2)
    if len(chunks) > 1 and len(chunks[-1]) < min_tail:
        previous, tail = chunks[-2], chunks[-1]
        if len(previous) + len(tail) <= max_chars:
            chunks[-2:] = [previous + tail]
        elif (previous[-1] not in _CONCLUSION_BREAKS
              and previous[-1] not in _CONCLUSION_CLOSERS):
            needed = min_tail - len(tail)
            if len(previous) > needed:
                chunks[-2:] = [previous[:-needed], previous[-needed:] + tail]

    if any(len(chunk) > max_chars for chunk in chunks):  # defensive invariant
        raise AssertionError("结论分句超过硬上限")
    return chunks


def _config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def worker_port() -> int:
    try:
        port = int((_config().get("tts") or {}).get("worker_port", 17952))
    except (TypeError, ValueError):
        port = 17952
    return port if 1024 <= port <= 65535 else 17952


class IndexTTSGpuEngine:
    """One FP32 CUDA model with reference-only encoders kept off the GPU.

    IndexTTS-2.5 normally places every component on one device.  Its Wav2Vec
    reference encoder alone is about 2.2 GiB and is unused after a fixed voice
    has been cached.  We construct on CPU, prepare/load that cache, and then
    move only the per-utterance synthesis modules to CUDA.  This keeps Pascal
    on its native fast FP32 path and avoids BF16 emulation.
    """

    def __init__(self, log: Callable[[str], None]) -> None:
        self.log = log
        cfg = _config().get("tts") or {}
        self.device = str(cfg.get("device") or "cuda:0")
        self.precision = str(cfg.get("precision") or "fp32").lower()
        self.duration_factor = float(cfg.get("duration_factor", 0.9))
        self.num_beams = max(1, int(cfg.get("num_beams", 1)))
        if not self.device.startswith("cuda"):
            raise RuntimeError(f"IndexTTS 已配置为 GPU-only，device 不能是 {self.device!r}")
        if self.precision not in ("fp32", "fp16"):
            raise RuntimeError(f"IndexTTS precision 仅支持 fp32/fp16，收到 {self.precision!r}")

        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("IndexTTS 已配置为 GPU-only，但 torch.cuda.is_available() 为 False")
        index = int(self.device.split(":", 1)[1]) if ":" in self.device else 0
        if index >= torch.cuda.device_count():
            raise RuntimeError(f"CUDA 设备不存在：{self.device}")
        self.torch = torch
        self.gpu_name = torch.cuda.get_device_name(index)
        self.total_vram_gb = torch.cuda.get_device_properties(index).total_memory / 1024 ** 3
        native_bf16 = bool(torch.cuda.is_bf16_supported(including_emulation=False))
        self.log(
            f"CUDA 检查通过：{self.gpu_name} {self.total_vram_gb:.1f}GiB，"
            f"原生 BF16={native_bf16}；使用 {self.precision.upper()} "
            f"（Pascal 上避免 BF16 模拟）"
        )

        import sys
        sys.path.insert(0, str(INDEXTTS_DIR))
        from indextts.infer_v2_5 import IndexTTS2

        checkpoints = INDEXTTS_DIR / "checkpoints"
        if not (checkpoints / "config.yaml").exists():
            raise FileNotFoundError("IndexTTS checkpoints/config.yaml 不存在")
        started = time.monotonic()
        # CPU construction is deliberate: the stock constructor otherwise peaks
        # above 6 GiB before the reference-only model can be discarded.
        self.tts = IndexTTS2(
            cfg_path=str(checkpoints / "config.yaml"),
            model_dir=str(checkpoints),
            use_bf16=False,
            device="cpu",
            use_cuda_kernel=False,
            use_accel=False,
            use_torch_compile=False,
            use_qwen_emo=False,
        )
        cache = self._load_or_build_reference_cache()
        self._discard_reference_encoders()
        self._move_runtime_to_cuda(cache)
        self.log(
            f"IndexTTS-2.5 GPU 引擎就绪：{self.device}/{self.precision.upper()}，"
            f"耗时 {time.monotonic() - started:.1f}s，{self._memory_summary()}"
        )

    def _cache_fingerprint(self) -> str:
        checkpoints = INDEXTTS_DIR / "checkpoints"
        digest = hashlib.sha256()
        for path in (
            REFERENCE_WAV,
            checkpoints / "config.yaml",
            INDEXTTS_DIR / "indextts" / "infer_v2_5.py",
        ):
            digest.update(path.read_bytes())
        for relative in (
            "gpt.pth", "codec.pth", "s2mel.pth",
            "hf_cache/w2v-bert-2.0/model.safetensors",
            "hf_cache/campplus_cn_common.bin",
            "hf_cache/bigvgan/bigvgan_generator.pt",
        ):
            path = checkpoints / relative
            if path.exists():
                stat = path.stat()
                digest.update(relative.encode("utf-8"))
                digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
        return digest.hexdigest()

    def _load_or_build_reference_cache(self) -> dict:
        fingerprint = self._cache_fingerprint()
        if REFERENCE_CACHE.exists():
            try:
                payload = self.torch.load(
                    str(REFERENCE_CACHE), map_location="cpu", weights_only=True,
                )
                if (payload.get("format") == CACHE_FORMAT
                        and payload.get("fingerprint") == fingerprint):
                    self.log("命中白绮参考音频条件缓存")
                    return payload["tensors"]
                self.log("白绮参考缓存已过期，重新生成")
            except Exception as exc:
                self.log(f"白绮参考缓存不可用，重新生成：{exc}")

        tensors = self._build_reference_cache_on_cuda()
        payload = {"format": CACHE_FORMAT, "fingerprint": fingerprint, "tensors": tensors}
        tmp_path = REFERENCE_CACHE.with_suffix(f".tmp.{os.getpid()}.pt")
        try:
            self.torch.save(payload, str(tmp_path))
            os.replace(tmp_path, REFERENCE_CACHE)
            self.log(f"白绮参考音频条件缓存已写入：{REFERENCE_CACHE.name}")
        except OSError as exc:
            self.log(f"参考缓存写入失败（本次仍可继续）：{exc}")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return tensors

    def _build_reference_cache_on_cuda(self) -> dict:
        """Run the fixed reference encoders once, with a <3 GiB staged peak."""
        import torchaudio

        tts = self.tts
        torch = self.torch
        self.log("首次生成白绮参考条件缓存（Wav2Vec/Campplus 分阶段上 GPU）…")
        tts.semantic_model = tts.semantic_model.to(self.device)
        tts.semantic_mean = tts.semantic_mean.to(self.device)
        tts.semantic_std = tts.semantic_std.to(self.device)
        tts.campplus_model = tts.campplus_model.to(self.device)
        tts.s2mel = tts.s2mel.to(self.device)

        with torch.inference_mode():
            audio, sample_rate = tts._load_and_cut_audio(str(REFERENCE_WAV), 15, False)
            audio_22k = torchaudio.transforms.Resample(sample_rate, 22050)(audio)
            audio_16k = torchaudio.transforms.Resample(sample_rate, 16000)(audio)
            inputs = tts.extract_features(audio_16k, sampling_rate=16000, return_tensors="pt")
            features = inputs["input_features"].to(self.device)
            attention = inputs["attention_mask"].to(self.device)
            # The stock cache-miss path computes this identical embedding three
            # times.  Speaker and default emotion use the same fixed reference.
            spk_cond = tts.get_emb(features, attention)
            ref_mel = tts.mel_fn(audio_22k.to(self.device).float())
            ref_lengths = torch.LongTensor([ref_mel.size(2)]).to(self.device)
            feat = torchaudio.compliance.kaldi.fbank(
                audio_16k.to(self.device), num_mel_bins=80, dither=0,
                sample_frequency=16000,
            )
            feat = feat - feat.mean(dim=0, keepdim=True)
            style = tts.campplus_model(feat.unsqueeze(0))
            prompt = tts.s2mel.models["length_regulator"](
                spk_cond, ylens=ref_lengths, n_quantizers=3, f0=None,
            )[0]
        tensors = {
            "spk_cond": spk_cond.detach().cpu(),
            "style": style.detach().cpu(),
            "prompt": prompt.detach().cpu(),
            "mel": ref_mel.detach().cpu(),
            "emo_cond": spk_cond.detach().cpu(),
        }
        torch.cuda.synchronize(self.device)
        tts.semantic_model = tts.semantic_model.to("cpu")
        tts.semantic_mean = tts.semantic_mean.to("cpu")
        tts.semantic_std = tts.semantic_std.to("cpu")
        tts.campplus_model = tts.campplus_model.to("cpu")
        # s2mel is a runtime module and remains on CUDA.
        gc.collect()
        torch.cuda.empty_cache()
        return tensors

    def _discard_reference_encoders(self) -> None:
        # They are provably unreachable while the fixed reference cache matches.
        self.tts.semantic_model = None
        self.tts.campplus_model = None
        self.tts.semantic_mean = None
        self.tts.semantic_std = None
        gc.collect()

    def _move_runtime_to_cuda(self, cache: dict) -> None:
        torch = self.torch
        tts = self.tts
        # IndexTTS 2.0's official low-memory path also halves only UnifiedVoice.
        # For 2.5 this is an intentionally local compatibility extension: the
        # integer codec boundary lets the decoder/diffusion/vocoder remain FP32.
        # Convert on CPU so a transient FP32+FP16 GPT copy never hits the 6GB GPU.
        if self.precision == "fp16":
            tts.gpt = tts.gpt.half()
        for name in ("gpt", "semantic_codec", "s2mel", "bigvgan"):
            module = getattr(tts, name)
            if next(module.parameters()).device.type != "cuda":
                setattr(tts, name, module.to(self.device))
        # IndexTTS creates two non-buffer diffusion cache tensors during the
        # CPU constructor.  ``Module.to`` cannot see them; force a rebuild on
        # the estimator's new CUDA device.
        estimator = tts.s2mel.models["cfm"].estimator
        estimator.transformer.max_batch_size = -1
        estimator.transformer.max_seq_length = -1
        estimator.setup_caches(max_batch_size=1, max_seq_length=8192)
        tts.emo_matrix = tuple(value.to(self.device) for value in tts.emo_matrix)
        tts.spk_matrix = tuple(value.to(self.device) for value in tts.spk_matrix)
        tts.cache_spk_cond = cache["spk_cond"].to(self.device)
        tts.cache_s2mel_style = cache["style"].to(self.device)
        tts.cache_s2mel_prompt = cache["prompt"].to(self.device)
        tts.cache_mel = cache["mel"].to(self.device)
        tts.cache_emo_cond = cache["emo_cond"].to(self.device)
        tts.cache_spk_audio_prompt = str(REFERENCE_WAV)
        tts.cache_emo_audio_prompt = str(REFERENCE_WAV)
        tts.device = self.device
        tts.dtype = torch.float16 if self.precision == "fp16" else None
        tts.use_bf16 = False
        tts.low_vram = True
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize(self.device)

    def _memory_summary(self) -> str:
        torch = self.torch
        allocated = torch.cuda.memory_allocated(self.device) / 1024 ** 2
        reserved = torch.cuda.memory_reserved(self.device) / 1024 ** 2
        return f"CUDA allocated/reserved={allocated:.0f}/{reserved:.0f}MiB"

    def synthesize(self, text: str, output_path: Path) -> float:
        started = time.monotonic()
        self.torch.cuda.reset_peak_memory_stats(self.device)
        generation_kwargs = {}
        if len(_normalize_speech_text(text)) <= CONCLUSION_MAX_CHARS:
            # 320 semantic tokens are about 11.5 seconds at the production
            # codec/S2M settings. This leaves ample room for <=20 characters
            # while bounding the random decoder's missing-EOS worst case.
            generation_kwargs["max_mel_tokens"] = SHORT_TEXT_MAX_MEL_TOKENS
        try:
            with self.torch.inference_mode():
                self.tts.infer(
                    spk_audio_prompt=str(REFERENCE_WAV),
                    text=text,
                    lang="ZH",
                    output_path=str(output_path),
                    duration_factor=self.duration_factor,
                    verbose=False,
                    num_beams=self.num_beams,
                    **generation_kwargs,
                )
            self.torch.cuda.synchronize(self.device)
            self.last_peak_mib = self.torch.cuda.max_memory_allocated(self.device) / 1024 ** 2
        finally:
            # Activations are no longer live after the WAV has been copied to CPU.
            # Return allocator cache so Vulkan has headroom between utterances.
            self.torch.cuda.empty_cache()
        return time.monotonic() - started


@dataclass
class _SpeechJob:
    text: str
    segments: tuple[str, ...]
    source: str
    done: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    error: str | None = None
    cancelled: bool = False


class SpeechService:
    """A single priority queue around model inference and blocking playback."""

    def __init__(
        self,
        engine: IndexTTSGpuEngine,
        *,
        session_id: str,
        play: Callable[[Path], None],
        log: Callable[[str], None],
        on_busy: Callable[[str | None], None] | None = None,
    ) -> None:
        self.engine = engine
        self.session_id = session_id
        self.play = play
        self.log = log
        self.on_busy = on_busy or (lambda _source: None)
        self.queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=64)
        self._counter = itertools.count()
        self._stopping = threading.Event()
        self._busy_lock = threading.Lock()
        self._current_source: str | None = None
        self._current_segment_index: int | None = None
        self._current_segment_count = 0
        self._current_segment_chars = 0
        self.completed = 0
        self.worker = threading.Thread(target=self._run, name="indextts-gpu-worker", daemon=True)
        self.worker.start()
        self.server: ThreadingHTTPServer | None = None
        self.server_thread: threading.Thread | None = None

    def start_http(self, port: int) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", port), _RequestHandler)
        server.daemon_threads = True
        server.speech_service = self  # type: ignore[attr-defined]
        self.server = server
        self.server_thread = threading.Thread(
            target=server.serve_forever, name="indextts-http", daemon=True,
        )
        self.server_thread.start()

    def status(self) -> dict:
        with self._busy_lock:
            source = self._current_source
            segment_index = self._current_segment_index
            segment_count = self._current_segment_count
            segment_chars = self._current_segment_chars
        return {
            "ok": True,
            "ready": not self._stopping.is_set(),
            "session_id": self.session_id,
            "device": self.engine.device,
            "precision": self.engine.precision,
            "gpu": self.engine.gpu_name,
            "queue_size": self.queue.qsize(),
            "busy": source is not None,
            "current_source": source,
            "current_segment": segment_index,
            "segment_count": segment_count,
            "segment_chars": segment_chars,
            "completed": self.completed,
        }

    def submit(self, text: str, source: str, timeout: float) -> dict:
        if self._stopping.is_set():
            raise RuntimeError("IndexTTS GPU 服务正在停止")
        text = str(text or "").strip()
        if not text:
            return {"ok": True, "skipped": "empty"}
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f"单次文本超过 {MAX_TEXT_CHARS} 字符")
        if source not in SOURCE_PRIORITY:
            raise ValueError(f"未知语音来源：{source}")
        segments = (tuple(split_conclusion_text(text))
                    if source == "conclusion" else (text,))
        job = _SpeechJob(text=text, segments=segments, source=source)
        try:
            self.queue.put_nowait((SOURCE_PRIORITY[source], next(self._counter), job))
        except queue.Full as exc:
            raise RuntimeError("IndexTTS GPU 队列已满") from exc
        if not job.done.wait(max(1.0, timeout)):
            job.cancelled = True
            raise TimeoutError(f"IndexTTS 请求等待超过 {timeout:.0f}s")
        if job.error:
            raise RuntimeError(job.error)
        if job.result is None:
            raise RuntimeError("IndexTTS 任务未完成")
        return job.result

    def close(self) -> None:
        self._stopping.set()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        self.worker.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                _, _, job = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if job.cancelled:
                    continue
                with self._busy_lock:
                    self._current_source = job.source
                    self._current_segment_index = None
                    self._current_segment_count = len(job.segments)
                    self._current_segment_chars = 0
                self.on_busy(job.source)
                if len(job.segments) > 1:
                    self.log(
                        f"GPU 细粒度分句 [{job.source}] {len(job.text)}字 -> "
                        f"{len(job.segments)}段：{[len(part) for part in job.segments]}"
                    )
                total_elapsed = 0.0
                peak_cuda_mib = 0.0
                completed_segments = 0
                for index, segment in enumerate(job.segments, start=1):
                    if job.cancelled or self._stopping.is_set():
                        break
                    with self._busy_lock:
                        self._current_segment_index = index
                        self._current_segment_chars = len(segment)
                    label = (job.source if len(job.segments) == 1
                             else f"{job.source} {index}/{len(job.segments)}")
                    self.log(f"GPU 开始合成 [{label}] {len(segment)}字：{segment}")
                    fd, raw_path = tempfile.mkstemp(
                        prefix="index_gpu_", suffix=".wav", dir=TTS_DIR,
                    )
                    os.close(fd)
                    output_path = Path(raw_path)
                    try:
                        elapsed = self.engine.synthesize(segment, output_path)
                        total_elapsed += elapsed
                        peak_cuda_mib = max(
                            peak_cuda_mib,
                            float(getattr(self.engine, "last_peak_mib", 0.0)),
                        )
                        if not job.cancelled and not self._stopping.is_set():
                            self.play(output_path)
                            completed_segments += 1
                        self.log(
                            f"GPU 合成完成 [{label}] {len(segment)}字，"
                            f"{elapsed:.1f}s，峰值 "
                            f"{getattr(self.engine, 'last_peak_mib', 0.0):.0f}MiB：{segment}"
                        )
                    finally:
                        try:
                            output_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                if self._stopping.is_set() and not job.cancelled:
                    job.error = "IndexTTS GPU 服务停止，语音任务未完成"
                elif not job.cancelled:
                    self.completed += 1
                    job.result = {
                        "ok": True,
                        "source": job.source,
                        "segments": completed_segments,
                        "segment_lengths": [len(part) for part in job.segments],
                        "synthesis_seconds": round(total_elapsed, 3),
                        "peak_cuda_mib": round(peak_cuda_mib, 1),
                    }
            except Exception as exc:
                import traceback
                job.error = str(exc)
                self.log(
                    f"GPU 合成失败 [{job.source}]：{exc}\n"
                    f"{traceback.format_exc()[-2400:]}"
                )
            finally:
                self.on_busy(None)
                with self._busy_lock:
                    self._current_source = None
                    self._current_segment_index = None
                    self._current_segment_count = 0
                    self._current_segment_chars = 0
                job.done.set()
                self.queue.task_done()


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "VivhiteIndexTTS/1"

    @property
    def service(self) -> SpeechService:
        return self.server.speech_service  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args) -> None:
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/health":
            self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        self._send(HTTPStatus.OK, self.service.status())

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/speak":
            self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16 * 1024:
                raise ValueError("请求体大小非法")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if str(payload.get("session_id", "legacy")) != self.service.session_id:
                self._send(HTTPStatus.CONFLICT, {"ok": False, "error": "session mismatch"})
                return
            timeout = min(1800.0, max(1.0, float(payload.get("timeout_sec", 900))))
            result = self.service.submit(
                str(payload.get("text") or ""), str(payload.get("source") or ""), timeout,
            )
            self._send(HTTPStatus.OK, result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
        except TimeoutError as exc:
            self._send(HTTPStatus.GATEWAY_TIMEOUT, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": str(exc)})
