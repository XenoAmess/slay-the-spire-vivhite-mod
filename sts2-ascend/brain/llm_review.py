"""LLM 元复盘 —— 每 N 局调用 OpenCode（kimi-for-coding/k3）做一次教练级复盘。

设计要点：
  - 不直接调模型裸 API（裸 API 只能输出文本，没法真正改代码）；
    而是 spawn `opencode run` 无头会话——一个带完整工具链（读文件/改代码/跑编译）的智能体，
    走用户本机已有的 OpenCode 授权，无需额外 API key。
  - 复盘提示词内嵌紧凑数据摘要（控制 token），并给出文件路径供其按需深读。
  - 安全边界写在提示词里：只许动 knowledge/ 与 brain/policy.py，禁止 git/进程/删除操作。
  - 复盘完成后大脑在主菜单安全点自重启（os.execv），加载新策略/新代码。

触发：agent.py 每局 finalize 后调用 maybe_review()；手动触发 `py brain/llm_review.py --now`。
任何异常只记日志，绝不中断游玩主循环。
"""
from __future__ import annotations

import json
import os
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

# 你的任务（严格按顺序，禁止任何多余操作）
1. 归因分析：主要死因趋势、打法缺陷、卡组构建问题、地图路线问题。
2. 将复盘报告**追加写入** `sts2-ascend/knowledge/meta_review.md`（新建一节，标题含日期时间）：
   归因分析、你做出的每项调整及理由、新沉淀的经验知识（中文）。
3. 允许的直接修改（必须保守、逐项写入报告）：
   - `sts2-ascend/knowledge/policy.json` 的数值参数（区间约束见 `sts2-ascend/brain/reflect.py` 的 BOUNDS；禁止新增键、禁止改 room_weights 结构之外的键路径）
   - `sts2-ascend/knowledge/stats.json` 中卡牌的 `bias` 字段（范围 -4 ~ 4）
4. 代码缺陷：仅当明确发现 `sts2-ascend/brain/policy.py` 的逻辑缺陷时才可编辑该文件，
   且改完必须运行 `py -3 -m py_compile sts2-ascend/brain/policy.py` 验证通过；
   禁止修改其他任何 .py 文件。把改动点与理由写进报告。
5. 新经验同时追加到 `sts2-ascend/knowledge/lessons.md`（一节，标题以 🧠 开头）。

# 禁止事项（最高优先级，覆盖仓库 AGENTS.md 的默认规则）
- 禁止任何 git 操作（add/commit/push 等）
- 禁止停止/启动任何进程（游戏和大脑正在运行）
- 禁止删除文件、禁止安装依赖、禁止修改 knowledge/runs/ 下的历史日志
- 不要读取或修改与本任务无关的文件

完成后，用 200 字以内输出本次复盘总结。"""


# ---------------------------------------------------------------------------
# review execution
# ---------------------------------------------------------------------------

def run_review(know, log=print) -> bool:
    """执行一次大模型复盘。返回 True 表示复盘确实执行了（调用方应自重启以加载变更）。"""
    cfg = load_llm_config()
    if not cfg.get("enabled"):
        log("[llm] 复盘已禁用（llm.enabled=false）")
        return False
    binary = shutil.which(cfg.get("opencode_bin", "opencode"))
    if not binary:
        log(f"[llm] 未找到 opencode 可执行文件（{cfg.get('opencode_bin')}），跳过本次复盘")
        return False

    stamp = time.strftime("%Y-%m-%d %H:%M")
    log(f"[llm] ===== 启动大模型十局复盘（{cfg['model']} via opencode）=====")
    prompt = build_prompt(know, cfg)
    try:
        PROMPT_FILE.write_text(prompt, encoding="utf-8")
    except OSError:
        pass

    cmd = [
        binary, "run",
        "--model", cfg["model"],
        "--title", f"sts2-ascend 十局复盘 {stamp}",
        "--dir", str(REPO_DIR),
        "--auto",   # 无头模式必须自动批准权限，否则无法写文件
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO_DIR),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=int(cfg.get("timeout_min", 25)) * 60,
        )
        out = (proc.stdout or "")[-3000:]
        err = (proc.stderr or "")[-1000:]
        log(f"[llm] 复盘会话结束（exit={proc.returncode}）。输出尾部：\n{out}")
        if proc.returncode != 0:
            log(f"[llm] stderr 尾部：{err}")
            return False
    except subprocess.TimeoutExpired:
        log(f"[llm] 复盘超时（{cfg.get('timeout_min')} 分钟），本次作废")
        return False
    except Exception as exc:
        log(f"[llm] 复盘调用失败（已忽略，不影响游玩）：{exc}")
        return False

    # 复盘产物落盘确认
    if REVIEW_LOG.exists():
        log(f"[llm] 复盘报告见 knowledge/meta_review.md（{REVIEW_LOG.stat().st_size} 字节）")
    else:
        log("[llm] 警告：未发现 meta_review.md，复盘 agent 可能未写报告")
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
