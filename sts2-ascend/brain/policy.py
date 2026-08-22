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
        self._failed_this_turn: set = set()  # card_ids that failed to play this turn
        self._potion_combat = None  # combat instance identity for potion blacklist
        self._potion_tried: set = set()      # potion indices already attempted this combat

    def note_action_failed(self, action: str, tags: list) -> None:
        """agent 在执行失败时回调：本回合内不再尝试这张牌（防 409 重试刷屏）。"""
        if action == "play_card":
            for t in tags or []:
                if t[0] == "play_card" and t[1]:
                    self._failed_this_turn.add(t[1])

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
            return handler(state, ctx)
        except Exception as exc:  # never crash the loop on a policy bug
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
            slots = [s for s in timeline.get("slots", []) if s.get("is_actionable")]
            if slots:
                return Decision("choose_timeline_epoch", {"option_index": slots[0]["index"]},
                                f"主菜单：选择时间线节点 {slots[0].get('title')}", wait=0.8)
        if "continue_run" in actions:
            return Decision("continue_run", {}, "主菜单：检测到进行中的存档，继续对局", wait=1.2)
        if "open_character_select" in actions:
            return Decision("open_character_select", {}, "主菜单：开启新的一局（标准模式）", wait=1.2)
        return Decision(None, {}, "主菜单：无可用动作，等待", wait=1.0)

    def _timeline(self, state: dict, ctx) -> Decision:
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
            return clamp(1.0 + (avg - glob) / 50.0, 0.5, 1.5)

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
            elif nt == "Shop":
                if gold >= pol["shop_min_gold"]:
                    return 1.4, f"金币{gold}足够"
                return 0.6, "金币不足"
            elif nt == "Monster":
                if floor <= 8:
                    return 1.25, "前期需要战斗积累卡牌"
            return 1.0, ""

        # ---- 全路径规划：从每个候选节点枚举到 Boss 行的所有路径，
        # 按历史场均掉血先验模拟沿途血量演进，投影死亡/低血进 Boss 重罚。
        # 解决贪心逐格选路的盲区：早期分支把后续逼进"唯一可选的精英"。----
        # 幕数缩放：先验来自一幕场均，二/三幕怪物伤害显著升级，必须放大
        # （第 18 局 F22 Unknown 连环遭遇战一场 -59，恒定先验完全低估）
        acts = pol.get("path_act_scale") or [1.0]
        act_idx = min(len(acts) - 1, max(0, (floor - 1) // 17))
        act_mul = float(acts[act_idx]) if isinstance(acts[act_idx], (int, float)) else 1.0

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
            for depth, key in enumerate(path_keys):
                gnode = graph.get(key) or {}
                nt = start_node.get("node_type", "Unknown") if depth == 0 else gnode.get("node_type", "Unknown")
                hpp = max(0.0, cur_hp) / max_hp
                factor, note = node_factor(nt, gnode, hpp)
                w = weights.get(nt, 1.0) * learned_room_factor(nt) * factor
                score += w * (0.97 ** depth)
                if note and depth == 0:
                    notes.append(note)
                cur_hp -= priors.get(nt, 8) * deck_ease * act_mul
                if nt == "Unknown" and act_idx >= 1:
                    cur_hp -= priors.get(nt, 8) * deck_ease * act_mul * (pol.get("unknown_gauntlet_act2_mult", 1.6) - 1.0)
                if nt == "RestSite":
                    cur_hp = min(float(max_hp), cur_hp + heal_frac * max_hp)
                if cur_hp <= 0:
                    score -= pol.get("path_death_penalty", 100.0)
                    break
            final_pct = max(0.0, cur_hp) / max_hp
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
            label = f"{nt}({n['row']},{n['col']})"
            details.append(f"{label}={best_ps:.2f}{'|' + '；'.join(best_pnotes) if best_pnotes else ''}")
            if best_ps > best_score:
                best_node, best_score = n, best_ps
                best_detail = label
                best_notes, best_proj = best_pnotes, best_pproj

        note_txt = f"；{'；'.join(best_notes)}" if best_notes else ""
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

        if not enemies:
            if can_end:
                return Decision("end_turn", {}, "战斗：场上无有效敌人，结束回合", wait=1.0)
            return Decision(None, {}, "战斗：等待敌人就绪", wait=0.7)

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

        # potion check (elite/boss or lethal danger)
        hard = ctx.current_combat_is_hard or combat.get("end_turn_will_kill_player") or block_gap >= my_hp
        potion_dec = self._maybe_potion(state, ctx, hard)
        if potion_dec is not None:
            return potion_dec

        best = None  # (score, card, target_index, why)
        for c in hand:
            if not c.get("playable"):
                continue
            if c.get("card_id") in self._failed_this_turn:
                continue
            # 需要目标但当前无有效目标：跳过（否则服务端 409）
            if c.get("requires_target"):
                valid = c.get("valid_target_indices") or []
                if not any(e.get("index") in valid for e in enemies):
                    continue
            cost = c.get("energy_cost", 0)
            if c.get("costs_x"):
                cost = energy  # dump all energy
            if cost > energy:
                continue
            score, target, why = self._score_play(c, enemies, incoming, my_block, round_no, pol,
                                                   my_hp, my_max_hp)
            score += self.know.card_value(c.get("card_id", "")) * 0.3
            if best is None or score > best[0]:
                best = (score, c, target, why)

        if best and best[0] > pol["play_threshold"]:
            _, card, target, why = best
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
            tname = ""
            if target is not None:
                tname = next((e["name"] for e in (combat.get("enemies") or []) if e.get("index") == target), "")
            return Decision("play_card", params,
                            f"战斗：打出【{card.get('name')}】{('→' + tname) if tname else ''}（{why}）；"
                            f"敌意图总伤{incoming}，我方{my_hp}血/{my_block}甲",
                            tags=[("play_card", card.get("card_id"))], wait=0.6)

        if can_end:
            hand_desc = ",".join(f"{c.get('name')}{'✓' if c.get('playable') else '✗'}" for c in hand) or "空手"
            risk = "；警告：结束回合可能致死！" if combat.get("end_turn_will_kill_player") else ""
            return Decision("end_turn", {},
                            f"战斗：评估后无值得出的牌（{hand_desc}），结束回合（敌意图总伤{incoming}，我方{my_hp}血/{my_block}甲）{risk}",
                            wait=1.2)
        return Decision(None, {}, "战斗：等待出牌时机", wait=0.7)

    def _score_play(self, card, enemies, incoming, my_block, round_no, pol,
                    my_hp: int = 9999, my_max_hp: int = 9999):
        """战斗中手牌评分。

        注意：战斗手牌载荷没有 card_type 字段（与奖励/商店载荷不同），
        必须从 dynamic_values / 文本 / target_type 推断牌的功能。

        生存权重：残血且敌意图可能致死时，压低攻击、抬高格挡——
        第 18 局 F22 致命战在意图 44~50 时仍连续输出不补防，直接阵亡。
        """
        dmg, block, hits = card_numbers(card)
        cost = card.get("energy_cost", 0)
        text = _text(card)
        aoe = ("所有敌人" in text or "all enemies" in text.lower()
               or (card.get("target_type") or "") == "AllEnemies")

        hp_pct = my_hp / max(1, my_max_hp)
        gap = max(0, incoming - my_block)
        lethal = gap >= my_hp              # 本回合就可能被打死
        urgent = gap > 0 and hp_pct < 0.45  # 慢性失血下的低血量状态
        if lethal:
            atk_damp, blk_boost = 0.55, 1.8
        elif urgent:
            atk_damp, blk_boost = 0.75, 1.4
        else:
            atk_damp, blk_boost = 1.0, 1.0

        # --- 攻击牌（有伤害数值） ---
        if dmg > 0:
            total = dmg * hits
            if aoe:
                eff = sum(max(1, total - e.get("block", 0)) for e in enemies)
                killable = [e for e in enemies if max(1, total - e.get("block", 0)) >= e.get("current_hp", 9999)]
                score = eff * atk_damp + pol["kill_bonus"] * len(killable)
                if lethal and not killable:
                    # 致死威胁下 AOE 若不能减员，等于放弃生存换数值
                    score *= 0.35
                if cost == 0:
                    score += pol["free_card_bonus"]
                return score, None, f"群体伤害≈{eff}"
            best_t, best_s, why, best_kill = None, -1.0, "", False
            for e in enemies:
                eff = max(1, total - e.get("block", 0))
                threat = sum((it.get("total_damage") or 0) for it in e.get("intents", []))
                s = (eff + threat * 0.3) * atk_damp
                killed = eff >= e.get("current_hp", 9999)
                if killed:
                    s += pol["kill_bonus"]  # 击杀直接消灭意图来源，不吃衰减
                    why = f"可击杀{e['name']}"
                if best_t is None or s > best_s:
                    valid = card.get("valid_target_indices") or []
                    if not card.get("requires_target") or not valid or e.get("index") in valid:
                        best_t, best_s, best_kill = e.get("index"), s, killed
                        if not why:
                            why = f"单体伤害≈{eff}"
            # 致死回合里"打不死人的大伤害"是自杀牌：
            # 第 28 局 Boss 战终盘 1 血面对 11 点意图，重锤(42伤)压过防御(5甲)
            # 抢走全部能量，结果无甲吃刀阵亡——非击杀攻击必须给格挡让路。
            if lethal and not best_kill:
                best_s *= 0.35
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
            if cost == 0:
                score += pol["free_card_bonus"]
            return score, None, f"功能牌（抽牌{dr}/回能）"

        # --- 无直接数值：按能力牌处理，开局回合优先 ---
        score = (pol["power_round_bonus"] if round_no <= 2 else 1.5)
        if cost == 0:
            score += pol["free_card_bonus"]
        return score, None, f"能力/增益牌（第{round_no}回合）"

    def _maybe_potion(self, state, ctx, hard: bool):
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
            if "combat" not in usage and "战斗" not in usage and usage:
                continue
            needs_target = bool(p.get("requires_target"))
            target = None
            if needs_target:
                valid = p.get("valid_target_indices") or []
                target = next((e["index"] for e in enemies if e["index"] in valid), None)
                if target is None:
                    continue
            if ("伤害" in desc or "damage" in desc.lower() or "攻击" in desc) and enemies:
                self._potion_tried.add(p["index"])
                params = {"option_index": p["index"]}
                if target is not None:
                    params["target_index"] = target
                return Decision("use_potion", params, f"战斗：使用攻击药水【{name}】（硬仗/危急）",
                                tags=[("use_potion", p.get("potion_id"))], wait=0.6)
            if ("格挡" in desc or "生命" in desc or "回复" in desc or "block" in desc.lower() or "heal" in desc.lower()):
                if (state.get("combat", {}).get("player", {}).get("current_hp", 1)
                        < 0.35 * state.get("combat", {}).get("player", {}).get("max_hp", 1)):
                    self._potion_tried.add(p["index"])
                    return Decision("use_potion", {"option_index": p["index"]},
                                    f"战斗：低血量使用防御/回复药水【{name}】",
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

        # 攻击牌边际价值乘法衰减（固定 -2.5 挡不住基础分 10+ 的攻击牌，
        # 第 18 局仍拿了 24 张近乎全攻的牌）：占比越高衰减越狠
        if is_attack(card):
            atk_scale = clamp(1.3 - 1.4 * ratio, 0.15, 1.2)
            value += (dmg * hits * 1.0 + (1.0 if cost <= 1 else 0.0)) * atk_scale
            if ratio < 0.35:
                value += 1.5  # 输出不足时额外鼓励补攻击
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
        screen_key = ((state.get("run") or {}).get("floor", 0), kind, prompt, len(cards))
        if screen_key != self._sel_key:
            self._sel_key = screen_key
            self._sel_tried = set()

        # 已达选择数量且可确认 → 先确认（升级/删除等分支也必须走这里，否则永远循环）
        min_sel = sel.get("min_select", 1)
        if (sel.get("can_confirm") and sel.get("selected_count", 0) >= min_sel
                and "confirm_selection" in actions):
            return Decision("confirm_selection", {}, f"选牌界面（{kind}）：已选 {sel.get('selected_count')} 张，确认",
                            wait=0.9)

        removing = "remove" in kind or "删除" in prompt
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
            pick = max(candidates, key=lambda c: self.eval_reward_card(c, []))
            tag = "card_pick"
            reason = f"选择卡牌：【{pick.get('name')}】"

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

        need_heal = hp_pct < self.know.policy["rest_heal_threshold"] or not upgradable or smith is None
        if heal and need_heal:
            # 回血将溢出（接近回满）且仍有可升级卡：改锻造，不浪费篝火
            if smith and upgradable and hp_pct + heal_frac >= 0.97:
                return Decision("choose_rest_option", {"option_index": smith["index"]},
                                f"篝火：回血将溢出（{hp_pct:.0%}+{heal_frac:.0%}≥97%），改为锻造升级",
                                tags=[("rest", "smith")], wait=1.2)
            return Decision("choose_rest_option", {"option_index": heal["index"]},
                            f"篝火：休息回血（当前 {hp_pct:.0%} < {self.know.policy['rest_heal_threshold']:.0%}）",
                            tags=[("rest", "heal")], wait=1.2)
        if smith:
            return Decision("choose_rest_option", {"option_index": smith["index"]},
                            f"篝火：锻造升级（血量 {hp_pct:.0%} 尚安全）",
                            tags=[("rest", "smith")], wait=1.2)
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
        scored = []
        for o in candidates:
            key = o.get("text_key") or o.get("title") or str(o["index"])
            v, n = self.know.event_option_value(event_id, key)
            scored.append((v, n, key, o))
        # epsilon exploration among under-sampled options
        if self.rng.random() < pol["exploration_rate"]:
            fresh = [s for s in scored if s[1] < 3]
            if fresh:
                v, n, key, o = self.rng.choice(fresh)
                return Decision("choose_event_option", {"option_index": o["index"]},
                                f"事件【{ev.get('title')}】：探索未知选项「{o.get('title')}」（探索率 {pol['exploration_rate']:.2f}）",
                                tags=[("event_choice", event_id, key)], wait=1.0)
        scored.sort(key=lambda s: s[0], reverse=True)
        v, n, key, o = scored[0]
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
