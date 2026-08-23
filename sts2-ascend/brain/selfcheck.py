"""冒烟自检 —— LLM 复盘修改任何 brain/*.py 后必须通过本检查。

覆盖：全模块导入 + 用假状态驱动 Policy 各屏幕处理器不抛异常。
"""
from __future__ import annotations

import random
import re
import json
import sys
import tempfile
from pathlib import Path

BRAIN = Path(__file__).resolve().parent
sys.path.insert(0, str(BRAIN))


def main() -> int:
    # 1) 全模块可导入
    import client, knowledge, policy, reflect, agent, autogit, llm_review  # noqa: F401

    # 2) Policy 在空知识库上能对各屏幕给出决策（不抛异常即可）
    tmp = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-"))
    know = knowledge.Knowledge(tmp)
    pol = policy.Policy(know)

    class DummyCtx:
        current_combat_is_hard = False
        run_finalized = True
        finalize_requested = False
        credit_tags: list = []
        combat = None
        combat_notes: list = []
        pending_event = None
        died_in_combat = None
        died_to_event = None
        rests_healed_at_full = 0
        death_hp_pct_at_entry = None
        death_was_elite = False

    ctx = DummyCtx()
    fake_states = [
        {"screen": "MAIN_MENU", "available_actions": ["open_character_select"]},
        {"screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 1,
         "combat": {"player": {"current_hp": 80, "max_hp": 80, "block": 0, "energy": 3},
                    "hand": [{"index": 0, "card_id": "STRIKE_IRONCLAD", "name": "打击", "playable": True,
                              "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                              "dynamic_values": [{"name": "Damage", "current_value": 6}]}],
                    "enemies": [{"index": 0, "enemy_id": "X", "name": "怪", "current_hp": 10, "max_hp": 10,
                                 "block": 0, "is_alive": True, "is_hittable": True, "intents": []}]},
         "run": {"current_hp": 80, "max_hp": 80, "gold": 99, "floor": 1, "deck": []}},
        {"screen": "MAP", "available_actions": ["choose_map_node"],
         "map": {"available_nodes": [{"index": 0, "row": 1, "col": 0, "node_type": "Monster"}], "nodes": []},
         "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 1, "deck": []}},
        {"screen": "REWARD", "available_actions": ["claim_reward", "proceed"],
         "reward": {"rewards": [{"index": 0, "reward_type": "Gold", "description": "42金币", "claimable": True}],
                    "card_options": [], "can_proceed": True},
         "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 2, "deck": []}},
        {"screen": "CARD_SELECTION", "available_actions": ["select_deck_card", "confirm_selection"],
         "selection": {"kind": "upgrade", "prompt": "升级", "min_select": 1, "selected_count": 0,
                       "can_confirm": False,
                       "cards": [{"index": 0, "card_id": "BASH", "name": "痛击", "card_type": "Attack"}]},
         "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 3, "deck": []}},
        {"screen": "EVENT", "available_actions": ["choose_event_option"],
         "event": {"event_id": "T", "title": "测试", "is_finished": False,
                   "options": [{"index": 0, "title": "A", "is_locked": False, "is_proceed": False}]},
         "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 4, "deck": []}},
    ]
    for st in fake_states:
        d = pol.decide(st, ctx)
        assert d is not None, f"decide returned None for {st['screen']}"

    # 3) 针对性场景断言（decide() 吞异常保活，逻辑错误必须在这里显式暴露）

    # 3a) 选牌端：攻击占比 0.8 时普通攻击须被乘法衰减压到阈值以下；格挡稀缺技能须增值
    atk_rich = ([{"card_id": f"STRIKE_{i}", "card_type": "Attack", "energy_cost": 1} for i in range(8)]
                + [{"card_id": f"DEFEND_{i}", "card_type": "Skill", "energy_cost": 1} for i in range(2)])
    weak_atk = {"card_id": "TWIN_STRIKE", "name": "双重打击", "card_type": "Attack", "energy_cost": 1,
                "dynamic_values": [{"name": "Damage", "current_value": 4}, {"name": "Hits", "current_value": 2}]}
    block_skill = {"card_id": "SHRUG_IT_OFF", "name": "耸肩卸力", "card_type": "Skill", "energy_cost": 1,
                   "rules_text": "获得8点格挡。抽1张牌。",
                   "dynamic_values": [{"name": "Block", "current_value": 8}]}
    v_atk = pol.eval_reward_card(dict(weak_atk), [dict(c) for c in atk_rich])
    v_blk = pol.eval_reward_card(dict(block_skill), [dict(c) for c in atk_rich])
    assert v_atk < know.policy["card_pick_threshold"], f"攻击乘法衰减失效: v_atk={v_atk}"
    assert v_blk >= know.policy["card_pick_threshold"] > v_atk, f"格挡稀缺增值失效: v_blk={v_blk}"

    # 3b) 战斗端：残血+致死意图下必须优先打出格挡牌而非攻击
    combat_state = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 2,
        "combat": {"player": {"current_hp": 15, "max_hp": 80, "block": 0, "energy": 3},
                   "hand": [
                       {"index": 0, "card_id": "STRIKE_IRONCLAD", "name": "打击", "playable": True,
                        "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                        "dynamic_values": [{"name": "Damage", "current_value": 6}]},
                       {"index": 1, "card_id": "SHRUG_IT_OFF", "name": "耸肩卸力", "playable": True,
                        "energy_cost": 1, "requires_target": False,
                        "rules_text": "获得8点格挡",
                        "dynamic_values": [{"name": "Block", "current_value": 8}]}],
                   "enemies": [{"index": 0, "enemy_id": "BOSSISH", "name": "大怪", "current_hp": 60,
                                "max_hp": 80, "block": 0, "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 25}]}]},
        "run": {"current_hp": 15, "max_hp": 80, "gold": 0, "floor": 20, "deck": []},
    }
    d = pol.decide(combat_state, ctx)
    assert d.action == "play_card" and d.params.get("card_index") == 1, \
        f"生存权重失效: {d.params}（{d.reason}）"

    # 3c) 地图端：二幕（floor>17）掉血先验必须比一幕重（预计进 Boss 血量更低）
    def map_reason(floor_no):
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": [{"index": 0, "row": 1, "col": 0, "node_type": "Monster"}], "nodes": []},
              "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": floor_no, "deck": []}}
        return pol.decide(st, ctx).reason

    p1 = float(re.search(r"进 Boss 血量 ?(\d+)%", map_reason(5)).group(1))
    p2 = float(re.search(r"进 Boss 血量 ?(\d+)%", map_reason(25)).group(1))
    assert p2 < p1, f"幕数缩放失效: F5 预计 {p1}% / F25 预计 {p2}%"

    # 3d) 致死回合：打不死人的大伤害攻击必须让位于格挡
    # （第 28 局 Boss 战终盘：1 血面对 11 点意图，重锤 42 伤抢走全部能量，无甲吃刀阵亡）
    lethal_state = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 9,
        "combat": {"player": {"current_hp": 1, "max_hp": 80, "block": 0, "energy": 3},
                   "hand": [
                       {"index": 0, "card_id": "BLUDGEON", "name": "重锤", "playable": True,
                        "energy_cost": 3, "requires_target": True, "valid_target_indices": [0],
                        "dynamic_values": [{"name": "Damage", "current_value": 42}]},
                       {"index": 1, "card_id": "DEFEND_IRONCLAD", "name": "防御", "playable": True,
                        "energy_cost": 1, "requires_target": False,
                        "rules_text": "获得5点格挡",
                        "dynamic_values": [{"name": "Block", "current_value": 5}]}],
                   "enemies": [{"index": 0, "enemy_id": "VANTOM", "name": "墨影幻灵", "current_hp": 60,
                                "max_hp": 250, "block": 0, "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 11}]}]},
        "run": {"current_hp": 1, "max_hp": 80, "gold": 0, "floor": 17, "deck": []},
    }
    d_lethal = pol.decide(lethal_state, ctx)
    assert d_lethal.action == "play_card" and d_lethal.params.get("card_index") == 1, \
        f"致死回合必须优先格挡: {d_lethal.params}（{d_lethal.reason}）"

    # 3e) 精英进场闸门（第 36 局复盘重构）：静态血量线之外增加实测战损投影——
    #     血量进精英"预计战后血量"低于安全线时整条候选路径 ×0.1 规避。
    #     空知识库下 Elite 先验 28、卡组折扣 min(0.2, 2%×6张)=12% → 战损 24.6：
    #     80% 血 → 战后 49% ≥ 45% 需求 → 放行；70% 血 → 战后 39% → 投影规避；
    #     50% 血 → 低于 soft 线静态规避
    def elite_reason(hp_now: int) -> str:
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": [{"index": 0, "row": 1, "col": 0, "node_type": "Elite"}], "nodes": []},
              "run": {"current_hp": hp_now, "max_hp": 80, "gold": 200, "floor": 10,
                      "deck": [{"card_id": f"CARD_{i}"} for i in range(6)]}}
        return pol.decide(st, ctx).reason

    old_elite = know.policy["elite_min_hp_pct"]
    know.policy["elite_min_hp_pct"] = 0.72
    know.policy["elite_soft_hp_pct"] = 0.62
    r_go = elite_reason(64)     # 80%：血量与战后余量双达标，放行
    r_proj = elite_reason(56)   # 70%：投影战后仅 39% < 45% 需求 → 规避
    r_low = elite_reason(40)    # 50%：<soft 规避
    assert "规避精英" not in r_go and "灰区" not in r_go, f"精英放行失效: {r_go}"
    assert "规避精英" in r_proj and "预计战后" in r_proj, f"精英投影闸门失效: {r_proj}"
    assert "规避精英" in r_low, f"低血规避精英失效: {r_low}"
    know.policy["elite_min_hp_pct"] = old_elite
    know.policy.pop("elite_soft_hp_pct", None)

    # 3f) Boss 行终端语义：地图缺 boss_node 键时按图最深行推断，
    # 进 Boss 血量投影不得再扣 Boss 自身战损（旧版 62/80 血被投影成 35%）
    boss_map = {"screen": "MAP", "available_actions": ["choose_map_node"],
                "map": {"available_nodes": [{"index": 0, "row": 16, "col": 3, "node_type": "Boss"}],
                        "nodes": [{"row": 1, "col": 0, "node_type": "Monster",
                                   "children": [{"row": 16, "col": 3}]},
                                  {"row": 16, "col": 3, "node_type": "Boss"}]},
                "run": {"current_hp": 62, "max_hp": 80, "gold": 0, "floor": 16, "deck": []}}
    d_boss = pol.decide(boss_map, ctx)
    m_boss = re.search(r"进 Boss 血量 ?(\d+)%", d_boss.reason)
    assert m_boss and int(m_boss.group(1)) >= 77, f"Boss 终端投影失效: {d_boss.reason}"

    # 3g) 自残牌约束：致死回合里无法终结战斗的自残攻击必须让位于格挡
    #     （第 29 局终局：9 血面对 28 点意图先打【御血术】自掉 2 血再阵亡）
    know.stats.setdefault("enemies", {})["DUMMY_BRUTE+DUMMY_HEXER"] = {
        "encounters": 5, "hp_lost_sum": 150.0, "deaths": 4, "wins": 1}
    stance_bad = know.enemy_stance("DUMMY_BRUTE+DUMMY_HEXER")
    assert stance_bad["urgent_hp_pct"] > 0.5 and stance_bad["blk_mult"] > 1.0 \
        and "高危" in stance_bad.get("danger", ""), f"高危组合姿态失效: {stance_bad}"
    assert know.enemy_stance("UNKNOWN_COMP")["atk_mult"] == 1.0, "未知组合应为中性姿态"
    # 第 36 局复盘：高危 Boss 提速的同时也要抬格挡（52 血进场每回合 5~9 甲
    # 硬吃 13~27 意图被磨死——少挨一刀多活一轮）
    stance_boss = know.enemy_stance("DUMMY_BRUTE+DUMMY_HEXER", "Boss")
    assert stance_boss["atk_mult"] > 1.0 and stance_boss["blk_mult"] > 1.0 \
        and "高危Boss" in stance_boss.get("danger", ""), f"高危Boss姿态失效: {stance_boss}"

    hemokinesis = {"index": 0, "card_id": "HEMOKINESIS", "name": "御血术", "playable": True,
                   "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                   "rules_text": "失去 2 点生命，造成 18 点伤害。",
                   "dynamic_values": [{"name": "Damage", "current_value": 18}]}
    ctx.combat = {"comp_id": "DUMMY_BRUTE+DUMMY_HEXER"}
    self_lethal_state = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 3,
        "combat": {"player": {"current_hp": 9, "max_hp": 80, "block": 0, "energy": 3},
                   "hand": [
                       dict(hemokinesis),
                       {"index": 1, "card_id": "DEFEND_IRONCLAD", "name": "防御", "playable": True,
                        "energy_cost": 1, "requires_target": False,
                        "rules_text": "获得5点格挡",
                        "dynamic_values": [{"name": "Block", "current_value": 5}]}],
                   "enemies": [
                       {"index": 0, "enemy_id": "KIN_FOLLOWER", "name": "同族信徒", "current_hp": 10,
                        "max_hp": 30, "block": 0, "is_alive": True, "is_hittable": True,
                        "intents": [{"total_damage": 10}]},
                       {"index": 1, "enemy_id": "KIN_PRIEST", "name": "同族神官", "current_hp": 40,
                        "max_hp": 50, "block": 0, "is_alive": True, "is_hittable": True,
                        "intents": [{"total_damage": 18}]}]},
        "run": {"current_hp": 9, "max_hp": 80, "gold": 0, "floor": 17, "deck": []},
    }
    d_self = pol.decide(self_lethal_state, ctx)
    assert d_self.action == "play_card" and d_self.params.get("card_index") == 1, \
        f"致死回合自残牌必须让位格挡: {d_self.params}（{d_self.reason}）"
    assert "高危" in d_self.reason, f"高危组合提示缺失: {d_self.reason}"
    ctx.combat = None

    # 3h) 服务端致死判定 + 409 黑名单精确到卡牌实例
    #     （第 31 局 F7 终局：17 血对 18 意图，一张防御 409 把同 id 两张防御全部拉黑，
    #      改打打击后无甲吃 18 刀阵亡——手牌里其实还压着可用的防御）
    def _defend(idx):
        return {"index": idx, "card_id": "DEFEND_IRONCLAD", "name": "防御", "playable": True,
                "energy_cost": 1, "requires_target": False,
                "rules_text": "获得5点格挡",
                "dynamic_values": [{"name": "Block", "current_value": 5}]}

    _strike = {"index": 0, "card_id": "STRIKE_IRONCLAD", "name": "打击", "playable": True,
               "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
               "dynamic_values": [{"name": "Damage", "current_value": 6}]}
    forced_state = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 4,
        "combat": {"player": {"current_hp": 17, "max_hp": 80, "block": 0, "energy": 3},
                   "end_turn_will_kill_player": True,
                   "hand": [dict(_strike), _defend(1), _defend(2)],
                   "enemies": [{"index": 0, "enemy_id": "FUZZY_WURM", "name": "毛绒伏地虫",
                                "current_hp": 30, "max_hp": 30, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 18}]}]},
        "run": {"current_hp": 17, "max_hp": 80, "gold": 0, "floor": 7, "deck": []},
    }
    d_f1 = pol.decide(forced_state, ctx)
    assert d_f1.action == "play_card" and d_f1.params.get("card_index") in (1, 2), \
        f"服务端致死判定必须先补防: {d_f1.params}（{d_f1.reason}）"
    # 模拟这张防御打出失败（409）：只拉黑该实例，另一张同 id 防御必须仍可选
    failed_idx = d_f1.params.get("card_index")
    pol.note_action_failed("play_card", list(d_f1.tags))
    d_f2 = pol.decide(forced_state, ctx)
    assert d_f2.action == "play_card" and d_f2.params.get("card_index") != failed_idx \
        and d_f2.params.get("card_index") in (1, 2), \
        f"409 黑名单不得连坐同 id 其他副本: {d_f2.params}（{d_f2.reason}）"
    # 已补 5 甲但服务端仍判定致死 → 必须继续补防而非输出（本地算术已"脱险"）
    # （换新回合数触发黑名单自然清空，聚焦验证 forced_kill 语义本身）
    forced_state["turn"] = 5
    forced_state["combat"]["player"]["block"] = 5
    forced_state["combat"]["hand"] = [dict(_strike), _defend(1)]
    d_f3 = pol.decide(forced_state, ctx)
    assert d_f3.action == "play_card" and d_f3.params.get("card_index") == 1, \
        f"服务端致死未解除前必须继续补防: {d_f3.params}（{d_f3.reason}）"

    # 3i) 奖励端抑制：统计实锤差牌（≥4局且场均低于全局均值4+）与未升级基础打/防牌
    know.stats.setdefault("cards", {})["PROVEN_DUD"] = {
        "seen": 9, "picked": 5, "plays": 20, "outcome_sum": 25.0, "bias": 0.0}
    dud = {"card_id": "PROVEN_DUD", "name": "废牌", "card_type": "Skill", "energy_cost": 1,
           "rules_text": "获得 8 点格挡。抽 1 张牌。",
           "dynamic_values": [{"name": "Block", "current_value": 8}]}
    v_dud = pol.eval_reward_card(dict(dud), [])
    assert v_dud < know.policy["card_pick_threshold"], f"实锤低价值牌未被回避: v={v_dud}"
    v_basic = pol.eval_reward_card({
        "card_id": "STRIKE_IRONCLAD", "card_type": "Attack", "energy_cost": 1,
        "dynamic_values": [{"name": "Damage", "current_value": 6}]}, [])
    assert v_basic < know.policy["card_pick_threshold"], \
        f"未升级基础打击在奖励端未被抑制: v={v_basic}"

    # 3j) 事件平值语义（第 56~57 局复盘改版）：
    #     a) 有实证收益的选项必须立即胜出（价值优先，平值才按样本数——石炉加湿器教训）
    #     b) 全零平值改选样本最少的选项分散采样：事件结算只记即时 hp/gold，祝福类
    #        选项长期记 0，按样本最大排序会把「涅奥的苦痛」(n=8) 永久锁死，
    #        营养牡蛎(+11/次)式的正收益选项永远无法被发现
    know.stats.setdefault("events", {})["TIE_EV"] = {
        "OPT_KNOWN": {"n": 4, "hp_delta_sum": 0.0, "gold_delta_sum": 0.0, "deaths": 0}}
    tie_state = {"screen": "EVENT", "available_actions": ["choose_event_option"],
                 "event": {"event_id": "TIE_EV", "title": "平值测试", "is_finished": False,
                           "options": [{"index": 0, "title": "未知项", "text_key": "OPT_FRESH",
                                        "is_locked": False, "is_proceed": False},
                                       {"index": 1, "title": "已知项", "text_key": "OPT_KNOWN",
                                        "is_locked": False, "is_proceed": False}]},
                 "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 5, "deck": []}}
    pol_exploit = policy.Policy(know, random.Random(2))  # 首抽 0.956 > 探索率 → 走利用路径
    d_tie = pol_exploit.decide(tie_state, ctx)
    assert d_tie.params.get("option_index") == 0 and "探索" not in d_tie.reason, \
        f"全零平值应选样本最少选项收集信息（不得锁死高样本项/不得走探索分支）: {d_tie.reason}"
    # 出现实证收益选项后恢复"价值→样本"贪心
    know.stats["events"]["TIE_EV"]["OPT_GOOD"] = {
        "n": 2, "hp_delta_sum": 40.0, "gold_delta_sum": 0.0, "deaths": 0}
    tie_state["event"]["options"].append(
        {"index": 2, "title": "收益项", "text_key": "OPT_GOOD",
         "is_locked": False, "is_proceed": False})
    pol_exploit2 = policy.Policy(know, random.Random(2))
    d_tie2 = pol_exploit2.decide(tie_state, ctx)
    assert d_tie2.params.get("option_index") == 2 and "探索" not in d_tie2.reason, \
        f"正收益选项必须胜出（价值→样本贪心恢复）: {d_tie2.reason}"

    # 3k) 探索不碰已知负收益选项（吃过 -34 血的选项不再被探索重试）
    know.stats["events"]["NEG_EV"] = {
        "OPT_BAD": {"n": 2, "hp_delta_sum": -68.0, "gold_delta_sum": 0.0, "deaths": 0}}

    class _AlwaysExploreFirstChoiceRng:
        def random(self) -> float:
            return 0.01

        def choice(self, seq):
            return seq[0]

    neg_state = {"screen": "EVENT", "available_actions": ["choose_event_option"],
                 "event": {"event_id": "NEG_EV", "title": "负收益测试", "is_finished": False,
                           "options": [{"index": 0, "title": "大亏项", "text_key": "OPT_BAD",
                                        "is_locked": False, "is_proceed": False},
                                       {"index": 1, "title": "新项", "text_key": "OPT_NEW",
                                        "is_locked": False, "is_proceed": False}]},
                 "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 6, "deck": []}}
    pol_neg = policy.Policy(know, _AlwaysExploreFirstChoiceRng())
    d_neg = pol_neg.decide(neg_state, ctx)
    assert d_neg.params.get("option_index") == 1 and "探索" in d_neg.reason, \
        f"探索必须回避已知负收益选项: {d_neg.reason}"

    # 3l) 能量预留：缺口未补且能量不足以「攻击后再补防」时，格挡先行
    #     （第 36 批 F17 Boss 战：先挥霍输出，下轮 20 意图手持防御却 0 能量）
    def reserve_combat(hp_now, block_now, energy_now, hand):
        return {"screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 2,
                "combat": {"player": {"current_hp": hp_now, "max_hp": 80, "block": block_now,
                                      "energy": energy_now},
                           "hand": hand,
                           "enemies": [{"index": 0, "enemy_id": "BRUISER", "name": "壮汉",
                                        "current_hp": 100, "max_hp": 120, "block": 0,
                                        "is_alive": True, "is_hittable": True,
                                        "intents": [{"total_damage": 12}]}]},
                "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 9, "deck": []}}

    heavy = {"index": 0, "card_id": "HEAVY_BLOW", "name": "重击", "playable": True,
             "energy_cost": 2, "requires_target": True, "valid_target_indices": [0],
             "dynamic_values": [{"name": "Damage", "current_value": 12}]}
    big_defend = {"index": 1, "card_id": "DEFEND_IRONCLAD", "name": "防御", "playable": True,
                  "energy_cost": 1, "requires_target": False,
                  "rules_text": "获得10点格挡",
                  "dynamic_values": [{"name": "Block", "current_value": 10}]}
    d_r1 = pol.decide(reserve_combat(50, 0, 2, [dict(heavy), dict(big_defend)]), ctx)
    assert d_r1.action == "play_card" and d_r1.params.get("card_index") == 1, \
        f"能量不足两用时必须先补防: {d_r1.params}（{d_r1.reason}）"
    d_r2 = pol.decide(reserve_combat(50, 10, 2, [dict(heavy)]), ctx)
    assert d_r2.action == "play_card" and d_r2.params.get("card_index") == 0, \
        f"缺口已补后攻击应恢复正常评分: {d_r2.params}（{d_r2.reason}）"

    # 3m) 战斗连续性：转阶段过场闪断不得把同一场战斗拆成多条统计
    #     （第 36 批 DW7 局 F17 一场 Boss 战被记为掉血 1/18/38 三笔，
    #      场均掉血被稀释、enemy_stance 死亡率失真、药水黑名单误重置）
    import agent as agent_mod
    tmp_agent = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-agent-"))
    agent_mod.KNOWLEDGE_DIR = tmp_agent
    agent_mod._LOG_PATH = tmp_agent / "brain.log"
    ag = agent_mod.Agent(dict(agent_mod.DEFAULT_CONFIG))
    tknow = ag.know

    def trk(st):
        ag._track(st, policy.Decision(action=None))

    def trk_state(hp, comp="E1", screen="COMBAT", victory=None, floor=17):
        st = {"screen": screen, "run_id": "RUN_T",
              "run": {"current_hp": hp, "max_hp": 80, "gold": 0, "floor": floor}}
        if screen == "COMBAT":
            st["combat"] = {"enemies": [{"enemy_id": comp, "is_alive": True}]}
        if screen == "GAME_OVER":
            st["game_over"] = {"is_victory": bool(victory)}
        return st

    trk(trk_state(80))                                     # 进入战斗 E1
    assert ag.ctx.combat and ag.ctx.combat["comp_id"] == "E1"
    trk(trk_state(80, screen="MODAL"))                     # 转阶段过场：挂起不结算
    assert tknow.stats["enemies"].get("E1") is None and ag.ctx.combat_bridge is not None
    trk(trk_state(72))                                     # 重连：延续同一场战斗
    assert tknow.stats["enemies"].get("E1") is None and ag.ctx.combat["hp_start"] == 80
    trk(trk_state(40, screen="GAME_OVER", victory=False))  # 阵亡：一次性结算
    e1 = tknow.stats["enemies"].get("E1")
    assert e1 and e1["encounters"] == 1 and e1["deaths"] == 1 and e1["hp_lost_sum"] == 40, f"E1={e1}"
    assert ag.ctx.died_in_combat is not None and ag.ctx.combat_notes[-1].endswith("（阵亡）")
    # 过场后战斗对象变化：先结算旧账再开新账
    trk(trk_state(40, comp="E2"))
    trk(trk_state(40, comp="E2", screen="MODAL"))
    trk(trk_state(35, comp="E3", floor=18))  # 真实流转必然换层：同层分段属多阶段战斗
    e2 = tknow.stats["enemies"].get("E2")
    assert e2 and e2["encounters"] == 1 and e2["wins"] == 1, f"E2={e2}"
    assert ag.ctx.combat and ag.ctx.combat["comp_id"] == "E3"

    # 3m2) 同层多段战斗聚合（第 97~98 批复盘）：97 局一场仪式兽（实际掉血
    #      45+0+35=80）被阶段切换拆成 3 条统计——boss_loss_stats 场均被稀释成
    #      22.9/段（真实 ≈65），Boss 前夜智能锻造「战损≥回血量」条件以 1.1 之差
    #      永不触发，敌人死亡率分母同步灌水。修复后同层分段必须合并为一场。
    ag_bs = agent_mod.Agent(dict(agent_mod.DEFAULT_CONFIG))
    tknow_bs = ag_bs.know

    def boss_phase(floor, hp_start, hp_end, rounds=3):
        ag_bs._start_combat({"max_hp": 80, "floor": floor}, "PHASE_BOSS", "Boss", hp_start)
        ag_bs.ctx.combat["rounds"] = rounds
        ag_bs._settle_combat(hp_end, won=True, died=False, split=True)

    boss_phase(17, 80, 62)     # 阶段1：-18 挂账（旧版此处立即入账 → 拆分复发）
    assert tknow_bs.stats["enemies"].get("PHASE_BOSS") is None, \
        "阶段1结算被立即入账（多段拆分复发）"
    boss_phase(17, 62, 30)     # 阶段2：同层开账不冲销，并段累计 -48
    assert tknow_bs.stats["enemies"].get("PHASE_BOSS") is None, \
        "阶段2结算被独立入账"
    boss_phase(18, 30, 5)      # 换层开战：冲销上一层合并账（整场 -48 一条记录）
    e_bs = tknow_bs.stats["enemies"].get("PHASE_BOSS") or {}
    assert e_bs.get("encounters") == 1 and abs(e_bs.get("hp_lost_sum", 0) - 50) < 1e-9 \
        and e_bs.get("wins") == 1, f"同层两段未合并为一场: {e_bs}"
    bl_bs, bn_bs = tknow_bs.boss_loss_stats()
    assert bn_bs == 1 and abs(bl_bs - 50.0) < 1e-9, \
        f"Boss 分档口径未按整场计（{bl_bs}/{bn_bs}），智能锻造校准仍失真"
    assert ag_bs.ctx.combat_notes == ["F17 Boss战 掉血50"], \
        f"战斗记录应合并为单条: {ag_bs.ctx.combat_notes}"
    # 致死分段立即落库 + 归因口径取整场（入场血量取首段、回合数取各段最长）
    ag_bs._start_combat({"max_hp": 80, "floor": 19}, "PHASE_BOSS2", "Boss", 76)
    ag_bs.ctx.combat["rounds"] = 3
    ag_bs._settle_combat(66, won=True, died=False, split=True)   # 阶段1：-10 挂起(open)
    ag_bs._start_combat({"max_hp": 80, "floor": 19}, "PHASE_BOSS2", "Boss", 66)
    assert tknow_bs.stats["enemies"].get("PHASE_BOSS2") is None, \
        "同层开新账误冲销了进行中的多阶段聚合账"
    ag_bs.ctx.combat["rounds"] = 4
    ag_bs._settle_combat(20, won=False, died=True)               # 阶段2 内阵亡：整场一次性落库
    e_bd = tknow_bs.stats["enemies"]["PHASE_BOSS2"]
    assert e_bd["encounters"] == 1 and e_bd["deaths"] == 1 \
        and abs(e_bd["hp_lost_sum"] - 56) < 1e-9, f"致死合并失败: {e_bd}"
    assert abs((ag_bs.ctx.death_hp_pct_at_entry or 0) - 0.95) < 1e-9, \
        f"死亡入场血量应取首段（整场进场时）: {ag_bs.ctx.death_hp_pct_at_entry}"
    assert ag_bs.ctx.died_in_combat["rounds"] == 4, \
        f"死亡回合数应取全场最长: {ag_bs.ctx.died_in_combat}"
    ag_bs.ctx.combat = None

    # 3j) 惨胜防线（第 36 局复盘新增）：补防后剩余缺口虽不致死、但会把血量
    #     打穿到 12% 皮血线以下时，非击杀攻击必须让位于格挡。
    #     （第 36 局 Boss 战：20 血对 27 意图，8 甲硬吃 19 剩 1 血下回合必死；
    #      本用例复刻该局面——36 血/5 甲对 33 意图，缺口 28 不致死但战后仅剩 8 血）
    pyrrhic_state = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 6,
        "combat": {"player": {"current_hp": 36, "max_hp": 80, "block": 5, "energy": 3},
                   "hand": [
                       {"index": 0, "card_id": "BLUDGEON", "name": "重锤", "playable": True,
                        "energy_cost": 3, "requires_target": True, "valid_target_indices": [0],
                        "dynamic_values": [{"name": "Damage", "current_value": 42}]},
                       {"index": 1, "card_id": "DEFEND_IRONCLAD", "name": "防御", "playable": True,
                        "energy_cost": 1, "requires_target": False,
                        "rules_text": "获得5点格挡",
                        "dynamic_values": [{"name": "Block", "current_value": 5}]}],
                   "enemies": [{"index": 0, "enemy_id": "KIN_PRIEST", "name": "同族神官",
                                "current_hp": 60, "max_hp": 80, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 33}]}]},
        "run": {"current_hp": 36, "max_hp": 80, "gold": 0, "floor": 17, "deck": []},
    }
    d_py = pol.decide(pyrrhic_state, ctx)
    assert d_py.action == "play_card" and d_py.params.get("card_index") == 1, \
        f"惨胜防线失效（血量将被打穿到皮血线仍选输出）: {d_py.params}（{d_py.reason}）"

    # 3k) 药水分级（第 36 局复盘新增）：增益药水只进精英/Boss/致死局，
    #     普通消耗战哪怕低血放血也不许烧（第 36 局 F15 把异鱼之油倒进净损
    #     2 血的顺风波，Boss 战空手阵亡）
    def potion_state() -> dict:
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 2,
            "combat": {"player": {"current_hp": 24, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [],
                       "enemies": [{"index": 0, "enemy_id": "M", "name": "小怪",
                                    "current_hp": 30, "max_hp": 30, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": 10}]}]},
            "run": {"current_hp": 24, "max_hp": 80, "gold": 0, "floor": 14, "deck": [],
                    "potions": [{"index": 0, "potion_id": "STRENGTH_P", "name": "力量药水",
                                 "description": "获得2点力量。", "occupied": True,
                                 "can_use": True, "usage": "combat"}]},
        }

    ctx.current_combat_is_hard = False
    d_p0 = pol.decide(potion_state(), ctx)
    assert d_p0.action != "use_potion", \
        f"普通战低血不得烧增益药水: {d_p0.action}（{d_p0.reason}）"
    ctx.current_combat_is_hard = True
    d_p1 = pol.decide(potion_state(), ctx)
    assert d_p1.action == "use_potion", \
        f"精英/Boss 战增益药水必须投入: {d_p1.action}（{d_p1.reason}）"
    ctx.current_combat_is_hard = False

    # 3n) 精英闸门不得在负分区间反转（第 43 局 F10 实证）：
    #     低血量全路径投影死亡时，旧版 ×0.1 把精英 -110 抬到 -11 压过篝火 -109，
    #     20 血走进 BYGONE_EFFIGY 阵亡。修复后：正分乘法/负分加性重罚，
    #     且死亡投影按存活深度递减罚分——深图低血时篝火必须胜出
    def deep_elite_vs_rest(hp_now: int):
        heads = [
            {"index": 0, "row": 1, "col": 0, "node_type": "Elite",
             "children": [{"row": 2, "col": 0}]},
            {"index": 1, "row": 1, "col": 1, "node_type": "RestSite",
             "children": [{"row": 2, "col": 1}]},
        ]
        chain = []
        for r in range(2, 17):
            for c in (0, 1):
                gnode = {"row": r, "col": c,
                         "node_type": "Boss" if r == 16 else "Monster"}
                if r < 16:
                    gnode["children"] = [{"row": r + 1, "col": c}]
                chain.append(gnode)
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": heads, "nodes": heads + chain,
                      "boss_node": {"row": 16}},
              "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 5, "deck": []}}
        return pol.decide(st, ctx)

    d_gate = deep_elite_vs_rest(20)  # 25% 血：精英闸门触发 + 全路径投影死亡
    assert d_gate.params.get("option_index") == 1, \
        f"负分区间闸门反转未修复（低血深图应选篝火而非精英）: {d_gate.reason}"
    assert "规避精英" in d_gate.reason, f"精英规避注释缺失: {d_gate.reason}"

    # 3o) 商店删牌语义：关键词缺失时由握手标志兜底，且必须删最无价值牌而非最高价值牌
    #     （第 43 局 F7 删掉余烬+、第 44 局 F9 删掉上勾拳——付费删掉自己最强的牌）
    def removal_state(prompt_txt, kind_txt=""):
        return {"screen": "CARD_SELECTION",
                "available_actions": ["select_deck_card", "confirm_selection"],
                "selection": {"kind": kind_txt, "prompt": prompt_txt, "min_select": 1,
                              "selected_count": 0, "can_confirm": False,
                              "cards": [
                                  {"index": 0, "card_id": "SHRUG_IT_OFF", "name": "耸肩卸力",
                                   "card_type": "Skill", "energy_cost": 1,
                                   "rules_text": "获得8点格挡",
                                   "dynamic_values": [{"name": "Block", "current_value": 8}]},
                                  {"index": 1, "card_id": "STRIKE_IRONCLAD", "name": "打击",
                                   "card_type": "Attack", "energy_cost": 1,
                                   "dynamic_values": [{"name": "Damage", "current_value": 6}]}]},
                "run": {"current_hp": 60, "max_hp": 80, "gold": 0, "floor": 9, "deck": []}}

    pol._removal_pending_floor = 9  # 模拟 remove_card_at_shop 刚发出（文案不可识别）
    d_rm1 = pol.decide(removal_state("请选择一张卡"), ctx)
    assert d_rm1.tags and d_rm1.tags[0][0] == "card_remove" and d_rm1.params.get("option_index") == 1, \
        f"删牌握手失败（应删打击而非高价值防牌）: {d_rm1.reason}"
    d_rm2 = pol.decide(removal_state("移除一张牌。"), ctx)  # 关键词路径（握手已消费）
    assert d_rm2.tags and d_rm2.tags[0][0] == "card_remove", f"删牌关键词识别失败: {d_rm2.reason}"
    d_rm3 = pol.decide(removal_state("选择一张牌加入你的牌组。"), ctx)  # 负例：普通拿牌屏
    assert d_rm3.tags and d_rm3.tags[0][0] == "card_pick", f"普通拿牌屏被误判为删牌: {d_rm3.reason}"

    # 3p) 目标列表过期不得弃权整回合（第 44 局 F6 实证：斩杀后 4 张可出攻击被
    #     静默跳过，对 14 点意图结束回合）——应兜底打向存活敌人
    stale_target_state = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 2,
        "combat": {"player": {"current_hp": 50, "max_hp": 80, "block": 0, "energy": 2},
                   "hand": [{"index": 0, "card_id": "STRIKE_IRONCLAD", "name": "打击",
                             "playable": True, "energy_cost": 1, "requires_target": True,
                             "valid_target_indices": [7],  # 过期：存活敌人是 0
                             "dynamic_values": [{"name": "Damage", "current_value": 6}]}],
                   "enemies": [{"index": 0, "enemy_id": "E", "name": "怪", "current_hp": 20,
                                "max_hp": 30, "block": 0, "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 10}]}]},
        "run": {"current_hp": 50, "max_hp": 80, "gold": 0, "floor": 6, "deck": []},
    }
    d_st = pol.decide(stale_target_state, ctx)
    assert d_st.action == "play_card" and d_st.params.get("target_index") == 0, \
        f"目标列表过期必须兜底出牌而非结束回合: {d_st.action}（{d_st.reason}）"
    assert "过期" in d_st.reason or "兜底" in d_st.reason, f"兜底注释缺失: {d_st.reason}"

    # 3q) 多页事件经验跨页聚合：尾键(.options.X)命中历史负收益时不得再选该选项
    #     （第 43 局实证：真理石板每页 n=0 被当新选项反复解读，单事件 -39）
    know.stats.setdefault("events", {})["WS_EV"] = {
        "CONTINUE": {"n": 2, "hp_delta_sum": -60.0, "gold_delta_sum": 0.0, "deaths": 0}}
    ws_state = {"screen": "EVENT", "available_actions": ["choose_event_option"],
                "event": {"event_id": "WS_EV", "title": "跨页聚合测试", "is_finished": False,
                          "options": [
                              {"index": 0, "title": "继 续 解 读",
                               "text_key": "WS_EV.pages.DECIPHER_9.options.CONTINUE",
                               "is_locked": False, "is_proceed": False},
                              {"index": 1, "title": "放弃",
                               "text_key": "WS_EV.pages.INITIAL.options.GIVE_UP",
                               "is_locked": False, "is_proceed": False}]},
                "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 7, "deck": []}}
    pol_ws = policy.Policy(know, random.Random(2))  # 首抽 0.956 > 探索率 → 走利用路径
    d_ws = pol_ws.decide(ws_state, ctx)
    assert d_ws.params.get("option_index") == 1, f"跨页尾键聚合失效（负收益选项被重选）: {d_ws.reason}"

    # 3r) Boss 前夜篝火优先回血（第 48 局实证：72% 血锻造后 Boss 战 -58 正好打死）
    rest_state = {
        "screen": "REST", "available_actions": ["choose_rest_option"],
        "rest": {"options": [
            {"index": 0, "option_id": "HEAL", "title": "休息", "is_enabled": True},
            {"index": 1, "option_id": "SMITH", "title": "锻造", "is_enabled": True}]},
        "run": {"current_hp": 58, "max_hp": 80, "gold": 0, "floor": 15,
                "deck": [{"card_id": "STRIKE_IRONCLAD", "upgraded": False}]},
    }
    ctx.rest_before_boss = False
    ctx.rest_proj_hp_pct = 1.0  # 本用例只验证常规线：隔离此前深图用例泄漏的绝境投影
    d_rest_norm = pol.decide(rest_state, ctx)
    # 常规逻辑：72% ≥ 安全线 55% → 锻造
    assert d_rest_norm.tags and d_rest_norm.tags[0] == ("rest", "smith"), \
        f"常规篝火应锻造: {d_rest_norm.reason}"
    ctx.rest_before_boss = True
    d_rest_boss = pol.decide(rest_state, ctx)
    assert d_rest_boss.tags and d_rest_boss.tags[0] == ("rest", "heal"), \
        f"Boss 前夜应优先回血: {d_rest_boss.reason}"
    ctx.rest_before_boss = False

    # 3t) 血量警戒带（第 54 局 F12 实证）：47.5% 血不在急需线内、篝火零加权，
    #     Shop(16.60|金币足够) 以 0.54 分压过 RestSite(16.06)，随后被迫 48% 血
    #     撞进子树里唯一的精英阵亡。45%~62% 区间篝火必须获得中等加权
    wary_state = {"screen": "MAP", "available_actions": ["choose_map_node"],
                  "map": {"available_nodes": [
                      {"index": 0, "row": 1, "col": 0, "node_type": "Monster"},
                      {"index": 1, "row": 1, "col": 1, "node_type": "RestSite"}], "nodes": []},
                  "run": {"current_hp": 40, "max_hp": 80, "gold": 0, "floor": 5, "deck": []}}
    d_wary = pol.decide(wary_state, ctx)
    assert d_wary.params.get("option_index") == 1 and "血量偏低" in d_wary.reason, \
        f"警戒带(50%血)应优先休整而非怪物连战: {d_wary.reason}"

    # 3u) 重生召唤物识别（第 52~53 局利齿之眼实证：单场被预测击杀 10+ 次，
    #     次次复活，kill_bonus 把输出全部吸走，雾菇本体意图 8→23 磨穿 80 血）：
    #     同一敌人同场被预测击杀 ≥2 次仍存活 → 击杀奖励归零（第 58 局升级，
    #     旧 ×0.25 压不住过量伤害满额计分的虚高），输出转向本体
    def spike_combat():
        return {"screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 3,
                "combat": {"player": {"current_hp": 80, "max_hp": 80, "block": 0, "energy": 3},
                           "hand": [
                               {"index": 0, "card_id": "CARD_STAB", "name": "小刺", "playable": True,
                                "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                                "dynamic_values": [{"name": "Damage", "current_value": 6}]},
                               {"index": 1, "card_id": "CARD_CLEAVE", "name": "重劈", "playable": True,
                                "energy_cost": 2, "requires_target": True,
                                "valid_target_indices": [0, 1],
                                "dynamic_values": [{"name": "Damage", "current_value": 12}]}],
                           "enemies": [
                               {"index": 0, "enemy_id": "RESPAWN_ADD", "name": "利齿之眼",
                                "current_hp": 5, "max_hp": 30, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 6}]},
                               {"index": 1, "enemy_id": "FOG_SOURCE", "name": "雾菇本体",
                                "current_hp": 60, "max_hp": 70, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 22}]}]},
                "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 5, "deck": []}}

    d_k1 = pol.decide(spike_combat(), ctx)
    assert d_k1.action == "play_card" and d_k1.params.get("target_index") == 0, \
        f"首次可击杀召唤物仍应优先斩杀: {d_k1.reason}"
    pol._combat_kills["RESPAWN_ADD"] = 2  # 模拟同场已两次预测击杀后它仍在场
    d_k2 = pol.decide(spike_combat(), ctx)
    assert d_k2.action == "play_card" and d_k2.params.get("target_index") == 1, \
        f"重生召唤物不应再吸引输出（应转火高威胁本体）: {d_k2.reason}"
    # 第 58 局复盘升级：确认重生体后击杀奖励必须归零（×0.25 曾压不住
    # 过量伤害满额 + 威胁分成的虚高，利齿之眼被追杀 13 次磨穿 83 血）
    assert pol._kill_bonus({"enemy_id": "RESPAWN_ADD"}, 6, 28, know.policy) == 0.0, \
        "重生召唤物击杀奖励未归零"
    assert pol._kill_bonus({"enemy_id": "FRESH_MOB"}, 6, 28, know.policy) > 0.0, \
        "正常敌人击杀奖励不应受影响"

    # 3x') 孤注一掷回合（第 59 局 Boss 战 T6 实证）：16 血/5 甲对 18 意图、
    #      手牌全是攻击无格挡牌——旧逻辑把全部攻击压到禁玩线，3 能量原样结束
    #      回合白吃 13 刀后下回合必死；修复后必须倾泻输出抢斩杀
    desperate_state = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 6,
        "combat": {"player": {"current_hp": 16, "max_hp": 80, "block": 5, "energy": 3},
                   "hand": [
                       {"index": 0, "card_id": "STRIKE_IRONCLAD", "name": "打击", "playable": True,
                        "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                        "dynamic_values": [{"name": "Damage", "current_value": 6}]},
                       {"index": 1, "card_id": "STRIKE_PLUS", "name": "打击+", "playable": True,
                        "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                        "dynamic_values": [{"name": "Damage", "current_value": 9}]},
                       {"index": 2, "card_id": "ANGER", "name": "愤怒", "playable": True,
                        "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                        "dynamic_values": [{"name": "Damage", "current_value": 6}]}],
                   "enemies": [{"index": 0, "enemy_id": "KIN_PRIEST", "name": "同族神官",
                                "current_hp": 40, "max_hp": 80, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 18}]}]},
        "run": {"current_hp": 16, "max_hp": 80, "gold": 0, "floor": 17, "deck": []},
    }
    d_des = pol.decide(desperate_state, ctx)
    assert d_des.action == "play_card", \
        f"无甲可补的致死回合必须孤注一掷输出而非弃权: {d_des.action}（{d_des.reason}）"

    # 3x'') 溢出格挡贬值（第 59 局 Boss 首回合实证：缺口 13 却连打坚毅24+重振精神10
    #       共 34 甲、3 能量零输出）——缺口补满后的纯溢出防牌须跌破出牌阈值，
    #       能量让给输出
    overblock_state = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 2,
        "combat": {"player": {"current_hp": 55, "max_hp": 80, "block": 30, "energy": 3},
                   "hand": [
                       {"index": 0, "card_id": "DEFEND_IRONCLAD", "name": "防御", "playable": True,
                        "energy_cost": 1, "requires_target": False,
                        "rules_text": "获得5点格挡",
                        "dynamic_values": [{"name": "Block", "current_value": 5}]},
                       {"index": 1, "card_id": "STRIKE_IRONCLAD", "name": "打击", "playable": True,
                        "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                        "dynamic_values": [{"name": "Damage", "current_value": 6}]}],
                   "enemies": [{"index": 0, "enemy_id": "KIN_BOSS", "name": "同族Boss",
                                "current_hp": 120, "max_hp": 160, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 10}]}]},
        "run": {"current_hp": 55, "max_hp": 80, "gold": 0, "floor": 17, "deck": []},
    }
    d_ob = pol.decide(overblock_state, ctx)
    assert d_ob.action == "play_card" and d_ob.params.get("card_index") == 1, \
        f"缺口已满时溢出格挡不得挤占输出: {d_ob.params}（{d_ob.reason}）"

    # 3y) Boss 入场血量要求线（第 60~61 局复盘）：路径投影此前只写进日志注释，
    #     「预计进 Boss 44%」照样沿 Monster 链磨到 Boss 门前（61 局 44% 入场被
    #     仪式兽处决；历史 44%~69% 入场 5 连亡）。低于要求线(65%)的投影按差值
    #     重罚——同一张地图，惩罚关闭时怪物积累路线胜出，惩罚生效后续航路线反超
    gate_map = {
        "screen": "MAP", "available_actions": ["choose_map_node"],
        "map": {"available_nodes": [
                    {"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                     "children": [{"row": 2, "col": 0}]},
                    {"index": 1, "row": 1, "col": 1, "node_type": "Shop",
                     "children": [{"row": 2, "col": 0}]}],
                "nodes": [
                    {"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                     "children": [{"row": 2, "col": 0}]},
                    {"index": 1, "row": 1, "col": 1, "node_type": "Shop",
                     "children": [{"row": 2, "col": 0}]},
                    {"row": 2, "col": 0, "node_type": "Boss"}],
                "boss_node": {"row": 2}},
        "run": {"current_hp": 56, "max_hp": 80, "gold": 0, "floor": 14, "deck": []}}
    know.policy["boss_entry_penalty"] = 0.0    # 复现旧行为：无入场要求线
    d_gate_off = pol.decide(dict(gate_map), ctx)
    assert d_gate_off.params.get("option_index") == 0, \
        f"基线失效（无惩罚时怪物积累路线应胜出）: {d_gate_off.reason}"
    know.policy["boss_entry_penalty"] = 110.0  # 生效：低投影入场被重罚，商店续航反超
    d_gate_on = pol.decide(dict(gate_map), ctx)
    assert d_gate_on.params.get("option_index") == 1, \
        f"Boss 入场要求线未生效（打一场后仅剩60%进场应让位续航路线）: {d_gate_on.reason}"
    solo_map = {
        "screen": "MAP", "available_actions": ["choose_map_node"],
        "map": {"available_nodes": [
                    {"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                     "children": [{"row": 2, "col": 0}]}],
                "nodes": [
                    {"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                     "children": [{"row": 2, "col": 0}]},
                    {"row": 2, "col": 0, "node_type": "Boss"}],
                "boss_node": {"row": 2}},
        "run": {"current_hp": 48, "max_hp": 80, "gold": 0, "floor": 14, "deck": []}}
    d_solo = pol.decide(solo_map, ctx)
    assert "进Boss血量预计" in d_solo.reason and "优先续航" in d_solo.reason, \
        f"低投影入场未在决策理由中标注: {d_solo.reason}"

    # 3z) 败局竞速（第 61 局 Boss 战 T3~T5 实证：意图 19→21→23→25 递增、净损
    #     速率 ~14/回合对 30 余血，每单回合都够不上 lethal/pyrrhic，引擎持续
    #     半攻半防温水等死）。按净损 EMA 外推 ≤2 回合必死时：解除能量预留并
    #     提速输出——打击必须压过防御；负例：无失血历史的新战斗中防御仍应胜出
    def race_state(hp_now, turn_no, combat_obj):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": turn_no,
            "combat": combat_obj,
            "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 17, "deck": []}}

    def race_combat(hp_now):
        return {"player": {"current_hp": hp_now, "max_hp": 80, "block": 0, "energy": 1},
                "hand": [
                    {"index": 0, "card_id": "RACE_STRIKE", "name": "重击", "playable": True,
                     "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                     "dynamic_values": [{"name": "Damage", "current_value": 15}]},
                    {"index": 1, "card_id": "RACE_GUARD", "name": "铁壁", "playable": True,
                     "energy_cost": 1, "requires_target": False,
                     "rules_text": "获得9点格挡",
                     "dynamic_values": [{"name": "Block", "current_value": 9}]}],
                "enemies": [{"index": 0, "enemy_id": "CEREMONIAL", "name": "仪式兽",
                             "current_hp": 200, "max_hp": 240, "block": 0,
                             "is_alive": True, "is_hittable": True,
                             "intents": [{"total_damage": 12}]}]}

    cb_race = race_combat(56)
    ctx.combat = cb_race
    for hp_now, turn_no in ((56, 1), (44, 2), (33, 3)):   # R1~R3：建立净损采样
        cb_race["player"]["current_hp"] = hp_now          # 游戏端每 tick 上报新血量
        pol.decide(race_state(hp_now, turn_no, cb_race), ctx)
    cb_race["player"]["current_hp"] = 22
    d_race = pol.decide(race_state(22, 4, cb_race), ctx)  # R4：外推 ≤2 回合死亡 → 竞速
    assert d_race.action == "play_card" and d_race.params.get("card_index") == 0 \
        and "败局竞速" in d_race.reason, \
        f"败局竞速未触发（死亡倒计时内应全力输出而非补防）: {d_race.action}（{d_race.reason}）"
    cb_fresh = race_combat(22)                           # 同局面但无失血历史的新战斗
    ctx.combat = cb_fresh
    d_ctrl = pol.decide(race_state(22, 1, cb_fresh), ctx)
    assert d_ctrl.action == "play_card" and d_ctrl.params.get("card_index") == 1, \
        f"败局竞速误触发（无失血历史不得放弃防御）: {d_ctrl.params}（{d_ctrl.reason}）"
    ctx.combat = None

    # 3v) 前期怪物加成的健康门槛（第 56 局复盘）：floor<=8 的 ×1.25 积累加成只在
    #     血量健康(≥警戒带62%)时生效——44%~62% 警戒带内曾吃满加成以 0.96 分压过
    #     Unknown 岔路（25.52 vs 24.56），随后漏斗行军阵亡
    def monster_map_reason(hp_now: int) -> str:
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": [{"index": 0, "row": 1, "col": 0,
                                           "node_type": "Monster"}], "nodes": []},
              "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 5, "deck": []}}
        return pol.decide(st, ctx).reason

    assert "前期需要战斗积累卡牌" in monster_map_reason(70), \
        f"健康血量应保留前期积累加成: {monster_map_reason(70)}"
    assert ("前期需要战斗积累卡牌" not in monster_map_reason(45)
            and "让位续航" in monster_map_reason(45)), \
        f"警戒带内前期加成必须失效: {monster_map_reason(45)}"

    # 3w) AoE 稀缺定价随存量递减（第 57 局 Boss 战实证）：16 张入组牌 0 张群体攻击，
    #     双子 Boss 七回合斩杀失败——首张 AoE 显著溢价(+3)，已有两张后回落(+0.5)
    aoe_card = {"card_id": "WHIRLWIND", "name": "旋风斩", "card_type": "Attack",
                "energy_cost": 1, "rules_text": "对所有敌人造成 5 点伤害。",
                "dynamic_values": [{"name": "Damage", "current_value": 5}]}
    plain_deck = [{"card_id": f"STRIKE_{i}", "card_type": "Attack", "energy_cost": 1}
                  for i in range(6)]
    aoe_deck = plain_deck[:4] + [
        {"card_id": "THUNDERCLAP_A", "card_type": "Attack", "energy_cost": 1,
         "rules_text": "对所有敌人造成 4 点伤害。"},
        {"card_id": "THUNDERCLAP_B", "card_type": "Attack", "energy_cost": 1,
         "rules_text": "对所有敌人造成 4 点伤害。"}]
    v_aoe_fresh = pol.eval_reward_card(dict(aoe_card), [dict(c) for c in plain_deck])
    v_aoe_dup = pol.eval_reward_card(dict(aoe_card), [dict(c) for c in aoe_deck])
    assert v_aoe_fresh - v_aoe_dup >= 2.0, \
        f"AoE 稀缺定价失效: fresh={v_aoe_fresh:.2f} dup={v_aoe_dup:.2f}"

    # 3x) 选牌界面跳过守卫（第 56 局 F2 实证）：经"打开卡牌奖励"进入的选牌屏没有
    #     阈值判断，-3.9 的未升级防御被硬塞进卡组；有 skip 动作且全员低于阈值应放弃，
    #     无跳过动作的强制选择屏则退回最小恶选择
    junk_pick_state = {
        "screen": "CARD_SELECTION",
        "available_actions": ["select_deck_card", "skip_reward_cards"],
        "selection": {"kind": "", "prompt": "将一张牌添加到你的牌组。", "min_select": 1,
                      "selected_count": 0, "can_confirm": False,
                      "cards": [{"index": 0, "card_id": "DEFEND_IRONCLAD", "name": "防御",
                                 "card_type": "Skill", "energy_cost": 1,
                                 "dynamic_values": [{"name": "Block", "current_value": 5}]}]},
        "run": {"current_hp": 60, "max_hp": 80, "gold": 0, "floor": 2, "deck": []}}
    d_junk = pol.decide(junk_pick_state, ctx)
    assert d_junk.action == "skip_reward_cards", \
        f"全负候选且有跳过动作时应放弃不拿: {d_junk.action}（{d_junk.reason}）"
    junk_pick_state["available_actions"] = ["select_deck_card"]
    d_junk2 = pol.decide(junk_pick_state, ctx)
    assert d_junk2.action == "select_deck_card", \
        f"无跳过动作的强制屏应退回最小恶选择: {d_junk2.action}（{d_junk2.reason}）"

    # 3s) 幻影局防护（第 50~51 局复盘）：大脑重启落在上一局结算屏时，
    #     旧 run_id 回声不得被当成新对局；零数据对局不得入账/存日志/触发复盘与 git
    agent_mod.llm_review = None   # 幻影 finalize 若发生会入队真实复盘请求，测试中必须禁用
    agent_mod.autogit = None      # 同理禁用自动 git 存档
    ag_fresh = agent_mod.Agent(dict(agent_mod.DEFAULT_CONFIG))  # 模拟重启后的新大脑进程
    assert ag_fresh.ctx.run_id == "run_unknown"
    go_echo = {"screen": "GAME_OVER", "run_id": "RUN_DEAD",
               "game_over": {"is_victory": False, "floor": 11},
               "run": {"current_hp": 0, "max_hp": 80, "gold": 99, "floor": 11}}
    ag_fresh._track(go_echo, policy.Decision(action=None))
    assert ag_fresh.ctx.run_id == "run_unknown", \
        f"结算屏旧 run_id 回声被误判为新对局: {ag_fresh.ctx.run_id}"
    ag_fresh._track({"screen": "EVENT", "run_id": "RUN_NEW",
                     "run": {"current_hp": 80, "max_hp": 80, "gold": 99, "floor": 1}},
                    policy.Decision(action=None))
    assert ag_fresh.ctx.run_id == "RUN_NEW", f"正常新对局未被识别: {ag_fresh.ctx.run_id}"
    runs_before = ag_fresh.know.stats["global"]["runs"]
    ag_fresh._finalize(victory=False, floor=6)
    assert ag_fresh.know.stats["global"]["runs"] == runs_before, "幻影局被计入生涯统计"
    assert list((tmp_agent / "runs").glob("*.json")) == [], "幻影局日志被写入 runs/"

    # 3aa) 组合战损维度姿态（第 64 局复盘）：FLYCONID+SNAPPING_JAXFRUIT 式组合
    #      死亡率仅 15% 但场均掉血 25.8（32% 血条）——旧判定只看死亡率，中性姿态下
    #      50 血对 26 意图仍全攻半防两回合被打穿。传 max_hp 按战损占比收紧；
    #      不传 max_hp 保持向后兼容（纯死亡率判定）
    know.stats.setdefault("enemies", {})["LOSSY_DUO"] = {
        "encounters": 13, "hp_lost_sum": 335.0, "deaths": 2, "wins": 11}
    st_loss = know.enemy_stance("LOSSY_DUO", None, 80)
    assert st_loss["urgent_hp_pct"] > 0.45 and st_loss["atk_mult"] < 1.0 \
        and "高危" in st_loss.get("danger", ""), f"组合战损姿态失效: {st_loss}"
    st_compat = know.enemy_stance("LOSSY_DUO")
    assert st_compat["atk_mult"] == 1.0 and "danger" not in st_compat, \
        f"不传 max_hp 应保持旧死亡率判定: {st_compat}"

    # 3bb) 高危组合解锁药水（第 64 局复盘）：普通房遭遇场均战损 ≥30% 血条的组合时，
    #      增益药水必须立即可用——旧门槛只认精英/Boss 房，异鱼之油拖到 9 血才掏出来
    def comp_potion_state():
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 2,
            "combat": {"player": {"current_hp": 50, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [],
                       "enemies": [{"index": 0, "enemy_id": "M", "name": "小怪",
                                    "current_hp": 30, "max_hp": 30, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": 10}]}]},
            "run": {"current_hp": 50, "max_hp": 80, "gold": 0, "floor": 5, "deck": [],
                    "potions": [{"index": 0, "potion_id": "OIL_P", "name": "异鱼之油",
                                 "description": "获得2点力量。", "occupied": True,
                                 "can_use": True, "usage": "combat"}]},
        }

    ctx.current_combat_is_hard = False
    ctx.combat = {"comp_id": "LOSSY_DUO", "node_type": "Monster"}  # 场均 25.8 ≥ 24 → 硬仗
    d_cp1 = pol.decide(comp_potion_state(), ctx)
    assert d_cp1.action == "use_potion", f"高危组合未解锁增益药水: {d_cp1.action}（{d_cp1.reason}）"
    ctx.combat = {"comp_id": "HARMLESS", "node_type": "Monster"}   # 无数据组合（先验12<24）不得烧药
    d_cp2 = pol.decide(comp_potion_state(), ctx)
    assert d_cp2.action != "use_potion", f"低危组合烧掉增益药水: {d_cp2.action}（{d_cp2.reason}）"
    ctx.combat = None

    # 3cc) Boss 前夜智能锻造（第 63 局复盘，第 84~85 批接线 heal_mult）：
    #      boss_eve_smith_heal_mult 此前从未被读取、条件退化回旧版「≥满血」；
    #      接线后战损线 = 回血量(30%×最大生命)×倍数。实测 Boss 分档场均 23.8，
    #      对 80 血角色恰好压线——场均 ≥24 时入场线达标则改锻造，否则回血
    know.stats["enemies"]["BOSS_HOG"] = {
        "encounters": 6, "hp_lost_sum": 200.0, "deaths": 2, "wins": 4,
        "boss_encounters": 2, "boss_hp_lost_sum": 170.0, "boss_deaths": 1}
    know.stats["enemies"]["BOSS_PIG"] = {
        "encounters": 6, "hp_lost_sum": 200.0, "deaths": 2, "wins": 4,
        "boss_encounters": 2, "boss_hp_lost_sum": 180.0, "boss_deaths": 1}
    bl, bn = know.boss_loss_stats()
    assert bn == 4 and abs(bl - 87.5) < 1e-6, f"Boss 分档统计错误: {bl}/{bn}"
    ctx.rest_before_boss = True
    # 锻造线（第 97~98 批复盘）：血量 + 回血量×0.5 ≥ 满血（≥85%）才改锻造——
    # 战损合并记账后整场 Boss 战损必然 ≥ 回血量，72% 血也去锻造会重演第 48 局惨案
    rest_boss_state = dict(rest_state)
    rest_boss_state["run"] = {"current_hp": 70, "max_hp": 80, "gold": 0, "floor": 15,
                              "deck": [{"card_id": "STRIKE_IRONCLAD", "upgraded": False}]}
    d_eve_smith = pol.decide(rest_boss_state, ctx)
    assert d_eve_smith.tags[0] == ("rest", "smith"), f"Boss前夜智能锻造未触发: {d_eve_smith.reason}"
    know.stats["enemies"]["BOSS_HOG"]["boss_hp_lost_sum"] = 46.0   # 场均值降至 22.5 < 回血量 24
    know.stats["enemies"]["BOSS_PIG"]["boss_hp_lost_sum"] = 44.0
    d_eve_heal = pol.decide(rest_boss_state, ctx)
    assert d_eve_heal.tags[0] == ("rest", "heal"), f"战损低于回血量应回血: {d_eve_heal.reason}"
    know.stats["enemies"]["BOSS_HOG"]["boss_hp_lost_sum"] = 170.0
    know.stats["enemies"]["BOSS_PIG"]["boss_hp_lost_sum"] = 180.0
    rest_mid = dict(rest_boss_state)
    rest_mid["run"] = dict(rest_boss_state["run"], current_hp=62)  # 77.5% < 锻造线 85%
    d_eve_mid = pol.decide(rest_mid, ctx)
    assert d_eve_mid.tags[0] == ("rest", "heal"), \
        f"锻造线以下的回血价值不应被放弃（48局复现）: {d_eve_mid.reason}"
    rest_low = dict(rest_boss_state)
    rest_low["run"] = dict(rest_boss_state["run"], current_hp=38)  # 47.5% < 入场线 65%
    d_eve_low = pol.decide(rest_low, ctx)
    assert d_eve_low.tags[0] == ("rest", "heal"), f"入场线未达标应回血: {d_eve_low.reason}"
    ctx.rest_before_boss = False

    # 3dd) 事件加牌稀释记账（第 63 局复盘）：带走这颗蛋把不可打出的鸟蛋混进卡组
    #      （Boss 战多次占据手牌 ✗ 位），结算只记 hp/gold 全零看似免费——
    #      card_delta 记账后每净增 1 张牌 -2 分，强正收益事件不被误伤
    know.commit_event_option("EGG_EV", "TAKE", 0.0, 0.0, died=False, deck_delta=1)
    v_egg, n_egg = know.event_option_value("EGG_EV", "TAKE")
    assert v_egg <= -2.0 and n_egg == 1, f"加牌稀释代价未入账: {v_egg}"
    know.commit_event_option("GIFT_EV", "CARD", 0.0, 200.0, died=False, deck_delta=1)
    v_gift, _ = know.event_option_value("GIFT_EV", "CARD")
    assert v_gift > 0.0, f"强正收益加牌不应被误伤: {v_gift}"

    # 3ee) 事件结算管线：pending_event 元组新增卡组规模字段后读写两端必须一致
    ag.ctx.reset_for("RUN_EVT", 0)
    ag._track({"screen": "EVENT", "run_id": "RUN_EVT",
               "run": {"current_hp": 80, "max_hp": 80, "gold": 50, "floor": 3,
                       "deck": [{"card_id": "A"}]}},
              policy.Decision(action="choose_event_option",
                              tags=[("event_choice", "PLUMB_EV", "TAKE")]))
    ag._track({"screen": "MAP", "run_id": "RUN_EVT",
               "run": {"current_hp": 80, "max_hp": 80, "gold": 60, "floor": 3,
                       "deck": [{"card_id": "A"}, {"card_id": "EGG"}]}},
              policy.Decision(action=None))
    pe = tknow.stats["events"].get("PLUMB_EV", {}).get("TAKE")
    assert pe and pe["n"] == 1 and pe.get("card_delta_sum") == 1.0 \
        and pe["gold_delta_sum"] == 10.0 and pe["hp_delta_sum"] == 0.0, \
        f"事件卡牌增量管线断裂: {pe}"

    # 3ff) 出牌黑名单索引漂移防护（第 65~66 局复盘实锤）：mod 手牌 index 是位置
    #      序号，打出一张牌后剩余牌 index 集体前移；叠加旧版把成功状态 completed
    #      当失败拉黑——每打出一张牌就误杀一张未出牌。66 局 F5：5 张手打出 2 张后
    #      双打击同时被误拉黑，1 能量弃权白吃 15 意图；65 局 F11 致死回合手握打击
    #      同型阵亡。修复后黑名单以「手牌数量未变」为有效期，手牌一变整体释放；
    #      手牌未变的 409 重试防护保持精确拉黑不变。
    raiders = [{"index": 0, "enemy_id": "RAIDER", "name": "劫掠者", "current_hp": 40,
                "max_hp": 40, "block": 0, "is_alive": True, "is_hittable": True,
                "intents": [{"total_damage": 15}]}]

    def poison_hand(n_strikes):
        cards = [{"index": 0, "card_id": "DEFEND_IRONCLAD", "name": "防御", "playable": True,
                  "energy_cost": 1, "requires_target": False, "rules_text": "获得5点格挡",
                  "dynamic_values": [{"name": "Block", "current_value": 5}]}]
        for i in range(n_strikes):
            cards.append({"index": i + 1, "card_id": "STRIKE_IRONCLAD", "name": "打击",
                          "playable": True, "energy_cost": 1, "requires_target": True,
                          "valid_target_indices": [0],
                          "dynamic_values": [{"name": "Damage", "current_value": 6}]})
        return cards

    def poison_state(energy, hand):
        return {"screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
                "turn": 99,
                "combat": {"player": {"current_hp": 87, "max_hp": 87, "block": 5,
                                      "energy": energy},
                           "hand": hand, "enemies": raiders},
                "run": {"current_hp": 87, "max_hp": 87, "gold": 0, "floor": 5, "deck": []}}

    h_left = [dict(c, index=i) for i, c in enumerate(poison_hand(2))]  # 打出2张后剩3→2张打击
    pol.decide(poison_state(1, [dict(c) for c in h_left]), ctx)        # 建立回合上下文
    pol._failed_this_turn = {0, 1}     # 复现旧版级联误拉黑：两张打击全在黑名单
    pol._failed_hand_len = 4           # 且失败发生在更早的 4 张手时期
    d_pf = pol.decide(poison_state(1, [dict(c) for c in h_left]), ctx)
    assert d_pf.action == "play_card" and d_pf.params.get("card_index") == 0, \
        f"手牌已变化时旧黑名单必须整体释放（66局F5弃权复现）: {d_pf.action}（{d_pf.reason}）"
    pol._failed_this_turn = {1}        # 同尺寸手牌：被拉黑实例仍须精确跳过（31局语义）
    pol._failed_hand_len = len(h_left)
    d_pg = pol.decide(poison_state(1, [dict(c) for c in h_left]), ctx)
    assert d_pg.action == "play_card" and d_pg.params.get("card_index") == 0, \
        f"同尺寸手牌的黑名单防护失效: {d_pg.params}（{d_pg.reason}）"

    # 3gg) 高危组合（死亡率维度）自动认定硬仗（第 65~66 局复盘）：头号杀手
    #      FUZZY_WURM+SHRINKER_BEETLE 25战11死（44%）多出现在普通怪房，
    #      _start_combat 旧逻辑只认 Elite/Boss 房——药水 premium 门对它永不开启，
    #      两局均带药进坟。死亡率 ≥ danger_comp_hard_death_rate 的组合自动升级；
    #      负例：低死亡率且场均战损 <30% 血条的温和组合不得误判。
    tknow.stats.setdefault("enemies", {})["DEATHLY_DUO"] = {
        "encounters": 9, "hp_lost_sum": 180.0, "deaths": 4, "wins": 5}   # 44%死/场均20(<24)
    tknow.stats["enemies"]["MILD_DUO"] = {
        "encounters": 8, "hp_lost_sum": 160.0, "deaths": 1, "wins": 7}   # 12.5%死/场均20
    ag._start_combat({"max_hp": 80, "floor": 5}, "DEATHLY_DUO", "Monster", 80)
    assert ag.ctx.current_combat_is_hard, \
        "死亡率≥30%的普通房组合应自动认定为硬仗（解锁药水）"
    ag._start_combat({"max_hp": 80, "floor": 5}, "MILD_DUO", "Monster", 80)
    assert not ag.ctx.current_combat_is_hard, "低危组合不应被误判为硬仗"
    ag.ctx.combat = None
    ag.ctx.current_combat_is_hard = False

    # 3hh) 拿牌门槛随卡组膨胀动态抬升（第 65 局复盘）：固定阈值 2.0 下 14 张/局的
    #      注水照单全收（SHRUG_IT_OFF×5 成 24 张卡组），-0.9/张 减分压不住 8 分
    #      格挡牌——软上限形同虚设。超软上限后门槛每张 +1.5，越臃肿越只拿精品；
    #      小卡组行为不变（同一张牌在空卡组下照常可拿）。
    bloated = [{"card_id": f"BLOAT_ATK_{i}", "card_type": "Attack", "energy_cost": 1}
               for i in range(22)]
    mid_skill = {"index": 0, "card_id": "GUARD_SMALL", "name": "小盾", "card_type": "Skill",
                 "energy_cost": 1, "rules_text": "获得4点格挡",
                 "dynamic_values": [{"name": "Block", "current_value": 4}]}
    v_mid = pol.eval_reward_card(dict(mid_skill), [dict(c) for c in bloated])
    thr_bloat = pol._pick_threshold(bloated)
    assert v_mid >= float(know.policy["card_pick_threshold"]), \
        f"对照失效：基础阈值下该牌本应达标 v={v_mid:.2f}"
    assert v_mid < thr_bloat, \
        f"膨胀门槛未抬过边际牌价值: v={v_mid:.2f} thr={thr_bloat:.2f}"
    bloat_state = {"screen": "CARD_SELECTION",
                   "available_actions": ["select_deck_card", "skip_reward_cards"],
                   "selection": {"kind": "", "prompt": "将一张牌添加到你的牌组。",
                                 "min_select": 1, "selected_count": 0, "can_confirm": False,
                                 "cards": [dict(mid_skill)]},
                   "run": {"current_hp": 60, "max_hp": 80, "gold": 0, "floor": 9,
                           "deck": [dict(c) for c in bloated]}}
    d_bl1 = pol.decide(bloat_state, ctx)
    assert d_bl1.action == "skip_reward_cards", \
        f"膨胀卡组应跳过平庸牌: {d_bl1.action}（{d_bl1.reason}）"
    bloat_state["run"]["deck"] = []
    d_bl2 = pol.decide(bloat_state, ctx)
    assert d_bl2.action == "select_deck_card", \
        f"空卡组应照常拿牌: {d_bl2.action}（{d_bl2.reason}）"

    # 3ii) 战斗中手牌献祭（第 71 局实锤）：Vantom 每阶段结束强制从手牌交一张，
    #      旧通用分支按"最高价值"点选——五连献祭把火焰屏障+×3/耸肩无视+×2 喂给
    #      Boss，伤口在候选里却视而不见，防御核心被拆光后意图 26→32 磨死。
    #      修复后 combat_hand 选屏按 badness 交最不值钱者，且逐张递进；
    #      负例：普通拿牌屏（无 combat_hand 语义）仍取最高价值。
    tribute_cards = [
        {"index": 0, "card_id": "SHRUG_IT_OFF", "name": "耸肩无视+", "card_type": "Skill",
         "energy_cost": 1, "rules_text": "获得11点格挡。抽1张牌。",
         "dynamic_values": [{"name": "Block", "current_value": 11},
                            {"name": "Draw", "current_value": 1}]},
        {"index": 1, "card_id": "WOUND", "name": "伤口", "card_type": "Status",
         "energy_cost": 1, "rules_text": "无法打出。"},
        {"index": 2, "card_id": "STRIKE_IRONCLAD", "name": "打击", "card_type": "Attack",
         "energy_cost": 1, "upgraded": False,
         "dynamic_values": [{"name": "Damage", "current_value": 6}]}]
    tribute_state = {"screen": "CARD_SELECTION",
                     "available_actions": ["select_deck_card"],
                     "selection": {"kind": "combat_hand_select", "prompt": "选择一张牌。",
                                   "min_select": 1, "selected_count": 0, "can_confirm": False,
                                   "cards": [dict(c) for c in tribute_cards]},
                     "run": {"current_hp": 32, "max_hp": 80, "gold": 37, "floor": 71, "deck": []}}
    d_tb1 = pol.decide(dict(tribute_state), ctx)
    assert d_tb1.params.get("option_index") == 1 and "献祭" in d_tb1.reason, \
        f"战斗献祭必须交出最不值钱的牌（应选伤口而非耸肩无视）: {d_tb1.reason}"
    d_tb2 = pol.decide(dict(tribute_state), ctx)
    assert d_tb2.params.get("option_index") == 2 and "献祭" in d_tb2.reason, \
        f"多次献祭应逐张交出次差者（伤口已交出后应交打击）: {d_tb2.reason}"
    gain_state = {"screen": "CARD_SELECTION",
                  "available_actions": ["select_deck_card"],
                  "selection": {"kind": "", "prompt": "将一张牌添加到你的牌组。",
                                "min_select": 1, "selected_count": 0, "can_confirm": False,
                                "cards": [dict(c) for c in tribute_cards]},
                  "run": {"current_hp": 60, "max_hp": 80, "gold": 37, "floor": 71, "deck": []}}
    d_tg = pol.decide(gain_state, ctx)
    assert d_tg.params.get("option_index") == 0 and "献祭" not in d_tg.reason, \
        f"普通拿牌屏被误判为献祭: {d_tg.reason}"

    # 3jj) 同名重复递减 + 「拿了不打」贬值（第 71 局）：单局 SHRUG_IT_OFF×5、
    #      FLAME_BARRIER 生涯 13 拿 6 打——同名牌从第 3 张起每张 -3，
    #      长期打不出去的牌拾取端额外 -4；健康出牌率的对照牌不受影响。
    guard_card = {"card_id": "GUARD_WALL", "name": "高墙", "card_type": "Skill",
                  "energy_cost": 1, "rules_text": "获得8点格挡。",
                  "dynamic_values": [{"name": "Block", "current_value": 8}]}

    def guard_deck(n):
        return [dict(guard_card) for _ in range(n)]

    v_g0 = pol.eval_reward_card(dict(guard_card), [])
    v_g2 = pol.eval_reward_card(dict(guard_card), guard_deck(2))
    v_g3 = pol.eval_reward_card(dict(guard_card), guard_deck(3))
    v_g4 = pol.eval_reward_card(dict(guard_card), guard_deck(4))
    thr_pick = float(know.policy["card_pick_threshold"])
    assert v_g0 >= thr_pick, f"首张合格防牌应可拿: {v_g0:.2f}"
    # 已有 2 张时候选 -3；此后每多一张再 -3（deck 非空使格挡稀缺 +1.5 生效，
    # 故首段差值为 -3+1.5=1.5）
    assert abs((v_g0 - v_g2) - 1.5) < 1e-6, \
        f"同名重复第3张应-3(叠加稀缺+1.5): {v_g0:.2f}→{v_g2:.2f}"
    for prev, cur in ((v_g2, v_g3), (v_g3, v_g4)):
        assert abs((prev - cur) - 3.0) < 1e-6, \
            f"同名重复递减步长应为-3: {prev:.2f}→{cur:.2f}"
    assert v_g2 >= thr_pick > v_g3, \
        f"递减阈值穿越点错误: v_g2={v_g2:.2f} v_g3={v_g3:.2f}"
    know.stats.setdefault("cards", {})["NEVER_PLAYED"] = {
        "seen": 20, "picked": 13, "plays": 6, "outcome_sum": 130.0, "bias": 0.0}
    know.stats["cards"]["ALWAYS_PLAYED"] = {
        "seen": 20, "picked": 10, "plays": 40, "outcome_sum": 100.0, "bias": 0.0}
    np_card = dict(guard_card, card_id="NEVER_PLAYED")
    ap_card = dict(guard_card, card_id="ALWAYS_PLAYED")
    v_np = pol.eval_reward_card(np_card, [])
    v_ap = pol.eval_reward_card(ap_card, [])
    assert v_ap - v_np >= 3.9, \
        f"「拿了不打」贬值失效: never={v_np:.2f} always={v_ap:.2f}"

    # 3kk) 混合牌攻防双面向（第 71 局 Boss 终盘 05:33:08 实证）：火焰屏障+
    #      （伤害6+格挡16）被解析成弱攻击，致死回合被压到禁玩线弃权阵亡——
    #      其本体格挡足以完全抵消当轮意图。有缺口时防御面向必须胜出；
    #      无缺口时攻击面向自动回落（负例：满甲空意图仍正常输出）。
    fb_plus = {"index": 0, "card_id": "FLAME_BARRIER", "name": "火焰屏障+", "playable": True,
               "energy_cost": 1, "requires_target": False,
               "rules_text": "获得16点格挡。下个敌人回合开始时，对攻击你的敌人造成等量伤害。",
               "dynamic_values": [{"name": "Damage", "current_value": 6},
                                  {"name": "Block", "current_value": 16}]}
    fb_lethal = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 21,
        "combat": {"player": {"current_hp": 27, "max_hp": 80, "block": 0, "energy": 3},
                   "end_turn_will_kill_player": True,
                   "hand": [dict(fb_plus)],
                   "enemies": [{"index": 0, "enemy_id": "VANTOM", "name": "墨影幻灵",
                                "current_hp": 90, "max_hp": 173, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 15}]}]},
        "run": {"current_hp": 27, "max_hp": 80, "gold": 37, "floor": 17, "deck": []}}
    d_fb = pol.decide(fb_lethal, ctx)
    assert d_fb.action == "play_card" and "格挡16" in d_fb.reason, \
        f"混合牌致死回合应走防御面向补防而非弃权: {d_fb.action}（{d_fb.reason}）"
    fb_calm = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 22,
        "combat": {"player": {"current_hp": 27, "max_hp": 80, "block": 30, "energy": 3},
                   "hand": [dict(fb_plus)],
                   "enemies": [{"index": 0, "enemy_id": "VANTOM", "name": "墨影幻灵",
                                "current_hp": 90, "max_hp": 173, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": []}]},
        "run": {"current_hp": 27, "max_hp": 80, "gold": 37, "floor": 17, "deck": []}}
    d_fbc = pol.decide(fb_calm, ctx)
    assert d_fbc.action == "play_card" and "伤害≈6" in d_fbc.reason, \
        f"缺口已满时混合牌应回落攻击面: {d_fbc.action}（{d_fbc.reason}）"

    # 3mm) 意图升级防御前置（第 84~85 批复盘）：升级型敌人（毛绒伏地虫
    #      4→7→24→…→31、仪式兽 Boss 18→20→22→24→26）在意图跳升回合，
    #      防御价值与紧急线同步上调——旧引擎只看当轮意图，升级前夜照常
    #      倾泻输出，两局均在跳升后 2~3 回合内被磨死
    def esc_state(turn_no, incoming):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": turn_no,
            "combat": {"player": {"current_hp": 40, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [
                           {"index": 0, "card_id": "ESC_BLADE", "name": "利刃", "playable": True,
                            "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                            "dynamic_values": [{"name": "Damage", "current_value": 10}]},
                           {"index": 1, "card_id": "ESC_WALL", "name": "壁垒", "playable": True,
                            "energy_cost": 1, "requires_target": False,
                            "rules_text": "获得10点格挡",
                            "dynamic_values": [{"name": "Block", "current_value": 10}]}],
                       "enemies": [{"index": 0, "enemy_id": "RISER", "name": "蓄力怪",
                                    "current_hp": 60, "max_hp": 80, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": incoming}]}]},
            "run": {"current_hp": 40, "max_hp": 80, "gold": 0, "floor": 9, "deck": []}}

    pol_esc_ctrl = policy.Policy(know, random.Random(7))   # 对照：无历史的新战斗
    d_esc0 = pol_esc_ctrl.decide(esc_state(2, 12), ctx)
    assert d_esc0.action == "play_card" and d_esc0.params.get("card_index") == 0, \
        f"对照失效（无升级历史时输出应胜出）: {d_esc0.reason}"
    ctx.combat = {"comp_id": "RISER"}                      # 绑定战斗实例身份供轨迹采样
    pol_esc = policy.Policy(know, random.Random(7))
    pol_esc.decide(esc_state(1, 7), ctx)                   # R1：低意图（升级前夜）
    d_esc1 = pol_esc.decide(esc_state(2, 12), ctx)         # R2：意图 +5 跳升
    assert d_esc1.action == "play_card" and d_esc1.params.get("card_index") == 1 \
        and "意图升级" in d_esc1.reason, \
        f"意图跳升回合应防御前置: {d_esc1.action}（{d_esc1.reason}）"
    ctx.combat = None

    # 3nn) 连续作战疲劳压制（第 84~85 批复盘）：84 局 F2~F9 七连战、第 RJG 局
    #      F2~F8 七连战，均力竭阵亡于链尾——地图投影按场均先验线性扣血，
    #      捕捉不到复利式疲劳。连续 ≥3 个战斗节点后怪物权重必须被压制
    def streak_reason(tags):
        stx = type("StreakCtx", (), {"credit_tags": tags})()
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": [{"index": 0, "row": 1, "col": 0,
                                           "node_type": "Monster"}], "nodes": []},
              "run": {"current_hp": 70, "max_hp": 80, "gold": 0, "floor": 5, "deck": []}}
        return pol.decide(st, stx).reason

    r_fresh = streak_reason([])
    r_tired = streak_reason([("map_node", "Monster")] * 4)
    assert "前期需要战斗积累卡牌" in r_fresh and "疲劳压制" not in r_fresh, \
        f"对照失效（无连战史应保留积累加成）: {r_fresh}"
    assert "疲劳压制" in r_tired, f"连续作战疲劳未生效: {r_tired}"

    # 3oo) 姿态死亡率门槛与斜率校准（第 84~85 批复盘）：头号杀手
    #      FUZZY_WURM+SHRINKER_BEETLE 41战12死=29.3%，旧公式（门槛0.30）
    #      输出完全中性——防御姿态门槛(0.25)必须低于药水解锁门槛(0.30)且更陡
    know.stats.setdefault("enemies", {})["NEAR_GATE_KILLER"] = {
        "encounters": 41, "hp_lost_sum": 766.0, "deaths": 12, "wins": 29}
    st_ng = know.enemy_stance("NEAR_GATE_KILLER", None, 80)
    assert st_ng["urgent_hp_pct"] > 0.45 and st_ng["blk_mult"] > 1.0 \
        and st_ng["atk_mult"] < 1.0 and "高危" in st_ng.get("danger", ""), \
        f"29%死亡率组合的姿态仍为中性: {st_ng}"
    assert know.enemy_stance("NO_DATA_COMP")["atk_mult"] == 1.0, "无数据组合应为中性"

    # 3pp) Boss 长战磨死的演化分级（第 84~85 批复盘）：固定 ±0.05/+1 的释放
    #      速度需 ~30 局才能把 block_safety 拉回有效区——步长须按战斗时长放大，
    #      且 Boss 长战单独加码 boss_atk_mult（不动普通战斗攻防平衡）
    from types import SimpleNamespace
    from reflect import finalize_run
    rknow = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-reflect-")))
    rctx = SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "BOSS_X", "rounds": 8, "node_type": "Boss"},
        death_was_elite=False, death_hp_pct_at_entry=0.9,
        credit_tags=[], rests_healed_at_full=0, ascension=0, combat_notes=[])
    finalize_run(rknow, rctx, victory=False, final_floor=17)
    assert abs(rknow.policy["boss_atk_mult"] - 1.20) < 1e-9, \
        f"boss_atk_mult 未演化: {rknow.policy['boss_atk_mult']}"
    assert abs(rknow.policy["kill_bonus"] - 14.0) < 1e-9, \
        f"kill_bonus 步长未按时长分级: {rknow.policy['kill_bonus']}"
    assert rknow.policy["block_safety"] < 1.0, \
        f"block_safety 未释放: {rknow.policy['block_safety']}"

    # 3qq) 灰区精英悲观投影复核（第 86~87 批复盘）：87 局以 86% 血（灰区）
    #      接受旧日雕像，实测战损 54（64% 血条）≈ Elite 实测场均的 3 倍——
    #      均值先验 + 灰区 0.5 谨慎权重挡不住战损分布的重尾。灰区内改用
    #      「均值 × 悲观系数」复核：悲观投影战后血量 < 投影线 → 整条路径规避；
    #      硬线以上不受影响；悲观系数/投影线放宽后同一局面恢复灰区放行。
    def grey_elite_reason(hp_now: int):
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": [{"index": 0, "row": 1, "col": 0,
                                           "node_type": "Elite"}], "nodes": []},
              "run": {"current_hp": hp_now, "max_hp": 80, "gold": 200, "floor": 10,
                      "deck": [{"card_id": f"CARD_{i}"} for i in range(6)]}}
        return pol.decide(st, ctx).reason

    # 隔离此前用例灌入的 rooms/enemies 实测数据（否则校准系数漂移，
    # 断言数值不可复现）；退出前恢复
    saved_rooms_elite_q = know.stats.setdefault("rooms", {}).pop("Elite", None)
    saved_enemies_q = know.stats.get("enemies", {})
    know.stats["enemies"] = {}
    old_hard_q = know.policy["elite_min_hp_pct"]
    know.policy["elite_min_hp_pct"] = 0.90          # 灰区 62%~90%
    know.policy["elite_soft_hp_pct"] = 0.62
    r_veto = grey_elite_reason(69)   # 86%：悲观投影战后仅剩 40% < 60% → 规避
    assert "规避精英" in r_veto and "预计战后" in r_veto, \
        f"灰区悲观复核未拦截（87 局同款入场血量）: {r_veto}"
    r_hard = grey_elite_reason(73)   # 91% ≥ 硬线：不受灰区复核影响
    assert "规避精英" not in r_hard and "灰区" not in r_hard, \
        f"硬线以上被悲观复核误伤: {r_hard}"
    know.policy["elite_grey_safety_mult"] = 1.0      # 演化放宽：悲观系数→1.0、投影线→0.55
    know.policy["elite_grey_proj_floor"] = 0.55
    r_loose = grey_elite_reason(69)
    assert "规避精英" not in r_loose and "灰区" in r_loose, \
        f"悲观参数敏感性失效（放宽后应恢复灰区放行）: {r_loose}"
    know.policy["elite_min_hp_pct"] = old_hard_q
    know.policy.pop("elite_soft_hp_pct", None)
    know.policy.pop("elite_grey_safety_mult", None)
    know.policy.pop("elite_grey_proj_floor", None)
    if saved_rooms_elite_q is not None:
        know.stats["rooms"]["Elite"] = saved_rooms_elite_q
    know.stats["enemies"] = saved_enemies_q

    # 3rr) 精英死亡演化改接悲观系数（第 86~87 批复盘）：elite_min_hp_pct 已在
    #      0.9 上限顶格空转——精英死亡信号必须驱动仍有余量的新旋钮，
    #      且胜利时双向释放（演化必须可逆）
    eknow = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-grey-")))
    ectx = SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "BYGONE_EFFIGY", "rounds": 6, "node_type": "Elite"},
        death_was_elite=True, death_hp_pct_at_entry=0.86,
        credit_tags=[], rests_healed_at_full=0, ascension=0, combat_notes=[])
    finalize_run(eknow, ectx, victory=False, final_floor=17)
    assert abs(eknow.policy["elite_grey_safety_mult"] - 1.7) < 1e-9, \
        f"精英死亡未上调灰区悲观系数: {eknow.policy['elite_grey_safety_mult']}"
    vctx = SimpleNamespace(
        died_to_event=None, died_in_combat=None,
        death_was_elite=False, death_hp_pct_at_entry=None,
        credit_tags=[], rests_healed_at_full=0, ascension=0, combat_notes=[])
    finalize_run(eknow, vctx, victory=True, final_floor=20)
    assert abs(eknow.policy["elite_grey_safety_mult"] - 1.6) < 1e-9, \
        f"胜利未释放灰区悲观系数（单向棘轮复发）: {eknow.policy['elite_grey_safety_mult']}"

    # 3ss) 姿态-药水门槛一致性（第 88 局复盘）：头号杀手 FUZZY+SHRINKER 式组合
    #      （死亡率 29.3% < 硬仗门槛 0.30、场均战损 18.7 < 0.30×80=24）此前从两条
    #      药水门槛的缝隙漏网——88 局 F8 姿态系统从第 1 回合就警告「⚠高危组合」，
    #      攻击药水却被锁到 20 血、意图已滚到 38。姿态认定高危的战斗，药水门必须
    #      同步开启（同一证据，同一结论）；无数据组合仍不得烧药
    def gap_potion_state():
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 1,
            "combat": {"player": {"current_hp": 64, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [],
                       "enemies": [{"index": 0, "enemy_id": "K", "name": "毛绒伏地虫",
                                    "current_hp": 30, "max_hp": 30, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": 4}]}]},
            "run": {"current_hp": 64, "max_hp": 80, "gold": 0, "floor": 8, "deck": [],
                    "potions": [{"index": 0, "potion_id": "ATK_P", "name": "攻击药水",
                                 "description": "造成12点伤害。", "occupied": True,
                                 "can_use": True, "usage": "combat"}]},
        }

    ctx.current_combat_is_hard = False
    ctx.combat = {"comp_id": "NEAR_GATE_KILLER", "node_type": "Monster"}  # 29.3%死/场均18.7：姿态高危但两条药水门槛都不触发
    d_gap1 = pol.decide(gap_potion_state(), ctx)
    assert d_gap1.action == "use_potion", \
        f"姿态高危组合未解锁攻击药水（88局F8复现）: {d_gap1.action}（{d_gap1.reason}）"
    ctx.combat = {"comp_id": "NO_DATA_COMP", "node_type": "Monster"}
    d_gap2 = pol.decide(gap_potion_state(), ctx)
    assert d_gap2.action != "use_potion", \
        f"无数据组合误烧攻击药水: {d_gap2.action}（{d_gap2.reason}）"
    ctx.combat = None
    ctx.current_combat_is_hard = False

    # 3tt) 输出饥饿感知拿牌（第 88~89 批复盘）：占比维度看不见「量足质弱」——
    #      89 局卡组攻击占比达标、回合爆发仍是几张 6 伤打击的水平，88% 血进
    #      一幕 Boss 11 回合仅打出 ~198 伤输掉斩杀竞速。爆发吞吐量低于
    #      deck_burst_floor 时，高质攻击（单牌总伤 ≥12 且 ≥7 伤/能耗）获得加分；
    #      弱攻击（打击级）不得因饥饿虚高（保护 3a 的占比衰减语义）。
    #      用同一副卡组切换门槛做隔离，排除占比上下文的混淆
    def _mk_strike(i):
        return {"card_id": f"STRIKE_{i}", "card_type": "Attack", "energy_cost": 1,
                "dynamic_values": [{"name": "Damage", "current_value": 6}]}

    starved_deck = ([_mk_strike(i) for i in range(5)]
                    + [{"card_id": f"DEFEND_{i}", "card_type": "Skill", "energy_cost": 1,
                        "dynamic_values": [{"name": "Block", "current_value": 5}]} for i in range(4)])
    big_atk = {"card_id": "CINDER", "name": "余烬", "card_type": "Attack", "energy_cost": 2,
               "dynamic_values": [{"name": "Damage", "current_value": 18}]}
    saved_floor_t = know.policy.get("deck_burst_floor", 30.0)
    know.policy["deck_burst_floor"] = 30.0   # 起步型卡组爆发 18 → 饥饿
    v_big_on = pol.eval_reward_card(dict(big_atk), [dict(c) for c in starved_deck])
    v_weak_on = pol.eval_reward_card(dict(weak_atk), [dict(c) for c in starved_deck])
    know.policy["deck_burst_floor"] = 0.0    # 关闭饥饿判定（其余评分路径完全一致）
    v_big_off = pol.eval_reward_card(dict(big_atk), [dict(c) for c in starved_deck])
    v_weak_off = pol.eval_reward_card(dict(weak_atk), [dict(c) for c in starved_deck])
    know.policy["deck_burst_floor"] = saved_floor_t
    assert v_big_on - v_big_off >= 2.5, \
        f"输出饥饿未给高质攻击加分: on={v_big_on:.2f} off={v_big_off:.2f}"
    assert abs(v_weak_on - v_weak_off) < 1e-6, \
        f"打击级弱攻击被饥饿加成虚高: on={v_weak_on:.2f} off={v_weak_off:.2f}"

    # 3uu) 长战演化顶格治理（第 88~89 批复盘）：kill_bonus 13→14→15、
    #      block_safety 2.05→2.00→1.95 单向漂移——0 胜生涯里「长战磨死」每局
    #      触发，信号只会把旋钮推向边界。余量不足一步时停止加码并显式留痕；
    #      行程充足时行为与旧版一致（3pp 已覆盖）
    gknow = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-gov-")))
    gknow.policy["kill_bonus"] = 19.5     # 距上限 0.5 < 步长 2.0
    gknow.policy["block_safety"] = 0.65   # 距下限 0.05 < 步长 0.1
    gctx = SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "BOSS_Y", "rounds": 8, "node_type": "Boss"},
        death_was_elite=False, death_hp_pct_at_entry=0.9,
        credit_tags=[], rests_healed_at_full=0, ascension=0, combat_notes=[])
    glesson = finalize_run(gknow, gctx, victory=False, final_floor=17)
    assert abs(gknow.policy["kill_bonus"] - 19.5) < 1e-9, \
        f"顶格旋钮仍被加码: {gknow.policy['kill_bonus']}"
    assert abs(gknow.policy["block_safety"] - 0.65) < 1e-9, \
        f"触底旋钮仍被释放: {gknow.policy['block_safety']}"
    assert "停止加码" in glesson and "停止释放" in glesson, \
        f"顶格治理未在复盘日志留痕: {glesson}"

    # 3vv) policy.json 三方合并写盘（第 90~91 批复盘）：运行中的大脑 finalize
    #      曾用内存旧值整体回写 policy.json——86~87 批写入的 boss_entry=0.72
    #      被冲掉成 0.65、88~89 批注册的 deck_burst_floor 在本批复盘进行中
    #      被整键冲掉（复盘期间实测复现）。外部冷修改必须在对局落盘后存活。
    mdir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-merge-"))
    mknow = knowledge.Knowledge(mdir)
    mknow.save()                                    # 建立基准
    disk_path = mdir / "policy.json"
    disk_now = json.loads(disk_path.read_text(encoding="utf-8"))
    disk_now["boss_entry_min_hp_pct"] = 0.72        # 外部冷修改（复盘会话写入）
    disk_now.pop("kill_race_enabled", None)         # 外部新增键被旧进程冲掉的形态
    disk_now["brand_new_external_key"] = 1.0        # 外部新增键
    disk_path.write_text(json.dumps(disk_now, ensure_ascii=False), encoding="utf-8")
    mknow.policy["kill_bonus"] = 18.0               # 本进程演化（内存值 ≠ 基准）
    mknow.save()
    after = json.loads(disk_path.read_text(encoding="utf-8"))
    assert abs(after["boss_entry_min_hp_pct"] - 0.72) < 1e-9, \
        f"外部冷修改被回写冲掉: {after['boss_entry_min_hp_pct']}"
    assert abs(after["kill_bonus"] - 18.0) < 1e-9, \
        f"本进程演化值被磁盘覆盖: {after['kill_bonus']}"
    assert after.get("brand_new_external_key") == 1.0, "外部新增键丢失"
    assert "kill_race_enabled" in after, "默认键未回填"
    assert abs(mknow.policy["boss_entry_min_hp_pct"] - 0.72) < 1e-9, "外部修改未实时采纳进内存"

    # 3ww) 斩杀竞速投影（第 90~91 批复盘，88~89 批遗留核对项⑤）：91 局 Boss 战
    #      65 血入场、输出 ~25/回合、仪式兽 252 血——击杀需 9+ 回合而意图逐轮
    #      滚升，引擎却把能量花在挑衅(挡6)/武装(挡5)这类奢侈格挡上逐回合买命，
    #      最终差 ~30 伤输掉竞速。实测输出速率证明击杀回合数超出可存活回合数
    #      时：奢侈格挡贬值、攻击提速（与 desperate/race_allin 互斥不叠加）。
    krc = type("KRCtx", (), {"combat": None, "current_combat_is_hard": True,
                             "credit_tags": []})()
    krc.combat = {"comp_id": "RACE_BOSS", "node_type": "Boss"}

    def krace_state(turn_no, hp_now, incoming=22):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": turn_no,
            "combat": {"player": {"current_hp": hp_now, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [
                           {"index": 0, "card_id": "KR_HIT", "name": "竞速斩", "playable": True,
                            "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                            "dynamic_values": [{"name": "Damage", "current_value": 12}]},
                           {"index": 1, "card_id": "KR_LUX", "name": "奢侈挡", "playable": True,
                            "requires_target": False,
                            "rules_text": "获得6点格挡",
                            "dynamic_values": [{"name": "Block", "current_value": 6}]}],
                       "enemies": [{"index": 0, "enemy_id": "RACE_BOSS", "name": "仪式兽",
                                    "current_hp": 200, "max_hp": 252, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": incoming}]}]},
            "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 17, "deck": []}}

    pol_kr = policy.Policy(know, random.Random(11))
    pol_kr.decide(krace_state(1, 65), krc)          # T1：样本不足，不武装
    pol_kr.decide(krace_state(2, 55), krc)          # T2：样本仍不足
    d_kr = pol_kr.decide(krace_state(3, 45), krc)   # T3：实测 ~24伤/回合 vs 200 血、意图 22/回合 → 投影必败
    assert d_kr.action == "play_card" and d_kr.params.get("card_index") == 0, \
        f"斩杀竞速失败时奢侈格挡仍胜出: {d_kr.action}（{d_kr.reason}）"
    assert "斩杀竞速投影" in d_kr.reason, f"竞速投影未留痕: {d_kr.reason}"
    # 对照：意图轻微（5/回合，血量账宽裕）时同一战斗不得触发竞速——防守路线可行
    pol_kr2 = policy.Policy(know, random.Random(11))
    pol_kr2.decide(krace_state(1, 80, incoming=5), krc)
    pol_kr2.decide(krace_state(2, 80, incoming=5), krc)
    d_kr2 = pol_kr2.decide(krace_state(3, 80, incoming=5), krc)
    assert "斩杀竞速投影" not in d_kr2.reason, f"防守可行时误触发竞速投影: {d_kr2.reason}"
    krc.combat = None

    # 3wx) 升级触发竞速 + 高危姿态解除（第 92~93 批复盘）：93 局 FUZZY+SHRINKER
    #      总血量 <80，旧门 min_enemy_hp=80 永远不开账；高危姿态压攻击(×0.85)
    #      抬格挡(×1.30)对滚雪球意图（4→7→24→…→31）恰好是反向用药——7 回合
    #      磨死。现在：持续升级(_esc_rounds≥2)同样开门、存活分母取当前意图
    #      （EMA 滞后修正）、竞速路线解除防御压制并改写矛盾文案。
    kdir_es = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-esc-"))
    know_es = knowledge.Knowledge(kdir_es)
    know_es.stats["enemies"]["RAMP_COMP"] = {
        "encounters": 5, "deaths": 3, "hp_lost_sum": 150.0, "wins": 2}
    krc_es = type("KRCtx", (), {"combat": None, "current_combat_is_hard": True,
                                "credit_tags": []})()
    krc_es.combat = {"comp_id": "RAMP_COMP", "node_type": "Monster"}

    def esc_state(turn_no, hp_now, incoming, ehp):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": turn_no,
            "combat": {"player": {"current_hp": hp_now, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [
                           {"index": 0, "card_id": "ES_HIT", "name": "竞速斩", "playable": True,
                            "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                            "dynamic_values": [{"name": "Damage", "current_value": 12}]},
                           {"index": 1, "card_id": "ES_LUX", "name": "奢侈挡", "playable": True,
                            "requires_target": False,
                            "rules_text": "获得6点格挡",
                            "dynamic_values": [{"name": "Block", "current_value": 6}]}],
                       "enemies": [{"index": 0, "enemy_id": "RAMP_COMP", "name": "滚雪球虫",
                                    "current_hp": ehp, "max_hp": 60, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": incoming}]}]},
            "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 6, "deck": []}}

    pol_es = policy.Policy(know_es, random.Random(7))
    pol_es.decide(esc_state(1, 65, 4, 60), krc_es)     # T1：意图 4 基准采样
    pol_es.decide(esc_state(2, 55, 7, 48), krc_es)     # T2：趋势+3，升级计数 1
    d_es = pol_es.decide(esc_state(3, 30, 24, 36), krc_es)  # T3：趋势+17 计数 2 → 开账
    assert d_es.action == "play_card" and d_es.params.get("card_index") == 0, \
        f"升级型低血池组合未走竞速路线: {d_es.action}（{d_es.reason}）"
    assert "斩杀竞速投影" in d_es.reason, f"升级门未开账: {d_es.reason}"
    assert "竞速解除防御压制" in d_es.reason, \
        f"高危防御姿态未被竞速解除/文案未改写: {d_es.reason}"
    assert "转防守节奏" not in d_es.reason, f"矛盾留痕残留: {d_es.reason}"
    # 对照：同一低血池组合但意图平稳（无升级轨迹）→ 门不开，不得误触发
    pol_es2 = policy.Policy(knowledge.Knowledge(kdir_es), random.Random(7))
    pol_es2.decide(esc_state(1, 65, 4, 60), krc_es)
    pol_es2.decide(esc_state(2, 55, 4, 48), krc_es)
    d_es2 = pol_es2.decide(esc_state(3, 30, 4, 36), krc_es)
    assert "斩杀竞速投影" not in d_es2.reason, f"无升级轨迹误开账: {d_es2.reason}"
    krc_es.combat = None

    # 3wy) 演化纠偏（第 92~93 批复盘）：非 Boss 长战阵亡不得再释放 block_safety
    #      （93 局 FUZZY+SHRINKER 7 回合磨死被旧规则判成「龟防拖长」扣防，
    #      实际死因是有效格挡不足——方向完全相反）
    rdir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-refl-"))
    rknow = knowledge.Knowledge(rdir)

    class _RC:
        def __init__(self):
            self.died_in_combat = {"comp_id": "RAMP_COMP", "node_type": "Monster", "rounds": 7}
            self.death_was_elite = False
            self.death_hp_pct_at_entry = 0.6
            self.died_to_event = None
            self.credit_tags = []
            self.ascension = 0
            self.rests_healed_at_full = 0
            self.combat_notes = []

    rctx = _RC()
    bs_before = rknow.policy["block_safety"]
    kb_before = rknow.policy["kill_bonus"]
    reflect.finalize_run(rknow, rctx, victory=False, final_floor=6)
    assert rknow.policy["block_safety"] > bs_before, \
        f"非 Boss 长战阵亡仍在释放防御: {bs_before} -> {rknow.policy['block_safety']}"
    assert rknow.policy["kill_bonus"] > kb_before or kb_before >= reflect.BOUNDS["kill_bonus"][1], \
        "非 Boss 长战阵亡未提升击杀奖励"
    # Boss 长战仍走释放分支
    rctx2 = _RC()
    rctx2.died_in_combat = {"comp_id": "BOSS_X", "node_type": "Boss", "rounds": 8}
    bs_b2 = rknow.policy["block_safety"]
    reflect.finalize_run(rknow, rctx2, victory=False, final_floor=9)
    assert rknow.policy["block_safety"] < bs_b2, \
        f"Boss 长战阵亡未释放防御: {bs_b2} -> {rknow.policy['block_safety']}"

    # 3wz) 溢出型大格挡贬值（第 94~95 批复盘）：94 局 Boss 战开局 87 血对意图
    #      7/17 连打两张岿然不动+(40挡)，~56 点溢出甲 ≈ 4 能量没换成伤害，
    #      Boss 多活两轮升级意图。有用部分不足牌面一半且血量宽裕时，大挡按
    #      纯溢出计价跌破出牌阈值；高意图回合与低血量（urgent/lethal）不受影响。
    kdir_ov = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-overblock-"))
    know_ov = knowledge.Knowledge(kdir_ov)
    ovc = type("OVCtx", (), {"combat": None, "current_combat_is_hard": False,
                             "credit_tags": []})()
    ovc.combat = {"comp_id": None, "node_type": "Monster"}

    def ov_wall_state(hp_now, incoming):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 1,
            "combat": {"player": {"current_hp": hp_now, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [{"index": 0, "card_id": "OV_WALL", "name": "巨墙", "playable": True,
                                 "energy_cost": 2, "requires_target": False,
                                 "rules_text": "获得40点格挡",
                                 "dynamic_values": [{"name": "Block", "current_value": 40}]}],
                       "enemies": [{"index": 0, "enemy_id": "OV_FOE", "name": "试法者",
                                    "current_hp": 50, "max_hp": 60, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": incoming}]}]},
            "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 17, "deck": []}}

    pol_ov = policy.Policy(know_ov, random.Random(5))
    d_ov1 = pol_ov.decide(ov_wall_state(76, 5), ovc)
    assert d_ov1.action == "end_turn", \
        f"血量宽裕时溢出大挡未被贬值仍被打出: {d_ov1.action}（{d_ov1.reason}）"
    d_ov2 = pol_ov.decide(ov_wall_state(30, 45), ovc)
    assert d_ov2.action == "play_card", \
        f"高意图回合右尺寸大挡被误贬值弃用: {d_ov2.action}（{d_ov2.reason}）"
    d_ov3 = pol_ov.decide(ov_wall_state(24, 8), ovc)
    assert d_ov3.action == "play_card", \
        f"紧急线以下大挡被误贬值弃用（低血量防御不得缩水）: {d_ov3.action}（{d_ov3.reason}）"
    ovc.combat = None

    # 3xa) 增益药水分类补「能力/power」（第 94~95 批复盘）：95 局能力药水因描述
    #      不含任何已知关键词，premium 门（高危姿态 T1 即开）形同虚设，直到
    #      20 血才被 ≤50% 兜底分支掏出。高危组合+满血+增益药水应在第 1 回合兑现；
    #      对照：描述完全无法分类的药水在满血时不得被兜底浪费。
    potc = type("PotCtx", (), {"combat": None, "current_combat_is_hard": False,
                               "credit_tags": []})()
    potc.combat = {"comp_id": "RAMP_COMP", "node_type": "Monster"}

    def pot_state(desc):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 1,
            "combat": {"player": {"current_hp": 80, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [{"index": 0, "card_id": "POT_HIT", "name": "打击", "playable": True,
                                 "energy_cost": 1, "requires_target": True,
                                 "valid_target_indices": [0],
                                 "dynamic_values": [{"name": "Damage", "current_value": 6}]}],
                       "enemies": [{"index": 0, "enemy_id": "RAMP_COMP", "name": "滚雪球虫",
                                    "current_hp": 40, "max_hp": 60, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": 4}]}]},
            "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 6, "deck": [],
                    "potions": [{"index": 0, "potion_id": "POT_POWER", "name": "能力药水",
                                 "description": desc, "usage": "combat", "occupied": True,
                                 "can_use": True, "requires_target": False}]}}

    pol_pot = policy.Policy(know_es, random.Random(5))
    d_pot = pol_pot.decide(pot_state("获得1点能力。"), potc)
    assert d_pot.action == "use_potion", \
        f"能力类增益药水未在高危战斗开局兑现: {d_pot.action}（{d_pot.reason}）"
    # 第 96 局复盘（兑现 94~95 批处方）：「能力/power」补词后又漏出第三批无法
    # 分类的药水（缚魂/无色/固化——96 局 Boss 战全部睡到 38% 血才被兜底掏出，
    # 其中固化药水单瓶 +33 甲）。premium 硬仗前 3 回合未知类别直接放行。
    pol_pot2 = policy.Policy(know_es, random.Random(5))
    d_pot2 = pol_pot2.decide(pot_state("闻起来像草莓。"), potc)
    assert d_pot2.action == "use_potion" and "硬仗开局" in d_pot2.reason, \
        f"premium硬仗T1未知类别药水未被放行: {d_pot2.action}（{d_pot2.reason}）"
    # 对照：非 premium 普通战中未知类别仍保留（防绕过增益保留策略）
    potc.combat = {"comp_id": "HARMLESS", "node_type": "Monster"}
    pol_pot3 = policy.Policy(know_es, random.Random(5))
    d_pot3 = pol_pot3.decide(pot_state("闻起来像草莓。"), potc)
    assert d_pot3.action == "play_card", \
        f"普通战兜底浪费未知类别药水: {d_pot3.action}（{d_pot3.reason}）"
    potc.combat = None

    # 3xx) 房间先验战斗发生率条件化（第 96 局复盘核心修复）：生涯 Unknown
    #      到访 148 次仅 33 次开战（22%）——damage_events 只统计真打了仗的样本，
    #      零伤事件到访从未进入分母，旧口径把 E[伤|开战] 当 E[伤|到访] 用：
    #      二幕每个 Unknown 被按满额战斗×1.6 计费（~35点），96 局路径分饱和在
    #      -165~-195、全图投影「进Boss血量 0%」而实际一路零伤事件走到 70% 血。
    prdir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-rate-"))
    pknow = knowledge.Knowledge(prdir)
    pknow.stats["rooms"]["Unknown"] = {"visits": 100, "outcome_sum": 0.0,
                                       "hp_lost_sum": 300.0, "damage_events": 20}
    pknow.stats["rooms"]["Monster"] = {"visits": 600, "outcome_sum": 0.0,
                                       "hp_lost_sum": 4800.0, "damage_events": 600}
    # Unknown：measured=15, w=0.7 → blended=13.5，rate=20/100=0.2 → 2.7
    assert abs(pknow.room_damage_prior("Unknown", 10.0) - 2.7) < 1e-9, \
        f"Unknown 先验未按战斗发生率折价: {pknow.room_damage_prior('Unknown', 10.0)}"
    # Monster：几乎每访必战（rate=1.0）→ 维持原口径不被折价
    assert abs(pknow.room_damage_prior("Monster", 8.0) - 8.0) < 1e-9, \
        f"高频开战房间被误折价: {pknow.room_damage_prior('Monster', 8.0)}"
    # 样本不足（到访<5）保守回退 1.0：维持必战假设
    pknow.stats["rooms"]["RareRoom"] = {"visits": 3, "outcome_sum": 0.0,
                                        "hp_lost_sum": 30.0, "damage_events": 3}
    assert abs(pknow.room_damage_prior("RareRoom", 10.0) - 10.0) < 1e-9, \
        f"小样本房间发生率未保守回退: {pknow.room_damage_prior('RareRoom', 10.0)}"

    # 3xy) 路径投影罚分去重（第 96 局复盘）：死亡投影曾与血量线/Boss入场线
    #      三重叠加（同一坏结局记三次账），二幕全图饱和在 -165~-195。中途死亡
    #      只记一次后：垂死路径的评分须回到 -100 以内（保留存活深度梯度），
    #      且「撑到 Boss 但血量不达标」的续航路线必须胜过半路暴毙路线。
    ds_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-destack-"))
    ds_know = knowledge.Knowledge(ds_dir)
    ds_pol = policy.Policy(ds_know)

    def destack_map(hp_now):
        heads = [
            {"index": 0, "row": 1, "col": 0, "node_type": "Monster",
             "children": [{"row": 2, "col": 0}]},
            {"index": 1, "row": 1, "col": 1, "node_type": "RestSite",
             "children": [{"row": 2, "col": 1}]},
        ]
        chain_a = []
        for r in range(2, 13):
            g = {"row": r, "col": 0, "node_type": "Boss" if r == 12 else "Monster"}
            if r < 12:
                g["children"] = [{"row": r + 1, "col": 0}]
            chain_a.append(g)
        chain_b = []
        for r in range(2, 13):
            nt = "Monster" if r == 11 else ("Boss" if r == 12 else "Event")
            g = {"row": r, "col": 1, "node_type": nt}
            if r < 12:
                g["children"] = [{"row": r + 1, "col": 1}]
            chain_b.append(g)
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": heads, "nodes": heads + chain_a + chain_b,
                      "boss_node": {"row": 12}},
              "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 5, "deck": []}}
        return ds_pol.decide(st, type("C", (), {"credit_tags": []})())

    d_ds = destack_map(30)   # 37% 血：怪物链半路暴毙 vs 篝火+事件链续航进场
    assert d_ds.params.get("option_index") == 1, \
        f"去重后续航路线未胜出: {d_ds.reason}"
    m_dying = re.search(r"Monster\(1,0\)=(-?[0-9.]+)", d_ds.reason)
    assert m_dying and -100.0 < float(m_dying.group(1)) < 0, \
        f"垂死路径评分仍被三重罚分饱和: {m_dying.group(1)}（{d_ds.reason}）"
    assert "投影中途死亡" in d_ds.reason, f"死亡投影未留痕: {d_ds.reason}"

    # 3xz) 绝境投影篝火回血（第 96 局复盘）：F22 篝火在 79% 血按常规线锻造，
    #      而地图端全路径投影早已给出「照此打下去进 Boss 仅 36%」的死局预警——
    #      随后 F23 -37、F31 被漏斗逼进强制精英 -68 阵亡。投影绝望时篝火的
    #      第一职责是把血量带回安全区，锻造让位；接近满血时仍锻造不浪费。
    def dire_rest_state():
        return {"screen": "REST", "available_actions": ["choose_rest_option"],
                "rest": {"options": [
                    {"index": 0, "option_id": "HEAL", "title": "休息", "is_enabled": True},
                    {"index": 1, "option_id": "SMITH", "title": "锻造", "is_enabled": True}]},
                "run": {"current_hp": 69, "max_hp": 87, "gold": 0, "floor": 22,
                        "deck": [{"card_id": "RAMPAGE_X", "upgraded": False}]}}
    ctx.rest_proj_hp_pct = 0.36   # 复现 96 局 F22 决策时的投影值
    d_dire = pol.decide(dire_rest_state(), ctx)
    assert d_dire.tags and d_dire.tags[0] == ("rest", "heal") and "绝境" in d_dire.reason, \
        f"绝境投影未改回血: {d_dire.reason}"
    ctx.rest_proj_hp_pct = 0.85   # 投影健康：维持锻造长线投资
    d_norm = pol.decide(dire_rest_state(), ctx)
    assert d_norm.tags and d_norm.tags[0] == ("rest", "smith"), \
        f"投影健康时不应放弃锻造: {d_norm.reason}"
    ctx.rest_proj_hp_pct = 0.36   # 回血边际不足最大生命 8%（84/87）→ 仍锻造
    st_high = dire_rest_state()
    st_high["run"] = dict(st_high["run"], current_hp=84)
    d_high = pol.decide(st_high, ctx)
    assert d_high.tags and d_high.tags[0] == ("rest", "smith"), \
        f"回血将溢出时仍应锻造: {d_high.reason}"
    ctx.rest_proj_hp_pct = 1.0    # 还原，防泄漏后续用例

    # 3ya) 商店购卡与奖励端同门槛（第 96 局复盘）：F30 卡组已在软上限边缘，
    #      商店仍按固定阈值 1.0 买进净价值仅 3.0 的巨像（73金）——同一张牌在
    #      奖励端会因动态拾取门槛被拒。膨胀卡组下商店必须拒收注水牌；
    #      单薄卡组下合格牌照常可买（门槛不能一刀切杀死商店价值）。
    def shop_gate_state(deck):
        return {"screen": "SHOP",
                "available_actions": ["buy_card", "close_shop_inventory"],
                "shop": {"is_open": True, "can_close": True,
                         "cards": [{"index": 0, "card_id": "SHOP_SMALL_GUARD", "name": "小盾",
                                    "card_type": "Skill", "energy_cost": 1,
                                    "is_stocked": True, "enough_gold": True, "price": 75,
                                    "rules_text": "获得4点格挡",
                                    "dynamic_values": [{"name": "Block", "current_value": 4}]}],
                         "relics": [], "card_removal": None},
                "run": {"current_hp": 68, "max_hp": 87, "gold": 500, "floor": 30,
                        "deck": [dict(c) for c in deck]}}
    bloat_deck = [{"card_id": f"BLOAT_A_{i}", "card_type": "Attack", "energy_cost": 1}
                  for i in range(22)]
    d_sg1 = pol.decide(shop_gate_state(bloat_deck), ctx)
    assert d_sg1.action == "close_shop_inventory", \
        f"膨胀卡组下商店仍买入低于动态门槛的注水牌: {d_sg1.action}（{d_sg1.reason}）"
    d_sg2 = pol.decide(shop_gate_state([]), ctx)
    assert d_sg2.action == "buy_card", \
        f"单薄卡组下合格牌被误拒: {d_sg2.action}（{d_sg2.reason}）"

    # 3za) 拾取端 learned value 封顶（第 106 局复盘核心修复）：outcome=到达层数
    #      是幸存者偏差噪声——能被拾取的前提就是活到奖励屏，早楼层 offered 的牌
    #      自动积累高 outcome。RAMPAGE 靠 +6 学习分在 55 局里自我强化循环拾取
    #      （106 局又拿 3 张）。封顶后学习信号只保留方向：场均 20 vs 全局 10 的
    #      「热门牌」相对无名牌的拾取优势必须 ≤ card_value_pick_cap。
    learn_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-cap-"))
    lknow = knowledge.Knowledge(learn_dir)
    lknow.stats.setdefault("cards", {})["HOT_STUFF"] = {
        "seen": 40, "picked": 30, "plays": 120, "outcome_sum": 600.0, "bias": 0.0}  # 场均20 vs 全局10
    hot_card = {"card_id": "HOT_STUFF", "name": "热门牌", "card_type": "Attack",
                "energy_cost": 1,
                "dynamic_values": [{"name": "Damage", "current_value": 6}]}
    plain_card = dict(hot_card, card_id="PLAIN_STUFF", name="无名牌")
    pol_cap = policy.Policy(lknow)
    v_hot = pol_cap.eval_reward_card(dict(hot_card), [])
    v_plain = pol_cap.eval_reward_card(dict(plain_card), [])
    cv_cap = float(lknow.policy["card_value_pick_cap"])
    assert v_hot - v_plain <= cv_cap + 1e-6, \
        f"learned value 拾取端未封顶: {v_hot:.2f}-{v_plain:.2f}>{cv_cap}"

    # 3zb) 事件触发战斗的延迟结算（第 106 局复盘数据修复）：「茂密的植被-战！」
    #      在随后的战斗中把感染×3 打进牌堆，旧逻辑进战瞬间结算 deck_delta 恒 0
    #      ——事件端把「污染卡组」当免费。新语义：hp/金币按离开事件屏瞬间的
    #      快照记账（事件自身即时效果，不含战斗损耗）；卡组增量用战后 live 值；
    #      战斗中的死亡不归因给事件选项（归敌人组合）。
    ag.ctx.reset_for("RUN_EVT2", 0)

    def evt_flow_state(screen, hp, gold, deck_len):
        st = {"screen": screen, "run_id": "RUN_EVT2",
              "run": {"current_hp": hp, "max_hp": 80, "gold": gold, "floor": 14,
                      "deck": [{"card_id": f"C{i}"} for i in range(deck_len)]}}
        if screen == "COMBAT":
            st["combat"] = {"enemies": [{"enemy_id": "VEG_BUG", "is_alive": True}]}
        return st

    ag._track(evt_flow_state("EVENT", 80, 50, 1),
              policy.Decision(action="choose_event_option",
                              tags=[("event_choice", "VEG_EV", "FIGHT")]))
    # 进战 tick：事件已发放 +20 金（即时效果），hp 未变——快照应冻结在此
    ag._track(evt_flow_state("COMBAT", 80, 70, 1), policy.Decision(action=None))
    assert tknow.stats["events"].get("VEG_EV", {}).get("FIGHT") is None, \
        "事件触发的战斗在进战瞬间就被提前结算（旧 bug 复发）"
    # 战后流转：战斗损耗 -14hp 与战利品金币不归属事件，卡组增量 +3（感染×3）入账
    ag._track(evt_flow_state("MAP", 66, 70, 4), policy.Decision(action=None))
    pe2 = tknow.stats["events"]["VEG_EV"]["FIGHT"]
    assert pe2["n"] == 1 and pe2["card_delta_sum"] == 3.0 \
        and pe2["hp_delta_sum"] == 0.0 and pe2["gold_delta_sum"] == 20.0, \
        f"事件战斗延迟结算管线断裂: {pe2}"
    assert not ag.ctx.died_to_event, "无死亡不应产生事件致死归因"

    # 4) 真实知识库可加载（验证数据结构兼容性——若复盘改了 stats/policy 结构这里会暴露）。
    #    repair_phantoms=False：自检不得抢先改写运行中大脑的统计并置修复标记，
    #    否则重启后的一次性修复会被标记跳过、灌水数据永久留存
    real = knowledge.Knowledge(BRAIN.parent / "knowledge", repair_phantoms=False)
    assert real.stats.get("global") is not None and real.policy, "knowledge structure broken"
    pol2 = policy.Policy(real)
    assert pol2.decide(fake_states[1], ctx) is not None

    print("SELFCHECK OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
