# 会议项目交接：历史日期实验支持修复方向，生产仍保留原策略

更新时间：2026-11-14。项目 `ByteDance/feishu-meeting-eval`，没有 Git，使用代码快照及输入/输出哈希追溯。默认仍为 `split-v3`，`context-v1` 是可选实验策略。

用户认可先处理工作边界、分别判断字段缺口、关闭已回答问题，再发挥持续补全作用，授权按顺序调研设计并修复。本轮已完成这些步骤与第一批修复。先读[本轮结果](action-context-prerequisites-results.md)，再看[设计](action-context-prerequisites-design.md)和[实施计划](superpowers/plans/2026-11-14-context-prerequisites.md)。此前实验归档为[上一轮交接](HANDOVER-2026-11-14-context-history.md)，更早 evidence-v1 状态见[证据流程交接](HANDOVER-2026-11-14-evidence-history.md)。

## 用户目标和实现

### 最新实验：旧日期不应阻断完成更新

用户随后授权开始实验，已完成[历史日期实验](history-time-experiment-results.md)。**本轮未修改生产源码或提示**；当前 context-v1 仍是下文 guarded 版本，默认 split-v3 不变。

原失败确定性复现：模型把旧 due_date 复制到当前事件且无当前证据，阻断整个任务分支；Service 原本只更新状态，无需重填旧期限。候选 `experiments/history-time/current-time.txt` 明确 time 只表示本次发言，历史属性继续保留。8 个定向场景基线首次2/8、候选首次6/8；HT06/HT07各恢复一次后8/8。该分数仅覆盖状态、日期、创建数及必要待处理，不代表全部语义质量。两次不复用缓存的完整M1/M2回放均首次12/12，完成后旧日期仍保留。

原失败 M2 基线复用旧响应；候选八例复用基线跟踪/事实/决策调用，属于局部对照；两次完整回放独立。实际新增68次、218,412 token。101项测试通过，生产文件与 final-guarded.zip 一致。所有运行结束。原件 `runs/2026-11-14-history-time/`，计划 `docs/superpowers/plans/2026-11-14-history-time-experiment.md`。

后续明确缺口：HT07 已识别改期但执行器不支持更新 due_date，仍显示通用确认；HT08 旧任务进度仍多问是否承接；精确引用结构失败仍存在。候选时间规则尚未合入生产提示；下一轮整合时需分别处理“没有新值，应保留旧值”与“明确修改字段，应更新或明确提示能力限制”。本轮未检验短UI或隐式研究目的的新方案。

以下是前置能力修复阶段的生产状态与实验记录，数字不与本次独立回放混用。

产品是会议逐字稿 → 纪要与行动项 → 任务 → 下次会前回顾 → 跨会决策追踪。离线 CLI、SQLite、本地任务模拟器可运行，真实飞书未验收。解释用原话、实际输出和失败位置，不靠案例 ID 硬编码，不仅增加模型步骤。用户已授权本轮实施和验证，不需要重复询问相同范围的许可。

`context-v1` 每 8 段维护实体、关系和需求线索，再全文解释、全文核验、生成任务或待确认记录。当前使用 `experiments/action-context/compact-check.json`：跟踪和解释开启推理，核验关闭推理，阶段上限均 16,384。协议版本为 3；当前核验提示内容与 `experiments/action-context/check-guarded.txt` 一致。

本轮变更：

- 跟踪/解释按动作、对象、角色、场景分工作；并列未知材料不能拖住已明确工作；必要目的/约束留在所属工作；保留明确介绍的无动作实体。
- `context_state.check_records` 的非支持判定要求具体 `issues`。仅 owner/commitment/question 问题不污染受支持内容，但仍限制写入。内容、时间、范围、旧任务关系问题继续阻断。
- 新增 `resolved` 用于会上已回答的核对/选择，`withdrawn` 表示取消。旧任务完成仍用 event completed/existing 更新。
- entity_only/withdrawn/resolved 禁止携带 event，矛盾输出明确失败，不再静默丢工作。不同记录可共享 thread/evidence。
- owner 缺口也清理已是 candidate 的未经支持归属。原 `task_events.py` 未改，默认和旧 evidence-v1 规则保留。

人工入口仍为 `requirements`、`resolve-requirement`：add_task/dismiss/ask_issuer。加入需明确内容、账号映射和权限；ask_issuer 只保存待询问，不发送消息。来源版本变化阻止旧确认；成功回执丢失只回读。未确认线索目前不跨会议继承，已建任务沿用跨会机制。用法见[说明](context-workflow.md)。

## 当前效果

- C20 视频与未知文稿分开，视频候选只问个人负责人；C21 整理意见不再被篇幅背景阻断。
- 连续分工完整窗口三轮在一次结构失败恢复后均保留三项工作，UI 为 candidate、仅问承接；最终 guarded 提示在同三份上游中维持结果，无重复遗漏卡。
- CP02 已回答页面核对关闭；CP03 取消后的旧筹备及已解决问题不再追问；CP04 两个首页保持不同任务，约束不另建工作；CP05 纯实体进入账本。
- 取消反例中，善后通知和另一场活动的同名任务均保留（其中一个首次跟踪超时，恢复一次后成功）。

| 当前 guarded 对照 | 内容 F1 | 完全正确召回 | 行为准则 |
| --- | ---: | ---: | ---: |
| 六个难例 | 72.7% | 4/6 | 15/20 |
| 连续窗口三份上游 | 各100% | 各3/3 | 各5/5 |
| 中文八例 | 90.9% | 5/6 | 20/23 |
| 两个取消反例 | 100% | 2/2 | 2/2 |

**表中 guarded 是冻结上游、只改核验提示的局部对照，不是新的独立全流程轮次。** 新目录从正常 evaluator/Service 路径运行，只复制模型调用缓存，不复制数据库；`cache-provenance.json` 记录来源。汇总已验证表中新增调用均为 check_work。六例累计任务 token 106,515，本次新增核验21,221 token；约33秒只代表新增核验，不代表完整流程性能。

上一轮六例三轮均值71.1%/50.0%，更早evidence-v1为75.2%/55.6%。不能将本轮单组局部对照直接解释为稳定超过旧方案。默认未切换。

## 尚未解决

1. C03 短片段上游仍将 UI 判成 ambiguous，没有事件。核验虽指出应恢复分工，最终仍漏 UI；完整窗口成功不能抵消它。
2. C09 仍生成“看看说明书＋无人使用背景”的 create 提议，缺少具体研究目的确认，计1个不合格创建提议；不是写入真实飞书。
3. CP06 只问是否推进减少咨询目标，再问具体做什么，未提出可选择的具体工作方向，targeted_question 不通过。
4. CP07 首次精确引文失败，恢复后跟踪成功、解释又 Wrong case_id；最终任务仍缺失。有效第8段检查点得到一条行为分，不把空输出当关闭成功。
5. 简化核验曾返回错误的 uncovered_spans 对象，并过度推断材料/邮件。最终补回Q数组和材料/通知边界后，六例结构完成；文稿核验理由仍有不一致。当前结构输出及语义分类尚不稳定。
6. 当前 guarded-replay 首次11/12，一次恢复后仍11/12。模型将历史截止日期放进当前完成事件却没有原文证据，触发 Deadline requires explicit text and evidence，旧任务完成更新未落地。新数据库的任务GUID改变，M2解释重新调用，故该回放不是只改核验的对照，也不能把失败归因于核验提示。扩大跨会实验前先明确历史字段继承及证据契约。

下一步优先研究解释已遗漏后如何按有依据的核验意见补回最小工作表示，以及如何把隐式业务目标转成具体可选方向。引用、case_id、日期错误按实际失败修，不靠无限重试。以上未实现，仍需冻结新的对照与反例。

## 验证与原件

101项测试通过，包含正常Service路径关闭记录冲突、独立相邻工作、局部疑点不写入。独立代码审查两项发现均已做失败测试→修复→全量通过；owner候选显示问题按实际影响升级处理。旧证据规则保留。简化核验 replay-final 首次12/12，当前 guarded-replay 首次及一次恢复后均11/12，程序测试通过不能替代真实回放失败。所有运行已结束，失败原件保留，详见 acceptance/final-verification 文件。

- `runs/2026-11-14-context-prerequisites/`：本轮所有原件。`boundary-r1` 为仅边界试验；`regression-r1/context-r1` 为初版；`*-final` 为简化核验全流程；**`guarded-*` 评测为当前提示局部对照，guarded-replay为部分复用上游的回放**。
- 代码快照：before、boundary-only、frozen-v1、final，当前为 **final-guarded.zip**。名称final不代表当前版本，勿混用。
- 恢复前原件在各 `first-pass/`，所有失败保留分母；成功语义未重采样。CP07不再继续重试。
- [汇总](../runs/2026-11-14-context-prerequisites/comparison-summary.json)、[测试日志](../runs/2026-11-14-context-prerequisites/final-tests.log)、[进度](../runs/2026-11-14-context-prerequisites/progress.md)。
- 原语义标签 `data/action-semantics-v2` 不变；`experiments/action-context/prerequisites-contract.json` 为15例48准则；`data/context-prerequisites-v1` 两个取消反例，输入/标签有冻结哈希。

所有标注是代理标注或复核，非人工金标准。新系列 blind 仍 not_ready；合成数据不称盲测。语义使用 `semantic-review.completed.json`，行为使用 `behavior-review.completed.json`，草稿不作评分依据。

```powershell
python experiments/action-context/summarize_prerequisites.py
python experiments/action-context/summarize.py
python experiments/action-evidence/summarize.py
python data/context-probes-v1/verify.py
python scripts/verify_action_semantics.py --data-dir data/action-semantics-v2
python -m unittest discover -s tests -v
```

修改代码、提示、模型或配置使用新输出目录。复用冻结上游进行局部试验可用 `experiments/action-context/seed_check_variant.py`，必须披露缓存来源与新增调用；不得称作新独立轮。普通恢复只针对调用/结构失败，保持原配置且保留首次输出。
