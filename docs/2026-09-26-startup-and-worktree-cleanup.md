# 2026-09-26 全栈启动与工作区整理

## 起因与分类

启动时 Steam 客户端未运行，游戏报告 `k_ESteamAPIInitResult_NoSteamClient`。启动客户端后通过统一 Stop/Start 入口重试，Steam auto 模式正常进入真实对局。

初始 38 项未提交变更主要是既有直播健康监测、每日计划、TTS 显存限制、Brain 修复及测试文档，不是可丢弃缓存。学习记忆本来由 Brain 自动提交；根 AGENTS 的“knowledge 已 gitignore”描述已纠正。12 个误跟踪的调试日志取消跟踪，磁盘原件保留；新增 `/knowledge/*.log` 忽略规则。

## 验证与运行故障

8 个相关 unittest 模块共 141 项通过。完整 selfcheck 最初因代码块插入断言/字典中间而不能解析；机械重排后出现既有 `MINION_ILLUSION_FOCUS_OBS` 断言不匹配。这些待整理代码连同自检修复先保存在提交 `e1443945` 中，未宣称完整验收通过。

首次开播通过两条独立 applied 回执、Quipper 3328 MiB allocator / staged_cuda 门禁，并确认 Streaming 与 HealthWatch Running。后续 F3 出现 `_boss_projected` 未初始化且连续决策失败，立即统一下播。故障策略及自检已保全在上述提交；运行文件回退到启动前已有提交 `12b88bb3` 的 policy.py/selfcheck.py，其他已通过测试的维护改动保留。只用统一生命周期入口重载，不手改学习记录或注入游戏动作。

## 推送阻塞

GitHub 拒绝历史中的 `knowledge/profiles/vivhite/runs/20260918-010416_BL53H2F0QGBG.json`：两个版本分别为 135661584、136160409 字节。仅在末尾删除文件或添加 ignore 无法移除历史可达大 blob。

采用隔离 bare 仓将精确路径迁移至 Git LFS；原始两版本 SHA256 均与 LFS payload 一致。只重写未发布提交，保留远端已发布边界 `78b590f4`，不需要强推。旧历史保留本地备份 ref，迁移映射和隔离仓保留于 ignored `.tmp/`。最终接入必须持 autogit 仓库锁并检查 HEAD，防止覆盖运行中新增提交。

最终已在仓库锁内接入迁移，206 个未发布提交保留，旧 HEAD 为 `8ee85f87`，新 HEAD 为 `b9c905aa`；备份 ref 为 `refs/backup/pre-lfs-20260926`。迁移后普通 Git blob 均未超过 100 MiB，LFS 两份 payload 完整性验证通过，但远端拒绝上传：`This repository exceeded its LFS budget`。未更改账单或宣称推送成功。

检查既有 ZIP 归档工具后未执行归档：目标记录仍为 `in_progress=true`、`human_assisted=true`、`excluded_from_learning=true`、`ended_at=null`，137407 条决策。工具按异常现场规则保留它；不得篡改这些标记来强行归档。当前需由账户所有者恢复 LFS 配额后正常 `git push origin master`，本地原文件、LFS payload、迁移前历史均已保留。

回退基线完整自检输出 `SELFCHECK OK`，退出码 0。重新启动后 run `FP8AM7ZG9GPH` 已取得两条不同 applied 动作，连续推进战斗、奖励与地图，Quipper 再次通过 3328 MiB / staged_cuda 门禁。

最终只从保全版本恢复独立的空手结束回合协调维护逻辑（计数器、复位、等待与确认），不恢复故障评分/观测块；相关 3 项回归测试及完整 selfcheck 均通过。该维护补丁已落盘，当前已运行的 Brain 仍是此前验证过的回退基线，下次正常加载生效。最终独立巡检确认为 Streaming、HealthWatch Running，已连续推进至 F7；运行中继续产生的学习记录属于正常自动存档，不作 ignore。

## 经验

- Stack ready 不等于真实游玩；开播后仍需持续检查动作与 HealthWatch。
- 整理历史遗留改动必须跑完整自检；语法恢复不能代替语义验收。
- 学习记忆与高频调试日志分别管理；不要为了干净状态忽略整份 knowledge。
- 大文件通过 LFS 保持原始证据，不能丢弃唯一对局记录来绕过上传限制。
