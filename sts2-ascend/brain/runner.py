"""大脑监督进程 —— 负责拉起/重启/崩溃恢复。

- 大脑以退出码 42 表示"LLM 复盘改了代码，请重启我"
- 异常退出时**先重试**：每次间隔 10 秒，最多连续 5 次快速崩溃（存活 <90s 才算快速崩溃）
- **回滚是最后手段**：仅当连续 5 次快速崩溃、且存在 committed 复盘重启标记（pending_restart.json，
  说明可能是复盘改坏了代码）时，才反向应用经单父 commit diff 与 marker 精确互证的 patch；
  patch 冲突或越界就保留现场并拒绝覆盖；成功撤销另存纯文件 tombstone，避免 marker
  被 Windows 短暂锁住时跨 runner 重启重复撤销
- 任何非零退出都会尝试重启，保证无人值守韧性

统一入口由 scripts/Start-Agent.ps1 调用。手动 legacy 调试若上次 Ctrl+C
留下 stop.request，可显式使用: py brain/runner.py --clear-stop
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import autogit
from lifecycle import (SESSION_ID, clear_stop_request, pid_file, request_stop,
                       pid_path, read_git_head, stop_requested, wait_for_stop)

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
MARKER = KNOWLEDGE_DIR / "pending_restart.json"
ROLLBACK_TOMBSTONES = KNOWLEDGE_DIR / "review_rollback_tombstones.json"
RESTART_CODE = 42
MAX_FAST_CRASHES = 5
MAX_REVIEW_RESTARTS = 5
FAST_CRASH_SECONDS = 90
RETRY_INTERVAL_SECONDS = 10
CTRL_C_GRACE_SECONDS = 20
STARTUP_TIMEOUT_CODE = 70
RECONCILE_BLOCKED_CODE = 71
STARTUP_IMPORT_SECONDS = 5
STARTUP_READY_SECONDS = 15
STARTUP_RETRY_SECONDS = 5
OUTAGE_BUDGET_SECONDS = 115
ROLLBACK_RESERVE_SECONDS = 45
MAX_REVIEW_STARTUP_FAILURES = 2
_SUPERSEDED_MARKER_KEY = "_superseded_marker"
_SUPERSEDED_MARKER_RAW_KEY = "_superseded_marker_raw"
_ROLLED_BACK_COMMITS: set[str] = set()
_ROLLBACK_TOMBSTONE_LIMIT = 100


def _time_left(deadline: float | None, cap: float) -> float:
    if deadline is None:
        return max(0.1, cap)
    return max(0.0, min(cap, deadline - time.monotonic()))


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


def _brain_pid_has_stage(pid: int, boot_id: str, boot_head: str,
                         boot_review: str, stage: str) -> bool:
    try:
        record = json.loads(pid_path("brain").read_text(encoding="utf-8"))
        current_stage = str(record.get("stage") or "starting")
        reached = ({"starting": 0, "imported": 1, "ready": 2}.get(current_stage, -1)
                   >= {"starting": 0, "imported": 1, "ready": 2}.get(stage, 99))
        return (int(record.get("pid", 0)) == int(pid)
                and record.get("session_id") == SESSION_ID
                and record.get("boot_id") == boot_id
                and record.get("boot_head") == boot_head
                and record.get("boot_review_commit") == boot_review
                and reached)
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _brain_pid_is_ready(pid: int, boot_id: str, boot_head: str,
                        boot_review: str) -> bool:
    return _brain_pid_has_stage(
        pid, boot_id, boot_head, boot_review, "ready")


def _terminate_startup_child(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is not None:
            return
        proc.terminate()
    except OSError:
        pass
    try:
        proc.wait(timeout=2)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        log(f"Brain 启动子进程 {getattr(proc, 'pid', '?')} 未及时退出；身份记录保留供 Stop 兜底")


def _replace_marker_text(contents: str) -> None:
    """Atomically replace the marker with bounded Windows sharing retries."""
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False,
                dir=MARKER.parent, prefix=".pending_restart.", suffix=".tmp") as temp:
            temp_name = temp.name
            temp.write(contents)
            temp.flush()
            os.fsync(temp.fileno())
        deadline = time.monotonic() + 2.0
        while True:
            try:
                os.replace(temp_name, MARKER)
                temp_name = None
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
    finally:
        if temp_name is not None:
            try:
                Path(temp_name).unlink()
            except OSError:
                pass


def _live_predecessor(info: dict) -> tuple[dict | None, str | None]:
    """Skip already reverted wrapper markers and expose the nearest live ancestor."""
    previous = info.get(_SUPERSEDED_MARKER_KEY)
    previous_raw = info.get(_SUPERSEDED_MARKER_RAW_KEY)
    for _depth in range(10):
        if not isinstance(previous, dict):
            break
        commit = str(previous.get("review_commit") or "").strip().lower()
        if not commit or not _review_was_rolled_back(commit):
            break
        previous_raw = previous.get(_SUPERSEDED_MARKER_RAW_KEY)
        previous = previous.get(_SUPERSEDED_MARKER_KEY)
    return (previous if isinstance(previous, dict) else None,
            previous_raw if isinstance(previous_raw, str) else None)


def _restore_superseded_marker(info: dict) -> bool:
    """After rollback/abort, reactivate the nearest non-reverted predecessor."""
    previous, previous_raw = _live_predecessor(info)
    if not isinstance(previous, dict) and not isinstance(previous_raw, str):
        MARKER.unlink(missing_ok=True)
        return False
    contents = (json.dumps(previous, ensure_ascii=False, indent=2) + "\n"
                if isinstance(previous, dict) else previous_raw)
    _replace_marker_text(contents)
    return True


def _active_review_commit() -> str:
    """Purely read the nearest live marker epoch; never mutate without the lock."""
    try:
        info = json.loads(MARKER.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    for _depth in range(10):
        # State-less markers are the backward-compatible committed format.
        if info.get("state") not in (None, "committed"):
            return ""
        value = str(info.get("review_commit") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40,64}", value):
            return ""
        if not _review_was_rolled_back(value):
            return value
        previous, previous_raw = _live_predecessor(info)
        if isinstance(previous, dict):
            info = previous
            continue
        if isinstance(previous_raw, str):
            try:
                info = json.loads(previous_raw)
                continue
            except json.JSONDecodeError:
                return ""
        return ""
    return ""


def _repair_tombstoned_marker_locked() -> None:
    """Retry a prior Windows marker restore only while repository lock is held."""
    try:
        info = json.loads(MARKER.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    commit = str(info.get("review_commit") or "").strip().lower()
    if (info.get("state") in (None, "committed")
            and re.fullmatch(r"[0-9a-f]{40,64}", commit)
            and _review_was_rolled_back(commit)):
        _restore_superseded_marker(info)


def _has_active_review_marker() -> bool:
    return bool(_active_review_commit())


def _load_rollback_tombstones() -> dict:
    try:
        data = json.loads(ROLLBACK_TOMBSTONES.read_text(encoding="utf-8"))
        commits = data.get("commits") if isinstance(data, dict) else None
        return commits if isinstance(commits, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _review_was_rolled_back(commit: str) -> bool:
    normalized = str(commit or "").strip().lower()
    if normalized in _ROLLED_BACK_COMMITS:
        return True
    if normalized and normalized in _load_rollback_tombstones():
        _ROLLED_BACK_COMMITS.add(normalized)
        return True
    return False


def _record_rollback_tombstone(commit: str) -> None:
    """Persist safe rollback identity without Git or the possibly locked marker."""
    normalized = str(commit or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40,64}", normalized):
        return
    _ROLLED_BACK_COMMITS.add(normalized)
    commits = _load_rollback_tombstones()
    commits[normalized] = {"rolled_back_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    commits = dict(list(commits.items())[-_ROLLBACK_TOMBSTONE_LIMIT:])
    payload = json.dumps({"version": 1, "commits": commits},
                         ensure_ascii=False, indent=2) + "\n"
    ROLLBACK_TOMBSTONES.parent.mkdir(parents=True, exist_ok=True)
    temp = ROLLBACK_TOMBSTONES.with_name(
        f".{ROLLBACK_TOMBSTONES.name}.{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + 2.0
        while True:
            try:
                os.replace(temp, ROLLBACK_TOMBSTONES)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
    finally:
        temp.unlink(missing_ok=True)


def _verified_review_commit_diff_paths(
    info: dict, deadline: float | None = None,
) -> tuple[str, ...]:
    """Read exact paths from a verified single-parent commit for forensics.

    Callers hold the repository transaction lock. The provisional commit need
    not yet be an ancestor of HEAD, so this proof deliberately checks its object,
    direct parent and exact diff without imposing publication state.
    """
    parent = str(info.get("review_parent") or "").strip().lower()
    commit = str(info.get("review_commit") or "").strip().lower()
    if (not re.fullmatch(r"[0-9a-f]{40,64}", parent)
            or not re.fullmatch(r"[0-9a-f]{40,64}", commit)):
        raise ValueError("marker 缺少合法 review_parent/review_commit")
    row = autogit._run_git(
        ["rev-list", "--parents", "-n", "1", commit],
        timeout=_time_left(deadline, 5.0))
    parts = row.stdout.strip().split() if row.returncode == 0 else []
    if (len(parts) != 2 or parts[0].lower() != commit
            or parts[1].lower() != parent):
        raise ValueError("marker commit 不是声明 parent 的单父提交")
    changed = autogit._run_git([
        "diff", "--name-only", "-z", "--no-renames", parent, commit, "--",
    ], timeout=_time_left(deadline, 5.0))
    if changed.returncode != 0:
        raise ValueError(changed.stderr.strip() or "无法读取 marker commit 精确 diff")
    raw_paths = tuple(
        path.replace("\\", "/") for path in changed.stdout.split("\0") if path)
    if not raw_paths:
        raise ValueError("marker commit 没有可验证的复盘路径")
    return raw_paths


def _validated_review_commit_paths(
    info: dict, deadline: float | None = None,
) -> tuple[str, ...]:
    """Derive the exact deny-only path set from a verified commit diff."""
    return autogit.validate_review_paths(
        _verified_review_commit_diff_paths(info, deadline))


def _trusted_marker_paths(
    info: dict, deadline: float | None = None,
) -> tuple[str, ...]:
    """Match marker claims to its commit diff, upgrading only truly old markers.

    A marker with no ``paths`` key predates exact-path publication and may use the
    verified commit diff. Once the key exists, empty, malformed or mismatched
    claims are corruption and fail closed; they never fall back to a fixed list.
    """
    actual = _validated_review_commit_paths(info, deadline)
    if "paths" not in info:
        if info.get("state") is None:
            return actual
        raise ValueError("两阶段 marker 缺少 paths；仅无 state 的旧格式可从 commit 补全")
    claimed_raw = info.get("paths")
    if not isinstance(claimed_raw, list) or not claimed_raw:
        raise ValueError("marker paths 已存在但为空或格式损坏")
    claimed = autogit.validate_review_paths(claimed_raw)
    if set(claimed) != set(actual):
        raise ValueError("marker paths 与 review_commit 实际 diff 不一致")
    return actual


def _reconcile_prepared_marker(deadline: float | None = None) -> bool:
    """Finish or abort an interrupted two-phase review before importing Brain."""
    try:
        info = json.loads(MARKER.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True
    except (OSError, json.JSONDecodeError) as exc:
        log(f"读取重启 marker 失败；拒绝在未知版本上启动 Brain：{exc}")
        return False
    state = info.get("state")
    if state in (None, "committed"):
        return True
    if state != "prepared":
        log(f"重启 marker state={state!r} 非法；拒绝在未知事务上启动 Brain")
        return False
    parent = str(info.get("review_parent") or "").strip().lower()
    commit = str(info.get("review_commit") or "").strip().lower()
    if (not re.fullmatch(r"[0-9a-f]{40,64}", parent)
            or not re.fullmatch(r"[0-9a-f]{40,64}", commit)):
        log("prepared marker 缺少合法 parent/commit；保留现场并拒绝混载")
        return False
    try:
        paths = _trusted_marker_paths(info, deadline)
    except (TypeError, ValueError, subprocess.SubprocessError) as exc:
        log(f"prepared marker 路径无法与 commit 精确互证；保留现场：{exc}")
        return False
    head = read_git_head(autogit.REPO_DIR)
    if head == commit or (head not in (parent, "")
                          and autogit.commit_is_ancestor(
                              commit, timeout=_time_left(deadline, 5.0))):
        # update-ref/worktree already published; only phase-two marker replace was
        # interrupted. Ownership is rechecked under the shared repository lock.
        try:
            current = json.loads(MARKER.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log(f"prepared marker 发布后重读失败：{exc}")
            return False
        if (current.get("state") != "prepared"
                or str(current.get("review_commit") or "").lower() != commit):
            return False
        try:
            current_paths = _trusted_marker_paths(current, deadline)
        except (TypeError, ValueError, subprocess.SubprocessError) as exc:
            log(f"prepared marker 发布后路径互证失败；保留现场：{exc}")
            return False
        autogit.sync_prepared_index(
            parent, commit, current_paths, log=log,
            operation_timeout=_time_left(deadline, 5.0))
        current["paths"] = list(current_paths)
        current["state"] = "committed"
        current["committed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        current["reconciled_at_startup"] = True
        try:
            _replace_marker_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n")
        except OSError as exc:
            log(f"prepared marker 二阶段确认失败，保留现场重试：{exc}")
            return False
        log(f"已把 HEAD 中断留存的 prepared marker {commit[:8]} 确认为 committed")
        return True
    if head != parent:
        log(f"prepared marker {commit[:8]} 的 HEAD 既非 parent 也非 commit；"
            "保留现场并拒绝混载")
        return False
    if not autogit.abort_unpublished_review_worktree(
            parent, commit, paths, log=log,
            lock_timeout=_time_left(deadline, 3.0),
            operation_timeout=_time_left(deadline, 8.0)):
        return False
    # HEAD never published the provisional commit; restoring/deleting the wrapper
    # completes the abort. Tombstoned predecessors are skipped automatically.
    try:
        _restore_superseded_marker(info)
    except OSError as exc:
        log(f"prepared marker 前任恢复失败，保留现场重试：{exc}")
        return False
    log(f"已恢复未发布 prepared marker {commit[:8]} 的前任状态")
    return True


def _save_prepared_recovery_package(
    info: dict, paths: tuple[str, ...], reason: str,
) -> Path | None:
    """Preserve every affected file before live recovery restores a known tree."""
    root = KNOWLEDGE_DIR / "code_backups" / "review_salvage"
    parent = str(info.get("review_parent") or "").strip().lower()
    name = (f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}-"
            f"prepared-{parent[:8] or 'nohead'}")
    final = root / name
    temp = root / f".{name}.tmp-{os.getpid()}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        temp.mkdir()
        files_root = temp / "files"
        files_root.mkdir()
        states: list[dict] = []
        for relative in paths:
            pure = Path(relative)
            normalized_parts = Path(relative.replace("\\", "/")).parts
            if (pure.is_absolute() or ".." in normalized_parts
                    or re.match(r"^[A-Za-z]:", relative)):
                states.append({"path": relative, "kind": "unsafe-path-not-copied"})
                continue
            source = autogit.REPO_DIR / Path(relative)
            target = files_root / Path(relative)
            state = {"path": relative, "exists": source.exists(),
                     "is_symlink": source.is_symlink()}
            if source.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(os.readlink(source), encoding="utf-8")
                state["kind"] = "symlink-target"
            elif source.is_dir():
                shutil.copytree(source, target, symlinks=True,
                                ignore_dangling_symlinks=True)
                state["kind"] = "directory"
            elif source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                state.update({"kind": "file", "size": source.stat().st_size})
            else:
                state["kind"] = "missing"
            states.append(state)

        current_patch = autogit._run_git_bytes([
            "diff", "--binary", parent, "--", *paths,
        ], timeout=5) if (paths and re.fullmatch(
            r"[0-9a-f]{40,64}", parent)) else None
        provisional = str(info.get("review_commit") or "").strip().lower()
        provisional_patch = autogit._run_git_bytes([
            "diff", "--binary", parent, provisional, "--", *paths,
        ], timeout=5) if (paths and re.fullmatch(r"[0-9a-f]{40,64}", parent)
                          and re.fullmatch(r"[0-9a-f]{40,64}", provisional)) else None
        (temp / "wip.patch").write_bytes(
            current_patch.stdout if current_patch is not None
            and current_patch.returncode == 0 else b"")
        (temp / "provisional.patch").write_bytes(
            provisional_patch.stdout if provisional_patch is not None
            and provisional_patch.returncode == 0 else b"")
        (temp / "file_states.json").write_text(
            json.dumps(states, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        (temp / "pending_restart.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        (temp / "report.md").write_text(reason + "\n", encoding="utf-8")
        manifest = {
            "schema": 1,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "failure_kind": "prepared_recovery",
            "reason": reason,
            "pre_head": parent,
            "current_head": read_git_head(autogit.REPO_DIR),
            "batch_runs": [],
            "model": "runner emergency recovery",
            "source": "prepared marker",
            "stopped": False,
            "all_paths": list(paths),
            "allowed_paths": list(paths),
            "auto_apply": False,
            "inspection_hint": "files/ 是已证明 commit 路径的保存现场；是否恢复工作树以调用方结果为准。",
        }
        (temp / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        os.replace(temp, final)
        return final
    except Exception as exc:
        log(f"prepared 现场完整保存失败；不覆盖工作树：{exc}")
        return None


def _recover_blocked_prepared_marker(
    reason: str, deadline: float | None = None,
) -> bool:
    """Quarantine a blocked prepared transaction, then restore a known tree.

    This is the live-safety fallback after exact forward/reverse proof failed.
    Nothing is discarded: every target file, both patches and the marker are
    atomically published under review_salvage before the worktree is restored.
    """
    try:
        lock_timeout = _time_left(deadline, 3.0)
        if lock_timeout <= 0:
            return False
        with autogit.repository_lock(timeout=lock_timeout):
            info = json.loads(MARKER.read_text(encoding="utf-8"))
            if info.get("state") != "prepared":
                return _reconcile_prepared_marker(deadline)
            try:
                paths = _trusted_marker_paths(info, deadline)
            except (TypeError, ValueError, subprocess.SubprocessError) as exc:
                # A mismatched claim is evidence of marker corruption. Derive
                # commit paths only for read-only forensics; never use them to
                # perform a destructive restore in this ambiguous transaction.
                try:
                    forensic_paths = _verified_review_commit_diff_paths(info, deadline)
                except Exception:
                    forensic_paths = ()
                detail = f"{reason}；marker/commit 路径互证失败：{exc}"
                package = _save_prepared_recovery_package(
                    info, forensic_paths, detail)
                if package is not None:
                    log(f"prepared 损坏现场已保存至 {package}；拒绝猜测恢复范围")
                return False
            package = _save_prepared_recovery_package(info, paths, reason)
            if package is None:
                return False
            head = read_git_head(autogit.REPO_DIR)
            if not re.fullmatch(r"[0-9a-f]{40,64}", head):
                log(f"prepared 现场已保存至 {package}，但 HEAD 不可读；保留工作树")
                return False
            restored = autogit._run_git([
                "restore", "--worktree", f"--source={head}", "--", *paths,
            ], timeout=_time_left(deadline, 8.0))
            if restored.returncode != 0:
                log(f"prepared 现场已保存至 {package}，但已知树恢复失败："
                    f"{restored.stderr.strip()}")
                return False
            commit = str(info.get("review_commit") or "").strip().lower()
            if re.fullmatch(r"[0-9a-f]{40,64}", commit):
                try:
                    _record_rollback_tombstone(commit)
                except OSError as exc:
                    log(f"prepared 恢复 tombstone 暂时写入失败；现场包仍保留：{exc}")
            try:
                _restore_superseded_marker(info)
            except OSError as exc:
                log(f"prepared 文件已恢复且现场已保存，但 marker 暂时锁定：{exc}")
            log(f"prepared 混合现场已完整保存至 {package}；工作树恢复为 {head[:8]}，立即重启 Brain")
            return True
    except Exception as exc:
        log(f"prepared 紧急恢复失败，现场保留：{exc}")
        return False


def rollback_from_marker(deadline: float | None = None) -> bool:
    """新代码启动失败：只反向应用 marker 指向的受控复盘 commit。"""
    try:
        # 读取、反向提交与 compare-and-delete 共用同一仓库锁；健康确认或下一轮
        # prepare 不能在中间替换 marker，旧回滚也不会删除后来者。
        lock_timeout = _time_left(deadline, 5.0)
        if lock_timeout <= 0:
            log("回滚总预算已耗尽；保留 marker/现场")
            return False
        with autogit.repository_lock(timeout=lock_timeout):
            info = json.loads(MARKER.read_text(encoding="utf-8"))
            parent = info["review_parent"]
            commit = info["review_commit"]
            if info.get("state") not in (None, "committed"):
                log("回滚 marker 尚处于 prepared，未证明已加载；拒绝据此回滚")
                return False
            if _review_was_rolled_back(str(commit)):
                log(f"复盘提交 {str(commit)[:8]} 已有安全撤销记录；拒绝重复回滚")
                return False
            paths = _trusted_marker_paths(info, deadline)
            transaction_timeout = _time_left(deadline, 30.0)
            if transaction_timeout <= 0:
                log("回滚事务预算已耗尽；保留 marker/现场")
                return False
            ok = autogit.rollback_review_commit(
                parent, commit, marker_paths=paths, log=log,
                lock_timeout=min(lock_timeout, transaction_timeout),
                transaction_timeout=transaction_timeout)
            if ok:
                try:
                    _record_rollback_tombstone(str(commit))
                except OSError as exc:
                    # In-memory identity still protects this runner generation.
                    log(f"复盘提交已撤销，但持久 tombstone 写入失败；本代仍禁止重复回滚：{exc}")
                current = json.loads(MARKER.read_text(encoding="utf-8"))
                if current.get("review_commit") == commit:
                    try:
                        restored = _restore_superseded_marker(current)
                        suffix = "；旧复盘 marker 已恢复" if restored else ""
                        log(f"新代码启动失败，已安全撤销复盘提交 {commit[:8]}{suffix}")
                    except OSError as exc:
                        # Code rollback is the safety-critical outcome. A transient
                        # Windows marker replacement failure must not stop runner
                        # and extend the live outage.
                        log(f"新代码提交 {commit[:8]} 已安全撤销；marker 恢复暂时失败，"
                            f"继续拉起 Brain 并保留现场：{exc}")
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


def _run_brain(deadline: float | None = None) -> tuple[int, float]:
    """Run one brain generation while remaining responsive to stack shutdown."""
    started = time.monotonic()
    deadline = deadline or (started + OUTAGE_BUDGET_SECONDS)
    child_env = os.environ.copy()
    proc: subprocess.Popen | None = None
    ready_deadline = min(deadline, time.monotonic() + STARTUP_READY_SECONDS)
    # Keep the repository transaction only until every module and config byte is
    # resident. Agent/Knowledge construction may itself acquire this same lock.
    try:
        lock_timeout = _time_left(deadline, 3.0)
        if lock_timeout <= 0:
            return STARTUP_TIMEOUT_CODE, time.monotonic() - started
        with autogit.repository_lock(timeout=lock_timeout):
            _repair_tombstoned_marker_locked()
            if not _reconcile_prepared_marker(deadline):
                return RECONCILE_BLOCKED_CODE, time.monotonic() - started
            boot_head = read_git_head(autogit.REPO_DIR)
            loaded_review = _active_review_commit()
            if boot_head:
                child_env["STS2_ASCEND_BOOT_HEAD"] = boot_head
            else:
                child_env.pop("STS2_ASCEND_BOOT_HEAD", None)
                log("无法冻结 Brain 启动提交号；本代健康 marker 将保留")
            child_env["STS2_ASCEND_BOOT_REVIEW_COMMIT"] = loaded_review or ""
            boot_id = os.urandom(12).hex()
            child_env["STS2_ASCEND_BOOT_ID"] = boot_id
            proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "brain"], cwd=str(BASE_DIR),
                env=child_env)
            import_deadline = min(
                ready_deadline, time.monotonic() + STARTUP_IMPORT_SECONDS)
            while time.monotonic() < import_deadline:
                rc = proc.poll()
                if rc is not None:
                    log(f"Brain 在 imported 握手前退出（rc={rc}）；按启动失败重试")
                    return STARTUP_TIMEOUT_CODE, time.monotonic() - started
                if _brain_pid_has_stage(
                        proc.pid, boot_id, boot_head or "", loaded_review or "",
                        "imported"):
                    break
                if stop_requested():
                    _terminate_startup_child(proc)
                    return 0, time.monotonic() - started
                time.sleep(0.05)
            else:
                log(f"Brain 未在 {STARTUP_IMPORT_SECONDS}s 内完成模块/config 导入；终止本代并重试")
                _terminate_startup_child(proc)
                return STARTUP_TIMEOUT_CODE, time.monotonic() - started
    except TimeoutError:
        log("冻结 Brain 启动版本等待仓库锁超时；不冒险混载代码，按全局断流预算重试")
        return STARTUP_TIMEOUT_CODE, time.monotonic() - started
    assert proc is not None
    # Repository lock is now released.  Agent construction/migrations can safely
    # take it; ready still has the same bounded startup deadline.
    while time.monotonic() < ready_deadline:
        rc = proc.poll()
        if rc is not None:
            log(f"Brain 在 ready 握手前退出（rc={rc}）；按启动失败重试")
            return STARTUP_TIMEOUT_CODE, time.monotonic() - started
        if _brain_pid_is_ready(
                proc.pid, boot_id, boot_head or "", loaded_review or ""):
            break
        if stop_requested():
            _terminate_startup_child(proc)
            return 0, time.monotonic() - started
        time.sleep(0.05)
    else:
        log(f"Brain 未在 {STARTUP_READY_SECONDS}s 内完成 Agent 初始化；终止本代并重试")
        _terminate_startup_child(proc)
        return STARTUP_TIMEOUT_CODE, time.monotonic() - started
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
    review_startup_failures = 0
    prepared_startup_failures = 0
    outage_deadline: float | None = None
    log("监督进程启动，拉起大脑…")
    while True:
        if stop_requested():
            log("停止请求已生效，监督进程结束")
            return 0
        if outage_deadline is None:
            outage_deadline = time.monotonic() + OUTAGE_BUDGET_SECONDS
        rc, alive_s = _run_brain(outage_deadline)
        startup_failure = rc in (STARTUP_TIMEOUT_CODE, RECONCILE_BLOCKED_CODE)
        if not startup_failure:
            # Reaching ready ends this outage epoch.  A later child exit starts a
            # fresh 115-second budget rather than inheriting hours of healthy play.
            outage_deadline = None

        # 停机期间即使子进程被超时兜底终止，也绝不能重新拉起。
        if stop_requested():
            log("大脑已停止，监督进程结束")
            return 0

        if rc == RESTART_CODE:
            active_review = _has_active_review_marker()
            review_restarts = review_restarts + 1 if active_review else 0
            log("大脑请求重启（LLM 复盘更新了代码/策略）"
                + (f"；复盘标记下连续重启 {review_restarts}/{MAX_REVIEW_RESTARTS}"
                   if review_restarts else ""))
            fast_crashes = 0
            review_crashes = 0
            if review_restarts >= MAX_REVIEW_RESTARTS and active_review:
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

        if rc == RECONCILE_BLOCKED_CODE:
            prepared_startup_failures += 1
            log(f"prepared 启动事务无法精确收口 {prepared_startup_failures}/3；"
                "先完整保存全部目标文件，再恢复当前已知提交")
            if _recover_blocked_prepared_marker(
                    "Runner 启动前无法证明 prepared 工作树的精确状态",
                    outage_deadline):
                prepared_startup_failures = 0
                continue
            remaining = _time_left(outage_deadline, OUTAGE_BUDGET_SECONDS)
            if prepared_startup_failures >= 3 or remaining <= 0:
                log("prepared 现场连续三次无法完整保存/恢复；在两分钟内停止并保留所有证据")
                return 1
            if wait_for_stop(min(STARTUP_RETRY_SECONDS, remaining)):
                return 0
            continue
        prepared_startup_failures = 0

        active_review = _has_active_review_marker()
        if rc == STARTUP_TIMEOUT_CODE:
            review_startup_failures += 1
            remaining = _time_left(outage_deadline, OUTAGE_BUDGET_SECONDS)
            label = "复盘代码" if active_review else "Brain"
            log(f"{label}启动握手失败 {review_startup_failures} 次；"
                f"本次断流预算剩余 {remaining:.0f}s")
            should_rollback = (active_review and (
                review_startup_failures >= MAX_REVIEW_STARTUP_FAILURES
                or remaining <= ROLLBACK_RESERVE_SECONDS))
            if should_rollback:
                log("复盘代码连续无法完成初始化；在两分钟预算内执行安全 patch 回滚")
                if not rollback_from_marker(outage_deadline):
                    log("启动失败回滚未能无损完成；保留现场并停止，拒绝混载未知代码")
                    return 1
                review_startup_failures = 0
                continue
            if remaining <= 0:
                log("Brain 连续无法完成启动且没有可安全撤销的复盘提交；115 秒断流预算耗尽，保留现场并停止")
                return 1
            if wait_for_stop(min(STARTUP_RETRY_SECONDS, remaining)):
                return 0
            continue
        review_startup_failures = 0

        # 异常退出：先耐心重试，回滚只是最后手段
        fast_crashes = 0 if alive_s > FAST_CRASH_SECONDS else fast_crashes + 1
        review_crashes = review_crashes + 1 if active_review else 0
        log(f"大脑异常退出（rc={rc}，存活 {alive_s:.0f}s，连续快速崩溃 "
            f"{fast_crashes}/{MAX_FAST_CRASHES}，复盘后崩溃 {review_crashes}/{MAX_FAST_CRASHES}）")

        # 有复盘 marker 时，慢崩溃同样计数；否则每次活过 90 秒都会清零，坏复盘
        # 可以永远逃过最后手段。
        if review_crashes >= MAX_FAST_CRASHES and active_review:
            log(f"复盘后连续 {MAX_FAST_CRASHES} 次异常退出——疑似复盘改坏了代码，执行安全 patch 回滚")
            if not rollback_from_marker():
                log("复盘崩溃回滚失败；为避免永久重启/回滚循环，runner 安全停止并保留现场")
                return 1
            fast_crashes = 0
            review_crashes = 0
            continue
        if wait_for_stop(RETRY_INTERVAL_SECONDS):
            log("重试等待期间收到停止请求，监督进程结束")
            return 0


if __name__ == "__main__":
    if "--clear-stop" in sys.argv and SESSION_ID == "legacy":
        clear_stop_request()
    with pid_file("runner"):
        sys.exit(main())
