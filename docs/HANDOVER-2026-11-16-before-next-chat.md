# 交接：context-v5 网络失败已恢复，剩余语义与结构问题

更新时间：2026-11-16。用户要求开跑整体数据，已完成 95 个场景 × 2 轮共 190 次模型验证及逐例原文复核。当前通过 **168/190（88.4%）**：第一轮 87/95，第二轮 81/95。被测算法及提示在两轮中保持不变，默认仍 split-v3，context-v5 可选。

随后用户要求先恢复网络异常：11次中断执行全部恢复，10次通过，C17仍因完成/进展汇报被当背景而失败。计入恢复后 **178/190（93.7%）**，两轮各89/95；原始首次运行168/190继续保留。剩余12次未通过为6次结构/证据错误、6次语义错误；服务同段冲突缺陷仍单列且未修复。恢复详情见 [网络恢复报告](context-v5-network-recovery-results.md)，证据位于 runs/2026-11-16-context-v5-network-recovery。新增28次请求全部收到响应，199,821 tokens；并发2、每例恢复一次，复用成功阶段，生产算法未变。恢复后的指标不是新一轮独立全量测试准确率。

优先阅读 [全量结果](context-v5-full-validation-results.md)、[运行计划](context-v5-full-validation-plan.md)。五项方案及实现见 [专项结果](user-solutions-results.md)、[设计依据](user-solutions-design.md)。本次运行前交接保存在 [前版交接](HANDOVER-2026-11-16-before-full-validation.md)。

## 用户最新口径

- M2 范围调整是已决定、需要执行的工作；保留内部员工、试点客户、今天，只问缺失负责人。
- 用户对 P03a“今天决定取消图文电视功能。”明确回答“保留为待分配任务”。同类 P12a 范围变更按 M2/P03a 标准应用，但 P12a 不是用户逐条重新标注。
- C23 的推断补问目的不必写入；明确目的正例仍须保留，无关背景反例不得编造义务。
- 明确暂缓的议题仅收集，无日期的已承诺工作继续保留。跨会议自动激活未实现。

原始自动评分 164/190，P03a/P12a 两例各两轮按当前政策修订后 168/190。修订与原文复核分开保存，原始输出、manifest、评分均未覆盖。先前将 P07a 询问“哪个场景”判为多余追问的两次扣分，经独立复核撤销：单句没有先行对象，提问存在合理依据，作为观察项保留。不要引用中间的166/190作为最终结果。

## 运行与证据

证据目录 runs/2026-11-16-context-v5-full：manifest.json / freeze.json / source.zip 为运行前冻结材料；r1、r2 保存所有首次请求、响应、状态、纪要与评估。source-review-notes.json 记录 190 次原文复核并绑定输出哈希；policy-overlay.json 保存用户裁定及类推范围；final-report.json 为最终汇总。

每轮原综合集54、边界对照33、补充6、完整服务链2。4 workers，各场景独立模型目录及SQLite，没有实际飞书写入。983次请求，971次收到响应，已记录4,186,590 tokens，模型运行约33.6分钟。0自动网络/格式重试，原有一次语义修正仍属于流水线。语料曾在前期被查看，本轮不是盲测；190次执行不是190个独立样本。

运行后205项项目测试与33项实验测试通过。生产代码/提示54份与启动前快照逐字节一致，输出代码摘要匹配。78个场景两轮均通过，12个结果翻转，5个两轮均失败，后者不都属于相同根因。

## 剩余失败的逐例溯因

用户要求提取并分类剩余12次，已整理为 [12次失败分析](context-v5-remaining-failures-analysis.md)，独立证据集在 runs/2026-11-16-context-v5-failure-analysis/README.md。12次对应9个场景；主因互斥分为汇报分类7、再检查越界1、引文改写2、顺序倒退1、省略分工边界1。越界机制实际出现3次，其中HT06两轮与汇报分类重叠，因此不能把各机制次数直接相加。

关键新证据：HT05/HT06四次初始检查认可completed/existing及全部六事件字段，却同时把record判context_only；history.tasks确实传入，并非旧任务未加载。C17/P11a文字仍保留，丢的是结构化报告。三次再检查的额外键均来自只读context_records；请求实际为json_object，schema位于提示数据中，本地才强制校验。PF02不存在的引用、CP07重抄旧引用删词、C14顺序倒退及三次再检查越界共6次均离线复现，内存定点纠正后对应结构校验通过，未修改生产代码或计为案例通过。C03短切片缺前导分工句，单列为省略恢复及输入/标签边界问题，避免将其当成无歧义直接指令。

## 目前具体问题

22次失败：11次场景网络故障、3次再检查输出越界、3次追踪证据或顺序错误、5次任务/汇报语义错误。每例的详细因果和原始文件在全量结果及source-review-notes.json。

优先处理共同语义原因：HT05/HT06、C17/P11a 把“没有新任务”误当“只有背景”，丢失旧任务完成/进展类型或确认入口。HT06两轮新支付任务正确但旧登录任务未更新，且再检查多返回只读记录字段。C03第一轮漏UI技术功能任务、第二轮恢复；完整上下文两轮保留。

协议故障已具体溯源：CP02/HT06三次check_repair超出目标记录；PF02第一轮引用改写后不存在的连续字符串；CP07第二轮删掉旧引文中的“怎么”却沿用位置；C14第二轮线程位置0、3、5、4倒退。不能继续把PF02称为重复引文，也不能把这些故障都归到introduced_by。

独立终审另发现确定性的 Service 集成缺陷：service.py:167 独立事件分支漏掉 context-v5。同人同段旧任务完成 + 新任务自承接，即使抽取正确，也触发 create_update_conflict，同时阻断两项写入。离线复现脚本与输出在 runs/2026-11-16-context-v5-full/review/reproduce_shared_evidence_conflict.py / .json，v4 对照成功，v5 旧任务仍open且无新任务，0模型调用。190次中该分支未触发，单列发现、不改分母。生产代码尚未修复；后续优先补策略接入和同段创建/更新服务回归。

M2与正例完整服务链4/4、补充12/12、C23及两种目的对照6/6。结果支持五项改动的核心行为，但不支持全量稳定或默认切换。

## 复现与后续

    $env:PYTHONIOENCODING='utf-8'
    python experiments/task-boundary/summarize_full_context_v5.py --out runs/2026-11-16-context-v5-full
    python -m unittest discover -s tests
    python -m unittest discover -s experiments/task-boundary -p 'test*.py'

新全量运行使用 run_full_context_v5.py --out runs/<全新目录> --workers 4。当前 runner 保留启动时冻结的 P03a/P12a 原规则；重跑前应显式迁移 policy-overlay.json 的用户裁定，不能把旧自动总分直接作为现行得分。

此轮只增加/调整评测入口、汇总与文档，未修复全量中发现的新算法缺陷。用户要求的11次网络失败恢复已完成；下一步优先修复服务策略接入遗漏和完成/进展汇报分类，再约束再检查目标和追踪历史复述。各次失败保留，新试验用新目录。

项目根目录 D:/HuaweiMoveData/Users/13736/Desktop/Remote_Intern/ByteDance/feishu-meeting-eval。Python标准库、无Git。模型deepseek-flash，配置 experiments/action-context/compact-check.json；凭据沿用上两级 meeting-agent/.env，勿打印或复制。不得覆盖fixtures、历史失败输出或历史评分。
