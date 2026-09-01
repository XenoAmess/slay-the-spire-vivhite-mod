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

import copy
import hashlib
import json
import math
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from character_profiles import CharacterProfile
from native_knowledge import NativeGameKnowledge

SHRINK_K = 6.0  # shrinkage strength toward prior mean

_MISSING = object()  # 三方合并写盘的「键不存在」哨兵（不能用 None：None 是合法值）
_SAVE_LOCKS_GUARD = threading.Lock()
_SAVE_LOCKS: dict[str, threading.Lock] = {}
_POLICY_TX_LOCKS_GUARD = threading.Lock()
_POLICY_TX_LOCKS: dict[str, threading.RLock] = {}

_READ_RETRIES = 8
_READ_RETRY_BASE_SECONDS = 0.01


def relic_stats_key(value: object) -> str | None:
    """Return a safe persistent relic identity, or ``None`` when text is corrupt.

    The HTTP client decodes API responses as strict UTF-8, but U+FFFD can still
    already be present in a valid JSON string when an upstream localized label
    was decoded with replacement.  Relic statistics use their identity as a JSON
    object key, so accepting that sentinel turns one damaged display label into a
    permanent, unmergeable relic record.  Keep existing historical rows intact,
    but never create or increment such a key from a new run.
    """
    if not isinstance(value, str):
        return None
    key = value.strip()
    if not key or "\ufffd" in key:
        return None
    return key


DEFAULT_POLICY = {
    "boss_race_slippery_joint_guard": True,  # Boss combat: do not reopen a doomed race when live Slippery powers make static DPS optimistic
    "boss_race_feasible_hp_buffer": 0.30,  # 前夜竞速预演可行侧生存余量；0 回落旧口径
    "boss_race_joint_flip_max_ttk_ratio": 1.5,  # 联合能量复核翻盘比上限（第1098~1110局批复盘）：
    # 击杀所需回合数超过 满血可存活回合数×此比值 时，前夜预演与 Boss 战斗端
    # 复核的「存在可行攻防分配」均不予放行（静态火力+期望格挡产能对滚雪球
    # Boss 系统性乐观）；<=0 严格回落旧口径（复核可直接翻盘）
    "longfight_race_joint_flip_max_ttk_ratio": 1.5,  # 长战大血池的非 Boss 战斗端翻盘比上限：
    # 当前存活敌血池达到 power_commit_pool_min 时，静态联合复核不能把已判负的
    # 斩杀竞速重新放行；0 严格回滚该长战闸，不影响 Boss 专用键
    "boss_race_combo_gate_require_all_known": True,  # Boss 未知时，组合级翻盘须让全部
                                                     # 已有重复实证的同幕组合可行；False 回落
                                                     # 旧的「任一组合可行即放行」口径（1132/1137/1147
                                                     # 三例 KIN 实际阵亡暴露了存在性放行的风险）
    # --- combat ---
    "block_safety": 1.0,          # scales how much we value blocking
    "power_round_bonus": 6.0,     # flat bonus for powers in early rounds
    "power_longfight_bonus_max": 7.0,  # 能力牌长战加成上限（第 223 批复盘）：按存活敌血池线性折算——
                                       # Boss/大血池长战中力量源（恶魔形态类）早一回合上场多一档全程增益，
                                       # 旧固定 6.0/1.5 在 Boss 攻坚 ×1.8 下整场输给攻击牌（DEMON_FORM 2拿0打）
    "power_longfight_hp_div": 30.0,    # 长战加成的血池除数：每 30 点存活敌血 +1 分（250 血 Boss 封顶 7）
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
    "shop_potion_gold": 60,       # 药水档（第 248 批复盘）：低于 shop_min_gold 但够买药水时商店保留中等权重——药水是爆毙通道唯一稳定补给，140 硬线曾让低金币段商店整体离场（237 局 120+ 金死携从未进店）
    "room_weights": {"Monster": 1.2, "Elite": 2.0, "RestSite": 1.0, "Shop": 1.1,
                     "Treasure": 1.4, "Unknown": 1.15, "Event": 1.1, "Boss": 10.0},
    "lookahead_weight": 0.35,     # 1-step lookahead contribution on map
    # --- rewards / shop ---
    "card_pick_threshold": 2.0,   # min value to take a reward card (skip otherwise)
    "rarity_bonus": {"Common": 0.0, "Uncommon": 0.8, "Rare": 1.6},
    # 卡牌奖励探索（仅用于可跳过的奖励 offer，不影响升级/删牌/战斗选牌）：
    # 在原始启发式近优、严格正价值且非诅咒/状态/不可打出的候选中，用 UCB
    # 给欠采样牌有限试用机会。每局配额是硬上限，避免“探索”反向注水。
    "card_exploration_enabled": True,
    "card_exploration_run_quota": 2,
    "card_exploration_min_picks": 2,
    "card_exploration_near_best_margin": 2.5,
    "card_exploration_ucb_scale": 1.0,
    "card_exploration_min_value": 1.0,
    # 遗物探索只在学习价值近优的候选之间轮转；明确负面描述、已证伪遗物和
    # 显著机会成本都不会因“新”而越过。宝箱/商店合计每局至多一次。
    "relic_exploration_enabled": True,
    "relic_exploration_run_quota": 1,
    "relic_exploration_sample_cap": 1,
    "relic_exploration_near_best_margin": 0.75,
    "relic_exploration_min_value": -0.5,
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
    "path_graveyard_hp_pct": 0.10,  # 近死带（第 255~257 批次复盘）：投影途中血量跌破此线即按
                                    # 凹陷深度折价——257 局投影「精英战后仅剩 3%」的路径仍压过
                                    # 安全候选，实战 -51 阵亡；3% 不是计划是运气，先验是均值
    "path_graveyard_penalty": 150.0,  # 近死带折价系数：每 1.0 比例凹陷深度的罚分
    "path_tail_hp_band_pct": 0.62,   # 尾部定价血量带（第 258~262 批次复盘）：投影血量跌破此带后，
                                     # 战斗先验按距带顶深度向实测单场最差战损（hp_lost_max）混合——
                                     # 262 局 49% 血进 Monster 投影仅 ~9 点（场均账），实战 -39 阵亡；
                                     # 带内的问题是「坏一场能不能活」而非「平均掉几滴」。满血段零影响
    "path_tail_loss_frac": 0.5,      # 尾部入账折价：最差样本是极值不是常态，半价折算后再与
                                     # 场均先验按深度线性混合（全价等于按最坏一场定价所有战斗）
    "path_tail_veto_penalty": 45.0,  # 单场尾部生存复核罚分基数（第 266 局批次复盘）：投影对
                                     # Monster/Unknown 用实测单场最差（hp_lost_max，全价不折半）
                                     # 复核「坏一场能不能活」——最坏打完跌破近死带即按缺口深度
                                     # ×此值加性罚分。尾部定价只抬均价且随血带深度缩水，266 局
                                     # 54% 血规划时留痕「先验9→11（最差48）」，下一战实际 -43
                                     # 阵亡：均价涨 2 点回答不了生还问题。Elite 不入此闸
                                     # （灰区悲观复核已覆盖同构风险，叠加会把精英挤出地图）
    "path_starve_loss_frac": 0.35,   # 输出饥饿战损上浮上限（第495~498局批复盘）：掉血先验是「历史平均
                                     # 卡组」的场均账，而战损随战斗时长增长——爆发缺口大的卡组连最便宜
                                     # 的组合（496 局 F15 方柱构装体，生涯场均 6.6）也能拖成 -57 的
                                     # 消耗战。健康带（非绝境）战斗节点先验按 1+此值×缺口深度 放大，
                                     # 让选路提前看见饥饿的复利代价；绝境带已有 dire_loss_mult 不叠加。
                                     # 卡组成型后上浮自动归零；0 = 关闭
    "elite_min_deck_cards": 4,    # 非基础牌少于此数时规避精英（卡组强度门槛，血量门槛之外的第二道闸）
    "elite_early_floor_max": 8,   # 前期精英加码窗口上限楼层（第374~379批次复盘）：QZLQ 局 F7 精英
                                  # 以 4 张非基础牌压线放行（≥90% 血"双达标"）后被单场 -80 整管抬走
                                  # ——开局卡组大半还是基础打/防，张数门槛证明不了输出成型，
                                  # 而前期精英的重尾是即死风险，遗物收益兑付不起
    "elite_early_deck_extra": 3,  # 前期精英额外要求的非基础牌数：floor ≤ elite_early_floor_max 时
                                  # 闸门按 elite_min_deck_cards + 此值 放行。中后期自动回落基础
                                  # 门槛——136~137 批「饥饿卡组靠精英供血」教义不受影响
    "path_act_scale": [1.0, 1.7, 2.3],  # 掉血先验按幕数放大：二幕起怪物伤害显著升级（先验是一幕场均）
    "unknown_gauntlet_act2_mult": 1.6,  # 二幕起 Unknown 可能是连环遭遇（如 THE_OBSCURA 三连战），额外风险乘数
    "path_doomed_value_bonus": 8.0,  # 绝境资源节点偏好（403~406 批次复盘）：全部候选路径都投影
                                     # 中途死亡时，死亡罚分饱和把候选差压成 <1 分噪声，引擎退化成
                                     # 「挑死得最晚的路」——EQ04 局 F3 商店(468金可换战力/删诅咒)
                                     # 以 0.61 分之差输给又一场白死的怪物战，随后连战五场阵亡。
                                     # 此时金币/宝箱/事件是唯一还能改变时间线的杠杆：纯价值节点
                                     # （Shop/Treasure/Event）加此正分，让「先换战力再赴死」压过
                                     # 「白死一场」。仅全候选死亡投影时触发，健康局面零影响。
                                     # 存活价值节点反超扩展（第495~498局批复盘）：当评分最高的候选
                                     # 是死亡投影而存在存活的 Shop/Treasure/Event 时，同样对后者
                                     # 加成——UNPSGREBQ2TU 局 F21 商店（投影存活 53%）以 8.62 分
                                     # 之差输给死亡投影的 Unknown，旧「全候选死亡」前提漏掉该形态
    "race_doom_power_bonus": 10.0,  # 竞速必败预演成立时的战力节点倾斜（第524局批复盘新增）：
                                    # _boss_race_doomed 判死 = 满血进场也追不上击杀曲线，
                                    # 入场血量的边际价值归零（本批四局以75%~100%血整管打空），
                                    # 剩余层数内唯一可能翻转时间线的是战力增量。对
                                    # Shop/Treasure/Event 候选加此正分；精英不参与（灰区
                                    # 闸门仍是即死风险的守门人），健康局面（未判死）零影响
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
    "never_played_veto_penalty": 40.0,  # 零出牌实证的一票否决（第524局批复盘新增）：picked≥4 且
                                        # plays==0 = 战斗端从未打出过的死牌——DISINTEGRATION(26拿0打)/
                                        # MIND_ROT(12)/SLOTH(6)/WASTE_AWAY(5) 靠「不可打出」面板被解析成
                                        # 高伤攻击，饥饿加分高达 +20 压不住 -4 旧罚分，选取率仍 74%。
                                        # 删除/献祭端复用同一评估函数，负值越大越先删/先交，语义自洽
    "starve_defense_suppress_max": 0.30,  # 输出饥饿时纯格挡技能的拾取贬值上限（第509~515局批复盘新增）：
                                          # 缺口深度 × 此值 = 压价比例——饥饿加分链顶格后高质攻击同分满额，
                                          # 纯防御仍按原价竞争名额，深缺口局卡组构成对缺口失明。
                                          # 门控：格挡来源≥min_block_cards 且非基础牌≥deck_thin_core 才生效；
                                          # 带抽牌的功能技不贬。0 = 关闭
    # --- events ---
    "exploration_rate": 0.25,     # legacy review knob; event selection no longer depends on RNG
    "exploration_decay": 0.97,    # per-run decay
    "exploration_min": 0.05,
    # 事件改用确定性欠采样轮转：仅高血、近优、非显著负收益且未触发重尾 veto
    # 的选项有资格；每局/每候选均有硬上限，避免 epsilon 实践上永远不命中。
    "event_exploration_enabled": True,
    "event_exploration_run_quota": 1,
    "event_exploration_sample_cap": 2,
    "event_exploration_near_best_margin": 2.0,
    "event_exploration_min_hp_pct": 0.70,
    "event_exploration_min_value": -1.0,
    "event_worst_margin_frac": 0.05,  # 最坏情况闸门的生存余量（占最大生命，第 255~257 批次复盘）：
                                      # 选项历史单次最差生命增量 hp_min 满足 当前血+hp_min ≤ 余量 时
                                      # 判定「吃下即死」——7RJ9 局 31% 血选均值 +10.5 的「休息」，
                                      # 被链内强制战 -55 抬走；均值账看不见的重尾由 hp_min 补位
    # --- potions ---
    "potion_hard_only": True,     # only spend potions in elite/boss or lethal danger
    "potion_boss_reserve_floors": 2,  # Boss 前夜进攻药水预留窗口（第 380~385 批复盘新增）：
                                      # 距下一个 Boss ≤N 层的普通房里，进攻/增益药水封存
                                      # 留给 Boss 斩杀竞速；当场致死或血量跌破交药线立即
                                      # 解封，防御/回复药水与精英/Boss 房不受限。BNSJ 局
                                      # 实证：F4/F14/F15 三瓶前倾消费后 F17 竞速空手阵亡。
                                      # 0 = 关闭预留（回退旧行为）
    "potion_starved_reserve_floors": 6,  # 输出饥饿卡组的预留窗加宽（第 386~390 批复盘新增）：
                                         # deck_burst < deck_burst_floor 的卡组距 Boss ≤N 层
                                         # 即封存进攻/增益药水（普通房）。本批五局竞速投影
                                         # 全线「击杀还需>可存活」，LK4C 局 F10 爆炸药水、
                                         # 3QQC 局 F13 速度+增益药水仍被统计恐惧门放行烧进
                                         # 普通怪房，F17 一幕 Boss 空手输掉竞速——饥饿卡组
                                         # 的胜负手在 Boss 房。强卡组窗口不变；解封三口原样
    "potion_block_hp_pct": 0.35,  # 药水提前交药线（第 236 局复盘新增，block_safety 顶格后的
                                  # 爆毙/短时死亡接替旋钮）：硬仗中血量低于此比例即掏防御/回复
                                  # 药水，并同步放宽「低血放血」硬仗判定——TNWN 局 40%~50% 血
                                  # 硬仗干瞪眼、拖到 10/80 血才喝药的实证。演化区间 0.35~0.80，
                                  # 「没挡住」的证据不再蒸发，而是让下一场硬仗更早喝药
    "potion_hold_release_hp_pct": 0.45,  # 进攻药水预留的解封血线（第422局复盘新增）：与防御端
                                         # 「提前交药线」解耦的独立旋钮。旧版复用
                                         # potion_block_hp_pct 当解封口，该键被爆毙证据推到顶格
                                         # 0.80 后，饥饿卡组在预留窗内只要血量<80%就放行烧药——
                                         # 422 局 F14（距 Boss 3 层）54% 血把力量药水倒进意图仅
                                         # 7 的普通怪房，F17 必败竞速空手进场差 4 血生还。
                                         # 预留封存的语义是「为唯一胜机囤弹药」，解封只该在
                                         # 真濒死时发生；缺键回落旧键（兼容旧库）
    "shop_potion_reserve_bonus": 6.0,    # Boss 预留窗内货架进攻药的竞价加成（第422局复盘新增）：
                                         # 同池竞价里功能牌 6~9 分稳定压过药水基分 2~3 分——
                                         # 422 局商店路由理由明写「金币80够买药水档位」，到店
                                         # 却先花 39 金买了岩石铠甲，预算跌破药水档（60金）后
                                         # 空手离店。预留窗内进攻药一次性加价压过可选卡，
                                         # 保证「路由为买药进店」的预算不被截胡
    # 无法分类的新药水仅在有空位、有余钱、与当前最优购买近似时试购；成功样本
    # 达上限后退出探索通道，实际使用仍必须通过 _maybe_potion 的硬仗/致死闸门。
    "potion_exploration_enabled": True,
    "potion_exploration_run_quota": 1,
    "potion_exploration_sample_cap": 1,
    "potion_exploration_near_best_margin": 0.50,
    "potion_exploration_max_price": 60,
    "potion_exploration_gold_reserve": 60,
    "potion_exploration_min_hp_pct": 0.55,
    # --- 战斗端补丁键（第 58~59 局复盘） ---
    "desperate_atk_mult": 1.3,    # 无甲可补的致死回合攻击提速：唯一活路是抢斩杀终结战斗
    "block_excess_value": 0.03,   # 超出当前意图缺口的溢出格挡每点评分（第 59 局 Boss 首回合溢出 34 甲白费整轮能量）
    "race_allin_blk_damp": 0.45,  # 败局竞速判死后非致死回合的格挡贬值系数（第546局批复盘新增）：
                                  # 竞速已判必败时「边防边耗」被证伪，block_safety 原价会让任何
                                  # 格挡牌挤掉非击杀攻击的能量（543 局 F5：全攻提速留痕下整回合
                                  # 打挑衅+双防御，零输出）。乘入 blk_boost；致死回合豁免（买命
                                  # 延长输出窗口当场仍合法）。0~1 之间，1 = 关闭贬值
    "race_block_floor_cost": 1.0,  # 竞速格挡下限的合格挡费用门槛（第891局批复盘新增，静态键）：
                                   # 斩杀竞速局的非致死回合，若手中有费用≤此值的有效格挡牌，
                                   # 末点能量为其保留（非击杀攻击按 race_floor_reserve_penalty
                                   # 让路）——891 局 F28-T2 实证：全攻提速 6 费清空、手握防御+
                                   # （1费8甲）零甲硬吃 16（30→14），与 876-F30-T3 / 891-F20-T3
                                   # 同型累计 3 例（≥3 线）且直接改写生死链。race_allin（败局
                                   # 竞速）维持 546 局 0.45 贬值现状不并入。置 0 即整体关闭
    "race_floor_reserve_penalty": 12.0,  # 竞速格挡下限的预留罚分（第891局批复盘）：kill_race 下
                                   # 攻击吃 ×1.25×1.15 双乘区、格挡被 ×0.70 贬值，普通预留 -8
                                   # 档压不过乘区差；12 档让「最后一刀」稳定让位 1 费格挡，
                                   # 同时 3z 回归锚（race_allin 路径不吃此罚分）原样保留
    # --- 引擎有效爆发授信（第547~552局批复盘新增） ---
    "engine_burst_credit": 6.0,   # 每张生效力量成长牌计入 deck_effective_burst 的理论爆发授信：
                                  # deck_burst 只装攻击面值，点燃/恶魔形态贡献恒为零——拾取端
                                  # 拿引擎缺口分毫不动、前夜竞速对带引擎卡组系统性过度判死。
                                  # 6≈+2力/回合在7回合长战的复利折算再除以 eff 还原口径
    "engine_credit_cap": 2,       # 授信引擎张数上限：防「为饥饿囤三张恶魔形态」反向注水，
                                  # 与 scaling_engine_deck_cap 同一防注水哲学
    "power_commit_pool_min": 90.0,  # 开局承诺加成的长战门槛（第555~653批复盘新增）：
                                  # T1~T2 且能量足额时，力量引擎（恶魔形态族）的出牌评分
                                  # 再叠一档 power_round_bonus，仅当敌血池合计 ≥ 此值。
                                  # 90≈KIN双子(307)/仪式兽(252)/VANTOM(173) 的次幕下沿；同时
                                  # 作为大血池长战的联合翻盘复核下限，
                                  # 普通怪房（40~80）不加成；治「引擎拾取端热、执行端冷」：
                                  # 本批 DEMON_FORM 12 次拾取/升级仅 4 局上场，生涯
                                  # 45拿29打、BARRICADE 5拿1打，实测 dpt 填不平竞速缺口
    "power_commit_lowhp_obs_hp_pct": 0.45,  # 低血承诺观测位阈值（第913局批复盘）：
                                  # 开局承诺加成发放且 hp% 低于此线、敌意图>0 时，在出牌
                                  # why 追加「低血承诺观测」留痕供跨局计数。913-F21-T1
                                  # 实证：30血(37.5%)对意图9 承诺恶魔形态整回合 0 输出
                                  # 白吃 9——攻击 ×0.75/格挡 ×1.4 的 urgent 乘区只作用
                                  # 出牌/格挡分支，能力分支零感知。阈值与 urgent/路由层
                                  # 0.45 低血线同源；纯观测不改分，置 0 即关闭观测
    "hand_tax_fire_obs": True,    # 手牌滞留税对账火力观测位（第808~812局批复盘）：
                                  # 竞速投影/防守线复核的两条判决留痕在税>0时追加
                                  # 「手牌税N/回合未计入对账火力」与构成明细，供复盘把
                                  # 税后火力对账反事实与实战结果对照。812-F9 感染×4
                                  # =12/回合与意图20合计致死、807-F23 毒素两回合20点
                                  # 同族——对账火力对该不进格挡结算的税零感知。
                                  # 纯观测不改判决，置 False 即整体关闭
    "race_same_round_hp_loss_obs": True,  # 竞速判死时同回合 HP 损失观测位：
                                           # 仅披露已经发生的逐 tick 扣血，供复盘核对
                                           # 自损/费用与敌方伤害，不改变竞速判定；置 False 关闭
    "hand_tax_stance_obs": True,  # 税负战斗防守姿态成本观测位（第808~812局批复盘）：
                                  # 「高危防守姿态 × 手牌税>0」交集出现时在战斗留痕
                                  # 追加「税负战斗防守观测」与税额明细。812-F9 实证：
                                  # 感染税不进格挡结算管线，高危组合「转防守节奏」的
                                  # 拖延每多一轮多付 3~12 点不可格挡税，姿态的
                                  # blk_mult 只挡意图挡不住税——防守节奏在税负战斗
                                  # 里反向放大成本。供复盘按独立对局计数共现率，
                                  # 为姿态端折减/提速行为化预注册供数。
                                  # 纯观测不改姿态与分值，置 False 即整体关闭
    "hand_tax_play_audit": True,  # 落选税牌旁观留痕（第1087~1097局批复盘）：
                                  # HAND_TAX_PLAY_PRICING（第1086局批）只在「中标税牌」
                                  # 的 why 落「手牌税止损计价」——1097-F27 实证：毒素×2
                                  # 滞留两回合缴税 20（占全场掉血 27 的 74%），全链
                                  # 留痕 0 次（部署时序 pre-fix 之外，落选侧评分永不
                                  # 入链），无法区分「已附加但落选」「未附加」与
                                  # 「未参选（接口标不可出/超费）」，预注册指标③
                                  # （能量重排=替换等值格挡 vs 挤出高伤攻击）不可测量。
                                  # 主路径出牌且手牌含未中标税牌时，在 why 追加
                                  # 「税牌旁观HAND_TAX_PLAY_AUDIT：名=参选分含止损/
                                  # 无附加/未参选」段。纯观测不改分，置 False 即关闭
    "card_pick_burst_audit": True,  # reward card selection audit; observation only
    "engine_bias_relief_deficit": 0.30,  # 引擎 learned 负分豁免的缺口深度门槛：DEMON_FORM -3.0 bias
                                  # 来自「必败局拿了也没用」的归因倒置，深缺口局面豁免其负分压制；
                                  # 缺口低于此值（卡组接近成型）恢复全额学习信号
    "dup_density_release_frac": 0.5,  # 引擎复制件密度放行折减率（第856~876局批复盘）：深缺口局面下
                                  # 高质攻击/活跃成长引擎的第3+张复制件惩罚按 (1-frac) 折减——
                                  # 0.5 表示 -3.0 罚分减半；置 0.0 即整体关闭，行为与旧口径一致
    "dup_density_release_deficit": 0.30,  # 复制件密度放行的缺口深度门槛：与 engine_bias_relief_deficit
                                  # 同口径（burst 距及格线比例），浅缺口卡组接近成型时不得放行，
                                  # 防「为堆料而堆料」稀释抽牌质量
    # --- 战略层补丁键（第 60~61 局复盘） ---
    "boss_entry_min_hp_pct": 0.72,  # 进 Boss 血量要求线（第 86~87 批复盘 0.65→0.72）：近 10 局入 Boss ≥95% 的 1 胜 1 负、66%~79% 的 5 局全灭——生还分界实测在 ~95%，旧线明显偏低
                                    # （136~137 批再校准：运行库 0.90→0.80——63/124/137 三局 ≥95% 满血入场全数 -77~-80 打空，
                                    # 入场血量在当前卡组强度下不构成生死变量，而 110 罚差系统性压制宝箱/商店/精英供电路线；
                                    # 默认值保持 0.72 供新库起步）
    "boss_entry_penalty": 110.0,    # 路径投影入 Boss 血量每差满血 100% 的评分惩罚：让续航路线能压过消耗路线
    "boss_entry_evidence_hp_cap": 0.65,  # 入场线证据上限（第 146~147 批复盘）：只有低于此值的进场磨死才喂
                                         # boss_entry_min_hp_pct 棘轮——63/124/137/143/146/147 局 66%~100% 进场
                                         # 全灭，0.65+ 带内血量已被证伪为生死变量；旧条件「进场<线即上调」是
                                         # 循环自证（旋钮自定义证据阈值），0 胜生涯无释放通道必漂向 0.90
    "boss_entry_starve_relief": 0.15,    # Boss 入场线的输出饥饿豁免（第 209 批复盘）：与 elite_grey_starve_relief
                                         # 同构——饥饿卡组（爆发 < deck_burst_floor）的瓶颈是卡组强度而非入场血量
                                         # （0.65~1.00 带内八局证伪），为堆血放弃战斗/商店/宝箱只会更弱（安全螺旋）；
                                         # 饥饿时入场线按此比例放宽（0.88→~0.75），卡组成型后豁免自动消失
    "hopeless_race_hp_frac": 0.6,   # 败局竞速启用血线：≤60% 最大生命才允许进入竞速模式
    "hopeless_race_horizon": 2.0,   # 按近期净损速率外推 N 回合内死亡 → 判定被动防守不可行
    # --- 战斗端补丁键（第 65~66 局复盘） ---
    "danger_comp_hard_death_rate": 0.30,  # 历史死亡率 ≥ 此值的敌人组合自动认定为硬仗（解锁药水投入；头号杀手 FUZZY+SHRINKER 44% 死亡率此前在普通怪房带药进坟）
    "danger_comp_stance_death_rate": 0.25,  # 姿态收紧专用的更低门槛（第 84~85 批复盘）：药水门槛 0.30 让头号杀手 FUZZY+SHRINKER（41战12死=29.3%）恰好漏网，enemy_stance 对它输出完全中性——防御姿态必须比药水解锁更灵敏
    # --- 组合感知与 Boss 前夜（第 62~64 局复盘） ---
    "comp_loss_stance_frac": 0.28,  # 敌方组合场均战损占最大生命比达到此值 → 即使死亡率<30%也视同高危收紧姿态
    "potion_comp_loss_frac": 0.30,  # 敌方组合场均战损占比达到此值 → 解锁增益/攻击药水（不再只认精英/Boss 房）
    "danger_comp_blk_boost": 0.30,  # 高危组合防御姿态的格挡增益斜率（第470局批复盘新增，短时死亡证据的
                                    # 第三级接替旋钮）：enemy_stance 非Boss分支 blk_mult = 1+此值×sev。
                                    # 动机：生涯死亡榜前三全是普通怪房里的杀手组合（VANTOM 134战78死58%、
                                    # KIN双子 125战73死、仪式兽 116战52死，合计吞掉 ~43% 的全部对局），
                                    # 全局 block_safety 与药水交药线双双顶格后，「没挡住」的证据只剩
                                    # 组合专属防御姿态这一正确战场可去——把斜率从固定 0.30 解放为
                                    # 可演化键（BOUNDS 0.30~0.60），短时阵亡证据逐局 +0.05 加固
                                    # 杀手组合的格挡姿态，胜利时回收。默认值=旧硬编码，行为零跳变
    "boss_eve_smith_min_samples": 3,  # Boss 前夜智能锻造所需的 Boss 分档最小样本数
    "boss_eve_smith_heal_mult": 1.0,  # Boss 前夜改锻造的战损线：场均Boss战损 ≥ 回血量×此倍数即视为"回血救不了"（79局复盘：旧条件 ≥满血 永远够不到，实测场均≈28）
    "boss_eve_smith_hp_pct": 0.65,  # Boss 前夜改锻造的入场血量线（第 214 批证据带修正：0.65~1.00 带内入场血量
                                    # 已被 8+ 局证伪为非生死变量，带内回血换不来生还率、锻造提速才兑付；<65% 仍是真求生区维持回血）
                                    # 第 244 批复盘起语义收窄为「安全区的血量门槛」：三区裁决下只有不回血也稳过
                                    # 悲观战损的安全区才用它裁决锻造/回血，翻转带与溢出区不再经过它
    "boss_eve_pess_mult": 1.5,      # Boss 前夜三区裁决的悲观战损倍数（第 244 批复盘）：一幕 Boss 场均战损 ~45
                                    # 但实测尾部 70~85（方差极大），裁决「不回血能否稳过」必须用悲观口径；
                                    # 1.5×场均 ≈ 67，覆盖 240~243 批五局处决战的实际战损带（46~70）
    "boss_eve_safe_margin_frac": 0.10,  # 安全余量（占最大生命）：不回血的预期余量（血量-悲观战损）≤ 此值即属
                                    # 翻转带，回血直接兑换生还率——240~243 批处决差 0.4~7 点全部落在该带内
    "boss_eve_race_audit_heal_enabled": True,  # 竞速误报的低血前夜回退闸（RACE_AUDIT_HEAL_OVERRIDE）：
                                     # race_audit 记录「判死→实战获胜」达到样本/比例门槛时，
                                     # 仅把 <锻造线且有效回血≥8% 的 Boss 前夜从必败上砧改回回血；
                                     # false 可立即回滚到原竞速裁决，地图投影同步该口径
    "boss_eve_race_audit_heal_min_latched": 6,  # 竞速误报回退的最小锁定样本数
    "boss_eve_race_audit_heal_win_rate": 0.30,  # 判死后最终获胜比例达到此值才触发回退
    # --- Boss 攻坚（第 82~83 批复盘） ---
    "boss_atk_mult": 1.15,  # Boss 战攻击评分全局乘区：死亡榜前三均为 Boss、意图逐轮升级，缩短战斗即减伤
    # --- 输出饥饿感知（第 88~89 批复盘） ---
    "deck_burst_floor": 30.0,  # 卡组爆发吞吐量门槛：按「伤害/能耗」降序装满3能量的期望伤害低于此值视为输出饥饿（起步卡组≈18），高质攻击拿牌加分
                               # （第 209 批起为可演化旋钮，BOUNDS 25~45：burst_starve 双旋钮顶格后的同语义接替——加宽饥饿带让顶格加分惠及更多卡组状态）
    # --- 卡组单薄感知（第 90~91 批复盘） ---
    "deck_thin_core": 8,          # 非基础牌少于此数视为卡组单薄：抽5张的方差让爆发曲线无法稳定组装（91 局 16 张卡组进 Boss，长战后期手牌全是打击）
    "deck_thin_discount": 0.35,   # 单薄期每缺 1 张核心牌降低拾取门槛的幅度（门槛只升不降曾让 91 局整场只拿 6 张牌）
    # --- 斩杀竞速投影（第 90~91 批复盘，88~89 批遗留核对项⑤落地） ---
    "kill_race_enabled": True,
    "low_pool_burst_race_obs": True,  # 低血多敌且近致死、但血池未过竞速门时只追加审计留痕
    "end_turn_settle_recovery_ticks_boss": 40,  # BOSS_SETTLE_TIER3: Boss-only settle recovery budget.
    "end_turn_settle_recovery_ticks_lethal": 50,  # LETHAL_SETTLE_EXTENSION: lethal Boss settle windows get a bounded final 10-tick extension.
    "kill_race_min_enemy_hp": 80.0,  # 敌方剩余总血量超过此值才做投影（一幕Boss≈250/二幕精英级；小怪无需竞速账）
    "kill_race_margin": 1.5,         # 预计击杀回合数超出可存活回合数此余量 → 判定防守路线已被数学证伪
    "kill_race_atk_mult": 1.25,      # 竞速失败时攻击提速乘区（与 desperate/race_allin 不叠加）
    "kill_race_blk_mult": 0.70,      # 竞速失败时格挡权重乘区：买不到胜利的奢侈格挡把能量还给输出（致死当回合格挡仍由 lethal 分支兜底）
    "kill_race_prior_eff": 0.55,     # 首回合攻坚先验折算率（第 255 批复盘）：实测输出速率不足两回合时，
                                     # 用 deck_burst×此值做悲观 DPS 开账——Boss 战头 1~2 回合不再盲防
                                     # （252 局 F5 劫掠者三连 T1~T3 意图 22→32 还在打坚毅补防）；
                                     # 零爆发不预测（无从竞速），两回合后自动切回实测口径。
                                     # 第 397~402 批复盘起为可演化旋钮（BOUNDS 0.35~0.55）：饥饿链
                                     # 全顶格后 Boss 竞速败北证据改接此处下调——战斗端更早全攻提速、
                                     # 篝火端 _boss_race_doomed 更早把前夜转锻造
     "kill_race_osc_damp": True,      # 竞速先验折算率换向阻尼（KILL_RACE_OSC_DAMP，第915~916局批复盘新增，
                                      # 静态键）：lessons 950~968 实测两通道 ±0.03 逐局换向极限环
                                      # （0.57↔0.60↔0.63↔0.66↔0.69 往复，数十次翻向零收敛）。
                                      # 开键后与上次实际施加步长反向时步长降为 |last|/2（连续换向
                                      # 几何收敛），同向连击恢复全速；false 即整体关闭（回滚＝旧版
                                      # 全步长行为，零差异）
     "kill_race_prior_eff_last_step": 0.0,  # 折算率上一次实际施加的带符号净步长（换向阻尼状态键）：
                                      # 由 reflect 局末按本局净额落盘；0=无历史。只影响阻尼判定，
                                      # 不直接参与任何决策分支
     "kill_race_blk_eff": 0.70,       # 防守线复核的格挡折算率（第454局批复盘新增，静态键）：
                                     # 格挡实现率与输出折算率（kill_race_prior_eff）是两种物理量
                                     # ——prior_eff 被 Boss 竞速败北证据压到 0.37 后，复核的格挡吞吐
                                     # 被连带压死成死代码（454 批三连死：毛绒伏地虫组合 R3 即判必败
                                     # 转全攻、实际顺手格挡多活 5~8 回合差一刀斩杀）。实测持续格挡
                                     # ≈理论吞吐×0.5~0.8，取 0.70 校准；缺键回落 prior_eff 兼容旧库
     "escalation_race_fire_inflate": 0.40,  # 持续升级确认后的防守线复核火力上浮系数（第791~798批复盘新增）：
                                     # 平铺火力的联合能量对账把成长型组合的拖延判成可持续，
                                     # 白送指数方免费回合（93局FUZZY意图4→31、798局F23
                                     # 熟睡甲虫力量+2/轮时意图15→31一轮回合翻倍，797局F7
                                     # 同组合单场-65阵亡）。持续升级(_esc_rounds≥2)一旦
                                      # 确认，防守复核按火力×(1+此值)计价拖延成本、更早转竞速；
                                       # 实证升级斜率+44%~+100%，取 0.40 保守档；
                                       # 0 或缺键即整体关闭（回滚＝旧版零行为差异）
     "escalation_race_fire_inflate_eff": 0.20,  # esc 桶防火力上浮的审计校准（RACE_ESC_FIRE_INFLATE_CALIB，
                                      # 第808~812局批复盘新增，静态键）：竞速审计台账
                                      # （RACE_PROJ_CALIB_AUDIT 部署后 runs 813~868 累计）
                                      # latched=56 场中 24 场实战获胜（42.9%，超过第802~807
                                      # 批预注册的「判死→获胜 ≥3 独立对局或占判死场 >30%」
                                      # 收紧线），其中 esc 桶 23/52=44.2% 显著高于非 esc 桶
                                      # （1/4）——0.40 上浮把联合复核的拖延成本定价得过悲，
                                      # 近半数判死局按攻防节奏即可磨下。消费端仅替换 esc 桶
                                      # 防守复核火力上浮系数；缺键回落旧键
                                      # escalation_race_fire_inflate（0.40 原口径），置 0 即
                                      # 整体关闭；回滚＝删键或改回 0.40，零行为差异
    # --- 竞速判死换挡上浮校准（第823~832局批复盘新增，静态键） ---
     "race_latch_dpt_uplift": 0.35,   # 实测口径判死对账的换挡上浮系数（RACE_LATCH_DPT_UPSHIFT）：
                                      # 实测均值取自防守姿态的开局回合，而判死判决本身的行为
                                      # 后果就是全攻换挡提速——竞速审计首窗（828~832局）8场
                                      # 入锁3场实战获胜（37.5%，≥3独立对局），触发前批预注册
                                      # 的「按桶行为化收紧」。非升级桶（esc_gate=False）的实测
                                      # dpt 按此系数上浮后再对账，让判决对齐换挡后的真实输出；
                                      # 后验实测 10→15~17伤/回合（832局F17），取 0.35 保守档。
                                      # 仅作用于实测分支的判死对账，升级桶与先验分支维持原口径；
                                      # 0 或缺键即整体关闭（回滚＝旧版零行为差异）
     "race_latch_dpt_uplift_eff": 0.20,  # esc 桶换挡上浮接替（RACE_ESC_DPT_UPSHIFT_EFF，
                                      # 第917~918局批复盘新增，静态键）：换挡的物理成因是
                                      # 判决自身触发的全攻提速，与敌人是否升级无关——升级桶
                                      # 却一直沿用裸实测口径对账。台账（race_audit，截至
                                      # 第918局）esc 桶判死 184 场中 88 场实战获胜（47.8%，
                                      # 连续多批超过第802~807批预注册的 30% 收紧线），且该桶
                                      # 预注册杠杆已用尽（margin 已零、fire inflate 已按
                                      # RACE_ESC_FIRE_INFLATE_CALIB 校准）。消费端仅替换 esc 桶
                                      # 实测分支判死对账的 dpt 上浮系数（判决侧 ttk；防守复核
                                      # 火力与 fire inflate 不动），取 0.20 保守档（低于非 esc 桶
                                      # 0.35）；留痕「升级桶×(1+换挡上浮…)」可 grep。置 0 即
                                      # 整体关闭（回滚＝旧版裸实测口径，零行为差异）
     # --- 防守复核火力滞后修正（第843~855局批复盘新增，静态键） ---
     "hard_combat_intent_spike_fire": True,  # 高危战斗在敌意图从0突跳时，竞速火力取当前意图：
                                      # Bygone Effigy 唤醒后获得10点力量，0→23 的一次性跳升
                                      # 若只走 EMA 会把固定23点伤害低估；false 回滚旧版滞后口径
     "joint_feas_fire_honest": True,  # 防守线联合复核的火力下限取当前意图（JOINT_FEAS_FIRE_LAG）：
                                      # 复核火力取滞后 EMA 时，意图跳升回合出现幻影低价——
                                      # 855局F22 以 ~7伤/回合的滞后口径判「格挡0+输出28
                                      # 追平击杀12回合」可行，而当轮真实意图 22，已判死的
                                      # 竞速被翻案成攻防节奏磨死（同型：843-F17/848-F29/
                                      # 849-F22）。开键后对账火力一律 max(EMA, 当前意图)，
                                      # 与 esc 桶 93 局「存活分母至少取当前意图」同一不变式；
                                      # 判决侧 tsurv 口径不动，只修复核侧。false 即回滚旧版
     # --- 全场重生体竞速血池信贷（第914局批复盘新增，静态键） ---
    "race_all_respawn_pool_credit": True,  # 全场皆为已证实重生体时把它们计入斩杀竞速血池
                                     # （RACE_POOL_ALL_RESPAWN_CREDIT）：目标端三重压制自
                                     # 152 局起对「全场无本体」放开，但竞速血池口径没同步——
                                     # 914 局 F2/F5 同名册重生体整场在场时 ttk 恒为 0、
                                     # 竞速永不判死，F5 被意图 6→26 滚雪球磨 10 回合白损 53 血。
                                     # 全场无本体时重生体就是唯一的血池与终点，计入竞速账；
                                     # 有本体在场时仍按旧口径剔除（506 局教义不动）。
                                     # false 即回滚旧版（重生体一律不计入血池，零行为差异）
     # --- 竞速账药水授信（第654~663/675~680批复盘新增，静态键） ---
    "race_potion_flat_credit": 12.0, # Boss 竞速账里每瓶进攻类药水折算的血池削减：预留教义把进攻药水
                                     # 封存到 Boss 窗口兑现，旧竞速账却只认 deck_burst——已入库的药水
                                     # 爆发被「预留端扣着、可行性端看不见」两边重复计提，贴线对局被
                                     # 误判必败。12≈爆炸安瓿面值的悲观折半；防御/回复药水不入账
    "race_potion_pool_cap_frac": 0.15,  # 药水授信合计不超过血池此比例（防多瓶叠加把必败账翻成假可行）
    "race_potion_credit_floors_to_boss": 6,  # 药水授信只在距 Boss 此层数内生效（预留窗口之外药水
                                             # 可能中途兑付进普通房，提前放行会造成假可行）；
                                             # floor 缺失或窗口外原账不动
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
    "power_starve_bonus_base": 6.0,       # 输出饥饿对力量/成长型能力牌的拾取基础加分（第 255 批复盘）：
                                          # Boss 攻坚的死因形态是「即时伤害不够、长战无成长」，战斗端已有
                                          # 能力牌长战加成，拾取端此前仍按平面 5 分定价。
                                          # 第429~434批复盘上调（2.0→6.0）：六局 Boss 败局先验输出仅
                                          # 12/回合 vs 血池254，卡组却零成长引擎——旧 2 分基础在
                                          # 高质攻击 20 分饥饿加分面前毫无竞争力
    "power_starve_bonus_extra_max": 8.0,  # 成长牌饥饿加分随缺口深度放大的上限（与 burst_starve 同构；
                                          # 第429~434批复盘上调 4.0→8.0，理由同上）
    "scaling_engine_deck_cap": 2.0,       # 成长引擎稀缺判定的满编数（第429~434批复盘新增）：卡组已有
                                          # ≥ 此数张力量成长牌时稀缺加分归零——首台点燃是结构刚需，
                                          # 第三张恶魔形态是注水，边际必须递减
    "scaling_engine_pick_bonus": 7.0,     # 成长引擎稀缺加分满档值（第429~434批复盘新增）：卡组零引擎
                                          # 时全额、1 台减半。与高质攻击饥饿加分（base+extra≈20）同一
                                          # 量级，让「第一台引擎」在拾取端真正竞争得过又一张打击
    "upgrade_scaling_power_bonus": 16.0,  # 锻造端成长引擎加分（第429~434批复盘新增）：输出饥饿或前夜
                                          # 竞速必败时升级力量牌的结构性加分——长战复利口径下点燃+
                                          # ≈+30 伤/场，高于单卡升级 +3~6 面值；旧评估里力量牌
                                          # 基础分 ~5-7 永远输给大攻击，砧子系统性错配
    # --- 连战战损疲劳（第 255 批复盘） ---
    "path_streak_loss_step": 0.06,   # 投影端连战战损递增步长：连续第 4 场起先验×(1+step×(n-2))逐场放大。
                                     # 权重端早有疲劳压制（×0.75 起）但战损账仍线性——欲望压低、代价没变贵，
                                     # VS71/EHSL/7RJ9 三局链尾实际 -47~-72 而投影只按 ~10/场记账
    "path_streak_loss_cap": 1.30,    # 连战战损递增上限（防超长链把投影全面打成死亡、评分失去分辨力）
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
    # --- 绝境行军治理（第 126 局复盘） ---
    "path_dire_loss_mult": 1.7,   # 绝境投影悲观战损乘区：血量<rest_urgent_hp_pct 时战斗节点先验×此值。
                                  # 均值账在重尾前高估生存——126 局 F5 单场 -52 在账面只值 ~7 点，
                                  # 35% 血仍敢进战斗，下一战 -28 阵亡；绝境下要问的是「坏抽能否活命」
    "dire_rest_gate_mult": 0.55,  # 绝境篝火优先门：血量<rest_urgent 且候选含 RestSite 时，
                                  # 非 RestSite 候选整条路径总分×此值（负分区间加性重罚，与精英闸门同模式）。
                                  # 126 局 35% 血 Monster(6,2)=22.09 压过眼前 RestSite(6,1)=9.82——
                                  # 战斗子树里 2~3 个未来篝火的 +30% 幻想回血账反超救命休息
    "path_dire_heal_depth_decay": 0.85,  # 绝境下未来篝火回血的深度折减：depth≥1 的篝火按 0.85^depth 记账
                                         # （能否活着走到、走到时是否还需要都不确定），眼前篝火全额。
                                         # 治本：掐断「穿过未来营地继续战斗」的幻想回血账源头
    "dire_first_fight_safety": 1.5,      # 绝境首战生存复核的悲观安全系数：先验×幕数×绝境乘区×此值
    "dire_first_fight_floor": 0.09,      # 绝境首战生存线（占最大生命）：悲观打完第一战剩余≤此值即重罚。
                                         # 136~137 批触发带分析：safety1.5×绝境乘区1.7 下有效触发需
                                         # hp≤~34%（0.05 时），实际零触发皆因「绝境岔路要么唯一候选
                                         # （强制行军分支整体跳过）、要么直接选了篝火」——放宽到 0.09
                                         # 把有效触发带扩到 ~38% 覆盖警戒带下沿，单选漏斗仍无解（地形问题）
    "dire_first_fight_penalty": 45.0,    # 绝境首战生存复核未过的加性罚分：均值账说战斗便宜，
                                         # 但 126 局 F5 单场 -52、25% 血时坏抽一刀即死——
                                         # 眼前有救命篝火时不该用生命赌均值
    # --- 消耗螺旋治理（第 109 局复盘） ---
    "exhaust_play_penalty": 3.0,  # 消耗类牌逐次递增罚分：坚毅每打一次随机烧一张手牌，109 局 INKLET 三连波
                                  # 里 66 次坚毅把全部攻击牌烧成完美无限僵局（600+ 回合拖崩 runner）。
                                  # 硬上限另按卡组规模折算 max(1,min(4,deck//8))，此键只管「第 N 次的边际代价」
    "exhaust_unclog_bonus": 2.0,  # 卡手修正（第 135 局复盘）：手牌含不可出牌（感染/诅咒/状态）时，
                                  # 「消耗其他牌」的牌每张卡手牌 +此分（上限按 2 张计）——
                                  # 135 局 F11 精英战感染×3 卡手，坚毅的烧牌价值被忽略
    # --- 多敌战斗辅助体转火（第 136~137 批复盘） ---
    "support_target_bonus": 8.0,  # 多敌战斗中本回合零伤害意图敌人（治疗/增益/蓄力）的定向转火加分：
                                  # 威胁分成使其永远排最后——头号杀手同族双子（生涯46战24死）的
                                  # 神官持续强化信徒、意图逐轮滚升，拖长战斗正是死因形态。
                                  # 击杀辅助消除的是未来的意图增长（重生召唤物与单敌战斗不适用）
    "target_sticky_bonus": 3.0,   # 定向攻击的集火连续性加分（第 695~697 批复盘新增，静态键）：
                                  # 多体重建型精英（残杀千足虫：三独立 40~46 血体、快照带互愈字段）
                                  # 的强度轮转让旧评分逐张重算时火线在节间横跳——697 局 F28 阵亡
                                  # 记录目标序 0→1→2 往返，三条血同时剩半截无一减员，承受轮数被
                                  # 直接拉长。延续上一张定向攻击牌的目标得小幅粘性分；击杀预告
                                  # /自我强化/辅助体等高优先证据保持原量级可覆盖之。
                                  # 战斗实例更替自动失效，单体战与重生体不适用

    "elite_grey_starve_relief": 0.12,  # 灰区精英的输出饥饿豁免（第 136~137 批复盘）：爆发低于 deck_burst_floor 的
                                       # 卡组处于「跳过精英也必输 Boss」状态——精英是遗物/高质牌唯一稳定供给，
                                       # 全让给篝火=慢性死亡（122 批遗物断供因果链）。灰区生存线下调此值，
                                       # 卡组成型后豁免自动消失；137 局 88% 血灰区精英被否决即本病灶样本
    "elite_healthy_entry_pct": 0.75,   # 健康进场子账本的入场血量线（第 396 局批次复盘）：Elite 战损统计存在
                                       # 选择性偏差——健康状态从不主动打精英，全量样本几乎全是低血被迫战，
                                       # 场均被抬到 ~24~40，灰区悲观复核（×safety 2.5）数学上永不可满足，
                                       # 规避→样本更坏→更规避自我强化。≥此血量的 Elite 战斗额外计入
                                       # hp_lost_sum_hi/damage_events_hi 子账本，闸门定价优先消费之；
                                       # 子账本 <3 样本时回落旧口径，行为零变化
    "elite_tail_veto_min_deficit": 0.50,  # 深度输出饥饿时，硬线以上精英也做单场最差尾部复核；
                                           # 第580局 90%血压线进旧日雕像，均值约7、实测整管-72
    # --- 致死负面负载牌拾取屏蔽（LEAK_DEATH_GUARD，第801局批复盘闭环） ---
    "leak_death_guard": True,    # 总开关：False 即整体回滚到旧版无屏蔽行为
    "leak_death_value": -30.0,   # 被屏蔽牌在 eval_reward_card 的统一计价值（深负；
                                 # 删牌端按负值倒挂后自动成为最优先清除对象）
    "leak_death_cards": ["THE_GAMBIT"],  # 已被 runtime 原文证实的「受到未格挡攻击
                                          # 伤害即立刻死亡」类负载名单；801 局孤注一掷
                                          # 面值 50 挡被估 40.7 分、167 金买进+升级，
                                          # F14 T4 泄 1 点攻击伤害整局猝死。语义泛化
                                          # （文本识别死亡被动）待更多样本，先精确名单
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
               # Raw floors are presentation/accounting facts.  The historical
               # floors_total/best_floor fields intentionally remain the learning
               # outcome (floor + 50 on victory) for complete compatibility.
               "floor_sum_raw": 0.0, "best_floor_raw": 0,
               "deaths_by_enemy": {}, "deaths_by_event": {},
               # 精英死亡进场血量分带（第495~498局批复盘新增）：low=低于软线进场，
               # healthy=软线以上进场。区分「被迫行军死」与「闸门/执行端漏放行死」
               "elite_death_entry_band": {"low": 0, "healthy": 0}},
    # offered 是 v2 精确口径（迁移后、每个真实 offer 每个 card id 最多 +1）；
    # seen 保留兼容并从 v2 起同步按该口径增加。旧 seen 曾被纯评分调用污染，
    # card_offer_tracking.baseline_runs 明确可靠统计从哪一局之后开始。
    "cards": {},    # id -> {seen, offered, picked, plays, outcome_sum, bias}
    "card_offer_tracking": {"version": 2, "baseline_runs": 0,
                            "offers": 0, "candidate_observations": 0},
    # 受控探索动作的成功回执计数。它不是效果评价（效果仍归 cards/relics/events
    # 等各自账本），只回答某个候选是否已经得到过有限试用，防止确定性策略在
    # 同构 offer 上永久偏向第一个槽位。domain -> stable key -> successful trials。
    "novelty_trials": {},
    "relics": {},   # id -> {picked, outcome_sum, bias}
    "enemies": {},  # comp_id -> {encounters, hp_lost_sum, deaths, wins}
    "events": {},   # id -> option_key -> {n, hp_delta_sum, gold_delta_sum, deaths, hp_min, card/relic/potion_delta_sum}
    "rooms": {},    # node_type -> {visits, outcome_sum, hp_lost_sum, damage_events}
    "rooms_act": {},  # "{node_type}@{act}" -> {hp_lost_sum, damage_events}（分幕掉血，第79局复盘新增）
    "rooms_band": {},  # "{node_type}@{act}_b{band}" -> {hp_lost_sum, damage_events, hp_lost_max}
                       # （分幕分层段掉血，第 266 局批次复盘新增：band 1=幕内1~5层、
                       #   2=6~11层、3=12层起——VANTOM/KIN/CEREMONIAL 等场均 40+ 的
                       #   杀手组合集中在幕内后段，全幕均值账把它们摊薄到 ~10）
    "respawn_adds": {},  # enemy_key -> {"confirmations": n}
                         # （跨局重生召唤物名册，第 506~508 局批复盘新增：同种敌人
                         #   在 ≥2 场独立战斗中被「预测击杀≥2 次仍存活」实证后，
                         #   后续战斗第 1 回合即按重生体三重压制，不再先烧 2 次输出）
    "leak_death_blocks": {},  # card_id -> {"total": n, "seen_at": {source: n}}
                              # （LEAK_DEATH_GUARD 留痕，第 801 局批复盘新增：致死负面
                              #   负载牌在 offer 池/商店货架出现的次数与来源。屏蔽本身
                              #   由拾取端深负计价完成且 eval_reward_card 保持纯函数，
                              #   计数只发生在 _record_card_offer / 商店评估等动作位）
    "act_entries": [],   # 进幕快照列表（第 506~508 批复盘新增）：每幕首战入场时记
                         # {act, floor, hp_pct, max_hp, gold, potions, deck_size, burst}
                         # ——把「进二幕时的卡组就绪度」变成可复盘的硬数据
}


def _read_text_retry(path: Path) -> str:
    """Read one UTF-8 file without turning transient I/O failure into absence.

    Returning a default after ``PermissionError`` is unsafe for long-term memory:
    the next successful save would atomically replace the real file with defaults.
    Only a genuine ``FileNotFoundError`` is interpreted by :func:`_load_json` as a
    first-run/missing file; all other ``OSError`` values retry briefly and then
    propagate so the caller fails closed.
    """
    last_error: OSError | None = None
    for attempt in range(_READ_RETRIES):
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise
        except OSError as exc:
            last_error = exc
            if attempt + 1 < _READ_RETRIES:
                time.sleep(_READ_RETRY_BASE_SECONDS * (attempt + 1))
    assert last_error is not None
    raise last_error


def _load_json(path: Path, default):
    try:
        raw = _read_text_retry(path)
    except FileNotFoundError:
        return copy.deepcopy(default)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # The read itself succeeded, so this is malformed persisted data rather
        # than a transient lock/read failure.  Preserve the exact bad bytes under
        # a collision-resistant name before allowing the historical default-based
        # recovery path.  Never quarantine on OSError.
        backup = path.with_suffix(
            path.suffix + f".broken-{time.time_ns()}-{os.getpid()}-{threading.get_ident()}")
        try:
            path.replace(backup)
        except OSError as exc:
            # Recovery is safe only if the malformed bytes were actually preserved.
            # Returning defaults while quarantine failed would let the next save
            # overwrite the sole copy of the damaged (but potentially recoverable)
            # long-term memory file.
            raise OSError(f"cannot quarantine malformed JSON {path}: {exc}") from exc
    return json.loads(json.dumps(default))


def _lock_file_handle(handle, timeout: float = 480.0) -> None:
    """Acquire a one-byte advisory lock without signalling another process."""
    deadline = time.monotonic() + timeout
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    while True:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except (OSError, BlockingIOError):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out acquiring policy transaction lock: {handle.name}")
            time.sleep(0.05)


def _unlock_file_handle(handle) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def _policy_transaction_lock(path: Path) -> Iterator[None]:
    """Serialize policy read/merge/replace with review Git transactions.

    In the real checkout, lazily importing ``autogit`` lets this transaction use
    the exact repository lock already held by review patch application.  The lazy
    import avoids a module cycle during startup.  Standalone/test knowledge roots
    outside that repository use a persistent sibling advisory lock instead.
    """
    resolved = path.resolve()
    try:
        import autogit  # lazy: autogit does not import knowledge

        repo = Path(autogit.REPO_DIR).resolve()
        resolved.relative_to(repo)
        if not (repo / ".git").exists():
            raise ValueError("autogit repository metadata is unavailable")
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError):
        autogit = None

    if autogit is not None:
        with autogit.repository_lock():
            yield
        return

    key = str(resolved).casefold()
    with _POLICY_TX_LOCKS_GUARD:
        local_lock = _POLICY_TX_LOCKS.setdefault(key, threading.RLock())
    with local_lock:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        lock_path = Path(tempfile.gettempdir()) / f"sts2-ascend-policy-{digest}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+b")
        try:
            _lock_file_handle(handle)
            yield
        finally:
            _unlock_file_handle(handle)
            handle.close()


def _save_json(path: Path, data) -> None:
    """Durably replace JSON without sharing a temporary filename across writers.

    The brain, watchdog, and review lifecycle may overlap briefly.  A fixed
    ``<name>.tmp`` lets two writers truncate and interleave the same temporary
    file before either replace, producing malformed long-term memory.  A unique
    sibling plus ``os.replace`` makes every visible version complete; ownership
    rules still prevent independent processes from intentionally editing the
    same aggregate.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    key = str(path.resolve()).casefold()
    with _SAVE_LOCKS_GUARD:
        path_lock = _SAVE_LOCKS.setdefault(key, threading.Lock())
    with path_lock:
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", newline="\n", delete=False,
                    dir=path.parent, prefix=f".{path.name}.", suffix=".tmp") as tmp:
                tmp_name = tmp.name
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
            # Windows can transiently deny replacement while another process has
            # just closed the destination.  Retry that narrow condition; never
            # fall back to an in-place truncate/write.
            for attempt in range(8):
                try:
                    os.replace(tmp_name, path)
                    tmp_name = None
                    break
                except PermissionError:
                    if attempt == 7:
                        raise
                    time.sleep(0.01 * (attempt + 1))
        finally:
            if tmp_name is not None:
                try:
                    Path(tmp_name).unlink()
                except OSError:
                    pass


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def act_floor_band(row_in_act: int) -> int:
    """幕内层段号（第 266 局批次复盘）：1=前段(1~5层)、2=中段(6~11层)、3=后段(12层起)。

    同幕怪物池按楼层递增（一幕前段 NIBBIT 场均 8.3、后段 VANTOM/KIN/
    CEREMONIAL 场均 41~43），层段是比「幕」更细一格的难度坐标。传入的
    row 既可以是地图节点行号（1 起、已含幕内语义），也可以是绝对层数——
    调用方保证传入前已折算为幕内行号。
    """
    r = max(1, int(row_in_act))
    if r <= 5:
        return 1
    if r <= 11:
        return 2
    return 3


class Knowledge:
    def __init__(self, root: Path | CharacterProfile, repair_phantoms: bool = True):
        self.profile = root if isinstance(root, CharacterProfile) else None
        knowledge_root = self.profile.knowledge_root if self.profile else Path(root)
        self.root = self.profile.root if self.profile else knowledge_root
        root = self.root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "runs").mkdir(exist_ok=True)
        # Per-profile rollback journal for the currently active run.  Online
        # learning is intentionally saved during a run, so an in-memory snapshot
        # alone cannot undo samples already written before a human presses F9.
        # The journal survives Brain restarts and is removed only when that exact
        # run is closed.  Separate Knowledge roots keep character profiles
        # isolated without a process-global switch.
        self._run_learning_lock = threading.RLock()
        self._run_learning_id = ""
        self._run_learning_baseline: dict | None = None
        self._run_learning_excluded = False
        self.stats = _load_json(root / "stats.json", DEFAULT_STATS)
        # F9 persists the exclusion bit before restoring stats.json.  If the
        # process dies in that narrow window, construction itself must complete
        # the rollback: MAIN_MENU/GAME_OVER restarts may never call
        # begin_run_learning before another save or legacy mutation occurs.
        journal = self._load_run_learning_journal()
        if journal is not None and bool(journal.get("excluded_from_learning")):
            self._run_learning_id = self._normalise_run_id(journal["run_id"])
            self._run_learning_baseline = copy.deepcopy(journal["stats"])
            self._run_learning_excluded = True
            self._restore_run_learning_baseline(persist=True)
        self.policy = _load_json(root / "policy.json", DEFAULT_POLICY)
        progression_defaults = copy.deepcopy(DEFAULT_PROGRESSION)
        if self.profile is not None:
            progression_defaults["character"] = self.profile.character_id
        self.progression = _load_json(root / "progression.json", progression_defaults)
        # Immutable facts extracted from the installed base game are a separate,
        # read-only layer.  They must never be merged into learned stats/policy:
        # game updates replace a versioned snapshot, whereas online evidence keeps
        # accumulating across runs.  Missing snapshots degrade explicitly through
        # ``game_knowledge.error`` and do not prevent selfchecks with temporary KBs.
        self.game_knowledge = NativeGameKnowledge.from_knowledge_root(knowledge_root)
        # fill in any new default keys added in later versions
        #
        # Raw-floor migration must observe key absence *before* setdefault.  The
        # outcome total is losslessly reversible because the only bonus is the
        # fixed +50 victory credit.  The maximum is not reversible from the score
        # alone, so progression and per-run/catalog evidence are consulted first.
        global_stats = self.stats.setdefault("global", {})
        missing_floor_sum_raw = "floor_sum_raw" not in global_stats
        missing_best_floor_raw = "best_floor_raw" not in global_stats
        for k, v in DEFAULT_POLICY.items():
            self.policy.setdefault(k, v)
        for k, v in progression_defaults.items():
            self.progression.setdefault(k, v)
        for k, v in DEFAULT_STATS["global"].items():
            self.stats["global"].setdefault(k, v)
        if missing_floor_sum_raw:
            global_stats["floor_sum_raw"] = max(
                0.0,
                float(global_stats.get("floors_total", 0.0) or 0.0)
                - 50.0 * int(global_stats.get("wins", 0) or 0),
            )
        if missing_best_floor_raw:
            progression_best = 0
            for value in self.progression.get("best_floor_by_ascension", {}).values():
                try:
                    progression_best = max(progression_best, int(float(value)))
                except (TypeError, ValueError, OverflowError):
                    continue
            score_best = int(global_stats.get("best_floor", 0) or 0)
            score_guess = max(0, score_best - 50) \
                if int(global_stats.get("wins", 0) or 0) else score_best
            history_best = self._best_raw_floor_from_history()
            global_stats["best_floor_raw"] = max(
                0, progression_best, score_guess, history_best)
        # seen 的旧实现位于 eval_reward_card()：每次轮询/商店/升级/删除评分都会
        # 增加，历史值无法从聚合账精确反推。保留它避免破坏现有知识，同时以
        # offered=0 开启一条可审计的新口径，并记录迁移时已有局数。
        if "card_offer_tracking" not in self.stats:
            self.stats["card_offer_tracking"] = {
                "version": 2,
                "baseline_runs": int(self.stats["global"].get("runs", 0) or 0),
                "offers": 0,
                "candidate_observations": 0,
            }
        self.stats.setdefault("novelty_trials", {})
        for e in self.stats.get("cards", {}).values():
            e.setdefault("offered", 0)
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
        # 迁移：敌人血池/火力观测字段（第 138~141 批复盘新增）。138~141 四局
        # 全部死于 F17 一幕 Boss（入场 60%~100% 全数打空、含满血局），路径投影
        # 只回答「带多少血进 Boss」从不回答「这套卡组杀得死 Boss 吗」——攻坚
        # 投影需要敌方总血池与逐轮意图火力两件先验。缺键即视为无数据
        # （getter 返回 None），历史数据无需回填，向后兼容
        for e in self.stats.get("enemies", {}).values():
            e.setdefault("hp_pool_sum", 0.0)
            e.setdefault("hp_pool_n", 0)
            e.setdefault("fire_sum", 0.0)
            e.setdefault("fire_rounds", 0)
        # 迁移：分幕掉血统计（第 79 局复盘新增：跨幕混算的 Monster 场均 ~9.9
        # 让二幕投影系统性乐观——预测进 Boss 82% 实际两场战斗后剩 27%）
        self.stats.setdefault("rooms_act", {})
        # 迁移：分幕分层段掉血统计（第 266 局批次复盘新增）。同幕内怪物池按
        # 楼层递增（一幕前段 NIBBIT 场均 8.3、后段 VANTOM/KIN/CEREMONIAL
        # 场均 41~43 且贡献生涯前三死因），全幕均值把后段杀手摊薄成「便宜战」。
        # 纯增量结构：旧库无此键即从空累积，历史聚合拆不出逐样本层段，不回填
        self.stats.setdefault("rooms_band", {})
        # 迁移：跨局重生召唤物名册与进幕快照（第 506~508 局批复盘新增）。
        # 纯增量结构：旧库无此键即从空累积，不回填、读取端 .get 兜底
        self.stats.setdefault("respawn_adds", {})
        self.stats.setdefault("act_entries", [])
        # 迁移：LEAK_DEATH_GUARD 留痕（第 801 局批复盘新增）。纯增量结构：
        # 旧库无此键即从空累积，读取端 .get 兜底，不回填
        self.stats.setdefault("leak_death_blocks", {})
        # 迁移：事件选项最坏情况记忆字段（第 255~257 批次复盘新增）。hp_min 记
        # 该选项历史单次最差生命增量（含事件链强制战的祖先归因样本）。历史聚合
        # 数据无法反推逐样本尾部（hp_delta_sum/n 拆不出单次极值），旧条目显式
        # 置 None 标记「无尾部数据」而非捏造回填，尾部自新样本起累积；
        # getter 对 None/缺键一律返回 None，向后兼容
        for _ev_opts in self.stats.get("events", {}).values():
            for e in _ev_opts.values():
                e.setdefault("hp_min", None)
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
            g["floor_sum_raw"] = max(
                0.0, float(g.get("floor_sum_raw", 0.0)) - lost_floors)
            # A phantom may also have polluted the raw maximum.  Recompute from
            # non-phantom active/catalog evidence instead of trying to subtract a
            # maximum.  If no evidence survived, retain zero rather than inventing
            # a floor from the learning score.
            g["best_floor_raw"] = self._best_raw_floor_from_history()
            rba = self.progression.setdefault("runs_by_ascension", {})
            for asc, cnt in by_asc.items():
                rba[asc] = max(0, int(rba.get(asc, 0)) - cnt)
            decay = float(self.policy.get("exploration_decay", 0.97)) or 0.97
            self.policy["exploration_rate"] = clamp(
                float(self.policy.get("exploration_rate", 0.25)) / (decay ** n_phantom), 0.0, 1.0)
            self.save()
        self.stats["phantom_repair_v1"] = True

    def _best_raw_floor_from_history(self) -> int:
        """Best trustworthy raw floor visible in active logs or archive catalog.

        This is deliberately a small, read-only migration helper rather than a
        dependency on the dashboard provider.  Invalid/concurrently replaced
        files are skipped; the online aggregate remains the source of truth after
        migration.
        """
        best = 0
        paths = []
        try:
            paths = sorted((self.root / "runs").glob("*.json"))
        except OSError:
            pass
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            decisions = ([row for row in data.get("decisions", []) if isinstance(row, dict)]
                         if isinstance(data.get("decisions"), list) else [])
            if not decisions and not bool(data.get("victory")):
                continue
            game_over = any(row.get("screen") == "GAME_OVER" for row in decisions)
            if bool(data.get("in_progress")) and not bool(data.get("victory")) and not game_over:
                continue
            values = [data.get("floor")]
            values.extend(row.get("floor") for row in decisions)
            for value in values:
                try:
                    floor = int(float(value))
                except (TypeError, ValueError, OverflowError):
                    continue
                if 0 <= floor <= 999:
                    best = max(best, floor)

        catalog = self.root / "archive" / "run_catalog.jsonl"
        try:
            lines = catalog.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            lines = []
        for line in lines:
            try:
                row = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(row, dict) or not row.get("file"):
                continue
            if bool(row.get("phantom_candidate")):
                continue
            if (bool(row.get("in_progress")) and not bool(row.get("victory"))
                    and row.get("last_screen") != "GAME_OVER"):
                continue
            try:
                floor = int(float(row.get("floor")))
            except (TypeError, ValueError, OverflowError):
                continue
            if 0 <= floor <= 999:
                best = max(best, floor)
        return best

    # ---------- persistence ----------

    @property
    def _run_learning_journal_path(self) -> Path:
        return self.root / ".active_run_learning.json"

    @staticmethod
    def _normalise_run_id(run_id: str) -> str:
        return str(run_id or "").strip()

    def _load_run_learning_journal(self) -> dict | None:
        path = self._run_learning_journal_path
        if not path.exists():
            return None
        payload = _load_json(path, {})
        if (not isinstance(payload, dict)
                or int(payload.get("version", 0) or 0) != 1
                or not self._normalise_run_id(payload.get("run_id"))
                or not isinstance(payload.get("stats"), dict)):
            raise ValueError(f"invalid active-run learning journal: {path}")
        return payload

    def _write_run_learning_journal(self) -> None:
        if not self._run_learning_id or self._run_learning_baseline is None:
            raise RuntimeError("active-run learning journal has no baseline")
        _save_json(self._run_learning_journal_path, {
            "version": 1,
            "run_id": self._run_learning_id,
            "excluded_from_learning": bool(self._run_learning_excluded),
            "stats": self._run_learning_baseline,
        })

    def _restore_run_learning_baseline(self, *, persist: bool) -> None:
        if self._run_learning_baseline is None:
            raise RuntimeError("cannot restore active-run learning without a baseline")
        self.stats = copy.deepcopy(self._run_learning_baseline)
        if persist:
            _save_json(self.root / "stats.json", self.stats)

    def begin_run_learning(self, run_id: str) -> None:
        """Open or resume the durable learning transaction for one profile/run.

        A normal reconnect keeps already accumulated autonomous samples while the
        original baseline remains available for a later F9.  If the journal says
        the run was previously excluded, reconnect restores the baseline before
        any new policy tick can learn from that run again.
        """
        run_id = self._normalise_run_id(run_id)
        if not run_id or run_id == "run_unknown":
            return
        with self._run_learning_lock:
            if self._run_learning_id == run_id:
                if self._run_learning_excluded:
                    self._restore_run_learning_baseline(persist=True)
                return

            journal = self._load_run_learning_journal()
            if journal is not None and self._normalise_run_id(
                    journal.get("run_id")) == run_id:
                self._run_learning_id = run_id
                self._run_learning_baseline = copy.deepcopy(journal["stats"])
                self._run_learning_excluded = bool(
                    journal.get("excluded_from_learning"))
                if self._run_learning_excluded:
                    self._restore_run_learning_baseline(persist=True)
                return

            # A stale excluded journal must be honoured before another run in the
            # same profile starts.  A stale autonomous journal leaves its already
            # persisted samples intact, matching normal crash/reconnect behaviour.
            if journal is not None and bool(journal.get("excluded_from_learning")):
                self.stats = copy.deepcopy(journal["stats"])
                _save_json(self.root / "stats.json", self.stats)

            self._run_learning_id = run_id
            self._run_learning_baseline = copy.deepcopy(self.stats)
            self._run_learning_excluded = False
            self._write_run_learning_journal()

    def exclude_run_learning(self, run_id: str) -> bool:
        """Rollback and permanently suppress learning for this mixed run.

        The exclusion bit is journalled before restoring ``stats.json``.  A crash
        between those writes therefore fails closed: the next Brain process sees
        the bit and completes the rollback instead of accepting partial samples.
        """
        run_id = self._normalise_run_id(run_id)
        if not run_id or run_id == "run_unknown":
            return False
        with self._run_learning_lock:
            if self._run_learning_id != run_id:
                self.begin_run_learning(run_id)
            if self._run_learning_id != run_id:
                return False
            self._run_learning_excluded = True
            self._write_run_learning_journal()
            self._restore_run_learning_baseline(persist=True)
            return True

    def run_learning_is_excluded(self, run_id: str | None = None) -> bool:
        with self._run_learning_lock:
            if run_id is not None and self._run_learning_id != self._normalise_run_id(run_id):
                return False
            return bool(self._run_learning_id and self._run_learning_excluded)

    def finish_run_learning(self, run_id: str) -> None:
        """Close one exact run transaction after terminal persistence succeeds."""
        run_id = self._normalise_run_id(run_id)
        if not run_id or run_id == "run_unknown":
            return
        with self._run_learning_lock:
            if self._run_learning_id != run_id:
                journal = self._load_run_learning_journal()
                if journal is None or self._normalise_run_id(
                        journal.get("run_id")) != run_id:
                    return
                self._run_learning_id = run_id
                self._run_learning_baseline = copy.deepcopy(journal["stats"])
                self._run_learning_excluded = bool(
                    journal.get("excluded_from_learning"))
            if self._run_learning_excluded:
                self._restore_run_learning_baseline(persist=True)
            self._run_learning_journal_path.unlink(missing_ok=True)
            self._run_learning_id = ""
            self._run_learning_baseline = None
            self._run_learning_excluded = False

    def _learning_write_allowed(self) -> bool:
        return not self.run_learning_is_excluded()

    def save(self) -> None:
        with self._run_learning_lock:
            if self._run_learning_excluded:
                # Direct aggregate updates in legacy call sites cannot leak on an
                # exit/save even if they bypass a commit_* guard.
                self._restore_run_learning_baseline(persist=False)
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
        合并结果回填内存并刷新基准。读取失败必须向上传播：把瞬时锁冲突
        当成空磁盘再整体回写，会永久覆盖本来完好的策略文件。
        stats/progression 只有本进程写入，维持整体写盘不变。
        """
        path = self.root / "policy.json"
        # The lock covers the *entire* read -> three-way merge -> atomic replace.
        # Merely locking _save_json leaves a TOCTOU window in which a review patch
        # or another brain can be read and then overwritten by our stale snapshot.
        with _policy_transaction_lock(path):
            loaded = _load_json(path, {})
            if not isinstance(loaded, dict):
                raise ValueError(f"policy.json root must be an object: {path}")
            self._adopt_disk_policy(loaded)
            _save_json(path, self.policy)
            self._policy_sync = dict(self.policy)

    def _adopt_disk_policy(self, disk: dict) -> list[str]:
        """按三方合并语义把磁盘 policy 并入内存，返回被采纳的键名（供留痕）。

        本进程未动过的键（内存==基准）采纳磁盘值；演化过的键保留内存值；
        内存与基准都没有的全新键同样采纳——这是外部新增键进入长驻进程的
        唯一不重启通道（第 123~124 局复盘实证：122 批复盘只改了代码默认值
        而没写运行库 JSON，重启前该修复对运行中的大脑完全不可见）。
        """
        base = getattr(self, "_policy_sync", None)
        adopted: list[str] = []
        if isinstance(base, dict):
            for k, disk_v in disk.items():
                mine = self.policy.get(k, _MISSING)
                if base.get(k, _MISSING) == mine and disk_v != mine:
                    self.policy[k] = disk_v
                    adopted.append(k)
        return adopted

    def refresh_policy(self) -> list[str]:
        """运行中进程的策略热同步（第 123~124 局复盘新增），返回生效键列表。

        缺陷定性（122~124 批实证）：LLM 复盘在独立会话里给 DEFAULT_POLICY
        新增 elite_grey_survival_floor=0.40 并依赖「加载器 setdefault 自动补齐
        运行库」——但 setdefault 只在进程启动时执行，长驻大脑不重启就永远
        看不到新键，_elite_grey_veto 沿旧舒适线语义空转，122 批核心修复在
        第 123~126 局全程为死代码。两条外部通道由此接入主循环周期调用：
          1) 磁盘 policy.json 的外部修改/新增键 → 三方合并实时采纳；
          2) 进程已加载代码里的 DEFAULT_POLICY 新增键 → deepcopy 兜底补齐
             （deepcopy 防止嵌套默认值与模块常量共享引用被运行时污染；
             代码本身的更新仍走 request_restart→exit42 重启通道）。
        只读磁盘 + 内存合并，不立即写盘（持久化交给既有的 save 节奏，
        避免与外部复盘会话的写入互相踩踏）。
        """
        path = self.root / "policy.json"
        # The asynchronous reviewer can save the same Knowledge instance while the
        # main loop hot-refreshes it.  Reuse the policy transaction lock so neither
        # thread mutates ``self.policy`` during the other's JSON serialization.
        with _policy_transaction_lock(path):
            loaded = _load_json(path, {})
            if not isinstance(loaded, dict):
                raise ValueError(f"policy.json root must be an object: {path}")
            adopted = self._adopt_disk_policy(loaded)
            added: list[str] = []
            for k, v in DEFAULT_POLICY.items():
                if k not in self.policy:
                    self.policy[k] = copy.deepcopy(v)
                    added.append(k)
            if adopted or added:
                self._policy_sync = dict(self.policy)
            return adopted + added

    # ---------- value estimates (shrunk toward prior) ----------

    def global_avg_outcome(self) -> float:
        g = self.stats["global"]
        return g["floors_total"] / g["runs"] if g["runs"] else 10.0

    def card_value(self, card_id: str) -> float:
        e = self.stats["cards"].get(card_id)
        if not e or not e["picked"]:
            return e.get("bias", 0.0) if e else 0.0
        # 零出牌不享 outcome 学分（第524局批复盘）：outcome=到达层数是「拾取即
        # 记分」的幸存者偏差账，picked>0 而 plays==0 的牌从未被战斗端打出过，
        # 其学分全部来自「拿它的局恰好走得远」，与卡牌价值无关——DISINTEGRATION
        # 凭虚假场均 33 把 learned value 抬到 +11.8（拾取端封顶后仍 +3），
        # 与 -4 的 unplayed 罚分对冲后净 +7，长期通过拾取门槛。零出牌时只保留
        # bias（228 批已封禁其正向增长），让拾取端的实证否决全权接管
        if not int(e.get("plays", 0) or 0):
            return e.get("bias", 0.0)
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
                # 第470局批复盘：格挡增益斜率 0.30 解放为可演化键
                # danger_comp_blk_boost——block_safety 与药水交药线双双顶格后，
                # 短时死亡证据改接组合专属防御姿态（战场归属正确的第三级接替）
                _blk_boost = float(self.policy.get("danger_comp_blk_boost", 0.30))
                base["urgent_hp_pct"] = round(0.45 + 0.20 * sev, 3)
                base["atk_mult"] = round(1.0 - 0.15 * sev, 3)
                base["blk_mult"] = round(1.0 + _blk_boost * sev, 3)
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

    def room_damage_prior_act(self, node_type: str, static_prior: float,
                              act: int, row_in_act: int | None = None) -> tuple[float, bool]:
        """分幕掉血先验（第 79 局复盘新增；第 148~160 批复盘首次接入调用方）。

        跨幕混算的 Monster 场均 ~9.9 是"一幕便宜 + 二幕昂贵"的平均假象——
        二幕单场大失血型组合（SPINY_TOAD 本批 -40/-29）让投影系统性乐观，
        F20 选路预测进 Boss 82%，两场战斗后实际只剩 27%。有分幕样本（≥3）
        时以更高实测权重混合；无分幕数据时回落跨幕旧口径（向后兼容，无需迁移）。
        实测项同步乘战斗发生率（第 96 局复盘）：与跨幕口径保持同一语义
        （E[掉血|到访]），否则分幕样本一够数就会把发生率折扣重新冲掉。

        分幕再分层段（第 266 局批次复盘）：row_in_act 传入时优先查
        rooms_band 层段实证（≥3 场）——同幕内怪物池按楼层递增，一幕全幕
        均值 ~10 把后段 VANTOM/KIN/CEREMONIAL（场均 41~43、生涯前三死因）
        摊薄成「便宜战」，路径投影因此敢在 F13~15 排三连战再进 Boss。
        基线取分幕口径（而非跨幕），层段账是对分幕账的进一步细化。

        返回 (先验, 是否命中分幕/分层段实证)。命中时实测场均已包含幕间/段间
        难度跃迁，调用方不得再乘 path_act_scale——否则幕效应被双重计费
        （第 148~160 批实证：Elite 二幕实测场均 34.0，旧口径 blended 22.7×1.7=38.7，
        若叠加再乘 1.7 则虚高至 45.9）；未命中时调用方照常乘幕数系数。
        """
        if row_in_act is not None:
            b = self.room_damage_band_stats(node_type, act, row_in_act)
            if b is not None:
                b_avg, _b_worst, b_n = b
                baseline = self.room_damage_prior_act(node_type, static_prior, act)[0]
                w = min(0.85, b_n / 8.0)
                return ((1.0 - w) * baseline
                        + w * b_avg * self.room_combat_rate(node_type)), True
        e = self.stats.get("rooms_act", {}).get(f"{node_type}@{act}")
        if not e or e.get("damage_events", 0) < 3:
            return self.room_damage_prior(node_type, static_prior), False
        baseline = self.room_damage_prior(node_type, static_prior)
        measured = e["hp_lost_sum"] / max(1, e["damage_events"])
        w = min(0.85, e["damage_events"] / 8.0)
        return ((1.0 - w) * baseline
                + w * measured * self.room_combat_rate(node_type)), True

    def event_option_value(self, event_id: str, option_key: str) -> tuple[float, int]:
        """Return (score, sample_count). Score mixes hp/gold deltas and death penalty.

        加牌稀释代价（第 62~64 局复盘新增）：事件结算此前只记即时 hp/gold，
        「带走这颗蛋」把不可打出的鸟蛋混进卡组（Boss 战多次占据手牌 ✗ 位），
        结算却记 0/0 看似免费。每净增 1 张牌按 -2 计稀释代价，
        强正收益（hp/gold）仍可覆盖——拿真牌的事件不会被误伤。

        减牌计价修正（第 136~137 批复盘）：旧公式对负增量取 -card_avg*2 反号
        为正——滑脚木桥「跨越」每跨一次随机掉一张牌（card_avg=-1）却被虚标
        +2 分，四连跨白掉四张牌。净减牌改为按失去平均卡值 -1/张计罚
        （半价：个别事件的减牌可能是去除诅咒的收益，不按全价反推）。

        遗物/药水收益入账（第 372~373 局批次复盘新增）：佩尔/特兹卡塔拉/
        木雕这类「给遗物」的事件此前全部记 0.0——结算账本只认 hp/gold/card，
        遗物断供恰是当前版本卡组输出不足的上游病因之一，事件学习端却对
        唯一的稳定遗物供给视而不见，选项间只能靠样本数瞎选。结算时按
        选择前后遗物/药水签名的净增量记账：遗物按 event_relic_value 计价
        （对标商店遗物基线 3.0 打折：随机遗物含垃圾）、药水按
        event_potion_value 计价（药水位有限且品质随机，半价处理）。
        """
        opts = self.stats["events"].get(event_id, {})
        e = opts.get(option_key)
        if not e or not e["n"]:
            return 0.0, 0
        hp_avg = e["hp_delta_sum"] / e["n"]
        gold_avg = e["gold_delta_sum"] / e["n"]
        card_avg = float(e.get("card_delta_sum", 0.0)) / e["n"]
        death_rate = e["deaths"] / e["n"]
        card_term = (-2.0 * card_avg) if card_avg > 0 else (1.0 * card_avg)
        relic_avg = float(e.get("relic_delta_sum", 0.0)) / e["n"]
        potion_avg = float(e.get("potion_delta_sum", 0.0)) / e["n"]
        return (hp_avg * 1.0 + gold_avg * 0.02 + card_term
                + relic_avg * float(self.policy.get("event_relic_value", 2.5))
                + potion_avg * float(self.policy.get("event_potion_value", 1.0))
                - death_rate * 40.0), e["n"]

    def event_option_worst(self, event_id: str, option_key: str) -> float | None:
        """该选项历史单次最差生命增量（最坏情况记忆，第 255~257 批次复盘新增）。

        均值账在重尾分布前系统性乐观：「茂密的植被-休息」均值 +3.3（含回血），
        尾部样本 -51.7（链内强制战把 31% 血的局直接抬走）。事件学习端若只看
        均值，低血量时会把「可能致死」当「小赚」。hp_min 含事件链强制战的
        祖先归因样本（agent 把战斗掉血等额追加给引出战斗页的选项）。
        无尾部数据（新事件/旧库迁移条目）返回 None。
        """
        e = self.stats["events"].get(event_id, {}).get(option_key)
        if not e:
            return None
        w = e.get("hp_min")
        return float(w) if w is not None else None

    def novelty_trial_count(self, domain: str, key: str) -> int:
        """Return successful controlled trials for one stable candidate key."""
        domains = self.stats.get("novelty_trials") or {}
        entries = domains.get(str(domain).lower()) or {}
        try:
            return max(0, int(entries.get(str(key), 0) or 0))
        except (TypeError, ValueError):
            return 0

    def commit_novelty_trial(self, domain: str, key: str) -> None:
        """Record one *accepted* controlled-exploration action.

        Policy calls this only after observing its ``novelty_trial`` tag in
        ``ctx.credit_tags``.  Rejected HTTP attempts therefore cannot consume a
        persistent sample or close the exploration gate.
        """
        if not self._learning_write_allowed():
            return
        domain = str(domain or "").strip().lower()
        key = str(key or "").strip()
        if not domain or not key:
            return
        domains = self.stats.setdefault("novelty_trials", {})
        entries = domains.setdefault(domain, {})
        entries[key] = min(999, self.novelty_trial_count(domain, key) + 1)

    # ---------- online commits ----------

    def commit_enemy_fight(self, comp_id: str, hp_lost: float, won: bool, died: bool,
                           node_type: str | None = None,
                           hp_pool: float | None = None,
                           fire_sum: float | None = None,
                           fire_rounds: int | None = None,
                           act: int | None = None) -> None:
        if not self._learning_write_allowed():
            return
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
            # Boss 分幕子账本（第 506~515 局批复盘新增）：竞速投影与前夜裁决
            # 此前消费全幕混合均值（血池 253/火力 14），而一幕 Boss 池实测
            # 血池 173~307、二三幕 300~400+——一幕前夜被二三幕均值系统性判死，
            # 翻转带回血压过锻造，卡组成型被慢性锁死。分幕账只认 node_type==
            # "Boss" 的观测（比旧全量账混入普通战血池样本更纯），历史条目无此
            # 键即从空累积，不捏造回填；读取端样本不足时回落全量均值（兼容）
            if act:
                sub = e.setdefault("boss_act", {}).setdefault(str(int(act)), {})
                sub["encounters"] = int(sub.get("encounters", 0)) + 1
                sub["hp_lost_sum"] = float(sub.get("hp_lost_sum", 0.0)) + max(0.0, hp_lost)
                sub["deaths"] = int(sub.get("deaths", 0)) + (1 if died else 0)
                if hp_pool is not None and hp_pool > 0:
                    sub["hp_pool_sum"] = float(sub.get("hp_pool_sum", 0.0)) + float(hp_pool)
                    sub["hp_pool_n"] = int(sub.get("hp_pool_n", 0)) + 1
                if fire_rounds:
                    sub["fire_sum"] = float(sub.get("fire_sum", 0.0)) + max(0.0, float(fire_sum or 0.0))
                    sub["fire_rounds"] = int(sub.get("fire_rounds", 0)) + int(fire_rounds)
        # 血池/火力观测入账（第 138~141 批复盘新增）：供 Boss 攻坚投影与
        # Boss 前夜篝火决策使用。血池按「场」记均值样本（多阶段聚合已取最大段），
        # 火力按「轮」累加（逐轮意图采样，格挡前口径）
        if hp_pool is not None and hp_pool > 0:
            e["hp_pool_sum"] = float(e.get("hp_pool_sum", 0.0)) + float(hp_pool)
            e["hp_pool_n"] = int(e.get("hp_pool_n", 0)) + 1
        if fire_rounds:
            e["fire_sum"] = float(e.get("fire_sum", 0.0)) + max(0.0, float(fire_sum or 0.0))
            e["fire_rounds"] = int(e.get("fire_rounds", 0)) + int(fire_rounds)

    def boss_loss_stats(self, act: int | None = None) -> tuple[float, int]:
        """全部分档 Boss 战的（场均掉血绝对值, 样本数）。

        第 63 局复盘新增：满血进 Boss 仍被仪式兽 85 点战损处决——
        「Boss 前夜优先回血」隐含假设回血量能覆盖预期战损；当实测 Boss
        场均战损 ≥ 满血时该假设崩塌，回血是无效投资，锻造缩短战斗才是活路。

        act 给定时优先消费分幕子账本（第 506~515 局批复盘新增）：前夜翻转带
        的悲观战损此前用全幕均值（含二三幕死亡样本），一幕前夜被系统性高估；
        分幕样本 <3 场时回落全量账（冷启动/旧库兼容）。
        """
        if act:
            tot_n_a = tot_loss_a = 0.0
            for e in (self.stats.get("enemies") or {}).values():
                sub = (e.get("boss_act") or {}).get(str(int(act))) or {}
                n = int(sub.get("encounters", 0) or 0)
                if n:
                    tot_n_a += n
                    tot_loss_a += float(sub.get("hp_lost_sum", 0.0) or 0.0)
            if tot_n_a >= 3:
                return (tot_loss_a / tot_n_a), int(tot_n_a)
        tot_n = tot_loss = 0.0
        for e in self.stats.get("enemies", {}).values():
            tot_n += float(e.get("boss_encounters", 0) or 0)
            tot_loss += float(e.get("boss_hp_lost_sum", 0.0) or 0.0)
        return (tot_loss / tot_n if tot_n else 0.0), int(tot_n)

    def enemy_hp_pool(self, comp_id: str | None) -> float | None:
        """该敌人组合的平均总血池（非召唤杂兵的最大生命合计）；无数据返回 None。"""
        e = (self.stats.get("enemies") or {}).get(comp_id or "")
        n = int((e or {}).get("hp_pool_n", 0) or 0)
        if not e or n < 1:
            return None
        return float(e["hp_pool_sum"]) / n

    def enemy_fire_rate(self, comp_id: str | None) -> float | None:
        """该敌人组合的场均逐轮意图火力（每回合期望伤害，格挡前口径）。"""
        e = (self.stats.get("enemies") or {}).get(comp_id or "")
        n = int((e or {}).get("fire_rounds", 0) or 0)
        if not e or n < 1:
            return None
        return float(e.get("fire_sum", 0.0)) / n

    def boss_vitals_worst(self) -> tuple[float | None, float | None]:
        """已学习 Boss 组合中最凶的一组（血池、火力）估计。

        只认 boss_encounters≥2 的组合（Boss 分档计数由 commit_enemy_fight 维护，
        普通怪房同名组合不会误入）；样本门槛：血池 ≥2 场、火力 ≥4 轮，
        不够则返回 (None, None) 让调用方退化为无投影行为（冷启动安全）。
        取最凶而非均值：攻坚投影回答的是「最坏的 Boss 能不能杀」，乐观账
        会在轮换到强 Boss 时重演满血败局。
        """
        worst_pool: float | None = None
        worst_fire: float | None = None
        for e in (self.stats.get("enemies") or {}).values():
            if int(e.get("boss_encounters", 0) or 0) < 2:
                continue
            pn = int(e.get("hp_pool_n", 0) or 0)
            if pn >= 2:
                v = float(e.get("hp_pool_sum", 0.0)) / pn
                worst_pool = v if worst_pool is None else max(worst_pool, v)
            fr = int(e.get("fire_rounds", 0) or 0)
            if fr >= 4:
                v = float(e.get("fire_sum", 0.0)) / fr
                worst_fire = v if worst_fire is None else max(worst_fire, v)
        return worst_pool, worst_fire

    def boss_race_vitals(self, act: int | None = None) -> tuple[float | None, float | None]:
        """已学习 Boss 组合的血池/火力均值估计（样本加权，第 397~402 批复盘新增）。

        兑现第 214 批遗留的「攻坚投影篝火端消费」：hp_pool/fire 自 138~141 批
        入库以来只有 boss_vitals_worst（最凶口径）一个读取方，篝火精算一直无米下锅。
        前夜裁决回答的是「像现在这套卡组打下一个普通 Boss 能不能赢」——取均值
        而非最凶（最凶含二三幕特化 Boss，会把一幕前夜全面判死）；资格门槛与
        boss_vitals_worst 相同（boss_encounters≥2、血池≥2 场、火力≥4 轮），
        聚合总量不足（血池 <2 场或火力 <4 轮）时返回 (None, None) 让调用方
        退化为旧行为（冷启动安全）。

        act 给定时优先聚合分幕子账本（第 506~515 局批复盘新增）：一幕 Boss 池
        实测血池 173~307，全幕混合均值 253 把一幕前夜系统性判死；分幕聚合量
        不足（血池 <2 场或火力 <4 轮）时回落全量口径（兼容旧库）。
        """
        if act:
            tot_pool = tot_pool_n = tot_fire = tot_fr = 0.0
            for e in (self.stats.get("enemies") or {}).values():
                sub = (e.get("boss_act") or {}).get(str(int(act))) or {}
                pn = int(sub.get("hp_pool_n", 0) or 0)
                if pn >= 1:
                    tot_pool += float(sub.get("hp_pool_sum", 0.0) or 0.0)
                    tot_pool_n += pn
                fr = int(sub.get("fire_rounds", 0) or 0)
                if fr >= 1:
                    tot_fire += float(sub.get("fire_sum", 0.0) or 0.0)
                    tot_fr += fr
            pool_a = (tot_pool / tot_pool_n) if tot_pool_n >= 2 else None
            fire_a = (tot_fire / tot_fr) if tot_fr >= 4 else None
            if pool_a is not None and fire_a is not None:
                return pool_a, fire_a
        tot_pool = tot_pool_n = 0.0
        tot_fire = tot_fr = 0.0
        for e in (self.stats.get("enemies") or {}).values():
            if int(e.get("boss_encounters", 0) or 0) < 2:
                continue
            pn = int(e.get("hp_pool_n", 0) or 0)
            if pn >= 2:
                tot_pool += float(e.get("hp_pool_sum", 0.0) or 0.0)
                tot_pool_n += pn
            fr = int(e.get("fire_rounds", 0) or 0)
            if fr >= 4:
                tot_fire += float(e.get("fire_sum", 0.0) or 0.0)
                tot_fr += fr
        pool = (tot_pool / tot_pool_n) if tot_pool_n >= 2 else None
        fire = (tot_fire / tot_fr) if tot_fr >= 4 else None
        return pool, fire

    def commit_room_damage(self, node_type: str, hp_lost: float, act: int | None = None,
                           floor: int | None = None,
                           hp_start_pct: float | None = None,
                           died: bool | None = None) -> None:
        """按房间类型累计战斗掉血（供路径先验动态校准）。

        act 传入时同步写入分幕键（第 79 局复盘新增）：跨幕混算的场均掉血
        掩盖了二幕伤害升级，路径投影因此系统性乐观。旧 rooms 聚合键保持
        原样写入（learned_room_factor 等旧消费方不受影响）。

        act+floor 同时传入时再写分幕分层段键 rooms_band（第 266 局批次复盘
        新增）：同幕内怪物池按楼层递增，全幕均值把后段杀手组合摊薄成便宜战。
        幕内行号由绝对层数折算（(floor-1)%17+1），与地图节点行号同口径。

        最坏情况战损记忆（第 258~262 批次复盘）：逐样本维护 hp_lost_max
        （单场最差掉血）——场均账在重尾分布前系统性乐观，262 局 49% 血进
        Monster 投影仅 ~9 点战损、实战 -39 阵亡；投影需要「坏一场掉多少」
        的尾部记忆，与事件层 hp_min（255~257 批）同构。旧条目缺键视为
        无尾部样本（None），自新样本起累积，不捏造回填。rooms/rooms_act/
        rooms_band 三级全部维护尾部记忆。

        健康进场子账本（第 396 局批次复盘新增）：Elite 战损统计的选择性
        偏差——健康状态几乎从不主动打精英，全量账本被低血被迫战垄断
        （一幕 Elite 场均 ~24、灰区悲观复核数学上永不可满足）。hp_start_pct
        ≥ elite_healthy_entry_pct 的 Elite 战斗额外计入 hp_lost_sum_hi/
        damage_events_hi 子账本（rooms 与 rooms_act 两级；band 样本太薄不写），
        供 elite_prior_healthy 消费。旧条目无此键即从空累积，历史数据不回填。

        存活尾部子账本（第 479~482 局批复盘新增）：hp_lost_max 是含死亡样本
        的 running max——阵亡场的掉血恒等于入场血量，量级只反映「进场多残」
        而非「这一战多危险」，max 因此被永久钉在满管血附近且永不衰减（实测：
        Monster 跨幕均值 10.1 / max 88，一幕前段均值 5.5 / max 80，Elite/Boss
        同病）。尾部定价与生存复核消费这份被污染的账，从 F1 满血起就全图
        触发（留痕「单场最差80打完仅剩0(≤8)」），先验被抬到 8→17~19 的幻影
        高位，候选间的真实差异被近似常数罚分淹没。自本批起 died=False 的样本
        额外计入 hp_lost_max_surv/damage_events_surv（三级同写；died=None 的
        旧调用按存活处理保持兼容），查询端 room_damage_worst 各层级优先返回
        成熟存活尾部；死亡样本照旧入全量账（场均/死亡率先验不受影响）。
        """
        if not self._learning_write_allowed():
            return
        e = self.stats["rooms"].setdefault(
            node_type, {"visits": 0, "outcome_sum": 0.0, "hp_lost_sum": 0.0, "damage_events": 0})
        e["hp_lost_sum"] = e.get("hp_lost_sum", 0.0) + max(0.0, hp_lost)
        e["damage_events"] = e.get("damage_events", 0) + 1
        e["hp_lost_max"] = max(float(e.get("hp_lost_max") or 0.0), max(0.0, float(hp_lost)))
        if died is None or not died:
            # 存活尾部子账本（第 479~482 局批复盘）：只有活着走出来的战斗才
            # 回答「坏一场掉多少」；阵亡场的掉血=入场血量，入账即污染（见 docstring）
            e["damage_events_surv"] = int(e.get("damage_events_surv", 0) or 0) + 1
            e["hp_lost_max_surv"] = max(float(e.get("hp_lost_max_surv") or 0.0),
                                        max(0.0, float(hp_lost)))
        _is_healthy_elite = (node_type == "Elite" and hp_start_pct is not None
                             and float(hp_start_pct) >= float(
                                 self.policy.get("elite_healthy_entry_pct", 0.75)))
        if _is_healthy_elite:
            e["hp_lost_sum_hi"] = e.get("hp_lost_sum_hi", 0.0) + max(0.0, hp_lost)
            e["damage_events_hi"] = int(e.get("damage_events_hi", 0)) + 1
            e["hp_lost_max_hi"] = max(float(e.get("hp_lost_max_hi") or 0.0),
                                      max(0.0, float(hp_lost)))
        if act is not None:
            ra = self.stats.setdefault("rooms_act", {}).setdefault(
                f"{node_type}@{int(act)}", {"hp_lost_sum": 0.0, "damage_events": 0})
            ra["hp_lost_sum"] += max(0.0, hp_lost)
            ra["damage_events"] += 1
            ra["hp_lost_max"] = max(float(ra.get("hp_lost_max") or 0.0), max(0.0, float(hp_lost)))
            if died is None or not died:
                ra["damage_events_surv"] = int(ra.get("damage_events_surv", 0) or 0) + 1
                ra["hp_lost_max_surv"] = max(float(ra.get("hp_lost_max_surv") or 0.0),
                                             max(0.0, float(hp_lost)))
            if _is_healthy_elite:
                ra["hp_lost_sum_hi"] = float(ra.get("hp_lost_sum_hi", 0.0)) + max(0.0, hp_lost)
                ra["damage_events_hi"] = int(ra.get("damage_events_hi", 0)) + 1
                ra["hp_lost_max_hi"] = max(float(ra.get("hp_lost_max_hi") or 0.0),
                                           max(0.0, float(hp_lost)))
            if floor is not None and int(floor) >= 1:
                row_in_act = (int(floor) - 1) % 17 + 1
                rb = self.stats.setdefault("rooms_band", {}).setdefault(
                    f"{node_type}@{int(act)}_b{act_floor_band(row_in_act)}",
                    {"hp_lost_sum": 0.0, "damage_events": 0})
                rb["hp_lost_sum"] += max(0.0, hp_lost)
                rb["damage_events"] += 1
                rb["hp_lost_max"] = max(float(rb.get("hp_lost_max") or 0.0),
                                        max(0.0, float(hp_lost)))
                if died is None or not died:
                    rb["damage_events_surv"] = int(rb.get("damage_events_surv", 0) or 0) + 1
                    rb["hp_lost_max_surv"] = max(float(rb.get("hp_lost_max_surv") or 0.0),
                                                 max(0.0, float(hp_lost)))

    def elite_prior_healthy(self, act: int, static_prior: float) -> tuple[float, bool]:
        """健康进场精英实证先验（第 396 局批次复盘新增）。

        因果链：健康状态从不主动打精英 → Elite 全量战损样本被低血被迫战
        垄断（本批留痕「Elite先验13→14/38→39」）→ 灰区悲观复核
        （先验×折抵上限×safety 2.5 ≈ 半管以上血）在 62%~90% 灰区带内
        数学不可满足 → 更规避 → 遗物/高质牌断供 → 卡组弱 → Boss 磨死
        （122 批已诊断的因果闭环，缺的是统计端的解法）。

        本口径回答「像现在这样健康地进场会掉多少」：rooms_act[f"Elite@{act}"]
        的健康子账本（≥3 样本）均值 × 战斗发生率，命中时幕数乘区归 1
        （分幕实测已含幕效应，与 room_damage_prior_act 同语义）；样本不足
        回落旧口径 (room_damage_prior_act)，行为与旧版严格一致。
        返回 (先验, 是否命中健康实证)。
        """
        ra = self.stats.get("rooms_act", {}).get(f"Elite@{int(act)}")
        n_hi = int((ra or {}).get("damage_events_hi", 0) or 0)
        if ra is not None and n_hi >= 3:
            avg = float(ra["hp_lost_sum_hi"]) / n_hi
            return avg * self.room_combat_rate("Elite"), True
        prior, _act_specific = self.room_damage_prior_act("Elite", static_prior, act)
        return prior, False


    def room_damage_band_stats(self, node_type: str, act: int,
                               row_in_act: int,
                               min_events: int = 3) -> tuple[float, float, int] | None:
        """分幕分层段掉血统计（第 266 局批次复盘新增）：返回 (场均, 单场最差, 样本数)。

        同幕怪物池随楼层递增——一幕前段 NIBBIT 场均 8.3、后段 VANTOM/
        KIN/CEREMONIAL 场均 41~43 且贡献生涯前三死因，全幕均值账把后段
        杀手摊薄成「便宜战」。层段样本 <min_events 时返回 None（宁可缺账
        不可捏造，调用方回落分幕/跨幕口径）；旧库条目无 hp_lost_max 时
        worst 返回 None 由调用方按无尾部处理。
        """
        rb = (self.stats.get("rooms_band") or {}).get(
            f"{node_type}@{int(act)}_b{act_floor_band(row_in_act)}")
        if not rb or int(rb.get("damage_events", 0) or 0) < min_events:
            return None
        n = int(rb["damage_events"])
        avg = float(rb["hp_lost_sum"]) / n
        worst = float(rb["hp_lost_max"]) if rb.get("hp_lost_max") is not None else None
        return avg, worst, n

    @staticmethod
    def _survived_tail(entry: dict | None, min_events: int) -> float | None:
        """存活尾部读取（第 479~482 局批复盘）：≥min_events 个非死亡样本才出账。

        旧条目缺 hp_lost_max_surv/damage_events_surv 键视为无存活尾部样本，
        返回 None 由调用方回落旧口径——宁可缺账不可捏造，与 hp_min 同规。
        """
        if not entry:
            return None
        n_surv = int(entry.get("damage_events_surv", 0) or 0)
        if n_surv < min_events or entry.get("hp_lost_max_surv") is None:
            return None
        return float(entry["hp_lost_max_surv"])

    def room_damage_worst(self, node_type: str, act: int | None = None,
                          row_in_act: int | None = None) -> float | None:
        """该房间类型历史单场最差掉血（重尾记忆，第 258~262 批次复盘新增）。

        分幕分层段样本（damage_events≥3）优先——尾部同样含幕间/段间难度
        跃迁，混算会把昂贵层段的尾部摊薄；无层段尾部时回落分幕条目
        （≥3 场），再回落跨幕条目（样本≥5）。旧库迁移条目无 hp_lost_max 键，
        返回 None（无尾部样本），调用方维持旧均值口径——尾部自新样本起累积，
        宁可缺账不可捏造。

        存活尾部优先（第 479~482 局批复盘）：各层级先查存活子账本
        （hp_lost_max_surv，≥3 个非死亡样本），命中即返回——它才是「坏一场
        （还活着的那种）能掉多少」的无偏答案；未成熟时回落含死亡样本的
        旧 hp_lost_max 口径，历史污染随新样本累积自然退役。层级顺序、样本
        门槛与回落行为均与旧版严格一致。
        """
        if act is not None and row_in_act is not None:
            b = self.room_damage_band_stats(node_type, act, row_in_act)
            if b is not None:
                rb = (self.stats.get("rooms_band") or {}).get(
                    f"{node_type}@{int(act)}_b{act_floor_band(row_in_act)}")
                _tail = self._survived_tail(rb, 3)
                if _tail is not None:
                    return _tail
                if b[1] is not None:
                    return b[1]
        if act is not None:
            ra = self.stats.get("rooms_act", {}).get(f"{node_type}@{int(act)}")
            if (ra and int(ra.get("damage_events", 0) or 0) >= 3):
                _tail = self._survived_tail(ra, 3)
                if _tail is not None:
                    return _tail
                if ra.get("hp_lost_max") is not None:
                    return float(ra["hp_lost_max"])
        e = self.stats.get("rooms", {}).get(node_type)
        if (e and int(e.get("damage_events", 0) or 0) >= 5):
            _tail = self._survived_tail(e, 3)
            if _tail is not None:
                return _tail
            if e.get("hp_lost_max") is not None:
                return float(e["hp_lost_max"])
        return None

    def commit_event_option(self, event_id: str, option_key: str, hp_delta: float,
                            gold_delta: float, died: bool, deck_delta: int = 0,
                            relic_delta: int = 0, potion_delta: int = 0) -> None:
        if not self._learning_write_allowed():
            return
        opts = self.stats["events"].setdefault(event_id, {})
        e = opts.setdefault(option_key, {"n": 0, "hp_delta_sum": 0.0, "gold_delta_sum": 0.0, "deaths": 0})
        e["n"] += 1
        e["hp_delta_sum"] += hp_delta
        e["gold_delta_sum"] += gold_delta
        e["card_delta_sum"] = float(e.get("card_delta_sum", 0.0)) + float(deck_delta)
        # 遗物/药水净增量（第 372~373 局批次复盘新增）：agent 端按选择前后
        # 的遗物/药水签名差值传入；旧库条目无此键，按 .get 缺省 0 兼容
        e["relic_delta_sum"] = float(e.get("relic_delta_sum", 0.0)) + float(relic_delta)
        e["potion_delta_sum"] = float(e.get("potion_delta_sum", 0.0)) + float(potion_delta)
        e["deaths"] += 1 if died else 0
        # 最坏情况记忆（第 255~257 批次复盘）：逐样本取最小生命增量，
        # 供事件层「吃下即死」闸门做尾部复核；None 表示尚无尾部样本
        _prev_min = e.get("hp_min")
        e["hp_min"] = float(hp_delta) if _prev_min is None else min(float(_prev_min), float(hp_delta))

    @staticmethod
    def _empty_card_stats() -> dict:
        return {"seen": 0, "offered": 0, "picked": 0, "plays": 0,
                "outcome_sum": 0.0, "bias": 0.0}

    def commit_card_seen(self, card_id: str) -> None:
        """Record one card in one offer (legacy single-card API).

        Callers that own the whole reward screen should use ``commit_card_offer``;
        it deduplicates duplicate ids and also maintains offer-level audit totals.
        """
        if not self._learning_write_allowed():
            return
        card_id = str(card_id or "").upper().rstrip("+")
        if not card_id:
            return
        e = self.stats["cards"].setdefault(card_id, self._empty_card_stats())
        e.setdefault("offered", 0)
        e["seen"] = int(e.get("seen", 0) or 0) + 1
        e["offered"] += 1

    def commit_card_offer(self, card_ids) -> int:
        """Record a complete reward offer exactly once; return unique candidates.

        Screen-instance deduplication belongs to Policy because only it sees screen
        transitions.  This store-level boundary still deduplicates repeated copies of
        one base id inside an offer, so ``seen`` means "offers containing this card",
        not evaluator invocations or candidate slots.
        """
        if not self._learning_write_allowed():
            return 0
        unique = []
        known = set()
        for raw in card_ids or []:
            card_id = str(raw or "").upper().rstrip("+")
            if card_id and card_id not in known:
                known.add(card_id)
                unique.append(card_id)
        if not unique:
            return 0
        tracking = self.stats.setdefault("card_offer_tracking", {
            "version": 2,
            "baseline_runs": int(self.stats["global"].get("runs", 0) or 0),
            "offers": 0,
            "candidate_observations": 0,
        })
        tracking["offers"] = int(tracking.get("offers", 0) or 0) + 1
        tracking["candidate_observations"] = int(
            tracking.get("candidate_observations", 0) or 0) + len(unique)
        for card_id in unique:
            self.commit_card_seen(card_id)
        return len(unique)

    def commit_card_play(self, card_id: str) -> None:
        if not self._learning_write_allowed():
            return
        e = self.stats["cards"].setdefault(card_id, self._empty_card_stats())
        e.setdefault("offered", 0)
        e["plays"] += 1

    # ---------- respawn-add roster / act-entry snapshots ----------

    def mark_respawn_add(self, enemy_key: str) -> None:
        """登记一次重生体实证（第 506~508 局批复盘新增）。

        调用时机：某敌人「同场被预测击杀 ≥2 次仍存活」当场坐实（policy 端
        _is_respawn_add 的确认瞬间，每场战斗每敌至多记一次）。跨局名册的
        生效门槛是 ≥2 场独立战斗的实证（is_known_respawn_add），单场误报
        （如连续两次高估伤害被格挡救活）不会污染名册。
        """
        if not self._learning_write_allowed():
            return
        if not enemy_key:
            return
        d = self.stats.setdefault("respawn_adds", {})
        e = d.setdefault(str(enemy_key), {"confirmations": 0})
        e["confirmations"] = min(99, int(e.get("confirmations", 0) or 0) + 1)

    def is_known_respawn_add(self, enemy_key: str) -> bool:
        """该种敌人是否已被 ≥2 场独立战斗实证为重生召唤物。"""
        if not enemy_key:
            return False
        d = self.stats.get("respawn_adds") or {}
        e = d.get(str(enemy_key)) or {}
        try:
            return int(e.get("confirmations", 0) or 0) >= 2
        except (TypeError, ValueError):
            return False

    def mark_leak_death_block(self, source: str, card_id: str) -> None:
        """LEAK_DEATH_GUARD 留痕：致死负面负载牌出现在某来源候选池并被屏蔽。

        第 801 局批复盘新增。调用位：_record_card_offer（奖励/CARD_SELECTION
        屏幕去重签名变更时，每屏每牌至多 +1）与商店货架评估循环。它只回答
        「守卫在生产端是否仍在正确显形」，效果评价归拾取端深负计价与对局结果。
        eval_reward_card 保持纯函数，本计数绝不进评分路径。
        """
        if not self._learning_write_allowed():
            return
        cid = str(card_id or "").upper().rstrip("+")
        if not cid:
            return
        d = self.stats.setdefault("leak_death_blocks", {})
        e = d.setdefault(cid, {"total": 0, "seen_at": {}})
        src = str(source or "?")
        seen = e.setdefault("seen_at", {})
        seen[src] = min(9999, int(seen.get(src, 0) or 0) + 1)
        e["total"] = min(9999, int(e.get("total", 0) or 0) + 1)

    def commit_act_entry(self, entry: dict) -> None:
        """记录一次进幕快照（第 506~508 局批复盘新增）。

        每幕首次开战时由 agent 端调用：把进幕时的血量/金币/药水/卡组规模/
        爆发吞吐落账，让「二幕消耗战死因」能对照进幕就绪度做定量归因。
        列表封顶 60 条（约 15~20 局的进幕样本），防 stats.json 无界膨胀。
        """
        if not self._learning_write_allowed():
            return
        d = self.stats.setdefault("act_entries", [])
        d.append(dict(entry))
        if len(d) > 60:
            del d[:-60]

    def act_entries(self) -> list:
        return list(self.stats.get("act_entries") or [])

    # ---------- run-end commits ----------

    def commit_run_end(self, outcome: float, victory: bool, picked_cards: list[str],
                       picked_relics: list[str], visited_rooms: list[str],
                       died_to_enemy: str | None, died_to_event: str | None,
                       raw_floor: float | None = None) -> None:
        if not self._learning_write_allowed():
            return
        g = self.stats["global"]
        g["runs"] += 1
        g["wins"] += 1 if victory else 0
        g["floors_total"] += outcome
        g["best_floor"] = max(g["best_floor"], int(outcome))
        if raw_floor is None:
            raw_floor = float(outcome) - (50.0 if victory else 0.0)
        raw_floor = max(0.0, float(raw_floor))
        g["floor_sum_raw"] = float(g.get("floor_sum_raw", 0.0)) + raw_floor
        g["best_floor_raw"] = max(int(g.get("best_floor_raw", 0)), int(raw_floor))
        if died_to_enemy:
            d = g["deaths_by_enemy"]
            d[died_to_enemy] = d.get(died_to_enemy, 0) + 1
        if died_to_event:
            d = g["deaths_by_event"]
            d[died_to_event] = d.get(died_to_event, 0) + 1
        for cid in picked_cards:
            e = self.stats["cards"].setdefault(cid, self._empty_card_stats())
            e.setdefault("offered", 0)
            e["picked"] += 1
            e["outcome_sum"] += outcome
        for raw_rid in picked_relics:
            rid = relic_stats_key(raw_rid)
            if rid is None:
                continue
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

    def _run_log_path(self, run_id: str) -> Path | None:
        """已有同 run_id 的对局日志（取命名最新者）——增量存档复用同一文件。"""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)[:80] or "run"
        try:
            matches = sorted((self.root / "runs").glob(f"*_{safe}.json"))
        except OSError:
            return None
        return matches[-1] if matches else None

    def load_run_log(self, run_id: str) -> dict | None:
        """读取同 run_id 的既有对局日志（断线重连续接局史用）；无则 None。"""
        p = self._run_log_path(run_id)
        if p is None:
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return d if isinstance(d, dict) else None

    def save_run_log(self, run_id: str, log: dict) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)[:80] or "run"
        # 同一对局复用同一文件（第 218 批复盘）：局中途增量存档 + 终局定稿
        # 写的是同一 run_id——各开新文件会让崩溃重启把一局拆成两条残缺日志
        path = self._run_log_path(run_id) \
            or (self.root / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.json")
        _save_json(path, log)
        return path
