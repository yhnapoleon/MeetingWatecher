import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_task_events import sample


class RecordedClient:
    model='deepseek-flash'
    endpoint='https://example.invalid'
    def __init__(self, fail_check=False, empty=False):
        self.calls=[]
        self.fail_check=fail_check
        self.empty=empty
    def call(self,prompt,payload,stage,**kwargs):
        self.calls.append(stage)
        meeting,event=sample()
        if stage=='locate_work':
            return {'case_id':'M','candidates':[] if self.empty else [{'spans':[{'segment_id':'s1','quote':'我会剪辑视频'}]}]}
        if stage=='interpret_work':
            event.pop('checks');event.pop('event_id')
            return {'case_id':'M','events':[] if self.empty else [event],'discarded_candidates':[]}
        if stage=='check_work':
            if self.fail_check:
                self.fail_check=False
                raise OSError('temporary failure')
            return {'case_id':'M','checks':[] if self.empty else [{'event_id':'E1','fields':event['checks']}],
                    'uncovered_spans':[{'segment_id':'s1','quote':'我会剪辑视频'}] if self.empty else []}
        raise AssertionError(stage)


class PipelineTests(unittest.TestCase):
    def test_failed_check_resumes_without_regenerating_successful_upstream(self):
        from meeting_eval.task_pipeline import TaskPipeline
        meeting,_=sample();client=RecordedClient(fail_check=True)
        with tempfile.TemporaryDirectory() as tmp:
            pipeline=TaskPipeline(client,Path(tmp),{})
            first=pipeline.run(meeting,{'tasks':[]})
            self.assertTrue(first['errors'])
            second=pipeline.run(meeting,{'tasks':[]},resume=True)
            self.assertEqual(second['errors'],[])
            self.assertEqual(len(second['checked_events']),1)
            self.assertEqual(client.calls,['locate_work','interpret_work','check_work','check_work'])

    def test_empty_locator_still_checks_original_for_omissions(self):
        from meeting_eval.task_pipeline import TaskPipeline
        meeting,_=sample();client=RecordedClient(empty=True)
        with tempfile.TemporaryDirectory() as tmp:
            result=TaskPipeline(client,Path(tmp),{}).run(meeting,{'tasks':[]})
            self.assertEqual(result['errors'],[])
            self.assertEqual(len(result['uncovered_spans']),1)
            self.assertEqual(client.calls[-1],'check_work')

    def test_missing_check_field_is_not_a_successful_empty_result(self):
        from meeting_eval.task_pipeline import TaskPipeline
        class Missing(RecordedClient):
            def call(self,*args,**kwargs):
                value=super().call(*args,**kwargs)
                if args[2]=='check_work':del value['checks'][0]['fields']['work']
                return value
        meeting,_=sample()
        with tempfile.TemporaryDirectory() as tmp:
            result=TaskPipeline(Missing(),Path(tmp),{}).run(meeting,{'tasks':[]})
            self.assertTrue(result['errors'])
            self.assertEqual(result['checked_events'],[])

    def test_interpreter_can_recover_work_missed_by_locator(self):
        from meeting_eval.task_pipeline import TaskPipeline
        class Recovery(RecordedClient):
            def call(self,*args,**kwargs):
                value=super().call(*args,**kwargs)
                if args[2]=='locate_work':value['candidates']=[]
                if args[2]=='interpret_work':value['events'][0]['candidate_ids']=[]
                return value
        meeting,_=sample()
        with tempfile.TemporaryDirectory() as tmp:
            result=TaskPipeline(Recovery(),Path(tmp),{}).run(meeting,{'tasks':[]})
            self.assertEqual(result['errors'],[])
            self.assertEqual(len(result['checked_events']),1)
            self.assertEqual(result['trace']['candidates'][0]['origin'],'interpret_work')

    def test_turning_off_stage_reasoning_removes_dependent_defaults(self):
        from meeting_eval.task_pipeline import TaskPipeline
        with tempfile.TemporaryDirectory() as tmp:
            pipeline=TaskPipeline(RecordedClient(),Path(tmp),{'interpret_work':{'thinking':'disabled'}})
            self.assertEqual(pipeline.inference['interpret_work']['temperature'],0)
            self.assertNotIn('reasoning_effort',pipeline.inference['interpret_work'])

    def test_service_recovers_check_failure_then_creates_exactly_one_task(self):
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        meeting,_=sample();meeting.update(account_map={'alice':'alice'},audience=['host','alice'],writers=['host'])
        client=RecordedClient(fail_check=True)
        def call(_client,prompt,payload,stage,*args,**kwargs):
            if stage=='facts':return {'facts':[],'unresolved':[]}
            if stage=='decisions':return {'decisions':[]}
            return client.call(prompt,payload,stage,**kwargs)
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.ModelClient.call',call):
            model=Extractor(None,Path(tmp)/'model','evidence-v1')
            store=Store(Path(tmp)/'state.sqlite')
            try:
                service=Service(store,model)
                first=service.process(meeting,'host','2026-11-14T00:00:00+08:00')
                self.assertEqual(first['status'],'partial')
                self.assertEqual(store.tasks(),[])
                second=service.process(meeting,'host','2026-11-14T00:01:00+08:00')
                third=service.process(meeting,'host','2026-11-14T00:02:00+08:00')
                self.assertEqual(second['status'],'processed')
                self.assertEqual(len(store.tasks()),1)
                self.assertEqual(second['bindings'],third['bindings'])
                self.assertIn('剪辑视频',service.minutes(second['source_id'],'host'))
                self.assertEqual(client.calls,['locate_work','interpret_work','check_work','check_work'])
            finally:store.close()

    def test_retry_of_other_branch_preserves_task_trace(self):
        from meeting_eval.extract import merge_retry
        previous=dict(items=[{'description':'valid'}],updates=[],facts=[],unresolved=[],decisions=[],
                      _task_trace={'events':['frozen']},_errors=[{'field':'facts','error':'bad'}])
        current=dict(items=[],updates=[],facts=[{'statement':'fixed'}],unresolved=[],decisions=[],_errors=[])
        result=merge_retry(previous,current)
        self.assertEqual(result['_task_trace'],{'events':['frozen']})
        self.assertEqual(result['items'],previous['items'])

    def test_semantic_dataset_uses_normal_evaluator_and_exports_review(self):
        import json
        from scripts.run_meeting_eval import evaluate
        from meeting_eval.inputs import digest
        meeting,_=sample()
        meeting.update(audience=['evaluator'],writers=['evaluator'])
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'data';data.mkdir()
            (data/'input.jsonl').write_text(json.dumps(meeting)+'\n',encoding='utf-8')
            (data/'labels.jsonl').write_text('',encoding='utf-8')
            (data/'manifest.json').write_text(json.dumps(dict(status='frozen',input_hash=digest([meeting]),labels_hash=digest([]))),encoding='utf-8')
            class Model:
                config={'strategy':'test'}
                def __init__(self,env,out,strategy,**kwargs):Path(out).mkdir(parents=True,exist_ok=True)
                def extract(self,m,c):return dict(items=[],facts=[],unresolved=[],decisions=[],updates=[])
            with patch('scripts.run_meeting_eval.Extractor',Model):
                report=evaluate(Path(tmp)/'out',None,'actions',data_dir=data)
            self.assertEqual(report['successful'],1)
            self.assertEqual(json.loads((Path(tmp)/'out/semantic-review.json').read_text(encoding='utf-8'))['status'],'draft')

    def test_completed_recovery_invalidates_and_archives_prior_review(self):
        from scripts.run_meeting_eval import save_review
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'semantic-review.json'
            old={'hashes':{'predictions':'old'},'status':'agent_reviewed'}
            path.write_text(json.dumps(old),encoding='utf-8')
            fresh={'hashes':{'predictions':'new'},'status':'draft'}
            save_review(path,fresh)
            self.assertEqual(json.loads(path.read_text()),fresh)
            archived=list(path.parent.glob('semantic-review.previous-*.json'))
            self.assertEqual(len(archived),1)
            self.assertEqual(json.loads(archived[0].read_text()),old)

    def test_subset_snapshot_can_be_scored_without_rebuilding_labels(self):
        import json
        from meeting_eval.inputs import digest
        from scripts.run_meeting_eval import evaluate
        from scripts.review_action_semantics import read_jsonl
        from scripts.score_action_semantics import score_semantics
        meeting,_=sample();meeting.update(audience=['evaluator'],writers=['evaluator'])
        inputs=[meeting,{**copy.deepcopy(meeting),'case_id':'N'}]
        labels=[dict(case_id=c['case_id'],event_id=c['case_id']+'.1',operation='candidate',description='剪辑视频',evidence_ids=['s1']) for c in inputs]
        class Model:
            config={'strategy':'test'}
            def __init__(self,env,out,strategy,**kwargs):Path(out).mkdir(parents=True,exist_ok=True)
            def extract(self,m,c):return dict(items=[],updates=[],facts=[],unresolved=[],decisions=[])
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'data';data.mkdir();out=Path(tmp)/'out'
            for name,rows in [('input',inputs),('labels',labels)]:
                (data/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
            (data/'manifest.json').write_text(json.dumps(dict(status='frozen',input_hash=digest(inputs),labels_hash=digest(labels))),encoding='utf-8')
            with patch('scripts.run_meeting_eval.Extractor',Model):
                evaluate(out,None,'actions',only=['M'],data_dir=data)
            selected=read_jsonl(out/'labels.snapshot.jsonl')
            self.assertEqual(len(selected),1)
            review=json.loads((out/'semantic-review.json').read_text(encoding='utf-8'))
            review.update(status='agent_reviewed',reviewer='test')
            review['cases'][0]['reviewed']=True
            score=score_semantics(read_jsonl(out/'predictions.jsonl'),selected,review)
            self.assertEqual(score['content']['expected'],1)


if __name__=='__main__':
    unittest.main()
