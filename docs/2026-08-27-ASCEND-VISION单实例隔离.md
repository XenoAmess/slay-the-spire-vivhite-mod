# ASCEND-VISION 单实例隔离

## 事故

直播中同时出现两个标题均为 `ASCEND-VISION` 的窗口。正式 viewer 使用当前知识库，复盘隔离 clone
中的 viewer 使用较早快照；两个窗口每 500ms 重新置顶，导致“近20局均层”在两个值之间闪烁。

根因是 viewer、监督器和窗口层工具均从各自的 `__file__` 推导项目根目录。复盘沙箱包含完整仓库
副本，因此拥有另一份 `knowledge/viewer.lock`，绕过了原有单实例保护；副本还会覆盖同 session 的
viewer PID 记录。

## 修复

- `lifecycle.STACK_ROOT` 优先从当前 session 的 `STS2_ASCEND_RUNTIME_DIR` 推导正式根目录；复制目录
  运行的代码与正式进程因此共享同一知识库和 viewer 锁。
- OpenCode 复盘进程树注入 `STS2_ASCEND_DISABLE_VIEWER=1`；监督器和 viewer 入口都 fail closed。
- `FloorStatsProvider` 只在统计语义变化时发布新版本；活动局文件仅 mtime/决策数变化时不重绘卡片。
- 直播止血只结束已核验命令行位于 `knowledge/code_backups/review_work` 的副本进程，不停止游戏、
  brain、TTS、复盘、直播姬或直播。

## 验证

- 枚举窗口与命令行，确认只剩一个响应中的正式 `ASCEND-VISION`。
- 单测覆盖复盘进程禁用 viewer、复制目录归一到 session 根、窗口层使用统一锁，以及活动局重写
  不产生仅时间戳变化的统计版本。

## raw sandbox 自检的二次事故

后续现场又捕获到一个已失去父进程的 viewer，命令行位于
`knowledge/code_backups/review_salvage/.../raw_sandbox/repo`。这次不是正常 OpenCode 复盘子进程，
而是手工运行 raw 副本自检；自检实例化并驱动真实 `Agent`/`Agent.run()` 路径，构造器
启动了 detached 驾驶舱监督器。由于该手工路径没有继承复盘子进程的 viewer 禁用环境，
副本的文件锁也不能阻止它与正式 viewer 并存。

二次修复在 Windows 加入 `Local\STS2_ASCEND_ASCEND_VISION` 命名互斥体。这个内核对象跨仓库副本
共享，即使某个 raw/手工调用者遗漏 `STS2_ASCEND_DISABLE_VIEWER=1`，也无法打开第二个窗口；
原文件心跳锁仍保留生命周期归属与诊断作用。回归测试验证已存在互斥体时拒绝新 viewer，
并确认持有者结束时释放句柄。
