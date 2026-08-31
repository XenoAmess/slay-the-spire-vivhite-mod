# Vivhite

语言 / Languages：中文 | [English](README.en.md)

`Vivhite` 是《杀戮尖塔 2》的白绮角色 Mod。白绮是一位精通数学、计算机与艺术的魔法少女、魔法大师；她以生命作为魔法演算材料，通过“支付謦欬施法 → 击杀或汲取回血 → 继续施法”建立战斗循环。

本文描述当前 `0.2.0` 角色实现。完整 61 张卡牌目录与逐牌数值见[《白绮角色与轮换大脑实现》](../docs/2026-08-30-白绮角色与轮换大脑实现.md)。最终运行时位图清单契约为 `92` 项，皮肤发布/校验契约为 legacy/V3 `30/34`；统一静态门禁、同批完整 PCK 与 Vulkan 真机验收仍待执行，本文不提前宣称通过。

**角色概要：**

- 初始属性：`78` 最大生命、`99` 金币、每回合 `3` 能量、抽 `5` 张牌。
- 初始牌组：4 × 弦光投影、4 × 闭域映射、1 × 白绮的变身式。
- 初始遗物：孤高冠冕——每当任意敌人死亡，立即回复最大生命的 `20%`，向上取整；同一实体的同一次死亡只结算一次。
- 专属卡池共 `61` 张：3 基础、18 普通、24 罕见、16 稀有。
- 三套主要构筑：守恒几何、递归星算、绯彩积分，并有跨体系组合牌。
- 美术契约共 `92` 张运行时位图：既有 89 项内容位图，加眼镜星光、白绮专属卡牌轨迹与角色选择转场各 1 张。

## 学习资源

- [STS2-RitsuLib](https://github.com/BAKAOLC/STS2-RitsuLib)：本项目用于内容注册、角色接入与 Godot 资源集成的基础库。
- [RitsuLib 文档](https://github.com/GlitchedReme/SlayTheSpire2ModdingTutorials/tree/master/RitsuLib)：按文件组织的教程和示例。
- [Slay the Spire 2 Modding Tutorials](https://glitchedreme.github.io/SlayTheSpire2ModdingTutorials/index.html)：完整教程站点。

## 安装与使用

### 方式 A：从源码构建（推荐）

1. 安装《杀戮尖塔 2》并准备 Godot 4.5.1 Mono、.NET 9 和 RitsuLib。
2. 按下文创建 `local.props` 并填写本机路径。
3. 在本目录运行 `dotnet build .\Vivhite.csproj`。完整构建会生成并部署 dll、manifest 和 pck。
4. 确认游戏的 `mods` 目录同时包含 `Vivhite` 与依赖 `STS2-RitsuLib`。

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
| `dotnet build .\Vivhite.csproj` | 完整构建：编译 + `CopyMod` + `ExportPCK` |
| `... /p:RunPckExport=false` | 跳过 PCK 导出 |
| `... /p:CopyModOnBuild=false` | 跳过复制到游戏 mods 目录，产物只留在 `bin/` |
| `... /p:RunPckExport=false /p:CopyModOnBuild=false` | 仅进行 C# 编译检查 |

完整构建会在 `Build` 后运行：

- **`CopyMod`**：复制 dll 和 manifest 到游戏的 `mods/Vivhite` 目录。
- **`ExportPCK`**：调用 `GodotExe`，将 pck 导出到同一 Mod 目录。

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

另有跨体系牌连接余裕、抽牌、击杀和汲取，包括按回合无限提高攻击謦欬与伤害的“白绮的猩红转化仪式”。该牌是固定謦欬翻倍规则的特例：运行时 `LifeCostPerPhase=1`，作用于攻击的额外謦欬每阶段只增加 `+1`，不随其他固定謦欬翻倍。完整 61 张牌的 ID、费用、效果和升级数值见[完整实现文档](../docs/2026-08-30-白绮角色与轮换大脑实现.md)。旧的“白绮打击”“白绮防御”“白绸结”只是已废弃的 Demo 内容，不属于当前注册、初始牌组或卡池。

### 核心关键词

| 关键词 | 语义 |
|---|---|
| `謦欬 N` | 在牌面效果及该牌引发的任何回血前损失 N 点不可格挡、不会被力量修改的生命；支付后会低于 1 生命时不可打出 |
| `余裕 N` | 自动按 1:1 抵消謦欬并被消耗 |
| `增维 N` | 永久增加 N 点最大生命，并同时增加 N 点当前生命 |
| `汲取 N%` | 整张攻击牌结算后汇总多段与群体实际造成的敌方生命损失，乘以总汲取率，并将最终回血量向上取整一次 |
| `致命` | 该牌的伤害直接令目标死亡时触发对应效果 |

牌面、本场全局与本回合临时汲取率按百分点相加，总汲取率和最终回复量均无自定义硬上限。汲取不计算格挡、过量伤害、自伤、荆棘或非攻击牌伤害。

### 无人为上限

白绮机制不设置最大生命成长、余裕、击杀回复、汲取百分点、汲取回复量、力量、抽牌成长或其他自定义硬上限。临时生成、复制、重复结算和从弃牌堆或消耗堆回收的牌与原牌同权，能够触发永久增维；汲取率可以超过 `100%`。

保留的只有游戏自然不变量：

- 当前生命不能超过最大生命。
- 謦欬的实际费用最低为 0。
- 支付后会低于 1 点生命的牌不可打出。
- 手牌数量等继续遵循游戏原生规则。
- 同一敌人的同一次死亡事件只结算一次；这是事件去重，不是回复上限。

### 共用 V3 皮肤与运行时美术契约

独立白绮角色与战士替换皮肤共用当前同一套白绮 V3 五页战斗 atlas，以及对应的商店、休息、选人、UI、Spine 和多人资源。两者仍保留不同的角色 ID、卡池、角色状态和统计数据；共享视觉资源不等于共享玩法身份。

最终运行时位图清单契约为 `92` 项：61 张卡图、19 个 Power 语义图标、2 张孤高冠冕资源、7 张能量 UI，以及眼镜星光、白绮专属卡牌轨迹、角色选择转场各 1 张。皮肤发布根内新增眼部控制器/贴图与转场贴图/材质后，legacy-single-page 与 v3-five-page 的精确皮肤契约分别为 `30` 和 `34` 个文件，即 `30/34`。

卡牌轨迹场景与贴图位于皮肤发布根外，只由 `VivhiteCharacter` 的白绮 profile 通过独立 `WithVfx` 接入；它不会写入 `IroncladReplacementAssets`，也不会让战士获得该轨迹。`92` 与 `30/34` 描述最终源资源/消费者契约，不代表完整 PCK 同批部署或 Vulkan 真机验收已经通过。

### Brain 外部工具说明（非 Mod 功能）

`Ctrl+Alt+F9`（人工接管）与 `Ctrl+Alt+F10`（恢复自动操作）只属于 `sts2-ascend` Brain 在全栈驻留期间的控制功能，并不是 Vivhite Mod 的游戏热键；完整语义见[《sts2-ascend Brain 人工接管快捷键》](../docs/2026-08-30-sts2-ascend-Brain人工接管快捷键.md)。

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
- 新角色内容应进入白绮自己的卡池、遗物池和状态，不要因共享皮肤而写入战士身份。
- 角色视觉资源统一指向当前 V3 五页白绮皮肤，不能回退旧单页 atlas 或独立静态战斗占位图。
- 卡图与透明 VFX 的新增或修订必须遵循[白绮卡牌图片生成技术规范](../docs/白绮卡牌图片生成技术规范.md)及对应美术活文档；完整不透明场景与明确需要 Alpha 的独立素材使用各自规定的生成路径。
- 新机制的平衡只能调整费用、耗血、基础数值、成长系数、稀有度和消耗属性，不能重新加入人为封顶。
- 资源路径必须以 `res://` 开头，并确认 PCK 内目录名与大小写正确。
