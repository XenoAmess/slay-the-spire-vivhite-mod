# 白绮宣传片生产工具

这里是白绮宣传视频的**项目侧**适配层。它把 STS2 的录制产物转换为
`xar_promo_toolchain` 能够审计的媒体、时间线和证据；它不把游戏逻辑、录屏器
或 Brain 运行时塞进 xAR 通用核心。

## 目录和责任边界

```text
tools/promo/
├─ vivhite_promo/                         # 白绮 adapter/preset/composer
├─ schemas/vivhite-promo-capture-v1.schema.json
├─ fixtures/minimal_capture/              # 离线、极小的契约 fixture
├─ claims/claims.json                     # 白绮语义主张及证据角色
├─ project.json                            # 项目配置
├─ storyboard.json                         # 镜头与时长
├─ pyproject.toml                          # xAR entry points
├─ preflight.ps1                           # 只读预检
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

`schemas/vivhite-promo-capture-v1.schema.json` 描述项目侧契约。典型根对象包括：

- `kind: "vivhite_promo_capture"`、`contract_version: 1`、`mode: "vivhite-promo"`；
- `producer_id`、`run_id`；
- `media.raw`（相对 `artifact_root` 的路径、字节数、SHA-256、媒体类型）和时长/时间基；
- 单调递增的 `marks`；
- `clean_spans`，每个 span 有 begin/end mark、`natural` 或 `staged` provenance，
  以及 evidence artifact 引用；
- 顶层 `evidence`；
- `project_context`，包含游戏/Mod 版本、Vulkan、分辨率、帧率和清洁画面断言。

`load_capture_contract(path, *, artifact_root=..., verify_files=True)` 会读取并
绑定文件；`validate_capture_contract(payload, artifact_root, *, verify_files=True)`
执行同一契约校验。有效对象的 `verify_unchanged()` 可在 preserve、build 或审计前
再次确认原始文件没有被替换。任何录制重试都使用新的 `run_id`/attempt；不得覆盖
已有 raw、partial、日志或证据。

通用 xAR 不解释 `natural`、`staged`、卡牌名称或 HP 数值。白绮 adapter 只把
经过语义检查的 span 投影为 xAR 的 `CaptureReceipt`/`VisualSource`；“画面里的
机制为什么是真的”由 `claims/claims.json` 和白绮 validator 证明。

## 清洁画面门禁

正式录制必须使用精确游戏 HWND/Game Capture，并确认：

- 外置 ASCEND-VISION viewer 已在该 capture session 禁用；
- 游戏内 STS2AIAgent CanvasLayer、AI edge tab、调试面板和第三方 overlay 均不可见；
- 没有 loading、主菜单等待画面、控制台、鼠标/任务栏/Steam 提示；
- 游戏、旁白、BGM、SFX 分轨保存，后续由 xAR 多轨计划混合；
- 录制前后用 `ffprobe` 复核分辨率、帧率、时长、编码、采样率和声道。

截图/OCR 工具只能产生辅助证据，不能代替连续视频录制。不要调用
`Start-Agent.ps1`、Bilibili 入口或自动 Brain 来“生成”确定性宣传镜头；宣传录制
与训练/直播是独立生命周期。

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
