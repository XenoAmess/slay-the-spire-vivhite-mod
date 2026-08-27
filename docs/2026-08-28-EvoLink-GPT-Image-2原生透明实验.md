# EvoLink GPT Image 2 原生透明实验

## 结论

EvoLink 的 `gpt-image-2` 路由已真实接受 `background: "transparent"`，并返回
带 Alpha 通道的 PNG。这条路径从 2026-08-28 起是仓库唯一允许的透明素材生成
方式；不保留绿幕、色键、传统抠图或其他生成服务作为备用方案。

本轮先生成白绮正面全身身份母版候选。所有付费尝试都追加保存在
`assets/vivhite-ironclad/generated/evolink-paid/2026-08-28/`，每次同时保留原始 PNG、
逐字 Prompt 和去除秘密后的实际请求参数；即使不采用也不删除或覆盖。

- 原始输出：
  `assets/vivhite-ironclad/generated/native-alpha-experiment/vivhite-master-front-gpt-image-2-alpha-v1.png`
- 原始提示词：
  `assets/vivhite-ironclad/generated/native-alpha-experiment/vivhite-master-front-v1.prompt.txt`
- 请求：`gpt-image-2`、`2:3`、`2K`、`quality=high`、
  `background=transparent`、两张仓库原始参考图、`n=1`。

EvoLink 当前公开请求结构没有 `output_format`；透明模式直接交付 PNG，因此仓库
客户端不发送臆造字段，而是在下载后检查 PNG 文件签名。

## 三次实验结果

视觉上，模型正确保持了银发、紫瞳、金色眼镜、蓝蝶、黑白礼服、冷淡可爱气质，
采用适合重新绑定的正面魔法少女姿势，且没有剑、法杖、魔杖或其他武器。

像素检查结果：

- 文件：PNG，RGBA8，`1680 × 2512`；
- 四角 Alpha：`0, 0, 0, 0`；
- `Alpha=0`：3,328,051 像素；
- `0<Alpha<255`：892,109 像素；
- `Alpha=255`：0 像素，最大 Alpha 为 254，人物主体采样约为 253；
- 非零 Alpha 包围盒：`(0, 0)–(1660, 2512)`；
- 微弱光晕在上、左、下边界仍有非零 Alpha。

这张图验证了“原生透明输出确实可用”，并作为第一次付费尝试保留在
`0001-master-front-halo-rejected/`。它的外光晕大且触边，因此不作为直接切割 Spine
身体部件的源图；这不是对“完整立绘可以有光晕”的否定，而是避免关节切片后形成矩形
光块、叠亮接缝和裁切。

第二次尝试保存在 `0002-master-front-clean-attempt/`。它同样是原生 RGBA PNG，四角
Alpha 为 0，身份特征和原始设定一致，边缘只出现极少量微弱非零像素。该图已接受为
**干净身份根/概念锚点**，并按原始字节复制到：

`assets/vivhite-ironclad/generated/anchor/vivhite-master-front-evolink-v1.png`

它可以用于保持后续姿势、服装和脸部一致，但不会被程序直接抠切成身体零件。其整体
柔光作为完整人物设计是允许的；真正用于 Spine 身体分件的后续源图仍需在提示和验收中
要求关节边缘清楚、无烘焙外光晕。

第三次纯文字尝试保存在 `0003-master-front-text-only/`。它是有效的原生透明备选，但
服装更华丽、成熟，偏离现有白绮设定，因此只作为归档备份，不取代第二次结果。

同一语义素材最多允许 8 次调整 Prompt 后重新生成。母图在第 2 次已达到用途要求，故在
第 3 次对照实验后停止，不为了用满配额继续付费。后续每个姿势、UI 或身体分件同样按
用途验收，合格即停；第 8 次仍不完美时接受其中最可用的版本并记录缺陷。

不得用程序收缩、阈值化、色键或清理这些输出的 Alpha。程序只在模型直接给出合格真
透明素材后做不改变创意内容的尺寸适配、切片和 atlas 打包。

## 工具与下载问题

`tools/art/evolink_transparent_image.py` 基于用户提供的异步请求脚本整理而来：

- 只使用 Python 标准库，不增加运行依赖；
- Key 来自 `EVOLINK_API_KEY` 或交互式隐藏输入；
- 支持用 `--task-id` 恢复已完成任务，避免重复生成和重复计费；
- 下载后拒收非 PNG 内容；
- 不记录完整 API 响应、授权头或临时签名 URL。

首次下载时，结果 CDN 拒绝了 Python 默认请求头并返回 403。给下载请求补上常规
浏览器 `User-Agent`、`Accept` 和 EvoLink `Referer` 后，从同一个任务成功取回，
没有创建第二个生成任务。

## 密钥安全

API Key 没有写入任何仓库文件。`.gitignore` 额外排除了常见本地凭据文件；提交前
还需扫描工作树和暂存区中的通用 `sk-...` 模式。若 Key 曾经出现在聊天记录中，
实验后仍建议在 EvoLink 控制台轮换。
