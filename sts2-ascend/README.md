# sts2-ascend — 杀戮尖塔2 自主学习智能体

基于 [CharTyr/STS2-Agent](https://github.com/CharTyr/STS2-Agent)（游戏内 HTTP API mod，AGPL-3.0）构建的
**会自动玩、会思考、会进化的杀戮尖塔2智能体**。

- 反复游玩最左侧的战士角色（Ironclad / 铁甲战士）
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

模型按**优先链**逐条检查（`opencode models` 清单为准，条目形如 `provider/model[@variant]`）：

1. `opencode-go/glm-5.3-flash@max` — GLM-5.3-Flash (2x usage) · OpenCode Go · max
3. 兜底 `kimi-for-coding/k3`，每 5 局一次（`review_every_runs`，同样走异步队列）

命中优先链任一条目 → 每局复盘（`preferred_every_runs`，默认 1）。
每个条目**独立失败冷却**：当前超时与硬失败（exit≠0/异常）都冷却 5 分钟，
由 `preferred_*_cooldown_min` 配置。优先与兜底复盘超时统一为 8 小时（480 分钟）；
复盘正常换行事件持续写直播流，病态超大单事件会有界截断；宿主内存只保留有界尾部。

并发安全设计：

- 复盘模型在无 remote、无 hardlink 的独立 clone 内工作；生产树只接收自检通过的 allowlist
  精确 patch
- 不使用“全仓指纹变化”、全仓脏状态或 refs 变化作为复盘门禁；真实仓的正常提交、推送、
  用户文件与运行日志变化不会让隔离成果作废
- autogit 以进程内锁 + 跨进程锁包围完整事务，并在私有 index 构造提交，不读写用户 index
- 普通存档与复盘提交各有精确 allowlist；目标路径已有 staged 内容时整笔拒绝
- 复盘 active 时在线存档照常提交并立即推送；复盘结束也会补推此前网络失败的积压，
  不依赖优先模型必须产出有效 patch 才能上库
- 分支固定 symbolic-ref 身份并通过 `update-ref` compare-and-swap 前进；并发提交发生时从新 HEAD
  重建，分支切换则拒绝事务
- 超时、进程失败、自检失败、allowlist 拒绝和提交冲突都会先把**全部工作树改动**（包括越界、
  ignored 和被规则拒绝的文件）原子保存到 `knowledge/code_backups/review_salvage/<批次>/`；
  `files/`、`wip.patch`、完整 `raw_sandbox/`、报告与 manifest 仅供人工分析，永不自动应用；
  clone/快照从创建起位于项目 ignored 的 `knowledge/code_backups/review_work/`，热停时先发布项目内
  指针再由新 Brain 异步补齐，不依赖可能被系统清理的外部 TEMP
- 隔离失败现场保存后才删除 clone；起不来时 runner 仅对校验过的复盘 commit 创建正向 revert commit，
  不使用 `reset --hard` 或全目录清理
- 重启 marker 在真实工作树/ref 变化前 exclusive 原子发布；加载新 commit 并健康完成两局后才清除
- 复盘产生变更 → 本局结束的安全点以退出码 42 自重启加载

复盘以 **OpenCode 无头会话**（`opencode run`，走本机已有授权，无需 API key）执行，
只可修改提示词与宿主共同定义的策略代码/报告 allowlist；在线 `stats`、`policy`、`progression`、
`lessons`、`runs` 在复盘期间只读。复盘报告追加到 `knowledge/meta_review.md`。

每份新 run 携带稳定 `run_number`，追及队列按局号读取 active 或已 compact 的原证据。旧日志
没有局号映射时会显式标记 `recent_fallback_unmapped`，不会把“最近 N 局”冒充目标批次。

手动立即触发一次（同步）复盘：`py brain/llm_review.py --now`。若故障报告证明旧批次曾完成但
未成功合入，可在大脑停止后的切换窗口用 `py brain/llm_review.py --requeue 562,566,567`
把指定局追加到队尾；已在 pending/reviewing 的局会自动去重，不会抢占最新直播证据。
配置项见 `brain/config.json` 的 `llm` 节（间隔/模型/冷却/队列上限/禁用）。

## ASCEND-VISION 直播驾驶舱

赛博青蓝悬浮窗（`brain/review_viewer.py`）现在是常驻直播驾驶舱，而不再依赖复盘任务才出现。
brain 启动时会启动独立 viewer，`dashboard_launcher.py` 监督其心跳并在异常退出后自动恢复；brain 热重启、
复盘开始或结束都不会改变驾驶舱生命周期。窗口继续无边框半透明置顶、点击穿透且不抢游戏焦点。

驾驶舱固定提供三类信息：

- **楼层统计**：历史平均、近 20 局平均、历史最高、近 20 局最高，以及最近 40 个有效完结局的
  原始楼层线和 5 局滚动均线。当前局独立显示，不混入历史均值；归档 catalog 与活动 run 按
  `run_id` 去重，活动证据优先，进行中局、零决策幻影局和坏 JSON 不会被伪装成 0 楼。
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
- 隔离复盘通过 allowlist、自检并导出 patch 后，把本场短结论直接放进 `LIVE-END` 哨兵；Edge 收到后
  立即以 `source=conclusion` 提交给共享 GPU owner，因此不依赖稍后才合入的全局结论文件，也不会读到上一场
- 共享 owner 会把整段结论保留为一个不可插队的逻辑任务，但每次真正调用模型前按自然停顿细分：目标约 10 字、
  硬上限 20 字；所有空白规范化后不超过 20 个字符的输入同时限制为最多 320 个语义 token，缩小随机解码
  未及时产生 EOS 时的单句阻塞上界
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
              └─ 复盘线程 → opencode / edge_speaker（按需；多行复盘流进入同一驾驶舱）

Stop-Agent.ps1：session 哨兵协作退出 → 精确进程树兜底 → 游戏关窗
```

进程协议在 `.runtime/`，共享实现为 `brain/lifecycle.py`。GUID stop 文件在停止后保留，用来阻止旧进程跨新 session 复活；不要手工清理。

每局结束自动 `git commit+push` 存档（`brain/autogit.py`），进化历史全程可追溯。

## 与上游 mod 的关系

- `third_party/dist/`：上游 release 包（默认 v0.9.0，由 Deploy-Mod.ps1 自动下载，不入库）
- 上游 mod 文件（`STS2AIAgent.dll/.pck/mod_id.json`）被复制到游戏 `mods/` 根目录（上游官方布局）
- 上游协议为 AGPL-3.0-only；本项目仅以网络客户端方式使用，未修改其代码

## 常见问题

- **游戏窗口就是智能体正在玩的实例**：大脑通过 HTTP 直接驱动当前运行的游戏进程，
  你看到画面上的每一步操作都是它做的。想验证可以随时截图对比 `brain.log` 的决策记录。
- 日志中文乱码：`brain.log` 是 UTF-8，用 VS Code / 新版记事本打开正常；PowerShell
  `Get-Content` 默认 GBK 会显示乱码。
- 端口：mod 默认 8080，被占用自动 8081+；大脑会探测 8080-8084。
