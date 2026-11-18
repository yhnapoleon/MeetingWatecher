# context-v5 网络失败恢复结果

2026-11-16，按用户要求，对全量回归中因超时、连接断开和 SSL EOF 中断的 **11 次场景执行**进行恢复。11 次均清除了调用错误；原文复核后 **10 次通过、1 次仍有语义错误**。恢复结果替换对应的网络中断结果后，整体为 **178/190（93.7%）**，两轮分别为 **89/95**。

原始全量首次运行仍为 **168/190（88.4%）**。178/190 是计入定向恢复后的结果，复用了此前成功阶段，不能当成新一轮独立测试的准确率，也不能用它覆盖首次运行的可靠性数据。

## 恢复范围与结果

| 原执行 | 原中断阶段 | 恢复后 |
|---|---|---|
| r1 / corpus / C15 | interpret_work 超时 | 通过；Alima 接受工业设计工作设计 |
| r1 / corpus / C17 | check_work SSL EOF | 调用恢复；完成／进展报告仍缺失，未通过 |
| r1 / pairs / P05b | track_context 超时 | 通过；正确提取小林承接的本园名单核对 |
| r2 / corpus / C11 | interpret_work 超时 | 通过；产品替代方案未生成执行任务 |
| r2 / cancellation / PF02 | track_context 超时 | 通过；只取消春季名单，保留小周的秋季名单 |
| r2 / updates / TU09 | facts 超时、track_context 连接断开 | 通过；试探改期只询问确认，原日期保留 |
| r2 / updates / TU11 | check_work 超时 | 通过；第三方改期等待负责人确认，原日期保留 |
| r2 / pairs / P03b | track_context 超时 | 通过；小林接受从规格表移除图文电视功能 |
| r2 / pairs / P05b | check_work 超时 | 通过；创建本园名单核对任务，无任务追问 |
| r2 / pairs / P06b | check_work SSL EOF | 通过；保留真实需求方向，未虚构执行任务 |
| r2 / pairs / R03 | track_context 超时 | 通过；小林尚未承接，保留候选并只问承接 |

C17 原文包含“已通过邮件发送纪要”和“正在放入共享文件夹”。恢复后这两项信息仍进入普通背景，reports 为空，缺少 completed / progress 类型，因此只算网络恢复，不能算案例通过。此前第二轮 C17 已暴露相同语义问题，本次使第一轮也获得了可判断的结果。

P05b 第二轮保留了原有 facts/unresolved 分支中被引用的培训问句，未把它变成任务或任务复核。该背景未决记录作为观察项保留；本次不追加新评审门槛，也没有重跑已经成功的事实提取阶段。

## 执行方式与证据

沿用同一 context-v5 算法、提示与模型参数，在独立目录复制原场景及 SQLite 状态，通过正常 Service.process 的 partial 恢复入口续跑。成功阶段保留，只对失败阶段重新请求并继续后续处理。并发为 2，每个选中执行只恢复一次；没有重跑语义或协议失败案例，也没有修改生产代码。

新增 **28 次模型请求，28 次均收到响应，199,821 tokens**；这些数字排除了副本中的原始请求。原全量记录逐文件哈希与恢复前一致，恢复输出中的流水线代码摘要也与全量冻结快照一致。33 项实验测试通过。

恢复脚本最初在写汇总时把相对路径传给 relative_to(ROOT)，导致汇总异常；每个场景的 Service 结果、任务状态、操作日志和纪要已先保存，线程池完成了全部 11 次恢复。已将入口路径改为绝对路径，并从保存结果离线重建汇总，没有因此追加模型请求。具体记录见 runner-incident.json，初始脚本快照也保留。

计入恢复后，原全量范围内剩余 **12 次未通过**：6 次结构／证据校验失败、6 次任务／汇报语义错误。此前终审另发现的“同段旧任务更新与新任务创建被误拦截”服务缺陷仍未修改，继续单列，不加入 190 次分母。它们属于后续修复范围，不能靠清除网络错误解决。

恢复证据：[运行目录](../runs/2026-11-16-context-v5-network-recovery/)、[最终统计](../runs/2026-11-16-context-v5-network-recovery/final-report.json)、[逐例原文复核](../runs/2026-11-16-context-v5-network-recovery/source-review-notes.json)。原始结果见 [全量报告](context-v5-full-validation-results.md)。

离线重新汇总：

```powershell
$env:PYTHONIOENCODING='utf-8'
python experiments/task-boundary/summarize_full_network.py --source runs/2026-11-16-context-v5-full --out runs/2026-11-16-context-v5-network-recovery
```
