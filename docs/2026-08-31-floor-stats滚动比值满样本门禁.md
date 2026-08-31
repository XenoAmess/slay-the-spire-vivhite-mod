# floor_stats 滚动比值满样本门禁

## 问题

ASCEND-VISION 已在显示层等待白绮与战士各自收集满 20 局，但底层
`floor_stats` 过去只检查两侧滚动均值是否存在。因此白绮完成第 1 局后，
底层便会提前发布 `1/20` 对 `20/20` 的比值。

## 修复

比值现在仅在两个角色的 `recent.count` 都等于当前 `rolling_window` 时计算；
任一角色样本未满时，`rolling_mean_ratio` 与
`vivhite_to_ironclad_ratio` 均保持 `None`。滚动均值本身仍照常提供，便于
观察采样进度。

## 验证

- `0/20`：两个比值字段均为 `None`。
- `1/20`：滚动均值存在，但两个比值字段仍为 `None`。
- `20/20`：按两侧滚动均值正常计算比值。
- `test_profile_floor_stats`、`test_floor_stats` 与 `test_dashboard_viewer`
  合计 53 项通过。

本次没有执行生命周期操作、部署、提交或推送。
