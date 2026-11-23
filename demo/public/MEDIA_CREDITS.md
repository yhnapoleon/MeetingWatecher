# 真人会议素材

当前完整助手视图（showcase=1）将下述音视频与 STT 词轴作为输入，纪要和任务由运行时模型生成。场景文件中保留的中文事件属于早期场景数据，不参与该视图的业务生成；本文其余内容用于说明素材与历史字段来源。

来源：AMI Meeting Corpus，会议 ES2002b，Edinburgh scenario meeting，2004-12-13。四位真人参与角色扮演式产品设计会议，存在自然停顿、重复、插话和背景声。

- 官方下载与授权说明：https://groups.inf.ed.ac.uk/ami/download/
- 许可：Creative Commons Attribution 4.0 International，https://creativecommons.org/licenses/by/4.0/ 。完整许可随附于 `AMI_LICENSE.txt`。
- 原始素材：`ES2002b.Mix-Headset.rm`、`ES2002b.Corner.rm`、AMI manual annotations v1.6.2。
- 本项目改动：连续截取原时间 1775–2165 秒（29:35–36:05）；转码为 MP3 / H.264 MP4；保持原声。原视频为 360×284 的低分辨率研究录像。
- 字幕：faster-whisper small.en 对该片段实际推理所得词级时间轴，保留自动识别错误；说话人通过 AMI 既有标注对齐，未声称完成自动说话人分离。
- 中文纪要与图节点：按原始逐词标注人工编排的演示事件；会前背景根据同系列 ES2002a 的摘要标注整理。
- 人名 David、Craig、Andrew 来自原会议发言；主持人使用角色名称，不推断其他身份。

实时 STT 使用本机 faster-whisper base.en，以较低延迟对滚动音频窗口重新识别。它与默认离线词轴的模型和输出不同。

## 双场连续会议派生素材

`ami-es2002-bc.mp3` / `ami-es2002-bc.mp4` 来源为同组 ES2002b、ES2002c。会议顺序由官方 a/b/c/d 编号及 `corpusResources/meetings.xml` 核验，四名参与者的全局 ID 相同。c 场新增使用 `ES2002c.Mix-Headset.rm` 与 `ES2002c.Corner.rm`，同属 AMI CC BY 4.0 许可。

双场总长 782 秒。b 场截取 1775–2165 秒；c 场依次截取 15–85、186–277、664–743、957–1032、1916–1993 秒。明确保留剪辑来源映射；前端显示原会议时间，未制作或替换原声。视频统一转为 360×284、25 fps，再按时间顺序连接。

双场字幕来自 small.en 实际推理，原输出保存在 `asr-cross-result.json`。字幕识别、人工原话标注、演示业务事件及独立后端实验结果分别保存。
