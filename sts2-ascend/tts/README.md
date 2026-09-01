# ASCEND-VOICE — 语音与音色服务

tts/ 是 sts2-ascend 的可选语音层：它把复盘直播流、白绮的短评和本场最终结论转换成音频。语音进程不参与策略决策，也不拥有游戏状态；语音不可用时，Brain 仍应继续游玩和保存证据。

## 运行边界

- 生产启动由 ../scripts/Start-Agent.ps1 统一完成。Brain 会按 brain/config.json 的 llm.tts_mode 按需拉起朗读器；不要在已有 session 中手工再启动一份 owner。
- 所有常驻进程继承 STS2_ASCEND_SESSION_ID、STS2_ASCEND_RUNTIME_DIR、STS2_ASCEND_STOP_FILE，并响应统一 Stop-Agent.ps1 的停止哨兵。不要手工删除 knowledge/ 或 .runtime/ 下的锁、flag、流文件和日志。
- IndexTTS 服务只监听本机 127.0.0.1（默认端口 17952）。它不是公开 HTTP 服务，也不会替代游戏 API。
- CUDA/模型/Edge 环境不可用时，克隆音色会记录原因并跳过或按兼容模式降级；不得为了“有声音”再加载第二份 GPU 模型、强行回退到未验收的 CPU 路径，或阻塞游戏动作链。
- 语音脚本不负责开播。当前保持下播时不要调用任何 Bilibili 开播脚本；停止语音请使用统一栈停止入口。

## 数据流

~~~text
Brain/llm_review
  ├─ review_live.stream ──► edge_speaker.py ──► Edge TTS / SAPI（实时正文）
  └─ quip / LIVE-END 结论 ─► quipper.py ─► IndexTTS-2.5 GPU owner ─► winsound
                                      ▲
                                      └─ indextts_client.py (/health,/speak,/handoff)
~~~

默认配置是 llm.tts_mode=edge、tts.clone_engine=indextts、tts.device=cuda:0。实时复盘正文与白绮短评可以并行出声，但 IndexTTS 模型在一个 quipper.py 进程内严格串行；最终结论先全部预合成再按顺序播放，避免半句失败或乱序。

## 组件索引

| 文件 | 用途 | 是否通常手工启动 |
| --- | --- | --- |
| [speaker.py](speaker.py) | 标准库兼容朗读器；sapi、indextts、hybrid 三种模式，读取 review_live.stream。 | 仅诊断 |
| [edge_speaker.py](edge_speaker.py) | Edge TTS 三路预取实时正文；Edge 失败时该句回退 Windows SAPI，结论转交共享 owner。 | 由复盘链按需拉起 |
| [quipper.py](quipper.py) | 唯一 IndexTTS-2.5 CUDA owner；按战况生成白绮短评并接收结论。 | 由 Brain 启动 |
| [indextts_gpu.py](indextts_gpu.py) | IndexTTS GPU 引擎、优先级队列和本地 HTTP 服务实现；无独立生产入口。 | 否 |
| [indextts_client.py](indextts_client.py) | 无第三方依赖的本地客户端；校验 session、代码 epoch 后调用 owner。 | 作为库导入 |
| [nano_speaker.py](nano_speaker.py) | MOSS-TTS-Nano 兼容朗读器，允许滞后读完整场流；需要 uv 与本地模型。 | 由配置按需拉起 |
| [speak_once.py](speak_once.py) | 把一个 UTF-8 文本文件提交给已存在的 IndexTTS owner；绝不另载模型。 | 可手工诊断 |
| [owner_epoch.py](owner_epoch.py) | 对 owner 的三个实现文件计算稳定代码代次，防止旧进程误接新请求。 | 作为库导入 |

### 兼容模式

speaker.py 支持以下模式（命令行参数或 TTS_MODE 环境变量）：

- sapi：Windows 内置语音，零模型、低延迟。
- indextts：全部提交给现有 IndexTTS owner；owner 不可用时退出，不回退 CPU。
- hybrid：直播正文走 SAPI，结论走共享 IndexTTS owner。

复盘链另外支持 edge、nano 和 off；这些值由 llm_review.py 负责选择启动命令，详见上级 sts2-ascend README 的“语音朗读（ASCEND-VOICE）”一节。

## 常用命令

命令默认从 sts2-ascend/ 目录执行；生产训练仍应优先使用统一入口。

~~~powershell
# 推荐：连同游戏、runner、Brain 一起启动（不触碰直播姬）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-Agent.ps1

# SAPI 试听，不读取或修改在线知识
py -3 tts/speaker.py --test

# 兼容模式手动跟读（仅在没有其它朗读器时）
py -3 tts/speaker.py sapi

# 向当前 owner 发送一个 UTF-8 文本文件；owner 不存在时以退出码 1 失败
py -3 tts/speak_once.py C:\path\to\sentence.txt

# Edge 旁路环境（通常由复盘链自动执行）
uv run --no-project --with edge-tts --with imageio-ffmpeg python tts/edge_speaker.py

# MOSS-Nano 旁路环境（可滞后播放；需要本地模型）
uv run --no-project --with onnxruntime --with sentencepiece --with torch --with torchaudio python tts/nano_speaker.py

# IndexTTS owner（需要 third_party/index-tts/checkpoints/config.yaml）
uv run --project third_party/index-tts python tts/quipper.py
~~~

上面的 quipper.py、edge_speaker.py 和 nano_speaker.py 会竞争 session-scoped 单实例锁；如果统一栈已经运行，重复命令通常会安全退出，但不要把这种退出误报为服务故障。完整停止使用：

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Stop-Agent.ps1
~~~

## 配置、接口与音量

brain/config.json 的 tts 节控制 owner：

| 键 | 当前默认值 | 说明 |
| --- | --- | --- |
| clone_engine | indextts | 克隆音色后端选择 |
| device | cuda:0 | GPU 设备；生产 owner 要求 CUDA |
| precision | fp16 | GPT 部分精度；低显存路径保持 codec/声码器 FP32 |
| worker_port | 17952 | 本地 owner HTTP 端口 |
| startup_timeout_sec | 240 | Brain 等待 owner /health 的上限 |
| request_timeout_sec | 900 | 单次 /speak 请求上限 |

除只读的 `/health` 外，owner 的写入请求必须绑定当前 session 和 owner_code_epoch：

- GET /health：返回 ready、session、PID 创建身份、epoch、设备、队列和当前播放阶段。
- POST /speak：提交 source=conclusion|review|manual|quip 的文本；输入体和文本长度有界。
- POST /handoff：代码 epoch 变化时停止接收新任务，排空旧队列后交接；不得用它强杀进程。

所有朗读器共享 knowledge/voice_volume.json。Ctrl+Shift+Alt+↑/↓ 调整音量（±10%），Ctrl+Shift+Alt+M 切换静音；状态由脚本原子更新，HUD 会显示当前值。

## 文件与保全

以下是运行时输入/产物，不应手工提交或作为游戏素材使用：

- knowledge/review_live.stream、review_conclusion.txt、tts_*.log、owner/voice lock 与 flag；由 Brain/生命周期协议维护。
- reference_voice*.wav、*.mp3、临时 index_gpu_*.wav 和 voice_tmp/；仓库 .gitignore 已排除。参考音色的生成/备份由 ../scripts/prepare_reference_voice.py 管理。
- third_party/index-tts/、third_party/MOSS-TTS-Nano/；模型体积大且按本机环境准备，不纳入仓库发布物。

不要把在线复盘流、合成音频或模型缓存复制进 knowledge 学习统计，也不要用音频文件的存在来证明 Brain 正在实际游玩。真实游玩证据仍以游戏 /state、state_version、applied 回执和驾驶舱心跳为准。

## 诊断与测试

~~~powershell
# 只测试 TTS 路由和队列，不需要启动游戏；-B 避免生成 pyc
py -3 -B -m unittest discover -s .\tests -p "test_tts_*.py" -v
py -3 -B -m unittest .\tests\test_indextts_gpu_service.py -v

# 查看当前 owner（只读；owner 不存在时返回 None）
py -3 -c "import sys; sys.path.insert(0, 'tts'); import indextts_client; print(indextts_client.health())"
~~~

GPU 基准与模型完整性检查属于专项实验，不是训练栈就绪证明。遇到无声，先看 knowledge/tts_speaker.log、knowledge/tts_quipper.log、knowledge/brain.log，再确认 GET http://127.0.0.1:17952/health 的 session/epoch；不要重启游戏或删除锁文件作为第一步。若需要改 owner 代码，先跑上述回归，再用统一 Stop/Start 完成交接。

## 相关文档

- [sts2-ascend/README.md](../README.md)：全栈启停、训练验收和直播失败关闭边界。
- [brain/README.md](../brain/README.md)：Brain 与 TTS 的职责边界。
- [scripts/README.md](../scripts/README.md)：生命周期脚本、UAC 与停止协议。
- [IndexTTS GPU 双路共享](../../docs/2026-08-26-IndexTTS-GPU双路共享.md)：GPU owner 设计与实测。
- [IndexTTS 复盘结论分句](../../docs/2026-08-27-IndexTTS复盘结论细粒度分句与生成上限.md)：结论分句和输入上限。
