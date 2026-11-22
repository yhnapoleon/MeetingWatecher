import { ArrowRight, CheckCircle, Clock, LinkSimple, Stack, ArrowsClockwise } from '@phosphor-icons/react';
import { projectAt, sourcePosition, type Scenario } from './scenario';

export function CrossMeetingPanel({scenario,time,onEvidence,onSeek}: {
  scenario:Scenario;time:number;onEvidence:(ids:string[])=>void;onSeek:(at:number)=>void;
}) {
  const current=sourcePosition(scenario,time)!.meeting;
  const second=scenario.meetings[1];
  const inSecond=time>=second.at;
  const state=projectAt(scenario,time);
  const baseline=projectAt(scenario,Math.min(time,second.at-1));
  const reports=state.tasks.filter(t=>t.status==='进行中');
  const carried=state.decisions.filter(d=>d.reaffirmations.some(r=>r.at>=second.at));
  return <div className="cross-document">
    <div className="cross-heading"><span><Stack size={18}/> 同一项目 · 持续跟进</span><small>预设事件演示</small></div>
    <h2>{inSecond?'上一场的决定，现在怎样了？':'从本场建立项目记忆'}</h2>
    <p className="cross-intro">{inSecond?'旧决定与原任务继续保留；新发言只更新对应事项。':'先记录方案与分工。进入第二场后，追踪重申、阶段汇报和方案修订。'}</p>
    <div className="cross-stats">
      <div><strong>{carried.length}</strong><span>跨会重申</span></div>
      <div><strong>{reports.length}</strong><span>阶段汇报</span></div>
      <div><strong>{state.decisions.filter(d=>baseline.decisions.some(p=>p.id===d.id) && d.versions.some(v=>v.at>=second.at)).length}</strong><span>方案修订</span></div>
    </div>
    <div className="cross-section-title"><ArrowsClockwise size={17}/><h3>决定的延续与变化</h3><span>{current.id}</span></div>
    {['power','audience','grouping'].map(id=>{
      const d=state.decisions.find(d=>d.id===id); if(!d)return null;
      const prior=baseline.decisions.find(d=>d.id===id);
      const introduced=inSecond && !prior;
      const changed=inSecond && !!prior && d.value!==prior.value;
      const reaffirmed=d.reaffirmations.some(r=>r.at>=second.at);
      return <article className={`cross-decision ${changed?'changed':''}`} key={id}>
        <header><strong>{d.title}</strong><span className={changed?'revision-badge':'adopted-badge'}>{introduced?'本场新增':changed?'已修订':reaffirmed?'已重申':inSecond?'沿用上场':'本场形成'}</span></header>
        <div className="cross-comparison">
          <div><small>{scenario.meetings[0].id} · 上一版</small><p>{prior?.value??'前场未形成'}</p></div><ArrowRight size={18}/>
          <div><small>{inSecond?'ES2002c · 当前':'等待下一场'}</small><p>{inSecond?d.value:'尚未开始'}</p></div>
        </div>
        <footer>{prior&&<button onClick={()=>onEvidence(prior.evidence)}><LinkSimple size={13}/>前场原话</button>}
          {(introduced||changed||reaffirmed)&&<button onClick={()=>onEvidence(d.evidence)}><LinkSimple size={13}/>本场原话</button>}
          <span>{d.versions.length} 个历史版本 · {d.reaffirmations.length} 次重申</span></footer>
      </article>;
    })}
    {!state.decisions.length&&<p className="document-empty">播放后，确定的方案会出现在这里。</p>}
    <div className="cross-section-title"><CheckCircle size={17}/><h3>原任务的进展</h3><span>保持同一任务</span></div>
    {state.tasks.map(t=>{
      const prior=baseline.tasks.find(b=>b.id===t.id);
      const person=scenario.people.find(p=>p.id===t.owner)!;
      return <article className="cross-task" key={t.id}>
        <div className="cross-person" style={{background:person.color}}>{person.initial}</div>
        <div><header><strong>{t.title}</strong><span>{t.status==='进行中'?'已汇报 · 进行中':t.status}</span></header>
          <p>{t.detail}</p><small>{person.name} · {t.due}</small>
          <footer><button onClick={()=>onEvidence(prior?.evidence??t.evidence)}>{inSecond&&!prior?'查看本场分工':'查看原分工'}</button>
          {prior&&t.status==='进行中'&&<button onClick={()=>onEvidence(t.evidence)}>查看本场汇报</button>}</footer>
        </div>
      </article>;
    })}
    {inSecond&&<p className="cross-note"><Clock size={14}/> 阶段汇报不等于完成验收；未提到的事项保留原状态。</p>}
    {!inSecond&&<p className="cross-note"><Clock size={14}/> 归档后可在项目内新建后续会议，自动承接这些内容。</p>}
  </div>;
}
