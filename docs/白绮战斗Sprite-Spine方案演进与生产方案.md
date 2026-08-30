# 白绮战斗 Sprite / Spine 方案演进与生产方案

> 文档性质：长期维护的架构决策、生产规范与复盘。
> 当前基线：Slay the Spire 2 v0.111.0、Godot 4.5.1、Spine 4.2.43。
> 最后更新：2026-08-30。
> 关联手册：[白绮 AI 生成图 Prompt 工程手册](白绮AI生成图Prompt工程手册.md)。
> 当前实现状态：V3 的 neutral、`attack_peak`、`attack_heavy_peak`、`cast_peak`、hurt 与
> death 已总装为 `hybrid_v3_final` 并发布为正式五页 runtime。总装器字段边界、严格五页布局、Spine runtime
> 专项 validator、八动画 84 个精确 Windows Vulkan 时刻、25 组连续中断（104/104 checkpoint、
> 50/50 t0 / mix+ε）、真实 `NIroncladVfx` 8 场景、merchant 十相位，以及严格 30 文件
> Source/Godot/Spine 与完整不部署 PCK 已通过。2026-08-29 又完成正式部署、Vulkan 日志和有范围
> 真机验收；选人、主要战斗动作/VFX、低血、死亡、商店与三幕篝火已覆盖。自然地图 marker、
> 多人端到端和 `light_off` 仍保留为消费路径缺口。本轮没有付费生成或操作 Bilibili 直播。
> 2026-08-30 已完成独立白绮角色与 Ironclad replacement 共用同一 V3 资源配置的源码接入；
> 独立角色仅覆盖自己的 energy counter。该新增消费路径的完整构建、部署与真机验收仍待完成，
> 不能沿用 Ironclad replacement 的既有真机结果冒充独立角色已通过。

## 1. 当前结论

白绮的最终战斗表现不应继续押注“把一张站姿整身图用网格拉出所有动作”，也不应把
“21 个 AI 独立人体碎片全部生成成功”设为唯一通路。当前主方案采用**完整关键姿势
attachment + Spine 骨链过渡 + 独立 VFX 的 Hybrid**：

- 待机、低血、商店 relaxed 和轻微呼吸使用一张身份稳定的中立整身加权网格；
- 普攻、重击、施法和死亡的关键受力姿势使用独立完整人物 attachment；`hurt` 已验证可由
  neutral 网格完成保护性收缩、后撤与回弹，无需新增姿势图；
- Spine 负责前摇、根位移、躯干和四肢的小到中幅联动、关键姿势切换、回弹、落地和
  VFX 时序，不要求单张网格完成不擅长的大角度形变；
- 魔法弧、眼部施法、法阵和光晕始终是独立特效层，人物 attachment 保持空手；
- “拆件 + 骨骼”仍作为并行研究线保留，但从 21 个微型残段收敛为约 8 个生成语义组；
  实际 Spine attachment 可按前后层序和必要关节多于 8 个，只有完成真实叠层验收后才有
  资格替换主方案。

这不是对拆件方案的否定。已有 `0030` 蓝蝶、`0033` 前刘海和 `0083` 右大腿证明，原生
透明独立附件能够生成；真正昂贵的是同时满足朝向、隐藏像素、相邻关节、画风、身份、
slot、pivot 和动画极限姿势。完整关键姿势把模型擅长的“完整人物构图”与 Spine 擅长的
“时序和局部运动”放在各自最可靠的位置。

## 2. 不可破坏的游戏消费契约

所有美术方案先服从消费者，再讨论画法。事实来源是实际场景、C# 注册、骨骼数据、原版
资源和构建器，而不是 PNG 的观感。

### 2.1 场景与比例

- 战斗继续使用私有 `combat.tscn`，保留原战士 Bounds、CenterPos、IntentPos、血条和
  `NIroncladVfx` 场景坐标。
- `SpineSprite` 场景缩放固定为 `Vector2(0.28, 0.28)`；不通过改场景 scale 修人物比例。
- 白绮骨架内部制作尺寸基线为初版的 `70%`，即约 `868 × 1302` Spine world units。
- 70% 真机约 350 px 高，而同截图原战士约 252 px；因此“70%”是当前可看基线，不是
  永久正确答案。最终尺寸须在相同 1920×1080 场景、脚底落点和同一动画采样比较后锁定。
- 商店复用同一战斗骨架并播放 `relaxed_loop`，故人物内部比例、头发和服装修订会同步
  影响商店；不得另做一套悄悄漂移的商店身份。

### 2.2 动画、slot 与事件

必须保留八个动画及既有时长契约：

- `idle_loop`
- `low_health_loop`
- `relaxed_loop`
- `attack`
- `attack_heavy`
- `cast`
- `hurt`
- `die`

必须保留：

- slot：`slash_mesh`、`eye_attach_slot`；
- event：`attack_slash_start`、`heavy_slash_start`、`cast_eyes_start`、`clear_vfx`；
- 原版 10 条 transition mix 与 `default_mix = 0.05`；
- 普攻、重击和施法现有事件时刻，除非源码消费者和真机共同证明需要改动。

白绮是空手魔法师。人物层不得出现剑、法杖、魔杖、书、盾、手持法球或其他武器；攻击
读感来自身体重心、手臂轨迹、根位移、停顿、回弹及魔法 VFX，而不是偷偷加武器。

### 2.3 视觉与血缘

- 固定身份：银发、紫瞳、金色眼镜、蓝蝶、黑白蓝紫魔法少女礼服、可爱而冷淡。
- 每个 AI 生成源必须遵循仓库 EvoLink 原生透明、追加式备份和 Prompt 归档规则。
- 人物、魔法弧、法阵、眼火和整体辉光分层；人物部件的关节切口不得烘入可见光幕。
- packed atlas 只是构建产物，不是 AI 重绘输入；每张源先按单图/单帧/spritesheet/atlas
  分类，再结合源码确定 region、slot、pivot、骨骼和层序。

## 3. 方案演进与旧方案复盘

### 3.1 V0：原战士 atlas / 骨骼兼容换皮

最早版本保留原战士骨骼、动画、region 布局和 10 张 atlas 页，以 AI 生成整身素材作为
语义来源，再确定性裁切、迁移和回包 190 个 region。战斗与商店同名 region 还有不同
rotate 状态，因此必须逐 region 处理，不能把整页直接缩放。

亮点：

- 最快覆盖战斗、商店、篝火、选人、UI 和多人入口；
- 原动画名、事件、Bounds 和 VFX 锚点天然兼容；
- 无武器可通过清空 sword region、重画复合手臂 region、把刀光换成魔法弧实现；
- 确定性打包和严格契约门禁证明了“AI 负责美术语义、代码负责 atlas 布局”可行。

主要问题：

- 原战士是持剑壮汉的姿势、比例、mesh 和权重；换贴图不会变成纤细魔法少女的运动学；
- AI 整身图被强行映射到旧 region 后，隐藏像素和关节并不真实存在；
- 外观虽然全换，动作仍带明显战士站姿，空手攻击缺乏施法者的重心和节奏；
- 早期棋盘格/绿幕血缘后来被判定污染，只能作为历史审计保留。

适用结论：V0 是兼容性探路和完整资源映射样板，不是最终战斗表演方案。

### 3.2 V0.5：私有整身加权网格运行时

随后建立白绮私有 combat Spine：30 根骨、345 个加权顶点、616 个三角形，完整保留八动画、
必要 slot/event 和原战士场景锚点。初版人物约为原战士可见高度的两倍，保留场景 `.28`
后把骨架内部缩至 50% 又显得过小，最终采用 70%；真机修正还包括商店 scale、眼火尺度、
魔法弧 shader 和事件淡出。

亮点：

- 从原战士贴图坐标中解放出来，拥有白绮自己的骨骼、掌心和眼部 VFX 锚点；
- 完整整身 attachment 不产生拆件接缝，脸、眼镜和服装身份稳定；
- 真机验证了资源替换注册、商店复用、VFX 事件和无武器链路可以工作。

暴露的问题：

- 一张整身图的内部遮挡已经压平；肩、肘、髋、膝和裙摆没有旋转后应出现的隐藏像素；
- 动作幅度虽有数值变化，肉眼仍像整片软图轻微晃动，缺乏起势、蓄力、命中和回弹；
- 把站姿网格卷成死亡会产生悬空、折叠或“复用战斗图倒下”的观感；
- 自动检查的“非空、有变化、不触边”和早期人工验收都曾给出通过，但用户真机观感仍明确
  指出人物偏大、动作弱、死亡怪。这说明技术通过不能代替表演质量和用户审美验收。

适用结论：可作为可运行回退基线和中立姿势层，不适合独自承担所有大动作。

### 3.3 V1：完整人物单网格 + 真父子骨链候选

`whole_mesh` 候选用 34 根层级骨链替代平铺控制骨：骨盆—躯干—颈—头、肩—上臂—前臂—手、
髋—大腿—小腿—脚，以及头发和裙摆辅助骨。普通攻击正向峰值 100、重击 158、受伤后退
100 Spine units，在 `.28` 下分别约 28、44.24、28 px；720 个关键段使用 Spine 4.2 合法
Bezier。

亮点：

- 肩转动能携带整条手臂，髋能携带整条腿，运动链比平铺控制骨真实；
- 一张人物图保持连续轮廓，完全没有关节拼缝；
- 事件、transition mix、Vulkan 逐帧加载和动画契约可完整自动验证。

局限：

- 原图仍是一张压平整身；骨链只能弯现有像素，不能创造被袖子、裙摆和身体遮住的内容；
- 大角度时呈橡皮布弯折，固定前后层序无法表现手臂越过躯干或裙摆翻动；
- 它改善了“动起来”，但没有解决“形成可信的新姿势”。

适用结论：适合呼吸、重心、小幅受击和关键姿势之间的短过渡，不适合动作峰值。

### 3.4 V2：15 部件临时 UV + 层级骨链 + 独立死亡整图

`split_mesh` 候选把站姿母图分成 15 个 UV 子域，建立 33 根拆件骨和 1 根死亡骨；死亡前
由拆件错峰坍塌，`1.05s` 原子卸载 15 件并挂载独立侧卧图，随后接地、回弹、静止。

亮点：

- refined 对照中，攻击、重击、受伤的手臂—躯干—重心联动明显优于整片弯折；
- 每个部件有独立层序和旋转，能表达更大的动作弧线；
- 独立死亡整图证明“专用完整姿势 + 原子切换”比站姿网格硬卷可靠；
- 候选保留 10 条 transition mix，并通过真实 Spine 4.2.43 / Vulkan 加载。

局限：

- UV 只是从压平母图取样，关节下没有隐藏像素；切开后必然缺口、叠亮或暴露矩形边缘；
- 死亡 `1.04 → 1.05s` 虽无空帧和双影，Alpha bbox 左边仍跳 61 px、宽增 90 px、高减
  76 px，说明原子切换的锚点和前一姿势不连续；
- 临时 UV 候选只能证明运动学，不能证明最终独立美术可生产。

适用结论：骨链和层序值得继承，临时 UV 美术不得发布。

### 3.5 V2.1：21 个目标微部件中的首批独立 AI 生产实验

为给 V2 补足真实隐藏像素，原计划需要约 21 个部件；当前付费批次先生成了蝶饰、前后发、
头脸、躯干、左右靴、左右大腿和左右小腿，手臂、手与裙片尚未按这条路线生成。每个已开工
语义最多八次。实验取得了三类结果：

1. 蓝蝶 `0030` 等刚性、拓扑明确的单物体首轮可用；
2. 后发 `0031`、前刘海 `0033`、头脸 `0045`、躯干 `0054`、左靴 `0063`、左大腿
   `0078`、右大腿 `0083`、左小腿 `0088`、右小腿 `0100` 等在修正 Alpha 验收后达到
   静态 Alpha 或静态候选标准，但均尚未因此自动获得动态/生产通过；
3. 某些部件八轮都在服从后来被淘汰的契约：右靴 Prompt 与当前 `0018` 历史消费者一致，
   却和已选择的 `0022` / 新 rig 目标方向相反；这首先是迁移真值未统一，不是模型能力上限。

它也暴露了高成本来源：

- “左/右”没有结合战斗母版和构建器，方向错误会污染整组八次；
- 讨论中认可的 `0022` 与 split builder 实际消费的 `0018` 并非同一张母版；至少左小腿
  的绘画方向、硬编码骨轴与两张母版互相冲突。视觉真值和运行时输入不先统一，部件即使
  生成正确也无法装配；
- 脸、躯干和人体残段会触发通用脸、假发、管件、胶囊或内容过滤；
- 每件单独漂亮不等于组合时风格、照明、比例和接缝一致；
- 真实 Alpha 曾被错误查看器显示成大光场，低 Alpha 计数又被误当成肉眼光晕，导致可用图
  被错判；
- 21 件意味着更多 slot、pivot、权重、层序、接缝和极限姿势测试，集成成本高于生成成本。

适用结论：独立生图是可用工具，但 21 个微部件不是当前主线的最低风险交付方式。

## 4. 统一对照数据如何解读

在同一 Windows Vulkan、1280×900 画布、场景 `.28`、制作比例 `.70`、每动画 5 帧下：

| 候选 | 8 动画总帧 | 空帧 / 触边 / 静态动画 | 最大质心位移 | 最大像素变化率 |
| --- | ---: | ---: | ---: | ---: |
| 当时 runtime | 40 | 0 / 0 / 0 | 293.639 px | 0.05001 |
| `whole_mesh` | 40 | 0 / 0 / 0 | 191.176 px | 0.05596 |
| `split_mesh` | 40 | 0 / 0 / 0 | 99.292 px | 0.05403 |

这些数字只证明资源能渲染且帧有变化。质心还会被魔法 VFX 和整身位置影响；数值更大不等于
动作更有力，数值更小也不等于动作更差。动作实感必须看：

- 预备方向是否与出手相反；
- 骨盆、胸腔、肩、肘、腕是否按力链错峰；
- 命中前是否有短暂蓄力，命中帧是否与 VFX event 对齐；
- 峰值轮廓是否与待机明确不同；
- 回弹是否先过冲再稳定，而不是线性复位；
- 脚底支撑、裙摆和头发是否服从惯性；
- 普攻、重击、施法能否只看剪影就区分。

因此生产验收必须同时包含机器门禁、接触表、事件精确帧和用户实际游戏观感。

## 5. V3 主方案：完整关键姿势 Hybrid

### 5.1 视觉层结构

建议 atlas / slot 分层如下：

```text
back magic / cast sigil
neutral whole-body weighted mesh
action pose slot
death pose slot
front magic / slash_mesh
eye_attach_slot
```

正常时只显示 neutral；动作峰值只显示一个 action pose；死亡落地只显示 death pose。同一时刻
不得显示两个人物层。特效可独立淡入淡出，人物层不做两张完整人物的交叉透明。

每个 action pose 必须声明 attachment 类型。默认采用刚性 region 以保持完整剪影，只允许
专用 pose root 做整体位移/旋转；此时四肢骨不会直接驱动图内手脚，不能在验收中声称它有
局部骨链变形。只有确实为该姿势重新绘制网格和权重后，才标记为 weighted mesh。

`SlashVfxSlot` 与 `EyeSlot` 跟随 Spine bone/slot，不会从完整人物图片里自动识别掌心和眼睛。
因此每张 action attachment 都必须配套 pose-specific 掌心、双眼/VFX 锚点骨时间线，并与
人物 attachment 在同一帧切换；事件精确帧检查二者是否落在真实手掌/双眼。商店共用 combat
骨架和 atlas，`relaxed_loop` 必须始终只显示 neutral，并显式隐藏 action/death slot。

首批完整姿势至少为：

- `neutral`：待机基准，也供 relaxed / low-health 小幅变形；
- `attack_peak`：单手或双手前推的短促魔法冲击；
- `attack_heavy_peak`：更低重心、更大胸胯扭转和双臂蓄力释放；
- `cast_peak`：打开胸腔和双臂、视线与眼部 VFX 统一；
- `death_side`：闭眼、重力正确、空手侧卧。

若 `hurt` 用 neutral 网格不能自然完成，再增加保护性收缩的 `hurt_peak`；它不得与低血
待机混淆。不能为了凑齐附件而增加成本。

### 5.2 单个动作的时序模板

以普攻为例：

1. `0%–20%`：neutral 网格后撤，骨盆先动，肩和手后跟；
2. `20%–45%`：根骨前冲，躯干和手臂加速；
3. 在轮廓最接近关键姿势、且魔法弧遮挡最强的 1–2 帧内，neutral 与
   `attack_peak` 做同帧原子切换；
4. `attack_slash_start` 与掌心/魔法弧的峰值对齐；
5. 峰值停留极短时间后原子切回 neutral，利用 VFX 和速度掩盖轮廓差；
6. neutral 网格小幅过冲并回正，`clear_vfx` 清理特效。

不使用完整人物交叉淡化，因为不同轮廓同时半透明会形成双人鬼影。若原子切换明显，优先
修正关键姿势的锚点、比例和前后帧轮廓，再调整切换时刻；不能只靠延长淡化掩盖。

### 5.3 关键姿势绘制契约

每张完整姿势必须与 neutral 共享：

- 相同身份参考、镜头、透视、人物尺度和服装细节；
- 相同画布族和像素密度；
- 可测量的骨盆、头心、脚底、双手和双眼锚点；
- 足够四边留白，不触及 atlas 或预览画布；
- 无武器、无场景、无文字、无第二姿势、无 spritesheet 拼版；
- 人物光影一致，魔法辉光不烘入人物层。

生成时一张图只要求一个动作峰值。禁止让模型一次输出多姿势表或四宫格，再依赖裁切；这会
降低单帧分辨率、身份一致性和 Alpha 独立性。

### 5.4 锚点与切换门禁

每张姿势建立最小锚点表：

```text
pelvis / head_center / left_foot_contact / right_foot_contact
left_hand / right_hand / eye_center / visual_alpha_bbox
```

切换前后必须检查：

- 支撑脚或骨盆不能无意瞬移；
- 头部位移符合动作弧线，不因画布留白变化跳动；
- 事件所用手掌和眼部锚点与 `slash_mesh` / `eye_attach_slot` 同帧对齐；
- Alpha bbox 的变化来自姿势，不来自图片缩放不一致；
- 人物层同帧可见数恒为 1，没有空帧或双影。

死亡专项应在落地前先让 neutral / action 网格形成与侧卧图接近的低位收缩轮廓，再切换。
当前 61 px 横跳是明确的回归门禁：V3 必须显著低于该值，并由实体接触边缘而非最淡 Alpha
决定地面位置。

### 5.5 一张峰值姿势不够时

单个 `attack_peak` 是先跑通消费者、锚点和事件链的最小版本，不是所有动作永久只能有一张
关键图。如果同一套 neutral 网格无法自然连接到峰值，按证据逐步增加：

- `anticipation_pose`：蓄力极值；
- `impact_pose`：命中剪影；
- `recovery_pose`：过冲后的回收极值。

每张仍是单独请求、单独文件和单独 Alpha 验收，禁止让模型输出四宫格、pose sheet 或已经
拼好的 spritesheet。Spine 在姿势之间负责根位移、局部骨链、切换与事件；只有人工逐帧确认
一处轮廓跳变无法靠锚点或网格过渡解决时，才增加下一张，避免把 Hybrid 退化成昂贵且身份
漂移的逐帧动画。

### 5.6 `attack_peak` V3 首个实现记录

首个闭环使用 `0104-combat-attack-peak-attempt-01`，并把其原图逐字节复制为
`custom/combat/sources/vivhite-combat-attack-peak-v1.png`。`0105` 已完整归档但因构图更直、
轮廓力度较弱而不采用；两轮均保留，不删除失败或未选结果。

隔离候选契约如下：

- 新骨 `vivhite_action_pose_root`、新 slot `vivhite_action_pose`、刚性 region
  `vivhite_combat_attack_peak` 和独立 atlas 页 `vivhite_combat_attack.png`；
- neutral 与 action 共同保留原始 `1680×2512` 整画布，统一打进 `1536×2272` region，
  authored world 均为 `868×1302`，场景继续保持 `.28`；禁止 action 自己按 Alpha bbox 归一化；
- `attack` 在 `.08` 同帧隐藏 neutral、显示 action，并触发 `attack_slash_start`；`.20` 同帧
  切回 neutral；人物 slot 不做 RGBA 交叉淡化；其余七动画都在 `t=0` 显式清空 action slot；
- 商店会随机 seek 共用的 `relaxed_loop`，因此该循环在 `0` 与 `12.000001` 两端都重新声明
  neutral 可见、action/death 不可见；
- 刀光不能自动识别完整姿势里的掌心。以隐藏 Vulkan composite 实测后，action 窗口对
  `vivhite_magic_arc` 使用 authored offset `(210,30)`，约等于最终画面向右 `59 px`、向上
  `8 px`，并与人物 attachment 同帧切换；attack 不发 EyeFire，眼部锚点保持 neutral；
- `SlashVfxSlot` 位于人物后方，只是视觉强调，不能被当作人物切换的遮罩。

静态验收覆盖 6 个 authored 文件、Spine `4.2.43`、8 个动画、108 个可见性分段和 28 个
runtime 样本。精确 Vulkan 验收使用真实 `0.1s` mix，共采 14 个时刻；人物层和 composite
均非空、无裁切，人物 attachment 数始终为 1，`.0799 → .08` 脚底变化为 `+4 px`，峰值末端
脚底相对切换前为 `-1 px`。`.20` 切回后的 neutral recovery 脚底再上移约 `12 px`，这是当前
仍需在游戏实际速度下观察的连续性风险；若用户真机能看见明显跳变，优先调整前后轮廓或
增加独立 recovery pose，不用双人物淡化掩盖。

同一构建又按每动画 21 帧复验全部八动画，168 帧均通过；`attack` 的最大逐帧质心位移约
`92.89 px`，没有空帧、触边或失败动画。该数值包含魔法 VFX，只用于同条件回归，不把它
冒充“动作自然”的审美分数。

当前结论仅为“隔离候选离线集成通过”。它证明了完整姿势、固定画布、原子 slot 与
pose-specific VFX 锚点这条链可行，但不等于正式运行时或用户审美门禁已经通过。

### 5.7 `attack_heavy_peak` 的独立消费者闭环

重击使用 `0106-combat-attack-heavy-peak-attempt-01`，并逐字节固化为
`custom/combat/sources/vivhite-combat-attack-heavy-peak-v1.png`；两者 SHA-256 均为
`648AD676050A6D8A1826567D48288105FBF12FCD0AD87D75E43D24029301B1F1`。它与普攻共用
`vivhite_action_pose` slot，但使用独立 atlas 页 `vivhite_combat_attack_heavy.png` 和 region
`vivhite_combat_attack_heavy_peak`；同样冻结完整 `1680×2512 → 1536×2272 → 868×1302`
画布变换，不按动作自身 Alpha bbox 归一化。

`attack_heavy` 在 `.12` 同帧触发 `heavy_slash_start`、隐藏 neutral 并挂载 heavy；`.32`
原子切回 neutral，可见区间为 `[.12,.32)`。`idle_loop → attack_heavy` 的运行时 mix 实测为
`.01999999955s`。掌心魔法弧首轮沿用普攻在真实场景测得的 authored offset `(210,30)`；
在重击 composite 中亮核从双掌前方起弧，保留少量空气间隔且不覆盖手指。

静态门禁覆盖 7 个 authored 文件、8 动画、Spine `4.2.43`、34 个全时段人物可见性样本和
32 个 runtime 样本。14 个精确 Windows Vulkan 时刻全部通过；character-only 会把 slash、
eye、sigil 三槽同时设为 null 与 Alpha 0，每帧恰好一个人物，无空帧、触边或双影。`.1199 →
.12` 脚底变化 `-4 px`、质心右移约 `17.27 px` 并上移 `8.19 px`；`.3199 → .32` 脚底
变化 `-2 px`。低重心、宽站姿和双空掌在无 VFX 时也能与普攻区分，因此停止在 1/8 次。

这推翻的是“0106 只有复用普攻窗口的阶段预览”旧状态；当前升级为“隔离候选离线集成通过”。
尚未推翻的风险是 `.12` 切入质心变化在用户真实游戏速度下是否可见；若真机突兀，先调前摇
轮廓、pose root 或切换时刻，再考虑单独 anticipation pose，不做双人物交叉淡化。

### 5.8 `cast_peak` 精确消费者闭环

施法首轮 `0107-combat-cast-peak-attempt-01` 已逐字节固化为
`custom/combat/sources/vivhite-combat-cast-peak-v1.png`。固定消费者下 cast 实体约
`206×349 px`，neutral 约 `209×351 px`；其高右掌、低左掌、打开胸腔和双腿支撑形成独立
施法剪影，空手且人物层没有法阵或能量。普通直显看到的宽蓝紫光场已被真实三底 SourceOver
推翻：实体核外扩折算到游戏尺寸不足 `0.6 px`，所以没有为错误显示浪费第 2 次生成。

接入契约冻结为：sigil 在 `.10` 挂载，`.25` 同帧触发 `cast_eyes_start` 并把 neutral 原子切换
为 `vivhite_combat_cast_peak`，人物可见窗口 `[.25,.60)`，`.60` 切回 neutral，
`1.222000026` 同帧触发 `clear_vfx` 并卸载 sigil，动画结束于 `1.5666667`。cast 在 `t=0`
触发 `clear_vfx` 清理外部 EyeFire，Spine slot 时间线另行清理 slash；最终事件序列为
`clear_vfx@0 → cast_eyes_start@.25 → clear_vfx@1.222000026`。EyeFire 不会替骨架清理任何
attachment，因此 action、sigil 和眼部 pose anchor 必须由各自时间线同帧切换与复位。
`relaxed_loop` 两端仍须重申 neutral 唯一可见，
隐藏 action/death/slash/sigil，防止商店随机 seek 进入残留状态。

旧状态只完成静态门禁，随后精确 Windows Vulkan 暴露并纠正了真正的问题：初版 EyeFire
offset `(40,40)` 的亮核 bbox 为 `(295,257,7,22)`，而同帧双眼约在 `(342,371)`，视觉上明显
悬空。最终消费者在 cast 人物窗口使用 `(194,-292)`，`.60` 切回 neutral 后改用
`(72,-282)`，直到 `clear_vfx` 清理。14/14 个精确时刻均为单人物、非空、无裁切；
character-only 正确隔离人物，composite 同时验证 sigil 和眼火的出现、切换与复位。

因此 `0107` 已升级为“隔离候选离线集成通过”，证据在
`assets/vivhite-ironclad/evaluation/v3-cast-0107-exact/`。它已进入五页 `hybrid_v3_final`，总装
cast exact 14/14、连续状态机、真实 consumer 与完整隔离 PCK 均通过；剩余门禁是正式 runtime
与用户真机审美，该状态仍不等于已部署通过。

### 5.9 V3 独立死亡连续性闭环

V3 继续使用冻结的 `0029` 侧卧整身美术源
`custom/combat/sources/vivhite-combat-death-side-collapse-v2.png`，SHA-256 为
`9B391E6DAE9AC1E85D05D77B3B0E7E286BF2F0B613E164C714A99054EC12A17B`。它不把死亡图
揉回 neutral 网格，也不重画 Alpha；改动只发生在 Spine 消费者：`die` 前段先让 neutral
形成低位、收缩、向侧卧轮廓靠近的坍塌，`1.05s` 同帧卸载 `vivhite_body` 并挂载唯一刚性
`vivhite_combat_death_side`，随后用 `2px` 压缩、`4px` 回弹和阻尼归位完成实体接地。人物层
不做 RGBA 交叉淡化，`hurt → die` 的运行时 mix 明确为 `0s`。

根代理在独立进程中复跑了 Windows display + Vulkan + 游戏实际 Spine GDExtension，共采
16 个精确时刻，覆盖预滚、坍塌极值、`1.0499 / 1.05 / 1.0501s` 原子边界、首次接地、
回弹和最终静止。16/16 均为非空、单人物 attachment、无裁切、无双影，且 slash / eye /
sigil 在 character-only 中同时为 null 与 Alpha 0。实体左边界切换跳变为 `16px`，相对旧 V2
的 `61px` 显著下降；最淡 Alpha 左边界跳变为 `33px`，但不用于决定实体接地。实体底边切换
只变化 `1px`，落地底边序列为 `684, 686, 680, 684, 684px`。

这推翻的是“已有死亡图必须再次生成才能修观感”的隐含假设，以及“当前仍是 61px 横跳”的
旧动态状态；没有推翻“独立侧卧整身 attachment 是正确素材类型”。当前状态为“隔离候选离线
集成通过”，证据在 `assets/vivhite-ironclad/evaluation/v3-death/`。`0029` 已作为逐字节供体进入
隔离五页 atlas，attack/heavy/cast/hurt 热源进入 die 的连续序列也已通过；它仍未进入正式
runtime，用户真机接地与观感仍待验。失败时回退到当前已部署 runtime，不在坏包上继续测试。

### 5.10 `hurt` 由 neutral 网格承担

`hybrid_hurt_neutral` 验证了受伤不需要新增 PNG、atlas 页或独立完整姿势。现有 neutral whole
mesh 通过保护性收缩、后撤和回弹完成 `hurt`：冲击 `.10`、恢复 `.28`、过冲 `.46`、阻尼
`.70`、`1.0` 回正。两候选 × 八动画 × 11 帧全部通过；`hurt` 有 10/11 个唯一帧，其余七动画
共 77/77 帧的 hash 与上游一致，证明改动没有污染其他动画。

受伤轮廓宽度从约 `210 px` 收缩为 `193 px`（约 `-8.1%`），最大质心位移约 `18.478 px`。
transition mix 冻结为 idle→hurt `.03s`、hurt→hurt `0s`、hurt→idle `.10s`、hurt→die `0s`。
统一候选已覆盖 `hurt` 热源到 hurt/die/idle 等目标并通过 t0 / mix+ε 门禁；连续受击在真实
游戏速度下的观感仍是用户真机门禁，而不是未完成的状态机测试或重新生图理由。证据在
`assets/vivhite-ironclad/evaluation/v3-hurt-neutral/`。

### 5.11 neutral / 商店共同基线

`hybrid_neutral_v3` 只修改 `idle_loop`、`low_health_loop`、`relaxed_loop`，保留 345 顶点、
616 三角、35 根骨；每个顶点四权重，共使用 28 根骨。19/19 个精确离线时刻通过。商店随机
seek 专项覆盖 `0, 1.37, 3, 5.4, 6, 9, 9.9, 11.9999, 12.000001`，所有相位都只保留 body，
并显式清理 action、death、slash、sigil 和 eye。它还修复了旧 neutral 循环没有始终复位
slash / sigil 的真实回归。

实际 `A>=128` 高度约为 `345–353 px`；原版战士对照高度约 `252 px`，即白绮仍约为原版的
`1.389×`。这是用户指定“当前骨架内部 70%”后的已知视觉差异，不得把“相比上一版不再过大”
写成“与原战士同尺寸”。统一真机必须继续检查 Bounds、血条、意图、VFX 与商店构图。

### 5.12 五页运行时契约与隔离总装

构建和校验现在同时支持两套严格布局：默认 `legacy-single-page` 仍要求原 26 个私有运行时
文件；显式 `v3-five-page` 要求 30 个文件，并按以下固定顺序同时供 combat 与 merchant 使用：

1. `vivhite_combat.png`，`3072×2304`，neutral + magic arc + sigil；
2. `vivhite_combat_death.png`，`2048×1536`；
3. `vivhite_combat_attack.png`，`2048×2304`；
4. `vivhite_combat_attack_heavy.png`，`2048×2304`；
5. `vivhite_combat_cast.png`，`2048×2304`。

`IroncladReplacementAssets` 只接受完整 legacy 或完整 V3 集合，部分页、错页名和混合布局均
fail closed。发布工具使用 `--runtime-layout v3-five-page`，构建使用
`/p:IroncladSkinRuntimeLayout=v3-five-page`；默认值没有改变。契约测试 4/4、C# build 0 warning /
0 error、legacy 26 文件 fixture、V3 30 文件 fixture、Godot/Spine 与最小 PCK 均已离线通过。
这里的“最小 PCK”仅指早期布局 fixture，不代表 `hybrid_v3_final` 的完整隔离 DLL/PCK 门禁。

`hybrid_v3_final` 已按最小、可反向证明的字段差量创建：以 `hybrid_cast_set` 为结构基线，
只移植 neutral 三循环的完整 slot 子树、`hurt.bones`，以及 death 的 `vivhite_rig` /
`vivhite_death_pose` 两个 bone 子树。真实 consumer 随后复现 `cast→cast` 时旧 EyeFire 残留，
因此新增了唯一一项有运行证据的差量：`cast.events` 首项 `clear_vfx@0`。五张页图分别从
neutral、death、attack、heavy、cast
已验收供体逐字节复制，不重新编码 PNG。总装器连续两次输出哈希一致；反向归一化后与 cast
基线语义完全相等，未发现越界字段变化。最终 Spine JSON SHA-256 为
`608DE3B142BB24A5D2BD402C24B6B1BAD4E643C0896D5931C854BAFE5353AAA1`。

候选专项 validator 已通过 8 authored / 5 pages / 35 bones / 6 slots / 8 animations / 4 events，
并完成 73 次 runtime 语义检查。总装版八动画又以真实游戏 Spine GDExtension 和 Windows Vulkan
完成 84 个精确时刻：neutral `5+5+9`、attack/heavy/cast 各 14、hurt 7、die 16；全部保持
单人物、非空、无触边，四个原子窗口也按既定附件契约切换。单独看 fresh exact sampler 不能
替代连续 AnimationState、真实 `NIroncladVfx`、merchant consumer 或真机验收；前三项已由下段
专项证据补齐。本句最初记录的“真机仍未执行”已由 5.13 的 2026-08-29 结果更新。

后续连续门禁已补齐到 25 条同实例 AnimationState 序列，104/104 个 Vulkan checkpoint 与
50/50 个 target t0 / mix+ε 六槽检查通过；没有复现 slash、sigil、action 或 death attachment
残留，因此没有批量增加 t0 reset。acceptance-only C# bridge 直接实例化当前游戏程序集的真实
`NIroncladVfx`：修复前 8 场景中唯一失败是 `cast@.30→cast@0`，旧 EyeFire 在 `.06s` 后仍可见；
隔离 A/B 证明零时 `clear_vfx` 的真实信号顺序位于 `animation_started` 之后、首个 epsilon 之前，
并保留 `.25` 再开启、`1.222000026` 再关闭。正式修复候选复跑为 8/8。merchant 正式 PackedScene
布局与 candidate override 的十个 dirty seek 相位也全部 body-only；standalone 中
`NMerchantCharacter` C# 未绑定，报告明确只把该段称为真实布局 + 已验证 seek 合约代理。

截至本段最初写成时，正式 `Vivhite/Vivhite/skins/ironclad/**` 仍保持 legacy；该历史结论已由
下一节的 2026-08-29 正式发布更新。连续状态机、真实 VFX、merchant、严格 30 文件
Source/Godot/Spine 与完整隔离 PCK 的离线证据继续作为发布输入事实，不因部署而被改写。

### 5.13 正式发布与真机消费结果

2026-08-29 使用显式 `v3-five-page` 把 `hybrid_v3_final` 发布为正式 30 逻辑文件 runtime；与隔离
runtime 的规范化清单 SHA-256 均为
`03D8818137931A429810BBCB6F4700CFB8E356205B5F45621E9A4E9C2BE5E931`。部署 PCK 为
101 entries、14,598,276 bytes，SHA-256
`F674613294E7BA69FF823A83AB1E465A8F730D6E5DB59791F343EE68608A84D0`；旧 26 文件 runtime 与旧
游戏三件套已保存在 `.work/hybrid-v3-deploy/backup-20260829-005041-7733080/`。

Vulkan 真机已覆盖 `IRONCLAD` 选人循环、idle、low-health、attack、attack-heavy、cast、非致死
hurt、die 到 `GAME_OVER`、普通 merchant、伪 merchant 视觉路径与三幕 rest-site 循环。普通
攻击、重击与施法均由实际卡牌消费并产生对应游戏结果；普通商店跨过 12 秒 relaxed 边界并开关
库存；三幕坐姿都跨过各自循环边界。

死亡序列的旧离线结论没有被推翻。真机 40 帧只出现一个人物：前两帧为同一 weighted body
倒下，随后是单一 `vivhite_combat_death_side`。全屏缩略图一度把两条腿与多层裙甲看成第二个人；
放大后只有一个头、一个躯干、两臂两腿，且 atlas 只有一个 death region、场景只有一个
SpineSprite、`die@1.05` 的 body/death slot 互斥。该纠正不需要修素材或新增 validator。

保留三项准确缺口：第一幕休息成功后未看到 `light_off`，现有反编译证据指向基础 consumer 在
清空选项前调用回调；调试跳房没有形成有效自然地图 marker；没有第二客户端做多人手势端到端。
这些都不能反向证明五页人物或 Alpha 失败。完整真机矩阵见
`2026-08-29-白绮Hybrid-V3部署与真机验收.md`。

### 5.14 独立白绮角色与 Ironclad replacement 共用 V3 资源

2026-08-30 获批并完成源码接入的资源契约是：Ironclad replacement 与独立 `Vivhite` 角色必须
复用同一份已注册 `CharacterAssetProfile`。二者共同消费当前 V3 五页 combat atlas、同一套白绮
私有骨骼、网格、权重和八动画，以及同一组 combat、merchant、rest-site、character-select、
UI 与 multiplayer 资源。独立角色不得复制出第二套可能漂移的资源路径；它只在共享 profile 上
覆盖自己的 `Vivhite_energy_counter.tscn`。

资源共享不改变玩法身份。独立白绮继续保留自己的 character ID、卡池、最大/当前生命、能量
状态和独立 energy counter；Ironclad replacement 仍是原战士玩法身份。共享的是视觉与场景消费
契约，不是角色状态、牌池或计数器实例。

此前独立角色使用 `scenes/characters/` 下静态占位战斗/商店/休息场景的路径，已被共享 V3
profile 取代。旧路径只能显示占位形象，不能可靠消费当前 combat skeleton、动作事件、VFX 锚点
和五页 atlas，而且会让同一白绮形象维护两套互相漂移的场景事实源，因此不再允许作为独立角色
的运行时回退。`legacy-single-page` 仍可作为历史审计与精确回退包保存，但不得成为正常构建或
独立角色加载路径；当前项目默认运行时布局已经切换为 `v3-five-page`。

本次接入没有生成或修改任何创意素材，没有改动 PNG、atlas、Spine、场景、UI 或多人手势；
现有原图、生成原图、候选和中间资产全部原样保留。当前证据边界为源码配置：
`VivhiteCharacter.AssetProfile` 读取已注册的 Ironclad replacement profile，并只替换 energy
counter；构建默认值指向 `v3-five-page`。本节更新时，独立白绮的最终完整构建、部署和真机
消费尚未完成，状态不得标记为真机通过。

下一道真机门禁必须同时证明：

- 分别以 Ironclad 与 Vivhite character ID 进入选人、战斗、商店和休息场景，资源路径与 V3
  五页 atlas 一致，八动画和 VFX 事件均正常；
- Vivhite 使用自己的卡池、生命/能量状态和 energy counter，Ironclad 的玩法状态不被替换；
- character-select、UI、地图标记与 multiplayer 手势均来自同一共享资源组；
- 日志与 PCK 消费中没有回落到旧静态占位场景或 legacy 单页。

若门禁失败，应修复共享 profile、注册顺序或 PCK 消费路径，并继续保留已验证的 V3 资源作为
事实源；不得以恢复旧静态独立角色或 legacy 单页来掩盖接入故障。

## 6. 并行研究线：约 8 个生成语义组

若继续拆件路线，推荐把 21 个独立微件收敛为约八个彼此协调的生成语义组：

1. 后发；
2. 完整头脸 + 中央前刘海；
3. 蓝蝶；
4. 躯干与裙摆的同套服装组；
5. 左臂组；
6. 右臂组；
7. 左腿组；
8. 右腿组。

“生成语义组”不是“一张图或一个 slot”。早期概括曾把头部层序写成
`后发 → 头脸/前发 → 蓝蝶`；专属 `0030` A/B 消费者已经推翻其中的前后关系：蓝蝶放在最前
会露出过长连接片，生产顺序必须是 `后发 → 头脸 → 蓝蝶 → 前发`，由前发遮住连接片而保留
双翼。四者不能合成同一 attachment；躯干与裙摆可用同一组参考和
配色连续生成，但若裙摆需要惯性仍应拆 slot。每条腿至少保留“大腿 + 小腿靴一体”两个
attachment，不能为了凑成七件而消灭膝关节；每条手臂也可按实际肘部运动拆成上臂和前臂手。

蓝蝶专项已经证明 `0030` 可保持一个刚性 region：源图/候选哈希一致、四边透明、pivot
`(176,650)` 落在实心连接片，16/16 Windows Vulkan 极值帧无空帧或裁切；`die@1.05s` 与身体
同步解绑，商店 `relaxed_loop` 任意随机相位仍唯一可见。当前状态仍是隔离头部灰盒，不是正式
生产通过；统一骨架应创建 `vivhite_butterfly` slot，父骨为 `vivhite_head`，并在整身战斗和
商店中复测。证据保存在 `assets/vivhite-ironclad/evaluation/semantic-butterfly/`。

### 6.1 屏幕左侧远臂的两件制灰盒结论

旧 `arm_left_*` 是屏幕侧别名；结合非对称蓝金肩饰、整身母版、UV 与层序，实际对应角色
远侧、解剖右臂。生产命名统一使用 `far_*`，避免再次把屏幕左误写成解剖左。

最低可靠粒度为 `far_upper_arm + far_forearm_hand`。腕部只保留测量锚点；没有真实极值失败
证据前不拆第三件。固定后到前层序为远侧上臂、远侧前臂手、躯干肩盖；蓝金肩饰属于躯干
肩盖而不是手臂，肩盖必须遮住上臂根部搭接。远侧手臂不拥有 `slash_mesh`；攻击魔法弧绑定
屏幕右侧近手，眼部 VFX 仍绑定头部。

隔离灰盒用游戏实际 Spine GDExtension、Windows Vulkan、`.28` 场景缩放采样八动画各五帧，
40/40 非空、有变化、无触边；`cast` 的上臂/前臂相对极值为 `-35°/-48°`，`die` 为
`+71°/+55°`，肩肘遮挡连续。该结果只批准消费结构，不批准诊断色块或历史 UV 进入 atlas；
仓库当前没有可发布的独立远臂美术。回退是继续使用 Hybrid 整身动作主线；拆件线下一门禁是
先冻结躯干肩盖与肩肘 pivot，再按此两件制生成干净美术并复跑相邻叠层。证据在
`assets/vivhite-ironclad/evaluation/semantic-left-arm/`。

### 6.2 `0031` 单张 weighted 后发

`0031` 不是 spritesheet 或多发束拼图，而是一张完整后发帽体；归档、提升源和候选页三者
逐字节一致。生产候选使用 `7×7` 网格（49 顶点、72 三角），冠顶保持 100% 根骨约束，下半部
才逐步分给左/中/右发尾，末梢三骨总权重不超过 `.72`。这样保留发尾惯性而不让整顶假发随
末端甩动。

Windows Vulkan 按八动画各 21 帧采样，168/168 非空、无触边且均有变化；重击约 `+20°`、
受伤约 `-19°` 的发尾压力下未见冠顶脱离、双头、颈部穿透或明显三角折线。商店所用
`relaxed_loop` 有 11 个唯一帧、首尾 hash 一致，能够承受任意随机 seek。结论是保留单个
weighted 后发 attachment，不拆成多根发束，也不再付费生成。

本专项旧接触表把蓝蝶画在前发之后的视觉前景；它只证明后发网格，不是总装层序真值。统一
生产骨架必须采用蓝蝶专项纠正后的 `后发 → 头脸 → 蓝蝶 → 前发`。此外该候选在 `die@0` 就
卸载正常头部，因此倒地阶段发丝仍由完整跨组件/独立死亡消费者验证。证据在
`assets/vivhite-ironclad/evaluation/semantic-back-hair/`；回退仍是 Hybrid 整身头部。

### 6.3 头脸、近臂、双腿与躯干裙摆的冻结结论

- 头脸：`0045` weighted consumer 为当前首选、`0045` rigid 为回退、`0044` 为历史对照；
  三候选 × 八动画 × 五帧共 120/120 通过。专项接触表沿用过旧层序，总装必须使用
  `后发 → 头脸 → 蓝蝶 → 前发`。当前仍是 research-only；真实 EyeFire 总场景待总装复验；
- 近臂（屏幕右/解剖左）：同样采用“上臂袖 + 前臂手”，不拆腕；`near_palm_deform` 只作内部
  变形，`slash_mesh` 仍是独立 VFX 消费者。9/9 灰盒通过，真实可发布美术为 0；
- 远腿：`far_thigh + far_lower_leg_with_boot`，保留膝、不拆踝；近腿：
  `right_thigh + right_lower_leg_and_boot_union`，保留髋/膝、锁定踝。`0078/0083/0100` 只作
  研究参考，旧 `0064–0071` 鞋尖方向错误；
- 躯干裙摆：必须拆成 `torso_core`、四个独立裙片和远肩饰前/后片。`0054` 的 Alpha 通过，
  但烘入袖、肩饰、腰裙与比例使其生产失败；`0048–0055` 已用满同一语义的 8/8 次额度。

统一语义 A/B 灰盒按两候选 × 八动画 × 21 帧共 336/336 通过，无空帧、裁切或触边；但明确
`deployable=false`、`production_runtime_ready_slots=[]`。仍完全缺少 13 个 EvoLink 生产附件：
`torso_core`、四裙片、远肩饰前/后、远/近上臂袖、远/近前臂手、远/近小腿靴一体。头脸、
前发和双大腿仍是研究件，因此“缺 13 个”不是“其余已可发布”。拆件线应在用户追加躯干额度
并取得整套真实附件后再继续；在此之前，Hybrid 完整关键姿势仍是可交付主线。

拆分原则不是“骨越多越高级”，而是只有在一个关节确实需要相对旋转、切换前后层序或产生
惯性时才拆。完整头脸与中央前发合并可避免最敏感的脸—刘海—眼镜叠缝；小腿与靴合并可
绕开踝端隐藏像素。每个实际 attachment 仍可使用局部网格和 2–4 根骨权重。

现有腿部复盘还说明，合并前必须先重建 setup pose 的真实骨点：左小腿绘画方向尚有
`0018/0022/builder` 冲突，右小腿三者轴线约为 `68.2° / 74.2° / 57.68°`。不能把旧
preview 的硬编码轴直接升级成生产真值，再用 Prompt 强迫美术迁就。正确顺序是先锁定最终
中立姿势和骨点，再把 `0078` 左大腿、`0083` 右大腿、`0088` 左小腿、`0100` 右小腿等
静态候选放入组合灰盒，最后决定保留膝关节还是合并整腿。

已生成的微件不删除：静态合格者可作为语义组重绘参考、局部纹理或方案研究证据；错误方向、
错误身份或真实可见光幕的图不得进入生产 atlas，也不得未经标注继续喂给模型。

## 7. 方案对比

| 维度 | 原版 atlas 换皮 | 整身单网格 | 21 微件拆分 | 约 8 语义组拆分 | 完整关键姿势 Hybrid |
| --- | --- | --- | --- | --- | --- |
| 兼容原游戏 | 最高 | 高 | 高 | 高 | 高 |
| 身份稳定 | 中 | 高 | 低到中 | 中到高 | 高 |
| 关节接缝 | 原网格决定 | 无 | 最多 | 较少 | 无人物接缝 |
| 大动作剪影 | 弱 | 弱到中 | 强 | 强 | 最强 |
| 隐藏像素要求 | 由原图限制 | 无法生成 | 极高 | 中 | 低 |
| AI 生成成本 | 中 | 低 | 最高 | 中 | 中 |
| Spine 绑定成本 | 低 | 中 | 最高 | 高 | 中 |
| 动画连续性风险 | 战士味 | 橡皮布 | 穿帮/叠亮 | 关节穿帮 | 姿势切换跳变 |
| 死亡表现 | 弱 | 卷曲 | 需专用死亡 | 仍需专用死亡 | 专用整身死亡最合适 |
| 当前角色适配 | 仅探路 | 回退基线 | 研究资产 | 并行候选 | **主线推荐** |

## 8. 生产流水线

### 8.1 立项

1. 从源码、场景、原骨骼和当前候选建立消费契约；
2. 指定该图是完整姿势、语义组内的具体 attachment，还是独立 VFX；
3. 锁定屏幕方向、画布、锚点、层序、最大动作和相邻附件；
4. 先做低成本灰盒或既有素材绑定测试，确认架构真的会消费这张图；
5. 再按 Prompt 手册进行付费生成。

### 8.2 生成与静态验收

- 每次只生成一个完整对象或一个完整姿势；
- 保存原图、逐字 Prompt、脱敏 request、task；失败也保留；
- 用真实 SourceOver 合成到黑、白、游戏蓝灰和实际相邻层；
- 检查身份、方向、异物、裁切、实际显示尺寸、`A>0/16/64/127` 边界和像素岛；
- 不使用阈值、色键、蒙版、程序抠图或 Alpha 清边；
- 静态通过不等于可以进入运行时，状态必须写清为“静态候选”。

### 8.3 Spine 接入

- 先在隔离候选目录构建，不覆盖运行时；
- atlas 页按语义隔离：neutral / action poses / death / VFX，避免改一个动作重排全部；
- 保留八动画、slot、event、transition mix、Spine 版本和默认 skin 门禁；
- 原子切换必须检查同帧人物层数量、前后 bbox、关键锚点和事件精确时刻；
- 头发、裙摆和蓝蝶使用辅助骨时，根部应稳定，末端才分配更高权重。

### 8.4 渲染与真机验收

离线固定使用游戏实际 Spine GDExtension、Windows Vulkan、相同画布、`.28` 和制作比例。
每个动画至少采样 0/25/50/75/100%，强动作另采：

- 预备极值；
- attachment 切换前一帧、切换帧和后一帧；
- VFX event 精确帧；
- 命中峰值；
- 回弹峰值；
- 死亡接地、回弹和最终静止。

自动检查非空、触边、动画变化、slot/event、同帧人物数、锚点和日志。人工检查身份、受力、
轮廓、接缝、头发/裙摆惯性、脚底、VFX 起点及普攻/重击可辨识度。最终必须由用户在真实
游戏尺寸观看；“机器通过”和维护者自行觉得自然都不能取代该门禁。

## 9. 失败处理与回退

- 资源加载、atlas、slot/event 或场景错误：停止该候选，不在坏包上继续测试；
- 单图方向错：回到消费契约，不用同一错误 Prompt 继续抽卡；
- 静态图好但切换跳：优先对齐锚点、比例、轮廓和切换时刻，不重画 Alpha；
- 关节穿帮：提高隐藏搭接、减少旋转、合并相邻 attachment 或改为完整关键姿势；
- 大动作仍像橡皮布：增加独立关键姿势，不继续无上限加骨；
- 八次生成仍不合格：保留整组、写清最佳候选和失败分类，停止并交用户评审；
- 主线候选未完成时，保留当前已验证运行时作为回退，不把研究候选直接部署。

## 10. 目前的实施优先级

1. 冻结已经部署的 JSON、五页 PNG、30 文件清单和三件套哈希；不得用任一分项整包覆盖正式 V3；
2. 保留 legacy 精确回退包，并继续把 `.import/.uid` 当 Godot cache 而非逻辑运行时；
3. 用自然地图有效位置补验 `map_marker`，不要用调试跳房的无效当前位置得出图片结论；
4. 用双客户端补验多人手势；在此之前仍只能标记资源/离线消费者通过；
5. 只有基础 rest-site consumer 顺序修复或游戏版本改变后再复验 `light_off`；没有证据支持重生
   篝火人物或修改 Alpha；
6. 拆件研究线保留证据但不阻塞已部署 Hybrid 主线。躯干组没有用户追加额度前禁止第 9 次生成。

这样从最小端到端闭环开始，避免先花完所有图的额度，最后才发现 slot、方向或切换架构不对。

## 11. 维护规则

本文件是活文档。发生以下任一情况，完成任务前必须同步更新：

- 新增、删除或合并 Spine 部件、slot、bone 或完整姿势；
- 改变 `.28`、70% 制作比例、画布、锚点、动画时长、event 或 transition mix；
- 某候选从概念、静态通过、离线集成通过、真机通过之间改变状态；
- 用户真机反馈推翻自动检查或既有人工结论；
- Prompt 生成结果改变了对微件、语义组拆分或完整姿势可行性的判断；
- 新的 Vulkan 指标、接触表或游戏日志证明现方案有回归。

更新必须同时说明：变更的证据、旧结论为何被推翻、当前推荐、回退方案和下一道门禁。
不得静默把历史失败改写成从未发生，也不得把离线候选写成已部署生产版。

## 12. 修订记录

- 2026-08-28：建立长期方案文档；复盘原版 atlas 换皮、私有整身网格、层级 whole mesh、
  临时 UV split mesh 与 21 微件生成；确立完整关键姿势 Hybrid 主线和约 8 语义组并行研究线；
  纳入 `.28`、70%、八动画、slot/event、死亡 61 px 跳变和三候选 Vulkan 对照证据。
- 2026-08-28：完成 V3 `attack_peak` 隔离候选；记录 `0104` 采用、`0105` 归档不采用、整画布
  固定变换、`.08–.20` 原子切换、商店边界重置、掌心 VFX `(210,30)` 以及 14 帧分层 Vulkan
  证据；保留 `.20` recovery 跳变作为真机门禁，不冒充已部署通过。
- 2026-08-28：完成 `attack_heavy_peak` 独立消费者；记录 0106 byte-identical source、
  `.12–.32` 原子窗口、`.02s` mix、14/14 分层 Vulkan、脚底 `-4/-2 px`、切入质心约
  `17.27 px` 与掌心 VFX `(210,30)`；升级为离线集成通过但保留真机审美门禁。
- 2026-08-28：新增 `cast_peak` 0107 静态候选；记录三底 SourceOver 对直显光场误判的纠正、
  与 neutral 一致的固定尺度，以及 `.10` sigil、`.25` 眼火/人物切换、`.60` 人物复位、
  `1.222000026` 清理契约；随后以 14/14 精确 Vulkan 升级为离线集成通过，记录旧 `(40,40)`
  眼火悬空与 cast `(194,-292)` / neutral `(72,-282)` 双锚点修正。
- 2026-08-28：完成 V3 独立死亡消费者；冻结 `0029` 美术源，通过预切换低位收缩、`1.05s`
  原子 slot 切换、`0s` hurt→die mix 与接地回弹，把旧 `61px` 实体横跳降至 `16px`、底边跳变
  降至 `1px`，16/16 精确 Windows Vulkan 帧通过；状态仍限定为隔离离线集成，等待多页整合
  和用户真机验收。
- 2026-08-28：完成 `0030` 蓝蝶语义组件的独立 Vulkan 消费者；确认单一刚性 region、实心
  pivot、死亡解绑和商店随机 seek，16/16 帧通过；用相邻头发 A/B 证据纠正旧层序，生产顺序
  固定为 `后发 → 头脸 → 蓝蝶 → 前发`，仍等待统一全身骨架整合。
- 2026-08-28：完成屏幕左/角色远侧/解剖右臂两件制灰盒；冻结
  `far_upper_arm + far_forearm_hand`、躯干肩盖遮挡、无独立腕与远手不持有 slash 的契约，
  八动画 40/40 Windows Vulkan 帧通过；明确仅结构通过，真实可发布远臂美术仍缺失。
- 2026-08-28：完成 `0031` 单张 weighted 后发消费者；冻结 49 顶点/72 三角与末梢权重上限，
  八动画 168/168 Vulkan 帧及商店随机相位通过；不再付费拆发束，并明确旧接触表的蝶饰层序
  已被专项 A/B 纠正、死亡倒地阶段仍待总装验收。
- 2026-08-28：完成 neutral 网格 `hurt` 与 neutral/merchant 基线专项；记录受伤轮廓收缩、
  transition mix、连续重触发风险、19/19 neutral 时刻和商店九相位清理；明确 70% 当前高度仍约
  为原战士 `1.389×`，保留真机布局门禁。
- 2026-08-28：加入严格五页/30 文件运行时契约，默认 legacy 不变；固化头脸、近臂、双腿、
  躯干裙摆和 336/336 总装灰盒结论，列出 13 个完全缺失的生产附件。交接时最终统一候选尚未
  创建、正式 runtime 未修改、游戏未部署。
- 2026-08-28：创建隔离 `hybrid_v3_final`；冻结“cast 结构基线 + neutral slots + hurt bones +
  death 两 bone”的最小语义合并和五个逐字节页供体。总装器双跑确定性、专项 validator 的 73 次
  runtime 检查及八动画 84 个精确 Windows Vulkan 时刻通过；正式 legacy runtime 未修改，连续
  `AnimationState` / `NIroncladVfx`、临时 30 文件、完整不部署 PCK 与真机仍保留为下一道门禁。
- 2026-08-28：连续 25 序列首次证明 Spine slot 无需批量 t0 reset；真实 `NIroncladVfx` 8 场景
  则精确复现唯一 `cast→cast` 残眼。以 `cast clear_vfx@0` 做隔离 A/B 并修复，最终候选重跑
  25/25 序列、104/104 checkpoint、50/50 t0/mix+ε、真实 consumer 8/8 与 merchant 10/10；
  记录旧结论、纠正证据及 C# consumer/standalone merchant 的不同保真边界。
- 2026-08-29：统一 wrapper 在全新隔离目录复跑总装、严格 30 文件与四套 Spine、84/84 exact、
  25/25 连续序列（104/104 checkpoint、50/50 t0/mix+ε）、真实 `NIroncladVfx` 8/8 和 merchant
  10/10；rest-site、character-select、UI 与多人资源也完成后置离线回归。完整 no-deploy PCK
  复跑为 0 warning / 0 error、101 entries，正式 runtime 与两套游戏 mods 哈希树均未变化；同时
  用 `UseSharedCompilation=false` 修复 `Start-Process -Wait` 被 Roslyn server 拖延的问题。只剩明确
  授权后的正式发布和真机，legacy runtime 未修改。
- 2026-08-29：在完整回退备份后把同一 `hybrid_v3_final` 发布为正式五页/30 文件 runtime，部署
  DLL/json/PCK 并通过 PCK 与 Vulkan 初始化日志。真机覆盖选人、idle/low-health、attack/heavy/
  cast/hurt/die、普通/伪商人视觉及三幕篝火；死亡缩略图的“双人”判断被用户与放大/slot/scene
  证据纠正为单人两腿。保留自然地图 marker、多人端到端和 `light_off` consumer 顺序三项缺口；
  没有新付费生成、Alpha 或 atlas 像素变化。
- 2026-08-30：独立白绮角色的静态占位加载路径由共享 `CharacterAssetProfile` 取代；记录
  Ironclad replacement 与 Vivhite 共用当前 V3 五页 combat atlas、私有骨骼/网格/动作及
  merchant/rest/select/UI/multiplayer 资源，而 Vivhite 保留自身 ID、卡池、生命/能量和独立
  energy counter。默认布局已改为 `v3-five-page`，禁止回退旧静态场景或 legacy 单页。本次没有
  生成或修改创意素材；源码接入已有，完整构建、部署和双角色真机消费仍是下一道门禁。
