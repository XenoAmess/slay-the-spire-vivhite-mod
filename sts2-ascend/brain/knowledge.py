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

_MISSING = object()  # 三方合并写盘的「键不存在」哨兵（不能用 None：None 是合法值）

DEFAULT_POLICY = {
    # --- combat ---
    "block_safety": 1.0,          # scales how much we value blocking
    "power_round_bonus": 6.0,     # flat bonus for powers in early rounds
    "kill_bonus": 12.0,           # bonus for securing a kill
    "free_card_bonus": 1.5,       # small bonus for 0-cost plays
    "play_threshold": 0.4,        # min score to bother playing a card
    # --- map ---
    "elite_min_hp_pct": 0.55,     # below this hp% elites are avoided
    "elite_soft_hp_pct": 0.62,    # 精英灰区下限：血量介于 soft~min 之间谨慎进精英（0.5 权重），不再一刀切规避
    "elite_grey_safety_mult": 1.5,  # 灰区精英悲观系数（第 86~87 批复盘）：均值战损×此值做尾部复核——87 局 86% 血进旧日雕像实测 -54 ≈ 均值 3 倍
    "elite_grey_proj_floor": 0.60,  # 灰区精英悲观投影线（旧舒适线语义，仅作旧库回退）：悲观投影战后血量低于此值 → 整条候选路径规避精英
    "elite_grey_survival_floor": 0.40,  # 灰区精英悲观生存线（第 122 局复盘）：复核问题改为「悲观情形是否仍能活命」——旧舒适线 60% 在实测先验下需入场血量 ≥95%~104%，灰区分支沦为死代码、精英被事实硬门在 ≥90% 血（122 局仅 45 次到访，遗物断供）
    "rest_urgent_hp_pct": 0.35,   # below this hp% rest sites are strongly preferred
    "rest_wary_hp_pct": 0.62,     # 血量警戒带：urgent 线以上、该线以下的灰区篝火获中等加权（第 54 局 47.5% 血商店压过篝火后被迫进精英）
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
    "rest_heal_fraction": 0.30,   # 篝火回血量估计（占最大生命比例）：溢出判断 + 路径血量模拟共用
    "smith_min_hp_pct": 0.55,     # 血量高于此值优先锻造升级（回血线过高 → 整局零锻造、卡组停在基础形态）
    # --- map path planning（全路径规划的血量模拟先验） ---
    "path_danger_priors": {"Monster": 8, "Unknown": 10, "Elite": 28, "Boss": 45,
                           "Event": 0, "Shop": 0, "Treasure": 0, "RestSite": 0, "Ancient": 0},
    "path_hp_floor_pct": 0.35,    # 路径投影进 Boss 血量低于此值 → 按差值惩罚
    "path_death_penalty": 100.0,  # 路径投影中途死亡的评分惩罚
    "elite_min_deck_cards": 4,    # 非基础牌少于此数时规避精英（卡组强度门槛，血量门槛之外的第二道闸）
    "path_act_scale": [1.0, 1.7, 2.3],  # 掉血先验按幕数放大：二幕起怪物伤害显著升级（先验是一幕场均）
    "unknown_gauntlet_act2_mult": 1.6,  # 二幕起 Unknown 可能是连环遭遇（如 THE_OBSCURA 三连战），额外风险乘数
    # --- 卡组构建 ---
    "deck_soft_cap": 20,          # 非基础牌软上限：超出后每张候选牌都贬值（膨胀稀释抽牌质量）
    "deck_overflow_penalty": 0.9, # 软上限之上每超一张的扣分
    "min_block_cards": 5,         # 格挡来源（含初始防牌）少于该数 → 格挡技能增值
    "pick_threshold_per_overflow": 1.5,  # 拿牌门槛随膨胀抬升：每超软上限一张，门槛 +1.5（第 65 局 24 张卡组实证：固定阈值压不住注水）
    # --- 卡组构建补丁（第 71 局复盘） ---
    "duplicate_pick_penalty": 3.0,  # 卡组已有≥2张同(基础)id牌后，每再拿一张的减分（71 局 SHRUG×5/FB×4 实证）
    "unplayed_min_picked": 4,       # 「拿了不打」判定的最小生涯拾取局数
    "unplayed_play_rate": 0.5,      # plays/picked ≤ 此值视为「拿了不打」（71 局 FLAME_BARRIER 13拿6打）
    "unplayed_card_penalty": 4.0,   # 「拿了不打」的牌在拾取端的额外减分
    # --- events ---
    "exploration_rate": 0.25,     # epsilon for trying unknown event options
    "exploration_decay": 0.97,    # per-run decay
    "exploration_min": 0.05,
    # --- potions ---
    "potion_hard_only": True,     # only spend potions in elite/boss or lethal danger
    # --- 战斗端补丁键（第 58~59 局复盘） ---
    "desperate_atk_mult": 1.3,    # 无甲可补的致死回合攻击提速：唯一活路是抢斩杀终结战斗
    "block_excess_value": 0.03,   # 超出当前意图缺口的溢出格挡每点评分（第 59 局 Boss 首回合溢出 34 甲白费整轮能量）
    # --- 战略层补丁键（第 60~61 局复盘） ---
    "boss_entry_min_hp_pct": 0.72,  # 进 Boss 血量要求线（第 86~87 批复盘 0.65→0.72）：近 10 局入 Boss ≥95% 的 1 胜 1 负、66%~79% 的 5 局全灭——生还分界实测在 ~95%，旧线明显偏低
    "boss_entry_penalty": 110.0,    # 路径投影入 Boss 血量每差满血 100% 的评分惩罚：让续航路线能压过消耗路线
    "hopeless_race_hp_frac": 0.6,   # 败局竞速启用血线：≤60% 最大生命才允许进入竞速模式
    "hopeless_race_horizon": 2.0,   # 按近期净损速率外推 N 回合内死亡 → 判定被动防守不可行
    # --- 战斗端补丁键（第 65~66 局复盘） ---
    "danger_comp_hard_death_rate": 0.30,  # 历史死亡率 ≥ 此值的敌人组合自动认定为硬仗（解锁药水投入；头号杀手 FUZZY+SHRINKER 44% 死亡率此前在普通怪房带药进坟）
    "danger_comp_stance_death_rate": 0.25,  # 姿态收紧专用的更低门槛（第 84~85 批复盘）：药水门槛 0.30 让头号杀手 FUZZY+SHRINKER（41战12死=29.3%）恰好漏网，enemy_stance 对它输出完全中性——防御姿态必须比药水解锁更灵敏
    # --- 组合感知与 Boss 前夜（第 62~64 局复盘） ---
    "comp_loss_stance_frac": 0.28,  # 敌方组合场均战损占最大生命比达到此值 → 即使死亡率<30%也视同高危收紧姿态
    "potion_comp_loss_frac": 0.30,  # 敌方组合场均战损占比达到此值 → 解锁增益/攻击药水（不再只认精英/Boss 房）
    "boss_eve_smith_min_samples": 3,  # Boss 前夜智能锻造所需的 Boss 分档最小样本数
    "boss_eve_smith_heal_mult": 1.0,  # Boss 前夜改锻造的战损线：场均Boss战损 ≥ 回血量×此倍数即视为"回血救不了"（79局复盘：旧条件 ≥满血 永远够不到，实测场均≈28）
    "boss_eve_smith_hp_pct": 0.85,  # Boss 前夜改锻造的入场血量线：多阶段战损按整场合并后（第 97~98 批复盘）整场战损≈65 必然≥回血量24，
                                    # 若只看战损条件会在 72% 血也去锻造、重演第 48 局惨案——回血在其价值过半溢出（血量+回血量×0.5≥满血）
                                    # 之前仍是有效投资，此时优先回血保入场线
    # --- Boss 攻坚（第 82~83 批复盘） ---
    "boss_atk_mult": 1.15,  # Boss 战攻击评分全局乘区：死亡榜前三均为 Boss、意图逐轮升级，缩短战斗即减伤
    # --- 输出饥饿感知（第 88~89 批复盘） ---
    "deck_burst_floor": 30.0,  # 卡组爆发吞吐量门槛：按「伤害/能耗」降序装满3能量的期望伤害低于此值视为输出饥饿（起步卡组≈18），高质攻击拿牌加分
    # --- 卡组单薄感知（第 90~91 批复盘） ---
    "deck_thin_core": 8,          # 非基础牌少于此数视为卡组单薄：抽5张的方差让爆发曲线无法稳定组装（91 局 16 张卡组进 Boss，长战后期手牌全是打击）
    "deck_thin_discount": 0.35,   # 单薄期每缺 1 张核心牌降低拾取门槛的幅度（门槛只升不降曾让 91 局整场只拿 6 张牌）
    # --- 斩杀竞速投影（第 90~91 批复盘，88~89 批遗留核对项⑤落地） ---
    "kill_race_enabled": True,
    "kill_race_min_enemy_hp": 80.0,  # 敌方剩余总血量超过此值才做投影（一幕Boss≈250/二幕精英级；小怪无需竞速账）
    "kill_race_margin": 1.5,         # 预计击杀回合数超出可存活回合数此余量 → 判定防守路线已被数学证伪
    "kill_race_atk_mult": 1.25,      # 竞速失败时攻击提速乘区（与 desperate/race_allin 不叠加）
    "kill_race_blk_mult": 0.70,      # 竞速失败时格挡权重乘区：买不到胜利的奢侈格挡把能量还给输出（致死当回合格挡仍由 lethal 分支兜底）
    # --- 执行端补丁键（第 79 局复盘） ---
    "desperate_confirm_ticks": 2,  # 孤注一掷观测确认窗：致死且无可负担格挡须连续 N tick 一致才允许孤注（防手牌渲染瞬时不完整触发假孤注，79局F23 实证）
    # --- 绝境投影与统计口径（第 96 局复盘） ---
    "rest_dire_proj_pct": 0.45,   # 绝境投影线：路径投影进Boss血量低于此值时，篝火回血优先于锻造（96局F22 在79%血锻造后 F23-37/F31强制精英阵亡）
    "proven_bad_margin": 3.0,     # 「统计实锤差牌」判定边际：场均低于全局均值此值即硬回避（旧 4.0 让 SETUP_STRIKE 9.4/BULLY 10.0 长期卡在缝隙反复被拿）
    # --- 拾取端学习信号治理（第 106 局复盘） ---
    "card_value_pick_cap": 3.0,   # 拾取端 card_value 贡献封顶（±）：outcome=到达层数是幸存者偏差噪声（能被拾取的前提就是活到奖励屏），
                                  # RAMPAGE 靠 +6 学习分在 55 局里自我强化循环拾取（106 局又拿 3 张）——学习信号保留方向、砍掉摆动幅度
    "burst_starve_bonus_base": 3.0,       # 输出饥饿对高质攻击的基础加分（原固定 +3）
    "burst_starve_bonus_extra_max": 4.0,  # 输出饥饿加分随缺口深度放大上限：106 局整场爆发 18~21(<门槛30) 只吃 +3，
                                          # 压不过 learned value 摆动与格挡牌基础分——Boss 战实测输出 ~10-15/回合全面输掉斩杀竞速；
                                          # 缺口越深加成越大（burst=0 时达 base+extra_max）
    # --- 路径投影罚分治理（第 107~108 批复盘） ---
    "path_penalty_saturation": 70.0,  # 投影罚分软饱和上限：死亡/血量线/Boss入场/中段精英罚分合计经 sat*tanh(raw/sat) 压扁。
                                      # 96 局去重只治了「同一坏结局记多次账」，没治「多候选同时吃满大额罚分」——
                                      # 108 局二幕开局全线 -159~-193、「预计进Boss血量 0%」，房间权重/休整加成等
                                      # 正信号在罚分竞赛中彻底失声，决策退化为比拼「投影死得早晚」这种高噪声量。
                                      # 小罚分近似线性（既有门槛翻转语义不变），大额罚分渐进饱和恢复分辨力
    "elite_mid_gate_depth_decay": 0.85,  # 中段精英投影罚分随深度衰减：逐节点选路下 depth 越深的精英越不是承诺
                                         # （中间岔口可改道），且休息回血会提高后续真实闸门的通过率——107 局 29% 血
                                         # 时唯一篝火因子树深处藏精英被罚到 -84 压过 Monster(-0.94)，放弃救命休息。
                                         # 近处精英（54 局商店下一层藏 F13 精英）衰减后仍保留主要威慑
    # --- 消耗螺旋治理（第 109 局复盘） ---
    "exhaust_play_penalty": 3.0,  # 消耗类牌逐次递增罚分：坚毅每打一次随机烧一张手牌，109 局 INKLET 三连波
                                  # 里 66 次坚毅把全部攻击牌烧成完美无限僵局（600+ 回合拖崩 runner）。
                                  # 硬上限另按卡组规模折算 max(1,min(4,deck//8))，此键只管「第 N 次的边际代价」
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
    "rooms": {},    # node_type -> {visits, outcome_sum, hp_lost_sum, damage_events}
    "rooms_act": {},  # "{node_type}@{act}" -> {hp_lost_sum, damage_events}（分幕掉血，第79局复盘新增）
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
    def __init__(self, root: Path, repair_phantoms: bool = True):
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
        # 三方合并写盘的基准点（第 90~91 批复盘）：加载即快照，save 时逐键对比
        self._policy_sync = dict(self.policy)
        # 迁移：旧版 rooms 条目只有 {visits, outcome_sum}，补齐掉血维度
        for e in self.stats["rooms"].values():
            e.setdefault("hp_lost_sum", 0.0)
            e.setdefault("damage_events", 0)
        # 迁移：旧版 enemies 条目没有 Boss 分档字段（第 63 局复盘新增：
        # 满血进 Boss 仍被仪式兽 85 点战损处决，需要 Boss 专属战损统计校准篝火策略）
        for e in self.stats.get("enemies", {}).values():
            e.setdefault("boss_encounters", 0)
            e.setdefault("boss_hp_lost_sum", 0.0)
            e.setdefault("boss_deaths", 0)
        # 迁移：分幕掉血统计（第 79 局复盘新增：跨幕混算的 Monster 场均 ~9.9
        # 让二幕投影系统性乐观——预测进 Boss 82% 实际两场战斗后剩 27%）
        self.stats.setdefault("rooms_act", {})
        # 一次性幻影局数据修复（自检加载真实库时应传 repair_phantoms=False，
        # 避免在运行中的大脑落盘前抢先改写/置标记）
        if repair_phantoms:
            self._repair_phantom_runs()

    def _repair_phantom_runs(self) -> None:
        """一次性修复：把历史上误入账的幻影局从生涯统计中扣除。

        幻影局指纹：runs/ 日志零决策且非胜利——真实对局至少有涅奥事件一条决策。
        每个幻影局曾使 global.runs/floors_total、progression.runs_by_ascension
        各 +1，并多衰减一次探索率。标记键 stats.phantom_repair_v1 防重复执行；
        以 runs/ 文件（不可变历史）为准而非计数器本身，对中途漂移稳健。
        """
        if self.stats.get("phantom_repair_v1"):
            return
        n_phantom, lost_floors, by_asc = 0, 0.0, {}
        for p in sorted((self.root / "runs").glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if d.get("decisions") or d.get("victory") or not d.get("run_id"):
                continue
            n_phantom += 1
            lost_floors += float(d.get("floor") or 0)
            asc = str(d.get("ascension", 0))
            by_asc[asc] = by_asc.get(asc, 0) + 1
        if n_phantom:
            g = self.stats["global"]
            g["runs"] = max(0, int(g.get("runs", 0)) - n_phantom)
            g["floors_total"] = max(0.0, float(g.get("floors_total", 0.0)) - lost_floors)
            rba = self.progression.setdefault("runs_by_ascension", {})
            for asc, cnt in by_asc.items():
                rba[asc] = max(0, int(rba.get(asc, 0)) - cnt)
            decay = float(self.policy.get("exploration_decay", 0.97)) or 0.97
            self.policy["exploration_rate"] = clamp(
                float(self.policy.get("exploration_rate", 0.25)) / (decay ** n_phantom), 0.0, 1.0)
            self.save()
        self.stats["phantom_repair_v1"] = True

    # ---------- persistence ----------

    def save(self) -> None:
        _save_json(self.root / "stats.json", self.stats)
        self._save_policy_merged()
        _save_json(self.root / "progression.json", self.progression)

    def _save_policy_merged(self) -> None:
        """policy.json 三方合并写盘：本进程演化值优先，外部冷修改保留。

        缺陷（第 90~91 批复盘定性）：异步 LLM 复盘在独立会话里改 policy.json，
        而运行中的大脑每局 finalize 会用内存旧值整体回写——86~87 批写入的
        boss_entry_min_hp_pct=0.72 曾被冲掉回 0.65，91 局又在 0.65 基础上
        演化到 0.67，冷修改两次被静默回滚，复盘决策凭空蒸发。

        以「上次同步点 _policy_sync」为基准逐键三方合并：
          内存值 == 基准值 → 该键本进程没动过 → 采纳磁盘值（外部修改实时生效）
          内存值 != 基准值 → 该键是本进程演化产物 → 保留内存值
        合并结果回填内存并刷新基准；磁盘不可读时退化为整体回写（旧行为）。
        stats/progression 只有本进程写入，维持整体写盘不变。
        """
        path = self.root / "policy.json"
        disk = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    disk = loaded
            except (json.JSONDecodeError, OSError):
                disk = {}
        base = getattr(self, "_policy_sync", None)
        if isinstance(base, dict):
            for k, disk_v in disk.items():
                mine = self.policy.get(k, _MISSING)
                if base.get(k, _MISSING) == mine and disk_v != mine:
                    self.policy[k] = disk_v  # 本进程未动过的键：外部修改实时生效
        _save_json(path, self.policy)
        self._policy_sync = dict(self.policy)

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

    def card_is_proven_bad(self, card_id: str) -> bool:
        """统计实锤的低价值牌：样本 ≥4 局且场均收益比全局均值低 proven_bad_margin+。

        动机（第 30~32 局复盘）：EXPECT_A_FIGHT(6.6分/5局)、BASH(7.2分/6局) 长期
        低于平均仍被反复拾取——learned bias（±4 上限）在奖励端 12+ 的启发式基础分
        面前是噪声。此判定供奖励端 -12 分硬回避，比人工 bias 更根本、随数据自演化。
        边际参数化（第 96 局复盘）：旧硬编码 4.0 让 SETUP_STRIKE(9.4)、BULLY(10.0)
        恰好卡在判定线外反复入组；默认收紧到 3.0，由 policy.json 可继续演化。
        """
        e = self.stats["cards"].get(card_id)
        if not e or e.get("picked", 0) < 4:
            return False
        margin = float(self.policy.get("proven_bad_margin", 3.0))
        return (e["outcome_sum"] / e["picked"]) < self.global_avg_outcome() - margin

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

    def enemy_stance(self, comp_id: str | None, node_type: str | None = None,
                     max_hp: int | None = None) -> dict:
        """按敌人组合历史战绩生成战斗姿态修正（无数据/低危→中性）。

        高危组合（样本≥3 且死亡率≥30%）自动收紧生存线：提高紧急血量阈值、
        压低进攻权重、抬高格挡权重。动机：FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
        10 战 6 死、场均掉血 25（全档案最致命），此前战斗端对它零感知，
        与打杂兵用同一套节奏反复送死。

        战损维度触发（第 62~64 局复盘新增）：死亡率不是唯一的危险信号——
        FLYCONID+SNAPPING_JAXFRUIT 13 战仅 15% 死亡率却场均掉血 25.8（32% 血条），
        中性姿态下引擎在 50 血对 26 意图时仍全攻半防，两回合被打穿。
        场均战损 ≥ comp_loss_stance_frac × 最大生命同样视同高危
        （需调用方传入 max_hp；不传则退化为纯死亡率判定，向后兼容）。

        Boss 战反转姿态（node_type="Boss"）：Boss 的死因是斩杀线不足——
        第 35 局仪式兽战拖到 8 回合被逐轮升级的意图磨死，压攻击只会拖长战斗、
        多吃整轮意图；高危 Boss 应保持甚至强化进攻速战速决。
        但第 36 局同族神官 Boss 战实证：格挡缺口才是压死骆驼的最后一根稻草
        （52 血进场、每回合 5~9 甲硬吃 13~27 意图）——高危 Boss 在提速的
        同时也要小幅抬格挡，少挨一刀多活一轮。
        """
        base = {"urgent_hp_pct": 0.45, "atk_mult": 1.0, "blk_mult": 1.0}
        e = (self.stats.get("enemies") or {}).get(comp_id or "")
        if not e:
            return base
        n = e.get("encounters", 0)
        deaths = e.get("deaths", 0)
        sev_parts = []
        # 死亡率门槛与斜率（第 84~85 批复盘校准）：旧门槛 0.30 + 斜率 1/0.30
        # 让头号杀手 FUZZY_WURM+SHRINKER_BEETLE（41战12死=29.3%）恰好漏网，
        # 姿态输出完全中性——防御姿态门槛必须低于药水解锁门槛（0.30），
        # 且斜率收紧到 1/0.15（40% 死亡率即接近满档）
        stance_rate_gate = float(self.policy.get("danger_comp_stance_death_rate", 0.25))
        if n >= 3 and deaths / n >= stance_rate_gate:
            sev_parts.append((deaths / n - stance_rate_gate) / 0.15)  # 死亡率越高收得越紧
        frac_thr = float(self.policy.get("comp_loss_stance_frac", 0.28))
        if n >= 3 and max_hp and e.get("hp_lost_sum", 0.0) / n >= float(max_hp) * frac_thr:
            loss_frac = e["hp_lost_sum"] / n / float(max_hp)
            sev_parts.append((loss_frac - frac_thr) / 0.12)  # 场均战损占比越高越危险
        if sev_parts:
            sev = min(1.0, max(sev_parts))
            if node_type == "Boss":
                base["atk_mult"] = round(1.0 + 0.10 * sev, 3)
                base["blk_mult"] = round(1.0 + 0.08 * sev, 3)
                base["danger"] = f"高危Boss（{n}战{deaths}死），速战速决"
            else:
                # 第 65~66 局复盘加强：头号杀手 FUZZY+SHRINKER（44% 死亡率，两局
                # 连续死于它）旧系数只换来格挡 +7%、紧急线 +7%，响应过于温和——
                # 紧急线 +0.20/格挡 +0.30；攻击压制维持 -0.15 不变（对磨血型组合
                # 拖长战斗同样致命，防而不缩才是正确姿态）
                base["urgent_hp_pct"] = round(0.45 + 0.20 * sev, 3)
                base["atk_mult"] = round(1.0 - 0.15 * sev, 3)
                base["blk_mult"] = round(1.0 + 0.30 * sev, 3)
                base["danger"] = f"高危组合（{n}战{deaths}死）"
        return base

    def combat_calibration(self) -> float:
        """敌人实测数据的 encounter 加权场均掉血 / 基准12 → 静态先验的整体校准系数。

        敌人统计（enemies）按战斗逐场累积、样本远多于 rooms，可先行校准：
        当前全场均值约 13~14 → 系数 ~1.1，Monster 先验 8→9、Elite 28→31。
        """
        en = self.stats["enemies"]
        tot_n = sum(e.get("encounters", 0) for e in en.values())
        if not tot_n:
            return 1.0
        mean = sum(e.get("hp_lost_sum", 0.0) for e in en.values()) / tot_n
        return clamp(mean / 12.0, 0.9, 1.5)

    def room_combat_rate(self, node_type: str) -> float:
        """房间战斗发生率：P(进入该类型房间后真的开战)。

        第 96 局复盘新增：damage_events 只统计「该房间真的打了仗」的样本
        （_settle_combat 才入账），而 Unknown/Event 类房间大量是事件/商店/宝箱——
        零战损的到访从未进入分母。生涯实测 Unknown 到访 148 次仅 33 次开战（22%），
        投影却按满额战斗计费，96 局二幕 3 个 Unknown 全是事件（其一还回血 +10），
        路径分饱和在 -165~-195、全图被投影成「进Boss血量 0%」，评分彻底失去分辨力。
        样本不足（到访 <5）时保守返回 1.0（视同必战，维持旧口径）。
        """
        e = self.stats["rooms"].get(node_type)
        if not e:
            return 1.0
        visits = int(e.get("visits", 0) or 0)
        if visits < 5:
            return 1.0
        return clamp(e.get("damage_events", 0) / visits, 0.05, 1.0)

    def room_damage_prior(self, node_type: str, static_prior: float) -> float:
        """路径模拟掉血先验的动态校准：rooms 实测场均掉血与静态先验加权混合。

        样本 <3 时回落静态先验 × 敌人统计整体校准系数；3~10 线性加权；
        ≥10 封顶 70% 实测权重（修复 Elite 静态先验 28 vs 实测 40+ 的低估）。
        发生率条件化（第 96 局复盘）：混合结果再乘 P(开战)，把先验语义从
        E[掉血|打了仗] 修正为路径投影真正需要的 E[掉血|到访]——Unknown 类
        房间按开战率 22% 折价后，二幕单个 Unknown 的期望掉血从 ~35 回落到 ~5，
        与实测一致（多数 Unknown 是零伤事件）。
        """
        e = self.stats["rooms"].get(node_type)
        if not e or e.get("damage_events", 0) < 3:
            cal = self.combat_calibration() if static_prior > 0 else 1.0
            return float(static_prior) * cal
        measured = e["hp_lost_sum"] / max(1, e["damage_events"])
        w = min(0.7, e["damage_events"] / 10.0)
        blended = (1.0 - w) * float(static_prior) + w * measured
        rate = self.room_combat_rate(node_type)
        return blended * rate

    def room_damage_prior_act(self, node_type: str, static_prior: float, act: int) -> float:
        """分幕掉血先验（第 79 局复盘新增）：优先用本幕实测场均掉血。

        跨幕混算的 Monster 场均 ~9.9 是"一幕便宜 + 二幕昂贵"的平均假象——
        二幕单场大失血型组合（SPINY_TOAD 本批 -40/-29）让投影系统性乐观，
        F20 选路预测进 Boss 82%，两场战斗后实际只剩 27%。有分幕样本（≥3）
        时以更高实测权重混合；无分幕数据时回落跨幕旧口径（向后兼容，无需迁移）。
        实测项同步乘战斗发生率（第 96 局复盘）：与跨幕口径保持同一语义
        （E[掉血|到访]），否则分幕样本一够数就会把发生率折扣重新冲掉。
        """
        e = self.stats.get("rooms_act", {}).get(f"{node_type}@{act}")
        if not e or e.get("damage_events", 0) < 3:
            return self.room_damage_prior(node_type, static_prior)
        baseline = self.room_damage_prior(node_type, static_prior)
        measured = e["hp_lost_sum"] / max(1, e["damage_events"])
        w = min(0.85, e["damage_events"] / 8.0)
        return (1.0 - w) * baseline + w * measured * self.room_combat_rate(node_type)

    def event_option_value(self, event_id: str, option_key: str) -> tuple[float, int]:
        """Return (score, sample_count). Score mixes hp/gold deltas and death penalty.

        加牌稀释代价（第 62~64 局复盘新增）：事件结算此前只记即时 hp/gold，
        「带走这颗蛋」把不可打出的鸟蛋混进卡组（Boss 战多次占据手牌 ✗ 位），
        结算却记 0/0 看似免费。每净增 1 张牌按 -2 计稀释代价，
        强正收益（hp/gold）仍可覆盖——拿真牌的事件不会被误伤。
        """
        opts = self.stats["events"].get(event_id, {})
        e = opts.get(option_key)
        if not e or not e["n"]:
            return 0.0, 0
        hp_avg = e["hp_delta_sum"] / e["n"]
        gold_avg = e["gold_delta_sum"] / e["n"]
        card_avg = float(e.get("card_delta_sum", 0.0)) / e["n"]
        death_rate = e["deaths"] / e["n"]
        return (hp_avg * 1.0 + gold_avg * 0.02 - card_avg * 2.0
                - death_rate * 40.0), e["n"]

    # ---------- online commits ----------

    def commit_enemy_fight(self, comp_id: str, hp_lost: float, won: bool, died: bool,
                           node_type: str | None = None) -> None:
        e = self.stats["enemies"].setdefault(comp_id, {"encounters": 0, "hp_lost_sum": 0.0, "deaths": 0, "wins": 0})
        e["encounters"] += 1
        e["hp_lost_sum"] += max(0.0, hp_lost)
        e["wins"] += 1 if won else 0
        e["deaths"] += 1 if died else 0
        # Boss 分档统计（第 63 局复盘新增）：Boss 战损远高于同名怪普通战
        # （仪式兽普通场均 32 vs Boss 战 85），混在一起会系统性低估 Boss 威胁，
        # 「Boss 前夜优先回血」的合理性判断依赖这份数据
        if node_type == "Boss":
            e["boss_encounters"] = e.get("boss_encounters", 0) + 1
            e["boss_hp_lost_sum"] = e.get("boss_hp_lost_sum", 0.0) + max(0.0, hp_lost)
            e["boss_deaths"] = e.get("boss_deaths", 0) + (1 if died else 0)

    def boss_loss_stats(self) -> tuple[float, int]:
        """全部分档 Boss 战的（场均掉血绝对值, 样本数）。

        第 63 局复盘新增：满血进 Boss 仍被仪式兽 85 点战损处决——
        「Boss 前夜优先回血」隐含假设回血量能覆盖预期战损；当实测 Boss
        场均战损 ≥ 满血时该假设崩塌，回血是无效投资，锻造缩短战斗才是活路。
        """
        tot_n = tot_loss = 0.0
        for e in self.stats.get("enemies", {}).values():
            tot_n += float(e.get("boss_encounters", 0) or 0)
            tot_loss += float(e.get("boss_hp_lost_sum", 0.0) or 0.0)
        return (tot_loss / tot_n if tot_n else 0.0), int(tot_n)

    def commit_room_damage(self, node_type: str, hp_lost: float, act: int | None = None) -> None:
        """按房间类型累计战斗掉血（供路径先验动态校准）。

        act 传入时同步写入分幕键（第 79 局复盘新增）：跨幕混算的场均掉血
        掩盖了二幕伤害升级，路径投影因此系统性乐观。旧 rooms 聚合键保持
        原样写入（learned_room_factor 等旧消费方不受影响）。
        """
        e = self.stats["rooms"].setdefault(
            node_type, {"visits": 0, "outcome_sum": 0.0, "hp_lost_sum": 0.0, "damage_events": 0})
        e["hp_lost_sum"] = e.get("hp_lost_sum", 0.0) + max(0.0, hp_lost)
        e["damage_events"] = e.get("damage_events", 0) + 1
        if act is not None:
            ra = self.stats.setdefault("rooms_act", {}).setdefault(
                f"{node_type}@{int(act)}", {"hp_lost_sum": 0.0, "damage_events": 0})
            ra["hp_lost_sum"] += max(0.0, hp_lost)
            ra["damage_events"] += 1

    def commit_event_option(self, event_id: str, option_key: str, hp_delta: float,
                            gold_delta: float, died: bool, deck_delta: int = 0) -> None:
        opts = self.stats["events"].setdefault(event_id, {})
        e = opts.setdefault(option_key, {"n": 0, "hp_delta_sum": 0.0, "gold_delta_sum": 0.0, "deaths": 0})
        e["n"] += 1
        e["hp_delta_sum"] += hp_delta
        e["gold_delta_sum"] += gold_delta
        e["card_delta_sum"] = float(e.get("card_delta_sum", 0.0)) + float(deck_delta)
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
