# Context-v5 系统修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 正确区分真实未决、工作资格和系统失败，并用有界恢复完成可恢复的模型调用。
**Architecture:** 保留现有事实/决策/工作分支；扩展 v5 检查协议保存资格和原异议；纪要单独核验。逻辑阶段通过同一个有界调用器保存尝试和 accepted 产物，技术恢复不修改语义输入或历史证据。
**Tech Stack:** Python 标准库、unittest、SQLite 模拟器、DeepSeek 记录式 API。
**Spec:** ../specs/2026-11-16-context-v5-system-remediation-design.md

## Global Constraints

- 默认 split-v3 不变；新语义与自动恢复只接入 context-v5。
- 无 Git。以 `runs/2026-11-16-context-v5-system-implementation/before-source.zip`、文件差异及 progress.md 替代提交/worktree 记录。
- 原 172/190 和历史目录不可覆盖；每次真实实验使用新目录，保存所有失败与恢复费用。
- 每节点首发＋一次技术恢复；一次语义修正，模型分歧不伪装成用户缺口。
- 命题/当前议题/最终状态分别判断；context_only 不决定 unresolved 去留，调研承接不关闭被调查的未知。
- 新标签在看新输出前冻结，区分必须保留、允许省略与禁止添加。

## Review Focus

- 已接受的研究工作和其真实未知可同时存在：纪要正例与正常入口验证。
- 暂缓事实在工作分支失败时仍可见：分支故障集成测试。
- 原检查可能错：复检允许有原话依据地推翻，不能机械强制改变文本。
- partial 重入、预算变化与中断不能重置恢复次数或重复平台写入。
- 失败缓存与成功 accepted 区分；费用未知不写零、技术成功不当语义通过。

## Task 1: 确定性问题与修正契约

Files: context_state.py、context_v3.py、context_v2.py、context_protocol_v5.py、context_v5.py、context_coverage.py；新增 tests/test_context_system.py。

Interfaces: reduce_v3 继续返回现有 review_records；v5 recheck 输入 review_issues，输出 issue_checks，程序固定 ID；旧策略不要求新字段。

- [x] 用保存的 HT04 pipeline 测试“只问关联，缺口与问题一致，items/updates 均空”，观察失败。
- [x] 归约先处理报告与关联缺口，再生成最终问题；去除晚删字段遗留旧问题。
- [x] 用 C11 无修改记录测试“首检异议遗漏不得被新 supported 覆盖”，并测试可有据推翻错误首检。
- [x] 复检携带固定异议，逐项 resolved/overturned/unresolved；未处理异议保留不支持状态。
- [x] 运行相关 context 测试并记录结果。

## Task 2: 有界阶段调用与预算

Files: 新增 meeting_eval/stage_runner.py；model_client.py、context_v5.py；tests/test_stage_recovery.py。

Interfaces: run_stage(client,prompt,payload,stage,validate,folder,inference) -> validated value；每次尝试保存 request identity、失败类型和状态，接受产物原子提交；v5 _stage 调用该入口，原 v3/v4 保留旧行为。

- [x] 测试 length→32K、坏 JSON→原预算恢复、失败两次后重入不再请求、首 accepted 不重复调用。
- [x] ModelClient 将 finish/parse/transport 分类，支持显式总截止时间和单次请求目录；保存失败响应及 usage，不泄露凭据。
- [x] run_stage 每节点最多两次请求；重入沿 attempt 恢复；length 不传结构修复反馈；输出完整验证后接受。
- [x] 语义修正失败状态显式传播，未通过目标不可执行；保留独立结果。
- [x] 测试真实缓存文件、损坏 accepted、usage unknown，以及原策略兼容。

## Task 3: 工作资格

Files: context_protocol_v5.py、context_v5.py、新增工作资格辅助模块（仅确有复用时）、v5 check/repair 提示；tests/test_context_system.py。

Interfaces: v5 record_check 增加 qualification={speech_scope,work_basis,evidence,adoption_evidence,reason}，转换前验证证据及分类相容；保留 trace 审计。

- [x] 构造 option/mention 被判 work、quoted 无采用、当前完成报告、真实建议等协议正反例。
- [x] 在现有检查中要求资格依据；资格冲突触发分类修正，不能自动发明动作或用户缺口。
- [x] 原未修改模型输出 fixture 按新契约显式补资格，只改测试输入，不放松生产验证。
- [x] 跑 context 相关测试。

## Task 4: 纪要命题核验

Files: 新增 minutes_review.py、纪要检查/修正提示；extract.py、service.py；tests/test_minutes_review.py。

Interfaces: review(meeting,candidates,read_only_context) -> {facts,unresolved,trace,errors}；程序绑定候选 ID，原候选检查与一次修正复检分开；只有最终通过的组可提交。

- [x] 测试已答选择、引用未采用、真实未知角色纠正、部分回答、暂缓+工作失败、未决漏提和模型核验失败。
- [x] 建立内容/本场资格/最终状态检查，发现问题进入固定目标修正；改写与新增必须再检查，不能自改自批。
- [x] 仅 v5 接入，事实/未决原始候选留证；系统失败返回相应 _errors，Service partial 可见。
- [x] 通过核验的暂缓事实独立保留，使用显式已核验 record 关联去重展示。
- [x] 正常 Service 入口验证 independent work/decisions 保留、partial 重入与重复处理。

## Task 5: 冻结标注与实测

Files: 新语义验收数据 semantic-v1.json、新实施实验入口与汇总；各自测试。

- [x] 冻结原6个场景的命题标准及未见对照，记录政策与歧义。
- [x] 离线项目与实验测试全部通过，独立代码审阅后处理重要问题。
- [x] CP01 固定旧前缀 high16K/high32K 各3次对照，C14 固定旧首 ledger 进行恢复验证；区分首发、恢复、最终语义。
- [x] 先小批跑原失败＋关键成功对照，按原话复核；必要迭代保留所有输出。
- [x] 按用户新指示取消95×2；完成12原失败＋8冻结对照的一轮必要测试，仅补跑受空对象适配影响的3例。保留失败并分开报告技术与语义，不与旧全量直接比。
- [x] 更新 HANDOVER、结果报告和用量；保留未解决失败与风险，不能只写通过的部分。

## 实施记录

用户已批准设计并要求实施测试。本计划不再设置中间许可步骤。每任务执行时在 runs 下 progress.md 记录选择、失败测试与最终证据。


2026-11-16 最终实施与限定验收已完成。20例组合12通过、5语义失败、3未完整完成；实施完成不等于全部语义问题已解决。后续以 docs/context-v5-system-implementation-results.md 和 HANDOVER.md 为准。
