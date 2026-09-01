# 2026-08-27 污染血缘快照

这是旧版白绮 Ironclad 换皮流程的完整隔离快照，包含 `custom/`、`generated/`、`runtime-current/` 和 `tools/` 四类历史对象。其来源包括画入 RGB 的棋盘格/绿幕、程序化 Alpha、旧战士形状 region 转移及其运行时副本。

## 允许与禁止

- 目录整体只用于历史审计、哈希追溯和失败复盘；不得作为 EvoLink 参考、身份/姿势锚点、Spine texture/mesh、atlas/UI 输入或运行时资源。
- 唯一封闭例外是四张多人手势：`custom/ui/multiplayer/point.png`、`rock.png`、`paper.png`、`scissors.png`。它们由用户在 2026-08-28 明确批准逐字节恢复到当前 `assets/vivhite-ironclad/custom/ui/multiplayer/`，不得扩展例外。
- 旧目录中的任何 `.import`、缓存、脚本或 packed/runtime 副本都不会因为位于快照中而获得发布资格。

新素材必须从当前 [`../../references/`](../../references/README.md) 的干净参考起链，经 EvoLink 原生透明流程和完整消费者验收；不要在本快照内修图或生成替代品。
