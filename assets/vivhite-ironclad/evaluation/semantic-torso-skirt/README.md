# 躯干 + 裙摆语义组离线消费审计

日期：2026-08-28  
状态：`contract_frozen_existing_art_rejected_not_publishable`  
结论：现有 `0054` 只能作为失败证据，不能进入生产 atlas；本目录不包含可部署美术。

## 消费契约证据

- `0054` 是一张单独的躯干状对象，不是 atlas、spritesheet 或多图拼接；`0018` 与 `0022` 都是单帧完整人物母版。
- `IroncladReplacementAssets.cs` 替换整套战斗 Spine skeleton data，`combat.tscn` 只在场景层以 `0.28` 缩放它，因此躯干、裙摆、手臂的前后关系完全由 Spine slot/draw-order 负责，C# 不会替单张躯干修复遮挡。
- 被审计的历史 split skeleton 中，固定 slot 索引为 `far arm=13 < torso=19 < skirt=21 < near arm=25`，且没有 `drawOrder` 动画。这个顺序会把裙摆画在躯干尖形前摆之上。
- 原版 atlas 独立提供 `bod`、`hips`、`belt`、上下臂和左右肩甲区域；游戏消费者并不要求把袖口、肩饰、躯干和裙层烘成一个对象。
- 灰盒使用 Spine `4.2.43`，实际场景缩放 `0.28`。当前诊断骨点为 pelvis `(-72.3333,665.6736)`、torso lower 相对 `(0,150.3105)`、torso upper 相对 `(0,119.2118)`、skirt center 相对 pelvis `(0,119.2118)`；这些坐标只复现当前灰盒，不得未经统一 neutral rig 冻结就升级成生产真值。

## 为什么 `0054` 生产失败

`0054` 的静态 Alpha 已通过；失败原因不是棋盘格、背景或低 Alpha 光晕，而是语义内容和动态消费不兼容：

1. `0048` 的上游 Prompt 明确要求把双侧白色肩盖/袖口和屏幕左侧蓝金肩饰固定在同一个躯干对象中；`0052`、`0054` 又把这个错误结构当成“正确单件”继续复刻。它无法让远臂从肩饰前后层之间穿过，也会与独立上臂重复。
2. `0054` 下缘画入了白色下腰/裙状层，不只是短而隐藏的腰插片；独立裙摆消费者会再次绘制相同职责。
3. 等实体高度拟合后，`0054` 宽度为 `217.41` world px，而冻结的 `0018` 目标为 `250.58` world px，窄约 `13.24%`。胸/腰宽比为 `0.884`，而 `0018` 为 `0.995`、`0022` 为 `1.022`；这不是一次统一缩放可以修正的误差。
4. setup pose 已能看到烘入肩盖与独立手臂重叠；在躯干相对裙摆 `+46°/-46°` 的两个极值，近侧袖口会与手臂分离，腰部会和裙根错开或相交，并暴露缺少隐藏搭接像素的问题。
5. 上述缺陷在真实 `0.28` 接触表中仍可辨认，并非只在 `0.70` 检查放大下出现。

因此，`0054`、从它复制出来的候选页以及 `0018` 的邻接裁样都只能留作灰盒证据；真实可发布附件数量为 **0**。

## 冻结的下一版生产规格

同一套服装色彩和接缝设计可以共享参考，但最终必须形成以下独立运行时附件：

- `torso_core`：包含高领、胸口镂空与紫晶、白色胸甲片、海军蓝束身衣和可见的海军蓝尖形前摆；不得包含双臂、双侧白袖/肩盖、蓝金肩饰或任何白裙层。pivot 为统一 neutral setup 的腰中心，远臂在它后方、近臂在它前方。
- `skirt_back`、`skirt_side_far`、`skirt_center_front`、`skirt_side_near`：四个协调设计但彼此独立的 attachment。每片上缘必须向上延伸并藏在 `torso_core` 后面，横向也要与相邻裙片保留实体搭接；关节切口不得烘入辉光。骨架使用 pelvis root 与 center/near/far 惯性子骨，两条大腿均在所有裙片后方。
- `far_shoulder_ornament_back` 与 `far_shoulder_ornament_front`：蓝金远侧肩饰拆成前后两片，让 `far_upper_arm_and_sleeve` 在两片之间穿过。
- 白色袖口/肩盖不属于躯干组；分别归 `far_upper_arm_and_sleeve` 与 `near_upper_arm_and_sleeve`，随各自上臂链旋转。

冻结的后到前层序：

1. `far_shoulder_ornament_back`
2. `far_upper_arm_and_sleeve`
3. `left_and_right_thighs`
4. `skirt_back`
5. `skirt_side_far`
6. `skirt_center_front`
7. `skirt_side_near`
8. `torso_core_with_visible_navy_front_hem`
9. `far_shoulder_ornament_front`
10. `near_upper_arm_and_sleeve`

## 下一次付费前门禁

- 躯干语义的 `0048–0055` 已经用满 8/8 次；`0055` 没有返回 PNG。没有用户针对该语义素材追加额度时，不得调用第九次，也不得把新名称 `torso_core` 当作重置额度的借口。
- 用户追加额度后，必须从干净身份/服装参考与冻结的 neutral consumer contract 重新起链；不得继续把 `0052` 或 `0054` 作为图像参考，因为它们已经烘入本规格明确排除的袖口、肩饰和白裙层。
- 每次付费请求只画一个具体 attachment。四个裙片共享同一套比例、配色、腰线和重叠规格，但分别输出；肩饰前后片也分别输出。所有请求继续遵守 EvoLink `gpt-image-2` + `background: transparent`、追加式归档和单素材串行尝试规则。
- 付费前必须先在统一 neutral rig 中冻结 torso 腰 pivot、pelvis/skirt 子骨、肩/肘 pivot、四裙片的目标 world rect 与隐藏搭接区，并用纯灰盒通过固定层序；不得让 Prompt 去猜骨点。
- 生成后必须先做黑/白/实际蓝灰底 SourceOver 与真实相邻附件 setup 合成；随后在 Windows Vulkan 下检查 setup、躯干相对裙摆 `+46°/-46°`、近/远上臂极值以及真实 `0.28` 尺寸。任何接缝、重复袖口、裙片穿插或需要 draw-order 临时补救的候选都不得提升。

回退始终是已验证的 Hybrid 整身动作主线；该语义灰盒不会修改正式 runtime。

## 本次离线复验

执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\art\candidates\semantic_torso_skirt\Invoke-SemanticTorsoSkirtPreview.ps1 -OutputDir .work\semantic-torso-skirt-evidence-recheck
```

结果：静态 fail-closed 门禁通过，随后以 Godot 4.5.1、游戏 Spine GDExtension、Windows Vulkan 在隐藏离屏窗口渲染 setup 与两个最大扭转姿势。三种姿势在 `480x420 @ 0.28` 和 `700x720 @ 0.70` 下均非空、未触边；检查放大的顺时针极值顶部只余 1 px，因此只能作为诊断图，不能反推生产安全画布。没有启动游戏、部署 Mod、调用 EvoLink 或操作直播。

## 精确文件与 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `0054/output.png` / 候选 `vivhite_semantic_torso_0054.png` | `70a293dd908af44aee0d9921cd5e4ac4d542105ba6717d8233705ec1a4a7cc35` |
| `0018/output.png` / 候选 `vivhite_semantic_context_0018.png` | `86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1` |
| `0022/output.png`（仅方向参考） | `488e74758164dab0702ec6f943e02d23d9561caef29320275f698cb0000e232e` |
| `Vivhite/tools/candidates/semantic_torso_skirt/candidate.json` | `2094592f2cd9b336c384690e9365db76830d62361c37d9f25684667986653493` |
| `Vivhite/tools/candidates/semantic_torso_skirt/vivhite_semantic_torso_skirt.spjson` | `7547c5bf16709da964c401d810159c29a03563a427c5df87fe94652591d1a6ff` |
| `Vivhite/tools/candidates/semantic_torso_skirt/vivhite_semantic_torso_skirt.spatlas` | `188bffc2efec00f8ee3d7be6420ddfc0882768022add818c6786f6e8d6966657` |
| `Vivhite/tools/candidates/semantic_torso_skirt/vivhite_semantic_torso_skirt_skeleton_data.tres` | `e9746910a5b25a2ee4c281ca6fb14ae7cc3f1f35d1d7d2903ab947458af9b085` |
| `contact-sheet-actual-0.28.png` | `b7147a5a27065c30c0853bdf3f3aa5475ec8a5204598328c2a41d257b86a3616` |
| `contact-sheet-inspection-0.70.png` | `97d05a5d2790829a280f6de43592a9406b39ac04aa849a62420404ff85c11274` |
| `summary.json` | `b0d9ab01344be79a36a3d7822b450296a28af90e7addc60febc65cff9dea77eb` |

接触表与 summary 是本次全新输出目录的结果；候选图仍与付费原图逐字节一致，未经过抠图、Alpha 修补或其他像素后处理。
