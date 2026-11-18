# 首批标注的来源与输入格式

本批次围绕“有身份的发言能否抽成正确任务”准备四段材料。标注人按 input.jsonl 逐段阅读，在 annotations.csv 复核任务、操作与证据。相邻两场周会另有完整的会前状态和预期结果。

| 样本 | 原件、取样范围与用途 | 能看见的身份 |
| --- | --- | --- |
| M1、M2 | 项目编写的两场中文周会。分别包含跨句认领、暂缓、决策变更和对原任务的完成报告；模拟时间和账号。会前回顾仍使用原有任务快照。[M1](../../examples/m1.json) · [M2](../../examples/m2.json) · [会前快照](../../examples/before_m2.json) | 模拟上游已解析的陈可、王宁及稳定人员引用。M1 的“说话人 2”和 M2 的“陈可”均映射到 chen。 |
| M3 | 项目编写的中文最小对照。甲向乙分派任务，乙作出回应。发言人与负责人需分别标。 | 两位发言人的姓名和人员引用。 |
| V65 | VCSum 开发集，固定提交 8e51d72e4e6f3af4074fd5b260b6f6d2e75e86c7，文件 short_dev.txt 的 SHA-256 为 6414aa52153aba24dfc4a99c43ec24a47a61361c0d8372ac0e4972d3b41cc4dd。视频号 972550220、片段 65_0、发言组 1，取句下标 1 和 4（均从 0 开始，非连续摘录）。用途为主持人对会内活动的预告。[作者与原始开发文件](https://github.com/hahahawu/VCSum/blob/8e51d72e4e6f3af4074fd5b260b6f6d2e75e86c7/vcsum_data/short_dev.txt) · [论文](https://aclanthology.org/2023.findings-acl.377/) | 原始 speaker 值 2；时间窗、姓名和账号均未知。保留原转写措辞。 |

**下一批直接取已有标注的多人会议。** 英文先取 AMI 的 ES2002a。已核对人工标注包 1.6.2，摘要含 3 条行动、3 条决策。行动标签 `ES2002a.rdhillon.s.4` 通过 `extractive/ES2002a.summlink.xml` 链到发言人 B 在 00:16:25.490–00:16:34.810 的分工发言，负责人是工业设计师。先回看这一段前后各约一分钟，补录对方是否承接及有无期限。保留 AMI 来源与 CC BY 4.0 署名。中文有视频需求时选 MISP-Meeting，有行动句标签需求时选 AliMeeting4MUG。[ES2002a 视频](https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/ES2002a/video/) · [AMI 人工标注包](https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip) · [授权说明](https://groups.inf.ed.ac.uk/ami/)

## 妙记原件与统一输入

首版采用公开示例为文本格式标准。每段首行写“发言人 HH:MM:SS.mmm”，下一行写原话，段间空一行。缺时间则首行仅保留发言人，内部字段为 null。有核实的姓名或角色时直接展示，只有匿名标签时保留源标签。配套 JSONL 用于评分。[公开样例](https://github.com/YunfanGoForIt/Smart-Minutes-Open/blob/17daef01330aed03d8cce38ebfe03c47ebd744c1/README.md#L106-L121)

飞书帮助中心说明基础版的妙记转写有使用额度，超过额度后新生成的妙记不显示文字记录。已有文字记录能否导出，取决于该篇妙记的权限设置。公开样本与模拟样本的标注可先行。[飞书帮助中心](https://www.feishu.cn/hc/zh-CN/articles/022111234449-%E6%9F%A5%E7%9C%8B%E5%A6%99%E8%AE%B0)

选用妙记文字记录导出接口，带 `need_speaker=true`、`need_timestamp=true`，`file_format=txt` 或 `srt`。成功结果是文件流。名字、匿名标签、段边界及文字排版以收到的文件为准。记录中有平台确认的身份时，主评测保留这个身份。导出只有展示名时先保留展示名；要给出可跨会的人员引用，须有可信的账号绑定。CLI 说话人列表的 speaker_id 可区分本场说话人；平台账号映射需单独核对，同名不能自动合并。[官方导出接口](https://open.feishu.cn/document/minutes-v1/minute-transcript/get.md)

**input.jsonl 每行是一场会议或一个明确标出的摘录。** started_at 用带时区的时间。每一段保留 id、start_ms、end_ms、speaker、speaker_name、person_ref、text。speaker 保留源标签，speaker_name 和 person_ref 仅填上游已提供、当前身份可见的信息；人员引用可以是脱敏别名，写任务时由适配器解析账号。采集端用原会议资源权限过滤后再生成模型视图。公开摘录以 null 表示未提供的字段。时间戳相对于录制开始；文件内没有音频的模拟时间仅供走读。

**annotations.csv 只给标注人与评分端。** 一行表示一个候选或更新，event_type 区分认领、分派、会内安排、暂缓、进度、决策；operation 记录会后动作。owner_ref 填任务实际负责人，speaker 的身份已经在输入中。用 evidence_ids 关联多句（竖线分隔），target_guid 仅在更新已存在任务时填。status=draft 表示设计草标。复核后可增删行，修改答案并填 reviewer 与 status=reviewed；模型评测应注明使用哪个标注版本。单独测试“上游错认人”时，保留原标签作为输入，人工身份作为诊断答案。
