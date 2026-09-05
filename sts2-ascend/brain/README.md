# Brain — sts2-ascend 决策与学习核心

`brain/` 是 `sts2-ascend` 的 Python 标准库大脑：发现本地 STS2-Agent HTTP API，读取状态，选择并发送动作，记录对局证据，更新 Profile 知识，并把已结束对局交给异步复盘链。它不是游戏 Mod；Mod/API 的部署由 [`../scripts/Deploy-Mod.ps1`](../scripts/Deploy-Mod.ps1) 完成，生产启动由 [`../scripts/Start-Agent.ps1`](../scripts/Start-Agent.ps1) 统一编排。

## 运行边界

- 生产环境只通过 `Start-Agent.ps1` 拉起 runner → Brain；直接运行模块只用于离线开发/诊断。
- Brain 只向本机 `127.0.0.1:8080–8084` 访问 STS2-Agent，不把游戏状态上传到网络服务。
- `/health=ready` 或进程存在不等于正在游玩。发送动作前必须有非菜单的有效 `/state`、`state_version`、可用动作和连续回执；`MAIN_MENU`、`run_unknown`、终局/孤儿局阻塞时保持 fail-closed。
- `knowledge/` 与 `.runtime/` 是运行时状态，由生命周期脚本维护；不要手工编辑、删除、复制或伪造其中的 session、PID、stop sentinel、active-run 或统计文件。
- `Ctrl+Alt+F9` 暂停动作发送并保留游戏/runner，`Ctrl+Alt+F10` 恢复；跨过 F9 的对局会被标记为人工接管并排除学习。
- Brain 不自动开播。直播姬必须保持用户指定状态；开播/下播由独立脚本且需明确授权。

## 模块地图

| 文件 | 职责 |
| --- | --- |
| [`agent.py`](agent.py) | 状态轮询、策略决策、动作闸门、对局/终局处理、知识保存和驾驶舱遥测。 |
| [`client.py`](client.py) | STS2-Agent `/health`、`/state`、`/actions/available`、`/data/*`、`/action` 的本机 HTTP 客户端。 |
| [`policy.py`](policy.py)、[`character_strategy.py`](character_strategy.py) | 候选动作评分、角色策略和卡牌/遗物选择。 |
| [`character_profiles.py`](character_profiles.py)、[`character_rotation.py`](character_rotation.py) | Vivhite/Ironclad Profile、严格轮换、追赶和在线 checkpoint。 |
| [`knowledge.py`](knowledge.py)、[`native_knowledge.py`](native_knowledge.py) | 持久统计、局档、原生游戏知识快照和原子写入。 |
| [`runner.py`](runner.py)、[`review_runners.py`](review_runners.py)、[`llm_review.py`](llm_review.py) | Brain 子进程监督、复盘模型链、失败包、回滚和局间热重载。 |
| [`lifecycle.py`](lifecycle.py)、[`manual_control.py`](manual_control.py) | session/runtime 路径、停止协议和全局人工接管闸门。 |
| [`live_dashboard.py`](live_dashboard.py)、[`dashboard_launcher.py`](dashboard_launcher.py) | ASCEND-VISION 本地驾驶舱与确定性决策遥测。 |
| [`window_layers.py`](window_layers.py)、[`broadcast_window_patrol.py`](broadcast_window_patrol.py) | 窗口层级维护；游戏窗口只在直播姬确认为 `Streaming` 时巡检。 |

## 启动方式

完整训练请从仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-Agent.ps1
```

开发者若需要直接调试 Brain（这会进入 Agent 主循环，可能连接并操作游戏），可从 `sts2-ascend/` 执行；只想做静态自检时请只运行第二条：

```powershell
py -3 -m brain
py -3 brain\selfcheck.py
```

直接启动不会替代统一脚本的部署、Steam 云空间检查、session 锁、runner 握手和残留进程校验，因此不应作为无人值守入口。配置快照在 [`config.json`](config.json)：端口、轮询间隔、复盘链、TTS owner 和 Vulkan 启动路径都应通过脚本/配置变更，不要写入密钥。

## API 与“真实游玩”证据

Brain 会在端口池中发现第一个健康 Agent，并按状态驱动循环：

```text
health ready → state/available_actions → policy candidate → final action gate
       ↑                                                ↓
       └──────────── applied/rejected 回执与状态推进 ────┘
```

`applied` 动作回执、递增 `state_version`、非 `MAIN_MENU` 的 `run` 和驾驶舱 `connected` 心跳共同构成训练/直播可用证据。看到 `MAIN_MENU/run_unknown` 时应停止动作和直播判断，读取日志与原生 Continue 证据；不能用 dashboard 心跳、缓存或“Stack ready”替代实际对局。

## 学习与复盘

每个角色有独立 Profile；rotation 记录局号、active slot 和 catch-up/1:1 轮换。对局证据先写 `runs/` 与 `in_progress`，原生终局和存档确认后才 finalize；人工接管、不可恢复孤儿局和不完整终局不会增加胜率、楼层或策略配额。

复盘模型由配置驱动的 OpenCode/Kimi → Codex/Luna 链处理，Luna 是新任务的最低优先级兜底；GLM 与 DeepSeek 当前在静态配置中禁用。模型开始工作后通常保持 runner/model/variant/审批/sandbox 亲和性；若某后端被静态配置明确禁用，机制保留失败包证据并把旧重试事务迁移到仍启用的后端。失败包和拒合现场写入 `knowledge/code_backups/`，由机制重新投递，不由维护者手工代写策略。自动 Git 事务统一使用 `[brain:auto]` 前缀，维护性改动使用 `[agent:task]`。

## 停止与人工接管

```powershell
# 停止 Brain、runner、播报/复盘链并请求游戏退出
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1

# 只停智能体与播报链，保留游戏窗口
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1 -KeepGame
```

停止先写 session sentinel，给组件保存知识的协作窗口，再按 PID、创建时间、可执行文件、命令行和工作区精确兜底。不要用 `taskkill /IM python*`、端口批量杀进程或直接删除 `.runtime`。

## 离线测试

从仓库根目录运行：

```powershell
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_*.py"
```

详见 [`../tests/README.md`](../tests/README.md)。修改 runner、lifecycle、review 或持久化协议时，至少补跑对应定向测试和一次完整发现测试；实机异常还需保存 `/state`、`/actions/available`、session 与日志证据。

## 故障定位

| 症状 | 先看什么 | 安全动作 |
| --- | --- | --- |
| API `MAIN_MENU/run_unknown` | `/state`、`/actions/available`、游戏日志、原生 Continue | 保持动作/直播关闭，等待权威存档证据；不要强开新局。 |
| Brain 反复重启 | `runner` 启动握手、review marker、失败包 | 让 runner 在预算内回滚/保全；不要手改 marker。 |
| 统计或局号异常 | 对应 Profile 的 checkpoint 与 `character_rotation` 审计 | 停止后按专项恢复工具处理，不直接改 `knowledge`。 |
| TTS 没声音 | owner epoch、17952 `/health`、GPU/Edge 日志 | 维持游戏动作链独立运行，按 [`../tts/README.md`](../tts/README.md) 诊断。 |
| 训练没有新动作 | `connected`、最近 `applied`、state_version 是否推进 | 进入修复/复核循环；不能把“进程存活”当成训练完成。 |

更高层的启动、部署、轮换和发布说明见 [`../README.md`](../README.md)。
