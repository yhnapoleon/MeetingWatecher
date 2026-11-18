# 交接：Context-v5 修复与两轮回归已完成

更新时间：2026-11-16。项目根目录：`D:/HuaweiMoveData/Users/13736/Desktop/Remote_Intern/ByteDance/feishu-meeting-eval`。

用户已授权“按计划推进”。本轮实施了 Service 接入、报告分类、检查目标隔离、原文证据与增量追踪等修复，并完成新一轮 95 场景×2 轮验证。**最终自动通过 183/190，结合原话和用户可见输出复核通过 172/190；仍失败 18 次、涉及 12 个场景。默认仍为 split-v3，context-v5 可选。** 本轮模型任务和测试均已结束。

随后按用户要求检查了这 18 次失败，新增[逐例原因分析](context-v5-final-failures-analysis.md)。离线确认：10 次错误出自独立 facts/unresolved 分支；HT04 存在删除承接缺口后保留旧问题的程序逻辑问题；C11 首检发现分类错误，但修正未改、复检反转；CP01 在前 8 段耗尽推理预算；C14 少了一个数组闭合符。本次诊断未调用模型或修改生产逻辑，原评分不变。

用户进一步要求审计标注、深挖系统原因并设计预算与失败机制，已完成[系统方案](superpowers/specs/2026-11-16-context-v5-system-remediation-design.md)、[未决标注审计](research/2026-11-16-unresolved-label-audit.md)和[预算恢复研究](research/2026-11-16-budget-recovery-research.md)。十次语义失败保留，但不是预先冻结的 unresolved 金标：C09 只关闭研究对象选择，P08b 要修主宾语而保留真实未知，P05a r1 的判断依赖“本场待解决问题”的产品范围。C11 已确认修正前后 record 完全相同，复检输入未带首检分类异议。建议统一命题/归属/最终状态核验、工作资格与异议处置；技术恢复按原因限定首发加一次，CP01 单独验证 16K→32K。**当前交付为设计，尚未实施或运行新模型实验。**

优先阅读：

1. [修复及完整结果报告](context-v5-fixes-results.md)：实现、前后对照、失败和用量。
2. [最终失败索引](../runs/2026-11-16-context-v5-fixes/full-compact-final/failure-index.json)：18 次结果路径、原因和哈希。
3. [独立语义复核](../runs/2026-11-16-context-v5-fixes/semantic-review-differences.md)：解释自动通过为何仍可能失败，并区分旧问题与本轮表现。
4. [最终代码审查](../runs/2026-11-16-context-v5-fixes/final-code-review.md)及[验证记录](../runs/2026-11-16-context-v5-fixes/verification.json)。
5. 需要追溯原缺陷时看[旧失败分析](context-v5-remaining-failures-analysis.md)与[修复前交接备份](HANDOVER-2026-11-16-before-v5-fixes.md)。

## 已实现与验证

- `meeting_eval/service.py`：context-v5 纳入独立事件策略。同段旧任务完成和独立新任务创建可同时落库；重复处理不重复写，split-v3 原保护保留。
- `meeting_eval/context_tracking_v5.py` 与独立 v5 追踪提示：模型只给增量和 Q 原文引用；程序维护旧历史、还原逐字证据、按新增段落顺序追加更新。拒绝未知证据、未来证据及旧 ID 替换。
- `meeting_eval/context_v5.py`：检查目标和只读背景分开，covered 处置保留必要参考，额外键继续严格拒绝。
- v5 提示：实际完成/进展仍是工作信息，不要求必须有新待办；不同动作分别保留状态；统一 assigned/accepted 的含义。
- `coverage_review` 统计 records 与 events 的证据引用补集；未覆盖孤立实体首次补为 entity_only。**不自动建任务，也没有证明稳定补漏**。
- 狭义处理新未来工作中 work_window + set 的矛盾：保留时间含义及证据，只把 change 规范为 keep；旧任务不适用。
- 生产改动 7 个文件；最终 56 份生产代码和提示与启动快照相同。项目测试 217 项、实验测试 35 项通过。

HT05 两轮保留第三方确认，旧任务 open；HT06 两轮旧任务 done、新支付任务创建、截止 11 月 20 日，旧期限不变。C17/P11a 两轮均分开 completed/progress，无新待办。CP02、PF02、CP07 两轮通过；C03 短片段和 CTX 完整片段本轮均通过，但此前调优中存在波动，不能据两次通过宣称完全解决省略恢复。

原 9 个缺陷场景按相同工作要求，修前（含已记录网络恢复）6/18，本轮首次执行17/18。C14 本轮第一轮因新的 JSON 语法错误失败，第二轮正确保留条件性调研；旧顺序倒退路径已由增量构造处理。

## 当前必须保留的失败

| 问题 | 次数 | 定位 |
|---|---:|---|
| 未决事项/描述偏移 | 10 | C09 两轮；P05a/P06a 两轮；P05b 第一轮；C13 第二轮；P08b 两轮。多项来自独立 facts/unresolved 分支，与正确工作输出冲突。 |
| 引用情境变成本场提议 | 2 | C24 两轮。 |
| 多余追问 | 2 | C11 第一轮产品备选方案；C20 第二轮仅提及的文稿。 |
| 旧任务确认问错 | 1 | HT04 第一轮应问匹配哪条旧任务，却问是否承接，missing_fields=[]；没有错误落库。第二轮正常。 |
| 推理耗尽导致截断 | 2 | CP01 两轮 track_context 耗尽16,384输出token；推理分别占16,384和15,922。 |
| 非法 JSON | 1 | C14 第一轮 track_context。 |

共同数据流：`meeting_eval/extract.py` 的 facts 阶段独立产生 facts/unresolved，使用 `prompts/extract-facts-context-v1.txt`；工作分支的检查不覆盖这些未决事项，`Service.minutes` 会直接展示它们。提示已经要求按最终状态处理，不能把问题简化成“缺少这句提示”。下一轮应在输出合并与核验处解决矛盾，同时保留真实尚未确定的问题。

HT04 已离线复现：ambiguous relation 没有 relation 缺口，底层先由 unknown commitment 生成承接问题，上层删除 commitment 缺口却保留该问题。C20 第二轮最早在追踪描述中预设文稿“需要处理或确认”，初始解释 R2 与检查继续沿用；并不是补入 entity_only 的彭老师记录直接变成了任务。具体路径与验证见新增原因分析。

## 评分与配置边界

最终两轮分别 85/95、87/95；83 个场景两轮通过，6 个两轮失败，6 个翻转。自动契约183/190比复核172/190多11次，是因为自动检查没有覆盖完整描述和未决问题语义。

原报告168/190首次结果、178/190网络恢复后结果仍保留。本轮发现原结果也存在此前漏记的未决事项错误，未追改旧分；**不要直接用178与172宣称整体提升或下降**。需要净提升结论，应按统一语义要求重审旧输出或建立新的未见用例。当前回归集此前已参与调优，190次不是190个独立场景，复核也不是独立人工真值。

`context-v5-reasoned-check.json` 是未采用实验配置。冻结旧上游后，开启检查思考曾补回一次 UI 工作；独立16次前置验证却仅9次通过，并有格式、截断、负责人及网络问题。因此最终使用原 `compact-check.json`，没有全局开启检查思考。受控探针、未完成轮次和其他调优结果不能并入最终190次。

P12b 的“改好灰度配置并发测试”存在两种读法。第一轮显式选择“进行并发测试”，独立复核后撤回明确错误判定，保留歧义观察、不扣分。以后评估发送测试与并发测试的区别，应新建消歧输入，不能追改本轮材料。

## 用户已确定的口径

- M2 范围调整是执行工作，保留今天、内部员工和试点客户，仅缺负责人时只问负责人。
- P03a“今天决定取消图文电视功能”保留待分配任务；今天决定不自动成为今天完成的期限。P12a 范围变更沿用该标准。
- 明确暂缓仅收集，不立即追问或创建任务；同会议后文明确推进可以激活，跨会议自动激活尚未实现。
- C23 核心是联系袁校长继续沟通；推断补问不强制，明说补问必须保留，无关报名问题不得添加补问。
- P07a 缺先行场景内容时询问哪个场景有依据，不沿用已撤销的“多余追问”扣分。

新入口 `run_context_v5_fixes.py` 已迁移原 policy-overlay；旧 `run_full_context_v5.py` 的默认 manifest 仍是历史口径，不要直接把它的旧规则当现行规则。

## 证据、用量与复现

根目录：`runs/2026-11-16-context-v5-fixes/`。

- `before-source.zip`、`before-hashes.json`：修前快照；`production-changes.json`：生产差异及哈希。
- `focused-v1..v4`：各次真实迭代。v1、v3 第二轮中止，完整首轮与未完成部分分开记录。
- `coverage-probe*`：冻结上游的受控补漏探针。
- `full-reasoned-v1`：9/16、gate_failed；未运行剩余174次。
- `full-compact-final`：最终 manifest/freeze/source.zip、r1/r2、源输出、SQLite、190条复核、final-report、failure-index、source-code-audit。
- `evaluation-tools.zip`：最终实验和汇总工具快照；`verification.json`、`total-usage.json`、`tuning-usage.json`：核验与消耗。

最终全量992次请求全部收到响应，5,206,653 tokens，28.1分钟，无重试。包括调优共有1,691份请求记录、已报告9,571,804 tokens；6个中止请求缺最终元数据，用量未知，3次网络错误在思考检查实验中。不要把已报告tokens视为完整账单。

```powershell
python -m unittest discover -s tests
python -m unittest discover -s experiments/task-boundary -p 'test*.py'
python experiments/task-boundary/summarize_context_v5_fixes.py --out runs/2026-11-16-context-v5-fixes/full-compact-final
```

新实验必须使用不存在的新输出目录，例如：
```powershell
python experiments/task-boundary/run_context_v5_fixes.py --out runs/next-context-v5-validation --workers 4 --rounds 2
```

环境为 PowerShell、Python标准库、无Git；凭据沿用上两级 `meeting-agent/.env`，勿输出或复制到证据。默认模型 deepseek-flash。旧诊断脚本的主入口可能覆盖历史证据或断言旧缺陷仍存在，不要拿它们当修复后的正式回归。

## 后续顺序

1. 处理最终 unresolved 与工作结果的冲突，覆盖真实未决和引用/已解决/回顾反例。
2. 处理 CP01 推理耗尽和 C14 格式失败；当前只有 json_object 与本地 schema 校验。官方文档有 Beta strict 工具调用能力，但本项目未接入或实测，见结果报告中的来源。
3. 修正 C24 引用范围、C11/C20 追问边界和 HT04 确认字段错配；固定失败证据，避免反复重跑直到偶然通过。
4. 继续保留默认 split-v3，若要评估切换，需另行以新的稳定结果支持。

[本轮实施计划与历史记录](superpowers/plans/2026-11-16-context-v5-fixes.md)记录了中间改动；以上最终结果优先于计划中保留的“运行中”历史条目。

