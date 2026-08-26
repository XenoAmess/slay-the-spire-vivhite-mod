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
    复盘激活期间对局存档只提交在线运行文件，自检失败仅反向应用 allowlist patch。
  - 复盘完成若产生变更：标记 request_restart，主循环在下一局间安全点以退出码 42 自重启加载。

设计要点（继承）：
  - 不直接调模型裸 API；spawn `opencode run` 无头会话——带完整工具链的智能体，走本机 OpenCode 授权。
  - 受限写入 + Git 安全网：只可改策略代码和复盘报告 allowlist；在线统计只读。
  - 复盘过程经 review_live.stream 直播给 review_viewer.py 悬浮窗。

手动触发 `py brain/llm_review.py --now`（同步执行，用于人工调试）。
任何异常只记日志，绝不中断游玩主循环。
"""
from __future__ import annotations

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
PREFERRED_STATE_FILE = KNOWLEDGE_DIR / "preferred_model_state.json"
LIVE_STREAM = KNOWLEDGE_DIR / "review_live.stream"          # 复盘直播流（review_viewer.py 读取）
VIEWER_PATH = BASE_DIR / "brain" / "review_viewer.py"
SALVAGE_ROOT = KNOWLEDGE_DIR / "code_backups" / "review_salvage"
REVIEW_MUTABLE_PATHS = [
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
]
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
        "models_probe_timeout_sec": 60,
        # 复盘直播悬浮窗（review_viewer.py）
        "viewer_enabled": True,
        # 语音朗读器（tts/）：edge=Edge 实时直播 + IndexTTS GPU 最终结论（默认） /
        # indextts=兼容用全 IndexTTS / hybrid=SAPI 实时直播 + IndexTTS GPU 结论 /
        # nano=全克隆音色（滞后大） / sapi=纯系统语音 / off=关闭
        "tts_mode": "edge",
        # 异步复盘单批上限；持久队列本身不截断
        "review_queue_max": 100,
    }
    merged.update({k: v for k, v in cfg.items() if v is not None})
    # ``viewer.enabled`` is canonical; the legacy LLM-local switch remains a
    # fallback for existing installations.
    if isinstance(viewer_cfg, dict) and viewer_cfg.get("enabled") is not None:
        merged["viewer_enabled"] = bool(viewer_cfg["enabled"])
    return merged


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


def _recent_run_summaries(n: int, batch_runs: list[int] | None = None) -> list[dict]:
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
        return [_summarize_run(data, "recent") for _, data in recent]

    seen = {path.name for path, _ in selected}
    selected.extend(_requested_archived_runs(requested, seen))
    selected.sort(key=lambda row: (int(row[1].get("run_number") or 0), row[0].name))
    matched = {int(data.get("run_number")) for _, data in selected
               if data.get("run_number") is not None}
    out = [_summarize_run(data, "exact_batch") for _, data in selected]
    if matched != requested:
        # Historical logs predate run_number.  Keep a bounded recent fallback for
        # diagnostic context, but label it so the coach cannot mistake it for the
        # requested queue batch.
        fallback_n = max(0, n - len(out))
        for path, data in list(recent)[-fallback_n:] if fallback_n else []:
            if path.name not in seen:
                out.append(_summarize_run(data, "recent_fallback_unmapped"))
    return out


def build_prompt(know, cfg: dict, every: int | None = None,
                 batch_runs: list[int] | None = None) -> str:
    n = int(cfg.get("max_runs_in_packet", 100))
    run_summaries = _recent_run_summaries(n, batch_runs=batch_runs)
    evidence_text = []
    for summary in run_summaries:
        evidence_text.extend(summary.get("combat_notes") or [])
        evidence_text.extend(summary.get("key_reasons") or [])
    native = getattr(know, "game_knowledge", None)
    packet = {
        "runs_summary": run_summaries,
        "run_evidence_scope": {
            "requested": list(batch_runs or []),
            "exact": sorted(int(item["run_number"]) for item in run_summaries
                            if item.get("evidence_match") == "exact_batch"),
            "missing": sorted(set(int(x) for x in (batch_runs or []))
                              - {int(item["run_number"]) for item in run_summaries
                                 if item.get("evidence_match") == "exact_batch"}),
            "fallback_is_not_batch_evidence": any(
                item.get("evidence_match") == "recent_fallback_unmapped"
                for item in run_summaries),
        },
        "stats_digest": _stats_digest(know),
        # Never inline the full ~9 MB corpus.  The index chooses entities named in
        # recent evidence plus the most consequential learned card/enemy records;
        # corpus_paths lets the reviewer drill into exact JSONL facts on demand.
        "native_game_knowledge": (native.review_digest(know.stats, evidence_text)
                                  if native is not None else
                                  {"snapshot": {"available": False,
                                                "error": "native index not initialized"}}),
    }
    lessons_tail = ""
    lessons_path = KNOWLEDGE_DIR / "lessons.md"
    if lessons_path.exists():
        lessons_tail = lessons_path.read_text(encoding="utf-8")[-2500:]

    cadence = every or cfg.get('review_every_runs', 10)
    if batch_runs and len(batch_runs) > 1:
        scope = f"本次复盘覆盖第 {batch_runs[0]}~{batch_runs[-1]} 局（共 {len(batch_runs)} 局，异步追及队列）"
    elif batch_runs:
        scope = f"本次复盘覆盖第 {batch_runs[0]} 局"
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

    return f"""你是「sts2-ascend」杀戮尖塔2自主学习智能体的总教练。{scope}。
智能体本体：启发式决策引擎（brain/policy.py，参数在 knowledge/policy.json）+ 统计学习（knowledge/stats.json），反复游玩战士 Ironclad。

# 数据摘要（紧凑 JSON 已内嵌；原生事实按本批实体检索，完整文件可按路径深读）
```json
{packet_json}
```

最近的 lessons.md 尾部：
```
{lessons_tail}
```

# 你的任务（严格按顺序）
1. 归因分析：主要死因趋势、打法缺陷、卡组构建问题、地图路线问题、代码缺陷。
   涉及卡牌/怪物/遗物/药水/事件机制时，必须优先查阅 packet 中的
   `native_game_knowledge`；摘要不够就按 `corpus_paths` 精确检索相应 runtime 与
   mechanics JSONL。不得用记忆中的旧版 STS2/STS1 数值覆盖 manifest 所指版本。
2. 将复盘报告**追加写入** `sts2-ascend/knowledge/meta_review.md`（新建一节，标题含日期时间）：
   归因分析、你做出的每项调整及理由、新沉淀的经验知识（中文）。
3. **只可修改下列 allowlist**（越界 patch 会被宿主拒绝，安全基础设施不可自改）：
   - `brain/__main__.py`、`agent.py`、`client.py`、`config.json`、`knowledge.py`、
     `native_knowledge.py`、`policy.py`、`reflect.py`、`selfcheck.py`
   - `knowledge/meta_review.md`、`knowledge/review_conclusion.txt`
   - `knowledge/stats.json`、`progression.json`、`policy.json`、`lessons.md` 和 `runs/`
     是在线大脑持续写入的数据，复盘期间**只读，绝对禁止修改**；新经验写入本次
     `meta_review.md` 报告，待在线学习流程自行吸收
   - 不得修改 `brain/autogit.py`、`runner.py`、`llm_review.py`、`lifecycle.py` 或
     `scripts/` 生命周期入口
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
- 禁止停止/启动任何进程（游戏和大脑正在运行）
- 禁止修改上述 allowlist 之外的任何文件（包括其他 `sts2-ascend/` 文件、Vivhite mod、游戏本体、系统文件）
- 禁止删除 `knowledge/runs/` 下的历史对局日志、禁止安装依赖

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


def _stream_run(cmd: list[str], timeout_sec: int,
                translate=None) -> tuple[int, str, bool, bool]:
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
    proc = subprocess.Popen(
        cmd, cwd=str(REPO_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=8192, env=env,
        **_process_group_kwargs())

    # 128 * 8192 约 1 MiB；即使模型连续八小时输出，reader 也不会无限吃内存。
    q: queue.Queue[str] = queue.Queue(maxsize=128)
    reader_cancel = threading.Event()
    reader_done = threading.Event()

    def _reader() -> None:
        try:
            while not reader_cancel.is_set():
                chunk = (proc.stdout.read(8192) if proc.stdout is not None else "")
                if not chunk:
                    break
                while not reader_cancel.is_set():
                    try:
                        q.put(chunk, timeout=0.2)
                        break
                    except queue.Full:
                        continue
        except (OSError, ValueError):
            pass
        finally:
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
            if _review_stop_requested():
                stopped = True
                _terminate_process_tree(proc)
                break
            if time.monotonic() > deadline:
                timed_out = True
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
    return rc, "".join(tail), timed_out, stopped


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
               async_mode: bool = False, _status: dict | None = None) -> bool:
    """执行一次大模型复盘。返回 True 表示复盘产生了已提交的变更（调用方应重启大脑）。

    流程：保存在线进度 → opencode 隔离复盘 → 路径 allowlist → 自检 → 精确提交；
    失败时从隔离 clone 导出包含全部改动（含 ignored/越界）的补合包；
    allowlist 只约束自动合入，不约束失败成果留档。
    source="preferred" 时若执行失败（非零退出/超时/异常）会对优先模型记失败冷却。
    async_mode=True（异步队列工作线程调用）时，在线存档和推送继续独立运行；
    它们不会参与隔离复盘 patch 的验收。
    """
    if _status is not None:
        _status.clear()
        _status.update({"outcome": "failed", "reason": "复盘未完成", "canceled": False})
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
    if tuple(REVIEW_MUTABLE_PATHS) != tuple(autogit.REVIEW_PATCH_ALLOWLIST):
        log("[llm] 复盘 allowlist 与 Git 安全层不一致，拒绝启动")
        return False

    runs = know.stats["global"]["runs"]
    batch_txt = f"第{batch_runs[0]}~{batch_runs[-1]}局" if batch_runs and len(batch_runs) > 1 \
        else f"第{batch_runs[0]}局" if batch_runs else f"第{runs}局"
    # 1) 只保存在线数据。代码必须已干净；自动流程绝不替用户提交开发中的代码。
    autogit.commit_progress_result(
        f"chore(sts2-ascend): {batch_txt}后复盘前在线存档",
        log=log, paths=REVIEW_CONCURRENT_PATHS,
    )
    pre_head = autogit.head()
    before_review = autogit.changed_paths_since(pre_head, REVIEW_MUTABLE_PATHS)
    if before_review:
        log("[llm] 复盘启动前 allowlist 路径已有用户改动，拒绝让模型覆盖："
            + ", ".join(before_review[:12]))
        return False

    stamp = time.strftime("%Y-%m-%d %H:%M")
    log(f"[llm] ===== 启动大模型复盘（{entry} via opencode [{source}]，{batch_txt}，备份点 {pre_head[:8]}）=====")
    prompt = build_prompt(know, cfg, every, batch_runs)
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
    rc, out, timed_out, stopped = -1, "", False, False
    eff_timeout_min = float(cfg.get("preferred_timeout_min", 480)) if source == "preferred" \
        else float(cfg.get("timeout_min", 480))
    translator = OpencodeJsonTranslator()
    sandbox = SandboxReviewResult(error="复盘尚未运行")
    try:
        sandbox = _run_review_sandbox(
            cmd, prompt, pre_head, int(eff_timeout_min * 60), translator, log=log)
        rc, out, timed_out, stopped = (
            sandbox.rc, sandbox.out, sandbox.timed_out, sandbox.stopped)
        # stop 可能恰好落在 opencode 自然退出与宿主验收之间；不能只信任
        # _stream_run 返回瞬间的 stopped 快照。
        stopped = stopped or _review_stop_requested()
        sandbox.stopped = sandbox.stopped or stopped
        if sandbox.error or stopped:
            _save_review_salvage(
                pre_head, sandbox.error or "协作停止留下的部分复盘现场", sandbox,
                batch_runs=batch_runs,
                model=entry, source=source, log=log)
        # 停止批次永不合入 patch，也永不消费队列，让新进程重做该批。
        if stopped:
            if _status is not None:
                _status.update({"outcome": "canceled", "reason": "整套停止", "canceled": True})
            retry_note = "批次下次启动重试" if async_mode else "手动复盘已取消"
            log(f"[llm] 整套停止已取消隔离复盘；真实工作树未改，{retry_note}"
                f"（复盘前基线 {pre_head[:8]}）")
            return False
        log(f"[llm] 复盘会话结束（exit={rc}）。输出尾部：\n{out[-2000:]}")
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
            "stopped": stopped,
            "review_id": review_id,
            # 结论取自即将删除的隔离 clone，已过 allowlist/selfcheck/patch 导出；
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
            try:
                know.save()
            except OSError:
                pass
            if _status is not None:
                _status.update({"outcome": "completed", "reason": "合法复盘无文件变更"})
            log("[llm] 复盘未产生任何文件变更，跳过提交")
            return False
        try:
            review_paths = list(autogit.validate_review_paths(review_paths))
        except ValueError as exc:
            _save_review_salvage(
                pre_head, f"Git 安全层拒绝复盘 patch：{exc}", sandbox,
                batch_runs=batch_runs, model=entry, source=source, log=log)
            log(f"[llm] Git 安全层拒绝复盘 patch：{exc}")
            return False
        if not sandbox.patch:
            _save_review_salvage(
                pre_head, "隔离复盘未导出有效 patch", sandbox,
                batch_runs=batch_runs, model=entry, source=source, log=log)
            log("[llm] 隔离复盘未导出有效 patch，拒绝合入")
            return False

        # 3) marker 在 update-ref/push 前原子发布；patch commit 的私有 index 只包含
        # 模型 hunk，同文件中并发用户 hunk 留在工作树且不会被提交。
        def prepare_marker(provisional) -> bool:
            # prepare 在工作树 apply/update-ref 之前、同一 Git 事务锁内执行，是
            # 合入前最后一道停止闸门。停止批次保留 reviewing 给新进程恢复。
            if _review_stop_requested():
                if _status is not None:
                    _status.update({
                        "outcome": "canceled", "reason": "整套停止", "canceled": True})
                log("[llm] patch 合入前收到整套停止请求；取消提交并保留复盘批次")
                return False
            return _write_restart_marker({
                "pre_head": pre_head,
                "review_parent": provisional.before_head,
                "review_commit": provisional.commit,
                "paths": review_paths,
                "time": stamp,
            }, log=log)

        def abort_marker(provisional) -> None:
            _remove_restart_marker(provisional.commit, log=log)

        if _review_stop_requested():
            if _status is not None:
                _status.update({"outcome": "canceled", "reason": "整套停止", "canceled": True})
            log("[llm] 隔离验证后收到整套停止请求；不进入 patch 提交")
            sandbox.stopped = True
            _save_review_salvage(
                pre_head, "隔离验证后整套停止", sandbox,
                batch_runs=batch_runs, model=entry, source=source, log=log)
            return False
        result = autogit.commit_patch_result(
            sandbox.patch,
            f"feat(sts2-ascend): {batch_txt} LLM 复盘变更（详见 knowledge/meta_review.md）",
            review_paths, log=log, prepare=prepare_marker, abort_prepare=abort_marker,
        )
        if not result.created:
            canceled = bool(_status is not None and _status.get("outcome") == "canceled")
            sandbox.stopped = sandbox.stopped or canceled or _review_stop_requested()
            if not canceled and _status is not None:
                _status["reason"] = result.reason or "复盘 patch 提交失败"
            _save_review_salvage(
                pre_head,
                "patch 合入前整套停止" if canceled else (
                    result.reason or "复盘 patch 提交失败"),
                sandbox, batch_runs=batch_runs, model=entry, source=source, log=log)
            log(f"[llm] 复盘 patch 未能安全提交，保留现场供诊断：{result.reason}")
            return False
        discard_verified_snapshot = True
        reviewed_through = max(batch_runs) if batch_runs else runs
        know.progression["last_successful_review_run"] = max(
            int(know.progression.get("last_successful_review_run", 0)), reviewed_through)
        try:
            know.save()
        except OSError:
            pass
        if _status is not None:
            _status.update({"outcome": "changed", "reason": "复盘 patch 已提交"})
        log("[llm] 复盘变更已提交，重启大脑以加载…")
        return True
    except Exception as exc:
        reason = f"复盘宿主验收/提交异常：{exc}"
        if _status is not None:
            _status["reason"] = reason
        sandbox.stopped = sandbox.stopped or _review_stop_requested()
        _save_review_salvage(
            pre_head, reason, sandbox, batch_runs=batch_runs,
            model=entry, source=source, log=log)
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


def _validate_queue(payload) -> dict:
    """Validate the fields consumed by the worker without discarding unknown keys."""
    if not isinstance(payload, dict):
        raise ReviewQueueError("review queue root must be an object")
    pending = payload.get("pending")
    reviewing = payload.get("reviewing")
    if not isinstance(pending, list):
        raise ReviewQueueError("review queue pending must be a list")
    for index, item in enumerate(pending):
        if not isinstance(item, dict) or "run" not in item:
            raise ReviewQueueError(f"review queue pending[{index}] is not a run object")
        run = item.get("run")
        retry_count = item.get("retry_count", 0)
        retry_after = item.get("retry_after", 0)
        if isinstance(run, bool) or not isinstance(run, int) or run <= 0:
            raise ReviewQueueError(f"review queue pending[{index}].run must be a positive integer")
        if (isinstance(retry_count, bool) or not isinstance(retry_count, int)
                or retry_count < 0):
            raise ReviewQueueError(
                f"review queue pending[{index}].retry_count must be a non-negative integer")
        if (isinstance(retry_after, bool) or not isinstance(retry_after, (int, float))
                or retry_after < 0 or not math.isfinite(float(retry_after))):
            raise ReviewQueueError(
                f"review queue pending[{index}].retry_after must be a finite non-negative number")
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
        existing.update(int(value) for value in
                        ((q.get("reviewing") or {}).get("runs") or []))
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
    # 成功复盘守卫 v2：距上次成功复盘 >= 阈值即视为"饥饿"。饥饿时**交替出牌**
    # 而非锁死兜底——v1 的无条件强制 k3 在 k3 本身不可用时形成死锁：
    # 守卫强制 k3 → k3 失败 → 永无成功 → 永远强制 k3，优先模型恢复也
    # 没机会被探测（历史实证：100 局零成功，last_llm_review_run 冻结）。
    # 交替规则：上次尝试是 fallback 就放行优先链（恢复探测），否则强制兜底；
    # 任一路成功即刷新 last_successful_review_run、退出饥饿态。
    last_ok = agent.know.progression.get("last_successful_review_run", 0)
    starve_every = max(1, int(cfg.get("review_every_runs", 5)))
    starved = runs - last_ok >= starve_every
    if starved and source == "preferred":
        if agent.know.progression.get("last_review_attempt_source") != "fallback":
            model, every, source = cfg["model"], starve_every, "fallback"
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
    starve_note = f"（距上次成功复盘 {runs - last_ok} 局，交替出牌）" if starved else ""
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
        _worker_started = True
    _worker_thread = threading.Thread(
        target=_worker_loop, args=(agent, log), daemon=True,
        name="llm-review-worker")
    _worker_thread.start()
    log("[llm] 异步复盘工作线程已启动")


def resume_review_queue(agent, log=print) -> None:
    """Resume queued/interrupted reviews immediately after brain startup."""
    if not load_llm_config().get("enabled") or _review_stop_requested():
        return
    try:
        with _queue_lock:
            q = _load_queue_unlocked()
            has_work = bool(q.get("pending") or q.get("reviewing"))
    except (ReviewQueueError, OSError) as exc:
        log(f"[llm] 复盘队列暂不可读；保留原文件，本次不启动 worker：{exc}")
        return
    if has_work:
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
    unexpected_paths: tuple[str, ...] = ()
    snapshot_dir: str = ""
    snapshot_complete: bool = False
    retained_sandbox_dir: str = ""
    salvage_saved: str = ""


def _sandbox_git(repo: Path, args: list[str], *, binary: bool = False,
                 timeout: int = 120) -> subprocess.CompletedProcess:
    return _run_captured_stop_aware(
        ["git", "-C", str(repo), *args], binary=binary, timeout=timeout)


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
    try:
        # 不信任模型留下的 index/commit/assume-unchanged 标记。
        reset = _sandbox_git(repo, ["reset", "--mixed", "--quiet", pre_head])
        if reset.returncode != 0:
            log("[llm] 失败复盘 WIP 基线恢复失败；仅保存诊断元数据")
            return
        # -f 明确纳入 ignored 文件；.git 元数据仍由 Git 自身排除。宿主写入的
        # prompt 若未被模型修改则随后退回基线；被修改/删除时也作为越界成果保留。
        stage_all = _sandbox_git(repo, ["add", "--all", "--force", "--", "."])
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
            repo, ["reset", "--quiet", pre_head, "--", own_prompt])
            if prompt_unchanged else subprocess.CompletedProcess([], 0, "", ""))
        if stage_all.returncode != 0 or unstage_prompt.returncode != 0:
            log("[llm] 失败复盘全量 WIP 暂存失败；仅保存诊断元数据")
            return
        names = _sandbox_git(repo, ["diff", "--cached", "--name-only", "-z", pre_head, "--"])
        if names.returncode != 0:
            log("[llm] 失败复盘全量 WIP 路径枚举失败；仅保存诊断元数据")
            return
        changed = list(dict.fromkeys(
            item.replace("\\", "/") for item in names.stdout.split("\0") if item))
        if prompt_deleted and own_prompt not in changed:
            changed.append(own_prompt)
        allowed_set = {path.replace("\\", "/").rstrip("/")
                       for path in REVIEW_MUTABLE_PATHS}
        allowed = [path for path in changed if path.rstrip("/") in allowed_set]
        unexpected = [path for path in changed if path.rstrip("/") not in allowed_set]
        result.wip_paths = tuple(changed)
        result.allowed_paths = tuple(allowed)
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
    if sandbox.timed_out:
        return "timeout"
    if sandbox.rc not in (-1, 0):
        return "process_exit"
    if sandbox.unexpected_paths or "allowlist" in reason:
        return "allowlist"
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save_review_salvage(
    pre_head: str, reason: str, sandbox: SandboxReviewResult, *,
    batch_runs: list[int] | None = None, model: str = "", source: str = "", log=print,
) -> Path | None:
    """原子保存全部失败成果供人工补合；含越界文件，但永不自动应用。"""
    if sandbox.salvage_saved:
        return Path(sandbox.salvage_saved)

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
        "return_code": sandbox.rc,
        "timed_out": sandbox.timed_out,
        "stopped": sandbox.stopped,
        "selfcheck_ok": sandbox.selfcheck_ok,
        "snapshot_complete": sandbox.snapshot_complete,
        "snapshot_included": bool(snapshot is not None and not deferred_snapshot and not deferred_raw),
        "snapshot_deferred": deferred_snapshot,
        "raw_sandbox_included": bool(retained is not None and not deferred_raw),
        "raw_sandbox_deferred": deferred_raw,
        "all_paths": list(all_paths),
        "allowed_paths": list(allowed_paths),
        "rejected_or_unexpected_paths": list(sandbox.unexpected_paths),
        "patch_bytes": patch_bytes,
        "patch_sha256": patch_sha256,
        "auto_apply": False,
        "inspection_hint": "files/ 与 wip.patch 是全量失败现场；人工检查后再选择性补合，禁止自动应用。",
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
            raw_stage = temp / ".raw_sandbox.incomplete"
            shutil.copytree(
                retained, raw_stage, dirs_exist_ok=True,
                symlinks=True, ignore_dangling_symlinks=True,
                copy_function=_copy_snapshot_file)
            raw_stage.replace(temp / "raw_sandbox")
        # 固定三件套始终存在；snapshot 缺失时仍发布空/已有 patch 供诊断。
        if not (temp / "wip.patch").is_file():
            (temp / "wip.patch").write_bytes(patch)
        (temp / "report.md").write_text(
            sandbox.diagnostic_report or "", encoding="utf-8")
        if sandbox.out:
            (temp / "model_output_tail.txt").write_text(
                sandbox.out[-256 * 1024:], encoding="utf-8")
        (temp / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if _review_stop_requested() and not (deferred_raw or deferred_snapshot):
            raise _ReviewStopped()
        temp.replace(final)
        sandbox.salvage_saved = str(final)
        if not deferred_snapshot:
            _discard_sandbox_snapshot(sandbox, log=log)
        if not deferred_raw:
            _discard_retained_sandbox(sandbox, log=log)
        log(f"[llm] 失败复盘成果已保存供补合（不会自动应用）：{final}")
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
            temp.replace(final)
            sandbox.salvage_saved = str(final)
            log(f"[llm] 停止期间已快速发布失败现场指针包：{final}")
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
    translator: "OpencodeJsonTranslator", log=print,
) -> SandboxReviewResult:
    """在无 remote、无共享 Git 元数据的临时 clone 中运行模型并导出精确 patch。"""
    sandbox_root = _new_review_temp("sts2-review-sandbox-")
    sandbox_repo = sandbox_root / "repo"
    result = SandboxReviewResult(error="隔离复盘未完成")
    paths: list[str] = []
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

        rc, out, timed_out, stopped = _stream_run(
            sandbox_cmd, timeout_seconds, translate=translator.feed)
        if stopped or timed_out or rc != 0:
            result = SandboxReviewResult(
                rc=rc, out=out, timed_out=timed_out, stopped=stopped,
                error="复盘进程未成功完成",
            )
            return result

        # 不信任模型留下的 HEAD/index/assume-unchanged 标记；先回到隔离基线，
        # 只保留工作树内容，再做全仓变更枚举。
        reset = _sandbox_git(sandbox_repo, ["reset", "--mixed", "--quiet", pre_head])
        if reset.returncode != 0:
            result = SandboxReviewResult(rc=rc, out=out, error="隔离仓库基线恢复失败")
            return result
        tracked = _sandbox_git(
            sandbox_repo, ["diff", "--name-only", "-z", pre_head, "--"])
        others = _sandbox_git(
            sandbox_repo, ["ls-files", "--others", "--exclude-standard", "-z", "--"])
        if tracked.returncode != 0 or others.returncode != 0:
            result = SandboxReviewResult(rc=rc, out=out, error="无法枚举隔离复盘变更")
            return result
        paths = list(dict.fromkeys(
            [item.replace("\\", "/") for item in (tracked.stdout + others.stdout).split("\0") if item]))
        own_prompt = PROMPT_FILE.relative_to(REPO_DIR).as_posix()
        paths = [path for path in paths if path != own_prompt]
        review_files = {item.replace("\\", "/").rstrip("/")
                        for item in REVIEW_MUTABLE_PATHS}
        unexpected = [path for path in paths
                      if path.replace("\\", "/").rstrip("/") not in review_files]
        if unexpected:
            result = SandboxReviewResult(
                rc=rc, out=out, paths=tuple(paths),
                error="复盘 patch 越过 allowlist：" + ", ".join(unexpected[:12]),
            )
            return result
        if not paths:
            result = SandboxReviewResult(rc=rc, out=out)
            return result

        # 自检也在隔离 clone 内执行；失败代码从未进入真实工作树。
        if not _run_selfcheck(log, sandbox_repo / "sts2-ascend"):
            result = SandboxReviewResult(
                rc=rc, out=out, paths=tuple(paths), error="复盘自检失败", selfcheck_ok=False)
            return result

        # 模型即使在隔离 clone 内自行 commit/stage，也先退回基线 index；仅把验证过
        # 的 allowlist 路径重新 stage，再从基线导出二进制 patch。
        stage = _sandbox_git(sandbox_repo, ["add", "--all", "--", *paths])
        patch = _sandbox_git(
            sandbox_repo,
            ["diff", "--cached", "--binary", "--unified=0", pre_head, "--", *paths],
            binary=True)
        if stage.returncode != 0 or patch.returncode != 0 or not patch.stdout:
            result = SandboxReviewResult(
                rc=rc, out=out, paths=tuple(paths), error="隔离复盘 patch 导出失败")
            return result
        conclusion = ""
        conclusion_rel = "sts2-ascend/knowledge/review_conclusion.txt"
        if conclusion_rel in paths:
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
            paths=tuple(paths),
            patch=patch.stdout,
            conclusion=conclusion,
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
            if result.unexpected_paths and not result.error:
                result.error = (
                    "复盘 patch 越过 allowlist："
                    + ", ".join(result.unexpected_paths[:12]))
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


def _path_in_specs(path: str, specs: list[str]) -> bool:
    value = path.replace("\\", "/").rstrip("/")
    return any(value == spec or value.startswith(spec.rstrip("/") + "/") for spec in specs)


def _partition_review_changes(paths: list[str] | tuple[str, ...]) -> tuple[list[str], list[str], list[str]]:
    """把工作树变更分成复盘 patch、在线并发数据和越界路径。"""
    review, concurrent, unexpected = [], [], []
    review_files = {item.replace("\\", "/").rstrip("/")
                    for item in REVIEW_MUTABLE_PATHS}
    for path in dict.fromkeys(str(item).replace("\\", "/") for item in paths):
        if path.rstrip("/") in review_files:
            review.append(path)
        elif _path_in_specs(path, REVIEW_CONCURRENT_PATHS):
            concurrent.append(path)
        else:
            unexpected.append(path)
    return review, concurrent, unexpected


def _discard_failed_review(autogit, pre_head: str, reason: str, log=print,
                           unexpected: list[str] | None = None) -> bool:
    """保存诊断并仅撤销受控复盘路径；在线文件和越界现场均保留。"""
    try:
        backup_dir = KNOWLEDGE_DIR / "code_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if REVIEW_LOG.exists():
            shutil.copy2(REVIEW_LOG, backup_dir / f"failed_review_{stamp}.md")
        diagnostic = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "pre_head": pre_head,
            "reason": reason,
            "unexpected_paths": unexpected or [],
        }
        (backup_dir / f"failed_review_{stamp}.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        log(f"[llm] 保存失败复盘诊断异常：{exc}")
    restored = autogit.restore_paths(pre_head, REVIEW_MUTABLE_PATHS, log=log)
    if restored:
        log("[llm] 失败复盘的 allowlist patch 已撤销；在线 stats/progression 与越界现场均保留")
    else:
        log("[llm] 失败复盘无法无损撤销；拒绝强制覆盖，现场与诊断均已保留")
    return restored


def _write_restart_marker(payload: dict, log=print) -> bool:
    """原子发布 runner marker；已有待验证 marker 时必须拒绝覆盖。"""
    temp = KNOWLEDGE_DIR / "code_backups" / (
        f".pending_restart.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # 同目录 hardlink 是原子且 exclusive 的发布：目标已存在时失败，因而新复盘
        # 不能覆盖仍在健康观察期的旧 marker。unlink 临时名不影响 marker 内容。
        os.link(temp, MARKER_FILE)
        return True
    except OSError as exc:
        log(f"[llm] 写重启 marker 失败：{exc}")
        return False
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _remove_restart_marker(expected_commit: str, log=print) -> None:
    """只清理由本次 prepare 写入、且尚未成功更新 ref 的 marker。"""
    try:
        current = json.loads(MARKER_FILE.read_text(encoding="utf-8"))
        if current.get("review_commit") == expected_commit:
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
        stage: Path | None = None
        try:
            manifest_path = package / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            completed: list[tuple[Path, SandboxReviewResult | None]] = []

            if raw_pointer.is_file():
                raw = Path(raw_pointer.read_text(encoding="utf-8")[:4096].strip()).resolve()
                if not _is_owned_review_temp(raw, "sts2-review-sandbox-"):
                    raise OSError(f"不安全的 raw sandbox 指针：{raw}")
                target = package / "raw_sandbox"
                if not target.exists():
                    if not raw.is_dir():
                        raise OSError(f"raw sandbox 已不存在：{raw}")
                    stage = package / ".raw_sandbox.tmp"
                    shutil.copytree(
                        raw, stage, dirs_exist_ok=True, symlinks=True,
                        ignore_dangling_symlinks=True,
                        copy_function=_copy_snapshot_file)
                    stage.replace(target)
                    stage = None
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
                if not target.exists():
                    if not snapshot.is_dir():
                        raise OSError(f"snapshot 已不存在：{snapshot}")
                    stage = package / ".captured_snapshot.tmp"
                    shutil.copytree(
                        snapshot, stage, dirs_exist_ok=True, symlinks=True,
                        ignore_dangling_symlinks=True,
                        copy_function=_copy_snapshot_file)
                    stage.replace(target)
                    stage = None
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
            os.replace(manifest_temp, manifest_path)
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
            log(f"[llm] 已异步补全停止复盘的完整失败现场：{package}")
        except Exception as exc:
            log(f"[llm] 延迟补全失败复盘现场异常；保留指针供下次重试：{exc}")
            if (stage is not None and stage.is_dir()
                    and not _review_stop_requested()):
                try:
                    shutil.rmtree(stage)
                except OSError:
                    pass


def _finalize_review_batch(batch: list[dict], outcome: str, log=print) -> float:
    """原子消费成功批次或把失败批次放回队尾；返回失败退避秒数。"""
    runs = tuple(item.get("run") for item in batch)
    with _queue_lock:
        q = _load_queue_unlocked()
        current_runs = tuple((q.get("reviewing") or {}).get("runs") or [])
        if current_runs != runs:
            log("[llm] 复盘队列批次身份已变化，保留现有队列而不覆盖")
            return 0.0
        if outcome in {"completed", "changed"}:
            q["reviewing"] = None
            _save_queue_unlocked(q)
            return 0.0
        if outcome != "failed":
            return 0.0

        # 新入队的局先处理，失败批次退到队尾；只保留稳定 run/time，下一次重新
        # 解析模型计划，从而尊重 preferred 冷却与恢复探测。批次永不因队列上限丢弃。
        pending = list(q.get("pending", []))
        seen = {item.get("run") for item in pending}
        delays: list[float] = []
        for item in batch:
            if item.get("run") not in seen:
                retry_count = int(item.get("retry_count", 0)) + 1
                delay = min(_REVIEW_RETRY_MAX_SECONDS,
                            _REVIEW_RETRY_BASE_SECONDS
                            * (2 ** min(retry_count - 1, 20)))
                pending.append({
                    "run": item.get("run"),
                    "time": item.get("time", ""),
                    "retry_count": retry_count,
                    "retry_after": time.time() + delay,
                })
                seen.add(item.get("run"))
                delays.append(float(delay))
        q["pending"] = pending
        q["reviewing"] = None
        _save_queue_unlocked(q)
    return min(delays, default=0.0)


def _worker_loop(agent, log) -> None:
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
    # Startup recovery is itself a durable queue transaction.  If the file is
    # temporarily locked/unreadable, retry in place rather than letting the daemon
    # thread die (or treating the interrupted batch as empty).
    while not _review_stop_requested():
        try:
            with _queue_lock:
                q = _load_queue_unlocked()
                if q.get("reviewing"):
                    lost_runs = list((q["reviewing"] or {}).get("runs") or [])
                    if lost_runs:
                        log(f"[llm] 上场复盘随进程中断，重新入队追及：第 {lost_runs} 局")
                        requeued = [{"run": r, "time": (q["reviewing"] or {}).get("started", "")}
                                    for r in lost_runs]
                        seen = {p.get("run") for p in requeued}
                        pending = [p for p in q.get("pending", []) if p.get("run") not in seen]
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

    while not _review_stop_requested():
        try:
            # request_restart 已置位 = 本进程已判定待重启（局间 sys.exit(42)）。
            # 此时严禁再开新复盘：开跑即随进程死亡被孤儿化，覆盖的对局丢失
            # （复盘 C 局中完成置位 → worker 又开跑 A → 局末退场掐断 A，实证路径）。
            if getattr(agent, "request_restart", False):
                return
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
                                        if float(item.get("retry_after", 0) or 0) <= now][:cap]
                    if eligible_indexes:
                        picked = set(eligible_indexes)
                        batch = [pending[index] for index in eligible_indexes]
                        q["pending"] = [item for index, item in enumerate(pending)
                                        if index not in picked]
                        q["reviewing"] = {"runs": [p["run"] for p in batch],
                                          "started": time.strftime("%Y-%m-%d %H:%M:%S")}
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
                if outcome == "failed":
                    log(f"[llm] 复盘失败批次已放回队尾，{delay:.0f}s 后继续追及")
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
    runs_list = [p["run"] for p in batch]
    log(f"[llm] 异步复盘启动：覆盖第 {runs_list} 局（模型 {model}）")
    status: dict = {}
    executed = run_review(agent.know, log=log, model=model, every=every, source=source,
                          batch_runs=runs_list, async_mode=True, _status=status)
    outcome = status.get("outcome", "changed" if executed else "failed")
    if outcome == "canceled" or status.get("canceled"):
        return "canceled"
    if outcome == "changed" or executed:
        log("[llm] 异步复盘产生变更，本局结束后自动重启大脑加载…")
        agent.request_restart = True
        return "changed"
    if outcome == "completed":
        return "completed"
    log(f"[llm] 异步复盘未成功，将自动重试：{status.get('reason', '未知原因')}")
    return "failed"


def main() -> None:
    if "--requeue" in sys.argv:
        session_file = BASE_DIR / ".runtime" / "session.json"
        try:
            session = json.loads(session_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            session = {}
        if session.get("state") in {"starting", "running", "foreground"}:
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
        print("用法: py brain/llm_review.py --now | --requeue 562,566,567")
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
