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
