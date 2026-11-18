# 会议行动项项目交接：继续优化抽取质量

更新时间：2026-11-14。项目目录：`D:\HuaweiMoveData\Users\13736\Desktop\Remote_Intern\ByteDance\feishu-meeting-eval`。

离线 MVP 和第一轮证据流程已经实现。下个对话从 **C03 的连续分工漏项、C09 的研究内容缺失及解释阶段的筛选规则** 继续优化。默认策略仍为 `split-v3`；新策略 `evidence-v1` 可以运行，但没有通过切换默认策略的质量门槛。当前没有需要继续等待的模型运行。

先读本文件，再读[实施与验证报告](action-evidence-results.md)。研究依据见[系统溯因](action-architecture-diagnosis.md)，原定边界与验收条件见[实施计划](superpowers/plans/2026-11-14-action-evidence-pipeline.md)。[旧交接](HANDOVER-2026-11-14-history.md)已归档，其中“尚未开始搭建”等说明只代表当时状态。

**用户目标与工作方式**

产品目标是“会议逐字稿 → 纪要和行动项 → 任务 → 下次会前回顾 → 跨会决策追踪”。目前重点是解决模型承担多项判断后漏项、误报增加的问题，找共同原因和可验证的架构改进。用户已授权实施、实验和核验；本轮停在交接，下一轮继续优化，无需重新询问是否开始。

解释要用具体例子说清原话、模型误解、出错位置和改动效果。不要靠个案禁令、针对案例 ID 返回结果，或单纯增加 Agent 数量解决问题。优先复用现有程序，有收益再扩展。用户此前选择用项目初标和代理复核推进，不等待新增人工确认流程，但必须如实注明标注性质。

**当前实现与验证状态**

CLI 已能导入会议、真实调用模型，在 SQLite 中保存抽取结果、任务意图和绑定；本地任务模拟器执行创建、更新与回读。会前按权限查询未完成工作，第二场会议完成同一任务并替代旧决定。真实飞书接入尚未验收。

| 部分 | 状态与入口 |
| --- | --- |
| 默认抽取 | `split-v3`：行动项、事实/未决问题、决定分开提取，有授权旧任务时提取更新；[extract.py](../meeting_eval/extract.py) |
| 证据流程 | `evidence-v1`：定位工作 → 解释工作/负责人/承接/时间/状态/旧任务关系 → 核验 → 代码生成提议；[task_pipeline.py](../meeting_eval/task_pipeline.py)、[task_events.py](../meeting_eval/task_events.py) |
| 提示 | [定位](../prompts/locate-work-v1.txt)、[解释](../prompts/interpret-work-v1.txt)、[核验](../prompts/check-work-v1.txt) |
| 推理配置 | [model_client.py](../meeting_eval/model_client.py) 支持按阶段配置；调整版用 [evidence-reasoned.json](../experiments/action-evidence/evidence-reasoned.json) |
| 写入与恢复 | [service.py](../meeting_eval/service.py)：权限、来源版本、冻结上下文、意图幂等、回执与失败恢复 |
| 语义评分 | [review_action_semantics.py](../scripts/review_action_semantics.py) 导出/校验复核；[score_action_semantics.py](../scripts/score_action_semantics.py) 计算指标 |
| 评测与回放 | [run_meeting_eval.py](../scripts/run_meeting_eval.py)、[replay_mvp.py](../scripts/replay_mvp.py)、[CLI](../meeting_eval/__main__.py) 均已接通策略和推理配置 |

上一轮最终记录：69 项自动测试通过；三个独立最终 M1/M2 回放各 12/12，首次处理成功；37 份成功任务阶段记录经最终规则重算，提议不变；18 份语义复核/分数通过验证；原先 52 次诊断仍可审计。证据见[最终核验](../runs/2026-11-14-evidence-implementation/final-verification.json)和[测试日志](../runs/2026-11-14-evidence-implementation/final-tests.log)。后续修改代码后需重新验证受影响的行为。

**效果与局限**

以下是六个既有难例 C02/C03/C09/C20/C21/C26、五个会议系列、每轮六条参考行动项的三轮均值。这是开发诊断材料，不能与完整 21 例旧锚点 F1 混比，也不代表未见会议效果。

| 方案 | 内容 F1 | 完全正确任务召回 | 含无依据陈述的预测 / 全部预测 |
| --- | ---: | ---: | ---: |
| 直接抽取，关闭推理 | 35.4% | 33.3% | 7/16 |
| 直接抽取，开启推理 | 47.9% | 50.0% | 7/23 |
| 三步流程初版 | 55.6% | 27.8% | 0/7 |
| 调整版，首次结果 | 70.9% | 50.0% | 0/13 |
| 调整版，恢复一次失败核验后 | 75.2% | 55.6% | 0/14 |

“含无依据陈述”不包括仅内容不完整、负责人或承接错误，0/14 不等于全部正确。调整版 C21 第一轮核验返回无效 JSON，恢复只重试该步骤；首次结果另存。每轮任务相关 token 平均 62,206，对照直接推理为 16,587，约 3.75 倍；六例累计处理耗时约 224.1 秒对 60.0 秒。事实和决定分支未计入此 token 比较。

直接推理上限 8,192 token；调整版解释和核验上限 16,384。扩大预算源自一次解释耗尽 8,192 token、未输出最终答案的真实失败。这是流程和预算共同变化的比较，不能把全部收益归因于架构。DeepSeek 推理模式忽略 temperature，配置中的 1 不代表已控制实际采样温度。

| 样例 | 调整版结果 | 后续要保留或解决的行为 |
| --- | --- | --- |
| C02 工作时段 | 三轮未制造交付期限 | “两会之间做设计”不等于“下次会前交付” |
| C03 连续分工 | 短片段 UI 工作 0/3；补前文后仍仅 1/3。同一完整窗口，直接推理 3/3，但有邮件误报、时间错误 | 从连续分工还原省略动作，再判断负责人是否承接 |
| C09 说明书 | 两轮仅“看说明书”；一轮被解释为 conditional，未进入任务 | 保留“用户对说明书的看法/使用问题”，稳定识别问答和短回应关系 |
| C20 视频和文稿 | 三轮只有视频剪辑与确认，没有附加文稿动作 | 不能给“还有文稿”补整理、制作或发送动作 |
| C21 整理意见 | 初版 0/3；调整版失败恢复后 3/3 | “我们会整理”是团队承诺；定位遗漏不能阻断全文理解 |
| C26 细化场景 | 三轮作为建议保留，不进入承诺任务 | “可以”且无人承接不能当作已答应工作 |

**首先查看的失败证据与待验证原因**

C03 的定位步骤已经找到 UI 原句，解释步骤却以“只有话题、没有明确动作”为由放入 `discarded_candidates`；核验没有标出遗漏。完整上下文第一、第三轮都如此。这不是简单的定位召回问题。

对照[完整上下文第一轮](../runs/2026-11-14-evidence-context/evidence-v1-r1/CTX_ES2002a_roles.json)与[第二轮](../runs/2026-11-14-evidence-context/evidence-v1-r2/CTX_ES2002a_roles.json)的 `extraction._task_trace`：看 `candidates`、`discarded_candidates`、`events`、`checked_events`、`uncovered_spans`。第一轮 facts 格式也失败，整例为 `partial`，但任务分支完成；不要把事实格式错误与 UI 语义遗漏混为一谈。

C09 找到了对象，但“说明书堆积却没人使用”的研究目的在解释时被压缩掉，核验没有判出内容不完整。看[调整版第一轮 C09](../runs/2026-11-14-evidence-refined/evidence-r1/C09.json)和[第二轮 C09](../runs/2026-11-14-evidence-refined/evidence-r2/C09.json)；后者把承接解释为 conditional，reducer 据此保留待核对。

当前解释提示要求“只写动作与对象”“只有对象无动作时解释为非明确工作”。**可能的共同原因**：这条限制在防止 C20 虚构动作的同时，也阻断了 C03 连续分工中的合理省略还原；只保留动作与对象又可能压缩 C09 的研究目的。这是待隔离实验验证的假设，不是已证明的唯一原因。

调整版核验前完整工作覆盖三轮均为 4/6，核验后仍为 4/6。另做过只开启核验推理、冻结初版提示/输入/8,192 预算的对照：16 份请求，相同请求复用后实际调用 14 次。C21 的遗漏原话三轮均被发现，但检查器不能直接生成新任务；C09 仍不完整。增加核验推理尚不是有效的召回修复。

**下轮建议顺序**

1. 从保存记录确认解释阶段的共同错误，区分“根据连续对话还原省略动作”和“凭空给孤立材料补动作”；检查工作描述是否应保留目的、范围等必要信息。先提出通用规则，再修改提示或中间表示。
2. 做变量清楚的小规模对照：保留现有三步流程；尝试“直接推理生成完整工作 → 字段核验”，或保留三步结构而只改变解释方式。继续使用现有统一新建/更新规则，不提供绕过核验的写入开关。尽量统一推理预算，差异单列。
3. 相同六例及独立 context 视图各跑三轮，复核全部预测和遗漏。核验要独立检查被删除工作的原话，不能只接受上一步的删除理由；同时守住 C20/C26 误报约束。
4. C03 完整窗口三项分工、C09 完整研究含义与承接连续三轮正确保留后，再跑原计划的完整 21 例三轮对照；冻结配置后采集、标注新系列盲测。新盲测未完成前，不宣称泛化提升或切换默认。

以上是下轮建议，尚未实现或验证。现有评分、日志、存储无需重搭。LangExtract、MiniCheck、DSPy/GEPA 及对话行动项论文的参考位置在[系统溯因](action-architecture-diagnosis.md)与[实施计划](superpowers/plans/2026-11-14-action-evidence-pipeline.md)，尚未引入这些库；是否采用应针对具体缺口设置对照。

**改动时保留的关键边界**

- 三步均读取完整授权原文；定位候选只是线索。解释可用 `candidate_ids=[]` 补出工作，程序补 ID。空候选仍需解释和检查。
- 引文必须精确匹配原文；重复出现用 occurrence 区分，代码计算位置。引用存在不等于支持整个描述。
- 时间断言被否定时，不能只清空 due 后继续写含错误期限的标题；未经支持的标题也不能当作可靠待核对标题展示。核验支持的 unspecified 时间可留空。
- 完成/重开旧任务不需要再次表达未来承诺；新建仍需支持承接。更新需要本人身份、支持的工作/状态、唯一授权旧任务关系，实际执行仍经过 Service。
- `items`、`updates` 和 `_task_trace` 一起冻结与恢复；调用/结构失败阻止该组写入，其他成功分支保留。语义疑点不能当网络错误反复重试，也不能重采样挑最好结果。
- 标签、预期答案、写权限和账号映射不进入模型语义输入。未知旧任务关系不能回退新建；共享引用不能作为合并两项工作的唯一依据。

相关回归测试：[task_events](../tests/test_task_events.py)、[task_pipeline](../tests/test_task_pipeline.py)、[inference_config](../tests/test_inference_config.py)、[action_semantics](../tests/test_action_semantics.py)，以及既有 Service、权限和入口测试。

**数据、评分与版本**

`data/action-semantics-v2/` 的 [regression](../data/action-semantics-v2/regression) 为原 21 个开发片段、12 条行动项；[context](../data/action-semantics-v2/context) 为 C02+C03 连续窗口，案例 `CTX_ES2002a_roles`，三条行动项；[blind](../data/action-semantics-v2/blind/manifest.json) 只有选样约束，状态 `not_ready`。盲测要求至少 24 个窗口、8 个新系列、中文不少于一半，排除全部既有系列。旧 9 个保留片段已参与分析，不能再称为未见数据。

标签和复核为 `agent_reviewed`，不是独立人工金标准。C03.2、C09.1 的短回应承接存在明确不确定性，主标签仍按原 create 计算。C09 的内容要求来自原始行动项标注及对话使用问题；如有依据修订，须先独立复核、新建版本，并对所有方案使用同版，不能为新结果加分而改答案。v2 把 C19“会后”、C20“后面”当未来安排，截止字段为空；旧 v1 标签不变。

语义评分只计算外部逐项复核，不能把 `check_work` 的判断当评测真值。每例（包括空输出）、每条预测均需复核参考匹配、内容依据/完整性、负责人/承接/时间/操作及理由。修改输入、预测或标签后旧复核哈希失效，必须重评。失败样例保留在召回分母，首次失败和恢复成绩分开报告。

新评测目录的 `labels.snapshot.jsonl` 已与所选案例一致。本轮旧实验生成于此修复前，重算时用另存的 `semantic-labels.snapshot.jsonl`，不要覆盖原快照。完整复核在 `semantic-review.completed.json`；`semantic-review.json` 可能仍是原始草稿。`precheck-review.json` 只审核验前内容，不参与执行。

**产物索引**

| 位置 | 内容 |
| --- | --- |
| [evidence-probes](../runs/2026-11-14-evidence-probes) | 直接抽取、直接推理、三步初版各三轮，初版两次失败保留 |
| [evidence-refined](../runs/2026-11-14-evidence-refined) | 调整版六例三轮；第一轮 `first-pass/` 是恢复前结果 |
| [evidence-context](../runs/2026-11-14-evidence-context) | 完整 C02+C03，直接推理与新流程各三轮 |
| [check-ablation](../runs/2026-11-14-evidence-check-ablation) | 仅切换核验推理模式的对照 |
| [comparison-summary.json](../runs/2026-11-14-evidence-implementation/comparison-summary.json) | 分轮/分语言语义指标、错误、候选、pending、成本与最终规则重算 |
| [旧 split-v3 语义重评](../runs/2026-11-14-evidence-implementation/old-split-v3-r1.semantic.json) | 21 例保存结果：锚点 F1 75.0%，内容 F1 66.7%；两套指标不可替代 |
| 最终回放 [r1](../runs/2026-11-14-evidence-final-v2-replay-r1/acceptance.json)、[r2](../runs/2026-11-14-evidence-final-v2-replay-r2/acceptance.json)、[r3](../runs/2026-11-14-evidence-final-v2-replay-r3/acceptance.json) | 最终代码各 12/12，目录名包含 `final-v2` |
| [progress.md](../runs/2026-11-14-evidence-implementation/progress.md) | 实施、独立审查和取舍；同目录有修改前与最终代码 zip |

`evidence-final-replay-*` 是完成汇报规则修复前的回放，含一轮 11/12；`evidence-replay-r1` 更早，不能混作最终三轮。原始模型请求、响应、用量位于各运行目录的 `model/`。

**环境与接续命令**

Windows PowerShell，本轮 Python 3.13；项目要求 Python 3.11+，运行时仅标准库。项目及上级没有 Git，同级 `meeting-agent` 是独立项目。用新运行目录、配置哈希及代码快照保留版本；改代码、提示、模型或配置后必须换数据库/输出目录，程序会拒绝混用旧状态。

模型配置从环境变量或 `../../meeting-agent/.env` 读取，变量为 `OPENAI_API_KEY`、`MEETING_MODEL`、`MEETING_API_BASE`，本轮模型为 `deepseek-flash`。不要输出或复制密钥；无需为接续重新索要凭据。

在项目目录先做不调用模型的检查：

```powershell
python -m unittest discover -s tests -v
python scripts/verify_action_semantics.py --data-dir data/action-semantics-v2
python experiments/action-evidence/summarize.py
```

`summarize.py` 会验证保存的复核、重算分数，并用**当前 reducer**核对旧提议；若下轮有意改策略而产生差异，须保存新比较和原因，不能改旧结果让断言通过。旧诊断另可运行 `python experiments/action-architecture/audit.py`。

以下新目录命令会调用模型。先复制/修改配置，再换成下一轮名称；每个重复用独立 r1/r2/r3 目录：

```powershell
python scripts/run_meeting_eval.py --strategy evidence-v1 --inference-config experiments/action-evidence/evidence-reasoned.json --data-dir data/action-semantics-v2/regression --cases C02 C03 C09 C20 C21 C26 --out runs/next-evidence-r1
python scripts/run_meeting_eval.py --strategy actions --inference-config experiments/action-evidence/thinking.json --data-dir data/action-semantics-v2/regression --cases C02 C03 C09 C20 C21 C26 --out runs/next-thinking-r1
python scripts/run_meeting_eval.py --strategy evidence-v1 --inference-config experiments/action-evidence/evidence-reasoned.json --data-dir data/action-semantics-v2/context --out runs/next-context-r1
python scripts/replay_mvp.py --strategy evidence-v1 --inference-config experiments/action-evidence/evidence-reasoned.json --out runs/next-replay-r1
```

恢复失败时保持原代码、配置和目录，重跑原命令；在已完成目录重跑不会重新采样。单独选择 `evidence-v1` 而不传配置文件会使用初始预算，不等于调整版。

评测导出复核草稿，逐项填写判断、理由、复核者及状态后，以新目录的快照评分：

```powershell
python scripts/score_action_semantics.py --predictions runs/next-evidence-r1/predictions.jsonl --labels runs/next-evidence-r1/labels.snapshot.jsonl --review runs/next-evidence-r1/semantic-review.completed.json --out runs/next-evidence-r1/semantic-scores.json
```

下轮交付要回答：C03/C09 的完整工作含义在哪一步恢复，三轮是否稳定，是否重新引入文稿/建议/期限误报，完全正确召回与可执行任务是否改善，以及多花了多少调用和 token。小样本机制通过后再扩大验证；默认切换仍需新会议上的证据。
