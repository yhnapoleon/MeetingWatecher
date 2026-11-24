# 配置与运行说明

## 环境与入口

| 用途 | 环境 | 入口 |
| --- | --- | --- |
| 阅读报告、视频和材料 | PDF、浏览器或视频播放器 | 三份 PDF、演示视频与测试用例 |
| 核对选定评测 | Python 3.11+，标准库 | scripts/verify_release_evidence.py |
| 完整应用 | Python 3.11+、Node.js 22+、自备模型凭据 | meeting_copilot + demo/?showcase=1 |
| 对新逐字稿推理 | Python 3.11+、自备模型凭据 | scripts/run_current.py --live |
| 核心与 Copilot 离线检查 | Python；Copilot 需要其锁定依赖 | 下方定向测试 |

将 `04_源码_MeetingWatcher.zip` 解压到新目录，下面命令除注明外均在解压后的项目根目录执行。代码、data、runs 和 docs 保持原工程相对路径，无需另行搬运。先运行 `python scripts/verify_submission.py` 核对文件并执行离线检查；安装 Copilot 依赖后可添加 `--copilot` 检查实时助手。

## 启动完整应用

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r meeting_copilot/requirements-lock.txt
Copy-Item .env.example .env
# 编辑 .env，填写自己的模型凭据。
.venv/Scripts/python.exe -m meeting_copilot --env .env --data runs/my-copilot --port 8766
```

新终端进入项目的 demo 目录：

```powershell
npm ci
npm run dev -- --host 127.0.0.1 --port 4173 --strictPort
```

浏览器打开 http://127.0.0.1:4173/?showcase=1 。从项目进入第一场，会议自动开始，动态纪要按新增稳定转写更新；选择“行动事项与跟进”，核对自动生成的候选并确认。也可打开项目助手，用文字追问或整理分工。第一场归档后在项目中新建第二场，用 Alt+I 邀请上场成员，进入会议后查看新要求、研究汇报及原任务更新。

项目列表与邀请状态保存在浏览器 localStorage，账本、作业、检查点和材料保存在 `--data` 目录。新一轮运行使用新数据目录和新的浏览器配置；回看已保存结果使用原目录。邀请接受与任务写入在本地执行。

前端默认代理 `/api/copilot` 到 127.0.0.1:8766。自选端口时先设置 `$env:COPILOT_API='http://127.0.0.1:8767'`，再启动 Vite；后端端口相应使用 `--port 8767`。`showcase=1` 是完整实时助手视图的路由开关，`review=1` 提供开发定位工具。直接打开静态 index.html 不包含 API 服务。

## 模型和输入

| 配置 | 用途 |
| --- | --- |
| OPENAI_API_KEY | 模型接口凭据，仅保存在自己的 .env 或环境变量 |
| MEETING_MODEL | 当前实测模型 deepseek-flash |
| MEETING_API_BASE | API 基础地址；模板为 https://api.deepseek.com，客户端追加 /chat/completions |
| --data | 实时助手的运行目录 |
| --history-db | 可选整会历史数据库 |
| --search-key | 可选外部检索密钥文件；基础会议流程无需配置 |

默认会议素材为 demo/public/scenario-cross.json、audio/ami-es2002-bc.mp3 和 video/ami-es2002-bc.mp4。两场共 782 秒，字幕来自实际 STT 词轴；说话人与原始时间映射见[媒体署名](../demo/public/MEDIA_CREDITS.md)。输入按游标释放给模型，纪要和任务由当前调用生成。在线 ASR 接入与真实飞书写入尚需联调。

## 离线检查

```powershell
$env:PYTHONUTF8='1'
python scripts/verify_release_evidence.py
$env:PYTHONPATH='tests'
python -m unittest test_unclear_intent test_context_system test_requirement_review test_report_routing test_context_state test_context_v5_regressions
.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_copilot*.py'
Set-Location demo
npm test
npm run typecheck
npm run build
npm run test:sites
```

公开证据检查核对两场新参会组输入、参考和规则的冻结哈希，并从逐条判分重算指标；它不调用模型，也不重新判断语义。核心定向测试使用随附夹具。完整工作区的部分历史测试还依赖原始请求与数据库，因此全库发现测试不是提交入口。

前端 build 产生 dist/client、dist/server 和 dist/.openai/hosting.json；静态构建不打包 Python 服务。Copilot 需要其依赖，整会核心检查只用标准库。

## 新逐字稿的整会提取

```powershell
python scripts/run_current.py --input examples/m1.json --out runs/my-meeting
python scripts/run_current.py --input examples/m1.json --out runs/my-meeting --actor host --live
```

默认预检不会请求模型或创建输出目录；添加 --live 才执行推理，要求全新输出目录。入口明确使用 context-v5 v19 + DecisionReview v2；普通 `python -m meeting_eval ingest` 默认仍为 split-v3。输入包含会议 ID、series、participants、segments 和需要时的 account_map，actor 须为授权主体。

config/context-v5-v19.json 指定：track_context high / 16384，interpret_work low / 32768，check_work high / 16384。其余阶段采用提取器配置。结果保存输入、推理配置、模型阶段、结构化结果、纪要、候选及 SQLite。重新汇总已有评测不等于重新推理。

## 提交内容与复现范围

项目材料外层提供三份报告、源码 ZIP、115 场景测试用例、架构图和最终视频。源码包内保留初始数据与标注、冻结评分摘要、两场新参会组文本证据、当前双场应用核查记录及必要代码和媒体。历史完整请求、数据库与原始录制帧留在原工作区。115 场景可检查评分原件和逐单元索引；两场新参会组可直接复算保存判分，完整历史模型重放需要相应运行原件。

报告的 Markdown 为可编辑正文，PDF 为同一正文的阅读版。在完整源码工作区安装 markdown、playwright 后可运行 `python scripts/render_reports.py` 重新生成；生成依赖本机 Microsoft Edge。视频源文件和本次材料列于提交说明，章节与观看重点见[展示流程](AI参会助手_双场会议演示剧本.md)。
