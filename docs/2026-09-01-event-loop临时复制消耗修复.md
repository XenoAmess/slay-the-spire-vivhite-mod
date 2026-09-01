# Event Loop 临时复制消耗语义复盘

日期：2026-09-01

## 结论

创意工坊评论“事件循环说是给一张临时复制，实际上给的是正常复制牌……带消耗词条”符合当前实现的真实缺陷。这里有两层彼此独立的语义：

- `CardPileCmd.AddGeneratedCardToCombat` 让副本属于本场战斗，战斗结束会被清理；这部分原实现已经成立，并不是把牌写入牌组的持久化 bug。
- “消耗”是打出后的结果位置和玩家可见的原生词条。原实现只调用 `CreateClone` 与 `SetToFreeThisTurn`，非消耗来源牌的副本没有 `CardKeyword.Exhaust`，因此会按普通牌处理。

## 引擎证据

游戏 v0.111.0 的 `CardModel.CreateClone` 会把新实例的 `ExhaustOnNextPlay` 初始化为 `false`；`SetToFreeThisTurn` 只写入本回合/直到打出的临时费用。`EndOfTurnCleanup` 还会清除 `ExhaustOnNextPlay`。出牌结果位置则优先检查持久 `CardKeyword.Exhaust`，其次才检查该 transient flag。

因此不能只把 `ExhaustOnNextPlay` 设为 `true`：副本若跨回合留在手中，该 flag 会被清掉，且卡面不会显示消耗词条。

## 修复

`EventLoop` 在 `CreateClone()` 后追加 `copy.AddKeyword(CardKeyword.Exhaust)`，再调用原有的 `SetToFreeThisTurn()` 和 `AddGeneratedCardToCombat()`。这保留了战斗内临时生命周期，同时使任何来源（包括本来不消耗的普通牌）的生成副本都成为一次性消耗牌。

中英文 `description`/`smartDescription` 同步说明生成副本带 `Exhaust`/“消耗”且本回合为 0 费。其他复制牌（例如 `ConservedRecurrence`）未改变。

## 回归覆盖

`GeneratedCardGrowthAcceptanceTests` 增加了非消耗基础牌 `ClosedDomainMapping` 的真实生产出牌链：

1. 普通来源牌先正常进入弃牌堆；
2. Event Loop 生成并加入战斗手牌；
3. 副本必须含 `CardKeyword.Exhaust`、`ExhaustOnNextPlay == false`，且不进入 run deck；
4. 打出副本后必须进入真实 Exhaust pile。

同时保留原有生成/回收副本触发 Dimension Up 的回归，并增加静态 IL 检查，防止以后移除持久词条。
