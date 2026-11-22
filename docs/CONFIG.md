# 配置与运行说明

## 1. 选择运行方式

| 要完成什么 | 入口 | 环境及外部条件 |
| --- | --- | --- |
| 查看连续会议界面 | demo 网页 | Node.js 22+，npm；初次安装需网络，播放不需要模型 key |
| 阅读已保存结果 | docs 与选定 runs 文本 | 不需要模型、数据库或 STT 服务 |
| 核对公开评测证据 | scripts/verify_release_evidence.py | Python 3.11+，标准库，无模型请求 |
| 运行后端离线核心检查 | unittest 定向套件 | Python 3.11+，标准库 |
| 对新逐字稿推理 | scripts/run_current.py --live | 自备模型凭据和网络，写入新 SQLite |
| 实时识别播放中的音频 | demo/scripts/stt_server.py | faster-whisper 等可选依赖，首次下载模型 |
| 重录演示视频 | demo/scripts/video/record_continuous.py | Playwright、Edge、FFmpeg、numpy、scipy；使用新目录 |

下面命令使用 PowerShell；除注明外均在项目根目录执行。Python 核心不需要安装第三方包；前端安装版本由 package-lock.json 固定。历史实验目录不要求重新创建。

## 2. 前端：直接播放已提供素材

```powershell
Set-Location demo
npm ci
npm run dev -- --host 127.0.0.1 --port 4173 --strictPort
```

浏览器打开 http://127.0.0.1:4173 。从项目进入第一场会议，加入现场后自动播放。AI 视图约占七成，原话查看不暂停；正常页面没有暂停、进度条和倍速。第一场结束后归档并查看项目承接，再现场创建第二场、用 Alt+I 邀请原班成员、进入下一场。邀请接受在本地模拟。

默认场景为 public/scenario-cross.json，音视频分别为 public/audio/ami-es2002-bc.mp3 和 public/video/ami-es2002-bc.mp4。两场素材总长 782 秒，字幕使用 small.en 实际识别词轴；中文事件和自动确认来自场景文件。浏览器 localStorage 保存项目状态；需要重新演示时使用新浏览器配置或只清理该站点存储。

`?review=1` 仅用于开发时间轴、定位及 STT 模式调试，不能用其播放控件说明普通界面的交互。详细场景字段见[前端说明](../demo/README.md)。

```powershell
npm test
npm run typecheck
npm run build
npm run test:sites
```

构建同时生成 dist/client、dist/server 和托管描述。测试覆盖时间轴、图节点、自动确认和静态资源托管；浏览器流程及视频采样属于独立验收。

## 3. Python 离线检查与结果阅读

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='tests'
python -m unittest test_unclear_intent test_context_system test_requirement_review test_report_routing test_context_state test_context_v5_regressions
python -m meeting_eval --help
python scripts/verify_release_evidence.py
```

核心套件使用仓库夹具。历史全库中另有依赖本地模型响应、SQLite 的归档测试及已记录旧失败，因此上述定向检查不等于全库全绿。公开证据检查验证两场新参会组的输入/参考/规则哈希，并从逐条判分复算任务与决定计数；它不重新判语义，也不重跑模型。

直接阅读 runs/2026-11-18-two-unseen-v19 下的 minutes.md、人工逐条复核.md 和 evaluation.json 即可了解保存结果。若使用完整本地运行库，可从 result.json 取真实 source_id，再查询：

```powershell
$run = 'runs/2026-11-18-two-unseen-v19/TS3003b'
$result = Get-Content "$run/result.json" -Raw -Encoding UTF8 | ConvertFrom-Json
python -m meeting_eval --db "$run/state.sqlite" minutes $result.source_id --viewer evaluator
python -m meeting_eval --db "$run/state.sqlite" requirements $result.source_id --viewer evaluator
```

这两条查询要求本地已有 state.sqlite；数据库不包含在 GitHub 文本证据中。原运行库用于留档，交互确认应在副本或新运行库中操作。

## 4. 当前模型配置与新推理

复制根目录 .env.example 为 .env，填写自己的 key；环境变量也可提供同名配置。

| 配置 | 用途 |
| --- | --- |
| OPENAI_API_KEY | 模型接口凭据 |
| MEETING_MODEL | 实测值 deepseek-flash |
| MEETING_API_BASE | API 基础地址，模板为 https://api.deepseek.com；客户端自动追加 /chat/completions |
| config/context-v5-v19.json | 当前三项显式推理参数；其他阶段采用提取器配置 |

| 阶段 | thinking / effort | max_tokens |
| --- | --- | ---: |
| track_context | enabled / high | 16384 |
| interpret_work | enabled / low | 32768 |
| check_work | enabled / high | 16384 |

`python -m meeting_eval ingest` 的默认策略仍为 split-v3，且没有 review-decisions 开关。要运行当前完整方案，使用新增便携入口，明确构造 context-v5 并开启决定核验：

```powershell
Copy-Item .env.example .env
# 编辑 .env 后，先检查输入和路径；此命令不请求模型、不创建输出目录。
python scripts/run_current.py --input examples/m1.json --out runs/my-meeting
# 新推理会调用模型，结果写入本地模拟器。
python scripts/run_current.py --input examples/m1.json --out runs/my-meeting --actor host --live
```

输入须满足现有会议 schema，包括稳定会议 ID、series、participants、segments 和需要时的 account_map。`--actor` 必须使用输入授权的主体；示例 m1 使用 host。导入时间默认取当前带时区时间，可通过 --at 显式指定；它是系统导入时间，不替代原语料录制日期。输出包括 input、inference、config、模型阶段、result、minutes、requirements 及 SQLite。

此入口默认只检查文件、段数与配置，首次推理要求全新输出目录。它复用现有 Service，不改变提取提示或恢复逻辑。收尾只验证预检及离线调用编排，没有新增真实模型推理。历史 experiments/full-meeting/run.py 等实验 runner 部分仍读取旧工作区相对凭据路径；新使用者优先用此入口及项目根 .env。

## 5. 可选实时 STT

在 demo 目录执行：

```powershell
python -m pip install -r scripts/requirements-stt.txt
python scripts/stt_server.py
```

服务监听 127.0.0.1:8766，接受本机 4173 / 4174 前端。首次运行下载 base.en。开发视图可切换实时 STT：前端约每 2.2 秒发送真实 PCM，服务识别最长 8 秒滚动窗口，响应可能修订先前文字。识别需要 1×；默认词轴回放无需启动这个服务。

说话人由 AMI 标注对齐，实时混音窗口使用主要发言人标签，不等于自动说话人分离。在线响应录制与离线词轴分别保存。重新生成默认字幕或素材需要 AMI 原件、FFmpeg 和相应 prepare/transcribe 脚本；正常播放使用已提供的派生媒体。

## 6. 可选视频重录

已验收主片无需重新制作。要录制新界面，在 demo 目录使用新名称，避免覆盖 final-20261122-v3：

```powershell
python -m pip install playwright numpy scipy
npm run dev -- --host 127.0.0.1 --port 4174 --strictPort
```

保持服务运行，在另一终端的 demo 目录执行。系统须安装 Microsoft Edge，FFmpeg 在 PATH 中：

```powershell
python scripts/video/record_continuous.py --dry --name rehearsal-new
python scripts/video/record_continuous.py --name recording-new
python scripts/video/compose.py recording-new
python scripts/video/verify.py recording-new
```

dry 只做定位彩排；正式录制连续播放 390 秒与 392 秒，不额外跳段或暂停。compose 根据 manifest 将源音频对齐录制时间，verify 检查声音定位、全片解码和时钟连续性。中间帧体积大，仅留在本地录制目录。

## 7. 复现范围与文件位置

| 内容 | GitHub | 原工作区 |
| --- | --- | --- |
| 当前核心和前端源码、配置、前端媒体 | 提供 | 提供 |
| 新参会组原文、参考、逐条判分和汇总 | 提供选定文本 | 提供完整运行 |
| 历史 115 场景逐处理单元索引 | 提供索引 | 提供原运行与评分依赖 |
| 历史模型请求、数据库、原始语料包 | 不随源码发布 | 保留 |
| 已验收主片与录制帧 | 不随 Git 提交 | 主片在交付/会议演示视频；帧在 demo/videos |

完整历史复算命令及依赖按[证据索引](EVALUATION.md)逐项列出。历史数据不齐时，只能复查公开判分和文档，不能宣称复现了当时的模型过程。

## 8. 文档阅读版生成

Markdown 为可编辑正文，三份 PDF 放在交付/项目文档。图源和截图保存在 docs/images。需要重新生成时安装文档工具，使用已安装的 Edge：

```powershell
python -m pip install markdown playwright
python scripts/render_reports.py
```

脚本由同一 Markdown 生成阅读版，并检查图片加载；输出后应重新检查分页、表格和中文渲染。临时 HTML 仅在 tmp/docs 中供排版验证。
