# context-v3：残留问题修复设计

用户已要求调研、设计、试实施并检验，按现有标准库/离线模拟器/默认不切换约束直接实施。此方案是工程选择，不声称用户逐项选定。新增独立 context-v3，保留 v1/v2。复用 v2 一次语义修正、身份、合并、执行器与权限规则。

## 调研与选择

考虑三路：继续补提示（代价低但保留冗余协议和双描述）；增加全新裁决器（调用成本高且上轮分类实验未证明收益）；在原流程收紧接口并统一判断定义（本轮选择）。

Anthropic 的 [evaluator-optimizer](https://www.anthropic.com/research/building-effective-agents) 以清晰评价标准和可用反馈为条件，不能以重复调用代替统一判据。[引用文档](https://platform.claude.com/docs/en/build-with-claude/citations) 使用由输入文档界定的定位信息；本项目借鉴限定证据集合，使用本地 Q 编号，不要求更换模型 API。[RARR](https://arxiv.org/abs/2210.08726) 在修订不支持内容时尽量保留原产出，支持本轮结构恢复携带原输出和具体错误的设计方向；论文不证明本项目效果。

## 接口

1. 所有解释/修正 record 和 event 字段 evidence 改为 Q 编号，程序依据当前会议逐段建立 catalogue，再展开精确全段 span。跟踪仍复用现有精确引用协议；该残留边界单列，不宣称全部阶段消除引用风险。
2. record.description 是唯一的最终工作内容。event.work 只携带 evidence，不再让模型重写 description；程序从所属 record 注入。work record 必须可直接成为任务描述，目的、范围和限制不能只存在旁注。非工作记录仍用 description 表达背景。
3. 每条 record 核验输出：record_id、kind（核验认定分类）、reason/evidence；content={verdict,reason,evidence,missing_details:[{description,evidence}]}；gap_checks=[{field,status=needed/not_needed,reason,evidence,question}]。不输出顶层 verdict/issues/proposed_kind/clarification/blocking_for。程序由分类差异、内容核验和原缺口变化推导旧内部协议：内容不支持或 missing_details 非空→work issue；分类不同→classification；撤销缺口/问题→对应 issue；阻断范围 work/reference/scope 为 content，其余 operation；提问按 needed gaps 生成。原有严格旧校验保留。真实未决事项被准确描述时 content 可 supported；不具备执行条件并不等于解释错误。
4. event 六字段核验只判断字段所写状态是否忠实。例如 relation=ambiguous 且确有竞争任务，应 supported；仍由执行器禁止非唯一更新。不会自动改写模型的 insufficient 为 supported。
5. 内容核验独立列出原文应保留但最终 description 缺失的必要信息；missing_details 对应同记录修正，不新造额外工作。仍保留 coverage_findings 处理独立遗漏。
6. 统一 need-policy 文件追加到跟踪/解释/核验/修正：implicit_need 需要原文把问题与期望改变、明确目标或留待处理的选择关联，单纯缺陷/抱怨/现状不自动形成潜在任务。implicit_need 输出 need_basis={goal,evidence}；其他记录 goal=null/evidence=[]。证据存在只保证来源，语义仍须核验。保护 CP06、合作邀约、建议工作。
7. 手工 resume 结构失败时，在该阶段原 payload 外增加 validation_feedback={error,previous_output,instruction}，提示保持身份和已正确语义。无自动额外调用。成功上游照常复用，原失败保留；一次恢复失败仍保留 partial，不扩大重试。单独保存诊断文件，配置/缓存隔离。

## 验收

程序测试覆盖重复引文 Q、未知 Q 拒绝、唯一内容进入 item、遗漏触发修正、撤销旧问题自动派生、真正关联歧义只问具体选项且不写旧任务、分类可关闭、结构 resume 带反馈且复用成功上游、旧版本不回归。
真实定向：C19/HT04/C23/CP01 + CP06/CP05/CP07 + C20/P07b/对象竞争/明确文稿/同段两工作 + M2/落实正例，各两轮首次结果单列。定向有失败仍记录并做一次可解释修订，不能无限抽样。达到门槛后完整跨会各两轮、33 对照、30语料、10行为和13旧任务更新；否则执行必要保护对照并报告未晋级。保持冻结评分，C19不接受机械多拆带来的虚高召回，C23按 item 而非 trace评分。每批快照保存，最后全套 unittest + 独立审查。只写本地 SQLite。

## 实施中已确认的接口补充（revision2）

- builder 审查指出 missing_details 必须保留到 repair：实现保存 checked_record.content_audit，并在 check.reason 写入缺失说明。
- 解析失败尚无 dict 时，从客户端已保存 response 提取 raw_text/finish_reason。恢复只改变请求反馈，成功结果写回原 stage 缓存键，避免重复恢复。
- 首次模型调用表明空数组示例会隐藏对象字段：所有空对象数组统一追加元素结构，仍由同一 schema 生成，包含 coverage_findings/gap_checks/missing_details。
- 明确“描述准确记录了未决状态”与“未决选择已经完成”不同，真实竞争对象的 gap 仍 needed。保护对照曾发生过误关，失败批次保留。
- relation 增加 candidate_guids：ambiguous 至少两个不同且有授权的旧任务 GUID，其他状态为空。reduce_v3 展示这些选项；对已完成/进度/重开且承接核验通过、没有真实 commitment gap 的历史汇报，去掉旧 reducer 误加的新工作承接缺口。仍不执行任何非唯一旧任务更新。
- 最终 revision2 冻结，两轮首次验证后不继续无限提示调优；若仍未达到门槛，则记录残留、做必要保护验收，并保留可选版本。
