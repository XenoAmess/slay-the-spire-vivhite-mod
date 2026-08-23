# 2026-08-24 水晶球占卜屏（CRYSTAL_SPHERE）卡死排查与上游完整支持

## 问题现象

自动游玩停在占卜（水晶球）界面不动：mod 上报 `screen=UNKNOWN`，
available_actions 只剩 `save_and_quit`/`discard_potion`，大脑无可用动作僵死。

## 根因定位（关键方法论）

1. **游戏日志直接给出答案**：mod 对未识别屏幕会打警告——
   `%APPDATA%\SlayTheSpire2\logs\godot.log` 里反复出现
   `Unhandled screen type: MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere.NCrystalSphereScreen`。
   结论：**是上游 mod 问题，不是大脑问题**。
2. **逆向游戏程序集搞清真实机制**（不要猜）：
   - 用 `System.Reflection.MetadataLoadContext` 枚举类型成员（不加载依赖、不执行）；
   - 用 **ICSharpCode.Decompiler**（NuGet）直接反编译 `sts2.dll` 里目标类为可读 C#——
     比读 IL 高效得多，是理解游戏逻辑的首选工具。
   - 游戏自带 `AutoSlay.Handlers.Screens.*` 系列处理器是"官方自动玩法"参照系，
     照它设计 mod API 最不容易跑偏。

## 占卜小游戏机制（反编译实证）

- 11×11 雾格棋盘，四角区域预清开；固定 14 个物品：1 遗物(4×4)、3 药水、3 卡牌奖励、
  **1 诅咒(2×2)**、7 金币堆。物品占多格，全格清开即揭示，**结束时全部发放（含诅咒）**。
- 每次点格固定消耗 1 次占卜；大占卜（默认）清 3×3，小占卜清 1 格，费用相同。
- `IsFinished = 占卜次数==0`——**必须用完所有次数**才能 proceed，没有提前离开。
- 安全空耗：点已清开的格子，次数照扣但不揭任何雾。
- 游戏自带 AutoSlay 是**随机盲点**（会踩诅咒）；mod 暴露物品坐标后大脑可以完美避诅咒。

## Mod 侧最终方案（上游 PR #48）

- `NCrystalSphereScreen => "CRYSTAL_SPHERE"` 屏幕映射。
- `crystal_sphere` 状态负载：剩余次数/当前工具/棋盘/隐藏格/物品（种类、is_good、占位、已揭示）。
  **以格子引用为准统计物品占位**——放置失败的物品不占格、永不揭示，直接跳过。
- 动作 `crystal_set_tool`、`crystal_clear_cell(x,y,tool?)`（tool 可选原子切换），
  校验坐标与阶段，等待"下一次占卜就绪 / 奖励子屏接管 / proceed 可用"三种落定态。
- `proceed` 由既有通用 NProceedButton 查找自动暴露，无需特判。
- 只需反射屏幕的私有 `_entity` 字段；minigame 的 `cells`/`Items`/`CellClicked` 全是公开 API。

### 踩坑：两套 available_actions

mod 里 `BuildAvailableActions`（ActionDescriptor 列表，供 MCP tools）和
`BuildAvailableActionNames`（状态负载里的字符串数组）是**两个方法**——
只改一个会出现"payload 有数据但没动作"的半成品状态。新动作两边都要加。

## 大脑侧策略（policy._crystal_sphere）

贪心：每次点击最大化"新清开的好物格数"（大占卜优先），
**硬约束：本次点击不得覆盖任何坏物品的全部剩余隐藏格**（防揭示诅咒）；
无利可图时小占卜点已清开的格子空耗剩余次数。实测 3 次点击揭示大片好物、
绕开诅咒，经奖励屏/选卡屏回地图，全链路打通。

## 部署与运维教训

- fork 构建的 dll 直接拷贝覆盖 `mods/STS2AIAgent.dll` 即可（pck/mod_id.json 不变）；
  但 `Deploy-Mod.ps1` 会下载上游 release 覆盖回来——**PR 未合并前重新部署后需再拷一次**。
- 换 dll 流程：`save_and_quit`（API）→ 杀游戏 → 拷 dll → `launch_vulkan.bat` 重启；
  StS2 会继续到原事件（占卜局重开一局新的占卜，已揭示奖励清零，属正常）。
- 杀大脑前查 `review_active.flag`：本次发现复盘已 LIVE-END 但 flag 残留 49 分钟（陈旧），
  且有一个 20 小时的孤儿 opencode 复盘进程——清理后再重启大脑。
- 杀 opencode 进程要看命令行：`opencode serve`/裸 `opencode` 可能是用户会话，别误杀。
- 大脑的 autogit 会把工作区未提交的大脑代码改动一起卷进"存档"提交——
  改完 brain/ 想单独成 commit 的话要么手快，要么接受并入存档。

## 相关链接

- 上游 PR：<https://github.com/CharTyr/STS2-Agent/pull/48>
- fork 分支：`XenoAmess/STS2-Agent` 的 `feat/crystal-sphere-screen`

## 追加：同日第二起占卜屏卡死（大脑侧契约缺口）

mod 修好一周后（实际数小时）占卜屏再次卡死——本次 mod/屏幕识别/动作全部正常，
根因在大脑侧：**`Sts2Client.act()` 只接受 card_index/target_index/option_index，
`_crystal_sphere` 策略传 `x/y/tool` 直接 TypeError**，动作每 tick 失败形成死循环
（决策正常、执行炸掉，日志里 `决策 占卜：big点(5,6)` + `act() got an unexpected
keyword argument 'x'` 成对出现就是判据）。

**教训：mod API 新增动作参数时，大脑 HTTP 客户端必须同步加字段**——
这是一条跨仓库（fork mod ↔ 工作区大脑）的隐性契约，两边任何一边缺位都表现为
"屏幕识别正常但无限僵死"。修复：`client.act()` 增加 `x/y/tool` 关键字参数
（6520d95 + autogit 存档）。

顺带根治了同日三次咬人的 `review_active.flag` 陈旧 bug：run_review 的
超时/exit≠0/异常路径在 finally 里补 `set_review_active(False)`（原先这些
提前 return 走不到后处理段的清理）。
