# sts2-ascend/tools — 离线工具与基准

本目录放置不属于生产决策循环的辅助工具：MOSS-TTS-Nano 性能基准、ONNX 元数据查看器，以及原生游戏知识快照流水线（[game-knowledge/](game-knowledge/)）。工具应当以显式输入/输出运行，不得被当作训练栈的第二个启动入口。

## 工具清单

| 文件/目录 | 用途 | 主要输入 | 主要输出/副作用 |
| --- | --- | --- | --- |
| [benchmark_moss_nano.py](benchmark_moss_nano.py) | 在同一进程加载一次 MOSS-Nano，连续合成两句并打印加载/合成耗时。 | third_party/MOSS-TTS-Nano/models、tts/reference_voice_15s.wav | third_party/MOSS-TTS-Nano/generated_audio/bench_*.wav（本地/忽略） |
| [benchmark_moss_cached_prompt.py](benchmark_moss_cached_prompt.py) | 先缓存参考音频 prompt codes，再测三句边际耗时和 RTF。 | 同上 | 终端统计；不写知识库 |
| [benchmark_moss_gpu.py](benchmark_moss_gpu.py) | 测试 ONNX Runtime 的 cuda、dml/directml 或 cpu provider；只在本进程调整 DLL 搜索路径。 | reference_voice_48k.wav、MOSS 模型、对应 Python 包 | 终端 provider/耗时统计；不改游戏或学习数据 |
| [dump_moss_onnx_metadata.py](dump_moss_onnx_metadata.py) | 递归打印 ONNX metadata 中的短标量和列表长度。 | 一个 metadata JSON（默认 MOSS 模型内文件） | stdout；只读 |
| [game-knowledge/](game-knowledge/) | 从 PCK、localization、运行中 Agent /data 和同版本 sts2.dll 建立版本隔离的原生事实快照。 | 明确的游戏目录/离线 response/mechanics 目录 | 显式 knowledge/game/<version>/ 输出；详见其 [README.md](game-knowledge/README.md) |

__pycache__/、模型目录和生成音频是本地构建产物；不要把它们误认为工具源码或发布素材。

## 运行基准

命令默认从 sts2-ascend/ 目录执行；从仓库根目录时给脚本补上 sts2-ascend/ 前缀。

~~~powershell
Set-Location G:\workspace\slay-the-spire-vivhite-mod\sts2-ascend

# MOSS-Nano：同一模型加载后合成两句
py -3 tools/benchmark_moss_nano.py

# 已缓存 prompt codes 的边际耗时/实时率
py -3 tools/benchmark_moss_cached_prompt.py

# provider 可选 cuda（默认）、dml/directml 或 cpu
py -3 tools/benchmark_moss_gpu.py cuda

# 只读查看默认或指定 metadata
py -3 tools/dump_moss_onnx_metadata.py
py -3 tools/dump_moss_onnx_metadata.py C:\path\to\tts_browser_onnx_meta.json
~~~

这些基准会加载本地模型并占用显存/CPU，可能生成较大的忽略文件；不要在训练对局或直播验收的关键窗口运行。它们的耗时结果不是“Brain 正在操作”的证据，也不替代真实 /state 与 applied 回执。

## 原生游戏知识入口

game-knowledge/ 是独立子项目，不要在本 README 重复其 schema 和版本契约。常用入口：

~~~powershell
Set-Location G:\workspace\slay-the-spire-vivhite-mod\sts2-ascend\tools\game-knowledge

# 查看当前 CLI（extract/runtime/mechanics/validate）
py -3 .\game_knowledge.py --help

# 离线单元/管线测试，不需要启动游戏或 Steam
py -3 -B -m unittest discover -s tests -p "test_*.py" -v
~~~

完整快照生成可能读取本机 SlayTheSpire2.pck、sts2.dll，或只读探测 127.0.0.1:8080–8084；写入只能落在显式 --output-root/--output-dir。它不会修改游戏、Steam、云存档、knowledge 学习统计或请求 UAC。发布/交付前必须运行 validator，并保留来源哈希；禁止手工编辑快照 JSONL 来“修”校验结果。

静态 mechanics 抽取器位于 [game-knowledge/GameKnowledge.Tool/](game-knowledge/GameKnowledge.Tool/)，使用 .NET 9 与 ICSharpCode.Decompiler；其构建和输入契约见 [GameKnowledge.Tool/README.md](game-knowledge/GameKnowledge.Tool/README.md)。

## 依赖与环境

- Python 3.10+；本机统一通过 py -3 选择已由 Start-Agent.ps1 预检过的解释器。
- MOSS 基准需要本地 third_party/MOSS-TTS-Nano/ 模型和相应 onnxruntime/numpy/音频依赖；benchmark_moss_gpu.py 的 provider 选择不能凭空安装或切换生产 TTS 配置。
- game-knowledge 的 Python 部分只用标准库；GameKnowledge.Tool 需要 .NET SDK 9，不需要 Godot 编辑器。
- 游戏目录、Steam 文件和云存档均为只读输入。工具不会自动点击原生模组确认、启动 GUI/UAC 或删除空间。

## 测试与故障处理

工具源码的回归优先使用对应子项目测试：

~~~powershell
# 原生知识流水线（该子项目的包根是 game-knowledge/，先切到它）
Set-Location G:\workspace\slay-the-spire-vivhite-mod\sts2-ascend\tools\game-knowledge
py -3 -B -m unittest discover -s tests -p "test_*.py" -v

# Brain/生命周期合同（工具若被生产脚本调用时一起验证）
Set-Location G:\workspace\slay-the-spire-vivhite-mod
py -3 -B -m unittest discover -s .\sts2-ascend\tests -p "test_start_agent_*.py" -v
~~~

若基准报模型缺失，先检查 third_party 是否按本机准备；不要复制模型到 Git 或修改 brain/config.json 作为临时绕过。若快照 validator 报版本/hash 不匹配，保留完整输出和来源证据，针对同一游戏版本重新生成；不要混用另一份 sts2.dll、PCK 或旧版本目录。

## 相关文档

- [sts2-ascend/README.md](../README.md)：训练栈、生命周期和知识层总览。
- [brain/README.md](../brain/README.md)：Brain 如何只读消费原生知识。
- [game-knowledge/README.md](game-knowledge/README.md)：快照 schema、CLI、校验和保全边界。
- [原生游戏知识提取](../../docs/2026-08-26-sts2原生游戏知识提取.md)：历史抽取记录。
