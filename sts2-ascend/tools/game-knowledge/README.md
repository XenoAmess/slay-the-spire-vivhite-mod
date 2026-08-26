# STS2 原生游戏知识提取器

这个目录把本机安装的 Slay the Spire 2 转成可校验、按游戏版本隔离的知识快照。Python 部分只使用标准库，并以只读方式打开游戏目录；所有生成文件只写入显式输出目录。当前目标版本是 `v0.111.0`。

## 为什么有三层数据

任何单一来源都不完整：

- `runtime/*.jsonl` 来自 STS2AIAgent 的 `/data/*`，提供 ModelDb 实例化后的卡牌数值、升级、池、角色初始配置等规范数据。
- `mechanics/*.jsonl` 来自本机 `sts2.dll` 的静态事实抽取，提供字段/属性表达式、实例与静态构造器、getter/setter/init accessor、调用、对象创建、赋值、一元 `++`/`--` 变异、条件、switch、循环、throw/yield/await、返回值、递归嵌套类型，以及怪物移动状态机。每个构造器、accessor 和方法还包含规范化嵌套 `control_flow` 语句树，包括 lambda/匿名 delegate 回调中的语句，保留 if/else、switch case、循环和 try/catch 到具体效果的父子关系，而不保存可重编译的整段源码。除 PCK 中全部 Model 类型外，还覆盖 Commands、GameActions、Combat、卡牌引擎、Runs、Creatures、Players、ValueProps、Random、Core.Events 和决策关键 helper。ILSpy AST 会把 expression-bodied method 规范化进 `MethodDeclaration.Body`，同一路径会保留其顶层调用/返回事实。它补上 runtime 怪物接口目前全部缺失的 move 数值和行为。
- `localization/{eng,zhs}/*.json` 从官方 PCK 原样抽取，提供英文和简体中文文本。`catalog/pck-index.jsonl` 与 `catalog/model-source-types.jsonl` 则给出完整资源/原生类型基集。

`catalog/localization-bilingual.jsonl` 将两种语言逐 key 对齐。若官方中文缺 key，记录会保留 `zhs: null`、标记 `missing_zhs`，并通过 `zhs_or_eng` + `fallback_locale: eng` 提供显式英文回退；不会静默冒充中文。

`catalog/runtime-mechanics-joins.jsonl` 使用游戏自己的 ID 规则关联前两层：`StringHelper.Slugify(type.Name)` 会在每个非首位大写字母前插入下划线，再大写、折叠空白并删除非 `[A-Z0-9_]` 字符。关联是精确匹配，不使用模糊名称猜测。

## 一次性生成完整快照

先构建并运行静态抽取器：

```powershell
$dotnet = 'C:\Users\xenoa\AppData\Local\Microsoft\dotnet\dotnet.exe'
$game = 'G:\SteamLibrary\steamapps\common\Slay the Spire 2'
$facts = Join-Path ([System.IO.Path]::GetTempPath()) 'sts2-mechanics-v0.111.0'

& $dotnet build .\GameKnowledge.Tool\GameKnowledge.Tool.csproj -c Release
& $dotnet .\GameKnowledge.Tool\bin\Release\net9.0\GameKnowledge.Tool.dll `
  "$game\data_sts2_windows_x86_64\sts2.dll" extract $facts
```

游戏运行时可以直接探测 8080–8084：

```powershell
py -3 .\game_knowledge.py extract `
  --game-dir $game `
  --discover-runtime `
  --mechanics-dir $facts
```

也可以导入事先保存的响应。目录内文件名必须是 `<collection>.response.json`，内容可以是 `/data/*` 原始数组，或 `{ "data": [...] }` 响应包装：

```powershell
py -3 .\game_knowledge.py extract `
  --game-dir $game `
  --runtime-response-dir 'C:\path\to\captured-responses' `
  --mechanics-dir $facts
```

默认输出为 `sts2-ascend/knowledge/game/<release_info.version>/`。也可以分步执行：

```powershell
py -3 .\game_knowledge.py runtime `
  --output-dir '..\..\knowledge\game\v0.111.0' `
  --runtime-response-dir 'C:\path\to\captured-responses'

py -3 .\game_knowledge.py mechanics `
  --output-dir '..\..\knowledge\game\v0.111.0' `
  --mechanics-dir $facts

py -3 .\game_knowledge.py validate `
  --output-dir '..\..\knowledge\game\v0.111.0' `
  --game-dir $game
```

`--full-pck-sha256` 会额外读取并哈希约 2 GB 的完整 PCK。默认记录 PCK directory SHA256；目录表本身包含所有条目的路径、长度、flags 和 Godot MD5，因此足以快速检测资源清单变化。

## 输出结构

```text
knowledge/game/v0.111.0/
  manifest.json                    版本、来源哈希、计数、过滤与关联结果
  validation.json                  完整性报告
  catalog/
    pck-index.jsonl                15,890 个 PCK 条目的完整目录
    model-source-types.jsonl       PCK 内原生 Model 类型路径
    localization-bilingual.jsonl  英中逐 key 并集与显式回退
    runtime-mechanics-joins.jsonl  runtime ID 到静态类型的精确关联
  localization/{eng,zhs}/*.json   官方双语文本
  runtime/*.jsonl                  实例化 ModelDb 数据
  mechanics/*.jsonl                静态属性和行为事实
```

JSONL envelope 的 JSON Schema 位于 `schemas/`。静态事实 v4 要求 `constructors`、每个属性的 `accessors`、`is_nested`、`declaring_type_name`、所有行为数组，以及递归校验的 `control_flow` 节点；嵌套类型使用标准的 `Outer+Inner` 唯一名且没有独立 runtime ID。validator 直接按该 schema 递归检查每条记录，核对 1,724 个 PCK Model 顶层类型闭包，并沿继承链确认每个 runtime 怪物确有实质移动状态机事实。双语目录从官方 eng/zhs 文件逐键重建后比较，不把生成目录自身当真值。`manifest.json` 中每个 artifact 都有长度、SHA256 和记录数；`validation.json` 绑定最终 manifest SHA256 和实际 artifact-set SHA256，读取层会拒绝旧报告或被改写的快照。validator 还会检查基础角色初始内容引用闭包、runtime/static 程序集一致性以及关联覆盖率。

## 原生模型过滤

优先使用 endpoint 的 `source_assembly`，只接受程序集 simple name 为 `sts2` 的对象。旧 endpoint 不提供该字段时，使用官方 PCK 的 `src/Core/Models/**/*.cs` 类型路径作为原生 ID 基集；这能保留没有 localization 的原生怪物分段、临时 Power 和内部模型。只有类型基集不可用时才退到 localization ID；若两者都不可用，记录保留但 `base_game_filter` 标为 `unavailable`，validator 会显式告警。

静态 facts 可能比 runtime ModelDb 多出 mock、deprecated、剧情专用或尚未注册的原生类型。这类对象记录为 `complete_with_static_only`，不等于漏数；真正的完整性错误是 `runtime_without_mechanics` 非空。

## 版本、版权与体积注意

- 快照只能用于 manifest 指明的游戏 commit/程序集 SHA。游戏更新后必须生成新的版本目录，不能覆盖旧版本后继续沿用旧结论。
- PCK 中的 `.cs` 仅是一字节导出占位，不能当作源码；行为事实来自本机程序集的结构化静态分析。
- 不提交反编译源码、贴图、音频或完整 PCK。仓库只保存运行时结构化数据、选定控制流与状态变化的结构化事实摘要、短本地化文本和来源哈希；这些 facts 不是可重新编译的完整反编译源码。
- `manifest.json` 是权威文件清单；未列入 `artifacts` 的残留生成文件不属于快照。
- 原生数据会随 Early Access 版本改变，AI 推理时应始终同时引用 `game.version`、`game.commit` 和 assembly SHA256。

## 测试

测试使用内存生成的最小 Godot PCK 和合成 runtime/mechanics 响应，不依赖安装游戏：

```powershell
py -3 -m unittest discover -s tests -v
```
