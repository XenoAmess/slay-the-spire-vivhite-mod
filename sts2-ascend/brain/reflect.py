"""Post-run reflection — the evolution step.

After every run ends (victory or death), this module:
  1. commits outcome statistics into the knowledge base (credit assignment),
  2. mutates bounded policy weights according to what killed us / what worked,
  3. appends a human-readable lesson to lessons.md,
  4. advances the ascension ladder on victory.
"""
from __future__ import annotations

import time

from knowledge import Knowledge, clamp

# bounded ranges for every mutable policy knob
BOUNDS = {    "elite_min_hp_pct": (0.35, 0.9),
    "rest_heal_threshold": (0.35, 0.85),
    "rest_urgent_hp_pct": (0.2, 0.6),
    "block_safety": (0.6, 2.1),
    "kill_bonus": (6.0, 20.0),
    "card_pick_threshold": (0.0, 6.0),
    "shop_relic_threshold": (0.0, 4.0),
    "power_round_bonus": (2.0, 10.0),
    "shop_min_gold": (60, 260),
    "boss_atk_mult": (1.0, 1.8),   # Boss 战攻击全局乘区的可演化区间（第 84~85 批复盘接入）
    # 第 86~87 批复盘接入：灰区精英悲观系数 / Boss 入场血量要求线
    "elite_grey_safety_mult": (1.0, 2.5),
    "boss_entry_min_hp_pct": (0.50, 0.90),
    # 第 138~141 批复盘接入：Boss 高血进场长战死证据的承接旋钮（拿牌端输出饥饿）
    "burst_starve_bonus_base": (0.0, 8.0),
    "burst_starve_bonus_extra_max": (0.0, 12.0),
    # 第 209 批复盘接入：burst_starve 双旋钮顶格（8/12，206~208 三连实证空转）
    # 后的同语义接替旋钮——加分数值顶死就加宽饥饿带，让更多卡组状态享受
    # 顶格加分（下限 25 防饥饿带消失，上限 45 防全卡组恒饥饿使加分失去区分度）
    "deck_burst_floor": (25.0, 45.0),
    # 第 228 批复盘接入：长战磨死证据的三级接替旋钮（仅 Boss 节点证据）——
    # burst_starve 双旋钮与饥饿带全部顶格后，把 Boss 前夜锻造线下调：
    # 0.65~1.00 带内入场血量已被十余局证伪为非生死变量 → 带内前夜回血无
    # 生存价值，下调即让更多前夜从一次性回血转成永久升级（145 场一幕 Boss
    # 实证：生还组场均前夜前锻造 1.67 次/升级牌打出 6.0 张 vs 阵亡组 1.14/3.4，
    # 零锻造局占阵亡组 31% vs 生还组 10%）。下限 0.45：低于此值的前夜回血
    # 服务的是「走到 Boss 之前别死」的真求生区，不许再压
    "boss_eve_smith_hp_pct": (0.45, 0.85),
    # 第 229 批复盘接入：普通怪房长战磨死证据的三级接替旋钮——burst_starve
    # 双旋钮与饥饿带全部顶格后，把常规篝火锻造线 smith_min_hp_pct 下调：
    # 222/228/229 连续三局活过一幕 Boss 后死于二幕走廊连战力竭（满血进二幕
    # 照样 5 场走廊 -80），而演化留痕清一色「输出饥饿证据停止吸收」——最高频
    # 新死亡模式的证据再次蒸发。语义与 Boss 侧前夜锻造线同构（一次性回血换
    # 永久升级，145 场 Boss 实证锻造次数/升级牌打出是最强生还区分项），且
    # 常规篝火服务的是每一场走廊战，战场归属正确（非 227 批警告的错位吸收）。
    # 下限 0.45 与 rest_urgent_hp_pct 对齐：低于此值的回血是真求生区，且有
    #     绝境投影/下一战预演双守卫兜底翻回回血，不许再压
    "smith_min_hp_pct": (0.45, 0.70),
    # 第 236 局复盘接入：爆毙/短时死亡通道的接替旋钮（兑现 231~233 批工作单——
    # 「药水提前交药时机 / 爆毙专属预演」二选一，本批选型前者）。block_safety
    # 顶格后，「没挡住」的证据改接药水提前交药线 potion_block_hp_pct：
    # 每 +0.05，硬仗中防御/回复药水的开喝血线提前 5%，放血判定同步放宽——
    # TNWN 局 40%~50% 血硬仗干瞪眼、拖到 10/80 才喝药的实证。下限 0.35 为
    # 原始默认；上限 0.80 防止交药线吞掉整个血条区间使防御/回复药水失去时机区分度
    "potion_block_hp_pct": (0.35, 0.80),
    # 第 237~238 批复盘接入：长战磨死证据的四级接替旋钮（兑现 229 批观察点⑤
    # 预案——常规/前夜锻造线 238~239 局双双触底，长战证据再次「彻底停止吸收」）。
    # 两条证据链分接两个不同旋钮，防双吃且战场归属各自正确：
    #   Boss 节点证据 → power_longfight_bonus_max：Boss 血池 250~400 时长战
    #     加成恒被 7.0 封顶（pool/30 早超顶），抬顶直接提高力量源（恶魔形态/
    #     点燃）在 Boss 长战的上场优先级——223 批实证 scaling 卡在最需要它的
    #     长战里上不了场。下限 4.0 防加成消失，上限 12.0 防能力牌压制一切。
    #   普通节点证据 → power_longfight_hp_div：走廊血池 50~150 远够不到加成
    #     封顶，抬上限无用；减小血池分母（每 −2）让同一血池折算更高加成，
    #     长战能力牌在走廊战早上场。下限 12.0 防小怪战也被高额加成扭曲节奏。
    "power_longfight_bonus_max": (4.0, 12.0),
    "power_longfight_hp_div": (12.0, 30.0),
    # 第 397~402 批复盘接入：输出饥饿接替链的第五级旋钮——burst_starve 双旋钮、
    # 饥饿带、双锻造线与长战加成全部顶格后，Boss 竞速败北证据改接竞速先验折算率：
    # 每次下调让 deck_burst×eff 的 DPS 开账更悲观 → 战斗端更早全攻提速、
    # 篝火端前夜更早转锻造（缩短战斗的两端杠杆同时前移）。下限 0.35 防
    #   先验归零使首回合竞速账永久全开。第709~713批复盘把上限从锚点 0.55
    #   放宽到 0.72：折算率语义是「先验产能→实战产出的兑现率」，713 局以被
    #   预演判死的卡组实战击败一幕 Boss，证明健康卡组兑现率远高于悲观时代
    #   赋值；而释放通道每局仅 +0.03，上限钉在 0.55 会让通道在中途「距锚点
    #   仅余」停摆、无法继续向实测收敛——悲观标签→入场线豁免→贫血进场是
    #   本批五局的核心死因链，校准速度本身就是生存变量
    "kill_race_prior_eff": (0.35, 0.72),
    # 第470局批复盘接入：短时死亡证据链的第三级接替旋钮——block_safety（全局
    # 防御权重）与 potion_block_hp_pct（药水交药线）双双顶格后，「没挡住」的
    # 证据改接高危组合防御姿态的格挡增益斜率 danger_comp_blk_boost：
    # 每次 +0.05 让 VANTOM/KIN双子/仪式兽这类生涯杀手组合（合计吞掉 ~43% 对局）
    # 的 enemy_stance 格挡姿态更硬（blk_mult = 1+斜率×sev，sev=1 时 1.30→最高1.60）。
    # 战场归属正确：证据来自具体组合战，回应也只作用于这些组合战，不再扰动全局。
    # 下限 0.30 即旧硬编码锚点；上限 0.60 防极端防御姿态彻底放弃输出拖长战斗
    "danger_comp_blk_boost": (0.30, 0.60),
}

# 爆毙重分类阈值（第 167~176 批复盘）：长战/爆毙此前只看回合数（≥4 即长战），
# 174 局 INKLET 4 回合整管 -64（每回合 16 血）被误判成「磨死」——kill_bonus
# 顶格期该证据直接丢弃。每回合失血 ≥ 此值时，死因语义是「没挡住」而非
# 「输出不足」，证据归 block_safety（短时爆毙通道）而非长战通道
BURST_DEATH_DPR = 14.0

# 竞速先验折算率的基准步长（第 397~402 批复盘起两通道共用；
# 换向阻尼 KILL_RACE_OSC_DAMP 以此为全速步长）
KILL_RACE_STEP = 0.03


def _kr_flip_damped_step(pol: dict, direction: int) -> tuple[float, str]:
    """竞速先验折算率的换向阻尼（KILL_RACE_OSC_DAMP，第 915~916 局批复盘新增）。

    lessons 950~968 台账：kill_race_prior_eff 在「Boss 竞速败北下调」与
    「F18+ 部分胜利释放」两通道间 ±0.03 逐局换向（0.57↔0.60↔0.63↔0.66↔0.69
    往复，数十次翻向零收敛）——两通道吸收的是同一物理量（一幕 Boss 击杀
    速率）的真实两面，逐局互相抵消形成极限环。阻尼规则：与上一次实际施加
    步长（kill_race_prior_eff_last_step，带符号净额）反向时，步长降为
    |last|/2（连续换向几何收敛）；同向连击或无历史保持全步长，真实证据
    不减速。返回 (步长, 追加到变更理由的阻尼留痕尾串)；
    knowledge/policy.json 写 kill_race_osc_damp: false 即整体关闭（回滚＝
    旧版全步长行为，零差异；last_step 记账照常保留供重启阻尼后对账）。
    """
    if not pol.get("kill_race_osc_damp", True):
        return KILL_RACE_STEP, ""
    try:
        last = float(pol.get("kill_race_prior_eff_last_step", 0.0) or 0.0)
    except (TypeError, ValueError):
        last = 0.0
    if last != 0.0 and (last > 0.0) != (direction > 0.0):
        step = min(KILL_RACE_STEP, abs(last) / 2.0)
        return step, (f"；换向阻尼：上一步 {last:+.2f}，"
                      f"步长 {KILL_RACE_STEP:.2f}→{step:.3f}")
    return KILL_RACE_STEP, ""


def _adj_burst_starve(know: Knowledge, changes: list[str], why_base: str, why_extra: str,
                      node_kind: str = "normal") -> bool:
    """长战磨死证据喂拿牌端输出饥饿双旋钮；双旋钮顶格后改接饥饿带宽度。

    顶格旋钮代谢（第 209 批复盘）：burst_starve 双旋钮 206~208 三连顶格
    （8.0/12.0 = 上限），留痕写着「证据改接拿牌端输出饥饿」而 _adj 实际
    空转——最高频死亡模式的证据再次蒸发（173~176 批「学习停摆」在接替
    旋钮上的复发）。加分数值顶死后，同语义方向是加宽饥饿带
    （deck_burst_floor）：更多卡组状态被认定输出饥饿，顶格加分因此在
    更多奖励屏真实生效；45 封顶后按节点分流三级接替——

      Boss 节点证据 → boss_eve_smith_hp_pct 下调（第 228 批复盘）：
        前夜锻造线每 -0.05，带内前夜从回血转锻造。语义忠实于证据本身：
        高血进场照样被磨死 = 回血买不到生还，唯一能带走的是永久战力。
        普通怪房长战死不得喂这条线（前夜锻造线与走廊战斗无关，
        错位吸收是 88~89/127~130 批反复清算过的老病）。
      普通节点证据 → smith_min_hp_pct 下调（第 229 批复盘）：常规篝火
        锻造线每 -0.05，45%~55% 血带的篝火从一次性回血转成永久升级。
        与 Boss 侧同构但战场归属正确：常规篝火服务的是走廊战本身，
        二幕连战力竭（222/228/229 满血进二幕 5 场 -80）正是它的证据。
        下限 0.45 与紧急回血线对齐，绝境投影/下一战预演双守卫照旧兜底。

    两条锻造线都触底（0.45）则按节点分流四级接替（第 237~238 批复盘）：
    Boss 证据抬能力牌长战加成上限（Boss 血池恒吃封顶，抬顶才有效），
    普通证据压长战加成血池分母（走廊血池够不到封顶，提折算率才有效）；
    双旋钮也顶格/触底才彻底封账并显式留痕（顶格代谢原则的递归终点）。

    返回是否成功吸收（False = 四级链全部顶格/触底，调用方负责下一级接替——
    第 397~402 批复盘起 Boss 侧由 kill_race_prior_eff 下调承接）。
    """
    _start = len(changes)
    pre = len(changes)
    _adj(know, "burst_starve_bonus_base", 0.3, changes, why_base)
    _adj(know, "burst_starve_bonus_extra_max", 0.5, changes, why_extra)
    if len(changes) == pre:
        pre2 = len(changes)
        _adj(know, "deck_burst_floor", 1.0, changes,
             "burst_starve 双旋钮顶格，输出饥饿带加宽（顶格加分惠及更多卡组状态）")
        if len(changes) == pre2:
            if node_kind == "boss":
                pre3 = len(changes)
                _adj(know, "boss_eve_smith_hp_pct", -0.05, changes,
                     "饥饿带顶格，Boss 长战磨死证据改接前夜锻造线"
                     "（带内回血无生存价值，一次性回血换永久升级）")
                if len(changes) == pre3:
                    pre4 = len(changes)
                    _adj(know, "power_longfight_bonus_max", 0.5, changes,
                         "前夜锻造线触底，Boss 长战磨死证据改接能力牌长战加成上限"
                         "（Boss 血池下加成恒被 7.0 封顶，抬顶让力量源更早压过打击上砧）")
                    if len(changes) == pre4:
                        changes.append("burst_starve 双旋钮、饥饿带、前夜锻造线与长战加成上限"
                                       "均顶格——输出饥饿证据停止吸收")
            else:
                pre3 = len(changes)
                _adj(know, "smith_min_hp_pct", -0.05, changes,
                     "饥饿带顶格，非 Boss 长战磨死证据改接常规锻造线"
                     "（一次性回血换永久升级，惠及每一场走廊战）")
                if len(changes) == pre3:
                    pre4 = len(changes)
                    _adj(know, "power_longfight_hp_div", -2.0, changes,
                         "常规锻造线触底，非 Boss 长战磨死证据改接能力牌长战加成折算"
                         "（走廊血池够不到加成封顶，减小血池分母让同血池折算更高加成）")
                    if len(changes) == pre4:
                        changes.append("burst_starve 双旋钮、饥饿带、常规锻造线与长战加成折算"
                                       "均顶格——输出饥饿证据彻底停止吸收")
    return len(changes) > _start


def _adj(know: Knowledge, key: str, delta: float, changes: list[str], why: str) -> None:
    lo, hi = BOUNDS[key]
    old = know.policy[key]
    new = clamp(old + delta, lo, hi)
    if abs(new - old) > 1e-9:
        know.policy[key] = new
        changes.append(f"{key}: {old:.2f} → {new:.2f}（{why}）")


def _adj_potion_line(know: Knowledge, changes: list[str], evidence: str) -> bool:
    """爆毙/短时死亡证据的接替旋钮（第 236 局复盘）：block_safety 顶格后，
    「没挡住」的证据改接药水提前交药线 potion_block_hp_pct——防御权重已经
    加不动，正确的响应不是把同一格挡再估值，而是让下一场硬仗更早把
    防御/回复药水喝掉（231~233 批工作单「药水提前交药时机」选项落地）。
    返回是否成功吸收（False = 接替旋钮也已顶格，调用方负责封账留痕）。
    """
    pre = len(changes)
    _adj(know, "potion_block_hp_pct", 0.05, changes,
         f"{evidence}且 block_safety 顶格——证据改接药水提前交药线"
         "（更早喝下防御/回复药水，不再加码已顶格的格挡权重）")
    return len(changes) > pre


def _adj_danger_comp_blk(know: Knowledge, changes: list[str], evidence: str) -> bool:
    """短时死亡证据链的第三级接替旋钮（第470局批复盘设计落地）：全局防御
    权重与药水交药线双双顶格后，「没挡住」的证据改接高危组合防御姿态的
    格挡增益斜率 danger_comp_blk_boost。

    战场归属论证：生涯死亡榜前三全是普通怪房杀手组合（VANTOM/KIN双子/
    仪式兽，合计 ~43% 对局死于此三者），短时阵亡几乎都发生在这些战局里
    ——证据来自组合战，回应也必须只作用于组合战。enemy_stance 的
    blk_mult = 1 + 斜率×sev，斜率每 +0.05 让 sev=1 的头号杀手格挡姿态从
    1.30 抬向 1.60，而中性组合与 Boss 姿态零波及。
    返回是否成功吸收（False = 三级链全部顶格，调用方负责封账留痕）。
    """
    pre = len(changes)
    _adj(know, "danger_comp_blk_boost", 0.05, changes,
         f"{evidence}且 block_safety/药水交药线均顶格——证据改接高危组合"
         "防御姿态斜率（杀手组合战的格挡姿态更硬，全局攻防平衡零波及）")
    return len(changes) > pre


def finalize_run(know: Knowledge, ctx, victory: bool, final_floor: int) -> str:
    """Commit statistics, evolve policy, write lessons. Returns the lesson text."""
    pol = know.policy
    outcome = float(final_floor) + (50.0 if victory else 0.0)

    died_to_enemy = None
    died_to_event = None
    if not victory:
        if ctx.died_to_event is not None:
            died_to_event = ctx.died_to_event[0]
        elif ctx.died_in_combat is not None:
            died_to_enemy = ctx.died_in_combat["comp_id"]

    # Run-end attribution is durable across a mid-run brain restart.  Do not read the
    # volatile credit_tags handshake stream here: replaying that stream would duplicate
    # novelty/UI/combat side effects, while omitting it used to erase all pre-restart
    # picks and route visits from the final learning update.
    attribution = getattr(ctx, "attribution_tags", [])
    picked_cards = [t[1] for t in attribution if t[0] == "card_pick"]
    picked_relics = [t[1] for t in attribution if t[0] == "relic_pick" and t[1]]
    visited_rooms = [t[1] for t in attribution if t[0] == "map_node"]

    know.commit_run_end(outcome, victory, picked_cards, picked_relics, visited_rooms,
                        died_to_enemy, died_to_event, raw_floor=final_floor)

    # ---------------- policy evolution ----------------
    changes: list[str] = []
    # 换向阻尼的运行内对账（_kr_flip_damped_step）：折算率的两个移动位点
    # （Boss 竞速败北下调 / F18+ 部分胜利释放）共用开局时的 last_step 做
    # 换向判定（last_step 只在局末按净步长落盘，同局两步互不触发阻尼），
    # _kr_net 累计本局对该旋钮的净施加步长
    _kr_net = 0.0
    # 僵局摆烂死（第 109 局复盘）：600+ 回合零掉血后主动停止防御送死，血量
    # 损失全部发生在「摆烂」之后——把它当成「格挡不足/击杀太慢」的证据是
    # 归因错位：109 局正是这样把 block_safety 1.05→1.10 推高的。摆烂死对
    # 攻防旋钮均无责，只留痕并把注意力指向卡组输出手段的丢失
    stall_death = bool((ctx.died_in_combat or {}).get("stall"))
    if not victory:
        if died_to_enemy and ctx.death_hp_pct_at_entry is not None and ctx.death_was_elite and not stall_death:
            if ctx.death_hp_pct_at_entry < pol["elite_min_hp_pct"] + 0.15:
                _adj(know, "elite_min_hp_pct", 0.05, changes,
                     f"精英战阵亡，进场血量 {ctx.death_hp_pct_at_entry:.0%}，提高精英回避线")
            # elite_min_hp_pct 已在 0.9 上限顶格空转（第 86~87 批复盘）——
            # 精英死亡信号改接灰区悲观系数：战损重尾证据越积越多，复核越保守
            # 第 135 局复盘修正：只有「灰区进场」（血量 < 硬线）的精英死亡才是
            # 灰区投影的证据。满血线以上进场仍阵亡（135 局 95% 血进精英被异蛙
            # 寄生虫 -76），病因在实战执行/卡组强度，灰区系数吸收纯属错位——
            # 0 胜生涯下胜利释放（-0.1）永不触发，这是又一条漂向 2.5 上限的
            # 单向棘轮，必须只喂它属于自己的证据
            if ctx.death_hp_pct_at_entry < pol["elite_min_hp_pct"]:
                _adj(know, "elite_grey_safety_mult", 0.2, changes,
                     "精英战灰区进场阵亡，灰区悲观投影系数上调")
            else:
                changes.append(f"精英战阵亡但满血线进场（{ctx.death_hp_pct_at_entry:.0%}≥"
                               f"{pol['elite_min_hp_pct']:.0%}）——证据指向实战执行/卡组强度，"
                               "灰区悲观系数不吸收")
        # 精英死亡进场血量分带遥测（第495~498局批复盘）：本批 4 局中 2 局死于
        # 精英战（-63/-71 单场），致命精英在选路端均被闸门否决过（「取损失最小项」
        # 被迫进场）或以低于软线的血量抵达——低血被迫进场与高血主动进场是两种
        # 不同病灶（前者无解需改行军，后者才是闸门/执行端问题），分账计数供
        # 后续批复盘定量归因。纯增量键，旧库缺键由 setdefault 补齐
        if died_to_enemy and ctx.death_was_elite:
            _band = know.stats["global"].setdefault(
                "elite_death_entry_band", {"low": 0, "healthy": 0})
            _soft_e = float(pol.get(
                "elite_soft_hp_pct", max(0.35, pol["elite_min_hp_pct"] - 0.15)))
            _bk = ("low" if (ctx.death_hp_pct_at_entry is not None
                             and ctx.death_hp_pct_at_entry < _soft_e) else "healthy")
            _band[_bk] = int(_band.get(_bk, 0)) + 1
        if died_to_enemy and not ctx.death_was_elite:
            if stall_death:
                rounds_s = int((ctx.died_in_combat or {}).get("rounds", 0) or 0)
                changes.append(f"僵局摆烂死（{rounds_s}回合）不计入 kill_bonus/block_safety"
                               "——死因是卡组失去输出手段（消耗螺旋/攻击耗尽），攻防旋钮均无责")
                # 第 244 批复盘修复：此处旧代码 early-return 并调用全仓库不存在的
                # lesson_tail（半成品重构残留，`if False else` 暴露改了一半）——
                # stall 死一旦发生即抛 NameError 崩掉大脑进程（靠 runner 重启兜底），
                # 且崩溃前跳过了卡牌 bias/探索衰减/进阶爬梯/lesson 落盘。改为跳过
                # 下方攻防线分流（stall 对攻防旋钮无责的教义不变），走统一收尾
            # 死亡模式分流（第 82~83 批复盘）：block_safety 此前是只升不降的
            # 单向棘轮（83 局 0 胜把它顶到 2.1 上限），而死亡榜前列全是血量
            # 170+ 的 Boss/高血组合——长战磨死的正确演化方向是进攻（更快清场
            # = 更少挨意图轮次），不是继续加防。按战斗时长分流：
            #   长战（≥4 回合）磨死 → 提升击杀奖励 + 小幅释放防御棘轮
            #   短时爆毙 → 维持旧逻辑上调防御权重
            rounds = int((ctx.died_in_combat or {}).get("rounds", 0) or 0)
            death_node = (ctx.died_in_combat or {}).get("node_type")
            # 爆毙重分类（第 167~176 批复盘）：回合数 ≥4 但每回合失血 ≥ 阈值的
            # 死亡是「没挡住」的爆毙（174 局 INKLET 4 回合 -64，dpr=16），不是
            # 「输出不足」的磨死——两类证据各有归属，混喂会让爆毙证据在
            # kill_bonus 顶格期凭空蒸发。旧记录无 hp_lost 字段时维持原口径
            _hp_lost = (ctx.died_in_combat or {}).get("hp_lost")
            _dpr = (_hp_lost / max(1, rounds)) if _hp_lost is not None else None
            burst_death = _dpr is not None and rounds >= 4 and _dpr >= BURST_DEATH_DPR
            if not stall_death and rounds >= 4 and not burst_death:
                # 步长按战斗时长分级（第 84~85 批复盘）：固定 ±0.05/+1 的释放
                # 速度要 ~30 局才能把 block_safety 从 2.1 拉回有效区间——
                # 8 回合 Boss 磨死的证据强度是 4 回合的两倍，步长应随之放大
                scale = min(3.0, rounds / 4.0)
                # 顶格治理（第 88~89 批复盘）：kill_bonus 13→14→15、block_safety
                # 2.05→2.00→1.95 连续单向漂移——0 胜生涯里「长战磨死」几乎每局
                # 触发，而长战的真正根因多是卡组输出不足（参数制造不出伤害），
                # 信号只会把两个旋钮单调推向边界（kill_bonus 上限 20 / 下限 0.6），
                # 顶死后重演 86~87 批诊断过的「空转旋钮」。演化前先查行程：
                # 余量不足一步时停止加码并显式留痕，把证据留给下一批复盘
                # 设计接替旋钮（顶格旋钮代谢原则的代码化）
                kb_step = 1.0 * scale
                kb_head = BOUNDS["kill_bonus"][1] - pol["kill_bonus"]
                if kb_head >= kb_step:
                    _adj(know, "kill_bonus", kb_step, changes,
                         f"长战磨死（{rounds}回合），提升击杀奖励加快清场")
                else:
                    changes.append(f"kill_bonus {pol['kill_bonus']:.2f} 距上限仅余 {kb_head:.2f}"
                                   f"(<步长{kb_step:.2f})，长战信号停止加码——顶格旋钮不再吸收证据")
                # 防御释放已从 Boss 长战分支移除（第 107~108 批复盘）：该规则是
                # 第 82~83 批引入的，当时还没有 boss_atk_mult 分轴；如今 Boss 攻坚
                # 已由专属旋钮（boss_atk_mult 提速 + boss_entry_min_hp_pct 入场线）
                # 承担，block_safety 再参与就形成跨语义振荡源——107 局 Boss 磨死
                # 降防（1.07→1.00）、108 局普通长战死升防（1.00→1.05），两种真实
                # 死亡信号让普通战的防御权重永远定不准。block_safety 只服务普通
                # 战斗语义，Boss 长战证据全部流向攻坚双轴
                if death_node == "Boss":
                    # Boss 攻坚乘区演化（第 84~85 批复盘新增）：死亡榜前六全是
                    # F17 一幕 Boss（84~85 批 10 局中 6 局），入场血量从 52%~95%
                    # 全数阵亡——瓶颈是战斗时长而非入场血量。Boss 长战磨死时
                    # 单独加码 boss_atk_mult（不动普通战斗的攻防平衡）
                    _adj(know, "boss_atk_mult", 0.05, changes,
                         f"Boss 长战磨死（{rounds}回合），攻坚乘区提速")
                    # 入场线证据分流（第 138~141 批复盘）：这条线的语义是「低血进场
                    # 扛不住」，只有低血进场被磨死才是它的证据。满血/高血进场照样
                    # 整管打空（63/124/137 局 ≥95% 三连、本批 138~141 四局 60%~100%
                    # 含教科书级满血局）时继续上调，只会逼智能体为攒血放弃精英/
                    # 商店/宝箱——卡组更弱、Boss 更打不过的正反馈死循环（安全棘轮
                    # 联立陷阱的复发形态）。与第 135 批 elite_grey_safety_mult 的
                    # 修正同构：各旋钮只吃属于自己的证据
                    _entry = ctx.death_hp_pct_at_entry
                    be_step = 0.02
                    be_head = BOUNDS["boss_entry_min_hp_pct"][1] - pol["boss_entry_min_hp_pct"]
                    # 证据上限（第 146~147 批复盘）：旧条件「进场<线即上调」让旋钮
                    # 自定义自己的证据阈值（循环自证）——143/146/147 局进场
                    # 66%/80%/100% 全部照输却仍三连 +0.02（0.82→0.88），加上此前
                    # 63/124/137 局 ≥95% 满血进场全数整管打空：0.65 以上带内入场
                    # 血量已被反复证伪为生死变量。0 胜生涯里该棘轮无释放通道，
                    # 必然漂到 0.90 上限并全程刷屏「优先续航路线」扭曲选路
                    # （147 局全程仅 ~6 场战斗的续航畸形路线进 Boss 即实证）。
                    # 只有真正极低血（<证据上限）进场磨死才是入场线的证据
                    _ev_cap = float(pol.get("boss_entry_evidence_hp_cap", 0.65))
                    if _entry is not None and _entry < min(pol["boss_entry_min_hp_pct"], _ev_cap):
                        if be_head >= be_step:
                            _adj(know, "boss_entry_min_hp_pct", be_step, changes,
                                 f"Boss 低血进场磨死（进场 {_entry:.0%}），入场血量要求线上调")
                        else:
                            changes.append(f"boss_entry_min_hp_pct {pol['boss_entry_min_hp_pct']:.2f} "
                                           f"距上限仅余 {be_head:.2f}(<步长{be_step:.2f})，停止加码")
                    else:
                        if _entry is None or _entry >= pol["boss_entry_min_hp_pct"]:
                            _band = (f"高血进场（{'?' if _entry is None else f'{_entry:.0%}'}"
                                     f"≥线 {pol['boss_entry_min_hp_pct']:.0%}）")
                        else:
                            _band = f"中带进场（{_entry:.0%}，≥证据上限 {_ev_cap:.0%}）"
                        changes.append(
                            f"Boss 长战磨死但{_band}——入场血量非生死变量，"
                            "入场线停止上调；证据改接拿牌端输出饥饿")
                        # 高血进场 Boss 长战死的真正根因是卡组击杀速率不足：
                        # 喂给拾取端输出饥饿旋钮，让拿牌对高质攻击更饥渴，
                        # 从源头缩短战斗（参数治不了的病从代码/结构侧治）；
                        # 双旋钮顶格后由 _adj_burst_starve 改接饥饿带宽度。
                        # 吸收判定按旋钮实值对比（终局封账消息也是 append，
                        # 不能拿 changes 长度当吸收依据）
                        _starved_knobs = ("burst_starve_bonus_base", "burst_starve_bonus_extra_max",
                                          "deck_burst_floor", "boss_eve_smith_hp_pct",
                                          "power_longfight_bonus_max", "power_longfight_hp_div",
                                          "smith_min_hp_pct")
                        _starved_before = {k: know.policy.get(k) for k in _starved_knobs}
                        _adj_burst_starve(
                            know, changes,
                            f"Boss 高血进场长战死（{'?' if _entry is None else f'{_entry:.0%}'}，"
                            f"{rounds}回合），拿牌端攻击饥饿基础分加码",
                            f"Boss 高血进场长战死（{rounds}回合），缺口越深纠偏上限越高",
                            node_kind="boss")
                        _starved_absorbed = any(know.policy.get(k) != v
                                                for k, v in _starved_before.items())
                        if not _starved_absorbed:
                            # 五级接替（第 397~402 批复盘）：饥饿链全顶格后，Boss 竞速
                            # 败北证据改接竞速先验折算率下调——deck_burst×eff 的 DPS
                            # 开账更悲观 → 战斗端更早全攻提速、篝火端前夜更早转锻造
                            # （本批五场前夜回血后的整管打空证明回血已零生存价值）
                            # 第 915~916 批复盘起步长过换向阻尼（_kr_flip_damped_step）
                            _kr_step, _kr_damp = _kr_flip_damped_step(pol, -1)
                            _kr_head = pol["kill_race_prior_eff"] - BOUNDS["kill_race_prior_eff"][0]
                            if _kr_head >= _kr_step:
                                _adj(know, "kill_race_prior_eff", -_kr_step, changes,
                                     "饥饿链全顶格，Boss 竞速败北证据改接竞速先验折算率下调"
                                     "（更早全攻提速+前夜更早转锻造）" + _kr_damp)
                                _kr_net += -_kr_step
                            else:
                                changes.append("kill_race_prior_eff 触底——Boss 输出不足证据彻底停止吸收")
                elif kb_head >= kb_step:
                    _adj(know, "block_safety", 0.05, changes,
                         f"非 Boss 战斗长战阵亡（{rounds}回合），死因是有效格挡不足而非龟防——上调防御权重")
                else:
                    # 第 127~130 批复盘：长战信号的主承接旋钮 kill_bonus 顶格后，
                    # 防御棘轮仍在代偿吸收——128/129/130 连续三局 +0.05
                    # （1.50→1.65），而生涯 0 胜使 -0.02 胜利释放永不触发，
                    # block_safety 必然单调漂到 2.1 上限后空转。长战证据的语义
                    # 是「战斗时长/输出不足」，92~93 批的防御加码本是与
                    # kill_bonus 并行的伴随项；主旋钮顶格后继续灌防御 = 顶格
                    # 证据的错位吸收（88~89 批原则：余量不足停止加码并留痕，
                    # 把证据留给复盘设计接替旋钮）。对意图升级型敌人，防御加码
                    # 拖长战斗反而是死因本身。短时爆毙（<4回合）分支不受影响
                    # ——那才是真正的「没挡住」证据
                    #
                    # 接替旋钮落地（第 167~176 批复盘）：173~176 连续四局长战死
                    # 证据在 kill_bonus 顶格后被整体丢弃（学习停摆）。与 Boss
                    # 高血进场长战死同构——「杀得慢」的证据喂给拿牌端输出饥饿
                    # （burst_starve 双旋钮，已顶格 8.0/12.0），从源头提高卡组
                    # 击杀速率；防御端仍不代偿。第 209 批：双旋钮顶格后由
                    # _adj_burst_starve 递归改接饥饿带宽度（deck_burst_floor）
                    changes.append(f"非 Boss 长战阵亡（{rounds}回合），kill_bonus 顶格——"
                                   "长战证据不再溢入 block_safety，防御棘轮停止代偿加码；"
                                   "证据改接拿牌端输出饥饿")
                    _adj_burst_starve(
                        know, changes,
                        f"非 Boss 长战磨死（{rounds}回合）且 kill_bonus 顶格，"
                        "攻击饥饿基础分加码",
                        f"非 Boss 长战磨死（{rounds}回合）且 kill_bonus 顶格，"
                        "缺口越深纠偏上限越高",
                        node_kind="normal")
            elif not stall_death:
                # 爆毙/短时死亡通道的顶格治理（第 231~233 批复盘）：block_safety
                # 顶格 2.1 后，233 局二幕 Boss 5 回合 -71（dpr 14.2≥14）撞上
                # 本分支——_adj 空转且零留痕，复盘只见「本局无参数调整」，与
                # 88~89 批顶格旋钮代谢原则（余量不足必须显式留痕）同一缺陷的
                # 静默版。长战分支 127~130 批就加了余量检查，本分支补上同款：
                # 有行程照旧吸收，无行程先走接替旋钮（第 236 局复盘选型落地），
                # 接替旋钮也顶格才显式封账留痕，把证据摆到复盘桌面上
                _bs_step = 0.05
                _bs_head = BOUNDS["block_safety"][1] - pol["block_safety"]
                if burst_death:
                    _burst_evidence = (f"高速失血爆毙（{rounds}回合掉血{_hp_lost:.0f}，"
                                       f"每回合{_dpr:.0f}≥{BURST_DEATH_DPR:.0f}）")
                    if _bs_head >= _bs_step:
                        _adj(know, "block_safety", _bs_step, changes,
                             f"{_burst_evidence}——按「没挡住」证据上调防御权重")
                    elif not _adj_potion_line(know, changes, _burst_evidence):
                        if not _adj_danger_comp_blk(know, changes, _burst_evidence):
                            changes.append(
                                f"{_burst_evidence}但 block_safety "
                                f"{pol['block_safety']:.2f}/药水交药线/组合姿态斜率"
                                "三级全顶格——爆毙证据停止吸收并留痕")
                else:
                    if _bs_head >= _bs_step:
                        _adj(know, "block_safety", _bs_step, changes, "普通战斗阵亡，略微上调防御权重")
                    elif not _adj_potion_line(know, changes,
                                              f"普通战斗短时阵亡（{rounds}回合）"):
                        if not _adj_danger_comp_blk(know, changes,
                                                    f"普通战斗短时阵亡（{rounds}回合）"):
                            changes.append(
                                f"普通战斗短时阵亡（{rounds}回合）但 block_safety "
                                f"{pol['block_safety']:.2f}/药水交药线/组合姿态斜率"
                                "三级全顶格——短时死亡证据停止吸收并留痕")
        # 事件致死的证据由统计层吸收（event_option_value 的死亡率惩罚），
        # 不再调整任何策略参数——旧 exploration_rate 是零消费的 legacy 旋钮，
        # 每局伪变异只在 lessons 里制造假「策略进化」噪声（已拆除）
        # 竞速先验折算率的部分胜利释放（第 494 局批复盘新增，第509~515局批复盘
        # 重开通道）：该旋钮的回收通道此前只挂整局胜利——0/494 生涯里被「Boss
        # 高血进场长战死」证据一路压到 0.37 触底后永不回升，形成死锁：折算率
        # 越低→竞速预演越悲观→战斗端越早全攻提速/前夜端回血价值被低估→多挨
        # 意图血贫进二幕→更难整局获胜→回收通道永远关闭。跨过幕界即「实战击败
        # 过一幕 Boss」的直接反证（F18+ 一幕、F34+ 连二幕），与整局胜利同向
        # 逐步释放。第509~515批实锤旧排除条件过宽：本批仅 512 局跨幕，且恰死在
        # 二幕 Boss 战——`_last_node != "Boss"` 把它也挡在门外，六局六次下调
        # 对零次释放，eff 钉死触底带。释放记的是一幕 Boss 战的反证（死于一幕
        # Boss 则 final_floor≤17，能行至 F18+ 本身就是证明），与最终 Boss 战的
        # 降账是两场独立战斗的证据：同局先释后降净额归零不是矛盾账目，
        # 是「一幕预演悲观被证伪 + 二幕长战确证」的诚实对冲。
        if final_floor >= 18:
            # 第 915~916 批复盘起步长过换向阻尼（_kr_flip_damped_step）
            _eff_step, _eff_damp = _kr_flip_damped_step(pol, 1)
            _eff_head = (BOUNDS["kill_race_prior_eff"][1]
                         - pol["kill_race_prior_eff"])
            if _eff_head >= _eff_step:
                _adj(know, "kill_race_prior_eff", _eff_step, changes,
                     f"行至 F{final_floor}（"
                     + ("一二幕" if final_floor >= 34 else "一幕")
                     + "Boss已实战击败）——竞速先验折算率获部分胜利释放" + _eff_damp)
                _kr_net += _eff_step
            else:
                changes.append(
                    f"kill_race_prior_eff {pol['kill_race_prior_eff']:.2f} "
                    f"距锚点仅余 {_eff_head:.2f}(<步长{_eff_step:.2f})——"
                    "部分胜利释放停止，视为已达健康锚点")
        # 换向阻尼的局末落盘：本局对该旋钮的净步长（同局先降后释按
        # 开局口径各判换向，落盘记净额）供下一局的换向判定；零净额
        # （触底/触顶空转或纯胜利局）不覆盖历史方向
        if _kr_net:
            pol["kill_race_prior_eff_last_step"] = _kr_net
    else:
        _adj(know, "block_safety", -0.02, changes, "胜利证明当前攻防平衡可行，轻微放开进攻")
        _adj(know, "elite_grey_safety_mult", -0.1, changes, "胜利证明当前精英规避强度足够，放宽灰区悲观系数")
        # 第 228 批复盘：前夜锻造线的胜利释放（与灰区悲观系数释放同构）——
        # 接替链有降必有升；只回收被棘轮压下去的部分（<0.65 锚点），防止
        # 单向演化残留，也避免健康值被胜利推过证据上限
        if pol["boss_eve_smith_hp_pct"] < 0.65:
            _adj(know, "boss_eve_smith_hp_pct", 0.05, changes,
                 "胜利证明当前前夜回血线可行，小幅上调回收")
        # 常规锻造线的胜利释放（第 229 批复盘，与前夜线同构）：只回收被
        # 普通怪房长战死证据压下去的部分（<0.55 默认锚点），健康值不被推高
        if pol.get("smith_min_hp_pct", 0.55) < 0.55:
            _adj(know, "smith_min_hp_pct", 0.05, changes,
                 "胜利证明当前常规回血线可行，小幅上调回收")
        # 药水提前交药线的胜利释放（第 236 局复盘，与锻造线释放同构）：
        # 接替链有降必有升；只回收被棘轮抬高的部分（>0.35 锚点），健康值不动
        if pol.get("potion_block_hp_pct", 0.35) > 0.35:
            _adj(know, "potion_block_hp_pct", -0.05, changes,
                 "胜利证明当前交药时机可行，小幅回收")
        # 能力牌长战加成双旋钮的胜利释放（第 237~238 批复盘，接替链有降必有升）：
        # 只回收被推离默认锚点的部分（上限 >7.0 / 分母 <30.0），健康值不动
        if pol.get("power_longfight_bonus_max", 7.0) > 7.0:
            _adj(know, "power_longfight_bonus_max", -0.5, changes,
                 "胜利证明当前长战加成上限可行，小幅回收")
        if pol.get("power_longfight_hp_div", 30.0) < 30.0:
            _adj(know, "power_longfight_hp_div", 2.0, changes,
                 "胜利证明当前长战加成折算可行，小幅回收")
        # 竞速先验折算率的胜利回收（第 397~402 批复盘，接替链有降必有升）：
        # 只回收被棘轮压低的部分（<0.55 默认锚点），健康值不动
        if pol.get("kill_race_prior_eff", 0.55) < 0.55:
            _adj(know, "kill_race_prior_eff", 0.03, changes,
                 "胜利证明当前竞速先验折算可行，小幅回收")
        # 高危组合防御姿态斜率的胜利回收（第470局批复盘，接替链有降必有升）：
        # 只回收被棘轮抬高的部分（>0.30 旧锚点），健康值不动
        if pol.get("danger_comp_blk_boost", 0.30) > 0.30:
            _adj(know, "danger_comp_blk_boost", -0.05, changes,
                 "胜利证明当前组合防御姿态可行，小幅回收")
        if ctx.rests_healed_at_full > 0:
            _adj(know, "rest_heal_threshold", -0.03, changes, "存在满血休息浪费，降低回血阈值")

    # card biases: cards picked often but with below-average outcomes get penalized
    # 「拿了不打」偏置封禁（第 228 批复盘）：outcome=到达层数是幸存者偏差——
    # DISINTEGRATION/MIND_ROT 这类不可打出的诅咒牌（生涯 7 拿 0 打/4 拿 0 打）
    # 靠「拿得晚→活得久」把 outcome 抬到 33 分、bias 一路 +0.2 涨到 +4 上限，
    # 复盘日志把它们供成「当前高价值卡牌」污染归因。判据与拾取端
    # unplayed_card_penalty 同一（picked≥4 且 plays ≤ play_rate×picked）：
    # 打不出去的牌不给正偏置，且逐局向负漂移；plays 字段缺失按 0 处理
    global_avg = know.global_avg_outcome()
    _unplayed_rate = float(pol.get("unplayed_play_rate", 0.5))
    for cid, e in know.stats["cards"].items():
        if e["picked"] >= 4:
            mean = e["outcome_sum"] / e["picked"]
            unplayed = float(e.get("plays", 0) or 0) <= _unplayed_rate * e["picked"]
            if unplayed:
                e["bias"] = clamp(e.get("bias", 0.0) - 0.3, -4.0, 4.0)
            elif mean < global_avg - 8:
                e["bias"] = clamp(e.get("bias", 0.0) - 0.3, -4.0, 4.0)
            elif mean > global_avg + 8:
                e["bias"] = clamp(e.get("bias", 0.0) + 0.2, -4.0, 4.0)

    # exploration_rate 每局衰减段已拆除：该旋钮零消费（事件选择为确定性
    # 欠采样轮转），逐局衰减与事件致死调整在 lessons 里制造假进化日志

    # ---------------- progression ladder ----------------
    prog = know.progression
    asc = ctx.ascension
    prog["runs_by_ascension"][str(asc)] = prog["runs_by_ascension"].get(str(asc), 0) + 1
    best = prog["best_floor_by_ascension"].get(str(asc), 0)
    prog["best_floor_by_ascension"][str(asc)] = max(best, final_floor)
    if victory:
        prog["wins_by_ascension"][str(asc)] = prog["wins_by_ascension"].get(str(asc), 0) + 1
        if asc >= prog.get("current_ascension", 0):
            prog["current_ascension"] = min(asc + 1, prog.get("max_ascension_goal", 10))
            changes.append(f"进阶提升：{asc} → {prog['current_ascension']}（胜利解锁更高难度）")

    # ---------------- lesson text ----------------
    # 「拿了不打」的牌不得进入高价值榜（第 228 批复盘）：DISINTEGRATION(7拿0打)
    # 曾以 33 分长期占据榜首误导复盘归因——榜单只反映「拿着它的局走得多远」，
    # 与卡牌本身价值无关。与偏置封禁同一判据
    def _is_played_card(e) -> bool:
        return float(e.get("plays", 0) or 0) > _unplayed_rate * e["picked"]

    top_cards = sorted(
        ((cid, e) for cid, e in know.stats["cards"].items()
         if e["picked"] >= 2 and _is_played_card(e)),
        key=lambda kv: -(kv[1]["outcome_sum"] / kv[1]["picked"]))[:5]
    top_ids = {c for c, _ in top_cards}
    worst_cards = [kv for kv in sorted(
        ((cid, e) for cid, e in know.stats["cards"].items()
         if e["picked"] >= 2 and cid not in top_ids and _is_played_card(e)),
        key=lambda kv: (kv[1]["outcome_sum"] / kv[1]["picked"]))[:3]]

    # 死因标注：失败但无死亡记录时不得标成"胜利"（第 51 局幻影局实证误导复盘）
    death_txt = (f"敌人组合 {died_to_enemy}" if died_to_enemy
                 else f"事件 {died_to_event}" if died_to_event
                 else ("无（胜利）" if victory else "无记录（数据缺失）"))
    lines = [
        f"\n## 第 {know.stats['global']['runs']} 局复盘（{time.strftime('%Y-%m-%d %H:%M')}）",
        f"- 结果：{'🏆 胜利' if victory else '💀 失败'}｜进阶 {asc}｜到达层数 {final_floor}｜当局评分 {outcome:.0f}",
        f"- 死因：{death_txt}",
        f"- 本局拿牌：{', '.join(picked_cards) if picked_cards else '无'}",
        f"- 本局遗物：{', '.join(picked_relics) if picked_relics else '无'}",
        f"- 战斗记录：{'; '.join(ctx.combat_notes[-6:]) if ctx.combat_notes else '无'}",
    ]
    if top_cards:
        lines.append("- 当前高价值卡牌：" + "，".join(f"{c}({e['outcome_sum']/e['picked']:.0f}分/{e['picked']}局)" for c, e in top_cards))
    if worst_cards:
        lines.append("- 当前低价值卡牌：" + "，".join(f"{c}({e['outcome_sum']/e['picked']:.0f}分/{e['picked']}局)" for c, e in worst_cards))
    if changes:
        lines.append("- 策略进化：" + "；".join(changes))
    else:
        lines.append("- 策略进化：本局无参数调整")
    lines.append(f"- 生涯战绩：{know.stats['global']['wins']}/{know.stats['global']['runs']} 胜，"
                 f"当前目标进阶 {prog['current_ascension']}")
    lesson = "\n".join(lines) + "\n"
    know.append_lesson(lesson)
    return lesson
