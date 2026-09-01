# third_party — 上游依赖说明

## STS2-Agent（上游 CharTyr/STS2-Agent，AGPL-3.0-only）

- **上游**：https://github.com/CharTyr/STS2-Agent
- **我方 fork**：https://github.com/XenoAmess/STS2-Agent（本地克隆在 `third_party/STS2-Agent/`，已 gitignore）
- **兼容基线**：v0.9.1（游戏 v0.111.0；已验证的 PR #46～#49 修复）。
  `third_party/STS2-Agent/` 是被 `.gitignore` 忽略的本地 checkout，分支和 HEAD 会随维护工作变化，
  不能把某个历史 SHA 当作当前部署事实。2026-09-01 审计时该 checkout 位于
  `integration/native-progression-event-localization`，HEAD 为 `c9c2101`（事件变量本地化修复），
  而不是 `main`；请以以下只读命令获取当前值：

  ```powershell
  git -C .\sts2-ascend\third_party\STS2-Agent status -sb
  git -C .\sts2-ascend\third_party\STS2-Agent rev-parse --short HEAD
  git -C .\sts2-ascend\third_party\STS2-Agent log -1 --oneline
  ```

### 维护工作流（重要）

若要把 fork 的 `main` 作为干净上游基线，先确认远端和工作树，再按团队约定同步；当前 checkout
若处于整合/功能分支，`Deploy-Mod.ps1 -Source auto` 会按**当前 checkout**构建，不能把它描述成
官方 release。建议在部署前记录 branch、HEAD、dirty 状态和构建日志：

1. 先同步 `main`，再从最新官方基线拉独立 `fix/*` 或 `feat/*` 分支。
2. 在独立分支修改、真机验证并推送，然后用 `gh pr create` 提给上游 `CharTyr/STS2-Agent`。
3. PR 合并前仅在该分支部署验证，不把它提前合入 fork `main`。
4. 上游合并后再次同步 `main`；如历史已因临时整合而分叉，先保存远端备份，再用带精确旧 SHA
   的 `--force-with-lease` 对齐，禁止无条件 force push。

本地克隆的 remote：`origin` = 我方 fork，`upstream` = 官方仓库。

### v0.9.1 已上游的修复

**fix/potion-aoe-target-resolution**（commit `bf61078`，已合入上游 v0.9.1）：

- 上游 PR：https://github.com/CharTyr/STS2-Agent/pull/46

**fix/unlock-screen-action**（初始 commit `04e2e75`，确认按钮后续修复已合入上游 v0.9.1）：

- 初始 UNLOCK 支持（已合并）：https://github.com/CharTyr/STS2-Agent/pull/47
- private 基类确认按钮后续修复（已合并，最终 PR head `925fb3a`）：
  https://github.com/CharTyr/STS2-Agent/pull/49
- 问题：赛后/里程碑的整屏解锁展示（"解锁遗物！"等）不被路由——`/state` 返回 `UNKNOWN` 且
  `available_actions` 为空，自动游玩在该屏永久卡死。
- 修复：`NUnlockScreen => "UNLOCK"` 路由 + `unlock` payload（类型/解锁项名称/can_confirm）+
  新动作 `confirm_unlock`（点击 `_unlockConfirmButton` 关屏）。
- 2026-08-26 真机首次复现后的二次修复：运行时屏幕是派生类 `NUnlockRelicsScreen`，而
  `_unlockConfirmButton` 是基类 `NUnlockScreen` 的 private 字段；旧反射只查运行时类型，
  所以能读到派生类 `_relics`，却永远读不到确认按钮。现在沿 `BaseType` 逐层查找，另以
  `NUnlockConfirmButton` 节点树查询兜底，并节流记录声明类型、节点路径、visible/enabled。
- 验证：现场 `/state`、游戏 `sts2.xml` 元数据和 HTTP 503 三方闭环；新增派生实例读取 private
  基类字段/属性测试；v0.9.1 Release 构建 0 警告 0 错误，48 项 C# 测试与 29 项 MCP Python 测试通过。
- 大脑侧兜底（不依赖 mod 正常暴露动作）：UNKNOWN 或已识别 UNLOCK 屏滞留 12 tick 后，
  点击底部确认区；UNLOCK 日志同步输出类型、can_confirm 和 actions，避免再次静默空转。
- 问题：`use_potion` 对 AoE/随机目标药水（如爆炸药瓶 EXPLOSIVE_AMPOULE）永远 pending——
  `GameActionService.ResolvePotionTarget` 的 switch 未覆盖 `AllEnemies/AllAllies/RandomEnemy`，
  落入默认分支返回 `potion.Owner.Creature`，游戏静默丢弃非法目标。
- 修复：这三类返回 `null`（与 `TargetedNoCreature` 一致，由游戏内部解析目标）。
- 验证：真机 `use_potion` 对 AoE 药水返回 completed、敌方全体扣血；Release 构建 0 警告；全部单元测试通过。
- 历史补丁文件：`STS2-Agent-v0.9.0-aoe-potion-fix.patch`（与 fork main 内容一致，留档；
  注意其中首个 hunk 有 BOM 乱码属已知瑕疵，正式实现以 fork 为准）。

**feat/crystal-sphere-screen**（最终 PR head `78c56bf`，已合入上游 v0.9.1）：

- 上游 PR：https://github.com/CharTyr/STS2-Agent/pull/48

### 如何复现部署构建（从已审计 checkout 构建并部署到游戏）

```powershell
cd sts2-ascend/third_party/STS2-Agent
# 仅在你明确要验证 main 且确认没有未提交工作时执行：
# git switch main
$env:DOTNET_ROOT = "C:\Users\xenoa\AppData\Local\Microsoft\dotnet"   # 本机 SDK 位置
$env:PATH = "$env:DOTNET_ROOT;$env:PATH"
$env:STS2_DATA_DIR = "G:\SteamLibrary\steamapps\common\Slay the Spire 2\data_sts2_windows_x86_64"
.\scripts\build-mod.ps1 -Configuration Release -GameRoot "G:\SteamLibrary\steamapps\common\Slay the Spire 2" -GodotExe "<Godot 4.5.1 mono 路径>"
```

- 注意：`-GameRoot` 只管部署；csproj 的程序集引用路径由环境变量 `STS2_DATA_DIR` 提供
- 官方 v0.9.1 release zip 可由仓库根的 `sts2-ascend/scripts/Deploy-Mod.ps1 -Source release`
  下载到 `dist/`；它不包含本地整合分支的额外修复。只有显式 `-Source release` 才会强制使用该
  未补丁包；默认 `auto` 优先本地 fork。部署结果应在发布记录中写明 source、branch 和 SHA。
