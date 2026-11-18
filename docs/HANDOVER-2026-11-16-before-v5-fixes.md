# 交接：全量与网络恢复已完成，下一轮处理剩余缺陷

更新时间：2026-11-16。项目根目录：`D:/HuaweiMoveData/Users/13736/Desktop/Remote_Intern/ByteDance/feishu-meeting-eval`。

用户希望会议转写能生成正确的工作记录、待分配任务、待确认事项和暂缓议题，并能更新已有任务。本轮已完成可选 context-v5 的全量验证、网络失败恢复，以及剩余失败的逐例分类和溯因。**尚未实施本轮新发现的缺陷修复。** 当前默认仍为 split-v3，context-v5 可选；没有运行中的模型任务或后台测试。

用户最后要求：“写个handover，我交给下个对话处理”。下个对话可从本文的建议顺序接着设计和修复，不需要重做网络恢复或重新寻找这12次失败。

## 当前结论与阅读顺序

- 原始全量：95个场景各运行两次，共190次；按最新用户口径通过 **168/190（88.4%）**。
- 网络恢复：11次中断全部恢复，10次案例通过，r1/C17仍有语义问题；新增28次请求全部收到响应。
- 计入恢复后：**178/190（93.7%）**，两轮各89/95。它是定向恢复后的统计，不是新一轮独立测试的准确率。
- 仍失败12次，对应9个场景；另有一个已离线复现、尚未触发于这190次结果的Service集成缺陷。
- 本轮没有改生产算法或提示，没有实际飞书写入；执行行为在独立SQLite模拟器中验证。54份生产代码及提示仍与全量启动前快照逐字节一致。

优先阅读：

1. [剩余12次的分类与溯因](context-v5-remaining-failures-analysis.md)：当前主要工作依据。
2. [12份独立证据索引](../runs/2026-11-16-context-v5-failure-analysis/README.md)：每例原话、阶段链、原始请求响应及校验错误。
3. [网络恢复结果](context-v5-network-recovery-results.md)、[原始全量报告](context-v5-full-validation-results.md)：指标口径及完整验证范围。
4. 需要了解此前五项实现时，再看 [专项结果](user-solutions-results.md)、[设计依据](user-solutions-design.md)。

## 用户已经明确的产品与评审口径

这些决定沿用，不要回到旧标签：

- **M2范围调整是执行工作。** “登录改版第一批的范围今天改一下，内部员工和试点客户都开放。”保留范围调整、两个开放对象和今天；仅缺个人负责人时只问负责人，不反问已明确的工作内容或是否执行。决定和工作可以共存。
- **已决定取消功能也保留待分配任务。** 用户对P03a“今天决定取消图文电视功能。”明确回答“保留为待分配任务”。P12a“第一批范围改为员工和试点客户”按M2/P03a标准应用，但P12a不是用户逐条重新标注。P03a的“今天决定”不自动等于今天完成的截止日。
- **暂缓事项仅收集。** 明确“先放着、今天不定”的议题进入待定事项，不立即追问或建执行任务；没有日期的已承诺工作仍是工作。同会议后文明确推进可激活，跨会议自动激活未实现。
- **C23推断目的不强制写。** 联系袁校长继续沟通是核心，推断的“补问没听清内容”不作为通过门槛；原文明说补问时须保留，无关报名问题反例不能添加补问义务。
- P07a“我们可以会后细化这个场景，先作为一个建议。”没有先行场景内容，先问哪个场景有合理依据。原先两次“多余追问”扣分已撤销，作为观察项保留，不能引用中间166/190成绩。

首次自动旧规则164/190，经P03a/P12a各两轮共4次显式评分修订后168/190。修订在原全量的policy-overlay.json中，原manifest、评分与输出均保留；这是口径变化，不是模型提升。原文复核由助手完成，独立代理审查代码并抽查证据，不是独立人工真值。这批语料前期已看过，不是盲测，190也不是190个独立场景。

## 剩余12次：按前因分类

| 主类 | 次数 | 执行 |
|---|---:|---|
| 完成/进展汇报被背景分类吞掉 | 7 | r1/C17（恢复后）、r2/C17、r2/P11a、r1/HT05、r2/HT05、r1/HT06、r2/HT06 |
| 再次检查越出目标记录范围 | 1 | r1/CP02 |
| 引文被改写 | 2 | r1/PF02、r2/CP07 |
| 线程更新顺序倒退 | 1 | r2/C14 |
| 省略分工与短切片边界 | 1 | r1/C03 |

上表按主要前因互斥计数，共12次。HT06两轮同时叠加再次检查越界，因此越界机制实际出现3次，不能把重叠机制直接相加。此前报告的“6结构、6语义”按最终失败表现分组，与此处按前因分类不矛盾。

### 1. 汇报分类：已找到明确的共同错误

HT05/HT06四次初始解释都正确产生work + completed + existing。原始check_work请求中确实包含对应H-HT05/H-HT06旧任务，不是历史数据缺失。检查器认可work、owner、commitment、time、state、relation六字段全部supported，却同时把所属record判为context_only，理由是“没有新增待办/独立跟进动作”。

该内部矛盾导致正确事件被拒或在repair中删除：HT05第一轮静默丢掉第三方完成确认入口；第二轮repair坚持work，复核仍否定，输出interpretation_unresolved。HT06两轮旧任务未更新，新支付任务正确创建，随后还发生再检查越界。

C17两轮及P11a第二轮的原话仍在facts/context文字里，丢的是结构化completed/progress报告，不是所有内容丢失。追踪、解释、检查都把它们视作分发背景。程序已有reduce_untracked_report，P11a第一轮同输入确实成功保留两条状态报告，因此不是整个报告功能缺失。

需区分：无旧任务的状态报告只记录；负责人本人报告旧任务完成可更新；第三方报告应保留确认入口，不直接自动完成。已有state/relation可表达这些关系，不必先新增类别。

已确认分类错误与传播路径。提示中“无独立跟进工作”的泛化标准压过后文报告例外、错误ledger影响检查，是有输出支持的解释，尚未做提示消融，不能把某一句提示视为已证明的唯一原因。

主要代码：`meeting_eval/context_v2.py`的run/reduce_v2，`context_state.py`的record_content_supported/reduce_context，`context_new_work.py`的reduce_untracked_report；提示为track-context-context-v1.txt、interpret-work-context-v5.txt、check-work-context-v5.txt，v5追踪仍复用v1文件再追加policy-context-v5.txt。

### 2. 再检查越界：schema本身没有绑定错

r1/CP02只允许R2、返回R1+R2；r1/HT06只允许R1、返回R1+R2；r2/HT06只允许R2、返回R1+R2。多余ID全部来自只读context_records。检查目标生成正确，模型把参考记录也写入record_checks。

实际请求response_format为json_object，output_schema/output_contract在消息数据里；本次请求没有以API参数强制执行该JSON Schema，本地closed_validate才拒绝额外键。不要声称服务端已经强约束，也不要在未核实时断言该服务不支持其他方式。

仅在内存移除多余只读键，三次结构展开均通过。但HT06的repair已经把完成事件删掉，只修格式仍不能恢复旧任务更新。CP02主体任务正确，resolved→context_only的非执行类别漂移触发修正，最后增加解释失败噪音。

主要代码：`context_protocol_v5.py`的check_contract/expand_checks，`context_protocol_v4.py`的closed_validate，`context_v2.py`构造check_repair输入，`context_v5.py`设置提示与schema，`model_client.py`的response_format。

### 3. 引文及顺序：直接阻断项已离线验证

- r1/PF02：原文“今天分别安排春季展会和秋季展会的准备工作。”，模型quote为“春季展会的准备工作”，连续匹配0次。不是重复引文，补occurrence不能解决。诊断副本只换成完整原句即通过该次ledger校验。
- r2/CP07：第二窗口重抄previous，删掉旧quote中的“怎么”，却沿用start=4/end=20，共四处。前一窗口正确；内存恢复该词后ledger校验通过。让模型重写已验证历史证据是具体易错点。
- r2/C14：线程原文位置0、3、5、4倒退；内存按0、3、4、5排序后校验通过。尚未进入条件工作解释，不能归为条件语义错误。

主要代码：`task_events.py`的align_spans/validate_spans；`context_state.py`的canonical_ledger；`context_v2.py`的检查点循环。考虑稳定证据ID、程序维护历史、模型只输出增量等方案时，围绕这些已观察到的输入边界验证，不要用模糊匹配或任意排序绕过证据约束。

### 4. C03：输入与标签边界需要一并判断

短切片从“for user interface, technical functions”开始，缺少更前面的分工起点。第一轮ledger已标work，interpret改成背景，check认可；第二轮同短输入成功，完整上下文CTX两轮也成功。已确认解释不稳定和前文缺失，尚不能证明截断是唯一原因。当前冻结标签要求UI候选，失败分保留；不要把它描述成无歧义直接指令或硬编码角色补任务。

## 另一个必须修的Service集成缺陷

`meeting_eval/service.py`约第167行，独立事件免冲突策略名单只有evidence-v1/context-v1..v4，漏context-v5。同一人同一段报告旧任务完成并承诺新任务，即使提取完全正确，v5仍进入旧规则create_update_conflict，两项写入都被阻断。

已有离线正常Service.process复现：[脚本](../runs/2026-11-16-context-v5-full/review/reproduce_shared_evidence_conflict.py)、[输出](../runs/2026-11-16-context-v5-full/review/reproduce_shared_evidence_conflict.json)。同一固定正确抽取，v4旧任务done且新任务创建；v5返回processed、无提取错误，但旧任务open且无新任务。

该分支未触发于当前190次结果：HT06更早被分类错误阻断，S-same-segment的旧任务在另一段。本缺陷不算进12次，但会挡住HT06语义修复后的闭环。生产代码尚未修复。

## 建议下个对话的顺序与验收

1. **先补Service策略接入遗漏及离线写入回归。** 用现成最小复现从正常入口验证：同段独立新建和更新都实际落库，重复处理不重复写入，旧split策略的冲突保护不被随意移除。
2. **统一报告分类与record/event结论。** 用HT05、HT06、C17、P11a及成功对照HT02/P11a-r1验证。逐阶段检查，不能只加提示后凭最终任务数判成功。
3. **隔离再检查的可输出目标与只读参考。** 用CP02和HT06验证合法键、额外键及真实语义结果；保留未知身份的严格拒绝，不静默吞任意额外字段。
4. **处理证据复制和更新顺序。** 先复现PF02、CP07、C14，再选择足够小的生成/程序边界改动。修复后既要过结构校验，也要验证最终任务。
5. **单独核对C03输入/标签。** 与CTX完整分工片段比较，不将标签修改伪装成模型提升。
6. 针对性验证通过后，再在新目录跑同口径回归。继续保留M2、C23正反例、暂缓/激活、承接与日期等既有成功行为，默认切换另作决定。

这些是后续建议，本次停在证据整理与交接，没有把内存诊断改动作为生产修复。不要直接重跑失败样例直到偶然通过来替代修复验证。

## 证据目录及工具

| 目录 | 内容 |
|---|---|
| runs/2026-11-16-context-v5-full | 原全量manifest/freeze/source.zip；r1/r2首次输入输出；source-review-notes.json；policy-overlay.json；final-report.json；独立审查及Service复现 |
| runs/2026-11-16-context-v5-network-recovery | 11次恢复副本、最终报告、逐例复核、原始树哈希、verification.json；runner-incident.json记录已解决的汇总路径错误 |
| runs/2026-11-16-context-v5-failure-analysis | 12次独立副本与原来源哈希；每例diagnosis.md/json、stage-timeline.json；classification.json；semantic-boundary-evidence.json；offline-boundary-checks.json；frozen-source.zip |

分析集477份来源文件及副本已验证一致，6次离线结构边界复现完成，4份事件/记录分类矛盾已核对。分析阶段0模型请求、0生产改动。离线“定点改动后通过”只指对应结构校验，不指整个案例通过。

本轮新增或调整的均为实验工具：

- `experiments/task-boundary/run.py`的one/recover增加可选strategy参数，旧默认context-v1保留。
- `run_full_context_v5.py`、`test_full_context_v5.py`、`summarize_full_context_v5.py`。
- `recover_full_network.py`、`summarize_full_network.py`。
- `extract_remaining_failures.py`、`replay_failure_boundaries.py`。

extract_remaining_failures.py的输出目录已存在，会拒绝覆盖已完成集合。replay_failure_boundaries.py当前断言原故障可复现；生产修复后它可能不再符合旧故障断言，应另写正式回归，不修改旧证据来跑绿。Service复现脚本同样是缺陷诊断，当前断言v5被拦截。

## 测试、用量与复现注意

最后一次完整代码测试：205项项目测试通过；网络恢复后33项实验测试重新通过。此后只增加诊断工具和文档，没有改生产代码；6次离线复现及证据校验已通过。下一轮修改代码后重新执行适当测试。

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest discover -s tests
python -m unittest discover -s experiments/task-boundary -p 'test*.py'
python experiments/task-boundary/replay_failure_boundaries.py
python runs/2026-11-16-context-v5-full/review/reproduce_shared_evidence_conflict.py
```

原全量983次请求、971次收到响应、4,186,590 tokens，约33.6分钟；网络恢复新增28次请求全部收到、199,821 tokens。原全量并发4，恢复并发2；未证明并发数是网络错误根因。原全量无自动网络/格式重试，恢复是用户另行授权的单次断点续跑；原有一次语义repair仍属于算法。

全量runner仍保存启动时的P03a/P12a旧规则。**未来重新运行前，显式迁移policy-overlay.json的最新口径**，并保存新规则/源码快照；不要直接把旧自动总分作为现行得分。模型、提示或生产代码变更后不要把旧缓存拿来当新模型实验结果。旧汇总工具用于重现旧证据，避免因修改评估代码覆盖历史评分。

PowerShell环境，Python标准库、无Git。模型deepseek-flash，配置`experiments/action-context/compact-check.json`；凭据沿用项目上两级`meeting-agent/.env`，勿打印、复制到证据或提交。新试验一律用新目录/数据库，保留fixtures、旧失败、原始评分及快照。

此次重写前的交接备份：[HANDOVER-2026-11-16-before-next-chat.md](HANDOVER-2026-11-16-before-next-chat.md)。
