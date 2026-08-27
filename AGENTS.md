# AGENTS.md

## 项目简介

Slay the Spire 2（杀戮尖塔2）角色 Mod「白绮 Vivhite」。

- 新增角色**白绮**：专属卡池/遗物池/药水池、初始卡组（4 白绮打击 + 4 白绮防御）、初始遗物（白绸结）。
- 基于基础库 **RitsuLib**（游戏内依赖 mod id：`STS2-RitsuLib`）。
- Mod id：`Vivhite`。内容 ID 规则：`{MODID}_{类别}_{原名}`（如 `VIVHITE_CARD_VIVHITE_STRIKE`）。

## 技术栈与环境

- 游戏：**Slay the Spire 2 v0.111.0**（Godot 4.5.1 Mono 引擎）。
- 语言/框架：C# / .NET 9（`net9.0`），SDK 为 Godot.NET.Sdk 4.5.1。
- 教程站：<https://tutorials.sts2modding.com/>（RitsuLib 章节为主）。
- RitsuLib 仓库：<https://github.com/BAKAOLC/STS2-RitsuLib>，主分支 0.5.x 兼容游戏 0.111.0。

### 本机路径

| 项 | 路径 |
| --- | --- |
| 游戏目录 | `G:\SteamLibrary\steamapps\common\Slay the Spire 2` |
| 游戏 exe | `G:\SteamLibrary\steamapps\common\Slay the Spire 2\SlayTheSpire2.exe` |
| 启动方式 | `%command% --rendering-driver vulkan`（**必须 vulkan**；游戏根目录 `launch_vulkan.bat` 已封装） |
| mod 部署目录 | `<游戏目录>\mods\<ModId>\`（dll + json + pck 三件套） |
| 游戏日志 | `%APPDATA%\SlayTheSpire2\logs\godot.log`（当前会话） |
| .NET SDK | `C:\Users\xenoa\AppData\Local\Microsoft\dotnet`（9.0.317 + 8.0.30 运行时） |
| Godot 编辑器 | `C:\Users\xenoa\AppData\Local\Temp\opencode\godot\...\Godot_v4.5.1-stable_mono_win64.exe`（临时目录，丢失需重下 4.5.1 mono） |

### 环境注意

- 非 Steam 启动需游戏根目录有 `steam_appid.txt`（内容 `2868840`），已创建。
- Godot 编辑器运行依赖 .NET 8 运行时；需要环境变量 `DOTNET_ROOT=<dotnet目录>` 且 PATH 含 dotnet（已写入用户环境变量）。
- `local.props`（被 .gitignore 忽略）配置 `Sts2Dir` / `GodotExe`，是本机构建的前提。

## 白绮美术素材规则

- 白绮的核心形象固定为：银发、紫色瞳孔、金色眼镜、魔法少女、华丽、可爱、冷漠；她是使用魔法的魔法师，不使用剑、法杖、魔杖或其他武器。
- 战士替换皮肤必须使用白绮自有的骨骼、网格、权重和魔法少女姿势；不得把白绮贴图套在原版战士的骨骼、网格或持剑姿势上。允许保留的只有游戏要求的角色 ID、动画/事件名称和场景锚点契约。
- 用户提供的原始参考图、AI 生成原图、模型编辑结果和实际采用的中间素材都要保存在仓库内；不得覆盖或删除原始生成图。
- **本仓库所有需要透明背景的新生成、重绘、迁移或修复素材，唯一允许的生成路径是 EvoLink `https://api.evolink.ai/v1/images/generations` 的 `gpt-image-2`，并且请求必须传 `background: "transparent"`。这是硬性要求，不是优先级建议；禁止改用内置 ImageGen、其他模型、其他供应商、绿幕、色键、传统抠图或任何备用透明化路径。** EvoLink 该路由的透明模式直接返回 PNG，公开请求结构没有 `output_format` 字段，不得臆造并发送未支持参数。
- EvoLink 透明请求必须通过 `tools/art/evolink_transparent_image.py` 或满足相同契约的仓库工具发起。API Key 只允许通过 `EVOLINK_API_KEY` 环境变量或交互式隐藏输入提供，严禁写入脚本、提示词、日志、图片元数据、仓库文件、命令行参数或 Git 历史。若 Key、余额、网络或服务不可用，必须停止并报告阻塞；不得切换备用方法。
- 每一次 EvoLink 付费生成都必须在仓库的追加式备份目录中同时保存三项内容：模型返回的未经后处理原图、逐字完整 Prompt、去除秘密后的实际请求参数。参数记录至少包含 endpoint、model、size、resolution、quality、background、n，以及所用参考图的仓库路径或公开 URL；不得记录 API Key、`Authorization` 头、临时签名下载 URL 或其他凭据。即使结果失败、不满意或最终不采用，这三项也不得覆盖或删除；缺少 Prompt 或参数记录的图片禁止进入后续素材链。
- 同一个语义素材最多允许 8 次“调整 Prompt 后重新生成”的付费尝试；8 次是硬上限，不是必须用满的配额。每次返回后立即按目标用途验收，达到可用质量就停止继续生成；8 次仍不理想时保留全部尝试，选择其中最可用者并明确记录剩余缺陷，不得擅自进行第 9 次调用。
- 提示词只描述主体、姿势、构图、材质、光照与禁止元素；不要在提示词里写“透明背景”“棋盘格”“白底”“灰底”“绿幕”等背景词，透明度只由 `background: "transparent"` 控制。白绮绑定母版还必须禁止主体外光晕、辉光、地面投影和环境光雾，避免半透明 Alpha 扩散到画布边界；魔法辉光必须另行通过同一 EvoLink 原生透明路径生成成独立特效层。
- 每张生成图必须程序化读取 Alpha 通道并进行视觉检查；聊天界面显示的黑底或棋盘格不作为判断依据。必须确认 PNG 为 RGBA、四角 `Alpha=0` 且主体内部接近不透明。Alpha 按用途验收：完整身份母版或独立魔法特效层允许连贯的整体光晕；需要拆成 Spine 身体部件的素材不得把光晕烘进关节切口，光晕应作为独立整身特效层；微弱非零 Alpha 触边是需要检查裁切风险的警告，不自动判整张失败。四角或连通背景不透明、图像中实际绘有棋盘格、或切片后会产生矩形光晕/叠亮接缝时，该图不得进入对应运行时 atlas。
- **禁止用代码、传统抠图、颜色阈值、洪水填充、色键、蒙版或后处理来创建、修补、收缩或清理主体 Alpha。** 代码只可在真透明素材验收通过后执行不改变创意内容的尺寸适配、切片和 atlas 打包。生成结果不合格时须保留该原始结果，并继续从干净设定图、头像或已验真的 EvoLink 透明参考通过同一路径重试，直到模型直接生成合格 Alpha。
- 任何源自画入 RGB 的棋盘格、绿幕、程序抠图或色键结果的素材及其全部衍生链都视为污染素材：可以为历史审计保留在仓库中，但不得作为新生成参考、绑定母版、atlas 输入或运行时素材。所有替代品必须从干净原始设定图和头像开始，经上述唯一 EvoLink 原生透明路径重新生成。
- 原始参考图、EvoLink 原始生成图、模型重试结果和每个有判断价值的中间版本均须另存并保留。处理后必须重新检查四角 Alpha、四边透明留白、发丝、眼镜、白色服装、蓝蝶、半透明魔法辉光和边缘色污染；最终运行时素材必须是真透明且无棋盘格、绿幕、外光晕触边或旧战士残片。

## 构建与部署

```powershell
cd Vivhite
dotnet build                            # 编译 dll + 导出 pck + 自动复制到游戏 mods 目录
dotnet build /p:RunPckExport=false      # 仅编译 dll（跳过 Godot 打包，改纯 C# 代码时用）
```

- 首次 PCK 导出若 Godot 未导入过项目会较慢；可用 `godot --headless --path <proj> --import` 预热。
- manifest `Vivhite.json` 的 `dependencies[STS2-RitsuLib].version` 由构建自动同步为 NuGet 实际版本。

## 真机测试工具链

`tools/test/GameTest.psm1`（PowerShell 模块）：

- `Save-Screenshot -Path <png>`：截屏（可用 Read 工具直接看图）。
- `Get-OcrText -Path <png> -Language zh-Hans`：WinRT OCR（中英文）。
- `Invoke-MouseClick -X -Y` / `Move-Mouse`：鼠标。
- `Send-Key -VkCode 0x..` / `Send-Text -Text "..."`：键盘（SendInput 扫描码）。
- **控制台输入含空格的指令时用剪贴板粘贴**（逐键发送空格会被吞）：

```powershell
Set-Clipboard "card VIVHITE_CARD_VIVHITE_STRIKE"
# Ctrl+V 粘贴后回车
```

游戏内控制台：按 `` ` ``（0xC0）开启；`card <ID>` 发卡到手牌、`dump` 导出全部 ID、`win/kill/heal` 等详见教程站。

## 子项目：sts2-ascend（自动游玩智能体）

`sts2-ascend/` 是独立的自动游玩子项目：基于上游 mod [CharTyr/STS2-Agent](https://github.com/CharTyr/STS2-Agent)
（游戏内 HTTP API，`mods/` 根目录部署 `STS2AIAgent.dll/.pck/mod_id.json`，端口 8080+），
外挂一个纯 Python 标准库的自主学习大脑（`sts2-ascend/brain/`）。

- 启动：`powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-Agent.ps1`（默认后台运行）
- 大脑记忆在 `sts2-ascend/knowledge/`（stats/policy/progression/lessons/runs，已 gitignore，**不要手工改**）
- 上游 release 包在 `sts2-ascend/third_party/dist/`（gitignore，由 `scripts/Deploy-Mod.ps1` 自动下载）
- 上游修复流程：先在 fork（XenoAmess/STS2-Agent，本地克隆 `sts2-ascend/third_party/STS2-Agent`）main 验证，再拉分支提 PR。已提：#46（AoE药水）、#47（UNLOCK屏）、#48（CRYSTAL_SPHERE 占卜屏完整支持）。`Deploy-Mod.ps1 -Source auto` 在本地 fork clone 存在时优先构建 fork；只有显式 `-Source release` 才部署官方未补丁包。
- 详细见 `sts2-ascend/README.md` 与 `docs/2026-08-22-sts2-ascend自动游玩智能体.md`

### 自动游玩全栈启停（AI 必读）

以下命令都从仓库根目录执行：

```powershell
# 默认：按 Source 部署、Vulkan 启动游戏、后台启动 runner/brain
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Start-Agent.ps1

# 完整停止：brain/runner、碎碎念、复盘 opencode/viewer/speaker，以及游戏
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1

# 只停止智能体和播报/复盘链，保留游戏
powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1 -KeepGame
```

- 用户说“启动/停止整套”“游戏 + brain + 播报员”时，AI **只使用上述统一入口**。不要分别拉起组件，不要泛杀 `python` / `uv` / `opencode`，也不要按 8080–8084 端口杀进程。
- `Start-Agent.ps1` 默认后台运行且幂等。`-SkipDeploy` 复用已部署 DLL；游戏已经运行时必须使用它，否则脚本会拒绝部署以避免 DLL 锁。`-Foreground` 仅用于调试，完整停止仍使用 `Stop-Agent.ps1`。
- `-Source auto`（默认）优先本地 fork、否则使用 release；`-Source fork` 强制 fork 构建；`-Source release` 强制官方包。自定义安装传 `-GameDir`，fork 构建可传 `-GodotExe`。
- “Stack ready”表示当前 session 的 brain 存活且 8080–8084 中某个 `/health` 已就绪。ASCEND-VISION 驾驶舱随 brain 启动，并由进程内监督器按心跳自愈；碎碎念在语音环境可用时由 brain 拉起，复盘 OpenCode 与复盘 speaker 仍按需出现。就绪等待超时只警告，runner 与驾驶舱监督器会继续在后台自愈，此时不要再启动第二套。
- 驾驶舱实时决策遥测是纯本地、确定性的 Python 标准库路径：只复用 Policy 本次已经计算出的观察、闸门、候选分数和结果，不重新评分，不调用 LLM、OpenCode、Minimax、OpenRouter 或任何网络服务，token 消耗为 0。遥测只写当前 session 的 `.runtime/live_dashboard.<SESSION_ID>.json`，采用有界队列和原子替换；异步复盘模型链本身仍可能消耗 token，二者不得混淆。
- ASCEND-VISION 必须在同一窗口使用状态驱动的稳定布局，不得按秒在整页 LIVE/REVIEW 间闪回：对局中显示决策主区和多行实时复盘流；`GAME_OVER` 显示趋势主区和复盘流；主菜单、等待或无新鲜决策时显示完整 REVIEW 视图；`--interactive` 可手动选择 LIVE/TREND/REVIEW。`knowledge/review_live.stream` 负责复盘文字展示，但不参与决策遥测、评分或动作选择。
- ASCEND-VISION 的资源根目录和 `knowledge/viewer.lock` 必须通过 `lifecycle.STACK_ROOT` 解析；复盘 clone、自检目录或备份副本不得按自身 `__file__` 建立独立 viewer 锁。复盘子进程必须继承 `STS2_ASCEND_DISABLE_VIEWER=1`。
- 楼层展示必须使用真实楼层口径 `floor_sum_raw` / `best_floor_raw`；历史 `floors_total` / `best_floor` 保留“真实楼层 + 胜利 50 分”的学习评分语义，不得拿来显示平均或最高楼层。
- 直播控制语义不变：开播仍先启动完整 sts2-ascend 栈并将杀戮尖塔2置于顶部，再通过本地哔哩哔哩直播姬开播；下播只操作直播姬，不停止任何服务、智能体或游戏。
- `Stop-Agent.ps1` 默认先发 session 哨兵，等待 40 秒协作保存/退出，再对经过 PID、创建时间、可执行文件、命令行和工作区校验的目标兜底；游戏先请求关窗，20 秒后才精确强停。`-WhatIf` 可无写入预览目标。
- `.runtime/` 由脚本维护。不要手改/删除 `session.json`、PID、lock 或 stop 文件；停止后保留的 GUID sentinel 用于防止旧进程“复活”（ABA），不是垃圾。`knowledge/` 的学习记忆同样不要手工修改。
- Runner 会在每次创建 Brain 前用纯 Git ref 文件冻结 `STS2_ASCEND_BOOT_HEAD` 与
  `STS2_ASCEND_BOOT_REVIEW_COMMIT`；二者只描述该子进程实际加载的代码/复盘 marker epoch，
  不是外部配置或 Stop 清理目标，不得由启动脚本复用旧值。旧 rollback marker 不得阻塞新复盘：
  新 marker 必须先以 `prepared` 事务接管并保存前任，工作树与 ref 均发布后才能改为 `committed`；
  CAS 中止/新代码回滚时恢复前任。只有从局间屏开始、完整跑完的新局才推进健康数。
- Runner 必须持有同一仓库事务锁，直到新 Brain 的 session PID 记录回显匹配
  `boot_id + boot_head + boot_review_commit + stage=imported`；此时模块/config 已完整载入，必须释放锁，
  再在锁外等待 `stage=ready`，避免 Agent/Knowledge 初始化重入仓库锁造成父子自锁。启动前若发现
  `prepared` marker，必须先有界证明并完成/撤回事务；无法精确证明时，先把全部目标文件和 patch
  保存进失败包，再恢复已知 Git 树。一次连续断流共用 115 秒绝对预算，回滚热路径不得等待 push。

生命周期维护规则：

- 新增长驻 Python 组件必须继承 `STS2_ASCEND_SESSION_ID`、`STS2_ASCEND_RUNTIME_DIR`、`STS2_ASCEND_STOP_FILE`，用 `brain/lifecycle.py` 的 `stop_requested()` / `wait_for_stop()` 响应停止；核心角色用 `pid_file(role)` 发布带 session 和精确创建身份的 PID 记录。
- 新增 detached 脚本或锁文件时，同步更新 `Start-Agent.ps1` 的残留拒绝清单，以及 `Stop-Agent.ps1` 的 scoped 进程、lock 和 marker 清单。身份校验不得退化为只看进程名、PID 或端口。
- 修改生命周期协议时必须同步更新 Start、Stop、AGENTS、README，并至少验证：冷启动、重复 Start、启动中 Stop、正常 Stop、重复 Stop、`-KeepGame`、复盘/TTS 活跃时 Stop，以及无关 Python/OpenCode 不被命中。

复盘安全与成果保全规则：

- **严禁重新引入“全仓指纹变化”、全仓脏状态或 refs 变化门禁。** 隔离复盘期间，真实仓的正常对局提交、推送、用户文件和运行日志变化均不得导致复盘成果作废。
- 复盘安全边界固定为：无 remote/无 hardlink 隔离 clone、deny-only 路径分类、隔离自检、二进制 patch 验收，以及真实仓提交时的私有 index + compare-and-swap。`sts2-ascend/` 下安全的静态项目文件（含新建/ignored 的源码、配置、脚本、测试、文档和静态知识）均可进入 patch；只隔离在线运行状态、Git 元数据、cache 产物和越界/不安全路径。严禁恢复固定文件 allowlist，也不要用全仓扫描替代这些局部边界。
- 复盘 active 时在线 checkpoint 仍须正常提交并推送；不得因为长复盘（统一超时 8 小时）让直播进度长期只留在本地。
- `review_queue_max` 与 `max_runs_in_packet` 当前统一为 100；它们限制单批规模，不得截断持久队列。
- 超时、进程失败、自检失败、deny-only 边界拒绝或提交冲突时，必须把隔离仓内**全部工作树改动**（含越界、被忽略和被规则拒绝的文件）保存到 `knowledge/code_backups/review_salvage/` 供人工分析；clone/快照原件必须从创建起位于项目 ignored 的 `knowledge/code_backups/review_work/`，热停只准发布项目内指针并异步补齐；自动合入只准使用通过 deny-only 分类与自检的精确 patch，补合包永不自动应用。
- 每个新失败包发布后必须立即更新受 Git 跟踪的 `sts2-ascend/REVIEW_REJECTIONS.md`，并为该条目单独建立 commit；正常运行时同步推送，整套停止临界区只准为守住两分钟死线延后 push，不得跳过 commit。补合/确认空包并从远端确认审计结论后，更新清单状态才可删除对应失败记录。
- 复盘验收必须区分“允许静态项目 patch / cache 临时产物 / 在线或越界现场 / 全量取证现场”：任一层路径名含 `cache`（大小写不敏感）或为标准 Python 字节码缓存后缀时，不进入自动 patch、也不阻断已验证源码；但文件本身仍须完整写入取证包并列入 `transient_artifact_paths`。ignored 本身不是拒绝理由；其中安全的静态项目文件照常验收，在线运行状态、Git 元数据与越界/不安全路径才拒绝整批并保全现场。
- **严禁 AI 自作主张收紧复盘模型可提交的文件范围。** 不得恢复固定文件 allowlist 或新增隐性禁区；不能借“安全”“防摸鱼”或闭环门禁之名限制模型修改 `brain/config.json`、新增源码/脚本/测试/文档或其他静态项目文件。闭环机制可以验收结果、保存现场和回退，但不得暗中覆盖或忽略模型对安全项目文件的修改。`REVIEW_PATCH_ALLOWLIST` 若仍存在，只能用于兼容缺少精确路径的历史重启 marker，绝不是模型提交边界。
- **维护 AI 是本项目的架构师，GLM 是应由机制驱动、自行完成复盘的执行者。** GLM 做错、卡住或未闭环时，优先定位并修复提示、证据、反馈、自检、观测、队列、提交或自愈机制，让下一次复盘能自己做对；不得长期由维护 AI 代写 GLM 本应完成的具体策略成果来掩盖机制缺陷。维护 AI 可以审计、保全、回退和提供最小可复现用例，但最终目标始终是 GLM 可独立工作。
- 失败合入在机制问题修复后，必须由维护 AI 重新调用 GLM，让 GLM 自己重新审核失败批次、补合有效成果、解决与当前主树的冲突、运行自检并完成提交；维护 AI 负责提供完整失败现场、可读任务和验收/重试通道，不得默认亲自代做该批具体补合。只有 GLM 重试机制本身仍有已证明故障时，维护 AI 才修该机制并再次调用 GLM。

## 工作流程规则

### 0. 必要性与成本优先（最高优先级）

- **如果不能用用户明确需求、当前真实故障、可复现测试、运行日志或现有数据证明必要性，严禁花费用户的模型额度和时间研究、设计或实现额外安全边界。** 不得在安全相关领域因为“理论上可能”“更完美”“纵深防御”而自行扩张任务；本条不限制正常的功能优化、故障修复、架构改进和主动推进。
- 提议任何新的门禁、限制、威胁模型或防御性机制前，必须先给出简短的必要性证据与预期收益；证据不足就立即停止该方向，回到用户要求的功能、稳定性和运营结果。
- 不得把假设性的 symlink、gitlink、prompt 篡改、路径逃逸等场景自动升级为当前任务；只有已经发生、能复现、用户明确要求，或存在迫近且不可逆的数据损失/凭据泄露风险时才处理。
- 本项目追求**相对安全、可观测、可记录、可回退**，不追求耗费大量额度证明“绝对安全”。优先采用最小有效修复并及时提交；不得以安全之名重新收紧复盘模型的文件范围或恢复全仓门禁。

### 1. 完成后默认提交并推送

完成任何任务后，**默认执行** `git commit` 然后 `git push`，无需再次征求确认。

- 提交信息应简洁明了，说明本次改动的内容。
- 确保只提交与本次任务相关的文件。
- 长任务必须按独立、可验证、可回退的增量及时拆分 commit 并推送；不得为了等待同一任务的所有后续问题一次修完而长期憋成一个大提交。

### 2. 完成后将经验总结进 docs

完成任何任务后，**必须将经验总结写入 `docs/` 目录**。

- 若 `docs/` 目录不存在，则先创建它。
- 经验总结包括但不限于：
  - 遇到的问题及解决方案
  - 关键技术点和注意事项
  - 踩过的坑与避免方法
- 文件命名建议：`docs/YYYY-MM-DD-主题.md`，例如 `docs/2026-08-22-初始化项目.md`。
