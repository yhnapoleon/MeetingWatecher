# context-v2 实施与验证

**Goal:** 实施 m2-repair-validation.md 第 4 节的修复方案，接通结构核验、一次遗漏修正、再核验和 Service 输出，完成关键样例及受影响回归。
**Spec:** ../specs/2026-11-15-m2-system-design.md
**Architecture:** 新增可选择的 context-v2；复用既有跟踪、事件规范化、更新/权限/持久化逻辑，使用独立版本核验及遗漏协议。旧版本继续可读。仅标准库。
**Execution:** executing-plans + TDD；无 Git，以 before.zip/交付快照和 progress.md 替代提交。

1. [x] 真实 Pipeline 的失败测试：纯遗漏触发、新增事件身份、拒绝后关闭、同段不同工作、失败再核验与未选中记录保持。
2. [x] 单一结构定义生成提示示例，解释 time.change/other_changes 先结构校验；gap/clarification 一致性、coverage 处置结构独立验证。
3. [x] 实现 context-v2 pipeline/reducer；关联修正目标、一次预算、新增记录/事件身份、退化保护、单一残留展示。
4. [x] 接入 Extractor/Service/CLI 策略，测试有效工作执行、系统争议阻断、幂等与版本隔离；不改变默认 split-v3。
5. [x] 七份关键样例两轮真实模型首次检验；达到门槛后完整 M1→M2/落实正例各两轮；执行受影响语料/对照及全套程序回归。
6. [x] 独立审查，必要修复，报告真实失败、成本与能力边界，更新 HANDOVER。

接口：schema → canonical events/records → check → repair plan（原记录目标+findings）→ fixed canonical events/records+dispositions → recheck → merge → 既有执行规则。新协议只向模型暴露 coverage_findings；旧 uncovered 字段仅为旧 reducer 适配的空列表，不进入新模型协议。

约束：不按段号去重、不清空 reference、proposed_kind 不直接执行；结构失败不能吃掉有效旧任务更新；所有首次失败和恢复分开。关键模型门槛失败时保留该批结果，按具体原因修正并冻结新批次；未经关键检验不以全量调用掩盖错误。审查重点为遗漏关闭与对应关系、修正退化、用户确认前提和真实执行结果。

## 执行结果

实施及计划内检验均已完成。171 项程序测试、最终 14 例离线重放、跨会 M2/落实正例各两轮和 33 对照通过；扩大回归无新增退化门槛未满足，保留可选策略，不替换默认。C19/HT04 仍 partial，C23 有内容遗漏，CP01 有额外背景待审项。完整结果见 [实施与检验报告](../../context-v2-results.md)；首次与恢复分别保留。上方完成标记表示步骤已执行，不表示全量上线门槛通过。
