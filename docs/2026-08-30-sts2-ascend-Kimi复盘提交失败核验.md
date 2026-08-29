# sts2-ascend Kimi 复盘提交失败核验

日期：2026-08-30

## 结论

近期日志不支持“Kimi 大量复盘提交失败”的判断。当前实际 Kimi 路由是 K3；自 2026-08-28
起抽取到 17 个路由批次，其中 10 个在模型启动前被证据预检延后，真正启动 provider 的只有
7 个。7 个 provider 批次中：4 个成功，2 个因整套生命周期停止而结束，1 个在 K3 已完成修改
和自检后随旧 Brain 异常退出终止。

没有发现以下 Kimi 自身或提交链失败：

- provider 自身失败：0；
- selfcheck 失败：0；
- 隔离仓本地提交失败：0；
- 宿主验收/提交失败：0；
- compare-and-swap 失败：0；
- 永久 push 失败：0。

有一次 push 首次失败，但约 6 秒后自动重试成功，不能算最终提交失败。用户看到的近期失败记录
主要是模型启动前的 evidence preflight 和维护期 lifecycle stop；它们不应归因成 Kimi
“不会提交”。

## 为什么一度看起来是 Kimi 在工作

Luna 当时受到 Windows 宿主工具链故障影响：临时目录 DACL 阻断原生 Apply Patch、Codex
0.149.1 的普通盘符 no-follow 误判，以及 provider OS cwd 未绑定隔离 clone。路由和历史任务
在不同时间窗口显示 Kimi，并不代表 Kimi 抢走了一个已经健康运行的 Luna 批次。上述宿主问题
恢复后，Luna 已重新接管目标失败包并独立完成修改、自检、本地提交、宿主 CAS 与推送。

## 核验口径

提交失败必须按真实阶段区分：provider 是否启动、是否产生工作、selfcheck、隔离 commit、宿主
验收、worktree apply、CAS、push 首次尝试和最终结果。不能仅凭一条带有 `failed` 的批次状态、
维护停止或首次 push 错误就归因给模型。

本次按用户要求没有分析或修复 GLM；GLM 余额不足导致的失败保持原状，不纳入 Kimi/Luna
故障统计。
