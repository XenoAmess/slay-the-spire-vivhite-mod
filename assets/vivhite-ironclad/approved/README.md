# Approved 发布候选

本集合只放已经通过静态 Alpha/尺寸检查、可以作为发布构建输入的文件。`approved` 不是自动部署清单：是否进入运行时仍要由对应的 Spine/场景消费者、PCK 合同和版本发布门禁确认。

## UI 文件

详见 [`ui/README.md`](ui/README.md)。当前五张批准素材如下：

| 文件 | 用途 |
| --- | --- |
| [`ui/icon.png`](ui/icon.png) | 角色图标 |
| [`ui/icon_outline.png`](ui/icon_outline.png) | 角色图标描边/锁定层 |
| [`ui/map_marker.png`](ui/map_marker.png) | 地图标记 |
| [`ui/select.png`](ui/select.png) | 选人界面选中态 |
| [`ui/select_locked.png`](ui/select_locked.png) | 选人界面锁定态 |

这些 PNG 的原始付费输出仍保存在 [`../generated/evolink-paid/`](../generated/evolink-paid/README.md)；不得覆盖归档原图，也不得从 `legacy-contaminated/` 恢复其他文件。

## 晋级规则

- 复制前核对源图、Prompt、脱敏请求和 SHA-256；不接受只有缩略图或聊天界面视觉判断的候选。
- 运行时接入前在黑、白和实际游戏底色上做 SourceOver，并验证四角 Alpha、边缘留白和目标显示尺寸。
- 任何与旧战士骨骼、污染血缘或程序抠图有关的文件都不得进入本集合。
