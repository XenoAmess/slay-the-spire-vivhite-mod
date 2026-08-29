# sts2-ascend Luna 旧重试执行契约迁移

日期：2026-08-30

## 现场与根因

Luna 的 Codex 路由应使用 `--approve-for-me`（该参数自身启用 `workspace-write`，不得同时传显式
`--sandbox`），但在线队列中仍有
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

交叉监控 Kimi 时还发现 generic prompt 把隔离仓缺省提交身份硬编码为 `sts2-review-luna`，因此 Kimi
也会按 Luna 名义创建本地提交。宿主最终 CAS 提交不继承该作者，故它不是提交失败原因，但会继续制造
归因噪声；已改为中性 `sts2-review-agent`，并用 prompt 回归断言禁止重新出现模型专属硬编码。

## 旧失败包证据预检的第二处阻断

Brain 热加载执行许可修复后，98 个旧 Luna 项都已自动刷新为 `approve_for_me=true`，但 runs
1014–1085 的首个重试仍没有启动 Codex。根因是目标失败包
`20260829-225316-1788015196791448300-ab40e708` 只保存了旧 schema 1 现场：`wip.patch`、
`report.md` 和 `files/` 全空，`file_states.json=[]`，却没有后来新增的 schema 3
`retry_candidate.patch` 与 inventory。宿主在 provider 启动前正确拒绝了不完整证据，却又把内部
`rc=-1` 继续当作 Luna provider 失败，错误地执行了五分钟冷却、解除 sticky affinity，并增加
`retry_count`。调度器随后选中 Kimi，因此界面看起来像“Luna 又失败、Kimi 接手”，实际上 Luna
进程从未创建。

修复分成两个最小闭环：

- 仅当旧包的完整快照、空 patch 大小与 SHA-256、全部空路径分类、空 `file_states.json`、空
  `files/` 目录和非 deferred 状态同时一致时，认证为 `legacy_certified_empty`，生成真实的 0 字节
  schema 3 candidate 和 inventory。独立反例复核还要求规范 `pre_head`、正常 `report.md`、
  `snapshot_included/raw_sandbox_included=false`，并拒绝任何遗留 `captured_snapshot/raw_sandbox`；缺字段、
  非空旁证或任一标志不一致都保持拒绝。不会把任意 `wip.patch` 当作候选。
- 认证结果只表示“旧模型没有代码候选”。原始 prompt 与 raw clone 均明确记录为
  `unavailable_not_fabricated`，下一轮由当前队列与 corpus 生成新任务，绝不伪造旧现场。
- 失败包证据预检未通过且 provider 尚未启动时，外层状态改为
  `outcome=deferred` / `deferred_kind=replay_evidence_preflight`，立即返回；不保存新失败包、不冷却
  backend、不解绑 Luna、不增加 retry 次数。真实 provider 已启动后的非零退出仍按模型失败处理。

## 第二轮验证

- 精准新增回归覆盖 certified-empty 成功迁移、七类 near-miss 拒绝、迁移后 mount/verify、预检延期、
  已启动 provider 失败负控，以及 deferred 后 Luna 计划、retry count 和 attempt lineage 不变。
- 组合相关测试 102 项曾在正常负载下全部通过；维护会话与在线 Kimi 并行高负载复跑时，唯一一次失败
  是既有 wall-clock 测试耗时 `2.049s > 2.0s`，该单测立即复跑为 `1.133s` 并通过，新增五项精准
  回归为 5/5。不得为这次无关的负载抖动放宽超时门槛。
- 真实失败包的副本已完成 `legacy_certified_empty -> schema 3`。首次 mount smoke test 虽把模块的
  临时物化路径指向副本，却漏改 `_salvage_package_path()` 实际使用的 `SALVAGE_ROOT`；mount 阶段因而
  又按包名解析到了生产失败包，并在 02:25 将它物化为同样的 0 字节、0 路径 schema 3 证据。原始
  `wip.patch`、报告、文件快照和模型输出均未覆盖或删除，新增 candidate/inventory 与 manifest 迁移
  字段已保留；该包逐项满足补强后的 certified-empty 条件。后续临时验收必须同时隔离
  `SALVAGE_ROOT`，不能只覆盖一个无效的别名。
- 最终仍以热加载后 Luna 自己完成 provider 启动、工具调用、代码落地、自检、本地提交、宿主 CAS
  与推送作为验收终点。

## 第三轮纠正：自动批准契约终止

上文记录的 `approve_for_me=true` 是当时针对无人值守工具阻断的历史结论，现已被第二次生产事故的
直接证据推翻：Luna 在隔离 clone 内运行时，一次原生文件修改事件同时写入了 clone 文件和真实仓的
绝对路径文件。`cwd` 与 `-C` 只能约束相对路径解析，`--approve-for-me` 还会自动批准越出 clone 的
写入，因此该执行契约已终止，不得再作为旧重试恢复目标。

sticky execution-approval refresh 现在明确是**双向迁移**，而不是只把 `false` 提升为 `true`：只有
`backend key + runner + model + variant + reasoning effort + sandbox` 精确匹配当前 backend identity
时，才把旧计划中的值刷新为当前配置；Luna 当前会执行 `true -> false`。worker 与直接恢复路径都必须
先将刷新结果耐久保存，保存失败则延期且不得启动 provider，避免重启后从旧 marker 重新带回自动批准。

命令构造器还提供独立于旧快照的最终约束：即使历史 marker 或配置仍携带
`approve_for_me=true`，实际 Luna 命令仍强制使用 `-a never`、`--ignore-user-config` 和内联
`luna_commit` custom permission profile，不再生成 `--approve-for-me`。因此旧重试不能通过陈旧布尔值
恢复自动批准，也不能继承用户级 trusted-workspace 配置。

计划中的 `sandbox=workspace-write` 仍保留，作为 backend 路由、亲和性比较和旧计划兼容所需的语义
配置；它不再直接映射为命令行 `--sandbox`。实际命令不得混入 `--sandbox`，因为写边界由内联 custom
profile 负责：沿用 workspace 读写边界，并仅为隔离 clone 自身的 `.git` 开放写权限，使 Luna 可以
自行提交，同时不把真实仓纳入可写范围。

当前代码、命令解析和无模型边界 canary 已验证；生产重放仍须按既有终点观察 Luna 自己完成证据读取、
修改、自检、clone 提交、宿主 CAS 与推送。在该整条链路完成前，本轮状态记为“生产重放闭环待验证”。
