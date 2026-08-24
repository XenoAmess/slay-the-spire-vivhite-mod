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
        """合成 text 到 wav（未增益）。成功返回 True。

        合成走子进程（python -m edge_tts）+ subprocess.run(timeout) 硬杀：
        曾在进程内 asyncio.wait_for(30s) 被 edge_tts/aiohttp 的取消挂死绕过——
        三个合成线程全部卡死、每句 90s 空转跳过、朗读永久沉默（第 651~660+ 句实证）。
        子进程超时会被可靠杀死，失败即回退 SAPI，杜绝"全静默"事故。
        """
        mp3 = wav.with_suffix(".mp3")
        try:
            # 必须用真实解释器（sys._base_executable）而非 sys.executable：
            # uv 旁路环境里 sys.executable 是 shim 跳板，会再孵化孙进程——
            # 超时杀掉的只是跳板，孙进程握着管道不放，subprocess.run 永远读不到
            # EOF 而挂死（第 3~8 句连续超时实证）。直跑真实解释器无孙进程可杀得干净。
            # PYTHONPATH 传递当前 sys.path，保证真实解释器能 import edge_tts。
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
            real_py = getattr(sys, "_base_executable", None) or sys.executable
            proc = subprocess.run([real_py, "-m", "edge_tts",
                                   "--voice", VOICE, f"--rate={RATE}",
                                   "--text", text, "--write-media", str(mp3)],
                                  capture_output=True, timeout=35, env=env,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if proc.returncode != 0 or not (mp3.exists() and mp3.stat().st_size > 1000):
                err = (proc.stderr or b"").decode("utf-8", "replace")[-200:]
                raise RuntimeError(f"edge_tts rc={proc.returncode} {err}")
            subprocess.run([self._ffmpeg, "-y", "-i", str(mp3), "-ar", "24000", "-ac", "1",
                            str(wav)], capture_output=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return wav.exists()
        except subprocess.TimeoutExpired:
            log("edge-tts 合成硬超时（35s 子进程已杀），跳过")
            return False
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
    inflight: dict[int, str] = {}        # seq -> text（合成中登记，供超时路径兜底取回原文）
    done_cond = threading.Condition()
    counters = {"put": 0, "played": 0}
    # 合成健康度：连续失败熔断 + 心跳可观测（静默必须可诊断）
    synth_stats = {"ok": 0, "fail": 0, "consec_fail": 0, "sapi_until": 0.0, "next_beat": 20}

    def synth_worker(wid: int) -> None:
        while True:
            try:
                try:
                    seq, sent = q.get(timeout=0.5)
                except queue.Empty:
                    if ended:
                        return
                    continue
                wav = TTS_DIR / f"edge_pf_{seq:05d}.wav"   # 每句独立文件：避免"播放器在读、合成器复写同名"的竞态
                if time.time() < synth_stats["sapi_until"]:
                    # 熔断期：不再尝试 edge（网络性死亡防全哑），直接交 SAPI 兜底
                    with done_cond:
                        done[seq] = (None, sent)
                        done_cond.notify_all()
                    continue
                inflight[seq] = sent
                ok = eng.synth_to_wav(sent, wav)
                inflight.pop(seq, None)
                if ok:
                    synth_stats["ok"] += 1
                    synth_stats["consec_fail"] = 0
                else:
                    synth_stats["fail"] += 1
                    synth_stats["consec_fail"] += 1
                    if synth_stats["consec_fail"] >= 5:
                        synth_stats["sapi_until"] = time.time() + 600
                        synth_stats["consec_fail"] = 0
                        log("edge-tts 连续 5 次合成失败，熔断 10 分钟：期间全部走 SAPI 兜底")
                total = synth_stats["ok"] + synth_stats["fail"]
                if total >= synth_stats["next_beat"]:
                    synth_stats["next_beat"] = total + 20
                    log(f"合成心跳：成功 {synth_stats['ok']} / 失败 {synth_stats['fail']}")
                with done_cond:
                    done[seq] = (wav if ok else None, sent)
                    done_cond.notify_all()
            except Exception as exc:
                # worker 线程静默死亡 = 该句永不完成且无人知晓（stderr 进隐藏控制台不可见）
                import traceback
                log(f"合成线程异常（继续）：{exc!r}\n{traceback.format_exc()[-400:]}")
                time.sleep(1)

    for _wid in range(3):
        threading.Thread(target=synth_worker, args=(_wid,), daemon=True).start()

    def player() -> None:
        while True:
            with done_cond:
                waited = 0.0
                while counters["played"] not in done:
                    done_cond.wait(timeout=0.5)
                    waited += 0.5
                    if ended and counters["played"] >= counters["put"] and q.empty():
                        return
                    if waited > 90:
                        # 某句合成 90s 还没好（挂死/超时）→ 用 SAPI 兜底读出原文，别让流水线陪葬也别静默
                        seq_to = counters["played"]
                        log(f"第 {seq_to} 句合成超时未归，SAPI 兜底")
                        done[seq_to] = (None, inflight.pop(seq_to, None))
                        break
            seq = counters["played"]
            wav, sent = done.pop(seq)
            try:
                if wav is not None:
                    _play_wav_with_gain(wav)
                    try:
                        wav.unlink(missing_ok=True)     # 播完即删，控制磁盘占用
                    except OSError:
                        pass
                elif sent:
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
