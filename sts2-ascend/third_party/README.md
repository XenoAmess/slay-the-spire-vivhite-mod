# third_party — 上游依赖说明

## STS2-Agent（上游 CharTyr/STS2-Agent，AGPL-3.0-only）

- **上游**：https://github.com/CharTyr/STS2-Agent
- **我方 fork**：https://github.com/XenoAmess/STS2-Agent（本地克隆在 `third_party/STS2-Agent/`，已 gitignore）
- **基线版本**：v0.9.0（`upstream/main` HEAD = `ca2a788`，已包含合并的 PR #46/#47）

### 维护工作流（重要）

以我 fork 的 `main` 为我们自己的长期维护分支：

1. 发现问题 → 在 **fork 的 `main`** 上修改 → 真机验证 → 推送 `origin main`。
2. 确认闭环后 → 从该修复**单独拉 `fix/*` 分支** → `gh pr create` 提给上游 `CharTyr/STS2-Agent`。
3. 上游合并后，下次同步 `upstream/main` 时自然回落到官方实现。

本地克隆的 remote：`origin` = 我方 fork，`upstream` = 官方仓库。

### 当前持有的修复

**fix/potion-aoe-target-resolution**（commit `bf61078`，已在 fork `main`）：

- 上游 PR：https://github.com/CharTyr/STS2-Agent/pull/46

**fix/unlock-screen-action**（初始 commit `04e2e75`，确认按钮补丁 `985f8c3`，已在 fork `main`）：

- 初始 UNLOCK 支持（已合并）：https://github.com/CharTyr/STS2-Agent/pull/47
- private 基类确认按钮后续修复（新 PR，commit `71fa12f`）：
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
  基类字段/属性测试；Release 构建 0 警告 0 错误，38 项 C# 测试与 Python selfcheck 通过。
- 大脑侧兜底（不依赖 mod 正常暴露动作）：UNKNOWN 或已识别 UNLOCK 屏滞留 12 tick 后，
  点击底部确认区；UNLOCK 日志同步输出类型、can_confirm 和 actions，避免再次静默空转。
- 问题：`use_potion` 对 AoE/随机目标药水（如爆炸药瓶 EXPLOSIVE_AMPOULE）永远 pending——
  `GameActionService.ResolvePotionTarget` 的 switch 未覆盖 `AllEnemies/AllAllies/RandomEnemy`，
  落入默认分支返回 `potion.Owner.Creature`，游戏静默丢弃非法目标。
- 修复：这三类返回 `null`（与 `TargetedNoCreature` 一致，由游戏内部解析目标）。
- 验证：真机 `use_potion` 对 AoE 药水返回 completed、敌方全体扣血；Release 构建 0 警告；全部单元测试通过。
- 历史补丁文件：`STS2-Agent-v0.9.0-aoe-potion-fix.patch`（与 fork main 内容一致，留档；
  注意其中首个 hunk 有 BOM 乱码属已知瑕疵，正式实现以 fork 为准）。

### 如何复现部署构建（从 fork main 构建并部署到游戏）

```powershell
cd third_party/STS2-Agent
git checkout main   # 我方维护分支
$env:DOTNET_ROOT = "C:\Users\xenoa\AppData\Local\Microsoft\dotnet"   # 本机 SDK 位置
$env:PATH = "$env:DOTNET_ROOT;$env:PATH"
$env:STS2_DATA_DIR = "G:\SteamLibrary\steamapps\common\Slay the Spire 2\data_sts2_windows_x86_64"
.\scripts\build-mod.ps1 -Configuration Release -GameRoot "G:\SteamLibrary\steamapps\common\Slay the Spire 2" -GodotExe "<Godot 4.5.1 mono 路径>"
```

- 注意：`-GameRoot` 只管部署；csproj 的程序集引用路径由环境变量 `STS2_DATA_DIR` 提供
- 官方 release zip 仍可由 `scripts/Deploy-Mod.ps1` 下载到 `dist/`（未打补丁的原版，仅作对照）
- 若上游合并了 PR 并发布新 release，可切回官方 release
