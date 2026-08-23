"""白绮碎碎念（quipper v2）——克隆音色的战况即兴点评。

设计（按用户要求）：
  - **每次都用 LLM 现写**：无固定池。投喂当前战况 + 人设 prompt 给一个免费模型
    （默认 openrouter/google/gemma-4-26b-a4b-it:free，cfg llm.quip_model 可改），
    生成 10 字内随性短评（高随机、像人）。
  - **节奏**：上一条**播完之后**才开始计时，随机 20~45 秒后看下一条。
  - **互斥**：与 edge/SAPI 长篇朗读可同时；与克隆总结音（speak_once）互斥——
    本进程说话时写 voice_quip_speaking.flag，speak_once 会等它播完再等 5 秒。
    总结音占用（voice_clone_busy.flag）时本进程让位。
  - LLM 失败的兜底：一句万能短评（"稳住"）——不读固定池。
  - 单实例锁 voice_quipper.lock；尊重全局音量/静音。

运行（uv 旁路，由大脑启动时拉起）：
  uv run --no-project --with onnxruntime --with sentencepiece --with torch --with torchaudio \
      python tts/quipper.py
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import wave
import winsound
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TTS_DIR = BASE_DIR / "tts"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
MOSS_DIR = BASE_DIR / "third_party" / "MOSS-TTS-Nano"
LOG_FILE = KNOWLEDGE_DIR / "tts_quipper.log"
LOCK_FILE = KNOWLEDGE_DIR / "voice_quipper.lock"
BUSY_FLAG = KNOWLEDGE_DIR / "voice_clone_busy.flag"          # 总结音占用（speak_once 写）
SPEAKING_FLAG = KNOWLEDGE_DIR / "voice_quip_speaking.flag"   # 本进程正在说话（speak_once 读）
TMP_WAV = TTS_DIR / "quip_tmp.wav"
REF_48K = TTS_DIR / "reference_voice_48k.wav"
CONFIG_PATH = BASE_DIR / "brain" / "config.json"

MIN_GAP, MAX_GAP = 20, 45        # 上一条播完后的随机间隔（秒）
LLM_TIMEOUT = 90
API = "http://127.0.0.1:8080"
FALLBACK_QUIPS = ["稳住", "继续", "看着打", "别慌"]   # 仅 LLM 失败时的兜底一句

sys.path.insert(0, str(TTS_DIR))
from speaker import get_voice_state  # noqa: E402


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
    return "openrouter/openrouter/free"


# ---------------------------------------------------------------------------
# MOSS-Nano 引擎（常驻）与播放
# ---------------------------------------------------------------------------

class NanoQuip:
    def __init__(self) -> None:
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
        log(f"引擎就绪（{time.time() - t0:.0f}s）")

    def play(self, text: str) -> None:
        st = get_voice_state()
        if st["muted"] or st["volume"] <= 0:
            return
        gain = st["volume"] / 100.0
        r = self.rt.synthesize_single_chunk(text=text, prompt_audio_codes=self.codes, streaming=False)
        import numpy as np
        wav = np.asarray(r["waveform"], dtype=np.float32) * gain
        sr = int(self.rt.codec_meta["codec_config"]["sample_rate"])
        ch = int(self.rt.codec_meta["codec_config"]["channels"])
        pcm = (wav.clip(-1, 1) * 32767).astype(np.int16)
        if pcm.ndim == 1:
            pcm = pcm[:, np.newaxis]
        with wave.open(str(TMP_WAV), "wb") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        winsound.PlaySound(str(TMP_WAV), winsound.SND_FILENAME)


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
                              errors="replace", timeout=LLM_TIMEOUT)
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
                              errors="replace", timeout=LLM_TIMEOUT)
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

def _pid_alive(pid: int) -> bool:
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


def main() -> int:
    if LOCK_FILE.exists():
        try:
            if _pid_alive(int(LOCK_FILE.read_text().strip() or "0")):
                return 0
        except (OSError, ValueError):
            pass
    try:
        LOCK_FILE.write_text(str(os.getpid()))
    except OSError:
        pass

    if not (MOSS_DIR / "models").exists():
        log("MOSS 模型未就绪，退出")
        return 0
    eng = NanoQuip()
    rng = random.Random()
    log(f"白绮碎碎念 v2 上线（LLM 现写：{_quip_model()}，播完后随机 {MIN_GAP}~{MAX_GAP}s 间隔）")

    last_play_end = 0.0
    next_gap = rng.uniform(MIN_GAP, MAX_GAP)
    last_sig = None

    while True:
        time.sleep(3)
        try:
            st = _get_state()
            if not st:
                continue
            screen = st.get("screen", "")
            run = st.get("run")
            if not run or screen in ("MAIN_MENU", "CHARACTER_SELECT", "GAME_OVER", "UNKNOWN", "UNLOCK"):
                continue
            if BUSY_FLAG.exists():            # 总结音在播 → 让位
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
                cand = _llm_generate(brief)
                if not cand:
                    break                          # 生成失败 → 直接走保底
                if _llm_audit(brief, cand):
                    text = cand
                    break
                log(f"审计被毙（第 {attempt + 1} 次），立即重生成：「{cand}」")
            if not text:
                text = rng.choice(FALLBACK_QUIPS)   # 保底句（预置安全文本，无需审计）
            last_sig = sig
            log(f"[{screen}] {text}（战况：{brief}）")

            SPEAKING_FLAG.write_text(str(os.getpid()), encoding="utf-8")
            try:
                eng.play(text)
            finally:
                SPEAKING_FLAG.unlink(missing_ok=True)
            last_play_end = time.time()
            next_gap = rng.uniform(MIN_GAP, MAX_GAP)
        except Exception as exc:
            log(f"循环异常（继续）：{exc}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        import traceback
        log(f"致命异常（静默退出）：{exc}\n{traceback.format_exc()[-800:]}")
        sys.exit(0)
