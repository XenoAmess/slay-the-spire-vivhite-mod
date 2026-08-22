"""Persistent knowledge store — the agent's long-term memory and evolution substrate.

Layout under knowledge/:
  stats.json        aggregated outcome statistics per card / relic / enemy comp / event option / room type
  policy.json       tunable decision weights, mutated by reflection after each run
  progression.json  ascension ladder state (win -> climb)
  lessons.md        human-readable self-summary appended after every run
  runs/<id>.json    full decision log of one run

All learning is online: every commit_* call updates incremental means immediately,
so the very next decision of the same session benefits.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

SHRINK_K = 6.0  # shrinkage strength toward prior mean

DEFAULT_POLICY = {
    # --- combat ---
    "block_safety": 1.0,          # scales how much we value blocking
    "power_round_bonus": 6.0,     # flat bonus for powers in early rounds
    "kill_bonus": 12.0,           # bonus for securing a kill
    "free_card_bonus": 1.5,       # small bonus for 0-cost plays
    "play_threshold": 0.4,        # min score to bother playing a card
    # --- map ---
    "elite_min_hp_pct": 0.55,     # below this hp% elites are avoided
    "rest_urgent_hp_pct": 0.35,   # below this hp% rest sites are strongly preferred
    "shop_min_gold": 140,         # below this gold shops lose value
    "room_weights": {"Monster": 1.2, "Elite": 2.0, "RestSite": 1.0, "Shop": 1.1,
                     "Treasure": 1.4, "Unknown": 1.15, "Event": 1.1, "Boss": 10.0},
    "lookahead_weight": 0.35,     # 1-step lookahead contribution on map
    # --- rewards / shop ---
    "card_pick_threshold": 2.0,   # min value to take a reward card (skip otherwise)
    "rarity_bonus": {"Common": 0.0, "Uncommon": 0.8, "Rare": 1.6},
    "shop_relic_threshold": 1.0,  # min learned/heuristic relic value to buy
    "removal_enabled": True,
    "removal_gold_reserve": 60,   # keep this much gold after paying removal
    # --- rest ---
    "rest_heal_threshold": 0.6,   # heal if hp% below this, else smith
    # --- events ---
    "exploration_rate": 0.25,     # epsilon for trying unknown event options
    "exploration_decay": 0.97,    # per-run decay
    "exploration_min": 0.05,
    # --- potions ---
    "potion_hard_only": True,     # only spend potions in elite/boss or lethal danger
}

DEFAULT_PROGRESSION = {
    "character": "IRONCLAD",
    "current_ascension": 0,
    "max_ascension_goal": 10,
    "wins_by_ascension": {},
    "runs_by_ascension": {},
    "best_floor_by_ascension": {},
}

DEFAULT_STATS = {
    "version": 1,
    "global": {"runs": 0, "wins": 0, "floors_total": 0, "best_floor": 0,
               "deaths_by_enemy": {}, "deaths_by_event": {}},
    "cards": {},    # id -> {seen, picked, plays, outcome_sum, bias}
    "relics": {},   # id -> {picked, outcome_sum, bias}
    "enemies": {},  # comp_id -> {encounters, hp_lost_sum, deaths, wins}
    "events": {},   # id -> option_key -> {n, hp_delta_sum, gold_delta_sum, deaths}
    "rooms": {},    # node_type -> {visits, outcome_sum}
}


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            backup = path.with_suffix(path.suffix + f".broken-{int(time.time())}")
            try:
                path.replace(backup)
            except OSError:
                pass
    return json.loads(json.dumps(default))


def _save_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class Knowledge:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "runs").mkdir(exist_ok=True)
        self.stats = _load_json(root / "stats.json", DEFAULT_STATS)
        self.policy = _load_json(root / "policy.json", DEFAULT_POLICY)
        self.progression = _load_json(root / "progression.json", DEFAULT_PROGRESSION)
        # fill in any new default keys added in later versions
        for k, v in DEFAULT_POLICY.items():
            self.policy.setdefault(k, v)
        for k, v in DEFAULT_PROGRESSION.items():
            self.progression.setdefault(k, v)
        for k, v in DEFAULT_STATS["global"].items():
            self.stats["global"].setdefault(k, v)

    # ---------- persistence ----------

    def save(self) -> None:
        _save_json(self.root / "stats.json", self.stats)
        _save_json(self.root / "policy.json", self.policy)
        _save_json(self.root / "progression.json", self.progression)

    # ---------- value estimates (shrunk toward prior) ----------

    def global_avg_outcome(self) -> float:
        g = self.stats["global"]
        return g["floors_total"] / g["runs"] if g["runs"] else 10.0

    def card_value(self, card_id: str) -> float:
        e = self.stats["cards"].get(card_id)
        if not e or not e["picked"]:
            return e.get("bias", 0.0) if e else 0.0
        mean = e["outcome_sum"] / e["picked"]
        shrunk = (e["outcome_sum"] + SHRINK_K * self.global_avg_outcome()) / (e["picked"] + SHRINK_K)
        return (shrunk - self.global_avg_outcome()) + e.get("bias", 0.0)

    def relic_value(self, relic_id: str) -> float:
        e = self.stats["relics"].get(relic_id)
        if not e or not e["picked"]:
            return e.get("bias", 0.0) if e else 0.0
        shrunk = (e["outcome_sum"] + SHRINK_K * self.global_avg_outcome()) / (e["picked"] + SHRINK_K)
        return (shrunk - self.global_avg_outcome()) + e.get("bias", 0.0)

    def enemy_danger(self, comp_id: str) -> float:
        """Average hp lost per encounter with this enemy composition."""
        e = self.stats["enemies"].get(comp_id)
        if not e or not e["encounters"]:
            return 12.0  # unknown = moderately dangerous prior
        return e["hp_lost_sum"] / e["encounters"]

    def event_option_value(self, event_id: str, option_key: str) -> tuple[float, int]:
        """Return (score, sample_count). Score mixes hp/gold deltas and death penalty."""
        opts = self.stats["events"].get(event_id, {})
        e = opts.get(option_key)
        if not e or not e["n"]:
            return 0.0, 0
        hp_avg = e["hp_delta_sum"] / e["n"]
        gold_avg = e["gold_delta_sum"] / e["n"]
        death_rate = e["deaths"] / e["n"]
        return hp_avg * 1.0 + gold_avg * 0.02 - death_rate * 40.0, e["n"]

    # ---------- online commits ----------

    def commit_enemy_fight(self, comp_id: str, hp_lost: float, won: bool, died: bool) -> None:
        e = self.stats["enemies"].setdefault(comp_id, {"encounters": 0, "hp_lost_sum": 0.0, "deaths": 0, "wins": 0})
        e["encounters"] += 1
        e["hp_lost_sum"] += max(0.0, hp_lost)
        e["wins"] += 1 if won else 0
        e["deaths"] += 1 if died else 0

    def commit_event_option(self, event_id: str, option_key: str, hp_delta: float, gold_delta: float, died: bool) -> None:
        opts = self.stats["events"].setdefault(event_id, {})
        e = opts.setdefault(option_key, {"n": 0, "hp_delta_sum": 0.0, "gold_delta_sum": 0.0, "deaths": 0})
        e["n"] += 1
        e["hp_delta_sum"] += hp_delta
        e["gold_delta_sum"] += gold_delta
        e["deaths"] += 1 if died else 0

    def commit_card_seen(self, card_id: str) -> None:
        e = self.stats["cards"].setdefault(card_id, {"seen": 0, "picked": 0, "plays": 0, "outcome_sum": 0.0, "bias": 0.0})
        e["seen"] += 1

    def commit_card_play(self, card_id: str) -> None:
        e = self.stats["cards"].setdefault(card_id, {"seen": 0, "picked": 0, "plays": 0, "outcome_sum": 0.0, "bias": 0.0})
        e["plays"] += 1

    # ---------- run-end commits ----------

    def commit_run_end(self, outcome: float, victory: bool, picked_cards: list[str],
                       picked_relics: list[str], visited_rooms: list[str],
                       died_to_enemy: str | None, died_to_event: str | None) -> None:
        g = self.stats["global"]
        g["runs"] += 1
        g["wins"] += 1 if victory else 0
        g["floors_total"] += outcome
        g["best_floor"] = max(g["best_floor"], int(outcome))
        if died_to_enemy:
            d = g["deaths_by_enemy"]
            d[died_to_enemy] = d.get(died_to_enemy, 0) + 1
        if died_to_event:
            d = g["deaths_by_event"]
            d[died_to_event] = d.get(died_to_event, 0) + 1
        for cid in picked_cards:
            e = self.stats["cards"].setdefault(cid, {"seen": 0, "picked": 0, "plays": 0, "outcome_sum": 0.0, "bias": 0.0})
            e["picked"] += 1
            e["outcome_sum"] += outcome
        for rid in picked_relics:
            e = self.stats["relics"].setdefault(rid, {"picked": 0, "outcome_sum": 0.0, "bias": 0.0})
            e["picked"] += 1
            e["outcome_sum"] += outcome
        for room in visited_rooms:
            e = self.stats["rooms"].setdefault(room, {"visits": 0, "outcome_sum": 0.0})
            e["visits"] += 1
            e["outcome_sum"] += outcome

    # ---------- lessons ----------

    def append_lesson(self, text: str) -> None:
        path = self.root / "lessons.md"
        with path.open("a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")

    def save_run_log(self, run_id: str, log: dict) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)[:80] or "run"
        path = self.root / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.json"
        _save_json(path, log)
        return path
