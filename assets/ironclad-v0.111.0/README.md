# Ironclad v0.111.0 authoring snapshot

这个目录是从 **Slay the Spire 2 v0.111.0** 官方 PCK 提取的原版战士（Ironclad）制作
模板和校验清单。它是版本化、只读性质的研究输入，不是白绮 Mod 的运行时目录，也不是
可以直接复制到 Workshop 的发布包。

> `manifest.json` 的 `notice` 明确要求：Mega Crit 原版美术仅用于本地参考/编辑，未经
> 许可不要重新分发。请同时遵守仓库根 [`AGENTS.md`](../../AGENTS.md) 的素材来源、Alpha
> 和运行时隔离规则。

## 快速事实

| 项目 | manifest 记录 |
| --- | --- |
| 目标游戏 | v0.111.0，PCK 格式 3 |
| 引擎/解码器 | Godot 4.5.1 Mono；`Texture2D.get_image().save_png()` |
| 提取记录 | 34 项 authoring 资源（`manifest.json` 中 `assets` 数组） |
| 领域 | `combat/`、`merchant/`、`rest_site/`、`character_select/`、`ui/` |
| 版本证据 | PCK 大小、目录 SHA-256、每个源/输出文件的 MD5/SHA-256 与尺寸均在 manifest 中 |

PNG 是带 Alpha 的解码结果；Spine `.spskel`/`.spatlas` 已恢复为可读的 `.skel`/`.atlas`。
不要把这些文件当作一张完整插画：atlas 页、region bounds、旋转和 slot 消费契约必须和
相邻 `.atlas`、`.tres`、`.tscn` 及实际运行时代码一起阅读。

## 目录布局和动画契约

```text
assets/ironclad-v0.111.0/
├─ manifest.json
├─ combat/          # 战斗场景、skeleton-data、Spine skeleton/atlas/纹理页
├─ merchant/        # 商店页；骨骼与 combat 共享，atlas 独立
├─ rest_site/       # 休息点 skeleton、atlas、场景
├─ character_select/# 选人 skeleton、atlas、场景
└─ ui/              # icon/outline/select/locked/map_marker 与多人手势
   └─ multiplayer/  # point/rock/paper/scissors（原版参考）
```

`manifest.json.animation_sets` 是不可悄悄变更的原版行为参考：

- combat 必须能解释 `idle_loop`、`low_health_loop`、`relaxed_loop`、`attack`、
  `attack_heavy`、`cast`、`hurt`、`die`，以及 `slash_mesh`、`eye_attach_slot` 和
  `attack_slash_start`、`heavy_slash_start`、`cast_eyes_start`、`clear_vfx`；
- character select 使用 `animation`；
- merchant 复用 combat skeleton 的 `relaxed_loop`；
- rest site 使用 `glory_loop`、`hive_loop`、`overgrowth_loop` 和 light on/off tracks。

这是“消费者契约”参考，不授权把白绮贴图套在原版战士骨骼、网格或持剑姿势上。当前白绮
替换必须使用自己的骨骼/网格/权重和魔法少女姿势，只保留游戏所需的角色 ID、动画/事件名
和场景锚点契约。

## 重新提取

从仓库根目录执行（只在确认安装 PCK 仍是 v0.111.0 时）：

```powershell
py -3 -B .\tools\art\extract_ironclad_assets.py
```

工具按以下顺序解析路径：命令行 `--game-dir`/`--godot`，环境变量 `STS2_DIR`/`GODOT_EXE`，
最后是 `Vivhite/local.props`。需要显式指定时：

```powershell
py -3 -B .\tools\art\extract_ironclad_assets.py `
  --game-dir 'G:\SteamLibrary\steamapps\common\Slay the Spire 2' `
  --godot 'C:\tools\Godot_v4.5.1-stable_mono_win64.exe'
```

可选参数：

| 参数 | 用途与限制 |
| --- | --- |
| `--output <dir>` | 指定输出根；默认是本目录。跨目录输出只适合一次性调查，不应替代版本化快照 |
| `--skip-version-check` | 仅用于研究新版本；会放弃 v0.111.0 指纹闸门，不能作为发布输入 |
| `--clean-output` | 删除并重建精确的 `assets/ironclad-v0.111.0` 根；再次提取前先提交对模板的任何本地修改 |

提取器只读打开 `SlayTheSpire2.pck`，不会写 `Vivhite/` runtime，也不会修改游戏安装目录。
正常重提取会覆盖已知输出文件；`manifest.json` 不记录本机绝对路径和时间戳，以便同版本
复现时稳定比较。若指纹不匹配，应先停止并确认游戏版本，不要用 `--skip-version-check`
掩盖版本漂移。

## 从模板到白绮运行时

推荐的单向流程是：

```text
原版 PCK（只读）
        │ extract_ironclad_assets.py
        ▼
本目录 manifest + authoring 模板
        │ 仅作尺寸/动画/场景契约参考
        ▼
assets/vivhite-ironclad/custom + approved（白绮自有源素材）
        │ tools/art/publish_ironclad_skin.py
        ▼
Vivhite/Vivhite/skins/ironclad（唯一正式 runtime）
        │ dotnet build + PCK gate
        ▼
游戏 mods/Vivhite 三件套
```

发布器会从已验收的白绮私有源生成 runtime，并检查所需的场景/动画契约；不要手工把本目录
中的 `.skel`、`.atlas` 或 `.png` 复制进 `Vivhite/Vivhite/skins/ironclad/`。候选输出应留在
`assets/vivhite-ironclad/candidates/` 或 `.work/`，通过 Source/Godot/PCK 验收后才能镜像。
相关流程见 [`tools/art/README.md`](../../tools/art/README.md) 和
[`docs/2026-08-27-战士白绮视觉替换.md`](../../docs/2026-08-27-战士白绮视觉替换.md)。

## 有意不包含的内容

提取器不会保存通用游戏脚本、shader、共享场景依赖、原始 `.import`/Godot cache UID、卡牌
和遗物插画、timeline portrait、能量球、transition/victory/combat VFX，亦不会生成可直接
发布的 Mod 资源。这些边界与 `manifest.json.not_included` 一致；缺失项不是提取失败。

## 检查清单

修改或升级游戏版本前，至少确认：

1. `manifest.json.game.version_fingerprint.matched` 与目标版本一致；
2. 每个 atlas 都和同目录 skeleton/scene 一起检查，记录 region/slot/事件变化；
3. 白绮源素材没有引用本目录作为 AI 生成参考或运行时 atlas 输入；
4. `publish_ironclad_skin.py`、`tools/test/Verify-VivhitePck.ps1` 和完整 `dotnet build`
   均通过，再进行真机验收。

