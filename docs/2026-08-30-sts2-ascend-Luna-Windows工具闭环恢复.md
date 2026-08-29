# sts2-ascend Luna Windows 工具闭环恢复

日期：2026-08-30

## 结论

这轮 Luna 没有形成有效落地，并不是它拒绝修改策略，而是 Windows 宿主先后存在三层可复现的工具故障：

1. Python 3.14 通过 `tempfile.mkdtemp()` 创建的复盘沙箱根目录带有近似 `0700` 的保护性 DACL，Codex 原生 Apply Patch 所用的受限身份无法穿过该目录，报 `Access is denied (os error 5)`。
2. Codex CLI 0.149.1 的 Windows no-follow 文件读取会把普通盘符路径误报成 `path contains a reparse point`；C 盘、D 盘普通文件都可以复现，和 Luna 是否正确分析任务无关。
3. 切换到兼容 Codex CLI 0.148.0 后，宿主只把命令行 `-C` 绑定到隔离 clone，却仍以真实仓作为 provider 的 OS 进程 cwd；shell/Git 在 clone 中工作，但首轮原生 Apply Patch 的部分相对路径落进了真实仓，留下中间态并反过来阻塞宿主合入。

恢复原则是只修宿主运行器、能力预检、错误反馈和重试语义，让 Luna 继续在隔离仓中自行修改、复核、自检和提交；维护 AI 不代写或代合并 Luna 的策略成果。

## 故障一：临时目录 DACL 导致 Apply Patch `os error 5`

### 证据

同一份普通文件在继承父目录权限的目录中可以由原生 Apply Patch 读取和更新；放入 Python 3.14 `tempfile.mkdtemp()` 新建的沙箱根目录后，会稳定失败并返回：

```text
Access is denied (os error 5)
```

这类临时目录采用近似 POSIX `0700` 的保护性 DACL。Brain 所在用户可以创建 clone 和启动 provider，但 Codex 原生工具使用的受限身份没有可继承的目录访问权限，因此“shell 能读、Apply Patch 不能读写”并不矛盾。

### 修复

沙箱根目录创建后、clone 和 provider 启动前，Windows 路径立即执行精确的：

```powershell
icacls <sandbox-root> /reset
```

随后验证目录 ACE 已从父目录继承。这里不使用 `/T`，也不向 `Everyone` 或其他宽泛主体授予新权限；目标只是撤销 `mkdtemp()` 根目录的特殊保护 DACL，恢复项目既有的继承契约。

如果 ACL 修复或继承验证失败，运行器在 provider 启动前失败关闭，不让 Luna 消耗 token，也不把宿主权限故障算成 Luna 的策略失败。

## 故障二：Codex 0.149.1 把普通 Windows 盘符误判为 reparse point

### 证据

不调用模型、直接使用 Codex 0.149.1 `exec-server` 的 `fs/readFile`，并传入 `followSymlinks: false` 时，以下对象都会稳定返回 `path contains a reparse point`：

- D 盘普通文件；
- C 盘普通临时文件；
- Windows 自带的普通文件。

相同路径改为 `followSymlinks: true` 可以读取。源码中 Windows no-follow 实现通过 `NtCreateFile` 配合 `OBJ_DONT_REPARSE` 打开 `\\??\\<drive>:\\...` 路径；普通盘符本身需要经过对象管理器链接解析，因而被这一实现误伤。对应实现见 Codex 0.149.1 的 [`no_follow/windows.rs`](https://github.com/openai/codex/blob/rust-v0.149.1/codex-rs/exec-server/src/no_follow/windows.rs)。

该问题会让 Luna 已经完成分析、准备执行的原生 Apply Patch 在真正写入前失败。失败包中没有文件改动和 patch，并不能据此推断 Luna 没有行动意愿。

### 兼容路线

Windows 上为 Luna 固定使用非全局安装的 Codex CLI 0.148.0，不覆盖用户机器上的全局 Codex：

```text
%LOCALAPPDATA%\OpenAI\CodexCliCompat\0.148.0\...
```

兼容可执行文件的固定 SHA-256 为：

```text
2AD2CF8A732DA68B8F141634F92DB1A03016C5FAF533A7225FBC0FB740130410
```

0.148.0 先经过无模型资格验证：普通 C、D 盘文件读取成功，返回字节与源文件完全一致；原生 Apply Patch 的读写回读也成功。对照组 0.149.1 在相同普通盘符读取上稳定失败。因此这里是针对已发生故障的最小兼容固定，不是无证据的版本回退或安全边界扩张。

## 故障三：Codex 0.148 的 `-C` 与 provider cwd 出现分裂

### 失败包证据

第 1014~1085 局 Luna 复盘的失败包位于：

```text
sts2-ascend/knowledge/code_backups/review_salvage/20260830-052932-1788038972712769500-9be95113/
```

其中 `provider_events.jsonl` 给出了直接证据：

- 原生 Apply Patch 首次校验失败时，错误中的目标是**真实仓**绝对路径
  `D:\workspace\slay-the-spire-vivhite-mod\sts2-ascend\brain\policy.py`；
- 随后的 `item_56` 在同一次 native `file_change` 中同时列出真实仓的
  `brain/policy.py`、真实仓的 `brain/selfcheck.py`，以及隔离 clone 内的
  `brain/knowledge.py`；
- 后续 `item_62/64/69/72/83/90` 的修订路径都在隔离 clone 内，说明 Luna 已经发现并继续修正首轮中间实现；
- Luna 在 clone 中自行运行完整 selfcheck，结果为 `SELFCHECK OK`，随后建立本地 commit
  `cc2a4a582f0c47518d37ae15a26a933a37574085`；该 commit 不存在于真实仓对象库，符合无共享 Git 元数据的隔离契约。

失败包中的 `validated_candidate.patch` 是 Luna 后续自修并通过宿主验收的精确六文件候选，
SHA-256 为 `1c81ddb864e1bbce0c4c2a8d630a0503a5be89fe45ba7dbc9890858ec8b6cffc`；
`wip.patch` 保留全量工作现场，`manifest.json` 记录 `selfcheck_ok=true`、六个候选路径和最终宿主错误。

### 真实仓泄漏中间态与精确恢复

泄漏发生后，真实仓只有两个目标文件带有该轮 Luna 的首轮中间实现；index 仍指向 HEAD，
没有用户 staged 内容。恢复前签名如下：

| 文件 | HEAD / index blob | 泄漏 worktree blob | 内容差异 |
| --- | --- | --- | --- |
| `sts2-ascend/brain/policy.py` | `b340e7799fc3c9795c25c10bd301c93381275a8b` | `12f3ead928dc394b18841c3f8aa3dc287902bfed` | 13 增、1 删 |
| `sts2-ascend/brain/selfcheck.py` | `39af0fa45f7085952df45ca2f658bb8fa52ecd56` | `5c38e13f3d3d384e36d72277b8e5b66293c8dc64` | 57 增、0 删 |

这些 hunk 全部属于本轮 `LETHAL_SETTLE_EXTENSION`，没有夹杂用户或并发修改，但它们不是
最终候选的逐字子集：最终版又移动了 `_settle_lethal`、把致命延长收进既有 Boss 第三级
旋钮门内，并增加了缺失的 tier-3-off 回滚夹具。因而不能把真实仓中间态冒充 Luna 最终成果，
也不能在其上盲目重放原始 `--unidiff-zero` patch。

`pre_head=9be95113`、失败时 `current_head=ed03db1c` 以及诊断时主树 `3c397fe4` 的相关
HEAD blobs 完全相同。确认上述 worktree 哈希和 index 前置条件仍成立、且没有新 provider
写入目标后，宿主只恢复这两个已证明泄漏的文件：

```powershell
git restore --worktree --source=HEAD -- `
  sts2-ascend/brain/policy.py `
  sts2-ascend/brain/selfcheck.py
```

恢复后两个工作文件的 `git hash-object` 分别重新等于上述 HEAD blob，且
`git diff --quiet HEAD -- <两个路径>` 返回 0。该动作只是撤销宿主 cwd 故障造成的泄漏，
没有代写、代合并或审计 Luna 的最终策略成果；完整失败包仍交给 Luna 自己重做闭环。

### 为什么不是 Luna 失败，也不是 CAS 失败

宿主的 private-index 路径对同一候选执行：

```text
git apply --cached --check --unidiff-zero --binary validated_candidate.patch  => rc=0
git apply          --check --unidiff-zero --binary validated_candidate.patch  => rc=1
error: patch failed: sts2-ascend/brain/policy.py:2561
```

也就是说，基于当前 HEAD 的私有 index 能正常构造候选 tree/commit；失败发生在
`commit_patch_result` 对**真实工作树**执行 `git apply --check` 时，因为该处已经存在首轮
泄漏中间态。流程尚未进入 prepare、真实 worktree apply 或 `update-ref`，所以没有发生
compare-and-swap。历史 `commit_conflict` 只是“patch 存在且错误文本含冲突”的宽泛分类，
准确归因应为 `worktree_overlap_before_cas`，并明确 `cas_attempted=false`，不能算作 Luna
提交失败或 CAS 失败。

### provider cwd 双绑定修复

Codex 的 `-C <sandbox_repo>` 继续保留，用于约束 CLI workspace 以及 shell/Git；同时
`_stream_run` 增加显式 `cwd` 参数，`_run_review_sandbox` 启动 provider 时必须传
`cwd=sandbox_repo`，最终的 `subprocess.Popen` 也使用同一个隔离路径。两层绑定缺一不可：

```text
Codex 参数工作区：-C <sandbox_repo>
provider OS cwd：  cwd=<sandbox_repo>
```

无模型回归一方面让真实子进程输出 `os.getcwd()`，验证 `_stream_run` 的 cwd；另一方面在
`_run_review_sandbox` 集成测试中断言传给 `_stream_run` 的 cwd 与命令中的 sandbox 路径
相同。这样可以同时捕获“底层参数未生效”和“调用方忘记传 cwd”两类回归。

由于零上下文 patch 在已存在前缀内容时可能错误地再次插入，宿主不能把单纯
`git apply --check --unidiff-zero` 成功当成“部分内容已安全合并”。同 hunk 中间态应失败关闭；
若后续需要兼容完整已落地内容或同文件不相交用户 hunk，应先用私有 tree 做三方合并，
再只向真实工作树应用 worktree 到合并 tree 的 residual patch。

## 启动与 provider 前预检

`Start-Agent.ps1` 冷启动会调用 `scripts/Install-CodexCompat.ps1`，把固定版本安装或校验到用户缓存。安装器必须同时核对版本和 SHA-256；失败应明确终止该次就绪流程，不得静默改用全局 0.149.1，也不得把原批次切给 Kimi。

每次 Luna provider 启动前仍要重新执行三项本地检查：

1. 实际执行文件版本必须精确为 0.148.0；
2. 可执行文件 SHA-256 必须与固定值一致；
3. 使用隔离的临时 `CODEX_HOME` 启动 `exec-server`，以 `followSymlinks: false` 读取当前普通盘符上的探针文件，并逐字节验证返回内容。

这些检查都不调用模型。只有全部通过才启动 Luna provider；失败记录为 `runner_codex_nofollow_preflight`，任务保持 `deferred` 和 Luna sticky 亲和性，不增加模型冷却、重试计数或 token 消耗。冷启动安装负责“兼容程序存在且可信”，provider 前预检负责“这一次运行确实具备普通路径读取能力”，两层职责不能互相替代。

## 错误分类与反馈

为防止宿主故障再次被“没有有效改动”或 closure gate 覆盖，错误归因必须保留精确签名：

- `Access is denied (os error 5)` / `WinError 5`：稳定的沙箱 DACL 能力故障，交由宿主修复；
- `path contains a reparse point`：Codex Windows no-follow 路径能力故障，归为 `runner_tool_path_capability`；最终明确的 `BLOCKED_TOOL_CAPABILITY` 与该签名应覆盖较早出现的通用 Python traceback；
- provider 前版本、SHA 或读取探针失败：`runner_codex_nofollow_preflight`，不得启动 provider；
- provider 原生文件事件落到隔离 clone 之外：宿主工作目录接线故障，禁止继续把该现场当作隔离成果；
- private index 可构造候选、但真实工作树在 CAS 前与候选同 hunk 重叠：`worktree_overlap_before_cas`，并记录 `cas_attempted=false`；
- 只有不含永久权限签名的通用 `Failed to write file`，或明确的共享冲突，才允许 Luna 对同一最小 patch 做短暂、有界的原生 Apply Patch 重试；不得教它改用脚本重定向、进程管理或其他绕过路径。

这样 Luna 会收到可行动的反馈：模型自己的修改有问题时由它继续修；宿主未提供基本工具能力时立即停止并等待机制恢复，避免空耗额度或伪造“自检成功”。

## 生产验证状态

故障批次中，Luna 已经完成分析、原生 Apply Patch、自修、完整 selfcheck 和隔离仓本地
commit `cc2a4a58`。这证明 DACL 与 0.149.1 no-follow 两类前置阻断已经越过，也证明 Luna
有能力自行完成“修改—复核—自检—提交”；真正阻断落地的是宿主 provider cwd 泄漏以及
随后的 CAS 前真实工作树冲突。

精确恢复泄漏并加载 cwd 双绑定修复后，智能体已热重启到新 session `f268e9d1…`。
本次维护期间本地直播姬持续保持 `Streaming`，直播中断为 0 秒，满足开播后最多中断两分钟的硬性规则。

截至本文记录时，新 session 中 Luna 对该失败批次的重新审核、最终隔离仓 commit、宿主
deny-only 验收、private-index/CAS 合入与远端确认仍为**待最终验证**。在完整回执出现前，
不得宣称端到端重试已经完成，也不由维护 AI 接手代做 Luna 的策略改动。

## 经验与注意事项

- Windows 上“进程用户能访问”不等于 Codex 原生工具的受限身份能访问；临时目录权限必须用真实原生 Apply Patch 探针验证。
- 看到 `path contains a reparse point` 时，先用普通 C、D 盘文件做无模型对照，不能直接推断项目目录真的存在 junction、symlink 或污染 clone。
- 版本固定必须同时包含安装位置、精确版本、二进制 SHA 和能力探针；只检查 `codex --version` 不能证明文件工具可用。
- CLI 的 `-C` 与 OS 进程 cwd 是两条不同的工作目录契约；原生文件工具存在时必须同时绑定到隔离 clone，不能只验证 shell 的 `pwd`。
- `commit_conflict` 不等于 CAS 已执行；必须按 private index、worktree check/apply、prepare、update-ref 的真实阶段记录失败，避免把宿主泄漏错算成模型提交失败。
- provider 前失败必须保留原任务的 Luna 亲和性并做到零 token，不能用自动换模型掩盖 Luna 路由故障。
- 完整闭环的成功口径仍是 Luna 自己完成修改、diff 复核、自检和隔离仓提交，宿主再完成局部边界验收与 CAS 发布；单次 Apply Patch 成功只是必要条件，不是最终完成条件。
