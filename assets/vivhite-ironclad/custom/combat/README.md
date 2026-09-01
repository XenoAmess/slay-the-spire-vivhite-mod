# Combat 制作源

战斗源图按职责分为两组：

- `sources/`：整身母源、攻击/重击/施法峰值、死亡侧卧和魔法弧（含 `vivhite-combat-death-side-collapse-v1/v2.png`）；
- `parts/normal/`：当前可供候选验证的后发与蓝蝶刚性部件。

这些文件由 [`../candidates/split_mesh/combat/`](../../candidates/split_mesh/combat/README.md) 和 [`../../evaluation/`](../../evaluation/README.md) 的消费证据引用。整身源不能被误当作 spritesheet，部件源也不能在未完成相邻关节 SourceOver 与真实 Vulkan 采样前进入正式 atlas。运行时资源的注册契约位于 `Vivhite/Vivhite/skins/ironclad/`，不由本目录自动部署。
