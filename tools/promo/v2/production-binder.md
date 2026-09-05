# 白绮宣传片 v2 production binder

`vivhite_promo.production_binder_v2` 是 draft EDL 与 renderer 之间的强制边界。只有它输出的
`authoring.status = production_verified` 才是可渲染输入；`director_v2` 的
`draft_unverified` 不能直接进入 renderer。

## take manifest 增量字段

顶层必须给出新制作尝试的 `run_id`；每个 source 的同名字段都必须与它一致。

每个 take 的 `source` 除 `artifact / duration_seconds / bytes / sha256` 外，必须提供：

```json
{
  "capture_identity": {
    "session_id": "capture-session-001",
    "game_run_id": "game-run-001",
    "game_process_id": "game-pid-1234-start-001",
    "source_video_artifact_id": "raw-take-T03-attempt-001",
    "run_id": "promo-v2-run-001",
    "take_id": "T03"
  },
  "game_process": {
    "pid": 1234,
    "identity": "game-pid-1234-start-001",
    "started_utc": "2026-09-03T00:00:00Z"
  },
  "recorder_process": {
    "pid": 5678,
    "identity": "obs-pid-5678-start-001",
    "started_utc": "2026-09-03T00:01:00Z"
  },
  "recording": {
    "start_frame": 100,
    "end_frame": 3700,
    "started_monotonic_seconds": 100.0,
    "stopped_monotonic_seconds": 160.0
  },
  "ffprobe": {
    "path": "probe/T03.json",
    "bytes": 1234,
    "sha256": "..."
  }
}
```

probe 文件必须声明 `kind = vivhite_promo_source_probe_v2`、`status = completed`，以
`source.path / bytes / sha256` 反向绑定同一个原始视频，并保存真实 ffprobe `result`。原始 take
固定为单路 H.264/yuv420p/1920×1080/60 FPS 视频和单路 AAC/48 kHz/stereo 音频；解码帧数、容器时长、
录制帧界与录制单调时钟都必须闭合。Matroska 未提供单路 duration 时以 `-count_frames` 的解码帧数为准；
若提供了单路 duration，它也必须一致。

每个 `evidence_refs` 条目在 production manifest 中必须同时有 `path / bytes / sha256`。正式动作另加：

```json
{
  "action_evidence": [
    {
      "step_id": "play_luminous_projection",
      "action_id": "action-T03-001",
      "sidecar": {
        "path": "contracts/T03/action-001.json",
        "bytes": 2345,
        "sha256": "..."
      },
      "pointer_hitbox": {"left": 700, "top": 680, "right": 1040, "bottom": 1040},
      "visible_state_paths": ["/run/current_hp", "/enemies/0/current_hp"]
    }
  ]
}
```

`step_id` 必须逐项覆盖 storyboard 的 `formal_action_chain.steps`。binder 只用文件路径调用
`load_action_evidence`，并核对 source/session/run/game process/take/subshot/action、目标牌或结束回合按钮、
点击落点、录制区间、显示区间以及 `visible_state_paths` 的真实前后变化。`staged_setup` 必须早于录制起点，
其文件和帧不会写入 EDL。

没有 `formal_action_chain` 的 `ui_gameplay`/`gameplay` take 也可以声明独立的 UI 动作，但必须显式给出
`subshot_id`、三份 state/receipt 引用、sidecar、点击 hitbox 和可见状态路径。当前允许的 UI 动作及其
manifest 目标字段如下；这些动作会写入 `action_bindings`，并标记 `formal_action = false`、`ui_action = true`，
不会伪造机制动作链：

| `action_kind` | receipt target / parameter | manifest 目标字段 |
| --- | --- | --- |
| `choose_reward_card` | `reward_card` / `card_id` | `target_card_id` |
| `choose_map_node` | `map_node` / `node_id` | `target_node_id` |
| `choose_rest_option` | `rest_option` / `option = rest` | `rest_option` |
| `buy_card` | `shop_item` / `item_id` | `target_item_id` |

奖励卡必须是 `VIVHITE_CARD_` ID；休息动作只能是 `rest`。UI 分支仍执行与机制动作相同的
capture identity、路径哈希、指针落点、录制/显示区间、单调时钟、before→receipt→after 状态变化和
`staged_setup` 早于录制起点门禁。`close_inventory`/`leave_shop` 只保留历史 ABI 名称，尚无对应的
action-evidence receipt kind 时不得冒充严格动作。

T14/T15 的 `state.after.payload.production_observations` 还必须记录正数
`actual_drain_healing / solitary_crown_actual_healing / actual_draw_delta / actual_energy_gain`、2–3 个
`enemy_deaths` 和事件顺序；state.before 必须证明缺血且携带
`VIVHITE_RELIC_ORIGIN_STAR_CHART`。T16 的三份动作 sidecar 必须共享连续运行链，两个 EDL 源 span 必须首尾相接，
phase handoff 必须是同一份语义快照。

片尾模板值通过 take 的 `template_values` 绑定到已哈希 evidence JSON：

```json
{
  "field": "runtime_version",
  "evidence_ref": "T20-runtime-manifest",
  "json_pointer": "/version",
  "display_value": "0.4.0"
}
```

## 生成 EDL

输出文件必须是 artifact root 内尚不存在的新路径：

```powershell
$env:PYTHONPATH = (Resolve-Path tools/promo).Path
py -3 -B -m vivhite_promo.production_binder_v2 `
  --storyboard (Resolve-Path tools/promo/v2/storyboard.json) `
  --take-manifest (Resolve-Path tools/promo/runs/<run-id>/capture/take-manifest.json) `
  --artifact-root (Resolve-Path .) `
  --output tools/promo/runs/<run-id>/edl/master-540.production.json
```

成功结果保留原有 `kind = vivhite_promo_multi_take_edl_v2`，并标记：

- `authoring.status = production_verified`
- `authoring.source_verification = bytes_sha256_ffprobe_verified`
- `authoring.action_evidence_verification = path_loaded_and_hash_bound`
- 每个视频 source 的 `verification = production_verified` 与稳定 `probe` 摘要
- `production_binding.staged_setup_in_edl = false`
