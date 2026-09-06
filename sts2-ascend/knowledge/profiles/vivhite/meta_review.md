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

# 第 170~186 局批复盘：余量门九局拦门 172 次自损未降、拦的全是边际带廉价牌——绝对否决退化为换序偏好（謦欬门让位）

日期：2026-09-07

## HYPOTHESIS

第 165~169 批落地的謦欬出牌余量门（VIVHITE_HP_PLAY_MARGIN_GATE）其预注册证伪条件已成立：拦门留痕 ≥3 局但致命战自损占掉血比例无变化。机制层面的归因：门的拦截带宽是「过普通阈值但未过 阈值+实付×margin」的边际带——自损主力（186 局 F17 实战 est=-24.00/实付8血 的收敛判决连打两次、est=-12/实付4血 的尺度变换与递推星芒）总分远超抬升带宽，门从未触及；被拦的全是边际带廉价牌（172 次拦门中 104 次是起手打击【弦光投影】实付2血），拦后 best 为空 → 带能空过，把生产回合变成空转回合。门的价值只在「有替代出牌时换序」，其绝对否决是纯伤害。

该假设可证伪：未来 3~10 局若决策链出现 VIVHITE_HP_PLAY_MARGIN_GATE_YIELD 留痕、但早期战（F2~F12）回合数与 IDLE_LEAK_BLK×拦门同现率不降，或致命战自损占比仍 ≥50% 且 Boss 战 ttk/race_audit 恶化，则假设不成立，policy.json 置 vivhite_hp_margin_gate_yield=0 回滚绝对否决，或按上批原预注册 vivhite_hp_cost_play_margin=0 整体回滚余量门。

## EVIDENCE

- 拦门留痕局数与频次：runs 178~186 九局分别 2/12/27/18/16/16/30/49/12 次，合计 172 次 ≥3 局阈值；被拦牌面 104/172 为弦光投影（实付2血），其余为预取未来/终止条件/递推星芒等低实付牌——没有一张是 est≤-12 的高估值自损主力。
- 致命战自损占比未降：186 局 F23 阵亡战自损37/掉血51=73%、F17 Boss 自损50/掉血47、177 局 F17 自损75/掉血38、182 局 F2 自损85/掉血69、185 局 F11 自损52/掉血0——全部 ≥50%，与门前（167~169 批 97%/98%/91%）同量级。
- 空转实证（186 局 7CCBKDSBQ9TR F2 决策链逐条核对）：02:34:53/02:34:58/02:35:02/02:35:20 连续四回合拦下弦光投影后带能空过；02:35:20 同决策残能空漏审计判定「可负担格挡【闭域映射】可抵5，扣除謦欬2后净保命3」——门把审计判定净正保命的格挡一并拦死，两条链在同一决策内结论相反。
- 高估值自损主力不受门约束（186 局 F17 决策链）：收敛判决 est=-24.00 hp-cost=8 于 02:39:58 与 02:40:49 两次打出；尺度变换 est=-12.00、递推星芒 est=-12.00 照常过门——抬升门槛 +24~+50 也拦不住总分足够高的牌。
- 双旋钮已全尽：lessons 留痕「life_cost_weight -3.00 触底且謦欬出牌余量门 3.00 顶格——双旋钮全尽，謦欬证据彻底停止吸收并留痕」，门已在其最强档位仍无效。
- failed_review_replay.requested_packages 为空，本批无重实现义务。

## PRODUCTION_CHANGE

- sts2-ascend/brain/policy.py：手牌循环后新增謦欬门让位（VIVHITE_HP_PLAY_MARGIN_GATE_YIELD）——best 为空且存在被拦候选且 vivhite_hp_margin_gate_yield 开启（默认 1）时，放行评分最高的被拦候选（其 score 本就过普通阈值）并留痕「謦欬门让位：拦下将无牌可出带能空过，放行评分最高被拦候选」；存在未过门替代出牌（best 非空）时拦下照旧（换序偏好保留）；致死回合豁免、margin=0 关闭、非白绮角色零改动均不变。_hp_gate_blocked 行扩展携带 card/target/why 供让位复原。
- sts2-ascend/brain/knowledge.py：DEFAULT_POLICY 新增静态键 vivhite_hp_margin_gate_yield=1（0=旧绝对否决口径，一键回滚）。
- sts2-ascend/brain/selfcheck.py：3prh 夹具更新并扩为五分支——margin=0 旧行为出牌不变；margin=50 单手牌被拦后让位放行且双标记留痕；yield=0 严格回滚 end_turn+拦门留痕；手牌含未过门替代牌（公理护环 life_cost=0）时门维持否决改出替代牌且无让位留痕；致死回合豁免出牌不变。

## EXPECTED_SIGNAL

未来 3~10 局：① 决策链出现 VIVHITE_HP_PLAY_MARGIN_GATE_YIELD 留痕，且「拦下…结束回合」与残能空漏审计同现率降为 0；② 早期战（F2~F12）回合数与场均掉血不升、空过能量减少；③ 有替代出牌的对局仍出现「謦欬门拒」换序留痕（门未失效）。有效信号：F17/F23 型战斗节奏加快、自损/掉血结构改善或首胜。证伪/回滚条件：让位留痕 ≥3 局但上述分布无变化，或致命战自损占比仍 ≥50% 且 race_audit 判死后胜率/ttk 恶化——policy.json 置 vivhite_hp_margin_gate_yield=0 或 vivhite_hp_cost_play_margin=0 整体撤回。

## VALIDATION

- py -3 -B sts2-ascend/brain/selfcheck.py：SELFCHECK OK（3prh 五分支，既有夹具全部通过）。
- py -3 -B sts2-ascend/tests/test_boss_race_sustain.py：2 tests OK。
- git diff --check 通过（仅宿主挂载的超长路径资产删除遗留告警，与本批无关）；完整 diff 已回读，仅 knowledge.py/policy.py/selfcheck.py 三个生产/测试文件 + 本报告与口播短评；未触碰 runs/stats/policy.json/lessons.md 等只读在线状态。

## REPLAY

本批 failed_review_replay.requested_packages 为空，无 retry_resolution 目标。
