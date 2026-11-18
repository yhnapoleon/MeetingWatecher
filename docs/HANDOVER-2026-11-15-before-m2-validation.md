# 交接：下一轮验证跨会 M2

更新时间：2026-11-15。用户已批准方案实施和测试。本轮实现、两轮完整模型复测、独立代码审查和134项程序回归均已完成；M2等语义验收仍有残留，不能说误报全部解决。

用户最新安排：本轮先保存交接，**下一场对话从跨会M2验证开始**。C20、P07b和证据协议问题保留在后续清单，本轮不继续启动模型实验。

先读[本轮结果报告](task-boundary-results.md)和[汇总JSON](../runs/2026-11-15-task-boundary/summary.json)。实现前的交接保存为[历史版本](HANDOVER-2026-11-15-boundary-design-history.md)；原完整基线仍在 `runs/2026-11-15-full-validation`，没有覆盖。

## 下一场先做：验证 M1→M2 的可见结果

项目目录：`D:\HuaweiMoveData\Users\13736\Desktop\Remote_Intern\ByteDance\feishu-meeting-eval`。M1/M2为合成跨会场景，独立于30段真实语料；语料精确率100%不覆盖这处残留。

### 原文、预期和当前偏差

- M1中，陈可接受整理三个登录失败案例并在周五下班前发研发群；同时决定首批只向内部员工开放。
- M2.1：“上周说的三个登录失败案例，今天早上我已经发到研发群了。”应关联并完成原任务，保留原期限，不新建副本。
- M2.2：“登录改版第一批的范围今天改一下，内部员工和试点客户都开放。”当前场景标签将其作为范围决定替代；原文没有另派人改配置等落实动作。应保存新决定并替代旧决定，不额外生成范围任务或追问负责人，也不把“今天”变成任务截止日期。

当前两个运行的输出不同，需分别看：

| 运行 | 当前结果 | 验证用途 |
| --- | --- | --- |
| `cross-v2/m2-result.json` | 旧任务完成、决定替代正确；多一项范围调整candidate、一张负责人确认，期限误写2026-11-16。 | 主场景：任务和决定均由M1真实提取后传到M2。 |
| `full-v2/updates/M2/result.json` | 无额外items，但范围记录被质疑，另有同段uncovered_span，共两张不当确认。 | 对照：旧任务由fixture预置；不能用它代替完整跨会验证。 |

旧的12项跨会检查全部通过，原因是`m2_no_duplicate_task`只查持久化任务数量，额外candidate没有实际创建。必须同时检查`extraction.items`、`_task_trace.review_records`和最终纪要；只看`acceptance.json.passed`不足以验收。

### 优先阅读的证据和入口

1. [跨会附加语义审查](../runs/2026-11-15-task-boundary/cross-v2/semantic-review.json)、[跨会M2结果](../runs/2026-11-15-task-boundary/cross-v2/m2-result.json)、[用户可见纪要](../runs/2026-11-15-task-boundary/cross-v2/M2.md)。
2. 同目录的`m1-result.json`、`context-host.json`、`context-guest.json`、`decisions.json`、`operations.jsonl`和`model/`；核对历史到底传入了什么，而非根据最终纪要猜测输入。
3. [单独M2结果](../runs/2026-11-15-task-boundary/full-v2/updates/M2/result.json)：比较`repair.before`、修正结果、record checks和uncovered_spans，定位两张确认的生成路径。
4. [跨会重放入口](../scripts/replay_mvp.py)的`replay`、[实验入口](../experiments/task-boundary/run.py)；输入为[examples/m1.json](../examples/m1.json)、[examples/m2.json](../examples/m2.json)、`examples/before_m2.json`。
5. 数据流：`Service.context/process` → `Extractor.evidence_extract` → `ContextPipeline.run` → `reduce_context` → `Service.minutes`。当前任务history只投影tasks；本场decisions分支并行，未输入任务解释器。

### 已试过什么，下一步怎样验证

C1消融在`cross`与`cross-c1`之间比较：提示相同，只补入Service已授权的历史decisions。仍产生范围候选和“今天”期限，因此未接入生产。它不是`cross-v2`最终提示上的新增对照，不要混作同一轮。A/B关键样例两轮结果有波动，不能凭一次M2无items判已解决。

先读上述首次trace，明确错误首次出现于跟踪、解释还是核验，以及为何修正后仍留下重复遗漏卡；然后把M2附加语义要求纳入新实验验收。若需重现当前流程，可在项目目录运行以下命令，均调用真实模型、使用本地模拟器并创建独立目录：

```powershell
python -X utf8 experiments/task-boundary/run.py --name m2-next-cross-r1 --suite cross
python -X utf8 experiments/task-boundary/run.py --name m2-next-isolated-r1 --suite full --only M2
```

名称必须未使用；已有目录不会被覆盖。改动前保存新源码快照。后续比较固定同一输入、模型、预算和修正次数，至少保留两轮配对首次结果；结构恢复单列，不挑最好结果。先用M2和“决定后明确安排灰度配置”的正例验证，再根据改动影响扩大回归，不先重跑全部已完成基线。

若追查前序解释影响，可按[设计C3](task-boundary-design.md)比较等调用的visible/blind分类器：授权原文、名册和历史相同，仅是否看ledger/records/events不同，后续合并核验一致。该机制尚未实施，先验证收益再决定是否接入；不能把新增一次调用的全部收益归因为去除前序解释。也不能凭决策与任务共享证据直接删除任务。

### M2验收标准

- M1仅创建原有案例整理任务；M2完成同一GUID，原期限保留，重复处理和重启不增建任务。
- 新范围决定正确替代旧决定；历史查询和权限隔离继续通过。
- M2新增`items=[]`，没有针对范围决定的错误确认或重复uncovered确认，纪要仍能读到新范围。
- 加上明确落实动作的正例（如“小林今天下班前改好灰度配置并发测试”—“好”）仍保留真实任务、负责人和期限；不能因存在范围决定而吞掉工作。
- 明确区分首次、一次修正与结构恢复结果，记录真实调用/token，并重新审查新输出。其他已通过路径按实际改动选择回归。

达到上述标准才称跨会M2问题解决；若仍失败，交付具体残留及阶段证据，不用旧12项全通过替代语义结论。

## 当前结果

| 项目 | 最终结果 |
| --- | --- |
| 30段真实语料，审计标签，首次 | 17项输出全部正确，0多余任务；精确率100%、召回率94.4%、F1为97.1%，任务级29/30整段准确。 |
| C19结构恢复 | 首次重复引文缺occurrence，一次同配置恢复成功；单列后18/18正确，原17项正确工作均保留，加上C14条件候选。 |
| 确认卡 | 基线22张；最终首次13张，恢复后14张。原9张不当追问消失、C26改待采纳；C20残留1张新的不当文稿确认。 |
| 连续分工/上下文 | 连续分工3/3；10个上下文与取消场景23项标准通过。 |
| 旧任务/跨会 | 13/13旧任务契约、12/12跨会既有检查通过；附加M2零额外候选/确认检查失败。 |
| 33个成对样例与扰动 | 首次30/33；2项结构失败各恢复一次成功，剩P07b过度追问指代，32/33。 |
| 程序测试 | 134项通过。生产源码与最终模型运行source.zip一致。 |

原标签同步出分：首次完全正确14/17，P82.4% / R77.8% / F1 80.0%；恢复后15/18，均83.3%。差异仍是C09研究目标、C22/C23会后时间口径；本轮未改标签。首次与恢复成绩不可混写。

已向用户澄清：主要提升是精确率70.8%→100%，首次召回率94.4%→94.4%；一次结构恢复后才到100%召回。不要在交接后写成“精确率与首次召回率都大幅提升”。

## 已实现的机制

- `context_only`保存非任务的决定、安排、转述和会话背景；核验支持后进入纪要“会议上下文”，不生成任务或确认。分类争议仍保留，后文可转为work。
- 无可关联旧任务的completed/progress，在内容/时间/状态/关系支持且无实际缺口时进入reports，消除C17兜底确认。
- suggested保留待采纳含义；conditional仅candidate并展示条件原话。局部日期疑问不吞条件候选；缺条件引文在context解释校验处拒绝。
- 三阶段提示明确话语归属、决定与落实工作、本人接受与提议、必要缺口与可后续细化的细节。一次定向修正及权限、幂等契约继续沿用。
- context协议与验证版本为7；未新增生产模型阶段。改动在context-v1，默认策略选择未切换。

独立审查发现的两处条件候选问题已补测试修复。相关文件：`meeting_eval/context_state.py`、`context_new_work.py`、`context_pipeline.py`、`extract.py`、`service.py`、三个context提示和`tests/test_task_boundary.py`。

## 下一轮优先处理

1. **M2范围决定误当工作。** 最终 `full-v2/updates/M2` 无items但有两张错误确认；`cross-v2/m2-result.json` 多一项范围调整candidate、一张确认，并把“今天”当期限。旧任务完成、决策替代仍正确。C1只补已授权历史decisions未解决，实验保留在`cross-c1`，没有接入生产。下一步可按设计C3比较看见/不看见前序解释的边界判断，同时保留“决定后明确改配置”的正例。
2. **C20文稿确认。** 视频工作正确；附带的“这个文稿可以吧”被补成与视频一并确认。核验指出错配，修正仍未消除，R2保留泛化问题。不能全局隐藏分类争议来修分。
3. **P07b过度追问。** “小林，这个场景会后细化一下可以吗？”—“可以，我来。”已接受，却因reference缺口没有进入任务。对照真正竞争指代，完善内容充分性判断。
4. **结构输出。** 最终54例首次仅C19失败；正反例P07a缺time.change、P08b引文定位失败，均已恢复一次。下一步研究证据协议，避免放宽校验或循环抽样。CP01命名问题仍保存为背景，未展示为独立潜在需求，作为边界观察保留。

A/B两轮冻结输入结果有波动，未证明新增类型本身稳定优于纯提示A。B已在固定回归集改善结果并提供明确上下文路由，保留为当前实验实现；当前结果不是新会议泛化结论。C2/C3尚未实施。

## 结果与脚本位置

- 最终完整模型：`runs/2026-11-15-task-boundary/full-v2`；33例：`pairs-v2`；跨会：`cross-v2`。
- 恢复：`corpus-v2-recovery`（C19），`pairs-v2-recovery`（P07a/P08b）。原件不变，恢复仅单列。
- 逐条语义/确认复核：`full-v2/source-review.json`；原/审计评分：`full-v2/corpus-scores.json`；恢复：`corpus-v2-recovery/overlay-scores.json`。
- 结构与调用：各例summary.json、config.json、输入、原始模型请求/响应、SQLite、operations.jsonl和minutes.md均保留。
- 源码：实现前`before.zip`，各运行`source.zip`。无Git仓库。
- 总探索1,107条调用记录、4,247,395 tokens；最终54例+跨会+C19恢复299次、1,159,823 tokens。没有真实飞书写入。
- [根因调查](task-boundary-diagnosis.md)、[设计](task-boundary-design.md)、[执行计划](superpowers/plans/2026-11-15-task-boundary.md)提供前序依据。

复算，不调用模型：

```powershell
python -X utf8 experiments/task-boundary/assess.py full-v2 --kind corpus --annotations runs/2026-11-15-task-boundary/full-v2/source-review.json
python -X utf8 experiments/task-boundary/assess.py pairs-v2 --kind pairs
python -X utf8 experiments/task-boundary/summarize.py
python -X utf8 -m unittest discover -s tests -q
```

新模型实验用 `experiments/task-boundary/run.py --name <新目录> --suite full|pairs|cross`，成对输入与预期在`experiments/task-boundary/fixtures.json`、`expectations.json`，预期不进入模型输入。新输出必须重新审查；`freeze_review.py`中的人工判断仅对应本次输出，不能换目录套用。

可给下一场对话的指令：

> 阅读 ByteDance/feishu-meeting-eval/docs/HANDOVER.md，先验证完整M1→M2跨会流程。重点检查原任务完成、范围决定替代，以及M2多出的范围候选和确认；比较cross-v2与单独M2的首次trace，结合已失败的C1消融定位问题。保留“决定后明确安排落实工作”的正例，按交接中的附加语义标准验收，不用旧12项检查全通过代替。C20/P07b暂列后续，不重复跑已完成的全部基线。
