# Director v2 独立短版 EDL 配方

三份 `*.recipe.json` 只引用 production 540 EDL 中已经绑定到同批新 take 的
`source_subshot_id`。`vivhite_promo.render_v2.build_variant_edl_v2()` 会复制这些
take 的路径、SHA-256、probe 和源窗，重新建立从 0 开始的 60/30/15 秒时间线；
它不会读取、截取或引用签署后的 540 秒母片。

配方中的 `cue_ids` 只复用逐 cue 的 XiaoxiaoNeural 音频和双语字幕。J-cut 的
绝对时间会随连续素材一同重映射；如果配方切断了 J-cut 的任一边界，构建会
失败而不是降级成普通旁白。
