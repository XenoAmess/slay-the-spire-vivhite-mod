
## 第 1 局复盘（2026-08-22 13:11）
- 结果：💀 失败｜进阶 0｜到达层数 9｜当局评分 9
- 死因：敌人组合 BYGONE_EFFIGY
- 本局拿牌：无
- 本局遗物：无
- 战斗记录：F9 Unknown战 掉血18（阵亡）
- 策略进化：block_safety: 1.00 → 1.05（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.250 → 0.242（经验累积，探索衰减）
- 生涯战绩：0/1 胜，当前目标进阶 0

## 第 2 局复盘（2026-08-22 13:21）
- 结果：💀 失败｜进阶 0｜到达层数 11｜当局评分 11
- 死因：敌人组合 ASSASSIN_RUBY_RAIDER+AXE_RUBY_RAIDER+CROSSBOW_RUBY_RAIDER
- 本局拿牌：SPITE, SHRUG_IT_OFF
- 本局遗物：白兽雕像, HAPPY_FLOWER
- 战斗记录：F6 Monster战 掉血21; F8 Elite战 掉血18; F11 Monster战 掉血1（阵亡）
- 策略进化：block_safety: 1.05 → 1.10（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.242 → 0.235（经验累积，探索衰减）
- 生涯战绩：0/2 胜，当前目标进阶 0

## 🧠 大模型复盘经验（2026-08-22 13:58，覆盖第 1~2 局）
- 「掉血1（阵亡）」类死亡要回溯整条 combat_notes 链归因：真凶是此前节点（F6 小怪 -21、真理石板事件 -34、F8 精英 -18）的累计失血，而非补刀敌人。
- 多页事件（如真理石板）每页 option_key 独立，探索会反复点开新页持续放血；经验收敛前用调低 Unknown 权重（1.15→0.95）规避。
- 进阶 0 初始卡组下，精英进场血量线 0.55 太激进，已上调至 0.65；精英基础权重 2.0→1.8。
- 两局 0 次休息：篝火权重 1.0→1.25，急需休息线 0.35→0.45，回血阈值 0.6→0.7，三管齐下纠正"从不休息"。
- 两局均死于普通战斗，block_safety 1.10→1.20 继续小幅上调。
- 单局拿牌 <2 是卡组强度危险信号；但当前所有卡牌 picked<4，样本不足，不动任何 bias，待数据累积。

## 第 3 局复盘（2026-08-22 14:16）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：BLUDGEON, TWIN_STRIKE, RAGE, HEADBUTT
- 本局遗物：无
- 战斗记录：F13 Monster战 掉血0; F13 Monster战 掉血6; F14 Monster战 掉血22; F15 Monster战 掉血3; F17 Boss战 掉血39（阵亡）
- 策略进化：block_safety: 1.20 → 1.25（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.235 → 0.228（经验累积，探索衰减）
- 生涯战绩：0/3 胜，当前目标进阶 0

## 第 4 局复盘（2026-08-22 14:20）
- 结果：💀 失败｜进阶 0｜到达层数 9｜当局评分 9
- 死因：敌人组合 VINE_SHAMBLER
- 本局拿牌：BREAKTHROUGH, BLUDGEON, RUPTURE, FEED, RAMPAGE, WHIRLWIND, BLUDGEON, BLUDGEON
- 本局遗物：无
- 战斗记录：F3 Monster战 掉血0; F4 Monster战 掉血0; F5 Monster战 掉血34; F6 Monster战 掉血26; F8 Unknown战 掉血10; F9 Unknown战 掉血10（阵亡）
- 当前高价值卡牌：BLUDGEON(11分/4局)
- 策略进化：block_safety: 1.25 → 1.30（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.228 → 0.221（经验累积，探索衰减）
- 生涯战绩：0/4 胜，当前目标进阶 0

## 第 5 局复盘（2026-08-22 14:26）
- 结果：💀 失败｜进阶 0｜到达层数 9｜当局评分 9
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：BASH, SETUP_STRIKE, UPPERCUT, SETUP_STRIKE, STONE_ARMOR, POMMEL_STRIKE, POMMEL_STRIKE, BLUDGEON, SPITE, UPPERCUT
- 本局遗物：开心小花
- 战斗记录：F5 Monster战 掉血33; F6 Monster战 掉血0; F6 Monster战 掉血3; F8 Elite战 掉血37; F9 Monster战 掉血6; F9 Monster战 掉血24（阵亡）
- 当前高价值卡牌：BLUDGEON(11分/5局)，SPITE(10分/2局)，POMMEL_STRIKE(9分/2局)，SETUP_STRIKE(9分/2局)，UPPERCUT(9分/2局)
- 策略进化：block_safety: 1.30 → 1.35（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.221 → 0.215（经验累积，探索衰减）
- 生涯战绩：0/5 胜，当前目标进阶 0

## 第 6 局复盘（2026-08-22 14:32）
- 结果：💀 失败｜进阶 0｜到达层数 13｜当局评分 13
- 死因：敌人组合 NIBBIT
- 本局拿牌：HEMOKINESIS, PILLAGE, BREAKTHROUGH, HEMOKINESIS, POMMEL_STRIKE, EVIL_EYE, RAMPAGE, SPITE
- 本局遗物：草莓, PANTOGRAPH
- 战斗记录：F5 Monster战 掉血0; F8 Elite战 掉血35; F9 Monster战 掉血15; F11 Monster战 掉血9; F12 Monster战 掉血0; F13 Monster战 掉血23（阵亡）
- 当前高价值卡牌：HEMOKINESIS(13分/2局)，BREAKTHROUGH(11分/2局)，SPITE(11分/3局)，RAMPAGE(11分/2局)，BLUDGEON(11分/5局)
- 当前低价值卡牌：SETUP_STRIKE(9分/2局)，UPPERCUT(9分/2局)，POMMEL_STRIKE(10分/3局)
- 策略进化：block_safety: 1.35 → 1.40（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.215 → 0.208（经验累积，探索衰减）
- 生涯战绩：0/6 胜，当前目标进阶 0

## 第 7 局复盘（2026-08-22 14:36）
- 结果：💀 失败｜进阶 0｜到达层数 8｜当局评分 8
- 死因：敌人组合 LEAF_SLIME_M+TWIG_SLIME_M
- 本局拿牌：SETUP_STRIKE, BLUDGEON, SWORD_BOOMERANG, HEADBUTT, SWORD_BOOMERANG, SPITE, SWORD_BOOMERANG
- 本局遗物：无
- 战斗记录：F5 Monster战 掉血0; F6 Monster战 掉血12; F7 Monster战 掉血0; F7 Monster战 掉血16; F8 Monster战 掉血3; F8 Monster战 掉血10（阵亡）
- 当前高价值卡牌：HEMOKINESIS(13分/2局)，HEADBUTT(12分/2局)，BREAKTHROUGH(11分/2局)，RAMPAGE(11分/2局)，POMMEL_STRIKE(10分/3局)
- 当前低价值卡牌：SWORD_BOOMERANG(8分/3局)，SETUP_STRIKE(9分/3局)，UPPERCUT(9分/2局)
- 策略进化：block_safety: 1.40 → 1.45（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.208 → 0.202（经验累积，探索衰减）
- 生涯战绩：0/7 胜，当前目标进阶 0

## 第 8 局复盘（2026-08-22 15:10）
- 结果：💀 失败｜进阶 0｜到达层数 13｜当局评分 13
- 死因：敌人组合 NIBBIT
- 本局拿牌：HEADBUTT, BREAKTHROUGH, SHRUG_IT_OFF
- 本局遗物：无
- 战斗记录：F13 Unknown战 掉血11（阵亡）
- 当前高价值卡牌：HEMOKINESIS(13分/2局)，HEADBUTT(13分/3局)，SHRUG_IT_OFF(12分/2局)，BREAKTHROUGH(12分/3局)，RAMPAGE(11分/2局)
- 当前低价值卡牌：SWORD_BOOMERANG(8分/3局)，SETUP_STRIKE(9分/3局)，UPPERCUT(9分/2局)
- 策略进化：block_safety: 1.45 → 1.50（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.202 → 0.196（经验累积，探索衰减）
- 生涯战绩：0/8 胜，当前目标进阶 0

## 第 9 局复盘（2026-08-22 15:29）
- 结果：💀 失败｜进阶 0｜到达层数 33｜当局评分 33
- 死因：敌人组合 THE_INSATIABLE
- 本局拿牌：RAMPAGE, UPPERCUT, HEADBUTT, UPPERCUT, BREAKTHROUGH, BLUDGEON, BLUDGEON, SWORD_BOOMERANG, SHRUG_IT_OFF, BLUDGEON, WHIRLWIND, VICIOUS, IMPERVIOUS, UPPERCUT, TWIN_STRIKE, STOMP, SPITE, BLUDGEON, MANGLE, ULTIMATE_STRIKE, IRON_WAVE, TRUE_GRIT, MANGLE, FIGHT_ME, HEADBUTT, SWORD_BOOMERANG, HOWL_FROM_BEYOND, MANGLE, POMMEL_STRIKE, RAMPAGE
- 本局遗物：HORN_CLEAT, 铜质鳞片, ETERNAL_FEATHER, 闪亮口红
- 战斗记录：F28 Unknown战 掉血13; F30 Monster战 掉血6; F31 Elite战 掉血14; F31 Elite战 掉血0; F33 Boss战 掉血15; F33 Boss战 掉血65（阵亡）
- 当前高价值卡牌：MANGLE(33分/3局)，TWIN_STRIKE(25分/2局)，UPPERCUT(23分/5局)，RAMPAGE(22分/4局)，WHIRLWIND(21分/2局)
- 当前低价值卡牌：SETUP_STRIKE(9分/3局)，HEMOKINESIS(13分/2局)，SPITE(15分/5局)
- 策略进化：block_safety: 1.50 → 1.55（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.196 → 0.190（经验累积，探索衰减）
- 生涯战绩：0/9 胜，当前目标进阶 0

## 第 10 局复盘（2026-08-22 15:35）
- 结果：💀 失败｜进阶 0｜到达层数 13｜当局评分 13
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：SPITE, DISMANTLE, POMMEL_STRIKE, DISMANTLE, HEMOKINESIS, TWIN_STRIKE, HEMOKINESIS, IRON_WAVE, UNRELENTING
- 本局遗物：小血瓶, ANCHOR, 永恒羽毛
- 战斗记录：F4 Monster战 掉血0; F7 Monster战 掉血11; F8 Monster战 掉血23; F11 Elite战 掉血44; F12 Monster战 掉血5; F13 Monster战 掉血24（阵亡）
- 当前高价值卡牌：MANGLE(33分/3局)，UPPERCUT(23分/5局)，IRON_WAVE(23分/2局)，RAMPAGE(22分/4局)，TWIN_STRIKE(21分/3局)
- 当前低价值卡牌：SETUP_STRIKE(9分/3局)，DISMANTLE(13分/2局)，HEMOKINESIS(13分/4局)
- 策略进化：block_safety: 1.55 → 1.60（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.190 → 0.184（经验累积，探索衰减）
- 生涯战绩：0/10 胜，当前目标进阶 0

## 🧠 第 1~10 局大复盘经验沉淀（2026-08-22 15:40，大模型教练）

- **核心死因是普通战 attrition，不是补刀怪**：7/10 局死于第一幕，致死战掉血少（-1~-24），真凶是此前 F5~F8 的 -20~-34 普通怪战。复盘要看完整 combat_notes 链。
- **卡组膨胀是输出密度不足的根因**：最佳局拿了 29 张牌；card_pick_threshold 2.0 → 3.0，只拿高价值牌，宁可跳牌。下轮观察：若拿牌 <5/局则回调 2.5。
- **高价值牌（优先拿）**：MANGLE(33) > UPPERCUT(23.4) > IRON_WAVE(23) > RAMPAGE(22) > TWIN_STRIKE(21) > WHIRLWIND(21) > HEADBUTT(20.8) > BLUDGEON(19.3)。
- **低价值牌（主动规避）**：SETUP_STRIKE(8.7，bias -1.5)、HEMOKINESIS(13.0 且自残，bias -1.0)、DISMANTLE(13.0)。自残牌在失血环境下要额外惩罚。
- **精英线 0.65 → 0.70**：65% 血 + 膨胀卡组进精英期望为负（F11 精英 -44 后 F13 即死）。
- **block_safety 手动加速 1.60 → 1.70**：自动 +0.05/局 的进化速率追不上失血速度，大复盘负责校正慢变量。
- **AoE（WHIRLWIND）价值上调**：2 次死于多怪组合补刀，AoE 缩短多怪战回合数。
- **事件学习正常**：真理石板 DECIPHER 已收敛为 -34 HP 负经验，贪心会自然回避，无需人工干预事件表。

## 第 11 局复盘（2026-08-22 15:48）
- 结果：💀 失败｜进阶 0｜到达层数 12｜当局评分 12
- 死因：敌人组合 PHROG_PARASITE
- 本局拿牌：VICIOUS, POMMEL_STRIKE, SETUP_STRIKE, SPITE, HEADBUTT, JUGGERNAUT, SPITE, SWORD_BOOMERANG, SPITE
- 本局遗物：梨子, 锚, TUNING_FORK
- 战斗记录：F6 Monster战 掉血8; F7 Elite战 掉血23; F9 Elite战 掉血0; F9 Elite战 掉血69; F12 Elite战 掉血0; F12 Elite战 掉血38（阵亡）
- 当前高价值卡牌：MANGLE(33分/3局)，UPPERCUT(23分/5局)，IRON_WAVE(23分/2局)，VICIOUS(22分/2局)，RAMPAGE(22分/4局)
- 当前低价值卡牌：SETUP_STRIKE(10分/4局)，DISMANTLE(13分/2局)，HEMOKINESIS(13分/4局)
- 策略进化：elite_min_hp_pct: 0.65 → 0.70（精英战阵亡，进场血量 42%，提高精英回避线）；exploration_rate: 0.184 → 0.179（经验累积，探索衰减）
- 生涯战绩：0/11 胜，当前目标进阶 0

## 第 12 局复盘（2026-08-22 17:19）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：FIGHT_ME, HEADBUTT, HEMOKINESIS, BREAKTHROUGH, HEMOKINESIS, IRON_WAVE, FIGHT_ME, UPPERCUT, HEMOKINESIS, HEMOKINESIS
- 本局遗物：缩放仪, PERMAFROST, 招架盾
- 战斗记录：F14 Elite战 掉血22; F15 Monster战 掉血0; F15 Monster战 掉血8; F17 Boss战 掉血23; F17 Boss战 掉血42; F17 Boss战 掉血15（阵亡）
- 当前高价值卡牌：MANGLE(33分/3局)，VICIOUS(22分/2局)，FIGHT_ME(22分/3局)，UPPERCUT(22分/6局)，RAMPAGE(22分/4局)
- 当前低价值卡牌：SETUP_STRIKE(10分/4局)，DISMANTLE(13分/2局)，SPITE(14分/9局)
- 策略进化：block_safety: 1.60 → 1.65（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.179 → 0.173（经验累积，探索衰减）
- 生涯战绩：0/12 胜，当前目标进阶 0

## 第 13 局复盘（2026-08-22 17:24）
- 结果：💀 失败｜进阶 0｜到达层数 9｜当局评分 9
- 死因：敌人组合 BYGONE_EFFIGY
- 本局拿牌：STRIKE_IRONCLAD, DEFEND_IRONCLAD, UNRELENTING, STRIKE_IRONCLAD, STRIKE_IRONCLAD, WHIRLWIND, VICIOUS, PILLAGE, VICIOUS, SWORD_BOOMERANG, STRIKE_IRONCLAD, SETUP_STRIKE, HEADBUTT, STRIKE_IRONCLAD, SWORD_BOOMERANG, UNRELENTING
- 本局遗物：无
- 战斗记录：F7 Unknown战 掉血1; F7 Unknown战 掉血9; F9 Elite战 掉血1; F9 Elite战 掉血0; F9 Elite战 掉血41; F9 Elite战 掉血1（阵亡）
- 当前高价值卡牌：MANGLE(33分/3局)，FIGHT_ME(22分/3局)，UPPERCUT(22分/6局)，RAMPAGE(22分/4局)，TWIN_STRIKE(21分/3局)
- 当前低价值卡牌：STRIKE_IRONCLAD(9分/5局)，SETUP_STRIKE(9分/5局)，UNRELENTING(10分/3局)
- 策略进化：elite_min_hp_pct: 0.70 → 0.75（精英战阵亡，进场血量 1%，提高精英回避线）；exploration_rate: 0.173 → 0.168（经验累积，探索衰减）
- 生涯战绩：0/13 胜，当前目标进阶 0

## 第 14 局复盘（2026-08-22 17:34）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：UPPERCUT, BREAKTHROUGH, SHRUG_IT_OFF, TWIN_STRIKE, UNRELENTING, SPITE, UPPERCUT, TRUE_GRIT, ANGER, VICIOUS, FEEL_NO_PAIN, TRUE_GRIT, UNRELENTING
- 本局遗物：WHETSTONE, 闪亮口红
- 战斗记录：F6 Monster战 掉血5; F8 Monster战 掉血20; F13 Monster战 掉血16; F14 Elite战 掉血23; F15 Monster战 掉血10; F17 Boss战 掉血57（阵亡）
- 当前高价值卡牌：MANGLE(33分/3局)，FIGHT_ME(22分/3局)，TRUE_GRIT(22分/3局)，RAMPAGE(22分/4局)，IRON_WAVE(21分/3局)
- 当前低价值卡牌：STRIKE_IRONCLAD(9分/5局)，SETUP_STRIKE(9分/5局)，PILLAGE(11分/2局)
- 策略进化：block_safety: 1.65 → 1.70（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.168 → 0.163（经验累积，探索衰减）
- 生涯战绩：0/14 胜，当前目标进阶 0

## 第 15 局复盘（2026-08-22 17:40）
- 结果：💀 失败｜进阶 0｜到达层数 6｜当局评分 6
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：BASH, SWORD_BOOMERANG, RAMPAGE, ANGER
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血26; F3 Monster战 掉血6; F4 Monster战 掉血2; F5 Monster战 掉血4; F6 Monster战 掉血42（阵亡）
- 当前高价值卡牌：MANGLE(33分/3局)，FIGHT_ME(22分/3局)，TRUE_GRIT(22分/3局)，IRON_WAVE(21分/3局)，UPPERCUT(21分/8局)
- 当前低价值卡牌：BASH(8分/2局)，STRIKE_IRONCLAD(9分/5局)，SETUP_STRIKE(9分/5局)
- 策略进化：block_safety: 1.70 → 1.75（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.163 → 0.158（经验累积，探索衰减）
- 生涯战绩：0/15 胜，当前目标进阶 0

## 第 16 局复盘（2026-08-22 18:07）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：RAMPAGE, RAMPAGE, BLUDGEON, UPPERCUT, FISTICUFFS, INFLAME, BLUDGEON, MANGLE
- 本局遗物：孙子兵法, 灯笼
- 战斗记录：F12 Unknown战 掉血17; F14 Monster战 掉血21; F15 Elite战 掉血43; F17 Boss战 掉血36（阵亡）
- 当前高价值卡牌：MANGLE(29分/4局)，FIGHT_ME(22分/3局)，TRUE_GRIT(22分/3局)，IRON_WAVE(21分/3局)，UPPERCUT(21分/9局)
- 当前低价值卡牌：BASH(8分/2局)，STRIKE_IRONCLAD(9分/5局)，SETUP_STRIKE(9分/5局)
- 策略进化：block_safety: 1.75 → 1.80（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.158 → 0.154（经验累积，探索衰减）
- 生涯战绩：0/16 胜，当前目标进阶 0

## 第 17 局复盘（2026-08-22 11:46）
- 结果：💀 失败｜进阶 0｜到达层数 6｜当局评分 6
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：BLUDGEON, TRUE_GRIT, FEEL_NO_PAIN, OFFERING
- 本局遗物：无
- 战斗记录：F2 Unknown战 掉血22; F3 Monster战 掉血2; F3 Monster战 掉血1; F4 Unknown战 掉血5; F5 Monster战 掉血19; F6 Monster战 掉血19（阵亡）
- 当前高价值卡牌：MANGLE(29分/4局)，FIGHT_ME(22分/3局)，IRON_WAVE(21分/3局)，UPPERCUT(21分/9局)，TWIN_STRIKE(20分/4局)
- 当前低价值卡牌：BASH(8分/2局)，STRIKE_IRONCLAD(9分/5局)，SETUP_STRIKE(9分/5局)
- 策略进化：exploration_rate: 0.154 → 0.149（经验累积，探索衰减）
- 生涯战绩：0/17 胜，当前目标进阶 0

## 🧠 第 11~17 局大复盘经验沉淀（2026-08-22 12:05，大模型教练）

- **死因结构变化：精英战成为第一杀手**：本周期精英战 4 次大失血（-23/-44/-69/-43）并直接或连锁导致 4 局死亡；且 Y1ZK、HATZYDJMQ4M4 两局的致命精英是**地图唯一候选**——贪心逐格选路在前期就走进漏斗，×0.1 软回避在单选项前完全失效。
- **代码级治疗（本次核心，参数调不了的病从代码治）**：
  1) `_map` 重写为全路径规划器：DFS 枚举到 Boss 行全部路径，按 path_danger_priors 场均掉血先验模拟血量演进；投影中途死亡 -100 分、进 Boss 血量 <35% 差值罚分；卡组越强先验越松（每张非基础牌 -3%，封顶 -40%）。
  2) 精英双门槛：新增 elite_min_deck_cards=4（非基础牌数），与血量线叠加——满血弱卡进精英实测送 69 血。
  3) 选牌端攻防再平衡：攻击占比 >55% 时攻击牌 -2.5；防御占比 <20% 时格挡技能 +1.5（17 局只拿过 1 张 DEFEND 而 block_safety 已顶格，两端价值观脱节）；自残牌（"失去N点生命"）-2.0。
  4) 篝火溢出保护：预计回血后 ≥97% 且有牌可升 → 改锻造。
- **新 policy 键**：rest_heal_fraction=0.30、path_danger_priors{Monster 8/Unknown 10/Elite 28/Boss 45}、path_hp_floor_pct=0.35、path_death_penalty=100、elite_min_deck_cards=4；block_safety 进化上限 1.8→2.1。
- **方法论教训**：
  1) 回避意图必须在更早的分支点全局规划，局部降权救不了唯一候选。
  2) 复盘固定检查项：跨子系统一致性（选牌端 vs 战斗端 vs 地图端的攻防价值观是否互相矛盾）。
  3) decide() 会吞异常保活、selfcheck 只测不抛异常——新决策逻辑必须配最小场景断言测试，否则 bug 静默变成错误决策（本次变量遮蔽 bug 即靠场景测试抓到）。
  4) 活着到 Boss 只是及格线，Boss 掉血 36~80 说明决定变量是斩杀线；下轮复盘开始统计 Boss 战回合数。

## 第 18 局复盘（2026-08-22 12:22）
- 结果：💀 失败｜进阶 0｜到达层数 22｜当局评分 22
- 死因：敌人组合 THE_OBSCURA
- 本局拿牌：HEADBUTT, ARMAMENTS, UNRELENTING, RAMPAGE, SWORD_BOOMERANG, RAMPAGE, TWIN_STRIKE, UNRELENTING, STOMP, RAMPAGE, SWORD_BOOMERANG, RAMPAGE, VICIOUS, CINDER, UNRELENTING, UPPERCUT, BATTLE_TRANCE, RUPTURE, UPPERCUT, CINDER, FIEND_FIRE, CINDER, THUNDERCLAP, UPPERCUT
- 本局遗物：斗篷扣, ORICHALCUM
- 战斗记录：F19 Monster战 掉血1; F19 Monster战 掉血0; F21 Monster战 掉血18; F22 Unknown战 掉血8; F22 Unknown战 掉血0; F22 Unknown战 掉血59（阵亡）
- 当前高价值卡牌：MANGLE(29分/4局)，STOMP(28分/2局)，FIGHT_ME(22分/3局)，CINDER(22分/3局)，IRON_WAVE(21分/3局)
- 当前低价值卡牌：BASH(8分/2局)，STRIKE_IRONCLAD(9分/5局)，SETUP_STRIKE(9分/5局)
- 策略进化：block_safety: 1.80 → 1.85（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.149 → 0.144（经验累积，探索衰减）
- 生涯战绩：0/18 胜，当前目标进阶 0

## 🧠 第 18 局专项复盘经验沉淀（2026-08-22 12:35，大模型教练）

- **死因定性变化**：本局不是 attrition 补刀死，而是"节点强度误判"——二幕 Unknown（THE_OBSCURA）实为三连遭遇战，单节点 -67 血，恒定掉血先验（Unknown=10）完全失真。地图先验已按幕数缩放 [1.0/1.7/2.3]，二幕 Unknown 额外 ×1.6。
- **代码级治疗（本轮核心）**：
  1) eval_reward_card 攻击边际价值改乘法衰减 clamp(1.3−1.4×攻击占比, 0.15, 1.2)——固定 -2.5 挡不住基础分 10+ 的攻击牌，第 18 局仍拿 24 张近全攻；
  2) 格挡稀缺改绝对数判定（<min_block_cards=5 即 +1.5），旧占比 <20% 判定在初始 4 防下永不触发；
  3) 卡组软上限：非基础牌 >20 后每超 1 张全候选 -0.9；
  4) _score_play 生存权重：致死威胁攻击 ×0.55/格挡 ×1.8，低血(<45%)攻击 ×0.75/格挡 ×1.4；击杀奖励豁免衰减；
  5) 药水栏满不再空转领取。
- **新 policy 键**：path_act_scale=[1.0,1.7,2.3]、unknown_gauntlet_act2_mult=1.6、deck_soft_cap=20、deck_overflow_penalty=0.9、min_block_cards=5；card_pick_threshold 2.0→3.0（发现磁盘值与上轮报告不符，已回读校验）。
- **selfcheck 新增 3 条场景断言**：选牌衰减、战斗生存优先级、地图幕数缩放——decide() 吞异常保活，回归只能靠断言抓。
- **方法论教训**：
  1) 固定减分是弱惩罚，抑制某类选择必须乘法化或设硬门槛；
  2) 场均统计直接套用到后续幕 = 用新手村经验走深渊；
  3) 关键行为尽量固化为代码结构而非依赖单一 JSON 参数（参数落盘可能被回滚）。
- **进展度量**：一幕 Boss 掉血 36~80 → 29，斩杀线初步缓解；下阶段瓶颈=二幕生存。观察项：soft-cap 后每局拿牌应降到 8~12 张，若仍死于二幕中段，考虑 min_block_cards 升至 6~7。

## 第 19 局复盘（2026-08-22 12:38）
- 结果：💀 失败｜进阶 0｜到达层数 22｜当局评分 22
- 死因：无（胜利）
- 本局拿牌：无
- 本局遗物：无
- 战斗记录：无
- 当前高价值卡牌：MANGLE(29分/4局)，STOMP(28分/2局)，FIGHT_ME(22分/3局)，CINDER(22分/3局)，IRON_WAVE(21分/3局)
- 当前低价值卡牌：BASH(8分/2局)，STRIKE_IRONCLAD(9分/5局)，SETUP_STRIKE(9分/5局)
- 策略进化：exploration_rate: 0.144 → 0.140（经验累积，探索衰减）
- 生涯战绩：0/19 胜，当前目标进阶 0

## 第 20 局复盘（2026-08-22 21:06）
- 结果：💀 失败｜进阶 0｜到达层数 7｜当局评分 7
- 死因：敌人组合 NIBBIT
- 本局拿牌：HEADBUTT, BASH, DEFEND_IRONCLAD, RUPTURE, BASH, BASH, BATTLE_TRANCE, BASH, CINDER, TRUE_GRIT
- 本局遗物：无
- 战斗记录：F4 Monster战 掉血10; F4 Monster战 掉血0; F5 Monster战 掉血17; F5 Monster战 掉血11; F6 Monster战 掉血35; F7 Monster战 掉血13（阵亡）
- 当前高价值卡牌：MANGLE(29分/4局)，STOMP(28分/2局)，FIGHT_ME(22分/3局)，IRON_WAVE(21分/3局)，UPPERCUT(21分/12局)
- 当前低价值卡牌：BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)，STRIKE_IRONCLAD(9分/5局)
- 策略进化：block_safety: 1.85 → 1.90（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.140 → 0.136（经验累积，探索衰减）
- 生涯战绩：0/20 胜，当前目标进阶 0

## 第 21 局复盘（2026-08-22 21:15）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：TWIN_STRIKE, SHRUG_IT_OFF, HOWL_FROM_BEYOND, BLUDGEON, MANGLE, BLUDGEON, BLUDGEON, SHRUG_IT_OFF, TWIN_STRIKE, HEADBUTT, IRON_WAVE, EVIL_EYE, POMMEL_STRIKE, MANGLE, MANGLE
- 本局遗物：JUZU_BRACELET, 地精之角
- 战斗记录：F9 Monster战 掉血29; F14 Elite战 掉血40; F15 Monster战 掉血15; F17 Boss战 掉血7; F17 Boss战 掉血18; F17 Boss战 掉血18（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(22分/3局)，UPPERCUT(21分/12局)
- 当前低价值卡牌：BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)，STRIKE_IRONCLAD(9分/5局)
- 策略进化：block_safety: 1.90 → 1.95（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.136 → 0.132（经验累积，探索衰减）
- 生涯战绩：0/21 胜，当前目标进阶 0

## 第 22 局复盘（2026-08-22 21:20）
- 结果：💀 失败｜进阶 0｜到达层数 7｜当局评分 7
- 死因：敌人组合 FOGMOG
- 本局拿牌：TWIN_STRIKE, EXPECT_A_FIGHT, SWORD_BOOMERANG, HEMOKINESIS
- 本局遗物：餐券
- 战斗记录：F2 Monster战 掉血6; F3 Monster战 掉血2; F4 Monster战 掉血11; F6 Monster战 掉血37; F7 Monster战 掉血24（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(22分/3局)，UPPERCUT(21分/12局)
- 当前低价值卡牌：BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)，STRIKE_IRONCLAD(9分/5局)
- 策略进化：block_safety: 1.95 → 2.00（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.132 → 0.128（经验累积，探索衰减）
- 生涯战绩：0/22 胜，当前目标进阶 0

## 第 23 局复盘（2026-08-22 21:33）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：STRIKE_IRONCLAD, IRON_WAVE, UNMOVABLE, UNMOVABLE, SHRUG_IT_OFF, STRIKE_IRONCLAD, CINDER, TWIN_STRIKE, HEADBUTT, IRON_WAVE, SHRUG_IT_OFF, TWIN_STRIKE, DISMANTLE, CINDER, SHRUG_IT_OFF, POMMEL_STRIKE, DISMANTLE, SHRUG_IT_OFF, SWORD_BOOMERANG, SHRUG_IT_OFF, SHRUG_IT_OFF
- 本局遗物：BLOOD_VIAL
- 战斗记录：F15 Monster战 掉血4; F15 Monster战 掉血0; F15 Monster战 掉血4; F17 Boss战 掉血0; F17 Boss战 掉血22; F17 Boss战 掉血22（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(22分/3局)，UPPERCUT(21分/12局)
- 当前低价值卡牌：BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)，SETUP_STRIKE(9分/5局)
- 策略进化：block_safety: 2.00 → 2.05（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.128 → 0.124（经验累积，探索衰减）
- 生涯战绩：0/23 胜，当前目标进阶 0

## 第 24 局复盘（2026-08-22 21:38）
- 结果：💀 失败｜进阶 0｜到达层数 7｜当局评分 7
- 死因：敌人组合 WRIGGLER
- 本局拿牌：TWIN_STRIKE, TWIN_STRIKE, EXPECT_A_FIGHT, STRIKE_IRONCLAD, HEADBUTT, HEADBUTT, EXPECT_A_FIGHT, STRIKE_IRONCLAD, HEADBUTT
- 本局遗物：无
- 战斗记录：F7 Elite战 掉血0; F7 Elite战 掉血16; F7 Elite战 掉血1; F7 Elite战 掉血26; F7 Elite战 掉血11; F7 Elite战 掉血10（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(22分/3局)，UPPERCUT(21分/12局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/3局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：elite_min_hp_pct: 0.75 → 0.80（精英战阵亡，进场血量 12%，提高精英回避线）；exploration_rate: 0.124 → 0.120（经验累积，探索衰减）
- 生涯战绩：0/24 胜，当前目标进阶 0

## 第 25 局复盘（2026-08-22 21:42）
- 结果：💀 失败｜进阶 0｜到达层数 5｜当局评分 5
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：BLUDGEON, POMMEL_STRIKE, EXPECT_A_FIGHT
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血11; F3 Monster战 掉血7; F4 Monster战 掉血6; F5 Monster战 掉血56（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(22分/3局)，UPPERCUT(21分/12局)
- 当前低价值卡牌：EXPECT_A_FIGHT(6分/4局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：block_safety: 2.05 → 2.10（普通战斗阵亡，略微上调防御权重）；exploration_rate: 0.120 → 0.117（经验累积，探索衰减）
- 生涯战绩：0/25 胜，当前目标进阶 0

## 第 26 局复盘（2026-08-22 21:50）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：无（胜利）
- 本局拿牌：无
- 本局遗物：无
- 战斗记录：无
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(22分/3局)，UPPERCUT(21分/12局)
- 当前低价值卡牌：EXPECT_A_FIGHT(6分/4局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：exploration_rate: 0.117 → 0.113（经验累积，探索衰减）
- 生涯战绩：0/26 胜，当前目标进阶 0

## 第 27 局复盘（2026-08-22 22:34）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：DISMANTLE, TAUNT, CINDER, HEADBUTT, UPPERCUT, RAMPAGE, UPPERCUT, HAND_OF_GREED, STONE_ARMOR, TAUNT, RAMPAGE
- 本局遗物：MERCURY_HOURGLASS
- 战斗记录：F12 Monster战 掉血3; F13 Monster战 掉血2; F13 Monster战 掉血11; F17 Boss战 掉血1; F17 Boss战 掉血18; F17 Boss战 掉血38（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(22分/3局)，UPPERCUT(20分/14局)
- 当前低价值卡牌：EXPECT_A_FIGHT(6分/4局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：exploration_rate: 0.113 → 0.110（经验累积，探索衰减）
- 生涯战绩：0/27 胜，当前目标进阶 0

## 第 28 局复盘（2026-08-22 22:43）
- 结果：💀 失败｜进阶 0｜到达层数 12｜当局评分 12
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：SHRUG_IT_OFF, WHIRLWIND, VICIOUS, HEADBUTT, HEADBUTT, SWORD_BOOMERANG, SHRUG_IT_OFF, IRON_WAVE, SHRUG_IT_OFF, SHRUG_IT_OFF, MOLTEN_FIST, SHRUG_IT_OFF
- 本局遗物：LUCKY_FYSH
- 战斗记录：F8 Monster战 掉血0; F9 Monster战 掉血0; F9 Monster战 掉血1; F9 Monster战 掉血0; F12 Monster战 掉血0; F12 Monster战 掉血42（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(22分/3局)，UPPERCUT(20分/14局)
- 当前低价值卡牌：EXPECT_A_FIGHT(6分/4局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：exploration_rate: 0.110 → 0.107（经验累积，探索衰减）
- 生涯战绩：0/28 胜，当前目标进阶 0

## 第 29 局复盘（2026-08-22 23:04）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：FIGHT_ME
- 本局遗物：无
- 战斗记录：F17 Unknown战 掉血35; F17 Unknown战 掉血11（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(21分/4局)，UPPERCUT(20分/14局)
- 当前低价值卡牌：EXPECT_A_FIGHT(6分/4局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：exploration_rate: 0.107 → 0.103（经验累积，探索衰减）
- 生涯战绩：0/29 胜，当前目标进阶 0

## 第 30 局复盘（2026-08-22 23:10）
- 结果：💀 失败｜进阶 0｜到达层数 7｜当局评分 7
- 死因：敌人组合 LEAF_SLIME_M+LEAF_SLIME_S+TWIG_SLIME_M+TWIG_SLIME_S
- 本局拿牌：UPPERCUT, TRUE_GRIT, SWORD_BOOMERANG, EXPECT_A_FIGHT
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血11; F3 Monster战 掉血4; F4 Monster战 掉血0; F5 Monster战 掉血32; F6 Monster战 掉血17; F7 Monster战 掉血17（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(21分/4局)，UPPERCUT(19分/15局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：exploration_rate: 0.103 → 0.100（经验累积，探索衰减）
- 生涯战绩：0/30 胜，当前目标进阶 0

## 第 31 局复盘（2026-08-22 23:16）
- 结果：💀 失败｜进阶 0｜到达层数 7｜当局评分 7
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：STRIKE_IRONCLAD, TWIN_STRIKE, SHRUG_IT_OFF, VICIOUS, HEADBUTT, TWIN_STRIKE
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血4; F3 Monster战 掉血3; F4 Monster战 掉血0; F6 Monster战 掉血50; F7 Monster战 掉血0; F7 Monster战 掉血30（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(21分/4局)，UPPERCUT(19分/15局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：exploration_rate: 0.100 → 0.097（经验累积，探索衰减）
- 生涯战绩：0/31 胜，当前目标进阶 0

## 第 32 局复盘（2026-08-22 23:21）
- 结果：💀 失败｜进阶 0｜到达层数 6｜当局评分 6
- 死因：敌人组合 FOGMOG
- 本局拿牌：SPITE, FLAME_BARRIER, FLAME_BARRIER, DRUM_OF_BATTLE, SPITE
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血6; F3 Monster战 掉血3; F4 Monster战 掉血2; F6 Monster战 掉血0; F6 Monster战 掉血69（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(21分/4局)，UPPERCUT(19分/15局)
- 当前低价值卡牌：FLAME_BARRIER(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.097 → 0.094（经验累积，探索衰减）
- 生涯战绩：0/32 胜，当前目标进阶 0

## 🧠 教练复盘 28~29 局沉淀（2026-08-22 23:24）

- **组合危险 ≠ 成员危险之和**：FUZZY_WURM_CRAWLER+SHRINKER_BEETLE 单体皆无害（场均掉血 -4/-5），组队后 10 战 6 死、场均 -25，全档案最致命（第 28/31 局两度死于它）。已新增 enemy_stance：历史死亡率≥30%（样本≥3）的组合自动转防守节奏——紧急血量线最高 0.60、攻击权重最低 ×0.85、格挡权重最高 ×1.15，决策理由带「⚠高危组合」标记。
- **自残必须定价到出牌端**：第 29 局终局 9 血面对 28 点意图先打【御血术】自掉 2 血再阵亡——选牌端的自残惩罚没有传导到战斗评分。现在「失去X点生命」攻击按当前血量扣分，致死回合无法终结战斗的自残牌直接禁玩（击杀最后一个敌人除外）。
- **致死回合启用禁玩线**：打不死人的攻击/AOE/功能牌/能力牌一律压到阈值以下（旧 ×0.35 衰减被基础分穿透，属「固定衰减挡不住高基础分」教训复发）；能击杀减员的攻击不受限——减员即减少意图来源。
- **增益类战斗药水此前永远用不出**：力量/敏捷/速度类不在「伤害/回复」关键词内，第 28 局囤三瓶带进坟墓。已并入硬仗用药判定。
- **重连附着局要识别**：决策数与到达层数严重不成比例（第 29 局 22 决策直跳 F17）＝大脑重启后附着到进行中对局，日志只覆盖后半程，统计归因打折看待。
- 本轮零参数改动，全部为代码结构修复；selfcheck 新增自残约束/高危姿态两条断言锁死行为。


## 第 33 局复盘（2026-08-22 23:30）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：STRIKE_IRONCLAD, RAMPAGE, UNRELENTING, RAMPAGE, BREAKTHROUGH, RAMPAGE, BLUDGEON, IRON_WAVE, HEADBUTT, SWORD_BOOMERANG, BLUDGEON
- 本局遗物：RAZOR_TOOTH, 永恒羽毛, WHETSTONE, 怀表
- 战斗记录：F7 Monster战 掉血18; F9 Monster战 掉血3; F11 Elite战 掉血36; F14 Elite战 掉血11; F15 Monster战 掉血4; F17 Boss战 掉血45（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(24分/7局)，FIGHT_ME(21分/4局)，UPPERCUT(19分/15局)
- 当前低价值卡牌：FLAME_BARRIER(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.094 → 0.091（经验累积，探索衰减）
- 生涯战绩：0/33 胜，当前目标进阶 0

## 第 34 局复盘（2026-08-22 23:35）
- 结果：💀 失败｜进阶 0｜到达层数 7｜当局评分 7
- 死因：敌人组合 VINE_SHAMBLER
- 本局拿牌：POMMEL_STRIKE, TWIN_STRIKE, TWIN_STRIKE, CINDER, MANGLE, ASHEN_STRIKE, CINDER
- 本局遗物：无
- 战斗记录：F4 Monster战 掉血0; F4 Monster战 掉血0; F5 Monster战 掉血20; F6 Monster战 掉血13; F7 Monster战 掉血10; F7 Monster战 掉血18（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(22分/8局)，FIGHT_ME(21分/4局)，UPPERCUT(19分/15局)
- 当前低价值卡牌：FLAME_BARRIER(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.091 → 0.089（经验累积，探索衰减）
- 生涯战绩：0/34 胜，当前目标进阶 0

## 第 35 局复盘（2026-08-22 23:45）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：SPITE
- 本局遗物：无
- 战斗记录：F15 Unknown战 掉血0; F17 Boss战 掉血66（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(22分/8局)，FIGHT_ME(21分/4局)，UPPERCUT(19分/15局)
- 当前低价值卡牌：FLAME_BARRIER(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.089 → 0.086（经验累积，探索衰减）
- 生涯战绩：0/35 胜，当前目标进阶 0

## 🧠 第 30~32 局复盘经验（2026-08-22 23:57）

1. **惩罚要精确到实例而非类别**：一张防御 409（瞬时时序抖动）不该拉黑同 id 的所有副本。第 31 局 F7 终局 17 血对 18 意图，黑名单连坐导致手上另一张可用的防御被禁用，无甲吃刀阵亡——黑名单/bias/回避逻辑都必须区分"这一次失败"与"这类牌不行"。
2. **服务端权威字段必须接入决策链**：`end_turn_will_kill_player` 是真实结算投影；回合内连续出牌会让本地意图快照过期，本地算术"脱险"不可信。致死未解除（gap>0）时所有非击杀牌让位于格挡。
3. **learned value 压不住启发式基础分时等于没信号**：EXPECT_A_FIGHT(6.6分/5局)、BASH(7.2分/6局) 的 card_value≈-2.8，对冲不了"格挡15+抽1"的 12+ 基础分。样本≥4 且场均低于全局均值 4+ 层 → 奖励端 -12 硬回避（card_is_proven_bad，随数据自演化）。
4. **奖励端永远不拿未升级的基础打/防牌**：生涯从奖励拾取 STRIKE_IRONCLAD×10 次，全部是浪费的卡位。
5. **药水期望价值随血量单调上升**："留着救急"在启发式引擎里退化为"带进坟墓"（三连死全带药）。低血量(≤35%)且有缺口 = 立即兑现；usage 分类不符或无法描述的药水在硬仗兜底使用。
6. **低血量时"前期积累卡牌"逻辑让位生存**：血量 < rest_urgent 线时 Monster 房权重 1.25→0.45。第 30 局 21% 血走进第 7 连战就是反例。
7. **复盘超时必须回滚工作区**：超时只作废报告不还原文件，半成品代码被后续备份提交裹挟入库且进程无感知——runs 30~31 实际跑在旧版代码上（floor_score 缺失），版本漂移严重干扰归因。

## 第 36 局复盘（2026-08-23 00:14）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：BLUDGEON, CRUELTY, SHRUG_IT_OFF, BLUDGEON, TRUE_GRIT, ANGER, RAMPAGE, STONE_ARMOR, RUPTURE, RAMPAGE
- 本局遗物：NUNCHAKU, 风箱
- 战斗记录：F9 Monster战 掉血40; F12 Elite战 掉血44; F14 Monster战 掉血7; F15 Monster战 掉血2; F17 Boss战 掉血0; F17 Boss战 掉血52（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(22分/8局)，FIGHT_ME(21分/4局)，UPPERCUT(19分/15局)
- 当前低价值卡牌：FLAME_BARRIER(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.086 → 0.084（经验累积，探索衰减）
- 生涯战绩：0/36 胜，当前目标进阶 0

## 第 37 局复盘（2026-08-23 00:19）
- 结果：💀 失败｜进阶 0｜到达层数 8｜当局评分 8
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：CINDER, DISMANTLE, RAMPAGE, BODY_SLAM, BATTLE_TRANCE, BLUDGEON, SHRUG_IT_OFF
- 本局遗物：无
- 战斗记录：F3 Monster战 掉血7; F4 Monster战 掉血0; F5 Monster战 掉血42; F6 Monster战 掉血8; F8 Monster战 掉血24; F8 Monster战 掉血23（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(22分/8局)，FIGHT_ME(21分/4局)，UPPERCUT(19分/15局)
- 当前低价值卡牌：FLAME_BARRIER(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.084 → 0.081（经验累积，探索衰减）
- 生涯战绩：0/37 胜，当前目标进阶 0

## 第 38 局复盘（2026-08-23 00:27）
- 结果：💀 失败｜进阶 0｜到达层数 8｜当局评分 8
- 死因：敌人组合 NIBBIT
- 本局拿牌：TRUE_GRIT, DISMANTLE, DISMANTLE, UPPERCUT, STRATAGEM
- 本局遗物：无
- 战斗记录：F3 Monster战 掉血8; F4 Monster战 掉血0; F5 Monster战 掉血30; F6 Monster战 掉血18; F8 Monster战 掉血32; F8 Monster战 掉血29（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(22分/8局)，FIGHT_ME(21分/4局)，UPPERCUT(19分/16局)
- 当前低价值卡牌：FLAME_BARRIER(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.081 → 0.079（经验累积，探索衰减）
- 生涯战绩：0/38 胜，当前目标进阶 0

## 第 39 局复盘（2026-08-23 00:37）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：SHRUG_IT_OFF, HEMOKINESIS, BULLY, SHRUG_IT_OFF, UNRELENTING, MANGLE, DISMANTLE, VICIOUS, HELLRAISER, FIGHT_ME, MANGLE, FIGHT_ME
- 本局遗物：赤牛, MERCURY_HOURGLASS
- 战斗记录：F8 Monster战 掉血5; F9 Elite战 掉血31; F9 Elite战 掉血3; F12 Monster战 掉血4; F14 Monster战 掉血2; F17 Boss战 掉血59（阵亡）
- 当前高价值卡牌：STOMP(28分/2局)，HOWL_FROM_BEYOND(25分/2局)，MANGLE(21分/10局)，FIGHT_ME(20分/6局)，UPPERCUT(19分/16局)
- 当前低价值卡牌：FLAME_BARRIER(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.079 → 0.076（经验累积，探索衰减）
- 生涯战绩：0/39 胜，当前目标进阶 0


## 🧠 第 26~35 局复盘经验（2026-08-23 00:38）

1. **屏幕闪断 ≠ 战斗结束**：Boss 转阶段过场把 COMBAT↔MODAL 来回切，旧逻辑按"离屏即结算"把一场 Boss 战拆成掉血 1/18/38 三笔——场均稀释、stance 失真、药水黑名单误重置。结算必须绑定语义信号（GAME_OVER/MAP/REWARD），过场屏只挂起；重连同组合同层视为延续。
2. **回合内能量是全局资源**：F17 实证第 1 回合蓄力期挥霍能量打输出，下轮 20 意图手持两张防御却 0 能量无甲硬吃。缺口未补且能量不够「攻击后再补防」时，非击杀攻击让路（击杀豁免）。
3. **无有效目标 ≠ 空回合**：敌人蓄力/转阶段暂不可选中时先等 ≤6 tick 再 end_turn 保底，白扔整轮能量=拖长战斗多吃意图。
4. **平局打破规则也是决策**：事件价值同为 0.0 时旧逻辑按选项位置取第一个（石炉加湿器 n=0 抢走失物盒 n=3）；tie-break 必须向高样本臂倾斜。
5. **探索要带安全底线**：ε-greedy 只看采样数不看价值符号，会把吃过 -34 血的选项再试一遍；探索池 = 欠采样 ∧ 非已知负收益（≤-5 排除）。
6. **一幕 Boss 斩杀线是新瓶颈**：3 局进 Boss 即败（38%/56%/82% 血进场全灭）。活着到 Boss 已稳定，下一步观察 Boss 战回合数随卡组成型的变化；精英灰区 64% 血进场的连锁代价记为观察项。

## 第 40 局复盘（2026-08-23 00:46）
- 结果：💀 失败｜进阶 0｜到达层数 13｜当局评分 13
- 死因：敌人组合 PHROG_PARASITE
- 本局拿牌：FLAME_BARRIER, FIGHT_ME, TRUE_GRIT, TRUE_GRIT, HEADBUTT, FIGHT_ME, SHRUG_IT_OFF, SHRUG_IT_OFF, STOMP, STOKE
- 本局遗物：HAPPY_FLOWER
- 战斗记录：F7 Monster战 掉血7; F7 Monster战 掉血25; F9 Monster战 掉血26; F11 Monster战 掉血17; F13 Elite战 掉血0; F13 Elite战 掉血33（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，STOMP(23分/3局)，MANGLE(21分/10局)，UPPERCUT(19分/16局)，RAMPAGE(18分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：elite_min_hp_pct: 0.72 → 0.77（精英战阵亡，进场血量 41%，提高精英回避线）；exploration_rate: 0.076 → 0.074（经验累积，探索衰减）
- 生涯战绩：0/40 胜，当前目标进阶 0

## 🧠 第 33~36 局复盘经验（2026-08-23 00:45）

1. **仿真器正确 ≠ 决策正确**：第 36 局路径规划"预计进 Boss 血量 65%"与实际分毫不差，但目标函数允许用光药水、放弃锻造去换血量百分比，走进注定打不赢的 Boss 战。"精确地走向错误目标"比"粗糙地走向正确目标"更危险。
2. **减权要乘在承诺上，不是乘在首项上**：选精英的总分含后续子树收益（精英+篝火回血组合分更高），灰区 ×0.5 只罚首节点权重被完全吞掉。凡"选 X 承担 X 全部后果"的决策，惩罚必须乘在该选项的整条路径总分上（新 _elite_path_gate：实测战损投影战后血量 < 需求线 → 整路径 ×0.1）。
3. **资源价值有场景梯度**：hard（需要资源）≠ premium（值得动用储备）。增益药水只在精英/Boss/真致死局启用，普通消耗战哪怕低血放血也不烧——第 36 局四瓶药全耗在非 Boss 房、Boss 战空手。
4. **生存判定要有余量维度**：lethal 与安全之间隔着"惨胜区"。补防后剩余缺口会把血量打穿到 max_hp 12% 以下时按致死回合处理（可击杀豁免）——20 血吃穿到 1 血不是脱险，是死缓。
5. **高危 Boss 提速也要抬格挡**：KIN 双子 8 战 4 死的败因是格挡缺口（5~11 甲硬吃 13~27 意图），enemy_stance 的 Boss 分支现在同时抬 atk/blk。
6. **统计因子防幸存者偏差**：learned_room_factor 用 outcome 加权房间时，精英房到访记录天然来自强局——对风险类节点该因子封顶 1.0，只许减不许加。

## 第 41 局复盘（2026-08-23 00:54）
- 结果：💀 失败｜进阶 0｜到达层数 11｜当局评分 11
- 死因：敌人组合 PHROG_PARASITE
- 本局拿牌：ARMAMENTS, UNRELENTING, IRON_WAVE, SHRUG_IT_OFF, BLUDGEON, TRUE_GRIT
- 本局遗物：活动星图, SHOVEL
- 战斗记录：F5 Monster战 掉血1; F6 Monster战 掉血18; F6 Monster战 掉血0; F8 Monster战 掉血0; F8 Monster战 掉血12; F11 Elite战 掉血50（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，STOMP(23分/3局)，MANGLE(21分/10局)，UPPERCUT(19分/16局)，RAMPAGE(18分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：elite_min_hp_pct: 0.77 → 0.82（精英战阵亡，进场血量 59%，提高精英回避线）；exploration_rate: 0.074 → 0.072（经验累积，探索衰减）
- 生涯战绩：0/41 胜，当前目标进阶 0

## 第 42 局复盘（2026-08-23 00:54）
- 结果：💀 失败｜进阶 0｜到达层数 11｜当局评分 11
- 死因：无（胜利）
- 本局拿牌：无
- 本局遗物：无
- 战斗记录：无
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，STOMP(23分/3局)，MANGLE(21分/10局)，UPPERCUT(19分/16局)，RAMPAGE(18分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/2局)
- 策略进化：exploration_rate: 0.072 → 0.070（经验累积，探索衰减）
- 生涯战绩：0/42 胜，当前目标进阶 0

## 第 46 局复盘（2026-08-23 01:22）
- 结果：💀 失败｜进阶 0｜到达层数 13｜当局评分 13
- 死因：敌人组合 BRUTE_RUBY_RAIDER+CROSSBOW_RUBY_RAIDER+TRACKER_RUBY_RAIDER
- 本局拿牌：IMPERVIOUS, MOLTEN_FIST, RAMPAGE, STONE_ARMOR, CINDER, DISMANTLE, TWIN_STRIKE, SHRUG_IT_OFF, RAGE
- 本局遗物：STONE_CRACKER
- 战斗记录：F4 Monster战 掉血2; F6 Monster战 掉血23; F7 Monster战 掉血11; F8 Monster战 掉血5; F12 Monster战 掉血25; F13 Unknown战 掉血30（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，STOMP(23分/3局)，MANGLE(21分/10局)，FIGHT_ME(18分/8局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：exploration_rate: 0.063 → 0.062（经验累积，探索衰减）
- 生涯战绩：0/46 胜，当前目标进阶 0

## 第 47 局复盘（2026-08-23 01:34）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：CINDER, COLOSSUS, SHRUG_IT_OFF, MOLTEN_FIST, TAUNT, SWORD_BOOMERANG, INFLAME, FIGHT_ME, FIGHT_ME, SPITE, RAMPAGE, THUNDERCLAP, RAGE
- 本局遗物：摆动球, ORICHALCUM
- 战斗记录：F13 Monster战 掉血23; F14 Monster战 掉血0; F15 Monster战 掉血8; F17 Boss战 掉血0; F17 Boss战 掉血29; F17 Boss战 掉血19（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，STOMP(23分/3局)，MANGLE(21分/10局)，THUNDERCLAP(20分/2局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：exploration_rate: 0.062 → 0.060（经验累积，探索衰减）
- 生涯战绩：0/47 胜，当前目标进阶 0

## 第 48 局复盘（2026-08-23 01:46）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：HELLRAISER, ANGER, CINDER, CRUELTY, TAUNT, CINDER, MOLTEN_FIST, CINDER, EQUILIBRIUM, TRUE_GRIT, STAMPEDE, SWORD_BOOMERANG
- 本局遗物：LUCKY_FYSH
- 战斗记录：F3 Monster战 掉血0; F4 Monster战 掉血14; F5 Monster战 掉血35; F6 Monster战 掉血12; F12 Monster战 掉血33; F17 Boss战 掉血58（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，STOMP(23分/3局)，MANGLE(21分/10局)，THUNDERCLAP(20分/2局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：exploration_rate: 0.060 → 0.058（经验累积，探索衰减）
- 生涯战绩：0/48 胜，当前目标进阶 0

## 第 49 局复盘（2026-08-23 01:55）
- 结果：💀 失败｜进阶 0｜到达层数 14｜当局评分 14
- 死因：敌人组合 FLYCONID+SNAPPING_JAXFRUIT
- 本局拿牌：THUNDERCLAP, ARMAMENTS, SPITE, CINDER, UPPERCUT, TWIN_STRIKE, SWORD_BOOMERANG, SHRUG_IT_OFF, STAMPEDE
- 本局遗物：STONE_CRACKER
- 战斗记录：F7 Monster战 掉血0; F7 Monster战 掉血24; F7 Monster战 掉血0; F12 Monster战 掉血12; F12 Monster战 掉血7; F14 Monster战 掉血25（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，STOMP(23分/3局)，MANGLE(21分/10局)，FIGHT_ME(18分/10局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：exploration_rate: 0.058 → 0.056（经验累积，探索衰减）
- 生涯战绩：0/49 胜，当前目标进阶 0

## 🧠 第 43~45 局复盘经验（2026-08-23 01:54）

1. **惩罚算子必须保序**：f<1 的乘法折扣只在正分半轴是惩罚，负分半轴是奖励——第 43 局精英闸门 ×0.1 把 -113.8 抬成 -11.38 压过篝火，20 血进精英阵亡。凡作用于带符号总分的折扣：先问符号，或改加性罚。
2. **全员皆坏的候选集里序信息比绝对值重要**：低血量全路径投影死亡时所有候选都吃 -100，评分差成噪声；死亡罚分现按存活深度递减（撑得更久更优），篝火天然胜出。
3. **UI 语义用握手不用猜**：删牌屏关键词识别失败曾把余烬+/上勾拳当垃圾删掉（两局实锤）——发起方显式传递上下文标志，关键词只做冗余校验。
4. **静默降级是最贵的失败模式**：目标列表过期时静默跳过可出牌→整回合弃权白吃 14 意图（44 局 F6/F12、45 局多次）。改为兜底打最高威胁存活敌人，409+实例黑名单接管真非法情形。
5. **学习键要归一化**：真理石板“继 续 解 读”空格变体+每页独立 n=0，单事件被探索放血 -39。读取侧按尾键(.options.X)跨页聚合，写入侧去空白。
6. 本轮四项修复全部落在代码层，参数零改动；新增 selfcheck 断言 3n/3o/3p/3q 锁死行为。

## 第 50 局复盘（2026-08-23 02:01）
- 结果：💀 失败｜进阶 0｜到达层数 6｜当局评分 6
- 死因：敌人组合 EYE_WITH_TEETH+FOGMOG
- 本局拿牌：ARMAMENTS, BLUDGEON, BULLY, PYRE
- 本局遗物：无
- 战斗记录：F4 Monster战 掉血0; F5 Monster战 掉血6; F6 Monster战 掉血27; F6 Monster战 掉血35; F6 Monster战 掉血0; F6 Monster战 掉血12（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，STOMP(23分/3局)，MANGLE(21分/10局)，FIGHT_ME(18分/10局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：exploration_rate: 0.056 → 0.055（经验累积，探索衰减）
- 生涯战绩：0/50 胜，当前目标进阶 0

## 第 51 局复盘（2026-08-23 02:01）
- 结果：💀 失败｜进阶 0｜到达层数 6｜当局评分 6
- 死因：无（胜利）
- 本局拿牌：无
- 本局遗物：无
- 战斗记录：无
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，STOMP(23分/3局)，MANGLE(21分/10局)，FIGHT_ME(18分/10局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：exploration_rate: 0.055 → 0.053（经验累积，探索衰减）
- 生涯战绩：0/51 胜，当前目标进阶 0

## 第 52 局复盘（2026-08-23 02:06）
- 结果：💀 失败｜进阶 0｜到达层数 8｜当局评分 8
- 死因：敌人组合 FLYCONID+TWIG_SLIME_M
- 本局拿牌：MOLTEN_FIST, BLUDGEON, STOMP, DISMANTLE, TRUE_GRIT
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血2; F4 Monster战 掉血0; F5 Monster战 掉血0; F7 Monster战 掉血69; F8 Monster战 掉血11（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，FIGHT_ME(18分/10局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：exploration_rate: 0.053 → 0.051（经验累积，探索衰减）
- 生涯战绩：0/52 胜，当前目标进阶 0

## 第 53 局复盘（2026-08-23 02:12）
- 结果：💀 失败｜进阶 0｜到达层数 5｜当局评分 5
- 死因：敌人组合 FOGMOG
- 本局拿牌：SHRUG_IT_OFF, SHRUG_IT_OFF, EVIL_EYE
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血11; F3 Monster战 掉血0; F4 Monster战 掉血0; F4 Monster战 掉血0; F5 Monster战 掉血80（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，FIGHT_ME(18分/10局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：exploration_rate: 0.051 → 0.050（经验累积，探索衰减）
- 生涯战绩：0/53 胜，当前目标进阶 0

## 第 54 局复盘（2026-08-23 02:22）
- 结果：💀 失败｜进阶 0｜到达层数 14｜当局评分 14
- 死因：敌人组合 BYRDONIS
- 本局拿牌：SALVO, FLAME_BARRIER, SHRUG_IT_OFF, ANGER, FEEL_NO_PAIN, DISMANTLE, CINDER, TRUE_GRIT, FIGHT_ME, CRUELTY, ANGER, VICIOUS
- 本局遗物：PLANISPHERE
- 战斗记录：F6 Monster战 掉血14; F7 Monster战 掉血17; F9 Monster战 掉血22; F12 Monster战 掉血17; F14 Elite战 掉血0; F14 Elite战 掉血38（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，UPPERCUT(18分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：elite_min_hp_pct: 0.87 → 0.90（精英战阵亡，进场血量 48%，提高精英回避线）
- 生涯战绩：0/54 胜，当前目标进阶 0

## 第 55 局复盘（2026-08-23 02:28）
- 结果：💀 失败｜进阶 0｜到达层数 6｜当局评分 6
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：TRUE_GRIT, SWORD_BOOMERANG, PACTS_END, CINDER
- 本局遗物：磨刀石
- 战斗记录：F2 Monster战 掉血0; F3 Monster战 掉血1; F4 Monster战 掉血0; F5 Monster战 掉血68; F6 Monster战 掉血12（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，UPPERCUT(18分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：本局无参数调整
- 生涯战绩：0/55 胜，当前目标进阶 0

## 🧠 第 50~51 局复盘经验（2026-08-23 02:30）

1. **幻影局根治（四次实证的统计灌水）**：大脑重启落在上一局结算屏时，GAME_OVER 帧上的旧 run_id 只是回声——新对局识别已排除该屏，且零决策对局一律不入账/不存日志/不触发复盘与 git。历史 4 个幻影局（第 19/26/42/51 局）由一次性迁移从生涯统计扣除（-4 局 -56 层，探索率回滚 4 次衰减），标记 phantom_repair_v1 幂等防重放。
2. **死因标注纠偏**："失败但无死亡数据"现在如实写"无记录（数据缺失）"，不再冒充"无（胜利）"误导复盘。
3. **Boss 前夜篝火必回血**：地图选中 boss_row-1 的篝火时向 _rest 传递语境，<95% 血强制休息（48 局实证：72% 血锻造后 Boss 战 -58 正好打死；回血 +24 可保命）；≥95% 才锻造。
4. 本轮五项修复全部落在代码层（agent/knowledge/policy/reflect/selfcheck），policy.json 参数零改动；新增 selfcheck 断言 3r/3s 锁死行为。

## 第 56 局复盘（2026-08-23 02:42）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：SWORD_BOOMERANG, TAUNT, HEADBUTT, TRUE_GRIT, CINDER, TAUNT, TAUNT, SHRUG_IT_OFF, CINDER, CINDER, EVIL_EYE, SHRUG_IT_OFF, TRUE_GRIT, SHRUG_IT_OFF, CRUELTY, TAUNT, CINDER, IMPATIENCE
- 本局遗物：PENDULUM
- 战斗记录：F14 Monster战 掉血12; F14 Monster战 掉血0; F15 Monster战 掉血0; F17 Boss战 掉血1; F17 Boss战 掉血15; F17 Boss战 掉血36（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，UPPERCUT(18分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(8分/4局)
- 策略进化：本局无参数调整
- 生涯战绩：0/56 胜，当前目标进阶 0

## 第 53 局复盘（2026-08-23 02:51）
- 结果：💀 失败｜进阶 0｜到达层数 6｜当局评分 6
- 死因：敌人组合 LEAF_SLIME_M+LEAF_SLIME_S+TWIG_SLIME_M+TWIG_SLIME_S
- 本局拿牌：DRUM_OF_BATTLE, SHRUG_IT_OFF, VICIOUS, IRON_WAVE
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血5; F3 Monster战 掉血0; F4 Monster战 掉血8; F5 Monster战 掉血13; F6 Monster战 掉血58（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，UPPERCUT(18分/19局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.056 → 0.055（经验累积，探索衰减）
- 生涯战绩：0/53 胜，当前目标进阶 0

## 🧠 第 52~55 局复盘经验（2026-08-23 02:57）

1. **四连死的统一公式**：健康开局（F2~F4 零失血）→ 单场放血战（-68/-69/-80/-38）→ 漏斗强制行军阵亡。放血战全部来自多体/召唤/滚雪球组合，生涯死亡榜前四名（FUZZY+SHRINKER 9死、KIN双子 6死、仪式兽 5死、FOGMOG 3死）无一例外。
2. **kill_bonus 曾是召唤物陷阱**：利齿之眼单场被"可击杀"斩首 10+ 次次次复活，雾菇本体意图 8→23 把 80 血磨穿。击杀定价改为「威胁占比折算 ×(0.4+0.6×share)，同场预测击杀≥2 次判重生体 ×0.25」——击杀的价值在消灭未来意图来源，不在血量归零事件。
3. **闸门盲区**：精英进场闸门只查候选首节点，54 局 47.5% 血时商店以 0.54 分压过篝火、子树里的 F13 精英无人过检，最终 48% 血撞上唯一候选阵亡。中段精英现在有半强度加性复检闸门（逐节点选路下中段尚未承诺，剂量随承诺程度递减）。
4. **45%~62% 是策略真空带**：急需线与锻造线、灰区下限之间落入"默认中性"的区间都是未审计的策略真空。新增 rest_wary_hp_pct=0.62 警戒带篝火 ×1.7；今后每加一条阈值线都必须问"两条线之间发生什么"。
5. **多体战斗是独立难度维度**：敌方数量抬长战斗期望与漏伤率——格挡价值按存活敌人数增值（+8%/个，上限+24%），AoE 攻击牌奖励端 +2.0 定价。治重尾伤害靠缩短战斗方差（集火/AoE/格挡密度），均值先验上调无解。
6. 本轮八项变更全部落在代码层 + 一键默认值（rest_wary_hp_pct），selfcheck 新增 3t/3u 断言锁死行为，SELFCHECK OK。

## 第 54 局复盘（2026-08-23 03:03）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：FIGHT_ME, FLAME_BARRIER, CRUELTY, TAUNT, IRON_WAVE, TWIN_STRIKE, RAMPAGE, SWORD_BOOMERANG, MOLTEN_FIST
- 本局遗物：锚, ETERNAL_FEATHER
- 战斗记录：F6 Monster战 掉血37; F7 Elite战 掉血9; F11 Monster战 掉血14; F14 Unknown战 掉血21; F15 Monster战 掉血16; F17 Boss战 掉血52（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，UPPERCUT(18分/19局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.055 → 0.053（经验累积，探索衰减）
- 生涯战绩：0/54 胜，当前目标进阶 0

## 第 55 局复盘（2026-08-23 03:10）
- 结果：💀 失败｜进阶 0｜到达层数 12｜当局评分 12
- 死因：敌人组合 FOGMOG
- 本局拿牌：BODY_SLAM, TAUNT, RUPTURE, CINDER, BLUDGEON, BLUDGEON, FIGHT_ME
- 本局遗物：弹珠袋, VAJRA
- 战斗记录：F2 Monster战 掉血3; F4 Monster战 掉血2; F5 Monster战 掉血0; F6 Monster战 掉血34; F9 Elite战 掉血0; F12 Monster战 掉血72（阵亡）
- 当前高价值卡牌：HOWL_FROM_BEYOND(25分/2局)，IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，UPPERCUT(18分/19局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.053 → 0.052（经验累积，探索衰减）
- 生涯战绩：0/55 胜，当前目标进阶 0

## 第 56 局复盘（2026-08-23 03:15）
- 结果：💀 失败｜进阶 0｜到达层数 7｜当局评分 7
- 死因：敌人组合 CUBEX_CONSTRUCT
- 本局拿牌：DEFEND_IRONCLAD, HOWL_FROM_BEYOND, HOWL_FROM_BEYOND, BREAKTHROUGH, BURNING_PACT, STRIKE_IRONCLAD, FEEL_NO_PAIN, HOWL_FROM_BEYOND, UPPERCUT
- 本局遗物：无
- 战斗记录：F4 Monster战 掉血8; F5 Monster战 掉血0; F5 Monster战 掉血17; F6 Monster战 掉血5; F6 Monster战 掉血17; F7 Monster战 掉血13（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，THUNDERCLAP(18分/3局)，UPPERCUT(17分/20局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：exploration_rate: 0.052 → 0.050（经验累积，探索衰减）
- 生涯战绩：0/56 胜，当前目标进阶 0

## 第 57 局复盘（2026-08-23 03:27）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：SHRUG_IT_OFF, SHRUG_IT_OFF, TRUE_GRIT, SHRUG_IT_OFF, CINDER, HEMOKINESIS, FLAME_BARRIER, IRON_WAVE, PANIC_BUTTON, HEMOKINESIS, PYRE, CINDER, SPITE, CINDER, SPITE, CINDER
- 本局遗物：PEN_NIB, 不休陀螺
- 战斗记录：F14 Monster战 掉血2; F14 Monster战 掉血0; F15 Monster战 掉血0; F15 Monster战 掉血0; F17 Boss战 掉血16; F17 Boss战 掉血38（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，THUNDERCLAP(18分/3局)，UPPERCUT(17分/20局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/57 胜，当前目标进阶 0

## 第 58 局复盘（2026-08-23 03:33）
- 结果：💀 失败｜进阶 0｜到达层数 6｜当局评分 6
- 死因：敌人组合 EYE_WITH_TEETH+FOGMOG
- 本局拿牌：MOLTEN_FIST, SHRUG_IT_OFF, INFLAME, FIGHT_ME
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血6; F3 Monster战 掉血1; F5 Monster战 掉血0; F6 Monster战 掉血54; F6 Monster战 掉血29（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，THUNDERCLAP(18分/3局)，UPPERCUT(17分/20局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/58 胜，当前目标进阶 0

## 第 59 局复盘（2026-08-23 03:45）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：STONE_ARMOR, UPPERCUT, TAUNT, TAUNT, BLUDGEON, HOWL_FROM_BEYOND, SHRUG_IT_OFF, MOLTEN_FIST, TRUE_GRIT, ANGER, UPPERCUT, SECOND_WIND, PANACHE
- 本局遗物：VAMBRACE, MUMMIFIED_HAND
- 战斗记录：F7 Monster战 掉血47; F9 Monster战 掉血28; F14 Monster战 掉血5; F15 Monster战 掉血7; F17 Boss战 掉血15; F17 Boss战 掉血40（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，THUNDERCLAP(18分/3局)，UPPERCUT(17分/22局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/59 胜，当前目标进阶 0

## 🧠 第 56~57 局大复盘经验（2026-08-23 03:44）
- 两局两种死法：**56=漏斗消耗死**——F4 岔路 44% 血仍吃满前期怪物加成 ×1.25，以 0.96 分压过 Unknown（25.52 vs 24.56），错失转向后十场连战漏斗行军阵亡；**57=迄今最健康败局**——运营满分进 Boss（64% 血），但卡组 0 AoE/最大单发 24，双子 Boss 七回合斩杀失败。KIN_FOLLOWER+KIN_PRIEST 升格头号杀手：12战7死。
- 修复①事件全零平值锁死：「涅奥的苦痛」凭 n=8 被无限重选（祝福类即时结算恒 0，样本数不再携带信息量）——并列 0 时改选样本最少者收集信息，出现首个非零收益即恢复"价值→样本"贪心（营养牡蛎 +11/次 一旦出现必被选中）。
- 修复②CARD_SELECTION 无阈值守卫：-3.9 防御/-6.2 打击曾被硬塞进卡组稀释质量；有 skip_reward_cards 动作且全员低于拾取阈值 → 放弃不拿，无跳过动作的强制屏 → 最小恶选择。
- 修复③floor≤8 怪房 ×1.25 加成增加血量门槛：<62%（警戒带）回落中性并注明「前期积累让位续航」。
- 修复④AoE 稀缺定价随存量递减：卡组存量 0/1/≥2 张 → +3.0/+2.0/+0.5，直击多体组合头号死因（致死榜前四全是多体/召唤组合）。
- 经验沉淀：①并列零值是多臂老虎机的信息死角，欠采样者优先直到出现第一个非零信号；②同一决策的多入口必须共享同一套门槛（REWARD 有阈值而 CARD_SELECTION 没有=后门）；③阶段目标从"活着到 Boss"升级为"杀死 Boss"，旧格挡气候需重新审计；④被迫的灰区精英也可能是好交易（57 局净赚遗物），统计上应区分计划内/漏斗精英。
- 观察点：AoE 入组率与多体死亡率联动；KIN Boss 死亡率能否 <50%；NEOW 采样发散与营养牡蛎复选率；警戒带内加成失效对前 8 层路线多样性的影响。


## 第 60 局复盘（2026-08-23 03:53）
- 结果：💀 失败｜进阶 0｜到达层数 9｜当局评分 9
- 死因：敌人组合 NIBBIT
- 本局拿牌：TAUNT, POMMEL_STRIKE, SECOND_WIND, SHRUG_IT_OFF, RAMPAGE, TRUE_GRIT, UNRELENTING, MOLTEN_FIST, THUNDERCLAP, BLUDGEON, WHIRLWIND
- 本局遗物：无
- 战斗记录：F3 Monster战 掉血0; F4 Unknown战 掉血0; F5 Monster战 掉血16; F7 Monster战 掉血28; F8 Monster战 掉血8; F9 Monster战 掉血28（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，UPPERCUT(17分/22局)，UNMOVABLE(17分/2局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/60 胜，当前目标进阶 0

## 🧠 第 58~59 局大复盘经验（2026-08-23 04:03）
- 两局对照：**58=重生体吸输出死**——FOGMOG 战「可击杀利齿之眼」13 次、本体只挨 6 刀，×0.25 衰减被"过量伤害记满额+威胁分成照发"两个评分漏洞架空，本体意图 8→22 滚雪球送光 83 血；**59=运营最好的败局**——AoE×2 如期入组、69% 血进 Boss、T4~T5 爆发 146 点，却死在 T6 绝命局：16 血/5 甲对 18 意图且手牌零格挡，pyrrhic 防线把三张攻击全压到禁玩线，3 能量原样结束回合白吃 13 刀。KIN 双子 15战9死（60%）。
- 修复①重生体压制 v2：确认重生体后过量伤害只记到当前血量、威胁分成清零、击杀奖励归零（单体+AoE 双端）——折价不等于改向，要拆掉虚高的每个计分入口。
- 修复②孤注一掷回合：致死且无可负担格挡牌时解除攻击禁玩压制并提速 ×1.3——"防御优先"规则在防御不可能时必须切换到抢斩杀这条唯一活路。
- 修复③溢出格挡贬值 0.2→0.03/点：59 局 Boss 首回合缺口 13 却堆了 34 甲零输出——无饱和上限的线性计分在需求线之外自相残杀。
- 经验沉淀：①部分修复等于没修复，结构性错误要拆每个计分入口；②生存规则必须区分可缓解/不可缓解致死；③资源价值相对于当前需求，饱和点就是需求线；④运营端进步要靠执行端兑现，瓶颈会随上层修复移动到下一环节（构建→入组→残局执行）。
- 观察点：重生体压制后多体组合死亡率；孤注一掷回合出现频率（高频=中段失血未治本）；Boss 首回合能量利用率；前期卡组厚度。

## 第 61 局复盘（2026-08-23 04:06）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：SHRUG_IT_OFF, IRON_WAVE, UNRELENTING, FIGHT_ME, RAMPAGE, UNMOVABLE, CINDER, SHRUG_IT_OFF, JUGGLING, STONE_ARMOR, ANGER, SHRUG_IT_OFF
- 本局遗物：STONE_CALENDAR
- 战斗记录：F11 Monster战 掉血12; F13 Unknown战 掉血9; F14 Monster战 掉血6; F15 Monster战 掉血22; F17 Boss战 掉血0; F17 Boss战 掉血35（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，UPPERCUT(17分/22局)，UNMOVABLE(17分/3局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/61 胜，当前目标进阶 0

## 第 62 局复盘（2026-08-23 04:13）
- 结果：💀 失败｜进阶 0｜到达层数 11｜当局评分 11
- 死因：敌人组合 PHROG_PARASITE
- 本局拿牌：FIGHT_ME, RAMPAGE, CRUELTY
- 本局遗物：ORICHALCUM
- 战斗记录：F8 Monster战 掉血13; F8 Monster战 掉血0; F8 Monster战 掉血5; F8 Monster战 掉血2; F11 Elite战 掉血0; F11 Elite战 掉血34（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/4局)，UPPERCUT(17分/22局)，UNMOVABLE(17分/3局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/62 胜，当前目标进阶 0

## 第 63 局复盘（2026-08-23 04:21）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：BREAKTHROUGH, STOMP, HOWL_FROM_BEYOND, BLUDGEON, CINDER, ANGER
- 本局遗物：LETTER_OPENER
- 战斗记录：F4 Monster战 掉血7; F5 Monster战 掉血34; F5 Monster战 掉血0; F9 Unknown战 掉血28; F12 Monster战 掉血22; F17 Boss战 掉血85（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/5局)，UPPERCUT(17分/22局)，UNMOVABLE(17分/3局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/63 胜，当前目标进阶 0

## 第 64 局复盘（2026-08-23 04:25）
- 结果：💀 失败｜进阶 0｜到达层数 5｜当局评分 5
- 死因：敌人组合 FLYCONID+SNAPPING_JAXFRUIT
- 本局拿牌：DISMANTLE, IRON_WAVE, SHRUG_IT_OFF, DRAMATIC_ENTRANCE
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血1; F3 Monster战 掉血16; F4 Monster战 掉血12; F5 Monster战 掉血42; F5 Monster战 掉血9（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/5局)，UPPERCUT(17分/22局)，UNMOVABLE(17分/3局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/64 胜，当前目标进阶 0

## 🧠 第 60~61 局大复盘经验（2026-08-23 04:31）
- 两局对照：**60=地图结构消耗死**——9 层无篝火 + 7 连战磨掉 80 血，F9 终局 17 血手握三打击一旋风斩全弃权（旧代码实证）；**61=投影失约的 Boss 处决**——路径规划每步都算出「预计进 Boss 血量」却从不进评分，44% 入场对场均战损半条命的仪式兽是数学必死局；T3 起意图 19→21→23→25 温水煮蛙，T4 手握五张攻击全弃权白吃 23 刀。
- 修复①Boss 入场要求线：路径投影 <65% 进 Boss 时按差值 ×110 罚分——投影必须变成约束，让 F10+ 的篝火/商店续航路线能压过继续消耗的战斗路线。
- 修复②败局竞速 v1：回合边界采样净损血 EMA，外推 ≤2 回合死亡且血 ≤60% 时解除能量预留、攻击提速 ×1.3（与孤注一掷互斥防双重放大）——单回合阈值（lethal/pyrrhic）挡不住叠力量型 Boss 的多回合死亡趋势。
- 经验沉淀：①投影不进评分就只是日记，任何"已知结论"要追问是否进了惩罚函数；②生存判定需要时间维度，快照只能做下限保护；③修复验证以决策日志行为标记为准而非代码库状态（两局都跑在上轮修复生效前的旧进程里）；④"谁杀的"看敌人统计、"为什么走到那里"看路径统计，两者不可互相替代。
- 观察点：入场线生效后进 Boss 血量中位能否 ≥65%；败局竞速触发频率与胜率；CEREMONIAL_BEAST/KIN 死亡率 <30%；新日志应出现「优先续航路线」「败局竞速全攻」标记。

## 第 65 局复盘（2026-08-23 04:34）
- 结果：💀 失败｜进阶 0｜到达层数 11｜当局评分 11
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：HEADBUTT, DEFEND_IRONCLAD, DEFEND_IRONCLAD, VICIOUS, DEFEND_IRONCLAD, SHRUG_IT_OFF, SHRUG_IT_OFF, SHRUG_IT_OFF, SHRUG_IT_OFF, CRUELTY, CRUELTY, JUGGLING, SHRUG_IT_OFF, SALVO
- 本局遗物：PARRYING_SHIELD
- 战斗记录：F6 Monster战 掉血0; F8 Monster战 掉血7; F8 Monster战 掉血11; F11 Unknown战 掉血0; F11 Unknown战 掉血44; F11 Unknown战 掉血13（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/5局)，UPPERCUT(17分/22局)，UNMOVABLE(17分/3局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/65 胜，当前目标进阶 0
