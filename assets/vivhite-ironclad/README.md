# 白绮战士换皮美术源

本目录保存原版战士 → 白绮视觉替换的原始参考、模型生成结果、制作源和历史失败
样本，全部受 Git 跟踪，不是临时缓存。

## 当前目录

- `references/`：用户提供的两张干净根参考；
- `prompts/evolink/`：准备提交给 EvoLink 的 Prompt；
- `generated/evolink-paid/`：每次付费调用的追加式原图、完整 Prompt 和去密请求参数；
- `generated/anchor/`：从已验收付费原图复制出的当前身份锚点；
- `generated/native-alpha-experiment/`：EvoLink 原生透明能力的早期实验副本；
- `legacy-contaminated/`：棋盘格、绿幕、程序抠图及其全部衍生链，只作历史保留。

`legacy-contaminated/` 中的内容禁止作为模型参考、绑定母版、atlas 输入或运行时
素材。旧 `custom/` 190-region / 10-page 流程已经连同产物移入该目录，因为它既
继承棋盘格血缘，也把新图塞回原战士 Alpha 和姿势。

## 唯一生成路径

所有透明图片只允许调用 EvoLink：

```text
POST https://api.evolink.ai/v1/images/generations
model: gpt-image-2
background: transparent
```

使用 `tools/art/evolink_transparent_image.py` 发起请求。每个语义素材最多 8 次
尝试；达到用途要求立即停止。任何付费结果即使失败或不用，也必须留在
`generated/evolink-paid/`，不得覆盖或删除。API Key 仅通过环境变量或隐藏输入
进入当前进程，绝不写入仓库。

## 角色硬约束

白绮是银白短发、紫色瞳孔、金色圆框眼镜的华丽、可爱而冷淡的魔法少女。
她是空手施法者：没有剑、法杖、魔杖、法书、盾、手持法球或任何其他武器，
也不使用白绫。战斗特效是紫蓝水晶光、魔法弧和蓝蝶。

战士替换必须使用白绮自己的骨骼、网格、权重和魔法少女动作。原战士素材只能
用于理解运行时动画名、事件名和场景锚点契约，不能再提供姿势、网格或 Alpha。

## 当前安全状态

旧 runtime PNG 已从 `Vivhite/Vivhite/skins/ironclad/` 移出，换皮保持 fail-closed。
只有新的 combat/merchant、rest-site、character-select 私有 rig 与九张 UI 全部
从干净 EvoLink 链重建、离线验收并完整发布后，才允许重新启用角色替换。

## 发布边界

仓库保留所有有价值的原始生成图、失败尝试和制作源。Mod PCK 只允许包含最终
`Vivhite/Vivhite/skins/ironclad/` 运行时资源和 Godot 导入产物，不包含
`assets/`、`tools/`、`.work/`、API 请求记录或历史污染目录。
