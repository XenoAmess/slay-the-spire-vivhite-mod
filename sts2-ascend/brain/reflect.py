"""Post-run reflection — the evolution step.

After every run ends (victory or death), this module:
  1. commits outcome statistics into the knowledge base (credit assignment),
  2. mutates bounded policy weights according to what killed us / what worked,
  3. appends a human-readable lesson to lessons.md,
  4. advances the ascension ladder on victory.
"""
from __future__ import annotations

import time

from knowledge import Knowledge, clamp

# bounded ranges for every mutable policy knob
BOUNDS = {
    "elite_min_hp_pct": (0.35, 0.9),
    "rest_heal_threshold": (0.35, 0.85),
    "rest_urgent_hp_pct": (0.2, 0.6),
    "block_safety": (0.6, 2.1),
    "kill_bonus": (6.0, 20.0),
    "card_pick_threshold": (0.0, 6.0),
    "shop_relic_threshold": (0.0, 4.0),
    "power_round_bonus": (2.0, 10.0),
    "shop_min_gold": (60, 260),
}


def _adj(know: Knowledge, key: str, delta: float, changes: list[str], why: str) -> None:
    lo, hi = BOUNDS[key]
    old = know.policy[key]
    new = clamp(old + delta, lo, hi)
    if abs(new - old) > 1e-9:
        know.policy[key] = new
        changes.append(f"{key}: {old:.2f} → {new:.2f}（{why}）")


def finalize_run(know: Knowledge, ctx, victory: bool, final_floor: int) -> str:
    """Commit statistics, evolve policy, write lessons. Returns the lesson text."""
    pol = know.policy
    outcome = float(final_floor) + (50.0 if victory else 0.0)

    died_to_enemy = None
    died_to_event = None
    if not victory:
        if ctx.died_to_event is not None:
            died_to_event = ctx.died_to_event[0]
        elif ctx.died_in_combat is not None:
            died_to_enemy = ctx.died_in_combat["comp_id"]

    picked_cards = [t[1] for t in ctx.credit_tags if t[0] == "card_pick"]
    picked_relics = [t[1] for t in ctx.credit_tags if t[0] == "relic_pick" and t[1]]
    visited_rooms = [t[1] for t in ctx.credit_tags if t[0] == "map_node"]

    know.commit_run_end(outcome, victory, picked_cards, picked_relics, visited_rooms,
                        died_to_enemy, died_to_event)

    # ---------------- policy evolution ----------------
    changes: list[str] = []
    if not victory:
        if died_to_enemy and ctx.death_hp_pct_at_entry is not None and ctx.death_was_elite:
            if ctx.death_hp_pct_at_entry < pol["elite_min_hp_pct"] + 0.15:
                _adj(know, "elite_min_hp_pct", 0.05, changes,
                     f"精英战阵亡，进场血量 {ctx.death_hp_pct_at_entry:.0%}，提高精英回避线")
        if died_to_enemy and not ctx.death_was_elite:
            # 死亡模式分流（第 82~83 批复盘）：block_safety 此前是只升不降的
            # 单向棘轮（83 局 0 胜把它顶到 2.1 上限），而死亡榜前列全是血量
            # 170+ 的 Boss/高血组合——长战磨死的正确演化方向是进攻（更快清场
            # = 更少挨意图轮次），不是继续加防。按战斗时长分流：
            #   长战（≥4 回合）磨死 → 提升击杀奖励 + 小幅释放防御棘轮
            #   短时爆毙 → 维持旧逻辑上调防御权重
            rounds = int((ctx.died_in_combat or {}).get("rounds", 0) or 0)
            if rounds >= 4:
                _adj(know, "kill_bonus", 1.0, changes,
                     f"长战磨死（{rounds}回合），提升击杀奖励加快清场")
                _adj(know, "block_safety", -0.05, changes, "长战实证过度龟防会拖长战斗，小幅回调")
            else:
                _adj(know, "block_safety", 0.05, changes, "普通战斗阵亡，略微上调防御权重")
        if died_to_event:
            _adj(know, "exploration_rate", -0.03, changes, "事件致死，收敛探索")
    else:
        _adj(know, "block_safety", -0.02, changes, "胜利证明当前攻防平衡可行，轻微放开进攻")
        if ctx.rests_healed_at_full > 0:
            _adj(know, "rest_heal_threshold", -0.03, changes, "存在满血休息浪费，降低回血阈值")

    # card biases: cards picked often but with below-average outcomes get penalized
    global_avg = know.global_avg_outcome()
    for cid, e in know.stats["cards"].items():
        if e["picked"] >= 4:
            mean = e["outcome_sum"] / e["picked"]
            if mean < global_avg - 8:
                e["bias"] = clamp(e.get("bias", 0.0) - 0.3, -4.0, 4.0)
            elif mean > global_avg + 8:
                e["bias"] = clamp(e.get("bias", 0.0) + 0.2, -4.0, 4.0)

    # exploration decays with experience
    old_exp = pol["exploration_rate"]
    pol["exploration_rate"] = clamp(old_exp * pol["exploration_decay"], pol["exploration_min"], 1.0)
    if abs(pol["exploration_rate"] - old_exp) > 1e-9:
        changes.append(f"exploration_rate: {old_exp:.3f} → {pol['exploration_rate']:.3f}（经验累积，探索衰减）")

    # ---------------- progression ladder ----------------
    prog = know.progression
    asc = ctx.ascension
    prog["runs_by_ascension"][str(asc)] = prog["runs_by_ascension"].get(str(asc), 0) + 1
    best = prog["best_floor_by_ascension"].get(str(asc), 0)
    prog["best_floor_by_ascension"][str(asc)] = max(best, final_floor)
    if victory:
        prog["wins_by_ascension"][str(asc)] = prog["wins_by_ascension"].get(str(asc), 0) + 1
        if asc >= prog.get("current_ascension", 0):
            prog["current_ascension"] = min(asc + 1, prog.get("max_ascension_goal", 10))
            changes.append(f"进阶提升：{asc} → {prog['current_ascension']}（胜利解锁更高难度）")

    # ---------------- lesson text ----------------
    top_cards = sorted(
        ((cid, e) for cid, e in know.stats["cards"].items() if e["picked"] >= 2),
        key=lambda kv: -(kv[1]["outcome_sum"] / kv[1]["picked"]))[:5]
    top_ids = {c for c, _ in top_cards}
    worst_cards = [kv for kv in sorted(
        ((cid, e) for cid, e in know.stats["cards"].items() if e["picked"] >= 2 and cid not in top_ids),
        key=lambda kv: (kv[1]["outcome_sum"] / kv[1]["picked"]))[:3]]

    # 死因标注：失败但无死亡记录时不得标成"胜利"（第 51 局幻影局实证误导复盘）
    death_txt = (f"敌人组合 {died_to_enemy}" if died_to_enemy
                 else f"事件 {died_to_event}" if died_to_event
                 else ("无（胜利）" if victory else "无记录（数据缺失）"))
    lines = [
        f"\n## 第 {know.stats['global']['runs']} 局复盘（{time.strftime('%Y-%m-%d %H:%M')}）",
        f"- 结果：{'🏆 胜利' if victory else '💀 失败'}｜进阶 {asc}｜到达层数 {final_floor}｜当局评分 {outcome:.0f}",
        f"- 死因：{death_txt}",
        f"- 本局拿牌：{', '.join(picked_cards) if picked_cards else '无'}",
        f"- 本局遗物：{', '.join(picked_relics) if picked_relics else '无'}",
        f"- 战斗记录：{'; '.join(ctx.combat_notes[-6:]) if ctx.combat_notes else '无'}",
    ]
    if top_cards:
        lines.append("- 当前高价值卡牌：" + "，".join(f"{c}({e['outcome_sum']/e['picked']:.0f}分/{e['picked']}局)" for c, e in top_cards))
    if worst_cards:
        lines.append("- 当前低价值卡牌：" + "，".join(f"{c}({e['outcome_sum']/e['picked']:.0f}分/{e['picked']}局)" for c, e in worst_cards))
    if changes:
        lines.append("- 策略进化：" + "；".join(changes))
    else:
        lines.append("- 策略进化：本局无参数调整")
    lines.append(f"- 生涯战绩：{know.stats['global']['wins']}/{know.stats['global']['runs']} 胜，"
                 f"当前目标进阶 {prog['current_ascension']}")
    lesson = "\n".join(lines) + "\n"
    know.append_lesson(lesson)
    return lesson
