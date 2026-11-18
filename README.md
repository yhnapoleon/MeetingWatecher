# 飞书会议行动项与决策追踪

当前代码：**context-v5 v19 + 决策核验 v2，准备本地 demo**。代码默认策略仍为 `split-v3`，运行当前链路需显式选择配置。项目使用 Python 3.11+ 标准库，任务与决定保存到本地 SQLite/模拟器，真实飞书联调待完成。

[当前交接与 demo 待办](docs/HANDOVER.md) · [克隆、配置及复现范围](docs/GitHub同步与复现范围.md) · [最新两场测试与语义复核](docs/新会议双场泛化测试_语义复核_v19.md)

源码、提示词、测试、文档与两场精简评测证据已纳入版本控制；历史模型响应、数据库、原始大语料及凭据留在本地。以下历史说明保留版本演进，当前运行入口以以上链接为准。

## 历史版本记录与原始说明

离线 MVP · 默认 split-v3 / 实验策略 evidence-v1、context-v1、context-v2、context-v3、context-v4 · 2026-11-16

团队成员在例会开始前看到自己有权查看的未完成事项，能沿着任务找到当时的承诺。会上有人汇报进度，会后更新到同一条任务。成员问起某次决策时，能看到当时采用的方案、后来的修改和每次修改的出处。

**离线闭环已可运行。** CLI 接收会议逐字稿，真实调用模型生成带引用的纪要，在 SQLite 中保存任务写入意图、模拟平台任务和决策版本。会前按查看人查询未完成项，次场会议可完成原任务并替代旧决定。真实飞书读写作为单独的集成验收。

**最新进度：context-v4 归档为失败实验。** 同一冻结上游八例各三轮，来源语义通过数为仅补提示 A 18/24、结构版 B 17/24、加 QA 的 C 14/24；C23 原例均未修复。198 项程序测试通过，但没有产品效果收益，默认仍为 split-v3。M2 目标契约四次通过，补查 M1 解释争议后完整回放只有 2/4 无残留；与旧版本成绩比较前需统一验收口径。当前最好方案、失败经验和后续接手步骤见[交接](docs/HANDOVER.md)，完整证据见[v4 报告](docs/context-v4-results.md)。

**上一轮：context-v3 已完成方案实施与定向检验。** C19、HT04、CP01 各两轮通过，C23 的必要联系目的仍遗漏；14 例两轮来源复核为 24/28。完整跨会和明确落实正例各两轮按当时契约首次通过，184 项程序测试通过，但隔离 M2 和同段工作保护例仍有残留，候选版本未晋级全量。详见[v3 报告](docs/context-v3-results.md)。

**此前阶段：context-v2 修复方案已实施。** 原始跨会 M2、明确落实正例各两轮首次通过，33 个对照和 171 项程序测试通过。扩大回归一次恢复后 52/54 可正常处理，但 C19/HT04 仍有协议错误、C23 行动目的缺失、CP01 额外背景待审项未解决；审计口径完全正确召回为 16/18，未达到全量切换门槛，默认保持 split-v3。实现、首次/恢复结果及成本见[本轮报告](docs/context-v2-results.md)与[交接](docs/HANDOVER.md)。

**此前阶段：context-v1 协议6已完成完整复测。** 30段真实语料生成24项任务或候选，审计口径17项正确、7项多余，准确率70.8%、召回率94.4%；误报集中在决策、现场活动、转述等任务边界。上下文/取消10场景、旧任务更新13契约及123项程序测试通过。两套标注评分、跨会额外候选和下一步见[完整报告](docs/full-validation-results.md)与[交接](docs/HANDOVER.md)；[上一轮定向修复](docs/pragmatic-checking-results.md)保留前后对照。

当前默认把行动项、事实与未决问题、产品决定分开提取，有授权旧任务时再提取更新，最后由程序汇总。此前 split-v3 开发集三轮锚点 F1 平均 76.1%，仍有文稿误报、跨句分工漏项；保留集 6 条待办全部找到，但承接和负责人字段并非全对。详见 [上一轮修复结果](docs/extraction-repair-results.md)。

后续 52 次诊断调用确认了片段上下文、跨句承接判断和内容核验的缺口。旧锚点 F1 不检查任务描述是否有依据，部分错误合并也会让分数上升，因此上述分数只表示该锚点评分结果。实验、论文与开源方案、架构建议见 [行动项系统溯因](docs/action-architecture-diagnosis.md)。

**证据流程已实现为可选策略。** 新增语义复核评分、分阶段推理配置、工作事件与原文证据、核验后统一生成新建/更新提议，以及逐步骤失败恢复。69 项自动测试通过，最终 evidence-v1 三次独立 M1/M2 回放各为 12/12。六个难例三轮中，直接推理的内容 F1 均值为 47.9%，新流程首次结果为 70.9%，一次失败核验恢复后为 75.2%；完全正确召回只从 50.0% 升至 55.6%，任务 token 约为 3.75 倍。C03/C09 仍有遗漏，未扩大到新盲测，默认保持 split-v3。口径、原件和成本见 [实施与验证结果](docs/action-evidence-results.md)。

**上下文与待确认需求已实现为实验策略 `context-v1`。** 每 8 段保存实体和需求线索，后文可补充、纠正或撤回；会后可查看隐式/模糊需求，由有权用户明确内容和负责人后加入任务。该轮 94 项自动测试通过，但六个难例三轮内容 F1 为 71.1%、完全正确召回 50.0%，低于上一版 75.2%/55.6%，任务 token 增加约 62%；因此不切默认。中文合成检验在一次结构失败恢复后任务命中 6/6，但取消后残留追问、实体账本漏存仍未解决。见 [本轮调研与验证](docs/action-context-results.md)、[人工确认用法](docs/context-workflow.md)和[当前交接](docs/HANDOVER.md)。

**前置能力修复已完成第一批。** 工作边界、核验字段缺口、已回答问题关闭已接入；该阶段101项测试通过。完整分工窗口能保留UI工作并只问承接，取消后旧问题、约束误拆与纯实体漏存有所改善。最终提示在冻结上游局部对照中，六例内容F1为72.7%、完全正确召回4/6；短片段UI、研究目的确认及结构失败仍未解决；该阶段跨会回放首次及一次恢复后均11/12，旧任务更新被截止时间证据校验阻断，默认不切换。该对照不算新增独立轮，详见[本轮修复与验证](docs/action-context-prerequisites-results.md)。

**历史日期实验已完成。** 隔离候选提示明确“本次时间陈述”与“历史任务期限”的区别，定向八例首次检查从2/8到6/8，两次引用失败各恢复一次后8/8；两次独立完整回放均首次12/12。该实验阶段候选尚未合入生产提示，实际改期执行及多余确认留待下一阶段修复，详见[实验报告](docs/history-time-experiment-results.md)。

**旧任务字段更新已接入 context-v1。** 历史日期规则已合入，明确改期或取消期限可实际修改原任务，普通进度不再要求重新承接；不支持的内容修改单独显示原因。当前111项测试通过。十三例新行为契约基线3/13，初版首次11/13、一次结构恢复后12/13，最终程序复用相同响应重放13/13；最终独立跨会回放首次12/12。六难例F1仍为72.7%，市场工作和研究目的遗漏、建议误判及相对时间多问仍未解决，默认不切换。详见[本轮方案与结果](docs/task-updates-results.md)。

## 运行离线 MVP

**2026-11-15：日期缺口不再直接丢掉明确工作。** context-v1 协议5保留相对期限，承接疑点与未决定日期保留候选、限制对应操作。119项测试通过，八个中文定向场景机械检查6/8→8/8，最终独立跨会回放首次12/12。六难例内容F1升至90.9%，但完全正确召回降至50%，短回应过度保守和研究目的仍未解决；自动纠错仅做隔离实验，默认不切换。见[方案与检验结果](docs/field-preservation-results.md)。

需要 Python 3.11+，仅使用标准库。在本项目目录执行：

```powershell
python scripts/replay_mvp.py --out runs/my-replay
python -m unittest discover -s tests -v
```

第一条默认读取 `../../meeting-agent/.env`，也可用 `--env-file` 指定；配置项为 OPENAI_API_KEY、MEETING_MODEL、MEETING_API_BASE，环境变量优先。首次回放会请求模型处理 M1/M2；完整成功的相同来源版本重放使用 SQLite 中已有结果。换模型、策略、提示词或抽取版本时使用新数据库和新输出目录；程序会拒绝复用不匹配的配置。旧版没有配置记录的数据库可继续查询，新版导入请使用新目录。

运行新的实验策略及冻结语义数据：

```powershell
python scripts/replay_mvp.py --strategy evidence-v1 --inference-config experiments/action-evidence/evidence-reasoned.json --out runs/my-evidence-replay
python scripts/run_meeting_eval.py --strategy evidence-v1 --inference-config experiments/action-evidence/evidence-reasoned.json --data-dir data/action-semantics-v2/regression --cases C02 C03 C09 C20 C21 C26 --out runs/my-evidence-eval
```

`--inference-config` 按阶段配置推理模式和 token 上限；上述文件是本次调整后的实验配置，单独选择 `evidence-v1` 则使用初始预算。语义评测先生成 `semantic-review.json` 草稿，完成逐条复核后再用 `scripts/score_action_semantics.py` 计分。复现已有成绩不调用模型：`python experiments/action-evidence/summarize.py`。

输出目录包含 `state.sqlite`、`M1.md`、`M2.md`、`model/` 请求响应、`operations.jsonl`、`bindings.json`、按人回顾、决策历史和 `acceptance.json`。每次 workflow 回放使用独立 `workflow-N.sqlite`，按当次事件时序推进权限。某分支调用或校验失败时状态为 `partial`，结果中的 `_errors` 保留具体问题，`ingest` 与评测命令返回非零退出码。重跑同一命令只恢复失败分支，复用原会前快照和成功结果；重试的原始响应、用量和耗时另存，不重复执行已有意图。

同一来源须由原操作者恢复，且仍有读取原会前上下文的权限。含无效对象的分支可展示已通过校验的内容，但该分支的写操作等待恢复；新建与更新存在证据冲突时写入 `pending` 待关联。纪要中的候选和待确认不代表平台任务已经建立。

单独导入及查询：

```powershell
python -m meeting_eval --db runs/local/state.sqlite ingest examples/m1.json --actor host --observed-at 2026-11-09T10:02:00+08:00 --out runs/local
python -m meeting_eval --db runs/local/state.sqlite recap --series 登录改版 --viewer host --as-of 2026-11-16T09:59:59+08:00
python -m meeting_eval --db runs/local/state.sqlite decisions --series 登录改版 --viewer host --as-of 2026-11-16T10:02:00+08:00 --history
python -m meeting_eval --db runs/local/state.sqlite recover --actor host
```

`ingest` 返回 source_id，可用 `minutes <source_id> --viewer host` 读纪要。历史查询同时限制获知时间与生效时间，权限使用当前授权。`recover` 重新检查未确认意图，已成功操作只读回确认，待发送操作重新检查写权限。

公开开发集通过同一导入与抽取服务运行：

```powershell
python scripts/run_meeting_eval.py --out runs/my-dev-eval
python scripts/score_mvp_actions.py runs/my-dev-eval/predictions.jsonl --split dev
```

21 个 dev 片段独立处理；部分失败保留有效行动项并记录错误，完全失败才在评分适配层写为空预测，同时保留 failed 状态，不能解释成没有待办。公开人员代号不会直接写入平台；只有提供明确 account_map 的人员才能执行任务写入。示例 speaker_map 使用同名模拟账号映射。

`--strategy` 可选 `actions`（原行动项规则）、`combined`（修订合并提示）、`split`（第一版拆分）、`actions-v2` / `split-v2`（追加规则实验）、`split-v3`（默认完整版本）或 `legacy`（旧完整提示）。所有版本都经过当前导入和校验，历史旧代码结果以保存的配置及响应为准。比较三轮独立请求：

```powershell
python scripts/compare_extractors.py --out runs/my-comparison --strategies actions split-v3 --repeats 3
python scripts/analyze_extraction_runs.py runs/my-comparison --out runs/my-fields.json
```

每轮独立保存输入、答案快照、配置哈希、评分、用量与耗时。同一目录恢复不算新的一轮。保留集使用 `run_meeting_eval.py --split holdout --out runs/my-holdout`；现有 9 段已在本轮使用，后续调优应新增未见评测数据。

程序是受信任操作员运行的本地 CLI。数据库、模型请求及日志是完整审计资料，按人可见范围由查询入口控制；不要把整个运行目录当成某个查看人的分享页。来源修订保存为 `revision_pending`，自动重建任务需后续明确协调规则。模拟器 token 永久有效，真实飞书适配时需单独实现平台的窗口与调用者约束。

[修复结果与验证](docs/extraction-repair-results.md) · [初版实现记录](docs/mvp-v1-results.md) · [当前 M1 纪要](runs/2026-11-14-repair-calendar-r1/M1.md) · [当前 M2 纪要](runs/2026-11-14-repair-calendar-r1/M2.md)

| 材料 | 用途 |
| --- | --- |
| [MVP 开发交接](docs/HANDOVER.md) | 当前状态更新与最初的构建依据。已实现离线闭环，后续重点为语义质量与飞书集成。 |
| [任务与验收](docs/acceptance.md) | 字节方提出的范围、第一批交付物和逐项验收方法 |
| [技术设计稿 v0.2](docs/design.md) | 用两次例会定义预期结果，说明妙记导入、任务幂等、决策版本、按人回顾及离线评分 |
| [调研总览](docs/research.md) · [语料实查与检索实验](docs/corpus-study.md) · [技术对照](docs/methods-study.md) · [飞书接口边界](docs/platform-study.md) | 中文样本与许可、四场公开会议的可复现实验、五个难点的可选实现，以及平台约束对验收的影响 |
| [标注指南](docs/annotation.md) | 如何选样、记录证据、处理身份和时间、复核争议 |
| [MVP 数据与评分说明](data/mvp-v1/README.md) · [复核表](data/mvp-v1/review.csv) · [证据视频](data/mvp-v1/clips) | 20 场公开会议，30 个摘录，35 条事件初标。按系列分为 21 个开发片段和 9 个保留片段，另有 6 个状态与权限检查。 |
| [逐字稿抽取基线 v1](docs/baseline-v1.md) · [模型输出](runs/2026-11-14-deepseek-flash-dev-v1/predictions.jsonl) · [错例对照](runs/2026-11-14-deepseek-flash-dev-v1/comparison.csv) | deepseek-flash 完成 21 个开发片段。按核心证据严格匹配，行动项 P 69.2%、R 75.0%、F1 72.0%。参考答案使用现有初标。 |
| [首批来源与格式](data/pilot/sources.md) · [模型输入](data/pilot/input.jsonl) · [待复核标注表](data/pilot/annotations.csv) | 四个中文样本，逐段显示可用的说话人身份，另表标任务负责人和证据 |
| [首场逐字稿](examples/m1.json) · [次场会前状态](examples/before_m2.json) · [次场逐字稿](examples/m2.json) · [预期结果](examples/expected.json) | 一组设计者编写的中文连续会议。时间轴、账号和任务号均为模拟数据，供讨论口径 |

## 走读第一条链路

打开首场逐字稿，找出谁答应发失败案例、日期能精确到哪一天。打开次场会前状态，分别以研发主持人和外部协作者身份列回顾清单。最后打开次场逐字稿，核对本次完成的是哪一条旧任务，以及试点范围发生了什么变化。评测时按这三个时点分别供数，预期结果只给评分器。

已提供一个可以独立运行的**会前清单评分脚本**。在本目录执行：

```powershell
python scripts/score_recap.py examples/expected.json examples/recap_prediction.json
```

预测文件刻意包含两个错误，用于验证评分器能定位漏提醒和跨权限引用。它是手写的测试输出。首批公开语料可用证据段评行动检出、负责人、时间和新建操作，命令见 [MVP 数据与评分说明](data/mvp-v1/README.md)。完整会议抽取基线与飞书联调按任务与验收页分阶段实现。
