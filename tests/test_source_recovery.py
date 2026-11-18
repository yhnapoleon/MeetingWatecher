import json
from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store
from meeting_eval.model_client import ModelResponseError
from meeting_eval.context_protocol import example
from test_context_state import ledger_fixture
from test_context_v3 import interpretation,check_response
from test_minutes_review import assessment

AT='2026-11-17T10:01:00+08:00'


class SourceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)
        self.calls=Counter();self.fail=True
        self.meeting,_,_,_=ledger_fixture();self.meeting['account_map']={'alice':'alice'}
        self.meeting['segments'][0]['text']='我会剪辑视频。设备是否支持录像尚不确定。'
        def call(client,prompt,payload,stage,**kwargs):
            self.calls[stage]+=1
            if stage=='facts':
                if self.fail:raise ModelResponseError('invalid JSON','syntax_invalid')
                return dict(facts=[],unresolved=[dict(statement='设备是否支持录像尚不确定',evidence_ids=['s1'])])
            if stage=='decisions':return dict(decisions=[])
            if stage=='track_context':return dict(case_id='M',entities=[],thread_updates=[],new_threads=[dict(entity_labels=['视频'],updates=[dict(kind='work',description='剪辑视频',evidence_ids=['s1'])])])
            if stage=='interpret_work':
                from meeting_eval.context_wire import wire_request
                return wire_request(dict(meeting=payload['meeting'],body=interpretation()))['body']
            if stage=='check_work':
                old=check_response(payload['records'],payload['events']);raw=example(payload['output_schema'])
                raw['record_checks']={r['record_id']:{k:v for k,v in r.items() if k!='record_id'} for r in old['record_checks']}
                for r in raw['record_checks'].values():r['qualification']=dict(speech_scope='current',work_basis='action',evidence=['Q1'],adoption_evidence=[],reason='说话人明确承接剪辑')
                raw['checks']={r['event_id']+'.'+k:v for r in old['checks'] for k,v in r['fields'].items()};raw['coverage_findings']=[]
                from meeting_eval.context_wire import wire_request
                return wire_request(dict(meeting=payload['meeting'],body=raw))['body']
            if stage=='check_minutes':return assessment(payload)
            raise AssertionError('Unexpected '+stage)
        for p in (patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.ModelClient.call',call)):
            p.start();self.addCleanup(p.stop)
        self.open()
        self.addCleanup(lambda:self.store.close())

    def open(self):
        self.store=Store(self.path/'state.sqlite')
        self.svc=Service(self.store,Extractor(None,self.path/'model','context-v5'))

    def process(self):return self.svc.process(self.meeting,'host',AT)

    def test_tracking_failure_preserves_pending_source_then_resumes_without_duplicate_task(self):
        from meeting_eval.model_client import ModelClient
        original=ModelClient.call;blocked=[True];self.fail=False
        def call(client,prompt,payload,stage,**kwargs):
            if stage=='track_context' and blocked[0]:
                self.calls[stage]+=1
                raise ModelResponseError('bad tracking JSON','syntax_invalid')
            return original(client,prompt,payload,stage,**kwargs)
        with patch.object(ModelClient,'call',call):
            first=self.process();sid=first['source_id']
            self.assertEqual(first['status'],'partial')
            self.assertEqual(len(self.store.tasks()),0)
            trace=first['extraction']['_task_trace']['tracking']
            self.assertEqual(trace['completed_segments'],0)
            self.assertEqual(trace['pending_segment_ids'],['s1'])
            before=self.calls.copy();self.process();self.assertEqual(before,self.calls)
            blocked[0]=False
            result=self.svc.retry_extraction(sid,'host','retry-tracking',AT)
            self.assertEqual(result['status'],'processed',result['extraction']['_errors'])
            self.assertEqual(result['extraction']['_task_trace']['tracking']['status'],'complete')
            self.assertEqual(self.calls['track_context'],before['track_context']+1)
            for stage in ['facts','decisions']:self.assertEqual(self.calls[stage],before[stage])
            self.assertEqual(len(self.store.tasks()),1)
            before=self.calls.copy();self.svc.retry_extraction(sid,'host','retry-tracking',AT)
            self.assertEqual(self.calls,before);self.assertEqual(len(self.store.tasks()),1)

    def test_explicit_retry_resumes_only_failure_and_does_not_duplicate_task(self):
        first=self.process();sid=first['source_id']
        self.assertEqual(first['status'],'partial');self.assertEqual(first['recovery'][0]['status'],'recovery_required')
        self.assertEqual(len(self.store.tasks()),1)
        before=self.calls.copy();self.process();self.assertEqual(before,self.calls)
        self.fail=False
        out=self.svc.retry_extraction(sid,'host','user-retry-1',AT)
        self.assertEqual(out['source_id'],sid);self.assertEqual(out['status'],'processed',out['extraction']['_errors'])
        self.assertEqual(self.calls['facts'],3)
        for name in ('track_context','interpret_work','check_work','decisions'):self.assertEqual(self.calls[name],before[name])
        self.assertEqual(len(self.store.tasks()),1);self.assertEqual(len(out['intent_ids']),1)
        # A real work and unknown question in the same segment both survive.
        issues=self.svc.collected_issues(sid,'host');self.assertEqual(len(issues),1)
        self.assertFalse(issues[0]['can_add_task'])
        before=self.calls.copy();self.svc.retry_extraction(sid,'host','user-retry-1',AT)
        self.assertEqual(before,self.calls)
        self.store.close();self.open()
        self.assertEqual(self.svc.collected_issues(sid,'host'),issues)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM sources').fetchone()[0],1)

    def test_persistently_bad_content_cannot_reset_grant_even_with_new_retry_id(self):
        sid=self.process()['source_id']
        for token in ('one','one','two'):
            out=self.svc.retry_extraction(sid,'host',token,AT)
            self.assertEqual(out['status'],'partial')
        self.assertEqual(self.calls['facts'],3)
        self.assertTrue(out['recovery'][0]['manual_grant_used'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM extraction_retry_grants').fetchone()[0],1)

    def test_crash_after_grant_commit_is_resumed_by_ordinary_process(self):
        sid=self.process()['source_id'];self.fail=False
        with patch.object(self.svc,'process',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.svc.retry_extraction(sid,'host','one',AT)
        self.store.close();self.open()
        out=self.process();self.assertEqual(out['status'],'processed');self.assertEqual(self.calls['facts'],3)

    def test_wrong_actor_cannot_consume_grant(self):
        sid=self.process()['source_id']
        with self.assertRaises(PermissionError):self.svc.retry_extraction(sid,'alice','one',AT)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM extraction_retry_grants').fetchone()[0],0)

    def test_concurrent_duplicate_retry_id_does_not_start_second_batch(self):
        import threading
        from meeting_eval.model_client import ModelClient
        sid=self.process()['source_id'];self.fail=False
        entered=threading.Event();release=threading.Event();results=[]
        original=ModelClient.call
        def blocking(client,prompt,payload,stage,**kwargs):
            if stage=='facts':entered.set();release.wait(5)
            return original(client,prompt,payload,stage,**kwargs)
        def worker():
            store=Store(self.path/'state.sqlite')
            try:
                svc=Service(store,Extractor(None,self.path/'model','context-v5'))
                results.append(svc.retry_extraction(sid,'host','concurrent',AT))
            except Exception as exc:results.append(exc)
            finally:store.close()
        with patch.object(ModelClient,'call',blocking):
            thread=threading.Thread(target=worker);thread.start()
            try:
                self.assertTrue(entered.wait(5))
                duplicate=self.svc.retry_extraction(sid,'host','concurrent',AT)
                self.assertEqual(duplicate['status'],'partial')
                self.assertEqual(self.store.db.execute('SELECT count(*) FROM extraction_retry_grants').fetchone()[0],1)
            finally:release.set();thread.join()
        self.assertEqual(len(results),1)
        self.assertIsInstance(results[0],dict,repr(results[0]))
        self.assertEqual(results[0]['status'],'processed');self.assertEqual(self.calls['facts'],3)
        self.assertEqual(len(self.store.tasks()),1)


if __name__=='__main__':unittest.main()
