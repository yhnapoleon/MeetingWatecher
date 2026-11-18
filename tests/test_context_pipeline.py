import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_context_state import ledger_fixture


class ContextClient:
    model='deepseek-flash'
    endpoint='https://example.invalid'
    def __init__(self,fail=False):self.calls=[];self.fail=fail
    def call(self,prompt,payload,stage,**kwargs):
        self.calls.append((stage,copy.deepcopy(payload)))
        m,event,ledger,record=ledger_fixture()
        if stage=='track_context':return dict(case_id='M',**ledger)
        if stage=='interpret_work':
            event.pop('checks')
            event['time']['change']='keep'
            event['other_changes']=[]
            return dict(case_id='M',events=[event],records=[record])
        if stage=='check_work':
            if self.fail:self.fail=False;raise ValueError('bad JSON')
            for value in event['checks'].values():value['evidence']=['Q1'] if value['evidence'] else []
            return dict(case_id='M',checks=[dict(event_id='E1',fields=event['checks'])],uncovered_spans=[],
                        record_checks=[dict(record_id='R1',verdict='supported',reason='原话支持',evidence=['Q1'])])
        raise AssertionError(stage)


class ContextPipelineTests(unittest.TestCase):
    def test_service_keeps_valid_work_and_does_not_repeat_optional_failed_repair(self):
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        class OptionalFailure(ContextClient):
            def call(self,prompt,payload,stage,**kwargs):
                if stage=='repair_work':
                    self.calls.append((stage,copy.deepcopy(payload)))
                    raise OSError('optional correction unavailable')
                value=super().call(prompt,payload,stage,**kwargs)
                if stage=='interpret_work':
                    r=copy.deepcopy(value['records'][0]);r['record_id']='R2';value['records'].append(r)
                    e=copy.deepcopy(value['events'][0]);e['record_id']='R2';value['events'].append(e)
                if stage=='check_work':
                    r=copy.deepcopy(value['record_checks'][0]);r['record_id']='R2';value['record_checks'].append(r)
                    e=copy.deepcopy(value['checks'][0]);e['event_id']='E2';value['checks'].append(e)
                    value['record_checks'][0].update(verdict='contradicted',issues=['work'],reason='此条内容有误')
                return value
        client=OptionalFailure()
        def call(_client,prompt,payload,stage,*args,**kwargs):
            if stage=='facts':return dict(facts=[],unresolved=[])
            if stage=='decisions':return dict(decisions=[])
            return client.call(prompt,payload,stage,**kwargs)
        m,*_=ledger_fixture();m.update(account_map={'alice':'alice'},audience=['host','alice'],writers=['host'])
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.ModelClient.call',call):
            store=Store(Path(tmp)/'state.sqlite')
            try:
                svc=Service(store,Extractor(None,Path(tmp)/'model','context-v1'))
                first=svc.process(m,'host','2026-11-15T00:00:00+08:00')
                self.assertEqual(first['status'],'processed')
                self.assertEqual(first['extraction']['_task_trace']['repair']['status'],'failed')
                self.assertEqual(len(store.tasks()),1)
                calls=len(client.calls)
                second=svc.process(m,'host','2026-11-15T00:00:00+08:00')
                self.assertEqual(len(client.calls),calls)
                self.assertEqual(second['source_id'],first['source_id'])
                self.assertEqual(len(store.tasks()),1)
            finally:store.close()

    def test_repair_can_remove_wrong_event_without_rewriting_other_event(self):
        from meeting_eval.context_pipeline import ContextPipeline
        class RemoveClient(ContextClient):
            def call(self,prompt,payload,stage,**kwargs):
                if stage=='repair_work':
                    self.calls.append((stage,copy.deepcopy(payload)))
                    r=copy.deepcopy(payload['original_records'][0]);r.update(kind='entity_only',missing_fields=[],question=None)
                    return dict(case_id='M',records=[r],events=[])
                if stage=='check_repair':
                    self.calls.append((stage,copy.deepcopy(payload)))
                    return dict(case_id='M',checks=[],uncovered_spans=[],record_checks=[dict(record_id='R1',
                        verdict='insufficient',issues=['classification'],reason='仍应是待确认线索',evidence=['Q1'])])
                value=super().call(prompt,payload,stage,**kwargs)
                if stage=='interpret_work':
                    r=copy.deepcopy(value['records'][0]);r['record_id']='R2';value['records'].append(r)
                    e=copy.deepcopy(value['events'][0]);e['record_id']='R2';value['events'].append(e)
                if stage=='check_work':
                    row=copy.deepcopy(value['record_checks'][0]);row['record_id']='R2';value['record_checks'].append(row)
                    e=copy.deepcopy(value['checks'][0]);e['event_id']='E2';value['checks'].append(e)
                    value['record_checks'][0].update(verdict='contradicted',issues=['classification'],reason='错误分类')
                return value
        m,*_=ledger_fixture();client=RemoveClient()
        with tempfile.TemporaryDirectory() as tmp:
            result=ContextPipeline(client,Path(tmp),{}).run(m,{'tasks':[]})
            original=result['trace']['repair']['before']['checked_events'][1]
            self.assertEqual(result['checked_events'],[original])
            self.assertEqual(result['events'][0]['event_id'],'E2')
            self.assertEqual(result['checked_records'][0]['check']['verdict'],'insufficient')
            self.assertEqual([s for s,p in client.calls].count('repair_work'),1)

    def test_repair_adds_missing_event_and_preserves_other_record(self):
        from meeting_eval.context_pipeline import ContextPipeline
        class RepairClient(ContextClient):
            def call(self,prompt,payload,stage,**kwargs):
                if stage in ('repair_work','check_repair'):
                    self.calls.append((stage,copy.deepcopy(payload)))
                    m,e,l,r=ledger_fixture()
                    if stage=='repair_work':
                        e.pop('checks');e['time']['change']='keep';e['other_changes']=[]
                        return dict(case_id='M',records=[r],events=[e])
                    self.assert_target=payload['records'][0]['record_id']
                    for v in e['checks'].values():v['evidence']=['Q1'] if v['evidence'] else []
                    return dict(case_id='M',checks=[dict(event_id=payload['events'][0]['event_id'],fields=e['checks'])],
                                record_checks=[dict(record_id='R1',verdict='supported',issues=[],reason='原话支持',evidence=['Q1'])],uncovered_spans=[])
                result=super().call(prompt,payload,stage,**kwargs)
                if stage=='interpret_work':
                    other=copy.deepcopy(result['records'][0]);other.update(record_id='R2',kind='entity_only')
                    result['records'][0].update(kind='ambiguous',content_basis='unknown',missing_fields=['work'],question='是否需要剪辑？')
                    result['records'].append(other);result['events']=[]
                if stage=='check_work':
                    result['checks']=[]
                    result['record_checks'][0].update(verdict='contradicted',issues=['classification'],reason='已明确说剪辑视频，不应视为未知')
                    result['record_checks'].append(dict(record_id='R2',verdict='supported',issues=[],reason='实体',evidence=['Q1']))
                return result
        m,*_=ledger_fixture();client=RepairClient()
        with tempfile.TemporaryDirectory() as tmp:
            pipe=ContextPipeline(client,Path(tmp),{})
            result=pipe.run(m,{'tasks':[]})
            self.assertEqual(result['errors'],[])
            self.assertEqual(len(result['checked_events']),1)
            self.assertEqual(result['checked_records'][0]['kind'],'work')
            original=result['trace']['repair']['before']['checked_records'][1]
            self.assertEqual(result['checked_records'][1],original)
            self.assertEqual([s for s,p in client.calls].count('repair_work'),1)
            pipe.run(m,{'tasks':[]},resume=True)
            self.assertEqual([s for s,p in client.calls].count('repair_work'),1)

    def test_failed_repair_keeps_first_checks_and_resume_reuses_upstream(self):
        from meeting_eval.context_pipeline import ContextPipeline
        class FailedRepair(ContextClient):
            def call(self,prompt,payload,stage,**kwargs):
                if stage=='repair_work':
                    self.calls.append((stage,copy.deepcopy(payload)))
                    value=super().call(prompt,payload,'interpret_work',**kwargs)
                    if len([s for s,p in self.calls if s=='repair_work'])==1:value['records'][0]['record_id']='R999'
                    return value
                if stage=='check_repair':
                    self.calls.append((stage,copy.deepcopy(payload)))
                    raise ValueError('check failed')
                value=super().call(prompt,payload,stage,**kwargs)
                if stage=='check_work':value['record_checks'][0].update(verdict='contradicted',issues=['question'],reason='多余问题')
                return value
        m,*_=ledger_fixture();client=FailedRepair()
        with tempfile.TemporaryDirectory() as tmp:
            pipe=ContextPipeline(client,Path(tmp),{})
            first=pipe.run(m,{'tasks':[]})
            self.assertEqual(first['trace']['repair']['status'],'failed')
            self.assertEqual(first['checked_records'][0]['check']['verdict'],'contradicted')
            second=pipe.run(m,{'tasks':[]},resume=True)
            self.assertEqual(second['checked_records'],first['checked_records'])
            self.assertEqual([s for s,p in client.calls].count('track_context'),1)
            self.assertEqual([s for s,p in client.calls].count('check_work'),1)
            self.assertEqual([s for s,p in client.calls].count('check_repair'),1)

    def test_unknown_check_evidence_reference_blocks_execution(self):
        from meeting_eval.context_pipeline import ContextPipeline
        class Invalid(ContextClient):
            def call(self,*args,**kwargs):
                value=super().call(*args,**kwargs)
                if args[2]=='check_work':value['record_checks'][0]['evidence']=['Q999']
                return value
        m,*_=ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            result=ContextPipeline(Invalid(),Path(tmp),{}).run(m,{'tasks':[]})
            self.assertTrue(result['errors'])
            self.assertEqual(result['checked_events'],[])

    def test_checkpoints_never_see_future_and_resume_preserves_upstream(self):
        from meeting_eval.context_pipeline import ContextPipeline
        m,*_=ledger_fixture()
        m['segments'] += [dict(id=f's{i}',speaker='A',person_ref='alice',text='嗯。') for i in range(2,10)]
        client=ContextClient(fail=True)
        with tempfile.TemporaryDirectory() as tmp:
            pipe=ContextPipeline(client,Path(tmp),{})
            first=pipe.run(m,{'tasks':[]})
            self.assertTrue(first['errors'])
            second=pipe.run(m,{'tasks':[]},resume=True)
            self.assertEqual(second['errors'],[])
            self.assertEqual(len(second['trace']['checkpoints']),2)
            self.assertEqual([len(p['meeting']['segments']) for s,p in client.calls if s=='track_context'],[8,9])
            self.assertEqual([s for s,p in client.calls].count('interpret_work'),1)
            self.assertEqual(second['checked_records'][0]['description'],'剪辑视频')

    def test_normal_service_routes_inferred_need_to_visible_review(self):
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        m,*_=ledger_fixture();m.update(account_map={'alice':'alice'},audience=['host','alice'],writers=['host'])
        client=ContextClient()
        def call(_client,prompt,payload,stage,*args,**kwargs):
            if stage=='facts':return {'facts':[],'unresolved':[]}
            if stage=='decisions':return {'decisions':[]}
            result=client.call(prompt,payload,stage,**kwargs)
            if stage=='interpret_work':result['records'][0].update(kind='implicit_need',content_basis='inferred',question='是否研究视频使用问题？',missing_fields=['work'])
            return result
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.ModelClient.call',call):
            store=Store(Path(tmp)/'state.sqlite')
            try:
                svc=Service(store,Extractor(None,Path(tmp)/'model','context-v1'))
                result=svc.process(m,'host','2026-11-14T00:00:00+08:00')
                self.assertEqual(result['status'],'processed')
                self.assertEqual(store.tasks(),[])
                self.assertEqual(result['extraction']['_task_trace']['review_records'][0]['category'],'implicit_need')
                self.assertIn('是否研究视频使用问题',svc.minutes(result['source_id'],'host'))
            finally:store.close()


if __name__=='__main__':unittest.main()
