# Workshop uploader tests

[`test_uploader_change_note.py`](test_uploader_change_note.py) 是 Steam Workshop 上传器的
源代码契约和输入拒绝测试。它验证：

- `--change-note-file` 是必需参数，并且经过验证的**原文**传给 `SubmitItemUpdate`；
- 严格 UTF-8、NUL、空白和 8,000-byte 上限检查发生在 `SteamAPI.InitEx` 之前；
- 非法 UTF-8 和超长文件返回退出码 2，不创建回执，也不触碰 Steam。

测试不会登录 Steam、创建 Workshop item 或提交任何更新。若本地没有已经构建的
`SteamWorkshopUploader.dll`，涉及进程的两项测试会显示为 skip；源代码契约仍会运行。

从仓库根目录执行：

```powershell
py -3 -B -m unittest discover `
  -s .\tools\workshop\tests -p 'test_*.py' -v
```

完整上传器说明见 [`../SteamWorkshopUploader/README.md`](../SteamWorkshopUploader/README.md)，
统一物料、预览图和发布门禁见 [`../README.md`](../README.md)。测试 fixture 使用系统临时
目录，禁止把生成的 DLL、receipt 或 Steam 日志提交到 Git。

