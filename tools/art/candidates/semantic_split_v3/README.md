# semantic_split_v3 跨组件总装灰盒

这是约八个生成语义组的离线 A/B 总装，不是运行时皮肤。A 行是旧 `split_mesh` 动作消费者；
B 行只接入已有证据支持的真实附件，其余位置使用高对比诊断灰盒。任何输入缺失、哈希漂移、
八动画/事件/slot 缺失、旧扁平 body attachment 泄漏或蓝蝶层序回退都会直接失败。

## B 行的事实状态

- 真实叠层研究输入：0031 后发、0045 头脸、0033 前刘海、0030 蓝蝶；总装顺序采用专项证据
  `后发 → 躯干 → 头脸 → 蓝蝶 → 前刘海`，纠正 head-face 子候选旧的蓝蝶前置实现。
- 真实静态研究输入：0078 远侧大腿、0083 近侧大腿。它们尚未取得生产运行时资格。
- 必须新走 EvoLink 语义生成：`torso_core`；同一服装组协调生成、但分别保存的 `skirt_back`、
  `skirt_side_far`、`skirt_center_front`、`skirt_side_near`；远肩饰前/后片；远/近上臂袖、
  远/近前臂手；远/近两张“小腿+靴一体”，共 13 张生产附件。
- 当前图中一个黄色裙块只是四裙片的总装运动代理，不冒充四个生产 slot；远肩饰前/后片刻意
  保持缺失并在 manifest 中明确阻断。其余缺件显示黄/粉/青交叉纹灰盒。
- 独立手腕和独立脚踝 attachment 已从目标拓扑移除；腕仅作掌心测量锚，膝关节保留。
- `production_runtime_ready_slots` 固定为空。候选不得复制到 `Vivhite/Vivhite/skins/ironclad`。

## 验收

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  tools/art/candidates/semantic_split_v3/Invoke-SemanticSplitV3Preview.ps1
```

脚本先重建并静态验证候选，再用游戏实际 Spine GDExtension、Windows Vulkan、场景 `.28`、
制作比例 `.70` 对 A/B 各做八动画 × 21 帧稠密扫描。最后从扫描中选取消费契约的关键时刻，
写出 `Vivhite/tools/candidates/semantic_split_v3/contact-sheets/`、总览图和
`ab-contact-index.json`。索引逐帧记录请求时刻、实际最近采样和量化误差，不能把近似帧冒充
事件精确帧；正式接入仍须另做 event exact Vulkan。
