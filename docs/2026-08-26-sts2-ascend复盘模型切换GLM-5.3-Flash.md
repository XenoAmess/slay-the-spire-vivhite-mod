# sts2-ascend 复盘模型切换：GLM-5.3-Flash

## 变更

OpenCode 当前模型清单登记的 ID 是 `opencode-go/glm-5.3-flash`；用户指定的
`GLM-5.3-Flash (2x usage) OpenCode Go · max` 在项目配置中对应：

```text
opencode-go/glm-5.3-flash@max
```

其中 `@max` 会被复盘路由解析为 OpenCode 的 `--variant max`，模型探测仍以
`opencode models` 返回的基础 ID 为准。

活动配置 `brain/config.json` 与 `llm_review.py` 的默认优先链已统一为这一条目；
兜底模型仍保留为 `kimi-for-coding/k3`，只有 GLM 条目不可用或处于失败冷却时才使用。
复盘悬浮窗演示元数据和配置回归测试也已同步。

## 证据边界

历史 `knowledge` 运行日志、旧复盘文档以及 `code_backups/review_salvage/` 中的
ox-alpha 字样是过去实际运行的证据，不做替换或重写。它们不参与当前模型路由；
新的复盘请求只读取当前配置中的 GLM 条目。

## 校验

本机 `opencode models` 可见 `opencode-go/glm-5.3-flash`，配置解析得到
`opencode-go/glm-5.3-flash@max`，并通过复盘配置、队列、Git 安全和持久化核心测试。
