"""大脑监督进程 —— 负责拉起/重启/崩溃回滚。

- 大脑以退出码 42 表示"LLM 复盘改了代码，请重启我"
- 大脑重启前会把 brain/*.py 快照到 knowledge/code_backups/pre_restart_<ts>/ 并写 pending_restart.json
- 若重启后进程很快异常退出且 marker 仍在（说明新代码起不来），runner 自动还原快照再重启
- 任何非零退出都会尝试重启（最多连续 5 次快速崩溃后放弃），保证无人值守韧性

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

        # 异常退出
        fast_crashes = fast_crashes + 1 if alive_s < FAST_CRASH_SECONDS else 0
        log(f"大脑异常退出（rc={rc}，存活 {alive_s:.0f}s）")
        if MARKER.exists():
            log("检测到重启标记：疑似 LLM 复盘改坏了代码，执行自动回滚")
            rollback_from_marker()
        if fast_crashes >= MAX_FAST_CRASHES:
            log(f"连续 {MAX_FAST_CRASHES} 次快速崩溃，放弃重启（游戏不受影响，需人工检查）")
            return 1
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
