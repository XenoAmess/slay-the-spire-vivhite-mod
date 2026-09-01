# 2026-09-01 工坊评论核对：Vulkan 与 Open Beta

## 范围

核对条目：<https://steamcommunity.com/sharedfiles/filedetails/?id=3793741497>（页面抓取日期：
2026-09-01，匿名 HTTP 200）。
本记录只处理两条与启动环境有关的评论：

- “vulkan 大概率不是必须的，只是我的测评机是十年前的 1060 古董罢了”；
- “另外我们只在 openbeta 上进行了测试”。

页面在核对时显示共 4 条留言；相关留言的 Steam comment ID 和页面时间如下（页面显示为
PDT，未将显示时区换算后再当作原始证据）：

| comment ID | 页面时间 | 内容摘要 |
|---:|---|---|
| `581680955259118895` | 2026-08-31 21:14:01 PDT | 只在 `openbeta` 测试 |
| `581680955259113670` | 2026-08-31 19:39:43 PDT | Vulkan 大概率不是必须，测评机为 GTX 1060 |

## 可复核证据

### 本机分支和版本

截至本次核对，本机 `G:\SteamLibrary\steamapps\appmanifest_2868840.acf` 的
`UserConfig.BetaKey` 与 `MountedConfig.BetaKey` 都是 `public-beta`。游戏目录的
`release_info.json` 同时报告：

```text
version = v0.111.0
branch  = v0.111.0
```

因此“只在 openbeta 测试”是作者的环境披露，且与本机 `public-beta` 证据一致；本机材料
不能独立验证“只”在该分支测试，也不能推导出 public/default 分支或其他游戏版本已经通过验证。

### 渲染后端

游戏目录同时提供以下官方包装脚本：

```text
launch_vulkan.bat  -> --rendering-driver vulkan
launch_opengl.bat  -> --rendering-driver opengl3
launch_d3d12.bat   -> --rendering-driver d3d12
```

当前 `sts2-ascend` 统一入口仍默认调用 `launch_vulkan.bat`，现有游戏日志首行确认：

```text
Vulkan 1.4.312 - Forward+ - Using Device #0: NVIDIA - NVIDIA GeForce GTX 1060
```

仓库源码检查未发现 Vivhite C#/GDScript 直接调用 Vulkan 专属 API；但正式 Spine、
卡牌轨迹、角色转场和其他 VFX 的实机验收记录均是 Windows Vulkan。当前没有同等的
OpenGL3 或 D3D12 运行时验收记录，不能把“游戏有替代后端”扩大成“本 Mod 已兼容替代后端”。

Steam 官方讨论也把 `--rendering-driver opengl3` 作为 Vulkan 启动失败时的排障选项，
但同一讨论中有用户报告 OpenGL 下卡牌不渲染、文字异常并在移动/攻击时崩溃：
<https://steamcommunity.com/app/2868840/discussions/0/798968342700412657/>。
这是游戏后端的上下文证据，不是 Vivhite 的通过证据。

## 结论和改动

1. Vulkan 评论为**部分正确**：Vulkan 不是游戏唯一的渲染入口，但截至目前它仍是
   Vivhite 唯一有完整实机证据的默认/推荐路径。不能仅凭 GTX 1060 或官方包装脚本
   宣称 OpenGL3/D3D12 已获支持。
2. Open Beta 评论是**与本机证据一致的作者披露**：发布材料现在明确写出验证范围为
   Steam `public-beta` + STS2 `v0.111.0`；没有把“只在该分支测试”扩展成独立事实证明。
3. README 和工坊源描述不再把 Vulkan 写成所有硬件上的绝对要求，而改为：
   “Vulkan 已验证；遇到启动问题可尝试游戏提供的 OpenGL3 排障入口；OpenGL3/D3D12
   尚未完成 Mod 专项验收，不作兼容承诺”。
4. `Start-Agent.ps1` 和 Brain 配置仍保持 Vulkan 默认值，且不自动切换后端。这样可避免
   未经验证的替代后端把训练栈带入不可观测或卡牌/VFX 损坏状态；若要新增后端支持，
   必须另行完成同一套加载、Spine、卡牌、VFX 和 API 真机验收。

## 后续门禁

若未来要正式宣称 OpenGL3 或 D3D12 兼容，应在独立测试会话中记录完整后端字符串、
游戏版本/分支、Mod 三件套哈希、依赖加载、角色选择、至少一场战斗、卡牌显示、Spine
动画、VFX 和 API 动作回执，并与 Vulkan 证据分开归档。测试失败时只保留失败证据，
不得把排障启动成功等同于 Mod 兼容通过。
