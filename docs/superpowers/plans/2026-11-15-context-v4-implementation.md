# context-v4 实施与实验计划

Spec: ../../context-v3-remediation-research.md。用户已授权实施与检验。

1. 冻结源码和 v3 结果。用失败测试定义覆盖适配、修正目标、身份与版本约束，以及 record/event 整体校验。
2. 实施可选 context-v4：核验的 new_work_findings 与 uncertain_findings 分开；原记录问题沿用 record_checks。动态固定目标槽位，只生成可变语义内容；程序恢复身份与新增 finding 命名空间。复用 v2 修正、处置与再核验。
3. 独立 QA 实验：源文生成必要信息问题；回答阶段只看问题和最终描述；核验比较答案并将遗漏派生为 missing_details。来源问题及回答均持久化，新增调用单列。QA 不默认启用。
4. 接入 Extractor/Service/CLI，运行完整程序回归。准备冻结八例、A（仅补提示）/B（结构）/C（结构+QA）三轮首次运行；同模型同语义修正预算。先跑小集，再按失败情况决定晋级保护集与全量。
5. 一次独立代码审查，必要修复；最终来源语义评分、用量、残留、HANDOVER 与源码快照。

接口审查重点：新输出必须在调用旧 validator 前转换；旧 initial_check 直接消费 raw.coverage_findings；修正回调也直接消费 raw.dispositions，不能只改 interpret；只读记录不进入可写槽位；新工作身份由程序分配但处置仍需完整核验；QA 回答输入不得通过通用 stage 自动注入 meeting/evidence_catalog；缓存必须包含协议与源码，旧版本补丁拒绝。

验收：未知目标/字段/身份/版本零接受；真实新增任务和修正处置能完成；M2 零伪任务/额外争议；C23 必要目的有来源且反例不补造目的。小集失败保留结果，不用重试挑成功，不以全套单测代替模型效果。晋级门槛未满足则不运行完整全量。

Review Focus: 局部补丁身份与原始 record/event 配对、readonly 越界、添加 finding 的完整处置、分类变化的原子性、QA 答案来源隔离和缓存复用、原 v1-v3 行为不变、Service 跨会更新及幂等。
