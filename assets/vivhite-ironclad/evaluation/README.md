# 离线验收与消费证据

`evaluation/` 保存对素材布局、源码消费者、Alpha、SourceOver、Spine 动画和真实 Vulkan 渲染的可复核证据。这里的 `success=true`、`passed=true` 或“帧检查通过”只代表对应证据层通过，**不自动代表生产或发布通过**；每个候选的生产状态必须以报告中的明确门禁为准。

## 证据集合

| 集合 | 覆盖范围 | 当前结论/入口 |
| --- | --- | --- |
| [`card-trail-vfx/`](card-trail-vfx/) | 0193/0194 数学星卡牌轨迹、基础纹理和运行时检查 | 0193 仍需视觉/整合审查；0194 技术门禁通过但仍有视觉门禁 |
| [`rest-site-acceptance/`](rest-site-acceptance/) | 休息点 3 循环、翻转、火焰开关、随机 seek | 静态与离线 Vulkan 证据通过；报告标明未跑完整运行时整合 |
| [`semantic-back-hair/`](semantic-back-hair/) | 后发刚性部件与 8 个战斗动画 | 研究/候选证据，见 `component-conclusion.md` |
| [`semantic-butterfly/`](semantic-butterfly/README.md) | 蓝蝶层序、解绑和 16 帧 Vulkan 接触表 | 灰盒通过；须在总装中置于前发下方 |
| [`semantic-head-face/`](semantic-head-face/) | 0044/0045 头脸候选、权重和 EyeFire 契约 | 研究候选；纠正蓝蝶层序并完成 EyeFire 场景门禁前不得发布 |
| [`semantic-left-arm/`](semantic-left-arm/) | 远侧手臂 8 动画 × 5 帧与极值遮挡 | 诊断灰盒，不可发布 |
| [`semantic-left-leg/`](semantic-left-leg/README.md) | 远侧腿拓扑、膝/踝极值和五姿势研究 | 研究门禁通过，生产门禁失败 |
| [`semantic-right-arm/`](semantic-right-arm/) | 近侧手臂候选的极值姿势校验 | `validation-summary.json` 通过，但仍是候选证据 |
| [`semantic-right-leg/`](semantic-right-leg/) | 近侧腿三件拆分与轴向冲突 | 推荐拓扑缺少生产美术，不可发布 |
| [`semantic-torso-skirt/`](semantic-torso-skirt/README.md) | 躯干/裙摆消费者、层序和 0054 失败分析 | 已冻结为拒绝；可发布附件数量为 0 |
| [`v3-cast-0107/`](v3-cast-0107/) / [`v3-cast-0107-exact/`](v3-cast-0107-exact/) | 施法峰值、眼部对齐与精确边界 | 精确候选帧通过，仍需正式整合门禁 |
| [`v3-death/`](v3-death/README.md) | 独立死亡侧卧原子切换 | 16/16 离线帧通过；仍需完整 VFX/真机复测 |
| [`v3-heavy-0106/`](v3-heavy-0106/) | 重击峰值与 mix/边界 | 候选证据帧通过，不等同最终自然度 |
| [`v3-hurt-neutral/`](v3-hurt-neutral/) | 中性受伤动画与重复受击风险 | 候选通过；`hurt -> hurt` 零 mix 仍需游戏观察 |

报告、JSON、接触表和 PNG 都是证据原件；不要把接触表拼图当作游戏 atlas，也不要把放大裁切图当作新美术源。

## 固定验收顺序

1. 判断输入是单图、单帧、atlas/spritesheet、tile sheet 还是多区域 PNG；读取相邻 `.atlas`、`.spatlas`、Spine JSON、`.tres` 和场景。
2. 从源码追踪 region/slot、动画与事件名、锚点、缩放、材质、混合模式、UV 和尺寸约束。
3. 对原生 RGBA 做程序化 Alpha 检查，并在黑、白、实际游戏底色及真实相邻部件 setup pose 下 SourceOver。
4. 在 Godot 4.5.1 / Spine 4.2.43 / Windows Vulkan 下采样全部相关动画、极值姿势和状态切换。
5. 只有报告明确给出生产门禁通过、运行时资源合同通过且发布前三件套验收通过，才允许晋级到 `Vivhite/Vivhite/`。

## 可复核原则

验收输出应记录生成时间、渲染驱动、画布、场景缩放、输入路径和 SHA-256。`.import`、`.uid`、`.godot`、临时日志和旧 D 盘绝对路径不是独立运行时证据；若报告引用了它们，仍须优先以仓库内相对路径和报告哈希复核。发现证据缺失、路径失效或结论冲突时保持 fail-closed，并保留现场。
