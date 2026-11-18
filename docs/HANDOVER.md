# 飞书会议评测交接

## 代码仓库与同步范围

GitHub：[yhnapoleon/MeetingWatecher](https://github.com/yhnapoleon/MeetingWatecher)，工作分支 `main`，本地 `origin` 指向该仓库。2026-11-18 首次同步当前源码、提示词、测试、实验脚本、文档及两场精简评测证据；凭据、数据库、原始模型响应与大语料留在本地，未删除。

克隆后的使用入口、可独立运行的测试、配置模板与历史实验依赖见 [GitHub 同步与复现范围](GitHub同步与复现范围.md)。本机下文的历史 `runs/` 路径不全部包含在 GitHub，切勿把仅保存的验收摘要当作完整运行归档。当前配置另存 [config/context-v5-v19.json](../config/context-v5-v19.json)，新机器不再依赖本机运行目录取配置。

首次发布验证：仅导出 Git 暂存文件到独立目录，核心定向测试 **56/56**、CLI帮助及两场输入/参考/规则哈希检查通过。CP02协议测试改读仓库内夹具，解决其对本地旧日志的依赖；生产代码未改。已扫描提交内容中的实际模型凭据及常见密钥格式，未发现凭据入库。后续从此目录正常提交并推送 `origin/main`；不要用整目录强制添加把被忽略的历史产物带入仓库。

## 当前接手点：转入 demo 准备（2026-11-18）

**用户最新决定：当前效果可以准备做一次 demo。下一轮先把演示主流程串起来，不默认继续加会议跑分。** 本轮已经完成两场新会议测试及主助手逐条语义复核；此轮交接只整理资料和演示入口，没有创建演示界面、启动服务或接入真实飞书。

项目路径：`D:/HuaweiMoveData/Users/13736/Desktop/Remote_Intern/ByteDance/feishu-meeting-eval`。Python 3.11+、标准库。现有交付以本地 CLI、Service、SQLite、Markdown 和 JSON 为主；仓库中尚无专用 demo 页面或一键演示入口。

### Demo 要让用户看到什么

演示主线建议是：**读一份会议逐字稿 → 查看有原文证据的任务和决定 → 处理一条待确认意向 → 在下一场会议中更新任务或决定 → 查看当前状态与历史。** 重点展示用户如何使用结果，阶段请求、token 和评测表作为追问时的补充材料。

准备一份短中文两场连续会议作为可交互主场景：人物用明确模拟账号映射，第一场包含一个明确工作、一条模糊意向和一项决定；第二场包含进度更新、重申和一项变更。可以参考现有中文对照，但需要明确标注“演示样例”。自然会议实测作为旁证保留，不把人工编写样例当泛化测试。

### 下一轮按这个顺序做

1. **整理演示输入与预期。** 先选定短中文场景，明确每一步观众应看到什么。原文、预期和演示输出分开保存；操作使用新的 `runs/demo-...` 目录或历史库的副本。
2. **做一个贯穿主线的入口。** 复用 `Service.process`、`minutes`、`requirements`、`resolve_requirement`、`recap`、`decisions`，明确构造 `Extractor(..., 'context-v5', inference_config=..., review_decisions=True)`。当前配置与下面的实测配置一致。界面形态可根据展示方式选择，尚未决定或实现。
3. **走完一次本地彩排。** 从真实模型生成结果，再演示确认及跨会查询，核对最终记录、原文、负责人、当前有效决定和历史。保留这次结果，现场可回放，明确区分“本次实时生成”和“已有运行回放”。自然整场推理单场约13–15分钟，适合提前运行；短样例耗时需实测，不能预先承诺秒级。
4. **只修复实际阻断演示的问题。** 优先检查确认入口是否能补清动作/负责人，以及同一议题在决定与未决栏是否自相矛盾。如需人工修订，保留原输出并标注修订；不要覆盖模型原件使其看起来全对。
5. **完成演示交付。** 一份简短操作说明、一条推荐启动命令、一份已跑通的演示数据和结果。展示完成标准是观众能沿主线看到任务/决定如何产生、确认和变化，而不是再增加一批评测数字。

### 可直接复用的材料

| 材料 | 在 demo 中的用途 | 当前边界 |
| --- | --- | --- |
| [TS3003b 最终纪要](../runs/2026-11-18-two-unseen-v19/TS3003b/minutes.md)、[原文](../runs/2026-11-18-two-unseen-v19/TS3003b/完整会议原文.txt)、[逐条复核](../runs/2026-11-18-two-unseen-v19/TS3003b/人工逐条复核.md) | 展示完整自然会议能提取工作、决定及原文证据；任务归属较清楚 | 未决栏有重复及状态冲突；AMI 人物没有真实飞书账号映射，只适合查看和讲解 |
| [模糊意向原始纪要](../runs/2026-11-18-unclear-intent/live/unclear/minutes.md)、[人工澄清后的保存结果](../runs/2026-11-18-unclear-intent/short-audit/clarification.json) | 说明“我之后再补一下”先澄清，明确内容与负责人后才建任务 | 此实验主要验证任务分支，不能冒充完整整场端到端 demo |
| [跨会首场](../runs/2026-11-18-cross-meeting-reaffirmation/live/initial.md)、[次场](../runs/2026-11-18-cross-meeting-reaffirmation/live/replacement.md)、[保存状态](../runs/2026-11-18-cross-meeting-reaffirmation/live/storage.json) | 会员资格重申、年费99改89；有效决定2条，历史4条，本地任务1条 | 是已验证中文机制对照；若串入新 demo，应在当前配置下重新彩排 |
| [原两场中文输入](../examples/m1.json)、[次场输入](../examples/m2.json)、[预期](../examples/expected.json) | 参考明确承接、任务更新、按人回顾的场景设计 | 属手写模拟数据，旧 replay 脚本不能直接当当前v19入口 |

### 配置和启动入口：不要误用默认策略

当前实测是 **context-v5 version 19 + DecisionReview version 2**，模型为 `deepseek-flash`。沿用[完整会议推理配置](../runs/2026-11-18-two-unseen-v19/TS3003b/inference.json)：跟踪和任务核验 high/16384，解释 low/32768，长度失败按现有机制恢复。完整配置及提示哈希在同目录 `config.json`。

- [完整会议入口](../experiments/full-meeting/run.py)支持 `--live --review-decisions`；要求目录中已有 `input.json`、`inference.json`，且不存在 `state.sqlite`。真实运行调用模型，必须用新目录。
- [通用 CLI](../meeting_eval/__main__.py)可查询和确认已有记录，但当前 `ingest` **没有** `--review-decisions`，不能直接得到本轮同配置的决策核验链路。代码默认策略仍为 `split-v3`。
- [旧 replay_mvp.py](../scripts/replay_mvp.py)的参数选项尚未包含 `context-v5`，内部也没开启决策核验。下一轮应复用其中 Service 编排，而不是把旧命令当已就绪的新 demo。
- 模型配置入口为项目上两级 `meeting-agent/.env`；只沿用读取，不在文档、演示页面或打包文件中输出凭据。
- 当前任务写入本地模拟器。真实飞书账号映射、凭据、文档/任务写入和端到端联调尚未完成。本次 demo 默认讲清本地闭环；若转做真实飞书演示，需作为独立联调步骤准备。

以下命令已可复查保存的实测结果，不调用模型，也不会创建演示业务任务。在项目根目录运行：

```powershell
$env:PYTHONUTF8='1'
python experiments/full-meeting/audit_unseen.py runs/2026-11-18-two-unseen-v19/IS1000a
python experiments/full-meeting/audit_unseen.py runs/2026-11-18-two-unseen-v19/TS3003b
python experiments/full-meeting/summarize_two_unseen.py
```

查看已保存自然会议的纪要和确认卡，使用结果里的真实 `source_id`：

```powershell
$meetingRun = 'runs/2026-11-18-two-unseen-v19/TS3003b'
$meetingResult = Get-Content -LiteralPath "$meetingRun/result.json" -Raw -Encoding UTF8 | ConvertFrom-Json
python -m meeting_eval --db "$meetingRun/state.sqlite" minutes $meetingResult.source_id --viewer evaluator
python -m meeting_eval --db "$meetingRun/state.sqlite" requirements $meetingResult.source_id --viewer evaluator
```

以上是读取。演示人工确认时必须改用新演示库/副本，并使用该来源真实有效的账号映射，不能把 AMI 人物代号直接当飞书用户。确认 API 为 `Service.resolve_requirement`；CLI 为 `resolve-requirement <source_id> <record_id> --actor ... --input ...`。普通候选使用 `add_task`，待采纳方案使用 `adopt_and_add_task`，待澄清意向使用 `clarify_and_add_task`；需最终 `description`、`owner_ref`。同一记录重复确认的幂等机制已有验证。[确认行为与例子](模糊意向分类_实施与验证.md)

### 当前质量判断与 demo 注意点

最新完整结果见[双场测试主报告](新会议双场泛化测试_语义复核_v19.md)。允许原文支持的合并、拆分和整体方案采纳；原标注不必视为唯一答案，内容匹配与负责人/状态要分别讲清。两场可接受答案、原始参考及逐条判定都已留存，下面的评测汇总保留具体数字。

| 已知问题 | Demo 中怎样处理 | 后续修复位置 |
| --- | --- | --- |
| IS1000a 将一般设计与技术设计合并，全绑定C | 不宣称这项能直接正确分派；展示确认或使用责任人明确的中文输入 | `context_v5`解释/核验中的工作拆分、指代及负责人绑定 |
| TS3003b 未决栏10条中4组重复，部分与决定栏冲突 | 作为已知质量问题记录；若要整页展示，先决定如何呈现已选方向与待核实条件 | `minutes_review.py`修正后追加项的归并，以及与决定的状态一致性 |
| 国际市场、语言适配没进决定栏，但在事实栏 | 明确栏目漏项与整份纪要漏信息不同，不声称所有内容都分对栏目 | `decision_review.py`的采纳/开放状态判定与裁决覆盖 |
| IB4005 旧名单混入最终名单、Gisella被最后检查删掉 | 暂不作为无需复核的自动布局结果展示；保留问题证据 | 人物与引用的一致性、撤回决定的证据要求 |
| 长核验可能截断并自动重试 | 预先彩排、保存可回放结果；现场显示真实运行状态 | 当前恢复已能完成这两场，后续再评估延迟优化 |

这些问题不要求在准备 demo 前全部重构。先跑通演示的核心路径，遇到真实阻断再按来源修复。最新两场的输入/参考/源码及 SQLite 重开、离线重复提交均已验收；历史全库测试有旧失败，具体见下方记录，不能引用旧套件数字宣称当前全库全绿。

### 给下一轮助手的直接任务

读完本节和双场测试主报告后，开始准备一次本地 demo：确定短中文连续会议、选定演示载体、复用现有 Service 做入口并彩排。用户已表示可以进入 demo 阶段，不需要再询问是否继续。当前只完成了交接，**demo 入口、界面、当前版本彩排和演示操作稿仍待做**；没有在后台运行模型或 demo 服务。

## 评测阶段交接记录（历史保留，旧“下一轮”安排以上文为准）

**最新：新增 IS1000a、TS3003b 两场完整测试，主助手已亲自逐条语义复核。** 同v19配置、独立空历史；793段原文全部覆盖，先通读重注并冻结可接受答案，再运行。两场首次完整调用均processed，含自动恢复，无显式恢复批次；18＋20次请求，2,080,276 token。任务内容P=7/7、参考R=7/7；决策内容P=23/23、决定栏参考R=18/20，另外2项在事实栏，整份纪要内容覆盖20/20。不同参会小组、同AMI遥控器场景，不能称跨领域泛化。[本轮主报告](新会议双场泛化测试_语义复核_v19.md) · [汇总指标](../runs/2026-11-18-two-unseen-v19/evaluation.json)

**高内容分不等于可直接分派或状态一致。** IS1000a R16合并一般设计与技术设计并全绑定C，职责归属不可靠；按冻结的含负责人整条记录口径，第一场P=1/2、完整参考R=1/3，两场合计6/7、5/7。内容口径与严格伴随分数并存，运行后口径说明已留档，未改冻结参考。TS3003b未决栏有10条，其中4组重复，且把预算/市场待核实扩成方向未定；来源是原U项保留后，4项事实又改写成未决直接追加。语言适配在核验中因实现未定被删出决定栏，事实仍保留；IS1000a国际市场被扫描发现后裁决遗漏，事实仍保留。尚未修改生产机制。[第一场复核](../runs/2026-11-18-two-unseen-v19/IS1000a/人工逐条复核.md) · [第二场复核](../runs/2026-11-18-two-unseen-v19/TS3003b/人工逐条复核.md)

可接受答案入口：[IS1000a](../runs/2026-11-18-two-unseen-v19/IS1000a/标注与可接受答案.md)、[TS3003b](../runs/2026-11-18-two-unseen-v19/TS3003b/标注与可接受答案.md)。原AMI参考另存reference-original.json；推理后未修改参考，所有输出逐条标注并绑定结果哈希。源码提示76文件一致、数据库重开及离线重复提交均通过。两场从现在起属于回归样本。

**最新：IB4005 已按用户要求完成语义复核与根因诊断。** R3 的数字准备与分发可合并命中两项参考，R6 的本人对调提议获同意可算合理承诺；任务语义精确率和参考召回均为 **2/2，100%**。分发方案属实，改记栏目重叠，决策内容支持率 **8/9=88.9%**，参考召回仍 **7/10=70%**。这是同一输出的事后口径调整，非模型提升。原冻结任务50%/50%、决策77.8%/70%的判分及输入/输出均未覆盖。[语义复核与溯源](IB4005_语义复核与问题溯源.md) · [新判定](../runs/2026-11-18-unseen-IB4005-v19/root-cause-review/semantic-review.json) · [原测试报告](新会议泛化测试_IB4005_v19.md)

IB4005 真实问题：裁决用“Agnes 与 Marianne、David 同室”的原话支持 visitor one 名单，引用子串校验通过但人物不符；该条没进入最后状态检查。Gisella 单间已提取，却被最后检查仅以 open 删除，未要求撤回依据。教授/助理用房的文字指代与采纳较含混，仍记参考未命中。协议故障为 new_work 同时关联已有记录，以及 Q744/Q817 混用了 sync 后缀（正确为 Q366/Q460）；离线实际校验复现、局部协议探针通过。诊断新增模型调用0，快照92个文件与5个冻结文件均未变。首次 partial，经原有 Service 恢复批次增加4次请求后 processed；共30次请求、2,586,201 token。该场与 IB4003 属同一系列，已成为诊断/回归样本，不能再称全新盲测。[离线诊断](../runs/2026-11-18-unseen-IB4005-v19/root-cause-review/offline-probes.json) · [运行验收](../runs/2026-11-18-unseen-IB4005-v19/acceptance.json)

两场完整会议已用 context-v5 version 19＋决策核验 version 2 重测。最终任务：ES2002a 3TP/0FP、ES2002b 4TP/1FP，合计精确率 **7/8=87.5%**、参考召回 **7/7=100%**。最终决策按独立主张：a 6TP/0FP、b 9TP/0FP，合计精确率 **15/15=100%**、AMI 参考召回 **10/11=90.9%**。第一场首次 partial（核验重复 JSON 键），经现有 Service.retry_extraction 补 1 次请求后 processed；第二场首次 processed。首次运行任务参考命中 4/7，恢复后 7/7。两场最终无阶段错误，离线重复提交、数据库重开及源码快照核对通过。[最新完整重测报告](两场会议重测_v19_任务与决策指标.md) · [逐条判分](../runs/2026-11-18-full-v19-retest/annotations.json)

本轮剩余问题：第二场“if possible we might consider”语音识别建议仍进入 conditional_work 和 candidate item，计 1 个任务误提；红外传输在草稿及独立核验中存在，却被最终裁决漏掉，计 1 个决策漏召回。原“稍后在展示中补充”的误提已转为 context_only / meeting_discourse，最终无任务、无澄清卡（本轮 R13，勿与本轮正常分工 R21 混淆）。第一场 Craig/Andrew 的共同工作时段仍遗漏；4 张不能直接建任务的需求/方案/澄清卡另报。原文输入相同、任务核验配置从旧版关闭思考改为 high，结果不能只归因于模糊意向改动。

模糊意向分类已接入 context-v5 version 19。新增 meeting_discourse / unclear_intent 核验依据，后者显示“待澄清意向”，通过 clarify_and_add_task 显式补全描述和负责人后创建任务。此前八个短对照通过；ES2002b 原 87 段的 R21 在默认高推理核验下无多提，关闭核验思考时仍为 4TP/1FP。56 项定向测试通过，扩大至 116 项时只有此前已记录的错误文本断言失败。[模糊意向实施与验证](模糊意向分类_实施与验证.md)

跨会议决策重申已完成实施和实验。下一轮优先查 **IB4003 的执行任务误入已决事项**。用户已将“可选功能算不算已采纳”的措辞边界降为低优先级。新版通过 `--strategy context-v5 --review-decisions` 显式开启。[跨会议重申实施与验证](跨会议决策重申_实施与验证.md) · [前序决策提取报告](决策提取三个系统缺口_实施与验证.md)

| 比较范围 | 当前结果 | 下一轮如何比较 |
| --- | --- | --- |
| ES2002a / ES2002b，两场开发会议 | 本轮完整新推理决策精确率 15/15，参考召回 10/11；前序复用草稿为 15/17、11/11。新增认可高级功能原则，同时漏掉红外，正确主张集合有变化。 | 复核红外在最终裁决中的遗漏；任务侧保住 7 项参考，检查语音识别建议误作条件承诺。 |
| IB4003，办公室分配 | 完整稿 390 段。7 行决定中 6 行获原文支持，另有 1 行执行任务。AMI 命中 1/3。 | 单看转错类别的那一行，同时复核其余 6 行。此场已用于诊断，后续可作回归样本。 |
| 两场中文 Service 对照 | 新版有效清单 2 项，历史 4 条，数据库 1 条任务。次场仍有多余的改价行动候选。 | 回归断言已检查两场时点、重申和替代关系、重复提交及重开。 |

开发集的决策精确率按独立主张计，IB4003 按输出行计。办公室会议漏掉的两条 AMI 参考是 Gisella 与访客共用双人间、本区域不设食堂，计入召回。原始主张、证据 ID 与判分可逐条复查。[最新两场评分](../runs/2026-11-18-full-v19-retest/evaluation.json) · [前序及办公室评分](../runs/2026-11-18-decision-system/evaluation.json) · [冻结口径](../runs/2026-11-18-decision-adoption/rubric-before-run.json)

### 1. 先查任务怎样进入已决事项

IB4003 第 322、326、329 段讨论下次会前询问同事偏好、准备分配草图。方案 1 的本场草稿为空；分段扫描发现“下次会议前形成具体分配提案”，随后 `decision_reconcile` 接受议题 10，以第 326 段（`IB4003.sync.266`）作为采纳依据。最终决策第 4 行记下了这项分派。可以从裁决节点直接追查模型把哪句话理解成“已确定的会议决定”。[整场原文](../runs/2026-11-18-decision-system/IB4003/input.json) · [阶段与节点 ID](../runs/2026-11-18-decision-system/IB4003/review-stages.json) · [最终输出](../runs/2026-11-18-decision-system/IB4003/review.json) · [裁决实现](../meeting_eval/decision_review.py)

建议用三个对照验收：① 草图分派退出决定，保留“同室安排征询个人偏好”这一已认可的原则；② ES2002b 保留已明确采用的三类讨论方法；③ “首批仅限会员，李宁请修改报名页”仍产生一条资格决定和一条真实任务。反向误分也已留样：次场只宣布年费改为 89 元，纪要却额外要求确认执行人。该项计入行动候选质量，数据库中实际创建的仍只有李宁的任务。[首场纪要](../runs/2026-11-18-decision-system/service-final/initial.md) · [次场纪要](../runs/2026-11-18-decision-system/service-final/replacement.md)

### 2. 跨会重申已验证

首场定下会员资格和 99 元年费，次场重申资格并将年费改为 89 元。真实模型给资格写入 `reaffirms`，给改价写入 `supersedes`；有效清单保留两项，四条历史原话可查。旧库原样重复已用副本回放，改写与不同批次已用独立裁决对照。64 项定向测试通过；加跑恢复套件后，65/70 通过，其余 5 项均为前次已记录的失败。[保存结果](../runs/2026-11-18-cross-meeting-reaffirmation/live/storage.json) · [实验与复现入口](跨会议决策重申_实施与验证.md)

### 运行入口与已知测试状态

从项目根目录 `ByteDance/feishu-meeting-eval` 运行。以下 PowerShell 命令可先做离线回归。

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='tests'
python -m unittest test_decision_adoption test_decision_review test_minutes_review test_mvp
```

验证跨会修复时，运行 `python experiments/full-meeting/decision_service_control.py runs/decision-service-next`，使用新的输出目录和 SQLite。该脚本调用真实模型。只重测 IB4003 决策时，[实验入口](../experiments/full-meeting/decision_system.py) 的 `review` 模式从指定输出目录读取 `input.json` 和 `baseline/result.json`；新目录需先从[本次 IB4003 现场](../runs/2026-11-18-decision-system/IB4003)复制这两份输入并保留层级。

本轮留存的定向测试为 40/40，全库为 333/340；其余 7 项用旧版提取器复验同样出现 4 个断言失败、3 个错误。新一轮可据此区分新增回归。[定向日志](../runs/2026-11-18-decision-system/targeted-tests.txt) · [全库日志](../runs/2026-11-18-decision-system/unittest.txt) · [旧版对照](../runs/2026-11-18-decision-system/archived-extractor-regression.txt)

## 历史版本与实验记录

**决策分支更新（11 月 18 日）。** context-v5 已接入选择、采纳、后文引用及最终状态校验。两场开发会议参考召回均为 10/11，严格人工精确率从 12/17 到 14/19，绝对误提仍为 5；边界判定会改变排序。[实验与限制](方案一_决策采纳依据实测.md)。


**2026-11-18 更新。** context-v5 version 18 已加入决策与行动分流，完整冻结回放 P=63.6%、参考 R=100%，真实片段中仍有 R21 多提与 GN33 汇报漏项。[决策与行动分流验证](决策与行动分流验证.md)。下列整场实跑为 version 17。


更新时间：2026-11-17。本文件是下一对话的首读入口。项目根目录：`D:/HuaweiMoveData/Users/13736/Desktop/Remote_Intern/ByteDance/feishu-meeting-eval`。

**最新测试：** 用户要求先重新跑 ES2002a，通过后再取一场完整会议。两场均使用 context-v5 version17、全新模型目录和空 SQLite，从完整 Service 从头推理，没有导入旧阶段结果。ES2002a 434段，processed，参考分工3/3保留，11次调用、776,927 tokens、284.09秒；ES2002b 977段，processed，三项语料分工及运行前另记的纪要归档承诺4/4保留，16次调用、2,583,625 tokens、707.18秒。两场均无最终阶段错误，保存/重开/HTTP禁用下重复提交一致。详见[本轮主报告](完整会议重跑与第二场测试.md)。

**通过边界与剩余问题：** 通过指整场可完成、关键分工与负责人保留、没有虚构硬截止日期，不是语义全对。ES2002a Craig/Andrew的共同工作时段结构化遗漏，R5需求卡把Andrew误写为David；ES2002b有产品范围要求、讨论框架升成候选任务，R21把“稍后展示时补充”解释为修改演示稿，另有4张设计要求/方案卡需人工甄别。第二场check_work先16K截断，现有恢复提升32K后响应缺一个括号，经原有close_record_checks规范化通过，已离线复现；两场均未触发strict引用补丁。无真实飞书账号映射，无外部写入。

**本轮改动及证据：** 仅完整会议输入脚本补入未被dialogue-act标注覆盖的词语；ES2002b遗漏的原词ID为ES2002b.B.words142（um），保留原词ID与时间戳后100%词语覆盖，ES2002a输入复核不变。生产源码/提示与运行快照一致。新证据分别在`runs/2026-11-17-full-meeting-ES2002a-fresh-v17/`、`runs/2026-11-17-full-meeting-ES2002b-fresh-v17/`，均含acceptance/usage-audit/summary及原始响应。旧失败/恢复证据不变，未跑其他数据集，当前无运行请求。

## 前序协议修复与定向恢复

**本轮指标复核：** 合并items与can_add_task=true确认卡并按record_id去重，严格执行任务口径暂计ES2002a=3TP/1FP/0FN（P75.0%、参考R100%），ES2002b=4TP/7FP/0FN（P36.4%、参考R100%）；合计7TP/8FP/0FN，P46.7%、参考R100%、F1 63.6%。只看items则合计P70.0%。参考为运行前保存的3+4项工作，不是穷尽全文金标；R15讨论框架存在边界争议，若另认可，P为53.3%，主分数不改。字段准确性未包含。逐条判定见`runs/2026-11-17-full-meeting-two-run-task-metrics.json`和本轮主报告。新增模型调用0。

**最新实施完成：** 用户已授权执行证据协议修复计划。context-v5升级version17，解释提供封闭输出schema，输入span/输出ID说明分开；完整草稿的引用类型错误可进入一次非思考strict补丁，错误反馈结构化。68项相关离线检查通过，独立代码复核无阻断项。ES2002a完整Service恢复为`processed`，无阶段错误；5次HTTP、525,635 tokens、179.576秒。三项参考分工保留：David R6在item，Craig R8在范围/承接确认卡，Andrew R9在候选item及承接确认卡。3条items中另有总体项目任务R2，不能误说items恰好等于3项参考工作。详见[修复结果](完整会议证据协议_修复结果.md)。

**恢复范围：** 已校验复用4个tracking窗口及旧事实/决策；工作解释/核验与纪要核验/修补/复核重新运行。首个解释响应即通过，真实调用未触发证据补丁；补丁路径经离线验证。结果保存、重开和重复提交一致；没有真实飞书账号映射。旧partial原件及所有历史成绩不变。新证据`runs/2026-11-17-full-meeting-ES2002a-protocol-recovery/`，实现/测试/快照`runs/2026-11-17-evidence-protocol-implementation/`。调用额度已关闭，当前无运行请求。P1缓存、输入压缩、partial字段展示和剩余语义问题未扩展实施。

## 该修复的前序调查与首轮失败（历史状态）

**最新溯源与方案（尚未实施）：** 用户要求先仔细定位系统问题。已完成[系统溯源与方案](完整会议失败_系统溯源与方案.md)和[实施计划](superpowers/plans/2026-11-17-evidence-protocol-repair.md)。离线证明两份失败响应仅将证据对象改为ID数组即可通过现有解释校验，但这只是因果探针，不能直接放行：第一次3处offset越界，第二次90处均为单字符。根因链为提示混淆输入span/输出ID、interpret无output_schema、证据补丁完整schema门槛挡住引用类型错误、重试反馈丢失明确类型信息。现有13项wire/reference测试全通过，缺实际跨边界案例。新增诊断脚本`experiments/full-meeting/diagnose_protocol.py`及`runs/2026-11-17-evidence-protocol-diagnosis/audit.json`；会议模型调用0，生产未改。

官方资料核对：JSON模式只保证JSON；strict工具约束schema，但thinking时强制named/required tool_choice会400。建议保留首轮解释思考配置，完整语义草稿的引用问题用一次非思考strict补丁，再独立核验。P0统一契约/恢复，P1另做阶段缓存依赖、输入去重和字段失败展示。注意改解释prompt会改变当前整个pipeline缓存父目录，不能声称已有tracking能自动继承；计划要求显式验证复用。整场恢复还需刷新依赖工作结果的纪要核验。

**最新完整会议测试：** 用户要求跑一场完整会议，已用AMI ES2002a完整434段（约18分钟、4人）从Service入口实跑context-v5 version16，未复用旧模型输出。最终`partial`：全文4个检查点通过，保存16事实、6决策、4未决；工作解释两次均返回证据对象数组，而接口只接受ID字符串数组，故items和任务确认卡均为0。两份未通过草稿都已有3项语料分工，不能计作成功。实际提示同时出现“ID数组”和“证据对象start/end”，引用补丁入口又因结构不符拒绝草稿。完整诊断见[完整会议测试_ES2002a](完整会议测试_ES2002a.md)。

本轮耗时324.22秒，11次HTTP、793,699个已知token；重复提交新增调用0，重开SQLite读取一致。没有真实飞书写入、生产修改或修复后实跑。新增可复现入口`experiments/full-meeting/run.py`，证据目录`runs/2026-11-17-full-meeting-ES2002a/`。当前无运行中的请求。后续优先统一输出证据契约，先用保存响应离线验证，再定向恢复失败分支；不要把这次失败与此前GN25语义漏提混为一类。

## 此前任务边界修复与扩展集状态

**后续状态核对发现回退：** 用户询问扩展测试未解决项后，用当前归并器离线回放GN13/18/20/28/33。GN33 R12/T3原先命中的“路径审查并初秋汇报”因整体progress转为report，任务入口少一个命中；其余四例旧漏项未补回。GN29两卡修复只证明局部效果，不能认定没有其他召回损失。见[未解决问题清单](扩展评测_未解决问题清单.md)及其中回放证据。生产未修改，新增模型请求0。

**当前结论：GN29 R8/R23 的进度汇报误入新任务确认卡已修复。固定上一轮模型输出、经Service回放为8TP/5FP/0FN，原11条items和其他确认卡不变；不是重新推理成绩。GN25增加非工作引用覆盖检查后，关闭思考与low核验两轮仍均为2TP/0FP/1FN。** 两轮纯背景反例均无任务/确认卡。当前无运行中的模型请求。

**最新实施证据：** [任务边界与条件保留：实施与测试结果](任务边界与条件保留_实施结果.md)。生产策略 context-v5 版号16；报告保存完整time，已知非未来工作不能因关系new获得新建许可；核验增加非工作记录引用范围。默认策略仍split-v3，核验low仅作实验未设默认。66项受影响离线检查通过；本次真实共4次HTTP、95,167个已知token，总上限6次，没有追加试跑。GN25仍未解决，不重复相同提示或据剩余额度继续请求。实验目录为 `runs/2026-11-17-task-routing-coverage/`，入口和审计见新报告。

**前序排查背景：** [离线排查报告](任务边界与条件保留_离线排查.md)记录修复前的根因和零模型调用对照。诊断中将set改keep只用于定位；本次生产修复保留原时间，不按R编号硬修。旧模型输出与冻结分数保留，不能覆盖成新成绩。

## 用户目标与约束

用户关注会议任务的召回率和准确率，以及事项能否保存、失败能否恢复；不要再以整场纪要语义正确率作为主指标。此前明确：优先解决未完成和系统机制，零散语义错误不适合逐例加规则，主要受模型能力与思考时间限制。

用户反复要求只跑必要测试，不要每次全量。不自动重跑60/115例，不通过改标签提高分数。最新授权是实施状态分流和覆盖核验方案并测试，已执行并如实记录负结果；后续继续研究时先读本轮原始输出，不把建议当成已经验证的解法。

## 当前实现与测试状态

默认策略仍是`split-v3`；改进策略为可选`context-v5`，当前version=17。识别实测版本仍需同时看代码/提示摘要。客户端支持显式low，但解释和核验的low实验都没有改变默认配置。

| 阶段 | 已完成的机制 | 已知限制 |
|---|---|---|
| 全文跟踪 | 原始发言ID、程序分配实体/线程ID、6000文本字节/128段检查点、内容失败后二分一次、保存成功前缀 | GN25/26/29/38四例全部跟踪完成；不代表后续任务完整 |
| 引用与输入 | 模型统一输出原始segment_id；全文只保留一次；引用偏移去重；完整草稿允许一次8K证据补丁 | 截断JSON不能补丁；内部仍保留Q编号适配 |
| 解释预算 | 支持显式low；定向实验interpret_work=low/32768 | 默认high未改；只验证两例，任务质量未达标 |
| 状态分流 | progress/completed+new保留report及time；新建卡须有受支持的future_work | GN29两张误提取卡消失，其他语义错误仍在 |
| 工作覆盖 | 新增nonwork_record_evidence；共享引用也检查独立工作 | GN25关闭思考/low两轮仍漏条件支付；未触发repair |
| 失败与恢复 | 现有run_stage有界重试、节点锁、接受结果缓存；新实验限制总HTTP次数 | 付款402仍是终止状态，不会自动检测充值后恢复；不要靠外层整场重跑 |

前序解释预算实验固定两例原文、history、已验证tracking、解释提示及输出契约，只改变interpret_work。历史实际`check_work/check_repair`关闭思考；`repair_work`显式保持旧high。最新覆盖对照则固定GN25解释，比较check_work关闭思考与low（同16,384上限），repair/check_repair配置未改且未调用。旧计划写“原核验high”不准确，以实际config.json为准。

实验使用TaskOnlyExtractor，从现有Service入口执行任务分支，未运行纪要/事实/决策。GN29的398段、GN25的93段跟踪均复用。因此两个processed仅指这个实验任务分支，**不能说旧纪要partial已经修好**。没有真实飞书账号映射，SQLite任务表为0；保存的是源结果、items、待确认内容。重开数据库、重复调用已核查一致，没有重复模型调用。

## 前序解释预算结果：保留原始计数，不与最新回放混用

| 样例 | 必需任务TP | 额外预测FP | 漏项FN | 准确率P | 召回率R |
|---|---:|---:|---:|---:|---:|
| GN29 | 8 | 7 | 0 | 53.3% | 100% |
| GN25 | 2 | 0 | 1 | 100% | 66.7% |
| 合计 | 10 | 7 | 1 | 58.8% | 90.9% |

F1=71.4%。items与`can_add_task=true`的实际工作确认卡一并计入，按record_id去重；同一描述含两个独立任务目标时分开匹配。GN29有11条items和3张计入指标的确认卡；最后一条item同时覆盖T7/T8，因此是15个原子预测、8TP/7FP，不是按卡片数直接计算。GN25一条item覆盖两个目标。

严格字段指标为7TP/10FP/4FN，P41.2%、R63.6%。其中GN29 T1负责人存在冻结标注已经承认的边界争议，应与识别指标及争议说明分开读。两例都是调优回归集，不是新的盲测或普适性证明。

真实共4次HTTP请求、283,822个已知token；实验限额8次，没有用完，也没有追加试跑。两次核验原始meta记syntax_invalid，但现有本地结构规范化生成normalized.json后节点accepted，没有额外模型请求。不能只看meta就判定核验失败。41项相关离线检查通过。

## 当前问题及具体证据

### 1. GN25：条件性支付被当作背景丢掉

冻结任务T3：如果大家决定Grad B参加Santa Barbara会议合适，由团队支付费用。原文`qm.Bed011.639`明确给出“if we all decide ... we'll pay for it”。本次解释记录R6把资助与访客/行程一起归入`context_only`，以“尚未决定”为理由不保留条件任务；核验也没有报遗漏。

这项工作在输入中，在tracking主题范围内，解释已完整返回；不是HTTP失败、长度耗尽或SQLite丢失。最近version15 high和本轮low都是2/3，version14曾为3/3；不能说是low造成的新退化。

下一步优先检查：已有条件承诺为何被“未决定参会”覆盖；核验是否独立检查同一背景记录中包含的条件工作。现有提示已经要求conditional和背景旁另建work，不宜未经归因再补一条相同口号。

### 2. GN29：7个额外预测，至少分成三类

| 输出记录 | 现象 | 冻结口径/需追查位置 |
|---|---|---|
| R15 / item:4 | 推进并命名G函数方案 | 一般研究方向认可升成decided工作；原文576/578/587 |
| R17 / item:5 | Robert阅读Heckerman and Breese论文 | 冻结任务表无此项，计FP；527/529有you should take a look，可能是指派边界或参考漏标，必须保留争议 |
| R22 / item:7 | 落实ontology与EVA关联并联系人 | 设计需求升成执行任务；冻结排除implicit_need，原文622 |
| R25 / item:9 | 构建instance gadget/数据结构 | 假设实现方案升成decided；原文648/650/652 |
| R8 / review:R8 | 明年交付物只完成一半 | 解释state=progress，却形成can_add_task=true的ambiguous卡，且问题为空；原文427 |
| R19 / review:R19 | 落实JavaBayes组合函数方案、咨询Srini | 问题/多个备选方案/一般建议合成可加任务卡；原文535、661、680等 |
| R23 / review:R23 | 他人ontology进度，并再次提到示例展示 | state=progress仍可加任务，问题为空；展示已由R24匹配T6，含重复内容 |

R8/R23 的上述旧路径已修复并完成Service回放：报告分支接受带明确时间的状态汇报，保留time；新建许可增加future_work及状态核验约束。两条成为report，空问题卡及对应pending消失。其余语义问题和冻结标签保持。

R15/R22/R25/R19则主要涉及任务资格与承诺的判断。GN29上轮没有有效解释结果，所以不能推断本轮low降低推理后造成这些错误。R17若认作有效额外任务，FP可从7降到6，但主分数不修改，整体仍未达零误提取门槛。

### 3. 字段问题另列，不逐例硬修

- GN29 T1：任务描述正确，但负责人是Grad A and team、ref=null；冻结参考是Grad A。原标注已指出you guys也可解释为团队共同负责。
- GN29 T6：展示ontology示例被写成next Monday截止，未保留“ontology就绪后”的前提。
- GN25 T1：roughly no more than ten over the summer仍带十项上限；冻结参考要求无十项硬指标。

这些不影响本轮“生成阻塞解除”的结论，但影响完整任务指标。先决定统一机制的范围，再考虑模型配置或小规模对照，不按单个例子扩写大量提示。

### 4. 仍未验证的范围

本轮没有重新跑完整Service的纪要分支、没有全量自然会议回归、没有验证新的独立泛化集。low仅开放参数与验证两例，没有证明适合全部任务。此前14场英文自然会议的tracking故障已在4例上修复验证，但其余样例未统一重测。

第二阶段“完整线程分批 + 局部核验 + 全局差异核对”**尚未实施**。已批准计划只在生成规模仍导致未完成时启用；本轮两例都完整，所以不自动继续分批，不把任务语义错误都归为需要分片。代码中没有新增interpret_batches/batch_review模块。

## 下一对话建议从这里开始

1. 先看最新结果和逐目标匹配，分开阅读解释records/events、核验checked_records/checked_events、归并review_records、Service.pending，不立即调用模型。
2. GN29 R8/R23 状态入口已修复，不重复修。其他方案讨论升级为任务及描述混合问题仍属语义边界，先判断是否有值得处理的共同机制。
3. GN25非工作引用覆盖已接入并真实测试；关闭思考和low都读到条件支付但仍认可context_only。下一步若继续，需要验证独立动作/承诺判断如何避免受整条背景分类影响，不再把“清单没有639”作为当前根因，也不把增加思考自动视为解法。
4. 单独记录R17及负责人边界争议，保持冻结标签不变。不要用改标解释掉全部FP。
5. 只有新改动及离线验证支持真实回归时，才按受影响节点开新run。最新4次覆盖核验请求已结束，不能为了6次上限还有余额自动继续；前序解释预算的4次请求属于另一个历史实验。

这是一条建议顺序，不是已经定位了所有根因或已经完成修复。用户此前不希望逐例处理语义小问题，下一对话应先判断共同机制是否值得修。

## 接手必读与证据入口

- [最新实施与测试报告](任务边界与条件保留_实施结果.md)：状态修复、两轮覆盖负结果、成本和复现入口。
- [前序解释预算报告](interpret-budget-results.md)：原始模型结果、成本、字段和标注争议。
- [逐目标匹配](../runs/2026-11-17-interpret-budget-low/task-matches.json)、[参考与预测汇总](../runs/2026-11-17-interpret-budget-low/task-output-review.json)、[审计](../runs/2026-11-17-interpret-budget-low/audit.json)。
- 原始现场：`runs/2026-11-17-interpret-budget-low/natural/GN29/`和`GN25/`。先看`input.json`、`result.json`、`config.json`、`preflight.json`；模型请求/响应、节点state/accepted在`model/context_v2/`下，数据库为`state.sqlite`。
- [调研设计](interpret-budget-research.md)、[执行计划](superpowers/plans/2026-11-17-interpret-budget-and-batching.md)：第一阶段执行，任务质量门槛未过；第二阶段未触发。
- [跟踪修复](tracking-recovery-v2.md)、[引用与输入去重](interpret-reliability.md)：避免重复修已经处理的问题。
- 数据集：`data/generalization-v1/`，72例（12标注试验、40自然、20控制），正式60例；标签与freeze保留。标注为模型辅助加助手证据复核，不是独立人工金标。[原扩展评测](generalization-v1-results.md)仍保留自然40例P50.0%/R13.9%的冻结原始成绩，不用本轮两例替换。
- [此前交接全文](HANDOVER-2026-11-17-before-next-chat.md)：旧115例、历史计划和所有进度，仅作历史查询。

## 代码入口与恢复注意事项

| 文件 | 职责 |
|---|---|
| `meeting_eval/model_client.py` | low/high/max参数、真实HTTP及响应元数据 |
| `meeting_eval/context_v5.py` | 原始ID边界、动态核验契约、覆盖提示；重点看_stage中的coverage_review |
| `meeting_eval/context_v2.py` | 跟踪→解释→核验→有界repair/recheck的流程 |
| `meeting_eval/context_state.py` | 记录校验与reduce_context，生成items/review_records；重点看progress及can_add_task流转 |
| `meeting_eval/context_v3.py` | reduce_v3及历史任务关联确认 |
| `meeting_eval/context_coverage.py` | coverage_findings转有界修复计划 |
| `meeting_eval/task_events.py`、`meeting_eval/service.py` | 工作状态归并、Service保存、确认与操作 |
| `meeting_eval/stage_runner.py` | 请求额度、节点恢复与接受缓存；复用现有机制 |
| `experiments/interpret-budget/run.py` | 固定tracking的任务分支实验、8次总HTTP限制、配置冻结 |
| `experiments/interpret-budget/audit.py` | 离线核验来源、调用、冻结标签与人工匹配计数 |

实验runner独立复核的两处P2已修：waiting_retry结果可续跑；恢复前先核验全部案例配置/代码，不能覆盖旧preflight。这两条未在实测中触发，仅离线验证。实测快照`runs/2026-11-17-interpret-budget-low/source.zip`与最终`runs/2026-11-17-interpret-budget-implementation/final-source.zip`都保留；差异在`post-run-fixes.diff`。实测生产代码和提示与最终一致，runner恢复逻辑有两处后补修复。

**不要对现有low run直接执行新版runner --resume**：旧manifest没有新增执行身份字段，新runner会拒绝；该run已经完成，不需要续跑。不要删除state、修改旧manifest或清空预算以绕过限制。以后实验用新目录，明确固定输入/阶段范围。

## 环境与最小复核命令

Windows PowerShell、Python 3.13、标准库unittest，本目录无Git仓库。凭据沿用上两级`meeting-agent/.env`，不要输出或复制；可用余额未知，本轮没有调用余额检查。文件和实验输出保留，不清理用户研究材料。

从项目根目录执行以下审计不调用模型：

```powershell
$env:PYTHONUTF8='1'
python experiments/interpret-budget/audit.py --out runs/2026-11-17-interpret-budget-low
```

41项通过的日志、RED/GREEN记录、独立复核、SQLite验证和最终核查位于`runs/2026-11-17-interpret-budget-implementation/`。只读接手不必重跑测试；修改后按影响范围选择`test_inference_config.py`、`test_interpret_budget_experiment.py`、`test_stage_recovery.py`、`test_reference_repair.py`等。默认GBK可能让旧测试读取UTF8失败，使用上述PYTHONUTF8设置。
