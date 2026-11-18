# 跟踪可靠性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans inline. 不重跑全量。

**Goal:** 简化模型跟踪协议，使失败可拆小、有界恢复、完整持久化且无静默跳段。
**Architecture:** 复用run_stage缓存/预算和Service重试入口；程序管理新增标识和证据位置；ContextV5使用内容分块与一次二分。
**Tech Stack:** Python标准库、既有SQLite模拟器；不引入框架依赖。
**Spec:** docs/superpowers/specs/2026-11-17-tracking-recovery-design.md

## Global Constraints
- 只修原因1；原冻结标签、输入、失败及旧源码快照保留。
- 6000 UTF-8文本字节/128段，一次二分，完整原始发言不可截断。
- 内容失败才二分；失败叶必须显式partial，不发布未核验任务。
- 实测限GN25、GN26、GN29、GN38；原60/115例不全量重跑。

## Review Focus
- 子窗口已成功、后续失败再恢复时不能覆盖历史、重复请求或任务。
- 跨窗口回答/取消仍必须通过全文解释；不能发布未处理尾部的前缀。
- HTTP 402/429等不能被二分当成内容问题扩大调用。
- 持久化块计划和节点缓存的身份必须随代码/参数变化失效。
- 原始段落证据引用、空发言/长单段和完全无任务会议不能误通过缺失覆盖。

### Task 1: 协议与检查点执行
Files: meeting_eval/context_tracking_reliable.py, meeting_eval/context_checkpoints.py, meeting_eval/context_v2.py, meeting_eval/context_v5.py, prompts/track-context-reliable-v1.txt, tests/test_tracking_reliable.py, tests/test_source_recovery.py。
Interfaces: tracking_schema(payload), expand_tracking(raw,payload); plan_ranges(segments,max_bytes=6000,max_segments=128); track_checkpoints(pipeline,meeting,folder,trace,resume=False)。
- [x] 先写失败测试，运行并保存RED日志。
- [x] 实现程序编号、原段ID证据、持久化分块与有界二分，接入ContextV5；旧策略保留原hook实现。
- [x] 验证协议、缓存重启/人工grant/副作用边界及既有相关测试，保存GREEN。未新增真实操作系统掉电注入，不据此作掉电保证。

### Task 2: 定向真实验证与交付
Files: experiments/tracking-recovery/run.py, runs/2026-11-17-tracking-recovery-v2/, docs/tracking-recovery-v2.md, docs/HANDOVER.md。
- [x] 从旧manifest仅取4例，不传标签；保存代码快照和配置，以正常Service执行一轮。
- [x] 审计覆盖、恢复、原子匹配与用量，保留后续阶段及语义失败。
- [x] fresh reviewer按Review Focus审阅；未发现阻断问题。未判断项与执行者裁定见code-review.md。
- [x] 最终必要验证后更新报告和交接，不声称已修所有语义漏召回或泛化通过。

## 执行记录
- Ruling: 用户已明确授权先修原因1，依developer自主推进要求不重复请求设计批准；方案/选择已在commentary说明。局部设计按小范围修复处理。
- Ruling: 当前无Git，保存prechange-source.zip，不使用Git专用脚本/合并或删除记录。所有证据保留本地。
- Ruling: 采用标准库文本字节上限而非新增tokenizer；这不是提供商token硬限制，原始超长单段仍受既有预算机制保护。
- Task 1 evidence: tests-red.txt 中新增8测试先失败；tests-green.txt 8通过；targeted-tests.txt 相关89项通过。之后生产文件未再改动。
- Ruling: 初轮4例遇到HTTP 402，用户明确授权充值后续测。生产终止状态不自动重试；实验resume.py在副本中仅归档402终止节点并用相同Service配置续跑，保留原证据和接受缓存，不清除内容耗尽预算。维护脚本额外验证原件保留、成功metadata保留、只允许最后一次HTTP 402且拒绝400。
- Ruling: 续测入口首次配置预检失败（缺少既有实验标记configure b/none），尚无模型请求。补齐同一初始化后通过，原预检目录保存在resume-preflight，未更改生产逻辑。
- Ruling: 无Git仓库，不适用finishing-a-development-branch的分支合并菜单；用户要求只做必要测试，因此不为技能流程额外运行全量或要求确认。
- Task 2 evidence: 最终4/4跟踪覆盖778段，20个成功节点；3 processed，GN29在interpret_work长度恢复后Q别名引用错误而partial。保持正常预算，不扩大本次范围追加解释协议修改或无限续跑。最终任务10TP/6FP/10FN，局部回归不代表泛化。26份成功metadata哈希和对应请求集合均未变，初轮+续测共51请求/2,935,650已知token，7次归档402无usage。final-verification.json全部断言通过；报告和HANDOVER已更新。
