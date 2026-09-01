# art/tests

这里是 `tools/art` 的 Python 静态契约测试，不是游戏内测试，也不要求人工操作。
测试会导入发布器和角色资源路由代码，检查运行时布局、文件数量、默认 active
profile 与 legacy/V3 边界；不会启动 Godot、Steam、游戏或直播。

从仓库根目录运行：

```powershell
py -3 -B -m unittest discover -s .\tools\art\tests -p 'test_*.py' -v
```

约定：

- 失败时保留完整 traceback，不要修改测试来放宽生产门禁；
- 测试使用的 `.work` fixture 可以重建，但不应进入 PCK；
- 涉及真实 Spine 渲染、Alpha 合成或消费者尺寸的检查，应改跑
  [`candidates/`](../candidates/README.md) / [`compare/preview/`](../compare/preview/README.md)
  的 Godot Vulkan 验收，而不是在这里伪造通过。
