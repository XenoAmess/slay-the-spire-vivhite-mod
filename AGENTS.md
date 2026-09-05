# AGENTS.md

## 项目简介

Slay the Spire 2（杀戮尖塔2）角色 Mod「白绮 Vivhite」。

- 新增角色**白绮**：61 张专属卡牌（3 基础、18 普通、24 罕见、16 稀有）；初始卡组为
  4 × 弦光投影、4 × 闭域映射、1 × 白绮的变身式；初始遗物为孤高冠冕。
- 旧“白绮打击 / 白绮防御 / 白绸结”仅属于已废弃占位设计，不得重新注册、接入卡池或作为当前实现依据。
- 基于基础库 **RitsuLib**（游戏内依赖 mod id：`STS2-RitsuLib`）。
- Mod id：`Vivhite`。内容 ID 规则：`{MODID}_{类别}_{原名}`（如 `VIVHITE_CARD_LUMINOUS_PROJECTION`）。

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
| 启动方式 | `%command% --rendering-driver vulkan`（本机统一训练/验收固定使用 Vulkan；这不是对所有硬件的绝对兼容性承诺；游戏根目录 `launch_vulkan.bat` 已封装；需要隔离 Steam 云同步时通过统一入口显式传 `-SteamMode off`） |
| mod 部署目录 | `<游戏目录>\mods\<ModId>\`（dll + json + pck 三件套） |
| 游戏日志 | `%APPDATA%\SlayTheSpire2\logs\godot.log`（当前会话） |
| .NET SDK | `C:\Users\xenoa\AppData\Local\Microsoft\dotnet`（9.0.317 + 8.0.30 运行时） |
| Godot 编辑器 | `C:\Users\xenoa\AppData\Local\Temp\opencode\godot\...\Godot_v4.5.1-stable_mono_win64.exe`（临时目录，丢失需重下 4.5.1 mono） |

### 环境注意

- 非 Steam 启动需游戏根目录有 `steam_appid.txt`（内容 `2868840`），已创建。
- Godot 编辑器运行依赖 .NET 8 运行时；需要环境变量 `DOTNET_ROOT=<dotnet目录>` 且 PATH 含 dotnet（已写入用户环境变量）。
- `local.props`（被 .gitignore 忽略）配置 `Sts2Dir` / `GodotExe`，是本机构建的前提。

## 白绮美术素材规则

- 任何白绮 AI 生图任务在付费调用前必须完整阅读并遵循 `docs/白绮AI生成图Prompt工程手册.md`；任何战斗 Sprite、Spine、部件粒度、骨骼或动作方案变更还必须完整阅读 `docs/白绮战斗Sprite-Spine方案演进与生产方案.md`。两份文件都是长期维护的事实源，不是一次性总结。
- 新增付费生成、候选状态变化、Prompt/消费契约/Alpha 误判、运行时接入结果或用户真机反馈时，必须在完成该任务前同步更新上述对应活文档及其修订记录。不得静默覆盖被推翻的旧结论；必须记录旧结论、纠正证据、当前状态和下一道门禁。
- 白绮的核心形象固定为：银发、紫色瞳孔、金色眼镜、魔法少女、华丽、可爱、冷漠；她是使用魔法的魔法师，不使用剑、法杖、魔杖或其他武器。
- 战士替换皮肤必须使用白绮自有的骨骼、网格、权重和魔法少女姿势；不得把白绮贴图套在原版战士的骨骼、网格或持剑姿势上。允许保留的只有游戏要求的角色 ID、动画/事件名称和场景锚点契约。
- 用户提供的原始参考图、AI 生成原图、模型编辑结果和实际采用的中间素材都要保存在仓库内；不得覆盖或删除原始生成图。
- **分析或生成任何游戏图片前，必须先判断它是单幅成品、单帧、atlas/spritesheet、tile sheet，还是多个独立区域拼在同一 PNG 中，并同时核对原版素材与实际消费它的源代码。** 素材侧优先读取相邻 `.atlas`、`.spatlas`、Spine JSON、`.tres`、manifest 或其他布局元数据，枚举 region 名称、bounds、旋转、offset、页数与 Alpha 岛；源码侧必须检索 C#、GDScript、场景文件及可用的反编译代码，追踪资源加载路径、region/slot、动画与事件名、节点锚点、缩放、材质、混合模式、UV 和尺寸约束。不能仅凭文件扩展名、肉眼看到的几个大块或原版贴图本身推断用途；若源码不可得，必须明确记录证据缺口。若图片是图集，必须先按“素材布局契约 + 源码消费契约”制定人物主体、前后肢体、头发、特效、背景等逐项制作方案，分别生成或编辑源素材，最后再确定性打包；禁止把 packed atlas 当作一幅完整插画交给模型整体重绘，也禁止把图集页误报成“单张场景图”。该检查必须发生在任何付费生成调用之前。
- **本仓库所有需要透明背景的新生成、重绘、迁移或修复素材，唯一允许的生成路径是 EvoLink `https://api.evolink.ai/v1/images/generations` 的 `gpt-image-2`，并且请求必须传 `background: "transparent"`。这是硬性要求，不是优先级建议；禁止改用内置 ImageGen、其他模型、其他供应商、绿幕、色键、传统抠图或任何备用透明化路径。** EvoLink 该路由的透明模式直接返回 PNG，公开请求结构没有 `output_format` 字段，不得臆造并发送未支持参数。
- EvoLink 透明请求必须通过 `tools/art/evolink_transparent_image.py` 或满足相同契约的仓库工具发起。API Key 只允许通过 `EVOLINK_API_KEY` 环境变量或交互式隐藏输入提供；Windows 下仓库工具必须兼容读取尚未被当前进程继承的用户级 `EVOLINK_API_KEY`，读取期间不得输出其值。严禁把 Key 写入脚本、提示词、日志、图片元数据、仓库文件、命令行参数或 Git 历史。若 Key、余额、网络或服务不可用，必须停止并报告阻塞；不得切换备用方法。
- 每一次 EvoLink 付费生成都必须在仓库的追加式备份目录中同时保存三项内容：模型返回的未经后处理原图、逐字完整 Prompt、去除秘密后的实际请求参数。参数记录至少包含 endpoint、model、size、resolution、quality、background、n，以及所用参考图的仓库路径或公开 URL；不得记录 API Key、`Authorization` 头、临时签名下载 URL 或其他凭据。即使结果失败、不满意或最终不采用，这三项也不得覆盖或删除；缺少 Prompt 或参数记录的图片禁止进入后续素材链。
- 同一个语义素材最多允许 8 次“调整 Prompt 后重新生成”的付费尝试；8 次是硬上限，不是必须用满的配额。每次返回后立即按目标用途验收，达到可用质量就停止继续生成；第 8 次仍不合格时必须保留全部尝试，记录逐次失败原因、当前最佳候选和剩余缺陷，先跳过该素材并继续下一项，最终交由用户统一评审。未经用户针对该素材追加额度，不得擅自进行第 9 次调用，也不得把不合格的最佳候选冒充最终通过。
- 提示词只描述主体、姿势、构图、材质、光照与禁止元素；不要在提示词里写“透明背景”“棋盘格”“白底”“灰底”“绿幕”等背景词，透明度只由 `background: "transparent"` 控制。白绮绑定母版还必须禁止主体外光晕、辉光、地面投影和环境光雾，避免半透明 Alpha 扩散到画布边界；魔法辉光必须另行通过同一 EvoLink 原生透明路径生成成独立特效层。
- 每张生成图必须程序化读取 Alpha 通道并进行视觉检查；聊天界面、`view_image`、普通透明 PNG 直显、黑底缩略图或棋盘格不作为 Alpha 判断依据，因为查看器可能把 `Alpha=0` 或极低 Alpha 像素中的 RGB 未经真实衰减地夸大显示。必须使用真实 SourceOver 分别合成到纯黑、纯白、接近实际场景的底色并在实际显示尺寸复核；存在关节、叠层或邻接消费者时还必须合成真实相邻附件的 setup pose 和最大旋转，完整姿势、UI 与独立 VFX 则验真实前后景层，不虚构相邻人体件。`Alpha>0` bbox、低 Alpha 绝对数量或透明像素 RGB 只能提示打包/边界风险，禁止单独据此判定可见光晕。必须确认 PNG 为 RGBA、四角 `Alpha=0` 且主体内部接近不透明。Alpha 按用途验收：完整身份母版或独立魔法特效层允许连贯的整体光晕；需要拆成 Spine 身体部件的素材不得把光晕烘进关节切口，光晕应作为独立整身特效层；微弱非零 Alpha 触边是需要检查裁切风险的警告，不自动判整张失败。四角或连通背景不透明、图像中实际绘有棋盘格、或真实 SourceOver 及关节叠层后会产生矩形光晕/叠亮接缝时，该图不得进入对应运行时 atlas。
- **禁止用代码、传统抠图、颜色阈值、洪水填充、色键、蒙版或后处理来创建、修补、收缩或清理主体 Alpha。** 代码只可在真透明素材验收通过后执行不改变创意内容的尺寸适配、切片和 atlas 打包。生成结果不合格时须保留该原始结果，并只在该语义素材剩余的八次额度内，从干净设定图、头像或已验真的 EvoLink 透明参考通过同一路径重试；第八次仍不合格时必须停止并按上一条交用户评审。
- 任何源自画入 RGB 的棋盘格、绿幕、程序抠图或色键结果的素材及其全部衍生链都视为污染素材：可以为历史审计保留在仓库中，但不得作为新生成参考、绑定母版、atlas 输入或运行时素材。所有替代品必须从干净原始设定图和头像开始，经上述唯一 EvoLink 原生透明路径重新生成。
- **用户于 2026-08-28 明确授权一项封闭例外：仅 `assets/vivhite-ironclad/custom/ui/multiplayer/` 下的 `point.png`、`rock.png`、`paper.png`、`scissors.png` 四张多人手势，允许从 `legacy-contaminated/2026-08-27/custom/ui/multiplayer/` 逐字节恢复，并可进入发布与运行时。** 这四张不得作为后续 AI 生成参考，也不得重做 Alpha；该例外不适用于任何其他污染素材、路径或衍生品。
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
- **Steam 本地存档模式**：统一入口支持可审计的 `-SteamMode auto|on|off`（默认 `auto`）。`auto` 和 `on`
  不覆盖游戏默认 Steam 初始化；只有用户显式指定 `off` 时，冷启动才向 `launch_vulkan.bat` 传
  `--force-steam off`。它只作用于本次游戏进程，不改游戏目录、Steam 客户端或云同步文件，也不需要
  UAC/人工 GUI；会话 `session.json` 记录请求模式、参数及 `steam_mode_applied`。若游戏已在运行，参数
  不会 retroactively 改变该进程，必须先用统一 `Stop-Agent.ps1` 停止，再以 `-SteamMode off` 冷启动。
  `-SteamMode off` 只适用于已完成该本地 profile 原生初始化、且明确接受独立存档命名空间的显式诊断/隔离实验，
  不是生产训练 fallback；它不能替代原生 Continue/存档证据门禁，也不能被当作 Steam Cloud 修复。`off` 使用独立的本地 `user://default/1` profile，
  不继承 Steam profile 的 `ModSettings`/“已同意加载模组”标记；首次运行若出现
  `user has not yet seen the mods warning` 并跳过 `STS2AIAgent`、RitsuLib、Vivhite，API 不会启动。
  无人值守时不得自动点击原生确认框或把它误报成 Brain 故障；若该 profile 尚未完成原生同意，必须保持训练/直播
  fail-closed，待本地 profile 已完成原生同意后再验收 off 模式。
- **Steam 云存档空间闸门**：`auto/on` 冷启动必须先由 `Start-Agent.ps1` 只读解析 Steam 客户端的 `userdata` 所在卷并检查可用空间；默认低于 `1 GiB`（可在脚本规定范围内显式调整）时，在部署和启动游戏前 fail-closed。不得把游戏安装盘空间当作云存档空间，不得删除/移动 Steam 文件、修改云元数据或请求 UAC；用户释放空间并确认本地/远端存档一致后才能重试。`off` 的独立本地 profile 不绕过已有模组同意闸门；复用已运行进程不伪造新的冷启动检查。会话须记录检查结果与路径，失败不得创建“Stack ready”假象。
- **D→G 工作区迁移清理经验**：迁移验收必须核对新 G 根的 session 根目录、构建结果、部署三件套哈希及运行/嵌套仓状态；旧 D 根不会自动删除。清理只能针对用户明确指定的精确旧路径，先保全 `ignored` 文件、`knowledge/` 与复盘现场；删除失败但已核实为空的目录壳可记录后不阻塞主线。禁止广泛或未授权递归删除；精确路径在保全并核验后可按用户授权递归清理，且不得借此绕过 UAC/人工授权约束。
- **双轨并行执行（训练与复盘互不替代）**：用户同时要求“继续复盘/写报告/完善 `AGENTS.md`”和“启动游戏＋Brain 训练”时，必须在同一任务中并行推进两条独立轨道。A 轨持续记录证据、更新报告与规则；B 轨只用统一 `Start-Agent.ps1` 保持游戏、Brain、runner 和驾驶舱运行，并巡检健康状态与真实动作。A 轨等待或失败不得暂停 B 轨，B 轨阻塞或需要修复也不得让 A 轨停摆；每次汇报必须分别说明报告进度和训练进程/动作证据，不能把“报告已写完”或“Stack ready”冒充训练完成。训练巡检发现健康异常或连续状态无进展时，立即记录证据并进入修复/复核循环，不得静默等待、挂机或把“暂时无法安全恢复”写成成功。运行态文件以 `sts2-ascend/.runtime/`（由 `lifecycle.STACK_ROOT` 解析）为准，仓库根目录同名目录不是栈证据。
- **保持下播的训练模式**：用户明确要求下播时，先确认并保持本地直播姬为 `Idle`，只调用 `Start-Agent.ps1` 启动或复用游戏＋Brain 全栈；禁止调用 `Start-BilibiliLive.ps1`、禁止自动复播，也不得为了证明训练而触碰直播姬。训练栈可以在下播状态继续运行，但仍须以真实 `/state` 和已确认动作证明训练；若证据不足则保持失败关闭并继续诊断，不得伪造动作或擅自人工接管。
- 全栈驻留期间的人工接管只使用全局快捷键：`Ctrl+Alt+F9` 停止 Brain 发送操作并保留游戏与 runner，`Ctrl+Alt+F10` 只恢复动作发送。只要某局跨过一次 F9 人工接管边界，该局便永久标记为 `human_assisted=true`、`excluded_from_learning=true`；Brain 将其所属 Profile 的在线 Knowledge `stats` 回滚到局前持久基线，F10 后同一局的学习写入仍保持禁用，进程重启也不得解除。
  该局已有及随后产生的增量决策/战斗日志继续以 `in_progress=true` 保留为审计证据，但不走正常 `finalize_run`，不增加总局数或胜场，不进入平均/最高/近 20、该局终局的 `policy.json` / `progression.json` / `lessons.md` 演化、LLM 复盘或轮换配额。完整栈退出后快捷键监听不存在，冷启动仍走 `Start-Agent.ps1`。
- Windows 上 Luna 只使用 `scripts/Install-CodexCompat.ps1` 安装到用户缓存并经固定版本/SHA256 校验的兼容 Codex CLI；`Start-Agent.ps1` 冷启动会自动就绪该缓存。每次 Luna provider 启动前必须再次核对固定 SHA256，并通过本地无模型 `exec-server fs/readFile` 普通盘符读取兼容能力预检；失败时不得启动 provider 或消耗 token，必须保持 Luna 原批次亲和性且不新增冷却。
- `-Source auto`（默认）优先本地 fork、否则使用 release；`-Source fork` 强制 fork 构建；`-Source release` 强制官方包。自定义安装传 `-GameDir`，fork 构建可传 `-GodotExe`。
- “Stack ready”表示当前 session 的 brain 存活且 8080–8084 中某个 `/health` 已就绪。ASCEND-VISION 驾驶舱随 brain 启动，并由进程内监督器按心跳自愈；碎碎念在语音环境可用时由 brain 拉起，复盘 OpenCode 与复盘 speaker 仍按需出现。就绪等待超时只警告，runner 与驾驶舱监督器会继续在后台自愈，此时不要再启动第二套。
- 驾驶舱实时决策遥测是纯本地、确定性的 Python 标准库路径：只复用 Policy 本次已经计算出的观察、闸门、候选分数和结果，不重新评分，不调用 LLM、OpenCode、Minimax、OpenRouter 或任何网络服务，token 消耗为 0。遥测只写当前 session 的 `.runtime/live_dashboard.<SESSION_ID>.json`，采用有界队列和原子替换；异步复盘模型链本身仍可能消耗 token，二者不得混淆。
- ASCEND-VISION 必须在同一窗口使用状态驱动的稳定布局，不得按秒在整页 LIVE/REVIEW 间闪回：对局中显示决策主区和多行实时复盘流；`GAME_OVER` 显示趋势主区和复盘流；主菜单、等待或无新鲜决策时显示完整 REVIEW 视图；`--interactive` 可手动选择 LIVE/TREND/REVIEW。`knowledge/review_live.stream` 负责复盘文字展示，但不参与决策遥测、评分或动作选择。
- ASCEND-VISION 的资源根目录和 `knowledge/viewer.lock` 必须通过 `lifecycle.STACK_ROOT` 解析；复盘 clone、自检目录或备份副本不得按自身 `__file__` 建立独立 viewer 锁。复盘子进程必须继承 `STS2_ASCEND_DISABLE_VIEWER=1`。
- 楼层展示必须使用真实楼层口径 `floor_sum_raw` / `best_floor_raw`；历史 `floors_total` / `best_floor` 保留“真实楼层 + 胜利 50 分”的学习评分语义，不得拿来显示平均或最高楼层。
- 直播控制语义不变：开播仍先启动完整 sts2-ascend 栈并将杀戮尖塔2置于顶部，再通过本地哔哩哔哩直播姬开播；下播只操作直播姬，不停止任何服务、智能体或游戏。
- Bilibili 开播及开播后的恢复、修复或重载过程中，**仅对已证明真实游玩的会话**适用“直播最多允许中断两分钟”的预算；在该前提成立时，所有恢复操作必须围绕硬性死线安排，一旦直播中断，恢复 `Streaming` 立即成为最高优先级。若真实游玩证据丢失、失效或无法证明，立即调用 `Stop-BilibiliLive.ps1` 下播并确认 `Idle`，不得为了两分钟预算继续空播或自动复播。
- **禁止空播/挂机硬闸（2026-09-01 事故复盘）**：`Stack ready`、`/health=ready` 或直播姬进程存活都不等于正在游玩。开播或断流恢复前，必须同时确认游戏已进入真实对局（不得是 `MAIN_MENU`、`run_unknown` 或等待界面），并由 `/state` 的有效 `run`/`state_version`、驾驶舱 `connected` 心跳、近期 `applied` 动作回执及连续状态进展共同证明 Brain 正在实际操作；若 API 没有可继续的真实对局、Brain 处于终局/孤儿账本阻塞，或连续巡检没有新的已确认动作/状态进展，禁止开播和自动复播。用户明确要求保持下播时，只调用 `Start-Agent.ps1` 启动 brain＋游戏栈，禁止调用 `Start-BilibiliLive.ps1` 或任何自动复播入口。直播中一旦发现主菜单/等待界面、平台挂机提示或处罚弹窗、决策/动作停止，或无法证明仍在实际操作，必须立即调用 `Stop-BilibiliLive.ps1` 下播并确认状态为 `Idle`，不得为了守两分钟红线继续空播；修复并重新证明真实游玩前不得再次开播。该硬闸源于 2026-09-01 直播姬因游戏长期停在主菜单被平台判定挂机、切断本场直播并取消 7 天直播推荐资格的事故。
- **原生编号档位绑定**：生产训练固定使用 `brain/config.json` 的 `native_profile_id=1`。Agent `/state` 必须报告 `native_profile_id`；Brain 发现游戏当前不是目标档位时，不得绑定/统计该档位的 run，也不得从该档位采集孤儿负证据。只允许在稳定空 `MAIN_MENU` 通过 Agent 的 `switch_profile` 游戏线程动作调用原生 `SaveManager.SwitchProfileId`，重载 Prefs/Progress/主菜单后再判断 `continue_run`；缺少可信档位 ID、错档时已进入活动局或切换动作不可用均保持 fail-closed。不得直接改 `profile.save`、外部点档或跨档合并 run_id。
- **孤儿运行恢复证据门禁**：Brain 报告存在跨进程未闭合的旧 `run_id` 时，默认只有与该 `run_id` 匹配的原生 Continue/API 证据（例如 `/state` 非菜单且提供 `continue_run`，或可验证的原生存档/历史记录）才能解除阻塞。若已证明原生存档不可恢复，唯一允许的窄例外是版本化 `no_native_save_no_continue` 负证据：同一 GUID session 内持有生命周期锁完成至少两次有序 `GET /state` 与 `/actions/available` 交叉采样（明确 `MAIN_MENU`、`run_unknown`、`run=null`、无 `continue_run`、数值 `state_version`），并对同一 `profile1/saves` 根下的 `current_run.save`、`current_run.save.backup`、`history`、`.stmp` 四类原生对象完成无读错且无匹配 run 的探针；随后必须经过统一 `Stop-Agent.ps1` 的同 session sentinel，再由一次性 `release_orphan_run.py --apply` 事务写入 orphan 审计行。该例外只解除精确 active slot、标记 `orphaned/excluded_from_learning`，绝不伪造终局、统计、学习或轮换配额；证据哈希/绑定、路径类别或 Stop sentinel 任一不符都保持阻塞。`run_unknown`、`MAIN_MENU`、进程存活、dashboard 心跳、日志、缓存或零字节 `.stmp` 单独都不是恢复证据；不得手改 `knowledge`、清除 active-run/轮换账、复制或改名临时文件、从外部注入动作，亦不得为“继续训练”强行开新局。证据缺失时保持全栈可观测地运行并修复/等待机制产生权威证据；允许进程继续驻留，但 Brain 动作发送和直播必须保持失败关闭。
- **HP 支付语义复盘规则**：`CreatureCmd.Damage` 返回的 `DamageResult.UnblockedDamage` 是经过原生减伤/阻挡后的实际掉血，不是请求值；Tungsten Rod 或 Buffer 将其降为 0 时，只要付款者仍存活且结果集合包含付款者，不能把支付误判为失败。只有没有付款者结果或付款者死亡才阻止后续卡牌效果；新增生命支付逻辑必须保留原生 `ValueProp`，并覆盖 1 点、多点、零实际掉血和真实阻止的回归测试。
- **Workshop 发布物料同步**：每次发布必须同步提升 `Vivhite.json`/`workshop-item.json` 版本、更新 `workshop/description.bbcode` 的中英文 Changelog，并从仓库已验收的本地素材重新生成 `workshop/preview.jpg`；旧预览图及 SHA-256 必须按版本归档。发布前必须通过描述/manifest/预览元数据一致性门禁和完整三件套/PCK 验收，不能用 `-SkipPreview` 绕过陈旧图片检查；Steam `SubmitItemUpdate` 的 change note 必须来自本次发布记录。上传只可复用已登录 Steam 客户端的仓库脚本，不得启动需要人工授权的 GUI/UAC；回执与远端只读元数据确认完成后才能宣称已发布。
- 窗口层巡检必须区分两条不变量：ASCEND-VISION 自身约 500ms 的无激活置顶永远运行；游戏窗口巡检仅在本地直播姬实际为 `Streaming` 时每 60 秒运行，按当前 session 的完整 `game_exe` 精确定位，先无激活恢复游戏 TOPMOST、再恢复 viewer。非 Streaming 或任何状态/窗口读取失败都不得触碰游戏；该路径只允许本地标准库/Win32，不调用 LLM 或网络，token 消耗为 0。
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
- **同一职责边界明确适用于 Luna。** 维护 AI 不得逐行审计、手工修补、代写或代为合并 Luna 的策略/复盘代码；Luna 必须自行操作隔离仓、自行复核 diff、解决冲突、运行自检、修复失败并完成合并。Luna 产物失败时，维护 AI 只修运行器、提示、证据、反馈、自检、队列、提交与自愈机制，并把完整失败证据重新交给 Luna 闭环。
- 失败合入在机制问题修复后，必须由维护 AI 重新调用 GLM，让 GLM 自己重新审核失败批次、补合有效成果、解决与当前主树的冲突、运行自检并完成提交；维护 AI 负责提供完整失败现场、可读任务和验收/重试通道，不得默认亲自代做该批具体补合。只有 GLM 重试机制本身仍有已证明故障时，维护 AI 才修该机制并再次调用 GLM。

## 工作流程规则

### 0. 必要性与成本优先（最高优先级）

- **如果不能用用户明确需求、当前真实故障、可复现测试、运行日志或现有数据证明必要性，严禁花费用户的模型额度和时间研究、设计或实现额外安全边界。** 不得在安全相关领域因为“理论上可能”“更完美”“纵深防御”而自行扩张任务；本条不限制正常的功能优化、故障修复、架构改进和主动推进。
- 提议任何新的门禁、限制、威胁模型或防御性机制前，必须先给出简短的必要性证据与预期收益；证据不足就立即停止该方向，回到用户要求的功能、稳定性和运营结果。
- 不得把假设性的 symlink、gitlink、prompt 篡改、路径逃逸等场景自动升级为当前任务；只有已经发生、能复现、用户明确要求，或存在迫近且不可逆的数据损失/凭据泄露风险时才处理。
- 本项目追求**相对安全、可观测、可记录、可回退**，不追求耗费大量额度证明“绝对安全”。优先采用最小有效修复并及时提交；不得以安全之名重新收紧复盘模型的文件范围或恢复全仓门禁。

### 0.1 独立部件采用一部件一子代理

- 任务能拆成多个互不依赖的语义部件时，必须为**每个独立部件单独创建一个子代理**；不得仅为减少代理数量而把多个独立部件捆给同一个子代理。
- 并发数量应尽量用满当前会话允许的子代理槽位。部件数超过并发上限时，为剩余部件逐个排队；任一槽位释放后立即启动下一个“一部件一代理”任务。
- 同一部件内部的提示词调整与重复生成属于连续迭代，仍由该部件的同一子代理负责，不得把同一部件的多次尝试并行发出，以免浪费额度并失去基于上一轮结果的反馈。
- 主代理负责预先划分互不冲突的输出路径/编号区间，并统一完成跨部件视觉一致性审查、整合、验证、文档、提交和推送；子代理不得同时修改共享索引、共享清单或公共文档。
- 如果运行时实际并发上限低于项目配置，以运行时可用槽位为准继续排队，不得因此退化为一个子代理承包多个独立部件。

### 0.2 子进程/子任务遇到 429 时优先复用原任务

- 服务端明确允许重试的 429（限流或暂时配额耗尽）是**可恢复的运输层中断**，不是语义失败、代码失败或任务完成；硬配额耗尽、账户停用或明确永久拒绝另行判定。任何情况下不得因此丢弃该子任务已有的工作树、输出、日志和上下文。
- 检出可重试 429 后主代理应直接安排恢复，不向用户等待确认：首选使用同一 canonical task/agent 身份继续工作，保留原 prompt、任务边界、输出路径、attempt/run ID 和模型亲和性，通过 `followup_task`/等价恢复入口续接；不得为同一部件并行创建重复代理或把任务偷偷转给另一模型。
- 恢复前读取并尊重服务端 `Retry-After`（若有）；没有该字段时使用有上限的指数退避并加入抖动。退避期间只保留一个恢复调度，不得忙等、并发重试或重复计费。恢复尝试必须记录时间、原因、等待值和原任务身份。
- 429 恢复必须是幂等的：先检查原子进程是否仍存活、是否已有部分结果和锁，再决定继续、从最近 checkpoint 续写或重新启动同一任务。禁止覆盖已产生的原始文件；重跑只能使用新的 attempt 文件名并链接到原任务。
- 原任务仍可复用时，不得把可重试 429 标为永久 cooldown、`blocked` 或“无有效成果”。首次中断即保全 partial/日志；达到有界恢复次数、服务端明确拒绝继续，或原任务身份/证据已不可恢复时，才停止主动恢复并按普通失败流程处理；必要时新代理必须显式记录 `replaces_task`/lineage，而不是隐式重复。
- 429 不应触发无关组件的停止、模型链跳级或工作范围扩张。游戏/录制/直播等独立轨道继续遵循各自生命周期规则；恢复失败时也要保持可观测、可回退和失败关闭，不伪造“已完成”。

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
