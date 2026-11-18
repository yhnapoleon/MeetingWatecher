# 解释阶段引用与输入去重 Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans inline；末尾一次fresh-context只读复核。

**Goal:** GN29在完整跟踪后不再因重复输入与证据编号映射造成可避免的技术中断。
**Architecture:** ContextV5增加模型请求投影和输出引用适配；内部canonical/Q契约保持，模型端仅原始segment_id。run_stage为interpret_work增加一次严格限定的引用补丁，沿用持久化、锁、全局时间与请求上限。
**Tech Stack:** Python标准库，既有Service/SQLiteSimulator。
**Spec:** 用户2026-11-17批准上一轮五点方案；本文件同时固定实施细节。

## Global Constraints
- 全文原样保留一次；已有证据quote通过segment_id/start/end还原，不做模型摘要或裁剪。
- 解释、检查、修复、复核的模型端统一原始ID；旧Q仅内部确定性适配，禁止数字尾号猜测。
- 首轮16K、长度恢复32K；完整且身份可定位的引用错误最多一次8K补丁，正常自动生成最多3次，HTTP及600秒节点总预算仍有界。
- 补丁只能改错误证据数组；不可改语义描述、身份、关联和其他字段；合并后完整校验再走独立语义核对。没有可用证据时显式失败。
- 只实测GN29（冻结已验证tracking前缀）和GN25（正常Service）；标签不传模型，不重跑60/115全量。
- 无Git；保留prechange-source.zip。用户已批准方案，不重复请求批准。不改任务语义规则。

## Review Focus
- 重复引文、多字节文本、同段局部证据与原偏移能精确还原；quote文本中的Q字样不能被改写。
- check/repair绑定scope、资格证据和遗漏证据必须完成双向适配，不发生某一阶段混用ID。
- 先长度耗尽再引用错误时可补一次；坏补丁、重启、并发及HTTP终止不能重置预算。
- 补丁不能通过重复/未知槽、修改身份或其他内容绕过整体语义校验。
- 旧策略契约、缓存身份和Service正常入口保持可用；固定GN29前缀要验证来源和覆盖，不冒充端到端新跟踪。

### Task 1: Wire projection and evidence repair
Files: new meeting_eval/context_wire.py, meeting_eval/reference_repair.py; modify context_v5.py, stage_runner.py; tests/test_context_wire.py, tests/test_reference_repair.py.
Interfaces: wire_request(payload), wire_prompt(prompt,meeting), decode_output(raw,meeting), ReferenceRepair.prepare(raw,payload), ReferenceRepair.merge(raw,request).
- [x] RED：无损投影/原ID往返、未知引用批量定位、受限补丁、预算耗尽后局部补丁、重启不重复调用。
- [x] GREEN：接入ContextV5所有后续阶段，版本和代码哈希更新；增加interpret的有界补丁分支。
- [x] 相关协议、stage_runner与Service离线回归；生产代码只保留必要改动。

### Task 2: Two live cases and delivery
Files: experiments/interpret-reliability/, runs/2026-11-17-interpret-reliability/, docs/interpret-reliability.md, docs/HANDOVER.md.
- [x] GN29固定旧完整跟踪，GN25正常入口；冻结代码和输入，一轮，记录所有失败/成本。
- [x] 复核任务原子匹配及真实输入用量；任务识别与技术完成分开。
- [x] 一次fresh-context只读复核，必要修复做RED/GREEN；最终验证并更新文档。

## Ledger
- Ruling: 字段补丁只支持证据引用类结构错误；其他schema问题和截断仍走原有整阶段恢复。先保留小范围可验证机制。
- Ruling: 补丁请求使用关闭思考的8K预算，保留全文和受影响记录上下文；正常解释仍沿用high推理。额外预算仅在引用错误且未使用补丁时开放。
- Evidence: 9项新增检查先RED；复核修正2项先RED，最终102项相关测试通过。独立复核及裁定见code-review.md。
- Ruling: 既有configure ledger实验工具同时冻结了facts/decisions初抽，本轮GN29的比较范围因此为固定前缀后的解释及纪要复核；如实披露，不将其3次请求当完整会议成本。GN25正常Service另覆盖全链路。
- Ruling: 实测期间修复空补丁和Q ID措辞。保留focus/source.zip与final-source.zip，记录差异；本轮未调用这两条修改路径，核对实际请求提示与最终代码一致，修正仅称离线验证。
- Business outcome NOT PASSED: GN29解释输入151,832→67,484 token，但16K/32K均截断，0/8任务。GN25任务分支通过但条件性支付漏收，2/3；纪要U1未核验，整场partial。合计13调用602,608 token，2TP/0FP/9FN，无外层重跑。不能将候选version15判为GN29修复成功。
- Ruling: 保持本轮预算和两例边界；不在结果不佳后临时增加分片或更高输出额度。下一阶段需单独解决解释输出规模与跨组关系，不改标签追分。默认split-v3保持。
