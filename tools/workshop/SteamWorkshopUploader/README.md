# Steam Workshop uploader

本目录是一个最小的 .NET 9 命令行桥接器：通过**已经登录的本机 Steam 客户端**调用
Steamworks.NET，把经过发布脚本验收的白绮三件套上传到 Workshop。它不是游戏 Mod，也不
读取或保存 Steam 密码、Cookie 或 API key；运行它会产生真实的 Workshop 变更，请先确认
版本、可见性和 change note。

## 输入契约

`Program.cs` 在 `SteamAPI.InitEx` 之前完成所有本地输入校验，只有校验通过才接触 Steam：

- `--content` 必须是只含 `Vivhite.dll`、`Vivhite.json`、`Vivhite.pck` 的目录，不能有子目录；
- `--preview` 必须存在，文件大小为 16 bytes（含）至 1,000,000 bytes（不含）；
- `--description-file` 和 `--change-note-file` 必须是严格 UTF-8；描述长度不超过 8,000 个字符；
- change note 必须非空、无 NUL、UTF-8 往返字节完全一致，最多 8,000 UTF-8 bytes（可有 BOM）；
- `--title` 长度为 1–128；`--visibility` 只能是 `public`、`friends`、`private` 或 `unlisted`；
- `--timeout-seconds` 为 30–7,200 秒；`--app-id` 必须非零。

上传回执以原子替换写入 `--result`，包含 `status`、Workshop item id、版本、可见性、依赖、
`upload_complete` 和 `dependency_complete`。失败也会写回执（若已创建 item 则保留其 id），
便于审计和重试。

## 推荐入口：统一发布脚本

不要手工拼接 Steam 参数。仓库根目录的
[`Publish-VivhiteWorkshop.ps1`](../Publish-VivhiteWorkshop.ps1) 会先构建 Release 三件套、
运行 [`tools/test/Verify-VivhitePck.ps1`](../../test/Verify-VivhitePck.ps1)、重新生成并校验
预览图和 BBCode，再从双语 Changelog 生成 change-note 文件，最后才调用本程序：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\workshop\Publish-VivhiteWorkshop.ps1 `
  -PublishedFileId 3793741497 -Visibility public
```

该入口要求 `Vivhite/local.props` 中的 `Sts2Dir`、`Sts2DataDir`、`GodotExe` 有效，并从
`Sts2DataDir` 找到 `Steamworks.NET.dll` 与 `steam_api64.dll`。Steam 客户端必须已运行且已
登录；Workshop 法律协议需要由用户预先完成。发布脚本不启动需要人工 UAC/GUI 授权的程序。
`-PrepareOnly` 只生成本地预检证据，不触碰 Steam；正式发布不要用 `-SkipBuild` 或
`-SkipPreview` 绕过门禁。

## 直接构建（仅开发/诊断）

直接构建需要 Steam 游戏数据目录中的两个原生文件；路径不要写进仓库：

```powershell
$steamworks = 'G:\SteamLibrary\steamapps\common\Slay the Spire 2\data_sts2_windows_x86_64'
dotnet build .\tools\workshop\SteamWorkshopUploader\SteamWorkshopUploader.csproj `
  -c Release -p:SteamworksDir=$steamworks
```

`SteamWorkshopUploader.csproj` 以 `net9.0`、nullable 和 warnings-as-errors 编译，并将
`steam_api64.dll` 复制到输出目录。直接执行时参数必须成对出现；`--published-file-id 0`
会尝试按当前账号拥有的标题/metadata 查找唯一 item，非零 id 则更新指定 item。最小参数
形状如下（路径和版本请替换为同一批次的物料）：

```powershell
$uploader = '.\tools\workshop\SteamWorkshopUploader\bin\Release\net9.0\SteamWorkshopUploader.dll'
& dotnet $uploader `
  --app-id 2868840 --published-file-id 3793741497 `
  --content '<directory-with-Vivhite-triplet>' --preview '<preview.jpg>' `
  --title '<title>' --description-file '<description.bbcode>' `
  --change-note-file '<release-note.txt>' --version '<semver>' `
  --visibility public --dependency-id '<STS2-RitsuLib-workshop-id>' `
  --result '<receipt.json>' --timeout-seconds 900
```

Windows PowerShell 中建议使用 `& dotnet @args` 传参，避免路径空格转义错误。该命令是真实
上传操作，不适合单元测试或无人值守试跑。

## 测试和故障处理

从仓库根目录运行不提交 Workshop 的契约测试：

```powershell
py -3 -B -m unittest discover `
  -s .\tools\workshop\tests -p 'test_*.py' -v
```

测试首先读取源代码检查 change-note 参数和校验顺序；若本地已有 Release DLL，还会测试
非法 UTF-8/超长 change note 在 Steam 初始化前返回退出码 2 且不生成回执。没有 DLL 时该部分
会明确 skip，不代表上传成功。

常见错误：

| 现象 | 处理 |
| --- | --- |
| `SteamAPI.InitEx` 失败 | 启动并登录可信 Steam 客户端，确认 App ID 为 2868840；不要复制凭据到命令行 |
| 法律协议需要确认 | 由用户在 Steam 客户端完成协议确认后重试；本工具不会自动点确认 |
| `content` 不是精确三件套 | 回到统一发布脚本，删除/修复 staging 目录后重新构建 |
| change note UTF-8/大小失败 | 使用 UTF-8 文件并从当前 `description.bbcode` 重新生成，不能截断多字节字符 |
| 上传后只得到 `content_uploaded` | 保留回执和日志，先核对 Workshop 远端只读元数据，再决定是否重试 |

相关记录见 [`docs/2026-09-01-workshop-uploader-change-note.md`](../../../docs/2026-09-01-workshop-uploader-change-note.md)。
