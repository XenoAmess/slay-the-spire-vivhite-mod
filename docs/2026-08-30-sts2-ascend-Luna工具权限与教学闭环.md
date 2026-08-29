# sts2-ascend Luna 工具权限与教学闭环

日期：2026-08-30

## 问题与结论

Luna 在 2026-08-29 22:53、22:57 的两次失败不是“读完任务后只肯写报告”。两个失败包的
`model_output_tail.txt` 都显示，它先后尝试 PowerShell、cmd、bash、`rg` 和直接读取任务文件，
但所有 shell 都在 `CreateProcess` 阶段被 `blocked by policy` 拒绝，直接读取也返回
`Access is denied`。两次均没有成功命令、文件变化或 patch，模型还明确说明自己尚未读到任务书。

根因是生产 Luna 被改成了：

```text
codex -a never exec ... --sandbox workspace-write
```

在当前非交互 Codex CLI 中，`-a never` 没有人工审批者可接管请求，因此连只读 shell 都被拒绝。
宿主又没有识别 Codex 工具路由层的非 JSON 错误，最终让“纯报告闭环闸门”覆盖了真正原因。

## 受控能力探针

在独立临时目录中用同一 `gpt-5.6-luna` 做了三个最小探针，不触碰策略或在线知识：

| 路由 | 只读 shell | 原生 Apply Patch | 结论 |
| --- | --- | --- | --- |
| `-a never --sandbox workspace-write` | `blocked by policy` | 未形成有效写入 | 不可用于无人值守复盘 |
| `-a on-request --sandbox workspace-write` | `blocked by policy` | 未继续 | 非交互进程没有人工审批者 |
| `--approve-for-me`（自身启用 `workspace-write`） | 成功 | 成功，且 shell 回读为新值 | 当前可用生产路由 |

因此恢复 Luna 的 `approve_for_me=true`；该参数自身启用 `workspace-write`，不得再同时传显式
`--sandbox`。这次不是猜测回退；
读、写和回读能力均已由真实 Luna 探针验证。

## 机制修复

1. `review_runners.py`
   - Luna 使用 `--approve-for-me`（其自身提供 `workspace-write`），不再注入 `-a never`，也不再追加与它互斥的显式 `--sandbox`。
   - Codex 翻译器单独统计 `blocked_tool_count`，保留有界 `tool_access_error`，并把工具路由层
     的 `blocked by policy` / 工具语境 `Access denied` 计入错误。
2. `llm_review.py`
   - 工具被阻断且没有成果时写入 `runner_tool_access_denied`，在纯报告闭环闸门之前终止归因。
   - `selfcheck_ok` 改为三态：`passed`、`failed`、`not_run`；零改动不再伪装成自检通过。
   - 每个普通失败包保存完整 `review_prompt.md`、命令行短契约、字节数与 SHA-256，便于精确复盘。
   - replay 首屏加入结构化失败反馈，旧失败包也会从原始输出推断工具阻断，不再让 Luna 猜上次
     为什么被拒。
3. 教学契约
   - 命令行短提示直接给出目标、操作授权、成功标准和 `BLOCKED_TOOL_CAPABILITY` 停止条件；即使
     完整任务书读取失败，也不会退化为“空报告”。
   - 完整任务改为：工具与最小证据 → 可证伪假设 → 最小生产改动 → selfcheck 失败即继续修 →
     回读 diff → 最后写报告 → Luna 在隔离 clone 内自行提交并返回 SHA。
   - replay 的 `no_valid_change` 只允许在完整 lineage 已读且有当前 HEAD 可核验证据时使用；
     `still_pending` 只表示证据未完成，不能代替工具故障或行动。
   - Luna 可以在无 remote 的隔离 clone 内使用 `git status/diff/add/commit`、自行解决冲突；禁止
     push。宿主只做 deny-only 验收和私有 index/CAS 发布，不代写、改写或盲套策略成果。

## 验证与注意事项

- runner、闭环、失败包、失败证据挂载、孤儿 clone 恢复、持久化 fail-closed 与 autogit 安全测试通过。
- `py -3 -B sts2-ascend/brain/selfcheck.py` 输出 `SELFCHECK OK`。
- 测试曾发现一次辅助函数被补丁插入到孤儿恢复函数中段；孤儿恢复测试立即暴露该问题。函数已移回
  闭环分类区并重跑测试通过。这说明涉及长文件时不能只依赖语法检查，必须覆盖邻接生命周期测试。
- 本次没有分析或修改 GLM；余额耗尽仍按用户要求允许它自然失败。
- 完整 packet 是证据载体，不能为“提示更短”随意截断；精简重点放在不重复的行动规则、置顶反馈和
  按需读取，而不是丢掉 100 局队列或失败 lineage 的证据。

官方 GPT-5.6 指导强调提示应清晰给出本地行动授权、证据、成功标准与停止条件，并避免重复规则；
Codex sandbox 文档则说明 `workspace-write` 负责工作区写权限，审批策略负责命令能否获准。此次修复按
这两条职责重新对齐生产配置。

## Kimi 近期“提交失败”交叉审计

用户看到的近期两条 Kimi 拒合记录并不是提交失败，而是同一个 run 1086 lineage 在 23:14:22、
23:28:54 两次被统一全栈停止打断。两次都记录为 `lifecycle_stop`，宿主尚未进入 selfcheck、CAS、
commit 或 push；旧实现把未运行的 `selfcheck_ok` 默认成 `true`，进一步放大了误解。第三次没有再被
打断后，Kimi 自行读取保全现场、完成四个文件的修改与自检，宿主成功生成提交 `ac26841f`。首次
push 因本机 GitHub 代理短暂断连失败，约六秒后自动补推成功，远端已确认包含该提交。

历史上 Kimi 确有 2026-08-26 至 2026-08-27 的 OpenCode/K3 静默 `exit=1`：模型未产生输出、patch
或报告；但 2026-08-28 以后没有新的 Kimi 自检失败、CAS 冲突、路径拒绝或永久推送失败。当前误导
主要来自观测层把任意模型都硬编码写成“GLM”，并把维护中断与真实模型失败并列展示。修复原则是：

- 新失败包、重试和有可靠回执的闭环使用实际 backend/model，不再用固定模型名；历史闭环或崩溃恢复
  缺少执行者回执时使用中性“复盘已闭环 / 执行后端未记录”，不得拿原失败模型猜补合执行者；
- `lifecycle_stop` 明确标为维护中断/取消，不称为模型提交失败；
- `selfcheck` 未执行时保持 `not_run`，不得显示为通过；
- 是否成功以宿主验收、CAS、commit 和远端确认分别记录，短暂 push 重试不得冒充永久提交失败。

账本使用 `review-rejection-ledger-schema:2` 做一次性历史迁移：marker 缺失时，中性化旧 `GLM`
闭环文案以及曾被旧迁移误写成“原失败模型已补合”的状态；marker 写入后不再改写未来带可靠 resolver
回执的精确状态。迁移回归测试必须把 `REJECTION_LEDGER`、`REPO_DIR` 和 autogit 全部隔离到临时
现场。此次曾因 `ReviewQueueSafetyTests` 只隔离 queue/salvage 而漏掉真实 ledger，测试意外生成提交
`ec692ae8`；现已加入临时账本与 autogit fail-fast，防止测试再次提交或推送真实仓。

## 03:02 生产回归：正确 probe 被错误转录

新 Brain 于 03:02 首次真正选中 Luna 后，Codex 0.149.1 在模型启动前直接以 `exit=2` 拒绝命令：

```text
error: the argument '--approve-for-me' cannot be used with '--sandbox <SANDBOX_MODE>'
```

现场的 event、tool、command、file change 均为 0，`model_work_started=false`。这不是 Luna 不执行，
而是宿主同时传入了互斥参数。回查原始能力 probe 后确认：成功的只读和写入 probe 实际都只传了
`--approve-for-me`；该参数自身启用 `workspace-write`。随后维护文档把它错误转录成
`--approve-for-me --sandbox workspace-write`，提交 `b1e2656b` 又依据错误文字，把此前正确的互斥
分支改成了两者同传。

第二次修正分成两个独立提交：

- `3d59370c`：`approve_for_me=true` 时只传 `--approve-for-me`，并校验配置中的语义沙箱仍为
  `workspace-write`；非自动审批路径才显式传 `--sandbox`。生产 runner 与模型评估器现在遵循同一
  参数契约，回归必须断言命令中不存在第二个 `--sandbox`。
- `07750744`：精确识别 Codex 的四行本地参数冲突、`rc=2`、零模型/工具/文件活动组合，记为
  `runner_cli_preflight`。仍按进程失败规则保全完整隔离现场并更新拒合审计，但状态为 `deferred`：
  不冷却 Luna、不增加 `retry_count`、不解除原模型亲和性，只延迟 60 秒。`LIVE-END` 同时发布
  `deferred_kind`、`failure_code` 和 `provider_work_started=false`；普通 `exit=0` 在宿主 CAS 前不会
  被默认的 `failed` 状态误报。

精确测试直接使用生产失败包的四行原始输出；普通 `rc=2`、provider 已开始工作、有路径或工具活动、
非 Codex runner、或任何不完全匹配的输出仍走原失败链。相关组合回归 104 项通过，runner/评估命令
回归 49 项通过，`selfcheck` 为 `SELFCHECK OK`。受旧 bug 影响而变成 non-sticky 的 26 条任务无需
手工修改在线队列：冷却清空后，现有 fresh-plan 事务会在 provider 启动前按当前唯一首选身份重新绑定
Luna，并先耐久写回 `retry_same_model=true`；贯通测试覆盖了完整 26 条 lineage。

## Kimi 当前闭环复核

第 1098～1110 局这轮 Kimi 并未提交失败。它在隔离仓完成 `SELFCHECK OK` 和本地提交
`b79ca28a`，随后 Codex/OpenCode CLI 用约六分钟生成最终答复；宿主在 stdout EOF 后才执行私有
index、deny-only 分类、自检与 CAS，最终提交并推送 `dce57b1d`。六分钟低于现有 15 分钟告警、
30 分钟 stall 自愈阈值，因此属于大上下文收尾延迟，不是 Git 卡住。03:02 的自然热重启把该成果和
此前 Luna 修复一起加载：Brain 不就绪约 4.98 秒，8080 health 与 Bilibili `Streaming` 全程保持，
直播中断为 0 秒。

本轮仍不分析或修复 GLM；它因余额不足产生的失败按用户要求保留原行为。
