# sts2-ascend Brain 人工接管快捷键

## 结果

Windows 全栈运行期间提供两枚系统级快捷键，即使杀戮尖塔2位于前台也可触发：

- `Ctrl+Alt+F9`：停止 Brain 发送游戏操作，把控制权交给玩家。
- `Ctrl+Alt+F10`：恢复 Brain 自主操作，从当前界面或当前对局继续；若当前局已被 F9 触及，
  只恢复动作发送，不恢复该局的学习写入。

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

暂停边界触及的当前局会永久标记为 `human_assisted=true`、`excluded_from_learning=true`：

- F9 将所属 Profile 的在线 Knowledge `stats` 回滚到该局开始前的持久基线。卡牌出牌/候选、
  敌人战斗、事件选项、房间掉血、进幕快照和其他局内学习增量都会一并撤回。
- F10 可以让 Brain 从最新游戏状态继续操作，但同一局的所有在线学习写入口保持禁用；Brain
  重启、再次 F9/F10 或重连都不会把该局重新变成自动样本。下一局未被人工边界触及时才恢复学习。
- 整局已有及随后产生的增量决策/战斗轨迹继续以 `in_progress=true` 保留，并携带
  `human_assisted=true`、`excluded_from_learning=true` 作为审计证据；运行日志保留不等于学习保留。
- 该局不调用正常 `finalize_run`，不增加角色总局数或胜场，不更新平均楼层、最高楼层、近 20 局、
  终局卡牌/遗物/房间归因或该局的 policy/progression/lessons，也不进入 LLM 复盘队列。
- 该局不消耗白绮/战士自动轮换配额；`release_human_controlled_run` 只释放精确活动 run ID，
  自动模式恢复后仍从原定槽位继续。

这避免玩家操作被误当成 Brain 水平，尤其不会污染白绮与战士的独立平衡样本。

## 实现要点与踩坑

- 热键监听不能放在被暂停或终止的 Brain 子进程中，否则“停止”之后没有组件能接收“启动”。
- Windows 使用 `RegisterHotKey`、`MOD_NOREPEAT` 和专用消息线程，不增加键盘钩子或第三方包。
- 控制状态必须按 session 隔离；新一轮统一 Start 默认自主运行，旧 session 的停手状态不能
  穿透到新进程（避免 ABA）。
- 只在策略循环加判断不足以可靠停手：按键可能发生在评分完成与 HTTP POST 之间，所以 API
  客户端必须保留最终硬闸门。
- 每个 Profile 以 `.active_run_learning.json` 保存精确 run ID、局前 `stats` 基线和排除标记。
  F9 必须先持久化排除标记再恢复基线；若中途崩溃，下一进程按标记 fail-closed 地完成回滚。
- 所有在线 `commit_*` 写入口都检查该局排除状态；最终 `save()` 还会在持久化前恢复基线，防止
  遗留的直接统计写入穿透 F10。同一局结束前，F10 不能清除该持久排除状态。
- run 增量日志与学习统计是两条独立链：日志保留完整审计轨迹，Knowledge 回滚学习增量；知识库
  压缩和 catalog 必须继续携带 `human_assisted`、`excluded_from_learning`，避免归档后重新进入统计。
- 人工接管局不能调用正常 `record_terminal`：该接口的契约是角色统计已成功持久化。新增的
  `release_human_controlled_run` 只释放精确活动 run ID，不推进配额和 finalized ledger。

## 验证

本节描述的是已经实现的生产契约；本补丁只有在下列生产测试全部通过后才允许提交：

1. 在 F9 前分别写入卡牌、敌人、事件、房间及其他在线统计，F9 后所属 Profile 的完整 `stats`
   与局前持久基线深度相等，另一 Profile 不受影响。
2. F10 后 Brain 可以继续决策和发送动作，但同一局所有在线学习提交均为无效；停止或重启 Brain
   后仍恢复基线并保持该 run 排除。
3. 增量 run 日志继续追加并携带 `in_progress`、`human_assisted`、`excluded_from_learning`；压缩成
   catalog 后三个语义不丢失，楼层统计和 LLM 数据包仍排除该局。
4. 混合局终局后，总局数、胜场、真实楼层均值/最高/近 20、终局归因、policy/progression/lessons、
   LLM 队列和轮换 index 均不因该局变化。
5. 控制文件原子切换、损坏状态停手、session 隔离、快捷键分发、客户端 POST 前硬闸门和暂停 epoch
   回归继续通过。

真机验收还应确认：

1. 游戏前台按 `Ctrl+Alt+F9` 后出现降调提示音，Brain 日志不再产生动作 POST。
2. 玩家至少执行一个手动操作，ASCEND-VISION 显示 `HUMAN`。
3. 按 `Ctrl+Alt+F10` 后出现升调提示音，Brain 从最新状态继续。
4. 该混合局终局后，角色总局数、真实楼层均值与轮换 index 均不因该局变化。

2026-08-30 真机验证已完成：后台 runner 成功注册两枚全局键；第一次停止将
`enabled=false / pause_generation=1`，Brain 在暂停观察窗口内没有产生新的决策动作；
恢复后立即从 F13 当前战斗继续出牌；第二次停止将
`enabled=false / pause_generation=2`。验收结束时保留第二次停止状态，游戏继续运行，
runner、Brain 与热键监听仍驻留。

上述 2026-08-30 记录只验证控制权和动作闸门，不替代本节新增的 Knowledge 回滚、F10 同局禁学、
日志归档排除、终局统计和轮换隔离生产测试。
