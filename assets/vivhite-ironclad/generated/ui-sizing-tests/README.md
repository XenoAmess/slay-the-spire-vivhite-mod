# UI 尺寸诊断输出

本目录保存 `icon_outline`、`map_marker`、`select` 和 `select_locked` 的缩放/适配测试图。它们是对已批准 UI PNG 的显示尺寸诊断，不是新的生成源、不是 atlas，也不应复制到运行时。

测试图用于比较 100%/104%/106% 等尺寸下的轮廓、留白和叠加关系；最终发布仍以 [`../../approved/ui/`](../../approved/ui/README.md) 的原始 PNG、实际 UI 消费者和发布 PCK 哈希为准。若测试发现问题，应回到干净源和 EvoLink 批次重新验收，不得用像素后处理修补 Alpha。
