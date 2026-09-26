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

## 经验

- Stack ready 不等于真实游玩；开播后仍需持续检查动作与 HealthWatch。
- 整理历史遗留改动必须跑完整自检；语法恢复不能代替语义验收。
- 学习记忆与高频调试日志分别管理；不要为了干净状态忽略整份 knowledge。
- 大文件通过 LFS 保持原始证据，不能丢弃唯一对局记录来绕过上传限制。
