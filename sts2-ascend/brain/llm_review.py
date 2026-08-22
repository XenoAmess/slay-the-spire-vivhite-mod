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
        "review_every_runs": 10,
        "timeout_min": 25,
        "max_runs_in_packet": 10,
        # Ox Alpha Free（openrouter/stealth/ox-alpha）：可用时每局复盘
        "preferred_model": "openrouter/stealth/ox-alpha",
        "preferred_every_runs": 1,
        "preferred_failure_cooldown_min": 360,
        "models_probe_timeout_sec": 60,
        # 复盘直播悬浮窗（review_viewer.py）
        "viewer_enabled": True,
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
    files = sorted(run_dir.glob("*.json"), key=lambda p: p.name)[-n:]
    out = []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        decisions = d.get("decisions", [])
        out.append({
            "run_id": d.get("run_id"), "victory": d.get("victory"), "floor": d.get("floor"),
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


def _preferred_cooldown_remaining() -> float:
    """优先模型失败冷却剩余秒数（0 表示未在冷却中）。"""
    until = float(_load_preferred_state().get("unavailable_until", 0) or 0)
    return max(0.0, until - time.time())


def _mark_preferred_failure(cfg: dict, log, reason: str) -> None:
    cooldown_min = float(cfg.get("preferred_failure_cooldown_min", 360))
    _save_preferred_state({
        "unavailable_until": time.time() + cooldown_min * 60,
        "last_failure": reason,
        "last_failure_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    log(f"[llm] 优先模型复盘失败（{reason}），{cooldown_min:.0f} 分钟内回退普通模型")


def _mark_preferred_ok() -> None:
    state = _load_preferred_state()
    if state.get("unavailable_until"):
        state["unavailable_until"] = 0
        _save_preferred_state(state)


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
    """决定本轮复盘的 (模型, 复盘间隔局数, 来源)。

    优先模型可用（在 `opencode models` 清单里且不在失败冷却期）→ 每局复盘；
    否则回退 cfg["model"] 按 review_every_runs 间隔复盘。
    """
    fallback = (cfg["model"], max(1, int(cfg.get("review_every_runs", 10))), "fallback")
    preferred = cfg.get("preferred_model")
    if not preferred or not binary:
        return fallback
    cooldown = _preferred_cooldown_remaining()
    if cooldown > 0:
        log(f"[llm] 优先模型 {preferred} 失败冷却中（剩余 {cooldown / 60:.0f} 分钟）")
        return fallback
    models = _query_available_models(binary, cfg, log)
    if models is None:
        return fallback
    if preferred in models:
        return preferred, max(1, int(cfg.get("preferred_every_runs", 1))), "preferred"
    log(f"[llm] 优先模型 {preferred} 不在可用清单，回退 {fallback[0]}（每 {fallback[1]} 局）")
    return fallback


# ---------------------------------------------------------------------------
# 直播流：把复盘会话的 stdout 实时写到 review_live.stream，并拉起悬浮窗
# ---------------------------------------------------------------------------

def _launch_viewer(cfg: dict, log) -> None:
    """拉起直播悬浮窗（独立进程，它的死活绝不影响复盘）。"""
    if not cfg.get("viewer_enabled", True) or not VIEWER_PATH.exists():
        return
    try:
        creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        subprocess.Popen([sys.executable, "-u", str(VIEWER_PATH)],
                         cwd=str(BASE_DIR), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=creationflags, close_fds=True)
        log("[llm] 直播悬浮窗已拉起")
    except Exception as exc:
        log(f"[llm] 直播悬浮窗拉起失败（不影响复盘）：{exc}")


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


def _stream_run(cmd: list[str], timeout_sec: int) -> tuple[int, str, bool]:
    """流式执行命令：stdout/stderr 合并逐行实时写入 LIVE_STREAM，同时收集全文。

    返回 (returncode, 全文输出, 是否超时)。超时则 kill 进程。
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
    with LIVE_STREAM.open("a", encoding="utf-8") as stream:
        while True:
            try:
                ln = q.get(timeout=0.2)
            except queue.Empty:
                ln = ""
            if ln is None:
                break
            if ln:
                lines.append(ln)
                try:
                    stream.write(ln)
                    stream.flush()
                except OSError:
                    pass
            if time.monotonic() > deadline:
                timed_out = True
                try:
                    proc.kill()
                except OSError:
                    pass
                break
    try:
        proc.wait(timeout=10)
    except Exception:
        pass
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, "".join(lines), timed_out


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
               async_mode: bool = False) -> bool:
    """执行一次大模型复盘。返回 True 表示复盘产生了已提交的变更（调用方应重启大脑）。

    流程：改前 commit 备份 → opencode 广权限复盘 → 自检 → 通过则提交/请求重启，失败则 git 回滚。
    source="preferred" 时若执行失败（非零退出/超时/异常）会对优先模型记失败冷却。
    async_mode=True（异步队列工作线程调用）时：
      - 复盘期间 autogit 对局存档只提交 knowledge/（不卷入半成品代码）
      - 自检失败的回滚是路径级的（restore_paths），不会抹掉复盘期间产生的对局存档
    """
    cfg = load_llm_config()
    if not cfg.get("enabled"):
        log("[llm] 复盘已禁用（llm.enabled=false）")
        return False
    binary = shutil.which(cfg.get("opencode_bin", "opencode"))
    if not binary:
        log(f"[llm] 未找到 opencode 可执行文件（{cfg.get('opencode_bin')}），跳过本次复盘")
        return False
    model = model or cfg["model"]

    import autogit  # 延迟导入，避免 standalone 运行时的循环依赖

    runs = know.stats["global"]["runs"]
    batch_txt = f"第{batch_runs[0]}~{batch_runs[-1]}局" if batch_runs and len(batch_runs) > 1 \
        else f"第{batch_runs[0]}局" if batch_runs else f"第{runs}局"
    # 1) 改前备份：把当前知识库+代码先提交推送（此时复盘未激活，全量提交）
    autogit.commit_progress(f"chore(sts2-ascend): {batch_txt}后复盘前备份", log=log)
    pre_head = autogit.head()

    stamp = time.strftime("%Y-%m-%d %H:%M")
    log(f"[llm] ===== 启动大模型复盘（{model} via opencode [{source}]，{batch_txt}，备份点 {pre_head[:8]}）=====")
    prompt = build_prompt(know, cfg, every, batch_runs)
    try:
        PROMPT_FILE.write_text(prompt, encoding="utf-8")
    except OSError:
        pass

    cmd = [
        binary, "run",
        "--model", model,
        "--title", f"sts2-ascend 复盘 {stamp}",
        "--dir", str(REPO_DIR),
        "--auto",
        prompt,
    ]

    # 直播流开启 + 拉起悬浮窗（哨兵/meta 先行，viewer 据此渲染标题）
    _stream_begin({"model": model, "source": source, "run": runs, "time": stamp})
    _launch_viewer(cfg, log)

    autogit.set_review_active(True)     # 此后对局存档只提交 knowledge/
    rc, out, timed_out = -1, "", False
    try:
        rc, out, timed_out = _stream_run(cmd, int(cfg.get("timeout_min", 25)) * 60)
        log(f"[llm] 复盘会话结束（exit={rc}）。输出尾部：\n{out[-2000:]}")
        if timed_out:
            log(f"[llm] 复盘超时（{cfg.get('timeout_min')} 分钟），本次作废")
            if source == "preferred":
                _mark_preferred_failure(cfg, log, "timeout")
            return False
        if rc != 0:
            if source == "preferred":
                _mark_preferred_failure(cfg, log, f"exit={rc}")
            return False
        if source == "preferred":
            _mark_preferred_ok()
    except Exception as exc:
        log(f"[llm] 复盘调用失败（已忽略，不影响游玩）：{exc}")
        if source == "preferred":
            _mark_preferred_failure(cfg, log, str(exc)[:120])
        return False
    finally:
        _stream_end({"exit": rc, "timeout": timed_out})

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
            if async_mode:
                # 路径级回滚：只还原复盘可触碰的路径，保留复盘期间的对局存档
                autogit.restore_paths(pre_head, [
                    "sts2-ascend/brain", "sts2-ascend/scripts",
                    "sts2-ascend/knowledge/policy.json", "sts2-ascend/knowledge/stats.json",
                    "sts2-ascend/knowledge/lessons.md", "sts2-ascend/knowledge/meta_review.md",
                ], log=log)
                autogit.commit_progress(
                    f"revert(sts2-ascend): {batch_txt}复盘未过自检，路径回滚到 {pre_head[:8]}", log=log)
            else:
                autogit.reset_hard(pre_head, log=log)
            log(f"[llm] 已回滚到复盘前备份点 {pre_head[:8]}（本次变更废弃，报告副本在 code_backups）")
            return False

        # 4) 提交复盘变更
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


def _load_queue() -> dict:
    try:
        return json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"pending": [], "reviewing": None}


def _save_queue(q: dict) -> None:
    try:
        QUEUE_FILE.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def enqueue_review(agent, log=print) -> None:
    """agent.py 每局结束后调用：按节奏入队复盘请求并确保工作线程存活。

    绝不阻塞游玩主循环——复盘由工作线程异步执行；若一局结束时上一场复盘还没完，
    请求在队列里累积，下一场复盘会一次性分析多局（追及）。
    """
    cfg = load_llm_config()
    if not cfg.get("enabled"):
        return
    runs = agent.know.stats["global"]["runs"]
    last = agent.know.progression.get("last_llm_review_run", 0)
    binary = shutil.which(cfg.get("opencode_bin", "opencode"))
    model, every, source = resolve_review_plan(cfg, binary, log=log)
    if runs - last < every:
        return
    agent.know.progression["last_llm_review_run"] = runs
    agent.know.save()
    q = _load_queue()
    q.setdefault("pending", []).append({"run": runs, "time": time.strftime("%Y-%m-%d %H:%M")})
    q["pending"] = q["pending"][-max(1, int(cfg.get("review_queue_max", 5))):]
    _save_queue(q)
    log(f"[llm] 复盘请求已入队（第{runs}局，待消化 {len(q['pending'])} 批），游玩不等待")
    _ensure_worker(agent, log)


def _ensure_worker(agent, log) -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
    threading.Thread(target=_worker_loop, args=(agent, log), daemon=True,
                     name="llm-review-worker").start()
    log("[llm] 异步复盘工作线程已启动")


def _worker_loop(agent, log) -> None:
    # 进程重启后清理残留的 reviewing 标记（上一场复盘子进程已随旧大脑消亡）
    q = _load_queue()
    if q.get("reviewing"):
        log("[llm] 清理残留的复盘标记（上次复盘随进程重启中断）")
        q["reviewing"] = None
        _save_queue(q)
    while True:
        try:
            q = _load_queue()
            pending = q.get("pending", [])
            if pending and not q.get("reviewing"):
                batch = list(pending)
                q["pending"] = []
                q["reviewing"] = {"runs": [p["run"] for p in batch],
                                  "started": time.strftime("%Y-%m-%d %H:%M:%S")}
                _save_queue(q)
                try:
                    _run_batch_review(agent, batch, log)
                finally:
                    q = _load_queue()
                    q["reviewing"] = None
                    _save_queue(q)
            time.sleep(5)
        except Exception as exc:
            log(f"[llm] 复盘工作线程异常（已忽略，30s 后继续）：{exc}")
            time.sleep(30)


def _run_batch_review(agent, batch: list[dict], log) -> None:
    cfg = load_llm_config()
    binary = shutil.which(cfg.get("opencode_bin", "opencode"))
    model, every, source = resolve_review_plan(cfg, binary, log=log)
    runs_list = [p["run"] for p in batch]
    log(f"[llm] 异步复盘启动：覆盖第 {runs_list} 局（模型 {model}）")
    executed = run_review(agent.know, log=log, model=model, every=every, source=source,
                          batch_runs=runs_list, async_mode=True)
    if executed:
        log("[llm] 异步复盘产生变更，本局结束后自动重启大脑加载…")
        agent.request_restart = True


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
    executed = run_review(know, model=model, every=every, source=source)
    print(f"done, executed={executed}")


if __name__ == "__main__":
    main()
