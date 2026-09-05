# 白绮宣传片 v2（导演版）

本目录是 540 秒导演版的项目侧、加法式生产入口。旧的 `tools/promo/storyboard.json`、`full-master-script.json`、`vivhite-player-10m` entry point 与所有 a4 run 继续保留为兼容/失败参考；不得用旧 a4 的 raw、成片、旁白或字幕填充本目录的机制镜头。

当前权威文档：

- [导演分镜计划 v2](../../../docs/2026-09-02-白绮宣传片导演分镜计划-v2.md)
- [制作进度与中断恢复](../../../docs/2026-09-02-白绮宣传片-v2-制作进度.md)
- [宣传片跨仓能力归属 ADR](../../../docs/2026-09-02-宣传片跨仓能力归属ADR.md)

## 生产模型

v2 明确区分五层：

1. 十个 canonical shot ID：只作为稳定 ABI、语义与 claims 汇总键；
2. 十五个 director section：组成连续的 `00:00–09:00` 时间线；
3. subshot：一项具体画面意图，可引用 gameplay take 或 xAR `TitleCardSpec` 说明页；
4. take/attempt：独立录制的原始文件及追加式尝试；
5. EDL segment：成片中对某个 subshot/source window 的一次引用，同一个新 take 可在冷开场、正文和 Finale 中使用不同干净区间。

所有时间门使用 60 FPS 整数帧；主片必须为 `32,400` 帧。旧“单条长录像截十个窗口”不再是可用生产路径。

## 当前文件与状态

- `storyboard.json`：v2 的机器可读导演时间线；当前已固结 15 个 director section、20 个 take 槽（19 必需 + T15 条件）和 51 个 subshot/cue。未产生真实素材时，source 只能是计划标记，不能伪造 bytes/SHA。
- `capture-runbook.json` 与 `CAPTURE_RUNBOOK.md`：按五批执行 T01–T20；每个 take 都固定为标记前 setup、2 秒干净 pre-roll、正式游戏 UI 操作、完整结算和 3–4 秒结果。T06 已从当前 C# 注册及中文本地化绑定为奖励池 Common“切线星光”。
- `T17_CAPTURE_RECIPE.md` 与 `T17_ARCHIVE_TEMPLATE.md`：T17 绯彩积分路线补镜的动态卡组浏览、清洁录制、四项 evidence、take-row/partial manifest 归档和中断恢复模板；T17 为 montage，`action_evidence` 保持空数组，不把浏览动作冒充机制结算。
- `run_t17_capture.ps1`：按当前帧传入网格/目标牌坐标，执行 T17 标记后滚轮与 hover，并以原子 partial/final `operator-marks.json` 留下 Stopwatch 边界；它不生成 native action evidence。
- `run_t19_capture.ps1`：从已准备或参数化进入的百科大全白绮牌池执行 T19 61 张牌检查、滚轮和三路线 hover；`-RequireCountOcr` 仅提供裁剪 OCR 辅助，完整 61-ID runtime manifest 仍须录后依据实际画面生成。
- `run_t07_capture.ps1`：从录制前已确认的真实奖励页，连续执行当前白绮奖励卡 hover/选择、Skip/map 打开、可达节点 hover/选择和结果尾；坐标、卡牌/节点 ID 与等待窗口均参数化，持续写入 partial/NDJSON UTC/Stopwatch operator marks，停录后绑定新 MKV 的 bytes/SHA-256（不生成 native action evidence）。
- `promo_capture_operator_common.ps1`：上述现场脚本共用的进程身份、滚轮、截图摘要和可恢复 marks 写入辅助；process identity 使用 `exe-pid-start-utc` 可移植格式，operator marks 永远不替代 `state.before → action.receipt → state.after`。
- `../vivhite_promo/capture_runbook_v2.py`：纯离线校验和单 take 现场提示器；每次从当前源码重新确认 T06，不启动游戏、OBS 或媒体进程。
- `../vivhite_promo/title_cards_v2.py`：构造 xAR v0.2.1 公共 `TitleCardSpec`；`../render_title_cards_v2.py` 负责显式绑定字体/蓝蝶并通过 xAR 公共 renderer 追加式生成 PNG。
- `build_narration_script.py` 与 `narration-script.json`：从 storyboard 确定性物化 30 个非空旁白 cue，并显式登记 21 个有意静音 cue；每个旁白 cue 独立生成中文音频与中英字幕资产，不把整章合成一条长字幕。
- `../vivhite_promo/media_gate_v2.py`：消费已存在的 ffprobe JSON，严格验证 540 秒/32,400 帧终片规格；当前未接入 renderer。
- `../schemas/vivhite-promo-action-evidence-v2.schema.json` 及 `../vivhite_promo/action_evidence_v2.py`：正式动作的 `state.before → action.receipt → state.after` 与 `staged_setup` 隔离契约；只有 production 对抗测试最终通过后才可放行实录。
- `../vivhite_promo/director_v2.py`：验证 storyboard 与 take-manifest 声明并组装多 take EDL；产出明确标记为 `draft_unverified`，不会把未读取的媒体/证据 bytes 冒充为已验证。

用户已于 2026-09-03 00:07 明确解除原始媒体门禁，当前允许启动游戏、OBS、录制与渲染；所有实际产物仍须使用新 run/attempt、保留失败尝试并通过对应生产门。`storyboard.json.round_scope` 已同步为 `production_authorized`；网络 TTS 仍保留独立布尔门，不由这次四项授权暗改。

## 未来 run 布局

每次录制和每次失败重试必须使用新 run/attempt，建议布局：

```text
tools/promo/runs/<new-v2-run-id>/
├─ notes/project-snapshot/
├─ capture/take-index.json
├─ capture/takes/<take-id>/<attempt-id>/contract.json
├─ raw/takes/<take-id>/<attempt-id>.mkv
├─ evidence/takes/<take-id>/<attempt-id>/
├─ title-cards/
├─ narration/
├─ subtitles/
├─ edl/
│  ├─ master-540.json
│  ├─ hero-60.json
│  ├─ cut-30.json
│  └─ cut-15.json
├─ logs/
├─ review/
└─ run-manifest.json
```

每个 take 独立绑定媒体、contract、probe、marks 与证据；不要把多个文件伪装成一份单 raw receipt。`staged_setup` 只允许发生在正式展示 span 之前，且必须从所有 EDL 中排除。

## 离线验证

从仓库根目录运行：

```powershell
py -3 -B -m unittest discover -s .\tools\promo\tests -p 'test_*.py' -v
```

该命令只执行离线测试。正式录制前还需重新执行严格 external-tools/overlay 预检；若当次仍发现训练 overlay payload，则先走可逆隔离并重跑预检，不能把离线测试通过解释成录制环境已经干净。

逐 take 清单可单独查看：

```powershell
$env:PYTHONPATH = (Resolve-Path .\tools\promo).Path
py -3 -B -m vivhite_promo.capture_runbook_v2 validate
py -3 -B -m vivhite_promo.capture_runbook_v2 show T18
```

标题卡像素已在 `run-20260902T162155Z-director-v2-title-cards-a2` 完成：10/10 张 1920×1080 RGBA PNG、字体/蓝蝶/xAR/storyboard 资源绑定及逐文件 SHA-256 均见 run 内 manifest。a1 的首张后置检查失败按 append-only 原则保留，不作正式输入。

旁白/字幕可用批次为 `run-20260903T0040-director-v2-narration-a5`：晓晓声线、无 BGM、30/30 个逐 cue MP3、累计 195.768 秒；对应中英文本、Edge TTS sidecar、全局双语 ASS/SRT 和 renderer 消费清单位于该 run。入口清单为 `logs/director-v2-narration-manifest.json`，其所有素材路径均相对该 run 根；C008B/C038/C048 的运行时待绑定数值未烘入预生成语音或字幕，须由 capture/binder 证据决定最终画面字段。a1–a4 均按追加式保留，只作失败或中间参考，不得作为最终剪辑输入。

还有两条未完成的生产边界：

- take manifest 声明和 draft EDL 尚未由 production binder 逐文件重读 bytes/SHA 并调用 action-evidence 门；
- 60/30/15 秒版本目前只有“同批新 take、各自独立 EDL”策略声明，三份 EDL 尚未编排；
