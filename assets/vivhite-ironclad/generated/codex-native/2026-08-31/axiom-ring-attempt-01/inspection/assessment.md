# 公理护环生成证据独立审计

审计日期：2026-08-31  
审计范围：仅 `axiom-ring-attempt-01` 证据包及其只读哈希锚点  
结论：现有 `inspection` 补充文件真实、可复现、无秘密，可随本证据包提交。

## 原记录完整性

- `prompt.txt`、`generation.json`、`original.png` 均已由提交
  `bac933ee09cefa60f7b485c9db49c4b18492bbc8` 跟踪。
- 三个工作树文件的 Git blob 均与索引一致；审计时没有已跟踪文件修改。
- `prompt.txt` 的 SHA-256 为
  `128cb15550deb2456a0ceb551eb4a3e4399e22316d0a1274c06e36f521c22c6a`，
  与 `generation.json.prompt_sha256` 一致。
- `original.png` 的 SHA-256 为
  `3966bb466d6eed83a49da1c2deaead9067fc6a69c0088e790db9b90aa9e23411`，
  与 `generation.json.original_sha256` 一致。
- `generation.json` 中四张参考图均存在，现场重算 SHA-256 后全部与记录一致。

## 原图与确定性派生链

- 原图为 `1536x1024`、8-bit RGB、完全不透明 PNG。
- `inspect_candidate.gd` 按整数安全区计算得到居中裁切
  `x=105, y=8, width=1325, height=1007`，再以 Godot Lanczos 缩放到
  `1000x760 RGB8`。
- 审计在仓库外的独立临时 Godot 4.5.1 Mono 工程中复制检查脚本，重新从
  `original.png` 生成六张派生图；六张重放结果与本目录现有文件逐字节同哈希。
- `centered-25x19-1000x760-rgb8.png` 的 SHA-256 为
  `636f9fc9a7863594120ff43f3bd344525858c5836379b1acfa3bd1225d4ab764`，
  与 `generation.json.runtime_sha256` 及运行时
  `Vivhite/Vivhite/images/cards/AxiomRing.png` 完全一致。
- 彩色、灰度、`250x190` 与 `100x76` 检查图均由上述同一 RGB8 派生图生成；
  没有使用重绘、抠图、蒙版或 Alpha 后处理。

## 内容与秘密检查

- 逐字检查 Prompt、JSON、GDScript、Godot 项目和两份日志；未发现 API Key、
  Authorization、Bearer、密码、Cookie、会话 ID 或常见凭据格式。
- 唯一 URL 是两份 Godot 引擎日志中的公开官网 `https://godotengine.org`。
- 所有 PNG 均无 `tEXt`、`zTXt`、`iTXt` 或 `eXIf` 块。
- 原图带有一个 `caBX` C2PA/JUMBF 来源声明块，记录 `gpt-image 2.0`、
  `trainedAlgorithmicMedia` 与 `OpenAI Media Service API`；未发现凭据或临时下载地址。
- 视觉复核确认原图、运行时裁切及 100x76 灰度缩略图内容一致，闭合向内的技能构图仍可辨；
  未发现武器、敌人、文字、水印、口部红色长条、丝线或液体。

## 证明边界

静态证据包能够证明 Prompt、参考图、原图、派生图和运行时文件之间的记录与哈希链一致，
且 C2PA 声明能够证明原图的生成式来源。它不能仅凭静态文件对“该 Prompt 和四张参考图确实作为
原生工具请求载荷发出”作密码学证明，因为包内没有原生工具的签名请求回执或工具调用 ID。
本审计没有为此伪造字段；当前记录未发现矛盾，该边界不影响现有确定性派生证据提交。

## 可提交清单

- `inspect_candidate.gd`
- `project.godot`
- `prepare-godot.log`
- `inspect-godot.log`
- `centered-25x19-1000x760-rgb8.png`
- `centered-25x19-1000x760-gray.png`
- `thumbnail-250x190-color.png`
- `thumbnail-250x190-gray.png`
- `thumbnail-100x76-color.png`
- `thumbnail-100x76-gray.png`
- `sha256-manifest.txt`
- `assessment.md`

