"""ASCEND-VOICE-EDGE —— Edge 实时直播 + IndexTTS GPU 最终结论。

在 uv 旁路环境运行（由 llm_review 复盘启动时拉起，或手动）：
  uv run --no-project --with edge-tts --with imageio-ffmpeg python tts/edge_speaker.py

设计：
  - 单一嗓音 zh-CN-XiaoxiaoNeural 读中英文（解决 SAPI 双嗓音割裂）
  - 合成走网络（约 1~3 秒/句），失败自动回退系统 SAPI（双嗓音兜底）
  - 朗读队列 256 上限，到顶丢最老一半
  - 音量/静音共享 knowledge/voice_volume.json（波形增益，0~400%）
  - Ctrl+Shift+Alt+↑/↓ 音量、Ctrl+Shift+Alt+M 静音
  - LIVE-END 携带的本场结论立即提交给白绮 IndexTTS GPU owner；两种声音允许同时播放
  - Edge 队列读完后退出；IndexTTS 不可用只跳过结论，不回退 CPU 或加载第二份模型
"""
from __future__ import annotations

import json
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
CONCLUSION_FILE = KNOWLEDGE_DIR / "review_conclusion.txt"

VOICE = "zh-CN-XiaoxiaoNeural"   # 统一嗓音（中英通读，不割裂）
RATE = "+10%"
MAX_QUEUE = 256

sys.path.insert(0, str(TTS_DIR))
from speaker import (SentenceSplitter, FenceStripper, speakable, SapiSpeaker,  # noqa: E402
                     get_voice_state, start_volume_hotkeys,
                     acquire_voice_lock, release_voice_lock)
from indextts_client import (IndexTTSServiceError, speak as index_speak,  # noqa: E402
                             wait_ready as wait_index_ready)
sys.path.insert(0, str(BASE_DIR / "brain"))
from lifecycle import stop_requested, wait_for_stop  # noqa: E402


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


def _marker_payload(line: str) -> dict | None:
    try:
        _, payload_text = line.split("]", 1)
        payload = json.loads(payload_text.strip())
        return payload if isinstance(payload, dict) else None
    except (AttributeError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _review_id_from_live_start(line: str) -> str:
    payload = _marker_payload(line)
    return str((payload or {}).get("review_id") or "").strip()[:160]


def _conclusion_from_live_end(line: str) -> tuple[bool, str, str]:
    """Return modern-payload flag, review id and validated conclusion."""
    payload = _marker_payload(line)
    if payload is None or "conclusion" not in payload:
        return False, "", ""
    review_id = str(payload.get("review_id") or "").strip()[:160]
    conclusion = " ".join(str(payload.get("conclusion") or "").split())[:200]
    return True, review_id, conclusion


def _fresh_conclusion_file(stream_started_at: float, path: Path = CONCLUSION_FILE) -> str:
    """Compatibility fallback that never reuses a previous review's conclusion."""
    try:
        if path.exists() and path.stat().st_mtime >= stream_started_at:
            return " ".join(path.read_text(encoding="utf-8").split())[:200]
    except OSError:
        pass
    return ""


def _fallback_conclusion(recent_texts: list[str]) -> str:
    return "。".join(text.strip() for text in recent_texts[-4:] if text.strip())[:300]


def _speak_conclusion_indextts(text: str) -> bool:
    """Submit one conclusion to the existing session's GPU owner, never a new model."""
    text = str(text or "").strip()[:300]
    if not text or stop_requested():
        return False
    status = wait_index_ready(240.0, stop_requested=stop_requested)
    if status is None:
        log("当前 session 的 IndexTTS GPU owner 未就绪；结论跳过，不回退 CPU/SAPI")
        return False
    try:
        result = index_speak(text, source="conclusion")
    except IndexTTSServiceError as exc:
        log(f"IndexTTS GPU 结论朗读失败（不回退 CPU/SAPI）：{exc}")
        return False
    log(
        f"IndexTTS GPU 结论播放完成（{status.get('device')}/{status.get('precision')}，"
        f"合成 {result.get('synthesis_seconds', '?')}s）"
    )
    return True


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

    if stop_requested():
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
    # 中途启动只追直播前沿，不重放历史：整段重放会让队列瞬间打满、
    # 丢弃区间恰好压在播放器脚下（丢队沙漠的引信）。直播旁白要的是"现在"。
    # 对齐到行首（8KB 尾部起点可能切在行中间）。
    try:
        _size = STREAM_FILE.stat().st_size
        _seek = max(0, _size - 8192)
        with STREAM_FILE.open("r", encoding="utf-8", errors="replace") as _f:
            _f.seek(_seek)
            _tail = _f.read()
            _nl = _tail.find("\n")
            if 0 <= _nl < len(_tail) - 1:
                _seek = _seek + _nl + 1
        state = {"offset": _seek}
    except OSError:
        state = {"offset": 0}
    ended = False
    end_at = 0.0
    stream_started_at = time.time()
    stream_conclusion = ""
    conclusion_payload_seen = False
    recent_texts: list[str] = []
    conclusion_submitted = False
    handled_review_ids: set[str] = set()
    handled_review_order: list[str] = []

    def mark_review_handled(review_id: str) -> None:
        if not review_id or review_id in handled_review_ids:
            return
        handled_review_ids.add(review_id)
        handled_review_order.append(review_id)
        if len(handled_review_order) > 128:
            handled_review_ids.discard(handled_review_order.pop(0))

    # One FIFO worker preserves conclusion order if an old Edge process spans
    # back-to-back reviews while the GPU owner is still starting.
    conclusion_q: queue.Queue[str] = queue.Queue()
    conclusion_pump_stop = threading.Event()

    def conclusion_pump() -> None:
        while not conclusion_pump_stop.is_set() and not stop_requested():
            try:
                text = conclusion_q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                _speak_conclusion_indextts(text)
            except Exception as exc:
                log(f"IndexTTS 结论队列异常（继续）：{exc!r}")
            finally:
                conclusion_q.task_done()

    conclusion_thread = threading.Thread(
        target=conclusion_pump,
        name="edge-index-conclusion",
        daemon=True,
    )
    conclusion_thread.start()

    # ---- 3 并发预取流水线：边播边预合成后 3 句，消除句间卡顿 ----
    done: dict[int, tuple] = {}          # seq -> (wav_path | None, text)
    inflight: dict[int, str] = {}        # seq -> text（合成中登记，供超时路径兜底取回原文）
    done_cond = threading.Condition()
    counters = {"put": 0, "played": 0}
    # 合成健康度：连续失败熔断 + 心跳可观测（静默必须可诊断）
    synth_stats = {"ok": 0, "fail": 0, "consec_fail": 0, "sapi_until": 0.0, "next_beat": 20}

    def synth_worker(wid: int) -> None:
        while not stop_requested():
            try:
                try:
                    seq, sent = q.get(timeout=0.5)
                except queue.Empty:
                    # 仅当"复盘结束且播放器已追平"才收工。此前只看 ended+队列空：
                    # 复盘间隙队列恰好排空而播放器还在播存量 → 3 个 worker 集体
                    # 退出 → 下一场复盘开始后无人合成 → 僵尸朗读器静默数小时
                    # （520 句心跳戛然而止实证）。
                    if stop_requested() or (ended and counters["played"] >= counters["put"]):
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

    worker_threads: list = []

    def spawn_worker() -> None:
        t = threading.Thread(target=synth_worker, args=(len(worker_threads),), daemon=True)
        worker_threads.append(t)
        t.start()

    def ensure_workers() -> None:
        """worker 灭绝即重新拉起（双保险：退出条件收紧后仍留兜底），并大声记日志。"""
        alive = [t for t in worker_threads if t.is_alive()]
        if len(alive) < 3:
            log(f"[edge-voice] 合成线程仅存 {len(alive)}/3，重新补齐（防僵尸朗读器）")
            del worker_threads[:]
            worker_threads.extend(alive)
            for _ in range(3 - len(alive)):
                spawn_worker()

    for _wid in range(3):
        spawn_worker()

    def player() -> None:
        while not stop_requested():
            try:
                with done_cond:
                    waited = 0.0
                    while counters["played"] not in done:
                        done_cond.wait(timeout=0.5)
                        waited += 0.5
                        if (stop_requested() or
                                (ended and counters["played"] >= counters["put"] and q.empty())):
                            return
                        if waited > 90:
                            # 某句迟迟无结果。诚实区分两种情况：
                            # 有原文（合成真挂了）→ SAPI 兜底读出来；
                            # 无原文（该句被队列丢弃，worker 从未见过）→ 直接跳过，
                            # 此前这里谎报"SAPI 兜底"实则什么都没读（丢队沙漠事故）。
                            seq_to = counters["played"]
                            sent_to = inflight.pop(seq_to, None)
                            if sent_to:
                                log(f"第 {seq_to} 句合成超时未归，SAPI 兜底")
                            else:
                                log(f"第 {seq_to} 句无合成结果且无原文，静默跳过")
                            done[seq_to] = (None, sent_to)
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
            except Exception as exc:
                # 播放器线程死亡 = 永久静默且无人知晓
                import traceback
                log(f"播放线程异常（继续）：{exc!r}\n{traceback.format_exc()[-400:]}")
                time.sleep(1)

    threading.Thread(target=player, daemon=True).start()

    while not stop_requested():
        try:
            ensure_workers()     # 合成线程灭绝兜底：灭绝即补齐并大声记日志
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
                        (conclusion_payload_seen, end_review_id,
                         stream_conclusion) = _conclusion_from_live_end(ln)
                        already_handled = (
                            end_review_id in handled_review_ids
                            if end_review_id else conclusion_submitted)
                        conclusion_submitted = already_handled
                        if stream_conclusion and not already_handled and not stop_requested():
                            # Index work proceeds in its own FIFO while Edge keeps playing.
                            # The cross-engine overlap is intentional.
                            if end_review_id:
                                mark_review_handled(end_review_id)
                            conclusion_submitted = True
                            conclusion_q.put(stream_conclusion)
                        continue
                    if ln.startswith("[LIVE-START]"):
                        ended = False
                        stream_started_at = time.time()
                        stream_conclusion = ""
                        conclusion_payload_seen = False
                        start_review_id = _review_id_from_live_start(ln)
                        conclusion_submitted = bool(
                            start_review_id and start_review_id in handled_review_ids)
                        recent_texts.clear()
                        continue
                    ln = fence.feed(ln)      # 剥掉 ``` 围栏代码块（跨报文状态机）
                    if not ln.strip():
                        continue
                    if not speakable(ln):
                        continue
                    for sent in splitter.feed(ln):
                        if q.full():
                            # 队列打满丢最老一半。丢弃必须同步标记 done 并唤醒播放器：
                            # 否则被丢句永远无结果，播放器在丢弃区间每句空等 90 个
                            # waited-秒（约 40~76 真实秒）才静默跳过——上百句的丢弃区
                            # 就是 1.5~3 小时静默沙漠（2026-08-24 占卜日事故实证）
                            with done_cond:
                                for _ in range(MAX_QUEUE // 2):
                                    try:
                                        dropped_seq, _ = q.get_nowait()
                                    except queue.Empty:
                                        break
                                    done[dropped_seq] = (None, None)
                                done_cond.notify_all()
                        q.put((counters["put"], sent))
                        counters["put"] += 1
                        recent_texts.append(sent)
                        del recent_texts[:-8]
            if ended and time.time() - end_at > 3 and q.empty() and counters["played"] >= counters["put"]:
                break
            if wait_for_stop(0.5):
                break
        except Exception as exc:
            log(f"主循环异常（继续）：{exc}")
            if wait_for_stop(2):
                break

    # This lock protects Edge/SAPI narrator instances only.  Release it before
    # cleanup/waiting so a following review's Edge voice is never blocked by
    # the independent white-voice conclusion.
    release_voice_lock()
    if eng._sapi is not None:
        eng._sapi.close()
    if not stop_requested() and not conclusion_submitted and not conclusion_payload_seen:
        conclusion = (_fresh_conclusion_file(stream_started_at)
                      or _fallback_conclusion(recent_texts))
        if conclusion:
            conclusion_submitted = True
            conclusion_q.put(conclusion)
        else:
            log("本场没有可用结论，跳过 IndexTTS；未读取上一场旧文本")
    elif not stop_requested() and conclusion_payload_seen and not conclusion_submitted:
        log("本场隔离复盘未产出已验证结论，跳过 IndexTTS；不拿流尾冒充结论")
    while conclusion_q.unfinished_tasks and not stop_requested():
        if wait_for_stop(0.5):
            break
    conclusion_pump_stop.set()
    conclusion_thread.join(timeout=1.0)
    log("edge 朗读器退出" if not stop_requested() else "收到全栈停止请求，edge 朗读器退出")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        import traceback
        log(f"致命异常（静默退出）：{exc}\n{traceback.format_exc()[-1000:]}")
        release_voice_lock()
        sys.exit(0)
