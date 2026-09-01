# 白绮（Vivhite）Ironclad 美术资产仓

这是白绮视觉资产的**可追溯源仓**，不是 Mod 的运行时目录。它保存干净参考、EvoLink 原图、候选构建、离线验收证据和历史失败样本；最终是否进入 `Vivhite/Vivhite/` 由代码消费契约、Alpha/SourceOver 检查和 Godot/Spine 验收共同决定。

![已验收 UI 素材示例](approved/ui/select.png)

## 快速导航

| 集合 | 内容 | 当前边界 |
| --- | --- | --- |
| [`references/`](references/README.md) | 用户提供的干净身份与脸部参考 | 只读参考，不直接打包 |
| [`prompts/`](prompts/README.md) | EvoLink Prompt 版本记录 | 逐字保存，不能代替请求归档 |
| [`generated/`](generated/README.md) | 生成原图、派生物和失败归档 | 追加式保存，默认不消费 |
| [`approved/`](approved/README.md) | 已通过静态素材门禁的 UI 文件 | 仍须由运行时契约决定是否部署 |
| [`custom/`](custom/README.md) | 供候选/运行时构建使用的源图 | 不是自动发布清单 |
| [`candidates/`](candidates/README.md) | 拆件和整身候选 | 明确 fail-closed，不得直接接入 |
| [`evaluation/`](evaluation/README.md) | Vulkan、Alpha、消费方和层序证据 | 证据通过不等于生产通过 |
| [`legacy-contaminated/`](legacy-contaminated/README.md) | 污染血缘的历史留档 | 永不作为新参考或运行时输入 |

各集合的 README 是索引和门禁说明；生成批次的叶目录沿用 [`generated/README.md`](generated/README.md) 的固定文件契约，不为每个瞬时检查目录复制一份说明。

## 资产生命周期

```text
references/ + prompts/
        │  （仅形成设定与请求，不产生运行时文件）
        ▼
generated/<provider>/<date>/<attempt>/
        │  原图 + Prompt + 脱敏请求参数 + 检查证据
        ├── rejected/discarded → generated/discarded/
        └── 通过 Alpha/视觉/消费契约 → custom/ 或 approved/
                                      │
                                      ▼
                             evaluation/（离线验收）
                                      │ 全部门禁通过后
                                      ▼
                         Vivhite/Vivhite/（运行时资源）
```

任何一步失败都保持失败关闭：不能用接触表、灰盒、旧原战士贴图或污染素材“补齐”下一步。

## 当前内容快照

- `approved/ui/` 有 5 张 UI 图：`icon`、`icon_outline`、`map_marker`、`select`、`select_locked`。
- `custom/character_select/sources/` 有选人英雄母源与魔法印记；`custom/combat/sources/` 有战斗整身、攻击/重击/施法峰值、死亡侧卧和魔法弧源图；`custom/combat/parts/normal/` 有后发和蓝蝶刚性部件；`custom/rest_site/sources/` 有休息点母源。
- `custom/ui/multiplayer/` 的 `point`、`rock`、`paper`、`scissors` 是用户于 2026-08-28 明确批准的封闭历史复用例外；仅允许逐字节进入该目录，不能扩展到其他污染素材。
- `candidates/split_mesh/combat/` 是拆件 + 骨链 + 整图落地的 Hybrid 预览候选，`candidate.json` 的 `deployable` 必须保持 `false`。
- `evaluation/` 中的报告保留每项的实际渲染驱动、Spine 版本、画布、帧哈希和生产结论；详见其索引，不把 `success=true` 自动解释为可发布。

## 透明素材与生成硬契约

所有需要透明背景的新生成、重绘或迁移只允许通过 EvoLink：

```text
POST https://api.evolink.ai/v1/images/generations
model: gpt-image-2
background: transparent
```

请求必须由 `tools/art/evolink_transparent_image.py`（或遵守同一契约的仓库工具）发起。每个语义素材最多 8 次付费尝试；每次都要在 [`generated/evolink-paid/`](generated/evolink-paid/README.md) 留下未经后处理的原图、逐字 Prompt 和去密实际参数。不得记录 API Key、Authorization 头或临时下载 URL，也不得覆盖、删除失败尝试。

Alpha 验收必须读取真实 RGBA 通道，并把素材 SourceOver 到黑、白和接近游戏场景的底色；需要部件拆分时还要合成真实相邻部件的 setup pose 与最大旋转。代码只能做不改变创意内容的尺寸适配、切片和 atlas 打包，不能用抠图、阈值、蒙版、色键或后处理制造/修补 Alpha。

## 角色与运行时边界

白绮固定为银发、紫瞳、金色圆框眼镜的魔法少女，空手施法，不使用剑、法杖、魔杖、法书、盾、手持法球或白绫。战士替换候选必须使用白绮自己的骨骼、网格、权重和姿势；原版战士素材只能提供动画名、事件名和场景锚点契约。

`Vivhite/Vivhite/skins/ironclad/` 的目录名是资源兼容契约，不代表把白绮贴图套到原版战士骨架，也不代表已注册 Ironclad 皮肤替换。当前正式代码保持替换 fail-closed；资产仓中的候选不能绕过 `IroncladReplacementAssets`、Spine atlas、场景和 manifest 的完整门禁。

## 维护与复核规则

1. 新增素材先判断它是单幅成品、单帧、atlas/spritesheet、tile sheet 还是多区域 PNG；同时读取相邻 atlas/Spine/场景元数据并追踪源码消费者。
2. 任何候选都必须标注 `research`、`preview`、`approved` 或 `runtime` 边界；没有明确生产结论的证据只能留在 `evaluation/`。
3. 生成原图、Prompt、请求参数、检查输出和哈希必须同批次保存；原图一旦归档不可静默替换。
4. Godot 的 `.import`、`.uid`、`.godot` 和临时日志不是验收证据，除非某份报告明确把它们列为审计对象，否则不要加入归档清单。
5. 发布前重新核对运行时资源、manifest、PCK 与素材哈希；`assets/`、`tools/`、`.work/`、请求记录和污染目录不得进入 PCK。

## 证据优先级

源码消费契约和真实 Godot/Spine Vulkan 结果优先于肉眼缩略图；专门的语义验收报告优先于旧设计笔记；运行时 manifest/PCK 检查优先于候选目录名称。发现路径、哈希或结论不一致时，先保留现场并标记 fail-closed，不要直接移动或覆盖图片。
