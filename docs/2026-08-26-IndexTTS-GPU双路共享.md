# IndexTTS-2.5 双路 GPU 共享改造

日期：2026-08-26

## 目标与结论

目标是让白绮碎碎念和复盘播报都使用 IndexTTS，并把分钟级 CPU 合成改为 GPU 合成。

结论不是“IndexTTS 不能用 GTX 1060”，而是原生产链没有接到 CUDA，且官方整模布局无法在
6GB 显存上与 Vulkan 游戏稳定共存。本次采用一个常驻 GPU owner、固定参考条件缓存、参考编码器
卸载和 GPT-only FP16，最终让两个入口共享同一模型并串行合成。

## 原链路的四个断点

1. `brain/config.json` 实际配置为 `tts_mode=edge`、`clone_engine=moss`。
2. `tts/quipper.py` 即使选择 IndexTTS，仍硬编码 `device="cpu"`。
3. `speaker.py` 中名为 IndexTTS 的结论函数实际启动 MOSS-Nano。
4. `speak_once.py` 默认也是 MOSS；旧 Index 分支未从生产代码收到 CUDA device。

更危险的是，旧设计会让碎碎念进程和一次性结论进程各自构造模型；标志文件只防同时播放，
不防同时加载/合成。GTX 1060 上第二份模型没有物理显存空间。

## 上游与硬件研究

- 本机：GTX 1060 6GB、compute capability 6.1、PyTorch `2.8.0+cu128`；CUDA 实际矩阵运算通过。
- IndexTTS-2.5 上游会把 GPT、W2V-BERT、semantic codec、S2Mel、CAMPPlus、BigVGAN 全部放到
  同一 device；所谓 `low_vram` 只对长文本分段，并不卸载模型。见
  [官方 `infer_v2_5.py`](https://github.com/index-tts/index-tts/blob/main/indextts/infer_v2_5.py)。
- 官方低显存 PR 的 4090 实测里，BF16 且不加载 QwenEmotion 仍约需 5.48GB；6GB cap 勉强运行，
  5GB OOM。它没有给同卡游戏留下余量。见
  [IndexTTS PR #755](https://github.com/index-tts/index-tts/pull/755)。
- 本机 `torch.cuda.is_bf16_supported()` 默认返回 True，但
  `including_emulation=False` 返回 False。GTX 1060 没有原生 BF16，软件模拟虽省权重内存却更慢。
- FlashAttention-2 只支持 Ampere/Ada/Hopper，Pascal 不在支持范围，见
  [FlashAttention CUDA 支持矩阵](https://github.com/Dao-AILab/flash-attention#nvidia-cuda-support)。
  因此必须关闭 `use_accel`；同理关闭 BigVGAN 自定义 CUDA kernel、DeepSpeed 和 torch.compile。
- `empty_cache()` 只能归还 allocator 中未占用的缓存，不能释放仍有活引用的模型，见
  [PyTorch 文档](https://docs.pytorch.org/docs/2.8/generated/torch.cuda.memory.empty_cache.html)。
  所以必须先真正删除/移走参考模型，再调用它给 Vulkan 腾空间。

## 实测对照

| 路径 | 条件 | 初始化/常驻 | 短句结果 |
| --- | --- | --- | --- |
| 官方式 FP32 整模 CUDA | 游戏关闭 | 初始化 108.2s；PyTorch allocated/reserved 6630/6754MiB | 已依赖 WDDM 共享显存，不适合同卡游戏 |
| 官方式 BF16 整模 CUDA | 游戏随后启动 | allocated/reserved 5063/5150MiB；整卡 5939MiB | 180s 仍只到 25 步扩散的第 7 步，GPU 100% 严重分页 |
| 本次 FP32 参考卸载 | 游戏关闭 | 首次 41.4s，缓存命中 27.5s；4339/4454MiB | 6 字 12.9s，但推理后整卡高水位 5839MiB，游戏余量仍小 |
| 本次 GPT FP16 + 其余 FP32 | 游戏关闭 | 缓存命中 24.0s；2791/2916MiB | 6 字 12.7s；峰值 3174MiB |
| 同上 | Vulkan 游戏运行 | 启动 37.4s；游戏+owner 整卡约 4496MiB | 11 字 19.8s，游戏持续响应；自动碎碎念 8 字 16.7s |
| 同上，复盘入口 | Vulkan 游戏运行 | 与碎碎念共享同一 owner | 65 字 38.6s；峰值 3287MiB |

FP16 是本地低显存兼容扩展，不是 IndexTTS-2.5 上游公开参数。只把 `UnifiedVoice/GPT` 转成
FP16；GPT 输出到后半链的关键边界是整数 codes，因此 semantic codec、S2Mel/CFM 和 BigVGAN
继续保持 FP32。此卡上短句实测没有变慢，但不能外推到所有 Pascal 卡或所有文本。

## 实现结构

```text
quipper.py（唯一长驻进程、唯一模型）
  ├─ IndexTTSGpuEngine
  │    ├─ CPU 构造，避免官方构造期整模挤爆 6GB
  │    ├─ 首次：W2V-BERT + CAMPPlus 分阶段上 GPU，计算固定白绮参考条件
  │    ├─ 缓存 5 个参考张量到本地 `.pt`
  │    ├─ 删除约 2.2GB 的 W2V-BERT/CAMPPlus
  │    └─ GPT(FP16) + codec/S2Mel/BigVGAN(FP32) 上 cuda:0
  └─ PriorityQueue（合成和播放均严格串行）
       ├─ priority 0：复盘结论
       ├─ priority 20：复盘直播句
       └─ priority 50：碎碎念

speaker.py（轻量 Python，无 torch）
  └─ localhost HTTP + session_id → 同一 PriorityQueue
```

服务只监听 `127.0.0.1`，并校验 `STS2_ASCEND_SESSION_ID`。`speak_once.py` 也只提交给现有
owner；服务不存在时明确失败，不会偷偷拉第二份模型或回退 CPU。

固定参考缓存包含：

- `cache_spk_cond`
- `cache_s2mel_style`
- `cache_s2mel_prompt`
- `cache_mel`
- `cache_emo_cond`

缓存 key 包含参考 WAV、配置、推理源码和关键 checkpoint 元信息。参考文件或模型变化会自动重算。
原版同一参考会重复跑三次 W2V；这里 speaker/emotion 共用一次结果。

## 复盘积压与生命周期

- IndexTTS 无法实时追上大模型 token 流，复盘直播队列限制为 8 句，满时丢最旧一半。
- 收到 `LIVE-END` 后清掉过时正文，等待当前句结束，立即提交人工生成的短结论。
- quipper 使用既有 session/lock/stop 协议，没有增加第二个长驻进程。
- `Stop-Agent.ps1` 的 `voice_clone_busy.flag` owner 已同步改为 `quipper.py`。
- 每次 WAV 已回到 CPU 后执行 `empty_cache()`，把无主激活缓存还给 Vulkan；活模型仍常驻。
- owner 强制 stdout/stderr 为 UTF-8，避免上游规范化后打印 emoji 时触发 GBK 编码异常。

## 验证

- `py -3 -m py_compile`：新增/修改的 TTS 与 agent 文件全部通过。
- `unittest`：覆盖 health、session 隔离、HTTP 提交、四并发调用严格串行；3 项通过。
- 真实 CUDA：manual、quip、review 三种 source 均完成合成与播放。
- 同卡实测：Vulkan 游戏运行中完成碎碎念与复盘长句，游戏进程保持 `Responding=True`。
- 统一启停：`Start-Agent.ps1 -SkipDeploy` 到 `Stack ready`，TTS health 返回
  `cuda:0/fp16`；`Stop-Agent.ps1` 能让 owner 协作退出并清理标志。

## 注意事项

1. 不要把 precision 改为 BF16；1060 的 BF16 是模拟路径，实测极慢。
2. 不要启用 `use_accel`、`use_torch_compile` 或自定义 CUDA kernel；Pascal/Windows 不满足支持条件。
3. 不要让 speaker/one-shot 自己 import 并构造 IndexTTS；6GB 卡只能存在一个 owner。
4. 更换参考音频后首次启动会重新生成缓存，启动时间会增加约十余秒。
5. 游戏资源场景可能继续抬高 Vulkan 显存；应关注 `tts_quipper.log` 的每句峰值。若以后出现持续增长，
   需要在无第二实例的前提下做 owner 自重建，不能同时保留新旧模型。
