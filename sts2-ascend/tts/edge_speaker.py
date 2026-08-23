"""ASCEND-VOICE-EDGE —— edge-tts 直播朗读器（统一多语言嗓音，云端零本地算力）。

在 uv 旁路环境运行（由 llm_review 复盘启动时拉起，或手动）：
  uv run --no-project --with edge-tts --with imageio-ffmpeg python tts/edge_speaker.py

设计：
  - 单一嗓音 zh-CN-XiaoxiaoNeural 读中英文（解决 SAPI 双嗓音割裂）
  - 合成走网络（约 1~3 秒/句），失败自动回退系统 SAPI（双嗓音兜底）
  - 朗读队列 256 上限，到顶丢最老一半
  - 音量/静音共享 knowledge/voice_volume.json（波形增益，0~400%）
  - Ctrl+Shift+Alt+↑/↓ 音量、Ctrl+Shift+Alt+M 静音
  - LIVE-END 后读完队列即退出
"""
from __future__ import annotations

import asyncio
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent           # sts2-ascend/
TTS_DIR = BASE_DIR / "tts"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
STREAM_FILE = KNOWLEDGE_DIR / "review_live.stream"
LOG_FILE = KNOWLEDGE_DIR / "tts_speaker.log"

VOICE = "zh-CN-XiaoxiaoNeural"   # 统一嗓音（中英通读，不割裂）
RATE = "+10%"
MAX_QUEUE = 256

sys.path.insert(0, str(TTS_DIR))
from speaker import (SentenceSplitter, FenceStripper, speakable, SapiSpeaker,  # noqa: E402
                     get_voice_state, start_volume_hotkeys,
                     acquire_voice_lock, release_voice_lock)


def log(msg: str) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[edge-voice {time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


class EdgeEngine:
    """edge-tts 合成（mp3 → ffmpeg 转 wav）；失败回退 SAPI。供 3 并发预取工作线程调用。"""

    def __init__(self) -> None:
        import edge_tts  # noqa: F401
        import imageio_ffmpeg
        self._ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self._sapi = None       # 懒加载 SAPI 兜底
        self._sapi_lock = threading.Lock()

    def synth_to_wav(self, text: str, wav: Path) -> bool:
        """合成 text 到 wav（未增益）。成功返回 True。"""
        mp3 = wav.with_suffix(".mp3")

        async def _run() -> None:
            import edge_tts
            await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(mp3))
        try:
            asyncio.run(_run())
            if not (mp3.exists() and mp3.stat().st_size > 1000):
                raise RuntimeError("mp3 empty")
            subprocess.run([self._ffmpeg, "-y", "-i", str(mp3), "-ar", "24000", "-ac", "1",
                            str(wav)], capture_output=True, timeout=60)
            return wav.exists()
        except Exception as exc:
            log(f"edge-tts 合成失败：{exc}")
            return False

    def say_fallback(self, text: str) -> None:
        with self._sapi_lock:
            if self._sapi is None:
                self._sapi = SapiSpeaker()
            self._sapi.say(text)


def _play_wav_with_gain(wav: Path) -> None:
    import array
    import wave
    import winsound
    st = get_voice_state()
    gain = 0.0 if st["muted"] else st["volume"] / 100.0
    if gain <= 0:
        return
    with wave.open(str(wav), "rb") as w:
        frames = w.readframes(w.getnframes())
        params = w.getparams()
    if abs(gain - 1.0) > 0.01:
        a = array.array("h")
        a.frombytes(frames)
        for i, s in enumerate(a):
            a[i] = max(-32768, min(32767, int(s * gain)))
        frames = a.tobytes()
    with wave.open(str(wav), "wb") as w:
        w.setparams(params)
        w.writeframes(frames)
    winsound.PlaySound(str(wav), winsound.SND_FILENAME)


def main() -> int:
    if "--test" in sys.argv:
        eng = EdgeEngine()
        w1 = TTS_DIR / "edge_test1.wav"
        if eng.synth_to_wav("你好，我是白绮的教练，edge 统一嗓音上线。", w1):
            _play_wav_with_gain(w1)
        w2 = TTS_DIR / "edge_test2.wav"
        if eng.synth_to_wav("Turn five had four block and two strikes, intent twenty-seven.", w2):
            _play_wav_with_gain(w2)
        return 0

    if not STREAM_FILE.exists():
        log("直播流不存在，退出")
        return 0
    if not acquire_voice_lock():
        log("已有朗读器在跑（单实例锁），本实例退出")
        return 0

    start_volume_hotkeys()
    eng = EdgeEngine()
    log(f"edge-tts 朗读器上线（统一嗓音 {VOICE}）")

    q: queue.Queue = queue.Queue(maxsize=MAX_QUEUE)
    splitter = SentenceSplitter()
    fence = FenceStripper()
    state = {"offset": 0}
    ended = False
    end_at = 0.0

    # ---- 3 并发预取流水线：边播边预合成后 3 句，消除句间卡顿 ----
    done: dict[int, tuple] = {}          # seq -> (wav_path | None, text)
    done_cond = threading.Condition()
    counters = {"put": 0, "played": 0}

    def synth_worker(wid: int) -> None:
        while True:
            try:
                seq, sent = q.get(timeout=0.5)
            except queue.Empty:
                if ended:
                    return
                continue
            wav = TTS_DIR / f"edge_pf_{seq:05d}.wav"   # 每句独立文件：避免"播放器在读、合成器复写同名"的竞态
            ok = eng.synth_to_wav(sent, wav)
            with done_cond:
                done[seq] = (wav if ok else None, sent)
                done_cond.notify_all()

    for _wid in range(3):
        threading.Thread(target=synth_worker, args=(_wid,), daemon=True).start()

    def player() -> None:
        while True:
            with done_cond:
                while counters["played"] not in done:
                    done_cond.wait(timeout=0.5)
                    if ended and counters["played"] >= counters["put"] and q.empty():
                        return
            seq = counters["played"]
            wav, sent = done.pop(seq)
            try:
                if wav is not None:
                    _play_wav_with_gain(wav)
                    try:
                        wav.unlink(missing_ok=True)     # 播完即删，控制磁盘占用
                    except OSError:
                        pass
                else:
                    eng.say_fallback(sent)
            except Exception as exc:
                import traceback
                log(f"播放失败：{exc!r}\n{traceback.format_exc()[-500:]}")
            counters["played"] += 1

    threading.Thread(target=player, daemon=True).start()

    while True:
        try:
            size = STREAM_FILE.stat().st_size
            if size < state["offset"]:
                state["offset"] = 0
            if size > state["offset"]:
                with STREAM_FILE.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(state["offset"])
                    data = f.read()
                    state["offset"] = f.tell()
                for ln in data.splitlines():
                    if ln.startswith("[LIVE-END]"):
                        ended = True
                        end_at = time.time()
                        continue
                    if ln.startswith("[LIVE-START]"):
                        ended = False
                        continue
                    ln = fence.feed(ln)      # 剥掉 ``` 围栏代码块（跨报文状态机）
                    if not ln.strip():
                        continue
                    if not speakable(ln):
                        continue
                    for sent in splitter.feed(ln):
                        if q.full():
                            for _ in range(MAX_QUEUE // 2):
                                try:
                                    q.get_nowait()
                                except queue.Empty:
                                    break
                        q.put((counters["put"], sent))
                        counters["put"] += 1
            if ended and time.time() - end_at > 3 and q.empty() and counters["played"] >= counters["put"]:
                break
            time.sleep(0.5)
        except Exception as exc:
            log(f"主循环异常（继续）：{exc}")
            time.sleep(2)

    if eng._sapi is not None:
        eng._sapi.close()
    release_voice_lock()
    log("edge 朗读器退出")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        import traceback
        log(f"致命异常（静默退出）：{exc}\n{traceback.format_exc()[-1000:]}")
        release_voice_lock()
        sys.exit(0)
