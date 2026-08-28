# Bilibili Live 开播后窗口层级恢复

## 问题

直播姬必须在交互式高权限计划任务中临时成为前台窗口，否则无法安全校验并点击开播按钮。开播完成后，公共入口会恢复《杀戮尖塔 2》为前台并置顶，再将 `ASCEND-VISION` 放在游戏上方。

原实现只调用 `SetForegroundWindow` 和 Alt 键兼容路径。当入口由 Codex 或非前台 PowerShell 会话启动时，Windows 的前台锁会拒绝这两次请求，造成直播已成功、但直播姬仍留在最前的错误结果。

## 修复

- 保留原有 `SetForegroundWindow` 快速路径。
- 前台锁拒绝时，从精确目标 HWND 反查进程 ID，用 `WScript.Shell.AppActivate(pid)` 执行兼容性激活。
- `AppActivate` 只是候选路径；仍必须验证前台 HWND 与最初目标完全相同，避免模糊标题匹配到其他窗口。
- 前台激活可能改变 TOPMOST 层级，因此在激活验证成功后再次执行 `SetWindowPos(HWND_TOPMOST)`。
- 最后使用不激活的 `Set-AscendViewerTopMost`，保证游戏仍接收输入，悬浮窗在 TOPMOST 区域中位于游戏之上。

## 验证要点

1. 开播顺序仍为完整栈、直播姬、游戏前台/TOPMOST、`ASCEND-VISION` 无激活置顶。
2. 现场验证游戏 HWND 就是前台窗口，且游戏的 `WS_EX_TOPMOST` 为真。
3. `ASCEND-VISION` 的置顶恢复不调用 `SetForegroundWindow`，不抢走游戏输入。
4. 下播语义不变：只操作直播姬，不停止游戏或任何 sts2-ascend 服务。
