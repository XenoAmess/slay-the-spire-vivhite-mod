# 2026-09-01 README 层级审计与主 README 建设

## 背景与目标

仓库此前已经积累了大量设计、事故复盘和验收文档，但根目录没有 `README.md`，各子项目的入口质量也不一致：有的只有一句用途说明，有的关键运行入口没有就近文档，还有大量素材目录容易被误解为可直接发布或可作为 AI 参考的资源。

本轮工作的目标是：

1. 从仓库根目录逐层识别真正的工程边界、工具边界和素材集合边界；
2. 为每个需要独立使用或维护的边界补充可执行的 README；
3. 用父级索引覆盖纯数据、一次性生成和运行态叶目录，避免机械地给每个叶子复制相同说明；
4. 新建一份能承担项目主页、快速开始、架构导航和安全边界说明的根 `README.md`；
5. 使用仓库中已经验收的图片丰富主页，不生成新图、不修改运行时素材。

## 审计口径

本次将以下目录视为需要 README 的独立边界：

- 有自己的构建入口、测试入口、发布入口或生命周期脚本；
- 有独立的数据来源、消费合同或安全限制；
- 维护者需要从该目录直接开始工作；
- 下级目录很多，需要一个集合级索引解释状态和流转关系。

以下内容不按“缺失 README”处理：

- `bin/`、`obj/`、`__pycache__/` 等构建或缓存目录；
- `.runtime/`、`sts2-ascend/knowledge/`、`.work/`、`.tmp/` 等在线状态或取证目录；
- 一次付费生成尝试中的 `inspection/`、临时 Godot 工程和单个素材叶目录；
- 被忽略的 `sts2-ascend/third_party/STS2-Agent/` 本地 checkout，其自身沿用上游 README，仓库只在父级说明 fork、source 与部署关系。

这些目录如果逐叶复制 README，反而会造成规则漂移。它们由最近的集合级 README 统一解释，并由 manifest、参数记录、provenance 或测试报告保存逐项事实。

## 覆盖结果

完成后，排除构建、缓存和运行态目录，仓库共有 **88 份 `README.md`**，另有 **1 份 `Vivhite/README.en.md`**；89 份 README 类文档均有一级标题，静态相对链接检查为 `bad_links=0`。

| 层级 | 当前入口 | 主要补全内容 |
| --- | --- | --- |
| 仓库根 | [`../README.md`](../README.md) | 项目定位、已验证基线、画廊、架构图、目录地图、Mod/Brain 快速开始、验收、美术、Workshop、排障与许可证 |
| 角色 Mod | [`../Vivhite/README.md`](../Vivhite/README.md)、[`../Vivhite/README.en.md`](../Vivhite/README.en.md) | 61 张卡牌、模块布局、构建/部署、66 项接受测试、PCK/真机门禁、素材与发布流程 |
| C# 验收 | [`../Vivhite.Tests/README.md`](../Vivhite.Tests/README.md) | 测试覆盖、环境准备、运行命令、失败诊断和测试新增约定 |
| 自动游玩栈 | [`../sts2-ascend/README.md`](../sts2-ascend/README.md) | 统一启停、真实游玩证据、Profile、复盘、驾驶舱、SteamMode、无人值守和直播失败关闭 |
| Brain 内核 | [`../sts2-ascend/brain/README.md`](../sts2-ascend/brain/README.md) | API、策略、轮换、持久化、runner、遥测、直接运行风险和模块地图 |
| 运维脚本 | [`../sts2-ascend/scripts/README.md`](../sts2-ascend/scripts/README.md) | Start/Stop/Deploy、session 身份、Steam 空间/同意门禁、诊断、直播桥接和 UAC 边界 |
| Brain 测试 | [`../sts2-ascend/tests/README.md`](../sts2-ascend/tests/README.md) | 全量/单文件测试、隔离要求、常见失败和新增回归规范 |
| Brain 复盘记录 | [`../sts2-ascend/docs/README.md`](../sts2-ascend/docs/README.md) | 18 份局部复盘/观测记录的索引；与根 docs 历史报告分层 |
| TTS 与诊断 | [`../sts2-ascend/tts/README.md`](../sts2-ascend/tts/README.md)、[`../sts2-ascend/tools/README.md`](../sts2-ascend/tools/README.md) | owner epoch、provider/fallback、游戏知识快照与诊断工具 |
| 游戏知识 | [`../sts2-ascend/tools/game-knowledge/README.md`](../sts2-ascend/tools/game-knowledge/README.md) | 原生快照来源、schema、包装器、256 MiB 限制、版本绑定和 CLI |
| 上游 Agent | [`../sts2-ascend/third_party/README.md`](../sts2-ascend/third_party/README.md) | fork/release 选择、当前 checkout 动态事实、PR 与可复现构建流程 |
| 素材总览 | [`../assets/README.md`](../assets/README.md) | 原版只读基线与白绮素材仓的隔离、图像分类和版权边界 |
| 白绮素材树 | [`../assets/vivhite-ironclad/README.md`](../assets/vivhite-ironclad/README.md) | `references → generated → candidates/evaluation → approved/custom` 血缘；各集合拥有就近索引 |
| 工具总览 | [`../tools/README.md`](../tools/README.md) | art/test/workshop 三条工具链的入口、写入范围和安全边界 |
| Vivhite 候选输出 | [`../Vivhite/tools/candidates/README.md`](../Vivhite/tools/candidates/README.md) | 17 个皮肤/Spine 候选输出目录的镜像索引；明确不进入 PCK |
| 美术工具 | [`../tools/art/README.md`](../tools/art/README.md) | 原版消费合同、EvoLink 原生透明、Alpha/SourceOver、atlas/Spine、候选和测试 |
| 真机/PCK 工具 | [`../tools/test/README.md`](../tools/test/README.md) | 截图/OCR/输入副作用、PCK 四层门禁和自包含测试 |
| Workshop 工具 | [`../tools/workshop/README.md`](../tools/workshop/README.md) | 预览生成、版本/描述/哈希合同、上传器、测试与 UAC 边界 |
| 发布物料 | [`../workshop/README.md`](../workshop/README.md) | BBCode、双语 Changelog、preview、历史 SHA、三件套与远端确认 |
| 文档/提示词/预留源码 | [`README.md`](README.md)、[`../prompts/README.md`](../prompts/README.md)、[`../src/README.md`](../src/README.md) | 事实源优先级、历史报告索引、提示词用途和空目录归属 |

素材树和美术工具树采用“集合 README + 有独立合同的候选 README”策略。`approved`、`custom`、`evaluation`、`generated`、`legacy-contaminated`、`references`、`prompts` 以及主要 Spine/语义候选均有入口；单次生成尝试仍由其参数、Prompt 和验收记录表达，不复制通用规则。

## 根 README 的信息架构

根 [`README.md`](../README.md) 现在按第一次访问仓库的阅读路径组织：

1. 一屏内说明白绮 Mod、自动游玩 Brain 和素材/发布工具链的关系；
2. 给出游戏、引擎、SDK、RitsuLib、Mod、卡牌数和 Workshop 的已验证基线；
3. 用画廊与 Mermaid 图展示成品外观和组件数据流；
4. 提供可复制的 Mod 构建、三件套部署、Brain 启停与验收命令；
5. 明确 `Stack ready` 不等于真实游玩、当前保持下播、不得自动复播或无人值守处理 UAC；
6. 汇总美术 Alpha/atlas 规则和 Workshop 版本、BBCode、预览、哈希、回执闭环；
7. 用故障表覆盖 `MAIN_MENU/run_unknown`、无动作、DLL 锁、Steam 空间、SteamMode off、PCK、Workshop 和 UAC。

## 图片选择与消费证据

主页只复用了三张已经存在且有验收来源的图片，没有调用付费生成，也没有修改任何 PNG/JPEG：

| 文件 | 分类 | 用途与证据 |
| --- | --- | --- |
| `workshop/preview.jpg` | 1024×1024 单幅成品 JPEG | `workshop/workshop-item.json` 与发布脚本消费的当前 Workshop 预览；不是 atlas |
| `docs/screenshots/char_select.png` | 1920×1080 单帧实机截图 | 角色选择真机证据，来源和用途见 `2026-08-22-白绮角色mod-demo搭建与真机测试.md` |
| `docs/screenshots/combat_attack.png` | 1920×1080 单帧实机截图 | 战斗动作真机证据，同一报告记录；不是运行时资源源图 |

因此本轮不涉及透明 Alpha 生成、拆件、Spine 页重打包或素材候选状态变更。README 也明确禁止把这些展示图反向当作生成参考或运行时 atlas 输入。

## 事实纠正

`sts2-ascend/third_party/README.md` 原先把被忽略的本地 fork checkout 固定描述为 `main` 和历史 SHA。审计时实际 checkout 为 `integration/native-progression-event-localization`、HEAD `c9c2101`。文档已经改为动态事实：部署前只读记录 branch、HEAD 与 dirty 状态；`-Source auto` 会优先构建当前本地 checkout，只有显式 `-Source release` 才使用官方 release 包。

## 验证

本轮使用以下只读或离线命令验证文档和现有合同；不启动游戏、Brain 或直播，不请求 UAC：

```powershell
# README 标题和相对链接静态检查
rg --files -g 'README.md' -g 'README.en.md'

# C# 离线接受测试（本机需要先把仓库记录的 .NET SDK 加入 PATH）
dotnet run --project .\Vivhite.Tests\Vivhite.Tests.csproj --no-restore

# 美术与 Workshop 合同测试
py -3 -B -m unittest discover -s .\tools\art\tests -p "test_*.py" -v
py -3 -B -m unittest discover -s .\tools\workshop\tests -p "test_*.py" -v

# 与本次入口/边界最相关的 Brain 回归（按文件分组）
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_renderer_compatibility_docs.py" -v
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_start_agent_steam_*.py" -v
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_bilibili_live_scripts.py" -v
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_broadcast_window_patrol.py" -v
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_workshop_materials.py" -v
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_runner_handshake.py" -v

# PCK 行为回归（合成 PCK，不启动真实游戏）
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\test\Verify-VivhitePck.Tests.ps1

# 提交前格式检查
git diff --cached --check
```

已确认结果：

- README 类文档：89（`README.md` 88 份、`README.en.md` 1 份）；缺失一级标题：0；失效相对链接：0；
- `tools/art/tests`：8/8 通过；
- `tools/workshop/tests`：3/3 通过；
- Brain 相关聚焦回归：65/65 通过（文档 3、SteamMode/空间/同意 16、直播桥接 28、窗口巡检 8、Workshop 5、runner 握手 5）；
- PCK 行为回归：12/12 通过；
- `Vivhite.Tests`：66/66 通过（`Result: 66 passed, 0 failed, 66 total.`）；
- 提交前格式检查：在暂存文档后执行 `git diff --cached --check`，无空白错误。

`sts2-ascend` 全量测试在本轮其他并行审计中为 750 项中的 749 项通过；现有环境相关用例 `test_sandbox_path_escape_is_rejected_before_host_selfcheck` 期望 `runner_tool_path_escape`、实际得到空错误码。该结果没有被 README 工作掩盖，也不能写成“全量通过”；本轮只把准确的运行命令和测试边界写入文档。

## 维护约定与遗留风险

- 版本、卡牌数、素材清单、RitsuLib 依赖、Workshop ID 或脚本参数变化时，应在同一变更中更新根 README 和对应子项目 README。
- 新增独立工具/构建入口时先判断是否形成新的维护边界；形成边界就补 README，纯产物叶目录则更新父级索引。
- 新增报告时同步更新 `docs/README.md` 的主题入口与日期清单，避免只存在于文件系统中。
- 发布新版本时仍必须同步两份 manifest、双语 BBCode Changelog、预览图与历史 SHA；README 不能替代发布门禁。
- 在线 `knowledge/`、`.runtime/` 和被忽略的 fork checkout 会持续变化；文档提交不得顺手暂存、回退或覆盖这些状态。
- 直播是独立、显式授权的操作。本轮保持下播，没有调用任何开播或自动复播入口。
