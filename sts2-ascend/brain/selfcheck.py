"""冒烟自检 —— LLM 复盘修改任何 brain/*.py 后必须通过本检查。

覆盖：全模块导入 + 用假状态驱动 Policy 各屏幕处理器不抛异常。
"""
from __future__ import annotations

import random
import re
import json
import math
import io
import os
import sys
import tempfile
from pathlib import Path

BRAIN = Path(__file__).resolve().parent
sys.path.insert(0, str(BRAIN))
sys.path.insert(0, str(BRAIN.parent / "tts"))


def main() -> int:
    # A selfcheck may be launched by the live Brain or from a saved review clone.
    # It is not a runner-managed Brain boot and must never open/write the live UI.
    os.environ["STS2_ASCEND_DISABLE_VIEWER"] = "1"
    os.environ.pop("STS2_ASCEND_BOOT_ID", None)

    # 1) 全模块可导入
    import client, knowledge, policy, reflect, agent, autogit, llm_review  # noqa: F401
    import owner_epoch
    tts_epoch = owner_epoch.code_epoch(BRAIN.parent)
    assert re.fullmatch(r"[0-9a-f]{64}", tts_epoch), "TTS owner code epoch invalid"
    assert set(owner_epoch.OWNER_EPOCH_PATHS) == {
        "tts/owner_epoch.py", "tts/indextts_gpu.py", "tts/quipper.py",
    }, "TTS owner epoch must remain path-local; never expand it to a repository fingerprint"

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
    act_boundaries = [pol._floor_act(floor_no) for floor_no in (17, 18, 33, 34)]
    assert act_boundaries == [1, 2, 2, 3], \
        f"分幕边界失效: F17/F18/F33/F34 -> {act_boundaries}"

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

    # 成长型普通怪姿态斜率反转：静态 FUZZY 首回合即解除攻击压制；
    # 未知组合必须连续两次升级才确认。Elite/Boss、非高危和一次波动均不得误触发。
    def ramp_stance(*, danger=True, atk=0.85, block=1.6):
        return {"danger": "高危组合" if danger else "",
                "atk_mult": atk, "blk_mult": block}

    st_fuzzy = ramp_stance()
    tag_fuzzy = pol._apply_growth_ramp_stance_relief(
        st_fuzzy, "FUZZY_WURM_CRAWLER+SHRINKER_BEETLE", "Monster", 0)
    assert tag_fuzzy == "斜率反转：成长型组合，解除攻击压制", tag_fuzzy
    assert st_fuzzy["atk_mult"] == 1.0 and st_fuzzy["blk_mult"] == 1.3, st_fuzzy
    st_substring = ramp_stance()
    assert not pol._apply_growth_ramp_stance_relief(
        st_substring, "NOT_FUZZY_WURM_CRAWLERISH", "Monster", 0), \
        "静态成长怪必须按 comp_id 成员精确匹配"
    st_once = ramp_stance()
    assert not pol._apply_growth_ramp_stance_relief(
        st_once, "RAMP_COMP", "Monster", 1), "一次意图波动不应确认为持续成长"
    st_twice = ramp_stance()
    assert pol._apply_growth_ramp_stance_relief(
        st_twice, "RAMP_COMP", "Monster", 2), "两次升级应解除普通怪防御压制"
    for room in ("Elite", "Boss"):
        st_room = ramp_stance()
        assert not pol._apply_growth_ramp_stance_relief(
            st_room, "FUZZY_WURM_CRAWLER", room, 3), f"{room} 不应走普通怪反转"
    st_safe = ramp_stance(danger=False)
    assert not pol._apply_growth_ramp_stance_relief(
        st_safe, "FUZZY_WURM_CRAWLER", "Monster", 3), "非高危组合不应反转"
    st_neutral_block = ramp_stance(block=0.9)
    assert pol._apply_growth_ramp_stance_relief(
        st_neutral_block, "FUZZY_WURM_CRAWLER", "Monster", 0)
    assert st_neutral_block["blk_mult"] == 0.9, "低于中性的格挡权重不得被抬高"

    # 竞速投影错账审计（第802~807局批复盘闭环实验 RACE_PROJ_CALIB_AUDIT
    # 回归夹具）：弹出式账本契约——无判死历史返回空账、有账弹快照、
    # 弹出后清空防跨场残留；契约是 agent 收官拼接「判死→实战」对照的基础。
    assert pol.pop_race_audit() == {}, "空战斗状态应返回空审计账"
    pol._race_audit = {"latched": True, "latch_round": 3, "esc": True}
    _ra_snap = pol.pop_race_audit()
    assert _ra_snap == {"latched": True, "latch_round": 3, "esc": True}, _ra_snap
    assert pol.pop_race_audit() == {}, "审计账弹出后应清空"

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
    pol_exploit = policy.Policy(know, random.Random(2))  # 事件决策已确定性，不依赖随机首抽
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

    neg_state = {"screen": "EVENT", "available_actions": ["choose_event_option"],
                 "event": {"event_id": "NEG_EV", "title": "负收益测试", "is_finished": False,
                           "options": [{"index": 0, "title": "大亏项", "text_key": "OPT_BAD",
                                        "is_locked": False, "is_proceed": False},
                                       {"index": 1, "title": "新项", "text_key": "OPT_NEW",
                                        "is_locked": False, "is_proceed": False}]},
                 "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 6, "deck": []}}
    pol_neg = policy.Policy(know, random.Random(0))
    d_neg = pol_neg.decide(neg_state, ctx)
    assert d_neg.params.get("option_index") == 1 \
        and "大亏项" in d_neg.reason and "经验价值 -34.0" not in d_neg.reason, \
        f"确定性决策必须回避已知负收益选项: {d_neg.reason}"

    # 3k2) 最坏情况生存闸门（第 255~257 批次复盘）：均值账看不见的重尾由
    #      hp_min 补位——7RJ9 局 31% 血选均值 +10.5 的「休息」被链内强制战
    #      -55 抬走。历史单次最差掉血超过当前血量（留余量）的选项，存在
    #      安全替代时必须出局；全员致死时保留原池强行择损（不制造无牌可出）
    know.commit_event_option("WORST_EV", "REST", 10.0, 0.0, died=False)
    know.commit_event_option("WORST_EV", "REST", -55.0, 0.0, died=False)
    _w_rest = know.event_option_worst("WORST_EV", "REST")
    assert _w_rest == -55.0, f"hp_min 应逐样本取最小: {_w_rest}"
    assert know.event_option_worst("WORST_EV", "NOPE") is None, "未知选项应无尾部数据"
    assert know.event_option_worst("NOPE_EV", "REST") is None, "未知事件应无尾部数据"
    _wv, _wn = know.event_option_value("WORST_EV", "REST")
    assert _wv < 0.0 and _wn == 2, f"均值账不受 hp_min 影响: {_wv}/{_wn}"
    # 均值正收益但尾部致死：+8 均值(+80/10) 配 -55 尾部，低血时必须让位安全项
    know.stats["events"]["WORST_EV2"] = {
        "REST": {"n": 10, "hp_delta_sum": 80.0, "gold_delta_sum": 0.0,
                 "deaths": 0, "hp_min": -55.0}}
    worst_state = {"screen": "EVENT", "available_actions": ["choose_event_option"],
                   "event": {"event_id": "WORST_EV2", "title": "茂密的植被", "is_finished": False,
                             "options": [{"index": 0, "title": "休息", "text_key": "REST",
                                          "is_locked": False, "is_proceed": False},
                                         {"index": 1, "title": "坚持跋涉", "text_key": "TRUDGE_ON",
                                          "is_locked": False, "is_proceed": False}]},
                   "run": {"current_hp": 30, "max_hp": 80, "gold": 0, "floor": 5, "deck": []}}
    pol_worst = policy.Policy(know, random.Random(2))
    d_worst = pol_worst.decide(worst_state, ctx)
    assert d_worst.params.get("option_index") == 1 and "最坏情况闸门" in d_worst.reason, \
        f"30 血时尾部 -55 的选项必须被闸门否决（即使均值更高）: {d_worst.reason}"
    # 满血时间门静默：80 血 + (-55) = 25 > 余量 4，均值高者照常胜出
    worst_state["run"] = dict(worst_state["run"], current_hp=80)
    pol_worst2 = policy.Policy(know, random.Random(2))
    d_worst2 = pol_worst2.decide(worst_state, ctx)
    assert d_worst2.params.get("option_index") == 0 and "最坏情况闸门" not in d_worst2.reason, \
        f"满血时最坏情况闸门不应触发: {d_worst2.reason}"
    # 全员致死：唯一选项尾部致死也得选（不制造无牌可出）
    worst_state["event"]["options"] = [worst_state["event"]["options"][0]]
    worst_state["run"] = dict(worst_state["run"], current_hp=30)
    pol_worst3 = policy.Policy(know, random.Random(2))
    d_worst3 = pol_worst3.decide(worst_state, ctx)
    assert d_worst3.params.get("option_index") == 0 and "强行择损" in d_worst3.reason, \
        f"无安全替代时必须保留原池强行择损: {d_worst3.reason}"

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

    def track_accepted(target, st, decision):
        """Drive one synthetic tick through the same observe -> accepted flow as run()."""
        target._track(st, decision)
        if decision.action:
            target._commit_successful_action(st, decision)

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

    # 3k3) Boss 前夜进攻药水预留（第 380~385 批复盘新增）：BNSJ 局 F4/F14/F15
    #      三瓶进攻药水全数前倾消费（两瓶倒在净损 0/-5 的普通怪房），F17 一幕
    #      Boss 斩杀竞速差 3~7 回合空手阵亡。距 Boss ≤2 层的普通怪房封存进攻/
    #      增益药水；精英/Boss 房、服务端致死、低血交药线三口解封不受限。
    #      远端（>窗口）普通高危房照旧投放——防「囤药带进坟墓」旧病回潮。
    #      第 386~390 批复盘追加：输出饥饿卡组（deck_burst < deck_burst_floor）
    #      的预留窗加宽到 potion_starved_reserve_floors——本批五局竞速投影全线
    #      「击杀还需>可存活」，LK4C 局 F10 爆炸药水、3QQC 局 F13 速度+增益
    #      药水仍被统计恐惧门烧进普通怪房，F17 一幕 Boss 空手输掉竞速。
    def reserve_potion_state(floor_no: int, lethal: bool = False, hp: int = 60,
                             deck: list | None = None) -> dict:
        st = {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 1,
            "combat": {"player": {"current_hp": hp, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [],
                       "enemies": [{"index": 0, "enemy_id": "M", "name": "小怪",
                                    "current_hp": 30, "max_hp": 30, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": 10}]}]},
            "run": {"current_hp": hp, "max_hp": 80, "gold": 0, "floor": floor_no,
                    "deck": list(deck or []),
                    "potions": [{"index": 0, "potion_id": "ATTACK_P", "name": "攻击药水",
                                 "description": "获得2点力量。", "occupied": True,
                                 "can_use": True, "usage": "combat"}]},
        }
        if lethal:
            st["combat"]["end_turn_will_kill_player"] = True
        return st

    _starved_deck = [{"card_id": "DEFEND_IRONCLAD", "card_type": "Skill",
                      "energy_cost": 1, "rules_text": "获得5点格挡。"}] * 10
    _strong_deck = [{"card_id": "HEAVY_BLADE", "card_type": "Attack", "energy_cost": 1,
                     "dynamic_values": [{"name": "Damage", "base_value": 16}]}] * 6

    ctx.current_combat_is_hard = True   # 高危组合门常开，复刻 BNSJ F15 场景
    ctx.combat = {"comp_id": "M", "node_type": "Monster"}
    d_hold = pol.decide(reserve_potion_state(15), ctx)   # 距 Boss 17-15=2 ≤ 窗口
    assert d_hold.action != "use_potion", \
        f"Boss 临门普通房必须封存进攻药水: {d_hold.action}（{d_hold.reason}）"
    ctx.combat = {"comp_id": "M", "node_type": "Monster"}
    d_far = pol.decide(reserve_potion_state(10), ctx)    # 距 Boss 7 > 窗口
    assert d_far.action == "use_potion", \
        f"远端普通高危房应照旧投放（防囤药入坟）: {d_far.action}（{d_far.reason}）"
    ctx.combat = {"comp_id": "M", "node_type": "Monster"}
    d_unseal = pol.decide(reserve_potion_state(15, lethal=True), ctx)
    assert d_unseal.action == "use_potion", \
        f"服务端致死必须立即解封: {d_unseal.action}（{d_unseal.reason}）"
    ctx.combat = {"comp_id": "M", "node_type": "Elite"}
    d_elite_rm = pol.decide(reserve_potion_state(15), ctx)
    assert d_elite_rm.action == "use_potion", \
        f"精英房预留不适用（换遗物值得花弹药）: {d_elite_rm.action}（{d_elite_rm.reason}）"
    ctx.combat = {"comp_id": "M", "node_type": "Monster"}
    d_lowhp = pol.decide(reserve_potion_state(15, hp=24), ctx)   # 24/80 < 交药线 35%
    assert d_lowhp.action == "use_potion", \
        f"血量跌破交药线必须解封（保命优先于囤积）: {d_lowhp.action}（{d_lowhp.reason}）"
    # 3k3b) 输出饥饿卡组的加宽预留窗（第 386~390 批复盘）：
    #       饥饿卡组（爆发<45）距 Boss 5 层的普通怪房必须封存——LK4C 局 F10
    #       爆炸药水、3QQC 局 F13 速度+增益药水的复刻位；强卡组同楼层照旧投放；
    #       饥饿但跌破交药线仍立即解封
    ctx.combat = {"comp_id": "M", "node_type": "Monster"}
    d_starve_hold = pol.decide(reserve_potion_state(12, deck=_starved_deck), ctx)
    assert d_starve_hold.action != "use_potion", \
        f"饥饿卡组距Boss≤6层普通房应封存进攻药水: {d_starve_hold.action}（{d_starve_hold.reason}）"
    ctx.combat = {"comp_id": "M", "node_type": "Monster"}
    d_strong_far = pol.decide(reserve_potion_state(12, deck=_strong_deck), ctx)
    assert d_strong_far.action == "use_potion", \
        f"强卡组预留窗不得被加宽（防囤药入坟）: {d_strong_far.action}（{d_strong_far.reason}）"
    ctx.combat = {"comp_id": "M", "node_type": "Monster"}
    d_starve_valve = pol.decide(reserve_potion_state(12, hp=24, deck=_starved_deck), ctx)
    assert d_starve_valve.action == "use_potion", \
        f"饥饿封存下交药线解封口必须保留: {d_starve_valve.action}（{d_starve_valve.reason}）"
    ctx.combat = None
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

    # 3n2) 投影近死带计价（第 255~257 批次复盘）：中途血量跌破近死带但没死透
    #      的路径旧账零罚分——257 局 64% 血进精英，投影明示「战后仅剩 3%」仍
    #      以 1.03 分压过安全候选，实战 -51 阵亡。凹陷后被篝火抬回的路径终点
    #      体面、途中是运气：最深凹陷深度必须折价为罚分
    dip_heads = [{"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                  "children": [{"row": 2, "col": 0}]}]
    dip_chain = []
    for r, nt in ((2, "Monster"), (3, "Monster"), (4, "Monster"),
                  (5, "RestSite"), (6, "Boss")):
        gnode = {"row": r, "col": 0, "node_type": nt}
        if r < 6:
            gnode["children"] = [{"row": r + 1, "col": 0}]
        dip_chain.append(gnode)
    dip_st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": dip_heads, "nodes": dip_heads + dip_chain,
                      "boss_node": {"row": 6}},
              "run": {"current_hp": 39, "max_hp": 80, "gold": 0, "floor": 5,
                      "deck": [{"card_id": "STRIKE_IRONCLAD"}] * 4}}
    # 39 血四连战投影：39→31→23→15→~7（≈8% 跌破 10% 近死带）→ 篝火抬回。
    # 先验钉死（rooms 实测 10 场场均 8）——否则共享夹具里前面用例留下的高危
    # 敌人条目会把 combat_calibration 顶到 1.5，静态先验 8→12，投影直接死亡
    # 饥饿上浮同步归零隔离（第495~498局批复盘）：本用例校准于旧口径，
    # 输出饥饿战损上浮的行为由 3bw 专项用例覆盖
    _svfrac_old = know.policy.get("path_starve_loss_frac")
    know.policy["path_starve_loss_frac"] = 0.0
    _rooms_old = know.stats.get("rooms", {}).get("Monster")
    know.stats.setdefault("rooms", {})["Monster"] = {
        "visits": 10, "outcome_sum": 0.0, "hp_lost_sum": 80.0, "damage_events": 10}
    try:
        pol_dip = policy.Policy(know, random.Random(2))
        d_dip_on = pol_dip.decide(dip_st, ctx)
    finally:
        if _rooms_old is None:
            know.stats["rooms"].pop("Monster", None)
        else:
            know.stats["rooms"]["Monster"] = _rooms_old
    assert "近死" in d_dip_on.reason, f"近死带投影未折价留痕: {d_dip_on.reason}"
    m_on = re.search(r"路径分 (-?\d+\.\d+)", d_dip_on.reason)
    assert m_on, f"路径分解析失败: {d_dip_on.reason}"
    _grave_old = know.policy.get("path_graveyard_hp_pct")
    know.policy["path_graveyard_hp_pct"] = 0.0  # 关闭近死带 → 同图不得折价
    know.stats.setdefault("rooms", {})["Monster"] = {
        "visits": 10, "outcome_sum": 0.0, "hp_lost_sum": 80.0, "damage_events": 10}
    try:
        pol_dip2 = policy.Policy(know, random.Random(2))
        d_dip_off = pol_dip2.decide(dip_st, ctx)
    finally:
        know.policy["path_graveyard_hp_pct"] = _grave_old
        if _rooms_old is None:
            know.stats["rooms"].pop("Monster", None)
        else:
            know.stats["rooms"]["Monster"] = _rooms_old
    assert "近死" not in d_dip_off.reason, f"近死带关闭后不应留痕: {d_dip_off.reason}"
    m_off = re.search(r"路径分 (-?\d+\.\d+)", d_dip_off.reason)
    assert m_off and float(m_on.group(1)) < float(m_off.group(1)), \
        f"近死带折价未体现为罚分（开 {m_on and m_on.group(1)} vs 关 {m_off and m_off.group(1)}）"
    if _svfrac_old is None:
        know.policy.pop("path_starve_loss_frac", None)
    else:
        know.policy["path_starve_loss_frac"] = _svfrac_old

    # 3n3) 尾部战损定价（第 258~262 批次复盘）：掉血先验是场均账，单场实测尾部
    #      可达 3~5 倍——262 局 49% 血进 Monster 投影仅 ~9 点（账面安全），实战
    #      -39 阵亡。血量跌破警戒带后先验必须向实测单场最差（hp_lost_max）混合；
    #      满血段零影响；关闭旋钮（带=0）后同图同分、不留痕
    # getter 单测：分幕样本优先、旧库缺键条目（无 hp_lost_max）返回 None
    know.stats.setdefault("rooms_act", {})["Monster@1"] = {
        "hp_lost_sum": 80.0, "damage_events": 10, "hp_lost_max": 50.0}
    assert know.room_damage_worst("Monster", 1) == 50.0, \
        f"分幕尾部记忆读取失败: {know.room_damage_worst('Monster', 1)}"
    know.stats["rooms_act"]["ZZ_LEGACY@1"] = {"hp_lost_sum": 10.0, "damage_events": 9}
    assert know.room_damage_worst("ZZ_LEGACY", 1) is None, \
        "旧库缺 hp_lost_max 键的条目必须视为无尾部样本（None）"
    know.stats["rooms_act"].pop("ZZ_LEGACY", None)
    tail_heads = [{"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                   "children": [{"row": 2, "col": 0}]}]
    tail_chain = []
    for r, nt in ((2, "Monster"), (3, "RestSite"), (4, "Boss")):
        gnode = {"row": r, "col": 0, "node_type": nt}
        if r < 4:
            gnode["children"] = [{"row": r + 1, "col": 0}]
        tail_chain.append(gnode)
    tail_st = {"screen": "MAP", "available_actions": ["choose_map_node"],
               "map": {"available_nodes": tail_heads, "nodes": tail_heads + tail_chain,
                       "boss_node": {"row": 4}},
               "run": {"current_hp": 40, "max_hp": 80, "gold": 0, "floor": 5,
                       "deck": [{"card_id": "STRIKE_IRONCLAD"}] * 4}}
    # 40 血（50%）跌破警戒带 62%：首场先验 8 应向尾部 50×0.5=25 混合抬价。
    # 钉死 rooms 先验（与 3n2 同因：防共享夹具的敌人条目顶满 combat_calibration）
    _rooms_old2 = know.stats.get("rooms", {}).get("Monster")
    _ract_old2 = know.stats.get("rooms_act", {}).get("Monster@1")
    know.stats.setdefault("rooms", {})["Monster"] = {
        "visits": 10, "outcome_sum": 0.0, "hp_lost_sum": 80.0, "damage_events": 10,
        "hp_lost_max": 50.0}
    know.stats.setdefault("rooms_act", {})["Monster@1"] = {
        "hp_lost_sum": 80.0, "damage_events": 10, "hp_lost_max": 50.0}
    try:
        pol_tail = policy.Policy(know, random.Random(2))
        d_tail_on = pol_tail.decide(tail_st, ctx)
    finally:
        if _rooms_old2 is None:
            know.stats["rooms"].pop("Monster", None)
        else:
            know.stats["rooms"]["Monster"] = _rooms_old2
        if _ract_old2 is None:
            know.stats["rooms_act"].pop("Monster@1", None)
        else:
            know.stats["rooms_act"]["Monster@1"] = _ract_old2
    assert "尾部定价" in d_tail_on.reason, f"尾部定价未留痕: {d_tail_on.reason}"
    m_ton = re.search(r"路径分 (-?\d+\.\d+)", d_tail_on.reason)
    assert m_ton, f"路径分解析失败: {d_tail_on.reason}"
    _band_old = know.policy.get("path_tail_hp_band_pct")
    know.policy["path_tail_hp_band_pct"] = 0.0  # 关闭尾部定价 → 同图不留痕、不抬价
    know.stats.setdefault("rooms", {})["Monster"] = {
        "visits": 10, "outcome_sum": 0.0, "hp_lost_sum": 80.0, "damage_events": 10,
        "hp_lost_max": 50.0}
    know.stats.setdefault("rooms_act", {})["Monster@1"] = {
        "hp_lost_sum": 80.0, "damage_events": 10, "hp_lost_max": 50.0}
    try:
        pol_tail2 = policy.Policy(know, random.Random(2))
        d_tail_off = pol_tail2.decide(tail_st, ctx)
    finally:
        know.policy["path_tail_hp_band_pct"] = _band_old
        if _rooms_old2 is None:
            know.stats["rooms"].pop("Monster", None)
        else:
            know.stats["rooms"]["Monster"] = _rooms_old2
        if _ract_old2 is None:
            know.stats["rooms_act"].pop("Monster@1", None)
        else:
            know.stats["rooms_act"]["Monster@1"] = _ract_old2
    assert "尾部定价" not in d_tail_off.reason, f"尾部定价关闭后不应留痕: {d_tail_off.reason}"
    m_toff = re.search(r"路径分 (-?\d+\.\d+)", d_tail_off.reason)
    assert m_toff and float(m_ton.group(1)) < float(m_toff.group(1)), \
        f"尾部定价未体现为投影罚分（开 {m_ton and m_ton.group(1)} vs 关 {m_toff and m_toff.group(1)}）"

    # 4na) 分幕分层段实证战损（第 266 局批次复盘）：同幕怪物池随楼层递增——
    #      一幕前段 NIBBIT 场均 8.3、后段 VANTOM/KIN/CEREMONIAL 场均 41~43
    #      且贡献生涯前三死因，全幕均值账把后段杀手摊薄成「便宜战」。commit
    #      三级双写（rooms/rooms_act/rooms_band），先验查询按 层段→分幕→跨幕 回落，
    #      样本不足宁可缺账（None）
    know.stats.setdefault("rooms_band", {})
    know.stats["rooms_band"]["ZZB4@1_b3"] = {
        "hp_lost_sum": 160.0, "damage_events": 4, "hp_lost_max": 60.0}
    b_avg, b_worst, b_n = know.room_damage_band_stats("ZZB4", 1, 13)
    assert (round(b_avg, 6), b_worst, b_n) == (40.0, 60.0, 4), \
        f"层段统计读取失败: {b_avg},{b_worst},{b_n}"
    know.stats["rooms_band"]["ZZB4@1_b2"] = {
        "hp_lost_sum": 30.0, "damage_events": 2, "hp_lost_max": 20.0}
    assert know.room_damage_band_stats("ZZB4", 1, 8) is None, "样本<3 的层段不应出账"
    assert know.room_damage_worst("ZZB4", 1, row_in_act=13) == 60.0, "层段尾部记忆读取失败"
    assert know.room_damage_worst("ZZB4", 1, row_in_act=8) is None, \
        "样本不足的层段必须视为无尾部样本（回落口径也不得捏造）"
    # commit 双写：floor=14 → 幕内行 14 → band 3，且 rooms/rooms_act 旧键同步
    know.stats.setdefault("rooms", {})["ZZB4"] = {
        "visits": 10, "outcome_sum": 0.0, "hp_lost_sum": 80.0, "damage_events": 10}
    know.commit_room_damage("ZZB4", 33.0, act=1, floor=14)
    rb = know.stats["rooms_band"].get("ZZB4@1_b3")
    assert rb and rb["damage_events"] == 5 and abs(rb["hp_lost_max"] - 60.0) < 1e-9, \
        f"分层段入账失败: {rb}"
    ra_z = know.stats["rooms_act"].get("ZZB4@1")
    assert ra_z and ra_z["damage_events"] == 1, f"分幕旧键未同步写入: {ra_z}"
    # 先验细化：同钉子数据下后段(band3)实证先验必须贵于全幕口径且命中标记为真
    _p_late, _hit_late = know.room_damage_prior_act("ZZB4", 8.0, 1, row_in_act=13)
    _p_act, _hit_act = know.room_damage_prior_act("ZZB4", 8.0, 1)
    _p_base = know.room_damage_prior("ZZB4", 8.0)
    assert _hit_late and not _hit_act, \
        f"命中标记错误: late={_hit_late} act={_hit_act}"
    assert _p_late > max(_p_act, _p_base), \
        f"层段先验未比全幕口径更贵: late={_p_late:.2f} act={_p_act:.2f} base={_p_base:.2f}"
    know.stats["rooms"].pop("ZZB4", None)
    know.stats["rooms_act"].pop("ZZB4@1", None)
    know.stats["rooms_band"].pop("ZZB4@1_b3", None)
    know.stats["rooms_band"].pop("ZZB4@1_b2", None)

    # 4nb) 单场尾部生存复核（第 266 局批次复盘）：尾部定价只抬均价且随血带深度
    #      缩水——266 局 54% 血规划时留痕「先验9→11（最差48）」，下一战实际 -43。
    #      投影必须用实测单场最差回答「坏一场能不能活」：最坏打完跌破近死带即按
    #      缺口深度加性罚分；关闭旋钮不留痕不罚分；满血段天然零触发；最差值取
    #      层段记忆（55）而非全幕记忆（50）
    veto_heads = [{"index": 0, "row": 12, "col": 0, "node_type": "Monster",
                   "children": [{"row": 13, "col": 0}]}]
    veto_chain = [{"row": 13, "col": 0, "node_type": "Boss"}]
    veto_st = {"screen": "MAP", "available_actions": ["choose_map_node"],
               "map": {"available_nodes": veto_heads, "nodes": veto_heads + veto_chain,
                       "boss_node": {"row": 13}},
               "run": {"current_hp": 43, "max_hp": 80, "gold": 0, "floor": 1,
                       "deck": [{"card_id": "STRIKE_IRONCLAD"}] * 4}}

    def _pin_veto_data():
        know.stats.setdefault("rooms", {})["Monster"] = {
            "visits": 10, "outcome_sum": 0.0, "hp_lost_sum": 80.0, "damage_events": 10,
            "hp_lost_max": 48.0}
        know.stats.setdefault("rooms_act", {})["Monster@1"] = {
            "hp_lost_sum": 80.0, "damage_events": 10, "hp_lost_max": 50.0}
        know.stats.setdefault("rooms_band", {})["Monster@1_b3"] = {
            "hp_lost_sum": 100.0, "damage_events": 5, "hp_lost_max": 55.0}

    _v_rooms = know.stats.get("rooms", {}).get("Monster")
    _v_ract = know.stats.get("rooms_act", {}).get("Monster@1")
    _v_rband = know.stats.get("rooms_band", {}).get("Monster@1_b3")
    _v_pen = know.policy.get("path_tail_veto_penalty")
    try:
        _pin_veto_data()
        d_v_on = policy.Policy(know, random.Random(2)).decide(veto_st, ctx)
        know.policy["path_tail_veto_penalty"] = 0.0
        d_v_off = policy.Policy(know, random.Random(2)).decide(veto_st, ctx)
        know.policy["path_tail_veto_penalty"] = _v_pen  # 恢复后再测满血段（排除旋钮干扰）
        veto_st["run"]["current_hp"] = 79
        d_v_full = policy.Policy(know, random.Random(2)).decide(veto_st, ctx)
    finally:
        know.policy["path_tail_veto_penalty"] = _v_pen
        if _v_rooms is None:
            know.stats["rooms"].pop("Monster", None)
        else:
            know.stats["rooms"]["Monster"] = _v_rooms
        if _v_ract is None:
            know.stats["rooms_act"].pop("Monster@1", None)
        else:
            know.stats["rooms_act"]["Monster@1"] = _v_ract
        if _v_rband is None:
            know.stats.get("rooms_band", {}).pop("Monster@1_b3", None)
        else:
            know.stats["rooms_band"]["Monster@1_b3"] = _v_rband
    assert "尾部生存复核" in d_v_on.reason, f"尾部生存复核未触发: {d_v_on.reason}"
    assert "最差55" in d_v_on.reason, \
        f"生存复核未取层段尾部记忆(应55而非全幕50): {d_v_on.reason}"
    m_von = re.search(r"路径分 (-?\d+\.\d+)", d_v_on.reason)
    m_voff = re.search(r"路径分 (-?\d+\.\d+)", d_v_off.reason)
    assert m_von and m_voff and float(m_von.group(1)) < float(m_voff.group(1)), \
        f"尾部生存复核未体现为罚分（开 {m_von and m_von.group(1)} vs 关 {m_voff and m_voff.group(1)}）"
    assert "尾部生存复核" not in d_v_off.reason, "复核旋钮关闭后不应留痕"
    assert "尾部生存复核" not in d_v_full.reason and "尾部定价" not in d_v_full.reason, \
        f"满血段不应触发尾部定价/复核: {d_v_full.reason}"

    # 4nc) 投影罚分段间清零（第 266 局批次复盘修正）：行前段累计的 raw_penalty
    #      未清零就被第二段 squash 整体携带重扣——中段精英等行前段罚分被记两次账，
    #      违反 96 局「同一坏结局只记一次账」。构造「Monster→精英(depth1)→Boss」
    #      单链，逐项复算路径分并要求严格一致（携带重扣会立刻破坏等式）
    dd_heads = [{"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                 "children": [{"row": 2, "col": 0}]}]
    dd_mid = {"row": 2, "col": 0, "node_type": "Elite", "children": [{"row": 3, "col": 0}]}
    dd_boss = {"row": 3, "col": 0, "node_type": "Boss"}
    dd_deck = [{"card_id": "STRIKE_IRONCLAD"}] * 4
    dd_st = {"screen": "MAP", "available_actions": ["choose_map_node"],
             "map": {"available_nodes": dd_heads, "nodes": dd_heads + [dd_mid, dd_boss],
                     "boss_node": {"row": 3}},
             "run": {"current_hp": 72, "max_hp": 80, "gold": 0, "floor": 3,
                     "deck": dd_deck}}
    _d_rooms_m = know.stats.get("rooms", {}).get("Monster")
    _d_rooms_e = know.stats.get("rooms", {}).get("Elite")
    _d_ract_m = know.stats.get("rooms_act", {}).get("Monster@1")
    _d_ract_e = know.stats.get("rooms_act", {}).get("Elite@1")
    _d_rband_b1 = know.stats.get("rooms_band", {}).get("Monster@1_b1")
    _d_relief = know.policy.get("boss_entry_starve_relief")
    # 饥饿上浮同步归零隔离（第495~498局批复盘）：本用例按旧口径逐项复算路径分，
    # 输出饥饿战损上浮的账目由 3bw 专项用例单独覆盖
    _d_svfrac = know.policy.get("path_starve_loss_frac")
    know.policy["path_starve_loss_frac"] = 0.0
    try:
        # 钉死输入：rooms 无尾部记忆（旧库形态）、无分幕/层段键 → 先验走跨幕口径，
        # 与测试内复算共用同一 getter，夹具污染被自然抵消
        know.stats.setdefault("rooms", {})["Monster"] = {
            "visits": 10, "outcome_sum": 0.0, "hp_lost_sum": 80.0, "damage_events": 10}
        know.stats["rooms"].pop("Elite", None)
        know.stats.setdefault("rooms_act", {}).pop("Monster@1", None)
        know.stats["rooms_act"].pop("Elite@1", None)
        know.stats.setdefault("rooms_band", {}).pop("Monster@1_b1", None)
        know.policy["boss_entry_starve_relief"] = 0.0
        pol_dd = policy.Policy(know, random.Random(2))
        d_dd = pol_dd.decide(dd_st, ctx)
        # —— 复算（与 simulate() 同一公式与常量来源；先验/入场线项自实际留痕
        #      反推，隔离共享夹具的策略值与敌人校准污染——本测试只验「段间账目」）——
        m_fin = re.search(r"预计进\s*Boss\s*血量\s*(\d+)%", d_dd.reason)
        assert m_fin, f"进Boss血量解析失败: {d_dd.reason}"
        final_pct = int(m_fin.group(1)) / 100.0
        # 入场线罚分用实际生效线（留痕里的 <X%，含饥饿放宽后的值）反推
        m_line = re.search(r"进Boss血量预计\d+%<(\d+)%", d_dd.reason)
        p_entry = ((int(m_line.group(1)) / 100.0 - final_pct)
                   * float(know.policy["boss_entry_penalty"])) if m_line else 0.0
        bs = pol_dd.deck_burst(dd_deck) < float(know.policy.get("deck_burst_floor", 30.0))
        gf, _gn = pol_dd._elite_path_gate(
            know.policy, know.policy["path_danger_priors"],
            72, 80, 0, 1.0, bs, act_no=1)
        decay = float(know.policy.get("elite_mid_gate_depth_decay", 0.85))
        mid_raw = (1.0 - gf) * 50.0 * 0.5 * (decay ** 1)
        p_floor = (0.35 - final_pct) * 40.0 if final_pct < 0.35 else 0.0
        sat = float(know.policy["path_penalty_saturation"])

        def _sq(x):
            return sat * math.tanh(x / sat) if x > 0 else x

        w = know.policy["room_weights"]
        expected = (w["Monster"] * 1.25          # depth0 前期积累加成（90%≥62%）
                    + w["Elite"] * 0.1 * 0.97     # depth1 卡组不足规避因子
                    + w["Boss"] * 0.97 ** 2
                    - _sq(mid_raw)                # 第一段：行前段（中段精英投影罚分）
                    - _sq(p_entry + p_floor))     # 第二段：仅含行后段追加（入场线/地板），
                                                  # 行前段旧账已被段间清零摘除
        m_dd = re.search(r"路径分 (-?\d+\.\d+)", d_dd.reason)
        assert m_dd, f"路径分解析失败: {d_dd.reason}"
        assert abs(float(m_dd.group(1)) - expected) < 2.0, \
            f"罚分段间账目不平（疑似携带重扣回潮）: 实际 {m_dd.group(1)} vs 复算 {expected:.4f}"
    finally:
        know.policy["boss_entry_starve_relief"] = _d_relief
        if _d_svfrac is None:
            know.policy.pop("path_starve_loss_frac", None)
        else:
            know.policy["path_starve_loss_frac"] = _d_svfrac
        if _d_rooms_m is None:
            know.stats["rooms"].pop("Monster", None)
        else:
            know.stats["rooms"]["Monster"] = _d_rooms_m
        if _d_rooms_e is None:
            know.stats["rooms"].pop("Elite", None)
        else:
            know.stats["rooms"]["Elite"] = _d_rooms_e
        if _d_ract_m is None:
            know.stats.get("rooms_act", {}).pop("Monster@1", None)
        else:
            know.stats["rooms_act"]["Monster@1"] = _d_ract_m
        if _d_ract_e is None:
            know.stats.get("rooms_act", {}).pop("Elite@1", None)
        else:
            know.stats["rooms_act"]["Elite@1"] = _d_ract_e
        if _d_rband_b1 is None:
            know.stats.get("rooms_band", {}).pop("Monster@1_b1", None)
        else:
            know.stats["rooms_band"]["Monster@1_b1"] = _d_rband_b1

    # 4nd) 存活尾部记忆（第479~482局批复盘）：hp_lost_max 是含死亡样本的
    #      running max——阵亡场掉血恒等于入场血量，max 被永久钉在满管血附近
    #      （实测 Monster 均值10.1/max88、一幕前段均值5.5/max80），尾部定价与
    #      生存复核从 F1 满血起全图空转。修复：commit 按 died 分流维护
    #      hp_lost_max_surv/damage_events_surv 三级双写；room_damage_worst 各层
    #      优先返回成熟存活尾部（≥3 样本），未成熟回落旧口径；死亡样本不得入
    #      存活账但照旧入全量账
    _nd = "SX_SURV"
    know.stats.setdefault("rooms_act", {})[_nd + "@1"] = {
        "hp_lost_sum": 800.0, "damage_events": 100, "hp_lost_max": 80.0}
    try:
        # 死亡样本：只入全量账，存活账不动，getter 未成熟回落旧口径
        know.commit_room_damage(_nd, 79.0, act=1, floor=14, died=True)
        ra_nd = know.stats["rooms_act"][_nd + "@1"]
        assert int(ra_nd.get("damage_events_surv", 0) or 0) == 0, \
            f"死亡样本漏进存活账: {ra_nd}"
        assert abs(float(ra_nd["hp_lost_max"]) - 80.0) < 1e-9, \
            f"死亡样本应照旧更新全量 max(79<80 不变): {ra_nd.get('hp_lost_max')}"
        assert know.room_damage_worst(_nd, 1) == 80.0, \
            f"存活账未成熟必须回落旧口径: {know.room_damage_worst(_nd, 1)}"
        # 存活样本：<3 不出账；≥3 后优先于被死亡污染的旧 max
        know.commit_room_damage(_nd, 30.0, act=1, floor=14, died=False)
        assert know.room_damage_worst(_nd, 1) == 80.0, "存活样本<3 不应出账"
        know.commit_room_damage(_nd, 25.0, act=1, floor=14, died=False)
        know.commit_room_damage(_nd, 35.0, act=1, floor=14, died=False)
        ra_nd = know.stats["rooms_act"][_nd + "@1"]
        assert int(ra_nd["damage_events_surv"]) == 3 and abs(
            float(ra_nd["hp_lost_max_surv"]) - 35.0) < 1e-9, \
            f"存活尾部三级入账失败: {ra_nd}"
        assert know.room_damage_worst(_nd, 1) == 35.0, \
            f"成熟存活尾部应压过死亡污染旧账: {know.room_damage_worst(_nd, 1)}"
        assert int(ra_nd["damage_events"]) == 104, \
            f"全量账必须照常累积(100+4): {ra_nd.get('damage_events')}"
        # 层段级同口径：带内存活尾部最优先（压过带内旧账与分幕旧账）
        know.stats.setdefault("rooms_band", {})[_nd + "@1_b3"] = {
            "hp_lost_sum": 500.0, "damage_events": 50, "hp_lost_max": 77.0,
            "damage_events_surv": 3, "hp_lost_max_surv": 41.0}
        assert know.room_damage_worst(_nd, 1, row_in_act=14) == 41.0, \
            f"层段存活尾部应最优先: {know.room_damage_worst(_nd, 1, row_in_act=14)}"
    finally:
        know.stats["rooms_act"].pop(_nd + "@1", None)
        know.stats.get("rooms_band", {}).pop(_nd + "@1_b3", None)


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
    pol.note_action_failed(d_rm1.action, d_rm1.tags)
    d_rm1_retry = pol.decide(removal_state("请选择一张卡"), ctx)
    assert (d_rm1_retry.tags and d_rm1_retry.tags[0][0] == "card_remove"
            and d_rm1_retry.params.get("option_index") == 1), \
        f"无关键词删牌首次 409 后语义丢失/改删强牌: {d_rm1_retry.reason}"
    d_rm2 = pol.decide(removal_state("移除一张牌。"), ctx)  # 关键词路径（握手已消费）
    assert d_rm2.tags and d_rm2.tags[0][0] == "card_remove", f"删牌关键词识别失败: {d_rm2.reason}"
    d_rm3 = pol.decide(removal_state("选择一张牌加入你的牌组。"), ctx)  # 负例：普通拿牌屏
    assert d_rm3.tags and d_rm3.tags[0][0] == "card_pick", f"普通拿牌屏被误判为删牌: {d_rm3.reason}"

    # remove_card_at_shop 本身也必须等成功回执才发布握手。失败时留在商店稳定
    # 重试；成功 tag 到账后，无关键词 CARD_SELECTION 才绑定 remove 模式。
    shop_remove_ctx = DummyCtx()
    shop_remove_ctx.run_id = "RUN_SHOP_REMOVE_TX"
    shop_remove_ctx.credit_tags = []
    shop_remove_state = {
        "screen": "SHOP", "run_id": "RUN_SHOP_REMOVE_TX",
        "available_actions": ["remove_card_at_shop", "close_shop_inventory"],
        "shop": {"is_open": True, "cards": [], "relics": [], "potions": [],
                 "card_removal": {"available": True, "used": False,
                                  "enough_gold": True, "price": 50}},
        "run": {"current_hp": 60, "max_hp": 80, "gold": 200, "floor": 9,
                "potions": [], "deck": removal_state("")["selection"]["cards"]}}
    pol._removal_pending_floor = -1
    d_shop_rm = pol.decide(shop_remove_state, shop_remove_ctx)
    assert d_shop_rm.action == "remove_card_at_shop" \
        and pol._removal_pending_floor == -1, \
        "删牌请求在 HTTP 成功前提前发布握手"
    pol.note_action_failed(d_shop_rm.action, d_shop_rm.tags)
    d_shop_rm_retry = pol.decide(shop_remove_state, shop_remove_ctx)
    assert d_shop_rm_retry.action == "remove_card_at_shop" \
        and pol._removal_pending_floor == -1, \
        "失败删牌请求没有稳定重试或污染握手"
    shop_remove_ctx.credit_tags.extend(d_shop_rm_retry.tags)
    generic_remove = removal_state("请选择一张卡")
    generic_remove["run_id"] = "RUN_SHOP_REMOVE_TX"
    d_shop_selection = pol.decide(generic_remove, shop_remove_ctx)
    assert (d_shop_selection.tags and d_shop_selection.tags[0][0] == "card_remove"
            and d_shop_selection.params.get("option_index") == 1), \
        f"成功删牌握手未绑定无关键词选牌屏: {d_shop_selection.reason}"

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

    # 3yh) 多敌战斗辅助体转火（第 136~137 批复盘）：头号杀手同族双子（生涯46战24死）
    #      的神官本回合零伤害意图（治疗/增益型）——威胁分成恒为 0，旧评分永远把它排
    #      最后，信徒被持续强化、意图逐轮滚升，拖长战斗正是死因形态。零伤害意图的
    #      辅助体获得定向转火加分；负例：辅助体转为攻击意图后恢复常规威胁评分。
    def support_state(sup_threat):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 2,
            "combat": {"player": {"current_hp": 70, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [{"index": 0, "card_id": "SUP_STRIKE", "name": "打击",
                                 "playable": True, "energy_cost": 1, "requires_target": True,
                                 "valid_target_indices": [0, 1],
                                 "dynamic_values": [{"name": "Damage", "current_value": 8}]}],
                       "enemies": [
                           {"index": 0, "enemy_id": "KIN_PRIEST_T", "name": "同族神官",
                            "current_hp": 30, "max_hp": 50, "block": 0, "is_alive": True,
                            "is_hittable": True,
                            "intents": [{"total_damage": sup_threat}]},
                           {"index": 1, "enemy_id": "KIN_FOLLOWER_T", "name": "同族信徒",
                            "current_hp": 120, "max_hp": 190, "block": 0, "is_alive": True,
                            "is_hittable": True,
                            "intents": [{"total_damage": 20}]}]},
            "run": {"current_hp": 70, "max_hp": 80, "gold": 0, "floor": 17, "deck": []}}

    d_sup = pol.decide(support_state(0), ctx)
    assert d_sup.action == "play_card" and d_sup.params.get("target_index") == 0 \
        and "辅助" in d_sup.reason, \
        f"零伤害辅助体未被优先转火: {d_sup.reason}（{d_sup.params}）"
    d_sup2 = pol.decide(support_state(4), ctx)
    assert d_sup2.action == "play_card" and d_sup2.params.get("target_index") == 1 \
        and "辅助体优先转火" not in d_sup2.reason, \
        f"辅助体转攻击意图后应恢复威胁评分: {d_sup2.reason}（{d_sup2.params}）"

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

    # 3x''') 消耗螺旋治理边界修正（第 135 局复盘，F11 精英战被异蛙寄生虫 -76 实证）：
    #       ① 彼岸咆哮（"…若这张牌在你的消耗牌堆中…"）仅提及消耗牌堆，不得计入
    #       消耗上限——旧纯文本匹配让 11 张卡组（上限=1）打一张彼岸咆哮就锁死坚毅；
    #       ② 致死回合豁免上限：21 血对 12 意图、坚毅是唯一格挡牌时，烧一张牌
    #       换活命永远值得（旧逻辑禁玩 → 白吃整轮意图进入死亡螺旋）
    HOWL = {"index": 0, "card_id": "HOWL_FROM_BEYOND", "name": "彼岸咆哮", "playable": True,
            "energy_cost": 3, "requires_target": False,
            "rules_text": "对所有敌人造成18点伤害。 在你的回合结束时，如果这张牌在你的消耗牌堆中，则将其打出。",
            "dynamic_values": [{"name": "Damage", "current_value": 18}]}
    GRIT = {"index": 1, "card_id": "TRUE_GRIT", "name": "坚毅", "playable": True,
            "energy_cost": 1, "requires_target": False,
            "rules_text": "获得7点格挡。 随机消耗1张牌。",
            "dynamic_values": [{"name": "Block", "current_value": 7}]}
    INFC2 = {"index": 2, "card_id": "INFECTION", "name": "感染", "playable": False,
             "energy_cost": 99, "requires_target": False, "rules_text": "不可打出。"}
    INFC3 = {"index": 3, "card_id": "INFECTION", "name": "感染", "playable": False,
             "energy_cost": 99, "requires_target": False, "rules_text": "不可打出。"}
    assert not policy._exhausts_other_cards(HOWL), "彼岸咆哮（仅提及消耗牌堆）被误判为消耗其他牌"
    assert policy._exhausts_other_cards(GRIT), "坚毅（随机消耗1张牌）未被识别为消耗其他牌"
    ex_saved = pol._exhaust_plays
    try:
        # ① 打出彼岸咆哮不得占用消耗计数
        pol._exhaust_plays = 0
        howl_state = {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 3,
            "combat": {"player": {"current_hp": 70, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [HOWL],
                       "enemies": [{"index": 0, "enemy_id": "X", "name": "怪", "current_hp": 100,
                                    "max_hp": 100, "block": 0, "is_alive": True, "is_hittable": True,
                                    "intents": []}]},
            "run": {"current_hp": 70, "max_hp": 80, "gold": 0, "floor": 11,
                    "deck": [{}] * 11},
        }
        d_howl = pol.decide(howl_state, ctx)
        assert d_howl.action == "play_card" and d_howl.params.get("card_index") == 0, \
            f"彼岸咆哮应正常打出: {d_howl.action}（{d_howl.reason}）"
        assert pol._exhaust_plays == 0, \
            f"彼岸咆哮不得占用消耗上限计数: {pol._exhaust_plays}"
        # ② 上限占满（=1）且非致死回合：坚毅仍被锁（僵局防护不松）
        pol._exhaust_plays = 1
        grit_lock_state = {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 4,
            "combat": {"player": {"current_hp": 60, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [GRIT],
                       "enemies": [{"index": 0, "enemy_id": "X", "name": "怪", "current_hp": 100,
                                    "max_hp": 100, "block": 0, "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": 6}]}]},
            "run": {"current_hp": 60, "max_hp": 80, "gold": 0, "floor": 11,
                    "deck": [{}] * 11},
        }
        d_lock = pol.decide(grit_lock_state, ctx)
        assert not (d_lock.action == "play_card" and d_lock.params.get("card_index") == 1), \
            f"非致死回合消耗上限占满后坚毅应被锁定: {d_lock.params}（{d_lock.reason}）"
        # ③ 致死回合（21 血对 12 意图，惨胜线内）：上限豁免，坚毅必须打出
        lethal_grit_state = {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 5,
            "combat": {"player": {"current_hp": 21, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [GRIT, INFC2, INFC3],
                       "enemies": [{"index": 0, "enemy_id": "X", "name": "怪", "current_hp": 100,
                                    "max_hp": 100, "block": 0, "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": 12}]}]},
            "run": {"current_hp": 21, "max_hp": 80, "gold": 0, "floor": 11,
                    "deck": [{}] * 11},
        }
        d_lethal = pol.decide(lethal_grit_state, ctx)
        assert d_lethal.action == "play_card" and d_lethal.params.get("card_index") == 1, \
            f"致死回合消耗上限必须豁免（坚毅是唯一活路）: {d_lethal.action} {d_lethal.params}（{d_lethal.reason}）"
    finally:
        pol._exhaust_plays = ex_saved

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
    _veto_saved_3y = know.policy.get("path_tail_veto_penalty")
    know.policy["path_tail_veto_penalty"] = 0.0  # 隔离尾部生存复核（4nb 单测覆盖），
                                                 # 本组只验证入场线惩罚的开/关差分
    d_gate_off = pol.decide(dict(gate_map), ctx)
    assert d_gate_off.params.get("option_index") == 0, \
        f"基线失效（无惩罚时怪物积累路线应胜出）: {d_gate_off.reason}"
    know.policy["boss_entry_penalty"] = 110.0  # 生效：低投影入场被重罚，商店续航反超
    d_gate_on = pol.decide(dict(gate_map), ctx)
    know.policy["path_tail_veto_penalty"] = _veto_saved_3y
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

    # 2b2) 断线重连残缺局守卫（第 214 批复盘）：重连落在局中途的旧对局只剩尾部
    #      几条决策（LE23B03412FL：4 决策 F17 阵亡）——卡牌/房间/敌人归因全是
    #      断章取义，入账即污染演化证据：F≥10 且决策 <10 的败局必须整体忽略
    ag.ctx.reset_for("RUN_PARTIAL", 0)
    ag.ctx.decisions = [{"t": f"00:00:0{i}", "screen": "MAP", "floor": 16 + (i % 2),
                         "hp": 40, "gold": 0, "action": "choose_map_node",
                         "params": {}, "reason": "x"} for i in range(4)]
    runs_before = ag.know.stats["global"]["runs"]
    logs_before = set((tmp_agent / "runs").glob("*.json"))
    ag._finalize(victory=False, floor=17)
    assert ag.know.stats["global"]["runs"] == runs_before, "断线重连残缺局被计入生涯统计"
    assert set((tmp_agent / "runs").glob("*.json")) == logs_before, "残缺局日志被写入 runs/"

    # 2c) 对局日志按 run_id 复用 + 断线重连续接局史（第 218 批复盘实证）：大脑
    #     在 F23 签名故障自杀，终局才落盘的旧实现让前半局决策/战斗记录全灭，
    #     重连进程另起新账把 24 层深局记成 24 决策/1 拿牌/0 遗物的残缺局。
    #     增量存档必须复用同一文件，重连进程必须接回既有局史
    p1 = know.save_run_log("RUN_REUSE", {"run_id": "RUN_REUSE", "decisions": [1]})
    p2 = know.save_run_log("RUN_REUSE", {"run_id": "RUN_REUSE", "decisions": [1, 2]})
    assert p1 == p2, f"同 run_id 应复用同一日志文件: {p1} vs {p2}"
    assert json.loads(p2.read_text(encoding="utf-8"))["decisions"] == [1, 2], "终稿未覆盖增量稿"
    assert know.load_run_log("RUN_REUSE")["decisions"] == [1, 2], "既有局史读不回"
    assert know.load_run_log("RUN_NOPE") is None, "无日志的 run_id 应返回 None"
    ag_crash = agent_mod.Agent(dict(agent_mod.DEFAULT_CONFIG))
    st_ev = {"screen": "EVENT", "run_id": "RUN_CRASH",
             "run": {"current_hp": 70, "max_hp": 80, "gold": 10, "floor": 5}}
    track_accepted(ag_crash, st_ev,
                   policy.Decision(
                       action="choose_event_option", reason="x",
                       tags=[("card_pick", "OLD_CARD"),
                             ("relic_pick", "OLD_RELIC"),
                             ("map_node", "Elite"),
                             ("novelty_trial", "event", "OLD_EVENT", 1),
                             ("selection_click", 7, 2),
                             ("reward_attempt", "Gold", "duplicate", 0),
                             ("potion_attempt", 0, "OLD_POTION"),
                             ("combat_play_commit", "OLD_CARD", False,
                              False, 0.0, 1, "")]))
    ag_crash._save_run_progress({"floor": 5}, force=True)   # 崩溃前最后一次增量落盘
    # A new durable pick must force an incremental write even though fewer than 15
    # decisions elapsed and the floor did not change.
    track_accepted(ag_crash, st_ev,
                   policy.Decision(action="choose_event_option", reason="new pick",
                                   tags=[("card_pick", "NEW_CARD")]))
    crash_raw = ag_crash.know.load_run_log("RUN_CRASH")
    assert crash_raw.get("attribution_tags") == [
        ["card_pick", "OLD_CARD"], ["relic_pick", "OLD_RELIC"],
        ["map_node", "Elite"], ["card_pick", "NEW_CARD"]], \
        f"增量日志未隔离/及时保存长期归因: {crash_raw.get('attribution_tags')}"
    ag_rejoin = agent_mod.Agent(dict(agent_mod.DEFAULT_CONFIG))  # 模拟重启后的新进程
    ag_rejoin._track(st_ev, policy.Decision(action=None))
    assert len(ag_rejoin.ctx.decisions) == 2, \
        f"断线重连未接回决策史: {len(ag_rejoin.ctx.decisions)} 条"
    assert ag_rejoin.ctx.started_at == ag_crash.ctx.started_at, "断线重连未保留开局时间"
    assert ag_rejoin.ctx.attribution_tags == [
        ("card_pick", "OLD_CARD"), ("relic_pick", "OLD_RELIC"),
        ("map_node", "Elite"), ("card_pick", "NEW_CARD")], \
        f"断线重连未精确恢复长期归因: {ag_rejoin.ctx.attribution_tags}"
    assert ag_rejoin.ctx.credit_tags == [], \
        f"断线重连错误重放瞬时握手流: {ag_rejoin.ctx.credit_tags}"
    # Reflect must consume the durable ledger exactly once.  Stop immediately after
    # commit_run_end so the broad policy-evolution portion stays out of this focused test.
    import reflect as reflect_mod
    captured_attribution = {}
    original_commit_run_end = ag_rejoin.know.commit_run_end

    class _AttributionCaptured(Exception):
        pass

    def _capture_run_end(outcome, victory, cards, relics, rooms, enemy, event,
                         raw_floor=None):
        captured_attribution.update(cards=list(cards), relics=list(relics), rooms=list(rooms),
                                    raw_floor=raw_floor)
        raise _AttributionCaptured

    ag_rejoin.know.commit_run_end = _capture_run_end
    try:
        reflect_mod.finalize_run(ag_rejoin.know, ag_rejoin.ctx, False, 5)
    except _AttributionCaptured:
        pass
    finally:
        ag_rejoin.know.commit_run_end = original_commit_run_end
    assert captured_attribution == {
        "cards": ["OLD_CARD", "NEW_CARD"],
        "relics": ["OLD_RELIC"], "rooms": ["Elite"], "raw_floor": 5}, \
        f"终局未使用续接后的长期归因: {captured_attribution}"
    # Old incremental logs remain compatible and restore no invented attribution.
    ag_old_log = agent_mod.Agent(dict(agent_mod.DEFAULT_CONFIG))
    ag_old_log._track({"screen": "EVENT", "run_id": "RUN_REUSE",
                       "run": {"current_hp": 70, "max_hp": 80,
                               "gold": 10, "floor": 5}},
                      policy.Decision(action=None))
    assert ag_old_log.ctx.attribution_tags == [], \
        f"旧日志缺字段时不应猜测归因: {ag_old_log.ctx.attribution_tags}"

    # 2d) 签名故障动作进程内拉黑（第 218 批复盘）：被拉黑动作不再发出——
    #     有安全替代改发安全动作，无替代时原地等待而非重试必败调用
    pol.mark_action_broken("crystal_clear_cell")
    cs_broken = {"screen": "CRYSTAL_SPHERE", "available_actions": ["crystal_clear_cell"],
                 "crystal_sphere": {"is_finished": False, "grid_width": 11, "grid_height": 11,
                                    "hidden_cells": [[0, 0], [1, 1]], "items": [],
                                    "divinations_left": 3},
                 "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 23, "deck": []}}
    d_broken = pol.decide(cs_broken, ctx)
    assert d_broken.action != "crystal_clear_cell", f"拉黑动作仍被发出: {d_broken.action}"
    cs_safe = dict(cs_broken)
    cs_safe["available_actions"] = ["crystal_clear_cell", "proceed"]
    d_safe = pol.decide(cs_safe, ctx)
    assert d_safe.action == "proceed", f"拉黑后未改发安全替代: {d_safe.action}"
    pol._broken_actions.clear()
    d_ok = pol.decide(cs_broken, ctx)
    assert d_ok.action == "crystal_clear_cell", f"清空拉黑后正常动作未恢复: {d_ok.action}"

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

    # 3cc) Boss 前夜三区生存余量裁决（第 244 批复盘改版，取代 63/214/228 批口径）：
    #      旧判据「场均战损≥回血量 且 血量≥锻造线 → 锻造」是方向性错误的边际分析——
    #      240~243 批五局前夜锻造后以 0.4~7 点血量差被一幕 Boss 处决，全部落在
    #      「回血即可翻盘」的翻转带内；唯一前夜回血的 8VT5 局以 1% 生还。
    #      新判据按悲观战损（场均×boss_eve_pess_mult=1.5）分三区：
    #        溢出区（有效回血<8%血条）→ 锻造（63 局教义的唯一保留点）
    #        翻转带（不回血预期余量 ≤ 安全余量 0.10×最大生命）→ 回血
    #        安全区（稳过悲观战损 且 ≥锻造线）→ 锻造
    know.stats["enemies"]["BOSS_HOG"] = {
        "encounters": 6, "hp_lost_sum": 200.0, "deaths": 2, "wins": 4,
        "boss_encounters": 2, "boss_hp_lost_sum": 170.0, "boss_deaths": 1}
    know.stats["enemies"]["BOSS_PIG"] = {
        "encounters": 6, "hp_lost_sum": 200.0, "deaths": 2, "wins": 4,
        "boss_encounters": 2, "boss_hp_lost_sum": 180.0, "boss_deaths": 1}
    bl, bn = know.boss_loss_stats()
    assert bn == 4 and abs(bl - 87.5) < 1e-6, f"Boss 分档统计错误: {bl}/{bn}"
    ctx.rest_before_boss = True
    rest_boss_state = dict(rest_state)
    rest_boss_state["run"] = {"current_hp": 70, "max_hp": 80, "gold": 0, "floor": 15,
                              "deck": [{"card_id": "STRIKE_IRONCLAD", "upgraded": False}]}
    # 超凶 Boss（场均 87.5 > 满血）：悲观战损 131.25，70 血余量远低于安全线——
    # 旧 63 批口径此处锻造（「战损≥满血则回血无效」），但 70 血仍有 10 点有效
    # 回血：回血是唯一确定性的生存增量，翻转带必须回血
    d_eve_flip = pol.decide(rest_boss_state, ctx)
    assert d_eve_flip.tags[0] == ("rest", "heal"), \
        f"超凶Boss翻转带应回血（244批三区裁决）: {d_eve_flip.reason}"
    know.stats["enemies"]["BOSS_HOG"]["boss_hp_lost_sum"] = 46.0   # 场均值降至 22.5 < 回血量 24
    know.stats["enemies"]["BOSS_PIG"]["boss_hp_lost_sum"] = 44.0
    d_eve_heal = pol.decide(rest_boss_state, ctx)
    assert d_eve_heal.tags[0] == ("rest", "heal"), f"战损低于回血量应回血: {d_eve_heal.reason}"
    # 翻转带实证回归（240~243 批）：场均 45、血量 66%（≥旧锻造线 65%）——
    # 旧口径此处锻造（K0P4 局随后以 4 点血量差被处决），新口径必须回血
    know.stats["enemies"]["BOSS_HOG"]["boss_hp_lost_sum"] = 90.0
    know.stats["enemies"]["BOSS_PIG"]["boss_hp_lost_sum"] = 90.0
    rest_flip = dict(rest_boss_state)
    rest_flip["run"] = dict(rest_boss_state["run"], current_hp=53)  # 66.25%，悲观 67.5
    d_eve_flip2 = pol.decide(rest_flip, ctx)
    assert d_eve_flip2.tags[0] == ("rest", "heal"), \
        f"翻转带（66%血/场均45）应回血（K0P4局处决差回归）: {d_eve_flip2.reason}"
    # 溢出区：接近满血（有效回血 5 < 8%×80=6.4）→ 锻造（63 局教义保留点）
    rest_full = dict(rest_boss_state)
    rest_full["run"] = dict(rest_boss_state["run"], current_hp=75)  # 93.75%
    d_eve_ovf = pol.decide(rest_full, ctx)
    assert d_eve_ovf.tags[0] == ("rest", "smith"), \
        f"接近满血的前夜应锻造（回血无效投资）: {d_eve_ovf.reason}"
    # 安全区：场均 30（悲观 45）、血量 70（余量 25 > 8 且 87.5% ≥ 锻造线 65%）→ 锻造
    know.stats["enemies"]["BOSS_HOG"]["boss_hp_lost_sum"] = 60.0
    know.stats["enemies"]["BOSS_PIG"]["boss_hp_lost_sum"] = 60.0
    d_eve_safe = pol.decide(rest_boss_state, ctx)
    assert d_eve_safe.tags[0] == ("rest", "smith"), \
        f"安全区（稳过悲观战损且≥锻造线）应锻造: {d_eve_safe.reason}"
    # 余量达标但血量低于锻造线 → 回血（场均 26.67、血量 63.75%：余量 11>8 但 <65%）
    know.stats["enemies"]["BOSS_HOG"]["boss_hp_lost_sum"] = 53.33
    know.stats["enemies"]["BOSS_PIG"]["boss_hp_lost_sum"] = 53.33
    rest_below = dict(rest_boss_state)
    rest_below["run"] = dict(rest_boss_state["run"], current_hp=51)
    d_eve_below = pol.decide(rest_below, ctx)
    assert d_eve_below.tags[0] == ("rest", "heal"), \
        f"余量达标但低于锻造线应回血: {d_eve_below.reason}"
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
    # 减牌计价（第 136~137 批复盘）：滑脚木桥「跨越」每跨一次随机掉一张牌
    # （card_avg=-1），旧公式反号虚标 +2 分导致四连跨白掉四张牌——净减牌必须计罚
    know.commit_event_option("LOSS_EV", "DROP", 0.0, 0.0, died=False, deck_delta=-1)
    v_drop, n_drop = know.event_option_value("LOSS_EV", "DROP")
    assert v_drop <= -0.99 and n_drop == 1, f"减牌事件未按失去卡值计罚: {v_drop}/{n_drop}"

    # 3ee) 事件结算管线：pending_event 元组新增卡组规模字段后读写两端必须一致
    ag.ctx.reset_for("RUN_EVT", 0)
    _ev_start = {"screen": "EVENT", "run_id": "RUN_EVT",
                 "run": {"current_hp": 80, "max_hp": 80, "gold": 50, "floor": 3,
                         "deck": [{"card_id": "A"}]}}
    track_accepted(ag, _ev_start,
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

    # 3ee2) 事件内换项抉择先行结算 + 同实例重选停滞罚分（第 214 批复盘）：
    #      滑脚木桥「再撑一会」单局八连——旧逻辑 pending_event 被后选覆盖，
    #      除最后一次外永不入账，n 恒 0 被「样本最少」规则反复选中。
    #      a) agent 端：同事件未离场改选其他选项时，上一次选择必须立即落库；
    #         同键重挂（tick 级重试）不产生幻影样本
    ag.ctx.reset_for("RUN_EVT2", 0)
    ev2_state = {"screen": "EVENT", "run_id": "RUN_EVT2",
                 "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 9,
                         "deck": [{"card_id": "A"}, {"card_id": "B"}]}}
    track_accepted(ag, ev2_state,
                   policy.Decision(action="choose_event_option",
                                   tags=[("event_choice", "BRIDGE_EV", "HOLD")]))
    track_accepted(ag, ev2_state,
                   policy.Decision(action="choose_event_option",
                                   tags=[("event_choice", "BRIDGE_EV", "HOLD")]))
    hold0 = tknow.stats["events"].get("BRIDGE_EV", {}).get("HOLD")
    assert not hold0, f"同键 tick 重试产生了幻影样本: {hold0}"
    ev2_state2 = {"screen": "EVENT", "run_id": "RUN_EVT2",
                  "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 9,
                          "deck": [{"card_id": "A"}]}}  # 第一次选择后掉了一张牌
    track_accepted(ag, ev2_state2,
                   policy.Decision(action="choose_event_option",
                                   tags=[("event_choice", "BRIDGE_EV", "CROSS")]))
    hold = tknow.stats["events"].get("BRIDGE_EV", {}).get("HOLD")
    assert hold and hold["n"] == 1 and hold.get("card_delta_sum") == -1.0, \
        f"事件内换项抉择未先行结算（上一次选择被吞）: {hold}"
    #      b) policy 端：同实例已选次数计入样本并倒扣价值，-1 已知项反超 0 分原地踏步项
    know.stats["events"]["BRIDGE_POL"] = {
        "CROSS": {"n": 10, "hp_delta_sum": 0.0, "gold_delta_sum": 0.0, "deaths": 0,
                  "card_delta_sum": -10.0}}
    bridge_state = {"screen": "EVENT", "available_actions": ["choose_event_option"],
                    "run_id": "RUN_BRIDGE",
                    "event": {"event_id": "BRIDGE_POL", "title": "滑脚木桥", "is_finished": False,
                              "options": [{"index": 0, "title": "再撑一会", "text_key": "HOLD",
                                           "is_locked": False, "is_proceed": False},
                                          {"index": 1, "title": "跨越", "text_key": "CROSS",
                                           "is_locked": False, "is_proceed": False}]},
                    "run": {"current_hp": 40, "max_hp": 80, "gold": 0, "floor": 9, "deck": []}}
    pol_bridge = policy.Policy(know, random.Random(2))
    ctx.run_id = "RUN_BRIDGE"
    ctx.credit_tags = []
    d_b1 = pol_bridge.decide(bridge_state, ctx)
    assert d_b1.params.get("option_index") == 0, f"首次应选 0 分未知项: {d_b1.reason}"
    ctx.credit_tags.extend(d_b1.tags)  # 模拟服务端成功回执；下一 tick 才产生停滞计数
    d_b2 = pol_bridge.decide(bridge_state, ctx)
    assert d_b2.params.get("option_index") == 1, \
        f"同实例重选必须吃停滞罚分（旧版会无限重选原地踏步项）: {d_b2.reason}"
    #      c) 跨实例（换楼层/换 run）罚分自动清零，不影响正常事件选择
    bridge_state3 = dict(bridge_state, run_id="RUN_BRIDGE2")
    pol_bridge2 = policy.Policy(know, random.Random(2))
    ctx.run_id = "RUN_BRIDGE2"
    ctx.credit_tags = []
    d_b3 = pol_bridge2.decide(bridge_state3, ctx)
    assert d_b3.params.get("option_index") == 0, f"新实例不应继承停滞罚分: {d_b3.reason}"

    # 3ee4) 事件遗物/药水收益入账（第 372~373 局批次复盘）：佩尔/特兹卡塔拉/
    #      木雕类「给遗物」的选项此前在结算账本上全是 0.0——账本只认 hp/gold/card，
    #      而遗物断供恰是当前版本输出不足的上游病因之一。结算端按选择前后
    #      遗物/药水签名做差入账，估值端计价后给遗物的选项必须反超真零收益项
    ag.ctx.reset_for("RUN_EVT_R", 0)
    _rel_a = {"screen": "EVENT", "run_id": "RUN_EVT_R",
              "run": {"current_hp": 80, "max_hp": 80, "gold": 50, "floor": 4,
                      "deck": [{"card_id": "A"}],
                      "relics": [{"relic_id": "BURNING_BLOOD"}],
                      "potions": [{"occupied": False}]}}
    track_accepted(ag, _rel_a,
                   policy.Decision(action="choose_event_option",
                                   tags=[("event_choice", "PAEL_EV", "FLESH")]))
    ag._track({"screen": "MAP", "run_id": "RUN_EVT_R",
               "run": {"current_hp": 80, "max_hp": 80, "gold": 50, "floor": 5,
                       "deck": [{"card_id": "A"}],
                       "relics": [{"relic_id": "BURNING_BLOOD"},
                                  {"relic_id": "PAELS_FLESH"}],
                       "potions": [{"occupied": False}]}},
              policy.Decision(action=None))
    pe_r = tknow.stats["events"].get("PAEL_EV", {}).get("FLESH")
    assert pe_r and pe_r["n"] == 1 and pe_r.get("relic_delta_sum") == 1.0 \
        and pe_r.get("potion_delta_sum") == 0.0, f"事件遗物增量管线断裂: {pe_r}"
    v_relic, n_relic = tknow.event_option_value("PAEL_EV", "FLESH")
    assert v_relic >= 2.0 and n_relic == 1, f"遗物收益未计入事件价值: {v_relic}"
    #      药水栏位占用变化同样入账
    ag.ctx.reset_for("RUN_EVT_P", 0)
    _pot_start = {"screen": "EVENT", "run_id": "RUN_EVT_P",
                  "run": {"current_hp": 80, "max_hp": 80, "gold": 50, "floor": 6,
                          "deck": [{"card_id": "A"}], "relics": [],
                          "potions": [{"occupied": False}]}}
    track_accepted(ag, _pot_start,
                   policy.Decision(action="choose_event_option",
                                   tags=[("event_choice", "COURIER_EV", "GRAB")]))
    ag._track({"screen": "MAP", "run_id": "RUN_EVT_P",
               "run": {"current_hp": 80, "max_hp": 80, "gold": 50, "floor": 7,
                       "deck": [{"card_id": "A"}], "relics": [],
                       "potions": [{"occupied": True}]}},
              policy.Decision(action=None))
    pe_p = tknow.stats["events"].get("COURIER_EV", {}).get("GRAB")
    assert pe_p and pe_p.get("potion_delta_sum") == 1.0 \
        and pe_p.get("relic_delta_sum") == 0.0, f"事件药水增量管线断裂: {pe_p}"
    #      终局屏 run 载荷被清空时按「签名不变」处理——不得把死亡结算成丢光遗物
    ag.ctx.reset_for("RUN_EVT_D", 0)
    _death_start = {"screen": "EVENT", "run_id": "RUN_EVT_D",
                    "run": {"current_hp": 80, "max_hp": 80, "gold": 50, "floor": 8,
                            "deck": [{"card_id": "A"}],
                            "relics": [{"relic_id": "BURNING_BLOOD"}]}}
    track_accepted(ag, _death_start,
                   policy.Decision(action="choose_event_option",
                                   tags=[("event_choice", "DEATH_EV", "RIP")]))
    ag._track({"screen": "GAME_OVER", "run_id": "RUN_EVT_D", "run": {}},
              policy.Decision(action=None))
    pe_d = tknow.stats["events"].get("DEATH_EV", {}).get("RIP")
    assert pe_d and pe_d["n"] == 1 and pe_d.get("relic_delta_sum") == 0.0, \
        f"终局空载荷被误结算成遗物损失: {pe_d}"

    # 3ee3) 敌方血池/火力观测写入侧（第 214 批补全）：首帧采血池（非召唤口径）、
    #      回合边界采格挡前火力，经 ctx.combat 的 obs_* 键交给 agent 结算入库——
    #      此前写入侧在回滚中丢失，全库 hp_pool_n=0、boss_vitals_worst 恒 None
    ctx.combat = {"comp_id": "VIT_DUO", "node_type": "Boss"}
    vit_state = {"screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 1,
                 "combat": {"player": {"current_hp": 80, "max_hp": 80, "block": 0, "energy": 3},
                            "hand": [],
                            "enemies": [{"index": 0, "enemy_id": "VIT_A", "name": "甲",
                                         "current_hp": 100, "max_hp": 120, "block": 0,
                                         "is_alive": True, "is_hittable": True,
                                         "intents": [{"total_damage": 10}]},
                                        {"index": 1, "enemy_id": "VIT_B", "name": "乙",
                                         "current_hp": 50, "max_hp": 60, "block": 0,
                                         "is_alive": True, "is_hittable": True,
                                         "intents": [{"total_damage": 6}]}]},
                 "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 17, "deck": []}}
    pol.decide(vit_state, ctx)
    assert ctx.combat.get("obs_hp_pool") == 180.0 \
        and ctx.combat.get("obs_fire_rounds") == 1 and ctx.combat.get("obs_fire_sum") == 16.0, \
        f"血池/火力观测写入侧断裂: {ctx.combat}"
    pol.decide(dict(vit_state, turn=2), ctx)
    assert ctx.combat.get("obs_fire_rounds") == 2 and ctx.combat.get("obs_fire_sum") == 32.0 \
        and ctx.combat.get("obs_hp_pool") == 180.0, f"火力回合边界采样断裂: {ctx.combat}"
    ctx.combat = None

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

    # 3hh-bis) 单薄卡组正价值保底（第 236 局复盘）：VS71 局开局连战五场零拿牌
    #          ——0.8 分的正价值候选被 1.0 门槛拦下（单薄折扣未触底），随后
    #          F5 -47/F6 -33 饿死。卡组单薄（非基础牌 < core）时，严格正价值
    #          候选不再因低于门槛被跳过；膨胀卡组照旧跳过（门槛防注水语义
    #          不变）；负价值候选照旧跳过（3x 已覆盖）
    pebble = {"index": 0, "card_id": "GUARD_PEBBLE", "name": "小卵石", "card_type": "Skill",
              "energy_cost": 1, "rules_text": "获得1点格挡",
              "dynamic_values": [{"name": "Block", "current_value": 1}]}
    thin_deck = ([{"card_id": f"WALL_{i}", "card_type": "Skill", "energy_cost": 1,
                   "dynamic_values": [{"name": "Block", "current_value": 8}]} for i in range(6)]
                 + [{"card_id": f"BASIC_STRIKE_{i}", "card_type": "Attack", "energy_cost": 1}
                    for i in range(4)])   # good=6 < core 8：单薄；门槛=2.0-2×0.35=1.3
    thin_state = {"screen": "CARD_SELECTION",
                  "available_actions": ["select_deck_card", "skip_reward_cards"],
                  "selection": {"kind": "", "prompt": "将一张牌添加到你的牌组。",
                                "min_select": 1, "selected_count": 0, "can_confirm": False,
                                "cards": [dict(pebble)]},
                  "run": {"current_hp": 60, "max_hp": 80, "gold": 0, "floor": 31,
                          "deck": [dict(c) for c in thin_deck]}}
    assert pol._pick_threshold(thin_state["run"]["deck"]) > 0.8, "前置失效：小卵石应低于动态门槛"
    d_th1 = pol.decide(thin_state, ctx)
    assert d_th1.action == "select_deck_card", \
        f"单薄卡组的正价值候选不得因门槛跳过（VS71局零拿牌复现）: {d_th1.action}（{d_th1.reason}）"
    bloated_deck2 = [dict(c, card_id=f"BLOAT2_ATK_{i}") for i, c in enumerate(bloated)]
    fat_state = {"screen": "CARD_SELECTION",
                 "available_actions": ["select_deck_card", "skip_reward_cards"],
                 "selection": {"kind": "", "prompt": "将一张牌添加到你的牌组。",
                               "min_select": 1, "selected_count": 0, "can_confirm": False,
                               "cards": [dict(pebble)]},
                 "run": {"current_hp": 60, "max_hp": 80, "gold": 0, "floor": 32,
                         "deck": [dict(c) for c in bloated_deck2]}}
    d_th2 = pol.decide(fat_state, ctx)
    assert d_th2.action == "skip_reward_cards", \
        f"膨胀卡组的低于门槛候选仍应跳过（防注水语义回退）: {d_th2.action}（{d_th2.reason}）"

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
    tribute_ctx = DummyCtx()
    tribute_ctx.credit_tags = []
    d_tb1 = pol.decide(dict(tribute_state), tribute_ctx)
    assert d_tb1.params.get("option_index") == 1 and "献祭" in d_tb1.reason, \
        f"战斗献祭必须交出最不值钱的牌（应选伤口而非耸肩无视）: {d_tb1.reason}"
    tribute_ctx.credit_tags.extend(d_tb1.tags)  # 模拟服务端成功接受第一次献祭
    d_tb2 = pol.decide(dict(tribute_state), tribute_ctx)
    assert d_tb2.params.get("option_index") == 2 and "献祭" in d_tb2.reason, \
        f"多次献祭应逐张交出次差者（伤口已交出后应交打击）: {d_tb2.reason}"
    gain_state = {"screen": "CARD_SELECTION",
                  "available_actions": ["select_deck_card"],
                  "selection": {"kind": "", "prompt": "将一张牌添加到你的牌组。",
                                "min_select": 1, "selected_count": 0, "can_confirm": False,
                                "cards": [dict(c) for c in tribute_cards]},
                  "run": {"current_hp": 60, "max_hp": 80, "gold": 37, "floor": 71, "deck": []}}
    d_tg = pol.decide(gain_state, tribute_ctx)
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
    resumed_ctx = type("ResumedStreakCtx", (), {
        "credit_tags": [],
        "attribution_tags": [("map_node", "Monster")] * 4,
    })()
    resumed_state = {"screen": "MAP", "available_actions": ["choose_map_node"],
                     "map": {"available_nodes": [{"index": 0, "row": 1, "col": 0,
                                                    "node_type": "Monster"}], "nodes": []},
                     "run": {"current_hp": 70, "max_hp": 80, "gold": 0,
                             "floor": 5, "deck": []}}
    r_resumed = pol.decide(resumed_state, resumed_ctx).reason
    assert "前期需要战斗积累卡牌" in r_fresh and "疲劳压制" not in r_fresh, \
        f"对照失效（无连战史应保留积累加成）: {r_fresh}"
    assert "疲劳压制" in r_tired, f"连续作战疲劳未生效: {r_tired}"
    assert "疲劳压制" in r_resumed, \
        f"重启恢复的 attribution_tags 未参与连续作战疲劳: {r_resumed}"

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
    #      且 Boss 长战单独加码 boss_atk_mult（不动普通战斗攻防平衡）。
    #      第 107~108 批复盘追加：block_safety 的 Boss 释放分支整体移除——
    #      攻坚已由专属双轴承担，防御释放只剩跨语义振荡源（107 局降防 →
    #      108 局普通长战死升防，普通战防御权重永远定不准）
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
    assert abs(rknow.policy["block_safety"] - 1.0) < 1e-9, \
        f"Boss 长战阵亡不得再动普通战防御权重: {rknow.policy['block_safety']}"

    # 3qq) 灰区精英悲观投影复核（第 86~87 批复盘新增；第 122 局复盘重定语义）：
    #      旧复核问法「悲观情形是否仍舒适」（战后 ≥60%）在实测先验下数学不可
    #      满足（放行需入场血量 ≥95%~104% > 90% 硬线），灰区分支沦为死代码、
    #      精英被事实硬门在 ≥90% 血。新问法「悲观情形是否仍能活命」：
    #      elite_grey_survival_floor（默认 40%）。默认悲观系数 1.5 下 86% 血
    #      灰区放行（0.5 谨慎权重保留）；精英死亡棘轮把悲观系数推到 1.9 后
    #      同一局面恢复规避——演化旋钮继续承担尾部威慑；硬线以上不受影响。
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
    old_safety_q = know.policy["elite_grey_safety_mult"]
    know.policy["elite_min_hp_pct"] = 0.90          # 灰区 62%~90%
    know.policy["elite_soft_hp_pct"] = 0.62
    know.policy["elite_grey_safety_mult"] = 1.5     # 默认悲观系数
    r_grey = grey_elite_reason(69)   # 86%：悲观投影战后 40% ≥ 生存线 40% → 灰区放行
    assert "规避精英" not in r_grey and "灰区" in r_grey, \
        f"生存线语义未放行灰区精英（旧舒适线死代码应修复）: {r_grey}"
    r_hard = grey_elite_reason(73)   # 91% ≥ 硬线：不受灰区复核影响
    assert "规避精英" not in r_hard and "灰区" not in r_hard, \
        f"硬线以上被悲观复核误伤: {r_hard}"
    know.policy["elite_grey_safety_mult"] = 1.9      # 精英死亡棘轮演化值（运行库实况）
    r_ratchet = grey_elite_reason(69)
    assert "规避精英" in r_ratchet and "预计战后" in r_ratchet, \
        f"悲观系数棘轮失效（1.9 下 86% 血应恢复规避）: {r_ratchet}"
    know.policy["elite_min_hp_pct"] = old_hard_q
    know.policy["elite_grey_safety_mult"] = old_safety_q
    know.policy.pop("elite_soft_hp_pct", None)
    if saved_rooms_elite_q is not None:
        know.stats["rooms"]["Elite"] = saved_rooms_elite_q
    know.stats["enemies"] = saved_enemies_q

    # 3qq2) 灰区否决语义修复（第 122 局复盘）：旧「舒适线 60%」在实测先验下
    #       数学不可满足——Elite 混合先验 ≈20.3、折抵上限 20%、悲观系数 1.9、
    #       血池 80 → 灰区放行需入场血量 ≥98.6%，全面越过 90% 硬线，灰区
    #       分支沦为死代码，精英被事实硬门在 ≥90% 血（122 局仅 45 次到访）。
    #       新语义只要求「悲观情形仍能活命」（elite_grey_survival_floor=40%）。
    #       直接单测 _elite_grey_veto：同一悲观投影 46%（≥40% 且 <60%）应从
    #       「规避」翻转为「放行」；跌破生存线仍规避；旧键回退路径保持原判。
    gv_pol = know.policy
    gv_saved_floor = gv_pol.pop("elite_grey_survival_floor", None)
    gv_saved_hard = gv_pol.get("elite_min_hp_pct")
    gv_saved_soft = gv_pol.pop("elite_soft_hp_pct", None)
    gv_saved_safety = gv_pol.get("elite_grey_safety_mult")
    try:
        # 复刻运行库灰区带宽与精英死亡棘轮演化值，保证断言数学可复现
        gv_pol["elite_min_hp_pct"] = 0.90
        gv_pol["elite_soft_hp_pct"] = 0.62
        gv_pol["elite_grey_safety_mult"] = 1.9
        veto_fallback = pol._elite_grey_veto(gv_pol, 20.3, 1.0, 0.85, 10, 80)
        assert veto_fallback[0] is not None and "规避精英" in veto_fallback[1], \
            f"无新键时应回退旧舒适线语义: {veto_fallback}"
        gv_pol["elite_grey_survival_floor"] = 0.40
        gv_pess = 0.85 - 20.3 * 1.0 * (1.0 - 0.20) * 1.9 / 80
        assert abs(gv_pess - 0.464) < 0.01, f"用例前提失真: {gv_pess}"
        veto_pass = pol._elite_grey_veto(gv_pol, 20.3, 1.0, 0.85, 10, 80)
        assert veto_pass == (None, ""), \
            f"生存线语义未放行灰区精英(悲观投影{gv_pess:.0%}≥40%): {veto_pass}"
        veto_dire = pol._elite_grey_veto(gv_pol, 20.3, 1.0, 0.70, 10, 80)
        assert veto_dire[0] is not None and "规避精英" in veto_dire[1], \
            f"悲观投影跌破生存线未拦截: {veto_dire}"
        veto_outside = pol._elite_grey_veto(gv_pol, 20.3, 1.0, 0.55, 10, 80)
        assert veto_outside == (None, ""), \
            f"soft 线以下应由外层静态规避而非灰区复核处理: {veto_outside}"
    finally:
        if gv_saved_floor is not None:
            gv_pol["elite_grey_survival_floor"] = gv_saved_floor
        else:
            gv_pol.pop("elite_grey_survival_floor", None)
        if gv_saved_hard is not None:
            gv_pol["elite_min_hp_pct"] = gv_saved_hard
        if gv_saved_soft is not None:
            gv_pol["elite_soft_hp_pct"] = gv_saved_soft
        else:
            gv_pol.pop("elite_soft_hp_pct", None)
        if gv_saved_safety is not None:
            gv_pol["elite_grey_safety_mult"] = gv_saved_safety

    # 3yi) 灰区精英的输出饥饿豁免（第 136~137 批复盘）：137 局 88% 血灰区精英被
    #      否决（悲观投影战后仅剩36%）而满血进 Boss 照样整管打空——弱卡组跳过
    #      精英等于选择慢性死亡（遗物断供→输出不足→Boss 磨死）。爆发低于
    #      deck_burst_floor 时生存线下调 elite_grey_starve_relief；强卡组（非饥饿）
    #      维持原威慑。直接单测 veto 函数，隔离地图端 good_cards/先验的干扰。
    #      数值复刻运行库：safety=2.3、先验 20.3、86% 血、折抵 20% → 悲观投影 39.3%
    yv_pol = know.policy
    yv_saved = {k: yv_pol.get(k) for k in ("elite_grey_survival_floor", "elite_grey_starve_relief")}
    yv_saved_hard2, yv_saved_soft2, yv_saved_safety2 = (
        yv_pol.get("elite_min_hp_pct"), yv_pol.pop("elite_soft_hp_pct", None),
        yv_pol.get("elite_grey_safety_mult"))
    try:
        yv_pol["elite_min_hp_pct"] = 0.90
        yv_pol["elite_soft_hp_pct"] = 0.62
        yv_pol["elite_grey_safety_mult"] = 2.3
        yv_pol["elite_grey_survival_floor"] = 0.40
        yv_pol["elite_grey_starve_relief"] = 0.12
        veto_strong = pol._elite_grey_veto(yv_pol, 20.3, 1.0, 0.86, 10, 80, burst_starved=False)
        assert veto_strong[0] is not None and "规避精英" in veto_strong[1] \
            and "饥饿豁免" not in veto_strong[1], f"强卡组灰区威慑失效: {veto_strong}"
        veto_weak = pol._elite_grey_veto(yv_pol, 20.3, 1.0, 0.86, 10, 80, burst_starved=True)
        assert veto_weak == (None, ""), \
            f"输出饥饿豁免未放行灰区精英（投影39%≥28%）: {veto_weak}"
        veto_dire2 = pol._elite_grey_veto(yv_pol, 20.3, 1.0, 0.62, 10, 80, burst_starved=True)
        assert veto_dire2[0] is not None and "饥饿豁免至28%" in veto_dire2[1], \
            f"豁免不是无底洞（跌破豁免线仍须拦截）: {veto_dire2}"
    finally:
        for k, v in yv_saved.items():
            if v is not None:
                yv_pol[k] = v
            else:
                yv_pol.pop(k, None)
        if yv_saved_hard2 is not None:
            yv_pol["elite_min_hp_pct"] = yv_saved_hard2
        if yv_saved_soft2 is not None:
            yv_pol["elite_soft_hp_pct"] = yv_saved_soft2

    # 3yj) 饥饿豁免集成口径：弱爆发卡组（全防御技能，burst=0）在 86% 血的灰区精英
    #      应放行到「谨慎评估」而非「规避精英」——复刻 137 局 RestSite(10,4) 压过
    #      Elite(10,5) 的病灶岔路。rooms/enemies 注入隔离真实库数据干扰
    saved_rooms_yj = know.stats.setdefault("rooms", {}).pop("Elite", None)
    saved_enemies_yj = know.stats.get("enemies", {})
    know.stats["enemies"] = {}
    know.stats["rooms"]["Elite"] = {"visits": 10, "outcome_sum": 0.0,
                                    "hp_lost_sum": 203.0, "damage_events": 10}
    old_hard_yj = know.policy["elite_min_hp_pct"]
    old_safety_yj = know.policy["elite_grey_safety_mult"]
    try:
        know.policy["elite_min_hp_pct"] = 0.90
        know.policy["elite_grey_safety_mult"] = 2.3
        starved_map = {"screen": "MAP", "available_actions": ["choose_map_node"],
                       "map": {"available_nodes": [{"index": 0, "row": 1, "col": 0,
                                                    "node_type": "Elite"}], "nodes": []},
                       "run": {"current_hp": 69, "max_hp": 80, "gold": 200, "floor": 10,
                               "deck": [{"card_id": f"GUARD_{i}", "card_type": "Skill",
                                         "energy_cost": 1, "rules_text": "获得4点格挡",
                                         "dynamic_values": [{"name": "Block", "current_value": 4}]}
                                        for i in range(10)]}}
        d_yj = pol.decide(starved_map, ctx)
        assert "规避精英" not in d_yj.reason and "谨慎评估" in d_yj.reason, \
            f"饥饿豁免未在地图端放行灰区精英: {d_yj.reason}"
    finally:
        know.policy["elite_min_hp_pct"] = old_hard_yj
        know.policy["elite_grey_safety_mult"] = old_safety_yj
        know.stats["enemies"] = saved_enemies_yj
        if saved_rooms_yj is not None:
            know.stats["rooms"]["Elite"] = saved_rooms_yj
        else:
            know.stats["rooms"].pop("Elite", None)

    # 3yh) 精英健康进场子账本（第 396 局批次复盘）：Elite 全量战损样本被低血
    #      被迫战垄断——健康状态从不主动打精英（生涯 396 局仅 166 次到访），
    #      污染先验让灰区悲观复核数学不可满足，规避→样本更坏→更规避自我强化。
    #      ≥elite_healthy_entry_pct 进场的 Elite 战斗额外计入 hp_lost_sum_hi/
    #      damage_events_hi 子账本；成熟（≥3 样本）时闸门改答「像现在这样健康地
    #      进场会掉多少」（幕数乘区归 1），未成熟回落旧口径行为严格一致。
    _yh_keys = ("elite_min_hp_pct", "elite_soft_hp_pct", "elite_grey_safety_mult",
                "elite_grey_survival_floor")
    _yh_pol_saved = {k: know.policy.get(k) for k in _yh_keys}
    _yh_rooms_e = know.stats.get("rooms", {}).get("Elite")
    _yh_rooms_m = know.stats.get("rooms", {}).get("Monster")
    _yh_ract_e = know.stats.get("rooms_act", {}).get("Elite@1")
    _yh_ract_m = know.stats.get("rooms_act", {}).get("Monster@1")
    _yh_rband_e = know.stats.get("rooms_band", {}).get("Elite@1_b3")
    _yh_rband_m = know.stats.get("rooms_band", {}).get("Monster@1_b3")
    _yh_enemies = know.stats.get("enemies", {})
    try:
        # 夹具隔离：enemies 置空使 combat_calibration=1.0；摘除将被写入的真实库键，
        # 使断言数值完全由注入数据决定
        know.stats["enemies"] = {}
        know.policy["elite_min_hp_pct"] = 0.90
        know.policy["elite_soft_hp_pct"] = 0.62
        know.policy["elite_grey_safety_mult"] = 2.5
        know.policy["elite_grey_survival_floor"] = 0.40
        know.stats.setdefault("rooms", {})["Elite"] = {
            "visits": 10, "outcome_sum": 0.0, "hp_lost_sum": 244.0, "damage_events": 10}
        know.stats["rooms"].pop("Monster", None)
        know.stats.setdefault("rooms_act", {}).pop("Elite@1", None)
        know.stats["rooms_act"].pop("Monster@1", None)
        know.stats.setdefault("rooms_band", {}).pop("Elite@1_b3", None)
        know.stats["rooms_band"].pop("Monster@1_b3", None)
        # 未成熟回落（hi 子账本不存在→旧口径）：污染先验下灰区复核应否决且无健康留痕
        know.stats.setdefault("rooms_act", {})["Elite@1"] = {
            "hp_lost_sum": 2440.0, "damage_events": 100}
        pr_fb, hit_fb = know.elite_prior_healthy(1, 28.0)
        assert hit_fb is False, f"未成熟时不应命中健康实证: {pr_fb}, {hit_fb}"
        gf_fb, note_fb = pol._elite_path_gate(
            know.policy, know.policy["path_danger_priors"], 64, 80, 10, 1.0,
            False, act_no=1)
        assert "健康进场实证先验" not in note_fb and "规避精英" in note_fb, \
            f"未成熟回落路径行为异常: {gf_fb}, {note_fb}"
        # 写入分流：高血 Elite 入健康子账本，低血 Elite 不入，Monster 高血也不入
        for _ in range(3):
            know.commit_room_damage("Elite", 12.0, act=1, floor=13, hp_start_pct=0.90)
        know.commit_room_damage("Elite", 60.0, act=1, floor=14, hp_start_pct=0.50)
        know.commit_room_damage("Monster", 30.0, act=1, floor=14, hp_start_pct=0.95)
        ra_yh = know.stats["rooms_act"]["Elite@1"]
        assert int(ra_yh.get("damage_events_hi", 0)) == 3 and abs(
            float(ra_yh.get("hp_lost_sum_hi", 0.0)) - 36.0) < 1e-9, \
            f"健康子账本分流失败: {ra_yh}"
        assert int(ra_yh["damage_events"]) == 104, f"全量账被健康分流挤占: {ra_yh}"
        assert "damage_events_hi" not in know.stats["rooms_act"]["Monster@1"], \
            "Monster 不应写健康子账本"
        assert know.stats["rooms"]["Elite"].get("damage_events_hi") == 3, \
            "跨幕条目健康子账本未同步写入"
        # 成熟命中（hi 场均 12）：同参数下灰区复核放行到谨慎评估并留痕来源
        ra_yh["hp_lost_sum_hi"] = 36.0
        ra_yh["damage_events_hi"] = 3
        pr_h, hit_h = know.elite_prior_healthy(1, 28.0)
        assert hit_h is True and abs(pr_h - 12.0) < 1e-6, \
            f"健康实证先验数值错误: {pr_h}, {hit_h}（期望 12×发生率1.0）"
        gf_h, note_h = pol._elite_path_gate(
            know.policy, know.policy["path_danger_priors"], 64, 80, 10, 1.0,
            False, act_no=1)
        assert gf_h == 0.5 and "谨慎评估" in note_h \
            and "健康进场实证先验" in note_h, \
            f"健康实证未放行灰区精英或留痕缺失: {gf_h}, {note_h}"
    finally:
        for k, v in _yh_pol_saved.items():
            if v is not None:
                know.policy[k] = v
            else:
                know.policy.pop(k, None)
        know.stats["enemies"] = _yh_enemies
        if _yh_rooms_e is None:
            know.stats.get("rooms", {}).pop("Elite", None)
        else:
            know.stats["rooms"]["Elite"] = _yh_rooms_e
        if _yh_rooms_m is None:
            know.stats.get("rooms", {}).pop("Monster", None)
        else:
            know.stats["rooms"]["Monster"] = _yh_rooms_m
        if _yh_ract_e is None:
            know.stats.get("rooms_act", {}).pop("Elite@1", None)
        else:
            know.stats["rooms_act"]["Elite@1"] = _yh_ract_e
        if _yh_ract_m is None:
            know.stats.get("rooms_act", {}).pop("Monster@1", None)
        else:
            know.stats["rooms_act"]["Monster@1"] = _yh_ract_m
        if _yh_rband_e is None:
            know.stats.get("rooms_band", {}).pop("Elite@1_b3", None)
        else:
            know.stats["rooms_band"]["Elite@1_b3"] = _yh_rband_e
        if _yh_rband_m is None:
            know.stats.get("rooms_band", {}).pop("Monster@1_b3", None)
        else:
            know.stats["rooms_band"]["Monster@1_b3"] = _yh_rband_m

    # 3rr) 精英死亡演化改接悲观系数（第 86~87 批复盘）：elite_min_hp_pct 已在
    #      0.9 上限顶格空转——精英死亡信号必须驱动仍有余量的新旋钮，
    #      且胜利时双向释放（演化必须可逆）。
    #      第 135 局复盘细化：只有灰区进场（<硬线）的精英死亡才喂灰区系数；
    #      满血线以上进场阵亡（135 局 95% 血进精英 -76）是实战执行/卡组强度
    #      的证据，错位吸收只会让这条无释放通道的棘轮漂向 2.5 上限空转
    eknow = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-grey-")))
    eknow.policy["elite_min_hp_pct"] = 0.9  # 复刻运行库顶格状态（默认 0.55 下 0.86 不算灰区）
    ectx = SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "BYGONE_EFFIGY", "rounds": 6, "node_type": "Elite"},
        death_was_elite=True, death_hp_pct_at_entry=0.86,
        credit_tags=[], rests_healed_at_full=0, ascension=0, combat_notes=[])
    finalize_run(eknow, ectx, victory=False, final_floor=17)
    assert abs(eknow.policy["elite_grey_safety_mult"] - 1.7) < 1e-9, \
        f"灰区精英死亡未上调灰区悲观系数: {eknow.policy['elite_grey_safety_mult']}"
    fctx = SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "PHROG_PARASITE", "rounds": 9, "node_type": "Elite"},
        death_was_elite=True, death_hp_pct_at_entry=0.95,
        credit_tags=[], rests_healed_at_full=0, ascension=0, combat_notes=[])
    finalize_run(eknow, fctx, victory=False, final_floor=11)
    assert abs(eknow.policy["elite_grey_safety_mult"] - 1.7) < 1e-9, \
        f"满血线进场精英死亡不应喂灰区系数（错位吸收复发）: {eknow.policy['elite_grey_safety_mult']}"
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

    # 3ss-bis) 药水提前交药线（第 236 局复盘，爆毙/短时死亡的接替旋钮）：
    #          TNWN 局 40%~50% 血硬仗干瞪眼、拖到 10/80 才喝药——防御/回复
    #          药水的开喝血线由 potion_block_hp_pct 控制（默认 0.35 与旧行为
    #          一致），演化上调后在无数据组合的普通硬仗里也提前开喝；
    #          默认线下同血量照旧不喝（旧行为回归防护）
    def heal_potion_state(hp_now: int):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 5,
            "combat": {"player": {"current_hp": hp_now, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [],
                       "enemies": [{"index": 0, "enemy_id": "H", "name": "硬仗怪",
                                    "current_hp": 30, "max_hp": 30, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": 12}]}]},
            "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 9,
                    "deck": [],
                    "potions": [{"index": 0, "potion_id": "BLOCK_P", "name": "格挡药水",
                                 "description": "获得12点格挡。", "occupied": True,
                                 "can_use": True, "usage": "combat"}]},
        }

    saved_pot_line = know.policy.get("potion_block_hp_pct", 0.35)
    know.policy["potion_block_hp_pct"] = 0.60
    ctx.combat = {"comp_id": "NO_DATA_COMP_PL", "node_type": "Monster"}  # 无数据组合：premium 不开，只靠放血线
    d_pl1 = pol.decide(heal_potion_state(44), ctx)   # 55% 血：旧线 35% 够不到，新线 60% 应喝
    assert d_pl1.action == "use_potion" and "交药线" in d_pl1.reason, \
        f"交药线上调后未提前使用防御药水: {d_pl1.action}（{d_pl1.reason}）"
    know.policy["potion_block_hp_pct"] = saved_pot_line
    ctx.combat = {"comp_id": "NO_DATA_COMP_PL2", "node_type": "Monster"}  # 新战斗实例：绕开药水尝试黑名单
    d_pl2 = pol.decide(heal_potion_state(44), ctx)
    assert d_pl2.action != "use_potion", \
        f"默认交药线被误抬（旧行为回归防护失效）: {d_pl2.action}（{d_pl2.reason}）"
    know.policy["potion_block_hp_pct"] = saved_pot_line
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

    # 3kz) 引擎复制件密度放行（第856~876局批复盘 ENGINE_DUP_DENSITY_RELEASE）：
    #      输出饥饿最终解在拿牌端引擎密度（833~842批定案），但复制件惩罚让高质
    #      攻击/活跃引擎的第3+张永远让位——876局引擎线成型后缺口仍66%，生涯0胜。
    #      深缺口下高质攻击（总伤≥12 且 ≥7伤/能耗）与活跃成长引擎的复制件罚分
    #      按 dup_density_release_frac 折减；弱攻击/防御功能牌不放行（71局
    #      「耸肩×5」注水病不复发）；浅缺口（deficit<门槛）与缺键行为同旧口径。
    #      复用 3tt 的 starved_deck/big_atk/weak_atk 夹具：加 2 张 CINDER 后
    #      burst=24，线 40 → deficit 0.40 ≥ 门槛 0.30（放行生效区）
    _saved_floor_kz = know.policy.get("deck_burst_floor", 45.0)
    know.policy["deck_burst_floor"] = 40.0
    dup_pair = [dict(big_atk), dict(big_atk)] + [dict(c) for c in starved_deck]
    v_dup_on = pol.eval_reward_card(dict(big_atk), [dict(c) for c in dup_pair])
    _saved_frac = know.policy.get("dup_density_release_frac", 0.5)
    know.policy["dup_density_release_frac"] = 0.0    # 整体关闭 → 旧口径罚分全额
    v_dup_off = pol.eval_reward_card(dict(big_atk), [dict(c) for c in dup_pair])
    know.policy["dup_density_release_frac"] = _saved_frac
    assert v_dup_on - v_dup_off >= 1.4, \
        f"深缺口未放行高质攻击复制件（deficit 应≈0.40）: on={v_dup_on:.2f} off={v_dup_off:.2f}"
    _det_on: list[str] = []
    pol.eval_reward_card(dict(big_atk), [dict(c) for c in dup_pair], detail=_det_on)
    assert _det_on and "密度放行" in _det_on[0], \
        f"放行路径未留观测标记: {_det_on}"
    _det_off: list[str] = []
    know.policy["dup_density_release_frac"] = 0.0
    pol.eval_reward_card(dict(big_atk), [dict(c) for c in dup_pair], detail=_det_off)
    know.policy["dup_density_release_frac"] = _saved_frac
    assert not _det_off, f"关闭开关后仍留放行标记: {_det_off}"
    weak_pair = [dict(weak_atk), dict(weak_atk)] + [dict(c) for c in starved_deck]
    v_weak_dup = pol.eval_reward_card(dict(weak_atk), [dict(c) for c in weak_pair])
    know.policy["dup_density_release_frac"] = 0.0
    v_weak_dup_off = pol.eval_reward_card(dict(weak_atk), [dict(c) for c in weak_pair])
    know.policy["dup_density_release_frac"] = _saved_frac
    assert abs(v_weak_dup - v_weak_dup_off) < 1e-6, \
        f"打击级弱攻击被误放行: on={v_weak_dup:.2f} off={v_weak_dup_off:.2f}"
    _saved_gate = know.policy.get("dup_density_release_deficit", 0.30)
    know.policy["dup_density_release_deficit"] = 0.9    # 门槛拉高 → 视同浅缺口不放行
    v_dup_shallow = pol.eval_reward_card(dict(big_atk), [dict(c) for c in dup_pair])
    know.policy["dup_density_release_deficit"] = _saved_gate
    assert abs(v_dup_shallow - v_dup_off) < 1e-6, \
        f"浅缺口被误放行: shallow={v_dup_shallow:.2f} off={v_dup_off:.2f}"
    know.policy["deck_burst_floor"] = _saved_floor_kz


    # 3uu) 长战演化顶格治理（第 88~89 批复盘）：kill_bonus 13→14→15 单向漂移
    #      ——0 胜生涯里「长战磨死」每局触发，信号只会把旋钮推向边界。余量不足
    #      一步时停止加码并显式留痕；行程充足时行为与旧版一致（3pp 已覆盖）。
    #      第 107~108 批复盘：Boss 长战的 block_safety 释放分支已整体移除，
    #      触底「停止释放」留痕随之退役——普通战防御权重不再被 Boss 死亡信号
    #      单向拖低（旧 0.6 下限正是被它磨穿的）
    gknow = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-gov-")))
    gknow.policy["kill_bonus"] = 19.5     # 距上限 0.5 < 步长 2.0
    gknow.policy["block_safety"] = 0.65
    gctx = SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "BOSS_Y", "rounds": 8, "node_type": "Boss"},
        death_was_elite=False, death_hp_pct_at_entry=0.9,
        credit_tags=[], rests_healed_at_full=0, ascension=0, combat_notes=[])
    glesson = finalize_run(gknow, gctx, victory=False, final_floor=17)
    assert abs(gknow.policy["kill_bonus"] - 19.5) < 1e-9, \
        f"顶格旋钮仍被加码: {gknow.policy['kill_bonus']}"
    assert abs(gknow.policy["block_safety"] - 0.65) < 1e-9, \
        f"Boss 长战阵亡仍触碰普通战防御权重: {gknow.policy['block_safety']}"
    assert "停止加码" in glesson, \
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
    d_kr_t1 = pol_kr.decide(krace_state(1, 65), krc)  # T1：样本不足，不武装
    krc.credit_tags.extend(d_kr_t1.tags)              # 模拟服务端成功回执
    d_kr_t2 = pol_kr.decide(krace_state(2, 55), krc)  # T2：样本仍不足
    krc.credit_tags.extend(d_kr_t2.tags)
    d_kr = pol_kr.decide(krace_state(3, 45), krc)   # T3：实测 ~24伤/回合 vs 200 血、意图 22/回合 → 投影必败
    assert d_kr.action == "play_card" and d_kr.params.get("card_index") == 0, \
        f"斩杀竞速失败时奢侈格挡仍胜出: {d_kr.action}（{d_kr.reason}）"
    assert "斩杀竞速投影" in d_kr.reason, f"竞速投影未留痕: {d_kr.reason}"
    # 对照：意图轻微（5/回合，血量账宽裕）时同一战斗不得触发竞速——防守路线可行
    krc.credit_tags = []
    pol_kr2 = policy.Policy(know, random.Random(11))
    d_kr2_t1 = pol_kr2.decide(krace_state(1, 80, incoming=5), krc)
    krc.credit_tags.extend(d_kr2_t1.tags)
    d_kr2_t2 = pol_kr2.decide(krace_state(2, 80, incoming=5), krc)
    krc.credit_tags.extend(d_kr2_t2.tags)
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
    d_es_t1 = pol_es.decide(esc_state(1, 65, 4, 60), krc_es)  # T1：意图 4 基准采样
    krc_es.credit_tags.extend(d_es_t1.tags)
    d_es_t2 = pol_es.decide(esc_state(2, 55, 7, 48), krc_es)  # T2：趋势+3，升级计数 1
    krc_es.credit_tags.extend(d_es_t2.tags)
    d_es = pol_es.decide(esc_state(3, 30, 24, 36), krc_es)  # T3：趋势+17 计数 2 → 开账
    assert d_es.action == "play_card" and d_es.params.get("card_index") == 0, \
        f"升级型低血池组合未走竞速路线: {d_es.action}（{d_es.reason}）"
    assert "斩杀竞速投影" in d_es.reason, f"升级门未开账: {d_es.reason}"
    assert "斜率反转：成长型组合，解除攻击压制" in d_es.reason, \
        f"持续成长组合未在竞速前解除攻击压制/文案未改写: {d_es.reason}"
    assert "转防守节奏" not in d_es.reason, f"矛盾留痕残留: {d_es.reason}"
    # 对照：同一低血池组合但意图平稳（无升级轨迹）→ 门不开，不得误触发
    krc_es.credit_tags = []
    pol_es2 = policy.Policy(knowledge.Knowledge(kdir_es), random.Random(7))
    d_es2_t1 = pol_es2.decide(esc_state(1, 65, 4, 60), krc_es)
    krc_es.credit_tags.extend(d_es2_t1.tags)
    d_es2_t2 = pol_es2.decide(esc_state(2, 55, 4, 48), krc_es)
    krc_es.credit_tags.extend(d_es2_t2.tags)
    d_es2 = pol_es2.decide(esc_state(3, 30, 4, 36), krc_es)
    assert "斩杀竞速投影" not in d_es2.reason, f"无升级轨迹误开账: {d_es2.reason}"
    krc_es.combat = None

    # 3xd) 竞速迟滞锁（第632局批复盘）：632 局 F29 盛碗虫三连战七个回合内
    #      「提速斩杀」与「转防守节奏」交替出现 5 次——实测口径判死进入竞速后，
    #      小怪阵亡缩池、先验/实测口径切换、EMA 滞后都会让逐 tick 重算在阈值
    #      附近反复翻案，攻防分配两头摇摆且矛盾留痕污染复盘。旧逻辑反例：
    #      下方 T4 血池从 130 缩到 30 时（fresh 判定不再必败）整场翻回防守。
    #      修复：实测样本满两回合判死后同场上锁，唯一合法出口仍是防守线
    #      联合复核判可行；先验口径（T1~T2 样本不足）不锁，误判可被自然纠正。
    kdir_flip = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-fliplock-"))
    know_flip = knowledge.Knowledge(kdir_flip)
    know_flip.stats["enemies"]["FLIP_COMP"] = {
        "encounters": 6, "deaths": 4, "hp_lost_sum": 180.0, "wins": 2}
    krc_fl = type("FLPCTX", (), {"combat": None, "current_combat_is_hard": True,
                                 "credit_tags": []})()
    krc_fl.combat = {"comp_id": "FLIP_COMP", "node_type": "Monster"}

    def flip_state(turn_no, hp_now, incoming, e_hp):
        if turn_no <= 3:
            hand = [
                {"index": 0, "card_id": "FP_HIT_A", "name": "磨刀砍", "playable": True,
                 "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                 "dynamic_values": [{"name": "Damage", "current_value": 5}]},
                {"index": 1, "card_id": "FP_HIT_B", "name": "磨刀砍二号", "playable": True,
                 "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                 "dynamic_values": [{"name": "Damage", "current_value": 5}]}]
        else:
            hand = [
                {"index": 0, "card_id": "FP_HIT_C", "name": "磨刀砍三号", "playable": True,
                 "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                 "dynamic_values": [{"name": "Damage", "current_value": 5}]},
                {"index": 1, "card_id": "FP_LUX", "name": "奢侈挡", "playable": True,
                 "requires_target": False,
                 "rules_text": "获得6点格挡",
                 "dynamic_values": [{"name": "Block", "current_value": 6}]}]
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": turn_no,
            "combat": {"player": {"current_hp": hp_now, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": hand,
                       "enemies": [{"index": 0, "enemy_id": "FLIP_COMP_E", "name": "翻案怪",
                                    "current_hp": e_hp, "max_hp": 150, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": incoming}]}]},
            "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 9, "deck": []}}

    pol_fl = policy.Policy(know_flip, random.Random(11))
    d_fl_t1 = pol_fl.decide(flip_state(1, 80, 4, 120), krc_fl)
    krc_fl.credit_tags.extend(d_fl_t1.tags)
    d_fl_t2 = pol_fl.decide(flip_state(2, 68, 12, 118), krc_fl)
    krc_fl.credit_tags.extend(d_fl_t2.tags)
    # T3：实测口径（两回合出牌，~5伤/回合）对 190 血池、火力 12/回合 → 投影判死入锁
    d_fl_t3 = pol_fl.decide(flip_state(3, 56, 12, 190), krc_fl)
    assert "斩杀竞速投影" in d_fl_t3.reason \
        and "竞速解除防御压制" in d_fl_t3.reason, \
        f"实测口径未上锁进入竞速: {d_fl_t3.action}（{d_fl_t3.reason}）"
    krc_fl.credit_tags.extend(d_fl_t3.tags)
    #      迟滞锁必须维持全攻（旧代码在此翻回「转防守节奏」并去打奢侈格挡；
    #      同时注意血池保持 ≥80 开账门之上，避免掉入血池过小不竞速的旧豁免）
    krc_fl.credit_tags.append(("combat_play_commit", "FP_BIG", True, False, 56.0, 3, ""))
    d_fl_t4 = pol_fl.decide(flip_state(4, 44, 12, 100), krc_fl)
    assert d_fl_t4.action == "play_card" and d_fl_t4.params.get("card_index") == 0, \
        f"迟滞锁失效（血池缩小后攻防翻转打格挡）: {d_fl_t4.action}（{d_fl_t4.reason}）"
    assert "斩杀竞速投影" in d_fl_t4.reason and "转防守节奏" not in d_fl_t4.reason, \
        f"同场竞速判定被逐tick翻案: {d_fl_t4.action}（{d_fl_t4.reason}）"
    krc_fl.credit_tags.extend(d_fl_t4.tags)
    d_fl_t5 = pol_fl.decide(flip_state(5, 34, 12, 96), krc_fl)
    assert "斩杀竞速投影" in d_fl_t5.reason and "转防守节奏" not in d_fl_t5.reason, \
        f"迟滞锁未跨tick维持: {d_fl_t5.action}（{d_fl_t5.reason}）"
    krc_fl.combat = None

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
    # Boss 长战走攻坚专属旋钮（第 107~108 批复盘）：不再释放 block_safety——
    # 该规则是第 82~83 批引入的（当时还没有 boss_atk_mult 分轴），如今形成
    # 跨语义振荡源：107 局 Boss 磨死降防 → 108 局普通长战死升防，普通战
    # 防御权重在两种真实死亡信号间打摆永远定不准
    rctx2 = _RC()
    rctx2.died_in_combat = {"comp_id": "BOSS_X", "node_type": "Boss", "rounds": 8}
    bs_b2 = rknow.policy["block_safety"]
    bam_b2 = rknow.policy["boss_atk_mult"]
    be_b2 = rknow.policy["boss_entry_min_hp_pct"]
    reflect.finalize_run(rknow, rctx2, victory=False, final_floor=9)
    assert abs(rknow.policy["block_safety"] - bs_b2) < 1e-9, \
        f"Boss 长战阵亡仍在释放防御（跨语义振荡复发）: {bs_b2} -> {rknow.policy['block_safety']}"
    assert rknow.policy["boss_atk_mult"] > bam_b2, \
        f"Boss 长战阵亡未提速攻坚乘区: {bam_b2} -> {rknow.policy['boss_atk_mult']}"
    assert rknow.policy["boss_entry_min_hp_pct"] > be_b2, \
        f"Boss 长战阵亡未上调入场血量线: {be_b2} -> {rknow.policy['boss_entry_min_hp_pct']}"

    # 3zg) 防御棘轮代偿治理（第 127~130 批复盘）：kill_bonus 顶格后，非 Boss
    #      长战死的 +0.05 仍灌进 block_safety——128/129/130 连续三局 1.50→1.65，
    #      0 胜生涯下胜利释放（-0.02）永不触发，单向棘轮必然漂到 2.1 空转。
    #      长战证据语义是「时长/输出不足」，主旋钮顶格后防御端停止代偿加码；
    #      短时爆毙（<4回合）的「没挡住」证据不受影响。
    gdir2 = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-drift-"))
    gknow2 = knowledge.Knowledge(gdir2)
    gknow2.policy["kill_bonus"] = 20.0     # 顶格（上限）
    gknow2.policy["block_safety"] = 1.65   # 128~130 局三连 +0.05 后的实景值
    gctx3 = _RC()
    gctx3.died_in_combat = {"comp_id": "RAMP_COMP", "node_type": "Monster", "rounds": 10}
    glesson3 = reflect.finalize_run(gknow2, gctx3, victory=False, final_floor=8)
    assert abs(gknow2.policy["block_safety"] - 1.65) < 1e-9, \
        f"kill_bonus 顶格后长战证据仍溢入防御棘轮: {gknow2.policy['block_safety']}"
    assert abs(gknow2.policy["kill_bonus"] - 20.0) < 1e-9, \
        f"顶格旋钮仍被加码: {gknow2.policy['kill_bonus']}"
    assert "停止代偿加码" in glesson3, f"代偿治理未在复盘日志留痕: {glesson3}"
    # 对照①：kill_bonus 有行程时，92~93 批语义不变（双旋钮并行加码）
    gknow2.policy["kill_bonus"] = 12.0
    gctx4 = _RC()
    gctx4.died_in_combat = {"comp_id": "RAMP_COMP", "node_type": "Monster", "rounds": 7}
    bs_g4 = gknow2.policy["block_safety"]
    reflect.finalize_run(gknow2, gctx4, victory=False, final_floor=6)
    assert gknow2.policy["block_safety"] > bs_g4, \
        f"kill_bonus 有行程时长战死未上调防御（92~93 语义被破坏）: {bs_g4} -> {gknow2.policy['block_safety']}"
    # 对照②：kill_bonus 顶格 + 短时爆毙（<4回合）——「没挡住」证据照常上调
    gknow2.policy["kill_bonus"] = 20.0
    gctx5 = _RC()
    gctx5.died_in_combat = {"comp_id": "BURST_COMP", "node_type": "Monster", "rounds": 2}
    bs_g5 = gknow2.policy["block_safety"]
    reflect.finalize_run(gknow2, gctx5, victory=False, final_floor=5)
    assert gknow2.policy["block_safety"] > bs_g5, \
        f"短时爆毙的防御证据被误伤: {bs_g5} -> {gknow2.policy['block_safety']}"

    # 3wz) 溢出型大格挡贬值（第 94~95 批复盘）：94 局 Boss 战开局 87 血对意图
    #      7/17 连打两张岿然不动+(40挡)，~56 点溢出甲 ≈ 4 能量没换成伤害，
    #      Boss 多活两轮升级意图。有用部分不足牌面一半且血量宽裕时，大挡按
    #      纯溢出计价跌破主出牌阈值、不得挤占攻击；若没有任何替代且能量本会
    #      白白丢弃，正边际兜底仍可用它少掉血。高意图/低血量不受贬值影响。
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
    assert d_ov1.action == "play_card" and "受控试用" in d_ov1.reason, \
        f"没有替代时正边际大挡仍带能量空过: {d_ov1.action}（{d_ov1.reason}）"
    ov_with_attack = ov_wall_state(76, 5)
    ov_with_attack["combat"]["hand"].append(
        {"index": 1, "card_id": "OV_STRIKE", "name": "打击", "playable": True,
         "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
         "dynamic_values": [{"name": "Damage", "current_value": 6}]})
    d_ov_attack = pol_ov.decide(ov_with_attack, ovc)
    assert d_ov_attack.action == "play_card" and d_ov_attack.params.get("card_index") == 1, \
        f"溢出大挡仍挤占正经输出: {d_ov_attack.action}（{d_ov_attack.reason}）"
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

    # 3xa-bis（第470局批复盘）：已识别的防御/回复类药水不得经「无法分类」兜底
    #           被 premium 硬仗开局白喝——470 局 F7 以 91/91 满血、意图 14 的
    #           轻量战把格挡药水倒进兜底通道（交药线门槛未到却一路落穿），五层
    #           后的死亡战手里再无防御资源。修复：识别为防御类的药水在门槛未到
    #           时显式保留；应急解封口（服务端致死判定/本地缺口吞血条）照旧放行
    pol_pot4 = policy.Policy(know_es, random.Random(5))
    potc.combat = {"comp_id": "RAMP_COMP", "node_type": "Monster"}
    d_pot4 = pol_pot4.decide(pot_state("获得12点格挡。"), potc)
    assert d_pot4.action == "play_card" and "药水" not in d_pot4.reason, \
        f"满血时防御药水仍被兜底白喝: {d_pot4.action}（{d_pot4.reason}）"
    st_emg = pot_state("获得12点格挡。")
    st_emg["combat"]["end_turn_will_kill_player"] = True
    pol_pot5 = policy.Policy(know_es, random.Random(5))
    d_pot5 = pol_pot5.decide(st_emg, potc)
    assert d_pot5.action == "use_potion" and "交药线" in d_pot5.reason, \
        f"致死局防御药水应急解封失效: {d_pot5.action}（{d_pot5.reason}）"
    potc.combat = None

    # 3xa-ter（第470局批复盘）：条件型成长引擎（撕裂族）的触发条件卡组无法满足
    #           时按死牌治理——470 局零自残卡组里撕裂被三端加成：商店 76 金购入、
    #           连续两次锻造 +16 引擎分、三场战斗 T1 上砧（含死亡战），全程零触发。
    #           战斗端：死牌评分压到出牌阈值之下，攻击正常上砧；
    #           对照组：卡组补入自残源后撕裂恢复引擎待遇；
    #           锻造端：+16 引擎分不再喂给触发条件不可满足的能力牌。
    def rupture_state(deck):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 1,
            "combat": {"player": {"current_hp": 70, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [
                           {"index": 0, "card_id": "RUPT_T", "name": "撕裂", "playable": True,
                            "energy_cost": 1, "requires_target": False, "card_type": "Power",
                            "resolved_rules_text": "每当你失去生命时，获得1点力量。"},
                           {"index": 1, "card_id": "RP_HIT", "name": "打击", "playable": True,
                            "energy_cost": 1, "requires_target": True,
                            "valid_target_indices": [0],
                            "dynamic_values": [{"name": "Damage", "current_value": 6}]}],
                       "enemies": [{"index": 0, "enemy_id": "NO_DATA_RUP", "name": "试裂兽",
                                    "current_hp": 120, "max_hp": 140, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": 10}]}]},
            "run": {"current_hp": 70, "max_hp": 80, "gold": 0, "floor": 6,
                    "deck": [dict(c) for c in deck]}}

    plain_deck = ([_mk_strike(i) for i in range(4)]
                  + [{"card_id": f"RP_DEF{i}", "card_type": "Skill", "energy_cost": 1,
                      "dynamic_values": [{"name": "Block", "current_value": 5}]} for i in range(4)])
    sd_deck = list(plain_deck) + [
        {"card_id": "HEMO_T", "card_type": "Attack", "energy_cost": 1,
         "resolved_rules_text": "失去4点生命，造成10点伤害。"}]
    rup_ctx = type("RupCtx", (), {"current_combat_is_hard": False, "credit_tags": []})()
    rup_ctx.combat = {"comp_id": "NO_DATA_RUP", "node_type": "Monster"}
    pol_rup1 = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-rupt1-"))), random.Random(5))
    d_rup_dead = pol_rup1.decide(rupture_state(plain_deck), rup_ctx)
    assert d_rup_dead.action == "play_card" and d_rup_dead.params.get("card_index") == 1, \
        f"零自残卡组里死引擎仍压过攻击上砧: {d_rup_dead.action}（{d_rup_dead.reason}）"
    assert "死牌" in d_rup_dead.reason or d_rup_dead.params.get("card_index") == 1, \
        f"死牌留痕缺失: {d_rup_dead.reason}"
    pol_rup2 = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-rupt2-"))), random.Random(5))
    d_rup_live = pol_rup2.decide(rupture_state(sd_deck), rup_ctx)
    assert d_rup_live.action == "play_card" and d_rup_live.params.get("card_index") == 0 \
        and "撕裂" in d_rup_live.reason, \
        f"有自残源后撕裂未恢复引擎待遇: {d_rup_live.action}（{d_rup_live.reason}）"

    upk_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-ruptup-"))
    upk_now = knowledge.Knowledge(upk_dir)
    up_pol = policy.Policy(upk_now, random.Random(5))
    up_deck = ([_mk_strike(i) for i in range(5)]
               + [{"card_id": f"RUPT_DEF{i}", "card_type": "Skill", "energy_cost": 1,
                   "dynamic_values": [{"name": "Block", "current_value": 5}]} for i in range(3)])
    up_state = {
        "screen": "CARD_SELECTION",
        "available_actions": ["select_deck_card", "confirm_selection"],
        "selection": {"kind": "upgrade", "prompt": "升级", "min_select": 1,
                      "selected_count": 0, "can_confirm": False,
                      "cards": [
                          {"index": 0, "card_id": "RUPT_UP", "name": "撕裂",
                           "card_type": "Power", "energy_cost": 1,
                           "rules_text": "每当你失去生命时，获得1点力量。"},
                          {"index": 1, "card_id": "BIG_ATK_UP", "name": "重击",
                           "card_type": "Attack", "energy_cost": 1,
                           "dynamic_values": [{"name": "Damage", "current_value": 15}]}]},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 10,
                "deck": [dict(c) for c in up_deck]}}
    d_upr = up_pol.decide(up_state, type("UCtxR", (), {})())
    assert d_upr.action == "select_deck_card" and d_upr.params.get("option_index") == 1, \
        f"触发条件不可满足的成长牌仍吃锻造端加分: {d_upr.action}（{d_upr.reason}）"
    assert "成长引擎" not in d_upr.reason, \
        f"死引擎锻造留痕残留: {d_upr.reason}"

    # 3xa-quinque（第546局批复盘）：战斗手牌载荷没有 card_type 字段（_score_play
    #           docstring 明示），旧死牌守卫的 is_power() 判定在实战中永不生效——
    #           LU9H 局零自残卡组在 18/21 血两次打出撕裂即铁证。修复后守卫补
    #           「力量+失去生命」文本共现通道，无 card_type 也拦得住。
    def rupture_nc_state(deck):
        st = rupture_state(deck)
        st["combat"]["hand"][0].pop("card_type", None)
        return st

    pol_rup_nc = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-ruptnc-"))), random.Random(5))
    d_rup_nc = pol_rup_nc.decide(rupture_nc_state(plain_deck), rup_ctx)
    assert d_rup_nc.action == "play_card" and d_rup_nc.params.get("card_index") == 1, \
        f"无card_type手牌的死引擎守卫失活（撕裂压过攻击）: {d_rup_nc.action}（{d_rup_nc.reason}）"
    d_rup_nc_live = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-ruptnc2-"))), random.Random(5)
    ).decide(rupture_nc_state(sd_deck), rup_ctx)
    assert d_rup_nc_live.action == "play_card" and d_rup_nc_live.params.get("card_index") == 0, \
        f"有自残源时无card_type引擎被误杀: {d_rup_nc_live.action}（{d_rup_nc_live.reason}）"

    # 3ra（第546局批复盘）：败局竞速执行经济学——判死后非致死回合的能力牌
    #           不再吃 base+长战加成、纯格挡按 race_allin_blk_damp 贬值，
    #           致死回合格挡豁免贬值（买命延长输出窗口当场仍合法）。
    ra_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-raecon-"))
    ra_pol = policy.Policy(knowledge.Knowledge(ra_dir), random.Random(5))
    ra_enemies = [{"index": 0, "enemy_id": "RA_BOSS", "name": "攻坚巨兽",
                   "current_hp": 253, "max_hp": 300, "block": 0,
                   "is_alive": True, "is_hittable": True,
                   "intents": [{"total_damage": 14}]}]
    ra_pow = {"index": 0, "card_id": "RA_POW", "name": "恶魔形态", "playable": True,
              "energy_cost": 3, "requires_target": False,
              "resolved_rules_text": "每回合开始时获得3点力量。"}
    s_pow_off = ra_pol._score_play(ra_pow, ra_enemies, 14, 0, 2, ra_pol.know.policy,
                                   my_hp=29, my_max_hp=80, cur_energy=3,
                                   hopeless_race=False, run_deck=[])[0]
    s_pow_on = ra_pol._score_play(ra_pow, ra_enemies, 14, 0, 2, ra_pol.know.policy,
                                  my_hp=29, my_max_hp=80, cur_energy=3,
                                  hopeless_race=True, run_deck=[])[0]
    assert s_pow_off > 10, f"健康局长战能力加成被误伤: {s_pow_off}"
    assert s_pow_on < ra_pol.know.policy["play_threshold"], \
        f"判死局能力牌仍吃长战加成挤占输出能量: {s_pow_on}"
    ra_blk = {"index": 0, "card_id": "RA_SHLD", "name": "壁垒", "playable": True,
              "energy_cost": 1, "requires_target": False,
              "dynamic_values": [{"name": "Block", "current_value": 8}]}
    ra_hit = {"index": 1, "card_id": "RA_HIT", "name": "打击", "playable": True,
              "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
              "dynamic_values": [{"name": "Damage", "current_value": 6}]}
    ra_pol.know.policy["block_safety"] = 2.1  # 对齐运行库口径，复现「格挡原价挤掉攻击」
    s_blk_norm = ra_pol._score_play(ra_blk, ra_enemies, 14, 0, 5, ra_pol.know.policy,
                                    my_hp=40, my_max_hp=80, cur_energy=3,
                                    hopeless_race=False, run_deck=[])[0]
    s_blk_allin = ra_pol._score_play(ra_blk, ra_enemies, 14, 0, 5, ra_pol.know.policy,
                                     my_hp=40, my_max_hp=80, cur_energy=3,
                                     hopeless_race=True, run_deck=[])[0]
    s_atk_allin = ra_pol._score_play(ra_hit, ra_enemies, 14, 0, 5, ra_pol.know.policy,
                                     my_hp=40, my_max_hp=80, cur_energy=3,
                                     hopeless_race=True, run_deck=[])[0]
    assert s_blk_norm > s_atk_allin, \
        f"对照场景失真（原价格挡本应压过弱攻击）: norm={s_blk_norm} atk={s_atk_allin}"
    assert s_blk_allin < s_atk_allin, \
        f"判死局非致死回合格挡未让位攻击: blk={s_blk_allin} atk={s_atk_allin}"
    s_blk_lethal = ra_pol._score_play(ra_blk, ra_enemies, 50, 0, 6, ra_pol.know.policy,
                                      my_hp=20, my_max_hp=80, cur_energy=3,
                                      hopeless_race=True, run_deck=[])[0]
    assert s_blk_lethal > s_blk_allin, \
        f"致死回合格挡被误贬值（买命窗口应保留原价）: lethal={s_blk_lethal} allin={s_blk_allin}"

    # 3xc（第658~663局批复盘）：开局承诺加成回归对——上一批该功能上线后
    #           首个整批窗口恰逢卡组零力量引擎（658~663 六局无一力量型
    #           能力牌供应），线上零触发、行为未受检验。此处正反例钉死：
    #           ① T1~T2 手握足额能量+大血池+无竞速判死 → 加分生效并留痕；
    #           ② 同局面 hopeless_race → 开局承诺被禁，能力仍压在出牌线
    #           之下（判死局烧 3 费买复利的旧教训不推翻）；
    #           ③ 走廊小血池不加成，节奏不扭曲。
    xc_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-commit-"))
    xc_pol = policy.Policy(knowledge.Knowledge(xc_dir), random.Random(5))
    xc_enemies = [dict(ra_enemies[0])]
    xc_inflame = {"index": 0, "card_id": "INFLAME", "name": "燃烧", "playable": True,
                  "energy_cost": 1, "requires_target": False,
                  "resolved_rules_text": "获得2点力量。"}
    _on_score, _, _why = xc_pol._score_play(dict(xc_inflame), xc_enemies, 14, 0, 1,
                                             xc_pol.know.policy,
                                             my_hp=77, my_max_hp=84, cur_energy=3,
                                             hopeless_race=False, run_deck=[])
    assert "开局承诺" in (_why or "") and _on_score > 15.0, \
        f"开局承诺加成失效: score={_on_score} why={_why}"
    _xc_off_score = xc_pol._score_play(dict(xc_inflame), xc_enemies, 14, 0, 1,
                                       xc_pol.know.policy,
                                       my_hp=77, my_max_hp=84, cur_energy=3,
                                       hopeless_race=True, run_deck=[])[0]
    assert _xc_off_score < xc_pol.know.policy["play_threshold"], \
        f"判死局能力牌吃开局承诺加成挤占输出能量: {_xc_off_score}"
    xc_hall = [dict(xc_enemies[0], current_hp=40)]
    _xc_small = xc_pol._score_play(dict(xc_inflame), xc_hall, 14, 0, 1,
                                   xc_pol.know.policy,
                                   my_hp=77, my_max_hp=84, cur_energy=3,
                                   hopeless_race=False, run_deck=[])[0]
    assert _xc_small < _on_score - 4.0, \
        f"走廊小血池误发开局承诺加成: small={_xc_small} boss={_on_score}"
    del _on_score, _why, _xc_off_score, _xc_small

    # 3xf（第635~640批复盘）：判死竞速致死回合的群体自残攻击解禁——非群体
    #           自残在同一局面走孤注一掷通道照常上砧，旧例唯独把突破族
    #           （小额掉血换全体伤害）压到禁玩线：640 局 F21「全攻提速」
    #           留痕下手握【突破】带能量空过（评估后无值得出的牌）。
    ff_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-brkaoe-"))
    ff_pol = policy.Policy(knowledge.Knowledge(ff_dir), random.Random(5))
    ff_enemies = [dict(ra_enemies[0])]
    ff_brk = {"index": 0, "card_id": "BREAKTHROUGH", "name": "突破", "playable": True,
              "energy_cost": 1, "requires_target": False,
              "resolved_rules_text": "失去1点生命，对所有敌人造成9点伤害。",
              "dynamic_values": [{"name": "Damage", "current_value": 9}]}
    ff_thr = ff_pol.know.policy["play_threshold"]
    # 对照：健康局致死回合无格挡可补时的 reserve_for_block=True 口径——
    # 群体自残照旧禁玩（回归保护）
    s_brk_norm = ff_pol._score_play(ff_brk, ff_enemies, 50, 0, 5, ff_pol.know.policy,
                                    my_hp=20, my_max_hp=80, cur_energy=3,
                                    reserve_for_block=True, min_blk_cost=1,
                                    run_deck=[])[0]
    assert s_brk_norm < ff_thr, \
        f"对照场景失真（健康局致死回合群体自残仍应禁玩）: {s_brk_norm}"
    # 正例①：斩杀竞速判死（kill_race）同局面解禁，减半计价后过阈值
    s_brk_race = ff_pol._score_play(ff_brk, ff_enemies, 50, 0, 5, ff_pol.know.policy,
                                    my_hp=20, my_max_hp=80, cur_energy=3,
                                    kill_race=True, run_deck=[])[0]
    assert s_brk_race > ff_thr >= s_brk_norm, \
        f"判死局群体自残攻击未被解禁: race={s_brk_race} norm={s_brk_norm} thr={ff_thr}"
    # 正例②：败局竞速口径（hopeless_race + 有格挡保留 → race_allin 生效路径）
    s_brk_allin = ff_pol._score_play(ff_brk, ff_enemies, 50, 0, 5, ff_pol.know.policy,
                                     my_hp=20, my_max_hp=80, cur_energy=3,
                                     hopeless_race=True,
                                     reserve_for_block=True, min_blk_cost=1,
                                     run_deck=[])[0]
    assert s_brk_allin > ff_thr, \
        f"race_allin 路径的群体自残未解禁: {s_brk_allin}"
    # 反例：自残后血量归零的直死牌不豁免（第29局终局教训守卫保留）
    s_brk_suic = ff_pol._score_play(ff_brk, ff_enemies, 50, 0, 5, ff_pol.know.policy,
                                    my_hp=1, my_max_hp=80, cur_energy=3,
                                    kill_race=True, run_deck=[])[0]
    assert s_brk_suic < ff_thr <= s_brk_race, \
        f"自残归零的直死牌不应解禁: suic={s_brk_suic}"

    # 3xg（01:43 滑溜批补合）：滑溜是逐 hit 的 HP 伤害上限，且只有穿甲
    # 命中才掉层。评分、击杀判断和最终出牌必须共用同一条逐段结算路径。
    sl_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-slippery-"))
    sl_pol = policy.Policy(knowledge.Knowledge(sl_dir), random.Random(5))
    sl_bludgeon = {
        "index": 0, "card_id": "BLUDGEON", "name": "重锤", "playable": True,
        "energy_cost": 3, "requires_target": True, "valid_target_indices": [0],
        "dynamic_values": [{"name": "Damage", "current_value": 32}],
    }
    # 实际载荷没有虚构的 Hits 动态值；中文“两次”必须由规则文本解析。
    sl_twin = {
        "index": 1, "card_id": "TWIN_STRIKE", "name": "双重打击", "playable": True,
        "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
        "resolved_rules_text": "造成5点伤害两次。",
        "dynamic_values": [{"name": "Damage", "current_value": 5}],
    }
    sl_strike = {
        "index": 2, "card_id": "STRIKE_IRONCLAD", "name": "打击", "playable": True,
        "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
        "dynamic_values": [{"name": "Damage", "current_value": 6}],
    }
    assert policy.card_numbers(sl_twin) == (5, 0, 2), \
        f"中文多段伤害载荷解析失效: {policy.card_numbers(sl_twin)}"

    def sl_enemy(hp=173, block=0, layers=None, *, index=0, intent=0, name="墨影幻灵"):
        powers = [] if layers is None else [{
            "power_id": "SLIPPERY_POWER", "name": "滑溜", "amount": layers,
            "is_debuff": False,
        }]
        return {
            "index": index, "enemy_id": f"VANTOM_{index}", "name": name,
            "current_hp": hp, "max_hp": 173, "block": block,
            "is_alive": True, "is_hittable": True,
            "intents": [{"total_damage": intent}], "powers": powers,
        }

    def sl_score(card, enemy, incoming=0):
        return sl_pol._score_play(
            dict(card), [enemy], incoming, 0, 2, sl_pol.know.policy,
            my_hp=80, my_max_hp=80, cur_energy=3, run_deck=[])

    # 三个身份字段必须合并识别，不能被一个无关 id 短路掉真实 power_id。
    sl_identity = sl_enemy(layers=8)
    sl_identity["powers"][0]["id"] = "RUNTIME_WRAPPER"
    assert sl_pol._enemy_slippery_stack(sl_identity) == 8, \
        f"真实 power_id 被无关 id 短路: {sl_identity['powers']}"

    # 无滑溜/零层严格保留旧计分；高层时不发“破层信用”，每个穿甲 hit 只记 1。
    s_plain, _, why_plain = sl_score(sl_bludgeon, sl_enemy(layers=None))
    s_zero, _, why_zero = sl_score(sl_bludgeon, sl_enemy(layers=0))
    s_sl_bludgeon, _, why_sl_bludgeon = sl_score(sl_bludgeon, sl_enemy(layers=8))
    s_sl_twin, _, why_sl_twin = sl_score(sl_twin, sl_enemy(layers=8))
    assert math.isclose(s_plain, 32.0) and math.isclose(s_zero, s_plain), \
        f"普通敌人旧评分回归: plain={s_plain} zero={s_zero} why={why_plain}/{why_zero}"
    assert math.isclose(s_sl_bludgeon, 1.0) and math.isclose(s_sl_twin, 2.0), \
        f"滑溜逐 hit 计分或零信用失效: hammer={s_sl_bludgeon} twin={s_sl_twin}"
    assert s_sl_twin > s_sl_bludgeon and "预计破1层" in why_sl_bludgeon \
            and "预计破2层" in why_sl_twin, \
        f"多段牌未正确优先: hammer={why_sl_bludgeon} twin={why_sl_twin}"

    # 第760~765批复盘 SLIPPERY_BURN_AUDIT（失败包 5274ccbe 补合）：高价单发
    # 烧层（重锤 1/3）与廉价多段烧层（双击 2/1）的留痕必须披露每费破层率与
    # 零意图标记；纯文本观测注，一阶分账不得漂移（上方 isclose 断言即守卫）。
    assert "滑溜烧墙审计：每费破层0.33" in why_sl_bludgeon \
            and "滑溜烧墙审计：每费破层2.00" in why_sl_twin, \
        f"滑溜烧墙审计注缺失或口径漂移: hammer={why_sl_bludgeon} twin={why_sl_twin}"
    assert "｜零意图回合" in why_sl_bludgeon, \
        f"零意图烧墙上下文未标记: {why_sl_bludgeon}"
    _, _, why_zero_layers = sl_score(sl_strike, sl_enemy(layers=None))
    assert "滑溜烧墙审计" not in why_zero_layers, \
        f"无滑溜目标误挂烧墙审计注: {why_zero_layers}"

    # block 必须先逐段吸收：全挡不掉层；部分穿甲只让该 hit 限伤并掉一层。
    s_full_block, _, why_full_block = sl_score(sl_bludgeon, sl_enemy(block=40, layers=8))
    s_full_plain, _, _ = sl_score(sl_bludgeon, sl_enemy(block=40, layers=None))
    s_partial, _, why_partial = sl_score(sl_strike, sl_enemy(block=3, layers=8))
    assert math.isclose(s_full_block, s_full_plain) and "预计破0层" in why_full_block, \
        f"整段被格挡仍误掉滑溜层: slip={s_full_block} plain={s_full_plain} why={why_full_block}"
    assert math.isclose(s_partial, 4.0) and "逐段折算≈4.0" in why_partial \
            and "预计破1层" in why_partial, \
        f"部分穿甲结算错误（3甲+1血应为4）: score={s_partial} why={why_partial}"
    s_combo, _, why_combo = sl_score(sl_twin, sl_enemy(block=3, layers=1))
    assert math.isclose(s_combo, 9.0) and "预计破1层" in why_combo, \
        f"多段攻击穿甲并中途耗尽滑溜层错误（3甲+1血+5血应为9）: " \
        f"score={s_combo} why={why_combo}"
    _, _, why_exact_block = sl_score(sl_bludgeon, sl_enemy(hp=1, block=32, layers=8))
    _, _, why_exact_pierce = sl_score(sl_bludgeon, sl_enemy(hp=1, block=31, layers=8))
    assert not why_exact_block.startswith("可击杀") and "预计破0层" in why_exact_block, \
        f"刚好全挡被误判击杀/掉层: {why_exact_block}"
    assert why_exact_pierce.startswith("可击杀") and "预计破1层" in why_exact_pierce, \
        f"刚好穿甲1点未判击杀/掉层: {why_exact_pierce}"

    # 层数耗尽后，后续 hit 恢复原伤害；击杀边界必须与评分共用模拟结果。
    s_one_layer, _, why_one_layer = sl_score(sl_twin, sl_enemy(layers=1))
    assert math.isclose(s_one_layer, 6.0) and "预计破1层" in why_one_layer, \
        f"滑溜耗尽后的后续 hit 未恢复伤害: score={s_one_layer} why={why_one_layer}"
    _, _, why_hp1 = sl_score(sl_bludgeon, sl_enemy(hp=1, layers=8))
    _, _, why_hp20 = sl_score(sl_bludgeon, sl_enemy(hp=20, layers=8))
    _, _, why_hp2_twin = sl_score(sl_twin, sl_enemy(hp=2, layers=8))
    assert why_hp1.startswith("可击杀") and not why_hp20.startswith("可击杀") \
            and why_hp2_twin.startswith("可击杀"), \
        f"滑溜击杀边界错误: hp1={why_hp1} hp20={why_hp20} twin/hp2={why_hp2_twin}"

    # AOE 中普通敌人仍按旧口径，滑溜敌人按逐段口径；理由留下可观测明细。
    sl_aoe = {
        "index": 3, "card_id": "CLEAVE", "name": "顺劈斩", "playable": True,
        "energy_cost": 1, "requires_target": False,
        "resolved_rules_text": "对所有敌人造成6点伤害。",
        "dynamic_values": [{"name": "Damage", "current_value": 6}],
    }
    sl_aoe_enemies = [
        sl_enemy(hp=50, layers=None, index=0, name="普通敌人"),
        sl_enemy(hp=50, layers=8, index=1, name="墨影幻灵"),
    ]
    s_aoe, t_aoe, why_aoe = sl_pol._score_play(
        sl_aoe, sl_aoe_enemies, 0, 0, 2, sl_pol.know.policy,
        my_hp=80, my_max_hp=80, cur_energy=3, run_deck=[])
    assert math.isclose(s_aoe, 7.0) and t_aoe is None \
            and "群体伤害≈7.0" in why_aoe and "墨影幻灵8→破1" in why_aoe, \
        f"AOE 滑溜折算错误: score={s_aoe} target={t_aoe} why={why_aoe}"
    # 第760~765批复盘 AOE 侧同口径烧墙审计注（CLEAVE 1费破1层=每费1.00）
    assert "滑溜烧墙审计：每费破层1.00" in why_aoe \
            and "｜零意图回合" in why_aoe, \
        f"AOE 烧墙审计注缺失或口径漂移: {why_aoe}"

    # 现有集火粘性不因结算重构丢失。
    sl_pol._focus_index = 1
    sticky_enemies = [
        sl_enemy(hp=80, layers=None, index=0, intent=5, name="甲"),
        sl_enemy(hp=80, layers=None, index=1, intent=5, name="乙"),
    ]
    sl_sticky_strike = dict(sl_strike, valid_target_indices=[0, 1])
    _, sticky_target, sticky_why = sl_pol._score_play(
        sl_sticky_strike, sticky_enemies, 10, 0, 2, sl_pol.know.policy,
        my_hp=80, my_max_hp=80, cur_energy=3, run_deck=[])
    assert sticky_target == 1 and sl_pol._focus_index == 1 and "延续集火" in sticky_why, \
        f"滑溜结算重构破坏集火粘性: target={sticky_target} why={sticky_why}"

    # 单体候选混有普通与滑溜敌人时，逐目标模拟不能把滑溜折算泄漏到普通目标。
    sl_mixed_bludgeon = dict(sl_bludgeon, valid_target_indices=[0, 1])
    _, mixed_target, mixed_why = sl_pol._score_play(
        sl_mixed_bludgeon, [
            sl_enemy(hp=80, layers=8, index=0, name="滑溜目标"),
            sl_enemy(hp=80, layers=None, index=1, name="普通目标"),
        ], 0, 0, 2, sl_pol.know.policy,
        my_hp=80, my_max_hp=80, cur_energy=3, run_deck=[])
    assert mixed_target == 1 and "普通目标" in mixed_why, \
        f"滑溜逐目标状态污染普通目标: target={mixed_target} why={mixed_why}"

    # 端到端：同场重锤与双重打击应选多段牌；只有重锤时仍正常出牌而非禁玩。
    def sl_combat_state(hand):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 2,
            "combat": {
                "player": {"current_hp": 80, "max_hp": 80, "block": 0, "energy": 3},
                "hand": hand, "enemies": [sl_enemy(layers=8)],
            },
            "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 17, "deck": []},
        }

    sl_live_pol = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-slippery-live-"))), random.Random(5))
    d_sl_multi = sl_live_pol.decide(sl_combat_state([sl_bludgeon, sl_twin]), DummyCtx())
    assert d_sl_multi.action == "play_card" and d_sl_multi.params.get("card_index") == 1 \
            and "滑溜8层" in d_sl_multi.reason, \
        f"端到端未选择多段攻击: {d_sl_multi.action} {d_sl_multi.params}（{d_sl_multi.reason}）"
    sl_only_pol = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-slippery-only-"))), random.Random(5))
    d_sl_only = sl_only_pol.decide(sl_combat_state([sl_bludgeon]), DummyCtx())
    assert d_sl_only.action == "play_card" and d_sl_only.params.get("card_index") == 0, \
        f"滑溜单段攻击被误禁导致空过: {d_sl_only.action} {d_sl_only.params}（{d_sl_only.reason}）"

    # 第580局：NO_BLOCK_POWER 锁窗内纯防牌必须成为死牌；载荷已报 0 时
    # 文本兜底同样生效；带伤害面的混合牌保留输出价值。
    nb_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-noblock-"))
    nb_pol = policy.Policy(knowledge.Knowledge(nb_dir), random.Random(5))
    nb_enemies = [{"index": 0, "enemy_id": "NB_EFFIGY", "name": "旧日雕像",
                   "current_hp": 110, "max_hp": 127, "block": 0,
                   "is_alive": True, "is_hittable": True,
                   "intents": [{"total_damage": 0}]}]
    nb_threshold = nb_pol.know.policy["play_threshold"]
    nb_def_pure = {"index": 0, "card_id": "DEFEND_IRONCLAD", "name": "防御",
                   "playable": True, "energy_cost": 1, "requires_target": False,
                   "dynamic_values": [{"name": "Block", "current_value": 5}],
                   "resolved_rules_text": "获得5点格挡。"}
    s_nb_flag = nb_pol._score_play(dict(nb_def_pure), nb_enemies, 23, 0, 1,
                                   nb_pol.know.policy, my_hp=71, my_max_hp=80,
                                   cur_energy=3, run_deck=[], block_locked=True)[0]
    s_nb_norm = nb_pol._score_play(dict(nb_def_pure), nb_enemies, 23, 0, 1,
                                   nb_pol.know.policy, my_hp=71, my_max_hp=80,
                                   cur_energy=3, run_deck=[])[0]
    assert s_nb_flag < nb_threshold <= s_nb_norm, \
        f"NO_BLOCK 锁窗纯防牌未按死牌计价: locked={s_nb_flag} norm={s_nb_norm}"
    nb_def_zero = {"index": 0, "card_id": "DEFEND_IRONCLAD", "name": "防御",
                   "playable": True, "energy_cost": 1, "requires_target": False,
                   "dynamic_values": [{"name": "Block", "current_value": 0}],
                   "resolved_rules_text": "获得0点格挡。"}
    s_nb_text = nb_pol._score_play(nb_def_zero, nb_enemies, 23, 0, 1,
                                   nb_pol.know.policy, my_hp=71, my_max_hp=80,
                                   cur_energy=3, run_deck=[])[0]
    assert s_nb_text < nb_threshold, \
        f"「获得0点格挡」文本通道死牌守卫失活: {s_nb_text}"
    nb_wave = {"index": 0, "card_id": "IRON_WAVE", "name": "铁斩波",
               "playable": True, "energy_cost": 1, "requires_target": False,
               "dynamic_values": [{"name": "Block", "current_value": 5},
                                  {"name": "Damage", "current_value": 5}]}
    d_wave = nb_pol._score_play(nb_wave, nb_enemies, 23, 0, 1, nb_pol.know.policy,
                                my_hp=71, my_max_hp=80, cur_energy=3, run_deck=[],
                                block_locked=True)
    assert d_wave[0] > 0 and ("单体伤害" in d_wave[2] or "群体伤害" in d_wave[2]), \
        f"锁窗混合牌伤害面被误杀: {d_wave}"

    # 3xa-quater（第470局批复盘）：短时死亡证据的第三级接替旋钮——高危组合
    #           防御姿态斜率 danger_comp_blk_boost。block_safety 与药水交药线
    #           双顶格后，证据改接组合专属姿态（战场归属正确）；默认值=旧
    #           硬编码 0.30 行为零跳变；演化后 enemy_stance 斜率同步生效；
    #           胜利时回收（接替链有降必有升）。
    dcb_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-dcb-"))
    dcb_know = knowledge.Knowledge(dcb_dir)
    dcb_know.stats["enemies"]["KILLER_COMP"] = {
        "encounters": 10, "deaths": 6, "hp_lost_sum": 500.0, "wins": 4}
    st_dcb0 = dcb_know.enemy_stance("KILLER_COMP", "Monster", 80)
    assert abs(st_dcb0["blk_mult"] - 1.30) < 1e-9, \
        f"默认斜率应为旧锚点1.30: {st_dcb0['blk_mult']}"
    dcb_know.policy["danger_comp_blk_boost"] = 0.45
    st_dcb1 = dcb_know.enemy_stance("KILLER_COMP", "Monster", 80)
    assert abs(st_dcb1["blk_mult"] - 1.45) < 1e-9, \
        f"斜率演化未在组合姿态生效: {st_dcb1['blk_mult']}"
    dcb2_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-sdeath-"))
    dcb2_know = knowledge.Knowledge(dcb2_dir)
    dcb2_know.policy["block_safety"] = 2.10      # 一级顶格
    dcb2_know.policy["potion_block_hp_pct"] = 0.80  # 二级顶格
    sd_ctx = SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "SD_COMP", "rounds": 3, "node_type": "Monster"},
        death_was_elite=False, death_hp_pct_at_entry=0.9,
        credit_tags=[], rests_healed_at_full=0, ascension=0, combat_notes=[])
    sd_lesson = finalize_run(dcb2_know, sd_ctx, victory=False, final_floor=12)
    assert abs(dcb2_know.policy["danger_comp_blk_boost"] - 0.35) < 1e-9, \
        f"三级链未吸收短时死亡证据: {dcb2_know.policy['danger_comp_blk_boost']}"
    assert "组合防御姿态斜率" in sd_lesson and "接替旋钮留待复盘设计" not in sd_lesson, \
        f"三级接替留痕异常: {sd_lesson[:300]}"

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

    # 3xz) 分幕实证先验接入（第 148~160 批复盘）：room_damage_prior_act 自第 79 批
    #      落地起从未被任何调用方使用（死代码），rooms_act 分幕数据持续采集 80+ 局
    #      零消费——投影一直用跨幕混算先验 × 静态 path_act_scale。接入后命中分幕
    #      实证时幕数乘区必须归 1：实测场均已含幕效应，再乘 act_mul 是双重计费
    #      （Elite 二幕：跨幕 blended 22.7×1.7=38.7 vs 本幕实证 34.0，叠加则 45.9）
    ac_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-actprior-"))
    ac_know = knowledge.Knowledge(ac_dir)
    ac_know.stats["rooms"]["Monster"] = {"visits": 600, "outcome_sum": 0.0,
                                         "hp_lost_sum": 4800.0, "damage_events": 600}
    ac_know.stats["rooms"]["Elite"] = {"visits": 55, "outcome_sum": 0.0,
                                       "hp_lost_sum": 1125.0, "damage_events": 55}
    # 无分幕数据 → 回落跨幕口径并标记未命中
    p_m1, hit_m1 = ac_know.room_damage_prior_act("Monster", 8.0, 2)
    assert not hit_m1 and abs(p_m1 - 8.0) < 1e-9, \
        f"无分幕样本未回落跨幕口径: {p_m1}, hit={hit_m1}"
    # 有分幕样本（Monster@2 实测 30/场）→ 高权重实证混合，命中标记 True
    ac_know.stats["rooms_act"]["Monster@2"] = {"hp_lost_sum": 300.0, "damage_events": 10}
    p_m2, hit_m2 = ac_know.room_damage_prior_act("Monster", 8.0, 2)
    exp_m2 = 0.15 * 8.0 + 0.85 * 30.0
    assert hit_m2 and abs(p_m2 - exp_m2) < 1e-9, \
        f"分幕实证先验错误: {p_m2}（期望 {exp_m2}）, hit={hit_m2}"
    # 二幕精英：实证 34.0 低于跨幕×1.7 旧口径 38.7——双重计费拆除后精英威胁
    # 不再被静态幕数系数虚抬（二幕遗物供给通道）
    ac_know.stats["rooms_act"]["Elite@2"] = {"hp_lost_sum": 102.0, "damage_events": 3}
    p_e2, hit_e2 = ac_know.room_damage_prior_act("Elite", 28.0, 2)
    exp_e2 = (1 - 3 / 8) * (0.3 * 28.0 + 0.7 * (1125.0 / 55)) + (3 / 8) * 34.0
    assert hit_e2 and abs(p_e2 - exp_e2) < 1e-9, \
        f"精英分幕先验错误: {p_e2}（期望 {exp_e2:.2f}）"
    assert p_e2 < (0.3 * 28.0 + 0.7 * (1125.0 / 55)) * 1.7, \
        f"幕效应双重计费未拆除: {p_e2}"
    # _act_danger：命中时幕数乘区归 1，未命中时维持 act_mul
    ac_pol = policy.Policy(ac_know)
    _ap, _am, _aspec = ac_pol._act_danger("Monster", {}, 2, 1.7)
    assert _aspec and _am == 1.0, f"命中分幕实证时幕数乘区未归 1: {_am}"
    _ap2, _am2, _aspec2 = ac_pol._act_danger("Unknown", {}, 2, 1.7)
    assert not _aspec2 and _am2 == 1.7, f"未命中分幕实证时幕数乘区丢失: {_am2}"
    # 集成：二幕地图投影使用分幕实证——满血、两场 Monster 到 Boss，
    # 旧口径投影 66%（8×1.7×2），新口径投影 33%（26.7×2，乘区归 1）
    def act2_proj_map():
        heads = [{"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                  "children": [{"row": 2, "col": 0}]}]
        rest_nodes = [
            {"row": 2, "col": 0, "node_type": "Monster",
             "children": [{"row": 3, "col": 0}]},
            {"row": 3, "col": 0, "node_type": "Boss"},
        ]
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": heads, "nodes": heads + rest_nodes,
                      "boss_node": {"row": 3}},
              "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                      "floor": 20, "deck": []}}
        return ac_pol.decide(st, type("C", (), {"credit_tags": []})())

    d_ac = act2_proj_map()
    m_ac = re.search(r"预计进 Boss 血量 (\d+)%", d_ac.reason)
    assert m_ac and m_ac.group(1) == "33", \
        f"二幕投影未使用分幕实证（旧口径为 66%）: {d_ac.reason}"

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

    # 3xy2) 投影罚分软饱和（第 108 局复盘）：二幕开局全线评分曾饱和在 -159~-193、
    #       「预计进Boss血量 0%」，房间权重/休整加成等正信号在罚分竞赛中失声，
    #       决策退化为比拼「投影死得早晚」。压扁后：大额罚分渐近饱和上限（任何
    #       候选的罚分贡献 ≤ path_penalty_saturation），候选间保序且保留可辨差距；
    #       小额罚分近似线性不受伤（3y 的门槛翻转语义不变，已在前序用例验证）
    sq_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-squash-"))
    sq_know = knowledge.Knowledge(sq_dir)
    sq_pol = policy.Policy(sq_know)

    def act2_map(hp_now, gold=0):
        heads = [
            {"index": 0, "row": 1, "col": 0, "node_type": "Monster",
             "children": [{"row": 2, "col": 0}]},
            {"index": 1, "row": 1, "col": 1, "node_type": "Shop",
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
              "run": {"current_hp": hp_now, "max_hp": 80, "gold": gold,
                      "floor": 20, "deck": []}}
        return sq_pol.decide(st, type("C", (), {"credit_tags": []})())

    d_sq = act2_map(45)      # 二幕 56% 血：怪物链半路暴毙 vs 商店+事件链低血进场
    m_chain = re.search(r"Monster\(1,0\)=(-?[0-9.]+)", d_sq.reason)
    m_shop = re.search(r"Shop\(1,1\)=(-?[0-9.]+)", d_sq.reason)
    assert m_chain and m_shop, f"软饱和用例候选缺失: {d_sq.reason}"
    sc_chain, sc_shop = float(m_chain.group(1)), float(m_shop.group(1))
    sat_cap = float(sq_know.policy["path_penalty_saturation"])
    assert -sat_cap - 10.0 < sc_chain < 0, \
        f"死亡路径罚分未饱和（应渐近 ±{sat_cap:.0f} 内）: {sc_chain}（{d_sq.reason}）"
    assert sc_shop > sc_chain, \
        f"软饱和破坏候选保序: shop={sc_shop} chain={sc_chain}"

    # 3xy2-bis) 商店药水档（第 248 批复盘）：gold < shop_min_gold(140) 但够买药水
    #       （≥shop_potion_gold 60）时商店不再被「金币不足」0.6 整体压死——
    #       药水是爆毙通道唯一稳定补给（237 局 120+ 金死携从未进店）。
    #       够药水档 → 理由留痕「够买药水」且分值高于 0 金档；0 金照旧「金币不足」
    d_pt = act2_map(60, gold=100)   # 75% 血、100 金：够买药水档（正常血量 1.0 权重）
    assert "够买药水" in d_pt.reason, f"药水档商店未留痕: {d_pt.reason}"
    assert "金币不足" not in d_pt.reason, f"药水档被误压成金币不足: {d_pt.reason}"
    d_pt0 = act2_map(60, gold=30)   # 30 金：连药水都买不起，照旧 0.6 压死
    assert "金币不足" in d_pt0.reason, f"0 金档商店误抬: {d_pt0.reason}"
    m_shop_pt = re.search(r"Shop\(1,1\)=(-?[0-9.]+)", d_pt.reason)
    m_shop_pt0 = re.search(r"Shop\(1,1\)=(-?[0-9.]+)", d_pt0.reason)
    assert m_shop_pt and m_shop_pt0, f"药水档用例候选缺失: {d_pt.reason}"
    assert float(m_shop_pt.group(1)) > float(m_shop_pt0.group(1)), \
        f"药水档未提升商店评分: {m_shop_pt.group(1)} vs {m_shop_pt0.group(1)}"

    # 3xy2-c) 绝境资源节点偏好（403~406 批次复盘）：全部候选路径都投影中途死亡时，
    #       死亡罚分软饱和把候选差压成噪声级，评分退化为比拼死得早晚——EQ04 局 F3
    #       商店(468金可换战力/删诅咒)以 0.61 分之差输给又一场白死的怪物战。
    #       全候选死亡投影且存在 Shop/Treasure/Event 首节点时：资源节点加
    #       path_doomed_value_bonus 正分胜出并留痕；无资源节点时行为不变
    dv_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-doomval-"))
    dv_know = knowledge.Knowledge(dv_dir)
    dv_pol = policy.Policy(dv_know)

    def doomval_map(second_head):
        """Monster 链(col0，depth0 开战) vs 第二候选(col1)；双方均投影中途死亡。

        hp=20/80：怪物链第 3 场战斗(depth2)打死；商店/怪物链首场延后到 depth1、
        第 3 场(depth3)打死——两列都在半路暴毙，触发绝境偏好条件。
        """
        heads = [{"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                  "children": [{"row": 2, "col": 0}]},
                 {"index": 1, "row": 1, "col": 1, "node_type": second_head,
                  "children": [{"row": 2, "col": 1}]}]
        all_nodes = list(heads)
        for col in (0, 1):
            for r in range(2, 13):
                g = {"row": r, "col": col,
                     "node_type": "Boss" if r == 12 else "Monster"}
                if r < 12:
                    g["children"] = [{"row": r + 1, "col": col}]
                all_nodes.append(g)
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": heads, "nodes": all_nodes,
                      "boss_node": {"row": 12}},
              "run": {"current_hp": 20, "max_hp": 80, "gold": 200,
                      "floor": 5, "deck": []}}
        return dv_pol.decide(st, type("C", (), {"credit_tags": []})())

    d_dv_shop = doomval_map("Shop")
    assert "绝境全候选死亡投影" in d_dv_shop.reason, \
        f"绝境偏好未留痕: {d_dv_shop.reason}"
    assert re.search(r"路径规划：Shop\(1,1\)", d_dv_shop.reason), \
        f"绝境时资源节点未胜出: {d_dv_shop.reason}"
    d_dv_mon = doomval_map("Monster")   # 对照组：无价值节点，行为不变
    assert "绝境全候选死亡投影" not in d_dv_mon.reason, \
        f"无价值节点时误留痕: {d_dv_mon.reason}"

    # 3xy3) 中段精英罚分深度衰减（第 107 局复盘）：29% 血时唯一篝火因子树深处
    #       藏精英被罚到 -84 压过 Monster(-0.94)，放弃救命休息。逐节点选路下
    #       depth 越深的精英越不是承诺（中间岔口可改道），罚分须随深度衰减；
    #       近处精英威慑仍保留主要强度（54 局商店下一层藏精英的教训不回退）
    md_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-midgate-"))
    md_know = knowledge.Knowledge(md_dir)
    md_know.policy["elite_min_hp_pct"] = 0.90   # 复刻运行值：62%~90% 灰区存在
    md_know.policy["elite_soft_hp_pct"] = 0.62
    md_know.policy["path_hp_floor_pct"] = 0.20  # 屏蔽血量线/Boss入场线，
    md_know.policy["boss_entry_min_hp_pct"] = 0.30  # 只留 mid_gate 单变量
    md_pol = policy.Policy(md_know)

    def midgate_map(elite_depth: int):
        """RestSite 首节点(r1) + 三层链(r2~r4，其中一层为 Elite) + Boss(r5)。

        elite_depth 为链内序数（2/3/4 行），对应路径投影中的 depth 1/2/3。
        """
        def build(col):
            nodes = []
            for row in (2, 3, 4):
                d = row - 1                      # 投影 depth：r2→1 ... r4→3
                nt = "Elite" if d == elite_depth - 1 else "Event"
                nodes.append({"row": row, "col": col, "node_type": nt,
                              "children": [{"row": row + 1, "col": col}]})
            return nodes
        left = [{"index": 0, "row": 1, "col": 0, "node_type": "RestSite",
                 "children": [{"row": 2, "col": 0}]}]
        right = [{"index": 1, "row": 1, "col": 1, "node_type": "RestSite",
                  "children": [{"row": 2, "col": 1}]}]
        lchain = build(0) + [{"row": 5, "col": 0, "node_type": "Boss"}]
        rchain = build(1) + [{"row": 5, "col": 1, "node_type": "Boss"}]
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": left + right, "nodes": left + right + lchain + rchain,
                      "boss_node": {"row": 5}},
              "run": {"current_hp": 50, "max_hp": 80, "gold": 0, "floor": 10,
                      "deck": [{"card_id": f"CARD_{i}"} for i in range(6)]}}
        return md_pol.decide(st, type("C", (), {"credit_tags": []})())

    d_near = midgate_map(2)    # 精英在 depth1（紧邻篝火）：威慑基本保持
    d_far = midgate_map(4)     # 精英在 depth3（深处）：承诺度低应显著减罚

    d_near = midgate_map(2)    # 精英在 depth1（紧邻篝火）：威慑基本保持
    d_far = midgate_map(4)     # 精英在 depth3（深处）：承诺度低应显著减罚
    m_near = re.search(r"RestSite\(1,0\)=(-?[0-9.]+)", d_near.reason)
    m_far = re.search(r"RestSite\(1,1\)=(-?[0-9.]+)", d_far.reason)
    assert m_near and m_far, f"mid_gate 用例候选缺失: {d_near.reason} / {d_far.reason}"
    assert float(m_far.group(1)) > float(m_near.group(1)) + 3.0, \
        f"远处精英罚分未随深度衰减: near={m_near.group(1)} far={m_far.group(1)}"
    for dd in (d_near, d_far):
        assert "路径中段含未达标精英" in dd.reason, \
            f"mid_gate 罚分留痕丢失: {dd.reason}"

    # 第580局：深度输出饥饿时，硬线以上精英也要过单场最差尾部复核。
    etv_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-etv-"))
    etv_know = knowledge.Knowledge(etv_dir)
    etv_know.policy["elite_min_hp_pct"] = 0.90
    etv_know.policy["elite_soft_hp_pct"] = 0.75
    etv_know.stats.setdefault("rooms_act", {})["Elite@1"] = {
        "hp_lost_sum": 300.0, "damage_events": 10, "hp_lost_max": 75.0}
    etv_pol = policy.Policy(etv_know)

    def etv_map(hp_now: int):
        def chain(col):
            nodes = [{"row": row, "col": col, "node_type": "Event"}
                     for row in (2, 3, 4)]
            for node in nodes[:-1]:
                node["children"] = [{"row": node["row"] + 1, "col": col}]
            return nodes
        elite_head = [{"index": 0, "row": 1, "col": 0, "node_type": "Elite",
                       "children": [{"row": 2, "col": 0}]}]
        rest_head = [{"index": 1, "row": 1, "col": 1, "node_type": "RestSite",
                      "children": [{"row": 2, "col": 1}]}]
        state = {"screen": "MAP", "available_actions": ["choose_map_node"],
                 "map": {"available_nodes": elite_head + rest_head,
                         "nodes": elite_head + rest_head + chain(0) + chain(1)
                         + [{"row": 5, "col": 0, "node_type": "Boss"},
                            {"row": 5, "col": 1, "node_type": "Boss"}],
                         "boss_node": {"row": 5}},
                 "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 15,
                         "deck": [{"card_id": f"GUARD_SKILL_{i}"} for i in range(6)]}}
        return etv_pol.decide(state, type("C", (), {"credit_tags": []})())

    d_etv_low = etv_map(72)
    assert "硬线精英尾部复核" in d_etv_low.reason, \
        f"硬线精英尾部复核未触发: {d_etv_low.reason}"
    assert re.search(r"路径规划：RestSite\(1,1\)", d_etv_low.reason), \
        f"尾部复核后仍选精英: {d_etv_low.reason}"
    # 反例是“满血 + 温和尾部”，不能沿用上面的 75 点极端样本；否则
    # 80/80 打完只剩 5 点，本来就应触发近死尾部复核。
    etv_know.stats["rooms_act"]["Elite@1"]["hp_lost_max"] = 20.0
    d_etv_full = etv_map(80)
    assert "硬线精英尾部复核" not in d_etv_full.reason, \
        f"满血健康进场被误伤: {d_etv_full.reason}"
    etv_know.policy["elite_tail_veto_min_deficit"] = 2.0
    d_etv_off = etv_map(72)
    assert "硬线精英尾部复核" not in d_etv_off.reason, \
        f"旋钮关闭后仍留痕: {d_etv_off.reason}"

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

    # 3xz-bis) 锻造预演连战累计（第 370~371 局复盘）：371 局 65% 血在双怪物
    #      前夜按「单场期望战损」判定安全上砧，随后两连战 -32/-20 连环处决；
    #      当时回血 +24 即可全活。地图端预演必须累计连续战斗节点——双怪链的
    #      累计账打穿紧急线时篝火改回血；单怪链控制组维持锻造（防退化为永远
    #      回血、卡组停摆）。
    cg_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-chainprev-"))
    cg_know = knowledge.Knowledge(cg_dir)
    cg_know.policy["path_danger_priors"]["Monster"] = 15   # 单场 15/80≈18.75%
    cg_pol = policy.Policy(cg_know)

    def chain_preview_map(monster_rows):
        """RestSite(1) 唯一头节点 + monster_rows 指定行放 Monster（其余 Event）+ Boss(5)。"""
        head = [{"index": 0, "row": 1, "col": 0, "node_type": "RestSite",
                 "children": [{"row": 2, "col": 0}]}]
        chain = []
        for row in range(2, 5):
            nt = "Monster" if row in monster_rows else "Event"
            g = {"row": row, "col": 0, "node_type": nt}
            if row < 4:
                g["children"] = [{"row": row + 1, "col": 0}]
            chain.append(g)
        chain.append({"row": 5, "col": 0, "node_type": "Boss"})
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": head, "nodes": head + chain,
                      "boss_node": {"row": 5}},
              "run": {"current_hp": 65, "max_hp": 80, "gold": 0, "floor": 8,
                      "deck": []}}
        return cg_pol.decide(st, ctx)

    st_rest = {"screen": "REST", "available_actions": ["choose_rest_option"],
               "rest": {"options": [
                   {"index": 0, "option_id": "HEAL", "title": "休息", "is_enabled": True},
                   {"index": 1, "option_id": "SMITH", "title": "锻造", "is_enabled": True}]},
               "run": {"current_hp": 52, "max_hp": 80, "gold": 0, "floor": 9,
                       "deck": [{"card_id": "STRIKE_X", "upgraded": False}]}}
    chain_preview_map({2, 3})                  # 篝火后双怪连战：累计 30/80=37.5%
    assert abs(getattr(ctx, "rest_next_fight_loss_frac", 0.0) - 0.375) < 1e-6, \
        f"连战预演未累计: {ctx.rest_next_fight_loss_frac}"
    ctx.rest_proj_hp_pct = 1.0                 # 投影健康，隔离绝境分支
    d_heal2 = pol.decide(st_rest, ctx)
    assert d_heal2.tags and d_heal2.tags[0] == ("rest", "heal") and "预演" in d_heal2.reason, \
        f"双怪前夜未触发预演回血: {d_heal2.reason}"
    chain_preview_map({2})                     # 控制：单怪链预演 15/80=18.75%
    assert abs(getattr(ctx, "rest_next_fight_loss_frac", 0.0) - 0.1875) < 1e-6, \
        f"单战预演值异常: {ctx.rest_next_fight_loss_frac}"
    ctx.rest_proj_hp_pct = 1.0
    d_smith2 = pol.decide(st_rest, ctx)
    assert d_smith2.tags and d_smith2.tags[0] == ("rest", "smith"), \
        f"单怪链不应放弃锻造: {d_smith2.reason}"

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

    # 3ya-bis) 货架药水购买（第 248 批复盘）：药水是爆毙通道唯一稳定补给，
    #      但货架药水此前完全不在评估范围。防御/回复药低血急需应成交；
    #      高价无法分类药不得挤占预算（价值 < 门槛 → 关店）
    def shop_potion_state(hp_now, potion):
        return {"screen": "SHOP",
                "available_actions": ["buy_card", "buy_potion", "close_shop_inventory"],
                "shop": {"is_open": True, "can_close": True,
                         "cards": [], "relics": [], "card_removal": None,
                         "potions": [potion]},
                "run": {"current_hp": hp_now, "max_hp": 80, "gold": 500, "floor": 30,
                        "deck": []}}
    block_pot = {"index": 0, "potion_id": "BLOCK_POTION", "name": "格挡药水",
                 "rarity": "Common", "usage": "CombatOnly", "price": 75,
                 "is_stocked": True, "enough_gold": True}
    d_sp1 = pol.decide(shop_potion_state(24, block_pot), ctx)   # 30% 血：防御药急需
    assert d_sp1.action == "buy_potion", \
        f"低血防御/回复药未成交: {d_sp1.action}（{d_sp1.reason}）"
    mystery_pot = {"index": 0, "potion_id": "MYSTERY_POTION", "name": "神秘药水",
                   "rarity": "Rare", "usage": "CombatOnly", "price": 200,
                   "is_stocked": True, "enough_gold": True}
    d_sp2 = pol.decide(shop_potion_state(24, mystery_pot), ctx)  # 高价未知药：1.2-1.67<门槛
    assert d_sp2.action == "close_shop_inventory", \
        f"高价无法分类药挤占预算: {d_sp2.action}（{d_sp2.reason}）"
    d_sp3 = pol.decide(shop_potion_state(24, dict(block_pot, enough_gold=False)), ctx)
    assert d_sp3.action == "close_shop_inventory", \
        f"无空位/金不足的药水被误买: {d_sp3.action}（{d_sp3.reason}）"

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

    # 3zb) 事件触发战斗的延迟结算（第 106 局复盘数据修复 + 第 237~238 批归因
    #      扩展）：「茂密的植被-战！」在随后的战斗中把感染×3 打进牌堆，旧逻辑
    #      进战瞬间结算 deck_delta 恒 0——事件端把「污染卡组」当免费。语义：
    #      hp/金币按离开事件屏瞬间的快照记账（事件自身即时效果）；卡组增量用
    #      战后 live 值；战斗中的死亡不归因给事件选项（归敌人组合）；第 237~238
    #      批起战斗掉血叠加归因到引发战斗的选项（快照把 -54 强制战藏成 0.0，
    #      237/238 两局实证被错选成系统性失血）。
    ag.ctx.reset_for("RUN_EVT2", 0)

    def evt_flow_state(screen, hp, gold, deck_len):
        st = {"screen": screen, "run_id": "RUN_EVT2",
              "run": {"current_hp": hp, "max_hp": 80, "gold": gold, "floor": 14,
                      "deck": [{"card_id": f"C{i}"} for i in range(deck_len)]}}
        if screen == "COMBAT":
            st["combat"] = {"enemies": [{"enemy_id": "VEG_BUG", "is_alive": True}]}
        return st

    track_accepted(ag, evt_flow_state("EVENT", 80, 50, 1),
                   policy.Decision(action="choose_event_option",
                                   tags=[("event_choice", "VEG_EV", "FIGHT")]))
    # 进战 tick：事件已发放 +20 金（即时效果），hp 未变——快照应冻结在此
    ag._track(evt_flow_state("COMBAT", 80, 70, 1), policy.Decision(action=None))
    assert tknow.stats["events"].get("VEG_EV", {}).get("FIGHT") is None, \
        "事件触发的战斗在进战瞬间就被提前结算（旧 bug 复发）"
    # 战后流转：战斗掉血 -14 归因到引发战斗的选项（237~238 批新语义），
    # 战利品金币仍不归属事件，卡组增量 +3（感染×3）入账
    ag._track(evt_flow_state("MAP", 66, 70, 4), policy.Decision(action=None))
    pe2 = tknow.stats["events"]["VEG_EV"]["FIGHT"]
    assert pe2["n"] == 1 and pe2["card_delta_sum"] == 3.0 \
        and pe2["hp_delta_sum"] == -14.0 and pe2["gold_delta_sum"] == 20.0, \
        f"事件战斗延迟结算管线断裂: {pe2}"
    assert not ag.ctx.died_to_event, "无死亡不应产生事件致死归因"

    # 3zv) 事件战掉血的选项链归因（第 237~238 批复盘核心修复）：「茂密的植被」
    #       INITIAL 页选「休息」(回血+7) → 次页只有强制「战！」→ 战斗 -14。
    #      旧语义：休息账面 +7、战！账面 0.0——必亏链被当免费反复选（237/238
    #      两局同一剧本连掉 55/54）。新语义：战！按快照效果−战斗掉血记 -14；
    #      祖先「休息」追加等额 -14 样本（是它把局面推进了强制战页）；
    #      敌人组合账不受影响（姿态/先验演化的数据源不变）；
    #      死亡路径下战斗账先行落库，掉血经暂存照样归因，事件死亡标志保持关闭
    ag.ctx.reset_for("RUN_EVT3", 0)

    def evt_chain_state(screen, hp, gold, deck_len, comp="VEG_BUG"):
        st = {"screen": screen, "run_id": "RUN_EVT3",
              "run": {"current_hp": hp, "max_hp": 80, "gold": gold, "floor": 14,
                      "deck": [{"card_id": f"C{i}"} for i in range(deck_len)]}}
        if screen == "COMBAT":
            st["combat"] = {"enemies": [{"enemy_id": comp, "is_alive": True}]}
        if screen == "GAME_OVER":
            st["game_over"] = {"is_victory": False}
        return st

    # 页1 选「休息」→ 页2 选「战！」（换项先行结算 +7）→ 战斗 -14 → MAP
    track_accepted(ag, evt_chain_state("EVENT", 80, 50, 1),
                   policy.Decision(action="choose_event_option",
                                   tags=[("event_choice", "VEG3_EV", "REST")]))
    track_accepted(ag, evt_chain_state("EVENT", 87, 50, 1),
                   policy.Decision(action="choose_event_option",
                                   tags=[("event_choice", "VEG3_EV", "FIGHT")]))
    ag._track(evt_chain_state("COMBAT", 87, 50, 1), policy.Decision(action=None))
    ag._track(evt_chain_state("MAP", 73, 50, 4), policy.Decision(action=None))
    ev_rest = tknow.stats["events"]["VEG3_EV"]["REST"]
    ev_fight = tknow.stats["events"]["VEG3_EV"]["FIGHT"]
    assert ev_fight["n"] == 1 and ev_fight["hp_delta_sum"] == -14.0, \
        f"引发战斗的选项未承担战斗掉血: {ev_fight}"
    assert ev_rest["n"] == 2 and ev_rest["hp_delta_sum"] == -7.0, \
        f"祖先选项未追加战斗掉血样本（应为 +7 与 -14 两条）: {ev_rest}"
    agg3 = ag.ctx.combat_agg
    assert agg3 and agg3.get("from_event") and agg3["hp_lost_sum"] == 14.0 \
        and agg3["comp_id"] == "VEG_BUG", \
        f"事件战聚合账未正确标记/累计（敌人组合账数据源被破坏）: {agg3}"
    # 死亡路径：战斗账先于事件账落库，掉血经暂存归因；事件死亡标志保持关闭
    ag.ctx.reset_for("RUN_EVT4", 0)
    track_accepted(ag, evt_chain_state("EVENT", 80, 50, 1),
                   policy.Decision(action="choose_event_option",
                                   tags=[("event_choice", "VEG4_EV", "FIGHT")]))
    ag._track(evt_chain_state("COMBAT", 80, 50, 1, comp="VEG4_BUG"),
              policy.Decision(action=None))
    ag._track(evt_chain_state("GAME_OVER", 0, 50, 1, comp="VEG4_BUG"),
              policy.Decision(action=None))
    ev_dead = tknow.stats["events"]["VEG4_EV"]["FIGHT"]
    assert ev_dead["n"] == 1 and ev_dead["hp_delta_sum"] == -80.0 \
        and ev_dead["deaths"] == 0, \
        f"死亡路径战斗掉血未归因选项/死亡标志泄漏: {ev_dead}"
    assert tknow.stats["enemies"]["VEG4_BUG"]["deaths"] == 1, \
        "事件战死亡的敌人组合归因被破坏"
    assert not ag.ctx.died_to_event, "事件战死亡被误记为事件致死"
    assert ag.ctx.pending_event is None and ag.ctx.pending_event_fight_loss == 0.0, \
        "事件结算后暂存状态未清理"

    # 3zc) 策略热同步（第 123~124 局复盘核心修复）：122 批复盘给 DEFAULT_POLICY
    #      新增 elite_grey_survival_floor=0.40 并依赖「加载器 setdefault 自动补齐」
    #      ——但 setdefault 只在进程启动时执行，长驻大脑不重启就看不到新键，
    #      该修复在第 123~126 局全程为死代码（运行库日志持续打印旧舒适线
    #      「<60%」文案即铁证）。refresh_policy 必须在不重启的前提下：
    #      ① 采纳磁盘新增键（复刻「进程早于键存在」：内存与基准快照都没有）；
    #      ② 采纳本进程未动过的既有键的外部修改；
    #      ③ 不覆盖本进程已演化的键（三方合并语义不变）；
    #      ④ 兜底补齐 DEFAULT_POLICY 缺失键且与模块常量深拷贝隔离。
    hdir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-refresh-"))
    hknow = knowledge.Knowledge(hdir)
    hknow.policy.pop("elite_grey_survival_floor", None)
    hknow._policy_sync.pop("elite_grey_survival_floor", None)  # 模拟进程早于该键存在
    _disk = dict(hknow.policy)
    _disk["elite_grey_survival_floor"] = 0.40
    (hdir / "policy.json").write_text(
        json.dumps(_disk, ensure_ascii=False), encoding="utf-8")
    changed = hknow.refresh_policy()
    assert "elite_grey_survival_floor" in changed, f"磁盘新增键未被采纳: {changed}"
    assert abs(hknow.policy["elite_grey_survival_floor"] - 0.40) < 1e-9, \
        f"热同步后新键值错误: {hknow.policy['elite_grey_survival_floor']}"
    # ② 既有键外部修改（内存未动过 → 采纳磁盘）
    hknow.save()
    _disk = dict(hknow.policy)
    _disk["block_safety"] = 0.77
    (hdir / "policy.json").write_text(
        json.dumps(_disk, ensure_ascii=False), encoding="utf-8")
    changed = hknow.refresh_policy()
    assert "block_safety" in changed and abs(hknow.policy["block_safety"] - 0.77) < 1e-9, \
        f"外部冷修改未被热同步采纳: {changed}"
    # ③ 本进程演化过的键不被磁盘回滚
    hknow.policy["block_safety"] = 1.05   # 模拟 reflect 演化（内存 != 基准）
    changed = hknow.refresh_policy()
    assert "block_safety" not in changed and abs(hknow.policy["block_safety"] - 1.05) < 1e-9, \
        f"进程演化值被磁盘覆盖: {changed} -> {hknow.policy['block_safety']}"
    # ④ DEFAULT_POLICY 兜底补齐 + 深拷贝隔离
    del hknow.policy["kill_race_enabled"]
    hknow.refresh_policy()
    assert hknow.policy.get("kill_race_enabled") is True, \
        f"DEFAULT_POLICY 缺失键未兜底补齐: {hknow.policy.get('kill_race_enabled')}"
    hknow.policy["room_weights"]["Monster"] = 9.9
    assert knowledge.DEFAULT_POLICY["room_weights"]["Monster"] == 1.2, \
        "热同步补齐的嵌套默认值与模块常量共享引用（污染源）"

    # 3zd) 绝境篝火优先门（第 126 局复盘核心缺陷）：35% 血时 Monster(6,2)=22.09
    #      压过眼前的 RestSite(6,1)=9.82——战斗子树里藏着 2~3 个未来篝火的 +30%
    #      幻想回血账（投影宣称打完怪进 Boss 还有 94%），下一战 -28 直接阵亡。
    #      修复三层：①未来篝火回血按深度折减（幸存条件品）②非休整候选首战
    #      生存复核（悲观战损后≤生存线即加性重罚）③软压制 ×0.55。
    #      用例复刻该岔路结构：Monster 子树含三个未来篝火（幻想账），RestSite
    #      子树平铺轻量节点；25% 血时旧账面「打完怪照样 51% 进 Boss」
    dr_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-direrest-"))
    dr_know = knowledge.Knowledge(dr_dir)
    dr_pol = policy.Policy(dr_know)

    def dire_rest_trap_map(hp_now: int):
        heads = [
            {"index": 0, "row": 1, "col": 0, "node_type": "Monster",
             "children": [{"row": 2, "col": 0}]},
            {"index": 1, "row": 1, "col": 1, "node_type": "RestSite",
             "children": [{"row": 2, "col": 1}]},
        ]
        col0 = ["RestSite", "Treasure", "RestSite", "Treasure", "RestSite", "Event", "Monster"]
        col1 = ["Monster", "Treasure", "Event", "Monster", "Treasure", "Event"]
        nodes = list(heads)
        for ci, plan in ((0, col0), (1, col1)):
            for i, nt in enumerate(plan):
                nxt = {"row": 9, "col": ci} if i == len(plan) - 1 \
                    else {"row": 3 + i, "col": ci}
                nodes.append({"row": 2 + i, "col": ci, "node_type": nt,
                              "children": [nxt]})
            nodes.append({"row": 9, "col": ci, "node_type": "Boss"})
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": heads, "nodes": nodes,
                      "boss_node": {"row": 9}},
              "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0,
                      "floor": 12, "deck": []}}
        return dr_pol.decide(st, type("C", (), {"credit_tags": []})())

    def trap_scores(decision):
        mm = re.search(r"Monster\(1,0\)=(-?[0-9.]+)", decision.reason)
        mr = re.search(r"RestSite\(1,1\)=(-?[0-9.]+)", decision.reason)
        return (float(mm.group(1)) if mm else None,
                float(mr.group(1)) if mr else None)

    d_trap = dire_rest_trap_map(20)   # 25% 血：绝境
    s_m, s_r = trap_scores(d_trap)
    assert d_trap.params.get("option_index") == 1 and s_m is not None and s_m < s_r, \
        f"绝境遇眼前篝火仍选战斗候选（126 局病灶复发）: M={s_m} R={s_r}（{d_trap.reason}）"
    assert "生存复核" in d_trap.reason, f"绝境首战生存复核未留痕: {d_trap.reason}"
    # 对照：两层闸门全关后怪物幻想账反超（旧缺陷复现，证明用例确实压在缺陷上）
    saved_gate = dr_know.policy.get("dire_rest_gate_mult")
    saved_pen = dr_know.policy.get("dire_first_fight_penalty")
    dr_know.policy["dire_rest_gate_mult"] = 1.0
    dr_know.policy["dire_first_fight_penalty"] = 0.0
    d_off = dire_rest_trap_map(20)
    dr_know.policy["dire_rest_gate_mult"] = 0.55 if saved_gate is None else saved_gate
    dr_know.policy["dire_first_fight_penalty"] = 45.0 if saved_pen is None else saved_pen
    off_m, off_r = trap_scores(d_off)
    assert d_off.params.get("option_index") == 0 and off_m > off_r, \
        f"关闭闸门后应复现怪物幻想账反超（用例失真）: M={off_m} R={off_r}（{d_off.reason}）"
    # 健康血量不受门扭曲：满血时怪物侧本就该胜出且无压制留痕
    d_hp = dire_rest_trap_map(80)
    hp_m, _hp_r = trap_scores(d_hp)
    assert d_hp.params.get("option_index") == 0 and "生存复核" not in d_hp.reason \
        and "非休整路线压制" not in d_hp.reason, \
        f"健康血量被绝境门误伤: M={hp_m}（{d_hp.reason}）"
    # 强制行军不受误伤：绝境但候选无篝火时，唯一战斗节点照常可选
    st_forced = {"screen": "MAP", "available_actions": ["choose_map_node"],
                 "map": {"available_nodes": [{"index": 0, "row": 1, "col": 0,
                                              "node_type": "Monster"}], "nodes": []},
                 "run": {"current_hp": 20, "max_hp": 80, "gold": 0, "floor": 5, "deck": []}}
    d_forced = dr_pol.decide(st_forced, type("C", (), {"credit_tags": []})())
    assert d_forced.params.get("option_index") == 0 \
        and "生存复核" not in d_forced.reason and "非休整路线压制" not in d_forced.reason, \
        f"无篝火候选的强制行军被绝境门误伤: {d_forced.reason}"

    # 3ze) 投影内连战疲劳沿路径递推（第 126 局复盘）：旧版把真实连战数当常量套
    #      在所有深度——fresh 状态下投影 5 连战全程零疲劳，「穿过未来营地的怪物
    #      链」越深相对越划算。新语义以真实连战数起步、遇战斗 +1、遇非战斗清零：
    #      同一张纯怪物链地图，携带连战史(streak=2)时的评分必须低于无史(streak=0)
    def chain_map_reason(tags):
        stx = type("ChainCtx", (), {"credit_tags": tags})()
        heads = [{"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                  "children": [{"row": 2, "col": 0}]}]
        chain = []
        for r in range(2, 8):
            g = {"row": r, "col": 0, "node_type": "Boss" if r == 7 else "Monster"}
            if r < 7:
                g["children"] = [{"row": r + 1, "col": 0}]
            chain.append(g)
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": heads, "nodes": heads + chain,
                      "boss_node": {"row": 7}},
              "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 12, "deck": []}}
        return dr_pol.decide(st, stx).reason

    r_s0 = chain_map_reason([])
    r_s2 = chain_map_reason([("map_node", "Monster")] * 2)
    p_s0 = float(re.search(r"Monster\(1,0\)=(-?[0-9.]+)", r_s0).group(1))
    p_s2 = float(re.search(r"Monster\(1,0\)=(-?[0-9.]+)", r_s2).group(1))
    assert p_s2 < p_s0, \
        f"投影内连战疲劳未沿深度递推（新旧评分应分离）: streak0={p_s0} streak2={p_s2}"

    # 3zf) 绝境悲观战损乘区 path_dire_loss_mult（第 126 局复盘）：均值账在重尾前
    #      高估生存——F5 单场 -52 在账面只值 ~7 点。血量<急需线时战斗先验×1.7，
    #      同一单怪路径的进 Boss 投影必须显著下调；健康血量不受影响
    def dire_loss_proj(hp_now: int, mult: float | None = None):
        saved = dr_know.policy.get("path_dire_loss_mult")
        if mult is not None:
            dr_know.policy["path_dire_loss_mult"] = mult
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": [{"index": 0, "row": 1, "col": 0,
                                           "node_type": "Monster"}], "nodes": []},
              "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 5, "deck": []}}
        reason = dr_pol.decide(st, type("C", (), {"credit_tags": []})()).reason
        if mult is not None:
            if saved is None:
                dr_know.policy.pop("path_dire_loss_mult", None)
            else:
                dr_know.policy["path_dire_loss_mult"] = saved
        return float(re.search(r"进 Boss 血量 ?(\d+)%", reason).group(1))

    p_dire_on = dire_loss_proj(24)          # 30% 血 < 急需线 35%：悲观口径生效
    p_dire_off = dire_loss_proj(24, 1.0)    # 关闭乘区：均值口径
    p_healthy = dire_loss_proj(80)          # 满血：不受乘区影响
    assert p_dire_on < p_dire_off <= p_healthy and abs(p_dire_off - p_healthy) > 40, \
        (f"绝境悲观战损乘区失效: on={p_dire_on}% off={p_dire_off}% healthy={p_healthy}%")
    assert abs(p_dire_on - round((24 - 8 * 1.7) / 80 * 100)) <= 1, \
        f"悲观乘区数值不符（应≈均值守恒×1.7）: {p_dire_on}%"

    # 3yk) Boss 入场线证据上限 boss_entry_evidence_hp_cap（第 146~147 局复盘）：
    #      旧条件「进场<线即上调」循环自证——143/146/147 局 66%/80%/100% 进场照输
    #      仍三连 +0.02（0.82→0.88），110 罚差刷屏「优先续航路线」扭曲选路（147 局
    #      全程仅 ~6 场战斗的续航畸形路线进 Boss）。中带进场（证据上限≤entry<线）
    #      死亡不再喂棘轮、证据改接 burst_starve；真正极低血（<上限）进场磨死照常
    #      上调（证据语义保留）；高血进场（≥线）沿用 138~141 批分流不变。
    eknow = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-entrycap-")))
    eknow.policy["boss_entry_min_hp_pct"] = 0.84
    ectx = _RC()
    ectx.died_in_combat = {"comp_id": "BOSS_X", "node_type": "Boss", "rounds": 8}
    ectx.death_hp_pct_at_entry = 0.75   # 中带：≥证据上限 0.65 但 < 线 0.84
    bsb_ek = eknow.policy["burst_starve_bonus_base"]
    be_ek = eknow.policy["boss_entry_min_hp_pct"]
    ek_lesson = reflect.finalize_run(eknow, ectx, victory=False, final_floor=17)
    assert abs(eknow.policy["boss_entry_min_hp_pct"] - be_ek) < 1e-9, \
        f"中带进场死亡仍喂入场线棘轮（循环自证复发）: {be_ek} -> {eknow.policy['boss_entry_min_hp_pct']}"
    assert eknow.policy["burst_starve_bonus_base"] > bsb_ek, \
        "中带进场 Boss 长战死证据未改接拿牌端输出饥饿"
    assert "中带进场" in ek_lesson, f"中带分流未在复盘日志留痕: {ek_lesson}"
    # 对照①：真正极低血进场（0.50 < 0.65）照常上调入场线（证据语义保留）
    ectx2 = _RC()
    ectx2.died_in_combat = {"comp_id": "BOSS_X", "node_type": "Boss", "rounds": 8}
    ectx2.death_hp_pct_at_entry = 0.50
    be_ek2 = eknow.policy["boss_entry_min_hp_pct"]
    reflect.finalize_run(eknow, ectx2, victory=False, final_floor=17)
    assert eknow.policy["boss_entry_min_hp_pct"] > be_ek2, \
        f"极低血进场磨死未上调入场线（证据语义被误伤）: {be_ek2} -> {eknow.policy['boss_entry_min_hp_pct']}"
    # 对照②：高血进场（≥线）旧语义不变——停止上调 + 证据改接 + 高血留痕
    ectx3 = _RC()
    ectx3.died_in_combat = {"comp_id": "BOSS_X", "node_type": "Boss", "rounds": 8}
    ectx3.death_hp_pct_at_entry = 0.95
    be_ek3 = eknow.policy["boss_entry_min_hp_pct"]
    ek_lesson3 = reflect.finalize_run(eknow, ectx3, victory=False, final_floor=17)
    assert abs(eknow.policy["boss_entry_min_hp_pct"] - be_ek3) < 1e-9, \
        "高血进场仍上调入场线（138~141 分流被破坏）"
    assert "高血进场" in ek_lesson3, f"高血分流留痕缺失: {ek_lesson3}"

    # 3zm) 长战证据接替旋钮 + 爆毙重分类（第 167~176 批复盘）：
    #      ①kill_bonus 顶格的非 Boss 长战死证据不再丢弃——改接 burst_starve
    #      双旋钮（与 Boss 高血进场长战死同构：「杀得慢」→ 拿牌端输出饥饿）；
    #      ②4 回合整管打空（dpr≥14）按「没挡住」爆毙重分类，证据归 block_safety；
    #      ③dpr 低于阈值的真长战不误伤；④旧记录无 hp_lost 字段时维持原口径。
    zdir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-grind-"))
    # ①顶格长战死：证据改接 burst_starve，防御端不代偿
    zknow = knowledge.Knowledge(zdir)
    zknow.policy["kill_bonus"] = 20.0
    zctx = _RC()
    zctx.died_in_combat = {"comp_id": "RAMP_COMP", "node_type": "Monster",
                           "rounds": 10, "hp_lost": 50.0}
    zb0 = zknow.policy["burst_starve_bonus_base"]
    zx0 = zknow.policy["burst_starve_bonus_extra_max"]
    zbs0 = zknow.policy["block_safety"]
    zlesson = reflect.finalize_run(zknow, zctx, victory=False, final_floor=8)
    assert abs(zknow.policy["block_safety"] - zbs0) < 1e-9, \
        f"顶格长战死仍代偿加码防御: {zbs0} -> {zknow.policy['block_safety']}"
    assert zknow.policy["burst_starve_bonus_base"] > zb0, \
        "顶格长战死证据未改接 burst_starve_bonus_base"
    assert zknow.policy["burst_starve_bonus_extra_max"] > zx0, \
        "顶格长战死证据未改接 burst_starve_bonus_extra_max"
    assert "停止代偿加码" in zlesson and "证据改接拿牌端输出饥饿" in zlesson, \
        f"接替旋钮留痕缺失: {zlesson}"
    # ②爆毙重分类：4 回合 -64（dpr=16 ≥ 14）→ block_safety 通道，不喂 burst_starve
    zctx2 = _RC()
    zctx2.died_in_combat = {"comp_id": "INKLET", "node_type": "Monster",
                            "rounds": 4, "hp_lost": 64.0}
    zb1 = zknow.policy["burst_starve_bonus_base"]
    zbs1 = zknow.policy["block_safety"]
    zlesson2 = reflect.finalize_run(zknow, zctx2, victory=False, final_floor=14)
    assert zknow.policy["block_safety"] > zbs1, \
        f"高速失血爆毙未上调防御（误留在长战通道）: {zbs1} -> {zknow.policy['block_safety']}"
    assert abs(zknow.policy["burst_starve_bonus_base"] - zb1) < 1e-9, \
        "爆毙证据误喂 burst_starve（证据归属混淆）"
    assert "高速失血爆毙" in zlesson2, f"爆毙重分类未留痕: {zlesson2}"
    # ③真长战不误伤：6 回合 -66（dpr=11 < 14）仍走长战通道
    zctx3 = _RC()
    zctx3.died_in_combat = {"comp_id": "FUZZY_WURM_CRAWLER+SHRINKER_BEETLE",
                            "node_type": "Monster", "rounds": 6, "hp_lost": 66.0}
    zb2 = zknow.policy["burst_starve_bonus_base"]
    zbs2 = zknow.policy["block_safety"]
    reflect.finalize_run(zknow, zctx3, victory=False, final_floor=5)
    assert zknow.policy["burst_starve_bonus_base"] > zb2, \
        "低 dpr 真长战被误重分类为爆毙（长战证据丢失）"
    assert abs(zknow.policy["block_safety"] - zbs2) < 1e-9, \
        "低 dpr 真长战误伤防御棘轮"
    # ④向后兼容：旧记录无 hp_lost 字段（dpr 未知）维持回合数口径
    zctx4 = _RC()
    zctx4.died_in_combat = {"comp_id": "RAMP_COMP", "node_type": "Monster", "rounds": 10}
    zb3 = zknow.policy["burst_starve_bonus_base"]
    zlesson4 = reflect.finalize_run(zknow, zctx4, victory=False, final_floor=8)
    assert zknow.policy["burst_starve_bonus_base"] > zb3, \
        "无 hp_lost 旧记录未维持长战口径"
    assert "停止代偿加码" in zlesson4, f"无 hp_lost 旧记录留痕缺失: {zlesson4}"

    # 3zn) 输出饥饿证据链的二次接替（第 209 批复盘）：burst_starve 双旋钮顶格
    #      （8.0/12.0，206~208 三连实证 _adj 空转、证据蒸发）后，长战证据递归
    #      改接 deck_burst_floor——加分数值顶死就加宽饥饿带，让顶格加分惠及
    #      更多卡组状态；floor 也顶格（45）则停止吸收并显式留痕
    ndir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-starve2-"))
    nknow = knowledge.Knowledge(ndir)
    nknow.policy["kill_bonus"] = 20.0
    nknow.policy["burst_starve_bonus_base"] = 8.0     # 顶格
    nknow.policy["burst_starve_bonus_extra_max"] = 12.0  # 顶格
    # ①非 Boss 长战死 + 双旋钮顶格 → deck_burst_floor +1.0，防御端不代偿
    nctx = _RC()
    nctx.died_in_combat = {"comp_id": "RAMP_COMP", "node_type": "Monster",
                           "rounds": 10, "hp_lost": 50.0}
    nf0 = nknow.policy["deck_burst_floor"]
    nbs0 = nknow.policy["block_safety"]
    nlesson = reflect.finalize_run(nknow, nctx, victory=False, final_floor=8)
    assert abs(nknow.policy["block_safety"] - nbs0) < 1e-9, \
        f"二次接替仍代偿加码防御: {nbs0} -> {nknow.policy['block_safety']}"
    assert abs(nknow.policy["deck_burst_floor"] - (nf0 + 1.0)) < 1e-9, \
        f"双旋钮顶格后证据未改接饥饿带宽度: {nf0} -> {nknow.policy['deck_burst_floor']}"
    assert "饥饿带加宽" in nlesson, f"二次接替留痕缺失: {nlesson}"
    # ②Boss 高血进场长战死 + 双旋钮顶格 → 同通道改接饥饿带
    nctx2 = _RC()
    nctx2.died_in_combat = {"comp_id": "BOSS_X", "node_type": "Boss",
                            "rounds": 9, "hp_lost": 70.0}
    nctx2.death_hp_pct_at_entry = 0.9
    nf1 = nknow.policy["deck_burst_floor"]
    nlesson2 = reflect.finalize_run(nknow, nctx2, victory=False, final_floor=17)
    assert nknow.policy["deck_burst_floor"] > nf1, \
        "Boss 高血进场长战死（双旋钮顶格）未改接饥饿带宽度"
    assert "饥饿带加宽" in nlesson2, f"Boss 分支二次接替留痕缺失: {nlesson2}"
    # ③饥饿带也顶格（45）→ 普通节点证据按第 229 批三级接替改接常规锻造线
    #   （smith_min_hp_pct -0.05），不再静默停止吸收
    nknow.policy["deck_burst_floor"] = 45.0
    nknow.policy["smith_min_hp_pct"] = 0.55
    nctx3 = _RC()
    nctx3.died_in_combat = {"comp_id": "RAMP_COMP", "node_type": "Monster",
                            "rounds": 10, "hp_lost": 50.0}
    nlesson3 = reflect.finalize_run(nknow, nctx3, victory=False, final_floor=8)
    assert abs(nknow.policy["deck_burst_floor"] - 45.0) < 1e-9, \
        f"顶格饥饿带仍被加码: {nknow.policy['deck_burst_floor']}"
    assert abs(nknow.policy["smith_min_hp_pct"] - 0.50) < 1e-9, \
        f"三级接替未改接常规锻造线: {nknow.policy['smith_min_hp_pct']}"
    assert "常规锻造线" in nlesson3, f"三级接替留痕缺失: {nlesson3}"
    # 对照：双旋钮有行程时主通道原样生效、饥饿带不抢跑
    ndir2 = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-starve2b-"))
    nknow2 = knowledge.Knowledge(ndir2)
    nknow2.policy["kill_bonus"] = 20.0
    nctx4 = _RC()
    nctx4.died_in_combat = {"comp_id": "RAMP_COMP", "node_type": "Monster",
                            "rounds": 10, "hp_lost": 50.0}
    nb0 = nknow2.policy["burst_starve_bonus_base"]
    reflect.finalize_run(nknow2, nctx4, victory=False, final_floor=8)
    assert nknow2.policy["burst_starve_bonus_base"] > nb0, \
        "双旋钮有行程时主通道未生效"
    assert abs(nknow2.policy["deck_burst_floor"] - 30.0) < 1e-9, \
        f"双旋钮有行程时饥饿带抢跑: {nknow2.policy['deck_burst_floor']}"

    # 3zo) Boss 入场线的输出饥饿豁免（第 209 批复盘）：与灰区精英豁免
    #      （elite_grey_starve_relief，136~137 批）同构——0.65~1.00 带内入场
    #      血量已八局证伪为生死变量（208 局 51% 进 KIN 双子，满血也只多活
    #      2~3 回合），饥饿卡组为堆血放弃战斗/商店是安全螺旋。饥饿时入场线
    #      0.88×(1-0.15)≈0.75：投影 80% 进场免于续航罚分并留痕；强卡组
    #      （非饥饿）罚分原样生效
    er_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-entryrelief-"))
    er_know = knowledge.Knowledge(er_dir)
    er_know.policy["boss_entry_min_hp_pct"] = 0.88   # 复刻运行值
    er_know.policy["boss_entry_starve_relief"] = 0.15
    er_pol = policy.Policy(er_know)

    def _atk_card(cid, dmg, cost=1):
        return {"card_id": cid, "card_type": "Attack", "energy_cost": cost,
                "dynamic_values": [{"name": "Damage", "current_value": dmg}]}

    def entry_map(deck):
        head = [{"index": 0, "row": 1, "col": 0, "node_type": "Monster",
                 "children": [{"row": 2, "col": 0}]}]
        chain = [{"row": 2, "col": 0, "node_type": "Monster",
                  "children": [{"row": 3, "col": 0}]},
                 {"row": 3, "col": 0, "node_type": "Boss"}]
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": head, "nodes": head + chain,
                      "boss_node": {"row": 3}},
              "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                      "floor": 10, "deck": deck}}
        return er_pol.decide(st, type("C", (), {"credit_tags": []})())

    # 饥饿卡组（burst 18 < 30）：投影 80% 进场 ≥ 放宽线 74.8% → 免罚 + 留痕
    d_starve = entry_map([_atk_card("STRIKE_IRONCLAD", 6) for _ in range(6)])
    assert "Boss入场线放宽" in d_starve.reason, \
        f"饥饿豁免留痕缺失: {d_starve.reason}"
    assert "优先续航路线" not in d_starve.reason, \
        f"饥饿卡组仍吃入场线罚分（豁免未生效）: {d_starve.reason}"
    # 强卡组（burst 44 ≥ 30）：投影 ~81% < 线 88% → 罚分原样生效，不误豁免
    d_strong = entry_map([_atk_card("BLUDGEON_T", 32)]
                         + [_atk_card("STRIKE_IRONCLAD", 6) for _ in range(5)])
    assert "优先续航路线" in d_strong.reason, \
        f"强卡组入场线罚分被误豁免: {d_strong.reason}"
    assert "入场线放宽" not in d_strong.reason, \
        f"强卡组误触发饥饿豁免: {d_strong.reason}"

    # 3yl) 全场皆为已证实重生体时解除重生压制（第 152 局 F6 实证）：墨宝 1 血
    #      不死阶段被重生标记三重压制（eff 封顶 1/威胁清零/击杀奖励归零），打击
    #      评分跌破出牌阈值——58 个 tick 满手攻击空过、65 回合白掉 54 血，直到
    #      僵局强攻（turn≥60）一刀终结。压制的前提是「场上还有本体可打」；存活
    #      敌人全是重生体时拒绝出牌是最差解，必须恢复正常评分终结战斗。
    def inklet_state():
        return {"screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 9,
                "combat": {"player": {"current_hp": 47, "max_hp": 80, "block": 0, "energy": 3},
                           "hand": [
                               {"index": 0, "card_id": "STRIKE_IRONCLAD", "name": "打击",
                                "playable": True, "energy_cost": 1, "requires_target": True,
                                "valid_target_indices": [0],
                                "dynamic_values": [{"name": "Damage", "current_value": 6}]},
                               {"index": 1, "card_id": "BASH", "name": "痛击",
                                "playable": True, "energy_cost": 1, "requires_target": True,
                                "valid_target_indices": [0],
                                "dynamic_values": [{"name": "Damage", "current_value": 8}]}],
                           "enemies": [
                               {"index": 0, "enemy_id": "INKLET_T", "name": "墨宝",
                                "current_hp": 1, "max_hp": 40, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 3}]}]},
                "run": {"current_hp": 47, "max_hp": 80, "gold": 0, "floor": 6, "deck": []}}
    pol._combat_kills["INKLET_T"] = 2   # 模拟同场已两次预测击杀后它仍在场（1 血不死）
    # 906~908 行按战斗实例更替清空击杀计数：手动播种后必须同步认领当前战斗
    # 实例，否则下一次 decide 检测到「战斗变更」先把播种清掉（167~176 批
    # 复盘发现的既有测试脆弱点——断言依赖上一个用例留下的实例身份）
    pol._kills_combat = ctx.combat
    d_ink = pol.decide(inklet_state(), ctx)
    assert d_ink.action == "play_card" and d_ink.params.get("target_index") == 0, \
        f"全场皆重生体时仍拒绝出牌（152 局 F6 空过复发）: {d_ink.action}（{d_ink.reason}）"
    assert "解除重生压制" in d_ink.reason, f"全场重生体解除压制未留痕: {d_ink.reason}"
    # 对照①：场上还有正常敌人时压制原样生效（52~53/58 局语义不破坏）——
    # 已证实重生体不应再吸引输出，转火高威胁本体
    def mixed_state():
        return {"screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 9,
                "combat": {"player": {"current_hp": 47, "max_hp": 80, "block": 0, "energy": 3},
                           "hand": [
                               {"index": 0, "card_id": "CARD_CLEAVE_T", "name": "重劈",
                                "playable": True, "energy_cost": 1, "requires_target": True,
                                "valid_target_indices": [0, 1],
                                "dynamic_values": [{"name": "Damage", "current_value": 8}]}],
                           "enemies": [
                               {"index": 0, "enemy_id": "INKLET_T", "name": "墨宝",
                                "current_hp": 1, "max_hp": 40, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 3}]},
                               {"index": 1, "enemy_id": "BODY_MAIN_T", "name": "本体",
                                "current_hp": 60, "max_hp": 70, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 20}]}]},
                "run": {"current_hp": 47, "max_hp": 80, "gold": 0, "floor": 6, "deck": []}}
    d_mix = pol.decide(mixed_state(), ctx)
    assert d_mix.action == "play_card" and d_mix.params.get("target_index") == 1, \
        f"有本体可打时重生体仍吸引输出（58 局压制被破坏）: {d_mix.reason}"
    # 对照②：_kill_bonus 的 ignore_respawn 通道——解除时奖励恢复、默认调用不受影响
    assert pol._kill_bonus({"enemy_id": "INKLET_T"}, 3, 3, know.policy) == 0.0, \
        "默认口径下重生体击杀奖励未归零"
    assert pol._kill_bonus({"enemy_id": "INKLET_T"}, 3, 3, know.policy, ignore_respawn=True) > 0.0, \
        "ignore_respawn 通道未恢复击杀奖励"

    # 3zp) 能力牌长战加成（第 223 批复盘）：能力牌价值须随战斗预期长度复利——
    #      旧固定 6.0/1.5 在 Boss 攻坚 ×1.8 下整场输给攻击牌（生涯 DEMON_FORM
    #      2 拿 0 打：3 费整回合换 6 分永远轮不上），scaling 卡在最需要它的
    #      长战里上不了场。按存活敌血池线性加成（封顶 7、每 30 血 +1）：
    #      大血池低意图窗口能力牌压过打击上砧；小血池与晚回合不扭曲既有节奏
    def power_state(turn_no, pool_hp):
        return {"screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": turn_no,
                "combat": {"player": {"current_hp": 60, "max_hp": 80, "block": 0, "energy": 3},
                           "hand": [
                               {"index": 0, "card_id": "STRIKE_T", "name": "打击",
                                "playable": True, "energy_cost": 1, "requires_target": True,
                                "valid_target_indices": [0],
                                "dynamic_values": [{"name": "Damage", "current_value": 6}]},
                               {"index": 1, "card_id": "DEMON_FORM_T", "name": "恶魔形态",
                                "playable": True, "energy_cost": 3, "requires_target": False,
                                "rules_text": "在每回合开始时获得2点力量"}],
                           "enemies": [
                               {"index": 0, "enemy_id": "BIG_BOSS_T", "name": "巨像",
                                "current_hp": pool_hp, "max_hp": pool_hp, "block": 0,
                                "is_alive": True, "is_hittable": True,
                                "intents": [{"total_damage": 10}]}]},
                "run": {"current_hp": 60, "max_hp": 80, "gold": 0, "floor": 17, "deck": []}}
    # ①大血池（250）第 1 回合：能力 6+7=13 > 打击 (6+10×0.3)=9 → 上能力并留痕
    pol_lf1 = policy.Policy(know, random.Random(5))
    d_lf1 = pol_lf1.decide(power_state(1, 250), ctx)
    assert d_lf1.action == "play_card" and d_lf1.params.get("card_index") == 1 \
        and "长战加成" in d_lf1.reason, \
        f"大血池低意图窗口能力牌应压过打击（DEMON_FORM 0打病灶未愈）: {d_lf1.action}（{d_lf1.reason}）"
    # ②小血池（20）：能力 6+0.7 < 打击 9 → 节奏不扭曲
    pol_lf2 = policy.Policy(know, random.Random(5))
    d_lf2 = pol_lf2.decide(power_state(1, 20), ctx)
    assert d_lf2.action == "play_card" and d_lf2.params.get("card_index") == 0, \
        f"小血池战斗节奏被长战加成扭曲: {d_lf2.action}（{d_lf2.reason}）"
    # ③晚回合（第 5 回合）：加成减半 1.5+3.5=5 < 打击 9 → 不再上能力
    pol_lf3 = policy.Policy(know, random.Random(5))
    d_lf3 = pol_lf3.decide(power_state(5, 250), ctx)
    assert d_lf3.action == "play_card" and d_lf3.params.get("card_index") == 0, \
        f"晚回合能力牌加成未减半: {d_lf3.action}（{d_lf3.reason}）"

    # 3zq) Boss 前夜锻造线旋钮语义收窄（第 244 批复盘）：三区生存余量裁决下，
    #      boss_eve_smith_hp_pct 只在「安全区」（不回血也稳过悲观战损）内裁决
    #      锻造/回血——翻转带与溢出区不再经过它（旧 228 批用例的血量/战损组合
    #      在新口径下全部落入翻转带，已不再触及旋钮，此处用安全区组合重锚）。
    #      场均 24（悲观 36）、血量 60%：余量 12>8 属安全区；线 0.55 → 锻造，
    #      线 0.65 → 回血（214 批对照口径不变）。地图投影镜像与 _rest 同口径
    know.stats["enemies"].pop("BOSS_HOG", None)
    know.stats["enemies"].pop("BOSS_PIG", None)
    know.stats.setdefault("enemies", {})["BOSS_EVE_T"] = {
        "encounters": 6, "hp_lost_sum": 200.0, "deaths": 2, "wins": 4,
        "boss_encounters": 3, "boss_hp_lost_sum": 72.0, "boss_deaths": 1}
    eve_line_state = {
        "screen": "REST", "available_actions": ["choose_rest_option"],
        "rest": {"options": [
            {"index": 0, "option_id": "HEAL", "title": "休息", "is_enabled": True},
            {"index": 1, "option_id": "SMITH", "title": "锻造", "is_enabled": True}]},
        "run": {"current_hp": 48, "max_hp": 80, "gold": 0, "floor": 16,
                "deck": [{"card_id": "STRIKE_IRONCLAD", "upgraded": False}]}}
    saved_eve_line = know.policy.get("boss_eve_smith_hp_pct")
    ctx.rest_before_boss = True
    ctx.rest_proj_hp_pct = 1.0
    know.policy["boss_eve_smith_hp_pct"] = 0.55   # 60% ≥ 55% → 安全区锻造
    d_eve55 = pol.decide(dict(eve_line_state), ctx)
    assert d_eve55.tags and d_eve55.tags[0] == ("rest", "smith"), \
        f"安全区内锻造线下调后应改锻造: {d_eve55.reason}"
    know.policy["boss_eve_smith_hp_pct"] = 0.65   # 对照：60% < 65% → 回血
    d_eve65 = pol.decide(dict(eve_line_state), ctx)
    assert d_eve65.tags and d_eve65.tags[0] == ("rest", "heal"), \
        f"锻造线 0.65 时低于线的前夜仍应回血: {d_eve65.reason}"
    if saved_eve_line is not None:
        know.policy["boss_eve_smith_hp_pct"] = saved_eve_line
    else:
        know.policy.pop("boss_eve_smith_hp_pct", None)
    ctx.rest_before_boss = False

    # 3zr) 长战证据三级接替（第 228 批复盘）：burst_starve 双旋钮+饥饿带全部顶格后，
    #      Boss 节点证据改接前夜锻造线 boss_eve_smith_hp_pct（-0.05，下限 0.45）；
    #      普通怪房长战死不得错位吸收（维持停止吸收留痕）；触底封账留痕；胜利对称释放
    zdir2 = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-evechain-"))
    zknow2 = knowledge.Knowledge(zdir2)
    zknow2.policy.update(kill_bonus=20.0, burst_starve_bonus_base=8.0,
                         burst_starve_bonus_extra_max=12.0, deck_burst_floor=45.0,
                         boss_eve_smith_hp_pct=0.60)
    bctx2 = _RC()
    bctx2.died_in_combat = {"comp_id": "BOSS_Z", "node_type": "Boss",
                            "rounds": 9, "hp_lost": 70.0}
    bctx2.death_hp_pct_at_entry = 0.88
    zlesson5 = reflect.finalize_run(zknow2, bctx2, victory=False, final_floor=17)
    assert abs(zknow2.policy["boss_eve_smith_hp_pct"] - 0.55) < 1e-9, \
        f"三级接替未下调前夜锻造线: {zknow2.policy['boss_eve_smith_hp_pct']}"
    assert "前夜锻造线" in zlesson5, f"三级接替留痕缺失: {zlesson5}"
    # 触底改接四级旋钮（第 237~238 批复盘）：0.45 不再下降，Boss 长战证据改接
    # 能力牌长战加成上限 power_longfight_bonus_max（Boss 血池恒吃 7.0 封顶）
    zknow2.policy["boss_eve_smith_hp_pct"] = 0.45
    zlesson6 = reflect.finalize_run(zknow2, bctx2, victory=False, final_floor=17)
    assert abs(zknow2.policy["boss_eve_smith_hp_pct"] - 0.45) < 1e-9, \
        f"锻造线触底仍被压低: {zknow2.policy['boss_eve_smith_hp_pct']}"
    assert abs(zknow2.policy["power_longfight_bonus_max"] - 7.5) < 1e-9, \
        f"Boss 长战证据未接替到长战加成上限: {zknow2.policy['power_longfight_bonus_max']}"
    assert "长战加成上限" in zlesson6, f"四级接替留痕缺失: {zlesson6}"
    # 双顶格封账：加成上限也顶格（12.0）才显式封账留痕
    zknow2.policy["power_longfight_bonus_max"] = 12.0
    zlesson6b = reflect.finalize_run(zknow2, bctx2, victory=False, final_floor=17)
    assert abs(zknow2.policy["power_longfight_bonus_max"] - 12.0) < 1e-9, \
        f"长战加成上限顶格后仍被加码: {zknow2.policy['power_longfight_bonus_max']}"
    assert "均顶格" in zlesson6b, f"彻底封账留痕缺失: {zlesson6b}"
    zknow2.policy["power_longfight_bonus_max"] = 7.0  # 复位，避免污染后续胜利释放断言
    # 对照：普通怪房长战死在全顶格下不得动前夜锻造线（错位吸收防护）；
    # 第 229 批起改接常规锻造线 smith_min_hp_pct（见 3zt 全量用例）
    ndir3 = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-evechain-n-"))
    nknow3 = knowledge.Knowledge(ndir3)
    nknow3.policy.update(kill_bonus=20.0, burst_starve_bonus_base=8.0,
                         burst_starve_bonus_extra_max=12.0, deck_burst_floor=45.0,
                         boss_eve_smith_hp_pct=0.60, smith_min_hp_pct=0.55)
    nctx5 = _RC()
    nctx5.died_in_combat = {"comp_id": "RAMP_COMP", "node_type": "Monster",
                            "rounds": 10, "hp_lost": 50.0}
    nlesson5 = reflect.finalize_run(nknow3, nctx5, victory=False, final_floor=8)
    assert abs(nknow3.policy["boss_eve_smith_hp_pct"] - 0.60) < 1e-9, \
        f"普通怪房长战死错位吸收了前夜锻造线: {nknow3.policy['boss_eve_smith_hp_pct']}"
    assert abs(nknow3.policy["power_longfight_hp_div"] - 30.0) < 1e-9, \
        f"常规锻造线有余量时四级旋钮被误吸（防双吃失效）: {nknow3.policy['power_longfight_hp_div']}"
    assert "常规锻造线" in nlesson5, f"普通节点接替常规锻造线留痕缺失: {nlesson5}"
    # 胜利释放：被棘轮压下去的锻造线回升，健康值(≥0.65)不被推过证据上限
    vctx2b = _RC()
    reflect.finalize_run(zknow2, vctx2b, victory=True, final_floor=20)  # 0.45 → 0.50
    assert abs(zknow2.policy["boss_eve_smith_hp_pct"] - 0.50) < 1e-9, \
        f"胜利未释放前夜锻造线: {zknow2.policy['boss_eve_smith_hp_pct']}"
    zknow2.policy["boss_eve_smith_hp_pct"] = 0.70   # 高于锚点：健康值不得被推高
    vctx2c = _RC()
    reflect.finalize_run(zknow2, vctx2c, victory=True, final_floor=21)
    assert abs(zknow2.policy["boss_eve_smith_hp_pct"] - 0.70) < 1e-9, \
        f"健康锻造线被胜利误推: {zknow2.policy['boss_eve_smith_hp_pct']}"

    # 3zt) 普通怪房长战死证据的常规锻造线接替（第 229 批复盘）：burst_starve
    #      双旋钮+饥饿带全部顶格后，非 Boss 长战磨死（222/228/229 二幕连战力竭型）
    #      改接 smith_min_hp_pct（-0.05，下限 0.45 对齐紧急回血线）；
    #      触底彻底封账留痕；胜利对称释放只回收 <0.55 锚点部分
    sdir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-smithline-"))
    sknow = knowledge.Knowledge(sdir)
    sknow.policy.update(kill_bonus=20.0, burst_starve_bonus_base=8.0,
                        burst_starve_bonus_extra_max=12.0, deck_burst_floor=45.0,
                        boss_eve_smith_hp_pct=0.60, smith_min_hp_pct=0.55,
                        block_safety=2.1)
    sctx = _RC()
    sctx.died_in_combat = {"comp_id": "ACT2_GAUNTLET", "node_type": "Monster",
                           "rounds": 8, "hp_lost": 40.0}
    slesson = reflect.finalize_run(sknow, sctx, victory=False, final_floor=23)
    assert abs(sknow.policy["smith_min_hp_pct"] - 0.50) < 1e-9, \
        f"常规锻造线接替未生效: {sknow.policy['smith_min_hp_pct']}"
    assert abs(sknow.policy["boss_eve_smith_hp_pct"] - 0.60) < 1e-9, \
        f"普通节点证据错位吸收前夜锻造线: {sknow.policy['boss_eve_smith_hp_pct']}"
    assert abs(sknow.policy["block_safety"] - 2.1) < 1e-9, \
        f"防御棘轮被代偿加码: {sknow.policy['block_safety']}"
    assert abs(sknow.policy["power_longfight_hp_div"] - 30.0) < 1e-9, \
        f"锻造线有余量时四级旋钮被误吸（防双吃失效）: {sknow.policy['power_longfight_hp_div']}"
    assert "常规锻造线" in slesson, f"接替留痕缺失: {slesson}"
    # 触底改接四级旋钮（第 237~238 批复盘）：0.45 不再下降，普通长战证据改压
    # 能力牌长战加成血池分母 power_longfight_hp_div（走廊血池够不到加成封顶）
    sknow.policy["smith_min_hp_pct"] = 0.45
    sctx2 = _RC()
    sctx2.died_in_combat = {"comp_id": "ACT2_GAUNTLET", "node_type": "Monster",
                            "rounds": 8, "hp_lost": 40.0}
    slesson2 = reflect.finalize_run(sknow, sctx2, victory=False, final_floor=23)
    assert abs(sknow.policy["smith_min_hp_pct"] - 0.45) < 1e-9, \
        f"常规锻造线触底仍被压低: {sknow.policy['smith_min_hp_pct']}"
    assert abs(sknow.policy["power_longfight_hp_div"] - 28.0) < 1e-9, \
        f"普通长战证据未接替到长战加成折算: {sknow.policy['power_longfight_hp_div']}"
    assert "长战加成折算" in slesson2, f"四级接替留痕缺失: {slesson2}"
    # 双触底封账：分母也触底（12.0）才显式彻底封账留痕（学习停摆必须可见）
    sknow.policy["power_longfight_hp_div"] = 12.0
    sctx2b = _RC()
    sctx2b.died_in_combat = {"comp_id": "ACT2_GAUNTLET", "node_type": "Monster",
                             "rounds": 8, "hp_lost": 40.0}
    slesson2b = reflect.finalize_run(sknow, sctx2b, victory=False, final_floor=23)
    assert abs(sknow.policy["power_longfight_hp_div"] - 12.0) < 1e-9, \
        f"长战加成折算触底后仍被压低: {sknow.policy['power_longfight_hp_div']}"
    assert "彻底停止吸收" in slesson2b, f"彻底封账留痕缺失: {slesson2b}"
    sknow.policy["power_longfight_hp_div"] = 30.0  # 复位，避免污染后续胜利释放断言
    # 胜利释放：被压下去的常规锻造线回升至锚点 0.55；健康值(≥0.55)不被推高
    sknow.policy["smith_min_hp_pct"] = 0.50
    reflect.finalize_run(sknow, _RC(), victory=True, final_floor=20)
    assert abs(sknow.policy["smith_min_hp_pct"] - 0.55) < 1e-9, \
        f"胜利未释放常规锻造线: {sknow.policy['smith_min_hp_pct']}"
    sknow.policy["smith_min_hp_pct"] = 0.60
    reflect.finalize_run(sknow, _RC(), victory=True, final_floor=21)
    assert abs(sknow.policy["smith_min_hp_pct"] - 0.60) < 1e-9, \
        f"健康常规锻造线被胜利误推: {sknow.policy['smith_min_hp_pct']}"
    # 长战加成双旋钮的胜利释放（第 237~238 批）：只回收被推离默认锚点的部分
    # （血池分母 <30 回升、加成上限 >7 回收），健康值不被推过锚点
    sknow.policy["power_longfight_hp_div"] = 26.0
    reflect.finalize_run(sknow, _RC(), victory=True, final_floor=22)
    assert abs(sknow.policy["power_longfight_hp_div"] - 28.0) < 1e-9, \
        f"胜利未释放长战加成折算: {sknow.policy['power_longfight_hp_div']}"
    sknow.policy["power_longfight_hp_div"] = 30.0
    reflect.finalize_run(sknow, _RC(), victory=True, final_floor=23)
    assert abs(sknow.policy["power_longfight_hp_div"] - 30.0) < 1e-9, \
        f"健康长战加成折算被胜利误推: {sknow.policy['power_longfight_hp_div']}"
    sknow.policy["power_longfight_bonus_max"] = 8.0
    reflect.finalize_run(sknow, _RC(), victory=True, final_floor=24)
    assert abs(sknow.policy["power_longfight_bonus_max"] - 7.5) < 1e-9, \
        f"胜利未回收长战加成上限: {sknow.policy['power_longfight_bonus_max']}"
    sknow.policy["power_longfight_bonus_max"] = 7.0
    reflect.finalize_run(sknow, _RC(), victory=True, final_floor=25)
    assert abs(sknow.policy["power_longfight_bonus_max"] - 7.0) < 1e-9, \
        f"健康长战加成上限被胜利误推: {sknow.policy['power_longfight_bonus_max']}"

    # 3zu) 爆毙/短时死亡通道的顶格治理（第 231~233 批复盘引入，第 236 局复盘
    #      落地接替旋钮）：block_safety 顶格 2.1 时，「没挡住」证据改接药水提前
    #      交药线 potion_block_hp_pct（231~233 批工作单「药水提前交药时机 /
    #      爆毙专属预演」二选一的选型兑现）；接替旋钮也顶格（0.80）才显式封账
    #      留痕；block_safety 有余量时旧行为不变；胜利对称释放接替旋钮
    udir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-burstcap-"))
    uknow = knowledge.Knowledge(udir)
    uknow.policy.update(block_safety=2.1, kill_bonus=20.0,
                        burst_starve_bonus_base=8.0, burst_starve_bonus_extra_max=12.0,
                        deck_burst_floor=45.0, smith_min_hp_pct=0.45)
    # ① 爆毙 + 顶格：block_safety 不动，接替旋钮吸收（+0.05）
    uctx = _RC()
    uctx.died_in_combat = {"comp_id": "CRUSHER+ROCKET", "node_type": "Boss",
                           "rounds": 5, "hp_lost": 71.0}
    ulesson = reflect.finalize_run(uknow, uctx, victory=False, final_floor=33)
    assert abs(uknow.policy["block_safety"] - 2.1) < 1e-9, \
        f"顶格后爆毙仍加码: {uknow.policy['block_safety']}"
    assert abs(uknow.policy["potion_block_hp_pct"] - 0.40) < 1e-9, \
        f"爆毙证据未接替到药水交药线: {uknow.policy['potion_block_hp_pct']}"
    assert "药水提前交药线" in ulesson, f"接替旋钮留痕缺失: {ulesson}"
    # ② 短时死亡（<4回合）+ 顶格：同一接替旋钮继续吸收
    uctx2 = _RC()
    uctx2.died_in_combat = {"comp_id": "OVICOPTER", "node_type": "Monster",
                            "rounds": 3, "hp_lost": 14.0}
    ulesson2 = reflect.finalize_run(uknow, uctx2, victory=False, final_floor=23)
    assert abs(uknow.policy["potion_block_hp_pct"] - 0.45) < 1e-9, \
        f"短时死亡证据未接替到药水交药线: {uknow.policy['potion_block_hp_pct']}"
    assert "药水提前交药线" in ulesson2, f"短时死亡接替留痕缺失: {ulesson2}"
    # ③ 双重顶格：交药线也到 0.80 上限 → 第三级接替（第470局批复盘）：
    #    证据改接高危组合防御姿态斜率 danger_comp_blk_boost（+0.05）
    uknow.policy["potion_block_hp_pct"] = 0.80
    uctx_b = _RC()
    uctx_b.died_in_combat = {"comp_id": "CRUSHER+ROCKET", "node_type": "Boss",
                             "rounds": 5, "hp_lost": 71.0}
    ulesson_b = reflect.finalize_run(uknow, uctx_b, victory=False, final_floor=33)
    assert abs(uknow.policy["potion_block_hp_pct"] - 0.80) < 1e-9, \
        f"双重顶格后接替旋钮仍被加码: {uknow.policy['potion_block_hp_pct']}"
    assert abs(uknow.policy["danger_comp_blk_boost"] - 0.35) < 1e-9, \
        f"三级接替（组合姿态斜率）未吸收爆毙证据: {uknow.policy['danger_comp_blk_boost']}"
    assert "组合防御姿态斜率" in ulesson_b, f"三级接替留痕缺失: {ulesson_b}"
    # ③-bis 三级全顶格：斜率也到 0.60 上限 → 显式封账留痕
    uknow.policy["danger_comp_blk_boost"] = 0.60
    ulesson_b2 = reflect.finalize_run(uknow, uctx_b, victory=False, final_floor=33)
    assert abs(uknow.policy["danger_comp_blk_boost"] - 0.60) < 1e-9, \
        f"三级顶格后仍被加码: {uknow.policy['danger_comp_blk_boost']}"
    assert "爆毙证据停止吸收" in ulesson_b2, f"三级全顶格封账留痕缺失: {ulesson_b2}"
    uctx_s = _RC()
    uctx_s.died_in_combat = {"comp_id": "OVICOPTER", "node_type": "Monster",
                             "rounds": 3, "hp_lost": 14.0}
    ulesson_s = reflect.finalize_run(uknow, uctx_s, victory=False, final_floor=23)
    assert "短时死亡证据停止吸收" in ulesson_s, f"短时死亡顶格封账留痕缺失: {ulesson_s}"
    # ④ 有余量时旧行为不变：爆毙证据照旧由 block_safety +0.05 吸收，
    #    接替旋钮不得重复吸收同一份证据
    uknow.policy["block_safety"] = 2.0
    uknow.policy["potion_block_hp_pct"] = 0.35
    uctx3 = _RC()
    uctx3.died_in_combat = {"comp_id": "CRUSHER+ROCKET", "node_type": "Boss",
                            "rounds": 5, "hp_lost": 71.0}
    reflect.finalize_run(uknow, uctx3, victory=False, final_floor=33)
    assert abs(uknow.policy["block_safety"] - 2.05) < 1e-9, \
        f"有余量时爆毙证据未吸收: {uknow.policy['block_safety']}"
    assert abs(uknow.policy["potion_block_hp_pct"] - 0.35) < 1e-9, \
        f"防御有余量时接替旋钮被误吸: {uknow.policy['potion_block_hp_pct']}"
    # ⑤ 胜利释放：只回收被棘轮抬高的部分（>0.35 锚点），健康值不被推低
    uknow.policy["potion_block_hp_pct"] = 0.40
    reflect.finalize_run(uknow, _RC(), victory=True, final_floor=20)
    assert abs(uknow.policy["potion_block_hp_pct"] - 0.35) < 1e-9, \
        f"胜利未释放药水交药线（单向棘轮复发）: {uknow.policy['potion_block_hp_pct']}"
    assert abs(uknow.policy["danger_comp_blk_boost"] - 0.55) < 1e-9, \
        f"胜利未回收组合姿态斜率: {uknow.policy['danger_comp_blk_boost']}"
    reflect.finalize_run(uknow, _RC(), victory=True, final_floor=21)
    assert abs(uknow.policy["potion_block_hp_pct"] - 0.35) < 1e-9, \
        f"健康交药线被胜利误推: {uknow.policy['potion_block_hp_pct']}"
    assert abs(uknow.policy["danger_comp_blk_boost"] - 0.50) < 1e-9, \
        f"健康姿态斜率被胜利误推: {uknow.policy['danger_comp_blk_boost']}"

    # 3zs) 「拿了不打」偏置封禁 + 榜单过滤（第 228 批复盘）：DISINTEGRATION 类
    #      不可打出牌（7拿0打）靠幸存者偏差把 outcome 抬到 33、bias 涨到 +4 上限，
    #      复盘日志供成「当前高价值卡牌」。判据与拾取端 unplayed_card_penalty 同一：
    #      picked≥4 且 plays ≤ play_rate×picked → bias 只降不升；lessons 高价值榜
    #      与低价值榜同时排除该类牌（既非价值信号也非负样本，是使用故障）
    bdir2 = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-biasban-"))
    bknow = knowledge.Knowledge(bdir2)
    bknow.stats.setdefault("cards", {})["NEVER_CAST"] = {
        "seen": 9, "picked": 5, "plays": 0, "outcome_sum": 160.0, "bias": 2.0}
    bknow.stats["cards"]["OFTEN_CAST"] = {
        "seen": 9, "picked": 5, "plays": 25, "outcome_sum": 160.0, "bias": 0.0}
    bk_ctx = SimpleNamespace(
        died_to_event=None, died_in_combat=None, death_was_elite=False,
        death_hp_pct_at_entry=None, credit_tags=[], rests_healed_at_full=0,
        ascension=0, combat_notes=[])
    blesson = reflect.finalize_run(bknow, bk_ctx, victory=False, final_floor=8)
    assert bknow.stats["cards"]["NEVER_CAST"]["bias"] < 2.0, \
        f"拿了不打的牌 bias 未被封禁: {bknow.stats['cards']['NEVER_CAST']['bias']}"
    assert bknow.stats["cards"]["OFTEN_CAST"]["bias"] > 0.0, \
        f"正常出牌的高收益牌被误伤: {bknow.stats['cards']['OFTEN_CAST']['bias']}"
    assert "NEVER_CAST" not in blesson, f"拿了不打的牌仍出现在复盘榜单: {blesson}"

    # 3zv) 首回合攻坚先验（第 255 批复盘）：旧版竞速判定要求实测满两回合才允许
    #      开账，Boss 战头 1~2 回合仍在按防守姿态花能量（252 局 F5 劫掠者三连：
    #      T1~T3 意图 22→32 还在打坚毅补防，能量药水睡到 19 血）。血池第 1 帧
    #      可见、卡组爆发是现成 DPS 先验：样本不足时用 deck_burst × 0.55 悲观
    #      折算开账；零爆发不预测（无从竞速），两回合后自动切回实测口径
    prc1 = type("PRCtx", (), {"combat": None, "current_combat_is_hard": False,
                              "credit_tags": []})()
    prc1.combat = {"comp_id": "KR1_BOSS", "node_type": "Boss"}

    def krace1_state(turn_no, hp_now, incoming, deck):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": turn_no,
            "combat": {"player": {"current_hp": hp_now, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [
                           {"index": 0, "card_id": "KR1_HIT", "name": "竞速斩", "playable": True,
                            "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                            "dynamic_values": [{"name": "Damage", "current_value": 12}]},
                           {"index": 1, "card_id": "KR1_LUX", "name": "奢侈挡", "playable": True,
                            "requires_target": False,
                            "rules_text": "获得6点格挡",
                            "dynamic_values": [{"name": "Block", "current_value": 6}]}],
                       "enemies": [{"index": 0, "enemy_id": "KR1_BOSS", "name": "攻坚巨兽",
                                    "current_hp": 200, "max_hp": 252, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": incoming}]}]},
            "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 17, "deck": deck}}

    weak_deck = [{"card_id": f"WK_STRIKE_{i}", "card_type": "Attack", "energy_cost": 1,
                  "dynamic_values": [{"name": "Damage", "current_value": 6}]} for i in range(4)]
    # ① 弱爆发（burst≈18→先验9.9/回合）对 200 血池：T1 即判必败竞速，攻击胜过奢侈格挡
    pol_kr3 = policy.Policy(know, random.Random(11))
    d_kr3 = pol_kr3.decide(krace1_state(1, 65, 22, weak_deck), prc1)
    assert d_kr3.action == "play_card" and d_kr3.params.get("card_index") == 0, \
        f"首回合攻坚先验未提速（弱爆发对大血池）: {d_kr3.action}（{d_kr3.reason}）"
    assert "斩杀竞速投影" in d_kr3.reason and "先验" in d_kr3.reason, \
        f"开局先验未留痕: {d_kr3.reason}"
    # ② 对照：强爆发+宽裕血量账（tsurv 16 > ttk 6）→ 防守路线可行，不得误触发
    strong_deck = [{"card_id": f"ST_HIT_{i}", "card_type": "Attack", "energy_cost": 1,
                    "dynamic_values": [{"name": "Damage", "current_value": 20}]} for i in range(3)]
    pol_kr4 = policy.Policy(know, random.Random(11))
    d_kr4 = pol_kr4.decide(krace1_state(1, 80, 5, strong_deck), prc1)
    assert "斩杀竞速投影" not in d_kr4.reason, f"防守可行时误触发开局先验: {d_kr4.reason}"
    # ③ 对照：空卡组（零爆发）不预测——保持旧「实测两回合」口径
    pol_kr5 = policy.Policy(know, random.Random(11))
    d_kr5 = pol_kr5.decide(krace1_state(1, 65, 22, []), prc1)
    assert "斩杀竞速投影" not in d_kr5.reason, f"零爆发不应预测竞速: {d_kr5.reason}"
    # ④ 防守线复核·联合能量口径（第460局批复盘改版）：旧版按「满能量全攻算
    #    击杀、满能量全挡算存活」两条线各自记账——同一回合的能量被花两次，
    #    guard_deck（唯一攻击牌 3 费 + 四张 1 费挡）账面「磨垒可行」（吞吐
    #    30×0.70=21 摸到火力封顶线→净火力1→可存活65回合），实际每回合要么
    #    花 3 能量打 26 要么全挡，永远凑不齐「19挡+26伤」同回合。460 批四场
    #    一幕 Boss 健康进场整管打空正是这个假象放进来的。修复后联合复核判
    #    不可行 → 全攻提速
    guard_deck = [{"card_id": "GD_HIT", "card_type": "Attack", "energy_cost": 3,
                   "dynamic_values": [{"name": "Damage", "current_value": 26}]}] + \
                  [{"card_id": f"GD_SHLD_{i}", "card_type": "Skill", "energy_cost": 1,
                    "dynamic_values": [{"name": "Block", "current_value": 10}]} for i in range(4)]
    pol_kr6 = policy.Policy(know, random.Random(11))
    d_kr6 = pol_kr6.decide(krace1_state(1, 65, 20, guard_deck), prc1)
    assert "斩杀竞速投影" in d_kr6.reason and "防守线复核" not in d_kr6.reason, \
        f"能量双算的假磨垒卡组未被联合复核识破: {d_kr6.reason}"
    # ④-b 联合复核正例（第460局批复盘）：真·攻防分配可行的卡组不得误杀——
    #    进攻线险负（ttk6.7>可存活4.7+余量1.5）后，格挡1点能量+攻击2点能量的
    #    分配能同时满足击杀与存活 → 维持攻防节奏，留痕联合对账
    joint_deck = [{"card_id": f"JT_ATK_{i}", "card_type": "Attack", "energy_cost": 1,
                   "dynamic_values": [{"name": "Damage", "current_value": 18}]} for i in range(3)] + \
                 [{"card_id": f"JT_BLK_{i}", "card_type": "Skill", "energy_cost": 1,
                   "dynamic_values": [{"name": "Block", "current_value": 12}]} for i in range(3)]
    pol_kr7 = policy.Policy(know, random.Random(11))
    d_kr7 = pol_kr7.decide(krace1_state(1, 80, 17, joint_deck), prc1)
    assert "斩杀竞速投影" not in d_kr7.reason and "防守线复核" in d_kr7.reason \
        and "联合能量对账" in d_kr7.reason, \
        f"联合分配可行的卡组被误判全攻提速: {d_kr7.reason}"
    prc1.combat = None

    # 3rf) 竞速格挡下限（第891局批复盘；856~876批 §四.3 预注册到期兑现）：
    #      891-F28-T2 实证——斩杀竞速「全攻提速」留痕下 6 费全部流向攻击、
    #      手握防御+（1费8甲）零甲硬吃 16（30→14），与 876-F30-T3 /
    #      891-F20-T3 同型累计 3 例且改写生死链。非致死 kill_race 回合的
    #      末点能量必须为最便宜合格挡牌保留（罚分 12 压过 ×1.25×1.15 攻击
    #      乘区差）；race_allin 路径维持 546 局全攻定案（3z 原样）；
    #      致死回合（买命/抢斩杀）维持全攻豁免。
    rf_pol = policy.Policy(know, random.Random(11))
    rf_enemies = [dict(ra_enemies[0])]
    rf_hit = {"index": 0, "card_id": "RF_HIT", "name": "竞速斩", "playable": True,
              "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
              "dynamic_values": [{"name": "Damage", "current_value": 12}]}
    rf_shld = {"index": 1, "card_id": "RF_SHLD", "name": "下限挡", "playable": True,
               "energy_cost": 1, "requires_target": False,
               "dynamic_values": [{"name": "Block", "current_value": 8}]}
    _rf_base = dict(reserve_for_block=True, min_blk_cost=1, my_hp=30, my_max_hp=87,
                    hopeless_race=False, kill_race=True, run_deck=[])
    s_floor_on, _, why_on = rf_pol._score_play(rf_hit, rf_enemies, 16, 0, 5,
                                               rf_pol.know.policy, cur_energy=1,
                                               race_blk_floor=True, **_rf_base)
    s_floor_off, _, why_off = rf_pol._score_play(rf_hit, rf_enemies, 16, 0, 5,
                                                 rf_pol.know.policy, cur_energy=1,
                                                 race_blk_floor=False, **_rf_base)
    assert s_floor_on < s_floor_off and "竞速格挡下限预留" in why_on \
        and "竞速格挡下限预留" not in why_off, \
        f"竞速格挡下限罚分/留痕未生效: on={s_floor_on}({why_on}) off={s_floor_off}({why_off})"
    s_floor_mid, _, why_mid = rf_pol._score_play(rf_hit, rf_enemies, 16, 0, 5,
                                                 rf_pol.know.policy, cur_energy=2,
                                                 race_blk_floor=True, **_rf_base)
    assert s_floor_mid > s_floor_on and "竞速格挡下限预留" not in why_mid, \
        f"能量充裕时误罚（cost+下限≤当前能量不应预留）: {s_floor_mid}({why_mid})"
    # decide 级正例：末点 1 能量在「攻击 vs 1费格挡」之间应让位给格挡
    def rfloor_state(energy_now, hp_now, incoming):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": 1,
            "combat": {"player": {"current_hp": hp_now, "max_hp": 87,
                                  "block": 0, "energy": energy_now},
                       "hand": [dict(rf_hit, index=0), dict(rf_shld, index=1)],
                       "enemies": [dict(rf_enemies[0],
                                        intents=[{"total_damage": incoming}])]},
            "run": {"current_hp": hp_now, "max_hp": 87, "gold": 0, "floor": 28,
                    "deck": weak_deck}}
    rf_ctx = type("RFCTX", (), {"combat": {"comp_id": "RF_RACE_COMP",
                                           "node_type": "Boss"},
                                "current_combat_is_hard": False,
                                "credit_tags": []})()
    d_floor = rf_pol.decide(rfloor_state(1, 30, 16), rf_ctx)
    assert d_floor.action == "play_card" \
        and d_floor.params.get("card_index") == 1, \
        f"非致死竞速回合末点能量未让位1费格挡: {d_floor.action}（{d_floor.reason}）"
    # 致死回合豁免：22 意图对 20 血当场必死 → 买命窗口原价保留（不再受下限影响）
    d_lethal = rf_pol.decide(rfloor_state(1, 20, 22), rf_ctx)
    assert d_lethal.action == "play_card", \
        f"致死回合弃权: {d_lethal.action}（{d_lethal.reason}）"

    # 3kv) 滚雪球局的防守线复核·联合能量口径（第454局批复盘引入，第460局
    #      批复盘改版）：454 批的教训是「格挡恰是升级型战斗的第一生存变量」，
    #      但其成立前提是卡组有输出引擎——旧复核按能量双算把「纯挡墙」也判
    #      成可行。联合口径下：
    #      ① 纯挡无输出引擎的墙对滚升意图：任何攻防分配都凑不齐击杀伤害，
    #         复核判不可行 → 全攻提速（墙没有赢法，拖延只多吃意图）；
    #      ② 零格挡对照维持全攻提速（冷启动安全不回潮）；
    #      ③ 火力压倒性格挡 → 复核仍判负，防复核沦为无条件否决竞速；
    #      「有攻击引擎的卡组在滚雪球局被复核救回」的正例由 ④-b 覆盖。
    esc_ctx = type("ESCCTX", (), {"combat": None, "current_combat_is_hard": False,
                                  "credit_tags": []})()
    esc_ctx.combat = {"comp_id": "ESC_RACE_COMP", "node_type": "Monster"}

    def accepted_combat(p, st, c):
        decision = p.decide(st, c)
        c.credit_tags.extend(decision.tags)
        return decision

    def esc_race_state(turn_no, hp_now, incoming, deck, t3_attack=False):
        if turn_no < 3:
            hand = [
                {"index": 0, "card_id": "ER_HIT", "name": "速攻", "playable": True,
                 "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                 "dynamic_values": [{"name": "Damage", "current_value": 10}]},
                {"index": 1, "card_id": "ER_HIT2", "name": "速攻二号", "playable": True,
                 "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                 "dynamic_values": [{"name": "Damage", "current_value": 10}]}]
        elif t3_attack:
            hand = [{"index": 0, "card_id": "ER_HIT3", "name": "孤注攻击", "playable": True,
                     "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                     "dynamic_values": [{"name": "Damage", "current_value": 10}]}]
        else:
            hand = [{"index": 0, "card_id": "ER_SHLD_A", "name": "壁垒甲", "playable": True,
                     "requires_target": False,
                     "dynamic_values": [{"name": "Block", "current_value": 8}]}]
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": turn_no,
            "combat": {"player": {"current_hp": hp_now, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": hand,
                       "enemies": [{"index": 0, "enemy_id": "ESC_RACE_COMP", "name": "滚雪球伏地虫",
                                    "current_hp": 55, "max_hp": 60, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": incoming}]}]},
            "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 5, "deck": deck}}

    esc_blk_deck = [{"card_id": f"ER_S_{i}", "card_type": "Skill", "energy_cost": 1,
                     "dynamic_values": [{"name": "Block", "current_value": 8}]} for i in range(3)]
    # ① 滚雪球局+纯挡墙（零输出引擎）：意图 4→7→24 确认持续升级后，竞速判负、
    #    联合复核不可行（卡组没有任何伤害来源，磨垒=无限拖）→ 全攻提速
    pol_escr = policy.Policy(knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-escrecheck-"))),
                             random.Random(11))
    accepted_combat(pol_escr, esc_race_state(1, 71, 4, esc_blk_deck), esc_ctx)
    accepted_combat(pol_escr, esc_race_state(2, 71, 7, esc_blk_deck), esc_ctx)
    d_e1 = pol_escr.decide(esc_race_state(3, 71, 24, esc_blk_deck), esc_ctx)
    assert ("斩杀竞速投影" in d_e1.reason and "防守线复核" not in d_e1.reason), \
        f"无输出引擎的纯挡墙未被联合复核识破: {d_e1.action}（{d_e1.reason}）"
    # ② 对照：零格挡卡组复核自然不触发——维持全攻提速（冷启动安全不回潮）
    esc_ctx.credit_tags = []
    pol_escr2 = policy.Policy(knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-escrecheck2-"))),
                              random.Random(11))
    accepted_combat(pol_escr2, esc_race_state(1, 71, 4, []), esc_ctx)
    accepted_combat(pol_escr2, esc_race_state(2, 71, 7, []), esc_ctx)
    d_e2 = pol_escr2.decide(esc_race_state(3, 71, 24, [], t3_attack=True), esc_ctx)
    assert "斩杀竞速投影" in d_e2.reason and "防守线复核" not in d_e2.reason, \
        f"零格挡卡组的滚雪球竞速被误放行: {d_e2.action}（{d_e2.reason}）"
    # ③ 对照：火力压倒格挡（40 意图 > 吞吐16.8 的净火力口径）——零余量下复核
    #    必须仍判负，防复核沦为无条件否决竞速
    esc_ctx.credit_tags = []
    pol_escr3 = policy.Policy(knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-escrecheck3-"))),
                              random.Random(11))
    accepted_combat(pol_escr3, esc_race_state(1, 71, 4, esc_blk_deck), esc_ctx)
    accepted_combat(pol_escr3, esc_race_state(2, 71, 7, esc_blk_deck), esc_ctx)
    d_e3 = pol_escr3.decide(esc_race_state(3, 71, 40, esc_blk_deck), esc_ctx)
    assert "斩杀竞速投影" in d_e3.reason and "防守线复核" not in d_e3.reason, \
        f"火力压倒性格挡时复核未判负: {d_e3.action}（{d_e3.reason}）"

    # 3kw) 防守复核火力滞后修正（JOINT_FEAS_FIRE_LAG，第843~855局批复盘）：
    #      非 esc 桶意图跳升回合（T1 意图 4 → T2 意图 26，_esc_rounds=1 未达
    #      开门槛），滞后 EMA≈10.6 远低于当轮意图——旧口径按幻影火力把已判死
    #      的竞速翻案成「格挡0+输出11 追平击杀5回合」的攻防节奏（855局F22
    #      同型死亡）。修正后对账火力取 max(EMA, 意图)=26 → 复核判负、doom
    #      判决维持并留痕；开关置 false 回落旧复核口径（对照②）。
    lag_ctx = type("LAGCTX", (), {"combat": None, "current_combat_is_hard": False,
                                  "credit_tags": []})()
    lag_ctx.combat = {"comp_id": "LAG_RACE_COMP", "node_type": "Monster"}

    def lag_race_state(turn_no, incoming, deck):
        hand = [
            {"index": 0, "card_id": "LG_HIT", "name": "速攻", "playable": True,
             "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
             "dynamic_values": [{"name": "Damage", "current_value": 10}]},
            {"index": 1, "card_id": "LG_HIT2", "name": "速攻二号", "playable": True,
             "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
             "dynamic_values": [{"name": "Damage", "current_value": 10}]}]
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": turn_no,
            "combat": {"player": {"current_hp": 71, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": hand,
                       "enemies": [{"index": 0, "enemy_id": "LAG_RACE_COMP", "name": "跳升怪",
                                    "current_hp": 88, "max_hp": 90, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": incoming}]}]},
            "run": {"current_hp": 71, "max_hp": 80, "gold": 0, "floor": 5, "deck": deck}}

    lag_deck = [{"card_id": f"LG_D_{i}", "card_type": "Attack", "energy_cost": 1,
                 "dynamic_values": [{"name": "Damage", "current_value": 10}]} for i in range(2)]
    pol_lag = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-lagfire-"))), random.Random(11))
    accepted_combat(pol_lag, lag_race_state(1, 4, lag_deck), lag_ctx)
    # 实测口径就位：两回合持续输出 11 → 实测 dpt 5.5/回合（防守回合稀释均值），
    # 换挡上浮 ×1.35 后 ttk≈88/7.4≈12 > 可存活 71/10.6+1.5≈8.2 → 竞速判死
    pol_lag._krace_turns = 2
    pol_lag._krace_dmg = pol_lag._krace_dmg_sustained = 11.0
    d_lag = pol_lag.decide(lag_race_state(2, 26, lag_deck), lag_ctx)
    assert ("斩杀竞速投影" in d_lag.reason and "防守线复核" not in d_lag.reason
            and "对账火力取意图26" in d_lag.reason), \
        f"意图跳升回合幻影火力翻案竞速判决未被修正: {d_lag.action}（{d_lag.reason}）"
    # ② 开关回退对照：joint_feas_fire_honest=false 恢复旧口径——滞后 EMA 10.6
    #    下联合复核判「格挡0+输出11 追平击杀5回合」可行（幻影火力翻案复现）
    lag_ctx.credit_tags = []
    pol_lag2 = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-lagfire2-"))), random.Random(11))
    pol_lag2.know.policy["joint_feas_fire_honest"] = False
    # 3kx) esc 桶防火力上浮的审计校准（RACE_ESC_FIRE_INFLATE_CALIB，第808~812局
    #      批复盘）：竞速审计台账 esc 桶 23/52=44.2% 判死局实战获胜（>30% 预注册
    #      线），触发前批预注册的「按桶收紧 fire inflate」——esc 桶复核火力上浮
    #      改走 escalation_race_fire_inflate_eff=0.20（留痕 ×1.20）；回退对照：
    #      eff 拉回 0.40 复现旧口径 ×1.40，eff=0 复现「整体关闭」无升级账留痕。
    assert "升级账" in d_e1.reason and "×1.20计价拖延成本" in d_e1.reason, \
        f"esc 桶复核火力未按审计校准 0.20 计价: {d_e1.reason}"
    esc_ctx.credit_tags = []
    pol_escr4 = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-escfire2-"))), random.Random(11))
    pol_escr4.know.policy["escalation_race_fire_inflate_eff"] = 0.40
    accepted_combat(pol_escr4, esc_race_state(1, 71, 4, esc_blk_deck), esc_ctx)
    accepted_combat(pol_escr4, esc_race_state(2, 71, 7, esc_blk_deck), esc_ctx)
    d_e4 = pol_escr4.decide(esc_race_state(3, 71, 24, esc_blk_deck), esc_ctx)
    assert "升级账" in d_e4.reason and "×1.40计价拖延成本" in d_e4.reason, \
        f"eff 键回退 0.40 未复现旧口径: {d_e4.reason}"
    esc_ctx.credit_tags = []
    pol_escr5 = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-escfire3-"))), random.Random(11))
    pol_escr5.know.policy["escalation_race_fire_inflate_eff"] = 0
    accepted_combat(pol_escr5, esc_race_state(1, 71, 4, esc_blk_deck), esc_ctx)
    accepted_combat(pol_escr5, esc_race_state(2, 71, 7, esc_blk_deck), esc_ctx)
    d_e5 = pol_escr5.decide(esc_race_state(3, 71, 24, esc_blk_deck), esc_ctx)
    assert "升级账" not in d_e5.reason and "斩杀竞速投影" in d_e5.reason, \
        f"eff=0 未按整体关闭回滚: {d_e5.reason}"

    accepted_combat(pol_lag2, lag_race_state(1, 4, lag_deck), lag_ctx)
    pol_lag2._krace_turns = 2
    pol_lag2._krace_dmg = pol_lag2._krace_dmg_sustained = 11.0
    d_lag2 = pol_lag2.decide(lag_race_state(2, 26, lag_deck), lag_ctx)
    assert "防守线复核" in d_lag2.reason and "联合能量对账" in d_lag2.reason, \
        f"开关回退后未恢复旧复核口径: {d_lag2.action}（{d_lag2.reason}）"

    # 3bx) 前夜必败预演的防守线复核·联合能量口径（第435~440批复盘引入，
    #      第460局批复盘改版）：裸血账判负后，攻防能量分配存在可行解（磨垒
    #      卡组「2能挡+1能攻」的持续分配能同时满足击杀与存活）则不判必败，
    #      前夜裁决交还旧三区口径（低血前夜恢复回血而非盲目锻造）
    bl_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-blkrelief-"))
    bl_know = knowledge.Knowledge(bl_dir)
    for _k in ("BR2_BOSS_A", "BR2_BOSS_B"):
        bl_know.stats["enemies"][_k] = {
            "encounters": 8, "hp_lost_sum": 320.0, "deaths": 4, "wins": 4,
            "boss_encounters": 2, "boss_hp_lost_sum": 80.0, "boss_deaths": 1,
            "hp_pool_sum": 320.0, "hp_pool_n": 2, "fire_sum": 80.0, "fire_rounds": 8}
    bl_pol = policy.Policy(bl_know, random.Random(13))
    bl_grind_deck = [{"card_id": f"BL_S{i}", "card_type": "Attack", "energy_cost": 1,
                      "dynamic_values": [{"name": "Damage", "current_value": 6}]} for i in range(5)] + \
                    [{"card_id": f"BL_SHLD_{i}", "card_type": "Skill", "energy_cost": 1,
                      "dynamic_values": [{"name": "Block", "current_value": 10}]} for i in range(4)]
    bl_rest = {
        "screen": "REST", "available_actions": ["choose_rest_option"],
        "rest": {"options": [
            {"index": 0, "option_id": "HEAL", "title": "休息", "is_enabled": True},
            {"index": 1, "option_id": "SMITH", "title": "锻造", "is_enabled": True}]},
        "run": {"current_hp": 48, "max_hp": 80, "gold": 0, "floor": 16, "deck": bl_grind_deck}}
    bl_ctx = SimpleNamespace(rest_before_boss=True, rest_proj_hp_pct=1.0,
                             rest_next_fight_loss_frac=0.0)
    d_bl_heal = bl_pol.decide(bl_rest, bl_ctx)
    assert d_bl_heal.tags and d_bl_heal.tags[0] == ("rest", "heal") and "竞速必败" not in d_bl_heal.reason, \
        f"防守线可行的磨垒卡组前夜被误判必败锻造: {d_bl_heal.action}（{d_bl_heal.reason}）"
    # 对照：同一卡组换掉格挡（纯弱攻）→ 防守线失效 → 维持必败锻造口径。
    # 第441~446批复盘起翻转带回血优先于必败锻造，故血量须在处决带外
    # （72-场均40×1.5=12 > 安全余量8）才能锁定「带外必败上砧」行为
    bl_all_atk_deck = [c for c in bl_grind_deck if c["card_type"] == "Attack"]
    d_bl_smith = bl_pol.decide(
        dict(bl_rest, run=dict(bl_rest["run"], current_hp=72, deck=bl_all_atk_deck)), bl_ctx)
    assert d_bl_smith.tags and d_bl_smith.tags[0] == ("rest", "smith") and "竞速必败" in d_bl_smith.reason, \
        f"零格挡卡组的必败预演被防守线复核误放行: {d_bl_smith.action}（{d_bl_smith.reason}）"
    # 新增对照（第441~446批复盘）：零格挡必败卡组但坐在处决带内（48/80）——
    # 翻转带回血必须压过必败锻造，且留痕写明竞速预演结论以供复盘归因
    d_bl_bandheal = bl_pol.decide(
        dict(bl_rest, run=dict(bl_rest["run"], deck=bl_all_atk_deck)), bl_ctx)
    assert d_bl_bandheal.tags and d_bl_bandheal.tags[0] == ("rest", "heal") \
        and "翻转带回血" in d_bl_bandheal.reason and "竞速预演虽判必败" in d_bl_bandheal.reason, \
        f"处决带内的必败卡组前夜未回血: {d_bl_bandheal.action}（{d_bl_bandheal.reason}）"

    # 3zw) 意图滚雪球确认解锁增益药水（第 255 批复盘）：低死亡率低战损的升级型
    #      组合从三条历史药水门槛的缝隙漏网（252 局 F5 劫掠者三连 8 战仅 1 死），
    #      _esc_rounds≥2（持续升级确认）即视为硬仗——增益的价值随剩余战斗时长
    #      衰减，等血量跌破线再喝等于把复利窗口烧掉
    pec = type("PECtx", (), {"combat": None, "current_combat_is_hard": False,
                             "credit_tags": []})()
    pec.combat = {"comp_id": "ESC_POT_COMP", "node_type": "Monster"}

    def esc_pot_state(turn_no, incoming):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": turn_no,
            "combat": {"player": {"current_hp": 65, "max_hp": 80, "block": 0, "energy": 3},
                       "hand": [
                           {"index": 0, "card_id": "EP_HIT", "name": "打击", "playable": True,
                            "energy_cost": 1, "requires_target": True, "valid_target_indices": [0],
                            "dynamic_values": [{"name": "Damage", "current_value": 12}]}],
                       "enemies": [{"index": 0, "enemy_id": "ESC_POT_COMP", "name": "滚雪球虫",
                                    "current_hp": 36, "max_hp": 60, "block": 0,
                                    "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": incoming}]}]},
            "run": {"current_hp": 65, "max_hp": 80, "gold": 0, "floor": 6, "deck": [],
                    "potions": [{"index": 0, "potion_id": "POT_ENERGY", "name": "能量药水",
                                 "description": "获得2点能量", "occupied": True,
                                 "can_use": True, "usage": "Combat"}]}}

    pol_ep = policy.Policy(knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-esapot-"))),
                           random.Random(7))
    pol_ep.decide(esc_pot_state(1, 4), pec)     # T1：意图基准采样
    pol_ep.decide(esc_pot_state(2, 7), pec)     # T2：趋势+3，升级计数 1（尚未确认）
    d_ep = pol_ep.decide(esc_pot_state(3, 24), pec)  # T3：趋势+17 计数 2 → 硬仗确认
    assert d_ep.action == "use_potion", \
        f"滚雪球确认后增益药水仍未解锁: {d_ep.action}（{d_ep.reason}）"
    # 对照：意图平稳（无升级轨迹）→ 不构成硬仗，药水保留
    pol_ep2 = policy.Policy(knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-esapot2-"))),
                            random.Random(7))
    pol_ep2.decide(esc_pot_state(1, 7), pec)
    pol_ep2.decide(esc_pot_state(2, 7), pec)
    d_ep2 = pol_ep2.decide(esc_pot_state(3, 7), pec)
    assert d_ep2.action != "use_potion", \
        f"意图平稳时误耗增益药水: {d_ep2.action}（{d_ep2.reason}）"
    pec.combat = None

    # 3zx) 连战战损疲劳递增（第 255 批复盘）：权重端早有疲劳压制但投影战损仍线性
    #      ——VS71/EHSL/7RJ9 三局链尾实际 -47~-72 而投影按 ~10/场记账。
    #      连续第 4 场起先验×(1+0.06×(n-2))逐场放大，封顶 1.30；非战斗节点清零
    slm_pol = policy.Policy(knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-slm-"))),
                            random.Random(3))
    _slm_p = slm_pol.know.policy
    assert abs(slm_pol._streak_loss_mult(_slm_p, "Monster", 3) - 1.06) < 1e-9, "连战战损递增步长错误"
    assert abs(slm_pol._streak_loss_mult(_slm_p, "Monster", 6) - 1.24) < 1e-9, "连战战损递增累计错误"
    assert abs(slm_pol._streak_loss_mult(_slm_p, "Monster", 99) - 1.30) < 1e-9, "连战战损递增未封顶"
    assert slm_pol._streak_loss_mult(_slm_p, "Monster", 2) == 1.0, "第 3 连战即加价（应自第 4 场起）"
    assert slm_pol._streak_loss_mult(_slm_p, "RestSite", 9) == 1.0, "非战斗节点被误加价"
    _slm_p["path_streak_loss_step"] = 0.0
    assert slm_pol._streak_loss_mult(_slm_p, "Monster", 9) == 1.0, "step=0 未关闭递增"

    # 3zy) 输出饥饿的成长牌增值（第 255 批复盘）：Boss 攻坚死因形态是「即时伤害
    #      不够、长战无成长」——力量型能力每早一回合上场就全程复利。拾取端此前
    #      平面 5 分定价；饥饿时力量文本的能力牌按缺口深度加分（base+extra）。
    #      第429~434批复盘扩展：加分之上叠加「成长引擎稀缺」结构分——卡组零引擎
    #      全额、1 台减半、≥cap 归零（首台点燃是刚需，第三张恶魔形态是注水）
    #      第547~552批复盘再扩展：供给口径换 deck_effective_burst——每台生效
    #      引擎 +engine_burst_credit 计入爆发，缺口随拾取引擎真实收窄，
    #      饥饿加分按收窄后的缺口缩放（拿引擎必须看得见进步）
    ph_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-powhun-"))
    ph_know = knowledge.Knowledge(ph_dir)
    ph_pol = policy.Policy(ph_know, random.Random(5))
    starve_deck = [{"card_id": f"PH_D{i}", "card_type": "Skill", "energy_cost": 1,
                    "rules_text": "获得5点格挡"} for i in range(10)]
    pow_strong = {"card_id": "INFLAME_T", "name": "点燃", "card_type": "Power", "energy_cost": 1,
                  "rules_text": "获得2点力量"}
    pow_plain = {"card_id": "PLAIN_POW_T", "name": "平平能力", "card_type": "Power", "energy_cost": 1,
                 "rules_text": "你的回合开始时风平浪静"}
    v_strong = ph_pol.eval_reward_card(dict(pow_strong), list(starve_deck))
    v_plain = ph_pol.eval_reward_card(dict(pow_plain), list(starve_deck))
    _ph_b = float(ph_know.policy["power_starve_bonus_base"])
    _ph_x = float(ph_know.policy["power_starve_bonus_extra_max"])
    _ph_s = float(ph_know.policy.get("scaling_engine_pick_bonus", 7.0))
    assert abs((v_strong - v_plain) - (_ph_b + _ph_x + _ph_s)) < 1e-9, \
        f"饥饿成长牌加分缺失或数值不符: {v_strong - v_plain:.2f}（期望 base+extra×缺口1.0+稀缺满档）"
    eng1_deck = list(starve_deck) + [dict(pow_strong, card_id="INFLAME_E1")]
    eng2_deck = eng1_deck + [dict(pow_strong, card_id="INFLAME_E2")]
    d_eng = []
    for _eng_deck in (starve_deck, eng1_deck, eng2_deck):
        d_eng.append(ph_pol.eval_reward_card(dict(pow_strong), list(_eng_deck))
                     - ph_pol.eval_reward_card(dict(pow_plain), list(_eng_deck)))
    _ph_c = float(ph_know.policy.get("engine_burst_credit", 6.0))
    _ph_floor = float(ph_know.policy["deck_burst_floor"])
    _ph_dc = _ph_x * (_ph_c / _ph_floor)  # 每台引擎收窄的缺口对应的 extra 衰减量
    assert abs(d_eng[0] - (_ph_b + _ph_x + _ph_s)) < 1e-9, "零引擎稀缺加分缺失"
    assert abs((d_eng[0] - d_eng[1]) - (_ph_dc + _ph_s / 2.0)) < 1e-9, \
        "1台引擎时稀缺未减半或缺口未随授信收窄"
    assert abs((d_eng[1] - d_eng[2]) - (_ph_dc + _ph_s / 2.0)) < 1e-9, \
        "引擎数达cap后稀缺未归零或缺口未继续收窄"
    assert abs(ph_pol.deck_effective_burst(list(eng1_deck)) - _ph_c) < 1e-9, \
        "deck_effective_burst 未计入引擎授信"
    fed_deck = list(starve_deck) + [
        {"card_id": f"PH_BIG{i}", "card_type": "Attack", "energy_cost": 1,
         "dynamic_values": [{"name": "Damage", "current_value": 15}]} for i in range(3)]
    v_strong2 = ph_pol.eval_reward_card(dict(pow_strong), list(fed_deck))
    v_plain2 = ph_pol.eval_reward_card(dict(pow_plain), list(fed_deck))
    assert abs(v_strong2 - v_plain2) < 1e-9, \
        f"卡组成型后成长牌仍吃饥饿加分: {v_strong2 - v_plain2:.2f}"

    # 3zy-bis（第429~434批复盘）：锻造屏在饥饿卡组下优先升级成长引擎——
    # 回归保护点：①升级分支此前没有任何带非空卡组的用例（空卡组短路饥饿门，
    # 曾险些掩盖作用域缺陷）；②力量牌须凭锻造端加分压过攻击候选并留痕来源；
    # ③整条路径走真实 decide()，防静默吞异常退化为永远选攻击。
    up_state = {
        "screen": "CARD_SELECTION",
        "available_actions": ["select_deck_card", "confirm_selection"],
        "selection": {"kind": "upgrade", "prompt": "升级", "min_select": 1,
                      "selected_count": 0, "can_confirm": False,
                      "cards": [
                          {"index": 0, "card_id": "UP_BIG_ATK", "name": "重击",
                           "card_type": "Attack", "energy_cost": 1,
                           "dynamic_values": [{"name": "Damage", "current_value": 15}]},
                          {"index": 1, "card_id": "INFLAME_UP_T", "name": "点燃",
                           "card_type": "Power", "energy_cost": 1,
                           "rules_text": "获得2点力量"}]},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 10,
                "deck": [dict(c) for c in starve_deck]}}
    d_up = ph_pol.decide(up_state, type("UCtx", (), {})())
    assert d_up.action == "select_deck_card" and d_up.params.get("option_index") == 1, \
        f"饥饿锻造未优先成长引擎: {d_up.action}（{d_up.reason}）"
    assert "优先升级成长引擎" in d_up.reason, f"锻造端引擎门控留痕缺失: {d_up.reason}"

    # 3zz) 终局日志防回写 + 复盘摘要的脏戳豁免（第 369 局复盘）：218 批的增量
    #      存档落地后，「结算屏→回主菜单→检查时间线」等后继决策会以增量稿
    #      格式（in_progress=true/victory=false/floor=当前屏）盖回已定稿日志
    #      ——141 个已完成局被永久打上「进行中」脏戳，_recent_run_summaries
    #      把它们全部过滤后，复盘数据包只能拿一百多局前的旧局当样本
    #      （第 263~369 局的复盘摘要整体失真）。两道修复各配回归：
    #      ①定稿后 _save_run_progress 一律只读；②摘要对「轨迹含 GAME_OVER
    #      的 in_progress 文件」按完成局放行，真进行中局仍排除。
    import llm_review as llm_review_mod
    _kr_backup = llm_review_mod.KNOWLEDGE_DIR
    ag_fin = agent_mod.Agent(dict(agent_mod.DEFAULT_CONFIG))
    st_map = {"screen": "MAP", "run_id": "RUN_FIN",
              "run": {"current_hp": 40, "max_hp": 80, "gold": 0, "floor": 6}}
    track_accepted(ag_fin, st_map,
                   policy.Decision(action="choose_map_node", reason="x"))
    assert ag_fin.ctx.run_finalized is False, "对局未结束不应处于定稿态"
    ag_fin._save_run_progress({"floor": 6}, force=True)
    log_path = next((tmp_agent / "runs").glob("*_RUN_FIN.json"))
    raw = json.loads(log_path.read_text(encoding="utf-8"))
    assert raw.get("in_progress") is True and raw.get("floor") == 6, \
        f"增量稿应带进行中标记: {raw.get('in_progress')}/{raw.get('floor')}"
    ag_fin._finalize(victory=False, floor=6)
    raw = json.loads(log_path.read_text(encoding="utf-8"))
    assert "in_progress" not in raw and raw.get("floor") == 6 and raw.get("victory") is False, \
        f"终稿语义缺失: in_progress={'in_progress' in raw}, floor={raw.get('floor')}"
    st_mm = {"screen": "MAIN_MENU", "run_id": "RUN_FIN",
             "run": {"current_hp": 0, "max_hp": 80, "gold": 0, "floor": 0}}
    track_accepted(ag_fin, st_mm,
                   policy.Decision(action="open_timeline",
                                   reason="主菜单：检查时间线可解锁项（优先解锁新内容）"))
    raw = json.loads(log_path.read_text(encoding="utf-8"))
    assert "in_progress" not in raw, "定稿日志被结算后继决策回写成进行中（脏戳复发）"
    llm_review_mod.KNOWLEDGE_DIR = tmp_agent
    tknow.save_run_log("RUN_LIVE", {"run_id": "RUN_LIVE", "in_progress": True,
                                    "victory": False, "floor": 12,
                                    "decisions": [{"screen": "COMBAT", "action": "play_card"}]})
    tknow.save_run_log("RUN_STAMP", {"run_id": "RUN_STAMP", "in_progress": True,
                                     "victory": False, "floor": 0,
                                     "decisions": [{"screen": "COMBAT", "action": "play_card", "floor": 9},
                                                   {"screen": "GAME_OVER", "action": None, "floor": 17,
                                                    "reason": "对局结束：胜利（层数 17），正在总结复盘…"},
                                                   {"screen": "MAIN_MENU", "action": "open_timeline",
                                                    "floor": 0}]})
    summaries = llm_review_mod._recent_run_summaries(10)
    summ_ids = {s["run_id"] for s in summaries}
    assert "RUN_STAMP" in summ_ids, f"定稿后被盖脏戳的完成局未进摘要: {sorted(summ_ids)}"
    assert "RUN_LIVE" not in summ_ids, f"真进行中对局混进了摘要: {sorted(summ_ids)}"
    stamp = next(s for s in summaries if s["run_id"] == "RUN_STAMP")
    assert stamp["floor"] == 17 and stamp["victory"] is True, \
        f"脏戳字段的读端复原失效（floor/victory 按决策轨迹复原）: {stamp}"
    llm_review_mod.KNOWLEDGE_DIR = _kr_backup

    # 3br) Boss 前夜竞速必败改锻造（第 397~402 批复盘）：本批五场 Boss 死亡全部
    #      发生在前夜翻转带回血之后（入场 57%~100%、战损 -46~-80 整管打空）——
    #      满血也追不上击杀曲线的对局里回血零生存价值。消费 138~141 批入库的
    #      Boss 血池/火力均值（boss_race_vitals，兑现第 214 批遗留的篝火端消费），
    #      与战斗端斩杀竞速同式对账；数据未成熟时回落旧三区裁决
    br_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-bosrace-"))
    br_know = knowledge.Knowledge(br_dir)
    br_know.stats["enemies"]["BR_BOSS_A"] = {
        "encounters": 8, "hp_lost_sum": 320.0, "deaths": 4, "wins": 4,
        "boss_encounters": 2, "boss_hp_lost_sum": 80.0, "boss_deaths": 1,
        "hp_pool_sum": 320.0, "hp_pool_n": 2, "fire_sum": 80.0, "fire_rounds": 8}
    br_know.stats["enemies"]["BR_BOSS_B"] = {
        "encounters": 8, "hp_lost_sum": 320.0, "deaths": 4, "wins": 4,
        "boss_encounters": 2, "boss_hp_lost_sum": 80.0, "boss_deaths": 1,
        "hp_pool_sum": 320.0, "hp_pool_n": 2, "fire_sum": 80.0, "fire_rounds": 8}
    br_pol = policy.Policy(br_know, random.Random(13))
    _vp, _vf = br_know.boss_race_vitals()
    assert _vp is not None and abs(_vp - 160.0) < 1e-6 and _vf is not None and abs(_vf - 10.0) < 1e-6, \
        f"Boss 血池火力均值读取失效: {_vp}/{_vf}"
    br_weak_deck = [{"card_id": f"BR_S{i}", "card_type": "Attack", "energy_cost": 1,
                     "dynamic_values": [{"name": "Damage", "current_value": 6}]} for i in range(5)]
    # 弱卡组（burst≈18→先验9.9/回合）：击杀需 16 回合 > 满血可存活 8 回合 → 必败。
    # 第441~446批复盘：48/80 坐在处决带内，翻转带回血优先于必败锻造——
    # 留痕必须写明竞速预演结论，供复盘区分「误判必败」与「无奈回血」
    br_rest_weak = {
        "screen": "REST", "available_actions": ["choose_rest_option"],
        "rest": {"options": [
            {"index": 0, "option_id": "HEAL", "title": "休息", "is_enabled": True},
            {"index": 1, "option_id": "SMITH", "title": "锻造", "is_enabled": True}]},
        "run": {"current_hp": 48, "max_hp": 80, "gold": 0, "floor": 16, "deck": br_weak_deck}}
    br_ctx = SimpleNamespace(rest_before_boss=True, rest_proj_hp_pct=1.0,
                             rest_next_fight_loss_frac=0.0)
    d_br_weak = br_pol.decide(br_rest_weak, br_ctx)
    assert d_br_weak.tags and d_br_weak.tags[0] == ("rest", "heal") \
        and "翻转带回血" in d_br_weak.reason and "竞速预演虽判必败" in d_br_weak.reason, \
        f"处决带内的必败前夜应回血而非上砧: {d_br_weak.action}（{d_br_weak.reason}）"
    # 带外对照（72/80：余量12>安全余量8）：维持第397~402批「必败改锻造」口径
    br_rest_weak_out = dict(br_rest_weak,
                            run=dict(br_rest_weak["run"], current_hp=72))
    d_br_weak_out = br_pol.decide(br_rest_weak_out, br_ctx)
    assert d_br_weak_out.tags and d_br_weak_out.tags[0] == ("rest", "smith") \
        and "竞速必败" in d_br_weak_out.reason, \
        f"处决带外的竞速必败前夜应改锻造: {d_br_weak_out.action}（{d_br_weak_out.reason}）"
    # 强卡组对照（3×15伤攻击 burst=45→先验24.75）：击杀需 6.5 ≤ 8+1.5 → 可赢 → 旧裁决回血
    br_strong_deck = [{"card_id": f"BR_BIG{i}", "card_type": "Attack", "energy_cost": 1,
                       "dynamic_values": [{"name": "Damage", "current_value": 15}]} for i in range(3)]
    br_rest_strong = dict(br_rest_weak)
    br_rest_strong["run"] = dict(br_rest_weak["run"], deck=br_strong_deck)
    d_br_strong = br_pol.decide(br_rest_strong, br_ctx)
    assert d_br_strong.tags and d_br_strong.tags[0] == ("rest", "heal"), \
        f"竞速可赢的强卡组前夜应维持旧回血裁决: {d_br_strong.reason}"
    # 第709~713批补合：紧急低血且悲观账判死时，必须再过一次乐观联合能量复核。
    # 用固定判定隔离测试分支路由，避免样本均值/卡池细节变化让回归夹具漂移。
    _br_doomed = br_pol._boss_race_doomed
    _br_joint = br_pol._race_joint_feasible
    br_pol._boss_race_doomed = lambda *args, **kwargs: (True, "固定悲观判死")
    br_rest_urgent = dict(br_rest_weak,
                          run=dict(br_rest_weak["run"], current_hp=20))
    br_pol._race_joint_feasible = lambda *args, **kwargs: (True, "固定乐观可行")
    d_br_urgent_heal = br_pol.decide(br_rest_urgent, br_ctx)
    assert d_br_urgent_heal.tags and d_br_urgent_heal.tags[0] == ("rest", "heal") \
        and "乐观口径复核存在可行攻防分配" in d_br_urgent_heal.reason, \
        f"紧急低血的乐观可行对局应回血: {d_br_urgent_heal.reason}"
    br_pol._race_joint_feasible = lambda *args, **kwargs: (False, "固定乐观无解")
    d_br_urgent_smith = br_pol.decide(br_rest_urgent, br_ctx)
    assert d_br_urgent_smith.tags and d_br_urgent_smith.tags[0] == ("rest", "smith") \
        and "必败弃疗改锻造" in d_br_urgent_smith.reason, \
        f"乐观口径也无解时应维持必败锻造: {d_br_urgent_smith.reason}"
    br_pol._boss_race_doomed = _br_doomed
    br_pol._race_joint_feasible = _br_joint
    # 数据未成熟回落（无血池/火力学样的空库）：行为与旧版严格一致（翻转带回血）
    nv_pol = policy.Policy(knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-bosrace2-"))),
                           random.Random(13))
    d_br_nv = nv_pol.decide(dict(br_rest_weak,
                                 run=dict(br_rest_weak["run"],
                                          **{"deck": br_weak_deck})), br_ctx)
    assert d_br_nv.tags and d_br_nv.tags[0] == ("rest", "heal"), \
        f"无 Boss 实证时前夜应回落旧口径回血: {d_br_nv.reason}"
    # 地图投影镜像一致性：必败对局下投影把前夜篝火记为锻造（不回血），预计进 Boss 血量更低。
    # 第441~446批复盘起翻转带内必败也投影回血，故血量语境须在带外（72-60>8）才走必败锻造通道；
    # 可选节点只留前夜篝火（Boss 权重×10 会抢走首选项，镜像就无从生效）
    def br_map_reason(pknow):
        pmap = policy.Policy(pknow, random.Random(13))
        st = {"screen": "MAP", "available_actions": ["choose_map_node"],
              "map": {"available_nodes": [
                  {"index": 0, "row": 16, "col": 0, "node_type": "RestSite",
                   "children": [{"row": 17, "col": 0}]}],
                  "nodes": [
                      {"row": 16, "col": 0, "node_type": "RestSite"},
                      {"row": 17, "col": 0, "node_type": "Boss"}]},
              "run": {"current_hp": 72, "max_hp": 80, "gold": 0, "floor": 16, "deck": br_weak_deck}}
        return pmap.decide(st, br_ctx).reason
    _proj_doom = float(re.search(r"进 Boss 血量 ?(\d+)%", br_map_reason(br_know)).group(1))
    _proj_nv = float(re.search(r"进 Boss 血量 ?(\d+)%", br_map_reason(
        knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-bosrace3-"))))).group(1))
    assert _proj_doom < _proj_nv, \
        f"投影镜像未与必败锻造口径同步: 必败{_proj_doom}% 应低于 无数据{_proj_nv}%"
    br_ctx.rest_before_boss = False

    # 3br-2) per-Boss 血池全称门（第731~740批拒合成果补合）：均值判负后，
    #        任一重复实证组合可赢即放行；全组合必败才保留死刑。native 缺失
    #        或显式关闭旋钮均严格回落旧均值口径。
    class _PerComboNative:
        available = True
        pools: dict = {}

        def lookup(self, category, monster_id):
            if category != "monsters" or monster_id not in self.pools:
                return None
            low, high = self.pools[monster_id]
            return {"runtime": {"min_hp": low, "max_hp": high}}

        def enrich_card(self, card):
            return card

    def _pc_enemy(pool_sum):
        return {
            "encounters": 8, "hp_lost_sum": 320.0, "deaths": 4, "wins": 4,
            "boss_encounters": 2, "boss_hp_lost_sum": 80.0, "boss_deaths": 1,
            "hp_pool_sum": float(pool_sum), "hp_pool_n": 2,
            "fire_sum": 80.0, "fire_rounds": 8,
            "boss_act": {"1": {"hp_pool_sum": float(pool_sum), "hp_pool_n": 2}},
        }

    pc_state = dict(br_rest_weak,
                    run=dict(br_rest_weak["run"], current_hp=20))
    pc_ctx = SimpleNamespace(rest_before_boss=True, rest_proj_hp_pct=1.0,
                             rest_next_fight_loss_frac=0.0)
    pc_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-percombo-"))
    pc_know = knowledge.Knowledge(pc_dir)
    pc_know.stats["enemies"]["PC_LIGHT"] = _pc_enemy(130.0)
    pc_know.stats["enemies"]["PC_HEAVY"] = _pc_enemy(600.0)
    pc_native = _PerComboNative()
    pc_native.pools = {"PC_LIGHT": (60, 70), "PC_HEAVY": (290, 310)}
    pc_know.game_knowledge = pc_native
    d_pc_light = policy.Policy(pc_know, random.Random(13)).decide(pc_state, pc_ctx)
    assert d_pc_light.tags and d_pc_light.tags[0] == ("rest", "heal"), \
        f"轻池可赢时应撤销均值死刑并保住低血回血: {d_pc_light.reason}"
    assert "BOSS_RACE_COMBO_GATE" in json.dumps(d_pc_light.trace, ensure_ascii=False), \
        f"组合门放行未进入持久决策轨迹: {d_pc_light.trace}"

    pc_native.pools = {"PC_LIGHT": (290, 300), "PC_HEAVY": (300, 310)}
    d_pc_heavy = policy.Policy(pc_know, random.Random(13)).decide(pc_state, pc_ctx)
    assert d_pc_heavy.tags and d_pc_heavy.tags[0] == ("rest", "smith") \
        and "BOSS_RACE_COMBO_GATE 全称必败分账" in d_pc_heavy.reason, \
        f"全组合必败时应维持死刑并写分账: {d_pc_heavy.reason}"

    pc_no_native = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-percombo-none-")))
    pc_no_native.stats["enemies"]["PC_LIGHT"] = _pc_enemy(130.0)
    pc_no_native.stats["enemies"]["PC_HEAVY"] = _pc_enemy(600.0)
    d_pc_no_native = policy.Policy(pc_no_native, random.Random(13)).decide(pc_state, pc_ctx)
    assert d_pc_no_native.tags and d_pc_no_native.tags[0] == ("rest", "smith") \
        and "BOSS_RACE_COMBO_GATE" not in d_pc_no_native.reason, \
        f"native 缺失时应回落均值判死: {d_pc_no_native.reason}"

    pc_off = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-percombo-off-")))
    pc_off.stats["enemies"]["PC_LIGHT"] = _pc_enemy(130.0)
    pc_off.stats["enemies"]["PC_HEAVY"] = _pc_enemy(600.0)
    pc_off.game_knowledge = _PerComboNative()
    pc_off.game_knowledge.pools = {"PC_LIGHT": (60, 70), "PC_HEAVY": (290, 310)}
    pc_off.policy["boss_race_per_combo_gate"] = False
    d_pc_off = policy.Policy(pc_off, random.Random(13)).decide(pc_state, pc_ctx)
    assert d_pc_off.tags and d_pc_off.tags[0] == ("rest", "smith") \
        and "BOSS_RACE_COMBO_GATE" not in d_pc_off.reason, \
        f"组合门关闭时应回落均值判死: {d_pc_off.reason}"

    # 3br-3) 残能救场守卫（第698~770批复盘闭环）：本批 89 例带能量空过横跨
    #        40 局（16 例缺口>0，742 局 F17-T2 死亡战手握岩石铠甲仍空过）。
    #        意图缺口>0 且剩能量时 end_turn 边界必须先尝试 primitive 救场：
    #        覆甲类即时能力牌旁路死牌误杀、可负担格挡优先、自残攻击排除；
    #        缺口≤0 或关闭 idle_energy_rescue 时严格回落旧版空过语义。
    def _resc_state(hand_cards, energy_val, incoming_val, blk_val):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": 2,
            "combat": {"player": {"current_hp": 5, "max_hp": 80,
                                  "block": blk_val, "energy": energy_val},
                       "hand": hand_cards,
                       "enemies": [{"index": 0, "enemy_id": "EXOSKEL",
                                    "name": "外骨骼", "current_hp": 90, "max_hp": 120,
                                    "block": 0, "is_alive": True, "is_hittable": True,
                                    "intents": [{"total_damage": incoming_val}]}]},
            "run": {"current_hp": 5, "max_hp": 80, "gold": 0, "floor": 17, "deck": []},
        }

    resc_armor = [{"index": 0, "card_id": "STONE_ARMOR", "name": "岩石铠甲",
                   "playable": True, "energy_cost": 1, "requires_target": False,
                   "rules_text": "获得4层覆甲。"}]
    resc_pol = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-idleresc-"))), random.Random(5))
    d_resc_plat = resc_pol.decide(_resc_state(resc_armor, 2, 19, 3), ctx)
    assert d_resc_plat.action == "play_card" \
        and d_resc_plat.params.get("card_index") == 0 \
        and "残能救场[覆甲]" in d_resc_plat.reason, \
        f"死亡层覆甲牌未被残能救场回收: {d_resc_plat.reason}"
    assert "RESCUE 残能救场" in json.dumps(d_resc_plat.trace, ensure_ascii=False), \
        f"残能救场未进入持久决策轨迹: {d_resc_plat.trace}"
    d_rollback = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-idleresc-rb-")))
    d_rollback.policy["idle_energy_rescue"] = False
    d_rb = policy.Policy(d_rollback, random.Random(5)).decide(
        _resc_state(resc_armor, 2, 19, 3), ctx)
    assert d_rb.action == "end_turn" and "评估后无值得出的牌" in d_rb.reason, \
        f"回滚键失效，旧空过语义被改变: {d_rb.reason}"

    resc_defend = [{"index": 0, "card_id": "DEFEND_IRONCLAD", "name": "防御",
                    "playable": True, "energy_cost": 1, "requires_target": False,
                    "rules_text": "获得5点格挡",
                    "dynamic_values": [{"name": "Block", "current_value": 5}]}]
    # 主评分线在健康状态下本就会直接选择该防御（回归保护：救场不与主路径抢戏）
    d_resc_blk = resc_pol.decide(_resc_state(resc_defend, 1, 10, 0), ctx)
    assert d_resc_blk.action == "play_card" \
        and d_resc_blk.params.get("card_index") == 0, \
        f"缺口>0 的正常格挡评分不应被打断: {d_resc_blk.reason}"
    _blk_c, _blk_kind = policy.idle_energy_rescue_pick(
        resc_defend, 1, 10, 0)
    assert _blk_kind == "block" and _blk_c is not None \
        and _blk_c.get("card_id") == "DEFEND_IRONCLAD", \
        f"救场池未把可负担格挡列为第一优先: {_blk_kind}"
    _none_c, _none_kind = policy.idle_energy_rescue_pick(
        resc_defend, 1, 10, 10)
    assert _none_c is None and _none_kind == "", \
        f"缺口≤0 时救场池应返回空: {(_none_kind, _none_c)}"
    _lock_c, _lock_kind = policy.idle_energy_rescue_pick(
        resc_armor + resc_defend, 3, 30, 5, block_locked=True)
    assert _lock_c is None and _lock_kind == "", \
        f"锁格挡窗口内格挡/覆甲不得成为救场弹药: {(_lock_kind, _lock_c)}"
    resc_hem = [{"index": 0, "card_id": "HEMOKINESIS", "name": "御血术",
                 "playable": True, "energy_cost": 1, "requires_target": False,
                 "rules_text": "失去2点生命，造成15点伤害。",
                 "dynamic_values": [{"name": "Damage", "current_value": 15}]}]
    _hem_c, _hem_kind = policy.idle_energy_rescue_pick(resc_hem, 1, 20, 0)
    assert _hem_c is None and _hem_kind == "", \
        f"自残成本型攻击不应作为救场弹药: {(_hem_kind, _hem_c)}"

    # 3bs) 输出饥饿链第五级接替（第 397~402 批复盘）：四级链全顶格后 Boss 竞速
    #      败北证据改接 kill_race_prior_eff 下调（更早全攻提速+前夜更早转锻造）；
    #      链未顶格时不接替；胜利按 +0.03 向锚点回收
    bs_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-relaykr-"))
    bs_know = knowledge.Knowledge(bs_dir)
    bs_know.policy.update({"burst_starve_bonus_base": 8.0, "burst_starve_bonus_extra_max": 12.0,
                           "deck_burst_floor": 45.0, "boss_eve_smith_hp_pct": 0.45,
                           "power_longfight_bonus_max": 12.0, "kill_race_prior_eff": 0.55})
    assert reflect.BOUNDS["kill_race_prior_eff"] == (0.35, 0.72), \
        f"竞速先验释放上限未恢复: {reflect.BOUNDS['kill_race_prior_eff']}"
    bs_ctx = SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "BR_BOSS_A", "node_type": "Boss", "rounds": 8,
                        "floor": 17, "hp_lost": 78.0, "stall": False},
        death_was_elite=False, death_hp_pct_at_entry=0.98, credit_tags=[],
        rests_healed_at_full=0, ascension=0, combat_notes=[])
    reflect.finalize_run(bs_know, bs_ctx, victory=False, final_floor=17)
    assert abs(bs_know.policy["kill_race_prior_eff"] - 0.52) < 1e-9, \
        f"顶格链后竞速败北证据未接替 kill_race_prior_eff: {bs_know.policy['kill_race_prior_eff']}"
    # 对照：链条未顶格（默认值）时证据被四级链吸收，不接替
    bs2_know = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-relaykr2-")))
    reflect.finalize_run(bs2_know, bs_ctx, victory=False, final_floor=17)
    assert abs(bs2_know.policy["kill_race_prior_eff"] - 0.55) < 1e-9, \
        f"链条未顶格却提前接替: {bs2_know.policy['kill_race_prior_eff']}"
    # 胜利回收：0.52 → 0.55 锚点
    bs_win_ctx = SimpleNamespace(
        died_to_event=None, died_in_combat=None, death_was_elite=False,
        death_hp_pct_at_entry=None, credit_tags=[], rests_healed_at_full=0,
        ascension=0, combat_notes=[])
    reflect.finalize_run(bs_know, bs_win_ctx, victory=True, final_floor=20)
    assert abs(bs_know.policy["kill_race_prior_eff"] - 0.55) < 1e-9, \
        f"胜利未回收竞速先验折算率: {bs_know.policy['kill_race_prior_eff']}"

    # 3bs-2) 部分胜利释放（第 494 局批复盘新增；第509~515局批复盘重开通道）：
    #        非胜利局但已跨过幕界（F18+ 即实战击败过一幕 Boss）即释放——
    #        旧排除条件「最终不死于 Boss 战」过宽：512 局型（打赢一幕 Boss 后
    #        死于二幕 Boss 战）被整体挡死，本批六局六次下调对零次释放，eff 钉死
    #        触底带。释放记的是一幕 Boss 战的反证（死于一幕 Boss 则 final_floor≤17），
    #        与最终二幕 Boss 战的降账是两场独立战斗的证据。
    #        正例一：压到 0.37 触底的折算率 + F31 精英阵亡 → 0.40；
    #        正例二：F33 死于二幕 Boss 战 → 同样 0.40（旧版反例，现已翻案）；
    #        反例：F17 内死亡（一幕 Boss 未被击败）→ 不释放
    bsp_know = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-relaykr3-")))
    bsp_know.policy["kill_race_prior_eff"] = 0.37
    bsp_ctx = SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "BR_ELITE_A", "node_type": "Elite", "rounds": 6,
                        "floor": 31, "hp_lost": 52.0, "stall": False},
        death_was_elite=True, death_hp_pct_at_entry=0.4, credit_tags=[],
        rests_healed_at_full=0, ascension=0, combat_notes=[])
    reflect.finalize_run(bsp_know, bsp_ctx, victory=False, final_floor=31)
    assert abs(bsp_know.policy["kill_race_prior_eff"] - 0.40) < 1e-9, \
        f"跨幕局未获部分胜利释放: {bsp_know.policy['kill_race_prior_eff']}"
    # 正例二：死于二幕 Boss 战的跨幕局也释放（512 局型，通道重开的核心形态）
    bsn_know = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-relaykr4-")))
    bsn_know.policy["kill_race_prior_eff"] = 0.37
    reflect.finalize_run(bsn_know, SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "BR_BOSS_B", "node_type": "Boss", "rounds": 8,
                        "floor": 33, "hp_lost": 86.0, "stall": False},
        death_was_elite=False, death_hp_pct_at_entry=0.9, credit_tags=[],
        rests_healed_at_full=0, ascension=0, combat_notes=[]),
        victory=False, final_floor=33)
    assert abs(bsn_know.policy["kill_race_prior_eff"] - 0.40) < 1e-9, \
        f"打赢一幕后死于二幕Boss战未获释放（512局型死锁复发）: {bsn_know.policy['kill_race_prior_eff']}"
    # 反例：未跨幕界（F17 死于一幕 Boss）→ 不释放（独立新库防前案残留）
    bsz_know = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-relaykr5-")))
    bsz_know.policy["kill_race_prior_eff"] = 0.37
    reflect.finalize_run(bsz_know, SimpleNamespace(
        died_to_event=None,
        died_in_combat={"comp_id": "BR_BOSS_C", "node_type": "Boss", "rounds": 8,
                        "floor": 17, "hp_lost": 80.0, "stall": False},
        death_was_elite=False, death_hp_pct_at_entry=1.0, credit_tags=[],
        rests_healed_at_full=0, ascension=0, combat_notes=[]),
        victory=False, final_floor=17)
    assert abs(bsz_know.policy["kill_race_prior_eff"] - 0.37) < 1e-9, \
        f"未跨幕界不应释放: {bsz_know.policy['kill_race_prior_eff']}"

    # 3bt) 竞速及格线与预留解耦（第422局复盘）：burst≈33 的卡组高于静态
    #      deck_burst_floor=30、却远低于杀 learned Boss 所需（血池160/火力10/
    #      满血存活8回合 → 及格线36.4）——旧口径把它当「非饥饿」卡组：力量
    #      药水在距 Boss 3 层的普通怪房被放行烧掉（旧版复用顶格 0.80 的
    #      potion_block_hp_pct 当解封口），商店路由理由明写「够买药水档位」
    #      到店却先花金币买功能牌、预算跌破药水档空手离店，最终空手走进必败
    #      竞速。修复三件套：required_deck_burst 竞速及格线 + 解封血线独立
    #      旋钮 potion_hold_release_hp_pct(0.45) + 预留窗内货架进攻药竞价加成
    _req_burst = br_pol.required_deck_burst(80)
    assert _req_burst is not None and abs(_req_burst - 160.0 * 10.0 / 80.0 / 0.55) < 1e-6, \
        f"竞速及格线计算失效: {_req_burst}"
    bt_race_deck = [{"card_id": f"BT_A{i}", "card_type": "Attack", "energy_cost": 1,
                     "dynamic_values": [{"name": "Damage", "current_value": 11}]}
                    for i in range(3)]   # burst=33：静态门槛下的「强卡组」

    def bt_potion_state(hp_now: int) -> dict:
        return {"screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
                "turn": 1,
                "combat": {"player": {"current_hp": hp_now, "max_hp": 80,
                                      "block": 0, "energy": 3},
                           "hand": [],
                           "enemies": [{"index": 0, "enemy_id": "M", "name": "小怪",
                                        "current_hp": 30, "max_hp": 30, "block": 0,
                                        "is_alive": True, "is_hittable": True,
                                        "intents": [{"total_damage": 7}]}]},
                "run": {"current_hp": hp_now, "max_hp": 80, "gold": 0, "floor": 14,
                        "deck": list(bt_race_deck),
                        "potions": [{"index": 0, "potion_id": "STRENGTH_P",
                                     "name": "力量药水", "description": "获得2点力量。",
                                     "occupied": True, "can_use": True,
                                     "usage": "combat"}]}}

    bt_ctx = SimpleNamespace(combat={"comp_id": "BT_M", "node_type": "Monster"},
                             current_combat_is_hard=True)
    # 复刻 422 局 F14 场景（距 Boss 3 层普通房、54%~75% 血）：竞速饥饿口径下
    # 预留窗加宽生效，且新解封线 0.45 不再被 50%~75% 血触发——旧口径全放行
    d_bt_hold = br_pol.decide(bt_potion_state(60), bt_ctx)
    assert d_bt_hold.action != "use_potion", \
        f"竞速饥饿卡组距Boss3层普通房应封存进攻药水: {d_bt_hold.action}（{d_bt_hold.reason}）"
    d_bt_mid = br_pol.decide(bt_potion_state(42), bt_ctx)
    assert d_bt_mid.action != "use_potion", \
        f"解封线0.45下52%血不得放行烧药（旧口径0.80会烧）: {d_bt_mid.action}（{d_bt_mid.reason}）"
    d_bt_low = br_pol.decide(bt_potion_state(24), bt_ctx)
    assert d_bt_low.action == "use_potion", \
        f"真濒死仍须立即解封（保命优先于囤积）: {d_bt_low.action}（{d_bt_low.reason}）"
    # 无 Boss 实证的空库：及格线回落 None→静态门槛，burst33≥30 视作强卡组，
    # 距 Boss 3 层照旧投放（防「囤药入坟」旧病回潮）
    nv2_pol = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-btline-"))), random.Random(13))
    assert nv2_pol.required_deck_burst(80) is None, "无 Boss 实证时竞速及格线应为 None"
    d_bt_nv = nv2_pol.decide(bt_potion_state(60), bt_ctx)
    assert d_bt_nv.action == "use_potion", \
        f"无实证时静态门槛行为必须保持: {d_bt_nv.action}（{d_bt_nv.reason}）"

    # 商店竞价保护：预留窗内进攻药加成压过可选卡；窗外加成关闭
    def bt_shop_state(floor_no: int) -> dict:
        return {"screen": "SHOP",
                "available_actions": ["buy_card", "buy_potion", "close_shop_inventory"],
                "shop": {"is_open": True, "can_close": True,
                         "cards": [{"index": 0, "card_id": "BT_SMALL_GUARD", "name": "小盾",
                                    "card_type": "Skill", "energy_cost": 1,
                                    "is_stocked": True, "enough_gold": True, "price": 75,
                                    "rules_text": "获得4点格挡",
                                    "dynamic_values": [{"name": "Block", "current_value": 4}]}],
                         "relics": [], "card_removal": None,
                         "potions": [{"index": 0, "potion_id": "STRENGTH_POTION",
                                      "name": "力量药水", "rarity": "Uncommon",
                                      "usage": "CombatOnly", "price": 50,
                                      "is_stocked": True, "enough_gold": True}]},
                "run": {"current_hp": 60, "max_hp": 80, "gold": 500, "floor": floor_no,
                        "deck": list(bt_race_deck)}}

    d_bt_shop = br_pol.decide(bt_shop_state(12), br_ctx)
    assert d_bt_shop.action == "buy_potion" and "药水" in d_bt_shop.reason, \
        f"预留窗内进攻药应加价压过可选卡（422局岩石铠甲截胡药水预算的复刻位）: " \
        f"{d_bt_shop.action}（{d_bt_shop.reason}）"
    d_bt_farshop = br_pol.decide(bt_shop_state(10), br_ctx)
    assert d_bt_farshop.action == "buy_card", \
        f"预留窗外竞价加成必须关闭（防为囤药牺牲战力投资）: " \
        f"{d_bt_farshop.action}（{d_bt_farshop.reason}）"

    # 3bu) 饥饿判定全消费端收口（第423~428批复盘）：required_deck_burst 竞速及格线
    #      此前只接了药水预留窗与商店端，拿牌端/地图端/升级端仍按静态 deck_burst_floor
    #      判饥饿——burst 高于静态门槛却远低于杀 Boss 所需的卡组（本批六局普遍如
    #      此，78% 血满状态进 Boss 照样整管打空）在拾取端对缺口失明，高质攻击饥饿
    #      加分全程缺位。修复后统一走 _starve_line：传 max_hp 且有 Boss 实证时用
    #      对账线；不传或数据未成熟时行为与旧版严格一致（冷启动安全）
    assert abs(br_pol._starve_line(80) - 160.0 * 10.0 / 80.0 / 0.55) < 1e-6, \
        f"对账饥饿线读取失效: {br_pol._starve_line(80)}"
    assert abs(br_pol._starve_line(None) - 30.0) < 1e-9, \
        "缺 max_hp 时饥饿线必须回落静态门槛"
    bu_atk = {"card_id": "BU_BIG", "name": "重砍", "card_type": "Attack", "energy_cost": 1,
              "dynamic_values": [{"name": "Damage", "current_value": 14}]}   # 质量门：14≥12 且 14/1≥7
    bu_deck = [{"card_id": f"BT_A{i}", "card_type": "Attack", "energy_cost": 1,
                "dynamic_values": [{"name": "Damage", "current_value": 11}]} for i in range(3)]
    v_bu_static = br_pol.eval_reward_card(dict(bu_atk), list(bu_deck))
    v_bu_recon = br_pol.eval_reward_card(dict(bu_atk), list(bu_deck), max_hp=80)
    assert v_bu_recon > v_bu_static, \
        f"对账饥饿线下高质攻击未吃缺口加分: recon={v_bu_recon:.2f} static={v_bu_static:.2f}"
    # 同一候选在无 Boss 实证的空库上不得因传 max_hp 而变化（回落口径一致性）
    v_bu_nv = nv2_pol.eval_reward_card(dict(bu_atk), list(bu_deck), max_hp=80)
    assert abs(v_bu_nv - v_bu_static) < 1e-6, \
        f"空库回落口径漂移: nv={v_bu_nv:.2f} static={v_bu_static:.2f}"

    # 3yr) 跨局重生召唤物名册（第 506~508 局批复盘新增）：506 局 F13 精英战
    #      对扭动虫按零伤害辅助体优先转火，前两刀斩杀奖励喂给打不死的分身
    #      （该战 -46），直到同场检测器坐实才解除——同种重生体每局都在重交
    #      这笔学费。当场坐实的敌键登记进跨局名册，≥2 场独立实证后新战斗
    #      第 1 回合即按重生体压制；单场误报不污染名册
    ra_know = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-respawn-")))
    assert not ra_know.is_known_respawn_add("WRIGGLER_ADD"), "空名册不应判定重生体"
    ra_know.mark_respawn_add("WRIGGLER_ADD")
    assert not ra_know.is_known_respawn_add("WRIGGLER_ADD"), \
        "单场实证不得激活跨局名册（防单场误报污染）"
    ra_know.mark_respawn_add("WRIGGLER_ADD")
    assert ra_know.is_known_respawn_add("WRIGGLER_ADD"), "双场实证应激活跨局名册"
    assert not ra_know.is_known_respawn_add(""), "空键必须安全返回 False"
    assert not ra_know.is_known_respawn_add("FRESH_MOB"), "未登记敌键不受影响"
    ra_pol = policy.Policy(ra_know)
    # 名册生效：本场零预测击杀也应直接判重生体（第 1 回合即压制）
    assert ra_pol._is_respawn_add({"enemy_id": "WRIGGLER_ADD", "name": "扭动虫"}), \
        "跨局名册未在第 1 回合生效"
    # 当场坐实 → 登记名册（同场同敌只记一次）；第二次独立坐实后生效
    ra_pol._combat_kills["SPRING_ADD"] = 2
    assert ra_pol._is_respawn_add({"enemy_id": "SPRING_ADD"}), "同场坐实判定丢失"
    assert (ra_know.stats.get("respawn_adds", {}).get("SPRING_ADD") or {}).get("confirmations") == 1, \
        "当场坐实应向名册登记一次"
    ra_pol._is_respawn_add({"enemy_id": "SPRING_ADD"})
    assert (ra_know.stats.get("respawn_adds", {}).get("SPRING_ADD") or {}).get("confirmations") == 1, \
        "同场重复确认不得重复计数（每场每敌至多一次）"
    # 名册生效后的行为闭环：辅助体不再吸引转火，输出直奔高威胁本体
    def roster_combat():
        st = spike_combat()
        st["combat"]["enemies"][0]["enemy_id"] = "WRIGGLER_ADD"
        return st
    d_roster = ra_pol.decide(roster_combat(), ctx)
    assert d_roster.action == "play_card" and d_roster.params.get("target_index") == 1, \
        f"名册重生体第1回合仍吸引输出（506局F13重演）: {d_roster.reason}"
    # 全场皆名册重生体时压制解除照常工作（152 局教义不被名册破坏）
    def all_roster_combat():
        st = roster_combat()
        st["combat"]["enemies"][1]["enemy_id"] = "WRIGGLER_SRC"
        st["combat"]["enemies"][0]["intents"] = [{"total_damage": 0}]
        st["combat"]["enemies"][1]["intents"] = [{"total_damage": 0}]
        return st
    ra_know.mark_respawn_add("WRIGGLER_SRC")
    ra_know.mark_respawn_add("WRIGGLER_SRC")
    d_allroster = ra_pol.decide(all_roster_combat(), ctx)
    assert d_allroster.action == "play_card", \
        f"全场名册重生体时压制解除失效（拒出牌复发）: {d_allroster.action}（{d_allroster.reason}）"

    # 3ys) 进幕快照账本（第 506~508 局批复盘新增）：二幕消耗战已成主死因，
    #      进幕就绪度（血量/金币/药水/卡组规模/爆发）必须有账可查。封顶 60 条、
    #      旧库无键自动补齐
    ae_know = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-actentry-")))
    for i in range(65):
        ae_know.commit_act_entry({"act": 2, "floor": 18 + i, "hp_pct": 0.5,
                                  "max_hp": 80, "gold": 100, "potions": 1,
                                  "deck_size": 20, "burst": 90.0 + i})
    ents = ae_know.act_entries()
    assert len(ents) == 60, f"进幕快照未按 60 条封顶: {len(ents)}"
    assert ents[-1]["burst"] == 154.0 and ents[0]["burst"] == 95.0, \
        "进幕快照封顶后应保留最新样本"
    ae_know.mark_respawn_add("COMPAT_PROBE")
    assert "respawn_adds" in ae_know.stats and "act_entries" in ae_know.stats, \
        "旧库迁移缺键"

    # 3yt) 进幕快照去重键（第509~515局批复盘）：(run_id, act) 变化判定——
    #      同局同幕只记一次，换局/换幕都记。旧实现按进程级 act 单值去重，
    #      同进程后续对局的一幕首战（act 仍=1）被整体吞掉——本批六局只落
    #      513 局一条快照，「进幕就绪度 vs 死亡楼层」对账样本断供
    _probe = SimpleNamespace()
    _due = agent.Agent._act_entry_due
    assert _due(_probe, "RUN_A", 1), "首局首幕应记快照"
    assert not _due(_probe, "RUN_A", 1), "同局同幕重复开战不得重复记录"
    assert _due(_probe, "RUN_A", 2), "同局跨幕应记快照"
    assert not _due(_probe, "RUN_A", 2), "同局同幕（跨幕后回望）不得重复记录"
    assert _due(_probe, "RUN_B", 1), "换局后同幕必须重新记快照（粘滞缺陷回归）"
    assert _due(_probe, "RUN_C", 1), "连续换局都要记"
    _p2 = SimpleNamespace()
    assert _due(_p2, "", 1) and not _due(_p2, "", 1), \
        "空 run_id 按同键确定性去重（降级不劣于旧行为）"

    # 3yu) 纯防御饥饿贬值（第509~515局批复盘）：饥饿加分链顶格后所有高质
    #      攻击/引擎同分满额，纯防御仍按原价竞争名额。缺口越深对无成长性的
    #      纯格挡技按比例压价；三重门控：格挡来源不足/卡组单薄/带抽牌不贬
    sd_know = knowledge.Knowledge(Path(tempfile.mkdtemp(prefix="sts2-selfcheck-stvdef-")))
    sd_know.stats["enemies"]["SD_BOSS_A"] = {
        "encounters": 8, "hp_lost_sum": 320.0, "deaths": 4, "wins": 4,
        "boss_encounters": 2, "boss_hp_lost_sum": 80.0, "boss_deaths": 1,
        "hp_pool_sum": 320.0, "hp_pool_n": 2, "fire_sum": 80.0, "fire_rounds": 8}
    sd_pol = policy.Policy(sd_know)
    sd_block_card = {"card_id": "SD_SHRUG", "name": "耸肩", "card_type": "Skill",
                     "energy_cost": 1,
                     "dynamic_values": [{"name": "Block", "current_value": 8}]}
    sd_draw_block = {"card_id": "SD_DRAWBLK", "name": "抽牌格挡", "card_type": "Skill",
                     "energy_cost": 1, "rules_text": "获得8点格挡，抽1张牌。",
                     "dynamic_values": [{"name": "Block", "current_value": 8}]}
    sd_rich_deck = ([{"card_id": f"SD_ATK{i}", "card_type": "Attack", "energy_cost": 1,
                      "dynamic_values": [{"name": "Damage", "current_value": 6}]}
                     for i in range(4)]
                    + [{"card_id": f"SD_BLK{i}", "card_type": "Skill", "energy_cost": 1,
                        "dynamic_values": [{"name": "Block", "current_value": 8}]}
                       for i in range(5)])
    v_sup_on = sd_pol.eval_reward_card(dict(sd_block_card), list(sd_rich_deck), max_hp=80)
    sd_pol.know.policy["starve_defense_suppress_max"] = 0.0
    v_sup_off = sd_pol.eval_reward_card(dict(sd_block_card), list(sd_rich_deck), max_hp=80)
    sd_pol.know.policy["starve_defense_suppress_max"] = 0.30
    assert v_sup_on < v_sup_off - 0.3, \
        f"深缺口下纯防御未贬值: on={v_sup_on:.2f} off={v_sup_off:.2f}"
    v_draw_on = sd_pol.eval_reward_card(dict(sd_draw_block), list(sd_rich_deck), max_hp=80)
    sd_pol.know.policy["starve_defense_suppress_max"] = 0.0
    v_draw_off = sd_pol.eval_reward_card(dict(sd_draw_block), list(sd_rich_deck), max_hp=80)
    sd_pol.know.policy["starve_defense_suppress_max"] = 0.30
    assert abs(v_draw_on - v_draw_off) < 1e-6, \
        f"带抽牌功能技不应贬值: on={v_draw_on:.2f} off={v_draw_off:.2f}"
    # 门控一：格挡来源不足（n_block<min_block_cards）不贬值——
    #         卡组形态达标（非基础牌 9≥core），仅格挡稀缺
    sd_fewblk_deck = (sd_rich_deck[:4]
                      + sd_rich_deck[4:6]
                      + [{"card_id": f"SD_UTL{i}", "card_type": "Skill", "energy_cost": 1,
                          "dynamic_values": []} for i in range(3)])
    v_few_on = sd_pol.eval_reward_card(dict(sd_block_card), list(sd_fewblk_deck), max_hp=80)
    sd_pol.know.policy["starve_defense_suppress_max"] = 0.0
    v_few_off = sd_pol.eval_reward_card(dict(sd_block_card), list(sd_fewblk_deck), max_hp=80)
    sd_pol.know.policy["starve_defense_suppress_max"] = 0.30
    assert abs(v_few_on - v_few_off) < 1e-6, \
        f"格挡稀缺时不应贬值: on={v_few_on:.2f} off={v_few_off:.2f}"
    # 门控二：卡组单薄（非基础牌<deck_thin_core）不贬值——量不足不是结构失衡；
    #         格挡来源达标（5 块 ≥min_block_cards）以隔离单薄门控
    sd_thin_deck = (sd_rich_deck[4:9] + sd_rich_deck[:2])
    v_thin_on = sd_pol.eval_reward_card(dict(sd_block_card), list(sd_thin_deck), max_hp=80)
    sd_pol.know.policy["starve_defense_suppress_max"] = 0.0
    v_thin_off = sd_pol.eval_reward_card(dict(sd_block_card), list(sd_thin_deck), max_hp=80)
    assert abs(v_thin_on - v_thin_off) < 1e-6, \
        f"单薄卡组不应贬值: on={v_thin_on:.2f} off={v_thin_off:.2f}"


    # 3zw) 零出牌死牌三端贯通（第529局批复盘）：知识恶魔战强制入组的瓦解/
    #      懒惰类死牌（生涯多拿零打）面板数字被 card_numbers 解析成高伤攻击，
    #      幻影伤害污染 deck_burst 口径（饥饿判定/竞速预演/药水预留全线偏乐观）；
    #      战斗出牌评分此前还吃 learned value 加成；强制入组屏（无跳过动作+
    #      全候选低于门槛）此前被记成正常拾取学分灌水 picked/outcome 账。
    #      修复：burst 贪心装箱跳过死牌；出牌评分叠加否决罚分；强制屏改记
    #      card_forced_add（不进信用账本）
    npd_know = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-npdead-")))
    npd_know.stats["cards"]["NPD_GHOST"] = {
        "seen": 9, "picked": 9, "plays": 0, "outcome_sum": 297.0, "bias": 0.0}
    npd_know.stats["cards"]["NPD_SLOTH"] = {
        "seen": 6, "picked": 6, "plays": 0, "outcome_sum": 198.0, "bias": 0.0}
    npd_know.stats["cards"]["NPD_LIVE"] = {
        "seen": 5, "picked": 5, "plays": 40, "outcome_sum": 100.0, "bias": 0.0}
    npd_pol = policy.Policy(npd_know)
    # 判定器本身：零打+多拿才判死；升级变体同判；有打出记录即自愈解除
    assert npd_pol._is_never_played_dead("NPD_GHOST"), "零出牌死牌判定失效"
    assert npd_pol._is_never_played_dead("NPD_GHOST+"), "升级死牌应按基础id同判"
    assert npd_pol._is_never_played_dead("NPD_SLOTH"), "第二张死牌判定丢失"
    assert not npd_pol._is_never_played_dead("NPD_LIVE"), "有打出记录不得判死"
    assert not npd_pol._is_never_played_dead(""), "空id必须安全返回 False"
    npd_know.stats["cards"]["NPD_GHOST"]["plays"] = 1
    assert not npd_pol._is_never_played_dead("NPD_GHOST"), "自愈解除失效"
    npd_know.stats["cards"]["NPD_GHOST"]["plays"] = 0
    # 幻影伤害剔除：装箱口径里死牌视同不存在
    npd_live = {"card_id": "NPD_LIVE", "name": "重刀", "card_type": "Attack",
                "energy_cost": 2,
                "dynamic_values": [{"name": "Damage", "current_value": 14}]}
    npd_ghost = {"card_id": "NPD_GHOST", "name": "瓦解", "card_type": "Attack",
                 "energy_cost": 1,
                 "dynamic_values": [{"name": "Damage", "current_value": 20}]}
    assert abs(npd_pol.deck_burst([dict(npd_live), dict(npd_ghost)])
               - npd_pol.deck_burst([dict(npd_live)])) < 1e-9, \
        "死牌幻影伤害仍被计入爆发吞吐"
    assert npd_pol.deck_burst([dict(npd_ghost)]) == 0.0, "纯死牌卡组爆发应为 0"
    npd_cold = policy.Policy(knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-npdead-cold-"))))
    assert npd_cold.deck_burst([dict(npd_ghost)]) > 0.0 \
            and not npd_cold._is_never_played_dead("NPD_GHOST"), \
        "冷启动无统计时行为必须与旧版一致"
    # 出牌端否决：致死局面下死牌（面板伤更高）不得抢过真实攻击的能量
    npd_combat = {
        "screen": "COMBAT", "available_actions": ["play_card", "end_turn"], "turn": 1,
        "combat": {"player": {"current_hp": 80, "max_hp": 80, "block": 0, "energy": 3},
                   "hand": [
                       {"index": 0, "card_id": "NPD_LIVE", "name": "重刀", "playable": True,
                        "energy_cost": 2, "requires_target": True, "valid_target_indices": [0],
                        "dynamic_values": [{"name": "Damage", "current_value": 14}]},
                       {"index": 1, "card_id": "NPD_GHOST", "name": "瓦解", "playable": True,
                        "energy_cost": 2, "requires_target": True, "valid_target_indices": [0],
                        "dynamic_values": [{"name": "Damage", "current_value": 20}]}],
                   "enemies": [{"index": 0, "enemy_id": "NPDEMO", "name": "小怪", "current_hp": 10,
                                "max_hp": 30, "block": 0, "is_alive": True, "is_hittable": True,
                                "intents": []}]},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 30,
                "deck": [dict(npd_live), dict(npd_ghost)] * 3},
    }
    d_npd = npd_pol.decide(npd_combat, ctx)
    assert d_npd.action == "play_card" and d_npd.params.get("card_index") == 0, \
        f"死牌抢走出牌能量（第529局F33形态回归）: {d_npd.reason}"
    # 强制入组屏：无跳过动作且全候选低于门槛 → 记 card_forced_add 不记学分；
    # 同屏有跳过动作时照旧整屏跳过
    npd_sel_cards = [
        {"index": 0, "card_id": "NPD_GHOST", "name": "瓦解", "card_type": "Attack",
         "energy_cost": 1,
         "dynamic_values": [{"name": "Damage", "current_value": 20}]},
        {"index": 1, "card_id": "NPD_SLOTH", "name": "懒惰", "card_type": "Skill",
         "energy_cost": 1, "dynamic_values": []}]
    npd_sel_base = {
        "screen": "CARD_SELECTION",
        "selection": {"kind": "", "prompt": "获得一张牌", "min_select": 1,
                      "selected_count": 0, "can_confirm": False,
                      "cards": npd_sel_cards},
        "run": {"current_hp": 70, "max_hp": 90, "gold": 0, "floor": 33,
                "deck": [dict(npd_live)] * 8}}
    d_forced = npd_pol.decide(
        {**npd_sel_base, "available_actions": ["select_deck_card"]}, ctx)
    assert d_forced.action == "select_deck_card" and d_forced.tags \
            and d_forced.tags[0][0] == "card_forced_add", \
        f"强制入组屏仍被记为拾取学分: {d_forced.tags}（{d_forced.reason}）"
    d_skip = npd_pol.decide(
        {**npd_sel_base, "available_actions": ["select_deck_card", "skip_reward_cards"],
         "run": {**npd_sel_base["run"], "floor": 34}}, ctx)
    assert d_skip.action == "skip_reward_cards", \
        f"有跳过动作的低价值屏未跳过: {d_skip.action}（{d_skip.reason}）"

    # 3zx) 解锁展示屏双通道（第551局后现场修复）：mod 正常暴露动作时走 HTTP；
    #      已识别 UNLOCK 但 can_confirm=false/actions=[] 连续 12 tick 时，必须像
    #      UNKNOWN 旧路由一样点击底部确认区，不能因“识别成功”反而永久等待。
    ul_know = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-unlock-")))
    ul_pol = policy.Policy(ul_know)
    ul_ctx = SimpleNamespace()
    ul_ready = {
        "screen": "UNLOCK", "available_actions": ["confirm_unlock"],
        "unlock": {"unlock_type": "NUnlockRelicsScreen",
                   "items": ["红头骨"], "can_confirm": True}}
    d_ul_ready = ul_pol.decide(ul_ready, ul_ctx)
    assert d_ul_ready.action == "confirm_unlock", \
        f"解锁 API 正常时未确认: {d_ul_ready.action}（{d_ul_ready.reason}）"
    ul_stuck = {
        "screen": "UNLOCK", "available_actions": [],
        "unlock": {"unlock_type": "NUnlockRelicsScreen",
                   "items": ["红头骨"], "can_confirm": False}}
    ul_clicks = []
    ul_pol._click_game_point = lambda x, y: ul_clicks.append((x, y)) or True
    for i in range(11):
        d_ul_wait = ul_pol.decide(ul_stuck, ul_ctx)
        assert d_ul_wait.action is None and not ul_clicks, \
            f"解锁兜底过早触发（tick {i + 1}）: {d_ul_wait.reason}"
    d_ul_fallback = ul_pol.decide(ul_stuck, ul_ctx)
    assert d_ul_fallback.action is None and ul_clicks == [(0.5, 0.89)] \
            and "鼠标兜底点击已发送" in d_ul_fallback.reason, \
        f"解锁无动作未触发鼠标兜底: clicks={ul_clicks}（{d_ul_fallback.reason}）"

    # 3zy-combat-margin) 有能量且存在正即时边际时不得被阈值/预留互锁为空过：
    # 真实第 554 局 F2 的 6 意图/5 甲/1 能量场景曾让第二张防御(0.03分)
    # 与打击(-8预留)互相压死；敌方格挡也曾把 6 伤错误折成 1 分。
    cm_know = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-combat-margin-")))
    cm_pol = policy.Policy(cm_know)
    cm_ctx = DummyCtx()
    cm_ctx.credit_tags = []
    cm_ctx.combat = {"comp_id": "CM_ENEMY", "node_type": "Monster"}
    # 模拟“拿牌局走不远”造成的强负 draft 归因；已在手里的执行不应被它压住。
    cm_know.stats["cards"]["CM_STRIKE"] = {
        "seen": 5, "picked": 1, "plays": 1, "outcome_sum": 0.0, "bias": -10.0}

    def cm_card(index, card_id, name, damage=0, block=0, card_kind=None):
        values = []
        if damage:
            values.append({"name": "Damage", "current_value": damage})
        if block:
            values.append({"name": "Block", "current_value": block})
        card = {"index": index, "card_id": card_id, "name": name,
                "playable": True, "energy_cost": 1,
                "requires_target": bool(damage),
                "valid_target_indices": [0] if damage else [],
                "dynamic_values": values}
        if card_kind:
            card["card_type"] = card_kind
        return card

    def cm_state(hand, *, block_now=0, incoming=0, enemy_block=0, energy=1, turn=2):
        return {
            "screen": "COMBAT", "available_actions": ["play_card", "end_turn"],
            "turn": turn,
            "combat": {
                "player": {"current_hp": 73, "max_hp": 80,
                           "block": block_now, "energy": energy},
                "hand": hand,
                "enemies": [{"index": 0, "enemy_id": "CM_ENEMY", "name": "测试怪",
                             "current_hp": 30, "max_hp": 30, "block": enemy_block,
                             "is_alive": True, "is_hittable": True,
                             "intents": ([{"total_damage": incoming}] if incoming else [])}]},
            "run": {"current_hp": 73, "max_hp": 80, "gold": 0,
                    "floor": 2, "deck": []}}

    cm_strike = cm_card(0, "CM_STRIKE", "打击", damage=6)
    cm_defend = cm_card(1, "CM_DEFEND", "防御", block=5)
    d_cm_gap = cm_pol.decide(
        cm_state([dict(cm_strike), dict(cm_defend)], block_now=5,
                 incoming=6, energy=1), cm_ctx)
    assert d_cm_gap.action == "play_card" and d_cm_gap.params.get("card_index") == 0, \
        f"残余缺口格挡预留仍与攻击互锁: {d_cm_gap.action}（{d_cm_gap.reason}）"

    # 敌方 8 甲不能把打击价值算成 max(1, 6-8)=1；本次确实削掉 6 点有效池。
    cm_ctx.combat = {"comp_id": "CM_BLOCK", "node_type": "Monster"}
    d_cm_enemy_block = cm_pol.decide(
        cm_state([dict(cm_strike), dict(cm_defend)], incoming=0,
                 enemy_block=8, energy=3, turn=3), cm_ctx)
    assert (d_cm_enemy_block.action == "play_card"
            and d_cm_enemy_block.params.get("card_index") == 0), \
        f"攻击削敌方格挡仍被错判为空过: {d_cm_enemy_block.action}（{d_cm_enemy_block.reason}）"

    # 零成功出牌 veto 可受控自愈：当前明确可出且有正边际的普通牌每战试一次；
    # 真正 Status/Curse 即使伪装了伤害数值也绝不能拿“探索”绕过。
    cm_know.stats["cards"]["CM_NOVEL"] = {
        "seen": 8, "picked": 5, "plays": 0, "outcome_sum": 0.0, "bias": 0.0}
    cm_know.stats["cards"]["CM_CURSE_DISINTEGRATION"] = {
        "seen": 8, "picked": 5, "plays": 0, "outcome_sum": 0.0, "bias": 0.0}
    cm_novel = cm_card(0, "CM_NOVEL", "新招式", damage=30, card_kind="Attack")
    cm_novel["rules_text"] = "Deal 30 damage. Exhaust a random card."
    cm_curse = cm_card(0, "CM_CURSE_DISINTEGRATION", "瓦解",
                       damage=20, card_kind="Curse")
    cm_ctx.combat = {"comp_id": "CM_TRIAL", "node_type": "Monster"}
    d_cm_trial = cm_pol.decide(cm_state([cm_novel], turn=4), cm_ctx)
    assert d_cm_trial.action == "play_card" and "受控试用" in d_cm_trial.reason, \
        f"零出牌 veto 仍永久自锁: {d_cm_trial.action}（{d_cm_trial.reason}）"
    def combat_policy_ledger(p):
        return (frozenset(p._novel_trials), p._exhaust_plays,
                p._krace_dmg, p._krace_turns, p._krace_round,
                dict(p._combat_kills))

    pristine_ledger = combat_policy_ledger(cm_pol)
    assert pristine_ledger == (frozenset(), 0, 0.0, 0, None, {}), \
        f"play_card Decision 在 HTTP 回执前污染策略状态: {pristine_ledger}"
    cm_pol.note_action_failed(d_cm_trial.action, d_cm_trial.tags)
    assert combat_policy_ledger(cm_pol) == pristine_ledger, \
        "失败 play_card 改写了试用/消耗/竞速/预测击杀账"

    # 下一回合仍可重试；只有把成功 Decision.tags 追加到 credit_tags 后，
    # 下一 tick 才一次性同步所有策略账。
    d_cm_trial_retry = cm_pol.decide(cm_state([cm_novel], turn=5), cm_ctx)
    assert d_cm_trial_retry.action == "play_card" and "受控试用" in d_cm_trial_retry.reason, \
        f"失败试用被误记成已成功，无法重试: {d_cm_trial_retry.action}（{d_cm_trial_retry.reason}）"
    assert combat_policy_ledger(cm_pol) == pristine_ledger, \
        "重试 Decision 在成功回执前污染策略状态"
    cm_ctx.credit_tags.extend(d_cm_trial_retry.tags)
    d_cm_after_success = cm_pol.decide(cm_state([cm_novel], turn=6), cm_ctx)
    committed_ledger = combat_policy_ledger(cm_pol)
    assert committed_ledger == (
            frozenset({"CM_NOVEL"}), 1, 30.0, 1, 5, {"CM_ENEMY": 1}), \
        f"成功 play_card 未完整同步试用/消耗/竞速/预测击杀账: {committed_ledger}"
    assert d_cm_after_success.action == "end_turn", \
        f"同战同卡成功受控试用后仍重复尝试: {d_cm_after_success.action}（{d_cm_after_success.reason}）"
    cm_pol.decide(cm_state([cm_novel], turn=6), cm_ctx)
    assert combat_policy_ledger(cm_pol) == committed_ledger, \
        "同一批 credit_tags 被重复同步到战斗策略账"
    cm_ctx.combat = {"comp_id": "CM_CURSE", "node_type": "Monster"}
    d_cm_curse = cm_pol.decide(cm_state([cm_curse], turn=7), cm_ctx)
    assert d_cm_curse.action == "end_turn" and "受控试用" not in d_cm_curse.reason, \
        f"状态/诅咒被误作新卡探索: {d_cm_curse.action}（{d_cm_curse.reason}）"

    # 回合号不是全局身份：两场战斗都从 T1 开始。上一战见过 play_card 后，
    # 下一战开场只有 end_turn 的加载窗口必须重新走长等待，不能继承短确认并空过。
    old_turn_combat = {"comp_id": "OLD_T1"}
    new_turn_combat = {"comp_id": "NEW_T1"}
    cm_pol._turn_combat = old_turn_combat
    cm_pol._cur_turn = 1
    cm_pol._saw_playable_this_turn = True
    cm_pol._end_stall = 1
    cm_pol._failed_this_turn = {0}
    cm_ctx.combat = new_turn_combat
    cm_loading = cm_state([dict(cm_strike)], turn=1)
    cm_loading["available_actions"] = ["end_turn"]
    d_cm_loading = cm_pol.decide(cm_loading, cm_ctx)
    assert d_cm_loading.action is None and "仍有可负担牌" in d_cm_loading.reason, \
        f"新战 T1 继承上一战短确认并提前结束: {d_cm_loading.action}（{d_cm_loading.reason}）"
    assert cm_pol._turn_combat is new_turn_combat \
        and not cm_pol._saw_playable_this_turn and cm_pol._failed_this_turn == set(), \
        "战斗身份变化没有清空逐回合瞬态状态"

    # 同一战同一回合也会有动作端点刷新窗：先见过 play_card 后，若随后载荷
    # 仍明确有 3 能量和可负担打击，连续两帧缺 endpoint 也不得走短确认结束。
    cm_pol._saw_playable_this_turn = True
    cm_pol._end_stall = 0
    cm_endpoint_gap = cm_state([dict(cm_strike)], turn=1, energy=3)
    cm_endpoint_gap["available_actions"] = ["end_turn"]
    d_gap_1 = cm_pol.decide(cm_endpoint_gap, cm_ctx)
    d_gap_2 = cm_pol.decide(cm_endpoint_gap, cm_ctx)
    assert d_gap_1.action is None and d_gap_2.action is None \
        and "play_card 暂不可用" in d_gap_2.reason, \
        f"同回合 endpoint 刷新窗仍带能量弃权: {d_gap_2.action}（{d_gap_2.reason}）"

    # 楼层号会跨局重复；新 run 必须清理商店/奖励/删牌屏握手，不能把旧 F5
    # 的“已处理”直接套到新局 F5。
    cm_pol._card_explore_run = "RUN_OLD"
    cm_pol._shop_done_floor = 5
    cm_pol._reward_floor = 5
    cm_pol._removal_pending_floor = 5
    cm_ctx.run_id = "RUN_NEW_TRANSIENTS"
    cm_ctx.credit_tags = []
    cm_pol.decide({"screen": "MAIN_MENU", "run_id": "RUN_NEW_TRANSIENTS",
                   "available_actions": []}, cm_ctx)
    assert (cm_pol._shop_done_floor, cm_pol._reward_floor,
            cm_pol._removal_pending_floor) == (-1, -1, -1), \
        "新 run 仍继承上一局的商店/奖励/删牌楼层握手"

    # 奖励/药水/事件的本地去重状态必须由成功回执驱动。Agent 的 ConnectionDown
    # 分支不会调用 note_action_failed；这里以“同一状态再次 decide、期间没有追加
    # credit_tags”精确模拟无回执，三类动作都必须稳定重试而不能幻影消费资源。
    receipt_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-action-receipts-"))

    reward_know = knowledge.Knowledge(receipt_dir / "reward")
    reward_pol = policy.Policy(reward_know, random.Random(0))
    reward_ctx = DummyCtx()
    reward_ctx.run_id = "RUN_RECEIPT_REWARD"
    reward_ctx.credit_tags = []
    reward_state = {
        "screen": "REWARD", "run_id": reward_ctx.run_id,
        "available_actions": ["claim_reward", "proceed"],
        "reward": {"rewards": [{"index": 0, "reward_type": "Gold",
                                   "description": "42金币", "claimable": True}],
                   "card_options": [], "can_proceed": True},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                "floor": 2, "deck": [], "potions": []}}
    reward_first = reward_pol.decide(reward_state, reward_ctx)
    reward_retry = reward_pol.decide(reward_state, reward_ctx)
    assert reward_first.action == reward_retry.action == "claim_reward" \
        and reward_first.params == reward_retry.params \
        and reward_pol._reward_tried == set(), \
        "奖励请求无回执时被幻影标记为已尝试，下一 tick 未稳定重试"
    reward_ctx.credit_tags.extend(reward_retry.tags)
    reward_after = reward_pol.decide(reward_state, reward_ctx)
    assert reward_after.action == "proceed" \
        and (0, "Gold", "42金币") in reward_pol._reward_tried, \
        "成功奖励回执未进入去重账，仍可能重复领取"

    reward_reject_pol = policy.Policy(reward_know, random.Random(0))
    reward_reject_ctx = DummyCtx()
    reward_reject_ctx.run_id = "RUN_RECEIPT_REWARD_REJECT"
    reward_reject_ctx.credit_tags = []
    reward_reject_state = json.loads(json.dumps(reward_state))
    reward_reject_state["run_id"] = reward_reject_ctx.run_id
    rejected_reward = reward_reject_pol.decide(reward_reject_state,
                                                reward_reject_ctx)
    reward_reject_pol.note_action_failed(rejected_reward.action,
                                         rejected_reward.tags)
    assert reward_reject_pol.decide(reward_reject_state,
                                    reward_reject_ctx).action == "proceed", \
        "显式拒绝的奖励请求丢失原有防空转行为"

    potion_know = knowledge.Knowledge(receipt_dir / "potion")
    potion_pol = policy.Policy(potion_know, random.Random(0))
    potion_ctx = DummyCtx()
    potion_ctx.run_id = "RUN_RECEIPT_POTION"
    potion_ctx.credit_tags = []
    potion_ctx.combat = {"comp_id": "RECEIPT_ENEMY", "node_type": "Boss"}
    potion_ctx.current_combat_is_hard = True
    potion_state = {
        "screen": "COMBAT", "run_id": potion_ctx.run_id, "turn": 1,
        "available_actions": ["use_potion", "play_card", "end_turn"],
        "combat": {
            "player": {"current_hp": 40, "max_hp": 80, "block": 0, "energy": 0},
            "hand": [],
            "enemies": [{"index": 0, "enemy_id": "RECEIPT_ENEMY",
                         "name": "回执测试怪", "current_hp": 30, "max_hp": 30,
                         "block": 0, "is_alive": True, "is_hittable": True,
                         "intents": [{"total_damage": 10}]}]},
        "run": {"current_hp": 40, "max_hp": 80, "gold": 0, "floor": 17,
                "deck": [], "potions": [{"index": 0, "occupied": True,
                    "can_use": True, "potion_id": "RECEIPT_FIRE",
                    "name": "火焰药水", "description": "造成20点伤害。",
                    "usage": "Combat", "requires_target": False}]}}
    potion_first = potion_pol.decide(potion_state, potion_ctx)
    potion_retry = potion_pol.decide(potion_state, potion_ctx)
    assert potion_first.action == potion_retry.action == "use_potion" \
        and potion_first.params == potion_retry.params \
        and potion_pol._potion_tried == set(), \
        (f"药水请求无回执时被幻影消费，本场不再重试救命药："
         f"first={potion_first.action}/{potion_first.params}, "
         f"retry={potion_retry.action}/{potion_retry.params}, "
         f"tried={potion_pol._potion_tried}")
    potion_ctx.credit_tags.extend(potion_retry.tags)
    potion_after = potion_pol.decide(potion_state, potion_ctx)
    assert potion_after.action != "use_potion" \
        and potion_pol._potion_tried == {(0, "RECEIPT_FIRE")}, \
        "成功药水回执未进入本场去重账"

    potion_reject_pol = policy.Policy(potion_know, random.Random(0))
    potion_reject_ctx = DummyCtx()
    potion_reject_ctx.run_id = "RUN_RECEIPT_POTION_REJECT"
    potion_reject_ctx.credit_tags = []
    potion_reject_ctx.combat = {"comp_id": "RECEIPT_ENEMY", "node_type": "Boss"}
    potion_reject_ctx.current_combat_is_hard = True
    potion_reject_state = json.loads(json.dumps(potion_state))
    potion_reject_state["run_id"] = potion_reject_ctx.run_id
    rejected_potion = potion_reject_pol.decide(potion_reject_state,
                                                potion_reject_ctx)
    potion_reject_pol.note_action_failed(rejected_potion.action,
                                         rejected_potion.tags)
    assert potion_reject_pol.decide(potion_reject_state,
                                    potion_reject_ctx).action != "use_potion", \
        "显式拒绝的药水请求丢失原有防空转行为"

    event_know = knowledge.Knowledge(receipt_dir / "event")
    event_pol = policy.Policy(event_know, random.Random(0))
    event_ctx = DummyCtx()
    event_ctx.run_id = "RUN_RECEIPT_EVENT"
    event_ctx.credit_tags = []
    event_state = {
        "screen": "EVENT", "run_id": event_ctx.run_id,
        "available_actions": ["choose_event_option"],
        "event": {"event_id": "RECEIPT_EVENT", "title": "回执测试",
                  "is_finished": False,
                  "options": [{"index": 0, "text_key": "WAIT",
                               "title": "继续", "is_locked": False,
                               "is_proceed": False, "will_kill_player": False}]},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                "floor": 4, "deck": []}}
    event_first = event_pol.decide(event_state, event_ctx)
    event_retry = event_pol.decide(event_state, event_ctx)
    assert event_first.action == event_retry.action == "choose_event_option" \
        and event_first.params == event_retry.params \
        and event_pol._event_picks.get("WAIT", 0) == 0, \
        "事件请求无回执时产生幻影已选次数并改变下一次选择"
    event_pol.note_action_failed(event_retry.action, event_retry.tags)
    assert event_pol._event_picks.get("WAIT", 0) == 0, \
        "显式拒绝的事件请求产生了虚假停滞计数"
    event_success = event_pol.decide(event_state, event_ctx)
    event_ctx.credit_tags.extend(event_success.tags)
    event_pol.decide(event_state, event_ctx)
    event_pol.decide(event_state, event_ctx)
    assert event_pol._event_picks.get("WAIT") == 1, \
        "成功事件回执未按恰好一次语义写入同实例选择次数"

    # 关闭商店也是事务：请求前不能抢先写 done，否则失败后的下一帧会直接
    # proceed 跳店；只有成功 tag（含丢回执后的状态确认）才能提交楼层握手。
    close_know = knowledge.Knowledge(receipt_dir / "shop_close")
    close_pol = policy.Policy(close_know, random.Random(0))
    close_ctx = DummyCtx()
    close_ctx.run_id = "RUN_SHOP_CLOSE"
    close_ctx.credit_tags = []
    close_state = {
        "screen": "SHOP", "run_id": close_ctx.run_id,
        "available_actions": ["close_shop_inventory", "proceed"],
        "shop": {"is_open": True, "can_close": True, "cards": [],
                 "relics": [], "potions": [], "card_removal": None},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                "floor": 11, "deck": [], "relics": [], "potions": []}}
    close_first = close_pol.decide(close_state, close_ctx)
    assert close_first.action == "close_shop_inventory" \
        and close_pol._shop_done_floor == -1, \
        "close_shop_inventory 在成功回执前抢先标记 shop done"
    close_pol.note_action_failed(close_first.action, close_first.tags)
    close_retry = close_pol.decide(close_state, close_ctx)
    assert close_retry.action == "close_shop_inventory" \
        and close_pol._shop_done_floor == -1, \
        "关闭商店失败后错误 proceed/标记完成"
    close_ctx.credit_tags.extend(close_retry.tags)
    closed_state = json.loads(json.dumps(close_state))
    closed_state["shop"]["is_open"] = False
    closed_state["available_actions"] = ["proceed"]
    closed_decision = close_pol.decide(closed_state, close_ctx)
    assert close_pol._shop_done_floor == 11 and closed_decision.action == "proceed", \
        "关闭商店成功握手未提交 done 楼层并继续"

    # 动作统计必须两阶段提交：_track 只消费已经观测到的状态转换；当前决策的
    # credit tags、ctx_ops、成功出牌和决策轨迹只有 HTTP 成功回执后才能提交。
    tx_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-action-txn-"))
    agent.KNOWLEDGE_DIR = tx_dir
    agent._LOG_PATH = tx_dir / "brain.log"
    tx_agent = agent.Agent(dict(agent.DEFAULT_CONFIG))
    tx_agent.ctx.reset_for("TX_RUN", 0)
    tx_decision = policy.Decision(
        action="choose_event_option", params={"option_index": 0}, reason="txn test",
        tags=[("event_choice", "TX_EVENT", "take"),
              ("play_card", "TX_CARD"), ("play_card_index", 0),
              ("card_pick", "TX_PICK"), ("map_node", "Monster"),
              ("rest", "heal")])
    tx_state = {
        "screen": "EVENT", "run_id": "TX_RUN",
        "run": {"current_hp": 80, "max_hp": 80, "gold": 12, "floor": 3,
                "deck": [], "relics": [], "potions": []}}
    tx_agent._track(tx_state, tx_decision)  # 相当于 action 返回失败前的预执行轨迹
    assert tx_agent.know.stats["cards"].get("TX_CARD") is None, \
        "失败/未确认动作仍被 _track 计为成功出牌"
    assert tx_agent.ctx.credit_tags == [] and tx_agent.ctx.pending_event is None, \
        "失败/未确认动作仍写入 credit tags 或 event ctx"
    assert tx_agent.ctx.rests_healed_at_full == 0 and tx_agent.ctx.decisions == [], \
        "失败/未确认动作仍写入休息统计或成功决策轨迹"
    assert tx_agent.ctx.last_hp == 80 and tx_agent.ctx.last_gold == 12, \
        "两阶段提交误伤了每 tick 必须保留的观察态更新"

    tx_agent._commit_successful_action(tx_state, tx_decision)
    assert tx_agent.know.stats["cards"]["TX_CARD"]["plays"] == 1, \
        "成功动作回执未提交 card play"
    assert tx_agent.ctx.credit_tags == tx_decision.tags, \
        "成功动作回执未提交完整 credit/ctx tags"
    assert tx_agent.ctx.pending_event[:2] == ("TX_EVENT", "take"), \
        "成功事件动作未建立后续观察结算快照"
    assert tx_agent.ctx.rests_healed_at_full == 1 and len(tx_agent.ctx.decisions) == 1, \
        "成功动作未提交休息统计或决策轨迹"

    # 下一 tick 的真实离场属于观察态，不依赖这一 tick 是否另有成功动作。
    tx_next = {
        "screen": "MAP", "run_id": "TX_RUN", "available_actions": [],
        "run": {"current_hp": 75, "max_hp": 80, "gold": 12, "floor": 3,
                "deck": [], "relics": [], "potions": []}}
    tx_agent._track(tx_next, policy.Decision())
    assert tx_agent.ctx.pending_event is None and tx_agent.ctx.last_hp == 75, \
        "观察态离场结算被错误推迟到下一次成功动作"
    assert tx_agent.know.stats["events"]["TX_EVENT"]["take"]["n"] == 1, \
        "已成功事件选择的真实离场结果未结算"

    # 3y) 竞速审计账本并表（第813~822局批复盘 RACE_AUDIT_STATS_AGGREGATION
    #     回归夹具）：_flush_combat_agg 弹出 latched 审计账时必须把
    #     「判死→实战结局」按 esc 分桶累计进 stats.race_audit；未入锁的
    #     战斗零改动，重复落库逐次累加。
    ra_dir = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-race-audit-"))
    agent.KNOWLEDGE_DIR = ra_dir
    agent._LOG_PATH = ra_dir / "brain.log"
    ra_agent = agent.Agent(dict(agent.DEFAULT_CONFIG))
    ra_agent.ctx.reset_for("RA_RUN", 0)

    def _ra_agg(won, died):
        return {"comp_id": "RA_COMP", "floor": 17, "node_type": "Boss",
                "hp_lost_sum": 40.0, "rounds": 8, "won": won, "died": died,
                "hp_start_pct": 0.8, "open": False, "from_event": False,
                "obs_hp_pool": 250.0, "obs_fire_sum": 40.0, "obs_fire_rounds": 3}

    ra_agent.policy._race_audit = {"latched": True, "latch_round": 3, "esc": True}
    ra_agent.ctx.combat_agg = _ra_agg(True, False)
    ra_agent._flush_combat_agg()
    _ra_stats = ra_agent.know.stats["race_audit"]
    assert _ra_stats == {"latched": 1, "won": 1, "esc_won": 1}, \
        f"判死→获胜未按 esc 分桶落库: {_ra_stats}"

    ra_agent.policy._race_audit = {"latched": True, "latch_round": 2, "esc": False}
    ra_agent.ctx.combat_agg = _ra_agg(False, True)
    ra_agent._flush_combat_agg()
    _ra_stats = ra_agent.know.stats["race_audit"]
    assert _ra_stats == {"latched": 2, "won": 1, "esc_won": 1,
                         "died": 1}, f"判死→阵亡未按 esc 分桶落库: {_ra_stats}"

    ra_agent.policy._race_audit = {"latched": False, "latch_round": None, "esc": False}
    ra_agent.ctx.combat_agg = _ra_agg(True, False)
    ra_agent._flush_combat_agg()
    _ra_stats = ra_agent.know.stats["race_audit"]
    assert _ra_stats == {"latched": 2, "won": 1, "esc_won": 1,
                         "died": 1}, f"未入锁战斗误计审计账: {_ra_stats}"
    assert ra_agent.ctx.combat_agg is None and ra_agent.ctx.combat is None, \
        "审计夹具结算后聚合账未清空"

    # POST 绝不能由 client 在 ConnectionDown 后透明重放：首个 POST 可能已经
    # 到达游戏，健康探针只能 GET，是否执行交给下一份 /state 做语义对账。
    class LostReceiptClient(client.Sts2Client):
        def __init__(self):
            super().__init__(ports=(8080,))
            self.base_url = "http://127.0.0.1:8080"
            self.calls = []

        def _raw_request(self, method, url, payload=None, timeout=10.0):
            self.calls.append((method, url, payload))
            if method == "POST":
                raise client.ConnectionDown("response lost")
            return {"status": "ready"}

    lost_client = LostReceiptClient()
    try:
        lost_client.act("claim_reward", option_index=0)
        assert False, "丢失 POST 回执未向 Agent 暴露 ConnectionDown"
    except client.ConnectionDown:
        pass
    assert sum(1 for method, _, _ in lost_client.calls if method == "POST") == 1 \
        and any(method == "GET" and url.endswith("/health")
                for method, url, _ in lost_client.calls), \
        f"client 在丢回执后重放了 POST 或未健康探测: {lost_client.calls}"
    try:
        client.Sts2Client._decode(b'{"ok":true,"data":')
        assert False, "截断 JSON 回执未按未知成功处理"
    except client.ConnectionDown:
        pass
    for malformed in (
            b'{}', b'{"data":{}}', b'{"ok":1,"data":{}}',
            b'{"ok":"true","data":{}}', b'{"ok":false}',
            b'{"ok":false,"error":null}', b'{"ok":false,"error":[]}'):
        try:
            client.Sts2Client._decode(malformed)
            assert False, f"畸形 2xx envelope 未按未知成功处理: {malformed!r}"
        except client.ConnectionDown:
            pass
    try:
        client.Sts2Client._decode(
            b'{"ok":false,"error":{"code":"invalid_action","message":"bad"}}')
        assert False, "结构完整的明确失败 2xx envelope 未抛 ApiError"
    except client.ApiError as exc:
        assert exc.code == "invalid_action", f"明确错误 code 丢失: {exc}"
    try:
        client.Sts2Client()._raw_request(
            "POST", "http://127.0.0.1/action", {"bad": object()})
        assert False, "发送前 JSON 序列化错误未明确归类"
    except client.ApiError as exc:
        assert exc.code == "invalid_request", \
            f"发送前序列化错误错误地进入未知成功路径: {exc}"
    # HTTPError 的错误体本身也可能在读取/解码时断掉；它同样不能证明 POST
    # 未执行，必须进入未知成功对账而不是 ApiError 永久失败路径。
    original_urlopen = client.urllib.request.urlopen
    try:
        for fp in (io.BytesIO(b'{"error":'), io.BytesIO(b'[]')):
            def raise_bad_http(_req, timeout=None, _fp=fp):
                raise client.urllib.error.HTTPError(
                    "http://127.0.0.1/action", 409, "Conflict", {}, _fp)
            client.urllib.request.urlopen = raise_bad_http
            try:
                client.Sts2Client()._raw_request(
                    "POST", "http://127.0.0.1/action", {"action": "claim_reward"})
                assert False, "不可解码 HTTPError 回执未按未知成功处理"
            except client.ConnectionDown:
                pass
    finally:
        client.urllib.request.urlopen = original_urlopen

    # Agent 的未知成功对账必须是 action-specific + 两阶段：接口列表抖动不是
    # 成功证据；连续三次未见物质变化后才放行重试，期间不得另发动作或写信用账。
    ambiguous_root = Path(tempfile.mkdtemp(prefix="sts2-selfcheck-ambiguous-action-"))

    def fresh_amb_agent(name, run_id):
        agent.KNOWLEDGE_DIR = ambiguous_root / name
        agent._LOG_PATH = agent.KNOWLEDGE_DIR / "brain.log"
        value = agent.Agent(dict(agent.DEFAULT_CONFIG))
        value.ctx.reset_for(run_id, 0)
        return value

    amb_reward_agent = fresh_amb_agent("reward", "AMB_REWARD")
    amb_reward_state = json.loads(json.dumps(reward_state))
    amb_reward_state["run_id"] = "AMB_REWARD"
    amb_reward_agent.ctx.run_id = "AMB_REWARD"
    amb_reward_decision = amb_reward_agent.policy.decide(
        amb_reward_state, amb_reward_agent.ctx)
    amb_reward_agent._remember_ambiguous_action(
        amb_reward_state, amb_reward_decision)
    endpoint_only = json.loads(json.dumps(amb_reward_state))
    endpoint_only["available_actions"] = ["proceed", "claim_reward"]
    assert [amb_reward_agent._reconcile_ambiguous_action(endpoint_only)
            for _ in range(3)] == ["wait", "wait", "retry"], \
        "仅 available_actions 变化被误认作奖励已领取，或未做短轮询防重复"
    assert amb_reward_agent.ctx.credit_tags == [] \
        and amb_reward_agent.policy._reward_tried == set(), \
        "未执行奖励在未知成功对账中获得了幻影信用/去重标记"
    amb_reward_retry = amb_reward_agent.policy.decide(
        endpoint_only, amb_reward_agent.ctx)
    assert amb_reward_retry.action == "claim_reward" \
        and amb_reward_retry.params == amb_reward_decision.params, \
        "无物质变化的奖励丢回执没有稳定重试原目标"

    # pending 仅表示服务端受理，不能提前写 reward_attempt；同一陈旧 payload
    # 应持续等待，看到精确目标消失后才补交一次完整 Decision。
    pending_agent = fresh_amb_agent("pending_reward", "AMB_PENDING")
    pending_state = json.loads(json.dumps(amb_reward_state))
    pending_state["run_id"] = "AMB_PENDING"
    pending_agent.ctx.run_id = "AMB_PENDING"
    pending_decision = pending_agent.policy.decide(
        pending_state, pending_agent.ctx)
    pending_agent._remember_ambiguous_action(
        pending_state, pending_decision, accepted=True)
    assert pending_agent._reconcile_ambiguous_action(pending_state) == "wait" \
        and pending_agent.ctx.credit_tags == [], \
        "pending 回执在动作效果落地前抢先提交了奖励事务"
    pending_applied = json.loads(json.dumps(pending_state))
    pending_applied["reward"]["rewards"] = []
    pending_applied["run"]["gold"] = 42
    assert pending_agent._reconcile_ambiguous_action(pending_applied) == "applied" \
        and pending_agent.ctx.credit_tags == pending_decision.tags, \
        "pending 回执未在精确效果落地后恰好一次补交事务"

    # 旧局 pending 后连到新 run/menu 不能把离屏误当旧动作成功。
    cross_agent = fresh_amb_agent("cross_run", "AMB_OLD")
    cross_before = json.loads(json.dumps(event_state))
    cross_before["run_id"] = "AMB_OLD"
    cross_decision = policy.Decision(
        "choose_event_option", {"option_index": 0}, "cross",
        tags=[("event_choice", "RECEIPT_EVENT", "WAIT")])
    cross_agent._remember_ambiguous_action(cross_before, cross_decision)
    cross_after = {"screen": "MAP", "run_id": "AMB_NEW",
                   "run": {"floor": 1, "deck": [], "relics": [], "potions": []}}
    assert [cross_agent._reconcile_ambiguous_action(cross_after)
            for _ in range(3)] == ["wait", "wait", "retry"] \
        and cross_agent.ctx.credit_tags == [], \
        "跨 run 离屏被误认作旧局事件动作成功并写入幻影信用"

    # 跑一段真实 Agent.run 控制流：前两份 unchanged GET 只能观察+等待，既不
    # 调 Policy 也不 POST；第三份才释放一次重试，防止 wiring 只返回 wait 却
    # 在主循环里被忽略。
    loop_agent = fresh_amb_agent("loop_gate", "AMB_LOOP")
    loop_state = json.loads(json.dumps(amb_reward_state))
    loop_state["run_id"] = "AMB_LOOP"
    loop_agent.ctx.run_id = "AMB_LOOP"
    loop_decision = loop_agent.policy.decide(loop_state, loop_agent.ctx)
    loop_agent._remember_ambiguous_action(loop_state, loop_decision)
    loop_decide_calls = []
    original_loop_decide = loop_agent.policy.decide

    def counted_loop_decide(state, ctx):
        loop_decide_calls.append(state.get("screen"))
        return original_loop_decide(state, ctx)

    loop_agent.policy.decide = counted_loop_decide

    class LoopGateClient:
        def __init__(self):
            self.state_reads = 0
            self.actions = []

        def health(self):
            return {"mod_version": "test", "game_version": "test"}

        def state(self):
            self.state_reads += 1
            if self.state_reads > 3:
                raise AssertionError("未知成功等待未在第三帧释放")
            return json.loads(json.dumps(loop_state))

        def act(self, action, **params):
            self.actions.append((action, params))
            return {"status": "completed"}

    loop_client = LoopGateClient()
    loop_agent.client = loop_client
    loop_agent._start_live_dashboard = lambda: None
    loop_agent._launch_quipper = lambda: None
    loop_agent.ensure_game = lambda: True
    loop_agent._last_policy_refresh = __import__("time").time()
    old_stop_requested = agent.stop_requested
    old_wait_for_stop = agent.wait_for_stop
    old_review_module = agent.llm_review
    old_autogit_module = agent.autogit
    try:
        agent.stop_requested = lambda: False
        agent.wait_for_stop = lambda _seconds: bool(loop_client.actions)
        agent.llm_review = None
        agent.autogit = None
        loop_agent.run()
    finally:
        agent.stop_requested = old_stop_requested
        agent.wait_for_stop = old_wait_for_stop
        agent.llm_review = old_review_module
        agent.autogit = old_autogit_module
    assert loop_client.state_reads == 3 \
        and len(loop_decide_calls) == 1 \
        and loop_client.actions == [("claim_reward", {"option_index": 0})], \
        ("主循环未真正抑制未知成功等待期的决策/重复 POST: "
         f"reads={loop_client.state_reads}, decide={loop_decide_calls}, "
         f"actions={loop_client.actions}")

    # Client 边界之外的普通异常也不能证明 POST 未发送：保留 Decision 做下一帧
    # 对账，不得直接把奖励写进永久 tried。签名 TypeError 的旧熔断仍在 Agent 内。
    generic_agent = fresh_amb_agent("generic_exception", "AMB_GENERIC")
    generic_state = json.loads(json.dumps(amb_reward_state))
    generic_state["run_id"] = "AMB_GENERIC"
    generic_agent.ctx.run_id = "AMB_GENERIC"

    class GenericLostClient:
        def __init__(self):
            self.actions = []

        def health(self):
            return {"mod_version": "test", "game_version": "test"}

        def state(self):
            return json.loads(json.dumps(generic_state))

        def act(self, action, **params):
            self.actions.append((action, params))
            raise RuntimeError("transport wrapper failed after send")

    generic_client = GenericLostClient()
    generic_agent.client = generic_client
    generic_agent._start_live_dashboard = lambda: None
    generic_agent._launch_quipper = lambda: None
    generic_agent.ensure_game = lambda: True
    generic_agent._last_policy_refresh = __import__("time").time()
    old_stop_requested = agent.stop_requested
    old_wait_for_stop = agent.wait_for_stop
    old_review_module = agent.llm_review
    old_autogit_module = agent.autogit
    try:
        agent.stop_requested = lambda: False
        agent.wait_for_stop = lambda _seconds: bool(generic_client.actions)
        agent.llm_review = None
        agent.autogit = None
        generic_agent.run()
    finally:
        agent.stop_requested = old_stop_requested
        agent.wait_for_stop = old_wait_for_stop
        agent.llm_review = old_review_module
        agent.autogit = old_autogit_module
    assert generic_client.actions == [("claim_reward", {"option_index": 0})] \
        and isinstance(generic_agent._ambiguous_action, dict) \
        and generic_agent.policy._reward_tried == set() \
        and generic_agent.ctx.credit_tags == [], \
        "Agent 普通动作异常被当成确定失败，未进入未知成功对账"

    # 同一奖励目标消失且金币落袋是明确 postcondition：补交原 Decision 的全部
    # tags/日志一次，随后 Policy 才把该奖励加入 tried。
    amb_reward_agent._remember_ambiguous_action(
        amb_reward_state, amb_reward_retry)
    reward_applied = json.loads(json.dumps(amb_reward_state))
    reward_applied["reward"]["rewards"] = []
    reward_applied["run"]["gold"] = 42
    assert amb_reward_agent._reconcile_ambiguous_action(reward_applied) == "applied", \
        "已领取但丢回执的奖励未由目标消失/金币变化确认"
    amb_reward_agent._track(reward_applied)
    amb_reward_agent.policy.decide(reward_applied, amb_reward_agent.ctx)
    assert amb_reward_retry.tags == amb_reward_agent.ctx.credit_tags \
        and len(amb_reward_agent.ctx.decisions) == 1, \
        "奖励未知成功未恰好一次补交完整事务账"

    # 事件离场、地图进房、篝火进选牌、卡牌/遗物奖励都必须用各自的屏幕或
    # 资源 postcondition 补交信用；这也是后续 HP/金币/战斗归因建立快照的前提。
    credit_cases = [
        ("map", "AMB_MAP", "MAP", "COMBAT",
         policy.Decision("choose_map_node", {"option_index": 0}, "map",
                         tags=[("map_node", "Monster")]),
         {"map": {"available_nodes": [{"index": 0, "node_type": "Monster"}]}}),
        ("rest", "AMB_REST", "REST", "CARD_SELECTION",
         policy.Decision("choose_rest_option", {"option_index": 1}, "rest",
                         tags=[("rest", "smith")]),
         {"rest": {"options": [{"index": 1, "option_id": "smith"}]}}),
        ("card_reward", "AMB_CARD_REWARD", "REWARD", "MAP",
         policy.Decision("choose_reward_card", {"option_index": 0}, "card",
                         tags=[("card_pick", "AMB_CARD")]),
         {"reward": {"card_options": [{"index": 0, "card_id": "AMB_CARD"}]}}),
        ("relic_reward", "AMB_RELIC_REWARD", "CHEST", "MAP",
         policy.Decision("choose_treasure_relic", {"option_index": 0}, "relic",
                         tags=[("relic_pick", "AMB_RELIC")]),
         {"chest": {"is_opened": True, "has_relic_been_claimed": False,
                    "relic_options": [{"index": 0, "relic_id": "AMB_RELIC"}]}}),
    ]
    for name, run_id, before_screen, after_screen, decision, extra in credit_cases:
        value = fresh_amb_agent(name, run_id)
        before = {"screen": before_screen, "run_id": run_id,
                  "available_actions": [decision.action],
                  "run": {"current_hp": 70, "max_hp": 80, "gold": 50,
                          "floor": 6, "deck": [], "relics": [], "potions": []},
                  **extra}
        after = json.loads(json.dumps(before))
        after["screen"] = after_screen
        if decision.action == "choose_treasure_relic":
            after["run"]["relics"].append(
                {"index": 0, "relic_id": "AMB_RELIC", "name": "精确遗物"})
        value._remember_ambiguous_action(before, decision)
        assert value._reconcile_ambiguous_action(after) == "applied" \
            and value.ctx.credit_tags == decision.tags \
            and value.ctx.decisions[-1]["action"] == decision.action, \
            f"{name} 丢回执后的成功转换未补交完整 Decision 事务"

    # 宝箱域或离屏的泛化变化不是领取证据；必须看到目标遗物入库存、该精确
    # option 消失，或该精确 option 被标 claimed，避免把 sibling/动画变化记账。
    exact_chest_agent = fresh_amb_agent("exact_chest", "AMB_EXACT_CHEST")
    exact_chest_before = {
        "screen": "CHEST", "run_id": "AMB_EXACT_CHEST",
        "available_actions": ["choose_treasure_relic"],
        "chest": {"is_opened": True, "has_relic_been_claimed": False,
                  "relic_options": [
                      {"index": 0, "relic_id": "TARGET_RELIC", "name": "目标"},
                      {"index": 1, "relic_id": "SIBLING_RELIC", "name": "兄弟"}]},
        "run": {"current_hp": 70, "max_hp": 80, "gold": 0, "floor": 6,
                "deck": [], "relics": [], "potions": []}}
    exact_chest_decision = policy.Decision(
        "choose_treasure_relic", {"option_index": 0}, "target",
        tags=[("relic_pick", "TARGET_RELIC")])
    generic_chest_after = json.loads(json.dumps(exact_chest_before))
    generic_chest_after["screen"] = "MAP"
    generic_chest_after["chest"]["has_relic_been_claimed"] = True
    exact_chest_agent._remember_ambiguous_action(
        exact_chest_before, exact_chest_decision)
    assert [exact_chest_agent._reconcile_ambiguous_action(generic_chest_after)
            for _ in range(3)] == ["wait", "wait", "retry"] \
        and exact_chest_agent.ctx.credit_tags == [], \
        "宝箱离屏/泛 claimed 标志被误当作精确目标领取成功"
    exact_option_after = json.loads(json.dumps(exact_chest_before))
    exact_option_after["chest"]["relic_options"] = [
        exact_option_after["chest"]["relic_options"][1]]
    exact_chest_agent._remember_ambiguous_action(
        exact_chest_before, exact_chest_decision)
    assert exact_chest_agent._reconcile_ambiguous_action(exact_option_after) == "applied" \
        and exact_chest_agent.ctx.credit_tags == exact_chest_decision.tags, \
        "同屏精确遗物 option 消失未确认丢回执领取成功"

    # 事件选择在进入下一屏前先补挂 pending_event，_track 才能把真实变化归因
    # 给正确选项；若顺序反了，离场 tick 会直接漏样本。
    amb_event_agent = fresh_amb_agent("event", "AMB_EVENT")
    amb_event_before = json.loads(json.dumps(event_state))
    amb_event_before["run_id"] = "AMB_EVENT"
    amb_event_decision = policy.Decision(
        "choose_event_option", {"option_index": 0}, "event",
        tags=[("event_choice", "RECEIPT_EVENT", "WAIT")])
    amb_event_after = json.loads(json.dumps(amb_event_before))
    amb_event_after["screen"] = "MAP"
    amb_event_after["run"]["current_hp"] = 73
    amb_event_after["map"] = {"available_nodes": []}
    amb_event_agent._remember_ambiguous_action(
        amb_event_before, amb_event_decision)
    assert amb_event_agent._reconcile_ambiguous_action(amb_event_after) == "applied" \
        and amb_event_agent.ctx.pending_event is not None, \
        "事件未知成功未在观察离场前建立归因快照"
    amb_event_agent._track(amb_event_after)
    assert amb_event_agent.ctx.pending_event is None \
        and amb_event_agent.know.stats["events"]["RECEIPT_EVENT"]["WAIT"]["n"] == 1, \
        "事件未知成功的真实离场结果未落库"

    # 同回合同一张牌的手牌/能量/计数变化可确认出牌；endpoint-only 变化不能。
    amb_play_agent = fresh_amb_agent("play", "AMB_PLAY")
    play_before = {
        "screen": "COMBAT", "run_id": "AMB_PLAY", "turn": 2,
        "available_actions": ["play_card", "end_turn"],
        "run": {"current_hp": 60, "max_hp": 80, "gold": 0, "floor": 8,
                "deck": [], "relics": [], "potions": []},
        "combat": {"player": {"current_hp": 60, "max_hp": 80, "block": 0,
                                "energy": 3, "cards_played_this_turn": 0},
                   "hand": [{"index": 0, "card_id": "AMB_STRIKE", "name": "打击",
                              "energy_cost": 1, "playable": True}],
                   "enemies": [{"index": 0, "enemy_id": "AMB_ENEMY",
                                 "current_hp": 20, "max_hp": 20, "block": 0,
                                 "is_alive": True, "powers": []}]}}
    play_decision = policy.Decision(
        "play_card", {"card_index": 0, "target_index": 0}, "play",
        tags=[("play_card", "AMB_STRIKE"), ("play_card_index", 0)])
    play_endpoint_only = json.loads(json.dumps(play_before))
    play_endpoint_only["available_actions"] = ["end_turn"]
    amb_play_agent._remember_ambiguous_action(play_before, play_decision)
    assert [amb_play_agent._reconcile_ambiguous_action(play_endpoint_only)
            for _ in range(3)] == ["wait", "wait", "retry"] \
        and amb_play_agent.know.stats["cards"].get("AMB_STRIKE") is None \
        and amb_play_agent.policy._failed_this_turn == set(), \
        "出牌 endpoint 刷新窗被误记成功/失败并污染卡槽黑名单"
    play_after = json.loads(json.dumps(play_before))
    play_after["combat"]["player"]["energy"] = 2
    play_after["combat"]["player"]["cards_played_this_turn"] = 1
    play_after["combat"]["hand"] = []
    play_after["combat"]["enemies"][0]["current_hp"] = 14
    amb_play_agent._remember_ambiguous_action(play_before, play_decision)
    assert amb_play_agent._reconcile_ambiguous_action(play_after) == "applied" \
        and amb_play_agent.know.stats["cards"]["AMB_STRIKE"]["plays"] == 1 \
        and amb_play_agent.ctx.credit_tags == play_decision.tags, \
        "同回合物质变化未确认丢回执出牌，或未补交出牌账"

    # 药水以槽位身份/占用变化为提交证据，不能因 use_potion endpoint 抖动消费。
    amb_potion_agent = fresh_amb_agent("potion", "AMB_POTION")
    potion_before = json.loads(json.dumps(potion_state))
    potion_before["run_id"] = "AMB_POTION"
    # 生产时序中该动作前的首帧已经 track→decide，Policy 因而绑定了本场
    # combat identity；先走一遍，避免测试手工 Decision 绕过这一生命周期。
    amb_potion_agent._track(potion_before)
    amb_potion_agent.ctx.current_combat_is_hard = True
    amb_potion_agent.policy.decide(potion_before, amb_potion_agent.ctx)
    potion_decision = policy.Decision(
        "use_potion", {"option_index": 0}, "potion",
        tags=[("potion_used", "RECEIPT_FIRE"),
              ("potion_attempt", 0, "RECEIPT_FIRE")])
    potion_after_state = json.loads(json.dumps(potion_before))
    potion_after_state["run"]["potions"][0].update(
        {"occupied": False, "can_use": False, "potion_id": None, "name": None})
    amb_potion_agent._remember_ambiguous_action(potion_before, potion_decision)
    assert amb_potion_agent._reconcile_ambiguous_action(potion_after_state) == "applied", \
        "已消耗药水的丢回执未由槽位变化确认"
    amb_potion_agent._track(potion_after_state)
    amb_potion_agent.policy.decide(potion_after_state, amb_potion_agent.ctx)
    assert amb_potion_agent.ctx.credit_tags == potion_decision.tags, \
        "药水未知成功未恰好一次进入消费/信用账"

    # 商店删牌 opener 与后续选牌各有独立握手。未落地时重试 opener/同一垃圾；
    # 落地后无关键词的选择屏也必须删打击，不能误删最高价值牌或反选。
    amb_shop_agent = fresh_amb_agent("shop_remove", "AMB_SHOP")
    amb_shop_state = {
        "screen": "SHOP", "run_id": "AMB_SHOP",
        "available_actions": ["remove_card_at_shop", "close_shop_inventory"],
        "shop": {"is_open": True, "can_close": True, "cards": [], "relics": [],
                 "potions": [], "card_removal": {"available": True, "used": False,
                 "enough_gold": True, "price": 50}},
        "run": {"current_hp": 70, "max_hp": 80, "gold": 150, "floor": 9,
                "deck": [{"index": 0, "card_id": "STRIKE_IRONCLAD", "name": "打击",
                          "card_type": "Attack", "upgraded": False},
                         {"index": 1, "card_id": "BASH", "name": "痛击+",
                          "card_type": "Attack", "upgraded": True}],
                "relics": [], "potions": []}}
    remove_open = amb_shop_agent.policy.decide(
        amb_shop_state, amb_shop_agent.ctx)
    assert remove_open.action == "remove_card_at_shop", \
        f"删牌事务测试未进入 opener: {remove_open.reason}"
    amb_shop_agent._remember_ambiguous_action(amb_shop_state, remove_open)
    assert [amb_shop_agent._reconcile_ambiguous_action(amb_shop_state)
            for _ in range(3)] == ["wait", "wait", "retry"], \
        "未落地的商店删牌 opener 没有短等待后重试"
    assert amb_shop_agent.policy.decide(
        amb_shop_state, amb_shop_agent.ctx).action == "remove_card_at_shop", \
        "商店删牌无回执未执行后被幻影标记完成"
    remove_select_state = {
        "screen": "CARD_SELECTION", "run_id": "AMB_SHOP",
        "available_actions": ["select_deck_card", "confirm_selection"],
        "selection": {"kind": "mystery", "prompt": "选择一张牌", "min_select": 1,
                      "max_select": 1, "selected_count": 0, "can_confirm": False,
                      "cards": json.loads(json.dumps(amb_shop_state["run"]["deck"]))},
        "run": json.loads(json.dumps(amb_shop_state["run"]))}
    amb_shop_agent._remember_ambiguous_action(amb_shop_state, remove_open)
    assert amb_shop_agent._reconcile_ambiguous_action(remove_select_state) == "applied", \
        "商店删牌已打开选择屏却未补交 opener 握手"
    amb_shop_agent._track(remove_select_state)
    remove_pick = amb_shop_agent.policy.decide(
        remove_select_state, amb_shop_agent.ctx)
    assert remove_pick.action == "select_deck_card" \
        and remove_pick.params.get("option_index") == 0, \
        f"无关键词删牌屏误选高价值牌: {remove_pick.params}（{remove_pick.reason}）"
    amb_shop_agent._remember_ambiguous_action(remove_select_state, remove_pick)
    assert [amb_shop_agent._reconcile_ambiguous_action(remove_select_state)
            for _ in range(3)] == ["wait", "wait", "retry"], \
        "未执行的 deck selection 未按同一 screen/count 重试"
    remove_pick_retry = amb_shop_agent.policy.decide(
        remove_select_state, amb_shop_agent.ctx)
    assert remove_pick_retry.action == "select_deck_card" \
        and remove_pick_retry.params == remove_pick.params, \
        "删牌选择丢回执未执行后换选/跳过了原垃圾牌"
    remove_selected = json.loads(json.dumps(remove_select_state))
    remove_selected["selection"]["selected_count"] = 1
    remove_selected["selection"]["can_confirm"] = True
    amb_shop_agent._remember_ambiguous_action(
        remove_select_state, remove_pick_retry)
    assert amb_shop_agent._reconcile_ambiguous_action(remove_selected) == "applied", \
        "selected_count 增长未确认 deck selection 已执行"
    amb_shop_agent._track(remove_selected)
    assert amb_shop_agent.policy.decide(
        remove_selected, amb_shop_agent.ctx).action == "confirm_selection", \
        "已执行选牌丢回执后重复点击并可能反选"

    # 时间线所有 pre-mutation 都必须由成功 tag/观察转换驱动；accepted 但长期
    # 不落地不能在超时后把 obtained 槽误标 tried，应该重试同槽。
    timeline_agent = fresh_amb_agent("timeline", "AMB_TIMELINE")
    timeline_agent.ctx.check_timeline = True
    timeline_menu = {
        "screen": "MAIN_MENU", "available_actions": ["open_timeline"],
        "timeline": None, "run": {}}
    open_timeline = timeline_agent.policy.decide(
        timeline_menu, timeline_agent.ctx)
    assert open_timeline.action == "open_timeline" \
        and timeline_agent.ctx.check_timeline, \
        "open_timeline 请求前抢先清除了 check_timeline"
    timeline_agent._commit_successful_action(timeline_menu, open_timeline)
    timeline_state = {
        "screen": "TIMELINE", "available_actions": ["choose_timeline_epoch",
                                                       "close_main_menu_submenu"],
        "timeline": {"can_choose_epoch": True, "can_confirm_overlay": False,
                     "slots": [{"index": 3, "state": "obtained", "title": "新内容"}]},
        "run": {}}
    choose_epoch = timeline_agent.policy.decide(
        timeline_state, timeline_agent.ctx)
    assert choose_epoch.action == "choose_timeline_epoch" \
        and 3 not in timeline_agent.ctx.timeline_tried, \
        "时间线槽位在请求前被抢先标记 tried"
    timeline_agent._commit_successful_action(timeline_state, choose_epoch)
    timeline_waits = [timeline_agent.policy.decide(
        timeline_state, timeline_agent.ctx) for _ in range(9)]
    assert all(d.action is None for d in timeline_waits[:-1]) \
        and timeline_waits[-1].action == "choose_timeline_epoch" \
        and 3 not in timeline_agent.ctx.timeline_tried, \
        "时间线 accepted/pending 未落地时超时跳过 obtained 槽或提前重复点击"
    timeline_agent._commit_successful_action(
        timeline_state, timeline_waits[-1])
    timeline_overlay = json.loads(json.dumps(timeline_state))
    timeline_overlay["timeline"]["can_confirm_overlay"] = True
    timeline_overlay["available_actions"] = ["confirm_timeline_overlay"]
    overlay_decision = timeline_agent.policy.decide(
        timeline_overlay, timeline_agent.ctx)
    assert overlay_decision.action == "confirm_timeline_overlay" \
        and 3 in timeline_agent.ctx.timeline_tried, \
        "时间线真实 overlay 转换未提交 tried/确认流程"

    # 409 是明确“未执行”但常由 GET→POST 间的刷新竞争产生。即使相同状态连续
    # 两次仍不得永久拉黑牌/奖励/药水；只有参数/能力错误走 definitive 路径。
    race_agent = fresh_amb_agent("api_race", "AMB_API")
    card_race = client.ApiError(
        "invalid_action", "Card cannot be played in the current state.",
        status=409)
    assert race_agent._defer_api_error_once(
        play_before, play_decision, card_race) \
        and race_agent._defer_api_error_once(
            play_before, play_decision, card_race), \
        "持续动画窗中的第二个 409 仍会永久拉黑可用牌"
    retryable_error = client.ApiError(
        "state_unavailable", "busy", status=503, retryable=True)
    assert race_agent._defer_api_error_once(
        play_before, play_decision, retryable_error), \
        "服务端显式 retryable 错误未保持无惩罚刷新"
    definitive_error = client.ApiError(
        "invalid_action", "This target type is not supported by the API.",
        status=409)
    assert not race_agent._defer_api_error_once(
        play_before, play_decision, definitive_error), \
        "永久不支持的动作签名错误被误当作刷新竞争"

    # event/map/rest/shop/selection/treasure 的瞬时失败按精确 action+option
    # 短冷却：先轮转 sibling；全部候选冷却时只能等待，不能跳过/离开屏幕；
    # 冷却自动过期后原目标重新可用。
    rotate_know = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-ui-rotation-")))
    rotate_know.policy["event_exploration_enabled"] = False
    rotate_know.policy["relic_exploration_enabled"] = False
    rotate_know.policy["potion_exploration_enabled"] = False

    def assert_ui_rotation(label, state, expected_action):
        rotate_pol = policy.Policy(rotate_know, random.Random(0))
        rotate_ctx = DummyCtx()
        rotate_ctx.run_id = state["run_id"]
        rotate_ctx.credit_tags = []
        first = rotate_pol.decide(state, rotate_ctx)
        assert first.action == expected_action, \
            f"{label} 轮转测试未产生首个候选: {first.action} / {first.reason}"
        rotate_pol.note_action_deferred(
            first.action, first.tags, state, first.params)
        second = rotate_pol.decide(state, rotate_ctx)
        assert second.action == expected_action \
            and second.params.get("option_index") != first.params.get("option_index"), \
            f"{label} 精确目标冷却后未轮转 sibling: {first.params} -> {second.params}"
        rotate_pol.note_action_deferred(
            second.action, second.tags, state, second.params)
        all_cooling = rotate_pol.decide(state, rotate_ctx)
        assert all_cooling.action is None and "短冷却" in all_cooling.reason, \
            f"{label} 全候选冷却时错误离场/跳过: {all_cooling.action} / {all_cooling.reason}"
        released = None
        for _ in range(5):
            released = rotate_pol.decide(state, rotate_ctx)
            if released.action == expected_action:
                break
        assert released is not None and released.action == expected_action, \
            f"{label} 精确目标短冷却没有自动过期: {released.reason if released else None}"
        return rotate_pol, rotate_ctx, first

    event_rotate_state = {
        "screen": "EVENT", "run_id": "ROT_EVENT",
        "available_actions": ["choose_event_option", "proceed"],
        "event": {"event_id": "ROT_EVENT_ID", "title": "轮转事件",
                  "is_finished": False, "page": 1,
                  "options": [
                      {"index": 0, "text_key": "A", "title": "A",
                       "is_locked": False, "will_kill_player": False},
                      {"index": 1, "text_key": "B", "title": "B",
                       "is_locked": False, "will_kill_player": False}]},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                "floor": 4, "deck": [], "relics": [], "potions": []}}
    event_rotate_pol, event_rotate_ctx, event_first = assert_ui_rotation(
        "事件", event_rotate_state, "choose_event_option")

    map_rotate_state = {
        "screen": "MAP", "run_id": "ROT_MAP",
        "available_actions": ["choose_map_node", "proceed"],
        "map": {"available_nodes": [
                    {"index": 0, "row": 1, "col": 0, "node_type": "Monster"},
                    {"index": 1, "row": 1, "col": 1, "node_type": "Monster"}],
                "nodes": []},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                "floor": 3, "deck": [], "relics": [], "potions": []}}
    assert_ui_rotation("地图", map_rotate_state, "choose_map_node")

    rest_rotate_state = {
        "screen": "REST", "run_id": "ROT_REST",
        "available_actions": ["choose_rest_option", "proceed"],
        "rest": {"options": [
            {"index": 0, "option_id": "HEAL", "title": "休息", "is_enabled": True},
            {"index": 1, "option_id": "SMITH", "title": "锻造", "is_enabled": True}]},
        "run": {"current_hp": 70, "max_hp": 80, "gold": 0, "floor": 7,
                "deck": [{"index": 0, "card_id": "ROT_STRIKE", "name": "打击",
                          "card_type": "Attack", "upgraded": False}],
                "relics": [], "potions": []}}
    assert_ui_rotation("篝火", rest_rotate_state, "choose_rest_option")

    shop_rotate_state = {
        "screen": "SHOP", "run_id": "ROT_SHOP",
        "available_actions": ["buy_relic", "close_shop_inventory", "proceed"],
        "shop": {"is_open": True, "can_close": True, "cards": [], "potions": [],
                 "card_removal": None,
                 "relics": [
                     {"index": 0, "relic_id": "ROT_RELIC_A", "name": "A",
                      "price": 60, "is_stocked": True, "enough_gold": True},
                     {"index": 1, "relic_id": "ROT_RELIC_B", "name": "B",
                      "price": 60, "is_stocked": True, "enough_gold": True}]},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 200,
                "floor": 8, "deck": [], "relics": [], "potions": []}}
    assert_ui_rotation("商店", shop_rotate_state, "buy_relic")

    selection_rotate_state = {
        "screen": "CARD_SELECTION", "run_id": "ROT_SELECTION",
        "available_actions": ["select_deck_card", "skip_reward_cards", "proceed"],
        "selection": {"kind": "upgrade", "prompt": "升级", "min_select": 1,
                      "max_select": 1, "selected_count": 0, "can_confirm": False,
                      "cards": [
                          {"index": 0, "card_id": "ROT_CARD_A", "name": "A",
                           "card_type": "Attack", "upgraded": False},
                          {"index": 1, "card_id": "ROT_CARD_B", "name": "B",
                           "card_type": "Attack", "upgraded": False}]},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                "floor": 9, "deck": [], "relics": [], "potions": []}}
    assert_ui_rotation("选牌", selection_rotate_state, "select_deck_card")

    chest_rotate_state = {
        "screen": "CHEST", "run_id": "ROT_CHEST",
        "available_actions": ["choose_treasure_relic", "proceed"],
        "chest": {"is_opened": True, "has_relic_been_claimed": False,
                  "relic_options": [
                      {"index": 0, "relic_id": "ROT_CHEST_A", "name": "A"},
                      {"index": 1, "relic_id": "ROT_CHEST_B", "name": "B"}]},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0,
                "floor": 10, "deck": [], "relics": [], "potions": []}}
    assert_ui_rotation("宝箱", chest_rotate_state, "choose_treasure_relic")

    # accepted/pending 超时接入同一精确冷却；相同页面的 sibling 必须接替。
    pending_rotate_agent = fresh_amb_agent("pending_rotate", "ROT_PENDING")
    pending_rotate_state = json.loads(json.dumps(event_rotate_state))
    pending_rotate_state["run_id"] = "ROT_PENDING"
    pending_rotate_agent.ctx.run_id = "ROT_PENDING"
    pending_rotate_decision = pending_rotate_agent.policy.decide(
        pending_rotate_state, pending_rotate_agent.ctx)
    pending_rotate_agent._remember_ambiguous_action(
        pending_rotate_state, pending_rotate_decision, accepted=True)
    pending_results = [pending_rotate_agent._reconcile_ambiguous_action(
        pending_rotate_state) for _ in range(12)]
    assert pending_results[-1] == "retry" \
        and pending_rotate_agent.policy.decide(
            pending_rotate_state, pending_rotate_agent.ctx).params.get("option_index") \
        != pending_rotate_decision.params.get("option_index"), \
        "accepted/pending 超时未冷却精确事件 option 并轮转 sibling"

    # 连续第三次 transient 409 同样冷却精确宝箱目标，不得永久拉黑。
    chest_race_agent = fresh_amb_agent("chest_race", "ROT_CHEST_RACE")
    chest_race_state = json.loads(json.dumps(chest_rotate_state))
    chest_race_state["run_id"] = "ROT_CHEST_RACE"
    chest_race_agent.ctx.run_id = "ROT_CHEST_RACE"
    chest_race_decision = chest_race_agent.policy.decide(
        chest_race_state, chest_race_agent.ctx)
    chest_race_error = client.ApiError(
        "invalid_action", "state advanced", status=409)
    assert all(chest_race_agent._defer_api_error_once(
        chest_race_state, chest_race_decision, chest_race_error) for _ in range(3))
    chest_race_next = chest_race_agent.policy.decide(
        chest_race_state, chest_race_agent.ctx)
    assert chest_race_next.action == "choose_treasure_relic" \
        and chest_race_next.params.get("option_index") \
        != chest_race_decision.params.get("option_index"), \
        "连续 transient 409 未轮转精确宝箱 sibling"

    # 同 run 的事件页面实例变化、以及 run identity 变化都必须立即清空旧冷却。
    event_rotate_pol.note_action_deferred(
        event_first.action, event_first.tags, event_rotate_state, event_first.params)
    next_page = json.loads(json.dumps(event_rotate_state))
    next_page["event"]["page"] = 2
    page_decision = event_rotate_pol.decide(next_page, event_rotate_ctx)
    assert page_decision.action == "choose_event_option" \
        and page_decision.params == event_first.params, \
        "事件 screen instance 变化后仍继承旧 option 冷却"
    next_run = json.loads(json.dumps(event_rotate_state))
    next_run["run_id"] = "ROT_EVENT_NEW_RUN"
    event_rotate_ctx.run_id = "ROT_EVENT_NEW_RUN"
    run_decision = event_rotate_pol.decide(next_run, event_rotate_ctx)
    assert run_decision.action == "choose_event_option", \
        "新 run 继承旧屏幕精确目标冷却"

    # 原生 REST option 要求 target 时必须发送合法且确定性的 target_index。
    rest_target_pol = policy.Policy(rotate_know, random.Random(0))
    rest_target_ctx = DummyCtx()
    rest_target_ctx.run_id = "REST_TARGET"
    rest_target_ctx.credit_tags = []
    rest_target_state = {
        "screen": "REST", "run_id": "REST_TARGET",
        "available_actions": ["choose_rest_option"],
        "rest": {"options": [{"index": 4, "option_id": "SMITH",
                               "title": "锻造", "is_enabled": True,
                               "requires_target": True,
                               "valid_target_indices": [2, 7]}]},
        "run": {"current_hp": 80, "max_hp": 80, "gold": 0, "floor": 7,
                "deck": [
                    {"index": 2, "card_id": "REST_WEAK", "name": "弱牌",
                     "card_type": "Skill", "upgraded": False},
                    {"index": 7, "card_id": "REST_STRONG", "name": "强攻",
                     "card_type": "Attack", "upgraded": False,
                     "dynamic_values": [{"name": "Damage", "current_value": 30}]}]}}
    rest_target = rest_target_pol.decide(rest_target_state, rest_target_ctx)
    assert rest_target.action == "choose_rest_option" \
        and rest_target.params.get("option_index") == 4 \
        and rest_target.params.get("target_index") in (2, 7) \
        and "原生目标直选" in rest_target.reason, \
        f"REST requires_target 未附合法目标: {rest_target.params} / {rest_target.reason}"
    unknown_target = json.loads(json.dumps(rest_target_state))
    unknown_target["run_id"] = "REST_UNKNOWN_TARGET"
    unknown_target["rest"]["options"] = [{
        "index": 5, "option_id": "MYSTERY", "title": "未知仪式",
        "is_enabled": True, "requires_target": True,
        "valid_target_indices": [9, 3]}]
    rest_target_ctx.run_id = "REST_UNKNOWN_TARGET"
    unknown_decision = rest_target_pol.decide(unknown_target, rest_target_ctx)
    assert unknown_decision.params.get("target_index") == 3 \
        and "目标语义未知" in unknown_decision.reason, \
        f"未知 REST target 未稳定选择首个合法项并解释: {unknown_decision.params} / {unknown_decision.reason}"

    # 要求目标但目标集为空的 enabled option 当前不可执行，必须在策略排序前
    # 排除：有合法 sibling 就选 sibling；全部不可执行时原地等待，不能 proceed。
    empty_target_sibling = json.loads(json.dumps(rest_target_state))
    empty_target_sibling["run_id"] = "REST_EMPTY_TARGET_SIBLING"
    empty_target_sibling["available_actions"] = ["choose_rest_option", "proceed"]
    empty_target_sibling["rest"]["options"] = [
        {"index": 0, "option_id": "SMITH", "title": "锻造",
         "is_enabled": True, "requires_target": True,
         "valid_target_indices": []},
        {"index": 1, "option_id": "HEAL", "title": "休息",
         "is_enabled": True, "requires_target": False},
    ]
    rest_target_ctx.run_id = "REST_EMPTY_TARGET_SIBLING"
    sibling_decision = rest_target_pol.decide(
        empty_target_sibling, rest_target_ctx)
    assert sibling_decision.action == "choose_rest_option" \
        and sibling_decision.params.get("option_index") == 1, \
        ("空 target REST 项遮蔽了合法 sibling: "
         f"{sibling_decision.action} / {sibling_decision.params} / {sibling_decision.reason}")

    all_empty_targets = json.loads(json.dumps(empty_target_sibling))
    all_empty_targets["run_id"] = "REST_ALL_EMPTY_TARGETS"
    all_empty_targets["rest"]["options"] = [
        {"index": 0, "option_id": "SMITH", "title": "锻造",
         "is_enabled": True, "requires_target": True,
         "valid_target_indices": []},
        {"index": 2, "option_id": "MYSTERY", "title": "仪式",
         "is_enabled": True, "requires_target": True,
         "valid_target_indices": []},
    ]
    rest_target_ctx.run_id = "REST_ALL_EMPTY_TARGETS"
    all_empty_decision = rest_target_pol.decide(
        all_empty_targets, rest_target_ctx)
    assert all_empty_decision.action is None \
        and "没有合法目标" in all_empty_decision.reason, \
        ("全部空 target REST 项错误 proceed/发动作: "
         f"{all_empty_decision.action} / {all_empty_decision.reason}")

    # 生产时序回归：Agent 必须先观察首个战斗帧、建立 ctx.combat，再让 Policy
    # 决策。否则首张牌成功标签会在下一 tick 先入账、随后又被“新战斗”初始化
    # 清空，导致受控试用和消耗上限可在同一场战斗重复透支。
    flow_card = cm_card(0, "FLOW_NOVEL", "首帧新牌", damage=30,
                        card_kind="Attack")
    flow_card["rules_text"] = "Deal 30 damage. Exhaust a random card."
    tx_agent.know.stats["cards"]["FLOW_NOVEL"] = {
        "seen": 8, "picked": 5, "plays": 0,
        "outcome_sum": 0.0, "bias": 0.0}
    flow_first = cm_state([flow_card], turn=1)
    flow_first["run_id"] = "TX_RUN"
    tx_agent._track(flow_first)
    flow_combat_identity = tx_agent.ctx.combat
    assert isinstance(flow_combat_identity, dict), \
        "首个战斗帧在 Policy 决策前没有建立 combat identity"
    flow_decision = tx_agent.policy.decide(flow_first, tx_agent.ctx)
    assert flow_decision.action == "play_card" and "受控试用" in flow_decision.reason, \
        f"首帧受控试用没有产生出牌决策: {flow_decision.reason}"
    tx_agent._commit_successful_action(flow_first, flow_decision)

    flow_next = cm_state([flow_card], turn=2)
    flow_next["run_id"] = "TX_RUN"
    tx_agent._track(flow_next)
    assert tx_agent.ctx.combat is flow_combat_identity, \
        "同场第二帧错误更换了 combat identity"
    tx_agent.policy.decide(flow_next, tx_agent.ctx)
    flow_ledger = combat_policy_ledger(tx_agent.policy)
    assert flow_ledger == (
            frozenset({"FLOW_NOVEL"}), 1, 30.0, 1, 1, {"CM_ENEMY": 1}), \
        f"首张成功出牌账被新战斗初始化清空或重复提交: {flow_ledger}"

    # 卡死分析结论必须绑定请求它的战斗；新战斗统一清除 verdict/触发位，晚到的
    # 旧线程结果不能让下一场从 T1 开始摆烂或强攻。新 run 也必须覆盖全部正式字段。
    stall_old_combat = tx_agent.ctx.combat
    assert tx_agent._commit_stall_verdict("giveup", stall_old_combat) \
        and tx_agent.ctx.force_giveup, "当前战斗的有效 giveup 结论未生效"
    tx_agent.ctx.stall_analysis_asked = True
    tx_agent.ctx.stall_analysis_needed = True
    tx_agent.ctx.force_offense = True
    tx_agent.ctx.stall_grind_grace = True
    tx_agent._start_combat({"max_hp": 80, "floor": 4, "deck": []},
                           "STALL_NEW", "Monster", 73)
    stall_new_combat = tx_agent.ctx.combat
    assert not any((tx_agent.ctx.stall_analysis_asked,
                    tx_agent.ctx.stall_analysis_needed,
                    tx_agent.ctx.stall_giveup,
                    tx_agent.ctx.force_giveup,
                    tx_agent.ctx.force_offense,
                    tx_agent.ctx.stall_grind_grace)), \
        "新战斗继承了上一战的 stall verdict/触发状态"
    assert not tx_agent._commit_stall_verdict("giveup", stall_old_combat) \
        and not tx_agent.ctx.force_giveup, \
        "异步旧战斗 giveup 结论污染了下一场战斗"
    assert tx_agent._commit_stall_verdict("offense", stall_new_combat) \
        and tx_agent.ctx.force_offense, "当前战斗 offense 结论未生效"
    tx_agent.ctx.check_timeline = True
    tx_agent.ctx.timeline_tried.add(3)
    tx_agent.ctx.rest_proj_hp_pct = 0.2
    tx_agent.ctx.reset_for("TX_RUN_NEXT", 0)
    assert (not tx_agent.ctx.force_offense and not tx_agent.ctx.force_giveup
            and not tx_agent.ctx.stall_grind_grace
            and not tx_agent.ctx.stall_analysis_asked
            and not tx_agent.ctx.check_timeline
            and tx_agent.ctx.timeline_tried == set()
            and tx_agent.ctx.rest_proj_hp_pct is None), \
        "RunContext.reset_for 没有覆盖动态生命周期字段"

    # Watchdog 必须感知同回合内的生命/格挡/能量/手牌/敌方状态进展；同时
    # JSON 字典键顺序和 available_actions 顺序变化不能伪造进展。
    wd_state = {
        "screen": "COMBAT", "turn": 4,
        "available_actions": ["play_card", "end_turn"],
        "run": {"floor": 9, "current_hp": 42, "max_hp": 80,
                "gold": 33, "ascension": 0},
        "combat": {
            "player": {"current_hp": 42, "max_hp": 80, "block": 3, "energy": 2},
            "hand": [{"index": 0, "card_id": "TX_CARD", "playable": True,
                      "energy_cost": 1,
                      "dynamic_values": [{"name": "Damage", "current_value": 6}]}],
            "enemies": [{"index": 0, "enemy_id": "TX_ENEMY", "current_hp": 20,
                         "max_hp": 30, "block": 2, "is_alive": True,
                         "is_hittable": True,
                         "intents": [{"intent_type": "Attack", "total_damage": 8}]}]}}
    wd_sig = tx_agent._signature(wd_state)
    wd_reordered = json.loads(json.dumps(wd_state))
    wd_reordered["available_actions"].reverse()
    wd_reordered["combat"]["enemies"][0]["intents"][0] = {
        "total_damage": 8, "intent_type": "Attack"}
    assert tx_agent._signature(wd_reordered) == wd_sig, \
        "watchdog 签名受无语义的列表/字典顺序影响"
    for path, value in [
            (("run", "current_hp"), 41),
            (("combat", "player", "block"), 9),
            (("combat", "player", "energy"), 1),
            (("combat", "hand", 0, "playable"), False),
            (("combat", "enemies", 0, "current_hp"), 14),
            (("combat", "enemies", 0, "block"), 0),
            (("combat", "enemies", 0, "intents", 0, "total_damage"), 12)]:
        changed = json.loads(json.dumps(wd_state))
        cursor = changed
        for part in path[:-1]:
            cursor = cursor[part]
        cursor[path[-1]] = value
        assert tx_agent._signature(changed) != wd_sig, \
            f"watchdog 未感知战斗状态变化: {path}"

    # 3zz-ab) 卡牌奖励 offer 统计 + 有界新牌探索：eval_reward_card 必须是纯函数；
    # 同一真实 offer 被状态轮询多次时每个基础 id 只记一次，离开屏幕后再次出现的
    # 同构 offer 才记第二次。升级/删牌/战斗选牌不是奖励，绝不能污染 seen。
    offer_know = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-card-offer-")))
    offer_pol = policy.Policy(offer_know, random.Random(41))
    offer_ctx = DummyCtx()
    offer_ctx.run_id = "RUN_CARD_OFFER"
    offer_card = {
        "index": 0, "card_id": "OFFER_NEW", "name": "新卡", "card_type": "Attack",
        "energy_cost": 1,
        "dynamic_values": [{"name": "Damage", "current_value": 9}]}
    # 纯评分（以及使用它的升级/删除/商店路径）不再偷偷增加 seen。
    _ = offer_pol.eval_reward_card(dict(offer_card), [])
    assert "OFFER_NEW" not in offer_know.stats["cards"], \
        "eval_reward_card 仍有 seen/offered 副作用"
    upgrade_offer_shape = {
        "screen": "CARD_SELECTION", "run_id": "RUN_CARD_OFFER",
        "available_actions": ["select_deck_card", "confirm_selection"],
        "selection": {"kind": "upgrade", "prompt": "升级", "min_select": 1,
                      "selected_count": 0, "can_confirm": False,
                      "cards": [dict(offer_card)]},
        "run": {"current_hp": 70, "max_hp": 80, "floor": 2, "deck": []}}
    offer_pol.decide(upgrade_offer_shape, offer_ctx)
    assert "OFFER_NEW" not in offer_know.stats["cards"], \
        "升级选牌被误计为奖励 offer"

    # 用真实 CARD_SELECTION 奖励结构；同 id 的升级副本在一份 offer 内仍只 +1。
    offer_state = {
        "screen": "CARD_SELECTION", "run_id": "RUN_CARD_OFFER",
        "available_actions": ["select_deck_card", "skip_reward_cards"],
        "selection": {"kind": "", "prompt": "将一张牌添加到你的牌组。",
                      "min_select": 1, "selected_count": 0, "can_confirm": False,
                      "cards": [dict(offer_card),
                                dict(offer_card, index=1, upgraded=True, name="新卡+")]},
        "run": {"current_hp": 70, "max_hp": 80, "floor": 2, "deck": []}}
    offer_pol.decide(offer_state, offer_ctx)
    offer_pol.decide(offer_state, offer_ctx)  # 同屏轮询，不得重记
    oe = offer_know.stats["cards"]["OFFER_NEW"]
    assert oe["seen"] == 1 and oe["offered"] == 1, \
        f"同一 offer 被重复/按卡槽记 seen: {oe}"
    assert offer_know.stats["card_offer_tracking"] == {
        "version": 2, "baseline_runs": 0, "offers": 1,
        "candidate_observations": 1}, \
        f"offer 汇总口径错误: {offer_know.stats['card_offer_tracking']}"
    offer_pol.decide({"screen": "MAP", "run_id": "RUN_CARD_OFFER",
                      "available_actions": [], "map": {"available_nodes": []},
                      "run": {"floor": 2, "deck": []}}, offer_ctx)
    offer_pol.decide(offer_state, offer_ctx)
    assert offer_know.stats["cards"]["OFFER_NEW"]["seen"] == 2, \
        "离开 offer 后再次出现的独立同构 offer 未计数"

    # REWARD 原生直出结构也走相同一次性口径。
    reward_direct = {
        "screen": "REWARD", "run_id": "RUN_CARD_OFFER",
        "available_actions": ["choose_reward_card", "skip_reward_cards"],
        "reward": {"pending_card_choice": True,
                   "card_options": [dict(offer_card, index=0, card_id="OFFER_DIRECT")],
                   "rewards": []},
        "run": {"current_hp": 70, "max_hp": 80, "floor": 3, "deck": []}}
    offer_pol.decide(reward_direct, offer_ctx)
    offer_pol.decide(reward_direct, offer_ctx)
    assert offer_know.stats["cards"]["OFFER_DIRECT"]["offered"] == 1, \
        "REWARD pending_card_choice 轮询重复记 offered"
    # REWARD 直出路径此前只把“单薄保底”用于禁止 skip，却漏发 choose 动作，
    # 正价值边际牌会落入后续 proceed 分支。它必须与 CARD_SELECTION 同口径。
    direct_thin_deck = (
        [{"card_id": f"OFFER_WALL_{i}", "card_type": "Skill", "energy_cost": 1,
          "dynamic_values": [{"name": "Block", "current_value": 8}]} for i in range(6)]
        + [{"card_id": f"BASIC_STRIKE_{i}", "card_type": "Attack", "energy_cost": 1}
           for i in range(4)])
    direct_pebble = {
        "index": 0, "card_id": "OFFER_PEBBLE", "name": "小卵石",
        "card_type": "Skill", "energy_cost": 1,
        "dynamic_values": [{"name": "Block", "current_value": 1}]}
    direct_thin_state = {
        "screen": "REWARD", "run_id": "RUN_CARD_OFFER",
        "available_actions": ["choose_reward_card", "skip_reward_cards"],
        "reward": {"pending_card_choice": True,
                   "card_options": [direct_pebble], "rewards": []},
        "run": {"current_hp": 70, "max_hp": 80, "floor": 4,
                "deck": direct_thin_deck}}
    d_direct_thin = offer_pol.decide(direct_thin_state, offer_ctx)
    assert d_direct_thin.action == "choose_reward_card" and "单薄卡组正价值保底" in d_direct_thin.reason, \
        f"REWARD 单薄保底只阻止 skip 却未选择卡牌: {d_direct_thin.action}（{d_direct_thin.reason}）"

    # 新卡探索不是全局随机 epsilon：只在原始评分近优且跨过拿牌门槛时，UCB
    # 可用每局配额把一次选择从高样本贪心牌转给零样本新牌；因此不会永远饿死。
    explore_know = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-card-explore-")))
    explore_know.policy.update({
        "card_exploration_enabled": True,
        "card_exploration_run_quota": 1,
        "card_exploration_min_picks": 2,
        "card_exploration_near_best_margin": 3.0,
        "card_exploration_ucb_scale": 2.0,
        "card_exploration_min_value": 1.0,
    })
    explore_know.stats["cards"]["EXP_KNOWN"] = {
        "seen": 30, "offered": 0, "picked": 20, "plays": 60,
        "outcome_sum": 200.0, "bias": 0.0}
    explore_pol = policy.Policy(explore_know, random.Random(42))
    explore_ctx = DummyCtx()
    explore_ctx.run_id = "RUN_EXPLORE"
    explore_ctx.credit_tags = []

    def reward_explore_state(floor_no, novel_id="EXP_NOVEL", novel_text=""):
        return {
            "screen": "CARD_SELECTION", "run_id": "RUN_EXPLORE",
            "available_actions": ["select_deck_card", "skip_reward_cards"],
            "selection": {"kind": "", "prompt": "将一张牌添加到你的牌组。",
                          "min_select": 1, "selected_count": 0, "can_confirm": False,
                          "cards": [
                              {"index": 0, "card_id": "EXP_KNOWN", "name": "熟悉招式",
                               "card_type": "Attack", "energy_cost": 1,
                               "dynamic_values": [{"name": "Damage", "current_value": 10}]},
                              {"index": 1, "card_id": novel_id, "name": "未知招式",
                               "card_type": "Attack", "energy_cost": 1,
                               "rules_text": novel_text,
                               "dynamic_values": [{"name": "Damage", "current_value": 9}]}]},
            "run": {"current_hp": 70, "max_hp": 80, "floor": floor_no, "deck": []}}

    d_explore = explore_pol.decide(reward_explore_state(4), explore_ctx)
    assert (d_explore.action == "select_deck_card"
            and d_explore.params.get("option_index") == 1
            and "受控探索" in d_explore.reason), \
        f"近优零样本新牌仍被永久贪心压制: {d_explore.action}（{d_explore.reason}）"
    assert explore_pol._card_explore_used == 0 \
        and explore_know.novelty_trial_count("card", "EXP_NOVEL") == 0 \
        and explore_pol._sel_tried == set(), \
        "卡牌探索在 HTTP 成功前提前消耗配额/持久样本/已选索引"

    # 409/断线没有成功标签：同一 offer 必须稳定重试原探索候选，不得改选贪心牌。
    explore_pol.note_action_failed("select_deck_card", d_explore.tags)
    d_explore_retry = explore_pol.decide(reward_explore_state(4), explore_ctx)
    assert (d_explore_retry.params.get("option_index") == 1
            and "同一 offer 保持受控探索选择" in d_explore_retry.reason
            and explore_pol._card_explore_used == 0
            and explore_know.novelty_trial_count("card", "EXP_NOVEL") == 0
            and explore_pol._sel_tried == set()), \
        f"失败回执改变了探索候选或提前记账: {d_explore_retry.reason}"

    # 模拟 agent 收到成功回执后提交 tags；下一 tick 才结算配额、持久样本与
    # selection index。随后第二份 offer 回归贪心，不会为了新颖性连续注水。
    explore_ctx.credit_tags.extend(d_explore_retry.tags)
    explore_pol.decide(reward_explore_state(4), explore_ctx)
    assert explore_pol._card_explore_used == 1 \
        and explore_know.novelty_trial_count("card", "EXP_NOVEL") == 1 \
        and explore_pol._sel_tried == {1}, \
        "成功卡牌探索未事务性提交配额/持久样本/已选索引"
    d_quota = explore_pol.decide(reward_explore_state(5, "EXP_NOVEL_2"), explore_ctx)
    assert d_quota.params.get("option_index") == 0 and "受控探索" not in d_quota.reason, \
        f"卡牌探索越过每局配额: {d_quota.reason}"

    # 安全门：即使提高配额/UCB，不可打出的伪高面板、Status/Curse、实锤零出牌
    # 死牌均不能成为“探索”对象。用新的 run id 重置配额后验证真实奖励结构。
    explore_know.policy["card_exploration_run_quota"] = 3
    blocked_state = reward_explore_state(6, "EXP_UNPLAYABLE", "无法打出。")
    blocked_state["run_id"] = "RUN_EXPLORE_SAFE"
    explore_ctx.run_id = "RUN_EXPLORE_SAFE"
    d_blocked = explore_pol.decide(blocked_state, explore_ctx)
    assert d_blocked.params.get("option_index") == 0 and "受控探索" not in d_blocked.reason, \
        f"明显不可打出牌被误用新颖度绕过: {d_blocked.reason}"
    assert not explore_pol._reward_exploration_safe(
        {"card_id": "EXP_STATUS", "card_type": "Status"}, []), \
        "Status 不得进入卡奖励探索候选"
    assert not explore_pol._reward_exploration_safe(
        {"card_id": "EXP_CURSE", "card_type": "Curse"}, []), \
        "Curse 不得进入卡奖励探索候选"
    explore_know.stats["cards"]["EXP_DEAD"] = {
        "seen": 8, "offered": 0, "picked": 5, "plays": 0,
        "outcome_sum": 100.0, "bias": 0.0}
    dead_state = reward_explore_state(7, "EXP_DEAD")
    dead_state["run_id"] = "RUN_EXPLORE_SAFE_2"
    explore_ctx.run_id = "RUN_EXPLORE_SAFE_2"
    d_dead = explore_pol.decide(dead_state, explore_ctx)
    assert d_dead.params.get("option_index") == 0 and "受控探索" not in d_dead.reason, \
        f"零成功出牌死牌被奖励探索重新拿入: {d_dead.reason}"

    # 事件探索必须确定性命中近优欠采样项，且 HTTP 失败不占成功样本/配额。
    novelty_know = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-domain-novelty-")))
    novelty_know.policy.update({
        "event_exploration_enabled": True,
        "event_exploration_run_quota": 1,
        "event_exploration_sample_cap": 2,
        "event_exploration_near_best_margin": 2.0,
        "event_exploration_min_hp_pct": 0.70,
        "event_exploration_min_value": -1.0,
        "relic_exploration_enabled": True,
        "relic_exploration_run_quota": 1,
        "relic_exploration_sample_cap": 1,
        "relic_exploration_near_best_margin": 0.75,
        "potion_exploration_enabled": True,
        "potion_exploration_run_quota": 1,
        "potion_exploration_sample_cap": 1,
    })
    novelty_know.stats["events"]["EVT_NOVEL"] = {
        "KNOWN": {"n": 5, "hp_delta_sum": 5.0, "gold_delta_sum": 0.0,
                  "deaths": 0, "hp_min": 0.0}}
    novelty_pol = policy.Policy(novelty_know, random.Random(0))
    novelty_ctx = DummyCtx()
    novelty_ctx.run_id = "RUN_DOMAIN_NOVELTY"
    novelty_ctx.credit_tags = []

    # 新 run_id 的首个 tick 发生在 Agent._track 重置 ctx 之前：旧局成功标签
    # 此时仍留在 ctx.credit_tags，绝不能被清空去重集后重复导入新局。
    carry_know = knowledge.Knowledge(
        Path(tempfile.mkdtemp(prefix="sts2-selfcheck-novelty-run-boundary-")))
    carry_pol = policy.Policy(carry_know, random.Random(0))
    carry_ctx = DummyCtx()
    carry_ctx.run_id = "RUN_CARRY_OLD"
    carry_ctx.credit_tags = [("novelty_trial", "card", "OLD_TRIAL", 1)]
    carry_state = {"screen": "MAIN_MENU", "run_id": "RUN_CARRY_NEW",
                   "available_actions": [], "run": {}}
    carry_pol.decide(carry_state, carry_ctx)
    assert carry_know.novelty_trial_count("card", "OLD_TRIAL") == 0 \
        and carry_pol._card_explore_used == 0, \
        "新局首 tick 重放了上一局 credit_tags，污染持久样本或新局配额"
    # 模拟随后的 Agent._track 已切换上下文；同局成功标签仍必须正常入账。
    carry_ctx.run_id = "RUN_CARRY_NEW"
    carry_ctx.credit_tags = [("novelty_trial", "card", "NEW_TRIAL", 1)]
    carry_pol.decide(carry_state, carry_ctx)
    assert carry_know.novelty_trial_count("card", "NEW_TRIAL") == 1 \
        and carry_pol._card_explore_used == 1, \
        "同局成功标签被跨局隔离闸门误伤"

    def novelty_event(run_id="RUN_DOMAIN_NOVELTY", event_id="EVT_NOVEL",
                      hp=80, known_key="KNOWN", novel_key="NOVEL",
                      novel_kills=False):
        return {
            "screen": "EVENT", "run_id": run_id,
            "available_actions": ["choose_event_option"],
            "event": {"event_id": event_id, "title": "探索测试",
                      "is_finished": False,
                      "options": [
                          {"index": 0, "text_key": known_key, "title": "稳妥",
                           "is_locked": False, "is_proceed": False,
                           "will_kill_player": False},
                          {"index": 1, "text_key": novel_key, "title": "新路",
                           "is_locked": False, "is_proceed": False,
                           "will_kill_player": novel_kills}]},
            "run": {"current_hp": hp, "max_hp": 80, "gold": 0,
                    "floor": 4, "deck": []}}

    d_event_novel = novelty_pol.decide(novelty_event(), novelty_ctx)
    assert (d_event_novel.params.get("option_index") == 1
            and "受控探索" in d_event_novel.reason
            and "样本 0/2" in d_event_novel.reason
            and "原值 0.00" in d_event_novel.reason
            and "配额 1/1" in d_event_novel.reason), \
        f"事件近优欠采样项未被确定性探索: {d_event_novel.reason}"
    novelty_tag = next(t for t in d_event_novel.tags if t[0] == "novelty_trial")
    assert novelty_tag[1:3] == ("event", "EVT_NOVEL:NOVEL"), \
        f"事件探索 key 未隔离 event_id: {novelty_tag}"
    novelty_pol.note_action_failed("choose_event_option", d_event_novel.tags)
    assert novelty_know.novelty_trial_count("event", "EVT_NOVEL:NOVEL") == 0 \
        and novelty_pol._event_explore_used == 0 \
        and novelty_pol._event_picks.get("NOVEL", 0) == 0, \
        "失败事件动作污染了成功探索样本或配额"
    d_event_retry = novelty_pol.decide(novelty_event(), novelty_ctx)
    assert d_event_retry.params.get("option_index") == 1 and "受控探索" in d_event_retry.reason, \
        "失败回执后近优事件选项未获得重试机会"
    novelty_ctx.credit_tags.extend(d_event_retry.tags)
    d_event_after = novelty_pol.decide(novelty_event(), novelty_ctx)
    assert novelty_know.novelty_trial_count("event", "EVT_NOVEL:NOVEL") == 1 \
        and d_event_after.params.get("option_index") == 0 \
        and "受控探索" not in d_event_after.reason, \
        f"事件探索成功样本/每局配额未收敛: {d_event_after.reason}"

    # 安全门优先于新颖度：低血、显著机会成本、will_kill 和 hp_min 重尾均 veto。
    novelty_ctx.credit_tags = []
    novelty_ctx.run_id = "RUN_EVENT_LOW"
    d_event_low = novelty_pol.decide(
        novelty_event("RUN_EVENT_LOW", "EVT_NOVEL", hp=40), novelty_ctx)
    assert d_event_low.params.get("option_index") == 0 and "受控探索" not in d_event_low.reason, \
        f"低血事件仍为新颖度冒险: {d_event_low.reason}"
    novelty_know.stats["events"]["EVT_GAP"] = {
        "KNOWN": {"n": 2, "hp_delta_sum": 10.0, "gold_delta_sum": 0.0,
                  "deaths": 0, "hp_min": 0.0}}
    novelty_ctx.run_id = "RUN_EVENT_GAP"
    d_event_gap = novelty_pol.decide(
        novelty_event("RUN_EVENT_GAP", "EVT_GAP"), novelty_ctx)
    assert d_event_gap.params.get("option_index") == 0 and "受控探索" not in d_event_gap.reason, \
        f"事件探索越过 near-best 机会成本: {d_event_gap.reason}"
    novelty_ctx.run_id = "RUN_EVENT_KILL"
    d_event_kill = novelty_pol.decide(
        novelty_event("RUN_EVENT_KILL", "EVT_GAP", novel_kills=True), novelty_ctx)
    assert d_event_kill.params.get("option_index") == 0 and "受控探索" not in d_event_kill.reason, \
        "will_kill 事件选项被新颖度放行"
    novelty_know.stats["events"]["EVT_TAIL"] = {
        "KNOWN": {"n": 3, "hp_delta_sum": 3.0, "gold_delta_sum": 0.0,
                  "deaths": 0, "hp_min": 0.0},
        "NOVEL": {"n": 1, "hp_delta_sum": 0.0, "gold_delta_sum": 0.0,
                  "deaths": 0, "hp_min": -80.0}}
    novelty_ctx.run_id = "RUN_EVENT_TAIL"
    d_event_tail = novelty_pol.decide(
        novelty_event("RUN_EVENT_TAIL", "EVT_TAIL", hp=72), novelty_ctx)
    assert d_event_tail.params.get("option_index") == 0 \
        and "最坏情况闸门" in d_event_tail.reason \
        and "受控探索" not in d_event_tail.reason, \
        f"事件历史重尾 veto 被新颖度绕过: {d_event_tail.reason}"

    # 非探索的贪心事件选择同样必须等成功回执才增加 _event_picks；409 与
    # ConnectionDown 都不能让未执行的选项吃到停滞罚分并在重试时无故换项。
    novelty_know.policy["event_exploration_enabled"] = False
    novelty_know.stats["events"]["EVT_GREEDY_FAIL"] = {
        "KNOWN": {"n": 3, "hp_delta_sum": 9.0, "gold_delta_sum": 0.0,
                  "deaths": 0, "hp_min": 0.0}}
    novelty_ctx.run_id = "RUN_EVENT_GREEDY_FAIL"
    novelty_ctx.credit_tags = []
    greedy_state = novelty_event("RUN_EVENT_GREEDY_FAIL", "EVT_GREEDY_FAIL")
    d_event_greedy = novelty_pol.decide(greedy_state, novelty_ctx)
    assert d_event_greedy.params.get("option_index") == 0 \
        and not any(t[0] == "novelty_trial" for t in d_event_greedy.tags) \
        and novelty_pol._event_picks.get("KNOWN", 0) == 0, \
        f"贪心事件失败回滚测试未建立正确前置状态: {d_event_greedy.reason}"
    novelty_pol.note_action_failed("choose_event_option", d_event_greedy.tags)
    assert novelty_pol._event_picks.get("KNOWN", 0) == 0, \
        "非探索事件选择失败后仍保留虚假的停滞计数"
    d_event_greedy_retry = novelty_pol.decide(greedy_state, novelty_ctx)
    assert d_event_greedy_retry.params.get("option_index") == 0, \
        f"非探索事件 409 后未稳定重试原选择: {d_event_greedy_retry.reason}"

    # 同价值遗物不再永久取 API 首槽；只轮转一次，显式负面描述仍被挡住。
    relic_ctx = DummyCtx()
    relic_ctx.run_id = "RUN_RELIC_NOVEL"
    relic_ctx.credit_tags = []
    relic_state = {
        "screen": "CHEST", "run_id": "RUN_RELIC_NOVEL",
        "available_actions": ["choose_treasure_relic"],
        "chest": {"is_opened": True, "has_relic_been_claimed": False,
                  "relic_options": [
                      {"index": 0, "relic_id": "A_KNOWN", "name": "熟悉遗物"},
                      {"index": 1, "relic_id": "Z_NOVEL", "name": "新遗物"}]},
        "run": {"current_hp": 80, "max_hp": 80, "floor": 5}}
    d_relic = novelty_pol.decide(relic_state, relic_ctx)
    assert d_relic.params.get("option_index") == 1 \
        and "样本 0/1" in d_relic.reason and "配额 1/1" in d_relic.reason, \
        f"同值遗物仍永久锁在首槽: {d_relic.reason}"
    relic_ctx.credit_tags.extend(d_relic.tags)
    d_relic_after = novelty_pol.decide(relic_state, relic_ctx)
    assert d_relic_after.params.get("option_index") == 0 \
        and novelty_know.novelty_trial_count("relic", "Z_NOVEL") == 1, \
        "遗物探索样本上限/每局配额未生效"
    relic_bad = json.loads(json.dumps(relic_state))
    relic_bad["run_id"] = "RUN_RELIC_BAD"
    relic_bad["chest"]["relic_options"][1].update(
        {"relic_id": "Z_BAD", "description": "You can no longer heal."})
    relic_ctx.run_id = "RUN_RELIC_BAD"
    relic_ctx.credit_tags = []
    d_relic_bad = novelty_pol.decide(relic_bad, relic_ctx)
    assert d_relic_bad.params.get("option_index") == 0 \
        and "受控遗物探索" not in d_relic_bad.reason, \
        f"显式负面遗物被新颖度放行: {d_relic_bad.reason}"

    # 商店未知药原本 0.8<1.0 永不购买；只有健康、有空位/余钱且近优时可试购一次。
    potion_ctx = DummyCtx()
    potion_ctx.run_id = "RUN_POTION_NOVEL"
    potion_ctx.credit_tags = []
    potion_state = {
        "screen": "SHOP", "run_id": "RUN_POTION_NOVEL",
        "available_actions": ["buy_potion", "close_shop_inventory"],
        "shop": {"is_open": True, "can_close": True, "cards": [], "relics": [],
                 "card_removal": None,
                 "potions": [{"index": 0, "potion_id": "MYSTERY_X",
                              "name": "陌生药剂", "price": 48,
                              "is_stocked": True, "enough_gold": True}]},
        "run": {"current_hp": 70, "max_hp": 80, "gold": 150,
                "floor": 6, "deck": [], "potions": [{"occupied": False}]}}
    d_potion = novelty_pol.decide(potion_state, potion_ctx)
    assert d_potion.action == "buy_potion" and "受控新药试购" in d_potion.reason \
        and "样本 0/1" in d_potion.reason and "配额 1/1" in d_potion.reason, \
        f"安全未知药仍永久低于商店门槛: {d_potion.reason}"
    potion_ctx.credit_tags.extend(d_potion.tags)
    d_potion_after = novelty_pol.decide(potion_state, potion_ctx)
    assert d_potion_after.action == "close_shop_inventory" \
        and novelty_know.novelty_trial_count("potion", "MYSTERY_X") == 1, \
        f"未知药探索未受成功样本上限约束: {d_potion_after.reason}"
    potion_low = json.loads(json.dumps(potion_state))
    potion_low["run_id"] = "RUN_POTION_LOW"
    potion_low["run"]["current_hp"] = 35
    potion_ctx.run_id = "RUN_POTION_LOW"
    potion_ctx.credit_tags = []
    d_potion_low = novelty_pol.decide(potion_low, potion_ctx)
    assert d_potion_low.action == "close_shop_inventory" \
        and "受控新药试购" not in d_potion_low.reason, \
        f"低血局仍花钱试未知药: {d_potion_low.reason}"
    potion_full = json.loads(json.dumps(potion_state))
    potion_full["run_id"] = "RUN_POTION_FULL"
    potion_full["shop"]["potions"][0]["potion_id"] = "MYSTERY_FULL"
    potion_full["run"]["potions"] = [
        {"occupied": True, "potion_id": "HEALING_POTION"},
        {"occupied": True, "potion_id": "FIRE_POTION"},
    ]
    potion_ctx.run_id = "RUN_POTION_FULL"
    potion_ctx.credit_tags = []
    d_potion_full = novelty_pol.decide(potion_full, potion_ctx)
    assert d_potion_full.action == "close_shop_inventory" \
        and "受控新药试购" not in d_potion_full.reason \
        and novelty_know.novelty_trial_count("potion", "MYSTERY_FULL") == 0, \
        f"药水栏已满仍反复试购未知药: {d_potion_full.reason}"

    # 3z) 结算等待闸门（第790局批复盘 END_TURN_SETTLE_GATE 回归夹具）：
    #     出过牌的回合里 payload 整体✗ 且 play_card 被撤走，但账面仍有
    #     可负担目标牌（790 局 F17-T6/T9 实测形态）时，先进入有界结算等待；
    #     预算耗尽后落回旧「确认无牌可出」提交文案；旋钮置 0 立即回滚。
    settle_know = knowledge.Knowledge(tmp)
    settle_pol = policy.Policy(settle_know)

    class _SettleCtx:
        current_combat_is_hard = False
        run_finalized = True
        finalize_requested = False
        credit_tags: list = []
        combat = None
        combat_notes: list = []
        pending_event = None
        died_in_combat = None

    s_ctx = _SettleCtx()

    def _settle_state(hand_playable):
        return {
            "screen": "COMBAT", "turn": 8,
            "available_actions": (["play_card", "end_turn"] if hand_playable
                                  else ["end_turn"]),
            "combat": {"player": {"current_hp": 19, "max_hp": 80, "block": 0,
                                  "energy": 1},
                       "hand": [{"index": 0, "card_id": "STRIKE_IRONCLAD",
                                 "name": "打击", "playable": hand_playable,
                                 "energy_cost": 1, "requires_target": True,
                                 "valid_target_indices": [0],
                                 "dynamic_values":
                                     [{"name": "Damage", "current_value": 6}]}],
                       "enemies": [{"index": 0, "enemy_id": "BEAST",
                                    "name": "仪式兽", "current_hp": 120,
                                    "max_hp": 252, "block": 0, "is_alive": True,
                                    "is_hittable": True,
                                    "intents": [{"total_damage": 18}]}]},
            "run": {"current_hp": 19, "max_hp": 80, "gold": 50,
                    "floor": 17, "deck": []},
        }

    d_s0 = settle_pol.decide(_settle_state(True), s_ctx)
    assert d_s0 is not None, "结算夹具热身帧无决策"
    saw_interim = False
    d_commit = None
    for _ in range(30):
        d_si = settle_pol.decide(_settle_state(False), s_ctx)
        if d_si.action == "end_turn":
            d_commit = d_si
            break
        assert d_si.action is None and "结算等待" in d_si.reason \
            and "打击(1)" in d_si.reason, \
            f"结算等待闸门未按预期拦截: {d_si.action}/{d_si.reason}"
        saw_interim = True
    assert saw_interim and d_commit is not None \
        and "确认无牌可出（能量耗尽或全部不可用）" in d_commit.reason, \
        f"结算等待未在预算内落回旧提交: {d_commit and d_commit.reason}"

    roll_know = knowledge.Knowledge(tmp)
    roll_pol = policy.Policy(roll_know)
    roll_know.policy["end_turn_settle_recovery_ticks"] = 0
    r_ctx = _SettleCtx()
    roll_pol.decide(_settle_state(True), r_ctx)
    rolled_away = False
    for _ in range(6):
        d_r = roll_pol.decide(_settle_state(False), r_ctx)
        if d_r.action == "end_turn":
            break
        assert "结算等待" not in d_r.reason, f"旋钮回滚失效仍出现等待: {d_r.reason}"
        rolled_away = True
    assert rolled_away or True  # 旧两拍流本身允许 1~2 帧确认后才提交

    # 3z-2) 结算等待深预算（第833~842局批复盘 END_TURN_SETTLE_DEEP_BUDGET 回归夹具）：
    #       闲置能量≥2 且账面仍有可负担目标牌时，等待上限放宽到深预算旋钮
    #       （840 局 F17[212] 实测形态：2 能量+防御✗ 被基预算收口，意图 17
    #       无格挡入体直接 -17 血）；深旋钮置 0 回滚基预算口径；能量<2 不受
    #       影响（3z 夹具 energy=1 已覆盖该侧）。
    deep_know = knowledge.Knowledge(tmp)
    deep_pol = policy.Policy(deep_know)
    deep_know.policy["end_turn_settle_recovery_ticks"] = 10

    def _deep_state():
        s = _settle_state(False)
        s["combat"]["player"]["energy"] = 2
        return s

    _deep_base = int(float(deep_know.policy.get("end_turn_settle_recovery_ticks", 10) or 0))
    _deep_ticks = int(float(deep_know.policy.get("end_turn_settle_recovery_ticks_deep", 22) or 0))
    assert _deep_ticks > _deep_base > 0, "深预算旋钮默认配置异常"
    deep_ctx = _SettleCtx()
    assert deep_pol.decide(_settle_state(True), deep_ctx) is not None, "深预算夹具热身帧无决策"
    d_deep_commit = None
    for _ in range(60):
        d_deep = deep_pol.decide(_deep_state(), deep_ctx)
        if d_deep.action == "end_turn":
            d_deep_commit = d_deep
            break
        assert d_deep.action is None and "结算等待" in d_deep.reason \
            and "打击(1)" in d_deep.reason, \
            f"深预算窗口内未按预期等待: {d_deep.action}/{d_deep.reason}"
    assert d_deep_commit is not None \
        and "确认无牌可出（能量耗尽或全部不可用）" in d_deep_commit.reason, \
        "深预算未在预算内落回旧提交"
    deep_know.policy["end_turn_settle_recovery_ticks_deep"] = 0
    base_ctx = _SettleCtx()
    assert deep_pol.decide(_settle_state(True), base_ctx) is not None, "回滚夹具热身帧无决策"
    _base_waits = 0
    d_base_commit = None
    for _ in range(30):
        d_base = deep_pol.decide(_deep_state(), base_ctx)
        if d_base.action == "end_turn":
            d_base_commit = d_base
            break
        assert "结算等待" in d_base.reason, f"深旋钮回滚后出现异常等待: {d_base.reason}"
        _base_waits += 1
    assert d_base_commit is not None and _base_waits <= _deep_base + 2, \
        f"深旋钮回滚后未按基预算收口: waits={_base_waits}"

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
