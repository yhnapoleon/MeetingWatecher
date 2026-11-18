import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_context_pipeline import ContextClient
from test_context_state import ledger_fixture
from meeting_eval.context_v2 import ContextV2Pipeline as Pipeline,reduce_v2


class ClientV2(ContextClient):
    def __init__(self,mode='add'):
        super().__init__();self.mode=mode

    def call(self,prompt,payload,stage,**kwargs):
        if stage in ('track_context','interpret_work'):
            return super().call(prompt,payload,stage,**kwargs)
        self.calls.append((stage,copy.deepcopy(payload)))
        if stage=='repair_work':
            records=copy.deepcopy(payload['original_records']);events=copy.deepcopy(payload['original_events'])
            if self.mode in ('add','bad_added'):
                _,e,_,r=ledger_fixture();r.update(record_id='R_O1_1',thread_ids=[],introduced_by='O1',
                    description='将合同发给法务',evidence=[dict(segment_id='s1',quote='我还会把合同发给法务')])
                e.pop('checks');e.update(record_id='R_O1_1',candidate_ids=[],other_changes=[])
                e['work']=dict(description=r['description'],evidence=r['evidence']);e['time']['change']='keep'
                records.append(r);events.append(e)
                dispositions=[dict(finding_id='O1',disposition='added',record_ids=['R_O1_1'],evidence=['Q1'])]
            else:dispositions=[dict(finding_id='O1',disposition='rejected',record_ids=[],evidence=['Q1'])] if payload['coverage_findings'] else []
            if self.mode=='invalid':records.append(copy.deepcopy(records[0]) if records else dict(record_id='bogus'))
            return dict(case_id='M',records=records,events=events,dispositions=dispositions)
        checks=[];record_checks=[]
        for r in payload['records']:
            bad=stage=='check_repair' and self.mode=='bad_added' and r['record_id']=='R_O1_1'
            record_checks.append(dict(record_id=r['record_id'],verdict='contradicted' if bad else 'supported',
                issues=['work'] if bad else [],reason='原话核验',evidence=['Q1'],proposed_kind=None,
                gap_checks=[],clarification=dict(status='not_needed',basis='没有待决定事项',fields=[],question=None,evidence=['Q1'])))
            if stage=='check_work' and self.mode=='unresolved':record_checks[-1]['clarification']['status']='unresolved'
        for e in payload['events']:
            checks.append(dict(event_id=e['event_id'],fields={f:dict(verdict='supported',reason='原话支持',evidence=['Q1']) for f in ('work','owner','commitment','time','state','relation')}))
        if stage=='check_work':
            findings=[] if self.mode in ('clean','unresolved') else [dict(description='将合同发给法务',evidence=['Q1'],relation='new_work',related_record_ids=[])]
            return dict(case_id='M',record_checks=record_checks,checks=checks,coverage_findings=findings)
        return dict(case_id='M',record_checks=record_checks,checks=checks,
            disposition_checks=[{**d,'verdict':'supported','reason':'原话支持处置'} for d in payload['dispositions']])


class PipelineV2Tests(unittest.TestCase):
    def run_case(self,mode):
        m,*_=ledger_fixture();m['segments'][0]['text']+='我还会把合同发给法务。'
        client=ClientV2(mode)
        with tempfile.TemporaryDirectory() as tmp:
            result=Pipeline(client,Path(tmp),{}).run(m,{'tasks':[]})
        return result,client,m

    def test_omission_alone_triggers_one_repair_and_adds_distinct_event(self):
        result,client,m=self.run_case('add')
        self.assertEqual(result['errors'],[])
        self.assertEqual([s for s,_ in client.calls].count('repair_work'),1)
        self.assertEqual([e['event_id'] for e in result['checked_events']],['E1','E2'])
        self.assertEqual([r['record_id'] for r in result['checked_records']],['R1','R_O1_1'])
        self.assertEqual(result['coverage_findings'],[])

    def test_verified_rejection_closes_omission_without_changing_original_event(self):
        result,client,m=self.run_case('reject')
        self.assertEqual(result['errors'],[])
        self.assertEqual(result['coverage_findings'],[])
        self.assertEqual(len(result['checked_events']),1)
        self.assertEqual(result['checked_events'],result['trace']['repair']['before']['checked_events'])

    def test_bad_addition_keeps_original_work_and_one_unresolved_finding(self):
        result,client,m=self.run_case('bad_added')
        self.assertEqual(result['errors'],[])
        self.assertEqual(len(result['checked_events']),1)
        self.assertEqual(len(result['coverage_findings']),1)
        self.assertEqual(result['coverage_findings'][0]['finding_id'],'O1')

    def test_invalid_repair_preserves_first_valid_output_and_is_not_retried(self):
        result,client,m=self.run_case('invalid')
        self.assertEqual(result['errors'],[])
        self.assertEqual(result['trace']['repair']['status'],'failed')
        self.assertEqual(len(result['checked_events']),1)
        self.assertEqual(len(result['coverage_findings']),1)
        self.assertEqual([s for s,_ in client.calls].count('repair_work'),1)

    def test_clean_case_does_not_call_optional_repair(self):
        result,client,m=self.run_case('clean')
        self.assertEqual(result['errors'],[])
        self.assertNotIn('repair_work',[s for s,_ in client.calls])

    def test_unresolved_interpretation_uses_remaining_single_repair_budget(self):
        result,client,m=self.run_case('unresolved')
        self.assertEqual(result['errors'],[])
        self.assertEqual([s for s,_ in client.calls].count('repair_work'),1)
        self.assertEqual(result['checked_records'][0]['clarification']['status'],'not_needed')


class ServiceV2Tests(unittest.TestCase):
    def run_service(self,mode):
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        m,*_=ledger_fixture();m['segments'][0]['text']+='我还会把合同发给法务。'
        m.update(account_map={'alice':'alice'},audience=['host','alice'],writers=['host'])
        client=ClientV2(mode)
        def call(_client,prompt,payload,stage,*args,**kwargs):
            if stage=='facts':return dict(facts=[],unresolved=[])
            if stage=='decisions':return dict(decisions=[])
            return client.call(prompt,payload,stage,**kwargs)
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.ModelClient.call',call):
            store=Store(Path(tmp)/'state.sqlite')
            try:
                svc=Service(store,Extractor(None,Path(tmp)/'model','context-v2'))
                first=svc.process(m,'host','2026-11-15T00:00:00+08:00')
                count=len(store.tasks());calls=len(client.calls)
                second=svc.process(m,'host','2026-11-15T00:00:00+08:00')
                self.assertEqual(second['source_id'],first['source_id']);self.assertEqual(len(store.tasks()),count);self.assertEqual(len(client.calls),calls)
                minutes=svc.minutes(first['source_id'],'host')
                return first,count,minutes
            finally:store.close()

    def test_service_executes_both_same_segment_tasks_and_repeat_is_idempotent(self):
        result,count,minutes=self.run_service('add')
        self.assertEqual(result['status'],'processed');self.assertEqual(count,2)
        self.assertEqual(result['extraction']['_task_trace']['review_records'],[])

    def test_failed_addition_is_one_unresolved_entry_without_fabricated_task_question(self):
        result,count,minutes=self.run_service('bad_added')
        self.assertEqual(count,1)
        reviews=result['extraction']['_task_trace']['review_records'];self.assertEqual(len(reviews),1)
        self.assertEqual(reviews[0]['category'],'interpretation_unresolved')
        self.assertEqual(minutes.count(reviews[0]['record_id']),1)
        self.assertNotIn('建议向任务提出方确认',minutes)


class ReducerV2Tests(unittest.TestCase):
    def fault(self,field):
        class Fault(ClientV2):
            def call(self,prompt,payload,stage,**kwargs):
                if stage=='repair_work':raise OSError('repair unavailable')
                raw=super().call(prompt,payload,stage,**kwargs)
                if stage=='check_work':
                    raw['checks'][0]['fields'][field]['verdict']='contradicted'
                    if field=='owner':
                        r=raw['record_checks'][0];r.update(verdict='contradicted',issues=['owner'])
                        r['gap_checks']=[dict(field='owner',verdict='supported',blocking_for='operation',reason='负责人不明',evidence=['Q1'])]
                        r['clarification'].update(status='needed',fields=['owner'],question='由谁负责？')
                return raw
        m,*_=ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp:result=Pipeline(Fault('clean'),Path(tmp),{}).run(m,{'tasks':[]})
        self.assertEqual(result['errors'],[]);self.assertEqual(result['trace']['repair']['status'],'failed')
        return reduce_v2(result,m,{'tasks':[]})

    def test_owner_only_dispute_keeps_real_work_candidate(self):
        result=self.fault('owner')
        self.assertEqual(len(result['items']),1);self.assertEqual(result['items'][0]['operation'],'candidate')
        self.assertNotEqual(result['review_records'][0]['category'],'interpretation_unresolved')

    def test_event_work_dispute_is_unresolved_without_task_premise(self):
        result=self.fault('work')
        self.assertEqual(result['items'],[])
        self.assertEqual(result['review_records'][0]['category'],'interpretation_unresolved')
        self.assertFalse(result['review_records'][0]['can_add_task'])


class SchemaV2Tests(unittest.TestCase):
    def test_missing_time_change_and_other_changes_reported_before_quote_matching(self):
        m,e,ledger,r=ledger_fixture();e.pop('checks');e['record_id']='R1'
        with tempfile.TemporaryDirectory() as tmp:
            pipe=Pipeline(ClientV2(),Path(tmp),{})
            with self.assertRaises(ValueError) as error:pipe.interpret(dict(case_id='M',records=[r],events=[e]),ledger,[],m,{'tasks':[]})
            self.assertIn('time.change',str(error.exception));self.assertIn('other_changes',str(error.exception))


if __name__=='__main__':unittest.main()
