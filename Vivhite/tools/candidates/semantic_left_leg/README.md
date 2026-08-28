# 白绮远侧腿语义组隔离研究候选

这是 `0078` 左大腿、`0088` 左小腿袜面、`0063` 左靴的只读组合灰盒。它不在正式
runtime 路径内，不会被 Mod 注册或发布；所有 PNG 都是原始 EvoLink RGBA 的刚性缩放、旋转
与 SourceOver 预览，没有创建蒙版、清理 Alpha 或修画。

## 已锁定的消费者事实

- split builder 与正式 custom 母版实际读取 `0018`；两者 SHA-256 同为
  `86ffd64a637d170e213879e72d986b707ee181d4812c8e3fb1eda4abfab98bd1`。
- `0022` 是另一张新 rig 视觉提案，没有源码消费者骨点，不能与 `0018` 的硬编码骨轴混用。
- 现有远侧腿 draw order 固定为 thigh(1) → lower(3) → foot(5)，没有 drawOrder 动画。
- 历史最大相对转角是 thigh `+58°`、knee `-88°`、ankle `+21°`。
- foot attachment 原点 `(485,1940)` 与真正踝旋转点 `(485,1840)` 相差 100 个母版像素。

## 灰盒结论

- `0078` 轴线相对 builder 大腿轴约差 `-4.6°`，可用于静态研究；`0088` 相对小腿轴只差
  约 `+0.34°`，方向本身不是当前失败点。
- `0063` 的实体宽高比与旧 foot UV 只差约 0.5%，但旧 UV 归一化 pivot 落不到新图真实靴口。
  `legacy_uv_setup` 保留这个断接；其余帧用人工量取的研究 pivot 让靴口接上，以便观察接缝。
- 当前 lower 在 thigh 前方，`0088` 的上端盖线会直接露在膝部；foot 在 lower 前方则确实能
  覆盖踝端。这证明旧 Prompt 关于“由大腿盖住小腿上端”的假设与消费者相反。
- `-88°` 膝弯是实质运动需求，膝关节不能删除；踝只有 `+21°`，独立靴 attachment 带来的
  接缝、pivot 歧义和三件比例漂移大于它的收益。

生产建议固定为：**保留膝关节，收敛成 `far_thigh + far_lower_leg_with_boot` 两个
attachment，删除独立踝 attachment**。新 lower-leg-with-boot 应包含真实隐藏膝搭接且置于
thigh 后方；当前三张图只保留为研究证据，不能直接进入 atlas。

接触表从左到右、从上到下依次为：旧 UV setup、物理靴口 setup、最大膝弯、最大踝弯、
死亡链组合极值。overlay 版中黄/粉/绿/紫分别表示髋、膝、真实踝 pivot、foot slot 原点。

## 复现

在仓库根目录用 Godot 4.5.1 运行：

```powershell
godot --path tools/art --display-driver windows --rendering-driver vulkan `
  --resolution 64x64 --position -32000,-32000 `
  --script tools/art/candidates/semantic_left_leg/build_semantic_left_leg_candidate.gd

godot --headless --path tools/art `
  --script tools/art/candidates/semantic_left_leg/validate_semantic_left_leg_candidate.gd
```

静态 gate 通过只表示研究证据完整；`validation.json` 必须继续保持
`production_gate_passed=false`，直到两件式新美术、Spine slot 和 Vulkan 极限姿势另行通过。
