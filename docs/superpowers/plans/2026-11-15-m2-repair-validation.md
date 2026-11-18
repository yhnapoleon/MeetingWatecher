# M2 修复方案验证计划

> 使用 executing-plans 在当前会话实施；本仓库无 Git，以隔离实验目录、源码快照和 progress.md 记录代替 worktree/commit。生产接入由端到端结果决定。

**Goal:** 为跨会 M2 选出有证据支持的修复路径，交付可复现实验、遗漏处置契约原型及明确的接入门槛。
**Architecture:** 先分别验证语义分类与确定性状态流；不把关闭确认当成分类正确。阶段实验通过才考虑接入 Service。
**Tech Stack:** Python unittest、现有 ModelClient/ContextPipeline、DeepSeek 当前配置、本地 SQLite。
**Spec:** ../specs/2026-11-15-m2-system-design.md

## 全局约束

- 原始输入、历史权限、模型及预算冻结；两次首次结果全部计入，结构失败与 unresolved 计失败。
- C3 仅比较前序解释是否可见，16 次调用；按既定晋级条件决定后续，不追加抽样挑结果。
- 原型放在 experiments/task-boundary，不改生产默认策略。保留任务、确认、未解决含义、遗漏、决定和历史更新六层判断。
- 覆盖身份不能只用段号；同段第二项工作、无失败记录的遗漏、首次受支持记录退化必须受测。
- 若阶段方案未晋级，交付实测负结果与下一步最小实验；不得宣称 M2 已修复。

## Task 1：冻结与 C3 分类对照

- [x] 保存源码快照、四份输入、提示和配置；运行前冻结逐例语义评分标准。
- [x] 新建 classify-v1.txt 与 run_repair_study.py：同输入 visible/blind，各两轮，保存请求、响应、失败与用量。
- [x] 检查 request 只有 upstream 字段不同；人工逐例评分，执行预定晋级门槛。

接口：分类记录使用局部 ID、kind、description、Q evidence、clarification、gap_checks；不输出平台操作。
验证：16 个首次结果都有记录；模型调用与保存元数据一致，未知证据和矛盾澄清结构不计通过。

## Task 2：遗漏与澄清契约原型

- [x] 先写行为失败测试：仅遗漏也触发修正；同段不同工作不合并；有效新增可关闭；失败新增/退化/结构失败不关闭；未选择记录保持。
- [x] 实现纯函数 repair_contract.py，明确输入已经过模型含义核验，原型自身不做语义判断。
- [x] 缺口路由验证：真实对象竞争阻断、普通省略不阻断、负责人缺口保留候选、分类争议不伪装成用户缺口。

接口：plan_repair 固定 targets/findings 与新增命名空间；apply_repair 合并一次核验结果；route_record 只消费已核验的 gap_checks。
验证：先 RED 后 GREEN；失效处置仍保留唯一 finding_id，不能无依据关闭。

## Task 3：决策、复核与交接

- [x] 根据 C3 门槛选择相同后续合并实验，或明确否决本批 C3 晋级。
- [x] 若两组同样正确或不晋级，比较更简单的现有阶段提示调整：冻结旧初始解释，核验关键样例与相邻保护样例，不直接采用分类额外调用。
- [x] 运行既有 unittest 回归；新原型单独运行；核对生产文件 hash、调用数与所有首次失败。
- [x] fresh-context 整体审查；修正重要问题；编写独立验证报告、更新 HANDOVER。

Review focus：评测是否泄漏答案、是否把未解决问题移列算成功、是否通过清空 reference/共享段号吞任务、是否把阶段正确写成端到端通过。
