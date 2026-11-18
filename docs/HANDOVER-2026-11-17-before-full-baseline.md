# 交接：三个未完成项已完成本轮功能验收

更新时间：2026-11-17。项目根目录：`D:/HuaweiMoveData/Users/13736/Desktop/Remote_Intern/ByteDance/feishu-meeting-eval`。默认仍为 split-v3，context-v5 是可选策略。

本轮优先处理 C14、SV17 的失败恢复，以及 SV05 的事项落袋。**90项离线专项通过；C14、SV17、SV05及正常对照SV10通过本轮功能验收。** SV05工作分类仍为 interpretation_unresolved，但可靠的讲义版本问题已稳定收录、可查询；没有把它称为语义分类修复。五个既有语义错误按用户要求暂缓，未逐例调优或重测。

## 优先阅读

1. [本轮实施与测试报告](context-v5-incomplete-recovery-results.md)：具体恢复边界、Service入口、四例结果和真实用量。
2. [四例原文复核](../runs/2026-11-17-incomplete-recovery/semantic-review.md)、[最终自动验收](../runs/2026-11-17-incomplete-recovery/live-contract-fix/summary.json)。
3. [90项专项记录](../runs/2026-11-17-incomplete-recovery/offline-tests.txt)、[整体代码复核与修正](../runs/2026-11-17-incomplete-recovery/review-report.md)。
4. [已执行计划](superpowers/plans/2026-11-17-incomplete-recovery-and-collection.md)。

## 当前结果

| 场景 | 结果 |
|---|---|
| C14 | 条件性调研成功保留，带原条件引文，不自动建任务 |
| SV17 | 下周再议及禁止立即推进保留；无立即工作、任务或当前待答问题 |
| SV05 | 讲义版本问题收录一条，ID为 I-e3c7f93635e5c975e32b；教室已答，工作分类诊断单列 |
| SV10 | 海报发送、修改文稿时间后发送两项工作均创建；实际发生一次本地结构恢复，无追加模型请求 |

四例重开数据库后可读取收录结果，重复process新增模型请求及任务写入均为零。任务写入是项目既有SQLite Simulator，未向真实飞书写入。SV17因复用工作分支曾失败时已接受的纪要，事实区与暂缓区各保留同一议题；展示去重没有追加处理。

## 已实现机制

- 仅为v5 check_work/check_repair规范化唯一可确定的容器错误：一个缺失闭合符或已知协议根字段错层级。原始响应和候选分别保存，完整身份、scope、schema和证据校验仍执行。四份C14/SV17历史失败响应离线恢复通过。
- 内容生成、传输恢复分别计数；自动最多4个物理请求。显式Service.retry_extraction可为每个耗尽节点登记一次恢复批次，最多增加2次，历史总计不超过6次。重复retry_id或换ID均不能清零额度。
- 单请求300秒、累计实际请求600秒，未知中断预留时间保守扣除；人工批次不扩大累计时间上限。节点OS锁避免并发重复请求，SQLite短事务登记授权，网络调用不持有数据库事务。
- waiting_retry / recovery_required / terminal_error分别表示冷却、可恢复耗尽和终止；HTTP错误摘要脱敏保存。Content-Length中断和缓慢HTTP错误正文均有定向测试。
- Service.collected_issues(sid, viewer)从sources.result读取已核验未决事项；稳定ID按来源版本、命题和证据生成，沿用来源权限，不补负责人或建任务。
- 授权提交后若崩溃，同retry_id调用返回当前状态；普通process可读取已登记授权继续。成功祖先复用，任务intent保持幂等。

## 本轮测试边界与证据

首轮四例的track_context因删掉重复契约后缺少接口要求的JSON字样，均被HTTP400拒绝。原`live`完整保留；修正请求边界后仅在`live-contract-fix`实验副本续跑失败工作组。成功的facts、decisions、unresolved与纪要核验逐字段不变，生产配置变更屏障没有放宽。

总计31个真实请求、153,608个已知token，4个HTTP400请求用量未知。实验副本继承的记录只计一次；其中修正后新增15个请求。四例最终processed，保留的4个terminal_error属于首轮历史失败，不是最终未完成节点。

证据根目录为`runs/2026-11-17-incomplete-recovery/`。保留before-source.zip、首轮tested-source.zip、最终tested-source-contract-fix.zip及哈希/差异；没有改旧标注、删失败或重跑挑最好结果。当前没有运行中的模型任务。

## 后续范围

C11/C24（备选或转述被当作当前工作）、P08b（调查者与能力主体混淆）、CP01（背景问题升为当前未决）、SV15（真实未知漏入unresolved）仍作为模型能力和思考预算边界保留。本轮不据此宣称系统语义全部正确，也不重算旧20例/95×2成绩。

用户明确要求：**只跑必要测试，不要每次跑全量。** 若继续开发，先跑受影响的离线专项；真实验证须显式限定样例和新输出目录。本轮固定四例入口：

```powershell
python experiments/task-boundary/run_incomplete_recovery.py --out runs/new-four-case-run
python -m unittest discover -s tests -p test_stage_recovery.py
python -m unittest discover -s tests -p test_source_recovery.py
python -m unittest discover -s tests -p test_issue_collection.py
```

模型为deepseek-flash，凭据沿用上两级`meeting-agent/.env`，不要输出或复制。环境为PowerShell、Python标准库、无Git。

上一阶段的12通过/5语义错误/3未完成及业务政策见[实施前交接](HANDOVER-2026-11-17-before-incomplete-recovery.md)和[上一阶段报告](context-v5-system-implementation-results.md)。原95×2结果属于更早历史，不能作为当前源码的新全量成绩。
