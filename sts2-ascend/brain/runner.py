"""大脑监督进程 —— 负责拉起/重启/崩溃恢复。

- 大脑以退出码 42 表示"LLM 复盘改了代码，请重启我"
- 异常退出时**先重试**：每次间隔 60 秒，最多连续 5 次快速崩溃（存活 <90s 才算快速崩溃）
- **回滚是最后手段**：仅当连续 5 次快速崩溃、且存在复盘重启标记（pending_restart.json，
  说明可能是复盘改坏了代码）时，才按标记回滚到复盘前备份点，然后继续重试
- 任何非零退出都会尝试重启，保证无人值守韧性

用法: py brain/runner.py   （替代直接 py -m brain）
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
MARKER = KNOWLEDGE_DIR / "pending_restart.json"
RESTART_CODE = 42
MAX_FAST_CRASHES = 5
FAST_CRASH_SECONDS = 90
RETRY_INTERVAL_SECONDS = 60


def log(msg: str) -> None:
    line = f"[runner {time.strftime('%H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        with (KNOWLEDGE_DIR / "brain.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def rollback_from_marker() -> bool:
    """新代码启动失败：按 marker 里的复盘前备份点做 git 回滚。"""
    try:
        info = json.loads(MARKER.read_text(encoding="utf-8"))
        pre = info["pre_head"]
        r1 = subprocess.run(["git", "-C", str(REPO_DIR), "reset", "--hard", pre],
                            capture_output=True, text=True, timeout=120)
        subprocess.run(["git", "-C", str(REPO_DIR), "clean", "-fd", "--", "sts2-ascend"],
                       capture_output=True, text=True, timeout=60)
        MARKER.unlink(missing_ok=True)
        ok = r1.returncode == 0
        log(f"新代码启动失败，已回滚到复盘前备份 {pre[:8]}（{'成功' if ok else '部分失败'}）")
        return ok
    except Exception as exc:
        log(f"回滚失败：{exc}")
        return False


def main() -> int:
    fast_crashes = 0
    log("监督进程启动，拉起大脑…")
    while True:
        started = time.monotonic()
        proc = subprocess.run([sys.executable, "-u", "-m", "brain"], cwd=str(BASE_DIR))
        alive_s = time.monotonic() - started
        rc = proc.returncode

        if rc == RESTART_CODE:
            log("大脑请求重启（LLM 复盘更新了代码/策略）")
            fast_crashes = 0
            continue

        if rc == 0:
            log("大脑正常退出，监督进程结束")
            return 0

        # 异常退出：先耐心重试，回滚只是最后手段
        fast_crashes = 0 if alive_s > FAST_CRASH_SECONDS else fast_crashes + 1
        log(f"大脑异常退出（rc={rc}，存活 {alive_s:.0f}s，连续快速崩溃 {fast_crashes}/{MAX_FAST_CRASHES}）")

        if fast_crashes >= MAX_FAST_CRASHES and MARKER.exists():
            log(f"连续 {MAX_FAST_CRASHES} 次快速崩溃且存在复盘重启标记——疑似复盘改坏了代码，执行最后手段：回滚")
            rollback_from_marker()
            fast_crashes = 0
        time.sleep(RETRY_INTERVAL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
