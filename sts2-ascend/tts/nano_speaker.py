"""ASCEND-VOICE-NANO —— 全克隆音色直播朗读器（MOSS-TTS-Nano，允许滞后）。

在 uv 旁路环境中运行（由 llm_review 复盘启动时拉起，或手动）：

  uv run --no-project --with onnxruntime --with sentencepiece --with torch --with torchaudio \
      python tts/nano_speaker.py

行为：
  - tail knowledge/review_live.stream，与直播窗同一份内容（代码/统计行不读）
  - 断句后进入文本队列（上限 4096 句，超出丢最老——防内存溢出）
  - 合成线程：常驻 MOSS-Nano 模型逐句合成到小容量 wav 缓冲（最多 4 个文件）
  - 播放线程：winsound 顺序播放，合成与播放流水线并行
  - LIVE-END 后直到队列读完才退出（允许大滞后，像播客一样把内容读完）
  - 单实例锁：已有一个在跑时新实例直接退出（复盘流被截断时老实例自动切到新内容）
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import wave
import winsound
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent           # sts2-ascend/
TTS_DIR = BASE_DIR / "tts"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
STREAM_FILE = KNOWLEDGE_DIR / "review_live.stream"
LOG_FILE = KNOWLEDGE_DIR / "tts_speaker.log"
MOSS_DIR = BASE_DIR / "third_party" / "MOSS-TTS-Nano"
TMP_DIR = TTS_DIR / "voice_tmp"
REF_48K = TTS_DIR / "reference_voice_48k.wav"

MAX_TEXT_QUEUE = 256        # 文本句队列上限；到顶时立刻丢弃最老的一半
PLAY_BUFFER = 4             # 预合成 wav 缓冲上限（控制磁盘占用）
MAX_SENTENCE = 90


def log(msg: str) -> None:
    line = f"[nano-voice {time.strftime('%H:%M:%S')}] {msg}"
    try:
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---- 复用 speaker.py 的过滤与断句（单一事实来源） ----
sys.path.insert(0, str(TTS_DIR))
from speaker import (SentenceSplitter, FenceStripper, speakable, lang_of, SapiSpeaker,  # noqa: E402
                     get_voice_state, start_volume_hotkeys,
                     acquire_voice_lock, release_voice_lock)
sys.path.insert(0, str(BASE_DIR / "brain"))
from lifecycle import stop_requested, wait_for_stop  # noqa: E402


class NanoEngine:
    """常驻 MOSS-TTS-Nano（ONNX CPU，4 线程，缓存参考音频编码）。"""

    def __init__(self) -> None:
        import numpy as np  # noqa
        sys.path.insert(0, str(MOSS_DIR))
        from onnx_tts_runtime import OnnxTtsRuntime

        def _load_wav_stdlib(self, path):
            import numpy as np
            with wave.open(str(path), "rb") as w:
                data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                data = data.astype(np.float32) / 32768.0
                ch = w.getnchannels()
                data = data.reshape(-1, ch).T.copy()
            return data[None, :, :].astype(np.float32)

        OnnxTtsRuntime._load_reference_audio = _load_wav_stdlib
        t0 = time.time()
        self.rt = OnnxTtsRuntime(model_dir=MOSS_DIR / "models")
        ref = REF_48K if REF_48K.exists() else TTS_DIR / "reference_voice.wav"
        self.codes = self.rt.encode_reference_audio(str(ref))
        log(f"MOSS-Nano 引擎就绪（加载 {time.time() - t0:.0f}s，音色 {ref.name}）")

    def synth(self, text: str, out_path: Path) -> None:
        r = self.rt.synthesize_single_chunk(text=text, prompt_audio_codes=self.codes, streaming=False)
        import numpy as np
        wav = np.asarray(r["waveform"], dtype=np.float32)
        sr = int(self.rt.codec_meta["codec_config"]["sample_rate"])
        ch = int(self.rt.codec_meta["codec_config"]["channels"])
        # 音量增益（静音=0；SAPI 上限 100%，MOSS 可到 200% 并防削波）
        st = get_voice_state()
        gain = 0.0 if st["muted"] else st["volume"] / 100.0
        wav = wav * gain
        pcm = (wav.clip(-1, 1) * 32767).astype(np.int16)
        if pcm.ndim == 1:
            pcm = pcm[:, np.newaxis]
        # 运行时的 waveform 布局是 (samples, channels)，即交错数据，直接落盘；
        # 别再 .T（曾把声道/样本转反导致听起来语速怪）
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())


def main() -> int:
    if "--test" in sys.argv:
        eng = NanoEngine()
        out = TMP_DIR / "test.wav"
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        eng.synth("你好，我是白绮的教练。MOSS Nano 克隆音色全量朗读已上线。", out)
        winsound.PlaySound(str(out), winsound.SND_FILENAME)
        return 0

    if stop_requested():
        return 0

    if not STREAM_FILE.exists():
        log("直播流不存在，退出")
        return 0
    if not acquire_voice_lock():
        log("已有朗读器在跑，本实例退出")
        return 0

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    eng = NanoEngine()
    sapi = SapiSpeaker()      # 英文句走系统英文嗓音（即时），中文走克隆音色
    start_volume_hotkeys()    # Ctrl+Alt+↑/↓ 音量，Ctrl+Alt+M 静音

    text_q: queue.Queue[str] = queue.Queue(maxsize=MAX_TEXT_QUEUE)
    play_q: queue.Queue[tuple] = queue.Queue(maxsize=PLAY_BUFFER)
    ended = threading.Event()
    synth_idle = threading.Event()
    counter = {"n": 0}

    def synth_worker() -> None:
        """严格按队列顺序：英文直接转播放队列（SAPI），中文先合成 wav 再入播放队列。"""
        while not stop_requested():
            try:
                sent = text_q.get(timeout=0.5)
            except queue.Empty:
                if ended.is_set() or stop_requested():
                    return
                continue
            synth_idle.clear()
            try:
                if lang_of(sent) == "en":
                    play_q.put(("sapi", sent))
                else:
                    counter["n"] += 1
                    out = TMP_DIR / f"sent_{counter['n'] % 100:03d}.wav"
                    eng.synth(sent, out)
                    play_q.put(("wav", out))     # 缓冲满则自然阻塞（背压）
            except Exception as exc:
                log(f"合成失败（跳过）：{exc}")
            finally:
                synth_idle.set()

    def play_worker() -> None:
        """严格按序播放：SAPI 等回执、wav 等播完——两种嗓音不错乱。"""
        while not stop_requested():
            try:
                kind, payload = play_q.get(timeout=0.5)
            except queue.Empty:
                if stop_requested() or (ended.is_set() and text_q.empty()):
                    return
                continue
            try:
                if kind == "sapi":
                    sapi.say(payload, wait=True)
                else:
                    winsound.PlaySound(str(payload), winsound.SND_FILENAME)
            except Exception as exc:
                log(f"播放失败：{exc}")

    threading.Thread(target=synth_worker, daemon=True).start()
    threading.Thread(target=play_worker, daemon=True).start()

    splitter = SentenceSplitter()
    fence = FenceStripper()
    state = {"offset": 0}
    log("MOSS-Nano 朗读器上线（中文=白绮克隆音色，英文=SAPI，严格按序，允许滞后读完）")

    while not stop_requested():
        try:
            size = STREAM_FILE.stat().st_size
            if size < state["offset"]:
                state["offset"] = 0            # 新复盘截断了流文件：继续读新内容（队列不清，旧内容读完接着读新的）
            if size > state["offset"]:
                with STREAM_FILE.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(state["offset"])
                    data = f.read()
                    state["offset"] = f.tell()
                for ln in data.splitlines():
                    if ln.startswith("[LIVE-END]"):
                        ended.set()
                        continue
                    if ln.startswith("[LIVE-START]"):
                        ended.clear()
                        continue
                    ln = fence.feed(ln)      # 剥掉 ``` 围栏代码块（跨报文状态机）
                    if not ln.strip():
                        continue
                    if not speakable(ln):
                        continue
                    for sent in splitter.feed(ln):
                        if text_q.full():
                            for _ in range(MAX_TEXT_QUEUE // 2):   # 到顶立刻丢最老的一半
                                try:
                                    text_q.get_nowait()
                                except queue.Empty:
                                    break
                        text_q.put(sent)
            if ended.is_set():
                for sent in splitter.flush():
                    if speakable(sent):
                        text_q.put(sent)
                # 全部读完才退出
                if text_q.empty() and synth_idle.is_set() and play_q.empty():
                    break
            if wait_for_stop(0.5):
                ended.set()
                break
        except Exception as exc:
            log(f"主循环异常（继续）：{exc}")
            if wait_for_stop(2):
                ended.set()
                break

    sapi.close()
    release_voice_lock()
    log("朗读器退出（全部读完）" if not stop_requested() else
        "收到全栈停止请求，朗读器退出")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        import traceback
        log(f"致命异常（静默退出）：{exc}\n{traceback.format_exc()[-1200:]}")
        release_voice_lock()
        sys.exit(0)
