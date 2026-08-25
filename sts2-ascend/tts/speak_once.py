"""Submit one text file to the existing IndexTTS-2.5 CUDA owner.

This diagnostic helper deliberately cannot instantiate a model.  Production
and manual one-shot speech therefore share quipper's single GPU allocation.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

TTS_DIR = Path(__file__).resolve().parent
BASE_DIR = TTS_DIR.parent
LOG_FILE = BASE_DIR / "knowledge" / "tts_speaker.log"

sys.path.insert(0, str(TTS_DIR))
from indextts_client import IndexTTSServiceError, speak, wait_ready  # noqa: E402


def log(message: str) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"[voice-once {time.strftime('%H:%M:%S')}] {message}\n")
    except OSError:
        pass


def main() -> int:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if not args:
        print("usage: python tts/speak_once.py <utf8-text-file>", file=sys.stderr)
        return 2
    text = Path(args[0]).read_text(encoding="utf-8").strip()
    if not text:
        return 0
    status = wait_ready(10.0)
    if status is None:
        log("IndexTTS GPU owner 未运行；拒绝加载第二份模型或回退 CPU")
        return 1
    try:
        result = speak(text, source="manual")
    except IndexTTSServiceError as exc:
        log(f"一次性 IndexTTS GPU 朗读失败：{exc}")
        return 1
    log(f"一次性 IndexTTS GPU 朗读完成：{result.get('synthesis_seconds', '?')}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
