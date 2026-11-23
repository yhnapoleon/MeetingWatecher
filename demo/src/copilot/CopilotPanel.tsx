import { useEffect, useRef, useState } from 'react';
import { HttpAgent } from '@ag-ui/client';
import './copilot.css';
import { WorkBoard } from './WorkBoard';

export type Evidence = { id:string; meeting_id:string; speaker:string; quote:string; start_ms:number|null; source_start_ms:number; provenance:string;url?:string };
export type Answer = {title:string;summary:string;sections:{title:string;text:string;kind:string;evidence_ids:string[]}[];columns:string[];rows:{cells:string[];evidence_ids:string[]}[];questions:string[];impact?:{change:string;target:string;reason:string;action:string}|null};
export type TopicVersion = {category?:'discussion'|'decision'|'proposal'|'question';prior_topic_id?:string|null;relation?:'new'|'reaffirmed'|'changed'|'questioned';title:string;text:string;kind:string;evidence_ids:string[];cursor_ms:number;job_id:string};
export type TopicCard = TopicVersion & {id:string;revision:number;created_ms:number;history:TopicVersion[]};
export type Result = {answer:Answer;evidence:Evidence[];coverage:Record<string,unknown>;model:string;live_summary?:{previous_meeting_cards?:TopicCard[];cards:TopicCard[];changed_ids:string[];processed_until_ms:number;generation?:number}};
export type Job = {id:string;kind:string;status:string;prompt:string;scope:{cursor_ms:number;meeting_id:string;meeting_start_ms:number};elapsed_s?:number;error?:string;result?:Result;artifact?:{id:string;version:number;files:string[];title:string}};
type Proposal = {id:string;state:string;impact:{change:string;target:string;reason:string;action:string};task?:{summary:string;guid:string}};
export type CopilotContext = {projectId:string;meeting:number;cursor:number;archives:{meeting:number;cursor_ms:number}[];inMeeting?:boolean;cue?:string;playing?:boolean};
const labels:Record<string,string>={work:'行动事项',qa:'问项目',catchup:'会中补课',brief:'会前简报',comparison:'方案比较',validation:'验证清单',revise:'材料修改',impact:'影响分析',handover:'交付包'};
const statuses:Record<string,string>={queued:'排队中',running:'执行中',completed:'已完成',failed:'失败',cancel_requested:'正在取消',cancelled:'已取消'};
const clock=(ms:number)=>`${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;

export async function api(path:string,body?:unknown,method='POST') {
  const res=await fetch('/api/copilot'+path,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!res.ok){let message='助手服务暂不可用';try{message=(await res.json()).detail||message;}catch{}throw new Error(typeof message==='string'?message:JSON.stringify(message));}
  return res.json();
}

export function CopilotPanel(props:CopilotContext) {
  const [open,setOpen]=useState(false),[ready,setReady]=useState(false),[error,setError]=useState('');
  const [input,setInput]=useState(''),[kind,setKind]=useState('qa'),[template,setTemplate]=useState('design');
  const [jobs,setJobs]=useState<Job[]>([]),[selected,setSelected]=useState(''),[stage,setStage]=useState('');
  const [busy,setBusy]=useState(false),[evidence,setEvidence]=useState<Evidence|null>(null);
  const [research,setResearch]=useState(false);
  const [automatic,setAutomatic]=useState(false),[proposals,setProposals]=useState<Proposal[]>([]);
  const session=useRef(''),latest=useRef(props),lastImpact=useRef(-1),running=useRef(false);
  const activeRun=useRef<{id:string;agent:HttpAgent}|null>(null);
  const selectedJob=jobs.find(j=>j.id===selected)??jobs[0];
  latest.current=props;
  const payload=()=>({project_id:latest.current.projectId,meeting:latest.current.meeting,cursor_ms:Math.round(latest.current.cursor),archives:latest.current.archives});
  const sync=async()=>{
    const info=await api(session.current?`/sessions/${session.current}`:'/sessions',payload(),session.current?'PUT':'POST');
    session.current=info.id;return info.id as string;
  };
  const refresh=async(sid:string)=>{
    const [js,ps]=await Promise.all([api(`/jobs?session_id=${sid}&include_summaries=false`),api(`/proposals?session_id=${sid}`)]);
    setJobs(js.filter((j:Job)=>j.kind!=='summary'));setProposals(ps);
    const active=activeRun.current;
    if(active&&js.some((j:Job)=>j.id===active.id&&['completed','failed','cancelled'].includes(j.status))){
      activeRun.current=null;running.current=false;setBusy(false);setStage('');active.agent.abortRun();
    }
  };
  useEffect(()=>{
    let alive=true;session.current='';setEvidence(null);setSelected('');setJobs([]);lastImpact.current=-1;
    const tick=async()=>{try {const sid=await sync();if(!alive)return;setReady(true);await refresh(sid);}catch(e){if(alive){setReady(false);setError(String(e));}}};
    void tick();const timer=setInterval(()=>void tick(),3000);
    return()=>{alive=false;clearInterval(timer);};
  },[props.projectId,props.meeting]);

  const run=async(mode:string,text:string,windowMs=120000,reformat=false)=>{
    if(running.current)return;
    running.current=true;setBusy(true);setError('');setStage('已接收');setEvidence(null);
    if(mode!=='impact')setOpen(true);
    const id=crypto.randomUUID();
    try{
      const sid=await sync();
      const agent=new HttpAgent({url:'/api/copilot/runs',threadId:`${props.projectId}-${props.meeting}`,
        initialMessages:[{id:crypto.randomUUID(),role:'user',content:text}]});
      activeRun.current={id,agent};setSelected(id);
      await agent.runAgent({runId:id,forwardedProps:{copilot:{session_id:sid,kind:mode,window_ms:windowMs,template,
        research:research&&['comparison','validation'].includes(mode),artifact_id:mode==='revise'||reformat?selectedJob?.artifact?.id:undefined}}},{
        onStepStartedEvent:({event})=>{if(activeRun.current?.id===id)setStage(event.stepName);},
        onRunErrorEvent:({event})=>{if(activeRun.current?.id===id)setError(event.message);},
      });
      await refresh(sid);setStage('');
    }catch(e){if(activeRun.current?.id===id)setError(String(e));}finally{if(activeRun.current?.id===id){activeRun.current=null;running.current=false;setBusy(false);}}
  };
  useEffect(()=>{
    if(!automatic||!props.inMeeting||!props.playing||!ready||busy)return;
    const time=Math.round(props.cursor);
    if(time-lastImpact.current<30000||!/battery|kinetic|power|instead|component/i.test(props.cue??''))return;
    lastImpact.current=time;
    void run('impact','检查刚才的新方案是否影响此前供电、成本、体积或已确认任务。仅有重申不要提醒。',30000);
  },[automatic,props.cue,Math.floor(props.cursor/5000),props.playing,ready,busy]);

  const showRef=(id:string)=>setEvidence(selectedJob?.result?.evidence.find(e=>e.id===id)??null);
  const referenceButtons=(ids:string[])=><span className="copilot-refs">{ids.slice(0,3).map((id,i)=><button key={id} onClick={()=>showRef(id)} title={id}>原话 {i+1}</button>)}{ids.length>3&&<details><summary>其余 {ids.length-3} 条依据</summary>{ids.slice(3).map((id,i)=><button key={id} onClick={()=>showRef(id)} title={id}>原话 {i+4}</button>)}</details>}</span>;
  const pending=proposals.filter(p=>p.state==='proposed');
  const action=async(id:string,verb:string)=>{try{await api(`/proposals/${id}/${verb}?session_id=${session.current}`,{});await refresh(session.current);}catch(e){setError(String(e));}};
  return <>
    <button className="copilot-launch" onClick={()=>setOpen(!open)} aria-label="打开项目助手">✦ 项目助手 {pending.length>0&&<b>{pending.length}</b>}<small>{ready?'已连接':'未连接'}</small></button>
    {open&&<aside className={`copilot-panel ${new URLSearchParams(location.search).has('showcase')?'showcase':''}`} aria-label="项目助手">
      <header><div><strong>✦ 项目助手</strong><small>真实模型 · 按当前进度读取证据</small></div><button aria-label="关闭项目助手" onClick={()=>setOpen(false)}>×</button></header>
      <div className="copilot-body">
        <p className="copilot-boundary">{new URLSearchParams(location.search).has('showcase')?'会议原声与 STT 词轴回放 · 总结、问答与材料由模型现场生成':'当前字幕为 STT 回放；下方回答由模型生成，与主视图预设纪要分开。'}</p>
        <div className="copilot-actions">
          {!props.inMeeting&&<button disabled={!ready||busy} onClick={()=>void run('brief','整理会前简报：上次决定、尚未确认的分工和本次建议议题。')}>准备这场会议</button>}
          {props.inMeeting&&<><button disabled={!ready||busy} onClick={()=>void run('catchup','最近两分钟发生了什么变化？',120000)}>最近两分钟</button><button disabled={!ready||busy} onClick={()=>void run('catchup','最近五分钟讨论了什么？',300000)}>最近五分钟</button></>}
          {!props.inMeeting&&props.archives.length>0&&<><select aria-label="交付模板" value={template} onChange={e=>setTemplate(e.target.value)}><option value="design">设计评审</option><option value="sync">项目同步</option></select><button disabled={!ready||busy} onClick={()=>void run('handover','整理本场会议结果与项目承接，附已有材料和待确认问题。')}>生成交付包</button></>}
        </div>
        {props.inMeeting&&<label className="copilot-auto"><input type="checkbox" checked={automatic} onChange={e=>setAutomatic(e.target.checked)}/>自动影响提醒<small>按讨论内容触发 · 每场最多 8 次</small></label>}
        {pending.slice(0,1).map(p=><article className="copilot-impact" key={p.id}><b>可能影响 · {p.impact.target}</b><p>{p.impact.change}</p><p>{p.impact.reason}</p><small>建议：{p.impact.action}</small><div><button onClick={()=>void action(p.id,'accept')}>加入我的待办</button><button onClick={()=>void run('validation',p.impact.action)}>生成验证清单</button><button onClick={()=>void action(p.id,'dismiss')}>忽略</button></div></article>)}
        {proposals.filter(p=>p.state==='accepted').map(p=><p className="copilot-confirmed" key={p.id}>✓ 我的待办：{p.task?.summary}</p>)}
        <form onSubmit={e=>{e.preventDefault();if(input.trim())void run(kind,input);}}>
          <select aria-label="任务类型" value={kind} onChange={e=>setKind(e.target.value)}><option value="qa">问项目</option><option value="catchup">会中补课 · 最近两分钟</option><option value="work">整理行动事项与进展</option><option value="comparison">委派：方案比较</option><option value="validation">委派：验证清单</option>{selectedJob?.artifact&&<option value="revise">修改当前材料</option>}</select>
          <textarea aria-label="助手指令" value={input} onChange={e=>setInput(e.target.value)} placeholder="上次为什么选择普通电池？也可以委派一份方案比较。"/>
          {['comparison','validation'].includes(kind)&&<label className="copilot-auto"><input type="checkbox" checked={research} onChange={e=>setResearch(e.target.checked)}/>补充公开资料（会向搜索服务发送检索词）</label>}
          <button className="copilot-primary" disabled={!ready||busy||!input.trim()}>{busy?stage||'执行中…':'发送'}</button>
        </form>
        {error&&<p role="alert" className="copilot-error">{error}</p>}
        <nav className="copilot-history" aria-label="助手任务历史">{jobs.slice(0,12).map(j=><button key={j.id} className={selectedJob?.id===j.id?'active':''} onClick={()=>{setSelected(j.id);setEvidence(null);}}>{labels[j.kind]} · {statuses[j.status]}</button>)}</nav>
        {selectedJob&&<article className="copilot-answer">
          <div className="copilot-job-meta">{labels[selectedJob.kind]} · {statuses[selectedJob.status]} · 截至本场 {clock(selectedJob.scope.cursor_ms-selectedJob.scope.meeting_start_ms)}{selectedJob.elapsed_s!==undefined&&` · ${selectedJob.elapsed_s}s`}</div>
          <p className="copilot-prompt">{selectedJob.prompt}</p>
          {['queued','running','cancel_requested'].includes(selectedJob.status)&&<button onClick={()=>void api(`/jobs/${selectedJob.id}/cancel?session_id=${session.current}`,{}).then(()=>refresh(session.current))}>取消任务</button>}
          {selectedJob.error&&<p className="copilot-error">{selectedJob.error}</p>}
          {selectedJob.result&&<><h2>{selectedJob.artifact?.title??selectedJob.result.answer.title}</h2><p>{selectedJob.result.answer.summary}</p>{selectedJob.kind==='catchup'&&<small className="copilot-boundary">稳定转写覆盖本场 {clock(Number(selectedJob.result.coverage.stable_start_ms??selectedJob.result.coverage.requested_start_ms)-selectedJob.scope.meeting_start_ms)}–{clock(Number(selectedJob.result.coverage.stable_end_ms)-selectedJob.scope.meeting_start_ms)}；边界尚未结束的发言会在下一次更新纳入。</small>}
            {selectedJob.result.answer.sections.map((s,i)=><section key={i}><h3>{s.title}<small>{s.kind==='suggestion'?'建议':s.kind==='unknown'?'待确认':''}</small></h3><p>{s.text}</p>{referenceButtons(s.evidence_ids)}</section>)}
            {!!selectedJob.result.answer.columns.length&&<div className="copilot-table"><table><thead><tr>{selectedJob.result.answer.columns.map((c,i)=><th key={i}>{c}</th>)}<th>依据</th></tr></thead><tbody>{selectedJob.result.answer.rows.map((r,i)=><tr key={i}>{r.cells.map((c,n)=><td key={n}>{c}</td>)}<td>{referenceButtons(r.evidence_ids)}</td></tr>)}</tbody></table></div>}
            {!!selectedJob.result.answer.questions.length&&<section><h3>待确认</h3><ul>{selectedJob.result.answer.questions.map((q,i)=><li key={i}>{q}</li>)}</ul></section>}
          </>}
          {selectedJob.kind==='work'&&selectedJob.status==='completed'&&<WorkBoard {...props}/>}
          {selectedJob.artifact&&<div className="copilot-downloads"><b>材料 v{selectedJob.artifact.version}</b>{selectedJob.artifact.files.map(f=><a key={f} href={`/api/copilot/artifacts/${selectedJob.artifact!.id}/${encodeURIComponent(f)}?session_id=${session.current}`} download>{f}</a>)}<button onClick={()=>{setKind('revise');setInput('只保留成本、体积、风险三个维度，并保留依据。');}}>修改这份材料</button>{selectedJob.kind==='handover'&&<button disabled={busy} onClick={()=>void run('handover','保留事实与材料版本，按所选模板重新导出。',120000,true)}>按所选模板重新导出</button>}</div>}
        </article>}
      </div>
      {evidence&&<section className="copilot-evidence" aria-label="助手原话证据"><button aria-label="关闭证据" onClick={()=>setEvidence(null)}>×</button><small>{evidence.meeting_id} · {evidence.speaker} {evidence.url?'':`· 原会议 ${clock(evidence.source_start_ms)}`}</small><blockquote>{evidence.quote}</blockquote><small>{{stt_replay:'STT 转写回放',corpus_transcript:'归档人工逐字稿',external_document:'外部网页正文',external_summary:'搜索摘要（未取得正文）'}[evidence.provenance]??evidence.provenance} · {evidence.id}</small>{evidence.url&&/^https?:\/\//.test(evidence.url)&&<a href={evidence.url} target="_blank" rel="noreferrer">打开来源网页 ↗</a>}{evidence.start_ms!==null&&<video key={evidence.id} src="/video/ami-es2002-bc.mp4" muted controls onLoadedMetadata={e=>{e.currentTarget.currentTime=evidence.start_ms!/1000;}}/>}<p>查看依据不会暂停当前会议；证据视频默认静音。</p></section>}
    </aside>}
  </>;
}
