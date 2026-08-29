"""LLM 元复盘 —— 异步追及队列：游玩不等待，复盘在后台串行消化。

模型策略（见 config.json 的 llm 节）：
  - runner-aware 优先链依次尝试 OpenCode/GLM、Codex/Luna、OpenCode/Kimi；
  - 每局结束只耐久入队，外部 CLI/模型探测全部由后台 worker 完成；
  - 已经启动过模型的失败事务固定原 runner/model/effort 重审，不静默换模型。
  - 失败冷却：优先模型复盘执行失败（非零退出/超时/异常）则冷却 preferred_failure_cooldown_min
    分钟，期间直接回退，避免每局白等一个超时。

异步架构（2026-08-22 起）：
  - agent.py 每局 finalize 后调用 enqueue_review()：只把请求写入 knowledge/review_queue.json
    并确保工作线程存活，主循环立即开下一局，**零等待**。
  - 工作线程 _worker_loop 串行消化队列：一局结束若上一场复盘未完，请求在队列累积，
    下一场复盘一次性分析多局（追及队列）。
  - 并发安全：autogit 的 add/commit/push 持有跨进程事务锁并使用私有 index；
    复盘激活期间对局存档只提交在线运行文件；失败 patch 始终停留在隔离取证包。
  - 复盘完成若改到 Brain 实际加载的源码/config：标记 request_restart，主循环在下一局间
    安全点以退出码 42 自重启；脚本/其他生产源码改动仍算闭环，但不误重启 Brain。

设计要点（继承）：
  - 不直接调模型裸 API；spawn OpenCode/Codex 无头会话，复用本机已有授权和工具链。
  - deny-only 路径边界 + Git 安全网：项目静态源码/配置/测试/文档可改；在线统计只读。
  - 复盘过程经 review_live.stream 直播给 review_viewer.py 悬浮窗。

手动触发 `py brain/llm_review.py --now`（同步执行，用于人工调试）。
任何异常只记日志，绝不中断游玩主循环。
"""
from __future__ import annotations

import codecs
import hashlib
import json
import math
import os
import py_compile
import queue
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

from lifecycle import stop_requested
from review_runners import (
    CodexJsonTranslator,
    OpencodeJsonTranslator,
    ReviewPlan,
    bind_review_workdir,
    build_review_command,
    review_plans_from_config,
    runner_binary,
    translator_for_runner,
)

try:
    from dashboard_launcher import ensure_dashboard_viewer
except Exception:  # optional broadcast UI must never disable review
    ensure_dashboard_viewer = None

BASE_DIR = Path(__file__).resolve().parent.parent          # sts2-ascend/
REPO_DIR = BASE_DIR.parent                                  # git 仓库根（opencode 在此获得完整上下文）
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
CONFIG_PATH = BASE_DIR / "brain" / "config.json"
PROMPT_FILE = KNOWLEDGE_DIR / "review_prompt_latest.md"
REVIEW_LOG = KNOWLEDGE_DIR / "meta_review.md"
MARKER_FILE = KNOWLEDGE_DIR / "pending_restart.json"
_SUPERSEDED_MARKER_KEY = "_superseded_marker"
_SUPERSEDED_MARKER_RAW_KEY = "_superseded_marker_raw"
_MARKER_HISTORY_MAX_DEPTH = 8
PREFERRED_STATE_FILE = KNOWLEDGE_DIR / "preferred_model_state.json"
LIVE_STREAM = KNOWLEDGE_DIR / "review_live.stream"          # 复盘直播流（review_viewer.py 读取）
VIEWER_PATH = BASE_DIR / "brain" / "review_viewer.py"
SALVAGE_ROOT = KNOWLEDGE_DIR / "code_backups" / "review_salvage"
REJECTION_LEDGER = BASE_DIR / "REVIEW_REJECTIONS.md"
REVIEW_REPORT_PATHS = frozenset({
    "sts2-ascend/knowledge/meta_review.md",
    "sts2-ascend/knowledge/review_conclusion.txt",
})
# A closure must change production behaviour/configuration or add production
# observability. Tests, docs, reports and selfcheck-only patches are useful
# evidence but cannot impersonate an operational response.
_REVIEW_PRODUCTION_SUFFIXES = frozenset({
    ".py", ".pyw", ".ps1", ".psm1", ".sh", ".bat", ".cmd",
    ".cs", ".csproj", ".fs", ".fsproj", ".vb", ".vbproj",
    ".gd", ".gdextension", ".ts", ".tsx", ".js", ".jsx",
})
_REVIEW_CONFIG_SUFFIXES = frozenset({
    ".toml", ".yaml", ".yml", ".ini", ".cfg", ".props", ".targets",
})
_REVIEW_CONFIG_NAMES = frozenset({
    "config.json", "pyproject.toml", "package.json", "requirements.txt",
    "project.godot", "mod_id.json",
})
_REVIEW_OWNER_HOT_RESTART_PATHS = frozenset({
    "sts2-ascend/tts/quipper.py",
    "sts2-ascend/tts/indextts_gpu.py",
    "sts2-ascend/tts/owner_epoch.py",
})
# 这些文件可能在异步复盘期间被在线大脑推进；它们不是复盘 patch，失败回滚和
# 复盘 commit 都不能覆盖。若同一文件来源无法区分，宁可保留现场供人工处理。
REVIEW_CONCURRENT_PATHS = [
    "sts2-ascend/knowledge/runs",
    "sts2-ascend/knowledge/stats.json",
    "sts2-ascend/knowledge/progression.json",
    "sts2-ascend/knowledge/policy.json",
    "sts2-ascend/knowledge/lessons.md",
    "sts2-ascend/knowledge/review_queue.json",
    "sts2-ascend/knowledge/preferred_model_state.json",
]
_worker_stop = threading.Event()


def _review_work_root() -> Path:
    """项目内 ignored 临时区；即使系统 TEMP 被清理，失败原件仍在项目范围。"""
    return Path(REPO_DIR) / "sts2-ascend" / "knowledge" / "code_backups" / "review_work"


def _review_hold_root() -> Path:
    """Operator-preserved packages that outlive an older host's bad closure."""
    return SALVAGE_ROOT.parent / "review_hold"


_REVIEW_HOLD_CLOSURE_DIR = ".closed"
_REVIEW_HOLD_CLOSURE_SCHEMA = 1
_REVIEW_ATTEMPT_RECEIPT_NAME = "review_attempt.json"
_REVIEW_ATTEMPT_RECEIPT_SCHEMA = 1
_LEGACY_REVIEW_SANDBOX_CLOCK_SKEW_SEC = 120.0


def _new_review_temp(prefix: str) -> Path:
    root = _review_work_root()
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def _is_owned_review_temp(path: Path, prefix: str) -> bool:
    """接受当前项目受管临时区，也兼容升级前遗留的系统 TEMP 现场。"""
    try:
        resolved = path.resolve()
        return (resolved.name.startswith(prefix) and (
            resolved.parent == _review_work_root().resolve()
            or resolved.parent == Path(tempfile.gettempdir()).resolve()))
    except OSError:
        return False


_PRIVATE_GIT_TEMP_PREFIXES = (
    "sts2-review-capture-index-",
    "sts2-review-validation-index-",
    "sts2-review-retry-index-",
)


def _remove_readonly_for_rmtree(function, path, _exc_info) -> None:
    """Let shutil remove Windows Git loose objects, which are read-only."""
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    function(path)


def _discard_owned_review_temp(root: Path | None, prefix: str, log=print) -> bool:
    """Remove one exact disposable temp tree, retrying transient Windows locks."""
    if root is None:
        return True
    try:
        resolved = root.resolve()
    except OSError as exc:
        log(f"[llm] private Git temp path lookup failed; retained: {root} ({exc})")
        return False
    if not _is_owned_review_temp(resolved, prefix):
        log(f"[llm] private Git temp ownership check failed; retained: {resolved}")
        return False
    last_error: OSError | None = None
    for delay in (0.0, 0.1, 0.25, 0.5):
        if delay:
            time.sleep(delay)
        try:
            if not resolved.exists():
                return True
            shutil.rmtree(resolved, onerror=_remove_readonly_for_rmtree)
            return True
        except OSError as exc:
            last_error = exc
    log(f"[llm] private Git temp cleanup failed; retained: {resolved} ({last_error})")
    return False


def _cleanup_stale_private_git_temps(log=print, *, min_age_sec: float = 300.0) -> None:
    """Reap only stale disposable indexes after the previous worker is gone."""
    root = _review_work_root()
    if not root.is_dir():
        return
    now = time.time()
    try:
        children = list(root.iterdir())
    except OSError as exc:
        log(f"[llm] private Git temp startup scan failed: {exc}")
        return
    for child in children:
        if not child.is_dir():
            continue
        prefix = next(
            (value for value in _PRIVATE_GIT_TEMP_PREFIXES
             if child.name.startswith(value)), "")
        if not prefix:
            continue
        try:
            age = max(0.0, now - child.stat().st_mtime)
        except OSError:
            continue
        if age < max(0.0, min_age_sec):
            continue
        _discard_owned_review_temp(child, prefix, log=log)

# Prompt working-set bounds.  Full traces remain available in runs/*.json (or
# the compact archive catalog); the inline packet should carry evidence, not
# repeat tens of kilobytes of near-identical route prose every review.
RUN_SUMMARY_COMBAT_NOTES = 5
RUN_SUMMARY_KEY_REASONS = 3
RUN_SUMMARY_TEXT_CHARS = 200


def _review_stop_requested() -> bool:
    """Combine the session sentinel with an in-process brain shutdown."""
    return stop_requested() or _worker_stop.is_set()


def _wait_review_stop(seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        if _review_stop_requested():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        _worker_stop.wait(min(0.2, remaining))


def load_llm_config() -> dict:
    cfg = {}
    viewer_cfg = {}
    if CONFIG_PATH.exists():
        try:
            root_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg = root_cfg.get("llm", {})
            viewer_cfg = root_cfg.get("viewer", {})
        except json.JSONDecodeError:
            pass
    merged = {
        "enabled": True,
        "runner": "opencode",
        "opencode_bin": "opencode",
        "codex_bin": "codex",
        "runner_bins": {"opencode": "opencode", "codex": "codex"},
        "model": "kimi-for-coding/k3",
        "review_every_runs": 5,
        "timeout_min": 480,
        "max_runs_in_packet": 100,
        # 优先模型链（按优先级；条目形如 provider/model[@variant]）：
        # GLM-5.3-Flash (2x usage) · OpenCode Go · max
        "preferred_models": [
            "opencode-go/glm-5.3-flash@max",
        ],
        # 新版优先读取 runner-aware 链；缺省/空值继续兼容上面的旧两级配置。
        "review_model_chain": None,
        "preferred_every_runs": 1,
        # 失败冷却：超时/硬失败统一 5 分钟（短冷却，别让模型长期缺席复盘）
        "preferred_timeout_cooldown_min": 5,
        "preferred_failure_cooldown_min": 5,
        # 异步复盘不阻塞游玩，优先模型的超时可放宽
        "preferred_timeout_min": 480,
        # 总复盘预算仍是 8 小时；这里只识别进程活着但长时间没有任何 stdout
        # 字节进展的工具/CLI 挂起。给模型推理、工具执行与输出缓冲留足余量。
        "stall_warn_min": 15,
        "stall_timeout_min": 30,
        # Transport/reconnect/error events are not model work.  Bound the time
        # before the translator observes the first reasoning/tool/message item
        # so a provider that only emits error heartbeats can fall through.
        "pre_work_timeout_min": 5,
        "models_probe_timeout_sec": 60,
        "models_probe_cache_sec": 300,
        # 复盘直播悬浮窗（review_viewer.py）
        "viewer_enabled": True,
        # 语音朗读器（tts/）：edge=Edge 实时直播 + IndexTTS GPU 最终结论（默认） /
        # indextts=兼容用全 IndexTTS / hybrid=SAPI 实时直播 + IndexTTS GPU 结论 /
        # nano=全克隆音色（滞后大） / sapi=纯系统语音 / off=关闭
        "tts_mode": "edge",
        # 异步复盘单批上限；持久队列本身不截断
        "review_queue_max": 100,
        # 反摸鱼闭环：两次纯报告后，下一批必须落地行为改动或运行时观测。
        "review_report_only_limit": 2,
        # 直播项目当前处于 0 胜追赶期：每个成功批次都必须有运行时闭环。
        # 没有足够把握改行为时也必须加生产观测，禁止用文档代替交付。
        "review_require_action_every_batch": True,
        # 同一问题达到任一证据阈值即应落地，不再等待“绝对安全”。
        "review_evidence_run_threshold": 3,
        "review_evidence_batch_threshold": 2,
    }
    merged.update({k: v for k, v in cfg.items() if v is not None})
    # ``viewer.enabled`` is canonical; the legacy LLM-local switch remains a
    # fallback for existing installations.
    if isinstance(viewer_cfg, dict) and viewer_cfg.get("enabled") is not None:
        merged["viewer_enabled"] = bool(viewer_cfg["enabled"])
    return merged


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _non_negative_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(parsed):
        return float(default)
    return max(0.0, parsed)


def _normalized_review_path(path) -> str:
    return str(path).replace("\\", "/").rstrip("/")


def _is_review_config_path(path: str) -> bool:
    pure = PurePosixPath(_normalized_review_path(path))
    folded = tuple(part.casefold() for part in pure.parts)
    relative = folded[1:] if folded[:1] == ("sts2-ascend",) else folded
    return (pure.name.casefold() in _REVIEW_CONFIG_NAMES
            or pure.suffix.casefold() in _REVIEW_CONFIG_SUFFIXES
            or (pure.suffix.casefold() == ".json" and relative
                and relative[0] in {"brain", "scripts", "tts"}))


def _is_review_action_path(path: str) -> bool:
    """Whether an accepted path can change production operation.

    This is a closure predicate, not a submission allowlist. Tests, docs and
    static knowledge may be accepted in the same patch; they simply cannot
    satisfy the mandatory runtime-action requirement by themselves.
    """
    normalized = _normalized_review_path(path)
    try:
        import autogit
        if autogit.classify_review_path(normalized) != autogit.REVIEW_PATH_ACCEPTED:
            return False
    except (ImportError, AttributeError):
        return False
    if normalized in REVIEW_REPORT_PATHS:
        return False
    pure = PurePosixPath(normalized)
    folded = tuple(part.casefold() for part in pure.parts)
    relative = folded[1:] if folded[:1] == ("sts2-ascend",) else folded
    if (not relative or relative[0] in {"tests", "docs"}
            or "tests" in relative or "test" in relative
            or pure.name.casefold() == "selfcheck.py"
            or pure.name.casefold().startswith("test_")):
        return False
    suffix = pure.suffix.casefold()
    return (suffix in _REVIEW_PRODUCTION_SUFFIXES
            or _is_review_config_path(normalized))


def _review_action_paths(paths) -> tuple[str, ...]:
    """Return paths that constitute a behaviour/observability closure.

    ``selfcheck.py`` alone deliberately does not count: tests can prove a real
    production change, but changing only the proof cannot improve live play.
    """
    normalized = tuple(dict.fromkeys(
        _normalized_review_path(path) for path in (paths or ())))
    return tuple(path for path in normalized if _is_review_action_path(path))


def _review_hot_restart_paths(paths) -> tuple[str, ...]:
    """Return accepted files loaded by the long-running Brain process.

    Runtime scripts and most non-Brain sources still count as actions, but a
    Brain restart cannot load them. Brain modules/live config plus the three TTS
    owner-epoch inputs do require the transactional marker: the new Brain hands
    the new epoch to the owner. ``selfcheck.py`` remains proof-only.
    """
    normalized = tuple(dict.fromkeys(
        _normalized_review_path(path) for path in (paths or ())))
    prefix = "sts2-ascend/brain/"
    return tuple(
        path for path in normalized
        if (path.startswith(prefix) or path in _REVIEW_OWNER_HOT_RESTART_PATHS)
        and path != prefix + "selfcheck.py"
        and _is_review_action_path(path)
        and (path.casefold().endswith((".py", ".pyw"))
             or _is_review_config_path(path))
    )


def _patch_has_substantive_changes(patch: bytes | str, selected_paths) -> bool:
    """Reject comment/whitespace-only touches for a selected exact path set."""
    action_paths = set(selected_paths or ())
    if not action_paths or not patch:
        return False
    text = (patch.decode("utf-8", errors="replace")
            if isinstance(patch, bytes) else str(patch))
    current = ""
    comment_prefixes = ("#", "//", "/*", "*", "*/", '"""', "'''")
    for line in text.splitlines():
        if line.startswith("diff --git "):
            marker = " b/"
            current = line.split(marker, 1)[1].strip() if marker in line else ""
            continue
        if current not in action_paths or not line.startswith(("+", "-")):
            continue
        if line.startswith(("+++", "---")):
            continue
        body = line[1:].strip()
        if (not body or body.startswith(comment_prefixes)
                or body in {"{", "}", "[", "]", ","}):
            continue
        return True
    return False


def _patch_has_substantive_action(patch: bytes | str, paths) -> bool:
    """Return whether a patch contains a real production closure."""
    return _patch_has_substantive_changes(patch, _review_action_paths(paths))


def _patch_requires_brain_restart(patch: bytes | str, paths) -> bool:
    """Return whether accepted changes must be loaded by a new Brain process."""
    return _patch_has_substantive_changes(patch, _review_hot_restart_paths(paths))


def _restart_marker_payload(
    pre_head: str, review_parent: str, review_commit: str,
    paths, stamp: str,
) -> dict:
    """Build a marker for the whole accepted transaction, not only hot files."""
    return {
        "pre_head": pre_head,
        "review_parent": review_parent,
        "review_commit": review_commit,
        "paths": list(dict.fromkeys(_normalized_review_path(path) for path in paths)),
        "time": stamp,
        "state": "prepared",
    }


def _infer_recent_report_only_streak(limit: int = 20) -> int:
    """Bootstrap the durable streak from recent accepted review commits.

    This migration makes the first review after deploying the gate aware of the
    already accepted report-only batches.  It reads commit paths only; no tree
    fingerprint or repository-wide hash is created.
    """
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(REPO_DIR), "log", "--no-renames",
                f"-n{max(1, limit)}", "--fixed-strings", "--grep=LLM 复盘变更",
                "--format=__STS2_REVIEW_COMMIT__%H", "--name-only",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    if proc.returncode != 0:
        return 0

    commits: list[list[str]] = []
    current: list[str] | None = None
    for raw in proc.stdout.splitlines():
        line = raw.strip().replace("\\", "/")
        if line.startswith("__STS2_REVIEW_COMMIT__"):
            if current is not None:
                commits.append(current)
            current = []
        elif line and current is not None:
            current.append(line)
    if current is not None:
        commits.append(current)

    streak = 0
    for paths in commits:
        if _review_action_paths(paths):
            break
        if paths:
            streak += 1
    return streak


def _review_closure_state(know, cfg: dict) -> dict:
    """Build the host-owned anti-stagnation state embedded in the next prompt."""
    limit = _positive_int(cfg.get("review_report_only_limit"), 2)
    run_threshold = _positive_int(cfg.get("review_evidence_run_threshold"), 3)
    batch_threshold = _positive_int(cfg.get("review_evidence_batch_threshold"), 2)
    progression = getattr(know, "progression", {})
    stored = progression.get("review_report_only_streak") if isinstance(progression, dict) else None
    if isinstance(stored, int) and not isinstance(stored, bool) and stored >= 0:
        streak = stored
        source = "progression"
    else:
        streak = _infer_recent_report_only_streak()
        source = "git_history_bootstrap"
    require_every_batch = bool(cfg.get("review_require_action_every_batch", True))
    required = require_every_batch or streak >= limit
    return {
        "version": 1,
        "consecutive_report_only": streak,
        "report_only_limit": limit,
        "evidence_run_threshold": run_threshold,
        "evidence_batch_threshold": batch_threshold,
        "action_required": required,
        "require_action_every_batch": require_every_batch,
        "state_source": source,
        "last_outcome": (progression.get("review_closure_last_outcome", "unknown")
                         if isinstance(progression, dict) else "unknown"),
        "rule": (
            "当前每批都必须修改运行时代码/配置或增加生产观测；证据阈值用于决定优先级。"
            "纯文档和仅自检永远不算闭环。"
        ),
    }


def _recent_review_context(max_chars: int = 12000) -> str:
    """Bounded recent reports let the model count repeated evidence explicitly."""
    try:
        text = REVIEW_LOG.read_text(encoding="utf-8")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return "[较早内容已截断]\n" + text[-max_chars:]


def _batch_description(batch_runs) -> str:
    """Describe reordered/recovered batches without producing `730~729`."""
    runs = sorted({int(run) for run in (batch_runs or [])})
    if not runs:
        return ""
    if len(runs) == 1:
        return f"第 {runs[0]} 局"
    if len(runs) == runs[-1] - runs[0] + 1:
        return f"第 {runs[0]}~{runs[-1]} 局"
    return f"第 {runs[0]}~{runs[-1]} 局范围内的 {len(runs)} 局"


def _historical_zero_code_context(max_sections: int = 10,
                                  max_chars: int = 30000) -> str:
    """Extract accepted zero-code reports as explicit implementation debt."""
    try:
        lines = REVIEW_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    sections: list[str] = []
    current: list[str] = []
    for line in lines:
        is_review_heading = (line.lstrip().startswith("#")
                             and "局" in line and "复盘" in line)
        if is_review_heading:
            if current:
                section = "\n".join(current).strip()
                if ("零代码" in section or "未改任何 .py" in section
                        or "未改任何 `.py`" in section):
                    sections.append(section)
            current = [line]
        elif current:
            current.append(line)
    if current:
        section = "\n".join(current).strip()
        if ("零代码" in section or "未改任何 .py" in section
                or "未改任何 `.py`" in section):
            sections.append(section)
    selected = "\n\n".join(sections[-max(1, max_sections):])
    if len(selected) <= max_chars:
        return selected
    return "[更早零代码债务已截断]\n" + selected[-max_chars:]


def _record_review_closure(know, base_state: dict, paths, batch_runs, log=print,
                           action_accepted: bool | None = None) -> dict:
    """Persist only accepted review outcomes; rejected/failed attempts never count."""
    action_paths = _review_action_paths(paths)
    is_action = bool(action_paths) if action_accepted is None else bool(action_accepted)
    if is_action:
        outcome = "implemented"
        streak = 0
    else:
        outcome = "report_only" if paths else "no_change"
        streak = int(base_state.get("consecutive_report_only", 0)) + 1
    progression = getattr(know, "progression", None)
    if isinstance(progression, dict):
        progression["review_report_only_streak"] = streak
        progression["review_closure_last_outcome"] = outcome
        progression["review_closure_last_runs"] = [int(run) for run in (batch_runs or [])]
        progression["review_closure_last_paths"] = [
            str(path).replace("\\", "/") for path in (paths or ())
        ]
        progression["review_closure_updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if is_action:
        log("[llm] 闭环完成：运行时行为/观测已落地，纯报告连续计数归零（"
            + ", ".join(action_paths) + "）")
    else:
        limit = int(base_state.get("report_only_limit", 2))
        suffix = "；下一批已强制进入代码/观测闭环" if streak >= limit else ""
        log(f"[llm] 本批仅沉淀报告，连续 {streak}/{limit} 批{suffix}")
    return {**base_state, "consecutive_report_only": streak,
            "action_required": (bool(base_state.get("require_action_every_batch", True))
                                or streak >= int(base_state.get("report_only_limit", 2))),
            "last_outcome": outcome}


def _review_closure_gate_error(state: dict, paths,
                               patch: bytes | str | None = None) -> str:
    action_paths = _review_action_paths(paths)
    substantive = bool(action_paths)
    if patch is not None:
        substantive = _patch_has_substantive_action(patch, paths)
    if not state.get("action_required") or substantive:
        return ""
    streak = int(state.get("consecutive_report_only", 0))
    limit = int(state.get("report_only_limit", 2))
    return (
        f"闭环闸门拒绝纯报告：当前要求每批落地；历史连续纯报告 {streak} 次（阈值 {limit}）。"
        "本批必须对运行时行为或观测路径产生实质代码变化；meta_review、短评、仅 selfcheck，"
        "以及只改注释/空白来碰瓷生产路径都不算闭环。无需证明绝对安全，可做相对安全、可观测、"
        "可记录、可继续调整或撤回的改动。"
    )


def _provider_tool_capability_error(
    runner: str, sandbox: "SandboxReviewResult",
) -> str:
    """Return a host/tool failure before the closure gate can blame the model."""
    metrics = (sandbox.provider_metrics
               if isinstance(sandbox.provider_metrics, dict) else {})
    try:
        blocked = int(metrics.get("blocked_tool_count") or 0)
    except (TypeError, ValueError):
        blocked = 0
    if (runner != "codex" or blocked <= 0 or sandbox.paths or sandbox.patch
            or sandbox.stopped or sandbox.timed_out or sandbox.stalled):
        return ""
    detail = " ".join(str(metrics.get("tool_access_error") or "").split())[:500]
    suffix = f"：{detail}" if detail else ""
    return (
        f"复盘 runner 工具能力被阻断（{blocked} 次），模型未获得读取/执行/写入任务的能力"
        f"{suffix}"
    )


# ---------------------------------------------------------------------------
# packet / prompt
# ---------------------------------------------------------------------------

def _stats_digest(know) -> dict:
    g = know.stats["global"]
    cards = [
        {"id": cid, "picked": e["picked"], "plays": e["plays"],
         "avg_outcome": round(e["outcome_sum"] / e["picked"], 1) if e["picked"] else None,
         "bias": e.get("bias", 0.0)}
        for cid, e in know.stats["cards"].items() if e["picked"] or e["plays"]
    ]
    enemies = [
        {"comp": comp, "fights": e["encounters"],
         "avg_hp_lost": round(e["hp_lost_sum"] / max(1, e["encounters"]), 1),
         "deaths": e["deaths"], "wins": e["wins"]}
        for comp, e in know.stats["enemies"].items()
    ]
    enemies.sort(key=lambda x: (-x["deaths"], -x["avg_hp_lost"]))
    relics = [
        {"id": rid, "picked": e.get("picked", 0),
         "avg_outcome": round(e.get("outcome_sum", 0.0) / e["picked"], 1)
         if e.get("picked") else None,
         "bias": e.get("bias", 0.0)}
        for rid, e in know.stats.get("relics", {}).items()
        if isinstance(e, dict) and e.get("picked")
    ]
    return {
        "stats_version": know.stats.get("version"),
        "global": g,
        "progression": know.progression,
        "cards": cards,
        "relics": relics,
        "enemies": enemies,
        "events": know.stats["events"],
        "rooms": know.stats.get("rooms", {}),
        "rooms_act": know.stats.get("rooms_act", {}),
        "rooms_band": know.stats.get("rooms_band", {}),
        "respawn_adds": know.stats.get("respawn_adds", {}),
        # 竞速审计账本（RACE_AUDIT_STATS_AGGREGATION，第813~822局批复盘）：
        # 把 RACE_PROJ_CALIB_AUDIT 的「判死→实战结局」计数直接带进 packet，
        # 复盘批不再依赖 grep 单局日志，预注册分桶规则可从 digest 消费
        "race_audit": know.stats.get("race_audit", {}),
        "act_entries_total": len(know.stats.get("act_entries") or []),
        "recent_act_entries": list(know.stats.get("act_entries") or [])[-12:],
        "policy": know.policy,
    }


def _clip_summary_text(value) -> str:
    text = str(value or "")
    if len(text) <= RUN_SUMMARY_TEXT_CHARS:
        return text
    return text[:RUN_SUMMARY_TEXT_CHARS - 1] + "…"


def _run_is_complete(data: dict) -> bool:
    """Exclude a genuine incremental checkpoint while tolerating old dirty stamps."""
    if not data.get("in_progress"):
        return True
    trail = data.get("decisions") or []
    return any(isinstance(item, dict) and item.get("screen") == "GAME_OVER"
               for item in trail)


def _requested_archived_runs(run_numbers: set[int], seen_files: set[str]) -> list[tuple[Path, dict]]:
    """Load exact compacted evidence by run_number, with archive hash verification."""
    catalog = KNOWLEDGE_DIR / "archive" / "run_catalog.jsonl"
    if not run_numbers or not catalog.exists():
        return []
    try:
        from compact_knowledge import read_run_evidence
    except ImportError:
        return []
    rows = []
    try:
        lines = catalog.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(entry, dict) or entry.get("run_number") not in run_numbers:
            continue
        filename = str(entry.get("file") or "")
        if not filename or filename in seen_files:
            continue
        try:
            data = json.loads(read_run_evidence(KNOWLEDGE_DIR, filename).decode("utf-8"))
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and _run_is_complete(data):
            rows.append((Path(filename), data))
            seen_files.add(filename)
    return rows


def _summarize_run(data: dict, evidence_match: str) -> dict:
    decisions = [x for x in (data.get("decisions") or []) if isinstance(x, dict)]
    # 脏戳字段的读端复原（第 369 局复盘）：被回写的文件顶层 floor=0/
    # victory=false 是脏值，决策轨迹才是真账。
    floor = int(data.get("floor") or 0)
    trail_max = max((int(x.get("floor") or 0) for x in decisions), default=0)
    if trail_max > floor:
        floor = trail_max
    victory = bool(data.get("victory"))
    if not victory and any(x.get("screen") == "GAME_OVER"
                           and "胜利" in str(x.get("reason") or "")
                           for x in decisions):
        victory = True
    combat_notes = list(data.get("combat_notes") or [])
    key_reasons = [x.get("reason", "") for x in decisions
                   if x.get("action") in ("choose_map_node", "choose_event_option",
                                          "choose_rest_option", "skip_reward_cards")]
    return {
        "run_id": data.get("run_id"), "run_number": data.get("run_number"),
        "evidence_match": evidence_match,
        "victory": victory, "floor": floor, "ascension": data.get("ascension"),
        "decisions": len(decisions), "combat_notes_total": len(combat_notes),
        "combat_notes": [_clip_summary_text(x)
                         for x in combat_notes[-RUN_SUMMARY_COMBAT_NOTES:]],
        "key_reasons_total": len(key_reasons),
        "key_reasons": [_clip_summary_text(x)
                        for x in key_reasons[-RUN_SUMMARY_KEY_REASONS:]],
    }


def _review_run_records(
        n: int, batch_runs: list[int] | None = None) -> list[tuple[Path, dict, str]]:
    """Resolve the bounded recent set or an exact queued batch once.

    The returned evidence label keeps archived/legacy fallback rows explicit so
    callers cannot accidentally present unrelated recent runs as the requested
    batch.  Both summaries and full decision-chain evidence consume this same
    resolver, preventing the two views from silently drifting apart.
    """
    run_dir = KNOWLEDGE_DIR / "runs"
    if not run_dir.exists():
        return []
    # 进行中对局不入摘要（第 218 批复盘）：增量存档的 in_progress 文件是
    # 半局数据，混进复盘摘要会把「还在打的一局」当完整对局误读。
    # 脏戳豁免（第 369 局复盘）：历史库存在「终局定稿后被结算屏后继决策
    # 回写增量稿」的已完成局——决策轨迹里已出现 GAME_OVER 的 in_progress
    # 文件必为定稿后被盖脏戳的完整体，按完成局放行；真进行中的对局轨迹里
    # 不可能出现 GAME_OVER，照常排除。否则摘要把近百余局全部过滤，
    # 复盘数据包永远停留在旧局（第 263~369 局实证）。
    requested = {int(item) for item in (batch_runs or [])}
    # 只保留提示词需要的最近 N 局与命中的批次，不把五百余局完整 JSON
    # 同时常驻内存。精确批次仍会继续从归档中补找。
    recent: deque[tuple[Path, dict]] = deque(maxlen=max(0, n))
    selected: list[tuple[Path, dict]] = []
    for p in sorted(run_dir.glob("*.json"), key=lambda p: p.name):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if _run_is_complete(d):
            recent.append((p, d))
            if requested and int(d.get("run_number") or -1) in requested:
                selected.append((p, d))

    if not requested:
        return [(path, data, "recent") for path, data in recent]

    seen = {path.name for path, _ in selected}
    selected.extend(_requested_archived_runs(requested, seen))
    selected.sort(key=lambda row: (int(row[1].get("run_number") or 0), row[0].name))
    matched = {int(data.get("run_number")) for _, data in selected
               if data.get("run_number") is not None}
    out = [(path, data, "exact_batch") for path, data in selected]
    if matched != requested:
        # Historical logs predate run_number.  Keep a bounded recent fallback for
        # diagnostic context, but label it so the coach cannot mistake it for the
        # requested queue batch.
        fallback_n = max(0, n - len(out))
        for path, data in list(recent)[-fallback_n:] if fallback_n else []:
            if path.name not in seen:
                out.append((path, data, "recent_fallback_unmapped"))
    return out


def _recent_run_summaries(n: int, batch_runs: list[int] | None = None) -> list[dict]:
    return [_summarize_run(data, evidence_match)
            for _, data, evidence_match in _review_run_records(n, batch_runs)]


def _primary_failure_decision_chain(
        n: int, batch_runs: list[int] | None = None,
        records: list[tuple[Path, dict, str]] | None = None) -> dict:
    """Return every persisted decision from the newest exact failed run.

    A 100-run queue currently contains roughly 6.6 MB of decision JSON and does
    not fit safely alongside tools in the review model's context.  The newest
    failed run is therefore the mandatory full-fidelity case; the other queued
    runs keep their bounded summaries.  Nothing inside the selected decision list
    is clipped or sampled, including legacy rows that predate rich trace fields.
    """
    records = records if records is not None else _review_run_records(n, batch_runs)
    eligible = []
    for path, data, evidence_match in records:
        if batch_runs and evidence_match != "exact_batch":
            continue
        summary = _summarize_run(data, evidence_match)
        if not summary["victory"]:
            eligible.append((int(summary.get("run_number") or 0), path, data,
                             evidence_match, summary))
    if not eligible:
        return {
            "selection_policy": "newest_exact_failed_run_full",
            "full_failure_run": None,
        }

    _, path, data, evidence_match, summary = max(
        eligible, key=lambda item: (item[0], item[1].name))
    decisions = [row for row in (data.get("decisions") or [])
                 if isinstance(row, dict)]
    serialized = json.dumps(decisions, ensure_ascii=False, separators=(",", ":"))
    return {
        "selection_policy": "newest_exact_failed_run_full; other_runs_summarized",
        "full_failure_run": {
            "run_id": data.get("run_id"),
            "run_number": summary.get("run_number"),
            "evidence_match": evidence_match,
            "evidence_file": path.name,
            "victory": False,
            "floor": summary.get("floor"),
            "decision_count": len(decisions),
            "serialized_chars": len(serialized),
            "complete_persisted_chain": True,
            "decisions": decisions,
        },
    }


def _sandbox_readable_corpus_paths(value):
    """Rewrite real-repository corpus paths for the isolated review clone.

    ``review_digest`` is also consumed by runtime callers, so keep its result
    untouched and normalize only the prompt packet's ``corpus_paths`` branch.
    The recursive handling keeps future grouped/list path shapes readable too.
    """
    repo_prefix = REPO_DIR.resolve().as_posix().rstrip("/")
    if isinstance(value, dict):
        return {key: _sandbox_readable_corpus_paths(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_sandbox_readable_corpus_paths(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sandbox_readable_corpus_paths(item) for item in value)
    if not isinstance(value, str) or not repo_prefix:
        return value
    normalized = value.replace("\\", "/")
    descendant_prefix = repo_prefix + "/"
    if normalized.casefold().startswith(descendant_prefix.casefold()):
        return normalized[len(descendant_prefix):]
    return value


def build_prompt(know, cfg: dict, every: int | None = None,
                 batch_runs: list[int] | None = None,
                 closure_state: dict | None = None,
                 salvage_packages: list[str] | None = None,
                 salvage_attempts: list[str] | None = None,
                 evidence_only: bool = False,
                 log=print) -> str:
    n = int(cfg.get("max_runs_in_packet", 100))
    # A runless legacy salvage still needs a positive synthetic ``run`` value as
    # durable queue identity.  It must never borrow a real run with that number
    # from the current knowledge store and present it as evidence for the old
    # package.
    run_records = ([] if evidence_only else
                   _review_run_records(n, batch_runs=batch_runs))
    run_summaries = [_summarize_run(data, evidence_match)
                     for _, data, evidence_match in run_records]
    decision_chain_evidence = (
        {
            "selection_policy": "evidence_only_replay_no_synthetic_run",
            "full_failure_run": None,
        }
        if evidence_only else
        _primary_failure_decision_chain(
            n, batch_runs=batch_runs, records=run_records)
    )
    evidence_text = []
    for summary in run_summaries:
        evidence_text.extend(summary.get("combat_notes") or [])
        evidence_text.extend(summary.get("key_reasons") or [])
    full_failure_run = decision_chain_evidence.get("full_failure_run") or {}
    evidence_text.extend(str(row.get("reason") or "")
                         for row in (full_failure_run.get("decisions") or []))
    native = getattr(know, "game_knowledge", None)
    closure_state = closure_state or _review_closure_state(know, cfg)
    replay_context = _failed_review_replay_context(
        salvage_packages or [], salvage_attempts or [], log=log)
    retry_feedback = _review_retry_feedback(
        salvage_packages or [], salvage_attempts or [])
    native_digest = (native.review_digest(know.stats, evidence_text)
                     if native is not None else
                     {"snapshot": {"available": False,
                                   "error": "native index not initialized"}})
    if isinstance(native_digest, dict) and "corpus_paths" in native_digest:
        native_digest = dict(native_digest)
        native_digest["corpus_paths"] = _sandbox_readable_corpus_paths(
            native_digest.get("corpus_paths"))
    packet = {
        "runs_summary": run_summaries,
        "run_evidence_scope": ({
            "requested": [],
            "queue_identity_runs": list(batch_runs or []),
            "evidence_only": True,
            "exact": [],
            "missing": [],
            "fallback_is_not_batch_evidence": False,
        } if evidence_only else {
            "requested": list(batch_runs or []),
            "queue_identity_runs": list(batch_runs or []),
            "evidence_only": False,
            "exact": sorted(int(item["run_number"]) for item in run_summaries
                            if item.get("evidence_match") == "exact_batch"),
            "missing": sorted(set(int(x) for x in (batch_runs or []))
                              - {int(item["run_number"]) for item in run_summaries
                                 if item.get("evidence_match") == "exact_batch"}),
            "fallback_is_not_batch_evidence": any(
                item.get("evidence_match") == "recent_fallback_unmapped"
                for item in run_summaries),
        }),
        "decision_chain_evidence": decision_chain_evidence,
        "review_closure": closure_state,
        # Recent accepted reports expose repeated issue mentions to the next
        # reviewer without inlining the unbounded full meta-review history.
        "recent_review_context": _recent_review_context(),
        "historical_zero_code_debt": _historical_zero_code_context(),
        # A failed package is evidence for a fresh same-model audit, never an input to
        # host-side patch application.  Bounded excerpts keep the initial prompt
        # navigable; the exact target+attempt files are mounted separately inside
        # the isolated clone and integrity-checked before receipts are accepted.
        "failed_review_replay": replay_context,
        "stats_digest": _stats_digest(know),
        # Never inline the full ~9 MB corpus.  The index chooses entities named in
        # recent evidence plus the most consequential learned card/enemy records;
        # corpus_paths lets the reviewer drill into exact JSONL facts on demand.
        "native_game_knowledge": native_digest,
    }
    lessons_tail = ""
    lessons_path = KNOWLEDGE_DIR / "lessons.md"
    if lessons_path.exists():
        lessons_tail = lessons_path.read_text(encoding="utf-8")[-2500:]

    cadence = every or cfg.get('review_every_runs', 10)
    if evidence_only:
        scope = ("本次只重审失败包证据；队列中的 run 数字只是持久身份，"
                 "不得把当前或近期同号 run 当作该失败包的证据")
    elif batch_runs and len(batch_runs) > 1:
        scope = f"本次复盘覆盖{_batch_description(batch_runs)}（异步追及队列）"
    elif batch_runs:
        scope = f"本次复盘覆盖{_batch_description(batch_runs)}"
    else:
        scope = f"每 {cadence} 局你做一次大模型复盘"
    missing_batch = packet["run_evidence_scope"]["missing"]
    if missing_batch:
        scope += (f"；其中第 {missing_batch} 局缺少历史 run_number 映射，"
                  "标为 recent_fallback_unmapped 的摘要仅供背景参考，不得冒充本批证据")

    # Whitespace-only compaction: _stats_digest's fields and values are left
    # intact.  This saves prompt tokens without silently weakening statistical
    # evidence; full stats.json remains available for on-demand inspection.
    packet_json = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    retry_feedback_json = json.dumps(
        retry_feedback, ensure_ascii=False, separators=(",", ":"))
    closure_summary_keys = (
        "action_required", "require_action_every_batch",
        "consecutive_report_only", "report_only_limit",
        "evidence_run_threshold", "evidence_batch_threshold", "last_outcome",
    )
    closure_summary = "；".join(
        f"{key}={json.dumps(closure_state.get(key), ensure_ascii=False)}"
        for key in closure_summary_keys if key in closure_state)

    return f"""你是「sts2-ascend」杀戮尖塔2自主学习智能体的总教练。{scope}。
你的交付不是分析报告，而是一次由你亲自完成、可验证、可撤回的生产闭环。

# 上次失败反馈（先读这一小段，再开始工作）
<retry_feedback>{retry_feedback_json}</retry_feedback>
若这里显示 `runner_tool_access_denied`，那是宿主工具权限故障，不是你的策略判断失败；本轮工具恢复后
不要重复上次的空终态。任何本地读取、shell 或 Apply Patch 再出现 `blocked by policy` / `Access denied`
时，立即输出 `BLOCKED_TOOL_CAPABILITY`、原始错误与被阻断的动作，然后停止；不得伪造已复盘或写
`no_valid_change`。

# 数据载体
本文件的**第一个 `json` 代码块就是完整 packet**，不存在独立的 packet JSON 文件。若工具截断
超长单行，请本地读取 `sts2-ascend/knowledge/review_prompt_latest.md`，提取第一个 fenced `json`
代码块并用 `json.loads` 解析。packet 内 `corpus_paths` 都是当前隔离 clone 可读的相对路径。

# review_closure 快速摘要
{closure_summary}

```json
{packet_json}
```

最近的 lessons.md 尾部：
```
{lessons_tail}
```

# 证据与合法终态
- 若 `failed_review_replay.requested_packages` 非空，先读其 `complete_evidence.index`，再按索引核对
  target 和全部 attempts 的完整 manifest、report、inventory、候选 patch 与 changed files。失败 patch
  只是证据；你必须基于当前 HEAD 自行重实现仍有效部分、解决冲突并自检，宿主不会替你套用。
- replay 只有三种回执：`integrated` 表示你已重实现并验证；`no_valid_change` 只允许在完整 lineage
  全部可读、且你能给出当前 HEAD 路径与证据条件证明无需改动时使用；证据不全写 `still_pending`。
  工具阻断只写 `BLOCKED_TOOL_CAPABILITY`，不能冒充以上任一结论。
- `historical_zero_code_debt` 是历史问题债务。只有指出已经存在的生产路径和实际生效行为才能标为
  resolved；每批优先完成一个最高价值 unresolved 问题，除非本批有更高优先级致命缺陷。
- 同一问题达到 `evidence_run_threshold` 个独立对局或连续 `evidence_batch_threshold` 个成功复盘批次
  后，不得再次只登记“待观察”。每个成功复盘批次必须落地一个有界运行时行为/配置改动，或增加
  后续 run 可直接验证假设的生产观测。纯 `meta_review.md`、纯短评、仅 selfcheck/tests/docs、注释或
  空白都不是闭环。
- 改动追求**相对安全、范围有界、可观测、可记录、可继续调整或撤回**；每批只选一个主假设。

# 交付顺序（严格执行）
1. 工具与证据：读取本任务书、`git status --short` 和完成一个最高价值问题所需的最小证据。若最新
   死亡局有 `decision_chain_evidence.full_failure_run`，必须先逐条阅读并检查 decisions；涉及卡牌、怪物、遗物、
   药水或事件时，优先查 `native_game_knowledge` 与对应 runtime/mechanics JSONL，不能用旧版记忆代替。
2. 假设：先写一句 `HYPOTHESIS / EVIDENCE / EXPECTED_SIGNAL`，引用具体局、楼层、回合或动作。
3. 落地：立即用 Apply Patch 对生产行为、配置或运行时观测做一个最小可逆改动。你被明确授权修改或
   新建 `sts2-ascend/` 下的静态项目文件，包括生产源码、`brain/config.json`、其他配置、
   `scripts/`、`tests/`、`docs/`、静态原生游戏 knowledge 与复盘报告；宿主以 deny-only 精确路径
   分类，不设 allowlist。
4. 自检修复：改过任何 `.py` 后运行 `py -3 -B sts2-ascend/brain/selfcheck.py`；失败就读取具体错误、
   继续修补并重跑，直到 `SELFCHECK OK`。回读完整 diff，核对行为、证据、撤回条件和意外文件。
5. 最后才写报告：把归因、假设、实际代码动作、未来 3~10 局指标、继续调整/撤回条件追加到
   `sts2-ascend/knowledge/meta_review.md`。replay target 各写一行
   `retry_resolution: <package-id> integrated|no_valid_change|still_pending`。再把 100 字以内、适合口播、
   约 10 字一停顿的短评写入 `sts2-ascend/knowledge/review_conclusion.txt`。
6. 自己收口：再次回读 diff、解决冲突、确认自检，然后在当前隔离 clone 内自行 `git add` 和本地
   `git commit`，返回 commit SHA。若缺少身份，用命令级 `-c user.name=sts2-review-luna`
   `-c user.email=local@sts2-ascend.invalid`；宿主只机械验收该最终内容并用 CAS 发布，不替你审计或改写。

# 写入边界
- 禁止写在线状态：`.runtime/`，`knowledge/runs/`、`archive/`、`code_backups/`，以及 stats、progression、
  policy、lessons、review_queue、preferred_model_state、pending_restart、lock/log/stream/flag、宿主 prompt、
  截图和拒合清单；它们只读。任一路径段含 cache 或 `.pyc/.pyo` 也不进入成果。
- 禁止写 `sts2-ascend/` 外路径、绝对路径、`..` 逃逸或 `.gitmodules`。允许当前隔离 clone 内为本批
  使用 git status/diff/add/commit；禁止 remote、push、reset、删除历史或改宿主/其他工作区。
- 除自检与本批必要的只读/测试命令外，禁止启动、停止、终止或管理进程；禁止安装依赖。

完成后用 200 字以内总结：假设、落地文件、自检结果、本地 commit SHA。"""


def _review_invocation_prompt(rel_prompt: str) -> str:
    """Keep the executable contract available even if the task-file read fails."""
    return (
        f"你位于宿主创建的隔离 clone。先完整阅读 {rel_prompt}。你已获授权在当前 clone "
        "内读取证据、修改 sts2-ascend 静态项目文件、运行 selfcheck，并自行回读 diff、"
        "解决冲突和本地 commit；禁止 push、访问其他工作区或管理在线进程。成功标准："
        "一个可证伪假设，一个最小生产行为/观测改动，SELFCHECK OK，最终 diff 复核和 commit SHA，"
        "最后才写报告。若读取、shell 或 Apply Patch 被 blocked/access denied，立即输出 "
        "BLOCKED_TOOL_CAPABILITY 与原始错误并停止，不能声称完成或写 no_valid_change。"
    )


# ---------------------------------------------------------------------------
# runner-aware 优先链可用性探测（只在后台 worker，带短缓存与失败冷却）
# ---------------------------------------------------------------------------

_preferred_state_memory: dict | None = None
_preferred_state_memory_path = ""
_preferred_state_lock = threading.RLock()


def _preferred_state_copy(state: dict) -> dict:
    return json.loads(json.dumps(state, ensure_ascii=False))


def _load_preferred_state() -> dict:
    """Load once per path; transient read failure remains retryable."""
    global _preferred_state_memory, _preferred_state_memory_path
    state_path = str(PREFERRED_STATE_FILE.resolve())
    with _preferred_state_lock:
        if _preferred_state_memory_path != state_path:
            _preferred_state_memory_path = state_path
            _preferred_state_memory = None
        if _preferred_state_memory is not None:
            return _preferred_state_copy(_preferred_state_memory)
        for attempt in range(4):
            try:
                state = json.loads(PREFERRED_STATE_FILE.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    raise ValueError("preferred state root is not an object")
                _preferred_state_memory = state
                return _preferred_state_copy(state)
            except FileNotFoundError:
                _preferred_state_memory = {}
                return {}
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                if attempt < 3:
                    time.sleep(0.05 * (attempt + 1))
        # Do not cache an unreadable disk as empty: a later resolver pass retries.
        return {}


def _save_preferred_state(state: dict) -> bool:
    """Atomically persist cooldown state while retaining an in-process fallback."""
    global _preferred_state_memory, _preferred_state_memory_path
    payload = json.dumps(state, ensure_ascii=False, indent=1) + "\n"
    state_path = str(PREFERRED_STATE_FILE.resolve())
    with _preferred_state_lock:
        _preferred_state_memory_path = state_path
        _preferred_state_memory = _preferred_state_copy(state)
        temp = PREFERRED_STATE_FILE.with_name(
            f".{PREFERRED_STATE_FILE.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        try:
            temp.write_text(payload, encoding="utf-8")
            _replace_with_retry(temp, PREFERRED_STATE_FILE, attempts=4)
            return True
        except OSError:
            return False
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def _parse_entry(entry: str) -> tuple[str, str | None]:
    """'opencode-go/glm-5.3-flash@max' → ('opencode-go/glm-5.3-flash', 'max')。"""
    if "@" in entry:
        m, v = entry.rsplit("@", 1)
        return m, (v or None)
    return entry, None


def _entry_state(entry: str) -> dict:
    entries = _load_preferred_state().get("entries", {})
    if not isinstance(entries, dict):
        return {}
    value = entries.get(entry, {})
    return value if isinstance(value, dict) else {}


def _write_entry_state(entry: str, data: dict) -> bool:
    state = _load_preferred_state()
    entries = state.get("entries")
    if not isinstance(entries, dict):
        entries = {}
        state["entries"] = entries
    entries[entry] = data
    return _save_preferred_state(state)


def _preferred_cooldown_remaining(entry: str) -> float:
    """该优先模型失败冷却剩余秒数（0 表示未在冷却中）。"""
    until = float(_entry_state(entry).get("unavailable_until", 0) or 0)
    return max(0.0, until - time.time())


def _mark_preferred_failure(cfg: dict, log, entry: str, reason: str, kind: str = "failure") -> None:
    """优先后端失败冷却（按稳定 backend key 独立计时）。"""
    key = "preferred_timeout_cooldown_min" if kind == "timeout" else "preferred_failure_cooldown_min"
    cooldown_min = float(cfg.get(key, 30 if kind == "timeout" else 60))
    durable = _write_entry_state(entry, {
        "unavailable_until": time.time() + cooldown_min * 60,
        "last_failure": reason,
        "last_failure_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    persistence = "" if durable else "；磁盘暂时写失败，本进程内冷却仍已生效"
    log(f"[llm] 优先后端 {entry} 复盘失败（{reason}），"
        f"{cooldown_min:.0f} 分钟内跳过该条目{persistence}")


def _mark_preferred_ok(entry: str) -> None:
    if _entry_state(entry).get("unavailable_until"):
        _write_entry_state(entry, {"unavailable_until": 0})


_review_probe_cache: dict[str, tuple[float, object]] = {}


def _probe_cache_get(key: str, ttl: float):
    cached = _review_probe_cache.get(key)
    if cached and time.monotonic() - cached[0] <= max(0.0, ttl):
        return cached[1]
    return None


def _probe_cache_put(key: str, value):
    _review_probe_cache[key] = (time.monotonic(), value)
    return value


def _query_available_models(binary: str, cfg: dict, log) -> set[str] | None:
    """运行 `opencode models` 返回可用模型 id 集合；探测失败返回 None。"""
    ttl = float(cfg.get("models_probe_cache_sec", 300) or 0)
    cache_key = f"opencode:{binary}"
    cached = _probe_cache_get(cache_key, ttl)
    if isinstance(cached, set):
        return set(cached)
    timeout = int(cfg.get("models_probe_timeout_sec", 60))
    try:
        proc = _run_captured_stop_aware(
            [binary, "models"], timeout=timeout)
    except _ReviewStopped:
        raise
    except Exception as exc:
        log(f"[llm] 模型清单探测异常：{exc}")
        return None
    if proc.returncode != 0:
        log(f"[llm] 模型清单探测失败（exit={proc.returncode}）：{(proc.stderr or '')[-200:]}")
        return None
    models = {ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()}
    return _probe_cache_put(cache_key, models)


def _query_codex_models(binary: str, cfg: dict, log) -> dict[str, set[str]] | None:
    """Cheap local catalog + saved-auth probe; no paid model turn is created."""
    ttl = float(cfg.get("models_probe_cache_sec", 300) or 0)
    cache_key = f"codex:{binary}"
    cached = _probe_cache_get(cache_key, ttl)
    if isinstance(cached, dict):
        return {str(key): set(value) for key, value in cached.items()}
    timeout = int(cfg.get("models_probe_timeout_sec", 60))
    try:
        auth = _run_captured_stop_aware(
            [binary, "login", "status"], timeout=min(timeout, 30))
        if auth.returncode != 0:
            log(f"[llm] Codex 登录探测失败（exit={auth.returncode}）")
            return None
        catalog = _run_captured_stop_aware(
            [binary, "debug", "models", "--bundled"], timeout=timeout)
        if catalog.returncode != 0:
            log(f"[llm] Codex 模型目录探测失败（exit={catalog.returncode}）")
            return None
        payload = json.loads(catalog.stdout or "{}")
        models: dict[str, set[str]] = {}
        for item in payload.get("models") or []:
            if not isinstance(item, dict) or not item.get("slug"):
                continue
            efforts = {
                str(level.get("effort")) for level in
                (item.get("supported_reasoning_levels") or [])
                if isinstance(level, dict) and level.get("effort")
            }
            models[str(item["slug"])] = efforts
        return _probe_cache_put(cache_key, models)
    except _ReviewStopped:
        raise
    except Exception as exc:
        log(f"[llm] Codex 可用性探测异常：{exc}")
        return None


def resolve_review_plan(
    cfg: dict, binary: str | None = None, log=print,
) -> ReviewPlan:
    """Resolve the first available runner/model entry in worker context.

    ``binary`` remains as a legacy OpenCode override for tests and old callers.
    ``ReviewPlan.__iter__`` preserves three-value tuple unpacking.
    """
    plans = review_plans_from_config(cfg)
    if not plans:
        raise ValueError("review model chain is empty")
    opencode_models: set[str] | None = None
    codex_models: dict[str, set[str]] | None = None
    reasons: list[str] = []
    for plan in plans:
        cooldown = _preferred_cooldown_remaining(plan.state_key)
        if cooldown > 0:
            log(f"[llm] 后端 {plan.key} 冷却中（剩余 {cooldown / 60:.0f} 分钟），看下一优先")
            reasons.append(f"{plan.key}:cooldown")
            continue
        selected_binary = binary if plan.runner == "opencode" and binary else runner_binary(cfg, plan.runner)
        if not selected_binary:
            log(f"[llm] 后端 {plan.key} 缺少 {plan.runner} 可执行文件，看下一优先")
            reasons.append(f"{plan.key}:binary-missing")
            continue
        if plan.runner == "opencode":
            if opencode_models is None:
                opencode_models = _query_available_models(selected_binary, cfg, log) or set()
            if plan.model not in opencode_models:
                log(f"[llm] 后端 {plan.key} 的模型不在 OpenCode 可用清单，看下一优先")
                reasons.append(f"{plan.key}:model-unavailable")
                continue
            return plan
        if plan.runner == "codex":
            if codex_models is None:
                codex_models = _query_codex_models(selected_binary, cfg, log) or {}
            efforts = codex_models.get(plan.model)
            if efforts is None:
                log(f"[llm] 后端 {plan.key} 的模型不在 Codex 目录，看下一优先")
                reasons.append(f"{plan.key}:model-unavailable")
                continue
            if plan.reasoning_effort and efforts and plan.reasoning_effort not in efforts:
                log(f"[llm] 后端 {plan.key} 不支持 reasoning={plan.reasoning_effort}，看下一优先")
                reasons.append(f"{plan.key}:effort-unavailable")
                continue
            return plan
        log(f"[llm] 不支持的复盘 runner={plan.runner}，看下一优先")
        reasons.append(f"{plan.key}:runner-unsupported")
    reason = ",".join(reasons) or "no-available-backend"
    log(f"[llm] 三级复盘后端当前均不可用；队列保留等待（{reason}）")
    return replace(plans[-1], available=False, unavailable_reason=reason)


# ---------------------------------------------------------------------------
# 直播流：把复盘会话的 stdout 实时写到 review_live.stream，并拉起悬浮窗
# ---------------------------------------------------------------------------

def _launch_viewer(cfg: dict, log) -> None:
    """确认全栈常驻悬浮窗存在；不再为每次复盘重复创建进程。"""
    if (_review_stop_requested() or not cfg.get("viewer_enabled", True)
            or ensure_dashboard_viewer is None):
        return
    try:
        ensure_dashboard_viewer({"viewer_enabled": True}, log)
    except Exception as exc:
        log(f"[llm] 直播悬浮窗检查失败（不影响复盘）：{exc}")


def _launch_speaker(cfg: dict, log) -> None:
    """拉起语音朗读器。

    ``edge`` 默认让 Edge TTS 读实时正文，并在结束后把本场短结论提交给共享
    IndexTTS GPU owner；两个引擎允许同时出声。独立进程的死活不影响复盘。
    """
    mode = str(cfg.get("tts_mode", "edge"))
    if _review_stop_requested() or mode == "off":
        return
    try:
        creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        cmd = None
        if mode == "edge":
            edge = BASE_DIR / "tts" / "edge_speaker.py"
            uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")
            if edge.exists() and Path(uv).exists():
                cmd = [uv, "run", "--no-project", "--with", "edge-tts",
                       "--with", "imageio-ffmpeg", "python", str(edge)]
            else:
                log("[llm] edge-tts 环境未就绪，语音回退 hybrid")
                mode = "hybrid"
        elif mode == "nano":
            nano = BASE_DIR / "tts" / "nano_speaker.py"
            moss_ready = (BASE_DIR / "third_party" / "MOSS-TTS-Nano" / "models").exists()
            uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")
            if nano.exists() and moss_ready and Path(uv).exists():
                cmd = [uv, "run", "--no-project",
                       "--with", "onnxruntime", "--with", "sentencepiece",
                       "--with", "torch", "--with", "torchaudio",
                       "python", str(nano)]
            else:
                log("[llm] MOSS-Nano 未就绪，语音回退 hybrid")
                mode = "hybrid"
        if cmd is None:
            speaker = BASE_DIR / "tts" / "speaker.py"
            if not speaker.exists():
                return
            cmd = [sys.executable, "-u", str(speaker), mode]
        subprocess.Popen(cmd, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=creationflags, close_fds=True)
        log(f"[llm] 语音朗读器已拉起（{mode}）")
    except Exception as exc:
        log(f"[llm] 语音朗读器拉起失败（不影响复盘）：{exc}")


def _stream_begin(meta: dict) -> None:
    try:
        LIVE_STREAM.write_text("[LIVE-START] " + json.dumps(meta, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    except OSError:
        pass


def _stream_end(payload: dict) -> None:
    try:
        with LIVE_STREAM.open("a", encoding="utf-8") as f:
            f.write("[LIVE-END] " + json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


class _ReviewStopped(RuntimeError):
    """协作停止已到达；调用方必须保留当前隔离现场。"""


def _process_group_kwargs() -> dict:
    """让复盘命令拥有可精确终止的进程树，不波及用户的其他工具。"""
    if os.name == "nt":
        return {"creationflags": (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))}
    return {"start_new_session": True}


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """终止本次命令及其子进程，避免停止后继续改写隔离仓。"""
    if proc.poll() is not None:
        return
    if os.name == "nt" and getattr(proc, "pid", None):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass


def _run_captured_stop_aware(
    args: list[str], *, cwd: Path | str | None = None, binary: bool = False,
    timeout: int = 120, env: dict | None = None,
) -> subprocess.CompletedProcess:
    """可轮询停止的 capture_output；停止时精确杀掉本次进程树。"""
    if _review_stop_requested():
        raise _ReviewStopped()
    kwargs = {
        "cwd": str(cwd) if cwd is not None else None,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
        **_process_group_kwargs(),
    }
    if not binary:
        kwargs.update({"text": True, "encoding": "utf-8", "errors": "replace"})
    proc = subprocess.Popen(args, **kwargs)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if _review_stop_requested():
                raise _ReviewStopped()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                stdout, stderr = proc.communicate(timeout=min(0.2, remaining))
                return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    except BaseException:
        _terminate_process_tree(proc)
        try:
            proc.communicate(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise


def _stream_run(cmd: list[str], timeout_sec: int, translate=None, *,
                stall_warn_sec: float = 0,
                stall_timeout_sec: float = 0,
                pre_work_timeout_sec: float = 0,
                raw_transcript: Path | None = None,
                metrics_sink: dict | None = None) -> tuple[int, str, bool, bool, bool]:
    """流式执行命令；直播落盘，队列、单事件与返回尾部均严格有界。"""
    env = dict(os.environ)
    env["NO_COLOR"] = "1"      # 关掉 ANSI 颜色，viewer 自己上色
    env["TERM"] = "dumb"
    # 提示词要求模型自行跑 selfcheck；-B + 环境双保险，避免宿主要求本身
    # 制造 ignored pyc，进而把合规复盘误判为越界。模型主动写入的 pyc 仍保留。
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # The review agent runs in a full repository clone and may execute project
    # entrypoints while validating a patch.  It must never create a second
    # broadcast overlay from that clone.
    env["STS2_ASCEND_DISABLE_VIEWER"] = "1"
    # BOOT_ID belongs only to the real runner→Brain startup handshake.  Passing
    # it into OpenCode makes sandbox selfchecks impersonate that startup and
    # fail when their PID cannot advance the live Brain record.
    env.pop("STS2_ASCEND_BOOT_ID", None)
    stream_started = time.monotonic()
    translator = getattr(translate, "__self__", None)
    reset_clock = getattr(translator, "reset_clock", None)
    if callable(reset_clock):
        reset_clock()
    proc = subprocess.Popen(
        cmd, cwd=str(REPO_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", bufsize=8192, env=env,
        **_process_group_kwargs())

    # 128 * 8192 约 1 MiB；即使模型连续八小时输出，reader 也不会无限吃内存。
    q: queue.Queue[str] = queue.Queue(maxsize=128)
    reader_cancel = threading.Event()
    reader_done = threading.Event()
    # last raw byte time, chunk count, first-byte latency, maximum inter-chunk gap
    progress = [stream_started, 0, None, 0.0]

    def _reader() -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            source = getattr(proc.stdout, "buffer", proc.stdout)
            read_chunk = getattr(source, "read1", source.read)
            while not reader_cancel.is_set():
                raw = read_chunk(8192) if source is not None else b""
                if not raw:
                    break
                chunk = (raw if isinstance(raw, str)
                         else decoder.decode(raw, final=False))
                observed = time.monotonic()
                progress[3] = max(progress[3], observed - progress[0])
                progress[0] = observed
                progress[1] += 1
                if progress[2] is None:
                    progress[2] = observed - stream_started
                if not chunk:
                    continue
                while not reader_cancel.is_set():
                    try:
                        q.put(chunk, timeout=0.2)
                        break
                    except queue.Full:
                        continue
        except (OSError, ValueError):
            pass
        finally:
            try:
                final = decoder.decode(b"", final=True)
                if final:
                    q.put(final, timeout=0.2)
            except (UnicodeError, queue.Full):
                pass
            reader_done.set()

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    deadline = time.monotonic() + timeout_sec
    tail: deque[str] = deque()
    tail_chars = 0
    tail_limit = 256 * 1024
    event_limit = 256 * 1024
    pending = ""
    timed_out = False
    stopped = False
    stalled = False
    warned = False
    seen_progress = 0
    silence_floor = stream_started

    transcript = None
    if raw_transcript is not None:
        try:
            raw_transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript = raw_transcript.open("w", encoding="utf-8", newline="")
        except OSError:
            transcript = None
    try:
      with LIVE_STREAM.open("a", encoding="utf-8") as stream:
        def emit_display(value: str) -> None:
            nonlocal tail_chars
            if not value.endswith("\n"):
                value += "\n"
            try:
                stream.write(value)
                stream.flush()
            except OSError:
                pass
            if len(value) >= tail_limit:
                tail.clear()
                value = value[-tail_limit:]
                tail_chars = 0
            tail.append(value)
            tail_chars += len(value)
            while tail_chars > tail_limit and tail:
                tail_chars -= len(tail.popleft())

        def emit_raw_line(raw: str) -> None:
            for output in (translate(raw) if translate else [raw]):
                emit_display(output)

        while True:
            try:
                chunk = q.get(timeout=0.2)
            except queue.Empty:
                chunk = ""
            if chunk:
                if transcript is not None:
                    try:
                        transcript.write(chunk)
                        transcript.flush()
                    except OSError:
                        try:
                            transcript.close()
                        except OSError:
                            pass
                        transcript = None
                pending += chunk
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    emit_raw_line(line + "\n")
                if len(pending) > event_limit:
                    dropped = len(pending) - event_limit
                    pending = pending[-event_limit:]
                    emit_display(
                        f"[llm] 单条无换行输出过大，已截断前 {dropped} 个字符；"
                        "这不影响隔离仓内失败文件的完整保全。")
                # Host-side translation/backpressure is observable progress, not
                # provider silence.  Start a new watchdog interval only after the
                # consumed raw chunk has finished translation.
                silence_floor = time.monotonic()
            if progress[1] != seen_progress:
                seen_progress = progress[1]
                warned = False
            if _review_stop_requested():
                stopped = True
                _terminate_process_tree(proc)
                break

            # A clean EOF wins over silence heuristics.  In particular, the
            # translator above may legitimately spend longer than the stall
            # threshold on the final chunk after the reader has already
            # observed EOF.  Do not turn that completed process into a stall.
            backlog = q.qsize()
            reader_finished = reader_done.is_set()
            if reader_finished and backlog == 0:
                if pending:
                    emit_raw_line(pending)
                    pending = ""
                break
            if time.monotonic() > deadline:
                timed_out = True
                _terminate_process_tree(proc)
                break
            observed_now = time.monotonic()
            raw_idle = observed_now - progress[0]
            idle = observed_now - max(progress[0], silence_floor)
            proc_state = proc.poll()
            diagnostics = (
                f"qsize={backlog}, reader_done={reader_finished}, "
                f"proc_poll={proc_state}, last_raw_idle={raw_idle:.1f}s, "
                f"effective_idle={idle:.1f}s")

            # The child has already exited, so silence is not a hung model.  Let
            # the pipe reader publish its final EOF/chunks even if a slow final
            # translation temporarily starved that thread under host CPU load.
            if proc_state is not None and backlog == 0:
                continue

            # Codex can keep emitting transport/reconnect/error JSON for hours.
            # Those bytes remain useful diagnostics, but they are not evidence
            # that the model has begun reasoning or using tools and therefore
            # must not extend the provider-start window.  Once real model work
            # is observed, the existing raw-output stall watchdog is unchanged.
            model_work_started = bool(
                translator is not None
                and getattr(translator, "model_work_started", False))
            if (translator is not None and not model_work_started
                    and pre_work_timeout_sec > 0
                    and observed_now - stream_started >= pre_work_timeout_sec):
                stalled = True
                emit_display(
                    f"[llm] provider produced no model work for "
                    f"{observed_now - stream_started:.1f}s; startup unavailable; "
                    f"diagnostics: {diagnostics}.")
                _terminate_process_tree(proc)
                break

            # A full/busy queue means raw output is waiting for translation;
            # lack of a newer pipe read is then backpressure, not model silence.
            if (backlog == 0 and stall_warn_sec > 0
                    and idle >= stall_warn_sec and not warned):
                warned = True
                emit_display(
                    f"[llm] 复盘已 {idle / 60:.1f} 分钟无输出进展；"
                    "继续等待，达到无进展上限才会保全现场并重试；"
                    f"诊断：{diagnostics}。")
            if (backlog == 0 and stall_timeout_sec > 0
                    and idle >= stall_timeout_sec):
                stalled = True
                emit_display(
                    f"[llm] 复盘连续 {idle / 60:.1f} 分钟无输出进展；"
                    "判定 CLI/工具调用挂起，终止本次并保全现场重试；"
                    f"诊断：{diagnostics}。")
                _terminate_process_tree(proc)
                break
    finally:
        if transcript is not None:
            try:
                transcript.close()
            except OSError:
                pass
        # This cleanup deliberately covers stream-open and translator failures too.
        # Otherwise a malformed provider event could strand a child that keeps
        # writing its disposable review clone after Brain has abandoned it.
        exceptional = sys.exc_info()[0] is not None
        if exceptional:
            _terminate_process_tree(proc)
        reader_cancel.set()
        if _review_stop_requested():
            stopped = True
        try:
            proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            _terminate_process_tree(proc)
            try:
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except OSError:
            pass
        reader_thread.join(timeout=1)
        progress[3] = max(progress[3], time.monotonic() - progress[0])
    rc = proc.returncode if proc.returncode is not None else -1
    if metrics_sink is not None:
        metrics_sink.update({
            "duration_sec": max(0.0, time.monotonic() - stream_started),
            "first_raw_byte_after_sec": progress[2],
            "max_raw_output_gap_sec": progress[3],
            "raw_chunk_count": progress[1],
        })
    return rc, "".join(tail), timed_out, stopped, stalled


# ---------------------------------------------------------------------------
# review execution
# ---------------------------------------------------------------------------

def _run_selfcheck(log, base_dir: Path | None = None) -> bool:
    """py_compile 全文件 + 冒烟测试（含真实知识库加载）。"""
    root = Path(base_dir) if base_dir is not None else BASE_DIR
    brain_dir = root / "brain"
    try:
        # 编译产物写到系统临时目录；这样失败现场里的任意 ignored/pyc 都必然
        # 是模型留下的内容，不需要按路径猜来源，更不会误删分析证据。
        with tempfile.TemporaryDirectory(prefix="sts2-review-pycompile-") as compiled:
            for index, f in enumerate(brain_dir.glob("*.py")):
                if _review_stop_requested():
                    raise _ReviewStopped()
                try:
                    py_compile.compile(
                        str(f), cfile=str(Path(compiled) / f"{index}-{f.name}.pyc"),
                        doraise=True)
                except py_compile.PyCompileError as exc:
                    log(f"[llm] 自检失败（编译 {f.name}）：{exc}")
                    return False
    except _ReviewStopped:
        raise
    try:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["STS2_ASCEND_DISABLE_VIEWER"] = "1"
        env.pop("STS2_ASCEND_BOOT_ID", None)
        proc = _run_captured_stop_aware(
            [sys.executable, str(brain_dir / "selfcheck.py")],
            timeout=120, env=env)
        if proc.returncode != 0 or "SELFCHECK OK" not in (proc.stdout or ""):
            log(f"[llm] 自检失败（冒烟）：{(proc.stdout or '')[-400:]} {(proc.stderr or '')[-400:]}")
            return False
    except _ReviewStopped:
        raise
    except Exception as exc:
        log(f"[llm] 自检异常：{exc}")
        return False
    return True


def run_review(know, log=print, model: str | None = None, every: int | None = None,
               source: str = "fallback", runner: str | None = None,
               backend_key: str | None = None, priority: int = 1,
               variant: str | None = None, reasoning_effort: str | None = None,
               approve_for_me: bool = False, sandbox_mode: str = "workspace-write",
               batch_runs: list[int] | None = None,
               async_mode: bool = False, _status: dict | None = None,
               salvage_packages: list[str] | None = None,
               salvage_attempts: list[str] | None = None,
               replay_queue_ids: list[str] | None = None,
               evidence_only: bool = False,
               review_queue_items: list[dict] | None = None) -> bool:
    """执行一次大模型复盘。返回 True 仅表示 patch 触及 Brain 加载路径、应热重启。

    流程：保存在线进度 → provider 隔离复盘 → deny-only 路径分类 → 自检 → 精确提交；
    失败时从隔离 clone 导出包含全部改动（含 ignored/越界）的补合包；
    cache 只从自动 patch 排除、不阻断源码；其他拒绝项不约束失败成果留档。
    source="preferred" 时若执行失败（非零退出/超时/异常）会对优先模型记失败冷却。
    async_mode=True（异步队列工作线程调用）时，在线存档和推送继续独立运行；
    它们不会参与隔离复盘 patch 的验收。
    """
    replay_packages = _normalize_salvage_package_names(salvage_packages or [])
    replay_attempts = _normalize_salvage_package_names(salvage_attempts or [])
    replay_target = replay_packages[0] if replay_packages else ""
    replay_queue_ids = [str(value) for value in (replay_queue_ids or []) if str(value)]
    if _status is not None:
        _status.clear()
        _status.update({
            "outcome": "failed",
            "reason": "复盘未完成",
            "canceled": False,
            "commit": "",
            "pushed": False,
            "salvage_packages": list(replay_packages),
            "salvage_attempts": list(replay_attempts),
            "retry_resolutions": {},
        })
    if _review_stop_requested():
        if _status is not None:
            _status.update({"outcome": "canceled", "reason": "整套停止", "canceled": True})
        log("[llm] 已收到整套停止请求，不再启动新复盘")
        return False
    cfg = load_llm_config()
    if not cfg.get("enabled"):
        log("[llm] 复盘已禁用（llm.enabled=false）")
        return False
    runner = str(runner or cfg.get("runner") or "opencode").strip().lower()
    model = str(model or cfg["model"])
    if runner == "opencode":
        parsed_model, parsed_variant = _parse_entry(model)
        model = parsed_model
        variant = variant or parsed_variant
    plan = ReviewPlan(
        key=str(backend_key or (model + (f"@{variant}" if variant else ""))),
        priority=max(1, int(priority)),
        runner=runner,
        model=model,
        variant=variant,
        reasoning_effort=reasoning_effort,
        approve_for_me=bool(approve_for_me),
        sandbox=str(sandbox_mode or "workspace-write"),
        every_runs=max(1, int(every or cfg.get("review_every_runs", 5))),
        source=source,
    )
    binary = runner_binary(cfg, runner)
    if not binary:
        if _status is not None:
            _status["reason"] = f"未找到 {runner} 可执行文件"
            _status["startup_unavailable"] = True
        log(f"[llm] 未找到 {runner} 可执行文件，保留本次复盘")
        return False
    entry = plan.display_model
    state_key = plan.state_key
    every = plan.every_runs

    import autogit  # 延迟导入，避免 standalone 运行时的循环依赖
    runs = know.stats["global"]["runs"]
    batch_txt = (_batch_description(batch_runs).replace(" ", "")
                 if batch_runs else f"第{runs}局")
    # 1) 只保存在线数据。代码必须已干净；自动流程绝不替用户提交开发中的代码。
    autogit.commit_progress_result(
        f"chore(sts2-ascend): {batch_txt}后复盘前在线存档",
        log=log, paths=REVIEW_CONCURRENT_PATHS,
    )
    pre_head = autogit.head()

    stamp = time.strftime("%Y-%m-%d %H:%M")
    log(f"[llm] ===== 启动大模型复盘（{entry} via {runner} [{source}]，{batch_txt}，备份点 {pre_head[:8]}）=====")
    closure_state = _review_closure_state(know, cfg)
    closure_note = "强制落地" if closure_state["action_required"] else "允许继续取证"
    log("[llm] 闭环状态：纯报告连续 "
        f"{closure_state['consecutive_report_only']}/{closure_state['report_only_limit']}，"
        f"本批{closure_note}（{closure_state['state_source']}）")
    prompt = build_prompt(
        know, cfg, every, batch_runs, closure_state=closure_state,
        salvage_packages=replay_packages, salvage_attempts=replay_attempts,
        evidence_only=evidence_only, log=log)
    try:
        PROMPT_FILE.write_text(prompt, encoding="utf-8")
    except OSError:
        pass
    # 提示词包可达数万字，超过 Windows 命令行 32767 上限（WinError 206）——
    # 完整提示词落盘；命令行保留目标、授权和停止条件，避免读文件失败时退化成空报告。
    rel_prompt = PROMPT_FILE.relative_to(REPO_DIR).as_posix()
    short_prompt = _review_invocation_prompt(rel_prompt)
    try:
        cmd = build_review_command(
            plan, binary, REPO_DIR, short_prompt,
            title=f"sts2-ascend 复盘 {stamp}")
    except ValueError as exc:
        if _status is not None:
            _status.update({"reason": str(exc), "startup_unavailable": True})
        log(f"[llm] 无法构造复盘 runner：{exc}")
        return False

    if _review_stop_requested():
        if _status is not None:
            _status.update({"outcome": "canceled", "reason": "整套停止", "canceled": True})
        log("[llm] 备份完成时收到停止请求，取消本次复盘")
        return False

    # 直播流开启 + 拉起悬浮窗/语音朗读器（哨兵/meta 先行）。review_id 让旧 Edge
    # 进程在连续复盘、同一路径 truncate/regrow 时仍能按场次去重结论。
    review_id = f"{os.getpid()}-{time.time_ns()}"
    attempt_items = [dict(item) for item in (review_queue_items or [])
                     if isinstance(item, dict)]
    attempt_runs = list(batch_runs or [runs])
    if (not attempt_items and replay_queue_ids
            and len(replay_queue_ids) == len(attempt_runs)):
        for run, queue_id in zip(attempt_runs, replay_queue_ids):
            attempt_items.append({
                "run": int(run),
                "queue_id": queue_id,
                **plan.as_queue_fields(),
                "retry_same_model": True,
                "salvage_packages": list(replay_packages),
                "salvage_attempts": list(replay_attempts),
                **({"replay_target": replay_target} if replay_target else {}),
            })
    attempt_receipt = {
        "attempt_id": review_id,
        "pre_head": pre_head,
        "batch_runs": attempt_runs,
        "queue_items": attempt_items,
        "replay_queue_ids": list(replay_queue_ids),
        "replay_target": replay_target,
        "replay_packages": list(replay_packages),
        "replay_attempts": list(replay_attempts),
        "plan": plan.as_queue_fields(),
        # Queue affinity is durable before run_review.  Once this receipt is
        # published, a host crash must not silently hand the attempt elsewhere.
        "provider_launch_affinity_committed": bool(attempt_items),
    }
    _stream_begin({
        "review_id": review_id,
        "runner": runner,
        "backend_key": state_key,
        "model": entry,
        "source": source,
        "run": runs,
        "time": stamp,
    })
    _launch_viewer(cfg, log)
    _launch_speaker(cfg, log)

    autogit.set_review_active(True)     # 生命周期标记；不阻塞在线存档与推送
    rc, out, timed_out, stopped, stalled = -1, "", False, False, False
    eff_timeout_min = float(cfg.get("preferred_timeout_min", 480)) if source == "preferred" \
        else float(cfg.get("timeout_min", 480))
    stall_timeout_min = _non_negative_float(cfg.get("stall_timeout_min"), 30.0)
    stall_warn_min = _non_negative_float(cfg.get("stall_warn_min"), 15.0)
    pre_work_timeout_min = _non_negative_float(
        cfg.get("pre_work_timeout_min"), 5.0)
    if stall_timeout_min > 0:
        stall_warn_min = min(stall_warn_min, stall_timeout_min)
    else:
        stall_warn_min = 0.0
    translator = translator_for_runner(runner)
    sandbox = SandboxReviewResult(error="复盘尚未运行")

    def save_failure(reason: str) -> Path | None:
        package = _save_review_salvage(
            pre_head, reason, sandbox, batch_runs=(batch_runs or [runs]),
            runner=runner, model=model, backend_key=state_key,
            variant=variant or "", reasoning_effort=reasoning_effort or "",
            priority=plan.priority, approve_for_me=plan.approve_for_me,
            sandbox_mode=plan.sandbox,
            source=source, every=every,
            replay_target=replay_target, replay_attempts=replay_attempts,
            replay_queue_ids=replay_queue_ids,
            review_attempt_id=sandbox.review_attempt_id,
            review_sandbox_name=sandbox.review_sandbox_name,
            review_attempt_receipt_schema=(
                sandbox.review_attempt_receipt_schema),
            prompt_text=prompt,
            invocation_prompt=short_prompt,
            log=log)
        if package is not None and _status is not None:
            _status["salvage_package"] = package.name
            _status["new_salvage_package"] = package.name
        return package

    try:
        sandbox = _run_review_sandbox(
            cmd, prompt, pre_head, int(eff_timeout_min * 60), translator,
            runner=runner,
            stall_warn_seconds=stall_warn_min * 60,
            stall_timeout_seconds=stall_timeout_min * 60,
            pre_work_timeout_seconds=pre_work_timeout_min * 60,
            replay_packages=replay_packages,
            replay_attempts=replay_attempts,
            attempt_receipt=attempt_receipt,
            log=log)
        rc, out, timed_out, stopped, stalled = (
            sandbox.rc, sandbox.out, sandbox.timed_out, sandbox.stopped,
            sandbox.stalled)
        if _status is not None:
            _status["provider_metrics"] = dict(sandbox.provider_metrics)
            _status["provider_work_started"] = sandbox.provider_work_started
        # stop 可能恰好落在 opencode 自然退出与宿主验收之间；不能只信任
        # _stream_run 返回瞬间的 stopped 快照。
        stopped = stopped or _review_stop_requested()
        sandbox.stopped = sandbox.stopped or stopped
        if stopped:
            sandbox.error = "统一停机中断并全量保全"
        capability_error = _provider_tool_capability_error(runner, sandbox)
        if capability_error:
            sandbox.failure_code = "runner_tool_access_denied"
            sandbox.error = capability_error
            sandbox.conclusion = (
                "本次未读取到任务，runner 工具权限已被宿主识别为基础设施故障；"
                "不能算作模型的纯报告。")
            if _status is not None:
                _status["failure_code"] = sandbox.failure_code
        resolutions = _validated_retry_resolutions(
            sandbox, replay_packages, log=log)
        confirmed_no_change = bool(replay_packages) and all(
            resolutions.get(name) == "no_valid_change" for name in replay_packages)
        closure_error = ""
        if rc == 0 and not timed_out and not stopped and not sandbox.error:
            closure_error = _review_closure_gate_error(
                closure_state, sandbox.paths, sandbox.patch)
            if closure_error and not confirmed_no_change:
                sandbox.error = closure_error
                # Do not broadcast a rejected report as if it were an accepted
                # review conclusion; make the retry reason visible instead.
                sandbox.conclusion = "本次复盘只写文档，闭环闸门已拒绝，模型必须落地代码或观测后重做。"
        if replay_packages and _status is not None:
            _status["retry_resolutions"] = resolutions
            _status["unresolved_salvage_packages"] = [
                name for name in replay_packages
                if resolutions.get(name) not in {"integrated", "no_valid_change"}]
        if sandbox.error or stopped:
            evidence_preflight_failed = (
                sandbox.replay_evidence_requested
                and not sandbox.replay_evidence_complete
                and not sandbox.replay_evidence_model_started
                and not stopped)
            if evidence_preflight_failed:
                # No model ran and the original lineage is already the complete
                # forensic source.  Do not manufacture a huge empty attempt; the
                # unchanged queue item will retry after evidence recovery.
                log("[llm] 完整失败包证据尚不可用；未启动模型、未消费回执、"
                    "未删除原包，target 保持队首重试")
            else:
                save_failure(sandbox.error or "协作停止留下的部分复盘现场")
        # 停止批次永不合入 patch，也永不消费队列，让新进程重做该批。
        if stopped:
            if _status is not None:
                _status.update({"outcome": "canceled", "reason": "整套停止", "canceled": True})
            retry_note = "批次下次启动重试" if async_mode else "手动复盘已取消"
            log(f"[llm] 整套停止已取消隔离复盘；真实工作树未改，{retry_note}"
                f"（复盘前基线 {pre_head[:8]}）")
            return False
        log(f"[llm] 复盘会话结束（exit={rc}）。输出尾部：\n{out[-2000:]}")
        if stalled:
            if _status is not None:
                _status["reason"] = "复盘 CLI/工具调用无进展挂起"
                _status["startup_unavailable"] = not sandbox.provider_work_started
            if not sandbox.provider_work_started:
                if source == "preferred":
                    _mark_preferred_failure(
                        cfg, log, state_key, "pre-work stall", kind="timeout")
                log("[llm] pre-work stall: next retry may advance to the next tier")
                return False

            # 这是本地工具链挂起，不是 provider 不可用；不冷却当前后端。队列会
            # 保存同批并在退避后再次调用同一模型，失败包供它复审/解冲突。
            backend = _review_backend_label({
                "backend_key": state_key, "runner": runner, "model": model,
                "variant": variant or "",
                "reasoning_effort": reasoning_effort or "",
            })
            log("[llm] 复盘无进展 watchdog 已终止挂起进程；完整现场已保存，"
                f"同批将重新交给 {backend}")
            return False
        if timed_out:
            if _status is not None:
                _status["reason"] = "复盘超时"
                _status["startup_unavailable"] = not sandbox.provider_work_started
            log(f"[llm] 复盘超时（{eff_timeout_min:.0f} 分钟），本次作废")
            if source == "preferred":
                _mark_preferred_failure(cfg, log, state_key, "timeout", kind="timeout")
            return False
        if rc != 0:
            if _status is not None:
                _status["reason"] = f"复盘进程 exit={rc}"
                _status["startup_unavailable"] = not sandbox.provider_work_started
            if source == "preferred":
                _mark_preferred_failure(cfg, log, state_key, f"exit={rc}")
            log(f"[llm] 隔离复盘失败：{sandbox.error or f'exit={rc}'}；真实工作树未改")
            return False
        if sandbox.error:
            if _status is not None:
                _status["reason"] = sandbox.error
            log(f"[llm] 隔离复盘被拒绝：{sandbox.error}；真实工作树未改")
            return False
        if source == "preferred":
            _mark_preferred_ok(state_key)
    except Exception as exc:
        # 启动期异常（如 WinError 206 命令行过长）属本地环境问题，非模型故障，不记冷却
        log(f"[llm] 复盘调用失败（已忽略，不影响游玩）：{exc}")
        return False
    finally:
        _stream_end({
            "exit": rc,
            "timeout": timed_out,
            "stalled": stalled,
            "stopped": stopped,
            "review_id": review_id,
            # 结论取自即将删除的隔离 clone，已过路径分类/selfcheck/patch 导出；
            # 直接随哨兵传递，避免真实工作树稍后才 apply 导致读到上一场旧文件。
            "conclusion": sandbox.conclusion,
            "conclusion_ready": bool(sandbox.conclusion),
        })
        # 模型退出隔离 clone 后已不可能产生半成品文件；无论成功失败都立即清 flag。
        autogit.set_review_active(False)
        # 无论本次复盘成功、失败还是合法无改动，都补推一次网络失败时积压的
        # 本地提交；正常直播 checkpoint 在复盘期间本就会照常 push。
        if not _review_stop_requested():
            autogit.push_pending(log=log, attempts=1)

    discard_verified_snapshot = False
    try:
        # 2) 模型在独立 clone 中运行；这里只接收已全仓扫描、自检通过的精确 patch。
        review_paths = list(sandbox.paths)
        if not review_paths:
            discard_verified_snapshot = True
            reviewed_through = max(batch_runs) if batch_runs else runs
            know.progression["last_successful_review_run"] = max(
                int(know.progression.get("last_successful_review_run", 0)), reviewed_through)
            _record_review_closure(
                know, closure_state, review_paths, batch_runs, log=log)
            try:
                know.save()
            except OSError:
                pass
            if _status is not None:
                _status.update({"outcome": "documented", "reason": "合法复盘无文件变更"})
            log("[llm] 复盘未产生任何文件变更，跳过提交")
            return False
        try:
            review_paths = list(autogit.validate_review_paths(review_paths))
        except ValueError as exc:
            save_failure(f"Git 安全层拒绝复盘 patch：{exc}")
            log(f"[llm] Git 安全层拒绝复盘 patch：{exc}")
            return False
        if not sandbox.patch:
            save_failure("隔离复盘未导出有效 patch")
            log("[llm] 隔离复盘未导出有效 patch，拒绝合入")
            return False

        # 3) marker 在 update-ref/push 前原子发布；patch commit 的私有 index 只包含
        # 模型 hunk，同文件中并发用户 hunk 留在工作树且不会被提交。
        has_action = _patch_has_substantive_action(sandbox.patch, review_paths)
        hot_restart = _patch_requires_brain_restart(sandbox.patch, review_paths)

        def prepare_marker(provisional) -> bool:
            # prepare 在工作树 apply/update-ref 之前、同一 Git 事务锁内执行，是
            # 合入前最后一道停止闸门。停止批次保留 reviewing 给新进程恢复。
            if _review_stop_requested():
                if _status is not None:
                    _status.update({
                        "outcome": "canceled", "reason": "整套停止", "canceled": True})
                log("[llm] patch 合入前收到整套停止请求；取消提交并保留复盘批次")
                return False
            if not hot_restart:
                return True
            return _write_restart_marker(_restart_marker_payload(
                pre_head, provisional.before_head, provisional.commit,
                review_paths, stamp), log=log)

        def abort_marker(provisional) -> None:
            if hot_restart:
                _remove_restart_marker(provisional.commit, log=log)

        def finalize_marker(provisional) -> None:
            if hot_restart and not _commit_restart_marker(provisional.commit, log=log):
                raise OSError("重启 marker 未能从 prepared 确认为 committed")

        if _review_stop_requested():
            if _status is not None:
                _status.update({"outcome": "canceled", "reason": "整套停止", "canceled": True})
            log("[llm] 隔离验证后收到整套停止请求；不进入 patch 提交")
            sandbox.stopped = True
            save_failure("隔离验证后整套停止")
            return False
        result = autogit.commit_patch_result(
            sandbox.patch,
            f"feat(sts2-ascend): {batch_txt} LLM 复盘变更（详见 knowledge/meta_review.md）",
            review_paths, log=log, prepare=prepare_marker, abort_prepare=abort_marker,
            finalize_prepare=finalize_marker,
        )
        if not result.created:
            canceled = bool(_status is not None and _status.get("outcome") == "canceled")
            sandbox.stopped = sandbox.stopped or canceled or _review_stop_requested()
            if not canceled and _status is not None:
                _status["reason"] = result.reason or "复盘 patch 提交失败"
            save_failure(
                "patch 合入前整套停止" if canceled else (
                    result.reason or "复盘 patch 提交失败"))
            log(f"[llm] 复盘 patch 未能安全提交，保留现场供诊断：{result.reason}")
            return False
        discard_verified_snapshot = True
        review_pushed = bool(result.pushed)
        if not review_pushed and not _review_stop_requested():
            review_pushed = autogit.push_pending(log=log, attempts=3)
        if _status is not None:
            _status.update({"commit": result.commit, "pushed": review_pushed})
        reviewed_through = max(batch_runs) if batch_runs else runs
        know.progression["last_successful_review_run"] = max(
            int(know.progression.get("last_successful_review_run", 0)), reviewed_through)
        _record_review_closure(
            know, closure_state, review_paths, batch_runs, log=log,
            action_accepted=has_action)
        try:
            know.save()
        except OSError:
            pass
        if replay_packages and _status is not None:
            closure_resolutions = dict(_status.get("retry_resolutions") or {})
            for name in replay_packages:
                if closure_resolutions.get(name) == "integrated" and not has_action:
                    closure_resolutions[name] = "still_pending"
                    unresolved = _status.setdefault("unresolved_salvage_packages", [])
                    if name not in unresolved:
                        unresolved.append(name)
                    log(f"[llm] {name} 声称 integrated 但本批没有生产动作；保留 target 重审")
            closure_result = _close_replayed_salvages(
                replay_packages, replay_attempts,
                closure_resolutions,
                commit=result.commit, pushed=review_pushed,
                review_backend={
                    "runner": runner, "model": model,
                    "backend_key": state_key, "variant": variant or "",
                    "reasoning_effort": reasoning_effort or "",
                },
                evidence_schema=(
                    _RETRY_SANDBOX_EVIDENCE_SCHEMA
                    if sandbox.replay_evidence_complete else 0),
                log=log)
            _status["closed_salvage_packages"] = closure_result["closed"]
            _status["host_pending_salvage_packages"] = closure_result["host_pending"]
        if hot_restart:
            if _status is not None:
                _status.update({"outcome": "changed", "reason": "运行时闭环 patch 已提交",
                                "changed_paths": review_paths})
            log("[llm] 运行时闭环变更已提交，重启大脑以加载…")
            return True
        if has_action:
            if _status is not None:
                _status.update({
                    "outcome": "completed",
                    "reason": "生产闭环 patch 已提交，当前 Brain 无需重载",
                    "changed_paths": review_paths,
                })
            log("[llm] 生产闭环变更已提交；不属于 Brain 加载路径，不触发热重启")
            return False
        if _status is not None:
            _status.update({"outcome": "documented", "reason": "复盘报告已提交，无需重启",
                            "changed_paths": review_paths})
        log("[llm] 复盘报告已提交；未改运行时代码，不触发 Brain 重启")
        return False
    except Exception as exc:
        reason = f"复盘宿主验收/提交异常：{exc}"
        if _status is not None:
            _status["reason"] = reason
        sandbox.stopped = sandbox.stopped or _review_stop_requested()
        save_failure(reason)
        log(f"[llm] {reason}；完整隔离现场已保留，真实工作树不做强制回滚")
        return False
    finally:
        autogit.set_review_active(False)
        if discard_verified_snapshot:
            _discard_sandbox_snapshot(sandbox, log=log)
            _discard_retained_sandbox(sandbox, log=log)


def maybe_review(agent, log=print) -> None:
    """【已废弃，保留兼容】同步复盘入口。新架构用 enqueue_review（异步不阻塞游玩）。"""
    cfg = load_llm_config()
    if not cfg.get("enabled"):
        return
    plan = _coerce_review_plan(resolve_review_plan(cfg, log=log), cfg)
    if not plan.available:
        return
    model, every, source = plan.model, plan.every_runs, plan.source
    runs = agent.know.stats["global"]["runs"]
    last = agent.know.progression.get("last_llm_review_run", 0)
    if runs - last < every:
        return
    executed = run_review(
        agent.know, log=log, model=model, every=every, source=source,
        runner=plan.runner, backend_key=plan.key, priority=plan.priority,
        variant=plan.variant, reasoning_effort=plan.reasoning_effort,
        approve_for_me=plan.approve_for_me, sandbox_mode=plan.sandbox)
    agent.know.progression["last_llm_review_run"] = runs
    agent.know.save()
    if executed:
        log("[llm] 复盘完成，回到主菜单后自动重启大脑以加载新策略/代码…")
        agent.request_restart = True


# ---------------------------------------------------------------------------
# 异步复盘队列（追及队列）——每局结束只入队，工作线程串行消化，游玩零等待
# ---------------------------------------------------------------------------

QUEUE_FILE = KNOWLEDGE_DIR / "review_queue.json"
_worker_started = False
_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_queue_lock = threading.RLock()
_QUEUE_IO_RETRIES = 8
_QUEUE_IO_RETRY_BASE_SECONDS = 0.01
_REVIEW_RETRY_BASE_SECONDS = 60
_REVIEW_RETRY_MAX_SECONDS = 15 * 60


class ReviewQueueError(RuntimeError):
    """The durable review queue cannot be safely read, validated, or replaced."""


def _empty_queue() -> dict:
    return {"pending": [], "reviewing": None}


def _validate_queue_item(item, label: str) -> None:
    if not isinstance(item, dict) or "run" not in item:
        raise ReviewQueueError(f"{label} is not a run object")
    run = item.get("run")
    retry_count = item.get("retry_count", 0)
    retry_after = item.get("retry_after", 0)
    if isinstance(run, bool) or not isinstance(run, int) or run <= 0:
        raise ReviewQueueError(f"{label}.run must be a positive integer")
    if (isinstance(retry_count, bool) or not isinstance(retry_count, int)
            or retry_count < 0):
        raise ReviewQueueError(f"{label}.retry_count must be a non-negative integer")
    if (isinstance(retry_after, bool) or not isinstance(retry_after, (int, float))
            or retry_after < 0 or not math.isfinite(float(retry_after))):
        raise ReviewQueueError(
            f"{label}.retry_after must be a finite non-negative number")
    every = item.get("every")
    if (every is not None and (isinstance(every, bool)
                              or not isinstance(every, int) or every <= 0)):
        raise ReviewQueueError(f"{label}.every must be a positive integer")
    for key in (
        "backend_key", "runner", "model", "variant", "reasoning_effort",
        "sandbox", "source", "retry_group", "queue_id", "replay_target",
    ):
        value = item.get(key)
        if value is not None and not isinstance(value, str):
            raise ReviewQueueError(f"{label}.{key} must be a string")
    priority = item.get("priority")
    if (priority is not None and (isinstance(priority, bool)
                                  or not isinstance(priority, int) or priority <= 0)):
        raise ReviewQueueError(f"{label}.priority must be a positive integer")
    for key in ("retry_same_model", "approve_for_me"):
        value = item.get(key)
        if value is not None and not isinstance(value, bool):
            raise ReviewQueueError(f"{label}.{key} must be a boolean")
    packages = item.get("salvage_packages")
    if (packages is not None and (not isinstance(packages, list)
                                  or any(not isinstance(value, str)
                                         for value in packages))):
        raise ReviewQueueError(f"{label}.salvage_packages must be a string list")
    attempts = item.get("salvage_attempts")
    if (attempts is not None and (not isinstance(attempts, list)
                                  or any(not isinstance(value, str)
                                         for value in attempts))):
        raise ReviewQueueError(f"{label}.salvage_attempts must be a string list")


def _queue_item_identity(item: dict) -> tuple:
    """A replay group may intentionally review a run already in the live queue."""
    queue_id = str(item.get("queue_id") or "")
    if queue_id:
        return ("queue_id", queue_id)
    group = str(item.get("retry_group") or "")
    if group:
        return ("retry_group", group, item.get("run"))
    return ("run", item.get("run"))


def _reviewing_items(reviewing: dict | None) -> list[dict]:
    """Read new full-item transactions while preserving legacy runs-only queues."""
    if not isinstance(reviewing, dict):
        return []
    items = reviewing.get("items")
    if isinstance(items, list):
        return [dict(item) for item in items if isinstance(item, dict)]
    stamp = reviewing.get("started", "")
    return [{"run": run, "time": stamp} for run in (reviewing.get("runs") or [])]


def _reviewing_matches_batch(reviewing: dict | None, batch: list[dict]) -> bool:
    """Use full identities for new transactions and runs only for legacy files."""
    if not isinstance(reviewing, dict):
        return False
    current = _reviewing_items(reviewing)
    if isinstance(reviewing.get("items"), list):
        return (tuple(_queue_item_identity(item) for item in current)
                == tuple(_queue_item_identity(item) for item in batch))
    return ([item.get("run") for item in current]
            == [item.get("run") for item in batch])


def _retry_affinity(item: dict) -> tuple | None:
    """Return the complete immutable runner/model binding for an attempted item."""
    if not item.get("retry_same_model"):
        return None
    model = str(item.get("model") or "")
    if not model:
        raise ReviewQueueError("retry_same_model item is missing its original model")
    return (
        str(item.get("runner") or "opencode"),
        model,
        str(item.get("source") or "preferred"),
        str(item.get("backend_key") or model),
        str(item.get("variant") or ""),
        str(item.get("reasoning_effort") or ""),
        bool(item.get("approve_for_me", False)),
        str(item.get("sandbox") or "workspace-write"),
        max(1, int(item.get("priority") or 1)),
    )


def _batch_retry_affinity(batch: list[dict]) -> tuple | None:
    """Prove that a sticky transaction has one runner/model, without silent fallback."""
    affinities = [_retry_affinity(item) for item in batch]
    sticky = [affinity for affinity in affinities if affinity is not None]
    if not sticky:
        return None
    if len(sticky) != len(batch):
        raise ReviewQueueError(
            "retry_same_model items cannot be mixed with an unattempted batch")
    if len(set(sticky)) != 1:
        raise ReviewQueueError(
            "retry_same_model batch contains conflicting runner/model bindings")
    return sticky[0]


def _refresh_sticky_approval(batch: list[dict], cfg: dict) -> bool:
    """Refresh execution approval only for an exact configured backend identity.

    This runs before affinity comparison so one replay group can normalize old
    and new approval snapshots.  Runner/model/variant/reasoning, backend key and
    sandbox must all match; sandbox is deliberately not migrated.
    """
    configured: dict[tuple[str, str, str, str, str, str], list[ReviewPlan]] = {}
    for candidate in review_plans_from_config(cfg):
        identity = (
            candidate.key,
            candidate.runner,
            candidate.model,
            candidate.variant or "",
            candidate.reasoning_effort or "",
            candidate.sandbox,
        )
        configured.setdefault(identity, []).append(candidate)

    refreshed = False
    for item in batch:
        if not item.get("retry_same_model"):
            continue
        model = str(item.get("model") or "")
        identity = (
            str(item.get("backend_key") or model),
            str(item.get("runner") or "opencode"),
            model,
            str(item.get("variant") or ""),
            str(item.get("reasoning_effort") or ""),
            str(item.get("sandbox") or "workspace-write"),
        )
        matches = configured.get(identity, [])
        if len(matches) != 1:
            continue
        approve_for_me = bool(matches[0].approve_for_me)
        if bool(item.get("approve_for_me", False)) != approve_for_me:
            item["approve_for_me"] = approve_for_me
            refreshed = True
    return refreshed


def _queue_item_ready_at(item: dict, now: float) -> float:
    """Combine per-attempt backoff with the bound preferred-model cooldown."""
    ready_at = float(item.get("retry_after", 0) or 0)
    affinity = _retry_affinity(item)
    if affinity is not None and affinity[2] == "preferred":
        ready_at = max(
            ready_at,
            now + _preferred_cooldown_remaining(affinity[3]),
        )
    return ready_at


def _select_review_batch(
    pending: list[dict], cap: int, now: float,
) -> tuple[list[int], float]:
    """Prefer a runnable retry transaction without splitting retry groups.

    Failed-package lineages are closure debt, so a runnable group wins even when
    recovery appended it behind newer live runs.  A blocked group is still skipped
    as a whole so fresh work can run.  Sticky ungrouped legacy items are only
    batched with the same runner/model affinity.  The returned indexes refer to
    ``pending``; the wait is the earliest future time at which any currently
    blocked transaction becomes runnable.
    """
    cap = max(1, int(cap))
    blocked_until: list[float] = []
    seen_groups: set[str] = set()

    # First pass: runnable failed-package transactions always close before newer
    # ordinary batches, regardless of where crash/hold recovery appended them.
    for index, item in enumerate(pending):
        group = str(item.get("retry_group") or "")
        if not group or group in seen_groups:
            continue
        seen_groups.add(group)
        indexes = [offset for offset, candidate in enumerate(pending)
                   if str(candidate.get("retry_group") or "") == group]
        group_items = [pending[offset] for offset in indexes]
        _batch_retry_affinity(group_items)
        ready_at = max(_queue_item_ready_at(candidate, now)
                       for candidate in group_items)
        if ready_at <= now:
            # Replay groups are durable transactions.  Queue construction caps
            # them at packet size; never split one after recovery even if a
            # legacy/corrupt config later lowers the live batching cap.
            return indexes, 0.0
        blocked_until.append(ready_at)

    # Second pass: collect the earliest compatible ordinary batch.  Group items
    # were handled atomically above and cannot leak into this batch.
    for index, item in enumerate(pending):
        if item.get("retry_group"):
            continue
        ready_at = _queue_item_ready_at(item, now)
        if ready_at > now:
            blocked_until.append(ready_at)
            continue

        affinity = _retry_affinity(item)
        indexes: list[int] = []
        for offset, candidate in enumerate(pending):
            if candidate.get("retry_group"):
                continue
            candidate_ready = _queue_item_ready_at(candidate, now)
            if candidate_ready > now:
                blocked_until.append(candidate_ready)
                continue
            candidate_affinity = _retry_affinity(candidate)
            if ((affinity is None and candidate_affinity is None)
                    or (affinity is not None and candidate_affinity == affinity)):
                indexes.append(offset)
                if len(indexes) >= cap:
                    break
        if indexes:
            return indexes, 0.0

    wait = min(blocked_until, default=now + 5.0) - now
    return [], min(30.0, max(1.0, wait))


def _restore_interrupted_reviewing(q: dict) -> list[dict]:
    """Move the exact interrupted transaction ahead of newer pending work."""
    if not q.get("reviewing"):
        return []
    recovered: list[dict] = []
    recovered_ids: set[tuple] = set()
    for item in _reviewing_items(q.get("reviewing")):
        identity = _queue_item_identity(item)
        if identity in recovered_ids:
            continue
        recovered.append(item)
        recovered_ids.add(identity)
    pending = [item for item in q.get("pending", [])
               if _queue_item_identity(item) not in recovered_ids]
    # The interrupted transaction was already selected before every pending item.
    # Restore that proven order.  The scheduler can still bypass it temporarily
    # when retry_after/model cooldown makes the whole transaction ineligible.
    q["pending"] = recovered + pending
    q["reviewing"] = None
    return recovered


def _validate_queue(payload) -> dict:
    """Validate the fields consumed by the worker without discarding unknown keys."""
    if not isinstance(payload, dict):
        raise ReviewQueueError("review queue root must be an object")
    pending = payload.get("pending")
    reviewing = payload.get("reviewing")
    if not isinstance(pending, list):
        raise ReviewQueueError("review queue pending must be a list")
    for index, item in enumerate(pending):
        _validate_queue_item(item, f"review queue pending[{index}]")
    if reviewing is not None:
        if not isinstance(reviewing, dict):
            raise ReviewQueueError("review queue reviewing must be null or an object")
        runs = reviewing.get("runs", [])
        if not isinstance(runs, list):
            raise ReviewQueueError("review queue reviewing.runs must be a list")
        for index, run in enumerate(runs):
            if isinstance(run, bool) or not isinstance(run, int) or run <= 0:
                raise ReviewQueueError(
                    f"review queue reviewing.runs[{index}] must be a positive integer")
        items = reviewing.get("items")
        if items is not None:
            if not isinstance(items, list):
                raise ReviewQueueError("review queue reviewing.items must be a list")
            for index, item in enumerate(items):
                _validate_queue_item(item, f"review queue reviewing.items[{index}]")
            if [item.get("run") for item in items] != runs:
                raise ReviewQueueError(
                    "review queue reviewing.items runs must match reviewing.runs")
    return payload


def _read_queue_text() -> str:
    last_error: OSError | None = None
    for attempt in range(_QUEUE_IO_RETRIES):
        try:
            return QUEUE_FILE.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise
        except OSError as exc:
            last_error = exc
            if attempt + 1 < _QUEUE_IO_RETRIES:
                time.sleep(_QUEUE_IO_RETRY_BASE_SECONDS * (attempt + 1))
    assert last_error is not None
    raise ReviewQueueError(f"cannot read review queue: {last_error}") from last_error


def _load_queue_unlocked() -> dict:
    try:
        raw = _read_queue_text()
    except FileNotFoundError:
        return _empty_queue()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Keep the original file untouched for diagnosis/recovery.  Treating it as
        # an empty queue lets the next save erase pending/reviewing evidence.
        raise ReviewQueueError(f"review queue contains invalid JSON: {exc}") from exc
    return _validate_queue(payload)


def _save_queue_unlocked(q: dict) -> None:
    _validate_queue(q)
    raw = (json.dumps(q, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    last_error: OSError | None = None
    for attempt in range(_QUEUE_IO_RETRIES):
        temp = QUEUE_FILE.with_name(
            f".{QUEUE_FILE.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
        try:
            with temp.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, QUEUE_FILE)
            return
        except OSError as exc:
            last_error = exc
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            if attempt + 1 < _QUEUE_IO_RETRIES:
                time.sleep(_QUEUE_IO_RETRY_BASE_SECONDS * (attempt + 1))
    assert last_error is not None
    raise ReviewQueueError(f"cannot save review queue: {last_error}") from last_error


def _load_queue() -> dict:
    with _queue_lock:
        return _load_queue_unlocked()


def _save_queue(q: dict) -> None:
    with _queue_lock:
        _save_queue_unlocked(q)


def requeue_review_runs(runs, log=print) -> list[int]:
    """Durably append explicitly recovered runs while the brain is stopped.

    This is intentionally permissive: an older preferred-model batch may be worth
    reviewing again even when newer runs are already queued.  Existing pending
    or reviewing entries are deduplicated, while newly recovered entries go to
    the tail so they cannot delay the live stream's freshest evidence.
    """
    normalized: list[int] = []
    seen_input: set[int] = set()
    for value in runs:
        run = int(value)
        if run <= 0 or run in seen_input:
            continue
        normalized.append(run)
        seen_input.add(run)

    added: list[int] = []
    with _queue_lock:
        q = _load_queue_unlocked()
        existing = {int(item.get("run")) for item in q.get("pending", [])
                    if item.get("run") is not None}
        existing.update(int(item["run"]) for item in
                        _reviewing_items(q.get("reviewing")) if item.get("run"))
        stamp = time.strftime("%Y-%m-%d %H:%M")
        for run in normalized:
            if run in existing:
                continue
            q["pending"].append({"run": run, "time": stamp})
            existing.add(run)
            added.append(run)
        if added:
            _save_queue_unlocked(q)
    if added:
        log(f"[llm] 已追回并重新入队历史复盘：第 {added} 局")
    else:
        log("[llm] 指定历史复盘均已在队列中，无需重复入队")
    return added


def _brain_session_is_active() -> bool:
    session_file = BASE_DIR / ".runtime" / "session.json"
    try:
        session = json.loads(session_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    return session.get("state") in {"starting", "running", "foreground"}


def _manifest_review_queue_fields(manifest: dict, cfg: dict) -> dict:
    """Restore one failed package's complete runner affinity without probing CLIs."""
    backend_key = str(manifest.get("backend_key") or "").strip()
    raw_model = str(manifest.get("model") or "").strip()
    configured = None
    for plan in review_plans_from_config(cfg):
        if backend_key and plan.key == backend_key:
            configured = plan
            break
        if raw_model and raw_model in {plan.model, plan.display_model}:
            configured = plan
            break

    runner = str(
        manifest.get("runner")
        or (configured.runner if configured else cfg.get("runner"))
        or "opencode").strip().lower()
    model = raw_model or (configured.model if configured else "")
    backend_key = backend_key or (configured.key if configured else model)
    variant = str(
        manifest.get("variant")
        or (configured.variant if configured else "")
        or "")
    reasoning = str(
        manifest.get("reasoning_effort")
        or (configured.reasoning_effort if configured else "")
        or "")
    source = str(
        manifest.get("source")
        or (configured.source if configured else "preferred"))
    try:
        priority = max(1, int(
            manifest.get("priority")
            or (configured.priority if configured else 1)))
    except (TypeError, ValueError):
        priority = configured.priority if configured else 1
    raw_approve = manifest.get("approve_for_me")
    approve_for_me = (
        raw_approve if isinstance(raw_approve, bool)
        else bool(configured.approve_for_me) if configured else False)
    sandbox_mode = str(
        manifest.get("sandbox")
        or (configured.sandbox if configured else "workspace-write"))
    try:
        every = max(1, int(
            manifest.get("every")
            or (configured.every_runs if configured else (
                cfg.get("preferred_every_runs", 1) if source == "preferred"
                else cfg.get("review_every_runs", 5)))))
    except (TypeError, ValueError):
        every = configured.every_runs if configured else (
            1 if source == "preferred" else 5)
    raw_sticky = manifest.get("retry_same_model")
    if not isinstance(raw_sticky, bool):
        model_started = manifest.get("provider_work_started")
        # Historical packages predate this field and were intentionally sticky.
        raw_sticky = model_started if isinstance(model_started, bool) else True

    return {
        "backend_key": backend_key,
        "priority": priority,
        "runner": runner,
        "model": model,
        "variant": variant,
        "reasoning_effort": reasoning,
        "approve_for_me": bool(approve_for_me),
        "sandbox": sandbox_mode,
        "every": every,
        "source": source,
        "retry_same_model": bool(raw_sticky and model),
    }


def _latest_replay_binding_manifest(
    target: str, target_manifest: dict, attempt_names,
) -> dict:
    """Use the latest valid attempt as executor affinity; keep target as evidence identity."""
    active = target_manifest
    for attempt_name in reversed(_normalize_salvage_package_names(attempt_names)):
        package = _salvage_package_path(attempt_name)
        if package is None:
            continue
        try:
            candidate = json.loads(
                (package / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(candidate, dict):
            continue
        candidate_target = str(candidate.get("replay_target") or target)
        if candidate_target != target:
            continue
        if any(key in candidate for key in (
                "model", "backend_key", "provider_work_started",
                "retry_same_model")):
            active = candidate
            break
    return active


def requeue_salvage_packages(package_names, log=print) -> dict[str, list[int]]:
    """Explicitly queue named failure packages for one-by-one model re-audit.

    This entry point is deliberately offline-only: callers first stop Brain via
    the unified lifecycle script, then name the packages to replay.  It never
    scans or auto-requeues every surviving package.  Each package receives its
    own stable ``retry_group`` so it cannot be mixed with live runs or another
    failure package in one model call.
    """
    if _brain_session_is_active():
        raise ReviewQueueError(
            "拒绝在线改写复盘队列：请先用 Stop-Agent.ps1 -KeepGame 停止 brain")
    requested = _normalize_salvage_package_names(package_names)
    queued: dict[str, list[int]] = {}
    queued_labels: dict[str, str] = {}
    cfg = load_llm_config()
    prepared: list[tuple[str, list[int], dict, bool]] = []
    prepared_roots: set[str] = set()
    for requested_name in requested:
        name = requested_name
        package = _salvage_package_path(requested_name)
        if package is None:
            log(f"[llm] 指定失败包不存在，跳过：{requested_name}")
            continue
        # Keep the controlled Stop window O(1): only publish queue/manifest
        # intent here.  Raw-clone indexing and patch derivation run lazily after
        # Start, inside the normal Brain worker.
        manifest = json.loads(
            (package / "manifest.json").read_text(encoding="utf-8"))
        existing_target = _normalize_salvage_package_names([
            manifest.get("replay_target")])
        if (manifest.get("replay_role") == "attempt_evidence"
                and existing_target and existing_target[0] != requested_name):
            root_name = existing_target[0]
            root_package = _salvage_package_path(root_name)
            if root_package is None:
                log(f"[llm] attempt {requested_name} 的 target {root_name} 不存在；"
                    "保留现场且不擅自提升为第二 target")
                continue
            name = root_name
            package = root_package
            manifest = json.loads(
                (package / "manifest.json").read_text(encoding="utf-8"))
            log(f"[llm] 指定的是 attempt {requested_name}；按 lineage 唤醒 target {name}")
        if name in prepared_roots:
            continue
        prepared_roots.add(name)
        if manifest.get("retry_resolution_state") in {
                "claimed_pending_code_push", "code_upstream_confirmed",
                "quarantined_pending_ledger",
                "ledger_final_upstream", "done"}:
            log(f"[llm] 失败包已有 {_resolution_backend_label(manifest)} 结论，"
                f"交由宿主闭环恢复而不重复消耗模型：{name}")
            continue
        manifest = dict(manifest)
        manifest.update({
            "replay_enqueue_pending": True,
            "replay_target": name,
            "replay_role": "target",
        })
        manifest.setdefault("replay_attempt_packages", [])
        _publish_manifest_update(package, manifest)
        runs: list[int] = []
        seen_runs: set[int] = set()
        for value in manifest.get("batch_runs") or []:
            try:
                run = int(value)
            except (TypeError, ValueError):
                continue
            if run > 0 and run not in seen_runs:
                runs.append(run)
                seen_runs.add(run)
        evidence_only = not runs
        if evidence_only:
            for value in (manifest.get("current_run"), manifest.get("run")):
                try:
                    fallback_run = int(value)
                except (TypeError, ValueError):
                    continue
                if fallback_run > 0:
                    runs = [fallback_run]
                    break
        if not runs:
            try:
                stats = json.loads((KNOWLEDGE_DIR / "stats.json").read_text(encoding="utf-8"))
                fallback_run = int(stats.get("global", {}).get("runs", 0))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                fallback_run = 0
            runs = [max(1, fallback_run)]
        prepared.append((name, runs, manifest, evidence_only))

    if not prepared:
        return queued
    with _queue_lock:
        q = _load_queue_unlocked()
        existing_groups = {
            str(item.get("retry_group") or "")
            for item in [*q.get("pending", []), *_reviewing_items(q.get("reviewing"))]
            if item.get("retry_group")
        }
        stamp = time.strftime("%Y-%m-%d %H:%M")
        for name, runs, manifest, evidence_only in prepared:
            if name in existing_groups:
                log(f"[llm] 失败包已在重审队列中，无需重复入队：{name}")
                continue
            lineage = _normalize_salvage_package_names(
                manifest.get("replay_attempt_packages") or [])
            active_manifest = _latest_replay_binding_manifest(
                name, manifest, lineage)
            affinity = _manifest_review_queue_fields(active_manifest, cfg)
            for run in runs:
                item = {
                    "run": run,
                    "time": str(manifest.get("time") or stamp),
                    "retry_group": name,
                    "replay_target": name,
                    "salvage_packages": [name],
                    "salvage_attempts": _normalize_salvage_package_names(
                        manifest.get("replay_attempt_packages") or []),
                    "evidence_only": evidence_only,
                    **affinity,
                }
                q["pending"].append(item)
            existing_groups.add(name)
            queued[name] = list(runs)
            queued_labels[name] = _review_backend_label(affinity)
        if queued:
            _save_queue_unlocked(q)
    for name, runs in queued.items():
        log(f"[llm] 已将失败包交回 {queued_labels.get(name, '原绑定复盘后端')} "
            f"独立重审队列：{name}（第 {runs} 局）")
    return queued


def _manifest_replay_runs(manifest: dict) -> tuple[list[int], bool]:
    """Return queue-compatible runs; old runless packages use evidence-only mode."""
    runs: list[int] = []
    for value in manifest.get("batch_runs") or []:
        try:
            run = int(value)
        except (TypeError, ValueError):
            continue
        if run > 0 and run not in runs:
            runs.append(run)
    evidence_only = not runs
    if not runs:
        for value in (manifest.get("current_run"), manifest.get("run")):
            try:
                run = int(value)
            except (TypeError, ValueError):
                continue
            if run > 0:
                runs = [run]
                break
    if not runs:
        try:
            stats = json.loads((KNOWLEDGE_DIR / "stats.json").read_text(encoding="utf-8"))
            run = int(stats.get("global", {}).get("runs", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            run = 0
        runs = [max(1, run)]
    return runs, evidence_only


def _review_hold_packages() -> list[tuple[Path, Path, dict]]:
    """Return (container, package, manifest) from the ignored hold root only."""
    root = _review_hold_root()
    if not root.is_dir():
        return []
    found: list[tuple[Path, Path, dict]] = []
    try:
        containers = sorted(
            (path for path in root.iterdir()
             if path.is_dir() and not path.name.startswith(".")),
            key=lambda path: path.name)
    except OSError:
        return []
    for container in containers:
        direct_manifest = container / "manifest.json"
        candidates = [container] if direct_manifest.is_file() else []
        if not candidates:
            try:
                candidates = sorted(
                    (path for path in container.iterdir()
                     if path.is_dir() and not path.name.startswith(".")),
                    key=lambda path: path.name)
            except OSError:
                continue
        for package in candidates:
            manifest_path = package / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    continue
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            found.append((container, package, manifest))
    return found


def _review_hold_contains_package(package_name: str) -> bool:
    names = _normalize_salvage_package_names([package_name])
    return bool(names) and any(
        package.name == names[0] for _container, package, _manifest
        in _review_hold_packages())


def _hold_tree_inventory(root: Path) -> dict[str, tuple[str, int | str]]:
    """Inventory one exact held package; this is not a repository fingerprint."""
    inventory: dict[str, tuple[str, int | str]] = {}
    for walk_root, directories, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(walk_root)
        kept_directories: list[str] = []
        for name in sorted(directories):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                inventory[relative] = ("symlink", os.readlink(path))
            else:
                inventory[relative] = ("dir", 0)
                kept_directories.append(name)
        directories[:] = kept_directories
        for name in sorted(files):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                inventory[relative] = ("symlink", os.readlink(path))
            else:
                inventory[relative] = ("file", path.stat().st_size)
    return inventory


def _restore_review_hold_package(source: Path, log=print) -> Path | None:
    """Resume-copy one whole held package, then atomically publish its exact name."""
    name = source.name
    final = SALVAGE_ROOT / name
    if final.is_dir():
        return final
    temp = SALVAGE_ROOT / f".hold-restore-{name}"
    try:
        SALVAGE_ROOT.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source, temp, dirs_exist_ok=True, symlinks=True,
            ignore_dangling_symlinks=True, copy_function=_copy_snapshot_file)
        if _hold_tree_inventory(source) != _hold_tree_inventory(temp):
            raise OSError("hold 恢复后的逐文件类型/大小清单不一致")
        if final.exists():
            # Another recovery pass won the exact publish race.  Keep its package;
            # the partial temp remains resumable and will be ignored by scanners.
            return final if final.is_dir() else None
        _replace_with_retry(temp, final)
        log(f"[llm] 已从 review_hold 原子恢复完整失败包：{name}")
        return final
    except _ReviewStopped:
        log(f"[llm] 停止期间暂停恢复 hold；部分副本留待下次续传：{name}")
        return None
    except Exception as exc:
        log(f"[llm] review_hold 恢复失败；hold 与部分副本均保留：{name}（{exc}）")
        return None


def _manifest_has_full_replay_receipt(manifest: dict) -> bool:
    try:
        schema = int(manifest.get("retry_resolution_evidence_schema") or 0)
    except (TypeError, ValueError):
        schema = 0
    return bool(
        manifest.get("retry_resolution_evidence_complete") is True
        and schema >= _RETRY_SANDBOX_EVIDENCE_SCHEMA
        and manifest.get("retry_resolution") in {"integrated", "no_valid_change"}
        and manifest.get("retry_resolution_commit"))


def _review_hold_closure_path(target: str) -> Path | None:
    names = _normalize_salvage_package_names([target])
    if not names:
        return None
    return _review_hold_root() / _REVIEW_HOLD_CLOSURE_DIR / f"{names[0]}.json"


def _read_review_hold_closure(target: str) -> dict:
    path = _review_hold_closure_path(target)
    if path is None:
        return {}
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        return receipt if isinstance(receipt, dict) else {}
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _active_replay_lineage_names(target: str) -> set[str]:
    """Return active, readable salvage packages currently bound to one target."""
    names: set[str] = set()
    if not SALVAGE_ROOT.is_dir():
        return names
    try:
        packages = list(SALVAGE_ROOT.iterdir())
    except OSError:
        return names
    for package in packages:
        if (not package.is_dir() or package.name.startswith(".")
                or package.name.startswith(_CLOSED_SALVAGE_PREFIX)):
            continue
        if package.name == target:
            names.add(package.name)
            continue
        try:
            manifest = json.loads((
                package / "manifest.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError,
                json.JSONDecodeError):
            continue
        normalized = _normalize_salvage_package_names([
            manifest.get("replay_target") or package.name])
        if normalized == [target]:
            names.add(package.name)
    return names


def _review_hold_closure_is_confirmed(target: str, receipt: dict | None = None) -> bool:
    """Accept only a full-evidence hold tombstone whose exact ledger row is upstream."""
    receipt = receipt if isinstance(receipt, dict) else _read_review_hold_closure(target)
    names = _normalize_salvage_package_names([target])
    if not names or receipt.get("target") != names[0]:
        return False
    try:
        schema = int(receipt.get("schema") or 0)
        evidence_schema = int(receipt.get("evidence_schema") or 0)
    except (TypeError, ValueError):
        return False
    resolution = str(receipt.get("resolution") or "")
    commit = str(receipt.get("commit") or "")
    ledger_status = str(receipt.get("ledger_status") or "")
    lineage = _normalize_salvage_package_names(receipt.get("lineage") or [])
    held_lineage = {
        package.name
        for _container, package, manifest in _review_hold_packages()
        if _normalize_salvage_package_names([
            manifest.get("replay_target") or package.name]) == names
    }
    active_lineage = _active_replay_lineage_names(names[0])
    if (schema != _REVIEW_HOLD_CLOSURE_SCHEMA
            or receipt.get("evidence_complete") is not True
            or evidence_schema < _RETRY_SANDBOX_EVIDENCE_SCHEMA
            or resolution not in {"integrated", "no_valid_change"}
            or len(commit) < 8 or names[0] not in lineage
            or not held_lineage.issubset(lineage)
            or not active_lineage.issubset(lineage)
            or "并闭环" not in ledger_status
            or f"`{commit[:8]}`" not in ledger_status):
        return False
    return bool(
        _upstream_contains_commit(commit)
        and _upstream_ledger_has_exact_status(names[0], ledger_status))


def _confirmed_review_hold_closures() -> dict[str, dict]:
    """Return remotely confirmed hold targets and their durable receipts."""
    targets = _normalize_salvage_package_names([
        manifest.get("replay_target") or package.name
        for _container, package, manifest in _review_hold_packages()
    ])
    confirmed: dict[str, dict] = {}
    for target in targets:
        receipt = _read_review_hold_closure(target)
        if not _review_hold_closure_is_confirmed(target, receipt):
            continue
        confirmed[target] = receipt
    return confirmed


def _review_hold_lineage_closure_is_confirmed(package_name: str) -> bool:
    """Resolve an empty target/attempt quarantine through its target tombstone."""
    normalized = _normalize_salvage_package_names([package_name])
    if not normalized:
        return False
    name = normalized[0]
    root = _review_hold_root() / _REVIEW_HOLD_CLOSURE_DIR
    try:
        paths = sorted(root.glob("*.json")) if root.is_dir() else []
    except OSError:
        return False
    direct = _review_hold_closure_path(name)
    if direct is not None and direct.is_file():
        paths = [direct, *(path for path in paths if path != direct)]
    for path in paths:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError,
                json.JSONDecodeError):
            continue
        if not isinstance(receipt, dict):
            continue
        lineage = _normalize_salvage_package_names(receipt.get("lineage") or [])
        target = str(receipt.get("target") or "")
        if name in lineage and _review_hold_closure_is_confirmed(target, receipt):
            return True
    return False


def _publish_review_hold_closure(
    original_name: str, manifest: dict, ledger_status: str, log=print,
) -> bool:
    """Publish the hold tombstone after code and the exact final ledger are upstream."""
    normalized = _normalize_salvage_package_names([
        manifest.get("retry_resolution_target")
        or manifest.get("replay_target") or original_name])
    if not normalized:
        return False
    target = normalized[0]
    # Attempts close first.  The target is the lineage commit point and alone
    # publishes the receipt which suppresses restoration of the whole hold group.
    if original_name != target:
        return True
    records = [
        (container, package, held_manifest)
        for container, package, held_manifest in _review_hold_packages()
        if _normalize_salvage_package_names([
            held_manifest.get("replay_target") or package.name]) == [target]
    ]
    if not records:
        return True
    if not _upstream_ledger_has_exact_status(target, ledger_status):
        log(f"[llm] review_hold 闭环清单尚未精确确认远端；保留 target quarantine：{target}")
        return False
    if not _manifest_has_full_replay_receipt(manifest):
        log(f"[llm] review_hold 闭环缺少完整证据 schema；保留 target quarantine：{target}")
        return False
    held_target = next(
        (held_manifest for _container, package, held_manifest in records
         if package.name == target), {})
    lineage = _normalize_salvage_package_names([
        target,
        *(manifest.get("retry_resolution_lineage") or []),
        *(manifest.get("replay_attempt_packages") or []),
        *(held_target.get("replay_attempt_packages") or []),
        *(package.name for _container, package, _held_manifest in records),
    ])
    queue_ids = list(dict.fromkeys(
        str(value) for value in [
            *(manifest.get("replay_queue_ids") or []),
            *(held_target.get("replay_queue_ids") or []),
        ] if str(value)))
    receipt = {
        "schema": _REVIEW_HOLD_CLOSURE_SCHEMA,
        "target": target,
        "lineage": lineage,
        "resolution": str(manifest.get("retry_resolution") or ""),
        "commit": str(manifest.get("retry_resolution_commit") or ""),
        "evidence_complete": True,
        "evidence_schema": int(
            manifest.get("retry_resolution_evidence_schema") or 0),
        "ledger_status": ledger_status,
        "ledger_confirmed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "queue_ids": queue_ids,
    }
    path = _review_hold_closure_path(target)
    if path is None:
        return False
    temp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        _replace_with_retry(temp, path)
        return True
    except OSError as exc:
        log(f"[llm] review_hold 闭环回执发布失败；保留 target quarantine：{target}（{exc}）")
        return False
    finally:
        temp.unlink(missing_ok=True)


def _reset_hold_manifest_for_full_replay(
    package: Path,
    held_manifest: dict,
    *,
    target: str,
    role: str,
    attempts: list[str],
    hold_container: Path,
) -> bool:
    """Invalidate only pre-full-evidence receipts and restore durable lineage."""
    try:
        active = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(active, dict):
            return False
        if _manifest_has_full_replay_receipt(active):
            return False
        before = dict(active)
        for key in list(active):
            if key.startswith("retry_resolution"):
                active.pop(key, None)
        active.update({
            "replay_enqueue_pending": True,
            "replay_target": target,
            "replay_role": role,
            "review_hold_requires_evidence_schema": _RETRY_SANDBOX_EVIDENCE_SCHEMA,
            "review_hold_recovered_at": (
                active.get("review_hold_recovered_at")
                or time.strftime("%Y-%m-%d %H:%M:%S")),
            "review_hold_source": (
                f"{hold_container.name}/{package.name}"),
        })
        if role == "target":
            active["replay_attempt_packages"] = list(attempts)
        else:
            active.pop("replay_attempt_packages", None)
        # A held manifest predates some later materialization fields.  Keep the
        # active package's complete evidence metadata, while filling any original
        # queue identity that an older closure may have removed.
        for key in (
            "batch_runs", "current_run", "run", "time", "pre_head", "model",
            "runner", "backend_key", "priority", "variant", "reasoning_effort",
            "approve_for_me", "sandbox", "retry_same_model",
            "provider_work_started", "source", "every", "reason", "failure_kind",
            "replay_queue_ids",
        ):
            if key not in active and key in held_manifest:
                active[key] = held_manifest[key]
        if active != before:
            _publish_manifest_update(package, active)
            return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return False


def _recover_review_holds(log=print) -> list[str]:
    """Restore operator-held lineages deleted/closed by a pre-fix review host."""
    records = _review_hold_packages()
    if not records or _review_stop_requested():
        return []
    groups: dict[str, list[tuple[Path, Path, dict]]] = {}
    for container, package, manifest in records:
        normalized = _normalize_salvage_package_names([
            manifest.get("replay_target") or package.name])
        if not normalized:
            continue
        groups.setdefault(normalized[0], []).append((container, package, manifest))

    recovered: list[str] = []
    for target, lineage_records in groups.items():
        if _review_stop_requested():
            break
        if _review_hold_closure_is_confirmed(target):
            continue
        # A full-evidence receipt already in quarantine is a valid in-flight host
        # closure.  Do not resurrect it while ledger cleanup is proceeding.
        quarantine = SALVAGE_ROOT / f"{_CLOSED_SALVAGE_PREFIX}{target}"
        try:
            quarantine_manifest = json.loads((
                quarantine / "manifest.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            quarantine_manifest = {}
        if _manifest_has_full_replay_receipt(quarantine_manifest):
            continue

        by_name = {package.name: (container, package, manifest)
                   for container, package, manifest in lineage_records}
        target_record = by_name.get(target)
        if target_record is None:
            log(f"[llm] review_hold lineage 缺少 target 原件，保持 hold：{target}")
            continue
        target_manifest = target_record[2]
        declared_attempts = _normalize_salvage_package_names(
            target_manifest.get("replay_attempt_packages") or [])
        discovered_attempts = _normalize_salvage_package_names([
            name for name, (_container, _package, manifest) in by_name.items()
            if name != target and manifest.get("replay_role") == "attempt_evidence"
        ])
        attempts = _normalize_salvage_package_names([
            *declared_attempts, *discovered_attempts])
        missing = [name for name in attempts if name not in by_name]
        if missing:
            log("[llm] review_hold lineage 缺少声明的 attempt 原件，整组保持 hold："
                f"target={target}, missing={missing}")
            continue
        ordered = [target, *attempts]
        for name in ordered:
            if _review_stop_requested():
                break
            container, source, held_manifest = by_name[name]
            active = SALVAGE_ROOT / name
            was_missing = not active.is_dir()
            if not active.is_dir():
                active = _restore_review_hold_package(source, log=log) or active
            if not active.is_dir():
                continue
            role = "target" if name == target else "attempt_evidence"
            changed = _reset_hold_manifest_for_full_replay(
                active, held_manifest, target=target, role=role,
                attempts=attempts, hold_container=container)
            if was_missing or changed:
                recovered.append(name)
        if (any(name in recovered for name in ordered)
                and all((SALVAGE_ROOT / name).is_dir() for name in ordered)):
            log(f"[llm] review_hold lineage 已恢复并等待完整证据 "
                f"{_review_backend_label(target_manifest)} 重审："
                f"target={target}, attempts={attempts}")
    return recovered


def _recover_salvage_replay_queue(log=print) -> None:
    """Reconcile atomically published packages with the durable target queue.

    Package publication deliberately precedes queue/ledger network work.  The
    manifest therefore carries the target and original queue ids; after any crash
    this scan converts the interrupted transaction (or creates one missing group)
    into exactly one target job and attaches every later failure as evidence.
    """
    confirmed_closures = _confirmed_review_hold_closures()
    resolved_targets = {
        target: {
            str(value) for value in (receipt.get("queue_ids") or []) if str(value)
        }
        for target, receipt in confirmed_closures.items()
    }
    resolved_lineages = {
        target: set(_normalize_salvage_package_names(receipt.get("lineage") or []))
        for target, receipt in confirmed_closures.items()
    }
    if not SALVAGE_ROOT.is_dir() and not resolved_targets:
        return
    targets: dict[str, tuple[Path, dict]] = {}
    attempts: dict[str, list[str]] = {}
    queue_ids: dict[str, set[str]] = {}
    packages = (sorted(SALVAGE_ROOT.iterdir(), key=lambda path: path.name)
                if SALVAGE_ROOT.is_dir() else [])
    for package in packages:
        manifest_path = package / "manifest.json"
        if (not package.is_dir() or package.name.startswith(_CLOSED_SALVAGE_PREFIX)
                or not manifest_path.is_file()):
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if not manifest.get("replay_enqueue_pending"):
            continue
        normalized = _normalize_salvage_package_names([
            manifest.get("replay_target") or package.name])
        if not normalized:
            continue
        target = normalized[0]
        manifest_queue_ids = {
            str(value) for value in (manifest.get("replay_queue_ids") or [])
            if str(value)}
        if target in resolved_targets:
            resolved_targets[target].update(manifest_queue_ids)
            continue
        if manifest.get("retry_resolution_state") in {
                "claimed_pending_code_push", "code_upstream_confirmed",
                "quarantined_pending_ledger", "ledger_final_upstream", "done"}:
            resolved_targets.setdefault(target, set()).update(manifest_queue_ids)
            resolved_lineages.setdefault(target, set()).update(
                _normalize_salvage_package_names([
                    target,
                    package.name,
                    *(manifest.get("retry_resolution_lineage") or []),
                    *(manifest.get("replay_attempt_packages") or []),
                ]))
            continue
        queue_ids.setdefault(target, set()).update(manifest_queue_ids)
        if package.name == target or manifest.get("replay_role") == "target":
            targets[target] = (package, manifest)
        else:
            attempts.setdefault(target, []).append(package.name)

    if not targets and not resolved_targets:
        return
    target_attempts: dict[str, list[str]] = {}
    with _queue_lock:
        q = _load_queue_unlocked()
        reviewing = q.get("reviewing")
        reviewing_items = _reviewing_items(reviewing)
        changed = False
        cfg = load_llm_config()
        if resolved_targets:
            def is_resolved_item(item: dict) -> bool:
                item_target = str(item.get("replay_target") or "")
                item_group = str(item.get("retry_group") or "")
                item_queue_id = str(item.get("queue_id") or "")
                item_lineage = set(_normalize_salvage_package_names([
                    *(item.get("salvage_packages") or []),
                    *(item.get("salvage_attempts") or []),
                ]))
                return any(
                    (item_target == target or item_group == target
                     or (item_queue_id in ids if ids else False))
                    and item_lineage.issubset(resolved_lineages.get(target, set()))
                    for target, ids in resolved_targets.items())

            pending_before = len(q.get("pending", []))
            q["pending"] = [item for item in q.get("pending", [])
                            if not is_resolved_item(item)]
            filtered_reviewing = [item for item in reviewing_items
                                  if not is_resolved_item(item)]
            if (len(q["pending"]) != pending_before
                    or len(filtered_reviewing) != len(reviewing_items)):
                reviewing_items = filtered_reviewing
                changed = True
                log("[llm] 已按耐久复盘模型回执消费遗留 replay 队列事务："
                    f"{sorted(resolved_targets)}")
        for target, (_package, manifest) in targets.items():
            lineage = _normalize_salvage_package_names([
                *(manifest.get("replay_attempt_packages") or []),
                *attempts.get(target, []),
            ])
            lineage = [name for name in lineage if name != target]
            target_attempts[target] = lineage
            ids = queue_ids.get(target, set())
            active_manifest = _latest_replay_binding_manifest(
                target, manifest, lineage)
            affinity = _manifest_review_queue_fields(active_manifest, cfg)

            def belongs(item: dict) -> bool:
                return (str(item.get("replay_target") or "") == target
                        or str(item.get("retry_group") or "") == target
                        or (str(item.get("queue_id") or "") in ids
                            if ids else False))

            matched = False
            for collection in (q.get("pending", []), reviewing_items):
                for item in collection:
                    if not belongs(item):
                        continue
                    matched = True
                    desired = {
                        "retry_group": target,
                        "replay_target": target,
                        "salvage_packages": [target],
                        "salvage_attempts": list(lineage),
                        **affinity,
                    }
                    if any(item.get(key) != value for key, value in desired.items()):
                        item.update(desired)
                        changed = True
            if not matched:
                runs, evidence_only = _manifest_replay_runs(manifest)
                stamp = str(manifest.get("time") or time.strftime("%Y-%m-%d %H:%M"))
                for run in runs:
                    item = {
                        "run": run,
                        "time": stamp,
                        "retry_group": target,
                        "replay_target": target,
                        "salvage_packages": [target],
                        "salvage_attempts": list(lineage),
                        "evidence_only": evidence_only,
                        **affinity,
                    }
                    q["pending"].append(item)
                changed = True
                log(f"[llm] 已从失败包原子意图恢复 "
                    f"{_review_backend_label(affinity)} target：{target}（第 {runs} 局）")
        if isinstance(reviewing, dict) and isinstance(reviewing.get("items"), list):
            if not reviewing_items:
                q["reviewing"] = None
            else:
                reviewing["items"] = reviewing_items
                reviewing["runs"] = [item["run"] for item in reviewing_items]
                groups = {str(item.get("retry_group") or "") for item in reviewing_items}
                if len(groups) == 1:
                    reviewing["retry_group"] = next(iter(groups))
        if changed:
            _save_queue_unlocked(q)

    # Queue durability comes first.  This secondary index is helpful but can be
    # reconstructed from attempt manifests after a crash at any instruction.
    for target, lineage in target_attempts.items():
        package, manifest = targets[target]
        if manifest.get("replay_attempt_packages") == lineage:
            continue
        try:
            updated = dict(manifest)
            updated["replay_attempt_packages"] = lineage
            _publish_manifest_update(package, updated)
        except OSError as exc:
            log(f"[llm] target attempt 索引暂未回写（队列已耐久）：{target}（{exc}）")


def enqueue_review(agent, log=print) -> None:
    """agent.py 每局结束后调用：按节奏入队复盘请求并确保工作线程存活。

    绝不阻塞游玩主循环——复盘由工作线程异步执行；若一局结束时上一场复盘还没完，
    请求在队列里累积，下一场复盘会一次性分析多局（追及）。
    """
    cfg = load_llm_config()
    if not cfg.get("enabled"):
        return
    runs = agent.know.stats["global"]["runs"]
    # 游戏线程只读取配置并耐久入队；绝不在这里 spawn `opencode models`、
    # `codex login status` 或任何其他外部探测。真正的后端计划由 worker 在
    # 认领 fresh 事务后解析并原子写回 reviewing。
    plans = review_plans_from_config(cfg)
    if not plans:
        return
    queued_plan = plans[0]
    every = queued_plan.every_runs
    source = "queued"
    last_ok = agent.know.progression.get("last_successful_review_run", 0)
    starve_every = max(1, int(cfg.get("review_every_runs", 5)))
    starved = runs - last_ok >= starve_every
    last = agent.know.progression.get("last_llm_review_run", 0)
    if runs - last < every:
        return
    progression_key = "last_llm_review_run"

    # Queue durability is the commit point.  Advancing cadence markers before a
    # failed queue read/write silently skips this run until the next interval.
    # Existing pending/reviewing data must remain authoritative on every failure.
    try:
        with _queue_lock:
            q = _load_queue_unlocked()
            reviewing_runs = set((q.get("reviewing") or {}).get("runs") or [])
            already_queued = runs in reviewing_runs or any(
                item.get("run") == runs for item in q["pending"])
            if not already_queued:
                q["pending"].append({
                    "run": runs, "time": time.strftime("%Y-%m-%d %H:%M"),
                    **queued_plan.as_queue_fields(),
                    "source": source,
                })
                _save_queue_unlocked(q)
    except (ReviewQueueError, OSError) as exc:
        log(f"[llm] 复盘队列持久化失败，保留原队列且不推进节奏标记：{exc}")
        return

    agent.know.progression[progression_key] = runs
    agent.know.progression["last_review_attempt_source"] = source
    agent.know.save()
    starve_note = (f"（距上次成功复盘 {runs - last_ok} 局，积压追及）"
                   if starved else "")
    log(f"[llm] 复盘请求已入队（第{runs}局，worker待选后端，"
        f"待消化 {len(q['pending'])} 批{starve_note}），游玩不等待")
    if not _review_stop_requested():
        _ensure_worker(agent, log)


def _ensure_worker(agent, log) -> None:
    global _worker_started, _worker_thread
    if _review_stop_requested():
        return
    with _worker_lock:
        if _worker_started:
            return
        try:
            thread = threading.Thread(
                target=_worker_loop, args=(agent, log), daemon=True,
                name="llm-review-worker")
            _worker_thread = thread
            _worker_started = True
            thread.start()
        except Exception as exc:
            # Thread construction/start can fail under transient OS resource
            # pressure.  Never leave the latch set without a live supervisor;
            # the next enqueue/startup probe must be able to retry.
            _worker_started = False
            _worker_thread = None
            log(f"[llm] 异步复盘工作线程启动失败；保留队列供下次自愈：{exc}")
            return
    log("[llm] 异步复盘工作线程已启动")


def _salvage_recovery_needed() -> bool:
    """Cheap startup probe for host work that exists outside review_queue.json."""
    if _review_hold_packages():
        return True
    if not SALVAGE_ROOT.is_dir():
        return False
    host_states = {
        "claimed_pending_code_push", "code_upstream_confirmed",
        "quarantined_pending_ledger", "ledger_final_upstream",
    }
    try:
        for package in SALVAGE_ROOT.iterdir():
            if not package.is_dir():
                continue
            if package.name.startswith(_CLOSED_SALVAGE_PREFIX):
                return True
            if ((package / "raw_sandbox_pointer.txt").is_file()
                    or (package / "snapshot_pointer.txt").is_file()):
                return True
            manifest_path = package / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if (manifest.get("replay_enqueue_pending")
                    or manifest.get("retry_resolution_state") in host_states):
                return True
    except OSError:
        return False
    return False


def resume_review_queue(agent, log=print) -> None:
    """Resume queued/interrupted reviews immediately after brain startup."""
    if _review_stop_requested():
        return
    llm_enabled = bool(load_llm_config().get("enabled"))
    host_recovery = _salvage_recovery_needed()
    try:
        with _queue_lock:
            q = _load_queue_unlocked()
            has_work = bool(q.get("pending") or q.get("reviewing"))
    except (ReviewQueueError, OSError) as exc:
        log(f"[llm] 复盘队列暂不可读；保留原文件并交给 worker 自愈：{exc}")
        # The supervised worker owns the long-lived retry loop.  Start it when
        # paid review is enabled, or when an ignored salvage manifest proves
        # host-only receipt/ledger/quarantine work exists.  Otherwise a lock
        # lasting beyond the short bootstrap retries would strand all recovery
        # until another game happens to enqueue work.
        if llm_enabled or host_recovery:
            _ensure_worker(agent, log)
        return
    if host_recovery or (llm_enabled and has_work):
        _ensure_worker(agent, log)


def shutdown_worker(log=print, timeout: float = 30.0) -> bool:
    """Cancel and join the optional review worker before Knowledge is saved."""
    _worker_stop.set()
    thread = _worker_thread
    if thread is None or thread is threading.current_thread():
        return True
    thread.join(max(0.0, timeout))
    if thread.is_alive():
        log(f"[llm] 复盘工作线程在 {timeout:.0f}s 内未退出；交由统一 Stop 的精确兜底处理")
        return False
    return True


@dataclass
class SandboxReviewResult:
    rc: int = -1
    out: str = ""
    timed_out: bool = False
    stalled: bool = False
    stopped: bool = False
    paths: tuple[str, ...] = ()
    patch: bytes = b""
    conclusion: str = ""
    error: str = ""
    # ``None`` means the host never ran selfcheck (for example, the model made
    # no accepted change).  Do not turn "not run" into a successful receipt.
    selfcheck_ok: bool | None = None
    failure_code: str = ""
    diagnostic_report: str = ""
    # WIP 与已通过验收、可自动合入的 patch 严格分离。失败现场包含全部
    # 工作树改动（含越界/ignored），只供人工分析，绝不会被自动应用。
    wip_patch: bytes = b""
    wip_paths: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    # 自检/导入产生的缓存仍进入全量取证包，但既不是模型源码成果，也不能
    # 被当成越界提交误杀已验证的源码 patch。
    artifact_paths: tuple[str, ...] = ()
    online_paths: tuple[str, ...] = ()
    unexpected_paths: tuple[str, ...] = ()
    sibling_paths: tuple[str, ...] = ()
    snapshot_dir: str = ""
    snapshot_complete: bool = False
    retained_sandbox_dir: str = ""
    salvage_saved: str = ""
    provider_metrics: dict = field(default_factory=dict)
    provider_work_started: bool = False
    provider_transcript_rel: str = ""
    review_attempt_id: str = ""
    review_sandbox_name: str = ""
    review_attempt_receipt_schema: int = 0
    # Failed-package receipts are authoritative only when the target and every
    # attempt were mounted into this clone and survived the post-run integrity
    # check.  The bounded prompt excerpt is a navigation summary, not evidence
    # completeness.
    replay_evidence_requested: bool = False
    replay_evidence_complete: bool = True
    replay_evidence_error: str = ""
    replay_evidence_index: str = ""
    replay_evidence_model_started: bool = False


def _git_env_with_long_paths(source: dict[str, str] | None = None) -> dict[str, str]:
    """Enable Git for deep preserved sandboxes without changing repo config."""
    env = dict(os.environ if source is None else source)
    try:
        count = max(0, int(env.get("GIT_CONFIG_COUNT", "0")))
    except (TypeError, ValueError):
        count = 0
    for index in range(count):
        if env.get(f"GIT_CONFIG_KEY_{index}", "").lower() == "core.longpaths":
            env[f"GIT_CONFIG_VALUE_{index}"] = "true"
            return env
    while (f"GIT_CONFIG_KEY_{count}" in env
           or f"GIT_CONFIG_VALUE_{count}" in env):
        count += 1
    env[f"GIT_CONFIG_KEY_{count}"] = "core.longpaths"
    env[f"GIT_CONFIG_VALUE_{count}"] = "true"
    env["GIT_CONFIG_COUNT"] = str(count + 1)
    return env


def _sandbox_git(repo: Path, args: list[str], *, binary: bool = False,
                 timeout: int = 120, env: dict[str, str] | None = None,
                 ) -> subprocess.CompletedProcess:
    return _run_captured_stop_aware(
        ["git", "-C", str(repo), *args], binary=binary, timeout=timeout,
        env=_git_env_with_long_paths(env))


def _new_private_sandbox_git(repo: Path, prefix: str) -> tuple[Path, dict[str, str]]:
    """Create a disposable index/object store that only reads the raw clone."""
    # Tests and recovery tools may temporarily point REPO_DIR at the raw repo
    # itself.  Never place the private object store beneath the worktree that the
    # following `git add --all` enumerates, or capture will ingest its own objects.
    managed_root = _review_work_root().resolve()
    if managed_root.is_relative_to(repo.resolve()):
        root = Path(tempfile.mkdtemp(prefix=prefix))
    else:
        root = _new_review_temp(prefix)
    try:
        index_path = root / "index"
        object_dir = root / "objects"
        object_dir.mkdir()
        git_dir_result = _sandbox_git(repo, ["rev-parse", "--absolute-git-dir"])
        if git_dir_result.returncode != 0:
            raise OSError("raw clone Git directory lookup failed: "
                          + git_dir_result.stderr[:400])
        source_objects = Path(git_dir_result.stdout.strip()).resolve() / "objects"
        if not source_objects.is_dir():
            raise OSError(f"raw clone Git objects missing: {source_objects}")
        env = _git_env_with_long_paths()
        env["GIT_INDEX_FILE"] = str(index_path)
        env["GIT_OBJECT_DIRECTORY"] = str(object_dir)
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(source_objects)
        env["GIT_OPTIONAL_LOCKS"] = "0"
        return root, env
    except Exception:
        _discard_owned_review_temp(root, prefix, log=lambda _message: None)
        raise


def _discard_private_sandbox_git(root: Path | None, prefix: str, log=print) -> None:
    _discard_owned_review_temp(root, prefix, log=log)


def _bounded_sandbox_sibling_paths(
    sandbox_root: Path, sandbox_repo: Path, limit: int = 256,
) -> tuple[str, ...]:
    """Enumerate bounded direct children written beside the managed clone.

    The model is allowed to write only inside ``sandbox_root/repo``. A direct
    sibling is enough to prove ``../`` escape; descendants need not be scanned or
    hashed because retaining the whole owned sandbox root preserves their bytes.
    """
    if not sandbox_root.is_dir():
        return ()
    found: list[str] = []
    try:
        with os.scandir(sandbox_root) as entries:
            for entry in entries:
                if Path(entry.path) == sandbox_repo:
                    continue
                # The host publishes this durable attempt binding before the
                # provider starts.  Its bytes are checked separately after the
                # provider exits, so it is not a model-written sibling escape.
                if entry.name == _REVIEW_ATTEMPT_RECEIPT_NAME:
                    continue
                if len(found) >= max(1, limit):
                    found.append("[additional-siblings-omitted]")
                    break
                suffix = "/" if entry.is_dir(follow_symlinks=False) else ""
                found.append(entry.name.replace("\\", "/") + suffix)
    except OSError as exc:
        # Enumeration failure itself means the owned root cannot be proven clean.
        return (f"[sibling-enumeration-failed:{type(exc).__name__}]",)
    return tuple(found)


def _is_review_transient_artifact(path: str) -> bool:
    """Return whether *path* is a reproducible tool/test cache artifact.

    This classification affects acceptance only.  The full-forensics capture
    still preserves these bytes and records their paths for later analysis.
    """
    import autogit
    return autogit.classify_review_path(path) == autogit.REVIEW_PATH_CACHE


def _replace_with_retry(source: Path, target: Path, attempts: int = 8) -> None:
    """Atomically publish a file/directory despite short Windows scan locks."""
    last_error: OSError | None = None
    for attempt in range(max(1, attempts)):
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.05 * (attempt + 1))
    assert last_error is not None
    raise last_error


def _publish_review_attempt_receipt(
    sandbox_root: Path, payload: dict,
) -> tuple[dict, bytes]:
    """Durably bind one managed clone to its exact queue/model transaction."""
    receipt = dict(payload)
    receipt.update({
        "schema": _REVIEW_ATTEMPT_RECEIPT_SCHEMA,
        "sandbox_name": sandbox_root.name,
    })
    receipt.setdefault(
        "attempt_id", f"{sandbox_root.name}-{os.getpid()}-{time.time_ns()}")
    receipt.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    receipt.setdefault("created_at_ns", time.time_ns())
    raw = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path = sandbox_root / _REVIEW_ATTEMPT_RECEIPT_NAME
    temp = sandbox_root / (
        f".{_REVIEW_ATTEMPT_RECEIPT_NAME}.{os.getpid()}."
        f"{threading.get_ident()}.{time.time_ns()}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return receipt, raw


def _read_sandbox_text(repo: Path, relative: str, limit: int = 2 * 1024 * 1024) -> str:
    """读取隔离仓内的小型报告；拒绝 symlink/路径逃逸并限制内存。"""
    root = repo.resolve()
    path = repo / relative
    if path.is_symlink():
        raise OSError(f"拒绝读取符号链接：{relative}")
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return ""
    with resolved.open("rb") as handle:
        payload = handle.read(limit + 1)
    truncated = len(payload) > limit
    text = payload[:limit].decode("utf-8", errors="replace")
    return text + ("\n\n[报告超过大小限制，已截断]\n" if truncated else "")


def _copy_snapshot_file(source: Path, destination: Path) -> int:
    """可停机的大文件复制；停止时原 clone 继续作为完整权威现场保留。"""
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with source.open("rb") as reader, destination.open("wb") as writer:
        while True:
            if _review_stop_requested():
                raise _ReviewStopped()
            chunk = reader.read(1024 * 1024)
            if not chunk:
                break
            writer.write(chunk)
            total += len(chunk)
    shutil.copystat(source, destination, follow_symlinks=False)
    return total


def _capture_sandbox_wip(repo: Path, pre_head: str,
                         result: SandboxReviewResult, log=print,
                         prompt_text: str | None = None) -> None:
    """在 clone 删除前全量快照工作树改动，含越界及 ignored 文件。"""
    if not repo.is_dir():
        return
    capture_git_root: Path | None = None
    capture_prefix = "sts2-review-capture-index-"
    try:
        # 不信任模型留下的 index/commit/assume-unchanged 标记，但 raw
        # clone 本身是取证原件。所有基线恢复和 force-stage 都只写入
        # disposable index/object store，不移动 raw HEAD，不覆盖 raw index。
        capture_git_root, capture_env = _new_private_sandbox_git(repo, capture_prefix)
        read_tree = _sandbox_git(repo, ["read-tree", pre_head], env=capture_env)
        if read_tree.returncode != 0:
            log("[llm] 失败复盘 WIP 基线恢复失败；仅保存诊断元数据")
            return
        # -f 明确纳入 ignored 文件；.git 元数据仍由 Git 自身排除。宿主写入的
        # prompt 若未被模型修改则随后退回基线；被修改/删除时也作为越界成果保留。
        stage_all = _sandbox_git(
            repo, ["add", "--all", "--force", "--", "."], env=capture_env)
        own_prompt = PROMPT_FILE.relative_to(REPO_DIR).as_posix()
        prompt_path = repo.joinpath(*PurePosixPath(own_prompt).parts)
        prompt_deleted = False
        try:
            prompt_unchanged = (prompt_text is None or (
                prompt_path.is_file()
                and not prompt_path.is_symlink()
                and prompt_path.read_text(encoding="utf-8") == prompt_text))
            prompt_deleted = prompt_text is not None and not prompt_path.exists()
        except OSError:
            prompt_unchanged = False
        unstage_prompt = (_sandbox_git(
            repo, ["reset", "--quiet", pre_head, "--", own_prompt], env=capture_env)
            if prompt_unchanged else subprocess.CompletedProcess([], 0, "", ""))
        if stage_all.returncode != 0 or unstage_prompt.returncode != 0:
            log("[llm] 失败复盘全量 WIP 暂存失败；仅保存诊断元数据")
            return
        names = _sandbox_git(
            repo, ["diff", "--cached", "--name-only", "-z", pre_head, "--"],
            env=capture_env)
        if names.returncode != 0:
            log("[llm] 失败复盘全量 WIP 路径枚举失败；仅保存诊断元数据")
            return
        changed = list(dict.fromkeys(
            item.replace("\\", "/") for item in names.stdout.split("\0") if item))
        if prompt_deleted and own_prompt not in changed:
            changed.append(own_prompt)
        # The host-created prompt is never a model submission target. Preserve a
        # modified/deleted copy in WIP forensics without classifying it as patch.
        classified = [path for path in changed if path != own_prompt]
        allowed, artifacts, online, unexpected = _partition_review_changes(classified)
        result.wip_paths = tuple(changed)
        result.allowed_paths = tuple(allowed)
        result.artifact_paths = tuple(artifacts)
        result.online_paths = tuple(online)
        result.unexpected_paths = tuple(unexpected)
        capture_complete = True

        if changed:
            snapshot = _new_review_temp("sts2-review-snapshot-")
            result.snapshot_dir = str(snapshot)
            (snapshot / "files").mkdir()
            patch_path = snapshot / "wip.patch"
            patch = _sandbox_git(
                repo,
                ["diff", "--cached", "--binary", "--full-index", "--unified=3",
                  f"--output={patch_path}", pre_head, "--"],
                env=capture_env,
            )
            if patch.returncode != 0 or not patch_path.is_file():
                log("[llm] 失败复盘全量 WIP patch 导出失败；保留文件快照")
                patch_path.write_bytes(b"")
                capture_complete = False
            elif patch_path.stat().st_size <= 4 * 1024 * 1024:
                # 小补丁兼容调用方诊断/测试；大补丁只驻留磁盘，避免 8 小时
                # 复盘把二进制成果再完整复制进 Brain 内存。
                result.wip_patch = patch_path.read_bytes()
            file_states: list[dict] = []
            repo_root = repo.resolve()
            for relative in changed:
                if _review_stop_requested():
                    raise _ReviewStopped()
                pure = PurePosixPath(relative)
                state = {"path": relative}
                if (pure.is_absolute() or ".." in pure.parts
                        or any(part in {"", "."} for part in pure.parts)):
                    state["kind"] = "unsafe_path_not_copied"
                    capture_complete = False
                    file_states.append(state)
                    continue
                source = repo.joinpath(*pure.parts)
                destination = snapshot / "files" / Path(*pure.parts)
                try:
                    if source.is_symlink():
                        state.update({"kind": "symlink", "target": os.readlink(source)})
                    elif not source.exists():
                        state["kind"] = "deleted"
                    elif source.is_file():
                        resolved_source = source.resolve()
                        if not resolved_source.is_relative_to(repo_root):
                            state["kind"] = "external_target_not_followed"
                            capture_complete = False
                        else:
                            copied = _copy_snapshot_file(source, destination)
                            state.update({"kind": "file", "bytes": copied})
                    else:
                        state["kind"] = "special_not_copied"
                        capture_complete = False
                except OSError as exc:
                    state.update({"kind": "copy_error", "error": str(exc)[:400]})
                    capture_complete = False
                file_states.append(state)
            (snapshot / "file_states.json").write_text(
                json.dumps(file_states, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
        report_rel = "sts2-ascend/knowledge/meta_review.md"
        if report_rel in changed:
            try:
                result.diagnostic_report = _read_sandbox_text(repo, report_rel)
            except OSError as exc:
                log(f"[llm] 读取隔离复盘报告异常：{exc}")
        conclusion_rel = "sts2-ascend/knowledge/review_conclusion.txt"
        if not result.conclusion and conclusion_rel in changed:
            try:
                conclusion = _read_sandbox_text(repo, conclusion_rel, limit=16 * 1024)
                result.conclusion = " ".join(conclusion.split())[:200]
            except OSError:
                pass
        result.snapshot_complete = capture_complete
    except _ReviewStopped:
        result.stopped = True
        result.snapshot_complete = False
        raise
    except Exception as exc:
        log(f"[llm] 失败复盘 WIP 捕获异常；仍保留空补合包：{exc}")
    finally:
        _discard_private_sandbox_git(capture_git_root, capture_prefix, log=log)


def _discard_sandbox_snapshot(result: SandboxReviewResult, log=print) -> bool:
    """只清理由本进程 mkdtemp 创建的精确临时快照。"""
    if not result.snapshot_dir:
        return True
    snapshot = Path(result.snapshot_dir)
    try:
        resolved = snapshot.resolve()
        if _is_owned_review_temp(resolved, "sts2-review-snapshot-"):
            def remove_readonly(function, path, _exc_info) -> None:
                os.chmod(path, stat.S_IWRITE)
                function(path)

            shutil.rmtree(resolved, onerror=remove_readonly)
            result.snapshot_dir = ""
            return True
        else:
            log(f"[llm] 补合快照路径校验失败，保留供人工检查：{resolved}")
            return False
    except OSError as exc:
        log(f"[llm] 补合快照清理失败，已保留：{snapshot}（{exc}）")
        return False


def _discard_retained_sandbox(result: SandboxReviewResult, log=print) -> bool:
    """清理已成功转存的原始隔离仓；路径必须是本进程的系统临时目录。"""
    if not result.retained_sandbox_dir:
        return True
    sandbox = Path(result.retained_sandbox_dir)
    try:
        resolved = sandbox.resolve()
        if not _is_owned_review_temp(resolved, "sts2-review-sandbox-"):
            log(f"[llm] 原始隔离仓路径校验失败，保留供人工检查：{resolved}")
            return False

        def remove_readonly(function, path, _exc_info) -> None:
            os.chmod(path, stat.S_IWRITE)
            function(path)

        shutil.rmtree(resolved, onerror=remove_readonly)
        result.retained_sandbox_dir = ""
        return True
    except OSError as exc:
        log(f"[llm] 原始隔离仓清理失败，已保留：{sandbox}（{exc}）")
        return False


def _salvage_kind(reason: str, sandbox: SandboxReviewResult) -> str:
    if sandbox.stopped:
        return "lifecycle_stop"
    if sandbox.stalled:
        return "stall"
    if sandbox.timed_out:
        return "timeout"
    if sandbox.failure_code:
        return sandbox.failure_code
    if sandbox.rc not in (-1, 0):
        return "process_exit"
    if sandbox.online_paths:
        return "online_runtime"
    if (sandbox.unexpected_paths or "deny-only" in reason
            or "路径边界" in reason or "allowlist" in reason):
        return "path_boundary"
    if sandbox.selfcheck_ok is False or "自检" in reason:
        return "selfcheck"
    if sandbox.patch and ("提交" in reason or "冲突" in reason):
        return "commit_conflict"
    return "review_failure"


def _review_backend_label(manifest: dict) -> str:
    """Return one unambiguous configured-backend/executor/model label."""
    backend_key = str(manifest.get("backend_key") or "").strip()
    runner = str(manifest.get("runner") or "").strip()
    model = str(manifest.get("model") or "").strip()
    suffix = str(
        manifest.get("reasoning_effort") if runner == "codex"
        else manifest.get("variant") or "").strip()
    display_model = model
    if display_model and suffix and not display_model.endswith(f"@{suffix}"):
        display_model = f"{display_model}@{suffix}"
    executor = "/".join(value for value in (runner, display_model) if value)
    if backend_key and backend_key not in {model, display_model, executor}:
        return f"{backend_key} ({executor})" if executor else backend_key
    return executor or backend_key or "未记录复盘后端"


def _resolution_backend_label(manifest: dict) -> str:
    label = str(manifest.get("retry_backend_label") or "").strip()
    if label:
        return label
    retry_fields = {
        "backend_key": manifest.get("retry_backend_key"),
        "runner": manifest.get("retry_runner"),
        "model": manifest.get("retry_model"),
        "variant": manifest.get("retry_variant"),
        "reasoning_effort": manifest.get("retry_reasoning_effort"),
    }
    if any(value for value in retry_fields.values()):
        return _review_backend_label(retry_fields)
    if manifest.get("retry_resolution"):
        return "执行后端未记录"
    return _review_backend_label(manifest)


def _rejection_pending_status(manifest: dict) -> str:
    backend = _review_backend_label(manifest)
    if manifest.get("failure_kind") == "lifecycle_stop" or manifest.get("stopped"):
        return f"维护中断/取消（非 {backend} 提交失败；待原后端恢复）"
    return f"待 {backend} 重审/补合"


def _failure_kind_label(manifest: dict) -> str:
    kind = str(manifest.get("failure_kind") or "")
    if kind == "lifecycle_stop":
        return "维护中断/取消（lifecycle_stop）"
    return kind


def _current_head_for_salvage() -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_DIR), "rev-parse", "--verify", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


_REJECTION_LEDGER_SCHEMA_MARKER = "<!-- review-rejection-ledger-schema:2 -->"


_REJECTION_LEDGER_HEADER = """# 复盘拒合与维护中断批次清单
<!-- review-rejection-ledger-schema:2 -->

这是一份由复盘宿主维护、受 Git 跟踪的拒合账本。失败包仍完整保存在
`knowledge/code_backups/review_salvage/`；本清单只记录索引和处理状态，不代替原始证据。

每次新拒合或维护中断在现场包原子发布后立即追加一行，并单独建立 Git commit；正常运行时同步推送，
整套停止临界区为守住两分钟直播死线只建立本地 commit，由下次启动补推。

| 时间 | 批次 | 基线 | 类型 | 模型 | 状态 | 失败包 | 原因 |
| --- | --- | --- | --- | --- | --- | --- | --- |
"""


def _ledger_cell(value, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[:max(0, limit - 1)] + "…"
    return text.replace("|", "\\|")


def _rejection_ledger_block(
    package_name: str, manifest: dict, *, status: str,
    package_cell: str, reason: str,
) -> str:
    runs = manifest.get("batch_runs") or []
    batch = _batch_description(runs) or "未记录"
    pre_head = str(manifest.get("pre_head") or "")[:8] or "—"
    model = _review_backend_label(manifest)
    marker = f"<!-- rejection:{package_name} -->"
    return (
        f"{marker}\n"
        f"| {_ledger_cell(manifest.get('time'))} | {_ledger_cell(batch)} | `{pre_head}` | "
        f"{_ledger_cell(_failure_kind_label(manifest))} | {_ledger_cell(model)} | "
        f"{_ledger_cell(status)} | {_ledger_cell(package_cell, 500)} | "
        f"{_ledger_cell(reason)} |\n"
    )


def _ledger_text_at_head() -> str:
    rel_ledger = REJECTION_LEDGER.relative_to(REPO_DIR).as_posix()
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_DIR), "show", f"HEAD:{rel_ledger}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30)
        if proc.returncode == 0:
            return proc.stdout
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return ""


def _ledger_markers(text: str) -> list[str]:
    prefix = "<!-- rejection:"
    suffix = " -->"
    return [line.strip()[len(prefix):-len(suffix)]
            for line in str(text or "").splitlines()
            if line.strip().startswith(prefix) and line.strip().endswith(suffix)]


def _ledger_marker_has_status(text: str, package_name: str, status: str) -> bool:
    """Match one package's row instead of accepting the status from another row."""
    return _ledger_marker_status(text, package_name) == status


def _ledger_marker_status(text: str, package_name: str) -> str:
    """Read the exact status cell for one named ledger row."""
    marker = f"<!-- rejection:{package_name} -->"
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.strip() == marker:
            # Ledger cells are escaped before rendering, so the delimiter itself
            # cannot occur inside a cell. Match the status column exactly; a
            # historical reason mentioning a pending state must not mask closure.
            cells = lines[index + 1].split(" | ")
            return cells[5].strip() if len(cells) > 5 else ""
    return ""


def _migrate_rejection_ledger_labels(log=print) -> bool:
    """Neutralize legacy GLM attribution without guessing the closing executor."""
    try:
        current = REJECTION_LEDGER.read_text(encoding="utf-8")
    except FileNotFoundError:
        return True
    except OSError as exc:
        log(f"[llm] 拒合清单模型标签迁移读取失败：{exc}")
        return False
    lines = current.splitlines(keepends=True)
    header_changed = False
    if lines and lines[0].rstrip("\r\n") == "# GLM 复盘拒合批次清单":
        newline = "\r\n" if lines[0].endswith("\r\n") else "\n" if lines[0].endswith("\n") else ""
        lines[0] = "# 复盘拒合与维护中断批次清单" + newline
        header_changed = True
    schema_missing = _REJECTION_LEDGER_SCHEMA_MARKER not in current
    schema_changed = False
    if schema_missing:
        newline = ("\r\n" if lines and lines[0].endswith("\r\n")
                   else "\n")
        lines.insert(1 if lines else 0, _REJECTION_LEDGER_SCHEMA_MARKER + newline)
        schema_changed = True
    changed_packages: list[str] = []
    for index, line in enumerate(lines[:-1]):
        marker = line.strip()
        if not (marker.startswith("<!-- rejection:") and marker.endswith(" -->")):
            continue
        row = lines[index + 1]
        newline = "\r\n" if row.endswith("\r\n") else "\n" if row.endswith("\n") else ""
        cells = row.rstrip("\r\n").split(" | ")
        if len(cells) <= 7:
            continue
        if not schema_missing:
            continue
        kind = cells[3].strip()
        model = cells[4].strip() or "未记录复盘后端"
        status = cells[5].strip()
        lifecycle_stop = kind in {"lifecycle_stop", "维护中断/取消（lifecycle_stop）"}
        lifecycle_prefix = "维护中断/取消；"
        status_body = (status[len(lifecycle_prefix):]
                       if status.startswith(lifecycle_prefix) else status)
        neutral_prefix = lifecycle_prefix if (
            lifecycle_stop or status.startswith(lifecycle_prefix)) else ""
        next_status = status
        if status == "待 GLM 重审/补合":
            next_status = (f"维护中断/取消（非 {model} 提交失败；待原后端恢复）"
                           if lifecycle_stop else f"待 {model} 重审/补合")
        elif status_body.startswith("GLM 已补合并闭环 "):
            tail = status_body[len("GLM 已补合并闭环 "):]
            next_status = f"{neutral_prefix}复盘已补合并闭环 {tail}"
        elif status_body.startswith("GLM 复审确认无有效成果并闭环 "):
            tail = status_body[len("GLM 复审确认无有效成果并闭环 "):]
            next_status = f"{neutral_prefix}复盘已确认无有效成果并闭环 {tail}"
        elif status_body.startswith(f"{model} 已补合并闭环 "):
            tail = status_body[len(f"{model} 已补合并闭环 "):]
            next_status = f"{neutral_prefix}复盘已补合并闭环 {tail}"
        elif status_body.startswith(f"{model} 复审确认无有效成果并闭环 "):
            tail = status_body[len(f"{model} 复审确认无有效成果并闭环 "):]
            next_status = f"{neutral_prefix}复盘已确认无有效成果并闭环 {tail}"
        row_changed = False
        if lifecycle_stop and kind != "维护中断/取消（lifecycle_stop）":
            cells[3] = "维护中断/取消（lifecycle_stop）"
            row_changed = True
        if next_status != status:
            cells[5] = next_status
            row_changed = True
        reason_suffix = " |" if cells[7].endswith(" |") else ""
        reason_text = cells[7][:-2] if reason_suffix else cells[7]
        next_reason = reason_text.replace("GLM 重审结论", "复盘重审结论")
        if lifecycle_stop and "非模型提交失败" not in next_reason:
            next_reason = f"{next_reason}；非模型提交失败"
        if next_reason != reason_text:
            cells[7] = f"{next_reason}{reason_suffix}"
            row_changed = True
        if not row_changed:
            continue
        lines[index + 1] = " | ".join(cells) + newline
        changed_packages.append(marker[len("<!-- rejection:"):-len(" -->")])
    head_before = _ledger_text_at_head()
    head_needs_migration = bool(
        head_before and _REJECTION_LEDGER_SCHEMA_MARKER not in head_before)
    if (not changed_packages and not header_changed and not schema_changed
            and not head_needs_migration):
        return True
    if _review_stop_requested() or not _flush_pending_rejection_ledger(log=log):
        return False
    updated = "".join(lines)
    temp = REJECTION_LEDGER.with_name(
        f".{REJECTION_LEDGER.name}.labels-{os.getpid()}-"
        f"{threading.get_ident()}-{time.time_ns()}.tmp")
    try:
        temp.write_text(updated, encoding="utf-8")
        os.replace(temp, REJECTION_LEDGER)
    finally:
        temp.unlink(missing_ok=True)
    import autogit
    rel_ledger = REJECTION_LEDGER.relative_to(REPO_DIR).as_posix()
    result = autogit.commit_progress_result(
        "chore(sts2-ascend): 修正复盘后端归因",
        paths=[rel_ledger], log=log, push=False)
    if _review_stop_requested():
        return False
    autogit.push_pending(log=log, attempts=1)
    if result.created:
        log("[llm] 已中性化历史闭环归因并修正拒合清单模型标签："
            f"{changed_packages} ({result.commit[:8]})")
    head_after = _ledger_text_at_head().replace("\r\n", "\n")
    committed = bool(
        result.created or head_after == updated.replace("\r\n", "\n"))
    if not committed:
        log("[llm] 拒合清单归因迁移尚未进入 HEAD；保留工作树改动待补交")
    return committed


def _flush_pending_rejection_ledger(log=print) -> bool:
    """Commit one leftover ledger edit before another rejection row is appended.

    This preserves the user-visible invariant that every newly rejected package
    has its own Git commit even when the previous commit hit a transient CAS/lock.
    """
    try:
        current = REJECTION_LEDGER.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = _REJECTION_LEDGER_HEADER
    head_text = _ledger_text_at_head()
    if current == head_text or (not head_text and current == _REJECTION_LEDGER_HEADER):
        return True
    head_markers = set(_ledger_markers(head_text))
    new_markers = [name for name in _ledger_markers(current) if name not in head_markers]
    if len(new_markers) > 1:
        log("[llm] 拒合清单存在多个旧版未拆分 marker；暂停追加新条目，避免合并提交："
            f"{new_markers}")
        return False
    import autogit
    rel_ledger = REJECTION_LEDGER.relative_to(REPO_DIR).as_posix()
    message = (f"chore(sts2-ascend): 记录拒合批次 {new_markers[0]}"
               if new_markers else
               "chore(sts2-ascend): 恢复拒合清单待提交状态")
    result = autogit.commit_progress_result(
        message, paths=[rel_ledger], log=log, push=False)
    if result.created:
        return True
    return REJECTION_LEDGER.read_text(encoding="utf-8") == _ledger_text_at_head()


def _record_review_rejection(package: Path, manifest: dict, log=print) -> None:
    """Append one durable rejection index row and commit that row independently.

    The salvage package is the forensic source of truth; the tracked ledger is only
    an auditable index.  Tests and alternate salvage roots intentionally do not
    mutate the production ledger.
    """
    try:
        production_root = (KNOWLEDGE_DIR / "code_backups" / "review_salvage").resolve()
        if SALVAGE_ROOT.resolve() != production_root:
            return
        package = package.resolve()
        if package.parent != production_root or not package.is_dir():
            log(f"[llm] 拒合清单跳过不安全失败包路径：{package}")
            return
        if not _flush_pending_rejection_ledger(log=log):
            log(f"[llm] 上一个拒合清单提交尚未独立落地；暂缓追加 {package.name}")
            return
        marker = f"<!-- rejection:{package.name} -->"
        try:
            current = REJECTION_LEDGER.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = _REJECTION_LEDGER_HEADER
        status = _rejection_pending_status(manifest)
        if marker in current:
            # Operator-preserved hold packages can outlive an invalid historical
            # prompt-only closure. Hold recovery explicitly clears that receipt
            # and publishes a fresh replay intent; restore the tracked index too.
            # A complete mounted-evidence receipt must never be reopened here.
            target_names = _normalize_salvage_package_names([
                manifest.get("replay_target") or package.name])
            hold_closure_confirmed = bool(
                target_names
                and _review_hold_closure_is_confirmed(target_names[0]))
            reopen_from_hold = bool(
                manifest.get("review_hold_recovered_at")
                and manifest.get("replay_enqueue_pending")
                and not _manifest_has_full_replay_receipt(manifest)
                and not hold_closure_confirmed)
            if (reopen_from_hold
                    and not _ledger_marker_has_status(
                        current, package.name, status)):
                rel_package = package.relative_to(BASE_DIR).as_posix()
                original_reason = str(manifest.get("reason") or "").strip()
                reason = "restored from review_hold; awaiting full-evidence review"
                if original_reason:
                    reason += f"; original failure: {original_reason}"
                reopened = _update_rejection_ledger(
                    package.name, manifest, status=status,
                    package_cell=f"`{rel_package}`", reason=reason,
                    message=("chore(sts2-ascend): reopen review batch "
                             f"{package.name} ({_review_backend_label(manifest)})"),
                    log=log)
                if reopened:
                    log(f"[llm] hold-restored ledger row reopened: {package.name}")
                return
            # _flush_pending_rejection_ledger above already proved this exact
            # existing edit is committed (or identical to HEAD).  A repeated
            # recovery pass may retry push, but must not request another commit.
            import autogit
            pushed = (autogit.push_pending(log=log, attempts=1)
                      if not _review_stop_requested() else False)
            if pushed and _upstream_ledger_contains(package.name, status):
                log(f"[llm] 拒合批次清单条目已存在并确认推送：{package.name}")
            return
        rel_package = package.relative_to(BASE_DIR).as_posix()
        row = _rejection_ledger_block(
            package.name, manifest, status=status,
            package_cell=f"`{rel_package}`", reason=str(manifest.get("reason") or ""))
        if not current.strip():
            current = _REJECTION_LEDGER_HEADER
        elif not current.endswith("\n"):
            current += "\n"
        temp = REJECTION_LEDGER.with_name(
            f".{REJECTION_LEDGER.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        try:
            temp.write_text(current + row, encoding="utf-8")
            os.replace(temp, REJECTION_LEDGER)
        finally:
            temp.unlink(missing_ok=True)

        import autogit  # delayed: keep standalone forensic helpers importable
        rel_ledger = REJECTION_LEDGER.relative_to(REPO_DIR).as_posix()
        result = autogit.commit_progress_result(
            f"chore(sts2-ascend): 记录拒合批次 {package.name}",
            paths=[rel_ledger], log=log, push=False)
        pushed = False
        if not _review_stop_requested():
            pushed = autogit.push_pending(log=log, attempts=1)
        if result.created:
            suffix = "并推送" if pushed else "（仅提交，待启动补推）"
            log(f"[llm] 拒合批次清单已单独提交{suffix}：{result.commit[:8]}")
        else:
            if pushed and _upstream_ledger_contains(package.name, status):
                log(f"[llm] 拒合批次清单条目已存在并确认推送：{package.name}")
            else:
                log(f"[llm] 拒合批次清单提交失败，条目留在工作树待补交：{result.reason}")
    except Exception as exc:
        # Ledger failure must never delete or invalidate the already-published evidence.
        log(f"[llm] 拒合批次清单更新异常；失败包仍完整保留：{exc}")


def _upstream_ref() -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_DIR), "rev-parse", "--abbrev-ref",
             "--symbolic-full-name", "@{upstream}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _upstream_contains_commit(commit: str) -> bool:
    upstream = _upstream_ref()
    if not upstream or not commit:
        return False
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_DIR), "merge-base", "--is-ancestor",
             commit, upstream], capture_output=True, timeout=30)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _upstream_ledger_contains(package_name: str, status: str) -> bool:
    upstream = _upstream_ref()
    if not upstream:
        return False
    rel_ledger = REJECTION_LEDGER.relative_to(REPO_DIR).as_posix()
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_DIR), "show", f"{upstream}:{rel_ledger}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30)
        if proc.returncode != 0:
            return False
        marker = f"<!-- rejection:{package_name} -->"
        lines = proc.stdout.splitlines()
        for index, line in enumerate(lines[:-1]):
            if line.strip() == marker:
                return status in lines[index + 1]
        return False
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def _upstream_ledger_has_exact_status(package_name: str, status: str) -> bool:
    """Require the named upstream row's status cell, not a reason substring."""
    upstream = _upstream_ref()
    if not upstream or not status:
        return False
    try:
        rel_ledger = REJECTION_LEDGER.relative_to(REPO_DIR).as_posix()
        proc = subprocess.run(
            ["git", "-C", str(REPO_DIR), "show", f"{upstream}:{rel_ledger}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30)
        return bool(
            proc.returncode == 0
            and _ledger_marker_has_status(proc.stdout, package_name, status))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def _upstream_ledger_has_terminal_closure(package_name: str) -> bool:
    """Accept only an exact final status cell for a legacy empty quarantine."""
    upstream = _upstream_ref()
    if not upstream:
        return False
    try:
        rel_ledger = REJECTION_LEDGER.relative_to(REPO_DIR).as_posix()
        proc = subprocess.run(
            ["git", "-C", str(REPO_DIR), "show", f"{upstream}:{rel_ledger}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30)
        if proc.returncode != 0:
            return False
        status = _ledger_marker_status(proc.stdout, package_name)
        actions = (
            "已补合并闭环 `",
            "复审确认无有效成果并闭环 `",
            "已确认无有效成果并闭环 `",
        )
        for action in actions:
            backend, separator, remainder = status.partition(action)
            if not backend.strip() or not separator or not remainder.endswith("`"):
                continue
            commit_prefix = remainder[:-1]
            if (len(commit_prefix) == 8
                    and all(char in "0123456789abcdefABCDEF"
                            for char in commit_prefix)):
                return True
        return False
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def _ensure_rejection_ledger_marker(
    package_name: str, manifest: dict, package_cell: str, log=print,
) -> bool:
    """Durably restore a missing initial rejection row before package cleanup."""
    if _upstream_ledger_contains(package_name, ""):
        return True
    if _review_stop_requested():
        return False
    try:
        production_root = (KNOWLEDGE_DIR / "code_backups" / "review_salvage").resolve()
        if SALVAGE_ROOT.resolve() != production_root:
            return False
        if not _flush_pending_rejection_ledger(log=log):
            return False
        try:
            current = REJECTION_LEDGER.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = _REJECTION_LEDGER_HEADER
        marker = f"<!-- rejection:{package_name} -->"
        if marker not in current:
            if current and not current.endswith("\n"):
                current += "\n"
            current += _rejection_ledger_block(
                package_name, manifest, status=_rejection_pending_status(manifest),
                package_cell=package_cell,
                reason=str(manifest.get("reason") or "闭环前恢复缺失的拒合索引"))
            temp = REJECTION_LEDGER.with_name(
                f".{REJECTION_LEDGER.name}.restore-{os.getpid()}-"
                f"{threading.get_ident()}-{time.time_ns()}.tmp")
            try:
                temp.write_text(current, encoding="utf-8")
                os.replace(temp, REJECTION_LEDGER)
            finally:
                temp.unlink(missing_ok=True)
        import autogit
        rel_ledger = REJECTION_LEDGER.relative_to(REPO_DIR).as_posix()
        result = autogit.commit_progress_result(
            f"chore(sts2-ascend): 补录拒合批次 {package_name}",
            paths=[rel_ledger], log=log, push=False)
        if result.created:
            log(f"[llm] 已恢复缺失拒合索引并单独提交：{result.commit[:8]}")
        if _review_stop_requested():
            return False
        autogit.push_pending(log=log, attempts=1)
        return _upstream_ledger_contains(package_name, "")
    except Exception as exc:
        log(f"[llm] 缺失拒合索引恢复失败，失败包继续保留：{exc}")
        return False


def _update_rejection_ledger(
    package_name: str, manifest: dict, *, status: str,
    package_cell: str, reason: str, message: str, log=print,
) -> bool:
    """Replace one exact ledger row, commit it separately, and confirm upstream."""
    try:
        if _review_stop_requested():
            return False
        production_root = (KNOWLEDGE_DIR / "code_backups" / "review_salvage").resolve()
        if SALVAGE_ROOT.resolve() != production_root:
            return False
        current = REJECTION_LEDGER.read_text(encoding="utf-8")
        marker = f"<!-- rejection:{package_name} -->"
        lines = current.splitlines(keepends=True)
        marker_index = next(
            (index for index, line in enumerate(lines) if line.strip() == marker), -1)
        if marker_index < 0 or marker_index + 1 >= len(lines):
            log(f"[llm] 拒合清单找不到待更新条目：{package_name}")
            return False
        block = _rejection_ledger_block(
            package_name, manifest, status=status,
            package_cell=package_cell, reason=reason)
        end = marker_index + 2 if lines[marker_index + 1].lstrip().startswith("|") \
            else marker_index + 1
        updated = "".join(lines[:marker_index]) + block + "".join(lines[end:])
        if updated != current:
            temp = REJECTION_LEDGER.with_name(
                f".{REJECTION_LEDGER.name}.resolve-{os.getpid()}-"
                f"{threading.get_ident()}-{time.time_ns()}.tmp")
            try:
                temp.write_text(updated, encoding="utf-8")
                os.replace(temp, REJECTION_LEDGER)
            finally:
                temp.unlink(missing_ok=True)
        import autogit
        rel_ledger = REJECTION_LEDGER.relative_to(REPO_DIR).as_posix()
        result = autogit.commit_progress_result(
            message, paths=[rel_ledger], log=log, push=False)
        if _review_stop_requested():
            return False
        # Handles a crash after the ledger commit/push but before ignored manifest
        # state advanced, and retries a transient push without duplicating a row.
        autogit.push_pending(log=log, attempts=1)
        return _upstream_ledger_contains(package_name, status)
    except Exception as exc:
        log(f"[llm] 拒合清单闭环更新失败；失败包继续保留：{exc}")
        return False


_CLOSED_SALVAGE_PREFIX = ".glm-closed-"


def _quarantine_closed_salvage(package: Path, log=print) -> Path | None:
    """Atomically move one confirmed package aside before final ledger commit."""
    try:
        root = SALVAGE_ROOT.resolve()
        resolved = package.resolve()
        if resolved.parent != root or not resolved.is_dir():
            return None
        quarantine = root / f"{_CLOSED_SALVAGE_PREFIX}{resolved.name}"
        if quarantine.exists():
            return quarantine
        resolved.replace(quarantine)
        return quarantine
    except OSError as exc:
        log(f"[llm] 已确认补合但隔离待删除失败包失败，原包继续保留：{package}（{exc}）")
        return None


def _delete_closed_quarantine(quarantine: Path, log=print) -> bool:
    """Delete one exact quarantined package after the final ledger is upstream."""
    try:
        root = SALVAGE_ROOT.resolve()
        resolved = quarantine.resolve()
        if (resolved.parent != root
                or not resolved.name.startswith(_CLOSED_SALVAGE_PREFIX)
                or not resolved.is_dir()):
            return False
        # The package has already left the active namespace and its final ledger
        # state is upstream.  Delete incrementally so Stop can return promptly.
        # Keep the root manifest as the recovery receipt until every potentially
        # large payload and nested directory is gone.
        manifest_path = resolved / "manifest.json"
        for walk_root, directories, files in os.walk(resolved, topdown=False):
            for name in files:
                path = Path(walk_root) / name
                if path == manifest_path:
                    continue
                if _review_stop_requested():
                    return False
                try:
                    path.unlink()
                except PermissionError:
                    os.chmod(path, stat.S_IWRITE)
                    path.unlink()
            for name in directories:
                if _review_stop_requested():
                    return False
                path = Path(walk_root) / name
                try:
                    path.unlink() if path.is_symlink() else path.rmdir()
                except PermissionError:
                    os.chmod(path, stat.S_IWRITE)
                    path.unlink() if path.is_symlink() else path.rmdir()
        if _review_stop_requested():
            return False
        # This tail is intentionally bounded and has no Stop checkpoint between
        # its two operations.  A process crash can leave only an empty quarantine;
        # boot recovery removes it solely after rechecking the exact upstream row.
        if manifest_path.exists():
            try:
                manifest_path.unlink()
            except PermissionError:
                os.chmod(manifest_path, stat.S_IWRITE)
                manifest_path.unlink()
        resolved.rmdir()
        return not resolved.exists()
    except OSError as exc:
        log(f"[llm] 最终清单已确认但删除隔离失败包失败，保留待下次重试：{quarantine}（{exc}）")
        return False


def _finish_quarantined_salvage(
    quarantine: Path, original_name: str, manifest: dict, log=print,
) -> bool:
    resolution = str(manifest.get("retry_resolution") or "")
    commit = str(manifest.get("retry_resolution_commit") or "")
    if resolution not in {"integrated", "no_valid_change"} or not commit:
        return False
    if _review_stop_requested() or not _upstream_contains_commit(commit):
        return False
    production_root = (KNOWLEDGE_DIR / "code_backups" / "review_salvage").resolve()
    if SALVAGE_ROOT.resolve() == production_root:
        if not _ensure_rejection_ledger_marker(
                original_name, manifest, "（隔离保留，待闭环）", log=log):
            return False
    backend = _resolution_backend_label(manifest)
    action = (f"{backend} 已补合" if resolution == "integrated"
              else f"{backend} 复审确认无有效成果")
    final_status = f"{action}并闭环 `{commit[:8]}`"
    final_reason = (f"{backend} 重审结论与提交 {commit[:8]} 已推送；"
                    "远端确认后精确清理对应失败包")
    final_ok = _update_rejection_ledger(
        original_name, manifest, status=final_status, package_cell="（闭环清理）",
        reason=final_reason,
        message=f"chore(sts2-ascend): 关闭复盘批次 {original_name} ({backend})",
        log=log)
    if not final_ok:
        return False
    manifest = dict(manifest)
    manifest["retry_resolution_state"] = "ledger_final_upstream"
    manifest["retry_resolution_ledger_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        _publish_manifest_update(quarantine, manifest)
    except OSError:
        # The exact upstream ledger row is the authoritative delete permission;
        # a crash here is recovered by rechecking it on the next boot.
        pass
    if not _publish_review_hold_closure(
            original_name, manifest, final_status, log=log):
        return False
    if not _delete_closed_quarantine(quarantine, log=log):
        return False
    log(f"[llm] {backend} 失败包已完成重审、远端确认并删除：{original_name}")
    return True


def _finalize_salvage_resolution(package: Path, manifest: dict, log=print) -> bool:
    """Close a GLM-audited package only after code and ledger are upstream."""
    resolution = str(manifest.get("retry_resolution") or "")
    commit = str(manifest.get("retry_resolution_commit") or "")
    if resolution not in {"integrated", "no_valid_change"}:
        return False
    if not _upstream_contains_commit(commit):
        return False
    if _review_stop_requested():
        return False
    production_root = (KNOWLEDGE_DIR / "code_backups" / "review_salvage").resolve()
    if SALVAGE_ROOT.resolve() == production_root:
        try:
            package_cell = f"`{package.relative_to(BASE_DIR).as_posix()}`"
        except ValueError:
            package_cell = f"`{package.as_posix()}`"
        if not _ensure_rejection_ledger_marker(
                package.name, manifest, package_cell, log=log):
            return False
    manifest = dict(manifest)
    manifest["retry_resolution_state"] = "quarantined_pending_ledger"
    manifest["retry_resolution_quarantine_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _publish_manifest_update(package, manifest)
    quarantine = _quarantine_closed_salvage(package, log=log)
    if quarantine is None:
        return False
    return _finish_quarantined_salvage(
        quarantine, package.name, manifest, log=log)


def _close_replayed_salvages(
    package_names, attempt_names, resolutions: dict, *,
    commit: str, pushed: bool, evidence_schema: int = 0,
    review_backend: dict | None = None, log=print,
) -> dict[str, list[str]]:
    """Persist model receipts and let the host close only remotely accepted work."""
    result = {"closed": [], "host_pending": []}
    if not commit:
        return result
    targets = _normalize_salvage_package_names(package_names)
    if not targets:
        return result
    target = targets[0]
    resolution = str(resolutions.get(target) or "")
    if resolution not in {"integrated", "no_valid_change"}:
        return result
    lineage = _normalize_salvage_package_names([target, *attempt_names])
    if (any(_review_hold_contains_package(name) for name in lineage)
            and int(evidence_schema or 0) < _RETRY_SANDBOX_EVIDENCE_SCHEMA):
        result["host_pending"].append(target)
        log("[llm] held lineage 缺少完整证据 schema 回执；"
            "忽略旧结论并保留原绑定模型重审："
            f"{target}")
        return result
    code_upstream = bool(pushed or _upstream_contains_commit(commit))
    # Persist the complete lineage on the target first.  If the host crashes at
    # any later instruction, startup can propagate the same GLM receipt without
    # spending another model call.
    ordered = [target, *[name for name in lineage if name != target]]
    receipt_backend = dict(review_backend or {})
    receipt_backend_label = (
        _review_backend_label(receipt_backend)
        if any(receipt_backend.values()) else "执行后端未记录")
    prepared: list[tuple[str, Path, dict]] = []
    for name in ordered:
        package = _salvage_package_path(name)
        if package is None:
            continue
        try:
            manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
            manifest = dict(manifest)
            manifest.update({
                "retry_resolution": resolution,
                "retry_resolution_target": target,
                "retry_resolution_lineage": lineage,
                "retry_resolution_commit": commit,
                "retry_resolution_claimed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "retry_resolution_state": (
                    "code_upstream_confirmed" if code_upstream
                    else "claimed_pending_code_push"),
                "retry_resolution_evidence_complete": True,
                "retry_resolution_evidence_schema": int(evidence_schema or 0),
                "retry_backend_label": receipt_backend_label,
                "retry_backend_key": str(receipt_backend.get("backend_key") or ""),
                "retry_runner": str(receipt_backend.get("runner") or ""),
                "retry_model": str(receipt_backend.get("model") or ""),
                "retry_variant": str(receipt_backend.get("variant") or ""),
                "retry_reasoning_effort": str(
                    receipt_backend.get("reasoning_effort") or ""),
            })
            _publish_manifest_update(package, manifest)
            prepared.append((name, package, manifest))
        except Exception as exc:
            log(f"[llm] 失败包 {name} 回执持久化异常；原包继续保留：{exc}")
            result["host_pending"].append(name)
    # Queue acknowledgement is the next transaction boundary.  Never quarantine
    # or delete here: a crash before _finalize_review_batch would otherwise leave
    # a stale reviewing item whose target evidence has already disappeared.
    result["host_pending"].extend(
        name for name, _package, _manifest in prepared
        if name not in result["host_pending"])
    return result


def _resume_replay_lineage_resolution(target_package: Path,
                                      target_manifest: dict, log=print) -> None:
    """Propagate one durable target receipt and resume host-only closure."""
    resolution = str(target_manifest.get("retry_resolution") or "")
    commit = str(target_manifest.get("retry_resolution_commit") or "")
    if resolution not in {"integrated", "no_valid_change"} or not commit:
        return
    if not _upstream_contains_commit(commit):
        if _review_stop_requested():
            return
        try:
            import autogit
            autogit.push_pending(log=log, attempts=1)
        except Exception as exc:
            log(f"[llm] lineage 代码提交补推异常，保留宿主闭环状态：{exc}")
            return
        if not _upstream_contains_commit(commit):
            return
    target_name = str(target_manifest.get("retry_resolution_target")
                      or target_manifest.get("replay_target")
                      or target_package.name)
    lineage = _normalize_salvage_package_names(
        target_manifest.get("retry_resolution_lineage")
        or [target_name, *(target_manifest.get("replay_attempt_packages") or [])])
    prepared: list[tuple[Path, dict]] = []
    preparation_failed = False
    for name in lineage:
        package = _salvage_package_path(name)
        if package is None:
            continue
        try:
            manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
            manifest = dict(manifest)
            manifest.update({
                "retry_resolution": resolution,
                "retry_resolution_target": target_name,
                "retry_resolution_lineage": lineage,
                "retry_resolution_commit": commit,
                "retry_resolution_claimed_at": target_manifest.get(
                    "retry_resolution_claimed_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
                "retry_resolution_state": "code_upstream_confirmed",
            })
            _publish_manifest_update(package, manifest)
            prepared.append((package, manifest))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            log(f"[llm] lineage 回执恢复暂未写入 {name}：{exc}")
            preparation_failed = True
    if _review_stop_requested():
        return
    prepared.sort(key=lambda item: item[0].name == target_name)
    for package, manifest in prepared:
        if _review_stop_requested():
            return
        if package.name == target_name and preparation_failed:
            return
        _finalize_salvage_resolution(package, manifest, log=log)


_RETRY_REPLAY_TOTAL_BYTES = 256 * 1024
_RETRY_EVIDENCE_SCHEMA = 3
_RETRY_SANDBOX_EVIDENCE_SCHEMA = 1
_RETRY_SANDBOX_EVIDENCE_ROOT = PurePosixPath(
    "sts2-ascend/.review_evidence/failed_review")
_RETRY_SANDBOX_EVIDENCE_INDEX = (
    _RETRY_SANDBOX_EVIDENCE_ROOT / "index.json")
_RETRY_SANDBOX_REQUIRED_FILES = (
    "manifest.json",
    "report.md",
    "file_states.json",
    "retry_candidate_inventory.json",
)
_RETRY_RESOLUTION_VALUES = frozenset({
    "integrated", "no_valid_change", "still_pending",
})


def _normalize_salvage_package_names(values) -> list[str]:
    """Return stable direct-child package ids without scanning the salvage root."""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        name = str(value or "").strip()
        if (not name or name in {".", ".."} or "/" in name or "\\" in name
                or name.startswith(".") or name in seen):
            continue
        normalized.append(name)
        seen.add(name)
    return normalized


def _salvage_package_path(name: str) -> Path | None:
    names = _normalize_salvage_package_names([name])
    if not names:
        return None
    package = SALVAGE_ROOT / names[0]
    try:
        if package.resolve().parent != SALVAGE_ROOT.resolve() or not package.is_dir():
            return None
    except OSError:
        return None
    return package


def _link_replay_attempt(target_name: str, attempt_name: str,
                         existing_attempts=(), log=print) -> list[str]:
    """Durably attach one failed retry attempt without turning it into a target."""
    target = _salvage_package_path(target_name)
    attempt = _salvage_package_path(attempt_name)
    attempts = _normalize_salvage_package_names([
        *existing_attempts, attempt_name])
    if target is None or attempt is None or target_name == attempt_name:
        return [name for name in attempts if name != target_name]
    try:
        attempt_manifest = json.loads(
            (attempt / "manifest.json").read_text(encoding="utf-8"))
        attempt_manifest = dict(attempt_manifest)
        attempt_manifest.update({
            "replay_enqueue_pending": True,
            "replay_target": target_name,
            "replay_role": "attempt_evidence",
            "replay_attempt_no": attempts.index(attempt_name) + 1,
            "replay_parent_attempt": (
                attempts[-2] if len(attempts) > 1 else target_name),
        })
        _publish_manifest_update(attempt, attempt_manifest)

        target_manifest = json.loads(
            (target / "manifest.json").read_text(encoding="utf-8"))
        target_manifest = dict(target_manifest)
        target_manifest.update({
            "replay_enqueue_pending": True,
            "replay_target": target_name,
            "replay_role": "target",
            "replay_attempt_packages": attempts,
        })
        _publish_manifest_update(target, target_manifest)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        # Both packages already contain enough linkage for startup reconciliation;
        # this fast-path failure must not lose or retarget either package.
        log(f"[llm] 重试 attempt 关联暂未完成，将由启动恢复重建：{exc}")
    return [name for name in attempts if name != target_name]


def _retry_raw_repo(package: Path) -> Path | None:
    raw = package / "raw_sandbox"
    for candidate in (raw / "repo", raw):
        if candidate.is_dir() and (candidate / ".git").exists():
            return candidate
    return None


def _publish_manifest_update(package: Path, manifest: dict) -> None:
    manifest_path = package / "manifest.json"
    temp = package / (
        f".manifest.retry-{os.getpid()}-{threading.get_ident()}-{time.time_ns()}.tmp")
    try:
        temp.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        _replace_with_retry(temp, manifest_path)
    finally:
        temp.unlink(missing_ok=True)


def _materialize_retry_evidence(package: Path, log=print) -> dict:
    """Build a review-only candidate from a recovered raw clone.

    The raw clone's HEAD, refs, stash, worktree, index and object database remain
    untouched.  Separate source sections expose accepted-only worktree, index,
    HEAD, local-branch and stash diffs; cache/online/rejected paths stay in
    inventory and in the original package.  No host path ever applies the
    candidate.
    """
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate_path = package / "retry_candidate.patch"
    inventory_path = package / "retry_candidate_inventory.json"
    if (manifest.get("retry_evidence_ready") is True
            and manifest.get("retry_evidence_schema") == _RETRY_EVIDENCE_SCHEMA
            and candidate_path.is_file() and inventory_path.is_file()):
        return manifest

    repo = _retry_raw_repo(package)
    previous_schema = manifest.get("retry_evidence_schema")
    previous_history = list(manifest.get("retry_evidence_history") or [])
    if previous_schema and previous_schema != _RETRY_EVIDENCE_SCHEMA:
        previous_history.append({
            "schema": previous_schema,
            "materialized_at": manifest.get("retry_evidence_materialized_at"),
            "candidate_bytes": manifest.get("retry_candidate_bytes"),
            "candidate_path_count": manifest.get("retry_candidate_path_count"),
            "candidate_sha256": (
                _file_sha256(candidate_path) if candidate_path.is_file() else ""),
            "migration_note": (
                "Early materializer may have written candidate blobs into the raw "
                "clone object database. Objects are intentionally preserved as "
                "forensic evidence; schema 3 never writes there."),
        })
    if repo is None:
        # Commit/CAS conflict packages can intentionally retain only the verified
        # snapshot.  Promote its accepted-only patch; never fall back to a noisy
        # all-files WIP merely because the raw clone was already discarded.
        validated = package / "validated_candidate.patch"
        if not validated.is_file():
            return manifest
        candidate_temp = package / (
            f".retry_candidate.patch.{os.getpid()}.{threading.get_ident()}.tmp")
        inventory_temp = package / (
            f".retry_candidate_inventory.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            candidate_temp.write_bytes(validated.read_bytes())
            paths = [str(value).replace("\\", "/")
                     for value in (manifest.get("validated_candidate_paths") or [])]
            inventory = {
                "schema": _RETRY_EVIDENCE_SCHEMA,
                "package": package.name,
                "pre_head": str(manifest.get("pre_head") or ""),
                "source": "validated accepted-only snapshot (no raw clone)",
                "auto_apply": False,
                "path_count": len(paths),
                "paths": paths,
                "accepted_candidate_paths": paths,
                "transient_artifact_paths": list(
                    manifest.get("transient_artifact_paths") or []),
                "online_runtime_paths": list(manifest.get("online_runtime_paths") or []),
                "rejected_or_unexpected_paths": list(
                    manifest.get("rejected_or_unexpected_paths") or []),
                "sources": [{
                    "kind": "validated_candidate",
                    "label": "sandbox accepted patch",
                    "accepted_candidate_paths": paths,
                    "candidate_bytes": candidate_temp.stat().st_size,
                }],
            }
            inventory_temp.write_text(
                json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            _replace_with_retry(candidate_temp, candidate_path)
            _replace_with_retry(inventory_temp, inventory_path)
            manifest = dict(manifest)
            manifest.update({
                "retry_evidence_ready": True,
                "retry_evidence_schema": _RETRY_EVIDENCE_SCHEMA,
                "retry_evidence_history": previous_history,
                "retry_evidence_materialized_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "retry_candidate_patch": candidate_path.name,
                "retry_candidate_inventory": inventory_path.name,
                "retry_candidate_bytes": candidate_path.stat().st_size,
                "retry_candidate_path_count": len(paths),
                "retry_inventory_path_count": len(paths),
                "retry_candidate_auto_apply": False,
            })
            _publish_manifest_update(package, manifest)
            return manifest
        finally:
            candidate_temp.unlink(missing_ok=True)
            inventory_temp.unlink(missing_ok=True)
    pre_head = str(manifest.get("pre_head") or "").strip()
    if not pre_head:
        raise OSError(f"失败包 {package.name} 缺少 pre_head，无法物化候选证据")

    index_root = _new_review_temp("sts2-review-retry-index-")
    index_path = index_root / "index"
    object_dir = index_root / "objects"
    object_dir.mkdir()
    candidate_temp = package / (
        f".retry_candidate.patch.{os.getpid()}.{threading.get_ident()}.tmp")
    inventory_temp = package / (
        f".retry_candidate_inventory.{os.getpid()}.{threading.get_ident()}.tmp")
    env = _git_env_with_long_paths()
    env["GIT_INDEX_FILE"] = str(index_path)
    env["GIT_OBJECT_DIRECTORY"] = str(object_dir)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        git_dir_result = _run_captured_stop_aware(
            ["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
            timeout=60)
        if git_dir_result.returncode != 0:
            raise OSError("raw clone Git 目录解析失败：" + git_dir_result.stderr[:400])
        git_dir = Path(git_dir_result.stdout.strip()).resolve()
        source_objects = git_dir / "objects"
        if not source_objects.is_dir():
            raise OSError(f"raw clone Git objects 不存在：{source_objects}")
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(source_objects)
        raw_index_path = git_dir / "index"
        raw_index_env = dict(env)
        raw_index_env["GIT_INDEX_FILE"] = str(raw_index_path)
        verify = _run_captured_stop_aware(
            ["git", "-C", str(repo), "rev-parse", "--verify", f"{pre_head}^{{commit}}"],
            env=env, timeout=60)
        raw_head_result = _run_captured_stop_aware(
            ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD^{commit}"],
            env=env, timeout=60)
        refs_result = _run_captured_stop_aware(
            ["git", "-C", str(repo), "for-each-ref",
             "--format=%(refname)%00%(objectname)%00%(objecttype)%00%(subject)"],
            env=env, timeout=60)
        stash_result = _run_captured_stop_aware(
            ["git", "-C", str(repo), "stash", "list",
             "--format=%gd%x00%H%x00%gs"], env=env, timeout=60)
        raw_index_names = (
            _run_captured_stop_aware(
                ["git", "-C", str(repo), "diff", "--cached", "--name-only", "-z",
                 pre_head, "--"], env=raw_index_env, timeout=120)
            if raw_index_path.is_file()
            else subprocess.CompletedProcess([], 0, "", ""))
        read_tree = _run_captured_stop_aware(
            ["git", "-C", str(repo), "read-tree", pre_head], env=env, timeout=60)
        stage = _run_captured_stop_aware(
            ["git", "-C", str(repo), "add", "--all", "--force", "--", "."],
            env=env, timeout=180)
        names = _run_captured_stop_aware(
            ["git", "-C", str(repo), "diff", "--cached", "--name-only", "-z",
             pre_head, "--"], env=env, timeout=120)
        commands = (verify, raw_head_result, refs_result, stash_result,
                    raw_index_names, read_tree, stage, names)
        if any(item.returncode != 0 for item in commands):
            errors = " ".join((item.stderr or "").strip() for item in commands
                              if item.returncode != 0)
            raise OSError("raw clone 候选 patch 物化失败：" + errors[:800])
        worktree_paths = list(dict.fromkeys(
            value.replace("\\", "/") for value in names.stdout.split("\0") if value))
        accepted, artifacts, online, rejected = _partition_review_changes(worktree_paths)
        raw_index_paths = list(dict.fromkeys(
            value.replace("\\", "/")
            for value in raw_index_names.stdout.split("\0") if value))
        (raw_index_accepted, raw_index_artifacts,
         raw_index_online, raw_index_rejected) = _partition_review_changes(raw_index_paths)

        def path_chunks(values: list[str], budget: int = 8000):
            chunk: list[str] = []
            size = 0
            for value in values:
                cost = len(value) + 3
                if chunk and size + cost > budget:
                    yield chunk
                    chunk, size = [], 0
                chunk.append(value)
                size += cost
            if chunk:
                yield chunk

        candidate_sections: list[bytes] = []
        candidate_hashes: dict[str, str] = {}
        source_inventory: list[dict] = []
        all_paths = [*worktree_paths, *raw_index_paths]
        all_accepted = [*accepted, *raw_index_accepted]
        all_artifacts = [*artifacts, *raw_index_artifacts]
        all_online = [*online, *raw_index_online]
        all_rejected = [*rejected, *raw_index_rejected]

        def export_private_index(kind: str, label: str, object_name: str,
                                 source_paths: list[str], source_accepted: list[str],
                                 source_artifacts: list[str], source_online: list[str],
                                 source_rejected: list[str], *, worktree: bool = False) -> None:
            source = {
                "kind": kind,
                "label": label,
                "object": object_name,
                "paths": source_paths,
                "accepted_candidate_paths": source_accepted,
                "transient_artifact_paths": source_artifacts,
                "online_runtime_paths": source_online,
                "rejected_or_unexpected_paths": source_rejected,
                "candidate_bytes": 0,
            }
            if not source_accepted:
                source_inventory.append(source)
                return
            reset_index = _run_captured_stop_aware(
                ["git", "-C", str(repo), "read-tree", pre_head],
                env=env, timeout=60)
            updates = []
            for chunk in path_chunks(source_accepted):
                args = (["git", "-C", str(repo), "add", "--all", "--force", "--", *chunk]
                        if worktree else
                        ["git", "-C", str(repo), "reset", "--quiet", object_name,
                         "--", *chunk])
                updates.append(_run_captured_stop_aware(args, env=env, timeout=120))
            if reset_index.returncode != 0 or any(item.returncode != 0 for item in updates):
                errors = " ".join((item.stderr or "").strip()
                                  for item in [reset_index, *updates]
                                  if item.returncode != 0)
                source["error"] = errors[:800]
                source_inventory.append(source)
                return
            section_path = index_root / f"candidate-{len(source_inventory)}.patch"
            patch = _run_captured_stop_aware(
                ["git", "-C", str(repo), "diff", "--cached", "--no-ext-diff",
                 "--binary", "--full-index", "--unified=3",
                 f"--output={section_path.as_posix()}", pre_head, "--"],
                env=env, timeout=300)
            if patch.returncode != 0 or not section_path.is_file():
                source["error"] = (patch.stderr or "candidate export failed")[:800]
                source_inventory.append(source)
                return
            payload = section_path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            if digest in candidate_hashes:
                source["duplicate_of"] = candidate_hashes[digest]
            elif payload:
                header = (f"\n# ===== replay evidence: {kind} {label} =====\n"
                          .encode("utf-8", errors="replace"))
                candidate_sections.append(header + payload)
                candidate_hashes[digest] = label
            source["candidate_bytes"] = len(payload)
            source["candidate_sha256"] = digest
            source_inventory.append(source)

        export_private_index(
            "worktree", "raw worktree/index vs pre_head", "WORKTREE",
            worktree_paths, accepted, artifacts, online, rejected, worktree=True)

        def export_raw_index() -> None:
            source = {
                "kind": "raw_index",
                "label": "raw index vs pre_head",
                "object": "INDEX",
                "paths": raw_index_paths,
                "accepted_candidate_paths": raw_index_accepted,
                "transient_artifact_paths": raw_index_artifacts,
                "online_runtime_paths": raw_index_online,
                "rejected_or_unexpected_paths": raw_index_rejected,
                "candidate_bytes": 0,
            }
            if not raw_index_accepted:
                source_inventory.append(source)
                return
            payload_parts: list[bytes] = []
            for chunk_no, chunk in enumerate(path_chunks(raw_index_accepted)):
                section_path = index_root / (
                    f"candidate-{len(source_inventory)}-raw-index-{chunk_no}.patch")
                patch = _run_captured_stop_aware(
                    ["git", "-C", str(repo), "diff", "--cached", "--no-ext-diff",
                     "--binary", "--full-index", "--unified=3",
                     f"--output={section_path.as_posix()}", pre_head, "--", *chunk],
                    env=raw_index_env, timeout=300)
                if patch.returncode != 0 or not section_path.is_file():
                    source["error"] = (
                        patch.stderr or "raw index candidate export failed")[:800]
                    source_inventory.append(source)
                    return
                payload_parts.append(section_path.read_bytes())
            payload = b"".join(payload_parts)
            digest = hashlib.sha256(payload).hexdigest()
            if digest in candidate_hashes:
                source["duplicate_of"] = candidate_hashes[digest]
            elif payload:
                header = b"\n# ===== replay evidence: raw_index raw index vs pre_head =====\n"
                candidate_sections.append(header + payload)
                candidate_hashes[digest] = "raw index vs pre_head"
            source["candidate_bytes"] = len(payload)
            source["candidate_sha256"] = digest
            source_inventory.append(source)

        export_raw_index()

        def parse_ref_lines(text: str, field_count: int) -> list[list[str]]:
            records: list[list[str]] = []
            for line in text.splitlines():
                fields = line.split("\0")
                if len(fields) >= field_count:
                    records.append(fields[:field_count])
            return records

        refs = [{"ref": fields[0], "object": fields[1], "type": fields[2],
                 "subject": fields[3]}
                for fields in parse_ref_lines(refs_result.stdout, 4)]
        stashes = [{"name": fields[0], "object": fields[1], "subject": fields[2]}
                   for fields in parse_ref_lines(stash_result.stdout, 3)]
        for stash in stashes:
            for key, suffix in (("index_parent", "^2"),
                                ("untracked_parent", "^3")):
                parent = _run_captured_stop_aware(
                    ["git", "-C", str(repo), "rev-parse", "--verify",
                     f"{stash['object']}{suffix}^{{commit}}"],
                    env=env, timeout=60)
                if parent.returncode == 0 and parent.stdout.strip():
                    stash[key] = parent.stdout.strip()
        raw_head = raw_head_result.stdout.strip()
        objects: list[tuple[str, str, str, bool]] = []
        if raw_head and raw_head != pre_head:
            objects.append(("head_commit", "HEAD", raw_head, False))
        for item in refs:
            if (item["ref"].startswith("refs/heads/")
                    and item["type"] == "commit" and item["object"] != pre_head):
                objects.append(("local_ref", item["ref"], item["object"], False))
        for item in stashes:
            objects.append(("stash", item["name"], item["object"], False))
            if item.get("index_parent"):
                objects.append(("stash_index", f"{item['name']}^2",
                                item["index_parent"], False))
            if item.get("untracked_parent"):
                objects.append(("stash_untracked", f"{item['name']}^3",
                                item["untracked_parent"], True))
        seen_objects: dict[str, str] = {}
        for kind, label, object_name, tree_paths_only in objects:
            if not object_name:
                continue
            if object_name in seen_objects:
                source_inventory.append({
                    "kind": kind, "label": label, "object": object_name,
                    "duplicate_object_of": seen_objects[object_name],
                    "candidate_bytes": 0,
                })
                continue
            seen_objects[object_name] = label
            object_names = _run_captured_stop_aware(
                (["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "-z",
                  object_name]
                 if tree_paths_only else
                 ["git", "-C", str(repo), "diff", "--name-only", "-z",
                  pre_head, object_name, "--"]), env=env, timeout=120)
            if object_names.returncode != 0:
                source_inventory.append({
                    "kind": kind, "label": label, "object": object_name,
                    "error": (object_names.stderr or "object diff failed")[:800],
                })
                continue
            object_paths = list(dict.fromkeys(
                value.replace("\\", "/")
                for value in object_names.stdout.split("\0") if value))
            obj_accepted, obj_artifacts, obj_online, obj_rejected = \
                _partition_review_changes(object_paths)
            all_paths.extend(object_paths)
            all_accepted.extend(obj_accepted)
            all_artifacts.extend(obj_artifacts)
            all_online.extend(obj_online)
            all_rejected.extend(obj_rejected)
            export_private_index(
                kind, label, object_name, object_paths, obj_accepted,
                obj_artifacts, obj_online, obj_rejected)

        paths = list(dict.fromkeys(all_paths))
        accepted = list(dict.fromkeys(all_accepted))
        artifacts = list(dict.fromkeys(all_artifacts))
        online = list(dict.fromkeys(all_online))
        rejected = list(dict.fromkeys(all_rejected))
        candidate_temp.write_bytes(b"".join(candidate_sections))
        inventory = {
            "schema": _RETRY_EVIDENCE_SCHEMA,
            "package": package.name,
            "pre_head": pre_head,
            "source": "raw_sandbox source-separated private indexes and object directory",
            "auto_apply": False,
            "raw_head": raw_head,
            "refs": refs,
            "stashes": stashes,
            "path_count": len(paths),
            "paths": paths,
            "accepted_candidate_paths": accepted,
            "transient_artifact_paths": artifacts,
            "online_runtime_paths": online,
            "rejected_or_unexpected_paths": rejected,
            "sources": source_inventory,
        }
        inventory_temp.write_text(
            json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        _replace_with_retry(candidate_temp, candidate_path)
        _replace_with_retry(inventory_temp, inventory_path)
        manifest = dict(manifest)
        manifest.update({
            "retry_evidence_ready": True,
            "retry_evidence_schema": _RETRY_EVIDENCE_SCHEMA,
            "retry_evidence_history": previous_history,
            "raw_forensic_note": manifest.get("raw_forensic_note") or (
                "Pre-schema-3 materialization may have added unreachable objects to the "
                "preserved raw clone. They are intentionally retained; schema 3 uses an "
                "isolated object directory and does not mutate raw Git state."),
            "retry_evidence_materialized_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "retry_candidate_patch": candidate_path.name,
            "retry_candidate_inventory": inventory_path.name,
            "retry_candidate_bytes": candidate_path.stat().st_size,
            "retry_candidate_path_count": len(accepted),
            "retry_inventory_path_count": len(paths),
            "retry_candidate_auto_apply": False,
        })
        _publish_manifest_update(package, manifest)
        log(f"[llm] 已从 raw clone 物化 {_review_backend_label(manifest)} "
            f"重审候选证据：{package.name} "
            f"({len(paths)} paths, {candidate_path.stat().st_size} bytes；不会自动应用)")
        return manifest
    finally:
        candidate_temp.unlink(missing_ok=True)
        inventory_temp.unlink(missing_ok=True)
        _discard_owned_review_temp(
            index_root, "sts2-review-retry-index-", log=log)


def _bounded_retry_text(path: Path, limit: int) -> tuple[str, bool, int]:
    """Read a bounded head+tail excerpt so appended reports remain visible."""
    if limit <= 0 or not path.is_file():
        return "", False, 0
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size <= limit:
            payload = handle.read(limit)
            truncated = False
        else:
            marker = b"\n\n[... bounded replay evidence omitted ...]\n\n"
            content_limit = max(0, limit - len(marker))
            head_size = content_limit // 2
            tail_size = content_limit - head_size
            head = handle.read(head_size)
            handle.seek(max(0, size - tail_size))
            tail = handle.read(tail_size)
            payload = head + marker[:limit] + tail
            payload = payload[:limit]
            truncated = True
    return payload.decode("utf-8", errors="replace"), truncated, size


class _RetryEvidenceUnavailable(RuntimeError):
    """The exact requested failed-package lineage cannot be mounted completely."""


def _retry_evidence_relative_path(value: object) -> PurePosixPath:
    """Normalize one Git-relative evidence path without consulting the real tree."""
    pure = PurePosixPath(str(value or "").replace("\\", "/"))
    if (not str(pure) or pure.is_absolute() or ".." in pure.parts
            or any(part in {"", "."} for part in pure.parts)):
        raise _RetryEvidenceUnavailable(f"失败包 inventory 含无效相对路径：{value!r}")
    return pure


def _copy_retry_evidence_file(
    source: Path,
    destination: Path,
    evidence_root: Path,
    records: list[dict],
    *,
    package: str,
    kind: str,
) -> dict:
    """Copy and immediately hash one exact forensic payload file."""
    if source.is_symlink() or not source.is_file():
        raise _RetryEvidenceUnavailable(f"失败包证据文件不可读：{source.name}")
    copied = _copy_snapshot_file(source, destination)
    record = {
        "path": destination.relative_to(evidence_root).as_posix(),
        "package": package,
        "kind": kind,
        "bytes": copied,
        "sha256": _file_sha256(destination),
    }
    records.append(record)
    return record


def _mount_failed_review_evidence(
    sandbox_repo: Path,
    package_names,
    attempt_names=(),
    log=print,
) -> dict:
    """Mount the complete requested lineage as relative, read-only sandbox files.

    This hashes only the exported failure evidence.  It deliberately does not
    fingerprint the repository, worktree, refs, or unrelated runtime state.
    """
    requested = _normalize_salvage_package_names(package_names)
    attempts = [name for name in _normalize_salvage_package_names(attempt_names)
                if name not in requested]
    if not requested:
        return {}
    evidence_root = sandbox_repo.joinpath(*_RETRY_SANDBOX_EVIDENCE_ROOT.parts)
    if evidence_root.exists():
        raise _RetryEvidenceUnavailable("隔离区完整证据目录已存在")
    records: list[dict] = []
    packages: list[dict] = []
    try:
        evidence_root.mkdir(parents=True)
        for name in [*requested, *attempts]:
            role = "target" if name in requested else "attempt_evidence"
            package = _salvage_package_path(name)
            if package is None:
                raise _RetryEvidenceUnavailable(f"失败包不存在：{name}")
            try:
                manifest = _materialize_retry_evidence(package, log=log)
            except (_ReviewStopped, KeyboardInterrupt):
                raise
            except Exception as exc:
                raise _RetryEvidenceUnavailable(
                    f"失败包 {name} 候选证据物化失败：{exc}") from exc
            if (manifest.get("snapshot_deferred")
                    or manifest.get("raw_sandbox_deferred")):
                raise _RetryEvidenceUnavailable(f"失败包仍在异步补全：{name}")
            if (manifest.get("retry_evidence_ready") is not True
                    or manifest.get("retry_evidence_schema") != _RETRY_EVIDENCE_SCHEMA
                    or manifest.get("retry_candidate_patch") != "retry_candidate.patch"
                    or manifest.get("retry_candidate_inventory")
                    != "retry_candidate_inventory.json"):
                raise _RetryEvidenceUnavailable(
                    f"失败包 {name} 未声明 schema {_RETRY_EVIDENCE_SCHEMA} "
                    "完整 retry candidate；wip.patch 不能替代")
            declared_attempts = _normalize_salvage_package_names(
                manifest.get("replay_attempt_packages") or [])
            if role == "target" and set(declared_attempts) != set(attempts):
                raise _RetryEvidenceUnavailable(
                    f"target {name} lineage 与调用参数不一致："
                    f"manifest={declared_attempts}, call={attempts}")
            if role == "attempt_evidence":
                declared_targets = _normalize_salvage_package_names([
                    manifest.get("replay_target")])
                if not declared_targets or declared_targets[0] not in requested:
                    raise _RetryEvidenceUnavailable(
                        f"attempt {name} 未指向本次 target：{requested}")

            missing = [relative for relative in _RETRY_SANDBOX_REQUIRED_FILES
                       if not (package / relative).is_file()]
            patch_files = sorted(
                path for path in package.iterdir()
                if path.is_file() and not path.is_symlink()
                and path.suffix.lower() == ".patch")
            if missing or not patch_files:
                detail = ", ".join(missing) if missing else "*.patch"
                raise _RetryEvidenceUnavailable(
                    f"失败包 {name} 缺少完整证据：{detail}")

            try:
                inventory = json.loads((
                    package / "retry_candidate_inventory.json").read_text(
                        encoding="utf-8"))
                inventory_paths = inventory.get("paths")
                if not isinstance(inventory_paths, list):
                    raise TypeError("paths 不是列表")
                pre_head = str(manifest.get("pre_head") or "")
                candidate_path = package / "retry_candidate.patch"
                if (not pre_head or inventory.get("package") != name
                        or str(inventory.get("pre_head") or "") != pre_head
                        or inventory.get("schema") != _RETRY_EVIDENCE_SCHEMA
                        or not candidate_path.is_file()
                        or candidate_path.stat().st_size
                        != (int(manifest["retry_candidate_bytes"])
                            if manifest.get("retry_candidate_bytes") is not None else -1)):
                    raise ValueError("candidate/inventory 与 manifest 身份或大小不一致")
                file_states = json.loads((package / "file_states.json").read_text(
                    encoding="utf-8"))
                if not isinstance(file_states, list):
                    raise TypeError("file_states 不是列表")
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise _RetryEvidenceUnavailable(
                    f"失败包 {name} inventory 不完整：{exc}") from exc

            package_root = evidence_root / "packages" / name
            root_file_records: list[str] = []
            # Every direct metadata/report/patch file is useful evidence.  The
            # enormous raw clone is represented below by its exact changed files,
            # while remaining preserved in the original failure package.
            for source in sorted(
                    path for path in package.iterdir()
                    if path.is_file() and not path.name.startswith(".")):
                record = _copy_retry_evidence_file(
                    source, package_root / source.name, evidence_root, records,
                    package=name, kind="package_root")
                root_file_records.append(record["path"])

            captured_records: list[str] = []
            captured_root = package / "files"
            if not captured_root.is_dir():
                raise _RetryEvidenceUnavailable(
                    f"失败包 {name} 缺少 changed-files 快照目录")
            for source in sorted(captured_root.rglob("*")):
                if source.is_symlink():
                    raise _RetryEvidenceUnavailable(
                        f"失败包 {name} changed-files 含未物化链接")
                if not source.is_file():
                    continue
                relative = source.relative_to(captured_root)
                record = _copy_retry_evidence_file(
                    source, package_root / "captured_files" / relative,
                    evidence_root, records, package=name, kind="captured_changed_file")
                captured_records.append(record["path"])

            raw_repo = _retry_raw_repo(package)
            changed_states: list[dict] = []
            seen_paths: set[str] = set()
            for raw_path in inventory_paths:
                pure = _retry_evidence_relative_path(raw_path)
                relative = pure.as_posix()
                if relative in seen_paths:
                    continue
                seen_paths.add(relative)
                state = {"path": relative}
                if raw_repo is None:
                    state["state"] = "raw_clone_unavailable"
                else:
                    source = raw_repo.joinpath(*pure.parts)
                    if source.is_symlink():
                        state.update({
                            "state": "symlink",
                            "target": os.readlink(source),
                        })
                    elif source.is_file():
                        record = _copy_retry_evidence_file(
                            source,
                            package_root / "changed_files" / "raw_worktree"
                            / Path(*pure.parts),
                            evidence_root, records, package=name,
                            kind="raw_worktree_changed_file")
                        state.update({
                            "state": "file",
                            "evidence_path": record["path"],
                            "bytes": record["bytes"],
                            "sha256": record["sha256"],
                        })
                    elif source.exists():
                        state["state"] = "special"
                    else:
                        # Deletions have no file bytes; the full binary patch and
                        # this explicit state together are their complete evidence.
                        state["state"] = "deleted_or_source_only"
                changed_states.append(state)

            packages.append({
                "package": name,
                "role": role,
                "manifest_pre_head": str(manifest.get("pre_head") or ""),
                "root_files": root_file_records,
                "candidate_patches": [
                    f"packages/{name}/{path.name}" for path in patch_files],
                "captured_changed_files": captured_records,
                "changed_file_states": changed_states,
                "inventory_path_count": len(seen_paths),
                "raw_clone_export": (
                    "exact inventory paths only; original raw_sandbox remains in "
                    "the failure package"),
            })

        index = {
            "schema": _RETRY_SANDBOX_EVIDENCE_SCHEMA,
            "complete": True,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "relative_root": _RETRY_SANDBOX_EVIDENCE_ROOT.as_posix(),
            "requested_packages": requested,
            "attempt_packages": attempts,
            "packages": packages,
            "files": records,
            "file_count": len(records),
            "total_bytes": sum(int(record["bytes"]) for record in records),
            "integrity_scope": (
                "only the mounted failed-package evidence; no repository, ref, "
                "worktree, or full-tree fingerprint"),
            "auto_apply": False,
        }
        index_path = sandbox_repo.joinpath(*_RETRY_SANDBOX_EVIDENCE_INDEX.parts)
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        index_bytes = index_path.stat().st_size
        index_sha256 = _file_sha256(index_path)
        for record in records:
            path = evidence_root.joinpath(*PurePosixPath(record["path"]).parts)
            os.chmod(path, stat.S_IREAD)
        os.chmod(index_path, stat.S_IREAD)
        log("[llm] 已挂载失败包完整只读证据："
            f"{len(packages)} packages, {len(records)} files, "
            f"{index['total_bytes']} bytes；索引 {_RETRY_SANDBOX_EVIDENCE_INDEX.as_posix()}")
        return {
            "root": evidence_root,
            "index_path": index_path,
            "index": index,
            "index_bytes": index_bytes,
            "index_sha256": index_sha256,
        }
    except BaseException:
        _remove_failed_review_evidence(sandbox_repo, log=log)
        raise


def _verify_failed_review_evidence(sandbox_repo: Path, mount: dict) -> None:
    """Verify the exact mounted payload after GLM exits, before accepting receipts."""
    if not mount:
        return
    index_path = Path(mount["index_path"])
    if (not index_path.is_file()
            or index_path.stat().st_size != int(mount["index_bytes"])
            or _file_sha256(index_path) != mount["index_sha256"]):
        raise _RetryEvidenceUnavailable("完整证据 index.json 在复盘期间被修改或删除")
    evidence_root = Path(mount["root"])
    for record in mount["index"]["files"]:
        pure = _retry_evidence_relative_path(record["path"])
        path = evidence_root.joinpath(*pure.parts)
        if (not path.is_file() or path.stat().st_size != int(record["bytes"])
                or _file_sha256(path) != record["sha256"]):
            raise _RetryEvidenceUnavailable(
                f"完整证据在复盘期间不完整：{record['path']}")


def _remove_failed_review_evidence(sandbox_repo: Path, log=print) -> bool:
    """Remove only this clone's deterministic evidence mount before Git inventory."""
    root = sandbox_repo.joinpath(*_RETRY_SANDBOX_EVIDENCE_ROOT.parts)
    if not root.exists():
        return True
    try:
        resolved_repo = sandbox_repo.resolve()
        resolved = root.resolve()
        expected = resolved_repo.joinpath(*_RETRY_SANDBOX_EVIDENCE_ROOT.parts)
        if resolved != expected or not resolved.is_relative_to(resolved_repo):
            log(f"[llm] 完整证据目录归属校验失败，保留：{root}")
            return False
    except OSError as exc:
        log(f"[llm] 完整证据目录读取失败，保留：{root}（{exc}）")
        return False
    last_error: OSError | None = None
    for delay in (0.0, 0.05, 0.15, 0.3):
        if delay:
            time.sleep(delay)
        try:
            shutil.rmtree(resolved, onerror=_remove_readonly_for_rmtree)
            return True
        except OSError as exc:
            last_error = exc
    log(f"[llm] 完整证据目录清理失败，保留隔离现场：{root}（{last_error}）")
    return False


def _preserve_provider_transcript(
    sandbox_repo: Path, result: SandboxReviewResult, transcript_rel: str, log=print,
) -> None:
    """Bind the raw provider JSONL to a real path in any future failure package."""
    result.provider_transcript_rel = ""
    source = sandbox_repo / transcript_rel
    if not source.is_file():
        return
    if result.retained_sandbox_dir:
        result.provider_transcript_rel = (
            "raw_sandbox/repo/.git/sts2-review-provider-events.jsonl")
        return
    if not result.snapshot_dir:
        return
    try:
        if _review_stop_requested():
            raise _ReviewStopped()
        destination = Path(result.snapshot_dir) / "provider_events.jsonl"
        _copy_snapshot_file(source, destination)
        # Non-deferred snapshots are copied directly into the package root.
        result.provider_transcript_rel = "provider_events.jsonl"
    except _ReviewStopped:
        result.stopped = True
        result.retained_sandbox_dir = str(sandbox_repo.parent)
        result.provider_transcript_rel = (
            "raw_sandbox/repo/.git/sts2-review-provider-events.jsonl")
    except OSError as exc:
        result.retained_sandbox_dir = str(sandbox_repo.parent)
        result.provider_transcript_rel = (
            "raw_sandbox/repo/.git/sts2-review-provider-events.jsonl")

        log(f"[llm] provider 原始事件流快照失败；保留其他失败证据：{exc}")


def _failed_review_replay_context(package_names, attempt_names=(), log=print) -> dict:
    """Inline one target lineage with a fixed total budget and explicit roles."""
    requested = _normalize_salvage_package_names(package_names)
    attempts = [name for name in _normalize_salvage_package_names(attempt_names)
                if name not in requested]
    evidence_names = [*requested, *attempts]
    packet = {
        "requested_packages": requested,
        "attempt_packages": attempts,
        "packages": [],
        "total_budget_bytes": _RETRY_REPLAY_TOTAL_BYTES,
        "inline_content_role": (
            "navigation summary only; truncation never implies complete evidence"),
        "complete_evidence": {
            "required": bool(requested),
            "relative_root": _RETRY_SANDBOX_EVIDENCE_ROOT.as_posix(),
            "index": _RETRY_SANDBOX_EVIDENCE_INDEX.as_posix(),
            "integrity": "per-file byte size and SHA-256",
            "missing_or_incomplete_action": "write still_pending; host keeps target queued",
            "auto_apply": False,
        },
        "auto_apply": False,
        "review_contract": (
            "The review model must compare this evidence with current HEAD, selectively reimplement "
            "still-valid changes, resolve conflicts, and run selfcheck; host never applies it."),
    }
    if not requested:
        return packet
    # A growing attempt history must never starve the original target patch.
    # Reserve 60% for target evidence.  The newest three attempts share most of
    # the remainder; older attempts contribute manifest/inventory summaries only.
    target_pool = (_RETRY_REPLAY_TOTAL_BYTES if not attempts
                   else _RETRY_REPLAY_TOTAL_BYTES * 3 // 5)
    target_each = max(1, target_pool // max(1, len(requested)))
    attempt_pool = max(0, _RETRY_REPLAY_TOTAL_BYTES - target_each * len(requested))
    recent_attempts = set(attempts[-3:])
    historical = [name for name in attempts if name not in recent_attempts]
    historical_pool = min(attempt_pool // 4, len(historical) * 1024)
    historical_each = (historical_pool // len(historical)) if historical else 0
    recent_pool = max(0, attempt_pool - historical_each * len(historical))
    recent_each = recent_pool // max(1, len(recent_attempts))
    package_budgets = {
        **{name: target_each for name in requested},
        **{name: historical_each for name in historical},
        **{name: recent_each for name in recent_attempts},
    }
    packet["budget_allocation"] = {
        "target_bytes_each": target_each,
        "recent_attempt_bytes_each": recent_each,
        "historical_attempt_summary_bytes_each": historical_each,
        "recent_attempt_count": len(recent_attempts),
    }
    for name in evidence_names:
        role = "target" if name in requested else "attempt_evidence"
        package_budget = max(0, package_budgets.get(name, 0))
        if role == "target":
            manifest_budget = min(8 * 1024, package_budget // 20)
            inventory_budget = min(16 * 1024, package_budget // 10)
            report_budget = min(24 * 1024, package_budget * 15 // 100)
            patch_budget = max(
                0, package_budget - manifest_budget - inventory_budget - report_budget)
        elif name in recent_attempts:
            manifest_budget = min(16 * 1024, package_budget * 20 // 100)
            inventory_budget = min(16 * 1024, package_budget * 20 // 100)
            report_budget = min(32 * 1024, package_budget * 25 // 100)
            patch_budget = max(
                0, package_budget - manifest_budget - inventory_budget - report_budget)
        else:
            manifest_budget = package_budget // 2
            inventory_budget = package_budget - manifest_budget
            report_budget = 0
            patch_budget = 0
        package = _salvage_package_path(name)
        if package is None:
            packet["packages"].append({
                "package": name, "role": role, "available": False,
                "error": "failure package is missing; keep pending",
            })
            continue
        materialization_error = ""
        try:
            _materialize_retry_evidence(package, log=log)
        except (_ReviewStopped, KeyboardInterrupt):
            raise
        except Exception as exc:
            materialization_error = str(exc)[:800]
            log(f"[llm] 失败包 {name} 候选证据暂未物化；仍回灌现有报告/WIP：{exc}")
        candidate = package / "retry_candidate.patch"
        candidate_source = "retry_candidate.patch"
        if not candidate.is_file():
            candidate = package / "validated_candidate.patch"
            candidate_source = "validated_candidate.patch"
        if not candidate.is_file():
            candidate = package / "wip.patch"
            candidate_source = "wip.patch (full forensic fallback)"
        manifest_text, manifest_truncated, manifest_size = _bounded_retry_text(
            package / "manifest.json", manifest_budget)
        inventory_text, inventory_truncated, inventory_size = _bounded_retry_text(
            package / "retry_candidate_inventory.json", inventory_budget)
        report_text, report_truncated, report_size = _bounded_retry_text(
            package / "report.md", report_budget)
        patch_text, patch_truncated, patch_size = _bounded_retry_text(
            candidate, patch_budget)
        packet["packages"].append({
            "package": name,
            "role": role,
            "inline_budget_bytes": package_budget,
            "available": True,
            "materialization_error": materialization_error,
            "manifest": manifest_text,
            "manifest_bytes": manifest_size,
            "manifest_truncated": manifest_truncated,
            "inventory": inventory_text,
            "inventory_bytes": inventory_size,
            "inventory_truncated": inventory_truncated,
            "report": report_text,
            "report_bytes": report_size,
            "report_truncated": report_truncated,
            "candidate_source": candidate_source,
            "candidate_patch": patch_text,
            "candidate_patch_bytes": patch_size,
            "candidate_patch_truncated": patch_truncated,
            "auto_apply": False,
        })
    return packet


def _review_retry_feedback(package_names, attempt_names=()) -> dict:
    """Build a small, actionable retry card from the exact preserved attempts."""
    requested = _normalize_salvage_package_names(package_names)
    attempts = [name for name in _normalize_salvage_package_names(attempt_names)
                if name not in requested]
    rows: list[dict] = []
    access_markers = (
        "blocked by policy", "access is denied", "permission denied",
        "拒绝启动任何本地 shell",
    )
    for name in [*requested, *attempts]:
        package = _salvage_package_path(name)
        if package is None:
            rows.append({"package": name, "available": False})
            continue
        try:
            manifest = json.loads(
                (package / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            manifest = {}
        try:
            output_tail = (package / "model_output_tail.txt").read_text(
                encoding="utf-8", errors="replace")[-32 * 1024:]
        except OSError:
            output_tail = ""
        access_line = next((
            " ".join(line.split())[:600]
            for line in output_tail.splitlines()
            if any(marker in line.casefold() for marker in access_markers)
        ), "")
        metrics = (manifest.get("provider_metrics")
                   if isinstance(manifest.get("provider_metrics"), dict) else {})
        failure_code = str(manifest.get("failure_code") or "")
        if not failure_code and access_line:
            failure_code = "runner_tool_access_denied"
        selfcheck_state = str(manifest.get("selfcheck_state") or "")
        if not selfcheck_state:
            legacy = manifest.get("selfcheck_ok")
            try:
                legacy_patch_bytes = int(manifest.get("patch_bytes") or 0)
            except (TypeError, ValueError):
                legacy_patch_bytes = 0
            selfcheck_state = (
                "passed" if legacy is True and legacy_patch_bytes > 0 else
                "failed" if legacy is False else "not_run")
        rows.append({
            "package": name,
            "role": "target" if name in requested else "attempt_evidence",
            "available": True,
            "failure_code": failure_code or str(manifest.get("failure_kind") or ""),
            "host_reason": str(manifest.get("reason") or "")[:800],
            "return_code": manifest.get("return_code"),
            "selfcheck_state": selfcheck_state,
            "command_count": metrics.get("command_count", 0),
            "file_change_count": metrics.get("file_change_count", 0),
            "blocked_tool_count": metrics.get("blocked_tool_count", 0),
            "patch_bytes": manifest.get("patch_bytes", 0),
            "tool_access_error": (
                str(metrics.get("tool_access_error") or "")[:600] or access_line),
            "attempt_no": manifest.get("replay_attempt_no", 0),
        })
    return {
        "active": bool(requested),
        "lineage_attempt_count": len(attempts),
        "previous_attempts": rows,
        "correction_contract": (
            "Do not repeat the previous terminal state. If tools are blocked, emit "
            "BLOCKED_TOOL_CAPABILITY with the original error. Otherwise finish one "
            "implemented production loop, or use no_valid_change only after reading "
            "the complete replay evidence and giving a verifiable receipt."),
    }


def _parse_retry_resolutions(report: str, package_names) -> dict[str, str]:
    """Parse only explicit per-package receipts; absence remains non-fatal.

    GLM normally emits the documented colon form, but Markdown-oriented models
    sometimes put the same receipt in a two- or three-column table.  Keep this
    deliberately strict: the marker must own the line/cell, the package must be
    one of the exact requested ids, and the payload must contain exactly one
    package/status pair.  This prevents explanatory prose from closing evidence.
    """
    requested = set(_normalize_salvage_package_names(package_names))
    found: dict[str, str] = {}

    def unformat(value: str) -> str:
        text = str(value or "").strip()
        wrappers = (("**", "**"), ("__", "__"), ("`", "`"))
        changed = True
        while changed and text:
            changed = False
            for opening, closing in wrappers:
                if (text.startswith(opening) and text.endswith(closing)
                        and len(text) >= len(opening) + len(closing)):
                    text = text[len(opening):-len(closing)].strip()
                    changed = True
                    break
        return text

    def parse_pair(value: str) -> tuple[str, str] | None:
        text = str(value or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            return None
        package = unformat(parts[0]).strip("`*<>,;:[]()")
        if package not in requested:
            return None
        remainder = parts[1].lstrip("`*_")
        for resolution in _RETRY_RESOLUTION_VALUES:
            if not remainder.startswith(resolution):
                continue
            tail = remainder[len(resolution):].lstrip("`*_ ")
            # GLM often appends a short parenthetical/table note immediately
            # after the formal status.  Accept punctuation-delimited notes while
            # still rejecting free prose such as "integrated because ...".
            if not tail or tail[0] in "(（[【:：-—,，;；.。/":
                return package, resolution
        return None

    for raw_line in str(report or "").splitlines():
        line = raw_line.strip()
        parsed: tuple[str, str] | None = None
        if line.startswith("|") and line.endswith("|"):
            cells = [unformat(cell) for cell in line[1:-1].split("|")]
            if len(cells) in {2, 3} and cells[0] == "retry_resolution":
                parsed = parse_pair(cells[1])
                if parsed is None and len(cells) == 3:
                    parsed = parse_pair(f"{cells[1]} {cells[2]}")
        else:
            if line.startswith(("- ", "* ", "+ ")):
                line = line[2:].lstrip()
            line = unformat(line)
            marker = "retry_resolution:"
            if line.startswith(marker):
                parsed = parse_pair(line[len(marker):].strip())
        if parsed is not None:
            package, resolution = parsed
            found[package] = resolution
    return found


def _validated_retry_resolutions(
    sandbox: SandboxReviewResult,
    package_names,
    log=print,
) -> dict[str, str]:
    """Accept GLM receipts only after complete mounted evidence was verified."""
    requested = _normalize_salvage_package_names(package_names)
    if not requested:
        return {}
    if (not sandbox.replay_evidence_requested
            or not sandbox.replay_evidence_complete):
        log("[llm] 失败包完整证据未通过校验；忽略本轮全部 retry_resolution，"
            "target 保持 pending")
        return {}
    return _parse_retry_resolutions(sandbox.diagnostic_report, requested)


_RETRY_RECEIPT_HISTORY_LIMIT = 256


def _committed_retry_resolutions(package_names, log=print) -> dict[str, tuple[str, str]]:
    """Find exact receipts added by upstream commits, with their commit ids.

    Reading the current report alone is unsafe because every later commit also
    contains historical text.  Inspect only added lines in each report-changing
    upstream commit.  An ``integrated`` receipt additionally requires a
    substantive production action in that same commit; ``no_valid_change`` is
    intentionally allowed to be report-only by the replay contract.
    """
    requested = set(_normalize_salvage_package_names(package_names))
    upstream = _upstream_ref()
    if not requested or not upstream or _review_stop_requested():
        return {}
    try:
        report_path = REVIEW_LOG.relative_to(REPO_DIR).as_posix()
    except ValueError:
        return {}

    def git_text(arguments: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(REPO_DIR), *arguments], capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=30)

    try:
        history = git_text([
            "log", "--format=%H", f"--max-count={_RETRY_RECEIPT_HISTORY_LIMIT}",
            upstream, "--", report_path,
        ])
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if history.returncode != 0:
        return {}

    found: dict[str, tuple[str, str]] = {}
    remaining = set(requested)
    for commit in history.stdout.splitlines():
        commit = commit.strip()
        if not commit or not remaining or _review_stop_requested():
            break
        try:
            report_diff = git_text([
                "show", "--format=", "--no-ext-diff", "--no-renames",
                "--unified=0", commit, "--", report_path,
            ])
        except (OSError, subprocess.TimeoutExpired):
            continue
        if report_diff.returncode != 0:
            continue
        added_report = "\n".join(
            line[1:] for line in report_diff.stdout.splitlines()
            if line.startswith("+") and not line.startswith("+++"))
        resolutions = _parse_retry_resolutions(added_report, remaining)
        if not resolutions:
            continue

        integrated = {
            name for name, resolution in resolutions.items()
            if resolution == "integrated"
        }
        has_action = False
        if integrated:
            try:
                changed = git_text([
                    "diff-tree", "--root", "--no-commit-id", "--name-only",
                    "-r", commit, "--",
                ])
                paths = (changed.stdout.splitlines()
                         if changed.returncode == 0 else [])
                action_paths = _review_action_paths(paths)
                if action_paths:
                    action_diff = git_text([
                        "show", "--format=", "--no-ext-diff", "--no-renames",
                        "--unified=1", commit, "--", *action_paths,
                    ])
                    has_action = (action_diff.returncode == 0
                                  and _patch_has_substantive_action(
                                      action_diff.stdout, action_paths))
            except (OSError, subprocess.TimeoutExpired):
                has_action = False

        for name, resolution in resolutions.items():
            if resolution == "integrated" and not has_action:
                log(f"[llm] 上游回执 {commit[:8]} 声称 {name} integrated，"
                    "但同一提交没有生产实质变更；继续保留失败包")
                continue
            if resolution not in {"integrated", "no_valid_change"}:
                continue
            found[name] = (resolution, commit)
            remaining.discard(name)
    return found


def _recover_committed_retry_resolutions(log=print) -> list[str]:
    """Persist missed upstream receipts so normal host closure can resume.

    This is a parser/crash recovery bridge, not an alternate delete path.  It
    writes the same durable manifest receipt as a live successful replay; queue
    acknowledgement, ledger finalization and exact package cleanup remain owned
    by the existing host transaction.
    """
    if not SALVAGE_ROOT.is_dir() or _review_stop_requested():
        return []
    targets: dict[str, list[str]] = {}
    for package in sorted(SALVAGE_ROOT.iterdir(), key=lambda path: path.name):
        manifest_path = package / "manifest.json"
        if (not package.is_dir() or package.name.startswith(_CLOSED_SALVAGE_PREFIX)
                or not manifest_path.is_file()):
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if (manifest.get("replay_enqueue_pending") is not True
                or manifest.get("retry_resolution_state") in {
                    "claimed_pending_code_push", "code_upstream_confirmed",
                    "quarantined_pending_ledger", "ledger_final_upstream", "done",
                }):
            continue
        normalized = _normalize_salvage_package_names([
            manifest.get("replay_target") or package.name])
        if not normalized:
            continue
        target = normalized[0]
        if package.name != target and manifest.get("replay_role") != "target":
            continue
        targets[target] = _normalize_salvage_package_names(
            manifest.get("replay_attempt_packages") or [])
    receipts = _committed_retry_resolutions(targets, log=log)
    recovered: list[str] = []
    for target, attempts in targets.items():
        receipt = receipts.get(target)
        if receipt is None or _review_stop_requested():
            continue
        resolution, commit = receipt
        # Recheck immediately before the durable write in case the tracked
        # upstream moved while history was inspected.
        if not _upstream_contains_commit(commit):
            continue
        _close_replayed_salvages(
            [target], attempts, {target: resolution}, commit=commit,
            pushed=True, log=log)
        package = _salvage_package_path(target)
        try:
            persisted = json.loads((
                package / "manifest.json").read_text(encoding="utf-8"))
        except (AttributeError, FileNotFoundError, OSError, ValueError,
                TypeError, json.JSONDecodeError):
            persisted = {}
        receipt_persisted = bool(
            persisted.get("retry_resolution") == resolution
            and persisted.get("retry_resolution_commit") == commit
            and persisted.get("retry_resolution_state") in {
                "claimed_pending_code_push", "code_upstream_confirmed",
                "quarantined_pending_ledger", "ledger_final_upstream", "done",
            })
        if receipt_persisted:
            recovered.append(target)
            log(f"[llm] 已从上游提交 {commit[:8]} 恢复失败包回执："
                f"{target} {resolution}")
    return recovered


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save_review_salvage(
    pre_head: str, reason: str, sandbox: SandboxReviewResult, *,
    batch_runs: list[int] | None = None, runner: str = "opencode",
    model: str = "", source: str = "", backend_key: str = "",
    variant: str = "", reasoning_effort: str = "",
    priority: int = 1, approve_for_me: bool = False,
    sandbox_mode: str = "workspace-write",
    every: int | None = None, replay_target: str = "",
    replay_attempts: list[str] | None = None,
    replay_queue_ids: list[str] | None = None,
    review_attempt_id: str = "", review_sandbox_name: str = "",
    review_attempt_receipt_schema: int = 0,
    startup_orphan_recovery: bool = False,
    prompt_text: str = "", invocation_prompt: str = "", log=print,
) -> Path | None:
    """原子保存全部失败成果供同一复盘模型重审；永不自动应用。"""
    if sandbox.salvage_saved:
        saved = Path(sandbox.salvage_saved)
        try:
            manifest = json.loads((saved / "manifest.json").read_text(encoding="utf-8"))
            _record_review_rejection(saved, manifest, log=log)
        except (OSError, ValueError, TypeError):
            pass
        return saved

    backend_fields = {
        "runner": runner,
        "model": model,
        "backend_key": backend_key,
        "variant": variant,
        "reasoning_effort": reasoning_effort,
    }
    backend_label = _review_backend_label(backend_fields)
    if sandbox.stopped:
        reason = (f"维护停机取消 {backend_label} 复盘并全量保全；"
                  "非模型提交失败")
    snapshot = Path(sandbox.snapshot_dir) if sandbox.snapshot_dir else None
    retained = Path(sandbox.retained_sandbox_dir) if sandbox.retained_sandbox_dir else None
    deferred_raw = bool(sandbox.stopped and retained is not None)
    deferred_snapshot = bool(sandbox.stopped and snapshot is not None)
    snapshot_patch = snapshot / "wip.patch" if snapshot is not None else None
    patch = sandbox.wip_patch or sandbox.patch
    if deferred_raw or deferred_snapshot:
        # Stop 临界区不扫描、hash 或复制任何大文件；指针发布后由新 worker 补齐。
        patch_bytes = -1
        patch_sha256 = ""
    elif snapshot_patch is not None and snapshot_patch.is_file():
        try:
            patch_bytes = snapshot_patch.stat().st_size
            # 大补丁的 hash 由异步恢复/人工分析按需计算；失败保存主路径只做
            # O(1) stat，避免 stop 恰落在多 GB hash 时卡住直播热切换。
            patch_sha256 = ""
        except OSError as exc:
            log(f"[llm] 补合 patch 摘要计算失败，仍保存全量现场：{exc}")
            patch_bytes = -1
            patch_sha256 = ""
    else:
        patch_bytes = len(patch)
        patch_sha256 = hashlib.sha256(patch).hexdigest()
    all_paths = tuple(sandbox.wip_paths or sandbox.paths)
    allowed_paths = tuple(sandbox.allowed_paths or (
        sandbox.paths if sandbox.patch else ()))
    now_ns = time.time_ns()
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{now_ns}-{pre_head[:8] or 'nohead'}"
    existing_attempts = _normalize_salvage_package_names(replay_attempts or [])
    target_name = _normalize_salvage_package_names([replay_target])
    target_name = target_name[0] if target_name else name
    replay_role = "attempt_evidence" if target_name != name else "target"
    queue_ids = list(dict.fromkeys(
        str(value) for value in (replay_queue_ids or []) if str(value)))
    final = SALVAGE_ROOT / name
    temp = SALVAGE_ROOT / f".{name}.tmp-{os.getpid()}-{threading.get_ident()}"
    manifest = {
        "schema": 1,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "failure_kind": _salvage_kind(reason, sandbox),
        "failure_code": str(sandbox.failure_code or ""),
        "reason": reason,
        "pre_head": pre_head,
        "current_head": _current_head_for_salvage(),
        "batch_runs": list(batch_runs or []),
        "runner": runner,
        "model": model,
        "backend_key": backend_key,
        "backend_label": backend_label,
        "priority": max(1, int(priority)),
        "variant": variant,
        "reasoning_effort": reasoning_effort,
        "approve_for_me": bool(approve_for_me),
        "sandbox": str(sandbox_mode or "workspace-write"),
        "source": source,
        "every": every,
        "retry_same_model": bool(
            getattr(sandbox, "provider_work_started", False)),
        "return_code": sandbox.rc,
        "timed_out": sandbox.timed_out,
        "stalled": sandbox.stalled,
        "stopped": sandbox.stopped,
        "selfcheck_ok": sandbox.selfcheck_ok,
        "selfcheck_state": (
            "passed" if sandbox.selfcheck_ok is True else
            "failed" if sandbox.selfcheck_ok is False else "not_run"),
        "provider_metrics": (
            dict(sandbox.provider_metrics)
            if isinstance(getattr(sandbox, "provider_metrics", None), dict)
            else {}),
        "provider_work_started": bool(
            getattr(sandbox, "provider_work_started", False)),
        "provider_transcript_rel": (
            sandbox.provider_transcript_rel
            if isinstance(getattr(sandbox, "provider_transcript_rel", None), str)
            else ""),
        "snapshot_complete": sandbox.snapshot_complete,
        "snapshot_included": bool(snapshot is not None and not deferred_snapshot and not deferred_raw),
        "snapshot_deferred": deferred_snapshot,
        "raw_sandbox_included": bool(retained is not None and not deferred_raw),
        "raw_sandbox_deferred": deferred_raw,
        "all_paths": list(all_paths),
        "allowed_paths": list(allowed_paths),
        "transient_artifact_paths": list(sandbox.artifact_paths),
        "online_runtime_paths": list(sandbox.online_paths),
        "rejected_or_unexpected_paths": list(sandbox.unexpected_paths),
        "sandbox_sibling_paths": list(sandbox.sibling_paths),
        "patch_bytes": patch_bytes,
        "patch_sha256": patch_sha256,
        "auto_apply": False,
        # This linkage is published in the same atomic package rename as the
        # forensic bytes.  A crash before the worker can update review_queue.json
        # is therefore recoverable and idempotently becomes exactly one target job.
        "replay_enqueue_pending": True,
        "replay_target": target_name,
        "replay_role": replay_role,
        "replay_attempt_no": len(existing_attempts) + (1 if replay_role == "attempt_evidence" else 0),
        "replay_parent_attempt": (
            existing_attempts[-1] if existing_attempts else (
                target_name if replay_role == "attempt_evidence" else "")),
        "replay_attempt_packages": ([] if replay_role == "target" else None),
        "replay_queue_ids": queue_ids,
        "startup_orphan_recovery": bool(startup_orphan_recovery),
        "review_attempt_id": str(review_attempt_id or ""),
        "review_sandbox_name": str(review_sandbox_name or ""),
        "review_attempt_receipt_schema": max(
            0, int(review_attempt_receipt_schema or 0)),
        "prompt_snapshot": "review_prompt.md" if prompt_text and not sandbox.stopped else "",
        "prompt_bytes": len(prompt_text.encode("utf-8")) if prompt_text else 0,
        "prompt_sha256": (
            hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
            if prompt_text else ""),
        "invocation_prompt_snapshot": (
            "invocation_prompt.txt" if invocation_prompt and not sandbox.stopped else ""),
        "inspection_hint": (
            f"files/ 与 wip.patch 是全量现场；宿主只将其作为证据交回 {backend_label}，"
            "由模型基于当前 HEAD 重审、解冲突、自检，禁止宿主自动应用。"),
    }
    try:
        SALVAGE_ROOT.mkdir(parents=True, exist_ok=True)
        temp.mkdir()
        if deferred_raw or deferred_snapshot:
            # Stop 临界区不复制任何可能很大的文件；只发布很小的持久指针包。
            # 新 Brain 启动后在后台把完整快照搬入本包。
            (temp / "files").mkdir()
            (temp / "file_states.json").write_text("[]\n", encoding="utf-8")
        elif snapshot is not None and snapshot.is_dir():
            shutil.copytree(
                snapshot, temp, dirs_exist_ok=True,
                copy_function=_copy_snapshot_file)
        else:
            (temp / "files").mkdir()
            (temp / "file_states.json").write_text("[]\n", encoding="utf-8")
        if deferred_raw:
            (temp / "raw_sandbox_pointer.txt").write_text(
                str(retained) + "\n", encoding="utf-8")
        if deferred_snapshot:
            (temp / "snapshot_pointer.txt").write_text(
                str(snapshot) + "\n", encoding="utf-8")
        if not deferred_raw and retained is not None and retained.is_dir():
            # 捕获链自身失败时，宁可保存完整 clone（含 .git 与所有 ignored/越界
            # 内容）供分析。symlinks=True 只复制链接本身，不跟随到隔离仓外。
            raw_target = temp / "raw_sandbox"
            shutil.copytree(
                retained, raw_target, dirs_exist_ok=True,
                symlinks=True, ignore_dangling_symlinks=True,
                copy_function=_copy_snapshot_file)
        # 固定三件套始终存在；snapshot 缺失时仍发布空/已有 patch 供诊断。
        if not (temp / "wip.patch").is_file():
            (temp / "wip.patch").write_bytes(patch)
        # The all-files WIP remains forensic truth.  Keep the already validated,
        # accepted-only patch separately so commit/CAS failures without a raw clone
        # never force the next GLM to consume cache/runtime noise as its candidate.
        if sandbox.patch:
            (temp / "validated_candidate.patch").write_bytes(sandbox.patch)
            manifest.update({
                "validated_candidate_patch": "validated_candidate.patch",
                "validated_candidate_bytes": len(sandbox.patch),
                "validated_candidate_sha256": hashlib.sha256(sandbox.patch).hexdigest(),
                "validated_candidate_paths": list(allowed_paths),
                "validated_candidate_auto_apply": False,
            })
        (temp / "report.md").write_text(
            sandbox.diagnostic_report or "", encoding="utf-8")
        if sandbox.out:
            (temp / "model_output_tail.txt").write_text(
                sandbox.out[-256 * 1024:], encoding="utf-8")
        if prompt_text and not sandbox.stopped:
            (temp / "review_prompt.md").write_text(prompt_text, encoding="utf-8")
        if invocation_prompt and not sandbox.stopped:
            (temp / "invocation_prompt.txt").write_text(
                invocation_prompt, encoding="utf-8")
        (temp / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if _review_stop_requested() and not (deferred_raw or deferred_snapshot):
            raise _ReviewStopped()
        _replace_with_retry(temp, final)
        sandbox.salvage_saved = str(final)
        if not deferred_snapshot:
            _discard_sandbox_snapshot(sandbox, log=log)
        if not deferred_raw:
            _discard_retained_sandbox(sandbox, log=log)
        log(f"[llm] 失败复盘成果已保存供补合（不会自动应用）：{final}")
        _record_review_rejection(final, manifest, log=log)
        return final
    except _ReviewStopped:
        # stop 可能在普通失败包 copy 途中才到达。绝不删除半包或系统临时源；
        # 原子发布“已有部分 + 全量源指针”，新 Brain 再异步补齐。
        sandbox.stopped = True
        try:
            SALVAGE_ROOT.mkdir(parents=True, exist_ok=True)
            temp.mkdir(exist_ok=True)
            (temp / "files").mkdir(exist_ok=True)
            if not (temp / "file_states.json").is_file():
                (temp / "file_states.json").write_text("[]\n", encoding="utf-8")
            if snapshot is not None and snapshot.is_dir():
                (temp / "snapshot_pointer.txt").write_text(
                    str(snapshot) + "\n", encoding="utf-8")
            if retained is not None and retained.is_dir():
                (temp / "raw_sandbox_pointer.txt").write_text(
                    str(retained) + "\n", encoding="utf-8")
            if not (temp / "wip.patch").is_file():
                (temp / "wip.patch").write_bytes(
                    patch if len(patch) <= 4 * 1024 * 1024 else b"")
            manifest.update({
                "stopped": True,
                "snapshot_included": False,
                "snapshot_deferred": bool(snapshot is not None),
                "raw_sandbox_included": False,
                "raw_sandbox_deferred": bool(retained is not None),
                "patch_sha256": "",
            })
            (temp / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            _replace_with_retry(temp, final)
            sandbox.salvage_saved = str(final)
            log(f"[llm] 停止期间已快速发布失败现场指针包：{final}")
            _record_review_rejection(final, manifest, log=log)
            return final
        except Exception as exc:
            log(f"[llm] 停止期间发布失败现场指针包异常；原始现场继续保留：{exc}")
            if sandbox.snapshot_dir:
                log(f"[llm] 原始全量快照仍保留在：{sandbox.snapshot_dir}")
            if sandbox.retained_sandbox_dir:
                log(f"[llm] 原始隔离仓仍保留在：{sandbox.retained_sandbox_dir}")
            return None
    except Exception as exc:
        log(f"[llm] 保存失败复盘补合包异常；不影响队列重试：{exc}")
        try:
            if temp.is_dir() and temp.parent == SALVAGE_ROOT:
                shutil.rmtree(temp)
        except OSError:
            pass
        if sandbox.snapshot_dir:
            log(f"[llm] 原始全量快照仍保留在：{sandbox.snapshot_dir}")
        if sandbox.retained_sandbox_dir:
            log(f"[llm] 原始隔离仓仍保留在：{sandbox.retained_sandbox_dir}")
        return None


def _run_review_sandbox(
    cmd: list[str], prompt: str, pre_head: str, timeout_seconds: int,
    translator, *, runner: str = "opencode", stall_warn_seconds: float = 0,
    stall_timeout_seconds: float = 0, pre_work_timeout_seconds: float = 0,
    replay_packages=(), replay_attempts=(),
    attempt_receipt: dict | None = None,
    log=print,
) -> SandboxReviewResult:
    """在无 remote、无共享 Git 元数据的临时 clone 中运行模型并导出精确 patch。"""
    sandbox_root = _new_review_temp("sts2-review-sandbox-")
    sandbox_repo = sandbox_root / "repo"
    result = SandboxReviewResult(error="隔离复盘未完成")
    paths: list[str] = []
    validation_git_root: Path | None = None
    validation_prefix = "sts2-review-validation-index-"
    replay_requested = _normalize_salvage_package_names(replay_packages)
    replay_attempt_names = [
        name for name in _normalize_salvage_package_names(replay_attempts)
        if name not in replay_requested]
    replay_mount: dict = {}
    replay_evidence_complete = not bool(replay_requested)
    replay_evidence_error = ""
    replay_model_started = False
    stream_metrics: dict = {}
    transcript_rel = ".git/sts2-review-provider-events.jsonl"
    receipt_bytes = b""
    published_receipt: dict = {}
    try:
        clone = _run_captured_stop_aware([
            "git", "clone", "--quiet", "--no-hardlinks", "--no-checkout",
            str(REPO_DIR), str(sandbox_repo),
        ], timeout=180)
        if clone.returncode != 0:
            result = SandboxReviewResult(error="创建隔离 clone 失败：" + clone.stderr.strip()[:400])
            return result
        checkout = _sandbox_git(sandbox_repo, ["checkout", "--quiet", "--detach", pre_head])
        if checkout.returncode != 0:
            result = SandboxReviewResult(error="隔离 clone checkout 失败：" + checkout.stderr.strip()[:400])
            return result
        _sandbox_git(sandbox_repo, ["remote", "remove", "origin"])

        prompt_path = sandbox_repo / PROMPT_FILE.relative_to(REPO_DIR)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        if replay_requested:
            try:
                replay_mount = _mount_failed_review_evidence(
                    sandbox_repo, replay_requested, replay_attempt_names, log=log)
                replay_evidence_complete = True
            except (_ReviewStopped, KeyboardInterrupt):
                raise
            except Exception as exc:
                replay_evidence_error = str(exc)[:1200]
                result = SandboxReviewResult(
                    error=("失败包完整证据不可用；保留 target 并重新排队："
                           + replay_evidence_error))
                return result
        try:
            sandbox_cmd = bind_review_workdir(cmd, runner, sandbox_repo)
        except ValueError as exc:
            result = SandboxReviewResult(error=f"复盘命令缺少工作目录安全边界：{exc}")
            return result

        receipt_payload = dict(attempt_receipt or {})
        receipt_payload.setdefault("pre_head", pre_head)
        receipt_payload.setdefault("runner", runner)
        receipt_payload.setdefault("batch_runs", [])
        receipt_payload.setdefault("queue_items", [])
        receipt_payload.setdefault("replay_queue_ids", [])
        published_receipt, receipt_bytes = _publish_review_attempt_receipt(
            sandbox_root, receipt_payload)
        replay_model_started = True
        rc, out, timed_out, stopped, stalled = _stream_run(
            sandbox_cmd, timeout_seconds, translate=translator.feed,
            stall_warn_sec=stall_warn_seconds,
            stall_timeout_sec=stall_timeout_seconds,
            pre_work_timeout_sec=pre_work_timeout_seconds,
            raw_transcript=sandbox_repo / transcript_rel,
            metrics_sink=stream_metrics)
        if stopped:
            # Stop keeps the exact clone as an O(1) deferred forensic source; do
            # not spend the shutdown budget hashing or deleting a large mount.
            replay_evidence_complete = False if replay_requested else True
            if replay_requested:
                replay_evidence_error = "整套停止前未完成完整证据退出后校验"
        elif replay_mount:
            try:
                _verify_failed_review_evidence(sandbox_repo, replay_mount)
            except Exception as exc:
                replay_evidence_complete = False
                replay_evidence_error = str(exc)[:1200]
            if not _remove_failed_review_evidence(sandbox_repo, log=log):
                replay_evidence_complete = False
                replay_evidence_error = (
                    replay_evidence_error or "完整证据目录未能在 patch 验收前移除")
            if not replay_evidence_complete:
                result = SandboxReviewResult(
                    rc=rc, out=out, timed_out=timed_out, stopped=stopped,
                    stalled=stalled,
                    error=("失败包完整证据退出校验失败；保留 target 并重新排队："
                           + replay_evidence_error),
                )
                return result
        if stopped or timed_out or stalled or rc != 0:
            result = SandboxReviewResult(
                rc=rc, out=out, timed_out=timed_out, stopped=stopped,
                stalled=stalled,
                error=("统一停机中断并全量保全" if stopped
                       else "复盘 CLI/工具调用无进展挂起" if stalled
                       else "复盘进程未成功完成"),
            )
            return result

        # 不信任模型留下的 HEAD/index/assume-unchanged 标记；在以
        # pre_head 为基线的 private index/object store 里 force-stage 整个工作树。
        # raw HEAD/index/objects 属于失败现场，验收过程绝不改写它们。
        validation_git_root, validation_env = _new_private_sandbox_git(
            sandbox_repo, validation_prefix)
        read_inventory_base = _sandbox_git(
            sandbox_repo, ["read-tree", pre_head], env=validation_env)
        if read_inventory_base.returncode != 0:
            result = SandboxReviewResult(rc=rc, out=out, error="隔离仓库基线恢复失败")
            return result
        stage_inventory = _sandbox_git(
            sandbox_repo, ["add", "--all", "--force", "--", "."],
            env=validation_env)
        inventory = _sandbox_git(
            sandbox_repo, ["diff", "--cached", "--name-only", "-z", pre_head, "--"],
            env=validation_env)
        if stage_inventory.returncode != 0 or inventory.returncode != 0:
            result = SandboxReviewResult(rc=rc, out=out, error="无法枚举隔离复盘变更")
            return result
        paths = list(dict.fromkeys(
            item.replace("\\", "/") for item in inventory.stdout.split("\0") if item))
        own_prompt = PROMPT_FILE.relative_to(REPO_DIR).as_posix()
        paths = [path for path in paths if path != own_prompt]
        accepted, transient, online, rejected = _partition_review_changes(paths)
        if online or rejected:
            denied = [*(f"{path} (online-runtime)" for path in online),
                      *(f"{path} (Git/outside/unsafe)" for path in rejected)]
            result = SandboxReviewResult(
                rc=rc, out=out, paths=tuple(accepted),
                allowed_paths=tuple(accepted), artifact_paths=tuple(transient),
                online_paths=tuple(online), unexpected_paths=tuple(rejected),
                error="复盘 patch 触碰 deny-only 路径边界：" + ", ".join(denied[:12]),
            )
            return result
        if not accepted:
            result = SandboxReviewResult(
                rc=rc, out=out, artifact_paths=tuple(transient))
            return result

        # 自检也在隔离 clone 内执行；失败代码从未进入真实工作树。
        if not _run_selfcheck(log, sandbox_repo / "sts2-ascend"):
            result = SandboxReviewResult(
                rc=rc, out=out, paths=tuple(accepted),
                allowed_paths=tuple(accepted), artifact_paths=tuple(transient),
                error="复盘自检失败", selfcheck_ok=False)
            return result

        # 自检可能生成新产物；再次把 private index 退回基线，仅导出
        # 验证过的 accepted 精确路径。
        read_patch_base = _sandbox_git(
            sandbox_repo, ["read-tree", pre_head], env=validation_env)
        stage = _sandbox_git(
            sandbox_repo, ["add", "--all", "--force", "--", *accepted],
            env=validation_env)
        patch = _sandbox_git(
            sandbox_repo,
            ["diff", "--cached", "--binary", "--unified=0", pre_head, "--", *accepted],
            binary=True, env=validation_env)
        if (read_patch_base.returncode != 0 or stage.returncode != 0
                or patch.returncode != 0 or not patch.stdout):
            result = SandboxReviewResult(
                rc=rc, out=out, paths=tuple(accepted),
                allowed_paths=tuple(accepted), artifact_paths=tuple(transient),
                error="隔离复盘 patch 导出失败")
            return result
        conclusion = ""
        conclusion_rel = "sts2-ascend/knowledge/review_conclusion.txt"
        if conclusion_rel in accepted:
            try:
                conclusion_path = sandbox_repo / conclusion_rel
                resolved_conclusion = conclusion_path.resolve()
                if (conclusion_path.is_symlink()
                        or not resolved_conclusion.is_relative_to(sandbox_repo.resolve())):
                    raise OSError("结论路径逃逸隔离 clone")
                raw_conclusion = resolved_conclusion.read_text(encoding="utf-8")
                conclusion = " ".join(raw_conclusion.split())[:200]
            except OSError as exc:
                log(f"[llm] 无法读取隔离复盘结论，语音结论将跳过：{exc}")
        result = SandboxReviewResult(
            rc=rc,
            out=out,
            paths=tuple(accepted),
            patch=patch.stdout,
            conclusion=conclusion,
            selfcheck_ok=True,
            allowed_paths=tuple(accepted),
            artifact_paths=tuple(transient),
        )
        return result
    except _ReviewStopped:
        result.stopped = True
        result.error = "整套停止；隔离复盘原始现场已快速保留"
        return result
    except Exception as exc:
        result = SandboxReviewResult(error=f"隔离复盘异常：{exc}")
        return result
    finally:
        try:
            provider_metrics = translator.metrics()
        except (AttributeError, TypeError, ValueError):
            provider_metrics = {}
        provider_metrics.update(stream_metrics)
        result.provider_metrics = provider_metrics
        result.provider_work_started = bool(
            getattr(translator, "model_work_started", False))
        result.review_attempt_id = str(published_receipt.get("attempt_id") or "")
        result.review_sandbox_name = str(
            published_receipt.get("sandbox_name") or sandbox_root.name)
        result.review_attempt_receipt_schema = int(
            published_receipt.get("schema") or 0)
        # Final failure-package location is chosen after we know whether the
        # disposable clone itself must be retained or only its host-side snapshot.
        result.provider_transcript_rel = ""
        result.replay_evidence_requested = bool(replay_requested)
        result.replay_evidence_complete = replay_evidence_complete
        result.replay_evidence_error = replay_evidence_error
        result.replay_evidence_index = (
            _RETRY_SANDBOX_EVIDENCE_INDEX.as_posix()
            if replay_requested else "")
        result.replay_evidence_model_started = replay_model_started
        # stop 可能落在 clone、checkout、自检、patch 导出或 capture 任一步；
        # 每次离开 try 都重新取样，不能只依赖 _stream_run 的瞬时返回值。
        result.stopped = result.stopped or _review_stop_requested()
        if result.stopped and sandbox_root.is_dir():
            # 直播热停走 O(1) 快速保留：不在 Stop 临界区 reset/add/hash/copy。
            # 项目内先发布指针包，新 Brain 的 worker 再异步搬运完整 clone。
            result.retained_sandbox_dir = str(sandbox_root)
        else:
            evidence_preflight_failed = bool(
                replay_requested and replay_evidence_error
                and not replay_model_started)
            if evidence_preflight_failed:
                # No model process existed, so there is no model WIP to preserve.
                # A partial mount belongs only to this disposable clone; remove it
                # and mark capture complete so no orphan snapshot is published.
                _remove_failed_review_evidence(sandbox_repo, log=log)
                result.snapshot_complete = True
            else:
                try:
                    _capture_sandbox_wip(
                        sandbox_repo, pre_head, result, log=log, prompt_text=prompt)
                except _ReviewStopped:
                    result.stopped = True
                    result.retained_sandbox_dir = str(sandbox_root)
            if receipt_bytes:
                receipt_path = sandbox_root / _REVIEW_ATTEMPT_RECEIPT_NAME
                try:
                    receipt_changed = bool(
                        receipt_path.is_symlink()
                        or not receipt_path.is_file()
                        or receipt_path.read_bytes() != receipt_bytes)
                except OSError:
                    receipt_changed = True
                if receipt_changed:
                    result.retained_sandbox_dir = str(sandbox_root)
                    result.unexpected_paths = tuple(dict.fromkeys((
                        *result.unexpected_paths,
                        f"../{_REVIEW_ATTEMPT_RECEIPT_NAME} [host-receipt-changed]",
                    )))
                    if not result.error:
                        result.error = "provider changed the durable host attempt receipt"
            siblings = _bounded_sandbox_sibling_paths(sandbox_root, sandbox_repo)
            if siblings:
                escaped = tuple(f"../{path}" for path in siblings)
                result.sibling_paths = siblings
                result.wip_paths = tuple(dict.fromkeys(
                    (*result.wip_paths, *escaped)))
                result.unexpected_paths = tuple(dict.fromkeys(
                    (*result.unexpected_paths, *escaped)))
                if not result.error:
                    result.error = (
                        "隔离复盘写出 sandbox repo 边界："
                        + ", ".join(escaped[:12]))
            if (result.online_paths or result.unexpected_paths) and not result.error:
                denied = [
                    *(f"{path} (online-runtime)" for path in result.online_paths),
                    *(f"{path} (Git/outside/unsafe)"
                      for path in result.unexpected_paths),
                ]
                result.error = (
                    "复盘 patch 触碰 deny-only 路径边界："
                    + ", ".join(denied[:12]))
            if (result.patch and set(result.allowed_paths) != set(result.paths)
                    and not result.error):
                result.error = "复盘自检后出现未进入已验证 patch 的 accepted 文件"
        if _review_stop_requested() and sandbox_root.is_dir():
            result.stopped = True
            result.retained_sandbox_dir = str(sandbox_root)
        _preserve_provider_transcript(
            sandbox_repo, result, transcript_rel, log=log)
        if (sandbox_repo.is_dir() and not result.snapshot_complete
                and not result.retained_sandbox_dir):
            # 全量捕获链自身出错时，绝不删除唯一现场。外层补合发布会把整个
            # clone（含 .git/ignored/越界内容）复制到项目内 raw_sandbox/。
            result.error = result.error or "隔离复盘全量现场捕获不完整"
            result.retained_sandbox_dir = str(sandbox_root)
        if (result.error and sandbox_root.is_dir() and not result.retained_sandbox_dir
                and not (replay_requested and replay_evidence_error
                         and not replay_model_started)):
            # 失败/拒绝时连 sandbox_root/repo 同级的越界文件也必须保留；仅靠
            # repo 内 Git 枚举无法覆盖模型违反 --dir 写出的 ../ 文件。
            result.retained_sandbox_dir = str(sandbox_root)
        _discard_private_sandbox_git(
            validation_git_root, validation_prefix, log=log)
        # 只删除本函数刚创建、且仍位于项目受管/兼容旧版临时区的精确目录。
        try:
            resolved = sandbox_root.resolve()
            if result.retained_sandbox_dir:
                pass
            elif _is_owned_review_temp(resolved, "sts2-review-sandbox-"):
                def remove_readonly(function, path, _exc_info) -> None:
                    os.chmod(path, stat.S_IWRITE)
                    function(path)

                cleanup_error: OSError | None = None
                for attempt in range(5):
                    try:
                        shutil.rmtree(resolved, onerror=remove_readonly)
                        cleanup_error = None
                        break
                    except OSError as exc:
                        cleanup_error = exc
                        if attempt < 4:
                            time.sleep(0.05 * (attempt + 1))
                if cleanup_error is not None:
                    raise cleanup_error
            else:
                log(f"[llm] 隔离目录校验失败，保留供人工清理：{resolved}")
        except OSError as exc:
            log(f"[llm] 隔离目录清理失败，已保留：{sandbox_root}（{exc}）")


def _partition_review_changes(
    paths: list[str] | tuple[str, ...],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Partition the inventory as allowed, cache, online and rejected paths."""
    import autogit

    allowed: list[str] = []
    transient: list[str] = []
    online: list[str] = []
    rejected: list[str] = []
    for raw in dict.fromkeys(_normalized_review_path(item) for item in paths):
        category = autogit.classify_review_path(raw)
        if category == autogit.REVIEW_PATH_ACCEPTED:
            allowed.append(autogit.normalize_paths([raw])[0])
        elif category == autogit.REVIEW_PATH_CACHE:
            transient.append(raw)
        elif category == autogit.REVIEW_PATH_ONLINE_RUNTIME:
            online.append(raw)
        else:
            rejected.append(raw)
    return allowed, transient, online, rejected


def _bounded_marker_snapshot(marker: dict, depth: int = 0) -> dict:
    """Copy a rollback chain while bounding stale-marker growth."""
    copied = dict(marker)
    previous = copied.get(_SUPERSEDED_MARKER_KEY)
    if not isinstance(previous, dict):
        return copied
    if depth + 1 >= _MARKER_HISTORY_MAX_DEPTH:
        copied.pop(_SUPERSEDED_MARKER_KEY, None)
        copied.pop(_SUPERSEDED_MARKER_RAW_KEY, None)
        copied["_superseded_history_truncated"] = True
        return copied
    copied[_SUPERSEDED_MARKER_KEY] = _bounded_marker_snapshot(previous, depth + 1)
    return copied


def _publish_restart_marker_text(contents: str) -> None:
    """Atomically replace the marker in its own directory, including on Windows."""
    MARKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = MARKER_FILE.with_name(
        f".{MARKER_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp, MARKER_FILE)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _write_restart_marker(payload: dict, log=print) -> bool:
    """Atomically hand rollback ownership from an older review to this review.

    The old exclusive-hardlink implementation turned a delayed health observation
    into a global code-review lock.  Preserve the previous marker inside the new
    marker so CAS abort can restore it, while a successfully committed newer review
    becomes the active rollback candidate.
    """
    try:
        next_marker = dict(payload)
        next_marker.setdefault("state", "prepared")
        previous_text = ""
        try:
            previous_text = MARKER_FILE.read_text(encoding="utf-8")
        except FileNotFoundError:
            pass
        if previous_text:
            try:
                previous = json.loads(previous_text)
            except json.JSONDecodeError:
                next_marker[_SUPERSEDED_MARKER_RAW_KEY] = previous_text
                previous_commit = "invalid-json"
            else:
                previous_commit = str(previous.get("review_commit") or "unknown")
                if previous_commit == str(next_marker.get("review_commit") or ""):
                    return True
                next_marker[_SUPERSEDED_MARKER_KEY] = _bounded_marker_snapshot(previous)
            next_marker["_superseded_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            log(f"[llm] 新复盘接管旧重启 marker {previous_commit[:8]}；"
                "旧 marker 已内嵌保留，提交失败会自动恢复")
        _publish_restart_marker_text(
            json.dumps(next_marker, ensure_ascii=False, indent=2) + "\n")
        return True
    except OSError as exc:
        log(f"[llm] 写重启 marker 失败；原 marker 保持不变：{exc}")
        return False


def _commit_restart_marker(expected_commit: str, log=print) -> bool:
    """Phase two: mark a provisional marker loadable only after ref+worktree agree."""
    try:
        current = json.loads(MARKER_FILE.read_text(encoding="utf-8"))
        if current.get("review_commit") != expected_commit:
            log("[llm] marker 最终确认时所有权已变化；保留后来 marker")
            return False
        if current.get("state") == "committed":
            return True
        current["state"] = "committed"
        current["committed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _publish_restart_marker_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n")
        return True
    except (OSError, json.JSONDecodeError) as exc:
        log(f"[llm] 重启 marker 最终确认失败；保持 prepared，绝不计为健康：{exc}")
        return False


def _remove_restart_marker(expected_commit: str, log=print) -> None:
    """Abort one prepare; restore its exact predecessor instead of losing safety."""
    try:
        current = json.loads(MARKER_FILE.read_text(encoding="utf-8"))
        if current.get("review_commit") == expected_commit:
            previous = current.get(_SUPERSEDED_MARKER_KEY)
            previous_raw = current.get(_SUPERSEDED_MARKER_RAW_KEY)
            if isinstance(previous, dict):
                _publish_restart_marker_text(
                    json.dumps(previous, ensure_ascii=False, indent=2) + "\n")
                log(f"[llm] patch 提交中止，已恢复旧重启 marker "
                    f"{str(previous.get('review_commit') or 'unknown')[:8]}")
            elif isinstance(previous_raw, str):
                _publish_restart_marker_text(previous_raw)
                log("[llm] patch 提交中止，已原样恢复旧格式重启 marker")
            else:
                MARKER_FILE.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        log(f"[llm] prepare marker 清理失败，保留诊断：{exc}")


def _kill_orphan_review_processes(log) -> None:
    """清理上一个大脑进程死亡后遗留的孤儿复盘 provider。

    大脑被杀/崩溃时，正在执行的复盘子进程会被系统收养继续跑——它改的文件
    没人收集、reviewing 标记没人清。worker 启动时（自身尚无在跑复盘，安全）
    OpenCode 以 title/--auto/project 路径识别；Codex 只认项目受管 review_work
    clone + exec/json/ephemeral 的生产调用形状。模型、审批模式以后可调，维护 AI
    与评测 canary 不在 review_work 下，不会被命中。
    """
    try:
        _run_captured_stop_aware(
            ["powershell", "-NoProfile", "-Command",
             "& { param($repo,$reviewRoot) Get-CimInstance Win32_Process | Where-Object { "
             "$cmd=[string]$_.CommandLine; "
             "$reviewRepoPattern='(?i)(?:^|\\s)(?:-C|--cd)\\s+\"?'+[regex]::Escape($reviewRoot)+'[\\\\/]+sts2-review-sandbox-[^\\\\/\"\\s]+[\\\\/]+repo\"?(?=$|\\s)'; "
             "$openReviewRepoPattern='(?i)(?:^|\\s)--dir\\s+\"?'+[regex]::Escape($reviewRoot)+'[\\\\/]+sts2-review-sandbox-[^\\\\/\"\\s]+[\\\\/]+repo\"?(?=$|\\s)'; "
             "$open=$_.Name -match '^opencode(\\.exe)?$' -and $cmd -match 'sts2-ascend' "
             "-and $cmd -match '--auto' -and $cmd.IndexOf($repo, "
             "[StringComparison]::OrdinalIgnoreCase) -ge 0; "
             "$open=$_.Name -match '^opencode(\\.exe)?$' -and $cmd -match $openReviewRepoPattern "
             "-and $cmd -match '(?i)(^|\\s)run(?=\\s)' -and $cmd -match '(?i)--format\\s+json(?=$|\\s)' "
             "-and $cmd -match '(?i)--auto(?=$|\\s)'; "
             "$codex=$_.Name -match '^(codex|node|cmd)\\.exe$' "
             "-and $cmd -match $reviewRepoPattern "
             "-and $cmd -match '(?i)(^|\\s)exec(?=\\s)' -and $cmd -match '--json' "
             "-and $cmd -match '--ephemeral'; $open -or $codex } | ForEach-Object { "
             "& taskkill.exe /PID ([string]$_.ProcessId) /T /F 2>$null | Out-Null } }",
             str(REPO_DIR), str(_review_work_root())], timeout=30)
        log("[llm] 已清理遗留的孤儿复盘进程（如有）")
    except _ReviewStopped:
        return
    except Exception as exc:
        log(f"[llm] 孤儿复盘进程清理失败（不影响运行）：{exc}")


def _recover_deferred_salvages(log=print) -> None:
    """新 worker 异步补齐 Stop 临界区保留的 raw clone 或完整快照。"""
    if not SALVAGE_ROOT.is_dir():
        return
    for package in sorted(SALVAGE_ROOT.iterdir(), key=lambda path: path.name):
        raw_pointer = package / "raw_sandbox_pointer.txt"
        snapshot_pointer = package / "snapshot_pointer.txt"
        if (not package.is_dir()
                or not (raw_pointer.is_file() or snapshot_pointer.is_file())):
            continue
        try:
            manifest_path = package / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            completed: list[tuple[Path, SandboxReviewResult | None]] = []

            if raw_pointer.is_file():
                raw = Path(raw_pointer.read_text(encoding="utf-8")[:4096].strip()).resolve()
                if not _is_owned_review_temp(raw, "sts2-review-sandbox-"):
                    raise OSError(f"不安全的 raw sandbox 指针：{raw}")
                target = package / "raw_sandbox"
                if not raw.is_dir() and not target.exists():
                    raise OSError(f"raw sandbox 已不存在：{raw}")
                if raw.is_dir():
                    # manifest/pointer remains deferred until copytree returns;
                    # a partial target is safely completed on the next retry.
                    shutil.copytree(
                        raw, target, dirs_exist_ok=True, symlinks=True,
                        ignore_dangling_symlinks=True,
                        copy_function=_copy_snapshot_file)
                manifest.update({
                    "raw_sandbox_included": True,
                    "raw_sandbox_deferred": False,
                    "raw_sandbox_recovered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                cleanup = (SandboxReviewResult(retained_sandbox_dir=str(raw))
                           if raw.is_dir() else None)
                completed.append((raw_pointer, cleanup))

            if snapshot_pointer.is_file():
                snapshot = Path(
                    snapshot_pointer.read_text(encoding="utf-8")[:4096].strip()).resolve()
                if not _is_owned_review_temp(snapshot, "sts2-review-snapshot-"):
                    raise OSError(f"不安全的 snapshot 指针：{snapshot}")
                target = package / "captured_snapshot"
                if not snapshot.is_dir() and not target.exists():
                    raise OSError(f"snapshot 已不存在：{snapshot}")
                if snapshot.is_dir():
                    shutil.copytree(
                        snapshot, target, dirs_exist_ok=True, symlinks=True,
                        ignore_dangling_symlinks=True,
                        copy_function=_copy_snapshot_file)
                manifest.update({
                    "snapshot_included": True,
                    "snapshot_deferred": False,
                    "snapshot_recovered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                cleanup = (SandboxReviewResult(snapshot_dir=str(snapshot))
                           if snapshot.is_dir() else None)
                completed.append((snapshot_pointer, cleanup))

            manifest_temp = package / (
                f".manifest.json.tmp-{os.getpid()}-{threading.get_ident()}")
            manifest_temp.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            _replace_with_retry(manifest_temp, manifest_path)
            # Once the raw clone is safely inside the ignored failure package,
            # derive a private-index candidate for the next GLM audit.  This is
            # outside the Stop critical path and never applies the candidate.
            try:
                manifest = _materialize_retry_evidence(package, log=log)
            except _ReviewStopped:
                raise
            except Exception as exc:
                log(f"[llm] 延迟现场已补全，{_review_backend_label(manifest)} "
                    f"重审候选证据稍后懒物化：{exc}")
            # 先让项目内完整副本与 manifest 落稳，再清系统临时现场；只有清理
            # 成功才撤指针。若此处崩溃/权限失败，下次启动仍能精确重试而不泄漏。
            for pointer, item in completed:
                cleaned = True
                if item is not None and item.snapshot_dir:
                    cleaned = _discard_sandbox_snapshot(item, log=log)
                if item is not None and item.retained_sandbox_dir:
                    cleaned = _discard_retained_sandbox(item, log=log) and cleaned
                if cleaned:
                    pointer.unlink()
            # Stop may publish the forensic pointer package milliseconds before the
            # daemon exits, leaving no time for the independent ledger commit. The
            # new worker already revisits every deferred package here, so backfill
            # the idempotent tracked index after the full manifest is durable.
            _record_review_rejection(package, manifest, log=log)
            log(f"[llm] 已异步补全停止复盘的完整失败现场：{package}")
        except Exception as exc:
            log(f"[llm] 延迟补全失败复盘现场异常；保留指针供下次重试：{exc}")


def _review_path_is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def _owned_review_sandbox_repo(root: Path) -> Path | None:
    """Accept only a direct, real managed review clone under review_work."""
    try:
        managed = _review_work_root().resolve()
        if (_review_path_is_link_like(root)
                or root.parent.resolve() != managed
                or not root.name.startswith("sts2-review-sandbox-")
                or not _is_owned_review_temp(root, "sts2-review-sandbox-")):
            return None
        repo = root / "repo"
        git_dir = repo / ".git"
        if (_review_path_is_link_like(repo) or _review_path_is_link_like(git_dir)
                or not repo.is_dir() or not git_dir.is_dir()
                or repo.resolve().parent != root.resolve()):
            return None
        return repo
    except OSError:
        return None


def _read_review_attempt_receipt(root: Path) -> tuple[dict | None, bytes]:
    path = root / _REVIEW_ATTEMPT_RECEIPT_NAME
    if path.is_symlink():
        raise ValueError("attempt receipt is a symbolic link")
    if not path.exists():
        return None, b""
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("attempt receipt is not a bounded regular file")
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("attempt receipt is not an object")
    return payload, raw


def _sandbox_created_epoch(root: Path) -> float:
    return float(root.stat().st_ctime)


def _queue_items_by_id(q: dict) -> dict[str, list[dict]]:
    indexed: dict[str, list[dict]] = {}
    collections = [q.get("pending", []), _reviewing_items(q.get("reviewing"))]
    for collection in collections:
        for item in collection:
            queue_id = str(item.get("queue_id") or "")
            if queue_id:
                indexed.setdefault(queue_id, []).append(dict(item))
    return indexed


def _replay_binding_from_items(items: list[dict]) -> tuple[str, list[str], list[str]]:
    targets = {
        str(item.get("replay_target") or item.get("retry_group") or "")
        for item in items
        if item.get("replay_target") or item.get("retry_group")
    }
    if len(targets) > 1:
        raise ReviewQueueError("attempt items contain conflicting replay targets")
    target = next(iter(targets), "")
    packages = _normalize_salvage_package_names(
        value for item in items for value in (item.get("salvage_packages") or []))
    attempts = _normalize_salvage_package_names(
        value for item in items for value in (item.get("salvage_attempts") or []))
    if target:
        packages = [target]
    return target, packages, [value for value in attempts if value != target]


def _receipt_orphan_binding(
    root: Path, repo: Path, receipt: dict, q: dict,
) -> dict:
    if receipt.get("schema") != _REVIEW_ATTEMPT_RECEIPT_SCHEMA:
        raise ReviewQueueError("unsupported attempt receipt schema")
    if receipt.get("sandbox_name") != root.name:
        raise ReviewQueueError("attempt receipt sandbox name mismatch")
    attempt_id = str(receipt.get("attempt_id") or "")
    if not attempt_id or len(attempt_id) > 240 or "\x00" in attempt_id:
        raise ReviewQueueError("attempt receipt id is invalid")
    if receipt.get("provider_launch_affinity_committed") is not True:
        raise ReviewQueueError("attempt receipt predates a durable provider binding")

    raw_items = receipt.get("queue_items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ReviewQueueError("attempt receipt has no full queue items")
    items = [dict(item) for item in raw_items if isinstance(item, dict)]
    if len(items) != len(raw_items):
        raise ReviewQueueError("attempt receipt contains a non-object queue item")
    for index, item in enumerate(items):
        _validate_queue_item(item, f"attempt.queue_items[{index}]")
    queue_ids = [str(item.get("queue_id") or "") for item in items]
    if not all(queue_ids) or len(set(queue_ids)) != len(queue_ids):
        raise ReviewQueueError("attempt receipt queue ids are missing or duplicated")
    if receipt.get("replay_queue_ids") != queue_ids:
        raise ReviewQueueError("attempt receipt queue id summary mismatch")
    runs = [int(item["run"]) for item in items]
    if receipt.get("batch_runs") != runs:
        raise ReviewQueueError("attempt receipt run summary mismatch")

    plan = receipt.get("plan")
    required_plan_fields = {
        "backend_key", "priority", "runner", "model", "variant",
        "reasoning_effort", "approve_for_me", "sandbox", "every", "source",
    }
    if not isinstance(plan, dict) or not required_plan_fields.issubset(plan):
        raise ReviewQueueError("attempt receipt is missing complete plan affinity")
    plan_item = {"run": 1, **plan, "retry_same_model": True}
    _validate_queue_item(plan_item, "attempt.plan")
    plan_affinity = _retry_affinity(plan_item)
    affinity = _batch_retry_affinity(items)
    if affinity is None or affinity != plan_affinity:
        raise ReviewQueueError("attempt receipt plan and queue affinity differ")

    current = _queue_items_by_id(q)
    for item, queue_id in zip(items, queue_ids):
        matches = current.get(queue_id, [])
        if len(matches) != 1:
            raise ReviewQueueError(
                f"attempt queue id is absent or ambiguous: {queue_id}")
        live = matches[0]
        if live.get("run") != item.get("run") or _retry_affinity(live) != affinity:
            raise ReviewQueueError(
                f"attempt queue identity/affinity changed: {queue_id}")
        for key in ("retry_group", "replay_target"):
            if str(live.get(key) or "") != str(item.get(key) or ""):
                raise ReviewQueueError(
                    f"attempt queue lineage changed: {queue_id}.{key}")
        if bool(live.get("evidence_only")) != bool(item.get("evidence_only")):
            raise ReviewQueueError(
                f"attempt queue evidence role changed: {queue_id}")
        for key in ("salvage_packages", "salvage_attempts"):
            if _normalize_salvage_package_names(live.get(key) or []) != (
                    _normalize_salvage_package_names(item.get(key) or [])):
                raise ReviewQueueError(
                    f"attempt queue evidence lineage changed: {queue_id}.{key}")

    head = _sandbox_git(repo, ["rev-parse", "--verify", "HEAD"], timeout=30)
    pre_head = str(receipt.get("pre_head") or "")
    if head.returncode != 0 or not pre_head or head.stdout.strip() != pre_head:
        raise ReviewQueueError("attempt receipt baseline does not match clone HEAD")
    target, packages, attempts = _replay_binding_from_items(items)
    if str(receipt.get("replay_target") or "") != target:
        raise ReviewQueueError("attempt receipt replay target summary mismatch")
    if _normalize_salvage_package_names(receipt.get("replay_packages") or []) != packages:
        raise ReviewQueueError("attempt receipt replay package summary mismatch")
    if _normalize_salvage_package_names(receipt.get("replay_attempts") or []) != attempts:
        raise ReviewQueueError("attempt receipt replay attempt summary mismatch")
    return {
        "attempt_id": attempt_id,
        "receipt_schema": _REVIEW_ATTEMPT_RECEIPT_SCHEMA,
        "pre_head": pre_head,
        "items": items,
        "plan": dict(plan),
        "replay_target": target,
        "replay_packages": packages,
        "replay_attempts": attempts,
    }


def _legacy_orphan_binding(
    candidates: list[tuple[Path, Path]], q: dict, log=print,
) -> list[tuple[Path, Path, dict]]:
    """Bind one pre-receipt clone only when current reviewing proves uniqueness."""
    reviewing = q.get("reviewing")
    if not isinstance(reviewing, dict) or not isinstance(reviewing.get("items"), list):
        return []
    items = _reviewing_items(reviewing)
    if not items or any(not item.get("queue_id") for item in items):
        return []
    try:
        affinity = _batch_retry_affinity(items)
        started = time.mktime(time.strptime(
            str(reviewing.get("started") or ""), "%Y-%m-%d %H:%M:%S"))
    except (ReviewQueueError, OverflowError, TypeError, ValueError):
        return []
    if affinity is None:
        return []
    now = time.time()
    eligible: list[tuple[Path, Path]] = []
    for root, repo in candidates:
        # Pre-receipt compatibility is only for attempts which crossed the old
        # provider boundary.  A clean clone left before spawn has no transcript.
        if not (repo / ".git" / "sts2-review-provider-events.jsonl").is_file():
            continue
        try:
            created = _sandbox_created_epoch(root)
        except OSError:
            continue
        if (created >= started - _LEGACY_REVIEW_SANDBOX_CLOCK_SKEW_SEC
                and created <= started + _LEGACY_REVIEW_SANDBOX_CLOCK_SKEW_SEC
                and created <= now + _LEGACY_REVIEW_SANDBOX_CLOCK_SKEW_SEC):
            eligible.append((root, repo))
    if len(eligible) != 1:
        if eligible:
            log("[llm] legacy review sandboxes are ambiguous; retaining all: "
                + ", ".join(root.name for root, _repo in eligible))
        return []
    root, repo = eligible[0]
    head = _sandbox_git(repo, ["rev-parse", "--verify", "HEAD"], timeout=30)
    if head.returncode != 0 or not head.stdout.strip():
        return []
    (runner, model, source, backend_key, variant, reasoning_effort,
     approve_for_me, sandbox_mode, priority) = affinity
    plan = {
        "backend_key": backend_key,
        "priority": priority,
        "runner": runner,
        "model": model,
        "variant": variant,
        "reasoning_effort": reasoning_effort,
        "approve_for_me": approve_for_me,
        "sandbox": sandbox_mode,
        "every": max(1, int(items[0].get("every") or 1)),
        "source": source,
    }
    target, packages, attempts = _replay_binding_from_items(items)
    binding = {
        "attempt_id": f"legacy:{root.name}:{head.stdout.strip()[:16]}",
        "receipt_schema": 0,
        "pre_head": head.stdout.strip(),
        "items": items,
        "plan": plan,
        "replay_target": target,
        "replay_packages": packages,
        "replay_attempts": attempts,
    }
    return [(root, repo, binding)]


def _pointed_review_sandbox_roots() -> set[Path]:
    pointed: set[Path] = set()
    if not SALVAGE_ROOT.is_dir():
        return pointed
    for package in SALVAGE_ROOT.iterdir():
        pointer = package / "raw_sandbox_pointer.txt"
        if not package.is_dir() or not pointer.is_file():
            continue
        try:
            raw = Path(pointer.read_text(encoding="utf-8")[:4096].strip()).resolve()
            if _is_owned_review_temp(raw, "sts2-review-sandbox-"):
                pointed.add(raw)
        except OSError:
            continue
    return pointed


def _orphan_salvage_records(attempt_id: str) -> list[tuple[Path, dict]]:
    records: list[tuple[Path, dict]] = []
    if not SALVAGE_ROOT.is_dir():
        return records
    for package in SALVAGE_ROOT.iterdir():
        manifest_path = package / "manifest.json"
        if not package.is_dir() or not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if manifest.get("review_attempt_id") == attempt_id:
            records.append((package, manifest))
    return records


def _orphan_salvage_is_complete(
    package: Path, manifest: dict, root: Path,
) -> bool:
    raw = package / "raw_sandbox"
    if (manifest.get("raw_sandbox_included") is not True
            or manifest.get("raw_sandbox_deferred") is True
            or manifest.get("review_sandbox_name") != root.name
            or not (raw / "repo" / ".git").is_dir()):
        return False
    source_receipt = root / _REVIEW_ATTEMPT_RECEIPT_NAME
    copied_receipt = raw / _REVIEW_ATTEMPT_RECEIPT_NAME
    try:
        if source_receipt.exists():
            return (not source_receipt.is_symlink()
                    and not copied_receipt.is_symlink()
                    and source_receipt.read_bytes() == copied_receipt.read_bytes())
    except OSError:
        return False
    return True


def _recover_bound_review_sandbox(
    root: Path, repo: Path, binding: dict, log=print,
) -> Path | None:
    existing = _orphan_salvage_records(binding["attempt_id"])
    if existing:
        if (len(existing) == 1
                and _orphan_salvage_is_complete(existing[0][0], existing[0][1], root)):
            cleanup = SandboxReviewResult(retained_sandbox_dir=str(root))
            if _discard_retained_sandbox(cleanup, log=log):
                log(f"[llm] orphan review sandbox already fully preserved: {root.name}")
                return existing[0][0]
        log(f"[llm] orphan review salvage state is incomplete/ambiguous; retaining clone: {root}")
        return None
    if _review_stop_requested():
        return None

    result = SandboxReviewResult(
        rc=-1,
        error="previous review host exited before publishing its sandbox",
        retained_sandbox_dir=str(root),
        provider_work_started=True,
        provider_metrics={"startup_orphan_recovery": True},
    )
    try:
        _capture_sandbox_wip(repo, binding["pre_head"], result, log=log)
    except _ReviewStopped:
        result.stopped = True
        result.retained_sandbox_dir = str(root)
    siblings = _bounded_sandbox_sibling_paths(root, repo)
    if siblings:
        escaped = tuple(f"../{path}" for path in siblings)
        result.sibling_paths = siblings
        result.wip_paths = tuple(dict.fromkeys((*result.wip_paths, *escaped)))
        result.unexpected_paths = tuple(dict.fromkeys(
            (*result.unexpected_paths, *escaped)))
    _preserve_provider_transcript(
        repo, result, ".git/sts2-review-provider-events.jsonl", log=log)
    plan = binding["plan"]
    items = binding["items"]
    saved = _save_review_salvage(
        binding["pre_head"], result.error, result,
        batch_runs=[int(item["run"]) for item in items],
        runner=str(plan["runner"]), model=str(plan["model"]),
        source=str(plan["source"]), backend_key=str(plan["backend_key"]),
        variant=str(plan["variant"]),
        reasoning_effort=str(plan["reasoning_effort"]),
        priority=max(1, int(plan["priority"])),
        approve_for_me=bool(plan["approve_for_me"]),
        sandbox_mode=str(plan["sandbox"]), every=max(1, int(plan["every"])),
        replay_target=str(binding["replay_target"]),
        replay_attempts=list(binding["replay_attempts"]),
        replay_queue_ids=[str(item["queue_id"]) for item in items],
        review_attempt_id=str(binding["attempt_id"]),
        review_sandbox_name=root.name,
        review_attempt_receipt_schema=int(binding["receipt_schema"]),
        startup_orphan_recovery=True,
        log=log,
    )
    if saved is None:
        log(f"[llm] orphan review sandbox preservation failed; clone retained: {root}")
    return saved


def _recover_unpointed_review_sandboxes(log=print) -> list[str]:
    """Turn exactly bound, unpointed managed clones into durable failure packages."""
    work_root = _review_work_root()
    if not work_root.is_dir() or _review_stop_requested():
        return []
    pointed = _pointed_review_sandbox_roots()
    candidates: list[tuple[Path, Path]] = []
    try:
        children = list(work_root.iterdir())
    except OSError as exc:
        log(f"[llm] cannot enumerate managed review_work; retaining it unchanged: {exc}")
        return []
    for root in children:
        repo = _owned_review_sandbox_repo(root)
        if repo is None:
            continue
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in pointed:
            continue
        candidates.append((root, repo))
    if not candidates:
        return []

    try:
        with _queue_lock:
            q = _load_queue_unlocked()
    except (ReviewQueueError, OSError) as exc:
        log(f"[llm] review queue cannot bind orphan sandboxes; retaining all: {exc}")
        return []

    bound: list[tuple[Path, Path, dict]] = []
    legacy: list[tuple[Path, Path]] = []
    for root, repo in candidates:
        try:
            receipt, _raw = _read_review_attempt_receipt(root)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            log(f"[llm] invalid orphan attempt receipt; retaining clone {root.name}: {exc}")
            continue
        if receipt is None:
            legacy.append((root, repo))
            continue
        try:
            binding = _receipt_orphan_binding(root, repo, receipt, q)
        except (OSError, ReviewQueueError, ValueError, TypeError) as exc:
            log(f"[llm] orphan attempt binding is not exact; retaining clone {root.name}: {exc}")
            continue
        bound.append((root, repo, binding))

    claims: dict[str, list[tuple[Path, Path, dict]]] = {}
    for record in bound:
        for item in record[2]["items"]:
            claims.setdefault(str(item["queue_id"]), []).append(record)
    conflicting_roots = {
        root.resolve()
        for records in claims.values() if len(records) > 1
        for root, _repo, _binding in records
    }
    exact: list[tuple[Path, Path, dict]] = []
    for record in bound:
        if record[0].resolve() not in conflicting_roots:
            exact.append(record)
    if conflicting_roots:
        log("[llm] receipt sandboxes have overlapping queue ids; retaining all conflicts: "
            + ", ".join(sorted(path.name for path in conflicting_roots)))
    exact.extend(_legacy_orphan_binding(legacy, q, log=log))

    recovered: list[str] = []
    for root, repo, binding in exact:
        if _review_stop_requested():
            break
        saved = _recover_bound_review_sandbox(root, repo, binding, log=log)
        if saved is not None:
            recovered.append(saved.name)
            log(f"[llm] recovered unpointed review sandbox into full salvage: {saved}")
    return recovered


def _resume_host_salvage_closures(log=print) -> None:
    """Resume receipt push/ledger/quarantine work without another GLM call."""
    if not SALVAGE_ROOT.is_dir() or _review_stop_requested():
        return
    packages = sorted(SALVAGE_ROOT.iterdir(), key=lambda path: path.name)
    # Finish already quarantined packages first; their code receipt and delete
    # authorization are independent from the model queue.
    for package in packages:
        if _review_stop_requested():
            return
        if not package.is_dir() or not package.name.startswith(_CLOSED_SALVAGE_PREFIX):
            continue
        try:
            manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
            original = package.name[len(_CLOSED_SALVAGE_PREFIX):]
            _finish_quarantined_salvage(package, original, manifest, log=log)
        except FileNotFoundError:
            # Only the crash window between the final manifest unlink and rmdir
            # produces an empty quarantine.  Recheck the exact package's final
            # upstream ledger row before removing that exact empty directory.
            original = package.name[len(_CLOSED_SALVAGE_PREFIX):]
            try:
                empty = not any(package.iterdir())
            except OSError:
                empty = False
            if (empty and (
                    _review_hold_lineage_closure_is_confirmed(original)
                    or _upstream_ledger_has_terminal_closure(original))):
                try:
                    package.rmdir()
                except OSError as exc:
                    log(f"[llm] 空隔离目录闭环恢复暂缓：{package.name}（{exc}）")
            else:
                log(f"[llm] 隔离失败包缺少 manifest，未获精确删除授权：{package.name}")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            log(f"[llm] 隔离失败包闭环恢复暂缓：{package.name}（{exc}）")

    resolved_states = {
        "claimed_pending_code_push", "code_upstream_confirmed",
        "quarantined_pending_ledger", "ledger_final_upstream",
    }
    target_names: set[str] = set()
    orphan_attempts: list[tuple[Path, dict]] = []
    for package in packages:
        if (_review_stop_requested() or not package.is_dir()
                or package.name.startswith(_CLOSED_SALVAGE_PREFIX)):
            if _review_stop_requested():
                return
            continue
        try:
            manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError, FileNotFoundError):
            continue
        if manifest.get("retry_resolution_state") not in resolved_states:
            continue
        target = str(manifest.get("retry_resolution_target")
                     or manifest.get("replay_target") or package.name)
        if manifest.get("replay_role") == "target" or package.name == target:
            target_names.add(target)
            _resume_replay_lineage_resolution(package, manifest, log=log)
        else:
            orphan_attempts.append((package, manifest))
    for package, manifest in orphan_attempts:
        if _review_stop_requested():
            return
        target = str(manifest.get("retry_resolution_target")
                     or manifest.get("replay_target") or "")
        if target not in target_names and _salvage_package_path(target) is None:
            _finalize_salvage_resolution(package, manifest, log=log)


def _backfill_rejection_ledger(log=print) -> None:
    """Idempotently index every surviving package, including Stop-edge packages."""
    _migrate_rejection_ledger_labels(log=log)
    if not SALVAGE_ROOT.is_dir():
        return
    for package in sorted(SALVAGE_ROOT.iterdir(), key=lambda path: path.name):
        manifest_path = package / "manifest.json"
        if not package.is_dir() or not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if package.name.startswith(_CLOSED_SALVAGE_PREFIX):
                original_name = package.name[len(_CLOSED_SALVAGE_PREFIX):]
                _finish_quarantined_salvage(
                    package, original_name, manifest, log=log)
                continue
            # Do not rescan every historical raw clone on each Brain boot.  The
            # explicit replay entry point materializes the named package before
            # queuing it; deferred Stop recovery does so once after its copy lands.
            _record_review_rejection(package, manifest, log=log)
            if manifest.get("retry_resolution_state") in {
                    "claimed_pending_code_push", "code_upstream_confirmed",
                    "quarantined_pending_ledger",
                    "ledger_final_upstream"}:
                if (manifest.get("replay_role") == "target"
                        or package.name == manifest.get("retry_resolution_target")):
                    _resume_replay_lineage_resolution(package, manifest, log=log)
                else:
                    _finalize_salvage_resolution(package, manifest, log=log)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            log(f"[llm] 拒合清单启动补录跳过损坏失败包 {package.name}：{exc}")


def _finalize_review_batch(batch: list[dict], outcome: str, log=print) -> float:
    """原子消费成功批次或把失败批次放回队尾；返回失败退避秒数。"""
    with _queue_lock:
        q = _load_queue_unlocked()
        if not _reviewing_matches_batch(q.get("reviewing"), batch):
            raise ReviewQueueError("复盘队列批次身份已变化，拒绝把收尾误报为成功")
        if outcome in {"completed", "documented", "changed"}:
            q["reviewing"] = None
            _save_queue_unlocked(q)
            return 0.0
        if outcome == "deferred":
            pending = list(q.get("pending", []))
            seen = {_queue_item_identity(item) for item in pending}
            ready_at = time.time() + 60.0
            for item in batch:
                identity = _queue_item_identity(item)
                if identity in seen:
                    continue
                deferred = dict(item)
                deferred["retry_after"] = max(
                    float(deferred.get("retry_after", 0) or 0), ready_at)
                pending.append(deferred)
                seen.add(identity)
            q["pending"] = pending
            q["reviewing"] = None
            _save_queue_unlocked(q)
            return 60.0
        if outcome not in {"failed", "replay_pending"}:
            return 0.0

        # 新入队的局先处理，失败批次退到队尾。完整保留本次实际模型计划、
        # retry_group 与失败包证据，使下一轮仍由同一个 GLM 对照当前 HEAD 重审。
        pending = list(q.get("pending", []))
        seen = {_queue_item_identity(item) for item in pending}
        delays: list[float] = []
        for item in batch:
            identity = _queue_item_identity(item)
            if identity not in seen:
                retry_count = int(item.get("retry_count", 0)) + 1
                delay = min(_REVIEW_RETRY_MAX_SECONDS,
                            _REVIEW_RETRY_BASE_SECONDS
                            * (2 ** min(retry_count - 1, 20)))
                retry_item = dict(item)
                retry_item.update({
                    "retry_count": retry_count,
                    "retry_after": time.time() + delay,
                    # A model field is only a preference hint on fresh queued work.
                    # Sticky affinity must be explicitly published before launch
                    # or recovered from a provider-started failure manifest.
                    "retry_same_model": bool(item.get("retry_same_model", False)),
                    "salvage_packages": _normalize_salvage_package_names(
                        item.get("salvage_packages") or []),
                })
                pending.append(retry_item)
                seen.add(identity)
                delays.append(float(delay))
        q["pending"] = pending
        q["reviewing"] = None
        _save_queue_unlocked(q)
    return min(delays, default=0.0)


def _persist_reviewing_batch_metadata(batch: list[dict], log=print) -> bool:
    """Durably enrich an active transaction with its resolved plan/evidence."""
    try:
        with _queue_lock:
            q = _load_queue_unlocked()
            reviewing = q.get("reviewing") or {}
            if not _reviewing_matches_batch(reviewing, batch):
                return False
            reviewing = dict(reviewing)
            reviewing["items"] = [dict(item) for item in batch]
            reviewing["runs"] = [item["run"] for item in batch]
            q["reviewing"] = reviewing
            _save_queue_unlocked(q)
        return True
    except (ReviewQueueError, OSError) as exc:
        log(f"[llm] 复盘批次元数据暂未落盘，将由收尾事务重试：{exc}")
        return False


def _worker_loop(agent, log) -> None:
    """Supervise the durable review daemon, including startup recovery.

    Startup maintenance touches several independently durable stores.  A locked
    or temporarily invalid queue must not kill the only daemon while leaving the
    `_worker_started` latch set forever.  Retry the whole idempotent startup/body
    transaction, and always release the latch if the thread really exits.
    """
    global _worker_started, _worker_thread
    try:
        while not _review_stop_requested():
            try:
                _worker_loop_body(agent, log)
                return
            except Exception as exc:
                log(f"[llm] 复盘守护线程启动/运行异常，持久状态保持不变，30s 后自愈重试：{exc}")
                if _wait_review_stop(30):
                    return
    finally:
        with _worker_lock:
            if (_worker_thread is None
                    or _worker_thread is threading.current_thread()):
                _worker_started = False
                _worker_thread = None


def _worker_loop_body(agent, log) -> None:
    # 进程重启后：先清孤儿（避免与重跑的复盘双写），再把 reviewing 的对局
    # 重新入队——此前直接丢弃标记，被中断复盘覆盖的对局永远丢失复盘。
    if _review_stop_requested():
        return
    _kill_orphan_review_processes(log)
    if _review_stop_requested():
        return
    _cleanup_stale_private_git_temps(log=log)
    if _review_stop_requested():
        return
    _recover_deferred_salvages(log=log)
    if _review_stop_requested():
        return
    # A pre-receipt host can die after the provider edited its managed clone but
    # before `_save_review_salvage` published a pointer/package.  Preserve only
    # clones with an exact durable queue binding; ambiguous legacy roots remain.
    _recover_unpointed_review_sandboxes(log=log)
    if _review_stop_requested():
        return
    # Operator-preserved packages may be the only surviving copy after an older
    # host accepted a prompt-truncated conclusion.  Restore that full lineage
    # before parsing historical receipts, so an old no_valid_change cannot close
    # it again without the mounted-evidence schema proof.
    _recover_review_holds(log=log)
    if _review_stop_requested():
        return
    # A previous GLM run may have pushed a valid receipt that an older parser
    # failed to recognize.  Recover that durable upstream fact before rebuilding
    # the replay queue, otherwise the already-closed target would be paid for and
    # executed again.
    _recover_committed_retry_resolutions(log=log)
    if _review_stop_requested():
        return
    _recover_salvage_replay_queue(log=log)
    if _review_stop_requested():
        return
    _backfill_rejection_ledger(log=log)
    if _review_stop_requested():
        return
    # Startup recovery is itself a durable queue transaction.  If the file is
    # temporarily locked/unreadable, retry in place rather than letting the daemon
    # thread die (or treating the interrupted batch as empty).
    while not _review_stop_requested():
        try:
            with _queue_lock:
                q = _load_queue_unlocked()
                if q.get("reviewing"):
                    requeued = _restore_interrupted_reviewing(q)
                    recovered_runs = [item.get("run") for item in requeued]
                    if recovered_runs:
                        log(f"[llm] 上场复盘随进程中断，优先恢复追及：第 {recovered_runs} 局")
                    _save_queue_unlocked(q)
            break
        except (ReviewQueueError, OSError) as exc:
            log(f"[llm] 复盘队列恢复失败，原文件保持不变，30s 后重试：{exc}")
            if _wait_review_stop(30):
                return

    next_salvage_maintenance = time.monotonic() + 60.0
    while not _review_stop_requested():
        try:
            # request_restart 已置位 = 本进程已判定待重启（局间 sys.exit(42)）。
            # 此时严禁再开新复盘：开跑即随进程死亡被孤儿化，覆盖的对局丢失
            # （复盘 C 局中完成置位 → worker 又开跑 A → 局末退场掐断 A，实证路径）。
            if getattr(agent, "request_restart", False):
                return
            if time.monotonic() >= next_salvage_maintenance:
                # Keep the three host transactions in this order even when the
                # first call finds nothing new.  A crash may have persisted the
                # receipt state but not yet acknowledged its queue items.
                _recover_review_holds(log=log)
                if _review_stop_requested():
                    return
                _recover_committed_retry_resolutions(log=log)
                if _review_stop_requested():
                    return
                _recover_salvage_replay_queue(log=log)
                if _review_stop_requested():
                    return
                _resume_host_salvage_closures(log=log)
                next_salvage_maintenance = time.monotonic() + 60.0
                if _review_stop_requested():
                    return
            # Host-only receipt/push/ledger/quarantine recovery is independent
            # from paid model execution.  When LLM review is disabled, keep the
            # durable review queue untouched and run only maintenance.
            worker_cfg = load_llm_config()
            if not worker_cfg.get("enabled", True):
                if _wait_review_stop(30):
                    return
                continue
            retry_wait = 0.0
            with _queue_lock:
                q = _load_queue_unlocked()
                pending = q.get("pending", [])
                if pending and not q.get("reviewing"):
                    approval_refreshed = _refresh_sticky_approval(
                        pending, worker_cfg)
                    if approval_refreshed:
                        # Selection itself compares the complete sticky tuple, so
                        # normalize and durably publish old approval snapshots
                        # before the scheduler can inspect a mixed replay group.
                        _save_queue_unlocked(q)
                        log("[llm] pending sticky review execution approval "
                            "refreshed from exact current backend config")
                    cap = max(1, min(
                        int(worker_cfg.get("review_queue_max", 100)),
                        int(worker_cfg.get("max_runs_in_packet", 100))))
                    now = time.time()
                    eligible_indexes, retry_wait = _select_review_batch(
                        pending, cap, now)
                    if eligible_indexes:
                        first = pending[eligible_indexes[0]]
                        retry_group = str(first.get("retry_group") or "")
                        picked = set(eligible_indexes)
                        transaction = f"{os.getpid()}-{time.time_ns()}"
                        batch = []
                        for offset, index in enumerate(eligible_indexes):
                            item = dict(pending[index])
                            item.setdefault("queue_id", f"{transaction}-{offset}")
                            batch.append(item)
                        q["pending"] = [item for index, item in enumerate(pending)
                                        if index not in picked]
                        q["reviewing"] = {
                            "runs": [p["run"] for p in batch],
                            "items": [dict(p) for p in batch],
                            "retry_group": retry_group,
                            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        _save_queue_unlocked(q)
                    else:
                        batch = []
                else:
                    batch = []
            if batch:
                outcome = "failed"
                try:
                    outcome = _run_batch_review(agent, batch, log)
                except Exception as exc:
                    log(f"[llm] 批次复盘异常，将保留并退避重试：{exc}")
                    outcome = "failed"
                if outcome == "canceled" or _review_stop_requested():
                    return
                # reviewing 是持久事务标记。若最终落盘暂时失败，不能返回外层
                # 进入“reviewing 非空、永不再取批”的空转态；原地重试直到成功或停止。
                while not _review_stop_requested():
                    try:
                        delay = _finalize_review_batch(batch, outcome, log=log)
                        break
                    except (ReviewQueueError, OSError) as exc:
                        log(f"[llm] 复盘批次收尾落盘失败，保留 reviewing，5s 后重试：{exc}")
                        if _wait_review_stop(5):
                            return
                else:
                    return
                if (outcome in {"completed", "documented", "changed"}
                        and not _review_stop_requested()):
                    _resume_host_salvage_closures(log=log)
                if outcome in {"failed", "replay_pending", "deferred"}:
                    if outcome == "deferred":
                        log(f"[llm] 当前绑定后端暂不可启动，批次原样保留，{delay:.0f}s 后重试")
                        retry_wait = min(30.0, max(1.0, delay))
                        continue
                    label = (f"失败包尚未完成 {_review_backend_label(batch[0])} 闭环"
                             if outcome == "replay_pending" else "复盘失败")
                    log(f"[llm] {label}，批次已放回队尾，{delay:.0f}s 后继续追及")
                    retry_wait = min(30.0, max(1.0, delay))
            if _wait_review_stop(retry_wait or 5):
                return
        except Exception as exc:
            log(f"[llm] 复盘工作线程异常（已忽略，30s 后继续）：{exc}")
            if _wait_review_stop(30):
                return


def _coerce_review_plan(value, cfg: dict) -> ReviewPlan:
    """Accept new ReviewPlan values and tuple-returning test/legacy resolvers."""
    if isinstance(value, ReviewPlan):
        return value
    model_entry, every, source = value
    runner = str(cfg.get("runner") or "opencode")
    model = str(model_entry)
    variant = None
    if runner == "opencode":
        model, variant = _parse_entry(model)
    return ReviewPlan(
        key=str(model_entry), priority=1, runner=runner, model=model,
        variant=variant, every_runs=max(1, int(every)), source=str(source))


def _run_batch_review(agent, batch: list[dict], log) -> str:
    if _review_stop_requested():
        return "canceled"
    cfg = load_llm_config()
    approval_refreshed = _refresh_sticky_approval(batch, cfg)
    if approval_refreshed:
        log("[llm] sticky review execution approval refreshed from exact current "
            "backend config")
    affinity = _batch_retry_affinity(batch)
    if affinity is not None:
        # A process that already produced a failure package/partial output owns
        # its retry lineage.  Never silently hand that evidence to another model.
        (runner, model, source, backend_key, variant, reasoning_effort,
         approve_for_me, sandbox_mode, priority) = affinity
        planned = [item for item in batch if item.get("model") == model]
        every = int((planned[-1] if planned else batch[-1]).get("every", 5))
        plan = ReviewPlan(
            key=backend_key, priority=priority, runner=runner, model=model,
            variant=variant or None, reasoning_effort=reasoning_effort or None,
            approve_for_me=approve_for_me, sandbox=sandbox_mode,
            every_runs=max(1, every), source=source)
        if source == "preferred" and _preferred_cooldown_remaining(plan.state_key) > 0:
            return "deferred"
        if not runner_binary(cfg, runner):
            log(f"[llm] sticky 后端 {plan.key} 的 {runner} 暂不可执行；保留原事务等待")
            return "deferred"
    else:
        # Fresh, not-yet-attempted work may use the existing availability/fallback
        # resolver immediately before launch.  This is the only cross-model handoff.
        plan = _coerce_review_plan(resolve_review_plan(cfg, log=log), cfg)
        if not plan.available:
            return "deferred"
    runner, model, source, every = (
        plan.runner, plan.model, plan.source, plan.every_runs)
    if runner not in {"opencode", "codex"}:
        log(f"[llm] 复盘批次绑定不支持的 runner={runner}；保留原事务等待")
        return "deferred"
    replay_batch = any(
        item.get("replay_target") or item.get("salvage_packages")
        for item in batch)
    if affinity is None and plan.every_runs > 1 and not replay_batch:
        distinct_runs = len({int(item["run"]) for item in batch})
        if distinct_runs < plan.every_runs:
            log(
                f"[llm] {plan.display_model} 需要至少 {plan.every_runs} 局合批；"
                f"当前只有 {distinct_runs} 局，保留队列等待积累")
            return "deferred"
    replay_target = next((str(item.get("replay_target") or "") for item in batch
                          if item.get("replay_target")), "")
    legacy_packages = _normalize_salvage_package_names(
        package for item in batch
        for package in (item.get("salvage_packages") or []))
    if not replay_target and legacy_packages:
        replay_target = legacy_packages[0]
    inherited_packages = [replay_target] if replay_target else []
    inherited_attempts = _normalize_salvage_package_names(
        package for item in batch
        for package in (item.get("salvage_attempts") or []))
    # Migrate an early draft queue which accumulated every package in one list:
    # the first package remains the target; later packages become attempt evidence.
    inherited_attempts = _normalize_salvage_package_names([
        *inherited_attempts, *legacy_packages[1:]])
    for item in batch:
        item.update({
            **plan.as_queue_fields(),
            "retry_same_model": True,
            "salvage_packages": list(inherited_packages),
            "salvage_attempts": list(inherited_attempts),
        })
        if replay_target:
            item["replay_target"] = replay_target
    binding_persisted = _persist_reviewing_batch_metadata(batch, log=log)
    if not binding_persisted and (affinity is None or approval_refreshed):
        # Provider launch is the point where model affinity becomes billable and
        # semantically binding.  A repaired execution contract must likewise be
        # durable before launch, or a Brain crash can restore the denied mode.
        if affinity is None:
            for item in batch:
                item["retry_same_model"] = False
        log("[llm] resolved runner 绑定尚未耐久落盘；本次不启动 provider，稍后重试")
        return "deferred"
    if not binding_persisted:
        log("[llm] sticky runner 绑定已来自耐久队列；本轮元数据刷新失败但不改变既有亲和性")
    runs_list = [p["run"] for p in batch]
    evidence_only = bool(batch) and all(bool(item.get("evidence_only"))
                                        for item in batch)
    replay_note = f"，重审失败包 {inherited_packages}" if inherited_packages else ""
    log(f"[llm] 异步复盘启动：覆盖第 {runs_list} 局"
        f"（{runner}/{plan.display_model}{replay_note}）")
    status: dict = {}
    executed = run_review(
                          agent.know, log=log, model=model, every=every, source=source,
                          runner=runner, backend_key=plan.key, priority=plan.priority,
                          variant=plan.variant, reasoning_effort=plan.reasoning_effort,
                          approve_for_me=plan.approve_for_me,
                          sandbox_mode=plan.sandbox,
                          batch_runs=runs_list, async_mode=True, _status=status,
                          salvage_packages=inherited_packages,
                          salvage_attempts=inherited_attempts,
                          replay_queue_ids=[str(item.get("queue_id") or "")
                                            for item in batch],
                          evidence_only=evidence_only,
                          review_queue_items=batch)
    new_package = str(status.get("new_salvage_package") or "")
    if not new_package:
        legacy_new = _normalize_salvage_package_names(
            status.get("salvage_packages") or [])
        new_package = next((name for name in reversed(legacy_new)
                            if name != replay_target), "")
    if not replay_target and new_package:
        replay_target = new_package
        inherited_packages = [replay_target]
    elif replay_target and new_package and new_package != replay_target:
        inherited_attempts = _link_replay_attempt(
            replay_target, new_package, inherited_attempts, log=log)
    retry_group = replay_target
    keep_sticky = not bool(status.get("startup_unavailable"))
    for item in batch:
        item.update({
            **plan.as_queue_fields(),
            "retry_same_model": keep_sticky,
            "salvage_packages": list(inherited_packages),
            "salvage_attempts": list(inherited_attempts),
        })
        if retry_group:
            item["retry_group"] = retry_group
            item["replay_target"] = retry_group
    _persist_reviewing_batch_metadata(batch, log=log)
    if replay_target:
        resolutions = status.get("retry_resolutions") or {}
        unresolved = status.get("unresolved_salvage_packages") or []
        if not status.get("commit"):
            unresolved = [replay_target]
        log(f"[llm] {plan.display_model} 失败包重审回执："
            f"{resolutions or '未写 retry_resolution'}"
            f"；仍 pending={unresolved}")
        if status.get("host_pending_salvage_packages"):
            log("[llm] 复盘模型已完成逐包结论；清单/删除由宿主耐久恢复继续处理："
                f"{status['host_pending_salvage_packages']}")
    if status.get("commit"):
        log(f"[llm] {plan.display_model} 复盘提交回执：commit={status['commit'][:12]} "
            f"pushed={bool(status.get('pushed'))}")
    outcome = status.get("outcome", "changed" if executed else "failed")
    if outcome == "canceled" or status.get("canceled"):
        return "canceled"
    if inherited_packages and outcome in {"changed", "completed", "documented"} and unresolved:
        # The accepted code/report commit remains valid.  Missing/still_pending
        # receipts or an unconfirmed push only keep the forensic package lineage
        # queued for another GLM pass; they never roll back the accepted commit.
        if outcome == "changed" or executed:
            agent.request_restart = True
        log("[llm] 本轮提交已保留，但失败包尚未得到远端确认的逐包结论；"
            "继续交给原复盘模型")
        return "replay_pending"
    if outcome == "changed" or executed:
        log("[llm] 异步复盘产生变更，本局结束后自动重启大脑加载…")
        agent.request_restart = True
        return "changed"
    if outcome == "documented":
        log("[llm] 异步复盘仅提交报告，已计入闭环状态且无需重启大脑")
        return "documented"
    if outcome == "completed":
        return "completed"
    log(f"[llm] 异步复盘未成功，将自动重试：{status.get('reason', '未知原因')}")
    return "failed"


def main() -> None:
    if "--replay-salvage" in sys.argv:
        try:
            raw = sys.argv[sys.argv.index("--replay-salvage") + 1]
            packages = [value.strip() for value in raw.split(",") if value.strip()]
        except IndexError:
            print("用法: py brain/llm_review.py --replay-salvage package-id[,package-id]")
            raise SystemExit(2)
        try:
            queued = requeue_salvage_packages(packages)
        except ReviewQueueError as exc:
            print(exc)
            raise SystemExit(3)
        print(json.dumps(queued, ensure_ascii=False))
        return
    if "--requeue" in sys.argv:
        if _brain_session_is_active():
            print("拒绝在线改写复盘队列：请先用 Stop-Agent.ps1 -KeepGame 停止 brain")
            raise SystemExit(3)
        try:
            raw = sys.argv[sys.argv.index("--requeue") + 1]
            runs = [int(value.strip()) for value in raw.split(",") if value.strip()]
        except (IndexError, ValueError):
            print("用法: py brain/llm_review.py --requeue 562,566,567")
            raise SystemExit(2)
        requeue_review_runs(runs)
        return
    if "--now" not in sys.argv:
        print("用法: py brain/llm_review.py --now | --requeue 562,566,567 | "
              "--replay-salvage package-id[,package-id]")
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from knowledge import Knowledge
    know = Knowledge(KNOWLEDGE_DIR)
    cfg = load_llm_config()
    plan = _coerce_review_plan(resolve_review_plan(cfg), cfg)
    print(f"plan: runner={plan.runner} model={plan.display_model} "
          f"every={plan.every_runs} source={plan.source} available={plan.available}")
    if not plan.available:
        return
    executed = run_review(
        know, model=plan.model, every=plan.every_runs, source=plan.source,
        runner=plan.runner, backend_key=plan.key, priority=plan.priority,
        variant=plan.variant, reasoning_effort=plan.reasoning_effort,
        approve_for_me=plan.approve_for_me, sandbox_mode=plan.sandbox,
        async_mode=True)
    print(f"done, executed={executed}")


if __name__ == "__main__":
    main()
