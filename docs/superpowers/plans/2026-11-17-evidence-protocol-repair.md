# 会议证据输出契约修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 修复完整会议工作解释的引用协议与恢复路径，让ES2002a三项分工能够经过正式核验并保存。

**Architecture:** 外部输出仅接受原始segment_id字符串数组，内部输入span表示保持精确；解释schema、提示例子和本地校验使用同一契约。完整语义草稿的引用错误只允许一次有界证据补丁，之后走原有工作核验和Service流程。

**Tech Stack:** Python 3.13、unittest、现有urllib ModelClient、DeepSeek JSON/strict工具模式、SQLite。

**Spec:** [系统溯源与方案](../../完整会议失败_系统溯源与方案.md)，执行前读取全文及`runs/2026-11-17-evidence-protocol-diagnosis/audit.json`。

## Global Constraints

- 本计划P0已实施并验证；保留所有首轮请求、响应、usage、数据库和冻结评测标签。
- 不无条件把对象转ID、不改变任务语义、不因ID真实就认定证据支持任务。
- 不切换生产默认策略；保持首轮解释low/32768实验配置，其他推理设置按实际config保存。
- 不增加节点现有内容、传输、时间和token上限；仅一份完整草稿可获一次证据补丁。
- 不全量重跑60/115例，不发送真实飞书任务，不更换语料以获得成功。
- 全局缓存改造与tracking/minutes输入压缩属于P1，独立立项，不混入以下P0。
- 当前目录无Git仓库；用源码摘要和快照记录变更，不执行虚构的commit流程。

## Review Focus

- 输入对象span合法，但输出同形对象非法：Task 1明确边界，Task 2修补不能自动放行。
- 未知ID、空必需引用、越界span不能因为草稿完整而被接受：Task 2逐项拒绝或修补后重验。
- 缺records/events、缺业务字段、重复record_id不属于“只坏引用”：Task 2拒绝局部补丁。
- strict工具强制调用与思考模式不兼容：Task 2验证实际发送请求关闭思考、无reasoning_effort。
- 新解释改变纪要依赖，旧tracking又不能无条件继承：Task 3验证复用来源及依赖刷新，区分恢复与重新推理。

---

### Task 1：解释输出schema与输入/输出引用说明一致

**Files:**
- Modify: `meeting_eval/context_v5.py`、`meeting_eval/context_wire.py`
- Modify if needed: `prompts/interpret-work-context-v5.txt`
- Test: `tests/test_context_wire.py`、`tests/test_context_v5_regressions.py`

**Interfaces:** 保持`wire_prompt(prompt, meeting)`、`wire_request(payload)`和`decode_output(raw, meeting)`调用方式；`_stage('interpret_work', ...)`增加由`closed_schema(INTERPRET)`派生的`output_schema`。原始ID成员及类型错误由解码器形成结构化诊断，解码后、业务适配前执行相同输出结构的closed校验；这使引用类型错误保留可修补诊断，同时拒绝其他额外字段。

- [x] **先写失败测试。** 从真实`ContextV5Pipeline._stage`捕获ModelClient收到的请求，断言records和六类event字段的evidence均为`array.items.type=string`；存在output_schema；非空示例含一个真实源ID；提示清楚将span限定为输入表示，输出只允许字符串数组。
- [x] **验证边界反例。** 输入ledger里合法`segment_id/start/end`不变；原文中的“Q1”不被改写；输出对象数组仍拒绝；未知额外业务字段拒绝。对check_work/repair_work/check_repair捕获公共提示，保证没有重新引入对象输出规则。
- [x] **最小实现。** 复用INTERPRET与closed_schema，不复制另一份业务schema；正确示例只示范类型与引用，不能灌入ES2002a的任务答案。更新context-v5协议/版本及摘要，使新旧请求不能混用缓存。
- [x] **验证。** 运行`python -m unittest discover -s tests -p test_context_wire.py -v`及相应context-v5测试，保留实际请求构造结果。尚不调用模型。

### Task 2：引用错误的有界恢复

**Files:**
- Modify: `meeting_eval/context_wire.py`、`meeting_eval/reference_repair.py`、`meeting_eval/stage_runner.py`
- Reuse: `meeting_eval/model_client.py`现有strict工具适配，除测试发现具体不兼容外不重写。
- Test: `tests/test_reference_repair.py`、`tests/test_context_wire.py`及现有stage runner/model client测试。

**Interfaces:**
- `reference_issues(raw, meeting)`的每项增加稳定错误code、字段路径、expected与actual_type；保留本地完整无效值供审计。
- 新增`ReferenceValidationError(ValueError)`，持有`issues`，让runner生成结构化反馈，而非解析异常字符串。
- `ReferenceRepair.prepare(raw, payload)`继续返回补丁请求或None；改为只在schema声明的证据值路径放宽预检，其他必需字段、类型、额外字段与身份仍完整校验。
- `ReferenceRepair.merge(patch, request)`保持只修改冻结slot的契约；最终仍走完整输出校验、decode和解释校验。

- [x] **先写真实边界失败测试。** 给完整record/event提供对象数组引用，验证prepare应产生限定slot补丁；原草稿不变。对象越界、未知ID或空必需引用均不能直接接受。已合法引用保持不动。
- [x] **验证补丁资格限制。** 缺case_id、records/events、owner等非证据字段，重复身份、未知关联记录、额外字段均不得进入引用补丁。仅证据字段的值类型错误可修补；缺证据必需键仍属于不完整结构。
- [x] **实现错误反馈。** 完整issues保存在本地；模型反馈按code聚合，最多给8个路径示例，包含expected/actual_type及正确ID数组例子，明确“不是调整start/end”。报告total_issues，避免重复坏值挤掉后续错误；不把整份草稿或源文本塞入错误字符串。
- [x] **实现schema限定的补丁预检。** 从INTERPRET遍历声明路径，临时屏蔽这些证据值来检查其余结构；不按任意键名通配放宽所有字段，不补造缺失业务字段。核对case、记录唯一性和事件所属记录。
- [x] **接入严格证据补丁。** 支持的官方endpoint上，patch_request使用现有strict_schema参数、thinking=disabled、max_tokens=8192、强制submit_result；不携带reasoning_effort。其他支持的原有调用路径保持JSON＋本地校验，不自动换供应商。非引用结构错误使用Task 1提供的完整schema走原有有界恢复。
- [x] **验证完整恢复链。** 假客户端依次返回坏草稿与合法补丁，断言只调用两次、非证据字段全等、原始坏响应保留、重入和重开不再调用。补丁为空/未知ID/改变scope、402终止、429传输重试、截断JSON分别检查既有预算和停止行为。schema正确不替代后续check_work。
- [x] **重放实际失败。** 在独立目录读取ES2002a两次响应，确认都进入限定引用恢复；诊断“转ID后通过”不能充当生产修补。运行受影响测试一次并保存日志，不扩大到全量语义集。

### Task 3：单场恢复与用户可见验收

**Files:**
- Create: `experiments/full-meeting/recover_protocol.py`
- Test: `tests/test_full_meeting_recovery.py`（复用检查、额度停止及依赖刷新）
- Update: `docs/完整会议测试_ES2002a.md`、`docs/HANDOVER.md`
- Output: 新目录`runs/2026-11-17-full-meeting-ES2002a-protocol-recovery/`，不覆盖首轮。

**Interfaces:** `recover_protocol.py --source <首轮目录> --out <新目录>`默认只做预检；`--live --limit 8`启用实际运行，总HTTP上限固定不超过8。通过现有Extractor/Service执行完整结果恢复；允许显式导入通过验证的tracking，不能用TaskOnlyExtractor把省略的纪要步骤算作完成。

- [x] **先写隔离预检。** 核对输入与history摘要，源tracking的提示、模型、推理设置、tracking实现和校验依赖没有变化；重跑保存tracking响应的本地校验。任一不符即停，不自动重新全文跟踪。manifest写出每个导入产物路径、哈希及验证依据。
- [x] **测试额度与停止。** 额度在真实HTTP发出前持久化占用，覆盖并发调用；8次耗尽或节点terminal/waiting/recovery状态时保存结果并停止，重入不能通过换目录自动重置额度。预检及离线测试不得访问网络。
- [x] **执行一次恢复。** 解释使用新契约从头推理，按需执行一次引用补丁、工作核验及原有语义修补。复用原事实/决策；用新工作核验结果刷新依赖它的纪要核验，必要时使用原有纪要修补/复核。全局8次额度先于任何额外尝试，不能为了processed继续加预算。
- [x] **核对产物。** 保存status、items、review_records、collected_issues、原始响应及所有usage；对三项参考分工逐项匹配、核对负责人和时间。任何新增任务对照原文判断，不能只数“三条”。没有真实账号映射时只验证本地保存与待绑定入口，不声称真实飞书任务已经创建。
- [x] **核对持久化。** Service完整结果无未处理的阶段错误；重开数据库后结果、纪要、待确认内容一致。重复提交不产生新增HTTP或重复记录。若失败，保留partial及诊断，不修改原始评测分数。
- [x] **记录结论。** 明确哪些阶段复用、哪些重新调用；比较首轮阻断是否解除，报告真实耗时与usage。记录此单例的适用边界，不重算整个扩展集指标。

## 后续P1，单独排期

1. tracking缓存按阶段真实依赖定位；测试解释提示改变时复用成立，tracking提示/校验实现改变时失效。
2. tracking与minutes请求的原文、证据目录、schema枚举去重；使用原始引用恢复等价性及字节/token审计验证，不截断历史语义。
3. 纪要行动项在该字段失败时显示“提取未完成”，成功且空时才显示“无”。

## 本计划自检

三个P0任务分别对应输出契约、恢复、整场产物验证；Review Focus五项均有明确测试归属。P1不作为P0前置。P0已完成：68项相关离线检查通过；ES2002a使用5次新HTTP恢复为processed，三项参考工作进入正式行动项/确认卡。严格引用补丁本轮未在线触发，保留离线验证边界。详见[修复结果](../../完整会议证据协议_修复结果.md)。
