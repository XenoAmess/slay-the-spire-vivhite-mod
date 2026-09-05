# sts2-ascend Luna 最低优先级调整

## 背景与目标

用户要求将 `gpt-5.6-luna` 移到训练复盘模型链的最低优先级。调整前的生产顺序是
GLM → DeepSeek → Luna → Kimi；调整后为 GLM → DeepSeek → Kimi → Luna。

## 实现与语义

- `brain/config.json` 将 Kimi 调为第 3 级 `preferred`，保留常规新任务的 5 局合批门槛。
- Luna 调为第 4 级 `fallback`，保留 `max`、`approval=never` 和 `workspace-write` 执行契约。
- 调度器仍按 `priority` 升序解析新任务；已有失败包如果已开始模型工作，仍按原
  runner/model/variant/reasoning/审批/sandbox 亲和性重试，不重写运行中队列或学习记忆。

## 关键注意

仅交换 JSON 数组位置不够：如果 Kimi 继续标记为 `fallback`，失败冷却语义会使它反复占用第 3 级，令
Luna 无法作为真正的最后兜底。因此同步交换了 Kimi/Luna 的 `preferred`/`fallback` 来源语义，并用测试固定
“前两级冷却时先选 Kimi，不探测 Luna”。

## 运行边界

本次未停止或重启正在运行的训练栈，未修改 `.runtime/` 或 `knowledge/`。`load_llm_config()` 会在新批次解析前重读
静态配置；已绑定的重试仍以持久化亲和性为准。
