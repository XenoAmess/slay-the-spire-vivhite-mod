"""ASCEND-VOICE —— 复盘直播语音朗读器（index-tts 旁路进程）。

在 index-tts 的 uv 虚拟环境中运行（由 llm_review 复盘启动时自动拉起，也可手动）：

  uv run --project third_party/index-tts python tts/speaker.py          # 直播模式
  uv run --project third_party/index-tts python tts/speaker.py --test   # 合成一句试听

数据源：knowledge/review_live.stream（与直播悬浮窗同一份）。
行为：断句 → 过滤（工具/统计/代码行不读）→ 队列（积压丢旧读新）→ IndexTTS-2.5
克隆 tts/reference_voice_15s.wav 的音色合成 → winsound 播放 → LIVE-END 后自动退出。
任何异常只写日志，绝不影响复盘与游玩。
"""
from __future__ import annotations

import os
import queue
import re
import shutil
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
OUT_WAV = TTS_DIR / "speaker_out.wav"
INDEXTTS_DIR = BASE_DIR / "third_party" / "index-tts"

DURATION_FACTOR = 0.9       # 稍快
MAX_QUEUE = 2               # 积压超过 2 句丢最旧
MAX_SENTENCE = 90           # 超长强制断句
TERMINATORS = "。！？!?\n"
SOFT_BREAKS = "，、；;：:"

_tts = None
_tts_lock = threading.Lock()


def log(msg: str) -> None:
    line = f"[voice {time.strftime('%H:%M:%S')}] {msg}"
    try:
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def speakable(line: str) -> bool:
    """几乎全读：只跳过哨兵/统计/工具/代码行。"""
    s = line.strip()
    if not s or s.startswith(("[LIVE-", "· tokens", "⚙", "📦")):
        return False
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    if cjk == 0:
        alpha = sum(c.isalpha() for c in s)
        if alpha / max(1, len(s)) < 0.5:      # 纯符号/路径/代码行
            return False
    return True


class SentenceSplitter:
    """流式断句：终结符断句，超长按软断点/硬切。"""

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


def _init_engine():
    """加载 IndexTTS-2.5（GTX 1060 无 bf16 硬件加速，用默认精度；OOM 自动退 CPU）。"""
    global _tts
    sys.path.insert(0, str(INDEXTTS_DIR))
    from indextts.infer_v2_5 import IndexTTS2
    ckpt = INDEXTTS_DIR / "checkpoints"
    try:
        _tts = IndexTTS2(cfg_path=str(ckpt / "config.yaml"), model_dir=str(ckpt), use_bf16=False)
        log("引擎已加载（GPU）")
    except Exception as exc:
        log(f"GPU 加载失败（{exc}），退 CPU")
        _tts = IndexTTS2(cfg_path=str(ckpt / "config.yaml"), model_dir=str(ckpt),
                         use_bf16=False, device="cpu")
        log("引擎已加载（CPU）")


def _synthesize_and_play(text: str) -> None:
    ref = TTS_DIR / "reference_voice_15s.wav"
    if not ref.exists():
        ref = TTS_DIR / "reference_voice.wav"
    with _tts_lock:
        _tts.infer(spk_audio_prompt=str(ref), text=text, lang="ZH",
                   output_path=str(OUT_WAV), duration_factor=DURATION_FACTOR, verbose=False)
    winsound.PlaySound(str(OUT_WAV), winsound.SND_FILENAME)


def _voice_worker(q: queue.Queue, stop: threading.Event) -> None:
    while not stop.is_set() or not q.empty():
        try:
            sent = q.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _synthesize_and_play(sent)
        except Exception as exc:
            log(f"合成/播放失败（跳过本句）：{exc}")


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
    if "--test" in sys.argv:
        log("试听模式")
        _init_engine()
        _synthesize_and_play("你好，我是白绮的教练。复盘直播语音链路已打通。")
        return 0

    if not STREAM_FILE.exists():
        log("直播流不存在，退出")
        return 0
    _init_engine()

    q: queue.Queue = queue.Queue(maxsize=MAX_QUEUE)
    stop = threading.Event()
    threading.Thread(target=_voice_worker, args=(q, stop), daemon=True).start()

    splitter = SentenceSplitter()
    state = {"offset": 0}
    ended = False
    end_at = 0.0
    log("语音朗读器上线")
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
                        q.get_nowait()      # 丢最旧，读最新
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
    stop.set()
    log("语音朗读器退出")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"致命异常（静默退出）：{exc}")
        sys.exit(0)
