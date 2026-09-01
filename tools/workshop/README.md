# `tools/workshop`

这里是白绮 Vivhite 的 Workshop 物料生成、发布前校验和 Steam 上传桥接工具。它与
[`workshop/`](../../workshop/README.md) 的受 Git 跟踪物料分工如下：脚本负责生成/验收和
调用发布器，`workshop/` 保存 `description.bbcode`、`preview.jpg`、版本 metadata 及历史
预览归档。运行本目录的发布命令会产生外部 Workshop 变更；默认不启动游戏、Brain 或直播。

## 文件地图

| 路径 | 作用 | 状态影响 |
| --- | --- | --- |
| [`New-VivhiteWorkshopPreview.ps1`](New-VivhiteWorkshopPreview.ps1) | 从已验收的白绮 hero/transition 源确定性生成 1024×1024 `preview.jpg`，同步 SHA-256/尺寸/版本 metadata，并归档旧预览 | 写 `workshop/` 受控物料；不访问 Steam |
| [`Publish-VivhiteWorkshop.ps1`](Publish-VivhiteWorkshop.ps1) | 串联 Release 三件套构建、PCK 闸门、预览/BBCode 契约、change note 和上传器 | `-PrepareOnly` 只写本地预检；正式运行会更新 Steam Workshop |
| [`SteamWorkshopUploader/`](SteamWorkshopUploader/README.md) | .NET 9 + Steamworks.NET CLI，使用已登录 Steam 客户端提交 item update | 真实上传；不保存凭据、不申请 UAC |
| [`tests/`](tests/README.md) | change-note 参数、严格 UTF-8 和 Steam 初始化前拒绝的 Python 契约测试 | 不登录/不提交 Workshop |

## 预览图生成

从仓库根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\workshop\New-VivhiteWorkshopPreview.ps1
```

脚本默认读取 `workshop/workshop-item.json`，使用仓库内已验收的白绮选人 hero 和 transition
源，原子替换预览图，并把上一版本按 `preview-v<version>-sha256-<hash>.jpg` 与 sidecar
归档到 `workshop/preview-history/`。若现有预览哈希与 metadata 不一致，脚本会拒绝覆盖，
避免把未登记的图片静默抹掉。图片是单幅 Workshop 成品，不是运行时 atlas；运行时素材的
Alpha/Spine 检查仍走 [`tools/art/README.md`](../art/README.md) 的专用流程。

## 发布前流程

推荐只使用统一入口，并在仓库根目录执行：

```powershell
# 只构建、验收并生成 preflight.json，不触碰 Steam
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\workshop\Publish-VivhiteWorkshop.ps1 -PrepareOnly

# 正式更新（需已登录 Steam 客户端，且用户已完成 Workshop 协议）
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\workshop\Publish-VivhiteWorkshop.ps1 `
  -PublishedFileId 3793741497 -Visibility public
```

发布脚本的固定顺序是：

```text
Release 构建（同批次 DLL/JSON/PCK）
        → Verify-VivhitePck.ps1 四层只读闸门
        → 预览图 + metadata 哈希/尺寸/版本门禁
        → 中英文 BBCode + 4 条 changelog 生成 change note
        → manifest/依赖/三件套门禁
        → SteamWorkshopUploader SubmitItemUpdate
        → receipt + 远端只读回执
```

正式发布不要使用 `-SkipBuild` 或 `-SkipPreview` 绕过同批次物料；`-PrepareOnly` 是唯一
适合在 Steam 未登录时做的预检模式。上传产生的 `workshop/.runtime/`、日志和 receipt
由脚本维护，属于运行态证据，不要提交或手工编辑。

## 安全与失败处理

- Steam 上传器只接受精确的 `Vivhite.dll`、`Vivhite.json`、`Vivhite.pck` 三件套，描述和
  change note 先做严格 UTF-8 校验，再初始化 Steam。
- 协议确认、Steam 登录和任何 UAC/人工 GUI 授权都必须由用户完成；工具不会自动点击、
  提升权限或读取密码。若协议未同意，保持 fail-closed 并保留回执。
- 发布失败时保留 `workshop/.runtime/preflight.json`、`publish-result.json` 和
  `upload.log`，先核对本批次版本、哈希和远端状态，再决定是否重试；不要直接删除证据。
- 游戏正在运行时，构建可能因 DLL 锁失败。按统一生命周期脚本的规则处理，不要泛杀
  Python/Steam 或手工复制安装目录文件。

## 相关入口

- [`tools/test/README.md`](../test/README.md)：PCK 最终内容闸门。
- [`Vivhite/README.md`](../../Vivhite/README.md)：Mod 构建、部署和版本基线。
- [`docs/2026-09-01-workshop物料版本与预览门禁.md`](../../docs/2026-09-01-workshop物料版本与预览门禁.md)：
  当前物料同步规则与验收证据。
- [`docs/2026-09-01-vivhite-0.2.1-workshop更新回执.md`](../../docs/2026-09-01-vivhite-0.2.1-workshop更新回执.md)：
  最近一次发布回执（历史证据，不替代当前脚本契约）。

