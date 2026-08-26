"""Decision engine — one Decision per screen, driven by live state + learned knowledge.

Every decision carries:
  action   : the /action name to POST
  params   : option_index / card_index / target_index / command
  reason   : Chinese natural-language rationale (局势分析总结)
  tags     : credit-assignment markers, e.g. ("card_pick", card_id)
  ctx_ops  : side effects on RunContext (tracked in agent.py)
"""
from __future__ import annotations

import math
import random
import re
import time
from dataclasses import dataclass, field

from decision_trace import DecisionTraceBuilder, ensure_decision_trace
from knowledge import Knowledge, clamp
from window_layers import reassert_viewer_topmost

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
    trace: dict | None = None          # display-only; never feeds policy or learning


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


def _exhausts_other_cards(card: dict) -> bool:
    """这张牌是否会消耗掉别的牌（坚毅/燃烧契约型），而非仅在文本里提及
    「消耗牌堆」或只消耗自身。只有前者才参与消耗螺旋上限与递增罚分——
    第 135 局复盘：彼岸咆哮的「若在你的消耗牌堆中，则将其打出」被旧的
    纯文本匹配误计为消耗牌，打一张就占满小卡组的每场上限(=1)，坚毅此后
    整场被锁，致死回合唯一格挡牌遭禁玩而阵亡。"""
    text = _text(card)
    if not text:
        return False
    if re.search(r"随机消耗|消耗\s*\d+\s*张|消耗.{0,4}手牌", text):
        return True
    return bool(re.search(r"exhaust\s+(?:a|an|another|\d+)\s+(?:random\s+)?card", text, re.I))


class Policy:
    def __init__(self, know: Knowledge, rng: random.Random | None = None):
        self.know = know
        self.rng = rng or random.Random()
        self._end_stall = 0  # consecutive ticks with end_turn but no play_card available
        self._saw_playable_this_turn = False  # 本回合是否进入过可出牌状态（区分"还没就绪"与"真出完了"）
        self._shop_done_floor = -1  # floor of the shop we already finished evaluating
        self._reward_floor = -1     # reward screen identity tracking
        self._reward_instance_key = None  # exact live reward payload; repeated rewards may share text
        self._reward_tried: set = set()  # (index, reward_type, description) accepted on this payload
        self._reward_cooldowns: dict[tuple, int] = {}  # transient 409 rotation, never permanent
        self._reward_card_cooldowns: dict[tuple, int] = {}
        self._active_card_offer_key = None  # 当前可跳过卡牌 offer；跨 tick 去重 seen
        self._active_card_offer_explore_id = None  # 同一 offer 重试时保持探索选择稳定
        self._card_explore_run = None       # run identity for per-run novelty quota
        self._card_explore_used = 0         # deliberate non-greedy reward picks this run
        # 受控新颖度统一走“成功回执标签 → 下一 tick 入账”。决策尝试本身不占
        # 配额，409/断线不会把从未执行的探索伪装成样本。
        self._novelty_successes: set[tuple] = set()
        self._event_explore_used = 0
        self._relic_explore_used = 0
        self._potion_explore_used = 0
        self._sel_key = None        # card-selection screen identity
        self._sel_tried: set = set()  # card indices already clicked this screen
        self._sel_instance = None   # unique identity for accepted-click handshakes
        self._sel_serial = 0
        self._sel_mode = None       # semantic mode bound to the current selection instance
        self._handshake_credit_source = None
        self._handshake_credit_cursor = 0
        self._uncertain_action = None  # POST response lost; reconcile from next observed state
        self._timeline_epoch_pending = None  # (slot index, unchanged-state wait ticks)
        self._cur_turn = None       # combat turn tracking
        self._turn_combat = None    # combat identity paired with _cur_turn
        self._failed_this_turn: set = set()  # 本回合打出失败的卡牌实例（hand index，非 card_id）
        self._card_cooldowns: dict[tuple, int] = {}  # exact card slot/identity refresh races
        self._failed_hand_len = -1  # 记录失败时的手牌数量：index 是位置序号，手牌一变即失效
        self._potion_combat = None  # combat instance identity for potion blacklist
        self._potion_tried: set = set()      # (slot, potion identity) accepted this combat
        self._potion_cooldowns: dict[tuple, int] = {}
        self._potion_inventory_signature = None
        # Exact UI option cooldowns are deliberately short-lived.  They rotate a
        # sibling after repeated transient 409s / accepted-pending timeouts without
        # converting an animation race into a permanent "tried" fact.
        self._ui_action_cooldowns: dict[tuple, int] = {}
        self._ui_cooldown_scope = None
        self._novel_trial_combat = None  # combat identity for controlled first-play trials
        self._novel_trials: set[str] = set()  # card ids already trialled once this combat
        self._phase_stall = 0       # 转阶段过场（无有效目标）连续等待计数
        self._removal_pending_floor = -1  # 商店删牌握手：remove_card_at_shop 已发出，等待选牌界面
        self._kills_combat = None   # 战斗实例身份（重生召唤物检测用）
        self._combat_kills: dict = {}  # enemy_id -> 本场已预测击杀次数（≥2 判定重生体）
        self._respawn_reported: set = set()  # 本场已向跨局名册登记过的敌键（防重复计数）
        self._race_combat = None    # 战斗实例身份（败局竞速检测用）
        self._race_round = None     # 已采样的回合号
        self._race_prev_hp = None   # 回合边界观测血量
        self._race_loss_rate = 0.0  # 近期每回合净损血 EMA
        self._race_rounds = 0       # 完成的回合边界采样数
        self._desp_combat = None    # 战斗实例身份（假孤注观测确认用）
        self._desp_streak = 0       # 连续观测到"致死且无可负担格挡"的 tick 数
        self._stall_combat = None   # 战斗实例身份（僵局检测用）
        self._stall_min_hp = 99999  # 本场敌人总血量的历史最低值
        self._stall_no_progress = 0  # 连续无进展回合数
        self._stall_turn_seen = None
        self._exhaust_plays = 0     # 本场已打出"消耗其他牌"的牌数（防坚毅耗光攻击牌）
        self._unknown_stall = 0     # UNKNOWN 界面滞留计数（解锁/提示屏兜底点击用）
        self._unlock_stall = 0      # UNLOCK 已识别但 API 确认动作缺失时的独立鼠标兜底计数
        self._intent_prev = 0       # 上一回合边界采样的敌意图总伤（意图升级轨迹用）
        self._intent_trend = 0      # 本回合相对上一回合的意图增量（≥0，升级幅度）
        # 斩杀竞速投影（第 90~91 批复盘）：本场已打出的期望总伤 / 出牌回合数
        self._krace_combat = None   # 战斗实例身份
        self._krace_dmg = 0.0       # 本场已打出攻击卡的期望总伤累计
        self._krace_turns = 0       # 已发生过出牌的回合数（实测输出速率的分母）
        self._krace_round = None    # 上次计回合的回合号
        self._krace_latch = False   # 竞速迟滞锁（第632局批复盘）：实测口径判死后同场维持
        # 出牌策略账必须以服务端成功回执为准。Agent 会在成功后把 Decision.tags
        # 追加进同一个 credit_tags 列表；这里用列表身份+游标只消费新增项一次。
        self._combat_credit_source = None
        self._combat_credit_cursor = 0
        self._incoming_ema = 0.0    # 敌意图总伤 EMA（回合边界采样，竞速投影的可存活账）
        self._esc_rounds = 0        # 意图持续升级计数（第 92~93 批复盘）：趋势≥2 的回合边界数
        # 敌方血池/火力观测（第 138~141 批复盘）：本场学习样本，结算时经 agent 入库，
        # 供地图端 Boss 攻坚投影与 Boss 前夜篝火决策使用
        self._vit_pool_max = 0.0    # 本场观测到的敌方总血池最大值（非召唤杂兵 max_hp 合计）
        self._vit_fire_sum = 0.0    # 本场逐轮原始意图总伤累计（格挡前口径）
        self._vit_fire_rounds = 0   # 火力采样轮数
        self._vit_combat = None     # 战斗实例身份（观测采样隔离用，第 214 批补全写入侧）
        self._vit_round_seen = None # 上次火力采样的回合号
        # 同事件实例内重复选择记忆（第 214 批复盘）：滑脚木桥「再撑一会」连选 5 次，
        # 结算端 pending_event 被后选覆盖导致该选项永远 n=0——「全零并列选样本最少」
        # 规则于是每局反复选中它，单事件白掉 5 张牌。同实例内已选次数计入有效样本
        # 并附停滞罚分：选过却没离开事件的选项就是「没解决问题」的实证
        self._event_inst = None         # 当前事件实例身份 (run_id, event_id, floor)
        self._event_picks: dict = {}    # 本实例内各选项已成功选择次数
        # 进程级动作拉黑（第 218 批复盘）：签名级 TypeError（进程代码落后于
        # 磁盘）在本进程内永远失败，agent 熔断后把动作名记到这里，decide
        # 拦截被拉黑动作改发安全替代，不再每 tick 重试注定失败的调用
        self._broken_actions: set = set()

    def _enrich_cards(self, cards: list[dict]) -> list[dict]:
        """用版本化原生快照补齐 API 省略的静态字段，不覆盖实时状态。"""
        native = getattr(self.know, "game_knowledge", None)
        if native is None or not getattr(native, "available", False):
            return list(cards or [])
        return [native.enrich_card(card) for card in (cards or [])]

    @staticmethod
    def _reward_attempt_key(raw) -> tuple | None:
        if not isinstance(raw, (tuple, list)) or not raw or raw[0] != "reward_attempt":
            return None
        if len(raw) >= 4:
            try:
                index = int(raw[1])
            except (TypeError, ValueError):
                index = raw[1]
            return (index, str(raw[2] or ""), str(raw[3] or ""))
        if len(raw) >= 3:  # old in-memory tag compatibility
            return (None, str(raw[1] or ""), str(raw[2] or ""))
        return None

    @staticmethod
    def _potion_key(potion_or_tag) -> tuple | None:
        if isinstance(potion_or_tag, dict):
            return (potion_or_tag.get("index"),
                    str(potion_or_tag.get("potion_id") or potion_or_tag.get("name") or ""))
        raw = potion_or_tag
        if not isinstance(raw, (tuple, list)) or not raw or raw[0] != "potion_attempt":
            return None
        try:
            index = int(raw[1])
        except (TypeError, ValueError, IndexError):
            return None
        identity = str(raw[2] or "") if len(raw) >= 3 else ""
        return (index, identity)

    @staticmethod
    def _card_key(card: dict) -> tuple:
        identity = (card.get("instance_id") or card.get("uuid")
                    or card.get("card_id") or card.get("name") or "")
        return (card.get("index"), str(identity))

    def _card_unavailable(self, card: dict) -> bool:
        index = card.get("index")
        key = self._card_key(card)
        return (index in self._failed_this_turn or key in self._failed_this_turn
                or self._card_cooldowns.get(key, 0) > 0)

    @staticmethod
    def _tick_cooldown_map(values: dict) -> None:
        for key in list(values):
            left = int(values.get(key, 0)) - 1
            if left <= 0:
                values.pop(key, None)
            else:
                values[key] = left

    def _tick_action_cooldowns(self) -> None:
        for values in (self._card_cooldowns, self._reward_cooldowns,
                       self._reward_card_cooldowns, self._potion_cooldowns,
                       self._ui_action_cooldowns):
            self._tick_cooldown_map(values)

    @staticmethod
    def _freeze_ui(value):
        """Return a small hashable signature without readiness-only noise."""
        if isinstance(value, dict):
            return tuple((str(key), Policy._freeze_ui(item))
                         for key, item in sorted(value.items(), key=lambda row: str(row[0])))
        if isinstance(value, (list, tuple)):
            return tuple(Policy._freeze_ui(item) for item in value)
        if isinstance(value, set):
            return tuple(sorted((Policy._freeze_ui(item) for item in value), key=repr))
        return value

    @staticmethod
    def _ui_item_identity(item: dict | None) -> tuple | None:
        if not isinstance(item, dict):
            return None
        fields = (
            "index", "i", "instance_id", "uuid", "card_id", "relic_id",
            "potion_id", "option_id", "node_id", "node_type", "row", "col",
            "x", "y", "text_key", "title", "name", "description", "price",
        )
        return tuple((key, Policy._freeze_ui(item.get(key)))
                     for key in fields if key in item)

    @staticmethod
    def _ui_indexed_item(items, index):
        for item in items or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("index", item.get("i"))
            try:
                same = int(raw) == int(index)
            except (TypeError, ValueError):
                same = raw == index
            if same:
                return item
        return None

    @classmethod
    def _ui_screen_scope(cls, state: dict) -> tuple:
        """Identity of the current run/screen instance owning option cooldowns."""
        screen = str(state.get("screen") or "UNKNOWN")
        run = state.get("run") or {}
        run_id = state.get("run_id") or run.get("run_id")
        floor = run.get("floor")

        def item_set(items):
            return tuple(sorted((cls._ui_item_identity(item) for item in (items or [])
                                 if isinstance(item, dict)), key=repr))

        if screen == "EVENT":
            domain = state.get("event") or {}
            instance = (domain.get("event_id"), domain.get("page"), domain.get("step"),
                        item_set(domain.get("options")))
        elif screen == "MAP":
            domain = state.get("map") or {}
            instance = item_set(domain.get("available_nodes"))
        elif screen == "REST":
            domain = state.get("rest") or {}
            instance = item_set(domain.get("options"))
        elif screen == "SHOP":
            domain = state.get("shop") or {}
            # Buying a sibling legitimately mutates inventory while remaining on
            # the same shop screen; keep the old target cooling until expiry.
            instance = (bool(domain.get("is_open")), domain.get("shop_id"),
                        domain.get("title"))
        elif screen == "CARD_SELECTION":
            instance = cls._selection_identity(state)
        elif screen == "CHEST":
            domain = state.get("chest") or {}
            options = (domain.get("relic_options") if "relic_options" in domain
                       else domain.get("relics") if "relics" in domain
                       else domain.get("options"))
            instance = (bool(domain.get("is_opened")), item_set(options))
        else:
            instance = None
        return (str(run_id or ""), screen, floor, cls._freeze_ui(instance))

    def _sync_ui_cooldown_scope(self, state: dict) -> None:
        scope = self._ui_screen_scope(state)
        if self._ui_cooldown_scope is None:
            self._ui_cooldown_scope = scope
            return
        if scope != self._ui_cooldown_scope:
            self._ui_cooldown_scope = scope
            self._ui_action_cooldowns = {}

    @classmethod
    def _ui_target_item(cls, state: dict, action: str, params: dict):
        index = (params or {}).get("option_index")
        domain, collection = {
            "choose_event_option": ("event", "options"),
            "choose_map_node": ("map", "available_nodes"),
            "choose_rest_option": ("rest", "options"),
            "select_deck_card": ("selection", "cards"),
            "buy_card": ("shop", "cards"),
            "buy_relic": ("shop", "relics"),
            "buy_potion": ("shop", "potions"),
        }.get(action, (None, None))
        if domain is not None:
            return cls._ui_indexed_item(((state.get(domain) or {}).get(collection) or []),
                                        index)
        if action == "choose_treasure_relic":
            chest = state.get("chest") or {}
            for key in ("relic_options", "relics", "options"):
                if key in chest:
                    return cls._ui_indexed_item(chest.get(key) or [], index)
        if action == "remove_card_at_shop":
            return (state.get("shop") or {}).get("card_removal")
        if action == "confirm_selection":
            sel = state.get("selection") or {}
            return {"selected_count": sel.get("selected_count"),
                    "min_select": sel.get("min_select"),
                    "max_select": sel.get("max_select")}
        return None

    @classmethod
    def _ui_target_key(cls, state: dict, action: str, params: dict | None) -> tuple | None:
        rotating = {
            "choose_event_option", "choose_map_node", "choose_rest_option",
            "select_deck_card", "confirm_selection", "buy_card", "buy_relic",
            "buy_potion", "remove_card_at_shop", "choose_treasure_relic",
        }
        if action not in rotating:
            return None
        params = params or {}
        item = cls._ui_target_item(state, action, params)
        return (action, params.get("option_index"), cls._ui_item_identity(item))

    def _ui_action_cooled(self, state: dict, action: str,
                          params: dict | None = None) -> bool:
        key = self._ui_target_key(state, action, params)
        return key is not None and self._ui_action_cooldowns.get(key, 0) > 0

    def _ui_option_cooled(self, state: dict, action: str, option: dict) -> bool:
        return self._ui_action_cooled(
            state, action, {"option_index": option.get("index", option.get("i"))})

    @staticmethod
    def _cooldown_wait(label: str) -> Decision:
        return Decision(None, {}, f"{label}：全部可行候选处于短冷却，等待精确目标重试",
                        wait=0.6)

    def _sync_potion_inventory_identity(self, state: dict) -> None:
        """Release suppression when a slot is emptied/refilled with new contents."""
        potions = (state.get("run") or {}).get("potions") or []
        signature = tuple((p.get("index"), bool(p.get("occupied")),
                           p.get("potion_id"), p.get("name"))
                          for p in potions if isinstance(p, dict))
        if self._potion_inventory_signature is None:
            self._potion_inventory_signature = signature
            return
        if signature == self._potion_inventory_signature:
            return
        live = {self._potion_key(p) for p in potions
                if isinstance(p, dict) and p.get("occupied")}
        self._potion_tried.intersection_update(live)
        for key in list(self._potion_cooldowns):
            if key not in live:
                self._potion_cooldowns.pop(key, None)
        self._potion_inventory_signature = signature

    def _sync_novelty_successes(self, ctx) -> None:
        """Import accepted controlled trials from the agent's transactional tags."""
        counters = {
            "card": "_card_explore_used",
            "event": "_event_explore_used",
            "relic": "_relic_explore_used",
            "potion": "_potion_explore_used",
        }
        for raw in getattr(ctx, "credit_tags", None) or []:
            if not isinstance(raw, (tuple, list)) or len(raw) < 4 \
                    or raw[0] != "novelty_trial":
                continue
            token = tuple(raw[:4])
            if token in self._novelty_successes:
                continue
            self._novelty_successes.add(token)
            domain, key = str(raw[1]), str(raw[2])
            self.know.commit_novelty_trial(domain, key)
            attr = counters.get(domain)
            if attr:
                setattr(self, attr, int(getattr(self, attr, 0)) + 1)

    def _sync_combat_play_successes(self, ctx) -> None:
        """Apply accepted play-card policy effects exactly once on the next tick."""
        tags = getattr(ctx, "credit_tags", None)
        if not isinstance(tags, list):
            return
        if tags is not self._combat_credit_source:
            self._combat_credit_source = tags
            self._combat_credit_cursor = 0
        elif len(tags) < self._combat_credit_cursor:
            # Defensive support for a context that truncates/replaces its ledger.
            self._combat_credit_cursor = 0

        pending = tags[self._combat_credit_cursor:]
        self._combat_credit_cursor = len(tags)
        for raw in pending:
            if (not isinstance(raw, (tuple, list)) or len(raw) < 7
                    or raw[0] != "combat_play_commit"):
                continue
            cid = str(raw[1] or "").upper().rstrip("+")
            if bool(raw[2]) and cid:
                self._novel_trials.add(cid)
            if bool(raw[3]):
                self._exhaust_plays += 1
            try:
                estimated_damage = float(raw[4] or 0.0)
            except (TypeError, ValueError):
                estimated_damage = 0.0
            if estimated_damage > 0.0:
                self._krace_dmg += estimated_damage
            try:
                round_no = int(raw[5])
            except (TypeError, ValueError):
                round_no = None
            if round_no is not None and self._krace_round != round_no:
                self._krace_round = round_no
                self._krace_turns += 1
            kill_id = str(raw[6] or "")
            if kill_id:
                self._combat_kills[kill_id] = self._combat_kills.get(kill_id, 0) + 1

    def _sync_action_handshakes(self, ctx) -> None:
        """Import accepted UI-opening actions exactly once.

        UI actions which open a follow-up state, consume a one-shot resource, or
        affect same-screen retry policy must mutate local state only after an
        accepted HTTP response.  A disconnected/no-response request is ambiguous and
        must remain retryable from the next observed state.
        """
        tags = getattr(ctx, "credit_tags", None)
        if not isinstance(tags, list):
            return
        if tags is not self._handshake_credit_source:
            self._handshake_credit_source = tags
            self._handshake_credit_cursor = 0
        elif len(tags) < self._handshake_credit_cursor:
            self._handshake_credit_cursor = 0
        pending = tags[self._handshake_credit_cursor:]
        self._handshake_credit_cursor = len(tags)
        for raw in pending:
            if (isinstance(raw, (tuple, list)) and len(raw) >= 2
                    and raw[0] == "shop_remove_pending"):
                try:
                    self._removal_pending_floor = int(raw[1])
                except (TypeError, ValueError):
                    continue
            elif (isinstance(raw, (tuple, list)) and raw
                  and raw[0] == "reward_attempt"):
                key = self._reward_attempt_key(raw)
                if key is not None:
                    self._reward_tried.add(key)
            elif (isinstance(raw, (tuple, list)) and len(raw) >= 2
                  and raw[0] == "potion_attempt"):
                key = self._potion_key(raw)
                if key is not None:
                    self._potion_tried.add(key)
            elif (isinstance(raw, (tuple, list)) and len(raw) >= 3
                  and raw[0] == "event_choice"):
                key = str(raw[2] or "")
                if key:
                    self._event_picks[key] = self._event_picks.get(key, 0) + 1
            elif (isinstance(raw, (tuple, list)) and len(raw) >= 2
                  and raw[0] == "timeline_check"):
                ctx.check_timeline = bool(raw[1])
            elif (isinstance(raw, (tuple, list)) and len(raw) >= 2
                  and raw[0] == "timeline_epoch"):
                try:
                    self._timeline_epoch_pending = (int(raw[1]), 0)
                except (TypeError, ValueError):
                    continue
            elif (isinstance(raw, (tuple, list)) and raw
                  and raw[0] == "timeline_clear"):
                ctx.timeline_tried = set()
            elif (isinstance(raw, (tuple, list)) and len(raw) >= 2
                  and raw[0] == "shop_close"):
                try:
                    self._shop_done_floor = int(raw[1])
                except (TypeError, ValueError):
                    continue

    @staticmethod
    def _selection_identity(state: dict) -> tuple:
        sel = state.get("selection") or {}
        floor_no = (state.get("run") or {}).get("floor", 0)
        cards = tuple((c.get("index"), c.get("card_id"), c.get("instance_id"),
                       c.get("uuid"), bool(c.get("upgraded")))
                      for c in (sel.get("cards") or []))
        return (floor_no, (sel.get("kind") or "").lower(),
                sel.get("prompt") or "", sel.get("min_select"),
                sel.get("max_select"), cards)

    def note_action_uncertain(self, action: str, tags: list, state: dict,
                              params: dict | None = None) -> None:
        """Remember only UI intents whose lost POST response needs semantic repair.

        Reward, potion, and event decisions do not pre-mutate local state, so their
        next live payload is already sufficient.  Shop removal and card selection
        carry semantics not reliably present in the follow-up payload; timeline
        actions likewise need to preserve the post-run unlock workflow.
        """
        params = params or {}
        if action == "remove_card_at_shop":
            self._uncertain_action = {
                "kind": "shop_remove",
                "floor": (state.get("run") or {}).get("floor", 0),
            }
            return
        if action == "select_deck_card":
            sel = state.get("selection") or {}
            index = next((t[2] for t in (tags or [])
                          if isinstance(t, (tuple, list)) and len(t) >= 3
                          and t[0] == "selection_click"),
                         params.get("option_index"))
            self._uncertain_action = {
                "kind": "selection",
                "identity": self._selection_identity(state),
                "instance": self._sel_instance,
                "index": index,
                "selected_count": int(sel.get("selected_count", 0) or 0),
            }
            return
        timeline_kinds = {
            "return_to_main_menu": "timeline_return",
            "open_timeline": "timeline_open",
            "choose_timeline_epoch": "timeline_choose",
            "close_main_menu_submenu": "timeline_close",
        }
        kind = timeline_kinds.get(action)
        if kind:
            self._uncertain_action = {
                "kind": kind,
                "index": params.get("option_index"),
            }

    def _reconcile_uncertain_action(self, state: dict, ctx) -> None:
        """Resolve one response-lost UI action from the next fresh state payload."""
        pending = self._uncertain_action
        if not isinstance(pending, dict):
            return
        self._uncertain_action = None
        kind = pending.get("kind")
        screen = state.get("screen", "UNKNOWN")

        if kind == "shop_remove":
            # Same SHOP means the opener did not land and may be retried.  Only the
            # actual follow-up selection screen inherits removal semantics.
            if (screen == "CARD_SELECTION"
                    and (state.get("run") or {}).get("floor", 0) == pending.get("floor")):
                self._removal_pending_floor = int(pending.get("floor", 0))
            return

        if kind == "selection":
            if screen != "CARD_SELECTION" or self._selection_identity(state) != pending.get("identity"):
                return  # screen/card-list transition proves the click resolved
            selected_count = int(((state.get("selection") or {}).get("selected_count", 0)) or 0)
            if selected_count > int(pending.get("selected_count", 0)):
                try:
                    index = int(pending.get("index"))
                except (TypeError, ValueError):
                    return
                if self._sel_instance == pending.get("instance"):
                    self._sel_tried.add(index)
            # Unchanged screen/count means no evidence of execution: clear the
            # uncertainty and let the normal handler retry the same candidate.
            return

        timeline = state.get("timeline") or {}
        if kind == "timeline_return":
            if screen in ("MAIN_MENU", "TIMELINE"):
                ctx.check_timeline = True
        elif kind == "timeline_open":
            if screen == "TIMELINE" or timeline.get("can_choose_epoch"):
                ctx.check_timeline = False
        elif kind == "timeline_choose":
            index = pending.get("index")
            slot = next((s for s in timeline.get("slots", [])
                         if s.get("index") == index), None)
            changed = (screen not in ("MAIN_MENU", "TIMELINE")
                       or timeline.get("can_confirm_overlay")
                       or slot is None or (slot.get("state") or "") != "obtained")
            if changed and index is not None:
                ctx.timeline_tried.add(index)
        elif kind == "timeline_close":
            if screen == "MAIN_MENU" and not timeline.get("can_choose_epoch"):
                ctx.timeline_tried = set()

    def _timeline_transition_wait(self, state: dict, ctx) -> Decision | None:
        """Wait for an accepted epoch click to change the UI before closing it."""
        pending = self._timeline_epoch_pending
        if pending is None:
            return None
        index, waits = pending
        timeline = state.get("timeline") or {}
        slot = next((s for s in timeline.get("slots", []) if s.get("index") == index), None)
        landed = (timeline.get("can_confirm_overlay") or slot is None
                  or (slot.get("state") or "") != "obtained")
        if landed:
            ctx.timeline_tried.add(index)
            self._timeline_epoch_pending = None
            return None
        if waits >= 8:
            # An accepted/pending response is not the same as an observed unlock.
            # Release the wait and let the normal handler retry this still-obtained
            # slot; marking it tried here would silently skip fresh content forever.
            self._timeline_epoch_pending = None
            return None
        self._timeline_epoch_pending = (index, waits + 1)
        return Decision(None, {},
                        f"时间线：已提交槽位 {index}，等待解锁状态落地（{waits + 1}/8）",
                        wait=0.6)

    @staticmethod
    def _novelty_tag(domain: str, key: str, used: int) -> tuple:
        """Build a per-run ordinal tag; the agent appends it only after success."""
        return ("novelty_trial", domain, str(key), int(used) + 1)

    def mark_action_broken(self, action: str) -> None:
        """进程内永久拉黑一个动作名（签名不匹配等代码错位，重试必败）。"""
        self._broken_actions.add(action)

    def note_action_failed(self, action: str, tags: list) -> None:
        """agent 在执行失败时回调：本回合内不再尝试这张牌实例（防 409 重试刷屏）。

        按 hand index 记账而非 card_id：第 31 局 F7 终局一张防御 409（瞬时时序抖动）
        把同 id 的两张防御全部拉黑，剩 18 点意图无甲吃刀阵亡——
        惩罚必须精确到打失败的那一张，同 id 的其他副本不受连坐。

        生命周期（第 65~66 局复盘）：mod 的手牌 index 是位置序号，打出一张牌后
        剩余牌的 index 集体前移——黑名单一旦跨手牌变化仍生效，就会把"顶到被拉黑
        槽位上的无辜卡"整体禁玩（66 局 F5 双打击被误拉黑后 1 能量弃权白吃 15 意图；
        65 局致死回合手握打击同型阵亡）。_combat 端以"手牌数量未变"为黑名单有效期：
        手牌一变（有牌打出/被消耗）立即整体释放；真正的 409 防护不受影响——
        失败后下一 tick 手牌未变，该实例仍被精确拉黑。
        """
        if action == "play_card":
            card_id = next((str(t[1] or "") for t in (tags or [])
                            if isinstance(t, (tuple, list)) and len(t) >= 2
                            and t[0] == "play_card"), "")
            for t in tags or []:
                if t[0] == "play_card_index":
                    try:
                        index = int(t[1])
                        identity = str(t[2] or "") if len(t) >= 3 else card_id
                        self._failed_this_turn.add((index, identity))
                    except (TypeError, ValueError):
                        pass
        # Explicitly rejected reward/potion requests retain the historical
        # anti-loop behavior.  Their decision phase no longer pre-mutates these
        # sets, however, so ConnectionDown/no-response remains safely retryable.
        if action == "claim_reward":
            for t in tags or []:
                key = self._reward_attempt_key(t)
                if key is not None:
                    self._reward_tried.add(key)
        elif action == "use_potion":
            for t in tags or []:
                key = self._potion_key(t)
                if key is not None:
                    self._potion_tried.add(key)
        elif action == "choose_reward_card":
            # A definitive schema/parameter failure must not pin controlled
            # exploration to the same invalid option forever.
            for raw in tags or []:
                if (isinstance(raw, (tuple, list)) and len(raw) >= 3
                        and raw[0] == "reward_card_attempt"):
                    self._reward_card_cooldowns[(raw[1], str(raw[2] or ""))] = 5
            self._active_card_offer_explore_id = None

    def note_action_deferred(self, action: str, tags: list,
                             state: dict | None = None,
                             params: dict | None = None) -> None:
        """Temporarily rotate an exact target after repeated refresh-race 409s.

        Unlike ``note_action_failed`` this never writes permanent tried/failed
        state.  It gives sibling cards/rewards/potions a few decisions to proceed,
        then automatically retries the same live target if it still exists.
        """
        if action == "play_card":
            card_id = next((str(t[1] or "") for t in (tags or [])
                            if isinstance(t, (tuple, list)) and len(t) >= 2
                            and t[0] == "play_card"), "")
            for raw in tags or []:
                if (isinstance(raw, (tuple, list)) and len(raw) >= 2
                        and raw[0] == "play_card_index"):
                    try:
                        index = int(raw[1])
                    except (TypeError, ValueError):
                        continue
                    identity = str(raw[2] or "") if len(raw) >= 3 else card_id
                    self._card_cooldowns[(index, identity)] = 3
        elif action == "claim_reward":
            for raw in tags or []:
                key = self._reward_attempt_key(raw)
                if key is not None:
                    self._reward_cooldowns[key] = 3
        elif action == "use_potion":
            for raw in tags or []:
                key = self._potion_key(raw)
                if key is not None:
                    self._potion_cooldowns[key] = 3
        elif action == "choose_reward_card":
            for raw in tags or []:
                if (isinstance(raw, (tuple, list)) and len(raw) >= 3
                        and raw[0] == "reward_card_attempt"):
                    self._reward_card_cooldowns[(raw[1], str(raw[2] or ""))] = 3
            self._active_card_offer_explore_id = None
        if isinstance(state, dict):
            self._sync_ui_cooldown_scope(state)
            key = self._ui_target_key(state, action, params or {})
            if key is not None:
                self._ui_action_cooldowns[key] = 4

    # ------------------------------------------------------------------
    # top-level router
    # ------------------------------------------------------------------

    def _trace_gate(self, label, status: str, value="") -> None:
        builder = getattr(self, "_active_trace_builder", None)
        if builder is not None:
            try:
                builder.gate(label, status, value)
            except Exception:
                pass

    def _trace_candidate(self, label, score, *, index=None, action="",
                         status="eligible", why="", target=None) -> None:
        builder = getattr(self, "_active_trace_builder", None)
        if builder is not None:
            try:
                builder.candidate(label, score, index=index, action=action,
                                  status=status, why=why, target=target)
            except Exception:
                pass

    def _trace_note(self, value) -> None:
        builder = getattr(self, "_active_trace_builder", None)
        if builder is not None:
            try:
                builder.note(value)
            except Exception:
                pass

    def decide(self, state: dict, ctx) -> Decision:
        screen = state.get("screen", "UNKNOWN")
        run_key = (state.get("run_id") or (state.get("run") or {}).get("run_id")
                   or getattr(ctx, "run_id", None))
        if run_key and run_key != self._card_explore_run:
            self._card_explore_run = run_key
            self._card_explore_used = 0
            self._novelty_successes = set()
            self._event_explore_used = 0
            self._relic_explore_used = 0
            self._potion_explore_used = 0
            self._combat_credit_source = None
            self._combat_credit_cursor = 0
            # Floor numbers and screen payloads repeat in every run.  Leaving these
            # process-local handshakes alive across a run boundary can skip a shop or
            # reward merely because the previous run ended on the same floor.
            self._shop_done_floor = -1
            self._reward_floor = -1
            self._reward_instance_key = None
            self._reward_tried = set()
            self._reward_cooldowns = {}
            self._reward_card_cooldowns = {}
            self._active_card_offer_key = None
            self._active_card_offer_explore_id = None
            self._sel_key = None
            self._sel_tried = set()
            self._sel_instance = None
            self._sel_mode = None
            self._handshake_credit_source = None
            self._handshake_credit_cursor = 0
            self._removal_pending_floor = -1
            self._uncertain_action = None
            self._timeline_epoch_pending = None
            self._event_inst = None
            self._event_picks = {}
            self._unknown_stall = 0
            self._unlock_stall = 0
            self._phase_stall = 0
            self._turn_combat = None
            self._cur_turn = None
            self._end_stall = 0
            self._saw_playable_this_turn = False
            self._failed_this_turn = set()
            self._card_cooldowns = {}
            self._failed_hand_len = -1
            self._potion_cooldowns = {}
            self._potion_inventory_signature = None
            self._ui_action_cooldowns = {}
            self._ui_cooldown_scope = None
        # 正常主循环会先 _track 再 decide；这个边界闸门仍保护直接调用、恢复中间
        # 态及测试桩，避免 state/ctx 暂时跨局时重放旧 credit_tags、吃掉新局配额。
        ctx_run_key = getattr(ctx, "run_id", None)
        if not (run_key and ctx_run_key and str(run_key) != str(ctx_run_key)):
            self._sync_novelty_successes(ctx)
            self._sync_combat_play_successes(ctx)
            self._sync_action_handshakes(ctx)
            self._reconcile_uncertain_action(state, ctx)
        # 相同候选可能在后续同楼层再次真实出现；只要中间离开 offer 屏就释放
        # 当前 key。这样轮询不重复计数，而两个独立的同构 offer 仍各记一次。
        if not self._state_has_explicit_card_offer(state):
            self._active_card_offer_key = None
            self._active_card_offer_explore_id = None
        if screen != "CARD_SELECTION" and self._sel_instance is not None:
            self._sel_key = None
            self._sel_instance = None
            self._sel_tried = set()
            self._sel_mode = None
        if screen != "UNKNOWN":
            self._unknown_stall = 0
        if screen != "UNLOCK":
            self._unlock_stall = 0
        self._sync_potion_inventory_identity(state)
        self._sync_ui_cooldown_scope(state)
        self._tick_action_cooldowns()
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
            "CRYSTAL_SPHERE": self._crystal_sphere,
            "MODAL": self._modal,
            "GAME_OVER": self._game_over,
            "UNLOCK": self._unlock_screen,
            "TIMELINE": self._timeline,
            "BUNDLE_SELECTION": self._bundle,
            "CAPSTONE": self._capstone,
        }.get(screen)
        if handler is None:
            return ensure_decision_trace(state, self._unknown(state, ctx))
        trace_builder = DecisionTraceBuilder(state)
        self._active_trace_builder = trace_builder
        try:
            decision = handler(state, ctx)
            if decision.action == "choose_rest_option":
                decision = self._prepare_rest_decision(state, decision)
                rest_tag = next((tag[1] for tag in (decision.tags or [])
                                 if isinstance(tag, (tuple, list)) and len(tag) > 1
                                 and tag[0] == "rest"), "unknown")
                self._trace_gate(
                    "LOCK 篝火规则命中", "pass",
                    f"{rest_tag}｜{decision.reason}")
            self._decide_errors = 0
            if decision.action and decision.action in self._broken_actions:
                actions = state.get("available_actions", [])
                for safe in ("proceed", "end_turn", "confirm_modal", "collect_rewards_and_proceed",
                             "skip_reward_cards", "confirm_selection", "confirm_bundle",
                             "dismiss_modal", "open_chest", "close_shop_inventory"):
                    if safe in actions:
                        return ensure_decision_trace(
                            state, Decision(safe, {},
                                            f"动作 {decision.action} 本进程签名不匹配已拉黑，改用 {safe}", wait=1.0))
                return ensure_decision_trace(
                    state, Decision(None, {},
                                    f"动作 {decision.action} 本进程签名不匹配已拉黑，无安全替代，等待", wait=1.5))
            try:
                decision.trace = trace_builder.finish(decision)
            except Exception:
                # Display-only instrumentation must never alter the chosen action.
                decision.trace = None
            return ensure_decision_trace(state, decision)
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
                        return ensure_decision_trace(
                            state, Decision(safe, {}, f"决策连续异常×{self._decide_errors}，尝试 {safe} 自救（{exc}）", wait=1.0))
                for indexed in ("select_deck_card", "choose_reward_card", "choose_rest_option",
                                "choose_event_option", "choose_treasure_relic", "choose_bundle",
                                "claim_reward", "resolve_rewards", "choose_map_node"):
                    if indexed in actions:
                        return ensure_decision_trace(
                            state, Decision(indexed, {"option_index": 0},
                                            f"决策连续异常×{self._decide_errors}，盲选 {indexed}[0] 自救（{exc}）", wait=1.0))
            return ensure_decision_trace(
                state, Decision(action=None, reason=f"决策异常({screen}): {exc}", wait=1.0))
        finally:
            self._active_trace_builder = None

    # ------------------------------------------------------------------
    # menu / character select / timeline
    # ------------------------------------------------------------------

    def _main_menu(self, state: dict, ctx) -> Decision:
        actions = state.get("available_actions", [])
        timeline = state.get("timeline")
        transition_wait = self._timeline_transition_wait(state, ctx)
        if transition_wait is not None:
            return transition_wait
        if timeline and timeline.get("can_confirm_overlay") and "confirm_timeline_overlay" in actions:
            return Decision("confirm_timeline_overlay", {}, "主菜单：确认时间线弹层", wait=0.8)
        if timeline and timeline.get("can_choose_epoch"):
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
                if "choose_timeline_epoch" not in actions:
                    return Decision(None, {}, "主菜单：时间线解锁动作暂未就绪，等待", wait=0.7)
                return Decision("choose_timeline_epoch", {"option_index": s["index"]},
                                f"主菜单：解锁时间线新内容【{s.get('title')}】",
                                tags=[("timeline_epoch", s["index"])], wait=0.8)
            # 没有新内容 → 关闭时间线弹层，继续主流程
            if "close_main_menu_submenu" in actions:
                return Decision("close_main_menu_submenu", {},
                                "主菜单：时间线无新解锁，关闭弹层",
                                tags=[("timeline_clear",)], wait=0.8)
        if "continue_run" in actions:
            return Decision("continue_run", {}, "主菜单：检测到进行中的存档，继续对局", wait=1.2)
        # 一局结束后：时间线有新解锁项（obtained 未 complete）时优先去解锁
        if getattr(ctx, "check_timeline", False):
            if "open_timeline" in actions:
                return Decision("open_timeline", {},
                                "主菜单：检查时间线可解锁项（优先解锁新内容）",
                                tags=[("timeline_check", False)], wait=1.0)
            return Decision(None, {}, "主菜单：等待时间线入口就绪", wait=0.7)
        if "open_character_select" in actions:
            return Decision("open_character_select", {}, "主菜单：开启新的一局（标准模式）", wait=1.2)
        return Decision(None, {}, "主菜单：无可用动作，等待", wait=1.0)

    def _timeline(self, state: dict, ctx) -> Decision:
        actions = state.get("available_actions", [])
        timeline = state.get("timeline") or {}
        transition_wait = self._timeline_transition_wait(state, ctx)
        if transition_wait is not None:
            return transition_wait
        # 1) 解锁页/查看页弹层优先确认
        if timeline.get("can_confirm_overlay") and "confirm_timeline_overlay" in actions:
            return Decision("confirm_timeline_overlay", {}, "时间线：确认解锁页", wait=0.8)
        # 2) 有新获得（obtained 未 complete）且未点过的槽位 → 优先解锁
        tried = getattr(ctx, "timeline_tried", None)
        if tried is None:
            tried = ctx.timeline_tried = set()
        unlockable = [s for s in timeline.get("slots", [])
                      if (s.get("state") or "") == "obtained" and s.get("index") not in tried]
        if unlockable:
            s = unlockable[0]
            if "choose_timeline_epoch" not in actions:
                return Decision(None, {}, "时间线：解锁动作暂未就绪，等待", wait=0.7)
            return Decision("choose_timeline_epoch", {"option_index": s["index"]},
                            f"时间线：优先解锁新内容【{s.get('title')}】",
                            tags=[("timeline_epoch", s["index"])], wait=1.0)
        # 3) 没有可解锁项 → 关闭时间线回主菜单开新局
        if "close_main_menu_submenu" in actions:
            return Decision("close_main_menu_submenu", {},
                            "时间线：无可解锁项，返回主菜单",
                            tags=[("timeline_clear",)], wait=0.8)
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

    def _act_danger(self, nt: str, priors: dict, act_no: int,
                    act_mul: float, row_in_act: int | None = None) -> tuple[float, float, bool]:
        """路径投影掉血先验的分幕实证口径（第 148~160 批复盘接入）。

        第 79 批写好的 room_damage_prior_act 此前从未被任何调用方使用
        （死代码），rooms_act 分幕数据持续采集 80+ 局却零消费——投影一直在用
        跨幕混算先验 × 静态 path_act_scale。接入后：rooms_act 有本幕样本
        （≥3 场）时返回实证先验且幕数乘区归 1（实测场均已含幕间难度跃迁，
        再乘 act_mul 是双重计费）；样本不足时回落跨幕先验 × act_mul 旧口径。

        row_in_act 传入时进一步查分幕分层段实证（第 266 局批次复盘）：
        同幕怪物池随楼层递增，一幕全幕均值 ~10 把后段 VANTOM/KIN/
        CEREMONIAL（场均 41~43、生涯前三死因）摊薄成「便宜战」——266 局
        54% 血规划 F8 战斗时投影按 ~11 记账、下一战实际 -43。层段命中同样
        归 1 幕数乘区（实测已含段间难度跃迁）。Elite 路径闸门维持分幕口径
        不传行号：灰区悲观复核有自己的标定语义，叠加层段抬价会把精英彻底
        挤出地图（258~262 批观察点⑤的既定担忧）。
        返回 (先验, 生效幕数乘区, 是否命中分幕/分层段实证)。
        """
        prior, act_specific = self.know.room_damage_prior_act(
            nt, float(priors.get(nt, 8)), act_no, row_in_act=row_in_act)
        return prior, (1.0 if act_specific else act_mul), act_specific

    def _streak_loss_mult(self, pol: dict, nt: str, eff_streak: int) -> float:
        """连战战损疲劳递增（第 255 批复盘）：连续第 4 场战斗起，投影先验按
        1 + path_streak_loss_step ×(n-2) 逐场放大（封顶 path_streak_loss_cap）。

        权重端早有同语义的疲劳压制（×0.75 起步），但战损端仍按场均线性扣血——
        欲望被压低、代价没变贵，长链的生存账系统性乐观。实证三局同一形态：
        VS71 局 F2~F5 四连战（0/0/0/-47 后 F6 阵亡）、EHSL 局 F2~F5 四连战
        （F5 劫掠者三连 -72 阵亡）、7RJ9 局 F2~F5 连战（Unknown -55 后阵亡）
        ——链尾实际战损 47~72，而投影只按 Monster 先验 ~10/场线性记账。
        只作用于投影（真实战斗由 fatigue 权重与姿态系统接管），RestSite 等非
        战斗节点清零连战后自然回到 1.0。
        """
        if nt not in ("Monster", "Elite", "Unknown") or eff_streak < 3:
            return 1.0
        step = float(pol.get("path_streak_loss_step", 0.06))
        if step <= 0.0:
            return 1.0
        cap = float(pol.get("path_streak_loss_cap", 1.30))
        return min(cap, 1.0 + step * (eff_streak - 2))

    def _elite_path_gate(self, pol: dict, priors: dict, hp: int, max_hp: int,
                         good_cards: int, act_mul: float,
                         burst_starved: bool = False,
                         act_no: int | None = None,
                         deck_req: int | None = None) -> tuple[float, str]:
        """精英进场闸门：按实测战损投影"打完精英还剩多少血"，不达标整条候选路径重罚。

        第 36 局实证：71% 血进灰区精英单场 -44（77% 现血）+ 两瓶药水，连锁三个
        篝火回血、零锻造，Boss 战全盘崩盘。旧灰区 ×0.5 只罚首节点权重，
        压不住子树优势（精英后接篝火回血的路径组合分反而更高）——闸门必须乘在
        候选总分上：选精英等于承诺承担它的全部后果。

        卡组强度只按封顶折扣折抵精英战损（牌数≠质量，全价折抵曾让投影过度乐观；
        simulate() 内部模拟仍用全额折扣，闸门独立更保守，二者取严不冲突）。

        deck_req（第374~379批次复盘）：调用方可传入加码后的卡组门槛——前期
        （floor ≤ elite_early_floor_max）精英要求 elite_min_deck_cards +
        elite_early_deck_extra 张非基础牌。374~379 批 QZLQ 局 F7 精英在
        「血量与卡组达标」（≥90% 血 + 恰好 4 张非基础牌）的放行下被单场 -80
        整管抬走：开局卡组里 60% 还是基础打/防，4 张门槛形同虚设，而前期
        精英的重尾（本批两场 -75/-80）是即死风险，遗物收益根本兑付不了。
        中后期精英不受影响（136~137 批「饥饿卡组靠精英供血」教义保留）。
        """
        hpp = hp / max(1, max_hp)
        req_n = int(deck_req) if deck_req and int(deck_req) > 0 \
            else int(pol.get("elite_min_deck_cards", 4))
        if good_cards < req_n:
            return 0.1, (f"非基础牌仅{good_cards}张(<{req_n})，"
                         f"卡组强度不足规避精英")
        hard = float(pol["elite_min_hp_pct"])
        soft = float(pol.get("elite_soft_hp_pct", max(0.35, hard - 0.15)))
        if hpp < soft:
            return 0.1, f"血量{hpp:.0%}<{soft:.0%}，规避精英"
        # 健康进场实证先验（第 396 局批次复盘）：Elite 全量样本被低血被迫战
        # 垄断（选择性偏差），灰区悲观复核在旧先验下数学不可满足——规避→
        # 样本更坏→更规避自我强化。健康子账本成熟（≥3）时改答「像现在这样
        # 健康地进场会掉多少」，命中时幕数乘区归 1（分幕实测已含幕效应）；
        # 未命中回落旧口径，行为与旧版严格一致。留痕带来源便于复盘核对。
        src_note = ""
        if act_no is not None:
            _prior_h, _hit_h = self.know.elite_prior_healthy(
                act_no, float(priors.get("Elite", 28)))
            if _hit_h:
                prior, eff_mul = _prior_h, 1.0
                src_note = f"（健康进场实证先验{prior:.0f}）"
            else:
                prior, eff_mul, _ = self._act_danger("Elite", priors, act_no, act_mul)
        else:
            prior = self.know.room_damage_prior("Elite", float(priors.get("Elite", 28)))
            eff_mul = act_mul
        deck_relief = min(0.20, 0.02 * good_cards)
        proj = hpp - prior * eff_mul * (1.0 - deck_relief) / max(1, max_hp)
        req = float(pol.get("path_hp_floor_pct", 0.35)) + 0.10 / max(1.0, act_mul)
        if proj < req:
            return 0.1, (f"血量{hpp:.0%}进精英预计战后仅剩{max(0.0, proj):.0%}"
                         f"(需求≥{req:.0%})，规避精英{src_note}")
        veto_f, veto_note = self._elite_grey_veto(pol, prior, eff_mul, hpp,
                                                  good_cards, max_hp, burst_starved)
        if veto_f is not None:
            return veto_f, veto_note + src_note
        if hpp < hard:
            return 0.5, f"血量{hpp:.0%}处于精英灰区({soft:.0%}~{hard:.0%})，谨慎评估{src_note}"
        return 1.0, ""

    def _elite_grey_veto(self, pol: dict, prior: float, act_mul: float, hpp: float,
                         good_cards: int, max_hp: int,
                         burst_starved: bool = False) -> tuple[float | None, str]:
        """灰区精英悲观投影复核（第 86~87 批复盘新增；第 122 局复盘重定语义）。

        第 87 局实证：86% 血（灰区内）接受旧日雕像，实测战损 54（64% 血条），
        约为 Elite 实测场均（16~20）的 3 倍——灰区的 0.5 谨慎权重挡不住
        战损分布的重尾，灰区决策必须回答"坏了会怎样"。

        但旧复核的问法是「悲观情形是否仍舒适」（战后 ≥60%），第 122 局复盘
        证明该问法在实测数据下数学不可满足：Elite 生涯场均战损 19.2（混合
        先验 ≈20.3）、卡组折抵上限 20%、悲观系数 1.9，血池 72~88 时灰区放行
        所需入场血量 ≥95%~104%，全面越过 90% 硬线——灰区分支自 87 批落地起
        即为死代码，精英被事实硬门在 ≥90% 血：122 局仅 45 次到访（0.37/局），
        遗物断供（122 局全程唯一遗物 ANCHOR）→ 卡组输出速率不足 → Boss 磨死
        （KIN 双子/CEREMONIAL 两大一幕 Boss 死亡率 47%/40%）。

        复核问题改为「悲观情形是否仍能活命」：战后跌破生存线
        elite_grey_survival_floor（默认 40%，与 path_hp_floor_pct 同级的危险区
        概念）才整条候选路径规避精英；线上放行但保留 0.5 灰区谨慎权重。
        悲观情形活命 + 均值情形舒适（均值投影战后 ~57%~71%）+ 0.5 折权，
        三层保守叠加足以吸收 87 局式重尾，无需再让门槛不可达。
        硬线以上不受影响。返回 (None, "") 表示不处于灰区或复核通过。

        输出饥饿豁免（第 136~137 批复盘）：137 局 88% 血灰区精英被否决
        （悲观投影战后仅剩36%），同期满血进 Boss 照样整管打空——卡组弱到
        「跳过精英也必输 Boss」时，风险定价必须计入机会成本：精英是遗物/
        高质牌的唯一稳定供给，全部让给篝火等于选择慢性死亡（122 局诊断的
        遗物断供→输出不足→Boss 磨死因果链）。爆发吞吐量低于 deck_burst_floor
        时生存线下调 elite_grey_starve_relief；卡组成型后豁免自动消失，
        棘轮威慑对强卡组原样生效。
        """
        hard = float(pol["elite_min_hp_pct"])
        soft = float(pol.get("elite_soft_hp_pct", max(0.35, hard - 0.15)))
        if not (soft <= hpp < hard):
            return None, ""
        relief = min(0.20, 0.02 * good_cards)
        safety = float(pol.get("elite_grey_safety_mult", 1.5))
        proj = hpp - prior * act_mul * (1.0 - relief) * safety / max(1, max_hp)
        if "elite_grey_survival_floor" in pol:
            # 新语义：悲观情形活命线（第 122 局复盘）
            floor = float(pol["elite_grey_survival_floor"])
        else:
            # 旧库兼容：无新键时沿用旧舒适线语义
            floor = float(pol.get("elite_grey_proj_floor", 0.60))
        eff_floor, starve_note = floor, ""
        if burst_starved:
            rel = clamp(float(pol.get("elite_grey_starve_relief", 0.0)),
                        0.0, max(0.0, floor - 0.05))
            if rel > 0:
                eff_floor = floor - rel
                starve_note = f"，饥饿豁免至{eff_floor:.0%}"
        if proj >= eff_floor:
            return None, ""
        return 0.1, (f"血量{hpp:.0%}灰区精英预计战后仅剩{max(0.0, proj):.0%}"
                     f"(<{floor:.0%}{starve_note})，规避精英")

    def _map(self, state: dict, ctx) -> Decision:
        m = state.get("map") or {}
        live_nodes = m.get("available_nodes", [])
        nodes = [node for node in live_nodes
                 if not self._ui_option_cooled(state, "choose_map_node", node)]
        if live_nodes and not nodes:
            return self._cooldown_wait("地图")
        if not live_nodes:
            return Decision(None, {}, "地图：暂无可走节点", wait=0.8)
        run = state.get("run") or {}

        # 永久增益类 AnyTime 药水（如加最大生命）：拿到就用，不占战斗决策
        for p in run.get("potions", []):
            if p.get("occupied") and p.get("can_use") and (p.get("usage") or "").lower() == "anytime":
                potion_key = self._potion_key(p)
                if (potion_key in self._potion_tried
                        or self._potion_cooldowns.get(potion_key, 0) > 0):
                    continue
                desc = p.get("description") or ""
                if "最大生命" in desc or "MaxHp" in desc:
                    return Decision("use_potion", {"option_index": p["index"]},
                                    f"地图：使用永久增益药水【{p.get('name')}】",
                                    tags=[("use_potion", p.get("potion_id")),
                                          ("potion_attempt", p["index"],
                                           potion_key[1])], wait=0.7)
        hp = run.get("current_hp", 1)
        max_hp = max(1, run.get("max_hp", 1))
        hp_pct = hp / max_hp
        gold = run.get("gold", 0)
        floor = run.get("floor", 0)
        pol = self.know.policy
        weights = pol["room_weights"]
        priors = pol.get("path_danger_priors", {})
        heal_frac = pol.get("rest_heal_fraction", 0.30)
        # Boss 前夜锻造线合成口径（第 228 批复盘）：与 _rest 的 smith_line 同式，
        # 投影镜像不得与实际篝火行为脱钩（旧镜像读裸配置、_rest 读 max 合成，
        # 配置值低于证据上限时两者分叉）
        eve_smith_line = min(float(pol.get("boss_eve_smith_hp_pct", 0.85)),
                             float(pol.get("boss_entry_evidence_hp_cap", 0.65)))

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

        # 前期精英卡组门槛加码（第374~379批次复盘）：开局阶段（floor ≤
        # elite_early_floor_max）精英要求额外 elite_early_deck_extra 张非基础牌。
        # QZLQ 局 F7 精英以 4 张门槛压线放行后被 -80 整管抬走——开局卡组大半
        # 还是基础牌，4 张证明不了输出成型，而前期精英的重尾是即死风险。
        # 中后期自动回到基础门槛，饥饿供血教义不受影响
        elite_deck_req = int(pol.get("elite_min_deck_cards", 4))
        if floor <= int(pol.get("elite_early_floor_max", 8)):
            elite_deck_req += max(0, int(pol.get("elite_early_deck_extra", 3)))

        # 连续作战长度（第 84~85 批复盘）：自最近一个非战斗节点以来的连续
        # 战斗节点数。Monster 链行军的战损是复利结算的——84 局 F2~F9 七连战
        # （中途仅一次篝火）、第 RJG 局 F2~F8 七连战，两局均在链尾力竭阵亡。
        # 地图投影按场均先验线性扣血，捕捉不到这种递增疲劳
        combat_streak = 0
        # attribution_tags 是可恢复的路线事实；credit_tags 只是进程内握手流。
        # 新版本优先读前者，旧日志/测试上下文缺字段时再回落，避免双份标签重复计数。
        route_tags = getattr(ctx, "attribution_tags", None)
        if not route_tags:
            route_tags = getattr(ctx, "credit_tags", None) or []
        for tag in reversed(route_tags):
            if not tag or tag[0] != "map_node":
                continue
            if tag[1] in ("Monster", "Elite", "Unknown"):
                combat_streak += 1
            else:
                break

        # 绝境口径（第 126 局复盘）：真实血量低于急需线时，投影切换到悲观战损。
        # 均值账在重尾分布前系统性高估生存——126 局 F5 单场 -52 在账面上只值 ~7，
        # 随后 35% 血仍敢进战斗。绝境下的问题不是「平均掉几滴」而是「坏抽能不能活」
        rest_dire = hp_pct < float(pol.get("rest_urgent_hp_pct", 0.45))
        dire_loss_mult = float(pol.get("path_dire_loss_mult", 1.7)) if rest_dire else 1.0
        # 绝境篝火优先门（第 126 局复盘核心缺陷）：35% 血时 Monster(6,2)=22.09 压过
        # 眼前的 RestSite(6,1)=9.82，原因是战斗子树里藏着 2~3 个未来篝火的 +30%
        # 全额幻想回血账（投影宣称打完怪进 Boss 还有 94%），下一战 -28 直接阵亡。
        # 眼前有救命篝火时，非休整候选必须整体压制，除非它真的好到打折仍能胜出
        dire_rest_available = any(n.get("node_type") == "RestSite" for n in nodes)

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
                if good_cards < elite_deck_req:
                    return 0.1, (f"非基础牌仅{good_cards}张(<{elite_deck_req})，"
                                 f"卡组强度不足规避精英")
                hard = float(pol["elite_min_hp_pct"])
                soft = float(pol.get("elite_soft_hp_pct", max(0.35, hard - 0.15)))
                if hpp < soft:
                    return 0.1, f"血量{hpp:.0%}<{soft:.0%}，规避精英"
                if hpp < hard:
                    # 灰区不再一刀切：第 28 局 F12 以 78% 血与 0.80 硬线差 2% 而错过精英
                    # 但灰区必须通过悲观投影复核（第 87 局 86% 血进旧日雕像实测 -54）
                    prior_e, gate_mul, _ = self._act_danger(
                        "Elite", priors, act_no, act_mul)
                    veto_f, veto_note = self._elite_grey_veto(
                        pol, prior_e, gate_mul, hpp, good_cards, max_hp, burst_starved)
                    if veto_f is not None:
                        return veto_f, veto_note
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
                    # 血量警戒带内商店增值（第 94~95 批复盘）：药水/遗物是休息的
                    # 代偿资源——94 局二幕 F20 岔路 Shop(24.75) 以 0.53 分之差输给
                    # Monster(25.28)，随后无篝火六连战斗力竭阵亡；低血量时商店的
                    # 即时救命价值（防御/回复药水）应高于常规权重
                    if hpp < pol.get("rest_wary_hp_pct", 0.62):
                        return 1.6, f"金币{gold}足够；血量{hpp:.0%}偏低，药水遗物可代偿休整"
                    return 1.4, f"金币{gold}足够"
                # 药水档（第 248 批复盘）：140 硬线以下商店被整体 0.6 压死，而
                # 药水（约 50~100 金）正是爆毙通道「没挡住」的唯一稳定补给——
                # 236 批把交药时机提前后，供给端不能继续断供。237 局 120+ 金币
                # 死携从未进店即此形态。药水档分值压在休整权重（1.7/2.5）之下，
                # 不改变危险血量的篝火优先级
                if gold >= float(pol.get("shop_potion_gold", 60)):
                    if hpp < pol.get("rest_wary_hp_pct", 0.62):
                        return 1.3, f"金币{gold}够买药水；血量{hpp:.0%}偏低，药水可代偿休整"
                    return 1.0, f"金币{gold}够买药水档位"
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
        act_no = self._floor_act(floor)
        act_idx = min(len(acts) - 1, max(0, act_no - 1))
        act_mul = float(acts[act_idx]) if isinstance(acts[act_idx], (int, float)) else 1.0
        # 分幕序号与 agent 结算侧共用 _floor_act 边界；
        # rooms_act 的键后缀供分幕实证先验查询。

        # 输出饥饿判定（第 136~137 批复盘）：爆发吞吐量低于门槛的卡组处于
        # 「跳过精英也必输 Boss」状态，灰区精英复核据此豁免部分生存线。
        # 饥饿线对账化（第423~428批复盘，_starve_line）：有 learned Boss 基准
        # 时用竞速及格线——burst 高于静态带的卡组同样在输掉竞速（本批六局
        # 全数阵亡于必败预演），入场线/精英豁免必须对真实缺口开放
        run_deck = run.get("deck", [])
        # 缺口深度随饥饿标志一并留档（第495~498局批复盘）：投影端战损上浮
        # 与锻造预演需要「差多远」的连续量，不能只有布尔饥饿标志
        # 第547~552局批复盘：供给口径换 deck_effective_burst——力量引擎计入
        # 爆发授信，拾取端的进步才能真实反馈到缺口深度
        _burst_val = self.deck_effective_burst(run_deck)
        _line_val = self._starve_line(max_hp, act=act_no)
        burst_starved = bool(run_deck) and _burst_val < _line_val
        starve_deficit = clamp(1.0 - (_burst_val / _line_val if burst_starved else 1.0),
                               0.0, 1.0)
        _starve_loss_frac = float(pol.get("path_starve_loss_frac", 0.0))

        # Boss 前夜竞速必败预演（第 397~402 批复盘）：与 _rest 的竞速必败改锻造
        # 同口径，投影镜像不得与实际篝火行为脱钩（99~102/228/244 批教训）。
        # 判定不随路径变化，路径枚举前算一次
        eve_doomed, eve_doom_note = self._boss_race_doomed(
            run_deck, max_hp, floor=floor,
            potions=run.get("potions") or None)

        elite_gate_f, elite_gate_note = self._elite_path_gate(
            pol, priors, hp, max_hp, good_cards, act_mul, burst_starved,
            act_no=act_no, deck_req=elite_deck_req)

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

        # 卡组越强战斗越短：掉血先验按非基础牌数打折（每张 -3%，最多 -40%）
        deck_ease = 1.0 - min(0.40, 0.03 * good_cards)

        # 投影罚分软饱和（第 107~108 批复盘）：死亡/血量线/Boss入场/中段精英四类
        # 罚分累计后经 sat*tanh(raw/sat) 压扁。96 局去重治的是「同一坏结局记多次
        # 账」；本修复治「多候选同时吃满大额罚分」——108 局二幕开局全线 -159~-193，
        # 房间权重、休整加成等正信号在罚分竞赛中失声，评分退化为比拼「投影死得
        # 早晚」（先验误差 × 幕数乘区的复利噪声）。tanh 单调保序（死亡深度的梯度
        # 信息不丢），小罚分近似线性（既有门槛翻转语义不变），大额罚分渐进饱和。
        pen_sat = float(pol.get("path_penalty_saturation", 70.0))

        def squash_penalty(raw: float) -> float:
            if raw <= 0.0 or pen_sat <= 0.0:
                return raw
            return pen_sat * math.tanh(raw / pen_sat)

        # 中段精英罚分的深度衰减：逐节点选路下 depth 越深的精英越不是承诺
        # （中间岔口可改道），且篝火回血会抬高后续真实闸门的通过率——107 局
        # 29% 血时唯一篝火因子树深处藏精英被罚到 -84，压过 Monster(-0.94)
        # 放弃救命休息；近处精英（54 局商店下一层）衰减有限威慑仍在
        mid_decay = float(pol.get("elite_mid_gate_depth_decay", 0.85))

        def simulate(start_node, path_keys):
            score, cur_hp, notes = 0.0, float(hp), []
            raw_penalty = 0.0
            mid_gate_hit = False
            died_mid = False
            # 投影途中最低存活血量（近死带计价用，第 255~257 批次复盘）：
            # 只记节点结算后的存活状态；开局血量本身不入账（计价对象是
            # 「这条路把你带到多险」，不是「你现在多险」）
            min_surv_hpp = 1.0
            # 投影内连战计数沿路径递推（第 126 局复盘）：旧版把真实连战数当常量
            # 套在所有深度上——fresh 状态下投影 5 连战全程零疲劳，链越长相对越
            # 划算，「穿过未来营地的怪物链」幻想由此再添一层补贴。
            # 以真实连战数起步，遇战斗节点 +1、遇非战斗清零；depth 0 语义与旧版一致
            proj_streak = combat_streak
            for depth, key in enumerate(path_keys):
                gnode = graph.get(key) or {}
                nt = start_node.get("node_type", "Unknown") if depth == 0 else gnode.get("node_type", "Unknown")
                hpp = max(0.0, cur_hp) / max_hp
                # 中段精英复检闸门：外层闸门只查候选首节点，第 54 局 F12 商店路径
                # 的子树里藏着 F13 精英，47.5% 血被"金币足够"抬进精英漏斗。
                # 逐节点选路意味着中段精英尚未承诺（后续仍可改道），罚分取外层
                # 闸门的一半强度、加性实现（符号安全），并随深度衰减，仅作子树
                # 前景的投影修正
                if nt == "Elite" and depth >= 1:
                    gf, _gnote = self._elite_path_gate(pol, priors, int(round(cur_hp)), max_hp,
                                                        good_cards, act_mul, burst_starved,
                                                        act_no=act_no, deck_req=elite_deck_req)
                    if gf < 1.0:
                        raw_penalty += (1.0 - gf) * _ELITE_GATE_NEG_PENALTY * 0.5 * (mid_decay ** depth)
                        mid_gate_hit = True
                factor, note = node_factor(nt, gnode, hpp)
                if nt in ("Monster", "Elite", "Unknown"):
                    eff_streak, proj_streak = proj_streak, proj_streak + 1
                else:
                    eff_streak, proj_streak = 0, 0
                # 连战战损疲劳递增（第 255 批复盘）：权重端疲劳压制之外，
                # 投影的掉血账也要随连战深度变贵（欲望压低+代价抬价缺一不可）
                streak_loss_mult = self._streak_loss_mult(pol, nt, eff_streak)
                if nt == "Monster" and eff_streak >= 3:
                    # 疲劳随连战深度递增（第 92~93 批复盘）：固定 0.75 让 93 局
                    # 连续第 4~5 战仍以 0.37 分优势压过商店，最终满血差被打穿——
                    # 每多连一场，惩罚再加深一档（下限 0.45 防止彻底禁战斗）
                    fatigue_f = max(0.45, 0.75 - 0.06 * (eff_streak - 3))
                    factor *= fatigue_f
                    note = (note + "；" if note else "") + f"连续作战{eff_streak}场，疲劳压制×{fatigue_f:.2f}"
                elif streak_loss_mult > 1.0 and depth == 0 and note:
                    note += f"；连战战损递增×{streak_loss_mult:.2f}"
                w = weights.get(nt, 1.0) * learned_room_factor(nt) * factor
                score += w * (0.97 ** depth)
                if note and depth == 0:
                    notes.append(note)
                # 掉血先验：分幕实证优先（rooms_act 有本幕样本时幕数乘区归 1，
                # 实测场均已含幕效应）；无分幕样本回落静态/跨幕混合 × act_mul。
                # 行号传入后进一步细化到分幕分层段实证（第 266 局批次复盘）：
                # 同幕怪物池随楼层递增，全幕均值把后段杀手摊薄成便宜战
                prior, node_act_mul, node_act_specific = self._act_danger(
                    nt, priors, act_no, act_mul, row_in_act=key[0])
                # 尾部战损定价（第 258~262 批次复盘）：掉血先验是场均账，而单场
                # 实测尾部可达场均 3~5 倍——262 局 49% 血进 Monster 投影仅 ~9 点
                # （账面安全），实战 -39 阵亡；VS71 局 F5 单场 -47、8NRJ 局 F5
                # 单场 -30，全发生在 45%~75% 的「非绝境」带内（dire_loss_mult
                # 只管 <45%）。与事件层 hp_min（255~257 批）、近死带折价同构：
                # 血量跌破警戒带后，「坏一场能不能活」比「平均掉几滴」更接近
                # 生死——按距带顶的深度把先验线性拉向实测尾部（半价入账：尾部
                # 是极值不是常态，全价等于按最坏一场定价所有战斗），满血段
                # 零影响；只抬价不压价，方向单调安全。
                if nt in ("Monster", "Elite", "Unknown"):
                    _worst = self.know.room_damage_worst(nt, act_no, row_in_act=key[0])
                    if _worst is not None:
                        _band = float(pol.get("path_tail_hp_band_pct", 0.62))
                        _hpp_now = max(0.0, cur_hp) / max_hp
                        if 0.0 < _band and _hpp_now < _band:
                            _risk = (_band - _hpp_now) / _band
                            _tail = _worst * float(pol.get("path_tail_loss_frac", 0.5))
                            _p0 = prior
                            prior += max(0.0, _tail - _p0) * _risk
                            if depth == 0 and prior - _p0 >= 1.0:
                                notes.append(
                                    f"低血尾部定价：{nt}先验{_p0:.0f}→{prior:.0f}"
                                    f"（实测单场最差{_worst:.0f}）")
                # 单场尾部生存复核（第 266 局批次复盘）：尾部定价只抬「均价」，
                # 且随血带深度缩水——266 局 54% 血规划 Monster 时留痕
                # 「先验9→11（最差48）」，下一战实际 -43 阵亡：均价涨 2 点回答
                # 不了「坏一场能不能活」。这里用实测单场最差做生存复核（全价、
                # 不折半——问的是尾部本身），最坏打完跌破近死带即按缺口深度
                # 加性罚分；满血段天然零触发（最差 <90% 血条够不着近死线）。
                # Elite 不入此闸：灰区悲观复核（×safety）已覆盖同构风险，
                # 双闸叠加会把精英彻底挤出地图（258~262 批观察点⑤）。
                if nt in ("Monster", "Unknown") and float(
                        pol.get("path_tail_veto_penalty", 45.0)) > 0.0:
                    _vw = self.know.room_damage_worst(nt, act_no, row_in_act=key[0])
                    if _vw is not None:
                        _sf = max_hp * float(pol.get("path_graveyard_hp_pct", 0.10))
                        _tail_hp = cur_hp - _vw
                        if _tail_hp <= _sf:
                            _gap = clamp((_sf - _tail_hp) / max(_sf, 1.0), 0.0, 2.0)
                            raw_penalty += _gap * float(pol.get("path_tail_veto_penalty", 45.0))
                            if depth == 0:
                                notes.append(
                                    f"低血尾部生存复核：单场最差{_vw:.0f}打完仅剩"
                                    f"{max(0.0, _tail_hp):.0f}(≤{_sf:.0f})，尾部罚分")
                # 深度输出饥饿时，精英硬线以上也不能只看均值：第580局以90%血
                # 压线进旧日雕像，均值先验约7，实际单场掉满72血。只在深缺口、
                # 硬线以上且已有尾部证据时复用现有死亡/近死罚分，健康卡组不受影响。
                if (nt == "Elite" and burst_starved
                        and starve_deficit >= float(pol.get("elite_tail_veto_min_deficit", 0.50))
                        and hpp >= float(pol["elite_min_hp_pct"])):
                    _vw = self.know.room_damage_worst("Elite", act_no)
                    if _vw is not None:
                        _sf = max_hp * float(pol.get("path_graveyard_hp_pct", 0.10))
                        _tail_hp = cur_hp - _vw
                        if _tail_hp <= 0:
                            raw_penalty += max(
                                0.0, float(pol.get("path_death_penalty", 100.0))
                                - 3.0 * min(depth, 15))
                            if depth == 0:
                                notes.append(f"硬线精英尾部复核：单场最差{_vw:.0f}"
                                             f"≥当前血条{cur_hp:.0f}，按投影死亡计价")
                        elif (_tail_hp <= _sf
                              and float(pol.get("path_tail_veto_penalty", 45.0)) > 0.0):
                            _gap = clamp((_sf - _tail_hp) / max(_sf, 1.0), 0.0, 2.0)
                            raw_penalty += _gap * float(pol.get("path_tail_veto_penalty", 45.0))
                            if depth == 0:
                                notes.append(f"硬线精英尾部复核：单场最差{_vw:.0f}打完仅剩"
                                             f"{max(0.0, _tail_hp):.0f}(≤{_sf:.0f})，尾部罚分")
                # 输出饥饿战损上浮（第495~498局批复盘新增）：掉血先验是「历史
                # 平均卡组」的场均账，而战损与战斗时长正相关——爆发缺口大的
                # 卡组连最便宜的组合（496 局 F15 方柱构装体，生涯场均 6.6）
                # 也能拖成 -57 的消耗战。按缺口深度把战斗先验线性放大（上限
                # path_starve_loss_frac），让选路在健康带就看见饥饿的复利代价；
                # 绝境带（<45%）已有 dire_loss_mult 1.7 悲观口径，不叠加重复计费。
                # 卡组成型后上浮自动归零，方向单调安全
                if (nt in ("Monster", "Elite", "Unknown") and burst_starved
                        and dire_loss_mult == 1.0 and _starve_loss_frac > 0.0):
                    _sv_mult = 1.0 + _starve_loss_frac * starve_deficit
                    prior *= _sv_mult
                    if depth == 0 and starve_deficit >= 0.15:
                        notes.append(f"输出饥饿战损上浮×{_sv_mult:.2f}"
                                     f"（缺口{starve_deficit:.0%}）")
                # Boss 行节点是路径终点：投影语义为"进入该节点的血量"，
                # 不扣 Boss 自身战损（旧版把 45 点 Boss 先验也扣进去，
                # 导致第 28 局实际以 77% 血进 Boss 却被投影成 35%，严重误导决策与复盘）
                if boss_row is not None and key[0] >= boss_row:
                    continue
                cur_hp -= (prior * deck_ease * node_act_mul * streak_loss_mult
                           * (dire_loss_mult if nt in ("Monster", "Elite", "Unknown") else 1.0))
                if nt == "Unknown" and act_idx >= 1 and not node_act_specific:
                    # 二幕遭遇战加价仅旧口径追加；分幕实证已含该效应，不重复计费
                    cur_hp -= prior * deck_ease * node_act_mul * (pol.get("unknown_gauntlet_act2_mult", 1.6) - 1.0)
                if nt == "RestSite":
                    # 投影与行为一致（第 99~102 批复盘）：篝火并非总是回血——
                    # _rest 在血量 ≥ 锻造安全线时会改锻造（非 Boss 前夜），Boss 前夜
                    # 按三区裁决也可能锻造。旧投影无条件 +30%，系统性高估锻造路线的
                    # 进 Boss 血量：100 局 F12 篝火投影「预计 98%」，实际锻造后
                    # 以 82% 进场被 70 点战损处决——投影乐观反过来为锻造背书，
                    # 形成循环论证。这里按投影血量镜像 _rest 的核心规则
                    # （绝境回血/溢出改锻造属二阶修正，不入投影）
                    # 第 244 批复盘：Boss 前夜镜像同步三区生存余量裁决——
                    # 仅「有效回血<8%血条（溢出区）」或「不回血也稳过悲观战损且
                    # 血量 ≥ 锻造线（安全区）」时投影锻造，其余一律投影回血
                    hpp_now = max(0.0, cur_hp) / max_hp
                    boss_eve = boss_row is not None and key[0] == int(boss_row) - 1
                    if boss_eve:
                        _bl, _bn = self.know.boss_loss_stats()
                        _heal_amt = heal_frac * max_hp * float(pol.get("boss_eve_smith_heal_mult", 1.0))
                        _pess = _bl * float(pol.get("boss_eve_pess_mult", 1.5))
                        _margin = float(pol.get("boss_eve_safe_margin_frac", 0.10)) * max_hp
                        _eff = min(_heal_amt, max_hp - max(0.0, cur_hp))
                        # 竞速必败镜像（第 397~402 批复盘；第441~446批同步翻转带
                        # 优先；第664~674批复盘再加「弃疗锻造带」）：处决带内默认
                        # 投影回血（带内不回血在任何执行下都是处决），但判死且回血
                        # 后余量仍不过线时与 _rest 一致投影锻造——低血幕里悲观战损
                        # 超过最大生命，旧口径曾把整条血条都判进回血带、系统性
                        # 高估「囤血等死」路线的进 Boss 血量；带外必败仍投影锻造
                        _flip_heal = cur_hp - _pess <= _margin
                        # 第664~674批复盘镜像同步：判死且回血后余量仍不过线的
                        # 前夜篝火与 _rest「必败弃疗改锻造」同口径投影锻造，
                        # 选路不再把死局前夜的回血记成有效生存增量
                        _doom_smith_band = (eve_doomed and _flip_heal
                                            and max(0.0, cur_hp) + _eff - _pess <= _margin)
                        _smith_proj = (
                            (_bn >= int(pol.get("boss_eve_smith_min_samples", 3))
                             and _bl >= _heal_amt
                             and (_eff < 0.08 * max_hp
                                  or (cur_hp - _pess > _margin
                                      and hpp_now >= eve_smith_line)))
                            or (eve_doomed and (not _flip_heal or _doom_smith_band)))
                        will_heal = not _smith_proj
                    else:
                        will_heal = hpp_now < float(pol.get("smith_min_hp_pct", 0.55))
                    if will_heal:
                        # 绝境下的未来篝火是「幸存条件品」：能否走到它、走到时是否
                        # 还需要它都不确定（第 126 局复盘）。眼前的篝火全额记账，
                        # 沿途更深的篝火按深度折减——否则怪物子树里堆 2~3 个未来
                        # 篝火就能凭空捏出「打完怪进 Boss 还有 94%」的幻想账，
                        # 反超眼前的救命休息
                        gain = heal_frac * max_hp
                        if depth >= 1 and rest_dire:
                            gain *= float(pol.get("path_dire_heal_depth_decay", 0.85)) ** depth
                        cur_hp = min(float(max_hp), cur_hp + gain)
                if cur_hp > 0.0:
                    min_surv_hpp = min(min_surv_hpp, cur_hp / max_hp)
                if cur_hp <= 0:
                    # 死亡投影保留"撑得更久"的序信息：死得越晚罚得越轻。
                    # 第 43 局实证：低血量时所有候选都吃满 -100，候选间评分差被压成
                    # 噪声，能续命的篝火与当场暴毙的精英无法区分（还给了闸门反转可乘之机）
                    raw_penalty += max(0.0, pol.get("path_death_penalty", 100.0) - 3.0 * min(depth, 15))
                    died_mid = True
                    break
            final_pct = max(0.0, cur_hp) / max_hp
            if mid_gate_hit:
                notes.append("路径中段含未达标精英，投影罚分")
            # 罚分去重（第 96 局复盘）：死亡投影已是最重罚分，血量线/Boss入场线
            # 与死亡是同一坏结局的三次记账——96 局二幕全图被叠加罚到 -165~-195、
            # 「预计进Boss血量 0%」而实际一路零伤事件走到 70% 血，评分彻底失去
            # 分辨力。中途死亡只记一次；撑到 Boss 但血量不达标的候选反而应优于
            # 半路暴毙（存活深度信息由死亡罚分的 -3/深度梯度保留）。
            # 107~108 批追加软饱和：去重治「多次记账」，饱和治「多候选同时吃满
            # 大额罚分」——两类候选都触底后仍保留单调序与可辨识差异
            score -= squash_penalty(raw_penalty)
            # 段间清零（第 266 局批次复盘修正）：raw_penalty 是投影内累计账，
            # 第一段 squash 后不清零，行后段（近死带/血量地板/Boss入场）追加的
            # 罚分会连同行前段旧账在第二段被整体再扣一次——行前段罚分（中段
            # 精英/尾部复核）被双重记账，违反 96 局「同一坏结局只记一次账」的
            # 去重原则。两段各自饱和、互不携带
            raw_penalty = 0.0
            if died_mid:
                notes.append("投影中途死亡")
                return score, notes, final_pct
            # 近死带计价（第 255~257 批次复盘）：投影中途血量跌破近死带但没死透
            # 时旧账零罚分——257 局 64% 血进精英，投影明示「战后仅剩 3%」，该路径
            # 仍以 1.03 分压过「进 Boss 65%」的 Unknown(-1.63)，实战 -51 阵亡。
            # 3% 不是计划是运气：掉血先验是均值，尾部一刀就死，「走完还剩 3%」
            # 与「走完还剩 35%」在旧账里同价。按最深凹陷深度线性折价（与死亡
            # 罚分的「死得越晚越轻」同族：活得越险越贵），汇入第二段 squash
            # 与其他罚分一起饱和。与终点血量线（path_hp_floor_pct）语义不同：
            # 地板罚「到 Boss 时太残」，近死带罚「路上险些暴毙」——凹陷后被
            # 篝火抬回的路径终点体面、途中仍是用运气换来的
            grave_pct = float(pol.get("path_graveyard_hp_pct", 0.0))
            if grave_pct > 0.0 and min_surv_hpp < grave_pct:
                raw_penalty += ((grave_pct - min_surv_hpp)
                                * float(pol.get("path_graveyard_penalty", 150.0)))
                notes.append(f"投影途中近死{min_surv_hpp:.0%}(<{grave_pct:.0%})，幸存按运气计价")
            floor_pct = pol.get("path_hp_floor_pct", 0.35)
            if final_pct < floor_pct:
                raw_penalty += (floor_pct - final_pct) * 40.0
            # Boss 入场要求线（第 60~61 局复盘）：投影此前只作日志注释不进评分，
            # 「预计进 Boss 血量 44%」照样沿 Monster 链一路磨到 Boss 门前。
            # Boss 场均战损≈45（半个最大生命），低于要求线的入场是数学必死局——
            # 按差值重罚，让 F10+ 的篝火/商店续航路线能压过继续消耗的战斗路线
            need_pct = float(pol.get("boss_entry_min_hp_pct", 0.65))
            # 输出饥饿豁免（第 209 批复盘）：与灰区精英豁免
            # （elite_grey_starve_relief，136~137 批）同构。入场血量在 0.65~1.00
            # 带内已被 63/124/137/143/146/147/167/208 八局证伪为生死变量——208 局
            # 51% 进 KIN 双子，6 回合总伤 ~142 而击杀投影还需 8~15 回合，满血进场
            # 只多活 2~3 回合结局不变。饥饿卡组的瓶颈是卡组强度：为堆血放弃战斗/
            # 商店/宝箱只会让卡组更弱（安全螺旋）。饥饿时入场线按比例放宽，罚分
            # 仍作用于放宽后的线以下；绝境闸门（血量地板/死亡投影）不受影响
            need_eff = need_pct
            if burst_starved:
                _relief = clamp(float(pol.get("boss_entry_starve_relief", 0.0)), 0.0, 0.5)
                if _relief > 0.0:
                    need_eff = need_pct * (1.0 - _relief)
            _to_boss = (boss_row is not None and path_keys
                        and int(path_keys[-1][0]) >= int(boss_row))
            # 浮点边界容差（第 494 局批复盘）：投影终点恰好落在入场线上时
            # （本批 2RSHS 局 F9「预计进Boss血量 75%<75%」），final_pct 的
            # 表示误差会把它判成不达标吃续航罚分并留下自相矛盾的留痕——
            # 二值判定必须带 epsilon，比例罚分（血量地板）不受影响不动
            if _to_boss and eve_doomed:
                # 竞速必败豁免（第524局批复盘新增）：_boss_race_doomed 判死的
                # 对局里满血进场也追不上击杀曲线，入场血量已被多批实证为非生死
                # 变量（本批 75%~100% 进场全数整管打空）——续航罚分只会把选路
                # 推向「囤血等死」，与候选端的战力节点倾斜配套（见下方
                # race_doom_power_bonus）。留痕供复盘核对豁免触发率
                notes.append("竞速必败预演成立，Boss入场血量线豁免"
                             "（满血亦追不上击杀曲线，续航罚分不计）")
            elif _to_boss and final_pct < need_eff - 1e-9:
                raw_penalty += (need_eff - final_pct) * float(pol.get("boss_entry_penalty", 110.0))
                _relax = f"（饥饿放宽自{need_pct:.0%}）" if need_eff < need_pct - 1e-9 else ""
                notes.append(f"进Boss血量预计{final_pct:.0%}<{need_eff:.0%}{_relax}，优先续航路线")
            elif _to_boss and need_eff < need_pct - 1e-9 and final_pct < need_pct:
                # 豁免生效的可观测留痕（复盘核对点）：罚分被饥饿豁免免除
                notes.append(f"输出饥饿，Boss入场线放宽至{need_eff:.0%}"
                             f"（预计{final_pct:.0%}免于续航罚分）")
            if raw_penalty > 0.0:
                score -= squash_penalty(raw_penalty)
            return score, notes, final_pct

        cand = []
        for n in nodes:
            nt = n.get("node_type", "Unknown")
            best_ps, best_pnotes, best_pproj, best_ppath = -1e9, [], 0.0, []
            for pth in paths_from((n["row"], n["col"])):
                ps, pnotes, pproj = simulate(n, pth)
                if ps > best_ps:
                    best_ps, best_pnotes, best_pproj, best_ppath = ps, pnotes, pproj, pth
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
            if nt != "RestSite" and rest_dire and dire_rest_available:
                # 绝境篝火优先门（第 126 局复盘）：两层不对称压制——
                # ①首战生存复核：沿该候选的投影路径找到第一场战斗，按悲观战损
                #   （先验×幕数×绝境乘区×安全系数）复核「打完眼前这一战还剩多少」，
                #   跌破生存线即加性重罚。均值账说战斗便宜，但 25% 血时坏抽一刀就死
                #   ——这正是 126 局 F5 单场 -52 的教训；眼前的篝火不存在这个问题。
                # ②软压制：未触发①的非休整候选整体 ×gate（负分区间加性兜底，
                #   与精英闸门同模式，保证任何符号下只降分不升分）
                rgate = clamp(float(pol.get("dire_rest_gate_mult", 0.55)), 0.05, 1.0)
                first_loss = 0.0
                for pdepth, pkey in enumerate(best_ppath or []):
                    pg = graph.get(pkey) or {}
                    pnt = n.get("node_type", "Unknown") if pdepth == 0 \
                        else pg.get("node_type", "Unknown")
                    if pnt in ("Monster", "Elite", "Unknown"):
                        _fp, _fm, _ = self._act_danger(pnt, priors, act_no, act_mul,
                                                       row_in_act=pkey[0])
                        first_loss = _fp * deck_ease * _fm
                        break
                safety = float(pol.get("dire_first_fight_safety", 1.5))
                proj_hp = hp - first_loss * dire_loss_mult * safety
                floor_hp = max_hp * float(pol.get("dire_first_fight_floor", 0.05))
                if first_loss > 0.0 and proj_hp <= floor_hp:
                    best_ps -= float(pol.get("dire_first_fight_penalty", 45.0))
                    best_pnotes.append(
                        f"绝境{hp_pct:.0%}首战悲观仅剩{max(0.0, proj_hp):.0f}"
                        f"/{max_hp}(≤{floor_hp:.0f})，生存复核重罚")
                else:
                    gated = best_ps * rgate
                    if gated < best_ps:
                        best_ps = gated
                    else:
                        best_ps -= (1.0 - rgate) * _ELITE_GATE_NEG_PENALTY
                    best_pnotes.append(
                        f"绝境{hp_pct:.0%}遇休整候选，非休整路线压制×{rgate:.2f}")
            cand.append({"node": n, "nt": nt, "ps": best_ps, "notes": best_pnotes,
                         "proj": best_pproj, "path": best_ppath,
                         "doomed": any("投影中途死亡" in x for x in best_pnotes)})
        # 绝境资源节点偏好（403~406 批次复盘）：全部候选都投影中途死亡时，
        # 死亡罚分经软饱和后候选差只剩 <1 分的噪声级，评分退化为比拼死得早晚；
        # 此时金币/宝箱/事件换卡牌、删诅咒、买药水是唯一还能改变时间线的杠杆
        # （EQ04 局 F3：468 金商店以 0.61 分之差输给又一场白死的怪物战，
        # 五连战后 F6 阵亡）。仅在全候选死亡投影且存在纯价值节点时加成，
        # 健康局面零影响。
        # 存活价值节点反超扩展（第495~498局批复盘）：饱和账的另一面是「死亡
        # 罚分 ~70 打平甚至反超存活节点的续航罚分」——UNPSGREBQ2TU 局 F21
        # 商店路径投影存活（进Boss 53%）却以 8.62 分之差输给死亡投影的
        # Unknown，「全候选死亡」前提不成立、加成未触发，白死一场。当评分
        # 最高的候选是死亡投影而存在存活的纯价值节点时，同样对后者加成：
        # 「活着走到商店/宝箱」永远优于「沿死亡路线多活两格」
        _doom_bonus = float(pol.get("path_doomed_value_bonus", 8.0))
        if cand and _doom_bonus > 0.0:
            _value_nts = ("Shop", "Treasure", "Event")
            _all_doomed = all(c["doomed"] for c in cand)
            _has_value = any(c["nt"] in _value_nts for c in cand)
            if _all_doomed and _has_value:
                for c in cand:
                    if c["nt"] in _value_nts:
                        c["ps"] += _doom_bonus
                        c["notes"].append(
                            f"绝境全候选死亡投影，优先{c['nt']}换战力(+{_doom_bonus:.0f})")
            elif _has_value:
                _best_c = max(cand, key=lambda c: c["ps"])
                if _best_c["doomed"]:
                    for c in cand:
                        if c["nt"] in _value_nts and not c["doomed"]:
                            c["ps"] += _doom_bonus
                            c["notes"].append(
                                f"绝境最高分为死亡路线，存活{c['nt']}改判优先(+{_doom_bonus:.0f})")
        # 竞速必败的战力节点倾斜（第524局批复盘新增）：竞速预演判死时，剩余
        # 层数内唯一可能翻转时间线的是战力增量（金币/卡牌/遗物/事件收益），
        # 入场血量的边际价值归零——本批四局前夜竞速必败仍按「囤血」逻辑选路
        # （RestSite 链 + 续航罚分导向），最终以 75%~100% 血整管打空。对纯价值
        # 节点加成；触发条件与 path_doomed_value_bonus（投影死亡）独立，二者
        # 可叠加（判死 + 投影死亡的商店是双重杠杆）。精英不参与：灰区闸门仍是
        # 即死风险的守门人，不能被必败加成重新放行
        _race_bonus = float(pol.get("race_doom_power_bonus", 10.0))
        if eve_doomed and _race_bonus > 0.0:
            for c in cand:
                if c["nt"] in ("Shop", "Treasure", "Event"):
                    c["ps"] += _race_bonus
                    c["notes"].append(
                        f"竞速必败预演：优先{c['nt']}换战力(+{_race_bonus:.0f}，"
                        f"入场血量已非生死变量)")
        best_node, best_score, best_detail, best_notes, best_proj = None, -1e9, "", [], 0.0
        best_path = []
        details = []
        for c in cand:
            label = f"{c['nt']}({c['node']['row']},{c['node']['col']})"
            details.append(f"{label}={c['ps']:.2f}{'|' + '；'.join(c['notes']) if c['notes'] else ''}")
            self._trace_candidate(
                label, c["ps"], index=c["node"].get("index"),
                action="choose_map_node", why="；".join(c["notes"]),
                target={"row": c["node"].get("row"),
                        "col": c["node"].get("col"),
                        "projected_hp": c.get("proj")})
            if c["ps"] > best_score:
                best_node, best_score = c["node"], c["ps"]
                best_detail = label
                best_notes, best_proj = c["notes"], c["proj"]
                best_path = c["path"]

        note_txt = f"；{'；'.join(best_notes)}" if best_notes else ""
        # 留痕诚实化（第 90~91 批复盘）：91 局 F14 以 55% 血选了精英（闸门否决后
        # 1.37 分仍压过 -13/-18 的其余候选，实战只掉 13 血属正确取舍），但日志
        # 同时出现「Elite=1.37|规避精英」的自相矛盾留痕，污染复盘归因——
        # 被否决仍当选时必须写明「取损失最小项」，让复盘能区分误判与无奈
        if (best_node is not None and best_node.get("node_type") == "Elite"
                and elite_gate_f < 1.0 and elite_gate_note):
            best_notes = [x for x in best_notes if x != elite_gate_note]
            best_notes.append(elite_gate_note + "但其余候选评分更差，取损失最小项")
            note_txt = f"；{'；'.join(best_notes)}"
        # Boss 前夜篝火语义传递（第 48 局实证：72% 血在 Boss 前夜按常规线选了
        # 锻造，Boss 战 -58 正好打死；回血 +24 即可保命——_rest 据此优先回血）
        ctx.rest_before_boss = (best_node.get("node_type") == "RestSite"
                                and boss_row is not None
                                and int(best_node.get("row", -999)) == int(boss_row) - 1)
        # 绝境投影传递（第 96 局复盘）：把「沿选中路径打下去预计进 Boss 的血量」
        # 交给 _rest——投影绝望（<rest_dire_proj_pct）时篝火回血优先于锻造
        ctx.rest_proj_hp_pct = best_proj
        # 下一战预演传递（第 99~102 批复盘）：篝火若选了锻造，紧接着的第一场
        # 战斗要把血量打到什么位置？99 局 61% 血在强制精英前夜锻造，精英 -49
        # 正好处决（回血 +24 即可生还）；100 局 62% 血锻造后 82% 进 Boss 被
        # 70 点战损收走。沿选中路径找首个必经战斗节点（Monster/Elite），把它的
        # 期望战损（占血条比例）交给 _rest 做锻造前预演；无必经战斗则归零。
        # 连战累计预演（第 370~371 局复盘）：单战预演看不见「打完一场还有一场」
        # 的连环偿债——371 局 65% 血在双怪物前夜按单场期望（~13%）判定安全上砧，
        # 随后两连战 -32/-20 连环处决；当时回血 +24 即可全活。改为把沿路径的
        # 连续战斗节点逐场累加（至多 3 场：更远的战斗隔着恢复节点，不属于本次
        # 锻造的偿债窗口）；首个非战斗节点即截断——血量语境被它重置
        next_fight_loss = 0.0
        if best_node.get("node_type") == "RestSite":
            _preview_fights = 0
            for key in (best_path or [])[1:]:
                gnode = graph.get(key) or {}
                nnt = gnode.get("node_type", "Unknown")
                if boss_row is not None and key[0] >= int(boss_row):
                    break  # Boss 前夜的入场血量问题由 boss-eve 分支处理
                if nnt in ("Monster", "Elite"):
                    _np, _nm, _ = self._act_danger(nnt, priors, act_no, act_mul,
                                                   row_in_act=key[0])
                    # 与路径投影同一把尺（第495~498局批复盘）：饥饿卡组的预演
                    # 战损同样按缺口上浮，否则砧前预演系统性乐观、放行连环偿债
                    if (burst_starved and dire_loss_mult == 1.0
                            and _starve_loss_frac > 0.0):
                        _np *= 1.0 + _starve_loss_frac * starve_deficit
                    next_fight_loss += _np * deck_ease * _nm / max_hp
                    _preview_fights += 1
                    if _preview_fights >= 3:
                        break
                else:
                    break
        ctx.rest_next_fight_loss_frac = next_fight_loss
        self._trace_gate(
            "GATE 精英生存闸门", "pass" if elite_gate_f >= 1.0 else "warn",
            elite_gate_note or f"系数 {elite_gate_f:.2f}")
        self._trace_gate(
            "RANK 路径聚合评分", "pass",
            f"{len(cand)} 条候选；最高 {best_score:.2f}")
        self._trace_gate(
            "GATE Boss 入场投影", "warn" if best_proj < 0.45 else "pass",
            f"选中路径预计入场血量 {best_proj:.0%}")
        self._trace_note("地图评分由房间价值、路径危险先验和生存投影一次聚合完成。")
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
        # 应急按钮族施加 NO_BLOCK_POWER 后，卡牌格挡面在锁窗内无效。
        block_locked = any(
            "NO_BLOCK" in str(power.get("power_id") or power.get("id")
                              or power.get("power") or "").upper()
            or (power.get("name") or "") == "不可格挡"
            for power in (player.get("powers") or [])
            if isinstance(power, dict))
        enemies = [e for e in combat.get("enemies", []) if e.get("is_alive") and e.get("is_hittable")]
        hand = self._enrich_cards(combat.get("hand", []))
        energy = player.get("energy", 0)
        round_no = state.get("turn") or 1
        pol = self.know.policy
        actions = state.get("available_actions", [])
        can_play = "play_card" in actions
        can_end = "end_turn" in actions

        # Round numbers restart at one for every combat.  Pair them with the Agent's
        # stable combat object; otherwise a T1→T1 transition can inherit “already saw
        # playable cards” and end the new combat's still-loading opening hand early.
        if self._turn_combat is not ctx.combat or self._cur_turn != round_no:
            self._turn_combat = ctx.combat
            self._cur_turn = round_no
            self._failed_this_turn = set()
            self._failed_hand_len = -1
            self._saw_playable_this_turn = False
            self._end_stall = 0
        # 出牌黑名单只在"手牌数量未变"的连续 tick 间有效（第 65~66 局复盘）：
        # 手牌 index 是位置序号，打出一张牌后全体前移，旧 index 立即指向别的牌。
        # 手牌一变即释放全部黑名单；手牌未变的重试场景（409 抖动）仍精确拉黑。
        if len(hand) != self._failed_hand_len:
            self._failed_this_turn = set()
            self._card_cooldowns = {}
        self._failed_hand_len = len(hand)
        if self._potion_combat is not ctx.combat:
            self._potion_combat = ctx.combat
            self._potion_tried = set()
            self._potion_cooldowns = {}
        if self._novel_trial_combat is not ctx.combat:
            self._novel_trial_combat = ctx.combat
            self._novel_trials = set()
        if self._kills_combat is not ctx.combat:
            self._kills_combat = ctx.combat
            self._combat_kills = {}
            self._respawn_reported = set()
        # 战斗上下文缺失（None）或对象更替时重置采样：净损速率只在同一场战斗内
        # 有意义，绝不跨战斗累计（测试环境常以 None 复用身份，生产端恒为真实对象）
        if ctx.combat is None or self._race_combat is not ctx.combat:
            self._race_combat = ctx.combat
            self._race_round = None
            self._race_prev_hp = None
            self._race_loss_rate = 0.0
            self._race_rounds = 0
            self._intent_prev = 0
            self._intent_trend = 0
            self._krace_dmg = 0.0
            self._krace_turns = 0
            self._krace_round = None
            self._krace_latch = False
            self._incoming_ema = 0.0
            self._esc_rounds = 0
        # 假孤注确认窗同样按战斗实例隔离：上一场的计数绝不带入下一场
        if self._desp_combat is not ctx.combat:
            self._desp_combat = ctx.combat
            self._desp_streak = 0

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

        # ---- 战斗僵局检测与升级 ----
        # 实证（第 107 局）：坚毅(True Grit)每回合消耗随机牌，360+ 回合后攻击牌全部进消耗堆，
        # 敌人 INKLET 剩 1 血永远不死 → 无限死循环。机制：
        #   turn≥60 → 置标志请求 agent 启动 AI 死循环分析（一场一次）
        #   turn≥100 且 20 回合无掉血进展 → 判定死循环，摆烂送死结束本局
        #   turn≥120 或 AI 判 offense → 绕过评分阈值，有攻击牌就打
        # 第 109 局复盘加急：旧线(150/30)下无输出卡组的僵局要拖 3 小时+，
        # runner 被拖到异常退出（rc=4294967295）丢掉前 8 层决策日志——
        # 「无进展」计数只在敌人总血量下降时归零，正常磨血战不受收紧影响
        enemy_hp_total = sum(e.get("current_hp", 0) for e in enemies)
        if self._stall_combat is not ctx.combat:
            self._stall_combat = ctx.combat
            self._stall_min_hp = enemy_hp_total
            self._stall_no_progress = 0
            self._stall_turn_seen = round_no
            self._exhaust_plays = 0
        if self._stall_turn_seen != round_no:
            if enemy_hp_total < self._stall_min_hp:
                self._stall_min_hp = enemy_hp_total
                self._stall_no_progress = 0
            else:
                self._stall_no_progress += 1
            self._stall_turn_seen = round_no

        if round_no >= 60 and not getattr(ctx, "stall_analysis_asked", False):
            ctx.stall_analysis_asked = True
            ctx.stall_analysis_needed = True   # agent 主循环拾取并启动 AI 死循环分析

        giveup = (getattr(ctx, "force_giveup", False)
                  or (round_no >= 100 and self._stall_no_progress >= 20
                      and not getattr(ctx, "stall_grind_grace", False)))
        if giveup:
            ctx.stall_giveup = True   # 复盘归因标记：摆烂死不得喂给攻防旋钮（reflect 消费）
            if can_end:
                return Decision("end_turn", {},
                                f"战斗：僵局判定无伤害手段（回合{round_no}，{self._stall_no_progress}回合无进展），摆烂送死以终结本局",
                                tags=[("stall_giveup", round_no)], wait=0.8)
            return Decision(None, {}, "战斗：摆烂中（停止出牌）", wait=0.5)

        incoming = sum((it.get("total_damage") or 0) for e in enemies for it in e.get("intents", []))
        my_block = player.get("block", 0)
        my_hp = player.get("current_hp", 1)
        my_max_hp = max(1, player.get("max_hp", my_hp))
        block_gap = max(0, incoming - my_block)

        # 敌方血池/火力观测写入侧（第 214 批补全）：第 138~141 批铺好了 agent 合并
        # 与 knowledge 入库/读取端，但本写入侧在复盘回滚中丢失——全库 hp_pool_n=0、
        # fire_rounds=0，boss_vitals_worst 恒 (None,None)，「Boss 攻坚投影」成了
        # 无米之炊。血池只在见到本战斗实例的首个有效帧采样（召唤物尚未登场，天然
        # 贴合「非召唤杂兵」口径，多阶段战斗逐段各采、agent 端取最大段）；火力按
        # 回合边界采格挡前意图总伤。消费端（攻坚投影/篝火精算）留待后续复盘接线
        if isinstance(ctx.combat, dict):
            if self._vit_combat is not ctx.combat:
                self._vit_combat = ctx.combat
                self._vit_pool_max = 0.0
                self._vit_fire_sum = 0.0
                self._vit_fire_rounds = 0
                self._vit_round_seen = None
            if self._vit_pool_max <= 0.0:
                pool = sum(float(e.get("max_hp", 0) or 0) for e in combat.get("enemies", [])
                           if e.get("is_alive"))
                if pool > 0.0:
                    self._vit_pool_max = pool
            if self._vit_round_seen != round_no:
                self._vit_round_seen = round_no
                self._vit_fire_sum += float(incoming)
                self._vit_fire_rounds += 1
            ctx.combat["obs_hp_pool"] = self._vit_pool_max
            ctx.combat["obs_fire_sum"] = self._vit_fire_sum
            ctx.combat["obs_fire_rounds"] = self._vit_fire_rounds

        # 败局竞速采样：回合边界记录净损血 EMA。取上一回合结束时的血量与本回合
        # 开始时的差值——已包含我方全部防御决策的净效果，速率居高不下即代表
        # "边防边耗"的防守路线本身已经失效（61 局 Boss 战意图 19→21→23→25
        # 递增，每单回合都够不上 lethal，引擎持续半攻半防温水等死）
        if self._race_round != round_no:
            if self._race_round is not None and self._race_prev_hp is not None:
                loss = max(0.0, float(self._race_prev_hp - my_hp))
                self._race_loss_rate = (loss if self._race_rounds == 0
                                        else 0.7 * self._race_loss_rate + 0.3 * loss)
                self._race_rounds += 1
            # 意图升级轨迹采样（第 84~85 批复盘）：84 局毛绒伏地虫战意图
            # 4→7→24→18→9→25→31、85 局仪式兽 Boss 战 18→20→22→24→26——
            # 升级型敌人每拖一轮就更难挡，而旧引擎只看"本回合意图"，在升级
            # 前夜（低意图回合）照常倾泻输出，两局均在意图跳升后 2~3 回合内死亡。
            # 回合边界记录增量，供姿态层提前抬防御/紧急线
            if self._race_rounds >= 1:
                self._intent_trend = max(0, int(incoming) - int(self._intent_prev))
                # 持续升级计数（第 92~93 批复盘）：93 局 FUZZY+SHRINKER 战意图
                # 4→7→24→18→13→25→31 滚雪球——单看「本回合跳升」会把它当一次性
                # 事件防御前置，而滚雪球的正确读法是「每拖一轮都更贵」。
                # 趋势≥2 的边界累计出现 2 次即认定持续升级（供竞速投影开门）
                if self._intent_trend >= 2:
                    self._esc_rounds += 1
            else:
                self._intent_trend = 0
            # 意图 EMA（第 90~91 批复盘）：斩杀竞速投影的「可存活回合」分母——
            # 净损速率含我方格挡决策的净效果，开局头两回合用它会被格挡稀释，
            # 意图 EMA 才是敌人火力本身的账
            if self._race_rounds == 0:
                self._incoming_ema = float(incoming)
            else:
                self._incoming_ema = 0.7 * self._incoming_ema + 0.3 * float(incoming)
            self._intent_prev = int(incoming)
            self._race_round = round_no
        self._race_prev_hp = my_hp

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
                affordable_playable = False
                for card in hand:
                    if (not card.get("playable") or self._card_unavailable(card)):
                        continue
                    cost = energy if card.get("costs_x") else (card.get("energy_cost") or 0)
                    if cost <= energy:
                        affordable_playable = True
                        break
                # play_card can disappear briefly after animations/refreshes even
                # though the payload already exposes affordable cards.  This is not
                # “played everything”: the old two-tick confirmation discarded
                # full-energy Strike/Defend hands.  Give the endpoint a long recovery
                # window, then end only as a final anti-hang fallback for stale data.
                if affordable_playable:
                    if self._end_stall < 30:
                        return Decision(
                            None, {},
                            f"战斗：仍有可负担牌但 play_card 暂不可用，等待接口恢复"
                            f"（{self._end_stall}/30，{hand_desc}，能量{energy}）",
                            wait=0.6)
                    self._end_stall = 0
                    return Decision("end_turn", {},
                                    "战斗：可出牌接口长时间未恢复，结束回合防止永久卡死",
                                    wait=1.2)
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

        # 敌方组合历史战绩 → 战斗姿态与药水门槛的共同输入，必须先于药水分级读取：
        # 高危组合自动转防守（见 knowledge.enemy_stance；Boss 房间反转姿态：
        # 斩杀线不足时压攻击=拖长战斗多吃意图）。第 64 局实证：
        # FLYCONID+SNAPPING_JAXFRUIT 场均掉血 25.8（32% 血条）但死亡率仅 15%，
        # 姿态中性 + 药水被"非精英房不用"锁死，异鱼之油拖到 9 血才掏出来。
        cctx = getattr(ctx, "combat", None) or {}
        comp_id = cctx.get("comp_id") or None
        stance = self.know.enemy_stance(comp_id, cctx.get("node_type"), my_max_hp)
        comp_expected_loss = self.know.enemy_danger(comp_id) if comp_id else 0.0
        # 姿态方向决定文案（第 84~85 批复盘）：高危 Boss 姿态实为提速进攻，
        # 旧文案一律写"转防守节奏"，与真实 atk_mult>1 自相矛盾，污染复盘日志。
        # tone 记入独立变量：若后续斩杀竞速投影解除防御压制（93 局实证），
        # 文案必须同步改写——矛盾留痕等于投毒复盘
        stance_defensive_tone = False
        if stance.get("danger"):
            stance_defensive_tone = stance.get("atk_mult", 1.0) < 1.0
            tone = "提速斩杀" if not stance_defensive_tone else "转防守节奏"
            danger_note = f"；⚠{stance['danger']}，{tone}"
        else:
            danger_note = ""
        # 意图升级防御前置（第 84~85 批复盘）：升级型敌人意图跳升回合，
        # 格挡价值与紧急线同步上调——现在多挡一点，是为升级后的更难回合买血
        esc = int(getattr(self, "_intent_trend", 0) or 0)
        if esc > 0:
            stance["blk_mult"] = round(stance.get("blk_mult", 1.0) * (1.0 + min(0.24, 0.04 * esc)), 3)
            stance["urgent_hp_pct"] = round(min(0.65, stance.get("urgent_hp_pct", 0.45) + min(0.10, 0.02 * esc)), 3)
            danger_note += f"；意图升级+{esc}，防御前置"
        # Boss 攻坚提速（第 82~83 批复盘）：生涯死亡榜前四名中三个是 Boss
        # （同族双子 190+58 血 12 死、仪式兽 252 血 10 死、墨影幻灵 173 血 8 死），
        # Boss 意图逐轮升级、拖一轮就多吃一轮整套意图——第 82 局以 95% 血进
        # 一幕 Boss 仍被两阶段共 81 点战损处决。全体 Boss 战给攻击评分加全局
        # 乘区（与高危姿态叠加），缩短战斗本身就是最大的减伤。
        if cctx.get("node_type") == "Boss":
            boss_boost = float(pol.get("boss_atk_mult", 1.15))
            if boss_boost > 1.0:
                stance["atk_mult"] = round(stance.get("atk_mult", 1.0) * boss_boost, 3)
                danger_note += f"；Boss攻坚提速×{boss_boost:.2f}"

        # 药水使用门槛：精英/Boss、致死威胁、"低血量且有缺口"，以及
        # "敌方组合本身就是硬仗"（场均战损 ≥ potion_comp_loss_frac × 最大生命——
        # 对这类组合按普通战囤药水等于把救命资源带进坟墓）。
        # 第 30~32 局连续三局带着可用药水进坟墓（敏捷/缚魂全程未用）——
        # 启发式引擎等不到"完美时机"，低血量时增益/攻击药水必须立即兑现。
        # 低血线接 potion_block_hp_pct（第 236 局复盘）：block_safety 顶格后
        # 爆毙证据的接替旋钮——TNWN 局 40%~50% 血的硬仗干瞪眼、拖到 10/80
        # 才喝药；交药线随演化提前，放血判定与防御/回复分支共用同一条线
        _potion_line = float(pol.get("potion_block_hp_pct", 0.35))
        low_hp_bleeding = my_hp <= _potion_line * my_max_hp and block_gap > 0
        # premium：值得动用增益药水的场合（硬房/真致死/高危组合/意图滚雪球确认）。
        # 普通消耗战哪怕低血也留着——第 36 局 F15 把异鱼之油倒进净损 2 血的顺风波，
        # Boss 战空手阵亡。姿态联动（第 88 局复盘）：药水门槛（死亡率 0.30 / 战损
        # 0.30×血条）比姿态门槛（0.25 / 0.28×血条）更迟钝，头号杀手 FUZZY+SHRINKER
        # （29.3%/场均18.7<24）恰好从两条药水门槛的缝隙漏网——88 局 F8 姿态系统
        # 从第 1 回合就警告「⚠高危组合」，攻击药水却被锁到 20 血、格挡药水 33 血才
        # 掏出（意图已滚到 38）。同一份历史证据已经把姿态推入防守，药水门必须同步
        # 开启，否则「知道危险」和「动用储备」脱节。
        # 意图滚雪球确认（_esc_rounds≥2，第 255 批复盘补第四条缝）：低死亡率低战损
        # 的升级型组合（252 局 F5 劫掠者三连，8 战仅 1 死、场均 26.4 恰好压线）
        # 三条历史门槛全部漏网，能量药水睡到 19 血才掏——增益的价值随剩余战斗
        # 时长衰减，等血量跌破线再喝等于把复利窗口烧掉；持续升级确认即视为硬仗
        premium = bool(ctx.current_combat_is_hard or combat.get("end_turn_will_kill_player")
                       or block_gap >= my_hp
                       or comp_expected_loss >= float(pol.get("potion_comp_loss_frac", 0.30)) * my_max_hp
                       or bool(stance.get("danger"))
                       or getattr(self, "_esc_rounds", 0) >= 2)
        hard = (premium or low_hp_bleeding)
        potion_dec = self._maybe_potion(state, ctx, hard, premium)
        if potion_dec is not None:
            return potion_dec

        # 败局竞速（第 60~61 局复盘新增）：按近期净损速率外推，horizon 回合内
        # 必被打空血条时，被动防守已被证伪——解除能量预留并提速输出，
        # 唯一可能翻转时间线的动作是抢在死亡倒计时之前终止战斗
        race_allin = (
            self._race_rounds >= 1 and self._race_loss_rate >= 1.0
            and my_hp <= float(pol.get("hopeless_race_hp_frac", 0.6)) * my_max_hp
            and my_hp <= self._race_loss_rate * float(pol.get("hopeless_race_horizon", 2.0))
        )

        # 斩杀竞速投影（第 90~91 批复盘，88~89 批遗留核对项⑤落地）：
        # 91 局一幕 Boss 战实证——65 血入场、输出 ~25/回合、仪式兽 252 血，
        # 击杀需 ~9 回合而意图 18→24 每回合滚升，引擎却还在用挑衅(挡6)/武装
        # (挡5)这类奢侈格挡逐回合买命，最终差 ~30 伤输掉斩杀竞速。逐回合贪心
        # 看不见这场数学必败：以「本场实测输出速率 vs 意图火力」做攻速对账，
        # 击杀所需回合数超出可存活回合数 + 余量 → 判定防守路线已被证伪，
        # 奢侈格挡贬值、攻击提速，把每一分能量押进唯一的活路——提前终结战斗。
        # 头两回合不武装（输出速率样本不足，避免误判）；与 desperate/race_allin
        # 不重复放大（同一局面只提速一次）。
        kill_race = False
        if pol.get("kill_race_enabled", True):
            enemy_hp_total = 0
            for e in enemies:
                if self._is_respawn_add(e):
                    continue
                try:
                    enemy_hp_total += max(0, int(e.get("current_hp") or 0))
                except (TypeError, ValueError):
                    continue
            # 开账门槛（第 92~93 批复盘扩展）：大血池（≥80）之外，「意图持续升级」
            # 同样必须开账——93 局 FUZZY+SHRINKER 总血量不足 80，旧门永远不开，
            # 防守姿态压着攻击把 7 回合磨死在意图 31 的滚雪球下。升级型敌人
            # （毛绒伏地虫/仪式兽/墨影幻灵）的杀伤来自时间而非血量，血池小≠竞速豁免
            esc_gate = getattr(self, "_esc_rounds", 0) >= 2
            if enemy_hp_total >= float(pol.get("kill_race_min_enemy_hp", 80.0)) or esc_gate:
                # 开局先验开账（第 255 批复盘）：旧版要求实测满两回合才允许判定，
                # Boss 战的头 1~2 回合仍在按防守姿态花能量——意图升级复利下最贵的
                # 正是这两回合（252 局 F5 劫掠者三连：T1~T3 意图 22→32 还在打坚毅
                # 补防）。血池第 1 帧就可见、卡组爆发是现成 DPS 先验：实测样本不足
                # 两回合时用 deck_burst × kill_race_prior_eff 悲观折算开账；零爆发
                # 不预测（没有弹药的局面无从竞速），两回合后自动切回实测速率口径。
                # Boss 血池实证（stats hp_pool）：KIN 双子 ~307 / 仪式兽 ~252 /
                # VANTOM ~173，逐轮火力 ~13——防守线在数学上普遍不可行，早一回合
                # 竞速就是早一回合止损
                if self._krace_turns >= 2:
                    dpt = self._krace_dmg / max(1, self._krace_turns)
                    dpt_src = f"实测{dpt:.0f}伤/回合"
                else:
                    _prior_eff = float(pol.get("kill_race_prior_eff", 0.55))
                    _deck_now = ((state.get("run") or {}).get("deck")) or []
                    # 第547~552局批复盘：头两回合开账 DPS 换引擎有效口径，
                    # 带引擎卡组不再被面值账推向过早 all-in
                    dpt = self.deck_effective_burst(_deck_now) * _prior_eff
                    dpt_src = f"先验{dpt:.0f}伤/回合" if dpt > 0 else ""
                if dpt > 0:
                    loss_rate = self._race_loss_rate if (
                        self._race_rounds and self._race_loss_rate >= 1.0) else max(1.0, self._incoming_ema)
                    if esc_gate:
                        # 滚雪球修正：EMA 按权重滞后于下一轮真实火力（93 局 T5 EMA≈16
                        # 而当轮意图已 25），持续升级时存活分母至少取当前意图
                        loss_rate = max(loss_rate, float(incoming))
                    tsurv = my_hp / max(1.0, loss_rate)
                    ttk = enemy_hp_total / max(1.0, dpt)
                    _race_margin = float(pol.get("kill_race_margin", 1.5))
                    # 竞速迟滞锁（第632局批复盘新增）：投影逐 tick 重算时，
                    # 实测口径切换、EMA 滞后、小怪阵亡缩池都会让判定在阈值
                    # 附近反复翻案——632 局 F29（盛碗虫三连）七个回合内
                    # 「提速斩杀」与「转防守节奏」交替出现 5 次，攻防分配两头
                    # 摇摆，矛盾留痕还污染复盘。实测样本满两回合判死进入竞速
                    # 后即上锁，同场不再凭先验口径自我平反；唯一合法出口仍是
                    # 下方防守线联合复核判可行。
                    _kr_latched = bool(getattr(self, "_krace_latch", False)) \
                        and self._krace_turns >= 2
                    if _kr_latched:
                        race_lost = True
                    else:
                        race_lost = ttk > tsurv + _race_margin
                    # 防守线复核（第435~440批复盘）：旧投影的可存活回合数=裸血÷意图
                    # 火力——把格挡整项忽略，而格挡吞吐恰是防守路线可行性的第一变量。
                    # 后果是自证死期的预言闭环：投影判死 → 全攻提速 blk×0.7 →
                    # 不再买命 → 更早被打空 → 「验证」了投影。修复：进攻线判负后
                    # 补算防守路线的可行性。
                    # 能量双算修正（第460局批复盘）：旧复核按「满能量全攻算击杀、
                    # 满能量全挡算存活」两条线各自记账——同一回合的能量被花两次，
                    # 只要格挡吞吐摸到火力封顶线就判磨垒可行，与实际执行脱节。
                    # 改用 _race_joint_feasible：同一能量预算内遍历攻防分配与
                    # 轮换混合，任一分配同时满足击杀与存活才维持攻防节奏。
                    # 意图滚雪球局的豁免取消（第454局批复盘）保留：滚雪球局同样
                    # 复核，但不给 margin 余量（意图逐轮上涨吃不得余量）
                    if race_lost:
                        _cr_deck = ((state.get("run") or {}).get("deck")) or []
                        # 滚雪球局零余量过线；普通局维持原 margin 口径
                        _def_margin = 0.0 if esc_gate else _race_margin
                        _feas, _mix = self._race_joint_feasible(
                            _cr_deck, enemy_hp_total, loss_rate, my_hp,
                            _def_margin)
                        if _feas:
                            race_lost = False
                            self._krace_latch = False
                            _esc_mark = "（滚雪球零余量）" if esc_gate else ""
                            danger_note += (f"；防守线复核：联合能量对账，{_mix}即可在"
                                            f"净火力下追平击杀所需{ttk:.0f}回合，"
                                            f"维持攻防节奏不全攻{_esc_mark}")
                    if race_lost:
                        kill_race = True
                        danger_note += (f"；斩杀竞速投影：击杀还需{ttk:.0f}回合>"
                                        f"可存活{tsurv:.0f}回合（{dpt_src}），全攻提速")
                        if self._krace_turns >= 2:
                            # 实测口径武装入锁（先验口径 T1~T2 不锁：样本不足的
                            # 误判可被下一 tick 自然纠正）
                            self._krace_latch = True
        if kill_race:
            # 高危姿态与竞速路线互斥（第 92~93 批复盘）：防守已被投影证伪时，
            # 压攻击=拖长战斗多吃意图、抬格挡=给买不到胜利的延寿加价。
            # 攻击压制解除、格挡增益封顶，能量全部让位输出
            if float(stance.get("atk_mult", 1.0)) < 1.0:
                stance["atk_mult"] = 1.0
                if stance_defensive_tone:
                    danger_note = danger_note.replace("转防守节奏", "提速斩杀（竞速解除防御压制）")
            if float(stance.get("blk_mult", 1.0)) > 1.0:
                stance["blk_mult"] = 1.0

        # 全场皆为已证实重生体时解除重生压制（第 152 局 F6 实证）：墨宝 1 血
        # 不死阶段被重生标记三重压制（eff 封顶 1、威胁清零、击杀奖励归零），
        # 打击评分 1.0+负 learned value 跌破出牌阈值——58 个 tick 满手攻击空过，
        # 65 回合 5 分钟白掉 54 血，直到僵局强攻（turn≥60）一刀终结。
        # 重生压制的初衷（52~53/58 局利齿之眼）是「杀召唤物无意义、应转火本体」，
        # 前提是场上还有本体可打；当存活敌人全是重生体时，压制让「不打」成为
        # 唯一选择——拒绝出牌永远是比「打重生体」更差的答案，必须放开。
        all_respawn = all(self._is_respawn_add(e) for e in enemies)
        if all_respawn:
            danger_note += "；全场均为已证实重生体，解除重生压制以终结战斗"

        best = None  # (policy_score, card, target_index, why)
        # If the policy threshold suppresses every option, a separately-accounted
        # positive immediate margin may still spend otherwise-wasted energy.  The
        # fifth tuple field records whether this is a normal fallback or a single
        # controlled first-play trial.
        marginal_best = None  # (immediate_score, card, target_index, why, mode)
        # 服务端致死判定：意图数值可能被敌方增益/减益污染，本地算术会漏判——
        # 只要服务端说"结束回合会死"且缺口未补满，就按致死回合处理（第 31 局 F7 终局教训）
        forced_kill = bool(combat.get("end_turn_will_kill_player"))
        # 能量预留采用一层联合机会判断，而不是“看见任意格挡就压攻击”：
        # 先估算每张可负担格挡对当前缺口的即时边际，只有它本身值得出
        # （超过出牌阈值）才保留相应能量。旧逻辑在 6 意图/5 甲时仍为第二张
        # 防御预留能量：防御因只多挡 1 点被溢出规则压到 0.03，打击又被固定
        # -8，二者互相压死后带着能量结束回合。现在低边际防御不再制造预留。
        gap_now = max(0, incoming - my_block)
        reserve_lethal = (gap_now >= my_hp
                          or (gap_now > 0 and (my_hp - gap_now) <= 0.12 * my_max_hp)
                          or (forced_kill and gap_now > 0))
        reserve_urgent = (gap_now > 0 and my_hp / max(1, my_max_hp)
                          < float(stance.get("urgent_hp_pct", 0.45)))
        reserve_blk_boost = 1.8 if reserve_lethal else (1.4 if reserve_urgent else 1.0)
        reserve_blk_boost *= float(stance.get("blk_mult", 1.0))
        reserve_blk_boost *= 1.0 + min(0.24, 0.08 * max(0, len(enemies) - 1))
        worthwhile_blk_costs = []
        for c in hand:
            cost = energy if c.get("costs_x") else (c.get("energy_cost") or 0)
            _dmg, block, _hits = card_numbers(c)
            if (not c.get("playable") or self._card_unavailable(c)
                    or block <= 0 or cost > energy):
                continue
            useful = min(block, gap_now)
            if useful < block * 0.5 and not reserve_lethal and not reserve_urgent:
                marginal = useful * float(pol.get("block_excess_value", 0.03))
            else:
                marginal = (useful * 1.05 * pol["block_safety"]
                            + (block - useful) * float(pol.get("block_excess_value", 0.03)))
                marginal *= reserve_blk_boost
            if marginal > float(pol["play_threshold"]):
                worthwhile_blk_costs.append(cost)
        reserve_for_block = gap_now > 0 and bool(worthwhile_blk_costs)
        min_blk_cost = min(worthwhile_blk_costs) if worthwhile_blk_costs else 99
        # 消耗螺旋治理（第 109 局复盘）：坚毅(True Grit)每打一次随机消耗一张手牌，
        # INKLET 三连波里 66 次坚毅把打击/痛击/上勾拳/熔融之拳全部烧光 → 完美
        # 无限僵局（600+ 回合格挡≥意图、零输出），runner 拖到崩溃。固定上限 4
        # （107 局引入）在多波房间会放大成 12+ 张消耗，且不随卡组厚度缩放。
        # 现在：上限按卡组规模折算（小卡组烧不起），评分端再叠加逐次递增罚分。
        # 第 135 局复盘修正两点：
        #   ① 计数对象改为「消耗其他牌」的牌（见 _exhausts_other_cards）——
        #      彼岸咆哮这类仅提及消耗牌堆的牌不再占位锁死坚毅；
        #   ② 致死回合（本地算术/惨胜线/服务端判定）豁免上限——烧一张牌换
        #      当场活命永远值得，僵局防护只针对非致死的温水回合。
        deck_n = len(((state.get("run") or {}).get("deck")) or [])
        max_exhaust_plays = max(1, min(4, deck_n // 8))
        exhaust_penalty_step = float(pol.get("exhaust_play_penalty", 3.0))
        exhaust_unclog_bonus = float(pol.get("exhaust_unclog_bonus", 2.0))
        gap_pre = max(0, incoming - my_block)
        lethal_now = (gap_pre >= my_hp
                      or (gap_pre > 0 and (my_hp - gap_pre) <= 0.12 * my_max_hp)
                      or (forced_kill and gap_pre > 0))
        self._trace_gate(
            "GATE 致死检查", "warn" if lethal_now else "pass",
            f"伤害缺口 {gap_pre} / 当前生命 {my_hp}"
            + ("；服务端判定结束回合致死" if forced_kill else ""))
        self._trace_gate(
            "GATE 防御能量预留", "active" if reserve_for_block else "pass",
            f"预留={reserve_for_block}；最低有效格挡费用 {min_blk_cost if reserve_for_block else 0}")
        self._trace_gate(
            "GATE 斩杀竞速", "warn" if (race_allin or kill_race) else "pass",
            f"败局竞速={race_allin}；斩杀竞速={kill_race}")
        self._trace_gate(
            "RANK 出牌阈值", "neutral", f"> {float(pol['play_threshold']):.2f}")
        for c in hand:
            if not c.get("playable"):
                continue
            if self._card_unavailable(c):
                continue
            # 消耗类牌每场上限：防"坚毅每回合消耗随机牌→攻击牌耗尽→死循环"
            #（第 107 局实证，上限随卡组规模折算见第 109 局复盘）
            if (_exhausts_other_cards(c) and not lethal_now
                    and self._exhaust_plays >= max_exhaust_plays):
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
                                                   reserve_for_block and not race_allin and not kill_race,
                                                   min_blk_cost, energy, race_allin, kill_race,
                                                   all_respawn=all_respawn,
                                                   run_deck=(state.get("run") or {}).get("deck"),
                                                   block_locked=block_locked)
            # 消耗递增罚分：第 1 次免费，之后每多打一次再扣一档——
            # 让坚毅在前期偶尔兑现，长战里自然让位给不可消耗的替代牌
            if _exhausts_other_cards(c):
                score -= self._exhaust_plays * exhaust_penalty_step
                # 卡手修正（第 135 局复盘）：手牌被不可出牌（感染/诅咒/状态）
                # 占满时，「消耗一张牌」是清手牌手段而非纯代价——135 局 F11
                # 精英战感染×3 卡手，坚毅手握整场未打，格挡与烧牌双价值空转
                if exhaust_unclog_bonus > 0:
                    clogged = sum(1 for h in hand if h is not c and not h.get("playable"))
                    if clogged:
                        score += min(clogged, 2) * exhaust_unclog_bonus
            immediate_score = score
            # Final-floor draft attribution is useful when choosing a reward, but a
            # negative draft value must not tell the executor to waste already-paid
            # cards and energy.  Combat accepts only a small non-negative prior.
            score += max(0.0, self.know.card_value(c.get("card_id", ""))) * 0.3
            # 零出牌死牌出牌否决（第529局批复盘）：生涯多拿零打的强制入组牌
            # 若在战斗端可出，learned value 加成与面板高伤会让它抢能量——
            # 与拾取端一票否决同一份证据接到出牌端口（负值有限，僵局强攻
            # 兜底通道不受影响）
            cid = (c.get("card_id") or "").upper().rstrip("+")
            never_played_dead = self._is_never_played_dead(cid)
            if never_played_dead:
                score -= float(pol.get("never_played_veto_penalty", 40.0))
            # A stale picked>=N/plays==0 veto must be recoverable if a later game/API
            # version exposes a genuinely playable positive card.  It may bypass the
            # threshold once per combat, but explicit status/curse/unplayable payloads
            # never receive novelty promotion.
            successful_plays = self._successful_card_plays(cid)
            safe_trial = self._safe_controlled_trial(c)
            trial_already = cid in self._novel_trials
            eligible_for_best = not (never_played_dead and trial_already)
            target_enemy = next((enemy for enemy in enemies
                                 if enemy.get("index") == target), None)
            self._trace_candidate(
                c.get("name") or c.get("card_id") or f"手牌 {c.get('index')}",
                score, index=c.get("index"), action="play_card",
                status="eligible" if eligible_for_best else "vetoed",
                why=(why if eligible_for_best else
                     f"{why}；零成功出牌否决且本场受控试用已用"),
                target={"index": target,
                        "name": (target_enemy or {}).get("name", "")} if target is not None else None)
            if eligible_for_best and (best is None or score > best[0]):
                best = (score, c, target, why)

            if immediate_score > 0.0 and safe_trial:
                if successful_plays > 0:
                    mode = "边际收益兜底"
                elif not trial_already:
                    mode = "受控试用"
                else:
                    mode = None
                if mode is not None and (marginal_best is None
                                         or immediate_score > marginal_best[0]):
                    marginal_best = (immediate_score, c, target, why, mode)

        choice_mode = ""
        chosen = best if best and best[0] > pol["play_threshold"] else None
        if chosen is None and marginal_best is not None:
            immediate_score, card, target, why, choice_mode = marginal_best
            chosen = (immediate_score, card, target, why)
        if chosen is not None:
            _, card, target, why = chosen
            commit_cid = (card.get("card_id") or "").upper().rstrip("+")
            commit_trial = False
            if (not choice_mode
                    and self._is_never_played_dead(card.get("card_id", ""))
                    and self._successful_card_plays(card.get("card_id", "")) == 0
                    and self._safe_controlled_trial(card)):
                choice_mode = "受控试用"
            if choice_mode == "受控试用":
                commit_trial = True
                why += "｜受控试用：零成功出牌但当前可用且有正即时边际（本场限一次）"
            elif choice_mode:
                why += f"｜{choice_mode}：正即时边际不带能量空过"
            commit_exhaust = _exhausts_other_cards(card)
            # 斩杀竞速记账：累计本场期望总伤与出牌回合数（实测输出速率的分子分母）
            _kd, _kb, _kh = card_numbers(card)
            _est = 0.0
            if _kd > 0:
                _est = float(_kd * _kh)
                if "所有敌人" in _text(card) or "all enemies" in _text(card).lower() \
                        or (card.get("target_type") or "") == "AllEnemies":
                    _est *= max(1, len(enemies))
            # 记录"预测击杀"：同一敌人本场被预测击杀 ≥2 次仍存活 → 重生召唤物，
            # 后续击杀奖励大幅衰减（第 52~53 局利齿之眼实证）
            commit_kill_id = ""
            if target is not None and isinstance(why, str) and why.startswith("可击杀"):
                tgt = next((e for e in enemies if e.get("index") == target), None)
                if tgt is not None:
                    commit_kill_id = tgt.get("enemy_id") or tgt.get("name") or ""
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
                                  ("play_card_index", card.get("index"),
                                   self._card_key(card)[1]),
                                  ("combat_play_commit", commit_cid, commit_trial,
                                   commit_exhaust, _est, round_no, commit_kill_id)], wait=0.6)
        # 僵局强攻（turn≥120 或 AI 判 offense）：绕过评分阈值，任何伤害牌打最低血敌人
        if round_no >= 120 or getattr(ctx, "force_offense", False):
            for c in hand:
                if not c.get("playable") or self._card_unavailable(c):
                    continue
                cost = energy if c.get("costs_x") else (c.get("energy_cost") or 0)
                if cost > energy:
                    continue
                _fd, _fh, _fhits = card_numbers(c)
                if _fd <= 0:
                    continue
                tgt = min(enemies, key=lambda e: e.get("current_hp", 9999))
                params = {"card_index": c["index"]}
                if c.get("requires_target"):
                    params["target_index"] = tgt.get("index")
                return Decision("play_card", params,
                                f"战斗：僵局强攻（回合{round_no}）打出【{c.get('name')}】→{tgt.get('name')}",
                                tags=[("play_card", c.get("card_id")),
                                      ("play_card_index", c.get("index"),
                                       self._card_key(c)[1])], wait=0.6)
        cooling_affordable = [c for c in hand
                              if c.get("playable")
                              and self._card_cooldowns.get(self._card_key(c), 0) > 0
                              and (energy if c.get("costs_x")
                                   else (c.get("energy_cost") or 0)) <= energy]
        if can_end and cooling_affordable:
            # These exact instances were selected as worthwhile immediately before
            # a refresh-race 409.  Do not convert their temporary rotation into an
            # energy-wasting end turn when there is no non-cooling sibling to play.
            return Decision(None, {},
                            "战斗：可用牌刚遇到状态刷新竞争，等待短冷却后继续出牌",
                            wait=0.5)
        if can_end:
            hand_desc = ",".join(f"{c.get('name')}{'✓' if c.get('playable') else '✗'}" for c in hand) or "空手"
            risk = "；警告：结束回合可能致死！" if combat.get("end_turn_will_kill_player") else ""
            skipped_by_energy = [c for c in hand if c.get("playable")
                                 and not self._card_unavailable(c)
                                 and c.get("energy_cost", 0) > energy]
            energy_note = f"；{len(skipped_by_energy)}张可出牌因能量不足弃用" if skipped_by_energy else ""
            return Decision("end_turn", {},
                            f"战斗：评估后无值得出的牌（{hand_desc}），结束回合（敌意图总伤{incoming}，我方{my_hp}血/{my_block}甲）{risk}{energy_note}{danger_note}",
                            wait=1.2)
        return Decision(None, {}, "战斗：等待出牌时机", wait=0.7)

    def _score_play(self, card, enemies, incoming, my_block, round_no, pol,
                    my_hp: int = 9999, my_max_hp: int = 9999, stance: dict | None = None,
                    forced_kill: bool = False, reserve_for_block: bool = False,
                    min_blk_cost: int = 99, cur_energy: int = 0, hopeless_race: bool = False,
                    kill_race: bool = False, all_respawn: bool = False,
                    run_deck: list[dict] | None = None, block_locked: bool = False):
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

        孤注一掷（第 59 局复盘新增）：致死缺口在手却无任何可负担格挡牌时，
        防御路线已不存在，解除非击杀攻击的禁玩压制并提速（desperate_atk_mult），
        抢斩杀让敌人意图作废是唯一活路——旧逻辑此局面 3 能量原样结束回合白吃刀。

        败局竞速（第 60~61 局复盘新增）：净损速率外推 horizon 回合内必死时，
        即便单回合还有格挡可补也不许再"边防边耗"——温水路线的每一分格挡都只是
        延缓死亡（61 局 Boss T3~T5 意图 19→21→23→25，T4 手握五张攻击全弃权）。
        解除能量预留并提速输出；与孤注一掷互斥触发提速，避免双重放大。
        """
        dmg, block, hits = card_numbers(card)
        declared_block = block
        if block_locked:
            block = 0
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
        # 孤注一掷（第 59 局 Boss 战 T6 实证）：致死缺口在手、却没有任何可负担的
        # 格挡牌时，旧逻辑把全部非击杀攻击压到禁玩线、3 能量原样结束回合白吃
        # 13 刀——无甲可补时防御已不可能，唯一活路是抢斩杀让敌人意图作废。
        # 败局竞速局吞并孤注一掷（第514~517批复盘）：竞速已判必败时，致死回合
        # 若仍落入 desperate 的 0.55 攻击衰减+1.8 格挡增益，执行层就在逐回合
        # 买命——「必败局的伤害会流到打死为止」的直接执行层病灶；判死局的
        # 唯一翻盘路径是把每一分能量押进输出，让实测 dpt 有机会上修推翻投影。
        desperate = lethal and not reserve_for_block and not hopeless_race
        # 败局竞速：整场被判负但单回合尚不致死——desperate 只救"当场必死"，
        # 这里救的是"两回合内必死"；二者互斥计提速，保证任何局面只放大一次
        race_allin = hopeless_race and not desperate
        urgent = gap > 0 and hp_pct < float(st.get("urgent_hp_pct", 0.45))  # 慢性失血下的低血量状态
        # 败局竞速豁免（第514~517批复盘）：判死局的致死回合不再压攻击抬格挡——
        # 买命买不来胜利，输出是唯一可能改写结局的变量；普通局 lethal 原样保留
        if lethal and not race_allin:
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
        if desperate or race_allin:
            atk_damp *= float(pol.get("desperate_atk_mult", 1.3))
        # 败局竞速执行经济学（第546局批复盘新增）：竞速判死后非致死回合，
        # 纯格挡不得再按原价挤占输出能量——543 局 F5 实证：29 血对意图 34、
        # 「全攻提速」留痕在场，整回合能量仍流向挑衅+双防御（block_safety 2.1
        # 让任何格挡牌面值压过非击杀攻击），下一回合才轮到输出已无命花。
        # 致死回合豁免：买命延长输出窗口在当场仍是合法战术，原价保留
        if race_allin and not lethal:
            blk_boost *= float(pol.get("race_allin_blk_damp", 0.45))
        # 斩杀竞速失败（第 90~91 批复盘）：与孤注一掷/败局竞速互斥放大——
        # 已在提速的局面不再叠加，只补「奢侈格挡贬值」这半边
        if kill_race and not desperate and not race_allin:
            atk_damp *= float(pol.get("kill_race_atk_mult", 1.25))
            blk_boost *= float(pol.get("kill_race_blk_mult", 0.70))

        m_self = re.search(r"失去\s*(\d+)\s*点?\s*生命|lose\s+(\d+)\s*(?:hp|health|life)", text, re.I)
        self_cost = int(next(g for g in m_self.groups() if g)) if m_self else 0
        floor_score = -50.0  # 生存模式禁玩线：叠加 card_value 加成后仍远低于阈值

        def _hybrid_defense() -> tuple[float, str] | None:
            """混合牌（伤害与格挡并存，如火焰屏障系）的防御面向评分。

            第 71 局 Boss 终盘实证（05:33:08）：火焰屏障+被解析成 6 点弱攻击，
            致死回合（服务端 end_turn_will_kill_player）被压到禁玩线弃权——
            而它的本体是 16 点格挡，足以完全抵消当轮意图救回一命。
            card_numbers 的 dmg>0 分支会遮蔽格挡价值，攻防两面必须取优：
            有缺口时防御面向往往远高于弱攻击面，无缺口时自动回落攻击面。
            """
            if block <= 0:
                return None
            useful_b = min(block, max(0, incoming - my_block))
            s = (useful_b * 1.05 * pol["block_safety"]
                 + (block - useful_b) * float(pol.get("block_excess_value", 0.03))) * blk_boost
            why_b = f"格挡{block}"
            dr_b = draw_amount(card)
            if dr_b:
                s += dr_b * 1.5
                why_b += f"/抽牌{dr_b}"
            if cost == 0:
                s += pol["free_card_bonus"]
            return s, why_b

        # --- 攻击牌（有伤害数值） ---
        if dmg > 0:
            total = dmg * hits

            def _effective_pool(enemy: dict) -> float:
                try:
                    raw_hp = enemy.get("current_hp", 9999)
                    hp = max(0.0, float(9999 if raw_hp is None else raw_hp))
                    enemy_block = max(0.0, float(enemy.get("block", 0) or 0))
                except (TypeError, ValueError):
                    return 9999.0
                return hp + enemy_block

            def _effective_damage(_enemy: dict) -> float:
                """Immediate attack output; block absorption is still real removal."""
                # Keep the long-standing overkill/kill-bonus scale for ordinary
                # targets, but unlike ``damage - block`` do not erase the portion
                # that strips block.  Confirmed respawn adds are capped separately.
                return float(total)

            def _would_kill(enemy: dict) -> bool:
                return float(total) >= _effective_pool(enemy)

            if aoe:
                eff = 0
                for e in enemies:
                    # Damage absorbed by enemy block still removes a current combat
                    # resource.  The old max(1, damage-block) valued a 6-damage Strike
                    # into 8 block as only 1 point, which routinely fell below the
                    # play threshold and ended turns with all energy unused.
                    e_eff = _effective_damage(e)
                    if self._is_respawn_add(e) and not all_respawn:
                        # 确认重生体：过量伤害记到当前血量为止（第 58 局实证：
                        # 11 点伤害砸 5 血利齿之眼按 11 计分，虚高吸走输出）
                        e_eff = min(e_eff, max(1.0, _effective_pool(e)))
                    eff += e_eff
                killable = [e for e in enemies if _would_kill(e)]
                score = eff * atk_damp + sum(
                    self._kill_bonus(e, sum((it.get("total_damage") or 0) for it in e.get("intents", [])),
                                     incoming, pol, ignore_respawn=all_respawn)
                    for e in killable)
                if reserve_for_block and not killable and cost + min_blk_cost > cur_energy:
                    score -= 8.0  # 给格挡让路：这点能量留着补缺口
                if lethal and not killable and not (desperate or race_allin):
                    # 致死威胁下 AOE 若不能减员，等于放弃生存换数值
                    score = min(score, floor_score)
                if self_cost and lethal and len(killable) < len(enemies):
                    # 判死竞速豁免（第 635~640 批复盘）：竞速/孤注一掷判定的
                    # 致死回合里，群体自残攻击（突破族：小额掉血换全体伤害）
                    # 旧例被无条件压到禁玩线——非群体自残在同一局面走
                    # desperate「无甲孤注抢斩杀」照常上砧，唯独群体面被吞，
                    # 640 局 F21「全攻提速」留痕下手握【突破】带能量空过。
                    # 判死局的唯一翻盘路径是把每一分能量押进输出（第546局
                    # 复盘教义），故对同一语境开放豁免；守卫两条：
                    # ① 自残后血量归零的直死牌不豁免（终局教训保留）；
                    # ② 豁免仍按减半复利口径计价，零自残攻击优先。
                    _doomed = desperate or race_allin or bool(kill_race)
                    if _doomed and my_hp - self_cost > 0:
                        score -= self_cost * (1.5 + 3.0 * (1.0 - hp_pct)) * 0.5
                    else:
                        score = min(score, floor_score)
                if cost == 0:
                    score += pol["free_card_bonus"]
                hb = _hybrid_defense()
                if hb is not None and hb[0] > score:
                    return hb[0], None, hb[1]
                return score, None, f"群体伤害≈{eff}"
            best_t, best_s, why, best_kill = None, -1.0, "", False
            # 辅助体转火（第 136~137 批复盘）：多敌战斗中本回合零伤害意图的敌人
            # （治疗/增益/蓄力型）威胁分成恒为 0，旧评分永远把它排最后——头号杀手
            # 同族双子（生涯 46 战 24 死）的神官持续强化信徒、意图逐轮滚升，
            # 拖长战斗正是死因形态。击杀辅助消除的是未来的意图增长，
            # 给予定向转火加分（重生召唤物与单敌战斗除外）
            sup_bonus = float(pol.get("support_target_bonus", 0.0))
            _valid = (card.get("valid_target_indices") or []) if card.get("requires_target") else []
            # 合法目标优先；列表为空/过期（击杀后刷新延迟）时退化为全体敌人，
            # 保证评分反映真实期望而非被压成 -1 弃权（第 44 局 F6 实证）
            _pool = [e for e in enemies if not _valid or e.get("index") in _valid] or list(enemies)
            for e in _pool:
                resp = self._is_respawn_add(e) and not all_respawn
                eff = _effective_damage(e)
                threat = sum((it.get("total_damage") or 0) for it in e.get("intents", []))
                # 已持有力量层数的敌人是场上的战斗时钟。旧辅助体转火会把
                # 零伤害减益体当头号目标，真正持续叠力量的敌人反而被晾着。
                scaler_stack = (self._enemy_strength_stack(e)
                                if (not resp and len(enemies) > 1) else 0.0)
                is_support = (not resp and len(enemies) > 1 and threat <= 0
                              and sup_bonus > 0 and scaler_stack <= 0)
                if resp:
                    # 确认重生体三重压制（第 58 局利齿之眼被预测击杀 13 次仍吸引
                    # 输出、本体雾菇意图滚到 22 的教训）：
                    #   ① 过量伤害只记到当前血量——打不死的部分是纯浪费；
                    #   ② 威胁分成清零——杀它一次只延迟一回合，消除不了长期威胁；
                    #   ③ 击杀奖励归零（_kill_bonus 内 ×0）
                    eff = min(eff, max(1.0, _effective_pool(e)))
                    s = eff * atk_damp
                else:
                    s = (eff + threat * 0.3) * atk_damp
                    if scaler_stack > 0:
                        s += sup_bonus * min(1.0, scaler_stack / 7.0)
                    elif is_support:
                        s += sup_bonus
                killed = _would_kill(e)
                if killed:
                    s += self._kill_bonus(e, threat, incoming, pol, ignore_respawn=all_respawn)
                if best_t is None or s > best_s:
                    best_t, best_s, best_kill = e.get("index"), s, killed
                    why = f"可击杀{e['name']}" if killed else (
                        f"自我强化体优先转火：{e['name']}（力量+{scaler_stack:.0f}，"
                        f"拖越久打越痛）" if scaler_stack > 0 else (
                            f"辅助体优先转火：{e['name']}（零伤害意图，放生=纵容其强化队友）"
                            if is_support else f"单体伤害≈{eff}"))
            # 致死回合里"打不死人的大伤害"是自杀牌：
            # 第 28 局 Boss 战终盘 1 血面对 11 点意图，重锤(42伤)压过防御(5甲)
            # 抢走全部能量，结果无甲吃刀阵亡——非击杀攻击必须给格挡让路。
            # 但孤注一掷/败局竞速回合例外：防守已不可能或已被证伪时，输出就是唯一的防御。
            if lethal and not best_kill and not (desperate or race_allin):
                best_s = min(best_s, floor_score)
            elif reserve_for_block and not best_kill and cost + min_blk_cost > cur_energy:
                best_s -= 8.0  # 能量预留：先补防再输出（第 36 批 F17 Boss 战教训）
            elif desperate and not best_kill:
                why += "｜无甲孤注抢斩杀"
            elif race_allin and not best_kill:
                why += "｜败局竞速全攻"
            elif self_cost:
                if best_kill and len(enemies) == 1:
                    pass  # 击杀最后一个敌人直接终局，自残值得
                elif lethal and not desperate:
                    best_s = min(best_s, floor_score)
                else:
                    best_s -= self_cost * (1.5 + 3.0 * (1.0 - hp_pct))  # 血越少自残越贵
            if cost == 0:
                best_s += pol["free_card_bonus"]
            hb = _hybrid_defense()
            if hb is not None and hb[0] > best_s:
                return hb[0], None, hb[1]
            return best_s, best_t, why

        # --- 防御/技能牌（有格挡数值） ---
        if block > 0:
            useful = min(block, max(0, incoming - my_block))
            # 溢出型大格挡贬值（第 94~95 批复盘）：有用量只有缺口那么大，
            # 但 2 费 40 挡在 7 点意图面前花掉的是 2 点能量——94 局 Boss 战
            # 开局 87 血对意图 7/17 连打两张岿然不动+，~56 点溢出甲 ≈ 4 能量
            # 没换成伤害，Boss 多活两轮 26/16 的升级意图（战损 61、二幕以 26%
            # 血入场后力竭）。斩杀竞速投影治「防守已被证伪」，这里治
            # 「防守根本不必要」：有用部分不足牌面一半且血量不在紧急线内时，
            # 该牌按纯溢出计价跌破出牌阈值；高意图回合（右尺寸）与低血量
            # （urgent/lethal）不受影响。
            if useful < block * 0.5 and not lethal and not urgent:
                score = useful * float(pol.get("block_excess_value", 0.03))
                why = f"格挡{block}｜溢出大挡贬值"
            else:
                # 溢出格挡大幅贬值（第 59 局 Boss 首回合实证：缺口 13 却连打坚毅24+
                # 重振精神10 共 34 甲，3 能量零输出——溢出按 block_excess_value 计分，
                # 缺口补满后的纯溢出防牌应跌破出牌阈值，把能量还给输出）
                score = (useful * 1.05 * pol["block_safety"]
                         + (block - useful) * float(pol.get("block_excess_value", 0.03))) * blk_boost
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
            # 孤注一掷/败局竞速回合例外：多抽一张攻击牌就是多一分抢斩杀的弹药
            if lethal and not (desperate or race_allin):
                score = min(score, floor_score)  # 致死回合抽牌/回能救不了命
            if cost == 0:
                score += pol["free_card_bonus"]
            return score, None, f"功能牌（抽牌{dr}/回能）"

        # 锁格挡期间纯防牌是零收益死牌；带伤害、抽牌或回能面的混合牌仍由
        # 前面的对应分支正常计价。文本通道兼容服务端已把动态格挡报成 0 的载荷。
        if (block <= 0 and dmg <= 0 and dr <= 0
                and "能量" not in text and "energy" not in text.lower()
                and ((block_locked and declared_block > 0)
                     or re.search(r"获得\s*0\s*点?\s*格挡|gain\s+0\s+block", text, re.I))):
            return -2.0, None, "锁格挡（不可格挡期间零收益，让位实伤）"

        # --- 无直接数值：按能力牌处理，开局回合优先 ---
        # 死牌禁玩（第470局批复盘）：条件型成长引擎的触发条件卡组无法满足
        # （撕裂族需要自残源）时，长战复利根本不存在——旧评分仍按
        # base+长战加成给它 7~14 分，死亡战 T1 压过攻击上砧白吃一整轮能量。
        # 按死牌计价压到出牌阈值之下，手牌里真没别的可打时宁可空过。
        # 第546局批复盘修复：is_power 依赖 card_type 字段，而战斗手牌载荷
        # 根本没有该字段（见本方法 docstring）——旧守卫在实战中永不生效，
        # 只有 selfcheck 夹具（带 card_type）能通过。补第二条文本共现通道：
        # 「力量+失去生命」同现即条件引擎，卡组无自残源一律按死牌治理
        if run_deck is not None and (
                (is_power(card)
                 and not self._scaling_power_active(card, run_deck))
                or (self._self_damage_conditioned(card)
                    and not self._deck_has_self_damage(run_deck))):
            return -2.0, None, "死牌（触发条件无自残源，永不生效，让位实伤）"
        # 长战加成（第 223 批复盘）：能力牌的价值随战斗预期长度复利——Boss/大血池
        # 战斗要打 6~10 回合，力量源（恶魔形态/点燃/撕裂）每早一回合上场就多一档
        # 全程增益。旧评分与战斗时长脱钩（固定 6.0/1.5），在 Boss 攻坚 ×1.8 下
        # 整场输给攻击牌：生涯 DEMON_FORM 2 拿 0 打——3 费整回合换 6 分永远轮不上，
        # scaling 卡在最需要它的长战里上不了场；而 219/220/223 三局 Boss 死的
        # 斩杀竞速投影（击杀 6~7 回合 > 可存活 2 回合）正是缺这一档复利输出。
        # 按存活敌血池线性加成（封顶）：低意图窗口（Boss 蓄力/增益回合）能力牌
        # 压过打击上砧，高意图回合攻击/格挡原样优先；第 3 回合起加成减半
        # （晚上场复利打折）。走廊小血池战斗加成 ≤1.5，不扭曲既有节奏。
        base = float(pol["power_round_bonus"] if round_no <= 2 else 1.5)
        pool = 0.0
        for e in enemies:
            try:
                pool += max(0.0, float(e.get("current_hp") or 0.0))
            except (TypeError, ValueError):
                continue
        lf = min(float(pol.get("power_longfight_bonus_max", 7.0)),
                 pool / max(1.0, float(pol.get("power_longfight_hp_div", 30.0))))
        if round_no > 2:
            lf *= 0.5
        score = base + lf
        # 致死回合上能力=放弃格挡能量（旧规）；败局竞速局同治（第546局批复盘）：
        # 判死局的能力复利视界（3+ 回合起步）超出剩余存活视界（~2 回合），
        # 543 局 F5 在「全攻提速」留痕下打出乱战+恶魔形态零伤整回合直接致死——
        # 战略层判死必须穿透到能力牌评分，否则全攻提速只是口号
        if lethal or race_allin:
            score = min(score, floor_score)
        if cost == 0:
            score += pol["free_card_bonus"]
        why = f"能力/增益牌（第{round_no}回合）"
        if lf >= 1.5:
            why += f"｜长战加成+{lf:.1f}（敌血池{pool:.0f}）"
        # 开局承诺加成（第555~653批复盘新增）：贵重力量引擎（恶魔形态等 3 费能力）
        # 在 T1~T2 手握足额能量时必须能压过「先打零散小攻击、引擎改天再说」的贪心
        # 顺位——本批实证：DEMON_FORM 整批 9 局拾取/升级共 12 次仅 4 局打出，
        # 生涯 45 拿仅 29 打、BARRICADE 5 拿 1 打；真实手牌里的上勾拳/痛击带威胁
        # 加分常与引擎基础分平起平坐，逐 tick 贪心把 3 能量先碎花掉，引擎到手
        # 又趴回牌堆 → 实测 dpt 填不平竞速缺口 → 投影自我兑现判死。再叠一档
        # power_round_bonus 保证有意义的领先幅度；双门槛防走样：
        #   ① 敌血池合计 ≥ power_commit_pool_min（走廊小战不加成，节奏不扭曲）；
        #   ② 当前能量足额（cur_energy >= cost，承诺的是整回合换复利）。
        # 竞速判死/致死回合维持上方 floor 不变：判死局烧 3 费买复利、视界超出
        # 剩余存活视界的旧教训不推翻。
        # 类型判定不走 is_power——战斗手牌载荷没有 card_type 字段（第546局
        # 批复盘教义），文本通道 + 注入 card_type 后复用 _scaling_power_active
        # （保留撕裂族「零自残源死牌」的否决语义）。
        _pool_floor = float(pol.get("power_commit_pool_min", 90.0))
        _scaling_text = bool(re.search(
            r"力量|strength|伤害\s*(提高|提升|增加)|(?:increase|gain[s]?)\s*.{0,16}(?:strength|damage)",
            _text(card), re.I))
        if (round_no <= 2 and cost > 0 and cur_energy >= cost and not (lethal or race_allin)
                and _scaling_text
                and self._scaling_power_active(dict(card, card_type="Power"), run_deck or [])
                and pool >= _pool_floor):
            _commit = float(pol.get("power_round_bonus", 6.0))
            score += _commit
            why += f"｜开局承诺+{_commit:.1f}（引擎整回合在场复利）"
        return score, None, why

    def _is_respawn_add(self, enemy: dict) -> bool:
        """同一敌人本场已被预测击杀 ≥2 次仍存活 → 判定为重生召唤物。

        跨局名册（第 506~508 局批复盘新增）：506 局 F13 精英战对扭动虫
        （重生召唤物）按「零伤害辅助体」优先转火，前两刀斩杀奖励全喂给
        打不死的分身（该战 -46 掏空半管血），直到同场检测器坐实才解除——
        这个学费每种重生体每局都在重交。现在当场坐实的瞬间把敌键登记进
        跨局名册（每场至多一次），此后任何战斗第 1 回合即按重生体三重压制
        （过量封顶/威胁清零/击杀奖励归零），不再重交学费。生效门槛为
        ≥2 场独立战斗的实证：单场误报（预测伤害被格挡吃掉等）不会污染名册。
        """
        kid = enemy.get("enemy_id") or enemy.get("name") or ""
        if self._combat_kills.get(kid, 0) >= 2:
            if kid and kid not in self._respawn_reported:
                self._respawn_reported.add(kid)
                try:
                    self.know.mark_respawn_add(kid)
                except Exception:
                    pass
            return True
        if kid and kid in self._respawn_reported:
            return True
        try:
            return self.know.is_known_respawn_add(kid)
        except Exception:
            return False

    def _enemy_strength_stack(self, enemy: dict) -> float:
        """读取敌人当前持有的力量类增益层数；无法识别时保持旧行为。"""
        total = 0.0
        for power in (enemy.get("powers") or []):
            if not isinstance(power, dict):
                continue
            power_id = str(power.get("id") or power.get("power_id")
                           or power.get("name") or "")
            if "strength" not in power_id.lower() and "力量" not in power_id:
                continue
            amount = next((power.get(key) for key in ("amount", "stack", "value", "count")
                           if power.get(key) is not None), None)
            try:
                amount_value = float(amount)
            except (TypeError, ValueError):
                continue
            if amount_value > 0:
                total += amount_value
        return total

    def _kill_bonus(self, enemy: dict, threat: float, incoming: float, pol: dict,
                    ignore_respawn: bool = False) -> float:
        """击杀奖励按「消除的威胁占比」折算，并对已证实的重生召唤物归零。

        第 52~53 局实证：利齿之眼每回合被【可击杀】斩首又复活，kill_bonus=12
        吸引引擎单场追杀召唤物 10+ 次，雾菇本体意图 8→23 滚雪球把 80 血磨穿——
        击杀的价值在消灭未来的意图来源，目标威胁占比越低越不值钱。
        第 58 局再实证：×0.25 的衰减仍压不过"过量伤害记满额 + 威胁分成"的虚高，
        利齿之眼被预测击杀 13 次、本体只挨 6 刀，83 血整场送光——重生体的击杀
        奖励必须彻底归零，配合评分端的三重压制（过量封顶/威胁清零）才能扭转目标。
        空档回合（intent 全 0）按全额计：抢在召唤物产出意图之前清场仍有价值。
        ignore_respawn（第 152 局复盘）：场上存活敌人全是已证实重生体时，
        归零击杀奖励等于禁止终结战斗——此时压制解除，奖励照常计。
        """
        kid = enemy.get("enemy_id") or enemy.get("name") or ""
        if not ignore_respawn and self._combat_kills.get(kid, 0) >= 2:
            return 0.0
        share = 1.0 if incoming <= 0 else min(1.0, max(0.0, threat) / incoming)
        return pol["kill_bonus"] * (0.4 + 0.6 * share)

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
            potion_key = self._potion_key(p)
            if (potion_key in self._potion_tried
                    or self._potion_cooldowns.get(potion_key, 0) > 0):
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
            # 「能力/ power」补入（第 94~95 批复盘）：95 局能力药水因描述不含
            # 任何已知关键词，premium 门（高危姿态 T1 即开）形同虚设，直到
            # 20 血才被 ≤50% 兜底分支掏出——晚了 7 个回合的增益等于没有
            is_buff = ("力量" in desc or "strength" in desc_l or "敏捷" in desc
                       or "dexterity" in desc_l or "能量" in desc or "energy" in desc_l
                       or "抽" in desc or "draw" in desc_l or "速度" in desc or "speed" in desc_l
                       or "能力" in desc or "power" in desc_l)
            # 防御/回复类前置识别（第470局批复盘）：「格挡药水」在满血时过不了
            # 交药线门槛，旧流程会一路落进「无法分类」兜底被 premium 硬仗开局
            # 白喝——470 局 F7 以 91/91 满血、意图 14 的轻量战把格挡药水倒进
            # 去了，五层后的死亡战手里再无防御资源。已识别类别的门槛必须
            # 尊重：识别为防御/回复的药水不得再经兜底通道流失
            is_defensive = bool("格挡" in desc or "生命" in desc or "回复" in desc
                                or "block" in desc_l or "heal" in desc_l)
            # Boss 前夜进攻药水预留（第 380~385 批复盘）：BNSJ 局实证——F4 力量/
            # F14 易伤/F15 攻击三瓶进攻药水在 Boss 前全数前倾兑付（其中两瓶倒在
            # 净损 0/-5 的普通怪房），F17 一幕 Boss 斩杀竞速差 3~7 回合空手阵亡。
            # premium 的统计恐惧门（高危组合/高期望战损）对普通房照常开门，而
            # 进攻/增益药水的真正兑现窗口是 Boss 竞速——距下一个 Boss ≤N 层的
            # 普通房里封存进攻类药水；当场致死或血量跌破交药线立即解封，
            # 防御/回复药水与精英/Boss 房不受限（详见 _hold_offensive_potion）
            if (is_damage or is_buff) and self._hold_offensive_potion(ctx, run, pol, combat):
                continue  # 封存且不计入 tried——本场若恶化成致死局仍可立即启用
            # 增益药水的价值在长战/硬仗兑现：普通战（哪怕低血放血）不构成使用理由，
            # 跳过且不计入 tried——本场若恶化成致死局仍可立即启用
            if is_buff and not premium:
                continue
            if (is_damage or is_buff) and enemies:
                params = {"option_index": p["index"]}
                if target is not None:
                    params["target_index"] = target
                kind = "攻击" if is_damage else "增益"
                return Decision("use_potion", params, f"战斗：硬仗使用{kind}药水【{name}】",
                                tags=[("use_potion", p.get("potion_id")),
                                      ("potion_attempt", p["index"],
                                       potion_key[1])], wait=0.6)
            if is_defensive:
                # 交药线接 potion_block_hp_pct（第 236 局复盘）：默认 0.35 与旧
                # 行为一致，爆毙/短时死亡证据在 block_safety 顶格后把它逐步提前
                _pot_line = float(pol.get("potion_block_hp_pct", 0.35))
                cb_def = (state.get("combat", {}).get("player", {}) or {})
                _hp_now = cb_def.get("current_hp", 1)
                _max_now = max(1, cb_def.get("max_hp", 1))
                # 应急解封（第470局批复盘）：交药线未到但服务端判定结束回合
                # 必死、或本地缺口已吞血条时，防御药水立即兑现——门槛拦的是
                # 满血糖掷，不是救命
                _incoming_now = sum((it.get("total_damage") or 0)
                                    for e in enemies for it in (e.get("intents") or []))
                _gap_now = max(0, _incoming_now - (cb_def.get("block", 0) or 0))
                _def_emergency = (bool(state.get("combat", {}).get("end_turn_will_kill_player"))
                                  or _gap_now >= _hp_now)
                if (_hp_now < _pot_line * _max_now) or _def_emergency:
                    return Decision("use_potion", {"option_index": p["index"]},
                                    f"战斗：低血量使用防御/回复药水【{name}】"
                                    f"（交药线 {_pot_line:.0%}）",
                                    tags=[("use_potion", p.get("potion_id")),
                                          ("potion_attempt", p["index"],
                                           potion_key[1])], wait=0.6)
                # 已识别的防御/回复类且未到交药线：显式保留，绝不落入下方
                # 兜底通道被 premium 硬仗开局白喝（470 局 F7 实证）
                continue
            # 兜底：硬仗（致死/精英/低血放血）里无法分类的药水也值得一试——
            # 用错药水的代价远小于带进坟墓（第 30~32 局三连教训）。
            # 默认反转（第 96 局复盘，兑现 94~95 批处方）：「能力/power」补词后
            # 又漏出第三批无法分类的药水（缚魂/无色/固化——96 局 Boss 战三者全部
            # 睡到 38% 血才被旧兜底掏出，其中固化药水单瓶 +33 甲）。增益类药水的
            # 价值随战斗剩余时长衰减，premium 硬仗的前 3 回合正是兑现窗口：
            # 未知类别直接放行，不再等血量跌破 50%。普通战仍保留（防绕过增益保留策略）
            cb_player = (state.get("combat") or {}).get("player") or {}
            cb_hp = cb_player.get("current_hp", 1)
            cb_max = max(1, cb_player.get("max_hp", 1))
            cb_incoming = sum((it.get("total_damage") or 0)
                              for e in enemies for it in (e.get("intents") or []))
            try:
                cb_turn = int(state.get("turn") or 99)
            except (TypeError, ValueError):
                cb_turn = 99
            early_premium = (premium and enemies and cb_turn <= 3
                             and not self._hold_offensive_potion(ctx, run, pol, combat))
            if early_premium or (premium and enemies and cb_incoming > cb_player.get("block", 0)
                                 and cb_hp <= 0.5 * cb_max):
                params = {"option_index": p["index"]}
                if target is not None:
                    params["target_index"] = target
                when_txt = "硬仗开局" if early_premium else "低血兜底"
                return Decision("use_potion", params,
                                f"战斗：{when_txt}使用药水【{name}】（描述无法分类，宁滥勿囤）",
                                tags=[("use_potion", p.get("potion_id")),
                                      ("potion_attempt", p["index"],
                                       potion_key[1])], wait=0.6)
        # A potion reaches this map only after Policy selected it and the API then
        # rejected the exact same live instance repeatedly.  If no sibling was
        # usable, wait for the short cooldown instead of ending a potentially lethal
        # turn while the rescue potion is still in the belt.
        cooling = [p for p in run.get("potions", [])
                   if p.get("occupied") and p.get("can_use")
                   and self._potion_cooldowns.get(self._potion_key(p), 0) > 0]
        if cooling:
            return Decision(None, {},
                            "战斗：救命药水刚遇到状态刷新竞争，等待短冷却后重试",
                            wait=0.5)
        return None

    def _race_joint_feasible(self, deck: list[dict], pool: float, fire: float,
                             my_hp: float, margin: float,
                             eff: float | None = None,
                             blk_eff: float | None = None) -> tuple[bool, str]:
        """联合能量口径的竞速可行性对账（第460局批复盘新增）。

        旧防守线复核的能量双算缺陷：进攻线按「满能量全攻」算击杀回合数，
        防守线按「满能量全挡」算存活回合数——同一回合的 3 点能量被两条线
        各花一次。只要格挡吞吐×折算率能摸到「火力-1」封顶线，任何卡组都被
        判成磨垒可行：460 批四场一幕 Boss 全部健康进场仍整管打空（U3D6 局
        前夜账面磨垒可行→回血进场→实战每回合能量既要买命又要输出，两头
        都够不着）；自检 ④ 的 guard_deck（唯一攻击牌 3 费+四张 1 费挡）是
        同一缺陷的最小复现——账面可行，实际永远凑不齐「19 挡+26 伤」同回合。

        修复：遍历「格挡能量 e_b + 进攻能量 E−e_b」的全部整数分配，再对
        Pareto 前沿相邻点做连续混合采样（对应隔轮轮换战术：挡一轮打一轮），
        任一点满足 击杀所需回合数 ≤ 净火力存活回合数 + 余量 即判可行。
        纯进攻点（e_b=0）保留在集合内——本口径是旧两线并集的严格收紧，
        只砍掉物理上做不到的「双算可行」，不会放行比旧纯进攻更差的路线。

        返回 (是否可行, 可行点描述)；不可行时描述为空串。

        口径说明：伤害轴一律用先验能力（deck_burst×eff），不用实测速率——
        实测是随机过程的一次采样，可行性规划应对齐期望产能；实测速率只负责
        上游「竞速是否已判负」的门。篝火端与战斗端因此共用同一把尺。
        """
        pol = self.know.policy
        if eff is None:
            eff = max(0.05, float(pol.get("kill_race_prior_eff", 0.55)))
        if blk_eff is None:
            blk_eff = max(0.05, float(pol.get(
                "kill_race_blk_eff",
                float(pol.get("kill_race_prior_eff", 0.55)))))
        energy = 3.0
        steps = max(1, int(round(energy)))
        pts = []
        for eb in range(steps + 1):
            ea = energy - float(eb)
            b = min(max(0.0, float(fire) - 1.0),
                    self.deck_block_burst(deck or [], float(eb)) * blk_eff)
            d = (self.deck_burst(deck or [], ea) * eff) if ea > 1e-9 else 0.0
            pts.append((b, d))
        # Pareto 前沿：按格挡量升序（同格挡量伤害降序），保留「伤害随格挡
        # 递减」的权衡曲线——高挡低伤与低挡高伤互不支配，都是合法战术点
        frontier = []
        best_d = float("inf")
        for b, d in sorted(pts, key=lambda p: (p[0], -p[1])):
            if d < best_d:
                frontier.append((float(b), float(d)))
                best_d = d

        def _ok(b: float, d: float) -> bool:
            if d <= 1e-9:
                return False
            ttk = float(pool) / d
            net = max(1.0, float(fire) - b)
            return ttk <= float(my_hp) / net + float(margin)

        n = len(frontier)
        # 单点与相邻点连线采样（0.05 步长近似连续混合）
        for i in range(n):
            if _ok(*frontier[i]):
                b, d = frontier[i]
                return True, f"格挡{b:.0f}+输出{d:.0f}/回合的分配"
            if i + 1 < n:
                b1, d1 = frontier[i]
                b2, d2 = frontier[i + 1]
                for k in range(1, 20):
                    t = k / 20.0
                    if _ok(b1 + (b2 - b1) * t, d1 + (d2 - d1) * t):
                        return True, (f"格挡{b1 + (b2 - b1) * t:.0f}"
                                      f"+输出{d1 + (d2 - d1) * t:.0f}/回合的混合分配")
        return False, ""

    def _race_potion_credit(self, potions: list | None, pool: float,
                            floor: int | None) -> float:
        """竞速账的随身药水授信（第654~663/675~680批复盘新增）。

        预留教义把进攻/增益药水整段封存给 Boss 竞速兑现，但旧竞速账只认
        deck_burst——已入库的药水爆发被两边重复计提（预留端当弹药扣着、
        可行性端又看不见），贴线的「药水助力即可行」对局被系统性判死，
        连带前夜弃疗上砧/入场线豁免全部按必败口径走。授信规则：
        - 只在 Boss 窗口内生效（距 Boss > race_potion_credit_floors_to_boss
          层不授信——此时预留门未锁，药水可能中途兑付进普通房，提前放行
          会造成假可行）；floor 缺失同样不授信（保守）。
        - 每瓶进攻类药水折算 race_potion_flat_credit 点血池削减，
          合计不超过 race_potion_pool_cap_frac × 血池。
        - 防御/回复药水不给授信（账只修输出侧，不动存活侧）。

        返回削减后的血池；输入为空或窗口外原样返回 pool（行为与旧版一致）。
        """
        pol = self.know.policy
        flat = float(pol.get("race_potion_flat_credit", 0.0))
        cap_frac = float(pol.get("race_potion_pool_cap_frac", 0.0))
        win = int(pol.get("race_potion_credit_floors_to_boss", 0))
        if not potions or flat <= 0.0 or pool <= 0.0 or win <= 0 or not floor:
            return float(pool)
        try:
            if self._floors_to_boss(int(floor)) > win:
                return float(pool)
        except (TypeError, ValueError):
            return float(pool)
        n = 0
        for p in potions:
            if isinstance(p, dict) and self._potion_class(p) == "offensive":
                n += 1
        if n <= 0:
            return float(pool)
        credit = min(float(n) * flat, cap_frac * float(pool))
        return max(1.0, float(pool) - credit)

    def _boss_race_doomed(self, deck: list[dict], max_hp: int,
                          floor: int | None = None,
                          potions: list | None = None) -> tuple[bool, str]:
        """Boss 竞速必败预演（第 397~402 批复盘新增；兑现第 214 批遗留的
        「攻坚投影·篝火端消费」接线）。

        本批五场 Boss 死亡全部发生在「前夜翻转带回血」之后：入场 57%~100%、
        战损 -46~-80 整管打空。竞速必败的对局里 Boss 的伤害会一直流到打死你
        为止——多 24 点入场血只是多吃几轮意图，回血的边际生存价值恒为零；
        而锻造缩短战斗是唯一可能翻转时间线的杠杆。

        判定与战斗端斩杀竞速投影同式对账：learned Boss 血池/火力均值
        （boss_race_vitals，138~141 批入库）× deck_burst×kill_race_prior_eff，
        满血可存活回合数仍追不上击杀所需回合数即判必败。
        分幕口径（第 506~515 局批复盘新增）：floor 可推幕号时消费分幕
        血池/火力均值——一幕 Boss 池实测血池 173~307，全幕混合均值 253 曾把
        一幕前夜系统性判死、翻转带回血压过锻造；分幕账未成熟时回落全量均值。
        防守线复核（第435~440批复盘引入，第460局批复盘改为联合能量口径）：
        进攻线（裸血÷火力）判负后，补算「持续买命」路线的可行性——但攻防
        两条线不得各自独占满能量（旧版能量双算：格挡吞吐摸到火力封顶线即判
        磨垒可行，460 批四场健康进场 Boss 全部整管打空），改用
        _race_joint_feasible 遍历攻防能量分配与轮换混合，任一分配能同时满足
        击杀与存活才不判必败（回血重新成为有效投资，前夜裁决交还旧三区口径）。
        数据未成熟/零爆发/零格挡/竞速关闭时返回 False，行为与旧版严格一致。
        """
        pol = self.know.policy
        if not pol.get("kill_race_enabled", True):
            return False, ""
        pool, fire = self.know.boss_race_vitals(
            self._floor_act(floor) if floor else None)
        if not pool or not fire or not max_hp:
            return False, ""
        # 第654~663/675~680批复盘：Boss 窗口内的随身进攻药水按保守折算冲抵
        # 血池（预留教义封存的弹药本就是竞速计划的组成部分），贴线对局不再
        # 因「药水已入库但账面看不见」被误判必败；窗口外/无药水时原账不动
        pool_eff = self._race_potion_credit(potions, float(pool), floor)
        _pot_tail = ""
        if pool_eff < float(pool):
            _pot_tail = f"，随身进攻药水授信-{float(pool) - pool_eff:.0f}血池"
        # 第547~552局批复盘：供给换 deck_effective_burst——力量引擎的复利
        # 授信计入竞速账，带引擎卡组不再被面值口径系统性判死（本批十局
        # 全线「缺口55%~83%直到前夜」的死锁主因之一）
        burst = self.deck_effective_burst(deck or [])
        if burst <= 0:
            return False, ""
        eff = max(0.05, float(pol.get("kill_race_prior_eff", 0.55)))
        margin = float(pol.get("kill_race_margin", 1.5))
        dpt = burst * eff
        ttk = pool_eff / max(1.0, dpt)
        tsurv = float(max_hp) / max(1.0, fire)
        if ttk <= tsurv + margin:
            return False, ""
        # 联合能量复核（第460局批复盘）：格挡折算率走独立的 kill_race_blk_eff
        # （第454局批复盘分家键）；攻防在同一能量预算内对账，双算可行一律砍掉
        _feasible, _ = self._race_joint_feasible(
            deck or [], pool_eff, fire, float(max_hp), margin, eff=eff)
        if _feasible:
            return False, ""
        note = (f"竞速预演：击杀需{ttk:.0f}回合＞满血可存活{tsurv:.0f}回合"
                f"（Boss血池均值{pool:.0f}、火力{fire:.0f}/回合，"
                f"先验输出{dpt:.0f}/回合{_pot_tail}；联合能量复核：任一攻防能量分配"
                f"均无法同时满足击杀与存活），必败局的伤害会流到打死为止")
        return True, note

    def required_deck_burst(self, max_hp: int, act: int | None = None) -> float | None:
        """竞速及格线：追平 learned Boss（血池/火力）所需的卡组理论爆发。

        第422局复盘新增。静态 deck_burst_floor=30 只回答「卡组比打击流强多少」，
        不回答「这套输出够不够杀 Boss」——422 局 burst≈33 高于静态门槛，全程被
        当「非饥饿」卡组对待：力量药水在 Boss 前 3 层的普通房被放行烧掉、商店
        金币先买了功能牌，最终空手走进必败竞速（先验 13/回合 vs 血池253/火力14）。
        本方法把「饥饿线」换成真实对账：required_dpt = 血池 ÷ 满血可存活回合
        （= pool×fire/max_hp），再除以 kill_race_prior_eff 还原成理论爆发口径；
        夹在 [deck_burst_floor, 3×deck_burst_floor] 内防数据噪声把线抬到天上。
        act 给定时消费分幕血池/火力均值（第 506~515 局批复盘新增）——一幕
        Boss 池实测血池 173~307，全幕混合均值把一幕及格线系统性抬高；分幕账
        未成熟时 boss_race_vitals 自行回落全量口径。
        数据未成熟/竞速关闭时返回 None——调用方必须回落静态门槛（行为与旧版一致）。
        """
        pol = self.know.policy
        if not pol.get("kill_race_enabled", True):
            return None
        pool, fire = self.know.boss_race_vitals(act)
        if not pool or not fire or not max_hp:
            return None
        eff = max(0.05, float(pol.get("kill_race_prior_eff", 0.55)))
        floor_b = float(pol.get("deck_burst_floor", 30.0))
        req_dpt = float(pool) * float(fire) / max(1.0, float(max_hp))
        return clamp(req_dpt / eff, floor_b, floor_b * 3.0)

    def _starve_line(self, max_hp: int | None = None,
                     act: int | None = None) -> float:
        """输出饥饿判定线：有 learned Boss 基准用竞速及格线，否则回落静态门槛。

        第423~428批复盘（兑现第422局「凡达标/饥饿判定必须对账」教义的全消费端
        收口）：required_deck_burst 此前只接了药水预留窗与商店端，拿牌端/地图端/
        升级端仍按静态 deck_burst_floor 判饥饿——本批六局卡组爆发普遍高于静态带
        却远低于杀 Boss 所需，高质攻击饥饿加分、升级攻击加成全程缺位，竞速缺口
        无人在拾取端补（78% 血满状态进 Boss 照样整管打空）。max_hp 缺失或数据
        未成熟时行为与旧版严格一致（冷启动安全）。
        act 给定时及格线换用分幕 Boss 口径（第 506~515 局批复盘新增）。
        """
        if max_hp:
            _req = self.required_deck_burst(int(max_hp), act=act)
            if _req is not None:
                return _req
        return float(self.know.policy.get("deck_burst_floor", 30.0))

    @staticmethod
    def _floor_act(floor_no: int | None) -> int:
        """楼层 → 幕号（1~3），作为路线与结算的唯一边界口径。

        一幕 F1-17、二幕 F18-33、三幕 F34+；异常输入按一幕处理（冷启动安全）。
        """
        try:
            f = int(floor_no or 1)
        except (TypeError, ValueError):
            return 1
        if f <= 17:
            return 1
        if f <= 33:
            return 2
        return 3

    @staticmethod
    def _floors_to_boss(floor_no: int) -> int:
        """距下一个 Boss 的层数（幕长为常量：一幕 Boss F17、二幕 F33，三幕按 51 估算）。

        生涯 320 场一幕 Boss 全部落在 F17、24 场二幕 Boss 全部落在 F33——
        幕边界是可靠常量，无需地图负载即可推算。
        """
        if floor_no <= 17:
            return 17 - floor_no
        if floor_no <= 33:
            return 33 - floor_no
        return 51 - floor_no

    def _hold_offensive_potion(self, ctx, run: dict, pol: dict, combat: dict) -> bool:
        """Boss 前夜进攻药水预留判定（第 380~385 批复盘新增）。

        进攻/增益药水的价值窗口是 Boss 斩杀竞速（「输出缺口是唯一主矛盾」教义），
        但 premium 统计恐惧门会让它们持续前倾兑付进普通怪房。规则：
        - 距下一个 Boss ≤ potion_boss_reserve_floors 层才生效（远端战斗照旧投放，
          不回潮「囤药带进坟墓」旧病——第 28/30~32 局教训）；
        - 输出饥饿卡组加宽预留窗（第 386~390 批复盘）：deck_burst < deck_burst_floor
          时窗口放宽到 potion_starved_reserve_floors（默认 6 层）。本批五局实证：
          竞速投影全线「击杀还需 N 回合 > 可存活 M 回合」的饥饿卡组，进攻药水
          仍在 Boss 前 4~7 层的普通房被统计恐惧门放行烧掉（LK4C 局 F10 爆炸
          药水、3QQC 局 F13 速度+增益药水），到 F17 一幕 Boss 全部空手或只剩
          零头，竞速差 3~7 回合处决——饥饿卡组的 Boss 竞速是唯一胜机，普通房
          的「硬」改变不了结局，Boss 房的「硬」直接决定结局。强卡组不受影响，
          解封三口（致死判定/交药线/精英Boss房）原样保留；
        - 仅封普通房：Elite/Boss 节点药水照常投入（精英换遗物值得花弹药）；
        - 解封口：服务端致死判定在场，或血量已跌破交药线（保命优先于囤积）。
        """
        reserve = int(pol.get("potion_boss_reserve_floors", 2))
        if reserve <= 0:
            return False
        # 输出饥饿卡组：预留窗加宽到 potion_starved_reserve_floors（第 386~390 批）。
        # 第422局复盘：饥饿线从静态 deck_burst_floor 升级为竞速及格线
        # required_deck_burst（learned Boss 血池/火力对账）——burst≈33 的卡组
        # 高于静态门槛却远低于杀 Boss 所需，旧口径把它当「强卡组」放行烧药；
        # 分幕口径消费当前楼层对应幕的 Boss 基准（第 506~515 局批复盘新增）；
        # 数据未成熟时回落静态门槛（行为与旧版一致）
        _deck_now = run.get("deck") or []
        if _deck_now:
            if self.deck_effective_burst(_deck_now) < self._starve_line(
                    max(1, int(run.get("max_hp", 1) or 1)),
                    act=self._floor_act(run.get("floor"))):
                reserve = max(reserve, int(pol.get("potion_starved_reserve_floors", 6)))
        try:
            f = int(run.get("floor", 0) or 0)
        except (TypeError, ValueError):
            return False
        if f <= 0 or self._floors_to_boss(f) > reserve:
            return False
        node_t = ((getattr(ctx, "combat", None) or {}).get("node_type")) or ""
        if node_t in ("Elite", "Boss"):
            return False
        if combat.get("end_turn_will_kill_player"):
            return False
        pl = combat.get("player") or {}
        # 解封血线（第422局复盘）：与防御端「提前交药线」potion_block_hp_pct
        # 解耦。旧版复用该键，其被爆毙证据推到顶格 0.80 后，预留窗内只要
        # 掉血<20% 就放行烧药，封存形同虚设；缺键回落旧键（兼容旧库）
        _line = float(pol.get("potion_hold_release_hp_pct",
                              pol.get("potion_block_hp_pct", 0.35)))
        if pl.get("current_hp", 1) <= _line * max(1, pl.get("max_hp", 1)):
            return False
        return True

    # ------------------------------------------------------------------
    # rewards / selection / bundles / chest / capstone
    # ------------------------------------------------------------------

    @staticmethod
    @staticmethod
    def _is_scaling_power(card: dict) -> bool:
        """力量/伤害成长型能力牌判定（第429~434批复盘新增）。

        拾取端与锻造端必须共用同一口径，否则出现「拾取认得点燃、锻造不认得」
        的半接线断层（第423~428批复盘教义：教义落地必须验收到最后一个消费端）。
        判定沿用第 255 批的文本正则：获得力量 / 伤害提高类描述。
        """
        if not is_power(card):
            return False
        return bool(re.search(
            r"力量|strength|伤害\s*(提高|提升|增加)|(?:increase|gain[s]?)\s*.{0,16}(?:strength|damage)",
            _text(card), re.I))

    @staticmethod
    def _deck_has_self_damage(deck: list[dict]) -> bool:
        """卡组中是否存在自残源（「失去X点生命」型攻击/技能）。"""
        for c in deck or []:
            if re.search(r"失去\s*\d+\s*点?\s*生命|lose\s+\d+\s*(?:hp|health)",
                         _text(c), re.I):
                return True
        return False

    @staticmethod
    def _self_damage_conditioned(card: dict) -> bool:
        """文本同时含「获得力量」与「失去生命」→ 触发前提是卡组有自残源。

        第546局批复盘新增：不依赖 is_power（战斗手牌载荷没有 card_type 字段，
        470 局的死牌守卫在战斗端整体失活——LU9H 局零自残卡组 18/21 血两次
        打出撕裂即铁证）。判定放宽为文本共现：撕裂族的变体措辞
        （「失去生命时获得力量」「Whenever you lose HP, gain Strength」）
        无论条件从句在前在后都能命中；无条件力量牌（点燃/恶魔形态）文本
        不含「失去生命」，天然不受影响。
        """
        t = _text(card)
        if not re.search(r"力量|strength", t, re.I):
            return False
        return bool(re.search(
            r"失去\s*\d*\s*点?\s*生命|lose[s]?\s+(?:\d+\s+)?(?:hp|health|life)", t, re.I))

    def _scaling_power_active(self, card: dict, deck: list[dict]) -> bool:
        """条件型成长引擎在当前卡组下能否真实生效（第470局批复盘新增）。

        撕裂（RUPTURE）族：文本形如「每当你失去生命时，获得1点力量」——
        触发前提是卡组存在自残源。零自残卡组里它是永不在场生效的死牌，
        却因文本含「力量」被 _is_scaling_power 认成成长引擎，三端同时吃分：
        商店按引擎稀缺加分购入、篝火按 +16 引擎分连续升级、战斗端按长战
        加成 T1 上砧——470 局实证全程零触发，其中一场是死亡战（T1 撕裂
        压过攻击白吃一整轮能量）。除「失去生命」触发表以外的成长牌
        （点燃/恶魔形态等无条件增益）一律视为生效，行为不变。
        """
        if not self._is_scaling_power(card):
            return False
        t = _text(card)
        if re.search(r"(?:每当|每次|whenever|any\s*time)[^。；;.]{0,24}(?:失去|lose)",
                     t, re.I):
            return self._deck_has_self_damage(deck)
        return True

    def _is_never_played_dead(self, card_id: str) -> bool:
        """零出牌死牌判定（第529局批复盘新增）。

        知识恶魔战强制入组的瓦解/心灵腐化/懒惰类死牌：生涯多拿零打
        （DISINTEGRATION 29拿0打），面板数字被 card_numbers 解析成高伤攻击，
        幻影伤害会污染 deck_burst 爆发口径。判据与拾取端一票否决同一把尺：
        picked ≥ unplayed_min_picked 且 plays == 0；引擎日后真实打出
        （plays>0）自动解除（自愈）；冷启动无统计恒 False，行为不变。
        """
        pol = self.know.policy
        e = (self.know.stats.get("cards") or {}
             ).get((card_id or "").upper().rstrip("+")) or {}
        return (int(e.get("picked", 0) or 0) >= int(pol.get("unplayed_min_picked", 4))
                and not int(e.get("plays", 0) or 0))

    def _successful_card_plays(self, card_id: str) -> int:
        """Return confirmed successful plays, never attempted-action counts."""
        e = (self.know.stats.get("cards") or {}
             ).get((card_id or "").upper().rstrip("+")) or {}
        return int(e.get("plays", 0) or 0)

    @staticmethod
    def _safe_controlled_trial(card: dict) -> bool:
        """Whether a positive, currently legal card may bypass a stale zero-play veto once.

        Combat payloads normally omit ``card_type``, so the engine's ``playable`` flag is
        necessary but not sufficient: known status/curse ids and explicit unplayable text
        are rejected before the numeric/text effect check.  This is deliberately
        conservative; an unknown card with no recognizable positive effect keeps the
        normal policy score and is never promoted merely for novelty.
        """
        if not card.get("playable"):
            return False
        ctype = (card.get("card_type") or "").lower()
        if ctype in ("status", "curse"):
            return False
        if card.get("requires_target") and not (card.get("valid_target_indices") or []):
            return False

        cid = (card.get("card_id") or "").upper().rstrip("+")
        name = (card.get("name") or "").strip()
        text = _text(card)
        # Token boundaries avoid rejecting legitimate cards such as BURNING_PACT merely
        # because their id contains the letters of the BURN status.
        bad_id_token = re.search(
            r"(?:^|_)(?:CURSE|STATUS|DAZED|WOUND|BURN|SLIMED|VOID|REGRET|PAIN|"
            r"DOUBT|SHAME|NORMALITY|PARASITE|INJURY|DECAY|CLUMSY|PRIDE|"
            r"ASCENDERS_BANE)(?:$|_)", cid)
        forced_dead = any(cid.endswith(suffix) for suffix in (
            "DISINTEGRATION", "MIND_ROT", "SLOTH", "WASTE_AWAY",
            "INFECTION", "GREED", "GUILTY", "NOT_YET", "SPOILS_MAP"))
        bad_names = {"晕眩", "伤口", "灼伤", "黏液", "虚无", "遗憾", "疼痛",
                     "疑虑", "羞耻", "常态", "寄生", "腐朽", "笨拙", "傲慢",
                     "进阶之灾", "瓦解", "心灵腐化", "懒惰"}
        if bad_id_token or forced_dead or name in bad_names:
            return False
        if re.search(r"不可打出|不能打出|无法打出|cannot\s+be\s+played|unplayable|"
                     r"诅咒|curse|状态牌|status\s+card", text, re.I):
            return False

        dmg, block, _hits = card_numbers(card)
        if dmg > 0 or block > 0 or draw_amount(card) > 0:
            return True
        if ctype in ("attack", "skill", "power"):
            return True
        return bool(re.search(
            r"获得.*(?:能量|力量|敏捷)|回复|治疗|heal|gain.*(?:energy|strength|dexterity)",
            text, re.I))

    def deck_burst(self, deck: list[dict], energy: float = 3.0) -> float:
        """卡组一回合期望伤害吞吐量：按「伤害/能耗」降序贪心装满 energy 点能量。

        第 88~89 批复盘新增（原为 eval_reward_card 内联逻辑，第 90~91 批复盘
        提取为公共方法）：斩杀竞速投影在战斗头两回合（实测速率样本不足时）
        也需要卡组理论爆发做先验估计，两处必须共用同一套口径。
        零出牌死牌不计入装箱（第529局批复盘）：强制入组牌的面板伤害从未被
        战斗端兑现，计入等于给饥饿判定/竞速预演/药水预留发幻影额度。
        """
        burst_energy, burst = energy, 0.0
        _burst_cards = []
        for c in deck or []:
            d, _b, h = card_numbers(c)
            if d > 0 and is_attack(c):
                if self._is_never_played_dead(c.get("card_id", "")):
                    continue
                _cost = max(1, c.get("energy_cost", 1) or 1)
                _burst_cards.append((d * h / _cost, _cost, d * h))
        _burst_cards.sort(reverse=True)
        for _eff, _cost, _tot in _burst_cards:
            if burst_energy <= 0:
                break
            if _cost > burst_energy:
                continue
            burst += _tot
            burst_energy -= _cost
        return burst

    def deck_block_burst(self, deck: list[dict], energy: float = 3.0) -> float:
        """卡组一回合期望格挡吞吐量：与 deck_burst 同式贪心，按「格挡/能耗」装满 energy。

        第435~440批复盘新增（防守线复核的供给侧）：斩杀竞速投影此前只算
        「裸血 ÷ 意图火力」的可存活回合数——把格挡整项忽略，而当前卡组的
        格挡吞吐恰恰是决定「防守路线是否可行」的第一变量（S42CX 局 89% 血
        进一幕 Boss 照样 5~6 回合整管打空：竞速投影提前判死 → 全攻提速
        blk×0.7 → 不买命 → 自证死期）。口径与 deck_burst 严格同源：
        同一贪心、同一能量预算、同一 prior_eff 悲观折算——两条路线的账本
        必须用同一把尺，否则复核本身就是新的乐观偏差。
        """
        block_energy, block = energy, 0.0
        _block_cards = []
        for c in deck or []:
            _d, b, _h = card_numbers(c)
            if b > 0 and not is_bad_card(c):
                _cost = max(1, c.get("energy_cost", 1) or 1)
                _block_cards.append((b / _cost, _cost, b))
        _block_cards.sort(reverse=True)
        for _eff, _cost, _tot in _block_cards:
            if block_energy <= 0:
                break
            if _cost > block_energy:
                continue
            block += _tot
            block_energy -= _cost
        return block

    def deck_effective_burst(self, deck: list[dict], energy: float = 3.0) -> float:
        """引擎有效爆发：deck_burst（攻击面值装箱）+ 力量成长牌的复利授信。

        第547~552局批复盘新增。本批十局的死因高度同构：竞速预演从 F1 起全线
        「缺口55%~83%」直到前夜判死——但 deck_burst 只装攻击牌面值，点燃/
        恶魔形态等力量引擎贡献恒为零，后果是三重死锁：
        ①拾取端拿了引擎，饥饿线/缺口分毫不动，评分系统看不见自己的进步；
        ②前夜竞速预演对带引擎卡组系统性过度判死（先验输出=面值×eff，把
          复利窗口整体抹零）；
        ③战斗端头两回合的开账 DPS 同样失真，引擎卡组被提前推向 all-in。
        授信口径：每张生效成长引擎 +engine_burst_credit（默认6≈+2力/回合
        在7回合长战的复利折算，再除以 eff 还原理论口径），至多计
        engine_credit_cap 张（防囤引擎注水）；条件型引擎走
        _scaling_power_active 同一把尺（撕裂族零自残卡组不授信）。
        仅替换「供给 vs 需求」类消费端（饥饿判定/竞速预演/药水预留/拿牌
        门槛），required_deck_burst 需求线与格挡侧不受影响。
        """
        burst = self.deck_burst(deck, energy)
        pol = self.know.policy
        credit = float(pol.get("engine_burst_credit", 6.0))
        cap_n = int(pol.get("engine_credit_cap", 2))
        if credit <= 0.0 or cap_n <= 0 or not deck:
            return burst
        n_eng = sum(1 for c in deck if self._scaling_power_active(c, deck))
        return burst + credit * min(n_eng, cap_n)

    def _deck_good_count(self, deck: list[dict]) -> int:
        """卡组中非基础、非废牌的数量（单薄/膨胀判定的共同口径）。"""
        return sum(1 for c in deck
                   if not ("STRIKE" in (c.get("card_id") or "").upper()
                           or "DEFEND" in (c.get("card_id") or "").upper()
                           or is_bad_card(c)))

    @staticmethod
    def _state_has_explicit_card_offer(state: dict) -> bool:
        """Whether this state exposes a voluntary card reward offer.

        Upgrade/removal/transform/combat selection screens also contain cards, but
        they are not offers and must never affect reward ``seen`` statistics.
        """
        screen = state.get("screen")
        if screen == "REWARD":
            reward = state.get("reward") or {}
            return bool(reward.get("pending_card_choice")
                        and reward.get("card_options"))
        if screen == "CARD_SELECTION":
            selection = state.get("selection") or {}
            return bool(selection.get("cards")
                        and "skip_reward_cards" in (state.get("available_actions") or []))
        return False

    def _record_card_offer(self, source: str, state: dict,
                           cards: list[dict]) -> tuple:
        """Count each base card id once when a new offer first becomes observable."""
        run = state.get("run") or {}
        selection = state.get("selection") or {}
        signature = tuple(sorted(
            ((str(c.get("card_id") or "").upper().rstrip("+"),
              bool(c.get("upgraded")), str(c.get("name") or ""))
             for c in cards),
            key=lambda x: x))
        key = (source, state.get("run_id") or run.get("run_id"), run.get("floor"),
               str(selection.get("kind") or ""), str(selection.get("prompt") or ""),
               signature)
        if key != self._active_card_offer_key:
            self._active_card_offer_key = key
            self._active_card_offer_explore_id = None
            self.know.commit_card_offer(c.get("card_id") for c in cards)
        return key

    def _reward_exploration_safe(self, card: dict, deck: list[dict]) -> bool:
        """Conservative safety gate for deliberate non-greedy reward trials."""
        cid = str(card.get("card_id") or "").upper().rstrip("+")
        if not cid or is_bad_card(card):
            return False
        if not card.get("upgraded") and ("STRIKE" in cid or "DEFEND" in cid):
            return False
        if self._is_never_played_dead(cid) or self.know.card_is_proven_bad(cid):
            return False
        text = _text(card).lower()
        if re.search(r"无法打出|不能打出|不可打出|unplayable|cannot\s+be\s+played|can't\s+be\s+played",
                     text, re.I):
            return False
        # 条件型成长牌在当前卡组无法触发时是已知死牌，不拿它做探索样本。
        if self._is_scaling_power(card) and not self._scaling_power_active(card, deck):
            return False
        return True

    def _reward_card_choice(self, scored: list[tuple[float, dict]], deck: list[dict],
                            state: dict, ctx,
                            value_floor: float) -> tuple[float, dict, str, tuple | None]:
        """Choose a reward card with a bounded UCB novelty allowance.

        The greedy heuristic remains the default.  A deliberate trial can replace it
        only when the candidate is safe, under-sampled, above the actual take floor,
        and within a configurable raw-score margin.  A per-run quota hard-caps the
        cost of exploration.  No random epsilon is needed, so an eligible unseen card
        cannot lose forever merely because every run rolled the same coin flip.
        """
        best_v, best = scored[0]
        pol = self.know.policy
        if (not bool(pol.get("card_exploration_enabled", True))
                or int(pol.get("card_exploration_run_quota", 2)) <= self._card_explore_used):
            return best_v, best, "", None

        cached = self._active_card_offer_explore_id
        if cached:
            for value, card in scored:
                if str(card.get("card_id") or "").upper().rstrip("+") == cached:
                    return (value, card, "（同一 offer 保持受控探索选择）",
                            self._novelty_tag("card", cached, self._card_explore_used))

        min_picks = max(1, int(pol.get("card_exploration_min_picks", 2)))
        margin = max(0.0, float(pol.get("card_exploration_near_best_margin", 2.5)))
        ucb_scale = max(0.0, float(pol.get("card_exploration_ucb_scale", 1.0)))
        min_value = max(float(value_floor),
                        float(pol.get("card_exploration_min_value", 1.0)))

        def samples(card: dict) -> int:
            cid = str(card.get("card_id") or "").upper().rstrip("+")
            entry = (self.know.stats.get("cards") or {}).get(cid) or {}
            return max(0, int(entry.get("picked", 0) or 0),
                       self.know.novelty_trial_count("card", cid))

        total_samples = sum(samples(c) for _v, c in scored)
        log_mass = math.log(2.0 + total_samples + len(scored))
        eligible = []
        for value, card in scored:
            picked = samples(card)
            if (picked >= min_picks or value < min_value
                    or best_v - value > margin
                    or not self._reward_exploration_safe(card, deck)):
                continue
            ucb = value + ucb_scale * math.sqrt(log_mass / (1.0 + picked))
            eligible.append((ucb, -picked, value, card))
        if not eligible:
            return best_v, best, "", None
        ucb, _neg_picked, value, card = max(
            eligible,
            key=lambda row: (row[0], row[1], row[2],
                             str(row[3].get("card_id") or "")))
        chosen_id = str(card.get("card_id") or "").upper().rstrip("+")
        best_id = str(best.get("card_id") or "").upper().rstrip("+")
        # If the unseen card is already greedy-best, it is naturally explored and
        # should not spend the deliberate non-greedy quota.
        if chosen_id == best_id or ucb <= best_v + 1e-9:
            return best_v, best, "", None
        # Cache the retry intent now, but commit quota/sample only after the agent
        # appends the returned tag for an accepted HTTP response.
        self._active_card_offer_explore_id = chosen_id
        picked = samples(card)
        note = (f"（受控探索：原值 {value:.1f}，UCB {ucb:.1f}，"
                f"生涯拾取 {picked}/{min_picks}，本局配额 "
                f"{self._card_explore_used + 1}/{int(pol.get('card_exploration_run_quota', 2))}）")
        return (value, card, note,
                self._novelty_tag("card", chosen_id, self._card_explore_used))

    def _thin_deck_must_pick(self, deck: list[dict], best_v: float) -> bool:
        """单薄卡组正价值保底（第 236 局复盘）：卡组单薄（非基础牌 < core）时，
        严格正价值的候选不再因低于拾取门槛被跳过——VS71 局开局连战五场
        零拿牌，0.8 分的正价值候选被 1.0 门槛拦下，饿死在 F6。门槛防的是
        膨胀卡组注水，单薄卡组的病是量不足（deck_thin_core 教义的自然延伸：
        单薄折扣已把门槛降向 0，但折扣未触底前仍会漏杀正价值候选）。
        负价值候选（诅咒/状态/未升级基础牌/实锤差牌）不在此列，照旧跳过。
        """
        if best_v <= 0:
            return False
        core = float(self.know.policy.get("deck_thin_core", 8))
        return self._deck_good_count(deck) < core

    def _pick_threshold(self, deck: list[dict],
                        max_hp: int | None = None,
                        act: int | None = None) -> float:
        """动态拿牌门槛：非基础牌超出软上限后线性抬升（每超一张 +1.5）。

        第 65 局实证：固定阈值 2.0 下 24 张卡组照拿不误（SHRUG_IT_OFF×5）——
        deck_overflow_penalty 的 -0.9/张 减分压不住 8+ 分的格挡牌，软上限形同
        虚设；膨胀稀释抽牌质量 → 战斗拖长 → 慢性失血，是 0/66 的慢性根因之一。
        卡组越臃肿越只拿精品：门槛抬到与"边际牌价值"同量级才能真实拦住注水。

        单薄折扣（第 90~91 批复盘）：91 局 16 张卡组进 Boss（非基础牌仅 6 张），
        整场只拿 6 张牌——长战后期抽牌全是打击。门槛此前只升不降，而单薄卡组
        的真正问题是「量不足」：抽 5 张的方差让爆发曲线无法稳定组装，此时
        及格线以上的牌都该收，每缺 1 张核心牌门槛按 discount 递减。

        输出饥饿减免（第514~517批复盘）：接通 pick_threshold_starve_relief 死键
        ——该键此前只存在于 policy.json，代码零消费，「饥饿降门槛」从未生效。
        卡组爆发低于竞速及格线时按缺口深度比例降低门槛（深缺口最多 -2.5），
        与拾取端饥饿加分同向：把边际攻击/引擎变便宜，而不是拦在及格线外。
        """
        pol = self.know.policy
        base = float(pol["card_pick_threshold"])
        if not deck:
            return base
        good = self._deck_good_count(deck)
        overflow = good - float(pol.get("deck_soft_cap", 20))
        thr = base
        if overflow > 0:
            thr += overflow * float(pol.get("pick_threshold_per_overflow", 1.5))
        core = float(pol.get("deck_thin_core", 8))
        if good < core:
            thr -= (core - good) * float(pol.get("deck_thin_discount", 0.35))
        relief = float(pol.get("pick_threshold_starve_relief", 0.0))
        if relief > 0.0 and max_hp:
            _burst = self.deck_effective_burst(deck)
            _line = self._starve_line(max_hp, act=act)
            if _burst < _line:
                _deficit = clamp(1.0 - _burst / max(1e-6, _line), 0.0, 1.0)
                thr -= relief * _deficit
        return max(0.0, thr)

    def eval_reward_card(self, card: dict, deck: list[dict],
                         max_hp: int | None = None,
                         act: int | None = None) -> float:
        """卡牌拾取/购买价值评估。

        act 给定时饥饿线换用分幕 Boss 口径（第 506~515 局批复盘新增）：
        一幕及格线不再被二三幕血池均值抬高，高质攻击/引擎的饥饿纠偏
        力度随真实缺口缩放。
        """
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

        # 卡组爆发吞吐量（第 88~89 批复盘新增）：按「伤害/能耗」降序贪心装满
        # 一回合 3 能量的期望伤害。攻击占比维度（ratio）看不见「量足质弱」的
        # 输出饥饿——第 89 局卡组攻击占比达标，回合爆发却仍是几张 6 伤打击的
        # 水平，88% 血进一幕 Boss、11 回合仅打出 ~198 伤输掉斩杀竞速。
        # 生涯 0/89 胜、Boss 阵亡遍布 52%~99% 入场血量：卡组强度而非入场血量
        # 才是当前瓶颈，拿牌端必须对绝对输出缺口敏感。
        # 饥饿线对账化（第423~428批复盘，_starve_line）：有 learned Boss 基准
        # 时用竞速及格线——静态带只回答「比打击流强多少」，burst≈45 的卡组
        # 高于静态门槛却只有杀 Boss 所需的三分之一，旧口径判「非饥饿」后
        # 拾取端对缺口彻底失明（缺口分母同步换成及格线，纠偏力度随真实差距缩放）
        burst = self.deck_effective_burst(deck)
        _line = self._starve_line(max_hp if deck else None, act=act)
        burst_starved = bool(deck) and burst < _line

        # 攻击牌边际价值乘法衰减（固定 -2.5 挡不住基础分 10+ 的攻击牌，
        # 第 18 局仍拿了 24 张近乎全攻的牌）：占比越高衰减越狠
        if is_attack(card):
            atk_scale = clamp(1.3 - 1.4 * ratio, 0.15, 1.2)
            value += (dmg * hits * 1.0 + (1.0 if cost <= 1 else 0.0)) * atk_scale
            if ratio < 0.35:
                # 输出不足时额外鼓励补攻击；越枯竭越急迫（第 71 局终局卡组
                # 攻击占比 ~20%，Boss 战输出跌到裸打击水平）
                value += 1.5 + min(2.5, (0.35 - ratio) * 12.0)
            # 绝对输出饥饿（第 88~89 批复盘）：占比达标但全是低伤打击时，
            # 高质攻击（单牌总伤 ≥12 且 ≥7 伤/能耗，即显著强于打击）额外加分——
            # 质量门槛确保只奖励「替换打击级输出」的牌，弱攻击不因饥饿而虚高。
            # 加分随缺口深度放大（第 106 局复盘）：固定 +3 压不过 learned value
            # 的 ±6 摆动与格挡牌基础分，106 局爆发 18~21(<30) 照旧拿了一堆
            # 防御/功能牌，Boss 战实测输出 ~10-15/回合全面输掉斩杀竞速——
            # 缺口越深（burst 距门槛越远）纠偏力度越大，burst≈0 时达 base+extra
            # 第470局批复盘：条件型引擎（撕裂族）必须触发条件可满足才享受
            # 饥饿加分——零自残卡组里它永不生效，饥饿纠偏不能喂死牌
            if (dmg * hits >= 12 and dmg * hits / max(1, cost) >= 7.0 and burst_starved):
                deficit = clamp(1.0 - burst / max(1e-6, _line), 0.0, 1.0)
                value += (float(pol.get("burst_starve_bonus_base", 3.0))
                          + float(pol.get("burst_starve_bonus_extra_max", 4.0)) * deficit)
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
            # 纯防御饥饿贬值（第509~515局批复盘新增）：饥饿加分链顶格后所有
            # 高质攻击/引擎同分满额，纯防御牌却仍按原价竞争名额——深缺口局面
            # 「再一张耸肩」与「再一张高质攻击」的边际价值差被抹平，卡组构成
            # 对输出缺口的响应只剩加法端。本批六局拿牌账：UNRELENTING×3、
            # TRUE_GRIT/SHRUG_IT_OFF 照常入组，Boss 战先验输出仅 9~19/回合。
            # 缺口越深对无成长性的纯格挡牌按比例压价（上限三成），把同分僵局
            # 的裁决权还给伤害端；三重门控防误伤——格挡来源不足/卡组单薄时
            # 不贬值（那两种局面的病是量不足不是结构失衡），带抽牌的功能技
            # 不贬值（抽牌加速爆发组装，与饥饿方向一致）。空卡组上下文
            # （升级/删除/献祭评估）burst_starved 恒 False，天然不受影响
            if (deck and burst_starved and block > 0 and draw_amount(card) <= 0
                    and n_block >= pol.get("min_block_cards", 5)
                    and good_cards >= pol.get("deck_thin_core", 8)):
                _sup = (clamp(1.0 - burst / max(1e-6, _line), 0.0, 1.0)
                        * float(pol.get("starve_defense_suppress_max", 0.30)))
                if _sup > 0:
                    value *= (1.0 - _sup)
        elif is_power(card):
            value += 5.0
            # 输出饥饿时的成长牌增值（第 255 批复盘）：Boss 攻坚的死因形态是
            # 「即时伤害不够、长战无成长」——力量型能力每早一回合上场就全程
            # 复利加成（223 批已在战斗端给能力牌长战加成，拾取端此前仍按
            # 平面 5 分定价）。与高质攻击的饥饿加分同构：缺口越深纠偏越大；
            # 「拿了不打」惩罚与重复贬值照常生效，防止为饥饿囤死牌
            # 第470局批复盘：饥饿增值与引擎稀缺加分均改走 _scaling_power_active
            # ——撕裂族在零自残卡组里是死牌，不得再吃引擎分
            if burst_starved and self._scaling_power_active(card, deck):
                _p_deficit = clamp(1.0 - burst / max(1e-6, _line), 0.0, 1.0)
                value += (float(pol.get("power_starve_bonus_base", 2.0))
                          + float(pol.get("power_starve_bonus_extra_max", 4.0)) * _p_deficit)
                # 成长引擎稀缺加分（第429~434批复盘新增）：饥饿纠偏此前只看
                # 「缺口深度」不看「卡组已有几台成长引擎」——434 局 9 拿 0 张
                # 力量牌、生涯 INFLAME 仅 72 拿，前夜竞速预演全线「先验输出
                # 12/回合 vs 血池254」。数学上首台点燃在 7 回合长战里 ≈ +30 伤，
                # 恰好是本批 Boss 败局的典型差距，但旧加分上限 6 分压不过高质
                # 攻击的 20 分饥饿加分，引擎永远竞争不过又一张打击。稀缺度按
                # 已有引擎数线性衰减：零引擎全额、1 台减半、≥cap 归零——
                # 防「为饥饿囤三张恶魔形态」的反向注水
                if deck:
                    _engines = sum(1 for c in deck if self._scaling_power_active(c, deck))
                else:
                    _engines = 0
                _cap_e = max(1.0, float(pol.get("scaling_engine_deck_cap", 2.0)))
                _scarcity = clamp((_cap_e - _engines) / _cap_e, 0.0, 1.0)
                value += float(pol.get("scaling_engine_pick_bonus", 7.0)) * _scarcity
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
        # 同名重复递减（第 71 局实锤）：单局拿进 SHRUG_IT_OFF×5 / FLAME_BARRIER×4——
        # 同名牌边际收益骤减且稀释抽牌质量。按基础 id（去升级后缀）计数，
        # 已有 ≥2 张起每再拿一张线性加重扣分，把名额让给卡组缺的维度
        _base_id = cid.rstrip("+")
        _copies = sum(1 for c in deck
                      if ((c.get("card_id") or "").upper().rstrip("+") == _base_id)) if deck else 0
        if _copies >= 2:
            value -= (_copies - 1) * float(pol.get("duplicate_pick_penalty", 3.0))
        # 「拿了不打」贬值（第 71 局实证）：FLAME_BARRIER 生涯 13 拿 6 打——
        # 长期占据手牌打不出去的牌等于卡组注水。生涯 picked≥unplayed_min_picked
        # 且 plays ≤ unplayed_play_rate × picked 时，拾取端额外惩罚
        _e_card = self.know.stats.get("cards", {}).get(_base_id) or {}
        if (_e_card.get("picked", 0) >= int(pol.get("unplayed_min_picked", 4))
                and _e_card.get("plays", 0) <= float(pol.get("unplayed_play_rate", 0.5)) * _e_card["picked"]):
            value -= float(pol.get("unplayed_card_penalty", 4.0))
            # 零出牌硬回避（第524局批复盘）：plays==0 的牌战斗端从未打出过——
            # DISINTEGRATION(26拿0打)/MIND_ROT(12)/SLOTH(6)/WASTE_AWAY(5) 的
            # 「不可打出」面板被 card_numbers 解析成高伤攻击后，饥饿加分（可达
            # +20）长期压过 -4 旧罚分，选取率仍高达 74%，入组即死注水。零出牌
            # 实证升级为一票否决；删除/献祭端复用本函数，负值越大越先删/先交，
            # 语义自洽。若引擎日后能打出它，plays>0 后否决自动解除（自愈）
            if not int(_e_card.get("plays", 0) or 0):
                value -= float(pol.get("never_played_veto_penalty", 40.0))
        # 统计实锤的低价值牌（样本≥4 且场均显著低于全局均值）硬性回避：
        # EXPECT_A_FIGHT(6.6分/5局)、BASH(7.2分/6局) 的 learned value ≈ -2.8，
        # 压不住格挡/抽牌启发式的 12+ 基础分，必须用大额惩罚对冲
        if self.know.card_is_proven_bad(card.get("card_id", "")):
            value -= 12.0
        # 拾取端 learned value 封顶（第 106 局复盘）：outcome=到达层数是
        # 幸存者偏差噪声——能被拾取的前提就是活到奖励屏，早楼层 offered 的牌
        # 自动积累高 outcome。RAMPAGE 靠 +6 学习分在 55 局里自我强化循环拾取
        # （106 局又拿 3 张），FIEND_FIRE n=4 收缩后仍摆动 +7.6。封顶保留
        # 学习信号的方向、砍掉幅度；战斗端本就 ×0.3 不受影响
        # 引擎负分豁免（第547~552局批复盘新增）：learned value 的计量视界是
        # 「拿它的局走到了几层」，而力量引擎的价值恰在长战复利——DEMON_FORM
        # 被 -3.0 bias 全额压制（33拿25打，负账来自「在必败局拿了也没用」的
        # 归因倒置），与引擎稀缺/饥饿加分正面抵消，形成「永远凑不出斩杀引擎」
        # 死锁。深缺口（≥engine_bias_relief_deficit）时生效引擎的 learned
        # 负分归零：保留正分激励、只豁免方向性误判；非饥饿局面行为不变
        _cv_cap = float(pol.get("card_value_pick_cap", 3.0))
        _learned = clamp(self.know.card_value(cid), -_cv_cap, _cv_cap)
        if (_learned < 0.0 and burst_starved
                and self._scaling_power_active(card, deck)):
            _relief_gate = clamp(1.0 - burst / max(1e-6, _line), 0.0, 1.0)
            if _relief_gate >= float(pol.get("engine_bias_relief_deficit", 0.30)):
                _learned = 0.0
        value += _learned
        return value

    def _reward(self, state: dict, ctx) -> Decision:
        r = state.get("reward") or {}
        actions = state.get("available_actions", [])
        run = state.get("run") or {}
        deck = self._enrich_cards(run.get("deck", []))
        pol = self.know.policy
        floor = run.get("floor", 0)

        # 以完整奖励载荷区分同层连续奖励屏。领取后列表会变化/重排，此时清掉
        # 旧 payload 的 suppression，避免两个同文案奖励因 index 重用发生碰撞。
        reward_instance_key = (
            state.get("run_id"), floor,
            tuple((o.get("index"), o.get("reward_type"), o.get("description"),
                   bool(o.get("claimable"))) for o in (r.get("rewards") or [])),
            tuple((c.get("index"), c.get("card_id"), c.get("name"),
                   bool(c.get("upgraded"))) for c in (r.get("card_options") or [])),
            bool(r.get("pending_card_choice")),
        )
        if floor != self._reward_floor or reward_instance_key != self._reward_instance_key:
            self._reward_floor = floor
            self._reward_instance_key = reward_instance_key
            self._reward_tried = set()
            self._reward_cooldowns = {}
            self._reward_card_cooldowns = {}

        # card choice pending?
        cards = self._enrich_cards(r.get("card_options", []))
        if r.get("pending_card_choice") and cards:
            self._record_card_offer("REWARD", state, cards)
            _mh = max(1, int(run.get("max_hp", 1) or 1))
            _act = self._floor_act(floor)
            all_scored = sorted(
                ((self.eval_reward_card(c, deck, max_hp=_mh, act=_act), c)
                 for c in cards),
                key=lambda row: (-row[0], str(row[1].get("card_id") or "")))
            scored = [row for row in all_scored
                      if self._reward_card_cooldowns.get(
                          (row[1].get("index"), str(row[1].get("card_id") or "")), 0) <= 0]
            for value, card in all_scored:
                cooled = self._reward_card_cooldowns.get(
                    (card.get("index"), str(card.get("card_id") or "")), 0) > 0
                self._trace_candidate(
                    card.get("name") or card.get("card_id"), value,
                    index=card.get("index"), action="choose_reward_card",
                    status="cooldown" if cooled else "eligible",
                    why="精确目标短冷却" if cooled else "奖励卡价值（含真实卡组上下文）")
            if not scored:
                self._trace_gate("GATE 精确目标冷却", "wait", "全部候选处于短冷却")
                return Decision(None, {}, "奖励选牌：候选刚被状态竞争拒绝，短暂冷却后重试", wait=0.7)
            best_v, best = scored[0]
            vals = [f"{c.get('name')}={v:.1f}" for v, c in all_scored]
            pick_line = self._pick_threshold(deck, max_hp=_mh, act=_act)
            thin_take = self._thin_deck_must_pick(deck, best_v)
            self._trace_gate(
                "GATE 动态拾取门槛", "pass" if (best_v >= pick_line or thin_take) else "reject",
                f"最高 {best_v:.2f} / 门槛 {pick_line:.2f}；单薄保底={thin_take}")
            self._trace_gate(
                "RANK 奖励卡价值", "pass", f"{len(scored)} 个当前可选候选")
            if (best_v >= pick_line or thin_take) and "choose_reward_card" in actions:
                best_v, best, explore_note, explore_tag = self._reward_card_choice(
                    scored, deck, state, ctx,
                    value_floor=0.0 if thin_take else pick_line)
                gate_note = (f"≥ 门槛 {pick_line:.1f}" if best_v >= pick_line
                             else f"低于门槛 {pick_line:.1f}，但单薄卡组正价值保底")
                tags = [("card_pick", best.get("card_id")),
                        ("reward_card_attempt", best.get("index"),
                         str(best.get("card_id") or ""))]
                if explore_tag is not None:
                    tags.append(explore_tag)
                return Decision("choose_reward_card", {"option_index": best["index"]},
                                f"奖励选牌：【{best.get('name')}】（价值 {best_v:.1f}，{gate_note}）"
                                f"{explore_note}；候选：{', '.join(vals)}",
                                tags=tags, wait=0.8)
            all_best_v = all_scored[0][0]
            cooling_take = (all_best_v >= pick_line
                            or self._thin_deck_must_pick(deck, all_best_v))
            any_cooling = len(scored) < len(all_scored)
            if (best_v < pick_line and any_cooling and cooling_take
                    and not self._thin_deck_must_pick(deck, best_v)):
                # The best take was only temporarily rotated after a refresh-race
                # rejection.  Skipping the whole offer would turn a short cooldown
                # into permanent reward loss.
                return Decision(None, {},
                                "奖励选牌：应拿候选正在短冷却，等待后重试而不跳过整组",
                                wait=0.6)
            if best_v < pick_line and "skip_reward_cards" in actions \
                    and not self._thin_deck_must_pick(deck, best_v):
                return Decision("skip_reward_cards", {},
                                f"奖励选牌：全部跳过（最高价值 {best_v:.1f} < 门槛 {pick_line:.1f}）；候选：{', '.join(vals)}",
                                wait=0.8)

        # claim simple rewards (gold / relic / potion)；失败过的（如药水栏满）不再重试
        cooling_rewards = []
        for opt in r.get("rewards", []):
            if not opt.get("claimable"):
                continue
            rtype = opt.get("reward_type", "")
            key = (opt.get("index"), rtype, opt.get("description", ""))
            reward_status = ("tried" if key in self._reward_tried else
                             "cooldown" if self._reward_cooldowns.get(key, 0) > 0
                             else "eligible")
            self._trace_candidate(
                opt.get("description") or rtype or f"奖励 {opt.get('index')}", None,
                index=opt.get("index"), action="claim_reward",
                status=reward_status, why=f"奖励类型 {rtype}")
            if key in self._reward_tried:
                continue
            if self._reward_cooldowns.get(key, 0) > 0:
                cooling_rewards.append(key)
                continue
            if rtype in ("Gold", "Relic", "Potion") and "claim_reward" in actions:
                if rtype == "Potion":
                    pots = run.get("potions", [])
                    if pots and all(p.get("occupied") for p in pots):
                        continue  # 药水栏已满：领取必失败，直接放弃避免重试空转
                tags = [("reward_attempt", opt.get("index"), rtype,
                         opt.get("description", ""))]
                if rtype == "Relic":
                    tags.insert(0, ("relic_pick", opt.get("description", "")))
                return Decision("claim_reward", {"option_index": opt["index"]},
                                f"领取奖励：{opt.get('description')}", tags=tags, wait=0.7)
            if rtype in ("Card", "SpecialCard") and "claim_reward" in actions:
                return Decision("claim_reward", {"option_index": opt["index"]},
                                f"打开卡牌奖励：{opt.get('description')}",
                                tags=[("reward_attempt", opt.get("index"), rtype,
                                       opt.get("description", ""))], wait=0.7)

        if cooling_rewards:
            return Decision(None, {},
                            "奖励界面：被状态竞争拒绝的奖励短暂冷却，等待后重试",
                            wait=0.7)

        # 仍有未尝试但领取失败的奖励（如药水栏满）→ 放弃它们直接前进
        skipped = [k[2] for k in self._reward_tried
                   if any(o.get("claimable") and o.get("index") == k[0]
                          and o.get("reward_type") == k[1] and o.get("description") == k[2]
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
        cards = self._enrich_cards(sel.get("cards", []))
        kind = (sel.get("kind") or "").lower()
        prompt = sel.get("prompt") or ""
        if not cards:
            return Decision(None, {}, f"选牌界面（{kind}）：无候选，等待", wait=0.8)

        # 屏幕身份 + 防重复点击记忆（重复点同一张卡可能反选/空转）
        floor_no = (state.get("run") or {}).get("floor", 0)
        screen_key = self._selection_identity(state)
        if screen_key != self._sel_key:
            self._sel_key = screen_key
            self._sel_tried = set()
            self._sel_serial += 1
            self._sel_instance = self._sel_serial
            self._sel_mode = None

        # Only accepted selection clicks appear in credit_tags.  Failed requests
        # therefore leave the candidate available for a stable retry.
        for raw in getattr(ctx, "credit_tags", None) or []:
            if (isinstance(raw, (tuple, list)) and len(raw) >= 3
                    and raw[0] == "selection_click"
                    and raw[1] == self._sel_instance):
                try:
                    self._sel_tried.add(int(raw[2]))
                except (TypeError, ValueError):
                    pass

        # 删牌语义判定：关键词（remove/移除/删除）+ 商店删牌动作握手双保险。
        # 第 43/44 局实证：界面 kind/prompt 不含已知关键词时，删牌屏被当成通用
        # 拿牌屏按"最高价值"点选，把余烬+/上勾拳当垃圾删了——发起方知道上下文，
        # 显式握手优先于文案猜测
        blob = f"{kind} {prompt}".lower()
        explicit_removing = "remove" in blob or "移除" in blob or "删除" in blob
        if explicit_removing:
            self._sel_mode = "remove"
        elif self._removal_pending_floor == floor_no:
            # Bind the successful shop handshake to this concrete screen.  The mode
            # stays sticky across 409/disconnect retries, while the floor token can
            # now be consumed without contaminating a later selection on this floor.
            self._sel_mode = "remove"
            self._removal_pending_floor = -1
        removing = self._sel_mode == "remove"

        # 已达选择数量且可确认 → 先确认（升级/删除等分支也必须走这里，否则永远循环）
        min_sel = sel.get("min_select", 1)
        if (sel.get("can_confirm") and sel.get("selected_count", 0) >= min_sel
                and "confirm_selection" in actions):
            if self._ui_action_cooled(state, "confirm_selection", {}):
                return self._cooldown_wait("选牌界面")
            return Decision("confirm_selection", {}, f"选牌界面（{kind}）：已选 {sel.get('selected_count')} 张，确认",
                            wait=0.9)

        upgrading = "upgrade" in kind or "升级" in prompt or "锻造" in prompt
        transforming = "transform" in kind or "变化" in prompt
        # 牌堆顶选择（第 82~83 批复盘）：头槌系攻击命中后要求"从弃牌堆选一张
        # 置于抽牌堆顶"——选最强牌正是正确语义，但它不是拿牌，不得计入
        # card_pick 污染信用账本（第 83 局实证：一局内头槌多次触发，暴走被
        # 记成 9 拿，卡牌学习数据的 picked/outcome_sum 被系统性灌水）
        top_of_pile = any(k in blob for k in ("抽牌堆", "弃牌堆", "牌堆顶", "置顶",
                                              "draw pile", "discard pile", "top of"))
        # 战斗中手牌强制选牌（kind=combat_hand_select）＝敌方献祭语义：
        # Vantom 每阶段结束强制从手牌交出一张（第 71 局 Boss 战五连献祭——
        # 通用"最高价值"分支把火焰屏障+×3、耸肩无视+×2 亲手喂给 Boss，
        # 伤口×2~3 在候选里却视而不见，防御核心被拆光后意图 26→32 磨死）。
        # 敌方强制的交牌永远交最不值钱者：状态牌 > 未升级基础牌 > 低价值牌。
        tribute = ("combat_hand" in kind) and not upgrading

        live_candidates = [c for c in cards if c["index"] not in self._sel_tried] or cards
        candidates = [card for card in live_candidates
                      if not self._ui_option_cooled(
                          state, "select_deck_card", card)]
        if not candidates:
            return self._cooldown_wait("选牌界面")

        def badness(c, for_removal=False):
            t = card_type(c).lower()
            if t == "curse":
                return 100
            if t == "status":
                return 90
            cid = (c.get("card_id") or "").upper()
            if "STRIKE" in cid and not c.get("upgraded"):
                return 50
            # 删牌语义扩展（第514~517批复盘）：未升级防御在打击之后、普通牌之前——
            # 防御技面值保底分(~8.7)让它们在拾取端持续注水（DEFEND 生涯 12848 次），
            # 而 junk 名单只认打击，防御臃肿永不可逆；输出饥饿主矛盾下，
            # 超出 min_block_cards 的冗余防御是「删掉最不心疼」的候选。
            # 仅付费删牌/变化生效，战斗献祭(tribute)不适用
            if for_removal and "DEFEND" in cid and not c.get("upgraded"):
                return 40
            return -self.eval_reward_card(c, [])

        explore_tag = None
        if removing or transforming:
            ranked_badness = [(badness(c, True), c) for c in candidates]
            pick = max(ranked_badness, key=lambda row: row[0])[1]
            verb = "删除" if removing else "变化"
            tag = "card_remove" if removing else "card_transform"
            reason = f"{verb}卡牌：【{pick.get('name')}】（最无价值）"
            self._trace_gate("GATE 选牌语义", "pass", f"{verb}：最大无价值度优先")
            for value, card in ranked_badness:
                self._trace_candidate(
                    card.get("name") or card.get("card_id"), value,
                    index=card.get("index"), action="select_deck_card",
                    why=f"{verb}无价值度")
        elif tribute:
            ranked_badness = [(badness(c), c) for c in candidates]
            pick = max(ranked_badness, key=lambda row: row[0])[1]
            tag = "card_sacrifice"
            reason = (f"战斗献祭：【{pick.get('name')}】（敌方强制交牌，交出最无价值者；"
                      f"候选：{' / '.join(c.get('name', '?') for c in candidates)}）")
            self._trace_gate("GATE 选牌语义", "warn", "敌方强制献祭：最大无价值度优先")
            for value, card in ranked_badness:
                self._trace_candidate(
                    card.get("name") or card.get("card_id"), value,
                    index=card.get("index"), action="select_deck_card",
                    why="战斗献祭无价值度")
        elif upgrading:
            # 锻造目标与卡组爆发缺口联动（第 106 局复盘）：爆发饥饿时升级
            # 攻击牌的优先级加倍——升级是免费的战力放大，缺输出的局面把砧
            # 让给防御/功能牌等于浪费整个篝火。
            # 饥饿线对账化（第423~428批复盘，_starve_line）：burst 高于静态带
            # 却远低于杀 Boss 所需的卡组旧口径判「非饥饿」，升级端对缺口失明
            # 成长引擎优先（第429~434批复盘新增）：输出饥饿或前夜竞速必败时，
            # 升级力量成长牌额外结构性加分。长战复利口径：点燃+每点力量对
            # 后续每刀全程加成，7 回合 Boss 战 ≈ +30 伤，高于多数单卡升级的
            # +3~6 面值；而旧评估 eval_reward_card(c, []) 里力量牌基础分 ~5-7，
            # 大攻击 ~20+，砧子永远落在攻击上（434 局前夜「可升级15张」仍无
            # 一台成型引擎）。门控在饥饿/必败局：走廊健康局面不扭曲既有节奏
            _up_deck = (state.get("run") or {}).get("deck", [])
            _up_mh = max(1, int(((state.get("run") or {}).get("max_hp", 1)) or 1))
            _up_floor = (state.get("run") or {}).get("floor")
            _up_act = self._floor_act(_up_floor)
            _up_starved = bool(_up_deck) and self.deck_effective_burst(_up_deck) < self._starve_line(_up_mh, act=_up_act)
            _up_doomed, _ = self._boss_race_doomed(
                _up_deck, _up_mh, floor=_up_floor,
                potions=((state.get("run") or {}).get("potions") or None))
            _atk_bonus = 4.0 if _up_starved else 2.0
            _scale_up_bonus = (float(self.know.policy.get("upgrade_scaling_power_bonus", 16.0))
                               if (_up_starved or _up_doomed) else 0.0)
            best, best_v = None, -1e9
            for c in candidates:
                if c.get("upgraded"):
                    continue
                # 真实卡组上下文（第514~517批复盘）：旧版传空卡组 []，攻击占比
                # 恒为中性 0.45、格挡稀缺与饥饿加分全部失效——与拿牌端第 33/34 局
                # 同型病灶。传入真实卡组后，饥饿局的高质攻击 +8~12 与占比衰减
                # 才能真实参与砧子分配
                v = self.eval_reward_card(c, _up_deck, max_hp=_up_mh,
                                          act=_up_act) + (_atk_bonus if is_attack(c) else 0.0)
                # 第470局批复盘：引擎加分只给触发条件可满足的成长牌——470 局
                # 零自残卡组里撕裂连续两次吃满 +16 引擎分上砧，两次锻造全废
                if (_scale_up_bonus > 0.0 and self._is_scaling_power(c)
                        and self._scaling_power_active(c, _up_deck)):
                    v += _scale_up_bonus
                self._trace_candidate(
                    c.get("name") or c.get("card_id"), v,
                    index=c.get("index"), action="select_deck_card",
                    why="升级目标价值（真实卡组上下文）")
                if v > best_v:
                    best, best_v = c, v
            if best is None:
                best = candidates[0]
            pick = best
            tag = "card_upgrade"
            self._trace_gate(
                "GATE 选牌语义", "pass",
                f"升级；输出饥饿={_up_starved}；竞速必败={_up_doomed}")
            reason = f"升级卡牌：【{pick.get('name')}】"
            if (_scale_up_bonus > 0.0 and self._is_scaling_power(pick)
                    and self._scaling_power_active(pick, _up_deck)):
                reason += f"（{'前夜竞速必败' if _up_doomed else '输出饥饿'}，优先升级成长引擎 +{_scale_up_bonus:.0f}）"
        else:
            # 必须用真实卡组上下文评估：第 34 局经此路径连拿 7 张全攻牌、
            # 第 33 局拿进基础【打击】——空卡组评估时攻击占比恒为中性 0.45，
            # 攻击乘法衰减与格挡稀缺增值双双失效
            deck = self._enrich_cards((state.get("run") or {}).get("deck", []))
            _mh = max(1, int(((state.get("run") or {}).get("max_hp", 1)) or 1))
            _sel_act = self._floor_act((state.get("run") or {}).get("floor"))
            scored = sorted(((self.eval_reward_card(c, deck, max_hp=_mh, act=_sel_act), c) for c in candidates),
                            key=lambda t: -t[0])
            for value, card in scored:
                self._trace_candidate(
                    card.get("name") or card.get("card_id"), value,
                    index=card.get("index"), action="select_deck_card",
                    why="选牌价值（真实卡组上下文）")
            best_v, pick = scored[0]
            pick_line = self._pick_threshold(deck, max_hp=_mh, act=_sel_act)
            _has_skip = "skip_reward_cards" in actions
            self._trace_gate(
                "GATE 动态拾取门槛", "pass" if (best_v >= pick_line or not _has_skip) else "reject",
                f"最高 {best_v:.2f} / 门槛 {pick_line:.2f}；可跳过={_has_skip}")
            self._trace_gate(
                "GATE 选牌语义", "pass",
                "牌堆顶选择" if top_of_pile else "自愿奖励" if _has_skip else "强制入组")
            if _has_skip:
                # 只有可跳过的通用选牌屏才是自愿奖励 offer。升级/删除/献祭/
                # 置顶均在前面的语义分支，不会污染 offered/seen。
                self._record_card_offer("CARD_SELECTION", state, cards)
            # 跳过守卫（第 56 局实证）：经"打开卡牌奖励"进入的本屏没有阈值判断，
            # 全负候选（未升级基础牌 -3.9/-6.2）也被硬塞进卡组稀释质量——
            # REWARD 端同场景会跳过，同一决策的两个入口必须共享同一套门槛
            # （第 65~66 局复盘：门槛升级为随卡组膨胀动态抬升）
            if best_v < pick_line and _has_skip \
                    and not self._thin_deck_must_pick(deck, best_v):
                return Decision("skip_reward_cards", {},
                                f"选牌界面：全部低于拾取门槛（最高 {best_v:.1f} < {pick_line:.1f}），跳过不拿",
                                tags=[("card_skip", None)], wait=0.8)
            explore_note = ""
            if _has_skip:
                # 到这里说明这份 offer 会被接受；探索候选也必须跨过真实拿牌线，
                # 单薄卡组的正价值保底则仍受 card_exploration_min_value 保护。
                _thin_take = self._thin_deck_must_pick(deck, best_v)
                _floor = 0.0 if _thin_take else pick_line
                best_v, pick, explore_note, explore_tag = self._reward_card_choice(
                    scored, deck, state, ctx, value_floor=_floor)
            # 强制入组屏识别（第529局批复盘）：无跳过动作且最高分低于自愿
            # 拾取门槛——选什么都非本意（知识恶魔战 F33 三连「瓦解/懒惰」屏
            # 实证，529 局被灌进 3 张瓦解），不得记 card_pick 学分：picked/
            # outcome 账与「本局拿牌」榜此前被此类强制屏系统性灌水
            if top_of_pile:
                tag = "card_top_pick"
            elif not _has_skip and best_v < pick_line:
                tag = "card_forced_add"
            else:
                tag = "card_pick"
            verb = "牌堆顶选择" if top_of_pile else "选择卡牌"
            detail = " / ".join(f"{c.get('name')}={v:.1f}" for v, c in scored)
            reason = (f"{verb}：【{pick.get('name')}】（价值 {best_v:.1f}）"
                      f"{explore_note}；候选：{detail}")

        tags = [(tag, pick.get("card_id")),
                ("selection_click", self._sel_instance, int(pick["index"]))]
        if explore_tag is not None:
            tags.append(explore_tag)
        self._trace_note("选牌轨迹只复制本次语义分支已经计算的价值，不会重新评价候选。")
        return Decision("select_deck_card", {"option_index": pick["index"]},
                        reason, tags=tags, wait=0.8)

    def _native_entity_text(self, category: str, item: dict, id_field: str) -> str:
        """Join live and immutable descriptions for conservative novelty gates."""
        chunks = [item.get("name"), item.get("description"), item.get(id_field)]
        native = getattr(self.know, "game_knowledge", None)
        if native is not None and getattr(native, "available", False):
            fact = native.lookup(category, item.get(id_field)) or {}
            runtime = fact.get("runtime") or {}
            chunks.extend((runtime.get("name"), runtime.get("description")))
        return " ".join(str(value or "") for value in chunks).lower()

    def _relic_exploration_safe(self, relic: dict, score: float) -> bool:
        """Reject explicit downside/trade-off relics from novelty selection."""
        learned = self.know.relic_value(relic.get("relic_id", ""))
        if learned < float(self.know.policy.get("relic_exploration_min_value", -0.5)):
            return False
        text = self._native_entity_text("relics", relic, "relic_id")
        downside_terms = (
            "cannot", "can't", "no longer", "lose ", "loses ", "curse",
            "无法", "不能", "不再", "失去", "诅咒", "减少你的", "降低你的",
        )
        return not any(term in text for term in downside_terms)

    def _relic_exploration_choice(self, scored: list[tuple[float, dict]],
                                  overall_best: float | None = None):
        """Return a deterministic near-best under-sampled relic, or ``None``.

        Ordering is independent of API slot order.  Learned value remains the safety
        boundary; novelty only breaks a near tie and can never promote an explicit
        drawback or a historically poor item.
        """
        pol = self.know.policy
        quota = max(0, int(pol.get("relic_exploration_run_quota", 1)))
        if (not pol.get("relic_exploration_enabled", True)
                or self._relic_explore_used >= quota or len(scored) < 2):
            return None
        cap = max(1, int(pol.get("relic_exploration_sample_cap", 1)))
        margin = max(0.0, float(pol.get("relic_exploration_near_best_margin", 0.75)))
        stable = sorted(scored, key=lambda row: (
            -row[0], str(row[1].get("relic_id") or row[1].get("name") or "")))
        greedy_score, greedy = stable[0]
        ceiling = greedy_score if overall_best is None else max(greedy_score, overall_best)
        greedy_id = str(greedy.get("relic_id") or greedy.get("name") or "")
        fresh = []
        for score, relic in scored:
            rid = str(relic.get("relic_id") or relic.get("name") or "")
            if not rid or rid == greedy_id or score < ceiling - margin:
                continue
            samples = max(
                self.know.novelty_trial_count("relic", rid),
                int((self.know.stats.get("relics", {}).get(rid) or {}).get("picked", 0) or 0),
            )
            if samples >= cap or not self._relic_exploration_safe(relic, score):
                continue
            fresh.append((samples, -score, rid, score, relic))
        if not fresh:
            return None
        samples, _, rid, score, relic = min(fresh)
        note = (f"；受控遗物探索：{rid} 样本 {samples}/{cap}，原值 {score:.2f}，"
                f"配额 {self._relic_explore_used + 1}/{quota}")
        return relic, score, note

    def _chest(self, state: dict, ctx) -> Decision:
        chest = state.get("chest") or {}
        actions = state.get("available_actions", [])
        if not chest.get("is_opened") and "open_chest" in actions:
            return Decision("open_chest", {}, "宝箱：开启", wait=1.0)
        live_relics = chest.get("relic_options", [])
        relics = [relic for relic in live_relics
                  if not self._ui_option_cooled(
                      state, "choose_treasure_relic", relic)]
        if (live_relics and not relics and not chest.get("has_relic_been_claimed")
                and "choose_treasure_relic" in actions):
            return self._cooldown_wait("宝箱")
        if relics and not chest.get("has_relic_been_claimed") and "choose_treasure_relic" in actions:
            scored = [(self.know.relic_value(r.get("relic_id", "")), r) for r in relics]
            scored.sort(key=lambda row: (
                -row[0], str(row[1].get("relic_id") or row[1].get("name") or "")))
            best_v, best = scored[0]
            explore = self._relic_exploration_choice(scored)
            note, tags = "", [("relic_pick", best.get("relic_id"))]
            if explore is not None:
                best, best_v, note = explore
                rid = str(best.get("relic_id") or best.get("name") or "")
                tags = [("relic_pick", best.get("relic_id")),
                        self._novelty_tag("relic", rid, self._relic_explore_used)]
            return Decision("choose_treasure_relic", {"option_index": best["index"]},
                            f"宝箱：选择遗物【{best.get('name')}】（价值 {best_v:.2f}）{note}",
                            tags=tags, wait=0.9)
        if "proceed" in actions:
            return Decision("proceed", {}, "宝箱：离开", wait=1.0)
        return Decision(None, {}, "宝箱：等待", wait=0.8)

    def _potion_exploration_choice(self, scored: list[tuple[float, dict]],
                                   run: dict, overall_best: float):
        """Choose one affordable unclassified potion through a bounded safe gate."""
        pol = self.know.policy
        quota = max(0, int(pol.get("potion_exploration_run_quota", 1)))
        if (not pol.get("potion_exploration_enabled", True)
                or self._potion_explore_used >= quota):
            return None
        # enough_gold 只代表买得起，不代表药水栏有空位。满槽时服务端会拒绝
        # buy_potion；若仍走探索，失败又不占样本/配额，就会在商店永久重试。
        potion_slots = run.get("potions") or []
        if potion_slots and all(slot.get("occupied") for slot in potion_slots):
            return None
        hp_pct = float(run.get("current_hp", 1) or 1) / max(
            1.0, float(run.get("max_hp", 1) or 1))
        if hp_pct < float(pol.get("potion_exploration_min_hp_pct", 0.55)):
            return None
        threshold = float(pol.get("shop_relic_threshold", 1.0))
        margin = max(0.0, float(pol.get("potion_exploration_near_best_margin", 0.5)))
        reference = max(threshold, overall_best if math.isfinite(overall_best) else threshold)
        cap = max(1, int(pol.get("potion_exploration_sample_cap", 1)))
        max_price = max(0, int(pol.get("potion_exploration_max_price", 60)))
        reserve = max(0, int(pol.get("potion_exploration_gold_reserve", 60)))
        gold = int(run.get("gold", 0) or 0)
        fresh = []
        for score, potion in scored:
            pid = str(potion.get("potion_id") or potion.get("name") or "")
            price = int(potion.get("price", 0) or 0)
            if (not pid or self._potion_class(potion) != "unknown"
                    or price > max_price or gold - price < reserve
                    or score <= 0.0 or score < reference - margin):
                continue
            text = self._native_entity_text("potions", potion, "potion_id")
            if any(term in text for term in (
                    "damage yourself", "lose ", "curse", "失去", "损失", "诅咒")):
                continue
            samples = self.know.novelty_trial_count("potion", pid)
            if samples < cap:
                fresh.append((samples, -score, pid, score, potion))
        if not fresh:
            return None
        samples, _, pid, score, potion = min(fresh)
        note = (f"受控新药试购：{pid} 样本 {samples}/{cap}，原值 {score:.2f}，"
                f"配额 {self._potion_explore_used + 1}/{quota}")
        return potion, score, note

    # ------------------------------------------------------------------
    # shop / rest
    # ------------------------------------------------------------------

    def _shop(self, state: dict, ctx) -> Decision:
        shop = state.get("shop") or {}
        run = state.get("run") or {}
        actions = state.get("available_actions", [])
        gold = run.get("gold", 0)
        deck = self._enrich_cards(run.get("deck", []))
        pol = self.know.policy
        floor = run.get("floor", 0)
        cooldown_blocked = False

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
            # 防御臃肿纳入删卡候选（第514~517批复盘）：junk 旧名单只认诅咒/状态/
            # 未升级打击，防御技在拾取端被面值保底分持续注水却永不可删——
            # DEFEND 生涯打出 12848 次、耸肩类拿 342 张。守卫：卡组格挡密度
            # 高于 min_block_cards 时才把未升级防御列为可删，防御底线不失守。
            _n_block = sum(1 for c in deck
                           if (is_skill(c) and card_numbers(c)[1] > 0)
                           or "DEFEND" in (c.get("card_id") or "").upper())
            junk = [c for c in deck if is_bad_card(c)
                    or ("STRIKE" in (c.get("card_id") or "").upper() and not c.get("upgraded"))
                    or ("DEFEND" in (c.get("card_id") or "").upper() and not c.get("upgraded")
                        and _n_block > float(pol.get("min_block_cards", 5)))]
            # 膨胀卡组的重复注水（第435~440批复盘）：旧 junk 判据只认诅咒/状态/
            # 未升级打击——打击升完或拿光后，31 张的臃肿卡组（本批 781P 局
            # 「可升级31张」）在商店永远不触发删牌，抽牌质量被同名三连稀释。
            # 软上限溢出≥2 时，同名第三张起视为注水纳入删除候选；具体删哪张
            # 仍由后续选牌屏的最无价值者排序决定（语义不变，只放宽付费资格）
            if deck:
                _ovf = self._deck_good_count(deck) - float(pol.get("deck_soft_cap", 20))
                if _ovf >= 2:
                    _copies: dict[str, int] = {}
                    for c in deck:
                        _bid = ((c.get("card_id") or "").upper().rstrip("+"))
                        _copies[_bid] = _copies.get(_bid, 0) + 1
                    junk = junk + [c for c in deck
                                   if _copies.get((c.get("card_id") or "").upper().rstrip("+"), 0) >= 3]
            if junk and "remove_card_at_shop" in actions:
                # 握手：下一个 CARD_SELECTION 屏就是删牌选择——不能依赖界面文案猜语义
                # （第 43/44 局实证：识别失败落入通用拿牌分支，付费删掉了余烬+/上勾拳
                #  两张全队最强的牌）
                if self._ui_action_cooled(state, "remove_card_at_shop", {}):
                    cooldown_blocked = True
                else:
                    return Decision("remove_card_at_shop", {},
                                    f"商店：付费删牌（预留 {pol['removal_gold_reserve']} 金后仍充足）",
                                    tags=[("shop_remove", None),
                                          ("shop_remove_pending", floor)], wait=0.9)

        # 卡牌购买与奖励端同门槛（第 96 局复盘）：F30 卡组已在软上限边缘，
        # 商店仍按固定阈值 1.0 买进净价值仅 3.0 的巨像等注水牌（73 金）——
        # 同一张牌在奖励端会因动态拾取门槛被拒。卡牌购买必须通过
        # max(动态拾取门槛, 商店基线)；遗物/药水不受卡组膨胀约束，维持原基线
        _shop_mh = max(1, int(run.get("max_hp", 1) or 1))
        _shop_act = self._floor_act(floor)
        shop_pick_line = max(float(pol["shop_relic_threshold"]),
                             self._pick_threshold(deck, max_hp=_shop_mh, act=_shop_act))
        best_action, best_score, best_reason, best_tags = None, -1e9, "", []
        for c in self._enrich_cards(shop.get("cards", [])):
            if not c.get("is_stocked") or not c.get("enough_gold"):
                continue
            v = self.eval_reward_card(c, deck, max_hp=_shop_mh, act=_shop_act) - c.get("price", 0) / 120.0
            if v <= shop_pick_line:
                self._trace_candidate(
                    c.get("name") or c.get("card_id"), v,
                    index=c.get("index"), action="buy_card", status="below_threshold",
                    why=f"净价值未越过卡牌门槛 {shop_pick_line:.2f}")
                continue
            if self._ui_option_cooled(state, "buy_card", c):
                cooldown_blocked = True
                self._trace_candidate(
                    c.get("name") or c.get("card_id"), v,
                    index=c.get("index"), action="buy_card", status="cooldown",
                    why="精确购买目标短冷却")
                continue
            self._trace_candidate(
                c.get("name") or c.get("card_id"), v,
                index=c.get("index"), action="buy_card",
                why=f"卡牌净价值；门槛 {shop_pick_line:.2f}")
            if v > best_score:
                best_action = ("buy_card", c["index"])
                best_score = v
                best_reason = f"购买卡牌【{c.get('name')}】（{c.get('price')}金，价值{v:.1f}≥门槛{shop_pick_line:.1f}）"
                best_tags = [("card_pick", c.get("card_id")), ("shop_buy_card", c.get("card_id"))]
        relic_scored = []
        for r in shop.get("relics", []):
            if not r.get("is_stocked") or not r.get("enough_gold"):
                continue
            v = 3.0 + self.know.relic_value(r.get("relic_id", "")) - r.get("price", 0) / 120.0
            if self._ui_option_cooled(state, "buy_relic", r):
                cooldown_blocked = True
                self._trace_candidate(
                    r.get("name") or r.get("relic_id"), v,
                    index=r.get("index"), action="buy_relic", status="cooldown",
                    why="精确购买目标短冷却")
                continue
            relic_scored.append((v, r))
            self._trace_candidate(
                r.get("name") or r.get("relic_id"), v,
                index=r.get("index"), action="buy_relic",
                why="遗物价值减价格成本")
            if v > best_score:
                best_action = ("buy_relic", r["index"])
                best_score = v
                best_reason = f"购买遗物【{r.get('name')}】（{r.get('price')}金，价值{v:.1f}）"
                best_tags = [("relic_pick", r.get("relic_id")), ("shop_buy_relic", r.get("relic_id"))]
        # 药水购买（第 248 批复盘）：货架药水此前完全不在评估范围——商店是
        # 药水的唯一稳定供给，而药水正是爆毙通道「没挡住」的执行端资源
        # （236 批交药线提前只解决了「何时喝」，没解决「有没有」）。防御/回复
        # 药按低血急需定价，攻击/增益药按爆发缺口定价，与遗物同池竞价、同门槛
        # 成交；enough_gold 已含空药水位校验（服务端口径），无需额外查栏位
        hp_pct = run.get("current_hp", 1) / max(1, run.get("max_hp", 1))
        # 输出饥饿判定接竞速及格线（第422局复盘，_starve_line 统一口径）；
        # 数据未成熟回落静态门槛
        potion_starved = bool(deck) and self.deck_effective_burst(deck) < self._starve_line(_shop_mh, act=_shop_act)
        # Boss 预留窗内进攻药竞价加成（第422局复盘）：饥饿卡组的 Boss 竞速是
        # 唯一胜机（386~390 批教义），但同池竞价里功能牌 6~9 分稳定压过药水
        # 基分 2~3 分——422 局商店路由理由明写「金币80够买药水档位」，到店却
        # 先花 39 金买了岩石铠甲，预算跌破药水档（60金）后空手离店。预留窗内
        # 给分类成功的进攻药一次性加价，保证「路由为买药进店」的预算不被截胡
        _reserve_bonus = 0.0
        if potion_starved:
            try:
                _sf = int(floor or 0)
            except (TypeError, ValueError):
                _sf = 0
            if (_sf > 0 and self._floors_to_boss(_sf)
                    <= int(pol.get("potion_starved_reserve_floors", 6))):
                _reserve_bonus = float(pol.get("shop_potion_reserve_bonus", 6.0))
        potion_scored = []
        for pt in shop.get("potions", []):
            if not pt.get("is_stocked") or not pt.get("enough_gold"):
                continue
            v = self._shop_potion_value(pt, hp_pct, potion_starved)
            if (_reserve_bonus > 0 and v > 0
                    and self._potion_class(pt) == "offensive"):
                v += _reserve_bonus
            if self._ui_option_cooled(state, "buy_potion", pt):
                cooldown_blocked = True
                self._trace_candidate(
                    pt.get("name") or pt.get("potion_id"), v,
                    index=pt.get("index"), action="buy_potion", status="cooldown",
                    why="精确购买目标短冷却")
                continue
            potion_scored.append((v, pt))
            self._trace_candidate(
                pt.get("name") or pt.get("potion_id"), v,
                index=pt.get("index"), action="buy_potion",
                why="药水价值减价格成本与预留修正")
            if v > best_score:
                best_action = ("buy_potion", pt["index"])
                best_score = v
                best_reason = f"购买药水【{pt.get('name')}】（{pt.get('price')}金，价值{v:.1f}）"
                best_tags = [("shop_buy_potion", pt.get("potion_id"))]

        market_best_score = best_score
        novelty_override_score = -math.inf
        # 遗物只在全货架最优值附近轮转；不会为了凑样本放弃显著更好的卡/药。
        if "buy_relic" in actions and relic_scored:
            explore_relic = self._relic_exploration_choice(
                relic_scored, overall_best=market_best_score)
            if explore_relic is not None:
                r, v, note = explore_relic
                if v > float(pol.get("shop_relic_threshold", 1.0)):
                    rid = str(r.get("relic_id") or r.get("name") or "")
                    best_action = ("buy_relic", r["index"])
                    best_score = v
                    novelty_override_score = v
                    best_reason = (f"购买遗物【{r.get('name')}】（{r.get('price')}金，"
                                   f"价值{v:.2f}）{note}")
                    best_tags = [("relic_pick", r.get("relic_id")),
                                 ("shop_buy_relic", r.get("relic_id")),
                                 self._novelty_tag("relic", rid, self._relic_explore_used)]

        # 新药试购可以在基线门槛下方至多让出 near-best_margin，但必须有空位
        # （enough_gold 的服务端口径）、买后余钱、健康血线和成功样本上限。
        if "buy_potion" in actions and potion_scored:
            explore_potion = self._potion_exploration_choice(
                potion_scored, run, overall_best=market_best_score)
            if explore_potion is not None and explore_potion[1] > novelty_override_score:
                pt, v, note = explore_potion
                pid = str(pt.get("potion_id") or pt.get("name") or "")
                best_action = ("buy_potion", pt["index"])
                best_score = max(v, float(pol.get("shop_relic_threshold", 1.0)) + 1e-6)
                best_reason = f"购买药水【{pt.get('name')}】（{pt.get('price')}金）；{note}"
                best_tags = [("shop_buy_potion", pt.get("potion_id")),
                             self._novelty_tag("potion", pid, self._potion_explore_used)]
        self._trace_gate(
            "GATE 商店成交门槛", "pass" if best_score > pol["shop_relic_threshold"] else "reject",
            f"最高 {best_score:.2f} / 基线 {float(pol['shop_relic_threshold']):.2f} / 卡牌线 {shop_pick_line:.2f}")
        self._trace_gate(
            "GATE 购买资格", "pass" if best_action else "neutral",
            f"金币 {gold}；冷却阻塞={cooldown_blocked}")
        self._trace_gate(
            "GATE 输出与药水预留", "warn" if potion_starved else "pass",
            f"输出饥饿={potion_starved}；进攻药加价={_reserve_bonus:.1f}")
        self._trace_note("商店候选均使用本次货架评估已经得到的净价值。")
        if best_action and best_score > pol["shop_relic_threshold"]:
            action, idx = best_action
            if action in actions:
                return Decision(action, {"option_index": idx}, f"商店：{best_reason}", tags=best_tags, wait=0.9)
            cooldown_blocked = True

        # A cooled purchase/removal is still an unresolved candidate.  Closing or
        # proceeding here would silently skip it before its short retry window
        # expires; wait, then re-evaluate the same live inventory.
        if cooldown_blocked:
            return self._cooldown_wait("商店")

        if shop.get("can_close") and "close_shop_inventory" in actions:
            return Decision("close_shop_inventory", {}, "商店：货架无值得购买，关闭",
                            tags=[("shop_close", floor)], wait=0.8)
        if "proceed" in actions:
            return Decision("proceed", {}, "商店：离开", wait=1.0)
        return Decision(None, {}, "商店：等待", wait=0.8)

    def _shop_potion_value(self, pt: dict, hp_pct: float, burst_starved: bool) -> float:
        """货架药水定价（第 248 批复盘）。

        货架载荷没有描述文本（仅 name/potion_id/rarity/usage/price），分类
        只能靠名称与 ID 关键词，与 _maybe_potion 的使用端分类同一套词表：
        - 防御/回复类：价值随失血加深——低血时它是下一场硬仗的命；
        - 攻击/增益类：爆发饥饿的卡组折价买下回合输出，成型卡组只给基线；
        - 无法分类：保守基线（宁缺毋滥，避免为未知效果挤占遗物预算）。
        统一减 price/120（与遗物同口径的金币机会成本）。
        """
        price = pt.get("price", 0) or 0
        cls = self._potion_class(pt)
        if cls == "defensive":
            base = 1.6 + 2.4 * (1.0 - hp_pct)
        elif cls == "offensive":
            base = 1.8 + (0.8 if burst_starved else 0.0)
        else:
            base = 1.2
        return base - price / 120.0

    def _potion_class(self, pt: dict) -> str:
        """货架药水分类（'defensive' | 'offensive' | 'unknown'）。

        第422局复盘从 _shop_potion_value 内联词表提取：预留窗竞价加成需要
        只对进攻/增益药生效，与使用端 _maybe_potion 的分类同一套词表。
        """
        # v0.111 API 的商店载荷常省略 description；优先从版本化原生快照补齐，
        # 只有 mod/新版本真正未知的药水才进入受控试购通道。
        blob = self._native_entity_text("potions", pt, "potion_id")
        if any(k in blob for k in ("格挡", "生命", "回复", "治疗", "屏障", "护甲",
                                   "block", "heal", "health", "regen", "barrier")):
            return "defensive"
        if any(k in blob for k in ("力量", "敏捷", "能量", "抽", "伤害", "攻击",
                                   "火焰", "毒", "雷", "爆炸", "能力",
                                   "strength", "dexterity", "energy", "draw",
                                   "damage", "attack", "fire", "poison",
                                   "lightning", "explosive", "power")):
            return "offensive"
        return "unknown"

    def _prepare_rest_decision(self, state: dict, decision: Decision) -> Decision:
        """Attach a legal target for native rest options that require one.

        Older API payloads opened a follow-up CARD_SELECTION screen for smithing,
        while native v0.111.0 rest options may expose their legal deck indices on
        the option itself.  Sending only ``option_index`` in the latter case is a
        deterministic 409, not an animation race.
        """
        option = self._ui_target_item(state, "choose_rest_option", decision.params)
        if not isinstance(option, dict) or not option.get("requires_target"):
            return decision
        valid = list(option.get("valid_target_indices") or [])
        if not valid:
            return Decision(None, {},
                            f"{decision.reason}；该项目要求目标但当前没有合法目标，等待刷新",
                            wait=0.7)

        def stable_target(value):
            try:
                return (0, int(value))
            except (TypeError, ValueError):
                return (1, str(value))

        valid.sort(key=stable_target)
        run = state.get("run") or {}
        deck = self._enrich_cards(run.get("deck", []))

        def same_index(card, raw) -> bool:
            try:
                return int(card.get("index")) == int(raw)
            except (TypeError, ValueError):
                return card.get("index") == raw

        target_cards = [(raw, next((card for card in deck if same_index(card, raw)), None))
                        for raw in valid]
        semantic = " ".join(str(option.get(key) or "") for key in
                            ("option_id", "title", "description")).lower()
        note = ""
        max_hp = max(1, int((run.get("max_hp", 1)) or 1))
        act = self._floor_act(run.get("floor"))
        if any(term in semantic for term in ("smith", "upgrade", "锻造", "升级")):
            candidates = [(raw, card) for raw, card in target_cards
                          if isinstance(card, dict) and not card.get("upgraded")]
            if candidates:
                target, card = max(
                    candidates,
                    key=lambda row: (
                        self.eval_reward_card(row[1], deck, max_hp=max_hp, act=act),
                        str(row[1].get("card_id") or row[1].get("name") or ""),
                        stable_target(row[0]),
                    ))
                note = f"；原生目标直选【{card.get('name') or card.get('card_id')}】"
            else:
                target = valid[0]
                note = "；升级语义未匹配到牌组条目，稳定选择首个合法目标"
        elif any(term in semantic for term in
                 ("remove", "purge", "transform", "删除", "移除", "变化")):
            candidates = [(raw, card) for raw, card in target_cards if isinstance(card, dict)]
            if candidates:
                target, card = min(
                    candidates,
                    key=lambda row: (
                        self.eval_reward_card(row[1], deck, max_hp=max_hp, act=act),
                        str(row[1].get("card_id") or row[1].get("name") or ""),
                        stable_target(row[0]),
                    ))
                note = f"；原生目标直选最低价值牌【{card.get('name') or card.get('card_id')}】"
            else:
                target = valid[0]
                note = "；移除语义未匹配到牌组条目，稳定选择首个合法目标"
        else:
            target = valid[0]
            note = "；目标语义未知，稳定选择服务端声明的首个合法目标"

        params = dict(decision.params or {})
        params["target_index"] = target
        return Decision(decision.action, params, decision.reason + note,
                        tags=list(decision.tags or []), wait=decision.wait)

    def _rest(self, state: dict, ctx) -> Decision:
        rest = state.get("rest") or {}
        run = state.get("run") or {}
        actions = state.get("available_actions", [])
        enabled_options = [o for o in rest.get("options", []) if o.get("is_enabled")]
        # Native rest options that require a target are not actionable until the
        # server exposes at least one legal target.  Filter them before strategic
        # ranking so a legal sibling can win instead of being masked by a preferred
        # but impossible smith/ritual option.
        live_options = [option for option in enabled_options
                        if (not option.get("requires_target")
                            or bool(option.get("valid_target_indices") or []))]
        if enabled_options and not live_options:
            return Decision(None, {},
                            "篝火：已启用项目均要求目标但当前没有合法目标，等待刷新",
                            wait=0.7)
        options = [option for option in live_options
                   if not self._ui_option_cooled(
                       state, "choose_rest_option", option)]
        if live_options and not options:
            return self._cooldown_wait("篝火")
        if not enabled_options:
            if "proceed" in actions:
                return Decision("proceed", {}, "篝火：无可选项目，离开", wait=1.0)
            return Decision(None, {}, "篝火：等待选项", wait=0.8)

        hp_pct = run.get("current_hp", 1) / max(1, run.get("max_hp", 1))
        max_hp = max(1, run.get("max_hp", 1))
        heal = next((o for o in options if o.get("option_id", "").upper() == "HEAL"), None)
        smith = next((o for o in options if "SMITH" in o.get("option_id", "").upper()), None)
        deck = self._enrich_cards(run.get("deck", []))
        upgradable = [c for c in deck if not c.get("upgraded")]
        heal_frac = self.know.policy.get("rest_heal_fraction", 0.30)
        pol = self.know.policy
        smith_ok = smith is not None and bool(upgradable)
        for option in options:
            self._trace_candidate(
                option.get("title") or option.get("option_id") or f"篝火 {option.get('index')}",
                None, index=option.get("index"), action="choose_rest_option",
                why="规则型候选，不伪造概率或分数")
        # Telemetry formatting is deliberately fail-open.  These values are only
        # copied for display; malformed optional config/context must never turn a
        # valid rest decision into a policy exception before the real rule chain
        # gets a chance to run.
        def _trace_float(value):
            try:
                parsed = float(value)
                return parsed if math.isfinite(parsed) else None
            except (TypeError, ValueError, OverflowError):
                return None

        _rest_smith_line = _trace_float(
            pol.get("smith_min_hp_pct", pol.get("rest_heal_threshold", 0.5)))
        _rest_projection = _trace_float(getattr(ctx, "rest_proj_hp_pct", None))
        _rest_dire_line = _trace_float(pol.get("rest_dire_proj_pct", 0.45))
        _rest_next_loss = _trace_float(
            getattr(ctx, "rest_next_fight_loss_frac", 0.0))
        _rest_smith_text = (f"当前 {hp_pct:.0%} / 锻造安全线 {_rest_smith_line:.0%}"
                            if _rest_smith_line is not None
                            else f"当前 {hp_pct:.0%} / 锻造安全线不可用")
        _rest_projection_display = (f"{_rest_projection:.0%}"
                                    if _rest_projection is not None else "—")
        _rest_next_loss_display = (f"{_rest_next_loss:.0%}"
                                   if _rest_next_loss is not None else "—")
        _rest_projection_text = (
            f"Boss入场投影={_rest_projection_display}；"
            f"前方连续战损={_rest_next_loss_display}")
        self._trace_gate(
            "GATE 当前生命线",
            ("neutral" if _rest_smith_line is None else
             "warn" if hp_pct < _rest_smith_line else "pass"),
            _rest_smith_text)
        self._trace_gate(
            "GATE 锻造资格", "pass" if smith_ok else "reject",
            f"锻造选项={smith is not None}；可升级牌={len(upgradable)}")
        self._trace_gate(
            "GATE 路径生存投影",
            ("neutral" if _rest_projection is None or _rest_dire_line is None else
             "warn" if _rest_projection < _rest_dire_line else "pass"),
            _rest_projection_text)
        self._trace_gate(
            "GATE Boss 前夜", "active" if getattr(ctx, "rest_before_boss", False) else "pass",
            f"前夜={bool(getattr(ctx, 'rest_before_boss', False))}")
        self._trace_note("篝火是规则直达决策：展示命中的稳定规则，不制造候选概率。")

        # Boss 前夜篝火：三区生存余量裁决（第 244 批复盘改版）。
        # 旧判据「场均战损 ≥ 回血量 且 血量 ≥ 锻造线 → 锻造」是方向性错误的边际
        # 分析：回血是篝火能提供的唯一确定性生存增量，判据不是「回血能否覆盖
        # 全场战损」，而是「回血能否把处决翻转成残血生还」。240~243 批实证：
        # 57%/66%/74%/80%/88% 五局前夜锻造后，分别以 0.4~7 点血量差被一幕 Boss
        # 处决——全部落在「回血即可翻盘」的翻转带内；同期唯一前夜回血的
        # 8VT5 局以 1% 血量生还。旧「0.65~1.00 带内入场血量证伪为非生死变量」
        # 是 n=8 的噪声结论（幸存者偏差），本批以翻转带处决差直接证伪。
        # 按悲观战损（场均 × boss_eve_pess_mult）分三区：
        #   溢出区：有效回血 <8% 血条（接近满血）→ 回血是无效投资，锻造
        #           （63 局满血被 85 点处决的教义在此保留：回血量为零才真无效）
        #   翻转带：不回血的预期余量（血量-悲观战损）≤ 安全余量 → 回血
        #   安全区：不回血也稳过悲观战损 且 血量 ≥ 锻造线 → 锻造投资未来
        if getattr(ctx, "rest_before_boss", False) and heal is not None and hp_pct < 0.95:
            _eve_act = self._floor_act(run.get("floor"))
            boss_loss, boss_n = self.know.boss_loss_stats(_eve_act)
            min_n = int(pol.get("boss_eve_smith_min_samples", 3))
            # 锻造线旋钮语义保留（安全区的血量门槛）：演化链胜利释放/证据接替
            # 照旧作用于它；地图端投影镜像（simulate 的 will_heal）同口径
            smith_line = min(float(pol.get("boss_eve_smith_hp_pct", 0.85)),
                             float(pol.get("boss_entry_evidence_hp_cap", 0.65)))
            heal_amount = heal_frac * max_hp * float(pol.get("boss_eve_smith_heal_mult", 1.0))
            cur_hp = float(run.get("current_hp", 0))
            pess = boss_loss * float(pol.get("boss_eve_pess_mult", 1.5))
            margin = float(pol.get("boss_eve_safe_margin_frac", 0.10)) * max_hp
            eff_heal = min(heal_amount, max_hp - cur_hp)
            if smith_ok and boss_n >= min_n and boss_loss >= heal_amount:
                if eff_heal < 0.08 * max_hp:
                    return Decision("choose_rest_option", {"option_index": smith["index"]},
                                    f"篝火：Boss 前夜溢出区改锻造（血量 {hp_pct:.0%} 接近满血，"
                                    f"有效回血仅{eff_heal:.0f}点<8%血条，回血无效投资）",
                                    tags=[("rest", "smith")], wait=1.2)
                # 竞速必败改锻造（第 397~402 批复盘）：满血进场也追不上击杀曲线的
                # 对局，升级缩短战斗是唯一可能翻盘的杠杆。
                # 第441~446批复盘修正：翻转带裁决（第244批）必须先于必败锻造。
                # 本批三局前夜坐在处决带内却被「必败改锻造」抢走回血后整管打空
                # （40%/60%/61% 进场分别掉 36/48/49，回血 +24 三局全部可活；
                # 另有一幕前夜 11% 上砧的极端样本）。带内不回血在任何执行下都是
                # 数学处决；必败局的伤害流到打死为止，回血同时最大化总输出与
                # 「投影误判翻盘率」，锻造的复利价值以「还有未来」为前提——
                # 必败判定本身否认了这个前提。两套教义各管一段：翻转带内回血至上，
                # 翻转带外维持必败上砧（60% 带外上砧胜一幕 Boss 的实证保留）
                _doomed, _doom_note = self._boss_race_doomed(
                    deck, max_hp, floor=run.get("floor"),
                    potions=run.get("potions") or None)
                if cur_hp - pess <= margin:
                    # 第664~674批复盘修正：悲观战损超过最大生命时（一幕 max80 vs
                    # pess≈91），「cur_hp-pess≤margin」对整个血条恒真，翻转带吞掉
                    # 「必败改锻造」教义使其沦为死代码。本批五局判死前夜全部照旧
                    # 回血，其中 668/671 两局回血后以 98%/100% 进场、掉 78/80 整管
                    # 打空——判死局的边际回血被实证为零。规则改为：判死且回血后
                    # 余量仍摸不到安全线时，回血既翻不了盘也改不了结局，锻造缩短
                    # 战斗是唯一杠杆；非判死或回血确有翻盘潜力的带内裁决不变
                    # （441~446 批三局带内回血生还的实证保留）
                    _post_margin = cur_hp + eff_heal - pess
                    if _doomed and _post_margin <= margin:
                        return Decision("choose_rest_option",
                                        {"option_index": smith["index"]},
                                        f"篝火：Boss 前夜必败弃疗改锻造（当前 {hp_pct:.0%}；"
                                        f"回血后预期余量{_post_margin:.0f}仍≤安全余量"
                                        f"{margin:.0f}（悲观战损{pess:.0f}=场均{boss_loss:.0f}"
                                        f"×{float(pol.get('boss_eve_pess_mult', 1.5)):.1f}），"
                                        f"回血买不到生还；{_doom_note}；本次可升级"
                                        f"{len(upgradable)}张，缩短战斗是唯一杠杆）",
                                        tags=[("rest", "smith")], wait=1.2)
                    _doom_tail = f"；竞速预演虽判必败（{_doom_note}），回血后有望越过悲观安全线" if _doomed else ""
                    return Decision("choose_rest_option", {"option_index": heal["index"]},
                                    f"篝火：Boss 前夜翻转带回血（当前 {hp_pct:.0%}；不回血预期余量"
                                    f"{cur_hp - pess:.0f}≤安全余量{margin:.0f}（悲观战损{pess:.0f}="
                                    f"场均{boss_loss:.0f}×{float(pol.get('boss_eve_pess_mult', 1.5)):.1f}）"
                                    f"{_doom_tail}，回血{eff_heal:.0f}点直接兑换生还率）",
                                    tags=[("rest", "heal")], wait=1.2)
                if _doomed:
                    return Decision("choose_rest_option", {"option_index": smith["index"]},
                                    f"篝火：Boss 前夜竞速必败改锻造（当前 {hp_pct:.0%}；{_doom_note}；"
                                    f"本次可升级{len(upgradable)}张，缩短战斗是唯一杠杆）",
                                    tags=[("rest", "smith")], wait=1.2)
                if hp_pct >= smith_line:
                    return Decision("choose_rest_option", {"option_index": smith["index"]},
                                    f"篝火：Boss 前夜安全区改锻造（血量 {hp_pct:.0%} ≥ 锻造线 "
                                    f"{smith_line:.0%}，且不回血预期余量{cur_hp - pess:.0f}>"
                                    f"安全余量{margin:.0f}——稳过悲观战损，升级投资未来）",
                                    tags=[("rest", "smith")], wait=1.2)
                return Decision("choose_rest_option", {"option_index": heal["index"]},
                                f"篝火：Boss 前夜优先回血（当前 {hp_pct:.0%}；余量达标但"
                                f"血量<锻造线{smith_line:.0%}，回血仍是有效投资）",
                                tags=[("rest", "heal")], wait=1.2)
            why_heal = (f"历史Boss战损{boss_loss:.0f}<回血量{heal_amount:.0f}或样本不足({boss_n})"
                        if boss_n < min_n or boss_loss < heal_amount
                        else "无锻造目标")
            return Decision("choose_rest_option", {"option_index": heal["index"]},
                            f"篝火：Boss 前夜优先回血（当前 {hp_pct:.0%}；{why_heal}）",
                            tags=[("rest", "heal")], wait=1.2)

        # 锻造区间：血量 ≥ smith_min_hp_pct 即可锻造。旧逻辑回血阈值 70% 过高，
        # 第 28 局连续两个篝火都在 46%/48% 回血、整局零锻造，卡组停在基础形态
        heal_line = float(pol.get("smith_min_hp_pct", pol["rest_heal_threshold"]))
        # 绝境投影回血（第 96 局复盘）：F22 篝火在 79% 血按常规线锻造，而地图端
        # 全路径投影早已给出「照此打下去进 Boss 仅 36%」的死局预警——随后 F23
        # -37、F31 被地图漏斗逼进强制精英 -68 阵亡。长线投资的前提是活到兑付日，
        # 投影绝望时回血优先于锻造；边际回复不足最大生命 8%（接近满血、回了个
        # 寂寞）时仍锻造，不浪费篝火
        dire_line = float(pol.get("rest_dire_proj_pct", 0.45))
        proj = getattr(ctx, "rest_proj_hp_pct", None)
        dire_gain = min(heal_frac * max_hp, max_hp - run.get("current_hp", 0))
        if (heal and smith_ok and proj is not None and proj < dire_line
                and hp_pct >= heal_line and dire_gain >= 0.08 * max_hp):
            return Decision("choose_rest_option", {"option_index": heal["index"]},
                            f"篝火：绝境投影优先回血（路径投影进Boss仅{proj:.0%}<{dire_line:.0%}，"
                            f"前路战损预期压倒锻造收益；本次可回复{dire_gain:.0f}点）",
                            tags=[("rest", "heal")], wait=1.2)
        # 锻造前预演（第 99~102 批复盘，第 370~371 局扩展为连战累计）：地图端
        # 已把「沿选中路径首个恢复节点之前的连续战斗期望战损合计」传来。放弃
        # 回血去锻造的前提是这段连战打完还站得住——99 局 61% 血在强制精英前夜
        # 锻造，精英 -49 正好处决（回血 +24 即可生还）；371 局 65% 血在双怪物
        # 前夜按单场账锻造，两连战 -32/-20 连环处决（回血 +24 即可全活）。
        # 若「当前血量 - 累计期望战损」跌破紧急线，先把血量垫回安全区再上砧。
        # 边际回复不足 8% 血条（接近满血）时不浪费篝火，维持锻造
        next_loss = float(getattr(ctx, "rest_next_fight_loss_frac", 0.0) or 0.0)
        urgent_line = float(pol.get("rest_urgent_hp_pct", 0.45))
        if (heal and smith_ok and hp_pct >= heal_line and next_loss > 0.0
                and hp_pct - next_loss < urgent_line
                and dire_gain >= 0.08 * max_hp):
            return Decision("choose_rest_option", {"option_index": heal["index"]},
                            f"篝火：锻造预演改回血（前方必经战斗期望战损合计{next_loss:.0%}，"
                            f"打完预计仅剩{hp_pct - next_loss:.0%}<紧急线{urgent_line:.0%}；"
                            f"先回血{heal_frac:.0%}垫安全区）",
                            tags=[("rest", "heal")], wait=1.2)
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
                if self._ui_option_cooled(state, "choose_event_option", proceed):
                    return self._cooldown_wait("事件")
                return Decision("choose_event_option", {"option_index": proceed["index"]},
                                "事件：已结束，继续", wait=1.0)

        live_candidates = [o for o in options
                           if not o.get("is_locked") and not o.get("will_kill_player")]
        if not live_candidates:
            live_candidates = [o for o in options if not o.get("is_locked")]
        if not live_candidates:
            return Decision(None, {}, "事件：全部锁定，等待", wait=0.8)
        candidates = [o for o in live_candidates
                      if not self._ui_option_cooled(
                          state, "choose_event_option", o)]
        if not candidates:
            return self._cooldown_wait("事件")

        # 事件实例身份切换时重置重复选择记忆（同实例重选 = 上次选择没解决问题）
        inst = (state.get("run_id"), event_id, (state.get("run") or {}).get("floor", 0))
        if self._event_inst != inst:
            self._event_inst = inst
            self._event_picks = {}

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

        def _lookup_worst(ev_id: str, key: str) -> float | None:
            # 最坏情况记忆的读取侧聚合（第 255~257 批次复盘）：与 _lookup 同
            # 口径跨页共享，取各键 hp_min 的最小者（任一页面留下过致死尾部，
            # 同语义选项都继承这份警惕）
            tail = key.split(".")[-1]
            worst = None
            for k in dict.fromkeys([key, tail]):
                w = self.know.event_option_worst(ev_id, k)
                if w is not None:
                    worst = w if worst is None else min(worst, w)
            return worst

        scored = []
        worst_by_key: dict[str, float | None] = {}
        for o in candidates:
            key = _norm_key(o)
            v, n = _lookup(event_id, key)
            worst_by_key[key] = _lookup_worst(event_id, key)
            repeats = self._event_picks.get(key, 0)
            if repeats:
                # 同实例重选停滞罚分（第 214 批复盘）：已选次数计入样本并倒扣价值，
                # 一次重选即让 -1 的已知选项反超 0 分的原地踏步选项
                n += repeats
                v -= 3.0 * repeats
            scored.append((v, n, key, o))
        all_event_scored = list(scored)
        # 最坏情况生存闸门（第 255~257 批次复盘新增）：事件价值是全局均值账，
        # 而「均值正收益、尾部能致死」的选项在低血量时是另一道题——7RJ9 局
        # 31% 血在茂密的植被选「休息」（均值 +10.5，n=8），被链内强制战 -55
        # 抬走（次层 F6 再 -25 阵亡）；同页「坚持跋涉」仅 -8 血本可生还。
        # 均值账永远看不见这条重尾，hp_min 尾部记忆（含事件链强制战的祖先
        # 归因样本）让做选择的那一环看见最坏情况：历史单次最差掉血超过
        # 当前血量（留 event_worst_margin_frac 余量）的选项，只要存在安全
        # 替代即出局；全员致死时保留原池强行择损（不制造无牌可出）
        my_hp = int((state.get("run") or {}).get("current_hp", 1) or 1)
        max_hp = max(1, int((state.get("run") or {}).get("max_hp", 1) or 1))
        _worst_margin = float(pol.get("event_worst_margin_frac", 0.05)) * max_hp
        veto_note = ""
        lethal_keys = set()
        lethal_descs = []
        lethal_veto_active = False
        for s in scored:
            _w = worst_by_key.get(s[2])
            if _w is not None and my_hp + _w <= _worst_margin:
                lethal_keys.add(s[2])
                lethal_descs.append(f"「{s[3].get('title')}」历史最差{_w:.0f}血")
        if lethal_keys:
            _safe_scored = [s for s in scored if s[2] not in lethal_keys]
            if _safe_scored:
                lethal_veto_active = True
                scored = _safe_scored
                veto_note = (f"；最坏情况闸门：{'、'.join(lethal_descs)}，"
                             f"当前{my_hp}血吃下即死，改选安全项")
            else:
                veto_note = (f"；最坏情况闸门：{'、'.join(lethal_descs)}，"
                             f"当前{my_hp}血吃下即死，但无安全替代，强行择损")
        for value, samples, key, option in all_event_scored:
            if key in lethal_keys:
                status = "vetoed" if lethal_veto_active else "forced_risk"
                why = f"历史最坏生命变化 {worst_by_key.get(key)}；样本 {samples}"
            else:
                status = "eligible"
                why = f"经验样本 {samples}"
            self._trace_candidate(
                option.get("title") or option.get("text_key") or key, value,
                index=option.get("index"), action="choose_event_option",
                status=status, why=why)
        self._trace_gate(
            "GATE 最坏情况生存", "warn" if lethal_keys else "pass",
            veto_note.lstrip("；") if veto_note else "无历史致死尾部")
        self._trace_gate(
            "RANK 事件经验价值", "pass", f"{len(scored)} 个闸门后候选")
        self._trace_note("事件候选分数与样本数直接来自本次经验账读取结果。")
        # 确定性欠采样探索：旧 epsilon 即使保留 5% 下限，也可能在稀有事件的
        # 有限次出现里永远不命中。现在只在高血、近优且通过上方 will_kill/hp_min
        # 重尾闸门的选项间按“样本最少→原值最高→稳定键”轮转；每局和每候选都
        # 有硬上限。显著负收益或明确灾难文案不会因新颖度复活。
        preview = sorted(scored, key=lambda s: (-s[0], -s[1], s[2]))
        if preview[0][0] > 0.0:
            greedy_preview = preview[0]
        else:
            tied = [s for s in preview if s[0] == preview[0][0]]
            greedy_preview = min(tied, key=lambda s: (s[1], s[2]))
        quota = max(0, int(pol.get("event_exploration_run_quota", 1)))
        hp_pct = my_hp / max_hp
        exploration_gate = (pol.get("event_exploration_enabled", True)
                            and self._event_explore_used < quota
                            and hp_pct >= float(pol.get("event_exploration_min_hp_pct", 0.70))
                            and not lethal_keys
                            and not any(s[3].get("will_kill_player") for s in scored))
        self._trace_gate(
            "GATE 受控探索", "active" if exploration_gate else "pass",
            f"生命 {hp_pct:.0%}；配额 {self._event_explore_used}/{quota}；致死尾部={bool(lethal_keys)}")
        if exploration_gate:
            cap = max(1, int(pol.get("event_exploration_sample_cap", 2)))
            margin = max(0.0, float(pol.get("event_exploration_near_best_margin", 2.0)))
            min_value = float(pol.get("event_exploration_min_value", -1.0))
            best_raw = max(s[0] for s in scored)
            fresh = []
            for v, n, key, o in scored:
                if key == greedy_preview[2] or v < min_value or v < best_raw - margin:
                    continue
                text = f"{o.get('title') or ''} {o.get('description') or ''}".lower()
                if any(term in text for term in (
                        "lose all", "失去所有", "损失所有", "become cursed",
                        "获得诅咒", "即死", "死亡")):
                    continue
                novelty_key = f"{event_id}:{key}"
                samples = max(n, self.know.novelty_trial_count("event", novelty_key))
                if samples < cap:
                    fresh.append((samples, -v, novelty_key, key, v, o))
            if fresh:
                samples, _, novelty_key, key, v, o = min(fresh)
                note = (f"样本 {samples}/{cap}，原值 {v:.2f}，最优 {best_raw:.2f}，"
                        f"配额 {self._event_explore_used + 1}/{quota}")
                return Decision(
                    "choose_event_option", {"option_index": o["index"]},
                    f"事件【{ev.get('title')}】：受控探索近优选项「{o.get('title')}」"
                    f"（{note}）{veto_note}",
                    tags=[("event_choice", event_id, key),
                          self._novelty_tag("event", novelty_key,
                                            self._event_explore_used)],
                    wait=1.0)
        # 有实证收益（>0）时：价值优先，平值按样本数优先（石炉加湿器教训：
        # 经验多比原始顺序可信）。全零平值反转（第 56~57 局实证）：事件结算只记
        # 即时 hp/gold，祝福类选项长期记 0——按样本最大排序会把选择永久锁死在
        # 首个采样过的选项上，「涅奥的苦痛」n=8 连续重选，营养牡蛎(+11/次)式的
        # 正收益选项永远等不到被发现。并列 0 时改选样本最少者主动分散采样；
        # 任一选项显现非零收益后自动恢复"价值→样本"贪心。
        v, n, key, o = greedy_preview
        scored.sort(key=lambda s: (-s[0], -s[1], s[2]))
        lines = " / ".join(f"{s[3].get('title')}={s[0]:.1f}(n={s[1]})" for s in scored)
        return Decision("choose_event_option", {"option_index": o["index"]},
                        f"事件【{ev.get('title')}】：选择「{o.get('title')}」（经验价值 {v:.1f}）；{lines}{veto_note}",
                        tags=[("event_choice", event_id, key)], wait=1.0)

    def _crystal_sphere(self, state: dict, ctx) -> Decision:
        """水晶球占卜小游戏（CRYSTAL_SPHERE）。

        机制（游戏源码实证）：11x11 雾格，每次点格消耗 1 次占卜（大占卜清 3x3，
        小占卜清 1 格，费用相同）；物品占多格，全格清开即揭示并在结束时发放——
        包括诅咒；占卜次数必须全部用完才会出现 proceed。
        策略：贪心最大化"新清开的好物格"，绝不点完坏物品的剩余格；
        无利可图时用小占卜点已清开的格子安全空耗次数。
        """
        actions = state.get("available_actions", [])
        cs = state.get("crystal_sphere") or {}
        if cs.get("is_finished") or "crystal_clear_cell" not in actions:
            if "proceed" in actions:
                return Decision("proceed", {}, "占卜：完成，继续", wait=1.0)
            return Decision(None, {}, "占卜：等待界面就绪", wait=0.8)

        w, h = cs.get("grid_width", 11), cs.get("grid_height", 11)
        hidden = {(c[0], c[1]) for c in cs.get("hidden_cells", [])}
        good_hidden: set = set()
        bad_sets: list = []
        for it in cs.get("items", []):
            hs = {(c[0], c[1]) for c in it.get("hidden_cells", [])}
            if not hs:
                continue
            if it.get("is_good"):
                good_hidden |= hs
            else:
                bad_sets.append(hs)

        def completes_bad(newly: set) -> bool:
            # 本次点击若覆盖某坏物品的全部剩余隐藏格 → 揭示诅咒，禁止
            return any(hs and hs <= newly for hs in bad_sets)

        def big_area(cx: int, cy: int) -> set:
            return {(x, y) for x in range(cx - 1, cx + 2) for y in range(cy - 1, cy + 2)
                    if 0 <= x < w and 0 <= y < h}

        best = None  # (score, tool, cell)  score=(好物新格, -触及坏格, 总新格)
        for cx in range(w):
            for cy in range(h):
                newly = {c for c in big_area(cx, cy) if c in hidden}
                if not newly or completes_bad(newly):
                    continue
                score = (len(newly & good_hidden),
                         -len(newly & set().union(*bad_sets)) if bad_sets else 0,
                         len(newly))
                if best is None or score > best[0]:
                    best = (score, "big", (cx, cy))
        for cell in hidden:
            newly = {cell}
            if completes_bad(newly):
                continue
            score = (1 if cell in good_hidden else 0, 0, 1)
            if best is None or score > best[0]:
                best = (score, "small", cell)

        if best and best[0][0] > 0:
            (gain, _, total), tool, (cx, cy) = best
            return Decision("crystal_clear_cell", {"x": cx, "y": cy, "tool": tool},
                            f"占卜：{tool}点({cx},{cy})，新清{total}格其中好物{gain}格"
                            f"（剩{cs.get('divinations_left')}次）", wait=1.2)

        # 无好物可揭：点已清开的格子空耗剩余次数（绝不碰坏物品）
        clear_cells = [(x, y) for x in range(w) for y in range(h) if (x, y) not in hidden]
        if clear_cells:
            sx, sy = clear_cells[0]
            return Decision("crystal_clear_cell", {"x": sx, "y": sy, "tool": "small"},
                            f"占卜：无利可图，空点({sx},{sy})安全消耗次数"
                            f"（剩{cs.get('divinations_left')}次）", wait=1.2)
        return Decision(None, {}, "占卜：无可行动格子，等待", wait=0.8)

    def _bundle(self, state: dict, ctx) -> Decision:
        """开局祝福/特殊界面的卡牌包选择（BUNDLE_SELECTION）。"""
        bundles = state.get("bundles") or []
        actions = state.get("available_actions", [])
        deck = self._enrich_cards((state.get("run") or {}).get("deck", []))
        if bundles and "choose_bundle" in actions:
            _mh = max(1, int(((state.get("run") or {}).get("max_hp", 1)) or 1))
            best, best_v, detail = None, -1e9, []
            for b in bundles:
                bundle_cards = self._enrich_cards(b.get("cards", []))
                v = sum(self.eval_reward_card(c, deck, max_hp=_mh) for c in bundle_cards)
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
            # 第 109 局实证：F9 顶石界面把翻页键「LeftArrow」当选项点掉。
            # 优先继续/确认类字样，箭头/返回类排最后，其余居中；平局保序回退首项
            def _opt_rank(o):
                line = str(o.get("line") or "")
                if any(k in line for k in ("继续", "确认", "前进", "Continue", "Proceed", "Confirm")):
                    return 2
                if any(k in line.lower() for k in ("arrow", "back", "左", "右", "返回")):
                    return 0
                return 1
            pick = max(options, key=_opt_rank)
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
            return Decision("return_to_main_menu", {}, "结算：返回主菜单，备战下一局",
                            tags=[("timeline_check", True)], wait=1.5)
        if "proceed" in actions:
            return Decision("proceed", {}, "结算：继续", wait=1.2)
        return Decision(None, {}, "结算：等待", wait=0.8)

    def _click_game_point(self, fx: float = 0.5, fy: float = 0.87) -> bool:
        """真实鼠标点击游戏窗口内相对坐标（解锁/提示屏确认按钮的兜底手段）。"""
        try:
            import ctypes
            from ctypes import wintypes
            u32 = ctypes.windll.user32
            hwnd = u32.FindWindowW(None, "Slay the Spire 2")
            if not hwnd:
                return False
            rect = wintypes.RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(rect))
            x = rect.left + int((rect.right - rect.left) * fx)
            y = rect.top + int((rect.bottom - rect.top) * fy)
            u32.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            u32.SetCursorPos(x, y)
            time.sleep(0.06)
            u32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
            time.sleep(0.08)
            u32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
            return True
        except Exception:
            return False
        finally:
            # This fallback must focus the game to deliver the click, but that
            # promotion can put the game ahead of ASCEND-VISION in the
            # TOPMOST band. Repair only the viewer z-order afterwards.
            try:
                reassert_viewer_topmost()
            except Exception:
                pass

    def _unlock_screen(self, state: dict, ctx) -> Decision:
        """新内容解锁展示屏（新遗物/新卡等，mod UNLOCK 路由 + confirm_unlock 动作）。"""
        unlock = state.get("unlock") or {}
        items = "、".join(unlock.get("items") or [])
        actions = state.get("available_actions", [])
        if "confirm_unlock" in actions:
            self._unlock_stall = 0
            label = f"【{items}】" if items else ""
            return Decision("confirm_unlock", {}, f"解锁新内容{label}，确认收下", wait=1.2)
        # 双保险：曾出现 mod 已识别 NUnlockRelicsScreen，但因私有基类字段反射
        # 漏查而永久给出 can_confirm=false/actions=[]。不要把已识别的 UNLOCK
        # 排除在 UNKNOWN 鼠标兜底之外；连续观察后点击画面底部中央的确认按钮。
        self._unlock_stall += 1
        if self._unlock_stall >= 12:
            self._unlock_stall = 0
            clicked = self._click_game_point(0.5, 0.89)
            probe = (f"type={unlock.get('unlock_type') or 'unknown'}, "
                     f"can_confirm={unlock.get('can_confirm')}, actions={actions}")
            return Decision(None, {},
                            f"解锁界面 API 长时间无确认动作（{probe}），"
                            f"鼠标兜底点击{'已发送' if clicked else '失败'}",
                            wait=1.5)
        return Decision(None, {},
                        f"解锁界面：等待确认按钮就绪（{self._unlock_stall}/12；"
                        f"type={unlock.get('unlock_type') or 'unknown'}；"
                        f"can_confirm={unlock.get('can_confirm')}；actions={actions}）",
                        wait=0.8)

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
            return Decision("confirm_modal", {}, "未知界面：确认弹窗", wait=0.7)
        if "proceed" in actions:
            return Decision("proceed", {}, "未知界面：尝试继续", wait=0.8)
        # 无任何可用动作的界面（如"解锁遗物！"这类展示屏，mod 未路由）：
        # 滞留 12 tick 后兜底点击屏幕底部中央（这类屏的确认按钮都在那里）
        self._unknown_stall += 1
        if self._unknown_stall >= 12:
            self._unknown_stall = 0
            if self._click_game_point(0.5, 0.87):
                return Decision(None, {}, "未知界面：无可用动作，点击底部确认按钮区域兜底", wait=1.5)
        return Decision(None, {}, f"未知界面（{state.get('screen')}）：观察中（{self._unknown_stall}/12）", wait=1.0)
