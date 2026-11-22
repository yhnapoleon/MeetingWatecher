# 会议助手网页演示

从项目进入一场会议，在原声播放中查看逐词字幕、结论、决定和任务；会后归档，再在同一项目创建第二场，承接前场信息。当前为已验收的 AI 主视图与连续双场版本。

## 启动

需要 Node.js 22+。在本目录执行：

```powershell
npm ci
npm run dev -- --host 127.0.0.1 --port 4173 --strictPort
```

打开 http://127.0.0.1:4173 。默认播放使用已提供媒体，不需要模型密钥或实时 STT 服务。

## 正常使用流程

1. 进入项目，选择第一场，进入会议现场后自动开始。
2. AI 区约占七成，优先显示结论与决定，任务和讨论图随后展开；字幕随真实词轴出现。
3. 查看原话不会暂停；普通页面没有暂停键、进度条和倍速。
4. 第一场结束后归档，查看会议纪要和项目承接。
5. 在同一项目现场创建第二场，Alt+I 邀请原班成员；邀请接受在本地模拟。
6. 进入第二场，继承内容单独呈现，本场议题与图节点随讨论产生；结束后再次归档。

项目状态保存于浏览器 localStorage。需要从头演示时使用新的浏览器配置或清理该站点存储。

## 素材与业务事件

默认 scenario-cross.json 使用 AMI ES2002b → ES2002c，同一团队真人角色扮演设计会议。总素材 782 秒：第一场连续 390 秒，第二场五段顺序节选共 392 秒。主片包含项目和归档操作，总长 15:11。原始时间及剪辑位置见 [MEDIA_CREDITS.md](public/MEDIA_CREDITS.md)。

字幕来自 faster-whisper small.en 对实际音频识别的 2,152 词，输出保存在 asr-cross-result.json；说话人按 AMI 标注对齐。中文纪要、任务、图节点、供电修订和自动确认是预设事件。后端另用完整逐字稿实测，结果见[跨会报告](../docs/跨会议真人演示与实测.md)。

音频是唯一业务时钟，同一 task.id 或 decision.id 表示同一对象的变化，minuteEvents 使用稳定节点 ID 更新图。事件只能引用当时已经发生的原话，第二场未开始时不展示其全场目录。

## 场景文件

| 字段 | 含义 |
| --- | --- |
| duration、people、tracks | 总时长、稳定人物与音轨；混音使用 audioMode=mixed |
| segments、captionWords | 原话及毫秒时间；词轴含 start/end/text/speaker |
| meetings、clips | 双场边界与原始媒体时间映射 |
| events、interactions | 任务/决定变化、确认出现与完成时间 |
| context、chapters | 会前承接及随讨论开放的议题 |
| minuteEvents | 带 at 和 node 的稳定 ID 图节点更新 |
| provenance | 素材、字幕与事件来源 |

备用 scenario-real.json 为单场真人片段；scenario.json 为中文合成语音场景。素材生成脚本保留在 scripts，正常播放无需重建。

## 开发模式与 STT

`?review=1` 用于时间轴定位、播放控件和模式调试。旧文档中的暂停、拖动、倍速描述仅适用于开发视图，不属于当前普通界面。

默认 STT 词轴回放无需服务；实时 STT 模式向本机服务发送 PCM，识别会修订文字；识别响应可以录制并按到达时间重放。服务与模型安装、端口和来源边界见[统一配置说明](../docs/CONFIG.md)。当前未将在线识别接入后端提取链路。

## 验证与视频

```powershell
npm test
npm run typecheck
npm run build
npm run test:sites
```

build 生成 dist/client、dist/server 与 dist/.openai/hosting.json。连续录制入口为 scripts/video/record_continuous.py；旧 record.py 为分段脚本。重录命令见配置说明，必须用新录制名称。当前主片与原录制文件留在本地，验收见[视频验收](../docs/项目会议视频验收.md)。
