# 多人手势 UI 离线验收

本目录验收 `point`、`rock`、`paper`、`scissors` 四张多人手势 PNG 的真实消费者布局。四张图属于 `AGENTS.md` 明确授权的封闭历史例外：允许从 `assets/vivhite-ironclad/legacy-contaminated/2026-08-27/custom/ui/multiplayer/` 逐字节恢复并进入运行时，但不得把它们作为 AI 参考、重新处理 Alpha，或把该例外扩展到其他素材。

## 消费者合同

- 四张资源是四个独立的完整手臂 `Texture2D`，不是一张四格 sprite sheet、atlas 或 UV 裁剪图。原始尺寸必须是 422×1200 RGBA；`hand_image.tscn` 的 TextureRect 是 383×1072，`keep-aspect-centered`，显示比例为 1072/1200。
- 固定消费者锚点（TextureRect 坐标）是指向 `(163,10)`、猜拳战斗 `(197,600)`、抓取标记 `(175,222)`；四个资源按 `CharacterModel` 到 `NHandImage`/`RelicPickingFightMove` 的映射加载。
- System.Drawing 阶段统计四角 Alpha、A≥1/8/128 bbox、边缘非零像素、连通域和上下带质心；渲染阶段再以黑、白和真实游戏截图做 SourceOver，并绘制 pivot 标记。缩略图棋盘格、黑底或 bbox 单独都不能证明无光晕。
- 这是资源/单客户端离线证据，不是两客户端多人端到端证明；真正的宝物争抢流程仍需另行安排第二客户端验收。

## 两阶段命令

从仓库根目录执行。第一阶段不启动 Godot/游戏，只读取 PNG 和消费者契约；`-GameplayBackground` 必须是真实游戏场景截图，不能用纯色伪造：

```powershell
& .\tools\art\evaluations\multiplayer_gestures\Invoke-MultiplayerGestureAcceptance.ps1 `
  -RepositoryRoot (Get-Location).Path `
  -OutputDirectory '.work/multiplayer-ui-acceptance' `
  -GameplayBackground '.work/ironclad-game-acceptance/gameplay-background.png'
```

第一阶段写出 `report.json` 和 `summary.txt`。报告的 `status` 必须为 `offline-resource-pass`，且每个 gesture 同时满足：approved 与授权例外源、runtime 逐字节哈希一致；尺寸与 vanilla 一致；四角 Alpha 为 0；分类为 `single-full-arm-texture`。报告中的 pointing fingertip 可能带有“比 vanilla 向右”的警告，这不应被静默改图。

第二阶段用真实 Godot Spine/Windows Vulkan 在同一消费者尺寸渲染四张图。输出目录必须是新建或空目录：

```powershell
& .\tools\art\evaluations\multiplayer_gestures\Invoke-MultiplayerGestureVulkanPreview.ps1 `
  -GameplayBackground '.work/ironclad-game-acceptance/gameplay-background.png' `
  -OutputDirectory '.work/multiplayer-ui-acceptance/vulkan-current'
```

包装器会从 `Vivhite/local.props` 解析 Godot，也可显式传 `-GodotExe`、`-ProjectDirectory`。它使用屏幕外、隐藏的 Windows/Vulkan 窗口和项目级 mutex，不触碰正在运行的游戏；缺少 PCK/Spine 扩展、底图或输出目录不为空时应失败关闭。

## 输出

```text
.work/multiplayer-ui-acceptance/
  report.json                 # 第一阶段资源、哈希和 Alpha 统计
  summary.txt
  sourceover-black-actual-383x1072.png
  sourceover-white-actual-383x1072.png
  sourceover-gameplay-actual-383x1072.png
  consumer-pivots-gameplay-actual-383x1072.png
  vulkan-current/
    report.json               # display_server=Windows, rendering_driver=vulkan
    render.stdout.log / render.stderr.log
```

先以程序化报告筛掉尺寸/哈希/Alpha 错误，再在四张接触表的实际显示尺寸复核袖口、指尖、抓取点和边缘渐变。通过只表示离线资源合同成立；不得把接触表反向写回 `assets/`、atlas 或正式 runtime，也不得将“未测试两客户端”写成多人流程已通过。

失败时保留完整输出、底图哈希、日志和 JSON，交复盘失败包流程；不要删除旧帧、手改 `status` 或以程序抠图修 Alpha。除上述四张封闭例外外，所有新增透明素材继续遵守 `AGENTS.md` 的 EvoLink 原生透明规则。
