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
    "boss_atk_mult": (1.0, 1.8),   # Boss 战攻击全局乘区的可演化区间（第 84~85 批复盘接入）
    # 第 86~87 批复盘接入：灰区精英悲观系数 / Boss 入场血量要求线
    "elite_grey_safety_mult": (1.0, 2.5),
    "boss_entry_min_hp_pct": (0.50, 0.90),
    # 第 138~141 批复盘接入：Boss 高血进场长战死证据的承接旋钮（拿牌端输出饥饿）
    "burst_starve_bonus_base": (0.0, 8.0),
    "burst_starve_bonus_extra_max": (0.0, 12.0),
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
    # 僵局摆烂死（第 109 局复盘）：600+ 回合零掉血后主动停止防御送死，血量
    # 损失全部发生在「摆烂」之后——把它当成「格挡不足/击杀太慢」的证据是
    # 归因错位：109 局正是这样把 block_safety 1.05→1.10 推高的。摆烂死对
    # 攻防旋钮均无责，只留痕并把注意力指向卡组输出手段的丢失
    stall_death = bool((ctx.died_in_combat or {}).get("stall"))
    if not victory:
        if died_to_enemy and ctx.death_hp_pct_at_entry is not None and ctx.death_was_elite and not stall_death:
            if ctx.death_hp_pct_at_entry < pol["elite_min_hp_pct"] + 0.15:
                _adj(know, "elite_min_hp_pct", 0.05, changes,
                     f"精英战阵亡，进场血量 {ctx.death_hp_pct_at_entry:.0%}，提高精英回避线")
            # elite_min_hp_pct 已在 0.9 上限顶格空转（第 86~87 批复盘）——
            # 精英死亡信号改接灰区悲观系数：战损重尾证据越积越多，复核越保守
            # 第 135 局复盘修正：只有「灰区进场」（血量 < 硬线）的精英死亡才是
            # 灰区投影的证据。满血线以上进场仍阵亡（135 局 95% 血进精英被异蛙
            # 寄生虫 -76），病因在实战执行/卡组强度，灰区系数吸收纯属错位——
            # 0 胜生涯下胜利释放（-0.1）永不触发，这是又一条漂向 2.5 上限的
            # 单向棘轮，必须只喂它属于自己的证据
            if ctx.death_hp_pct_at_entry < pol["elite_min_hp_pct"]:
                _adj(know, "elite_grey_safety_mult", 0.2, changes,
                     "精英战灰区进场阵亡，灰区悲观投影系数上调")
            else:
                changes.append(f"精英战阵亡但满血线进场（{ctx.death_hp_pct_at_entry:.0%}≥"
                               f"{pol['elite_min_hp_pct']:.0%}）——证据指向实战执行/卡组强度，"
                               "灰区悲观系数不吸收")
        if died_to_enemy and not ctx.death_was_elite:
            if stall_death:
                rounds_s = int((ctx.died_in_combat or {}).get("rounds", 0) or 0)
                changes.append(f"僵局摆烂死（{rounds_s}回合）不计入 kill_bonus/block_safety"
                               "——死因是卡组失去输出手段（消耗螺旋/攻击耗尽），攻防旋钮均无责")
                return "\n".join(changes) if False else lesson_tail(know, changes, ctx, victory, final_floor)
            # 死亡模式分流（第 82~83 批复盘）：block_safety 此前是只升不降的
            # 单向棘轮（83 局 0 胜把它顶到 2.1 上限），而死亡榜前列全是血量
            # 170+ 的 Boss/高血组合——长战磨死的正确演化方向是进攻（更快清场
            # = 更少挨意图轮次），不是继续加防。按战斗时长分流：
            #   长战（≥4 回合）磨死 → 提升击杀奖励 + 小幅释放防御棘轮
            #   短时爆毙 → 维持旧逻辑上调防御权重
            rounds = int((ctx.died_in_combat or {}).get("rounds", 0) or 0)
            death_node = (ctx.died_in_combat or {}).get("node_type")
            if rounds >= 4:
                # 步长按战斗时长分级（第 84~85 批复盘）：固定 ±0.05/+1 的释放
                # 速度要 ~30 局才能把 block_safety 从 2.1 拉回有效区间——
                # 8 回合 Boss 磨死的证据强度是 4 回合的两倍，步长应随之放大
                scale = min(3.0, rounds / 4.0)
                # 顶格治理（第 88~89 批复盘）：kill_bonus 13→14→15、block_safety
                # 2.05→2.00→1.95 连续单向漂移——0 胜生涯里「长战磨死」几乎每局
                # 触发，而长战的真正根因多是卡组输出不足（参数制造不出伤害），
                # 信号只会把两个旋钮单调推向边界（kill_bonus 上限 20 / 下限 0.6），
                # 顶死后重演 86~87 批诊断过的「空转旋钮」。演化前先查行程：
                # 余量不足一步时停止加码并显式留痕，把证据留给下一批复盘
                # 设计接替旋钮（顶格旋钮代谢原则的代码化）
                kb_step = 1.0 * scale
                kb_head = BOUNDS["kill_bonus"][1] - pol["kill_bonus"]
                if kb_head >= kb_step:
                    _adj(know, "kill_bonus", kb_step, changes,
                         f"长战磨死（{rounds}回合），提升击杀奖励加快清场")
                else:
                    changes.append(f"kill_bonus {pol['kill_bonus']:.2f} 距上限仅余 {kb_head:.2f}"
                                   f"(<步长{kb_step:.2f})，长战信号停止加码——顶格旋钮不再吸收证据")
                # 防御释放已从 Boss 长战分支移除（第 107~108 批复盘）：该规则是
                # 第 82~83 批引入的，当时还没有 boss_atk_mult 分轴；如今 Boss 攻坚
                # 已由专属旋钮（boss_atk_mult 提速 + boss_entry_min_hp_pct 入场线）
                # 承担，block_safety 再参与就形成跨语义振荡源——107 局 Boss 磨死
                # 降防（1.07→1.00）、108 局普通长战死升防（1.00→1.05），两种真实
                # 死亡信号让普通战的防御权重永远定不准。block_safety 只服务普通
                # 战斗语义，Boss 长战证据全部流向攻坚双轴
                if death_node == "Boss":
                    # Boss 攻坚乘区演化（第 84~85 批复盘新增）：死亡榜前六全是
                    # F17 一幕 Boss（84~85 批 10 局中 6 局），入场血量从 52%~95%
                    # 全数阵亡——瓶颈是战斗时长而非入场血量。Boss 长战磨死时
                    # 单独加码 boss_atk_mult（不动普通战斗的攻防平衡）
                    _adj(know, "boss_atk_mult", 0.05, changes,
                         f"Boss 长战磨死（{rounds}回合），攻坚乘区提速")
                    # 入场线证据分流（第 138~141 批复盘）：这条线的语义是「低血进场
                    # 扛不住」，只有低血进场被磨死才是它的证据。满血/高血进场照样
                    # 整管打空（63/124/137 局 ≥95% 三连、本批 138~141 四局 60%~100%
                    # 含教科书级满血局）时继续上调，只会逼智能体为攒血放弃精英/
                    # 商店/宝箱——卡组更弱、Boss 更打不过的正反馈死循环（安全棘轮
                    # 联立陷阱的复发形态）。与第 135 批 elite_grey_safety_mult 的
                    # 修正同构：各旋钮只吃属于自己的证据
                    _entry = ctx.death_hp_pct_at_entry
                    be_step = 0.02
                    be_head = BOUNDS["boss_entry_min_hp_pct"][1] - pol["boss_entry_min_hp_pct"]
                    # 证据上限（第 146~147 批复盘）：旧条件「进场<线即上调」让旋钮
                    # 自定义自己的证据阈值（循环自证）——143/146/147 局进场
                    # 66%/80%/100% 全部照输却仍三连 +0.02（0.82→0.88），加上此前
                    # 63/124/137 局 ≥95% 满血进场全数整管打空：0.65 以上带内入场
                    # 血量已被反复证伪为生死变量。0 胜生涯里该棘轮无释放通道，
                    # 必然漂到 0.90 上限并全程刷屏「优先续航路线」扭曲选路
                    # （147 局全程仅 ~6 场战斗的续航畸形路线进 Boss 即实证）。
                    # 只有真正极低血（<证据上限）进场磨死才是入场线的证据
                    _ev_cap = float(pol.get("boss_entry_evidence_hp_cap", 0.65))
                    if _entry is not None and _entry < min(pol["boss_entry_min_hp_pct"], _ev_cap):
                        if be_head >= be_step:
                            _adj(know, "boss_entry_min_hp_pct", be_step, changes,
                                 f"Boss 低血进场磨死（进场 {_entry:.0%}），入场血量要求线上调")
                        else:
                            changes.append(f"boss_entry_min_hp_pct {pol['boss_entry_min_hp_pct']:.2f} "
                                           f"距上限仅余 {be_head:.2f}(<步长{be_step:.2f})，停止加码")
                    else:
                        if _entry is None or _entry >= pol["boss_entry_min_hp_pct"]:
                            _band = (f"高血进场（{'?' if _entry is None else f'{_entry:.0%}'}"
                                     f"≥线 {pol['boss_entry_min_hp_pct']:.0%}）")
                        else:
                            _band = f"中带进场（{_entry:.0%}，≥证据上限 {_ev_cap:.0%}）"
                        changes.append(
                            f"Boss 长战磨死但{_band}——入场血量非生死变量，"
                            "入场线停止上调；证据改接拿牌端输出饥饿")
                        # 高血进场 Boss 长战死的真正根因是卡组击杀速率不足：
                        # 喂给拾取端输出饥饿旋钮，让拿牌对高质攻击更饥渴，
                        # 从源头缩短战斗（参数治不了的病从代码/结构侧治）
                        _adj(know, "burst_starve_bonus_base", 0.3, changes,
                             f"Boss 高血进场长战死（{'?' if _entry is None else f'{_entry:.0%}'}，"
                             f"{rounds}回合），拿牌端攻击饥饿基础分加码")
                        _adj(know, "burst_starve_bonus_extra_max", 0.5, changes,
                             f"Boss 高血进场长战死（{rounds}回合），缺口越深纠偏上限越高")
                elif kb_head >= kb_step:
                    _adj(know, "block_safety", 0.05, changes,
                         f"非 Boss 战斗长战阵亡（{rounds}回合），死因是有效格挡不足而非龟防——上调防御权重")
                else:
                    # 第 127~130 批复盘：长战信号的主承接旋钮 kill_bonus 顶格后，
                    # 防御棘轮仍在代偿吸收——128/129/130 连续三局 +0.05
                    # （1.50→1.65），而生涯 0 胜使 -0.02 胜利释放永不触发，
                    # block_safety 必然单调漂到 2.1 上限后空转。长战证据的语义
                    # 是「战斗时长/输出不足」，92~93 批的防御加码本是与
                    # kill_bonus 并行的伴随项；主旋钮顶格后继续灌防御 = 顶格
                    # 证据的错位吸收（88~89 批原则：余量不足停止加码并留痕，
                    # 把证据留给复盘设计接替旋钮）。对意图升级型敌人，防御加码
                    # 拖长战斗反而是死因本身。短时爆毙（<4回合）分支不受影响
                    # ——那才是真正的「没挡住」证据
                    changes.append(f"非 Boss 长战阵亡（{rounds}回合），kill_bonus 顶格——"
                                   "长战证据不再溢入 block_safety，防御棘轮停止代偿加码")
            else:
                _adj(know, "block_safety", 0.05, changes, "普通战斗阵亡，略微上调防御权重")
        if died_to_event:
            _adj(know, "exploration_rate", -0.03, changes, "事件致死，收敛探索")
    else:
        _adj(know, "block_safety", -0.02, changes, "胜利证明当前攻防平衡可行，轻微放开进攻")
        _adj(know, "elite_grey_safety_mult", -0.1, changes, "胜利证明当前精英规避强度足够，放宽灰区悲观系数")
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
