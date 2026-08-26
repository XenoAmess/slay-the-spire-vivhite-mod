"""大脑监督进程 —— 负责拉起/重启/崩溃恢复。

- 大脑以退出码 42 表示"LLM 复盘改了代码，请重启我"
- 异常退出时**先重试**：每次间隔 60 秒，最多连续 5 次快速崩溃（存活 <90s 才算快速崩溃）
- **回滚是最后手段**：仅当连续 5 次快速崩溃、且存在复盘重启标记（pending_restart.json，
  说明可能是复盘改坏了代码）时，才反向应用该复盘 commit 的 allowlist patch；
  patch 冲突或越界就保留现场并拒绝覆盖
- 任何非零退出都会尝试重启，保证无人值守韧性

统一入口由 scripts/Start-Agent.ps1 调用。手动 legacy 调试若上次 Ctrl+C
留下 stop.request，可显式使用: py brain/runner.py --clear-stop
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import autogit
from lifecycle import (SESSION_ID, clear_stop_request, pid_file, request_stop,
                       stop_requested, wait_for_stop)

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
MARKER = KNOWLEDGE_DIR / "pending_restart.json"
RESTART_CODE = 42
MAX_FAST_CRASHES = 5
MAX_REVIEW_RESTARTS = 5
FAST_CRASH_SECONDS = 90
RETRY_INTERVAL_SECONDS = 60
CTRL_C_GRACE_SECONDS = 20


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
    """新代码启动失败：只反向应用 marker 指向的受控复盘 commit。"""
    try:
        # 读取、反向提交与 compare-and-delete 共用同一仓库锁；健康确认或下一轮
        # prepare 不能在中间替换 marker，旧回滚也不会删除后来者。
        with autogit.repository_lock():
            info = json.loads(MARKER.read_text(encoding="utf-8"))
            parent = info["review_parent"]
            commit = info["review_commit"]
            paths = info.get("paths")
            ok = autogit.rollback_review_commit(parent, commit, marker_paths=paths, log=log)
            if ok:
                current = json.loads(MARKER.read_text(encoding="utf-8"))
                if current.get("review_commit") == commit:
                    MARKER.unlink(missing_ok=True)
                    log(f"新代码启动失败，已安全撤销复盘提交 {commit[:8]}")
                else:
                    log("安全回滚已完成，但 marker 已变化；保留新 marker，不执行旧删除")
            else:
                # marker 和现场都保留，便于人工判定冲突；绝不降级成强制覆盖。
                log(f"新代码启动失败，但复盘提交 {commit[:8]} 无法无损撤销；"
                    "已保留 marker/工作树诊断，未触碰其他并发改动")
            return ok
    except KeyError:
        log("回滚 marker 是旧格式或字段不全；拒绝执行历史上的全仓强制回滚，现场已保留")
        return False
    except Exception as exc:
        log(f"回滚失败：{exc}")
        return False


def _run_brain() -> tuple[int, float]:
    """Run one brain generation while remaining responsive to stack shutdown."""
    started = time.monotonic()
    proc = subprocess.Popen([sys.executable, "-u", "-m", "brain"], cwd=str(BASE_DIR))
    stop_logged = False
    try:
        while True:
            try:
                return proc.wait(timeout=0.5), time.monotonic() - started
            except subprocess.TimeoutExpired:
                if stop_requested() and not stop_logged:
                    log("收到全栈停止请求，等待大脑保存知识库并退出…")
                    stop_logged = True
    except KeyboardInterrupt:
        log("收到 Ctrl+C，转为全栈协作停止请求…")
        request_stop("runner-ctrl-c")
        deadline = time.monotonic() + CTRL_C_GRACE_SECONDS
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        if proc.poll() is None:
            log("大脑未在宽限期内退出，终止子进程")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        return 0, time.monotonic() - started


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    fast_crashes = 0
    review_crashes = 0
    review_restarts = 0
    log("监督进程启动，拉起大脑…")
    while True:
        if stop_requested():
            log("停止请求已生效，监督进程结束")
            return 0
        rc, alive_s = _run_brain()

        # 停机期间即使子进程被超时兜底终止，也绝不能重新拉起。
        if stop_requested():
            log("大脑已停止，监督进程结束")
            return 0

        if rc == RESTART_CODE:
            review_restarts = review_restarts + 1 if MARKER.exists() else 0
            log("大脑请求重启（LLM 复盘更新了代码/策略）"
                + (f"；复盘标记下连续重启 {review_restarts}/{MAX_REVIEW_RESTARTS}"
                   if review_restarts else ""))
            fast_crashes = 0
            review_crashes = 0
            if review_restarts >= MAX_REVIEW_RESTARTS and MARKER.exists():
                log(f"复盘标记下连续 {MAX_REVIEW_RESTARTS} 次退出码 {RESTART_CODE}——"
                    "疑似复盘引入重启循环，执行安全 patch 回滚")
                if not rollback_from_marker():
                    log("重启循环回滚失败；为避免无限热重启，runner 安全停止并保留现场")
                    return 1
                review_restarts = 0
            continue

        # 只有连续的 42 才构成重启循环；任何其他退出都会切断该序列。
        review_restarts = 0

        if rc == 0:
            log("大脑正常退出，监督进程结束")
            return 0

        # 异常退出：先耐心重试，回滚只是最后手段
        fast_crashes = 0 if alive_s > FAST_CRASH_SECONDS else fast_crashes + 1
        review_crashes = review_crashes + 1 if MARKER.exists() else 0
        log(f"大脑异常退出（rc={rc}，存活 {alive_s:.0f}s，连续快速崩溃 "
            f"{fast_crashes}/{MAX_FAST_CRASHES}，复盘后崩溃 {review_crashes}/{MAX_FAST_CRASHES}）")

        # 有复盘 marker 时，慢崩溃同样计数；否则每次活过 90 秒都会清零，坏复盘
        # 可以永远逃过最后手段。
        if review_crashes >= MAX_FAST_CRASHES and MARKER.exists():
            log(f"复盘后连续 {MAX_FAST_CRASHES} 次异常退出——疑似复盘改坏了代码，执行安全 patch 回滚")
            if not rollback_from_marker():
                log("复盘崩溃回滚失败；为避免永久重启/回滚循环，runner 安全停止并保留现场")
                return 1
            fast_crashes = 0
            review_crashes = 0
        if wait_for_stop(RETRY_INTERVAL_SECONDS):
            log("重试等待期间收到停止请求，监督进程结束")
            return 0


if __name__ == "__main__":
    if "--clear-stop" in sys.argv and SESSION_ID == "legacy":
        clear_stop_request()
    with pid_file("runner"):
        sys.exit(main())
