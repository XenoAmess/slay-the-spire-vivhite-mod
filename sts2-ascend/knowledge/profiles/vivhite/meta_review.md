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
