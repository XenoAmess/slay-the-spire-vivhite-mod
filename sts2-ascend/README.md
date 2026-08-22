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
# 一键：部署上游 mod（首次自动下载 release）→ 启动/检测游戏 → 启动大脑
powershell -ExecutionPolicy Bypass -File sts2-ascend\scripts\Start-Agent.ps1
```

要求：
- 杀戮尖塔2 v0.111.0（`scripts\Deploy-Mod.ps1 -GameDir` 可改路径）
- `py -3`（Python 3.11+；本机 3.14 验证通过）
- 游戏必须先以 Vulkan 启动（`launch_vulkan.bat`，脚本已处理）

停止：在运行大脑的终端按 `Ctrl+C`（或直接结束 python 进程）。知识库实时落盘，随时中断不丢进度。

## 它如何"进化"

1. **在线统计**：每场战斗结束记录敌方组合与掉血量（敌人危险度模型）；每个事件选项结算
   生命/金币变化；每次拿牌/拿遗物打上归因标签。
2. **赛后归因**：一局结束时按"到达层数+胜利率"给本局所有选择记账（incremental mean +
   shrinkage 收缩估计，样本少时不过拟合）。
3. **策略突变**（有界）：被精英打死→提高精英回避血量线；被小怪打死→上调防御权重；
   事件致死→收敛探索率；胜利→放宽进攻性并提升目标进阶。全部钳制在安全区间内。
4. **自我总结**：以上全部变化以中文写入 `lessons.md`，形成可读的"成长日记"。

## 大模型复盘（异步追及队列：游玩零等待）

**每局结束后**，大脑只做一件事：把复盘请求写入 `knowledge/review_queue.json`，然后**立即开下一局**。
复盘由独立工作线程在后台串行消化——若一局结束时上一场复盘还没完，请求在队列里累积，
下一场复盘**一次性分析多局**（追及队列，积压上限 `review_queue_max` 批）。

模型按**优先链**逐条检查（`opencode models` 清单为准，条目形如 `provider/model[@variant]`）：

1. `opencode/ox-alpha@max` — Ox Alpha Free (Unlimited) · OpenCode Zen · max
2. `openrouter/stealth/ox-alpha@max` — Ox Alpha · OpenRouter · max
3. 兜底 `kimi-for-coding/k3`，每 5 局一次（`review_every_runs`，同样走异步队列）

命中优先链任一条目 → 每局复盘（`preferred_every_runs`，默认 1）。
每个条目**独立失败冷却**：超时冷却 30 分钟（免费模型拥堵常见，从宽），
硬失败（exit≠0/异常）冷却 60 分钟（`preferred_*_cooldown_min`）。

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

## 进程结构

```
runner.py（监督进程：拉起大脑 / 退出码42重启 / 崩溃自动回滚）
  └─ py -m brain（决策主循环，游玩不中断）
        ├─ 每局结束 → 入队 review_queue.json
        └─ 复盘工作线程（串行消化，可多局合并）→ opencode run（ox-alpha / k3）→ 直播悬浮窗
```

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
