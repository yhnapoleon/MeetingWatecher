# MeetingWatcher 前端

React / TypeScript / Vite 应用包含项目工作台、会议现场、动态纪要、行动事项与跟进、文字助手和会议归档。完整交互见[技术设计](../docs/design.md)，前后端环境见[配置说明](../docs/CONFIG.md)。

## 启动

先在项目根目录配置模型并启动 `python -m meeting_copilot --env .env --data runs/my-copilot --port 8766`，再在本目录执行：

```powershell
npm ci
npm run dev -- --host 127.0.0.1 --port 4173 --strictPort
```

打开 http://127.0.0.1:4173/?showcase=1 。默认 API 代理到 8766，设置 COPILOT_API 可更换目标。完整助手视图需要服务端及模型配置；静态托管不包含 Python 服务。

## 交互与状态

1. 项目内进入第一场，音频开始后，字幕按实际 STT 词轴逐步出现。
2. LiveSummary 随新增稳定转写调用模型，同一议题原位补充；目录只显示已生成内容，可回看或跟随最新。
3. WorkBoard 自动加入分工候选，展示负责人、任务对象、内容、DDL、时间原话和依据；用户核对后确认保存。文字整理复用候选。
4. 项目助手支持文字问答、补课、比较表、验证清单、修改与下载，AG-UI 显示运行过程。
5. 会后归档，在项目中新建第二场并邀请成员；上场任务与本场更新并排显示，确认后更新原 GUID。
6. 回看首场按当时归档范围读取，保留原分工和后续确认历史。

当前议题是完整阅读区，目录和任务状态条独立布局；手动选择旧议题时保持选择。原话弹层不会暂停会议。浏览器 localStorage 保存项目状态，服务端保存账本与产物。

## 素材与检查

默认场景 scenario-cross.json 为 AMI ES2002b → ES2002c，两场共 782 秒。当前模型处理按游标释放的转写，不使用后续发言。音视频、字幕和原始时间映射见[MEDIA_CREDITS](public/MEDIA_CREDITS.md)。在线 ASR 与真实飞书写入尚需联调。

```powershell
npm test
npm run typecheck
npm run build
npm run test:sites
```

build 生成 dist/client、dist/server、dist/.openai/hosting.json。开发定位可用 `review=1`。当前完整演示 15:13，第二场 05:32 开始，详见[展示流程](../docs/AI参会助手_双场会议演示剧本.md)。
