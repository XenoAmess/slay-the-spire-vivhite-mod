# Vivhite Steam Workshop 发布物料

本目录保存可复用、无凭据的创意工坊物料：

已发布条目：<https://steamcommunity.com/sharedfiles/filedetails/?id=3793741497>

- `preview.jpg`：由仓库已验收的白绮选人母源和转场图确定性合成，未调用新的 AI 生成；
- `description.bbcode`：中英双语公开描述；
- `workshop-item.json`：App ID、条目 ID、依赖和版本记录；
- `.runtime/`：被忽略的同批 DLL/JSON/PCK、上传器构建和上传回执。

首次发布或后续更新统一从仓库根执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\workshop\Publish-VivhiteWorkshop.ps1
```

脚本在仓库内隔离构建发布三件套，不覆盖游戏当前 `mods/Vivhite`；随后执行完整 PCK 门禁、重建预览、复用正在运行且已登录的 Steam 客户端，通过 Steamworks UGC API 创建或更新条目，并添加 RitsuLib Workshop 依赖。脚本不读取或保存 Steam 密码、Steam Guard 码或登录令牌。
