# 查看和处理待确认需求

`context-v1` 在同一场会议内分段保存实体及工作线索，后文可以补充、纠正或撤回；会后展示隐式需求和模糊工作。当前实验协议为6，支持旧任务状态及截止日期更新、正常上下文承接及一次核验纠错。效果与成本见 [本轮验证报告](pragmatic-checking-results.md)。

核验发现错误时，系统限定对应记录重新解释并核验一次，其他记录保留。修正步骤调用或结构失败时使用初次核验的结果，待确认记录仍可人工处理；trace.repair 保存前后结果和错误。同一来源不会因反复导入而继续修正。只有首次解释、首次核验等必需步骤失败时，走原有 partial 恢复流程。repair_work/check_repair 推理配置默认分别继承 interpret_work/check_work，也可单独配置。

## 导入与查看

在项目目录运行，模型凭据使用已有环境配置：

```powershell
python -m meeting_eval --db runs/my-context/state.sqlite ingest examples/m1.json --actor host --out runs/my-context --strategy context-v1 --inference-config experiments/action-context/compact-check.json
python -m meeting_eval --db runs/my-context/state.sqlite requirements <source_id> --viewer host
python -m meeting_eval --db runs/my-context/state.sqlite minutes <source_id> --viewer host
```

`source_id` 取导入返回值。`requirements` 列出稳定的 `record_id`、可能含义、原话、缺少的字段、确认问题、建议询问的提出方及现有处理结果。隐式需求是推测，不代表会议已经决定执行。`entity_only` 原文对象保存在 `_task_trace.ledger` 或记录中，不默认生成任务。

当前是对已取得逐字稿的离线分段处理，每 8 段检查一次新增信息。不是实时接入飞书会议；未确认线索尚不自动跨会议继承。已创建任务仍通过原有跨会议任务上下文处理。

## 旧任务汇报与更新

对于新工作，“下次会前”这样的明确相对期限可以保留为 `due_text`，`due_date=null`；不会仅因尚未换算日期就要求补日期或移除任务。承接或日期本身尚未决定时保留候选及对应问题，候选不会自动写入模拟器。内容、范围或描述里的日期被核验否定时，继续保留可见确认记录，不能将其当成已核实的任务。

已唯一关联的旧任务可以完成、重开、改期或取消期限。仅汇报进度时保留汇报，无需再次承接；没有新的时间陈述则保留旧期限。例如负责人明确把期限改到 2026-11-20 后，`due_date` 更新为该日期，`due_text` 保存对应原文；明确取消时两者一起清空。执行仍检查身份、证据、权限和旧值。

试探性的改期保留原日期，显示具体确认问题。内容修改、换负责人等当前不支持的变更显示“执行受阻”及原因，这类记录只能 `dismiss`。改期不自动重写标题，因此标题可能含历史期限，当前期限以结构化字段和纪要更新为准。

## 人工决定

将决定写入本地 JSON，再通过同一 CLI 提交。加入任务时必须明确最终内容和负责人，不能只点击一个含糊标题：

```json
{
  "decision": "add_task",
  "description": "此处填写确认后的完整工作内容",
  "owner_ref": "chen",
  "due_date": null,
  "due_text": null
}
```

```powershell
python -m meeting_eval --db runs/my-context/state.sqlite resolve-requirement <source_id> <record_id> --actor host --input decision.json
```

示例 `chen` 来自 `examples/m1.json` 的明确身份映射；实际输入须提供已授权的 `account_map` 或 `speaker_map`。公开语料中的人物代号不会自动变成平台账号。

另外两种决定：

- `{"decision":"dismiss"}`：忽略本条需求。
- `{"decision":"ask_issuer"}`：保存待向提出方询问的状态和问题；不会发送消息，可以随后再确认或忽略。

确认人必须能读取该来源并具有写权限，负责人必须有明确账号映射且在来源受众内。存在未解决的旧任务关系时，不能从这里绕过关系核对直接新建。任务写入本地模拟器，仍经过意图、回执、失败恢复；人工决定单独记入审计，不伪装为会上原负责人的承诺。

同一来源和记录的相同最终决定重复提交，复用原结果；改变最终决定内容会报冲突。来源修订后，旧记录不再允许新确认，尚未发送的旧确认也不会重发。写入已成功但回执丢失时，恢复只读回原任务。

```powershell
python -m meeting_eval --db runs/my-context/state.sqlite recover --actor host
```

`task_guid` 与 `intent_status=confirmed` 表示创建已回读确认；`unknown` 表示写入尚未确认，不能当作任务已经创建。幂等范围是同一 `record_id`；当前模型可能为同一工作给出多条确认记录，需先核对原话，不能把每张卡都加入任务。

## 复现评测

```powershell
python scripts/run_meeting_eval.py --strategy context-v1 --inference-config experiments/action-context/compact-check.json --data-dir data/action-semantics-v2/regression --cases C02 C03 C09 C20 C21 C26 --out runs/my-context-eval
python scripts/run_meeting_eval.py --strategy context-v1 --inference-config experiments/action-context/compact-check.json --data-dir data/context-probes-v1 --out runs/my-context-probes
python scripts/replay_mvp.py --strategy context-v1 --inference-config experiments/action-context/compact-check.json --out runs/my-context-replay
```

修改模型、代码、提示或配置后使用新数据库与目录。恢复调用/结构失败时保持原配置，重跑原命令；成功步骤不会重新采样。语义判断不理想不属于可重试的调用失败。

冻结语义标签与行为契约分别评分。合成样例是机制检查，不能称为未见会议盲测。已有复核的校验与汇总不调用模型：

```powershell
python experiments/action-context/summarize.py
python experiments/action-context/summarize_prerequisites.py
python experiments/task-updates/summarize.py
python data/context-probes-v1/verify.py
```
