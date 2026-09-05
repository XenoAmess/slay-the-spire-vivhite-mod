# 白绮宣传片生产工具

当前生产主线是 **导演 v2（540 秒、多个独立 take）**，入口见
[`v2/README.md`](./v2/README.md) 和 [`v2/storyboard.json`](./v2/storyboard.json)。本文后半的
600 秒 full master、a4 与从 a4 派生的短版均为保留的 **v1 兼容/失败参考**，
不得作为 v2 机制镜头、旁白或 EDL 的来源。实际录制、导出与人工复核状态见
[`制作进度`](../../docs/2026-09-02-白绮宣传片-v2-制作进度.md)；离线源码测试不会
自动启动游戏、OBS、录制、TTS 或渲染。

这里是白绮宣传视频的**项目侧**适配层。它把 STS2 的录制产物转换为
`xar_promo_toolchain` 能够审计的媒体、时间线和证据；它不把游戏逻辑、录屏器
或 Brain 运行时塞进 xAR 通用核心。

## 目录和责任边界

源码、测试、分镜/旁白输入及采用素材的制作配方纳入 Git；真实媒体与单次运行现场留在
已忽略的 `runs/<run-id>/`。不要整目录忽略 `v2/` 或通配忽略 `archive_*.py`。
2026-09-05 的旧试拍脚本、根目录临时截图和扫描日志已保全迁入 run，恢复清单与
具体边界见 [`工作区归档记录`](../../docs/2026-09-05-宣传片工作区归档与提交边界.md)。

```text
tools/promo/
├─ v2/                                     # 540 秒导演版 storyboard 与交接入口
├─ vivhite_promo/                         # 白绮 adapter/preset/composer
│  ├─ director_v2.py                    # v2 storyboard/take manifest/多源 EDL 离线门
│  ├─ action_evidence_v2.py             # 正式动作三联证据门
│  ├─ title_cards_v2.py                 # xAR TitleCardSpec 项目侧工厂
│  ├─ media_gate_v2.py                  # 540s/32,400 帧成片 ffprobe 门
│  └─ semantic_audit.py                    # 项目侧 claims/证据语义门禁
├─ schemas/vivhite-promo-action-evidence-v2.schema.json
├─ schemas/vivhite-promo-capture-v1.schema.json
├─ fixtures/minimal_capture/              # 离线、极小的契约 fixture
├─ claims/claims.json                     # 白绮语义主张及证据角色
├─ project.json                            # 项目配置
├─ capture-settings.json                  # 原生 surface/OBS/FFmpeg/音频固定策略
├─ storyboard.json                         # 镜头与时长
├─ pyproject.toml                          # xAR entry points
├─ preflight.ps1                           # 只读预检
├─ configure_obs.ps1                       # OBS 配置预演/备份后应用
├─ isolate_capture_mods.ps1                # 可逆隔离游戏内 overlay/Workshop 污染
└─ tests/                                  # 不启动游戏的契约测试
```

白绮侧负责以下内容：OBS/窗口录制、Vulkan 游戏状态、卡牌和关键词语义、
镜头编排、旁白/翻译、素材禁用规则，以及 Mod/PCK/Workshop 版本证据。

xAR 侧只负责通用的 receipt、artifact 哈希、证据角色、Storyboard、字幕、
渲染/混音计划、技术 audit、review、signoff 和离线 export。不要在这里复制
xAR 的 TTS、渲染器或证据实现，也不要将白绮素材或绝对本机路径提交到 xAR 仓库。

## 只读预检

从白绮仓库根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\promo\preflight.ps1
```

预检会检查：

- 项目文件、schema、adapter/preset/composer 和 xAR entry point 是否存在；
- `minimal_capture` 的 JSON 身份、相对路径、文件长度及 SHA-256；
- 1920×1080/60 FPS/Vulkan，第三方/Mod overlay 的
  `overlays_absent`，以及 `loading_absent`、`console_absent` 是否明确为
  `true`；
- STS2 原生版本/日期/`MODDED` 标签是否通过独立的
  `native_debug_surface_*` 字段声明为已隐藏，而不是被
  `overlays_absent` 顺带冒充；
- JSON 中没有绝对路径、路径逃逸、用户目录或凭据样式字符串；
- FFmpeg、ffprobe、OBS 是否可用（默认仅警告）。

在正式取景前，把依赖缺失升级为失败：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\promo\preflight.ps1 -RequireExternalTools
```

如果需要同时跑离线契约测试：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\promo\preflight.ps1 -RunTests
```

`-RunTests` 只执行 `unittest`，使用临时目录和合成字节；它不会启动
Slay the Spire 2、Steam、OBS、录屏器、Brain 或直播脚本。`-Json` 可输出给 CI：

```powershell
.\tools\promo\preflight.ps1 -Json | ConvertFrom-Json
```

## Capture contract v1

`schemas/vivhite-promo-capture-v1.schema.json` 描述项目侧契约。其 canonical wire
shape 是根对象中的 `capture_receipt`，不是旧文档里的 `media` 或顶层 evidence。
典型根对象包括：

- `format_version: 1`、`kind: "vivhite_promo_capture"`、`contract_version: 1`、
  `mode: "vivhite-promo"`、`producer_id`、`run_id`；
- `capture_receipt.producer`，以及
  `capture_receipt.raw_capture`（相对 `artifact_root` 的文件绑定：`path`、`bytes`、
  `sha256`，可选 `media_type`）、`duration_seconds` 和 `timebase`；
- `capture_receipt.marks`：单调递增的边界标记，首个标记为
  `recording_started_after_gameplay_hud`，并包含
  `recording_stop_requested` 停止边界；
- `capture_receipt.clean_spans`：每个 span 绑定 begin/end mark、`natural` 或
  `staged` provenance，以及该 span 自己的 `evidence` 数组（每项是 `role` 加同样的
  artifact 文件绑定）；
- 根级 `shot_bindings`：把宣传 shot ID 映射到已验证的 clean span；
- 可选根级 `audio_stems`：每项以 `stem_id` 和相对路径、字节数、SHA-256 文件绑定
  描述 game、SFX、BGM 或旁白分轨；
- `project_context`：游戏、Mod、PCK 和 RitsuLib 的版本/身份，Vulkan、分辨率、帧率，
  以及必须为 `true` 的 `overlays_absent`、`loading_absent`、`console_absent`。
  这里的 `overlays_absent` **只表示第三方/Mod overlay 不存在**，不包含 STS2
  自己绘制的右上角版本、日期和 `MODDED` 标签。原生标签由
  `native_debug_surface_hidden`、`native_debug_surface_method` 和
  `native_debug_surface_evidence_role` 单独描述。

v1 解析器仍可读取没有 `native_debug_surface_*` 的旧 receipt，但“缺失”只表示未知，
绝不等于隐藏；生产 adapter 必须看到 `native_debug_surface_hidden=true`、方法
`vivhite-promo-capture-surface-v1`，以及一个确实出现在 clean-span evidence 中的
hash-bound evidence role 才会放行。`false`、字段缺失、方法不匹配或未闭合的 role
都保持 RED。

`load_capture_contract(path, *, artifact_root=..., verify_files=True)` 会读取并
校验 receipt 中的原始媒体、clean-span evidence 和（若提供）audio stem 文件绑定；
`validate_capture_contract(payload, artifact_root, *, verify_files=True)` 执行同一契约
校验。有效对象的 `verify_unchanged()` 可在 preserve、build 或审计前再次确认所有已
绑定文件没有被替换。任何录制重试都使用新的 `run_id`/attempt；不得覆盖已有 raw、
partial、日志或证据。

通用 xAR 不解释 `natural`、`staged`、卡牌名称或 HP 数值。白绮 adapter 只把
经过语义检查的 span 投影为 xAR 的 `CaptureReceipt`/`VisualSource`；“画面里的
 机制为什么是真的”由 `claims/claims.json` 和白绮 validator 证明。

## 白绮语义审计门禁

`vivhite_promo.semantic_audit` 是项目侧的只读 gate。它在已加载的
`VivhiteCaptureContract` 上检查三条边：`claims[*].source_refs` 必须是项目根内
真实存在的路径；每个 claim 的 `shot_ids` 和 `evidence_roles` 必须闭合到对应
clean span；每个 claim 还必须有项目 validator 明确返回的 `pass` 结果。捕获文件
会在审计前再次执行 `verify_unchanged()`，因此过期或被替换的证据保持 RED。

推荐在构建前显式注入白绮自己的 validator（它只解释白绮机制，不进入 xAR）：

```python
from vivhite_promo.semantic_audit import enforce_semantic_gate

report = enforce_semantic_gate(
    "tools/promo/claims/claims.json",
    candidate.contract,
    project_root=repo_root,
    validator=validate_vivhite_claim,  # (claim, contract, project_root) 也可
)
```

validator 也可以是一份按 `claim_id` 索引的结果 sidecar（`pass`/`fail`/`pending`）。
没有显式结果时，即使 ledger 的 `status` 写成 `verified`，默认仍不能通过；只有
迁移旧的、已在项目外独立验收的 ledger 时才可显式使用
`allow_declared_verified=True`。`pending`、`fail`、缺失结果、路径逃逸和缺证据都会
阻断。`approved`、`review`、`signoff` 或 xAR technical-audit 对象不是 semantic
validator result，永远不会被这里自动转换为通过；本 gate 也不会写 manifest、review
或 signoff。

适配器提供同一入口，便于保持项目身份和 claims 路径集中管理：
`adapter.audit_semantics(candidate, validator=...)`（别名
`adapter.semantic_audit`）。该调用只返回结构化 `SemanticAuditReport`；生产脚本应
在继续 preserve/build 前调用 `report.raise_if_blocked()` 或
`enforce_semantic_gate`。

## 清洁画面门禁

正式录制必须使用精确游戏 HWND/Game Capture，并确认：

- 外置 ASCEND-VISION viewer 已在该 capture session 禁用；
- 游戏内 STS2AIAgent CanvasLayer、AI edge tab、第三方调试面板和 overlay 均不可见，
  并在 contract 中只用 `overlays_absent` 表达这一层；
- STS2 原生右上角版本/日期/`MODDED` 标签另行确认不可见，并把运行期开关和结果写入
  `runtime.manifest` 等 hash-bound evidence；
- 没有 loading、主菜单等待画面、控制台、鼠标/任务栏/Steam 提示；
- 游戏、旁白、SFX 分轨保存；首片 `BGM=disabled`，不得提交或混入 BGM stem，后续如授权再由 xAR 多轨计划加入；
- 录制前后用 `ffprobe` 复核分辨率、帧率、时长、编码、采样率和声道。

截图/OCR 工具只能产生辅助证据，不能代替连续视频录制。不要调用
`Start-Agent.ps1`、Bilibili 入口或自动 Brain 来“生成”确定性宣传镜头；宣传录制
与训练/直播是独立生命周期。

### OBS 配置

`configure_obs.ps1` 默认只读检查当前 OBS 配置；只有明确传入 `-Apply` 才会在 OBS
进程已关闭时写入。脚本会先把当前活动场景、profile 和 `global.ini` 复制到
`.work/obs-backups/<UTC 时间>-<唯一后缀>/`，再设置精确的 Slay the Spire 2
Game Capture、1920×1080、60 FPS、隐藏鼠标和 overlay。当前固定窗口匹配为
`Slay the Spire 2:Engine:SlayTheSpire2.exe`；活动场景中不允许 monitor/display
capture。录像使用 NVENC H.264、MKV、AAC 192 kbit/s、48 kHz 双声道、单轨输出。
它不会启动 OBS、游戏、直播、WebSocket 或 Brain，也不会修改 Windows 系统音频端点。

```powershell
# 只读预演
.\tools\promo\configure_obs.ps1 -Json

# 关闭 OBS 后，明确应用并保留备份
.\tools\promo\configure_obs.ps1 `
  -RecordingPath 'G:\OBS_VIDEOS\vivhite_capture_20260902' `
  -Apply -Json
```

当前 OBS 32.2.2 不包含 Game Capture 的进程音频源，因此配置将
`capture_audio` 明确保持为 `false`，只启用一个全局 WASAPI 输出源（麦克风关闭，避免重复和漂移）。
`use_device_timing=false`，Game Capture 的 `capture_cursor=false`、
`capture_overlays=false`、`anti_cheat_hook=true`、`hook_rate=1`。这里的
`capture_overlays=false` 只控制 OBS 能控制的 overlay，不能隐藏游戏自己绘制的 UI。
正式取景前必须做一段短录并用 `ffprobe`/试听确认游戏声；不能把 OBS 的“正在录制”状态当作音频已录入的证明。

如果 `STS2AIAgent` 仍部署，它会留下右侧 `AI` 边签；OBS 的
`capture_overlays=false` 无法移除它。Workshop `LieRenTVmod` 也会改动选人/背景资源。
正式录制前先停止游戏并运行可逆隔离脚本，确认这些已知污染 payload 已经移出：

```powershell
.\tools\promo\isolate_capture_mods.ps1 -Apply -Json
# 启动 Vulkan 游戏；如出现原生模组同意框，由操作者在游戏内确认
# 所有取景完成、游戏退出后：
.\tools\promo\isolate_capture_mods.ps1 -Restore -Json
```

脚本只移动这四个已知污染目标（STS2AIAgent 三件套及 LieRenTVmod Workshop 目录），逐文件保存 SHA-256 到
`.work/promo-capture-isolation/`，绝不删除、覆盖或触碰存档及其他 Mod。

### STS2 原生 debug surface

STS2 v0.111.0 的右上角版本、日期、RitsuLib/`MODDED` 标签由游戏场景自己绘制，
不是 OBS overlay，`capture_overlays=false` 和 `overlays_absent=true` 都不能证明它们
消失。白绮 Mod 提供仅宣传录制时启用的 `PromoCaptureSurface`：先部署当前构建，再在
启动同一个 Vulkan 游戏进程前设置：

```powershell
$env:VIVHITE_PROMO_CAPTURE = '1'
& 'G:\SteamLibrary\steamapps\common\Slay the Spire 2\SlayTheSpire2.exe' `
  --rendering-driver vulkan
```

普通启动不设置该变量，原生警告保持不变。正式 take 必须同时保存启动/runtime manifest
和开始/结束画面证据；只有日志确认 patch 已安装、实际 Game Capture 画面确认标签不可见，
contract 才能写 `native_debug_surface_hidden=true`。对应方法固定为
`vivhite-promo-capture-surface-v1`，evidence role 应指向该次 run 已绑定的
`runtime.manifest`。如果 patch 安装失败或画面仍有标签，保留失败 take 并创建新 attempt；
不得通过裁切、模糊、遮罩或把 `overlays_absent=true` 改写成“已隐藏”来绕过门禁。

本机已将 FFmpeg 9.0.1 覆盖安装到既有目录 `C:\ffmpeg\bin`；其
`ffmpeg.exe`/`ffprobe.exe` SHA-256 见 `ffmpeg-lock.json`，并由预检同时验证 xAR
图需要的 `tpad` 过滤器。若确有迁移需要，旧的并排目录可作为临时诊断来源，但
`-RequireExternalTools` 会拒绝缺少 `tpad` 或不匹配锁定 SHA-256 的版本。若路径不同，
可显式设置 `XAR_PROMO_FFMPEG`（以及 `XAR_PROMO_FFPROBE`）；首片按项目决策不加入 BGM，
旁白、游戏声和 SFX 仍应以独立 stem 保存，最终混音由 xAR 计划生成。

## 离线测试

```powershell
# 推荐 Python 3.11+；不需要安装游戏或 Steam
py -3 -B -m unittest discover `
  -s .\tools\promo\tests -p 'test_*.py' -v
```

测试覆盖 schema 和 entry point、fixture 文件绑定、路径逃逸、篡改检测、非单调
marks、清洁画面字段，以及 composer 的 `validate_only=True` 不得启动外部进程。
测试会从仓库本地路径导入 adapter；不要求将媒体复制到 Git，也不执行网络请求。

## 生产流水线

```text
外部录制 producer
  → Vivhite capture-contract/语义校验
  → xAR preserve
  → xAR plan/build（字幕、混音、渲染）
  → xAR 技术审计
  → Vivhite 语义审计（卡牌/版本/禁用素材）
  → 人工 review
  → signoff
  → export
```

下述旧流程的首片目标是 1920×1080 横屏约 10 分钟，现仅作 v1 兼容说明。
v2 的权威规格是 540 秒；60/30/15 秒版本必须分别从同一批 v2 新 take
生成独立 EDL。技术审计通过不等于白绮语义审计或人工发布批准。

### 当前录制的候选短片

项目侧 `render_capture_candidate.py` 只接受与原始录屏同一 run 的哈希绑定
capture contract，并且会在渲染前后重新校验原始字节和 clean span。它只生成
`preliminary` 候选，不执行语义审核、人工 review、signoff 或发布：

```powershell
py -3 -B .\tools\promo\render_capture_candidate.py `
  --raw .\tools\promo\runs\<run-id>\raw\capture.mkv `
  --capture-contract .\tools\promo\runs\<run-id>\partial-candidate-contract.json `
  --output-root .\tools\promo\runs\<new-run-id>-candidates
```

若省略 `--capture-contract`，脚本只会在 raw 所属 run 中按固定候选路径推断；
找不到或发现多个 receipt 会直接失败。每个输出仍需独立的 xAR 技术审计、白绮
语义审计和人工 1.0× 审看后，才可进入 signoff/export。

`--output-root` 必须是尚不存在的新 sibling run；脚本会记录实际 xAR source
commit，并在每个 variant 前后复核 raw、contract、旁白和 FFmpeg/ffprobe 字节，
任何输入变化都会保留已生成的 partial、拒绝写入 batch manifest。

### 十分钟 full master

本次完整主片的 run-relative 交付包见
[`docs/2026-09-02-白绮宣传片完整主片渲染回执.md`](../../docs/2026-09-02-白绮宣传片完整主片渲染回执.md)。当前可复核文件为：

- [`run-20260902T-full-master-delivery-a4/renders/full-master.mp4`](runs/run-20260902T-full-master-delivery-a4/renders/full-master.mp4)
- [`run-manifest.json`](runs/run-20260902T-full-master-delivery-a4/run-manifest.json)
- [`full-master-artifact-index.json`](runs/run-20260902T-full-master-delivery-a4/review/full-master-artifact-index.json)
- [`full-master-evidence-coverage.json`](runs/run-20260902T-full-master-delivery-a4/review/full-master-evidence-coverage.json)

该版本是 600 秒、1920×1080/60 的 `master-draft-preserved`：旁白使用
`zh-CN-XiaoxiaoNeural`，不加入外部 BGM，保留游戏声和中英字幕。主片文件为
`209,336,732` bytes，SHA-256 为
`B50D787748D0D58570BC0C70D9C6D871BF92FDAC72D74ABDEDEE5A20C3D057D8`。
当前门禁为 `capture_contract=passed`、`technical_audit=passed`、
`semantic_audit=pending`、`human_review=user-delegated-assumed-pass`
（无独立 1.0× 观察记录）、`signoff=false`、`export=false`；不得把它称为已发布成片。
`a1`、`a2`、`a3` 是保全的历史尝试，`a4` 是修正旁白淡化顺序并重新闭合哈希的 canonical run，
历史目录均未覆盖。

关键 sidecar 的实际字节与 SHA-256：

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `run-manifest.json` | 3,722 | `A838918771ABD6EECFC75B0D3A8589F22A6923BF96B63D304784F01AD06C7469` |
| `review/full-master-artifact-index.json` | 39,684 | `EF08F6271BBC1324B94480460FB5F3400AF3D90845D978FED304D4B5160D8D6F` |
| `review/full-master-evidence-coverage.json` | 5,056 | `49E4EAE2E94F6468CB6350EC144BE91243E3FB8075DEE226A7ABF8F455687BBC` |
| `review/full-master-deliverable-probe.json` | 1,674 | `2204AAD9E15A9F83E426D0CFEC3A65BC34B7C3B6A8AEA4765FFC70CDE5F70318` |
| `review/audio-technical-audit.json` | 3,800 | `2695DD84722292DCE0AB5CDD688E6BE00A95BFA5A4D3199147225A16DC7BE6B6` |

本批固定使用 xAR Promo Toolchain `v0.2.1`（tag commit
`fb160b1eac10cbf1758ccf729f85b14c08e0c6e9`；本机 source worktree
`G:/workspace/xar_promo_toolchain-v0.2.1-tag`）。可从
[GitHub Release v0.2.1](https://github.com/XenoAmess/xar_promo_toolchain/releases/tag/v0.2.1)
复核发布物：wheel（190,405 bytes）SHA-256
`f8de0711415e7fce2bf07a34d3db4edc0593f32ba1cb61034946665e27014621`，
sdist（13,281,238 bytes）SHA-256
`56a712c03078a67a856f861d8c619dcdbd17967a4f26645c9c6e1643d14e4ad5`。

`render_full_master.py` 将同一份已封存的 OBS raw 和长片 EDL 组装为一个
1920×1080/60、H.264/AAC、48 kHz 双声道的 600 秒初稿。它只消费 capture
contract、EDL 和已生成的旁白；不会启动游戏、OBS、OCR、TTS 或发布客户端，且
不会用循环/补帧伪造缺失的镜头。首片不加入 BGM，游戏声和晓晓旁白在同一条
可审计的 FFmpeg filtergraph 中混合，双语字幕写入独立 ASS 文件。

先用最终旁白批次生成新的 EDL（`--source-start` 必须来自 capture receipt，
不可凭空猜测），再把每个 segment 的 source window/span/provenance 与真实
clean span 对齐：

```powershell
py -3 -B .\tools\promo\build_full_master_edl.py `
  --source-start <capture-source-seconds> `
  --narration-root run-20260902T-full-master-tts-a4/narration `
  --output .\tools\promo\runs\<run-id>\notes\full-master-edl.json

$env:PYTHONPATH = 'tools/promo;G:\workspace\xar_promo_toolchain\src'
py -3 -B .\tools\promo\render_full_master.py `
  --raw .\tools\promo\runs\<run-id>\raw\capture.mkv `
  --capture-contract .\tools\promo\runs\<run-id>\capture\contract.json `
  --edl .\tools\promo\runs\<run-id>\notes\full-master-edl.json `
  --narration-root .\tools\promo\runs\run-20260902T-full-master-tts-a4\narration `
  --output-root .\tools\promo\runs\<new-sibling-run-id>-full-master `
  --ffmpeg C:\ffmpeg\bin\ffmpeg.exe `
  --ffprobe C:\ffmpeg\bin\ffprobe.exe
```

输出 run 会保留规范化 EDL、完整 argv/filtergraph、xAR 执行日志、字幕、partial
和 `review/full-master-deliverable-probe.json`。输出目录必须是 raw 所属 run 的
新 sibling；已有目录和已有文件都不会被覆盖。缺少旁白、span 不足、哈希变化或
最终编码不符合 1080p60/H.264/AAC 契约时命令 fail-closed，并保留失败现场。
产物始终标记为 `preliminary`；技术/语义审计、人工审看、signoff 和 export 仍
是后续门禁。

### 60/30/15 秒短版

短版从 a4 的同一份 raw/capture-contract lineage、staged EDL 和 Xiaoxiao
旁白批次派生，未从已签署 MP4 偷转码；每个版本都有独立 EDL、filtergraph、
partial、probe、字幕和 alias。批次清单：
[`batch-manifest.json`](runs/run-20260902T-preview-full-master-a4/batch-manifest.json)。
run manifest 与客观检查见 [`run-manifest.json`](runs/run-20260902T-preview-full-master-a4/run-manifest.json)
和 [`postflight-validation.json`](runs/run-20260902T-preview-full-master-a4/review/postflight-validation.json)。
批次清单 bytes/SHA-256 为 `15,558` /
`D5C13BE2A3BE66961F89620A997370F22B2CE3F6F2D258732E61C8421D4585B7`；
postflight bytes/SHA-256 为 `10,045` /
`05EC8614893F725E7F883EDF5F8B1B6C20B6B1125496CE3CA7A7161595176AB2`。

| 版本 | 成片 | 时长 | SHA-256 |
|---|---|---:|---|
| Hero | [`vivhite-player-hero-60.mp4`](runs/run-20260902T-preview-full-master-a4/hero-60/renders/vivhite-player-hero-60.mp4) | 60.000 s / 20,092,648 bytes | `2AC54EAE8204E1F69F141DA68566136EC388651BB420FF848105B115C3D28EF5` |
| Cut | [`vivhite-player-cut-30.mp4`](runs/run-20260902T-preview-full-master-a4/cut-30/renders/vivhite-player-cut-30.mp4) | 30.000 s / 9,702,759 bytes | `EE2D15DDB0E8F1D0BF77F65E82C589DBAD0ADF3B144380076C71950CBACDF777` |
| Bumper | [`vivhite-player-cut-15.mp4`](runs/run-20260902T-preview-full-master-a4/cut-15/renders/vivhite-player-cut-15.mp4) | 15.000 s / 4,914,451 bytes | `6F14C6C81EF2FAD6953F8CE5495597CABEC752F0A58B06EEB5E2ABE9E5D85FFD` |

三者均为 `preliminary`；客观 technical checks 已通过，但 `semantic_audit=pending`、
`human_review=pending`（未记录独立 1.0× 观察）、`signoff=false`、`export=false`。
当前 canonical batch 是 `a4`，旧批次仅作为历史 attempt 保留。批次状态和每个变体的技术字段以
其 probe、manifest 与 postflight 报告为准。短版脚本为
`render_preview_variants.py`，只做项目侧 EDL 派生和调用通用 renderer，不启动
游戏、OBS、OCR 或发布客户端。

`tools/promo/runs/` 是本机 `.gitignore` 下的内容寻址保全 bundle；上述链接只在此工作区可复核，
原始视频、旁白和运行态文件不随源码提交，也不代表已上传或已发布到平台。

## 故障处理

预检、录制、渲染或审计失败时保留完整原始文件、partial、日志和失败报告，创建
新的 attempt；不要删除、覆盖或手改 contract 来强行变绿。缺少 FFmpeg/ffprobe/OBS、
无法证明清洁画面，或某条主张缺少源码/测试/实录证据时，保持失败关闭，先修复证据
链再继续。
