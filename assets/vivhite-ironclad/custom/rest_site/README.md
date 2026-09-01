# Rest-site 制作源

[`sources/vivhite-rest-site-seated-master-v1.png`](sources/vivhite-rest-site-seated-master-v1.png) 是休息点坐姿的单幅 RGBA 母源，不是游戏运行时 atlas 页面。对应的 `overgrowth_loop`、`hive_loop`、`glory_loop`、翻转、火焰开关和随机初始 seek 契约记录在[验收组件报告](../../evaluation/rest-site-acceptance/component-report.md)中。

原图、Prompt 与请求参数必须逐字节对应 [`generated/evolink-paid/`](../../generated/evolink-paid/README.md) 的追加批次。任何运行时接入前，都要重新核对实际场景尺寸、锚点、边界和 SourceOver 叠层；静态母源本身不等于运行时通过。

## 当前边界

- 本目录只保存制作源，不声明已注册或已部署到游戏。
- 透明度验收必须使用 RGBA、四角 `Alpha=0`、黑/白/场景底色 SourceOver 合成及实际显示尺寸复核。
- 不得用脚本抠图、色键、蒙版或其他后处理修补 Alpha；需要透明素材时遵循仓库 EvoLink 原生透明契约。
- 验收报告中的 `runtime_game_integration=not_run` 未被真实机验证前，保持 fail-closed。

返回 [Vivhite 资产总索引](../../README.md)。
