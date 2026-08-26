# 2026-08-27 ASCEND-VISION 持续置顶修复

## 问题

`ASCEND-VISION` 进程和窗口都没有退出，但杀戮尖塔 2 被设置为 `TOPMOST` 后会进入 TOPMOST z-order 链的前方，导致赛博青蓝悬浮窗被游戏盖住。一次性的开播/下播复位无法覆盖游戏点击、Livehime 临时置顶和查看器建窗恢复焦点等路径。

## 修复

- 新增 `brain/window_layers.py`，通过查看器锁文件 PID 与精确窗口标题定位窗口，并使用 `SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE|SWP_NOMOVE|SWP_NOSIZE|SWP_SHOWWINDOW)` 修复层级；整个过程不调用 `SetForegroundWindow`。
- `review_viewer.py` 在建窗、恢复游戏焦点、每 500ms 心跳和渲染异常后复位自身 z-order。
- `policy.py` 的游戏坐标点击仍然先激活游戏，但在 `finally` 中恢复查看器层级。
- `BilibiliLive.psm1` 的所有游戏置顶和 Livehime 临时置顶清理路径都恢复查看器；烟测脚本也显式验证两次。

## 约束与验证

- 游戏继续保持前台和 `WS_EX_TOPMOST`，查看器保持 `WS_EX_NOACTIVATE`、点击穿透和置顶，不抢输入焦点。
- 下播入口仍只操作哔哩哔哩直播姬，不停止服务、不关闭游戏、不修改 `.runtime`。
- 单元测试覆盖 PID 锁解析、无激活复位和看门狗节流；PowerShell 测试覆盖入口顺序及所有游戏置顶路径。
- 真机验收应检查查看器在游戏上方的 z-order、前台窗口仍为游戏，以及游戏点击和 Livehime 操作后的自动恢复。
