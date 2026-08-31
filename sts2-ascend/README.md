# sts2-ascend — 杀戮尖塔2 自主学习智能体

基于 [CharTyr/STS2-Agent](https://github.com/CharTyr/STS2-Agent)（游戏内 HTTP API mod，AGPL-3.0）构建的
**会自动玩、会思考、会进化的杀戮尖塔2智能体**。

- 分角色游玩白绮（Vivhite）与战士（Ironclad）：首次追平前按 VVVVI 推进；白绮追平后下一局为 Ironclad，此后永久 1:1
- 每个决策都产出中文局势分析与理由（见 `knowledge/brain.log`）
- **每局结束后自动复盘**：把结果归因到卡牌/遗物/敌人/事件选项，突变策略参数，写进 `knowledge/lessons.md`
- 以通关为目标，胜利后自动提升进阶（Ascension）继续挑战更高难度

## 架构

```
┌─────────────────────────────┐        HTTP 127.0.0.1:8080         ┌──────────────────────────────┐
│  Slay the Spire 2 (游戏进程) │  /state /actions/available /action │  brain/ (Python 3, 纯标准库)   │
│  └ STS2AIAgent mod (上游)   │ ◄────────────────────────────────► │  ├ client.py    API 客户端     │
│    暴露游戏状态 + 动作接口   │   GET /data/{cards,relics,...}     │  ├ policy.py    逐屏决策引擎   │
└─────────────────────────────┘                                    │  ├ knowledge.py 持久化知识库   │
                                                                   │  ├ reflect.py   赛后复盘/进化 │
                                                                   │  └ agent.py     主循环/看门狗 │
└─────────────────────────────┘        knowledge/ = 智能体的长期记忆（跨对局持续进化）
                                        ├ stats.json       卡牌/遗物/敌人/事件 表现统计（增量均值+收缩估计）
                                        ├ policy.json      可调策略权重（每局按死因/胜负自动突变）
                                        ├ progression.json 进阶天梯（胜利即 +1）
                                        ├ lessons.md       每局中文复盘总结（自我反思）
                                        └ runs/*.json      每局完整决策日志
```

大脑**不依赖任何第三方包**（纯 Python 标准库），也**不修改上游 mod**——只是它的 HTTP 客户端。
MCP server（上游附带）对本项目不是必需的。

## 双角色 Profile 与追赶轮换

双角色共用同一套 `Policy` 决策算法；`Agent` 为每个角色创建相互独立的 `Knowledge` / `Policy`
运行实例，角色差异通过 `CharacterProfile`、角色目录和参数实例表达：

| `profile_id` | 实际 `character_id` | 学习数据根目录 |
| --- | --- | --- |
| `ironclad` | `IRONCLAD` | 历史 `knowledge/` 根目录，原位保留且不迁移 |
| `vivhite` | `VIVHITE_CHARACTER_VIVHITE_CHARACTER` | `knowledge/profiles/vivhite/` |

没有角色字段的历史日志继续归为 Ironclad。新运行日志写入 `profile_id`、API 返回的
`character_id` 和角色内递增的 `profile_run_number`；两套 `stats.json`、`policy.json`、
`progression.json`、`lessons.md` 与 `runs/` 不交叉读写。

楼层统计也以 Profile 为硬边界，不能把两人的样本合并后再按标签显示。Ironclad 的生涯平均/最高
优先来自历史根目录自己的 `floor_sum_raw / runs` 与 `best_floor_raw`；Vivhite 只读取
`knowledge/profiles/vivhite/` 下对应字段，聚合不可用时也只回退到同一 Profile 的有效完结局。两人的
“近 20 局平均”和“近 20 局最高”分别从各自最近 20 个有效完结局计算，某一方样本不足时只显示
该方现有样本或 `N/A`，绝不从另一方回填。旧库缺少
raw-floor 字段时的胜利加分反推兼容只属于 Ironclad 历史；没有角色字段的根目录逐局日志同样只归
Ironclad。进行中局、人工接管局和零决策幻影局都不进入这些生涯或近 20 局指标。

`CharacterRotation` 的持久状态位于 `knowledge/character_rotation.json`。没有活动对局和轮换历史时，
目标固定为 Vivhite；仅在首次追平前，且 Vivhite 在各自 `stats.global.runs` 中已成功保存的总局数少于 Ironclad 时，
目标角色按 Vivhite → Vivhite → Vivhite → Vivhite → Ironclad（VVVVI）追赶序列推进。每局终局
成功保存后都会重新比较双方总局数；任一白绮局使双方追平，就立即退出追赶模式，下一局明确选择 Ironclad，
随后永久按 Ironclad → Vivhite → Ironclad 的 1:1 严格交替；即使白绮短暂落后一局也不重返 4:1，且不补齐当前五局序列。活动对局始终以 API
的实际 `run.character_id` 绑定 Profile，只有终局日志与角色统计成功保存后才推进配额；重复终局按
`run_id` 幂等去重。目标角色缺失、锁定或载荷不完整时停在选角界面并记录原因，不回退到其他角色。

Vivhite 的 `CharacterProfile` 绑定独立的 61 卡静态目录和评分参数。余裕先按 `1:1` 抵扣謦欬；
抵扣后真正损失的生命每点计 `-1.25`，当前生命严格低于最大生命 35% 时该风险权重变为两倍，支付后
会低于 1 点生命的牌判定为不可打出。实际获得余裕每点计 `+1.25`，消耗余裕按同一资源价值扣回；
余裕数量及收益不做自定义封顶。

61 卡目录直接保存现行最终整数：固定牌面謦欬已翻倍，猩红转化仪式的 `0,1,2,3...` 阶段謦欬是
不翻倍的明确特例；同时带謦欬和抽牌的牌，其抽牌数已经翻倍，若有弃牌则弃牌数同步翻倍。运行时
汲取只使用牌面、全局与本回合效果相加后的最终总率，不重放“旧值调整”或“翻倍”等配置演进；
多段与群攻先汇总整张攻击造成的实际敌方生命损失，再按最终总率计算并只向上取整一次。评分只对
实际回复生命按每点 `+0.85` 计收益，不按牌面
理论回复伪造满血收益；汲取率可超过 100%，也不对比例或回复量做自定义裁剪。永久最大生命每点
`+3.0`，击杀实际回血每点 `+1.0`；孤高冠冕按最大生命 20% 向上取整，归纳法阵按 50%/75%
放大即时死亡回复。战士继续使用自己的参数实例，不消费白绮目录或这些白绮专属估值。

## 原生终局分数与解锁落盘

Brain 不再在 `GAME_OVER` 直接调用返回主菜单。Agent HTTP API 暴露动作 `continue_game_over`，
Brain 通过通用动作端点调用它；MCP 的 full profile 额外暴露同名独立工具，guided/layered profile
则通过通用 `act` 提交该动作。三条入口推进的是同一原生流程，协议分为：

1. `game_over.phase=intro` 时只允许 `continue_game_over`，真实点击原生 Continue。
2. `summary_animating` 期间等待游戏执行分数条、角色解锁计算与原生结算协程。
3. 只有原生 MainMenuButton 真实可见且可用时进入 `summary_ready`；此时 Brain 才幂等持久化本局
   统计与轮换记录，下一次轮询再执行 `return_to_main_menu`。

`summary_ready + MainMenuButton 可用` 是这里采用的原生 UI 生命周期落盘屏障；Brain 不读取或比对
游戏存档文件来额外宣称落盘验证成功。

`continue_game_over` 真实点击 `NGameOverContinueButton`；返回动作也只真实点击
`NReturnToMainMenuButton`，禁止直接调用会绕过总结协程的 `ReturnToMainMenu` 私有路径。其后出现的每个
`UNLOCK` 屏只通过 `confirm_unlock` 顺序确认；按钮未就绪时等待，不盲点屏幕、不提前开始下一局。
HTTP 回执丢失或重连依赖真实按钮和 phase 恢复，既不会重复 Continue，也不会重复写终局统计。

分角色楼层统计只使用 `floor_sum_raw` / `best_floor_raw`；驾驶舱 UI 显示当前活动角色的一套四指标，并显示同窗口
Vivhite÷Ironclad 滚动平均楼层比。LLM 复盘的目标契约是队列项携带 `profile_id`、单批只含一个
Profile，且 prompt、runs、stats、lessons、policy、报告和队列均按角色隔离；该链路仍处于最终
集成验证阶段，在相关提交与回归完成前不得视为已生产验证。

平衡结论尚未产生：必须重新采集 Vivhite 与 Ironclad 各至少 20 局，以真实楼层同窗口计算比值；
目标仍为 `1.35～1.65`（中心 `1.50`）。当前没有足够的 `20+20` 真机样本，因此不声称已经达标。

## 快速开始

```powershell
# 在仓库根目录：按 Source 部署 → Vulkan 启动游戏 → 后台启动 runner/brain
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-Agent.ps1

# 完整停止 brain/runner、播报/复盘链和游戏
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1

# 只停智能体与播报链，保留游戏
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1 -KeepGame
```

要求：

- 杀戮尖塔2 v0.111.0（`scripts\Deploy-Mod.ps1 -GameDir` 可改路径）
- `py -3`（Python 3.11+；本机 3.14 验证通过）
- 游戏根目录有 `launch_vulkan.bat`；冷启动由脚本自动调用

启动默认在后台运行，不占住当前终端。常用参数：

- `-SkipDeploy`：复用当前已部署 DLL；附着到已经运行的游戏时必须使用
- `-Source auto|fork|release`：默认 `auto`，本地 fork clone 存在时优先构建 fork，否则用官方 release
- `-GameDir <目录>`：自定义游戏安装目录；fork 构建可另传 `-GodotExe`
- `-Foreground`：只用于 runner 调试；此时 `Ctrl+C` 会协作停止 Python 栈，但不会代替完整 Stop 关闭游戏
- `-ReadyTimeoutSeconds 120`：等待 brain + API 就绪；超时只警告，后台 runner 仍继续自愈

停止脚本默认给 Python 组件 40 秒保存/退出，再做身份校验后的精确兜底；游戏先关窗，20 秒后才强停。可用 `-WhatIf` 预览目标。不要直接结束某个 Python——runner 会重拉 brain，也会遗留播报/复盘子进程。

`Stack ready` 表示 brain 与游戏 API 已就绪。ASCEND-VISION 驾驶舱随 brain 启动并由监督器持续检查心跳、异常退出后自动重拉；碎碎念在语音环境可用时启动，复盘 OpenCode 与复盘 speaker 仍只在有任务时按需出现。

全栈运行时可随时把游戏交还给玩家：`Ctrl+Alt+F9` 全局停止 Brain 发送操作，
`Ctrl+Alt+F10` 恢复自主操作。暂停采用 runner 驻留的控制权切换，游戏与驾驶舱不会关闭。
F9 一旦触及当前局，该局便永久标记为 `human_assisted` / `excluded_from_learning`；
所属 Profile 的在线 `stats` 立即回滚到该局开始前已经持久化的基线。
F10 在同一局只恢复 Brain 发送操作，不会重新开启本局学习；排除标记与回滚事务会持久化，Brain 或整套重启后仍保持。
整局日志继续以 `in_progress=true` 的审计记录保留，不伪装为自动完结局。
该局不增加自动总局数，不更新生涯或近 20 局楼层指标，也不进入终局
`stats`、`policy`、`progression`、`lessons`、LLM 复盘或角色轮换配额。
若完整栈已经退出，快捷键监听也不存在，仍需用 `Start-Agent.ps1` 冷启动。

## 它如何"进化"

1. **在线统计**：每场战斗结束记录敌方组合与掉血量（敌人危险度模型）；每个事件选项结算
   生命/金币变化；每次成功拿牌/拿遗物打上归因标签。动作必须收到最终成功回执，或由后续
   同局状态满足动作特定后置条件后才入账；`pending`/断线本身不算成功。
2. **赛后归因**：一局结束时按"到达层数+胜利率"给本局所有选择记账（incremental mean +
   shrinkage 收缩估计，样本少时不过拟合）。
3. **策略突变**（有界）：被精英打死→提高精英回避血量线；被小怪打死→上调防御权重；
   事件致死→收敛探索率；胜利→放宽进攻性并提升目标进阶。全部钳制在安全区间内。
4. **自我总结**：以上全部变化以中文写入 `lessons.md`，形成可读的"成长日记"。

卡牌奖励的可靠曝光口径是 v2 `offered`：只统计真实 offer，同屏轮询和重复 ID 去重；旧
`seen` 保留兼容但不再当曝光率。零/低样本新牌在安全近优集合中使用有界 UCB 探索，战斗中
对当前可出且即时边际为正的新牌提供每场一次受控试用，不会因“从没试过”永久自锁。

事件、遗物和药水也使用确定性、限额的受控探索：事件只在高血、近优且通过致死/历史重尾
闸门时轮转欠采样选项；宝箱与商店只在近优、无明确负面的遗物间打破固定首槽偏置；商店
未知药只在有空位、健康、低价且保留金币时试购。所有配额均以最终成功回执或动作特定状态
效果确认为准，`pending`、失败或断线请求不伪造样本。`UNKNOWN` 屏不盲探任意动作，仍只使用
已声明的确认/继续和延迟界面兜底。

## 知识库压缩（compact）

`runs/*.json` 是逐决策原始证据，局数增长后不应让全部历史永远占据活跃工作集。
压缩工具默认只做只读预览：

```powershell
# 可在运行中执行：只统计，不写 knowledge
py -3 sts2-ascend/brain/compact_knowledge.py

# 必须先用 Stop-Agent.ps1 停止整套，再显式 apply
py -3 sts2-ascend/brain/compact_knowledge.py --apply
```

默认保留最近 96 份原始日志、所有胜局/进行中局、F33+ 深层局，以及最长轨迹、
最大文件、各终局层数和各进阶的代表样本。其他日志不会丢弃：工具先用
`ZIP_DEFLATED` 写入 `knowledge/archive/batch-*.zip`，逐文件重读校验 SHA256，
再原子发布 `knowledge/archive/manifest.json`，最后才移走 active 副本。
`knowledge/archive/run_catalog.jsonl` 保留所有 active/archived 对局的可检索摘要；需要深读
某一份归档原文时可运行 `py -3 sts2-ascend/brain/compact_knowledge.py --show-run <文件名>`，
工具会先按 manifest 校验 SHA256 再输出。二次执行在没有新历史时
是严格 no-op；损坏 JSON 会作为异常证据留在 active 目录。

`lessons.md` 保留全部 `🧠` 长期经验与最近 96 节，`meta_review.md` 保留最近 32 节；
被裁出的原文同批完整备份。`stats.json`、`policy.json`、`progression.json` 不裁剪，
并随归档保存只读快照，因此在线学习所需的充分统计不受影响。runtime `*.log` 只在
dry-run 报告体积，不写入二进制知识归档。

compact 只减少当前 checkout、文件扫描和后续提示词成本；普通提交无法缩小 Git 历史中
已经存在的对象。若将来确需重写历史，必须作为单独的破坏性维护操作评估和执行。

## 原生游戏知识快照

`knowledge/game/v0.111.0/` 保存与游戏版本绑定的只读事实层：runtime ModelDb、英中本地化、
PCK 目录、`sts2.dll` 结构化 mechanics 和跨层 ID join。当前基础集合是 596 卡、299 遗物、
107 怪物、66 药水，另含事件、Power、遭遇、池、地图、商店、奖励、篝火、升阶、怪物招式
状态机以及战斗命令/行动、伤害与格挡属性、随机数、卡费和 run 流程等规则。manifest 记录游戏
commit、程序集/PCK SHA256 和每个 artifact hash；validation 报告绑定 manifest 与实际 artifact set，
报告过期、快照被改写或验证失败时都不会静默加载。

mechanics v4 还用规范化的嵌套语句树保留 if/else 与 switch case 到具体效果的映射；在线摘要
只在分支相关时输出该字段，并设置节点、深度、同级数量和文本长度上限，避免复盘提示无限膨胀。

在线 Policy 会用该快照补齐 API 省略的卡牌类型、费用、规则文本和动态值；复盘 prompt 只
内嵌本批相关的有界事实，并提供完整 JSONL 路径供按需深读。复现、schema 和校验命令见
`tools/game-knowledge/README.md`。

## 大模型复盘（异步追及队列：游玩零等待）

**每局结束后**，大脑只做一件事：把复盘请求写入 `knowledge/review_queue.json`，然后**立即开下一局**。
复盘由独立工作线程在后台串行消化——若一局结束时上一场复盘还没完，请求在队列里累积，
下一场复盘**一次性分析多局**。`review_queue_max` 与 `max_runs_in_packet` 当前都为 100，
只限制单次取批/提示词覆盖的局数，不截断持久队列；
复盘失败会把整批放回队尾，并以 60 秒起、15 分钟封顶的条目级持久化退避继续追及，
退避中的旧批次不会拦住后来产生的新直播证据。

复盘使用宿主强制的“证据 → 实验 → 观测/撤回”闭环。当前 0 胜追赶期内，**每个成功批次**
都必须修改至少一个运行时行为/配置路径，或在生产代码中增加能进入后续 run 的观测；只改
`meta_review.md`/短评，或者只改 `selfcheck.py`，会在真实提交前被拒绝，完整隔离成果进入
`review_salvage`，原批次退避重试；只碰生产文件的注释/空白同样过不了实质变更检查。提示词同时按
“同一问题 3 个独立对局或连续 2 个复盘批次”
判定证据成熟，并携带最近零代码报告作为历史实现债务；模型必须优先补做未落地问题。
要求是相对安全、有界、可观测、可记录、可继续调整或撤回，不要求证明绝对安全；拿不准行为
改法时先落地运行时观测，也不能用“参数顶格/耦合较宽/再看几局”代替交付。

模型按 runner-aware **三级优先链**逐条检查；OpenCode 使用 `opencode models`，Codex 使用
本机登录状态与 bundled model catalog 做不产生付费轮次的可用性探测：

1. `opencode-go/glm-5.3-flash@max` — GLM-5.3-Flash (2x usage) · OpenCode Go · max
2. `gpt-5.6-luna@max` — Codex CLI · 隔离 clone custom profile · `approval=never`
3. 兜底 `kimi-for-coding/k3`，常规新任务每 5 局一次（同样走异步队列）

Windows 上 Luna 固定使用用户缓存中的 Codex CLI `0.148.0`；`Start-Agent.ps1` 冷启动时通过
`scripts/Install-CodexCompat.ps1` 非全局安装并校验固定 SHA256。每次启动 Luna provider 前还会
用本地 `exec-server fs/readFile` 对普通盘符文件执行无模型、零 token 的读取兼容能力预检；
预检失败时不启动 provider、不冷却 Luna，并保留原批次亲和性重试。

前两级均按每局优先复盘；Kimi 的 5 局门槛只控制常规新任务，已有失败包的逐包重审不会因此
永久等不到第 5 局。模型已经开始产生语义输出/工具事件后，失败事务固定原 runner、模型、推理强度
和审批模式重试；若 CLI 在模型工作开始前就不可用，才允许按优先链顺位交给下一层。
每个条目**独立失败冷却**：当前超时与硬失败（exit≠0/异常）都冷却 5 分钟，
由 `preferred_*_cooldown_min` 配置。优先与兜底复盘超时统一为 8 小时（480 分钟）；
复盘正常换行事件持续写直播流，病态超大单事件会有界截断；宿主内存只保留有界尾部。
总预算之外还有独立的无进展 watchdog：连续 15 分钟没有任何 stdout 字节时告警，30 分钟时
只终止该场复盘并完整保全现场、原模型退避重试。stall 属于本地 CLI/工具链故障，不会错误冷却 GLM；
这里以同一 provider 子进程 stdout 的原始字节进展为主计时，有新字节即清零；队列仍有 backlog 或
宿主正在翻译刚读到的事件时不算模型静默。整场 8 小时总预算不变，15/30 分钟为推理、工具执行及
可能的子进程输出缓冲预留余量。

隔离、提交与成果保全设计：

- 复盘模型在无 remote、无 hardlink 的独立 clone 内工作；宿主盘点该 clone 的全部改动，
  再用 deny-only 分类器导出自检通过的精确二进制 patch。`sts2-ascend/` 下安全的静态
  项目文件均可接收，包括新建或 ignored 的源码、`brain/config.json`、其他配置、脚本、
  测试、文档和静态知识。cache 产物从 patch 排除但不阻断已验证源码；在线运行状态、
  Git 元数据与越界/不安全路径会拒绝自动合入整批，并先保全完整现场
- 不使用“全仓指纹变化”、全仓脏状态或 refs 变化作为复盘门禁；真实仓的正常提交、推送、
  用户文件与运行日志变化不会让隔离成果作废
- autogit 以进程内锁 + 跨进程锁包围完整事务，并在私有 index 构造提交；分支 CAS 成功后，
  真实 index 只对本次精确 pathspec 同步到新提交，不改工作树，也不全量重置用户 index
- 真实 index 同步遇到短暂的 `index.lock` 会有界重试，并在每次重试前复核提交关系和目标
  index 身份；重试仍失败时写入耐久 pending-sync 回执。下次存档事务会先做 preflight 自愈：
  只有目标 paths 仍精确等于已记录的机器父提交快照时，才把这些 paths 的 index 前移到机器
  存档提交。HEAD 后来已有无关 commit 也不妨碍恢复；若检测到真正的用户 staged 内容，则保留
  用户内容并拒绝覆盖
- 普通存档使用既定的在线进度 pathspec；复盘提交使用 deny-only 验证后的实际改动路径，
  不使用固定文件名单。排除上述可证明的机器遗留 index 后，目标路径已有 staged 内容时整笔拒绝
- 复盘 active 时在线存档照常提交并立即推送；复盘结束也会补推此前网络失败的积压，
  不依赖优先模型必须产出有效 patch 才能上库
- 分支固定 symbolic-ref 身份并通过 `update-ref` compare-and-swap 前进；并发提交发生时从新 HEAD
  重建，分支切换则拒绝事务
- 超时、进程失败、自检失败、deny-only 边界拒绝和提交冲突都会先把**全部工作树改动**（包括越界、
  ignored 和被规则拒绝的文件）原子保存到 `knowledge/code_backups/review_salvage/<批次>/`；
  `files/`、`wip.patch`、完整 `raw_sandbox/`、provider 原始 JSONL、报告与 manifest 供人工分析和模型逐包重审；
  宿主永不自动套用其中的旧 patch
- 每次新失败包发布后都会更新受 Git 跟踪的 [`REVIEW_REJECTIONS.md`](REVIEW_REJECTIONS.md)，并为
  该条拒合记录单独建立 commit；正常运行立即 push，停止临界区先本地 commit、下次启动补推，
  以免远端清单失踪又不牺牲两分钟热停死线。GLM 补合或确认无有效改动后，
  宿主只负责耐久闭环：确认代码 commit 已在远端，先将精确失败包原子移入
  `.glm-closed-*`，再为该包一次性提交最终清单行并确认远端，最后才可中断地精确清理隔离目录。
  重试产生的 evidence attempt 先闭环，唯一 target 作为 lineage 日志最后删除；任何一步失败或 Stop
  都保留可恢复现场，新 Brain 续做清单/隔离清理，不会让 GLM 重做已推送的策略成果
- 路径任一层名称含 `cache`（大小写不敏感）或为 Python 字节码缓存后缀的再生成产物会完整留档并
  记录到 `transient_artifact_paths`，但不会混入源码 patch，也不会误杀已经通过自检的源码改动；
  clone/快照从创建起位于项目 ignored 的 `knowledge/code_backups/review_work/`，热停时先发布项目内
  指针再由新 Brain 异步补齐，不依赖可能被系统清理的外部 TEMP
- 隔离失败现场保存后才删除 clone；起不来时 runner 仅对校验过的复盘 commit 创建正向 revert commit，
  不使用 `reset --hard` 或全目录清理
- 重启 marker 在真实工作树/ref 变化前以 `prepared` 原子发布；两者均成功后才确认为 `committed`。
  若旧 marker 尚在观察，新复盘会把它内嵌后接管，Git CAS 中止则自动恢复旧 marker，绝不再把健康
  观察延迟变成全局拒合锁；新代码回滚后 runner 也会恢复前任 marker，并写独立 tombstone 防止
  Windows 文件锁导致重复回滚。Runner 创建每代 Brain 前只读 Git ref 与 marker 文件冻结启动 epoch，
  不启动可能被杀软卡住的 Git 子进程；只有从局间屏后开始并完整跑完的两局才清除观察链。健康记账
  拿不到仓库锁会在 0.1 秒内放弃本局而不阻塞直播；崩溃重试间隔为 10 秒
- Runner 在仓库锁内创建每代 Brain，并要求 session PID 文件回显本代唯一 `boot_id`、冻结 HEAD、
  marker epoch 和 `stage=imported` 后放锁，再在锁外等待 `stage=ready`；模块/config 不会混载，
  Agent/Knowledge 初始化又可以安全重入仓库锁。15 秒未 ready 会精确终止本代。罕见
  `prepared` 残留会在启动前按精确 provisional patch 判定：HEAD 已发布则补确认为 committed，
  HEAD 仍在 parent 则证明工作树未应用或精确反向撤回；重叠到无法证明时，先完整保存目标文件、
  当前/provisional patch 和 marker 到 salvage，再恢复当前已知 Git 树，绝不无限断流
- 一次连续启动断流共用单一 115 秒绝对 deadline；复盘代码两次握手失败即在剩余预算内本地创建
  安全反向 commit 并立即拉起旧代码。push 交给后续正常 checkpoint，恢复热路径不等待网络
- GLM 可用时，积压/长期未成功只扩大追及批次，不再强制交替到 K3；K3 仅在 preferred 模型被
  实际判定 unavailable/cooldown 时作为 fallback
- 提交验收与 Brain 热重启分开判定：通过验收的源码、脚本、测试、文档和静态知识都按实际
  patch 提交；只有 `brain/` 内 Brain 长驻进程会加载的 Python 源码或运行配置出现实质变更，
  才发布事务 marker，并在局间以退出码 42 热重启。其他已验收文件不因此被丢弃，也不制造
  无意义的 Brain 断流

复盘以 **OpenCode 或 Codex 无头会话**执行，复用本机已有授权且无需项目 API key；
模型可修改 `sts2-ascend/` 下 deny-only 边界内的任意静态项目文件，不设固定提交名单；在线
`stats`、`policy`、`progression`、`lessons`、`runs` 在复盘期间只读。复盘报告追加到
`knowledge/meta_review.md`。

每份新 run 携带稳定 `run_number`，追及队列按局号读取 active 或已 compact 的原证据。旧日志
没有局号映射时会显式标记 `recent_fallback_unmapped`，不会把“最近 N 局”冒充目标批次。
每批复盘还会把**最新死亡局的全部持久决策记录**原样内嵌到
`decision_chain_evidence.full_failure_run`，模型必须逐条检查；其余局继续使用有界摘要，避免
100 局完整链超过模型上下文。新生成的战斗记录会为每个成功动作补记回合和能量；`end_turn`
额外保存当时的手牌、可用动作、来伤和有界 `SCAN/GATE/RANK/LOCK` 轨迹，地图、休息、事件、
选牌、商店和药水等高信息选择也保存有界轨迹。旧 run 没有这些新增字段时仍完全兼容。

手动立即触发一次（同步）复盘：`py brain/llm_review.py --now`。若故障报告证明旧批次曾完成但
未成功合入，可在大脑停止后的切换窗口用 `py brain/llm_review.py --requeue 562,566,567`
把指定局追加到队尾；已在 pending/reviewing 的局会自动去重，不会抢占最新直播证据。
配置项见 `brain/config.json` 的 `llm` 节（间隔/模型/冷却/队列上限/禁用）。

### 失败包逐包交回 GLM

失败包不是可由宿主盲套的补丁。机制修好后，每个指定包会以稳定、独立的
`replay_target=<package-id>` / `retry_group=<package-id>` 进入持久队列。同一 target 的后续失败
不会变成新目标，而是另存完整失败包并标记为 `replay_role=attempt_evidence`，追加到该 target 的
`salvage_attempts` lineage。工作线程的一个取批只包含该 target，不与直播新局或另一 target
混合；它的运行记录即使与正常队列局号重叠也保留独立身份。单批上限仍由
`review_queue_max` / `max_runs_in_packet` 约束。失败时的 `model` / `source` / `every`
会跟随每个队列条目持久化和重试，不会因退避或 Brain 重启被默默改成另一模型。

失败包与 manifest 一起原子发布 `replay_enqueue_pending`、target/role 和当时的 `replay_queue_ids`。
如果进程在“包已保存、队列尚未收尾”之间中断，新 Brain 会用 queue id、target 和 manifest intent
对齐 pending/reviewing，缺失时创建且仅创建一个 target job，并把后续 attempt 全部挂回该 lineage。

没有真实 run id 的历史失败包会标记为 `evidence_only`；为满足持久队列 schema 而分配的正整数
synthetic run 只写入 `queue_identity_runs`，绝不是对局证据。该任务的 prompt 不加载当前或近期的
同号 run，`requested` / `exact` / `missing` 与 `runs_summary` 均为空，
`decision_chain_evidence.full_failure_run` 也为 `null`，因此不会把后来恰好同号的死亡局思维链错接到旧包。
启动时的 replay intent、ledger、pending/reviewing 和 host-only closure 维护都在同一个 worker supervisor
中执行；启动或运行阶段异常时保留持久状态，30 秒后重跑整套幂等恢复。线程真正退出时一定释放
`_worker_started` latch，使监督器能够重新拉起，而不是留下“标记为已启动、实际没有 worker”的死状态。

`evidence schema v3` 在 Brain 恢复后懒物化证据。沙箱验收、失败 WIP 捕获和重审物化都使用一次性
私有 Git index 与私有 object directory，raw objects 只作为 alternate 读取；force-stage、`read-tree`
和候选对象都不会写回 raw HEAD、index 或 object database。物化器还会用独立的只读 index 环境直接读取
raw `.git/index`，将 raw worktree 与模型原 index 分成两个证据源，而不是让私有 index 覆盖后者。
它从 manifest 的 `pre_head` 分源导出 raw worktree、raw index、raw HEAD commit、local refs 与 stash
相对基线的改动；只有 `refs/heads/*` 中的 commit 能形成代码候选，`refs/notes/*` 等其他 refs 只进入
inventory provenance，不被解释成待合入代码。每个来源分别记录路径分类和 accepted-only 候选片段。
Windows 下 Git loose objects 带只读属性；private-index 清理会先解除只读并短重试。worker 启动时只按
`capture-index` / `validation-index` / `retry-index` 三个固定前缀回收超过 5 分钟的直属临时目录，
不会扫描或删除 `sandbox`、`snapshot` 与 `review_salvage` 取证现场。
所有隔离/取证 Git 子进程仅通过进程环境启用 `core.longpaths=true`，因此深层 generated/cache/rejected
文件即使完整 Windows 路径超过 260 字符仍会被 force-stage 到全量 inventory；不会通过跳过长路径来
伪造“现场完整”，也不会改写原仓库或用户的 Git 配置。
整个过程也不写原 clone 的 local refs、stash 或 worktree；早期 schema 的物化摘要保存在 history，不清除
取证 clone 中已有的不可达 objects。没有 raw clone 时，如果失败链已保存验收过的
`validated_candidate.patch`，v3 会将它提升为 accepted-only 候选，不会把含 cache/运行现场的全量
`wip.patch` 冒充已验证补丁。`retry_candidate_inventory.json` 同时保留全量路径和分源记录；
cache、在线现场与被拒文件的原始字节仍全部留在失败包。所有候选只是有界证据：GLM 必须
对照当前 HEAD 重新审核，选择性重实现仍有效的改动、解决冲突并运行 selfcheck；宿主绝不自动应用它。

GLM 在报告中为当前包写软回执：

```text
retry_resolution: <package-id> integrated|no_valid_change|still_pending
```

也接受语义完全相同的 Markdown 表格行（`retry_resolution` 必须独占首列，包 id 必须精确匹配）；
合法状态后可紧跟括号、冒号或破折号引出的简短说明。解释性正文、包名子串和把自由文本直接续在
状态词后的模糊内容不会被当作回执。若旧版解析器漏认了已经推送的回执，
唯一复盘 worker 会在启动及周期维护中只检查上游提交新增的报告行：`integrated` 还必须与同一提交里的
生产实质改动相互印证。确认后仍沿用 manifest → queue → ledger → quarantine 的宿主耐久事务恢复，
不会直接套用失败补丁或越过取证清单删除目录。

`integrated` 表示已在当前 HEAD 重新实现并验证，`no_valid_change` 表示复审确认无仍应合入的改动。
该回执不是代码验收门禁：遗漏或 `still_pending` 不会撤回本轮已验收的独立改动，但失败包会
保持 pending；新失败包只追加为 attempt evidence，target 与原模型计划一起退到队尾继续交给 GLM。
只有 `integrated` / `no_valid_change` 对应 commit 已确认在远端后，宿主才会按 attempt-first/target-last
顺序闭环 lineage。回执先落 manifest，持久 `reviewing` 事务成功消费后才允许隔离包；
每个包只提交一次最终清单行并确认远端。删除逐文件检查 Stop，可由下次启动续做；隔离包的根
`manifest.json` 始终最后删除，随后才删除目录。若进程恰在这个有界尾部崩溃而留下空的
`.glm-closed-*`，恢复逻辑不会因“目录已经空”自行放行，只有精确确认 upstream 中该 package 的
最终 `并闭环` 清单行后才删除这个空尾目录。

显式重投是离线队列操作：先使用统一入口停 Brain（可保留游戏），指定包名，再恢复整套。
该命令只发布小 manifest/queue intent，对失败包体积是 O(1)；不在停机窗口扫 raw clone、hash 大文件或物化 patch。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1 -KeepGame
py -3 -B .\sts2-ascend\brain\llm_review.py --replay-salvage PACKAGE_A,PACKAGE_B
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-Agent.ps1 -SkipDeploy
```

入口不会扫描并自动重投所有历史包；只为显式命名的直接子目录发布 intent 并入队。
若指定的目录本身是 attempt，入口会回溯并唤醒它已有的 target，绝不擅自提升出第二 target。
Brain 仍在活 session 时会拒绝改写队列，避免与在线 worker 竞争；恢复后 worker 才懒物化 v3 证据。

### 复盘代码的局间重载

异步复盘提交 `brain/*.py` 等运行时代码后，会同时留下 committed `pending_restart.json`。
Brain 只在无 active run 的 `MAIN_MENU` / `CHARACTER_SELECT` 以退出码 42 交给 runner 重载；
`GAME_OVER` 仍由旧进程完成归档和返回菜单，避免新进程重复结算同一个终局帧。若用户中途放弃，
旧 run 会先按既有规则归档，再在新 run 的任何动作发生前完成进程交接。判定只比较 runner 冻结的
`boot_review_commit` 与耐久 marker，不根据全仓 HEAD 或普通存档提交触发。

## ASCEND-VISION 直播驾驶舱

赛博青蓝悬浮窗（`brain/review_viewer.py`）现在是常驻直播驾驶舱，而不再依赖复盘任务才出现。
brain 启动时会启动独立 viewer，`dashboard_launcher.py` 监督其心跳并在异常退出后自动恢复；brain 热重启、
复盘开始或结束都不会改变驾驶舱生命周期。窗口继续无边框半透明置顶、点击穿透且不抢游戏焦点。

窗口层级分成两条明确独立的本地看门狗：`ASCEND-VISION` 自身约每 500ms 无激活恢复一次置顶，
无论是否开播都持续有效；游戏窗口只在本机直播姬实际状态为 `Streaming` 时每 60 秒巡检一次。
游戏巡检从当前 session 读取精确 `game_exe`，按完整可执行文件路径定位窗口，先无激活恢复游戏
`TOPMOST`，再把驾驶舱排到游戏上方。空闲、启动中、停止中、直播姬未运行、状态未知或读取失败时
绝不触碰游戏窗口。这条巡检只使用 Python 标准库、Livehime 本地日志和 Win32，LLM/token 消耗为 0。

驾驶舱固定提供三类信息：

- **楼层统计**：UI 显示当前活动角色的一套四指标（历史平均、近 20 局平均、历史最高、近 20 局最高）、该角色最近 40 个有效完结局的原始楼层线与 5 局滚动均线，并显示双角色同窗口滚动平均楼层比值。
  底层 `profiles` 分别保存白绮与战士数据，样本不共享、互不回填；UI 不并排显示两套指标卡片。
  当前局独立显示，不混入历史均值；归档 catalog 与活动 run 按 `run_id` 去重，活动证据优先，
  进行中局、人工接管局、零决策幻影局和坏 JSON 不会被伪装成 0 楼。
- **机械决策链**：以 `SCAN → GATE → RANK → LOCK → ACK` 展示当前观察、规则闸门、前三候选、
  最终动作、说明文本及 `proposed/pending/reconciling/applied/retrying/rejected/failed` 等执行结果。
  规则直达型动作只画真实经过的线性节点，不编造候选、概率或“思维链”。
- **实时复盘流**：`knowledge/review_live.stream` 在同一窗口提供多行流式复盘正文；复盘 OpenCode 和
  speaker 仍按需启动，复盘流中断不会影响实时统计、决策图或游戏控制，也不会进入决策遥测。

窗口采用状态驱动的稳定布局，而不是按秒把整页切回另一种模式：

- 对局中以决策链为主，同时保留多行实时复盘流；
- `GAME_OVER` 时以楼层趋势为主，同时继续显示复盘流；
- 主菜单、等待状态或没有新鲜决策时切换为完整 REVIEW 视图；
- `--interactive` 下可手动固定 LIVE、TREND 或 REVIEW，自动模式不会覆盖手动选择。

真实楼层与学习分严格隔离：`stats.json` 的 `floor_sum_raw` / `best_floor_raw` 用于驾驶舱；原有
`floors_total` / `best_floor` 继续保留“真实楼层 + 胜利 50 分”的学习评分，既有策略估值语义不变。
旧库会用胜场数、进阶最佳层及逐局/归档证据迁移，不会把胜利奖励显示成楼层。

实时决策遥测是**纯本地、确定性的 Python 标准库代码**，只复用 Policy 本次已经算出的状态、闸门、
候选分数与结果，不重新决策或再次随机探索。发布器通过有界队列异步原子替换
`.runtime/live_dashboard.<SESSION_ID>.json`；这条路径不调用 LLM、OpenCode、Minimax、OpenRouter 或
任何网络服务，token 消耗为 **0**。大模型只属于独立异步复盘链，复盘链本身仍可能消耗模型 token；
“遥测零 token”不代表实时复盘免费。

手动与配置用法：

- `py brain/review_viewer.py --demo`：用模拟统计与决策演示驾驶舱。
- `py brain/review_viewer.py --attach-current`：只读轮询 `opencode.db`，回放最近一场复盘。
- `--interactive`：允许拖拽/ESC 关闭、手动选择 LIVE/TREND/REVIEW，并关闭点击穿透。
- 首选开关为 `config.json` 的 `viewer.enabled`；旧 `llm.viewer_enabled` 继续兼容。
- viewer 的根目录和单实例锁以当前 stack session 的 `.runtime` 为准；复盘隔离 clone 继承
  `STS2_ASCEND_DISABLE_VIEWER=1`，即使自检执行入口脚本也不能创建第二个直播悬浮窗。
- Windows 另用 `Local\STS2_ASCEND_ASCEND_VISION` 命名互斥体建立跨目录单实例：主树、
  `review_work` 和 `review_salvage/raw_sandbox` 即使有不同的文件锁，也不能同时打开两个窗口。
- detached viewer 使用关闭继承句柄的方式启动，不能再持有 OpenCode/selfcheck 的 stdout 捕获管道；
  viewer 存活不会阻止工具调用收到 EOF。
- 活动局日志持续写入只更新文件签名，不会在统计内容未变化时触发统计卡重绘。

该升级不改变直播控制边界：开播仍启动完整 sts2-ascend 栈、将杀戮尖塔2置顶后通过本地直播姬开播；
下播仍只让哔哩哔哩直播姬下播，不停止驾驶舱、智能体、语音服务或游戏。

## 语音朗读（ASCEND-VOICE）

默认是两种声音并行：**Edge TTS 读实时复盘正文**，白绮的 **IndexTTS-2.5 GPU** 继续读碎碎念和
最终结论。两套引擎按用户要求允许同时出声；`quipper.py` 是唯一 IndexTTS 模型 owner，不会为结论
再加载第二份模型：

- 默认配置：`llm.tts_mode=edge`、`tts.clone_engine=indextts`、`device=cuda:0`
- `edge_speaker.py` 用 `zh-CN-XiaoxiaoNeural` 三路预合成实时正文；Edge 网络失败只让该句回退 SAPI，
  不会把实时正文塞给慢速 IndexTTS
- 隔离复盘通过 deny-only 路径分类、自检并导出精确 patch 后，把本场短结论直接放进
  `LIVE-END` 哨兵；Edge 收到后
  立即以 `source=conclusion` 提交给共享 GPU owner，因此不依赖稍后才合入的全局结论文件，也不会读到上一场
- 共享 owner 会把整段结论保留为一个不可插队的逻辑任务，并按自然停顿细分：目标约 10 字、硬上限 20 字；
  它先依次预合成本批全部短句，确认每个 WAV 都准备完成后，才按原顺序连续播放，播放阶段不再等待下一句推理。
  任一句预合成失败则整批不开始播放并记录失败段，避免半段结论出声或乱序；标点留在短句内提供自然语气停顿
- 所有空白规范化后不超过 20 个字符的输入限制为最多 320 个语义 token，缩小随机解码未及时产生 EOS 时的
  单句阻塞上界
- `LIVE-START/END` 带唯一 `review_id`；同一 Edge 跨连续复盘时按 id 去重，并由单一 FIFO 保证多场结论顺序
- Edge 正文队列和白绮结论并行工作；白绮碎碎念也不因 Edge 直播暂停。Index 内部仍严格串行，结论优先于
  等待中的碎碎念，但不会强行打断已经开始的那一句
- GTX 1060 低显存路径：GPT 使用 FP16，codec / S2Mel / BigVGAN 保持 FP32；禁用 BF16、
  FlashAttention、CUDA 自定义 kernel 和 torch.compile
- 固定参考音色 `tts/reference_voice_15s.wav` 由 `scripts/prepare_reference_voice.py` 从原始 WAV 的前 15 秒生成：
  只把超过 400ms 的低能量静段缩到 200ms，保留自然停顿并在替换前备份 WAV 和条件缓存；可先运行
  `py -3 scripts/prepare_reference_voice.py --dry-run` 预览，再去掉 `--dry-run` 原子更新；首次生成条件缓存后，
  只在参考阶段使用的 Wav2Vec/CAMPPlus 随后从显卡卸载，不参与每句合成
- Edge 朗读内容 = 直播窗可见内容（代码/JSON/路径/tokens 行不读）
- GPU owner 和 Edge 朗读器各有 session-scoped 单实例锁；CUDA 不可用时只跳过白绮结论/碎碎念，
  绝不静默回退 CPU 或加载第二份模型
- Brain 热重载后不会把一次 `Popen` 当作 owner 已上线：`/health` 必须回显同 session、定向 TTS 代码
  epoch、协议/feature 与精确 PID 创建身份才算成功。owner 代码变化时，旧代先停止接单并完整播完已接语音，
  队列空闲后协作退出；候选确认旧 PID 已消失才加载 CUDA 模型。首次从旧协议升级需要统一 Stop/Start 一次，
  不会为迁移强杀旧语音进程
- 兼容模式仍可选：`llm.tts_mode` = `indextts` / `hybrid` / `sapi` / `nano` / `off`
- **音量控制**：`Ctrl+Shift+Alt+↑` 调大 / `Ctrl+Shift+Alt+↓` 调小（±10%）/ `Ctrl+Shift+Alt+M` 静音切换；
  悬浮窗 HUD 实时显示；状态存 `knowledge/voice_volume.json`（SAPI 每句现读、克隆合成按比例缩放）
- 手动一次性朗读：先启动整套，再运行 `py -3 tts/speak_once.py <UTF-8文本文件>`；它只提交给现有 owner，不会另载模型

TTS 环境在 `third_party/index-tts/`（uv 旁路，gitignore）。GPU 改造与实测见
`docs/2026-08-26-IndexTTS-GPU双路共享.md`；最终结论的 10～20 字强制分段与短句生成上限见
`docs/2026-08-27-IndexTTS复盘结论细粒度分句与生成上限.md`。

## 进程结构

```
Start-Agent.ps1（session + PID 身份记录，默认后台）
  ├─ SlayTheSpire2.exe（Vulkan）
  └─ runner.py（拉起大脑 / 退出码42重启 / 崩溃自动回滚）
        └─ py -m brain（决策主循环）
              ├─ 驾驶舱监督器 → review_viewer.py（常驻、自愈、点击穿透）
              ├─ 本地决策遥测 → .runtime/live_dashboard.<SESSION_ID>.json（原子快照）
              ├─ quipper.py（唯一 IndexTTS GPU owner + 白绮碎碎念）
              ├─ 每局结束 → review_queue.json
              └─ 复盘线程 → opencode/codex / edge_speaker（按需；多行复盘流进入同一驾驶舱）

Stop-Agent.ps1：session 哨兵协作退出 → 精确进程树兜底 → 游戏关窗
```

进程协议在 `.runtime/`，共享实现为 `brain/lifecycle.py`。GUID stop 文件在停止后保留，用来阻止旧进程跨新 session 复活；不要手工清理。

每局结束自动 `git commit+push` 存档（`brain/autogit.py`），进化历史全程可追溯。

## 与上游 mod 的关系

- `third_party/dist/`：上游 release 包（默认 v0.9.1，由 Deploy-Mod.ps1 自动下载，不入库）
- 上游 mod 文件（`STS2AIAgent.dll/.pck/mod_id.json`）被复制到游戏 `mods/` 根目录（上游官方布局）
- 上游协议为 AGPL-3.0-only；本项目仅以网络客户端方式使用，未修改其代码

## 常见问题

- **游戏窗口就是智能体正在玩的实例**：大脑通过 HTTP 直接驱动当前运行的游戏进程，
  你看到画面上的每一步操作都是它做的。想验证可以随时截图对比 `brain.log` 的决策记录。
- 日志中文乱码：`brain.log` 是 UTF-8，用 VS Code / 新版记事本打开正常；PowerShell
  `Get-Content` 默认 GBK 会显示乱码。
- 端口：mod 默认 8080，被占用自动 8081+；大脑会探测 8080-8084。
