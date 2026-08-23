"""Main autonomous loop.

反复游玩 → 局势分析（每次决策打印中文局势摘要）→ 自我总结进化（每局结束 reflect）→
胜利后提升进阶继续进发。

Usage:  py -m brain            (from sts2-ascend/ directory)
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from client import ConnectionDown, Sts2Client
from knowledge import Knowledge
from policy import Policy
from reflect import finalize_run

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
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            log(f"[warn] config.json 解析失败，使用默认配置")
    return cfg


@dataclass
class RunContext:
    """Per-run tracking for credit assignment and reflection."""
    run_id: str = "run_unknown"
    ascension: int = 0
    started_at: str = ""
    credit_tags: list = field(default_factory=list)   # ("card_pick", id) etc.
    decisions: list = field(default_factory=list)     # full decision log
    combat: dict | None = None                        # active combat tracker
    combat_agg: dict | None = None                    # 同层多段战斗聚合账（第 97~98 批复盘）
    combat_notes: list = field(default_factory=list)
    pending_event: tuple | None = None                # (event_id, option_key, hp_before, gold_before, floor, deck_size_before)
    pending_event_own: tuple | None = None            # (hp, gold) 事件自身即时效果快照：离开事件屏瞬间采样（106 局复盘）
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
    rest_before_boss: bool = False   # 本次地图选择指向 Boss 前夜的篝火（_rest 消费）

    def reset_for(self, run_id: str, ascension: int):
        self.__init__(run_id=run_id, ascension=ascension, started_at=time.strftime("%Y-%m-%d %H:%M:%S"))


class Agent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.know = Knowledge(KNOWLEDGE_DIR)
        self.client = Sts2Client(ports=cfg["api_ports"])
        self.rng = random.Random(cfg["seed"]) if cfg.get("seed") is not None else random.Random()
        self.policy = Policy(self.know, self.rng)
        self.ctx = RunContext()
        self.last_sig = None
        self.same_count = 0
        self.runs_played = 0
        self.request_restart = False  # llm_review 改了代码后置位，回到主菜单时自重启
        self._last_policy_refresh = 0.0  # 策略热同步节流（第 123~124 局复盘）

    # ---------------- quipper（白绮碎碎念） ----------------

    def _launch_quipper(self) -> None:
        """启动白绮碎碎念进程（克隆音色低频短评）。它自己有活锁，重复拉起会自动退出。"""
        try:
            lock = KNOWLEDGE_DIR / "voice_quipper.lock"
            if lock.exists():
                try:
                    pid = int(lock.read_text().strip() or "0")
                    if pid > 0:
                        import ctypes
                        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                        if h:
                            ctypes.windll.kernel32.CloseHandle(h)
                            return  # 已在跑
                except (OSError, ValueError):
                    pass
            quipper = BASE_DIR / "tts" / "quipper.py"
            moss_ready = (BASE_DIR / "third_party" / "MOSS-TTS-Nano" / "models").exists()
            if not quipper.exists() or not moss_ready:
                return
            import shutil
            uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")
            if not Path(uv).exists():
                return
            creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                             | getattr(subprocess, "DETACHED_PROCESS", 0)
                             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            subprocess.Popen([uv, "run", "--no-project",
                              "--with", "onnxruntime", "--with", "sentencepiece",
                              "--with", "torch", "--with", "torchaudio",
                              "python", str(quipper)],
                             cwd=str(BASE_DIR), stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=creationflags, close_fds=True)
            log("[agent] 白绮碎碎念已拉起")
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

    def ensure_game(self) -> None:
        if self.client.discover():
            return
        if self._game_process_count() > 0:
            # game process exists but API not up yet (still booting / mod loading) — wait, don't relaunch
            log("[agent] 游戏进程已存在但 API 未就绪，等待加载…")
            self.client.wait_until_ready(timeout_s=300.0, poll_s=4.0)
            log(f"[agent] 游戏已就绪：{self.client.base_url}")
            return
        log("[agent] 游戏未运行，启动游戏…")
        exe = self.cfg["game_exe"]
        subprocess.Popen(["cmd", "/c", exe], cwd=str(Path(exe).parent), shell=False,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.client.wait_until_ready(timeout_s=300.0, poll_s=4.0)
        log(f"[agent] 游戏已就绪：{self.client.base_url}")

    # ---------------- run context tracking ----------------

    def _track(self, state: dict, decision) -> None:
        run = state.get("run") or {}
        run_id = state.get("run_id") or "run_unknown"
        screen = state.get("screen", "UNKNOWN")
        hp = run.get("current_hp", self.ctx.last_hp)
        gold = run.get("gold", self.ctx.last_gold)
        asc = run.get("ascension", self.ctx.ascension)

        # new run detection
        # GAME_OVER 屏必须排除（第 50~51 局复盘）：大脑重启落在上一局结算屏时，
        # 新进程会把旧 run_id 回声当成新对局，随后在 GAME_OVER 上二次结算出
        # 零决策幻影局（第 19/26/42/51 局四次实证，生涯统计被灌水 4 局 56 层）
        if run_id != self.ctx.run_id and screen not in ("MAIN_MENU", "GAME_OVER") and run:
            if self.ctx.run_id != "run_unknown" and not self.ctx.run_finalized and self.ctx.decisions:
                # previous run vanished without GAME_OVER (crash/abandon) — close it out as a loss
                log("[agent] 检测到上一局异常结束，按失败归档")
                self._finalize(victory=False, floor=self.ctx.decisions[-1].get("floor", 0))
            self.ctx.reset_for(run_id, asc)
            log(f"\n[agent] ===== 新对局开始：{run_id}（进阶 {asc}）=====")

        # combat enter/exit tracking
        # 战斗连续性：Boss/精英转阶段过场、结算弹层会让屏幕在 COMBAT↔MODAL 间闪断。
        # 旧逻辑按"离开战斗屏"立即结算并重建上下文，同一场 Boss 战被拆成 2~3 条统计
        # （第 36 批 DW7 局 F17 实证：一场掉血被记为 1/18/38 三笔）——场均掉血被稀释、
        # enemy_stance 死亡率失真、药水黑名单误重置。现在过场类屏幕只挂起不结算，
        # 回到同组合同层的战斗视为延续（ctx.combat 对象身份不变，药水黑名单随之保留）。
        if screen == "COMBAT":
            enemies_now = (state.get("combat") or {}).get("enemies", [])
            comp = "+".join(sorted({(e.get("enemy_id") or "?") for e in enemies_now if e.get("is_alive")}))
            node_type = next((t[1] for t in reversed(self.ctx.credit_tags) if t[0] == "map_node"), "Unknown")
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
        if self.ctx.pending_event is not None:
            if screen in ("COMBAT", "MODAL"):
                if self.ctx.pending_event_own is None:
                    self.ctx.pending_event_own = (hp, gold)
            elif screen != "EVENT":
                event_id, key, hp0, gold0, floor0, deck0 = self.ctx.pending_event
                own_hp, own_gold = self.ctx.pending_event_own or (hp, gold)
                through_combat = self.ctx.pending_event_own is not None
                victory_screen = screen == "GAME_OVER" and bool((state.get("game_over") or {}).get("is_victory"))
                died_here = screen == "GAME_OVER" and not victory_screen
                deck_delta = len(run.get("deck", []) or []) - deck0
                self.know.commit_event_option(event_id, key, own_hp - hp0, own_gold - gold0,
                                              died=(died_here and not through_combat),
                                              deck_delta=deck_delta)
                log(f"[agent] 事件结算：{event_id}/{key} → 生命 {own_hp - hp0:+}，金币 {own_gold - gold0:+}，"
                    f"卡组 {deck_delta:+d}"
                    + ("（经战斗延迟记账，死亡归因敌方组合）" if through_combat else "")
                    + ("（致死）" if died_here and not through_combat else ""))
                if died_here and not through_combat:
                    self.ctx.died_to_event = (event_id, key)
                self.ctx.pending_event = None
                self.ctx.pending_event_own = None

        # credit tags from the decision just made
        for tag in decision.tags:
            if tag[0] == "event_choice":
                self.ctx.pending_event = (tag[1], tag[2], hp, gold, run.get("floor", 0),
                                          len(run.get("deck", []) or []))
                self.ctx.pending_event_own = None  # 新选项重置自身效果快照
            elif tag[0] == "rest":
                if tag[1] == "heal" and hp >= run.get("max_hp", 1) - 2:
                    self.ctx.rests_healed_at_full += 1
            self.ctx.credit_tags.append(tag)

        # card play counting (cheap online learning)
        for tag in decision.tags:
            if tag[0] == "play_card" and tag[1]:
                self.know.commit_card_play(tag[1])

        self.ctx.last_hp, self.ctx.last_gold = hp, gold
        if decision.action:
            self.ctx.decisions.append({
                "t": time.strftime("%H:%M:%S"), "screen": screen,
                "floor": run.get("floor", 0), "hp": hp, "gold": gold,
                "action": decision.action, "params": decision.params, "reason": decision.reason,
            })

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
                           "node_type": node_type, "hp_start_pct": hp / max_hp}
        self.ctx.current_combat_is_hard = node_type in ("Elite", "Boss")
        self.ctx.stall_giveup = False  # 僵局摆烂标记按场清零（第 109 局复盘：归因隔离）
        # 高危组合自动升级硬仗（第 65~66 局复盘）：历史死亡率 ≥30% 的杀手组合
        # （FUZZY_WURM+SHRINKER_BEETLE 25战11死、KIN 双子 15战9死）大量出现在
        # 普通怪房，药水 premium 门此前对它们永不开启——两局均带药进坟。
        # 按统计实锤解锁增益/攻击药水投入，与 Elite/Boss 同一待遇。
        e = self.know.stats.get("enemies", {}).get(self.ctx.combat["comp_id"])
        rate_gate = float(self.know.policy.get("danger_comp_hard_death_rate", 0.30))
        if e and e.get("encounters", 0) >= 3 and e.get("deaths", 0) / max(1, e["encounters"]) >= rate_gate:
            self.ctx.current_combat_is_hard = True
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
                   "open": bool(split),
                   "obs_hp_pool": obs_pool, "obs_fire_sum": obs_fire,
                   "obs_fire_rounds": obs_fr}
            self.ctx.combat_agg = agg
        if died:
            # 致死必须立即落库：died_in_combat / 入场血量 / 精英标记供复盘归因，
            # 且死亡是整场战斗的绝对终结（不存在后续分段）
            self.ctx.died_in_combat = {"comp_id": agg["comp_id"], "node_type": agg["node_type"],
                                       "rounds": agg["rounds"], "floor": agg.get("floor"),
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
        self.know.commit_enemy_fight(agg["comp_id"], float(agg.get("hp_lost_sum", 0.0)),
                                     won=bool(agg.get("won")), died=bool(agg.get("died")),
                                     node_type=agg.get("node_type"),
                                     hp_pool=(float(agg.get("obs_hp_pool", 0.0)) or None),
                                     fire_sum=float(agg.get("obs_fire_sum", 0.0) or 0.0),
                                     fire_rounds=int(agg.get("obs_fire_rounds", 0) or 0))
        # 分幕掉血入账（第 84~85 批复盘接线）：act 参数按整场战斗的楼层归幕
        act_no = (int(agg.get("floor") or 1) - 1) // 17 + 1
        self.know.commit_room_damage(agg.get("node_type") or "Unknown",
                                     float(agg.get("hp_lost_sum", 0.0)), act=act_no)
        note = (f"F{agg['floor']} {agg['node_type']}战 掉血{int(round(agg['hp_lost_sum']))}"
                + ("（阵亡）" if agg.get("died") else ""))
        self.ctx.combat_notes.append(note)
        log(f"[agent] 战斗{'失败' if agg.get('died') else '结束'}：{note}")
        self.ctx.combat_agg = None

    # ---------------- reflection ----------------

    def _finalize(self, victory: bool, floor: int) -> None:
        if self.ctx.run_finalized:
            return
        self.ctx.run_finalized = True
        # 幻影局守卫（第 50~51 局复盘）：真实对局至少有涅奥事件一条决策，
        # 零决策必为结算屏回声幻影——不得入账/存日志/触发复盘与 git 存档
        if not self.ctx.decisions and not victory:
            log("[agent] ⚠ 忽略零数据幻影对局（重启落在结算屏的旧对局回声），不计入统计")
            return
        self.runs_played += 1
        # 终局前落库挂起的战斗聚合账（第 97~98 批复盘）：胜利结算屏触发的
        # settle 挂账后没有下一场战斗来冲销，必须在此补记，否则最后一战丢失
        self._flush_combat_agg()
        lesson = finalize_run(self.know, self.ctx, victory, floor)
        log("\n" + lesson)
        path = self.know.save_run_log(self.ctx.run_id, {
            "run_id": self.ctx.run_id,
            "ascension": self.ctx.ascension,
            "started_at": self.ctx.started_at,
            "victory": victory,
            "floor": floor,
            "decisions": self.ctx.decisions,
            "combat_notes": self.ctx.combat_notes,
        })
        log(f"[agent] 对局日志已保存：{path.name}")
        self.know.save()
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
        # LLM 复盘提交了变更：立即以退出码 42 请求 runner 重启（此时处于局间，重启无损）
        if self.request_restart:
            log("[agent] 复盘变更已落盘，请求 runner 重启大脑…")
            sys.exit(42)

    # ---------------- stuck-combat AI analysis ----------------

    def _launch_stuck_analysis(self, state: dict) -> None:
        """战斗超 100 回合：异步启动 AI 分析，判定 grind/offense/giveup。"""
        th = getattr(self, "_stuck_thread", None)
        if th is not None and th.is_alive():
            return
        self._stuck_thread = threading.Thread(target=self._stuck_analysis_run,
                                              args=(state,), daemon=True,
                                              name="stall-analysis")
        self._stuck_thread.start()
        log("[stall] 战斗回合超限，已自主启动 AI 死循环分析…")

    def _stuck_analysis_run(self, state: dict) -> None:
        try:
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
            proc = subprocess.run([binary, "run", "--model", model, "--dir", str(REPO_DIR), prompt],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=300)
            out = proc.stdout or ""
            m = re.search(r"VERDICT:\s*(grind|offense|giveup)", out)
            verdict = m.group(1) if m else None
            reason = out.strip().splitlines()[1][:120] if verdict and len(out.strip().splitlines()) > 1 else ""
            log(f"[stall] AI 死循环分析结论：{verdict or '未解析出'} {reason}")
            if verdict == "giveup":
                self.ctx.force_giveup = True
            elif verdict == "offense":
                self.ctx.force_offense = True
            elif verdict == "grind":
                self.ctx.stall_grind_grace = True
        except Exception as exc:
            log(f"[stall] AI 死循环分析失败（确定性兜底仍生效）：{exc}")

    # ---------------- watchdog ----------------

    def _signature(self, state: dict):
        return (state.get("screen"), state.get("turn"),
                tuple(state.get("available_actions", [])),
                (state.get("run") or {}).get("floor"))

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

    # ---------------- main loop ----------------

    def run(self) -> None:
        log("[agent] sts2-ascend 自主学习智能体启动")
        log(f"[agent] 知识库：{KNOWLEDGE_DIR}")
        self._launch_quipper()
        self.ensure_game()
        health = self.client.health()
        log(f"[agent] 已连接 mod v{health.get('mod_version')}（游戏 {health.get('game_version')}）")
        g = self.know.stats["global"]
        log(f"[agent] 生涯战绩：{g['wins']}/{g['runs']} 胜｜当前目标进阶 {self.know.progression['current_ascension']}")
        self._boot_ticks = 0  # 稳定运行 50 tick 后删除重启标记（向 runner 证明新代码可用）

        while True:
            if self.cfg["max_runs"] and self.runs_played >= self.cfg["max_runs"]:
                log(f"[agent] 达到 max_runs={self.cfg['max_runs']}，停止")
                return
            try:
                state = self.client.state()
            except ConnectionDown:
                log("[agent] 与游戏失去连接，等待恢复…")
                time.sleep(5)
                try:
                    self.ensure_game()
                except Exception as exc:
                    log(f"[agent] 重连失败：{exc}")
                continue
            except Exception as exc:
                log(f"[agent] 状态读取异常：{exc}")
                time.sleep(2)
                continue

            self._boot_ticks += 1
            if self._boot_ticks == 50:
                try:
                    (KNOWLEDGE_DIR / "pending_restart.json").unlink(missing_ok=True)
                except OSError:
                    pass

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

            # run finalization hook (policy asked for it on GAME_OVER)
            if self.ctx.finalize_requested and not self.ctx.run_finalized:
                go = state.get("game_over") or {}
                floor = go.get("floor") or (self.ctx.decisions[-1]["floor"] if self.ctx.decisions else 0)
                self._finalize(bool(go.get("is_victory")), int(floor or 0))
                continue

            forced = self._watchdog(state)
            if forced:
                decision = type("D", (), {"action": forced, "params": {}, "reason": "看门狗介入", "tags": [], "wait": 1.0})()
            else:
                decision = self.policy.decide(state, self.ctx)

            # 战斗回合超限（≥100）→ 大脑自主启动 AI 死循环分析（异步，不阻塞游玩）
            if getattr(self.ctx, "stall_analysis_needed", False):
                self.ctx.stall_analysis_needed = False
                self._launch_stuck_analysis(state)

            if decision.reason:
                floor = (state.get("run") or {}).get("floor", 0)
                log(f"[{time.strftime('%H:%M:%S')}] [{state.get('screen')}/F{floor}] {decision.reason}")

            self._track(state, decision)

            if decision.action:
                try:
                    resp = self.client.act(decision.action, **decision.params)
                    status = resp.get("status", "?")
                    # "completed" 是 mod 对成功动作的标准返回（第 65~66 局复盘实锤）：
                    # 旧白名单漏掉它，导致每张成功打出的牌都被 note_action_failed
                    # 拉黑；叠加手牌位置索引前移，等于每打出一张牌就误杀一张
                    # 未出牌——65 局致死回合手握打击被禁玩阵亡、66 局 F5 双打击
                    # 被禁玩后 1 能量弃权白吃 15 意图
                    if status not in ("ok", "success", "pending", "stable", "completed"):
                        log(f"  ↳ 动作 {decision.action} 返回 {status}: {resp.get('message', '')}")
                        self.policy.note_action_failed(decision.action, decision.tags)
                except ConnectionDown:
                    log("[agent] 动作执行时断线")
                    time.sleep(3)
                except Exception as exc:
                    log(f"  ↳ 动作 {decision.action} 失败：{exc}")
                    self.policy.note_action_failed(decision.action, decision.tags)
                    time.sleep(self.cfg["action_settle"])
                time.sleep(max(decision.wait, self.cfg["action_settle"]))
            else:
                time.sleep(self.cfg["poll_interval"])


def main() -> None:
    # UTF-8 console/log output so Chinese summaries stay readable when redirected
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    cfg = load_config()
    agent = Agent(cfg)
    try:
        agent.run()
    except KeyboardInterrupt:
        log("\n[agent] 手动停止，保存知识库…")
        agent.know.save()


if __name__ == "__main__":
    main()
