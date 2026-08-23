"""ASCEND-VOICE —— 复盘直播语音朗读器（stdlib 版，随大脑 Python 直接运行）。

模式（argv[1] 或环境变量 TTS_MODE）：
  sapi     —— Windows 自带语音（Microsoft Huihui，中文女声）实时朗读直播流，零成本零延迟
  indextts —— 全部用 index-tts 克隆音色（GTX 1060 上很慢，仅离线适用）
  hybrid   —— 直播过程走 SAPI；复盘结束时的结论段用 index-tts 克隆音色朗读（默认）

手动：
  py -3 tts/speaker.py                 # 直播模式（tail review_live.stream）
  py -3 tts/speaker.py --test          # SAPI 试听一句

任何异常只写日志，绝不影响复盘与游玩。
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import winsound
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent           # sts2-ascend/
TTS_DIR = BASE_DIR / "tts"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
STREAM_FILE = KNOWLEDGE_DIR / "review_live.stream"
LOG_FILE = KNOWLEDGE_DIR / "tts_speaker.log"
SUMMARY_TEXT_FILE = TTS_DIR / "conclusion_text.txt"
SPEAK_ONCE = TTS_DIR / "speak_once.py"

DURATION_FACTOR = 0.9       # index-tts 语速（稍快）
SAPI_RATE = 1               # SAPI 语速（-10~10）
MAX_QUEUE = 256             # 朗读队列上限；到顶时立刻丢弃最老的一半
MAX_SENTENCE = 90
TERMINATORS = "。！？!?\n"
SOFT_BREAKS = "，、；;：:"

# ---- 语音单实例锁（所有朗读器共享，防双音齐发） ----
VOICE_LOCK = KNOWLEDGE_DIR / "voice_speaker.lock"


def _pid_alive(pid: int) -> bool:
    """进程存活检查。os.kill(pid,0) 在 Windows 上偶发 SystemError 风格的 ctypes 错误
    （"returned a result with an exception set"），会绕过 OSError 捕获搞崩整个朗读器——
    改用 OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) 这个稳的路径。"""
    if pid <= 0:
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    except Exception:
        return False


def acquire_voice_lock() -> bool:
    try:
        if VOICE_LOCK.exists():
            old = int(VOICE_LOCK.read_text().strip() or "0")
            if old and _pid_alive(old):
                return False
        VOICE_LOCK.write_text(str(os.getpid()))
        return True
    except (OSError, ValueError):
        return True


def release_voice_lock() -> None:
    try:
        VOICE_LOCK.unlink(missing_ok=True)
    except OSError:
        pass


# ---- 音量控制（跨进程共享：knowledge/voice_volume.json） ----
VOLUME_FILE = KNOWLEDGE_DIR / "voice_volume.json"


def get_voice_state() -> dict:
    try:
        d = json.loads(VOLUME_FILE.read_text(encoding="utf-8"))
        return {"volume": max(0, min(400, int(d.get("volume", 100)))),
                "muted": bool(d.get("muted", False))}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"volume": 100, "muted": False}


def set_voice_state(volume: int | None = None, muted: bool | None = None) -> dict:
    st = get_voice_state()
    if volume is not None:
        st["volume"] = max(0, min(400, int(volume)))
    if muted is not None:
        st["muted"] = bool(muted)
    try:
        VOLUME_FILE.write_text(json.dumps(st), encoding="utf-8")
    except OSError:
        pass
    return st


def start_volume_hotkeys() -> None:
    """Ctrl+Shift+Alt+↑/↓ 调音量（±10），Ctrl+Shift+Alt+M 静音切换。
    轮询实现无需窗口聚焦；避开与网易云音乐冲突的 Ctrl+Alt 组合。"""
    import ctypes

    def _loop() -> None:
        prev = {"up": False, "down": False, "mute": False}
        u32 = ctypes.windll.user32
        while True:
            try:
                ctrl = bool(u32.GetAsyncKeyState(0x11) & 0x8000)
                shift = bool(u32.GetAsyncKeyState(0x10) & 0x8000)
                alt = bool(u32.GetAsyncKeyState(0x12) & 0x8000)
                up = bool(u32.GetAsyncKeyState(0x26) & 0x8000)
                down = bool(u32.GetAsyncKeyState(0x28) & 0x8000)
                mute = bool(u32.GetAsyncKeyState(0x4D) & 0x8000)   # M 键
                combo = ctrl and shift and alt
                if combo and up and not prev["up"]:
                    st = set_voice_state(volume=get_voice_state()["volume"] + 10)
                    log(f"音量 +10 → {st['volume']}%")
                if combo and down and not prev["down"]:
                    st = set_voice_state(volume=get_voice_state()["volume"] - 10)
                    log(f"音量 -10 → {st['volume']}%")
                if combo and mute and not prev["mute"]:
                    st = set_voice_state(muted=not get_voice_state()["muted"])
                    log("静音" if st["muted"] else f"取消静音（{st['volume']}%）")
                prev = {"up": up and combo, "down": down and combo, "mute": mute and combo}
            except Exception:
                pass
            time.sleep(0.12)

    threading.Thread(target=_loop, daemon=True, name="volume-hotkeys").start()

_SAPI_PS = r"""
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$zh = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $zh.SelectVoice('Microsoft Huihui Desktop') } catch {}
$zh.Rate = __RATE__
$en = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $en.SelectVoice('Microsoft Zira Desktop') } catch {}
$en.Rate = __RATE__
$tmp = '__TMPWAV__'
while (($line = [Console]::In.ReadLine()) -ne $null) {
    $use = $zh; $txt = $line
    if ($line.StartsWith('en|')) { $use = $en; $txt = $line.Substring(3) }
    elseif ($line.StartsWith('zh|')) { $txt = $line.Substring(3) }
    if ($txt.Trim()) {
        try {
            $use.SetOutputToWaveFile($tmp)
            $use.Speak($txt)
            $use.SetOutputToNull()
        } catch {}
    }
    [Console]::Out.WriteLine('ok')
    [Console]::Out.Flush()
}
"""


def log(msg: str) -> None:
    line = f"[voice {time.strftime('%H:%M:%S')}] {msg}"
    try:
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


_CODE_RE = re.compile(
    r'[{}\[\]]'                       # 括号结构（JSON/代码）
    r'|"\w+"\s*:'                     # "key": value
    r'|==|!=|<=|>='                   # 比较运算
    r'|\w+\.(?:py|json|md|log|yaml|yml|toml|wav|txt|ps1)\b'   # 文件名
    r'|\w+\(.*\)'                     # 函数调用 f(...)
    r'|^\s*[/\]<>$|]'                 # 路径/命令行开头
)


def speakable(line: str) -> bool:
    """只读直播窗里的分析/思维链文字：哨兵/统计/工具/代码/JSON/路径行一律不读。"""
    s = line.strip()
    if not s or s.startswith(("[LIVE-", "· tokens", "⚙", "📦")):
        return False
    if _CODE_RE.search(s):
        return False
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    if cjk == 0:
        alpha = sum(c.isalpha() for c in s)
        if alpha / max(1, len(s)) < 0.5:      # 纯符号/数据行
            return False
    return True


def lang_of(sent: str) -> str:
    """含中文按中文读，纯英文按英文读（避免英文句里的数字被中文念出来）。"""
    return "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in sent) else "en"


class FenceStripper:
    """流式剥离 ``` 围栏代码块内容（围栏标记可跨行、可跨报文）。

    兜底：围栏内容超过 600 字仍未闭合，视为误判——恢复朗读，防止整段被吞。"""

    def __init__(self) -> None:
        self.in_fence = False
        self._bt = 0            # 连续反引号计数（跨行延续）
        self._fence_chars = 0

    def feed(self, line: str) -> str:
        out: list[str] = []
        for ch in line:
            if ch == "`":
                self._bt += 1
                if self._bt >= 3:
                    self.in_fence = not self.in_fence
                    self._fence_chars = 0
                    self._bt = 0
                continue
            if self._bt:
                if not self.in_fence:
                    out.append("`" * self._bt)
                self._bt = 0
            if self.in_fence:
                self._fence_chars += 1
                if self._fence_chars > 600:
                    self.in_fence = False      # 兜底：异常长围栏当误判处理
                continue
            out.append(ch)
        return "".join(out)


class SentenceSplitter:
    def __init__(self) -> None:
        self.buf = ""

    def feed(self, line: str) -> list[str]:
        self.buf += line.strip() + " "
        out: list[str] = []
        while True:
            cut = -1
            for i, ch in enumerate(self.buf):
                if ch in TERMINATORS:
                    cut = i
                    break
            if cut < 0 and len(self.buf) >= MAX_SENTENCE:
                soft = max(self.buf.rfind(c, 0, MAX_SENTENCE) for c in SOFT_BREAKS)
                cut = soft if soft > 20 else MAX_SENTENCE
            if cut < 0:
                break
            sent = self.buf[:cut + 1].strip("。！？!?\n ")
            self.buf = self.buf[cut + 1:]
            if sent:
                out.append(sent)
        return out

    def flush(self) -> list[str]:
        tail = self.buf.strip()
        self.buf = ""
        return [tail] if tail else []


class SapiSpeaker:
    """常驻 PowerShell + System.Speech 合成到 wav，Python 侧按音量增益后播放。

    改走文件是因为 SAPI 的 Volume 属性上限只有 100——想更响必须波形增益。
    每句读完回执 ok（保证多引擎混排时顺序不乱）。"""

    TMP_IN = TTS_DIR / "sapi_tmp.wav"
    TMP_OUT = TTS_DIR / "sapi_play.wav"

    def __init__(self) -> None:
        script = _SAPI_PS.replace("__RATE__", str(SAPI_RATE)).replace(
            "__TMPWAV__", str(self.TMP_IN).replace("\\", "/"))
        creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        self.proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=creationflags)
        self._ack_lock = threading.Lock()

    def say(self, text: str, wait: bool = True) -> None:
        try:
            if self.proc.poll() is not None:
                return
            with self._ack_lock:
                self.proc.stdin.write(lang_of(text) + "|" + text + "\n")
                self.proc.stdin.flush()
                if wait:  # 等合成完成回执
                    self.proc.stdout.readline()
            self._play_with_gain()
        except (OSError, ValueError):
            pass

    def _play_with_gain(self) -> None:
        import array
        import wave
        if not self.TMP_IN.exists():
            return
        st = get_voice_state()
        gain = 0.0 if st["muted"] else st["volume"] / 100.0
        try:
            with wave.open(str(self.TMP_IN), "rb") as w:
                frames = w.readframes(w.getnframes())
                params = w.getparams()
            if abs(gain - 1.0) > 0.01:
                a = array.array("h")
                a.frombytes(frames)
                for i, s in enumerate(a):
                    a[i] = max(-32768, min(32767, int(s * gain)))
                frames = a.tobytes()
            with wave.open(str(self.TMP_OUT), "wb") as w:
                w.setparams(params)
                w.writeframes(frames)
            winsound.PlaySound(str(self.TMP_OUT), winsound.SND_FILENAME)
        except Exception:
            try:  # 兜底：不增益直接播
                winsound.PlaySound(str(self.TMP_IN), winsound.SND_FILENAME)
            except Exception:
                pass

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
        except Exception:
            pass
        try:
            self.proc.kill()
        except Exception:
            pass


def _speak_conclusion_indextts(text: str) -> None:
    """用克隆音色读结论段：写文本到文件，spawn 旁路环境里的 speak_once.py（默认 MOSS-Nano 引擎）。"""
    try:
        SUMMARY_TEXT_FILE.write_text(text, encoding="utf-8")
    except OSError:
        return
    uv = shutil_which_uv()
    if not uv or not SPEAK_ONCE.exists():
        return
    if not (BASE_DIR / "third_party" / "MOSS-TTS-Nano" / "models").exists():
        log("MOSS-Nano 模型未就绪，跳过克隆音色结论")
        return
    try:
        subprocess.Popen([uv, "run", "--no-project",
                          "--with", "onnxruntime", "--with", "sentencepiece",
                          "--with", "torch", "--with", "torchaudio",
                          "python", str(SPEAK_ONCE), str(SUMMARY_TEXT_FILE)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log("结论段已交给 MOSS-Nano（克隆音色，后台合成）")
    except Exception as exc:
        log(f"克隆音色结论朗读启动失败：{exc}")


def shutil_which_uv() -> str | None:
    import shutil as _sh
    found = _sh.which("uv")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "uv.exe"
    return str(candidate) if candidate.exists() else None


def _tail_lines(state: dict) -> list[str]:
    try:
        size = STREAM_FILE.stat().st_size
        if size < state["offset"]:
            state["offset"] = 0
        if size == state["offset"]:
            return []
        with STREAM_FILE.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(state["offset"])
            data = f.read()
            state["offset"] = f.tell()
        return data.splitlines()
    except OSError:
        return []


def main() -> int:
    mode = "hybrid"
    for a in sys.argv[1:]:
        if a in ("sapi", "indextts", "hybrid"):
            mode = a
    mode = os.environ.get("TTS_MODE", mode)

    if "--test" in sys.argv:
        spk = SapiSpeaker()
        spk.say("你好，我是白绮的教练。语音链路已打通。")
        spk.say("Turn 5 had 4 block and 2 strikes, intent 27.")
        time.sleep(8)
        spk.close()
        return 0

    if not STREAM_FILE.exists():
        log("直播流不存在，退出")
        return 0
    if not acquire_voice_lock():
        log("已有朗读器在跑（单实例锁），本实例退出")
        return 0

    sapi = SapiSpeaker() if mode in ("sapi", "hybrid") else None
    start_volume_hotkeys()
    log(f"语音朗读器上线（模式 {mode}，音量控制：Ctrl+Shift+Alt+↑/↓ 调音量，Ctrl+Shift+Alt+M 静音）")

    q: queue.Queue = queue.Queue(maxsize=MAX_QUEUE)
    splitter = SentenceSplitter()
    fence = FenceStripper()
    state = {"offset": 0}
    ended = False
    end_at = 0.0
    stream_started_at = time.time()
    recent_texts: list[str] = []

    def pump() -> None:
        while True:
            try:
                sent = q.get(timeout=0.5)
            except queue.Empty:
                if ended:
                    return
                continue
            if sapi:
                sapi.say(sent)
            recent_texts.append(sent)
            del recent_texts[:-8]

    threading.Thread(target=pump, daemon=True).start()

    while True:
        for ln in _tail_lines(state):
            if ln.startswith("[LIVE-END]"):
                ended = True
                end_at = time.time()
                continue
            if ln.startswith("[LIVE-START]"):
                ended = False
                stream_started_at = time.time()
                continue
            ln = fence.feed(ln)          # 剥掉 ``` 围栏代码块（跨报文状态机）
            if not ln.strip():
                continue
            if not speakable(ln):
                continue
            for sent in splitter.feed(ln):
                if q.full():
                    for _ in range(MAX_QUEUE // 2):      # 到顶立刻丢最老的一半
                        try:
                            q.get_nowait()
                        except queue.Empty:
                            break
                q.put(sent)
        if ended:
            for sent in splitter.flush():
                if speakable(sent):
                    q.put(sent)
            if time.time() - end_at > 3 and q.empty():
                break
        time.sleep(0.5)

    if mode in ("indextts", "hybrid"):
        # 优先朗读复盘 agent 专为语音写的短评（review_conclusion.txt，100 字内）；
        # 只有它是本场复盘新写的（mtime 晚于本场开始）才用，否则回退流尾部
        conclusion = ""
        concl_file = KNOWLEDGE_DIR / "review_conclusion.txt"
        try:
            if concl_file.exists() and concl_file.stat().st_mtime >= stream_started_at:
                conclusion = concl_file.read_text(encoding="utf-8").strip()[:200]
        except OSError:
            pass
        if not conclusion and recent_texts:
            conclusion = "。".join(recent_texts[-4:])[:300]
        if conclusion:
            _speak_conclusion_indextts(conclusion)
    if sapi:
        sapi.close()
    release_voice_lock()
    log("语音朗读器退出")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"致命异常（静默退出）：{exc}")
        release_voice_lock()
        sys.exit(0)
