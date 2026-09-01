# `character_select_acceptance`：选人界面离线验收

本目录验证白绮私有 character-select Spine 场景和五张独立 UI 纹理在真实消费者尺寸下的行为。脚本只读运行时资源、挂载游戏 PCK 以取得 Spine 4.2.43 扩展，并把报告/渲染证据写到 `.work/`；不会启动游戏、修改正式 skin、调用直播或生成服务。

## 验收对象

- 私有 `character_select.tscn`、`vivhite_character_select.spjson`、`characterselect_ironclad.spatlas` 和两个独立 slot（hero、magic sigil）。正式场景画布是 2560×1200，动画名必须是 `animation`，时长约 5.3333335 秒。
- `render_character_select_hero_only.gd` 隐藏的只是 `vivhite_magic_backdrop`，在 0、25%、50%、75%、100% 五个时间点检查加权 hero 网格确实运动、端点闭合且不触边。
- `render_ui_actual_size.gd` 按消费者尺寸检查 `icon`/`icon_outline`（85×85）、`select`/`select_locked`（132×195）和 `map_marker`（49×64），并分别 SourceOver 到黑、白、游戏蓝灰底色。
- `audit_character_select_sources.gd` 是静态、只读的来源/atlas/slot 审计；它不会把 atlas 页误当成单幅插画，也不会重打包 Alpha。

## 推荐运行顺序

从仓库根目录执行。Godot 默认从 `Vivhite/local.props` 读取；若路径不可用，给每条命令显式替换 `$godot` 和 `$pck`。

```powershell
$propsText = Get-Content .\Vivhite\local.props -Raw
$props = [xml]$propsText
$godot = [string]$props.Project.PropertyGroup.GodotExe
$pck = 'G:\SteamLibrary\steamapps\common\Slay the Spire 2\SlayTheSpire2.pck'

# 1) 静态来源/atlas/动画合同（可 headless）
& $godot --headless --path .\Vivhite `
  --script (Resolve-Path .\tools\art\candidates\character_select_acceptance\audit_character_select_sources.gd) -- `
  --output '.work/character-select-acceptance/sources-current'

# 2) 完整真实场景：写出 frames/ 与 spine-only/，Windows Vulkan 隐藏窗口
& $godot --path .\Vivhite --display-driver windows --rendering-driver vulkan `
  --script (Resolve-Path .\tools\art\render_vivhite_character_select_preview.gd) -- `
  --pck $pck --output '.work/character-select-acceptance/spine-current'

# 3) 同一场景只显示 hero 网格；输出五帧到 hero-only/ 子目录
& $godot --path .\Vivhite --display-driver windows --rendering-driver vulkan `
  --script (Resolve-Path .\tools\art\candidates\character_select_acceptance\render_character_select_hero_only.gd) -- `
  --pck $pck --output '.work/character-select-acceptance/spine-current/hero-only'

# 4) 五张 UI 纹理的实际尺寸/三底色 SourceOver
& $godot --path .\Vivhite --display-driver windows --rendering-driver vulkan `
  --script (Resolve-Path .\tools\art\candidates\character_select_acceptance\render_ui_actual_size.gd) -- `
  --pck $pck --output '.work/character-select-acceptance/ui-current'

# 5) 将步骤 2/3 的五帧合成审阅接触表
& $godot --path .\Vivhite --display-driver windows --rendering-driver vulkan `
  --script (Resolve-Path .\tools\art\candidates\character_select_acceptance\make_spine_contact_sheets.gd) -- `
  --input '.work/character-select-acceptance/spine-current' `
  --output '.work/character-select-acceptance/spine-current/contact-sheets'
```

步骤 2 的根渲染器会生成 `frames/` 和 `spine-only/`；接触表脚本还需要步骤 3 生成的 `hero-only/`，所以不要把步骤 3 的输出直接放在 `spine-current/` 根目录。所有脚本的 `--output`/`--input` 都必须保持在仓库 `.work/` 下；输入 PNG 不得被缩放回 `assets/` 或正式 atlas。

## 结果与判读

各脚本在自己的输出目录写 `report.json`；接触表脚本额外写三张 PNG：

```text
.work/character-select-acceptance/
  sources-current/report.json
  spine-current/
    report.json
    frames/frame-*.png
    spine-only/frame-*.png
    hero-only/report.json + frame-*.png
    contact-sheets/
      animation-full-scene.png
      animation-spine-sourceover.png
      animation-hero-only-sourceover.png
  ui-current/report.json + ui-actual-size-sourceover.png
```

验收必须同时看到 `display_server=Windows`、`rendering_driver=vulkan`、`success=true`，并人工复核黑/白/游戏蓝灰三种 SourceOver：四角 Alpha 应为 0，主体内部接近不透明，发丝/眼镜/白服/蓝蝶没有矩形光晕或触边。hero-only 的“有运动”不等于完整场景或 UI 发布通过；仍需运行正式 PCK/场景门禁和发布器。

## 安全边界

这是离线证据链，不是运行时入口。缺少真实 PCK、窗口驱动不是 Vulkan、输入目录含旧报告、或任何帧为空时应保持 fail-closed，保留完整 stdout/stderr/JSON/PNG 供复盘；不要手改报告或复制诊断灰盒进入 `Vivhite/Vivhite/skins/ironclad/`。新透明素材仍必须遵守仓库 `AGENTS.md` 的源码消费审计、EvoLink 原生透明和原图/Prompt/请求归档规则。
