# 最新交接：context-v4 已实施，模型效果未达晋级标准

2026-11-15。用户要求实施残留问题修复方案并检验。已完成可选 context-v4、独立 QA 实验、程序回归、真实模型对照和正常跨会回放。**不晋级默认策略；默认仍为 split-v3。**

先读[实施检验报告](context-v4-results.md)、[总汇总](../runs/2026-11-15-context-v4/summary.json)、[调研依据](context-v3-remediation-research.md)和[实施计划](superpowers/plans/2026-11-15-context-v4-implementation.md)。上一版交接保存在[历史文件](HANDOVER-2026-11-15-before-context-v4.md)。

## 实现与验证

- 分离 new_work_findings/uncertain_findings，程序派生覆盖关系；原记录内容缺失仍用 missing_details。
- 局部修正使用固定目标槽位和 scope；程序恢复 record/thread 身份，分配新增身份。未知槽位、额外身份字段、旧版本补丁被拒绝，再经过旧证据/语义/处置校验。
- QA 仅实验启用：来源问题独立提取，回答只看 work 描述；记录/finding 绑定支持整项遗漏，再核验只重看相关问题。独立审查的三个 QA 缺陷及修正枚举提示缺口已修复。
- 程序测试 198/198。v1-v3 核心及 v3 提示字节未变。
- 八个冻结上游样例，各三轮：A 仅补提示来源语义 18/24，最终 B 结构版 17/24，最终 C 加 QA 14/24。首批未修版本也保留。不是全流程或全语料分数。
- C23 原例三组各 0/3；补两句原始前文的额外探针也 0/3。改写/明确目的正例的冻结上游已正确，不能算修正收益。
- 原始跨会和明确落实各两轮：M2 目标更新/创建契约均通过，权限、历史、幂等与重启通过；补查 M1 后完整流程只有 2/4 无解释争议，另两轮的监控面板记录修正失败。

## 残留与下一步

1. B 的隔离 M2 为 2/3：仍可能把范围决定合法地改成需要负责人/承接的工作，结构有效不代表分类正确。
2. 故意遗漏同段第二工作时 B 为 0/3：核验未发现实际发送测试结果工作。C 能提出新增，但范围决定被误提为工作问题，并用背景记录声称 covered，违反任务描述核验约束，整轮失败。
3. C23 来源问题阶段三轮均返回 requirements=[]，没有识别必要目的；增加问答阶段未改善该语义判断。
4. M1 的“监控面板先放着、今天不定”仍有潜在需求/背景分类和修正契约问题；旧跨会验收漏检此类 M1 解释争议，现已加检查。

优先研究独立原文工作发现及与已有记录对齐，并统一决定/实施的判定权；不要继续堆同模型核验或用重试挑成功。保持冻结标签，C23 的口语推断边界若需重审，另报新旧口径。

小集未过门槛，没有扩大到完整 30 语料/33 对照/10 行为/13 更新回归。QA 不作为默认生产路径。

## 运行与产物

```powershell
python -m unittest discover -s tests -v
python scripts/replay_mvp.py --out runs/my-context-v4 --strategy context-v4 --inference-config experiments/action-context/compact-check.json
python experiments/task-boundary/run_context_v4.py --name my-new-small --mode small --arms B C --rounds 3
```

使用新输出目录；small 使用已冻结上游，cross/positive 使用正常 Service。所有证据在 runs/2026-11-15-context-v4，包括 before.zip、各批源码、final-source.zip、原始请求响应、SQLite、来源复核和 progress.md。

共 262 次真实调用、1,152,910 tokens，均收到响应，零模型恢复调用。一次 positive-r1 评估缺输入产物已从实际使用的同一输入补存并离线重评，没有新增模型调用；原异常日志保留。所有平台写入仍为本地模拟。
