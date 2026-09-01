# Vivhite.Tests — 角色 Mod 接受测试

`Vivhite.Tests/` 是白绮 Mod 的离线接受测试项目。它把 `Vivhite/VivhiteCode/` 的生产 C# 源码编译进一个独立的 .NET 9 可执行程序，再通过反射、源码快照和资源契约检查注册内容；测试不会启动游戏、部署 Mod、导出 PCK 或写入 Steam 存档。

## 测试覆盖

测试入口是 [`Program.cs`](Program.cs)，当前覆盖以下几类不变量：

- 61 张卡牌的稳定 ID、稀有度分布（3/18/24/16）、初始卡组和废弃占位类排除；
- 生命支付、Drain、Dimension Up、謦欬/汲取、遗物触发和死亡事件顺序；
- 中英文本地化、关键词、Power 文案与图标；
- 白绮独占的 V3 五页皮肤、魔法战斗场景、卡牌拖尾和音频；
- 61 张卡图、Power/遗物/UI/VFX 的 92 项运行时位图清单；
- PCK 三件套部署契约，避免 DLL、JSON、PCK 来自不同构建批次。

测试按职责放在 [`Acceptance/`](Acceptance/)、[`Mechanics/`](Mechanics/) 和 [`Relics/`](Relics/)；共享的仓库快照与断言工具也在项目内。`bin/`、`obj/` 是构建产物，已被 Git 忽略。

## 前置条件

项目需要本机游戏数据目录中的 `sts2.dll`、`Steamworks.NET.dll` 等程序集。推荐先在 `Vivhite/` 创建被忽略的 `local.props`（见 [`Vivhite/README.md`](../Vivhite/README.md)）；若未配置，项目会尝试使用默认 Steam 安装路径。

首次运行允许还原 NuGet 包：

```powershell
dotnet restore .\Vivhite.Tests\Vivhite.Tests.csproj
```

## 运行

从仓库根目录执行：

```powershell
# Debug/默认配置（首次运行不要加 --no-restore）
dotnet run --project .\Vivhite.Tests\Vivhite.Tests.csproj

# 已还原后的快速回归
dotnet run --project .\Vivhite.Tests\Vivhite.Tests.csproj --no-restore

# 发布前 Release 验收
dotnet run --project .\Vivhite.Tests\Vivhite.Tests.csproj -c Release --no-restore
```

成功时末行会报告 `N passed, 0 failed`。测试数量会随契约演进变化，README 不把数量当作 API；发布记录会保存当次完整输出。单个测试没有统一的过滤参数，需要临时调试时可在 `Program.cs` 中使用本地分支，不要把调试删改带入提交。

## 与其他门禁的关系

接受测试验证 C# 行为和静态资源契约，不能替代 Godot/PCK 挂载验证或真机验收。推荐发布顺序是：

1. `dotnet run --project Vivhite.Tests ...`；
2. [`tools/test/Verify-VivhitePck.ps1`](../tools/test/Verify-VivhitePck.ps1) 对同批 PCK 做只读挂载检查；
3. 按 [`Vivhite/README.md`](../Vivhite/README.md) 的 Vulkan 真机清单确认选人、战斗和终局流程。

测试失败时保留完整异常和 Git diff，先修复生产契约，再重跑全套；不要手改 `knowledge/` 或把测试 fixture 当运行时素材。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `sts2.dll` not found | 检查 `Vivhite/local.props` 的 `Sts2DataDir`，确认指向游戏 `data_sts2_windows_x86_64`。 |
| NuGet/SDK 找不到 | 使用 .NET 9 SDK，并确保 `DOTNET_ROOT`/PATH 指向本机 SDK；不要复制游戏 DLL 到仓库。 |
| 测试通过但游戏缺资源 | 继续运行 PCK 门禁；接受测试不会读取最终 PCK。 |
| 出现 `bin/`、`obj/` 变更 | 这些目录是本地产物，确认未被强制添加后即可清理，不要提交。 |

相关总览见仓库根 [`README.md`](../README.md)。
