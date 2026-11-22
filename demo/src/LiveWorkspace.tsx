import { ArrowRight, CheckCircle, Flag, ListChecks, LinkSimple, Stack, TreeStructure, Waveform } from '@phosphor-icons/react';
import { DiscussionGraph } from './MinutesPanel';
import { minutesAt, visibleChapters } from './minutes';
import { formatTime, projectAt, sourcePosition, type Scenario } from './scenario';
import './live-workspace.css';

export function LiveWorkspace({ scenario, time, onEvidence }: { scenario: Scenario; time: number; onEvidence: (ids: string[]) => void }) {
  const state = projectAt(scenario, time);
  const meeting = sourcePosition(scenario, time)?.meeting;
  const start = meeting?.at ?? 0;
  const baseline = start ? projectAt(scenario, start - 1) : null;
  const chapter = visibleChapters(scenario, time).at(-1);
  const nodes = minutesAt(scenario, time);
  const decisions = [...state.decisions].sort((a, b) => Math.max(b.versions.at(-1)!.at, b.reaffirmations.at(-1)?.at ?? 0) - Math.max(a.versions.at(-1)!.at, a.reaffirmations.at(-1)?.at ?? 0));
  return <div className="live-workspace">
    <header className="live-topic"><div><span className="live-eyebrow"><span className="listening-dot" />正在讨论</span><h2>{chapter?.title.replace(/^第二场 · /, '') ?? '等待讨论展开'}</h2></div><div className="live-counts"><span><Flag size={14} />{state.decisions.length} 项决定</span><span><ListChecks size={15} />{state.tasks.length} 项行动</span></div></header>
    {baseline && <details className="carry-strip"><summary><Stack size={16} /><strong>上场已确认</strong><span>{baseline.decisions.length} 项决定 · {baseline.tasks.length} 项任务</span><small>查看承接内容</small></summary><div>{baseline.decisions.map(d => <span key={d.id}>{d.title}：<b>{d.value}</b></span>)}</div></details>}
    <section className="outcomes-section" aria-label="会议结论与决定">
      <div className="live-section-heading"><h3><CheckCircle size={20} weight="fill" />结论与决定</h3><span>{baseline ? '沿用已有共识，随本场讨论更新' : '从讨论中确认，保留原话依据'}</span></div>
      {!decisions.length ? <div className="outcomes-empty"><Waveform size={30} /><div><strong>正在听取方案与理由</strong><p>形成共识后，决定会出现在这里。</p></div><span className="sound-bars"><i /><i /><i /><i /></span></div> : <div className={`outcome-grid ${decisions.length === 1 ? 'single' : ''}`}>
        {decisions.map(d => {
          const changedAt = Math.max(d.versions.at(-1)!.at, d.reaffirmations.at(-1)?.at ?? 0);
          const inherited = changedAt < start;
          const revised = d.versions.length > 1;
          const recent = !inherited && time - changedAt < 16000;
          const prior = d.versions.at(-2);
          return <article key={d.id} className={`outcome-card ${revised ? 'revised' : ''} ${inherited ? 'inherited' : ''} ${recent ? 'fresh' : ''}`} data-decision={d.id}>
            <header><span className="outcome-icon"><CheckCircle weight="fill" size={20} /></span><h4>{d.title}</h4><span className="outcome-status">{inherited ? '沿用上场' : revised ? '已修订' : d.reaffirmations.length ? '本场重申' : '已确认'}</span></header>
            <div className="outcome-value" key={d.value}>{d.value}{d.unit && <small>{d.unit}</small>}</div>
            {revised && prior && !inherited ? <div className="outcome-diff"><span>原方案</span><del>{prior.value}</del><ArrowRight size={15} /><strong>采用新方案</strong></div> : <p>{inherited ? '来自已归档会议 · 保留同一事项' : d.detail}</p>}
            <footer><span>{recent ? <><i />刚刚{revised ? '更新' : '确认'}</> : inherited ? '项目记忆' : `${formatTime(changedAt - start)} · 已记录`}</span><button onClick={() => onEvidence(d.evidence)} aria-label={`查看${d.title}原话`}><LinkSimple size={13} />原话依据</button></footer>
          </article>;
        })}
      </div>}
    </section>
    <div className="live-detail-grid">
      <section className="live-graph-panel"><div className="live-section-heading"><h3><TreeStructure size={19} />讨论脉络</h3><span>观点随发言逐步连接</span></div><DiscussionGraph items={nodes} onEvidence={onEvidence} /></section>
      <section className="live-task-panel"><div className="live-section-heading"><h3><ListChecks size={20} />接下来做什么</h3><span>{state.tasks.length} 项行动</span></div>
        {!state.tasks.length && <div className="live-task-empty"><ListChecks size={27} /><p>听取分工，明确负责人和交付内容</p></div>}
        <div className="live-task-list">{state.tasks.map(t => {
          const person = scenario.people.find(p => p.id === t.owner)!;
          const update = state.changes.filter(c => c.kind === 'task' && c.evidence.some(id => t.evidence.includes(id))).at(-1);
          const fresh = update && update.at >= start && time - update.at < 14000;
          return <article className={`live-task ${fresh ? 'fresh' : ''}`} key={t.id}><i className="task-owner-avatar" style={{ background: person.color }}>{person.initial}</i><div><header><strong>{t.title}</strong><span className={t.status === '进行中' ? 'in-progress' : ''}>{t.status === '进行中' ? '已汇报 · 进行中' : t.status}</span></header><p>{person.name}<span>·</span>{t.due}</p></div><button aria-label={`查看${person.name}任务依据`} onClick={() => onEvidence(t.evidence)}><LinkSimple size={15} /></button></article>;
        })}</div>
      </section>
    </div>
  </div>;
}
