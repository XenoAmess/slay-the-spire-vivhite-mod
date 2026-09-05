# T17 清洁 take 归档与 production row 模板

本文件是 `T17_CAPTURE_RECIPE.md` 的执行后模板，供清洁录制结束后立即归档。
它不是已完成的证据，也不能直接替代真实文件。尖括号字段必须由现场真实观察、
`ffprobe`、`Get-FileHash` 和录制标记填入；不要凭截图或猜测补值。每次重录使用
新的 `<attempt_id>`（例如 `a02`），绝不覆盖旧 raw 或旧失败包。

## 1. T17 的固定绑定

* owner subshot：`S10-04-crimson-route`
* timeline/source：恰好 12.0 s，即 720 帧（60 FPS）；推荐从 mark 后完整 2 s
  preroll 开始取连续 `[in_seconds, out_seconds)`，不要跨 take 拼接。
* asset type：`montage`；`formal_action_claimed=false`，但滚轮和悬停必须是
  真实游戏 UI 输入。`action_evidence` 保持空数组；不要伪造 card action sidecar。
* evidence refs（四项且只用这四项）：`T17-frame-begin`、`T17-runtime-manifest`、
  `T17-lineage`、`T17-frame-end`。
* 生产源路径必须是 run artifact root 内的相对路径，例如
  `raw/takes/T17/a02.mkv` 或经过确定性 CFR 归一化后的
  `raw/takes/T17/a02.cfr-normalized.mkv`。外部 `G:/OBS_VIDEOS/...` 只写入
  attempt/lineage 的原始来源字段，不能直接作为 binder source。

## 2. 动态牌组浏览策略

### 标记前（`staged_setup`）

1. 建立真实白绮 run，记录 session/run/game/OBS identity。若需要准备牌组，
   只在 mark 前用游戏控制台把当前绯彩路线牌加入 `Deck`；关闭控制台并等待飞牌
   动画结束。旧占位牌不能遮挡或靠裁切隐藏。
2. 优先从战斗/运行中的原生卡组查看进入 `NDeckViewScreen`。不要假设固定坐标：
   先保存 clean checkpoint，再按当前帧重新定位顶部卡组图标、网格和滚动条。
   只有卡组查看不可用时，才使用原生“百科大全→卡牌总览”及当前牌池筛选。
3. 在 checkpoint 的 OCR/人工复核中确认至少两张当前 `VIVHITE_CARD_…` 绯彩
   路线牌。推荐可读标题为“绯色面积”“三色轮舞”“光谱积分”“血色守恒律”
   “绯红定积分”“绯彩极限”；实际标题和 tooltip 以本次运行时为准。禁止把
   T19 的 61 张计数、旧 Ironclad/旧占位牌写入 T17。
4. 根据当前网格位置选一个路线核心牌作为 hover 目标；坐标仅是当帧元数据，
   不得复制旧 take 坐标。关闭搜索/排序/设置/所有 overlay，确认系统鼠标不会
   被 game capture 录入。记录 `setup_end_frame` 和 checkpoint 路径。

### 标记后（唯一正式 source span）

1. 开始 OBS 后先静置 2 s，取正式 `frame-begin`（完整 HUD/网格，不带 tooltip
   残影）。
2. 在网格内真实滚轮向下约 4 s（必要时一次连续拖动原生滚动条）。以画面中的
   网格/滚动条变化为依据，不在中途排序、搜索、切窗口或开控制台。滚动后至少
   有两张绯彩路线牌可辨。
3. 真实移动到当前目标牌的 bbox 中心并停留至少 1.5 s。只依赖游戏自己的
   hover 高亮/tooltip，不点击牌面打开第二层详情。tooltip 标题、牌图和关系
   文字应完整落在安全区。
4. 继续无输入保持 tooltip 与网格 3–4 s，再停止录制。若网格仍在动画，宁可
   延长到稳定后再停，不要把 mark 前 setup 或另一 run 拼进 source。

### 不依赖固定坐标的现场记录

将以下观察写入 `T17-ui-observation.json`（辅助文件，不列入
`action_evidence`）：

```json
{
  "kind": "vivhite_promo_t17_ui_observation_v1",
  "take_id": "T17",
  "attempt_id": "<attempt_id>",
  "screen_kind": "deck_view",
  "grid_bbox": {"left": "<observed>", "top": "<observed>", "right": "<observed>", "bottom": "<observed>"},
  "scroll": {
    "direction": "down",
    "wheel_delta": "<observed>",
    "begin_seconds": "<from_mark>",
    "end_seconds": "<from_mark>",
    "settled_frame": "<frame>"
  },
  "hover": {
    "card_id": "<actual VIVHITE_CARD_...>",
    "title": "<actual runtime title>",
    "bbox": {"left": "<observed>", "top": "<observed>", "right": "<observed>", "bottom": "<observed>"},
    "begin_seconds": "<from_mark>",
    "end_seconds": "<from_mark>",
    "settled_frame": "<frame>"
  }
}
```

OCR 是定位/复核辅助，不是 runtime identity 的唯一证据；`runtime-manifest` 必须
列出画面实际可读的 IDs 和标题。若 OCR 与当前本地化不一致，保留截图并判退该
attempt，不要猜测修正文案。

## 3. 四个 evidence 文件模板

下面的 JSON 只给出推荐字段。路径、字节数、SHA、帧和时间必须在文件关闭后真实
计算；所有路径相对于 artifact root，所有 evidence 行 `status` 必须为 `verified`。

### `frame-begin.json`

```json
{
  "kind": "vivhite_promo_t17_frame_evidence_v1",
  "ref_id": "T17-frame-begin",
  "role": "frame.begin",
  "take_id": "T17",
  "attempt_id": "<attempt_id>",
  "source_artifact": "raw/takes/T17/<attempt_id>.mkv",
  "source_sha256": "<64 hex>",
  "frame": "<first post-mark complete-grid frame>",
  "source_seconds": "<frame/60>",
  "image_path": "capture/takes/T17/<attempt_id>/evidence/frame-begin.png",
  "observed": "完整原生卡组网格、至少两张绯彩牌；无控制台、调试/训练层、OBS、系统鼠标、loading"
}
```

### `runtime-manifest.json`

```json
{
  "kind": "vivhite_promo_t17_runtime_manifest_v1",
  "ref_id": "T17-runtime-manifest",
  "role": "runtime.manifest",
  "take_id": "T17",
  "attempt_id": "<attempt_id>",
  "session_id": "<session>",
  "game_run_id": "<native run>",
  "game_process_id": "<exe:pid:start-utc>",
  "recorder_process_id": "<obs:pid:start-utc>",
  "runtime_version": "<current build/version>",
  "mod_build": "<dll/pck or commit hash>",
  "screen_kind": "deck_view",
  "visible_cards": [
    {"id": "VIVHITE_CARD_<actual>", "title": "<actual runtime title>", "readable": true},
    {"id": "VIVHITE_CARD_<actual>", "title": "<actual runtime title>", "readable": true}
  ],
  "scroll": {"direction": "down", "begin_frame": "<frame>", "end_frame": "<frame>"},
  "hover": {"card_id": "<one listed ID>", "title": "<same title>", "begin_frame": "<frame>", "end_frame": "<frame>"},
  "forbidden_surfaces": {"console": false, "debug_overlay": false, "modded_label": false, "obs_or_taskbar": false, "system_cursor": false, "loading": false}
}
```

`visible_cards` 只列实际出现在该 raw 的牌；不要将源码中的全量牌表冒充画面观测。
至少两项 ID 必须以 `VIVHITE_CARD_` 开头，且不得为旧 Strike/Defend/白绸结。

### `lineage.json`（对应 `T17-lineage`）

```json
{
  "kind": "vivhite_promo_t17_lineage_v1",
  "ref_id": "T17-lineage",
  "role": "runtime.manifest",
  "take_id": "T17",
  "attempt_id": "<attempt_id>",
  "run_id": "run-20260903T0012-director-v2-a1",
  "raw": {
    "artifact": "raw/takes/T17/<attempt_id>.mkv",
    "bytes": "<raw bytes>",
    "sha256": "<raw sha256>",
    "start_frame": "<0 or actual>",
    "end_frame_exclusive": "<start + decoded frame count>"
  },
  "clean_source_span": {
    "subshot_id": "S10-04-crimson-route",
    "in_seconds": "<integer frame / 60>",
    "out_seconds": "<in + 12.0>",
    "begin_frame_inclusive": "<frame>",
    "end_frame_exclusive": "<begin + 720>",
    "duration_frames": 720,
    "duration_seconds": 12.0
  },
  "setup_provenance": "staged_setup",
  "formal_action_source": true,
  "formal_action_claimed": false,
  "same_process_and_session": true,
  "note": "真实游戏 UI 滚轮与 hover；不声称机制结算或完全平衡/无限成长"
}
```

### `frame-end.json`

```json
{
  "kind": "vivhite_promo_t17_frame_evidence_v1",
  "ref_id": "T17-frame-end",
  "role": "frame.end",
  "take_id": "T17",
  "attempt_id": "<attempt_id>",
  "source_artifact": "raw/takes/T17/<attempt_id>.mkv",
  "source_sha256": "<same raw sha256>",
  "frame": "<last result-hold frame>",
  "source_seconds": "<frame/60>",
  "image_path": "capture/takes/T17/<attempt_id>/evidence/frame-end.png",
  "observed": "与 frame-begin 同一 raw；tooltip、牌名和至少两张路线牌仍可读；无禁画元素"
}
```

## 4. `take-row.production.json` 骨架

把下列骨架复制到 `capture/takes/T17/<attempt_id>/` 后再用真实值替换。字段名和
`action_evidence: []` 的形状与 `production_binder_v2._bind_take` 对齐；不要把
`T17-ui-observation.json` 塞进 `evidence_refs`，除非另有明确 storyboard ref。

```json
{
  "schema_version": 2,
  "kind": "vivhite_promo_take_row_v2",
  "status": "production_candidate",
  "run_id": "run-20260903T0012-director-v2-a1",
  "attempt_id": "<attempt_id>",
  "take": {
    "take_id": "T17",
    "independent": true,
    "source": {
      "artifact": "raw/takes/T17/<attempt_id>.mkv",
      "duration_seconds": "<decoded duration>",
      "bytes": "<source bytes>",
      "sha256": "<source sha256>",
      "capture_identity": {
        "session_id": "<session>",
        "game_run_id": "<native run>",
        "game_process_id": "<game identity>",
        "source_video_artifact_id": "T17-<attempt_id>-<short sha>",
        "run_id": "run-20260903T0012-director-v2-a1",
        "take_id": "T17"
      },
      "game_process": {"pid": "<pid>", "identity": "<same game identity>", "started_utc": "<utc>"},
      "recorder_process": {"pid": "<pid>", "identity": "<obs identity>", "started_utc": "<utc>"},
      "recording": {
        "start_frame": "<frame>",
        "end_frame": "<start + decoded frame count>",
        "started_monotonic_seconds": "<start request tick / frequency>",
        "stopped_monotonic_seconds": "<stop request tick / frequency>"
      },
      "ffprobe": {"path": "probe/takes/T17/<attempt_id>/source-probe.json", "bytes": "<bytes>", "sha256": "<sha256>"}
    },
    "evidence_refs": [
      {"ref_id": "T17-frame-begin", "role": "frame.begin", "status": "verified", "path": "evidence/takes/T17/<attempt_id>/frame-begin.json", "bytes": "<bytes>", "sha256": "<sha256>"},
      {"ref_id": "T17-runtime-manifest", "role": "runtime.manifest", "status": "verified", "path": "evidence/takes/T17/<attempt_id>/runtime-manifest.json", "bytes": "<bytes>", "sha256": "<sha256>"},
      {"ref_id": "T17-lineage", "role": "runtime.manifest", "status": "verified", "path": "evidence/takes/T17/<attempt_id>/lineage.json", "bytes": "<bytes>", "sha256": "<sha256>"},
      {"ref_id": "T17-frame-end", "role": "frame.end", "status": "verified", "path": "evidence/takes/T17/<attempt_id>/frame-end.json", "bytes": "<bytes>", "sha256": "<sha256>"}
    ],
    "action_evidence": [],
    "spans": [{"subshot_id": "S10-04-crimson-route", "in_seconds": "<frame/60>", "out_seconds": "<frame/60 + 12.0>"}]
  },
  "editorial_boundary": {
    "formal_owner_span": {"begin_zero_based_frame_inclusive": "<frame>", "end_zero_based_frame_exclusive": "<frame + 720>", "duration_frames": 720, "duration_seconds": 12.0},
    "display": {"first_complete_grid_frame": "<frame>", "scroll_begin_frame": "<frame>", "hover_begin_frame": "<frame>", "hover_end_frame": "<frame>", "last_result_hold_frame": "<frame>"},
    "normalization_note": "<source byte identity or exact CFR normalization provenance>"
  }
}
```

Binder 要点：`source.recording.end_frame - start_frame` 必须等于 probe 的解码帧数；
单调时钟差必须与声明时长相差不超过 0.25 s；每个 evidence descriptor 的 bytes
和 SHA 必须与文件真实值一致；T17 不需要、也不允许伪造正式动作 sidecar。

## 5. 部分 manifest 与验收顺序

在整批 19/20 个 take 尚未齐全时，可保存一个仅用于交接的
`take-manifest.t17-only.json`，但公共 binder 预期会因 take 数量不足而失败；这个
失败不能被写成 T17 失败。结构如下：

```json
{
  "schema_version": 2,
  "kind": "vivhite_promo_take_manifest_v2",
  "batch_id": "run-20260903T0012-director-v2-a1-t17-<attempt_id>-partial",
  "run_id": "run-20260903T0012-director-v2-a1",
  "source_strategy": "independent_take_files",
  "from_legacy_a4": false,
  "partial_scope": {"take_ids": ["T17"], "production_binder_expected_global_status": "blocked_until_all_required_takes_exist"},
  "takes": [<将 take-row.production.json 中 take 对象原样放入此处>]
}
```

建议按以下顺序完成，不要跳过任何一步：

1. OBS 停止且文件大小稳定后，复制外部 raw 到新 artifact 路径；保留外部原件，
   记录原始路径、文件关闭时间和 SHA。
2. 用真实 `ffprobe` 生成 `probe/takes/T17/<attempt_id>/source-probe.json`；确认
   H.264/yuv420p、1920×1080、60/1、AAC 48 kHz stereo。若需 CFR 归一化，新增
   文件和 hash，原始文件仍保留。
3. 从同一 raw 抽取 frame-begin/end，并逐帧检查禁画元素；生成 runtime-manifest、
   lineage、可选 ui-observation，计算所有 evidence bytes/SHA。
4. 先以 60 FPS 帧算术核对 12 s span，再写 row 和 partial manifest。不要从不同
   attempt 取 12 s，也不要把 preroll/setup 写入 display span。
5. 交给 `_bind_take`/production binder 做 path/hash/probe 校验；T17 的预期结果是
   `action_evidence=[]` 且 `production_eligible=true`，全量 EDL 要等 19/20 个 take。
6. 通过后才在主进度 doc 追加 attempt、raw/probe/evidence hashes、span 和状态；
   判退则新建 `take-row.rejected.json` 并保留全部 raw/抽帧/原因，下一次使用新
   attempt。

## 6. 快速判退清单

* mark 后少于 2 s clean preroll、滚轮无实际变化、只有一张路线牌或 tooltip 不可读；
* source span 不是同一 raw 连续 720 帧，或为了凑 12 s 拼接不同 take；
* mark 后出现控制台、排序/搜索、暂停、训练/调试面板、`MODDED`/Ironclad、OBS、
  任务栏、系统鼠标或 loading；
* runtime manifest 只写“应该存在”的牌，没有同一 raw 的实际可读 ID/title；
* 任一 path/bytes/SHA/录制帧界与真实文件不符，或把 staged setup evidence 暴露
  到 EDL；
* 旁白将 T17 说成机制结算、完全平衡或必然无限成长，或提前宣称 T19 的 61 张。
