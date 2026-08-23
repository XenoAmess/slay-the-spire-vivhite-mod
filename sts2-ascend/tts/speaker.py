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

import os
import queue
import re
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
SUMMARY_TEXT_FILE = TTS_DIR / "conclusion_text.txt"
SPEAK_ONCE = TTS_DIR / "speak_once.py"

DURATION_FACTOR = 0.9       # index-tts 语速（稍快）
SAPI_RATE = 1               # SAPI 语速（-10~10）
MAX_QUEUE = 2               # 积压超过 2 句丢最旧
MAX_SENTENCE = 90
TERMINATORS = "。！？!?\n"
SOFT_BREAKS = "，、；;：:"

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
while (($line = [Console]::In.ReadLine()) -ne $null) {
    if ($line.StartsWith('en|')) { $en.Speak($line.Substring(3)) }
    elseif ($line.StartsWith('zh|')) { $zh.Speak($line.Substring(3)) }
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
    """常驻 PowerShell + System.Speech，逐行朗读；每句读完回执 ok（保证多引擎混排时顺序不乱）。"""

    def __init__(self) -> None:
        script = _SAPI_PS.replace("__RATE__", str(SAPI_RATE))
        self.proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        self._ack_lock = threading.Lock()

    def say(self, text: str, wait: bool = True) -> None:
        try:
            if self.proc.poll() is not None:
                return
            with self._ack_lock:
                self.proc.stdin.write(lang_of(text) + "|" + text + "\n")
                self.proc.stdin.flush()
                if wait:  # 等朗读完成回执；超时兜底防死锁
                    self.proc.stdout.readline()
        except (OSError, ValueError):
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

    sapi = SapiSpeaker() if mode in ("sapi", "hybrid") else None
    log(f"语音朗读器上线（模式 {mode}）")

    q: queue.Queue = queue.Queue(maxsize=MAX_QUEUE)
    splitter = SentenceSplitter()
    state = {"offset": 0}
    ended = False
    end_at = 0.0
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
            if not speakable(ln):
                continue
            for sent in splitter.feed(ln):
                if q.full():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        pass
                q.put(sent)
        if ended:
            for sent in splitter.flush():
                if speakable(sent):
                    q.put(sent)
            if time.time() - end_at > 3 and q.empty():
                break
        time.sleep(0.5)

    if mode in ("indextts", "hybrid") and recent_texts:
        conclusion = "。".join(recent_texts[-4:])[:300]
        _speak_conclusion_indextts(conclusion)
    if sapi:
        sapi.close()
    log("语音朗读器退出")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"致命异常（静默退出）：{exc}")
        sys.exit(0)
