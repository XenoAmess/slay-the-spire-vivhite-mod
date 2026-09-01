# sts2-ascend/tests — Brain 离线回归

这里是 `sts2-ascend` 的 Python `unittest` 回归集。测试以标准库和 mock 为主，验证决策、Profile/轮换、持久化、生命周期、复盘闭环、驾驶舱、TTS owner、Workshop 和直播脚本合同；它们不代替游戏内真实对局，也不应向 `/action` 发送外部动作。

## 运行

从仓库根目录：

```powershell
# 全量（-B 避免生成字节码缓存）
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_*.py"

# 详细输出
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_*.py" -v

# 一个文件或一个测试类
py -3 -B -m unittest .\sts2-ascend\tests\test_character_rotation.py -v
py -3 -B -m unittest .\sts2-ascend\tests\test_runner_handshake.py -v
```

若系统没有 `py -3`，使用 `Start-Agent.ps1` 预检通过的同一 `python.exe`；不要混用缺少依赖的 Windows Store 占位命令。测试发现路径固定为 `sts2-ascend/tests`，从其他目录运行时请相应调整工作目录。

## 覆盖面导航

| 主题 | 代表测试 |
| --- | --- |
| 策略与角色轮换 | `test_character_strategy.py`、`test_character_profiles.py`、`test_character_rotation.py` |
| 持久化/统计/终局 | `test_persistence_fail_closed.py`、`test_native_game_over_save_barrier.py`、`test_profile_*.py`、`test_floor_stats.py` |
| runner、复盘与失败保全 | `test_runner_handshake.py`、`test_review_*.py`、`test_failed_review_evidence_mount.py`、`test_review_salvage.py` |
| 生命周期/人工接管/窗口 | `test_manual_control.py`、`test_broadcast_window_patrol.py`、`test_window_layers.py`、`test_start_agent_*.py` |
| 驾驶舱与语音 | `test_live_dashboard.py`、`test_dashboard_viewer.py`、`test_tts_*.py`、`test_indextts_gpu_service.py` |
| 游戏知识、孤儿恢复和 Workshop | `test_orphan_run_recovery.py`、`test_release_orphan_cli.py`、`test_renderer_compatibility_docs.py`、`test_workshop_materials.py` |

新增测试应保持确定性、可离线运行、明确清理临时目录；需要真实游戏/Steam/GPU 的实验放在专项文档或外部验收，不把凭据写进 fixture。

## 失败处理

先记录完整命令、Python 版本、失败测试和工作树状态，再按模块定位。`__pycache__/`、临时 review clone 和 `.runtime/` 不属于测试结果，已在 `.gitignore` 中排除；不要为了让测试通过手改 `knowledge/`。生命周期/复盘测试若与在线 Brain 并行运行，使用测试自己的临时根目录并遵守 session 隔离。

模块设计与生产启停见 [`../brain/README.md`](../brain/README.md)、[`../scripts/README.md`](../scripts/README.md) 和 [`../README.md`](../README.md)。
