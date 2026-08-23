"""一次性克隆音色朗读：MOSS-TTS-Nano（ONNX CPU）合成文本文件内容并播放。

由 speaker.py 在复盘结束时调用：
  uv run --no-project --with onnxruntime --with sentencepiece --with torch --with torchaudio \
      python tts/speak_once.py <文本文件路径>

引擎选择：默认 MOSS-Nano（本机 RTF≈2.6）；`--engine indextts` 可回退 IndexTTS-2.5（更慢）。
GTX 1060 的 GPU 加速四条路均已实测不通（cudnn9 弃 Pascal / DirectML 需新版 Windows），见 docs。
"""
from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TTS_DIR = BASE_DIR / "tts"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
INDEXTTS_DIR = BASE_DIR / "third_party" / "index-tts"
MOSS_DIR = BASE_DIR / "third_party" / "MOSS-TTS-Nano"
LOG_FILE = KNOWLEDGE_DIR / "tts_speaker.log"
REF_48K = TTS_DIR / "reference_voice_48k.wav"


def log(msg: str) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[voice-once {time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def _synth_moss(text: str, out: Path) -> None:
    """MOSS-TTS-Nano ONNX CPU 合成（stdlib wave 读参考音频，绕开 torchaudio/torchcodec）。"""
    import numpy as np
    sys.path.insert(0, str(MOSS_DIR))
    from onnx_tts_runtime import OnnxTtsRuntime

    def _load_wav_stdlib(self, path):
        with wave.open(str(path), "rb") as w:
            data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            data = data.astype(np.float32) / 32768.0
            ch = w.getnchannels()
            data = data.reshape(-1, ch).T.copy()
        return data[np.newaxis, :, :].astype(np.float32)

    OnnxTtsRuntime._load_reference_audio = _load_wav_stdlib
    ref = REF_48K if REF_48K.exists() else TTS_DIR / "reference_voice.wav"
    rt = OnnxTtsRuntime(model_dir=MOSS_DIR / "models")
    rt.synthesize(text=text, prompt_audio_path=str(ref),
                  output_audio_path=str(out), enable_wetext=False)
    # 音量增益（与朗读器共享 voice_volume.json）
    try:
        sys.path.insert(0, str(TTS_DIR))
        from speaker import get_voice_state
        st = get_voice_state()
        gain = 0.0 if st["muted"] else st["volume"] / 100.0
        if abs(gain - 1.0) > 0.01:
            with wave.open(str(out), "rb") as w:
                frames = w.readframes(w.getnframes())
                params = w.getparams()
            pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0 * gain
            pcm16 = (np.clip(pcm, -1, 1) * 32767).astype(np.int16)
            with wave.open(str(out), "wb") as w:
                w.setparams(params)
                w.writeframes(pcm16.tobytes())
    except Exception:
        pass


def _synth_indextts(text: str, out: Path) -> None:
    import os
    sys.path.insert(0, str(INDEXTTS_DIR))
    from indextts.infer_v2_5 import IndexTTS2
    ckpt = INDEXTTS_DIR / "checkpoints"
    tts = IndexTTS2(cfg_path=str(ckpt / "config.yaml"), model_dir=str(ckpt),
                    use_bf16=False, device=os.environ.get("TTS_DEVICE") or "cpu")
    ref = TTS_DIR / "reference_voice_15s.wav"
    tts.infer(spk_audio_prompt=str(ref), text=text, lang="ZH",
              output_path=str(out), duration_factor=0.9, verbose=False)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    engine = "moss"
    if "--engine" in sys.argv:
        engine = sys.argv[sys.argv.index("--engine") + 1]
    if not args:
        return 1
    text = Path(args[0]).read_text(encoding="utf-8").strip()
    if not text:
        return 0
    out = TTS_DIR / "conclusion.wav"
    t0 = time.time()
    log(f"开始合成（{len(text)} 字，引擎 {engine}）")
    if engine == "indextts":
        _synth_indextts(text, out)
    else:
        _synth_moss(text, out)
    log(f"合成完成，耗时 {time.time() - t0:.0f}s，播放（{out.stat().st_size} bytes）")
    import winsound
    busy = KNOWLEDGE_DIR / "voice_clone_busy.flag"
    try:
        busy.write_text(str(os.getpid()), encoding="utf-8")   # 吐槽员见此标志让位
    except OSError:
        pass
    try:
        winsound.PlaySound(str(out), winsound.SND_FILENAME)
    finally:
        busy.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"一次性朗读失败：{exc}")
        sys.exit(0)
