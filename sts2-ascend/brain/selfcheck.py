"""冒烟自检 —— LLM 复盘修改任何 brain/*.py 后必须通过本检查。

覆盖：全模块导入 + 用假状态驱动 Policy 各屏幕处理器不抛异常。
"""
from __future__ import annotations

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

    # 4) 真实知识库可加载（验证数据结构兼容性——若复盘改了 stats/policy 结构这里会暴露）
    real = knowledge.Knowledge(BRAIN.parent / "knowledge")
    assert real.stats.get("global") is not None and real.policy, "knowledge structure broken"
    pol2 = policy.Policy(real)
    assert pol2.decide(fake_states[1], ctx) is not None

    print("SELFCHECK OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
