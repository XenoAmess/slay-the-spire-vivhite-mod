#!/usr/bin/env python3
"""MOSS-TTS-Nano GPU/DirectML 基准测试工具。

运行时会先把 pip 安装的 NVIDIA CUDA 运行库目录加入 DLL 搜索路径，
再加载一次 ONNX 模型、缓存参考音频编码，并测量三条语句的合成速度。
"""

from __future__ import annotations

import argparse
import os
import sys
import sysconfig
import time
from pathlib import Path


ASCEND_ROOT = Path(__file__).resolve().parents[1]
MOSS_ROOT = ASCEND_ROOT / "third_party" / "MOSS-TTS-Nano"
MODEL_DIR = MOSS_ROOT / "models"
REFERENCE_AUDIO = ASCEND_ROOT / "tts" / "reference_voice_48k.wav"

BENCHMARK_TEXTS = (
    "你好，我是白绮的教练。",
    "本场复盘的主要结论：普通战斗的慢性失血才是最大死因。",
    "The fatal mistake was made earlier: turns one and two dumped everything into offense.",
)

# Windows 会在句柄关闭时撤销 add_dll_directory；保留句柄直到进程退出。
_DLL_DIRECTORY_HANDLES: list[object] = []


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark MOSS-TTS-Nano with CUDA or DirectML.",
    )
    parser.add_argument(
        "provider",
        nargs="?",
        default="cuda",
        help="Execution provider: cuda (default), dml/directml, or cpu.",
    )
    return parser.parse_args()


def _add_pip_nvidia_dll_directories() -> None:
    """将 pip 安装的 NVIDIA 运行库加入当前进程的 DLL 搜索路径。"""

    purelib = Path(sysconfig.get_paths()["purelib"])
    nvidia_root = purelib / "nvidia"
    add_dll_directory = getattr(os, "add_dll_directory", None)

    for dll_directory in sorted(nvidia_root.glob("*/bin")):
        if not dll_directory.is_dir():
            continue

        if callable(add_dll_directory):
            try:
                handle = add_dll_directory(str(dll_directory))
            except OSError:
                pass
            else:
                _DLL_DIRECTORY_HANDLES.append(handle)

        dll_path = str(dll_directory)
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        if dll_path not in path_entries:
            os.environ["PATH"] = dll_path + os.pathsep + os.environ.get("PATH", "")


def _require_runtime_files() -> None:
    if not MOSS_ROOT.is_dir():
        raise FileNotFoundError(f"MOSS-TTS-Nano directory not found: {MOSS_ROOT}")
    if not MODEL_DIR.is_dir():
        raise FileNotFoundError(f"MOSS-TTS-Nano model directory not found: {MODEL_DIR}")
    if not REFERENCE_AUDIO.is_file():
        raise FileNotFoundError(f"Reference voice file not found: {REFERENCE_AUDIO}")


def main() -> None:
    """加载指定硬件 provider，并输出三条语句的耗时与实时率。"""

    args = _parse_args()
    _require_runtime_files()
    _add_pip_nvidia_dll_directories()

    import numpy as np
    import onnxruntime as ort
    import wave

    print("providers:", ort.get_available_providers(), flush=True)

    moss_root_text = str(MOSS_ROOT)
    if moss_root_text not in sys.path:
        sys.path.insert(0, moss_root_text)

    from onnx_tts_runtime import OnnxTtsRuntime  # type: ignore[import-not-found]

    def _load_wav_stdlib(self: object, path: str | Path) -> np.ndarray:
        """用 stdlib wave 读取 48kHz 立体声 PCM16，绕过 torchaudio/torchcodec。"""

        del self
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
            data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            channel_count = wav_file.getnchannels()
            data = data.reshape(-1, channel_count).T.copy()
        return data[np.newaxis, :, :].astype(np.float32)

    OnnxTtsRuntime._load_reference_audio = _load_wav_stdlib

    provider = str(args.provider).strip().lower()

    # MOSS-TTS-Nano 当前只原生识别 cpu/cuda；为 DirectML 补充 provider 解析。
    import ort_cpu_runtime as ort_runtime  # type: ignore[import-not-found]

    if provider in {"dml", "directml", "dmlexecutionprovider"}:
        ort_runtime._normalize_execution_provider = lambda raw: "dml"
        ort_runtime._resolve_ort_providers = lambda execution_provider: [
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        ]
        provider = "dml"

    started_at = time.perf_counter()
    runtime = OnnxTtsRuntime(model_dir=MODEL_DIR, execution_provider=provider)
    print(f"load {time.perf_counter() - started_at:.1f}s", flush=True)

    prompt_codes = runtime.encode_reference_audio(REFERENCE_AUDIO)
    for index, text in enumerate(BENCHMARK_TEXTS):
        started_at = time.perf_counter()
        result = runtime.synthesize_single_chunk(
            text=text,
            prompt_audio_codes=prompt_codes,
            streaming=False,
        )
        elapsed_seconds = time.perf_counter() - started_at
        frame_count = len(result.get("generated_frames", []))
        audio_seconds = frame_count / 12.5
        real_time_factor = elapsed_seconds / max(audio_seconds, 0.1)
        print(
            f"{provider} sent{index} ({len(text)} chars): "
            f"{elapsed_seconds:.1f}s, audio {audio_seconds:.1f}s, "
            f"RTF {real_time_factor:.2f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
