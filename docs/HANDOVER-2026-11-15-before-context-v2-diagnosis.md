# 交接：context-v2 已实施，跨会 M2 通过，扩大回归仍有四类问题

更新时间：2026-11-15。最新用户要求：“好，请实施该计划并检验之”。修复方案已接入可选策略 `context-v2`（协议版本 8）；默认仍为 `split-v3`。原始跨会 M1→M2、追加明确落实任务的正例各两轮首次通过，171 项程序测试通过。扩大回归发现 C19、HT04、C23、CP01 四类残留，无新增退化门槛未满足。

## 当前入口

先读[实施与检验报告](context-v2-results.md)、[本轮汇总](../runs/2026-11-15-context-v2/summary.json)和[实施计划](superpowers/plans/2026-11-15-context-v2-implementation.md)。此前调查、设计和原型研究见[系统设计](superpowers/specs/2026-11-15-m2-system-design.md)、[修复方案实验](m2-repair-validation.md)；上一版交接完整保存在[历史版本](HANDOVER-2026-11-15-before-context-v2.md)。

## 已实现和已检验的行为

- `context_protocol.py` 统一必填结构与完整示例，检查缺口、用户确认和覆盖处置的一致性；新模型协议不再混用 uncovered_spans。
- `context_coverage.py` 和 `context_v2.py` 实现纯遗漏也触发的一次修正预算、独立新增记录/事件身份、处置再核验、原有效记录退化保护和单一残留展示。
- Extractor、Service、CLI 已接入。真正的内容/关联待决定事项继续提问；系统解释争议显示为不能直接加任务的 interpretation_unresolved。旧 context-v1 保留，策略切换需要新数据库。
- 七个关键样例修订后两轮各 7/7，最终代码离线重放全部一致。跨会原始 M2 两轮都完成同 GUID 旧任务并保留期限、替代范围决定，零额外任务/问题/finding；落实正例两轮都保留唯一陈可改灰度配置并发测试任务。重复处理、重启、历史及权限检查通过。
- 33 个边界/承接对照首次 33/33。完整 54 例首次 42 processed / 12 partial，其中 11 例网络中断；在副本上各恢复一次后 52 processed / 2 partial。原始请求和首次失败均保留。
- 30 段语料输出 17 项，审计口径 16 项完全正确，精确率 94.1%、召回率 88.9%、整例 28/30。旧任务更新按当前 M2 预期首次 3/13、一次恢复后 12/13。上下文/取消 23 条原冻结标准恢复后通过，但 CP01 额外背景残留单独记为失败。
- 最终全套程序回归 171/171（本轮新增 37 项）；独立审查发现的两项 reducer 错误、再核验提示冲突及新增候选 trace 缺失已修正，审查记录和失败/通过日志保留。

## 下一轮必须面对的具体问题

1. **C19 引用与核验协议**：首次重复短引文缺 occurrence；恢复后核验撤回问句却未给 question issue。仍 partial，没有可用任务。引用 ID 方案尚未实现。
2. **HT04 真实关联歧义**：两个旧任务信息相同，本应请用户选择；核验同时输出 needed/relation 和 blocking_for=none，被一致性检查拒绝。不能靠放松校验消除失败。
3. **C23 输出内容退化**：item 保留联系袁校长，却省略核对未听清内容的具体目的；仅 trace 有背景，按冻结评分仍 content_complete=false。旧版首次完全正确召回 17/18，本轮 16/18。
4. **CP01 背景未关闭**：主要范围与承接正确，但“开关名称未统一”背景留下额外 interpretation_unresolved。没有新增任务仍不等于该例全部通过。

后续优先从核验冗余字段冲突、record/event 两份描述漂移以及背景修正机制找共同原因，先在这四例上验证，再评估是否扩大。不得以清空缺口、直接应用 proposed_kind、改标签或隐藏 unresolved 来提高分数。本轮实现与验证已完成，但全量切换门槛未满足。

## 运行与证据

```powershell
python scripts/replay_mvp.py --out runs/my-context-v2 --strategy context-v2 --inference-config experiments/action-context/compact-check.json
python -m unittest discover -s tests -v
```

使用新的输出目录。批次执行入口为 `experiments/task-boundary/run_context_v2.py`；离线重放和评分分别为 `replay_context_v2.py`、`score_context_v2.py`。输入、源码快照、原始模型记录、SQLite、纪要、测试日志、评分及复核全部保存在 `runs/2026-11-15-context-v2`。本轮 606 次请求尝试，579 次收到响应、27 次传输失败，2,400,037 tokens；恢复新增 48 次请求、181,926 tokens。未进行真实飞书平台写入。
