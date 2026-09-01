# `src/` 保留目录

当前仓库的可编译 Mod 源码位于 [`Vivhite/`](../Vivhite/)，自动游玩大脑位于
[`sts2-ascend/`](../sts2-ascend/)，因此 `src/` 目前没有参与任何解决方案或构建目标的
源文件。保留这个入口是为了给未来跨子项目的纯库代码、公共协议或生成器预留清晰边界。

## 约定

- 新代码放入这里前，必须同时把它加入明确的 `.csproj`/`.sln` 或 Python 包边界，并在根
  [`README.md`](../README.md) 和对应子项目 README 中说明依赖关系；仅把文件丢进 `src/`
  不会自动参与构建。
- 不要在这里复制 `Vivhite/Vivhite` 的 Godot 资源、运行时 PCK、`.runtime` 或
  `sts2-ascend/knowledge`。这些目录有各自的生命周期和验收规则。
- 目录本身不提供启动、部署、直播或 UAC 入口；任何新工具应拥有独立 README、无人工授权
  的可审计命令和对应测试。

