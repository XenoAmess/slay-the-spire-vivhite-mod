"""对局存档与 LLM 复盘使用的受限 Git 事务。

自动提交使用独立 ``GIT_INDEX_FILE``，不会夹带调用前已经 staged 的用户文件；
add、建 commit、原子更新分支及 push 全程持有同一个跨进程锁。分支更新使用
compare-and-swap，外部并发提交只会令事务重试，不会被覆盖。

复盘回滚只接受固定 allowlist 内、属于一个已验证 commit 的反向 patch，并先用
``git apply --check`` 验证。这里刻意没有全仓 reset/clean。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Sequence

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent

DEFAULT_PROGRESS_PATHS = (
    "sts2-ascend/knowledge/runs",
    "sts2-ascend/knowledge/stats.json",
    "sts2-ascend/knowledge/progression.json",
    "sts2-ascend/knowledge/review_queue.json",
    "sts2-ascend/knowledge/policy.json",
    "sts2-ascend/knowledge/lessons.md",
    "sts2-ascend/knowledge/preferred_model_state.json",
)
# runner 只信这份进程内常量，不信 pending marker 自报的路径。
REVIEW_PATCH_ALLOWLIST = (
    "sts2-ascend/brain/__main__.py",
    "sts2-ascend/brain/agent.py",
    "sts2-ascend/brain/client.py",
    "sts2-ascend/brain/config.json",
    "sts2-ascend/brain/knowledge.py",
    "sts2-ascend/brain/native_knowledge.py",
    "sts2-ascend/brain/policy.py",
    "sts2-ascend/brain/reflect.py",
    "sts2-ascend/brain/selfcheck.py",
    "sts2-ascend/knowledge/meta_review.md",
    "sts2-ascend/knowledge/review_conclusion.txt",
)

_GIT_LOCK = threading.RLock()
_LOCK_STATE = threading.local()
REVIEW_ACTIVE_FILE = BASE_DIR / "knowledge" / "review_active.flag"
_HEX_COMMIT = re.compile(r"^[0-9a-fA-F]{40,64}$")


@dataclass(frozen=True)
class CommitResult:
    created: bool
    before_head: str = ""
    commit: str = ""
    pushed: bool = False
    reason: str = ""

    def __bool__(self) -> bool:
        return self.created


def set_review_active(active: bool) -> None:
    """标记复盘会话进行中（由 llm_review 调用）。文件+pid 形式，跨进程可见。"""
    try:
        # 与 commit 的范围判定共用仓库锁，避免“刚判为全 knowledge，复盘随即
        # 开始写报告”的 TOCTOU 窗口。
        with repository_lock():
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
        if _pid_alive(pid):
            return True
        else:
            REVIEW_ACTIVE_FILE.unlink(missing_ok=True)
            return False
    except (OSError, ValueError):
        return False


def _pid_alive(pid: int) -> bool:
    """无副作用探活；Windows 绝不能用 ``os.kill(pid, 0)``。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) \
                    and exit_code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _git_dir() -> Path:
    """不调用 Git 地解析普通仓库或 worktree 的 gitdir。"""
    dot_git = REPO_DIR / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        line = dot_git.read_text(encoding="utf-8", errors="replace").strip()
        if line.lower().startswith("gitdir:"):
            candidate = Path(line.split(":", 1)[1].strip())
            return candidate if candidate.is_absolute() else (REPO_DIR / candidate).resolve()
    raise RuntimeError(f"找不到 Git 元数据目录：{dot_git}")


def _lock_file_handle(handle, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    while True:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except (OSError, BlockingIOError):
            if time.monotonic() >= deadline:
                raise TimeoutError("等待自动 Git 跨进程锁超时")
            time.sleep(0.05)


def _unlock_file_handle(handle) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def repository_lock(timeout: float = 480.0) -> Iterator[None]:
    """同进程可重入、跨进程互斥的仓库事务锁。"""
    depth = int(getattr(_LOCK_STATE, "depth", 0))
    if depth:
        _LOCK_STATE.depth = depth + 1
        try:
            yield
        finally:
            _LOCK_STATE.depth -= 1
        return

    started = time.monotonic()
    if not _GIT_LOCK.acquire(timeout=max(0.0, float(timeout))):
        raise TimeoutError("等待自动 Git 进程内锁超时")
    try:
        lock_path = _git_dir() / "sts2-ascend-autogit.lock"
        handle = lock_path.open("a+b")
        try:
            remaining = max(0.0, float(timeout) - (time.monotonic() - started))
            _lock_file_handle(handle, remaining)
            _LOCK_STATE.depth = 1
            _LOCK_STATE.handle = handle
            yield
        finally:
            _LOCK_STATE.depth = 0
            _LOCK_STATE.handle = None
            _unlock_file_handle(handle)
            handle.close()
    finally:
        _GIT_LOCK.release()


def _run_git(
    args: Sequence[str], *, timeout: int = 90, env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_DIR), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env, input=input_text,
    )


def _run_git_bytes(
    args: Sequence[str], *, timeout: int = 90, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(REPO_DIR), *args],
        capture_output=True, timeout=timeout, env=env,
    )


def _git(args: list[str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
    """兼容旧调用点的受锁单命令入口。"""
    with repository_lock():
        return _run_git(args, timeout=timeout)


def _nul_paths(raw: str) -> list[str]:
    return [item.replace("\\", "/") for item in raw.split("\0") if item]


def _normalize_path(path: str | os.PathLike[str]) -> str:
    raw = os.fspath(path).replace("\\", "/").rstrip("/")
    pure = PurePosixPath(raw)
    if (not raw or pure.is_absolute() or ".." in pure.parts
            or any(char in raw for char in ("\0", "\n", "\r", "*", "?", "["))
            or raw.startswith(":")):
        raise ValueError(f"不安全的 Git 路径：{raw!r}")
    normalized = pure.as_posix().lstrip("./")
    if normalized != "sts2-ascend" and not normalized.startswith("sts2-ascend/"):
        raise ValueError(f"自动 Git 禁止触碰 sts2-ascend 外路径：{raw!r}")
    return normalized


def normalize_paths(paths: Sequence[str | os.PathLike[str]]) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(_normalize_path(path) for path in paths))
    if not result:
        raise ValueError("Git 路径列表不能为空")
    return result


def _path_in_specs(path: str, specs: Sequence[str]) -> bool:
    value = path.replace("\\", "/").rstrip("/")
    return any(value == spec or value.startswith(spec.rstrip("/") + "/") for spec in specs)


def validate_review_paths(
    paths: Sequence[str], allowlist: Sequence[str] = REVIEW_PATCH_ALLOWLIST,
) -> tuple[str, ...]:
    """Normalize and validate the review patch's exact file allowlist.

    Review specs are files, not directory roots.  Prefix semantics would accept a
    path such as ``brain/config.json/evil.py`` after replacing the allowed file with
    a directory.  Progress/archive scopes intentionally keep using
    :func:`_path_in_specs`; untrusted review patches require exact equality.
    """
    normalized = normalize_paths(paths)
    allowed = normalize_paths(allowlist)
    allowed_set = set(allowed)
    denied = [path for path in normalized if path not in allowed_set]
    if denied:
        raise ValueError("复盘 patch 含越界路径：" + ", ".join(denied))
    return normalized


def head() -> str:
    """当前 HEAD 的完整 commit hash。"""
    return _git(["rev-parse", "HEAD"]).stdout.strip()


def has_changes(paths: Sequence[str] | None = None) -> bool:
    """指定路径（默认整个 sts2-ascend）是否有未提交变更。"""
    specs = normalize_paths(("sts2-ascend",) if paths is None else paths)
    return bool(_git(["status", "--porcelain", "--", *specs]).stdout.strip())


def changed_paths_since(base_commit: str, roots: Sequence[str] | None = None) -> tuple[str, ...]:
    """返回相对 ``base_commit`` 的 tracked + untracked 工作树路径。"""
    specs = normalize_paths(("sts2-ascend",) if roots is None else roots)
    with repository_lock():
        tracked = _run_git(["diff", "--name-only", "-z", base_commit, "--", *specs])
        others = _run_git(["ls-files", "--others", "--exclude-standard", "-z", "--", *specs])
        if tracked.returncode != 0 or others.returncode != 0:
            raise RuntimeError(((tracked.stderr or "") + (others.stderr or "")).strip())
        return tuple(dict.fromkeys(_nul_paths(tracked.stdout) + _nul_paths(others.stdout)))


def repo_changed_paths_since(base_commit: str) -> tuple[str, ...]:
    """扫描整个仓库的 tracked + untracked 变更，仅供复盘越界审计。"""
    with repository_lock():
        tracked = _run_git(["diff", "--name-only", "-z", base_commit, "--"])
        others = _run_git(["ls-files", "--others", "--exclude-standard", "-z", "--"])
        if tracked.returncode != 0 or others.returncode != 0:
            raise RuntimeError(((tracked.stderr or "") + (others.stderr or "")).strip())
        return tuple(dict.fromkeys(_nul_paths(tracked.stdout) + _nul_paths(others.stdout)))


def restore_paths(from_commit: str, paths: list[str], log=print) -> bool:
    """拒绝从共享工作树的“当前总 diff”猜测模型 patch。

    模型和用户可能在复盘期间修改同一个 allowlist 文件；从当前 diff 生成反向 patch
    会把两者一起删除，无法安全判源。调用保留用于 API 兼容和路径审计，但在复盘尚未
    隔离到独立 worktree 前一律 fail closed，交由诊断/人工处理。
    """
    try:
        validate_review_paths(paths)
        if not _HEX_COMMIT.fullmatch(from_commit):
            raise ValueError("恢复基线 commit hash 非法")
        log("[git] 路径恢复被拒绝：共享工作树 diff 无法区分模型与并发用户改动；"
            "在线 stats/progression 和全部现场均已保留")
        return False
    except Exception as exc:
        log(f"[git] 路径恢复被拒绝，现场已保留供诊断：{exc}")
        return False


def _staged_paths_unlocked(timeout: float = 90) -> tuple[str, ...]:
    result = _run_git(
        ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACDMRTUXB", "--"],
        timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return tuple(_nul_paths(result.stdout))


def _index_entries_unlocked(paths: Sequence[str], timeout: float = 90) -> bytes:
    result = _run_git_bytes(
        ["ls-files", "--stage", "-z", "--", *paths], timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def _symbolic_head_unlocked(timeout: float = 90) -> str:
    result = _run_git(["symbolic-ref", "-q", "HEAD"], timeout=timeout)
    if result.returncode == 0:
        return result.stdout.strip()
    # rc=1 是正常 detached HEAD；其他失败也 fail closed 为不可用身份。
    if result.returncode == 1:
        return ""
    raise RuntimeError(result.stderr.strip() or "无法读取 HEAD symbolic ref")


def _push_with_retry_unlocked(log=print, attempts: int = 1, timeout_sec: int = 30) -> bool:
    for attempt in range(attempts):
        try:
            proc = _run_git(["push"], timeout=timeout_sec)
            if proc.returncode == 0:
                return True
            err = ((proc.stderr or "") + (proc.stdout or "")).strip()[:200]
        except subprocess.TimeoutExpired:
            # update-ref 已经成功时，push 超时不能把“本地 commit 已创建”误报成
            # 整个事务失败；按普通推送失败重试，最终由 CommitResult.pushed 表达。
            err = f"push timed out after {timeout_sec}s"
        if attempt + 1 < attempts:
            delay = 5 if attempt == 0 else 15
            log(f"[git] 推送失败（第 {attempt + 1}/{attempts} 次，{delay}s 后重试）：{err}")
            time.sleep(delay)
        else:
            log(f"[git] 推送失败（第 {attempt + 1}/{attempts} 次）：{err}")
    log("[git] 推送多次失败，本地提交保留；下次事务会再次推送")
    return False


def _push_with_retry(log=print, attempts: int = 1, timeout_sec: int = 30) -> bool:
    """兼容入口；push 也受同一仓库事务锁保护。"""
    with repository_lock():
        return _push_with_retry_unlocked(
            log=log, attempts=attempts, timeout_sec=timeout_sec)


def push_pending(log=print, attempts: int = 1) -> bool:
    """补推本地线性提交；没有积压时为成功空操作。"""
    try:
        with repository_lock():
            upstream = _run_git([
                "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
            if upstream.returncode == 0 and upstream.stdout.strip():
                ahead = _run_git([
                    "rev-list", "--count", f"{upstream.stdout.strip()}..HEAD"])
                if ahead.returncode == 0:
                    try:
                        if int(ahead.stdout.strip() or "0") <= 0:
                            return True
                    except ValueError:
                        pass
            pushed = _push_with_retry_unlocked(log=log, attempts=max(1, int(attempts)))
            if pushed:
                log("[git] 已补推积压的本地提交")
            return pushed
    except Exception as exc:
        log(f"[git] 积压 push 异常，保留本地提交供下次复盘结束重试：{exc}")
        return False


def commit_progress_result(
    message: str, log=print, paths: Sequence[str] | None = None, *, push: bool = True,
) -> CommitResult:
    """用私有 index 原子提交指定路径，并可选在同一事务中 push。"""
    try:
        with repository_lock():
            specs = normalize_paths(DEFAULT_PROGRESS_PATHS if paths is None else paths)
            # 可选的精确文件在旧安装中可能尚不存在；忽略既不存在也从未 tracked
            # 的 pathspec，但保留已删除的 tracked 路径以便提交 deletion。
            effective_specs = []
            for spec in specs:
                tracked = _run_git(["ls-files", "-z", "--", spec])
                if (REPO_DIR / Path(spec)).exists() or bool(tracked.stdout):
                    effective_specs.append(spec)
            if not effective_specs:
                return CommitResult(False, before_head=head(), reason="nothing to commit")
            specs = tuple(effective_specs)
            staged = _staged_paths_unlocked()
            overlap = [path for path in staged if _path_in_specs(path, specs)]
            if overlap:
                reason = "目标路径已有用户 staged 内容，拒绝自动提交：" + ", ".join(overlap[:8])
                log(f"[git] {reason}")
                return CommitResult(False, reason=reason)

            original_target_index = _index_entries_unlocked(specs)
            transaction_ref = _symbolic_head_unlocked()
            last_error = ""
            for _attempt in range(3):
                if _symbolic_head_unlocked() != transaction_ref:
                    return CommitResult(False, reason="事务期间 HEAD 分支身份发生变化")
                before_result = _run_git(["rev-parse", "HEAD"])
                if before_result.returncode != 0:
                    last_error = before_result.stderr.strip()
                    break
                before = before_result.stdout.strip()
                fd, index_name = tempfile.mkstemp(prefix="sts2-ascend-index-", suffix=".tmp")
                os.close(fd)
                Path(index_name).unlink(missing_ok=True)
                env = os.environ.copy()
                env["GIT_INDEX_FILE"] = index_name
                try:
                    read = _run_git(["read-tree", before], env=env)
                    add = _run_git(["add", "--all", "--", *specs], env=env)
                    if read.returncode != 0 or add.returncode != 0:
                        last_error = ((read.stderr or "") + (add.stderr or "")).strip()
                        break
                    quiet = _run_git(["diff", "--cached", "--quiet"], env=env)
                    if quiet.returncode == 0:
                        return CommitResult(False, before_head=before, reason="nothing to commit")
                    if quiet.returncode != 1:
                        last_error = (quiet.stderr or "git diff --cached 失败").strip()
                        break
                    tree = _run_git(["write-tree"], env=env)
                    if tree.returncode != 0:
                        last_error = tree.stderr.strip()
                        break
                    made = _run_git(
                        ["commit-tree", tree.stdout.strip(), "-p", before],
                        env=env, input_text=message.rstrip() + "\n",
                    )
                    if made.returncode != 0:
                        last_error = made.stderr.strip()
                        break
                    commit = made.stdout.strip()
                    if _symbolic_head_unlocked() != transaction_ref:
                        return CommitResult(False, before_head=before,
                                            reason="提交前 HEAD 分支身份发生变化")
                    update_target = transaction_ref or "HEAD"
                    update = _run_git([
                        "update-ref", "-m", message[:120], update_target, commit, before])
                    if update.returncode != 0:
                        # 不遵守本锁的外部 Git 更新了 HEAD；从新 HEAD 重建树后再试。
                        last_error = update.stderr.strip()
                        continue

                    try:
                        current_target_index = _index_entries_unlocked(specs)
                        if current_target_index == original_target_index:
                            sync = _run_git([
                                "restore", "--staged", f"--source={commit}", "--", *specs])
                            if sync.returncode != 0:
                                log("[git] 提交已建立，但真实 index 同步失败；用户 index 未被强制覆盖："
                                    + sync.stderr.strip()[:200])
                        else:
                            log("[git] 提交期间目标 index 被外部进程修改；已保留其内容")
                    except Exception as exc:
                        log(f"[git] 提交已建立，真实 index 后处理异常；用户 index 未被覆盖：{exc}")
                    try:
                        # 复盘在无 remote 的隔离 clone 中运行；真实仓的正常提交和
                        # push 不再参与复盘验收，也不能让直播存档滞留数小时。
                        pushed = _push_with_retry_unlocked(log=log) if push else False
                    except Exception as exc:
                        log(f"[git] 本地提交已建立，push 异常，保留供下次重试：{exc}")
                        pushed = False
                    return CommitResult(True, before_head=before, commit=commit, pushed=pushed)
                finally:
                    Path(index_name).unlink(missing_ok=True)

            reason = last_error or "HEAD 连续并发更新，compare-and-swap 三次均失败"
            log(f"[git] 自动提交被跳过：{reason[:300]}")
            return CommitResult(False, reason=reason)
    except Exception as exc:
        log(f"[git] 自动存档异常（已忽略）：{exc}")
        return CommitResult(False, reason=str(exc))


def commit_progress(message: str, log=print, paths: Sequence[str] | None = None) -> bool:
    """兼容旧 API：返回是否真的产生了新提交。"""
    result = commit_progress_result(message, log=log, paths=paths)
    if result.created:
        suffix = "并推送" if result.pushed else "（推送待重试）"
        log(f"[git] 已自动存档{suffix}：{message}")
    return result.created


def commit_patch_result(
    patch_bytes: bytes, message: str, paths: Sequence[str], *, reverse: bool = False,
    log=print, push: bool = True,
    prepare: Callable[[CommitResult], bool] | None = None,
    abort_prepare: Callable[[CommitResult], None] | None = None,
    finalize_prepare: Callable[[CommitResult], None] | None = None,
    lock_timeout: float = 480.0,
    transaction_timeout: float | None = None,
) -> CommitResult:
    """把精确 patch 同时应用到私有 index 与工作树，再以 CAS 建立 commit。

    私有 index 只包含 patch 本身；同文件中不相交的用户工作树 hunk 会留在工作树，
    不会进入 commit。``prepare`` 在工作树/分支变化前拿到确定 commit id，可用于
    原子发布重启 marker；CAS 失败会调用 ``abort_prepare`` 后无损重试。
    ``finalize_prepare`` 只在工作树 patch 与 update-ref 都成功后调用，可把
    provisional marker 两阶段确认为 committed；其失败不会倒退已成立的提交。
    """
    provisional: CommitResult | None = None
    prepared = False
    worktree_applied = False
    deadline = (time.monotonic() + max(0.1, float(transaction_timeout))
                if transaction_timeout is not None else None)

    def remaining(default: float) -> float:
        if deadline is None:
            return default
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("精确 patch 事务总预算已耗尽")
        return max(0.1, min(default, value))

    def tx_git(args, *, timeout: float = 90, **kwargs):
        return _run_git(args, timeout=remaining(timeout), **kwargs)
    try:
        validated = validate_review_paths(paths)
        if not patch_bytes:
            return CommitResult(False, reason="empty patch")
        fd, patch_name = tempfile.mkstemp(prefix="sts2-review-exact-", suffix=".patch")
        with os.fdopen(fd, "wb") as handle:
            handle.write(patch_bytes)
        try:
            with repository_lock(timeout=min(lock_timeout, remaining(lock_timeout))):
                staged = _staged_paths_unlocked(timeout=remaining(90))
                overlap = [path for path in staged if _path_in_specs(path, validated)]
                if overlap:
                    reason = "patch 目标已有用户 staged 内容：" + ", ".join(overlap[:8])
                    log(f"[git] {reason}")
                    return CommitResult(False, reason=reason)
                original_target_index = _index_entries_unlocked(
                    validated, timeout=remaining(90))
                transaction_ref = _symbolic_head_unlocked(timeout=remaining(90))
                direction = ["--reverse"] if reverse else []
                opposite = [] if reverse else ["--reverse"]
                last_error = ""

                for _attempt in range(3):
                    if _symbolic_head_unlocked(timeout=remaining(90)) != transaction_ref:
                        return CommitResult(False, reason="patch 事务期间 HEAD 分支身份发生变化")
                    before_result = tx_git(["rev-parse", "HEAD"])
                    if before_result.returncode != 0:
                        last_error = before_result.stderr.strip()
                        break
                    before = before_result.stdout.strip()
                    fd, index_name = tempfile.mkstemp(prefix="sts2-patch-index-", suffix=".tmp")
                    os.close(fd)
                    Path(index_name).unlink(missing_ok=True)
                    env = os.environ.copy()
                    env["GIT_INDEX_FILE"] = index_name
                    provisional = None
                    prepared = False
                    worktree_applied = False
                    try:
                        read = tx_git(["read-tree", before], env=env)
                        cached = tx_git(
                            ["apply", "--cached", "--unidiff-zero", *direction,
                             "--binary", patch_name],
                            timeout=120, env=env,
                        )
                        if read.returncode != 0 or cached.returncode != 0:
                            last_error = ((read.stderr or "") + (cached.stderr or "")).strip()
                            break
                        actual_result = tx_git(
                            ["diff", "--cached", "--name-only", "-z", "--no-renames", "--"],
                            env=env,
                        )
                        if actual_result.returncode != 0:
                            last_error = actual_result.stderr.strip()
                            break
                        try:
                            actual_paths = validate_review_paths(_nul_paths(actual_result.stdout))
                        except ValueError as exc:
                            last_error = str(exc)
                            break
                        if set(actual_paths) != set(validated):
                            last_error = "patch 实际路径与声明不一致"
                            break
                        tree = tx_git(["write-tree"], env=env)
                        if tree.returncode != 0:
                            last_error = tree.stderr.strip()
                            break
                        made = tx_git(
                            ["commit-tree", tree.stdout.strip(), "-p", before],
                            env=env, input_text=message.rstrip() + "\n",
                        )
                        if made.returncode != 0:
                            last_error = made.stderr.strip()
                            break
                        provisional = CommitResult(
                            True, before_head=before, commit=made.stdout.strip(), pushed=False)

                        check = tx_git(
                            ["apply", "--check", "--unidiff-zero", *direction,
                             "--binary", patch_name], timeout=120)
                        if check.returncode != 0:
                            last_error = "patch 与当前工作树冲突：" + check.stderr.strip()
                            break
                        if prepare is not None:
                            try:
                                prepared = bool(prepare(provisional))
                            except Exception as exc:
                                last_error = f"patch prepare 回调异常：{exc}"
                                prepared = False
                            if not prepared:
                                last_error = last_error or "patch prepare 回调拒绝"
                                if abort_prepare is not None:
                                    abort_prepare(provisional)
                                break

                        if _symbolic_head_unlocked(timeout=remaining(90)) != transaction_ref:
                            if prepared and abort_prepare is not None:
                                abort_prepare(provisional)
                            prepared = False
                            return CommitResult(
                                False, before_head=before,
                                reason="patch 应用前 HEAD 分支身份发生变化",
                            )

                        applied = tx_git(
                            ["apply", "--unidiff-zero", *direction, "--binary", patch_name],
                            timeout=120)
                        if applied.returncode != 0:
                            last_error = "patch 应用工作树失败：" + applied.stderr.strip()
                            if prepared and abort_prepare is not None:
                                abort_prepare(provisional)
                            prepared = False
                            break
                        worktree_applied = True

                        if _symbolic_head_unlocked(timeout=remaining(90)) != transaction_ref:
                            # 分支切换发生在工作树 apply 后；精确撤销仍需通过 check，
                            # 不可逆时保留 marker/现场而不更新任何 ref。
                            undo_check = tx_git([
                                "apply", "--check", "--unidiff-zero", *opposite,
                                "--binary", patch_name,
                            ], timeout=120)
                            if undo_check.returncode == 0:
                                undone = tx_git([
                                    "apply", "--unidiff-zero", *opposite, "--binary", patch_name,
                                ], timeout=120)
                                if undone.returncode == 0:
                                    worktree_applied = False
                                    if prepared and abort_prepare is not None:
                                        abort_prepare(provisional)
                                    prepared = False
                            return CommitResult(
                                False, before_head=before,
                                reason="patch 应用后 HEAD 分支身份发生变化",
                            )
                        update_target = transaction_ref or "HEAD"
                        update = tx_git([
                            "update-ref", "-m", message[:120], update_target,
                            provisional.commit, before,
                        ])
                        if update.returncode != 0:
                            last_error = update.stderr.strip()
                            undo_check = tx_git(
                                ["apply", "--check", "--unidiff-zero", *opposite,
                                 "--binary", patch_name], timeout=120)
                            if undo_check.returncode != 0:
                                # 无法证明无损时不做强制恢复，marker 留作诊断。
                                return CommitResult(False, before_head=before,
                                                    reason="CAS 失败且工作树 patch 无法无损撤销：" + last_error)
                            undone = tx_git(
                                ["apply", "--unidiff-zero", *opposite, "--binary", patch_name],
                                timeout=120)
                            if undone.returncode != 0:
                                return CommitResult(False, before_head=before,
                                                    reason="CAS 失败后的工作树恢复失败：" + undone.stderr.strip())
                            worktree_applied = False
                            if prepared and abort_prepare is not None:
                                abort_prepare(provisional)
                            prepared = False
                            continue

                        if prepared and finalize_prepare is not None:
                            try:
                                finalize_prepare(provisional)
                            except Exception as exc:
                                # Ref and worktree already agree on the new commit.
                                # Keep the marker in prepared state for diagnosis;
                                # never misreport the established commit as failed.
                                log(f"[git] patch 已提交，但 prepare 最终确认异常；"
                                    f"保留 marker 供重试：{exc}")

                        try:
                            current_target_index = _index_entries_unlocked(
                                validated, timeout=remaining(90))
                            if current_target_index == original_target_index:
                                sync = tx_git([
                                    "restore", "--staged", f"--source={provisional.commit}",
                                    "--", *validated,
                                ])
                                if sync.returncode != 0:
                                    log("[git] patch commit 已建立，但真实 index 同步失败；"
                                        "用户 index 未被强制覆盖：" + sync.stderr.strip()[:200])
                            else:
                                log("[git] patch 事务期间目标 index 被外部进程修改；已保留其内容")
                        except Exception as exc:
                            log(f"[git] patch commit 已建立，真实 index 后处理异常；"
                                f"用户 index 未被覆盖：{exc}")
                        try:
                            pushed = _push_with_retry_unlocked(log=log) if push else False
                        except Exception as exc:
                            log(f"[git] patch commit 已建立，push 异常，保留供下次重试：{exc}")
                            pushed = False
                        return CommitResult(
                            True, before_head=before, commit=provisional.commit, pushed=pushed)
                    finally:
                        Path(index_name).unlink(missing_ok=True)

                return CommitResult(False, reason=last_error or "patch CAS 三次失败")
        finally:
            Path(patch_name).unlink(missing_ok=True)
    except Exception as exc:
        # 只有尚未更新 ref 的异常会到这里。已应用但不能证明可逆时 fail closed，
        # 不尝试覆盖同文件并发用户编辑。
        if prepared and provisional is not None and abort_prepare is not None and not worktree_applied:
            try:
                abort_prepare(provisional)
            except Exception:
                pass
        log(f"[git] 精确 patch 事务失败，现场保留：{exc}")
        return CommitResult(False, reason=str(exc))


def _validated_commit_pair_unlocked(
    parent: str, commit: str, timeout: float = 90,
) -> tuple[str, ...]:
    if not _HEX_COMMIT.fullmatch(parent) or not _HEX_COMMIT.fullmatch(commit):
        raise ValueError("回滚 marker 的 commit hash 格式非法")
    row = _run_git(["rev-list", "--parents", "-n", "1", commit], timeout=timeout)
    if row.returncode != 0:
        raise ValueError("回滚 commit 不存在")
    parts = row.stdout.strip().split()
    if len(parts) != 2 or parts[0].lower() != commit.lower() or parts[1].lower() != parent.lower():
        raise ValueError("回滚只接受已验证的单父提交及其直接父节点")
    if _run_git(
            ["merge-base", "--is-ancestor", commit, "HEAD"],
            timeout=timeout).returncode != 0:
        raise ValueError("回滚 commit 不在当前 HEAD 历史中")
    changed = _run_git(
        ["diff", "--name-only", "-z", "--no-renames", parent, commit, "--"],
        timeout=timeout)
    if changed.returncode != 0:
        raise ValueError(changed.stderr.strip())
    return tuple(_nul_paths(changed.stdout))


def abort_unpublished_review_worktree(
    parent: str, commit: str, marker_paths: Sequence[str], *,
    log=print, lock_timeout: float = 5.0, operation_timeout: float = 10.0,
) -> bool:
    """Reconcile a ``prepared`` marker while HEAD still equals its parent.

    ``git apply`` is atomic across the review patch, so an interrupted transaction
    is either still at the parent worktree or contains the complete provisional
    patch. Prove one of those two states with forward/reverse checks; undo only the
    latter. Any overlap with an external edit fails closed and preserves evidence.
    """
    patch_name = ""
    deadline = time.monotonic() + max(0.1, float(operation_timeout))

    def remaining(cap: float | None = None) -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("prepared marker 恢复总预算已耗尽")
        return max(0.1, min(value, cap)) if cap is not None else max(0.1, value)

    try:
        with repository_lock(timeout=min(lock_timeout, remaining(lock_timeout))):
            if not _HEX_COMMIT.fullmatch(parent) or not _HEX_COMMIT.fullmatch(commit):
                raise ValueError("prepared marker commit 格式非法")
            claimed = validate_review_paths(marker_paths)
            row = _run_git(
                ["rev-list", "--parents", "-n", "1", commit],
                timeout=remaining())
            parts = row.stdout.strip().split() if row.returncode == 0 else []
            if (len(parts) != 2 or parts[0].lower() != commit.lower()
                    or parts[1].lower() != parent.lower()):
                raise ValueError("prepared marker 不是声明父节点的单父 commit")
            changed = _run_git(
                ["diff", "--name-only", "-z", "--no-renames", parent, commit, "--"],
                timeout=remaining())
            actual = validate_review_paths(_nul_paths(changed.stdout)) \
                if changed.returncode == 0 else ()
            if set(actual) != set(claimed):
                raise ValueError("prepared marker 路径与 provisional commit 不一致")
            patch = _run_git_bytes([
                "diff", "--binary", "--unified=0", parent, commit, "--", *actual,
            ], timeout=remaining())
            if patch.returncode != 0 or not patch.stdout:
                raise RuntimeError("无法读取 prepared commit 精确 patch")
            fd, patch_name = tempfile.mkstemp(
                prefix="sts2-prepared-reconcile-", suffix=".patch")
            with os.fdopen(fd, "wb") as handle:
                handle.write(patch.stdout)

            reverse_check = _run_git([
                "apply", "--check", "--reverse", "--unidiff-zero", "--binary",
                patch_name,
            ], timeout=remaining())
            if reverse_check.returncode == 0:
                undone = _run_git([
                    "apply", "--reverse", "--unidiff-zero", "--binary", patch_name,
                ], timeout=remaining())
                if undone.returncode != 0:
                    raise RuntimeError("prepared worktree patch 无法无损撤回："
                                       + undone.stderr.strip())
                log(f"[git] 已撤回未发布的 prepared 工作树 patch {commit[:8]}")
                return True

            forward_check = _run_git([
                "apply", "--check", "--unidiff-zero", "--binary", patch_name,
            ], timeout=remaining())
            if forward_check.returncode == 0:
                log(f"[git] prepared commit {commit[:8]} 尚未进入工作树，无需撤回")
                return True
            raise RuntimeError("prepared 工作树既非父版本也非完整 provisional 版本；保留现场")
    except Exception as exc:
        log(f"[git] prepared marker 恢复被拒绝：{exc}")
        return False
    finally:
        if patch_name:
            Path(patch_name).unlink(missing_ok=True)


def commit_is_ancestor(commit: str, *, timeout: float = 5.0) -> bool:
    """Bounded precise history check used only for rare prepared reconciliation."""
    if not _HEX_COMMIT.fullmatch(str(commit or "")):
        return False
    try:
        with repository_lock(timeout=timeout):
            return _run_git(
                ["merge-base", "--is-ancestor", commit, "HEAD"],
                timeout=timeout).returncode == 0
    except (OSError, TimeoutError, subprocess.SubprocessError):
        return False


def sync_prepared_index(
    parent: str, commit: str, marker_paths: Sequence[str], *,
    log=print, operation_timeout: float = 5.0,
) -> bool:
    """Repair only the review transaction's stale real index after update-ref.

    ``commit_patch_result`` updates the worktree/ref before synchronising the real
    index.  A crash in that tiny window leaves the whole review staged in reverse.
    Synchronise only when the target index is provably still the parent tree;
    otherwise preserve the user's index byte-for-byte and merely report it.
    """
    deadline = time.monotonic() + max(0.1, float(operation_timeout))

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("prepared index 同步总预算已耗尽")
        return max(0.1, value)

    try:
        with repository_lock(timeout=min(2.0, remaining())):
            claimed = validate_review_paths(marker_paths)
            row = _run_git(
                ["rev-list", "--parents", "-n", "1", commit], timeout=remaining())
            parts = row.stdout.strip().split() if row.returncode == 0 else []
            if (len(parts) != 2 or parts[0].lower() != commit.lower()
                    or parts[1].lower() != parent.lower()):
                raise ValueError("prepared index 对应关系非法")
            head = _run_git(["rev-parse", "HEAD"], timeout=remaining())
            current_head = head.stdout.strip().lower() if head.returncode == 0 else ""
            if not current_head:
                raise RuntimeError("prepared index 无法读取 HEAD")
            ancestor = _run_git(
                ["merge-base", "--is-ancestor", commit, current_head],
                timeout=remaining())
            if ancestor.returncode != 0:
                raise ValueError("prepared commit 不在当前 HEAD 历史中")
            already = _run_git(
                ["diff", "--cached", "--quiet", current_head, "--", *claimed],
                timeout=remaining())
            if already.returncode == 0:
                return True
            parent_index = _run_git(
                ["diff", "--cached", "--quiet", parent, "--", *claimed],
                timeout=remaining())
            if parent_index.returncode == 1:
                log("[git] prepared 发布后的真实 index 含用户内容；保留原 index，不自动覆盖")
                return False
            if parent_index.returncode != 0:
                raise RuntimeError(parent_index.stderr.strip() or "无法比较 prepared index")
            synced = _run_git([
                "restore", "--staged", f"--source={current_head}", "--", *claimed,
            ], timeout=remaining())
            if synced.returncode != 0:
                raise RuntimeError(synced.stderr.strip() or "prepared index 同步失败")
            log(f"[git] 已补齐 prepared commit {commit[:8]} 的真实 index 同步")
            return True
    except Exception as exc:
        log(f"[git] prepared index 保守保留：{exc}")
        return False


def rollback_review_commit(
    parent: str, commit: str, marker_paths: Sequence[str] | None = None, log=print,
    *, lock_timeout: float = 5.0, transaction_timeout: float = 30.0,
) -> bool:
    """以私有 index + 精确反向 patch 撤销一个复盘 commit。"""
    try:
        started = time.monotonic()
        with repository_lock(timeout=lock_timeout):
            remaining = max(0.1, transaction_timeout - (time.monotonic() - started))
            changed = _validated_commit_pair_unlocked(
                parent, commit, timeout=min(3.0, remaining))
            validated = validate_review_paths(changed)
            if marker_paths is not None:
                claimed = validate_review_paths(marker_paths)
                if set(claimed) != set(validated):
                    raise ValueError("marker 路径与 commit 实际路径不一致")
            remaining = max(0.1, transaction_timeout - (time.monotonic() - started))
            patch = _run_git_bytes([
                "diff", "--binary", "--unified=0", parent, commit, "--", *validated,
            ], timeout=min(3.0, remaining))
            if patch.returncode != 0 or not patch.stdout:
                raise RuntimeError(patch.stderr.decode("utf-8", "replace").strip() or "空回滚 patch")
            result = commit_patch_result(
                patch.stdout,
                f"revert(sts2-ascend): 安全撤销复盘 {commit[:8]}",
                validated, reverse=True, log=log, push=False,
                lock_timeout=max(0.1, min(lock_timeout, remaining)),
                transaction_timeout=max(
                    0.1, transaction_timeout - (time.monotonic() - started)),
            )
            if not result.created:
                raise RuntimeError("精确反向 patch 提交失败：" + result.reason)
            log(f"[git] 已用受控反向 patch 撤销复盘 {commit[:8]}，未触碰 allowlist 外路径")
            return True
    except Exception as exc:
        log(f"[git] 安全回滚被拒绝，现场已保留供诊断：{exc}")
        return False
