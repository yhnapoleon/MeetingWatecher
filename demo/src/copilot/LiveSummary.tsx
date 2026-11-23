import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { HttpAgent } from '@ag-ui/client';
import { api, type CopilotContext, type Job, type Evidence } from './CopilotPanel';
import './live-summary.css';
import { WorkBoard } from './WorkBoard';

const time=(ms:number)=>`${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
const prompt='只根据新增发言补充或修订已有议题，识别本次明确分工；没有新事实则保持原卡。';

// Switching meetings creates an independent subscription, including its session and in-flight callbacks.
export function LiveSummary(props:CopilotContext) {
  return <SummarySession key={`${props.projectId}-${props.meeting}`} {...props}/>;
}
function SummarySession(props:CopilotContext) {
  const [jobs,setJobs]=useState<Job[]>([]),[selected,setSelected]=useState('');
  const [stage,setStage]=useState(''),[error,setError]=useState(''),[evidence,setEvidence]=useState<Evidence|null>(null);
  const [workTab,setWorkTab]=useState(false),[automatic,setAutomatic]=useState(true);
  const [following,setFollowing]=useState(true),[workOwner,setWorkOwner]=useState<string|undefined>();
  const [comparing,setComparing]=useState(false);
  const state=useRef(props),sid=useRef(''),running=useRef(false),alive=useRef(true);
  const activeAgent=useRef<HttpAgent|null>(null);
  const reading=useRef<HTMLDivElement|null>(null);
  useLayoutEffect(()=>{
    const el=reading.current,scroll=el?.closest('.ai-scroll,.archive-scroll');
    if(!el||!scroll||workTab)return;
    scroll.scrollTop=0;
    const fit=()=>{const room=scroll.getBoundingClientRect().bottom-el.getBoundingClientRect().top-12;el.style.height=`${Math.max(260,room)}px`;};
    fit();const observer=new ResizeObserver(fit);observer.observe(scroll);
    const work=scroll.querySelector('.summary-work-strip');if(work)observer.observe(work);
    return()=>observer.disconnect();
  },[workTab,props.meeting,jobs[0]?.id]);
  state.current=props;
  const sync=async()=>{
    const p=state.current;
    const r=await api(sid.current?`/sessions/${sid.current}`:'/sessions',{project_id:p.projectId,meeting:p.meeting,cursor_ms:Math.round(p.cursor),archives:p.archives},sid.current?'PUT':'POST');
    sid.current=r.id;return r.id as string;
  };
  const refresh=async()=>{
    const id=await sync(); const all:Job[]=await api(`/jobs?session_id=${id}&kind=summary&latest=true`);
    if(alive.current)setJobs(all.filter(j=>j.kind==='summary'&&j.status==='completed'&&(j.result?.live_summary||!props.inMeeting)&&j.scope.meeting_id===(props.meeting?'ES2002c':'ES2002b')).sort((a,b)=>b.scope.cursor_ms-a.scope.cursor_ms));
    return id;
  };
  const generate=async()=>{
    if(running.current)return;
    running.current=true;setError('');setStage('正在整理新增发言');
    try {
      const id=await sync();const progress=await api(`/summary-progress?session_id=${id}`);
      if(!alive.current||!progress.ready)return;
      const agent=new HttpAgent({url:'/api/copilot/runs',threadId:`summary-${props.projectId}-${props.meeting}`,initialMessages:[{id:crypto.randomUUID(),role:'user',content:prompt}]});
      activeAgent.current=agent;
      await agent.runAgent({runId:crypto.randomUUID(),forwardedProps:{copilot:{session_id:id,kind:'summary',incremental:true,extract_work:true}}},{
        onStepStartedEvent:({event})=>{if(alive.current)setStage(event.stepName==='整理回答与引用'?'正在补充议题与分工':event.stepName);},
        onRunErrorEvent:({event})=>{if(alive.current){setError(event.message);setAutomatic(false);}},
      });
      if(alive.current)await refresh();
    } catch(e) {if(alive.current){setError(String(e));setAutomatic(false);}}
    finally {running.current=false;activeAgent.current=null;if(alive.current)setStage('');}
  };
  useEffect(()=>()=>{alive.current=false;activeAgent.current?.abortRun();},[]);
  useEffect(()=>{
    alive.current=true; let pending=false,stopped=false;
    const tick=async()=>{
      if(pending||running.current)return;pending=true;
      try {
        const id=await refresh();const p=state.current;
        const ended=p.cursor>=(p.meeting?782000:389999)-1;
        if(!stopped&&automatic&&((p.inMeeting&&p.playing)||ended)){
          const progress=await api(`/summary-progress?session_id=${id}`);
          if(!stopped&&progress.ready&&(p.inMeeting||progress.processed_until_ms>(p.meeting?390000:0)))void generate();
        }
      }catch(e){if(alive.current){setError(String(e));setAutomatic(false);}}finally{pending=false;}
    };
    void tick();const timer=setInterval(()=>void tick(),1500);
    return()=>{stopped=true;clearInterval(timer);};
  },[automatic]);
  const current=jobs.find(j=>j.scope.cursor_ms<=props.cursor),board=current?.result?.live_summary,cards=board?.cards??[];
  const legacy=!props.inMeeting&&current?.result&&!board?current.result:null;
  const changed=new Set(board?.changed_ids??[]);
  const activeId=following?(board?.changed_ids?.at(-1)??cards.at(-1)?.id):selected;
  const active=cards.find(c=>c.id===activeId)??cards.at(-1);
  const prior=board?.previous_meeting_cards?.find(c=>c.id===active?.prior_topic_id);
  const categoryLabel:Record<string,string>={discussion:'研究与讨论',decision:'明确要求 / 决定',proposal:'方案提议 · 尚未采纳',question:'待核对 / 待验证'};
  const relationLabel:Record<string,string>={new:'本场新增',reaffirmed:'重申上场',changed:'本场变更',questioned:'与上场有差异 · 待核对'};
  const showWork=(owner?:string)=>{setWorkOwner(owner);setWorkTab(true);};
  const refs=(ids:string[])=><div className="summary-refs">{ids.map((id,i)=><button key={id} onClick={()=>setEvidence(current?.result?.evidence.find(e=>e.id===id)??null)}>原话 {i+1} ↗</button>)}</div>;
  const start=current?.scope.meeting_start_ms??(props.meeting?390000:0);
  return <div className="live-summary" data-cursor-ms={props.cursor} data-summary-id={current?.id??''} data-summary-count={board?.generation??jobs.length} data-processed-until={board?.processed_until_ms??start}>
    <nav className="live-mode-tabs"><button className={!workTab?'active':''} onClick={()=>setWorkTab(false)}>动态纪要</button><button className={workTab?'active':''} onClick={()=>showWork()}>行动事项与跟进</button></nav>
    {workTab&&<WorkBoard {...props} focusOwner={workOwner}/>}<div style={{display:workTab?'none':undefined}}>
    <header className="summary-heading"><div><small><i/>{stage||'随新增发言补充 · 真实模型'}</small><h2>{props.inMeeting?'讨论正在形成':'会议纪要与修订记录'}</h2></div>{(props.inMeeting||!!board)&&<label><input type="checkbox" checked={automatic} onChange={e=>setAutomatic(e.target.checked)}/>自动总结与任务识别</label>}</header>
    <div className="summary-scope"><span>发言到达 → 补充议题 → 保留修订依据</span><span>{current?`本场已处理至 ${time((board?.processed_until_ms??current.scope.cursor_ms)-start)} · 当前 ${time(props.cursor-start)}`:'等待第一段稳定转写'}</span></div>
    {error&&<p className="copilot-error">{error} · 自动更新已暂停，可重新开启或手动重试。</p>}
    {!workTab&&<div className="summary-work-strip"><WorkBoard {...props} preview onOpen={showWork}/></div>}
    {!cards.length&&!legacy&&<div className="summary-empty"><div className="summary-waves"><i/><i/><i/><i/><i/></div><h3>正在听取当前议题</h3><p>发言中出现问题、理由或分工后，在这里逐步记录。</p><small>每约 12 秒新增稳定转写触发一次整理，结果返回后更新</small></div>}
    {legacy&&<section><small>历史整段纪要</small><h3>{legacy.answer.title}</h3><p>{legacy.answer.summary}</p>{legacy.answer.sections.map((s,i)=><article key={i}><h3>{s.title}</h3><p>{s.text}</p>{refs(s.evidence_ids)}</article>)}</section>}
    <div className="summary-reading-layout" ref={reading} style={{display:cards.length?undefined:'none'}}><div className="summary-reading-main"><div className="summary-follow"><strong>当前议题</strong><button onClick={()=>setFollowing(!following)} aria-pressed={following}>{following?'正在跟随讨论':'回到最新讨论'}</button></div><div className="summary-cards">{cards.map((c,i)=><article key={c.id} id={c.id} data-topic-id={c.id} data-revision={c.revision} hidden={c.id!==active?.id} className={`${changed.has(c.id)?'just-updated':''} ${selected===c.id?'selected-topic':''}`}>
      <header><span>{String(i+1).padStart(2,'0')}</span><h3>{c.title}</h3><small>{categoryLabel[c.category??'discussion']}</small></header><div className="topic-relation">{relationLabel[c.relation??'new']}</div>
      <div className="topic-content"><p>{c.text}</p>{refs(c.evidence_ids)}</div>
      <div className="summary-revision">{time(c.created_ms-start)} 开始记录 · {time(c.cursor_ms-start)} {c.revision===1?'新增':'补充 / 修订'} · 第 {c.revision} 版</div>
      {c.history.length>1&&<details className="summary-history"><summary>查看逐步形成过程</summary>{c.history.map((v,n)=><section key={v.job_id}><small>{time(v.cursor_ms-start)} · 第 {n+1} 版</small><p>{v.text}</p>{refs(v.evidence_ids)}</section>)}</details>}
    </article>)}</div>
    {prior&&<button className="prior-topic" onClick={()=>{setSelected(active!.id);setFollowing(false);setComparing(true);}}>对照上场记录：{prior.title} ↗</button>}
    {comparing&&prior&&active&&<section className="topic-comparison" role="dialog" aria-label="两场议题对照"><header><div><small>同一议题 · 各自原话与状态</small><h3>{active.title}</h3></div><button onClick={()=>setComparing(false)} aria-label="关闭议题对照">返回本场纪要 ×</button></header><div className="topic-comparison-grid"><article><small>上场归档</small><h3>{prior.title}</h3><div><p>{prior.text}</p>{refs(prior.evidence_ids)}</div></article><article><small>{relationLabel[active.relation??'new']} · {categoryLabel[active.category??'discussion']}</small><h3>本场新增发言后的记录</h3><div><p>{active.text}</p>{refs(active.evidence_ids)}</div></article></div><p>只比较已经发生的发言；有差异的内容保留待核对状态。</p></section>}

    </div><aside className="summary-index" aria-label="本场议题目录"><h3>本场议题与方案</h3><p>随发言新增，点击查看完整内容</p>{cards.map(c=><button key={c.id} data-topic-nav={c.id} className={active?.id===c.id?'active':''} onClick={()=>{setSelected(c.id);setFollowing(false);}}><small>{categoryLabel[c.category??'discussion']} · 第 {c.revision} 版</small><strong>{c.title}</strong><span>{relationLabel[c.relation??'new']} · {time(c.cursor_ms-start)}</span></button>)}{!cards.length&&<p>等待本场首个议题</p>}</aside></div>
    {props.inMeeting&&<button className="summary-refresh" disabled={!!stage} onClick={()=>void generate()}>处理下一段新增发言</button>}
    {evidence&&<section className="summary-evidence" aria-label="纪要原话证据"><button aria-label="关闭纪要证据" onClick={()=>setEvidence(null)}>×</button><small>{evidence.meeting_id} · {evidence.speaker} · 原会议 {time(evidence.source_start_ms)}</small><h3>这条纪要来自哪里</h3><blockquote>{evidence.quote}</blockquote><p>主会议继续播放 · 引用来自当前已到达的转写</p></section>}
  </div></div>;
}
