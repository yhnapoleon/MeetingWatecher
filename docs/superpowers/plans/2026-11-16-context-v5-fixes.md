# Context-v5 剩余缺陷修复计划

> 执行：使用 superpowers:executing-plans，在当前会话逐项实施；各代码边界先复现失败再验证修复。

**Goal:** 正确保留工作状态报告、执行同段独立新建和更新，并消除已发现的检查身份与证据生成错误。
**Architecture:** 保留现有 record/event、单次语义 repair 和 SQLite Service。v5 独立演进提示及协议，不更改默认 split-v3，不覆盖历史评分与证据。
**Tech Stack:** Python 标准库、unittest、SQLite、deepseek-flash。
**Spec:** ../../HANDOVER.md 与 ../../context-v5-remaining-failures-analysis.md。

## 约束与检查重点

- 新实验使用独立目录、数据库和源码快照；迁移 P03a/P12a 最新评分，不修改旧 runner 的历史口径。
- 本人完成报告可更新；第三方完成报告需确认；无旧任务的完成/进展只记录。
- 保留 split 策略冲突保护、重复处理幂等、未知身份拒绝、逐字证据及历史前缀不可变。
- 保留 M2、C23 正反例、暂缓/激活、承接与日期行为；C03 不改冻结标签、不硬编码角色。
- 当前仓库无 Git，以源码快照和变更清单记录；不运行会重写旧证据的诊断脚本主入口。

## 执行任务

### 1. Service 策略接入
- [x] tests/test_context_v5_regressions.py：固定正确抽取经 Service.process，断言旧任务 done、新任务创建、重复不增加审计；split-v3 保持冲突待确认。
- [x] 运行新测试，确认 v5 因名单遗漏失败。
- [x] meeting_eval/service.py：将 context-v5 纳入已有独立事件策略。
- [x] 运行回归及项目测试。

### 2. 报告分类
- [x] prompts/track-context-context-v5.txt、interpret-work-context-v5.txt、check-work-context-v5.txt、policy-context-v5.txt：统一 work 与新待办的区别，明确状态汇报及 record/event 一致性。
- [x] 用 HT05/HT06/C17/P11a 和成功对照 HT02 验证解释、检查、归约与落库结果。提示效果必须通过新模型运行判断。

### 3. 检查范围
- [x] tests/test_context_v5_regressions.py：检查请求只读参考不携带可输出身份，目标明确；多余/未知键依旧拒绝。
- [x] meeting_eval/context_v5.py：仅 v5 请求隔离只读背景与输出目标，维持原绑定及严格校验。
- [x] CP02、HT06 完整流程验证。

### 4. 原文证据与增量历史
- [x] 复现 PF02/CP07/C14，读取当前 ledger 校验与前缀契约。
- [x] meeting_eval/context_tracking_v5.py 与 v5 追踪提示：原文证据由稳定段落编号引用，程序还原原话；模型只追加历史增量，按新增段落位置构造更新，不重排历史。
- [x] 回归覆盖未知证据、未来证据、旧 ID 改写、不同实体、合法同段独立工作；随后验证最终任务。

### 5. C03 输入边界
- [x] 对比短输入与 CTX 完整上下文；新模型结果按原标签评分，解释歧义不伪装成修复。

### 6. 回归和交接
- [x] 新增实验入口迁移 policy-overlay，完成有限定向迭代后，在冻结版本上运行全量两轮并保留失败，保存请求响应、评分和语义复核。
- [x] 运行项目与实验测试；独立代码审查；修复重要发现并验证。
- [x] 更新结果报告与 HANDOVER，区分代码验证、模型回归和未解决问题。

## 执行记录

- 2026-11-16：已读取交接、失败分析与主要代码。确认 Service 策略遗漏；旧诊断脚本会重写历史 JSON，正式回归另建文件。
- 执行决定：用户已授权按计划推进；在当前会话直接实施，不另开审批。Git 专用工作树/提交脚本不适用于此无 Git 项目，采用新目录源码快照。

- Task 1: complete — 新回归先在 v5 旧任务 open 处失败；补接入后 207 项项目测试通过，含真实 SQLite 新建、更新、重复处理及 split 冲突保护。
- Tasks 2–4: 首版实现完成，代码边界回归通过（212 项主测试、33 项既有实验测试；新增评分迁移测试单独通过）。真实模型 focused-v1 22 场景×2 轮正在运行。
- C03: 已对比原输入；短片段缺少 industrial designer 的前导分派，但保留角色切换和 Marketing 分派，仍按原冻结标签评分。

- focused-v1：完整首轮 22 次，自动检查 20/22；原话复核 19/22。CTX 将段落尾号误作 Q202；P11a 合并不同动作状态；M1 范围已定被误当新执行工作。第二轮刚启动即主动停止，未完成结果不计入首轮统计。证据见 runs/2026-11-16-context-v5-fixes/focused-v1/iteration-report.json。
- 修正：Q 引用 schema 限定当前目录枚举；分开不同动作的 completed/progress；明确公布初始范围与变更范围的边界。新增 schema 测试先失败后通过。项目 213 项、实验 34 项通过；focused-v2 两轮 44 次以并发 4 启动，不使用旧缓存或自动重试。
- 独立只读代码审查未发现需修复项，记录于 runs/2026-11-16-context-v5-fixes/code-review.md。

- focused-v2 完整两轮 43/44 自动及原话复核通过。唯一失败 r2/CTX：完整前文里 UI 只保留实体，未进入线程；解释和检查均漏掉，Q6–Q8 未被任何记录引用。新增 coverage_review 暴露未引用原文与无工作线索实体，保留语义判定及单次 repair，不自动生成任务。新增测试先因缺失该字段失败，修复后 214 项主测试、34 项实验测试通过。focused-v3 9 场景×2 轮运行中。

- focused-v3 首轮 8/9 自动通过，CTX 完整分工保留；C03 的 Marketing accepted 被检查降为 assigned。检查理由先承认 Okay 为接受，再以紧邻邮件为由降级；复核又以“assigned 只要求有分派”接受降级，暴露 check 提示与解释提示的类别定义不一致。另发现 coverage_review 仅统计 record 证据，将 event 已引用的接受回应误列为未覆盖。第二轮刚启动即停止，保留证据。
- 修正 coverage 引用集合为 records + events 六字段（扩展测试先失败后通过），统一 assigned=已分派且尚未接受、accepted=已有对应接受。项目 214/214、实验 34/34；focused-v4 9 场景×2 轮运行中。覆盖提示改动是对新发现输入错误的修复，不把模型语义错误全部归因为该输入。

- focused-v4 两轮 17/18 自动及原话复核通过；唯一 CTX 失败为 new/future_work + time.work_window + change=set 的冗余字段冲突。采用狭义归一化为 keep，仅适用于有时间文本/证据的新未来工作窗口；保留时间语义供独立核验，旧任务/其他关系不改。独立审查同意该边界，真实失败内存复现已验证。
- 新增无记录覆盖的孤立实体 entity_only 记录，不自动产生工作/问题/事件；进入已有分类检查和单次 repair。项目217项、实验34项通过。两次冻结上游的快速检查补漏探针仍未恢复 UI 分工；只开启检查思考的第三次受控探针运行中，均不计入独立全流程准确率。

- 受控补漏：coverage-probe 与 coverage-probe-v2 冻结旧上游，关闭检查思考仍将 UI 角色分工判纯实体；coverage-probe-thinking 仅将 check_work/check_repair 思考开启，成功分类纠正→repair→复核，补回 UI candidate，另两项 create 保留。该探针不计入端到端准确率，不能据单例宣称思考是所有错误的唯一原因。
- 新建 experiments/action-context/context-v5-reasoned-check.json；旧 compact-check 配置不改。实验入口增加可选配置传递及前置 gate，默认旧调用行为保留；调度测试保证全部95场景不重不漏。项目217项、实验35项通过。
- 当前运行：runs/2026-11-16-context-v5-fixes/full-reasoned-v1，session_id=52492，并发4；先 C03/CTX/C17/P11a/HT05/HT06/M2-service/positive-service 两轮16次，自动检查通过后继续其余174次。总190次均新请求、新数据库，同一源码和参数快照。模型运行期间不改生产代码。

## 最终状态

- 本轮实现、代码回归、独立审查、完整模型回归及交接均已完成；不表示所有模型缺陷已消除。
- 思考检查前置验证9/16，未采用，未执行剩余174次。最终使用compact-check完成95场景×2轮，无重试。
- 最终自动183/190，原话及用户可见输出复核172/190（85/95、87/95）；18次失败、12场景。原9个缺陷场景6/18→17/18。
- 项目217项、实验35项通过；56份生产文件匹配快照；190份输出哈希及manifest、用量核验通过。
- 默认split-v3不变。结果见docs/context-v5-fixes-results.md；后续缺口见docs/HANDOVER.md与最终failure-index.json。所有本轮任务已结束。
