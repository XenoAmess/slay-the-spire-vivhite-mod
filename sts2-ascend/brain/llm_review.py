"""LLM 元复盘 —— 异步追及队列：游玩不等待，复盘在后台串行消化。

模型策略（见 config.json 的 llm 节）：
  - 优先模型 preferred_model（默认 opencode-go/glm-5.3-flash，即 GLM-5.3-Flash）：
    每局结束后探测 `opencode models`，在清单里且无失败冷却 → 每局复盘一次。
  - 回退模型 model（默认 kimi-for-coding/k3）：优先模型不可用 → 每 review_every_runs 局复盘。
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
  - 不直接调模型裸 API；spawn `opencode run` 无头会话——带完整工具链的智能体，走本机 OpenCode 授权。
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
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from lifecycle import stop_requested

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
        "model": "kimi-for-coding/k3",
        "review_every_runs": 5,
        "timeout_min": 480,
        "max_runs_in_packet": 100,
        # 优先模型链（按优先级；条目形如 provider/model[@variant]）：
        # GLM-5.3-Flash (2x usage) · OpenCode Go · max
        "preferred_models": [
            "opencode-go/glm-5.3-flash@max",
        ],
        "preferred_every_runs": 1,
        # 失败冷却：超时/硬失败统一 5 分钟（短冷却，别让模型长期缺席复盘）
        "preferred_timeout_cooldown_min": 5,
        "preferred_failure_cooldown_min": 5,
        # 异步复盘不阻塞游玩，优先模型的超时可放宽
        "preferred_timeout_min": 480,
        # 总复盘预算仍是 8 小时；这里只识别进程活着但长时间没有任何输出进展
        # 的工具/CLI 挂起。实测正常 GLM 单步最长约 3 分钟，10 分钟才终止。
        "stall_warn_min": 5,
        "stall_timeout_min": 10,
        "models_probe_timeout_sec": 60,
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

    Runtime scripts and non-Brain sources still count as actions, but restarting
    Brain cannot load them. Brain Python modules and its live config do require
    the transactional marker. ``selfcheck.py`` remains proof-only.
    """
    normalized = tuple(dict.fromkeys(
        _normalized_review_path(path) for path in (paths or ())))
    prefix = "sts2-ascend/brain/"
    return tuple(
        path for path in normalized
        if path.startswith(prefix)
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
        # A failed package is evidence for a fresh GLM audit, never an input to
        # host-side patch application.  The bounded excerpts are copied into the
        # prompt because ignored forensic packages are intentionally absent from
        # the isolated review clone.
        "failed_review_replay": _failed_review_replay_context(
            salvage_packages or [], salvage_attempts or [], log=log),
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
    closure_summary_keys = (
        "action_required", "require_action_every_batch",
        "consecutive_report_only", "report_only_limit",
        "evidence_run_threshold", "evidence_batch_threshold", "last_outcome",
    )
    closure_summary = "；".join(
        f"{key}={json.dumps(closure_state.get(key), ensure_ascii=False)}"
        for key in closure_summary_keys if key in closure_state)

    return f"""你是「sts2-ascend」杀戮尖塔2自主学习智能体的总教练。{scope}。
智能体本体：启发式决策引擎（brain/policy.py，参数在 knowledge/policy.json）+ 统计学习（knowledge/stats.json），反复游玩战士 Ironclad。

# 数据载体说明
本提示文件的**第一个 `json` 代码块就是完整 packet**，不存在独立的 packet JSON 文件。
若 Read 工具截断下面的超长单行，不要把截断误判成字段缺失；请在本地读取
`sts2-ascend/knowledge/review_prompt_latest.md`，提取第一个 fenced `json` 代码块后用
`json.loads` 解析。packet 内 `corpus_paths` 已是隔离 sandbox 仓库可读的相对路径。

# review_closure 快速摘要
{closure_summary}

# 数据摘要（紧凑 JSON 已内嵌；原生事实按本批实体检索，完整文件可按路径深读）
```json
{packet_json}
```

最近的 lessons.md 尾部：
```
{lessons_tail}
```

# 证据累计与闭环纪律（宿主会按真实变更路径验收）
- 若 packet 的 `failed_review_replay.packages` 非空，这是此前失败批次的只读取证证据，
  **绝不代表宿主已经或将自动套用其中 patch**。你必须基于当前 HEAD 重新审核：逐项比较候选
  patch/报告与当前源码，只重实现仍有效的部分，自行解决冲突，运行自检后走本批正常提交路径。
  不得把失败 patch 当成已验证成果，也不得只写一份“建议人工补合”的文档。
- `requested_packages` 是本批唯一需要给出结论的 target；`attempt_packages` 只是这个
  target 此前重试失败留下的完整证据，不是新的并行任务。你必须同时审阅 lineage 中列出的
  attempt，但只对 target 写一条最终回执，避免一次失败就把任务无限拆包或越审越大。
- 先读取 packet 的 `review_closure` 与 `recent_review_context`，为反复出现的问题复用稳定的
  `issue_id`，并把本批独立 run 证据与此前批次证据合并判断。
- `historical_zero_code_debt` 是此前被“零代码纪律”拖欠的实现债务。先逐项对账：只有能指出
  **已经存在的生产代码路径和实际生效行为**才可标为 resolved；一次无关代码改动不能把整包债务
  清零。每批优先补做一个最高价值 unresolved 历史问题，除非本批出现更高优先级的致命新缺陷。
- 同一问题在至少 `evidence_run_threshold` 个独立对局出现，或连续
  `evidence_batch_threshold` 个成功复盘批次出现，即达到证据阈值；不得再次只登记“待观察”。
- 当前 `review_closure.require_action_every_batch=true`：**每个成功复盘批次**都必须完成一个
  **有界闭环实验**：修改运行时行为/配置，或者先增加能直接验证该假设的运行时观测代码。
  纯 `meta_review.md`、纯短评、仅改 `selfcheck.py`、只改生产文件注释/空白都不算闭环，
  宿主会拒绝整批并保存现场重试。
- 改动追求的是**相对安全、范围有界、可观测、可记录、可继续调整或撤回**，不是证明绝对安全。
  “还不够安全”“耦合面较宽”“参数已经顶格”“还想再看几局”均不能作为阈值后的延期理由；
  不敢直接改策略时就先加运行时观测，但观测必须落在生产代码中并能在后续 run 留下证据。
- 每批只选一个最高价值主假设。报告必须写清 `issue_id`、证据 run、实际代码动作、未来 3~10 局
  的观测指标、继续调整条件与撤回条件。Git 历史由宿主管理，后续可用反向提交恢复。
- “顶格旋钮不再吸收证据”只禁止把同一数值无限推向边界；正确动作是转交同语义接替旋钮、
  改结构或加观测，绝不等于“零代码纪律”。

# 你的任务（严格按顺序）
1. 归因分析：主要死因趋势、打法缺陷、卡组构建问题、地图路线问题、代码缺陷。
   若 `decision_chain_evidence.full_failure_run` 非 null，必须先逐条阅读其中的
   `decisions`；这是本批最新死亡局未经截断的完整持久决策链。旧日志可能只有
   action/params/reason；新日志的
   关键选择还会带 turn/energy/trace，end_turn 会带 turn_end_state。重点核查有剩余
   能量和可打手牌却结束回合、错误目标、药水时机、路线与休息选择，并引用具体楼层/
   回合/动作作为证据。其余局可按 runs_summary 做趋势分析，不要求逐条展开。
   涉及卡牌/怪物/遗物/药水/事件机制时，必须优先查阅 packet 中的
   `native_game_knowledge`；摘要不够就按 `corpus_paths` 精确检索相应 runtime 与
   mechanics JSONL。不得用记忆中的旧版 STS2/STS1 数值覆盖 manifest 所指版本。
2. 将复盘报告**追加写入** `sts2-ascend/knowledge/meta_review.md`（新建一节，标题含日期时间）：
   归因分析、你做出的每项调整及理由、新沉淀的经验知识（中文）。
   若本批带有失败包，对 `failed_review_replay.requested_packages` 中的每个包另写一行：
   `retry_resolution: <package-id> integrated|no_valid_change|still_pending`。
   `integrated` 表示你已在当前 HEAD 重新实现并验证有效成果，`no_valid_change` 表示复审后确认
   没有仍应合入的改动，`still_pending` 表示本轮尚未解决。该行用于宿主追踪，不替代代码、自检
   或本批复盘说明；遗漏不会让整批代码被拒绝，但失败包会继续保持 pending。
3. 你可以修改或新建 `sts2-ascend/` 下的静态项目文件，包括生产源码、
   **`brain/config.json`** 及其他配置、`scripts/`、`tests/`、`docs/`、静态原生游戏
   knowledge 和复盘报告。宿主使用 deny-only 分类器按最终精确路径验收，不设固定文件名单。
   只有以下边界禁止写入：
   - 在线运行状态：`.runtime/`，`knowledge/runs/`、`archive/`、`code_backups/`，以及
     `stats/progression/policy/lessons/review_queue/preferred_model_state/pending_restart` 等
     在线状态文件、锁/日志/stream/flag、宿主 prompt、截图和拒合清单；这些全部只读
   - Git 元数据（任意 `.git` 路径及 `.gitmodules`）
   - 任一路径段含 `cache`（大小写不敏感）及 `.pyc/.pyo` 字节码；它们是临时产物，
     不进入 patch，但若工具意外生成会被宿主完整留存在取证快照中，不会误杀合规源码
   - `sts2-ascend/` 之外的任何路径、绝对路径或 `..` 逃逸路径
   新经验仍应追加到 `knowledge/meta_review.md`；短评写入
   `knowledge/review_conclusion.txt`。不要用 tests/docs/selfcheck 代替要求的生产闭环。
4. 改完任何 `.py` 后**必须**运行 `py -3 -B sts2-ascend/brain/selfcheck.py` 并确认输出 SELFCHECK OK；
   若不通过，修好再试，实在修不好就把该文件改回原样。
5. 不要提交：git 提交由宿主大脑在复盘前后自动完成（复盘前已备份，复盘后变更会被提交；
   若你的变更导致自检失败，会被整体回滚到备份点）。
6. **额外产出一段点评短评**：把它**写入** `sts2-ascend/knowledge/review_conclusion.txt`
   （纯文本、单行、一两句话点评这几局的表现+一个最关键的改进点，**100 字以内**）。
   这段文字会被克隆音色朗读出来，所以要口语化、适合听；请主动用逗号或句号切成
   **约 10 字一个停顿、任一连续分句不超过 20 字**。运行时还会再次强制细分兜底。

# 禁止事项（最高优先级，覆盖仓库 AGENTS.md 的默认规则）
- 禁止任何 git 操作（add/commit/push/reset 等，宿主大脑统一管理）
- 除上述自检命令外，禁止启动、停止、终止或管理任何进程（游戏和大脑正在运行）
- 禁止删除在线知识、历史对局日志或失败取证包；禁止安装依赖

完成后，用 200 字以内输出本次复盘总结。"""


# ---------------------------------------------------------------------------
# 优先模型可用性探测（每局一次，带失败冷却）
# ---------------------------------------------------------------------------

def _load_preferred_state() -> dict:
    try:
        return json.loads(PREFERRED_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_preferred_state(state: dict) -> None:
    try:
        PREFERRED_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def _preferred_entries(cfg: dict) -> list[str]:
    """优先模型链（按优先级排序）。每项形如 'provider/model' 或 'provider/model@variant'。"""
    entries = cfg.get("preferred_models")
    if isinstance(entries, list) and entries:
        return [str(e) for e in entries if e]
    single = cfg.get("preferred_model")
    return [single] if single else []


def _parse_entry(entry: str) -> tuple[str, str | None]:
    """'opencode-go/glm-5.3-flash@max' → ('opencode-go/glm-5.3-flash', 'max')。"""
    if "@" in entry:
        m, v = entry.rsplit("@", 1)
        return m, (v or None)
    return entry, None


def _entry_state(entry: str) -> dict:
    return _load_preferred_state().get("entries", {}).get(entry, {})


def _write_entry_state(entry: str, data: dict) -> None:
    state = _load_preferred_state()
    state.setdefault("entries", {})[entry] = data
    _save_preferred_state(state)


def _preferred_cooldown_remaining(entry: str) -> float:
    """该优先模型失败冷却剩余秒数（0 表示未在冷却中）。"""
    until = float(_entry_state(entry).get("unavailable_until", 0) or 0)
    return max(0.0, until - time.time())


def _mark_preferred_failure(cfg: dict, log, entry: str, reason: str, kind: str = "failure") -> None:
    """优先模型失败冷却（按条目独立计时）。kind="timeout" 从宽，硬失败从严。"""
    key = "preferred_timeout_cooldown_min" if kind == "timeout" else "preferred_failure_cooldown_min"
    cooldown_min = float(cfg.get(key, 30 if kind == "timeout" else 60))
    _write_entry_state(entry, {
        "unavailable_until": time.time() + cooldown_min * 60,
        "last_failure": reason,
        "last_failure_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    log(f"[llm] 优先模型 {entry} 复盘失败（{reason}），{cooldown_min:.0f} 分钟内跳过该条目")


def _mark_preferred_ok(entry: str) -> None:
    if _entry_state(entry).get("unavailable_until"):
        _write_entry_state(entry, {"unavailable_until": 0})


def _query_available_models(binary: str, cfg: dict, log) -> set[str] | None:
    """运行 `opencode models` 返回可用模型 id 集合；探测失败返回 None。"""
    timeout = int(cfg.get("models_probe_timeout_sec", 60))
    try:
        proc = subprocess.run([binary, "models"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except Exception as exc:
        log(f"[llm] 模型清单探测异常：{exc}")
        return None
    if proc.returncode != 0:
        log(f"[llm] 模型清单探测失败（exit={proc.returncode}）：{(proc.stderr or '')[-200:]}")
        return None
    return {ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()}


def resolve_review_plan(cfg: dict, binary: str | None, log=print) -> tuple[str, int, str]:
    """决定本轮复盘的 (模型条目, 复盘间隔局数, 来源)。

    按优先链逐条检查（在 `opencode models` 清单里且不在失败冷却期），命中即用、每局复盘；
    全部不可用则回退 cfg["model"] 按 review_every_runs 间隔复盘。
    条目形如 'provider/model' 或 'provider/model@variant'。
    """
    fallback = (cfg["model"], max(1, int(cfg.get("review_every_runs", 5))), "fallback")
    entries = _preferred_entries(cfg)
    if not entries or not binary:
        return fallback
    models: set[str] | None = None
    for entry in entries:
        model_id, _variant = _parse_entry(entry)
        cooldown = _preferred_cooldown_remaining(entry)
        if cooldown > 0:
            log(f"[llm] 优先模型 {entry} 冷却中（剩余 {cooldown / 60:.0f} 分钟），看下一优先")
            continue
        if models is None:
            models = _query_available_models(binary, cfg, log) or set()
        if model_id in models:
            return entry, max(1, int(cfg.get("preferred_every_runs", 1))), "preferred"
        log(f"[llm] 优先模型 {model_id} 不在可用清单，看下一优先")
    log(f"[llm] 优先模型全部不可用，回退 {fallback[0]}（每 {fallback[1]} 局）")
    return fallback


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


class OpencodeJsonTranslator:
    """把 opencode `--format json` 的事件流逐行翻译成可读直播文本。

    事件形如 {"type": "text", "part": {"id": ..., "type": "text", "text": ...}}。
    text/reasoning 事件是同一 part 的增量快照（全量重复推送），按 part id 去重只输出增量。
    """

    def __init__(self) -> None:
        self._seen: OrderedDict[str, int] = OrderedDict()
        self._seen_limit = 4096

    def feed(self, raw: str) -> list[str]:
        s = raw.strip()
        if not s:
            return []
        if not s.startswith("{"):
            return [s]
        try:
            evt = json.loads(s)
        except json.JSONDecodeError:
            return [s]
        part = evt.get("part") or {}
        ptype = part.get("type") or evt.get("type") or ""
        # Provider 输入不可信；固定长度 key 防止 4096 个超长 id 绕过 LRU 内存界。
        raw_pid = str(part.get("id") or "")
        pid = hashlib.blake2s(raw_pid.encode("utf-8", errors="replace"),
                              digest_size=16).hexdigest()
        if ptype in ("text", "reasoning"):
            text = part.get("text") or ""
            prev = self._seen.get(pid, 0)
            if len(text) <= prev:
                if pid in self._seen:
                    self._seen.move_to_end(pid)
                return []
            self._seen[pid] = len(text)
            self._seen.move_to_end(pid)
            while len(self._seen) > self._seen_limit:
                self._seen.popitem(last=False)
            prefix = "💭 " if ptype == "reasoning" and prev == 0 else ""
            return [prefix + text[prev:]]
        if ptype in ("tool", "tool-call", "tool_call", "tool-use", "tool-result", "tool_result"):
            name = part.get("tool") or part.get("name") or "tool"
            brief = json.dumps(part.get("input") or part.get("args") or {},
                               ensure_ascii=False)[:160]
            return [f"⚙ {name} {brief}"]
        if ptype == "patch":
            files = part.get("files") or []
            return ["📦 修改 " + ", ".join(str(f).split("/")[-1] for f in files)]
        if ptype == "step-finish":
            tok = (part.get("tokens") or {}).get("total")
            return [f"· tokens {tok} ·"] if tok else []
        return []   # step-start 等噪音不显示


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
    while True:
        if _review_stop_requested():
            _terminate_process_tree(proc)
            try:
                proc.communicate(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            raise _ReviewStopped()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_process_tree(proc)
            try:
                proc.communicate(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            raise subprocess.TimeoutExpired(args, timeout)
        try:
            stdout, stderr = proc.communicate(timeout=min(0.2, remaining))
            return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def _stream_run(cmd: list[str], timeout_sec: int, translate=None, *,
                stall_warn_sec: float = 0,
                stall_timeout_sec: float = 0) -> tuple[int, str, bool, bool, bool]:
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
    proc = subprocess.Popen(
        cmd, cwd=str(REPO_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=8192, env=env,
        **_process_group_kwargs())

    # 128 * 8192 约 1 MiB；即使模型连续八小时输出，reader 也不会无限吃内存。
    q: queue.Queue[str] = queue.Queue(maxsize=128)
    reader_cancel = threading.Event()
    reader_done = threading.Event()
    progress = [time.monotonic(), 0]

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
                progress[0] = time.monotonic()
                progress[1] += 1
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
            if progress[1] != seen_progress:
                seen_progress = progress[1]
                warned = False
            if _review_stop_requested():
                stopped = True
                _terminate_process_tree(proc)
                break
            if time.monotonic() > deadline:
                timed_out = True
                _terminate_process_tree(proc)
                break
            idle = time.monotonic() - progress[0]
            if stall_warn_sec > 0 and idle >= stall_warn_sec and not warned:
                warned = True
                emit_display(
                    f"[llm] 复盘已 {idle / 60:.1f} 分钟无输出进展；"
                    "继续等待，达到无进展上限才会保全现场并重试。")
            if stall_timeout_sec > 0 and idle >= stall_timeout_sec:
                stalled = True
                emit_display(
                    f"[llm] 复盘连续 {idle / 60:.1f} 分钟无输出进展；"
                    "判定 CLI/工具调用挂起，终止本次并保全现场重试。")
                _terminate_process_tree(proc)
                break
            if reader_done.is_set() and q.empty():
                if pending:
                    emit_raw_line(pending)
                    pending = ""
                break

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
    rc = proc.returncode if proc.returncode is not None else -1
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
               source: str = "fallback", batch_runs: list[int] | None = None,
               async_mode: bool = False, _status: dict | None = None,
               salvage_packages: list[str] | None = None,
               salvage_attempts: list[str] | None = None,
               replay_queue_ids: list[str] | None = None,
               evidence_only: bool = False) -> bool:
    """执行一次大模型复盘。返回 True 仅表示 patch 触及 Brain 加载路径、应热重启。

    流程：保存在线进度 → opencode 隔离复盘 → deny-only 路径分类 → 自检 → 精确提交；
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
    binary = shutil.which(cfg.get("opencode_bin", "opencode"))
    if not binary:
        log(f"[llm] 未找到 opencode 可执行文件（{cfg.get('opencode_bin')}），跳过本次复盘")
        return False
    model = model or cfg["model"]
    entry = model                       # 条目原文（含 @variant），用于冷却记账与展示
    model_id, variant = _parse_entry(entry)

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
    log(f"[llm] ===== 启动大模型复盘（{entry} via opencode [{source}]，{batch_txt}，备份点 {pre_head[:8]}）=====")
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
    # 完整提示词落盘为 review_prompt_latest.md，命令行只传一句引导，让复盘 agent 自己读文件。
    rel_prompt = PROMPT_FILE.relative_to(REPO_DIR).as_posix()
    short_prompt = (f"你位于宿主创建的隔离 clone。请完整阅读 {rel_prompt}，只可在当前 "
                    "--dir 根目录内使用相对路径；禁止绝对路径、.. 逃逸或访问其他工作区。"
                    "严格按任务书执行。")

    cmd = [
        binary, "run",
        "--model", model_id,
        "--format", "json",      # JSON 事件流（含 text/reasoning/tool），直播翻译成人话
        "--thinking",            # 显示思维链
    ]
    if variant:
        cmd += ["--variant", variant]
    cmd += [
        "--title", f"sts2-ascend 复盘 {stamp}",
        "--dir", str(REPO_DIR),
        "--auto",
        short_prompt,
    ]

    if _review_stop_requested():
        if _status is not None:
            _status.update({"outcome": "canceled", "reason": "整套停止", "canceled": True})
        log("[llm] 备份完成时收到停止请求，取消本次复盘")
        return False

    # 直播流开启 + 拉起悬浮窗/语音朗读器（哨兵/meta 先行）。review_id 让旧 Edge
    # 进程在连续复盘、同一路径 truncate/regrow 时仍能按场次去重结论。
    review_id = f"{os.getpid()}-{time.time_ns()}"
    _stream_begin({
        "review_id": review_id,
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
    stall_timeout_min = _non_negative_float(cfg.get("stall_timeout_min"), 10.0)
    stall_warn_min = _non_negative_float(cfg.get("stall_warn_min"), 5.0)
    if stall_timeout_min > 0:
        stall_warn_min = min(stall_warn_min, stall_timeout_min)
    else:
        stall_warn_min = 0.0
    translator = OpencodeJsonTranslator()
    sandbox = SandboxReviewResult(error="复盘尚未运行")

    def save_failure(reason: str) -> Path | None:
        package = _save_review_salvage(
            pre_head, reason, sandbox, batch_runs=(batch_runs or [runs]),
            model=entry, source=source, every=every,
            replay_target=replay_target, replay_attempts=replay_attempts,
            replay_queue_ids=replay_queue_ids, log=log)
        if package is not None and _status is not None:
            _status["salvage_package"] = package.name
            _status["new_salvage_package"] = package.name
        return package

    try:
        sandbox = _run_review_sandbox(
            cmd, prompt, pre_head, int(eff_timeout_min * 60), translator,
            stall_warn_seconds=stall_warn_min * 60,
            stall_timeout_seconds=stall_timeout_min * 60, log=log)
        rc, out, timed_out, stopped, stalled = (
            sandbox.rc, sandbox.out, sandbox.timed_out, sandbox.stopped,
            sandbox.stalled)
        # stop 可能恰好落在 opencode 自然退出与宿主验收之间；不能只信任
        # _stream_run 返回瞬间的 stopped 快照。
        stopped = stopped or _review_stop_requested()
        sandbox.stopped = sandbox.stopped or stopped
        resolutions = (_parse_retry_resolutions(
            sandbox.diagnostic_report, replay_packages) if replay_packages else {})
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
            # 这是本地工具链挂起，不是 provider 不可用；不冷却 GLM。队列会
            # 保存同批并在退避后再次调用同一模型，失败包供它复审/解冲突。
            log("[llm] 复盘无进展 watchdog 已终止挂起进程；完整现场已保存，"
                "同批将重新交给 GLM")
            return False
        if timed_out:
            if _status is not None:
                _status["reason"] = "复盘超时"
            log(f"[llm] 复盘超时（{eff_timeout_min:.0f} 分钟），本次作废")
            if source == "preferred":
                _mark_preferred_failure(cfg, log, entry, "timeout", kind="timeout")
            return False
        if rc != 0:
            if _status is not None:
                _status["reason"] = f"复盘进程 exit={rc}"
            if source == "preferred":
                _mark_preferred_failure(cfg, log, entry, f"exit={rc}")
            log(f"[llm] 隔离复盘失败：{sandbox.error or f'exit={rc}'}；真实工作树未改")
            return False
        if sandbox.error:
            if _status is not None:
                _status["reason"] = sandbox.error
            log(f"[llm] 隔离复盘被拒绝：{sandbox.error}；真实工作树未改")
            return False
        if source == "preferred":
            _mark_preferred_ok(entry)
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
                commit=result.commit, pushed=review_pushed, log=log)
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


def maybe_review(agent, log=print) -> None:
    """【已废弃，保留兼容】同步复盘入口。新架构用 enqueue_review（异步不阻塞游玩）。"""
    cfg = load_llm_config()
    if not cfg.get("enabled"):
        return
    binary = shutil.which(cfg.get("opencode_bin", "opencode"))
    model, every, source = resolve_review_plan(cfg, binary, log=log)
    runs = agent.know.stats["global"]["runs"]
    last = agent.know.progression.get("last_llm_review_run", 0)
    if runs - last < every:
        return
    executed = run_review(agent.know, log=log, model=model, every=every, source=source)
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
    for key in ("model", "source", "retry_group", "queue_id", "replay_target"):
        value = item.get(key)
        if value is not None and not isinstance(value, str):
            raise ReviewQueueError(f"{label}.{key} must be a string")
    retry_same_model = item.get("retry_same_model")
    if retry_same_model is not None and not isinstance(retry_same_model, bool):
        raise ReviewQueueError(f"{label}.retry_same_model must be a boolean")
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


def requeue_salvage_packages(package_names, log=print) -> dict[str, list[int]]:
    """Explicitly queue named failure packages for one-by-one GLM re-audit.

    This entry point is deliberately offline-only: callers first stop Brain via
    the unified lifecycle script, then name the packages to replay.  It never
    scans or auto-requeues every surviving package.  Each package receives its
    own stable ``retry_group`` so it cannot be mixed with live runs or another
    failure package in one GLM call.
    """
    if _brain_session_is_active():
        raise ReviewQueueError(
            "拒绝在线改写复盘队列：请先用 Stop-Agent.ps1 -KeepGame 停止 brain")
    requested = _normalize_salvage_package_names(package_names)
    queued: dict[str, list[int]] = {}
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
            log(f"[llm] 失败包已有 GLM 结论，交由宿主闭环恢复而不重复消耗模型：{name}")
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
            model = str(manifest.get("model") or "")
            source = str(manifest.get("source") or "preferred")
            try:
                every = int(manifest.get("every") or (
                    cfg.get("preferred_every_runs", 1) if source == "preferred"
                    else cfg.get("review_every_runs", 5)))
            except (TypeError, ValueError):
                every = 1 if source == "preferred" else 5
            for run in runs:
                item = {
                    "run": run,
                    "time": str(manifest.get("time") or stamp),
                    "retry_group": name,
                    "replay_target": name,
                    "retry_same_model": True,
                    "salvage_packages": [name],
                    "salvage_attempts": _normalize_salvage_package_names(
                        manifest.get("replay_attempt_packages") or []),
                    "evidence_only": evidence_only,
                    "every": max(1, every),
                    "source": source,
                }
                if model:
                    item["model"] = model
                q["pending"].append(item)
            existing_groups.add(name)
            queued[name] = list(runs)
        if queued:
            _save_queue_unlocked(q)
    for name, runs in queued.items():
        log(f"[llm] 已将失败包交回 GLM 重审队尾：{name}（第 {runs} 局，独立批次）")
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


def _recover_salvage_replay_queue(log=print) -> None:
    """Reconcile atomically published packages with the durable target queue.

    Package publication deliberately precedes queue/ledger network work.  The
    manifest therefore carries the target and original queue ids; after any crash
    this scan converts the interrupted transaction (or creates one missing group)
    into exactly one target job and attaches every later failure as evidence.
    """
    if not SALVAGE_ROOT.is_dir():
        return
    targets: dict[str, tuple[Path, dict]] = {}
    attempts: dict[str, list[str]] = {}
    queue_ids: dict[str, set[str]] = {}
    resolved_targets: dict[str, set[str]] = {}
    for package in sorted(SALVAGE_ROOT.iterdir(), key=lambda path: path.name):
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
        if manifest.get("retry_resolution_state") in {
                "claimed_pending_code_push", "code_upstream_confirmed",
                "quarantined_pending_ledger", "ledger_final_upstream", "done"}:
            resolved_targets.setdefault(target, set()).update(manifest_queue_ids)
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
                return any(
                    item_target == target or item_group == target
                    or (item_queue_id in ids if ids else False)
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
                log("[llm] 已按耐久 GLM 回执消费遗留 replay 队列事务："
                    f"{sorted(resolved_targets)}")
        for target, (_package, manifest) in targets.items():
            lineage = _normalize_salvage_package_names([
                *(manifest.get("replay_attempt_packages") or []),
                *attempts.get(target, []),
            ])
            lineage = [name for name in lineage if name != target]
            target_attempts[target] = lineage
            ids = queue_ids.get(target, set())

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
                        "retry_same_model": True,
                        "salvage_packages": [target],
                        "salvage_attempts": list(lineage),
                    }
                    if any(item.get(key) != value for key, value in desired.items()):
                        item.update(desired)
                        changed = True
            if not matched:
                runs, evidence_only = _manifest_replay_runs(manifest)
                source = str(manifest.get("source") or "preferred")
                try:
                    every = int(manifest.get("every") or (
                        cfg.get("preferred_every_runs", 1) if source == "preferred"
                        else cfg.get("review_every_runs", 5)))
                except (TypeError, ValueError):
                    every = 1 if source == "preferred" else 5
                stamp = str(manifest.get("time") or time.strftime("%Y-%m-%d %H:%M"))
                for run in runs:
                    item = {
                        "run": run,
                        "time": stamp,
                        "retry_group": target,
                        "replay_target": target,
                        "retry_same_model": True,
                        "salvage_packages": [target],
                        "salvage_attempts": list(lineage),
                        "evidence_only": evidence_only,
                        "every": max(1, every),
                        "source": source,
                    }
                    if manifest.get("model"):
                        item["model"] = str(manifest["model"])
                    q["pending"].append(item)
                changed = True
                log(f"[llm] 已从失败包原子意图恢复 GLM target：{target}（第 {runs} 局）")
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
    binary = shutil.which(cfg.get("opencode_bin", "opencode"))
    model, every, source = resolve_review_plan(cfg, binary, log=log)
    # 成功复盘饥饿只放宽真实 fallback 的节奏，绝不覆盖已经解析成功的 preferred
    # 模型。GLM 可用时强制交替到 K3 会让迁移后的主模型无故少一半机会；只有
    # resolve_review_plan 因真实 unavailable/cooldown 选中 fallback 时才运行 K3。
    last_ok = agent.know.progression.get("last_successful_review_run", 0)
    starve_every = max(1, int(cfg.get("review_every_runs", 5)))
    starved = runs - last_ok >= starve_every
    if source == "fallback":
        # 兜底节奏独立记账（preferred 尝试不得刷新兜底计数）；
        # 饥饿态下豁免节奏门槛——交替本身就是节奏，再卡门槛会漏掉轮次。
        last = agent.know.progression.get("last_fallback_review_run", 0)
        if not starved and runs - last < every:
            return
        progression_key = "last_fallback_review_run"
    else:
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
                    "model": model, "every": every, "source": source,
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
    log(f"[llm] 复盘请求已入队（第{runs}局，{source}/{model}，待消化 {len(q['pending'])} 批{starve_note}），游玩不等待")
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
    selfcheck_ok: bool = True
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


def _sandbox_git(repo: Path, args: list[str], *, binary: bool = False,
                 timeout: int = 120, env: dict[str, str] | None = None,
                 ) -> subprocess.CompletedProcess:
    return _run_captured_stop_aware(
        ["git", "-C", str(repo), *args], binary=binary, timeout=timeout, env=env)


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
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(index_path)
        env["GIT_OBJECT_DIRECTORY"] = str(object_dir)
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(source_objects)
        env["GIT_OPTIONAL_LOCKS"] = "0"
        return root, env
    except Exception:
        try:
            if root.is_dir() and _is_owned_review_temp(root.resolve(), prefix):
                shutil.rmtree(root)
        except OSError:
            pass
        raise


def _discard_private_sandbox_git(root: Path | None, prefix: str, log=print) -> None:
    if root is None:
        return
    try:
        resolved = root.resolve()
        if _is_owned_review_temp(resolved, prefix):
            shutil.rmtree(resolved)
    except OSError as exc:
        log(f"[llm] private Git capture cleanup failed; retained: {root} ({exc})")


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
    if sandbox.stalled:
        return "stall"
    if sandbox.timed_out:
        return "timeout"
    if sandbox.rc not in (-1, 0):
        return "process_exit"
    if sandbox.online_paths:
        return "online_runtime"
    if (sandbox.unexpected_paths or "deny-only" in reason
            or "路径边界" in reason or "allowlist" in reason):
        return "path_boundary"
    if not sandbox.selfcheck_ok or "自检" in reason:
        return "selfcheck"
    if sandbox.patch and ("提交" in reason or "冲突" in reason):
        return "commit_conflict"
    return "review_failure"


def _current_head_for_salvage() -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_DIR), "rev-parse", "--verify", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


_REJECTION_LEDGER_HEADER = """# GLM 复盘拒合批次清单

这是一份由复盘宿主维护、受 Git 跟踪的拒合账本。失败包仍完整保存在
`knowledge/code_backups/review_salvage/`；本清单只记录索引和处理状态，不代替原始证据。

每次新拒合在失败包原子发布后立即追加一行，并单独建立 Git commit；正常运行时同步推送，
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
    model = manifest.get("model") or "—"
    marker = f"<!-- rejection:{package_name} -->"
    return (
        f"{marker}\n"
        f"| {_ledger_cell(manifest.get('time'))} | {_ledger_cell(batch)} | `{pre_head}` | "
        f"{_ledger_cell(manifest.get('failure_kind'))} | {_ledger_cell(model)} | "
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
        status = "待 GLM 重审/补合"
        if marker in current:
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
                package_name, manifest, status="待 GLM 重审/补合",
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
    action = "GLM 已补合" if resolution == "integrated" else "GLM 复审确认无有效成果"
    final_status = f"{action}并闭环 `{commit[:8]}`"
    final_reason = f"GLM 重审结论与提交 {commit[:8]} 已推送；远端确认后精确清理对应失败包"
    final_ok = _update_rejection_ledger(
        original_name, manifest, status=final_status, package_cell="（闭环清理）",
        reason=final_reason,
        message=f"chore(sts2-ascend): 关闭 GLM 重审批次 {original_name}", log=log)
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
    if not _delete_closed_quarantine(quarantine, log=log):
        return False
    log(f"[llm] GLM 失败包已完成重审、远端确认并删除：{original_name}")
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
    commit: str, pushed: bool, log=print,
) -> dict[str, list[str]]:
    """Persist GLM receipts and let the host close only remotely accepted work."""
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
    code_upstream = bool(pushed or _upstream_contains_commit(commit))
    # Persist the complete lineage on the target first.  If the host crashes at
    # any later instruction, startup can propagate the same GLM receipt without
    # spending another model call.
    ordered = [target, *[name for name in lineage if name != target]]
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
    env = dict(os.environ)
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
        log(f"[llm] 已从 raw clone 物化 GLM 重审候选证据：{package.name} "
            f"({len(paths)} paths, {candidate_path.stat().st_size} bytes；不会自动应用)")
        return manifest
    finally:
        candidate_temp.unlink(missing_ok=True)
        inventory_temp.unlink(missing_ok=True)
        try:
            if index_root.is_dir() and index_root.parent == _review_work_root().resolve():
                shutil.rmtree(index_root)
        except OSError:
            pass


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
        "auto_apply": False,
        "review_contract": (
            "GLM must compare this evidence with current HEAD, selectively reimplement "
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


def _parse_retry_resolutions(report: str, package_names) -> dict[str, str]:
    """Softly parse GLM's per-package resolution lines; absence is not a gate."""
    requested = set(_normalize_salvage_package_names(package_names))
    found: dict[str, str] = {}
    marker = "retry_resolution:"
    for raw_line in str(report or "").splitlines():
        line = raw_line.strip().strip("`*")
        position = line.find(marker)
        if position < 0:
            continue
        parts = line[position + len(marker):].strip().split()
        if len(parts) < 2:
            continue
        package = parts[0].strip("`<>,;:[]()")
        resolution = parts[1].strip("`<>,;:[]().")
        if package in requested and resolution in _RETRY_RESOLUTION_VALUES:
            found[package] = resolution
    return found


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save_review_salvage(
    pre_head: str, reason: str, sandbox: SandboxReviewResult, *,
    batch_runs: list[int] | None = None, model: str = "", source: str = "",
    every: int | None = None, replay_target: str = "",
    replay_attempts: list[str] | None = None,
    replay_queue_ids: list[str] | None = None, log=print,
) -> Path | None:
    """原子保存全部失败成果供 GLM 重审与后续分析；永不自动应用。"""
    if sandbox.salvage_saved:
        saved = Path(sandbox.salvage_saved)
        try:
            manifest = json.loads((saved / "manifest.json").read_text(encoding="utf-8"))
            _record_review_rejection(saved, manifest, log=log)
        except (OSError, ValueError, TypeError):
            pass
        return saved

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
        "reason": reason,
        "pre_head": pre_head,
        "current_head": _current_head_for_salvage(),
        "batch_runs": list(batch_runs or []),
        "model": model,
        "source": source,
        "every": every,
        "return_code": sandbox.rc,
        "timed_out": sandbox.timed_out,
        "stalled": sandbox.stalled,
        "stopped": sandbox.stopped,
        "selfcheck_ok": sandbox.selfcheck_ok,
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
        "inspection_hint": (
            "files/ 与 wip.patch 是全量失败现场；宿主只将其作为证据交回 GLM，"
            "由 GLM 基于当前 HEAD 重审、解冲突，禁止自动应用。"),
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
    translator: "OpencodeJsonTranslator", *, stall_warn_seconds: float = 0,
    stall_timeout_seconds: float = 0, log=print,
) -> SandboxReviewResult:
    """在无 remote、无共享 Git 元数据的临时 clone 中运行模型并导出精确 patch。"""
    sandbox_root = _new_review_temp("sts2-review-sandbox-")
    sandbox_repo = sandbox_root / "repo"
    result = SandboxReviewResult(error="隔离复盘未完成")
    paths: list[str] = []
    validation_git_root: Path | None = None
    validation_prefix = "sts2-review-validation-index-"
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
        sandbox_cmd = list(cmd)
        try:
            sandbox_cmd[sandbox_cmd.index("--dir") + 1] = str(sandbox_repo)
        except (ValueError, IndexError):
            result = SandboxReviewResult(error="复盘命令缺少 --dir 安全边界")
            return result

        rc, out, timed_out, stopped, stalled = _stream_run(
            sandbox_cmd, timeout_seconds, translate=translator.feed,
            stall_warn_sec=stall_warn_seconds,
            stall_timeout_sec=stall_timeout_seconds)
        if stopped or timed_out or stalled or rc != 0:
            result = SandboxReviewResult(
                rc=rc, out=out, timed_out=timed_out, stopped=stopped,
                stalled=stalled,
                error=("复盘 CLI/工具调用无进展挂起" if stalled
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
        # stop 可能落在 clone、checkout、自检、patch 导出或 capture 任一步；
        # 每次离开 try 都重新取样，不能只依赖 _stream_run 的瞬时返回值。
        result.stopped = result.stopped or _review_stop_requested()
        if result.stopped and sandbox_root.is_dir():
            # 直播热停走 O(1) 快速保留：不在 Stop 临界区 reset/add/hash/copy。
            # 项目内先发布指针包，新 Brain 的 worker 再异步搬运完整 clone。
            result.retained_sandbox_dir = str(sandbox_root)
        else:
            try:
                _capture_sandbox_wip(
                    sandbox_repo, pre_head, result, log=log, prompt_text=prompt)
            except _ReviewStopped:
                result.stopped = True
                result.retained_sandbox_dir = str(sandbox_root)
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
        if (sandbox_repo.is_dir() and not result.snapshot_complete
                and not result.retained_sandbox_dir):
            # 全量捕获链自身出错时，绝不删除唯一现场。外层补合发布会把整个
            # clone（含 .git/ignored/越界内容）复制到项目内 raw_sandbox/。
            result.error = result.error or "隔离复盘全量现场捕获不完整"
            result.retained_sandbox_dir = str(sandbox_root)
        if result.error and sandbox_root.is_dir() and not result.retained_sandbox_dir:
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
    """清理上一个大脑进程死亡后遗留的孤儿复盘 opencode。

    大脑被杀/崩溃时，正在执行的复盘子进程会被系统收养继续跑——它改的文件
    没人收集、reviewing 标记没人清。worker 启动时（自身尚无在跑复盘，安全）
    按命令行特征精确击杀：标题 ASCII 前缀 sts2-ascend + --auto（用户自己的
    opencode 会话不带这两个组合，绝不误伤）。
    """
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "& { param($repo) Get-CimInstance Win32_Process | Where-Object { "
             "$_.Name -match '^opencode(\\.exe)?$' -and $_.CommandLine -match 'sts2-ascend' "
             "-and $_.CommandLine -match '--auto' -and $_.CommandLine.IndexOf($repo, "
             "[StringComparison]::OrdinalIgnoreCase) -ge 0 } | ForEach-Object { "
             "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }",
             str(REPO_DIR)],
            capture_output=True, timeout=30, creationflags=creationflags)
        log("[llm] 已清理遗留的孤儿复盘进程（如有）")
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
                log(f"[llm] 延迟现场已补全，GLM 重审候选证据稍后懒物化：{exc}")
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
            if empty and _upstream_ledger_contains(original, "并闭环"):
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
                    "retry_same_model": bool(item.get("model")),
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
    _recover_deferred_salvages(log=log)
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
                    requeued = _reviewing_items(q.get("reviewing"))
                    lost_runs = [item.get("run") for item in requeued]
                    if requeued:
                        log(f"[llm] 上场复盘随进程中断，重新入队追及：第 {lost_runs} 局")
                        seen = {_queue_item_identity(item) for item in requeued}
                        pending = [
                            item for item in q.get("pending", [])
                            if _queue_item_identity(item) not in seen]
                        # review_queue_max 现在只限制单次提示词批量，不再丢弃持久队列。
                        # 中断批次退到队尾，让停止期间/其后新完成的局先获得复盘，
                        # 避免 100 局旧批在反复热更新时永久压住新鲜样本。
                        q["pending"] = pending + requeued
                    q["reviewing"] = None
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
                _resume_host_salvage_closures(log=log)
                next_salvage_maintenance = time.monotonic() + 60.0
                if _review_stop_requested():
                    return
            # Host-only receipt/push/ledger/quarantine recovery is independent
            # from paid model execution.  When LLM review is disabled, keep the
            # durable review queue untouched and run only maintenance.
            if not load_llm_config().get("enabled", True):
                if _wait_review_stop(30):
                    return
                continue
            retry_wait = 0.0
            with _queue_lock:
                q = _load_queue_unlocked()
                pending = q.get("pending", [])
                if pending and not q.get("reviewing"):
                    worker_cfg = load_llm_config()
                    cap = max(1, min(
                        int(worker_cfg.get("review_queue_max", 100)),
                        int(worker_cfg.get("max_runs_in_packet", 100))))
                    now = time.time()
                    eligible_indexes = [index for index, item in enumerate(pending)
                                        if float(item.get("retry_after", 0) or 0) <= now]
                    if eligible_indexes:
                        first = pending[eligible_indexes[0]]
                        retry_group = str(first.get("retry_group") or "")
                        # A failed package is always a standalone GLM job. Normal
                        # online items may still batch up to cap, but never absorb
                        # a retry group or another package lineage.
                        eligible_indexes = [
                            index for index in eligible_indexes
                            if ((str(pending[index].get("retry_group") or "") == retry_group)
                                if retry_group else
                                not pending[index].get("retry_group"))
                        ][:cap]
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
                        earliest = min(float(item.get("retry_after", 0) or 0)
                                       for item in pending)
                        retry_wait = min(30.0, max(1.0, earliest - now))
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
                if outcome in {"failed", "replay_pending"}:
                    label = "失败包尚未完成 GLM 闭环" if outcome == "replay_pending" else "复盘失败"
                    log(f"[llm] {label}，批次已放回队尾，{delay:.0f}s 后继续追及")
                    retry_wait = min(30.0, max(1.0, delay))
            if _wait_review_stop(retry_wait or 5):
                return
        except Exception as exc:
            log(f"[llm] 复盘工作线程异常（已忽略，30s 后继续）：{exc}")
            if _wait_review_stop(30):
                return


def _run_batch_review(agent, batch: list[dict], log) -> str:
    if _review_stop_requested():
        return "canceled"
    cfg = load_llm_config()
    binary = shutil.which(cfg.get("opencode_bin", "opencode"))
    # 尊重入队时的来源决策，且以**最新一条**为准：饥饿交替出牌时批次常混含
    # 两种来源，若按"含 fallback 即整场 k3"则优先链的恢复探测永远轮不到。
    # 最新入队项携带的是入队时刻最新的世界状态。
    planned = [p for p in batch if p.get("source") and p.get("model")]
    if planned:
        picked = planned[-1]
        model, every, source = picked["model"], int(picked.get("every", 5)), picked["source"]
    else:
        model, every, source = resolve_review_plan(cfg, binary, log=log)
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
            "model": model,
            "every": max(1, int(every)),
            "source": source,
            "retry_same_model": True,
            "salvage_packages": list(inherited_packages),
            "salvage_attempts": list(inherited_attempts),
        })
        if replay_target:
            item["replay_target"] = replay_target
    _persist_reviewing_batch_metadata(batch, log=log)
    runs_list = [p["run"] for p in batch]
    evidence_only = bool(batch) and all(bool(item.get("evidence_only"))
                                        for item in batch)
    replay_note = f"，重审失败包 {inherited_packages}" if inherited_packages else ""
    log(f"[llm] 异步复盘启动：覆盖第 {runs_list} 局（模型 {model}{replay_note}）")
    status: dict = {}
    executed = run_review(agent.know, log=log, model=model, every=every, source=source,
                          batch_runs=runs_list, async_mode=True, _status=status,
                          salvage_packages=inherited_packages,
                          salvage_attempts=inherited_attempts,
                          replay_queue_ids=[str(item.get("queue_id") or "")
                                            for item in batch],
                          evidence_only=evidence_only)
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
    for item in batch:
        item.update({
            "model": model,
            "every": max(1, int(every)),
            "source": source,
            "retry_same_model": True,
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
        log(f"[llm] GLM 失败包重审回执：{resolutions or '未写 retry_resolution'}"
            f"；仍 pending={unresolved}")
        if status.get("host_pending_salvage_packages"):
            log("[llm] GLM 已完成逐包结论；清单/删除由宿主耐久恢复继续处理："
                f"{status['host_pending_salvage_packages']}")
    if status.get("commit"):
        log(f"[llm] GLM 复盘提交回执：commit={status['commit'][:12]} "
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
        log("[llm] 本轮提交已保留，但失败包尚未得到远端确认的逐包结论；继续交给 GLM")
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
    binary = shutil.which(cfg.get("opencode_bin", "opencode"))
    model, every, source = resolve_review_plan(cfg, binary)
    print(f"plan: model={model} every={every} source={source}")
    executed = run_review(know, model=model, every=every, source=source, async_mode=True)
    print(f"done, executed={executed}")


if __name__ == "__main__":
    main()
