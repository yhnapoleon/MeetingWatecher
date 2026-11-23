# 固定用例与评测证据索引

## 阅读与复核方式

先看本页的分组，再读对应报告的逐条判断。[评测用例索引.csv](evidence/评测用例索引.csv) 记录历史回归每个处理单元的 ID、来源、结果路径、输入/结果哈希和参考数量；它由已保存评分原件提取，不新增标注或模型输出。115 场景对应 117 个处理单元，两个双场链路分别有两次处理，不能把 117 写成会议数。

索引中历史 runs 路径以项目根目录为起点，主要在原工作区存在。GitHub 提供索引和选定文本证据，完整模型响应及 SQLite 不随源码发布。

## 分组、配置与判分

| 组别 | 输入与版本 | 参考与结果目录 | 核心结论 |
| --- | --- | --- | --- |
| 历史回归 | 115 场景、117 单元；当时冻结的 context-v5 配置 | runs/2026-11-17-full-baseline/task-metrics/review-and-score.json | 任务 72/76、72/73；完整字段 70/76、70/73；自然核心 17/21、17/18 |
| 整会重测 | ES2002a/b 434＋977 段；v19＋DecisionReview v2 | runs/2026-11-18-full-v19-retest | 最终任务 7/8、7/7；决定 15/15、10/11；首场含一次失败阶段恢复 |
| 新参会组 | IS1000a/TS3003b 389＋404 段；v19，同领域新组 | runs/2026-11-18-two-unseen-v19 | 内容任务 7/7、7/7；决定 23/23、18/20；含负责人任务 6/7、5/7 |
| 真人跨会 | ES2002b/c 977＋999 段，同库顺序；v19 | runs/2026-11-18-ami-bc-continuity；recovery 保存恢复结果 | 4 项重申，供电只进事实；候选分工未成历史任务，纪要有误关联 |
| 确认定位对照 | 首场结果经正常 API 模拟确认，次场只取 71 段 | runs/2026-11-18-ami-bc-confirmed-probe | 3/3 定位正确、0 新建；Andrew 完成状态需复核 |
| 状态分流与覆盖 | GN29 固定输出回放；GN25 两种核验设置 | runs/2026-11-17-task-routing-coverage | GN29 FP 7→5；GN25 均漏条件支付；另有 GN33 回退 |
| 证据协议恢复 | ES2002a v16 失败原件→v17 恢复 | runs/2026-11-17-full-meeting-ES2002a-protocol-recovery | 三项参考分工保留；新增 5 次请求完成；并非从头推理 |

除历史任务评分原件外，完整运行通常以 input.json、inference.json/config.json、reference.json/rubric-before-run.json、annotations.json、result.json 记录输入、配置、参考、判分和预测。具体文件因实验不同，以各原报告为准。

历史自然片段、构造样例和同源会议已经用于研发；新参会组仍在 AMI 遥控器设计领域。标注与复核由助手依据原文完成，未建立多人一致性金标。各组样本有重叠，不汇总成一个总体泛化分数。

## 原报告入口

- [115 场景任务指标](context-v5-task-metrics.md)：任务、字段、自然核心与更新契约分别计分。
- [v19 两场重测](两场会议重测_v19_任务与决策指标.md)：原文、恢复和前后比较。
- [新参会组语义复核](新会议双场泛化测试_语义复核_v19.md)：内容与负责人伴随指标。
- [真人跨会与确认对照](跨会议真人演示与实测.md)：完整试验与 71 段定位对照。
- [状态分流和条件保留](任务边界与条件保留_实施结果.md)、[回退与未解决项](扩展评测_未解决问题清单.md)。
- [证据协议修复](完整会议证据协议_修复结果.md)。

## 可复算范围

GitHub 克隆后可执行：

```powershell
$env:PYTHONUTF8='1'
python scripts/verify_release_evidence.py
```

此命令核对两场输入、参考和规则的冻结哈希，从逐条判分重算任务与决定计数；判断来自已保存复核，不在命令中重新评审。原 result.json、SQLite 和模型节点不公开，因此只核对判分与汇总记录的结果哈希相同，不声称核验了未提供文件的字节。

以下命令要求完整本地证据，不调用模型：

```powershell
python experiments/task-boundary/score_current_tasks.py --out runs/2026-11-17-full-baseline
python experiments/full-meeting/score_retest.py runs/2026-11-18-full-v19-retest
python experiments/full-meeting/verify_retest.py runs/2026-11-18-full-v19-retest
python experiments/full-meeting/audit_unseen.py runs/2026-11-18-two-unseen-v19/IS1000a
python experiments/full-meeting/audit_unseen.py runs/2026-11-18-two-unseen-v19/TS3003b
```

历史评分脚本可能写回汇总，需要保持归档字节不变时，在完整副本运行。重新汇总不等于重新推理。新模型运行使用[配置说明](CONFIG.md)中的全新输出目录。

## 演示与软件验证

当前双场应用以 AMI 原声与 STT 词轴为输入，实时调用模型形成纪要、任务候选和更新，用户核对后确认。最终视频为 15:13，第二场从 05:32 开始；三项任务保留同一 GUID，共六次确认快照，第二场三次更新且重复新建为零。所选第二场没有明确新分工，新增为 0；新要求和未采纳方案分别显示。

第二场 39 次增量处理生成 8 张议题卡，35 个可见更新状态通过阅读范围检查。33 项 Copilot 测试、前端类型检查、构建及 4 项托管检查通过。成片全量解码与十次正常速度声音抽查通过，关键画面逐项复查。它们验证产品与软件行为，不并入上表的冻结任务识别率。详见[应用验证](第二场AI视图修订_实现与验证.md)及[核查数据](evidence/second-view-v5-2026-11-23.json)。
