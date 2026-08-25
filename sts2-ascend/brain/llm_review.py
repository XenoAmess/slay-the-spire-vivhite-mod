"""LLM 元复盘 —— 异步追及队列：游玩不等待，复盘在后台串行消化。

模型策略（见 config.json 的 llm 节）：
  - 优先模型 preferred_model（默认 openrouter/stealth/ox-alpha，即 Ox Alpha Free）：
    每局结束后探测 `opencode models`，在清单里且无失败冷却 → 每局复盘一次。
  - 回退模型 model（默认 kimi-for-coding/k3）：优先模型不可用 → 每 review_every_runs 局复盘。
  - 失败冷却：优先模型复盘执行失败（非零退出/超时/异常）则冷却 preferred_failure_cooldown_min
    分钟，期间直接回退，避免每局白等一个超时。

异步架构（2026-08-22 起）：
  - agent.py 每局 finalize 后调用 enqueue_review()：只把请求写入 knowledge/review_queue.json
    并确保工作线程存活，主循环立即开下一局，**零等待**。
  - 工作线程 _worker_loop 串行消化队列：一局结束若上一场复盘未完，请求在队列累积，
    下一场复盘一次性分析多局（追及队列）。
  - 并发安全：autogit 全局 git 锁；复盘激活期间对局存档只提交 knowledge/（不卷入半成品代码）；
    自检失败用路径级回滚（restore_paths），不会抹掉复盘期间产生的对局存档。
  - 复盘完成若产生变更：标记 request_restart，主循环在下一局间安全点以退出码 42 自重启加载。

设计要点（继承）：
  - 不直接调模型裸 API；spawn `opencode run` 无头会话——带完整工具链的智能体，走本机 OpenCode 授权。
  - 广权限 + git 安全网：可改 sts2-ascend/ 下任何文件；改前备份、改后自检、失败回滚。
  - 复盘过程经 review_live.stream 直播给 review_viewer.py 悬浮窗。

手动触发 `py brain/llm_review.py --now`（同步执行，用于人工调试）。
任何异常只记日志，绝不中断游玩主循环。
"""
from __future__ import annotations

import json
import os
import py_compile
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from lifecycle import stop_requested

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
REVIEW_MUTABLE_PATHS = [
    "sts2-ascend/brain", "sts2-ascend/scripts",
    "sts2-ascend/knowledge/policy.json", "sts2-ascend/knowledge/stats.json",
    "sts2-ascend/knowledge/lessons.md", "sts2-ascend/knowledge/meta_review.md",
]
_worker_stop = threading.Event()


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
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("llm", {})
        except json.JSONDecodeError:
            pass
    merged = {
        "enabled": True,
        "runner": "opencode",
        "opencode_bin": "opencode",
        "model": "kimi-for-coding/k3",
        "review_every_runs": 5,
        "timeout_min": 25,
        "max_runs_in_packet": 10,
        # 优先模型链（按优先级；条目形如 provider/model[@variant]）：
        # 1) Ox Alpha Free (Unlimited) · OpenCode Zen · max —— 若在 opencode models 清单则用
        # 2) Ox Alpha · OpenRouter · max（stealth 马甲，当前可见条目）
        "preferred_models": [
            "opencode/ox-alpha@max",
            "openrouter/stealth/ox-alpha@max",
        ],
        "preferred_every_runs": 1,
        # 失败冷却：超时/硬失败统一 5 分钟（短冷却，别让模型长期缺席复盘）
        "preferred_timeout_cooldown_min": 5,
        "preferred_failure_cooldown_min": 5,
        # 异步复盘不阻塞游玩，优先模型的超时可放宽
        "preferred_timeout_min": 40,
        "models_probe_timeout_sec": 60,
        # 复盘直播悬浮窗（review_viewer.py）
        "viewer_enabled": True,
        # 语音朗读器（tts/）：hybrid=SAPI实时直播+克隆音色读结论(默认) / nano=全克隆音色(滞后大) /
        # sapi=纯系统语音 / off=关闭
        "tts_mode": "hybrid",
        # 异步复盘队列：最多累积多少批待消化（超出丢弃最旧的）
        "review_queue_max": 5,
    }
    merged.update({k: v for k, v in cfg.items() if v is not None})
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
    return {
        "global": g,
        "progression": know.progression,
        "cards": cards,
        "enemies": enemies,
        "events": know.stats["events"],
        "policy": know.policy,
    }


def _recent_run_summaries(n: int) -> list[dict]:
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
    files = []
    for p in sorted(run_dir.glob("*.json"), key=lambda p: p.name):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if d.get("in_progress"):
            trail = d.get("decisions") or []
            if not any(isinstance(x, dict) and x.get("screen") == "GAME_OVER"
                       for x in trail):
                continue
        files.append((p, d))
    out = []
    for f, d in files[-n:]:
        decisions = d.get("decisions", [])
        # 脏戳字段的读端复原（第 369 局复盘）：被回写的文件顶层 floor=0/
        # victory=false 是脏值，决策轨迹才是真账——层数取轨迹最大值，
        # 胜负按 GAME_OVER 屏结算文案复原；干净文件两段逻辑零改动。
        floor = int(d.get("floor") or 0)
        trail_max = max((int(x.get("floor") or 0) for x in decisions
                         if isinstance(x, dict)), default=0)
        if trail_max > floor:
            floor = trail_max
        victory = bool(d.get("victory"))
        if not victory and any(isinstance(x, dict) and x.get("screen") == "GAME_OVER"
                               and "胜利" in str(x.get("reason") or "")
                               for x in decisions):
            victory = True
        out.append({
            "run_id": d.get("run_id"), "victory": victory, "floor": floor,
            "ascension": d.get("ascension"), "decisions": len(decisions),
            "combat_notes": d.get("combat_notes", []),
            "key_reasons": [x.get("reason", "") for x in decisions
                            if x.get("action") in ("choose_map_node", "choose_event_option",
                                                   "choose_rest_option", "skip_reward_cards")][-10:],
        })
    return out


def build_prompt(know, cfg: dict, every: int | None = None,
                 batch_runs: list[int] | None = None) -> str:
    n = int(cfg.get("max_runs_in_packet", 10))
    packet = {
        "runs_summary": _recent_run_summaries(n),
        "stats_digest": _stats_digest(know),
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

    return f"""你是「sts2-ascend」杀戮尖塔2自主学习智能体的总教练。{scope}。
智能体本体：启发式决策引擎（brain/policy.py，参数在 knowledge/policy.json）+ 统计学习（knowledge/stats.json），反复游玩战士 Ironclad。

# 数据摘要（已内嵌，完整文件可按需深读）
```json
{json.dumps(packet, ensure_ascii=False, indent=1)}
```

最近的 lessons.md 尾部：
```
{lessons_tail}
```

# 你的任务（严格按顺序）
1. 归因分析：主要死因趋势、打法缺陷、卡组构建问题、地图路线问题、代码缺陷。
2. 将复盘报告**追加写入** `sts2-ascend/knowledge/meta_review.md`（新建一节，标题含日期时间）：
   归因分析、你做出的每项调整及理由、新沉淀的经验知识（中文）。
3. **你可以修改 `sts2-ascend/` 下的任何文件**（策略参数、统计数据结构、决策代码、配置……）：
   - 改代码逻辑/数据结构比调参数更有价值——参数调不了的病就从代码治
   - 若修改 `knowledge/*.json` 的结构，**必须同步修改 `brain/knowledge.py` 并迁移现有数据**（保持兼容）
   - 新经验同时追加到 `sts2-ascend/knowledge/lessons.md`（一节，标题以 🧠 开头）
4. 改完任何 `.py` 后**必须**运行 `py -3 sts2-ascend/brain/selfcheck.py` 并确认输出 SELFCHECK OK；
   若不通过，修好再试，实在修不好就把该文件改回原样。
5. 不要提交：git 提交由宿主大脑在复盘前后自动完成（复盘前已备份，复盘后变更会被提交；
   若你的变更导致自检失败，会被整体回滚到备份点）。
6. **额外产出一段点评短评**：把它**写入** `sts2-ascend/knowledge/review_conclusion.txt`
   （纯文本、单行、一两句话点评这几局的表现+一个最关键的改进点，**100 字以内**）。
   这段文字会被克隆音色朗读出来，所以要口语化、适合听。

# 禁止事项（最高优先级，覆盖仓库 AGENTS.md 的默认规则）
- 禁止任何 git 操作（add/commit/push/reset 等，宿主大脑统一管理）
- 禁止停止/启动任何进程（游戏和大脑正在运行）
- 禁止修改 `sts2-ascend/` 之外的任何文件（Vivhite mod、游戏本体、系统文件……）
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
    """'openrouter/stealth/ox-alpha@max' → ('openrouter/stealth/ox-alpha', 'max')。"""
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
    """拉起直播悬浮窗（独立进程，它的死活绝不影响复盘）。"""
    if _review_stop_requested() or not cfg.get("viewer_enabled", True) or not VIEWER_PATH.exists():
        return
    try:
        creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        # stderr 落盘：viewer 崩溃 traceback 必须可尸检（此前 DEVNULL 吞掉，
        # 悬浮窗反复消失却无迹可寻）
        err_f = open(KNOWLEDGE_DIR / "viewer_err.log", "ab")
        out_f = open(KNOWLEDGE_DIR / "viewer_out.log", "ab")
        subprocess.Popen([sys.executable, "-u", str(VIEWER_PATH)],
                         cwd=str(BASE_DIR), stdin=subprocess.DEVNULL,
                         stdout=out_f, stderr=err_f,
                         creationflags=creationflags, close_fds=False)
        log("[llm] 直播悬浮窗已拉起")
    except Exception as exc:
        log(f"[llm] 直播悬浮窗拉起失败（不影响复盘）：{exc}")


def _launch_speaker(cfg: dict, log) -> None:
    """拉起语音朗读器。tts_mode: edge=edge-tts统一嗓音(默认,云端零算力) / nano=全克隆音色 /
    hybrid=SAPI直播+克隆结论 / sapi=纯系统语音 / off=关闭。独立进程，死活不影响复盘。"""
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
        self._seen: dict[str, int] = {}

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
        pid = str(part.get("id") or "")
        if ptype in ("text", "reasoning"):
            text = part.get("text") or ""
            prev = self._seen.get(pid, 0)
            if len(text) <= prev:
                return []
            self._seen[pid] = len(text)
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


def _stream_run(cmd: list[str], timeout_sec: int,
                translate=None) -> tuple[int, str, bool, bool]:
    """流式执行命令：stdout/stderr 合并逐行实时写入 LIVE_STREAM，同时收集全文。

    translate（可选）：把每个原始输出行映射为 0~N 个展示行（如 OpencodeJsonTranslator.feed）。
    返回 (returncode, 全文输出, 是否超时, 是否被全栈停机中断)。
    """
    env = dict(os.environ)
    env["NO_COLOR"] = "1"      # 关掉 ANSI 颜色，viewer 自己上色
    env["TERM"] = "dumb"
    proc = subprocess.Popen(
        cmd, cwd=str(REPO_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, env=env)

    q: queue.Queue[str | None] = queue.Queue()

    def _reader() -> None:
        try:
            for ln in proc.stdout or []:
                q.put(ln)
        finally:
            q.put(None)

    threading.Thread(target=_reader, daemon=True).start()

    deadline = time.monotonic() + timeout_sec
    lines: list[str] = []
    timed_out = False
    stopped = False
    with LIVE_STREAM.open("a", encoding="utf-8") as stream:
        while True:
            try:
                ln = q.get(timeout=0.2)
            except queue.Empty:
                ln = ""
            if ln is None:
                break
            if ln:
                out_lines = translate(ln) if translate else [ln]
                for ol in out_lines:
                    if not ol.endswith("\n"):
                        ol += "\n"
                    lines.append(ol)
                    try:
                        stream.write(ol)
                        stream.flush()
                    except OSError:
                        pass
            if _review_stop_requested():
                stopped = True
                try:
                    proc.terminate()
                except OSError:
                    pass
                break
            if time.monotonic() > deadline:
                timed_out = True
                try:
                    proc.kill()
                except OSError:
                    pass
                break
    if _review_stop_requested():
        stopped = True
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    except OSError:
        pass
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, "".join(lines), timed_out, stopped


# ---------------------------------------------------------------------------
# review execution
# ---------------------------------------------------------------------------

def _run_selfcheck(log) -> bool:
    """py_compile 全文件 + 冒烟测试（含真实知识库加载）。"""
    brain_dir = BASE_DIR / "brain"
    for f in brain_dir.glob("*.py"):
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as exc:
            log(f"[llm] 自检失败（编译 {f.name}）：{exc}")
            return False
    try:
        proc = subprocess.run([sys.executable, str(brain_dir / "selfcheck.py")],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if proc.returncode != 0 or "SELFCHECK OK" not in (proc.stdout or ""):
            log(f"[llm] 自检失败（冒烟）：{(proc.stdout or '')[-400:]} {(proc.stderr or '')[-400:]}")
            return False
    except Exception as exc:
        log(f"[llm] 自检异常：{exc}")
        return False
    return True


def run_review(know, log=print, model: str | None = None, every: int | None = None,
               source: str = "fallback", batch_runs: list[int] | None = None,
               async_mode: bool = False, _status: dict | None = None) -> bool:
    """执行一次大模型复盘。返回 True 表示复盘产生了已提交的变更（调用方应重启大脑）。

    流程：改前 commit 备份 → opencode 广权限复盘 → 自检 → 通过则提交/请求重启，失败则 git 回滚。
    source="preferred" 时若执行失败（非零退出/超时/异常）会对优先模型记失败冷却。
    async_mode=True（异步队列工作线程调用）时：
      - 复盘期间 autogit 对局存档只提交 knowledge/（不卷入半成品代码）
      - 自检失败的回滚是路径级的（restore_paths），不会抹掉复盘期间产生的对局存档
    """
    if _status is not None:
        _status["canceled"] = False
    if _review_stop_requested():
        if _status is not None:
            _status["canceled"] = True
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
    batch_txt = f"第{batch_runs[0]}~{batch_runs[-1]}局" if batch_runs and len(batch_runs) > 1 \
        else f"第{batch_runs[0]}局" if batch_runs else f"第{runs}局"
    # 1) 改前备份：把当前知识库+代码先提交推送（此时复盘未激活，全量提交）
    autogit.commit_progress(f"chore(sts2-ascend): {batch_txt}后复盘前备份", log=log)
    pre_head = autogit.head()

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
    short_prompt = (f"请立即用读文件工具完整阅读 {rel_prompt}（本场复盘的完整任务书已写好），"
                    f"并严格按其中全部指示执行。")

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
            _status["canceled"] = True
        log("[llm] 备份完成时收到停止请求，取消本次复盘")
        return False

    # 直播流开启 + 拉起悬浮窗/语音朗读器（哨兵/meta 先行）
    _stream_begin({"model": entry, "source": source, "run": runs, "time": stamp})
    _launch_viewer(cfg, log)
    _launch_speaker(cfg, log)

    autogit.set_review_active(True)     # 此后对局存档只提交 knowledge/
    rc, out, timed_out, stopped = -1, "", False, False
    eff_timeout_min = float(cfg.get("preferred_timeout_min", 40)) if source == "preferred" \
        else float(cfg.get("timeout_min", 25))
    translator = OpencodeJsonTranslator()
    try:
        rc, out, timed_out, stopped = _stream_run(
            cmd, int(eff_timeout_min * 60), translate=translator.feed)
        log(f"[llm] 复盘会话结束（exit={rc}）。输出尾部：\n{out[-2000:]}")
        if stopped:
            if _status is not None:
                _status["canceled"] = True
            # 停机路径不执行 git restore/commit/push：保留原子落盘的实时记忆，
            # 也避免把并发用户改动卷入额外的版本控制副作用。
            autogit.set_review_active(False)
            retry_note = "批次下次启动重试" if async_mode else "手动复盘已取消"
            log(f"[llm] 整套停止已取消复盘；不执行停机期代码回滚，"
                f"实时记忆保留，{retry_note}（复盘前备份点 {pre_head[:8]}）")
            return False
        if timed_out:
            log(f"[llm] 复盘超时（{eff_timeout_min:.0f} 分钟），本次作废")
            if source == "preferred":
                _mark_preferred_failure(cfg, log, entry, "timeout", kind="timeout")
            return False
        if rc != 0:
            if source == "preferred":
                _mark_preferred_failure(cfg, log, entry, f"exit={rc}")
            return False
        if source == "preferred":
            _mark_preferred_ok(entry)
        # 复盘会话成功（不论是否产生文件变更）——刷新成功标记，兜底守卫以此为准
        know.progression["last_successful_review_run"] = runs
        try:
            know.save()
        except OSError:
            pass
    except Exception as exc:
        # 启动期异常（如 WinError 206 命令行过长）属本地环境问题，非模型故障，不记冷却
        log(f"[llm] 复盘调用失败（已忽略，不影响游玩）：{exc}")
        return False
    finally:
        _stream_end({"exit": rc, "timeout": timed_out, "stopped": stopped})
        if stopped or timed_out or rc != 0:
            # 失败/超时/异常路径在上方提前 return，走不到后处理段的
            # set_review_active(False)——flag 陈旧会永久卡住 autogit 宽窄判断
            # （一日内三次实证）。成功路径保持 True 到后处理结束。
            autogit.set_review_active(False)

    try:
        # 2) 无变更则无需提交/重启
        if not autogit.has_changes():
            log("[llm] 复盘未产生任何文件变更，跳过提交")
            return False

        # 3) 自检：编译 + 冒烟（含真实知识库结构兼容校验）
        if not _run_selfcheck(log):
            log("[llm] 复盘变更未通过自检，执行 git 回滚")
            try:
                backup = KNOWLEDGE_DIR / "code_backups" / f"failed_review_{time.strftime('%Y%m%d-%H%M%S')}.md"
                backup.parent.mkdir(parents=True, exist_ok=True)
                if REVIEW_LOG.exists():
                    shutil.copy2(REVIEW_LOG, backup)
            except OSError:
                pass
            autogit.set_review_active(False)    # 回滚提交需要 brain/ 全量范围
            if async_mode:
                # 路径级回滚：只还原复盘可触碰的路径，保留复盘期间的对局存档
                autogit.restore_paths(pre_head, REVIEW_MUTABLE_PATHS, log=log)
                autogit.commit_progress(
                    f"revert(sts2-ascend): {batch_txt}复盘未过自检，路径回滚到 {pre_head[:8]}", log=log)
            else:
                autogit.reset_hard(pre_head, log=log)
            log(f"[llm] 已回滚到复盘前备份点 {pre_head[:8]}（本次变更废弃，报告副本在 code_backups）")
            return False

        # 4) 提交复盘变更（先解锁收窄标记，复盘自身的提交必须是全量范围）
        autogit.set_review_active(False)
        autogit.commit_progress(f"feat(sts2-ascend): {batch_txt} LLM 复盘变更（详见 knowledge/meta_review.md）", log=log)

        # 5) 写重启标记并请求重启（runner 若发现新代码起不来，会按 marker 回滚到 pre_head）
        try:
            MARKER_FILE.write_text(json.dumps({"pre_head": pre_head, "time": stamp}), encoding="utf-8")
        except OSError:
            pass
        log("[llm] 复盘变更已提交，重启大脑以加载…")
        return True
    finally:
        autogit.set_review_active(False)


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


def _load_queue_unlocked() -> dict:
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"pending": [], "reviewing": None}


def _save_queue_unlocked(q: dict) -> None:
    temp = QUEUE_FILE.with_name(
        f".{QUEUE_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temp.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, QUEUE_FILE)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _load_queue() -> dict:
    with _queue_lock:
        return _load_queue_unlocked()


def _save_queue(q: dict) -> None:
    with _queue_lock:
        _save_queue_unlocked(q)


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
    # 守卫强制 k3 → k3 失败 → 永无成功 → 永远强制 k3，ox-alpha 复活也
    # 没机会被探测（第 267~366 局实证：100 局零成功，last_llm_review_run 冻结在 266）。
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
        agent.know.progression["last_fallback_review_run"] = runs
    else:
        last = agent.know.progression.get("last_llm_review_run", 0)
        if runs - last < every:
            return
        agent.know.progression["last_llm_review_run"] = runs
    agent.know.progression["last_review_attempt_source"] = source
    agent.know.save()
    with _queue_lock:
        q = _load_queue_unlocked()
        q.setdefault("pending", []).append({
            "run": runs, "time": time.strftime("%Y-%m-%d %H:%M"),
            "model": model, "every": every, "source": source,
        })
        q["pending"] = q["pending"][-max(1, int(cfg.get("review_queue_max", 10))):]
        _save_queue_unlocked(q)
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
    with _queue_lock:
        q = _load_queue_unlocked()
        has_work = bool(q.get("pending") or q.get("reviewing"))
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


def _worker_loop(agent, log) -> None:
    # 进程重启后：先清孤儿（避免与重跑的复盘双写），再把 reviewing 的对局
    # 重新入队——此前直接丢弃标记，被中断复盘覆盖的对局永远丢失复盘。
    if _review_stop_requested():
        return
    _kill_orphan_review_processes(log)
    if _review_stop_requested():
        return
    with _queue_lock:
        q = _load_queue_unlocked()
        if q.get("reviewing"):
            lost_runs = list((q["reviewing"] or {}).get("runs") or [])
            if lost_runs:
                log(f"[llm] 上场复盘随进程中断，重新入队追及：第 {lost_runs} 局")
                cap = max(1, int(load_llm_config().get("review_queue_max", 10)))
                requeued = [{"run": r, "time": (q["reviewing"] or {}).get("started", "")}
                            for r in lost_runs]
                # Interrupted runs are never discarded when the queue is full.
                seen = {p.get("run") for p in requeued}
                pending = [p for p in q.get("pending", []) if p.get("run") not in seen]
                slots = max(0, cap - len(requeued))
                q["pending"] = (requeued[:cap] + (pending[-slots:] if slots else []))
            q["reviewing"] = None
            _save_queue_unlocked(q)
    while not _review_stop_requested():
        try:
            # request_restart 已置位 = 本进程已判定待重启（局间 sys.exit(42)）。
            # 此时严禁再开新复盘：开跑即随进程死亡被孤儿化，覆盖的对局丢失
            # （复盘 C 局中完成置位 → worker 又开跑 A → 局末退场掐断 A，实证路径）。
            if getattr(agent, "request_restart", False):
                return
            with _queue_lock:
                q = _load_queue_unlocked()
                pending = q.get("pending", [])
                if pending and not q.get("reviewing"):
                    batch = list(pending)
                    q["pending"] = []
                    q["reviewing"] = {"runs": [p["run"] for p in batch],
                                      "started": time.strftime("%Y-%m-%d %H:%M:%S")}
                    _save_queue_unlocked(q)
                else:
                    batch = []
            if batch:
                outcome = "running"
                try:
                    outcome = _run_batch_review(agent, batch, log)
                finally:
                    # Only a genuinely canceled batch remains reviewing for recovery.
                    canceled = outcome == "canceled" or (
                        outcome == "running" and _review_stop_requested())
                    if not canceled:
                        with _queue_lock:
                            q = _load_queue_unlocked()
                            q["reviewing"] = None
                            _save_queue_unlocked(q)
                if outcome == "canceled":
                    return
            if _wait_review_stop(5):
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
    if status.get("canceled"):
        return "canceled"
    if executed:
        log("[llm] 异步复盘产生变更，本局结束后自动重启大脑加载…")
        agent.request_restart = True
    return "completed"


def main() -> None:
    if "--now" not in sys.argv:
        print("用法: py brain/llm_review.py --now   # 立即对当前知识库做一次大模型复盘")
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
