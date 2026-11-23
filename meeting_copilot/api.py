import asyncio
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from ag_ui.core import RunAgentInput
from .contracts import SessionInput, RunOptions, WorkConfirmation
from .storage import Storage, dumps
from .memory import Memory
from .jobs import Runner, is_visible
from .artifacts import TEMPLATES
from meeting_eval.store import Store
from meeting_eval.service import Service


def create_app(root, scenario, model, history_db=None, search=None):
    storage=Storage(root)
    memory=Memory(scenario,root,history_db)
    runner=Runner(storage,memory,model,search)

    @asynccontextmanager
    async def lifespan(app):
        runner.recover()
        yield
        runner.pool.shutdown(wait=False)

    app=FastAPI(title='MeetingWatcher Copilot',lifespan=lifespan)
    app.state.storage=storage
    app.state.runner=runner
    app.state.memory=memory

    def session(sid):
        with storage.connect() as db:
            row=db.execute('SELECT body FROM sessions WHERE id=?',(sid,)).fetchone()
        if not row:
            raise HTTPException(404,'会议会话不存在')
        return json.loads(row['body'])

    def visible_job(jid,sid):
        try: job=storage.job(jid)
        except LookupError: raise HTTPException(404,'任务不存在')
        if not is_visible(job['scope'],session(sid)):
            raise HTTPException(403,'任务不在当前项目/时间范围内')
        return job

    @app.get('/api/copilot/health')
    def health():
        return {'status':'ok','model':model.model,'input':'stt_replay','historical_service':memory.history.exists(),'search':search is not None}

    @app.post('/api/copilot/sessions')
    def create_session(body:SessionInput):
        try: scope=memory.scope(body)
        except ValueError as e: raise HTTPException(422,str(e))
        sid=uuid.uuid4().hex
        with storage.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?,?)',(sid,dumps(scope)))
        return {'id':sid,'scope':scope}

    @app.put('/api/copilot/sessions/{sid}')
    def update_session(sid:str,body:SessionInput):
        old=session(sid)
        try: scope=memory.scope(body)
        except ValueError as e: raise HTTPException(422,str(e))
        if old['project_id']!=scope['project_id'] or old['meeting_id']!=scope['meeting_id']:
            raise HTTPException(409,'切换会议需要新建会话')
        with storage.connect() as db:
            db.execute('UPDATE sessions SET body=? WHERE id=?',(dumps(scope),sid))
        return {'id':sid,'scope':scope}

    @app.get('/api/copilot/templates')
    def templates(): return TEMPLATES

    @app.get('/api/copilot/work')
    def meeting_work(session_id: str):
        return runner.work.view(session(session_id))

    @app.get('/api/copilot/summary-progress')
    def summary_progress(session_id: str):
        return runner.summary_progress(session(session_id))

    @app.post('/api/copilot/work/{pid}/confirm')
    def confirm_work(pid: str, body: WorkConfirmation, session_id: str):
        with runner.lock:
            try:
                return runner.work.confirm(pid, session(session_id), body)
            except LookupError as e:
                raise HTTPException(404, str(e))
            except PermissionError as e:
                raise HTTPException(403, str(e))
            except ValueError as e:
                raise HTTPException(409, str(e))

    @app.get('/api/copilot/jobs')
    def jobs(session_id:str, kind:str|None=None, latest:bool=False, include_summaries:bool=True):
        scope=session(session_id)
        with storage.connect() as db:
            rows=[json.loads(r['body']) for r in db.execute('SELECT body FROM jobs WHERE project=? ORDER BY rowid DESC',(scope['project_id'],))]
        visible = [j for j in rows if is_visible(j['scope'],scope) and (kind is None or j['kind']==kind)
                   and (include_summaries or j['kind']!='summary')]
        if latest:
            visible = sorted((j for j in visible if j['status']=='completed' and j['scope']['meeting_id']==scope['meeting_id']),
                             key=lambda j:j['scope']['cursor_ms'], reverse=True)[:1]
        return visible

    @app.get('/api/copilot/jobs/{jid}')
    def job(jid:str,session_id:str): return visible_job(jid,session_id)

    async def stream(jid,after=0):
        while True:
            rows=storage.events(jid,after)
            for seq,event in rows:
                after=seq
                yield 'id: '+str(seq)+'\ndata: '+dumps(event)+'\n\n'
            state=storage.job(jid)['status']
            if state in ('completed','failed','cancelled'):
                # Flush a terminal event committed just after the status update.
                await asyncio.sleep(.05)
                for seq,event in storage.events(jid,after):
                    yield 'id: '+str(seq)+'\ndata: '+dumps(event)+'\n\n'
                return
            if not rows:
                yield ': heartbeat\n\n'
            await asyncio.sleep(.25)

    @app.post('/api/copilot/runs')
    def run(body:RunAgentInput):
        try:
            opts=RunOptions.model_validate(body.forwarded_props['copilot'])
            scope=session(opts.session_id)
            if opts.research and (search is None or opts.kind not in ('comparison','validation')):
                raise ValueError('公开搜索仅供已配置搜索服务的比较表/验证清单使用')
            if not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}',body.run_id):
                raise ValueError('无效的运行 ID')
            prompt=next((m.content for m in reversed(body.messages) if m.role=='user'), '')
            if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>5000:
                raise ValueError('请输入 1–5000 字的请求')
            if opts.kind=='impact':
                with storage.connect() as db:
                    prior=[json.loads(r['body']) for r in db.execute('SELECT body FROM jobs WHERE project=?',(scope['project_id'],))]
                checks=[j for j in prior if j['kind']=='impact' and j['scope']['meeting_id']==scope['meeting_id'] and j['id']!=body.run_id]
                if len(checks)>=8:
                    raise ValueError('本场已达到 8 次自动分析预算，仍可手动问项目')
                if any(j['status'] not in ('failed','cancelled') and abs(j['scope']['cursor_ms']-scope['cursor_ms'])<25000 for j in checks):
                    raise ValueError('该讨论窗口已分析')
            job={'id':body.run_id,'thread_id':body.thread_id,'scope':scope,'status':'queued','prompt':prompt,
                 'created_at':datetime.now(timezone.utc).isoformat(), **opts.model_dump(exclude={'session_id'})}
            runner.submit(job)
        except (ValueError,KeyError) as e:
            raise HTTPException(422,str(e))
        return StreamingResponse(stream(body.run_id),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})

    @app.get('/api/copilot/jobs/{jid}/events')
    def events(jid:str,session_id:str,after_seq:int=Query(default=0,ge=0)):
        visible_job(jid,session_id)
        return StreamingResponse(stream(jid,after_seq),media_type='text/event-stream')

    @app.post('/api/copilot/jobs/{jid}/cancel')
    def cancel(jid:str,session_id:str):
        with runner.lock:
            j=visible_job(jid,session_id)
            if j['status'] in ('queued','running'):
                j['status']='cancel_requested';storage.save_job(j)
        return j

    @app.get('/api/copilot/artifacts/{aid}/{name}')
    def download(aid:str,name:str,session_id:str):
        j=visible_job(aid,session_id)
        a=j.get('artifact')
        if not a or name not in a['files']:
            raise HTTPException(404,'材料文件不存在')
        return FileResponse(storage.root/'artifacts'/aid/name,filename=name)

    @app.get('/api/copilot/proposals')
    def proposals(session_id:str):
        scope=session(session_id)
        with storage.connect() as db:
            rows=[json.loads(r['body']) for r in db.execute('SELECT body FROM proposals WHERE project=?',(scope['project_id'],))]
        return [r for r in rows if is_visible(r['scope'],scope)]

    @app.post('/api/copilot/proposals/{pid}/{action}')
    def accept(pid:str,action:str,session_id:str):
        scope=session(session_id)
        if action not in ('accept','dismiss'):
            raise HTTPException(422,'未知操作')
        with runner.lock:
            with storage.connect() as db:
                row=db.execute('SELECT body FROM proposals WHERE id=?',(pid,)).fetchone()
            if not row:raise HTTPException(404,'建议不存在')
            proposal=json.loads(row['body'])
            if not is_visible(proposal['scope'],scope):raise HTTPException(403,'建议不可见')
            if proposal['state']!='proposed':return proposal
            if action=='accept':
                # Existing Service + Simulator path, in a separate DB from historical experiments.
                store=Store(storage.root/'actions.sqlite')
                try:
                    service=Service(store)
                    actor=scope['actor'];at=datetime.now(timezone.utc).isoformat()
                    payload={'summary':proposal['impact']['action'],'assignee':actor,'due_date':None,'due_text':None,
                             'readers':[actor],'writers':[actor],'tenant':'local','series':'AMI-ES2002-cross-meeting',
                             'origin':'copilot_user_confirmation','evidence':proposal['impact']['evidence_ids']}
                    store.put_intent({'id':pid,'actor':actor,'source_id':None,'operation':'create','payload':payload,
                                      'policy':'copilot_explicit_user_confirmation','observed_at':at})
                    service.recover(actor=actor,observed_at=at)
                    guid=store.binding(pid)
                    if not guid:raise HTTPException(409,'任务尚未确认写入')
                    proposal.update(state='accepted',task=service.sim.get(guid,actor))
                finally:store.close()
            else:proposal['state']='dismissed'
            with storage.connect() as db:db.execute('UPDATE proposals SET body=? WHERE id=?',(dumps(proposal),pid))
            return proposal

    return app
