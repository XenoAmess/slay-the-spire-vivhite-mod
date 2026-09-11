# 白绮 Boss 竞速同回合掉血观测复盘

日期：2026-09-01

## HYPOTHESIS

第 4 局 `9D3T8FHYXKJM` 的 F17 竞速判死理由遗漏了已经由 `_race_same_round_loss` 记录的同回合掉血，因此后续复盘无法区分卡牌自损/费用与敌方意图伤害。

该假设可证伪：若竞速判死时没有同回合掉血，或现有理由已经完整披露该账，则新观测标记应为零信号。

## EVIDENCE

- 完整失败证据索引 `sts2-ascend/.review_evidence/failed_review/index.json` 已核对 473/473 个文件的字节数与 SHA-256；目标包和 3 个重试包的 manifest、report、inventory、候选 patch 均已读取。候选 patch 仅作证据，未自动套用。
- Run 4 `9D3T8FHYXKJM` 的完整 211 条 decision 已逐条检查。F17 决策 192–209 中 HP 从 66 降至 9，多个理由含 `hp-cost`、`VIVHITE_LIVE_ESTIMATE` 和竞速判断；决策 210 以 HP 0 进入 `GAME_OVER`。
- 原生 v0.111.0 knowledge 将 `SOUL_FYSH` 定义为 Boss；其 mechanics 记录 `BECKON`、`DE_GAS`、`GAZE`、`FADE`、`SCREAM` 及 16/7/13 伤害口径。生产 `policy.py` 已逐 tick 累加 `_race_same_round_loss`，但原先只在回血和零伤害意图同时成立的 `BOSS_SUSTAIN_NET_HP` 路径展示相关账。

## PRODUCTION_CHANGE

- `sts2-ascend/brain/knowledge.py` 增加默认开启的 `race_same_round_hp_loss_obs` 开关。
- `sts2-ascend/brain/policy.py` 仅在白绮、Boss、`race_lost` 且同回合观测损失大于 0 时，在既有竞速理由后追加 `RACE_SAME_ROUND_HP_LOSS_OBS` 与损失量。
- `sts2-ascend/tests/test_boss_race_sustain.py` 锁定无回血竞速路径的标记；该分支只改理由文本，不改 action、评分、TTK、可存活回合或能量分配。

## EXPECTED_SIGNAL

未来 3–10 局只统计相关白绮 Boss 竞速判死样本：标记出现次数、损失量、同决策 `hp-cost`/敌方 intent 对账，以及标记后的胜负。至少一个样本应能把损失量与自损/费用或敌方伤害账本对应；非白绮、非 Boss、未 `race_lost`、无损失或开关关闭时标记应为零。若第 10 局仍无样本，补充费用/事件证据而不改竞速阈值；若标记越界或改变动作/评分，立即关闭开关并回退分支。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：`SELFCHECK OK`。
- 独立 `test_boss_race_sustain.py` 已尝试，但 Python 3.14 受管临时目录触发 WinError 5 ACL 错误；未将环境失败伪报为测试通过。
- 目标 diff `git diff --check` 通过，无冲突；工作树中宿主挂载的 `.review_evidence/` 与其他无关变更未纳入本批。

## REPLAY

retry_resolution: 20260831-200515-1788177915907021900-8589e247 integrated

# 第 7~20 局批复盘：謦欬实付占致命战掉血过半，生命支付权重改按实测自损加码

日期：2026-09-05

## HYPOTHESIS

白绮 0/45 生涯的致命 Boss/终盘战掉血主要由謦欬（生命支付）自损构成，但 reflect 的生命支付权重适应只按「本局拿牌张数 ≥2」每局 -0.05 收紧，拿不到实战支付强度；对实测自损占掉血 ≥50% 的致命战再加一档收紧，权重将更快到达能抑制自损卡组的水平。

该假设可证伪：若未来 3~10 局致命战「自损N」段占掉血比例不下降（仍 ≥50%）、或收紧后拿牌/出牌形态与死亡形态均无变化，则假设不成立，删除加码分支与观测字段即整体回滚。

## EVIDENCE

- 近 16 局 runs 文件逐场实测（脚本统计 boss 层 play_card 理由内 hp-cost 累加 vs 战斗记录掉血）：15 场致命 Boss 战自损占掉血 59%~143%，13/15 ≥50%——run42 F33 自损83/掉血85、run43 F33 119/97、run39 F48 142/99、run33 F17 72/84、run35 F17 75/84。
- 批内最新死亡局 run 20（REV1WJECKYDZ，F17 SOUL_FYSH）完整决策链已读：续航账「净损EMA13.4/回合、同回合回血11、自损/费用85、零伤害回合3」，终盘「败局竞速全攻」仍以 hp-cost=4 打出【绯色面积】后 4 血 0 甲对 24 意图结束回合。
- 失败证据索引 sts2-ascend/.review_evidence/failed_review/index.json 已核对：target 包 retry_candidate.patch 与 wip.patch 均 0 字节（git checkout 超时，模型未产出），两个 attempt 包为生命周期停机全量保全、无候选改动——lineage 无可重实现内容。
- 生产 policy.py 已有 _race_same_round_loss 同回合净扣血逐 tick 实测账本（自损/费用口径），但此前只在续航账注展示，死亡归因与战斗记录均不消费。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：新增 combat_self_hp_loss() 访问器，口径与 BOSS_SUSTAIN 账注「自损/费用」字段严格一致。
- sts2-ascend/brain/agent.py：战斗聚合账累计 self_hp_loss_sum（多阶段分段累加）；died_in_combat 新增 self_hp_loss；战斗记录在自损>0 时追加「自损N」段（竞速审计段与（阵亡）后缀位置不变）。
- sts2-ascend/brain/reflect.py：白绮謦欬卡组阵亡的 -0.05 拿牌口径之上，致命战实测自损占比 ≥50% 时再加 -0.05（同一 BOUNDS (-3.0,-0.5) 钳制）；缺 self_hp_loss 字段的旧记录退回纯拿牌口径，行为与旧版一致。
- sts2-ascend/brain/selfcheck.py：3pra 夹具锁定三分支——自损 98% 双档收紧至 -1.35、24% 单档 -1.30、缺字段单档 -1.30，且加码证据入 lesson。

## EXPECTED_SIGNAL

未来 3~10 局：lessons 出现「謦欬实付加码收紧」且 ivhite_param_life_cost_weight 下探速度快于旧纯拿牌口径；战斗记录「自损N」段使每批可直接复核自损/掉血占比。有效信号：致命战自损占比降至 <50%、Boss 战回合数延长或出现首胜。证伪/回滚条件：10 局内自损占比不降、或权重触底 -3.0 后死亡形态不变——删除加码分支与观测字段即可整体撤回。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK。
- git diff --check 通过；完整 diff 已回读，仅 4 个生产/测试文件，无在线状态、无无关文件。

## REPLAY

retry_resolution: 20260905-121621-1788581781070312400-70149919 no_valid_change

# 第 21~48 局批复盘：竞速生存分母把謦欬自付当敌方磨损，判死后 41% 实战获胜——自付隔离出 tsurv

日期：2026-09-05

## HYPOTHESIS

白绮竞速判死的「可存活回合」分母（`_race_loss_rate` 回合首→回合首净损 EMA）把自愿支付的謦欬生命费用计入敌方磨损：T1 换挡倾泻直接压扁 tsurv → 判死 → 败局竞速全攻再付更多生命 → 自证死期闭环。把同回合实测自付从边界净损中隔离（敌方归属口径），虚假判死率应降到 30% 预注册线以下。

该假设可证伪：race_audit 台账按判死入锁与实战结局逐场对照，未来 3~10 局 won/latched 不降至 <30%（或平均楼层/判死后死亡率显著恶化）即不成立，`vivhite_race_self_loss_exclude=False` 一键恢复混合口径。

## EVIDENCE

- race_audit 台账（本 profile stats）：判死入锁 75 场、实战获胜 31 场 = 41.3%；本批 21~52 局战斗记录可对照的 45 场中 20 场判死后获胜 = 44.4%，且 36/45 在 T2 即入锁（最早允许时刻）——越过「判死→获胜 >30% 行为化收紧」预注册线（esc 桶 44.2% 收紧为先例）。
- 批内最新死亡局 run 48（2CT4ZDKZ0JSA，F17 乐加维林族母）完整决策链已读：T1 自付 16 血（85→69，并行星雨 hp-cost 6、尺度变换+ 4、星图检索 2×2、弦光投影 2），T2 边界净损样本 16 全部来自自付；终盘 3 血仍打出 hp-cost 2 的星图检索跌至 1 血、全手牌被謦欬锁死后中 21 意图阵亡。
- 上一批（7~20 局）的 自损N 战斗记录段在本批 52 局零显形：该改动 19:09 才提交，晚于全部 52 局结束时间，属部署时序而非观测失效；本批不改该链路。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：新增 `_race_prev_same_round_loss` 回合边界快照（初始化/战斗重置同步）；白绮且 `vivhite_race_self_loss_exclude`（默认开）时，边界净损减去上一回合同回合 tick 差值实测的自付量后再进 EMA——敌方回合间行动天然落在边界采样之外，汲取/回血仍留账内（D0T5BPUDMG6 续航口径不动）；判决现场在 tsurv 计算前追加「已隔离謦欬实付N（VIVHITE_RACE_SELF_LOSS_EXCLUDE）」留痕。已知口径边界：同回合敌方反伤（荆棘类）会被一并隔离，属有界乐观偏置，已在注释登记。
- sts2-ascend/brain/selfcheck.py：3prb 夹具锁定三分支——T1 零意图自付 16 后开关开启时首边界样本为 0 且留痕在场；回滚键关闭时严格回落混合口径 16 且无留痕；自损账原始口径 16 不变。
- sts2-ascend/tests/test_boss_race_sustain.py：续航夹具 EMA 断言由混合口径 8.5 更新为敌方归属口径 1.5（T1 自付 10 不再计入），注释登记批次依据；同文件判死锁存、续航开门、自损账显示断言不变。

## EXPECTED_SIGNAL

未来 3~10 局：race_audit won/latched 降至 <30%；战斗理由出现 VIVHITE_RACE_SELF_LOSS_EXCLUDE 留痕且可与同决策 hp-cost/敌方意图对账；竞速入锁时刻后移（T2 占比下降）。证伪/回滚条件：10 局内 won 率不降、died/latched 异常飙升或平均楼层显著下滑——置 `vivhite_race_self_loss_exclude=False` 即整体撤回。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（含新 3prb 夹具）。
- py -3 -B sts2-ascend/tests/test_boss_race_sustain.py：2 tests OK。
- git diff --check 通过；完整 diff 已回读，仅 3 个生产/测试文件 + 本报告与口播短评，无在线状态、无无关文件（工作树中宿主挂载的超长路径资产删除遗留不纳入本批）。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 362 局复盘：自付主导时滑溜低回报单体生命攻击门

日期：2026-09-08

## HYPOTHESIS

若白绮已观测到可行动段自付速率不低于敌方净损，且 SLIPPERY 将单体攻击折成的实际移除低于本次生命支付，则判死竞速豁免会错误放行低回报攻击。可证伪信号是未来 3~10 局该门的命中留痕与自付>实际移除事件是否下降。

## EVIDENCE

- 第 362 局 VANTOM F17 完整链：自付 13/回合、敌方净损 5/回合；T3 已判死，随后仍以生命支付攻击出牌，T7 结束时 2 HP 阵亡。
- 原生知识 `SLIPPERY_POWER` 规定下一次失去生命只失 1 点；决策链同时记录了低回报单体攻击与 `VIVHITE_RACE_SELF_LOSS_DOMINATES`。
- `failed_review_replay.requested_packages` 为空，无需重放失败包。

## PRODUCTION_CHANGE

- `policy.py` 新增默认启用的 `VIVHITE_RACE_SELF_LOSS_PAYBACK_GATE`：仅在完成至少一个回合采样、自付占主导时，压低白绮单体“实付血量>实际移除且未斩杀”的候选；AOE、普通高回报、斩杀和非白绮路径不变。
- `knowledge.py` 增加 `vivhite_race_self_loss_payback_gate`，设为 `0` 即回滚；`selfcheck.py` 覆盖滑溜、普通目标、斩杀和关闭键。

## EXPECTED_SIGNAL

未来 3~10 局应出现 `VIVHITE_RACE_SELF_LOSS_PAYBACK_GATE`，且自付>实际移除事件减少，同时不牺牲斩杀。若命中后无改善或楼层/阵亡恶化，将该键置 `0` 并撤回本门。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：`SELFCHECK OK`。
- `git diff --check` 通过；改动仅限三处静态源码与本报告/短评，未触碰在线运行状态。

## REPLAY

`retry_resolution: none`（`failed_review_replay.requested_packages` 为空）。

# 第 5~6 局批复盘：前夜竞速预演不扣滑溜破层期，对墨影幻灵贴线局误判可行→翻转带回血——开局滑溜破层税入预演

日期：2026-09-06

## HYPOTHESIS

前夜竞速预演（_boss_race_doomed/BOSS_RACE_PROJ_AUDIT）可行侧 ttk 口径 pool/dpt 不扣除开局自挂滑溜 Boss 的破层期：VANTOM（墨影幻灵，原生 mechanics SlipperyAmt=8，AfterAddedToRoom 自挂 8 层 SlipperyPower，每层把一次命中压到只失 1 血）的前 8 次命中近乎零产出，预演因此对该 Boss 系统性乐观，把贴线必败局判成「竞速预演可行」并在篝火翻转带回血而非锻造。

该假设可证伪：若未来 3~10 局含滑溜 Boss 组合池的幕里，BOSS_RACE_SLIPPERY_TAX 留痕出现但回血/锻造分布与 Boss 战结局均无变化（或标记只在明显无关对局出现），则假设不成立，oss_race_slippery_tax_per_layer=0 一键回滚。

## EVIDENCE

- 第 5 局 NM71E9ZJ3DVR：F15 篝火「竞速预演判可行——击杀需9回合＞满血可存活7回合，但联合能量复核存在可行攻防分配（血池252、火力11、先验28/回合），回血23点」→ F17 墨影幻灵实战 3 回合阵亡（掉血53）。
- 第 6 局 ETE5DESYP28G（完整 234 条决策链已逐条读，F15~F17 段 35 条全检）：F15 篝火同款判可行（击杀需7＞可存活7，联合复核放行，药水授信-12血池）→ 回血15点、78 血 100% 进场 → 实战 T1~T3 逐 hit≈1.0（滑溜8层烧墙），T3 战斗端投影「击杀还需15回合>可存活5回合」，6 回合阵亡（掉血78，自损/费用 75 另有謦欬账）。
- 同型旧证：1232 局 F17 VANTOM 8 层开局投影「击杀还需9回合」，实战 T7 阵亡累计仅 ~57 伤（SLIPPERY_TTK_OBS 注释登记）。三个独立对局（5/6/1232）同一失真方向，达 evidence_run_threshold。
- 原生 v0.111.0 mechanics：全怪物仅 VANTOM/INKLET 开局自挂 SlipperyPower；VANTOM SlipperyAmt 表达式 AscensionHelper.GetValueIfAscension (AscensionLevel.ToughEnemies, 9, 8)，asc0=8 层；SLIPPERY_POWER 描述「下一次要失去生命值时只会失去1点」。
- 生产现状：战斗端已有 SLIPPERY_RACE_GUARD（挡静态复核翻案）与 SLIPPERY_TTK_OBS（ttk 未扣破层期留痕），均不改判决；前夜预演 _boss_race_doomed 与 _race_joint_feasible 完全无滑溜口径——这是消费链上最后一处未堵的乐观口。
- failed_review_replay 目标包 20260901-000605-1788192365526162900-0b9c97f5：manifest/inventory/retry_evidence_history 全部可读且一致——宿主创建隔离 clone 时 D 盘 No space left，provider 未开始工作，retry_candidate.patch 0 字节、路径数 0，legacy_pre_provider_certified_empty 认证空 lineage，无可重实现内容。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：新增 _native_slippery_layers（解析 mechanics SlipperyAmt 末尾字面量，native 缺失/无属性/异常一律返回 0）与 _act_slippery_tax（同幕已有重复实证的组合池内取最大开局滑溜层数 × per_layer，有界悲观）；_boss_race_doomed 可行侧 ttk 加计破层税并贯通联合能量复核（新增 	tk_tax 参数，默认 0 严格旧口径）与组合全称门（逐组合只对本组合滑溜成员加计，分账留「滑+N.N」标记）；可行侧 BOSS_RACE_PROJ_AUDIT 账面与判死 note 均带「开局滑溜破层税+N.N回合已计入（组合N层，BOSS_RACE_SLIPPERY_TAX）」。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增 oss_race_slippery_tax_per_layer=0.25（8 层 ≈ +2.0 回合，对应 ~3~4 hit/回合的破层速率）；0 严格回滚旧口径。
- sts2-ascend/brain/selfcheck.py：3br-slip-tax 夹具锁定四分支——非滑溜组合不加税；滑溜组合贴线卡组（3×15伤）税后由可赢翻为必败且带滑+2.0/组合门 0/1 分账；per_layer=0 严格回滚；税后仍可赢的强卡组（3×20伤）可行侧账面自报破层税；端到端翻转带内同一篝火裸口径回血、税后必败弃疗改锻造。

## EXPECTED_SIGNAL

未来 3~10 局：一幕前夜篝火理由出现 BOSS_RACE_SLIPPERY_TAX 留痕（可行侧账面或判死 note）；对墨影幻灵幕的贴线对局锻造占比上升、100% 进场整管打空案例减少；战斗端 SLIPPERY_TTK_OBS 与前夜税可逐局对账（预演 ttk 与实战破层期量级吻合）。有效信号：F17 对 VANTOM 的战损下降或首胜。证伪/回滚条件：10 局内税留痕出现但对 VANTOM 战损/结局无变化，或税把非滑溜 Boss（仪式兽/KIN）前夜误伤率推高（判死后获胜样本）——置 oss_race_slippery_tax_per_layer=0 即整体撤回。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（含新 3br-slip-tax 夹具，改后复跑仍 OK）。
- py -3 -B sts2-ascend/tests/test_boss_race_sustain.py：2 tests OK。
- git diff --check 通过；完整 diff 已回读，仅 knowledge.py/policy.py/selfcheck.py 三个生产/测试文件 + 本报告与口播短评；未触碰在线状态（runs/stats/policy.json/lessons.md 等只读路径零改动）；工作树中宿主挂载的 .review_evidence/ 与无关超长路径资产删除遗留不纳入本批。

## REPLAY

retry_resolution: 20260901-000605-1788192365526162900-0b9c97f5 no_valid_change（完整 lineage 可读：provider 未开始工作、候选 patch 0 字节经认证为空，当前 HEAD 无其可重实现内容；本批假设与改动全部基于 runs 5~6 原始证据独立得出）


# 第 53~88 局批复盘：竞速判死台账 43% 假阳性已闸住篝火端，路径端必败豁免仍裸奔——入场线豁免接入同一审计闸

日期：2026-09-06

## HYPOTHESIS

race_audit 台账「判死入锁→实战获胜 41/95（43%≥30%）」（本批 run 63 篝火留痕）已把「竞速必败」标签证伪为近半数假阳性；篝火端早由 RACE_AUDIT_HEAL_OVERRIDE 按同账同阈保住回血，而路径投影的「竞速必败预演成立→Boss 入场血量线豁免」（eve_doomed 即整幕免掉续航罚分）是消费链上最后一个仍把判死当确定结论的裸奔口。给豁免接入同一台账闸后，假阳性体制下入场线恢复计价，路径端重新获得「续航路线 vs 战力路线」的真实分辨力。

该假设可证伪：未来 3~10 局若 RACE_AUDIT_DOOM_WAIVER_GATE 留痕出现但被闸幕里的入场血量分布、休整/续航路线占比与 Boss 战结局均无变化，或豁免继续触发而闸从不显形，则假设不成立，置 `boss_entry_doom_waiver_audit_gate=False` 一键回滚到判死即豁免旧口径。

## EVIDENCE

- 本批 8 局全负、7 局死于 Boss（F17×3/F33×2/F48/F28 精英）。run 63/68/78/83 的路径留痕均含「竞速必败预演成立，Boss入场血量线豁免（满血亦追不上击杀曲线，续航罚分不计）」——豁免在四个独立对局整幕生效。
- 同批 run 63 篝火留痕「RACE_AUDIT_HEAL_OVERRIDE：竞速判死后获胜41/95（43%≥30%）」——同一本台账已在篝火端否决必败弃疗，路径端豁免却无任何对账。
- 最新死亡局 run 88（ZX6TDLQSV0W7，F17 灵魂异鱼）176 条决策链已逐条检查：F16 前夜组合全称门放行判可行→回血 8 点→100% 进场，实战 5 回合阵亡（掉血80｜自损62，T1 即付 8 血黄金构图）；竞速审计 T2 判死。预演两个方向都在错：判死的 43% 实战获胜，判可行的整管打空。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：路径投影的必败豁免改为先算 `_doom_waiver`，`boss_entry_doom_waiver_audit_gate`（默认开）且 race_audit 达到 `boss_eve_race_audit_heal_min_latched`/`_win_rate` 同阈时否决豁免、入场血量线续航罚分照常计价，并留「竞速判死后获胜W/L，Boss入场线豁免被审计闸否决（RACE_AUDIT_DOOM_WAIVER_GATE）」可 grep 标记；台账缺失/不足、判死可靠、开关关闭或台账字段异常时严格回落旧豁免口径。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增 `boss_entry_doom_waiver_audit_gate=True`（False 即整体回滚），复用既有审计阈值键不新增旋钮。
- sts2-ascend/brain/selfcheck.py：3br-waiver-gate 夹具锁定三分支——台账 40%≥30% 时豁免被否决且带 GATE 留痕；开关关闭严格回滚旧豁免；台账 20%<30% 时豁免不误伤。夹具图自带 nodes[].children（旧 br_audit_map_reason 的图缺 children，_to_boss=False，两侧留痕都不会显形）。

## EXPECTED_SIGNAL

未来 3~10 局：判死幕的路径理由出现 RACE_AUDIT_DOOM_WAIVER_GATE 留痕且可与同决策 eve_doom_note/竞速预演账面对账；被闸幕里「进Boss血量预计X%<Y%，优先续航路线」留痕回归、休整/续航节点占比上升；「竞速必败预演成立…豁免」触发率下降。有效信号：被闸幕的 Boss 入场血量分布上移或 Boss 战损/结局改善。证伪/回滚条件：闸留痕出现 3 局以上但入场血量、选路与 Boss 结局均无变化，或闸把判死可靠幕（台账 <30%）误伤——置 False 整体撤回。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（含新 3br-waiver-gate 夹具）。
- 独立探针：台账 41/95 时豁免被否决并带 GATE 留痕；无台账时旧豁免原样触发。
- git diff --check 通过（仅宿主挂载的超长路径资产删除遗留告警，与本批无关）；完整 diff 已回读，仅 knowledge.py/policy.py/selfcheck.py 三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md 等只读在线状态。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 93~148 局批复盘：换向阻尼与同局对冲的相位错配——F33 型死亡局把竞速先验折算率名降实升推向上限

日期：2026-09-06

## HYPOTHESIS

第 494 批设计「同局先降后释净额归零的诚实对冲」以两通道同步长为前提；第 915~916 批换向阻尼（KILL_RACE_OSC_DAMP）加入后，同局两通道仍各按「上局落盘净额」判换向，相位恰使降通道折半而释通道全速——F33 型死亡局（打败一幕 Boss 后死于二幕 Boss）净步长系统性为正，0/150 胜生涯里 Boss 竞速败北证据被同局释放反超，kill_race_prior_eff 单调漂向 0.72 上限，「饥饿链全顶格后的第五级下调」名存实亡。

可证伪预期：本改动生效后 3~10 局内，F33 型死亡局 lessons 中 kill_race_prior_eff 的局内净变化 ≤0 且释放留痕带「换向阻尼：同局净步长」；旋钮不再单调漂向 0.72。若 F33 型死亡局净额仍 >0，或非 Boss 跨幕死亡局（bsd2 型纯释放）被误阻尼，则证伪/回滚：policy.json 写 kill_race_same_run_damp=false 一键撤回（回滚=旧版口径，零差异）。

## EVIDENCE

- 本批 12 局全负：7 局死于 F33（二幕 Boss，同局先降后释型）、4 局死于 F17、1 局 F27。lessons 台账逐局核对：0.65→0.64→0.67、0.67→0.66→0.69、0.69→0.68→0.71——每场 F33 型死亡净 +0.02；当前 policy.json eff=0.7033（last_step=-0.0103），距 0.72 上限仅 0.017。
- 相位机制复现：上局净额 +0.02 → 本局降通道判换向减半（-0.009）；同局释通道仍读上局落盘 +0.02 → 同向全速 +0.03；局末落盘净 +0.021 → 下局降通道再减半……死亡证据方向被系统性反转。
- selfcheck 旧夹具 3bs-3 e 恰好把该缺陷固化为预期（同局降 -0.015、释 +0.03、净 +0.015 落盘）——本批以新证据翻案并同步夹具。
- failed_review_replay.requested_packages 为空，无失败包需重实现。

## PRODUCTION_CHANGE

- sts2-ascend/brain/reflect.py：`_kr_flip_damped_step` 新增可选 reference 参数——非零且 `kill_race_same_run_damp` 开启（默认）时优先于上局落盘值判换向，留痕改标「同局净步长」；同局释放通道（final_floor≥18）调用处传 `reference=_kr_net`。reference 为 0/None（本局降通道未施加）时行为与旧版严格一致，跨局各通道（bsd1~bsd4 型）零波及。同步更新 494 批「净额归零」旧注释为现行语义。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 `kill_race_same_run_damp=True`（false=旧版口径一键回滚）。
- sts2-ascend/brain/selfcheck.py：3bs-3 e 夹具翻案为新预期（0.63→0.6225，净 -0.0075 落盘，留痕含「同局净步长」）；新增 f) 夹具验证 same_run_damp=false 严格回滚旧净账（0.645/+0.015）；`_kr_damp_knowledge` 助手加 same_run_damp 形参。

## EXPECTED_SIGNAL

未来 3~10 局：① F33 型死亡局 lessons 出现「换向阻尼：同局净步长 -0.0X」且局内净变化 ≤0；② eff 停止向 0.72 单调漂移，竞速败北证据重新真实下拉；③ bsd2 型纯释放局（精英/普通跨幕死亡）释放步长不受本改动影响。证伪/回滚：F33 型死亡局净额仍 >0、纯释放局被误阻尼，或 10 局内 F17/F33 Boss 战绩与竞速预演口径无任何变化——policy.json 置 kill_race_same_run_damp=false 整体撤回。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（含翻案后的 3bs-3 e 与新增 f) 回滚夹具）。
- git diff --check 通过；完整 diff 已回读，仅 knowledge.py/reflect.py/selfcheck.py 三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md 等只读在线状态（克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关）。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 153~157 局批复盘：謦欬成长卡组首窗实测 dpt 系统性低估，T2 即判死入锁——竞速 dpt 以同尺引擎先验为首窗下限

日期：2026-09-06

## HYPOTHESIS

白绮斩杀竞速的实测 dpt 在开账首窗（_krace_turns 2~4）对謦欬成长卡组系统性低估：T1/T2 的能量大量买成长能力牌（回溯咒文/守恒递归，出牌估值 +59~+124 正是为后续回合产出买单），首窗实测仅 5~14 伤/回合，而同卡组引擎有效先验 31~45——ttk 被放大 3~5 倍，T2 即判死入锁。race_audit 台账 won/latched=119/250=47.6% 久高于 30% 预注册线的根源是首窗实测口径失真，而不是第 21~48 批处理的自付污染（该批謦欬隔离落地后段 88/175=50.3%，未降反升，其 <30% 目标已被证据证伪；但隔离同时压住了败局全攻自证闭环——本批五局「败局竞速」零显形——故不做整键回滚，改修首窗口径）。

该假设可证伪：未来 3~10 局若 race_audit won/latched 不降至 <30%、入锁时刻不后移（T2 占比不降），或死亡形态转为长回合磨死（战斗回合数显著上升且掉血增大，914-F5 型流血复活），则假设不成立，policy.json 置 vivhite_race_dpt_prior_floor_turns=0 一键回滚裸实测口径。

## EVIDENCE

- stats.race_audit：latched 250 / won 119 = 47.6%；第 21~48 批落地时 31/75=41.3%，落地后段 88/175=50.3%——謦欬隔离未使假判死率下降。
- 本批 5 局逐场对照：13 场入锁 7 场实战获胜——153-F31（T2锁→4回合胜）、154-F12（T2→7）、156-F15（T2→5）、156-F17（T2→7）、156-F31（T10→13）、157-F17（T2→9）、157-F21（T3→5）；入锁全部发生在 T2/T3 首窗。
- 同决策留痕的口径落差：157-F22 T1「先验31伤/回合」、157-F17 T2「实测6伤/回合×1.35→7」、156-F17 T2「实测6伤/回合」、153-F31 T2「实测6伤/回合」——首窗实测为先验的 1/5~1/2。
- 同批 run 157（LFJEC4VNJ74A，F22 CHOMPER 阵亡）302 条完整决策链已逐条检查：F21 T1/T2 回溯咒文（hp-cost 6，估值 +59.15，recovery-copy=77）与守恒递归+（hp-cost 10，估值 +124.25，recovery-copy=154）——出牌评分已把成长能力牌的未来产出计价，竞速投影却按当下实测速率判死，同一张牌在两条链路估值方向相反。
- 上一批（93~148）同局阻尼已落地；本批 eff 0.66→0.69 为 bsd2 型纯释放，非该机制回退。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：`_combat_kill_race_projection` 实测分支（_krace_turns≥2）在换挡上浮之后新增首窗先验下限——白绮且 `vivhite_race_dpt_prior_floor_turns`（默认 4）>0 且 2≤_krace_turns≤N 时，实测 dpt 以 `deck_effective_burst(deck)×kill_race_prior_eff`（与先验分支同公式、同 eff 演化键）为下限，生效时留「首窗实测X伤/回合低于引擎先验下限Y（謦欬成长卡组换挡期，竞速dpt取先验下限，VIVHITE_RACE_DPT_PRIOR_FLOOR）」并改用先验下限口径；先验已含引擎授信与悲观折算，下限生效不再叠换挡上浮；窗口外、键=0、非白绮 profile 严格维持旧口径。先验同样反映弱卡组（无弹药卡组先验亦低），不捂住真弱卡组判死。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 `vivhite_race_dpt_prior_floor_turns=4`（0=一键回滚）。
- sts2-ascend/brain/selfcheck.py：3prf 夹具锁定四分支——开键下限生效不判死且带留痕（池 110、意图 10、实测 6→8.1 vs 先验 16.5，ttk 6.7≤阈值 10.07）；键=0 严格回滚裸实测判死（ttk 13.6>10.07）；窗口外（_krace_turns=5）不生效照常判死；非白绮 profile 不受影响。

## EXPECTED_SIGNAL

未来 3~10 局：① race_audit won/latched 降至 <30%（同阈同账，可直接与 119/250 对账）；② 入锁时刻后移，T2/T3 首窗入锁占比下降；③ 战斗理由出现 VIVHITE_RACE_DPT_PRIOR_FLOOR 留痕并可与同决策卡组先验对账。有效信号：边际假判死消失后 Boss/长战战绩改善或首胜。证伪/回滚条件：won 率不降、留痕出现但判决/结局分布无变化，或死亡形态转为长回合磨死——policy.json 置 vivhite_race_dpt_prior_floor_turns=0 即整体撤回。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（含新增 3prf 四分支夹具）。
- py -3 -B sts2-ascend/tests/test_boss_race_sustain.py：2 tests OK。
- git diff --check 通过（仅宿主挂载的超长路径资产删除遗留告警，与本批无关）；完整 diff 已回读，仅 knowledge.py/policy.py/selfcheck.py 三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md 等只读在线状态。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 158~164 局批复盘：謦欬权重触底钳制零留痕、同局回收反向——生命支付通道补齐顶格代谢与同局矛盾守卫

日期：2026-09-06

## HYPOTHESIS

`vivhite_param_life_cost_weight` 在 BOUNDS 下限 -3.0 触底时，謦欬死亡收紧（拿牌口径 -0.05 与实付加码 -0.05）被 `_adj` 静默钳制、lessons 零留痕，而同局 F18+ 部分胜利回收（+0.025）照常触发——0/164 生涯里几乎每局行至 F18+，旋钮被死亡证据钉向地板又逐局抬离，主导死因（致命战实测自损占掉血 ≥50%）在 lessons 中完全不可见，违反项目既定的「顶格旋钮代谢：余量不足停止加码并显式留痕」原则（同文件 kill_bonus/爆毙链均有触底留痕，謦欬通道是漏网者）。

该假设可证伪：未来 3~10 局若 lessons 在权重触底局仍无「触底…停止吸收并留痕」文本，或自损占比 ≥50% 的 F18+ 死亡局仍出现「生命支付权重部分胜利回收」改值行，则本批改动未生效或被绕过。

## EVIDENCE

- 第 164 局（S65QRQYDHXGE，F25 精英 INFESTED_PRISM 阵亡）：致命战自损 73/掉血 90=81%≥50%，应双档收紧 -0.10；但入局权重已 -3.00 触底，lessons 只见「-3.00 → -2.98（行至 F25 部分胜利回收）」——收紧蒸发、回收反向，policy.json 现值 -2.975 正是该振荡态。本批决策链尾部逐条核对：23:03:37 1 血全体手牌 blocked_by_hook 空过 2 能量后阵亡，謦欬实付是压垮血线的主因之一。
- 自损主导在本批反复出现且不限于败局：158 局 F17 Boss 自损 69/掉血 55、164 局 F17 Boss 自损 94/掉血 44（获胜局自损超敌方伤害两倍）、164 局 F22/F24 敌方零伤害仍自损 28/25——生命支付估值偏低的证据强度持续高于旋钮行程。
- 163 局 lessons「-2.98→-3.00（謦欬卡组阵亡收紧）」→164 局「-3.00→-2.98（回收）」：相邻两局一降一升，旋钮钉不住证据位置。
- reflect.py 旧代码：謦欬收紧通道（拿牌口径+实付加码）直接 `_adj`，钳制时 `abs(new-old)<1e-9` 零 append；回收通道（final_floor≥18）无任何同局死亡证据守卫。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/reflect.py：
  ① 謦欬实付主导死亡的统一判定（`_self_dominant_death`：非胜利、非摆烂、致命战 self_hp_loss/hp_lost ≥50%）上提至 finalize_run 顶部，收紧通道与回收通道共用同一口径；
  ② 收紧通道新增 `_lc_tighten` 触底检查——余量不足一步（0.05）时不改值并显式留痕「触底（余量X<步长0.05）…停止吸收并留痕（接替手段待复盘设计）」，与同文件 kill_bonus/爆毙链的顶格代谢同原则；
  ③ F18+ 部分胜利回收新增同局矛盾守卫——`_self_dominant_death` 为真时回收让位并留痕「部分胜利回收让位于同局謦欬实付证据」，不再把被本局死亡证据要求收紧的旋钮抬离钉点。
  非自损主导死亡、缺 self_hp_loss 旧记录、摆烂死、胜利回收与非白绮 profile 行为与旧版严格一致。
- sts2-ascend/brain/selfcheck.py：3prg 夹具锁定三分支——触底钳制不改值且有留痕（-3.0 保持）；自损主导同局 F18+ 回收让位（-2.00→-2.10，无 +0.025）；非自损主导 F18+ 回收照旧（-2.00→-2.05→-2.025）。
- 回滚条件单一：把 `_lc_tighten` 换回原直接 `_adj` 并删除回收守卫即可；无新增 policy 键。

## EXPECTED_SIGNAL

未来 3~10 局：① lessons 在权重触底局出现「触底…停止吸收并留痕」文本（收紧证据不再蒸发）；② 自损占比 ≥50% 的 F18+ 死亡局出现「部分胜利回收让位」，权重不再名降实升；③ 权重在自损主导期保持 -3.0 钉底，复盘可直接据触底留痕计数设计接替手段（如生命支付牌的拿牌端门槛）。证伪条件：上述留痕缺席或回收改值行仍在自损主导局出现。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（含新增 3prg 三分支夹具，既有 3pra 单/双档口径不变）。
- 完整 diff 已回读：仅 reflect.py/selfcheck.py 两个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md 等只读在线状态（克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关）。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 165~169 局批复盘：謦欬权重触底接替手段落地——负净值謦欬仍过出牌阈值，新增出牌余量门接收取代纯留痕

日期：2026-09-07

## HYPOTHESIS

ivhite_param_life_cost_weight 触底 -3.00 后（上批复盘已补「停止吸收并留痕」），謦欬死亡证据仍无真正的行为接替：估值税只改候选之间的相对排序，改不了「vs 结束回合」的比较——第 169 局 F17 Boss 战 T1 决策链实锤 VIVHITE_LIVE_ESTIMATE=-16.30（COMPLEMENTARY_AFTERIMAGE，hp-cost=6）与 -6.75（TERMINATION_CONDITION）两张负净值謦欬牌仍被打出，致命战自损 71/掉血 78=91% 阵亡。剩余有效杠杆是把謦欬实付折进出牌门槛本身。

该假设可证伪：未来 3~10 局若 lessons 出现「证据改接謦欬出牌余量门」且决策链出现「謦欬出牌门拦下」（VIVHITE_HP_PLAY_MARGIN_GATE），但致命战自损占掉血 ≥50% 的比例不下降，或拿牌/出牌端输出饥饿显著加剧（Boss 战 ttk 与 race_audit 判死后胜率恶化），则假设证伪，policy.json 写 vivhite_hp_cost_play_margin=0 一键回滚。

## EVIDENCE

- 第 169 局（EUH5AA8D7P4D，F17 Boss WATERFALL_GIANT 阵亡）：自损 71/掉血 78=91%；决策链 F17 T1 逐条核到两张负净值謦欬牌连打（-16.30/-6.75），78 血 100% 进场仍阵亡；本局拿牌 14 张中 12 张生命支付牌。
- 同批同型证据达到阈值：167 局 F17 Boss 自损 76/掉血 78=97%（12 张生命支付牌）、168 局 F17 Boss 自损 117/掉血 71（自损超敌方伤害）与 F21 自损 79/掉血 81=98%（13 张）、169 局 91%；169 局 lessons 两次出现「触底…停止吸收并留痕（接替手段待复盘设计）」——接替手段正是本批交付物。
- 旧杠杆边界：play_threshold=0.4 存在，但 _score_play 的通用伤害分可轻易盖过 character_estimate 的负值；158/61 张白绮牌带 life_calculation_cost>0（含起手 4+4 基础牌），拿牌端「密度上限」类设计会把整套机制锁死，不可行——必须落在出牌端 vs 结束回合的比较上。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：
  ① 新增 _vivhite_hp_pay（与 _rescue_block_tradeoff 同口径：LifeCost 含绯红仪式附加 − Margin 抵扣；非白绮/目录外牌恒 0）；
  ② _combat 手牌循环新增謦欬出牌余量门（VIVHITE_HP_PLAY_MARGIN_GATE）：非致死回合謦欬实付每点按 vivhite_hp_cost_play_margin 抬高该候选的出牌门槛，仅拦「已过普通阈值但未过抬升阈值」的候选并留痕「謦欬门拒」；被拦候选同时退出 marginal_best 与残能救场通道（付血换不空过正是本门要拦的死循环），end_turn 原因披露拦下清单；致死回合豁免（买命/抢斩杀当场兑现）；margin=0 或缺键严格回滚旧行为，非白绮角色零改动。
- sts2-ascend/brain/reflect.py：BOUNDS 新增 vivhite_hp_cost_play_margin=(0.0, 3.0)；_lc_tighten 触底分支由纯留痕改为改接——权重余量不足一步时证据改接余量门（每级 +0.5）并留痕「证据改接謦欬出牌余量门」，余量门也顶格后才「双旋钮全尽…彻底停止吸收并留痕」。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增 vivhite_hp_cost_play_margin=0.0（静态键，0=关闭）。
- sts2-ascend/brain/selfcheck.py：3prg 夹具更新（触底双档证据改接余量门 0→1.0 且留痕；双顶格封账不改值且留痕）；新增 3prh 决策链夹具（margin=0 出牌=旧行为；margin 极高时同手牌 end_turn 且带拦门留痕、残能救场不得绕行；致死回合豁免仍出牌）。
- 回滚条件单一：policy.json 写 vivhite_hp_cost_play_margin=0 即恢复旧行为；reflect 改接段删除即恢复纯留痕。

## EXPECTED_SIGNAL

未来 3~10 局：① lessons 在謦欬卡组阵亡局出现「证据改接謦欬出牌余量门」且 margin 自 0 上行；② 决策链出现「謦欬出牌门拦下【X】实付N血」与候选「謦欬门拒」状态；③ 致命战自损占掉血比例降至 <50%，F17/F21 型自损主导阵亡减少。证伪/回滚：拦门留痕 ≥3 局但自损占比无变化，或 Boss 战 ttk/race_audit 显著恶化 → margin 归零回滚。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（3prg 更新 + 3prh 新增三分支，既有夹具全部通过）。
- py -3 -B sts2-ascend/tests/test_boss_race_sustain.py：2 tests OK。
- 生产探针（隔离 clone 内临时 Knowledge）：margin=0 出牌=旧行为零差异；margin=50 同手牌 end_turn 且带拦门留痕、残能救场不绕行；致死回合豁免出牌；reflect 触底局 margin 0→0.5→1.0 双档改接留痕、双顶格封账留痕。
- git diff --check 通过（仅宿主挂载的超长路径资产删除遗留告警，与本批无关）；完整 diff 已回读，仅 knowledge.py/policy.py/reflect.py/selfcheck.py 四个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md 等只读在线状态。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 187~196 局批复盘：Boss 血池台账系统性虚高 4~20 倍——竞速预演 ttk 同倍率高估，前夜误判必败弃疗，写入侧原生封顶

日期：2026-09-07

## HYPOTHESIS

在线 hp_pool 学习台账相对原生游戏快照系统性虚高 4~20 倍，导致 `boss_race_vitals` 给出的 Boss 血池均值同倍率虚高，竞速必败预演 `ttk=pool/dpt` 被系统性拉长，前夜篝火把可赢/贴线对局误判必败而弃疗转锻造，战斗端进入败局全攻姿态，构成 188/193/195/196 四局 F33 二幕 Boss 阵亡的共同上游。

该假设可证伪：未来 3~10 局若 `stats.hp_pool_native_clamp_obs.clamped` 持续增长且 `max_ratio` 维持 >4，且前夜留痕中「Boss血池均值」降回原生量级（一幕 173~252、二幕 321~408）、doom 判定减少，则假设成立；若钳制计数零增长（台账本来就干净），则假设证伪，policy.json 写 `hp_pool_native_clamp_factor=0` 一键回滚。

## EVIDENCE

- 台账 vs 原生逐个对账（profiles/vivhite/stats.json 只读读取 × game/v0.111.0 原生 runtime/mechanics）：KNOWLEDGE_DEMON 账面 6462.6/2.87≈2254 vs 原生 379（5.9×）；VANTOM ≈823 vs 173（4.8×）；CEREMONIAL_BEAST ≈1455 vs 252（5.8×）；LAGAVULIN_MATRIARCH ≈4801 vs 222（21.6×）；KIN 双子 ≈2051 vs 248（8.3×）；普通怪同型：MYTE ≈3305 vs 61（54×）、TOADPOLE ≈451 vs 21（21×）、SHRINKER_BEETLE ≈250 vs 38（6.6×）。
- 活数交叉证实：196 局（0VJUNJDY23ZT）F33 实战长战注记「敌血池379」与原生 KNOWLEDGE_DEMON=379 完全一致——采样口径本身正确时读数正确，但入账历史均值 2254。
- 消费侧实锤：188 局（VVQC85H1H6TR）前夜留痕「竞速预演：击杀需85回合＞满血可存活5回合（Boss血池均值2844、火力18/回合，先验输出34/回合…）必败局的伤害会流到打死为止」→ 弃疗 → F33 阵亡；193/195/196 同型 F33 死亡。188 局按原生二幕血池 ~321~408 重估 ttk≈10~12 回合，虽仍偏劣但远非 85 回合级绝望，联合能量复核与组合门的放行空间被虚高账面整体压死。
- 衰减与入账路径已排除：`_decay_stats` 对 sum/n 同乘保持比率；`commit_enemy_fight` 唯一写入口、agent 端分段取 max——均不改变均值口径。虚高的具体放大机制（首帧采样之外的来源）未完全定位，故本批只落写入侧封顶 + 观测，不臆改采样。
- failed_review 目标包 20260907-075516-1788738916971161100-9bea4999 完整 lineage 已读：index.json complete=true；manifest 记录 online_runtime（宿主 git checkout 120s 超时），command_count=0、file_change_count=0；wip.patch 0 字节、report.md 0 字节；retry_candidate.patch 5424083 字节全部为新忽略文件删除快照（0 行新增、43403 行删除、0 个新文件），无任何可重实现的有效改动。

## PRODUCTION_CHANGE

- sts2-ascend/brain/knowledge.py：
  ① 新增 `Knowledge._native_hp_pool_clamp`（HP_POOL_NATIVE_CLAMP）：comp 成员原生 max_hp 合计 × `hp_pool_native_clamp_factor`（默认 1.5，覆盖进阶血量上浮与 min/max 散布）作为写入上限，超限样本封顶并把次数/最大倍率/最近组合记入 `stats["hp_pool_native_clamp_obs"]`（顶层键，不被 `_decay_stats` 衰减）；native 不可用、unknown 组合、成员缺数据、factor≤0 或任何异常一律原样返回（与旧版严格一致）；
  ② `commit_enemy_fight` 入口处对 hp_pool 统一钳制一次，Boss 分幕子账本与全量账共用钳制后样本；
  ③ DEFAULT_POLICY 新增 `hp_pool_native_clamp_factor=1.5`（≤0 即回滚）。
- sts2-ascend/brain/selfcheck.py：新增 3br-pool-clamp 夹具（2254→568.5 钳制 + 观测计数/倍率断言；界内 400 原样通过；native 缺失组合 9999 原样入账；factor=0 后同型样本恢复全价）。
- 不改任何评分/阈值/动作选择路径；只改学习台账写入。回滚条件单一：policy.json 写 `hp_pool_native_clamp_factor=0`。

## EXPECTED_SIGNAL

未来 3~10 局：① `hp_pool_native_clamp_obs.clamped` 逐局增长、`max_ratio` 维持 >4（确认虚高仍在发生并被封堵）；② 前夜/攻坚留痕的「Boss血池均值」随新样本入账逐步回落到原生量级；③ F33 型「击杀需数十回合」误判减少，篝火弃疗率下降、RACE_AUDIT 判死后实战胜率不再恶化。证伪/回滚：钳制零触发（账面本干净）→ 假设证伪回滚；钳制触发但 Boss 战战绩进一步恶化 → factor=0 回滚并重新审查原生对照口径。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（新增 3br-pool-clamp 四分支，既有夹具全部通过）。
- 完整 diff 已回读：仅 brain/knowledge.py（+58）与 brain/selfcheck.py（+45）两个文件；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

retry_resolution: 20260907-075516-1788738916971161100-9bea4999 no_valid_change（完整 lineage 已读：online_runtime 宿主 checkout 超时、模型零工作；wip.patch/report.md 均 0 字节；retry_candidate.patch 仅含忽略文件删除快照、0 行新增，无有效改动可在当前 HEAD 重实现；本批生产闭环由上方 HP_POOL_NATIVE_CLAMP 独立承担）

# 第 197~224 局批复盘：写入侧封顶挡不住历史虚高样本的比率守恒滞留——读取侧 boss_race_vitals 逐组合均值接入同一原生上限

日期：2026-09-07

## HYPOTHESIS

第 187~196 批落地的写入侧 HP_POOL_NATIVE_CLAMP 只封新样本，而 `_decay_stats` 对 hp_pool_sum/n 同比缩放（比率守恒）——历史虚高样本的账面均值在数学上永不随新样本回落；读取侧 `boss_race_vitals` 聚合不做同源封顶时，消费端（前夜竞速预演 ttk=pool/dpt、竞速及格线 required_deck_burst）将无限期按 4~20× 虚高血池判必败，上批 EXPECTED_SIGNAL ②「均值回落原生量级」不可能在有限局数内兑现。

该假设可证伪：未来 3~10 局若 `hp_pool_native_clamp_obs.read_clamped` 逐局增长且前夜/攻坚留痕的「Boss血池均值」回落到 ≤ 原生 max_hp 合计×1.5（一幕 ≲480、二幕 ≲620）、「击杀需N回合」回到十回合级，则假设成立；若 read_clamped 零增长且留痕均值纹丝不动（消费端未走 boss_race_vitals），则假设证伪。回滚单一：policy.json 置 `hp_pool_native_clamp_factor=0`，写/读两侧同键同关。

## EVIDENCE

- 本批两次 F16 前夜留痕（runs 只读检索）：20260907-093535_2A4MRUCJZG8D「竞速预演：击杀需92回合＞满血可存活4回合（Boss血池均值2986、火力18/回合，先验输出32/回合…）」；20260907-112909_B0YWRLH337GZ「击杀需99回合＞满血可存活5回合（Boss血池均值3126…）」——同一留痕尾部 native 分账「THE_INSATIABLE321」，账面为原生 321 的 9.3~9.7 倍。
- stats.json 只读对账：THE_INSATIABLE hp_pool 账面 5648.9/3.84≈1472（act 子账 1909）、KNOWLEDGE_DEMON 6838.2/2.93≈2335（原生 379）——187~196 批钳制落地后账面均值没有可观测回落。
- `hp_pool_native_clamp_obs`（写侧）：clamped=13、max_ratio=3.667、last_comp=WRIGGLER——写入侧钳制确在逐局触发；均值不动证明缺口在读取侧而非写入侧。
- 消费侧死循环仍在：本批 run 224（Y9EN0PX2TY6H，F17 KIN_FOLLOWER+KIN_PRIEST 阵亡）完整决策链已逐条检查，前夜弃疗/翻转裁决继续按虚高 ttk 计价；race_audit 台账 won/latched=142/324=43.8%，仍远高于 30% 预注册线。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/knowledge.py：
  ① 抽出 `_native_hp_pool_bound(comp_id)`（组合成员原生 max_hp 合计 × hp_pool_native_clamp_factor；factor<=0/native 缺失/任何异常返回 None），写入侧 `_native_hp_pool_clamp` 改调它，写侧行为与观测键（clamped/max_ratio/last_comp）严格不变；
  ② 新增 `_native_pool_mean_clamp(comp_id, mean)`（HP_POOL_READ_CLAMP）：读取侧对逐组合账面均值套用同一原生上限，钳制事件记入 hp_pool_native_clamp_obs 的 `read_clamped`/`read_max_ratio`/`read_last_comp` 独立分账（不污染写侧计数），factor<=0 时 bound 为 None、读侧随写侧一并回滚；
  ③ `boss_race_vitals` 分幕聚合与全量回落两条路径都在聚合前对每个组合的账面均值过读侧钳制（等权口径不变：钳后均值×n 累加）。
- sts2-ascend/brain/selfcheck.py：新增 3br-pool-read-clamp 夹具五分支——分幕口径虚高均值 2254→568.5 钳制且 read 分账齐全、写侧 clamped 零污染；全量回落口径同钳；界内均值 400 原样通过且观测不增；native 缺失组合 9999 严格维持旧虚高口径；factor=0 后读侧恢复旧虚高均值 2254。
- 不改任何评分/阈值/动作选择公式；只改学习台账读取口径。回滚条件单一：policy.json 写 `hp_pool_native_clamp_factor=0`（写/读同关）。

## EXPECTED_SIGNAL

未来 3~10 局：① `hp_pool_native_clamp_obs.read_clamped` 逐局增长、`read_max_ratio` 维持 >4（确认历史虚高仍在账面且已被读取侧封堵）；② 前夜/攻坚留痕「Boss血池均值」≤ 原生合计×1.5（一幕 ≲480、二幕 ≲620），「击杀需N回合」回到十回合级，可与同留痕尾部「native校准/分账」注直接对账；③ 边际贴线对局的前夜裁决（回血 vs 锻造）与 RACE_AUDIT 判死后胜率分布出现可观测变化。证伪/回滚：read_clamped 零增长且留痕均值不变 → 假设证伪并复查消费路径；钳制生效但 Boss 战战绩进一步恶化 → factor=0 整体撤回。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（新增 3br-pool-read-clamp 五分支，既有 3br-pool-clamp 写侧夹具与全部既有夹具通过）。
- git diff --check 通过；完整 diff 已回读：仅 brain/knowledge.py 与 brain/selfcheck.py 两个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 231~243 局批复盘：謦欬余量门顶格后在低危长战制造放血死循环——新增僵局放行（VIVHITE_HP_GATE_STALL_BREAK）

日期：2026-09-07

## HYPOTHESIS

`vivhite_hp_cost_play_margin` 被死亡证据推至顶格 3.0 后（謦欬双旋钮全尽、证据已停止吸收），余量门在低危小怪战每回合拦下 2 血攻击牌，残能救场通道转而反复付 2 血打出格挡牌——战斗被人为拖长数十回合，累计自损反超敌方伤害，「防自杀门」异化为「放血死循环」。该假设可证伪：未来 3~10 局若低危长战（单场 ≥15 回合）仍出现「连续低危拦截 N/6」进度爬满却不出现「VIVHITE_HP_GATE_STALL_BREAK」放行留痕，或放行后该类战斗的自损/回合数不降，则本批改动未生效或假设错误。

## EVIDENCE

- 第 243 局（HKCW2VWRK5L0，F17 Boss VANTOM 阵亡）完整 316 链已逐条深读：F3 树枝/树叶史莱姆战拖 **56 回合**（自损46~48/掉血39）——逐回合核对，謦欬出牌门在 78 血/意图 0 下仍逐回合拦下【弦光投影】（实付2血），残能救场[IDLE_LEAK_BLK] 转而每两回合付 2 血打【闭域映射】，血线 73→20 几乎全是放血；进 Boss 前的 F3~F15 自损账（14/48/14/10/14/18/3/4）为 F17 败北埋下血债。
- 同型死循环在本批至少三次独立复现：238 局（FJ1PPH55LQFE）F2 战 **76 回合**阵亡（自损64/掉血78，门留痕 45 次，终局 1 血全员 blocked_by_hook）；235 局（2DWFAX5CEC5Y）F3 战 19 回合阵亡（自损46/掉血68，门留痕 17 次）；239 局（DH84M6ANQSHP）F12 战敌方零伤害仍自损 64。
- 机制根因（policy.py 现状）：余量门只按「实付×margin」抬高单卡出牌门槛，不区分攻击/格挡、不计拖延代价；被拦攻击退出残能救场，但格挡类謦欬牌仍可经救场/正常通道付血打出——低意图回合拦门没换来任何减伤，却每场累积 2 血/回合的放血。
- 旋钮侧无路可走：lessons 尾部连续两批留痕「謦欬出牌余量门 3.00 顶格……謦欬证据彻底停止吸收并留痕」，生命支付权重 -3.00 触底——估值/门槛双通道均已饱和，本批不改旋钮、只在行为层拆死循环。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：
  ① 新增每战斗僵局账 `_hp_gate_stall`/`_hp_gate_stall_round`/`_hp_gate_stall_latch`（随 `_combat_stall_check` 的战斗身份切换重置）；
  ② end_turn 收口处维护计数（每回合只动一次）：「回合结束仍有謦欬候选被余量门拦下 且 本回合敌意图被格挡全覆盖（incoming<=my_block，拦门零减伤收益）」才累加，无拦截或高危回合清零；
  ③ 计数达到 `vivhite_hp_gate_stall_turns`（默认 6）后本场把余量门压回 0 并闩锁——仅撤附加门槛，普通评分阈值、致死豁免、零付出牌、非白绮角色行为全部不变；出牌理由留「謦欬门僵局放行（VIVHITE_HP_GATE_STALL_BREAK）」，拦截回合理由追加「连续低危拦截N/M（进度）」。
- sts2-ascend/brain/knowledge.py：新增静态键 `vivhite_hp_gate_stall_turns: 6`（0=一键回滚，旧行为零差异），注释完整记录三局实证。
- sts2-ascend/brain/selfcheck.py：新增 3pri 夹具七分支——阈值前照旧拦截且有进度留痕、同回合多 tick 不重复计数、达标放行且有标记、闩锁后不回归、新战斗重置、意图未覆盖永不计数（含覆盖/未覆盖交替断链）、stall=0 回滚键下零放行零留痕。
- 回滚条件单一：policy.json 置 `vivhite_hp_gate_stall_turns=0`。

## EXPECTED_SIGNAL

未来 3~10 局：① 决策链出现「连续低危拦截N/6」进度注并至少一次「VIVHITE_HP_GATE_STALL_BREAK」放行（可直接与 243-F3/238-F2 同型场景对账）；② 放行战斗的回合数与自损显著低于本批同型死循环（基准：56 回合/自损46、76 回合/自损64、19 回合/自损46）；③ 一幕小怪战后的进 Boss 血量分布上移（本批 F17 Boss 入场血 100% 仍败，但前置放血局 235/238 直接死在一幕）。证伪/回滚：进度注从未出现（门已拦不住或场景不再复现）→ 复查计数口径；放行后同型战斗自损/回合不降或高危战自损占比反弹 ≥50% → policy.json 置 0 整体撤回。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（含新增 3pri 七分支；既有 3prh 余量门三分支与全部既有夹具通过）。
- `git diff --check` 通过（仅宿主挂载的 assets 超长路径删除遗留告警，与本批无关、不入 commit）；完整 diff 已回读：brain/policy.py、brain/knowledge.py、brain/selfcheck.py 三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 244~259 局批复盘：謦欬双旋钮全尽后自损仍在放血——拿牌端零余裕源盲区，新增余裕供给稀缺加分（VIVHITE_MARGIN_PICK_SCARCITY）

日期：2026-09-07

## HYPOTHESIS

謦欬是全目录机制（61 张目录中 58 张 life_calculation_cost>0，初始卡组 9/9 全謦欬），生命支付无法靠「少拿謦欬」回避；余裕（Margin）是唯一在支付端冲抵实付的供给。战斗端估值权重 -3.0 触底、出牌余量门 3.0 顶格（lessons 连续多批「双旋钮全尽，謦欬证据彻底停止吸收并留痕」），但拿牌端对余裕源没有任何稀缺纠偏——静态估值只给 margin_gain×1.25≈+3.75，竞争不过又一张謦欬攻击/技能，卡组长期凑不出余裕供给，自损在各楼层持续≥敌方掉血。该假设可证伪：未来 3~10 局若决策链不出现「余裕供给稀缺加分」留痕，或出现后零无条件余裕源终局占比与战斗自损/掉血比均不回落，则改动未生效或假设错误，policy.json 置 `vivhite_margin_pick_bonus=0` 一键回滚。

## EVIDENCE

- 终局卡组余裕源 vs 成绩对账（runs 只读，catalog margin_gain>0 口径）：本批 16 局中 6 局终局 0 张余裕源——245（F2，自损58/掉血78）、250（F4，自损70/掉血50）、247（F11）、249（F17）、257（F17）、246（F22，自损201>掉血183）——全部早亡或自损反超敌方；最深的两局 251/252（均 F33）恰为余裕源最多的 6/3 张；259 局（F23）拿 17 张生命支付牌、余裕源仅 3 张，致命战自损24/掉血31（77%）。
- 战斗注记全批自损主导：244 F7 自损20/掉血21、250 F2 自损70/掉血50、254 F11 自损18/掉血4、259 F19 自损31/掉血31——自损≥敌方掉血在本批是常态而非尾部事件；双旋钮已饱和（255~259 lessons 反复「謦欬实付加码收紧；双旋钮全尽」），证据再无估值/门槛旋钮可接。
- 机制根因（policy.py 现状核查）：`eval_reward_card` 对余裕源仅有 `estimate_character_card` 的 margin_gain×margin_weight(+1.25) 静态估值；余裕供给既无「卡组已有几台」的存量感知，也无稀缺加分通道（对照：成长引擎有 scaling_engine_pick_bonus 稀缺加分、AoE 有首张 +3、复制件有密度放行）——余裕源在与謦欬攻击的名额竞争中系统性落败。
- 259 局（3ACQ9CYH7NCN，F23 CHOMPER 阵亡）决策链切片已读：EVENT/拿牌理由中余裕从未作为选取依据出现；439 决策中 COMBAT play_card 177 次，自损贯穿 F14~F23 每层（21/36/31/18/31/24）。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：
  ① 新增 `Policy._vivhite_margin_source(card)`——无条件即时余裕源判定：白绮目录内 margin_gain>0 且不带 margin_if 条件（与残能救场 independent_benefit 同口径；INVARIANT 的 margin_if_max_hp_grew_this_combat 等条件余裕不计），非白绮角色/目录外牌恒 False；
  ② `eval_reward_card` 末尾新增稀缺加分：卡组上下文非空、候选为无条件余裕源时，按卡组已有无条件余裕源数线性衰减加分（零源全额 vivhite_margin_pick_bonus、≥vivhite_margin_deck_cap 归零，防为供给囤牌反向注水），detail 留「余裕供给稀缺加分（卡组无条件余裕源N张，+X）」；空卡组上下文（升级/删除/献祭评估）与非白绮角色天然不受影响。
- sts2-ascend/brain/knowledge.py：新增静态键 `vivhite_margin_pick_bonus: 4.0`（0=一键回滚，旧行为零差异）与 `vivhite_margin_deck_cap: 3.0`（稀缺衰减分母/供给上限），注释记录本批实证。
- sts2-ascend/brain/selfcheck.py：新增 3prj 夹具八分支——零源全额 +4.0 且有 detail 留痕；≥cap 归零；1 张存量线性 +8/3（同卡组开/关对账，隔离卡组构成对其他语境项的串扰）；条件余裕候选不吃加分且不计入存量；非余裕源候选零差异；空卡组上下文零差异。
- 回滚条件单一：policy.json 置 `vivhite_margin_pick_bonus=0`。

## EXPECTED_SIGNAL

未来 3~10 局：① 决策链拿牌理由出现「余裕供给稀缺加分」留痕（零源卡组场景应高频出现）；② 终局卡组零无条件余裕源占比从本批 6/16 下降，余裕源张数向 251/252（F33，6/3 张）形态靠拢；③ 战斗自损/掉血比回落（本批常态 ≥100%，目标 <50% 的謦欬实付主导线以下），一幕早亡局（245-F2/250-F4 型）减少。证伪/回滚：留痕从不出现（余裕源候选从未进入奖励池）→ 复查口径；留痕出现但自损占比与早亡率无变化，或深局余裕囤牌挤出输出致 burst 缺口恶化 → policy.json 置 0 整体撤回。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（含新增 3prj 八分支；既有 3prh/3pri 謦欬门夹具与全部既有夹具通过；首轮跨卡组对账夹具因卡组构成串扰误判，已改同卡组开/关对账后通过）。
- `git diff --check` 通过（仅宿主挂载的 assets 超长路径删除遗留告警，与本批无关、不入 commit）；完整 diff 已回读：brain/policy.py（+35）、brain/knowledge.py（+13）、brain/selfcheck.py（+81）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 271~294 局批复盘：esc 入锁被静态联合复核逐 tick 翻案解锁——滚雪球锁持（RACE_ESC_LATCH_HOLD）

日期：2026-09-08

## HYPOTHESIS

esc（滚雪球，_esc_rounds≥2）战斗中，实测口径竞速判死入锁（_krace_latch）后，静态联合能量复核（_race_joint_feasible，平铺常数火力+固定系数通胀）逐 tick 在「可行/判死」边界给出相反答案并解锁——第632批迟滞锁要消除的「提速斩杀/转防守节奏」逐 tick 摇摆病理经联合复核出口复发：防守回合给指数升级的意图送免费复利，全攻回合在残血下放弃格挡，两种策略互相打断、没有一种被连贯执行。滚雪球局的拖延成本是指数项，静态线性复核在边界上注定反复翻案；入锁后不再凭同一复核自我平反（未入锁的判死当 tick 与非滚雪球局出口保留），esc 桶假判死率应向 <30% 预注册线收敛。

该假设可证伪：未来 3~10 局若决策链不出现「RACE_ESC_LATCH_HOLD」留痕（esc 入锁场景不再复现或计数口径有误），或锁持后 esc 桶 race_audit won/latched 不降反升且深局战损/楼层恶化，则假设不成立，policy.json 置 `race_esc_latch_hold=false` 一键回滚旧版逐 tick 翻案。

## EVIDENCE

- 最新死亡局第 294 局（NW3VAZW0D8RY，F11 TERROR_EEL 精英战阵亡）完整 77 链已逐条深读：终局战 T1「防守线复核…维持攻防节奏」→ T5「斩杀竞速投影…全攻提速」（入锁）→ T6「防守线复核…（滚雪球零余量）」（翻案解锁）→ T7 提速（再入锁）→ T8 防守（再翻案）→ T9 提速阵亡——9 个回合内提速/防守交替 7 次，翻案 tick 均带滚雪球零余量标记。
- 同型摇摆在本批另两局独立复现（达 evidence_run_threshold=3）：281 局（CUJAVR30CKX3）F14 精英战 ADADA（T3提速→T4防守→T5提速→T6防守带滚雪球标记→T8提速）；292 局（PA72MZDBFBNL）F24 精英战 ADA（T5/T6提速→T6/T7防守带滚雪球标记→T7提速）。
- race_audit 台账（stats 只读）：latched=414、won=173=41.8% 判死后实战获胜；esc 桶 99/(99+198)=33.3%——连续多批超第802~807批预注册的 30% 收紧线，且该桶系数杆已全部用尽：margin 零余量（454批）、fire inflate 校准 0.40→0.20（808~812批）、dpt uplift_eff 0.20（917~918批），假判死率始终未降。本批 24 局战斗注记 30+ 次「竞速审计：T{N}判死→实战{M}回合」（M 普遍 2~3×N，如 292 局 T2判死→实战14回合）同向佐证。
- 生产现状核查（policy.py `_combat_kill_race_projection`）：`_kr_latched` 强制 race_lost=True 后，联合复核判可行即 `race_lost=False` 且 `_krace_latch=False`——迟滞锁只挡先验口径自我平反，静态复核出口每 tick 都可翻案，与 632 批 F29「七回合交替 5 次」的原始病理同构。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：`if _feas:` 翻案分支新增滚雪球锁持——`_kr_latched and esc_gate and race_esc_latch_hold（默认 True）` 时不再 race_lost=False/解锁，改留「滚雪球锁持：联合复核虽报可行（…），实测入锁不翻案（RACE_ESC_LATCH_HOLD）」（复核结论保留留痕对账）；未入锁（判死当 tick）、非滚雪球局与键置 False 三条路径严格维持旧行为。不改 ttk/tsurv、判决阈值、评分或姿态公式。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 `race_esc_latch_hold: True`（False=一键回滚，旧行为零差异），注释记录三局实证与台账。
- sts2-ascend/brain/selfcheck.py：`combat_flip_probe` 增加 latched/latch_hold/esc_rounds 参数（latch_hold 默认 False，显式隔离既有翻盘比/滑溜夹具语义）；新增 3br-esc-latch-hold 四分支——① 默认开+esc+入锁+复核可行→锁持留痕、不翻案、维持竞速；② 键置 False→严格回滚旧版翻案解锁；③ 非 esc（_esc_rounds=0）→出口不变；④ 未入锁的判死当 tick（esc 仍在）→出口不变。
- 回滚条件单一：policy.json 置 `race_esc_latch_hold=false`。

## EXPECTED_SIGNAL

未来 3~10 局：① esc 入锁战斗的决策链出现「RACE_ESC_LATCH_HOLD」留痕，可直接与 294-F11/281-F14/292-F24 同型场景对账；② 入锁后的滚雪球战斗中「提速斩杀（竞速解除防御压制）」与「维持攻防节奏不全攻」逐 tick 交替消失（本批基准：294-F11 七连交替、281-F14/292-F24 各 ≥2 次）；③ race_audit esc 桶 won/latched 向 <30% 收敛（当前 99/297=33.3%），全局 173/414=41.8% 回落。证伪/回滚：留痕从不出现 → 复查 esc 入锁场景与计数口径；锁持后 esc 桶判死后胜率不降反升、或深局平均楼层/战损显著恶化 → policy.json 置 false 整体撤回。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（新增 3br-esc-latch-hold 四分支；既有 3br-combat-cap/ttk-obs/longfight 翻盘比与滑溜夹具、3prf 首窗先验下限及全部既有夹具通过；tests/test_boss_race_sustain.py 两条 _krace_latch 断言路径 _feas 均为否，不受锁持影响）。
- 完整 diff 已回读：brain/policy.py（翻案分支 +24/-7，行为仅锁持一条）、brain/knowledge.py（纯 +11 静态键，首轮误改的既有注释缩进已还原）、brain/selfcheck.py（探针参数化 + 四分支夹具）+ 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 306 局复盘：竞速排除自付口径缺少主导性观测（VIVHITE_RACE_SELF_LOSS_DOMINATES）

日期：2026-09-08

## HYPOTHESIS

第 306 局 F17 乐加维林族母战中，`VIVHITE_RACE_SELF_LOSS_EXCLUDE` 将白绮生命支付从竞速生存分母排除；当实际自付速率达到敌方净损速率时，该口径可能高估可存活回合数并掩盖白绮自身放血。该假设可证伪：未来 3~10 局若主导标记与高自损、预测生存期失真或短战阵亡不共现，则当前怀疑不成立。

## EVIDENCE

- run `Q36VL8XL7NR9` 的完整 200 条决策链已逐条核对。F17 进入时生命 59，敌人原生血池 222；T1/T2 决策先后记录「已隔离謦欬实付17」与「已隔离謦欬实付30」，随后在意图 19 的窗口进入全攻竞速，T4 阵亡。
- 当局战斗记录为 F17 敌方掉血 59、自损 36；F15 另有自损 38/敌方掉血 45。当前链路确实能记录自付，但竞速注记只说明已隔离金额，不能按回合判断自付是否已经主导生存消耗。
- 原生知识核对：`LAGAVULIN_MATRIARCH` 为 Boss、222/222 HP；其机制含沉睡/醒来、斩击与 9×2 开膛破肚，首个零伤害窗口不能代表后续敌方净损。此前已存在的排除口径仍可能避免“自付反过来制造判死”的闭环，因此本批先增加能直接证伪的观测，不提前改判定。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- `sts2-ascend/brain/knowledge.py`：新增 `vivhite_race_self_loss_obs=true`，作为单键可回滚的生产观测开关。
- `sts2-ascend/brain/policy.py`：从 `SELF_LOSS_PHASE_OBS` 的可行动段按完成回合保存实际自付速率，并在白绮竞速投影中追加 `VIVHITE_RACE_SELF_LOSS_DOMINATES`（自付速率≥敌方净损速率，且至少 2 HP/回合）及比值。该信息不进入 `loss_rate`、`tsurv`、`ttk`、评分、姿态或动作选择；`vivhite_race_self_loss_obs=false` 即撤回新增留痕。
- `sts2-ascend/brain/selfcheck.py`：覆盖白绮分账速率更新、敌方零损、低于敌损与低于噪声门槛四分支，同时保留非白绮与旧混合口径回归。

## EXPECTED_SIGNAL

未来 3~10 局：① Boss/精英竞速链中可见 `VIVHITE_RACE_SELF_LOSS_DOMINATES` 时，战斗记录的可行动段自损应与标记速率同向；② 统计标记局的自损/敌方损耗比、投影可存活回合与实际存活回合差值，重点对账沉睡/醒来型 Boss；③ 若至少 2/3 局出现标记并伴随自损主导及短于投影的结局，则下一批可将自付接入受限生存护栏；若 3~10 局始终不出现、或标记只出现在可安全 setup 且预测兑现，则证伪本假设。撤回条件：将 `policy.json` 的 `vivhite_race_self_loss_obs` 置为 `false`，恢复无新增标记的旧行为。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：`SELFCHECK OK`。
- `git diff --check` 通过；本批 diff 仅含三个预期静态文件，未触碰 runs、stats、policy.json、lessons、review_queue、在线状态或宿主遗留 assets。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 `retry_resolution` 目标。

# 第 307~314 局批复盘：余裕稀缺加分观测只挂在从不执行的 REWARD 路径——真实拿牌路径补留痕（VIVHITE_MARGIN_PICK_OBS）

日期：2026-09-08

## HYPOTHESIS

第 244~259 局批上线的余裕供给稀缺加分（VIVHITE_MARGIN_PICK_SCARCITY）本体已计入 eval_reward_card 分值（3prj 夹具在证、policy.json vivhite_margin_pick_bonus=4.0 生效中），但其 detail 观测只挂在 v0.111.0 从不执行的 REWARD/choose_reward_card 路径——与第1290~1294批 CARD_BURST_PICK_AUDIT 同型接线缺口。真实拿牌路径 CARD_SELECTION/select_deck_card 的 else 分支调用 eval_reward_card 时不传 detail、理由也不渲染加分注，因此 244~259 批预注册的验证信号「决策链拿牌理由出现余裕供给稀缺加分留痕」在结构上不可能触发，余裕源假设至今无法闭环。该假设可证伪：未来 3~10 局若真实拿牌路径决策链仍零出现「余裕供给稀缺加分（卡组无条件余裕源N张，+X）」留痕，则消费路径复查有误；policy.json 置 vivhite_margin_pick_bonus=0 时留痕与加分同灭（单键回滚，旧行为零差异）。

## EVIDENCE

- 全文检索本批 28 个 run 文件（2026-09-08，第 290~314 局）：「余裕供给稀缺加分」0 次；244~259 批上线以来 50+ 局从未显形。run 内「余裕」仅出现在残能空漏审计的「余裕机会成本」字段，与拿牌端无关。
- 生产现状核查（policy.py）：6643-6654 行 detail 仅在调用方传入 list 时追加；唯一渲染 detail 的消费端是 _reward 的 choose_reward_card 分支（6735 行 _det_note）——第1290~1294批已证 v0.111.0 实战拿牌全走 CARD_SELECTION/select_deck_card（896 局 choose_reward_card 零出现）；else 分支（7119 行）不传 detail、理由（7179 行）不含任何加分注。
- 第 314 局（TM8ACYF5SKGJ，F23 MYTE 战阵亡）完整 305 链已逐条深读：全链 18 次拿牌理由（终止条件/三色轮舞/负空间等）均无任何余裕供给注；该批自损主导依旧（310 局 F27 自损31/掉血26、311 局 F24 自损12/掉血0、313 局 F2 自损28/掉血26、314 局 F19 自损55/掉血44），但余裕源是否经稀缺加分进入卡组完全不可观测，244~259 批的「零源终局占比下降」信号无法对账。
- 相邻观测对账：同批上线的其余留痕均正常显形（STALL_BREAK 6-39 次/局、DPT_FLOOR 6-96 次/局、DOMINATES 在 310/311/313/314 四局出现）——证明 run 记录链路本身完好，唯独余裕稀缺加分留痕结构性缺失。
- 第 306 局批预注册的 DOMINATES 后续条件（≥2/3 局标记且伴随短于投影结局）经核对不成立：310/311/314 三局标记高频出现，但竞速审计行均为「判死→实战获胜」（311-F21 T5判死→10回合胜、314-F17 T6判死→7回合胜、314-F21 T4判死→5回合胜），非「短于投影」，故本批不接生存护栏。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：
  ① 新增 Policy._vivhite_margin_pick_note(pick, deck)——按 eval_reward_card 同一公式（vivhite_margin_pick_bonus × 稀缺线性衰减）重算落牌实际吃到的加分，仅当 deck 非空、bonus>0、落牌为无条件余裕源且稀缺>0 时返回「；余裕供给稀缺加分（卡组无条件余裕源N张，+X）」，否则空串；
  ② CARD_SELECTION/select_deck_card 的 else 分支（自愿与强制拿牌共用）在组装理由前把该注追加进 explore_note——纯观测，不改任何评分/阈值/动作选择；bonus=0 时留痕与加分同灭，单键回滚。
- sts2-ascend/brain/selfcheck.py：新增 3prk 夹具九分支——helper 六分支（零源全额留痕、≥cap 归零、bonus=0 消失、非余裕源无、条件余裕无、空卡组无）+ 真实消费路径三分支（单牌 offer 拿余裕源带精确留痕「0张，+4.0」、拿非余裕源无留痕、bonus=0 回滚后选择不变且留痕消失）。
- 不改 knowledge.py（复用既有 vivhite_margin_pick_bonus 单键），不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 决策链拿牌理由出现「余裕供给稀缺加分（卡组无条件余裕源N张，+X）」留痕（零源卡组拿余裕源时应为 +4.0 全额），可直接与本批 314 局 18 次无注拿牌对账；② 留痕局的终局无条件余裕源张数与 244~259 批基线（6/16 局零源）可对账，判断加分是否真实改变拿牌构成；③ 若留痕高频出现但零源终局占比与战斗自损/掉血比仍不回落，则证明是加分幅度不足而非观测缺失，下一批调 vivhite_margin_pick_bonus 或 vivhite_margin_deck_cap。证伪/回滚：留痕仍零出现 → 消费路径复查有误；留痕出现但理由分值与「+X」对不上 → 公式漂移复查；policy.json 置 vivhite_margin_pick_bonus=0 即整体撤回（加分与留痕同灭）。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（新增 3prk 九分支；既有 3prj 稀缺加分八分支、3pri/3prh 謦欬门夹具与全部既有夹具通过）。
- git diff --check 通过（仅宿主挂载的 assets 超长路径删除遗留告警，与本批无关、不入 commit）；完整 diff 已回读：brain/policy.py（+23，helper + 一行接线）、brain/selfcheck.py（+67）两个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 315~319 局批复盘：自伤型攻击药水零计价零门槛——污浊药水自血入账与自杀边界（POTION_SELF_HARM_OBS）

日期：2026-09-08

## HYPOTHESIS

`_maybe_potion` 的 is_damage 分支只按描述关键词识别「攻击药水」，从不核算药水对使用者自身的伤害：污浊药水（FOUL_POTION，原生描述「对所有玩家和敌人造成12点伤害」）被当纯进攻药水在硬仗连喝——生涯 10 个独立对局共 19 瓶、每瓶约 12 自血（hp 98→86→74 逐瓶可核）合计 ~228 自血从未进入任何决策理由与留痕；318 局 F48 Boss 死亡战 T1 连喝 3 瓶付 36 自血（入场血 98 的 37%），该战自损 69/掉血 98、竞速 T2 判死→T5 阵亡。且 is_defensive 分支有交药线血量门槛，is_damage 分支完全没有——hp≤自伤量时使用即当场自杀的边界在结构上无防线。该假设可证伪：未来 3~10 局若决策链 use_potion 理由不出现「自伤N血（POTION_SELF_HARM_OBS）」留痕（自伤药水不再进背包或词表漏配），或留痕出现但自伤量与实测 hp 落差对不上，则消费路径/解析复查；policy.json 置 `potion_self_harm_gate=false` 时留痕与门槛同灭（单键回滚，旧行为零差异）。

## EVIDENCE

- 全文检索本 profile 全部 324 个 run 文件：污浊药水出现在 10 局（50/83/98/127/137/147/210/233/283/318），每次使用 hp 落差逐瓶可核（85→73、78→76→64、78→66→54、72→60、84→72、78→66、98→86→74 等），单瓶固定 ~12 自血；所有使用理由均为「硬仗使用攻击药水【污浊药水】」，无任何自伤披露。
- 原生知识核对（knowledge/game/v0.111.0/runtime/potions.jsonl）：FOUL_POTION 描述「对所有玩家和敌人造成{Damage}点伤害」，Event 池、AnyTime；全词表扫描「所有玩家/all players/对自己/失去」仅 FOUL_POTION 命中自伤型——词表完备。
- 第 318 局（DYDWW3K4A9QN，F48 阵亡）完整决策链已逐条深读：F45 连领 3 瓶污浊药水，F48 Boss 战（火炬头聚合体/女王）T1 hp 98→86→74 连喝 3 瓶后才开始出牌；该回合謦欬实付 51（自付速率 51.0/回合≥敌方净损 16.0/回合，DOMINATES 比值 3.19），全场自损 69/掉血 98，竞速 T2 判死→T5 阵亡——36 自血占入场血 37%，与謦欬实付并列最大自残来源，但决策链零留痕。
- 生产现状核查（policy.py `_maybe_potion`）：is_damage = 描述含「伤害/damage/攻击」即命中；使用分支旧版无任何血量门槛；对照 is_defensive 分支（交药线 potion_block_hp_pct + 致死解封）——自伤边界缺口仅存在于攻击类。
- 相邻批次预注册对账：① 307~314 批 VIVHITE_MARGIN_PICK_OBS 留痕已在 318/319 两局真实拿牌路径显形（「余裕供给稀缺加分（卡组无条件余裕源0/1/2张，+4.0/+2.7/+1.3）」），终局无条件余裕源 3/4/4/8/2 张——244~259 批「零源终局占比下降」信号成立（本批 0/5 零源），但自损/掉血比仍未回落，瓶颈不在余裕供给端；② 306 批 DOMINATES 接入生存护栏的预注册条件（≥2/3 局标记且「短于投影」结局）本批仍不成立：DOMINATES 5/5 局显形，但四场死亡审计均为判死后 1~3 回合阵亡（T7→9、T6→7、T2→5、T5→7），无短于投影案例，故本批不接护栏。
- 台账观察（非本批动作，记录移交）：271~294 批 race_esc_latch_hold 的证伪条件「esc 桶判死后胜率不降反升」在数值上触发——race_audit esc 桶 99/297=33.3% → 116/330=35.2%（边际 17/33=51.5%），全局 173/414=41.8% → 192/452=42.5%；但在线 policy.json 显式钉有 `race_esc_latch_hold: true`，复盘写边界禁止改 policy.json，改 knowledge.py 默认值会被显式键遮蔽而无效——该回滚只能由在线学习环或宿主执行，留痕移交，本批不以无效改动冒充闭环。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py（`_maybe_potion`）：
  ① is_defensive 判定后新增自伤识别——`is_damage 且描述含「所有玩家」/"all players"` 命中药水标记 _self_harm，自伤量取描述第一个数字（解析失败回落实证默认 12，与 10 局 19 瓶实测一致）；
  ② 使用分支新增自杀/贴死边界门——`potion_self_harm_gate`（默认开）下，使用后血量将 ≤`potion_self_harm_reserve_hp`（默认 1，只拦字面自杀）时 `continue` 跳过且不计 tried（回血后仍可用，与增益药非 premium 跳过同一语义）；
  ③ 使用时理由追加「，自伤N血（POTION_SELF_HARM_OBS）」——纯披露，供后续批次对账自伤药水真实成本；gate 置 false 时门槛与披露同灭，旧行为零差异。
  不改任何评分/竞速/姿态公式；非自伤药水路径严格不变。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增 `potion_self_harm_gate: True`（单键回滚）与 `potion_self_harm_reserve_hp: 1`（后续批次拿到披露账后再决定是否上调覆盖贴死自残），注释记录 10 局实证与 318-F48 死亡战。
- sts2-ascend/brain/selfcheck.py：新增 3k4 夹具七分支——① hp98 高血硬仗照常使用且理由带「自伤12血（POTION_SELF_HARM_OBS）」；② hp13（13-12=1≤reserve）自杀边界跳过；③ hp14（2>1）照常兑现；④ 跳过不计 tried，hp60 后同一瓶可再用；⑤ 描述无数字回落默认 12 仍跳过；⑥ 非自伤攻击药水（「对所有敌人造成20点伤害」）hp10 照旧使用且无披露（旧行为不变）；⑦ gate=false 时 hp13 照用且无披露（严格回滚）。

## EXPECTED_SIGNAL

未来 3~10 局：① 决策链 use_potion 理由出现「自伤N血（POTION_SELF_HARM_OBS）」留痕（污浊药水生涯出现率约 1/32 局、出现即 1~3 瓶，可直接与 318-F48 T1 三瓶 36 血对账）；② 若出现 hp 接近自伤量的场面，可见自伤药水留包未用（跳过不计 tried，非锁死）；③ 披露账累计 ≥3 次后，可对账「自伤药水使用×12」与战斗注记自损的构成比例，决定是否上调 `potion_self_harm_reserve_hp` 把贴死自残（如使用后血量跌破交药线）也纳入门禁。证伪/回滚：留痕从不出现（自伤药水不再进背包或词表漏配）→ 复查消费路径与关键词；留痕出现但披露自伤量与实测 hp 落差对不上 → 数字解析复查；policy.json 置 `potion_self_harm_gate=false` 即整体撤回（门槛与披露同灭，旧行为零差异）。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（新增 3k4 七分支；既有 3k/3k3/3k3b 药水预留夹具、3prj/3prk 余裕加分夹具、3pri/3prh 謦欬门夹具与全部既有夹具通过）。
- `git diff --check -- sts2-ascend/` 通过；完整 diff 已回读：brain/policy.py（+41/-1，自伤识别+边界门+披露）、brain/knowledge.py（+14 两个静态键）、brain/selfcheck.py（+51 七分支夹具）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 320~336 局批复盘：謦欬卡组血税密度拿牌计价——出牌侧双旋钮全尽后的供给端收口（VIVHITE_LIFE_COST_DECK_TAX）

日期：2026-09-08

## HYPOTHESIS

謦欬是全目录机制（58/61 张 life_calculation_cost>0），但拿牌端对卡组累计生命支付血税零约束：单牌估值只按自身 life_cost×weight 常数计价，不看卡组已有血税总量——余裕供给（margin_deck_cap 3 张）追不上时，每张新謦欬牌的边际实付递增却仍按面值计价。EVIDENCE：本批 17/17 局终局卡组生命支付牌占比 88~100%（目录血税合计 38~120、均值 ~76），实测自损 ≥ 敌方掉血 50%，321（204 vs 130）/322（200 vs 160）/328（281 vs 256）/329（292 vs 201）/330（224 vs 209）/336（250 vs 244）六局自损反超敌方；出牌侧双旋钮已全尽（life_cost_weight -2.98 触底、hp_cost_play_margin 3.00 顶格，reflect 连续多局留痕「双旋钮全尽，謦欬证据彻底停止吸收并留痕」）；336 局单局拿 22 张生命支付牌、终局血税 110，F33 无厌沙虫战 T2 起 VIVHITE_LIVE_ESTIMATE 持续深负（-13.20/-11.90）仍靠僵局放行打出。EXPECTED_SIGNAL：未来 3~10 局终局卡组目录血税合计与自损/掉血比从 ~1.0 回落、决策链选牌理由出现「謦欬血税密度扣分」留痕；若到达层数显著恶化则 policy.json 置 vivhite_life_cost_pick_tax=0 一键回滚（扣分与留痕同灭，软顶以下旧行为零差异）。

## EVIDENCE

- 逐局对账本批 17 个 run 文件（320~336）：终局卡组目录血税合计 38~120，余裕源 1~6 张；战斗注记自损合计/敌方掉血合计逐局比值 0.67~1.57，17 局全部 ≥50%，六局 >100%（最高 329 局 292 vs 201=1.45）。
- 第 336 局（2EE2CX3DTL6J，F33 阵亡于 THE_INSATIABLE）完整链已逐条阅读：终局 33 张含 30 张生命支付牌（血税 110）；F33 Boss 战 T2 hp-cost=8 margin=0/spent=0 打出绯彩极限，T5 末 hp 113、敌意图 20，T6 被一波击穿（全场掉血 137｜自损 10）——出牌侧已无可收紧空间，缺口在卡组构成。
- reflect.py 謦欬通道现状：`vivhite_param_life_cost_weight` 触及 BOUNDS 下限 -3.0（实测 -2.98，余量 0.02<步长 0.05）后证据改接 `vivhite_hp_cost_play_margin`，该门亦顶格 3.00；连续多局 lessons 留痕「双旋钮全尽，謦欬证据彻底停止吸收并留痕」——自损证据已无在线旋钮可吸收，必须新开有界杠杆。
- 拿牌端现状核查（policy.py `eval_reward_card`）：既有 `vivhite_margin_pick_bonus` 只奖励余裕供给端（cap 3 张，本批终局余裕源 2~6 张说明已在起效），对称的「血税密度超顶扣分」不存在；单牌 life_cost 按 weight 常数计价与卡组累计量无关。
- 相邻批次预注册对账：307~314 批 VIVHITE_MARGIN_PICK_OBS 已在真实拿牌路径显形，本批 run 理由可见余裕稀缺加分多次触发——余裕供给端机制健康，佐证剩余缺口在血税密度侧。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py（`eval_reward_card`，余裕稀缺加分块之后）：新增 VIVHITE_LIFE_COST_DECK_TAX——白绮 profile、deck 非空、候选目录血税 >0 且卡组目录血税合计超过软顶（默认 60，约起始卡组 20 的 3 倍）时，按 `tax（默认 2.0）× clamp(超出比例,0,1) × 候选自身血税` 从拾取/购买价值线性扣分，detail 留痕「謦欬血税密度扣分（卡组目录血税N/软顶M，-X，VIVHITE_LIFE_COST_DECK_TAX）」。软顶以下零差异；零血税候选（余裕源/能力牌）不受影响；空卡组上下文（升级/删除/献祭评估）与非白绮角色天然不受影响；tax=0 一键回滚。覆盖奖励选牌、CARD_SELECTION、商店购买全部 eval_reward_card 消费端；升级/删除端传空 deck 不受影响。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增 `vivhite_life_cost_pick_tax: 2.0`（静态键，0=关闭回滚）与 `vivhite_life_cost_deck_cap: 60.0`（软顶与超出比例分母），注释记录本批 17 局实证与双旋钮全尽背景。
- sts2-ascend/brain/selfcheck.py：新增 3prl 夹具六分支——① 血税恰在软顶（60）开/关键零差异；② 超顶（72，超出比例 0.2）扣分恰为 2.0×0.2×8=3.2；③ detail 留痕带审计标记；④ 零血税候选（AXIOM_RING）超顶卡组零差异；⑤ 空卡组上下文零差异；⑥ 非白绮角色（STRIKE×20）开/关键零差异。
- 不改 reflect 通道、不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 决策链选牌/购牌理由在卡组血税 >60 后出现「謦欬血税密度扣分（卡组目录血税N/软顶60，-X）」留痕，可直接与本批 336 局 22 张生命支付牌对账；② 终局卡组目录血税合计从本批均值 ~76 回落、自损/掉血比从 ~1.0 显著下行（首场验证：任一终局血税 ≤55 且自损/掉血 <0.8）；③ 若留痕高频出现但血税与自损比不回落，说明扣分幅度不足，下一批上调 `vivhite_life_cost_pick_tax` 或下调 `vivhite_life_cost_deck_cap`。证伪/回滚：留痕从不出现 → 复查 eval_reward_card 消费路径；到达层数（floor_sum_raw 均值）较本批显著恶化 → policy.json 置 `vivhite_life_cost_pick_tax=0` 整体撤回（扣分与留痕同灭，软顶以下旧行为零差异）。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（新增 3prl 六分支；既有 3prj/3prk 余裕加分夹具、3pri/3prh 謦欬门夹具、3prf 先验下限夹具与全部既有夹具通过）。
- 完整 diff 已回读：brain/policy.py（+38，密度扣分+留痕）、brain/knowledge.py（+10 两个静态键）、brain/selfcheck.py（+60 六分支夹具）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 343~354 局批复盘：謦欬门僵局放行「连续全覆盖」条件在意图交替战中结构性不可达——未覆盖拦截观测上线（VIVHITE_HP_GATE_STALL_UNCOVERED）

日期：2026-09-08

## HYPOTHESIS

謦欬门僵局放行（VIVHITE_HP_GATE_STALL_BREAK，第 231~243 批）要求「连续 N 回合（当前 6）回合结束仍有謦欬候选被拦、且敌意图被格挡全覆盖（incoming<=my_block）」才停用余量门。在意图高低交替、我方格挡仅覆盖低峰的战斗中该条件结构性不可达：低峰回合计数、高峰回合清零，放行永不触发；余量门（已顶格 3.00）永久锁死謦欬攻击，残能救场转而每回合付 2 血格挡，战斗退化为放血死循环。该假设可证伪：未来 3~10 局若「连续未覆盖拦截N回合（VIVHITE_HP_GATE_STALL_UNCOVERED）」留痕从不出现、或出现但从不与高自损长战/阵亡共现，则「放行条件不可达是放血死循环的结构性成因」不成立。

## EVIDENCE

- 第 354 局（FBGRZKL1FFCQ，F3 SHRINKER_BEETLE 阵亡）完整 70 链逐条核对：敌意图 7/13 交替、我方单张闭域映射格挡 9。决策 24/26 僵局进度 1/6→2/6；T3 意图 13>甲 9 清零后全链再未出现放行。其后 16 回合每回合付 2 血格挡（VIVHITE_LIVE_ESTIMATE=-5.90→-11.80 仍打出），生命 78→1；决策 67/68 生命 1 时全手牌 blocked_by_hook 空过两回合后阵亡。战斗账：19 回合，自损 57/掉血 78，竞速审计 T17 判死→实战 19 回合阵亡。
- 同批佐证：349 局 F3/F4 自损 22/20（掉血 12/19）、345 局 F5 自损 20/掉血 1、344 局 F9 精英自损 18；历史同型 243 局 F3 拖 56 回合、238 局 F2 76 回合、235 局 F3 19 回合——但那些是「全覆盖低危」局，本批 354 局证明「未覆盖」局同样死循环且放行机制够不到。
- 生产现状核查（policy.py）：放行账只在 `_hp_gate_blocked and incoming <= my_block` 时累加，其余清零（含同回合多 tick 守卫）；现有链路对「被拦但意图未覆盖」的连续回合零观测——低危进度注记只在 `_hp_gate_stall_limit>0` 时渲染，未覆盖链长度完全不可见，无法直接验证放行条件是否该扩展。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增 `vivhite_hp_gate_uncovered_obs: 1`（静态键，0=关闭一键回滚）。
- sts2-ascend/brain/policy.py：新增 `self._hp_gate_stall_uncovered` 观测账（初始化、新战斗重置与既有 stall 账同点）；回合收口处与低危链互斥维护——被拦且意图未覆盖的连续回合 +1，覆盖回合或无拦截回合清零；`_hp_gate_blocked` 非空且计数 >0 时在回合理由追加「；连续未覆盖拦截N回合（VIVHITE_HP_GATE_STALL_UNCOVERED）」。不改放行阈值、不改评分、不改任何动作选择；obs=0 时计数与留痕同灭，旧行为零差异；非白绮角色零改动。
- sts2-ascend/brain/selfcheck.py：新增 3prm 夹具五分支——① 未覆盖拦截连续计数 1→3 且逐回合留痕、行为仍 end_turn；② 未覆盖回合不累计低危放行账；③ 覆盖回合清零未覆盖链且不留痕（互斥）；④ 新战斗重置观测账；⑤ obs=0 回滚键下不计数不留痕、行为零差异。
- 不改 reflect 通道、不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 决策链 end_turn 理由在「謦欬出牌门拦下」后出现「连续未覆盖拦截N回合（VIVHITE_HP_GATE_STALL_UNCOVERED）」，可直接量出放行条件不可达的战斗占比与持续长度（首场验证：任一长战该计数 ≥6 且同战自损/掉血 ≥0.5，即与 354 局 F3 同型对账）；② 若该留痕高频（≥2 局）且与高自损长战/阵亡共现，下一批有证据把僵局放行条件扩展为「低危链≥N 或未覆盖链≥M」；③ 若留痕从不出现，则 354 局为孤立样本，本假设证伪。撤回条件：policy.json 置 `vivhite_hp_gate_uncovered_obs=0`，计数与留痕同灭，旧行为零差异。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（新增 3prm 五分支；既有 3pri 謦欬门僵局放行夹具、3prh 余量门夹具、3prl 血税密度夹具与全部既有夹具通过）。
- `git diff --check` 通过；完整 diff 已回读：brain/knowledge.py（+8 静态键）、brain/policy.py（+30 观测账+留痕）、brain/selfcheck.py（+54 五分支夹具）+ 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 355~360 局批复盘：謦欬门把净正保命格挡一并逐出残能救场——门拦格挡净保命放行（VIVHITE_HP_GATE_RESCUE_BLOCK）

日期：2026-09-08

## HYPOTHESIS

謦欬出牌余量门（VIVHITE_HP_PLAY_MARGIN_GATE）拦下的候选被无差别逐出残能救场手牌，但救场格挡通道自带净保命>0 计价（min(block,gap)−实际謦欬−余裕机会成本）：被门拦下的謦欬格挡牌（闭域映射：付 2 血挡 9）在意图缺口>0 时本就是净正保命，把它一并排除等于把可抵伤害换成贴脸掉血——「付血换不空过」反死循环语义只适用于攻击牌，对净正保命格挡是反向伤害。该假设可证伪：未来 3~10 局若决策链「残能救场[格挡]」理由从不出现「门拦格挡净保命放行（VIVHITE_HP_GATE_RESCUE_BLOCK）」留痕（消费路径复查），或留痕出现但同回合 hp 账与「可抵−謦欬」对不上（计价复查），则本假设不成立；policy.json 置 `vivhite_hp_gate_rescue_block=0` 即整体撤回（恢复全部排除，旧行为零差异）。

## EVIDENCE

- 逐局扫描本批 355~360 及相邻 361~364 全部 run 决策链，对账「謦欬出牌门拦下」与「残能空漏审计(IDLE_LEAK_BLK)」同回合共现且被拦牌正是审计认定的净正保命格挡牌：3 个独立对局命中（达 evidence_run_threshold=3）——① 355 局（R6EUW7PXRYVD）F5 死亡战 T1：门拦【闭域映射】，审计可抵3/謦欬2/净保命1，hp33 空过，该局 F5 阵亡；② 362 局（MT4U8BGXWLWW）F17 Boss 死亡战 T1：门拦【闭域映射】×3+【分治法阵】，审计可抵5/謦欬2/净保命3，hp69 空过；③ 364 局（DYGY56WTK8YQ）F2 T8、F8 T2/T4/T10/T12 五处：门拦【闭域映射】，审计可抵5/謦欬2/净保命3。
- 本批自损主导依旧（355 局 F2 自损14/掉血8、360 局 F2 自损18/掉血0、359 局 F17 Boss 自损55/掉血89 阵亡），356/357 两局门拦 23/25 次而僵局放行 0 次——放行条件够不到的战斗中，每一滴净正保命都直接改写生死。
- 生产现状核查（policy.py）：救场手牌过滤把全部 `_hp_gate_blocked` 下标剔除（原注释只考虑「付血换不空过正是本门要拦的死亡螺旋」），未区分攻击与格挡；救场通道 `idle_energy_rescue_pick` 格挡分支本身已用 `_rescue_block_tradeoff` 扣除实际謦欬与余裕成本并要求净保命>0、缺口>0——被排除的恰是这套计价已判定净正的牌。
- 原生知识核对：闭域映射描述「謦欬 {LifeCost}。获得 {Block} 点格挡。」，不含「失去生命」字样，救场通道 `_SELF_COST_RE` 不会拦截——排除完全来自门拦下标过滤这一处。
- 相邻批次预注册对账：343~354 批 VIVHITE_HP_GATE_STALL_UNCOVERED 已在 361~364 四局显形（2/2/2/10 次），但未覆盖链全部止步 1 回合即被「无拦截回合」清零——「未覆盖链≥M(M≥2)」的放行扩展在当前账目下结构性不可达，本批不接该扩展（预注册条件不满足，留痕移交后续批次）；本批改接同源但已证净正的救场端缺口。
- failed_review_replay.requested_packages 含 20260908-151840-1788851920186074500-380d8ec0（target）：manifest 显示 process_exit、return_code=1、command_count=0、file_change_count=0、patch_bytes=-1，无任何候选 patch/变更文件可重实现；本批基于当前 HEAD 自行完成新的生产闭环。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py（残能救场手牌过滤）：新增门拦净保命格挡例外——`vivhite_hp_gate_rescue_block`（默认开）下，门拦下标中 block>0 的牌（card_numbers 口径）回到救场手牌，打出与否仍由救场通道自己的缺口>0/净保命>0（扣除实际謦欬与余裕成本）裁决；謦欬攻击牌维持排除，「付血换不空过」反死循环语义不变。救场打出的牌若原在门拦清单，理由追加「；门拦格挡净保命放行（VIVHITE_HP_GATE_RESCUE_BLOCK）」留痕供对账。0=一键回滚（恢复全部排除，旧行为零差异）；非白绮角色 `_hp_gate_blocked` 恒空、零改动。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增 `vivhite_hp_gate_rescue_block: 1`（静态键，0=关闭回滚），注释记录三局实证与反死循环边界。
- sts2-ascend/brain/selfcheck.py：新增 3prn 夹具三分支——① 默认开：门拦闭域映射（挡9/謦欬2，意图10缺口10）必须经救场打出且理由带「残能救场[格挡]」与放行留痕；② 混合手牌（门拦弦光投影+门拦闭域映射）：救场只放行格挡牌（card_index=1），攻击牌维持排除；③ 回滚键 0：门拦格挡恢复退出救场、照旧 end_turn 且无留痕。
- 不改评分/阈值/放行账；不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 决策链出现「残能救场[格挡]…门拦格挡净保命放行（VIVHITE_HP_GATE_RESCUE_BLOCK）」留痕，可直接与 355-F5/362-F17/364 五处空过场面逐一比对——同型场面应改为打出格挡且当回合 hp 账改善「可抵−謦欬」点；②「门拦格挡牌+IDLE_LEAK_BLK 净保命>0 却空过」的矛盾对应清零；③ 若留痕高频出现且早期怪物战（355/360 型 F2~F5）自损+掉血合计与战斗回合数下降，则接下一批评估门拦格挡在主评分端的同型豁免。证伪/回滚：留痕从不出现 → 复查救场消费路径与 card_numbers 口径；留痕出现但放行后长战自损/掉血比显著恶化（死循环复发迹象）→ policy.json 置 `vivhite_hp_gate_rescue_block=0` 整体撤回（恢复全部排除，旧行为零差异）。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（新增 3prn 三分支；既有 3prh 余量门夹具——攻击牌默认键下仍被拦且不得经救场绕行、3pri 僵局放行、3prm 未覆盖观测、3prl 血税密度等全部既有夹具通过）。
- `git diff --check -- sts2-ascend/` 通过；完整 diff 已回读：brain/policy.py（+28/-1，格挡例外过滤+放行留痕）、brain/knowledge.py（+13 静态键）、brain/selfcheck.py（+81 三分支夹具）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

retry_resolution: 20260908-151840-1788851920186074500-380d8ec0 integrated（失败包为零产出 process_exit：patch_bytes=-1、无候选 patch/变更文件，无有效内容可重实现；本批已在当前 HEAD 自行完成新的生产闭环并经 SELFCHECK OK 验证）。

# 第 363~380 局批复盘：謦欬血税密度扣分已计价 49 次却零留痕——拿牌路径观测接线补通（VIVHITE_LIFE_COST_DECK_TAX 入链）

日期：2026-09-08

## HYPOTHESIS

第 320~336 局批落地的謦欬血税密度扣分（VIVHITE_LIFE_COST_DECK_TAX）在 eval_reward_card 内同时做两件事：扣分本体 `value -= tax×超出比例×自身血税`（与 detail 无关、必然生效）和 detail 留痕。但 v0.111.0 实战拿牌全走 CARD_SELECTION/select_deck_card 的 `_score_sel`，该路径只把含 `BURST_STARVE_SUPPLY_LEVER` 的注记暂存进 `_sd_notes` 并随中标入链，血税注记随 `_det` 整体丢弃——第 320~336 批预注册的「决策链出现謦欬血税密度扣分留痕」信号在当前接线下结构性不可达，与条件是否达成无关。EVIDENCE：本批 18 个 run 文件全文检索 `LIFE_COST_DECK_TAX` 0 次；而逐局 deck_changes 重建卡组目录血税时间线，18 局共 49 次「拿牌前卡组目录血税 >60 且候选自身血税 >0」的资格拿牌（363×1/364×5/365×2/367×4/372×11/375×4/377×10/378×2/379×1/380×9；372 局终局血税 116、377 局 108、380 局 98），扣分条件 49 次成立、留痕 0 次——缺口在观测接线而非条件未达。EXPECTED_SIGNAL：未来 3~10 局决策链选牌理由在超顶卡组拿血税牌时出现「謦欬血税密度扣分（卡组目录血税N/软顶60，-X，VIVHITE_LIFE_COST_DECK_TAX）」，可与本批 49 次资格拿牌逐一对账；证伪：留痕仍零出现 → 消费路径复查；留痕出现但 -X 与 `2.0×超出比例×自身血税` 对不上 → 公式漂移复查。回滚：注记本体随既有键 `vivhite_life_cost_pick_tax=0` 同灭（不新增键），接线零差异。

## EVIDENCE

- 全文检索本批 18 个 run 文件（363~380）：`LIFE_COST_DECK_TAX` 0 次；对照同批 `RESCUE_BLOCK`（373/375/377/378/380 共 31 次）与 `STALL_UNCOVERED`（13/18 局显形）均正常入链——run 记录链路本身完好，唯独血税密度注记结构性缺失。
- 逐局 deck_changes 重建（起始卡组目录血税 20 = 4×弦光投影2+4×闭域映射2+变身式4）：14/18 局终局目录血税 >60（最高 372 局 116），18 局共 49 次资格拿牌中 REWARD 屏 38 次、SHOP 屏 9 次、EVENT 屏 2 次——第 320~336 批「留痕+血税回落」的首场验证（任一终局血税 ≤55）本批 0/18 达成，但无法区分「扣分未生效」与「生效但幅度不足」，因为留痕根本到不了链上。
- 生产现状核查（policy.py 7356~7370 行 `_score_sel`）：`_det` 只提取 `BURST_STARVE_SUPPLY_LEVER` 注记进 `_sd_notes`；`_pick_sd` 在自愿/强制分支统一入链（7426~7428 行）。同型接线缺口的既往病例：第1290~1294批 CARD_BURST_PICK_AUDIT、第1307~1312批 BURST_STARVE_SUPPLY_LEVER、第 307~314 批 VIVHITE_MARGIN_PICK_OBS——同一消费路径已三次补齐同类观测，本批为第四次、针对 320~336 批注记。
- 相邻批次预注册对账：① 355~360 批 VIVHITE_HP_GATE_RESCUE_BLOCK 已在 373/375/377/378/380 五局显形（377 局 23 次），接线健康；② 343~354 批 VIVHITE_HP_GATE_STALL_UNCOVERED 13/18 局显形（377 局 15 次最高）；③ 315~319 批 POTION_SELF_HARM_OBS 本批 0 次——污浊药水生涯出现率约 1/32 局，本批 18 局未遇到属正常口径，不判失效。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py（`_score_sel`，CARD_SELECTION/select_deck_card 唯一真实拿牌路径）：候选注记暂存从「只保留 BURST_STARVE_SUPPLY_LEVER」扩展为「同时保留 VIVHITE_LIFE_COST_DECK_TAX」，多条注记以「；」拼接后按既有 `_pick_sd` 通道随中标入链。纯观测接线：不改评分、不改排序、不改选择、不新增键；`vivhite_life_cost_pick_tax=0` 时注记本体不存在，接线随既有回滚键同灭、旧行为零差异；非白绮角色血税恒 0、零改动。
- sts2-ascend/brain/selfcheck.py：3prl 夹具新增第 ⑦ 组三分支——① 超顶卡组（目录血税 72>60）强制拿绯彩极限（自身血税 8）的 decide() 理由必须带「謦欬血税密度扣分…VIVHITE_LIFE_COST_DECK_TAX」；② 同卡组拿零血税公理之环不带留痕；③ `vivhite_life_cost_pick_tax=0` 回滚键下留痕消失且 option_index 选择不变。
- 不改 knowledge.py（复用既有 `vivhite_life_cost_pick_tax` 键，不新增静态键）、不改 reflect 通道、不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 决策链选牌理由在卡组目录血税 >60 且中标牌自身血税 >0 时出现「謦欬血税密度扣分（卡组目录血税N/软顶60，-X，VIVHITE_LIFE_COST_DECK_TAX）」留痕——按本批节奏（49 次/18 局 ≈ 2.7 次/局）首场即可验证，可直接与 372 局（终局血税 116）/377 局（108）/380 局（98）的资格拿牌对账；② 拿到真实 -X 账后可首次回答第 320~336 批悬置问题：扣分是「未生效」（留痕对应场次血税仍照拿）还是「生效但幅度不足」（留痕场次的落选候选可见），据此决定上调 `vivhite_life_cost_pick_tax` / 下调 `vivhite_life_cost_deck_cap` 或确认 320~336 批机制空转；③ 若留痕高频出现且终局目录血税从本批均值 ~71 回落、自损/掉血比下行，则血税密度闭环成立。证伪/回滚：留痕仍零出现 → 复查 `_score_sel`/`_pick_sd` 消费路径；留痕出现但 -X 与 `tax×clamp(超出比例,0,1)×自身血税` 对不上 → 公式漂移复查；`vivhite_life_cost_pick_tax=0` 即整体撤回（注记与扣分同灭，软顶以下旧行为零差异）。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（3prl 新增第 ⑦ 组三分支；既有 3prl①~⑥ 血税密度、3prk 余裕加分真实路径、3prn 门拦格挡放行、3prm 未覆盖观测、3bsl 供给纠偏入链与全部既有夹具通过）。
- `git diff --check -- sts2-ascend/` 通过；完整 diff 已回读：brain/policy.py（+9/-4，注记暂存扩展+注释实证）、brain/selfcheck.py（+46 三分支夹具）两个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 381~385 局批复盘：竞速投影「可存活回合」对沙坑吞噬钟失明——SANDPIT_EAT_CLOCK_CAP 封底上线

日期：2026-09-08

## HYPOTHESIS

战斗端斩杀竞速投影的可存活回合 `tsurv = 裸血 ÷ 火力`，只对 HP 消耗计账；而无厌沙虫（THE_INSATIABLE）Liquify 后挂上的计数沙坑（SANDPIT_POWER，初始 4、每个敌方回合 -1，原生 `SandpitPower.AfterRemoved` 在计数归零时 `CreatureCmd.Kill(force)` 强制吞噬）是一条与 HP/格挡完全无关的确定性死亡钟，投影对它完全失明——沙坑在场时 tsurv 被系统性高估，判死/翻盘判决的方向与量级同时失真。该假设可证伪：未来 3~10 局若「沙坑吞噬钟N回合封底（SANDPIT_EAT_CLOCK_CAP）」留痕从不出现（说明 API 功率载荷不可见），或留痕出现但封底后的判决与实战阵亡回合对账反而更差，则本假设不成立。

## EVIDENCE

- 第 385 局（CXU2MG7HAY02，F33 THE_INSATIABLE 阵亡）全链逐条核对：19:26:39 投影「击杀还需6回合>可存活16回合（实测27伤/回）」——可存活 16 回合出自裸血 72÷低意图期火力 EMA；但沙坑 Liquify 已发生（19:26:38 手牌已出现其塞入的狂乱逃离），死亡钟上限远小于 16，实战 T6 即阵亡（竞速审计：T2判死→实战6回合），19:26:51 口径急坍为「可存活2回合」。
- 原生机制核对（knowledge/game/v0.111.0 mechanics）：`TheInsatiable.LiquifyMove` 以 `PowerCmd.Apply(..., 4m)` 挂沙坑并塞入 6 张狂乱逃离；`SandpitPower.AfterSideTurnStartLate` 每敌方回合 -1、`AfterRemoved` 触发 eat_player 强制击杀；`FranticEscape.OnPlay` 计数 +1 且本战耗能 +1——续命存在但有界，保守账不计入。
- 死亡榜对账：THE_INSATIABLE 以 16.55 权重居死因前五（stats_digest），该 Boss 的竞速判决质量直接影响到达层数。
- 相邻批次对账：謦欬双旋钮全尽与血税密度留痕接线（363~380 批）均已落地，本批不重复开工；failed_review_replay.requested_packages 为空，无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py（`_combat_kill_race_projection`，`tsurv` 计算之后、`ttk` 与判死比较之前）：新增 SANDPIT_EAT_CLOCK_CAP——经既有 `_enemy_power_stack(e, "sandpit", "沙坑")` 读取全场敌人沙坑计数最大值 N；N>0 且 tsurv>N 时留痕「沙坑吞噬钟N回合封底：可存活X→N（沙坑归零即被强制吞噬，SANDPIT_EAT_CLOCK_CAP）」并把 tsurv 封底到 N。封底同时收紧判死比较（ttk>tsurv+margin）与防守线翻盘比上限（ttk>1.5×tsurv 不予放行）的分母；狂乱逃离 +1 续命不计入保守账；计数不可见或键=False 严格回滚旧口径（零差异）；非沙坑战斗零改动。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 `sandpit_eat_clock_cap: True`（False 一键回滚），注释记录 385 局实证。
- sts2-ascend/brain/selfcheck.py：新增 3sec 夹具三分支——① 敌持 SANDPIT_POWER 计数 2（血 71、意图 EMA≈4 → 裸口径 tsurv≈17.8，池 200、实测 dpt 20×1.35=27 → ttk≈7.4）：封底后 7.4>2+1.5 判死、理由带封底注记与「可存活2回合」，且 Boss 翻盘比上限（1.5×2=3<7.4）不许防守复核翻案；② 无沙坑功率同口径：不封底、不判死、无注记；③ 键=False：沙坑在场也严格回滚旧口径（零差异）。
- 不改 reflect 通道、不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 任一遭遇 THE_INSATIABLE 且 Liquify 已发生的对局，决策链理由应出现「沙坑吞噬钟N回合封底（SANDPIT_EAT_CLOCK_CAP）」，且封底后的「可存活N回合」与实战阵亡回合可直接对账（385 局型：投影 16 vs 实战 6 的失真应显著收敛）；② 封底生效场次判死/全攻提速应不迟于旧口径出现，狂乱逃离的续命价值可在封底注记旁直接读出；③ 若留痕从不出现 → 复查 API 敌人 powers 载荷是否含 SANDPIT_POWER（观测键自身即答案）；若留痕出现但对 THE_INSATIABLE 的到达层数/阵亡回合分布无改善甚至恶化 → `sandpit_eat_clock_cap=False` 整体撤回（无沙坑战斗旧行为零差异）。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（新增 3sec 三分支；既有 3prl①~⑦ 血税密度、3bsl 供给纠偏入链、3zsu 换挡上浮、3kw/3kx 复核火力与全部既有夹具通过）。
- 完整 diff 已回读：brain/policy.py（+25，封底+留痕）、brain/knowledge.py（+4 一个静态键）、brain/selfcheck.py（+74 三分支夹具）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 386~391 局批复盘：自付低回报门对滑溜破层零计价——低价烧墙破层抵扣放行（VIVHITE_RACE_PAYBACK_SLIPPERY_CREDIT）

日期：2026-09-08

## HYPOTHESIS

謦欬自付低回报门（VIVHITE_RACE_SELF_LOSS_PAYBACK_GATE，第362局批落地）按「实付血量 > 当次实际移除」拦截单体攻击；但滑溜（SLIPPERY）把每次命中压成 1 点实际移除，而破层本身是解锁后续全额伤害的必经进度——旧口径等价于把烧墙期全部謦欬攻击判负，竞速态残能空留、坐等意图滚雪球。EVIDENCE：391 局（57DS0V8P8F55）F17 VANTOM（滑溜 8 层开局，生涯死因榜第一 22.42 权重）全链：T2/T5/T6 弦光投影（实付2血）被「实付2血>实际移除1」压到 -55.95 禁玩线（同链 7 次 PAYBACK_GATE 留痕、16 次 SLIPPERY_TTK_OBS），T4 满 3 能量零意图回合空过，意图 5→8→19→28 滚雪球，竞速审计 T6 判死→实战 T10 阵亡（自损39/掉血80，敌方伤害主导——非 362 局自杀螺旋形态）。EXPECTED_SIGNAL：未来 3~10 局滑溜战决策链出现「破层抵扣1放行：实付2≤实际移除1+破层1（VIVHITE_RACE_PAYBACK_SLIPPERY_CREDIT）」，可与 391 局 T2/T5/T6 三处空过场面逐一对账（同型场面应改为打出且当回合破层+1）；证伪：留痕从不出现 → 消费路径复查；放行场次烧墙期回合数/自损占比较 391 局显著恶化（362 局螺旋复发迹象）→ policy.json 置 `vivhite_race_payback_slippery_credit=0` 整体回滚（旧口径零差异）。

## EVIDENCE

- 391 局 F17 VANTOM 全链逐条核对（decision_chain_evidence.full_failure_run，完整 222 条）：T2 end_turn 候选弦光投影 -55.95「实付2血>实际移除1」（能量余1）；T4 满 3 能量、意图 0，绯色面积/尺度变换被拦（实付4）空过；T5（能量余2）、T6（能量余1）弦光投影同型被拦；T7 意图已滚到 28 才因威胁分成放行。破层实际节奏 8→6(T3)→4(T5)→1(T8)→0，被拦的低价烧墙若放行可提前约 2 回合进入全额伤害段。
- 同批佐证：390 局（RCYVJTZGU289）1 次 PAYBACK_GATE 为非滑溜目标（绯彩极限实付8>移除0，地道虫），属正确拦截且本批改动不影响（无破层即无抵扣）；386/388/389 局无 PAYBACK 留痕。
- 历史对账：362 局批（门的起源，VANTOM F17 自付13/回合 vs 敌方净损5/回合）、760~765 局批（SLIPPERY_BURN_AUDIT 烧墙能效）、1232 局批（SLIPPERY_TTK_OBS）——同一 Boss 形态的四次独立证据；本批是「门对破层零计价」的首个行为化批次，未达阈值前未登记过「待观察」。
- 生产现状核查（policy.py 4882 行）：`_payback_blocked = paid > max(0, eff) and not killed`，eff 在滑溜下逐段折算为 1（`_attack_outcome` 同时返回 `slippery_broken` 但未被任何裁决消费，仅用于留痕）；390 局非滑溜拦截证明门本体健康，缺口仅在破层价值零计价。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py（`_score_play` 单体攻击循环）：低回报门比较从「实付 > 实际移除」改为「实付 > 实际移除 + 破层抵扣」，破层抵扣 = 本次实际破层数 × `vivhite_race_payback_slippery_credit`（默认 1.0/层）。效果边界：弦光投影型（实付2、破1层）2>1+1 不成立 → 放行；实付≥4 的高价謦欬（绯色面积/尺度变换/黄金构图/绯红定积分型）仍被拦——362 局自杀螺旋（自付13/回合主要来自高价牌）拦截边界不变；斩杀候选（not killed）与非滑溜目标（broken=0）零改动；门的总开关 `vivhite_race_self_loss_payback_gate=0` 与抵扣键 `vivhite_race_payback_slippery_credit=0` 各自独立回滚旧口径（零差异）。留痕：被拦且抵扣>0 时注记改写为「实付N血>实际移除X+破层抵扣Y」；因抵扣放行时追加「破层抵扣Y放行：实付N≤实际移除X+破层Z（VIVHITE_RACE_PAYBACK_SLIPPERY_CREDIT）」供对账。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 `vivhite_race_payback_slippery_credit: 1.0`，注释记录 391 局实证与 362 局边界。
- sts2-ascend/brain/selfcheck.py：3xg-payback 夹具按新契约修订并扩到六分支——① 低价烧墙（实付2/破1层）放行且带 CREDIT 留痕、无 GATE 注记；② 高价謦欬（实付4/破1层）维持禁玩线且注记带「+破层抵扣1」；③ 普通目标不误拦；④ 斩杀候选不拦；⑤ 总开关=0 回滚；⑥ 抵扣键=0 回滚旧拦截口径（禁玩线+原注记、无放行留痕）。
- 不改评分主体/阈值/竞速判决；不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 滑溜战（VANTOM 及一切 SLIPPERY 敌人）竞速态决策链出现「破层抵扣放行（VIVHITE_RACE_PAYBACK_SLIPPERY_CREDIT）」留痕，391 局 T2/T5/T6 型场面应改为打出低价烧墙牌；② 放行场次的烧墙期（首层→末层回合跨度）较 391 局（T1→T8）收敛，且竞速审计判死回合与实战阵亡回合差不再扩大；③ 若放行场次可行动段自付速率重新显著超过敌方净损（362 局螺旋形态复发），policy.json 置 `vivhite_race_payback_slippery_credit=0` 整体回滚（旧口径零差异）；若留痕从不出现，复查 `_attack_outcome` 的 broken 返回值与门激活条件。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（3xg-payback 修订为六分支；既有 3prl 血税密度、3prn 门拦格挡救场、3sec 沙坑封底、滑溜折算/集火粘性/端到端多段牌等全部既有夹具通过）。
- `git diff` 已完整回读：brain/policy.py（+27/-1，破层抵扣+双向留痕）、brain/knowledge.py（+10 一个静态键）、brain/selfcheck.py（+34/-6 六分支夹具）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 402~426 局批复盘：謦欬双旋钮全尽证据只留痕不吸收——第三级接替旋钮改接拿牌端血税软顶（vivhite_life_cost_deck_cap）

日期：2026-09-09

## HYPOTHESIS

謦欬死亡证据链在 `vivhite_param_life_cost_weight` 触底（-2.975，余量 0.025<步长0.05）与 `vivhite_hp_cost_play_margin` 顶格（3.00，余量 0.00<步长0.5）后「双旋钮全尽，謦欬证据彻底停止吸收并留痕」——但拿牌端血税软顶 `vivhite_life_cost_deck_cap=60` 是从不被证据驱动的静态键，生命支付牌密度这个源头变量无任何闭环。EVIDENCE：① 425/426 局 lessons 连续两局「双旋钮全尽…彻底停止吸收并留痕」（达 evidence_batch_threshold）；② 426 局（3SCUF5ED4VJ9，F17 LAGAVULIN_MATRIARCH 阵亡）16 次拿牌 15 张生命支付牌，终局目录血税远超 60 软顶仍照拿；F17 Boss 战 T8 两血两能回合 4 张非诅咒手牌（弦光投影/并行星雨/局部同胚/三色轮舞）全部 blocked_by_hook（謦欬会令生命低于1）锁死空过，吃 21 意图阵亡——密度失控的终局形态；③ 363~380 批终局目录血税 116/108/98 远超软顶 60，血税扣分只在远段位计价、早期拿牌零约束。EXPECTED_SIGNAL：未来 3~10 局謦欬卡组阵亡且双旋钮全尽时，lessons 出现「vivhite_life_cost_deck_cap: 60.00 → 55.00（…双旋钮全尽…謦欬证据改接拿牌端血税软顶）」而非「彻底停止吸收」；选牌理由的「謦欬血税密度扣分（卡组目录血税N/软顶M…）」软顶 M 随档降至 55/50…，扣分在更低血税段位出现；终局目录血税与单局生命支付拿牌张数较 426 局（15 张）回落。证伪/回滚：留痕仍写「彻底停止吸收」→ 复查 `_lc_tighten` 消费路径；软顶下调后血税留痕密度不变且自损占比无改善、或因拿不到謦欬牌出现输出饥饿恶化 → policy.json 重置 `vivhite_life_cost_deck_cap=60.0`（BOUNDS 上限即旧锚点，恢复旧行为零差异）。

## EVIDENCE

- 426 局决策链尾部逐条核对（decision_chain_evidence.full_failure_run）：T7 起「击杀还需4回合>可存活1回合」全攻提速；T8 03:14:48 当前 2 生命、能量 2，全部非诅咒手牌因謦欬会令生命低于 1 被 blocked_by_hook，end_turn 后吃意图 21 → GAME_OVER。本局拿牌清单 16 张中 15 张生命支付牌。
- lessons 对账：425 局（拿 8 张生命支付牌）与 426 局（拿 15 张）策略进化段均为「vivhite_param_life_cost_weight -2.98 触底（余量 0.02<步长0.05）且謦欬出牌余量门 3.00 顶格（余量 0.00<步长0.5）…双旋钮全尽，謦欬证据彻底停止吸收并留痕」——证据连续两批零吸收。
- 生产现状核查（reflect.py `_lc_tighten` 封账分支 / policy.py 6982~7005 血税计价）：软顶键存在于 DEFAULT_POLICY 与 policy.json 但不在 reflect.BOUNDS，任何证据通道都调不到它；血税密度扣分的留痕接线（363~380 批）已验证健康，软顶下调后信号可直接经既有「謦欬血税密度扣分（…/软顶M…）」留痕观测。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/reflect.py：① BOUNDS 新增 `vivhite_life_cost_deck_cap: (30.0, 60.0)`——上限 60.0 即旧锚点（policy.json 重置 60.0 一键回滚，旧行为零差异），下限 30.0 贴近起始卡组血税 20，防软顶归零使首张謦欬牌即被计价、锁死整套机制；② `_lc_tighten` 封账分支改为第三级接替：双旋钮全尽且软顶余量 ≥5.0 时 `_adj(deck_cap, -5.0)` 并留痕「双旋钮全尽，…謦欬证据改接拿牌端血税软顶」；软顶也触底后才写「三级旋钮全尽，謦欬证据彻底停止吸收并留痕」。自损主导局双档收紧语义不变（一次 finalize 最多 -10）。回收通道与评分主体零改动；非白绮角色不进该通道。
- sts2-ascend/brain/knowledge.py：`vivhite_life_cost_deck_cap` DEFAULT_POLICY 注释补充第三级接替旋钮语义（键值不变）。
- sts2-ascend/brain/policy.py：血税计价段注释更新——双旋钮全尽后证据改接本软顶（行为不变，仅注释对账）。
- sts2-ascend/brain/selfcheck.py：3prg 夹具 cap2 修订为新契约（双旋钮全尽+软顶默认 60：双档证据改接软顶 60→55→50，留痕带「证据改接拿牌端血税软顶」且不得出现封账），新增 cap3 分支（软顶 30 触底：值不变、留痕「三级旋钮全尽…彻底停止吸收并留痕」）。
- 不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 謦欬卡组（≥2 张生命支付牌）阵亡局 lessons 出现「vivhite_life_cost_deck_cap: 60.00 → 55.00」式软顶下调留痕（首场謦欬阵亡即可验证）；② 后续选牌理由「謦欬血税密度扣分（卡组目录血税N/软顶M，-X…）」中 M 降至 55/50…，可直接与 372/377/380 局（终局血税 116/108/98）型超顶拿牌对账——扣分开始计价的血税段位应明显前移；③ 若终局目录血税均值与单局生命支付拿牌张数较本批（426 局 15 张）回落、且自损/掉血比下行，则源头闭环成立。证伪/回滚：留痕仍写「彻底停止吸收」→ 复查 `_lc_tighten` 分支；软顶下调后血税留痕密度不变或输出饥饿链（burst_starve 侧）恶化 → policy.json 重置 `vivhite_life_cost_deck_cap=60.0` 整体撤回（BOUNDS 上限即旧锚点，旧行为零差异）。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（3prg cap2 修订+cap3 新增；既有 3prf 单双档收紧、3prg floor/dom/nd、3prh 余量门、3prl①~⑦ 血税密度、3prn 门拦格挡救场、3sec 沙坑封底、3xg-payback 破层抵扣等全部既有夹具通过）。
- `git diff --check -- sts2-ascend/` 通过；完整 diff 已回读：brain/reflect.py（+36/-6，BOUNDS 一项+第三级接替）、brain/knowledge.py（+4/-1 注释）、brain/policy.py（+2/-2 注释）、brain/selfcheck.py（+21/-4 夹具）四个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。
# 第 427~433 局批复盘：謦欬自我复制引擎同回合复打零血税记忆——余量门带复打递增税（VIVHITE_HP_REPEAT_PLAY_TAX）

日期：2026-09-09

## HYPOTHESIS

謦欬出牌余量门（VIVHITE_HP_PLAY_MARGIN_GATE）对同回合第 1 次与第 6 次打出同名生命支付牌一视同仁——评分循环对本回合已实付血税零记忆，自我复制引擎牌（守恒递归，create_free_this_turn_copy）的每次复打都按「首打」独立估值，单回合可形成自我放血链。该假设可证伪：未来 3~10 局若「同回合第N次复打税（VIVHITE_HP_REPEAT_PLAY_TAX）」留痕从不出现（commit 账未接线），或留痕出现但复打分仍超带顶放行（幅度不足），或对局自损峰值无改善，则本假设不成立。

## EVIDENCE

- 433 局（9HTP647E98VC，F33 CRUSHER+ROCKET 阵亡）F30 棘刺蟾蜍战全链逐条核对：T2 六连打守恒递归+/守恒递归（hp 90→80→70→60→50→40→30，单回合自损 60；每次 trace 候选分恒 33.1>余量门 30.4 带顶、LIVE_ESTIMATE 恒 +24.50/+23.50），直到 30 血低血惩罚把分压进门带才拦下余牌；全场自损 70 vs 敌方掉血 68，T3 竞速观测「自付速率18.0/回合≥敌方净损9.9/回合（VIVHITE_RACE_SELF_LOSS_DOMINATES）」；F30 出场 22 血，Boss 37% 血入场，T4 四回合掉血 60 爆毙（竞速审计 T2 判死→实战 4 回合阵亡，判决本身准确，败因是入场血量）。
- 同批佐证：431 局（VBJUHSC3QQ6P，F33）F23 Monster 战自损 30/掉血 14、432 局 F17 Boss 自损 37/掉血 48——自损主导是本批常态而非孤例；433 局 F30 是单回合放血链最极端的可读样本。
- 生产现状核查（policy.py 门带段）：_hp_extra = _hp_pay * _hp_play_margin 只看当次实付，循环内无任何同回合同名复打计数；_sync_combat_play_successes 已有服务端成功回执账（_exhaust_plays/_krace_dmg 同型先例），复打计数可直接挂在同一通道。
- 相邻批次对账：402~426 批血税软顶（拿牌端源头）与本批不重叠——本批针对出牌端「同回合复打」这一门带盲区；386~391 批破层抵扣、381~385 批沙坑封底均不触碰门带。failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：① _sync_combat_play_successes 新增謦欬同回合复打账——按 combat_play_commit 服务端成功回执逐牌计数（同名基础 id 合并，+与非+同账），回合切换即清零；② _combat 门带装载段新增静态键 ivhite_hp_repeat_play_tax（仅在余量门激活时读取），并加无 commit 回合的复打账跨回合复位（新战斗由 _combat_stall_check 战斗身份重置兜底）；③ 门带计算改为 实付×余量门 + 实付×(N-1)×复打税（N=本回合同名第几次打出）：首打零差异、复打越深带顶越高、超带顶高分仍放行（软递增非硬上限）；被拦注记带「同回合第N次复打税（VIVHITE_HP_REPEAT_PLAY_TAX）」并进门拦收口名单，过门侧追加「已计价仍过门」纯观测注记（供区分「税未接线」与「幅度不足」）；④ _hp_gate_blocked 元组扩到 6 元（repeat_count），收口留痕与僵局放行/未覆盖观测消费端同步兼容。致死回合豁免与余量门一致；僵局放行闩锁停门时本税同步停用；tax=0 一键回滚（旧行为零差异），非白绮角色零改动（_hp_play_margin 恒 0 不进分支）。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 ivhite_hp_repeat_play_tax: 0.5，注释记录 433 局 F30 实证与回滚口径。
- sts2-ascend/brain/selfcheck.py：新增 3prt 夹具四分支——① 同回合首打照旧放行（复打税零差异）；② 模拟 commit 回执后同回合第 2 次复打被递增门槛拦下，且理由带「謦欬出牌门拦下…VIVHITE_HP_REPEAT_PLAY_TAX」；③ 回合切换后复打账清零、次回合首打照旧放行；④ tax=0 回滚键下同回合复打零差异且不留痕。
- 不改评分主体/阈值/竞速判决/reflect 通道；不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 任一同回合同名謦欬牌复打场面（守恒递归自我复制链为本批原型）决策链出现「同回合第N次复打税（VIVHITE_HP_REPEAT_PLAY_TAX）」留痕——按本批频率首场謦欬长战即可验证，433 局 F30 T2 型六连打应收敛为「首打放行+复打被拦」；② 单回合自损峰值（433 局 F30 T2 的 60）显著回落，自损/掉血比下行；③ 若留痕从不出现 → 复查 combat_play_commit 账与门带消费路径；若留痕出现但均为「已计价仍过门」（复打分超带顶）→ 上调 ivhite_hp_repeat_play_tax；若引擎启动受阻导致长战输出链恶化（换挡期战损上升）→ policy.json 置 ivhite_hp_repeat_play_tax=0 整体撤回（首打与旧行为零差异）。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（新增 3prt 四分支；既有 3prh 余量门、3pri 僵局放行、3prm 未覆盖观测、3prl①~⑦ 血税密度、3prn 门拦格挡救场、3sec 沙坑封底、3xg-payback 破层抵扣等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py（+63/-7，复打账+门带递增+双向留痕）、brain/knowledge.py（+10 一个静态键）、brain/selfcheck.py（+49 四分支夹具）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 461~480 局批复盘：呼唤（BECKON）「失去生命」措辞滞留税全链不可见——HAND_END_TAX 正则补型 + 纯税面主评分计价

日期：2026-09-09

## HYPOTHESIS

SOUL_FYSH 灌注的状态牌呼唤（BECKON，「在你的回合结束时，如果这张牌在你的手牌中，你失去6点生命。」）使用「失去N点生命」措辞，而 HAND_END_TAX 族正则（808~812 批落地）只认「受到N点伤害」——滞留税在收口披露、残能救场 taxstop（另被 `_SELF_COST_RE` 自残排除先行误杀）、主评分三处全部不可见；同时无伤害/格挡/抽牌面的呼唤落入「能力/增益牌」桶吃 power_round_bonus+长战加成。该假设可证伪：未来 3~10 局再遇 SOUL_FYSH 时，若 end_turn 收口从不出现「手牌滞留税HAND_END_TAX=每回合6（BECKON×N）」、呼唤仍被判「无值得出的牌（呼唤✓）」空过、或仍以「能力/增益牌｜长战加成」名义白打，则本假设不成立。

## EVIDENCE

- 480 局（0QUF68051NMG，F17 SOUL_FYSH 阵亡，decision_chain_evidence.full_failure_run 逐条核对）：T3 末能量 0 手握呼唤，回合结束 19→13 血（-6 与 BECKON 触发值精确吻合）；T5 能量 1、手牌「终止条件✗,递推星芒✗,尺度变换✗,白绮的变身式✗,呼唤✓」被判「评估后无值得出的牌」空过，1 血/8 甲吃意图 13 阵亡——可出的呼唤未被任何通道计价（本回合止血 6 点）。
- 历史同型三例：20260902-181845「白绮的变身式✗,呼唤✓,呼唤✓,递推星芒✗ 结束回合（敌意图24，我方4血/0甲）」（两张可出呼唤 = -12 未计价）；20260905-145057「呼唤✓,呼唤✓,黎曼星阵✗ 结束回合（24，4血/9甲）」；20260905-183531「闭域映射✓,呼唤✓,综合色轮✗」。反向误分类实证：20260902-165045「打出【呼唤】（能力/增益牌（第2回合）｜长战加成+4.3）」——1 费无效果牌吃增益桶加成。
- 原生机制对账（native_game_knowledge / knowledge/game/v0.111.0/mechanics）：Beckon.OnTurnEndInHand → CreatureCmd.Damage(owner, 6, Unblockable|Unpowered|Move)，HasTurnEndInHandEffect=true——不可格挡、不吃力量；SOUL_FYSH BeckonMove 每次塞 2 张（抽牌堆+弃牌堆各 1）。本批 stats_digest：SOUL_FYSH 35.6 战 15.4 死，是高频 Boss。
- 生产现状核查：`_HAND_TAX_ZHS_RE` 仅「受到\s*(\d+)\s*点伤害」一型，对「失去6点生命」零命中；`idle_energy_rescue_pick` 内 `_SELF_COST_RE`（失去N点生命）在 taxstop 识别之前执行，呼唤即使正则命中也会先被自残排除；`_score_play` 无直接数值桶对纯滞留税牌无任何特判。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：① `_HAND_TAX_ZHS_RE` 补「失去\s*(\d+)\s*点?\s*生命」交替型（保持「受到N点伤害」原支不变），`_HAND_TAX_EN_RE` 补 life 词尾，新增 `_hand_tax_amount()` 多捕获组取数助手，三处取数点（hand_end_turn_tax / 救场 taxstop / _score_play 止损计价）同步切换；旁观留痕（HAND_TAX_PLAY_AUDIT，仅用真值性）自动覆盖呼唤；② `idle_energy_rescue_pick` 把滞留税识别提到 `_SELF_COST_RE` 之前——税牌的「失去生命」是持牌条件税而非打出自付，不再被自残排除误杀，税收>最佳格挡净效益时优先打出止血（通道原语义不变）；③ `_score_play` 无直接数值桶新增纯滞留税牌分支：命中滞留税且无伤害/格挡/抽牌/回能面的牌不再落入能力牌桶吃长战加成，改按与攻击税牌同一把等效格挡尺（1.05×block_safety×blk_boost）计价并留痕「手牌滞留税牌（打出即清零N/回合滞留税，HAND_TAX_PLAY_PRICING）」；`hand_tax_play_pricing=0` 严格回落旧能力牌口径，`hand_tax_stoploss=0` 关闭救场止损通道，双双回滚锚不动既有行为。
- sts2-ascend/brain/selfcheck.py：新增 3br-5 夹具（呼唤税额识别 6/12、救场 taxstop 优先且不被自残排除、allow_taxstop=False 回落格挡、end_turn 收口披露 BECKON×1）与 3br-6 夹具（主评分「手牌滞留税牌」计价+不再误判「能力/增益牌」；旋钮=0 严格回滚旧口径）。
- 不改评分阈值/竞速判决/reflect 通道；不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 再遇 SOUL_FYSH（或其它塞「失去N点生命」手牌税的组合）时 end_turn 收口出现「手牌滞留税HAND_END_TAX=每回合6（BECKON×N）」披露，残能救场出现「残能救场[手牌税止损]…呼唤…清零手牌滞留税」——按 SOUL_FYSH 35.6 战的高频，数局内即可验证；② 呼唤主评分理由变为「手牌滞留税牌（打出即清零6/回合滞留税…）」，「评估后无值得出的牌（呼唤✓）」型空过与「能力/增益牌｜长战加成」型白打双双消失；③ Boss 战非行动段自损（呼唤税计入 SELF_LOSS_PHASE_OBS 非行动段）应下行，480 局 T3/T5 型「-6 未计价」不再出现。证伪/回滚：留痕从不出现 → 复查正则与运行时 description 字段口径；呼唤打出挤压关键格挡/输出导致战损恶化 → policy.json 置 `hand_tax_play_pricing=0`（回能力牌旧口径）或 `hand_tax_stoploss=0`（关救场止损）分级撤回。

## VALIDATION

- `py -3 -B sts2-ascend/brain/selfcheck.py`：SELFCHECK OK（新增 3br-5/3br-6 六分支；既有 3br-4 毒素/感染税、3htp 税牌主评分、3htpa 旁观留痕、3prg 血税软顶、3prl 血税密度、3prn 门拦格挡救场、3prt 复打税、3sec 沙坑封底、3xg-payback 破层抵扣等全部既有夹具通过）。
- `py -3 -B -m unittest sts2-ascend.tests.test_character_strategy`：57 tests OK。
- `git diff --check -- sts2-ascend/` 通过；完整 diff 已回读：brain/policy.py（+37/-8，正则补型+取数助手+救场排除序+纯税面分支）、brain/selfcheck.py（+66 两组夹具）两个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。


# 第 481~488 局批复盘：知识恶魔诅咒四选同价并列+点击回执丢失——机制税分极（KNOWLEDGE_DEMON_CURSE_TAX）+ 冷却轮换观测（UI_OPTION_COOLDOWN_SUPPRESSED）

日期：2026-09-09

## HYPOTHESIS

知识恶魔「知识诅咒」强制入组屏（无跳过）对瓦解/心灵腐化/懒惰/衰朽四张诅咒用 eval_reward_card 同价评分（状态垃圾分，488 局两屏均 -14.5），并列时点击恒落 index 0 的瓦解；该点击在实战中高频丢失回执（服务端已受理但状态未见效果），被 note_action_deferred 冷却轮换静默推向第二张——轨迹只留下「候选：懒惰=-14.5」式单候选假象，复盘长期无法区分「载荷只有一张」与「轮换吞没」。最终系统性吃进对多段出牌白绮最差的懒惰（SlothPower.ShouldPlay：每回合出牌<3）：488 局 F33 14:35:44 选懒惰后，次回合打出 3 张（切线星光/启发式护盾/公理护环）即黄金分割（1费）/生命流形（2费）/星图检索（0费）全部 blocked_by_hook 锁死空过；终回合意图 30 时只剩 2 次出牌额度，11 血 9 甲阵亡。该假设可证伪：未来 3~10 局若知识恶魔战决策链从不出现「知识恶魔诅咒机制税（KNOWLEDGE_DEMON_CURSE_TAX）」留痕、或「UI_OPTION_COOLDOWN_SUPPRESSED」观测从不显形而单候选屏仍复现（则说明上游载荷真只有一张，轮换假说不成立），或分极后诅咒选择仍未脱离懒惰/衰朽，则本假设不成立。

## EVIDENCE

- 488 局（21JKMZZJLBQG，F33 知识恶魔阵亡，decision_chain_evidence.full_failure_run 尾部逐条核对）：14:35:44 选【懒惰】（价值 -14.5，单候选）；14:35:49 end_turn 能量 2 余【黄金分割✗/生命流形✗/星图检索✗ 全 blocked_by_hook】；14:35:54 残能救场打出闭域映射后 11 血 9 甲吃意图 30 → GAME_OVER。竞速审计 T2 判死→实战 7 回合阵亡，判决准确，败因含出牌上限被掐。
- 生涯全量扫描（runs/）：86 屏知识恶魔诅咒决策中仅 6 屏（39/152/188/195/196/233 局）双候选且均选瓦解；其余 80 屏全部单候选、清一色吃进心灵腐化/懒惰/衰朽——474/477/478/482/486/487/488 局连续复现，达 evidence_run_threshold。
- 原生机制对账（knowledge/game/v0.111.0/mechanics）：KnowledgeDemon._curseOfKnowledgeSets 恒为 {瓦解,X} 双选；DisintegrationPower.AfterSideTurnEndLate 每回合末 6 点不可格挡自伤；MindRotPower 抽牌-1；SlothPower.ShouldPlay=_cardsPlayedThisTurn<3（出牌上限）；WasteAwayPower 能量上限-1。
- 生产现状核查：本地合成双候选载荷喂当前 Policy，瓦解/心灵腐化同分并列、稳定序选 index0 瓦解——评分无机制分极；note_action_deferred（agent.py:3154 回执丢失链）对 select_deck_card 设 4 tick 精确冷却，被冷却候选在 _card_selection 候选过滤后零留痕。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：① 新增 _KD_CURSE_TAX_BASE 与 _knowledge_demon_curse_offset——四诅咒按机制分极：心灵腐化 -1.0（抽牌-1 最轻）、瓦解 -2.0-5.0×(1-血线)（每回合末 6 点自伤随血线加深，满血时优于懒惰/衰朽、29% 血线 -5.5 仍优于懒惰）、衰朽 -5.0（3 能卡组能量-1）、懒惰 -8.0（出牌上限 3 对多段出牌謦欬卡组最差）；旋钮 knowledge_demon_curse_tax=0 时偏移恒 0、注记不出现（同价旧口径零差异回滚）；② _score_sel 计入偏移并随中标注记入链「知识恶魔诅咒机制税±N（KNOWLEDGE_DEMON_CURSE_TAX）」；③ 候选冷却过滤处新增观测闸「GATE 候选冷却轮换」warn：被 note_action_deferred 冷却抑制的候选名写入轨迹（UI_OPTION_COOLDOWN_SUPPRESSED），后续复盘可直接区分单候选载荷与轮换吞没。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 knowledge_demon_curse_tax: 1.0，注释记录 488 局实证与回滚口径。
- sts2-ascend/brain/selfcheck.py：新增 3kd 夹具四分支——① 高血线 {瓦解,心灵腐化} 机制税后心灵腐化反超且带留痕；② 28/95 血线 {瓦解,懒惰} 瓦解反超（488 局 F33 形态反转）；③ 旋钮=0 回滚同价旧口径、稳定序回落 index0、无留痕；④ index0 被 deferred 冷却后轮换到懒惰且轨迹披露被抑制候选。
- 不改评分主体/竞速判决/reflect 通道；不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 知识恶魔战（生涯 24.9 死的第一死因，482/486/487/488 连续四局遭遇）诅咒屏决策理由出现「知识恶魔诅咒机制税（KNOWLEDGE_DEMON_CURSE_TAX）」——首场遭遇即可验证；② 双候选屏优先选心灵腐化（高血线）或瓦解（低血线对懒惰），不再吃进懒惰/衰朽；③ 「GATE 候选冷却轮换（UI_OPTION_COOLDOWN_SUPPRESSED）」若显形，直接证实轮换吞没假说并披露被吞候选；若诅咒屏仍单候选但该观测从不显形，则坐实上游载荷缺卡，转 STS2-Agent fork 修复。证伪/回滚：留痕从不出现 → 复查 card_id 口径与 _score_sel 接线；分极后选瓦解导致自伤死亡链恶化（竞速生存分母被 6/回合拖垮）→ policy.json 置 knowledge_demon_curse_tax=0 整体回滚（旧口径零差异）。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（新增 3kd 四分支；既有 3zw 死牌三端、3br-5/3br-6 呼唤滞留税、3prg 血税软顶、3prl 血税密度、3prn 门拦格挡救场、3prt 复打税、3sec 沙坑封底、3xg-payback 破层抵扣等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py（+63，机制税表+助手+计价留痕+冷却观测闸）、brain/knowledge.py（+10 一个静态键）、brain/selfcheck.py（+76 四分支夹具）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 505~511 局批复盘：謦欬余量门意图 0 自由回合纯输出压制——自由回合减免（VIVHITE_HP_GATE_FREE_TURN_RELIEF）

日期：2026-09-09

## HYPOTHESIS

謦欬出牌余量门（VIVHITE_HP_PLAY_MARGIN_GATE，已顶格 3.0）对战斗语境零感知：门带只看「普通阈值 < 分数 ≤ 阈值+实付×margin」静态区间，不看敌意图、不看我方血线——敌意图总伤 0 的完全自由回合仍拦下已过普通阈值的謦欬攻击牌。自由回合自付本回合绝无致死可能（原生 hook 禁止自付致死），且 LIVE_ESTIMATE 已把实付血税计入分数，门带在此类回合是纯输出压制：拉长战斗、恶化竞速。该假设可证伪：未来 3~10 局若决策链从不出现「意图0自由回合减免过门（VIVHITE_HP_GATE_FREE_TURN_RELIEF）」留痕（减免未接线），或留痕出现但意图 0 回合自损主导比/单回合自损峰值显著恶化（放行有害），或精英/长战回合数与自损/掉血比无回落，则本假设不成立。

## EVIDENCE

- 511 局（JRTYJ0T6VAY8，F11 旧日雕像精英阵亡，decision_chain_evidence.full_failure_run 逐条核对）：T1 敌意图总伤 0、我方 45 血，门拦【弦光投影】实付2血+【绯色面积+】实付4血+【终止条件】实付4血，合计压制 30+ 点输出（连续低危拦截 1/6）；T2 意图 0 再拦弦光投影（2/6）；全程僵局放行进度止步 3/6（阈值 6），竞速审计 T4 判死→实战 7 回合阵亡——门压制的恰是本场唯一可缩短竞速的输出窗口；终段 1 血全部手牌 blocked_by_hook（原生自付致死闸实证），16 血/41 甲回合仍拦终止条件+负空间。
- 生涯全量扫描（runs/ 517 局文件）：332 局共 2239 处「敌意图总伤0…謦欬出牌门拦下」同帧记录；本批 505~511 全部 7 局复现（505/506/507/508/509/510/511 各自的 runs 文件均命中），远超 evidence_run_threshold。506 局 F12 精英战非行动段 50、507 局 F17 Boss 非行动段 79——自由回合零输出是长非行动段的组成成分。
- 生产现状核查（policy.py 门带段）：_hp_extra = _hp_pay × _hp_play_margin + 复打税，区间判定不含 incoming/my_hp 任何语境项；致死回合豁免与僵局放行（需连续 6 低危回合，511 局止步 3/6、354 局型交替意图结构性不可达）是仅有的两道泄压，均不覆盖「意图 0 即放行」这一更细粒度情形。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：① 新增静态键读取 _hp_free_relief（仅 _hp_play_margin>0 时读取，钳 [0,1]）；② 门带计算拆分量——敌意图总伤≤0 回合余量门分量按 margin×(1-relief) 折算（relief=1.0 即自由回合撤门带、回归普通阈值），复打税分量不减免（守恒递归自我复制链在自由回合照样放血，第 427~433 局批闭环保留）；③ 被拦注记公式显示折后系数并标「意图0自由回合减免（原×N，VIVHITE_HP_GATE_FREE_TURN_RELIEF）」；④ 新增纯观测注记：无减免必被拦、仅靠减免过门的打出牌带「意图0自由回合减免过门（无减免将拦+X）」——直接区分「减免未接线」与「接线但放量」。relief=0 一键回滚（旧行为零差异），非白绮角色零改动（_hp_play_margin 恒 0 不进分支）。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 vivhite_hp_gate_free_turn_relief: 1.0，注释记录 511 局实证与回滚口径。
- sts2-ascend/brain/selfcheck.py：新增 3pru 夹具四分支——① 默认 relief=1.0 意图 0 回合放行謦欬攻击且带减免留痕（511 局 F11 T1 形态反转）；② 意图>0 回合不减免、照旧拦截且无减免留痕（非自由回合零差异）；③ relief=0 回滚键下图 0 回合恢复拦截、不留痕（旧行为零差异）；④ 自由回合复打税分量不被减免冲销（同回合第 2 次复打仍拦）。3pri/3prm 四个旧夹具（vknow_sb/vknow_mx/vknow_off/vknow_uc）显式钉 relief=0——僵局放行/未覆盖观测机制面向「拦门仍持续」场景（含意图 0 回合），单独验证旧链路与闩锁。
- 不改评分主体/阈值/竞速判决/reflect 通道；不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 任一意图 0 回合手握謦欬攻击牌的场面（按生涯 332/517 局命中率，首场謦欬战即可验证）出牌理由出现「意图0自由回合减免过门（VIVHITE_HP_GATE_FREE_TURN_RELIEF）」；511 局 F11 T1 型「意图0+拦 30+ 输出」应反转为「首回合输出照打」；② 「敌意图总伤0…謦欬出牌门拦下」同帧记录在决策链中消失（纯复打税拦截除外，其留痕带 VIVHITE_HP_REPEAT_PLAY_TAX）；③ 精英/Boss 战非行动段长度与自损/掉血比回落，506 局 F12（非行动段 50）、507 局 F17（非行动段 79）型长拖减少。证伪/回滚：减免留痕从不出现 → 复查静态键读取与 incoming 口径；留痕出现但自由回合自损显著抬升、或 1 血 blocked_by_hook 终段提前 → policy.json 置 vivhite_hp_gate_free_turn_relief=0 整体撤回（旧行为零差异）；复打税被误减免 → 复查两分量拆分。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（新增 3pru 四分支；既有 3prh 余量门、3pri 僵局放行、3prm 未覆盖观测、3prn 门拦格挡救场、3prt 复打税、3prg 血税软顶、3prl 血税密度、3br-5/3br-6 呼唤滞留税、3kd 诅咒税、3sec 沙坑封底、3xg-payback 破层抵扣等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py（+43/-2，减免旋钮+门带分量拆分+双向留痕）、brain/knowledge.py（+10 一个静态键）、brain/selfcheck.py（+60，3pru 四分支+四个旧夹具钉 relief=0）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 512~529 局批复盘：意图0自由回合减免在普通怪战斗放血——减免硬仗限定（VIVHITE_HP_FREE_TURN_HARD_ONLY）

日期：2026-09-09

## HYPOTHESIS

第 505~511 批落地的謦欬门意图0自由回合减免（relief=1.0，撤余量门门带）以精英战证据立项（511 局 F11 旧日雕像意图0回合门带压制 30+ 输出），却对全部战斗类型生效。普通 Monster 战意图0回合高频出现且敌方压力低，门带被撤后「过普通阈值但未过血税门带」分位的謦欬牌持续放行付血，血量经济被慢性烧穿——这是本批普通战「自损≥敌方掉血」形态的直接驱动。该假设可证伪：未来 3~10 局普通战意图0回合若不出现「謦欬出牌门拦下…（普通战不享意图0减免，VIVHITE_HP_FREE_TURN_HARD_ONLY）」留痕（接线错误），或普通战单场自损/掉血比不回落（514 局 F2 型 20/10 依旧），或精英/Boss 战「减免过门」留痕同步消失（误伤硬仗语义），则本假设不成立。

## EVIDENCE

- 全量扫描本批 18 个 runs 文件：10 局共 60+ 处「意图0自由回合减免过门（无减免将拦+N）」同帧留痕（9PTGN5 22 处、3ZPZ99 15、YZNGYD 13、CJQT1E 12、2W8Z56/B1Z2RV 各 10、VMYDQG 7、GNKBZD/SGSRKC 各 5、GJCHTN 4）；逐条核对目标怪物，绝大多数为普通怪（小啃兽/毛绒伏地虫/缩小甲虫/蟾蜍蝌蚪/飞蝇菌子/异蛙寄生虫/蛮兽/雾菇/噬尸蛞蝓/树枝史莱姆/棘刺蟾蜍/海洋混混/双尾鼠等）。极端样本：2W8Z56 局 F12 普通战 T1 完美综合色 hp-cost=16 靠减免过门（无减免将拦+48.0），单发实付 16 血；205241 局 F25 棘刺蟾蜍战 T4 在 44 血时三连付 2+4+4=10 血。
- 自损/掉血对账（本批 combat notes）：513 局 F5 Monster 自损26/掉血20、514 局 F2 自损20/掉血10（自损为敌方 2 倍）、514 局 F5 自损10/掉血0、515 局 F2 自损22/掉血14、529 局 F6 自损18/掉血6（3 倍）——普通战自损常态化追平甚至反超敌方掉血。
- 529 局 F17 Boss 战（decision_chain_evidence.full_failure_run 逐条核对）：T4 意图0 回合预取未来实付4血+星图检索实付2血×2 均带「减免过门（无减免将拦+12.0/+6.0）」，自由回合烧 8 血后 T5 意图20 抵达、0 甲全攻再付 8 血，T6 1 血空过阵亡——硬仗减免语义本身保留（输出压制致死证据仍在），但普通战无此立项证据。
- 生产现状核查（policy.py）：`_hp_free_relief` 只按 `incoming<=0` 折算门带，对 node_type 零感知；`cctx.get("node_type")` 在同函数上游（Boss 攻坚提速分支）已可靠可用。既有安全网：普通战恢复门带后的放血死循环由 VIVHITE_HP_GATE_STALL_BREAK 闩锁兜底（231~243 批闭环），未覆盖结构由 STALL_UNCOVERED 观测（343~354 批）。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：① `_hp_free_relief` 计算后新增硬仗限定——静态键 `vivhite_hp_gate_free_turn_relief_hard_only`（默认 1）开启且 `cctx.node_type` 非 Elite/Boss 时把减免压回 0 并置 `_hp_relief_hard_suppressed` 留痕标记（node_type 缺失按普通战处理=保守回旧门带，不放大付血）；② 双向留痕：门带命中分支的 `_gate_formula` 与 end_turn 收口的 `_gate_note` 在意图0被压回门带时追加「（普通战不享意图0减免，VIVHITE_HP_FREE_TURN_HARD_ONLY）」——普通战接线与普通战自损回落均可直接从决策链核对；硬仗（Elite/Boss）减免、复打税不减免、僵局放行闩锁、margin=0 回滚全部语义不变；hard_only=0 一键回滚（普通战恢复减免，与 505~511 后行为零差异），非白绮角色零改动（_hp_play_margin 恒 0 不进分支）。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 `vivhite_hp_gate_free_turn_relief_hard_only: 1`，注释记录本批 60+ 处普通战减免过门实证与回滚口径。
- sts2-ascend/brain/selfcheck.py：3pru 新增三分支——⑤ 默认 hard_only 下普通 Monster 战意图0回合恢复拦截且留痕含 HARD_ONLY、不含减免过门注记；⑥ hard_only=0 回滚键下普通战恢复减免放行（上批行为零差异）；⑦ 默认 hard_only 下 Elite 战意图0回合减免继续生效（上批立项证据语义不变）。既有 3pru①~④（Boss ctx）不受 hard_only 影响。
- 不改评分主体/门带数值/复打税/竞速判决/reflect 通道；不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 普通战意图0回合决策链出现「謦欬出牌门拦下…（普通战不享意图0减免，VIVHITE_HP_FREE_TURN_HARD_ONLY）」——按本批频率首场普通战意图0回合即可验证；② 普通战单场自损/掉血比回落（514 局 F2 型 20/10、529 局 F6 型 18/6 → ≤1.0），SELF_LOSS_PHASE_OBS 可行动段自损下行；③ 精英/Boss 战「意图0自由回合减免过门」留痕继续出现（硬仗语义不变的直接对账）。证伪/撤回：HARD_ONLY 留痕从不出现 → 复查 cctx node_type 接线和静态键读取；普通战自损比不回落 → 减免非主因，复查 LIVE_ESTIMATE 血税计价口径；普通战放血僵局复发（STALL_BREAK 进度频繁打满/闩锁）或长战输出链恶化 → policy.json 置 `vivhite_hp_gate_free_turn_relief_hard_only=0` 整体撤回（普通战恢复减免，与上批行为零差异）。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（3pru 新增⑤⑥⑦三分支；既有 3pru①~④、3prh 余量门、3pri 僵局放行、3prm 未覆盖观测、3prn 门拦格挡救场、3prt 复打税、3prg 血税软顶、3prl 血税密度、3br-5/3br-6 呼唤滞留税、3kd 诅咒税、3sec 沙坑封底、3xg-payback 破层抵扣等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py（+35，硬仗限定+双向留痕）、brain/knowledge.py（+10 一个静态键）、brain/selfcheck.py（+44，3pru 三分支）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。


# 第 530~536 局批复盘：斩杀竞速判死后能力牌仍吃血池长战复利——竞速判死长战复利撤账（KILL_RACE_LONGFIGHT_OFF）

日期：2026-09-10

## HYPOTHESIS

kill_race 判死的语义是「击杀投影回合数 > 可存活回合数」：敌血池越大、存活视界越短，判死越硬；而能力/增益牌的长战加成 lf 正比于同一敌血池（pool/power_longfight_hp_div，封顶 power_longfight_bonus_max=7），于是能力牌恰在「复利视界已被投影证伪」的语境吃到最高加成，把能量引向 3+ 回合才能兑付的复利牌。546 批已为 lethal/race_allin 建立能力牌整分 floor（「判死局的能力复利视界超出剩余存活视界」），唯独 kill_race（非致死、非 EMA 判死口径）漏网。该假设可证伪：未来 3~10 局 kill_race 激活（决策理由带「斩杀竞速投影…全攻提速」）的回合里，能力牌理由应出现「竞速判死长战复利撤账（原+N/敌血池M，KILL_RACE_LONGFIGHT_OFF）」且不再带「长战加成+N」；若该留痕从不出现（机制未接线）或撤账后竞速局战损反而恶化（挤掉的引擎确为翻盘变量），则假设不成立。

## EVIDENCE

- 536 局（8XVF0UUDJG4Y，F33 无厌沙虫/THE_INSATIABLE 阵亡，完整链 runs/20260909-233604_8XVF0UUDJG4Y.json 逐条核对）：T2「斩杀竞速投影：击杀还需7回合>可存活4回合（沙坑吞噬钟4回合封底，SANDPIT_EAT_CLOCK_CAP；防守线复核翻盘比超限不予放行，JOINT_FLIP_TTK_CAP），全攻提速」——判死 latch 后：T3 意图21、59血，打出【公理护环】（能力/增益牌（第3回合）｜长战加成+5.7（敌血池136））与【负空间】（同+5.7），只补 9 甲掉 12；T5 意图20、38血，【公理护环】再以能力牌口径 +3.75 打出，仍只有 9 甲掉 11，T6 0 血 GAME_OVER。竞速审计 T2 判死→实战 5 回合阵亡，判决本身准确，败因含判死后能量仍流向复利牌。
- 生涯扫描（runs/ 529~536 局全量）：kill_race 语境（理由含 斩杀竞速/全攻提速/竞速生存分母/竞速自付速率 标记）的「能力/增益牌+长战加成」打出共 50+ 例——529:1、530:1（守恒递归 +5.9/血池142）、531:11、532:10、533:16（含 F33 知识恶魔 T2 变身式+ 长战加成+12.0/血池293）、534:8、536:6——远超 evidence_run_threshold=3 的独立对局线。
- 生产现状核查：_score_play 能力牌分支 lf 只在 round_no>2 减半，无任何竞速语境感知；下方 floor 仅覆盖 lethal or race_allin（policy.py 原 5477 行），kill_race 调用链（_krace_latch 武装后 race_lost=True → kill_race=True → _score_play 传参）全程未接入。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：能力牌分支新增竞速判死长战复利撤账——kill_race 且非 lethal/race_allin 时 lf 分量归零（base、开局承诺、致死豁免、race_allin/lethal 整分 floor 全部不变），why 追加「竞速判死长战复利撤账（原+N/敌血池M，KILL_RACE_LONGFIGHT_OFF）」留痕供后续对账；旋钮 kill_race_longfight_off=False 一键回滚旧口径（零差异）。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 kill_race_longfight_off: True，注释记录 536 局实证与回滚语义。
- sts2-ascend/brain/selfcheck.py：新增 3krlf 夹具四分支——① 健康同局面（血池253、T3）长战加成+3.5 原样保留；② kill_race 非致死回合 lf 撤账、分差恰为 3.5 且带留痕；③ 旋钮 False 严格回滚（分数/注记与对照逐分一致）；④ 致死竞速回合 546 批整分 floor 不受影响（仍压在出牌线下）。
- 不改竞速判决/ttk-tsurv 投影/开局承诺/reflect 通道；不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① kill_race 激活回合的能力牌理由出现「竞速判死长战复利撤账…KILL_RACE_LONGFIGHT_OFF」——按本批每局 6~16 例的频率，首个 kill_race 局即可验证；② 判死后回合的格挡/输出能量占比上升，「意图20+只补9甲同时上砧能力牌」型记录减少；③ kill_race 局竞速审计「判死→实战阵亡回合数」不再因复利白打回合而提前。证伪/撤回：留痕从不出现 → 复查 kill_race 传参与静态键读取；撤账后判死局反超率（race_audit won/latched，当前 308/736≈41.8%）显著下滑、或竞速局战损恶化 → policy.json 置 kill_race_longfight_off=false 整体撤回。后续观测点（本批不动）：先验口径 T1~T2 kill_race 下的开局承诺加成（533 局 F33 T2 变身式+ 开局承诺+6.0 同型）是否同样需要竞速语境感知，待撤账留痕积累后按证据另行立项。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（新增 3krlf 四分支；既有 3ra 败局竞速 floor、3xf/3xf-race-lethal、3xc/xcl 开局承诺、3pru HARD_ONLY、3prh/3pri/3prm/3prn/3prt 謦欬门族、3br-5/3br-6 呼唤滞留税、3kd 诅咒税、3sec 沙坑封底等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py（+20，撤账+留痕）、brain/knowledge.py（+6 一个静态键）、brain/selfcheck.py（+41，3krlf 四分支）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。


# 第 537~552 局批复盘：交替意图普通战余量门永久锁死謦欬攻击——全拦截僵局放行（VIVHITE_HP_GATE_STALL_ANY）

日期：2026-09-10

## HYPOTHESIS

謦欬余量门僵局放行闩锁（VIVHITE_HP_GATE_STALL_BREAK）只统计「本回合敌意图被格挡全覆盖」的连续拦截回合（policy.py 收口处 incoming<=my_block 才累加、否则清零）。在意图高低交替、格挡只覆盖低峰的普通 Monster 战里，该链每 1~2 回合被高危回合清零，闩锁结构性不可达，余量门永久锁死全部謦欬攻击，战斗退化为纯格挡放血死循环直至阵亡。新增「回合结束仍有謦欬候选被拦（不论覆盖）连续≥4 且敌血量零进展≥3」的全拦截放行口径后，这类战斗会在第 5 个 decide 前后闩锁放行謦欬攻击，零输出长战的回合数与自损应显著回落。该假设可证伪：未来 3~10 局若决策链从不出现「謦欬门全拦截僵局放行（VIVHITE_HP_GATE_STALL_ANY）」留痕（接线错误或条件仍不可达），或留痕出现但 549 型「意图交替+格挡覆盖低峰+零输出」长战依旧不闩锁（条件过严），或放行后早期普通战自损/战损死亡显著恶化（放行有害），则本假设不成立。

## EVIDENCE

- 549 局（QRCRZLGYYHLZ，F2 Monster 阵亡，完整链逐条核对 54 条）：意图 7/13 交替、每回合格挡 9——意图 13 的高危回合（incoming 13>block 9 未覆盖）把低危链清零，留痕「连续低危拦截 1/6→0/6」循环 17 回合、STALL_UNCOVERED 同步 1 回合反复清零；全程只出【闭域映射】实付 2 血×25≈50 自损、敌方零掉血，终段 2 血全部 blocked_by_hook 后阵亡（掉血78｜自损50）。
- 538 局（L7B0Z1KJM10A，F3 阵亡，逐条核对）：同型 7/13 交替，靠残能救场双格挡（18≥13）才勉强维持低危链，闩锁第 7 回合才到 6/6，此时已 42/56 血，最终自损44/掉血56 阵亡；闩锁后留痕甚至显示「连续低危拦截0回合≥6」（计数与闩锁状态脱节的旁证）。
- 546 局（ZHSGXY9CHY2E）：F4 Monster 掉血32｜自损36、F5 阵亡；549/538/546 构成同型早期放血死循环三连。
- 同问题历史线：343~354 批已就 354 局 F3（SHRINKER_BEETLE 意图 7/13、格挡 9，19 回合自损57/掉血78 阵亡）立 STALL_UNCOVERED 纯观测账，距今近 200 局未行为化；本批再增 3 个独立对局（538/546/549），远超 evidence_run_threshold=3——不得再只登记待观察。
- 生产现状核查（policy.py）：收口处只有 incoming<=my_block 一条累加口径；既有 _stall_no_progress（第 109 局账，敌血量不降才累加）可复用为「战斗零进展」合取条件。
- 对账本批前两批留痕：HARD_ONLY 16/16 局接线（普通战不享意图0减免 101 处）；KILL_RACE_LONGFIGHT_OFF 已在 3 局出现 8 处（543/551/552，含 552 局 F33 T2 变身式撤账+12.0、T4 公理护环撤账+4.4），接线验证通过。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：① 新增全拦截账 _hp_gate_stall_any（回合结束仍有謦欬候选被拦即累加、不论意图覆盖，无拦截回合清零）与分流标记 _hp_gate_stall_any_fired，战斗身份变化时随既有账一并重置；② 闩锁新增并列口径——静态键 vivhite_hp_gate_stall_any_turns（默认 4）达标且 _stall_no_progress≥3（敌血量零进展）时闩锁放行，同样仅撤余量门附加门槛（复打税同步停用同旧口径），普通评分/致死豁免/旧全覆盖口径不变；③ 留痕分流：全拦截口径触发的放行注记「謦欬门全拦截僵局放行：连续拦截N回合（含意图未覆盖回合）且敌血量零进展M回合≥3（VIVHITE_HP_GATE_STALL_ANY）」，end_turn 收口在拦截回合追加「连续拦截N/4含未覆盖（零进展M，STALL_ANY 进度）」；零进展合取保证推进正常的战斗不受本口径影响；any=0 一键回滚（旧行为零差异），非白绮角色零改动（_hp_play_margin 恒 0 不进分支）。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 vivhite_hp_gate_stall_any_turns: 4，注释记录 549/538/546 局实证与回滚口径。
- sts2-ascend/brain/selfcheck.py：新增 3prv 夹具三分支——① 意图 0/10 交替下旧低危链反复清零（断言 _hp_gate_stall==0）而全拦截账 4 连后第 5 个 decide 闩锁放行、带 STALL_ANY 留痕、闩锁后回归检查、新战斗重置三态；② 敌血量逐回合下降（160→120）时零进展条件不达成、5 连拦截仍不闩锁（推进战斗零差异）；③ any=0 回滚键下 6 连拦截不放行、不留痕（旧行为零差异）。既有 3pri 两个旧夹具（hi-incoming 5 连高危、stalloff 7 连）显式钉 any=0——它们单独验证旧「全覆盖」链路与旧键回滚语义，新口径由 3prv 单独验证（同 3pru 钉 relief=0 的既有模式）。
- 不改评分主体/门带数值/复打税/竞速判定/reflect 通道；不改 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 任一「意图交替+格挡覆盖低峰」的普通战（按 354/511/538/546/549 的历史频率，数局内必现）决策链出现「连续拦截N/4含未覆盖（STALL_ANY 进度）」并在达标后出现「謦欬门全拦截僵局放行（VIVHITE_HP_GATE_STALL_ANY）」——留痕显形即验证接线；② 549 型「17 回合零输出、自损≈50、F2/F3 阵亡」战斗消失：同型战斗在放行后转为正常输出收尾，早期 Monster 战自损/掉血比与战斗回合数回落；③ 推进正常的战斗（敌血量持续下降）不出现 STALL_ANY 留痕（零进展合取的直接对账）。证伪/撤回：留痕从不出现 → 复查 _hp_gate_blocked 口径与 _stall_no_progress 接线；留痕出现但同型零输出长战依旧 → 条件过严，考虑降阈值或放宽零进展合取；放行后早期普通战自损死亡显著恶化（如放行回合自付后吃满高意图死亡链增多）→ policy.json 置 vivhite_hp_gate_stall_any_turns=0 整体撤回（旧行为零差异）。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（新增 3prv 三分支；既有 3pri 余量门族、3prm 未覆盖观测、3prn 门拦格挡救场、3prt 复打税、3pru 自由回合减免/HARD_ONLY、3krlf 竞速撤账、3kd 诅咒税、3br-5/3br-6 呼唤滞留税、sec 沙坑封底等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py（+49/-2，全拦截账+闩锁并列口径+双向留痕）、brain/knowledge.py（+9 一个静态键）、brain/selfcheck.py（+92，3prv 三分支+两个旧夹具钉 any=0）三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不进 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。


# 第 553~559 局批复盘：謦欬血税软顶 reflect 下限扩档 30.0→15.0（VIVHITE_LIFE_COST_DECK_CAP_FLOOR_EXT）

日期：2026-09-10

## HYPOTHESIS

謦欬死亡证据链第三级旋钮 vivhite_life_cost_deck_cap 的 reflect 下限 30.0 已于 559 局触底（policy.json=30.0、余量 0.00<步长 5.0），life_cost_weight 触底（-2.98）与出牌余量门顶格（3.00）在先，三级旋钮全尽后謦欬卡组阵亡证据「彻底停止吸收并留痕」；而本批证据仍同向，下限扩至 15.0（步长 -5.0 与 60.0 锚点不变）即可让同向证据恢复吸收。可证伪：若扩档后謦欬卡组阵亡局 lessons 不再出现「证据改接拿牌端血税软顶」、deck_cap 不下调，或拿牌端出现大面积跳过/输出饥饿恶化，则假设证伪。

## EVIDENCE

- 559 局（EAPVYVADK63Q）lessons 尾部原文：「vivhite_param_life_cost_weight -2.98 触底（余量 0.02<步长0.05）且謦欬出牌余量门 3.00 顶格（余量 0.00<步长0.5）且血税软顶 30.00 触底（余量 0.00<步长5.0）——白绮謦欬卡组（本局拿19张生命支付牌）阵亡——三级旋钮全尽，謦欬证据彻底停止吸收并留痕」。
- 559 局逐条核对 decision_chain_evidence.full_failure_run：F33 THE_INSATIABLE Boss 战 T5 一回合连打三张謦欬攻击（尺度变换+实付4、尺度变换+复打实付4、终止条件实付4，合计自付12血），0 格挡裸接意图20，竞速审计 T4 判死→实战 5 回合阵亡（掉血110｜自损27）；拿牌 19 张生命支付牌。
- 555 局（PCERAVAKT7XL）F17 Boss 战 自损39/掉血30（自损反超敌方），同批 553 局 F11 Elite 自损13/掉血8、554 局 F2 自损20/掉血0——謦欬实付主导死亡的证据方向跨批次未变。
- 代码现状逐行核对：reflect.py BOUNDS["vivhite_life_cost_deck_cap"]=(30.0, 60.0)，_lc_tighten 第三级在余量<5.0 时只追加封账留痕不改值；policy.json 当前值 30.0 恰好钉在下限，步长 -5.0 永远不可达——证据吸收通道结构性关闭。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/reflect.py：BOUNDS["vivhite_life_cost_deck_cap"] 下限 30.0→15.0（步长 -5.0、上限/锚点 60.0 不变），注释记录 559 局触底封账与本批同向证据；第三级改接注释同步更新。15.0 仍低于起始卡组血税 20，保留「防软顶归零锁死整套机制」的原始防线；回滚=下限恢复 30.0（policy.json 重置 60.0 另可整体回滚本旋钮）。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 该键注释同步 BOUNDS 15.0~60.0 与扩档出处。
- sts2-ascend/brain/policy.py：血税密度计价注释同步新下限与出处（计价公式本身不变——运行时行为差异仅来自 reflect 继续下调后的 policy 值）。
- sts2-ascend/brain/selfcheck.py：3prg 夹具更新——旧 cap3（三旋钮全尽+软顶30.0）改为断言继续吸收（30→25→20）且不得封账；新增 cap4（软顶15.0）断言触新下限后不再改值且「三级旋钮全尽/彻底停止吸收并留痕」封账照旧。
- 不改计价公式/步长/锚点/其他 BOUNDS/出牌侧闸门；不改 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## EXPECTED_SIGNAL

未来 3~10 局：① 謦欬卡组阵亡局 lessons 重新出现「双旋钮全尽……证据改接拿牌端血税软顶」、vivhite_life_cost_deck_cap 由 30.0 逐级 25.0→20.0 下调（吸收恢复的直接对账，559 型封账文不再出现）；② 单局生命支付牌拿牌数由 559 局 19 / 426 型 15~16 降至 ≤12，终局卡组目录血税合计回落；③ 拿牌 trace 中「謦欬血税密度扣分（VIVHITE_LIFE_COST_DECK_TAX）」在更低卡组血税开始显形。证伪/撤回：封账文仍出现 → 复查 reflect 第三级分支与 BOUNDS 接线；拿牌大面积跳过、路径注记「输出饥饿」频率显著上升或 F<10 早亡增多（密度扣分过强误伤卡组构建）→ policy.json 重置 60.0 且 BOUNDS 下限回 30.0 整体撤回。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（3prg 更新+新增 cap4；既有 cap2 60→55→50、floor 改接余量门、3prh 余量门族、3pri/3prm/3prn/3prt/3pru/3prv、3krlf、3kd、3br-5/3br-6、sec 等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/reflect.py（+9/-3，BOUNDS 下限扩档+注释）、brain/knowledge.py（+2/-1 注释）、brain/policy.py（+2/-1 注释）、brain/selfcheck.py（+22/-6，3prg 更新+cap4）四个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不进 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 560~576 局批复盘：SLEEP_GUARD 在产 9 场族母遭遇零留痕——敌能力快照观测落地（ENEMY_POWERS_SNAPSHOT_OBS）

日期：2026-09-10

## HYPOTHESIS / EVIDENCE / EXPECTED_SIGNAL

- **HYPOTHESIS**：沉睡保期禁攻（SLEEP_GUARD，b485c249 于 2026-09-07 起在产，
  战斗端把沉睡≥2层敌人的未格挡非击杀攻击压到禁玩线）在 vivhite profile 从未
  显形——本批 576 局（A4JFCSM4QX1F，F17 乐加维林族母阵亡）T1~T3 三个零意图
  回合连续打出弦光投影/终止条件（各付 2~4 血），决策理由全为「单体伤害≈N」
  正常口径、零 SLEEP_GUARD 留痕；同代码用 API 契约载荷（power_id=
  ASLEEP_POWER、amount=3）本地复现（direct _score_play 与 decide 端到端）拦截
  正常、理由带 SLEEP_GUARD 注记。力量账本（自我强化体优先转火 1307 条）与
  滑溜账本（滑溜逐段折算 32 条）证明敌方 powers 通道整体在产，但
  _enemy_power_stack 对「单能力缺失」或「amount=null」一律静默按 0 处理——
  载荷缺口与逻辑缺口从决策链不可分辨。该假设可证伪：下一场族母（或其他
  Boss/Elite）战斗的首个出牌段决策理由应出现「敌能力快照：乐加维林族母
  [ASLEEP_POWER×3,PLATING_POWER×12]（ENEMY_POWERS_SNAPSHOT_OBS）」——
  ① 快照含 ASLEEP_POWER×≥2 而攻击仍打出 → 逻辑缺口成立，下批修 veto 接线；
  ② 快照无 ASLEEP_POWER 或显示 ×∅ → 载荷缺口成立，下批走上游修复或名称/
  意图兜底；③ 快照在且 SLEEP_GUARD 正常拦截（T2/T3 意图保持 0）→ 576 异常
  为瞬态，观测位转常驻对账。
- **EVIDENCE**：① 576 局 packet 全链 123 条切片逐条核读 + 完整链 runs/
  20260910-073910_A4JFCSM4QX1F.json F17 全 33 条：T1 82 血起，三回合自损
  8/10/4，Boss T4 起 14/21/22 滚动火力，T9 15 血孤注阵亡（竞速审计 T8 判死
  →实战 9 回合）；② 全 profile 扫描：SLEEP_GUARD 留痕 0 条；2026-09-07 部署
  后族母遭遇 9 场（541/545/548/559/563/568/574/575/576，其中 541/548/563/576
  四场已逐条核对 F17 T1 全部提前唤醒），独立对局数 ≥ evidence_run_threshold=3；
  ③ 原生档核读 mechanics/monsters.jsonl LagavulinMatriarch（AfterAddedToRoom→
  Sleep 挂 Plating12+Asleep3；AsleepPower.AfterDamageReceived：UnblockedDamage
  !=0 即剥 Plating、Stun 接 WakeUpMove）与 runtime/powers.jsonl（ASLEEP_POWER
  id 与「沉睡」译名确认）；④ 上游 API 契约核读 CharTyr/STS2-Agent main
  GameStateService.BuildCreaturePowerPayloads：敌 powers 以 power_id/name/
  amount(nullable int) 上报，契约上可读；⑤ 本地复现探针（当前 HEAD）：同载荷
  下 _score_play 返回 -50/SLEEP_GUARD 留痕、decide 端到端 end_turn——机制
  本身无回归。
- **EXPECTED_SIGNAL**：未来 3~10 局——① 每场 Boss/Elite 战首个出牌段决策理由
  出现一条 ENEMY_POWERS_SNAPSHOT_OBS 快照（每场一次，第二 tick 起不重复）；
  ② 族母局快照直接给出上述三分支判定证据；③ 普通战零快照（观测面只覆盖
  硬仗）。证伪/撤回：快照从不出现 → 复查 cctx node_type 接线与战斗实例身份；
  快照证明载荷完整但 SLEEP_GUARD 仍不拦截 → 按逻辑缺口修 veto；观测本身引发
  任何评分/动作差异 → policy.json 置 enemy_powers_snapshot_obs=0 整体撤回
  （旧行为零差异）。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：__init__ 新增 _powers_obs_combat 战斗实例身份；
  _combat 竞速投影段后新增观测位——静态键 enemy_powers_snapshot_obs（默认 1）
  开启且 cctx.node_type ∈ {Boss, Elite} 时，把本场首个走到出牌段 tick 的敌方
  powers 身份（power_id×amount，amount 缺失记 ∅，无能力记「无能力」）一次性
  追加进 danger_note 留痕；首 tick 若被药水段提前返回不消耗本次快照。评分/
  判决/动作零改动（纯字符串注记）。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键
  enemy_powers_snapshot_obs: 1，注释记录 9 场零留痕实证与回滚口径。
- sts2-ascend/brain/selfcheck.py：新增 3ps 五锚——① Boss 战首 tick 快照含
  ASLEEP_POWER×3（沉睡禁攻同帧依旧先生效）；② 同实例第二 tick 不重复；
  ③ 新实例重新落账；④ Monster 普通战零快照；⑤ 键=0 严格回滚且动作不变。
- 不改 SLEEP_GUARD/veto 口径、血税链、竞速投影、reflect 通道；不动 runs/
  stats/policy.json/lessons.md/review_queue 等只读在线状态。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（3ps 五锚新增；既有
  3sg 七锚、3pru①~⑦、3prh/3pri/3prm/3prn/3prt/3prg/3prl、3br-5/3br-6、3kd、
  3sec、3xg-payback 等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py
  （+41，观测位+实例身份）、brain/knowledge.py（+8 一个静态键）、
  brain/selfcheck.py（+59，3ps 五锚）三个生产/测试文件 + 本报告与口播短评；
  未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆
  残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

---

# 白绮謦欬零压付血闸复盘（第 577~589 局批）

日期：2026-09-10

## HYPOTHESIS / EVIDENCE / EXPECTED_SIGNAL

- **HYPOTHESIS**：普通 Monster 战敌方零威胁（意图≤0）的非致死/非竞速回合，
  謦欬实付买的是「提速」，而提速在敌方不出手时零收益——余量门带（3.0 顶格）
  只拦「阈值~阈值+实付×margin」的边际分，高分謦欬牌全额付血照过；三级旋钮
  （life_cost_weight -3.00 / 余量门 3.00 / 血税软顶 15.00）已全尽封账，该
  泄漏无任何既有闸门承接。
- **EVIDENCE**：589 局 `0AP4ZV61DL0U` 完整 441 条决策逐段核对——F22 T4 敌意图
  总伤 0、我方 90 血，仍打出分治法阵+实付 4 血买抽牌提速（全场掉血 0｜自损
  15）；F25 Elite 掉血 0｜自损 18、F28 Elite 掉血 2｜自损 15 同批同型；
  577-F22 掉血 9｜自损 19、578-F25 掉血 3｜自损 14 跨局复现（≥3 独立对局
  达 evidence_run_threshold）。F33 Boss 战 T4 判死→实战 6 回合阵亡，走廊
  慢性烧血直接压缩 Boss 容错。
- **EXPECTED_SIGNAL**：未来 3~10 局——① 普通战「掉血≈0 自损≥12」形态消失或
  自损显著回落；② 决策链出现「謦欬零压付血闸…VIVHITE_HP_ZERO_PRESSURE_GATE」
  留痕且被拦候选不再经 marginal/残能救场绕行；③ 普通战 STALL_ANY/STALL_BREAK
  闩锁不放行高频化（零威胁战唯一输出全是謦欬牌时 4 回合内有界放行兜底）；
  ④ 普通战掉血与战斗回合数不回升。证伪/撤回：自损形态无变化 → 复查
  node_type/意图口径接线；闩锁高频放行或掉血回升 → policy.json 置
  vivhite_hp_zero_pressure_gate=0 一键回滚（旧行为零差异）。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：謦欬门体系新增零压付血闸——普通 Monster 战
  意图≤0 的非致死/非竞速回合，hp_pay>0 且本打不击杀目标（可击杀/kills≥1
  豁免：零压回合击杀买断敌方下一回合出手权）的謦欬候选视同门拦，入
  _hp_gate_blocked 照旧退出 marginal/残能救场通道并喂僵局账；Elite/Boss 不
  启用（505~511 批自由回合减免已证伪硬仗意图0输出压制）；意图0减免生效的
  回合（hard_only=0 回滚口径）本闸同步不启用；end_turn 门拦披露按行追加
  VIVHITE_HP_ZERO_PRESSURE_GATE 标记；STALL_BREAK/STALL_ANY 闩锁把余量门压 0
  时本闸同步停用（死锁兜底）。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键
  vivhite_hp_zero_pressure_gate: 1，注释记录跨局实证与回滚口径。
- sts2-ascend/brain/selfcheck.py：新增 3prz 五锚——① 普通战意图0高分謦欬牌
  被视同门拦且留痕；② gate=0 回滚键恢复旧行为（打出）且零留痕；③ 击杀打
  豁免放行；④ Elite 意图0不启用（减免语义不变）；⑤ 意图>0 普通战不启用。
- 不改评分公式、余量门带、复打税、自由回合减免、竞速/孤注豁免、reflect
  通道；不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（3prz 五锚新增；既有
  3pru①~⑦（含 hard_only=0 回滚口径与减免交互）、3prh/3pri/3prm/3prn/3prt/
  3prg/3prl/3prv、3sg、3ps 等全部既有夹具通过——首轮自检曾捕获本闸翻越
  hard_only=0 减免回滚口径的交互缺口，已加减免优先约束并复跑通过）。
- 完整 diff 已回读：brain/policy.py（+44，闸门+披露标记）、brain/knowledge.py
  （+17 一个静态键及注释）、brain/selfcheck.py（+64，3prz 五锚）；未触碰
  runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的
  assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 590~595 局批复盘：知识恶魔诅咒屏冷却吞优强吃最差——强制入组屏冷却等待闸（UI_OPTION_COOLDOWN_FORCED_WAIT）

日期：2026-09-10

## HYPOTHESIS / EVIDENCE / EXPECTED_SIGNAL

- **HYPOTHESIS**：无跳过动作的强制入组选牌屏上，评分最高的候选若正处于 409/回执丢失短冷却（note_action_deferred 置 4、按 decide 逐拍衰减自动恢复），旧口径立即改点严格更差的剩余候选——瞬态刷新竞争被兑换成永久更差诅咒。改为有界等待（≤4 decide）恢复精确目标即可保住机制税排序的选择，等待期间不新发动作、冷却不会被重新武装，代价仅为数秒等待。可证伪：未来 3~10 局若知识恶魔战（或其他强制屏）决策链从不出现「UI_OPTION_COOLDOWN_FORCED_WAIT」留痕而 UI_OPTION_COOLDOWN_SUPPRESSED 仍显形（接线错误或条件仍不可达），或等待决策超过 4 拍仍不恢复点击（有界性失败），或等待恢复后诅咒选择仍未脱离懒惰/衰朽最差档（假设无效），则本假设不成立。
- **EVIDENCE**：595 局（8WAK6DGQ5AYK，F33 知识恶魔阵亡）完整链逐条核对——两连战斗中诅咒强制屏的 GATE 候选冷却轮换 双双 warn：① 13:08:25 屏「被冷却抑制候选：心灵腐化（UI_OPTION_COOLDOWN_SUPPRESSED）」→ 强吃瓦解（机制税-3.0@80% 血线，被抑制的心灵腐化税-1.0 严格更优）；② 13:09:15 屏「被冷却抑制候选：瓦解」→ 强吃懒惰（税-8.0，对多段出牌謦欬卡组最差，被抑制的瓦解税-4.65@47% 血线严格更优）。懒惰的 SlothPower 出牌上限随后在末段 3 回合锁死 5 次出牌（13:09:20 公理护环×2(0费) blocked_by_hook、13:09:34 闭域映射、13:09:42 综合色序+闭域映射），终段 Boss 余约 16 血时我方 0 血阵亡——任一被锁的格挡/0费能力打出都足以翻转。488 局 F33「选懒惰后次回合 3 牌全 blocked_by_hook，11 血 9 甲阵亡」同型、529 局 F33 三连瓦解屏同线，独立对局证据 ≥3 达 evidence_run_threshold；481~488 批预注册的「轮换吞没」观测本批首次在实战中双屏显形，坐实吞没假说且证明现有机制税在单候选假象下被架空。
- **EXPECTED_SIGNAL**：未来 3~10 局——① 知识恶魔战（生涯 31.5 权重第一死因，近批高频遭遇）或其他强制屏出现「选牌界面：最高分候选【X】处于短冷却……（UI_OPTION_COOLDOWN_FORCED_WAIT）」等待决策，随后 4 拍内点击恢复的精确目标；② 诅咒屏选择向机制税排序回归（高血线心灵腐化、低血线瓦解），不再吃进懒惰/衰朽；③ 懒惰诱发的出牌上限锁死形态（blocked_by_hook 成串）在 Boss 战末段消失。证伪/撤回：等待留痕从不出现且抑制观测仍显形 → 复查 _cooled_out/_score_sel 接线；等待循环超 4 拍 → 冷却衰减接线复查；等待后仍吃进最差诅咒 → policy.json 置 ui_option_cooldown_forced_wait=false 整体回滚（旧轮换口径零差异）。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：_card_selection 通用拿牌分支新增强制屏冷却等待闸——无跳过动作（强制入组）且存在被冷却抑制候选时，用同一 _score_sel 口径对被抑制候选评分，其最高分严格高于剩余最高分时返回有界等待决策（wait=0.6，冷却 4 拍自动衰减恢复），轨迹追加「GATE 强制屏冷却等待」warn 与 UI_OPTION_COOLDOWN_FORCED_WAIT 留痕；可跳过屏、升级/献祭/牌堆顶等语义分支与全候选被冷却的既有 _cooldown_wait 路径不受影响。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 ui_option_cooldown_forced_wait: True，注释记录 595/488 局实证与回滚口径（False=旧轮换零差异）。
- sts2-ascend/brain/selfcheck.py：3kd 夹具重排——④ 钉 ui_option_cooldown_forced_wait=False 保留旧轮换+观测披露断言作为回滚锚（同 3pru 钉 relief=0 的既有模式）；新增⑤默认口径更优候选被抑制必有界等待且双留痕、⑥冷却 4 拍衰减后点击精确更优目标瓦解、⑦被抑制候选本身更差时不等待立即点剩余最优、⑧可跳过自愿屏不启用等待闸。
- 不改机制税分极值、冷却时长/衰减、_sel_tried 接受口径、reward/shop/event 其他冷却消费点；不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（3kd 重排④+新增⑤⑥⑦⑧；既有 3prz 零压付血闸、3prv STALL_ANY、3pru/3prt/3prg、3sg、3ps、3br-5/3br-6、sec 等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py（+32，等待闸+留痕）、brain/knowledge.py（+9 一个静态键及注释）、brain/selfcheck.py（+66/-4，3kd 重排+四新锚）；未触碰 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 596~601 局批复盘：零压闸误拦謦欬攻击白打窗——攻击牌豁免门拦、回归余量门带计价（VIVHITE_HP_ZP_ATTACK_EXEMPT）

日期：2026-09-10

## HYPOTHESIS / EVIDENCE / EXPECTED_SIGNAL

- **HYPOTHESIS**：謦欬零压付血闸（577~589 批新增）把普通 Monster 战意图≤0
  回合的 hp_pay>0 謦欬候选**全部**视同门拦，但其立项证据只覆盖抽牌/提速类
  非攻击牌（589-F22 分治法阵+实付 4 血买抽牌）。对脚本循环敌人，意图 0 回合
  恰是蓄力/空窗回合（SPINY_TOAD 的 Spikes 蓄力：原生机制确认该回合蟾蜍无
  荆棘），謦欬攻击在此压低敌血＝缩短战斗＝减少未来意图周期，收益非零；硬拦
  攻击牌把输出挤进需要同时防御（甚至荆棘反伤）的高压回合，拉长战斗、放大
  总战损。把攻击牌移出门拦、回归「余量门带计价」（边际付血仍被既有门带拦）
  即可恢复白打窗而不撤 513/514/529 放血防线。可证伪：未来 3~10 局若普通战
  「掉血≈0 自损≥12」形态显著回升（放血防线被穿透）、STALL_ANY/STALL_BREAK
  闩锁放行高频化，或豁免注记从不显形（接线错误），则假设不成立。
- **EVIDENCE**：601 局（SVX64LWV96AY，F27 SPINY_TOAD 阵亡）完整链逐条核
  对——T1 我方 47 血/4 能量/敌意图 0（Spikes 蓄力回合，无荆棘），零压闸拦
  下整手謦欬攻击（终止条件+实付4、切线星光实付2、闭域投影+实付4）空过；
  T2 荆棘+爆炸意图回合反而付血打进荆棘（实付约 8+荆棘反伤），全场掉血
  47｜自损 15｜非行动段 55，8 回合阵亡。跨局：596 局 12 处、601 局 16 处
  决策含 ZERO_PRESSURE_GATE 拦下记录，多为 67~94 血健康状态整手/大半手空过
  （596-F22 T2 拦 6 张、601-F13 T6 拦 5 张、601-F24 T1 拦 4 张）。原生机制
  核对（v0.111.0 mechanics/monsters.jsonl）：SPINY_TOAD 固定循环
  Spikes(BuffIntent,+5 荆棘)→Explosion(23,−5 荆棘)→Lash(17)——意图 0 的
  Spikes 回合与 Lash 回合是仅有两个无荆棘攻击窗，零压闸恰好封死其中一类。
- **EXPECTED_SIGNAL**：未来 3~10 局——① 普通战意图 0 回合决策链出现「零压
  回合謦欬攻击豁免…（VIVHITE_HP_ZP_ATTACK_EXEMPT）」注记且攻击牌按门带计
  价打出；②「敌意图总伤0+謦欬出牌门拦下（攻击牌）」整手空过记录消失（非
  攻击謦欬拦截留痕仍在）；③ 遭遇脚本循环敌人的战斗回合数与全场掉血下降；
  ④ 普通战全场自损/掉血比不恶化（余量门带 3.0 顶格计价仍在）。证伪/撤回：
  放血形态回升或闩锁高频放行 → policy.json 置 vivhite_hp_zp_attack_exempt=0
  一键回滚（577~589 旧口径零差异）；豁免注记零显形 → 复查策略目录
  card_type 接线。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：零压付血闸新增攻击豁免分支——默认（静态键
  vivhite_hp_zp_attack_exempt=1）普通 Monster 战意图≤0 回合謦欬**攻击牌**
  （策略目录 card_type=="attack" 或载荷观测类型兜底，目录外/非白绮恒否）
  不再视同门拦，仅追加豁免注记供对账，余量门带计价/复打税/击杀豁免/
  STALL 闩锁体系全部不变；非攻击謦欬（格挡/抽牌/增益）维持视同门拦并照
  旧入 _hp_gate_blocked 喂僵局账；子键 0 恢复 577~589 批旧口径（攻击一并
  门拦，旧行为零差异）；主键 vivhite_hp_zero_pressure_gate=0 仍整体回滚。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键
  vivhite_hp_zp_attack_exempt: 1，注释记录 601-F27 实证、原生循环机制核对
  与回滚口径。
- sts2-ascend/brain/selfcheck.py：3prz 重排——① 改钉新默认：意图0回合高分
  謦欬攻击（弦光投影）按门带计价放行且留豁免注记、零压闸标记不再出现；
  新增①b 非攻击謦欬（白绮的变身式，实付4血）维持视同门拦并留痕；新增①c
  豁免子键=0 恢复攻击视同门拦（回滚锚）；既有②主键回滚、③击杀豁免、
  ④Elite 不启用、⑤意图>0 不启用四锚原样通过。
- 不改评分公式、余量门带/顶格 3.0、复打税、自由回合减免 hard_only、
  life_cost_weight/血税软顶三级封账、竞速/孤注豁免、reflect 通道；不动
  runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（3prz 重排①+新增
  ①b/①c；既有②~⑤、3pru 自由回合减免族、3prn 救场格挡、3prv STALL_ANY、
  3prt 复打税、3prg 血税软顶、3kd 诅咒税/冷却等待、3br-5/3br-6、sec 等全部
  既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py
  （+49/-6，豁免开关+门拦分支+注记）、brain/knowledge.py（+14 一个静态键及
  注释）、brain/selfcheck.py（+49/-4，3prz 重排+两新锚）；未触碰
  runs/stats/policy.json/lessons.md/review_queue 等只读在线状态；克隆残留
  assets 超长路径删除告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 602~614 局批复盘：Boss 分幕子账本 int() 截断计数器——前夜悲观战损虚高 8~10 倍、91% 血前夜被必败弃疗（BOSS_ACT_TRUNC 重落地：c51b8252 被宿主安全撤销后的 HEAD 重实现）

日期：2026-09-11

## HYPOTHESIS / EVIDENCE / EXPECTED_SIGNAL

- **HYPOTHESIS**：Knowledge.commit_enemy_fight 的 Boss 分幕子账本用
  int(old)+1 累积 encounters/deaths/hp_pool_n/fire_rounds——在线统计每局
  ×STAT_DECAY_PER_RUN(0.9965) 比率守恒衰减后 int() 截断小数，计数器被永久
  钉死在个位数，而 float 分子（hp_lost_sum/hp_pool_sum/fire_sum）正常累积，
  分幕「场均战损/血池」系统性虚高 8~10 倍。oss_loss_stats(act) 消费虚高
  均值使前夜悲观战损（×boss_eve_pess_mult 1.5）恒超最大生命：翻转带恒触发，
  且判死局「回血后余量仍≤安全余量」对整个血条恒真——高血前夜被弃疗改锻造，
  441~446 批「翻转带回血至上」被架空。该病灶 295~305 批已完整修复
  （c51b8252，自检通过）但 5 分钟后因新代码启动失败被宿主安全撤销
  （2f782e34，rollback_from_marker 机制），此后无人重落地，当前 HEAD 仍是
  int() 截断版本。runner 自 f2c17aad（08-27）起在 stage=imported 后即释放
  仓库锁、锁外等待 ready（Knowledge 构造可安全自取该锁），启动失败与本改动
  无因果链证据；按 d8a11849 先例由本批基于当前 HEAD 重实现。
- **EVIDENCE**：① 本批决策链实证消费——603 局前夜「悲观战损884=场均589
  ×1.5」（一幕）、609 局「悲观战损1709=场均1139×1.5」、610 局「必败弃疗改
  锻造（当前 91%；悲观战损1744=场均1162×1.5）」（二幕 F32 前夜，91% 血
  弃疗后 F33 阵亡）——场均量级 589~1162，而本批实战 Boss 单场掉血仅
  78~100；≥3 独立对局达 evidence_run_threshold。② clone 内在线 stats 只读
  核算：分幕子账 act1 场均 455.8~965.0、act2 1007.2~1421.4 vs 同库全量账
  同组合 37.7~86.4；WATERFALL_GIANT 子账 hp_lost_sum=2222.6417892319973 与
  主账逐位相等，而子账 encounters=4.965（钉死）vs 主账 40.88——衰减对分子
  分母同乘，唯 int() 每写截断能制造该背离。③ 614 局（X6HFURH6D3M0，F33
  知识恶魔阵亡）全链已逐条深读：两连诅咒屏选择正确（心灵腐化/瓦解，590~595
  批冷却等待闸口径在产），死因输出饥饿+自损（既有旋钮封账覆盖），本批主
  假设取自账本层；602/604/613 局 F17 一幕 Boss 战自损 24~59 同链核对。
- **EXPECTED_SIGNAL**：未来 3~10 局——① 前夜留痕「场均N」从 589~1162 量级
  回落至全量账量级（约 40~90，一幕偏低、二幕偏高），翻转带/安全区/必败
  三区真实分流重新可观测；② stats.json 出现 boss_act_trunc_repair_v1 标记，
  各 boss 子账 encounters/hp_pool_n 逐局浮点增长（不再钉死个位数）；③ 约
  3 场同幕 Boss 战后分幕口径恢复，高血前夜（610 局 91% 型）不再被恒真
  「必败」弃疗。证伪/撤回：场均留痕不变或计数器仍钉死 → 修复未生效，复查
  消费路径与迁移标记；前夜裁决显著恶化（贴线局被错误弃疗/回血）→ git
  revert 本提交整体回滚（改动集中于 knowledge.py 写侧/迁移 + selfcheck
  夹具，无评分/阈值/动作公式变更）。

## PRODUCTION_CHANGE

- sts2-ascend/brain/knowledge.py：
  - commit_enemy_fight 同族 6 处 int() 截断计数器改浮点累积（子账
    encounters/deaths/hp_pool_n/fire_rounds + 主账 hp_pool_n/fire_rounds），
    与主账 encounters/boss_encounters 既有浮点范式一致；读取端全部经
    int() 取值，类型兼容。
  - 新增一次性迁移 _repair_boss_act_trunc_counters（随 repair_phantoms
    闸门执行，自检加载真实库传 repair_phantoms=False 不触发）：分母小数
    部分已被 int 销毁、逐幕分布无法反推，诚实修复为作废 boss_act 子账本；
    读取端样本不足时按既有设计回落全量账（血池读取另有
    HP_POOL_READ_CLAMP 逐组合钳制双保险），修复后的浮点计数器自新样本
    起正确累积，约 3 场同幕 Boss 战后恢复分幕口径；标记键
    stats.boss_act_trunc_repair_v1 防重复执行。
- sts2-ascend/brain/selfcheck.py：新增 3br-act-trunc 夹具四分支——① 浮点
  计数器跨一次衰减后正常增长（×0.9965+1，不再钉 1）、主账 hp_pool_n 同验；
  ② 前置态复现分幕虚高（1900/3≈633），迁移后子账作废、标记置位、
  boss_loss_stats(1) 回落全量账 60；③ 幂等与标记预置跳过；④ 迁移后 3 场
  新样本恢复分幕口径（场均 40、n=3）。
- 不改任何评分/阈值/动作选择公式；只修账本写入口径与一次性作废不可恢复
  数据。撤回条件单一：git revert 本提交。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（新增 3br-act-trunc
  四分支；既有 3br-pool-clamp/3br-pool-read-clamp、3prz 零压闸族、3kd 诅咒
  税族、3ps、3sg、3br-5/3br-6、sec 等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/knowledge.py
  （+49/-6，写侧 6 处浮点化 + 一次性迁移方法）、brain/selfcheck.py（+74，
  3br-act-trunc 四分支）；未触碰 runs/stats/policy.json/lessons.md/
  review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为宿主
  挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 620~636 局批复盘：SLEEP_GUARD 只管出牌通道——伤害药水提前唤醒沉睡 Boss（POTION_SLEEP_GUARD）

日期：2026-09-11

## HYPOTHESIS / EVIDENCE / EXPECTED_SIGNAL

- **HYPOTHESIS**：沉睡保期教义（SLEEP_GUARD，1280~1284 批）只接管出牌评分通道，
  伤害药水通道（_maybe_potion 的 is_damage 分支）零防护——原生
  AsleepPower.AfterDamageReceived 以 UnblockedDamage≠0 唤醒且来源不限，一瓶
  攻击药水即可在 T1 把沉睡 Boss 提前唤醒，随后整场守卫因对象消失而永久失效。
  补上同口径药水闸（沉睡≥sleep_guard_min_stacks、未格挡伤害、非击杀时跳过且
  不计 tried），沉睡窗口即可跨通道保留。可证伪：未来 3~10 局若遭遇沉睡 Boss
  且手持伤害药水的对局从不出现 POTION_SLEEP_GUARD 留痕（条件不可达/接线错），
  或留痕出现但自然苏醒后同一瓶不再兑现（tried 误标），或族母战 T2/T3 战损较
  本批恶化（假设方向错），则本假设不成立。
- **EVIDENCE**：620 局 F17（乐加维林族母）T1 逐 tick 复核——02:50:27 先掷攻击
  药水【药水形状的石头】（target_index=0），下一 tick（02:50:28）敌能力快照
  「乐加维林族母[无能力]」（ENEMY_POWERS_SNAPSHOT_OBS）证明 ASLEEP/PLATING 已
  被唤醒流程移除，T2 意图升级+19 触发 HARD_INTENT_SPIKE_FIRE；该场此后
  SLEEP_GUARD 零留痕（守卫对象已消失）。对照 632 局同 Boss（F17，84/84 入场）：
  非伤害药水开局、快照 [PLATING_POWER×12,ASLEEP_POWER×3] 证明生产载荷可读，
  T1 收尾 tick（05:40:08）守卫正常拦下闭域投影/绯色面积/递推星芒 3 张攻击——
  560~576 批遗留的「载荷缺口 vs 逻辑缺口」就此结案：载荷在产、卡牌侧在产，
  泄漏通道是伤害药水。634 局 F17 同型遭遇快照同口径可读。另核 632 局 T1
  05:40:07 弦光投影 12 伤穿透未拦但 PLATING×12 全吸收（UnblockedDamage=0，
  次 tick 守卫对余牌照常生效证明未唤醒）——结果无害；守卫「未格挡」判定只看
  block 不看 plating 的口径余量登记为后续观察点，本批不动。本批 17 局其余
  死因主轴（謦欬自损 18%~43%、竞速判死后 4 场惨胜）全部落在既有旋钮封账与
  既有教义覆盖范围内，不重开。
- **EXPECTED_SIGNAL**：未来 3~10 局——① 遭遇沉睡 Boss 且手持伤害药水的对局
  决策链出现「沉睡保期药水闸…（POTION_SLEEP_GUARD）」skip 候选留痕，伤害
  药水在自然苏醒前保留在手；② 沉睡 Boss 战不再出现「伤害药水使用后快照转
  无能力」的提前唤醒形态；③ 自然苏醒/护甲打穿后同一瓶伤害药水正常兑现
  （不计 tried 语义）。证伪/撤回：留痕从不显形而提前唤醒仍发生 → 复查
  is_damage/目标解析接线；沉睡1层（回合末自然苏醒）被误拦 → 复查
  sleep_guard_min_stacks 读取；族母战 T2/T3 战损较 620（T2 意图19）显著恶化
  → policy.json 置 potion_sleep_guard=false 一键回滚（旧行为零差异）。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：_maybe_potion 新增沉睡保期药水闸——is_damage
  药水（单体目标/AOE「所有」语义）将对沉睡计数≥sleep_guard_min_stacks 的敌人
  造成未格挡伤害（药水伤害>目标 block）且不击杀（<目标当前 HP）时，跳过且
  不计 tried，候选以 status=skipped 留痕（POTION_SLEEP_GUARD）；可击杀、全
  格挡、描述无伤害数字、键=False 四种情形严格回落旧口径；buff/防御/无法分类
  药水与既有自伤门/Boss 前夜预留/兜底通道全部不变。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键
  potion_sleep_guard: True，注释记录 620/632/634 局实证与回滚口径。
- sts2-ascend/brain/selfcheck.py：新增 3sg2 六分支——① 沉睡3层+未格挡24伤+
  非击杀不用药且留痕、自然苏醒后同一瓶仍可兑现（不计 tried）；② 可击杀放行；
  ③ 全格挡放行；④ 沉睡1层放行；⑤ 键=False 严格回滚且零留痕；⑥ AOE 伤害
  药水同口径拦截。
- 不改 SLEEP_GUARD 卡牌侧口径、自伤药水门、进攻药预留窗、竞速/謦欬任何旋钮；
  不动 runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（新增 3sg2 六分支；
  既有 3sg①~⑦ 沉睡守卫族、3ps 快照观测、3k3/3k4 药水门族、3prz 零压闸族、
  3kd、3br 等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py
  （+55，药水闸+留痕）、brain/knowledge.py（+11 一个静态键及注释）、
  brain/selfcheck.py（+79，3sg2 六分支）；未触碰 runs/stats/policy.json/
  lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除
  告警为宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。

# 第 637~656 局批复盘：激怒零感知——技能牌喂 Boss 力量滚雪球（ENRAGE_SKILL_TAX）

日期：2026-09-11

## HYPOTHESIS / EVIDENCE / EXPECTED_SIGNAL

- **HYPOTHESIS**：原生 EnragePower.AfterCardPlayed 在玩家打出 Skill 牌时给持有者
  +Amount 力量（mechanics/powers.jsonl 实证，仅 CardType.Skill 触发），而 Brain
  出牌评分对 ENRAGE_POWER 零感知（改动前全 brain 检索零命中）。白绮謦欬卡组大量
  Skill 型功能牌（公理护环/启发式护盾/局部同胚/星图检索/不变量/闭域映射）在激怒
  战中每回合喂 Boss 3~5 张 = +6~10 力量/回合，力量复利滚进未来每一刀意图。按
  「激怒层数×计价系数」对技能牌扣分（激怒技能税），可把边际 0 费增益/抽牌压到
  阈值下、给意图增速刹车，同时保留大额格挡与斩杀（格挡买的是当前意图，税的是
  未来回合的力量复利）。可证伪：未来 3~10 局若激怒敌人（实验体/外骨骼/女王/
  假商人）战斗决策链从不出现 ENRAGE_SKILL_TAX 注记（接线或载荷不可读），或注记
  显形但激怒战意图增速不放缓、656 同型败局（T8 判死→T11 阵亡）原样重现，或
  必要格挡被误压导致低甲吃刀，则本假设不成立。
- **EVIDENCE**：656 局（02YF1HWCMUP3，F48 实验体 #C24 阵亡）全链逐条核对——
  首 tick 快照「实验体 #C24[ADAPTABLE_POWER×1,ENRAGE_POWER×2]」
  （ENEMY_POWERS_SNAPSHOT_OBS）载荷可读；T1 打 3 张技能（不变量+公理护环×2）
  意图 20→26→30、T3~T6 每回合 1~4 张技能意图 30→40→50→60→70（≈5 技能×2 力量
  /回合），T9 起「斩杀竞速投影：击杀还需8回合>可存活0回合」全攻仍追不上，T11
  1 血吃意图 36 阵亡（竞速审计：T8判死→实战11回合阵亡）。同 Boss 同快照同结局：
  592 局 F48（#C21，掉血85 阵亡）、630 局 F48（#C22，掉血111｜自损83 阵亡）——
  3 个独立对局达 evidence_run_threshold。对照无激怒回合：重生间隙（T2/T7）意图
  归零、战损立停，坐实滚雪球来自力量复利而非固定脚本。原生机制核对
  （v0.111.0 mechanics/powers.jsonl）：ENRAGE_POWER「每当你打出一张技能牌时，
  获得{Amount}点力量」，StackType=Counter、Buff。
- **EXPECTED_SIGNAL**：未来 3~10 局——① 激怒敌人战斗决策链出现「激怒技能税：
  技能牌喂敌+N力量（-X.X，ENRAGE_SKILL_TAX）」注记；② 激怒战中 0 费/低值技能
  （公理护环类面板 +3.75 级）让位于攻击或结束回合，每回合技能出牌数下降；③
  激怒战意图逐回合增速低于「技能数×Amount」的旧 1:1 口径，实验体战回合数/战损
  改善。证伪/撤回：注记零显形而激怒遭遇仍在 → 复查 powers 载荷与类型双通道接线；
  大额格挡（+20 级）被误压、低甲吃刀形态出现 → policy.json 置 enrage_skill_tax=0
  一键回滚（旧行为零差异，改动集中于评分加分项与注记，无阈值/公式重写）。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：_combat 出牌循环前一次性汇总存活敌人激怒层数
  （_enemy_power_stack 复用力量/滑溜/沉睡同构读取，id/power_id/name 中英文兼容）；
  循环内每张候选在角色估价后计价激怒技能税——技能类型判定复用零压闸同型双通道
  （白绮策略目录 card_type=="skill" 优先，目录外取载荷观测 card_type；两条都缺时
  保守按非技能，宁可漏税不误伤），技能牌 score -= 层数×enrage_skill_tax 并追加
  注记；攻击/能力牌（原生不触发激怒）严格零差异，馀量门/复打税/竞速/沉睡守卫/
  零压闸等全部既有体系不动。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 enrage_skill_tax: 2.0，
  注释记录 656/592/630 局实证与回滚口径（0 = 关闭，严格回滚旧口径）。
- sts2-ascend/brain/selfcheck.py：新增 3et 五分支——① 激怒×2 在场大额格挡技能
  照过阈值且带税注记、无激怒同牌同动作零注记；② 攻击牌激怒在场零注记；③ 双
  激怒敌人（合计4层）边际 0 费抽牌技能被税压到阈值下改结束回合、无激怒照打；
  ④ 键=0 严格回滚（激怒在场边际技能照打且零注记）；⑤ 能力牌激怒在场照打且
  零注记（原生仅 Skill 触发）。
- 不改机制税分极值、激怒层数读取语义、_score_play 任何分支公式；不动
  runs/stats/policy.json/lessons.md/review_queue 等只读在线状态。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（新增 3et 五分支；既有
  3sg/3sg2 沉睡守卫族、3ps 快照观测、3k3/3k4 药水门族、3prz 零压闸族、3kd、
  3br 等全部既有夹具通过）。
- py -3 -B -m unittest sts2-ascend.tests.test_character_strategy：57 tests OK。
- git diff --check -- sts2-ascend/ 通过；完整 diff 已回读：brain/policy.py
  （+38，循环前层数汇总+循环内计价留痕）、brain/knowledge.py（+9 一个静态键及
  注释）、brain/selfcheck.py（+102，3et 五分支）；未触碰 runs/stats/policy.json/
  lessons.md/review_queue 等只读在线状态；克隆残留的 assets 超长路径删除告警为
  宿主挂载遗留，与本批无关、不入 commit。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。
