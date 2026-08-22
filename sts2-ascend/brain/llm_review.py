"""LLM 元复盘 —— 每 N 局调用 OpenCode（kimi-for-coding/k3）做一次教练级复盘。

设计要点：
  - 不直接调模型裸 API（裸 API 只能输出文本，没法真正改代码）；
    而是 spawn `opencode run` 无头会话——带完整工具链的智能体，走本机 OpenCode 授权。
  - **广权限 + git 安全网**：复盘 agent 可改 sts2-ascend/ 下任何文件（代码/数据结构/配置）。
    改前宿主大脑自动 commit 备份；改后自检（编译+冒烟+真实知识库兼容），通过才提交，
    失败则 `git reset --hard` 回滚到备份点；重启后若新代码起不来，runner 按标记再回滚一次。
  - 复盘完成后大脑以退出码 42 请求 runner 重启，加载新策略/新代码。

触发：agent.py 每局 finalize 后调用 maybe_review()；手动触发 `py brain/llm_review.py --now`。
任何异常只记日志，绝不中断游玩主循环。
"""
from __future__ import annotations

import json
import os
import py_compile
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # sts2-ascend/
REPO_DIR = BASE_DIR.parent                                  # git 仓库根（opencode 在此获得完整上下文）
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
CONFIG_PATH = BASE_DIR / "brain" / "config.json"
PROMPT_FILE = KNOWLEDGE_DIR / "review_prompt_latest.md"
REVIEW_LOG = KNOWLEDGE_DIR / "meta_review.md"
MARKER_FILE = KNOWLEDGE_DIR / "pending_restart.json"


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


def build_prompt(know, cfg: dict) -> str:
    n = int(cfg.get("max_runs_in_packet", 10))
    packet = {
        "runs_summary": _recent_run_summaries(n),
        "stats_digest": _stats_digest(know),
    }
    lessons_tail = ""
    lessons_path = KNOWLEDGE_DIR / "lessons.md"
    if lessons_path.exists():
        lessons_tail = lessons_path.read_text(encoding="utf-8")[-2500:]

    return f"""你是「sts2-ascend」杀戮尖塔2自主学习智能体的总教练。每 {cfg.get('review_every_runs', 10)} 局你做一次大模型复盘。
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


def run_review(know, log=print) -> bool:
    """执行一次大模型复盘。返回 True 表示复盘产生了已提交的变更（调用方应重启大脑）。

    流程：改前 commit 备份 → opencode 广权限复盘 → 自检 → 通过则提交/请求重启，失败则 git 回滚。
    """
    cfg = load_llm_config()
    if not cfg.get("enabled"):
        log("[llm] 复盘已禁用（llm.enabled=false）")
        return False
    binary = shutil.which(cfg.get("opencode_bin", "opencode"))
    if not binary:
        log(f"[llm] 未找到 opencode 可执行文件（{cfg.get('opencode_bin')}），跳过本次复盘")
        return False

    import autogit  # 延迟导入，避免 standalone 运行时的循环依赖

    runs = know.stats["global"]["runs"]
    # 1) 改前备份：把当前知识库+代码先提交推送
    autogit.commit_progress(f"chore(sts2-ascend): 第{runs}局后复盘前备份", log=log)
    pre_head = autogit.head()

    stamp = time.strftime("%Y-%m-%d %H:%M")
    log(f"[llm] ===== 启动大模型复盘（{cfg['model']} via opencode，备份点 {pre_head[:8]}）=====")
    prompt = build_prompt(know, cfg)
    try:
        PROMPT_FILE.write_text(prompt, encoding="utf-8")
    except OSError:
        pass

    cmd = [
        binary, "run",
        "--model", cfg["model"],
        "--title", f"sts2-ascend 复盘 {stamp}",
        "--dir", str(REPO_DIR),
        "--auto",
        prompt,
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_DIR), capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=int(cfg.get("timeout_min", 25)) * 60)
        log(f"[llm] 复盘会话结束（exit={proc.returncode}）。输出尾部：\n{(proc.stdout or '')[-2000:]}")
        if proc.returncode != 0:
            log(f"[llm] stderr 尾部：{(proc.stderr or '')[-800:]}")
            return False
    except subprocess.TimeoutExpired:
        log(f"[llm] 复盘超时（{cfg.get('timeout_min')} 分钟），本次作废")
        return False
    except Exception as exc:
        log(f"[llm] 复盘调用失败（已忽略，不影响游玩）：{exc}")
        return False

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
        autogit.reset_hard(pre_head, log=log)
        log(f"[llm] 已回滚到复盘前备份点 {pre_head[:8]}（本次变更废弃，报告副本在 code_backups）")
        return False

    # 4) 提交复盘变更
    autogit.commit_progress(f"feat(sts2-ascend): 第{runs}局后 LLM 复盘变更（详见 knowledge/meta_review.md）", log=log)

    # 5) 写重启标记并请求重启（runner 若发现新代码起不来，会按 marker 回滚到 pre_head）
    try:
        MARKER_FILE.write_text(json.dumps({"pre_head": pre_head, "time": stamp}), encoding="utf-8")
    except OSError:
        pass
    log("[llm] 复盘变更已提交，重启大脑以加载…")
    return True


def maybe_review(agent, log=print) -> None:
    """agent.py 每局结束后调用。到局数就复盘；复盘执行过则在主菜单安全点自重启。"""
    cfg = load_llm_config()
    every = max(1, int(cfg.get("review_every_runs", 10)))
    runs = agent.know.stats["global"]["runs"]
    last = agent.know.progression.get("last_llm_review_run", 0)
    if runs - last < every:
        return
    executed = run_review(agent.know, log=log)
    agent.know.progression["last_llm_review_run"] = runs
    agent.know.save()
    if executed:
        log("[llm] 复盘完成，回到主菜单后自动重启大脑以加载新策略/代码…")
        agent.request_restart = True


def main() -> None:
    if "--now" not in sys.argv:
        print("用法: py brain/llm_review.py --now   # 立即对当前知识库做一次大模型复盘")
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from knowledge import Knowledge
    know = Knowledge(KNOWLEDGE_DIR)
    executed = run_review(know)
    print(f"done, executed={executed}")


if __name__ == "__main__":
    main()
