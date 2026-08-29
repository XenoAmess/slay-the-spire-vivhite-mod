# sts2-ascend GLM 与 Luna 实机对照评测方案

## 目标

在生产三级优先链已经上线后，用同一批真实失败局、同一冻结代码、同一 Prompt 字节和同一生产验收器，对以下两个执行者做项目内实机比较：

- OpenCode：opencode-go/glm-5.3-flash，variant=max
- Codex：gpt-5.6-luna，reasoning=max，auto-review

本评测回答四件事：代码闭环质量、证据准确性、执行性能、token/实际额度代价。它不是通用模型排行榜；三个样本只支持 sts2-ascend 当前复盘任务上的方向性结论。

## 三个冻结案例

| Case | baseline | runs | 历史主线 | 历史 GLM 墙钟/token |
| --- | --- | ---: | --- | ---: |
| A | b84e6c244522a49862b35dc47188da02330f49d2 | 843–855 | 联合防守复核使用滞后火力 | 38分12秒 / 135429 |
| B | 3d75901176b4f2c7403c818ff4514053c7c2dbcc | 856–876 | 深输出缺口下复制件密度 | 1时47分 / 144971 |
| C | be2e4680345862d522132454b971f0b1a8c4c946 | 877–891 | 非致死竞速回合保留有效格挡 | 2时49分 / 196793 |

历史 GLM 结果只作为第三份参考，不向参评模型泄露，也不当作金标准。Case B 历史报告有 end_turn、可打防御牌和重复计数误差；Case C 历史补丁没有证明能覆盖“竞速锁被联合复核翻回后再抽到格挡”的真实状态机。这些会进入隐藏验收和盲评。

## 评测器契约

入口：sts2-ascend/scripts/review_model_eval.py。

- 评测不读取生产队列，不领取在线任务，不导入当前 Brain 实例，也不提交模型结果。
- baseline 通过 Git archive 建立无 remote、无共享 index/object 的隔离仓。
- Prompt 只在对应历史 baseline clone 内由该版本 build_prompt 确定性重建；provenance 明确 historical_byte_original=false。
- Windows checkout 在取文件前固定 core.autocrlf=false、core.eol=lf，避免原生知识 manifest 因 CRLF 漂移而失效。
- 两个候选必须复用同一 prompt bundle；同时校验 baseline、batch_runs、run_evidence_scope、Prompt 内首个 JSON packet 和 SHA-256。
- 六次任务显式传同一个 validator commit。验收器从该 commit 冻结 brain 快照，避免 Brain 中途提交让 A/B 使用不同门禁。
- 历史执行契约（已于 2026-08-30 被下述契约取代）：Codex auto-review 只传 approve-for-me；非 auto-review 才显式传 workspace-write sandbox，以避免当时 CLI 互斥参数导致模型启动前失败。
- provider 输出使用二进制 read1(8192)；每个原始 chunk 先记心跳，再写盘并 flush，之后用独立增量 UTF-8 decoder 解析 JSONL。首 raw byte、首完整事件、首模型工作和最大 raw 静默分别统计。
- 总超时 8 小时；连续 30 分钟无原始输出触发 watchdog。15–30 分钟静默在报告中记警告。
- selfcheck 后用 force-stage 捕获全部工作树，包括 ignored/cache/pyc/在线路径；all_changes.patch 保存完整现场。
- 宿主注入的 review_prompt_latest.md 单列为 harness_owned_paths，不冒充模型改动。
- 当前生产 deny-only 分类把模型文件分成 accepted、transient、online、rejected；只有 accepted 精确导出 changes.patch。无 accepted 或空 patch 不得标记可合入。
- execution_success、production_acceptance、blind_review 三层独立，禁止再用一个 success 字段混淆“CLI 跑完”“可合入”和“能力更好”。
- 初始化、provider、自检、patch 或 validator 失败都写正式 manifest；原始事件、stderr、时间戳 transcript、完整 sandbox、全量 patch、精确 patch和证据哈希全部保留。

### 2026-08-30 Luna 宿主执行契约纠正

生产环境已捕获 Codex 原生工具在一次变更中同时报告“隔离 clone 路径”与“真实仓绝对路径”的外写证据。这证明工作目录和 `-C` 只能约束相对路径，`auto-review` / `--approve-for-me` 不是隔离边界；因此上述历史契约已终止使用。独立 evaluator 的 Luna 宿主现固定遵守：

- 评测规格仍必须声明 `spec.sandbox=workspace-write`；这是 provider 适配与任务亲和性的语义契约，不再直接映射为 CLI `--sandbox` 参数。
- 实际 builder 固定为 `codex -a never exec`，并传入 `--ignore-user-config`，防止用户级信任配置扩大评测权限。
- builder 内联 `luna_commit` 权限 profile：继承 `:workspace`，只将 workspace root 内的 `.git` 重开为可写，同时固定 `network=false`；该 profile 作为 `default_permissions`。
- 命令只允许一个 `-C`，且必须指向本次 isolated repository。命令中不得出现 `--sandbox`、`--approve-for-me`、`--add-dir` 或任何 bypass / yolo 类选项。
- 这是同时满足“只写隔离 clone”与“Luna 在 clone 内自行 Git 提交”的兼容方案；不改变评测顺序、Prompt、任务策略、产物分类或接收口径。

## 已完成验证

- 定向单元测试：18/18 通过。
- Codex auto-review 与 sandbox 互斥、非 auto-review sandbox、原始半行输出、raw stall watchdog、ignored/cache 全现场、宿主 Prompt 排除、固定 validator revision、畸形 provenance 正式失败、三层状态均有回归。
- Case A 使用同一 baseline 和 843–855 连续重建两次：
  - Prompt SHA-256 均为 f69e138ae4a19612835cd7f3e7e0539b57d6319fd191fdd2eb0ee9a6908b9576
  - bytes 均为 448508
  - exact 13、missing 0、direct evidence 13
  - native snapshot available=true
  - v0.111.0 / 41cef1ea；596 cards、107 monsters、299 relics、66 potions；validation 24 pass、0 fail

## 实机顺序与盲评

为抵消先后顺序影响：

- Case A：GLM 后 Luna
- Case B：Luna 后 GLM
- Case C：GLM 后 Luna

每个 Case 生成身份盲化的 A/B 包，隐藏模型、provider、耗时、token、Git 作者和原始 transcript。三名互不沟通的评审分别按 100 分制评分：

- 正确性 30
- 证据 20
- 架构 20
- 测试 15
- 可观测与回退 10
- 报告 5

单案差值小于 5 分记平局。只有赢下至少 2/3、三案平均优势至少 5 分且无 INVALID/灾难性回归，才写“能力明显更好”。

性能数据在质量评分锁定后揭示。OpenCode 与 Codex 的 token/套餐口径不同；无法从本机授权证明的人民币或美元实际扣费必须写 N/A，不能拿公开 API 单价冒充本次 Codex 套餐账单。

## 直播风险判断

三级链代码热更新已经在 72.58 秒内完成，Brain 断流低于两分钟；当前生产 Brain 已加载并健康运行。

评测器本身是离线工具，修改和提交不需要重启 Brain，直播中也可安全部署。六次 max 实机任务虽然不触碰游戏、生产队列或 Brain 生命周期，但会长时间占用模型 CLI、CPU、磁盘和网络，也会污染严格性能对比。因此：

- 功能上线不必等下播。
- 为获得干净性能数据并降低直播资源抖动，完整六次对照优先在下播后运行。
- 本轮用户已下播，可直接执行。
- 生产 Brain 仍保持运行；评测失败只保留离线结果，不触发生产提交或重启。

## 后续产物

最终结果写入：

docs/2026-08-28-GLM-5.3-Flash与GPT-5.6-Luna实机对照评审.md

其中必须给出每案盲评分、类别差、胜平负、墙钟、首 raw byte、首模型工作、最大静默、token、失败/重试、生产门禁结果，以及“谁更好、差距多少、Luna 是否达到二级 fallback 标准”的明确结论。
