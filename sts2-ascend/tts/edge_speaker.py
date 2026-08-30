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
import re
import secrets
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
PLAYER_RESULT_TIMEOUT_SECONDS = 90.0
PLAYER_WAIT_POLL_SECONDS = 0.5
PLAYER_SHUTDOWN_JOIN_SECONDS = 5.0
WORKER_SHUTDOWN_JOIN_SECONDS = 3.0
EDGE_SCAVENGE_FAILURE_SAMPLE_LIMIT = 3

_LEGACY_EDGE_ARTIFACT = re.compile(
    r"^edge_pf_\d{5}\.(?:mp3|wav)$", re.ASCII)
_INSTANCE_EDGE_ARTIFACT = re.compile(
    r"^edge_pf_(\d+)_([0-9a-f]{16})_\d{5}\.(?:mp3|wav)$", re.ASCII)

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
        finally:
            # Every sequence has an instance-private MP3 staging file.  It is
            # never a playback artifact and must not accumulate on any outcome.
            _discard_wav(mp3)

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


def _discard_wav(wav: Path | None) -> None:
    if wav is None:
        return
    try:
        wav.unlink(missing_ok=True)
    except OSError:
        pass


def _pid_presence(pid: int) -> bool | None:
    """Return True/False only when process presence is known conclusively.

    Scavenging is deliberately conservative: access failures and unexpected
    platform errors return ``None`` so a possibly-live speaker's files survive.
    """
    if pid <= 0:
        return None
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int,
                                             ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            # OpenProcess documents ERROR_INVALID_PARAMETER for a PID that does
            # not exist.  Access denied or any other result is not deletion proof.
            return False if ctypes.get_last_error() == 87 else None
        except Exception:
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _scavenge_edge_artifacts(
    root: Path = TTS_DIR, *, current_pid: int | None = None,
    pid_presence=None,
) -> dict[str, int]:
    """Remove exact legacy artifacts and files owned by conclusively dead PIDs.

    This runs only after the narrator lock is acquired and before this instance
    creates a playback buffer.  It intentionally scans no prefix beyond
    ``edge_pf_`` and never guesses when PID state cannot be read.
    """
    own_pid = os.getpid() if current_pid is None else int(current_pid)
    probe = pid_presence or _pid_presence
    stats = {
        "matched": 0,
        "deleted": 0,
        "deleted_bytes": 0,
        "kept_self": 0,
        "kept_live": 0,
        "kept_unknown": 0,
        "failed": 0,
    }
    failure_samples: list[str] = []
    try:
        candidates = root.glob("edge_pf_*")
        for path in candidates:
            name = path.name
            instance_match = _INSTANCE_EDGE_ARTIFACT.fullmatch(name)
            if _LEGACY_EDGE_ARTIFACT.fullmatch(name):
                remove = True
            elif instance_match:
                stats["matched"] += 1
                owner_pid = int(instance_match.group(1))
                if owner_pid == own_pid:
                    stats["kept_self"] += 1
                    continue
                try:
                    presence = probe(owner_pid)
                except Exception:
                    presence = None
                if presence is True:
                    stats["kept_live"] += 1
                    continue
                if presence is not False:
                    stats["kept_unknown"] += 1
                    continue
                remove = True
            else:
                continue

            if not instance_match:
                stats["matched"] += 1
            try:
                size = path.stat().st_size
                path.unlink()
                stats["deleted"] += 1
                stats["deleted_bytes"] += size
            except OSError as exc:
                stats["failed"] += 1
                if len(failure_samples) < EDGE_SCAVENGE_FAILURE_SAMPLE_LIMIT:
                    failure_samples.append(f"{name}: {exc}")
    except OSError as exc:
        stats["failed"] += 1
        failure_samples.append(f"scan: {exc}")

    if stats["matched"] or stats["failed"]:
        sample_text = ""
        if failure_samples:
            sample_text = "；失败样例 " + " | ".join(failure_samples)
            remaining = stats["failed"] - len(failure_samples)
            if remaining > 0:
                sample_text += f" | 另 {remaining} 个"
        log(
            "Edge 临时音频启动扫尾："
            f"匹配 {stats['matched']}，删除 {stats['deleted']} 个/"
            f"{stats['deleted_bytes']} 字节，保留 self {stats['kept_self']}、"
            f"活 PID {stats['kept_live']}、PID 未知 {stats['kept_unknown']}，"
            f"删除失败 {stats['failed']}{sample_text}"
        )
    return stats


class _PlaybackBuffer:
    """Keep queue admission, synthesis results and playback order in one state.

    ``put`` is the next sequence that has actually been admitted.  A player at
    ``played == put`` is waiting for a future sentence, not for a timed-out one;
    only an admitted sentence owns a result deadline.  ``pending_texts`` starts
    at admission rather than worker pickup, so a genuinely stuck worker can
    always fall back to SAPI with the original sentence.
    """

    def __init__(
        self, *, max_queue: int = MAX_QUEUE,
        result_timeout: float = PLAYER_RESULT_TIMEOUT_SECONDS,
        wait_poll: float = PLAYER_WAIT_POLL_SECONDS,
        clock=None,
        instance_nonce: str | None = None,
    ) -> None:
        self.max_queue = max(2, int(max_queue))
        self.result_timeout = max(0.0, float(result_timeout))
        self.wait_poll = max(0.0, float(wait_poll))
        self.clock = clock or time.monotonic
        nonce = str(instance_nonce or secrets.token_hex(8))
        safe_nonce = "".join(
            char if char.isalnum() or char in "-_" else "_" for char in nonce)
        self.wav_prefix = f"edge_pf_{os.getpid()}_{safe_nonce}"
        self.work: queue.Queue[tuple[int, str]] = queue.Queue(maxsize=self.max_queue)
        self.done: dict[int, tuple[Path | None, str | None]] = {}
        self.pending_texts: dict[int, str] = {}
        self.claimed: set[int] = set()
        self.cond = threading.Condition()
        self.counters = {"put": 0, "played": 0}
        self.closed = False

    def wav_path(self, root: Path, seq: int) -> Path:
        """Return this speaker instance's private sequence filename."""
        return root / f"{self.wav_prefix}_{seq:05d}.wav"

    def enqueue(self, sent: str) -> int:
        """Admit one sentence, dropping the oldest queued half at capacity."""
        with self.cond:
            if self.closed:
                raise RuntimeError("edge playback buffer is closed")
            if self.work.full():
                for _ in range(self.max_queue // 2):
                    try:
                        dropped_seq, _ = self.work.get_nowait()
                    except queue.Empty:
                        break
                    self.pending_texts.pop(dropped_seq, None)
                    # A timeout may already have claimed this still-queued item.
                    # Never recreate an orphan done entry behind the player.
                    if (dropped_seq >= self.counters["played"]
                            and dropped_seq not in self.claimed):
                        self.done[dropped_seq] = (None, None)
                    else:
                        self.done.pop(dropped_seq, None)
            seq = self.counters["put"]
            self.pending_texts[seq] = sent
            try:
                self.work.put_nowait((seq, sent))
            except queue.Full:
                self.pending_texts.pop(seq, None)
                raise
            self.counters["put"] += 1
            self.cond.notify_all()
            return seq

    def should_synthesize(self, seq: int, sent: str) -> bool:
        """Reject queued work that timed out or was dropped before pickup."""
        with self.cond:
            return bool(
                not self.closed
                and seq >= self.counters["played"]
                and seq not in self.claimed
                and self.pending_texts.get(seq) == sent
            )

    def publish_result(self, seq: int, wav: Path | None, sent: str) -> bool:
        """Publish one result, deleting a late WAV instead of orphaning it."""
        with self.cond:
            accepted = bool(
                not self.closed
                and seq >= self.counters["played"]
                and seq not in self.claimed
                and seq not in self.done
                and self.pending_texts.get(seq) == sent
            )
            if accepted:
                self.done[seq] = (wav, sent)
                self.cond.notify_all()
        if not accepted:
            _discard_wav(wav)
        return accepted

    def is_drained(self) -> bool:
        return (self.counters["played"] >= self.counters["put"]
                and self.work.empty())

    def close(self) -> None:
        """Abort all unplayed work and reject every later worker result."""
        wavs: list[Path] = []
        with self.cond:
            self.closed = True
            wavs.extend(
                wav for wav, _ in self.done.values() if wav is not None)
            self.done.clear()
            self.pending_texts.clear()
            self.claimed.clear()
            while True:
                try:
                    self.work.get_nowait()
                except queue.Empty:
                    break
            self.cond.notify_all()
        for wav in wavs:
            _discard_wav(wav)

    def wait_next(self, *, stop, drained) -> tuple[int, Path | None, str | None, bool] | None:
        """Wait for the current admitted sequence; return ``timed_out`` last.

        No deadline exists while the player is caught up with ``put``.  This is
        the crucial distinction between an idle stream and a stuck synthesis.
        """
        deadline: float | None = None
        with self.cond:
            while True:
                if self.closed or stop():
                    return None
                seq = self.counters["played"]
                if seq in self.done:
                    wav, sent = self.done.pop(seq)
                    self.pending_texts.pop(seq, None)
                    self.claimed.add(seq)
                    return seq, wav, sent, False
                if drained():
                    return None
                if (seq >= self.counters["put"]
                        or seq not in self.pending_texts):
                    # There is no admitted sentence at this sequence.  Wake
                    # periodically for stop/end checks, but never age a timeout.
                    deadline = None
                    self.cond.wait(timeout=self.wait_poll)
                    continue
                if deadline is None:
                    deadline = self.clock() + self.result_timeout
                remaining = deadline - self.clock()
                if remaining <= 0:
                    sent = self.pending_texts.pop(seq)
                    self.claimed.add(seq)
                    return seq, None, sent, True
                self.cond.wait(timeout=min(self.wait_poll, remaining))

    def mark_played(self, seq: int) -> None:
        with self.cond:
            if seq != self.counters["played"]:
                raise RuntimeError(
                    f"edge playback sequence mismatch: expected "
                    f"{self.counters['played']}, got {seq}")
            self.done.pop(seq, None)
            self.pending_texts.pop(seq, None)
            self.claimed.discard(seq)
            self.counters["played"] += 1
            self.cond.notify_all()


_active_playback: _PlaybackBuffer | None = None
_active_player_thread: threading.Thread | None = None
_active_worker_threads: list[threading.Thread] = []


def _worker_refill_allowed(*, ended: bool, playback: _PlaybackBuffer) -> bool:
    """Keep workers alive for real work, not a drained LIVE-END grace period.

    The main loop intentionally stays alive for three seconds after LIVE-END so
    the same speaker can observe a back-to-back LIVE-START.  During that grace
    period drained workers are expected to exit; refilling them before reading
    the stream only makes each replacement observe the same ended state and
    exit again.  A later LIVE-START clears ``ended`` and immediately reopens
    refill after the stream state has been consumed.
    """
    return not ended or not playback.is_drained()


def _close_playback_before_unlock(
    playback: _PlaybackBuffer | None = None,
    player_thread: threading.Thread | None = None,
    worker_threads: list[threading.Thread] | None = None,
    *, join_timeout: float = PLAYER_SHUTDOWN_JOIN_SECONDS,
    worker_join_timeout: float = WORKER_SHUTDOWN_JOIN_SECONDS,
) -> None:
    """Close playback and give all non-daemon audio threads bounded joins.

    The player and worker budgets are totals, not per-thread waits, so shutdown
    waits at most ``join_timeout + worker_join_timeout`` before releasing the
    narrator lock.  A thread that outlives that budget remains non-daemon and
    therefore still reaches its WAV/MP3 cleanup ``finally`` before interpreter
    teardown.
    """
    global _active_playback, _active_player_thread, _active_worker_threads
    target = playback if playback is not None else _active_playback
    thread = player_thread if player_thread is not None else _active_player_thread
    workers = list(
        _active_worker_threads if worker_threads is None else worker_threads)
    if target is not None:
        target.close()
    if (thread is not None and thread is not threading.current_thread()
            and thread.is_alive()):
        thread.join(timeout=max(0.0, float(join_timeout)))
        if thread.is_alive():
            # The thread is intentionally non-daemon: release the narrator lock
            # after this bounded wait, while Python still guarantees its playback
            # finally runs and removes the claimed WAV before process teardown.
            log("播放器仍在完成当前句；已结束接单，当前 WAV 将由播放 finally 清理")
    worker_deadline = time.monotonic() + max(
        0.0, float(worker_join_timeout))
    for worker in workers:
        if worker is threading.current_thread() or not worker.is_alive():
            continue
        worker.join(timeout=max(0.0, worker_deadline - time.monotonic()))
    live_workers = [worker for worker in workers if worker.is_alive()]
    if live_workers:
        log(
            f"仍有 {len(live_workers)} 个合成线程在完成当前句；已结束接单，"
            "临时 MP3/WAV 将由合成 finally 清理"
        )
    if target is _active_playback:
        _active_playback = None
    if thread is _active_player_thread:
        _active_player_thread = None
    if worker_threads is None or worker_threads is _active_worker_threads:
        # Retain any thread that exceeded the bounded join so the fatal path can
        # observe it again; non-daemon status guarantees its cleanup can finish.
        _active_worker_threads = live_workers


def _player_loop(playback: _PlaybackBuffer, eng, *, is_ended, stop=None) -> None:
    stop = stop or stop_requested
    while not stop():
        try:
            item = playback.wait_next(
                stop=stop,
                drained=lambda: bool(is_ended()) and playback.is_drained(),
            )
            if item is None:
                return
            seq, wav, sent, timed_out = item
            if timed_out:
                log(f"第 {seq} 句合成超时未归，SAPI 兜底")
            try:
                if wav is not None:
                    try:
                        _play_wav_with_gain(wav)
                    finally:
                        _discard_wav(wav)
                elif sent:
                    eng.say_fallback(sent)
            except Exception as exc:
                import traceback
                log(f"播放失败：{exc!r}\n{traceback.format_exc()[-500:]}")
            finally:
                playback.mark_played(seq)
        except Exception as exc:
            # 播放器线程死亡 = 永久静默且无人知晓
            import traceback
            log(f"播放线程异常（继续）：{exc!r}\n{traceback.format_exc()[-400:]}")
            time.sleep(1)


def main() -> int:
    global _active_playback, _active_player_thread, _active_worker_threads
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

    _scavenge_edge_artifacts()
    start_volume_hotkeys()
    eng = EdgeEngine()
    log(f"edge-tts 朗读器上线（统一嗓音 {VOICE}）")

    playback = _PlaybackBuffer()
    _active_playback = playback
    q = playback.work
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
    counters = playback.counters
    # 合成健康度：连续失败熔断 + 心跳可观测（静默必须可诊断）
    synth_stats = {"ok": 0, "fail": 0, "consec_fail": 0, "sapi_until": 0.0, "next_beat": 20}

    def synth_worker(wid: int) -> None:
        while not stop_requested() and not playback.closed:
            try:
                try:
                    seq, sent = q.get(timeout=0.5)
                except queue.Empty:
                    # 仅当"复盘结束且播放器已追平"才收工。此前只看 ended+队列空：
                    # 复盘间隙队列恰好排空而播放器还在播存量 → 3 个 worker 集体
                    # 退出 → 下一场复盘开始后无人合成 → 僵尸朗读器静默数小时
                    # （520 句心跳戛然而止实证）。
                    if (playback.closed or stop_requested()
                            or (ended and counters["played"] >= counters["put"])):
                        return
                    continue
                if not playback.should_synthesize(seq, sent):
                    continue
                # 旧 speaker 释放 voice lock 后 worker 仍可能迟到；PID +
                # nonce 隔离可防它的 cleanup 误删新 speaker 的同序号 WAV/MP3。
                wav = playback.wav_path(TTS_DIR, seq)
                if time.time() < synth_stats["sapi_until"]:
                    # 熔断期：不再尝试 edge（网络性死亡防全哑），直接交 SAPI 兜底
                    playback.publish_result(seq, None, sent)
                    continue
                ok = eng.synth_to_wav(sent, wav)
                if ok:
                    synth_stats["ok"] += 1
                    synth_stats["consec_fail"] = 0
                else:
                    _discard_wav(wav)
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
                playback.publish_result(seq, wav if ok else None, sent)
            except Exception as exc:
                # worker 线程静默死亡 = 该句永不完成且无人知晓（stderr 进隐藏控制台不可见）
                import traceback
                log(f"合成线程异常（继续）：{exc!r}\n{traceback.format_exc()[-400:]}")
                time.sleep(1)

    worker_threads: list[threading.Thread] = []
    _active_worker_threads = worker_threads

    def spawn_worker() -> None:
        worker_id = len(worker_threads)
        t = threading.Thread(
            target=synth_worker,
            args=(worker_id,),
            name=f"edge-synth-{worker_id}",
            daemon=False,
        )
        worker_threads.append(t)
        t.start()

    def ensure_workers() -> None:
        """worker 灭绝即重新拉起（双保险：退出条件收紧后仍留兜底），并大声记日志。"""
        if not _worker_refill_allowed(ended=ended, playback=playback):
            return
        alive = [t for t in worker_threads if t.is_alive()]
        if len(alive) < 3:
            log(f"[edge-voice] 合成线程仅存 {len(alive)}/3，重新补齐（防僵尸朗读器）")
            del worker_threads[:]
            worker_threads.extend(alive)
            for _ in range(3 - len(alive)):
                spawn_worker()

    for _wid in range(3):
        spawn_worker()

    player_thread = threading.Thread(
        target=_player_loop,
        args=(playback, eng),
        kwargs={"is_ended": lambda: ended},
        name="edge-playback",
        daemon=False,
    )
    _active_player_thread = player_thread
    player_thread.start()

    while not stop_requested():
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
                        # 入队即登记原文；满队列仍保持“丢最老一半”，被丢序号
                        # 立即发布 skip marker，不制造 90 秒空等区间。
                        playback.enqueue(sent)
                        recent_texts.append(sent)
                        del recent_texts[:-8]
            if ended and time.time() - end_at > 3 and q.empty() and counters["played"] >= counters["put"]:
                break
            # Consume LIVE-START/LIVE-END before deciding whether a dead pool is
            # actionable.  A drained LIVE-END is normal shutdown; a subsequent
            # LIVE-START reopens refill in this same iteration.
            ensure_workers()
            if wait_for_stop(0.5):
                break
        except Exception as exc:
            log(f"主循环异常（继续）：{exc}")
            if wait_for_stop(2):
                break

    # This lock protects Edge/SAPI narrator instances only.  Release it before
    # cleanup/waiting so a following review's Edge voice is never blocked by
    # the independent white-voice conclusion.
    # Close the producer/player contract before another speaker can acquire the
    # voice lock.  Non-daemon workers get one shared bounded join budget; any
    # late result is rejected by the closed buffer and its private WAV is deleted.
    _close_playback_before_unlock(playback, player_thread, worker_threads)
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
        _close_playback_before_unlock()
        release_voice_lock()
        sys.exit(0)
