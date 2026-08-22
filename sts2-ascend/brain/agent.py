"""Main autonomous loop.

反复游玩 → 局势分析（每次决策打印中文局势摘要）→ 自我总结进化（每局结束 reflect）→
胜利后提升进阶继续进发。

Usage:  py -m brain            (from sts2-ascend/ directory)
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
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
    combat_notes: list = field(default_factory=list)
    pending_event: tuple | None = None                # (event_id, option_key, hp_before, gold_before, floor)
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
        if run_id != self.ctx.run_id and screen not in ("MAIN_MENU",) and run:
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
                    self._settle_combat(hp, won=True, died=False)
                    self._start_combat(run, comp, node_type, hp)
                else:
                    log("[agent] 战斗屏幕重连：同组合同层，按同一场战斗延续（统计不重复结算）")
        elif screen != "COMBAT" and self.ctx.combat is not None:
            victory_screen = screen == "GAME_OVER" and bool((state.get("game_over") or {}).get("is_victory"))
            died_here = screen == "GAME_OVER" and not victory_screen
            if not died_here and screen in ("MODAL", "UNKNOWN", "TIMELINE"):
                # 疑似转阶段过场：挂起等待重连；若下一帧是 MAP/REWARD 等真实流转再结算
                self.ctx.combat_bridge = (self.ctx.combat["comp_id"], self.ctx.combat["floor"], time.time())
            else:
                self._settle_combat(hp, won=not died_here, died=died_here)

        # event outcome commit on screen change
        if self.ctx.pending_event is not None and screen != "EVENT":
            event_id, key, hp0, gold0, floor0 = self.ctx.pending_event
            victory_screen = screen == "GAME_OVER" and bool((state.get("game_over") or {}).get("is_victory"))
            died_here = screen == "GAME_OVER" and not victory_screen
            self.know.commit_event_option(event_id, key, hp - hp0, gold - gold0, died=died_here)
            log(f"[agent] 事件结算：{event_id}/{key} → 生命 {hp - hp0:+}，金币 {gold - gold0:+}" + ("（致死）" if died_here else ""))
            if died_here:
                self.ctx.died_to_event = (event_id, key)
            self.ctx.pending_event = None

        # credit tags from the decision just made
        for tag in decision.tags:
            if tag[0] == "event_choice":
                self.ctx.pending_event = (tag[1], tag[2], hp, gold, run.get("floor", 0))
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
        max_hp = max(1, run.get("max_hp", 1))
        self.ctx.combat = {"comp_id": comp or "unknown", "hp_start": hp, "floor": run.get("floor", 0),
                           "node_type": node_type, "hp_start_pct": hp / max_hp}
        self.ctx.current_combat_is_hard = node_type in ("Elite", "Boss")
        danger = self.know.enemy_danger(comp)
        log(f"[agent] 进入战斗：敌方={comp}｜历史场均掉血 {danger:.1f}｜房间类型 {node_type}")

    def _settle_combat(self, hp: int, won: bool, died: bool) -> None:
        c = self.ctx.combat
        if c is None:
            return
        hp_lost = max(0, c["hp_start"] - hp)
        self.know.commit_enemy_fight(c["comp_id"], hp_lost, won=won, died=died)
        self.know.commit_room_damage(c.get("node_type", "Unknown"), hp_lost)
        note = f"F{c['floor']} {c['node_type']}战 掉血{hp_lost}" + ("（阵亡）" if died else "")
        self.ctx.combat_notes.append(note)
        if died:
            self.ctx.died_in_combat = c
            self.ctx.death_hp_pct_at_entry = c.get("hp_start_pct")
            self.ctx.death_was_elite = c.get("node_type") == "Elite"
            log(f"[agent] 战斗失败：{note}")
        else:
            log(f"[agent] 战斗结束：{note}（剩余 {hp} 血）")
        self.ctx.combat = None
        self.ctx.current_combat_is_hard = False

    # ---------------- reflection ----------------

    def _finalize(self, victory: bool, floor: int) -> None:
        if self.ctx.run_finalized:
            return
        self.ctx.run_finalized = True
        self.runs_played += 1
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

            if decision.reason:
                floor = (state.get("run") or {}).get("floor", 0)
                log(f"[{time.strftime('%H:%M:%S')}] [{state.get('screen')}/F{floor}] {decision.reason}")

            self._track(state, decision)

            if decision.action:
                try:
                    resp = self.client.act(decision.action, **decision.params)
                    status = resp.get("status", "?")
                    if status not in ("ok", "success", "pending", "stable"):
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
