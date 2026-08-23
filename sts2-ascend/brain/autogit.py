"""每局结束后的自动存档：把知识库与大脑代码提交并推送。

设计：
- 在 agent._finalize 末尾调用（此时本局统计/复盘/LLM 报告均已落盘）
- 任何失败（无变更、断网、钩子拒绝…）只记日志，绝不影响游玩主循环
- 提交范围：sts2-ascend/knowledge/（进化记忆）+ sts2-ascend/brain/（LLM 复盘可能改过 policy.py）
- 异步复盘并发安全：
  - 所有 git 调用走全局锁 _GIT_LOCK（游玩线程的存档 vs 复盘线程的提交/回滚不会撞 index.lock）
  - 复盘进行中（set_review_active(True)）时，每局存档只 add knowledge/，不碰 brain/——
    防止把复盘 agent 改了一半的代码卷进对局存档提交
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent

_GIT_LOCK = threading.Lock()
REVIEW_ACTIVE_FILE = BASE_DIR / "knowledge" / "review_active.flag"


def set_review_active(active: bool) -> None:
    """标记复盘会话进行中（由 llm_review 调用）。文件+pid 形式，跨进程可见。"""
    try:
        if active:
            REVIEW_ACTIVE_FILE.write_text(str(os.getpid()), encoding="utf-8")
        else:
            REVIEW_ACTIVE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def is_review_active() -> bool:
    """复盘是否进行中（含跨进程场景：手动 --now 复盘时游玩侧存档也会收窄范围）。

    标记文件里的 pid 已死则视为残留标记，自动清理。"""
    try:
        if not REVIEW_ACTIVE_FILE.exists():
            return False
        pid = int(REVIEW_ACTIVE_FILE.read_text().strip() or "0")
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            REVIEW_ACTIVE_FILE.unlink(missing_ok=True)
            return False
    except (OSError, ValueError):
        return False


def _git(args: list[str], timeout: int = 90) -> subprocess.CompletedProcess:
    with _GIT_LOCK:
        return subprocess.run(
            ["git", "-C", str(REPO_DIR)] + args,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )


def head() -> str:
    """当前 HEAD 的完整 commit hash。"""
    return _git(["rev-parse", "HEAD"]).stdout.strip()


def has_changes() -> bool:
    """sts2-ascend/ 下是否有未提交变更。"""
    return bool(_git(["status", "--porcelain", "--", "sts2-ascend"]).stdout.strip())


def reset_hard(to_commit: str, log=print) -> bool:
    """回滚 sts2-ascend 相关历史到指定提交（并清理该目录下未跟踪文件）。用于复盘失败回滚。

    注意：仅同步复盘时代码路径使用；异步复盘请用 restore_paths（不会抹掉对局存档）。"""
    r1 = _git(["reset", "--hard", to_commit], timeout=120)
    r2 = _git(["clean", "-fd", "--", "sts2-ascend"], timeout=60)
    ok = r1.returncode == 0 and r2.returncode == 0
    log(f"[git] 回滚到 {to_commit[:8]}：{'成功' if ok else '失败'}")
    return ok


def restore_paths(from_commit: str, paths: list[str], log=print) -> bool:
    """外科手术式回滚：只把指定路径恢复到 from_commit 的状态，不动其他文件/历史。

    异步复盘失败时使用——复盘期间产生的对局存档（knowledge/runs/ 等）不受影响。
    随后由调用方决定是否把恢复结果提交。
    """
    r1 = _git(["restore", "--source=" + from_commit, "--worktree", "--"] + paths, timeout=120)
    r2 = _git(["clean", "-fd", "--", "sts2-ascend/brain"], timeout=60)   # 清掉复盘新建但未跟踪的代码文件
    ok = r1.returncode == 0 and r2.returncode == 0
    log(f"[git] 路径回滚到 {from_commit[:8]}（{len(paths)} 条路径）：{'成功' if ok else '失败'}")
    return ok


def _push_with_retry(log=print, attempts: int = 3) -> bool:
    """推送并重试（网络抖动 curl 56 是常客）。间隔 5s/15s/30s。最终失败只记日志。"""
    delay = 5
    for i in range(attempts):
        p = _git(["push"], timeout=120)
        if p.returncode == 0:
            return True
        err = ((p.stderr or "") + (p.stdout or "")).strip()[:200]
        log(f"[git] 推送失败（第 {i + 1}/{attempts} 次，{delay}s 后重试）：{err}")
        time.sleep(delay)
        delay *= 3
    log("[git] 推送多次失败，本次放弃（下次提交时会带上未推送的提交）")
    return False


def commit_progress(message: str, log=print) -> bool:
    """提交 sts2-ascend/ 变更（遵循 .gitignore）并推送。返回是否真的产生了新提交。

    复盘进行中时只提交 knowledge/（进化记忆），跳过 brain/（防止卷入半成品代码）。"""
    try:
        scope = "sts2-ascend/knowledge" if is_review_active() else "sts2-ascend"
        _git(["add", scope])
        r = _git(["commit", "-m", message])
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            if "nothing to commit" in out or "无文件要提交" in out:
                return False
            log(f"[git] 自动提交被跳过：{out.strip()[:200]}")
            return False
        if _push_with_retry(log):
            log(f"[git] 已自动存档并推送：{message}" + ("（复盘进行中，仅 knowledge/）" if scope != "sts2-ascend" else ""))
        else:
            log(f"[git] 已自动存档（推送待重试）：{message}")
        return True
    except Exception as exc:
        log(f"[git] 自动存档异常（已忽略）：{exc}")
        return False
