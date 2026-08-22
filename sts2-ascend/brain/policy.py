"""Decision engine — one Decision per screen, driven by live state + learned knowledge.

Every decision carries:
  action   : the /action name to POST
  params   : option_index / card_index / target_index / command
  reason   : Chinese natural-language rationale (局势分析总结)
  tags     : credit-assignment markers, e.g. ("card_pick", card_id)
  ctx_ops  : side effects on RunContext (tracked in agent.py)
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from knowledge import Knowledge, clamp

# 精英闸门在负分区间的加性罚基数：乘法折扣对负分会"越乘越好"（第 43 局实证），
# 必须换成加性重罚才能保证闸门在任何符号区间都只降分不升分
_ELITE_GATE_NEG_PENALTY = 50.0


@dataclass
class Decision:
    action: str | None = None          # None = wait (do nothing this tick)
    params: dict = field(default_factory=dict)
    reason: str = ""
    tags: list = field(default_factory=list)
    wait: float = 0.5                  # seconds to wait after executing


# ---------------------------------------------------------------------------
# card feature extraction
# ---------------------------------------------------------------------------

_NUM = r"(\d+)"

def _text(card: dict) -> str:
    return card.get("resolved_rules_text") or card.get("rules_text") or ""


def card_numbers(card: dict) -> tuple[int, int, int]:
    """(damage_per_hit, block, hits) from dynamic_values, falling back to text parse."""
    dmg = block = 0
    hits = 1
    for dv in card.get("dynamic_values") or []:
        name = (dv.get("name") or "").lower()
        val = dv.get("current_value", dv.get("base_value", 0)) or 0
        if "damage" in name or "伤害" in name:
            dmg = int(val)
        elif "block" in name or "格挡" in name:
            block = int(val)
        elif "hit" in name or "次数" in name:
            hits = max(1, int(val))
    text = _text(card)
    if dmg == 0:
        m = re.search(_NUM + r"\s*点伤害|deal\s+" + _NUM + r"\s+damage", text, re.I)
        if m:
            dmg = int(next(g for g in m.groups() if g))
    if block == 0:
        m = re.search(_NUM + r"\s*点格挡|gain\s+" + _NUM + r"\s+block|" + _NUM + r"\s+block", text, re.I)
        if m:
            block = int(next(g for g in m.groups() if g))
    if hits == 1:
        m = re.search(r"(\d+)\s*次|x(\d+)\b|twice|两次", text, re.I)
        if m:
            g = next((g for g in m.groups() if g and g.isdigit()), None)
            if g:
                hits = max(1, int(g))
            elif m.group(0) in ("twice", "两次"):
                hits = 2
    return dmg, block, hits


def card_type(card: dict) -> str:
    return card.get("card_type") or ""


def is_attack(card: dict) -> bool:
    return card_type(card).lower() == "attack"


def is_power(card: dict) -> bool:
    return card_type(card).lower() == "power"


def is_skill(card: dict) -> bool:
    return card_type(card).lower() == "skill"


def is_bad_card(card: dict) -> bool:
    return card_type(card).lower() in ("status", "curse")


def draw_amount(card: dict) -> int:
    text = _text(card)
    m = re.search(r"抽\s*" + _NUM + r"\s*张|draw\s+" + _NUM, text, re.I)
    return int(next(g for g in m.groups() if g)) if m else 0


class Policy:
    def __init__(self, know: Knowledge, rng: random.Random | None = None):
        self.know = know
        self.rng = rng or random.Random()
        self._end_stall = 0  # consecutive ticks with end_turn but no play_card available
        self._saw_playable_this_turn = False  # 本回合是否进入过可出牌状态（区分"还没就绪"与"真出完了"）
        self._shop_done_floor = -1  # floor of the shop we already finished evaluating
        self._reward_floor = -1     # reward screen identity tracking
        self._reward_tried: set = set()  # (reward_type, description) already attempted this screen
        self._sel_key = None        # card-selection screen identity
        self._sel_tried: set = set()  # card indices already clicked this screen
        self._cur_turn = None       # combat turn tracking
        self._failed_this_turn: set = set()  # 本回合打出失败的卡牌实例（hand index，非 card_id）
        self._potion_combat = None  # combat instance identity for potion blacklist
        self._potion_tried: set = set()      # potion indices already attempted this combat
        self._phase_stall = 0       # 转阶段过场（无有效目标）连续等待计数
        self._removal_pending_floor = -1  # 商店删牌握手：remove_card_at_shop 已发出，等待选牌界面
        self._kills_combat = None   # 战斗实例身份（重生召唤物检测用）
        self._combat_kills: dict = {}  # enemy_id -> 本场已预测击杀次数（≥2 判定重生体）

    def note_action_failed(self, action: str, tags: list) -> None:
        """agent 在执行失败时回调：本回合内不再尝试这张牌实例（防 409 重试刷屏）。

        按 hand index 记账而非 card_id：第 31 局 F7 终局一张防御 409（瞬时时序抖动）
        把同 id 的两张防御全部拉黑，剩 18 点意图无甲吃刀阵亡——
        惩罚必须精确到打失败的那一张，同 id 的其他副本不受连坐。
        """
        if action == "play_card":
            for t in tags or []:
                if t[0] == "play_card_index":
                    try:
                        self._failed_this_turn.add(int(t[1]))
                    except (TypeError, ValueError):
                        pass

    # ------------------------------------------------------------------
    # top-level router
    # ------------------------------------------------------------------

    def decide(self, state: dict, ctx) -> Decision:
        screen = state.get("screen", "UNKNOWN")
        handler = {
            "MAIN_MENU": self._main_menu,
            "CHARACTER_SELECT": self._character_select,
            "MAP": self._map,
            "COMBAT": self._combat,
            "REWARD": self._reward,
            "CARD_SELECTION": self._card_selection,
            "SHOP": self._shop,
            "REST": self._rest,
            "CHEST": self._chest,
            "EVENT": self._event,
            "MODAL": self._modal,
            "GAME_OVER": self._game_over,
            "TIMELINE": self._timeline,
            "BUNDLE_SELECTION": self._bundle,
            "CAPSTONE": self._capstone,
        }.get(screen)
        if handler is None:
            return self._unknown(state, ctx)
        try:
            decision = handler(state, ctx)
            self._decide_errors = 0
            return decision
        except Exception as exc:  # never crash the loop on a policy bug
            self._decide_errors = getattr(self, "_decide_errors", 0) + 1
            # 连续异常（如代码/知识库版本错位的 AttributeError）会每 tick 空转僵死，
            # 看门狗的 abandon_run 在 MAP 等屏幕上又不可用——连续异常时改发安全动作自救：
            if self._decide_errors >= 10:
                actions = state.get("available_actions", [])
                for safe in ("proceed", "end_turn", "confirm_modal", "collect_rewards_and_proceed",
                             "skip_reward_cards", "confirm_selection", "confirm_bundle",
                             "dismiss_modal", "open_chest", "close_shop_inventory"):
                    if safe in actions:
                        return Decision(safe, {}, f"决策连续异常×{self._decide_errors}，尝试 {safe} 自救（{exc}）", wait=1.0)
                for indexed in ("select_deck_card", "choose_reward_card", "choose_rest_option",
                                "choose_event_option", "choose_treasure_relic", "choose_bundle",
                                "claim_reward", "resolve_rewards", "choose_map_node"):
                    if indexed in actions:
                        return Decision(indexed, {"option_index": 0},
                                        f"决策连续异常×{self._decide_errors}，盲选 {indexed}[0] 自救（{exc}）", wait=1.0)
            return Decision(action=None, reason=f"决策异常({screen}): {exc}", wait=1.0)

    # ------------------------------------------------------------------
    # menu / character select / timeline
    # ------------------------------------------------------------------

    def _main_menu(self, state: dict, ctx) -> Decision:
        actions = state.get("available_actions", [])
        timeline = state.get("timeline")
        if timeline and timeline.get("can_confirm_overlay") and "confirm_timeline_overlay" in actions:
            return Decision("confirm_timeline_overlay", {}, "主菜单：确认时间线弹层", wait=0.8)
        if timeline and timeline.get("can_choose_epoch") and "choose_timeline_epoch" in actions:
            # 只点 obtained（新获得待确认）的槽位；complete 的点开只是查看——
            # 曾因此把同一个已完成槽位无限重复点击（is_actionable 含 complete）。
            # 另用 timeline_tried 防"点了状态不变"的兜底循环。
            tried = getattr(ctx, "timeline_tried", None)
            if tried is None:
                tried = ctx.timeline_tried = set()
            new_slots = [s for s in timeline.get("slots", [])
                         if (s.get("state") or "") == "obtained" and s.get("index") not in tried]
            if new_slots:
                s = new_slots[0]
                tried.add(s.get("index"))
                return Decision("choose_timeline_epoch", {"option_index": s["index"]},
                                f"主菜单：解锁时间线新内容【{s.get('title')}】", wait=0.8)
            # 没有新内容 → 关闭时间线弹层，继续主流程
            if "close_main_menu_submenu" in actions:
                ctx.timeline_tried = set()
                return Decision("close_main_menu_submenu", {}, "主菜单：时间线无新解锁，关闭弹层", wait=0.8)
        if "continue_run" in actions:
            return Decision("continue_run", {}, "主菜单：检测到进行中的存档，继续对局", wait=1.2)
        # 一局结束后：时间线有新解锁项（obtained 未 complete）时优先去解锁
        if getattr(ctx, "check_timeline", False):
            ctx.check_timeline = False
            if "open_timeline" in actions:
                return Decision("open_timeline", {}, "主菜单：检查时间线可解锁项（优先解锁新内容）", wait=1.0)
        if "open_character_select" in actions:
            return Decision("open_character_select", {}, "主菜单：开启新的一局（标准模式）", wait=1.2)
        return Decision(None, {}, "主菜单：无可用动作，等待", wait=1.0)

    def _timeline(self, state: dict, ctx) -> Decision:
        actions = state.get("available_actions", [])
        timeline = state.get("timeline") or {}
        # 1) 解锁页/查看页弹层优先确认
        if timeline.get("can_confirm_overlay") and "confirm_timeline_overlay" in actions:
            return Decision("confirm_timeline_overlay", {}, "时间线：确认解锁页", wait=0.8)
        # 2) 有新获得（obtained 未 complete）且未点过的槽位 → 优先解锁
        tried = getattr(ctx, "timeline_tried", None)
        if tried is None:
            tried = ctx.timeline_tried = set()
        unlockable = [s for s in timeline.get("slots", [])
                      if (s.get("state") or "") == "obtained" and s.get("index") not in tried]
        if unlockable and "choose_timeline_epoch" in actions:
            s = unlockable[0]
            tried.add(s.get("index"))
            return Decision("choose_timeline_epoch", {"option_index": s["index"]},
                            f"时间线：优先解锁新内容【{s.get('title')}】", wait=1.0)
        # 3) 没有可解锁项 → 关闭时间线回主菜单开新局
        if "close_main_menu_submenu" in actions:
            ctx.timeline_tried = set()
            return Decision("close_main_menu_submenu", {}, "时间线：无可解锁项，返回主菜单", wait=0.8)
        return self._main_menu(state, ctx)

    def _character_select(self, state: dict, ctx) -> Decision:
        cs = state.get("character_select") or {}
        chars = cs.get("characters", [])
        target = self.know.progression.get("character", "IRONCLAD")
        chosen = None
        for c in chars:
            cid = (c.get("character_id") or "").upper()
            if c.get("is_locked") or c.get("is_random"):
                continue
            if target in cid:
                chosen = c
                break
        if chosen is None:  # fallback: first unlocked non-random (leftmost warrior)
            for c in chars:
                if not c.get("is_locked") and not c.get("is_random"):
                    chosen = c
                    break
        if chosen is None:
            return Decision(None, {}, "选角界面：未找到可用角色", wait=1.0)
        if not chosen.get("is_selected"):
            return Decision("select_character", {"option_index": chosen["index"]},
                            f"选择角色：{chosen.get('name')}（目标角色 {target}）",
                            tags=[("character", chosen.get("character_id"))], wait=0.8)

        # ascension ladder
        current = cs.get("ascension", 0)
        goal = min(self.know.progression.get("current_ascension", 0), cs.get("max_ascension", 0))
        if current < goal and cs.get("can_increase_ascension") and "increase_ascension" in state.get("available_actions", []):
            return Decision("increase_ascension", {}, f"调整进阶：{current} → {current + 1}（目标 {goal}）", wait=0.5)
        if current > goal and cs.get("can_decrease_ascension") and "decrease_ascension" in state.get("available_actions", []):
            return Decision("decrease_ascension", {}, f"调整进阶：{current} → {current - 1}（目标 {goal}）", wait=0.5)

        if cs.get("can_embark") and "embark" in state.get("available_actions", []):
            return Decision("embark", {}, f"出发！角色={chosen.get('name')} 进阶={current}",
                            tags=[("embark", current)], wait=2.0)
        return Decision(None, {}, f"选角界面：等待可出发状态（asc={current}）", wait=0.8)

    # ------------------------------------------------------------------
    # map
    # ------------------------------------------------------------------

    def _elite_path_gate(self, pol: dict, priors: dict, hp: int, max_hp: int,
                         good_cards: int, act_mul: float) -> tuple[float, str]:
        """精英进场闸门：按实测战损投影"打完精英还剩多少血"，不达标整条候选路径重罚。

        第 36 局实证：71% 血进灰区精英单场 -44（77% 现血）+ 两瓶药水，连锁三个
        篝火回血、零锻造，Boss 战全盘崩盘。旧灰区 ×0.5 只罚首节点权重，
        压不住子树优势（精英后接篝火回血的路径组合分反而更高）——闸门必须乘在
        候选总分上：选精英等于承诺承担它的全部后果。

        卡组强度只按封顶折扣折抵精英战损（牌数≠质量，全价折抵曾让投影过度乐观；
        simulate() 内部模拟仍用全额折扣，闸门独立更保守，二者取严不冲突）。
        """
        hpp = hp / max(1, max_hp)
        if good_cards < pol.get("elite_min_deck_cards", 4):
            return 0.1, (f"非基础牌仅{good_cards}张(<{pol.get('elite_min_deck_cards', 4)})，"
                         f"卡组强度不足规避精英")
        hard = float(pol["elite_min_hp_pct"])
        soft = float(pol.get("elite_soft_hp_pct", max(0.35, hard - 0.15)))
        if hpp < soft:
            return 0.1, f"血量{hpp:.0%}<{soft:.0%}，规避精英"
        prior = self.know.room_damage_prior("Elite", float(priors.get("Elite", 28)))
        deck_relief = min(0.20, 0.02 * good_cards)
        proj = hpp - prior * act_mul * (1.0 - deck_relief) / max(1, max_hp)
        req = float(pol.get("path_hp_floor_pct", 0.35)) + 0.10 / max(1.0, act_mul)
        if proj < req:
            return 0.1, (f"血量{hpp:.0%}进精英预计战后仅剩{max(0.0, proj):.0%}"
                         f"(需求≥{req:.0%})，规避精英")
        if hpp < hard:
            return 0.5, f"血量{hpp:.0%}处于精英灰区({soft:.0%}~{hard:.0%})，谨慎评估"
        return 1.0, ""

    def _map(self, state: dict, ctx) -> Decision:
        m = state.get("map") or {}
        nodes = m.get("available_nodes", [])
        if not nodes:
            return Decision(None, {}, "地图：暂无可走节点", wait=0.8)
        run = state.get("run") or {}

        # 永久增益类 AnyTime 药水（如加最大生命）：拿到就用，不占战斗决策
        for p in run.get("potions", []):
            if p.get("occupied") and p.get("can_use") and (p.get("usage") or "").lower() == "anytime":
                desc = p.get("description") or ""
                if "最大生命" in desc or "MaxHp" in desc:
                    return Decision("use_potion", {"option_index": p["index"]},
                                    f"地图：使用永久增益药水【{p.get('name')}】",
                                    tags=[("use_potion", p.get("potion_id"))], wait=0.7)
        hp = run.get("current_hp", 1)
        max_hp = max(1, run.get("max_hp", 1))
        hp_pct = hp / max_hp
        gold = run.get("gold", 0)
        floor = run.get("floor", 0)
        pol = self.know.policy
        weights = pol["room_weights"]
        priors = pol.get("path_danger_priors", {})
        heal_frac = pol.get("rest_heal_fraction", 0.30)

        # room danger learning: average hp loss per node type biases weights
        def learned_room_factor(node_type: str) -> float:
            e = self.know.stats["rooms"].get(node_type)
            if not e or e["visits"] < 3:
                return 1.0
            avg = e["outcome_sum"] / e["visits"]
            glob = self.know.global_avg_outcome()
            f = clamp(1.0 + (avg - glob) / 50.0, 0.5, 1.5)
            if node_type == "Elite":
                # 精英的到访记录天然集中在"走得远的强局"（幸存者偏差），
                # 该因子本意衡量房间价值，不应给高危房额外加分（第 36 局 F11
                # 精英因此被抬到 19.47 分压过 Unknown 17.66）
                f = min(f, 1.0)
            return f

        # 卡组强度：非基础牌数量（精英进场门槛之一）
        good_cards = 0
        for c in run.get("deck", []):
            cid = (c.get("card_id") or "").upper()
            if "STRIKE" in cid or "DEFEND" in cid or is_bad_card(c):
                continue
            good_cards += 1

        boss_row = (m.get("boss_node") or {}).get("row")
        if boss_row is None:
            # 地图载荷缺 boss_node 键（第 27~28 局实证：投影把 Boss 当普通节点扣 45 点先验，
            # F16 实际 77% 血被报成"预计进 Boss 血量 35%"）——退化用图中最深行推断 Boss 行
            rows = sorted({int(n.get("row", 0)) for n in m.get("nodes", [])})
            if len(rows) >= 2:
                boss_row = rows[-1]
        graph = {(n["row"], n["col"]): n for n in m.get("nodes", [])}

        def node_factor(nt: str, gnode: dict | None, hpp: float):
            """单节点权重修正系数与说明。"""
            if nt == "Elite":
                if good_cards < pol.get("elite_min_deck_cards", 4):
                    return 0.1, f"非基础牌仅{good_cards}张(<{pol.get('elite_min_deck_cards', 4)})，卡组强度不足规避精英"
                hard = float(pol["elite_min_hp_pct"])
                soft = float(pol.get("elite_soft_hp_pct", max(0.35, hard - 0.15)))
                if hpp < soft:
                    return 0.1, f"血量{hpp:.0%}<{soft:.0%}，规避精英"
                if hpp < hard:
                    # 灰区不再一刀切：第 28 局 F12 以 78% 血与 0.80 硬线差 2% 而错过精英
                    return 0.5, f"血量{hpp:.0%}处于精英灰区({soft:.0%}~{hard:.0%})，谨慎评估"
                return 1.0, "血量与卡组达标，精英奖励价值高"
            if nt == "RestSite":
                if hpp < pol["rest_urgent_hp_pct"]:
                    return 2.5, "低血量急需休息"
                if boss_row is not None and (gnode or {}).get("row", 0) >= boss_row - 1:
                    return 2.0, "Boss 前休整"
                # 警戒带（第 54 局实证：47.5% 血不在急需线内，篝火无任何加权，
                # 被"金币足够"的商店以 0.54 分压过，随后被迫 48% 血进精英阵亡）
                if hpp < pol.get("rest_wary_hp_pct", 0.62):
                    return 1.7, "血量偏低（<62%），优先休整续航"
            elif nt == "Shop":
                if gold >= pol["shop_min_gold"]:
                    return 1.4, f"金币{gold}足够"
                return 0.6, "金币不足"
            elif nt == "Monster":
                # 低血量时"前期积累卡牌"必须让位于生存：
                # 第 30 局 21% 血仍以 1.25 加成走进第 7 连战阵亡
                if hpp < pol["rest_urgent_hp_pct"]:
                    return 0.45, f"血量{hpp:.0%}过低，避免无谓消耗战"
                if floor <= 8:
                    # 第 56 局实证：加成无健康门槛，44% 血仍以 1.25 吃满，
                    # F4 岔路以 0.96 分压过 Unknown（25.52 vs 24.56），错失
                    # 商店/事件/休息多样性后漏斗行军阵亡——警戒带内回落中性
                    if hpp >= pol.get("rest_wary_hp_pct", 0.62):
                        return 1.25, "前期需要战斗积累卡牌"
                    return 1.0, "血量偏低，前期积累让位续航"
            return 1.0, ""

        # ---- 全路径规划：从每个候选节点枚举到 Boss 行的所有路径，
        # 按历史场均掉血先验模拟沿途血量演进，投影死亡/低血进 Boss 重罚。
        # 解决贪心逐格选路的盲区：早期分支把后续逼进"唯一可选的精英"。----
        # 幕数缩放：先验来自一幕场均，二/三幕怪物伤害显著升级，必须放大
        # （第 18 局 F22 Unknown 连环遭遇战一场 -59，恒定先验完全低估）
        acts = pol.get("path_act_scale") or [1.0]
        act_idx = min(len(acts) - 1, max(0, (floor - 1) // 17))
        act_mul = float(acts[act_idx]) if isinstance(acts[act_idx], (int, float)) else 1.0

        elite_gate_f, elite_gate_note = self._elite_path_gate(
            pol, priors, hp, max_hp, good_cards, act_mul)

        def paths_from(start_key) -> list[list[tuple]]:
            out: list[list[tuple]] = []

            def dfs(key, path):
                g = graph.get(key)
                children = [c for c in ((g or {}).get("children") or [])
                            if (c.get("row"), c.get("col")) not in path]
                row = key[0]
                if (not children or len(path) > 40 or len(out) >= 512
                        or (boss_row is not None and row >= boss_row)):
                    out.append(list(path))
                    return
                for ch in children:
                    ck = (ch.get("row"), ch.get("col"))
                    path.append(ck)
                    dfs(ck, path)
                    path.pop()

            dfs(start_key, [start_key])
            return out or [[start_key]]

        def simulate(start_node, path_keys):
            # 卡组越强战斗越短：掉血先验按非基础牌数打折（每张 -3%，最多 -40%）
            deck_ease = 1.0 - min(0.40, 0.03 * good_cards)
            score, cur_hp, notes = 0.0, float(hp), []
            mid_gate_hit = False
            for depth, key in enumerate(path_keys):
                gnode = graph.get(key) or {}
                nt = start_node.get("node_type", "Unknown") if depth == 0 else gnode.get("node_type", "Unknown")
                hpp = max(0.0, cur_hp) / max_hp
                # 中段精英复检闸门：外层闸门只查候选首节点，第 54 局 F12 商店路径
                # 的子树里藏着 F13 精英，47.5% 血被"金币足够"抬进精英漏斗。
                # 逐节点选路意味着中段精英尚未承诺（后续仍可改道），罚分取外层
                # 闸门的一半强度、加性实现（符号安全），仅作子树前景的投影修正
                if nt == "Elite" and depth >= 1:
                    gf, _gnote = self._elite_path_gate(pol, priors, int(round(cur_hp)), max_hp,
                                                        good_cards, act_mul)
                    if gf < 1.0:
                        score -= (1.0 - gf) * _ELITE_GATE_NEG_PENALTY * 0.5
                        mid_gate_hit = True
                factor, note = node_factor(nt, gnode, hpp)
                w = weights.get(nt, 1.0) * learned_room_factor(nt) * factor
                score += w * (0.97 ** depth)
                if note and depth == 0:
                    notes.append(note)
                # 掉血先验：静态值与实测场均掉血（rooms 数据）加权混合；
                # 无实测数据时按敌人统计的总体校准系数放大，修复静态先验系统性低估
                prior = self.know.room_damage_prior(nt, float(priors.get(nt, 8)))
                # Boss 行节点是路径终点：投影语义为"进入该节点的血量"，
                # 不扣 Boss 自身战损（旧版把 45 点 Boss 先验也扣进去，
                # 导致第 28 局实际以 77% 血进 Boss 却被投影成 35%，严重误导决策与复盘）
                if boss_row is not None and key[0] >= boss_row:
                    continue
                cur_hp -= prior * deck_ease * act_mul
                if nt == "Unknown" and act_idx >= 1:
                    cur_hp -= prior * deck_ease * act_mul * (pol.get("unknown_gauntlet_act2_mult", 1.6) - 1.0)
                if nt == "RestSite":
                    cur_hp = min(float(max_hp), cur_hp + heal_frac * max_hp)
                if cur_hp <= 0:
                    # 死亡投影保留"撑得更久"的序信息：死得越晚罚得越轻。
                    # 第 43 局实证：低血量时所有候选都吃满 -100，候选间评分差被压成
                    # 噪声，能续命的篝火与当场暴毙的精英无法区分（还给了闸门反转可乘之机）
                    score -= max(0.0, pol.get("path_death_penalty", 100.0) - 3.0 * min(depth, 15))
                    break
            final_pct = max(0.0, cur_hp) / max_hp
            if mid_gate_hit:
                notes.append("路径中段含未达标精英，投影罚分")
            floor_pct = pol.get("path_hp_floor_pct", 0.35)
            if final_pct < floor_pct:
                score -= (floor_pct - final_pct) * 40.0
            return score, notes, final_pct

        best_node, best_score, best_detail, best_notes, best_proj = None, -1e9, "", [], 0.0
        details = []
        for n in nodes:
            nt = n.get("node_type", "Unknown")
            best_ps, best_pnotes, best_pproj = -1e9, [], 0.0
            for pth in paths_from((n["row"], n["col"])):
                ps, pnotes, pproj = simulate(n, pth)
                if ps > best_ps:
                    best_ps, best_pnotes, best_pproj = ps, pnotes, pproj
            if nt == "Elite" and elite_gate_f < 1.0:
                # 精英闸门乘在整条候选路径总分上（而非只罚首节点权重）：
                # 子树优势（精英后接篝火/宝箱的组合分）曾完全吞掉首节点减权。
                # 第 43 局实证：低血量全路径投影死亡（总分≈-110）时，×0.1 反而把
                # 精英从 -110 抬到 -11，压过篝火(-109)——负分区间乘法是奖励不是
                # 惩罚。改为：正分区间维持乘法语义；负分区间加性重罚，保证闸门
                # 在任何符号下都只降分不升分。
                gated = best_ps * elite_gate_f
                if gated < best_ps:
                    best_ps = gated
                else:
                    best_ps -= (1.0 - elite_gate_f) * _ELITE_GATE_NEG_PENALTY
                if elite_gate_note:
                    # 闸门已否决时删去 node_factor 的正面注释，避免理由自相矛盾
                    best_pnotes = [x for x in best_pnotes if "达标，精英奖励价值高" not in x]
                    best_pnotes.append(elite_gate_note)
            label = f"{nt}({n['row']},{n['col']})"
            details.append(f"{label}={best_ps:.2f}{'|' + '；'.join(best_pnotes) if best_pnotes else ''}")
            if best_ps > best_score:
                best_node, best_score = n, best_ps
                best_detail = label
                best_notes, best_proj = best_pnotes, best_pproj

        note_txt = f"；{'；'.join(best_notes)}" if best_notes else ""
        # Boss 前夜篝火语义传递（第 48 局实证：72% 血在 Boss 前夜按常规线选了
        # 锻造，Boss 战 -58 正好打死；回血 +24 即可保命——_rest 据此优先回血）
        ctx.rest_before_boss = (best_node.get("node_type") == "RestSite"
                                and boss_row is not None
                                and int(best_node.get("row", -999)) == int(boss_row) - 1)
        ctx_ops_tags = [("map_node", best_node.get("node_type", "Unknown"))]
        return Decision("choose_map_node", {"option_index": best_node["index"]},
                        f"路径规划：{best_detail}（路径分 {best_score:.2f}，预计进 Boss 血量 {best_proj:.0%}{note_txt}）；"
                        f"候选：{' / '.join(details)}",
                        tags=ctx_ops_tags, wait=1.5)

    # ------------------------------------------------------------------
    # combat
    # ------------------------------------------------------------------

    def _combat(self, state: dict, ctx) -> Decision:
        combat = state.get("combat") or {}
        player = combat.get("player") or {}
        enemies = [e for e in combat.get("enemies", []) if e.get("is_alive") and e.get("is_hittable")]
        hand = combat.get("hand", [])
        energy = player.get("energy", 0)
        round_no = state.get("turn") or 1
        pol = self.know.policy
        actions = state.get("available_actions", [])
        can_play = "play_card" in actions
        can_end = "end_turn" in actions

        if self._cur_turn != round_no:
            self._cur_turn = round_no
            self._failed_this_turn = set()
            self._saw_playable_this_turn = False
        if self._potion_combat is not ctx.combat:
            self._potion_combat = ctx.combat
            self._potion_tried = set()
        if self._kills_combat is not ctx.combat:
            self._kills_combat = ctx.combat
            self._combat_kills = {}

        if not enemies:
            # 无有效目标 ≠ 空回合：Boss/精英蓄力或转阶段过场时敌人暂时不可选中，
            # 旧逻辑直接结束回合白扔能量（整轮输出窗口作废，战斗被拖长多吃意图）。
            # 手牌能量俱在时先等几个 tick，过场通常会自行恢复。
            if can_end:
                playable_left = any(c.get("playable") and c.get("energy_cost", 0) <= energy
                                    for c in hand)
                if playable_left and energy > 0:
                    self._phase_stall += 1
                    if self._phase_stall <= 6:
                        return Decision(None, {}, f"战斗：暂无可打目标但手牌能量俱在（疑似转阶段过场），等待（{self._phase_stall}/6）", wait=0.7)
                    self._phase_stall = 0
                    return Decision("end_turn", {}, "战斗：转阶段等待超时，结束回合保底", wait=1.0)
                self._phase_stall = 0
                return Decision("end_turn", {}, "战斗：场上无有效敌人，结束回合", wait=1.0)
            return Decision(None, {}, "战斗：等待敌人就绪", wait=0.7)
        self._phase_stall = 0

        incoming = sum((it.get("total_damage") or 0) for e in enemies for it in e.get("intents", []))
        my_block = player.get("block", 0)
        my_hp = player.get("current_hp", 1)
        my_max_hp = max(1, player.get("max_hp", my_hp))
        block_gap = max(0, incoming - my_block)

        # 关键时序规则：mod 只在手牌就绪后暴露 play_card，而 end_turn 可能更早出现。
        # 没看到 play_card 就急着 end_turn 会把还没抽好的整回合手牌白白扔掉。
        # 实测：回合过渡窗口可达 5 秒（空手→能量回满→手牌逐张浮现→play_card 开放），
        # 因此用"本回合是否进入过可出牌状态"区分两种情形：
        #   - 已进入过 → 现在没的出 = 真的出完了，短确认即结束回合（不拖节奏）
        #   - 从未进入 → 还在抽牌/开局触发动画里，必须长耐心等待（15 次≈9 秒）
        if not can_play:
            if can_end:
                self._end_stall += 1
                hand_desc = ",".join(f"{c.get('name')}{'✓' if c.get('playable') else '✗'}" for c in hand) or "空手"
                if self._saw_playable_this_turn:
                    if self._end_stall < 2:
                        return Decision(None, {}, f"战斗：本回合已无牌可出，确认结束（{hand_desc}）", wait=0.5)
                    self._end_stall = 0
                    return Decision("end_turn", {}, "战斗：确认无牌可出（能量耗尽或全部不可用），结束回合", wait=1.2)
                if self._end_stall < 15:
                    return Decision(None, {}, f"战斗：手牌未就绪，等待稳定（{self._end_stall}/15，{hand_desc}）", wait=0.6)
                self._end_stall = 0
                return Decision("end_turn", {}, "战斗：手牌长时间未就绪（疑似全部不可用），结束回合", wait=1.2)
            return Decision(None, {}, "战斗：回合过渡中，等待", wait=0.6)
        self._end_stall = 0
        self._saw_playable_this_turn = True

        # 药水使用门槛：精英/Boss、致死威胁，以及"低血量且有缺口"。
        # 第 30~32 局连续三局带着可用药水进坟墓（敏捷/缚魂全程未用）——
        # 启发式引擎等不到"完美时机"，低血量时增益/攻击药水必须立即兑现。
        low_hp_bleeding = my_hp <= 0.35 * my_max_hp and block_gap > 0
        # premium：值得动用增益药水的场合（硬房/真致死）。普通消耗战哪怕低血也留着——
        # 第 36 局 F15 把异鱼之油倒进净损 2 血的顺风波，Boss 战空手阵亡。
        premium = bool(ctx.current_combat_is_hard or combat.get("end_turn_will_kill_player")
                       or block_gap >= my_hp)
        hard = (premium or low_hp_bleeding)
        potion_dec = self._maybe_potion(state, ctx, hard, premium)
        if potion_dec is not None:
            return potion_dec

        # 敌方组合历史战绩 → 战斗姿态（高危组合自动转防守，见 knowledge.enemy_stance；
        # Boss 房间反转姿态：斩杀线不足时压攻击=拖长战斗多吃意图）
        cctx = getattr(ctx, "combat", None) or {}
        comp_id = cctx.get("comp_id") or None
        stance = self.know.enemy_stance(comp_id, cctx.get("node_type"))
        danger_note = f"；⚠{stance['danger']}，转防守节奏" if stance.get("danger") else ""

        best = None  # (score, card, target_index, why)
        # 服务端致死判定：意图数值可能被敌方增益/减益污染，本地算术会漏判——
        # 只要服务端说"结束回合会死"且缺口未补满，就按致死回合处理（第 31 局 F7 终局教训）
        forced_kill = bool(combat.get("end_turn_will_kill_player"))
        # 能量预留：缺口未补且手里还有可负担的格挡牌时，非击杀攻击不得吃掉
        # 补防所需的最低能量——第 36 批 F17 Boss 战实证：先挥霍能量打输出，
        # 下一轮 20 点意图来袭时手持两张防御却 0 能量，无甲硬吃。
        gap_now = max(0, incoming - my_block)
        affordable_blk_costs = [c.get("energy_cost", 0) for c in hand
                                if c.get("playable") and c.get("index") not in self._failed_this_turn
                                and card_numbers(c)[1] > 0 and c.get("energy_cost", 0) <= energy]
        reserve_for_block = gap_now > 0 and bool(affordable_blk_costs)
        min_blk_cost = min(affordable_blk_costs) if affordable_blk_costs else 99
        for c in hand:
            if not c.get("playable"):
                continue
            if c.get("index") in self._failed_this_turn:
                continue
            # 需要目标但载荷里的有效目标列表为空/过期（击杀敌人后刷新延迟时常见）：
            # 不再静默跳过——第 44 局 F6 上勾拳斩杀后，剩余 4 张可出攻击被整体跳过、
            # 对 14 点意图弃权结束回合；第 45 局同型流失反复出现（欺凌✓不打出）。
            # 现改为照常评分参选，出牌时兜底指向最高威胁存活敌人；若真非法，
            # 服务端 409 拒绝一次并由实例黑名单接管——代价一个 tick，
            # 远小于整回合弃权白吃整套意图。
            cost = c.get("energy_cost", 0)
            if c.get("costs_x"):
                cost = energy  # dump all energy
            if cost > energy:
                continue
            score, target, why = self._score_play(c, enemies, incoming, my_block, round_no, pol,
                                                  my_hp, my_max_hp, stance, forced_kill,
                                                  reserve_for_block, min_blk_cost, energy)
            score += self.know.card_value(c.get("card_id", "")) * 0.3
            if best is None or score > best[0]:
                best = (score, c, target, why)

        if best and best[0] > pol["play_threshold"]:
            _, card, target, why = best
            # 记录"预测击杀"：同一敌人本场被预测击杀 ≥2 次仍存活 → 重生召唤物，
            # 后续击杀奖励大幅衰减（第 52~53 局利齿之眼实证）
            if target is not None and isinstance(why, str) and why.startswith("可击杀"):
                tgt = next((e for e in enemies if e.get("index") == target), None)
                if tgt is not None:
                    kid = tgt.get("enemy_id") or tgt.get("name") or ""
                    self._combat_kills[kid] = self._combat_kills.get(kid, 0) + 1
            params = {"card_index": card["index"]}
            if card.get("requires_target"):
                if target is None:
                    # 非攻击类指向牌（如施加 debuff 的技能）：兜底选威胁最高的敌人
                    valid = card.get("valid_target_indices") or []
                    def threat(idx):
                        e = next((x for x in enemies if x.get("index") == idx), None)
                        return sum((it.get("total_damage") or 0) for it in (e or {}).get("intents", [])) if e else 0
                    pool = [i for i in valid if any(e.get("index") == i for e in enemies)] or [e["index"] for e in enemies]
                    target = max(pool, key=threat) if pool else None
                if target is not None:
                    params["target_index"] = target
                    _valid_now = card.get("valid_target_indices") or []
                    if _valid_now and target not in _valid_now:
                        why += "；原目标列表已过期，兜底切换最高威胁存活敌人"
            tname = ""
            if target is not None:
                tname = next((e["name"] for e in (combat.get("enemies") or []) if e.get("index") == target), "")
            return Decision("play_card", params,
                            f"战斗：打出【{card.get('name')}】{('→' + tname) if tname else ''}（{why}）；"
                            f"敌意图总伤{incoming}，我方{my_hp}血/{my_block}甲{danger_note}",
                            tags=[("play_card", card.get("card_id")),
                                  ("play_card_index", card.get("index"))], wait=0.6)
        if can_end:
            hand_desc = ",".join(f"{c.get('name')}{'✓' if c.get('playable') else '✗'}" for c in hand) or "空手"
            risk = "；警告：结束回合可能致死！" if combat.get("end_turn_will_kill_player") else ""
            skipped_by_energy = [c for c in hand if c.get("playable")
                                 and c.get("index") not in self._failed_this_turn
                                 and c.get("energy_cost", 0) > energy]
            energy_note = f"；{len(skipped_by_energy)}张可出牌因能量不足弃用" if skipped_by_energy else ""
            return Decision("end_turn", {},
                            f"战斗：评估后无值得出的牌（{hand_desc}），结束回合（敌意图总伤{incoming}，我方{my_hp}血/{my_block}甲）{risk}{energy_note}{danger_note}",
                            wait=1.2)
        return Decision(None, {}, "战斗：等待出牌时机", wait=0.7)

    def _score_play(self, card, enemies, incoming, my_block, round_no, pol,
                    my_hp: int = 9999, my_max_hp: int = 9999, stance: dict | None = None,
                    forced_kill: bool = False, reserve_for_block: bool = False,
                    min_blk_cost: int = 99, cur_energy: int = 0):
        """战斗中手牌评分。

        注意：战斗手牌载荷没有 card_type 字段（与奖励/商店载荷不同），
        必须从 dynamic_values / 文本 / target_type 推断牌的功能。

        生存权重：残血且敌意图可能致死时，压低攻击、抬高格挡——
        第 18 局 F22 致命战在意图 44~50 时仍连续输出不补防，直接阵亡。

        高危姿态：enemy_stance 对高死亡率组合收紧 atk/blk 权重与紧急线。
        自残代价：「失去X点生命」的攻击牌按当前血量扣分；致死回合里
        无法终结战斗的自残攻击 = 加速死亡，直接禁玩
        （第 29 局终局 9 血面对 28 点意图先打【御血术】自掉 2 血再阵亡）。

        能量预留：缺口未补、手里有格挡牌且「这张攻击 + 最便宜格挡 > 现有能量」
        时，非击杀攻击让路——先补防再输出，避免下一轮无甲吃整套意图。
        """
        dmg, block, hits = card_numbers(card)
        cost = card.get("energy_cost", 0)
        text = _text(card)
        aoe = ("所有敌人" in text or "all enemies" in text.lower()
               or (card.get("target_type") or "") == "AllEnemies")

        st = stance or {}
        hp_pct = my_hp / max(1, my_max_hp)
        gap = max(0, incoming - my_block)
        # 本回合就可能被打死：本地算术 + 服务端判定双保险。
        # gap>0 时以服务端为准——回合内已打出的格挡会让本地算术"提前脱险"，
        # 但服务端的 end_turn_will_kill_player 看到的是真实结算投影
        # （第 31 局 F7 终局：17 血对 18 意图，本地补 5 甲后误判安全改打打击，阵亡）
        # 惨胜防线（pyrrhic）：补防后剩余缺口虽不致死，却会把血量打穿到 12% 皮血线
        # （第 36 局 Boss 战：20 血对 27 意图，8 甲硬吃 19 剩 1 血，下回合必死）
        pyrrhic = gap > 0 and (my_hp - gap) <= 0.12 * my_max_hp
        lethal = gap >= my_hp or pyrrhic or (forced_kill and gap > 0)
        urgent = gap > 0 and hp_pct < float(st.get("urgent_hp_pct", 0.45))  # 慢性失血下的低血量状态
        if lethal:
            atk_damp, blk_boost = 0.55, 1.8
        elif urgent:
            atk_damp, blk_boost = 0.75, 1.4
        else:
            atk_damp, blk_boost = 1.0, 1.0
        atk_damp *= float(st.get("atk_mult", 1.0))
        blk_boost *= float(st.get("blk_mult", 1.0))
        # 多敌战斗格挡增值：意图来源越多战斗越长、漏伤越多（第 52~55 局四场
        # 致命战全是 2~3 体组合、滚动总意图 15~26），每点格挡的期望价值更高
        blk_boost *= 1.0 + min(0.24, 0.08 * max(0, len(enemies) - 1))

        m_self = re.search(r"失去\s*(\d+)\s*点?\s*生命|lose\s+(\d+)\s*(?:hp|health|life)", text, re.I)
        self_cost = int(next(g for g in m_self.groups() if g)) if m_self else 0
        floor_score = -50.0  # 生存模式禁玩线：叠加 card_value 加成后仍远低于阈值

        # --- 攻击牌（有伤害数值） ---
        if dmg > 0:
            total = dmg * hits
            if aoe:
                eff = sum(max(1, total - e.get("block", 0)) for e in enemies)
                killable = [e for e in enemies if max(1, total - e.get("block", 0)) >= e.get("current_hp", 9999)]
                score = eff * atk_damp + sum(
                    self._kill_bonus(e, sum((it.get("total_damage") or 0) for it in e.get("intents", [])),
                                     incoming, pol)
                    for e in killable)
                if reserve_for_block and not killable and cost + min_blk_cost > cur_energy:
                    score -= 8.0  # 给格挡让路：这点能量留着补缺口
                if lethal and not killable:
                    # 致死威胁下 AOE 若不能减员，等于放弃生存换数值
                    score = min(score, floor_score)
                if self_cost and lethal and len(killable) < len(enemies):
                    score = min(score, floor_score)
                if cost == 0:
                    score += pol["free_card_bonus"]
                return score, None, f"群体伤害≈{eff}"
            best_t, best_s, why, best_kill = None, -1.0, "", False
            _valid = (card.get("valid_target_indices") or []) if card.get("requires_target") else []
            # 合法目标优先；列表为空/过期（击杀后刷新延迟）时退化为全体敌人，
            # 保证评分反映真实期望而非被压成 -1 弃权（第 44 局 F6 实证）
            _pool = [e for e in enemies if not _valid or e.get("index") in _valid] or list(enemies)
            for e in _pool:
                eff = max(1, total - e.get("block", 0))
                threat = sum((it.get("total_damage") or 0) for it in e.get("intents", []))
                s = (eff + threat * 0.3) * atk_damp
                killed = eff >= e.get("current_hp", 9999)
                if killed:
                    s += self._kill_bonus(e, threat, incoming, pol)
                if best_t is None or s > best_s:
                    best_t, best_s, best_kill = e.get("index"), s, killed
                    why = f"可击杀{e['name']}" if killed else f"单体伤害≈{eff}"
            # 致死回合里"打不死人的大伤害"是自杀牌：
            # 第 28 局 Boss 战终盘 1 血面对 11 点意图，重锤(42伤)压过防御(5甲)
            # 抢走全部能量，结果无甲吃刀阵亡——非击杀攻击必须给格挡让路。
            if lethal and not best_kill:
                best_s = min(best_s, floor_score)
            elif reserve_for_block and not best_kill and cost + min_blk_cost > cur_energy:
                best_s -= 8.0  # 能量预留：先补防再输出（第 36 批 F17 Boss 战教训）
            elif self_cost:
                if best_kill and len(enemies) == 1:
                    pass  # 击杀最后一个敌人直接终局，自残值得
                elif lethal:
                    best_s = min(best_s, floor_score)
                else:
                    best_s -= self_cost * (1.5 + 3.0 * (1.0 - hp_pct))  # 血越少自残越贵
            if cost == 0:
                best_s += pol["free_card_bonus"]
            return best_s, best_t, why

        # --- 防御/技能牌（有格挡数值） ---
        if block > 0:
            useful = min(block, max(0, incoming - my_block))
            score = (useful * 1.05 * pol["block_safety"] + (block - useful) * 0.2) * blk_boost
            why = f"格挡{block}"
            dr = draw_amount(card)
            if dr:
                score += dr * 1.5
                why += f"/抽牌{dr}"
            if cost == 0:
                score += pol["free_card_bonus"]
            return score, None, why

        # --- 功能牌（抽牌/回能/特殊效果） ---
        dr = draw_amount(card)
        if dr > 0 or "能量" in text or "energy" in text.lower():
            score = 2.0 + dr * 1.5
            if lethal:
                score = min(score, floor_score)  # 致死回合抽牌/回能救不了命
            if cost == 0:
                score += pol["free_card_bonus"]
            return score, None, f"功能牌（抽牌{dr}/回能）"

        # --- 无直接数值：按能力牌处理，开局回合优先 ---
        score = (pol["power_round_bonus"] if round_no <= 2 else 1.5)
        if lethal:
            score = min(score, floor_score)  # 致死回合上能力=放弃格挡能量
        if cost == 0:
            score += pol["free_card_bonus"]
        return score, None, f"能力/增益牌（第{round_no}回合）"

    def _kill_bonus(self, enemy: dict, threat: float, incoming: float, pol: dict) -> float:
        """击杀奖励按「消除的威胁占比」折算，并对已证实的重生召唤物强衰减。

        第 52~53 局实证：利齿之眼每回合被【可击杀】斩首又复活，kill_bonus=12
        吸引引擎单场追杀召唤物 10+ 次，雾菇本体意图 8→23 滚雪球把 80 血磨穿——
        击杀的价值在消灭未来的意图来源，目标威胁占比越低越不值钱；同一敌人
        本场已被预测击杀 ≥2 次仍存活即为重生体（阈值 2 可吸收偶发 409/未命中
        的误计），奖励降至 1/4。空档回合（intent 全 0）按全额计：抢在召唤物
        产出意图之前清场仍有价值。
        """
        kid = enemy.get("enemy_id") or enemy.get("name") or ""
        mult = 0.25 if self._combat_kills.get(kid, 0) >= 2 else 1.0
        share = 1.0 if incoming <= 0 else min(1.0, max(0.0, threat) / incoming)
        return pol["kill_bonus"] * (0.4 + 0.6 * share) * mult

    def _maybe_potion(self, state, ctx, hard: bool, premium: bool = False):
        run = state.get("run") or {}
        pol = self.know.policy
        if pol.get("potion_hard_only") and not hard:
            return None
        combat = state.get("combat") or {}
        enemies = [e for e in combat.get("enemies", []) if e.get("is_alive") and e.get("is_hittable")]
        for p in run.get("potions", []):
            if not p.get("occupied") or not p.get("can_use"):
                continue
            if p["index"] in self._potion_tried:
                continue  # 尝试过但没生效（如时机不合法），本场战斗不再重复
            desc = (p.get("description") or "")
            name = p.get("name") or ""
            usage = (p.get("usage") or "").lower()
            # combat/战斗/anytime 都允许在战斗中使用（第 30 局敏捷药水疑因
            # usage 分类不符被整场跳过，带进坟墓）
            if usage and not any(k in usage for k in ("combat", "战斗", "anytime", "任意", "any")):
                continue
            needs_target = bool(p.get("requires_target"))
            target = None
            if needs_target:
                valid = p.get("valid_target_indices") or []
                target = next((e["index"] for e in enemies if e["index"] in valid), None)
                if target is None:
                    continue
            desc_l = desc.lower()
            # 攻击类（伤害/攻击）与增益类（力量/敏捷/能量/抽牌）战斗药水都应在硬仗投入使用：
            # 第 28 局囤力量/敏捷/迅捷三瓶增益药水全程未用（含死局战）带进坟墓
            is_damage = "伤害" in desc or "damage" in desc_l or "攻击" in desc
            is_buff = ("力量" in desc or "strength" in desc_l or "敏捷" in desc
                       or "dexterity" in desc_l or "能量" in desc or "energy" in desc_l
                       or "抽" in desc or "draw" in desc_l or "速度" in desc or "speed" in desc_l)
            # 增益药水的价值在长战/硬仗兑现：普通战（哪怕低血放血）不构成使用理由，
            # 跳过且不计入 tried——本场若恶化成致死局仍可立即启用
            if is_buff and not premium:
                continue
            if (is_damage or is_buff) and enemies:
                self._potion_tried.add(p["index"])
                params = {"option_index": p["index"]}
                if target is not None:
                    params["target_index"] = target
                kind = "攻击" if is_damage else "增益"
                return Decision("use_potion", params, f"战斗：硬仗使用{kind}药水【{name}】",
                                tags=[("use_potion", p.get("potion_id"))], wait=0.6)
            if ("格挡" in desc or "生命" in desc or "回复" in desc or "block" in desc.lower() or "heal" in desc.lower()):
                if (state.get("combat", {}).get("player", {}).get("current_hp", 1)
                        < 0.35 * state.get("combat", {}).get("player", {}).get("max_hp", 1)):
                    self._potion_tried.add(p["index"])
                    return Decision("use_potion", {"option_index": p["index"]},
                                    f"战斗：低血量使用防御/回复药水【{name}】",
                                    tags=[("use_potion", p.get("potion_id"))], wait=0.6)
            # 兜底：硬仗（致死/精英/低血放血）里无法分类的药水也值得一试——
            # 用错药水的代价远小于带进坟墓（第 30~32 局三连教训）。
            # 仅限 premium 场合：普通战里不可分类的药水同样保留（防绕过增益保留策略）
            cb_player = (state.get("combat") or {}).get("player") or {}
            cb_hp = cb_player.get("current_hp", 1)
            cb_max = max(1, cb_player.get("max_hp", 1))
            cb_incoming = sum((it.get("total_damage") or 0)
                              for e in enemies for it in (e.get("intents") or []))
            if (premium and enemies and cb_incoming > cb_player.get("block", 0)
                    and cb_hp <= 0.5 * cb_max):
                self._potion_tried.add(p["index"])
                params = {"option_index": p["index"]}
                if target is not None:
                    params["target_index"] = target
                return Decision("use_potion", params,
                                f"战斗：硬仗兜底使用药水【{name}】（描述无法分类，宁滥勿囤）",
                                tags=[("use_potion", p.get("potion_id"))], wait=0.6)
        return None

    # ------------------------------------------------------------------
    # rewards / selection / bundles / chest / capstone
    # ------------------------------------------------------------------

    def eval_reward_card(self, card: dict, deck: list[dict]) -> float:
        pol = self.know.policy
        dmg, block, hits = card_numbers(card)
        cost = card.get("energy_cost", 0)
        value = 0.0

        # --- 卡组形态上下文 ---
        n_attack = sum(1 for c in deck if is_attack(c)) if deck else 0
        ratio = n_attack / len(deck) if deck else 0.45  # 无卡组上下文（升级/删除）按中性占比
        n_block = sum(1 for c in deck
                      if (is_skill(c) and card_numbers(c)[1] > 0)
                      or "DEFEND" in (c.get("card_id") or "").upper()) if deck else 0
        good_cards = sum(1 for c in deck
                         if not ("STRIKE" in (c.get("card_id") or "").upper()
                                 or "DEFEND" in (c.get("card_id") or "").upper()
                                 or is_bad_card(c))) if deck else 0

        def _is_aoe(c: dict) -> bool:
            t = _text(c)
            return ("所有敌人" in t or "all enemies" in t.lower()
                    or (c.get("target_type") or "") == "AllEnemies")

        n_aoe = sum(1 for c in deck if _is_aoe(c)) if deck else 0

        # 攻击牌边际价值乘法衰减（固定 -2.5 挡不住基础分 10+ 的攻击牌，
        # 第 18 局仍拿了 24 张近乎全攻的牌）：占比越高衰减越狠
        if is_attack(card):
            atk_scale = clamp(1.3 - 1.4 * ratio, 0.15, 1.2)
            value += (dmg * hits * 1.0 + (1.0 if cost <= 1 else 0.0)) * atk_scale
            if ratio < 0.35:
                value += 1.5  # 输出不足时额外鼓励补攻击
            # AoE 定价随存量递减（第 56~57 局复盘）：致死榜前列全是多体/召唤组合
            # （第 57 局 16 张入组牌 0 张群体攻击，双子 Boss 七回合斩杀失败），
            # 首张群体攻击是结构性稀缺资源(+3)；已有 1 张仍增值(+2)；
            # ≥2 张后边际价值快速回落(+0.5)，名额让给其他维度
            if _is_aoe(card):
                value += 3.0 if n_aoe == 0 else (2.0 if n_aoe == 1 else 0.5)
        elif is_skill(card):
            value += block * 0.8 + draw_amount(card) * 1.5
            # 格挡来源绝对数稀缺（初始 4 张防牌很快被稀释，旧占比判定 <20% 几乎不触发）
            if block > 0 and deck and n_block < pol.get("min_block_cards", 5):
                value += 1.5
        elif is_power(card):
            value += 5.0
        elif is_bad_card(card):
            value -= 10.0
        value += pol["rarity_bonus"].get(card.get("rarity", ""), 0.0)
        # 未升级基础牌不提升卡组强度：出现在卡牌奖励里等于浪费名额
        # （第 33 局 F2 把【打击】当奖励拿走）
        _cid = (card.get("card_id") or "").upper()
        if not card.get("upgraded") and (_cid.startswith("STRIKE_") or _cid.startswith("DEFEND_")):
            value -= 4.0
        # 自残牌在慢性失血环境下额外惩罚（BREAKTHROUGH/HEMOKINESIS 类）
        if re.search(r"失去\s*\d+\s*点?生命|lose\s+\d+\s*(?:hp|health|life)", _text(card), re.I):
            value -= 2.0
        if cost >= 3:
            value -= 1.0
        # 卡组规模软上限：非基础牌超出后逐张贬值——膨胀稀释抽牌质量是战斗拖长的根因
        if deck:
            overflow = good_cards - pol.get("deck_soft_cap", 20)
            if overflow > 0:
                value -= overflow * pol.get("deck_overflow_penalty", 0.9)
        cid = (card.get("card_id") or "").upper()
        # 奖励端不拿未升级的基础打/防牌（生涯从奖励拾取 STRIKE_IRONCLAD×10 次）。
        # 删除/变化场景里该惩罚反而抬高其"最该删"排序，语义自洽
        if not card.get("upgraded") and ("STRIKE" in cid or "DEFEND" in cid):
            value -= 4.0
        # 统计实锤的低价值牌（样本≥4 且场均显著低于全局均值）硬性回避：
        # EXPECT_A_FIGHT(6.6分/5局)、BASH(7.2分/6局) 的 learned value ≈ -2.8，
        # 压不住格挡/抽牌启发式的 12+ 基础分，必须用大额惩罚对冲
        if self.know.card_is_proven_bad(card.get("card_id", "")):
            value -= 12.0
        value += self.know.card_value(card.get("card_id", ""))
        self.know.commit_card_seen(card.get("card_id", ""))
        return value

    def _reward(self, state: dict, ctx) -> Decision:
        r = state.get("reward") or {}
        actions = state.get("available_actions", [])
        run = state.get("run") or {}
        deck = run.get("deck", [])
        pol = self.know.policy
        floor = run.get("floor", 0)

        # 换层/换屏时重置"已尝试"记忆
        if floor != self._reward_floor:
            self._reward_floor = floor
            self._reward_tried = set()

        # card choice pending?
        cards = r.get("card_options", [])
        if r.get("pending_card_choice") and cards:
            best, best_v = None, -1e9
            vals = []
            for c in cards:
                v = self.eval_reward_card(c, deck)
                vals.append(f"{c.get('name')}={v:.1f}")
                if v > best_v:
                    best, best_v = c, v
            if best_v >= pol["card_pick_threshold"] and "choose_reward_card" in actions:
                return Decision("choose_reward_card", {"option_index": best["index"]},
                                f"奖励选牌：【{best.get('name')}】（价值 {best_v:.1f}）；候选：{', '.join(vals)}",
                                tags=[("card_pick", best.get("card_id"))], wait=0.8)
            if "skip_reward_cards" in actions:
                return Decision("skip_reward_cards", {},
                                f"奖励选牌：全部跳过（最高价值 {best_v:.1f} < 阈值 {pol['card_pick_threshold']}）；候选：{', '.join(vals)}",
                                wait=0.8)

        # claim simple rewards (gold / relic / potion)；失败过的（如药水栏满）不再重试
        for opt in r.get("rewards", []):
            if not opt.get("claimable"):
                continue
            rtype = opt.get("reward_type", "")
            key = (rtype, opt.get("description", ""))
            if key in self._reward_tried:
                continue
            if rtype in ("Gold", "Relic", "Potion") and "claim_reward" in actions:
                if rtype == "Potion":
                    pots = run.get("potions", [])
                    if pots and all(p.get("occupied") for p in pots):
                        continue  # 药水栏已满：领取必失败，直接放弃避免重试空转
                self._reward_tried.add(key)
                tags = [("relic_pick", opt.get("description", ""))] if rtype == "Relic" else []
                return Decision("claim_reward", {"option_index": opt["index"]},
                                f"领取奖励：{opt.get('description')}", tags=tags, wait=0.7)
            if rtype in ("Card", "SpecialCard") and "claim_reward" in actions:
                self._reward_tried.add(key)
                return Decision("claim_reward", {"option_index": opt["index"]},
                                f"打开卡牌奖励：{opt.get('description')}", wait=0.7)

        # 仍有未尝试但领取失败的奖励（如药水栏满）→ 放弃它们直接前进
        skipped = [k[1] for k in self._reward_tried
                   if any(o.get("claimable") and o.get("reward_type") == k[0] and o.get("description") == k[1]
                          for o in r.get("rewards", []))]
        note = f"（放弃无法领取的：{'、'.join(skipped)}）" if skipped else ""
        if r.get("can_proceed") and "proceed" in actions:
            return Decision("proceed", {}, f"奖励结算完毕{note}，继续前进", wait=1.0)
        if "collect_rewards_and_proceed" in actions:
            return Decision("collect_rewards_and_proceed", {}, f"一键收取奖励并继续{note}", wait=1.0)
        return Decision(None, {}, "奖励界面：等待可操作", wait=0.8)

    def _card_selection(self, state: dict, ctx) -> Decision:
        sel = state.get("selection") or {}
        actions = state.get("available_actions", [])
        cards = sel.get("cards", [])
        kind = (sel.get("kind") or "").lower()
        prompt = sel.get("prompt") or ""
        if not cards:
            return Decision(None, {}, f"选牌界面（{kind}）：无候选，等待", wait=0.8)

        # 屏幕身份 + 防重复点击记忆（重复点同一张卡可能反选/空转）
        floor_no = (state.get("run") or {}).get("floor", 0)
        screen_key = (floor_no, kind, prompt, len(cards))
        if screen_key != self._sel_key:
            self._sel_key = screen_key
            self._sel_tried = set()

        # 删牌语义判定：关键词（remove/移除/删除）+ 商店删牌动作握手双保险。
        # 第 43/44 局实证：界面 kind/prompt 不含已知关键词时，删牌屏被当成通用
        # 拿牌屏按"最高价值"点选，把余烬+/上勾拳当垃圾删了——发起方知道上下文，
        # 显式握手优先于文案猜测
        blob = f"{kind} {prompt}".lower()
        removing = ("remove" in blob or "移除" in blob or "删除" in blob
                    or self._removal_pending_floor == floor_no)
        if self._removal_pending_floor == floor_no:
            self._removal_pending_floor = -1  # 握手消费，防残留误触发

        # 已达选择数量且可确认 → 先确认（升级/删除等分支也必须走这里，否则永远循环）
        min_sel = sel.get("min_select", 1)
        if (sel.get("can_confirm") and sel.get("selected_count", 0) >= min_sel
                and "confirm_selection" in actions):
            return Decision("confirm_selection", {}, f"选牌界面（{kind}）：已选 {sel.get('selected_count')} 张，确认",
                            wait=0.9)

        upgrading = "upgrade" in kind or "升级" in prompt or "锻造" in prompt
        transforming = "transform" in kind or "变化" in prompt

        candidates = [c for c in cards if c["index"] not in self._sel_tried] or cards

        if removing or transforming:
            def badness(c):
                t = card_type(c).lower()
                if t == "curse":
                    return 100
                if t == "status":
                    return 90
                cid = (c.get("card_id") or "").upper()
                if "STRIKE" in cid and not c.get("upgraded"):
                    return 50
                return -self.eval_reward_card(c, [])
            pick = max(candidates, key=badness)
            verb = "删除" if removing else "变化"
            tag = "card_remove" if removing else "card_transform"
            reason = f"{verb}卡牌：【{pick.get('name')}】（最无价值）"
        elif upgrading:
            best, best_v = None, -1e9
            for c in candidates:
                if c.get("upgraded"):
                    continue
                v = self.eval_reward_card(c, []) + (2.0 if is_attack(c) else 0.0)
                if v > best_v:
                    best, best_v = c, v
            if best is None:
                best = candidates[0]
            pick = best
            tag = "card_upgrade"
            reason = f"升级卡牌：【{pick.get('name')}】"
        else:
            # 必须用真实卡组上下文评估：第 34 局经此路径连拿 7 张全攻牌、
            # 第 33 局拿进基础【打击】——空卡组评估时攻击占比恒为中性 0.45，
            # 攻击乘法衰减与格挡稀缺增值双双失效
            deck = (state.get("run") or {}).get("deck", [])
            scored = sorted(((self.eval_reward_card(c, deck), c) for c in candidates),
                            key=lambda t: -t[0])
            best_v, pick = scored[0]
            # 跳过守卫（第 56 局实证）：经"打开卡牌奖励"进入的本屏没有阈值判断，
            # 全负候选（未升级基础牌 -3.9/-6.2）也被硬塞进卡组稀释质量——
            # REWARD 端同场景会跳过，同一决策的两个入口必须共享同一套门槛。
            # 服务端提供 skip 动作且全员低于阈值 → 放弃；无跳过动作（强制选择屏）
            # 则退回最小恶选择
            if (best_v < self.know.policy["card_pick_threshold"]
                    and "skip_reward_cards" in actions):
                return Decision("skip_reward_cards", {},
                                f"选牌界面：全部低于拾取阈值（最高 {best_v:.1f} < "
                                f"{self.know.policy['card_pick_threshold']}），跳过不拿",
                                tags=[("card_skip", None)], wait=0.8)
            tag = "card_pick"
            detail = " / ".join(f"{c.get('name')}={v:.1f}" for v, c in scored)
            reason = f"选择卡牌：【{pick.get('name')}】（价值 {best_v:.1f}）；候选：{detail}"

        self._sel_tried.add(pick["index"])
        return Decision("select_deck_card", {"option_index": pick["index"]},
                        reason, tags=[(tag, pick.get("card_id"))], wait=0.8)

    def _chest(self, state: dict, ctx) -> Decision:
        chest = state.get("chest") or {}
        actions = state.get("available_actions", [])
        if not chest.get("is_opened") and "open_chest" in actions:
            return Decision("open_chest", {}, "宝箱：开启", wait=1.0)
        relics = chest.get("relic_options", [])
        if relics and not chest.get("has_relic_been_claimed") and "choose_treasure_relic" in actions:
            best = max(relics, key=lambda r: self.know.relic_value(r.get("relic_id", "")))
            return Decision("choose_treasure_relic", {"option_index": best["index"]},
                            f"宝箱：选择遗物【{best.get('name')}】",
                            tags=[("relic_pick", best.get("relic_id"))], wait=0.9)
        if "proceed" in actions:
            return Decision("proceed", {}, "宝箱：离开", wait=1.0)
        return Decision(None, {}, "宝箱：等待", wait=0.8)

    # ------------------------------------------------------------------
    # shop / rest
    # ------------------------------------------------------------------

    def _shop(self, state: dict, ctx) -> Decision:
        shop = state.get("shop") or {}
        run = state.get("run") or {}
        actions = state.get("available_actions", [])
        gold = run.get("gold", 0)
        deck = run.get("deck", [])
        pol = self.know.policy
        floor = run.get("floor", 0)

        if not shop.get("is_open"):
            if self._shop_done_floor == floor:
                if "proceed" in actions:
                    return Decision("proceed", {}, "商店：本店已评估过，离开", wait=1.0)
            elif shop.get("can_open") and "open_shop_inventory" in actions:
                return Decision("open_shop_inventory", {}, "商店：打开货架", wait=0.9)
            if "proceed" in actions:
                return Decision("proceed", {}, "商店：离开", wait=1.0)
            return Decision(None, {}, "商店：等待", wait=0.8)

        # card removal first if we have junk
        removal = shop.get("card_removal")
        if (pol.get("removal_enabled") and removal and removal.get("available") and not removal.get("used")
                and removal.get("enough_gold") and gold - removal.get("price", 999) >= pol["removal_gold_reserve"]):
            junk = [c for c in deck if is_bad_card(c)
                    or ("STRIKE" in (c.get("card_id") or "").upper() and not c.get("upgraded"))]
            if junk and "remove_card_at_shop" in actions:
                # 握手：下一个 CARD_SELECTION 屏就是删牌选择——不能依赖界面文案猜语义
                # （第 43/44 局实证：识别失败落入通用拿牌分支，付费删掉了余烬+/上勾拳
                #  两张全队最强的牌）
                self._removal_pending_floor = floor
                return Decision("remove_card_at_shop", {},
                                f"商店：付费删牌（预留 {pol['removal_gold_reserve']} 金后仍充足）",
                                tags=[("shop_remove", None)], wait=0.9)

        best_action, best_score, best_reason, best_tags = None, -1e9, "", []
        for c in shop.get("cards", []):
            if not c.get("is_stocked") or not c.get("enough_gold"):
                continue
            v = self.eval_reward_card(c, deck) - c.get("price", 0) / 120.0
            if v > best_score:
                best_action = ("buy_card", c["index"])
                best_score = v
                best_reason = f"购买卡牌【{c.get('name')}】（{c.get('price')}金，价值{v:.1f}）"
                best_tags = [("card_pick", c.get("card_id")), ("shop_buy_card", c.get("card_id"))]
        for r in shop.get("relics", []):
            if not r.get("is_stocked") or not r.get("enough_gold"):
                continue
            v = 3.0 + self.know.relic_value(r.get("relic_id", "")) - r.get("price", 0) / 120.0
            if v > best_score:
                best_action = ("buy_relic", r["index"])
                best_score = v
                best_reason = f"购买遗物【{r.get('name')}】（{r.get('price')}金，价值{v:.1f}）"
                best_tags = [("relic_pick", r.get("relic_id")), ("shop_buy_relic", r.get("relic_id"))]
        if best_action and best_score > pol["shop_relic_threshold"]:
            action, idx = best_action
            if action in actions:
                return Decision(action, {"option_index": idx}, f"商店：{best_reason}", tags=best_tags, wait=0.9)

        if shop.get("can_close") and "close_shop_inventory" in actions:
            self._shop_done_floor = floor  # 标记本店已评估，防止 开→关→开 死循环
            return Decision("close_shop_inventory", {}, "商店：货架无值得购买，关闭", wait=0.8)
        if "proceed" in actions:
            return Decision("proceed", {}, "商店：离开", wait=1.0)
        return Decision(None, {}, "商店：等待", wait=0.8)

    def _rest(self, state: dict, ctx) -> Decision:
        rest = state.get("rest") or {}
        run = state.get("run") or {}
        actions = state.get("available_actions", [])
        options = [o for o in rest.get("options", []) if o.get("is_enabled")]
        if not options:
            if "proceed" in actions:
                return Decision("proceed", {}, "篝火：无可选项目，离开", wait=1.0)
            return Decision(None, {}, "篝火：等待选项", wait=0.8)

        hp_pct = run.get("current_hp", 1) / max(1, run.get("max_hp", 1))
        heal = next((o for o in options if o.get("option_id", "").upper() == "HEAL"), None)
        smith = next((o for o in options if "SMITH" in o.get("option_id", "").upper()), None)
        deck = run.get("deck", [])
        upgradable = [c for c in deck if not c.get("upgraded")]
        heal_frac = self.know.policy.get("rest_heal_fraction", 0.30)
        pol = self.know.policy

        # Boss 前夜篝火：回血优先于锻造，除非血量已接近满（第 48 局复盘实证）。
        # 常规的"回血将溢出→改锻造"分支在此不适用——溢出的几点血量远低于
        # Boss 预期战损（先验 45+），能多回一点是一点
        if getattr(ctx, "rest_before_boss", False) and heal is not None and hp_pct < 0.95:
            return Decision("choose_rest_option", {"option_index": heal["index"]},
                            f"篝火：Boss 前夜优先回血（当前 {hp_pct:.0%}，Boss 预期战损过半，锻造不救命）",
                            tags=[("rest", "heal")], wait=1.2)

        # 锻造区间：血量 ≥ smith_min_hp_pct 即可锻造。旧逻辑回血阈值 70% 过高，
        # 第 28 局连续两个篝火都在 46%/48% 回血、整局零锻造，卡组停在基础形态
        smith_ok = smith is not None and bool(upgradable)
        heal_line = float(pol.get("smith_min_hp_pct", pol["rest_heal_threshold"]))
        if heal and (hp_pct < heal_line or not smith_ok):
            # 回血将溢出（接近回满）且仍有可升级卡：改锻造，不浪费篝火
            if smith_ok and hp_pct + heal_frac >= 0.97:
                return Decision("choose_rest_option", {"option_index": smith["index"]},
                                f"篝火：回血将溢出（{hp_pct:.0%}+{heal_frac:.0%}≥97%），改为锻造升级",
                                tags=[("rest", "smith")], wait=1.2)
            return Decision("choose_rest_option", {"option_index": heal["index"]},
                            f"篝火：休息回血（当前 {hp_pct:.0%} < {heal_line:.0%}）",
                            tags=[("rest", "heal")], wait=1.2)
        if smith_ok:
            return Decision("choose_rest_option", {"option_index": smith["index"]},
                            f"篝火：锻造升级（血量 {hp_pct:.0%} ≥ 安全线 {heal_line:.0%}，升级降低后续战损）",
                            tags=[("rest", "smith")], wait=1.2)
        if heal:
            return Decision("choose_rest_option", {"option_index": heal["index"]},
                            f"篝火：休息回血（无升级目标，当前 {hp_pct:.0%}）",
                            tags=[("rest", "heal")], wait=1.2)
        pick = options[0]
        return Decision("choose_rest_option", {"option_index": pick["index"]},
                        f"篝火：选择 {pick.get('title')}", tags=[("rest", pick.get("option_id"))], wait=1.0)

    # ------------------------------------------------------------------
    # event / modal / game over / unknown
    # ------------------------------------------------------------------

    def _event(self, state: dict, ctx) -> Decision:
        ev = state.get("event") or {}
        actions = state.get("available_actions", [])
        options = ev.get("options", [])
        if not options:
            return Decision(None, {}, "事件：无选项，等待", wait=0.8)
        event_id = ev.get("event_id", "unknown")

        if ev.get("is_finished"):
            proceed = next((o for o in options if o.get("is_proceed")), None)
            if proceed and "choose_event_option" in actions:
                return Decision("choose_event_option", {"option_index": proceed["index"]},
                                "事件：已结束，继续", wait=1.0)

        candidates = [o for o in options if not o.get("is_locked") and not o.get("will_kill_player")]
        if not candidates:
            candidates = [o for o in options if not o.get("is_locked")]
        if not candidates:
            return Decision(None, {}, "事件：全部锁定，等待", wait=0.8)

        pol = self.know.policy

        def _norm_key(o) -> str:
            raw = o.get("text_key") or o.get("title") or str(o["index"])
            return re.sub(r"\s+", "", str(raw))

        def _lookup(ev_id: str, key: str) -> tuple[float, int]:
            # 读取侧聚合：精确键优先，其次跨页尾键（.options.X）。
            # 第 43 局实证：真理石板四页各自 n=0、"继 续 解 读"空格变体再分裂，
            # 探索把每一页都当新选项重试，单事件放血 -39——同一语义的经验必须
            # 跨页共享才能凑到最小样本数；写入侧键同步去空白，历史数据无需迁移
            tail = key.split(".")[-1]
            best_v, best_n = 0.0, 0
            for k in dict.fromkeys([key, tail]):
                v, n = self.know.event_option_value(ev_id, k)
                if n > best_n:
                    best_v, best_n = v, n
            return best_v, best_n

        scored = []
        for o in candidates:
            key = _norm_key(o)
            v, n = _lookup(event_id, key)
            scored.append((v, n, key, o))
        # epsilon exploration among under-sampled options
        # 已知负收益（价值 ≤ -5，如吃过大亏的选项）不再浪费探索次数；
        # 探索只在真正欠采样的选项里挑
        if self.rng.random() < pol["exploration_rate"]:
            fresh = [s for s in scored if s[1] < 3 and s[0] > -5.0]
            if fresh:
                v, n, key, o = self.rng.choice(fresh)
                return Decision("choose_event_option", {"option_index": o["index"]},
                                f"事件【{ev.get('title')}】：探索未知选项「{o.get('title')}」（探索率 {pol['exploration_rate']:.2f}）",
                                tags=[("event_choice", event_id, key)], wait=1.0)
        # 有实证收益（>0）时：价值优先，平值按样本数优先（石炉加湿器教训：
        # 经验多比原始顺序可信）。全零平值反转（第 56~57 局实证）：事件结算只记
        # 即时 hp/gold，祝福类选项长期记 0——按样本最大排序会把选择永久锁死在
        # 首个采样过的选项上，「涅奥的苦痛」n=8 连续重选，营养牡蛎(+11/次)式的
        # 正收益选项永远等不到被发现。并列 0 时改选样本最少者主动分散采样；
        # 任一选项显现非零收益后自动恢复"价值→样本"贪心。
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        if scored[0][0] > 0.0:
            v, n, key, o = scored[0]
        else:
            pool = [s for s in scored if s[0] == scored[0][0]]
            v, n, key, o = min(pool, key=lambda s: s[1])
        lines = " / ".join(f"{s[3].get('title')}={s[0]:.1f}(n={s[1]})" for s in scored)
        return Decision("choose_event_option", {"option_index": o["index"]},
                        f"事件【{ev.get('title')}】：选择「{o.get('title')}」（经验价值 {v:.1f}）；{lines}",
                        tags=[("event_choice", event_id, key)], wait=1.0)

    def _bundle(self, state: dict, ctx) -> Decision:
        """开局祝福/特殊界面的卡牌包选择（BUNDLE_SELECTION）。"""
        bundles = state.get("bundles") or []
        actions = state.get("available_actions", [])
        deck = (state.get("run") or {}).get("deck", [])
        if bundles and "choose_bundle" in actions:
            best, best_v, detail = None, -1e9, []
            for b in bundles:
                v = sum(self.eval_reward_card(c, deck) for c in b.get("cards", []))
                names = "、".join(c.get("name", "?") for c in b.get("cards", []))
                detail.append(f"包{b['index']}[{names}]={v:.1f}")
                if v > best_v:
                    best, best_v = b, v
            return Decision("choose_bundle", {"option_index": best["index"]},
                            f"卡包选择：选包{best['index']}（总价值 {best_v:.1f}）；{' / '.join(detail)}",
                            tags=[("bundle_pick", best["index"])]
                                 + [("card_pick", c.get("card_id")) for c in best.get("cards", []) if c.get("card_id")],
                            wait=0.8)
        if "confirm_bundle" in actions:
            return Decision("confirm_bundle", {}, "卡包选择：确认", wait=0.8)
        return Decision(None, {}, "卡包选择：等待", wait=0.7)

    def _capstone(self, state: dict, ctx) -> Decision:
        cap = state.get("capstone") or {}
        options = cap.get("options", [])
        actions = state.get("available_actions", [])
        if options and "choose_capstone_option" in actions:
            # 暂无语义学习数据，默认选第一个（通常为继续/前进类）
            pick = options[0]
            return Decision("choose_capstone_option", {"option_index": pick.get("index", pick.get("i", 0))},
                            f"顶石界面：选择「{pick.get('line')}」",
                            tags=[("capstone", pick.get("line"))], wait=1.0)
        return Decision(None, {}, "顶石界面：等待", wait=0.7)

    def _modal(self, state: dict, ctx) -> Decision:
        modal = state.get("modal") or {}
        actions = state.get("available_actions", [])
        if modal.get("can_confirm") and "confirm_modal" in actions:
            return Decision("confirm_modal", {}, f"弹窗：确认（{modal.get('type_name')}）", wait=0.7)
        if modal.get("can_dismiss") and "dismiss_modal" in actions:
            return Decision("dismiss_modal", {}, f"弹窗：关闭（{modal.get('type_name')}）", wait=0.7)
        return Decision(None, {}, "弹窗：等待", wait=0.6)

    def _game_over(self, state: dict, ctx) -> Decision:
        go = state.get("game_over") or {}
        actions = state.get("available_actions", [])
        victory = bool(go.get("is_victory"))
        if not ctx.run_finalized:
            ctx.finalize_requested = True  # agent.py performs reflection once
            return Decision(None, {}, f"对局结束：{'胜利' if victory else '失败'}（层数 {go.get('floor')}），正在总结复盘…", wait=0.5)
        if go.get("can_continue") and "continue_run" in actions:
            return Decision("continue_run", {}, "结算：继续（进入下一阶段）", wait=1.5)
        if go.get("can_return_to_main_menu") and "return_to_main_menu" in actions:
            ctx.check_timeline = True  # 回主菜单后优先检查时间线可解锁项
            return Decision("return_to_main_menu", {}, "结算：返回主菜单，备战下一局", wait=1.5)
        if "proceed" in actions:
            return Decision("proceed", {}, "结算：继续", wait=1.2)
        return Decision(None, {}, "结算：等待", wait=0.8)

    def _unknown(self, state: dict, ctx) -> Decision:
        # 按载荷兜底路由，防新屏幕名漏网
        if state.get("bundles"):
            return self._bundle(state, ctx)
        if state.get("capstone"):
            return self._capstone(state, ctx)
        actions = state.get("available_actions", [])
        if "choose_bundle" in actions:
            return self._bundle(state, ctx)
        if "choose_capstone_option" in actions:
            return self._capstone(state, ctx)
        if "confirm_modal" in actions:
            return Decision("confirm_modal", {}, "未知界面：尝试确认弹窗", wait=0.7)
        if "proceed" in actions:
            return Decision("proceed", {}, "未知界面：尝试继续", wait=0.8)
        return Decision(None, {}, f"未知界面（{state.get('screen')}）：观察中", wait=1.0)
