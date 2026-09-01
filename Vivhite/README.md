# Vivhite

语言 / Languages：中文 | [English](README.en.md)

`Vivhite` 是《杀戮尖塔 2》的白绮角色 Mod。白绮是一位精通数学、计算机与艺术的魔法少女、魔法大师；她以生命作为魔法演算材料，通过“支付謦欬施法 → 击杀或汲取回血 → 继续施法”建立战斗循环。

本文描述当前 `0.2.0` 角色实现。完整 61 张卡牌目录与逐牌数值见[《白绮角色与轮换大脑实现》](../docs/2026-08-30-白绮角色与轮换大脑实现.md)。当前运行时位图门禁为 `92/92`：它在既有 `89/89` 内容位图基线上纳入了 3 张独立 VFX，并已完成同批三件套原子部署与 Vulkan 实机验证。

**角色概要：**

- 初始属性：`78` 最大生命、`99` 金币、每回合 `3` 能量、抽 `5` 张牌。
- 初始牌组：4 × 弦光投影、4 × 闭域映射、1 × 白绮的变身式。
- 初始遗物：孤高冠冕——每当任意敌人死亡，立即回复最大生命的 `20%`，向上取整；同一实体的同一次死亡只结算一次。
- 专属卡池共 `61` 张：3 基础、18 普通、24 罕见、16 稀有。
- 三套主要构筑：守恒几何、递归星算、绯彩积分，并有跨体系组合牌。
- 运行时位图门禁已达到 `92/92`：61 张卡图、19 个 Power 图标、2 张孤高冠冕资源、7 张能量 UI 资源和 3 张独立 VFX。

## 学习资源

- [STS2-RitsuLib](https://github.com/BAKAOLC/STS2-RitsuLib)：本项目用于内容注册、角色接入与 Godot 资源集成的基础库。
- [RitsuLib 文档](https://github.com/GlitchedReme/SlayTheSpire2ModdingTutorials/tree/master/RitsuLib)：按文件组织的教程和示例。
- [Slay the Spire 2 Modding Tutorials](https://glitchedreme.github.io/SlayTheSpire2ModdingTutorials/index.html)：完整教程站点。

## 安装与使用

### 方式 A：从源码构建（推荐）

1. 安装《杀戮尖塔 2》并准备 Godot 4.5.1 Mono、.NET 9 和 RitsuLib。
2. 按下文创建 `local.props` 并填写本机路径。
3. 在本目录运行 `dotnet build .\Vivhite.csproj`。完整构建会生成、验证并原子部署 dll、manifest 和 pck 三件套。
4. 确认游戏的 `mods` 目录同时包含 `Vivhite` 与依赖 `STS2-RitsuLib`。

可部署构建必须让 `Vivhite.dll`、`Vivhite.json` 与 `Vivhite.pck` 来自同一批候选。项目会先在实时 Mod 目录之外准备并验证三件套，再以整目录事务发布；显式要求 `/p:RunPckExport=false /p:CopyModOnBuild=true` 会被 `VIVH001` 拒绝，不会形成拆分部署。

### 方式 B：安装构建产物

将以下三件套放入 `<游戏目录>\mods\Vivhite\`：

- `Vivhite.dll`
- `Vivhite.json`
- `Vivhite.pck`

同时安装 manifest 指定版本的 `STS2-RitsuLib`。启动游戏必须使用 Vulkan；Steam 启动项为：

```text
%command% --rendering-driver vulkan
```

本机若已提供游戏根目录下的 `launch_vulkan.bat`，也可以通过该脚本启动。

## 配置本机路径

```powershell
Copy-Item .\local.props.template .\local.props
```

在 `local.props` 中设置以下值（文件已在 `.gitignore`，不要提交）：

| 字段 | 说明 |
|---|---|
| `Sts2Dir` | 《杀戮尖塔 2》安装目录 |
| `Sts2DataDir` | 游戏 dll 目录，通常为 `$(Sts2Dir)/data_sts2_windows_x86_64` |
| `GodotExe` | 用于导出 pck 的 Godot 4.5.1 Mono 可执行文件 |
| `RitsuLibDeployDir` | RitsuLib 的本机部署目录，默认 `$(Sts2Dir)/mods/STS2-RitsuLib`；它不是当前 Mod 的输出目录 |

## RitsuLib 版本兼容性

> **发布前必须校对 manifest 与 csproj 的版本。**
>
> `Vivhite.json` 中 `dependencies[STS2-RitsuLib].version` 必须与 `.csproj` 实际编译使用的 `STS2.RitsuLib` 版本一致。构建会同步该依赖版本；`min_game_version` 仍需人工确认。

### 当前版本快照（2026-08-30）

| 项 | 值 |
|---|---|
| 目标游戏版本 | Slay the Spire 2 `0.111.0` |
| 引擎 / SDK | Godot 4.5.1 Mono / `Godot.NET.Sdk` 4.5.1 |
| 目标框架 | `.NET 9` / `net9.0` |
| RitsuLib | `0.5.14` |
| 白绮实现版本 | `0.2.0` |

### 版本对应表

| RitsuLib 版本 | 目标 STS2 版本 | 本项目状态 |
|---|---|---|
| `0.5.14` | `0.111.0` | 当前编译基线 |

切换其他版本前请先核对 [STS2-RitsuLib Releases](https://github.com/BAKAOLC/STS2-RitsuLib/releases) 与对应游戏分支；不要假设旧 API 或旧兼容包仍可直接使用。

### 包选择

项目固定引用当前主线包：

```xml
<PackageReference Include="STS2.RitsuLib" Version="0.5.14" GeneratePathProperty="true" />
```

一次只能启用一个 RitsuLib 主线或兼容包。切换包时必须同时复核游戏版本、公开 API、manifest 依赖版本和真机加载结果。

### 发布前 checklist：版本对齐

1. 构建后确认 `Vivhite.json` 的 `dependencies[STS2-RitsuLib].version` 与实际解析的 NuGet 版本一致。
2. 确认 `min_game_version` 与目标游戏分支一致。
3. 确认 dll、json、pck 三件套被部署到同一 `mods/Vivhite` 目录。
4. 使用 Vulkan 启动，并以实际加载日志确认依赖和 Mod 均被识别。

### 升级注意事项

- 本项目当前面向 STS2 `0.111.0`、RitsuLib `0.5.14` 与 Godot 4.5.1 Mono。
- 升级 RitsuLib 或游戏版本时，应重新编译并检查卡牌命令、Hook、角色资源配置与 PCK 导出。
- `Vivhite.json` 的运行时依赖校验和 `.csproj` 的编译时依赖是两条不同链路，二者都必须更新。

## 构建

| 命令 | 行为 |
|---|---|
| `dotnet build .\Vivhite.csproj` | 完整构建：编译 → `ExportPCK` 候选 → `CopyMod` 事务提交 |
| `... /p:RunPckExport=false` | 跳过 PCK 导出；`CopyModOnBuild` 默认随之变为 `false`，不触碰实时 Mod 目录 |
| `... /p:CopyModOnBuild=false` | 禁用 PCK 导出与实时发布，编译产物只留在 `bin/` |
| `... /p:RunPckExport=false /p:CopyModOnBuild=false` | 仅进行 C# 编译检查 |

完整构建先编译，再由 Build 后的 `CopyMod` 目标触发并依赖 `ExportPCK`：

- **`ExportPCK`**：调用发布脚本，在实时 Mod 目录之外导出 PCK、收集当前 DLL 与同步依赖版本后的 manifest，并验证完整候选三件套。
- **`CopyMod`**：只在 `ExportPCK` 的整目录事务成功后报告提交完成；该目标没有逐文件复制，不会单独覆盖实时 DLL、PCK 或 manifest。

> `/p:RunPckExport=false` 单独使用时已安全地默认关闭复制；若显式重新打开 `CopyModOnBuild`，构建会在美术校验和编译前以 `VIVH001` 失败。`STS2_SKIP_PCK_EXPORT=1` 遵循同一 fail-closed 规则。

> `RitsuLibDeployDir` 只控制 RitsuLib 框架自身的部署位置；当前 Mod 的 dll、manifest 和 pck 由 `ModOutputDir` 控制，默认是 `$(Sts2Dir)/mods/$(MSBuildProjectName)`。

## 目录结构

```text
Vivhite/
├── VivhiteCode/   # C# 角色、卡牌、遗物与战斗规则
├── Vivhite/       # Godot 资源与中英文本地化
├── Vivhite.csproj
├── Vivhite.json   # Mod manifest
├── project.godot
└── local.props.template
```

`res://Vivhite/...` 是 Godot/PCK 内的资源路径，对应仓库中的 `Vivhite/` 资源目录，并非 C# namespace。

## 白绮内容

### 角色配置

| 项 | 值 |
|---|---|
| 类型 | `VivhiteCharacter` |
| 角色 ID | `VIVHITE_CHARACTER_VIVHITE_CHARACTER` |
| 初始属性 | 78 最大生命、99 金币、3 能量、每回合抽 5 张牌 |
| 初始牌组 | 4 × 弦光投影、4 × 闭域映射、1 × 白绮的变身式 |
| 初始遗物 | 孤高冠冕：每个敌人死亡时回复最大生命的 20%，向上取整 |
| 卡池 | 61 张：3 基础、18 普通、24 罕见、16 稀有 |

### 卡池与三套构筑

| 构筑 | 主要方向 |
|---|---|
| 守恒几何 | 用余裕减免謦欬，永久增加最大生命，并把超量治疗转为资源 |
| 递归星算 | 强化伤害、击杀回复、抽牌与能量连锁 |
| 绯彩积分 | 通过多段伤害与可超过 100% 的汲取形成伤害、回复、格挡和力量循环 |

另有跨体系牌连接余裕、抽牌、击杀和汲取，包括按回合无限提高攻击謦欬与伤害的稀有能力牌“白绮的猩红转化仪式”。完整 61 张牌的 ID、费用、效果和升级数值见[完整实现文档](../docs/2026-08-30-白绮角色与轮换大脑实现.md)。早期 Demo 内容已从当前注册、初始牌组与内容池移除；具体历史保留在[早期 Demo 记录](../docs/2026-08-22-白绮角色mod-demo搭建与真机测试.md)中。

### 核心关键词

| 关键词 | 语义 |
|---|---|
| `謦欬 N` | 在牌面效果及该牌引发的任何回血前损失 N 点不可格挡、不会被力量修改的生命；支付后会低于 1 生命时不可打出 |
| `余裕 N` | 自动按 1:1 抵消謦欬并被消耗 |
| `增维 N` | 永久增加 N 点最大生命，并同时增加 N 点当前生命 |
| `汲取 N%` | 整张攻击牌结算后，将多段与群体实际造成的敌方生命损失汇总，乘以牌面、本场全局与本回合临时汲取率之和，形成一次回复请求并只向上取整一次 |
| `致命` | 该牌的伤害直接令目标死亡时触发对应效果 |

牌面汲取率、本场全局汲取率与本回合临时汲取率按百分点相加。运行时不会分项重复结算，而是只用完整攻击的实际敌方生命损失与最终总率计算一次回复请求并向上取整。汲取不计算格挡、过量伤害、自伤、荆棘或非攻击牌伤害。

### 无人为上限

白绮机制不设置最大生命成长、余裕、击杀回复、汲取百分点、汲取回复量、力量、抽牌成长或其他自定义硬上限。临时生成、复制、重复结算和从弃牌堆或消耗堆回收的牌与原牌同权，能够触发永久增维；汲取率可以超过 `100%`。

保留的只有游戏自然不变量：

- 当前生命不能超过最大生命。
- 謦欬的实际费用最低为 0。
- 支付后会低于 1 点生命的牌不可打出。
- 手牌数量等继续遵循游戏原生规则。
- 同一敌人的同一次死亡事件只结算一次；这是事件去重，不是回复上限。

### 独立白绮 V3 皮肤与美术门禁

原版 `IRONCLAD` 不再注册任何 Vivhite 资源替换，因此继续使用游戏原生的战斗、商店、休息、选人、UI、Spine、音频和多人资源。只有独立白绮角色从 `VivhiteCharacterAssets` 获取当前白绮 V3 五页资源 profile，并在其上局部覆盖白绮自己的能量计数器和卡牌轨迹。该 profile 沿用历史物理目录 `res://Vivhite/skins/ironclad/`，但目录名不表示资源所有权，也不会触发战士替换。

`tools/art/audit_vivhite_runtime_art.gd` 与 PCK 四层只读门禁检查当前 `92/92` 位图：61 张独立不透明卡图、19 个 Power 语义图标、2 张孤高冠冕资源、7 张能量 UI，以及眼镜星光、白绮专属卡牌轨迹和角色选择转场 3 张 VFX。早期 `89/89` 只是加入这 3 张 VFX 前的内容位图基线，不能再代表当前发布清单。皮肤源码/发布清单也已达到精确 `30/34` 文件契约，全卡静态视觉 QA 为 `61/61`。

同批 DLL、manifest 与 PCK 已完成原子部署；Vulkan 实机确认白绮战斗皮肤、头像、孤高冠冕、余裕 UI、中文卡名和卡图正常，未见红色 `NOPE` 或裸本地化 key。该次证据不应被扩大成未来每次构建都自动通过；后续资源变更仍须重跑静态、PCK 与真机门禁。生成原图、逐字 Prompt、生成事实和检查图均追加式保存在 `assets/vivhite-ironclad/generated/`，不会覆盖既有创意素材。

## Brain 角色隔离、追及轮换与原生结算

Brain 共用同一套决策算法，但战士与白绮使用独立的 `CharacterProfile`。战士继续使用历史 `knowledge/` 根目录；白绮的统计、策略、进度、课程、运行日志和 LLM 复盘队列/报告写入 `knowledge/profiles/vivhite/`。只有位于历史 `knowledge/` 根目录且没有角色字段的旧日志才按战士处理；位于 `knowledge/profiles/vivhite/` 的无字段日志仍归属白绮。分角色卡牌统计、最高楼层、平均楼层、胜率和近 20 局数据彼此隔离。

仅在首次追平前且白绮已成功落盘的总局数少于战士时，轮换按 `VVVVI`（白绮四局、战士一局）的追赶序列推进；如果白绮在一个五局周期中途追平，下一局明确选择战士，并永久切换为严格 `1:1` 交替，不承诺跑完该周期，也不会因战士局后暂时再次少一局而重返追赶。只有唯一终局日志与对应角色统计均成功持久化后才消费轮换配额，重复终局通知不会重复推进。

GAME OVER 阶段由 MCP 暴露真实的 `continue_game_over` 动作。Brain 先点击游戏原生 Continue；`summary_animating` 期间只等待，进入 `summary_ready` 只表示真实返回主菜单按钮已经可用，并不证明存档成功。此时 Agent 通过当前 Profile 的 Godot `user://` 路径只读打开真实 `progress.save`，把磁盘 JSON 与当前 `saveManager.Progress.ToSerializable()`（补齐最新 schema version）序列化出的完整 `SerializableProgress` JSON 做递归等价比较，并暴露 `save_status`、`save_verified` 与 `save_error`。只有精确满足 `save_status=verified`、`save_verified=true` 且 `save_error` 为空，Brain 才幂等落盘本局日志与角色统计、提交轮换终局账本，并在下一次轮询点击真实返回按钮；`pending` 继续等待，错误、缺字段、错误类型或矛盾组合均 fail closed，不结算、不轮换、不离场。随后出现的每个原生 `UNLOCK` 界面再逐项通过 `confirm_unlock` 确认。

`Ctrl+Alt+F9` 只暂停 Brain 发送动作并保留游戏与 runner，`Ctrl+Alt+F10` 恢复自动控制；它们是 `sts2-ascend` 的外部控制，不是 Vivhite Mod 游戏热键。被人工接管触及的局会标记为 human-assisted，并从自动角色统计、学习、LLM 复盘和轮换配额中排除，但仍不能绕过上述原生存档屏障。

## Manifest 格式

`Vivhite.json` 是 Mod 清单。`0.2.0` 实现对应的关键字段为：

```json
{
  "id": "Vivhite",
  "name": "白绮 Vivhite",
  "pck_name": "Vivhite",
  "author": "VivhiteMod",
  "description": "新增魔法少女角色白绮：61 张专属卡牌、三套构筑与无上限生命魔法循环。",
  "version": "0.2.0",
  "has_pck": true,
  "has_dll": true,
  "affects_gameplay": true,
  "min_game_version": "0.111.0",
  "dependencies": [
    { "id": "STS2-RitsuLib", "version": "0.5.14" }
  ]
}
```

### 字段说明

| 字段 | 说明 |
|---|---|
| `id` | 必须与 `Entry.ModId` 和部署目录一致 |
| `pck_name` | 必须与实际导出的 `.pck` 文件名一致 |
| `version` | 当前白绮实现的 SemVer 版本 |
| `has_pck` / `has_dll` | 表示该 Mod 同时分发资源包和代码程序集 |
| `affects_gameplay` | 白绮拥有独立玩法内容，因此必须为 `true` |
| `min_game_version` | 最低兼容 STS2 版本，应与编译目标一致 |
| `dependencies` | 运行时依赖；RitsuLib 版本应与 NuGet 编译版本一致 |

## 开发提示

- 内容 ID 使用 `{MODID}_{类别}_{原名}`；卡牌完整 ID 为 `VIVHITE_CARD_<ID>`。
- 新角色内容应进入白绮自己的卡池、遗物池和状态；不得写入战士身份或注册战士资源替换。
- 白绮视觉资源统一指向当前 V3 五页白绮皮肤，不能回退旧单页 atlas 或独立静态战斗占位图；原版 `IRONCLAD` 始终使用游戏原生资源。
- 新卡图必须先核对消费者与[卡图生成技术规范](../docs/白绮卡牌图片生成技术规范.md)；完整不透明场景图走 Codex 原生生成，透明独立素材才走 EvoLink。
- 新机制的平衡只能调整费用、耗血、基础数值、成长系数、稀有度和消耗属性，不能重新加入人为封顶。
- 资源路径必须以 `res://` 开头，并确认 PCK 内目录名与大小写正确。
