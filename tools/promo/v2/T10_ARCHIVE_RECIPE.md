# T10 归档与探针操作单

脚本 `tools/promo/archive_t10_attempt.py` 用于每一条独立的 T10（地图 → Act 2/3 篝火 → 休息 → 返回地图）OBS take。它只接受已经关闭的 MKV；不会启动游戏/OBS，也不会改写或删除外部录制。

## 运行

```powershell
py -3 -B tools/promo/archive_t10_attempt.py `
  --external-dir 'G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T10\a04' `
  --run-id run-20260903T0012-director-v2-a1 `
  --attempt-id a04
```

外部目录必须恰好包含一份已关闭的 `*.mkv`。脚本先做两次大小/mtime/SHA-256 采样，再把 MKV 字节级复制到 `raw/takes/T10/a04.mkv`，并将目录内其余 JSON、NDJSON、PNG 等原件复制到 `capture/takes/T10/a04/source-artifacts/`。重复运行时，已有文件只有在字节完全相同的情况下才会复用；出现差异会立即失败，不会覆盖。

## 产物

- `raw/takes/T10/<attempt>.mkv`：不可变 OBS 原件。
- `raw/takes/T10/<attempt>.cfr-normalized.mkv`：ffmpeg stream-copy 的审阅副本；不替代原件。
- `probe/takes/T10/<attempt>/`：原始/归一化 ffprobe 与命令记录。
- `evidence/takes/T10/<attempt>/`：两路完整解码、blackdetect/freezedetect 日志、CFR 时间锚点帧与 frame index（时间 seek 的审阅锚点，不是原生 frame mark）。
- `capture/takes/T10/<attempt>/`：来源 sidecar、attempt manifest、审阅行、binder validation、handoff。
- `contracts/takes/T10/<attempt>/strict-action-sidecar.rejected.json`：明确记录缺少原生三元证据。

## 严格门禁

T10 录制器输出的是操作员 marks；本归档器不会把坐标、OCR、墙钟时间或视频像素升级成 `state.before`、`action.receipt`、`state.after` 或编码帧边界。即使目录中出现名为 `receipt`/`state`/`action` 的文件，也只作为 `candidate_artifacts_not_promoted` 列出，必须由独立的原生证据验证流程确认后才能进入 production manifest。默认结果因此是 `rejected_preserved`、`production_eligible=false`，且不会写入正式 EDL。独立原生 sidecar 仍须先交给 binder 验证，再把本工具的原件/探针作为 lineage 输入。

## 中断恢复

`operator-marks.partial.json` 会原样保存在 `source-artifacts`；没有最终 `operator-marks.json` 也不会伪造完成状态。`archive-context.json` 固定首次观察时间，`archive-summary.json` 是完成哨兵。归档中途失败时保留已经生成的原件、探针和日志；修复外部输入后可再次运行，任何不一致文件都会显式报错并等待人工处理。
