# 交接：Context-v5 系统机制已实施，定向验收仍有残留失败

2026-11-17 优先级更新：用户要求先修 C14、SV17 的失败/重试机制，以及 SV05 的事项落袋；五个语义错误暂按模型能力与思考预算限制保留，不再逐例调优。新增[三个未完成项实施计划](superpowers/plans/2026-11-17-incomplete-recovery-and-collection.md)，状态为计划已制定、尚未实施。拟先做受限无语义改动的结构恢复、分类重试与节点续跑，再让已核验未决事项持久收录、可查询；只做3目标＋1正常对照的必要验证。下文仍是2026-11-16已完成工作的记录。

更新时间：2026-11-16。项目根目录：`D:/HuaweiMoveData/Users/13736/Desktop/Remote_Intern/ByteDance/feishu-meeting-eval`。

最新用户要求是“调研各自解决方案、实施和测试”，并在充值后明确：**以后只跑必要测试，不要每次跑全量。** 本次采用12个原失败场景＋8个冻结正反例，各一轮；空对象接口适配后仅补跑受影响的C20/SV17/SV19。没有启动原计划95×2全量。

**最新20例定向组合：自动契约15/20；原文复核12通过、5语义错误、3未完整完成。默认仍为split-v3，context-v5可选。** 这些是不同必要迭代中每例最后版本的组合，不是同一快照的全量准确率。不能与旧172/190直接比较，也不能宣称所有旧失败已解决。

优先阅读：

1. [本次实施与测试报告](context-v5-system-implementation-results.md)：具体根因、改法、负结果及未解决项。
2. [最终20例语义复核](../runs/2026-11-16-context-v5-system-implementation/focused-semantic-review.md)及同名JSON：源输入、实际输出路径、裁定与哈希。
3. [代码审阅](../runs/2026-11-16-context-v5-system-implementation/review-report.md)、[验证记录](../runs/2026-11-16-context-v5-system-implementation/verification.json)、[用量审计](../runs/2026-11-16-context-v5-system-implementation/usage-audit.json)。
4. [标注审计](research/2026-11-16-unresolved-label-audit.md)、[预算与恢复研究](research/2026-11-16-budget-recovery-research.md)、[实施计划](superpowers/plans/2026-11-16-context-v5-system-implementation.md)。

## 当前实现

- HT04先确定旧任务关联缺口，再生成追问；完成报告不再误问承接。
- v5工作检查增加话语范围、工作资格和原话依据；分类冲突不能直接补负责人等执行缺口。
- 修正和复检保留固定ID的首检异议，必须逐条解决、有据推翻或保留未解决。
- facts/unresolved增加命题核验、一次修正与独立复检；真实未知与已承接调查可以并存；暂缓事实独立于工作分支保留。
- 每逻辑节点最多首发＋一次恢复；length从16K升32K一次；预算调整不清零尝试、不失效成功祖先。
- 结构失败时官方DeepSeek端点可用一次非思考strict工具恢复；固定空object做接口适配，完整本地身份/证据/schema校验仍执行。真实strict响应仍出现非法JSON和错层级，不能信任parsed或strict标记。
- 中断、损坏accepted、usage回填、402终止、429冷却均有记录及恢复路径。耗尽保持partial，不为通过而加第三次请求。

最新全套项目检查248项通过；之后代理兼容、固定空对象两项新增用例连同恢复专项17项通过；实验工具35项通过。代码审阅无剩余P1/P2。上述计数和测试版本见verification，不把离线通过当模型语义通过。

## 未解决项

| 分类 | 场景 | 后续关注 |
|---|---|---|
| 语义错误 | C11、C24 | 产品备选/转述被判为当前工作；C24还有两条假未决 |
| 语义错误 | P08b | 调查者、能力主体和录像对象仍被混淆 |
| 语义错误 | CP01 | 工作范围正确，但将背景“开关名称未统一”升为当前未决；这是政策原文复核发现，非预冻结逐例金标 |
| 语义错误 | SV15 | 调查已承接，“资料是否支持离线检索”只留在facts，unresolved漏提 |
| 未完整完成 | C14、SV17 | 两次结构恢复仍未通过；SV17暂缓事实独立保留 |
| 未完整完成 | SV05 | 纪要符合部分回答标准，但工作解释仍为interpretation_unresolved |

新8例冻结要求6条真实未决，保留5条，误增0。C20最新正常入口只追问视频工作的owner，不再虚构文稿动作；但冻结复检重放仍出现旧错，不能宣称稳定解决。

增加核验提示或单独开启纪要high思考未修复C20/C24，因此未采用。下一步优先用固定失败输入研究独立的源句引用范围、主体及动作判断，检验是否减少相同错误解释被反复认可；保留相邻正例，不靠重跑挑成功。仅在影响面或失败证据要求时扩大测试。

## 证据与运行

本次根目录：`runs/2026-11-16-context-v5-system-implementation/`。`before-source.zip`、`final-source.zip`、`production-changes.json`保留实现前后代码；所有取消批次、失败与探针都保留。初期429及余额不足402后用户已充值，后续必要测试已结束，当前没有等待余额或运行中的模型任务。

复现必要测试时使用不存在的新输出目录，并显式选case，例如：

```powershell
python experiments/task-boundary/run_system_validation.py --out runs/next-focused --only C11 C24 P08b --rounds 1 --workers 1
python experiments/task-boundary/run_system_validation.py --out runs/next-controls --semantic --only SV02 SV15 SV16 --rounds 1 --workers 1
python -m unittest discover -s tests -p test_stage_recovery.py
```

不要不带`--only`就启动真实回归。默认模型deepseek-flash，凭据沿用上两级`meeting-agent/.env`，不输出或复制凭据。环境为PowerShell、Python标准库、无Git。旧诊断脚本可能覆盖旧证据或断言旧bug仍存在，不用作当前回归入口。

## 保留的业务口径与历史

- 明确暂缓只收集，不立即追问或建任务；同场后续明确推进可激活，跨会议自动激活未实现。
- M2范围调整是执行工作；保留今天、内部员工和试点客户。P03a/P12a按用户口径保留待分配任务，今天决定不自动成为今天完成期限。
- C23核心是联系袁校长继续沟通；未明说的补问目的不强制。
- P07a缺先行场景时询问哪个场景有依据；P12b“并发测试”歧义不追改旧标签。
- `semantic-v1.json`标签在预测前冻结，助手编写，不是独立人工金标；原P08b条件性口径保留，新消歧输入另评。

旧全量183/190自动、172/190语义结果及既有政策背景见[前一阶段交接备份](HANDOVER-2026-11-16-before-system-implementation.md)与[旧结果报告](context-v5-fixes-results.md)。它们是历史证据，不是当前代码的新全量成绩。
