import { useEffect, useState } from 'react';
import { App } from './App';
import { MinutesPanel } from './MinutesPanel';
import { CrossMeetingPanel } from './CrossMeetingPanel';
import { formatTime, projectAt, sourcePosition, validateScenario, type Scenario } from './scenario';
import './project.css';

type Archive = { meeting: number; time: number; scenario: Scenario };
type Meeting = { title: string; members: string[] };
type Project = { id: string; name: string; archives: Archive[]; meetings: Meeting[] };
const KEY = 'meeting-projects-v1';
const firstMeeting = (): Meeting => ({ title: '功能方案与分工', members: ['B', 'A', 'C', 'D'] });
const newProject = (id: string, name: string): Project => ({ id, name, archives: [], meetings: [firstMeeting()] });

export function ProjectApp() {
  const [scenario, setScenario] = useState<Scenario>();
  const [projects, setProjects] = useState<Project[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null');
      return saved?.map((p: Project) => ({ ...p, meetings: p.meetings ?? [firstMeeting(), ...(p.archives.some(a => a.meeting === 1) ? [{ title: '方案汇报与迭代', members: ['B', 'A', 'C', 'D'] }] : [])] })) ?? [newProject('remote', '遥控器产品设计')];
    } catch { return [newProject('remote', '遥控器产品设计')]; }
  });
  const [selected, setSelected] = useState('remote');
  const [page, setPage] = useState('home');
  const [meeting, setMeeting] = useState(0);
  const [session, setSession] = useState<Scenario>();
  const [error, setError] = useState('');
  const [dialog, setDialog] = useState<'create' | 'invite' | null>(null);
  const [title, setTitle] = useState('');
  const [archiveTab, setArchiveTab] = useState('minutes');
  const [evidence, setEvidence] = useState<string[] | null>(null);
  const project = projects.find(p => p.id === selected)!;
  const latest = project?.archives.at(-1);
  const active = project?.meetings[meeting];
  const saved = project?.archives.find(a => a.meeting === meeting);
  const prior = project?.archives.filter(a => a.meeting < meeting).at(-1);

  useEffect(() => { fetch('/scenario-cross.json').then(r => r.json()).then(r => setScenario(validateScenario(r))).catch(e => setError(String(e))); }, []);
  useEffect(() => localStorage.setItem(KEY, JSON.stringify(projects)), [projects]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (page === 'prepare' && meeting > 0 && e.altKey && e.code === 'KeyI') { e.preventDefault(); setDialog('invite'); }
      if (e.key === 'Escape') { setDialog(null); setEvidence(null); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [page, meeting]);
  if (!scenario) return <div className="project-page">{error || '正在载入会议项目…'}</div>;

  const updateProject = (value: Project) => setProjects(ps => ps.map(p => p.id === selected ? value : p));
  const start = () => {
    const begin = meeting ? 390000 : 0;
    setSession({ ...scenario, context: undefined, title: active.title,
      events: [...(prior?.scenario.events.filter(e => e.at <= prior.time) ?? []), ...scenario.events.filter(e => e.at >= begin && e.at < (meeting ? 782001 : 390000))],
      interactions: [...(prior?.scenario.interactions.filter(i => i.completeAt <= prior.time) ?? []), ...scenario.interactions.filter(i => i.showAt >= begin && i.showAt < (meeting ? 782001 : 390000))] });
    setPage('meeting');
  };
  const archive = (time: number) => {
    if (!saved) updateProject({ ...project, archives: [...project.archives, { meeting, time, scenario: session! }] });
    setArchiveTab('minutes'); setPage('archive');
  };
  const memory = (a: Archive | undefined) => {
    const state = a ? projectAt(a.scenario, a.time) : null;
    return <div className="memory-body"><h3>有效决定 <b>{state?.decisions.length ?? 0}</b></h3>
      {state?.decisions.map(d => <div className="memory-item" key={d.id}><strong>{d.title}</strong><p>{d.value}</p><small>{d.versions.length} 个版本 · {d.reaffirmations.length} 次重申</small></div>)}
      <h3>行动事项 <b>{state?.tasks.length ?? 0}</b></h3>
      {state?.tasks.map(t => <div className="memory-task" key={t.id}><span>☑</span><div><strong>{t.title}</strong><p>{scenario.people.find(p => p.id === t.owner)?.name} · {t.status}</p></div></div>)}
      {!state && <p className="empty-memory">本项目尚无已归档会议。<br />会议结束后，决定和行动事项将保存在这里。</p>}</div>;
  };
  const seekEvidence = (at: number) => setEvidence(scenario.segments.filter(s => s.start <= at && s.end >= at).map(s => s.id));
  if (page === 'meeting') return <App key={selected + meeting} supplied={session} startAt={meeting ? 390000 : 0} endAt={meeting ? 782000 : 389999} onBack={() => setPage('project')} onArchive={archive} />;
  return <main className="project-shell">
    <aside className="project-sidebar"><div className="project-logo">✦ <strong>MeetingWatcher</strong></div><p>会议协作空间</p><button onClick={() => setPage('home')}>▦　我的项目</button><div className="sidebar-note">让讨论成为项目的记忆<br /><small>真人会议 · 连续协作</small></div></aside>
    <section className="project-page"><header><span>工作空间 / {page === 'home' ? '项目' : project.name}</span><span className="project-avatar">YH</span></header>
      {page === 'home' ? <>
        <div className="page-title"><div><small>WORKSPACE</small><h1>我的项目</h1><p>把每一场讨论，接到下一次行动。</p></div><button className="blue" onClick={() => { const name = prompt('项目名称'); if (name?.trim()) { const id = crypto.randomUUID(); setProjects([...projects, newProject(id, name.trim())]); setSelected(id); setPage('project'); } }}>＋ 新建项目</button></div>
        <div className="project-cards">{projects.map(p => <button className="project-card" key={p.id} onClick={() => { setSelected(p.id); setPage('project'); }}><span className="folder-icon">▱</span><h2>{p.name}</h2><p>从功能定义到方案迭代，让决定与分工持续推进。</p><div className="avatar-line">{scenario.people.map(p => <i key={p.id} style={{ background: p.color }}>{p.initial}</i>)}</div><footer>{p.meetings.length} 场会议 · {p.archives.length} 场已归档 <span>进入项目 →</span></footer></button>)}</div>
        <div className="project-disclosure">演示素材：AMI ES2002b / ES2002c 真人角色扮演会议，CC BY 4.0。字幕来自实际 STT 词轴，中文纪要与交互为预设演示。</div>
      </> : <>
        <div className="page-title"><div><small>PROJECT / REMOTE CONTROL</small><h1>{page === 'prepare' ? '准备开始会议' : page === 'archive' ? '本场会议已归档' : project.name}</h1><p>{page === 'project' ? '同一项目下的会议，自动承接已有决定与未完成工作。' : active.title}</p></div><button onClick={() => setPage('project')}>返回项目</button></div>
        {page === 'project' ? <div className="project-columns"><div>
          <div className="section-heading"><h2>项目会议</h2><button className="blue" disabled={!latest || project.meetings.length >= 2} onClick={() => { setTitle(''); setDialog('create'); }}>＋ 新建会议</button></div>
          {project.meetings.map((m, n) => { const a = project.archives.find(a => a.meeting === n); return <article className="meeting-card" key={n}><div className="meeting-number">0{n + 1}</div><div><span className={a ? 'saved-tag' : 'pending-tag'}>{a ? '已归档' : '待开始'}</span><h2>{m.title}</h2><p>{n ? '继承项目记忆 · 继续协作' : '目标用户 · 功能框架 · 任务分工'}</p><small>{m.members.length} 位成员 · {n ? '项目内创建' : '真人会议节选'}</small></div><button className="blue" onClick={() => { setMeeting(n); if (a) { setArchiveTab('minutes'); setPage('archive'); } else setPage('prepare'); }}>{a ? '查看归档' : '进入会议'} →</button></article>; })}
          <div className="carry-explainer"><strong>✦ 项目记忆随会议积累</strong><p>归档后保留有效决定、任务状态与原话来源。新建后续会议时自动带入，同一事项持续更新。</p></div>
        </div><aside className="memory-panel"><h2>项目记忆</h2><small>{latest ? `来自 0${latest.meeting + 1} ${project.meetings[latest.meeting].title}` : '等待第一场会议归档'}</small>{memory(latest)}</aside></div>
        : page === 'archive' && saved ? <div className="archive-layout">
          <div className="archive-document"><nav className="archive-tabs"><button className={archiveTab === 'minutes' ? 'active' : ''} onClick={() => setArchiveTab('minutes')}>会议纪要</button><button className={archiveTab === 'cross' ? 'active' : ''} onClick={() => setArchiveTab('cross')}>项目承接</button><span>已保存 · 原话可追溯</span></nav>
            <div className="archive-scroll">{archiveTab === 'minutes' ? <MinutesPanel scenario={saved.scenario} time={saved.time} onEvidence={setEvidence} onSeek={seekEvidence} archived /> : <CrossMeetingPanel scenario={saved.scenario} time={saved.time} onEvidence={setEvidence} onSeek={seekEvidence} />}</div>
          </div><aside className="memory-panel"><h2>留给下一场的内容</h2>{memory(saved)}<button className="blue large" onClick={() => setPage('project')}>返回项目，查看累计结果 →</button></aside>
        </div> : <div className="preparation-grid"><div className="preparation-main"><span className="saved-tag">同一项目 · 自动承接</span><h2>{active.title}</h2><p>{project.name} / {meeting ? '新建会议' : '第一场会议'}</p>
          <div className="participant-heading"><h3>参会成员 <small>{active.members.length} / 4</small></h3>{meeting > 0 && <button onClick={() => setDialog('invite')}>邀请上场成员 <kbd>Alt I</kbd></button>}</div>
          <div className="people-grid">{scenario.people.filter(p => active.members.includes(p.id)).map(p => <div key={p.id}><i style={{ background: p.color }}>{p.initial}</i><strong>{p.name}</strong><small>{p.role}</small><span className="member-ready">已加入</span></div>)}</div>
          {meeting > 0 && active.members.length === 1 && <p className="invite-hint">按 <kbd>Alt</kbd> + <kbd>I</kbd>，快速邀请上场的 3 位协作成员。</p>}
          <div className="carry-explainer"><h3>{meeting ? `已继承上一场：${project.meetings[0].title}` : '从本场建立项目记忆'}</h3><p>{meeting ? '已归档的决定和任务自动带入，保留来源与历史。本场新纪要将在发言后逐步生成。' : '讨论中的决定与分工将实时记录，并在归档后用于后续会议。'}</p></div>
          <button className="blue large" disabled={active.members.length < 4} onClick={start}>进入会议现场 →</button>
        </div><aside className="memory-panel"><h2>会前承接</h2>{memory(prior)}</aside></div>}
      </>}
    </section>
    {dialog && <div className="project-overlay"><section className="project-dialog" role="dialog" aria-modal="true" aria-label={dialog === 'create' ? '新建项目会议' : '邀请上场成员'}>
      <small>{project.name}</small><h2>{dialog === 'create' ? '新建项目会议' : '邀请上场成员'}</h2>
      {dialog === 'create' ? <><p>此会议将自动继承本项目最近一次归档。</p><label>会议名称<input autoFocus value={title} onChange={e => setTitle(e.target.value)} placeholder="例如：方案汇报与迭代" /></label><div className="dialog-summary">✦ 已连接项目记忆 · {latest ? projectAt(latest.scenario, latest.time).decisions.length : 0} 项决定 · {latest ? projectAt(latest.scenario, latest.time).tasks.length : 0} 项任务</div><footer><button onClick={() => setDialog(null)}>取消</button><button className="blue" disabled={!title.trim()} onClick={() => { const n = project.meetings.length; updateProject({ ...project, meetings: [...project.meetings, { title: title.trim(), members: ['B'] }] }); setMeeting(n); setDialog(null); setPage('prepare'); }}>创建会议</button></footer></>
      : <><p>来自「{project.meetings[0].title}」的协作成员</p><div className="invite-list">{scenario.people.filter(p => p.id !== 'B').map(p => <div key={p.id}><span className="invite-check">✓</span><i style={{ background: p.color }}>{p.initial}</i><strong>{p.name}</strong><small>{p.role}</small></div>)}</div><footer><button onClick={() => setDialog(null)}>取消</button><button className="blue" onClick={() => { updateProject({ ...project, meetings: project.meetings.map((m, n) => n === meeting ? { ...m, members: [...project.meetings[0].members] } : m) }); setDialog(null); }}>邀请 3 位成员加入</button></footer><small className="dialog-footnote">演示成员会自动接受邀请</small></>}
    </section></div>}
    {evidence && <div className="project-overlay"><section className="project-dialog archive-evidence" role="dialog" aria-label="归档原话"><h2>讨论依据</h2>{scenario.segments.filter(s => evidence.includes(s.id)).map(s => <article key={s.id}><small>{scenario.people.find(p => p.id === s.speaker)?.name} · {sourcePosition(scenario, s.start)?.meeting.id} · {formatTime(sourcePosition(scenario, s.start)?.sourceTime ?? s.start)}</small><p>{s.text}</p></article>)}{!evidence.length && <p>此时间点没有发言，可点击带来源的决定或图节点查看原话。</p>}<footer><button onClick={() => setEvidence(null)}>关闭原话</button></footer></section></div>}
  </main>;
}
