# Vivhite Steam Workshop 发布物料

本目录保存可复用、无凭据的创意工坊物料：

已发布条目：<https://steamcommunity.com/sharedfiles/filedetails/?id=3793741497>

- `preview.jpg`：由仓库已验收的白绮选人母源和转场图确定性合成，未调用新的 AI 生成；版本芯片由 `workshop-item.json` 驱动；
- `preview-history/`：受 Git 跟踪的追加式预览历史，文件名包含旧版本和完整 SHA-256，旁有审计 JSON；不覆盖或删除旧图；
- `description.bbcode`：中英双语公开描述，包含每次发布的 `更新日志 / Changelog`；
- `workshop-item.json`：App ID、条目 ID、依赖、当前版本和预览图版本/哈希记录；
- `.runtime/`：被忽略的同批 DLL/JSON/PCK、上传器构建和上传回执。

首次发布或后续更新统一从仓库根执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\workshop\Publish-VivhiteWorkshop.ps1
```

脚本在仓库内隔离构建发布三件套，不覆盖游戏当前 `mods/Vivhite`；随后执行完整 PCK 门禁、按 metadata 版本重建预览、校验中英版本/Changelog/源图哈希/历史命名，再复用正在运行且已登录的 Steam 客户端，通过 Steamworks UGC API 创建或更新条目，并添加 RitsuLib Workshop 依赖。`-SkipPreview` 仅可在预览版本、尺寸、字节数和 SHA-256 全部与 metadata 一致时通过，不能绕过陈旧图片门禁。脚本不读取或保存 Steam 密码、Steam Guard 码或登录令牌。

当前物料版本为 `0.2.1`。本次更新记录 HP 支付在 Tungsten Rod/Buffer 等减伤下仍继续结算、Event Loop 生成牌的战斗内临时/0 费/出牌后 Exhaust 语义，并注明仅 Steam `public-beta`、游戏 `v0.111.0` 的 Vulkan 路径完成实机验证；OpenGL3/D3D12 没有 Mod 兼容承诺。
