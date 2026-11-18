# 会议项目交接：字段缺口保留工作，承接语义仍需改进

更新时间：2026-11-15。默认 split-v3，实验 context-v1 协议5。项目没有Git，以源码快照和输入输出哈希追溯。用户要求日期缺口不能取消明确工作，已完成调研、计划、第一批程序修复与检验。

先读[本轮结果](field-preservation-results.md)、[设计](field-preservation-design.md)、[修改计划](superpowers/plans/2026-11-15-field-preservation.md)。之前的旧任务更新状态见[归档](HANDOVER-2026-11-15-task-updates-history.md)，错误溯因见[诊断](regression-error-diagnosis.md)。

## 当前能力

- 离线逐字稿→纪要/任务→会前回顾→跨会状态与决策版本，使用SQLite与任务模拟器。真实飞书尚未验收。
- context每8段维护实体和需求线索，后文可补全、纠正、撤回。隐式与模糊需求可由有权用户确认；未确认线索不跨会议继承。
- 已支持旧任务完成、重开、明确改期与取消期限；普通进度不重新要求承接。未出现的字段保留，改期不重写任务标题。
- 本轮新增 context_new_work.py：已明确相对期限保留文字、日期为空；承接不足或期限未定保留候选，只限制相关操作。事件和原核验不改写。
- 候选仍需确认，不执行有疑问的日期。时间错误混入工作描述时保留确认记录，不当作可信任务。内容/范围/指代/关系疑点和隐式目标仍限制执行。
- 不支持的旧任务内容/负责人修改显示执行受阻，只能dismiss。ask_issuer仅保存状态，不发送消息。

## 本轮验证

| 检查 | 结果及口径 |
| --- | --- |
| 中文8例 | 机械契约6/8→8/8，修复版冻结上游；非盲测、非全部语义通过 |
| 原6难例 | 内容F1 72.7%→90.9%；完全正确召回4/6→3/6，承接判断更保守 |
| 连续分工 | 首次时间操作结构失败，同配置恢复一次；内容3/3，完全正确2/3 |
| 最终独立M1/M2 | 首次12/12，无恢复 |
| 旧任务更新 | 原13例固定响应经最终Service重放，状态/日期/创建数通过 |
| 程序/兼容 | 119项测试；旧evidence 37份输出重算一致，task_events.py未改 |

独立审查两项Important均已做失败测试→修复→全量通过。模型新增87次、369,056 token，包括首次失败与恢复，不重复计算缓存。所有模型运行结束，标注与语义复核均为代理。

## 仍需修复

1. 短回应承接：C02的Yep被过度怀疑，市场Okay也保守降为候选。市场标签本身标有归属不确定，C02标签无此标记。工作留住了，不代表承接识别正确。
2. 研究目的：C09仍缺具体目标，确认问题笼统。限定一次重新解释再核验也未解决，不能靠循环强制通过。
3. 修饰对象：FP02把工作未约定截止时间写成合同条款没有期限；机械日期检查通过不等于描述完全正确。FP07隐式需求的问题仍混合多个缺口。
4. 核验纠错：隔离实验补回旧UI且不把邮件变任务，建议也恢复；生产尚无自动修正通道。实验有诊断反馈，不代表系统会自动定位问题。
5. 没有下一场会议日程查询/事件绑定；旧标题可能留历史日期；多次矛盾更新、偶发结构失败及真实飞书契约仍未解决。

下一轮优先验证回应与具体要求的绑定，禁止凭空构造竞争回应对象；研究目的与澄清问题另设口径。保持默认策略，不将内容F1提高等同整体提升。

## 原件与复现

目录 `runs/2026-11-15-field-preservation/`：before/initial/final快照；baseline/repaired中文配对；regression/context为初版模型调用；context/first-pass保留结构失败；trace-replay用最终代码重放旧新响应，零调用；repair-probe为隔离一次修正；replay-final为最终独立回放。

```powershell
python -X utf8 experiments/field-preservation/summarize.py
python -X utf8 experiments/action-evidence/summarize.py
python -X utf8 -m unittest discover -s tests -v
```

[汇总](../runs/2026-11-15-field-preservation/summary.json) · [测试](../runs/2026-11-15-field-preservation/final-tests.log) · [最终校验](../runs/2026-11-15-field-preservation/final-verification.json) · [使用方法](context-workflow.md)
