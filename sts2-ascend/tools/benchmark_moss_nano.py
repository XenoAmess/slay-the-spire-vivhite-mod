"""MOSS-TTS-Nano ONNX 进程内基准：加载一次，连续合成两句并测量耗时。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


ASCEND_ROOT = Path(__file__).resolve().parents[1]
MOSS_ROOT = ASCEND_ROOT / "third_party" / "MOSS-TTS-Nano"
MODEL_DIR = MOSS_ROOT / "models"
REFERENCE_AUDIO = ASCEND_ROOT / "tts" / "reference_voice_15s.wav"
OUTPUT_DIR = MOSS_ROOT / "generated_audio"

SAMPLE_TEXTS = (
    "你好，我是白绮的教练。",
    "本场复盘的主要结论：普通战斗的慢性失血才是最大死因，防御权重已经上调。",
)


def main() -> None:
    """加载一次 ONNX 运行时，并依次合成两条基准语句。"""
    parser = argparse.ArgumentParser(
        description="Benchmark MOSS-TTS-Nano with one model load and two utterances."
    )
    parser.parse_args()

    if not MOSS_ROOT.is_dir():
        raise FileNotFoundError(f"MOSS-TTS-Nano directory not found: {MOSS_ROOT}")
    if not MODEL_DIR.is_dir():
        raise FileNotFoundError(f"MOSS-TTS-Nano model directory not found: {MODEL_DIR}")
    if not REFERENCE_AUDIO.is_file():
        raise FileNotFoundError(f"Reference voice file not found: {REFERENCE_AUDIO}")

    sys.path.insert(0, str(MOSS_ROOT))
    from onnx_tts_runtime import OnnxTtsRuntime  # type: ignore[import-not-found]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    started_at = time.perf_counter()
    runtime = OnnxTtsRuntime(model_dir=MODEL_DIR)
    print(f"load: {time.perf_counter() - started_at:.1f}s", flush=True)

    for index, text in enumerate(SAMPLE_TEXTS):
        started_at = time.perf_counter()
        runtime.synthesize(
            text=text,
            prompt_audio_path=str(REFERENCE_AUDIO),
            enable_wetext=False,
            output_audio_path=str(OUTPUT_DIR / f"bench_{index}.wav"),
        )
        elapsed = time.perf_counter() - started_at
        print(f"sent{index} ({len(text)} chars): {elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
