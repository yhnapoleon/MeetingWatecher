import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_context_state import ledger_fixture
from test_context_pipeline import ContextClient
try:
    from meeting_eval.context_v3 import ContextV3Pipeline as Pipeline
except ModuleNotFoundError:
    from meeting_eval.context_v2 import ContextV2Pipeline as Pipeline
from meeting_eval.context_v2 import reduce_v2
try:
    from meeting_eval.context_v3 import reduce_v3
except ImportError:
    reduce_v3=reduce_v2
from meeting_eval.context_coverage import plan_repair


def interpretation():
    m,e,l,r=ledger_fixture()
    r.update(evidence=['Q1'],need_basis=dict(goal=None,evidence=[]))
    e.pop('checks');e['candidate_ids']=[];e['work']={'evidence':['Q1']}
    for field in ('owner','commitment','time','state','relation'):
        e[field]['evidence']=['Q1'] if e[field]['evidence'] else []
    e['time']['change']='keep';e['other_changes']=[];e['relation']['candidate_guids']=[]
    return dict(case_id='M',records=[r],events=[e])


def check_response(records,events):
    return dict(case_id='M',record_checks=[dict(record_id=r['record_id'],kind=r['kind'],reason='分类符合原话',evidence=['Q1'],
        content=dict(verdict='supported',reason='内容完整且忠实',evidence=['Q1'],missing_details=[]),gap_checks=[]) for r in records],
        checks=[dict(event_id=e['event_id'],fields={f:dict(verdict='supported',reason='忠实于原话状态',evidence=['Q1'])
            for f in ('work','owner','commitment','time','state','relation')}) for e in events],coverage_findings=[])


class V3Client(ContextClient):
    def __init__(self,bad=False):super().__init__();self.bad=bad
    def call(self,prompt,payload,stage,**kwargs):
        self.calls.append((stage,copy.deepcopy(payload)))
        if stage=='track_context':return dict(case_id='M',**ledger_fixture()[2])
        if stage=='interpret_work':
            raw=interpretation()
            if self.bad and not payload.get('validation_feedback'):raw['events'][0]['work']['evidence']=['Q999']
            return raw
        if stage=='check_work':return check_response(payload['records'],payload['events'])
        raise AssertionError('Unexpected semantic repair '+stage)


class V3Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.pipe=Pipeline(V3Client(),Path(self.tmp.name),{})
        self.m,_,self.ledger,_=ledger_fixture();self.history={'tasks':[]}
        self.catalog={'Q1':dict(segment_id='s1',quote=self.m['segments'][0]['text'])}
    def interpret(self,raw):
        try:return self.pipe.interpret(raw,self.ledger,[],self.m,self.history)
        except (ValueError,TypeError,KeyError) as exc:self.fail('Valid v3 response rejected: '+str(exc))
    def verify(self,raw,interpreted):
        try:return self.pipe.check(raw,interpreted,self.m,self.catalog)
        except (ValueError,TypeError,KeyError) as exc:self.fail('Valid v3 check rejected: '+str(exc))
    def test_q_reference_removes_repeated_substring_ambiguity(self):
        self.m['segments'][0]['text']+='会后再确认，会后发布。'
        raw=interpretation();raw['events'][0]['time'].update(kind='work_window',text='会后',evidence=['Q1'])
        result=self.interpret(raw)
        self.assertEqual(result['events'][0]['time']['evidence'][0]['quote'],self.m['segments'][0]['text'])
    def test_item_uses_single_record_content_including_purpose(self):
        raw=interpretation();raw['records'][0]['description']='联系袁校长，核对刚才未听清的内容。'
        i=self.interpret(raw);c=self.verify(check_response(i['records'],i['events']),i)
        out=reduce_v2(dict(**c,coverage_findings=[],trace={}),self.m,self.history)
        self.assertEqual(out['items'][0]['description'],'联系袁校长，核对刚才未听清的内容。')
    def test_unknown_evidence_is_rejected(self):
        raw=interpretation();raw['records'][0]['evidence']=['Q999']
        with self.assertRaisesRegex(ValueError,'evidence'):self.pipe.interpret(raw,self.ledger,[],self.m,self.history)
    def test_rejected_gap_derives_question_issue_and_repair_target(self):
        raw=interpretation();raw['records'][0].update(missing_fields=['reference'],question='对象是谁？')
        i=self.interpret(raw);check=check_response(i['records'],i['events'])
        check['record_checks'][0]['gap_checks']=[dict(field='reference',status='not_needed',reason='对象已明确',evidence=['Q1'],question=None)]
        c=self.verify(check,i);r=c['checked_records'][0]
        self.assertEqual(set(r['check']['issues']),{'reference','question'})
        self.assertEqual(plan_repair(c['checked_records'],[],self.catalog,'test')['target_record_ids'],['R1'])
    def test_real_relation_choice_is_not_semantic_failure_and_never_updates(self):
        raw=interpretation();raw['records'][0].update(missing_fields=['relation'],question='关联 H1 还是 H2？')
        raw['events'][0]['relation'].update(kind='ambiguous',candidate_guids=['H1','H2']);raw['events'][0]['state']['kind']='completed'
        self.history={'tasks':[dict(guid='H1',summary='整理案例'),dict(guid='H2',summary='整理案例')]}
        i=self.interpret(raw);check=check_response(i['records'],i['events'])
        check['record_checks'][0]['gap_checks']=[dict(field='relation',status='needed',reason='两条旧任务竞争',evidence=['Q1'],question='关联 H1 还是 H2？')]
        c=self.verify(check,i)
        self.assertFalse(plan_repair(c['checked_records'],[],self.catalog,'test')['needs_repair'])
        out=reduce_v2(dict(**c,coverage_findings=[],trace={}),self.m,self.history)
        self.assertEqual(out['items'],[]);self.assertEqual(out['updates'],[])
        self.assertEqual(out['review_records'][0]['question'],'关联 H1 还是 H2？')
        self.assertFalse(out['review_records'][0]['can_add_task'])
    def test_ambiguous_old_completion_lists_choices_without_new_acceptance_gap(self):
        self.history={'tasks':[dict(guid='H1',summary='整理案例'),dict(guid='H2',summary='整理案例')]}
        raw=interpretation();raw['records'][0].update(missing_fields=['relation'],question='关联哪条旧任务？')
        e=raw['events'][0];e['state']['kind']='completed';e['commitment']['kind']='unknown'
        e['relation'].update(kind='ambiguous',candidate_guids=['H1','H2'])
        i=self.interpret(raw);r=check_response(i['records'],i['events'])
        r['record_checks'][0]['gap_checks']=[dict(field='relation',status='needed',reason='两个候选',evidence=['Q1'],question='关联哪条旧任务？')]
        c=self.verify(r,i);out=reduce_v3(dict(**c,coverage_findings=[],trace={}),self.m,self.history)
        self.assertEqual(out['review_records'][0]['missing_fields'],['relation'])
        self.assertIn('H1',out['review_records'][0]['question']);self.assertIn('H2',out['review_records'][0]['question'])
        self.assertEqual(out['updates'],[]);self.assertEqual(out['items'],[])

    def test_content_omission_triggers_repair_even_if_support_is_true(self):
        i=self.interpret(interpretation());raw=check_response(i['records'],i['events'])
        raw['record_checks'][0]['content']['missing_details']=[dict(description='核对未听清内容的目的',evidence=['Q1'])]
        c=self.verify(raw,i)
        self.assertIn('work',c['checked_records'][0]['check']['issues'])
        self.assertEqual(c['checked_records'][0]['content_audit']['missing_details'][0]['description'],'核对未听清内容的目的')
        self.assertTrue(plan_repair(c['checked_records'],[],self.catalog,'test')['needs_repair'])
    def test_background_reclassification_is_derived_without_duplicate_issue_fields(self):
        raw=interpretation();raw['records'][0].update(kind='implicit_need',content_basis='inferred',
            missing_fields=['scope'],question='是否需要处理？',need_basis=dict(goal='减少重复咨询',evidence=['Q1']))
        raw['events']=[];i=self.interpret(raw);check=check_response(i['records'],[])
        check['record_checks'][0].update(kind='context_only',gap_checks=[dict(field='scope',status='not_needed',reason='背景',evidence=['Q1'],question=None)])
        c=self.verify(check,i)
        self.assertEqual(c['checked_records'][0]['proposed_kind'],'context_only')
        self.assertIn('classification',c['checked_records'][0]['check']['issues'])
    def test_implicit_need_requires_source_backed_goal(self):
        raw=interpretation();raw['records'][0].update(kind='implicit_need',question='是否处理？');raw['events']=[]
        with self.assertRaisesRegex(ValueError,'goal'):self.pipe.interpret(raw,self.ledger,[],self.m,self.history)


class V3PipelineTests(unittest.TestCase):
    def test_resume_preserves_unparsed_client_response_in_feedback(self):
        from meeting_eval.model_client import ModelClient
        payloads=[]
        def transport(request,**kwargs):
            p=json.loads(request.data)['messages'][1]['content'];payload=json.loads(p);payloads.append(payload)
            if 'previous' in payload:content=json.dumps(dict(case_id='M',**ledger_fixture()[2]))
            elif 'records' in payload:content=json.dumps(check_response(payload['records'],payload['events']))
            elif 'validation_feedback' in payload:content=json.dumps(interpretation())
            else:content='{invalid json'
            return io.BytesIO(json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content=content))],usage={})).encode())
        m,*_=ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.urllib.request.urlopen',transport):
            p=Pipeline(ModelClient(None,Path(tmp)/'model'),Path(tmp)/'pipeline',{})
            first=p.run(m,{'tasks':[]});second=p.run(m,{'tasks':[]},resume=True)
            count=len(payloads);p.run(m,{'tasks':[]},resume=True)
            self.assertEqual(len(payloads),count)
        self.assertTrue(first['errors']);self.assertEqual(second['errors'],[])
        feedback=next(v['validation_feedback'] for v in payloads if 'validation_feedback' in v)
        self.assertEqual(feedback['previous_output']['raw_text'],'{invalid json')
        self.assertIn('JSONDecodeError',feedback['error'])

    def test_normal_pipeline_reaches_execution_without_repair(self):
        m,*_=ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            p=Pipeline(V3Client(),Path(tmp),{});result=p.run(m,{'tasks':[]})
        self.assertEqual(result['errors'],[])
        self.assertEqual(reduce_v2(result,m,{'tasks':[]})['items'][0]['operation'],'create')
    def test_resume_supplies_error_feedback_and_preserves_successful_tracking(self):
        m,*_=ledger_fixture();client=V3Client(True)
        with tempfile.TemporaryDirectory() as tmp:
            p=Pipeline(client,Path(tmp),{});first=p.run(m,{'tasks':[]});second=p.run(m,{'tasks':[]},resume=True)
            count=len(client.calls);p.run(m,{'tasks':[]},resume=True)
            self.assertEqual(len(client.calls),count)
        self.assertTrue(first['errors']);self.assertEqual(second['errors'],[])
        self.assertEqual(len([s for s,_ in client.calls if s=='track_context']),1)
        payload=[v for s,v in client.calls if s=='interpret_work'][-1]
        self.assertEqual(payload['validation_feedback']['previous_output']['events'][0]['work']['evidence'],['Q999'])
        self.assertIn('evidence',payload['validation_feedback']['error'])

    def test_service_strategy_executes_and_is_idempotent(self):
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        client=V3Client();m,*_=ledger_fixture()
        m.update(account_map={'alice':'alice'},audience=['host','alice'],writers=['host'])
        def call(_client,prompt,payload,stage,*args,**kwargs):
            if stage=='facts':return dict(facts=[],unresolved=[])
            if stage=='decisions':return dict(decisions=[])
            return client.call(prompt,payload,stage,**kwargs)
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.ModelClient.call',call):
            store=Store(Path(tmp)/'state.sqlite')
            try:
                try:extractor=Extractor(None,Path(tmp)/'model','context-v3')
                except ValueError as exc:self.fail('Strategy unavailable: '+str(exc))
                svc=Service(store,extractor);first=svc.process(m,'host','2026-11-15T00:00:00+08:00')
                second=svc.process(m,'host','2026-11-15T00:00:00+08:00')
                self.assertEqual(first['status'],'processed');self.assertEqual(len(store.tasks()),1)
                self.assertEqual(first['source_id'],second['source_id'])
            finally:store.close()


if __name__=='__main__':unittest.main()
