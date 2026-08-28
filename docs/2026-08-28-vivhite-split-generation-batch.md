# 白绮拆件素材生成批次

## 批次规则

- 每个语义素材最多进行 8 次 EvoLink 付费生成；达到用途要求即停止，不为用满额度而继续调用。
- 第 8 次仍不合格时，保留全部原图、Prompt、脱敏请求参数和任务记录，登记逐次失败原因、当前最佳候选及剩余缺陷，然后先跳过该素材。
- 所有达到 8 次上限但未通过的素材在批次末统一交给用户评审；只有用户明确追加该素材额度后才允许第 9 次及以后调用。
- “当前最佳候选”只用于评审，不等于运行时验收通过；不得因达到上限而降低 Alpha、拆件边界、身份一致性或单附件构图标准。

## 当前进度

| 语义素材 | 已用额度 | 状态 | 结论 |
| --- | ---: | --- | --- |
| 独立侧卧死亡整身 | 5/8 | 通过 | 采用 attempt 05；闭眼自然侧卧、无武器，作为单一死亡 attachment 使用。 |
| 蓝蝶发饰 | 1/8 | 通过 | 单一连续附件、四角透明、无边缘触碰。 |
| 后层发壳 | 1/8 | 通过 | 单一后发附件；上层前额区域作为被脸和前刘海覆盖的隐藏搭接区。 |
| 前刘海 | 8/8 | 待用户统一评审 | 八次均未消除外围低 Alpha 柔光；当前最佳为 attempt 07，仅作为评审候选，不进入生产 atlas。 |
| 头脸 | 8/8 | 待用户统一评审 | 八次均未消除外围低 Alpha 柔光；attempt 05 的身份和几何最佳且低 Alpha 外围像素最少，仅作为评审候选。 |
| 躯干 | 8/8 | 待用户统一评审 | attempt 08 被内容过滤拒绝；attempt 07 是当前最佳设计且不触边，但仍有 8592 个低 Alpha 外围像素。 |
| 左靴（画面左/后腿） | 8/8 | 待用户统一评审 | 八次均有外围低 Alpha 光场；attempt 04 的造型、留白和约 5274 个低 Alpha 外围像素最平衡，仅作为评审候选。 |
| 右靴（画面右/前腿） | 8/8 | 待用户统一评审 | 八次均有外围低 Alpha 光场；attempt 08 最小且朝向正确，但插片多出金饰，仅作为评审候选。 |

## 前刘海逐次记录

1. `0032-split-front-hair-attachment-attempt-01`：画风与 Alpha 格式正确，但主体是完整假发壳，包含大量后发，不能作为独立前刘海层。
2. `0033-split-front-hair-attachment-attempt-02`：构图已经收敛为一块连续的浅横向额前刘海；四角透明、四边不触边。外围仍有大范围低 Alpha 柔光，叠到独立脸部附件时可能形成灰亮遮罩，因此暂不标记最终通过。
3. `0034-split-front-hair-attachment-attempt-03`：沿 attempt 02 做同形清理，但非零 Alpha 增加到 259088，出现 9 个边缘触碰像素，退化。
4. `0035-split-front-hair-attachment-attempt-04`：改为原始设定参考和技术平涂语义，构图可用、无触边，但仍有约 1.3 万个低 Alpha 外围像素。
5. `0036-split-front-hair-attachment-attempt-05`：改用宽画布、低质量和 Live2D 层提示；模型退化成带呆毛的完整前发帽，且柔光仍在。
6. `0037-split-front-hair-attachment-attempt-06`：仅参考 attempt 02 做清理；主体放大触碰四边并产生 43 个边缘非零像素，淘汰。
7. `0038-split-front-hair-attachment-attempt-07`：无参考、纯三色矢量式提示；得到本批最好的单一连通刘海形状，四边不触边，但 259448 个非零像素中约 1.4 万个低于 Alpha 128，外围灰光仍会叠亮脸部。登记为当前最佳评审候选。
8. `0039-split-front-hair-attachment-attempt-08`：进一步移除身份与精品语义，只保留工业平涂要求；形状更简单，但仍有约 1.3 万个低 Alpha 外围像素，问题未解决。

前刘海已达到 8 次硬上限，现按规则跳过。除非用户在最终评审时明确追加该语义素材额度，否则不得调用第 9 次，也不得把 attempt 07 打包为通过素材。

## 头脸逐次记录

1. `0040-split-head-face-attachment-attempt-01`：成功生成单一无发头脸，三分之四朝 screen-right，双紫瞳、金色圆框眼镜、冷淡闭口表情、完整头壳和短颈根均正确。主体接近占满 2048 方形画布，Alpha bounds 为 `[0,16,2036,2032]`，57 个边缘非零像素；外围柔光会在后发、前刘海和高领接缝处叠亮，因此只作为后续同形重绘参考。
2. `0041-split-head-face-attachment-attempt-02`：保留第 1 次身份并缩小实体，但柔光仍扩散到左右边缘，出现 418 个边缘非零像素，淘汰。
3. `0042-split-head-face-attachment-attempt-03`：完全不带参考的低复杂度赛璐璐测试；不触边，但仍有约 1.32 万个低 Alpha 外围像素，且五官身份弱于参考驱动版本。这证明柔光不是由上一张生成图单独继承。
4. `0043-split-head-face-attachment-attempt-04`：仅参考用户原始头像并降低复杂度；身份、三分之四朝向、无发头壳、金框眼镜和短颈根可用，四边不触边。非零 Alpha 327497，其中约 1.16 万低于 128，仍需继续尝试模型内清理；暂列当前最佳。
5. `0044-split-head-face-attachment-attempt-05`：在 attempt 04 上同形缩小并要求删除外部照明；实体约 400×687，四边不触边，身份仍稳定。非零 Alpha 163740，其中 6831 低于 128，柔光绝对面积明显下降但仍存在；更新为当前最佳。
6. `0045-split-head-face-attachment-attempt-06`：把紫灰实体轮廓明确指定为闭合边界做清理，模型仍重画并放大主体；约 1.02 万个低 Alpha 外围像素，退化。
7. `0046-split-head-face-attachment-attempt-07`：以 attempt 05 为唯一参考并降为低复杂度复刻；身份可用、无触边，但低 Alpha 外围像素约 8542，仍差于 attempt 05。
8. `0047-split-head-face-attachment-attempt-08`：仅参考用户原始头像，把主体缩到画布约一半；四边不触边，但仍有约 7413 个低 Alpha 外围像素，身份细节也略弱于 attempt 05。

头脸已达到 8 次硬上限，现按规则跳过。当前最佳评审候选为 `0044-split-head-face-attachment-attempt-05`；除非用户明确追加该语义素材额度，否则不得调用第 9 次或放入生产 atlas。

## 躯干逐次记录

1. `0048-split-torso-attachment-attempt-01`：成功生成一张连通的三分之四躯干，包含高领、胸口肤色区、紫晶、白色胸片、深蓝束腰、金线、screen-left 固定肩饰、双肩接口和腰部插片；没有夹带头、四肢或独立裙片。外围柔光令 Alpha bounds 达到 `[0,13,1658,2483]`，20 个边缘非零像素，肩口与腰口存在叠亮风险；只作为后续同形清理参考。
2. `0049-split-torso-attachment-attempt-02`：基于 attempt 01 同形缩小，服装结构保留，但柔光仍跨到左右边缘，17 个边缘非零像素。
3. `0050-split-torso-attachment-attempt-03`：无参考低复杂度测试；不触边但服装漂移成大蝴蝶结和不同腰身，且仍有约 1.37 万个低 Alpha 外围像素。
4. `0051-split-torso-attachment-attempt-04`：只参考原始人物设定；服装身份回升且不触边，但姿态退回正面、下摆被误画成裙片，仍有约 9883 个低 Alpha 外围像素。
5. `0052-split-torso-attachment-attempt-05`：以 attempt 01 为唯一参考、低复杂度缩小复刻；三分之四结构、服装身份、双肩接口和腰口均可用，四边不触边，暂列当前设计最佳。仍有约 9998 个低 Alpha 外围像素，不能进入生产 atlas。
6. `0053-split-torso-attachment-attempt-06`：对 attempt 05 做闭合边界清理，模型再次放大主体，低 Alpha 外围像素增至约 1.30 万，退化。
7. `0054-split-torso-attachment-attempt-07`：低复杂度精确复刻 attempt 05；服装结构、三分之四方向、肩口和短腰口均保留，四边不触边，低 Alpha 外围像素降至 8592，更新为当前最佳评审候选。
8. `0055-split-torso-attachment-attempt-08`：无参考小尺寸平涂对照被 EvoLink 以 `content_policy_violation` 拒绝，没有返回 PNG；Prompt、脱敏请求与 task 记录仍按追加式归档保留。

躯干已达到 8 次硬上限，现按规则跳过。当前最佳评审候选为 `0054-split-torso-attachment-attempt-07`；除非用户明确追加该语义素材额度，否则不得调用第 9 次或放入生产 atlas。

## 左靴逐次记录

1. `0056-split-leg-left-boot-attachment-attempt-01`：只生成一只朝画面左下的深蓝短靴，紫色鞋跟、紫晶和金色小菱形均正确；但主体周围有大面积紫色外发光，且 19 个边缘像素触碰画布，不适合作为独立脚踝附件。
2. `0057-split-leg-left-boot-attachment-attempt-02`：移除战斗母片参考，仅保留用户原始人物设定，并缩小构图。单靴、插片、朝向和身份细节保留，四边不再触碰；整圈低 Alpha 紫色光场仍明显，继续尝试完全无图像参考的工业平涂语义。
3. `0058-split-leg-left-boot-attachment-attempt-03`：完全无图像参考、改用四组硬边平涂；单靴结构完整且不触边，非零 Alpha 170246，其中低于 128 的外围像素约 6546，仍有可见蓝紫柔光。
4. `0059-split-leg-left-boot-attachment-attempt-04`：进一步收敛为低质量、无光照的平面贴花语义；造型简洁、朝向正确、四边留白充分，非零 Alpha 121890，其中约 5274 低于 128。当前是设计与外围柔光面积最平衡的候选。
5. `0060-split-leg-left-boot-attachment-attempt-05`：尝试严格限制为闭合填充多边形；模型反而放大主体并恢复更明显的整圈柔光，非零 Alpha 244181，其中约 7227 低于 128，较 attempt 04 退化。
6. `0061-split-leg-left-boot-attachment-attempt-06`：以 attempt 04 为唯一参考，要求只移除外部照明并保持同形；视觉结构几乎精确保留，但 Alpha bounds 扩张到 `[29,19,763,1205]`，低于 128 的外围像素约 5437，未优于原图。
7. `0062-split-leg-left-boot-attachment-attempt-07`：移除“魔法”和宝石发光语义，改成技术服装贴片；得到本批最简洁的平面单靴，四边留白充足，但仍有约 6093 个低于 128 的外围像素。
8. `0063-split-leg-left-boot-attachment-attempt-08`：最后改用方形画布、十六进制固色和技术切片语义；结构仍正确且不触边，但外围低 Alpha 像素约 7024，证明换画幅也没有消除模型生成的展示光场。

左靴已达到 8 次硬上限，现按规则跳过。当前最佳评审候选为 `0059-split-leg-left-boot-attachment-attempt-04`；除非用户明确追加该语义素材额度，否则不得调用第 9 次或放入生产 atlas。

## 右靴逐次记录

1. `0064-split-leg-right-boot-attachment-attempt-01`：得到一只正确的前腿靴，插片朝左上、鞋尖朝左下、鞋跟在画面右侧，单物件且四边不触碰；简洁平涂设计可用，但外围仍有约 7084 个低于 Alpha 128 的像素。
2. `0065-split-leg-right-boot-attachment-attempt-02`：验证“完全不在 Prompt 中提及 glow/halo”并不能消除展示光场；模型还把领口误强化为金边，低于 Alpha 128 的外围像素约 5988，身份设计较 attempt 01 退化。
3. `0066-split-leg-right-boot-attachment-attempt-03`：只参考用户原始人物设定并提高质量；鞋靴细节精致、单物件且不触边，但透视过于正面、饰物变复杂，Alpha bounds 扩张到 `[65,37,689,981]`，外围光场仍明显。
4. `0067-split-leg-right-boot-attachment-attempt-04`：以 attempt 01 为唯一参考做同形去外部照明；主体几乎精确保留，但 Alpha bounds 扩张到 `[27,19,759,1205]`，极低 Alpha 光场接近四边，未通过。
5. `0068-split-leg-right-boot-attachment-attempt-05`：尝试传统动画赛璐璐层语义；单靴和方向正确，但插片不够明确、上部饰件变大，仍有约 6871 个低 Alpha 外围像素。
6. `0069-split-leg-right-boot-attachment-attempt-06`：尝试丝网印刷分色层语义；模型放大主体并产生额外金色饰件，非零 Alpha 达 285595，外围柔光和设计漂移均退化。
7. `0070-split-leg-right-boot-attachment-attempt-07`：改用方形画布和正向固色约束；造型清晰，但主体和光场共同触及画布底边，出现 30 个边缘非零像素，淘汰。
8. `0071-split-leg-right-boot-attachment-attempt-08`：把物件目标缩至画布约四分之一；朝向、单物件和留白正确，非零 Alpha 74168，其中约 4320 低于 128，为本组最低；仍有可见外围光场，且上方插片误多一枚金饰。

右靴已达到 8 次硬上限，现按规则跳过。当前最佳评审候选为 `0071-split-leg-right-boot-attachment-attempt-08`；除非用户明确追加该语义素材额度，否则不得调用第 9 次或放入生产 atlas。

所有检查仅做离线素材与 Vulkan 预览，不部署、不启动或重启游戏，也不触发直播。
