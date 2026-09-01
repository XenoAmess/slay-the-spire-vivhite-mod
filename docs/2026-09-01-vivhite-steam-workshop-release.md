# 2026-09-01 白绮 Steam 创意工坊发布

## 发布结果

- Steam App ID：`2868840`（Slay the Spire 2）。
- Workshop item ID：`3793741497`。
- 公开地址：<https://steamcommunity.com/sharedfiles/filedetails/?id=3793741497>。
- 可见性：`public`。
- 必须依赖：RitsuLib，Workshop item ID `3747602295`，Mod 版本契约 `0.5.14`。
- 发布版本：Vivhite `0.2.0`，最低游戏版本 `0.111.0`；本机发布验收使用 Steam
  `public-beta` 分支。

条目先创建并完成首轮上传；随后主线程的 64 项发布验收发现中文“孤高冠冕”说明缺少“向上取整”，完成最小修正并复跑为 `64/64 PASS`。发布流程立即从修正后的当前工作树重新隔离构建，并覆盖更新同一个 item，没有创建重复条目。最终 Steam 回执时间为 `2026-09-01T01:40:57.7917231Z`，状态为 `published`，上传、依赖与可见性均完成，且不要求额外接受 Workshop 协议。

## 首发发布包证据（评论修复前）

本节记录的是首发上传包，不包含本次评论核验后新增的 Tungsten Rod 生命支付修复、
Event Loop `Exhaust` 修复或随后更新的源描述；公开 Workshop 当前仍对应这份旧包。
本地修复后的三件套已重新构建并部署到测试机，但本次没有重新上传 Steam。

发布脚本把三件套构建到忽略目录 `workshop/.runtime/content/Vivhite/`，没有覆盖游戏当前的 `mods/Vivhite`。最终目录只有以下三份文件，总计 `96,090,342` bytes：

| 文件 | bytes | SHA256 |
| --- | ---: | --- |
| `Vivhite.dll` | 226,304 | `2D28A6C639E3DB0C9F56ADA33B0D5ED85C5D537F04C09F82D512ABB3D8C28E98` |
| `Vivhite.json` | 434 | `28E888CC149E13EBCFA683DEE139FF6527F87C6B553AEF71527557EC9E29BF71` |
| `Vivhite.pck` | 95,863,604 | `212C71463EEFB37652C1E68852774805B94A716FF91A533A78F50C742806BBD6` |

最终 PCK 门禁通过：323 个条目，Godot 4.5.1、pack format 3；运行时美术 `92/92`；卡牌 `61/61`、Power `19/19`、冠冕 `2/2`、能量 UI `7/7`、VFX `3/3`；英文与简中各 `314/314` localization key 且六份源文件与包内文件逐字节一致；NOPE/generic fallback 为 0；门禁后 PCK SHA256 保持不变。

预检、回执和日志分别保存在本地忽略的 `workshop/.runtime/preflight.json`、`publish-result.json` 与 `upload.log`。最终预检记录的 Git HEAD 为 `7e920f0a208bbbde4ab39798a28fe237df843ec7`；上述中文文案修正由主线程维护并另行提交，本提交不夹带该文件。

## 预览图与公开物料

`workshop/preview.jpg` 是 1024×1024、170,354 bytes 的 JPEG，SHA256 为 `20BC597F5B63CD40560CCE0358A2928A91666D068FAA71FA272B84A9A071260C`，低于 Steam 1 MB 限制。本次没有调用 AI 生图。

预览图由仓库内已经验收的白绮素材确定性合成：

- 选人英雄母源 `assets/vivhite-ironclad/custom/character_select/sources/vivhite-character-select-hero-master-v1.png`，SHA256 `2CABDE503DDAE0780F5530FED0FFB8C2910C3F8289A7DFDAAEC93261E6AC781A`；
- 选人转场 `Vivhite/Vivhite/skins/ironclad/transitions/vivhite_character_select_transition.png`，SHA256 `82015B8F5AA1C6DD9FA57B9D757E009F35FCA67D8818B269AF4AB6F49FF252D2`。

仓库当前源描述为中英双语，明确列出 61 张卡牌、三套主要构筑、初始遗物、Vulkan 验证基线、
RitsuLib 依赖和安装步骤；这不是对首发上传说明的追溯性描述。匿名请求公开页面返回 HTTP 200，
并确认公开订阅入口、标题、中英文说明、English / Simplified Chinese 标签、RitsuLib Required Item
和预览图元数据均存在。

## 工坊评论复核后的说明修订

发布后收到的评论指出“Vulkan 大概率不是必须”以及“只在 openbeta 测试”。本机证据确认
游戏目录同时提供 OpenGL3/D3D12 包装脚本，且 `appmanifest_2868840.acf` 的
`BetaKey` 为 `public-beta`；不过 Vivhite 目前只有 Vulkan 的完整实机验收。仓库源描述已
改为“Vulkan 已验证、OpenGL3/D3D12 仅可用于游戏级排障且未作 Mod 兼容承诺”，并明确
验证范围为 `public-beta` / `v0.111.0`。本节记录的是源文件修订；重新上传同一条目需
另行执行发布脚本并保存新的回执，不能把本地源描述当作已上线内容。

## 上传实现与复用

统一入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\workshop\Publish-VivhiteWorkshop.ps1
```

入口会依次完成隔离 Release 构建、PCK 内容门禁、确定性预览重建、manifest/版本/依赖/三件套精确校验、Steamworks.NET 上传和回执检查。`workshop/workshop-item.json` 已固化 item ID，后续默认更新现有条目。上传器会先查询现有 children；RitsuLib 已存在时输出 `dependency_present=3747602295`，不会因重复 `AddDependency` 让更新失败。

上传只复用本机已经运行且登录的可信 Steam 客户端。工具不读取、不接收、不保存密码、Steam Guard 码、令牌或其他登录秘密。

## 问题与经验

1. 游戏部署目录中的旧 PCK 不应直接当发布物。首轮核验发现源文件已有更新，因此采用独立输出目录做同批 DLL/JSON/PCK 构建，并在上传前强制运行完整 PCK 门禁。
2. Steam 对该 ready-to-use Workshop 的 `GetWorkshopEULAStatus` 返回 `k_EResultInvalidParam`。上传器只把它视作“不提供预检接口”，仍以 `CreateItem` / `SubmitItemUpdate` 的协议标志做 fail-closed 判断；权威标志均为 false。
3. Steam 原生库会向 stderr 写初始化诊断。包装器保留这些行到本地忽略日志，并以进程退出码和结构化回执判定成败；不得提交本地日志。
4. 首发后出现同批文案修正时，必须重建并更新原 item，而不是创建第二个条目。最终对外包以三件套 SHA256 和最后一份 `published` 回执为准。
5. 仓库存在并行改动。发布文件使用精确路径和独立提交处理，禁止把 `knowledge/`、主线程文案修正或其他脏工作树内容带入发布提交。
