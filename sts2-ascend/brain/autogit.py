"""每局结束后的自动存档：把知识库与大脑代码提交并推送。

设计：
- 在 agent._finalize 末尾调用（此时本局统计/复盘/LLM 报告均已落盘）
- 任何失败（无变更、断网、钩子拒绝…）只记日志，绝不影响游玩主循环
- 提交范围：sts2-ascend/knowledge/（进化记忆）+ sts2-ascend/brain/（LLM 复盘可能改过 policy.py）
"""
from __future__ import annotations

import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent


def _git(args: list[str], timeout: int = 90) -> subprocess.CompletedProcess:
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
    """回滚 sts2-ascend 相关历史到指定提交（并清理该目录下未跟踪文件）。用于复盘失败回滚。"""
    r1 = _git(["reset", "--hard", to_commit], timeout=120)
    r2 = _git(["clean", "-fd", "--", "sts2-ascend"], timeout=60)
    ok = r1.returncode == 0 and r2.returncode == 0
    log(f"[git] 回滚到 {to_commit[:8]}：{'成功' if ok else '失败'}")
    return ok


def commit_progress(message: str, log=print) -> bool:
    """提交 sts2-ascend/ 全部变更（遵循 .gitignore）并推送。返回是否真的产生了新提交。"""
    try:
        _git(["add", "sts2-ascend"])
        r = _git(["commit", "-m", message])
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            if "nothing to commit" in out or "无文件要提交" in out:
                return False
            log(f"[git] 自动提交被跳过：{out.strip()[:200]}")
            return False
        p = _git(["push"], timeout=120)
        if p.returncode != 0:
            log(f"[git] 自动推送失败（不影响游玩，下次再试）：{(p.stderr or '').strip()[:200]}")
        else:
            log(f"[git] 已自动存档：{message}")
        return True
    except Exception as exc:
        log(f"[git] 自动存档异常（已忽略）：{exc}")
        return False
