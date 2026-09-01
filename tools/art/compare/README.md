# art/compare

这里放多方案离线比较工具。当前唯一子目录是 [`preview/`](preview/)，它使用
游戏本体 PCK 与匹配的 Spine GDExtension，在隐藏 Vulkan 窗口中按统一场景比例采样
候选。比较器不会部署 Mod、修改候选源或控制正在运行的游戏。

请先读 [`preview/README.md`](preview/README.md)；不要把 `.work/` 报告或临时 stage
当作运行时资源。
