# semantic_right_arm：屏幕右 / 近侧手臂灰盒

本目录表示白绮朝屏幕右姿势中的**角色解剖左臂、屏幕右、近侧**。它只定义消费者
几何、骨链、pivot、draw order 和极限动作，使用彩色 capsule 灰盒，不生成、复制或
修补任何角色 Alpha；状态固定为 `executable-graybox-consumer-no-art`。

## 消费契约

`consumer-contract.json` 是事实源：近侧上臂、前臂/空手两段式 attachment，躯干盖住
肩端，固定 setup 与 hidden-overlap 预算，八个动画的动作/受伤/循环极限，以及
`slash_mesh`/`eye_attach_slot` 兼容 slot。屏幕坐标名称不能被误当作解剖左右，腕部
不应重新拆成独立生产件。

## 一键构建、验证、极限图

```powershell
& .\tools\art\candidates\semantic_right_arm\Invoke-SemanticRightArmGraybox.ps1
# 不需要渲染接触表时：
& .\tools\art\candidates\semantic_right_arm\Invoke-SemanticRightArmGraybox.ps1 -SkipRender
```

包装器会从 `Vivhite/local.props` 解析 Godot，依次执行 build、static validate，再以
隐藏 Vulkan 运行 `render-semantic-right-arm-extremes`；它不会触碰游戏或正式 skins。
分步命令中的 builder/validator/render 脚本均以 `--path tools/art` 运行，因为它们将
仓库根解析后把结果写到 `Vivhite/tools/candidates/semantic_right_arm/`；渲染图固定在
`.work/semantic-right-arm/extreme-poses.png`。

这套灰盒通过后仍没有可发布图；下一道门是独立远侧/近侧手臂的原生透明生成与真实
相邻 torso/skirt/hand SourceOver 验收。禁止把 capsule 图当素材输入。

