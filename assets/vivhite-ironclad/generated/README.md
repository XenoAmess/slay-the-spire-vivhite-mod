# Generated 生成归档

`generated/` 是追加式生成与派生物档案，不是运行时素材目录。每个有判断价值的批次都应保留原图、逐字 Prompt、去密请求参数以及后续检查结果；失败、未采用或被废弃的批次不能覆盖或删除。

## 提供方与用途

| 子目录 | 内容 | 使用边界 |
| --- | --- | --- |
| [`evolink-paid/`](evolink-paid/README.md) | EvoLink 付费透明生成的完整批次（按日期/编号） | 原图永久保留；每语义最多 8 次尝试 |
| [`evolink/`](evolink/README.md) | 非付费/专项 EvoLink 记录（当前含 energy-text） | 仍需完整请求与 Alpha 证据，不自动晋级 |
| [`codex-native/`](codex-native/README.md) | 2026-08-31 卡图等本地生成实验 | 仅按批次记录和验收结论使用；不替代透明生成硬契约 |
| [`derived/`](derived/README.md) | 从已验收层确定性组合的派生图与消费者证据 | 不得反向作为新生成参考 |
| [`anchor/`](anchor/README.md) | 从已验收原图复制的身份锚点 | 只读工作副本，原始归档不变 |
| [`native-alpha-experiment/`](native-alpha-experiment/README.md) | 早期原生 Alpha 实验副本 | 实验/审计用途，不是自动运行时输入 |
| [`ui-sizing-tests/`](ui-sizing-tests/README.md) | UI 尺寸与叠加测试输出 | 诊断图，不是发布源 |
| [`discarded/`](discarded/README.md) | 已明确拒绝/废弃的完整批次 | 永不作为参考、atlas 或运行时输入 |

生成叶目录通常包含：

```text
<original/output>.png
<prompt>.txt
<request/generation>.json       # 脱敏参数与事实
inspection/                     # Alpha、SourceOver、尺寸/运行时证据
```

具体批次可有额外的 `consumer-contract.md`、`assessment.md` 或 `runtime/`；不能据目录名推断通过状态，必须读取其报告。

## 安全契约

- 透明新生成只允许 EvoLink `gpt-image-2` + `background: transparent`，经仓库工具发起；API Key、Authorization 和临时签名 URL 不得落盘。
- 代码只可做验收通过后的尺寸适配、切片和打包，不可用抠图、阈值、蒙版、色键或后处理制造/修补 Alpha。
- `inspection/` 中的缩略图、灰度图和 SourceOver 图是证据，不可作为新的生成参考或运行时纹理。
- 每次归档后用相对路径和 SHA-256 复核三件套；若批次失败，保留原样并记录失败原因。
