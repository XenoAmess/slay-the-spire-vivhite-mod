# semantic_head_face：头脸三分支研究候选

本构建器把已归档的 `0031` 后发、`0044/0045` 头脸、`0033` 前刘海和 `0030` 蓝蝶
放入一个隔离 consumer graph，生成三个可比较分支：

```text
head0044_rigid    # 0044 头脸 + 刚性前/后发
head0045_rigid    # 0045 头脸 + 刚性前/后发
head0045_weighted # 0045 头脸 + weighted 前/后发（当前 preferred next gate）
```

它的基础 split mesh 只是动作/锚点灰盒，不是生产美术。所有分支都声明
`research_only_not_publishable`，不得复制到正式 skins。

## 层序与消费者契约

候选渲染层序是 `back hair → torso → head/face → front hair → butterfly → foreground
arm`；总装纠正后的实际集成顺序是 `back hair → torso → head/face → butterfly → front
hair → foreground arm`。`eye_attach_slot` 绑定头部本地 `vivhite_eye_anchor`，但
EyeFire 真场景 composite 尚未由此候选单独证明。三分支都要求八动画、`relaxed_loop`
两端显式四层 reset、`die` 原子 detach，并拒绝旧的合并 head slot。

## 构建与验证

```powershell
& $godot --headless --path .\tools\art `
  --script res://candidates/semantic_head_face/build_semantic_head_face_candidate.gd -- `
  build-semantic-head-face
& $godot --headless --path .\Vivhite `
  --script (Resolve-Path .\tools\art\candidates\semantic_head_face\validate_semantic_head_face_candidate.gd)
```

支持 builder 的 `--output-root PATH`；默认输出为
`Vivhite/tools/candidates/semantic_head_face/<variant>/`，每个分支含自己的
`.spjson/.spatlas/.tres` 与 `candidate.json`。validator 是无网络静态 gate，检查来源
哈希、2048² page/1024² 源画布、atlas region、骨/slot/眼锚点和 runtime block。

## 不能误读的结果

validator 输出的“3 variants / 40 frames each”是结构与历史 Vulkan 证据覆盖，不是
完整 EyeSlot/EyeFire 或真机资格。若要推进，下一道门是 head0045_weighted 与接受的
torso、后发、蓝蝶在 `.28` 实际场景下的 SourceOver/关节复核；禁止用旧接触表或程序
抠图补齐缺失层。

