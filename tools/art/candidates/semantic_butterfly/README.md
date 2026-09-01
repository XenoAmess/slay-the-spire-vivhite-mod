# semantic_butterfly：0030 蓝蝶层序候选

这是蓝蝶 `0030` 的独立、刚性 region 研究。候选同时制作 under-front-hair 与
front-most 两个探针 slot，用于验证不同头发遮挡顺序、最大正负旋转、商店随机相位和
死亡 detach；它不是正式运行时资源。

## 输入与不变量

- `semantic_butterfly.png` 必须逐字节复制自归档 EvoLink 原图；builder 只生成不透明
  SourceOver 诊断条，不修改源 Alpha，也不把邻接层合并进蓝蝶 region。
- Spine 4.2.43、`default` skin、八个消费者动画和固定 pivot/slot order 由 validator
  检查；`relaxed_loop` 两端复位，`die` 只保留预期的显示/分离键。
- `semantic_butterfly_analysis.json` 应声明 `isolated_graybox_not_runtime` 和
  `deployable=false`；任何“通过”都不能绕过完整 head/face 总装。

## 一键预览

```powershell
& .\tools\art\candidates\semantic_butterfly\Invoke-SemanticButterflyPreview.ps1
```

包装器会解析 `Vivhite/local.props`、校验游戏/编辑器 Spine DLL，先使用 art 项目构建
并在 `Vivhite` 项目做静态门禁，再启动屏外 Vulkan exact renderer。可传
`-GodotExe -Sts2Dir -ProjectDir -OutputDir`；输出必须是新的 `.work/` 目录。

分步构建命令：

```powershell
& $godot --headless --path .\tools\art `
  --script res://candidates/semantic_butterfly/build_semantic_butterfly_candidate.gd -- `
  build-semantic-butterfly
& $godot --headless --path .\Vivhite `
  --script (Resolve-Path .\tools\art\candidates\semantic_butterfly\validate_semantic_butterfly_candidate.gd)
```

报告通常包含 `summary.json`、Vulkan 接触表、Alpha triptych 和分析 JSON。接触表只能
用于审美/消费者诊断，不能反向成为 atlas 或生图参考；失败现场应完整保留。

