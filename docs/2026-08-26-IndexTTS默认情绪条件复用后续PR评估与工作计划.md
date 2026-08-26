# IndexTTS-2.5 默认情绪条件复用后续 PR 评估与工作计划

日期：2026-08-26
状态：已实施；上游 PR [#799](https://github.com/index-tts/index-tts/pull/799) 已创建

## 2026-08-26 执行结果

用户确认本功能与 #795 相互独立并要求立即提交后，不再等待 #795 的维护者反馈。实现从当时最新的
`upstream/main`（`ee40fa7`）新建独立工作区 `D:\workspace\index-tts-reuse-spk-cond-pr` 和分支
`feat/reuse-spk-cond-for-default-emo`，没有修改 #795、FP16 PR 或直播项目的生产代码。

- 上游 PR：[#799](https://github.com/index-tts/index-tts/pull/799)
- 提交：`618f1e1595c7b67198359b63c11fb130ffc570c4`
- 标题：`feat(inference): optionally reuse speaker conditioning for default emotion`
- 状态：OPEN、MERGEABLE；外部 fork CI 尚待上游授权/运行

最终公共接口为构造器参数 `reuse_spk_cond_for_emo=False` 和仅适用于 2.5 的 WebUI 启动参数
`--reuse_spk_cond_for_emo`。只有调用者没有传入 emotion audio/vector/text 时才复用；显式 emotion audio
即使路径与 speaker 相同也继续独立编码。复用分支不写通用 emotion cache，切换 speaker 时使用本次最新的
`spk_cond_emb`；每个生成 segment 直接调用一次 `get_emovec()`，不再对相同条件调用两次。

为了让本 PR 与 #795 保持真正独立，没有顺手删除 [#796](https://github.com/index-tts/index-tts/issues/796)
记录的 speaker 重复 Wav2Vec 前向。因此准确收益口径是：当前 `main` 冷参考总 Wav2Vec 调用 `3 → 2`，
本特化只移除独立的默认 emotion 前向；若 #795/#796 的 speaker 修复以后合入，届时才自然成为 `2 → 1`。
缓存命中时没有 Wav2Vec 收益，但每个 segment 的 `get_emovec` 仍为 `2 → 1`。PR 明确声明这不是有意义的
常驻显存优化，并说明两条重采样链不同、输出音色或情绪可能变化。

验证全程复用已有 IndexTTS 依赖环境，只运行 CPU/mock 与完整 no-GPU 套件，没有下载 checkpoint、启动模型、
调用 CUDA、重建生产参考缓存或干扰直播/游戏/brain：

```text
pytest -m "not gpu"
173 passed, 22 deselected, 30 subtests passed
```

新增测试覆盖默认关闭、隐式默认 emotion alias、显式 audio/vector/text 旁路、同路径显式 emotion 独立编码、
speaker 切换、emotion cache 隔离、单次 `get_emovec` fast path，以及 WebUI 仅向 2.5 传参。没有把 #795 的
8.175 秒 emotion miss 数据包装成本 PR 实机结果；PR 只把它标为方向性旁证，并公开声明未做本分支 GPU、
DeepSpeed、BF16、accel、多 GPU 或主观音频 A/B。

## 结论

这个后续 PR 技术上完全可达，也值得保留为候选 PR；但它不是高概率直接合并的改动。

推荐定位为一个显式 opt-in 的“低计算参考准备”配置，不要称为 `low_vram` 或“穷鬼显存模式”：

- `spk_cond` 兼任默认 `emo_cond` 不会带来有意义的常驻显存收益。
- 相对当前上游 PR #795，参考缓存 miss 时 Wav2Vec2-BERT forward 可从 2 次降到 1 次。
- 如果同时跳过 `merge_emovec()` 中对相同条件的第二次 `get_emovec()`，每个生成 segment 仍能持续少一次情绪条件编码。
- 现有 speaker/emotion 两条音频预处理链不同，因此共享模式是明确的音色/情绪权衡，不是无损重构。

主观接受率判断：

| 提交方式 | 预估上游接受概率 |
| --- | ---: |
| 自动启用、声称无损或声称省显存 | 5–15% |
| 只做条件复用、没有持续收益证据 | 30–45% |
| 默认关闭、严格 opt-in、加入 segment fast path、CPU/mock 测试和诚实文档 | 45–60% |
| 另有同 seed 音频 A/B 或维护者预先认可 | 60–70% |

## 调研依据

### 本地代码和结果

当前上游 cache miss 路径会执行两次 speaker Wav2Vec2-BERT 和一次默认 emotion Wav2Vec2-BERT；其中一次 speaker 结果未使用。#795 已计划删除确定无用的 speaker duplicate，但仍保留独立 emotion 预处理链。

本地固定参考声线实现只执行一次 Wav2Vec2，并把结果作为默认 emotion 条件。15 秒参考音频的 Wav2Vec2-BERT 主导矩阵/卷积计算估算约为 `951 GFLOP/forward`，所以：

- 原上游 `3 → 1`：约少 `1.90 TFLOP`，其中语义特化本身约少 `0.95 TFLOP`。
- 以 #795 为基线 `2 → 1`：约少 `0.95 TFLOP`，即参考 Wav2Vec2 计算减少 50%。
- 这是参考缓存 miss 或参考音频改变时的收益；进程内 cache 命中后，原版本来也不会逐句重复 Wav2Vec2。

现有本地显存结果表明，约 2.2–2.3 GiB 的收益来自 W2V-BERT/CAMPPlus 不再常驻 GPU，而不是条件张量复用。当前两个条件张量仍是独立 storage，各约 2.93 MiB；即使真正做 alias，最多只多省约 2.93 MiB。

### 上游接受信号

- [PR #755](https://github.com/index-tts/index-tts/pull/755) 接受了低显存配置下跳过 QwenEmotion 的方案，说明资源受限配置符合项目方向；但该 PR 由核心协作者自提自合，不能直接等同于外部 PR 的接受率。
- [PR #516](https://github.com/index-tts/index-tts/pull/516) 和 [PR #517](https://github.com/index-tts/index-tts/pull/517) 说明默认关闭、可显式开启的性能开关可以被接受，并且需要性能数据。
- [PR #718](https://github.com/index-tts/index-tts/pull/718) 表明 no-GPU CI 是实际门槛；无 GPU 测试失败后需要修复再合并。
- [PR #765](https://github.com/index-tts/index-tts/pull/765) / [PR #767](https://github.com/index-tts/index-tts/pull/767) 是主要负面信号：维护者不愿接受可能静默降低音频质量的猜测性改变，即便默认路径没有改变。
- 当前基础 PR [#795](https://github.com/index-tts/index-tts/pull/795) 是 OPEN、MERGEABLE，但尚无 review/comment；其外部 fork CI 的 `action_required` 是等待维护者授权，不是测试失败。

## 锁定的后续设计

### 公共接口

推荐新增构造器参数，并在 2.5 WebUI 提供同名开关：

```python
IndexTTS2(
    ...,
    reuse_spk_cond_for_emo=False,
)
```

设计约束：

- 默认值必须是 `False`，默认行为和默认声音完全不变。
- 只支持 IndexTTS-2.5；v2 不接受该选项。
- 不与 `reference_device="cpu"`、`low_vram` 或精度模式自动绑定。
- 只有在没有有效外部 emotion source 时才启用：没有 `emo_audio_prompt`、`emo_vector`，且没有启用 `use_emo_text`。
- 显式 emotion audio 即使与 speaker 使用同一个文件路径，也必须继续走独立预处理链。
- 启用时打印一次明确警告：两条重采样链不同，输出音色/情绪可能改变。

### 推理 fast path

只在 `infer_v2_5.py` 内实现，不修改同时服务 v2/v2.5 的 `indextts/gpt/model_v2.py`：

1. speaker reference 准备完成后，特殊模式直接令 `emo_cond_emb = spk_cond_emb`。
2. 默认 fallback 的 `emo_alpha` 已为 `1.0`，生成每个 segment 时直接调用一次 `get_emovec()`。
3. 特殊模式跳过 `merge_emovec()` 对相同 speaker/emotion 条件的第二次 `get_emovec()`。
4. 初版不做跨 segment 的 `emovec` 生命周期缓存；先控制改动范围，避免扩大 autocast、缓存失效和测试边界。
5. 不把 alias 写入通用 `cache_emo_cond`，防止显式 emotion 请求污染或复用错误缓存。

## 待办清单

### 阶段 1：独立性决策

- [x] 用户确认本功能与 #795 独立，取消等待其 review/合入的门槛。
- [x] 重新核对最新 upstream/main、#795 diff 和公共参数风格。
- [x] 从 main 独立提交，不携带 #795 的 reference-device helper 或 speaker 重复前向修复。

### 阶段 2：独立分支实现

- [x] 从更新后的 upstream/main 新建独立分支。
- [x] 增加 `reuse_spk_cond_for_emo=False` 构造器参数和 public docstring。
- [x] 仅在 2.5 WebUI 增加显式开关及帮助文本。
- [x] 在隐式默认 emotion 分支接入条件 alias。
- [x] 在同一特殊分支接入单次 `get_emovec()` fast path。
- [x] 保持显式 emotion audio/vector/text 的原始路径不变。
- [x] 不改变默认重采样链，不把此特化绑定到 CPU reference offload。

### 阶段 3：无 GPU 验证

按上游 [PR 模板](https://github.com/index-tts/index-tts/blob/main/.github/pull_request_template.md)准备 CPU/mock 测试；不启动本地模型、不占用直播显存：

- [x] 默认关闭时保留旧 emotion encoder 和 `merge_emovec()` 路径。
- [x] 开启且无显式 emotion source 时，emotion encoder 不调用，两个条件为同一对象。
- [x] 开启时 fast path 恰调用一次 `get_emovec()`，不调用 `merge_emovec()`。
- [x] 显式 emotion audio 生效时，即使路径与 speaker 相同，也仍独立编码。
- [x] emotion vector / emotion text 路径不被错误短路。
- [x] speaker 路径变化后不会继续使用旧 emotion alias，显式 emotion cache 不被污染。
- [x] WebUI 在 v2 使用该参数时由 argparse 给出明确错误；v2 Python API 签名未改。
- [x] 完整 no-GPU 套件通过：173 passed、22 deselected、30 subtests passed。

不额外购买或申请 GPU 测试。已有 GTX 1060 固定声线直播运行结果可作为真实使用记录，但不能包装成通用音质 A/B 证明。

### 阶段 4：PR 文案和审查应对

- [x] PR 标题使用：`feat(inference): optionally reuse speaker conditioning for default emotion`。
- [x] 正文明确写出：这是 opt-in 的计算/音频质量权衡，不是显存优化。
- [x] 给出当前 main `3 → 2` Wav2Vec 和每 segment `2 → 1` `get_emovec` 的结构性收益。
- [x] 明确常驻显存收益约为 0；不声称缓存命中后 Wav2Vec 逐句提速。
- [x] 明确 speaker/emotion 重采样链不同，结果不保证 bit-identical。
- [x] 邀请有多种 GPU、语言和参考音频的社区成员补充音频 A/B。
- [x] 没有顺带统一重采样；这类默认行为变更仍应另行讨论。

## 验收标准与停止条件

后续 PR 只有同时满足以下条件才值得提交：

- 默认路径无行为变化，且 opt-in 边界可由 CPU 测试证明。
- 显式 emotion source 不受影响。
- 代码改动局限在 2.5 推理和必要的 WebUI/文档/测试。
- 无 GPU 测试通过，且没有为了本 PR 改动直播项目或运行中的 IndexTTS owner。
- PR 文案不夸大显存和逐句延迟收益。

本 PR 已按用户的独立性决策提交；后续根据 #799 自身的维护者反馈修订，不再以 #795 的状态作为停止条件。

## 参考文件

- 本地生产实现：[indextts_gpu.py](/D:/workspace/slay-the-spire-vivhite-mod/sts2-ascend/tts/indextts_gpu.py:165)
- 本地显存和直播验证：[2026-08-26-IndexTTS-GPU双路共享.md](/D:/workspace/slay-the-spire-vivhite-mod/docs/2026-08-26-IndexTTS-GPU双路共享.md:44)
- 上游 reference-device 工作区：`D:\workspace\index-tts-low-vram-pr`
- 官方基础 PR：[index-tts/index-tts#795](https://github.com/index-tts/index-tts/pull/795)
- 默认 emotion 条件复用工作区：`D:\workspace\index-tts-reuse-spk-cond-pr`
- 独立上游 PR：[index-tts/index-tts#799](https://github.com/index-tts/index-tts/pull/799)
