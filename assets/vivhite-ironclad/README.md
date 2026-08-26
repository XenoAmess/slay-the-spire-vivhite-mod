# 白绮战士换皮美术源

本目录保存原版战士 → 白绮视觉替换的全部可复现美术源与最终成品，受 Git
跟踪，不是临时缓存。

## 目录

- `references/`：用户提供的人物设定图与头像参考；
- `generated/anchor/`：白绮全身身份锚点及透明化中间件；
- `generated/gameplay/`：战斗、死亡、篝火和选人 atlas 的 AI 迁移源；
- `generated/ui_raw/`：七张 UI/多人手势的独立 ImageGen 原图；
- `generated/ui_alpha/`：技术绿底转 straight-alpha 后的中间件；
- `generated/*-generation-prompts.md`：实际生成约束、输入映射和提示词；
- `custom/`：可发布成品，包括 190 个 Spine region 母片、10 张 atlas 页、
  9 张 UI/多人手势及静态审计报告。

`assets/ironclad-v0.111.0/` 是另一个受跟踪目录，只保存与游戏 v0.111.0
匹配的原版制作模板和 manifest。发布器从模板目录读取场景/资源包装器，从本
目录的 `custom/` 读取白绮成品；两者不会互相覆盖。

## 角色硬约束

白绮是银白短发、紫色瞳孔、金色圆框眼镜的华丽、可爱而冷淡的魔法少女。
她是空手施法者：没有剑、法杖、魔杖、法书、盾、手持法球或任何其他武器，
也不使用白绫。战斗特效是紫蓝水晶光、魔法弧和蓝蝶。

## 离线重建

以下命令都只操作仓库文件：

```powershell
$godot = 'C:\path\to\Godot_v4.5.1-stable_mono_win64_console.exe'

& $godot --headless --path .\tools\art `
  --script res://atlas_region_tool.gd -- init-all `
  --source-root assets/ironclad-v0.111.0 `
  --custom-root assets/vivhite-ironclad/custom

& $godot --headless --path .\tools\art `
  --script res://build_vivhite_gameplay_regions.gd -- build

foreach ($domain in 'combat','merchant','rest_site','character_select') {
  & $godot --headless --path .\tools\art `
    --script res://atlas_region_tool.gd -- pack `
    --workspace "assets/vivhite-ironclad/custom/$domain" `
    --weapon-policy clear
}

& $godot --headless --path .\tools\art `
  --script res://build_vivhite_gameplay_regions.gd -- audit

py -3 -B .\tools\art\publish_ironclad_skin.py
```

`build` 会从已跟踪的 AI 生成源确定性重建四域 region；随后必须逐域以
`weapon-policy clear` 回包。`audit` 必须确认 190/190 region 与模板不同、
10/10 atlas 页与模板不同，并逐 region 校对“当前母片 = packed rect = build report
像素哈希”；因此改完母片却忘记重新 pack 会直接失败。combat/merchant 的
`sword blade` 与 `sword_handle` alpha 必须全为零。选人页的复合 `top arm`
使用专门的空手护臂切图并单独记录、验证审计来源。

四张多人手势、头像、选人图和地图标记由
`tools/art/process_vivhite_ui.gd` 做确定性裁切、锚点和 Alpha 后处理；完整输入
映射与执行命令见 `generated/ui-generation-prompts.md`。九张输出先全部写入同级
staging 目录，成功后才整体切换；缺源图或保存失败不会留下半套 UI。

## 发布边界

仓库会保留制作模板、AI 原图、中间件、region 母片和最终 PNG。Mod PCK 只包含
`Vivhite/Vivhite/skins/ironclad/` 下的 30 个逻辑运行时资源及 Godot 导入产物；
不会包含 `assets/`、`tools/`、`.work/` 或任何复制的 `.skel/.spskel`。
发布器会按这 30 项精确镜像运行时目录，并拒绝尺寸变化、仅重编码但像素仍等于
原版的 PNG、被改动的 atlas 布局以及目录内任何陈旧调试文件。
