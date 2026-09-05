# T19/T20 可执行录制交接单

> 用途：给下一位录制人员一份可以从零恢复的 T19（61 张专属卡牌浏览）和 T20（白绮主标题/idle 收束）操作单。
>
> 本文是录制 recipe，不是新的分镜定义；canonical storyboard 仍以 tools/promo/v2/storyboard.json 为唯一接口。
>
> 2026-09-04 编写时仅做了源码、日志和历史截图的只读核对，没有启动或操作游戏、OBS，也没有产生新的 take。

## 0. 范围与对应分镜

| take | 画面用途 | canonical subshot | 目标展示时长 | 可否从同一 raw take 取多个窗口 |
|---|---|---|---:|---|
| T19 | 牌库/卡组浏览，建立 61 张和三条构筑路线的视觉印象 | S10-01-card-library（448–462 s） | 14 s | 否；浏览动作应是一段连续 span |
| T20 | 白绮轮廓、标题桥接、idle、CTA 收束 | S01-06-question-bridge、S01-07-main-title、S01-08-main-title-continuation、S10-10-idle-cta、S10-11-version-and-workshop-status | 12 s / 5 s / 5 s / 12 s / 7 s | 是；只能取同一份新 raw take 的不同干净窗口 |

T20 不得用于三套构筑路线；T19 不得被剪成角色选人或标题素材。两者都必须使用本地当前编译版本的真实 UI，旧截图和旧录像只能帮助找界面，不能进入成片。

## 1. 已核对的事实（只读基线，不替代新证据）

### 1.1 Mod 运行时身份

- Vivhite/VivhiteCode/Characters/VivhiteCharacter.cs：StartingHp => 78、StartingGold => 99、MaxEnergy => 3。角色选择标题来自 zhs localization，独立标题必须是“白绮”。
- Vivhite/VivhiteCode/Relics/SolitaryCrown.cs：RegisterCharacterStarterRelic(typeof(VivhiteCharacter))；Vivhite/Vivhite/localization/zhs/relics.json 的标题是“孤高冠冕”。
- Vivhite.Tests/ApprovedCardCatalog.cs 的批准目录为 61 个 ID，稀有度为 3 Basic、18 Common、24 Uncommon、16 Rare。VIVHITE_CARD_POOL 是当前卡池 ID。
- 当前 manifest 基线是 Vivhite/Vivhite.json v0.2.1、游戏 v0.111.0、RitsuLib 0.5.14；录制时仍须把实际 build/mod hash 写进新的 runtime manifest，不能只引用这些文字。
- 历史 Godot 日志的注册/dump 可见 61 个 VIVHITE_CARD_... ID 和 VIVHITE_RELIC_ORIGIN_STAR_CHART。这是诊断基线，不是 T19 的画面证据；每次正式录制都要重新导出/保存 runtime manifest。

### 1.2 牌库 UI 契约

- 原版 NCardLibrary 的 %CardGrid、%CardCountLabel、%SearchBar 和池筛选按钮由运行时创建。
- DisplayCards() 以当前可见卡数填充 CARD_COUNT；zhs 文案为 {Amount}张牌。因此选中白绮池且未加筛选时，画面上必须实际看到 61张牌（或当前语言对应的等价真实 count），不能后期叠字。
- NCardLibraryGrid.FilterCards() 对当前池的 _allCards 计数；未发现/未解锁卡会在 holder 上显示 locked/not-seen 状态，但不会把已注册且 ShouldShowInCardLibrary 的卡从 count 中悄悄扣掉。若 count 不是 61，应优先查池筛选、卡的 ShouldShowInCardLibrary 或部署版本。
- 从主菜单进入百科大全时，原版默认池通常是 Ironclad；必须现场点选 RitsuLib 注入的白绮图标。RitsuLib 的 mod filter 只保证图标/选中状态，不保证有叫“Vivhite”的文字 tooltip。
- mod filter 默认插在 Colorless 前，但按钮会按窗口宽度换行；坐标只能从当前帧重新量取。不要把历史 x/y 当固定 ABI。
- NCardGrid 使用原生 ScrollContainer/滚轮和动态 holder；滚动后等待 UI 停稳。不要依赖旧槽位或用快速拖拽制造不可读的卡名。
- 搜索框只覆盖已发现卡；搜索结果不能单独证明完整 61 张，正式证明以池筛选后的 count label + 新 runtime manifest 为准。

### 1.3 角色选择 UI 契约

NCharacterSelectScreen.SelectCharacter 会把当前角色的真实数据写入以下节点：

- InfoPanel/VBoxContainer/Name：独立角色名“白绮”
- InfoPanel/VBoxContainer/HpGoldSpacer/HpGold/Hp/Label：78/78
- InfoPanel/VBoxContainer/HpGoldSpacer/HpGold/Gold/Label：99
- InfoPanel/VBoxContainer/Relic/Name/RichTextLabel：孤高冠冕
- InfoPanel/VBoxContainer/Relic/Description：当前版本的遗物说明
- InfoPanel/VBoxContainer/DescriptionLabel：白绮角色描述

选择变化有约 0.5 s 的信息面板 tween。正式标记前至少等面板稳定；只要出现“铁甲战士”、??/??、??? 或旧战士立绘残留，该次 T20 直接作废。

### 1.4 可复核的源证据索引

以下路径用于中断交接时复核契约；它们不能代替正式 raw 的 frame/manifest：

- 起始属性：Vivhite/VivhiteCode/Characters/VivhiteCharacter.cs（StartingHp、StartingGold）。
- starter relic：Vivhite/VivhiteCode/Relics/SolitaryCrown.cs（RegisterCharacterStarterRelic）及 Vivhite/Vivhite/localization/zhs/relics.json。
- 61 卡黄金目录：Vivhite.Tests/ApprovedCardCatalog.cs；当前运行时注册基线：C:/Users/xenoa/AppData/Roaming/SlayTheSpire2/logs/godot.log 的 Vivhite [Content] Registered card 段。
- 牌库计数实现：.work/sts2-decompiled-v0.111.0/MegaCrit/sts2/Core/Nodes/Screens/CardLibrary/NCardLibrary.cs 的 DisplayCards；计数过滤实现：同目录 NCardLibraryGrid.cs 的 FilterCards/RefreshVisibility。
- 角色选择字段：.work/sts2-decompiled-v0.111.0/MegaCrit/sts2/Core/Nodes/Screens/CharacterSelect/NCharacterSelectScreen.cs 的节点缓存和 SelectCharacter。
- 旧 UI 参考：.work/promo-capture-isolation/vivhite-select.png。该文件右上有版本/日期，永远只用于坐标和布局参考。
- 已知失败参考：.work/hybrid-v3-deploy/runtime-20260829-v3/character-select-independent-vivhite.png（白绮标题却为 75/75、白绸结并混入铁甲头像）以及 character-select-loop/t-0001ms.png（铁甲战士 80/80、燃烧之血配白绮立绘）。这些文件只用于说明错配模式，禁止进入素材链。

## 2. 全局录制和清洁门

1. 每次尝试使用新的 attempt_id，不得覆盖已有文件。建议 raw 路径：
   tools/promo/runs/run-20260903T0012-director-v2-a1/raw/takes/T19/<attempt_id>.mkv 或 .../T20/<attempt_id>.mkv。
2. 录制前只做 staged_setup：可预置界面、牌库筛选、角色高亮或路线；控制台/调试面板只能在正式 mark 前使用，不能进入 display span。
3. 采集参数固定为 1920×1080、60 FPS、H.264、yuv420p、AAC 48 kHz 双声道；游戏使用 Vulkan。录制结束立即保留原始 MKV，并用 ffprobe 确认实际参数。
4. 在干净界面上打 mark，随后保留约 2 s pre-roll；正式动作 1×速率。结果/idle 后保留 3–4 s。不要用后期补帧、冻结帧或假 HUD 补出缺失状态。
5. 成片 display span 中不得出现控制台、Brain/AI、ASCEND-VISION、OBS、MODDED/debug/version/RitsuLib 角标、任务栏、系统鼠标、loading screen、旧 Ironclad replacement 或旧占位卡。
6. 所有失败 raw、探针、截图、OCR、manifest 和哈希都保留；失败不覆盖成功候选。坐标是当前帧的起点提示，不是录制时可盲点的常数。

现场开始前可只读查看机器清单（不会启动游戏或录制）：

    $env:PYTHONPATH = (Resolve-Path .\tools\promo).Path
    py -3 -B -m vivhite_promo.capture_runbook_v2 show T19
    py -3 -B -m vivhite_promo.capture_runbook_v2 show T20

每次 attempt 结束后，再按 CAPTURE_RUNBOOK.md 的 validate 流程检查 probe、帧率和证据文件；不要在 recipe 中把“show”输出当成新的画面证据。

## 3. T19：61 张专属卡牌牌库/卡组浏览

### 3.1 目标与准备

T19 的主证明路径是“百科大全 → 白绮卡池”，因为只有这里有原生 61张牌 count。战斗中打开的临时卡组可以作为补充画面，但单独不能通过 T19 验收。

1. 从干净主菜单进入“百科大全”（或当前版本实际同义入口），确认是当前编译的 Vivhite，而不是旧安装目录。
2. 在筛选条现场定位白绮图标：优先看图标、选中描边和 card pool 变化；不要依赖文字 tooltip。RitsuLib 通常把它放在 Colorless 前，若换行则按当前截图重定位。
3. 清空搜索、稀有度、类型、费用等筛选；关闭会改变可见总数的升级/统计选项。确认 count label 原生显示 61张牌。若显示其他数字，先停止该尝试并记录原因；不得以字幕或后期图形覆盖。
4. 预览当前卡页并选出至少三组路线代表，按当前 tooltip 的真实标题辨认：
   - 守恒几何：VIVHITE_CARD_AXIOM_RING（公理护环）或 VIVHITE_CARD_LAW_OF_CONSERVATION（守恒定律）
   - 递归星算：VIVHITE_CARD_ASTRAL_PURSUIT（星算追猎）或 VIVHITE_CARD_PROOF_OF_TERMINATION（终止证明）
   - 绯彩积分：VIVHITE_CARD_TRICHROMATIC_WALTZ（三色轮舞）或 VIVHITE_CARD_CRIMSON_AREA（绯色面积）
   可选展示 VIVHITE_CARD_UNIFIED_FIELD_THEORY（统一场论）。这些是识别建议，不得用旧数值硬编码。
5. 在正式 mark 前完成滚动位置、筛选和代表卡的 staged setup，写下当前帧中白绮 filter bbox、count label bbox、代表卡 bbox 和 setup_end_frame。

### 3.2 连续正式动作（建议 raw 19–24 s，display 至少 14 s）

1. mark 后保留约 2 s 干净 pre-roll：count 和多张卡清楚可见。
2. 在 card grid 上使用原生滚轮/ScrollContainer，以 1×速度浏览至少一页；滚动后等待卡面稳定，不要把名称滚成一片模糊。
3. 依次把鼠标悬停在守恒、递归、绯彩代表卡上，每张 tooltip 至少保持 1.5 s；若需要移动到下一页，保留自然过渡。tooltip 必须显示当前版本标题/描述，数值以游戏实际呈现为准。
4. 结束时保留 3–4 s 稳定结果，至少同时看见原生 count 和一组代表卡/tooltip。任何无输入、无动画、无可见状态变化的片段不得连续超过 4 s。
5. 停止录制并保留整个连续 raw；不要把三张卡从不同 raw 拼成“单次浏览”，也不要点击卡牌详情来掩盖不可读的 hover。

### 3.3 T19 证据包

至少保存以下独立文件（路径写入 run index）：

- T19-frame-begin：display span 首帧，含白绮 filter、61张牌和 UI 清洁检查。
- T19-runtime-manifest：run/session、游戏进程和 recorder 身份、build/mod hash、UI route、VIVHITE_CARD_POOL、count=61、完整 61 ID 列表/哈希、当前筛选、代表卡 {id,title}、滚动/hover 时间和 bbox、raw 路径与 SHA-256。
- T19-tooltip-ocr：至少一张守恒、一张递归、一张绯彩 tooltip 的截图/OCR 及各自路径、字节数、哈希；OCR 仅作辅助，画面本身仍须可读。
- T19-frame-end：display span 末帧，含结果 tail 和清洁检查。
- 可选 T19-ui-observation.json：记录 filter/count/scroll/hover 的 UI 观察、截图引用和 staged setup。

T19 的滚轮和 hover 属于 UI 观察，不在当前 production-binder 的 reward/map/rest/buy formal action 枚举中；不要为了“补 sidecar”伪造 state.before、action.receipt、state.after。若以后 binder 扩展，沿用真实 UI observation 和同一 raw 哈希。

### 3.4 T19 验收/作废

通过条件：

- 原生白绮池 count 明确为 61；新的 runtime manifest 能对上 61 个当前 ID。
- 三条路线至少各有一张当前 tooltip 标题可辨认，滚动/hover 是同一段 1×连续动作。
- ffprobe、帧率、分辨率、音频和 source hash 合格；display span 无禁用界面。

直接作废：

- count 不是 61，或只有搜索结果/字幕声称 61；
- 出现 VIVHITE_CARD_VIVHITE_STRIKE、旧白绮防御/白绸结等占位 ID，或任何 Ironclad 卡池/标签；
- 快速滚动导致标题不可读、鼠标/系统 UI 录入、卡页静止超过 4 s；
- 证据缺文件/哈希不一致、raw 被覆盖、后期叠加伪造数值。

## 4. T20：白绮主标题轮廓与 idle 收束

### 4.1 首选路线：角色选择

1. 从干净主菜单进入“单人模式”→“标准模式”。历史截图中标准模式卡大致位于 x=389–737、y=190–873（中心约 563,531），仅作起点；现场必须重新 hover/截图确认。
2. 在角色列表用现场鼠标或左右键移动高亮到白绮；历史截图中的白绮缩略图约 x=1200–1290、y=885–1018，仅作起点。以信息面板真实文本为准。
3. 等待约 0.5 s tween 完成，完整看到：独立“白绮”、78/78、99、孤高冠冕、遗物描述和角色描述。不要裁掉角色名、属性或遗物。
4. 在上述身份画面稳定后打 mark；T20 的标题轮廓、问题桥接和 CTA 都从这一份新 raw take 取干净窗口。不要为 T20 点击确认按钮；若必须为别的 take 确认，须在 T20 display span 结束后再点，不能把黑场/loading transition 当 idle。

如果角色选择动画在当前版本不可稳定采集，才可使用干净战斗 idle 作为备选；备选仍须能证明白绮身份和负空间，不能用静态卡牌页或旧战士皮肤冒充。

### 4.2 正式窗口

1. mark 后约 2 s pre-roll，保留全画面角色选择动画/idle，不裁切、不放大到看不见名字和属性。
2. 录制 6–8 s 的完整立绘/idle 循环，给标题轮廓和开场白 J-cut 留负空间。后期允许 5–8% 数字推近，但原始画面必须完整。
3. 建议 raw 至少 19 s（2 s pre-roll + 最长 12 s CTA source window + 3–4 s tail），推荐 19–30 s。继续保留若干干净 idle 窗口，供 question bridge、标题延续和 finale CTA 使用；窗口可以在同一 raw 内有意重叠，但每个 source span 必须分别精确对应 6/5/5/12/7 s 的 storyboard 时长，不能把不同版本或旧录像混剪。
4. 结束后留 3–4 s idle tail。T20 是 montage（uncut_action=false），但不能用黑场、loading 或静帧假装动画。

### 4.3 T20 证据包

- T20-frame-begin / T20-frame-end：含清洁检查和身份文字的起止帧。
- T20-runtime-manifest：run/session、进程/recorder、build/mod hash、character ID、标题“白绮”、HP 78/78、gold 99、starter relic 孤高冠冕、raw 路径和 SHA-256、各窗口起止时间。
- T20-lineage：把同一 raw 的窗口映射到 S01-06/S01-07/S01-08/S10-10/S10-11；禁止跨 raw 偷换角色身份。
- T20-workshop-status-receipt：在组片时由当前本地/Steam 只读元数据生成并哈希绑定。不得在 raw 中手写“已发布”或虚构 Workshop 状态；模板字段只接受真实 receipt。

### 4.4 T20 验收/作废

通过条件：

- 角色选择信息面板完整且稳定显示“白绮 / 78/78 / 99 / 孤高冠冕”，动画和负空间可用。
- 同一新 raw 能提供标题、桥接、idle、CTA 的清洁窗口；技术探针和证据哈希一致。
- 不依赖确认后的黑场/loading，不带版本角标、debug、鼠标或旧皮肤。

直接作废：

- 任意帧出现“铁甲战士”、旧 Ironclad residual、??/??、???、错误遗物或被裁掉的身份字段；
- 只有静态卡页、loading/黑场、系统鼠标/OBS/Brain/AI/版本层；
- Workshop 文案没有真实只读 receipt，或用后期文字掩盖缺失的运行时身份。

## 5. 坐标和现场重定位表

下表是历史截图的起始提示，不是固定点击契约。每个正式 manifest 必须记录当前帧测得的 bbox、中心点、帧号和截图哈希。

| 控件/区域 | 历史起点提示 | 重定位方法 |
|---|---|---|
| 主菜单“百科大全” | x≈770–820, y≈934–955 | 现场 hover 后看按钮高亮和 OCR；不使用历史截图作素材 |
| 主菜单“单人模式” | x≈770–820, y≈780–810 | 现场 hover，确认进入标准模式 |
| 标准模式卡 | bbox≈(389,190)–(737,873)，中心≈(563,531) | 以当前按钮高亮/文字为准 |
| 白绮角色缩略图 | x≈1200–1290, y≈885–1018 | 用左右键或现场 hover，确认信息面板 |
| 角色选择确认 | 中心约 (1835,780) | T20 不点击；其他 take 只能在 T20 span 结束后点击 |
| 牌库白绮 filter | 预计位于 Colorless 前，可能换行 | 看图标、选中框和 count 变化；每次截图记录 bbox |
| 牌库 grid | 历史常见列中心约 x=400/680/960/1240/1520，行 y≈300/680 | 只在 live frame 上找 card holder；滚轮必须位于当前 ScrollContainer |

## 6. 中断后的恢复顺序

1. 先读最新 progress、run index 和本 recipe，确认没有正在写入的 MKV；不要复用不明状态的 attempt。
2. 只读核对游戏窗口/进程和 session；身份或版本不确定时，新建 attempt_id。
3. 从 staged setup 重新开始，重新写 setup_end_frame、filter/角色 bbox 和当前 count/身份；不要把旧截图当新门禁。
4. 启动独立 OBS 输出路径，打 mark，按对应 T19/T20 连续序列录制；失败也保留 raw。
5. 立即 ffprobe、抽帧、OCR、runtime manifest、lineage 和 SHA-256；把证据路径回报给主任务并更新进度文档。
6. 不修改 tools/promo/v2/storyboard.json，不删除历史失败包，不把旧 Ironclad 或旧占位素材重新纳入链路。

## 7. 修订记录

- 2026-09-04：初版。完成 Vivhite 78/78/99/孤高冠冕、牌库原生 count、61 卡 catalog、RitsuLib filter、T19/T20 分镜映射和现场坐标提示的只读核对；本次未启动游戏/OBS，未录制素材，未修改 canonical storyboard。
- 2026-09-04：补充 NCardLibraryGrid.FilterCards/_allCards 计数语义，明确未发现卡的 locked/not-seen 状态不会单独解释 count 缺失。
- 2026-09-04：补充可复核的源码、运行日志和历史 UI 参考路径索引。
- 2026-09-04：补充不启动游戏的现场清单命令和 attempt 后 validate 提醒。
- 2026-09-04：修正 T19 raw 时长建议为 19–24 s，使 2 s pre-roll + 14 s display + 3–4 s tail 的下限一致。
- 2026-09-04：补充 T20 raw 至少 19 s、最长 CTA source window=12 s，以及同一 raw 内允许重叠但各 subshot span 必须精确对齐 storyboard 时长。
- 2026-09-04：标注两份历史角色错配帧（75/75+白绸结、80/80+燃烧之血）为明确失败参考，避免误选。
