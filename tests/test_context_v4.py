import copy
import tempfile
import unittest
from pathlib import Path

from test_context_v3 import interpretation, check_response, V3Client
from test_context_state import ledger_fixture
from meeting_eval.context_v3 import reduce_v3
from meeting_eval.context_protocol_v4 import coverage_to_v3, repair_contract, expand_patch
from meeting_eval.context_v4 import ContextV4Pipeline


def payload():
    raw=interpretation()
    return dict(meeting=ledger_fixture()[0],target_record_ids=['R1'],
                original_records=raw['records'],original_events=raw['events'],
                context_records=[],coverage_findings=[])


def patch_for(p):
    raw=interpretation();r=raw['records'][0];e=raw['events'][0]
    return dict(case_id='M',scope=repair_contract(p)[1]['scope'],
                targets={'target_1':dict(record={k:v for k,v in r.items() if k not in ('record_id','thread_ids','introduced_by')},
                    event={k:v for k,v in e.items() if k not in ('record_id','event_id')})},
                additions={},dispositions=[])


class V4ProtocolTests(unittest.TestCase):
    def test_new_work_relation_is_program_owned(self):
        raw=check_response([],[]);raw.pop('coverage_findings')
        raw.update(new_work_findings=[dict(description='发送测试结果',evidence=['Q1'])],uncertain_findings=[])
        out=coverage_to_v3(raw)
        self.assertEqual(out['coverage_findings'],[dict(description='发送测试结果',evidence=['Q1'],relation='new_work',related_record_ids=[])])
        raw['new_work_findings'][0]['related_record_ids']=['R1']
        with self.assertRaises(ValueError):coverage_to_v3(raw)

    def test_patch_restores_identity_and_does_not_mutate_original(self):
        p=payload();before=copy.deepcopy(p);raw=patch_for(p)
        raw['targets']['target_1']['record']['description']='修改后的工作'
        out=expand_patch(raw,p)
        self.assertEqual(out['records'][0]['record_id'],'R1')
        self.assertEqual(out['records'][0]['thread_ids'],['T1'])
        self.assertEqual(out['events'][0]['record_id'],'R1')
        self.assertEqual(out['records'][0]['description'],'修改后的工作')
        self.assertEqual(p,before)

    def test_rejects_out_of_scope_identity_and_stale_patch(self):
        p=payload()
        for mutate in (lambda r:r['targets'].update(target_2=r['targets']['target_1']),
                       lambda r:r['targets']['target_1']['record'].update(thread_ids=['T2']),
                       lambda r:r.update(scope='stale'),
                       lambda r:r.update(records=[])):
            raw=patch_for(p);mutate(raw)
            with self.assertRaises(ValueError):expand_patch(raw,p)

    def test_additions_get_finding_identity_from_program(self):
        p=payload();p['coverage_findings']=[dict(finding_id='O1',description='另一工作',evidence=['Q1'],relation='new_work',related_record_ids=[])]
        raw=patch_for(p);raw['additions']={'O1':[copy.deepcopy(raw['targets']['target_1'])]}
        raw['dispositions']=[dict(finding_id='O1',disposition='added',record_ids=['R_O1_1'],evidence=['Q1'])]
        out=expand_patch(raw,p)
        self.assertEqual(out['records'][1]['record_id'],'R_O1_1')
        self.assertEqual(out['records'][1]['introduced_by'],'O1')
        self.assertEqual(out['records'][1]['thread_ids'],[])
        self.assertEqual(out['events'][1]['record_id'],'R_O1_1')

    def test_invalid_record_event_pair_cannot_replace_work(self):
        p=payload();raw=patch_for(p);raw['targets']['target_1']['record']['kind']='context_only'
        m,_,ledger,_=ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            pipe=ContextV4Pipeline(V3Client(),Path(tmp),{})
            with self.assertRaisesRegex(ValueError,'Closed record'):
                pipe.interpret(expand_patch(raw,p),ledger,[],m,{'tasks':[]},True)


class V4Client(V3Client):
    def call(self,prompt,payload,stage,**kwargs):
        if stage=='check_work':
            raw=check_response(payload['records'],payload['events']);raw.pop('coverage_findings')
            raw.update(new_work_findings=[],uncertain_findings=[])
            return raw
        return super().call(prompt,payload,stage,**kwargs)


class V4PipelineTests(unittest.TestCase):
    def test_missing_second_work_is_added_and_finding_closed(self):
        class Client(V4Client):
            def call(self,prompt,p,stage,**kwargs):
                if stage=='check_work':
                    raw=super().call(prompt,p,stage,**kwargs)
                    raw['new_work_findings']=[dict(description='发送第二份材料',evidence=['Q1'])]
                    return raw
                if stage=='repair_work':
                    bundle=patch_for(payload())['targets']['target_1']
                    bundle['record']['description']='发送第二份材料';bundle['event']['candidate_ids']=[]
                    return dict(case_id='M',scope=p['repair_scope'],targets={},additions={'O1':[bundle]},
                        dispositions=[dict(finding_id='O1',disposition='added',record_ids=['R_O1_1'],evidence=['Q1'])])
                if stage=='check_repair':
                    raw=check_response(p['records'],p['events']);raw.pop('coverage_findings')
                    raw['disposition_checks']=[dict(**d,verdict='supported',reason='另一工作已补入') for d in p['dispositions']]
                    return raw
                return super().call(prompt,p,stage,**kwargs)
        m,*_=ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            out=ContextV4Pipeline(Client(),Path(tmp),{}).run(m,{'tasks':[]})
        self.assertEqual(out['trace']['repair']['status'],'checked')
        self.assertEqual(out['coverage_findings'],[])
        self.assertEqual(len(reduce_v3(out,m,{'tasks':[]})['items']),2)
        self.assertEqual([r['record_id'] for r in out['checked_records']],['R1','R_O1_1'])

    def test_normal_pipeline_preserves_execution(self):
        m,*_=ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            pipe=ContextV4Pipeline(V4Client(),Path(tmp),{})
            out=pipe.run(m,{'tasks':[]})
        self.assertEqual(out['errors'],[])
        self.assertEqual(reduce_v3(out,m,{'tasks':[]})['items'][0]['operation'],'create')

    def test_repair_roundtrip_applies_description_and_rechecks(self):
        class Client(V4Client):
            def call(self,prompt,p,stage,**kwargs):
                if stage=='check_work':
                    raw=super().call(prompt,p,stage,**kwargs)
                    raw['record_checks'][0]['content']['missing_details']=[dict(description='补回必要目的',evidence=['Q1'])]
                    return raw
                if stage=='repair_work':
                    allowed=p['output_schema']['properties']['targets']['properties']['target_1']['properties']['event']['properties']['time']['properties']['kind']['enum']
                    if 'deadline' not in allowed:raise ValueError('Missing supported deadline option')
                    raw=patch_for(p);raw['scope']=p['repair_scope']
                    raw['targets']['target_1']['record']['description']='补回必要目的'
                    return raw
                if stage=='check_repair':
                    raw=check_response(p['records'],p['events']);raw.pop('coverage_findings');raw['disposition_checks']=[]
                    return raw
                return super().call(prompt,p,stage,**kwargs)
        m,*_=ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            out=ContextV4Pipeline(Client(),Path(tmp),{}).run(m,{'tasks':[]})
        self.assertEqual(out['trace']['repair']['status'],'checked')
        self.assertEqual(reduce_v3(out,m,{'tasks':[]})['items'][0]['description'],'补回必要目的')

    def test_service_strategy_executes_and_is_idempotent(self):
        from unittest.mock import patch
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        client=V4Client();m,*_=ledger_fixture()
        m.update(account_map={'alice':'alice'},audience=['host','alice'],writers=['host'])
        def call(_client,prompt,payload,stage,*args,**kwargs):
            if stage=='facts':return dict(facts=[],unresolved=[])
            if stage=='decisions':return dict(decisions=[])
            return client.call(prompt,payload,stage,**kwargs)
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.ModelClient.call',call):
            store=Store(Path(tmp)/'state.sqlite')
            try:
                extractor=Extractor(None,Path(tmp)/'model','context-v4')
                svc=Service(store,extractor);first=svc.process(m,'host','2026-11-15T00:00:00+08:00')
                second=svc.process(m,'host','2026-11-15T00:00:00+08:00')
                self.assertEqual(first['status'],'processed');self.assertEqual(len(store.tasks()),1)
                self.assertEqual(first['source_id'],second['source_id'])
            finally:store.close()
