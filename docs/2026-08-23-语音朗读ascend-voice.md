# 2026-08-23 语音朗读（ASCEND-VOICE）：index-tts 克隆音色 + SAPI 混合方案

## 需求与调研结论

把复盘直播窗打印的内容用 index-tts 读出声。调研关键事实：

- **IndexTTS-2.5**（bilibili，0.8B，零样本克隆）：`uv sync` 自动装正确版本 Python+torch，
  与大脑 Python 3.14 完全隔离；模型走 ModelScope 国内镜像（23 项约 10 分钟）。
- **m4a 参考音频需转 WAV**：无系统 ffmpeg，用 `uv run --with imageio-ffmpeg` 临时拉起的
  内嵌 ffmpeg 解决（`reference_voice.m4a` → 24kHz 单声道 wav，另裁 15s 版加速条件编码）。
- **首次运行会下载小模型**：必须设 `HF_ENDPOINT=https://hf-mirror.com`，否则慢/卡死。

## 性能实测（i7-6700K + GTX 1060 6GB）

| 路径 | 结果 |
| --- | --- |
| GPU（与游戏争抢，显存 96% 占用） | 25+ 分钟/句未产出，**病态不可用** |
| CPU fp32 | 34 字 ≈ 6 分钟（≈10s/字），仅适合"每场复盘的结论段" |
| `use_accel=True` 加速引擎 | **无效**——依赖 flash-attention（纯 CUDA 库），CPU 上直接报错 |
| SAPI（Huihui/Zira） | 即时，零成本 |

结论：这台 2015-2016 年的硬件上，index-tts 实时逐句直播不可行；
hybrid 模式（SAPI 直播 + 克隆音色读结论）是当下最优解。
若要更自然的实时音色，应考虑云端 TTS（如 edge-tts），而非本地大模型。
- 因此采用**混合方案**：SAPI（Microsoft Huihui，系统自带 zh-CN 女声）实时朗读直播流；
  index-tts 克隆音色只在复盘结束时读结论段（后台合成几分钟无所谓）。
- 教训：**涉及本地大模型的功能，先用最短输入测硬件吞吐，再谈架构**。

## 架构

```
review_live.stream
  └─ tts/speaker.py（大脑 Python，stdlib only；随复盘由 llm_review 自动拉起）
       ├─ 断句（。！？；，超长 90 字硬切）→ 过滤（哨兵/tokens/工具/代码行不读）
       ├─ 朗读队列 maxsize=2，积压丢最旧（永远读最新）
       ├─ SAPI：常驻 powershell + System.Speech 阻塞 Speak（管道即队列）
       └─ LIVE-END 且队列空 → hybrid 模式把结论段交给 tts/speak_once.py
            （uv venv 里的 index-tts，克隆音色，合成后 winsound 播放）
```

## 坑

1. PowerShell 常驻 SAPI 要用 `[Console]::In.ReadLine()` + UTF8 编码声明；
   Speak（阻塞）而非 SpeakAsync（否则多句叠音）。
2. 长文本一律走文件（参考 Windows 命令行上限的教训）。
3. 杀后台测试进程要用命令行匹配（`py` 启动器 pid ≠ 实际 python 子进程）；
   shell 超时不一定会杀子进程（第一个 --test 进程幸存并空跑了 7 小时 GPU）。
