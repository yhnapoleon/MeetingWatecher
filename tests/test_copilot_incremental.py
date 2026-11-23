import json
import uuid
import unittest
from pathlib import Path
import test_copilot as base


class IncrementalModel:
    model = 'incremental-contract-fixture'
    mode = 'update'
    work = False
    progress = False
    relate = False
    def call(self, messages, log_path, tools=None, tool_choice=None):
        assert tools is None, 'Chronological subscription does not need keyword retrieval'
        ctx = json.loads(messages[-1]['content'])
        ref = ctx['new_evidence_ids'][-1]
        cards = ctx['previous_summary']['cards']
        cid = cards[0]['id'] if cards else None
        if self.mode == 'unknown_id': cid = 'not-a-real-topic'
        if self.mode == 'old_ref': ref = ctx['evidence'][0]['id']
        changes = [] if self.mode == 'no_change' else [{'id':cid,'title':'供电方案','text':f'已收到 {len(ctx["evidence"])} 段发言', 'kind':'fact','evidence_ids':[ref]}]
        if self.relate and changes:
            changes[0].update(category='proposal',relation='questioned',
                              prior_topic_id='missing-prior' if self.mode=='bad_prior' else ctx['previous_meeting_cards'][0]['prior_topic_id'])
        work = []
        if self.work:
            pending=ctx['meeting_work']['proposals']
            work=[{'owner':'David','title':'组件概念','object_text':'组件方案','detail':f'逐步补充第 {len(ctx["evidence"])} 段',
                   'existing_proposal_id':pending[0]['id'] if pending else None,'due_text':'下次会议前' if pending else None,
                   'evidence_ids':[ctx['new_evidence_ids'][-1]]}]
        if self.progress:
            task=ctx['meeting_work']['tasks'][0]
            work=[{'owner':task['owner'],'title':task['title'],'target_guid':task['guid'],
                   'existing_proposal_id':None,'state':'progress','detail':f'新增汇报 {ref}',
                   'evidence_ids':[ref]}]
        return {'content':json.dumps({'title':'增量','summary':'','summary_changes':changes,'work_changes':work})}


class IncrementalTests(unittest.TestCase):
    setUp = base.CopilotTests.setUp
    tearDown = base.CopilotTests.tearDown
    session = base.CopilotTests.session

    def incremental(self, sid, rid=None):
        rid = rid or str(uuid.uuid4())
        body={'threadId':'live-test','runId':rid,'state':{},'tools':[],'context':[],
              'messages':[{'id':'u','role':'user','content':'处理新增发言'}],
              'forwardedProps':{'copilot':{'session_id':sid,'kind':'summary','incremental':True,'extract_work':True}}}
        r=self.client.post('/api/copilot/runs',json=body)
        self.assertEqual(r.status_code,200,r.text)
        return self.client.get(f'/api/copilot/jobs/{rid}',params={'session_id':sid}).json()

    def use_model(self):
        m=IncrementalModel();self.app.state.runner.model=m
        return m

    def test_invalid_json_is_repaired_once_then_passes_normal_evidence_checks(self):
        class BrokenJSONModel(IncrementalModel):
            repaired_ref = None
            attempts = 0
            def call(self, messages, log_path, tools=None, tool_choice=None):
                if log_path.name == '02-answer-format-repair.json':
                    self.attempts += 1
                    fixed = messages[-1]['content'].replace(',kind"', ',"kind"')
                    if self.repaired_ref:
                        value = json.loads(fixed)
                        value['summary_changes'][0]['evidence_ids'] = [self.repaired_ref]
                        fixed = json.dumps(value)
                    return {'content': fixed}
                response = super().call(messages, log_path, tools, tool_choice)
                response['content'] = response['content'].replace(', "kind"', ',kind"')
                return response
        model = BrokenJSONModel(); self.app.state.runner.model = model
        result = self.incremental(self.sid)
        self.assertEqual(result['status'], 'completed', result.get('error'))
        self.assertEqual(model.attempts, 1)
        model.repaired_ref = 'invented-evidence'
        result = self.incremental(self.sid)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(model.attempts, 2)

    def test_real_entry_advances_topic_without_future_or_replacing_identity(self):
        self.use_model()
        late=self.session(120000)
        first=self.incremental(late)
        self.assertEqual(first['status'],'completed',first.get('error'))
        self.assertEqual(first['scope']['cursor_ms'],15160)
        self.assertTrue(all(e['end_ms']<=15160 for e in first['result']['evidence']))
        card=first['result']['live_summary']['cards'][0]
        self.assertEqual(card['revision'],1)
        self.assertNotIn('cost',' '.join(e['quote'] for e in first['result']['evidence']))
        duplicate=self.incremental(late,rid=first['id'])
        self.assertEqual(first['result'],duplicate['result'])
        second=self.incremental(late)
        self.assertEqual(second['scope']['cursor_ms'],35020)
        c2=second['result']['live_summary']['cards'][0]
        self.assertEqual(c2['id'],card['id'])
        self.assertEqual(c2['revision'],2)
        self.assertEqual(c2['history'][0]['text'],card['text'])
        early=self.session(16000)
        jobs=self.client.get('/api/copilot/jobs',params={'session_id':early}).json()
        self.assertEqual([j['id'] for j in jobs],[first['id']])
        self.assertFalse(self.client.get('/api/copilot/summary-progress',params={'session_id':early}).json()['ready'])
        # Second meeting starts its own board, even with the first meeting archived.
        second_meeting=self.session(425000,1,[{'meeting':0,'cursor_ms':389999}])
        third=self.incremental(second_meeting)
        self.assertEqual(third['result']['live_summary']['cards'][0]['revision'],1)
        self.assertNotEqual(third['result']['live_summary']['cards'][0]['id'],card['id'])

    def test_noninformative_speech_advances_cursor_without_new_card(self):
        m=self.use_model();first=self.incremental(self.sid)
        m.mode='no_change';second=self.incremental(self.sid)
        self.assertEqual(first['result']['live_summary']['cards'],second['result']['live_summary']['cards'])
        self.assertEqual(second['result']['live_summary']['changed_ids'],[])
        self.assertGreater(second['scope']['cursor_ms'],first['scope']['cursor_ms'])

    def test_patch_requires_new_evidence_and_known_identity(self):
        m=self.use_model();self.incremental(self.sid)
        m.mode='old_ref';bad=self.incremental(self.sid)
        self.assertEqual(bad['status'],'completed')
        self.assertEqual(bad['result']['live_summary']['cards'][0]['revision'],1)
        self.assertEqual(bad['result']['live_summary']['ignored_changes'][0]['reason'],'no_new_evidence')
        m.mode='unknown_id';bad=self.incremental(self.sid)
        self.assertEqual(bad['status'],'failed')
        self.assertIn('不存在的卡片',bad['error'])

    def test_rephrased_old_topic_does_not_block_new_action_fields(self):
        m=self.use_model();m.work=True
        first=self.incremental(self.sid)
        m.mode='old_ref';second=self.incremental(self.sid)
        self.assertEqual(second['status'],'completed',second.get('error'))
        self.assertEqual(first['result']['live_summary']['cards'],second['result']['live_summary']['cards'])
        self.assertEqual(first['result']['work_proposal_ids'],second['result']['work_proposal_ids'])
        proposals=self.client.get('/api/copilot/work',params={'session_id':self.sid}).json()['proposals']
        self.assertEqual(proposals[0]['change']['due_text'],'下次会议前')

    def test_candidate_enrichment_keeps_id_and_earlier_scope(self):
        m=self.use_model();m.work=True
        first=self.incremental(self.sid);second=self.incremental(self.sid)
        pid=first['result']['work_proposal_ids'][0]
        self.assertEqual(second['result']['work_proposal_ids'],[pid])
        def view(sid):return self.client.get('/api/copilot/work',params={'session_id':sid}).json()
        early=self.session(first['scope']['cursor_ms'])
        self.assertIsNone(view(early)['proposals'][0]['change']['due_text'])
        self.assertEqual(view(self.sid)['proposals'][0]['change']['due_text'],'下次会议前')
        self.assertEqual(len(view(self.sid)['proposals']),1)
        confirmed=self.client.post(f'/api/copilot/work/{pid}/confirm',params={'session_id':self.sid},json={})
        self.assertEqual(confirmed.status_code,200,confirmed.text)
        self.assertEqual(confirmed.json()['due_text'],'下次会议前')
        self.assertEqual(len(view(self.sid)['tasks']),1)
        self.assertEqual(view(self.sid)['proposals'],[])

    def test_progress_without_candidate_id_enriches_same_target(self):
        m=self.use_model();m.work=True
        first=self.incremental(self.sid);pid=first['result']['work_proposal_ids'][0]
        saved=self.client.post(f'/api/copilot/work/{pid}/confirm',params={'session_id':self.sid},json={}).json()
        m.work=False;m.progress=True
        later=self.session(480000,1,[{'meeting':0,'cursor_ms':389999}])
        from meeting_copilot.live_summary import context
        from meeting_copilot.contracts import SessionInput
        scope=self.app.state.memory.scope(SessionInput(project_id='remote',meeting=1,cursor_ms=480000,archives=[{'meeting':0,'cursor_ms':389999}]))
        ctx=context(self.app.state.storage,self.app.state.memory,self.app.state.runner.work,scope)
        self.assertTrue({e['id'] for e in saved['evidence']} <= {e['id'] for e in ctx['evidence']})
        self.assertTrue(all(e['meeting_id']=='ES2002c' for e in ctx['new_transcript']))
        a=self.incremental(later);b=self.incremental(later)
        self.assertEqual(a['status'],'completed',a.get('error'))
        self.assertEqual(b['status'],'completed',b.get('error'))
        self.assertEqual(a['result']['work_proposal_ids'],b['result']['work_proposal_ids'])
        def view(sid):return self.client.get('/api/copilot/work',params={'session_id':sid}).json()
        current=view(later);self.assertEqual(len(current['proposals']),1)
        candidate=current['proposals'][0]
        self.assertEqual(candidate['change']['target_guid'],saved['guid'])
        earlier=self.session(a['scope']['cursor_ms'],1,[{'meeting':0,'cursor_ms':389999}])
        self.assertNotEqual(view(earlier)['proposals'][0]['change']['detail'],candidate['change']['detail'])
        done=self.client.post(f'/api/copilot/work/{candidate["id"]}/confirm',params={'session_id':later},json={})
        self.assertEqual(done.status_code,200,done.text)
        self.assertEqual(done.json()['guid'],saved['guid'])
        self.assertEqual(done.json()['detail'],candidate['change']['detail'])
        self.assertEqual(len(view(later)['tasks']),1)
        self.assertEqual(view(later)['proposals'],[])

    def test_prior_topic_relation_and_proposal_status_are_preserved(self):
        m=self.use_model();first=self.incremental(self.sid)
        later=self.session(480000,1,[{'meeting':0,'cursor_ms':389999}]);m.relate=True
        linked=self.incremental(later)
        self.assertEqual(linked['status'],'completed',linked.get('error'))
        board=linked['result']['live_summary'];card=board['cards'][0]
        self.assertEqual(card['category'],'proposal')
        self.assertEqual(card['relation'],'questioned')
        self.assertEqual(card['prior_topic_id'],first['result']['live_summary']['cards'][0]['id'])
        self.assertEqual(board['previous_meeting_cards'][0]['id'],card['prior_topic_id'])
        m.mode='bad_prior';bad=self.incremental(later)
        self.assertEqual(bad['status'],'failed')
        self.assertIn('可见归档',bad['error'])

    def test_refresh_reuses_saved_board(self):
        self.use_model();first=self.incremental(self.sid)
        from meeting_copilot.api import create_app
        from fastapi.testclient import TestClient
        other=create_app(Path(self.tmp.name),base.ROOT/'demo/public/scenario-cross.json',IncrementalModel())
        with TestClient(other) as client:
            progress=client.get('/api/copilot/summary-progress',params={'session_id':self.sid}).json()
            self.assertEqual(progress['processed_until_ms'],first['scope']['cursor_ms'])
            self.assertEqual(progress['cursor_ms'],35020)
        other.state.runner.pool.shutdown(wait=True)

    def test_last_short_passage_is_flushed_at_meeting_end(self):
        from unittest.mock import patch
        from meeting_copilot.live_summary import plan
        sid=self.session(782000,1)
        memory=self.app.state.memory
        scope=memory.scope(__import__('meeting_copilot.contracts',fromlist=['SessionInput']).SessionInput(
            project_id='remote',meeting=1,cursor_ms=782000))
        windows=[e for e in memory.evidence if e['meeting_id']=='ES2002c']
        after=windows[-2]['end_ms']
        self.assertLess(782000-after,12000)
        with patch('meeting_copilot.live_summary.latest',return_value={'scope':{'cursor_ms':after}}):
            progress=plan(self.app.state.storage,memory,scope)
        self.assertTrue(progress['ready'])
        self.assertEqual(progress['cursor_ms'],windows[-1]['end_ms'])

    def test_pending_increment_does_not_queue_a_second_copy(self):
        from unittest.mock import patch
        self.use_model()
        with patch.object(self.app.state.runner.pool,'submit'):
            # submit through Runner so the SSE reader need not wait for this intentionally queued job.
            scope=self.app.state.memory.scope(__import__('meeting_copilot.contracts',fromlist=['SessionInput']).SessionInput(
                project_id='remote',meeting=0,cursor_ms=120000))
            job={'id':'pending-increment-test','thread_id':'test','scope':scope,'status':'queued','kind':'summary',
                 'prompt':'处理新增发言','incremental':True,'extract_work':True}
            self.app.state.runner.submit(job)
            self.assertFalse(self.app.state.runner.summary_progress(scope)['ready'])
            with self.assertRaisesRegex(ValueError,'上一轮尚未完成'):
                self.app.state.runner.submit({**job,'id':'another-increment-test','scope':scope})
        # No worker was launched; this record is intentionally only a queue-boundary test.
        job['status']='cancelled';self.app.state.storage.save_job(job)

    def test_lightweight_summary_query_preserves_other_job_history(self):
        self.use_model();first=self.incremental(self.sid);second=self.incremental(self.sid)
        latest=self.client.get('/api/copilot/jobs',params={'session_id':self.sid,'kind':'summary','latest':True}).json()
        self.assertEqual([j['id'] for j in latest],[second['id']])
        other=self.client.get('/api/copilot/jobs',params={'session_id':self.sid,'include_summaries':False}).json()
        self.assertEqual(other,[])
        self.assertEqual(len(self.client.get('/api/copilot/jobs',params={'session_id':self.sid}).json()),2)

if __name__=='__main__': unittest.main()
