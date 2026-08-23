"""白绮碎碎念（quipper）——克隆音色的低频随机战况点评。

设计：
  - 轮询游戏 mod API，仅在"有局面变化"时，按随机间隔（45~100s 抖动）插一句 10 字内短评
  - 克隆音色（MOSS-Nano），与长篇朗读器（edge/SAPI）可同时发声
  - 但绝不和白绮自己的"克隆总结音"（speak_once 结论段）同时读——靠 voice_clone_busy.flag 互斥
  - 模型"像人"靠两层：内置白绮人设短句池（分场景）+ 每周一次的 LLM 批量补货 quips_llm.txt
  - 尊重全局音量/静音（voice_volume.json）、单实例锁（voice_quipper.lock）
  - 任何异常只记日志，绝不影响任何其他组件

运行（uv 旁路，由大脑在启动时拉起）：
  uv run --no-project --with onnxruntime --with sentencepiece --with torch --with torchaudio \
      python tts/quipper.py
"""
from __future__ import annotations

import json
import os
import queue
import random
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
BUSY_FLAG = KNOWLEDGE_DIR / "voice_clone_busy.flag"      # 克隆总结音占用标志（speak_once 写）
LLM_QUIPS = TTS_DIR / "quips_llm.txt"
TMP_WAV = TTS_DIR / "quip_tmp.wav"
REF_48K = TTS_DIR / "reference_voice_48k.wav"

MIN_GAP, MAX_GAP = 45, 100        # 两句之间的随机间隔（秒）
HARD_MIN_GAP = 35                 # 硬下限
API = "http://127.0.0.1:8080"

sys.path.insert(0, str(TTS_DIR))
from speaker import get_voice_state  # noqa: E402


def log(msg: str) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[quip {time.strftime('%H:%M:%S')}] {msg}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 白绮短句池（10 字内为主；分场景）
# ---------------------------------------------------------------------------

QUIPS: dict[str, list[str]] = {
    "general": [
        "稳了稳了", "这波可以", "继续冲", "看着还行", "我在看哦", "不错嘛", "加油加油",
        "挺好挺好", "稳一手", "别急别急", "慢慢打", "可以的", "有点东西", "妙啊",
        "嗯哼", "就这样打", "我看好你", "稳住别慌",
    ],
    "advantage": [
        "这局有戏", "打得漂亮", "就要赢了", "好顺啊", "这伤害绝了", "碾压局", "舒服了",
        "这卡组成了", "芜湖起飞", "太猛了吧",
    ],
    "danger": [
        "血量告急", "要没了要没了", "苟住苟住", "别贪了", "快回血啊", "这波悬",
        "吓我一跳", "稳住别浪", "心凉了半截", "别送啊",
    ],
    "combat_start": ["开打开打", "上啊", "揍他", "新一场来了", "干就完了", "来吧来吧"],
    "boss": ["精英诶，小心", "Boss了！稳住", "这场硬", "大场面来了", "决战了啊"],
    "kill": ["杀了杀了", "好杀", "漂亮", "一个倒下", "再见啦", "拿下"],
    "map": ["往哪走呢", "选条路", "这条路看着肥", "走这边？", "前面有啥"],
    "shop": ["买买买", "金币够吗", "看看有啥货", "剁手时间", "老板大气"],
    "rest": ["歇会儿", "回口血", "烤火烤火", "休息一下", "喝口水"],
    "event": ["啥事呢", "看戏看戏", "这事件有意思", "哟，彩蛋"],
    "idle": ["无聊了", "还在打呀", "慢慢磨", "有点困", "我睡着了吗", "快点嘛"],
    "potion": ["喝药喝药", "干了这瓶", "好药水"],
}


def _load_quips() -> dict[str, list[str]]:
    pool = {k: list(v) for k, v in QUIPS.items()}
    try:
        if LLM_QUIPS.exists():
            extra = [ln.strip() for ln in LLM_QUIPS.read_text(encoding="utf-8").splitlines()
                     if ln.strip() and len(ln.strip()) <= 20]
            if extra:
                pool["general"] += extra
    except OSError:
        pass
    return pool


# ---------------------------------------------------------------------------
# 引擎（MOSS-Nano，常驻）与播放
# ---------------------------------------------------------------------------

class NanoQuip:
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
        log(f"引擎就绪（{time.time() - t0:.0f}s）")

    def say(self, text: str) -> None:
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
# 游戏状态
# ---------------------------------------------------------------------------

def _get_state() -> dict | None:
    try:
        with urllib.request.urlopen(f"{API}/state", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("data") if d.get("ok") else None
    except Exception:
        return None


def _pick_category(st: dict) -> str:
    screen = st.get("screen", "")
    combat = st.get("combat") or {}
    run = st.get("run") or {}
    if screen == "COMBAT" and combat:
        hp = (combat.get("player") or {}).get("current_hp", 99)
        maxhp = max(1, (combat.get("player") or {}).get("max_hp", 99))
        if hp / maxhp < 0.35:
            return "danger"
        enemies = combat.get("enemies") or []
        if any((e.get("is_alive") and (e.get("current_hp", 1) / max(1, e.get("max_hp", 1))) < 0.25) for e in enemies):
            return "kill"
        room = (run.get("room_type") or "")
        if "Boss" in room or "Elite" in room:
            return "boss"
        return "combat_start" if (st.get("turn") or 9) <= 2 else "general"
    if screen == "MAP":
        return "map"
    if screen == "SHOP":
        return "shop"
    if screen == "REST":
        return "rest"
    if screen == "EVENT":
        return "event"
    return "general"


def _sig(st: dict) -> tuple:
    run = st.get("run") or {}
    combat = st.get("combat") or {}
    return (st.get("screen"), run.get("floor"), st.get("turn"),
            (combat.get("player") or {}).get("current_hp"))


# ---------------------------------------------------------------------------
# LLM 批量补货（每周一次，后台线程，一次调用产 50 句）
# ---------------------------------------------------------------------------

def _maybe_refill_llm() -> None:
    try:
        if LLM_QUIPS.exists() and time.time() - LLM_QUIPS.stat().st_mtime < 7 * 86400:
            return
    except OSError:
        return

    def _job() -> None:
        import shutil
        binary = shutil.which("opencode")
        if not binary:
            return
        prompt = (
            f"请为杀戮尖塔2的自动游玩解说写 50 句超短吐槽/点评，角色是「白绮」（温柔俏皮的小教练）。"
            f"要求：每句 10 个汉字以内、口语化、像真人随口说的；涵盖顺风/逆风/击杀/逛街/商店/休息/无聊等场景；"
            f"每行一句，不要编号不要解释。把全部句子直接写入文件 {LLM_QUIPS.as_posix()}（UTF-8，覆盖写）。"
            "写完回复 OK 即可。"
        )
        try:
            subprocess.run([binary, "run", "--model", "kimi-for-coding/k3", "--dir", str(BASE_DIR.parent),
                            "--auto", prompt], capture_output=True, timeout=420)
            log("LLM 短句池补货完成")
        except Exception as exc:
            log(f"LLM 补货失败（用内置池）：{exc}")

    threading.Thread(target=_job, daemon=True).start()


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
    _maybe_refill_llm()
    eng = NanoQuip()
    pool = _load_quips()
    rng = random.Random()
    log("白绮碎碎念上线")

    last_quip = 0.0
    next_gap = rng.uniform(MIN_GAP, MAX_GAP)
    last_sig = None

    while True:
        time.sleep(5)
        try:
            st = _get_state()
            if not st:
                continue
            screen = st.get("screen", "")
            run = st.get("run")
            # 只在一局进行中插话
            if not run or screen in ("MAIN_MENU", "CHARACTER_SELECT", "GAME_OVER", "UNKNOWN", "UNLOCK"):
                continue
            # 克隆总结音占用时让位
            if BUSY_FLAG.exists():
                continue
            sig = _sig(st)
            now = time.time()
            if sig == last_sig:
                continue
            if now - last_quip < max(HARD_MIN_GAP, next_gap):
                continue
            last_sig = sig
            cat = _pick_category(st)
            text = rng.choice(pool.get(cat, pool["general"]) + pool["general"])
            last_quip = now
            next_gap = rng.uniform(MIN_GAP, MAX_GAP)
            log(f"[{cat}] {text}")
            eng.say(text)
        except Exception as exc:
            log(f"循环异常（继续）：{exc}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"致命异常（静默退出）：{exc}")
        sys.exit(0)
