# tools — 构建、验收与发布工具箱

仓库级 `tools/` 放置不属于游戏 Mod 或 Brain 运行时的可复用工具。工具默认是只读验收或确定性打包；需要写文件的脚本会把输出限制在明确的仓库目录，并在各自 README 中说明。

## 导航

| 路径 | 作用 |
| --- | --- |
| [`art/`](art/README.md) | 原版素材提取、白绮透明素材/atlas 生产、候选评估、Spine 私有 rig 和离线验收。 |
| [`test/`](test/README.md) | `GameTest.psm1` 真机截屏/OCR/输入模块，以及 Vivhite PCK 只读门禁。 |
| [`workshop/`](workshop/README.md) | Workshop 预览图生成、描述/版本/哈希合同和 Steam 发布；上传器见其子目录 README。 |

### 相关但不在这里的工具

- [`../sts2-ascend/tools/`](../sts2-ascend/tools/README.md)：Brain 的游戏知识快照与 MOSS/TTS 诊断工具。
- [`../Vivhite/tools/`](../Vivhite/tools/README.md)：Mod 内部的五页皮肤、PCK 和候选资源验证器。
- [`../Vivhite.Tests/`](../Vivhite.Tests/README.md)：编译生产源并运行  C# 接受测试。

## 工具使用原则

1. 从仓库根目录执行，并使用 README 给出的参数；不要从 ignored clone 或游戏安装目录复制脚本运行。
2. 发布前按“生产源 → 构建三件套 → PCK/静态门禁 → 真机 → Workshop 物料”顺序验收。
3. `.work/`、`.tmp/`、`bin/`、`obj/` 和 Python 缓存是临时/构建产物，不提交；不要把它们当作缺失源码。
4. 工具不会替代 Steam/游戏原生确认，也不会为了无人值守而执行 UAC 或 GUI 点击。
