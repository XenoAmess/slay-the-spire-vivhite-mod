# sts2-ascend 在线状态 staged 自愈（2026-08-28）

## 问题

真实仓偶尔会被人工工具或宽范围 `git add --all` 暂存整棵工作树。截图、viewer/TTS 日志和刚结束的
run 会因此同时进入真实 index。旧逻辑只要发现目标 run 已 staged 就把它视为“用户内容”，拒绝 Brain
存档；之后每局都会撞同一堵墙，必须人工精确 unstage 才能恢复。

这不是 `index.lock` 冲突，也不应依赖人工长期巡检。在线状态本来就由 Brain 持续重写，工作树中的
最新完整文件才是提交来源；真实 index 里偶然留下的旧快照不能拥有比 Brain 更高的优先级。

## 所有权与事务模型

- `DEFAULT_PROGRESS_PATHS` 是 Brain 管理域：runs、stats、progression、review queue、运行 policy、
  lessons 和 preferred model state。
- 一次提交的全部 pathspec 都在这个管理域内时，目标 staged 不再阻塞。Brain 仍从当前工作树构造
  私有 index 和 commit；分支 CAS 成功后，只把这些精确 pathspec 的真实 index 同步到新 commit。
- `.tmp` 截图、TTS/viewer 日志、代码、配置、文档及其他 staged 不在管理域内，既不会进入机器存档，
  也不会被 unstage 或改写。
- 任一请求混入非机器 pathspec，仍使用严格冲突规则：只要目标 staged，整笔拒绝。这保留了复盘代码
  与人工代码提交的隔离边界。

## 崩溃恢复

机器路径 staged 接管不是先执行 `reset`。提交前会把目标 index 的 `ls-files --stage -z` 快照做
SHA-256 摘要，并与 parent、候选 commit、精确 paths、接管策略一起先写入 `.git` 下的耐久 journal：

1. journal 成功落盘后才 CAS 前移分支；CAS 失败会删除本次无效记录，HEAD 和真实 index 原样保留。
2. CAS 成功后按调用前的精确 index 快照同步目标 paths。短暂 `index.lock` 继续有界重试。
3. 若进程在 CAS 后、同步前退出，下次存档 preflight 会验证提交关系、路径未被后续 commit 改写、
   digest 和两次 index 读取均一致，再完成精确同步。
4. 若外部进程已经把机器 index 改成新内容，恢复器不会覆盖；记录和现场保留，本轮存档会从最新
   工作树重新建 commit，旧记录在证明已被新提交取代后清理。
5. 旧版无接管策略的 pending journal 继续走原 parent-tree 恢复分支，向后兼容。

因此，宽范围 staged 只能让某一次机器存档多走一个可观测的接管分支，不能永久堵塞后续 run 上库。

## 回归矩阵

- 原有 autogit/CAS/回滚/runner 事务矩阵：58/58 通过。
- 接管相关定向矩阵：10/10 通过，包括真实 `git add --all`、staged A/工作树 B、新 run、无关 staged
  保留、机器+代码混合请求拒绝、CAS 三次失败、同步锁失败后恢复、digest 不匹配保留现场、旧 pending
  被新机器提交取代。
- 测试只使用临时 Git 仓；没有停止或重启直播 Brain。

## 维护注意

- 新增在线持久化文件时，只有确实由 Brain 独占写入和提交的状态才应加入
  `DEFAULT_PROGRESS_PATHS`。日志、截图、失败取证包和源码不得为了“方便”扩大进管理域。
- 判断是否接管看本次全部 pathspec 的所有权，不按文件名猜测，也不使用全仓指纹或全仓洁净门禁。
- 日志出现“检测到 Brain 在线状态被放入真实 staged”代表自愈分支生效，不是需要人工立刻处理的
  故障；只有 journal 长期保留且目标 index 持续变化时才需要进一步调查并行写入者。

## 生产上线验收

- 使用统一 `Stop-Agent.ps1 -KeepGame` / `Start-Agent.ps1 -SkipDeploy` 热切换，游戏 PID 全程保留；
  Brain 断流约 52 秒。新进程 `boot_head=f4470755`，已验证包含机制提交 `d76cde0`，8080 health ready，
  并从第 847 局 F21 的原战斗继续游玩。
- 在真实 index 已有 9 张 `.tmp` 截图和 3 个 TTS/viewer 日志 staged 的现场，精确 stage 第 847 局
  run 的中途快照。结算时新 Brain 明确记录机器路径接管，并建立、推送存档提交 `304ca906`。
- `304ca906` 只包含 lessons、policy、progression、review queue、目标 run 和 stats 六个在线状态文件；
  目标 run 自动退出 staged。验收前后记录的上述 12 个非机器 staged blob id 逐项相同。
- 热停期间正在静默的 GLM 复盘按协议完整保存为失败包 `20260828-103400-...-9a9d4d44`，拒合清单
  单独提交并在启动后补推；新 worker 随后从 raw clone 补全现场并继续逐包重审，没有因上线丢批。
