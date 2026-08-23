
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

## 第 66 局复盘（2026-08-23 04:41）
- 结果：💀 失败｜进阶 0｜到达层数 7｜当局评分 7
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：TAUNT, CINDER, STAMPEDE, SWORD_BOOMERANG, HOWL_FROM_BEYOND, SALVO
- 本局遗物：无
- 战斗记录：F3 Monster战 掉血0; F4 Monster战 掉血4; F5 Monster战 掉血53; F6 Monster战 掉血19; F7 Monster战 掉血6; F7 Monster战 掉血9（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/5局)，UPPERCUT(17分/22局)，UNMOVABLE(17分/3局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/66 胜，当前目标进阶 0

## 第 67 局复盘（2026-08-23 04:47）
- 结果：💀 失败｜进阶 0｜到达层数 12｜当局评分 12
- 死因：敌人组合 MAWLER
- 本局拿牌：HOWL_FROM_BEYOND, EVIL_EYE, HAND_OF_GREED, PACTS_END, IRON_WAVE, SPITE, FLAME_BARRIER, FLAME_BARRIER, SPITE
- 本局遗物：POTION_BELT
- 战斗记录：F2 Monster战 掉血13; F3 Monster战 掉血9; F5 Monster战 掉血6; F6 Monster战 掉血0; F9 Monster战 掉血41; F12 Monster战 掉血12（阵亡）
- 当前高价值卡牌：IMPERVIOUS(23分/2局)，MANGLE(21分/10局)，STOMP(19分/5局)，UPPERCUT(17分/22局)，UNMOVABLE(17分/3局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/67 胜，当前目标进阶 0

## 第 68 局复盘（2026-08-23 04:58）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：CRUELTY, UPPERCUT, IMPERVIOUS, ANGER, RAMPAGE, SHRUG_IT_OFF, SALVO, HEMOKINESIS, RAMPAGE, RAMPAGE, HELLRAISER, CRUELTY
- 本局遗物：双截棍, BAG_OF_MARBLES
- 战斗记录：F9 Monster战 掉血12; F14 Monster战 掉血0; F15 Monster战 掉血13; F17 Boss战 掉血38; F17 Boss战 掉血1; F17 Boss战 掉血38（阵亡）
- 当前高价值卡牌：IMPERVIOUS(21分/3局)，MANGLE(21分/10局)，STOMP(19分/5局)，UPPERCUT(17分/23局)，UNMOVABLE(17分/3局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/68 胜，当前目标进阶 0

## 🧠 第 62~64 局大复盘经验（2026-08-23 04:58）
- 三局对照：**62=地图漏斗消耗死**——F4~F10 几乎全单候选，血量 39%→34%→10% 阴跌，40% 血被唯一候选逼进 PHROG_PARASITE 精英（执行层无错，杠杆在上游消耗率）；**63=满血进 Boss 仍被处决**——仪式兽意图 18→26 逐轮 +2、卡组输出 ~12/回合数学必败，全场零锻造（每个篝火都低于 55% 锻造线），「锻造不救命」在战损≥满血的 Boss 面前是反话；**64=钝刀组合无感知**——FLYCONID+SNAPPING_JAXFRUIT 死亡率仅 15% 但场均咬掉 32% 血条，姿态中性、异鱼之油被"非精英房不用"锁死到 9 血才掏。
- 修复①组合战损维度姿态：场均掉血 ≥28% 血条即视同高危收紧（不再只看死亡率≥30%）；修复②高危组合解锁药水：场均战损 ≥30% 血条的普通房遭遇立即可用增益/攻击药水；修复③Boss 分档统计 + 前夜智能锻造：分档实测场均战损 ≥ 满血且入场线达标时改锻造——回血救不了败局，缩短战斗才是活路；修复④事件加牌稀释记账：每净增 1 张牌 -2 分，「带走这颗蛋」式看似免费的坑不再反复踩。
- 经验沉淀：①死亡率不是危险的唯一签名，频率维度与强度维度（场均战损占血条比）任一超标都要收紧姿态；②资源规则隐含的假设要显式化校验——"回血优于锻造"隐含"回血量能覆盖预期战损"，假设崩塌时要靠数据识别而非参数微调；③结算口径决定学习方向，隐性成本（卡组稀释）不进结算就会在同一个坑里反复跌倒；④单候选被迫局面的归因对象是"是什么让所有备选消失了"，不是最后一步选了什么。
- 时序警示：62~64 三局仍跑在 60~61 复盘修复生效前的旧进程里（入场线/败局竞速未被验证）。观察点：新对局对 ≥28% 血条组合是否出现「⚠高危组合」标记与提前用药；Boss 分档积累后是否出现「前夜改锻造」；BYRDONIS_NEST.TAKE 是否被平值探索排除。

## 🧠 第 65~66 局大复盘经验（2026-08-23 05:07）
- 两局对照 + 一个波及全史的实锤：**65=漏斗图消耗死**（F1 投影进 Boss 血量 0%、F2~F8 十一战磨到 10%，40% 血被唯一候选逼进精英，执行层无错）；**66=F5 劫掠者三人组一战 -53 后续航不可达**（三步「优先续航路线」注释无篝火可走，带药进坟）。真正的大鱼是对局日志铁证揪出的**出牌黑名单索引漂移**：mod 成功状态 "completed" 不在白名单 → 每张成功打出的牌被当失败拉黑；手牌 index 是位置序号、打出即前移 → 被拉黑槽位顶上无辜卡。66 局 F5 双打击被误拉黑携余能弃权吃 15 意图；65 局致死回合手握打击被禁玩阵亡——「孤注一掷」被静默废掉。两局共 5 个「有✓牌却 end_turn」，这是 0/66 的最大单一根因候选。
- 修复①状态白名单补 "completed"；②黑名单以「手牌数量未变」为有效期，手牌一变整体释放（31 局 409 防护保持精确拉黑）；③死亡率≥30% 的普通房组合自动认定硬仗解锁药水——与 62~64 的战损维度互补：FUZZY+SHRINKER 场均 25% 血条恰好躲过战损阈值，处决型与钝刀型各需一维；④高危姿态格挡/紧急线系数加强（+0.30/+0.20 per sev，攻击压制不动=防而不缩）；⑤拿牌门槛随卡组膨胀每超一张 +1.5（24 张卡组照单全收的注水止住）。自检新增 3ff/3gg/3hh 三组回归，SELFCHECK OK。
- 经验沉淀：①"成功"也要进协议校验——状态枚举是隐式契约，漏一个词每次成功都变失败记账；②位置索引进长期记忆前必须定义"所指对象何时失效"，黑名单的失效条件要绑定手牌变化事件；③弃权回合是最贵的决策错误（白吃整轮意图+整轮能量作废），审计优先扫「有✓牌却 end_turn」模式，它是静默失效逻辑的第一指纹；④危险画像 = 死亡率 × 战损占比双指标，单一维度各漏一半杀手；⑤上限要做成准入门槛抬升而非价格折扣，否则必被高基础分选项碾压。
- 时序警示：65~66 两局同样可能跑在更早批次修复生效前的旧进程里。生效验证看行为标记：①「有✓牌却结束回合」频率归零；②每场能量消耗/出牌数上升、场均掉血下降；③死亡率型组合遭遇出现硬仗用药；④单局拿牌 ≤10。

## 第 69 局复盘（2026-08-23 05:10）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：TAUNT, UNRELENTING, STONE_ARMOR, STONE_ARMOR, THUNDERCLAP, BREAKTHROUGH, UPPERCUT, SPITE, SECOND_WIND, BARRICADE
- 本局遗物：JUZU_BRACELET
- 战斗记录：F7 Monster战 掉血7; F9 Unknown战 掉血16; F12 Monster战 掉血2; F13 Monster战 掉血1; F14 Monster战 掉血11; F17 Boss战 掉血76（阵亡）
- 当前高价值卡牌：IMPERVIOUS(21分/3局)，MANGLE(21分/10局)，STOMP(19分/5局)，UPPERCUT(17分/24局)，UNMOVABLE(17分/3局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/69 胜，当前目标进阶 0

## 第 70 局复盘（2026-08-23 05:20）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：SHRUG_IT_OFF, RESTLESSNESS, THUNDERCLAP, BLUDGEON, CINDER, SHRUG_IT_OFF, CINDER, RUPTURE, HEADBUTT, MANGLE, STOMP, UNMOVABLE
- 本局遗物：PEN_NIB
- 战斗记录：F6 Monster战 掉血34; F12 Monster战 掉血24; F14 Monster战 掉血6; F15 Monster战 掉血13; F17 Boss战 掉血40; F17 Boss战 掉血45（阵亡）
- 当前高价值卡牌：IMPERVIOUS(21分/3局)，MANGLE(20分/11局)，STOMP(18分/6局)，UPPERCUT(17分/24局)，UNMOVABLE(17分/4局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/70 胜，当前目标进阶 0

## 第 71 局复盘（2026-08-23 05:33）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：FLAME_BARRIER, SHRUG_IT_OFF, BREAKTHROUGH, SHRUG_IT_OFF, SPITE, HEADBUTT, UNMOVABLE, IMPERVIOUS, VICIOUS, STONE_ARMOR, FLAME_BARRIER, FLAME_BARRIER, FLAME_BARRIER, SHRUG_IT_OFF, SHRUG_IT_OFF
- 本局遗物：餐券
- 战斗记录：F17 Boss战 掉血7; F17 Boss战 掉血8; F17 Boss战 掉血2; F17 Boss战 掉血11; F17 Boss战 掉血20; F17 Boss战 掉血32（阵亡）
- 当前高价值卡牌：MANGLE(20分/11局)，IMPERVIOUS(20分/4局)，STOMP(18分/6局)，UPPERCUT(17分/24局)，UNMOVABLE(17分/5局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/71 胜，当前目标进阶 0

## 第 72 局复盘（2026-08-23 05:37）
- 结果：💀 失败｜进阶 0｜到达层数 5｜当局评分 5
- 死因：敌人组合 WRIGGLER
- 本局拿牌：INFLAME, VICIOUS
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血1; F4 Monster战 掉血3; F5 Unknown战 掉血80（阵亡）
- 当前高价值卡牌：MANGLE(20分/11局)，IMPERVIOUS(20分/4局)，STOMP(18分/6局)，UPPERCUT(17分/24局)，UNMOVABLE(17分/5局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/72 胜，当前目标进阶 0

## 第 73 局复盘（2026-08-23 05:46）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：STONE_ARMOR, THUNDERCLAP, FLAME_BARRIER, HEADBUTT, THUNDERCLAP, FLAME_BARRIER, FIGHT_ME, CONFLAGRATION, POMMEL_STRIKE, FLAME_BARRIER, HEADBUTT, FIGHT_ME, THUNDERCLAP, TAUNT
- 本局遗物：棋子, WAR_PAINT
- 战斗记录：F14 Monster战 掉血0; F14 Monster战 掉血3; F15 Unknown战 掉血0; F15 Unknown战 掉血20; F15 Unknown战 掉血1; F17 Boss战 掉血38（阵亡）
- 当前高价值卡牌：MANGLE(20分/11局)，IMPERVIOUS(20分/4局)，STOMP(18分/6局)，UPPERCUT(17分/24局)，UNMOVABLE(17分/5局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/73 胜，当前目标进阶 0

## 第 74 局复盘（2026-08-23 05:56）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：RAMPAGE, WHIRLWIND, HEADBUTT, TRUE_GRIT, TRUE_GRIT, UNMOVABLE, STONE_ARMOR, POMMEL_STRIKE, HELLRAISER, UPPERCUT, STOMP, DARK_EMBRACE
- 本局遗物：GREMLIN_HORN
- 战斗记录：F7 Monster战 掉血6; F11 Monster战 掉血8; F13 Monster战 掉血2; F14 Monster战 掉血0; F17 Boss战 掉血65; F17 Boss战 掉血15（阵亡）
- 当前高价值卡牌：MANGLE(20分/11局)，IMPERVIOUS(20分/4局)，STOMP(18分/7局)，UPPERCUT(17分/25局)，UNMOVABLE(17分/6局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/74 胜，当前目标进阶 0

## 🧠 第 71 局大复盘经验（2026-08-23 06:06）
- 三局同因：69/70/71 全部满血进 Boss 全部死于 Boss——「活到 Boss」已通关，「杀死 Boss」是新瓶颈。71 局日志揪出两个波及 Boss 战的实锤：①Vantom 每阶段结束强制从手牌献祭一张（kind=combat_hand_select），旧逻辑按"最高价值"点选，五连把火焰屏障+×3/耸肩无视+×2 喂给 Boss，伤口×2~3 在候选里视而不见——防御核心自拆后手牌被伤口淹没、输出退化成裸打击，阶段掉血 7/8/2→11/20/32 逐段崩盘；②火焰屏障+（伤害6+格挡16）被 dmg>0 分支当弱攻击评分，致死回合压到禁玩线弃权——16 点格挡本可完全抵消当轮意图。
- 修复①战斗手牌强制选牌按 badness 献祭最不值钱者（状态>未升级基础>低价值），理由带「战斗献祭」标记；②混合牌攻防双面向取优，有缺口走格挡面、无缺口回落攻击面；③拾取端三连：同名重复从第3张起每张-3、「拿了不打」(picked≥4 且 plays≤半数)额外-4、攻击枯竭补攻击奖励随深度加码。自检新增 3ii/3jj/3kk 三组回归，SELFCHECK OK，真实知识库复现三场景全部翻转。
- 经验沉淀：①同一屏幕名下藏着相反语义，"选择"类决策先问代价由谁承担——敌方发起的选择玩家必然受损；②多阶段 Boss 的真实血条=各阶段之和×阶段间资源税，一次错误献祭以"后续每回合多吃意图"复利结算；③数值解析的第一命中分支决定牌的人格，复合特征必须每面独立评分再取优；④出牌率是拾取端的照妖镜，plays/picked 才是"真有用"的证据。
- 时序警示：大脑进程未重启前旧代码仍在跑，72~74 局不作修复效果证据。生效判定看行为标记：Boss 战日志出现「战斗献祭」且交状态/基础牌；「手握可出防牌弃权致死」归零；单局同名牌≤3。
## 第 75 局复盘（2026-08-23 06:08）
- 结果：💀 失败｜进阶 0｜到达层数 15｜当局评分 15
- 死因：敌人组合 BYGONE_EFFIGY
- 本局拿牌：HEMOKINESIS, ARMAMENTS, BREAKTHROUGH, IMPERVIOUS, THUNDERCLAP, TAUNT, CRUELTY, STONE_ARMOR
- 本局遗物：STONE_CRACKER
- 战斗记录：F13 Monster战 掉血3; F14 Monster战 掉血0; F14 Monster战 掉血0; F15 Elite战 掉血2; F15 Elite战 掉血5; F15 Elite战 掉血18（阵亡）
- 当前高价值卡牌：MANGLE(20分/11局)，IMPERVIOUS(19分/5局)，STOMP(18分/7局)，UPPERCUT(17分/25局)，UNMOVABLE(17分/6局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/75 胜，当前目标进阶 0

## 第 76 局复盘（2026-08-23 06:18）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：CINDER, SECOND_WIND, THUNDERCLAP, SHRUG_IT_OFF, TWIN_STRIKE, WHIRLWIND, ARMAMENTS, THE_GAMBIT, THRUMMING_HATCHET, FEEL_NO_PAIN, HOWL_FROM_BEYOND, CINDER
- 本局遗物：苦无, POCKETWATCH
- 战斗记录：F8 Elite战 掉血59; F9 Unknown战 掉血0; F9 Unknown战 掉血0; F9 Unknown战 掉血8; F14 Monster战 掉血13; F17 Boss战 掉血42（阵亡）
- 当前高价值卡牌：MANGLE(20分/11局)，IMPERVIOUS(19分/5局)，STOMP(18分/7局)，UPPERCUT(17分/25局)，UNMOVABLE(17分/6局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/76 胜，当前目标进阶 0

## 第 77 局复盘（2026-08-23 06:36）
- 结果：💀 失败｜进阶 0｜到达层数 22｜当局评分 22
- 死因：敌人组合 SPINY_TOAD
- 本局拿牌：THUNDERCLAP, HEADBUTT, SHRUG_IT_OFF, BLUDGEON, BLUDGEON, TAUNT, HEADBUTT, BLUDGEON, ANGER, MANGLE, FIGHT_ME, MANGLE, PACTS_END, STAMPEDE, MANGLE, MANGLE, CONFLAGRATION, MANGLE, TRUE_GRIT, HOWL_FROM_BEYOND, BLUDGEON, UPPERCUT, MANGLE, MANGLE
- 本局遗物：战纹涂料, NUNCHAKU
- 战斗记录：F20 Monster战 掉血8; F21 Monster战 掉血44; F21 Monster战 掉血0; F22 Monster战 掉血10; F22 Monster战 掉血0; F22 Monster战 掉血15（阵亡）
- 当前高价值卡牌：MANGLE(21分/18局)，CONFLAGRATION(20分/2局)，IMPERVIOUS(19分/5局)，STOMP(18分/7局)，UPPERCUT(17分/26局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/77 胜，当前目标进阶 0

## 第 78 局复盘（2026-08-23 06:48）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：THUNDERCLAP, CINDER, SECOND_WIND, SHRUG_IT_OFF, FLAME_BARRIER, SWORD_BOOMERANG, ANGER, RAMPAGE, UNMOVABLE
- 本局遗物：PEN_NIB
- 战斗记录：F6 Monster战 掉血24; F7 Monster战 掉血32; F12 Monster战 掉血7; F14 Monster战 掉血7; F15 Monster战 掉血19; F17 Boss战 掉血63（阵亡）
- 当前高价值卡牌：MANGLE(21分/18局)，CONFLAGRATION(20分/2局)，IMPERVIOUS(19分/5局)，STOMP(18分/7局)，UPPERCUT(17分/26局)
- 当前低价值卡牌：DRUM_OF_BATTLE(6分/2局)，EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)
- 策略进化：本局无参数调整
- 生涯战绩：0/78 胜，当前目标进阶 0

## 第 79 局复盘（2026-08-23 07:06）
- 结果：💀 失败｜进阶 0｜到达层数 23｜当局评分 23
- 死因：敌人组合 BOWLBUG_ROCK+BOWLBUG_SILK+SLUMBERING_BEETLE
- 本局拿牌：SHRUG_IT_OFF, UPPERCUT, RAMPAGE, CINDER, FLAME_BARRIER, FIEND_FIRE, TAUNT, MAYHEM, DRUM_OF_BATTLE, SHRUG_IT_OFF, BATTLE_TRANCE, BARRICADE, BREAKTHROUGH, UNRELENTING, THUNDERCLAP, UNMOVABLE, SHRUG_IT_OFF
- 本局遗物：PEAR, 闪亮口红
- 战斗记录：F19 Monster战 掉血3; F20 Monster战 掉血15; F21 Monster战 掉血40; F22 Monster战 掉血0; F22 Monster战 掉血8; F23 Monster战 掉血24（阵亡）
- 当前高价值卡牌：FIEND_FIRE(22分/2局)，MANGLE(21分/18局)，BARRICADE(20分/2局)，CONFLAGRATION(20分/2局)，IMPERVIOUS(19分/5局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(9分/8局)
- 策略进化：本局无参数调整
- 生涯战绩：0/79 胜，当前目标进阶 0

## 第 80 局复盘（2026-08-23 07:17）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：MANGLE, BREAKTHROUGH, CINDER, CONFLAGRATION, STOMP, SECOND_WIND, STOMP, SPITE, EVIL_EYE, ANGER, BLUDGEON
- 本局遗物：VAMBRACE
- 战斗记录：F9 Monster战 掉血31; F9 Monster战 掉血0; F12 Monster战 掉血10; F14 Monster战 掉血0; F15 Monster战 掉血14; F17 Boss战 掉血64（阵亡）
- 当前高价值卡牌：FIEND_FIRE(22分/2局)，MANGLE(21分/19局)，BARRICADE(20分/2局)，IMPERVIOUS(19分/5局)，CONFLAGRATION(19分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(9分/8局)
- 策略进化：本局无参数调整
- 生涯战绩：0/80 胜，当前目标进阶 0

## 第 81 局复盘（2026-08-23 07:23）
- 结果：💀 失败｜进阶 0｜到达层数 8｜当局评分 8
- 死因：敌人组合 NIBBIT
- 本局拿牌：DISMANTLE, EVIL_EYE, UNRELENTING, WHIRLWIND, CRUELTY, CINDER
- 本局遗物：无
- 战斗记录：F3 Monster战 掉血2; F4 Monster战 掉血0; F5 Monster战 掉血10; F6 Monster战 掉血19; F7 Monster战 掉血12; F8 Monster战 掉血32（阵亡）
- 当前高价值卡牌：FIEND_FIRE(22分/2局)，MANGLE(21分/19局)，BARRICADE(20分/2局)，IMPERVIOUS(19分/5局)，CONFLAGRATION(19分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，DEFEND_IRONCLAD(9分/8局)
- 策略进化：本局无参数调整
- 生涯战绩：0/81 胜，当前目标进阶 0

## 第 82 局复盘（2026-08-23 07:32）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：THUNDERCLAP, HOWL_FROM_BEYOND, HEMOKINESIS, DEFEND_IRONCLAD, DISMANTLE, TRUE_GRIT, BREAKTHROUGH, TRUE_GRIT, STONE_ARMOR
- 本局遗物：CANDELABRA
- 战斗记录：F6 Monster战 掉血19; F7 Monster战 掉血18; F9 Monster战 掉血46; F15 Monster战 掉血0; F17 Boss战 掉血45; F17 Boss战 掉血36（阵亡）
- 当前高价值卡牌：FIEND_FIRE(22分/2局)，MANGLE(21分/19局)，BARRICADE(20分/2局)，IMPERVIOUS(19分/5局)，CONFLAGRATION(19分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：本局无参数调整
- 生涯战绩：0/82 胜，当前目标进阶 0

## 第 83 局复盘（2026-08-23 07:56）
- 结果：💀 失败｜进阶 0｜到达层数 33｜当局评分 33
- 死因：敌人组合 KNOWLEDGE_DEMON
- 本局拿牌：IRON_WAVE, RAMPAGE, TAUNT, THUNDERCLAP, HEADBUTT, RAMPAGE, DEFEND_IRONCLAD, TRUE_GRIT, THUNDERCLAP, RAMPAGE, RAMPAGE, TAUNT, TAUNT, RAMPAGE, ANGER, FEEL_NO_PAIN, ARMAMENTS, RAMPAGE, FIEND_FIRE, RAMPAGE, SHRUG_IT_OFF, RAMPAGE, EVIL_EYE, TAUNT, UPPERCUT, TAUNT, TAUNT, RAMPAGE, CINDER, FIGHT_ME, TRUE_GRIT, WHIRLWIND, INFLAME, ARMAMENTS, HEMOKINESIS, DISINTEGRATION, SLOTH
- 本局遗物：PEAR, LASTING_CANDY, ANCHOR
- 战斗记录：F25 Monster战 掉血1; F25 Monster战 掉血11; F25 Monster战 掉血0; F33 Boss战 掉血0; F33 Boss战 掉血43; F33 Boss战 掉血51（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，RAMPAGE(20分/42局)，BARRICADE(20分/2局)，TAUNT(20分/26局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：本局无参数调整
- 生涯战绩：0/83 胜，当前目标进阶 0

## 第 84 局复盘（2026-08-23 08:04）
- 结果：💀 失败｜进阶 0｜到达层数 9｜当局评分 9
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：CINDER, THUNDERCLAP, IRON_WAVE, TAUNT, UNRELENTING, UPPERCUT, ARMAMENTS
- 本局遗物：无
- 战斗记录：F5 Monster战 掉血0; F6 Monster战 掉血18; F7 Monster战 掉血31; F9 Monster战 掉血0; F9 Monster战 掉血6; F9 Monster战 掉血46（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，RAMPAGE(20分/42局)，BARRICADE(20分/2局)，TAUNT(20分/27局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：本局无参数调整
- 生涯战绩：0/84 胜，当前目标进阶 0

## 第 85 局复盘（2026-08-23 08:14）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：THUNDERCLAP, CINDER, STOMP, TAUNT, SHRUG_IT_OFF, TWIN_STRIKE, HEMOKINESIS, TRUE_GRIT, ARMAMENTS, CRUELTY, DRUM_OF_BATTLE, INFLAME, THUNDERCLAP
- 本局遗物：BLOOD_VIAL
- 战斗记录：F15 Monster战 掉血5; F15 Monster战 掉血4; F15 Monster战 掉血12; F15 Monster战 掉血0; F17 Boss战 掉血26; F17 Boss战 掉血29（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，RAMPAGE(20分/42局)，BARRICADE(20分/2局)，TAUNT(19分/28局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：本局无参数调整
- 生涯战绩：0/85 胜，当前目标进阶 0

## 🧠 第 82~83 局复盘经验（2026-08-23 08:20）
- **死亡榜交叉图鉴验证**：comp_id 不含类型信息——KIN_FOLLOWER+KIN_PRIEST（12死）/CEREMONIAL_BEAST（10死）/VANTOM（8死）全是 Boss（190~252 血）。生涯 Boss 死亡占比超 1/3，"头号杀手组合"多数是 Boss 攻坚失败而非杂兵战失误。
- **Boss 战胜负手 = 战斗时长 × 意图增长**：82 局 95% 血进一幕 Boss 仍被 -45/-36 处决。入场血量线只是必要条件；新增 boss_atk_mult=1.15 全局攻击乘区缩短战斗。
- **演化必须双向可逆**：block_safety 被单向棘轮顶到 2.1 上限（83 局 0 胜只加不减），龟防对高血敌人=温水煮蛙。reflect 现按战斗时长分流：长战磨死（≥4回合）→ kill_bonus +1 且防御 −0.05；短暴毙 → 防御 +0.05（旧逻辑）。
- **选屏语义看上游动作**：83 局战斗中反复"选择暴走+"曾疑似献祭最优牌，实为头槌效果（弃牌堆置顶抽牌堆顶，选最强正确）；但旧代码把它记成 card_pick 灌水信用账本（单局暴走虚计 9 拿）——现以 card_top_pick 单列。
- 下批核对：①Boss 战日志出现「Boss攻坚提速×1.15」；②本局拿牌不再含头槌重复计数；③连续长战磨死时 kill_bonus 应爬升、block_safety 缓释。

## 第 86 局复盘（2026-08-23 08:25）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：CINDER, BREAKTHROUGH, TRUE_GRIT, EVIL_EYE, BREAKTHROUGH, UPPERCUT, TRUE_GRIT, RUPTURE, CINDER, HEMOKINESIS
- 本局遗物：NUNCHAKU
- 战斗记录：F6 Monster战 掉血26; F7 Monster战 掉血9; F9 Monster战 掉血13; F13 Monster战 掉血13; F15 Monster战 掉血11; F17 Boss战 掉血53（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，RAMPAGE(20分/42局)，BARRICADE(20分/2局)，TAUNT(19分/28局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：本局无参数调整
- 生涯战绩：0/86 胜，当前目标进阶 0

## 第 87 局复盘（2026-08-23 08:35）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：MOLTEN_FIST, SWORD_BOOMERANG, CRUELTY, CINDER, TAUNT, BREAKTHROUGH, RAMPAGE, CINDER, FIGHT_ME, SHRUG_IT_OFF, TAUNT
- 本局遗物：PENDULUM, 小血瓶
- 战斗记录：F7 Monster战 掉血5; F12 Monster战 掉血0; F14 Elite战 掉血48; F15 Monster战 掉血9; F15 Monster战 掉血0; F17 Boss战 掉血42（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，RAMPAGE(20分/43局)，BARRICADE(20分/2局)，TAUNT(19分/30局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus: 12.00 → 13.00（长战磨死（6回合），提升击杀奖励加快清场）；block_safety: 2.10 → 2.05（长战实证过度龟防会拖长战斗，小幅回调）
- 生涯战绩：0/87 胜，当前目标进阶 0

## ?? ? 84~85 ??????2026-08-23 08:40?
- **??????**?10 ?? 6 ????? Boss??? 52%~95% ????2 ??????????"??? Boss"?"??? Boss"?????????????????????????????????
- **??????**?boss_eve_smith_heal_mult ? rooms_act ? act ????????"??????????"????????????????/????? grep ???????????
- **??????**?FUZZY+SHRINKER ?????? 29.3%??????? 0.30????????????sev=0???? danger_comp_stance_death_rate=0.25 + ?????1/0.15???????????
- **??????????**?????????????? 4?31???? 18?26??????????????????????????????????????????
- **?????**??????????????????????????????? ?3 ??????? ?0.75?
- **?????**??0.05 ????? block_safety ?????? ~30 ????????????min(3,rounds/4)??Boss ?????? boss_atk_mult?
- ???????????????+N??????????3 ???????????Boss ??? boss_atk_mult>1.15 ???rooms_act ?????????FUZZY ??????????

## 第 88 局复盘（2026-08-23 08:43）
- 结果：💀 失败｜进阶 0｜到达层数 8｜当局评分 8
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：EVIL_EYE, SWORD_BOOMERANG, HEMOKINESIS
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血0; F3 Monster战 掉血0; F4 Monster战 掉血0; F6 Monster战 掉血28; F8 Monster战 掉血44; F8 Monster战 掉血20（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，RAMPAGE(20分/43局)，BARRICADE(20分/2局)，TAUNT(19分/30局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus: 13.00 → 14.00（长战磨死（12回合），提升击杀奖励加快清场）；block_safety: 2.05 → 2.00（长战实证过度龟防会拖长战斗，小幅回调）
- 生涯战绩：0/88 胜，当前目标进阶 0

## 第 89 局复盘（2026-08-23 08:53）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_PRIEST
- 本局拿牌：BLUDGEON, THUNDERCLAP, CINDER, HAND_OF_GREED, AGGRESSION, MOLTEN_FIST, FLAME_BARRIER, DISMANTLE
- 本局遗物：STONE_CRACKER, STRIKE_DUMMY
- 战斗记录：F14 Monster战 掉血8; F14 Monster战 掉血0; F15 Monster战 掉血16; F17 Boss战 掉血9; F17 Boss战 掉血52; F17 Boss战 掉血9（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，RAMPAGE(20分/43局)，BARRICADE(20分/2局)，TAUNT(19分/30局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus: 14.00 → 15.00（长战磨死（11回合），提升击杀奖励加快清场）；block_safety: 2.00 → 1.95（长战实证过度龟防会拖长战斗，小幅回调）
- 生涯战绩：0/89 胜，当前目标进阶 0

## 🧠 第 86~87 局复盘经验（2026-08-23 08:55）
- **入场血量-生还配对**：近 10 局入一幕 Boss，≥95% 血 1 胜 1 负、66%~79% 五连亡、52% 即死——boss_entry_min_hp_pct 0.65→0.72 重标定，并接入演化（Boss 长战磨死 +0.02，区间 0.50~0.90）。
- **灰区精英悲观复核**：87 局 86% 血进旧日雕像实测 -54（≈均值 3 倍重尾）。新增 _elite_grey_veto：均值×悲观系数(1.5) 投影战后 <60% 整条路径规避精英；硬线（≥90%）以上不变。均值回答「平均会怎样」，不可逆承诺必须回答「坏了会怎样」。
- **顶格旋钮代谢**：elite_min_hp_pct 顶在 0.9 后精英死亡信号空转——信号改接 elite_grey_safety_mult（精英死亡 +0.2／胜利 -0.1，区间 1.0~2.5）。给信号接旋钮前先确认旋钮还有行程。
- **归因沿血量时间线回溯**：87 局死因是 Boss，根因是灰区精英赌输——终局死因只是链条最后一环，修第一个非必要冒险才有杠杆。
- 下批核对：①地图日志出现「灰区精英预计战后…规避精英」且灰区精英拾取归零；②Boss 入场血量 ≥72% 成为常态；③精英再阵亡时 elite_grey_safety_mult 应爬升、胜利后回落。

## 第 90 局复盘（2026-08-23 09:11）
- 结果：💀 失败｜进阶 0｜到达层数 21｜当局评分 21
- 死因：敌人组合 BOWLBUG_ROCK+BOWLBUG_SILK+SLUMBERING_BEETLE
- 本局拿牌：THUNDERCLAP, THUNDERCLAP, DISMANTLE, SHRUG_IT_OFF, BREAKTHROUGH, TAUNT, FLAME_BARRIER, SHRUG_IT_OFF, BREAKTHROUGH, FIGHT_ME
- 本局遗物：PERMAFROST
- 战斗记录：F12 Unknown战 掉血13; F14 Monster战 掉血11; F17 Boss战 掉血41; F19 Monster战 掉血23; F20 Monster战 掉血6; F21 Monster战 掉血51（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，RAMPAGE(20分/43局)，BARRICADE(20分/2局)，TAUNT(19分/31局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus: 15.00 → 16.00（长战磨死（9回合），提升击杀奖励加快清场）；block_safety: 1.95 → 1.90（长战实证过度龟防会拖长战斗，小幅回调）
- 生涯战绩：0/90 胜，当前目标进阶 0

## 🧠 第 88~89 局复盘经验（2026-08-23 09:21）
- **药水门与姿态门同源**：姿态（死亡率≥0.25）判高危、药水门（0.30/战损0.30×血条）却放行，FUZZY+SHRINKER（29.3%/场均18.7）从缝隙漏网——88 局 F8 姿态 T1 就警告高危，攻击药水却锁到 20 血、意图已滚到 38。已接线：stance.danger 直通 premium。同一份证据必须驱动同一套结论。
- **入场血量轴饱和**：89 局 88% 血入一幕 Boss 仍亡，生涯 Boss 阵亡遍布 52%~99% 入场——血量线只滤必死局，不预测生还；分界维度是卡组输出吞吐量（0/89 胜，瓶颈在牌不在血）。
- **占比看不见绝对饥饿**：新增 deck_burst_floor=30（按伤害/能耗降序装满3能量的期望伤害，起步卡组≈18）；饥饿时高质攻击（总伤≥12 且 ≥7伤/能耗）拿牌+3，弱攻击不虚高。占比指标升级为吞吐量指标。
- **长战棘轮装上限阀**：kill_bonus 13→16、block_safety 2.05→1.90 单向漂移，0 胜生涯里每局长战死都在加码——参数制造不出伤害。演化前查边界行程，余量不足一步即停并留痕「顶格旋钮不再吸收证据」。
- **热进程覆盖冷修改**：运行中大脑 finalize 会用内存旧值整体回写 policy.json——86~87 批写入的 boss_entry=0.72 被冲掉成 0.65（已恢复）。复盘改 JSON 后若未重启且有局落盘，改动会静默丢失。
- 下批核对：①高危组合战斗前 3 回合内应见攻击/增益药水；②起步阶段选牌倾向 ≥12 伤攻击；③kill_bonus 再动应伴随「距上限仅余」留痕或停摆；④boss_entry 稳定 0.72 不回落；⑤若仍 0 胜，给 Boss 战接入斩杀回合数投影（攻速对账）。

## 第 91 局复盘（2026-08-23 09:24）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：MOLTEN_FIST, MOLTEN_FIST, SHRUG_IT_OFF, CINDER, THE_GAMBIT, DRUM_OF_BATTLE
- 本局遗物：VAMBRACE, 餐券
- 战斗记录：F15 Elite战 掉血0; F15 Elite战 掉血13; F15 Elite战 掉血0; F17 Boss战 掉血14; F17 Boss战 掉血28; F17 Boss战 掉血23（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，RAMPAGE(20分/43局)，BARRICADE(20分/2局)，TAUNT(19分/31局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus: 16.00 → 19.00（长战磨死（16回合），提升击杀奖励加快清场）；block_safety: 1.90 → 1.75（长战实证过度龟防会拖长战斗，小幅回调）；boss_atk_mult: 1.15 → 1.20（Boss 长战磨死（16回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.65 → 0.67（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/91 胜，当前目标进阶 0

## 第 92 局复盘（2026-08-23 09:36）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：BREAKTHROUGH, SHRUG_IT_OFF, FLAME_BARRIER, TAUNT, FLAME_BARRIER, RAMPAGE, SHRUG_IT_OFF, RAGE, THINKING_AHEAD, TRUE_GRIT
- 本局遗物：STONE_CRACKER, WHETSTONE, POTION_BELT, PERMAFROST
- 战斗记录：F7 Monster战 掉血18; F12 Monster战 掉血0; F15 Monster战 掉血0; F15 Monster战 掉血38; F17 Boss战 掉血7; F17 Boss战 掉血41（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，RAMPAGE(20分/44局)，BARRICADE(20分/2局)，TAUNT(19分/32局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus: 19.00 → 20.00（长战磨死（15回合），提升击杀奖励加快清场）；block_safety: 1.75 → 1.60（长战实证过度龟防会拖长战斗，小幅回调）；boss_atk_mult: 1.20 → 1.25（Boss 长战磨死（15回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.67 → 0.69（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/92 胜，当前目标进阶 0

## 第 93 局复盘（2026-08-23 09:41）
- 结果：💀 失败｜进阶 0｜到达层数 6｜当局评分 6
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：INFLAME, THUNDERCLAP, FEEL_NO_PAIN, RAMPAGE
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血0; F3 Monster战 掉血0; F4 Monster战 掉血0; F5 Monster战 掉血28; F6 Monster战 掉血52（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，BARRICADE(20分/2局)，RAMPAGE(20分/45局)，TAUNT(19分/32局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：block_safety: 1.60 → 1.51（长战实证过度龟防会拖长战斗，小幅回调）
- 生涯战绩：0/93 胜，当前目标进阶 0

## 🧠 第 90~91 局复盘经验（2026-08-23 09:49）
- **复盘会话活在回写枪口下**：本批复盘进行中实测复现热进程回写——kill_bonus 被冲到顶格 20、boss_entry 0.67→0.69、88~89 批注册的 deck_burst_floor 整键消失。冷修改必须假设落盘即可能被冲；已根治：knowledge.py 三方合并写盘（内存演化值优先、外部冷修改保留并实时采纳），验证需覆盖完整 finalize 周期。
- **逐回合贪心算不出必败局**：91 局 Boss 战 65 血入场、~25 伤/回合对 252 血仪式兽、意图 18→24 滚升，引擎用挑衅(挡6)/武装(挡5)买命 9 回合差 ~30 伤败北——每步局部合理，整体是开局注定的竞速。已接入斩杀竞速投影：实测输出速率 vs 意图火力的攻速对账，击杀回合数 > 可存活回合数+余量 → 奢侈格挡×0.70、攻击×1.25（与孤注/竞速互斥不叠加，头两回合不武装防误判）。
- **资源价值由能否改变结局决定**：格挡的功能是延寿，投影证明寿命买不够时延寿失去价值——奢侈格挡必须贬值，能量还给输出。
- **门槛要双向行程**：拿牌门槛有膨胀抬升无单薄折扣，91 局 16 张卡组整场只拿 6 张、越弱越不敢拿。新增 deck_thin_core=8/discount=0.35：非基础牌每缺 1 张门槛 -0.35。
- **留痕矛盾等于投毒**：91 局 F14「Elite=1.37|规避精英」同框——闸门否决但其余候选更差的正确取舍被日志说成自相矛盾。被否决仍当选时留痕改为「取损失最小项」。
- 上批观察点核对：①硬仗前 3 回合用药通过；②kill_bonus 机制未违反且已顶格 20；③boss_entry 0.72 再被冲（回写事故，已根治）；④斩杀回合数投影本批落地。本批新观察点：①长战 T4+ 出现「斩杀竞速投影」留痕且奢侈格挡消失；②单薄期不再整屏跳过奖励；③冷修改在完整 finalize 周期后存活；④kill_bonus 下次长战 Boss 阵亡应见「距上限仅余」留痕；⑤若一幕 Boss 仍 0 胜，把 burst_floor 与 Boss 血量档挂钩（252 血需 burst≥40）。

## 第 94 局复盘（2026-08-23 09:58）
- 结果：💀 失败｜进阶 0｜到达层数 24｜当局评分 24
- 死因：敌人组合 EXOSKELETON
- 本局拿牌：RAMPAGE, IMPERVIOUS, HEADBUTT, FLAME_BARRIER, EVIL_EYE, CONFLAGRATION, STOMP, SPITE, THUNDERCLAP, UNRELENTING, RUPTURE
- 本局遗物：HAPPY_FLOWER, 彩虹戒指
- 战斗记录：F23 Monster战 掉血21; F23 Monster战 掉血0; F23 Monster战 掉血0; F24 Monster战 掉血0; F24 Monster战 掉血14; F24 Monster战 掉血5（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，CONFLAGRATION(20分/4局)，BARRICADE(20分/2局)，RAMPAGE(20分/46局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：block_safety: 1.51 → 1.56（普通战斗阵亡，略微上调防御权重）
- 生涯战绩：0/94 胜，当前目标进阶 0

## 第 95 局复盘（2026-08-23 10:03）
- 结果：💀 失败｜进阶 0｜到达层数 6｜当局评分 6
- 死因：敌人组合 FUZZY_WURM_CRAWLER+SHRINKER_BEETLE
- 本局拿牌：CINDER, HEMOKINESIS, TAUNT, SHRUG_IT_OFF, AGGRESSION
- 本局遗物：无
- 战斗记录：F2 Monster战 掉血2; F3 Monster战 掉血0; F5 Monster战 掉血0; F6 Monster战 掉血60; F6 Monster战 掉血20（阵亡）
- 当前高价值卡牌：FIEND_FIRE(26分/3局)，MANGLE(21分/19局)，CONFLAGRATION(20分/4局)，BARRICADE(20分/2局)，RAMPAGE(20分/46局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长3.00)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.56 → 1.41（长战实证过度龟防会拖长战斗，小幅回调）
- 生涯战绩：0/95 胜，当前目标进阶 0

## 🧠 第 92~93 局复盘经验（2026-08-23 10:10）
- **时序澄清**：两局均运行于 90~91 批变更（09:52 提交）之前的旧代码，竞速投影尚未生效——死法属旧代码遗产；94 局（新代码首局）一幕 Boss 总战损仅 61，首次完整扛过一幕 Boss。
- **敌人分「数值型」与「时间型」**：93 局 FUZZY+SHRINKER（生涯头号杀手，14 死）杀伤来自意图滚雪球 4→7→24→…→31，引擎却按死亡率信号切入防守姿态（atk×0.85/blk×1.30）反向用药——格挡买断当轮买不断下一轮，7 回合磨死时全场最大格挡仅 13。已接入 `_esc_rounds` 持续升级计数：升级轨迹≥2 次即打开斩杀竞速投影账本、存活分母取当前意图（EMA 在单调爬升下严重滞后）、并解除高危姿态攻防压制、同步改写「转防守节奏」矛盾文案。
- **门槛按杀伤机制设而非体型设**：`kill_race_min_enemy_hp=80` 把"血池小"当"无需竞速"，恰好豁免了最需要竞速的滚雪球组合——开账问题应是"战斗是否随时间变贵"，不是"它够不够大"。
- **同一信号不同病因禁共用旋钮**：block_safety 三连降（1.90→1.51）源于把非 Boss 长战死亡也归因"龟防拖长"；实为有效格挡不足。现防御释放仅限 Boss 长战，非 Boss 长战阵亡改为上调防御；疲劳压制改随连战深度递增（×0.75 起每场 -0.06），治 93 局 0.37 分压过商店的近局翻车。
- 上批观察点①②③④因时序顺延未验证；⑤部分验证（94 局 Boss 通过）。本批新观察点：①升级型低血池战斗 T3~T5 出现竞速投影且无矛盾文案；②非 Boss 长战进化显示「上调防御权重」；③连战≥5 出现疲劳压制×0.63 级乘数；④block_safety 停止单向下行；⑤kill_bonus「距上限仅余」留痕持续核对。

## 第 96 局复盘（2026-08-23 10:19）
- 结果：💀 失败｜进阶 0｜到达层数 31｜当局评分 31
- 死因：敌人组合 INFESTED_PRISM
- 本局拿牌：THUNDERCLAP, FIGHT_ME, TRUE_GRIT, SHRUG_IT_OFF, TAUNT, HOWL_FROM_BEYOND, RAMPAGE, UNRELENTING, BATTLE_TRANCE, FISTICUFFS, FIEND_FIRE, FIGHT_ME, HEADBUTT, CINDER, CINDER, UPPERCUT, MAYHEM, FEEL_NO_PAIN, SWORD_BOOMERANG, COLOSSUS
- 本局遗物：草莓, VAMBRACE, 地精之角, BLOOD_VIAL, ODDLY_SMOOTH_STONE, LASTING_CANDY
- 战斗记录：F19 Monster战 掉血5; F21 Monster战 掉血19; F21 Monster战 掉血0; F23 Monster战 掉血37; F31 Elite战 掉血30; F31 Elite战 掉血38（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，COLOSSUS(24分/2局)，FISTICUFFS(24分/2局)，MANGLE(21分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：elite_grey_safety_mult: 1.50 → 1.70（精英战阵亡，灰区悲观投影系数上调）
- 生涯战绩：0/96 胜，当前目标进阶 0

## 🧠 第 94~95 局复盘经验（2026-08-23 10:26）
- **时序裁定**：两局均运行在上批（92~93）修复落盘前的代码上——95 局 FUZZY+SHRINKER 死亡是 93 局同因复现（min_enemy_hp=80 开账门对小血池滚雪球组合永不开启，满血进场仍单场 -60），属旧代码遗产；92~93 批修复自 96 局起进入实战验证期。
- **94 局里程碑与新缺陷**：新代码时代首次完整扛过一幕 Boss（100% 入场 10 回合斩杀墨影幻灵，竞速投影全程正确未误触发），但 61 血惨胜暴露「防守不必要」regime 无开关——87 血对意图 7 连打两张岿然不动+(40挡)，≥4 能量换 56 点零价值甲，多挨两轮升级意图。已落地溢出型大格挡贬值：有用部分 < 牌面一半且非 lethal/urgent → 按纯溢出计价跌破出牌阈值。
- **二幕力竭归因**：Boss 出场 26% 血 + 六连战斗节点无可达篝火，芯片磨死于场均仅 4.7 血的 EXOSKELETON——真凶是资源耗尽。F20 岔路商店以 0.53 分之差被 Monster 压过（持金 404）：商店权重现于血量警戒带内增值 1.6×（药水遗物 = 代偿休息）。
- **分类器教训**：能力药水因描述不含任何已知关键词，premium 门 T1 即开却睡到 20 血才被兜底掏出。已补「能力/power」；若再现第三种漏网应反转默认（premium 场合未知类别放行）而非继续补词。
- **参数面观察**：boss_entry 0.72 冷恢复再次按三方合并规则败给内存演化值 0.69——该旋钮已是演化资产，冷修改无效属预期行为非事故。
- 上批观察点核对：④距上限留痕通过；⑤burst_floor↔Boss 档挂钩触发条件解除（一幕 Boss 已胜）不实施；①②顺延至 96 局（修复未在窗口内生效）。
- 观察点（下批复盘核对）：①96 局起竞速投影留痕首验；②舒适局不再出现 2 费大挡、Boss 战损应显著低于 61；③警戒带内商店出现「代偿休整」留痕；④非 Boss 长战阵亡后 block_safety 上调首验；⑤能力类药水硬仗 T1~T3 兑现。

## 第 97 局复盘（2026-08-23 10:30）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：CINDER, ULTIMATE_STRIKE, TRUE_GRIT, COLOSSUS, ANGER, RUPTURE, CINDER, IRON_WAVE, THUNDERCLAP, CINDER, THUNDERCLAP, TRUE_GRIT, DISMANTLE, TRUE_GRIT, VICIOUS
- 本局遗物：精准剪刀, 诅咒珍珠, GAME_PIECE
- 战斗记录：F12 Monster战 掉血13; F14 Unknown战 掉血8; F15 Monster战 掉血14; F17 Boss战 掉血45; F17 Boss战 掉血0; F17 Boss战 掉血35（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，ULTIMATE_STRIKE(25分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(22分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长2.25)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.41 → 1.30（长战实证过度龟防会拖长战斗，小幅回调）；boss_atk_mult: 1.25 → 1.30（Boss 长战磨死（9回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.69 → 0.71（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/97 胜，当前目标进阶 0

## 第 98 局复盘（2026-08-23 10:36）
- 结果：💀 失败｜进阶 0｜到达层数 9｜当局评分 9
- 死因：敌人组合 EYE_WITH_TEETH+FOGMOG
- 本局拿牌：BURNING_PACT, BATTLE_TRANCE, DISMANTLE, SHRUG_IT_OFF, BREAKTHROUGH
- 本局遗物：橙型香盒, 奥术卷轴
- 战斗记录：F3 Monster战 掉血4; F4 Monster战 掉血1; F7 Unknown战 掉血24; F8 Monster战 掉血22; F9 Monster战 掉血7; F9 Monster战 掉血18（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，ULTIMATE_STRIKE(25分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(22分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，BURNING_PACT(8分/2局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.50)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.30 → 1.35（非 Boss 战斗长战阵亡（6回合），死因是有效格挡不足而非龟防——上调防御权重）
- 生涯战绩：0/98 胜，当前目标进阶 0

## 第 99 局复盘（2026-08-23 10:43）
- 结果：💀 失败｜进阶 0｜到达层数 14｜当局评分 14
- 死因：敌人组合 BYGONE_EFFIGY
- 本局拿牌：SHRUG_IT_OFF, TAUNT, HOWL_FROM_BEYOND, STOMP, RAMPAGE, RAMPAGE, HEMOKINESIS, FIGHT_ME, TAUNT, VICIOUS, STONE_ARMOR
- 本局遗物：REGAL_PILLOW
- 战斗记录：F5 Monster战 掉血5; F6 Unknown战 掉血4; F7 Monster战 掉血6; F9 Monster战 掉血21; F14 Elite战 掉血0; F14 Elite战 掉血49（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，ULTIMATE_STRIKE(25分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(22分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，BURNING_PACT(8分/2局)
- 策略进化：elite_grey_safety_mult: 1.70 → 1.90（精英战阵亡，灰区悲观投影系数上调）
- 生涯战绩：0/99 胜，当前目标进阶 0

## 第 100 局复盘（2026-08-23 10:52）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：TRUE_GRIT, RAMPAGE, CINDER, HOWL_FROM_BEYOND, RUPTURE, DISMANTLE, SECOND_WIND
- 本局遗物：ANCHOR
- 战斗记录：F6 Monster战 掉血22; F8 Monster战 掉血24; F12 Unknown战 掉血32; F14 Unknown战 掉血8; F17 Boss战 掉血36; F17 Boss战 掉血34（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，ULTIMATE_STRIKE(25分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(22分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，BURNING_PACT(8分/2局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.50)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.35 → 1.27（长战实证过度龟防会拖长战斗，小幅回调）；boss_atk_mult: 1.30 → 1.35（Boss 长战磨死（6回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.71 → 0.73（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/100 胜，当前目标进阶 0

## 第 101 局复盘（2026-08-23 11:02）
- 结果：💀 失败｜进阶 0｜到达层数 15｜当局评分 15
- 死因：敌人组合 NIBBIT
- 本局拿牌：MOLTEN_FIST, ARMAMENTS, RAMPAGE, HEADBUTT, TRUE_GRIT, SWORD_BOOMERANG, CINDER, THUNDERCLAP, TAUNT, IMPERVIOUS
- 本局遗物：NUNCHAKU
- 战斗记录：F13 Monster战 掉血15; F13 Monster战 掉血0; F14 Monster战 掉血13; F14 Monster战 掉血0; F15 Monster战 掉血11; F15 Monster战 掉血8（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，ULTIMATE_STRIKE(25分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(22分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，BURNING_PACT(8分/2局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.25)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.27 → 1.32（非 Boss 战斗长战阵亡（5回合），死因是有效格挡不足而非龟防——上调防御权重）
- 生涯战绩：0/101 胜，当前目标进阶 0

## 🧠 第 96 局复盘经验（2026-08-23 11:01）
- **时序与里程碑**：生涯最深局（F31）。一幕近乎完美（91% 血进 Boss、Boss 战损 61→46 持续改善、竞速投影/精英闸门/药水兜底全部按设计工作）；死因是二幕 F31 强制精英 INFESTED_PRISM（78% 血进场 -68），属「地图漏斗 + 资源耗尽」的结构性死亡而非决策事故。
- **分母决定语义（本批核心修复）**：rooms 的 damage_events 只统计真开战的房间，被当成到访数用后，E[伤|开战] 冒充了 E[伤|到访]——Unknown 148 访仅 33 战（22%），投影却按满额战斗×1.6 收费，二幕路径分全部饱和在 -165~-195、「进Boss血量 0%」而实际一路零伤事件走到 70% 血。已接入 room_combat_rate 折价：Unknown 先验 13→2.95，Monster/Elite 不受影响。
- **罚分要封顶**：死亡投影 + 血量线 + Boss 入场线三记同一坏结局，把候选全压进饱和区、序信息归零。现中途死亡只记一次账；「撑到 Boss 但低血」重新优于「半路暴毙」。
- **投影信息要用满**：F22 在 79% 血按常规线锻造，而全路径投影早已宣判死局——随后 F23 -37、F31 阵亡。地图端投影现在传递给篝火：绝境（<45%）时回血优先于锻造（边际回复≥8%血条才触发，防溢出浪费）。
- **商店与奖励端同门槛**：F30 固定阈值 1.0 买进净价值 3.0 的巨像（73金）；卡牌购买现须通过 max(动态拾取门槛, 商店基线)，膨胀卡组拒收注水牌。
- **分类器默认反转兑现**：第三批无法分类药水（缚魂/无色/固化）在 Boss 战睡到 38% 血；premium 硬仗前 3 回合未知类别直接放行，普通战仍保留。
- **proven_bad 边际收紧 4.0→3.0**：SETUP_STRIKE(9.4)/BULLY(10.0) 不再卡线外反复入组。
- 上批观察点：①竞速留痕✅ ②Boss战损46<61部分达标✅/无溢出大挡✅ ③④场景未遇顺延 ⑤增益药水T1兑现✅。
- 观察点（下批核对）：①二幕 Unknown 密集路线路径分回正、无 0% 饱和投影；②绝境篝火「优先回血」留痕且战损收敛；③膨胀卡组商店拒收留痕；④硬仗 T1~T3 未知药水兑现率上升；⑤SETUP_STRIKE/BULLY 从拿牌记录消失。

## 第 102 局复盘（2026-08-23 11:12）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：STRATAGEM, VICIOUS, VICIOUS, ARMAMENTS, ARMAMENTS, ARMAMENTS, ARMAMENTS, BREAKTHROUGH, UNRELENTING, HEADBUTT, UNRELENTING, CINDER, SHRUG_IT_OFF, CINDER, HOWL_FROM_BEYOND, THE_GAMBIT, THE_GAMBIT
- 本局遗物：LUCKY_FYSH
- 战斗记录：F15 Monster战 掉血4; F15 Monster战 掉血6; F15 Monster战 掉血6; F17 Boss战 掉血26; F17 Boss战 掉血0; F17 Boss战 掉血38（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，ULTIMATE_STRIKE(25分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(22分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，BURNING_PACT(8分/2局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.25)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.32 → 1.26（长战实证过度龟防会拖长战斗，小幅回调）；boss_atk_mult: 1.35 → 1.40（Boss 长战磨死（5回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.73 → 0.75（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/102 胜，当前目标进阶 0

## 第 103 局复盘（2026-08-23 11:19）
- 结果：💀 失败｜进阶 0｜到达层数 15｜当局评分 15
- 死因：敌人组合 FOGMOG
- 本局拿牌：ULTIMATE_STRIKE, CINDER, SPITE, HOWL_FROM_BEYOND, WHIRLWIND, SHRUG_IT_OFF, THE_GAMBIT
- 本局遗物：RAINBOW_RING
- 战斗记录：F5 Monster战 掉血8; F6 Monster战 掉血0; F9 Monster战 掉血13; F11 Monster战 掉血3; F12 Monster战 掉血0; F15 Monster战 掉血68（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(22分/3局)，ULTIMATE_STRIKE(22分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，BURNING_PACT(8分/2局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.00)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.26 → 1.31（非 Boss 战斗长战阵亡（4回合），死因是有效格挡不足而非龟防——上调防御权重）
- 生涯战绩：0/103 胜，当前目标进阶 0

## 第 104 局复盘（2026-08-23 11:29）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：SHRUG_IT_OFF, CINDER, FLAME_BARRIER, PILLAGE, CINDER, STOMP, MOLTEN_FIST, STOMP, TAUNT, ARMAMENTS, PACTS_END, FEEL_NO_PAIN, RAMPAGE
- 本局遗物：STURDY_CLAMP
- 战斗记录：F9 Monster战 掉血19; F12 Unknown战 掉血6; F12 Unknown战 掉血0; F14 Monster战 掉血8; F15 Monster战 掉血5; F17 Boss战 掉血74（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(22分/3局)，ULTIMATE_STRIKE(22分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，BURNING_PACT(8分/2局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.50)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.31 → 1.24（长战实证过度龟防会拖长战斗，小幅回调）；boss_atk_mult: 1.40 → 1.45（Boss 长战磨死（6回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.75 → 0.77（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/104 胜，当前目标进阶 0

## 第 105 局复盘（2026-08-23 11:40）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：CINDER, HEADBUTT, ARMAMENTS, THUNDERCLAP, CINDER, SHRUG_IT_OFF, SWORD_BOOMERANG, TAUNT, ARMAMENTS, FLAME_BARRIER
- 本局遗物：GORGET
- 战斗记录：F14 Monster战 掉血7; F14 Monster战 掉血0; F15 Monster战 掉血4; F17 Boss战 掉血58; F17 Boss战 掉血0; F17 Boss战 掉血10（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(22分/3局)，ULTIMATE_STRIKE(22分/3局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，BURNING_PACT(8分/2局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.50)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.24 → 1.16（长战实证过度龟防会拖长战斗，小幅回调）；boss_atk_mult: 1.45 → 1.50（Boss 长战磨死（6回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.77 → 0.79（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/105 胜，当前目标进阶 0

## 第 106 局复盘（2026-08-23 11:53）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 KIN_FOLLOWER+KIN_PRIEST
- 本局拿牌：THUNDERCLAP, TRUE_GRIT, SHRUG_IT_OFF, TRUE_GRIT, FEEL_NO_PAIN, RAMPAGE, UPPERCUT, HEADBUTT, RAMPAGE, SHRUG_IT_OFF, ANGER, SWORD_BOOMERANG, BREAKTHROUGH, ULTIMATE_STRIKE, RAMPAGE, COLOSSUS
- 本局遗物：GORGET
- 战斗记录：F14 Unknown战 掉血8; F14 Unknown战 掉血0; F15 Monster战 掉血42; F15 Monster战 掉血0; F17 Boss战 掉血24; F17 Boss战 掉血36（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，MANGLE(21分/19局)，COLOSSUS(20分/4局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，BURNING_PACT(8分/2局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.75)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.16 → 1.07（长战实证过度龟防会拖长战斗，小幅回调）；boss_atk_mult: 1.50 → 1.55（Boss 长战磨死（7回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.79 → 0.81（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/106 胜，当前目标进阶 0

## 第 107 局复盘（2026-08-23 12:05）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：TRUE_GRIT, SPITE, FLAME_BARRIER, TAUNT, MOLTEN_FIST, RUPTURE, FIGHT_ME, CINDER, MOLTEN_FIST
- 本局遗物：RED_MASK
- 战斗记录：F12 Monster战 掉血0; F14 Monster战 掉血0; F14 Monster战 掉血15; F14 Monster战 掉血0; F17 Boss战 掉血0; F17 Boss战 掉血52（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，MANGLE(21分/19局)，COLOSSUS(20分/4局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，BURNING_PACT(8分/2局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.50)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.07 → 1.00（长战实证过度龟防会拖长战斗，小幅回调）；boss_atk_mult: 1.55 → 1.60（Boss 长战磨死（6回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.81 → 0.83（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/107 胜，当前目标进阶 0

## 第 108 局复盘（2026-08-23 12:20）
- 结果：💀 失败｜进阶 0｜到达层数 23｜当局评分 23
- 死因：敌人组合 BOWLBUG_ROCK+BOWLBUG_SILK+SLUMBERING_BEETLE
- 本局拿牌：ULTIMATE_DEFEND, CINDER, THUNDERCLAP, UNRELENTING, COLOSSUS, HOWL_FROM_BEYOND, SHRUG_IT_OFF, TAUNT, TAUNT, JUGGERNAUT, THRASH, TRUE_GRIT, BREAKTHROUGH, SWORD_BOOMERANG, THUNDERCLAP, WHIRLWIND, BURNING_PACT
- 本局遗物：BELLOWS
- 战斗记录：F19 Monster战 掉血5; F20 Monster战 掉血17; F21 Monster战 掉血32; F23 Monster战 掉血0; F23 Monster战 掉血0; F23 Monster战 掉血26（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(21分/5局)，MANGLE(21分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.00)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.00 → 1.05（非 Boss 战斗长战阵亡（4回合），死因是有效格挡不足而非龟防——上调防御权重）
- 生涯战绩：0/108 胜，当前目标进阶 0

## 🧠 第 106 局复盘沉淀（2026-08-23 12:23）
- **死因定性**：F17 一幕 Boss 同族双子（生涯 38战18死/47%，近 10 局 6 死于它）——多局 ≥95% 血进场仍败，入场血量不是瓶颈，卡组输出速率才是（本局实测 ~10-15 伤/回合，斩杀竞速投影报「击杀需 30~75 回合 vs 可存活 3~4 回合」）。
- **结构性修复①**：card_value 以「拿到该牌的局到达层数」为收益是幸存者偏差噪声（能被拾取的前提就是活到奖励屏），RAMPAGE 靠 +6 摆动在 55 局里自我强化循环拾取——拾取端贡献封顶 ±3（card_value_pick_cap），保方向砍幅度。
- **结构性修复②**：输出饥饿对高质攻击的加分从固定 +3 改为随缺口深度放大（base 3 + max extra 4×deficit）；锻造在爆发饥饿时攻击优先加码翻倍。
- **结构性修复③**：事件触发的战斗延迟结算——「茂密的植被-战！」把感染×3 打进牌堆但 deck_delta 恒记 0，事件端把污染当免费。现在 hp/金币按离开事件屏瞬间快照记账（自身效果），战斗后用 live 卡组补记增量；战斗死亡仍归因敌人组合不归事件。
- **经验教训**：①凡以事后结果给事前选项打分的学习器，必须检查结果分布是否被选择机制扭曲；②纠偏信号强度必须与要对抗的噪声同量级；③统计要跟着因果走不要跟着屏幕走（代价可能在后续战斗才兑现）；④死亡归因链与记账便利性必须分开设计。
- 观察点：RAMPAGE 候选分回落至门槛附近、饥饿加深留痕出现、DENSE_VEGETATION 战！负 card_delta 入账。

## 🧠 第 107~108 局复盘沉淀（2026-08-23 12:55）
- **两局定性**：107 局是「中盘崩盘→带残血进必死数学」的标准败局（65% 进场 < 要求线 83%，输出速率不足未改善，kill_bonus 顶格后参数已无吸收空间）；108 局是里程碑局——首次稳定过一幕 Boss 进二幕（23 局，生涯第二高），死于二幕漏斗地形对生涯死亡率 60% 的 BOWLBUG 三件套强制三连战力竭。攻防均衡的拿牌结构（AoE/攻击牌充足）与走得更远正相关，106 局拾取端修复方向获得正反馈。
- **结构性修复①**：投影罚分软饱和（path_penalty_saturation=70）——死亡/血量线/Boss入场/中段精英四类罚分累计后统一经 sat·tanh(raw/sat) 压扁再扣分。108 局二幕开局全线 -159~-193、「预计进Boss血量 0%」，房间权重/休整加成等正信号在罚分竞赛中彻底失声；tanh 单调保序、小额近似线性（3y 门槛翻转语义不变）、大额渐进饱和恢复分辨力。
- **结构性修复②**：中段精英罚分随深度衰减（elite_mid_gate_depth_decay=0.85）——逐节点选路下 depth 越深的精英越不是承诺（岔口可改道），且篝火回血会抬高后续真实闸门通过率。107 局 29% 血时唯一篝火因子树深处藏精英被罚到 -84 输给 Monster(-0.94)，放弃救命休息后 F11 打到 12% 血险些暴毙——「渴死的人不喝因为井边有狼」。
- **结构性修复③**：block_safety 振荡源切除——Boss 长战降防分支（82~83 批引入）整体移除，Boss 长战证据全走攻坚双轴（boss_atk_mult/boss_entry_min_hp_pct）。此前 107 局 Boss 磨死降防（1.07→1.00）、108 局普通长战死升防（1.00→1.05），两种真实信号让普通战防御权重永远定不准；一个参数不能服侍两个主人。
- **经验教训**：①「去重」治不了「集体触底」——多候选同时吃满大额罚分时候选差异只剩投影噪声，罚分必须像收益一样有界有梯度；②承诺强度与投影距离成反比，远期可改道的风险不得全额记账去否决当下必需的资源；③共享旋钮上的旧语义分支在专属旋钮上线后必须退役，否则专属化本身就是振荡放大器；④里程碑局（首次过 Boss）的正面样本同样宝贵：它验证了「AoE 稀缺定价+饥饿深度加成+封顶学习分」的拾取端组合拳有效。
- 观察点：①二幕开局路径分回到 ±40 量级、「预计进Boss血量 0%」注水减少；②低血量子树藏精英时篝火与替代候选的分差收窄到个位数；③block_safety 不再 Boss死↓/普通死↑ 交替漂移；④boss_atk_mult 继续向 1.8 上限爬坡而 kill_bonus 维持顶格留痕。

## 第 109 局复盘（2026-08-23 13:47）
- 结果：💀 失败｜进阶 0｜到达层数 9｜当局评分 9
- 死因：敌人组合 INKLET
- 本局拿牌：无
- 本局遗物：无
- 战斗记录：F9 Unknown战 掉血44（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(21分/5局)，MANGLE(21分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长3.00)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.05 → 1.10（非 Boss 战斗长战阵亡（612回合），死因是有效格挡不足而非龟防——上调防御权重）
- 生涯战绩：0/109 胜，当前目标进阶 0

## 第 110 局复盘（2026-08-23 13:56）
- 结果：💀 失败｜进阶 0｜到达层数 21｜当局评分 21
- 死因：敌人组合 BOWLBUG_ROCK+BOWLBUG_SILK+SLUMBERING_BEETLE
- 本局拿牌：THUNDERCLAP, CINDER, SHRUG_IT_OFF, BREAKTHROUGH, UPPERCUT, SHRUG_IT_OFF, CINDER, ANGER, FLAME_BARRIER, FEEL_NO_PAIN, CONFLAGRATION, FASTEN, CINDER, BREAKTHROUGH
- 本局遗物：VAJRA
- 战斗记录：F14 Monster战 掉血0; F15 Monster战 掉血6; F17 Boss战 掉血29; F19 Monster战 掉血18; F20 Monster战 掉血35; F21 Monster战 掉血27（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，COLOSSUS(21分/5局)，MANGLE(21分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.75)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.10 → 1.15（非 Boss 战斗长战阵亡（7回合），死因是有效格挡不足而非龟防——上调防御权重）
- 生涯战绩：0/110 胜，当前目标进阶 0

## 第 111 局复盘（2026-08-23 14:02）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 VANTOM
- 本局拿牌：TAUNT, BREAKTHROUGH, DISMANTLE, COLOSSUS, SALVO, BLUDGEON, BARRICADE, STOMP, TAUNT, STONE_ARMOR
- 本局遗物：金色珍珠, 寻龙尺, SHOVEL
- 战斗记录：F2 Monster战 掉血0; F4 Monster战 掉血6; F7 Monster战 掉血3; F12 Unknown战 掉血17; F15 Monster战 掉血3; F17 Boss战 掉血80（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，MANGLE(21分/19局)，ULTIMATE_STRIKE(20分/4局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长2.50)，长战信号停止加码——顶格旋钮不再吸收证据；boss_atk_mult: 1.60 → 1.65（Boss 长战磨死（10回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.83 → 0.85（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/111 胜，当前目标进阶 0

## 第 112 局复盘（2026-08-23 14:08）
- 结果：💀 失败｜进阶 0｜到达层数 17｜当局评分 17
- 死因：敌人组合 CEREMONIAL_BEAST
- 本局拿牌：BLUDGEON, FEEL_NO_PAIN, TAUNT, SHRUG_IT_OFF, THUNDERCLAP, HEADBUTT, BLUDGEON, STOMP, TRUE_GRIT, RUPTURE, TRUE_GRIT
- 本局遗物：ANCHOR
- 战斗记录：F5 Monster战 掉血0; F6 Monster战 掉血23; F7 Monster战 掉血6; F8 Monster战 掉血28; F12 Monster战 掉血2; F17 Boss战 掉血69（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，MANGLE(21分/19局)，ULTIMATE_STRIKE(20分/4局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长2.00)，长战信号停止加码——顶格旋钮不再吸收证据；boss_atk_mult: 1.65 → 1.70（Boss 长战磨死（8回合），攻坚乘区提速）；boss_entry_min_hp_pct: 0.85 → 0.87（Boss 长战磨死，入场血量要求线上调）
- 生涯战绩：0/112 胜，当前目标进阶 0

## 第 113 局复盘（2026-08-23 14:16）
- 结果：💀 失败｜进阶 0｜到达层数 23｜当局评分 23
- 死因：敌人组合 THE_OBSCURA
- 本局拿牌：TAUNT, CINDER, CINDER, BREAKTHROUGH, BLUDGEON, THRASH, PILLAGE, IRON_WAVE, BREAKTHROUGH
- 本局遗物：开心小花, MOLTEN_EGG
- 战斗记录：F13 Monster战 掉血14; F15 Unknown战 掉血0; F17 Boss战 掉血30; F19 Monster战 掉血32; F20 Monster战 掉血20; F23 Monster战 掉血28（阵亡）
- 当前高价值卡牌：FIEND_FIRE(27分/4局)，MAYHEM(27分/2局)，FISTICUFFS(24分/2局)，THRASH(23分/2局)，MANGLE(21分/19局)
- 当前低价值卡牌：EXPECT_A_FIGHT(7分/5局)，BASH(7分/6局)，SETUP_STRIKE(9分/5局)
- 策略进化：kill_bonus 20.00 距上限仅余 0.00(<步长1.50)，长战信号停止加码——顶格旋钮不再吸收证据；block_safety: 1.15 → 1.20（非 Boss 战斗长战阵亡（6回合），死因是有效格挡不足而非龟防——上调防御权重）
- 生涯战绩：0/113 胜，当前目标进阶 0
