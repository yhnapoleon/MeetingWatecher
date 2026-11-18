# 前置能力修复计划

设计：[工作边界、字段缺口与问题关闭](../../action-context-prerequisites-design.md)。用户授权当前会话实施；本会话直接实现，最终独立复核。项目无 Git，用源码快照替代 worktree/commit，保留进度和验证原件。

全局约束：默认策略与旧标签不变；不扩大调用步骤；不按案例 ID 编码结果；不绕过权限、承接、时间及旧任务关系检查。

## Task 1：工作边界

- 修改 `prompts/track-context-context-v1.txt`、`interpret-work-context-v1.txt` 的工作身份/背景约束规则。
- 增加 `tests/test_context_prerequisites.py`：同引文两记录独立处理，必要范围仍阻断，保留后文补全。
- 冻结新行为准则和源码快照；通过正常入口对 C20/C21 试验，保存前后真实输出，不以程序测试冒充模型质量。

## Task 2：核验缺口分别判断

- 修改 `check_records(raw,records,meeting)`，校验非支持结果的 issues；输出 check.issues。
- 修改 `reduce_context(...)`，局部 owner/commitment/question 问题不污染内容，仍按原事件与缺口阻止写入。
- 修改核验提示并增加测试：局部疑点保留、owner/commitment 不自动写入、错误内容/时间/关系仍阻断、未知 issue 拒绝。
- 运行 `python -m unittest discover -s tests -p test_context*.py -v`，预期全部通过。

## Task 3：已解决问题关闭

- 在 ledger/record 类别中支持 resolved，核验后关闭；修改三阶段提示。旧任务 completed/existing 不改变。
- 测试 resolved 有证据才关闭、不生成新任务；真实 CP03/CP02/CP04 检验取消和约束，CP05 检验无动作实体。
- 提升 ContextPipeline 协议版本，使新输出不会复用旧协议缓存。

## Task 4：真实检验和独立审查

- 运行六个难例与连续窗口、中文八例，完整复核，重点样例重复验证；已有语义及行为评分继续使用冻结口径。
- 独立审查实现、权限和旧任务更新；必要修复做失败测试→修复→全量测试。
- 更新结果报告和 HANDOVER，保留首次结构失败、恢复、成本与限制；质量未通过则不切默认。

Review Focus：核验 issue 与事件判定冲突时不能放行自动执行；已解决记录不能屏蔽同原话中的另一项未决工作；取消不能关闭善后或别的活动；明确任务不能被旁边模糊材料阻断；旧实验原件可继续审计。
