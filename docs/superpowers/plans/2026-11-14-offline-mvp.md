# 离线会议闭环 Implementation Plan

> 执行方式：superpowers:executing-plans；已有 design.md、HANDOVER.md 及用户开工确认作为范围依据。

**Goal:** 用 CLI 导入真实模型抽取结果，持久化任务及决策，跑通 M1 → 回顾 → M2 与六个状态样例。

**Architecture:** 标准库 Python 包 meeting_eval；导入与模型抽取、SQLite 事件与意图、本地任务适配器、业务服务分开。回放与评分脚本仅在验收侧读取答案。

**Tech Stack:** Python 3.11+、sqlite3、urllib、unittest。

**Spec:** ../../HANDOVER.md、../../design.md。

## Global Constraints

- 公开语料人员引用、会议说话人标签与平台账号分别保留。模型不得读取 labels/expected。
- 开发仅用 21 个 dev 片段；保留原基线与提示词，新运行写独立目录。
- 历史状态按 observed_at 截断，读取仍按当前授权；写操作检查执行权与受众。
- 当前目录无 Git，原地新增文件，不操作同级仓库；用文件与运行产物保存进展。

## Review Focus

- 丢回执后重启：恢复同一意图和 GUID。
- 同名任务、会签汇报：不能误完成另一任务。
- 撤权后的历史查询与共享纪要：不能泄露来源。
- 来源修订：不能自动重复新建；保留待核对版本。
- 同一段多个交付：保留多个本地行动项。

## Task 1：导入、状态存储和任务适配器

Files: meeting_eval/{__init__,store,inputs}.py；tests/test_mvp.py。
Interfaces: normalize(raw, actor, roster) -> dict；Store(path)；Simulator(store).create/get/update。
- [x] 写入并运行状态历史、撤权、只读写入、丢回执重启、身份保留测试，确认缺少实现时失败。
- [x] 实现 source/version、extraction、intent、binding、task_event、decision、audit 表；时间统一 UTC。
- [x] 运行 unittest 验证。

## Task 2：模型抽取及业务服务

Files: meeting_eval/{extract,service}.py；prompts/extract-meeting-v1.txt。
Interfaces: Extractor(env_file, out).extract(meeting, context) -> dict；Service.process(raw, actor, observed_at)；recap/decisions/minutes。
- [x] 写入证据拒绝、同段多任务、歧义关联、跨租户隔离与决策版本测试，运行失败后实现。
- [x] 复用原 credentials，记录请求/响应/用量；任务输出保持现有评分字段。
- [x] 状态变更经持久化意图执行、读回确认。修订保留待核对结果。

## Task 3：CLI、回放和开发集

Files: meeting_eval/__main__.py；scripts/replay_mvp.py、run_meeting_eval.py；README.md、docs/mvp-v1-results.md。
- [x] CLI 暴露 ingest、recap、decisions、minutes、recover。
- [x] 回放调用正常服务入口；独立验收 M1 日期/身份/证据、M2 同 GUID、决策替代、六个集合。
- [x] 真实请求 M1/M2 和开发集，保存 SQLite、纪要、请求响应、操作日志、评分与基线对比。
- [x] unittest 全套、数据校验、新程序回放通过；独立审查并修复关键问题。

## 执行记录

- 开工：设计与实施范围已确认；存储与业务接口按上列签名串联，无独立子项目。
- Task 1/2：身份、持久化、抽取与服务测试先失败后通过；补充权限和恢复故障测试后全套 22 项通过。
- Task 3：全新数据库 runs/2026-11-14-offline-mvp-v2 真实模型回放 12/12；21 个开发片段有效输出，F1 0.70，保留旧基线 0.72。
- Final review：独立审查提出 4 项，均已复现并修复；名册权限、账号映射、恢复当前权限和实际获知时间均有回归测试。
- Ruling：目录没有 Git，采用原地新增模块、版本化运行目录与本文记录；未运行依赖 Git 的 task-start/task-done 或提交步骤。成本是没有提交粒度的版本历史。
- Ruling：源码修订暂存 revision_pending，避免不确定的自动重复建项；代价是修订后的业务变更仍需单独协调。
- Ruling：模拟器使用永久 token；不能据此断言真实飞书跨窗口幂等性，真实适配留至接入阶段验证。
- Ruling：未来生效事件同时按 effective_at 和 observed_at 过滤，已加测试；历史授权始终使用当前范围。
- Minor deferred：无。真实飞书授权、令牌窗口和网络认证按离线范围保留至集成阶段。
