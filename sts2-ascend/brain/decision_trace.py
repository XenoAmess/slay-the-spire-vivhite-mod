"""Read-only policy telemetry for the ASCEND-VISION dashboard.

The trace is deliberately derived from the decision and the state that already
produced it.  It never calls a policy scorer, consumes randomness, or feeds data
back into the policy.  A handler may provide a richer ``Decision.trace`` later;
this module supplies a truthful, bounded trace for every screen today.
"""
from __future__ import annotations

import re
from typing import Any


MAX_GATES = 32
MAX_CANDIDATES = 8
MAX_TEXT = 280


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    value = "" if value is None else str(value)
    value = " ".join(value.replace("\x00", " ").split())
    return value[:limit]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return round(result, 3)


def _same_index(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return str(left) == str(right)


def _ranked_values(reason: str) -> list[tuple[str, float]]:
    """Recover scores the policy already emitted; do not calculate new ones."""
    result: list[tuple[str, float]] = []
    seen: set[str] = set()
    for match in re.finditer(
            r"([^=＝,，;；|/\n]{1,42})[=＝]\s*(-?\d+(?:\.\d+)?)", reason or ""):
        label = match.group(1).strip(" ：:（）()[]【】\t")
        # Reasons often prefix the first item with "候选：".
        for separator in ("：", ":"):
            if separator in label:
                label = label.rsplit(separator, 1)[-1].strip()
        score = _number(match.group(2))
        key = label.casefold()
        if label and score is not None and key not in seen:
            seen.add(key)
            result.append((_text(label, 64), score))
    return result[:MAX_CANDIDATES]


def _candidate(label: Any, index: Any = None, *, score: Any = None,
               status: str = "available", why: Any = "", action: str = "") -> dict:
    return {
        "label": _text(label, 72) or "未命名候选",
        "score": _number(score),
        "status": status,
        "why": _text(why, 150),
        "index": index,
        "action": _text(action, 48),
    }


def _item_label(item: dict, fallback: str) -> str:
    return _text(item.get("name") or item.get("title") or item.get("description")
                 or item.get("text_key") or item.get("card_id")
                 or item.get("relic_id") or item.get("potion_id") or fallback, 72)


def _state_candidates(state: dict, decision) -> list[dict]:
    screen = str(state.get("screen") or "UNKNOWN").upper()
    params = getattr(decision, "params", {}) or {}
    action = str(getattr(decision, "action", "") or "")
    selected_key = (params.get("card_index") if action == "play_card"
                    else params.get("option_index"))
    rows: list[dict] = []

    def add(items, fallback: str, candidate_action: str = "", *, selected=None) -> None:
        for position, raw in enumerate(items or []):
            if not isinstance(raw, dict):
                continue
            index = raw.get("index", raw.get("i", position))
            is_selected = (candidate_action == action and
                           _same_index(index, selected_key if selected is None else selected))
            locked = bool(raw.get("is_locked"))
            playable = raw.get("playable")
            status = "chosen" if is_selected else (
                "locked" if locked or playable is False else "available")
            why = (raw.get("unplayable_reason") or raw.get("unplayable_reason_raw")
                   or raw.get("why_not_playable") or raw.get("disabled_reason")
                   or raw.get("description") or raw.get("option_id") or "")
            score = raw.get("score", raw.get("value"))
            rows.append(_candidate(_item_label(raw, f"{fallback} {index}"), index,
                                   score=score, status=status, why=why,
                                   action=candidate_action))

    if screen == "COMBAT":
        combat = state.get("combat") or {}
        add(combat.get("hand"), "手牌", "play_card")
    elif screen == "MAP":
        nodes = (state.get("map") or {}).get("available_nodes") or []
        for position, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            index = node.get("index", position)
            label = f"{node.get('node_type') or '节点'}({node.get('row', '?')},{node.get('col', '?')})"
            rows.append(_candidate(label, index,
                                   status="chosen" if action == "choose_map_node" and
                                   _same_index(index, selected_key) else "available",
                                   why=node.get("description", ""), action="choose_map_node"))
    elif screen == "REWARD":
        reward = state.get("reward") or {}
        if reward.get("pending_card_choice"):
            add(reward.get("card_options"), "奖励卡", "choose_reward_card")
        else:
            add(reward.get("rewards"), "奖励", "claim_reward")
    elif screen == "CARD_SELECTION":
        add((state.get("selection") or {}).get("cards"), "卡牌", "select_deck_card")
    elif screen == "SHOP":
        shop = state.get("shop") or {}
        add(shop.get("cards"), "卡牌", "buy_card")
        add(shop.get("relics"), "遗物", "buy_relic")
        add(shop.get("potions"), "药水", "buy_potion")
    elif screen == "EVENT":
        add((state.get("event") or {}).get("options"), "事件选项", "choose_event_option")
    elif screen == "REST":
        add((state.get("rest") or {}).get("options"), "篝火选项", "choose_rest_option")
    elif screen == "CHEST":
        chest = state.get("chest") or {}
        add(chest.get("relic_options") or chest.get("relics") or chest.get("options"),
            "宝箱", "choose_treasure_relic")
    return rows


def _merge_scores(candidates: list[dict], reason: str) -> list[dict]:
    ranked = _ranked_values(reason)
    if not ranked:
        return candidates[:MAX_CANDIDATES]
    used: set[int] = set()
    for row in candidates:
        label = row["label"].casefold()
        for pos, (ranked_label, score) in enumerate(ranked):
            other = ranked_label.casefold()
            if pos not in used and (other in label or label in other):
                row["score"] = score
                used.add(pos)
                break
    # Preserve policy-emitted candidates even when a state label cannot be matched.
    for pos, (label, score) in enumerate(ranked):
        if pos not in used:
            candidates.append(_candidate(label, score=score, why="策略本次已计算的评分"))
    candidates.sort(key=lambda row: (
        row.get("status") != "chosen",
        row.get("score") is None,
        -(row.get("score") or 0.0),
    ))
    return candidates[:MAX_CANDIDATES]


def _observations(state: dict) -> dict:
    screen = _text(state.get("screen") or "UNKNOWN", 40)
    run = state.get("run") or {}
    combat = state.get("combat") or {}
    player = combat.get("player") or {}
    facts = [f"屏幕 {screen}", f"楼层 F{run.get('floor', 0)}"]
    hp = run.get("current_hp", player.get("current_hp"))
    max_hp = run.get("max_hp", player.get("max_hp"))
    if hp is not None:
        facts.append(f"生命 {hp}/{max_hp or '?'}")
    if screen == "COMBAT":
        facts.append(f"回合 {state.get('turn', '?')}")
        facts.append(f"能量 {player.get('energy', '?')}")
        incoming = 0
        for enemy in combat.get("enemies") or []:
            if not isinstance(enemy, dict) or not enemy.get("is_alive", True):
                continue
            for intent in enemy.get("intents") or []:
                if isinstance(intent, dict):
                    try:
                        incoming += int(intent.get("total_damage") or 0)
                    except (TypeError, ValueError):
                        pass
        facts.append(f"敌方意图伤害 {incoming}")
    return {"title": f"{screen} · F{run.get('floor', 0)}", "facts": facts[:8]}


def build_decision_trace(state: dict, decision, *, parse_reason_scores: bool = True) -> dict:
    reason = _text(getattr(decision, "reason", ""), 800)
    action = getattr(decision, "action", None)
    actions = [str(item) for item in (state.get("available_actions") or [])]
    candidates = _state_candidates(state, decision)
    if parse_reason_scores:
        candidates = _merge_scores(candidates, reason)
    selected_row = next((row for row in candidates if row.get("status") == "chosen"), None)
    legal = not action or action in actions or not actions
    gates = [
        {"label": "SCAN 状态载荷", "status": "pass", "value": _text(state.get("screen") or "UNKNOWN", 48)},
        {"label": "GATE 动作可用性", "status": "pass" if legal else "warn",
         "value": "等待" if not action else ("接口允许" if legal else "接口列表未声明")},
        {"label": "RANK 候选池", "status": "pass" if candidates else "neutral",
         "value": f"{len(candidates)} 个可展示候选" if candidates else "规则直达，无评分池"},
        {"label": "LOCK 最终选择", "status": "pass" if action else "wait",
         "value": _text(action or "等待下一状态", 64)},
    ]
    selected_label = selected_row.get("label") if selected_row else _text(action or "等待", 72)
    return {
        "observation": _observations(state),
        "gates": gates[:MAX_GATES],
        "candidates": candidates[:MAX_CANDIDATES],
        "selected": {
            "action": action,
            "label": selected_label,
            "params": dict(getattr(decision, "params", {}) or {}),
            "reason": reason,
        },
        "explanation": [reason] if reason else ["等待更多可操作状态"],
    }


class DecisionTraceBuilder:
    """Collect values while a policy handler is already computing them.

    The builder has no reference to Policy or RNG.  Callers pass only values that
    have already been calculated for the real decision, which makes tracing a
    passive copy operation rather than a second evaluation path.
    """

    def __init__(self, state: dict):
        self.state = state
        self._gates: list[dict] = []
        self._candidates: list[dict] = []
        self._notes: list[str] = []

    def gate(self, label: Any, status: str, value: Any = "") -> None:
        if len(self._gates) >= MAX_GATES:
            return
        self._gates.append({
            "label": _text(label, 72),
            "status": _text(status, 16) or "neutral",
            "value": _text(value, 180),
        })

    def candidate(self, label: Any, score: Any, *, index: Any = None,
                  action: str = "", status: str = "eligible", why: Any = "",
                  target: Any = None) -> None:
        if len(self._candidates) >= 32:
            return
        row = _candidate(label, index, score=score, status=status,
                         why=why, action=action)
        if target is not None:
            row["target"] = _safe_target(target)
        self._candidates.append(row)

    def note(self, value: Any) -> None:
        note = _text(value, 220)
        if note and len(self._notes) < 4:
            self._notes.append(note)

    def finish(self, decision) -> dict:
        trace = build_decision_trace(self.state, decision, parse_reason_scores=False)
        if self._gates:
            # Retain SCAN/LOCK/ACK mechanics while replacing the generic middle
            # with the handler's actual gates.
            generic = trace.get("gates") or []
            trace["gates"] = (generic[:1] + list(self._gates) + generic[-1:])[:MAX_GATES]
        if self._candidates:
            params = getattr(decision, "params", {}) or {}
            action = str(getattr(decision, "action", "") or "")
            selected_index = (params.get("card_index") if action == "play_card"
                              else params.get("option_index"))
            chosen = None
            for row in self._candidates:
                if (row.get("action") == action and
                        _same_index(row.get("index"), selected_index)):
                    row["status"] = "chosen"
                    chosen = row
                elif row.get("status") in ("eligible", "available"):
                    row["status"] = "rejected"
            ordered = sorted(self._candidates, key=lambda row: (
                row.get("status") != "chosen",
                row.get("score") is None,
                -(row.get("score") or 0.0),
                row.get("label") or "",
            ))[:MAX_CANDIDATES]
            trace["candidates"] = ordered
            if chosen is not None:
                selected = trace.get("selected") or {}
                selected["label"] = chosen.get("label")
                selected["score"] = chosen.get("score")
                if chosen.get("target") is not None:
                    selected["target"] = chosen.get("target")
                trace["selected"] = selected
        if self._notes:
            trace["explanation"] = list(self._notes) + list(trace.get("explanation") or [])
        return trace


def _safe_target(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key)[:40]: _text(item, 80) for key, item in list(value.items())[:8]}
    return _text(value, 80)


def ensure_decision_trace(state: dict, decision):
    """Attach a fallback trace without allowing telemetry to break policy."""
    try:
        if not isinstance(getattr(decision, "trace", None), dict):
            decision.trace = build_decision_trace(state, decision)
    except Exception:
        try:
            decision.trace = {
                "observation": {"title": _text(state.get("screen") or "UNKNOWN")},
                "gates": [], "candidates": [],
                "selected": {"action": getattr(decision, "action", None),
                             "label": _text(getattr(decision, "action", None) or "等待"),
                             "params": dict(getattr(decision, "params", {}) or {}),
                             "reason": _text(getattr(decision, "reason", ""))},
                "explanation": [_text(getattr(decision, "reason", ""))],
            }
        except Exception:
            pass
    return decision
