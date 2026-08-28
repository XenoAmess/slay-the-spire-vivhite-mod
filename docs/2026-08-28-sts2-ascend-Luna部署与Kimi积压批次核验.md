# sts2-ascend Luna 部署与 Kimi 积压批次核验

日期：2026-08-28

## 结论

- 当前生产 Brain 的 `boot_head=d5623658`，该提交包含三级复盘链提交 `ced1c279`；实际加载顺序为 GLM-5.3-Flash、GPT-5.6-Luna、Kimi K3。Luna 已作为第二优先级部署并加载，但截至本次核验，当前长复盘仍由 GLM 执行，尚不能把“已部署”误报成“已观察到生产 Luna fallback 成功”。
- Kimi 的 `every_runs=5` 只是普通新任务的最低启动门槛，不是固定批大小。worker 先按 `min(review_queue_max, max_runs_in_packet)` 选择全部可运行且兼容的积压项；当前两个上限均为 100。因此启动 Kimi 时若已有 12、42 或 100 局普通积压，会一次把完整批次交给 Kimi，而不是只取 5 局。
- Kimi 启动后才完成的新局无法倒灌进已经冻结的 prompt，会留给下一批。积压超过 100 局时仍按用户已设定的 100 局上限分批。
- 失败包 `retry_group`、已经产生模型工作的 sticky runner/model 事务以及尚在冷却的项保持各自事务边界，不与普通积压强行混合；这用于保留失败现场和模型亲和性，不是 5 局截断。

## 代码链路

1. `brain/config.json` 中 Kimi 配置 `every_runs=5`，同时 `review_queue_max=100`、`max_runs_in_packet=100`。
2. `brain/llm_review.py::_worker_loop_body` 以两个 100 上限的较小值计算选批容量。
3. `brain/llm_review.py::_select_review_batch` 收集全部兼容、已到执行时间的普通队列项，直到上述容量。
4. `brain/llm_review.py::_run_batch_review` 只用 `every_runs` 判断是否已达到启动门槛，随后把完整 `runs_list` 原样传给 `run_review(batch_runs=...)`。

## 回归验证

在 `tests/test_review_runners.py` 增加两项回归：

- 12 局普通积压交给 Kimi 时，断言 `batch_runs == [1..12]`，同时 `every == 5`。
- 容量为 100 时，scheduler 必须一次选中 100 个普通队列项。

定向测试：

```text
C:\Python314\python.exe -B -m unittest sts2-ascend.tests.test_review_runners
27 tests, OK
```

本次没有修改生产 Brain 代码或配置，不需要热重启，Brain 断流为 0。
