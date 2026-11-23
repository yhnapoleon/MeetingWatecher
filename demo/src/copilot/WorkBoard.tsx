import {useEffect,useRef,useState} from 'react';
import {api,type CopilotContext,type Evidence} from './CopilotPanel';
import './work.css';

type Change={target_guid:string|null;owner:string;title:string;object_text?:string|null;deadline_text?:string|null;due_text:string|null;state:string;detail:string;evidence_ids:string[]};
type Proposal={id:string;origin?:string;scope?:{meeting_id:string;cursor_ms:number;meeting_start_ms:number};change:Change;evidence:Evidence[]};
type Work={guid:string;owner:string;title:string;object_text?:string|null;deadline_text?:string|null;origin?:string;created_origin?:string;due_text:string|null;state:string;detail:string;note:string;evidence:Evidence[];revision:string;scope:{meeting_id:string;cursor_ms:number};created_scope:{meeting_id:string}};
const labels:Record<string,string>={open:'待开展',progress:'进行中 · 已汇报',done:'已完成'};
const stamp=(e:Evidence)=>`${e.meeting_id} · ${e.speaker} · ${Math.floor(e.source_start_ms/60000)}:${String(Math.floor(e.source_start_ms/1000)%60).padStart(2,'0')}`;

export function WorkBoard(props:CopilotContext&{compact?:boolean;preview?:boolean;onOpen?:(owner?:string)=>void;focusOwner?:string}){
 const [focusOwner,setFocusOwner]=useState(props.focusOwner);
 useEffect(()=>setFocusOwner(props.focusOwner),[props.focusOwner]);
 const latest=useRef(props),sid=useRef('');latest.current=props;
 const [data,setData]=useState<{tasks:Work[];history:Work[];proposals:Proposal[]}>({tasks:[],history:[],proposals:[]});
 const [error,setError]=useState(''),[editing,setEditing]=useState(''),[note,setNote]=useState(''),[due,setDue]=useState(''),[state,setState]=useState('open'),[busy,setBusy]=useState(false),[selected,setSelected]=useState(''),[evidence,setEvidence]=useState<Evidence|null>(null);
 const refresh=async()=>{
  const p=latest.current;
  const s=await api(sid.current?`/sessions/${sid.current}`:'/sessions',{project_id:p.projectId,meeting:p.meeting,cursor_ms:Math.round(p.cursor),archives:p.archives},sid.current?'PUT':'POST');
  sid.current=s.id;return api(`/work?session_id=${s.id}`);
 };
 useEffect(()=>{let alive=true,pending=false;sid.current='';
  const tick=async()=>{if(pending)return;pending=true;try{const d=await refresh();if(alive)setData(d);}catch(e){if(alive)setError(String(e));}finally{pending=false;}};
  void tick();const timer=setInterval(()=>void tick(),2500);return()=>{alive=false;clearInterval(timer);};
 },[props.projectId,props.meeting]);
 const confirm=async(p:Proposal)=>{setBusy(true);setError('');try{
  await refresh();await api(`/work/${p.id}/confirm?session_id=${sid.current}`,{note,due_text:due.trim()||null,state});
  setData(await refresh());setEditing('');
 }catch(e){setError(String(e));}finally{setBusy(false);}};
 const refs=(es:Evidence[])=>es.slice(0,2).map((e,i)=><button className="work-ref" key={e.id} onClick={()=>setEvidence(e)}>原话 {i+1} ↗</button>);
 const automatic=data.proposals.filter(p=>p.origin==='automatic');
 const meetingId=props.meeting?'ES2002c':'ES2002b';
 const original=(task:Work)=>data.history.find(h=>h.guid===task.guid)??task;
 const pendingFor=(guid:string)=>data.proposals.find(p=>p.change.target_guid===guid);
 const newItems=data.proposals.filter(p=>!p.change.target_guid&&p.scope?.meeting_id===meetingId);
 const carried=data.proposals.filter(p=>!p.change.target_guid&&p.scope?.meeting_id!==meetingId);
 const inheritedTasks=data.tasks.filter(t=>t.created_scope.meeting_id!==meetingId);
 const newTasks=data.tasks.filter(t=>t.created_scope.meeting_id===meetingId);
 const newCount=newItems.length+newTasks.length;
 if(props.preview&&props.meeting)return <aside className="work-continuity"><header><strong>上场分工 → 本场跟进</strong><button onClick={()=>props.onOpen?.()}>查看任务与新增事项</button></header><div>{inheritedTasks.map(t=><button key={t.guid} data-work-preview={t.owner} onClick={()=>props.onOpen?.(t.owner)}><b>{t.owner}</b><span>{t.title}</span><em>{pendingFor(t.guid)?'发现本场进展 · 待确认':t.scope.meeting_id===meetingId?labels[t.state]:'上场待开展 · 等待汇报'}</em></button>)}</div><small>本场新增分工 {newCount} 项 · 上场待确认 {carried.length} 项</small></aside>;
 if(props.preview)return automatic.length?<aside className="work-discovery" data-automatic-count={automatic.length}><div><strong>✦ 自动识别到 {automatic.length} 项行动事项</strong><p>无需输入指令 · 已从发言提取负责人、工作内容与时间要求</p><small>{automatic.map(p=>`${p.change.owner} · ${p.change.title}`).join('　/　')}</small></div><button onClick={()=>props.onOpen?.()}>查看自动识别任务</button></aside>:null;
 const focused=data.tasks.find(t=>t.owner===focusOwner);
 const visibleProposals=props.meeting&&!props.compact?data.proposals.filter(p=>p.change.owner===focusOwner):data.proposals;
 const visibleTasks=props.meeting&&!props.compact?data.tasks.filter(t=>t.owner===focusOwner):data.tasks;
 return <section className={`work-board ${props.compact?'compact':''}`} data-work-count={data.tasks.length}>
  <header><div><small>会议工作 · 本地任务模拟器</small><h2>{props.meeting?'上次留下的工作，今天继续跟进':'把分工变成可跟进的工作'}</h2></div><span>{data.tasks.filter(t=>t.state!=='done').length} 项待跟进</span></header>
  {error&&<p className="copilot-error">{error}</p>}
  {!!props.meeting&&!props.compact&&<section className="work-carry-overview"><div className="work-carry-grid">{inheritedTasks.map(t=><button key={t.guid} data-carry-owner={t.owner} className={focusOwner===t.owner?'active':''} onClick={()=>setFocusOwner(t.owner)}><b>{t.owner} · {t.title}</b><span>上场：{labels[original(t).state]}</span><strong>本场：{pendingFor(t.guid)?'新增进展待确认':t.scope.meeting_id===meetingId?labels[t.state]:'等待汇报'}</strong><small>查看原分工与本场变化 ↗</small></button>)}</div><div className="work-new-status"><b>本场新增分工：{newCount} 项</b><span>{newCount?'新分工与原任务进展分别保留':'当前未识别到明确的新分工；方案提议不自动创建任务。'}</span>{newTasks.map(t=><button key={t.guid} onClick={()=>setFocusOwner(t.owner)}>本场新建 · {t.owner} · {t.title}</button>)}{[...newItems,...carried].map(p=><button key={p.id} onClick={()=>setFocusOwner(p.change.owner)}>{p.scope?.meeting_id===meetingId?'本场新增':'上场待确认'} · {p.change.owner} · {p.change.title}</button>)}</div></section>}
  {focused&&focused.created_scope.meeting_id!==meetingId&&!props.compact&&!!props.meeting&&<section className="work-before-after" data-comparison-owner={focused.owner}><header><h3>{focused.owner}：同一项工作的变化</h3><small>{focused.guid}</small></header><div><article><small>上场已确认 · {labels[original(focused).state]}</small><h3>{original(focused).title}</h3><p>{original(focused).detail}</p><span>DDL：{original(focused).deadline_text||'未明确'} · {original(focused).due_text||'未明确时间'}</span>{refs(original(focused).evidence)}</article><article><small>{pendingFor(focused.guid)?'本场自动识别 · 待确认':focused.scope.meeting_id===meetingId?'本场已确认进展':'本场尚无新增进展'}</small><p>{pendingFor(focused.guid)?.change.detail??(focused.scope.meeting_id===meetingId?focused.detail:'继续听取本场汇报，出现新信息后更新。')}</p>{refs(pendingFor(focused.guid)?.evidence??(focused.scope.meeting_id===meetingId?focused.evidence:[]))}</article></div></section>}
  {!props.compact&&!props.meeting&&<section className="work-live" aria-label="行动事项动态识别"><header><strong>随分工发言生成</strong><span>{data.proposals.length} 项待确认</span></header>
   <p>识别后直接出现；后续补充更新原事项，确认后进入任务清单。</p>
   {!data.proposals.length&&!data.tasks.length&&<div className="work-listening">正在听取分工 · 出现明确负责人和工作后生成行动事项</div>}
   <div className="work-live-grid">{data.proposals.map(p=><button key={p.id} data-live-proposal={p.id} data-owner={p.change.owner} onClick={()=>document.getElementById(`work-detail-${p.id}`)?.scrollIntoView({behavior:'smooth',block:'start'})}>
    <small>{p.origin==='automatic'?'会议自动识别':'文字发起整理'} · 待确认</small><b>{p.change.owner}</b><strong>{p.change.title}</strong>
    <span>对象：{p.change.object_text||p.change.title}</span><span>DDL：{p.change.deadline_text||'未明确'}</span><span>时间要求：{p.change.due_text||'本段未明确'}</span>
    <em>{p.scope?`${Math.floor((p.scope.cursor_ms-p.scope.meeting_start_ms)/60000)}:${String(Math.floor((p.scope.cursor_ms-p.scope.meeting_start_ms)/1000)%60).padStart(2,'0')} 发言更新 · `:''}查看详细信息 ↗</em>
   </button>)}</div>
  </section>}
  {!props.compact&&visibleProposals.map(p=><article className="work-proposal" id={`work-detail-${p.id}`} key={p.id} data-proposal={p.id} data-owner={p.change.owner} data-origin={p.origin??'text'}>
   <small className="work-origin">{p.origin==='automatic'?'✦ 会议自动识别':'⌨ 文字发起整理'} · {p.change.target_guid?'进展待确认':'任务待确认'}</small>
   <h3>{p.change.title}</h3>
   <dl className="work-fields"><div><dt>负责人</dt><dd>{p.change.owner}</dd></div><div><dt>任务对象 / 交付物</dt><dd>{p.change.object_text||p.change.title}</dd></div><div className="wide"><dt>任务内容</dt><dd>{p.change.detail}</dd></div><div><dt>DDL / 截止时间</dt><dd>{p.change.deadline_text||'未明确具体截止时间'}</dd></div><div><dt>原话时间要求</dt><dd>{p.change.due_text||'本段未明确'}</dd></div></dl>
   <div className="work-meta"><span>建议状态：{labels[p.change.state]}</span><span>原话依据：{p.evidence.length} 条</span></div>
   <div>{refs(p.evidence)}</div>
   {editing!==p.id?<button className="work-primary" onClick={()=>{setEditing(p.id);setNote('');setDue('');setState(p.change.state);}}>{p.change.target_guid?'确认本次进展':'确认并保存任务'}</button>:<form onSubmit={e=>{e.preventDefault();void confirm(p);}}>
    <label>确认说明<textarea aria-label="任务确认说明" value={note} onChange={e=>setNote(e.target.value)} placeholder="可补充承接、范围或进展说明；会保留为用户确认"/></label>
    <label>补充时间<input aria-label="补充任务时间" value={due} onChange={e=>setDue(e.target.value)} placeholder="留空保留原记录，不猜测具体日期"/></label>
    <label>确认状态<select aria-label="确认任务状态" value={state} onChange={e=>setState(e.target.value)}><option value="open">待开展</option><option value="progress">进行中 · 已汇报</option><option value="done">已完成</option></select></label>
    <button className="work-primary" disabled={busy}>{busy?'正在保存…':'保存确认'}</button><small>操作者确认会单独留痕，任务写入本地模拟器。</small>
   </form>}
  </article>)}
  <div className="work-tasks">{visibleTasks.map(t=><article key={t.guid} data-task={t.guid} data-owner={t.owner} data-state={t.state}>
   <div className="work-owner"><b>{t.owner}</b><span className={`work-state ${t.state}`}>{labels[t.state]}</span></div>
   <h3>{t.title}</h3>{!props.compact&&<div className="work-entry-label">创建入口：{t.created_origin==='automatic'?'会议自动识别':'文字发起整理'} → 操作者确认</div>}<p className="work-due">DDL：{t.deadline_text||'未明确具体截止时间'} · 时间要求：{t.due_text||'未明确'}</p>{!props.compact&&<p className="work-due">任务对象：{t.object_text||t.title}</p>}<p>{t.detail}</p>
   <small>{t.created_scope.meeting_id===t.scope.meeting_id?'本场确认保存':'关联上场原任务 · 未重复新建'} · {t.guid}</small>
   {!props.compact&&<><div>{refs(t.evidence)}<button className="work-ref" onClick={()=>setSelected(selected===t.guid?'':t.guid)}>查看跟进记录</button></div>
   {selected===t.guid&&<ol className="work-history">{data.history.filter(h=>h.guid===t.guid).map(h=><li key={h.revision}><b>{h.scope.meeting_id} · {labels[h.state]}</b><p>{h.detail}</p>{h.note&&<p className="work-note">用户确认：{h.note}</p>}<div>{refs(h.evidence)}</div></li>)}</ol>}</>}
  </article>)}</div>
  {!data.tasks.length&&!data.proposals.length&&<p className="work-empty">会议中的明确分工会随自动总结生成待确认任务；也可在项目助手中用文字按需整理。核对信息并确认后，任务会在这里持续跟进。</p>}
  {evidence&&<section className="work-evidence"><button onClick={()=>setEvidence(null)} aria-label="关闭行动项证据">×</button><small>{stamp(evidence)}</small><h3>这次记录的原话依据</h3><blockquote>{evidence.quote}</blockquote><p>会议继续播放 · 用户补充和模型提取分开保存</p></section>}
 </section>
}
