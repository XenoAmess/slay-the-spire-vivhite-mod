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

`Stack ready` 不表示播报员此刻一定存在：碎碎念由 brain 在语音环境可用时启动；opencode、悬浮窗与复盘 speaker 只在复盘时按需启动。

## 它如何"进化"

1. **在线统计**：每场战斗结束记录敌方组合与掉血量（敌人危险度模型）；每个事件选项结算
   生命/金币变化；每次拿牌/拿遗物打上归因标签。
2. **赛后归因**：一局结束时按"到达层数+胜利率"给本局所有选择记账（incremental mean +
   shrinkage 收缩估计，样本少时不过拟合）。
3. **策略突变**（有界）：被精英打死→提高精英回避血量线；被小怪打死→上调防御权重；
   事件致死→收敛探索率；胜利→放宽进攻性并提升目标进阶。全部钳制在安全区间内。
4. **自我总结**：以上全部变化以中文写入 `lessons.md`，形成可读的"成长日记"。

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

## 大模型复盘（异步追及队列：游玩零等待）

**每局结束后**，大脑只做一件事：把复盘请求写入 `knowledge/review_queue.json`，然后**立即开下一局**。
复盘由独立工作线程在后台串行消化——若一局结束时上一场复盘还没完，请求在队列里累积，
下一场复盘**一次性分析多局**（追及队列，积压上限 `review_queue_max` 批）。

模型按**优先链**逐条检查（`opencode models` 清单为准，条目形如 `provider/model[@variant]`）：

1. `opencode/ox-alpha@max` — Ox Alpha Free (Unlimited) · OpenCode Zen · max
2. `openrouter/stealth/ox-alpha@max` — Ox Alpha · OpenRouter · max
3. 兜底 `kimi-for-coding/k3`，每 5 局一次（`review_every_runs`，同样走异步队列）

命中优先链任一条目 → 每局复盘（`preferred_every_runs`，默认 1）。
每个条目**独立失败冷却**：当前超时与硬失败（exit≠0/异常）都冷却 5 分钟，
由 `preferred_*_cooldown_min` 配置。

并发安全设计：

- autogit 全局 git 锁，游玩线程与复盘线程不撞 index.lock
- 复盘激活期间，每局自动存档**只提交 `knowledge/`**，不会把复盘 agent 改了一半的代码卷进去
- 自检失败用**路径级回滚**（`git restore --source`），不会抹掉复盘期间产生的对局存档
- 复盘产生变更 → 本局结束的安全点以退出码 42 自重启加载；起不来则 runner 按标记回滚

复盘以 **OpenCode 无头会话**（`opencode run`，走本机已有授权，无需 API key）执行，
可修改 `sts2-ascend/` 下任何文件（改数据结构必须同步迁移 `knowledge.py` 与现有数据）。
复盘报告：`knowledge/meta_review.md`；新经验同步进 `lessons.md`。

手动立即触发一次（同步）复盘：`py brain/llm_review.py --now`。
配置项见 `brain/config.json` 的 `llm` 节（间隔/模型/冷却/队列上限/禁用）。

## 复盘直播悬浮窗（ASCEND-VISION）

每次复盘启动时，大脑会自动拉起一个**赛博青蓝主题的直播悬浮窗**（`brain/review_viewer.py`），
把 opencode 复盘的推理过程实时投到屏幕上：

- 复盘 stdout 由大脑流式写入 `knowledge/review_live.stream`（`[LIVE-START]/[LIVE-END]` 哨兵），
  viewer 进程 tail 该文件渲染——viewer 的死活绝不影响复盘本身
- 无边框半透明置顶、**点击穿透**（不挡游戏操作），停靠屏幕右上角
- 特效：青色数字雨背景（新消息脉冲加速）、打字机逐字输出、工具调用品红高亮、
  `SELFCHECK OK` 金色闪光、结束定格 30 秒后淡出
- 手动用法：
  - `py brain/review_viewer.py --demo` 演示全部特效（不依赖游戏/复盘）
  - `py brain/review_viewer.py --attach-current` 只读轮询 `opencode.db`，回放最近一场复盘
    （含 💭 思维链，已结束的会话停留 10 分钟）
  - `--interactive` 可拖拽/ESC 关闭（关闭点击穿透）
- 开关：`config.json` 的 `llm.viewer_enabled`（默认 true）

## 语音朗读（ASCEND-VOICE）

白绮碎碎念和复盘朗读现在都走 **IndexTTS-2.5 GPU**。`quipper.py` 是唯一常驻模型 owner；
`speaker.py` 通过仅监听 localhost、带 session 校验的队列提交复盘句子，两条链不会各占一份模型：

- 默认配置：`llm.tts_mode=indextts`、`tts.clone_engine=indextts`、`device=cuda:0`
- GTX 1060 低显存路径：GPT 使用 FP16，codec / S2Mel / BigVGAN 保持 FP32；禁用 BF16、
  FlashAttention、CUDA 自定义 kernel 和 torch.compile
- 固定参考音色 `tts/reference_voice_15s.wav` 首次生成条件缓存；只在参考阶段使用的 Wav2Vec/CAMPPlus
  随后从显卡卸载，不参与每句合成
- 复盘直播最多保留 8 句最新内容；`LIVE-END` 会丢弃过时积压，让结论优先于直播正文，直播正文又优先于碎碎念
- 朗读内容 = 直播窗可见内容（代码/JSON/路径/tokens 行不读）
- GPU owner 和复盘朗读器各有 session-scoped 单实例锁；CUDA 不可用时明确失败，绝不静默回退 CPU 或加载第二份模型
- 兼容模式仍可选：`llm.tts_mode` = `hybrid` / `sapi` / `edge` / `nano` / `off`
- **音量控制**：`Ctrl+Shift+Alt+↑` 调大 / `Ctrl+Shift+Alt+↓` 调小（±10%）/ `Ctrl+Shift+Alt+M` 静音切换；
  悬浮窗 HUD 实时显示；状态存 `knowledge/voice_volume.json`（SAPI 每句现读、克隆合成按比例缩放）
- 手动一次性朗读：先启动整套，再运行 `py -3 tts/speak_once.py <UTF-8文本文件>`；它只提交给现有 owner，不会另载模型

TTS 环境在 `third_party/index-tts/`（uv 旁路，gitignore）。GPU 改造与实测见
`docs/2026-08-26-IndexTTS-GPU双路共享.md`。

## 进程结构

```
Start-Agent.ps1（session + PID 身份记录，默认后台）
  ├─ SlayTheSpire2.exe（Vulkan）
  └─ runner.py（拉起大脑 / 退出码42重启 / 崩溃自动回滚）
        └─ py -m brain（决策主循环）
              ├─ quipper.py（唯一 IndexTTS GPU owner + 白绮碎碎念）
              ├─ 每局结束 → review_queue.json
              └─ 复盘线程 → opencode → viewer / speaker（speaker 提交到同一 GPU owner）

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
