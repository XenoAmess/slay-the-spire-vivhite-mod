# 2026-08-28 STS2-Agent fork 主线同步 v0.9.1

## 结论

上游 `CharTyr/STS2-Agent` 的 PR #46、#47、#48、#49 已全部合并，并在
`upstream/main` 的 `9f99876` 发布 `v0.9.1`。我方 fork 原 `main` 的生产功能均已进入
官方主线，不再存在需要单独保留的未上游代码。

我方 fork 的本地、`origin/main` 与 `upstream/main` 现均精确指向：

```text
9f99876d8dd11416aec13273956902d58a231ccb  Release v0.9.1
```

## 比对结果

同步前，我方 `origin/main` 为 `cdd723d`，与官方主线发生历史分叉：我方独有 4 个提交，
上游独有 11 个提交。这 4 个提交是 #48/#49 合并前为真机部署而建立的线性整合提交，
并非上游缺失的新功能。

最终代码树差异只有 9 个文件，内容均来自上游正式合并或 `v0.9.1` 发布整理：

- 版本号与 changelog 更新；
- #47 的卡屏截图；
- Reflection 测试的 warning 抑制写法与测试项目条目排序；
- 多人大厅回归脚本对 bundle selection 的处理。

核心 `GameStateService`、Crystal Sphere、unlock confirm、AoE 药水等生产实现没有我方独占差异。

## 同步方式

由于两条 `main` 历史已分叉，普通 merge 会永久保留一层重复整合历史，无法让 fork 回到
官方干净基线。因此采用以下可恢复流程：

1. 将旧 `cdd723d` 推送到远端备份分支
   `backup/main-before-upstream-sync-20260828`；
2. 将本地 `main` 移到 `upstream/main`；
3. 验证官方树；
4. 使用带旧 SHA 的 `--force-with-lease` 更新 `origin/main`，防止覆盖并发远端更新；
5. 恢复本地 `main` 对 `origin/main` 的跟踪。

同步后 `origin/main...upstream/main` 的左右提交计数为 `0 0`，工作区干净。旧主线仍可从
备份分支完整恢复。

## 验证

- C# 自定义测试：48 项通过；
- MCP Python `unittest`：29 项通过；
- `STS2AIAgent.csproj` Release 构建：0 warning、0 error；
- 本地 `main`、本地 `origin/main`、本地 `upstream/main` 与 GitHub `origin/main` 均为
  `9f99876`。

## 维护要点

- 已上游的 fork 修复如果曾被 cherry-pick 到 fork `main`，不能只看提交数判断是否仍有私有代码，
  必须同时比较最终树和 patch 等价性。
- 精确重置公开主线前要保存远端备份，并用带期望旧 SHA 的 `--force-with-lease`，不要使用无条件
  force push。
- 后续新修复仍应从最新官方 `main` 拉独立分支提交 PR；只有确有尚未上游的生产差异时，fork
  `main` 才需要领先官方。
