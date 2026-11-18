# 三个未完成项：技术恢复与事项收录实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use checkbox steps below. Continue native implementation; do not create a new execution-method approval step.

**Goal:** C14/SV17 的有效判断不因可恢复的结构错误丢失，故障能定位并按节点续跑；SV05 的讲义版本问题持久收录、可查询，不因工作分类冲突悬空。

**Architecture:** 在现有 ModelClient→run_stage→v5完整校验之间增加有限的结构规范化；将内容生成、传输恢复、人工续跑分开计数并共享请求总上限。事项收录复用 sources.result，不引入另一套任务库，不要求事项先成为可执行工作。

**Tech Stack:** Python标准库、SQLite、现有context-v5与Service；默认split-v3不变，无Git，以源码快照/差异和运行证据交付。

**Spec:** 用户2026-11-17的新要求优先；基础设计见`docs/superpowers/specs/2026-11-16-context-v5-system-remediation-design.md`，实测依据见`docs/context-v5-system-implementation-results.md`及本次第1节。状态：2026-11-17已实施并检验；90项离线专项通过，3目标＋1正常对照通过功能验收。首轮JSON模式400及仅失败分支续跑均保留，详见`docs/context-v5-incomplete-recovery-results.md`。

## Global Constraints

- 只优先修C14、SV17、SV05；C11/C24/P08b/CP01/SV15五个语义错误保留为模型能力与思考预算边界，本轮不逐例调提示、不更换模型、不扩语义审核链。
- “事项落袋”指已有可靠命题持久收录、可读、有原话依据及状态；不等于自动建执行任务，不补负责人、期限或承接。
- 只做必要验证，不跑95×2；原响应、失败、消耗和旧标签全部保留，不重复抽样取最好结果。
- 技术恢复不能修改判断文本、verdict、身份、证据、条件或业务状态；所有恢复结果仍走原完整schema、scope、身份和证据校验。
- 用户已授权修复方向；本计划不要求重新选择实现方式或批准模型请求。新增工作的验收独立于五项暂缓语义问题。

## 1. 已核实的问题与本次取舍

| 场景 | 当前证据 | 处理目标 |
|---|---|---|
| C14 | `focused-strict/r1/corpus/C14`：首检文本缺少record_checks的闭合；第二次strict arguments可解析，但checks/coverage_findings被放在record_checks内部。判断内容已经生成 | 优先恢复唯一可确定的协议结构；无法恢复才重新生成失败节点 |
| SV17 | `empty-fix-semantic/r1/semantic/SV17`：普通输出与strict输出都在同一容器边界少闭合符。暂缓判断与原话均已给出 | 不再把完整语义重做当作唯一格式恢复手段；保留暂缓事项，拒绝立即执行 |
| SV05 | `semantic-focused/r1/semantic/SV05`：sources.result中的unresolved已有“明天培训使用哪个版本的讲义仍未确定”；另有implicit_need与工作资格uncertain的冲突 | 给已核验问题明确的收录ID、状态与读取入口；工作解释未定不能阻止保存 |

当前恢复把不同故障混在“最多两次请求”里；网络失败会挤占内容恢复机会，耗尽后重复process也不能再推进。strict请求还同时携带源output_schema、output_contract与工具schema，接口适配后表达可能不一致。需要同时处理恢复策略和协议冗余，而不是只增加重试次数。

本计划调整此前“不得自动补括号”的保守策略：允许**唯一、无语义内容变更、完整校验通过**的结构规范化。通用宽松JSON修复、截断内容补全、缺字段猜测、任意树重排仍不采用。

## 2. 恢复策略

顺序：已有完整缓存→受限本地结构规范化→按失败类型恢复一次内容输出→明确的等待/耗尽状态。每个逻辑节点独立记录，恢复不重跑成功检查点、facts或decisions，不重复任务写入。

| 类型 | 动作 | 限制 |
|---|---|---|
| 缺闭合符/协议字段错层级 | 先尝试本地规范化，不调用模型；保存原始与规范化产物、规则、修改位置及哈希 | 仅v5 check_work/check_repair的已知协议；唯一合法候选且原校验全部通过 |
| 无法唯一恢复的语法/schema错误 | 原输入、同预算重新生成失败节点；官方端点沿用一次strict恢复，但只发送一份工具契约 | 不重新判断整场；不能因为结果可解析就接受 |
| length | 保持原文和推理档位，16K→32K一次 | 不对截断文本做本地补全；32K再次截断停止 |
| 429/可恢复5xx/连接中断 | 依据Retry-After或有界退避恢复传输 | 不消耗内容重生成额度，但计入物理请求总数；402/401/403及确定的契约400不盲重试 |
| 等待或耗尽 | 明确保存retry_at、失败节点和原因；保留独立结果 | 普通重复process不清零次数；等待期内不请求；耗尽不伪装成“正在重试” |

初始策略：每节点最多2次内容生成、2次额外传输恢复，自动物理请求合计不超过4次。单次请求最多300秒，累计实际请求时间最多600秒；服务端冷却与进程离线时间不计为模型请求时间，长冷却持久化后返回。中断且结果未知的请求计一次；无法恢复耗时记录时按该次预留截止预算扣除。次数与时间使用先预留后结算，断电不能获得额外额度。

显式人工续跑最多追加1个恢复批次，至多2次物理请求，节点历史总计不超过6次；每次给固定retry_id，重复提交同ID不增加额度。这个入口是用户选择重试失败节点，不是自动无限重试，也不是每次弹窗请求许可。来源和冻结上下文权限要重新检查，成功节点继续复用。

### 本地结构规范化的边界

1. 只处理已完整结束的stop/tool_calls内容；length、未闭合字符串、缺失值、重复键直接拒绝本地恢复。
2. 对非法JSON，只在已知根字段checks/coverage_findings/disposition_checks/issue_checks的token边界试插**一个**缺失的`}`，不改字符串、数组内容或其他标点。候选位置由JSON token扫描确定，不在字符串内做替换。
3. 对已解析却错层级的对象，仅允许把误置于record_checks、且名称不属于本次任何record_id的上述协议根字段移回根；根上已有同名字段时拒绝，不合并、不覆盖。
4. 字符串、数值、布尔、null、数组顺序、键和值数量必须完整保留；根字段只移动协议位置。输出只有一个符合完整契约的结果时才接受；多个不同合法结果或仍缺数据时转入有界模型恢复。
5. 规范化只恢复一次响应的结构，不把两个失败响应拼成第三份结果。新的accepted记录引用实际验证的candidate文件，崩溃重入不能误用未规范化raw。

## Review Focus

- 解析器默认吞掉重复键，会悄悄改变判断；Task1必须测试重复键、字符串内括号、两个合法候选及缺值均拒绝。
- 本地修正后崩溃，重入可能错误读取原坏raw；Task1/2必须覆盖接受产物指针、损坏accepted重建和规范化重复执行。
- 先429再结构错误，两种额度可能相互重置；Task2必须断言跨重入总请求、内容次数和等待时间均守上限。
- 同一段既有待定问题又有明确工作，不能因收录问题删掉工作；Task3必须覆盖两者并存，不用证据重叠做语义去重。
- SV05重新打开数据库后事项可能只剩展示字符串；Task3必须验证稳定ID、查询、来源权限、重复处理和原分类诊断保留。

## Task 1: 恢复已生成的检查结构

**Files:** 新建`meeting_eval/check_transport.py`、`tests/test_check_transport.py`；修改`model_client.py`、`stage_runner.py`、`context_v5.py`。

**Interfaces:** `normalize_check_output(raw_text, contract) -> {value, normalization} | None`；只为check_work/check_repair注入run_stage。normalization包含规则、原始/候选哈希与结构编辑记录。正常解析、完整业务校验仍使用现有转换回调。

- [x] 将C14和SV17的首发/恢复输出、原contract与校验上下文复制为独立测试fixture，记录来源哈希；测试在未实现时失败。
- [x] 实现上述有限规则和拒绝条件；保存`normalized.json`，原`response.json/raw.json`不覆盖；通过原validate后才提交accepted。
- [x] strict请求的模型输入只保留工具schema这一份输出契约，删掉重复output_schema/output_contract文本；保留原逻辑请求作审计，恢复/回填仍用完整本地契约。非strict请求只保留一份完整契约。
- [x] 验证C14恢复后conditional与原证据不变，SV17恢复后deferred_topic与下周再议不变；不新增任何语义判断。正常合法输出原样通过。
- [x] 运行`python -m unittest discover -s tests -p test_check_transport.py`及已有恢复专项，检查所有负例拒绝且故障fixture无需网络即可完整验证。保存源码差异，不创建Git提交。

## Task 2: 分类预算、节点续跑与可见失败状态

**Files:** 修改`stage_runner.py`、`model_client.py`、`extract.py`、`service.py`、`tests/test_stage_recovery.py`；新增`tests/test_source_recovery.py`。

**Interfaces:** `run_stage(..., recovery_grant=None)`保持原返回值；状态增加content_attempts/transport_retries/request_count/charged_request_seconds及候选文件指针。`Service.retry_extraction(sid, actor, retry_id, observed_at)`仅对失败节点发放一次持久化受限恢复授权；输出增加明确的技术恢复摘要。普通`process`不发放新额度。

- [x] 先写“429→坏JSON→恢复成功”、length→32K、连续网络失败、规范化后崩溃、402终止、累计时间耗尽和重复retry_id的失败测试。
- [x] 实现第2节额度与状态：accepted/waiting_retry/recovery_required/terminal_error，外层继续使用兼容的processed/partial；不能让内部unknown异常被误报为可恢复格式错。同节点以非阻塞OS锁覆盖一次stage调用，竞争者立即返回busy（执行裁定，避免误把在途请求认作崩溃）；SQLite事务原子登记retry_id授权，网络调用不占用数据库事务；重复及并发提交同retry_id均只登记一个批次。
- [x] 保存错误类别、HTTP状态和经凭据脱敏的服务端错误摘要，避免再次只能看到HTTP400而无法判断契约问题。
- [x] 在同代码与同冻结输入版本内，Service重复处理/显式续跑只重进失败依赖组；accepted缓存直接返回。旧历史数据库不静默迁移计数，历史输出在新目录受控重放。
- [x] 运行恢复/Service专项；断言成功祖先调用数不变、已确认intent不增、原用量不丢、未知用量不写零。持续失败必须有可查询记录而非只抛异常。

## Task 3: SV05事项持久收录

**Files:** 修改`service.py`及必要的结果装配代码；新增`tests/test_issue_collection.py`。复用`sources.result`，无需新任务表或另一套存储。

**Interfaces:** 持久化`result.collected_issues`；`Service.collected_issues(sid, viewer)`读取它并沿用source_readable。每条包含稳定issue_id、source_id、statement、evidence_ids、retention_state=collected、resolution_state=open、can_add_task=false。ID由source版本和规范化后的命题/证据计算，重复处理不重复收录；新source版本不冒充同一事项。

- [x] 补齐SV05正常Service入口/重开SQLite测试（执行时在实现后立即补齐，非先RED；已记入progress.md）：讲义版本问题恰好一条，教室已答不进入待定列表，无虚构任务/owner；测试同段真实工作与未知问题并存。
- [x] 只从通过纪要核验的unresolved建立收录记录，随源结果事务持久化；不会根据未通过的工作解释编写新事项，不追加模型调用。
- [x] 在纪要未决部分以ID展示“已收录·待确定”，不重复显示同一条收录记录；工作分类冲突保留为系统诊断，与业务事项状态分开。没有明确命题映射时，不删除/合并另一条work记录。
- [x] 重复process、只重试工作、重开进程后均能查询；来源权限撤销后不可读取。收录不会创建任务或自动询问他人。
- [x] 运行事项收录及相关Service专项。SV05验收为“事项落袋且可追踪”；即使工作分类诊断仍在，也如实保留，不把它伪称为模型已经理解正确。

## Task 4: 最小验收与交接

**Files:** 新建本轮定向实验入口/manifest及结果报告，更新`docs/HANDOVER.md`；证据写入新的`runs/2026-11-17-incomplete-recovery/`。

- [x] 先离线重放两例全部失败响应，覆盖真实解析/转换/归约与Service持久化；正常对照用已有已接受输出验证不变。
- [x] 核心改动专项通过后，真实入口仅跑C14、SV17、SV05各1次，另选SV10一条正常工作对照各1次。只统计本机制自动恢复，不在外层重跑挑成功。
- [x] C14：成功交付经过校验的条件性调研结果；SV17：暂缓事项保留、不立即建任务，技术状态完整；SV05：版本问题有稳定收录记录、地点已答不重复追问。另验收重复process零额外模型调用/平台写入。
- [x] 若真实运行出现新故障，先冻结该节点调查，仅补受影响节点；不再启动20例或95×2。持续模型/接口失败就报告具体失败与可恢复状态，不无限追加尝试。
- [x] 报告分列本地规范化、模型恢复、等待/耗尽、事项收录结果、请求与用量。五项暂缓语义错误不作为本轮过关门槛，不改旧标注来提高分数。

实施顺序：Task1→Task2→Task3→Task4。执行已完成。人工续跑沿用累计600秒上限；跨代码修正的实验副本显式记录配置哈希，生产数据库不静默迁移。具体执行裁定和TDD顺序偏差见`runs/2026-11-17-incomplete-recovery/progress.md`。
