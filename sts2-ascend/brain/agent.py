"""Main autonomous loop.

反复游玩 → 局势分析（每次决策打印中文局势摘要）→ 自我总结进化（每局结束 reflect）→
胜利后提升进阶继续进发。

Usage:  py -m brain            (from sts2-ascend/ directory)
"""
from __future__ import annotations

import copy
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from character_profiles import CharacterProfile, ProfileStore
from character_rotation import (CharacterRotation, CharacterRotationError,
                                canonical_character_id)
from client import ApiError, ConnectionDown, Sts2Client
from decision_trace import ensure_decision_trace
from knowledge import Knowledge
from lifecycle import (mark_pid_stage, pid_file, read_git_head, request_stop,
                       stop_requested, wait_for_stop)
from live_dashboard import LiveDashboardPublisher
from manual_control import (BrainControlPaused, PAUSE_HOTKEY, RESUME_HOTKEY,
                            read_control_state)
from policy import Decision, Policy
from reflect import finalize_run

try:
    from dashboard_launcher import start_dashboard_supervisor
except Exception:  # dashboard is optional and must never block gameplay startup
    start_dashboard_supervisor = None

try:
    import llm_review
except Exception:  # LLM 复盘是可选模块，导入失败不影响游玩
    llm_review = None

try:
    import autogit
except Exception:
    autogit = None

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
CONFIG_PATH = BASE_DIR / "brain" / "config.json"
_LOG_PATH = KNOWLEDGE_DIR / "brain.log"
REVIEW_HEALTHY_RUNS = 2


def log(msg: str = "") -> None:
    """Print to console AND append to knowledge/brain.log in UTF-8 (no shell redirection mojibake)."""
    line = str(msg)
    try:
        print(line, flush=True)
    except Exception:
        pass  # headless (no console) — file logging below is the real channel
    try:
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass

DEFAULT_CONFIG = {
    "api_ports": [8080, 8081, 8082, 8083, 8084],
    "game_exe": r"G:\SteamLibrary\steamapps\common\Slay the Spire 2\launch_vulkan.bat",
    "game_process_hint": "SlayTheSpire2",
    "poll_interval": 0.6,
    "action_settle": 0.5,
    "watchdog_escalate_after": 25,   # identical states before trying proceed/modal
    "watchdog_abandon_after": 90,    # identical states before abandoning the run
    "max_runs": 0,                   # 0 = play forever
    "seed": None,                    # fixed rng seed for reproducible exploration
    "viewer": {"enabled": True, "supervise_interval_sec": 2.0},
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            log(f"[warn] config.json 解析失败，使用默认配置")
    return cfg


def _event_reward_sig(run: dict) -> tuple:
    """事件奖励签名（第 372~373 局批次复盘）：(遗物 id 元组, 占用药水槽数)。

    佩尔/特兹卡塔拉/木雕这类「给遗物」的事件此前在结算账本上全是 0.0——
    账本只认 hp/gold/card，而遗物断供恰是当前版本输出不足的上游病因之一。
    选择时记下签名、结算时做差，遗物/药水收益从此入账。
    run 载荷缺 relics/potions 键（旧服务端/测试桩）时按空处理。
    """
    relic_ids = tuple(sorted(str(r.get("relic_id") or "")
                             for r in (run.get("relics") or []) if isinstance(r, dict)))
    potion_slots = sum(1 for p in (run.get("potions") or [])
                       if isinstance(p, dict) and p.get("occupied"))
    return relic_ids, potion_slots


def _reward_delta(old_sig: tuple, new_sig: tuple) -> tuple:
    """签名差值 → (净增遗物数, 净增药水槽数)。替换（换遗物）按数量差近似。"""
    old_ids, new_ids = set(old_sig[0]), set(new_sig[0])
    return (len(new_ids - old_ids) - len(old_ids - new_ids),
            new_sig[1] - old_sig[1])


# Only these run-level facts are consumed again at final reflection.  ``credit_tags``
# is also an in-process handshake stream (novelty trials, selection clicks, combat
# commits, reward attempts, ...); persisting that whole stream would replay volatile
# side effects after a brain restart.
_DURABLE_ATTRIBUTION_KINDS = frozenset({"card_pick", "relic_pick", "map_node"})

# Rich traces are useful review evidence, but persisting one for every card click
# multiplies a run log several times over.  Keep them at the decisions where the
# policy commits a turn or a run-level strategic choice.  Every successful action
# still keeps its compact action/params/reason row below.
_DURABLE_DECISION_TRACE_ACTIONS = frozenset({
    "end_turn",
    "use_potion",
    "choose_map_node",
    "choose_event_option",
    "choose_rest_option",
    "choose_reward_card",
    "skip_reward_cards",
    "select_deck_card",
    "buy_card",
    "buy_relic",
    "buy_potion",
})


def _durable_attribution_tags(raw_tags) -> list[tuple]:
    """Validate the small, replay-safe subset stored in incremental run logs."""
    result: list[tuple] = []
    for raw in raw_tags or []:
        if (not isinstance(raw, (tuple, list)) or len(raw) < 2
                or raw[0] not in _DURABLE_ATTRIBUTION_KINDS):
            continue
        result.append(tuple(raw))
    return result


def _decision_log_entry(state: dict, decision, *, timestamp: str | None = None) -> dict:
    """Build bounded, replay-safe evidence for one accepted action.

    Old run logs only carried ``action/params/reason``.  That is enough to know
    what happened, but not enough to diagnose the expensive failure mode where
    the policy ends a turn while energy and playable cards remain.  Combat rows
    now also keep turn/energy; an ``end_turn`` row keeps the bounded hand and
    intent snapshot plus the already-computed display trace.  Strategic choices
    keep that trace as well, while routine card clicks remain compact.
    """
    run = state.get("run") or {}
    combat = state.get("combat") or {}
    player = combat.get("player") or {}
    screen = state.get("screen", "UNKNOWN")
    hp = run.get("current_hp", player.get("current_hp"))
    gold = run.get("gold")
    entry = {
        "t": timestamp or time.strftime("%H:%M:%S"),
        "screen": screen,
        "floor": run.get("floor", 0),
        "hp": hp,
        "gold": gold,
        "action": decision.action,
        "params": decision.params,
        "reason": decision.reason,
    }

    if screen == "COMBAT":
        turn = state.get("turn")
        energy = player.get("energy")
        if turn is not None:
            entry["turn"] = turn
        if energy is not None:
            entry["energy"] = energy

    if decision.action not in _DURABLE_DECISION_TRACE_ACTIONS:
        return entry

    ensure_decision_trace(state, decision)
    trace = getattr(decision, "trace", None)
    if isinstance(trace, dict):
        selected = dict(trace.get("selected") or {})
        # ``entry.reason`` is canonical; do not store the same long sentence in
        # selected.reason and explanation again.  Preserve any genuinely distinct
        # builder notes because they often explain a gate or ranking tie.
        selected.pop("reason", None)
        explanation = [value for value in (trace.get("explanation") or [])
                       if value and value != decision.reason][:4]
        entry["trace"] = {
            "observation": copy.deepcopy(trace.get("observation") or {}),
            "gates": copy.deepcopy(list(trace.get("gates") or [])[:32]),
            "candidates": copy.deepcopy(list(trace.get("candidates") or [])[:8]),
            "selected": selected,
        }
        if explanation:
            entry["trace"]["explanation"] = copy.deepcopy(explanation)

    if screen == "COMBAT" and decision.action == "end_turn":
        incoming = 0
        for enemy in combat.get("enemies") or []:
            if not isinstance(enemy, dict) or not enemy.get("is_alive", True):
                continue
            for intent in enemy.get("intents") or []:
                if not isinstance(intent, dict):
                    continue
                try:
                    incoming += int(intent.get("total_damage") or 0)
                except (TypeError, ValueError):
                    pass
        hand = []
        for position, card in enumerate(combat.get("hand") or []):
            if not isinstance(card, dict) or len(hand) >= 12:
                continue
            card_evidence = {
                "index": card.get("index", position),
                "card_id": card.get("card_id"),
                "name": card.get("name"),
                "card_type": card.get("card_type"),
                "energy_cost": card.get("energy_cost"),
                "playable": card.get("playable"),
                "requires_target": card.get("requires_target"),
                "valid_target_indices": list(card.get("valid_target_indices") or [])[:8],
                "why_not_playable": card.get("why_not_playable")
                    or card.get("disabled_reason"),
            }
            hand.append({key: value for key, value in card_evidence.items()
                         if value is not None and value != []})
        entry["turn_end_state"] = {
            "block": player.get("block"),
            "incoming_damage": incoming,
            "available_actions": [str(value)
                                  for value in (state.get("available_actions") or [])[:32]],
            "hand": hand,
        }
    return entry


@dataclass
class RunContext:
    """Per-run tracking for credit assignment and reflection."""
    run_id: str = "run_unknown"
    ascension: int = 0
    started_at: str = ""
    run_number: int = 0                      # 生涯序号；异步复盘按批精确取证
    profile_id: str = ""
    character_id: str = ""
    profile_run_number: int = 0
    credit_tags: list = field(default_factory=list)   # ("card_pick", id) etc.
    attribution_tags: list = field(default_factory=list)  # durable run-end facts only
    decisions: list = field(default_factory=list)     # full decision log
    combat: dict | None = None                        # active combat tracker
    combat_agg: dict | None = None                    # 同层多段战斗聚合账（第 97~98 批复盘）
    combat_notes: list = field(default_factory=list)
    pending_event: tuple | None = None                # (event_id, option_key, hp_before, gold_before, floor, deck_size_before, relic_ids, potion_slots)
    pending_event_own: tuple | None = None            # (hp, gold) 事件自身即时效果快照：离开事件屏瞬间采样（106 局复盘）
    event_chain: list = field(default_factory=list)   # 同事件内已先行结算的祖先选项 [(event_id, key)]（第 237~238 批复盘）
    pending_event_fight_loss: float = 0.0             # 事件触发战斗的掉血暂存（死亡时战斗账先于事件账落库）
    died_in_combat: dict | None = None                # set when the run ended inside a combat
    died_to_event: tuple | None = None                # (event_id, option_key) when an event killed us
    combat_bridge: tuple | None = None                # (comp_id, floor, ts) 转阶段过场挂起标记
    last_hp: int = 0
    last_gold: int = 0
    rests_healed_at_full: int = 0
    death_hp_pct_at_entry: float | None = None
    death_was_elite: bool = False
    current_combat_is_hard: bool = False
    run_finalized: bool = False
    finalize_requested: bool = False
    # Reflection mutates the in-memory profile before the three durable terminal
    # artifacts (run log, profile state, rotation ledger) are published.  Retain
    # that exact once-applied result across a transient write failure so the next
    # GAME_OVER poll can retry persistence without applying learning twice.
    pending_terminal_persistence: dict | None = None
    rest_before_boss: bool = False   # 本次地图选择指向 Boss 前夜的篝火（_rest 消费）
    rest_proj_hp_pct: float | None = None
    rest_next_fight_loss_frac: float = 0.0
    check_timeline: bool = False
    timeline_tried: set = field(default_factory=set)
    # Stall-analysis state is combat-scoped.  These are declared fields instead of
    # dynamic attributes so reset_for() reliably overwrites them at every new run.
    stall_analysis_asked: bool = False
    stall_analysis_needed: bool = False
    stall_giveup: bool = False
    force_giveup: bool = False
    force_offense: bool = False
    stall_grind_grace: bool = False
    # A review marker may advance only for a run that began after this Brain
    # observed a genuine between-run screen. A mid-run reconnect validates only
    # the tail of that run and must keep rollback protection intact.
    review_health_eligible: bool = False
    # A run touched while the global stop hotkey owns control is a mixed human/AI
    # sample.  Keep its partial audit trail, but never feed its terminal floor,
    # choices or outcome into autonomous balance statistics or LLM review.
    human_assisted: bool = False

    def reset_for(self, run_id: str, ascension: int, run_number: int = 0):
        self.__init__(run_id=run_id, ascension=ascension, run_number=run_number,
                      started_at=time.strftime("%Y-%m-%d %H:%M:%S"))


class Agent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.client = Sts2Client(ports=cfg["api_ports"])
        self.rng = random.Random(cfg["seed"]) if cfg.get("seed") is not None else random.Random()
        self.profile_store = ProfileStore(KNOWLEDGE_DIR)
        self.rotation = CharacterRotation.from_knowledge_root(KNOWLEDGE_DIR)
        self._profile_knowledge: dict[str, Knowledge] = {
            profile.profile_id: Knowledge(profile)
            for profile in self.profile_store.profiles
        }
        self._profile_policies: dict[str, Policy] = {
            profile_id: Policy(know, self.rng, character_rotation=self.rotation)
            for profile_id, know in self._profile_knowledge.items()
        }
        self.active_profile = self.profile_store.ironclad
        self.know = self._profile_knowledge[self.active_profile.profile_id]
        self.policy = self._profile_policies[self.active_profile.profile_id]
        self.ctx = RunContext()
        self.last_sig = None
        self.same_count = 0
        self.runs_played = 0
        self.request_restart = False  # llm_review 改了代码后置位，回到主菜单时自重启
        self._last_policy_refresh = 0.0  # 策略热同步节流（第 123~124 局复盘）
        self._boot_head = ""  # Runner 在模块加载前冻结；测试构造 Agent 不访问 Git
        self._boot_review_commit = ""  # 与本进程代码同时冻结的 rollback marker
        self._boot_head_thread: threading.Thread | None = None  # legacy test compatibility
        self._review_health_ready_for_new_run = False
        self._ambiguous_action = None  # response-lost POST awaiting next-state reconciliation
        self._api_race_retry = None  # repeated refresh races, diagnostic only
        self.live_dashboard: LiveDashboardPublisher | None = None
        self.dashboard_supervisor = None
        initial_control = read_control_state()
        self._manual_pause_active = False
        self._manual_run_ids: set[str] = set()
        # An enabled inherited session has already acknowledged its prior pause
        # epochs.  A child born while paused must still observe the current epoch.
        self._seen_pause_generation = (
            initial_control.pause_generation if initial_control.enabled
            else max(0, initial_control.pause_generation - 1))
        self._recover_persisted_terminal_rotation()

    def _activate_profile(self, profile: CharacterProfile) -> None:
        """Expose one character's paired Knowledge/Policy as the active runtime."""
        knowledge = getattr(self, "_profile_knowledge", {}).get(profile.profile_id)
        policies = getattr(self, "_profile_policies", {})
        policy = policies.get(profile.profile_id)
        if knowledge is None or policy is None:
            # Compatibility for lightweight tests and older construction helpers:
            # normal Agent instances eagerly own both profile runtimes.
            knowledge = Knowledge(profile)
            policy = Policy(
                knowledge, getattr(self, "rng", None),
                character_rotation=getattr(self, "rotation", None))
            self._profile_knowledge = dict(
                getattr(self, "_profile_knowledge", {}),
                **{profile.profile_id: knowledge})
            self._profile_policies = dict(
                getattr(self, "_profile_policies", {}),
                **{profile.profile_id: policy})
        self.active_profile = profile
        self.know = knowledge
        self.policy = policy

    def _recover_persisted_terminal_rotation(self) -> bool:
        """Finish a terminal rotation publication interrupted by process death.

        ``_finalize`` writes the final run log and character profile before it
        calls ``record_terminal``.  A crash in that narrow window loses only the
        process-local retry object, while the durable rotation ledger still owns
        an active run.  Recover exclusively from that exact active identity and
        require both final-log shape and the matching profile run count.  Any
        missing, malformed, in-progress, or human-assisted evidence leaves the
        active slot untouched (fail closed).
        """
        rotation = getattr(self, "rotation", None)
        store = getattr(self, "profile_store", None)
        if rotation is None or store is None:
            return False
        try:
            snapshot = rotation.snapshot()
        except (CharacterRotationError, OSError, ValueError) as exc:
            log(f"[agent] 跨进程终局恢复无法读取轮换状态，保持阻塞：{exc}")
            return False

        run_id = str(snapshot.active_run_id or "").strip()
        character_id = str(snapshot.active_character_id or "").strip()
        if not run_id or not character_id or snapshot.active_character is None:
            return False
        try:
            profile = store.for_character(character_id)
        except KeyError as exc:
            log(f"[agent] 跨进程终局恢复找不到角色 profile，保持阻塞：{exc}")
            return False
        if canonical_character_id(profile.character_id) != snapshot.active_character:
            log(f"[agent] 跨进程终局恢复角色不一致，保持阻塞：{run_id}")
            return False

        knowledge = getattr(self, "_profile_knowledge", {}).get(
            profile.profile_id)
        if knowledge is None:
            log(f"[agent] 跨进程终局恢复缺少角色知识库，保持阻塞：{run_id}")
            return False
        try:
            terminal = knowledge.load_run_log(run_id)
        except (OSError, ValueError) as exc:
            log(f"[agent] 跨进程终局恢复无法读取终局日志，保持阻塞：{exc}")
            return False
        if not isinstance(terminal, dict):
            return False

        required = (
            "run_id", "run_number", "profile_id", "character_id",
            "profile_run_number", "ascension", "started_at", "victory",
            "floor", "decisions", "combat_notes", "attribution_tags",
        )
        if any(key not in terminal for key in required):
            log(f"[agent] 跨进程终局恢复证据不完整，保持阻塞：{run_id}")
            return False
        if (str(terminal.get("run_id") or "") != run_id
                or str(terminal.get("profile_id") or "") != profile.profile_id
                or canonical_character_id(terminal.get("character_id"))
                != snapshot.active_character
                or bool(terminal.get("in_progress"))
                or bool(terminal.get("human_assisted"))
                or bool(terminal.get("excluded_from_learning"))
                or not isinstance(terminal.get("victory"), bool)
                or not isinstance(terminal.get("started_at"), str)
                or not terminal["started_at"].strip()
                or not isinstance(terminal.get("decisions"), list)
                or not isinstance(terminal.get("combat_notes"), list)
                or not isinstance(terminal.get("attribution_tags"), list)):
            log(f"[agent] 跨进程终局恢复拒绝非完整自动对局：{run_id}")
            return False

        profile_run_number = terminal.get("profile_run_number")
        run_number = terminal.get("run_number")
        persisted_runs = (getattr(knowledge, "stats", {}).get("global", {})
                          .get("runs"))
        def valid_integer(value) -> bool:
            return (isinstance(value, int)
                    and not isinstance(value, bool) and value >= 0)

        if (not valid_integer(run_number)
                or run_number <= 0
                or not valid_integer(profile_run_number)
                or profile_run_number <= 0
                or run_number != profile_run_number
                or not valid_integer(terminal.get("ascension"))
                or not valid_integer(terminal.get("floor"))
                or not valid_integer(persisted_runs)
                or persisted_runs != profile_run_number):
            log(f"[agent] 跨进程终局恢复尚无角色统计落盘证明，保持阻塞：{run_id}")
            return False

        try:
            result = rotation.record_terminal(
                run_id,
                terminal_persisted=True,
                character_id=terminal["character_id"],
            )
        except (CharacterRotationError, OSError, ValueError) as exc:
            log(f"[agent] 跨进程终局恢复写入失败，保持阻塞：{exc}")
            return False

        try:
            knowledge.finish_run_learning(run_id)
        except (OSError, ValueError) as exc:
            # The rotation write above is already atomic and durable.  Learning
            # journal cleanup is independent and a later run can supersede a
            # non-excluded stale journal without replaying this terminal.
            log(f"[agent] 跨进程终局已恢复，学习事务清理稍后自愈：{exc}")
        log(f"[agent] 跨进程终局恢复完成：{run_id}，下一角色 {result.next_character}")
        return True

    def _bind_profile_for_state(self, state: dict) -> CharacterProfile | None:
        """Bind an active run from the API's actual character identity.

        At character selection there is no run identity yet, so the durable next
        target selects the profile whose ascension settings should be displayed.
        Once a run exists, only ``run.character_id`` is authoritative.
        """
        store = getattr(self, "profile_store", None)
        rotation = getattr(self, "rotation", None)
        if store is None or rotation is None:
            return None

        run = state.get("run") or {}
        if run:
            run_id = state.get("run_id") or run.get("run_id")
            character_id = run.get("character_id")
            if not run_id or not character_id:
                return None
            ctx = getattr(self, "ctx", None)
            ctx_run_id = getattr(ctx, "run_id", "run_unknown")
            # A process that first attaches to a stale GAME_OVER echo must not
            # create an unresolved "active" rotation entry. A genuine terminal
            # frame already has the matching live context and was observed earlier.
            if (state.get("screen") == "GAME_OVER"
                    and str(ctx_run_id) != str(run_id)):
                return None
            # If the API has already replaced an unfinished run, _track must first
            # finalize that old context against its original profile. It invokes
            # this binder again immediately afterwards for the replacement run.
            if (ctx_run_id not in ("", "run_unknown", str(run_id))
                    and not bool(getattr(ctx, "run_finalized", False))):
                return None
            try:
                try:
                    profile = store.for_character(str(character_id))
                except KeyError:
                    canonical = canonical_character_id(character_id)
                    if canonical is None:
                        raise
                    profile = store.resolve(canonical)
            except KeyError:
                error = f"actual_character_unmapped:{character_id}"
                if getattr(self, "_rotation_runtime_error", None) != error:
                    self._rotation_runtime_error = error
                    log(f"[agent] 角色运行时绑定失败：{error}")
                return None

            self._activate_profile(profile)
            # A run first seen under manual control is not an autonomous quota
            # candidate.  Binding its profile is still required so the Brain can
            # safely resume it, but it must not occupy/advance the scheduler.
            if str(run_id) not in getattr(self, "_manual_run_ids", set()):
                try:
                    rotation.observe_active_run(str(run_id), str(character_id))
                    self._rotation_runtime_error = None
                except CharacterRotationError as exc:
                    error = f"observe_active_run_failed:{run_id}:{character_id}:{exc}"
                    if getattr(self, "_rotation_runtime_error", None) != error:
                        self._rotation_runtime_error = error
                        log(f"[agent] 角色轮换状态错误：{error}")

            if ctx is not None:
                ctx.profile_id = profile.profile_id
                ctx.character_id = str(character_id)
            return profile

        if state.get("screen") == "CHARACTER_SELECT":
            try:
                profile = store.resolve(rotation.target_character)
            except (CharacterRotationError, KeyError) as exc:
                error = f"selection_profile_unavailable:{exc}"
                if getattr(self, "_rotation_runtime_error", None) != error:
                    self._rotation_runtime_error = error
                    log(f"[agent] 角色轮换状态错误：{error}")
                return None
            self._activate_profile(profile)
            return profile
        return None

    def _run_profile_metadata(self) -> dict:
        """Return backward-compatible terminal/incremental run-log identity."""
        ctx = self.ctx
        profile = (getattr(self, "active_profile", None)
                   or getattr(getattr(self, "know", None), "profile", None))
        profile_id = (getattr(ctx, "profile_id", "")
                      or getattr(profile, "profile_id", "") or "ironclad")
        character_id = (getattr(ctx, "character_id", "")
                        or getattr(profile, "character_id", "")
                        or (getattr(getattr(self, "know", None),
                                    "progression", {}) or {}).get(
                                        "character", "IRONCLAD"))
        profile_run_number = int(
            getattr(ctx, "profile_run_number", 0)
            or getattr(ctx, "run_number", 0) or 0)
        return {
            "profile_id": str(profile_id),
            "character_id": str(character_id),
            "profile_run_number": profile_run_number,
        }

    # ---------------- ASCEND-VISION live telemetry ----------------

    def _start_live_dashboard(self) -> None:
        """Start telemetry and the idempotent viewer supervisor, fail-open."""
        try:
            self.live_dashboard = LiveDashboardPublisher()
            self.live_dashboard.connection("starting", "等待游戏 API")
        except Exception as exc:
            self.live_dashboard = None
            log(f"[agent] 实时驾驶舱遥测启动失败（不影响游玩）：{exc}")
        if start_dashboard_supervisor is not None:
            try:
                self.dashboard_supervisor = start_dashboard_supervisor(self.cfg, log)
            except Exception as exc:
                log(f"[agent] ASCEND-VISION 监督器启动失败（不影响游玩）：{exc}")

    def _capture_boot_head(self) -> None:
        """Freeze the exact commit this Brain process loaded without spawning Git."""
        self._boot_head = ""
        self._boot_review_commit = ""
        self._boot_head_thread = None
        inherited = os.environ.get("STS2_ASCEND_BOOT_HEAD", "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{40,64}", inherited):
            self._boot_head = inherited
            log(f"[agent] 启动代码基线：{inherited[:8]}（runner 冻结）")
        elif autogit is not None:
            # Direct ``py -m brain`` fallback.  Pure ref-file reads are bounded and
            # cannot hang gameplay behind Windows CreateProcess/antivirus checks.
            self._boot_head = read_git_head(autogit.REPO_DIR)
            if self._boot_head:
                log(f"[agent] 启动代码基线：{self._boot_head[:8]}（本地冻结）")
        if not self._boot_head:
            log("[agent] 启动提交号暂不可读；代码版本诊断留空，游玩照常启动")
        review_handoff_present = "STS2_ASCEND_BOOT_REVIEW_COMMIT" in os.environ
        inherited_review = os.environ.get(
            "STS2_ASCEND_BOOT_REVIEW_COMMIT", "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{40,64}", inherited_review):
            self._boot_review_commit = inherited_review
        elif not review_handoff_present:
            # Direct ``py -m brain`` fallback.  This read happens before the
            # review worker resumes, so it still identifies the loaded epoch.
            try:
                marker = json.loads((KNOWLEDGE_DIR / "pending_restart.json").read_text(
                    encoding="utf-8"))
                candidate = str(marker.get("review_commit") or "").strip().lower()
                if (marker.get("state") in (None, "committed")
                        and re.fullmatch(r"[0-9a-f]{40,64}", candidate)):
                    self._boot_review_commit = candidate
            except (OSError, json.JSONDecodeError):
                pass

    def _dashboard_observe(self, state: dict, *, connection: str = "connected",
                           message: str = "") -> None:
        publisher = self.live_dashboard
        if publisher is None:
            return
        try:
            publisher.observe(state, run_number=self.ctx.run_number,
                              connection=connection, message=message)
        except Exception:
            pass

    def _dashboard_connection(self, status: str, message: str = "") -> None:
        publisher = self.live_dashboard
        if publisher is None:
            return
        try:
            publisher.connection(status, message)
        except Exception:
            pass

    def _dashboard_propose(self, state: dict, decision, *, watchdog: bool = False) -> None:
        publisher = self.live_dashboard
        if publisher is None:
            return
        try:
            ensure_decision_trace(state, decision)
            decision_id = publisher.propose(
                state, decision, run_number=self.ctx.run_number, watchdog=watchdog)
            setattr(decision, "_dashboard_decision_id", decision_id)
        except Exception:
            pass

    def _dashboard_outcome(self, status: str, message: str = "", decision=None) -> None:
        publisher = self.live_dashboard
        if publisher is None:
            return
        try:
            publisher.outcome(
                status, message,
                decision_id=getattr(decision, "_dashboard_decision_id", None))
        except Exception:
            pass

    # ---------------- manual takeover hotkeys ----------------

    @staticmethod
    def _state_run_identity(state: dict) -> str:
        run = state.get("run") or {}
        return str(state.get("run_id") or run.get("run_id") or "").strip()

    def _knowledge_for_run_learning(
            self, *, state: dict | None = None,
            profile_id: str = "") -> tuple[Knowledge | None, CharacterProfile | None]:
        """Resolve the exact profile store that owns one run's learning journal."""
        stores = getattr(self, "_profile_knowledge", {}) or {}
        profiles = getattr(self, "profile_store", None)
        if profile_id and profile_id in stores:
            profile = None
            if profiles is not None:
                try:
                    profile = profiles.resolve(profile_id)
                except KeyError:
                    pass
            return stores[profile_id], profile

        run = (state or {}).get("run") or {}
        character_id = str(run.get("character_id") or "").strip()
        if profiles is not None and character_id:
            try:
                try:
                    profile = profiles.for_character(character_id)
                except KeyError:
                    canonical = canonical_character_id(character_id)
                    if canonical is None:
                        raise
                    profile = profiles.resolve(canonical)
            except KeyError:
                log(f"[agent] 无法为人工接管局解析角色学习库：{character_id}")
                return None, None
            knowledge = stores.get(profile.profile_id)
            if knowledge is None:
                active = getattr(self, "active_profile", None)
                if getattr(active, "profile_id", None) == profile.profile_id:
                    knowledge = getattr(self, "know", None)
            return knowledge, profile

        return getattr(self, "know", None), getattr(self, "active_profile", None)

    @staticmethod
    def _begin_run_learning(knowledge, run_id: str) -> None:
        begin = getattr(knowledge, "begin_run_learning", None)
        if callable(begin):
            begin(run_id)

    @staticmethod
    def _exclude_run_learning(knowledge, run_id: str) -> None:
        exclude = getattr(knowledge, "exclude_run_learning", None)
        if callable(exclude):
            exclude(run_id)

    @staticmethod
    def _finish_run_learning(knowledge, run_id: str) -> None:
        finish = getattr(knowledge, "finish_run_learning", None)
        if callable(finish):
            finish(run_id)

    @staticmethod
    def _run_learning_is_excluded(knowledge, run_id: str) -> bool:
        check = getattr(knowledge, "run_learning_is_excluded", None)
        return bool(callable(check) and check(run_id))

    def _mark_manual_takeover(self, state: dict, *, source: str) -> str:
        """Mark every run straddling a human-control boundary as non-learning."""
        ctx = self.ctx
        current_run_id = self._state_run_identity(state)
        ctx_run_id = str(getattr(ctx, "run_id", "") or "").strip()
        changed = False
        processed: set[tuple[int, str]] = set()

        def exclude_scope(knowledge, run_id: str) -> None:
            nonlocal changed
            if knowledge is None or not run_id or run_id == "run_unknown":
                return
            key = (id(knowledge), run_id)
            if key in processed:
                return
            if self._run_learning_is_excluded(knowledge, run_id):
                processed.add(key)
                return
            self._begin_run_learning(knowledge, run_id)
            if self._run_learning_is_excluded(knowledge, run_id):
                processed.add(key)
                return
            self._exclude_run_learning(knowledge, run_id)
            processed.add(key)
            changed = True

        # The previous autonomous context is also mixed if the human crossed a
        # run boundary before the paused reader observed the replacement state.
        if (ctx_run_id and ctx_run_id != "run_unknown"
                and not bool(getattr(ctx, "run_finalized", False))):
            self._manual_run_ids.add(ctx_run_id)
            old_knowledge, _old_profile = self._knowledge_for_run_learning(
                profile_id=str(getattr(ctx, "profile_id", "") or ""))
            exclude_scope(old_knowledge, ctx_run_id)
            if not bool(getattr(ctx, "human_assisted", False)):
                ctx.human_assisted = True
                changed = True

        if current_run_id:
            self._manual_run_ids.add(current_run_id)
            current_knowledge, current_profile = self._knowledge_for_run_learning(
                state=state)
            exclude_scope(current_knowledge, current_run_id)
            if ctx_run_id in ("", "run_unknown") and hasattr(ctx, "reset_for"):
                if current_profile is not None and current_knowledge is not None:
                    self._activate_profile(current_profile)
                run = state.get("run") or {}
                ascension = int(run.get("ascension", 0) or 0)
                next_run = int((getattr(current_knowledge or self.know,
                                        "stats", {}) or {}).get(
                    "global", {}).get("runs", 0) or 0) + 1
                ctx.reset_for(current_run_id, ascension, next_run)
                ctx.character_id = str(run.get("character_id") or "")
                if current_profile is not None:
                    ctx.profile_id = current_profile.profile_id
                ctx.profile_run_number = next_run
                ctx.human_assisted = True
                changed = True
            elif ctx_run_id == current_run_id and not bool(
                    getattr(ctx, "human_assisted", False)):
                ctx.human_assisted = True
                changed = True

        if changed:
            try:
                run = state.get("run") or {}
                self._save_run_progress(run, force=True)
            except Exception as exc:
                log(f"[agent] 人工接管标记增量存档失败（仍保持停手）：{exc}")
            log(
                f"[agent] 当前局 {current_run_id or ctx_run_id or 'none'} "
                f"已标记为人工接管样本（{source}），不计入自动平衡/复盘")
        return current_run_id

    def _manual_control_blocks(self, state: dict) -> bool:
        """Observe pause epochs and return whether gameplay actions are forbidden."""
        snapshot = read_control_state()
        seen = int(getattr(self, "_seen_pause_generation", 0) or 0)
        if snapshot.pause_generation > seen:
            self._mark_manual_takeover(state, source=snapshot.source)
        self._seen_pause_generation = max(seen, snapshot.pause_generation)

        if (not self._state_run_identity(state)
                and state.get("screen") in ("MAIN_MENU", "CHARACTER_SELECT")
                and bool(getattr(self.ctx, "human_assisted", False))
                and not bool(getattr(self.ctx, "run_finalized", False))):
            floor = (self.ctx.decisions[-1].get("floor", 0)
                     if self.ctx.decisions else 0)
            self._exclude_human_assisted_run(victory=False, floor=floor)

        if snapshot.paused:
            self._mark_manual_takeover(state, source=snapshot.source)
            if not getattr(self, "_manual_pause_active", False):
                self._manual_pause_active = True
                detail = f"（状态异常：{snapshot.error}）" if snapshot.error else ""
                log(
                    f"[agent] Brain 已停止发送游戏操作{detail}；"
                    f"{RESUME_HOTKEY} 恢复，{PAUSE_HOTKEY} 保持人工接管")
            return True

        if getattr(self, "_manual_pause_active", False):
            self._manual_pause_active = False
            log(f"[agent] Brain 已由 {RESUME_HOTKEY} 恢复自主操作")
            self._dashboard_connection("connected", "Brain 已恢复自主操作")
        return False

    def _exclude_human_assisted_run(self, *, victory: bool, floor: int) -> None:
        """Close a mixed run without mutating autonomous stats, policy or quota."""
        if self.ctx.run_finalized:
            return
        run_id = str(self.ctx.run_id or "run_unknown")
        self.ctx.human_assisted = True
        self._manual_run_ids.add(run_id)
        knowledge, _profile = self._knowledge_for_run_learning(
            profile_id=str(getattr(self.ctx, "profile_id", "") or ""))
        # Re-apply the rollback at close so even a legacy/direct stats mutation
        # after F10 cannot survive the mixed run.
        self._begin_run_learning(knowledge, run_id)
        self._exclude_run_learning(knowledge, run_id)
        # Preserve the partial evidence as in-progress/excluded.  Existing floor
        # statistics and LLM packet builders already omit in-progress logs.
        try:
            self._save_run_progress({"floor": int(floor or 0)}, force=True)
        except Exception as exc:
            log(f"[agent] 人工接管局审计存档失败：{exc}")
        try:
            self._finish_run_learning(knowledge, run_id)
        except Exception as exc:
            # The exclusion marker and restored stats were persisted first.  A
            # leftover journal therefore remains fail-closed on the next process.
            log(f"[agent] 人工接管局学习快照清理失败（隔离仍有效）：{exc}")
        self.ctx.run_finalized = True
        self.ctx.finalize_requested = False
        self.ctx.combat = None
        self.ctx.combat_agg = None
        rotation = getattr(self, "rotation", None)
        if rotation is not None and run_id != "run_unknown":
            try:
                rotation.release_human_controlled_run(run_id)
            except CharacterRotationError as exc:
                log(f"[agent] 人工接管局释放轮换身份失败：{exc}")
        result = "胜利" if victory else "结束"
        log(
            f"[agent] 人工接管局 {run_id} 已{result}于 F{int(floor or 0)}；"
            "不增加局数、不更新平均/最高楼层、不进入 LLM 复盘，轮换配额保持原位")

    # ---------------- quipper（白绮碎碎念） ----------------

    def _launch_quipper(self) -> None:
        """Start or generation-handoff the single session IndexTTS owner."""
        try:
            quipper = BASE_DIR / "tts" / "quipper.py"
            if not quipper.exists():
                return
            import shutil
            uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")
            if not Path(uv).exists():
                return
            index_root = BASE_DIR / "third_party" / "index-tts"
            if not (index_root / "checkpoints" / "config.yaml").exists():
                log("[agent] IndexTTS 模型未就绪；GPU-only owner 未启动")
                return
            tts_dir = str(BASE_DIR / "tts")
            if tts_dir not in sys.path:
                sys.path.insert(0, tts_dir)
            from indextts_client import health as index_owner_health
            from owner_epoch import (OWNER_PROTOCOL_VERSION, code_epoch,
                                     status_matches)

            expected_epoch = code_epoch(BASE_DIR)
            session_id = os.environ.get("STS2_ASCEND_SESSION_ID", "legacy")
            current = index_owner_health(timeout=0.5)
            if status_matches(
                    current, session_id=session_id,
                    expected_epoch=expected_epoch, require_ready=True):
                log(
                    f"[agent] IndexTTS GPU owner 健康确认：pid "
                    f"{current.get('owner_pid')}，epoch {expected_epoch[:12]}"
                )
                return
            if (isinstance(current, dict)
                    and str(current.get("session_id", "legacy")) == session_id
                    and int(current.get("owner_protocol_version", 0) or 0)
                    < OWNER_PROTOCOL_VERSION):
                log(
                    "[agent] 当前 IndexTTS owner 是旧交接协议；本代不强杀、不假报成功，"
                    "下一次统一 Stop/Start 将完成一次迁移"
                )
                return
            cmd = [uv, "run", "--project", str(index_root), "python", str(quipper)]
            creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                             | getattr(subprocess, "DETACHED_PROCESS", 0)
                             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            subprocess.Popen(cmd,
                             cwd=str(BASE_DIR), stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=creationflags, close_fds=True)
            log(
                f"[agent] IndexTTS owner 候选已启动，等待 health 确认 "
                f"epoch {expected_epoch[:12]}；尚未宣称接管成功"
            )

            def confirm_owner() -> None:
                deadline = time.monotonic() + 240.0
                while time.monotonic() < deadline and not stop_requested():
                    status = index_owner_health(timeout=0.8)
                    if status_matches(
                            status, session_id=session_id,
                            expected_epoch=expected_epoch, require_ready=True):
                        log(
                            f"[agent] IndexTTS GPU owner 接管并健康确认：pid "
                            f"{status.get('owner_pid')}，epoch {expected_epoch[:12]}"
                        )
                        return
                    if wait_for_stop(0.5):
                        return
                if not stop_requested():
                    log(
                        f"[agent] IndexTTS owner 在 240 秒内未回显目标 epoch "
                        f"{expected_epoch[:12]}；未假报成功，稍后安全边界重试"
                    )

            monitor = threading.Thread(
                target=confirm_owner, name="indextts-owner-health", daemon=True)
            self._quipper_confirm_thread = monitor
            monitor.start()
        except Exception as exc:
            log(f"[agent] 碎碎念拉起失败（不影响游玩）：{exc}")

    # ---------------- game process management ----------------

    def _game_process_count(self) -> int:
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SlayTheSpire2.exe", "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout
            return sum(1 for line in out.splitlines() if "SlayTheSpire2" in line)
        except Exception:
            return 0

    def _wait_for_game_api(self, timeout_s: float = 300.0, poll_s: float = 4.0) -> bool:
        """Wait for the mod API while remaining responsive to Stop-Agent.ps1."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if stop_requested():
                return False
            if self.client.discover():
                return True
            if wait_for_stop(min(poll_s, max(0.0, deadline - time.monotonic()))):
                return False
        raise ConnectionDown(
            f"STS2-Agent API not reachable on ports {self.client.ports} within {timeout_s}s")

    def ensure_game(self) -> bool:
        if stop_requested():
            return False
        if self.client.discover():
            return True
        if self._game_process_count() > 0:
            # game process exists but API not up yet (still booting / mod loading) — wait, don't relaunch
            log("[agent] 游戏进程已存在但 API 未就绪，等待加载…")
            if not self._wait_for_game_api(timeout_s=300.0, poll_s=4.0):
                return False
            log(f"[agent] 游戏已就绪：{self.client.base_url}")
            return True
        log("[agent] 游戏未运行，启动游戏…")
        exe = os.environ.get("STS2_ASCEND_GAME_LAUNCHER") or self.cfg["game_exe"]
        if stop_requested():
            return False
        subprocess.Popen(["cmd", "/c", exe], cwd=str(Path(exe).parent), shell=False,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not self._wait_for_game_api(timeout_s=300.0, poll_s=4.0):
            return False
        log(f"[agent] 游戏已就绪：{self.client.base_url}")
        return True

    # ---------------- run context tracking ----------------

    def _track(self, state: dict, decision=None) -> None:
        """Apply observations from the state returned by the game.

        This phase intentionally ignores the decision that will be sent next.  It
        must run *before* policy evaluation so a new run/combat identity exists when
        the policy consumes success tags from the previous HTTP response.  Keeping
        the optional argument preserves the small direct-call test helpers and makes
        the observation-only contract explicit.
        """
        run = state.get("run") or {}
        self._bind_profile_for_state(state)
        run_id = state.get("run_id") or "run_unknown"
        screen = state.get("screen", "UNKNOWN")
        hp = run.get("current_hp", self.ctx.last_hp)
        gold = run.get("gold", self.ctx.last_gold)
        asc = run.get("ascension", self.ctx.ascension)

        # Freeze a clean boundary before accepting a run as evidence that newly
        # loaded review code is healthy. Attaching to an existing run proves only
        # its tail and used to retire rollback protection too early.
        if (screen in ("MAIN_MENU", "CHARACTER_SELECT") and not run
                and (self.ctx.run_id == "run_unknown" or self.ctx.run_finalized)):
            self._review_health_ready_for_new_run = True

        # new run detection
        # GAME_OVER 屏必须排除（第 50~51 局复盘）：大脑重启落在上一局结算屏时，
        # 新进程会把旧 run_id 回声当成新对局，随后在 GAME_OVER 上二次结算出
        # 零决策幻影局（第 19/26/42/51 局四次实证，生涯统计被灌水 4 局 56 层）
        if run_id != self.ctx.run_id and screen not in ("MAIN_MENU", "GAME_OVER") and run:
            if (self.ctx.run_id != "run_unknown" and not self.ctx.run_finalized
                    and (self.ctx.decisions
                         or bool(getattr(self.ctx, "human_assisted", False)))):
                if bool(getattr(self.ctx, "human_assisted", False)):
                    # Human play can return to menu or start another run while the
                    # Brain is paused.  Never reinterpret that gap as an AI loss.
                    self._exclude_human_assisted_run(
                        victory=False,
                        floor=(self.ctx.decisions[-1].get("floor", 0)
                               if self.ctx.decisions else 0))
                else:
                    # previous run vanished without GAME_OVER (crash/abandon) — close it out as a loss
                    log("[agent] 检测到上一局异常结束，按失败归档")
                    self._finalize(victory=False, floor=self.ctx.decisions[-1].get("floor", 0))
                # A pending review could not restart at the menu because the old
                # context still needed this loss finalization. The replacement run
                # has not been accepted or acted on yet, so hand it to the reloaded
                # Brain before reset_for erases that last safe boundary.
                restart_reason = self._pending_review_restart_reason()
                if restart_reason:
                    log(f"[agent] {restart_reason}；异常旧局已归档，新局动作前请求 runner 重启大脑…")
                    sys.exit(42)
            self._bind_profile_for_state(state)
            # Capture the character-local baseline before any event/combat/card
            # observation from this run can mutate Knowledge.  Reconnect reuses
            # the durable journal instead of replacing the original baseline.
            self._begin_run_learning(self.know, str(run_id))
            journal_excluded = self._run_learning_is_excluded(
                self.know, str(run_id))
            next_run = int(self.know.stats.get("global", {}).get("runs", 0)) + 1
            review_health_eligible = bool(
                getattr(self, "_review_health_ready_for_new_run", False))
            self.ctx.reset_for(run_id, asc, next_run)
            profile = (getattr(self, "active_profile", None)
                       or getattr(self.know, "profile", None))
            self.ctx.profile_id = getattr(profile, "profile_id", "ironclad")
            self.ctx.character_id = str(
                run.get("character_id")
                or getattr(profile, "character_id", "IRONCLAD"))
            self.ctx.profile_run_number = next_run
            self.ctx.review_health_eligible = review_health_eligible
            self.ctx.human_assisted = (
                str(run_id) in getattr(self, "_manual_run_ids", set())
                or journal_excluded)
            if self.ctx.human_assisted:
                self._manual_run_ids.add(str(run_id))
                self._exclude_run_learning(self.know, str(run_id))
            self._review_health_ready_for_new_run = False
            log(f"\n[agent] ===== 新对局开始：{run_id}（进阶 {asc}）=====")
            # 断线重连续接局史（第 218 批复盘）：大脑在局中途崩溃/签名故障自杀后，
            # 新进程遇同 run_id 旧账另起——218 局 F23 重启把 23 层深局记成
            # 24 决策/1 拿牌/0 遗物的残缺局，复盘数据全被带歪。增量落盘的
            # 决策与战斗记录在此接回，重连不再丢局史。
            prior = self.know.load_run_log(run_id)
            if prior and (prior.get("decisions") or prior.get("combat_notes")):
                # Resuming a persisted run is not a complete boot-validation run,
                # even if a transient menu-like screen was observed first.
                self.ctx.review_health_eligible = False
                self.ctx.decisions = list(prior.get("decisions") or [])
                self.ctx.combat_notes = list(prior.get("combat_notes") or [])
                # Resume only terminal attribution facts.  The general credit_tags
                # ledger is deliberately left empty because Policy consumes it as a
                # volatile success/handshake stream; replaying it would double-count
                # novelty, card plays and UI attempts after every restart.
                self.ctx.attribution_tags = _durable_attribution_tags(
                    prior.get("attribution_tags"))
                if prior.get("started_at"):
                    self.ctx.started_at = prior["started_at"]
                prior_run_number = prior.get(
                    "profile_run_number", prior.get("run_number"))
                if prior_run_number:
                    self.ctx.run_number = int(prior_run_number)
                    self.ctx.profile_run_number = self.ctx.run_number
                if prior.get("human_assisted") or prior.get("excluded_from_learning"):
                    self.ctx.human_assisted = True
                    self._manual_run_ids.add(str(run_id))
                    self._exclude_run_learning(self.know, str(run_id))
                log(f"[agent] 断线重连：接续对局日志（{len(self.ctx.decisions)} 条决策 / "
                    f"{len(self.ctx.combat_notes)} 条战斗记录 / "
                    f"{len(self.ctx.attribution_tags)} 条长期归因）")

        # combat enter/exit tracking
        # 战斗连续性：Boss/精英转阶段过场、结算弹层会让屏幕在 COMBAT↔MODAL 间闪断。
        # 旧逻辑按"离开战斗屏"立即结算并重建上下文，同一场 Boss 战被拆成 2~3 条统计
        # （第 36 批 DW7 局 F17 实证：一场掉血被记为 1/18/38 三笔）——场均掉血被稀释、
        # enemy_stance 死亡率失真、药水黑名单误重置。现在过场类屏幕只挂起不结算，
        # 回到同组合同层的战斗视为延续（ctx.combat 对象身份不变，药水黑名单随之保留）。
        if screen == "COMBAT":
            enemies_now = (state.get("combat") or {}).get("enemies", [])
            comp = "+".join(sorted({(e.get("enemy_id") or "?") for e in enemies_now if e.get("is_alive")}))
            node_type = next((t[1] for t in reversed(self.ctx.attribution_tags)
                              if t[0] == "map_node"), "Unknown")
            if self.ctx.combat is None:
                self._start_combat(run, comp, node_type, hp)
            elif self.ctx.combat_bridge:
                b_comp, b_floor, _b_ts = self.ctx.combat_bridge
                self.ctx.combat_bridge = None
                if b_comp != (comp or "unknown") or b_floor != run.get("floor", 0):
                    log(f"[agent] 过场后战斗对象变化（{b_comp}→{comp or 'unknown'}），结算前段再开新账")
                    self._settle_combat(hp, won=True, died=False, split=True)
                    self._start_combat(run, comp, node_type, hp)
                else:
                    log("[agent] 战斗屏幕重连：同组合同层，按同一场战斗延续（统计不重复结算）")
            # 回合数采样（第 82~83 批复盘）：记录战斗进行到的最大回合数，
            # 供复盘区分「长战磨死」与「短时爆毙」，分别演化进攻/防御参数
            turn_no = state.get("turn")
            if isinstance(turn_no, int) and self.ctx.combat is not None:
                self.ctx.combat["rounds"] = max(int(self.ctx.combat.get("rounds", 0)), turn_no)
        elif screen != "COMBAT" and self.ctx.combat is not None:
            victory_screen = screen == "GAME_OVER" and bool((state.get("game_over") or {}).get("is_victory"))
            died_here = screen == "GAME_OVER" and not victory_screen
            if not died_here and screen in ("MODAL", "UNKNOWN", "TIMELINE", "CARD_SELECTION"):
                # 疑似转阶段过场：挂起等待重连；若下一帧是 MAP/REWARD 等真实流转再结算。
                # CARD_SELECTION 同属过场（第 99~102 批复盘）：战斗中无色药水/卡牌效果
                # 会弹选牌屏（102 局 F17 Boss 战 hp 全程 39 不变），旧清单漏了它——
                # 选牌屏被当成真实流转立即结算，97~98 批的同层整场合并被重新拆碎
                # （该场 Boss 战记成 26/0/38 三条，boss_loss_stats 场均再度稀释）
                self.ctx.combat_bridge = (self.ctx.combat["comp_id"], self.ctx.combat["floor"], time.time())
            else:
                self._settle_combat(hp, won=not died_here, died=died_here)

        # event outcome commit on screen change
        # 事件触发战斗的延迟结算（第 106 局复盘）：「茂密的植被-战！」会在
        # 随后的战斗中把感染×3 打进牌堆，旧逻辑在进战瞬间结算，deck_delta
        # 恒记 0——事件学习端把「污染卡组」当免费，战！以 0 分力压坚持跋涉。
        # 现在：离开事件屏的第一个 tick 先快照 hp/金币（事件自身的即时效果，
        # 不含后续战斗损耗），战斗/过场屏只挂起不结算；真实流转屏（MAP/
        # REWARD/GAME_OVER…）才落库——卡组增量用战后 live 值补记，状态牌
        # 污染从此入账。战斗中的死亡不归因给事件选项（因果链归敌人组合，
        # 保住 deaths_by_enemy 排行榜对姿态演化的驱动）。
        # 战斗掉血归因到选项链（第 237~238 批复盘）：快照语义把战斗损耗
        # 排除在事件 hp 账外——「茂密的植被」休息→战！链中休息账面 +7 回血、
        # 战！账面 0.0，而强制战 237/238 两局连掉 55/54 血；事件学习端把
        # 必亏选项当免费反复选（战！n=19 价值 0.0）。战斗掉血本就全额记
        # 敌人组合账（姿态/先验演化不受影响），此处叠加一份因果归因：
        # 当前挂起选项按「快照效果 − 战斗掉血」记账；同事件内已先行结算的
        # 祖先选项（event_chain，如引出强制战页的「休息」）各追加一条等额
        # 掉血样本——是「休息」而非「战！」把局面推进了强制战页，代价必须
        # 让做选择的那一环看见。金币仍按快照（战利品属战斗经济）。
        if self.ctx.pending_event is not None:
            if screen in ("COMBAT", "MODAL"):
                if self.ctx.pending_event_own is None:
                    self.ctx.pending_event_own = (hp, gold)
            elif screen != "EVENT":
                # 兼容旧格式 6 元组：缺签名位补空（进程热替换边界）
                _pe = self.ctx.pending_event
                if len(_pe) < 8:
                    _pe = tuple(_pe) + ((), 0)
                event_id, key, hp0, gold0, floor0, deck0, rel0, pot0 = _pe
                own_hp, own_gold = self.ctx.pending_event_own or (hp, gold)
                through_combat = self.ctx.pending_event_own is not None
                victory_screen = screen == "GAME_OVER" and bool((state.get("game_over") or {}).get("is_victory"))
                died_here = screen == "GAME_OVER" and not victory_screen
                deck_delta = len(run.get("deck", []) or []) - deck0
                # 遗物/药水净增量（第 372~373 局批次复盘）：选择前后签名做差，
                # 「给遗物的选项记 0 分」的学习盲区从此闭合。run 载荷在终局屏
                # 可能已被清空——此时按签名不变处理，避免把死亡结算成「丢光遗物」
                relic_delta, potion_delta = _reward_delta(
                    (rel0, pot0),
                    _event_reward_sig(run) if run else (rel0, pot0))
                # 战斗掉血：优先读尚未落库的聚合账（战后正常流转）；死亡时战斗账
                # 已先行 flush，改读 _flush_combat_agg 留下的暂存
                fight_loss = 0.0
                if through_combat:
                    agg = self.ctx.combat_agg
                    if agg is not None and agg.get("from_event"):
                        fight_loss = float(agg.get("hp_lost_sum", 0.0) or 0.0)
                    else:
                        fight_loss = float(self.ctx.pending_event_fight_loss or 0.0)
                self.know.commit_event_option(event_id, key, own_hp - hp0 - fight_loss,
                                              own_gold - gold0,
                                              died=(died_here and not through_combat),
                                              deck_delta=deck_delta,
                                              relic_delta=relic_delta,
                                              potion_delta=potion_delta)
                # 祖先选项链追加等额掉血样本（「休息」引出强制战页之类）
                if fight_loss > 0.0:
                    for anc_id, anc_key in self.ctx.event_chain:
                        self.know.commit_event_option(anc_id, anc_key, -fight_loss, 0.0,
                                                      died=False, deck_delta=0)
                log(f"[agent] 事件结算：{event_id}/{key} → 生命 {own_hp - hp0 - fight_loss:+}，金币 {own_gold - gold0:+}，"
                    f"卡组 {deck_delta:+d}，遗物 {relic_delta:+d}，药水 {potion_delta:+d}"
                    + (f"（经战斗延迟记账，战斗掉血 {fight_loss:.0f} 归因选项链"
                       f"（含祖先 {len(self.ctx.event_chain)} 环），死亡归因敌方组合）" if through_combat else "")
                    + ("（致死）" if died_here and not through_combat else ""))
                if died_here and not through_combat:
                    self.ctx.died_to_event = (event_id, key)
                self.ctx.pending_event = None
                self.ctx.pending_event_own = None
                self.ctx.event_chain = []
                self.ctx.pending_event_fight_loss = 0.0

        # 观察态转换必须在动作请求前执行：即使本 tick 的新动作失败，上一动作已经
        # 导致的离场、战斗结束、生命/金币变化仍是真实事实，不能丢失。决策本身的
        # tags/ctx 副作用则统一留给 _commit_successful_action；否则 409/断线也会
        # 伪造拿牌、路线、休息和事件选择样本。
        self.ctx.last_hp, self.ctx.last_gold = hp, gold

    def _commit_successful_action(self, state: dict, decision) -> None:
        """Commit one accepted HTTP action and its credit/context effects.

        ``_track`` is deliberately observation-only.  The API may reject a request
        with 409, raise on a signature mismatch, or disconnect before confirming it;
        none of those attempts may enter the learning ledger.  Once the response is
        accepted, use the *pre-action* state to establish event/rest snapshots, append
        all credit tags, count successful card plays, and persist the decision trail.
        """
        run = state.get("run") or {}
        screen = state.get("screen", "UNKNOWN")
        hp = run.get("current_hp", self.ctx.last_hp)
        gold = run.get("gold", self.ctx.last_gold)

        for tag in decision.tags:
            if tag[0] == "event_choice":
                # 事件内换项抉择先行结算（第 214 批复盘）：同一事件未离场就改选
                # 其他选项（滑脚木桥「再撑一会」单局八连后才换跨越），旧逻辑直接
                # 覆盖 pending_event——除最后一次外全部选择永不入账，n 恒 0 被
                # 「样本最少」规则反复选中。改选时按当前观测增量把上一次选择落库。
                # 同键重挂（同选项的 tick 级重试）不结算也不刷新快照——点击未落地
                # 的重试不应产生幻影样本，最终结算仍从首次选择起量
                prev = self.ctx.pending_event
                if prev is not None and prev[0] == tag[1] and prev[1] != tag[2]:
                    deck_now = len(run.get("deck", []) or [])
                    # 兼容旧格式 6 元组（进程热替换/测试桩）：缺签名位按空处理
                    _rel0 = prev[6] if len(prev) > 6 else ()
                    _pot0 = prev[7] if len(prev) > 7 else 0
                    _sw_rel, _sw_pot = _reward_delta((_rel0, _pot0),
                                                     _event_reward_sig(run))
                    self.know.commit_event_option(prev[0], prev[1], hp - prev[2], gold - prev[3],
                                                  died=False, deck_delta=deck_now - prev[5],
                                                  relic_delta=_sw_rel, potion_delta=_sw_pot)
                    log(f"[agent] 事件内换项抉择：先行结算 {prev[0]}/{prev[1]} → "
                        f"生命 {hp - prev[2]:+}，金币 {gold - prev[3]:+}，卡组 {deck_now - prev[5]:+d}，"
                        f"遗物 {_sw_rel:+d}，药水 {_sw_pot:+d}")
                    # 祖先链记账（第 237~238 批复盘）：若后续选项触发战斗，战斗
                    # 掉血会给本环追加等额样本——引出强制战页的选择必须看见代价
                    self.ctx.event_chain.append((prev[0], prev[1]))
                    self.ctx.pending_event = (tag[1], tag[2], hp, gold, run.get("floor", 0),
                                              deck_now) + _event_reward_sig(run)
                    self.ctx.pending_event_own = None  # 新选项重置自身效果快照
                elif prev is None or prev[0] != tag[1]:
                    self.ctx.pending_event = (tag[1], tag[2], hp, gold, run.get("floor", 0),
                                              len(run.get("deck", []) or [])) + _event_reward_sig(run)
                    self.ctx.pending_event_own = None  # 新选项重置自身效果快照
                    self.ctx.event_chain = []  # 新事件重置祖先链
                    self.ctx.pending_event_fight_loss = 0.0
            elif tag[0] == "rest":
                if tag[1] == "heal" and hp >= run.get("max_hp", 1) - 2:
                    self.ctx.rests_healed_at_full += 1
            self.ctx.credit_tags.append(tag)
            if tag and tag[0] in _DURABLE_ATTRIBUTION_KINDS:
                self.ctx.attribution_tags.append(tuple(tag))

        for tag in decision.tags:
            if tag[0] == "play_card" and tag[1]:
                self.know.commit_card_play(tag[1])

        # Persist the accepted pre-action decision evidence.  Rich snapshots are
        # deliberately limited by _decision_log_entry; routine actions remain as
        # compact as the historical schema.
        decision_row = _decision_log_entry(state, decision)
        decision_row["hp"] = hp
        decision_row["gold"] = gold
        self.ctx.decisions.append(decision_row)
        self._save_run_progress(run)

    @staticmethod
    def _stable_sig(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), default=str)

    @staticmethod
    def _indexed_item(items, index):
        """Find one payload item by API index without trusting list position."""
        for item in items or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("index", item.get("i"))
            try:
                if int(raw) == int(index):
                    return item
            except (TypeError, ValueError):
                if raw == index:
                    return item
        return None

    @classmethod
    def _run_material(cls, state: dict) -> dict:
        """Run fields whose change proves a resource/deck/inventory effect."""
        run = state.get("run") or {}

        def card_sig(card):
            return (card.get("index"), card.get("card_id"), card.get("instance_id"),
                    card.get("uuid"), card.get("name"), bool(card.get("upgraded")))

        return {
            "character_id": run.get("character_id"),
            "ascension": run.get("ascension"),
            "floor": run.get("floor"),
            "act_id": run.get("act_id"),
            "current_hp": run.get("current_hp"),
            "max_hp": run.get("max_hp"),
            "gold": run.get("gold"),
            "max_energy": run.get("max_energy"),
            "deck": tuple(card_sig(c) for c in (run.get("deck") or [])
                          if isinstance(c, dict)),
            "relics": tuple((r.get("index"), r.get("relic_id"), r.get("name"),
                              r.get("counter"))
                             for r in (run.get("relics") or []) if isinstance(r, dict)),
            # can_use/usage may flicker with screen readiness; identity/occupancy is
            # the durable proof that a potion was consumed or obtained.
            "potions": tuple((p.get("index"), bool(p.get("occupied")),
                               p.get("potion_id"), p.get("name"))
                              for p in (run.get("potions") or []) if isinstance(p, dict)),
        }

    @classmethod
    def _combat_material(cls, state: dict) -> dict:
        """Combat deltas caused by a card/potion, minus readiness-only fields."""
        combat = state.get("combat") or {}
        player = combat.get("player") or {}

        def card_sig(card):
            # playable/targets/why are endpoint readiness and can flicker while the
            # same physical card remains in hand.
            return (card.get("index"), card.get("card_id"), card.get("instance_id"),
                    card.get("uuid"), card.get("name"), bool(card.get("upgraded")),
                    card.get("energy_cost"), card.get("star_cost"),
                    bool(card.get("costs_x")), bool(card.get("star_costs_x")))

        def creature_sig(creature):
            return {
                "index": creature.get("index"),
                "id": creature.get("enemy_id") or creature.get("player_id"),
                "current_hp": creature.get("current_hp"),
                "max_hp": creature.get("max_hp"),
                "block": creature.get("block"),
                "is_alive": creature.get("is_alive"),
                "powers": creature.get("powers") or [],
            }

        return {
            "turn": state.get("turn"),
            "player": {
                "current_hp": player.get("current_hp"),
                "max_hp": player.get("max_hp"),
                "block": player.get("block"),
                "energy": player.get("energy"),
                "stars": player.get("stars"),
                "focus": player.get("focus"),
                "powers": player.get("powers") or [],
                "orbs": player.get("orbs") or [],
                "cards_played_this_turn": player.get("cards_played_this_turn"),
                "attacks_played_this_turn": player.get("attacks_played_this_turn"),
                "skills_played_this_turn": player.get("skills_played_this_turn"),
            },
            "hand": tuple(card_sig(c) for c in (combat.get("hand") or [])
                          if isinstance(c, dict)),
            "enemies": tuple(creature_sig(e) for e in (combat.get("enemies") or [])
                             if isinstance(e, dict)),
            "players": tuple(creature_sig(p) for p in (combat.get("players") or [])
                             if isinstance(p, dict)),
        }

    @staticmethod
    def _potion_at(state: dict, index):
        run = state.get("run") or {}
        for potion in run.get("potions") or []:
            if not isinstance(potion, dict):
                continue
            try:
                same = int(potion.get("index")) == int(index)
            except (TypeError, ValueError):
                same = potion.get("index") == index
            if same:
                return (bool(potion.get("occupied")), potion.get("potion_id"),
                        potion.get("name"))
        return None

    @classmethod
    def _screen_material(cls, state: dict, key: str):
        """Payload for a concrete screen, plus durable run resources."""
        return {
            key: state.get(key),
            "run": cls._run_material(state),
        }

    @staticmethod
    def _selection_reconcile_key(state: dict) -> tuple:
        sel = state.get("selection") or {}
        cards = tuple((c.get("index"), c.get("card_id"), c.get("instance_id"),
                       c.get("uuid"), bool(c.get("upgraded")))
                      for c in (sel.get("cards") or []))
        return ((state.get("run") or {}).get("floor", 0),
                (sel.get("kind") or "").lower(), sel.get("prompt") or "",
                sel.get("min_select"), sel.get("max_select"), cards)

    @staticmethod
    def _run_identity(state: dict):
        run = state.get("run") or {}
        return state.get("run_id") or run.get("run_id")

    @staticmethod
    def _card_identity(card: dict | None) -> tuple | None:
        if not isinstance(card, dict):
            return None
        physical = card.get("instance_id") or card.get("uuid")
        if physical:
            return ("physical", str(physical))
        return ("logical", str(card.get("card_id") or card.get("name") or ""),
                bool(card.get("upgraded")))

    @classmethod
    def _card_count(cls, cards, target: dict | None) -> int:
        identity = cls._card_identity(target)
        if identity is None:
            return 0
        return sum(1 for card in (cards or [])
                   if cls._card_identity(card) == identity)

    @staticmethod
    def _relic_identity(relic: dict | None) -> tuple | None:
        if not isinstance(relic, dict):
            return None
        relic_id = str(relic.get("relic_id") or "")
        name = str(relic.get("name") or "")
        if relic_id:
            return ("id", relic_id)
        if name:
            return ("name", name)
        return None

    @classmethod
    def _relic_count(cls, relics, target: dict | None) -> int:
        identity = cls._relic_identity(target)
        if identity is None:
            return 0
        return sum(1 for relic in (relics or [])
                   if cls._relic_identity(relic) == identity)

    @staticmethod
    def _treasure_options(state: dict) -> list:
        chest = state.get("chest") or {}
        for key in ("relic_options", "relics", "options"):
            value = chest.get(key)
            if isinstance(value, list):
                return value
        return []

    @classmethod
    def _treasure_target_present(cls, state: dict, target: dict | None) -> bool:
        identity = cls._relic_identity(target)
        if identity is None:
            return False
        return any(cls._relic_identity(item) == identity
                   for item in cls._treasure_options(state))

    @staticmethod
    def _reward_identity(item: dict | None) -> tuple | None:
        if not isinstance(item, dict):
            return None
        return (item.get("index"), str(item.get("reward_type") or ""),
                str(item.get("description") or ""))

    @classmethod
    def _reward_target_present(cls, state: dict, target: dict | None) -> bool:
        identity = cls._reward_identity(target)
        if identity is None:
            return False
        return any(cls._reward_identity(item) == identity
                   for item in ((state.get("reward") or {}).get("rewards") or []))

    @classmethod
    def _event_resource_material(cls, state: dict) -> dict:
        """Durable resources an event option can directly change.

        Floor/act and readiness fields are intentionally excluded: they can change
        while an event click is still queued and must not manufacture success.
        """
        run = cls._run_material(state)
        return {key: run.get(key) for key in (
            "current_hp", "max_hp", "gold", "max_energy", "deck", "relics",
            "potions")}

    @classmethod
    def _event_page_material(cls, state: dict) -> tuple:
        event = state.get("event") or {}
        options = tuple((item.get("index"), item.get("text_key"),
                         item.get("title"), item.get("description"),
                         bool(item.get("is_proceed")))
                        for item in (event.get("options") or [])
                        if isinstance(item, dict))
        return (event.get("event_id"), event.get("title"),
                event.get("page"), event.get("step"),
                bool(event.get("is_finished")), options)

    def _remember_ambiguous_action(self, state: dict, decision,
                                   *, accepted: bool = False,
                                   message: str | None = None) -> None:
        """Retain an unacknowledged action until the next successful state GET."""
        try:
            before = copy.deepcopy(state)
        except Exception:
            before = state
        self._ambiguous_action = {
            "state": before,
            "decision": decision,
            "polls": 0,
            "accepted": bool(accepted),
        }
        self._dashboard_outcome(
            "pending" if accepted else "uncertain",
            message or ("服务端已受理，等待状态确认" if accepted
                        else "回执不确定，等待状态对账"),
            decision)
        try:
            self.policy.note_action_uncertain(decision.action, decision.tags,
                                              before, decision.params)
        except Exception as exc:
            log(f"[agent] 模糊动作的 UI 语义暂存失败（仍保留 Agent 对账）：{exc}")

    def _ambiguous_action_outcome(self, before: dict, after: dict, decision) -> str:
        """Return ``applied`` only for an action-specific material postcondition.

        ``unproven`` includes both an unchanged state and a superseding transition
        whose cause cannot safely be attributed to the lost POST.  The caller waits
        for a few fresh GETs before allowing Policy to retry, avoiding both an early
        duplicate and false learning credit.
        """
        action = decision.action
        params = decision.params or {}
        before_screen = before.get("screen")
        after_screen = after.get("screen")
        before_run_id = self._run_identity(before)
        after_run_id = self._run_identity(after)
        if before_run_id is None and after_run_id is None:
            same_run = True  # legacy/test payloads without run identity
        else:
            # If one side has already lost its run id, it may be a new run/menu.
            # Never credit an in-run action from that boundary transition.
            same_run = (before_run_id is not None and after_run_id is not None
                        and before_run_id == after_run_id)

        run_boundary_actions = {
            "open_character_select", "embark", "continue_run",
            "continue_game_over", "return_to_main_menu",
        }
        if action not in run_boundary_actions and not same_run:
            return "unproven"

        if action == "remove_card_at_shop":
            # Opening card removal is proven only by its semantic follow-up screen.
            return ("applied" if (after_screen == "CARD_SELECTION" and same_run
                    and (after.get("run") or {}).get("floor", 0)
                    == (before.get("run") or {}).get("floor", 0)) else "unproven")

        if action == "select_deck_card":
            if after_screen != "CARD_SELECTION":
                return "applied"
            if self._selection_reconcile_key(after) != self._selection_reconcile_key(before):
                return "applied"
            old_count = int(((before.get("selection") or {}).get("selected_count", 0)) or 0)
            new_count = int(((after.get("selection") or {}).get("selected_count", 0)) or 0)
            return "applied" if new_count > old_count else "unproven"

        if action == "confirm_selection":
            if after_screen != "CARD_SELECTION":
                return "applied"
            return ("applied" if self._selection_reconcile_key(after)
                    != self._selection_reconcile_key(before) else "unproven")

        if action == "play_card":
            # A later turn cannot prove which card (if any) was played; committing
            # the old hand index there can credit/blacklist a newly drawn card.
            if before_screen != "COMBAT" or after_screen != "COMBAT":
                return ("applied" if (before_screen == "COMBAT" and same_run
                        and after_screen in ("CARD_SELECTION", "MODAL", "REWARD", "GAME_OVER"))
                        else "unproven")
            if not same_run or before.get("turn") != after.get("turn"):
                return "unproven"
            before_combat = before.get("combat") or {}
            after_combat = after.get("combat") or {}
            before_player = before_combat.get("player") or {}
            after_player = after_combat.get("player") or {}
            old_plays = before_player.get("cards_played_this_turn")
            new_plays = after_player.get("cards_played_this_turn")
            if (isinstance(old_plays, int) and isinstance(new_plays, int)
                    and new_plays > old_plays):
                return "applied"

            # Energy/enemy/power animation changes alone are not proof.  Require
            # the concrete card instance (or, on old payloads, one logical copy)
            # to have left the same-turn hand.
            old_card = self._indexed_item(before_combat.get("hand") or [],
                                          params.get("card_index"))
            if old_card is not None and self._card_count(
                    after_combat.get("hand") or [], old_card) < self._card_count(
                        before_combat.get("hand") or [], old_card):
                return "applied"
            return "unproven"

        if action == "end_turn":
            if before_screen == "COMBAT" and after_screen != "COMBAT":
                return "applied"
            old_turn, new_turn = before.get("turn"), after.get("turn")
            return ("applied" if (same_run and isinstance(old_turn, int)
                    and isinstance(new_turn, int) and new_turn > old_turn)
                    else "unproven")

        if action == "continue_game_over":
            if before_screen != "GAME_OVER":
                return "unproven"
            if after_screen != "GAME_OVER":
                return "applied"
            before_game_over = before.get("game_over") or {}
            after_game_over = after.get("game_over") or {}
            if (before_game_over.get("can_continue")
                    and not after_game_over.get("can_continue")):
                return "applied"
            before_phase = str(before_game_over.get("phase") or "")
            after_phase = str(after_game_over.get("phase") or "")
            return ("applied" if before_phase == "intro"
                    and after_phase in ("summary_animating", "summary_ready")
                    else "unproven")

        if action == "use_potion":
            slot = params.get("option_index")
            if self._potion_at(before, slot) != self._potion_at(after, slot):
                return "applied"
            if before_screen == "COMBAT" and after_screen in ("CARD_SELECTION", "REWARD", "GAME_OVER"):
                return "applied"
            return "unproven"

        if action == "claim_reward":
            if before_screen == "REWARD" and after_screen != "REWARD":
                return "applied"
            index = params.get("option_index")
            old = self._indexed_item(((before.get("reward") or {}).get("rewards") or []), index)
            new = self._indexed_item(((after.get("reward") or {}).get("rewards") or []), index)
            if old is not None and (not self._reward_target_present(after, old)
                                    or (new is not None
                                        and not new.get("claimable", True))):
                return "applied"
            before_reward = before.get("reward") or {}
            after_reward = after.get("reward") or {}
            if (old is not None
                    and str(old.get("reward_type") or "") in ("Card", "SpecialCard")
                    and not before_reward.get("pending_card_choice")
                    and (after_reward.get("pending_card_choice")
                         or after_reward.get("card_options"))):
                return "applied"
            return "unproven"

        if action == "choose_reward_card":
            if before_screen in ("REWARD", "CARD_SELECTION") and after_screen not in ("REWARD", "CARD_SELECTION"):
                return "applied"
            before_reward = before.get("reward") or {}
            after_reward = after.get("reward") or {}
            before_cards = (before_reward.get("card_options")
                            or (before.get("selection") or {}).get("cards") or [])
            after_cards = (after_reward.get("card_options")
                           or (after.get("selection") or {}).get("cards") or [])
            selected = self._indexed_item(before_cards, params.get("option_index"))
            before_deck = (before.get("run") or {}).get("deck") or []
            after_deck = (after.get("run") or {}).get("deck") or []
            if selected is not None and (
                    self._card_count(after_deck, selected)
                    > self._card_count(before_deck, selected)
                    or self._card_count(after_cards, selected)
                    < self._card_count(before_cards, selected)):
                return "applied"
            return "unproven"

        if action == "skip_reward_cards":
            if before_screen in ("REWARD", "CARD_SELECTION") and after_screen not in ("REWARD", "CARD_SELECTION"):
                return "applied"
            before_reward = before.get("reward") or {}
            after_reward = after.get("reward") or {}
            before_cards = (before_reward.get("card_options")
                            or (before.get("selection") or {}).get("cards") or [])
            after_cards = (after_reward.get("card_options")
                           or (after.get("selection") or {}).get("cards") or [])
            if before_cards and (not after_cards
                    or (before_reward.get("pending_card_choice")
                        and not after_reward.get("pending_card_choice"))):
                return "applied"
            return "unproven"

        if action in ("collect_rewards_and_proceed", "resolve_rewards"):
            if before_screen in ("REWARD", "CARD_SELECTION") and after_screen not in ("REWARD", "CARD_SELECTION"):
                return "applied"
            before_claimable = sum(1 for item in
                                   ((before.get("reward") or {}).get("rewards") or [])
                                   if item.get("claimable"))
            after_claimable = sum(1 for item in
                                  ((after.get("reward") or {}).get("rewards") or [])
                                  if item.get("claimable"))
            return "applied" if after_claimable < before_claimable else "unproven"

        if action == "choose_event_option":
            if before_screen == "EVENT" and after_screen != "EVENT":
                return "applied"
            if after_screen != "EVENT":
                return "unproven"
            if self._event_page_material(before) != self._event_page_material(after):
                return "applied"
            return ("applied" if self._event_resource_material(before)
                    != self._event_resource_material(after) else "unproven")

        if action == "choose_map_node":
            if before_screen == "MAP" and after_screen != "MAP":
                return "applied"
            if after_screen != "MAP":
                return "unproven"
            old_run, new_run = self._run_material(before), self._run_material(after)
            return ("applied" if (old_run.get("floor") != new_run.get("floor")
                    or old_run.get("act_id") != new_run.get("act_id")) else "unproven")

        if action == "choose_rest_option":
            if before_screen == "REST" and after_screen != "REST":
                return "applied"
            if after_screen != "REST":
                return "unproven"
            old_run, new_run = self._run_material(before), self._run_material(after)
            if (old_run.get("current_hp") != new_run.get("current_hp")
                    or old_run.get("max_hp") != new_run.get("max_hp")
                    or old_run.get("deck") != new_run.get("deck")):
                return "applied"
            return "unproven"

        if action in ("buy_card", "buy_relic", "buy_potion"):
            collection = {"buy_card": "cards", "buy_relic": "relics",
                          "buy_potion": "potions"}[action]
            index = params.get("option_index")
            old = self._indexed_item(((before.get("shop") or {}).get(collection) or []), index)
            new = self._indexed_item(((after.get("shop") or {}).get(collection) or []), index)
            if old is not None and (new is None or not new.get("is_stocked", new.get("stocked", True))):
                return "applied"
            old_run, new_run = self._run_material(before), self._run_material(after)
            inventory = {"buy_card": "deck", "buy_relic": "relics",
                         "buy_potion": "potions"}[action]
            if (old is not None and old_run.get("gold") is not None
                    and new_run.get("gold") is not None
                    and new_run.get("gold") < old_run.get("gold")
                    and old_run.get(inventory) != new_run.get(inventory)):
                return "applied"
            return "unproven"

        if action == "choose_treasure_relic":
            old = self._indexed_item(self._treasure_options(before),
                                     params.get("option_index"))
            if old is None:
                return "unproven"
            before_run = before.get("run") or {}
            after_run = after.get("run") or {}
            if self._relic_count(after_run.get("relics") or [], old) \
                    > self._relic_count(before_run.get("relics") or [], old):
                return "applied"

            # Some API versions keep the chest visible for one frame and either
            # remove only the selected option or mark that exact row claimed.  A
            # generic chest payload/screen change is deliberately insufficient:
            # it can be an animation refresh or an unrelated proceed transition.
            after_chest = after.get("chest")
            if isinstance(after_chest, dict) and after_screen == "CHEST":
                if not self._treasure_target_present(after, old):
                    return "applied"
                exact = next((item for item in self._treasure_options(after)
                              if self._relic_identity(item) == self._relic_identity(old)),
                             None)
                if isinstance(exact, dict) and (
                        exact.get("claimed") is True
                        or exact.get("is_claimed") is True
                        or exact.get("claimable") is False):
                    return "applied"
                claimed_id = (after_chest.get("claimed_relic_id")
                              or after_chest.get("selected_relic_id"))
                if claimed_id and str(claimed_id) == str(old.get("relic_id") or ""):
                    return "applied"
            return "unproven"

        # Deterministic UI transitions.  Each action is tied to its own payload or
        # expected destination; unrelated endpoint/readiness changes are ignored.
        destination = {
            "open_character_select": {"CHARACTER_SELECT"},
            "embark": {"MAP", "COMBAT", "EVENT", "REST", "SHOP"},
            "continue_run": {"MAP", "COMBAT", "EVENT", "REST", "SHOP", "REWARD"},
            "return_to_main_menu": {"MAIN_MENU", "TIMELINE", "UNLOCK"},
        }.get(action)
        if destination is not None:
            return "applied" if after_screen in destination and after_screen != before_screen else "unproven"

        domain_by_action = {
            "select_character": "character_select",
            "increase_ascension": "character_select",
            "decrease_ascension": "character_select",
            "choose_timeline_epoch": "timeline",
            "confirm_timeline_overlay": "timeline",
            "open_timeline": "timeline",
            "close_main_menu_submenu": "timeline",
            "confirm_unlock": "unlock",
            "open_chest": "chest",
            "open_shop_inventory": "shop",
            "close_shop_inventory": "shop",
            "confirm_modal": "modal",
            "dismiss_modal": "modal",
            "crystal_clear_cell": "crystal_sphere",
            "choose_bundle": "bundles",
            "confirm_bundle": "bundles",
            "choose_capstone_option": "capstone",
        }
        domain = domain_by_action.get(action)
        if domain is not None:
            if before_screen != after_screen:
                return "applied"
            return ("applied" if self._stable_sig(before.get(domain))
                    != self._stable_sig(after.get(domain)) else "unproven")

        if action == "proceed":
            if before_screen != after_screen:
                return "applied"
            key = {
                "REWARD": "reward", "SHOP": "shop", "CHEST": "chest",
                "EVENT": "event", "REST": "rest", "GAME_OVER": "game_over",
            }.get(before_screen)
            if key and self._stable_sig(before.get(key)) != self._stable_sig(after.get(key)):
                return "applied"
            return "unproven"

        # Unknown actions are never credited from a generic full-state difference.
        # Waiting then re-evaluating the live state is safer than double-submitting
        # or poisoning a learning ledger with an unrelated transition.
        return "unproven"

    def _ambiguous_action_applied(self, before: dict, after: dict, decision) -> bool:
        """Compatibility helper used by focused self-checks."""
        return self._ambiguous_action_outcome(before, after, decision) == "applied"

    def _reconcile_ambiguous_action(self, state: dict) -> str | None:
        """Commit inferred success before tracking its observed outcome, else retry."""
        pending = self._ambiguous_action
        if not isinstance(pending, dict):
            return None
        before = pending["state"]
        decision = pending["decision"]
        if self._ambiguous_action_outcome(before, state, decision) != "applied":
            polls = int(pending.get("polls", 0)) + 1
            max_polls = 12 if pending.get("accepted") else 3
            if polls < max_polls:
                pending["polls"] = polls
                self._dashboard_outcome(
                    "reconciling", f"等待动作特定效果（{polls}/{max_polls}）", decision)
                log(f"[agent] 动作 {decision.action} 丢失回执；尚无动作特定效果，"
                    f"等待新状态确认（{polls}/{max_polls}）")
                return "wait"
            self._ambiguous_action = None
            if pending.get("accepted"):
                try:
                    self.policy.note_action_deferred(
                        decision.action, decision.tags, before, decision.params)
                except Exception:
                    pass
            prefix = "服务端已受理但" if pending.get("accepted") else ""
            log(f"[agent] 动作 {decision.action} {prefix}连续状态未见效果，"
                "释放为精确目标冷却后的重新评估")
            self._dashboard_outcome(
                "retrying", f"{prefix}连续状态未见效果，释放后重新评估", decision)
            return "retry"
        self._ambiguous_action = None
        try:
            self._commit_successful_action(before, decision)
            log(f"[agent] 动作 {decision.action} 丢失回执；已由下一状态确认成功并补交事务账")
            self._dashboard_outcome("applied", "下一状态已确认动作生效", decision)
            return "applied"
        except Exception as exc:
            # The game-side effect is already proven.  Never turn bookkeeping failure
            # into a duplicate action; preserve the live state and continue.
            log(f"[agent] 动作 {decision.action} 已由状态确认成功，但补交本地事务账失败：{exc}")
            self._dashboard_outcome(
                "applied", f"动作已生效；本地事务账失败：{exc}", decision)
            return "applied"

    @staticmethod
    def _api_error_is_transient(exc: ApiError) -> bool:
        """Classify errors that deserve a fresh-state retry before local penalty."""
        if bool(getattr(exc, "retryable", False)):
            return True
        code = str(getattr(exc, "code", "") or "").lower()
        message = str(exc).lower()
        if int(getattr(exc, "status", 0) or 0) == 409:
            if (any(term in message for term in ("not supported", "disabled"))
                    or (code == "invalid_target" and any(term in message for term in (
                        "requires target_index", "requires option_index",
                        "requires card_index")))):
                return False
            # invalid_action/invalid_target frequently mean that the state advanced
            # between GET and POST (card no longer playable, target reindexed,
            # potion readiness flicker).  Agent gives the exact target a bounded
            # cooldown after repeated identical rejections; it is never promoted to
            # a permanent gameplay blacklist solely because an animation lasted.
            if code in ("invalid_action", "invalid_target", "invalid_parameter",
                        "validation_error", "state_unavailable"):
                return True
        return False

    def _api_retry_key(self, state: dict, decision, exc: ApiError) -> tuple:
        action = decision.action
        if action in ("play_card", "end_turn", "use_potion"):
            material = {
                "screen": state.get("screen"),
                "run_id": state.get("run_id"),
                "combat": self._combat_material(state),
                "potions": self._run_material(state).get("potions"),
            }
        else:
            domain = {
                "choose_event_option": "event",
                "choose_map_node": "map",
                "choose_rest_option": "rest",
                "choose_treasure_relic": "chest",
                "claim_reward": "reward",
                "choose_reward_card": "reward",
                "skip_reward_cards": "reward",
                "collect_rewards_and_proceed": "reward",
                "select_deck_card": "selection",
                "confirm_selection": "selection",
                "buy_card": "shop", "buy_relic": "shop",
                "buy_potion": "shop", "remove_card_at_shop": "shop",
            }.get(action)
            material = {
                "screen": state.get("screen"),
                "run_id": state.get("run_id"),
                "domain": state.get(domain) if domain else None,
                "run": self._run_material(state),
            }
        return (decision.action,
                self._stable_sig(decision.params or {}),
                self._stable_sig(material),
                str(getattr(exc, "code", "") or "").lower())

    def _defer_api_error_once(self, state: dict, decision, exc: ApiError) -> bool:
        """Keep refresh-race 409s out of permanent gameplay blacklists.

        The live payload is authoritative on the next tick.  Repeated 409s are
        counted for diagnostics/watchdog progress but remain non-definitive: an
        animation window can outlast one settle interval, and permanently skipping
        a still-present reward, potion, or affordable card is worse than another
        state-driven attempt.  Parameter/schema failures are classified definitive
        by :meth:`_api_error_is_transient` and still take the failure path.
        """
        if not self._api_error_is_transient(exc):
            self._api_race_retry = None
            return False
        if bool(getattr(exc, "retryable", False)):
            # 503/state_unavailable is explicitly declared retryable by the server;
            # do not turn infrastructure readiness into a gameplay blacklist.
            self._api_race_retry = None
            return True
        key = self._api_retry_key(state, decision, exc)
        if (isinstance(self._api_race_retry, tuple)
                and len(self._api_race_retry) == 2
                and self._api_race_retry[0] == key):
            count = int(self._api_race_retry[1]) + 1
        else:
            count = 1
        self._api_race_retry = (key, count)
        if count % 3 == 0:
            try:
                self.policy.note_action_deferred(
                    decision.action, decision.tags, state, decision.params)
                log(f"  ↳ 动作 {decision.action} 连续刷新竞争×{count}；"
                    "仅冷却该精确目标，让同屏其他候选先行")
            except Exception as defer_exc:
                log(f"  ↳ 临时轮转目标失败（保持无永久惩罚）：{defer_exc}")
        return True

    def _save_run_progress(self, run: dict, force: bool = False) -> None:
        """对局日志增量存档（第 218 批复盘）：旧实现只在终局落盘——大脑在局
        中途崩溃/自杀重启（218 局 F23 签名故障）时，前半局决策与战斗记录全灭，
        重连进程另起新账把深局记成残缺局。现在每 15 条决策（或换层）落盘一次，
        重连时按 run_id 接续，崩溃最多丢失最近十几条决策。"""
        if not self.ctx.decisions or self.ctx.run_id == "run_unknown":
            return
        # 终局定稿后禁止增量覆盖（第 369 局复盘）：结算屏之后的「回主菜单/
        # 检查时间线」等后继决策会以增量稿格式（in_progress=true/victory=
        # false/floor=当前屏）盖回已定稿日志——141 个已完成局被永久打上
        # 「进行中」脏戳，复盘摘要把它们全部过滤后只能拿一百多局前的旧局
        # 当样本（第 263~369 局的复盘数据包因此整体失真）。定稿只出自
        # _finalize 的 save_run_log，此后对局日志一律只读。
        if self.ctx.run_finalized:
            return
        # A pause/profile transition can change the active ``self.know`` alias
        # before this mixed run's audit record is written.  The context identity
        # remains authoritative, exactly as it is for the learning rollback.
        knowledge, _profile = self._knowledge_for_run_learning(
            profile_id=str(getattr(self.ctx, "profile_id", "") or ""))
        if knowledge is None:
            knowledge = self.know
        floor = run.get("floor", 0)
        attribution_tags = _durable_attribution_tags(self.ctx.attribution_tags)
        if not force:
            mark = getattr(self, "_rlog_mark", (0, -1, -1))
            last_n, last_f = mark[:2]
            last_a = mark[2] if len(mark) >= 3 else -1
            if (len(self.ctx.decisions) - last_n < 15 and floor == last_f
                    and len(attribution_tags) == last_a):
                return
        self._rlog_mark = (len(self.ctx.decisions), floor, len(attribution_tags))
        try:
            knowledge.save_run_log(self.ctx.run_id, {
                "run_id": self.ctx.run_id,
                "run_number": self.ctx.run_number,
                **self._run_profile_metadata(),
                "ascension": self.ctx.ascension,
                "started_at": self.ctx.started_at,
                "victory": False,
                "in_progress": True,
                "floor": floor,
                "decisions": self.ctx.decisions,
                "combat_notes": self.ctx.combat_notes,
                "attribution_tags": attribution_tags,
                "human_assisted": bool(getattr(self.ctx, "human_assisted", False)),
                "excluded_from_learning": bool(
                    getattr(self.ctx, "human_assisted", False)),
            })
        except OSError:
            pass

    def _mark_review_run_healthy(self) -> None:
        """Retire a review rollback marker only after reloaded code completes runs.

        A fixed number of API ticks proves little: rare screens can crash minutes
        later, and the old 50-tick deletion made runner rollback impossible.  Runner
        freezes the exact marker present before importing this Brain; only complete
        runs matching that loaded marker epoch count.  No Git subprocess runs on the
        gameplay thread.  The repository lock prevents racing a newly prepared
        marker from the asynchronous reviewer.
        """
        marker = KNOWLEDGE_DIR / "pending_restart.json"
        if autogit is None or not marker.exists():
            return
        if not bool(getattr(self.ctx, "review_health_eligible", False)):
            diag = ("partial-run", getattr(self.ctx, "run_id", "unknown"))
            if getattr(self, "_review_health_diag", None) != diag:
                self._review_health_diag = diag
                log("[agent] 复盘健康计数未推进：本进程在该局开始前未观察到局间边界；"
                    "下一局完整验证")
            return
        if not getattr(self, "_boot_review_commit", ""):
            diag = ("missing-boot-review", str(marker))
            if getattr(self, "_review_health_diag", None) != diag:
                self._review_health_diag = diag
                log("[agent] 复盘健康计数未推进：该 marker 不是本进程启动时加载的；"
                    "等待重启加载")
            return
        try:
            # Optional health bookkeeping must never queue live gameplay behind a
            # review/progress Git transaction. A later complete run can retry it.
            with autogit.repository_lock(timeout=0.1):
                info = json.loads(marker.read_text(encoding="utf-8"))
                if info.get("state") not in (None, "committed"):
                    return
                review_commit = str(info.get("review_commit") or "")
                if not review_commit:
                    return
                loaded_review = getattr(self, "_boot_review_commit", "")
                if loaded_review != review_commit:
                    diag = (review_commit, loaded_review)
                    if getattr(self, "_review_health_diag", None) != diag:
                        self._review_health_diag = diag
                        log(f"[agent] 复盘健康计数未推进：marker {review_commit[:8]} "
                            f"不是本进程加载的 marker {loaded_review[:8] or 'none'}；"
                            "等待重启加载")
                    return
                healthy_runs = int(info.get("healthy_runs", 0) or 0) + 1
                if healthy_runs >= REVIEW_HEALTHY_RUNS:
                    marker.unlink(missing_ok=True)
                    log(f"[agent] 复盘代码已完成 {healthy_runs} 局，撤销安全标记转为健康")
                    return
                info["healthy_runs"] = healthy_runs
                info["last_healthy_run_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                tmp_name = None
                try:
                    with tempfile.NamedTemporaryFile(
                            mode="w", encoding="utf-8", newline="\n", delete=False,
                            dir=marker.parent, prefix=".pending_restart.",
                            suffix=".tmp") as tmp:
                        tmp_name = tmp.name
                        json.dump(info, tmp, ensure_ascii=False, indent=1)
                        tmp.flush()
                        os.fsync(tmp.fileno())
                    os.replace(tmp_name, marker)
                    tmp_name = None
                finally:
                    if tmp_name is not None:
                        try:
                            Path(tmp_name).unlink()
                        except OSError:
                            pass
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError,
                subprocess.SubprocessError) as exc:
            log(f"[agent] 复盘健康标记更新失败（保留 marker）：{exc}")

    def _note_signature_failure(self, action: str, exc: Exception) -> None:
        """签名级动作失败熔断（第 218 批复盘）：长驻进程不热重载代码——复盘
        把 client.act 签名更新落盘后，旧进程载入时的 act 仍是老版本，policy
        新代码传入的 x/y/tool 触发 TypeError 仍每 tick 重试同一动作，218 局
        F23 连刷 75 秒直到看门狗杀进程、前半局局史全灭。「unexpected keyword
        argument」类 TypeError 是永久性代码错位，重试永远不会成功：同一动作
        三连即存档局史并请求 runner 重启加载磁盘新代码；若近期已因此重启过
        （磁盘代码同源故障，重启无用），改为进程内拉黑该动作避免重启死循环。"""
        if not isinstance(exc, TypeError) or "argument" not in str(exc):
            return
        fails = getattr(self, "_sig_fails", None)
        if fails is None:
            fails = self._sig_fails = {}
        fails[action] = fails.get(action, 0) + 1
        if fails[action] < 3:
            return
        fails[action] = 0
        marker = KNOWLEDGE_DIR / "stale_code_restart.json"
        try:
            info = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
        except (OSError, json.JSONDecodeError):
            info = {}
        if info.get("action") == action and time.time() - float(info.get("ts", 0) or 0) < 900:
            log(f"[agent] 动作 {action} 签名故障且 15 分钟内重启未愈（磁盘代码同源），"
                "进程内拉黑该动作，等待复盘修复")
            self.policy.mark_action_broken(action)
            return
        log(f"[agent] 动作 {action} 连续签名故障（进程代码落后于磁盘），"
            "存档局史并请求 runner 重启加载新代码")
        try:
            marker.write_text(json.dumps({"ts": time.time(), "action": action}), encoding="utf-8")
        except OSError:
            pass
        last_floor = self.ctx.decisions[-1].get("floor", 0) if self.ctx.decisions else 0
        self._save_run_progress({"floor": last_floor}, force=True)
        sys.exit(42)

    def _act_entry_due(self, run_id: str, act: int) -> bool:
        """进幕快照去重判定：同局同幕只记一次，换局/换幕都要记。

        第509~515局批复盘新增。旧实现按进程级 act 单值去重——同一进程内
        后续对局的一幕首战（act 仍=1）被整体吞掉，六局只落一条快照。
        方法只读写自身键状态，不触其他属性，便于 selfcheck 用哑对象直测。
        """
        key = (str(run_id or ""), int(act))
        if key == getattr(self, "_last_entry_key", None):
            return False
        self._last_entry_key = key
        return True

    def _start_combat(self, run: dict, comp: str, node_type: str, hp: int) -> None:
        # 同层多段战斗聚合（第 97~98 批复盘）：多阶段 Boss 的阶段切换会以
        # 「settle+重开账」形态把一场战斗拆成多条统计——97 局一场仪式兽
        # （实际掉血 45+0+35=80）被拆成 3 条：boss_loss_stats 场均被稀释成
        # 22.9/段（真实 ≈65），Boss 前夜智能锻造的「战损≥回血量」条件以 1.1 之差
        # 永不触发，敌人死亡率分母同步灌水。修复：同层分段并入同一聚合账，
        # 只有换层开战/终局才落库。一层一节点 ⇒ floor 是「同一场战斗」的可靠键。
        agg = self.ctx.combat_agg
        if agg is not None and agg.get("floor") != run.get("floor", 0):
            self._flush_combat_agg()
        max_hp = max(1, run.get("max_hp", 1))
        self.ctx.combat = {"comp_id": comp or "unknown", "hp_start": hp, "floor": run.get("floor", 0),
                           "node_type": node_type, "hp_start_pct": hp / max_hp,
                           # 事件触发战斗标记（第 237~238 批复盘）：pending_event 存活
                           # 期间开打的战斗只能由该事件直接引发（事件屏→战斗/过场屏
                           # 不结算），掉血将在事件结算时归因到选项链
                           "from_event": self.ctx.pending_event is not None}
        self.ctx.current_combat_is_hard = node_type in ("Elite", "Boss")
        # Every stall verdict belongs to exactly this combat.  A previous giveup or
        # offense verdict must never make the next encounter surrender/force attacks
        # from turn one, and every long combat gets its own analysis opportunity.
        self.ctx.stall_analysis_asked = False
        self.ctx.stall_analysis_needed = False
        self.ctx.stall_giveup = False
        self.ctx.force_giveup = False
        self.ctx.force_offense = False
        self.ctx.stall_grind_grace = False
        # 高危组合自动升级硬仗（第 65~66 局复盘）：历史死亡率 ≥30% 的杀手组合
        # （FUZZY_WURM+SHRINKER_BEETLE 25战11死、KIN 双子 15战9死）大量出现在
        # 普通怪房，药水 premium 门此前对它们永不开启——两局均带药进坟。
        # 按统计实锤解锁增益/攻击药水投入，与 Elite/Boss 同一待遇。
        e = self.know.stats.get("enemies", {}).get(self.ctx.combat["comp_id"])
        rate_gate = float(self.know.policy.get("danger_comp_hard_death_rate", 0.30))
        if e and e.get("encounters", 0) >= 3 and e.get("deaths", 0) / max(1, e["encounters"]) >= rate_gate:
            self.ctx.current_combat_is_hard = True
        # 进幕快照（第 506~508 局批复盘新增；第509~515局批复盘修粘滞）：
        # 每局每幕首次开战时把就绪度落账。本批实证二幕消耗战已成主死因（F22/F31），
        # 而「进二幕时卡组多强、带了多少资源」此前没有账——快照让下批复盘能把
        # 死亡楼层与进幕爆发/血量/金币/药水做定量对照。
        # 粘滞缺陷：旧实现按进程级 `_last_entry_act` 去重，同一进程内后续对局的
        # 一幕首战（act 仍=1）全部被吞——本批六局只落了 513 局一条快照，
        # 「进幕就绪度 vs 死亡楼层」的对账样本直接断供。改按 (run_id, act) 键去重：
        # 同局同幕只记一次，换局/换幕都记（纯观测，任何异常静默跳过）
        try:
            _act = int(self.policy._floor_act(run.get("floor", 0)))
            if self._act_entry_due(getattr(self.ctx, "run_id", ""), _act):
                _deck = run.get("deck", []) or []
                self.know.commit_act_entry({
                    "act": _act,
                    "floor": int(run.get("floor", 0) or 0),
                    "hp_pct": round(hp / max_hp, 3),
                    "max_hp": int(max_hp),
                    "gold": int(run.get("gold", 0) or 0),
                    "potions": len([p for p in (run.get("potions") or [])
                                    if p.get("occupied")]),
                    "deck_size": len(_deck),
                    "burst": round(float(self.policy.deck_burst(_deck)), 1),
                })
        except Exception:
            pass
        danger = self.know.enemy_danger(comp)
        log(f"[agent] 进入战斗：敌方={comp}｜历史场均掉血 {danger:.1f}｜房间类型 {node_type}")

    def _settle_combat(self, hp: int, won: bool, died: bool, split: bool = False) -> None:
        """结算当前战斗账。

        split=True 表示本次结算来自「转场后战斗对象变化」（多阶段切换）：
        同层的分段并入挂起的聚合账而非独立入账。split=False 表示真实战斗终结
        （经 MAP/REWARD/GAME_OVER 等实屏流转）：聚合账补记 open=False 挂起，
        等下一层开战或终局时落库。致死任何情况下立即落库。
        """
        c = self.ctx.combat
        if c is None:
            return
        hp_lost = max(0, c["hp_start"] - hp)
        # 血池/火力观测合并（第 138~141 批复盘）：policy 端逐 tick 把本场观测
        # 写在 ctx.combat 上（obs_* 键），结算时并入聚合账——多阶段战斗按
        # 「血池取最大段、火力求和」口径合并，flush 时一次性入统计库
        obs_pool = float(c.get("obs_hp_pool") or 0.0)
        obs_fire = float(c.get("obs_fire_sum") or 0.0)
        obs_fr = int(c.get("obs_fire_rounds") or 0)
        agg = self.ctx.combat_agg
        # open 聚合账 = 一场多阶段战斗仍在进行：同层任何后续结算都并入它，
        # 无论本次流转是阶段切换（split）还是真实终结屏（GAME_OVER 致死等）
        joinable = (agg is not None and agg.get("open")
                    and agg.get("floor") == c.get("floor"))
        if not joinable and agg is not None:
            self._flush_combat_agg()
            agg = None
        if joinable:
            agg["hp_lost_sum"] += max(0.0, hp_lost)
            agg["from_event"] = bool(agg.get("from_event")) or bool(c.get("from_event"))
            agg["rounds"] = max(int(agg.get("rounds", 0) or 0), int(c.get("rounds", 0) or 0))
            agg["won"] = bool(won) and not agg["died"]
            agg["died"] = agg["died"] or bool(died)
            agg["obs_hp_pool"] = max(float(agg.get("obs_hp_pool", 0.0) or 0.0), obs_pool)
            agg["obs_fire_sum"] = float(agg.get("obs_fire_sum", 0.0) or 0.0) + obs_fire
            agg["obs_fire_rounds"] = int(agg.get("obs_fire_rounds", 0) or 0) + obs_fr
            # 非分段流转 = 战斗真实终结：关闭挂起账（等换层/终局落库）
            agg["open"] = bool(split)
        else:
            agg = {"comp_id": c["comp_id"], "floor": c.get("floor", 0),
                   "node_type": c.get("node_type"), "hp_lost_sum": max(0.0, hp_lost),
                   "rounds": int(c.get("rounds", 0) or 0), "won": bool(won),
                   "died": bool(died), "hp_start_pct": c.get("hp_start_pct"),
                   "open": bool(split), "from_event": bool(c.get("from_event")),
                   "obs_hp_pool": obs_pool, "obs_fire_sum": obs_fire,
                   "obs_fire_rounds": obs_fr}
            self.ctx.combat_agg = agg
        if died:
            # 致死必须立即落库：died_in_combat / 入场血量 / 精英标记供复盘归因，
            # 且死亡是整场战斗的绝对终结（不存在后续分段）
            self.ctx.died_in_combat = {"comp_id": agg["comp_id"], "node_type": agg["node_type"],
                                       "rounds": agg["rounds"], "floor": agg.get("floor"),
                                       # 全场掉血（第 167~176 批复盘新增）：长战/爆毙的
                                       # 分类不能只看回合数——4 回合掉 64 血是「没挡住」
                                       # 的爆毙而非磨死，reflect 按每回合失血率分流证据
                                       "hp_lost": float(agg.get("hp_lost_sum", 0.0) or 0.0),
                                       # 僵局摆烂死（第 109 局复盘）：600+ 回合零掉血后主动送死，
                                       # 血量损失全发生在「停止防御」之后——与格挡/击杀权重无关，
                                       # 标记随死亡归因传递，reflect 据此隔离攻防旋钮
                                       "stall": bool(getattr(self.ctx, "stall_giveup", False))}
            self.ctx.death_hp_pct_at_entry = agg.get("hp_start_pct")
            self.ctx.death_was_elite = agg.get("node_type") == "Elite"
            self._flush_combat_agg()
            log(f"[agent] 战斗失败：F{agg['floor']} {agg['node_type']}战 "
                f"掉血{int(round(agg['hp_lost_sum']))}（阵亡，含{agg['rounds']}回合全场）")
        self.ctx.combat = None
        self.ctx.current_combat_is_hard = False

    def _flush_combat_agg(self) -> None:
        """把挂起的同层聚合账一次性写入统计（第 97~98 批复盘新增）。"""
        agg = self.ctx.combat_agg
        if not agg:
            return
        # 事件触发战斗的掉血暂存（第 237~238 批复盘）：死亡时本账先于事件账
        # 落库，pending_event 结算点读不到聚合账——掉血在此暂存交给事件结算
        if agg.get("from_event") and self.ctx.pending_event is not None:
            self.ctx.pending_event_fight_loss = float(agg.get("hp_lost_sum", 0.0) or 0.0)
        # 幕号提前推算（第 506~515 局批复盘）：Boss 分幕子账本靠它分流——
        # 竞速投影/前夜裁决消费分幕血池火力均值，不再被全幕混合口径带偏
        _fl = int(agg.get("floor") or 1)
        act_no = Policy._floor_act(_fl)
        self.know.commit_enemy_fight(agg["comp_id"], float(agg.get("hp_lost_sum", 0.0)),
                                     won=bool(agg.get("won")), died=bool(agg.get("died")),
                                     node_type=agg.get("node_type"),
                                     hp_pool=(float(agg.get("obs_hp_pool", 0.0)) or None),
                                     fire_sum=float(agg.get("obs_fire_sum", 0.0) or 0.0),
                                     fire_rounds=int(agg.get("obs_fire_rounds", 0) or 0),
                                     act=act_no)
        # 分幕掉血入账（第 84~85 批复盘接线）：act 参数按整场战斗的楼层归幕；
        # floor 同步入账分幕分层段键 rooms_band（第 266 局批次复盘新增）——
        # 同幕怪物池随楼层递增，全幕均值把后段杀手组合摊薄成便宜战。
        # hp_start_pct 同步入账（第 396 局复盘新增）：Elite 的健康进场
        # 子账本靠它分流——健康状态主动打的精英与低血被迫打的精英是两个分布
        # died 同步入账（第 479~482 局批复盘）：存活尾部子账本靠它分流——
        # 阵亡场掉血=入场血量，混进尾部记忆会把「单场最差」永久钉在满管血，
        # 尾部定价与生存复核从 F1 满血起全图空转（详见 knowledge 端 docstring）
        self.know.commit_room_damage(agg.get("node_type") or "Unknown",
                                     float(agg.get("hp_lost_sum", 0.0)), act=act_no,
                                     floor=_fl,
                                     hp_start_pct=agg.get("hp_start_pct"),
                                     died=bool(agg.get("died")))
        # 竞速投影错账审计（RACE_PROJ_CALIB_AUDIT 观测位，第802~807局批复盘）：
        # 本场若发生过实测口径竞速判死入锁，战斗记录追加「判死→实战」对照，
        # 把 stance 成长型反向偏置的系统性悲观率变成每局可检索的硬留痕；
        # 「（阵亡）」后缀保持全链断言兼容，审计段插在其前
        _ra = self.policy.pop_race_audit()
        note = f"F{agg['floor']} {agg['node_type']}战 掉血{int(round(agg['hp_lost_sum']))}"
        learning_allowed = getattr(self.know, "_learning_write_allowed", None)
        if (_ra.get("latched")
                and (not callable(learning_allowed) or learning_allowed())):
            note += (f"｜竞速审计：T{_ra.get('latch_round', '?')}判死→"
                     f"实战{agg.get('rounds', '?')}回合"
                     + ("阵亡" if agg.get("died") else "获胜"))
            # 审计账本并表落库（RACE_AUDIT_STATS_AGGREGATION，第813~822局批复盘
            # 闭环实验）：战斗记录字符串只活在单局日志里，每批复盘都要重新
            # grep 原始日志才能数出「判死→获胜」占比，且 813~827 全窗口落在
            # 部署间隙内、审计位零显形后连基线都无从留存。这里把同一观测
            # （定义不变：实测口径判死入锁的战斗）按上批预注册的分桶口径
            # （esc 升级局单独计数）累计进 stats，供后续批次从 stats digest
            # 直接消费预注册规则（判死→获胜 ≥3 例或 >30% → 行为化收紧）。
            # 纯计数累计：不参与任何评分/阈值分支，race_audit 键缺失即零起账。
            _ra_won = not agg.get("died")
            _ra_stats = self.know.stats.get("race_audit")
            if not isinstance(_ra_stats, dict):
                _ra_stats = {}
                self.know.stats["race_audit"] = _ra_stats
            _ra_out_key = "won" if _ra_won else "died"
            _ra_stats["latched"] = int(_ra_stats.get("latched", 0) or 0) + 1
            _ra_stats[_ra_out_key] = int(_ra_stats.get(_ra_out_key, 0) or 0) + 1
            if _ra.get("esc"):
                _ra_esc_key = "esc_won" if _ra_won else "esc_died"
                _ra_stats[_ra_esc_key] = int(_ra_stats.get(_ra_esc_key, 0) or 0) + 1
        note += "（阵亡）" if agg.get("died") else ""
        self.ctx.combat_notes.append(note)
        log(f"[agent] 战斗{'失败' if agg.get('died') else '结束'}：{note}")
        self.ctx.combat_agg = None

    # ---------------- reflection ----------------

    def _finalize(self, victory: bool, floor: int) -> None:
        if self.ctx.run_finalized:
            return
        if bool(getattr(self.ctx, "human_assisted", False)):
            self._exclude_human_assisted_run(victory=victory, floor=floor)
            return
        rotation = getattr(self, "rotation", None)
        if rotation is not None and self.ctx.run_id != "run_unknown":
            try:
                if self.ctx.run_id in rotation.snapshot().finalized_run_ids:
                    self._finish_run_learning(self.know, self.ctx.run_id)
                    self.ctx.run_finalized = True
                    self.ctx.finalize_requested = False
                    self.ctx.pending_terminal_persistence = None
                    log(f"[agent] 忽略重复终局通知：{self.ctx.run_id} 已完成轮换结算")
                    return
            except CharacterRotationError as exc:
                log(f"[agent] 读取角色轮换终局账失败，保留本次终局：{exc}")
        # 幻影局守卫（第 50~51 局复盘）：真实对局至少有涅奥事件一条决策，
        # 零决策必为结算屏回声幻影——不得入账/存日志/触发复盘与 git 存档
        if not self.ctx.decisions and not victory:
            self._finish_run_learning(self.know, self.ctx.run_id)
            self.ctx.run_finalized = True
            self.ctx.finalize_requested = False
            log("[agent] ⚠ 忽略零数据幻影对局（重启落在结算屏的旧对局回声），不计入统计")
            return
        # 断线重连残缺局守卫（第 214 批复盘）：重连落在局中途的旧对局只剩尾部
        # 几条决策（LE23B03412FL：4 决策 F17 阵亡）——卡牌/房间/敌人归因全是
        # 断章取义，入账即污染演化证据与死亡榜。正常打到 F10+ 的对局决策数
        # 必然过百，「决策极少却楼层颇深」只可能是残缺局：忽略之，不入账不演化
        if not victory and floor >= 10 and len(self.ctx.decisions) < 10:
            knowledge, _profile = self._knowledge_for_run_learning(
                profile_id=str(getattr(self.ctx, "profile_id", "") or ""))
            if knowledge is None:
                knowledge = self.know
            try:
                # finish_run_learning restores an excluded journal before
                # unlinking it.  Do this before publishing run_finalized so a
                # failed cleanup remains retryable and fail-closed.
                self._finish_run_learning(knowledge, self.ctx.run_id)
            except Exception as exc:
                self.ctx.finalize_requested = True
                log(f"[agent] 残缺终局学习快照清理失败，保留结算页重试：{exc}")
                return
            self.ctx.run_finalized = True
            self.ctx.finalize_requested = False
            self.ctx.pending_terminal_persistence = None
            log(f"[agent] ⚠ 忽略断线重连残缺对局（仅 {len(self.ctx.decisions)} 条决策却到 F{floor}），"
                "不计入统计")
            return
        pending = getattr(self.ctx, "pending_terminal_persistence", None)
        if pending is None:
            # 终局前落库挂起的战斗聚合账（第 97~98 批复盘）：胜利结算屏触发的
            # settle 挂账后没有下一场战斗来冲销，必须在此补记，否则最后一战丢失
            self._flush_combat_agg()
            lesson = finalize_run(self.know, self.ctx, victory, floor)
            # finalize_run 是生涯 runs 计数的唯一提交点；以提交后的值校正序号，
            # 让 review_queue 的第 N 局能精确关联这份原始证据。
            self.ctx.run_number = int(
                self.know.stats.get("global", {}).get("runs", 0))
            self.ctx.profile_run_number = self.ctx.run_number
            pending = {
                "victory": bool(victory),
                "floor": int(floor),
                "lesson": lesson,
                "payload": {
                    "run_id": self.ctx.run_id,
                    "run_number": self.ctx.run_number,
                    **self._run_profile_metadata(),
                    "ascension": self.ctx.ascension,
                    "started_at": self.ctx.started_at,
                    "victory": bool(victory),
                    "floor": int(floor),
                    "decisions": self.ctx.decisions,
                    "combat_notes": self.ctx.combat_notes,
                    "attribution_tags": _durable_attribution_tags(
                        self.ctx.attribution_tags),
                },
            }
            self.ctx.pending_terminal_persistence = pending

        # Each operation is safe to retry with the same in-memory post-reflection
        # snapshot.  Do not mark the context finalized, leave GAME_OVER, increment
        # max_runs, or consume the character quota until all three have succeeded.
        terminal = None
        try:
            path = self.know.save_run_log(
                self.ctx.run_id, pending["payload"])
            self.know.save()
            if rotation is not None:
                character_id = pending["payload"].get("character_id")
                terminal = rotation.record_terminal(
                    self.ctx.run_id,
                    terminal_persisted=True,
                    character_id=character_id or None,
                )
            self._finish_run_learning(self.know, self.ctx.run_id)
        except Exception as exc:
            self.ctx.finalize_requested = True
            log(f"[agent] 终局落盘未完成，保留原生结算页稍后重试：{exc}")
            return

        self.ctx.run_finalized = True
        self.ctx.finalize_requested = False
        self.ctx.pending_terminal_persistence = None
        self.runs_played += 1
        victory = bool(pending["victory"])
        floor = int(pending["floor"])
        log("\n" + str(pending["lesson"]))
        log(f"[agent] 对局日志已保存：{path.name}")
        if terminal is not None:
            if terminal.advanced:
                log(f"[agent] 角色轮换已推进：{terminal.character} → "
                    f"{terminal.next_character}")
            else:
                log(f"[agent] 重复终局未推进角色轮换：{self.ctx.run_id}")
        self._mark_review_run_healthy()
        # 每局结束把复盘请求投入异步队列（工作线程消化，游玩不等待；多局积压会合并追及）
        if llm_review is not None:
            llm_review.enqueue_review(self, log=log)
        # 每局结束自动把进化记忆 commit+push 到仓库（失败不影响游玩）
        if autogit is not None:
            g = self.know.stats["global"]
            result = "胜" if victory else "负"
            autogit.commit_progress(
                f"chore(sts2-ascend): 第{g['runs']}局存档（{result} F{floor} 进阶{self.ctx.ascension}，生涯 {g['wins']}胜/{g['runs']}局）",
                log=log)
        # LLM 复盘提交了变更：终局证据已归档，但不能直接停在 GAME_OVER
        # 重启。新进程若仍看到同一终局帧，胜利局会被重复结算；先由旧进程
        # 完成返回菜单动作，再由主循环的空菜单安全边界以退出码 42 重启。
        if self.request_restart:
            log("[agent] 复盘变更已落盘，等待返回主菜单后重启大脑…")

    # ---------------- stuck-combat AI analysis ----------------

    def _launch_stuck_analysis(self, state: dict) -> None:
        """战斗超 100 回合：异步启动 AI 分析，判定 grind/offense/giveup。"""
        combat_identity = self.ctx.combat
        th = getattr(self, "_stuck_thread", None)
        if (th is not None and th.is_alive()
                and getattr(self, "_stuck_thread_combat", None) is combat_identity):
            return
        self._stuck_thread = threading.Thread(target=self._stuck_analysis_run,
                                              args=(state, combat_identity), daemon=True,
                                              name="stall-analysis")
        self._stuck_thread_combat = combat_identity
        self._stuck_thread.start()
        log("[stall] 战斗回合超限，已自主启动 AI 死循环分析…")

    def _commit_stall_verdict(self, verdict: str | None, combat_identity) -> bool:
        """Apply an asynchronous verdict only to the combat that requested it."""
        if combat_identity is None or self.ctx.combat is not combat_identity:
            log("[stall] 分析完成时战斗身份已变化，丢弃过期结论")
            return False
        if verdict == "giveup":
            self.ctx.force_giveup = True
        elif verdict == "offense":
            self.ctx.force_offense = True
        elif verdict == "grind":
            self.ctx.stall_grind_grace = True
        else:
            return False
        return True

    def _stuck_analysis_run(self, state: dict, combat_identity=None) -> None:
        try:
            if stop_requested():
                return
            import shutil
            binary = shutil.which("opencode")
            if not binary:
                log("[stall] 未找到 opencode，跳过 AI 分析（确定性兜底仍生效）")
                return
            combat = state.get("combat") or {}
            run = state.get("run") or {}
            player = combat.get("player") or {}
            turn = state.get("turn") or 0
            enemies = [{"id": e.get("enemy_id"), "hp": f"{e.get('current_hp')}/{e.get('max_hp')}",
                        "block": e.get("block"),
                        "intents": [i.get("intent_type") for i in e.get("intents", [])]}
                       for e in combat.get("enemies", [])]
            hand = [c.get("card_id") for c in combat.get("hand", [])]
            deck = [c.get("card_id") for c in (run.get("deck") or [])]
            # 牌堆信息（关键：攻击牌是否已被消耗光）
            av = state.get("agent_view") or {}
            avc = av.get("combat") or {}
            piles = {k: [x.get("line") for x in (avc.get(k) or [])]
                     for k in ("draw", "discard", "exhaust")}
            model = (self.cfg.get("llm") or {}).get("model", "kimi-for-coding/k3")
            prompt = (
                f"杀戮尖塔2自动游玩 agent 的一场战斗已经进行了 {turn} 回合仍未结束。"
                "请判断这是正常磨血还是死循环，并给出处置。\n\n"
                f"敌人: {json.dumps(enemies, ensure_ascii=False)}\n"
                f"我方: hp {player.get('current_hp')}/{player.get('max_hp')}, "
                f"格挡 {player.get('block')}, 能量 {player.get('energy')}\n"
                f"手牌: {json.dumps(hand, ensure_ascii=False)}\n"
                f"卡组: {json.dumps(deck, ensure_ascii=False)}\n"
                f"牌堆(抽/弃/消耗): {json.dumps(piles, ensure_ascii=False)}\n\n"
                "判定规则：\n"
                "- 敌人血量在持续下降，我方迟早能赢 → grind（正常磨血，继续打）\n"
                "- 我方手里/卡组里还有伤害手段但一直没正确用出来 → offense（应立即无视评分阈值强攻）\n"
                "- 我方已无任何伤害手段（攻击牌被消耗/转化殆尽——注意查看消耗堆！）→ giveup（死循环，应停止一切出牌快速送死结束本局）\n\n"
                "第一行严格输出：VERDICT: grind 或 VERDICT: offense 或 VERDICT: giveup\n"
                "第二行用一句中文给出理由。"
            )
            if stop_requested():
                return
            proc = subprocess.Popen(
                [binary, "run", "--model", model, "--dir", str(REPO_DIR), prompt],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace")
            deadline = time.monotonic() + 300
            while True:
                try:
                    out, _ = proc.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    if stop_requested() or time.monotonic() >= deadline:
                        proc.terminate()
                        try:
                            proc.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.communicate(timeout=5)
                        return
            out = out or ""
            m = re.search(r"VERDICT:\s*(grind|offense|giveup)", out)
            verdict = m.group(1) if m else None
            reason = out.strip().splitlines()[1][:120] if verdict and len(out.strip().splitlines()) > 1 else ""
            log(f"[stall] AI 死循环分析结论：{verdict or '未解析出'} {reason}")
            self._commit_stall_verdict(verdict, combat_identity)
        except Exception as exc:
            log(f"[stall] AI 死循环分析失败（确定性兜底仍生效）：{exc}")

    # ---------------- watchdog ----------------

    def _signature(self, state: dict):
        """Return the semantically relevant state used by the stall watchdog.

        The old four-field signature treated every tick in the same combat turn as
        identical.  Successful card plays commonly leave ``screen``, ``turn``, floor,
        and available action names unchanged, so HP/block/energy/hand/enemy progress
        could still trip escalation or even abandonment.  Keep the signature bounded
        to decision-relevant JSON fields and canonicalise mappings/action ordering so
        harmless key/list ordering does not masquerade as progress.
        """
        def freeze(value):
            if isinstance(value, dict):
                return tuple(sorted((str(k), freeze(v)) for k, v in value.items()))
            if isinstance(value, (list, tuple)):
                return tuple(freeze(v) for v in value)
            if isinstance(value, set):
                return tuple(sorted(freeze(v) for v in value))
            return value

        run = state.get("run") or {}
        combat = state.get("combat") or {}
        player = combat.get("player") or {}

        hand = []
        for card in combat.get("hand") or []:
            hand.append(tuple((key, freeze(card.get(key))) for key in (
                "index", "card_id", "instance_id", "uuid", "upgraded", "playable",
                "energy_cost", "costs_x", "requires_target", "valid_target_indices",
                "dynamic_values") if key in card))

        enemies = []
        for enemy in combat.get("enemies") or []:
            enemies.append(tuple((key, freeze(enemy.get(key))) for key in (
                "index", "enemy_id", "instance_id", "name", "current_hp", "max_hp",
                "block", "is_alive", "is_hittable", "powers", "intents")
                                 if key in enemy))

        # Non-combat screens can also update their choices without changing the set of
        # endpoint names.  These payloads are small and directly drive Policy routing.
        screen_payload = tuple((key, freeze(state.get(key))) for key in (
            "event", "reward", "selection", "map", "shop", "rest", "chest",
            "game_over", "modal", "unlock") if key in state)

        return (
            state.get("screen"), state.get("turn"),
            tuple(sorted(str(a) for a in (state.get("available_actions") or []))),
            tuple(run.get(key) for key in
                  ("floor", "current_hp", "max_hp", "gold", "ascension")),
            tuple(player.get(key) for key in
                  ("current_hp", "max_hp", "block", "energy")),
            tuple(hand), tuple(enemies), screen_payload,
        )

    def _watchdog(self, state: dict):
        sig = self._signature(state)
        if sig == self.last_sig:
            self.same_count += 1
        else:
            self.same_count = 0
            self.last_sig = sig
        if self.same_count == self.cfg["watchdog_escalate_after"]:
            log(f"[watchdog] 界面疑似卡死（{sig[0]}），尝试 proceed/confirm_modal")
            for act in ("proceed", "confirm_modal"):
                if act in state.get("available_actions", []):
                    return act
        if self.same_count >= self.cfg["watchdog_abandon_after"]:
            log(f"[watchdog] 长时间无进展，放弃本局")
            if "abandon_run" in state.get("available_actions", []):
                return "abandon_run"
            self.same_count = 0
        return None

    def _pending_review_restart_reason(self) -> str:
        """Return an in-memory or durable review epoch this Brain has not loaded."""
        if bool(getattr(self, "request_restart", False)):
            return "复盘线程已完成运行时代码闭环"

        try:
            marker = json.loads((KNOWLEDGE_DIR / "pending_restart.json").read_text(
                encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        # State-less markers are the backward-compatible committed format used by
        # Runner as well. A prepared transaction is never loadable.
        if marker.get("state") not in (None, "committed"):
            return ""
        review_commit = str(marker.get("review_commit") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40,64}", review_commit):
            return ""
        loaded_review = str(
            getattr(self, "_boot_review_commit", "") or "").strip().lower()
        if review_commit == loaded_review:
            return ""
        return (f"耐久复盘 marker {review_commit[:8]} 尚未由本进程加载"
                f"（当前 {loaded_review[:8] or 'none'}）")

    def _pending_review_restart_at_safe_boundary(self, state: dict) -> str:
        """Return the exact reload reason only at a truly empty menu boundary.

        The asynchronous reviewer can finish after run finalization and miss the
        next menu poll. Recheck immediately before every UI action so stale modules
        cannot embark another run. GAME_OVER is deliberately excluded: a new Brain
        may observe the same terminal frame and finalize a victory twice. The durable
        marker is compared only with Runner's import-time review epoch, never HEAD.
        """
        screen = str(state.get("screen") or "")
        if screen not in ("MAIN_MENU", "CHARACTER_SELECT"):
            return ""
        run = state.get("run") or {}
        run_finalized = bool(getattr(self.ctx, "run_finalized", False))
        # Menu screens are safe only when they really carry no active run and this
        # process has no unarchived context. A user-abandoned run is finalized by
        # _track's new-run detector, which performs its own pre-reset restart check.
        if (run or (getattr(self.ctx, "run_id", "run_unknown") != "run_unknown"
                    and not run_finalized)):
            return ""
        return self._pending_review_restart_reason()

    # ---------------- main loop ----------------

    def run(self) -> None:
        log("[agent] sts2-ascend 自主学习智能体启动")
        log(f"[agent] 知识库：{KNOWLEDGE_DIR}")
        self._start_live_dashboard()
        self._capture_boot_head()
        # Agent construction and boot handoff are complete.  This second stage is
        # intentionally outside Runner's repository lock: Knowledge migrations may
        # legitimately acquire that same cross-process lock while constructing us.
        ready_published = mark_pid_stage("brain", "ready")
        if os.environ.get("STS2_ASCEND_BOOT_ID") and not ready_published:
            raise RuntimeError("无法发布 Brain ready 启动握手")
        self._launch_quipper()
        if not self.ensure_game():
            self._dashboard_connection("stopped", "启动阶段收到停止请求")
            log("[agent] 启动阶段收到停止请求")
            return
        health = self.client.health()
        self._dashboard_connection("connected", f"mod v{health.get('mod_version')}")
        log(f"[agent] 已连接 mod v{health.get('mod_version')}（游戏 {health.get('game_version')}）")
        g = self.know.stats["global"]
        log(f"[agent] 生涯战绩：{g['wins']}/{g['runs']} 胜｜当前目标进阶 {self.know.progression['current_ascension']}")
        if llm_review is not None:
            llm_review.resume_review_queue(self, log=log)

        while True:
            if stop_requested():
                log("[agent] 收到全栈停止请求，停止决策循环")
                return
            if self.cfg["max_runs"] and self.runs_played >= self.cfg["max_runs"]:
                log(f"[agent] 达到 max_runs={self.cfg['max_runs']}，停止")
                return
            try:
                state = self.client.state()
            except ConnectionDown:
                self._dashboard_connection("disconnected", "与游戏失去连接")
                log("[agent] 与游戏失去连接，等待恢复…")
                if wait_for_stop(5):
                    return
                try:
                    if not self.ensure_game():
                        return
                except Exception as exc:
                    self._dashboard_connection("disconnected", f"重连失败：{exc}")
                    log(f"[agent] 重连失败：{exc}")
                continue
            except Exception as exc:
                self._dashboard_connection("degraded", f"状态读取异常：{exc}")
                log(f"[agent] 状态读取异常：{exc}")
                if wait_for_stop(2):
                    return
                continue

            # Read-only polling stays alive so the dashboard can show the exact
            # human-owned run, but no profile tracking, policy evaluation or POST
            # may occur while the global stop hotkey is active.
            if self._manual_control_blocks(state):
                self._dashboard_observe(
                    state, connection="paused",
                    message=f"人工接管中 · {RESUME_HOTKEY} 启动 Brain")
                if wait_for_stop(0.2):
                    return
                continue

            # An active run is always bound from the API's actual character.  On
            # CHARACTER_SELECT only, the durable next target selects the matching
            # profile so ascension/policy data stay character-local.
            self._bind_profile_for_state(state)
            self._dashboard_observe(state)

            # 策略热同步（第 123~124 局复盘）：长驻进程此前只在启动时执行
            # setdefault——复盘会话给 DEFAULT_POLICY 新增的键（如 122 批的
            # elite_grey_survival_floor）要等重启才可见，运行库 JSON 的冷修改
            # 也要等下一次 save 才被三方合并采纳。122 批核心修复因此在第
            # 123~126 局全程为死代码。每 20 秒吸收一次磁盘外部修改与代码
            # 新增默认键，让复盘产物分钟级生效而无需等待局间重启。
            now_ts = time.time()
            if now_ts - self._last_policy_refresh >= 20.0:
                self._last_policy_refresh = now_ts
                try:
                    changed = self.know.refresh_policy()
                    if changed:
                        log(f"[agent] 策略热同步生效：{', '.join(sorted(changed))}")
                except Exception as exc:
                    log(f"[agent] 策略热同步失败（忽略，不影响游玩）：{exc}")

            # A POST response may be lost after the game already applied the action.
            # Reconcile that action from this fresh GET *before* observation tracking:
            # event/map/rest snapshots and combat-end credit must exist before _track
            # consumes the resulting transition.
            ambiguous_result = self._reconcile_ambiguous_action(state)

            # Observe the state transition before asking Policy for the next action.
            # In particular, the first combat frame must create ctx.combat before
            # Policy imports the previous action's transactional success tags.  The
            # former decide→track order let the first successful card tag be imported
            # and then immediately erased by Policy's new-combat resets on the next
            # tick, reopening one-per-combat trials and corrupting race counters.
            self._track(state)

            # run finalization hook (policy asked for it on GAME_OVER)
            if self.ctx.finalize_requested and not self.ctx.run_finalized:
                go = state.get("game_over") or {}
                floor = go.get("floor") or (self.ctx.decisions[-1]["floor"] if self.ctx.decisions else 0)
                self._finalize(bool(go.get("is_victory")), int(floor or 0))
                continue

            # A response-lost POST can still be settling after the first fresh GET.
            # Observe each frame, but send no new action until three consecutive
            # polls fail to show its action-specific postcondition.
            if ambiguous_result == "wait":
                if wait_for_stop(self.cfg["poll_interval"]):
                    return
                continue

            forced = self._watchdog(state)
            if forced:
                decision = Decision(forced, {}, "看门狗介入", wait=1.0)
            else:
                decision = self.policy.decide(state, self.ctx)
            self._dashboard_propose(state, decision, watchdog=bool(forced))

            # 战斗回合超限（≥100）→ 大脑自主启动 AI 死循环分析（异步，不阻塞游玩）
            if getattr(self.ctx, "stall_analysis_needed", False):
                self.ctx.stall_analysis_needed = False
                self._launch_stuck_analysis(state)

            if decision.reason:
                floor = (state.get("run") or {}).get("floor", 0)
                log(f"[{time.strftime('%H:%M:%S')}] [{state.get('screen')}/F{floor}] {decision.reason}")

            if decision.action:
                # The reviewer may finish after finalization but before a menu
                # action starts the next run. Recheck as late as possible, directly
                # before client.act; live-run screens remain uninterrupted.
                restart_reason = self._pending_review_restart_at_safe_boundary(state)
                if restart_reason:
                    log(f"[agent] {restart_reason}；局间安全边界请求 runner 重启大脑…")
                    sys.exit(42)
                if stop_requested():
                    return
                if self._manual_control_blocks(state):
                    self._dashboard_outcome(
                        "paused", "人工接管已在动作发送前生效", decision)
                    continue
                try:
                    resp = self.client.act(decision.action, **decision.params)
                    status = resp.get("status", "?") if isinstance(resp, dict) else "?"
                    # "completed" 是 mod 对成功动作的标准返回（第 65~66 局复盘实锤）：
                    # 旧白名单漏掉它，导致每张成功打出的牌都被 note_action_failed
                    # 拉黑；叠加手牌位置索引前移，等于每打出一张牌就误杀一张
                    # 未出牌——65 局致死回合手握打击被禁玩阵亡、66 局 F5 双打击
                    # 被禁玩后 1 能量弃权白吃 15 意图
                    if status not in ("ok", "success", "pending", "stable", "completed"):
                        message = resp.get("message", "") if isinstance(resp, dict) else repr(resp)
                        log(f"  ↳ 动作 {decision.action} 返回 {status}: {message}")
                        # A syntactically valid HTTP response with an unknown status
                        # still cannot prove non-execution.  Reconcile from /state
                        # instead of poisoning retry/learning state.
                        self._remember_ambiguous_action(state, decision)
                    elif status == "pending" or resp.get("stable") is False:
                        # The server clicked/enqueued the action but its own settle
                        # wait expired.  This is accepted-but-unobserved: committing
                        # reward/potion/selection/event suppression now can skip the
                        # real resource on the next stale GET.  Hold the full
                        # Decision and commit only after an action-specific state
                        # postcondition appears.
                        self._remember_ambiguous_action(
                            state, decision, accepted=True)
                        response_state = resp.get("state")
                        if isinstance(response_state, dict):
                            self._reconcile_ambiguous_action(response_state)
                    else:
                        # HTTP 回执确认后才提交 credit/ctx 和记账。把记账异常与动作
                        # 失败分开：服务端已经执行成功时，不得反过来拉黑该动作。
                        try:
                            self._commit_successful_action(state, decision)
                            self._api_race_retry = None
                            self._dashboard_outcome("applied", f"服务端回执：{status}", decision)
                        except Exception as exc:
                            self._dashboard_outcome(
                                "applied", f"动作已生效；本地记账失败：{exc}", decision)
                            log(f"  ↳ 动作 {decision.action} 已成功，但本地记账失败：{exc}")
                except BrainControlPaused:
                    # The client owns the final pre-POST gate, closing the small
                    # interval between policy evaluation and this call.
                    self._mark_manual_takeover(state, source="client-action-gate")
                    self._manual_pause_active = True
                    self._dashboard_outcome(
                        "paused", "人工接管已阻止动作发送", decision)
                    self._dashboard_connection(
                        "paused", f"人工接管中 · {RESUME_HOTKEY} 启动 Brain")
                    log("[agent] 人工接管在最后发送闸门阻止了一次待执行动作")
                    continue
                except ConnectionDown:
                    self._dashboard_connection("disconnected", "动作执行时断线")
                    log("[agent] 动作执行时断线")
                    self._remember_ambiguous_action(state, decision)
                    if wait_for_stop(3):
                        return
                except ApiError as exc:
                    log(f"  ↳ 动作 {decision.action} 被 API 拒绝：{exc}")
                    if self._defer_api_error_once(state, decision, exc):
                        self._dashboard_outcome("retrying", f"状态刷新竞争：{exc}", decision)
                        log("  ↳ 判定为状态刷新竞争；刷新状态后重试一次，不拉黑动作/卡牌")
                    else:
                        # status=0 is a definitive local request construction
                        # failure (for example a non-serialisable payload), not a
                        # rejection returned by the game API.  Keep the two terminal
                        # states distinct for the live dashboard.
                        terminal = "failed" if int(getattr(exc, "status", 0) or 0) == 0 \
                            else "rejected"
                        self._dashboard_outcome(terminal, str(exc), decision)
                        self.policy.note_action_failed(decision.action, decision.tags)
                        self._note_signature_failure(decision.action, exc)
                    if wait_for_stop(self.cfg["action_settle"]):
                        return
                except Exception as exc:
                    log(f"  ↳ 动作 {decision.action} 失败：{exc}")
                    # Client normalises every definitive local/request failure to
                    # ApiError.  A remaining exception can therefore have happened
                    # after a custom/test transport sent the POST; prefer semantic
                    # reconciliation over poisoning permanent tried state.  Keep
                    # the legacy TypeError signature fuse so stale hot code still
                    # restarts/blacklists after three deterministic occurrences.
                    self._remember_ambiguous_action(
                        state, decision,
                        message=f"执行异常，等待语义对账：{exc}")
                    self._note_signature_failure(decision.action, exc)
                    if wait_for_stop(self.cfg["action_settle"]):
                        return
                if wait_for_stop(max(decision.wait, self.cfg["action_settle"])):
                    return
            else:
                if wait_for_stop(self.cfg["poll_interval"]):
                    return


def main() -> None:
    # UTF-8 console/log output so Chinese summaries stay readable when redirected
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    with pid_file("brain"):
        cfg = load_config()
        # Every Brain module and the complete config snapshot are now resident.
        # Runner can release its repository lock before Knowledge/Agent migration.
        imported_published = mark_pid_stage("brain", "imported")
        if os.environ.get("STS2_ASCEND_BOOT_ID") and not imported_published:
            raise RuntimeError("无法发布 Brain imported 启动握手")
        agent = Agent(cfg)
        completed = False
        try:
            agent.run()
            completed = True
        except KeyboardInterrupt:
            log("\n[agent] 手动停止，保存知识库…")
            completed = True
        finally:
            if completed and not stop_requested():
                request_stop("brain-normal-exit")
            if llm_review is not None:
                llm_review.shutdown_worker(log=log, timeout=30)
            if stop_requested():
                log("[agent] 全栈停止：保存知识库并退出")
            if agent.live_dashboard is not None:
                agent.live_dashboard.close(timeout=1.0)
            agent.know.save()


if __name__ == "__main__":
    main()
