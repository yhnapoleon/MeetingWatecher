# GN29解释预算与分批处理修复计划

> **For agentic workers:** 执行时使用superpowers:executing-plans逐项实施。任务使用复选框跟踪，条件阶段不得自动扩大执行范围。2026-11-17第一阶段已执行；结果见 ../../interpret-budget-results.md。

**Goal:** 在有界请求预算下恢复GN29任务输出，以冻结任务P/R验收，并检查GN25条件任务是否保留。

**Architecture:** 先开放官方支持的low参数，用固定输入验证现有32K上限能否完成解释。若生成规模仍阻塞，再按完整线程限定批次输出、保存接受结果，并通过局部核验和全局差异核对后提交现有任务处理入口。

**Tech Stack:** Python 3.13、标准库unittest、现有DeepSeek客户端与run_stage、SQLite Simulator；不新增框架依赖。

**Spec:** [调研与设计](../../interpret-budget-research.md)。实施前阅读该文与[当前结果](../../interpret-reliability.md)。

## Global Constraints

- 原制定阶段仅调研；用户2026-11-17随后授权实施与测试，第一阶段按下述上限执行。
- 冻结标签、历史结果与默认split-v3保持原状；context-v5默认high也不因实验自动更改。
- 只跑受影响离线检查和必要真实样例；不跑60/115全量。
- 不逐例新增语义分类提示；标签不得进入模型输入。
- 每次实验新建输出目录并保存源码、输入与配置摘要；不覆盖既有run。
- 本地没有Git仓库，以源码快照与变更清单保留版本，不执行虚构的提交步骤。

## Review Focus

- low与high请求不能误用同一接受缓存；由任务1测试。
- 接口拒绝low、空白JSON或截断响应不能被标记成功；由任务1、2测试。
- 同一工作后文取消、短回应承接、条件性支付必须保留完整上下文；由任务3、4测试。
- 同一人物涉及不同工作不能误合并，跨批同一工作不能重复落地；由任务4测试。
- 中断后成功批不重跑、额度不重置、未核验任务不提前发布；由任务2、5测试。

## 第一阶段：低强度受控实验

### 任务1：增加显式low支持

**Files:** 修改`meeting_eval/model_client.py`；扩展`tests/test_inference_config.py`。

- [x] 增加失败测试：enabled+low原样发出；low/high产生不同缓存；disabled+low仍拒绝；其他供应商不因新增low而绕过现有能力限制。
- [x] 执行`python -m unittest discover -s tests -p test_inference_config.py -v`，确认新增low用例因现有白名单失败。
- [x] 在`inference_parameters(model, max_tokens, inference=None)`扩展允许值为low/high/max。默认值和其他参数规则保持现有契约；不顺带支持medium别名。
- [x] 重跑该文件，全部通过；模拟请求确认配置已纳入Extractor/节点身份，不输出凭据。

### 任务2：固定输入、限额执行与任务验收

**Files:** 新建`experiments/interpret-budget/run.py`、`experiments/interpret-budget/audit.py`、`tests/test_interpret_budget_experiment.py`。复用旧实验审计和Service，不修改旧runner或已有run。

**Interfaces:** `load_frozen_case(case_id: str) -> dict`返回已校验的meeting/history/ledger及来源哈希；`reserve_request(state_path: Path, limit: int = 8) -> None`在实际HTTP发送前原子持久化占用一次额度，耗尽抛异常。runner串行执行，禁止并发造成额度竞态。

- [x] 写故障注入测试：任意原文或ledger摘要不匹配拒绝复用；第9次请求在网络前拒绝；重启仍从已占用额度继续；HTTP失败也占用；能力400不退回high；金标不进入请求。用临时目录和mock网络验证。
- [x] 实现实验入口，先离线导出请求与manifest。固定两例最近一次完整tracking、原提示及契约；显式只覆盖interpret_work为enabled/low/32768。记录requested/response model、生成与推理token、finish_reason、复用阶段、调用数及所有失败。
- [x] 解释通过后使用现有核验、有限修复和任务归并/SQLite入口；只为任务分支验证，不重新调用纪要模型。审计标注该实验不是全会议重新生成。
- [x] 执行`python -m unittest discover -s tests -p test_interpret_budget_experiment.py -v`，全部通过；另复跑`test_inference_config.py`、`test_stage_recovery.py`、`test_reference_repair.py`，确认相关缓存和恢复契约。
- [x] 实施阶段才运行`python experiments/interpret-budget/run.py --out runs/2026-11-17-interpret-budget-low --cases GN29 GN25 --max-requests 8`。GN29若仍length或能力不支持low，停止后续付费节点并留证。
- [x] 执行`python experiments/interpret-budget/audit.py --out runs/2026-11-17-interpret-budget-low`。独立报告技术完成、任务识别P/R、完整字段、落地状态和成本；既有high结果作为历史对照，披露非同期及模型版本限制。
- [ ] 验收目标未通过：GN29=8/8但7FP，GN25=2/3。原目标GN29=8/8、GN25=3/3、新增FP=0。失败按解释/核验/归并归因，不改标签。满足目标则结束本次结构修复，不实施第二阶段；low完整但有语义漏项时先评估质量，不自动启动分批。

## 第二阶段：仅生成规模仍造成未完成时实施

本轮未触发：两例low解释均完整，余下是任务语义质量问题。以下任务保持未实施。

### 任务3：批次边界与结构契约

**Files:** 新建`meeting_eval/interpret_batches.py`、`tests/test_interpret_batches.py`；修改`meeting_eval/context_v5.py`，新增`prompts/interpret-work-batched-v1.txt`。

**Interfaces:** `plan_batches(ledger: dict, *, max_threads: int = 4, max_updates: int = 8) -> list[dict]`返回稳定batch_id/target_thread_ids；`merge_batches(results: list[dict], ledger: dict, meeting: dict) -> dict`分配全局ID并验证结构全覆盖。批次协议新增cross_batch_links，由程序校验引用的线程存在且确实跨批。

- [ ] 写测试：完整线程不拆开；4线程/8update上限；单个超限线程独占；空ledger；公共人物不合并全部线程；乱序完成不改变ID；未知/遗漏/重复目标线程拒绝。
- [ ] 离线用GN29/GN25 ledger生成批次清单，输出实际B、每批update数及请求输入字节估计。字符/字节估计不得标为实际计费token。
- [ ] 每批保留全文与全局只读索引，目标线程及其完整update作为输出责任范围。允许全文证据引用；超范围线程只能进入cross_batch_links，不能偷偷新增另一批记录。
- [ ] 将实体补齐移到全局合并后执行一次；程序重写records/events引用。批内覆盖只验证target_thread_ids，合并后复用全局canonical_records约束，不削弱旧入口校验。
- [ ] 执行`python -m unittest discover -s tests -p test_interpret_batches.py -v`；原`test_context_state.py`、`test_context_wire.py`通过。

### 任务4：限定核验输出及全局查漏、归并

**Files:** 新建`meeting_eval/batch_review.py`、`tests/test_batch_review.py`、`prompts/check-work-global-v1.txt`；修改`meeting_eval/context_v5.py`、`meeting_eval/context_protocol_v5.py`，按需要复用`meeting_eval/context_coverage.py`。

**Interfaces:** `global_review_contract(payload: dict) -> tuple[dict, dict]`产生绑定scope的差异结构与绑定信息；`validate_global_review(raw: dict, payload: dict) -> dict`验证差异只引用已知记录/线程，新增遗漏必须有原文证据。差异类型限定missing/duplicate/conflict/cross_batch，不能直接携带替换整份结果。

- [ ] 测试跨批重复工作只落地一次、同人不同任务保持独立、后文取消阻止建任务、短回应可引用前文、条件付款保留条件、同一发言中的第二项工作仍可被发现。
- [ ] 批次核验只输出本批记录/事件字段判断，其他记录只读；全局核对单独输出差异。沿用原核验语义政策，不用批次校验的“线程已覆盖”代替任务完整性。
- [ ] 把差异转成现有有界修复的明确目标或带证据新增候选；核验后的重复处置明确保留目标与被合并来源。跨批关联需解决后才可结束，未解决标记partial，不静默丢弃。
- [ ] 对新增或修改记录执行独立recheck；禁止未选中记录被改写，禁止把不同任务仅凭相同实体/相似描述自动合并。
- [ ] 执行`python -m unittest discover -s tests -p test_batch_review.py -v`及`test_context_v2_contract.py`、`test_check_transport.py`、`test_context_v5_regressions.py`，确认原路径契约仍有效。

### 任务5：集成恢复、限额与定向验收

**Files:** 修改`meeting_eval/context_v5.py`和实验runner；新增`tests/test_batch_recovery.py`。批次运行状态与源码摘要进入新版本配置，旧缓存不能被误认作分批结果。

- [ ] 以mock故障验证：第2批失败后第1批接受结果仍可用；重启仅续失败节点；输入/提示改变不复用旧结果；全局核对失败不发布任何未验证任务；请求限额跨重启不重置。
- [ ] 复用run_stage执行批次及全局节点，保持每节点现有限额。批次串行，初始high/16K、长度恢复32K，引用补丁8K；不递归二分、不追加全场重抽。
- [ ] 将任务2的实验额度用于第二阶段，独立新run上限4B+8；保存待处理批次、失败原因和接受结果。离线清单确定B及费用估计后再执行，不从阶段一自动启动付费实验。
- [ ] 执行`python -m unittest discover -s tests -p test_batch_recovery.py -v`及受影响的阶段恢复/Service入口测试。
- [ ] 先只跑GN29，结构、核验、SQLite落地和冻结8项任务全部检查；通过后GN25检查3项任务及条件保留。重复调用、关闭并重开数据库确认不重复建任务。
- [ ] 汇总完整尝试成本，分别报告技术完成与任务P/R；未达目标保留失败结论，不临时扩大预算。不重跑全量，不宣称普适性已经成立。

## 文档与收尾

- [x] 更新HANDOVER和专项结果，给出代码版本、复用范围、实际付费请求数、任务逐目标匹配和未解决事项。
- [x] 自查计划与设计一致：分批只有生成规模阻塞时启用；原文完整性、跨批归并、额度和发布边界均有对应测试。
- [x] 第一阶段实际结果与限制已写入报告；第二阶段未触发，任务质量门槛未过。
