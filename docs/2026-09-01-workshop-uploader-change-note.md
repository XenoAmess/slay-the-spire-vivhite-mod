# Steam Workshop 上传器：从发布说明生成真实 Change Note

## 背景

此前 `SteamWorkshopUploader` 在 `SubmitItemUpdate` 时根据“首次发布/刷新元数据”拼接一条固定英文文本。这样即使本地 `description.bbcode` 已经包含更新日志，Steam Workshop 的版本历史仍看不到本次实际修复内容。发布流程现在由上层脚本维护一份与 BBCode 同步的 release-note 文件，并通过以下参数把它交给上传器：

```text
--change-note-file <绝对或可解析为绝对路径的 UTF-8 文件>
```

该参数是必需的；缺失参数不会回退到通用文案，也不会进入 Steam 初始化或创建/更新 Workshop 项目。

## 输入契约

- 文件必须存在且可读；目录、缺失文件和读取错误均 fail-closed。
- 内容必须是严格 UTF-8。允许一个开头 UTF-8 BOM，但 BOM 不会传给 Steam；UTF-16 BOM、非法字节和替换字符路径都会被拒绝。
- 有效 payload 必须包含非空白文本，且不得含 NUL（原生字符串终止符）。换行、中文和 BBCode 文字按原样保留。
- 采用 Steam SDK `k_cchPublishedDocumentChangeDescriptionMax = 8000` 的保守上限，按 UTF-8 **字节**计算，而不是按 .NET UTF-16 字符数计算；超过上限在调用任何 Steam API 前拒绝。当前 Steamworks API 参考将该旧常量标为 “Unused”，因此这是防止截断/拒绝的本地安全上限，而非把未公开行为当成可依赖的服务承诺。
- 解码后再次严格 UTF-8 编码并逐字节比对，确保传给 `SubmitItemUpdate` 的是文件中验证过的确切 payload，而不是宽松解码产生的替换字符或隐式规范化结果。

验证与内容读取在 `Main` 的 Steam 初始化之前完成；上传阶段复用同一份已验证的 description/change note 快照，避免发布过程中途文件被修改造成描述与历史说明错配。

## 调用示例

```powershell
& $dotnetExe $uploaderDll `
  --app-id 2868840 `
  --content $contentDir `
  --preview $previewPath `
  --title $title `
  --description-file $descriptionPath `
  --change-note-file $changeNotePath `
  --visibility public `
  --dependency-id 0 `
  --version 0.2.1 `
  --result $resultPath
```

上层发布脚本负责从仓库维护的 BBCode 更新日志生成/刷新 `$changeNotePath`，并在同一批次预检中记录其来源；上传器只负责验证和把内容传给 Steam，不自行编辑或推送 BBCode。

## 验收

`tools/workshop/tests/test_uploader_change_note.py` 覆盖：

1. `--change-note-file` 必需、无旧固定 fallback，且确实传入 `SubmitItemUpdate`；
2. 严格 UTF-8、非空、NUL 和 8000 字节上限，以及验证发生在 `SteamAPI.InitEx` 之前；
3. 在本机已有构建产物时，非法 UTF-8 与超长文件均以输入错误退出（代码 2），不写发布回执、不触碰 Steam 提交。

依据： [ISteamUGC::SubmitItemUpdate](https://partner.steamgames.com/doc/api/isteamugc#SubmitItemUpdate) 说明 change note 是提交时传入的简短变更说明；[Steamworks 常量参考](https://partner.steamgames.com/doc/api/ISteamRemoteStorage#k_cchPublishedDocumentChangeDescriptionMax) 给出 8000 字节的历史 change-description 上限。
