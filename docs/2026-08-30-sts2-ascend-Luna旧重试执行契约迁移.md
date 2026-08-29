# sts2-ascend Luna 旧重试执行契约迁移

日期：2026-08-30

## 现场与根因

Luna 的 Codex 路由已改为 `--approve-for-me --sandbox workspace-write`，但在线队列中仍有
98 个早期失败后形成的 sticky 重试项。这些任务把 `approve_for_me=false` 与模型身份一起固化；
原实现遇到 sticky 批次会直接从队列恢复完整 `ReviewPlan`，不会采用当前配置。因此仅修改
`brain/config.json` 仍不足以恢复旧任务，它们下一次启动时不会携带 `--approve-for-me`，可能重复
已经实证的无人值守工具阻断。

这不是 Luna 的策略或服从性问题，而是宿主把“模型重试亲和性”和“执行权限契约”混成了同一个
不可变快照。不能通过手工改 `knowledge/review_queue.json` 处理，因为在线队列由生命周期机制维护，
而且后续从失败 manifest 恢复时还会重新带回旧值。

## 修复原则

- sticky 重试继续冻结 `backend key + runner + model + variant + reasoning effort`，失败现场不换模型。
- 只有当前配置中存在 `backend key + runner + model + variant + reasoning effort + sandbox` 的
  唯一精确匹配时，启动前才刷新 `approve_for_me`；权限不能跨 sandbox 借用。
- `sandbox`、批次频率、优先级和失败 lineage 均不随这次修复变化；当前故障没有证据要求扩大迁移范围。
- worker 在持有队列锁时、scheduler 做 affinity 比较前刷新整个 pending 队列，使同一 replay group
  中的新旧布尔快照先归一化，并立即耐久保存；保存失败就不选批、不启动 provider。
- `_run_batch_review` 仍保留第二层刷新，用于 reviewing、恢复或直接调用路径；该层刷新后的元数据
  必须先耐久落盘，失败则返回 `deferred`。
- 现场日志明确记录执行许可已按当前精确后端配置刷新，便于确认自动迁移实际发生。

## 回归验证

新增测试覆盖：

1. 真实 worker/scheduler 路径面对同一 Luna replay group 的 `false/true` 混合快照时，先统一为
   当前配置的 `true` 并保存，再允许选批。
2. backend key、model 或 sandbox 不同的配置项不能向旧任务“借”权限，也不能改变旧任务亲和性。
3. 权限刷新后若 reviewing 元数据写入失败，本轮必须延后，`run_review` 不得被调用。

`test_persistence_fail_closed.py` 单文件 68 项通过；与 runner、孤儿恢复、失败包保全相关的组合
回归共 129 项通过。修复不读取或改写 GLM 状态，也没有手工修改在线队列。

## 运维注意

下一次 Brain 加载该版本后，旧 Luna 任务首次出队时应先出现 execution approval refreshed 日志，
随后 Codex 命令应包含 `--approve-for-me` 且不包含 `-a never`。验收必须继续观察 Luna 自己完成读取、
修改、自检、本地提交、宿主 CAS 和推送，不能只以进程成功启动作为闭环完成。
