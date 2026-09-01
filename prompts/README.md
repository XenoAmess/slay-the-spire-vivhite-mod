# Prompt 资料

`prompts/` 保存项目早期需求和任务边界的**人类可读种子文本**。它们帮助维护者理解
为什么会有白绮 Mod 和 `sts2-ascend` 自动游玩大脑，但不是运行时配置、模型凭据或可直接
执行的脚本。

| 文件 | 内容 | 当前用途 |
| --- | --- | --- |
| [`vivhite_mod_prompt.txt`](vivhite_mod_prompt.txt) | 白绮角色 Mod 的目标、RitsuLib、游戏路径、Vulkan 验收基线和探索要求 | 新建/审查 Mod 工作时的背景上下文；现行技术细节以 [`AGENTS.md`](../AGENTS.md) 和 [`Vivhite/README.md`](../Vivhite/README.md) 为准 |
| [`autoplay_agent_prompt.txt`](autoplay_agent_prompt.txt) | 自动游玩战士、分析局势并从对局学习的原始需求 | `sts2-ascend` 的历史需求来源；执行命令和安全门禁以 [`sts2-ascend/README.md`](../sts2-ascend/README.md) 为准 |

## 阅读和引用方式

两份文件均为 UTF-8 纯文本，可用任意编辑器查看：

```powershell
Get-Content -Encoding UTF8 .\prompts\vivhite_mod_prompt.txt
Get-Content -Encoding UTF8 .\prompts\autoplay_agent_prompt.txt
```

如果要把需求转成实现任务，请先核对事实源的优先级：

1. 根 [`AGENTS.md`](../AGENTS.md) 的当前规则、禁止事项和路径边界；
2. 对应子项目 README、代码和测试；
3. [`docs/`](../docs/README.md) 中带证据的日期报告；
4. 本目录的早期意图文本。

因此，提示词里出现的旧角色、旧路径或“可以自行探索”的措辞不能覆盖后来明确的约束，
例如：白绮必须使用自己的骨骼/网格，透明素材必须经 EvoLink 原生路径，训练和直播必须
通过统一生命周期入口，用户要求下播时不得自动开播。

## 编辑约定

- 可以补充背景、澄清已实现目标，但不要在这里写 API key、Steam 凭据、临时签名 URL、
  本机运行态 JSON 或任何个人隐私。
- 需求发生实质变化时，保留旧文本并在 [`docs/`](../docs/README.md) 写日期化决策/证据；
  不要静默覆盖导致历史无法追溯。
- 新的模型提示词、EvoLink 请求 Prompt 和候选素材契约应放在对应的追加式归档目录，
  并遵守 [`docs/白绮AI生成图Prompt工程手册.md`](../docs/白绮AI生成图Prompt工程手册.md)
  的八次尝试、原图留存、Alpha 验收和请求参数脱敏规则。
- 提示词文件不会被构建器自动打包进 PCK，也不会被 Brain 自动加载；若新增消费者，必须
  在对应 README、测试和根项目地图中明确声明。

