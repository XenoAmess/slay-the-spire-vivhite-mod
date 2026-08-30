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

### 端到端重试最终回执

新 session 中，Luna 没有沿用维护 AI 的策略判断，而是重新阅读第 808～812 局证据，先否决了
与当前 HEAD 重复的 Boss 血池方案，再提出“奖励选牌后的有效爆发增量缺少生产观测”这一可证伪
假设。它自行完成了以下闭环：

1. 原生 Apply Patch 第一次因上下文不匹配失败后，重新读取精确上下文并成功修改隔离仓；
2. 修改 `knowledge.py`、`policy.py`、`selfcheck.py` 及本批复盘记录，只增加
   `CARD_BURST_PICK_AUDIT` 观测，不改变评分、阈值、探索或动作选择；
3. 自行运行完整 `selfcheck.py`，结果为 `SELFCHECK OK`；
4. 自行执行 diff 复核、`git diff --check` 和精确 `git add --`，没有把宿主挂载的
   `.review_evidence/` 纳入提交；
5. 在隔离仓建立本地 commit
   `ddae78e1098b32ce0c0cb477b5dbc7818aacc26b`（6 files，92 additions，1 deletion）。

provider 随后以 `exit=0`、`timeout=false`、`stalled=false`、`stopped=false`、
`conclusion_ready=true` 自然结束。宿主完成 deny-only 验收与 private-index/CAS 后，发布为真实仓
commit `79b8b720aa643f010aaabf809af3ab4e684e569b`，回执 `pushed=True`；远端
`master` 后续提交仍以该 commit 为祖先。原重试目标
`20260827-215023-1787838623754163300-cd0aa644` 被 Luna 自己重新审核并解析为
`integrated`，待处理列表归零。

这次结果证明故障修复后的 Luna 已能独立完成“证据分析—证伪—修改—复核—自检—隔离提交”，
宿主也能完成验收、CAS 与推送。维护 AI 只修复和监控宿主机制，没有代写或代合并本批策略成果。

## 失败证据递归膨胀及宿主修复

一次为遵守直播维护死线而停止复盘时，生命周期失败包正确保留了隔离仓内完整现场，其中也包含
宿主只读挂载的 `sts2-ascend/.review_evidence/failed_review/`。旧的重试物化器随后用私有 index
执行全量 `git add --all --force -- .`，把这份宿主证据再次当作模型改动写入候选；下一轮挂载又
复制该候选，造成路径数和字节数递归增长，现场从约 51 MB 放大到约 155 MB。

修复只作用于宿主提供的精确证据根，不改变通用静态项目路径分类，也不限制 Luna 修改任何安全的
源码、配置、脚本、测试或文档：

- 私有 index 在首次哈希前用 Git exclude pathspec 排除精确宿主证据根；
- raw staged index、HEAD/local ref、stash 与 stash-untracked 的路径都在进入候选分类前执行同一
  精确过滤；
- 旧 schema 3 候选会重物化一次，保留旧候选摘要和历史，原失败包及 raw sandbox 始终不删除；
- captured-files 挂载改为 top-down 目录遍历，在精确证据根进入下降队列前剪枝，不枚举、排序或
  复制其 payload；只读取该根 `index.json`，记录 bytes、SHA-256、总字节、文件/路径数、
  package lineage 和原始保全位置；
- 该证据仍可被 Luna 阅读和引用，但不会再被当成 Luna 自己的候选成果递归回灌。

定向回归覆盖 raw staged index、local ref、stash、stash-untracked、captured 根剪枝、index
摘要、legacy certified-empty 与 no-raw 分支；相关最小集合 80/80 通过。更广的复盘、持久化、
salvage、closure、runner 与 autogit 回归结果记录在本次最终运行回执中。

## 经验与注意事项

- Windows 上“进程用户能访问”不等于 Codex 原生工具的受限身份能访问；临时目录权限必须用真实原生 Apply Patch 探针验证。
- 看到 `path contains a reparse point` 时，先用普通 C、D 盘文件做无模型对照，不能直接推断项目目录真的存在 junction、symlink 或污染 clone。
- 版本固定必须同时包含安装位置、精确版本、二进制 SHA 和能力探针；只检查 `codex --version` 不能证明文件工具可用。
- CLI 的 `-C` 与 OS 进程 cwd 是两条不同的工作目录契约；原生文件工具存在时必须同时绑定到隔离 clone，不能只验证 shell 的 `pwd`。
- `commit_conflict` 不等于 CAS 已执行；必须按 private index、worktree check/apply、prepare、update-ref 的真实阶段记录失败，避免把宿主泄漏错算成模型提交失败。
- provider 前失败必须保留原任务的 Luna 亲和性并做到零 token，不能用自动换模型掩盖 Luna 路由故障。
- 完整闭环的成功口径仍是 Luna 自己完成修改、diff 复核、自检和隔离仓提交，宿主再完成局部边界验收与 CAS 发布；单次 Apply Patch 成功只是必要条件，不是最终完成条件。

## 第二次绝对路径泄漏与宿主硬边界修复

> 状态纠正：本章记录上述闭环之后出现的第二份生产证据。前文关于 Luna 曾独立完成
> `CARD_BURST_PICK_AUDIT` 并由宿主发布的历史事实仍然成立；被新证据推翻的是“同时绑定
> provider cwd 与 `-C` 即足以构成写入硬边界”这一结论。cwd 与 `-C` 只能约束相对路径，不能
> 阻止原生文件工具按绝对路径写到 clone 外。

### 第二次事故证据与 Luna 行为判断

第二次事故的完整取证包为：

```text
20260830-065308-1788043988509458300-774f9f44
```

其中 Codex 0.148 原生事件 `item36` 在同一次 `file_change` 中混合报告了三个目标：真实仓的
`sts2-ascend/brain/policy.py`、真实仓的 `sts2-ascend/brain/selfcheck.py`，以及隔离 clone 的
`sts2-ascend/brain/knowledge.py`。三个写入几乎同时发生，且该事件之前的可见输出没有暴露这两个
真实仓绝对路径，说明仅靠事后阅读模型文字无法提前阻止这次外写。

Luna 首次在 clone 中运行 selfcheck 时，clone 实际只包含 `knowledge.py` 的修改，真实仓中的
`policy.py` 与 `selfcheck.py` 并未进入该次自检，因此形成了假阳性。随后 Luna 自己检查 diff，发现
clone 缺少后两处改动，并在 clone 中重新完成 `policy.py` 与 `selfcheck.py` 的修改。这一轨迹说明
Luna 的执行意图和自我纠正能力正常；失效的是宿主未把原生文件工具限制在隔离仓内，而不是 Luna
拒绝落地或把任务交给了别的模型。

事故发生后，先通过统一生命周期入口执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1 -KeepGame
```

该操作停止 Brain、runner、复盘和播报链，但保留游戏。宿主随后只对已由原生事件和逐 hunk 对照
证明为本次泄漏的两处真实仓改动使用精确 `apply_patch` 回退，没有执行宽泛的 Git restore、reset
或全仓清理。回退后分别比较工作树、HEAD 与 index blob，`policy.py`、`selfcheck.py` 的内容均重新
等同于 HEAD；完整事故包仍保留给 Luna 重试。该拒绝现场已通过独立审计提交记录：

```text
1682c3f3d045ec1be619967377de3242203eca56
```

### 根因：自动批准外写与继承用户信任配置

第二次证据表明，双工作目录绑定没有失效：provider 的 OS cwd 和命令行唯一 `-C` 都确实指向
clone。真正的缺口是命令仍使用 `--approve-for-me`；当原生工具提出 clone 外绝对路径写入时，
自动审查替 Luna 批准了这次操作。同时 Codex 继承用户级配置，而真实仓在该配置中属于 trusted
项目；clone 又位于真实项目目录下，用户配置参与了权限判断。两者共同使外写穿过了原本只用于
定位工作区的 cwd/`-C` 约束。

因此后发结论是：

- cwd 与 `-C` 仍须都绑定 clone，但二者只解决相对路径和 shell/Git 的工作目录；
- `--approve-for-me` 不能作为无人值守复盘的安全边界；
- provider 必须忽略用户级信任与权限配置，并由宿主为本次进程显式给出最小写入能力。

### 终态命令与 `luna_commit` 权限 profile

Luna provider 的终态命令契约为：

```text
codex -a never exec --model <model> \
  -c permissions.luna_commit={extends=":workspace",filesystem={":workspace_roots"={".git"="write"}},network={enabled=false}} \
  -c default_permissions="luna_commit" \
  --json --ephemeral --ignore-user-config --color never \
  -C <clone> <prompt>
```

命令中必须恰好有一个 `-C`，目标为本轮隔离 clone；不得再出现 `--sandbox`、
`--approve-for-me`、`--add-dir`、`--yolo` 或任何 bypass/danger 选项。`-a never` 禁止交互批准，
`--ignore-user-config` 排除用户 trusted 配置，`network=false` 关闭 sandbox 工具的网络能力（不影响
Codex 与模型服务的控制面通信）；内联
`luna_commit` profile 继承 Codex 的 `:workspace` 边界，只额外把当前 workspace 根下的 `.git`
开放为可写，使 Luna 能按照职责自行 `git add` 和 `git commit`。

这里不能直接使用普通 `workspace-write + -a never`：实测它会保护 clone 的 `.git`，创建
`.git/index.lock` 失败，`git add`/`git commit` 以退出码 128 结束，违背“Luna 自行提交”的闭环
要求。当前 Windows sandbox 后端上，内联 `luna_commit` 是既保留 workspace 写边界、又仅补回
clone-local Git 元数据写入的已验证方案；它没有收紧 Luna 对 clone 内安全静态项目文件的修改范围。

### 零模型硬边界 canary

固定 SHA 的 Codex CLI 0.148 在不调用模型、不访问网络的临时 clone 上完成了权限 canary：

- clone 内普通文件写入和移动均成功；
- clone 内 `git add` 与 `git commit` 成功，HEAD 推进到
  `ae73cf79dc86b70b1540073dbcd5d70e50e1f7b3`；
- 对 clone 外 sentinel 的直接写入被拒绝，文件字节和 mtime 均未变化；
- 把 clone 内文件移动到 clone 外也被拒绝，源文件和外部目标的字节、mtime 均保持不变。

该 canary 同时验证了两条必要能力：Luna 在 clone 内仍能修改并自行建立 commit，绝对路径写入和
跨边界移动则由 OS 权限 profile 阻断。它不发送 prompt，不启动 provider 模型，也不消耗模型额度。

### reported-path 熔断的准确职责

运行器另在 Codex JSONL 的 `item.started` 与 `item.completed` 阶段校验所有可见
`changes[].path`。一旦报告路径位于预期 clone 外或格式非法，运行器立即终止进程树，记录
`runner_tool_path_escape`，跳过 selfcheck、候选验收与提交，并完整保全 WIP。该检查是快速停机和
取证熔断，不是硬写入边界：Codex 0.148 的 JSONL 会丢失 `Update.move_path` 的目标路径，而且事件
可能在写入完成后才上报；真正阻止外写的是上述 OS `luna_commit` profile。

重放失败证据时，如果已挂载证据后触发该 reported-path 熔断，退出校验没有完整完成，则必须令
`replay_evidence_complete=false`，错误明确记录“reported-path 熔断后未完成退出校验”；
`retry_resolutions` 保持为空，不得把未完成验证的旧失败包误标成已合入、已跳过或空包。自检、证据
移除和解析发布在该分支均不可达。

### 直播恢复与当前生产门禁

维护期间本地直播姬在 `07:12:49` 从 `Streaming` 变为 `Idle`。按照开播后最多中断两分钟的硬性
规则，立即使用 Bilibili 统一开播入口恢复整套，直播在 `07:14:09` 回到 `Streaming`，中断约
80 秒，低于两分钟。统一入口完成了栈和直播恢复；脚本最后仅在把游戏窗口置顶时因当前桌面会话
不可用而失败，该错误发生在直播恢复之后，不影响已经恢复的 `Streaming` 状态。

为避免用未提交、未验证的宿主代码继续驱动生产 Luna，Brain 随后经统一生命周期入口暂停，游戏与
直播保留。第二次事故包必须在硬边界代码提交并重启后重新交给 Luna，由 Luna 自己复核证据、修改、
自检和建立 clone commit，再由宿主完成验收、CAS 与推送。截至本章记录时，这一轮生产闭环仍待
重启验证；不得把零模型 canary、reported-path 熔断测试或前一批次的成功回执冒充为该事故包已经
成功闭环。

### 生产重放暴露的 Apply Patch 路径教学缺口

硬边界提交并重启后，生产 Luna attempt `10760-1788047339964675900` 使用了终态命令契约：
provider 的命令行与 PEB cwd 都精确绑定隔离 clone，真实仓 `policy.py`、`selfcheck.py`、
`knowledge.py` 在启动前、运行中和退出后的 clean-filter、原始 SHA256、mtime 与长度均未变化。
这证明 OS 写边界在生产环境真实生效；但该 attempt 没有完成业务闭环。

Luna 已读取目标失败包、当前代码和证据，也形成了可证伪假设，但连续把原生 Apply Patch 的目标
构造成盘符绝对路径、重复 clone 根、`brain/knowledge.py` 缩写或其他错误锚点。结果是十余次
`writing outside of the project; rejected by user approval settings`，以及 `clone\clone\...`、
`clone\brain\...` 等不存在路径。相对 shell 读取 `sts2-ascend/...` 始终成功，`file_change_count=0`，
说明新证据不是权限 profile 阻止 Python/Git/普通 clone 内写入，而是宿主提示只说了“禁止绝对路径”，
没有教清原生 Apply Patch 的仓库根相对语法，也没有把 outside-project 与 generic 写入失败分开反馈。

为避免继续消耗额度，使用 `Stop-Agent.ps1 -KeepGame` 协作停止该 attempt。终态包
`20260830-080907-1788048547255004400-feaa36b2` 准确定性为 `lifecycle_stop`，不是 Luna 提交失败；
退出时完整证据校验尚未完成，因此没有发布任何 retry resolution，也没有 selfcheck、clone commit、
宿主 CAS 或策略成果。拒合审计本地 commit 为 `9c15ff1d`，由下一次正常启动补推。停止期间本地直播姬
始终保持 `Streaming`，游戏保留，没有发生直播中断。

宿主随后只修教学机制，不代写 Luna 的策略成果：长任务书与实际启动短提示现在复用同一个
Apply Patch 路径契约。契约明确每个目标必须从 `git rev-parse --show-toplevel` 所指的仓库根起算；
当前 cwd 与 `-C` 已在该根，不必用被命令策略拒绝的绝对路径探测。目标只使用以 `sts2-ascend/` 开头
的正斜杠相对路径，例如 `sts2-ascend/brain/knowledge.py`；禁止盘符、UNC、
重复 clone 根和 `brain/...` 缩写，`Get-Location` 输出不得拼进补丁路径。outside-project、
`<clone>\<clone>` 或找不到缩写目标被归类为路径构造错误：纠正为准确相对路径后只重试一次，仍失败
才报告 `BLOCKED_TOOL_CAPABILITY`，且不得改用 shell、脚本或重定向旁路写入。这样保留 Luna 自己
读证据、改代码、自检和提交的职责，同时把宿主已观察到的工具反馈教给下一轮。

静态验收包括 `test_review_closure.py` 22/22 通过，以及完整 `brain/selfcheck.py` 输出
`SELFCHECK OK`。下一道生产门禁仍是重启统一栈，让 Luna 对保留的失败 lineage 自己重新审核并产生
成功 Apply Patch、selfcheck、clone commit、宿主 CAS 和远端 push；在这些回执出现前，本章仍不把
该失败批次记为已闭环。
