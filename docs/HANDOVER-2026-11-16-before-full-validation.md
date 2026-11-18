# 交接：五项方案已实现为可选 context-v5，针对性验证完成

更新时间：2026-11-16。用户要求依次调研、设计并检验五项问题。已完成根因核对、实现、三版真实模型试验及独立代码审查。

优先阅读：[结果报告](user-solutions-results.md)、[方案与调研依据](user-solutions-design.md)。上一轮原始溯源见 [review-feedback-diagnosis.md](review-feedback-diagnosis.md)；实施前交接保存在 [before-user-solutions](HANDOVER-2026-11-16-before-user-solutions.md)。

## 当前可用行为

- M2 范围调整保留为工作，保存内部员工、试点客户、今天。已决定但未指定个人用 commitment=decided，保留待分配候选，只问负责人；不虚构个人承接。assigned 仍只问对应负责人是否承接。
- gap_checks 已关闭的字段不会被历史 check.issues 重新打开。问题按真实缺口组合。已核验的新工作 work_window 在展示描述中保留，不改为 deadline。
- deferred_topic 收集明确暂缓的议题，禁止任务事件、缺口、追问。纪要有“待定事项（仅收集）”；无日期任务仍为工作。同会议后文明确推进可转 work；跨会议自动激活尚未实现。
- 修正复用 v4 的 repair_contract/expand_patch，record_id/thread_ids/introduced_by 由程序绑定。
- 首次核验和再核验使用固定 record_id 键及扁平 event_id.field 键，如 E1.work、E1.time。未知/缺失槽位拒绝，分类变化与遗漏进入原修正路径。输出 schema 的 additionalProperties=false 与本地严格校验一致。
- C23 不再强制写推断的补问目的；明确补问和无关背景两个对照仍分别要求保留/不虚构动作。

## 实现位置与状态

默认仍 split-v3。context-v5 已注册为可选 Extractor/CLI 策略，可用 python -m meeting_eval 的 ingest --strategy context-v5；尚未替换默认。

新增 meeting_eval/context_v5.py、context_protocol_v5.py、三个 v5 提示文件。修改 context_state.py、context_new_work.py、context_protocol.py、task_events.py、extract.py、service.py。新契约及 reducer 测试在 tests/test_user_solutions.py。

共用归约器的缺口修复、可见时段、枚举扩展会影响 context/evidence 系列后续运行；历史输出和提示文件未改，不要把旧缓存当成当前实现。默认 split-v3 不使用此任务流水线。模拟器持久化配置变化应使用新数据库。

新策略不增加模型阶段，继续一次解释、核验、必要时一次修正及再核验。没有实际飞书写入，完整入口使用独立 SQLite 模拟器。

## 验证结果与失败保留

证据根目录：runs/2026-11-16-user-solutions。

- live-v1：当前口径 7/10，45 次调用。发现 CP06 缺必要问题、激活案例额外字段、M2 展示丢今天。原评分 G-omitted 仍用了旧数量条件，另存 assessment-overlay.json 修正；原文件未覆盖。
- live-v2：6/10，34 次调用。3 次 JSON 括号错误，1 次把 candidate_guids 写进核验输出。已移除继承提示中的错位要求、展平事件核验槽位。
- live-v3：同一最终算法两轮，各 10/10，共 20/20，88 次调用。8 个任务分支案例与2个完整入口；仅 G-omitted 冻结旧追踪/解释以测补回，其余从完整流水线/Service 运行。包含4次完整 M1→M2流程。
- 205 项项目测试、30 项实验测试全部通过。独立代码复审通过；时间展示和评估迁移两个发现已处理。
- 总计167次调用、1,017,206 tokens，0自动重试。全部收到响应不等于全部通过；失败批次完整保留。
- C23历史12份重评属于前轮评分口径变更，不是本轮模型提升。本轮source-review.json为助手原文复核，不是独立人工真值。

最终纪要展示标签将仅缺owner的supported工作显示为“已明确工作（待分配）”。模型测试结束后对4个保存数据库只读重渲染8份纪要，位于 final-minutes/，没有追加模型调用或任务变更。原 live-v3 纪要保留。

live-v1/source.zip 为运行后重建快照，只还原一次运行中落盘的问句文案变化；source-audit.json验证全部模型配置代码摘要一致。live-v2/live-v3 的 source.zip 均在运行前创建。最终工作区快照与测试记录见 final-source/ 和 tests-verification.json。

## 复现

    $env:PYTHONIOENCODING='utf-8'
    python -m unittest discover -s tests
    python -m unittest discover -s experiments/task-boundary -p 'test*.py'
    python experiments/task-boundary/verify_user_solutions.py --out runs/new-user-solutions --rounds 2

summarize_user_solutions.py 为已完成这批试验的离线证据汇总，不是通用语义评委。复核笔记与输出哈希在 source-review.json，汇总在 verification-summary.json。

项目根目录 D:/HuaweiMoveData/Users/13736/Desktop/Remote_Intern/ByteDance/feishu-meeting-eval。Python标准库、无Git。模型deepseek-flash，配置 experiments/action-context/compact-check.json；凭据沿用上两级 meeting-agent/.env，勿打印或复制。新试验使用新目录/数据库，不覆盖 fixtures、失败输出或历史评分。

## 后续边界

本次五项调研、方案与针对性验证已完成。继续工作时先由实际需求决定是否扩大到完整语料回归、跨会议待定事项激活或默认切换，不把20/20当成全量稳定性证明。旧“范围调整必须零任务”和“C23必须写推断目的”规则继续作废。
