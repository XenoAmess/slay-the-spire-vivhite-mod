# 白绮战士替换：篝火组件离线验收报告

## 结论

- 状态：**离线 Windows Vulkan 验收通过**。
- 当前 `rest_site` 正式资源可继续使用，**无需重新生成 0024 或重做篝火 Spine**。
- 本报告不代表游戏内真机集成通过；本轮未部署 Mod、未启动或操作游戏，也未启动直播。真机中的篝火背景遮挡、多人四角色并排和实际交互仍由总集成阶段验收。

## 0024 血缘与素材契约

- 付费原图 `0024-rest-site-seated-master-attempt-01.png` 与采用母片 `vivhite-rest-site-seated-master-v1.png` 逐字节一致。
- 两者 SHA-256 均为 `cf5a2960274e19716438906edf4b493d67a0cbd7afd9c19321ffba6166f30de5`。
- 请求记录为 EvoLink `gpt-image-2`、`background: transparent`、2K/high，并保留了逐字 Prompt 与去密请求参数。
- 原始 2048×2048 RGBA 的四角 Alpha 均为 0；1,395,078 个非透明像素的 Alpha 不低于 250。原图整体辉光有 292 个低 Alpha 边缘像素，但确定性打包后的 2048×2048 runtime atlas 四边均为 Alpha 0，主体边界位于 `(54,52)..(1985,1996)`，没有运行时裁切。
- runtime atlas 只有 `vivhite_rest_site_seated` 一个私有 region；没有原战士身体 region、武器或旧战士碎片。

## Spine 与消费端契约

- Spine 版本 `4.2.43`，仅有 lowercase `default` skin、`vivhite_rest_hero` slot 和一个白绮加权 mesh。
- 骨架由 `root` 加 26 根 `vivhite_*` 私有骨组成；mesh 为 165 个顶点，每点恰有 2 个权重，不依赖原战士骨骼、网格或姿势。
- 五个动画及实际时长：
  - `overgrowth_loop`：5.0 秒；
  - `hive_loop`：3.6 秒；
  - `glory_loop`：4.4 秒；
  - `_tracks/light_off`：0.5 秒；
  - `_tracks/light_on`：0.5 秒。
- 三章循环的首尾骨变换完全闭合。游戏源码消费契约为 Act 0/1/2 分别选择 overgrowth/hive/glory，并随机 seek 到循环任意相位；`HideFlameGlow()` 会在 track 1 循环叠加 `_tracks/light_off`。
- 场景继续使用 `NRestSiteCharacter` 和直接子节点 `SpineSprite`，根变换为 position `(-2,42)`、scale `(0.760006,0.760006)`；`SelectionReticle`、`Hitbox`、`ThoughtBubbleLeft`、`ThoughtBubbleRight` 的节点及原偏移均保持不变。左右玩家翻转路径也按源码进行了独立渲染。

## Vulkan 渲染结果

- 环境：Godot 4.5.1 Mono、Windows display server、Vulkan、NVIDIA GeForce GTX 1060，并只读挂载 v0.111.0 原版 PCK 以加载真实 Spine GDExtension。
- 共渲染 73 张透明帧：三个循环各 9 个正向相位和 9 个翻转相位、两个灯轨各 5 帧、原战士尺寸参考 9 帧。
- 每个章节循环有 5 个像素不同的实际姿态，首帧与末帧一致；正向和翻转均通过。73 帧均非空且没有碰触 1920×1080 画布边缘。
- 每帧又真实 SourceOver 到纯黑、纯白和接近篝火场景的深绿色，共 219 张检查图；最终固化为 11 张接触表。
- 人工复核黑、白、篝火色以及左右翻转结果：银发、紫瞳、金色眼镜、蓝蝶和服装稳定；没有棋盘格、绿边、矩形晕、黑块、武器或原战士残片；脸、眼镜、头发、肩肘腕、裙摆、膝盖和脚踝未出现断裂、翻面或明显拉伸。亮灯与灭灯状态可清楚区分。
- 保留场景 `.760006` 后，白绮平均可见尺寸约 `362–364 × 480 px`；原战士为 `304 × 488 px`。白绮高度为原版约 98.4%，横向因展开坐姿为约 119.2–119.7%，不属于人物整体放大，且仍有充足画布留白。

## 固化证据

完整机器可读指标见 `report.json`；接触表采用固定帧并保留一致的缩放基准：

| 文件 | 内容 | SHA-256 |
| --- | --- | --- |
| `01-overgrowth-loop-camp.png` | 第一章循环，篝火近似底 | `9cea58d54c502d9b7b4a01d0a5b503438ab377b974c55ed890af7c422f0ea55d` |
| `02-hive-loop-camp.png` | 第二章循环，篝火近似底 | `2075b73cfa9264e9abee7e48b661a8040322cc85fbf4961575d91bc337520937` |
| `03-glory-loop-camp.png` | 第三章循环，篝火近似底 | `2135c6426edccd7653a43dbc87743cdcce7cf15a9ef2f8ceaa8f75a28c746af2` |
| `04-overgrowth-loop-flipped-camp.png` | 第一章左右翻转 | `b7e39fde31b3c37428534cfd4aeb800cd388c0abf9b5f2ef356d35b102be6799` |
| `05-hive-loop-flipped-camp.png` | 第二章左右翻转 | `fbe2eb6e10a38016adf838be6a20d310530c143e0c547f282ad7b65e41fb8695` |
| `06-glory-loop-flipped-camp.png` | 第三章左右翻转 | `c711156a4c927753871931acc6f01397a1dd6cc22d04b9a4039520607b5891c6` |
| `07-overgrowth-loop-black.png` | 纯黑 SourceOver | `ab6a1e647ba8228c6d2acf320a99f54bcc158429cc63f96000c97a242b4df0e3` |
| `08-overgrowth-loop-white.png` | 纯白 SourceOver | `2e2acb62dff0b4e51aec40a224caae5fc8593987358f671d5620129562ab7d3f` |
| `09-light-on-camp.png` | 亮灯 track 1 叠加 | `6c620f7df078e755437acf89f34e7b5e0044e5b16bd47d99590000319347900e` |
| `10-light-off-camp.png` | 灭灯 track 1 叠加 | `1e394a922127a965a497bc532d4f841ac9db1e312573809c9f9623a476835d8b` |
| `11-vivhite-vs-vanilla-actual-scale.png` | 相同像素比例的白绮/原战士尺寸对照 | `ecfba98c5b8297e07fa88e3500034a10504d6b4988dc06ae6d42273d02448edc` |

`report.json` SHA-256：`23034c9a760837704131fc4fd3cfbc4237a6902afd5d9a9d30f39355dab4da06`。
