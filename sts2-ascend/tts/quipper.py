"""白绮碎碎念 + 复盘最终结论共用的 IndexTTS-2.5 GPU owner。

设计（按用户要求）：
  - **每次都用 LLM 现写**：无固定池。投喂当前战况 + 人设 prompt 给一个免费模型
    （默认 minimax-cn-coding-plan/MiniMax-M3，cfg llm.quip_model 可改），
    生成 10 字内随性短评（高随机、像人）。
  - **节奏**：上一条**播完之后**才开始计时，随机 20~45 秒后看下一条。
  - **单模型**：本进程唯一持有 IndexTTS CUDA 模型；碎碎念和最终结论通过
    本机队列串行合成，绝不再启动第二份模型。实时复盘正文由 Edge TTS 独立播放。
  - **优先级**：结论 > 兼容模式复盘直播 > 碎碎念；同一 Index worker 严格串行。
    Edge 与白绮声音按用户要求允许同时播放。
  - LLM 失败的兜底：一句万能短评（"稳住"）——不读固定池。
  - 单实例锁 voice_quipper.lock；尊重全局音量/静音。

运行（IndexTTS 项目 venv，由大脑启动时拉起）：
  uv run --project third_party/index-tts python tts/quipper.py
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
import winsound
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TTS_DIR = BASE_DIR / "tts"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
INDEXTTS_DIR = BASE_DIR / "third_party" / "index-tts"
LOG_FILE = KNOWLEDGE_DIR / "tts_quipper.log"
LOCK_FILE = KNOWLEDGE_DIR / "voice_quipper.lock"
BUSY_FLAG = KNOWLEDGE_DIR / "voice_clone_busy.flag"          # 本进程正在播复盘/结论
SPEAKING_FLAG = KNOWLEDGE_DIR / "voice_quip_speaking.flag"   # 本进程正在播碎碎念
CONFIG_PATH = BASE_DIR / "brain" / "config.json"

MIN_GAP, MAX_GAP = 20, 45        # 上一条播完后的随机间隔（秒）
LLM_TIMEOUT = 45                 # 免费路由拥堵时快速失败转保底（90s 太久会显得哑巴）
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # 隐藏进程里调 console 程序必须加，否则弹黑窗
API = "http://127.0.0.1:8080"
FALLBACK_QUIPS = ["稳住", "继续", "看着打", "别慌"]   # 仅 LLM 失败时的兜底一句
HANDOFF_WAIT_SECONDS = 180.0

sys.path.insert(0, str(TTS_DIR))
from speaker import get_voice_state  # noqa: E402
from indextts_gpu import IndexTTSGpuEngine, SpeechService, worker_port  # noqa: E402
from indextts_client import health as owner_health  # noqa: E402
from owner_epoch import (OWNER_FEATURE_VERSION, OWNER_PROTOCOL_VERSION,  # noqa: E402
                         code_epoch, valid_code_epoch)
sys.path.insert(0, str(BASE_DIR / "brain"))
from lifecycle import SESSION_ID, stop_requested, wait_for_stop  # noqa: E402

OWNER_CODE_EPOCH = code_epoch(BASE_DIR)


def log(msg: str) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[quip {time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def _quip_model() -> str:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        m = (cfg.get("llm") or {}).get("quip_model")
        if m:
            return str(m)
    except (OSError, json.JSONDecodeError):
        pass
    return "minimax-cn-coding-plan/MiniMax-M3"


def _apply_gain_play(path: Path) -> None:
    """统一增益播放（0~400%，静音跳过）。"""
    import numpy as np
    st = get_voice_state()
    if st["muted"] or st["volume"] <= 0:
        return
    gain = st["volume"] / 100.0
    with wave.open(str(path), "rb") as w:
        frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        params = w.getparams()
    pcm = (frames.astype(np.float32) / 32768.0 * gain).clip(-1, 1)
    pcm16 = (pcm * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setparams(params)
        w.writeframes(pcm16.tobytes())
    winsound.PlaySound(str(path), winsound.SND_FILENAME)


# ---------------------------------------------------------------------------
# 战况采集
# ---------------------------------------------------------------------------

def _get_state() -> dict | None:
    try:
        with urllib.request.urlopen(f"{API}/state", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("data") if d.get("ok") else None
    except Exception:
        return None


def _state_brief(st: dict) -> str:
    screen = st.get("screen", "?")
    run = st.get("run") or {}
    parts = [f"界面={screen}", f"层数={run.get('floor', '?')}", f"血量={run.get('current_hp', '?')}/{run.get('max_hp', '?')}"]
    combat = st.get("combat")
    if screen == "COMBAT" and combat:
        p = combat.get("player") or {}
        parts.append(f"回合={st.get('turn', '?')} 能量={p.get('energy', '?')} 格挡={p.get('block', 0)}")
        enemies = [f"{e.get('name')}{e.get('current_hp')}/{e.get('max_hp')}"
                   for e in (combat.get("enemies") or []) if e.get("is_alive")]
        if enemies:
            parts.append("敌人=" + ",".join(enemies[:3]))
    return "；".join(str(x) for x in parts)


def _sig(st: dict) -> tuple:
    run = st.get("run") or {}
    combat = st.get("combat") or {}
    return (st.get("screen"), run.get("floor"), st.get("turn"),
            (combat.get("player") or {}).get("current_hp"))


# ---------------------------------------------------------------------------
# LLM 现写短评
# ---------------------------------------------------------------------------

def _llm_generate(brief: str) -> str | None:
    """第一轮：根据战况生成短评。"""
    binary = shutil.which("opencode")
    if not binary:
        return None
    prompt = (
        "你是「白绮」，一位正在围观杀戮尖塔2自动对局的温柔俏皮小教练。"
        f"当前战况：{brief}\n"
        "请据此即兴说一句短评/吐槽。要求：10 个汉字以内、口语化、像真人随口说的、可以俏皮一点。"
        "只输出这句话本身——不要引号、不要解释、不要任何其他内容。"
    )
    try:
        proc = subprocess.run([binary, "run", "--model", _quip_model(),
                               "--dir", str(BASE_DIR.parent), prompt],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=LLM_TIMEOUT,
                              creationflags=_NO_WINDOW)
        out = (proc.stdout or "").strip()
        if not out:
            return None
        line = out.splitlines()[0].strip().strip('"\'“”‘’')
        line = re.sub(r"^[（(\[].*?[)）\]]", "", line).strip()
        return line[:20] if line else None
    except Exception as exc:
        log(f"LLM 短评生成失败：{exc}")
        return None


def _llm_audit(brief: str, quip: str) -> bool:
    """第二轮：内容审计。**必须模型显式输出 PASS 才算通过**——
    未知报错/异常一律判不通过（否则有把报错报文直接读出来的风险）。"""
    binary = shutil.which("opencode")
    if not binary:
        return False
    prompt = (
        "你是直播内容审计员。下面这句是一个游戏解说 AI 根据战况即兴说的短评。\n"
        f"战况：{brief}\n"
        f"短评：「{quip}」\n"
        "审计三项：1) 与战况场景相关（不离题）；2) 适合作为直播内容说出（无脏字/敏感/违规内容）；"
        "3) 符合内容安全条例。\n"
        "三项全过才在第一行输出 PASS；任一项不过输出 FAIL。不要输出任何其他内容。"
    )
    try:
        proc = subprocess.run([binary, "run", "--model", _quip_model(),
                               "--dir", str(BASE_DIR.parent), prompt],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=LLM_TIMEOUT,
                              creationflags=_NO_WINDOW)
        out = (proc.stdout or "").strip()
        first = out.splitlines()[0].strip().upper() if out else ""
        ok = first.startswith("PASS")      # 显式合法才算过（未知报错/异常 → False）
        if not ok:
            log(f"审计未通过：「{quip}」（{first[:60] or '空响应'}）")
        return ok
    except Exception as exc:
        log(f"审计调用异常（判不通过）：{exc}")
        return False


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------

def _pid_alive(pid: int, created_unix: float = 0.0) -> bool:
    """OpenProcess + 映像名校验。仅凭 OpenProcess 成功判活会被 pid 复用毒锁：
    锁 pid 被无关进程复用时误判"活着"→ 单实例锁永久锁死（悬浮窗消失事故）。"""
    if pid <= 0:
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            if created_unix > 0:
                class FileTime(ctypes.Structure):
                    _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]
                k32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(FileTime)] * 4
                created, exited, kernel, user = FileTime(), FileTime(), FileTime(), FileTime()
                if k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                                       ctypes.byref(kernel), ctypes.byref(user)):
                    ticks = (int(created.high) << 32) | int(created.low)
                    actual_unix = ticks / 10_000_000 - 11_644_473_600
                    if abs(actual_unix - created_unix) > 0.1:
                        return False
            buf = ctypes.create_unicode_buffer(512)
            size = ctypes.c_ulong(512)
            k32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                                       ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return "python" in buf.value.lower()
            return True   # 映像名拿不到（权限等）：保守视为活
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


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


def _process_creation_identity(pid: int) -> tuple[int, float]:
    try:
        import ctypes

        class FileTime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

        k32 = ctypes.windll.kernel32
        k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(FileTime)] * 4
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenProcess(0x1000, False, pid)
        if not h:
            return 0, 0.0
        try:
            created, exited, kernel, user = FileTime(), FileTime(), FileTime(), FileTime()
            if not k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                                       ctypes.byref(kernel), ctypes.byref(user)):
                return 0, 0.0
            ticks = (int(created.high) << 32) | int(created.low)
            return ticks, ticks / 10_000_000 - 11_644_473_600
        finally:
            k32.CloseHandle(h)
    except Exception:
        return 0, 0.0


def _release_own_lock() -> None:
    """Delete only the quipper lock still owned by this process."""
    try:
        raw = LOCK_FILE.read_text(encoding="utf-8").strip()
        record = json.loads(raw) if raw.startswith("{") else {"pid": int(raw or "0")}
        if (int(record.get("pid", 0)) == os.getpid() and
                record.get("session_id", SESSION_ID) == SESSION_ID and
                record.get("owner_code_epoch", OWNER_CODE_EPOCH) == OWNER_CODE_EPOCH):
            LOCK_FILE.unlink(missing_ok=True)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    for flag in (SPEAKING_FLAG, BUSY_FLAG):
        try:
            if int(flag.read_text(encoding="utf-8").strip() or "0") == os.getpid():
                flag.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def _own_owner_record() -> dict:
    creation_filetime, created_unix = _process_creation_identity(os.getpid())
    return {
        "pid": os.getpid(),
        "session_id": SESSION_ID,
        "created_unix": created_unix or time.time(),
        "creation_filetime": creation_filetime,
        "owner_protocol_version": OWNER_PROTOCOL_VERSION,
        "owner_feature_version": OWNER_FEATURE_VERSION,
        "owner_code_epoch": OWNER_CODE_EPOCH,
        "executable": sys.executable,
        "script": str(Path(__file__).resolve()),
    }


def _read_owner_lock() -> tuple[str, dict] | None:
    try:
        raw = LOCK_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        record = json.loads(raw) if raw.startswith("{") else {
            "pid": int(raw), "session_id": "legacy",
        }
        return raw, record
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _claim_owner_lock(record: dict) -> bool:
    """Create the owner lock atomically; contenders can never both claim it."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
    except Exception:
        try:
            LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return True


def _remove_stale_lock(raw: str) -> None:
    """Remove only the exact stale snapshot we inspected."""
    try:
        if LOCK_FILE.read_text(encoding="utf-8").strip() == raw:
            LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _health_matches_lock(status: object, record: dict) -> bool:
    if not isinstance(status, dict):
        return False
    try:
        if (str(status.get("session_id", "legacy")) != str(record.get("session_id", "legacy"))
                or int(status.get("owner_pid", 0)) != int(record.get("pid", 0))
                or str(status.get("owner_code_epoch", "")).lower()
                != str(record.get("owner_code_epoch", "")).lower()
                or int(status.get("owner_protocol_version", 0)) < OWNER_PROTOCOL_VERSION):
            return False
        expected_filetime = int(record.get("creation_filetime", 0))
        if expected_filetime:
            return int(status.get("owner_creation_filetime", 0)) == expected_filetime
        expected_unix = float(record.get("created_unix", 0.0))
        actual_unix = float(status.get("owner_created_unix", 0.0))
        return expected_unix > 0 and actual_unix > 0 and abs(expected_unix - actual_unix) <= 0.1
    except (TypeError, ValueError):
        return False


def _request_handoff(record: dict) -> bool:
    status = owner_health(timeout=1.0)
    if not _health_matches_lock(status, record):
        log("旧 owner 的 health 与锁身份不一致；不发送交接请求，也不触碰该进程")
        return False
    payload = json.dumps({
        "session_id": SESSION_ID,
        "owner_pid": int(record.get("pid", 0)),
        "owner_created_unix": float(record.get("created_unix", 0.0)),
        "owner_creation_filetime": int(record.get("creation_filetime", 0)),
        "owner_code_epoch": str(record.get("owner_code_epoch", "")),
        "requested_code_epoch": OWNER_CODE_EPOCH,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{worker_port()}/handoff", data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
            result = json.loads(response.read().decode("utf-8"))
        return bool(result.get("accepted"))
    except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError) as exc:
        log(f"旧 owner 拒绝或未响应协作交接：{exc}")
        return False


def _acquire_owner_lock(record: dict) -> bool:
    """Acquire ownership, draining a compatible older code generation first."""
    while not stop_requested():
        snapshot = _read_owner_lock()
        if snapshot is None:
            if _claim_owner_lock(record):
                return True
            continue
        raw, owner = snapshot
        owner_pid = int(owner.get("pid", 0))
        owner_created = float(owner.get("created_unix", 0.0))
        if not _pid_alive(owner_pid, owner_created):
            _remove_stale_lock(raw)
            continue
        owner_session = str(owner.get("session_id", "legacy"))
        if owner_session != SESSION_ID:
            log(f"发现其他 session 的活 owner {owner_pid}；不接管、不触碰")
            return False
        owner_epoch = str(owner.get("owner_code_epoch", "")).lower()
        try:
            owner_protocol = int(owner.get("owner_protocol_version", 0))
        except (TypeError, ValueError):
            owner_protocol = 0
        if owner_protocol >= OWNER_PROTOCOL_VERSION and owner_epoch == OWNER_CODE_EPOCH:
            log(f"当前代码代次 owner 已存在（pid {owner_pid}，epoch {OWNER_CODE_EPOCH[:12]}）")
            return False
        if owner_protocol < OWNER_PROTOCOL_VERSION or not valid_code_epoch(owner_epoch):
            log(
                f"当前 owner pid {owner_pid} 不支持在线代次交接；"
                "保留旧进程，需下一次统一 Stop/Start 完成一次迁移"
            )
            return False
        if not _request_handoff(owner):
            return False
        log(
            f"已请求旧 owner pid {owner_pid} 在当前语音排水后交接 "
            f"{owner_epoch[:12]} -> {OWNER_CODE_EPOCH[:12]}"
        )
        deadline = time.monotonic() + HANDOFF_WAIT_SECONDS
        while _pid_alive(owner_pid, owner_created):
            if stop_requested():
                return False
            if time.monotonic() >= deadline:
                log("旧 owner 未在 180 秒内完成空闲交接；不强杀，候选退出")
                return False
            time.sleep(0.2)
        _remove_stale_lock(raw)
    return False


def _set_busy(source: str | None) -> None:
    """Publish compatibility flags while the one GPU worker owns the speaker."""
    for flag in (SPEAKING_FLAG, BUSY_FLAG):
        try:
            if int(flag.read_text(encoding="utf-8").strip() or "0") == os.getpid():
                flag.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
    if source is None:
        return
    target = SPEAKING_FLAG if source == "quip" else BUSY_FLAG
    try:
        target.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    _hide_own_console()
    if stop_requested():
        return 0
    owner_record = _own_owner_record()
    if not _acquire_owner_lock(owner_record):
        return 0

    if not (INDEXTTS_DIR / "checkpoints" / "config.yaml").exists():
        raise FileNotFoundError("IndexTTS 模型未就绪；GPU-only 模式不回退 CPU/MOSS")
    gpu_engine = IndexTTSGpuEngine(log)
    service = SpeechService(
        gpu_engine, session_id=SESSION_ID, play=_apply_gain_play,
        log=log, on_busy=_set_busy, owner_identity=owner_record,
        owner_code_epoch=OWNER_CODE_EPOCH,
    )
    service.start_http(worker_port())
    rng = random.Random()
    log(
        f"白绮 IndexTTS GPU owner 上线（LLM 现写：{_quip_model()}，"
        f"端口 {worker_port()}，epoch {OWNER_CODE_EPOCH[:12]}，"
        f"feature {OWNER_FEATURE_VERSION}，播完后随机 {MIN_GAP}~{MAX_GAP}s 间隔）"
    )

    last_play_end = 0.0
    next_gap = rng.uniform(MIN_GAP, MAX_GAP)
    last_sig = None

    try:
        while not stop_requested():
            if service.handoff_requested():
                if service.wait_handoff_idle(0.2):
                    log("已拒绝新请求并完整排空当前语音；旧代码代次协作退出")
                    break
                continue
            if wait_for_stop(3):
                break
            try:
                st = _get_state()
                if not st:
                    continue
                screen = st.get("screen", "")
                run = st.get("run")
                if not run or screen in ("MAIN_MENU", "CHARACTER_SELECT", "GAME_OVER", "UNKNOWN", "UNLOCK"):
                    continue
                if BUSY_FLAG.exists():            # 复盘/结论在合成或播放 → 让位
                    continue
                sig = _sig(st)
                if sig == last_sig:               # 局面没变化
                    continue
                now = time.time()
                if now - last_play_end < next_gap:   # 上条播完后还没攒够间隔
                    continue

                brief = _state_brief(st)
                # 生成→审计 循环：被毙立刻重生成再审，直到出合法句（上限 6 次防 LLM 死循环）
                text = None
                for attempt in range(6):
                    if stop_requested() or service.handoff_requested():
                        break
                    cand = _llm_generate(brief)
                    if service.handoff_requested():
                        break
                    if not cand:
                        break                          # 生成失败 → 直接走保底
                    if _llm_audit(brief, cand):
                        text = cand
                        break
                    log(f"审计被毙（第 {attempt + 1} 次），立即重生成：「{cand}」")
                if stop_requested() or service.handoff_requested():
                    break
                if not text:
                    text = rng.choice(FALLBACK_QUIPS)   # 保底句（预置安全文本，无需审计）
                last_sig = sig
                log(f"[{screen}] {text}（战况：{brief}）")

                if stop_requested() or service.handoff_requested():
                    break
                service.submit(text, "quip", timeout=900.0)
                last_play_end = time.time()
                next_gap = rng.uniform(MIN_GAP, MAX_GAP)
            except Exception as exc:
                log(f"循环异常（继续）：{exc}")
    finally:
        service.close()
    log("收到全栈停止请求，碎碎念退出")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        import traceback
        log(f"致命异常（GPU-only owner 退出）：{exc}\n{traceback.format_exc()[-1600:]}")
        sys.exit(1)
    finally:
        _release_own_lock()
