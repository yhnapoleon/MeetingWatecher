import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwise,
  ArrowLeft,
  ArrowRight,
  ArrowsOutSimple,
  CaretDown,
  Check,
  CheckCircle,
  Clock,
  ClosedCaptioning,
  DotsThree,
  FileText,
  Flag,
  Headphones,
  ListChecks,
  Microphone,
  MicrophoneSlash,
  Monitor,
  Pause,
  Play,
  Plus,
  ShieldCheck,
  SidebarSimple,
  Sparkle,
  SpeakerHigh,
  SpeakerSlash,
  SquaresFour,
  UploadSimple,
  Users,
  VideoCamera,
  X,
} from "@phosphor-icons/react";
import {
  formatTime,
  projectAt,
  sourcePosition,
  validateScenario,
  type Person,
  type Scenario,
  type Task,
} from "./scenario";
import { useMeetingAudio } from "./useMeetingAudio";
import { MinutesPanel } from "./MinutesPanel";
import { captionAt, visibleCaption } from "./minutes";
import { useLiveStt } from "./useLiveStt";
import { CrossMeetingPanel } from "./CrossMeetingPanel";
import { LiveWorkspace } from './LiveWorkspace';

function Avatar({
  person,
  size = "normal",
}: {
  person: Person;
  size?: string;
}) {
  return (
    <span className={`avatar ${size}`} style={{ background: person.color }}>
      {person.initial}
    </span>
  );
}

export function App({ supplied, startAt=0, endAt, onArchive, onBack }: { supplied?:Scenario; startAt?:number; endAt?:number; onArchive?:(time:number)=>void; onBack?:()=>void } = {}) {
  const presentation = !!supplied;
  const review = new URLSearchParams(location.search).has('review');
  const [scenario, setScenario] = useState<Scenario | null>(supplied ?? null);
  const [files, setFiles] = useState<Map<string, File> | null>(null);
  const [loadError, setLoadError] = useState("");
  const [tab, setTab] = useState("overview");
  const [setup, setSetup] = useState(!supplied);
  const [caption, setCaption] = useState(true);
  const [layout, setLayout] = useState<"equal" | "ai">(presentation ? 'ai' : 'equal');
  const [menu, setMenu] = useState(false);
  const [members, setMembers] = useState(false);
  const [evidence, setEvidence] = useState<string[] | null>(null);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [pinned, setPinned] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const transcript = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const recordingInput = useRef<HTMLInputElement>(null);
  const previousMeeting = useRef<string | undefined>(undefined);
  const [captionMode, setCaptionMode] = useState<
    "aligned" | "live" | "recorded"
  >("aligned");
  const audio = useMeetingAudio(scenario, files);
  const initialized = useRef(false);
  useEffect(()=>{if(supplied && audio.ready && !initialized.current){initialized.current=true;audio.seek(startAt);if(presentation && !review)void audio.play();}},[audio.ready]);
  useEffect(()=>{if(endAt && audio.playing && audio.time>=endAt-100){audio.pause();audio.seek(endAt);}},[audio.time,audio.playing]);
  const stt = useLiveStt(scenario, audio, captionMode === "live");
  const alignedCaption = scenario ? captionAt(scenario, audio.time) : null;
  const shownCaption = visibleCaption(
    scenario,
    captionMode === "live"
      ? stt.caption
      : captionMode === "recorded"
        ? stt.recordedAt(audio.time)
        : alignedCaption,
    audio.time,
  );
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    v.playbackRate = audio.rate;
    if (Math.abs(v.currentTime - audio.time / 1000) > 0.45)
      v.currentTime = audio.time / 1000;
    if (audio.playing) void v.play().catch(() => {});
    else v.pause();
  }, [audio.time, audio.playing, audio.rate]);
  const state = useMemo(
    () => (scenario ? projectAt(scenario, audio.time) : null),
    [scenario, audio.time],
  );
  useEffect(() => {
    if(supplied) return;
    fetch("/scenario-cross.json")
      .then((r) => {
        if (!r.ok) throw new Error("无法读取演示场景");
        return r.json();
      })
      .then((raw) => setScenario(validateScenario(raw)))
      .catch((error) => setLoadError(error.message));
  }, []);
  const source = scenario ? sourcePosition(scenario,audio.time) : null;
  useEffect(() => {
    if (!supplied && previousMeeting.current && previousMeeting.current!==source?.meeting.id && source && source.meeting.at>0)
      setTab('cross');
    previousMeeting.current=source?.meeting.id;
  }, [source?.meeting.id]);
  const active =
    scenario?.segments.filter(
      (s) => s.start <= audio.time && s.end > audio.time,
    ) ?? [];
  const current =
    active[0] ?? scenario?.segments.filter((s) => s.end <= audio.time && s.start >= (source?.clip.at ?? 0)).at(-1);
  const speaker =
    scenario?.people.find((p) => p.id === (pinned ?? current?.speaker)) ??
    scenario?.people[0];
  const chapter = scenario?.chapters.filter((c) => c.at <= audio.time).at(-1);
  const finished = !!scenario && audio.time >= (endAt ?? scenario.duration);
  const latest = state?.changes.filter(c => c.at >= startAt).at(-1);
  const currentSegment = current?.id;
  useEffect(() => {
    if (tab !== "overview" || scenario?.minuteEvents.length) return;
    const target = finished ? ".meeting-complete" : ".latest-change";
    transcript.current
      ?.querySelector(target)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [latest?.at, finished, tab]);
  useEffect(() => {
    if (tab === "transcript" && !search && filter === "all")
      transcript.current
        ?.querySelector('[data-current="true"]')
        ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [currentSegment, tab, filter, search]);
  const showEvidence = (ids: string[]) => {
    if (!presentation) audio.pause();
    setEvidence(ids);
  };
  const importFiles = async (selected: FileList | null) => {
    if (!selected?.length) return;
    audio.pause();
    setLoadError("");
    try {
      const list = [...selected];
      const json = list.filter((f) => f.name.endsWith(".json"));
      if (json.length !== 1)
        throw new Error("请同时选择一份场景 JSON 和它的全部音频文件");
      const data = validateScenario(JSON.parse(await json[0].text()));
      const media = new Map(
        list.filter((f) => !f.name.endsWith(".json")).map((f) => [f.name, f]),
      );
      for (const track of data.tracks)
        if (!media.has(track.src.split("/").pop()!))
          throw new Error(`缺少 ${track.src}`);
      if (media.size !== list.length - 1) throw new Error("音频文件名重复");
      setFiles(media);
      setCaptionMode("aligned");
      setScenario(data);
      setTab("overview");
      setPinned(null);
      setFilter("all");
      setSearch("");
      setEvidence(null);
    } catch (error) {
      setLoadError((error as Error).message);
    }
  };
  const person = (id: string) => scenario!.people.find((p) => p.id === id)!;
  const chooseScenario = async (path:string) => {
    audio.pause();
    try {
      const response=await fetch(path);
      if(!response.ok) throw new Error('无法读取演示场景');
      const next=validateScenario(await response.json());
      setFiles(null); setCaptionMode('aligned'); setTab('overview');
      setFilter('all'); setSearch(''); setPinned(null); setEvidence(null);
      setLoadError(''); setScenario(next);
    } catch(error) { setLoadError((error as Error).message); }
  };
  const taskCard = (task: Task) => (
    <div className="task-row" key={task.id}>
      <span className={`task-status ${task.status === "已完成" ? "done" : ""}`}>
        {task.status === "已完成" ? <Check size={14} /> : <span />}
      </span>
      <div className="task-body">
        <strong>{task.title}</strong>
        <p>{task.detail}</p>
        <div className="task-meta">
          <span>
            <Avatar person={person(task.owner)} size="tiny" />
            {person(task.owner).name}
          </span>
          <span>
            <Clock size={13} />
            {task.due}
          </span>
          <span className="status-label">{task.status}</span>
        </div>
      </div>
      <button
        className="evidence-button"
        title="查看原文证据"
        onClick={() => showEvidence(task.evidence)}
      >
        <FileText size={17} />
      </button>
    </div>
  );

  if (!scenario || !state || !speaker)
    return (
      <main className="loading-screen">
        <Sparkle size={32} />
        <p>{loadError || "正在准备会议演示…"}</p>
      </main>
    );
  return (
    <main className={`meeting-app ${presentation ? 'immersive' : ''}`} data-ready={audio.ready} data-media-time={audio.time} data-playing={audio.playing} data-rate={audio.rate}>
      {supplied && <div className="project-breadcrumb"><button onClick={()=>{audio.pause();onBack?.();}}>← 返回项目</button><span>遥控器产品设计 / {startAt ? "02 方案汇报与迭代" : "01 功能方案与分工"}</span><small>真人会议节选 · 预设事件演示</small></div>}
      <header className="window-bar">
        <div className="meeting-title">
          <VideoCamera weight="fill" size={21} />
          <strong>{scenario.title}</strong>
          <span className="demo-label">{presentation ? finished ? '会议已结束' : '会议中' : '演示回放'}</span>
        </div>
        <div className="window-meta">
          <ShieldCheck size={15} />
          <span>{formatTime(Math.max(0,audio.time-startAt))}</span>
          <button onClick={() => setMenu(!menu)}>
            <SquaresFour size={16} />
            布局
            <CaretDown size={12} />
          </button>
        </div>
        {menu && (
          <div className="layout-menu">
            <button
              onClick={() => {
                setLayout("equal");
                setMenu(false);
              }}
            >
              <SidebarSimple size={18} />
              会议与 AI 等宽{layout === "equal" && <Check size={16} />}
            </button>
            <button
              onClick={() => {
                setLayout("ai");
                setMenu(false);
              }}
            >
              <Sparkle size={18} />
              聚焦 AI 视图{layout === "ai" && <Check size={16} />}
            </button>
          </div>
        )}
      </header>
      <section className="participant-strip">
        {scenario.people.map((p) => (
          <button
            key={p.id}
            className={`participant ${active.some((s) => s.speaker === p.id) ? "speaking" : ""} ${pinned === p.id ? "pinned" : ""}`}
            onClick={() => setPinned(pinned === p.id ? null : p.id)}
            title={pinned === p.id ? "取消固定画面" : "固定参会人画面"}
          >
            <Avatar person={p} size="small" />
            <div>
              <strong>
                {p.name}
                {(p.id === "chen" || p.role.includes("主持人")) && (
                  <span>（主持人）</span>
                )}
              </strong>
              <span>
                {active.some((s) => s.speaker === p.id)
                  ? "正在发言"
                  : p.role.split(" · ")[0]}
              </span>
            </div>
            <span className="mic-state">
              <Microphone
                size={15}
                weight={
                  active.some((s) => s.speaker === p.id) ? "fill" : "regular"
                }
              />
            </span>
          </button>
        ))}
        <button
          className="participant-add"
          title="查看参会人"
          onClick={() => setMembers(!members)}
        >
          <Users size={21} />
          <span>{scenario.people.length} 人参会</span>
        </button>
      </section>
      <section className={`workspace ${layout === "ai" ? "ai-focused" : ""}`}>
        <div
          className={`meeting-stage ${scenario.video && !files ? "real-stage" : ""}`}
        >
          <div className="stage-top">
            <span>
              <Headphones size={16} />
              {finished ? "会议已结束" : "语音会议"}
            </span>
            <button
              className="stage-layout"
              title="切换主画面大小"
              onClick={() => setLayout(layout === "equal" ? "ai" : "equal")}
            >
              <ArrowsOutSimple size={17} />
            </button>
          </div>
          {scenario.video && !files && (
            <div className="real-video-wrap">
              <video
                ref={video}
                src={`/${scenario.video}`}
                muted
                playsInline
                preload="auto"
              />
              <span className="recording-credit">{source?`${source.meeting.id} · 原片 ${formatTime(source.sourceTime)} · 节选`:'AMI · 真人会议片段'}</span>
            </div>
          )}
          <div className="speaker-focus">
            <div
              className={`speaker-ring ${active.some((s) => s.speaker === speaker.id) && audio.playing ? "active" : ""}`}
            >
              <Avatar person={speaker} size="hero" />
            </div>
            <h1>{speaker.name}</h1>
            <p>{speaker.role}</p>
            <div
              className={`speaking-indicator ${audio.playing && active.length ? "live" : ""}`}
            >
              <Microphone size={16} />
              <span>
                {pinned
                  ? "已固定此画面"
                  : audio.playing && active.length
                    ? "正在发言"
                    : finished
                      ? "感谢参与"
                      : audio.playing
                        ? "聆听中"
                        : presentation ? "正在连接" : "播放已暂停"}
              </span>
            </div>
          </div>
          <div className="stage-bottom">
            <div className="topic-label">
              <span>当前议题</span>
              <strong>{chapter?.title}</strong>
            </div>
            {caption && (
              <div className="live-caption">
                <span>
                  {shownCaption?.speaker
                    ? person(shownCaption.speaker).name
                    : "会议字幕"}
                </span>
                <p>
                  {shownCaption?.text ||
                    (captionMode === "live"
                      ? stt.status
                      : captionMode === "recorded"
                        ? "当前时段没有录制的识别输出"
                        : "字幕将跟随语音逐词出现。")}
                  {audio.playing && <i className="caption-caret" />}
                </p>
                <div className="caption-tools">
                  <select
                    aria-label="字幕模式"
                    value={captionMode}
                    onChange={(e) => {
                      audio.pause();
                      setCaptionMode(e.target.value as typeof captionMode);
                    }}
                  >
                    <option value="aligned">
                      {scenario.captionWords ? "STT 逐词回放" : "标注字幕回放"}
                    </option>
                    <option
                      value="live"
                      disabled={!!files || scenario.audioMode !== "mixed"}
                    >
                      实时 STT
                    </option>
                    <option value="recorded" disabled={!stt.count}>
                      本次识别重放
                    </option>
                  </select>
                  {captionMode === "live" && <small>{stt.status}</small>}
                  {stt.count > 0 && (
                    <button onClick={stt.download}>导出出字轴</button>
                  )}
                  <button onClick={() => recordingInput.current?.click()}>
                    载入出字轴
                  </button>
                  <input
                    ref={recordingInput}
                    hidden
                    type="file"
                    accept=".json"
                    onChange={async (e) => {
                      const f = e.target.files?.[0];
                      if (f) {
                        audio.pause();
                        if (await stt.loadRecording(f))
                          setCaptionMode("recorded");
                      }
                      e.target.value = "";
                    }}
                  />
                </div>
              </div>
            )}
          </div>
          {members && (
            <aside className="members-panel">
              <div>
                <strong>参会人 · {scenario.people.length}</strong>
                <button
                  onClick={() => setMembers(false)}
                  aria-label="关闭参会人"
                >
                  <X size={18} />
                </button>
              </div>
              {scenario.people.map((p) => (
                <div key={p.id}>
                  <Avatar person={p} size="small" />
                  <span>
                    {p.name}
                    <small>{p.role}</small>
                  </span>
                  <Microphone size={16} />
                </div>
              ))}
            </aside>
          )}
        </div>
        <section className="ai-panel">
          <header className="ai-header">
            <div>
              <span className="ai-icon">
                <Sparkle size={19} weight="fill" />
              </span>
              <strong>AI 会议助手</strong>
              <span className={`live-status ${audio.playing ? "running" : ""}`}>
                <i />
                {finished
                  ? "总结已完成"
                  : audio.playing
                    ? "跟随会议"
                    : "已就绪"}
              </span>
            </div>
            <button
              title="聚焦 AI 视图"
              onClick={() => setLayout(layout === "ai" ? "equal" : "ai")}
            >
              <ArrowsOutSimple size={17} />
            </button>
          </header>
          {!supplied && source && scenario.meetings.length===2 && <div className="series-navigation" aria-label="跨会议导航">
            {scenario.meetings.map(m=><button key={m.id} className={m.id===source.meeting.id?'current':''}
              onClick={()=>{audio.seek(m.at);setTab('cross');}}><small>{m.id}</small><strong>{m.title}</strong></button>)}
          </div>}
          <nav className="ai-tabs">
            {[
              ["overview", "实时纪要"],
              ...(scenario.meetings.length===2 ? [["cross","跨会追踪"]] : []),
              ...(scenario.minuteEvents.length ? [["graph", "讨论全览"]] : []),
              ["transcript", "文字记录"],
              ["history", "变更记录"],
            ].map(([id, label]) => (
              <button
                key={id}
                className={tab === id ? "selected" : ""}
                onClick={() => setTab(id)}
              >
                {label}
                {id === "history" && state.changes.length > 0 && (
                  <span>{state.changes.length}</span>
                )}
              </button>
            ))}
          </nav>
          {!!scenario.minuteEvents.length && latest && (
            <button
              className="ai-latest-update"
              key={latest.at}
              onClick={() => showEvidence(latest.evidence)}
            >
              <Sparkle size={13} />
              <span>{latest.label}</span>
              <time>{formatTime(Math.max(0,latest.at-startAt))}</time>
              <ArrowRight size={12} />
            </button>
          )}
          <div className="ai-scroll" ref={transcript}>
            {presentation && tab === 'overview' && <LiveWorkspace scenario={scenario} time={audio.time} onEvidence={showEvidence} />}
            {tab==='cross' && scenario.meetings.length===2 && <CrossMeetingPanel scenario={scenario} time={audio.time} onEvidence={showEvidence} onSeek={audio.seek}/>}
            {((tab === "overview" && !presentation) || tab === "graph") &&
              !!scenario.minuteEvents.length && (
                <MinutesPanel
                  scenario={scenario}
                  time={audio.time}
                  onEvidence={showEvidence}
                  onSeek={presentation ? (at) => showEvidence(scenario.segments.filter(s => s.start <= at && s.end >= at).map(s => s.id)) : audio.seek}
                  graphOnly={tab === "graph"}
                  caption={shownCaption}
                  captionLabel={captionMode === 'live' ? '实时识别' : captionMode === 'recorded' ? '识别响应回放' : 'STT 词轴回放'}
                />
              )}
            {tab === "overview" && !scenario.minuteEvents.length && (
              <>
                <div className="meeting-progress">
                  <div>
                    <span className="eyebrow">
                      {finished ? "会议回顾" : "正在讨论"}
                    </span>
                    <h2>
                      {finished ? "分工已明确，准备推进" : chapter?.title}
                    </h2>
                  </div>
                  <span className="chapter-count">
                    {scenario.chapters.findIndex((c) => c === chapter) + 1}
                    <small> / {scenario.chapters.length}</small>
                  </span>
                </div>
                <div className="chapter-progress">
                  {scenario.chapters.map((c) => (
                    <button
                      key={c.at}
                      title={`跳转至 ${c.title}`}
                      onClick={() => audio.seek(c.at)}
                      className={c.at <= audio.time ? "complete" : ""}
                    />
                  ))}
                </div>
                <section className="structured-section">
                  <div className="section-heading">
                    <span>
                      <Flag size={18} />
                      关键决定
                    </span>
                    <span>
                      {state.decisions.length ? "当前有效" : "持续整理中"}
                    </span>
                  </div>
                  {state.decisions.length === 0 ? (
                    <div className="empty-card">
                      <Flag size={22} />
                      <div>
                        <strong>等待形成明确决定</strong>
                        <p>讨论达成共识后，决定会显示在这里</p>
                      </div>
                    </div>
                  ) : (
                    state.decisions.map((d) => (
                      <article key={d.id} className="decision-card">
                        <div className="decision-top">
                          <strong>{d.title}</strong>
                          <span>
                            <CheckCircle size={14} weight="fill" />
                            已确定
                          </span>
                        </div>
                        <div className="price-comparison">
                          {d.versions.some((v) => v.value !== d.value) && (
                            <>
                              <div className="old-price">
                                <span>原方案</span>
                                <strong>
                                  {d.versions[0].value}
                                  <small>元</small>
                                </strong>
                              </div>
                              <ArrowRight size={24} className="price-arrow" />
                            </>
                          )}
                          <div className="current-price">
                            <span>
                              {d.versions.length > 1
                                ? "当前方案"
                                : "已采纳方案"}
                            </span>
                            <strong key={d.value}>
                              {d.value}
                              <small>{d.unit}</small>
                            </strong>
                          </div>
                        </div>
                        <p>{d.detail}</p>
                        <footer>
                          <span>
                            {d.versions.length > 1
                              ? `${d.versions.length} 条决定记录`
                              : "有原文证据支持"}
                          </span>
                          <button onClick={() => showEvidence(d.evidence)}>
                            查看依据
                            <ArrowRight size={14} />
                          </button>
                        </footer>
                      </article>
                    ))
                  )}
                </section>
                <section className="structured-section">
                  <div className="section-heading">
                    <span>
                      <ListChecks size={19} />
                      行动任务
                      <span className="count">{state.tasks.length}</span>
                    </span>
                    <span>按负责人落实</span>
                  </div>
                  <div className="task-list">
                    {state.tasks.length ? (
                      state.tasks.map(taskCard)
                    ) : (
                      <div className="empty-card">
                        <ListChecks size={24} />
                        <div>
                          <strong>正在聆听任务分工</strong>
                          <p>任务会保留负责人、交付时间和相关原话</p>
                        </div>
                      </div>
                    )}
                  </div>
                </section>
                {latest && (
                  <div className="latest-change" key={`${latest.at}`}>
                    <span className="change-icon">
                      <ArrowClockwise size={16} />
                    </span>
                    <div>
                      <strong>{latest.label}</strong>
                      <p>{latest.detail}</p>
                    </div>
                    <time>{formatTime(Math.max(0,latest.at-startAt))}</time>
                  </div>
                )}
                {finished && (
                  <div className="meeting-complete">
                    <CheckCircle size={21} weight="fill" />
                    <div>
                      <strong>会议事项已整理</strong>
                      <p>
                        {state.tasks.length} 项任务 · {state.decisions.length}{" "}
                        项有效决定 · {state.changes.length} 条变更记录
                      </p>
                    </div>
                  </div>
                )}
              </>
            )}
            {tab === "transcript" && (
              <>
                <div className="transcript-filters">
                  <input
                    aria-label="搜索已播放字幕"
                    placeholder="搜索已播放的内容"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  <select
                    aria-label="筛选发言人"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  >
                    <option value="all">全部发言人</option>
                    {scenario.people.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
                {scenario.segments
                  .filter(
                    (s) =>
                      s.start <= audio.time &&
                      s.start >= startAt &&
                      (filter === "all" || s.speaker === filter) &&
                      s.text.includes(search),
                  )
                  .map((s) => (
                    <article
                      className={`transcript-line ${s.id === current?.id ? "current" : ""}`}
                      data-current={s.id === current?.id}
                      key={s.id}
                    >
                      <Avatar person={person(s.speaker)} size="small" />
                      <div>
                        <header>
                          <strong>{person(s.speaker).name}</strong>
                          <button
                            onClick={() => {
                              if (presentation) showEvidence([s.id]);
                              else { audio.pause(); audio.seek(Math.max(startAt,s.start)); }
                            }}
                          >
                            {formatTime(s.start - startAt)}
                          </button>
                        </header>
                        <p>
                          {s.end <= audio.time
                            ? s.text
                            : captionAt(
                                {
                                  ...scenario,
                                  captionWords: undefined,
                                  segments: [s],
                                },
                                audio.time,
                              ).text}
                        </p>
                      </div>
                    </article>
                  ))}
                {audio.time === 0 && (
                  <p className="empty-note">
                    开始播放后，文字记录将跟随会议出现。
                  </p>
                )}
              </>
            )}
            {tab === "history" && (
              <>
                <div className="history-intro">
                  <h2>每一次变化，都有迹可循</h2>
                  <p>按会议时间保留分工、确认和决定的演变</p>
                </div>
                <div className="history-list">
                  {state.changes.map((c, index) => (
                    <article key={`${c.at}-${index}`}>
                      <span className={`history-dot ${c.kind}`}>
                        {c.kind === "decision" ? (
                          <Flag size={15} />
                        ) : (
                          <Check size={15} />
                        )}
                      </span>
                      <div>
                        <header>
                          <strong>{c.label}</strong>
                          <time>{formatTime(c.at)}</time>
                        </header>
                        <p>{c.detail}</p>
                        <button onClick={() => showEvidence(c.evidence)}>
                          查看相关发言
                          <ArrowRight size={13} />
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
                {!state.changes.length && (
                  <p className="empty-note">
                    任务和决定出现后，变化将记录在这里。
                  </p>
                )}
              </>
            )}
          </div>
          {presentation && caption && <section className="focused-transcription"><header><span className="listening-dot" /><strong>实时转写</strong><span>{shownCaption?.speaker ? person(shownCaption.speaker).name : '等待发言'}</span><small>{captionMode === 'live' ? '实时识别' : 'STT 词轴回放'}</small></header><p>{shownCaption?.text || '正在聆听，文字随发言逐词出现…'}</p></section>}
          <footer className="ai-footer">
            <ShieldCheck size={14} />
            <span>基于会议发言整理</span>
            <span>预设事件演示</span>
          </footer>
          {state.interaction && (
            <div className="confirmation-layer">
              <article
                className={`confirmation-card ${state.interaction.phase}`}
              >
                <header>
                  <span className="ai-icon">
                    <Sparkle size={20} weight="fill" />
                  </span>
                  <div>
                    <strong>
                      {state.interaction.phase === "complete"
                        ? "任务已确认"
                        : state.interaction.title}
                    </strong>
                    <p>
                      {state.interaction.phase === "complete"
                        ? "已加入行动任务"
                        : `${state.interaction.remaining} 秒后自动确认演示选项`}
                    </p>
                  </div>
                  {state.interaction.phase === "complete" && (
                    <CheckCircle weight="fill" size={28} />
                  )}
                </header>
                <blockquote>“{state.interaction.quote}”</blockquote>
                <div className="confirmation-fields">
                  <label>
                    具体工作<div>{state.interaction.task.title}</div>
                  </label>
                  <div className="field-pair">
                    <label>
                      负责人
                      <div>
                        <Avatar
                          person={person(state.interaction.task.owner)}
                          size="tiny"
                        />
                        {person(state.interaction.task.owner).name}
                      </div>
                    </label>
                    <label>
                      交付时间
                      <div>
                        <Clock size={15} />
                        {state.interaction.task.due}
                      </div>
                    </label>
                  </div>
                  <p>{state.interaction.task.detail}</p>
                </div>
                <footer>
                  <span>
                    {scenario.video ? "根据会议原话整理" : "已根据后续发言补全"}
                  </span>
                  <button
                    className={`primary ${state.interaction.phase !== "waiting" ? "auto-selected" : ""}`}
                    aria-disabled="true"
                  >
                    <Check size={16} />
                    {state.interaction.phase === "complete"
                      ? "已创建任务"
                      : state.interaction.phase === "selected"
                        ? "正在确认…"
                        : "确认并创建任务"}
                  </button>
                </footer>
                <div className="countdown-track">
                  <span
                    style={{
                      width: `${Math.min(100, ((audio.time - state.interaction.showAt) / (state.interaction.selectAt - state.interaction.showAt)) * 100)}%`,
                    }}
                  />
                </div>
              </article>
            </div>
          )}
        </section>
      </section>
      <section className="meeting-toolbar">
        <div className="toolbar-left">
          <button title="音频输出" onClick={() => audio.setMuted(!audio.muted)}>
            {audio.muted ? (
              <SpeakerSlash size={21} />
            ) : (
              <SpeakerHigh size={21} />
            )}
            <span>{audio.muted ? "取消静音" : "扬声器"}</span>
          </button>
          <button title="参会人" onClick={() => setMembers(!members)}>
            <Users size={21} />
            <span>参会人</span>
          </button>
        </div>
        <div className="toolbar-center">
          <button className="visual-control" disabled title="演示使用预录声轨">
            <MicrophoneSlash size={23} />
            <span>麦克风</span>
          </button>
          <button disabled className="visual-control" title="语音会议">
            <VideoCamera size={23} />
            <span>摄像头</span>
          </button>
          <button
            onClick={() => {
              audio.pause();
              setSetup(true);
            }}
          >
            <UploadSimple size={22} />
            <span>演示素材</span>
          </button>
          <button
            className="ai-toolbar active"
            onClick={() => {
              setLayout(layout === "ai" ? "equal" : "ai");
            }}
          >
            <Sparkle size={22} weight="fill" />
            <span>AI 视图</span>
          </button>
          <button
            className={caption ? "active" : ""}
            onClick={() => setCaption(!caption)}
          >
            <ClosedCaptioning size={22} />
            <span>字幕</span>
          </button>
        </div>
        <div className="toolbar-right">
          <button
            className="end-button"
            onClick={() => {
              audio.pause();
              if(onArchive) onArchive(audio.time); else audio.seek(scenario.duration);
              setTab("overview");
            }}
          >
            {onArchive ? "结束并归档本场" : "结束演示"}
          </button>
        </div>
      </section>
      {(!presentation || review) && <footer className="playback-bar">
        <button
          className="play-button"
          aria-label={audio.playing ? "暂停播放" : "开始播放"}
          disabled={!audio.ready}
          onClick={() => (audio.playing ? audio.pause() : void audio.play())}
        >
          {audio.playing ? (
            <Pause size={19} weight="fill" />
          ) : (
            <Play size={19} weight="fill" />
          )}
        </button>
        <button
          className="restart"
          aria-label="重新开始"
          onClick={() => {
            audio.pause();
            audio.seek(startAt);
            setTab("overview");
          }}
        >
          <ArrowClockwise size={18} />
        </button>
        <time>
          {formatTime(Math.max(0,audio.time-startAt))}
          <span> / {formatTime((endAt ?? scenario.duration)-startAt)}</span>
        </time>
        <div className="scrubber">
          <input
            type="range"
            min={startAt}
            max={endAt ?? scenario.duration}
            step="100"
            value={audio.time}
            onChange={(e) => audio.seek(Number(e.target.value))}
            aria-label="会议播放进度"
            style={
              {
                "--progress": `${((audio.time-startAt) / ((endAt ?? scenario.duration)-startAt)) * 100}%`,
              } as React.CSSProperties
            }
          />
          <div className="timeline-marks">
            {scenario.chapters.filter(c=>c.at>startAt && c.at<=audio.time && c.at<(endAt ?? scenario.duration)).map((c) => (
              <button
                key={c.at}
                title={c.title}
                onClick={() => audio.seek(c.at)}
                style={{ left: `${((c.at-startAt) / ((endAt ?? scenario.duration)-startAt)) * 100}%` }}
              />
            ))}
          </div>
        </div>
        <select
          aria-label="播放速度"
          value={audio.rate}
          onChange={(e) => audio.setRate(Number(e.target.value))}
        >
          <option value="1">1×</option>
          <option value="1.5">1.5×</option>
          <option value="2">2×</option>
        </select>
        <span className="autoplay-label">
          <Sparkle size={13} />
          自动演示
        </span>
      </footer>}
      {audio.error && !setup && (
        <div className="error-banner" role="alert">
          {audio.error}
          <button onClick={() => setSetup(true)}>检查素材</button>
        </div>
      )}
      {setup && (
        <div className="modal-backdrop">
          <section className="setup-dialog">
            <div className="setup-heading">
              <span className="setup-icon">
                <VideoCamera weight="fill" size={28} />
              </span>
              <span className="demo-label">演示回放</span>
              {audio.time > 0 && (
                <button
                  aria-label="关闭素材窗口"
                  onClick={() => setSetup(false)}
                >
                  <X size={20} />
                </button>
              )}
            </div>
            <h1>{scenario.title}</h1>
            <p className="setup-subtitle">
              {scenario.meetings.length
                ? '同一团队的两场会议：先形成分工，再追踪重申、汇报与方案修订。'
                : scenario.video
                ? "真实的停顿、插话与讨论。看一项提议如何成为团队共识。"
                : "跟随一场会议，看讨论如何成为明确的行动。"}
            </p>
            <div className="setup-people">
              {scenario.people.map((p) => (
                <div key={p.id}>
                  <Avatar person={p} size="medium" />
                  <strong>{p.name}</strong>
                  <span>{p.role.split(" · ")[0]}</span>
                </div>
              ))}
            </div>
            <div className="setup-summary">
              <span>
                <Clock size={17} />
                {formatTime(scenario.duration)}
              </span>
              <span>
                <Headphones size={17} />
                {scenario.audioMode === "mixed"
                  ? `混音 · ${scenario.people.length} 个逻辑通道`
                  : `${scenario.tracks.length} 条说话人声轨`}
              </span>
              <span>
                <Sparkle size={17} />
                交互自动完成
              </span>
            </div>
            <div className="setup-agenda">
              {scenario.chapters.map((c) => (
                <span key={c.at}>{c.title}</span>
              ))}
            </div>
            <p className="source-note">{scenario.provenance}</p>
            <div className="scenario-choice">
              <button onClick={()=>void chooseScenario('/scenario-cross.json')}>双场真人会议</button>
              <button onClick={()=>void chooseScenario('/scenario-real.json')}>单场真人会议</button>
              <button onClick={()=>void chooseScenario('/scenario.json')}>中文合成示例</button>
              <span>{scenario.captionSource ?? "句级标注 · 渐进字幕"}</span>
            </div>
            {(loadError || audio.error) && (
              <div role="alert" className="import-error">
                {loadError || audio.error}
              </div>
            )}
            <div className="setup-actions">
              <button
                className="secondary"
                onClick={() => input.current?.click()}
              >
                <UploadSimple size={17} />
                导入标注音频
              </button>
              <button
                className="primary"
                disabled={!audio.ready}
                onClick={() => {
                  setSetup(false);
                  void audio.play();
                }}
              >
                <Play weight="fill" size={16} />
                {audio.loading
                  ? "正在加载声轨…"
                  : audio.time > 0 && !finished
                    ? "继续演示"
                    : "开始演示"}
              </button>
            </div>
            <p className="import-hint">
              导入时同时选择场景 JSON 与全部音频文件
            </p>
            <input
              ref={input}
              hidden
              type="file"
              multiple
              accept=".json,.mp3,.wav,.m4a,.ogg"
              onChange={(e) => {
                void importFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </section>
        </div>
      )}
      {evidence && (
        <div className="modal-backdrop evidence-backdrop">
          <section className="evidence-dialog">
            <header>
              <div>
                <span className="eyebrow">原文证据</span>
                <h2>回到这段讨论</h2>
              </div>
              <button aria-label="关闭证据" onClick={() => setEvidence(null)}>
                <X size={22} />
              </button>
            </header>
            {evidence.map((id) => {
              const s = scenario.segments.find((s) => s.id === id)!;
              return (
                <article key={id}>
                  <Avatar person={person(s.speaker)} size="small" />
                  <div>
                    <header>
                      <strong>{person(s.speaker).name}</strong>
                      <button
                        onClick={() => {
                          setEvidence(null);
                          audio.seek(Math.max(startAt,s.start));
                          void audio.play();
                        }}
                      >
                        {sourcePosition(scenario,s.start) ? `${sourcePosition(scenario,s.start)!.meeting.id} · ${formatTime(sourcePosition(scenario,s.start)!.sourceTime)}` : formatTime(s.start)}
                        <Play size={12} weight="fill" />
                      </button>
                    </header>
                    <p>{s.text}</p>
                  </div>
                </article>
              );
            })}
            <footer>
              <button className="secondary" onClick={() => setEvidence(null)}>
                返回会议
              </button>
            </footer>
          </section>
        </div>
      )}
    </main>
  );
}
