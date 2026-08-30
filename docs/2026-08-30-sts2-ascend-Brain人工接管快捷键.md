# sts2-ascend Brain 人工接管快捷键

## 结果

Windows 全栈运行期间提供两枚系统级快捷键，即使杀戮尖塔2位于前台也可触发：

- `Ctrl+Alt+F9`：停止 Brain 发送游戏操作，把控制权交给玩家。
- `Ctrl+Alt+F10`：启动 Brain 自主操作，从当前界面或当前对局继续。

“停止”采用驻留暂停，而不是杀死 runner/Brain。全局热键监听由长期存活的 runner
持有，因此停手后仍然有组件能够接收恢复快捷键。每次切换播放一组降调/升调提示音；
ASCEND-VISION 顶栏会在暂停时显示 `HUMAN`，底栏显示恢复键。

该快捷键只负责运行中控制权切换。完整栈已经由 `Stop-Agent.ps1` 退出后，监听器也会
退出，不能用 `Ctrl+Alt+F10` 冷启动全栈；冷启动仍使用统一的 `Start-Agent.ps1`。

## 动作边界

runner 将当前模式原子写入 session 专属的
`.runtime/brain-control.<session_id>.json`。Brain 暂停期间仍可只读轮询 `/state`，
用于展示当前人工对局，但不执行 Profile 绑定、状态学习、策略评分或 `/action` POST。

停手机制有两层：

1. Agent 在每轮决策前和策略完成后检查控制状态。
2. `Sts2Client.act` 在所有游戏动作 POST 的最后边界再次检查。

因此快捷键生效后不会发送下一项操作。按键瞬间若已有一个请求被游戏接收，该项动作无法
撤销，但不会继续连发后续动作。控制文件缺失保持旧版自主运行语义；文件存在但损坏或不可读
时 fail-closed，Brain 停手而不是猜测可以操作。

## 学习与轮换隔离

暂停边界触及的当前局会标记为 `human_assisted`：

- 可以在恢复后让 Brain 接着打，但该混合局不增加角色总局数。
- 不更新平均楼层、最高楼层、胜率和局末策略参数。
- 不进入 LLM 复盘队列。
- 不消耗白绮/战士自动轮换配额；自动模式恢复后仍从原定槽位继续。
- 已有决策轨迹仅保留为 `in_progress + excluded_from_learning` 审计记录，现有楼层统计和
  LLM 数据包会自然排除它。

这避免玩家操作被误当成 Brain 水平，尤其不会污染白绮与战士的独立平衡样本。

## 实现要点与踩坑

- 热键监听不能放在被暂停或终止的 Brain 子进程中，否则“停止”之后没有组件能接收“启动”。
- Windows 使用 `RegisterHotKey`、`MOD_NOREPEAT` 和专用消息线程，不增加键盘钩子或第三方包。
- 控制状态必须按 session 隔离；新一轮统一 Start 默认自主运行，旧 session 的停手状态不能
  穿透到新进程（避免 ABA）。
- 只在策略循环加判断不足以可靠停手：按键可能发生在评分完成与 HTTP POST 之间，所以 API
  客户端必须保留最终硬闸门。
- 人工接管局不能调用正常 `record_terminal`：该接口的契约是角色统计已成功持久化。新增的
  `release_human_controlled_run` 只释放精确活动 run ID，不推进配额和 finalized ledger。

## 验证

定向测试覆盖控制文件原子切换、损坏状态停手、session 隔离、快捷键分发、客户端 POST
前硬闸门、Agent 暂停 epoch、人工局不进入统计，以及轮换槽位不推进。真机验收还应确认：

1. 游戏前台按 `Ctrl+Alt+F9` 后出现降调提示音，Brain 日志不再产生动作 POST。
2. 玩家至少执行一个手动操作，ASCEND-VISION 显示 `HUMAN`。
3. 按 `Ctrl+Alt+F10` 后出现升调提示音，Brain 从最新状态继续。
4. 该混合局终局后，角色总局数、真实楼层均值与轮换 index 均不因该局变化。

2026-08-30 真机验证已完成：后台 runner 成功注册两枚全局键；第一次停止将
`enabled=false / pause_generation=1`，Brain 在暂停观察窗口内没有产生新的决策动作；
恢复后立即从 F13 当前战斗继续出牌；第二次停止将
`enabled=false / pause_generation=2`。验收结束时保留第二次停止状态，游戏继续运行，
runner、Brain 与热键监听仍驻留。
