# 跟踪检查点恢复设计

用户授权：先修复自然会议跟踪阶段失败，调研主流开源方案并移植可用机制。只处理原因1，不调任务语义标签和状态分类。

## 调研与选择

- LangGraph [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)：每步保存、成功节点恢复时复用，sync在下一步前完成持久化。[Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)：有界且按异常区分的重试，节点重跑不等于外部副作用恰好一次。本项目已有accepted.json、节点锁、持久化预算和Service幂等，复用这些机制，不整体迁移框架。
- Pydantic AI [Retries](https://pydantic.dev/docs/ai/core-concepts/retries/) / [Output](https://pydantic.dev/docs/ai/core-concepts/output/)：验证器反馈模型，输出重试受预算限制。本项目已经反馈错误；要同时缩小协议，不能把严格工具输出当作免验证保证。
- LlamaIndex [SentenceSplitter](https://developers.llamaindex.ai/python/framework-api-reference/node_parsers/sentence_splitter/)：按长度及完整语句边界拆分。本项目以完整原始发言为边界，使用UTF-8文本字节数6000和最多128段的确定性上限，不新增tokenizer依赖，不声称它是模型token硬上限。超长单段原样保留，不截断证据。

方案比较：单纯加重试仍承担复杂编号错误和整链成本；整体LangGraph迁移不能修模型协议；选择复用持久化执行器并简化跟踪协议、按内容分块、耗尽后有界缩小窗口。

## 接口与行为

新增跟踪输出只有entities、new_threads、thread_updates。模型给标签、含义、原始segment_id证据和既有线程选择；程序分配所有新增N/T编号、还原逐字证据、以最后证据位置确定更新时间，依原文顺序追加。原始发言编号直接作引用，不再要求模型维护Q编号与原编号两套映射。新线程必须有更新，既有线程必须存在，每次更新至少引用当前新增段落。未通过验证的数据不提交。

ContextV2抽取跟踪hook保留旧行为，ContextV5覆盖hook及协议；解释/核对/收录逻辑及推理配置保持原样，版本及代码哈希更新。

按6000文本字节、128段计划检查点。一个检查点按原run_stage预算失败后，仅内容类耗尽可二分一次（一个根至多三个节点，每节点原有预算）；HTTP、权限、冷却、并发忙等不触发分块请求风暴。成功左半保存后才处理右半。不能跳过失败源段继续声称整场完成。

每步原子写tracking-state.json并向trace暴露total、completed、pending、blocked范围与最后有效ledger。重复调用从相同输入/配置重放缓存，不重新调用已成功节点；叶节点耗尽沿现有Service显式retry入口继续，原授权预算不重置。部分跟踪不得触发interpret或真实任务写入；完整输入后来可能撤销早先工作，所以不能把前缀直接发布。

这里“可靠”指验证后提交、进度不丢、范围可见、可续跑和有限成本，不承诺外部模型永久成功。单段或二分后仍失败时明确保持partial。

## 验证

离线：新编号程序所有权、原发言ID、重复/不存在线程、空更新、历史只读、跨块撤销；检查点密集短回应、长单段；父失败后子成功、叶失败保留前缀、重复调用不耗请求、人工grant续跑、非内容错误不二分。旧下游及Service恢复测试定向回归。

线上：仅GN25/GN26/GN29/GN38，正常Service入口，保留失败及用量；主判断是完整跟踪覆盖、是否进入后续提取、检查点/调用成本。任务结果只作防止跟踪简化吞信息的复核，语义未修复部分如实报告。
