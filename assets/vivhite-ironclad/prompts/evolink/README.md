# EvoLink Prompt 集合

这里按语义和版本保存发送给 EvoLink 的纯文本 Prompt（当前共 106 个版本文件）。命名约定为 `<semantic>-vN.txt`，例如 `split-head-face-attachment-v8.txt`；同一语义的版本不可覆盖或重编号。

Prompt 不应写入“透明背景、棋盘格、白底、灰底、绿幕”等背景词；透明度由请求参数 `background: "transparent"` 控制。Prompt 只描述主体、姿势、构图、材质、光照和禁止元素，实际 endpoint/model/size/quality/resolution/n 必须以 [`../../generated/evolink-paid/`](../../generated/evolink-paid/README.md) 的请求 JSON 为准。

本目录不保存 API Key，不直接触发网络请求，也不代表对应语义已经通过 Alpha 或运行时消费门禁。
