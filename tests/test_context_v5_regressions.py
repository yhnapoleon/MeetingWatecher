"""Observable regressions from the 2026-11-16 handover."""
import copy
import tempfile
import unittest
from pathlib import Path

from meeting_eval.service import Service
from meeting_eval.store import Store, Simulator


class TrackingV5Tests(unittest.TestCase):
    def setUp(self):
        self.meeting = dict(case_id='M', segments=[
            dict(id='s1', text='今天分别安排春季展会和秋季展会的准备工作。'),
            dict(id='s2', text='用户经常来问设备怎么恢复出厂设置。'),
            dict(id='s3', text='春季先取消，秋季继续准备。')])

    def delta(self):
        return dict(case_id='M', new_entities=[dict(entity_id='N1', label='春季展会', mentions=['Q1'])],
            entity_mentions=[], links=[], new_threads=[dict(thread_id='T1', entity_ids=['N1'])],
            thread_entities=[], updates_by_segment={
                's1':[dict(thread_id='T1', kind='work', description='准备春季展会', evidence=['Q1'])],
                's2':[], 's3':[dict(thread_id='T1', kind='withdrawn', description='取消春季准备', evidence=['Q3'])]})

    def expand(self, raw, previous=None, ids=None):
        from meeting_eval.context_tracking_v5 import expand_delta
        return expand_delta(raw, dict(meeting=self.meeting, previous=previous,
            new_segment_ids=ids if ids is not None else ['s1','s2','s3']))

    def test_program_supplies_verbatim_evidence_and_source_order(self):
        raw=self.delta()
        raw['updates_by_segment']={k:raw['updates_by_segment'][k] for k in ['s3','s1','s2']}
        ledger=self.expand(raw)
        self.assertEqual([u['after_segment'] for u in ledger['threads'][0]['updates']], ['s1','s3'])
        self.assertEqual(ledger['entities'][0]['mentions'][0]['quote'], self.meeting['segments'][0]['text'])
        self.assertEqual(ledger['threads'][0]['updates'][-1]['kind'], 'withdrawn')

    def test_delta_keeps_previous_evidence_and_updates_immutable(self):
        raw=self.delta(); raw['updates_by_segment']['s3']=[]
        previous=self.expand(raw); before=copy.deepcopy(previous)
        patch=dict(case_id='M', new_entities=[], entity_mentions=[dict(entity_id='N1', mentions=['Q3'])],
            links=[], new_threads=[], thread_entities=[],
            updates_by_segment={'s3':[dict(thread_id='T1',kind='withdrawn',description='取消春季准备',evidence=['Q3'])]})
        out=self.expand(patch, previous, ['s3'])
        self.assertEqual(previous,before)
        self.assertEqual(out['threads'][0]['updates'][:1],previous['threads'][0]['updates'])
        self.assertEqual(out['entities'][0]['mentions'][0],previous['entities'][0]['mentions'][0])
        self.assertEqual(out['threads'][0]['updates'][-1]['after_segment'],'s3')

    def test_rejects_unknown_evidence_future_update_and_history_rewrite(self):
        for change in [
            lambda x:x['new_entities'][0].update(mentions=['Q999']),
            lambda x:x['updates_by_segment']['s1'][0].update(evidence=['Q3']),
            lambda x:x['updates_by_segment'].update(s999=[]),
            lambda x:x.update(entities=[]),
            lambda x:x['new_entities'][0].update(quote='改写的引文')]:
            with self.subTest(change=change):
                raw=self.delta();change(raw)
                with self.assertRaises(ValueError):self.expand(raw)
        previous=self.expand(self.delta())
        raw=self.delta();raw['updates_by_segment']={'s3':[]}
        with self.assertRaises(ValueError):self.expand(raw,previous,['s3'])

    def test_same_segment_distinct_work_remains_distinct(self):
        raw=self.delta()
        raw['new_entities'].append(dict(entity_id='N2',label='秋季展会',mentions=['Q1']))
        raw['new_threads'].append(dict(thread_id='T2',entity_ids=['N2']))
        raw['updates_by_segment']['s1'].append(dict(thread_id='T2',kind='work',description='准备秋季展会',evidence=['Q1']))
        out=self.expand(raw)
        self.assertEqual(len(out['threads']),2)
        self.assertEqual(out['threads'][1]['updates'][-1]['kind'],'work')

    def test_generation_contract_binds_evidence_to_current_catalog(self):
        from meeting_eval.context_tracking_v5 import delta_schema
        from meeting_eval.context_protocol_v4 import closed_validate
        schema=delta_schema(dict(meeting=self.meeting,previous=None,new_segment_ids=['s1','s2','s3']))
        raw=self.delta();raw['new_entities'][0]['mentions']=['Q202']
        with self.assertRaises(ValueError):closed_validate(raw,schema)


class RecheckV5Tests(unittest.TestCase):
    def test_background_citations_are_rechecked_even_when_also_used_by_work(self):
        from meeting_eval.context_v5 import ContextV5Pipeline
        from meeting_eval.context_protocol import example
        requests=[]
        class Client:
            model='deepseek-flash'
            endpoint='https://example.invalid'
            def call(self,prompt,p,stage,**kwargs):
                requests.append(copy.deepcopy(p))
                return example(p['output_schema'])
        payload=dict(meeting=dict(case_id='M',segments=[
            dict(id='s1',text='会场开放到周五；若审批通过，我们支付费用。'),
            dict(id='s2',text='场地可容纳二十人。')]),
            records=[dict(record_id='R1',kind='context_only',evidence=[dict(segment_id='s1',quote='会场开放到周五；若审批通过，我们支付费用。')]),
                     dict(record_id='R2',kind='work',evidence=[dict(segment_id='s1',quote='会场开放到周五')])],
            events=[],ledger=dict(entities=[],threads=[]))
        before=copy.deepcopy(payload)
        with tempfile.TemporaryDirectory() as tmp:
            out=ContextV5Pipeline(Client(),Path(tmp),{})._stage('check_work',payload,lambda x:x,Path(tmp),False)
        coverage=requests[0]['coverage_review']
        self.assertEqual(coverage['nonwork_record_evidence'],[dict(record_id='R1',kind='context_only',evidence=['s1'])])
        self.assertEqual(coverage['unrepresented_evidence'],['s2'])
        self.assertEqual(out['coverage_findings'],[])
        self.assertEqual(payload,before)

    def test_initial_check_exposes_unrepresented_source_without_promoting_it(self):
        from meeting_eval.context_v5 import ContextV5Pipeline
        from meeting_eval.context_protocol import example
        requests=[]
        class Client:
            model='deepseek-flash'
            endpoint='https://example.invalid'
            def call(self,prompt,p,stage,**kwargs):
                requests.append(copy.deepcopy(p))
                return example(p['output_schema'])
        payload=dict(meeting=dict(case_id='M',segments=[dict(id='s1',text='已记录的工作'),
            dict(id='s2',text='好，我来'),dict(id='s3',text='另一个角色的省略分工')]),
            records=[dict(record_id='R1',evidence=[dict(segment_id='s1',quote='已记录的工作')])],
            events=[dict(event_id='E1',record_id='R1',**{f:dict(evidence=[dict(segment_id='s2',quote='好，我来')] if f=='commitment' else [])
                for f in ('work','owner','commitment','time','state','relation')})],
            ledger=dict(entities=[dict(entity_id='N2',label='另一个角色',mentions=[dict(segment_id='s3',quote='另一个角色的省略分工')])],
                threads=[dict(thread_id='T1',entity_ids=[])]))
        with tempfile.TemporaryDirectory() as tmp:
            out=ContextV5Pipeline(Client(),Path(tmp),{})._stage('check_work',payload,lambda x:x,Path(tmp),False)
        self.assertEqual(requests[0]['coverage_review']['unrepresented_evidence'],['s3'])
        self.assertEqual(requests[0]['coverage_review']['unthreaded_entities'][0]['entity_id'],'N2')
        self.assertEqual([r['record_id'] for r in out['record_checks']],['R1'])
        self.assertEqual(out['coverage_findings'],[])

    def test_request_separates_targets_from_read_only_records(self):
        import json
        from meeting_eval.context_v5 import ContextV5Pipeline
        from meeting_eval.context_protocol import example
        from meeting_eval.context_protocol_v5 import expand_checks
        payload=json.loads((Path(__file__).parent/'fixtures/cp02_recheck_payload.json').read_text(encoding='utf8'))
        payload={k:v for k,v in payload.items() if k not in ('scope','output_schema','output_contract')}
        requests=[]
        class Client:
            model='deepseek-flash'
            endpoint='https://example.invalid'
            def call(self,prompt,p,stage,**kwargs):
                requests.append(copy.deepcopy(p))
                raw=example(p['output_schema'])
                return raw
        with tempfile.TemporaryDirectory() as tmp:
            out=ContextV5Pipeline(Client(),Path(tmp),{})._stage('check_repair',payload,lambda x:x,Path(tmp),False)
        self.assertEqual([r['record_id'] for r in out['record_checks']],['R2'])
        self.assertNotIn('context_records',requests[0])
        self.assertEqual(requests[0]['check_targets']['record_ids'],['R2'])
        self.assertTrue(requests[0]['read_only_context'])
        self.assertNotIn('record_id',requests[0]['read_only_context'][0])
        # Known read-only identities and unknown identities remain invalid output keys.
        raw=example(requests[0]['output_schema'])
        for identity in ('R1','R999'):
            bad=copy.deepcopy(raw);bad['record_checks'][identity]=copy.deepcopy(raw['record_checks']['R2'])
            with self.assertRaises(ValueError):expand_checks(bad,payload,True)


class InterpretationV5Tests(unittest.TestCase):
    def setUp(self):
        from meeting_eval.context_v5 import ContextV5Pipeline
        from test_context_v3 import V3Client, interpretation
        from test_context_state import ledger_fixture
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pipe=ContextV5Pipeline(V3Client(),Path(self.tmp.name),{})
        self.meeting,_,self.ledger,_=ledger_fixture()
        self.raw=interpretation()

    def test_unrepresented_entity_becomes_checked_object_not_automatic_work(self):
        self.meeting['segments'].append(dict(id='s2',text='另有客户反馈。',speaker='A',person_ref='alice'))
        self.ledger['entities'].append(dict(entity_id='N2',label='客户反馈',mentions=[dict(segment_id='s2',quote='客户反馈')]))
        before=copy.deepcopy(self.raw)
        result=self.pipe.interpret(self.raw,self.ledger,[],self.meeting,{'tasks':[]})
        self.assertEqual(len(result['records']),2)
        obj=result['records'][1]
        self.assertEqual(obj['kind'],'entity_only')
        self.assertEqual(obj['description'],'客户反馈')
        self.assertEqual(obj['missing_fields'],[])
        self.assertIsNone(obj['question'])
        self.assertEqual(len(result['events']),1)
        self.assertEqual(self.raw,before)
        # Existing event evidence already represents the object: no duplicate.
        self.raw['events'][0]['work']['evidence'].append('Q2')
        covered=self.pipe.interpret(self.raw,self.ledger,[],self.meeting,{'tasks':[]})
        self.assertEqual(len(covered['records']),1)

    def test_new_work_window_keeps_window_without_setting_deadline(self):
        from test_context_v3 import check_response
        from meeting_eval.context_v3 import reduce_v3
        self.meeting['segments'][0]['text']+='会后开展。'
        self.raw['events'][0]['time'].update(kind='work_window',text='会后',date=None,change='set',evidence=['Q1'])
        before=copy.deepcopy(self.raw)
        result=self.pipe.interpret(self.raw,self.ledger,[],self.meeting,{'tasks':[]})
        self.assertEqual(result['events'][0]['time']['change'],'keep')
        self.assertEqual(self.raw,before)
        catalog={'Q1':dict(segment_id='s1',quote=self.meeting['segments'][0]['text'])}
        checked=self.pipe.check(check_response(result['records'],result['events']),result,self.meeting,catalog)
        out=reduce_v3(dict(**checked,coverage_findings=[],trace={}),self.meeting,{'tasks':[]})
        self.assertEqual(len(out['items']),1)
        self.assertIsNone(out['items'][0]['due_date'])
        self.assertIsNone(out['items'][0]['due_text'])
        self.assertIn('会后',out['items'][0]['description'])

    def test_existing_work_window_set_is_still_rejected(self):
        e=self.raw['events'][0]
        e['relation'].update(kind='existing',target_guid='H1',evidence=['Q1'])
        e['time'].update(kind='work_window',text='会后',change='set',evidence=['Q1'])
        with self.assertRaisesRegex(ValueError,'Setting a deadline'):
            self.pipe.interpret(self.raw,self.ledger,[],self.meeting,{'tasks':[dict(guid='H1',summary='剪辑视频')]})


class ServiceV5RegressionTests(unittest.TestCase):
    def run_shared_evidence(self, strategy):
        meeting = dict(meeting_id='shared', series='shared',
            started_at='2026-11-16T10:00:00+08:00',
            audience=['host', 'chen'], writers=['host'],
            roster={'host': '主持人', 'chen': '陈可'}, speaker_map={'陈可': 'chen'},
            account_map={'host': 'host', 'chen': 'chen'},
            segments=[dict(id='S1', speaker='陈可',
                text='上周的登录案例我已经发到研发群了。另外我来整理支付案例并发到客服群。')])
        extraction = dict(facts=[], decisions=[], unresolved=[],
            items=[dict(description='整理支付案例并发到客服群。', operation='create',
                owner_kind='corpus_person', owner_ref='chen', owner_label='陈可',
                due_text=None, due_date=None, action_anchor='S1', evidence_ids=['S1'])],
            updates=[dict(target_guid='OLD', description='整理登录案例并发到研发群。',
                owner_ref='chen', status='done', effective_at=None, evidence_ids=['S1'])])

        class FixedExtractor:
            def extract(self, meeting, context):
                return copy.deepcopy(extraction)

        extractor = FixedExtractor()
        extractor.strategy = strategy
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'state.sqlite')
            try:
                Simulator(store).seed(dict(guid='OLD', summary='整理登录案例并发到研发群。',
                    status='open', readers=['host', 'chen'], writers=['host'],
                    assignee='chen', tenant='local', series='shared'), '2026-11-09T10:00:00+08:00')
                svc = Service(store, extractor)
                first = svc.process(meeting, 'host', '2026-11-16T10:02:00+08:00')
                audit = store.db.execute('SELECT count(*) FROM audit').fetchone()[0]
                second = svc.process(meeting, 'host', '2026-11-16T10:03:00+08:00')
                self.assertEqual(first['source_id'], second['source_id'])
                self.assertEqual(audit, store.db.execute('SELECT count(*) FROM audit').fetchone()[0])
                return first, store.tasks(), store.task('OLD')['status']
            finally:
                store.close()

    def test_v5_completes_old_and_creates_new_idempotently(self):
        result, tasks, old = self.run_shared_evidence('context-v5')
        self.assertEqual(result['status'], 'processed')
        self.assertEqual(old, 'done')
        self.assertEqual(len(tasks), 2)
        new = next(t for t in tasks if t['guid'] != 'OLD')
        self.assertEqual(new['summary'], '整理支付案例并发到客服群。')
        self.assertEqual(new['assignee'], 'chen')
        self.assertEqual(result['pending'], [])

    def test_split_keeps_shared_evidence_conflict_protection(self):
        result, tasks, old = self.run_shared_evidence('split-v3')
        self.assertEqual(old, 'open')
        self.assertEqual(len(tasks), 1)
        self.assertEqual([p['reason'] for p in result['pending']], ['create_update_conflict'])


if __name__ == '__main__':
    unittest.main()
