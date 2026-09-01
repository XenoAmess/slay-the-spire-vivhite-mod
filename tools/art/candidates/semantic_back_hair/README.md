# semantic_back_hair：0031 后发语义候选

本目录研究一张完整的 `0031` 后发 PNG 如何作为**一个** weighted mesh 位于 torso/neck
之后、head-face/front-hair/butterfly 之前。它是离线 research candidate，不修改正式
皮肤、不部署、不启动游戏，也不调用付费生图。

## 已冻结的消费事实

- 输入是 `1024×1024`、RGBA、四角透明的 EvoLink 原始输出；构建器把原图逐字节放到
  独立 atlas page，不裁切、不阈值、不抠 Alpha。
- 后发网格为 `7×7`（49 顶点）的 weighted cap；冠顶锁在 `vivhite_hair_back`，下半部
  只有受限惯性，避免整片头发随末端乱摆。邻接 head/face、front hair、butterfly
  仅用于验证 setup/最大旋转时的遮挡，不会被误宣称为本候选的输出。
- `relaxed_loop` 必须在 `0/12.000001s` 闭环；`die` 会按契约 detach 头部层。当前
  仍缺全身总装与真实游戏 composite 证据，不能提升为生产 slot。

## 构建与静态门禁

```powershell
& $godot --headless --path .\tools\art `
  --script res://candidates/semantic_back_hair/build_semantic_back_hair_candidate.gd -- `
  build-semantic-back-hair-candidate

& $godot --headless --path .\Vivhite `
  --script (Resolve-Path .\tools\art\candidates\semantic_back_hair\validate_semantic_back_hair_candidate.gd) -- `
  validate-semantic-back-hair-candidate
```

构建器/validator 都支持自定义候选根（详见脚本 `Usage`）；默认输出为
`Vivhite/tools/candidates/semantic_back_hair/`。输出含 `.spjson/.spatlas/.tres`、
`candidate.json`、Alpha/setup 接触表和只作邻接证据的 PNG。验证通过表示字节血缘、
Alpha、骨网格和层序契约一致，不表示可直接进入 runtime。

## 下一道门

若需要继续生成，必须先完成“头脸 + torso”真实邻接的实际尺寸 Vulkan 验收；只有
结构性失败才允许在该语义素材的剩余八次 EvoLink 配额内重试。`A=1` 稀疏像素或普通
查看器外观不是重试理由；原始图、Prompt、请求参数和每次失败都要追加保留。
