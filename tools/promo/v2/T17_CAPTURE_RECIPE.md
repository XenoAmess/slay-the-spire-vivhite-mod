# T17「绯彩积分」清洁录制交接单

本交接单是 `run-20260903T0012-director-v2-a1` 的 T17 现场补充，供当前执行者或
中断后的接替者直接照做。它只规定标记前的 `staged_setup`、标记后的真实游戏 UI
输入和验收证据；本文件本身不代表 T17 已录制，也不把控制台操作当成正式素材。

T17 是 `asset_type=montage` 的独立 take，服务于 `S10-04-crimson-route`（时间线
`484–496 s`，12 s）。它表达第三条构筑路线，不承担 T16 的猩红转化仪式因果，也
不承担 T19 的「61 张」计数证明。`storyboard.json` 当前给 T17 的正式证据角色只有：

```text
T17-frame-begin       frame.begin
T17-runtime-manifest  runtime.manifest
T17-lineage           runtime.manifest
T17-frame-end         frame.end
```

T17 的 `formal_display` 为 `real_input=true`、`game_resolution=true`、
`playback_speed=1`、`uncut_action=false`：可以在后期取连续蒙太奇窗口，但不能把
静态截图、控制台注入或不同运行拼成一次游戏操作。

## 路线选择与已核对的运行时事实

优先使用战斗/运行中的原生「卡组查看」界面。这样不依赖主菜单是否显示 RitsuLib
自定义牌池按钮，也不会与 T19 的牌库计数镜头混淆。

* 反编译的 `CardConsoleCmd`（`.work/sts2-decompiled-v0.111.0/MegaCrit/sts2/Core/DevConsole/ConsoleCommands/CardConsoleCmd.cs:18,34,67`）确认命令格式为 `card <card-id> [pileName]`；`Deck` 是合法 pile，默认才是 `Hand`。
* `NDeckViewScreen`（同目录 `Nodes/Screens/NDeckViewScreen.cs:224`）读取
  `PileType.Deck.GetPile(player)`，所以标记前执行 `card … Deck` 后，关闭控制台再
  打开卡组查看，新增卡会出现在原生卡组网格中。
* 当前源码/中文本地化仍注册以下绯彩牌（数值一律以当次 tooltip 为准）：

  | ID | 当前中文标题 | 用途 |
  | --- | --- | --- |
  | `VIVHITE_CARD_CRIMSON_AREA` | 绯色面积 | 先展示路线入口 |
  | `VIVHITE_CARD_TRICHROMATIC_WALTZ` | 三色轮舞 | 推荐最终悬停牌，名称和多段攻击意象清楚 |
  | `VIVHITE_CARD_SPECTRAL_INTEGRAL` | 光谱积分 | 展示汲取增量路线 |
  | `VIVHITE_CARD_CRIMSON_CONSERVATION_LAW` | 血色守恒律 | 展示回血/力量转化路线 |
  | `VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL` | 绯红定积分 | 展示高阶路线 |
  | `VIVHITE_CARD_CHROMATIC_LIMIT` | 绯彩极限 | 可作第六张，避免画面过稀 |

这些 ID 均来自 `Vivhite/VivhiteCode/Cards` 与
`Vivhite/Vivhite/localization/zhs/cards.json` 的当前工作树；不要把旧
`VIVHITE_CARD_VIVHITE_STRIKE`、旧防御/白绸结或任何 Ironclad 卡当作替代品。

## 标记前 staged_setup

每次重试都使用新的 `<attempt_id>`，不覆盖旧 raw。以下命令只允许在 recording mark
之前执行，命令文本和命令回执必须写入 `staged-setup.json`，不能进入 EDL 展示段。

1. 先确认游戏处在一个真实白绮 run（不是主菜单、loading、解锁页或 Brain/AI
   画面），并记录 `session_id`、`game_run_id`、游戏 PID/启动时间。若当前没有
   run，使用原生 UI 开一局白绮；不要用外部 API 注入一张“牌库截图”。
2. 在控制台关闭前按需给**运行牌组**加入路线牌。推荐一次加入六张，确保网格有
   至少两行可滚动内容：

   ```text
   card VIVHITE_CARD_CRIMSON_AREA Deck
   card VIVHITE_CARD_TRICHROMATIC_WALTZ Deck
   card VIVHITE_CARD_SPECTRAL_INTEGRAL Deck
   card VIVHITE_CARD_CRIMSON_CONSERVATION_LAW Deck
   card VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL Deck
   card VIVHITE_CARD_CHROMATIC_LIMIT Deck
   ```

   `Deck` 参数是已由游戏源码核对的运行牌组写入，不是把卡塞进手牌。每条命令
   返回失败、卡牌未注册或卡组视图未反映新增卡时，立刻保留该 attempt 的日志并
   停止，不在正式 span 内补牌；可改用下一 attempt 或下面的牌库路径。
3. 等待新增卡的原生飞入/提示动画完全结束。若需要进入战斗以显示完整顶部 HUD，
   可在加入牌后使用已验证的 `fight SLIMES_NORMAL`，再等战斗稳定；这仍属于
   `staged_setup`。不要用 `kill`、直接 API 或调试面板制造结果。
4. 点击顶部卡组图标进入 `NDeckViewScreen`。现有 1920×1080 参考帧中图标约在
   `(1788,34)`，仅作命中区域起点；每次必须从当前帧重新确认图标的实际 bbox。卡
   组网格参考中心为第一行约 `(400,430)…(1515,430)`、第二行约
   `(400,800)…(1240,800)`，不得复制旧 take 坐标。若新增牌在网格下方，先用
   原生「获得顺序/类型/费用/拼音顺序」按钮整理到便于阅读的位置，再关闭所有
   排序/设置弹层。
5. 如果当前 run 无法打开卡组查看，才走备选牌库路径：原生主菜单 → 百科大全 →
   卡牌总览，启用当前 RitsuLib/Vivhite 牌池筛选；若筛选按钮不存在，使用游戏自带
   搜索逐个确认上述中文标题。牌库路径必须仍能在同一画面看到至少两张当前
   `VIVHITE_CARD_` 牌，不能把 T19 的「61」计数提前写入 T17。搜索、筛选和进入
   页面均在 mark 前完成。
6. 关闭控制台、搜索框、设置、解锁页及一切训练/调试覆盖层；确认游戏窗口完整占
   满 1920×1080，系统鼠标不会被录入。截一张 clean checkpoint（仅作恢复依据，
   不替代 raw/evidence），并在 `staged-setup.json` 写 `setup_end_frame`。

若卡组中已经存在旧占位牌，不能靠裁切、遮挡或旁白掩盖：能用原生
`remove_card <ID> Deck` 明确移除就仍在 mark 前处理并记录，否则放弃该 attempt，
重新建立干净 run。

## OBS 配置（当前现场基线，录制前仍须回读）

只使用独立新输出目录，例如：

```text
G:\OBS_VIDEOS\vivhite-director-v2\run-20260903-0012\T17\a01\
```

禁止复用当前 T10/T16 的输出目录或把多个 take 写进同一 MKV。当前本机 OBS 配置
文件（`%APPDATA%\obs-studio\basic\profiles\未命名\basic.ini` 与
`basic\scenes\未命名.json`）已读到以下基线；若现场 UI 与此不一致，先修正并重新
记录配置快照：

| 项目 | 必须值 |
| --- | --- |
| Profile / Scene | `未命名` / `场景 3` |
| Source | `游戏采集`（`game_capture`），窗口 `Slay the Spire 2:Engine:SlayTheSpire2.exe` |
| 画布/输出 | 1920×1080，60 FPS（60/1） |
| 视频 | NVENC H.264，MKV；输出为 yuv420p（若 OBS UI 显示 NV12，导出/ffprobe 仍必须验证 yuv420p） |
| 色彩 | Rec.709，Partial range |
| 音频 | AAC，48 kHz，Stereo；当前简单输出为 192 kbps |
| 音源 | 全局 WASAPI 桌面音频开启；Mic/Aux 关闭且静音，游戏采集自身 `capture_audio=false` |
| 禁止项 | `capture_cursor=false`、`capture_overlays=false`；无 OBS/任务栏/桌面/系统鼠标进入 game capture |

旁白和 BGM 不在 T17 raw 中后加；本 take 只需保留游戏自身 hover/点击音效，后期
按导演规范压低环境声。录制前同时静音 TTS/通知/其他桌面应用，避免全局 WASAPI
把非游戏声音写进 raw。录制开始前确认 OBS 正在 `场景 3`，预览中只有游戏画面，
没有训练 overlay、`MODDED`/debug 标签或 loading。

## 正式真实点击序列

建立 recording mark 后，源文件只保留一条连续操作链。目标是约 14 s raw（2 s
preroll + 4 s scroll + 2 s hover + 4 s result hold）；最终给 `S10-04` 取一段
连续 12 s 展示窗口。实际秒数以帧和单调时钟为准，不为凑时长硬剪操作中段。

| 相对时间 | 操作 | 现场要求 |
| --- | --- | --- |
| `0.0–2.0 s` | 无输入，clean preroll | 完整卡组 HUD/卡框可读；至少两张路线牌已在画面中；没有 console/tooltip 残影 |
| `2.0–6.0 s` | `game_ui_scroll`：鼠标停在卡组网格内，真实滚轮向下（必要时一次连续拖动原生滚动条） | 以当前滚动条/网格为准，不用固定坐标；让至少两张绯彩牌从网格中可辨地出现；滚动动画保持 1×，不切镜 |
| `6.0–8.0 s` | `game_ui_hover`：移动到一张路线核心牌并停留 | 推荐 `三色轮舞`，备选 `血色守恒律`/`光谱积分`；hover ≥1.5 s，tooltip 标题、牌图和关系文字完整，不被字幕/底部 UI 遮挡 |
| `8.0–12.0 s` | 无输入，结果保持 | tooltip 与至少两张路线牌保持 3–4 s；若网格动画尚未落定，延长到稳定后再停录，不超过必要范围 |

鼠标坐标只是证据元数据；OBS 不录系统指针，画面必须依靠游戏自身 hover 高亮和
tooltip 反馈。不要点击卡牌打开第二层详情（除非当前 UI 必须点击才能显示 tooltip，
且要在 mark 前排练清楚），不要在正式 span 中排序、搜索、切换窗口或再次开控制台。

### EDL 取段规则

T17 是 montage，不要求像 T03/T16/T18 那样把卡牌效果做成“从点击到结算”的
机制链；但 `game_ui_scroll` 与 `game_ui_hover` 本身必须是连续真实输入。优先把
`2.0–14.0 s` 的 12 s clean span 交给 `S10-04`，确保包含滚动、完整 hover 和
至少 3 s tooltip 尾巴。如果实际滚动较短，允许从 1.5 s 开始取连续 12 s，但
不得把 mark 前 setup、控制台、排序动画或另一 run 拼入 source span。原始 MKV
和任何 CFR 副本都追加保存，不能覆盖原片。

## 证据与 take manifest

T17 最小证据按 storyboard 四个 ref 交付；建议把更细的操作记录嵌入两个 manifest，
而不是伪造不受 binder 支持的 card action sidecar：

1. `T17-frame-begin`：mark 后第一张完整网格帧的 PNG，记录 `frame`、source 相对
   时间、raw SHA-256；四角无 OBS/console/鼠标。
2. `T17-runtime-manifest`：当前编译版本、mod/build hash、session/run/process
   identity、画面类型（deck view 或 card library）、实际可见卡牌
   `{id,title}` 列表、scroll/hover 的单调时间和 frame 区间。至少两项 ID 必须
   是本次画面实际可读的 `VIVHITE_CARD_…`。
3. `T17-lineage`：把 raw artifact → clean source span → `S10-04-crimson-route`
   的关系写清，注明 `setup_provenance=staged_setup`、`formal_action_source=true`
   （游戏 UI 操作真实发生）和 `formal_action_claimed=false`（不声称机制结算）。
   绑定 raw/source bytes、SHA、录制起止帧、EDL source in/out、OBS/game identity。
4. `T17-frame-end`：结果保持结束后的 PNG；tooltip/网格仍可读，且与
   `frame-begin` 属于同一 raw、同一进程。

可另存 `T17-ui-observation.json`（角色/卡牌标题、实际滚轮方向、hover bbox、
pointer down/up、settled frame）作为审计辅助，但其 `role` 应为
`runtime.observation` 或 `ui.observation`，不要把 `game_ui_scroll`/`game_ui_hover`
硬塞进 `production_binder_v2` 的 `action_evidence`：当前 binder 的 UI action 枚举
只接受奖励、地图、休息、购买及历史商店控制，不接受这两个浏览动作。若没有 native
state.before/receipt/after，就不要伪造严格 action sidecar；T17 的 storyboard 不
要求它们。

所有 evidence row 都要有 `status=verified`（或 binder 允许的 `bound`）、path、
bytes、SHA-256；`staged-setup.json` 可作为内部审计文件，但不能出现在 T17 的
display evidence 或 EDL。记录 `recording.start_frame`、`recording.end_frame` 与
单调时钟，并满足：

```text
staged_setup.setup_end_frame < recording.start_frame <= display.begin
display.begin < scroll.begin < hover.begin < hover.end <= display.end
display.end - display.begin >= 12 s（若作为 S10-04 的 12 s source window）
```

## 通过/判退门

### 通过

* 同一新 raw、同一游戏进程/会话和同一 OBS 录制身份；技术 probe 为
  1920×1080、60 FPS、H.264/yuv420p、AAC 48 kHz 双声道。
* mark 后 2 s 完整 HUD；真实滚轮使至少两张当前绯彩牌可辨地出现；真实 hover
  至少 1.5 s，tooltip 标题和关系文字可读；结果尾 3–4 s。
* `T17-runtime-manifest` 的 ID/中文标题与当前 C#/本地化一致，未混入旧占位牌或
  Ironclad replacement；画面无 console、Brain/AI、ASCEND-VISION、MODDED/debug、
  OBS、任务栏、系统鼠标和 loading。
* `T17-lineage` 能闭合 raw、12 s source span 与 `S10-04`，并明确没有平衡性绝对
  承诺或「必然无限成长」的旁白事实。

### 判退（保留 raw，不覆盖）

* 只有一张路线牌、牌名/tooltip 不可读、滚动没有实际变化，或静态网格连续超过
  4 s；
* `card …`、排序、搜索、控制台、暂停、窗口切换或任何调试/训练面板出现在
  recording mark 之后；
* 出现旧 `VIVHITE_CARD_VIVHITE_STRIKE`/旧占位设计、`铁甲战士`、旧录像、系统
  鼠标、OBS/任务栏或 loading；
* source 跨两个 run/process、缺任一最小 evidence、raw/probe/hash 不闭合，或为了
  凑 12 s 从不同 take 拼接；
* 旁白/字幕把这段画面说成已经完全平衡、必然无限成长，或把 T17 冒充 T16 的
  phase/结算证据；「61 张」只在 T19/T20 的独立证据中出现。

判退后把 attempt manifest、raw、probe、抽帧和失败原因写入新 attempt 目录，并
在进度 doc 追加一行；下一次必须重新读取本文件、`capture-runbook.json`、
`storyboard.json` 和最新进度，不得从判退片段剪出正式素材。

## 中断恢复交接

1. 列出最新 `tools/promo/runs/<run-id>/capture/takes/T17/*`，确认没有正在写入的
   MKV；若录制状态不明，宁可新建 attempt，不向旧文件续写。
2. 核对游戏 PID/创建时间、`VIVHITE_PROMO_CAPTURE=1`、Vulkan、OBS PID/创建时间、
   scene/source/window 和输出目录；任何一项不明都先做只读截图/日志核对。
3. 重新执行 mark 前 staged_setup；旧 attempt 的卡组/筛选状态不能当作新 attempt
   的事实。把 `setup_end_frame`、clean checkpoint 和本次实际可见卡牌写清。
4. 录制结束立即复制/探测 raw，生成四个 evidence 文件和 `T17-ui-observation`
   （若采用），计算 SHA-256，写入 take row；先逐帧检查禁项，再交 production
   binder。不要以“画面看起来像”替代 runtime manifest。
5. 任何失败都保留全部现场和日志；只有新的 raw + 完整 evidence + 12 s 连续 span
   通过后，才把 T17 状态从 `capture_pending` 更新为可供 EDL 的 production row。
