"""一次性克隆音色朗读：index-tts 合成文本文件内容并播放（在 uv venv 中运行）。

用法（由 speaker.py 在复盘结束时调用）：
  uv run --project third_party/index-tts python tts/speak_once.py <文本文件路径>
"""
from __future__ import annotations

import sys
import time
import winsound
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TTS_DIR = BASE_DIR / "tts"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
INDEXTTS_DIR = BASE_DIR / "third_party" / "index-tts"
LOG_FILE = KNOWLEDGE_DIR / "tts_speaker.log"


def log(msg: str) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[voice-once {time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    text = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
    if not text:
        return 0
    sys.path.insert(0, str(INDEXTTS_DIR))
    from indextts.infer_v2_5 import IndexTTS2
    ckpt = INDEXTTS_DIR / "checkpoints"
    import os
    # GTX 1060 与游戏抢 GPU 时合成会病态慢（实测 25 分钟不出一句），默认 CPU；
    # 要试 GPU 可设 TTS_DEVICE=cuda:0。use_accel 打开 GPT2 加速引擎（老 CPU 上最实在的一档提速）。
    device = os.environ.get("TTS_DEVICE") or "cpu"
    t0 = time.time()
    tts = IndexTTS2(cfg_path=str(ckpt / "config.yaml"), model_dir=str(ckpt),
                    use_bf16=False, device=device)
    log(f"引擎加载 {time.time() - t0:.0f}s")
    ref = TTS_DIR / "reference_voice_15s.wav"
    if not ref.exists():
        ref = TTS_DIR / "reference_voice.wav"
    out = TTS_DIR / "conclusion.wav"
    log(f"开始合成（{len(text)} 字，device={device}）")
    t0 = time.time()
    tts.infer(spk_audio_prompt=str(ref), text=text, lang="ZH",
              output_path=str(out), duration_factor=0.9, verbose=False)
    log(f"合成完成，耗时 {time.time() - t0:.0f}s，播放（{out.stat().st_size} bytes）")
    winsound.PlaySound(str(out), winsound.SND_FILENAME)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"一次性朗读失败：{exc}")
        sys.exit(0)
