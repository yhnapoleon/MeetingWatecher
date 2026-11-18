# 新增72例采集、标注与任务评测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Keep original runs intact.

**Goal:** 交付12例标注试验和60例正式测试，正式集40例自然会议、20例成对控制，以任务P/R/F1评测冻结context-v5。

**Architecture:** 本地新增数据与实验脚本，复用现有Service评测入口；标签与生成输入隔离，预测前冻结。分来源记录原文、许可、处理和证据，预测后逐项匹配，不修改标签追分。

**Tech Stack:** Python、JSON/JSONL、现有SQLite Simulator。

**Spec:** `docs/generalization-dataset-protocol.md`；用户2026-11-17授权定规模、采集标注并测试。

## Global Constraints

- 12例标注试验不进入正式60例成绩；正式40自然＋20控制，中文24、英文16自然会议，至少30场不同会议。
- 只运行新增正式60例一轮；12例用作标注与离线入口验证，不另做无必要模型消耗。现有115例不重跑。
- 不改生产算法、提示、推理配置、旧标签；保留所有失败和用量。
- 按原会议/系列隔离试验与正式集；自建控制不伪装真实会议。
- 标注由助手完成并自查，披露非双人独立人工盲标；正式测试前可由执行技能要求的独立审阅核对数据/代码。
- 当前无Git；使用独立data/generalization-v1、experiments/generalization-v1、runs新目录及哈希保留证据，不执行Git专用步骤或删除工作记录。

## Review Focus

- 同源切片跨集：检查源meeting/series与现有数据、试验/正式集交集为空。
- 截断后续答复：自然输入截至原会议结束的连续后缀，起点对齐原话题；保存完整原件供核对。
- 标签泄漏：runner只从input字段构建meeting，不向模型传gold或摘要。
- 重复任务匹配：记录输出位置、record_id及gold ID，去重且一对一；合并/拆分记录等价匹配组。
- 技术partial被排除：所有预定例进入分母，失去的任务计FN；真实工作卡和items分别报告。

### Task 1: 采集与采样

**Files:** `data/generalization-v1/raw/`, `experiments/generalization-v1/build_dataset.py`, `data/generalization-v1/provenance.json`.
**Interfaces:** 输出原始文件、来源哈希和72例输入；消费旧source-groups及所有既有输入的来源索引。
- [x] 验证已有来源与许可；中文使用VCSum新会议、英文使用QMSum Academic/Committee，避开AMI重叠。
- [x] 固定候选排序种子、源分组与连续话题后缀，生成40自然正式例、12试验例及20控制例。
- [x] 核对数量、来源隔离、原文逐段还原和长度测量；不因模型输出换样例。

### Task 2: 标注与冻结

**Files:** `data/generalization-v1/labels.json`, `annotation-guide.md`, `freeze.json`.
**Interfaces:** 每例tasks(required/optional)、字段、证据、负例依据与禁止误提取；正式60例gold在模型前写入哈希。
- [x] 先读12例试验并落实标注边界，再逐例标注60例。
- [x] 对易漏任务和非任务段落复读；保存不确定解释及允许拆并，不看模型输出改标签。
- [x] 检查证据存在、负责人来源、时间未伪造、旧任务更新与新工作分离，冻结数据/生产哈希。

### Task 3: 入口与一轮测试

**Files:** `experiments/generalization-v1/run.py`, `validate.py`, `runs/<new-generalization>/`.
**Interfaces:** 复用run_full_context_v5.one与run_system_validation.accounting；输出每例result/tasks/assessment及progress。
- [x] 离线检查输入与gold隔离、60例准确调度、禁止复用旧run覆盖、来源/证据约束。
- [x] fresh reviewer审阅新增数据/脚本及冻结过程，重要问题预测前修正。
- [x] 使用既有推理预算4 worker执行正式60例一次，逐例保留原始失败，不人工补跑。

### Task 4: 任务级复核及报告

**Files:** `runs/<new-generalization>/task-matches.json`, `docs/generalization-v1-results.md`, `docs/HANDOVER.md`.
**Interfaces:** 消费冻结gold与新预测；输出匹配与P/R/F1、字段、items-only、控制整对、耗时用量及失败分析。
- [x] 全部60例逐目标匹配；有含义疑点的输出回查原文，技术未完成样例不剔除。
- [x] 自然/控制、语言/来源/长度分层，会议组重采样区间；小分母明确标注。
- [x] 哈希、数量、引用链接和用量核对后更新交接，保留原115例基线。

## 执行记录

- 已确定72例规模；按用户直接执行授权，不再追加计划审批。
- AliMeeting官方入口为3.42GB至73.24GB音频包；本批用已有公开VCSum完整原文中的新会议替代中文来源。仍为24中文＋16英文自然测试，限制是中文并非全新语料库。

- Ruling: 自然片段合计长度显著高于预估，采用52例完整上下文独立提示预标注＋执行助手证据/边界复核；pilot仍不跑被测Service。标注调用单独计量。代价是同服务模型可能与被测模型共享盲点，报告不得称为独立人工金标。
- Ruling: 话题完整性优先于预定长度配额，保留已采样输入，按实测长度报告；不通过截断答复凑比例。

- Task 1 complete: 52自然+20控制已采集；源会议52场互异、原文后缀逐段还原、旧样本排除；来源许可见data/generalization-v1/sources-and-rights.md。
- Task 2 complete: 72标签，正式95 required+9 optional；完整原文模型辅助预标注54次（52成功+2预算耗尽恢复），1,116,041已知token。执行助手修正明确工作漏标、范围推断及重复，原始预标注保留；不是全量独立人工盲标。
- Final review: fresh-context reviewer /root/review_generalization_freeze，只读抽查；确认61生产文件哈希不变。四项Important均修正：原子目标各计FP/字段；GC02a/GN33漏标与时序；失败调用记账；执行依赖和模型身份冻结/快照。
- Final: fixed 原子目标吞FP和整条字段扣分 — test_extra_goal_in_matching_output_is_false_positive、test_fields_checked_per_atomic_goal_and_optional_neutral RED→GREEN；optional额外FP与重复匹配亦覆盖。
- Final: fixed GC02a主持核实回复、GN33发信任务 — test_scope_reply_and_transcript_send_references_present RED→GREEN。
- Final: fixed 失败调用记账和冻结依赖拒绝 — 对应两项test_contract测试 RED→GREEN。
- Final: Ruling: 审阅并非52份逐词人工双盲，报告明确辅助标注局限；公共语料预训练未知，只声明项目未见。预测质量及实际成本以接下来的正式日志为准。仅本地评测，不公共再分发，不加跨任意输出目录全局锁。
- Final: Ruling: 来源文件哈希验证并入冻结前检查，提升为可复现证据完整性要求；无必需任务样例的报告命名保持准确，不称严格零任务。
- Task 3 in progress: 新增一轮60例、4 worker、context-v5及原推理配置；无外层重跑。

- Task 3 complete: 60例一次调度结束，614调用、18,873,529 token、3750.465秒。45 processed、15 partial；14跟踪耗尽与1纪要核验partial分开记账。旧115例未重跑。
- Task 4 complete: task-matches.json覆盖60例、目标一对一，输出task-metrics.json及task-review.md。自然11TP/11FP/68FN；控制16TP/0FP/0FN。4处参考边界和1处合并匹配另做敏感性分析，未改冻结标签。
- Final verification: 冻结哈希/模型身份/源文件还原再次验证；15份新增冻结快照内容一致，61生产文件未变；60result哈希及独立任务计数相符；614条测试和54条标注metadata逐文件核对用量一致。完整证据见runs/2026-11-17-generalization-v1/final-verification.json。
- Handoff: 主报告、数据入口、协议状态、交接均更新。方案未通过新自然会议普适性验证；后续修复建议留在报告，本轮不修改生产实现或补跑追分。当前无Git，按既定ruling保留工作目录及所有失败记录，不执行Git合并/清理流程。
