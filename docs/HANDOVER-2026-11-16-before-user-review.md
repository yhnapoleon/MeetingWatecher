# 交接：统一复评完成，A 正常入口 2/4，来源清单实验不晋级

更新时间：2026-11-16。用户已批准按上一版建议执行统一复评、小范围机制验证、A 正常入口验证和 C23 独立审查。本轮均已完成。**A 尚不稳定；新增独立来源清单 D 未改善最终产物，停止扩大。下一轮优先处理已发现工作在修正/再核验/合并中的协议失败。**

本轮报告：[统一复评与独立工作发现实验](baseline-reassessment-results.md)。全部结果：[总汇总](../runs/2026-11-16-baseline-reassessment/summary.json)。上一版完整交接保存在 [本轮前交接](HANDOVER-2026-11-16-before-baseline-reassessment.md)，其中包含 v1—v4 历史、M2/C23 原始问题与复现约束。

## 1. 项目与代码现状

会议行动项与决策追踪离线 MVP 已支持：真实模型提取带证据的任务/候选/决策、SQLite 模拟任务平台、会前回顾、跨会完成同一旧任务、决定替代、历史查询、权限隔离、幂等与重启。尚未集成真实飞书读写。

项目根目录：D:/HuaweiMoveData/Users/13736/Desktop/Remote_Intern/ByteDance/feishu-meeting-eval。Windows PowerShell，Python 标准库，无 Git 仓库；每批运行以 source.zip、配置与原始请求作为版本依据。

默认仍为 split-v3。v1/v2/v3/v4 均保留。**本轮没有改生产源码或生产提示**：49 个相关文件与 v4 final-source.zip 字节一致。新增内容限于实验 runner、来源清单提示、实验边界测试和文档。A、D 均未注册为 Service 的独立生产策略。

## 2. 本轮得到的比较结果

| 比较口径 | 结果 | 可以支持的判断 |
| --- | --- | --- |
| 对昨日 v2/v3/v4 各四次 Service 回放，统一补查 M1/M2 解释残留、修正与提取错误 | v2 4/4，v3 3/4，v4 2/4 | 原先仅看 M2 会漏掉 M1 问题；这是离线复评，旧 DB/权限/幂等检查继承记录，未重新运行 |
| 本日同批冻结上游，M2/落实正例/已有第二工作/遗漏第二工作，各两轮 | A 5/8，D 4/8 | D 没有带来最终收益；两者遗漏工作最终均 0/2 |
| A 真实正常入口，跟踪→解释→核验→Service/SQLite | 普通跨会 0/2，明确落实正例 2/2，总计 2/4 | A 可以走通核心路径，但尚不是稳定的新基线 |
| C23 独立盲审 | 原文与改写的目的关系存在标签边界争议；明确目的正例和无关背景反例边界清楚 | 保留原分数，不将改标签算作模型提升 |

A 是 run_context_v4.py 中的 PromptOnly(ContextV3Pipeline)，即 v3 加少量核验提示补充。普通 --strategy context-v3 不自动包含 A。D 是本轮实验原型：在 A 首次核验前提供只看原文/授权历史得到的工作清单，再由原核验和修正流程裁定。

历史 v2 的 4/4 不能掩盖其 C19、HT04、CP01、C23 扩大回归问题；v3 在其中部分样例已有改善。继续开发可保留 v3 代码基础，同时保留 v2 历史跨会强对照。没有完成全版本同日、同输入、同轮数的综合排名。

历史 30 段语料的强基线仍是 context-v1 协议 7 task-boundary 最终版：首次完全正确任务 17/18、整段 29/30；一次结构恢复后 18/18、30/30。它仍有任务级指标未覆盖的范围伪任务/多余确认问题。复现须使用当次 source.zip，不能用今天同名策略替代历史共享代码。

## 3. 新定位：不是所有没产出都因为没发现

原文同段追加：“另外，陈可今天下班前把测试结果发给客服。”冻结 G-omitted 故意省去其任务记录。

- 本批 A 两轮都正确发现遗漏，均进入修正。A-r1 修正和再核验内容正确，但新记录缺 introduced_by，合并失败；A-r2 再核验多输出只读记录，Incomplete record checks。
- D 两个来源清单都发现了发送工作，但最终仍失败：第一轮修正输出只读记录，Unknown requirement thread；第二轮首次核验漏事件检查，Incomplete event checks。
- 六份 D 来源清单全把范围决定列为 works。来源阶段本身仍误分类，M2 两轮最终均失败，不能将独立读取原文当作可靠真值。
- 只读核对确认，本批 A 八份首次核验请求与上一批 A 对应例完全相同，模型标识/fingerprint 也一致，结果仍波动。历史三轮 A 没发现 G-omitted，本批两轮发现了；不要用一批小样本断言固定因果。

额外零模型调用定位：[binding-counterfactual.json](../runs/2026-11-16-baseline-reassessment/binding-counterfactual.json)。复用 A-r1 原修正和再核验，仅给 R_O1_1 补 introduced_by=O1，现有 apply_repair 从 invalid 变为 checked，遗漏清零。**这是离线单字段干预，不是模型修复成功，也不是 Service 通过；原失败分数未改。**

## 4. A 正常入口失败位置

| 运行 | 最终结果 |
| --- | --- |
| a-cross-r1 | M2 同 GUID 完成、期限保留、决定替代通过；M1 仅需再核验 R2，却输出 R1/R3/R2，留下解释未解决 |
| a-cross-r2 | M1 同上；M2 首次核验 Incomplete event checks，提取 partial，旧任务未完成 |
| a-positive-r1 | 完整通过，无解释残留 |
| a-positive-r2 | 完整通过；M1 修正成功，落实任务与旧任务更新正确 |

四次使用新目录和新数据库；实际 trace protocol 均为 context-v3-coverage-prompt-control，确认 A 适配确实进入正常流水线。评估保留 facts/decisions、权限、历史、重复处理与重启检查。只读检查原任务 due_text 保留；cross-r2 没完成更新，不能将“期限没改”当成功。

## 5. C23 的处理原则

独立审查先看原话，后看旧标签与对照。其判断是：会后联系袁校长是明确工作，联系可能为了继续沟通并处理未听清内容；但“补问未听清内容”是否必须写入任务，属于原文的语用解释边界。

旧分数全部保留。后续应先明确评测要求，把明确目的 C23-explicit 和明确无关背景 C23-unrelated 作为稳定对照，将原文/改写的语用关系另列审查。不能以增加“信号”关键词算通过，也不能以本次标签质疑宣布旧模型已经提高。

[独立审查记录](../runs/2026-11-16-baseline-reassessment/independent-review.md)保留先于标签阅读的原始判定。

## 6. 下一步应做什么

1. 先对已记录的成功语义、失败结构做离线复现：新增记录 finding 绑定；修正只允许选中记录及合法新增；再核验只覆盖当前 records/events，context_records 只读。
2. 由程序绑定确定性身份/范围时，保留真实语义核验和失败记录。不能通过清空遗漏、过滤解释争议或放宽一致性检查提高分数。
3. 单独验证修正协议改善后，再跑 A 的普通跨会及遗漏工作小集。决定/实施和 M1 延期议题的语义判断仍要保留独立对照，结构正确不能替语义得分。
4. 小集过门槛后再扩大。v3/v4/A/D 都不能据本轮称全量提升；保留 C19、HT04、CP01、CP06 等已验证改动和保护例。
5. 不继续在来源清单或 QA 上堆阶段，不重复整批旧实验。当前最短入口是本轮 A-r1/G-omitted、A-r2/G-omitted 和 a-cross-r1/M1。

## 7. 入口、产物和用量

- 离线复评：experiments/task-boundary/reassess_baselines.py。
- 小集 D 原型及 A 正常入口受控适配：experiments/task-boundary/probe_source_work.py。
- 来源提示：experiments/task-boundary/source-work-inventory.txt。
- 实验边界测试：experiments/task-boundary/test_baseline_reassessment.py。
- 执行计划：[baseline-reassessment](superpowers/plans/2026-11-16-baseline-reassessment.md)。
- 总汇总与每批 source.zip、原始请求/响应、输入/输出、SQLite、语义复核均在 runs/2026-11-16-baseline-reassessment。
- 程序测试：原有 198/198；新增实验边界 4/4。程序通过不代表模型语义修复成功。
- 本轮项目模型 API：**80 次调用，80 次收到响应，454,426 tokens，零恢复调用**。小集 32 次/190,076 tokens；正常入口 48 次/264,350 tokens。token 口径不含 Codex 会话和审查子任务自身用量。

模型仍使用 deepseek-flash 和 experiments/action-context/compact-check.json。凭据在项目上两级 meeting-agent/.env，不复制到文档或日志。所有写入限本地模拟器，无真实飞书写入。

复现离线步骤：
    $env:PYTHONIOENCODING='utf-8'
    python experiments/task-boundary/reassess_baselines.py --out runs/my-offline-reassessment
    python -m unittest discover -s experiments/task-boundary -p test_baseline_reassessment.py -v

需要新的真实模型实验时必须使用新名称。probe_source_work.py --mode small --rounds 2 运行四例 A/D 两轮；--mode cross 或 positive 每次只运行一轮 Service，需不同名称才能重复。旧 run_context_v4.py 的 cross/positive 固定为 v4，传 --arms A 仍不会切到 A。

既有 fixtures 冻结，不再 --prepare，不覆盖历史目录，不在已处理会议的旧库上把缓存命中当重测。本轮完成的是复评与机制验证；未修复生产语义问题，未更改默认策略或旧标签。

