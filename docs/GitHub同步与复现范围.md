# GitHub 同步与复现范围

代码仓库：[yhnapoleon/MeetingWatecher](https://github.com/yhnapoleon/MeetingWatecher)，分支 `main`。此仓库保存进入 demo 准备阶段的当前代码；最新接手任务见 [HANDOVER](HANDOVER.md)。

## 提交内容

保留 `meeting_eval`、`prompts`、`scripts`、`tests`、`experiments`、`examples`、`docs` 和必要文本数据，并提供 [v19 推理配置](../config/context-v5-v19.json)与[环境变量模板](../.env.example)。两个新会议的原文、重注参考、可接受答案、逐条复核、最终纪要、指标及验收摘要按明确清单保留在 `runs/2026-11-18-two-unseen-v19/`。

历史模型请求/响应、SQLite、源码压缩快照、原始语料压缩包、音视频和旧泛化数据工作目录仍在原工作区，不上传。凭据及缓存由 `.gitignore` 排除。原文件未删除；`.gitattributes` 保持文件字节，避免 Git 换行转换改变冻结参考的哈希。

仓库中的历史文档保留原记录。指向未提交 `runs/`、原始数据或本机绝对路径的链接属于本地历史证据入口，不代表这些文件能从 GitHub 下载。特别是完整审计 `audit_unseen.py` 需要数据库、模型节点和源码快照，在原工作区可运行，单独克隆此仓库不能完整重放历史运行。

## 克隆与离线验证

Python 3.11+，核心代码使用标准库。

```powershell
git clone https://github.com/yhnapoleon/MeetingWatecher.git
Set-Location MeetingWatecher
$env:PYTHONUTF8='1'
$env:PYTHONPATH='tests'
python -m unittest test_unclear_intent test_context_system test_requirement_review test_report_routing test_context_state test_context_v5_regressions
python -m meeting_eval --help
```

以上定向测试使用仓库内夹具，不请求真实模型。`unittest discover` 中有依赖本地历史响应/数据库的归档回归，主要在 `test_extraction_repair`、`test_full_meeting_recovery`、`test_task_boundary`、`test_user_solutions`；完整历史库未发布，不能将直接全库发现的缺文件错误当作新代码回归。已有历史断言失败见交接记录。

为使上述核心命令可独立运行，CP02复检协议测试所需的业务输入已从历史请求中提取到 `tests/fixtures/cp02_recheck_payload.json`，测试直接读取该夹具；未改产品逻辑，也不需要发布历史HTTP元数据和系统提示。

2026-11-18首次发布前，已在仅含待提交文件的独立目录验证上述56项测试全部通过、CLI帮助可用，且两场输入/参考/规则的字节哈希与冻结清单一致。

## 用当前配置进行新推理

复制 `.env.example` 为 `.env` 并填写自己的模型凭据，或设置同名环境变量。不要使用仓库外旧工作区的隐式配置路径。

普通 CLI 的默认策略仍为 `split-v3`，`ingest` 尚无决策核验开关。要使用本轮完整 v19 链路，在新目录下通过 Service 构造提取器：

```python
import json
from pathlib import Path
from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store

out = Path("runs/demo-local")
assert not out.exists(), "Use a new output directory"
out.mkdir(parents=True)
settings = json.loads(Path("config/context-v5-v19.json").read_text(encoding="utf8"))
extractor = Extractor(Path(".env"), out / "model", "context-v5",
                      inference_config=settings, review_decisions=True)
meeting = json.loads(Path("examples/m1.json").read_text(encoding="utf8"))
store = Store(out / "state.sqlite")
try:
    service = Service(store, extractor)
    result = service.process(meeting, "host", "2026-11-09T10:02:00+08:00")
    print(result["status"], result["source_id"])
    print(service.minutes(result["source_id"], "host"))
finally:
    store.close()
```

该示例会调用模型并写入本地模拟器；它是当前 API 的使用入口，不代表已经完成 demo 彩排。真实飞书写入尚未联调。

## 数据来源与许可

仓库内 AMI 片段与两场完整转写来自 AMI Meeting Corpus 人工标注包1.6.2，原摘要及说话人元数据保留，项目增加结构转换、任务/决策重注与中文解释。来源、修改和场景性质见 [数据说明](../data/mvp-v1/README.md)，许可副本为 [CC BY 4.0](../data/licenses/AMI_CC_BY_4.0.txt)。

VCSum 文本样例来自 Wu 等发布的固定版本，出处见同一数据说明及[语料调研](corpus-study.md)，仓库许可副本见 [VCSum MIT](../data/licenses/VCSum_MIT.txt)。历史说明中的 `data/mvp-v1/raw/` 许可链接对应本地原件，GitHub 读者使用这里的许可副本。原始语料包与媒体按来源说明自行取得；此仓库未为项目自有源码另行指定开源许可证。
