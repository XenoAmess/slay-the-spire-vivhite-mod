"""一次性克隆音色朗读：MOSS-TTS-Nano（ONNX CPU）合成文本文件内容并播放。

由 speaker.py 在复盘结束时调用：
  uv run --no-project --with onnxruntime --with sentencepiece --with torch --with torchaudio \
      python tts/speak_once.py <文本文件路径>

引擎选择：默认 MOSS-Nano（本机 RTF≈2.6）；`--engine indextts` 可回退 IndexTTS-2.5（更慢）。
GTX 1060 的 GPU 加速四条路均已实测不通（cudnn9 弃 Pascal / DirectML 需新版 Windows），见 docs。
"""
from __future__ import annotations

import os
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


def _synth_moss_all(text: str) -> list:
    """MOSS-Nano 逐句合成，全部存好再返回 wav 文件列表（播放阶段连续播放不卡）。"""
    import re as _re
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
    codes = rt.encode_reference_audio(str(ref))

    sys.path.insert(0, str(TTS_DIR))
    from speaker import get_voice_state
    st = get_voice_state()
    gain = 0.0 if st["muted"] else st["volume"] / 100.0

    # 切成短句（句号/问号/叹号/分号/换行），过长的再按逗号软切
    parts = [p.strip() for p in _re.split(r"(?<=[。！？!?；;\n])", text) if p.strip()]
    sentences: list[str] = []
    for p in parts:
        if len(p) > 45:
            subs = [s.strip() for s in _re.split(r"(?<=[，,、：:])", p) if s.strip()]
            sentences.extend(subs)
        else:
            sentences.append(p)

    files: list = []
    for i, sent in enumerate(sentences):
        if not sent:
            continue
        r = rt.synthesize_single_chunk(text=sent, prompt_audio_codes=codes, streaming=False)
        wav = np.asarray(r["waveform"], dtype=np.float32) * gain
        sr = int(rt.codec_meta["codec_config"]["sample_rate"])
        ch = int(rt.codec_meta["codec_config"]["channels"])
        pcm = (wav.clip(-1, 1) * 32767).astype(np.int16)
        if pcm.ndim == 1:
            pcm = pcm[:, np.newaxis]
        seg = TTS_DIR / f"concl_{i:02d}.wav"
        with wave.open(str(seg), "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        files.append(seg)
        log(f"  句{i + 1}/{len(sentences)}（{len(sent)}字）已合成：{sent[:30]}")
    return files


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



def _hide_own_console() -> None:
    """uv run 拉起的包装 python 会被 Windows 分配可见控制台（uv 不传递隐藏标志），
    进程启动后自隐藏，治常驻黑窗。"""
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass

def main() -> int:
    _hide_own_console()
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
    moss_files: list = []
    if engine == "indextts":
        _synth_indextts(text, out)
        log(f"合成完成，耗时 {time.time() - t0:.0f}s，待播（{out.stat().st_size} bytes）")
    else:
        moss_files = _synth_moss_all(text)      # 先全部合成存好（静默，不占麦）
        log(f"全部 {len(moss_files)} 句合成完成，耗时 {time.time() - t0:.0f}s，待连续播放")
    import winsound
    # 若白绮吐槽员正在说话：等它说完，再多等 5 秒才播总结（互不抢麦）
    quip_speaking = KNOWLEDGE_DIR / "voice_quip_speaking.flag"
    wait_start = time.time()
    while quip_speaking.exists() and time.time() - wait_start < 90:
        time.sleep(1)
    if quip_speaking.exists():
        log("等待吐槽员超时（90s），强行播放")
    time.sleep(5)
    busy = KNOWLEDGE_DIR / "voice_clone_busy.flag"
    try:
        busy.write_text(str(os.getpid()), encoding="utf-8")   # 吐槽员见此标志让位
    except OSError:
        pass
    try:
        if engine == "indextts":
            winsound.PlaySound(str(out), winsound.SND_FILENAME)
        else:
            for seg in moss_files:              # 一次性连续播完
                winsound.PlaySound(str(seg), winsound.SND_FILENAME)
                seg.unlink(missing_ok=True)
    finally:
        busy.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"一次性朗读失败：{exc}")
        sys.exit(0)
