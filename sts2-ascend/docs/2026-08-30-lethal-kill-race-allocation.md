# 致死斩杀竞速的执行分配复盘

## 可证伪假设

当 `kill_race=true` 且本回合已致死时，`reserve_for_block=true` 仍会把攻击压到 0.55 倍、把格挡抬到 1.8 倍，并压低 0 费抽牌；因此部分格挡可能挤掉攻击或抽牌，导致本来可改写结局的输出窗口消失。

## 证据

1185-F17 的 T6 在 17 血、16 点来袭时连续打出两张 5 格挡；T7 在 11 血、28 点来袭时先用 Cinder+，随后用 Shrug 与 Battle Trance，最终阵亡。Vantom 的原生血量为 173，Battle Trance 为 0 费抽 3；Slippery 使慢速输出更难追回斩杀曲线。

## 最小改动

在 `brain/policy.py` 中仅对“致死斩杀竞速”解除普通致死的攻防反向倍率；完全覆盖缺口的格挡仍保留，部分格挡乘既有 `race_allin_blk_damp`，抽牌获得“续攻”评分。普通致死和非致死竞速路径不变。`brain/selfcheck.py` 增加对应的攻/部分格挡/抽牌比较与普通致死回归断言。

## 验证与回滚信号

`py -3 -B sts2-ascend/brain/selfcheck.py` 输出 `SELFCHECK OK`。最小 fixture 中竞速致死的 Strike、Battle Trance 均高于部分格挡，而普通致死 Strike 仍低于原闸门。若三场独立实战中部分格挡仍压过可支付攻击/抽牌，或完整覆盖缺口的格挡被错误压低，应回滚本次条件分支。
