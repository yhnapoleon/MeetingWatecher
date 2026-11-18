# 数据、论文与开源调研

调研日期 2026-11-13。当前最影响实现的选择是能取得哪类输入：带时间戳和说话人的转写可以直接评承诺抽取；要评声音定位需要对应音轨；要评会前回顾还需要历史任务状态和查询身份。这三种证据分别采集。

| 本轮深入核查 | 对首版的影响 |
| --- | --- |
| [语料实查与可复现实验](corpus-study.md) | VCSum 提供可直接定位的中文误报样本；QMSum 四场真实文件可测会内证据定位和同项目串会。记录获取条件、固定版本、失败案例和分母。 |
| [五个难点的方案与对照](methods-study.md) | 从声学归属、屏幕指代、跨句承诺到时态、撤权，逐项给出基线、困难负例、数据和采用条件。跨会部分加入直接研究会议决策演变的 EvoWiki / CrossMeet。 |
| [飞书平台契约与联调](platform-study.md) | 原生导出参数、任务幂等窗口、会签整体完成和按资源授权，均按官方接口逐项核查。 |

## 第一批数据从哪里取

| 来源 | 选样与使用方式 | 需要补什么 |
| --- | --- | --- |
| AliMeeting4MUG | 中文行动项检测 Track 5 有公开基线、数据入口和解析代码。先选一场有行动句标签的会，逐句保留发言顺序；同时保留周围未标为行动项的讨论。仅采正句无法测误报。[官方代码及下载入口](https://github.com/alibaba-damo-academy/SpokenNLP/blob/main/alimeeting4mug/readme.md) · [数据集](https://www.modelscope.cn/datasets/modelscope/Alimeeting4MUG) | 人工把跨句承诺合成任务，补交付物、负责人、日期精度。先核对实际发布版本与数据授权，再决定是否能向项目方转交原文；代码仓库许可证只说明代码。 |
| AliMeeting / M2MeT | 中文近、远场录音，同步采集；TextGrid 含说话人、时间区间和转写。选有连续多人发言或打断的一段，对照录音核对说话人和边界。[挑战赛与格式说明](https://www.aishelltech.com/M2Met) | 对照原始会议和媒体 ID 再连接其他标注；不同发布包不能靠名称相似拼接。声学说话人编号只代表本场。 |
| AMI | 同一设计团队有连续会议。可先按 ES2002a、ES2002b 检查人工摘要的 DECISIONS/ACTIONS 和对应发言，做英文关联对照。官方也公布了各场次是否有投影片，以及个别源文件缺失。[系列编号](https://groups.inf.ed.ac.uk/ami/corpus/meetingids.shtml) · [摘要与证据](https://groups.inf.ed.ac.uk/ami/corpus/annotation.shtml) · [媒体缺损](https://groups.inf.ed.ac.uk/ami/corpus/dataproblems.shtml) · [许可与署名](https://groups.inf.ed.ac.uk/ami/) | 人工标同一事项是否被修改、延续或替代。原语料无本项目的飞书账号与任务回执；模拟补充字段单独注明来源。 |
| 自录两场中文周会 | 参与者同意后用虚构项目自然讨论，一次记录承诺，一次追踪进展。保留原始妙记导出选项、名册、录音和会前模拟任务表。真实导出能暴露分段、匿名标签、时间精度等问题。[妙记导出说明](https://www.feishu.cn/content/article/7578773484596153570) | 写明录制用途和可使用范围；原始版本供解析，脱敏版本供标注。样例目录是台词级模拟；完成录制和导出后再归入真实妙记格式子集。 |

**首个采集动作**：从 MUG 的 Track 5 开发样本按 meeting ID 取整场，人工挑出一段至少涉及两位说话人的任务讨论，再取同场一段未形成任务的讨论。登记原始 ID、原版字段、来源链接、许可状态、引用段号和媒体可用性。缺少日期或时间戳就按实际缺失记录。没有真实内部业务数据时，用这组材料先看抽取错例；业务表现要用获准使用的业务样本单独测。

## 论文如何影响设计

| 方法与出处 | 在本项目中做什么实验 | 何时值得引入 |
| --- | --- | --- |
| Liu 等的行动项识别以会议上下文建模缓解短句歧义，发布中文人工标注语料。[论文](https://arxiv.org/abs/2303.16763) · [官方实现](https://github.com/alibaba-damo-academy/SpokenNLP/tree/main/action-item-detection) | 固定同一批“我来”“周五给”样本，比较单句、含前后文两种输入，按承诺和负责人分别判分。可用公开分类器筛候选，再让抽取器填字段。 | 长会整场输入成本高，且候选筛选对承诺保持足够召回时。历史基线环境较旧，优先复用标签与解析逻辑。 |
| QMSum 将面向问题的会议摘要与相关文本区间联系起来。[论文](https://aclanthology.org/2021.naacl-main.472/) | 将“上次定了什么”拆成两次判定：有没有找对证据、在正确证据下是否回答正确。固定生成器比较整场输入和先找证据再回答。 | 出现答案流畅但引错会或丢失反对意见的错例时。跨会关系和权限需另行标注。 |
| Zep / Graphiti 用时序知识图保存事实随时间的变化。[论文](https://arxiv.org/abs/2501.13956) · [Graphiti](https://github.com/getzep/graphiti) | 给同一决策安排修订和撤回，同时问旧时点与当前时点。对比 SQLite 版本表和图检索的正确引用、过期结论、耗时与模型调用数。 | 第一批直接借用“生效时间与记录时间分开”的思想。等出现多条依赖链、简单版本表检索漏证据，再试图服务；权限过滤仍由应用控制。 |

## 可以复用的工具

| 工具 | 取用方式及边界 |
| --- | --- |
| Label Studio | 官方说话人分段模板能在音频上画时间区间。先用小样例核对导出的区间、说话人和本地段 ID；任务认领、状态变化另按本项目字段标注。第一批文本样例直接改 JSON 即可。[分段模板](https://labelstud.io/templates/speaker_segmentation) |
| WhisperX | 当只有录音时，候选管线为转写、强制对齐、说话人分离。用同一段中文重叠讲话，与人工边界及真实妙记结果比较；组号无法直接指派飞书账号。评中文前确认对齐模型、说话人模型的可用性及模型条款。[官方项目](https://github.com/m-bain/whisperX) |
| lark-cli 与飞书 Python SDK | 本机 CLI 1.0.93 的帮助与 schema 已核对。妙记详情可以只取逐字稿并返回文件路径，导出文本文法需真实样本确认。创建任务有幂等 token，更新任务通过 GUID 和 update_fields。原型用 CLI 核对测试空间，服务化时可用 SDK，同一份本地任务契约承接两者。[官方 SDK](https://github.com/larksuite/oapi-sdk-python) · [任务平台](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/task-v2/overview) |

本次接口核查可在本机复现，以下命令只查看本地帮助和参数：

```powershell
lark-cli minutes +detail --help
lark-cli skills read lark-meeting/references/lark-minutes-detail.md
lark-cli schema task.tasks.create
lark-cli schema task.tasks.patch
```

## 本地 meeting-agent 能借哪些实现

勘查对象为同级仓库的本地工作树，HEAD 为 `8db0b41`，包含后续未提交文件。下列路径指向实际勘查的源码和记录。

| 已有实现 | 在新项目里的用法 |
| --- | --- |
| [行动项结构](../../../meeting-agent/src/contracts/intent-preparation.ts) 定义 task、deliverable、可空 owner/time 和带修订号的 sources。 | 沿用证据引用与字段拆分，新增账号解析结果、截止日期精度及飞书任务绑定。可把既有 assignment 输出转成本项目预测，在相同样本上比较。 |
| [回放入口](../../../meeting-agent/src/domain/commands.ts) 的 ingest 将 speaker 设为 null、identity 设为 unknown。 | 导入器直接读原始逐字稿及名册；评已有抽取器时在适配层显式带入来源身份，否则测出的负责人错误混入了导入损失。 |
| [决策整理](../../../meeting-agent/src/domain/collection-decisions.ts) 保留决策、范围、出处和需复核标志；[模型上下文](../../../meeting-agent/src/agent/collection-context.ts) 只序列化指定信息。 | 用其结构做跨会证据投影。增加租户、查看人、来源 ACL 过滤与版本生效时间。旧项目的别名机制解决标识暴露，租户授权另需实现。 |
| [评分器](../../../meeting-agent/scripts/evals/scoring.mjs) 和[反例测试](../../../meeting-agent/tests/evals/scoring.test.mjs) 处理空分母、缺预测、假阳性；原分类函数按样本中的标签集合计数。 | 复用计分和反例思路。两条同类型任务会被标签集合合并，所以新行动项评分必须按任务实例一对一匹配。 |
| [自然对话脚本](../../../meeting-agent/tests/fixtures/collaboration-natural-dialogue.zh-CN.txt) 含暂缓、条件和分工；[语料说明](../../../meeting-agent/tests/evals/README.md) 标明合成来源与审核状态。 | 作为负例和录制脚本的素材，剥离操作者提示，重新标业务字段。它们适合作开发用例。 |
| [既有飞书接入记录](../../../meeting-agent/docs/feishu-coze-plan.md) 记录会中机器人在当时测试账号上的限制。 | 本项目第一步走会后妙记导出；会中机器人仅在需要实时回顾且测试租户具备能力时另行验证。该历史结果不能推断当前租户的会后接口权限。 |
| [集合测试](../../../meeting-agent/tests/unit/collection-digest.test.ts) 已覆盖个人决定不进入共享报告、相同议题未决项并列、引用别名随输入确定；[引用测试](../../../meeting-agent/tests/unit/source-references.test.ts) 已有修订后仍能定位历史引用的断言。 | 移植输入/预期的语义。把“个人与会议”扩展为两个带明确 ACL 的查看人；给并列议题添加一例“本次明确替代”，分别判相关和替代；把“引用版本没变”用于检查妙记修订前后证据可回放。 |
