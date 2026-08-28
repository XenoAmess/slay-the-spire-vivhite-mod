# sts2-ascend Codex/Luna 三级复盘链实装

## 目标与结论

复盘链从 OpenCode 双层模型选择扩展为 runner-aware 三级优先级：

1. OpenCode：`opencode-go/glm-5.3-flash@max`
2. Codex：`gpt-5.6-luna`，`reasoning=max`，`workspace-write`，auto-review
3. OpenCode：`kimi-for-coding/k3`

这不是简单替换模型名。宿主现在把 runner、模型、variant/reasoning、审批方式、sandbox、
优先级与批次间隔统一成 `ReviewPlan`，命令构造、输出翻译、失败包、队列恢复、冷却和生命周期
都使用同一份计划。旧版 `preferred_models + model` 配置继续兼容。

## 关键机制

- 可用性探测只运行本地 CLI：OpenCode 读取 `models`，Codex 检查 `login status` 和 bundled
  model catalog，不创建付费推理轮次。探测与正式 provider 都使用独立进程组；超时、整套 Stop
  或事件翻译异常时精确回收本次进程树。
- Codex 使用 `exec --json --ephemeral -C <隔离仓>`，stdin 关闭，避免后台任务等待交互输入。
  auto-review 由 `--approve-for-me` 明确启用，推理强度由 CLI config override 固定为 `max`。
- GLM 和 Luna 常规间隔均为一局；Kimi 常规新任务至少积累五个不同 run 才启动。失败包是独立
  取证事务，不受五局门槛阻塞，否则单局失败 target 可能永远无法闭环。
- provider 已产生模型正文、推理或工具事件后，失败包与重试队列会耐久保存完整亲和性，后续必须
  使用同 runner/model/variant/reasoning/审批/sandbox 重审。仅 CLI 在模型工作开始前不可用时，
  才允许按优先级交给下一层。
- provider JSONL 一边进入有界直播流，一边写入隔离仓 `.git`。模型失败时随 raw sandbox 保存；
  模型成功但宿主提交/CAS 后续失败时，JSONL 会先复制进宿主快照，manifest 指向失败包内真实文件，
  不再留下一个随 clone 删除而失效的路径。
- 性能观测从 CLI 真正启动前重新计时，记录首原始字节、首事件、首模型工作、总时长、原始 chunk
  数与最大无字节间隔。最后一段静默和全程零输出也计入最大间隔，便于区分模型慢、输出缓冲和真挂起。
- Start、Stop 与 Brain 启动期孤儿清理不写死 Luna、GLM 或审批参数，只匹配当前项目受管
  `review_work/sts2-review-sandbox-*/repo` 与 runner 的生产调用形状，避免配置升级后漏杀，也不碰
  用户自己运行的 Codex 会话和隔离评测 canary。

## 直播更新风险判断

代码编写、静态测试和隔离 canary 可以在直播中完成，不影响正在游玩的旧 Brain。生产激活必须等
当前复盘自然退出并完成宿主提交，随后只用统一 `Stop-Agent.ps1 -KeepGame` 与
`Start-Agent.ps1 -SkipDeploy` 热切换。这样不会中断当前 GLM 的隔离成果，也能把 Brain 断流控制在
两分钟内；不应为了验证新链先关 Brain 再长时间测试。

## 验证与踩坑

- `test_review_runners.py` 覆盖三级配置、旧配置、两种命令、两种 JSONL translator、畸形事件、
  fallback、Kimi 合批、失败包例外、进程树清理和 lifecycle 匹配。
- `test_persistence_fail_closed.py` 覆盖队列事务、完整 runner 亲和性、启动失败顺位 fallback、
  最新 attempt 绑定，以及 provider transcript 在失败包内的有效路径。
- 补合、失败证据只读挂载、hold 恢复、闭环闸门、健康 marker、决策链和路径分类测试继续通过。
- Windows `.CMD` 不是最终 provider 进程；对裸 `subprocess.run(timeout=...)` 只超时外壳会遗留
  Node/Codex 子进程。探测与正式执行都必须走进程树感知路径。
- translator 构造时间可能早于 clone；若不在 spawn 前重置时钟，首事件延迟会错误包含 clone 和证据
  挂载时间，无法用于 GLM/Luna 性能对照。

## 2026-08-28 上线实测

- 核心实现提交为 ced1c279，随后已由 Brain 的正常自动提交带到 origin/master；生产 Brain
  boot_head=d5623658，明确包含该提交并达到 stage=ready。
- 三个核心测试模块共 106 项通过；此前误放在 unittest.main() 后的三条死测试已移回 TestCase，
  并点名验证 clean EOF、pre-work fallback、OpenCode 生命周期匹配和杀软锁定 transcript 保全。
- hold 恢复/拒合清单重开 4 项通过，完整 brain/selfcheck.py 输出 SELFCHECK OK，Start/Stop
  PowerShell AST 均为 0 error。
- 保留游戏的统一热切总计 72.58 秒：旧代退出与精确兜底 64.99 秒，新代到 ready 7.59 秒；
  没有超过两分钟断流死线，也没有启动第二套 runner/Brain。
- 旧 Brain 曾三次在模型启动前复现 Codex 参数冲突：
  --sandbox <SANDBOX_MODE> cannot be used with --approve-for-me。新命令已改为二选一：
  auto-review 只传 --approve-for-me，非 auto-review 才显式传 --sandbox。合法的
  retry_candidate_bytes=0 也不再被 or -1 误判为证据缺失。
- 截至热切完成，三级链与 hold 账本恢复已在生产运行；Luna 多批实机质量/性能对照仍按独立冻结
  基线执行，未完成前不得把“CLI 可启动”写成“能力已经优于 GLM”。

三级链上线后的真实任务质量与性能对照另见同日 GLM/Luna 实机评审报告；原始评测证据保存在
ignored 的 `knowledge/code_backups/review_eval/`，不混入生产复盘队列。
