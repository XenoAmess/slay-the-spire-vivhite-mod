# Profile 与轮换重置归档的 Git 隔离

## 问题证据

根仓提交 `25a6f789` 是一次 Brain 在线 checkpoint，却同时提交并推送了
`sts2-ascend/knowledge/profile_reset_archives/vivhite/20260831T081050.489211Z/`
下的旧统计、7 份旧对局和旧复盘队列，合计约 10 万行。这些文件是统计重置事务的本地恢复现场，
其 manifest 和 SHA-256 用于恢复与审计，不属于新的在线学习状态，也不应成为模型复盘输入。

根因不是 checkpoint 使用了全仓 `git add`。`autogit.default_progress_paths()` 会递归发现嵌套
Knowledge store；旧的扫描剪枝没有排除 `profile_reset_archives`，于是归档中“`runs/` 与
`stats.json` 并存”的快照被误认成仍在运行的角色 profile。与此同时，这两个目录既没有 ignore
规则，也没有被 deny-only 分类器认定为运行恢复现场。

## 修复

- `profile_reset_archives` 与 `rotation_reset_archives` 现在属于显式的本地恢复目录集合。
- Knowledge store 自动发现会在这两个目录处剪枝，默认 checkpoint 不再返回其中任何 pathspec。
- 显式传给 `commit_progress_result()` 的归档路径或能覆盖归档的祖先 pathspec 会被拒绝，避免未来
  调用方重新扩大范围。
- deny-only review 分类将两类归档标记为 `online-runtime`，保留在取证现场但不进入 review patch。
- `sts2-ascend/.gitignore` 忽略两类归档。解除已有跟踪后，新归档及 checksum 继续保存在本机，
  普通 `git add` 不会重新纳入版本控制。

测试只在临时 Git 仓库中构造假归档，覆盖已跟踪归档被修改、显式 autogit pathspec、review
分类和 ignore 命中；不读取、修改、删除或覆盖真实归档。

## 已跟踪归档的后续解除跟踪

ignore 不会自动作用于已经存在于 HEAD 的文件。下一次根仓维护提交应在保留本地文件的前提下，
仅从 Git index 移除这两个目录：

```powershell
git rm -r --cached --ignore-unmatch -- `
  sts2-ascend/knowledge/profile_reset_archives `
  sts2-ascend/knowledge/rotation_reset_archives
```

必须保留 `--cached`；不得运行会删除工作树文件的 `git rm -r`。随后只把这批 staged deletion 与
本次 `.gitignore`、autogit、测试和文档放进同一个精确提交。提交前后分别通过归档 manifest
记录的 SHA-256 或 `Get-FileHash` 校验本地文件，且用下列命令确认新 HEAD 不再跟踪归档：

```powershell
git ls-tree -r --name-only HEAD -- `
  sts2-ascend/knowledge/profile_reset_archives `
  sts2-ascend/knowledge/rotation_reset_archives
git check-ignore -v --no-index -- `
  sts2-ascend/knowledge/profile_reset_archives `
  sts2-ascend/knowledge/rotation_reset_archives
```

本修复不改写 `25a6f789` 的历史；解除跟踪会以一个可审计的新提交完成。
