"""冒烟自检 —— LLM 复盘修改任何 brain/*.py 后必须通过本检查。

覆盖：全模块导入 + 用假状态驱动 Policy 各屏幕处理器不抛异常。
"""
from __future__ import annotations

import random
import re
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

    # 3j) 事件平值按样本数优先：价值同为 0.0 时不得按选项原始顺序盲取第一个
    #     （第 36 批实证：石炉加湿器(n=0) 排在 失物盒(n=3) 前面被选中）
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
    assert d_tie.params.get("option_index") == 1, f"事件平值必须偏向样本多的选项: {d_tie.reason}"

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
    trk(trk_state(35, comp="E3"))
    e2 = tknow.stats["enemies"].get("E2")
    assert e2 and e2["encounters"] == 1 and e2["wins"] == 1, f"E2={e2}"
    assert ag.ctx.combat and ag.ctx.combat["comp_id"] == "E3"

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
    d_rest_norm = pol.decide(rest_state, ctx)
    # 常规逻辑：72% ≥ 安全线 55% → 锻造
    assert d_rest_norm.tags and d_rest_norm.tags[0] == ("rest", "smith"), \
        f"常规篝火应锻造: {d_rest_norm.reason}"
    ctx.rest_before_boss = True
    d_rest_boss = pol.decide(rest_state, ctx)
    assert d_rest_boss.tags and d_rest_boss.tags[0] == ("rest", "heal"), \
        f"Boss 前夜应优先回血: {d_rest_boss.reason}"
    ctx.rest_before_boss = False

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
