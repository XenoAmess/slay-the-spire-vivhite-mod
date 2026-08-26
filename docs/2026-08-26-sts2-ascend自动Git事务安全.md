# sts2-ascend 自动 Git 事务安全

## 问题与修复

原实现的线程锁只包围单条 Git 命令，`add`、`commit`、`push` 之间仍可交错；同时直接
使用真实 index，可能把调用前已暂存的用户文件带入自动提交。复盘失败和 runner 连续
崩溃还存在全仓强制回滚/清理，会覆盖与本次复盘无关的并发工作。

修复后的 `brain/autogit.py` 使用两层事务锁：进程内可重入锁，以及 Git 元数据目录中的
跨进程文件锁。一次自动存档从构造提交到 push 始终持锁。提交树在独立
`GIT_INDEX_FILE` 中从当时 HEAD 构造，不读取用户真实 index；目标路径若已有 staged
内容则整笔拒绝。分支以 `update-ref <new> <old>` compare-and-swap 更新，HEAD 发生并发
变化时从新基线重建，不能覆盖并发提交。事务还固定启动时的 symbolic-ref 身份并明确
更新该 ref；并发切换到相同 OID 的另一分支也会被拒绝，不能把提交写到错误分支。

`review_active.flag` 的进程探活在 Windows 使用 `OpenProcess` +
`GetExitCodeProcess`，不再调用会向目标进程发送信号的 `os.kill(pid, 0)`。锁等待与 push
都有有界超时；push 超时只记为“本地 commit 已建立、推送待重试”，不会把已经移动的
HEAD 误报成“未提交”。

普通对局默认只提交 runs、stats、progression、policy、lessons、review queue 和模型状态；
复盘期间进一步排除 policy/lessons，只保留纯在线运行文件。这样不会顺手提交知识目录中的
游戏快照、日志或 TTS 文件。LLM 复盘的可写路径是代码中的精确 allowlist，明确排除 autogit、runner、
llm_review、lifecycle、生命周期脚本以及在线 stats/progression。复盘提交只 stage 验证
通过的精确路径。目录匹配要求“完全相等或以 `目录/` 为边界”，`policy.py.evil` 之类前缀碰撞
不能借合法文件名越界。复盘活跃期间的在线进度 commit 会延后 push：push 可能更新本地远端
跟踪 ref，若在复盘指纹窗口内发生会造成无法归因的 ref 漂移；待复盘完成后的下一次普通事务
再推送线性历史。

## 隔离复盘与真实工作区防逃逸

模型不再直接修改生产工作树。每轮复盘从复盘前 commit 创建一个无 hardlink、无 remote
的临时独立 clone，命令的 `--dir` 被强制替换为 clone 根；提示词同时禁止绝对路径和
`..` 逃逸。模型结束后，系统丢弃其 HEAD/index 状态，全仓枚举 tracked 与非 ignored
untracked 变更，只接受精确 allowlist；自检也在 clone 内执行。allowlist 外变更立即拒绝，
ignored 写入只存在于临时 clone，不会进入生产 patch。可信 `selfcheck.py` 本身不在模型
allowlist，模型不能把验收程序改成恒定成功后夹带坏策略。

独立 clone 不是操作系统文件沙箱，因此运行模型前后还会对真实仓库的 index、全部
tracked/untracked 文件内容做逐文件哈希，并显式纳入 `.runtime` 和 pending marker 等关键
ignored 路径、third-party 构建/fork、code backups 与本机 `local.props`。指纹还包含
HEAD、symbolic ref、全部 refs、index flags、Git config/info-exclude/hooks；只允许当前分支
由确实改动在线路径的前向存档 commit 推进，空提交与历史改写均拒绝。只有 runs、stats、
progression 和运行日志等在线产物可排除。任何仓库根部
文件、代码、TTS 实现或关键 ignored 路径在这段时间发生变化，都会在应用 patch 前
fail closed：不合入、不清理、不覆盖，保留现场和诊断。这样也能发现模型使用绝对路径
逃逸，以及无法安全归因的外部并发编辑。

## 精确 patch、marker 与回滚语义

不再使用全仓强制重置或目录清理，也不从共享工作树的“总 diff”猜测哪些 hunk 属于模型。
隔离 clone 只导出经验证的二进制零上下文 patch；真实仓库用私有 index 应用它，并再次从
私有 index 的 staged diff 校验实际路径与声明完全一致。工作树冲突就拒绝。同一 allowlist
文件中的不相交用户 hunk 会保留在工作树，不会进入复盘 commit；在线 stats/progression
从来不在 patch 中。

成功复盘的重启 marker 以同目录临时文件 + exclusive hardlink 原子发布，记录精确 `review_parent`、
`review_commit` 和路径。marker 在真实工作树、`update-ref` 和 push 之前发布；落盘失败则
根本不应用 patch；若已有仍待健康验证的 marker，新复盘使用原子 exclusive 发布并拒绝
覆盖旧 marker。若随后 CAS 失败，只有精确反向 patch 能无损应用时才撤掉工作树 patch
并删除本轮 marker；否则 marker 与现场都留下诊断，不强制恢复。

runner 只接受单父、位于当前历史、实际改动全部落在内置 allowlist 的 commit，并以新的
前向 revert commit 撤销它。marker 自报路径不可信，必须与 commit 实际路径完全一致。
同文件并发用户 hunk 不进入回滚 commit，patch 冲突时拒绝覆盖。复盘 marker 存在时，快速
与慢速异常退出都计入连续复盘崩溃，避免“每次活过 90 秒”永久绕过安全回滚。大脑侧只有
确认 marker 对应已加载历史并完整健康运行两局后才清除 marker。

## 风险边界与验证

仓库锁能协调所有 sts2-ascend 自动 Git 进程；无法强制第三方 Git 客户端遵守自定义锁。
对此使用真实 workspace 指纹、目标 index 前后指纹、精确 patch 和分支 CAS 防止覆盖。
外部程序若在指纹结束后的毫秒级窗口改写同一 hunk，`git apply --check` 会拒绝；若在
patch 已应用后抢写同一 hunk，系统不能证明可逆时会保留 marker/现场并停止自动恢复。
这是刻意的 fail-closed 边界，需要人工诊断，而不是冒险抹掉后到的用户内容。

这层独立 clone 是 Git/工作树隔离，不是操作系统权限沙箱。真实仓库指纹能发现绝大多数直接
逃逸，但不能阻止延迟 detached 子进程，也无法区分模型逃逸写入与合法在线进程写入那些被
排除的 stats/progression 路径；若威胁模型包含恶意命令执行，仍需 AppContainer/受限账户等
真正的文件权限沙箱。另一个可用性债务是 push 仍在仓库事务锁内：三次 120 秒超时加退避最坏
会占锁约 380 秒。它不造成提交夹带或历史覆盖，但会延迟在线存档和健康 marker 更新，后续可在
保留 commit CAS 的前提下把网络 push 拆到锁外队列。

`tests/test_autogit_safety.py` 在临时仓库覆盖：既有 staged 文件隔离与保留、目标 staged
拒绝、allowlist 前缀碰撞、复盘活跃时延后 push、CAS 故障、跨进程锁、Windows 无副作用进程探活、真实仓库根与关键 ignored 路径
指纹、隔离 clone 越界/ignored 写入、精确 patch 冲突拒绝、越界 commit 拒绝、同文件并发
用户 hunk 保留、marker 原子写入与 CAS 失败清理、runner 慢崩溃计数，以及前向历史安全
撤销。测试全部使用临时仓库和故障注入，不读写真实 knowledge 数据。
