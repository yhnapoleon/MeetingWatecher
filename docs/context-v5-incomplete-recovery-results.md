# 三个未完成项：恢复机制与事项收录结果

2026-11-17。C14、SV17 已完成工作分支处理；SV05 的讲义版本问题已持久收录，可凭稳定 ID 查询。正常对照 SV10 保留并创建了两项工作。**90 项离线专项通过，3 个目标＋1 个正常对照通过本轮功能验收。** 默认策略仍为 split-v3，新增机制用于可选的 context-v5。

本轮按用户要求优先解决未完成和事项落袋。C11、C24、P08b、CP01、SV15 五项语义问题暂缓，未针对它们调优或重测。本轮四例结果不能换算成新的全量准确率。

## 从失败响应到可用结果

C14 旧响应已经给出条件性调查的内容和证据，却在 `record_checks` 结束处少了闭合符；第二次工具输出又把 `checks` 等根字段放入了 `record_checks`。SV17 两份旧响应也在相同边界缺少闭合符。原来只能重新调用模型，两个机会用尽后整组工作无法交付。

现在先检查完整结束的响应，只允许两种结构恢复：在已知协议根字段前插入一个缺失的 `}`，或把误放在 `record_checks` 中的已知根字段移回根。候选必须唯一，且继续通过原 schema、scope、身份、证据、转换与业务校验。重复键、缺值、截断、歧义候选均拒绝；不补判断、负责人、期限或证据。

四份历史失败响应已通过离线全链路重放：C14 仍是带条件的候选工作，SV17 仍是暂缓事项，均不自动建任务。原响应、规范化结果及哈希分别保存，`accepted` 记录引用真正验证过的候选文件；损坏或中断后可按此指针重建。

真实 SV10 的首检也出现缺闭合符，程序在字符位置 892 恢复一个 `}` 后通过完整校验，同一节点只请求一次，海报发送与文稿修改后发送两项工作均成功落库。这提供了历史重放之外的一次实际恢复证据。

## 分类恢复与节点续跑

自动阶段最多两次内容生成，另有两次传输恢复机会，总请求不超过四次。传输失败重复同一份请求，不挤占内容重生成机会。length 可升至 32K 一次；结构错误保持原预算，并可在官方接口使用工具契约恢复。普通 JSON 与工具模式各只发送一份输出契约。

429、可恢复 5xx、连接中断进入传输恢复，遵守 Retry-After；长冷却持久化为 `waiting_retry`。402、401、403 和明确请求契约错误进入 `terminal_error`。耗尽保存为 `recovery_required`，普通重复处理不清零额度。意外程序错误不会被当成格式错误反复请求。

每次请求先预留次数及时间，再发起网络调用；单次至多 300 秒，累计实际请求时间至多 600 秒。冷却和离线时间不计入请求耗时。中断且没有可恢复耗时记录时，保守扣除预留时间。节点使用非阻塞 OS 锁，进程退出自动释放；并发调用返回正在处理状态。SQLite 只用短事务登记授权，不跨网络持有事务。

服务接口：

```python
# sid 来自 process 返回的 source_id；viewer/actor 使用现有授权身份。
issues = service.collected_issues(sid, viewer)
result = service.retry_extraction(sid, actor, retry_id, observed_at)
```

`retry_extraction` 仅给可恢复的耗尽节点登记一个持久化批次，最多增加两次请求，节点历史总计不超过六次。相同 ID 重放返回当前结果；换 ID 也不能重置已使用的额度。来源版本、执行身份和冻结历史权限需重新校验。若授权提交后进程崩溃，普通 `process` 可读取授权继续，成功祖先仍复用。600 秒累计上限对人工续跑也生效，已耗尽时间的节点不会因授权获得额外时间。

## SV05 的事项落袋

SV05 原有 `unresolved` 已经正确保留讲义版本未知；阻塞来自另一条工作分类冲突。本轮将已通过纪要核验的命题写入同一份 `sources.result.collected_issues`，无需额外模型调用或另建任务库。

实际记录为：

- ID：`I-e3c7f93635e5c975e32b`。
- 命题：明天培训使用哪个版本的讲义仍未确定。
- 证据：`SV05.1`、`SV05.3`。
- 状态：`retention_state=collected`、`resolution_state=open`、`can_add_task=false`。

纪要显示“已收录·待确定”，重开数据库后仍可查询，重复处理不生成新 ID；新来源版本使用不同 ID，撤销来源权限后不能读取。教室地点已经答复，不被重复列为未决。工作分类仍为 `interpretation_unresolved`，单独作为系统诊断保留；这不代表模型分类已修复，也不妨碍可靠问题被收录。同一段有真实工作和未知问题时，两者均保留。

## 实际验证与用量

| 样例 | 本轮观察 | 结果 | 修正后新增请求 | 已知 token 合计（含首轮） |
|---|---|---|---:|---:|
| C14 | 条件性调研和原条件引文保留，无自动任务 | 通过 | 4 | 52,696 |
| SV17 | 下周再议保留，无立即工作或当前待答问题 | 通过 | 3 | 21,036 |
| SV05 | 讲义版本问题稳定收录，教室已答，诊断保留 | 通过事项收录验收 | 5 | 50,250 |
| SV10 | 小林承接的两项工作均创建，今天完成 | 通过 | 3 | 29,626 |

首轮共 16 个请求，四例的 `track_context` 各遇到一次 HTTP 400：删除重复契约文本后，请求中缺少官方 JSON 模式要求的“JSON”字样。错误正文明确记录了原因，节点停止，没有盲重试。已在 ModelClient 的请求边界补充 JSON 输出指令，且新增失败请求形态测试。

首轮目录 `live` 保持不变。修正后的 `live-contract-fix` 是有来源与配置哈希记录的实验副本，只重进失败的工作依赖组，新增 15 个请求。已接受的 facts、decisions、unresolved 与纪要核验结果逐字段断言不变；生产 Service 的配置变更屏障仍保留。

两阶段总计 **31 个真实请求、153,608 个已知 token，4 个 HTTP 400 请求用量未知**。副本中继承的首轮记录不重复计费或计数。四例最终均为 processed；重复 process 新增请求为零、任务事件写入为零。实际模型阶段没有触发新的请求级重试，SV10 发生一次本地规范化。429、超时、内容恢复、人工批次、并发和崩溃边界由故障注入专项验证，不能把本次实测表述为它们都在真实网络中发生过。

独立代码复核发现的 Content-Length 截断及缓慢 HTTP 错误正文绕过总期限，均经本地服务器复现、修复并验证。最终 90 项专项涵盖结构恢复、失败分类、全部次数上限、未知耗时预留、稳定收录、权限、并发及已有需求确认路径。未跑 95×2 或新的 20 例全量。

任务落库使用项目既有 SQLite Simulator，没有向真实飞书创建任务。SV17 为复用此前已接受的纪要，当前在事实区和暂缓区各保留一条相同议题；这不影响暂缓语义与禁止立即执行，但跨分支展示去重尚未追加处理。

## 证据与复现入口

- [最终自动验收与用量](../runs/2026-11-17-incomplete-recovery/live-contract-fix/summary.json)、[逐例原文复核](../runs/2026-11-17-incomplete-recovery/semantic-review.md)。
- [90 项专项记录](../runs/2026-11-17-incomplete-recovery/offline-tests.txt)、[独立复核及修正](../runs/2026-11-17-incomplete-recovery/review-report.md)。
- `runs/2026-11-17-incomplete-recovery/` 保留原响应、初次失败、前后源码快照、差异和哈希。`tested-source-contract-fix.zip` 是当前验证源码快照，属于内部复现证据。

无需模型的关键复现：

```powershell
python -m unittest discover -s tests -p test_recorded_check_replay.py
python -m unittest discover -s tests -p test_recovery_policy.py
python -m unittest discover -s tests -p test_source_recovery.py
python -m unittest discover -s tests -p test_issue_collection.py
```

需要重新验证模型时，入口固定为四例，必须使用新的输出目录：`python experiments/task-boundary/run_incomplete_recovery.py --out runs/new-four-case-run`。本次已完成，不需要为复核报告再次调用模型。
