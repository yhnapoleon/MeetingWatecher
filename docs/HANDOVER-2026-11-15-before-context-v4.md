# 最新交接：context-v3 已实施，三类定向问题通过，候选版本未晋级

2026-11-15。用户要求：对残留问题调研、设计、试实施并检验。已新增可选 context-v3（协议 9），保留 v1/v2，默认 split-v3 不变。

先读[实施与检验报告](context-v3-results.md)、[汇总](../runs/2026-11-15-context-v3/summary.json)、[设计](superpowers/specs/2026-11-15-context-v3-design.md)与[实施计划](superpowers/plans/2026-11-15-context-v3-implementation.md)。上轮交接完整保存为[历史版本](HANDOVER-2026-11-15-before-context-v3.md)。

## 当前能力与结果

- 模型只生成一份任务描述；event/item 复用 record.description。单独核验 content.missing_details，并将遗漏明细保留给修正阶段。
- 解释/修正证据使用全会议固定 Q 编号；程序展开精确全段来源。跟踪仍使用原精确引文协议。
- 程序从分类、内容和 gap 判定派生旧内部 verdict/issues/clarification；真实未决事项与解释错误分开。ambiguous 旧任务关联列出至少两个授权选项，保持零执行。
- 跟踪/解释/核验/修正共用潜在需求规则；隐式需求需有来源支持的目标。手工恢复附失败输出和错误反馈，成功阶段复用，自动重试未增加。
- C19、HT04、CP01 各两轮达到目标；CP06 真实需求保护对照也两轮通过。C23 两轮仍失败：item 有信号背景，却未保留核对未听清内容的具体目的。
- 14 个定向例各两轮：可观察契约 26/28，来源语义复核 24/28。最终完整跨会 M1→M2 和明确落实正例各两轮首次通过；权限、历史、重复处理和重启检查通过。
- 全套程序测试 184/184（新增 13 项）。独立代码审查未发现重要实现缺陷，另独立复核五例两轮的来源语义。

## 仍未通过的门槛

1. C23：核验仍认为未听清内容只是背景，missing_details 为空。单一描述解决了数据漂移，没有解决目的关系的语义判断。
2. 隔离 M2 第一轮：范围决定被核验误标遗漏，new_work 同时带 related_record_ids=[R2]，协议拒绝；一次带反馈恢复仍同样失败。第二轮隔离及两轮完整跨会通过，不能覆盖该失败。
3. 同段第二工作 final-r2：真实任务保留，但范围记录核验 kind 与理由不一致，误触发修正；修正返回全部 R1/R2/R3，目标只允许 R2/T2，因未选线程被拒绝，留下额外解释争议。

下一轮优先核对覆盖关系不变量是否在新提示中完整表达、局部修正的确定性身份/范围是否可由程序绑定；C23 单独检验背景与必要目的的关系。保持已有来源评分，不以描述含“信号”就算 C23 正确，不隐藏残留，不直接应用错误 kind。

2026-11-15 后续调研已完成，见[残留问题修复建议](context-v3-remediation-research.md)。已从 M2 实际失败请求确认旧版覆盖关系三条完整规则未保留；建议先对照补齐提示，再采用程序绑定目标的局部补丁和分离覆盖结构。C23 单独实验来源问题到最终任务的必要信息核验。此次未新增模型运行或修改生产实现，以上结果不变。

因定向门槛失败，本轮未扩大到完整 30 语料/33 对照/10 行为/13 更新套件，不能宣称全量召回改善。全部首次、修订和一次恢复均保留。

## 运行与证据

```powershell
python scripts/replay_mvp.py --out runs/my-context-v3 --strategy context-v3 --inference-config experiments/action-context/compact-check.json
python -m unittest discover -s tests -v
```

验证入口 `experiments/task-boundary/run_context_v3.py`，可观察评分 `assess_context_v3.py`，一次副本恢复 `recover_context_v3_focus.py`。请使用新输出目录。所有产物在 `runs/2026-11-15-context-v3`，包含 before.zip、各批次源码、模型原件、SQLite、纪要、评分及审查。真实模型共 203 次调用、1,289,203 tokens；其中恢复新增 1 次、6,315 tokens。203 次均收到响应，无网络失败；没有真实飞书写入。
