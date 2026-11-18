# Context-v5 推理预算与失败恢复调查

2026-11-16。对象为最终两轮 `full-compact-final` 的 CP01、C14，以及同轮全部 992 份请求记录。本次只读取生产代码、原始请求/响应、阶段产物和 SQLite；未调用模型，未改生产逻辑或历史结果。

**建议先将追踪阶段的 16,384→32,768 预算作为受控实验，并实现按失败原因选择的一次恢复。** CP01 确实耗尽了输出预算，C14 则在充足预算内生成了非法 JSON。两者不能共用“修复格式”的重试提示。现有程序已经保存原始响应、成功检查点和独立分支结果，具备局部恢复基础；缺少的是明确的失败类型、预算升级、持久化尝试上限与可核算的恢复记录。32K 能否解决 CP01，仍须真实调用验证。

## 1. 已证实的故障与影响范围

### CP01：第一个检查点耗尽预算

两轮请求完全相同：`thinking=enabled`、`reasoning_effort=high`、`max_tokens=16384`，输入 6,650 tokens。输入仅含 s1–s8；s9 才限定为移动端设置页，s10 才明确承接。第一个检查点失败后，程序没有执行第二个检查点及工作解释、核验。

| 轮次 | 输出 tokens | reasoning tokens | 内容字符 | finish_reason | 耗时秒 |
|---|---:|---:|---:|---|---:|
| r1 | 16,384 | 16,384 | 0 | length | 94.372 |
| r2 | 16,384 | 15,922 | 1,309 | length | 95.150 |

原始记录：[r1 请求/响应目录](../../runs/2026-11-16-context-v5-fixes/full-compact-final/r1/probes/CP01/model/8312b068dc1a040bb1e3e48e7de50057b5fb7acccc8769efa15556c1d422a2c8)、[r2 对应目录](../../runs/2026-11-16-context-v5-fixes/full-compact-final/r2/probes/CP01/model/8312b068dc1a040bb1e3e48e7de50057b5fb7acccc8769efa15556c1d422a2c8)。两轮都不是网络超时，也不是已看完十段之后的理解失败。

`result.json` 两轮均为 `partial`：保留 7 条 facts、1 条 decisions，items/updates 都为空，trace 内成功检查点数为 0。只读 SQLite 核实 sources=1、extraction_context=1、decisions=1、intents=0、tokens=0。因此任务分支没有执行写入，成功的独立分支仍有持久结果。

已证因果是“该次推理消耗占满输出预算→无法得到完整增量→客户端拒绝→任务分支停止”。**尚未证实**的解释包括：未明确范围的前缀使模型反复权衡、逐段维护多种对象使推理变长、重复协议说明增加负担。请求中 system 有 5,095 字符，user 有 11,194 字符；其中 `output_schema` 的 JSON 序列化有 7,091 字符，`output_contract` 有 2,027 字符，meeting 有 1,372 字符。这里只是可隔离测试的输入构成，不能将字符占比当 token 占比，也不能据此证明 schema 导致推理耗尽。

### C14：第二个检查点正常结束，但 JSON 少了闭合符

首检查点完成前 8 段。失败请求包含截至第 13 段的原文及首检查点 ledger，新增 5 段，输入 8,269 tokens；输出 2,674 tokens，其中 reasoning=2,362，内容 813 字符，`finish_reason=stop`，耗时 13.631 秒。上限仍为 16,384；不是 length 故障。

[原始请求/响应](../../runs/2026-11-16-context-v5-fixes/full-compact-final/r1/corpus/C14/model/b67e94605e7041c0fa1460ed766e1ee893022f1d7de36ab39e93a58697f41ee0)在 `json.loads` 的字符 811 处失败。既有[离线诊断](../context-v5-final-failures-analysis.md)已在内存中插入缺失的 `]`，验证解析、`expand_delta` 的协议/证据/顺序检查均能通过；这定位了语法阻断点，未证明后续工作解释正确，也未修改原响应。

当前结果为 `partial`，保留 5 条 facts、1 条 unresolved 和首个成功检查点，items/updates 为空。SQLite 的 intents=0、tokens=0。**增加预算不针对这次故障；自动补括号后直接信任其语义也没有依据。**

## 2. 当前代码实际如何失败、缓存和恢复

相关入口：[ModelClient](../../meeting_eval/model_client.py)、[ContextV3Pipeline._stage](../../meeting_eval/context_v3.py)、[继承的 ContextV2Pipeline.run](../../meeting_eval/context_v2.py)、[Extractor](../../meeting_eval/extract.py)、[Service](../../meeting_eval/service.py)。v5 覆盖请求构造和校验，仍复用这些调用及恢复路径。

| 层级 | 当前行为 | 对恢复的含义 |
|---|---|---|
| HTTP 调用 | 非流式 `urlopen(timeout=90)`，完整 HTTP JSON 到达后写 response，再写 meta | 保存成功收到的非法/截断内容；没有分块持久化。连接中断或进程中止可能没有最终 usage |
| 完成原因 | 任何非 stop 都抛 `ValueError('Incomplete model response')` | length、服务端中断及内容过滤被抹成同一个错误；不能据此正确选恢复策略 |
| JSON 校验 | 收到后才 `json.loads(content)`，且根必须为 object | meta 的 `status=received` 不等于可用；解析失败时 meta 仍含 usage |
| 请求缓存 | key=endpoint+完整 request；只要 response 存在且未 fresh，就复用 | **已收到的 length/坏 JSON 会被普通重入反复读取**；不存在 response、已有 meta 的传输失败才自动进入 retry 目录 |
| 阶段缓存 | `validated.json` 存在就直接返回；否则调用，成功才写 validated | 同配置恢复可复用成功检查点；失败输出不会作为有效 ledger |
| 阶段重入 | resume 且 state 已存在才设 fresh；若有 validation-failure，将错误和 previous_output 加到输入 | Service 对 partial 的重入会发新请求。但 length 和 JSONDecodeError 都进入“结构或证据定位修复”反馈，**预算仍不变** |
| 分支合并 | items/updates 属于依赖组；失败时记两条同源错误；facts、decisions 可继续保留 | 可只恢复工作分支，不必重新支付正确的独立分支 |
| Service 重入 | partial 使用冻结的原 context，并复查 actor/读取权限；非 partial 返回已存结果并恢复 intent | 不会拿今天的新任务状态替换当时上下文；语义错但无 `_errors` 的 processed 结果不会靠此路径重算 |

`_saved_response` 会找回与 prompt/payload 匹配的保存响应，将 raw_text 和 finish_reason 放入 validation-failure；CP01 和 C14 均已实际留下此文件。raw response 的重试目录保留每次收到的响应，但阶段 `state.json`、`validation-failure.json` 和聚合 `result.json` 是覆盖写；不能只看最新聚合产物统计经历过的尝试。`write_json` 目前直接 `write_text`，没有临时文件替换的原子提交。

现有恢复是**调用者再次执行 Service.process 时触发**，不是单次模型调用内的自动重试。生产代码未设这一逻辑阶段跨 process 调用的总次数上限；最终 992 请求没有 retry 目录，不含恢复后的成功率。

### 改配置会影响恢复范围

阶段 accepted cache 和管线目录均含整个 `self.config`，其中包括所有阶段的 inference。直接把 track 的 max_tokens 改为 32K，会改变整条管线的 accepted-cache 路径；即使某个上游阶段本来成功，也无法直接命中旧 `validated.json`。底层 request 没变时仍可能复用 raw response，但所有 track 请求因预算变了都会有新 request key。不能声称“只改配置就必然只重跑失败检查点”。

正常同配置的 C14 partial 恢复会保留第一个 validated 检查点，重跑第二个，并从它的成功结果继续 interpret/check；CP01 则从第一个检查点开始。新恢复设计应保留这一范围，预算变化作为失败节点的新 attempt 参数，不通过修改整条管线配置抹去已接受状态。若确实改变语义 prompt、schema 或转换代码，应按依赖关系失效对应产物，不能继续无条件复用。

### 事务和副作用

模型调用发生在 Service 数据库事务之前；源、冻结 context、规划 intent 和结果更新在同一 `with self.store.db` 内。任务分支失败不会产生其创建/更新 intent；独立 decisions 可以提交。随后 `recover` 以持久 intent、create token 和回读结果恢复平台写入。它处理的是执行恢复，不是模型重试。

这不是所有分支全成全败的事务：CP01 的 decision 已持久化而任务仍失败，符合现有部分成功设计。恢复时继续通过确定性的 intent ID 与 `INSERT OR IGNORE` 避免重复规划；不能重新创建整场会议或更换 source identity 来绕过失败。

## 3. 同轮用量分布支持哪些预算调整

统计方法：遍历最终目录 r1/r2 下全部 `meta.json`，关联同目录 request/response，按 meta.stage 分组。P95/P99 使用排序后 `ceil(p*n)` 的 nearest-rank 值；包括失败请求，未混入调优轮次。共 992 请求、5,206,653 total tokens，与交接总数一致。194 次 facts/decisions 包含链式用例的多场会议，不能将请求数误当独立场景数。

| 阶段 | 请求数 | 输出 P50 | 输出 P95 | 输出 P99 | 输出最大 | 推理 P95 | 秒 P95 | 秒最大 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| track_context | 210 | 1,599 | 7,808 | 12,123 | 16,384 | 7,386 | 44.732 | 95.150 |
| interpret_work | 191 | 1,473 | 5,390 | 12,664 | 14,830 | 5,038 | 31.287 | 87.606 |
| check_work | 191 | 480 | 962 | 1,293 | 1,298 | 0 | 5.722 | 7.800 |
| repair_work | 6 | 1,508 | 3,554 | 3,554 | 3,554 | 3,284 | 20.951 | 20.951 |
| check_repair | 6 | 227 | 463 | 463 | 463 | 0 | 3.566 | 3.566 |
| facts | 194 | 76 | 202 | 301 | 351 | 0 | 2.665 | 3.495 |
| decisions | 194 | 6 | 57 | 100 | 100 | 0 | 2.147 | 6.671 |

| 阶段 | 总输入 tokens | 总输出 tokens | 其中总推理 tokens |
|---|---:|---:|---:|
| track_context | 1,054,284 | 541,556 | 483,404 |
| interpret_work | 1,166,410 | 373,681 | 318,228 |
| check_work | 1,597,209 | 96,360 | 0 |
| repair_work | 47,188 | 10,517 | 9,328 |
| check_repair | 48,662 | 1,610 | 0 |
| facts | 127,460 | 17,632 | 0 |
| decisions | 120,826 | 3,258 | 0 |

track 中除了 CP01 的两次 length，其他 208 次都以 stop 结束，最大输出 12,123；这 208 次包括 C14 的语法失败，不能称为全部有效。interpret 最大的 14,830 来自 r1/C24，推理占 14,472，却仍有语义错误：大预算不等于正确分类。

建议分阶段配置如下，标为“实验”的值尚未实测：

| 阶段 | 建议 | 依据与边界 |
|---|---|---|
| track_context | 固定 CP01 请求先试 high/32,768；通过后再评估将 32,768 作为首发上限 | 16K 已确定不足两次；32K 给出两倍容量，不能保证推理一定在此结束 |
| interpret_work | 暂保留 high/16,384；遇 length 可一次升级 32,768 | 无现有截断，最大值已到上限约 91%；无需为所有调用直接扩容 |
| repair_work | 暂保留 high/16,384 | 仅 6 份样本，不据此降低预算或提高思考档位 |
| check_work/check_repair | 保持非思考及当前 16,384 上限 | 此次没有长度问题；已有开启检查思考的负面实验，不与预算恢复混测 |
| facts/decisions | 保持非思考及 6,000 | 现有失败是语义归属/描述问题，不是输出长度 |

32K 是上限而非必付 tokens；但更高上限可能让本来会继续思考的调用产生更多成本和延迟。CP01 的 16K 两次已约 95 秒，线性外推 32K 约 190 秒仅可用于初始资源规划，不能当性能预测。建议将读等待与总耗时分别记录，并用真实 32K 耗时校准约 240–300 秒的阶段总截止时间；若超出则显式超时退出，不静默继续加预算。

当前 `timeout=90` 不是 90 秒总墙钟上限，两个 CP01 都超过 94 秒仍收到了响应。官方还说明非流式等待会收到空行保活、十分钟未开始推理才断连；因此不能简单认为“90秒已经限制了整次推理”。[DeepSeek 连接保活说明](https://api-docs.deepseek.com/quick_start/rate_limit/)

## 4. 官方接口能力与本地差距

以下为 2026-11-16 查询的官方文档，不代替本项目端到端兼容性验证：

- `deepseek-flash` 当前映射 DeepSeek-V4.1-Flash-1017，支持思考/非思考，context 为 1M，最大输出 384K。历史 response.model 只记录了 `deepseek-flash` 别名，不能仅凭这一字段独立确认底层权重版本。[Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- Chat Completions 的 `max_tokens` 范围为 1–393,216；未指定时非思考默认 8K、思考 64K、max 思考 128K。本地明确指定 16K，会覆盖这些默认值。`response_format.type` 公布的值是 text/json_object；不能自行发送未文档化的 json_schema。[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)
- 当前思考档位有 low/high/max；本地 `inference_parameters` 仅接受 high/max，low 必须先修改并验证本地参数校验。thinking 下 temperature 不生效；不能用 temperature=0 作为确定性保证。[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)
- JSON 模式要求 prompt 明确输出 JSON、给格式示例并提供足够预算；官方也说明可能出现空内容。现有请求已经使用 json_object 和协议示例，但 C14 的原始响应仍未通过解析；生产必须以实际解析结果为准。[JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- Beta strict 是 **工具参数 schema 约束**，不是把当前 response_format 改一个值。需 `/beta` base URL、工具 `strict=true`；思考及非思考均支持。所有 object 属性需 required、additionalProperties=false；minItems/maxItems、minLength/maxLength 等不支持，需转换 schema，并保留本地校验。[Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)
- 另一个实际约束：thinking 下 required/指定函数的 tool_choice 会返回 400。因此不能在现有 high 追踪请求上直接强制唯一 strict 工具。若保留 thinking+auto，必须处理模型未调用工具或调用形式不符；若关闭 thinking 来强制调用，则同时改变了推理机制，须单独实验。[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)

本地客户端目前只读取 content、只接受 stop；strict 工具通常需要读取 tool_calls.arguments 并接受匹配的结束原因，还要验证唯一工具、函数名和 schema。它可以作为独立结构可靠性实验，但不是 CP01 的预算补救，也不保证引用归属和工作资格正确。现有 schema 带 example；其他阶段还使用可空类型数组。应逐项核对、适配并验证接口接受范围。数组内容、引用及跨节点关系等本地约束仍须保留，不能未经验证就承诺 Beta 接口兼容。

## 5. 可实施的调用尝试状态机

将“逻辑阶段/检查点”和“某一次请求”分开。逻辑输入包括完整原文前缀、上一 accepted ledger、增量段落、prompt/schema/转换版本；每次请求另存 actual max_tokens、reasoning_effort、request hash、attempt_id。仅预算或传输恢复改变时，继续挂在同一逻辑节点，已接受的祖先节点仍可复用。

```text
planned → request_started → response_received
                            ├─ length → budget_exhausted
                            ├─ stop → parse → schema/evidence/order validation → accepted
                            │           └─ error → structure_invalid
                            ├─ transient server interruption → transport_failed
                            └─ other finish reason → terminal/explicit classification
request_started → connection error/deadline → transport_failed 或 usage_unknown

budget_exhausted / structure_invalid / retryable transport_failed
  → 若本节点尚有恢复额度：new attempt → 同样的完整校验
  → 否则 exhausted，保持 partial，不提交该节点下游任务
```

先采用**每个逻辑节点最多 2 次实际请求（首发+1次恢复）**，计数落盘，Service 重入不自动清零。恢复失败后停止；用户明确发起新实验可新建 campaign，并关联旧失败，不能将新 campaign 的成功覆盖为首发成功。认证、非法参数、content_filter 等不自动换参数绕过；服务端中断必须按记录的原因分类，不能统统扩预算。

| 故障类别 | 一次恢复如何发起 | 成功条件 |
|---|---|---|
| length，且 16K 已用满 | 保持原文、prompt、schema、high 不变，完整重生成，max_tokens=32,768；不将截断正文当完整状态，也不追加“修复结构” | stop、完整 JSON、schema 与证据/顺序/身份校验全部通过，再执行下游 |
| length，已用 32K | 本轮候选策略先终止，不自动升 64K/max | 后续单独实验决定更高预算、low 或协议调整 |
| stop+JSONDecodeError/空内容 | 同逻辑输入一次格式重生成；附准确 parser error 和原始待校验文本，明确它是数据。C14 不需增加预算 | 输出重新通过全部本地校验，之后仍执行 interpret/check；不使用手动补字符直接代替请求 |
| stop+schema/证据定位错误 | 精确反馈校验错误、原始身份和未受影响字段；一次完整有效输出 | 不允许反馈成为新增任务依据；错误证据、未来引用、替换旧 ID 均继续拒绝 |
| 可重试传输错误 | 按状态码/连接错误有限等待后一次新 attempt；原预算不变 | 收到完整响应并校验；无 usage 时记录 unknown，不能计为零 |
| 已通过结构但语义错 | 走独立语义检查/repair_work/check_repair | 原文依据、目标身份和修正理由成立；格式恢复额度不能用于反复抽样语义答案 |

模型“补语法”也可能改变字段含义，因此它仍是候选重生成，不享有更宽松的验收。已有本地身份/证据/顺序检查和后续语义检查必须继续运行。若以后尝试纯语法 formatter，只能保存为诊断候选或进入同等核验，不能建立“能 parse 就自动采纳”的快捷路径。

预算实验通过后，可将追踪首发设为 32K；此时 length 不再自动升级，单次恢复额度仅留给可恢复的格式/传输故障。这样避免形成 16→32→64→更高的无界链。预算配置与尝试策略应同时记入运行 manifest；现有 inference_config 只支持模型参数，timeout/attempt_limit 等是**建议新增的本地配置**，不能直接把它们塞进当前 inference 字典。

### 最小记录和提交契约

每次 attempt 保留 request、完整 raw response、HTTP/finish reason、parser/validator 结果、开始与结束时间、prompt/completion/reasoning/cache tokens、实际预算、模型返回名与 fingerprint、恢复原因、父 attempt、最后 accepted checkpoint。把 `received`、`parsed`、`validated`、`exhausted` 分开统计。HTTP 层已保存 usage 的失败不能漏记；无最终 usage 的中断单独统计未知次数。缓存命中应引用既有 attempt，不新增一笔“模型消耗”。

accepted 文件使用临时文件写完后原子替换，再更新节点状态；启动时核对 accepted 文件可解析且依赖/hash 匹配，不把“文件存在”当完整提交。不得先推进 checkpoint 再完成验证。变更后的检查点只重建其后代；独立 facts/decisions 和无变化的祖先继续复用。

语义修正阶段失败另有状态缺口：`ContextV2Pipeline.run` 的 repair 子块捕获异常后只记 `trace.repair.status=failed`，外层 `errors` 可能仍为空；Service 的 partial 重试只看 `_errors`，不能保证重入会恢复该 repair。这不同于 CP01/C14 的外层错误，但新增恢复应明确“保留首检有效结果、待修正目标不可执行、失败原因用户可见”，不能仅凭 stage trace 认为所有失败都有 Service 重试入口。

## 6. 最小验证矩阵与交付口径

先离线验证状态机与原失败记录，再消耗模型额度。所有真实实验使用新目录，保留原 172/190 结果。

| 层级 | 最小输入/故障注入 | 必须看到的结果 |
|---|---|---|
| 离线分类 | CP01 r1 空 content/length、r2 截断 content/length、C14 stop/坏 JSON、网络错误 | 分类不同；已有 usage 全计入；length 不被改称语法失败 |
| 缓存与重入 | 相同 request 的坏响应；成功第一 checkpoint+失败第二 checkpoint；同节点再次 Service.process | 失败 raw 可审计但不作为成功缓存；最多一次恢复；首检查点不重调，预算改变不抹去祖先；计数跨重入保留 |
| 状态与副作用 | C14 恢复成功/失败；CP01 失败；修正阶段失败 | facts/decisions 保留；未接受任务不执行；成功恢复后重复 process 不重复 intent/平台写入；repair 故障可见 |
| 崩溃与核算 | 写 accepted 中断、HTTP 已开始但无最终 usage、已收到响应后解析失败 | 损坏文件不被当 accepted；unknown usage 不置零；失败与恢复耗费都计入；原始响应不覆盖 |
| CP01 预算隔离 | 冻结原前 8 段请求，以 high/16K 与 high/32K 同口径各做至少 3 次 | 同时报告首发完整率、推理/正文 tokens、耗时；32K 完成后继续读 s9–s10并核对最终范围、承接和任务数量。前缀过关不是全流程通过 |
| C14 格式恢复 | 冻结 r1 成功首 ledger 和失败第二输入，按 proposed recovery 至少 3 次 | JSON/增量协议通过、首 ledger 未改变；完整原文进入下游，条件性调研语义仍正确。不得拿 r2 的不同首 ledger 充作同输入恢复成功 |
| 未见正反例 | 跨检查点的暂缓后澄清、撤回、条件未成立、仅引用工作各至少 1 个新例 | 不为缩短推理漏掉真实工作，也不因重生成扩大工作范围；最终用户输出与平台状态匹配 |

若 high/32K 仍耗尽，再一次只改变一个因素：先比较 low/32K（需要本地允许 low），或缩减重复协议表示并保持 schema 约束；不能同时改预算、思考强度、checkpoint_size 和提示后归因于其中一个。改变 checkpoint 边界会让模型看到不同澄清时机，应另列协议实验。strict 工具也单列实验，不与预算实验合并。

三个重复只足以筛掉明显不稳定方案，不能证明稳定性。报告分别列出首发成功、一次恢复成功、耗尽/未知 usage、语义通过与实际任务执行；不得只保留最后一次成功。若 CP01 的预算放宽后完整输出仍误解范围，则长度故障已经修复，但语义故障仍应独立保留。

本次证据支持扩充追踪预算与补齐失败恢复机制；不支持宣称 32K 已解决 CP01、strict 已消除 C14，或局部恢复后整套评测分数已经提高。
