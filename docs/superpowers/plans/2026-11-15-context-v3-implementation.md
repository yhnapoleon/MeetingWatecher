# context-v3 实施计划

Spec: ../specs/2026-11-15-context-v3-design.md
Execution: 本会话实施，最终独立审查。无 Git；before.zip、每批快照和 progress.md 保留版本证据。

1. [x] 先写 tests/test_context_v3.py：通过真实 interpret/check/reducer 复现重复引文、双描述、HT04、派生 issue、完整性遗漏；运行 RED。
2. [x] 新建 context_protocol_v3.py（模型结构与纯适配）、context_v3.py（继承 v2，新增 payload 及反馈）；新提示和共享 need-policy；不改 v2 模块。运行 GREEN 和全套回归。
3. [x] Extractor/Service/CLI 接入可选 context-v3，真实 Service 测试幂等和权限复用，结构恢复测试。
4. [x] 新 runner 调用现有 full/pairs/M2 验证机制；定向两轮，读原文人工复核四例及保护对照；按设计门槛决定扩大。
5. [x] 一次独立代码审查与必要修复；报告首次/恢复/残留、成本、源码快照，更新 HANDOVER。

接口风险：新check必须先由纯函数推导旧check再走旧alignment，不能绕过一致性验证；record描述变更必须进入event并再次核验；Q从原meeting编号，不能按修正子集重新编号；新状态兼容旧reducer但不把真实gap计为内容错误；反馈缓存必须保留成功阶段复用。

执行结果：方案已实现，184 程序测试通过；定向两轮来源复核 24/28，完整跨会和落实正例各两轮通过。定向晋级门槛失败，按设计未扩大到完整语料套件。步骤完成表示已执行及报告，不表示候选版本已可晋级。详见 ../../context-v3-results.md。
