#!/usr/bin/env python3
"""测试缓存参考音频 prompt codes 后，MOSS-TTS-Nano 单句合成的边际耗时。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


ASCEND_ROOT = Path(__file__).resolve().parents[1]
MOSS_ROOT = ASCEND_ROOT / "third_party" / "MOSS-TTS-Nano"
MODEL_DIR = MOSS_ROOT / "models"
PROMPT_AUDIO_PATH = ASCEND_ROOT / "tts" / "reference_voice_15s.wav"

BENCHMARK_TEXTS = (
    "你好，我是白绮的教练。",
    "本场复盘的主要结论：普通战斗的慢性失血才是最大死因。",
    "The fatal mistake was made earlier: turns one and two dumped everything into offense.",
)


def main() -> None:
    """缓存一次参考音频编码，然后测量各测试句的合成性能。"""

    parser = argparse.ArgumentParser(
        description="Benchmark MOSS-TTS-Nano with cached prompt audio codes."
    )
    parser.parse_args()

    if not MOSS_ROOT.is_dir():
        raise FileNotFoundError(f"MOSS-TTS-Nano directory not found: {MOSS_ROOT}")
    if not MODEL_DIR.is_dir():
        raise FileNotFoundError(f"MOSS-TTS-Nano model directory not found: {MODEL_DIR}")
    if not PROMPT_AUDIO_PATH.is_file():
        raise FileNotFoundError(f"Reference voice file not found: {PROMPT_AUDIO_PATH}")

    if str(MOSS_ROOT) not in sys.path:
        sys.path.insert(0, str(MOSS_ROOT))

    from onnx_tts_runtime import OnnxTtsRuntime  # type: ignore[import-not-found]

    runtime = OnnxTtsRuntime(model_dir=MODEL_DIR)
    prompt_codes = runtime.resolve_prompt_audio_codes(
        voice="",
        prompt_audio_path=str(PROMPT_AUDIO_PATH),
    )
    print("Prompt codes cached.", flush=True)

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
            f"sent{index} ({len(text)} chars): "
            f"{elapsed_seconds:.1f}s, audio {audio_seconds:.1f}s, "
            f"RTF {real_time_factor:.2f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
