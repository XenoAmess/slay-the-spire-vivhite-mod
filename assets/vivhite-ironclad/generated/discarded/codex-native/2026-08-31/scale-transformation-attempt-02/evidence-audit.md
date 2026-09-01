# 尺度变换 attempt-02 独立证据审计

结论：生成来源和后处理检查链可以完整复原，但该候选**没有被运行时采用**，也不能标记为通过稿。

## 可直接证明的链路

- 原始 Codex 会话：`01a05470-252b-7202-b5d3-b4263e9b4297`。
- JSONL 第 3086 行是 `built-in image_gen` 调用；第 3087 行是成功的 `image_generation_end`，call ID 为 `exec-e9e76be2-4478-47be-a710-24f048205827`。
- 调用使用的五张参考图及顺序已经从真实 tool call 恢复，并逐一核对 SHA-256。
- `prompt.txt` 仅比 tool call 和 `revised_prompt` 多一个结尾换行；去掉该换行后逐字相同。
- Codex 默认输出与仓库 `original.png` 的 SHA-256 同为 `E854FEC4...F086C803`，逐字节一致。
- 原图为 `1536×1024`、8-bit、PNG color type 2、无 Alpha；`transparent_background=false`。
- Godot 裁切日志真实记录 `x=105, y=8, w=1325, h=1007`，输出 `1000×760 RGB8`。
- 彩色、灰度以及 `250×190`、`100×76` 检查图均存在，哈希已写入 `generation.json`；两个 Godot 命令均退出 0。

## 未采用原因

中央 25:19 裁切后，白绮后侧用于锚定坐标场的手仍碰到并越过左边界。attempt-03 的真实 Prompt 明确把 attempt-02 作为 Image 1，并把修复这一缺陷列为唯一修订目标。因此 attempt-02 的正确状态是 `inspected_rejected_not_for_runtime`，不是静态通过稿。

## 提交分类

本目录现有原图、逐字 Prompt、全部 inspection 文件、恢复后的 `generation.json` 和本审计文件形成一致的“已检查但未采用候选”证据包，可以按该状态提交。不得把其中的 `prepared-runtime-candidate.png` 当作当前运行时卡图，也不得把状态改写成 accepted。

