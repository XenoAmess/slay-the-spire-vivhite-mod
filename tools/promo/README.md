# 白绮宣传片生产工具

这里是白绮宣传视频的**项目侧**适配层。它把 STS2 的录制产物转换为
`xar_promo_toolchain` 能够审计的媒体、时间线和证据；它不把游戏逻辑、录屏器
或 Brain 运行时塞进 xAR 通用核心。

## 目录和责任边界

```text
tools/promo/
├─ vivhite_promo/                         # 白绮 adapter/preset/composer
│  └─ semantic_audit.py                    # 项目侧 claims/证据语义门禁
├─ schemas/vivhite-promo-capture-v1.schema.json
├─ fixtures/minimal_capture/              # 离线、极小的契约 fixture
├─ claims/claims.json                     # 白绮语义主张及证据角色
├─ project.json                            # 项目配置
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
- 1920×1080/60 FPS/Vulkan 以及 `overlays_absent`、`loading_absent`、
  `console_absent` 是否明确为 `true`；
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
- 游戏内 STS2AIAgent CanvasLayer、AI edge tab、调试面板和第三方 overlay 均不可见；
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
Game Capture、1920×1080、60 FPS、隐藏鼠标和 overlay。它不会启动 OBS、游戏、直播、
WebSocket 或 Brain，也不会修改音频端点。

```powershell
# 只读预演
.\tools\promo\configure_obs.ps1 -Json

# 关闭 OBS 后，明确应用并保留备份
.\tools\promo\configure_obs.ps1 -Apply -Json
```

当前 OBS 32.2.2 不包含 Game Capture 的进程音频源，因此配置将
`capture_audio` 明确保持为 `false`，只启用一个全局 WASAPI 输出源（麦克风关闭，避免重复和漂移）。
正式取景前必须做一段短录并用 `ffprobe`/试听确认游戏声；不能把 OBS 的“正在录制”状态当作音频已录入的证明。

游戏内的 `STS2AIAgent` 会始终留下右侧 `AI` 边签，OBS 的
`capture_overlays=false` 无法移除它；Workshop `LieRenTVmod` 也会改动选人/背景资源。
正式录制前先停止游戏并运行可逆隔离脚本：

```powershell
.\tools\promo\isolate_capture_mods.ps1 -Apply -Json
# 启动 Vulkan 游戏；如出现原生模组同意框，由操作者在游戏内确认
# 所有取景完成、游戏退出后：
.\tools\promo\isolate_capture_mods.ps1 -Restore -Json
```

脚本只移动这四个已知污染目标（STS2AIAgent 三件套及 LieRenTVmod Workshop 目录），逐文件保存 SHA-256 到
`.work/promo-capture-isolation/`，绝不删除、覆盖或触碰存档及其他 Mod。

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

首片目标为 1920×1080 横屏约 10 分钟；60/30/15 秒版本必须从新的配置快照和
run 生成。技术审计通过不等于白绮语义审计或人工发布批准。

## 故障处理

预检、录制、渲染或审计失败时保留完整原始文件、partial、日志和失败报告，创建
新的 attempt；不要删除、覆盖或手改 contract 来强行变绿。缺少 FFmpeg/ffprobe/OBS、
无法证明清洁画面，或某条主张缺少源码/测试/实录证据时，保持失败关闭，先修复证据
链再继续。
