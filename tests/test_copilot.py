"""API boundaries and delivered artifacts; no paid model calls."""
import io
import json
import tempfile
import unittest
import uuid
import zipfile
import threading
import time
from unittest.mock import patch
from pathlib import Path
from fastapi.testclient import TestClient
from meeting_copilot.api import create_app
from meeting_copilot.search import public_url

ROOT=Path(__file__).resolve().parents[1]


class ModelFixture:
    model='deterministic-test-fixture'
    invalid=False
    calls=0

    def call(self,messages,log_path,tools=None,tool_choice=None):
        self.calls+=1
        if tools:
            return {'role':'assistant','content':'','tool_calls':[{'id':'call-test','type':'function',
                'function':{'name':'search_evidence','arguments':'{"query":"battery power"}'}}]}
        self.last_messages=messages
        ctx=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'));ref=ctx['evidence'][0]['id']
        if self.invalid:ref='future-or-fabricated-reference'
        data={'title':'可下载材料','summary':'测试内容','sections':[{'title':'原话','text':'<script>alert(1)</script>',
              'kind':'fact','evidence_ids':[ref]}], 'columns':['维度','值'],
              'rows':[{'cells':['成本','=1+1'],'evidence_ids':[ref]}], 'questions':['待确认'], 'impact':None}
        return {'role':'assistant','content':json.dumps(data)}


class CopilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.model=ModelFixture()
        self.app=create_app(Path(self.tmp.name),ROOT/'demo/public/scenario-cross.json',self.model)
        self.client=TestClient(self.app)
        self.client.__enter__()
        self.sid=self.session(120000)

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.app.state.runner.pool.shutdown(wait=True)
        self.tmp.cleanup()

    def session(self,cursor,meeting=0,archives=None):
        r=self.client.post('/api/copilot/sessions',json={'project_id':'remote','meeting':meeting,'cursor_ms':cursor,'archives':archives or []})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()['id']

    def run_job(self,kind='qa',sid=None,rid=None,artifact=None,template='design',extract_work=False):
        rid=rid or str(uuid.uuid4());sid=sid or self.sid
        body={'threadId':'test','runId':rid,'state':{},'tools':[],'context':[],
              'messages':[{'id':'u','role':'user','content':'比较供电方案'}],
              'forwardedProps':{'copilot':{'session_id':sid,'kind':kind,'artifact_id':artifact,'template':template,'extract_work':extract_work}}}
        response=self.client.post('/api/copilot/runs',json=body)
        self.assertEqual(response.status_code,200,response.text)
        events=[json.loads(l[5:]) for l in response.text.splitlines() if l.startswith('data:')]
        job=self.client.get('/api/copilot/jobs/'+rid,params={'session_id':sid}).json()
        return job,events

    def test_real_entry_emits_protocol_and_limits_evidence(self):
        job,events=self.run_job()
        self.assertEqual(job['status'],'completed',job.get('error'))
        self.assertEqual(events[0]['type'],'RUN_STARTED')
        self.assertEqual(events[-1]['type'],'RUN_FINISHED')
        self.assertIn('TOOL_CALL_RESULT',[e['type'] for e in events])
        self.assertTrue(all(e['meeting_id']=='ES2002b' and e['end_ms']<=120000 for e in job['result']['evidence']))

    def test_project_and_archive_boundaries(self):
        for body in [{'project_id':'unbound','meeting':0,'cursor_ms':120000},
                     {'project_id':'remote','meeting':0,'cursor_ms':390001},
                     {'project_id':'remote','meeting':0,'cursor_ms':120000,'archives':[{'meeting':0,'cursor_ms':389999}]},
                     {'project_id':'remote','meeting':0,'cursor_ms':120000,'archives':[{'meeting':1,'cursor_ms':782000}]}]:
            self.assertEqual(self.client.post('/api/copilot/sessions',json=body).status_code,422)

    def test_rewind_hides_future_job_and_download(self):
        job,_=self.run_job('comparison');early=self.session(1000)
        self.assertEqual(self.client.get('/api/copilot/jobs/'+job['id'],params={'session_id':early}).status_code,403)
        self.assertEqual(self.client.get(f"/api/copilot/artifacts/{job['id']}/主文档.md",params={'session_id':early}).status_code,403)
        self.assertEqual(self.client.get('/api/copilot/jobs',params={'session_id':early}).json(),[])

    def test_duplicate_request_does_not_call_model_again(self):
        job,_=self.run_job('comparison');calls=self.model.calls
        again,_=self.run_job('comparison',rid=job['id'])
        self.assertEqual(self.model.calls,calls)
        self.assertEqual(job['artifact']['sha256'],again['artifact']['sha256'])

    def test_catchup_uses_window_and_reports_coverage(self):
        sid=self.session(350000);job,_=self.run_job('catchup',sid=sid)
        self.assertEqual(job['status'],'completed')
        self.assertTrue(all(230000<=e['start_ms']<=e['end_ms']<=350000 for e in job['result']['evidence']))
        self.assertEqual(job['result']['coverage']['requested_start_ms'],230000)

    def test_rolling_summary_is_scoped_and_has_no_material(self):
        sid=self.session(350000)
        job,events=self.run_job('summary',sid=sid)
        self.assertEqual(job['status'],'completed',job.get('error'))
        self.assertEqual(events[-1]['type'],'RUN_FINISHED')
        self.assertTrue(all(230000<=e['start_ms']<=e['end_ms']<=350000 for e in job['result']['evidence']))
        self.assertIsNone(job.get('artifact'))
        early=self.session(240000)
        self.assertEqual(self.client.get('/api/copilot/jobs/'+job['id'],params={'session_id':early}).status_code,403)

    def test_charging_reason_query_keeps_cost_context(self):
        from meeting_copilot.contracts import SessionInput
        scope=self.app.state.memory.scope(SessionInput(project_id='remote',meeting=1,cursor_ms=432000,archives=[{'meeting':0,'cursor_ms':389999}]))
        ctx=self.app.state.memory.retrieve(scope,'charging dock base rejected reason remote control meeting decision not adopted')
        text=' '.join(e['quote'].lower() for e in ctx['evidence'])
        self.assertIn('complexity',text)
        self.assertIn('cost',text)
        self.assertIn('cradle',text)
        self.assertTrue(all(e['end_ms']<=432000 for e in ctx['evidence']))

    def test_unknown_citation_fails_without_creating_artifact(self):
        self.model.invalid=True
        job,events=self.run_job('comparison')
        self.assertEqual(job['status'],'failed')
        self.assertIn('证据集之外',job['error'])
        self.assertEqual(events[-1]['type'],'RUN_ERROR')
        self.assertFalse((Path(self.tmp.name)/'artifacts'/job['id']).exists())

    def test_material_revision_preserves_original(self):
        first,_=self.run_job('comparison')
        original=(Path(self.tmp.name)/'artifacts'/first['id']/'主文档.md').read_bytes()
        second,_=self.run_job('revise',artifact=first['id'])
        self.assertEqual(self.model.last_messages[-1]['role'],'user')
        self.assertIn(second['prompt'],self.model.last_messages[-1]['content'])
        self.assertIn('rows',self.model.last_messages[-1]['content'])
        self.assertEqual(second['artifact']['version'],2)
        self.assertEqual(second['artifact']['parent_id'],first['id'])
        self.assertEqual((Path(self.tmp.name)/'artifacts'/first['id']/'主文档.md').read_bytes(),original)

    def test_export_bundle_and_template_share_snapshot(self):
        child,_=self.run_job('comparison')
        first,_=self.run_job('handover');calls=self.model.calls
        second,_=self.run_job('handover',artifact=first['id'],template='sync')
        self.assertEqual(self.model.calls,calls)
        self.assertEqual(first['result']['business'],second['result']['business'])
        self.assertEqual(first['result']['answer'],second['result']['answer'])
        r=self.client.get(f"/api/copilot/artifacts/{second['id']}/交付包.zip",params={'session_id':self.sid})
        self.assertEqual(r.status_code,200)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            z.extractall(Path(self.tmp.name)/'independent-open')
            self.assertIn('主文档.md',z.namelist())
            self.assertIn(f"材料/{child['id']}/主文档.md",z.namelist())
            self.assertFalse(any(n.endswith(('.sqlite','.env')) or 'logs/' in n for n in z.namelist()))
            self.assertIn('&lt;script&gt;',z.read('主文档.html').decode())
            self.assertIn("'=1+1",z.read('比较表.csv').decode('utf-8-sig'))

    def test_events_resume_and_job_survives_new_app_instance(self):
        job,_=self.run_job()
        events=self.app.state.storage.events(job['id'])
        after=events[-3][0]
        response=self.client.get(f"/api/copilot/jobs/{job['id']}/events",params={'session_id':self.sid,'after_seq':after})
        self.assertNotIn('RUN_STARTED',response.text)
        self.assertIn('RUN_FINISHED',response.text)
        other=create_app(Path(self.tmp.name),ROOT/'demo/public/scenario-cross.json',self.model)
        with TestClient(other) as c:
            restored=c.get('/api/copilot/jobs/'+job['id'],params={'session_id':self.sid}).json()
            self.assertEqual(restored['result'],job['result'])
        other.state.runner.pool.shutdown(wait=True)

    def test_accept_proposal_creates_one_real_simulator_task(self):
        scope=self.app.state.memory.scope(__import__('meeting_copilot.contracts',fromlist=['SessionInput']).SessionInput(
            project_id='remote',meeting=0,cursor_ms=120000))
        proposal={'id':'proposal-test','scope':scope,'state':'proposed','job_id':'fixture',
                  'impact':{'action':'核对供电体积','evidence_ids':['fixture-source']}}
        with self.app.state.storage.connect() as db:
            db.execute('INSERT INTO proposals VALUES (?,?,?)',('proposal-test','remote',json.dumps(proposal)))
        first=self.client.post('/api/copilot/proposals/proposal-test/accept',params={'session_id':self.sid}).json()
        second=self.client.post('/api/copilot/proposals/proposal-test/accept',params={'session_id':self.sid}).json()
        self.assertEqual(first['task']['guid'],second['task']['guid'])
        self.assertEqual(first['task']['assignee'],'evaluator')
        self.assertEqual(first['task']['status'],'open')

    def test_cancel_inflight_does_not_publish_material(self):
        entered=threading.Event();release=threading.Event()
        original=self.model.call
        def delayed(*args,**kwargs):
            entered.set();release.wait(10);return original(*args,**kwargs)
        self.model.call=delayed
        results=[]
        thread=threading.Thread(target=lambda:results.append(self.run_job('comparison')))
        thread.start();self.assertTrue(entered.wait(10))
        rows=self.client.get('/api/copilot/jobs',params={'session_id':self.sid}).json()
        jid=rows[0]['id']
        cancelled=self.client.post(f'/api/copilot/jobs/{jid}/cancel',params={'session_id':self.sid})
        self.assertEqual(cancelled.json()['status'],'cancel_requested')
        release.set();thread.join(15)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0][0]['status'],'cancelled')
        self.assertFalse((Path(self.tmp.name)/'artifacts'/jid).exists())

    def test_public_reader_rejects_private_and_non_http_urls(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',80))]):
            with self.assertRaises(ValueError):public_url('http://localhost:8766/api/copilot/jobs')
        with self.assertRaises(ValueError):public_url('file:///D:/secret')

    def test_restart_resumes_checkpoint_without_repeating_retrieval(self):
        original=self.model.call
        def interrupted(messages,log_path,**kwargs):
            if not kwargs.get('tools'):raise SystemExit('simulated process interruption')
            return original(messages,log_path,**kwargs)
        self.model.call=interrupted
        with self.app.state.storage.connect() as db:
            scope=json.loads(db.execute('SELECT body FROM sessions WHERE id=?',(self.sid,)).fetchone()['body'])
        jid=str(uuid.uuid4())
        self.app.state.storage.save_job({'id':jid,'thread_id':'restart','scope':scope,'kind':'comparison','status':'queued',
                                        'prompt':'比较供电','window_ms':120000,'template':'design','artifact_id':None})
        with self.assertRaises(SystemExit):self.app.state.runner.execute(jid)
        self.assertEqual(self.app.state.storage.job(jid)['status'],'running')
        resumed_model=ModelFixture()
        other=create_app(Path(self.tmp.name),ROOT/'demo/public/scenario-cross.json',resumed_model)
        with TestClient(other):
            deadline=time.monotonic()+10
            while other.state.storage.job(jid)['status']=='running' and time.monotonic()<deadline:time.sleep(.05)
            restored=other.state.storage.job(jid)
            self.assertEqual(restored['status'],'completed',restored)
            self.assertEqual(resumed_model.calls,1,'only the answer node should call the model after restart')
            self.assertTrue((Path(self.tmp.name)/'artifacts'/jid/'主文档.md').exists())
        other.state.runner.pool.shutdown(wait=True)


if __name__=='__main__':unittest.main()
